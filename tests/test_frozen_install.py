"""Focused BM-022 frozen-install transaction and exact-artifact tests."""

import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib.artifacts import ArtifactStore
from resources.lib.build_manager import (
    ActionExecutionResult,
    ActionFailureDiagnostic,
    ReconcileFailure,
    ReconcilePhase,
    ReconcileResult,
)
from resources.lib.frozen import (
    AddonCaptureNode,
    CaptureStatus,
    DependencyEdge,
    FrozenBuildManifest,
    ProvenanceStatus,
)
from resources.lib.frozen_install import (
    FrozenInstallCoordinator,
    FrozenInstallPhase,
    FrozenInstallStore,
    FrozenInstallTransaction,
    FrozenInstallValidationError,
    FrozenLifecycleStage,
    FrozenInstalledAddon,
    InMemoryFrozenArtifactBackend,
    KodiRuntimeFrozenArtifactBackend,
    active_activation_hold_ids,
    ensure_frozen_install_guard,
    run_frozen_install_startup,
    validate_frozen_manifest,
)
from resources.lib.startup import StartupClassification, StartupStatus
from resources.lib.update_guard import AddonUpdatePolicy, UpdatePolicyBackend
from resources.lib.planner import PlanAction, SET_SKIN
from resources.lib.skin import SkinFailureCode, SkinResult, SkinStatus


SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"


def _zip(addon_id, version, *, requires=(), repository=False):
    buf = io.BytesIO()
    requires_xml = "".join(
        f'<import addon="{addon}" version="{minimum}"/>'
        for addon, minimum in requires
    )
    extensions = (
        '<extension point="xbmc.addon.repository">'
        '<dir><info>http://127.0.0.1:9999/addons.xml</info>'
        '<datadir zip="true">http://127.0.0.1:9999/</datadir></dir>'
        '</extension>'
        if repository else
        '<extension point="xbmc.python.pluginsource" library="default.py"/>'
    )
    xml = (
        f'<addon id="{addon_id}" name="{addon_id}" version="{version}">\n'
        f'  <requires>{requires_xml}</requires>{extensions}\n'
        '</addon>\n'
    ).encode()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{addon_id}/addon.xml", xml)
        archive.writestr(f"{addon_id}/default.py", b"# BM-022 fixture\n")
    return buf.getvalue()


class FakePolicy(UpdatePolicyBackend):
    def __init__(self, policy=AddonUpdatePolicy.AUTOMATIC):
        self.policy = policy
        self.calls = []
        self.fail_after = None

    def get_policy(self):
        return self.policy

    def set_policy(self, policy):
        self.calls.append(AddonUpdatePolicy(policy))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise RuntimeError("policy mutation failed")
        self.policy = AddonUpdatePolicy(policy)


class InMemoryRegistryBackend:
    def __init__(self, installer):
        self.installer = installer
        self.refresh_calls = 0

    def get_addon_details(self, addon_id):
        return self.installer.get_addon_details(addon_id)

    def refresh_local_addons(self):
        self.refresh_calls += 1


class FrozenInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.store = FrozenInstallStore(self.root / "transaction")
        self.policy = FakePolicy(AddonUpdatePolicy.NOTIFY_ONLY)
        self.backend = InMemoryFrozenArtifactBackend()

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self, *, complete=True, cycle=False, optional_missing=False):
        dep_id = "script.module.bm022.dep"
        app_id = "plugin.video.bm022.fixture"
        repo_id = "repository.bm022.fixture"
        dep_zip = _zip(dep_id, "1.0.0")
        if cycle:
            dep_zip = _zip(dep_id, "1.0.0", requires=((app_id, "1.0.0"),))
        app_zip = _zip(app_id, "1.0.0", requires=((dep_id, "1.0.0"),))
        repo_zip = _zip(repo_id, "1.0.0", repository=True)
        dep_meta = self.artifacts.import_zip(
            dep_zip, expected_addon_id=dep_id, expected_version="1.0.0", source="test"
        )
        app_meta = self.artifacts.import_zip(
            app_zip, expected_addon_id=app_id, expected_version="1.0.0", source="test"
        )
        repo_meta = self.artifacts.import_zip(
            repo_zip, expected_addon_id=repo_id, expected_version="1.0.0", source="test"
        )
        dep_edges = (
            (DependencyEdge(app_id, "1.0.0", False, (dep_id,)),)
            if cycle else ()
        )
        app_edges = (
            (DependencyEdge("script.module.bm022.optional", "", True, (app_id,)),)
            if optional_missing
            else (DependencyEdge(dep_id, "1.0.0", False, (app_id,)),)
        )
        nodes = (
            AddonCaptureNode(
                repo_id, "1.0.0", "xbmc.addon.repository", False,
                ProvenanceStatus.VERIFIED_REPOSITORY, artifact=repo_meta,
            ),
            AddonCaptureNode(
                dep_id, "1.0.0", "xbmc.python.module", True,
                ProvenanceStatus.VERIFIED_REPOSITORY, artifact=dep_meta,
                dependency_edges=dep_edges,
            ),
            AddonCaptureNode(
                app_id, "1.0.0", "xbmc.python.pluginsource", True,
                ProvenanceStatus.VERIFIED_REPOSITORY, artifact=app_meta,
                dependency_edges=app_edges,
            ),
            AddonCaptureNode(
                "xbmc.python", "3.0.1", "system", True,
                ProvenanceStatus.UNKNOWN, system=True,
            ),
        )
        if optional_missing:
            nodes += (
                AddonCaptureNode(
                    "script.module.bm022.optional", "", "", False,
                    ProvenanceStatus.UNKNOWN,
                    optional=True,
                    status=CaptureStatus.MISSING,
                ),
            )
        if not complete:
            nodes = tuple(
                AddonCaptureNode(
                    node.addon_id, node.version, node.addon_type,
                    node.desired_enabled, node.provenance,
                    artifact=None, status=CaptureStatus.INCOMPLETE_ARTIFACT,
                    system=node.system,
                ) if node.addon_id == app_id else node
                for node in nodes
            )
        return FrozenBuildManifest(
            schema_version=1,
            build_id="bm022-fixture",
            name="BM-022 fixture",
            created_at="2026-09-21T00:00:00Z",
            kodi_version="21.1",
            platform="macos",
            capture_status=CaptureStatus.COMPLETE,
            addons=nodes,
        )

    def _coordinator(self, **kwargs):
        kwargs.setdefault("registry_backend", InMemoryRegistryBackend(self.backend))
        return FrozenInstallCoordinator(
            store=self.store,
            artifact_store=self.artifacts,
            policy_backend=self.policy,
            installer=self.backend,
            session_id_provider=lambda: SESSION_A,
            **kwargs,
        )

    def test_manifest_round_trip_and_topological_order(self):
        manifest = self._manifest()
        decoded = FrozenBuildManifest.from_json(manifest.to_json())
        plan = validate_frozen_manifest(decoded, self.artifacts)
        self.assertEqual(
            [node.addon_id for node in plan.install_order],
            [
                "repository.bm022.fixture",
                "script.module.bm022.dep",
                "plugin.video.bm022.fixture",
            ],
        )

    def test_system_dependencies_are_not_installed(self):
        plan = validate_frozen_manifest(self._manifest(), self.artifacts)
        self.assertNotIn("xbmc.python", [node.addon_id for node in plan.install_order])

    def test_kodi_state_result_string_is_verified_by_readback(self):
        backend = KodiRuntimeFrozenArtifactBackend()
        backend._rpc = lambda _method, _params: {"result": "OK"}
        backend._wait_for_details = lambda addon_id: FrozenInstalledAddon(
            addon_id, "1.0.0", False
        )
        result = backend.set_addon_enabled("script.module.fixture", False)
        self.assertEqual(result.addon_id, "script.module.fixture")
        self.assertFalse(result.enabled)

    def test_optional_dependency_absent_at_capture_is_not_installed(self):
        manifest = self._manifest(optional_missing=True)
        decoded = FrozenBuildManifest.from_json(manifest.to_json())
        plan = validate_frozen_manifest(decoded, self.artifacts)
        self.assertIn("script.module.bm022.optional", plan.nodes)
        self.assertNotIn(
            "script.module.bm022.optional",
            [node.addon_id for node in plan.install_order],
        )

    def test_incomplete_manifest_is_rejected_before_mutation(self):
        result = self._coordinator().install(
            self._manifest(complete=False),
            manifest_path="/fixture.json",
            device_profile_id="test",
        )
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(self.backend.install_calls, [])
        self.assertIsNone(self.store.inspect())

    def test_required_dependency_missing_is_rejected(self):
        manifest = self._manifest()
        altered = FrozenBuildManifest(
            schema_version=manifest.schema_version,
            build_id=manifest.build_id,
            name=manifest.name,
            created_at=manifest.created_at,
            kodi_version=manifest.kodi_version,
            platform=manifest.platform,
            capture_status=manifest.capture_status,
            addons=tuple(
                replace(
                    node,
                    dependency_edges=(
                        (DependencyEdge("missing.required.dep", "1.0.0"),)
                        if node.addon_id == "plugin.video.bm022.fixture"
                        else node.dependency_edges
                    ),
                )
                for node in manifest.addons
                if node.addon_id != "script.module.bm022.dep"
            ),
        )
        with self.assertRaises(FrozenInstallValidationError):
            validate_frozen_manifest(altered, self.artifacts)

    def test_dependency_cycle_fails_safely(self):
        with self.assertRaises(FrozenInstallValidationError):
            validate_frozen_manifest(self._manifest(cycle=True), self.artifacts)

    def test_complete_install_restores_policy_and_clears_transaction(self):
        calls = []

        def configure(request):
            calls.append(request)
            return SimpleNamespace(outcome="complete")

        result = self._coordinator(configuration_runner=configure).install(
            self._manifest(),
            manifest_path="/fixture.json",
            device_profile_id="test",
        )
        self.assertEqual(result.outcome, "complete")
        self.assertIsNone(self.store.inspect())
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NOTIFY_ONLY)
        self.assertEqual(
            self.backend.install_calls,
            [
                "repository.bm022.fixture",
                "script.module.bm022.dep",
                "plugin.video.bm022.fixture",
            ],
        )
        self.assertEqual(calls[0].manifest_path, "/fixture.json")
        self.assertFalse(self.backend.installed["repository.bm022.fixture"].enabled)
        self.assertTrue(self.backend.installed["plugin.video.bm022.fixture"].enabled)

    def test_already_exact_version_is_idempotent(self):
        manifest = self._manifest()
        self.backend.installed["repository.bm022.fixture"] = FrozenInstalledAddon(
            "repository.bm022.fixture", "1.0.0", False
        )
        result = self._coordinator().install(
            manifest, manifest_path="/fixture.json", device_profile_id="test"
        )
        self.assertEqual(result.outcome, "complete")
        self.assertNotIn("repository.bm022.fixture", self.backend.install_calls)

    def test_wrong_installed_version_fails_closed(self):
        self.backend.installed["repository.bm022.fixture"] = FrozenInstalledAddon(
            "repository.bm022.fixture", "2.0.0", True
        )
        result = self._coordinator().install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="test"
        )
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(self.store.inspect().phase, FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)

    def test_hash_tampering_fails_before_install(self):
        manifest = self._manifest()
        node = next(
            node for node in manifest.addons
            if node.addon_id == "plugin.video.bm022.fixture"
        )
        self.artifacts.artifact_path(node.artifact.sha256).write_bytes(b"tampered")
        result = self._coordinator().install(
            manifest, manifest_path="/fixture.json", device_profile_id="test"
        )
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(self.backend.install_calls, [])

    def test_guard_failure_prevents_software_mutation_and_preserves_attention(self):
        self.policy.fail_after = 0
        result = self._coordinator().install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="test"
        )
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(self.backend.install_calls, [])
        self.assertEqual(self.store.inspect().phase, FrozenInstallPhase.NEEDS_ATTENTION)

    def test_configuration_failure_keeps_quarantine_and_transaction(self):
        fake_exception = "BM017F_FAKE_STAGE_EXCEPTION_SECRET_4831"
        diagnostic = ActionFailureDiagnostic(
            "PRIVATE_RESOURCE_INITIALIZATION_FAILED",
            "plugin.video.redlight",
            "redlight.settings",
            "DATABASE_OPEN_FAILED",
            "OPEN_SETTINGS_DATABASE",
            "CREATE_DATABASE_DIRECTORY",
            "MODULE_SOURCE_MISMATCH",
            "requests.packages.urllib3.exceptions",
            "script.module.urllib3",
            "script.module.requests",
        )
        reconcile_result = SimpleNamespace(
            failure=SimpleNamespace(
                phase=SimpleNamespace(value="execute"),
                code="ACTION_FAILED",
                message=fake_exception,
            ),
            action_results=(SimpleNamespace(
                action=SimpleNamespace(kind="configure", addon_id=""),
                succeeded=False,
                owner_result=diagnostic,
            ),),
        )
        configuration_result = SimpleNamespace(
            outcome="failed",
            failure=None,
            reconcile_result=reconcile_result,
            private_overlay=None,
        )
        result = self._coordinator(
            configuration_runner=lambda _request: configuration_result
        ).install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="test"
        )
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        transaction = self.store.inspect()
        self.assertIsNotNone(transaction)
        self.assertEqual(
            transaction.status_code, "FROZEN_CONFIGURATION_ACTION_FAILED"
        )
        self.assertIn("action=CONFIGURE", transaction.status_message)
        self.assertIn("resource_failure=PRIVATE_RESOURCE_INITIALIZATION_FAILED", transaction.status_message)
        self.assertIn("owner=plugin.video.redlight", transaction.status_message)
        self.assertIn("resource=redlight.settings", transaction.status_message)
        self.assertIn("cause=DATABASE_OPEN_FAILED", transaction.status_message)
        self.assertIn("initialization_stage=OPEN_SETTINGS_DATABASE", transaction.status_message)
        self.assertIn("last_completed_stage=CREATE_DATABASE_DIRECTORY", transaction.status_message)
        self.assertIn("import_failure_category=MODULE_SOURCE_MISMATCH", transaction.status_message)
        self.assertIn(
            "failing_module=requests.packages.urllib3.exceptions",
            transaction.status_message,
        )
        self.assertIn("expected_provider=script.module.urllib3", transaction.status_message)
        self.assertIn("actual_provider=script.module.requests", transaction.status_message)
        self.assertNotIn(fake_exception, transaction.status_message)

    def test_skin_failure_code_is_persisted_without_raw_result_text(self):
        fake_secret = "/private/fake/profile/secret-token BM023A_FAILURE_TEXT"
        skin_result = SkinResult(
            "skin.arctic.fuse.3",
            SkinStatus.FAILED,
            "skin.estuary",
            f"unsafe diagnostic: {fake_secret}",
            failure_code=SkinFailureCode.TARGET_SKIN_NOT_ACTIVE,
        )
        action = ActionExecutionResult(
            action=PlanAction(
                SET_SKIN, "skin.arctic.fuse.3", "active", "skin.estuary",
                "skin activation required",
            ),
            succeeded=False,
            changed=False,
            message=skin_result.message,
            owner_result=skin_result,
        )
        reconcile = ReconcileResult(
            success=False,
            request=None,
            desired_fingerprint=None,
            action_results=(action,),
            failure=ReconcileFailure(
                ReconcilePhase.EXECUTE, "ACTION_FAILED", fake_secret
            ),
        )
        configuration_result = SimpleNamespace(
            outcome="failed",
            failure=None,
            reconcile_result=reconcile,
            private_overlay=None,
        )

        result = self._coordinator(
            configuration_runner=lambda _request: configuration_result
        ).install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="test"
        )

        self.assertEqual(result.outcome, "needs_attention")
        transaction = self.store.inspect()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.phase, FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertEqual(
            transaction.status_code, "FROZEN_CONFIGURATION_ACTION_FAILED"
        )
        self.assertIn("action=SET_SKIN", transaction.status_message)
        self.assertIn("addon=skin.arctic.fuse.3", transaction.status_message)
        self.assertIn(
            "skin_failure_code=TARGET_SKIN_NOT_ACTIVE",
            transaction.status_message,
        )
        self.assertNotIn(fake_secret, transaction.status_message)
        self.assertNotIn("/private/", transaction.status_message)
        self.assertNotIn("BM023A_FAILURE_TEXT", transaction.status_message)

    def test_restart_boundary_reasserts_and_finalizes(self):
        restart = SimpleNamespace(
            outcome="manual_restart_required",
            transaction=SimpleNamespace(
                transaction_id="33333333-3333-4333-8333-333333333333"
            ),
        )
        result = self._coordinator(
            configuration_runner=lambda _request: restart
        ).install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="test"
        )
        self.assertEqual(result.outcome, "awaiting_restart")
        self.policy.policy = AddonUpdatePolicy.AUTOMATIC
        resumed = FrozenInstallCoordinator(
            store=self.store,
            artifact_store=self.artifacts,
            policy_backend=self.policy,
            installer=self.backend,
            manifest_loader=lambda _path: self._manifest(),
            session_id_provider=lambda: SESSION_B,
        ).resume_after_restart()
        self.assertEqual(resumed.outcome, "complete", (resumed.code, resumed.message))
        self.assertIsNone(self.store.inspect())
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NOTIFY_ONLY)

    def test_preexisting_lifecycle_owner_stays_held_until_verified_resume(self):
        manifest = self._manifest()
        owner_id = "plugin.video.bm022.fixture"
        self.backend.installed[owner_id] = FrozenInstalledAddon(owner_id, "1.0.0", True)
        from resources.lib.private_overlay import PrivateOverlayMetadata
        from resources.lib.redlight_resource import redlight_declaration

        overlay_meta = PrivateOverlayMetadata(
            "fixture-overlay", "sha256:" + "2" * 64, True, True
        )
        declaration = replace(redlight_declaration(), owner_addon_id=owner_id)
        profile = SimpleNamespace(
            frozen_install_policies=(),
            private_overlay=SimpleNamespace(overlay_id="fixture-overlay"),
            build=SimpleNamespace(id="bm022-fixture"),
            config=SimpleNamespace(
                private_settings=(), structured_private_resources=(declaration,)
            ),
        )

        def configuration_runner(_request):
            private_result = SimpleNamespace(
                succeeded=True,
                resource_results=(SimpleNamespace(succeeded=True),),
            )
            reconcile = SimpleNamespace(
                success=True,
                action_results=(SimpleNamespace(
                    owner_result=SimpleNamespace(private_result=private_result),
                ),),
                private_overlay=overlay_meta,
            )
            return SimpleNamespace(outcome="complete", reconcile_result=reconcile)

        metadata_provider = lambda _profile, _fingerprint: (
            overlay_meta.overlay_id,
            overlay_meta.fingerprint,
            overlay_meta.required,
        )
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ):
            first = self._coordinator(
                configuration_runner=configuration_runner,
                private_overlay_metadata_provider=metadata_provider,
            ).install(
                manifest,
                manifest_path="/fixture-frozen.json",
                configuration_manifest_path="/fixture-config.json",
                device_profile_id="test",
                interactive=False,
            )
            self.assertEqual(first.outcome, "awaiting_restart")
            transaction = self.store.inspect()
            self.assertEqual(
                transaction.lifecycle_stage,
                FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            )
            self.assertFalse(transaction.activation_hold_released)
            self.assertEqual(transaction.private_overlay_id, overlay_meta.overlay_id)
            self.assertEqual(active_activation_hold_ids(self.store), frozenset({owner_id}))
            self.assertFalse(self.backend.installed[owner_id].enabled)
            self.assertEqual(self.backend.install_calls, [])
            self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
            abandoned = self._coordinator().abandon()
            self.assertEqual(abandoned.outcome, "needs_attention")
            self.assertEqual(active_activation_hold_ids(self.store), frozenset({owner_id}))

            resumed = FrozenInstallCoordinator(
                store=self.store,
                artifact_store=self.artifacts,
                policy_backend=self.policy,
                installer=self.backend,
                manifest_loader=lambda _path: manifest,
                session_id_provider=lambda: SESSION_B,
                configuration_runner=configuration_runner,
                registry_backend=InMemoryRegistryBackend(self.backend),
                private_overlay_metadata_provider=metadata_provider,
            ).resume_after_restart(current_session_id=SESSION_B)

        self.assertEqual(resumed.outcome, "complete", (resumed.code, resumed.message))
        self.assertIsNone(self.store.inspect())
        self.assertTrue(self.backend.installed[owner_id].enabled)
        self.assertEqual(active_activation_hold_ids(self.store), frozenset())
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NOTIFY_ONLY)

    def test_new_lifecycle_owner_crosses_restart_before_configuration(self):
        manifest = self._manifest()
        owner_id = "plugin.video.bm022.fixture"
        from resources.lib.private_overlay import PrivateOverlayMetadata
        from resources.lib.redlight_resource import redlight_declaration

        overlay_meta = PrivateOverlayMetadata(
            "fixture-overlay", "sha256:" + "3" * 64, True, True
        )
        declaration = replace(redlight_declaration(), owner_addon_id=owner_id)
        profile = SimpleNamespace(
            frozen_install_policies=(),
            private_overlay=SimpleNamespace(overlay_id="fixture-overlay"),
            build=SimpleNamespace(id="bm022-fixture"),
            config=SimpleNamespace(
                private_settings=(), structured_private_resources=(declaration,)
            ),
        )
        configured = []

        def configuration_runner(_request):
            configured.append(True)
            private_result = SimpleNamespace(
                succeeded=True,
                resource_results=(SimpleNamespace(succeeded=True),),
            )
            reconcile = SimpleNamespace(
                success=True,
                action_results=(SimpleNamespace(
                    owner_result=SimpleNamespace(private_result=private_result),
                ),),
                private_overlay=overlay_meta,
            )
            return SimpleNamespace(outcome="complete", reconcile_result=reconcile)

        metadata_provider = lambda _profile, _fingerprint: (
            overlay_meta.overlay_id,
            overlay_meta.fingerprint,
            overlay_meta.required,
        )
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ):
            first = self._coordinator(
                configuration_runner=configuration_runner,
                private_overlay_metadata_provider=metadata_provider,
            ).install(
                manifest,
                manifest_path="/fixture-frozen.json",
                configuration_manifest_path="/fixture-config.json",
                device_profile_id="test",
                interactive=False,
            )
            self.assertEqual(first.outcome, "awaiting_restart")
            transaction = self.store.inspect()
            self.assertEqual(
                transaction.lifecycle_stage,
                FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            )
            self.assertEqual(transaction.lifecycle_restart_count, 1)
            self.assertFalse(transaction.activation_hold_released)
            self.assertEqual(active_activation_hold_ids(self.store), frozenset({owner_id}))
            self.assertFalse(self.backend.installed[owner_id].enabled)
            self.assertTrue(self.backend.installed)
            self.assertEqual(configured, [])
            self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)

            resumed = FrozenInstallCoordinator(
                store=self.store,
                artifact_store=self.artifacts,
                policy_backend=self.policy,
                installer=self.backend,
                manifest_loader=lambda _path: manifest,
                session_id_provider=lambda: SESSION_B,
                configuration_runner=configuration_runner,
                registry_backend=InMemoryRegistryBackend(self.backend),
                private_overlay_metadata_provider=metadata_provider,
            ).resume_after_restart(current_session_id=SESSION_B)

        self.assertEqual(resumed.outcome, "complete")
        self.assertEqual(configured, [True])
        self.assertIsNone(self.store.inspect())
        self.assertTrue(self.backend.installed[owner_id].enabled)
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NOTIFY_ONLY)

    def test_bm022_resume_gates_configuration_when_bm020_has_no_transaction(self):
        manifest = self._manifest()
        owner_id = "plugin.video.bm022.fixture"
        from resources.lib.private_overlay import PrivateOverlayMetadata
        from resources.lib.redlight_resource import redlight_declaration

        overlay_meta = PrivateOverlayMetadata(
            "fixture-overlay", "sha256:" + "4" * 64, True, True
        )
        declaration = replace(redlight_declaration(), owner_addon_id=owner_id)
        profile = SimpleNamespace(
            frozen_install_policies=(),
            private_overlay=SimpleNamespace(overlay_id="fixture-overlay"),
            build=SimpleNamespace(id="bm022-fixture"),
            config=SimpleNamespace(
                private_settings=(), structured_private_resources=(declaration,)
            ),
        )
        events = []

        class RecordingPolicy(FakePolicy):
            def get_policy(inner_self):
                events.append("read_updater_policy")
                return super(RecordingPolicy, inner_self).get_policy()

            def set_policy(inner_self, policy):
                events.append("set_updater_policy")
                return super(RecordingPolicy, inner_self).set_policy(policy)

        policy = RecordingPolicy(AddonUpdatePolicy.NOTIFY_ONLY)

        class Registry:
            def get_addon_details(inner_self, addon_id):
                events.append("query_registry")
                return self.backend.get_addon_details(addon_id)

            def refresh_local_addons(inner_self):
                self.assertEqual(
                    active_activation_hold_ids(self.store),
                    frozenset({owner_id}),
                )
                events.append("refresh_local_addons")
                self.backend.installed[owner_id] = FrozenInstalledAddon(
                    owner_id, "1.0.0", False
                )

        registry = Registry()

        def configure(_request):
            events.append("configuration_private_apply")
            private_result = SimpleNamespace(
                succeeded=True,
                resource_results=(SimpleNamespace(succeeded=True),),
            )
            reconcile = SimpleNamespace(
                success=True,
                action_results=(SimpleNamespace(
                    owner_result=SimpleNamespace(private_result=private_result),
                ),),
                private_overlay=overlay_meta,
            )
            return SimpleNamespace(outcome="complete", reconcile_result=reconcile)

        metadata_provider = lambda _profile, _fingerprint: (
            overlay_meta.overlay_id,
            overlay_meta.fingerprint,
            overlay_meta.required,
        )
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ), patch.object(
            FrozenInstallCoordinator,
            "_private_overlay_metadata",
            side_effect=lambda _profile, _fingerprint: (
                overlay_meta.overlay_id,
                overlay_meta.fingerprint,
                overlay_meta.required,
            ),
        ):
            first = FrozenInstallCoordinator(
                store=self.store,
                artifact_store=self.artifacts,
                policy_backend=policy,
                installer=self.backend,
                session_id_provider=lambda: SESSION_A,
                configuration_runner=configure,
                private_overlay_metadata_provider=metadata_provider,
            ).install(
                manifest,
                manifest_path="/fixture-frozen.json",
                configuration_manifest_path="/fixture-config.json",
                device_profile_id="test",
                interactive=False,
            )
            self.assertEqual(first.outcome, "awaiting_restart")
            transaction = self.store.inspect()
            self.assertEqual(
                transaction.lifecycle_stage,
                FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            )
            self.assertFalse(transaction.activation_hold_released)
            self.backend.installed.pop(owner_id)
            events.clear()

            bm020_status = StartupStatus(StartupClassification.NO_TRANSACTION)
            self.assertIsNone(bm020_status.transaction)
            resumed = run_frozen_install_startup(
                bm020_status=bm020_status,
                store=self.store,
                artifact_store=self.artifacts,
                policy_backend=policy,
                installer=self.backend,
                registry_backend=registry,
                manifest_loader=lambda _path: manifest,
                session_id_provider=lambda: SESSION_B,
                configuration_runner=configure,
            )

        self.assertEqual(resumed.outcome, "complete", (resumed.code, resumed.message))
        self.assertLess(events.index("set_updater_policy"), events.index("refresh_local_addons"))
        self.assertLess(events.index("read_updater_policy"), events.index("refresh_local_addons"))
        self.assertLess(events.index("refresh_local_addons"), events.index("configuration_private_apply"))
        self.assertEqual(events.count("refresh_local_addons"), 1)
        self.assertIsNone(self.store.inspect())
        self.assertEqual(policy.policy, AddonUpdatePolicy.NOTIFY_ONLY)
        self.assertTrue(self.backend.installed[owner_id].enabled)

    def test_bm022_registry_readiness_failure_keeps_hold_and_blocks_configuration(self):
        manifest = self._manifest()
        owner_id = "plugin.video.bm022.fixture"
        from resources.lib.private_overlay import PrivateOverlayMetadata
        from resources.lib.redlight_resource import redlight_declaration

        overlay_meta = PrivateOverlayMetadata(
            "fixture-overlay", "sha256:" + "5" * 64, True, True
        )
        declaration = replace(redlight_declaration(), owner_addon_id=owner_id)
        profile = SimpleNamespace(
            frozen_install_policies=(),
            private_overlay=SimpleNamespace(overlay_id="fixture-overlay"),
            build=SimpleNamespace(id="bm022-fixture"),
            config=SimpleNamespace(
                private_settings=(), structured_private_resources=(declaration,)
            ),
        )
        configured = []
        metadata_provider = lambda _profile, _fingerprint: (
            overlay_meta.overlay_id,
            overlay_meta.fingerprint,
            overlay_meta.required,
        )

        class WrongVersionRegistry:
            def __init__(inner_self):
                inner_self.refresh_calls = 0

            def get_addon_details(inner_self, addon_id):
                return FrozenInstalledAddon(addon_id, "9.9.9", False)

            def refresh_local_addons(inner_self):
                inner_self.refresh_calls += 1

        registry = WrongVersionRegistry()

        def configure(_request):
            configured.append(True)
            return SimpleNamespace(outcome="complete")

        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ), patch.object(
            FrozenInstallCoordinator,
            "_private_overlay_metadata",
            side_effect=lambda _profile, _fingerprint: (
                overlay_meta.overlay_id,
                overlay_meta.fingerprint,
                overlay_meta.required,
            ),
        ):
            first = self._coordinator(
                configuration_runner=configure,
                private_overlay_metadata_provider=metadata_provider,
            ).install(
                manifest,
                manifest_path="/fixture-frozen.json",
                configuration_manifest_path="/fixture-config.json",
                device_profile_id="test",
                interactive=False,
            )
            self.assertEqual(first.outcome, "awaiting_restart")
            resumed = FrozenInstallCoordinator(
                store=self.store,
                artifact_store=self.artifacts,
                policy_backend=self.policy,
                installer=self.backend,
                manifest_loader=lambda _path: manifest,
                session_id_provider=lambda: SESSION_B,
                configuration_runner=configure,
                registry_backend=registry,
                private_overlay_metadata_provider=metadata_provider,
            ).resume_after_restart(current_session_id=SESSION_B)

        self.assertEqual(resumed.outcome, "needs_attention")
        self.assertEqual(resumed.code, "FROZEN_ADDON_REGISTRY_WRONG_VERSION")
        self.assertEqual(configured, [])
        self.assertEqual(registry.refresh_calls, 0)
        durable = self.store.inspect()
        self.assertEqual(durable.phase, FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertEqual(
            durable.lifecycle_stage,
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
        )
        self.assertFalse(durable.activation_hold_released)
        self.assertEqual(active_activation_hold_ids(self.store), frozenset({owner_id}))

    def test_lifecycle_hold_includes_optional_managed_dependents(self):
        from resources.lib.redlight_resource import redlight_declaration

        owner_id = "plugin.video.redlight"
        dependent_id = "plugin.video.optional.consumer"
        profile = SimpleNamespace(config=SimpleNamespace(
            structured_private_resources=(redlight_declaration(),),
        ))
        owner = AddonCaptureNode(
            addon_id=owner_id,
            version="2.6.8",
            addon_type="xbmc.python.pluginsource",
            desired_enabled=True,
            provenance=ProvenanceStatus.VERIFIED_REPOSITORY,
        )
        dependent = AddonCaptureNode(
            addon_id=dependent_id,
            version="1.0.0",
            addon_type="xbmc.python.pluginsource",
            desired_enabled=True,
            provenance=ProvenanceStatus.VERIFIED_REPOSITORY,
            dependency_edges=(DependencyEdge(owner_id, optional=True),),
        )
        plan = SimpleNamespace(install_order=(owner, dependent))

        self.assertEqual(
            FrozenInstallCoordinator._activation_hold_ids(plan, profile),
            tuple(sorted((owner_id, dependent_id))),
        )

    def test_startup_reasserts_guard_before_resume(self):
        transaction = FrozenInstallTransaction(
            transaction_id="33333333-3333-4333-8333-333333333333",
            build_id="bm022-fixture",
            manifest_path="/fixture.json",
            device_profile_id="test",
            manifest_fingerprint="a" * 64,
            phase=FrozenInstallPhase.AWAITING_RESTART,
            originating_kodi_session_id=SESSION_A,
            original_update_policy=AddonUpdatePolicy.AUTOMATIC,
            created_at="2026-09-21T00:00:00Z",
            updated_at="2026-09-21T00:00:00Z",
        )
        self.store.create(transaction)
        status = ensure_frozen_install_guard(
            store=self.store, policy_backend=self.policy
        )
        self.assertTrue(status.allowed)
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)

    def test_activation_hold_persists_across_attention_until_explicit_release(self):
        transaction = FrozenInstallTransaction(
            transaction_id="33333333-3333-4333-8333-333333333333",
            build_id="bm022-fixture",
            manifest_path="/fixture.json",
            device_profile_id="test",
            manifest_fingerprint="a" * 64,
            phase=FrozenInstallPhase.AWAITING_RESTART,
            originating_kodi_session_id=SESSION_A,
            original_update_policy=AddonUpdatePolicy.AUTOMATIC,
            created_at="2026-09-21T00:00:00Z",
            updated_at="2026-09-21T00:00:00Z",
            configuration_manifest_path="/configuration.json",
            lifecycle_stage=FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            activation_hold_ids=("plugin.video.redlight",),
            activation_hold_released=False,
            lifecycle_restart_count=1,
        )
        self.store.create(transaction)
        self.assertEqual(
            active_activation_hold_ids(self.store),
            frozenset({"plugin.video.redlight"}),
        )
        attention = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=FrozenInstallPhase.AWAITING_RESTART,
            new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
            status_code="TEST_HOLD",
        )
        self.assertFalse(attention.activation_hold_released)
        self.assertEqual(
            active_activation_hold_ids(self.store),
            frozenset({"plugin.video.redlight"}),
        )
        released = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=FrozenInstallPhase.NEEDS_ATTENTION,
            new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
            lifecycle_stage=FrozenLifecycleStage.ACTIVATION_RELEASED,
            activation_hold_released=True,
        )
        self.assertTrue(released.activation_hold_released)
        self.assertEqual(active_activation_hold_ids(self.store), frozenset())

    def test_reassert_failure_transitions_attention(self):
        transaction = FrozenInstallTransaction(
            transaction_id="33333333-3333-4333-8333-333333333333",
            build_id="bm022-fixture",
            manifest_path="/fixture.json",
            device_profile_id="test",
            manifest_fingerprint="a" * 64,
            phase=FrozenInstallPhase.AWAITING_RESTART,
            originating_kodi_session_id=SESSION_A,
            original_update_policy=AddonUpdatePolicy.AUTOMATIC,
            created_at="2026-09-21T00:00:00Z",
            updated_at="2026-09-21T00:00:00Z",
        )
        self.store.create(transaction)
        self.policy.fail_after = 0
        status = ensure_frozen_install_guard(
            store=self.store, policy_backend=self.policy
        )
        self.assertFalse(status.allowed)
        self.assertEqual(self.store.inspect().phase, FrozenInstallPhase.NEEDS_ATTENTION)

    def test_explicit_abandon_restores_policy_without_rollback(self):
        restart = SimpleNamespace(
            outcome="manual_restart_required",
            transaction=SimpleNamespace(
                transaction_id="33333333-3333-4333-8333-333333333333"
            ),
        )
        self._coordinator(
            configuration_runner=lambda _request: restart
        ).install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="test"
        )
        result = self._coordinator().abandon()
        self.assertEqual(result.outcome, "complete")
        self.assertIsNone(self.store.inspect())
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NOTIFY_ONLY)
        self.assertTrue(self.backend.installed)


if __name__ == "__main__":
    unittest.main()
