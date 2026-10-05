"""Focused BM-022 frozen-install transaction and exact-artifact tests."""

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib.artifacts import ArtifactStore
from resources.lib.build_manager import (
    ActionExecutionResult,
    ActionFailureDiagnostic,
    ReconcileRequest,
    ReconcileFailure,
    ReconcilePhase,
    ReconcileResult,
)
from resources.lib.restart import RestartReport, RestartRequirement
from resources.lib.restart_coordinator import (
    RestartCapabilityResolver,
    RestartCoordinator,
)
from resources.lib.transaction import (
    RestartTransaction,
    TransactionLockBusy,
    TransactionPhase,
    TransactionStore,
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
    FrozenInstallResult,
    FrozenInstallStateConflict,
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
from resources.lib.update_guard import AddonUpdateGuard, AddonUpdatePolicy, UpdatePolicyBackend
from resources.lib.planner import CONFIGURE, PlanAction, SET_SKIN
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
        for name, data in (
            (f"{addon_id}/addon.xml", xml),
            (f"{addon_id}/default.py", b"# BM-022 fixture\n"),
        ):
            entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return buf.getvalue()


class FakePolicy(UpdatePolicyBackend):
    def __init__(self, policy=AddonUpdatePolicy.AUTOMATIC):
        self.policy = policy
        self.calls = []
        self.reads = 0
        self.fail_after = None

    def get_policy(self):
        self.reads += 1
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

    def _restart_store(self):
        return TransactionStore(str(self.root / "held-retry-profile"))

    @staticmethod
    def _bm020_transaction():
        return RestartTransaction(
            transaction_id="33333333-3333-4333-8333-333333333333",
            phase=TransactionPhase.AWAITING_RESTART,
            request=ReconcileRequest("/fixture-build.json", "test"),
            desired_state_fingerprint="sha256:" + "a" * 64,
            restart_requirement=RestartRequirement.KODI_RESTART,
            originating_kodi_session_id=SESSION_A,
            created_at="2026-09-24T00:00:00+00:00",
            updated_at="2026-09-24T00:00:00+00:00",
        )

    def _held_redlight_retry_case(self):
        from resources.lib.private_overlay import PrivateOverlayMetadata
        from resources.lib.redlight_resource import redlight_declaration

        profile_root = self.root / "held-retry-profile"
        self.store = FrozenInstallStore(
            profile_root / "addon_data" / "script.build.manager"
        )
        owner_id = "plugin.video.redlight"
        owner_zip = _zip(owner_id, "2.6.8")
        owner_meta = self.artifacts.import_zip(
            owner_zip,
            expected_addon_id=owner_id,
            expected_version="2.6.8",
            source="test",
        )
        source_store = ArtifactStore(self.root / "retained-artifacts")
        source_store.import_zip(
            owner_zip,
            expected_addon_id=owner_id,
            expected_version="2.6.8",
            source="retained",
        )
        manifest = FrozenBuildManifest(
            schema_version=1,
            build_id="bm022-held-retry-fixture",
            name="Held retry fixture",
            created_at="2026-09-24T00:00:00Z",
            kodi_version="21.3",
            platform="macos",
            capture_status=CaptureStatus.COMPLETE,
            addons=(AddonCaptureNode(
                owner_id,
                "2.6.8",
                "xbmc.python.pluginsource",
                True,
                ProvenanceStatus.VERIFIED_REPOSITORY,
                artifact=owner_meta,
            ),),
        )
        profile = SimpleNamespace(
            frozen_install_policies=(),
            private_overlay=SimpleNamespace(overlay_id="held-retry-overlay"),
            build=SimpleNamespace(id=manifest.build_id),
            config=SimpleNamespace(
                private_settings=(),
                structured_private_resources=(redlight_declaration(),),
            ),
        )
        overlay_identity = (
            "held-retry-overlay",
            "sha256:" + "8" * 64,
            False,
        )
        overlay_meta = PrivateOverlayMetadata(
            overlay_identity[0], overlay_identity[1], overlay_identity[2], True
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

        self.policy = FakePolicy(AddonUpdatePolicy.AUTOMATIC)
        self.backend.installed[owner_id] = FrozenInstalledAddon(
            owner_id, "2.6.8", True
        )
        coordinator = FrozenInstallCoordinator(
            store=self.store,
            artifact_store=self.artifacts,
            policy_backend=self.policy,
            installer=self.backend,
            manifest_loader=lambda _path: manifest,
            session_id_provider=lambda: SESSION_A,
            configuration_runner=configuration_runner,
            registry_backend=InMemoryRegistryBackend(self.backend),
            private_overlay_metadata_provider=lambda _profile, _fingerprint: overlay_identity,
        )
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ):
            initial = coordinator.install(
                manifest,
                manifest_path="/fixture-held-frozen.json",
                configuration_manifest_path="/fixture-held-config.json",
                device_profile_id="test",
                interactive=False,
            )
        self.assertEqual(initial.outcome, "awaiting_restart", (initial.code, initial.message))
        awaiting = self.store.inspect()
        self.assertEqual(
            awaiting.lifecycle_stage,
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
        )
        held = self.store.transition_expected(
            transaction_id=awaiting.transaction_id,
            expected_phase=FrozenInstallPhase.AWAITING_RESTART,
            new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
            status_code="FROZEN_MANIFEST_INVALID",
            status_message="outcome=failed; stage=frozen_manifest_validation",
        )
        coordinator.session_id_provider = lambda: SESSION_B
        for path in self.artifacts.artifacts_dir.iterdir():
            path.unlink()
        return manifest, profile, source_store, coordinator, held

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
        from resources.lib.private_overlay import PrivateOverlayMetadata

        overlay_meta = PrivateOverlayMetadata(
            "fixture-overlay", "sha256:" + "9" * 64, False, True
        )
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
            "private",
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
            private_overlay=overlay_meta,
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
        self.assertIn("configuration_scope=private", transaction.status_message)
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
        self.assertEqual(transaction.private_overlay_id, overlay_meta.overlay_id)
        self.assertEqual(
            transaction.private_overlay_fingerprint, overlay_meta.fingerprint
        )
        self.assertFalse(transaction.private_overlay_required)
        self.assertNotIn(fake_exception, transaction.status_message)

    def test_public_configure_failure_persists_scope_and_safe_cause(self):
        from resources.lib.config import (
            ConfigApplyResult,
            ConfigOperationKind,
            ConfigOperationResult,
            ConfigOperationStatus,
        )

        fake_private_text = "/private/fake/profile/PRIVATE_TOKEN_PUBLIC_FAILURE"
        public_result = ConfigApplyResult(results=(ConfigOperationResult(
            ConfigOperationKind.SETTING,
            "fixture-public-package",
            ConfigOperationStatus.FAILED,
            fake_private_text,
            fake_private_text,
            fake_private_text,
            addon_id="plugin.video.publicfixture",
            key="private.token",
        ),))
        reconcile_result = ReconcileResult(
            success=False,
            request=None,
            desired_fingerprint="a" * 64,
            action_results=(ActionExecutionResult(
                PlanAction(CONFIGURE, "", "", "", "configuration required"),
                False,
                False,
                fake_private_text,
                public_result,
            ),),
            failure=ReconcileFailure(
                ReconcilePhase.EXECUTE, "ACTION_FAILED", fake_private_text
            ),
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
        transaction = self.store.inspect()
        self.assertEqual(transaction.phase, FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertIn("action=CONFIGURE", transaction.status_message)
        self.assertIn("configuration_scope=public", transaction.status_message)
        self.assertIn(
            "cause=PUBLIC_CONFIGURATION_OPERATION_FAILED", transaction.status_message
        )
        self.assertIn("owner=plugin.video.publicfixture", transaction.status_message)
        self.assertNotIn("addon=", transaction.status_message)
        self.assertNotIn("configuration_scope=private", transaction.status_message)
        self.assertNotIn("private.token", transaction.status_message)
        self.assertNotIn(fake_private_text, json.dumps(transaction.to_dict()))

    def test_example_redlight_declaration_establishes_activation_hold(self):
        from resources.lib.manifest import load_manifest_file
        from resources.lib.resolver import resolve_manifest

        example_path = (
            Path(__file__).resolve().parents[1]
            / "resources/builds/examples/eric-main.example.json"
        )
        desired = resolve_manifest(
            load_manifest_file(str(example_path)), "bonus-room"
        )
        owner = AddonCaptureNode(
            "plugin.video.redlight",
            "2.6.8",
            "xbmc.python.pluginsource",
            True,
            ProvenanceStatus.VERIFIED_REPOSITORY,
        )
        plan = SimpleNamespace(install_order=(owner,))

        self.assertEqual(
            FrozenInstallCoordinator._activation_hold_ids(plan, desired),
            ("plugin.video.redlight",),
        )

    def test_configuration_failure_after_restart_keeps_redlight_held(self):
        from resources.lib.private_overlay import PrivateOverlayMetadata
        from resources.lib.redlight_resource import redlight_declaration

        manifest = self._manifest()
        owner_id = "plugin.video.bm022.fixture"
        overlay_meta = PrivateOverlayMetadata(
            "fixture-overlay", "sha256:" + "8" * 64, False, True
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
        fake_secret = "/private/fake/profile/PRIVATE_TOKEN_4721"
        diagnostic = ActionFailureDiagnostic(
            "PRIVATE_RESOURCE_INITIALIZATION_FAILED",
            owner_id,
            "redlight.settings",
            "DATABASE_OPEN_FAILED",
            "OPEN_SETTINGS_DATABASE",
            "CREATE_DATABASE_DIRECTORY",
            configuration_scope="private",
        )
        action_result = ActionExecutionResult(
            PlanAction(CONFIGURE, "", "", "", "fixture action"),
            False,
            False,
            fake_secret,
            diagnostic,
        )

        def configure(request):
            reconcile = ReconcileResult(
                success=False,
                request=request,
                desired_fingerprint="a" * 64,
                action_results=(action_result,),
                failure=ReconcileFailure(
                    ReconcilePhase.EXECUTE, "ACTION_FAILED", fake_secret
                ),
                private_overlay=overlay_meta,
            )
            return SimpleNamespace(
                outcome="failed",
                failure=None,
                reconcile_result=reconcile,
            )

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
            self.assertFalse(self.backend.installed[owner_id].enabled)
            resumed = FrozenInstallCoordinator(
                store=self.store,
                artifact_store=self.artifacts,
                policy_backend=self.policy,
                installer=self.backend,
                manifest_loader=lambda _path: manifest,
                session_id_provider=lambda: SESSION_B,
                configuration_runner=configure,
                registry_backend=InMemoryRegistryBackend(self.backend),
                private_overlay_metadata_provider=metadata_provider,
            ).resume_after_restart(current_session_id=SESSION_B)

        self.assertEqual(resumed.outcome, "needs_attention")
        transaction = self.store.inspect()
        self.assertEqual(transaction.phase, FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertEqual(
            transaction.lifecycle_stage, FrozenLifecycleStage.CONFIGURING
        )
        self.assertFalse(transaction.activation_hold_released)
        self.assertEqual(
            active_activation_hold_ids(self.store), frozenset({owner_id})
        )
        self.assertFalse(self.backend.installed[owner_id].enabled)
        self.assertEqual(transaction.private_overlay_id, overlay_meta.overlay_id)
        self.assertEqual(
            transaction.private_overlay_fingerprint, overlay_meta.fingerprint
        )
        self.assertFalse(transaction.private_overlay_required)
        self.assertNotIn(fake_secret, transaction.status_message)
        self.assertNotIn(fake_secret, json.dumps(transaction.to_dict()))

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

    def test_restart_boundary_verifies_persisted_quarantine_and_finalizes(self):
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
        # Kodi persisted the quarantine across the restart: NEVER_CHECK stands.
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        self.assertEqual(self.policy.calls, [AddonUpdatePolicy.NEVER_CHECK])
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
        # After the restart the only write is the terminal restore of the original.
        self.assertEqual(
            self.policy.calls,
            [AddonUpdatePolicy.NEVER_CHECK, AddonUpdatePolicy.NOTIFY_ONLY],
        )

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
        self.assertLess(events.index("read_updater_policy"), events.index("refresh_local_addons"))
        self.assertLess(events.index("refresh_local_addons"), events.index("configuration_private_apply"))
        # The restart is verify-only: the single post-restart write is the terminal
        # restore, which happens after the refresh and the private configuration.
        self.assertEqual(events.count("set_updater_policy"), 1)
        self.assertLess(events.index("configuration_private_apply"), events.index("set_updater_policy"))
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

    def test_startup_verifies_persisted_quarantine_without_writing(self):
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
        self.policy.policy = AddonUpdatePolicy.NEVER_CHECK  # as persisted by Kodi
        status = ensure_frozen_install_guard(
            store=self.store, policy_backend=self.policy
        )
        self.assertTrue(status.allowed)
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        self.assertEqual(self.policy.calls, [])
        self.assertEqual(self.store.inspect(), transaction)

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

    def test_held_retry_runs_real_continuation_under_bm020_lock(self):
        manifest, profile, source_store, coordinator, held = (
            self._held_redlight_retry_case()
        )
        events = []
        restart_store = self._restart_store()
        original_set_policy = self.policy.set_policy
        original_read_bytes = source_store.read_bytes
        original_rearm = self.store.rearm_held_quiescence
        original_restart_inspect = restart_store.inspect
        original_locked_access = restart_store.locked_access
        original_transition = self.store.transition_expected
        original_clear = self.store.clear_expected
        original_registry_query = coordinator.registry_backend.get_addon_details
        original_configuration_runner = coordinator.configuration_runner
        original_resume = coordinator.resume_after_restart
        rearmed_snapshots = []
        issued_transaction_access = []

        def set_policy(policy):
            policy = AddonUpdatePolicy(policy)
            events.append(("policy", policy))
            return original_set_policy(policy)

        def read_bytes(sha256):
            events.append("artifact_stage")
            return original_read_bytes(sha256)

        def inspect_bm020():
            events.append("bm020_inspect")
            return original_restart_inspect()

        @contextmanager
        def locked_access():
            events.append("bm020_lock_acquired")
            try:
                with original_locked_access() as access:
                    issued_transaction_access.append(access)
                    yield access
            finally:
                events.append("bm020_lock_released")

        def rearm(expected):
            events.append("cas")
            snapshot = original_rearm(expected)
            rearmed_snapshots.append(snapshot)
            return snapshot

        def transition(**kwargs):
            stage = kwargs.get("lifecycle_stage")
            if stage in (
                FrozenLifecycleStage.PRIVATE_VERIFIED,
                FrozenLifecycleStage.ACTIVATION_RELEASED,
            ):
                events.append(stage.value)
            return original_transition(**kwargs)

        def clear_expected(**kwargs):
            events.append("frozen_transaction_cleared")
            return original_clear(**kwargs)

        def check_registry(addon_id):
            events.append("registry_check")
            return original_registry_query(addon_id)

        class FixtureBuildManager:
            def reconcile(_self, request):
                events.append("configuration_reconcile")
                fixture_result = original_configuration_runner(request)
                fixture_reconcile = fixture_result.reconcile_result
                return ReconcileResult(
                    success=True,
                    request=request,
                    desired_fingerprint="sha256:" + "d" * 64,
                    restart_report=RestartReport(RestartRequirement.NONE, 0, 0),
                    action_results=fixture_reconcile.action_results,
                    private_overlay=fixture_reconcile.private_overlay,
                )

        restart_coordinator = RestartCoordinator(
            FixtureBuildManager(),
            capability_resolver=RestartCapabilityResolver(platform_id="macos"),
            session_id_provider=lambda: SESSION_B,
            store=restart_store,
        )
        self.assertIs(restart_coordinator._store, restart_store)

        def configure(request, *, transaction_access):
            events.append("configuration_private_apply")
            self.assertEqual(len(issued_transaction_access), 1)
            self.assertIs(transaction_access, issued_transaction_access[0])
            self.assertTrue(transaction_access.matches(restart_store))
            self.assertFalse(self.backend.installed["plugin.video.redlight"].enabled)
            self.assertEqual(
                active_activation_hold_ids(self.store),
                frozenset({"plugin.video.redlight"}),
            )
            self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
            return restart_coordinator.reconcile(
                request, transaction_access=transaction_access
            )

        def resume(*, current_session_id, transaction_access=None):
            events.append("resume")
            try:
                restart_store.create(self._bm020_transaction())
            except TransactionLockBusy:
                events.append("bm020_create_blocked")
            else:
                self.fail("BM-020 transaction creation was not serialized with retry")
            return original_resume(
                current_session_id=current_session_id,
                transaction_access=transaction_access,
            )

        self.policy.set_policy = set_policy
        source_store.read_bytes = read_bytes
        self.store.rearm_held_quiescence = rearm
        restart_store.inspect = inspect_bm020
        restart_store.locked_access = locked_access
        self.store.transition_expected = transition
        self.store.clear_expected = clear_expected
        coordinator.registry_backend.get_addon_details = check_registry
        coordinator.configuration_runner = configure
        coordinator.resume_after_restart = resume
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ):
            result = coordinator.retry_held_quiescence(
                expected_transaction=held,
                current_session_id=SESSION_B,
                artifact_source_store=source_store,
                restart_store=restart_store,
            )

        self.assertEqual(result.outcome, "complete", (result.code, result.message))
        self.assertEqual(events.count("resume"), 1)
        self.assertLess(events.index("artifact_stage"), events.index("cas"))
        self.assertLess(events.index("bm020_lock_acquired"), events.index("cas"))
        self.assertLess(events.index("cas"), events.index("resume"))
        self.assertLess(events.index("resume"), events.index("bm020_create_blocked"))
        self.assertLess(events.index("bm020_create_blocked"), events.index("registry_check"))
        self.assertLess(events.index("registry_check"), events.index("configuration_private_apply"))
        self.assertLess(events.index("configuration_private_apply"), events.index("configuration_reconcile"))
        self.assertLess(events.index("configuration_private_apply"), events.index(FrozenLifecycleStage.PRIVATE_VERIFIED.value))
        self.assertLess(events.index(FrozenLifecycleStage.PRIVATE_VERIFIED.value), events.index(FrozenLifecycleStage.ACTIVATION_RELEASED.value))
        self.assertLess(events.index(FrozenLifecycleStage.ACTIVATION_RELEASED.value), events.index(("policy", AddonUpdatePolicy.AUTOMATIC)))
        self.assertLess(events.index(("policy", AddonUpdatePolicy.AUTOMATIC)), events.index("frozen_transaction_cleared"))
        self.assertLess(events.index("frozen_transaction_cleared"), events.index("bm020_lock_released"))
        node = manifest.addons[0]
        self.assertEqual(
            self.artifacts.read_bytes(node.artifact.sha256),
            source_store.read_bytes(node.artifact.sha256),
        )
        self.assertEqual(len(rearmed_snapshots), 1)
        rearmed = rearmed_snapshots[0]
        self.assertEqual(rearmed.phase, FrozenInstallPhase.AWAITING_RESTART)
        self.assertEqual(rearmed.status_code, "")
        self.assertEqual(rearmed.status_message, "")
        for field in (
            "transaction_id",
            "build_id",
            "manifest_path",
            "device_profile_id",
            "manifest_fingerprint",
            "originating_kodi_session_id",
            "original_update_policy",
            "updater_guard_required",
            "install_plan_fingerprint",
            "configuration_manifest_path",
            "private_overlay_id",
            "private_overlay_fingerprint",
            "private_overlay_required",
            "lifecycle_stage",
            "activation_hold_ids",
            "activation_hold_released",
            "lifecycle_restart_count",
        ):
            self.assertEqual(getattr(rearmed, field), getattr(held, field), field)
        self.assertFalse(rearmed.activation_hold_released)
        self.assertEqual(active_activation_hold_ids(self.store), frozenset())
        self.assertIsNone(self.store.inspect())
        self.assertIsNone(restart_store.inspect())
        owner = self.backend.installed["plugin.video.redlight"]
        self.assertEqual(owner.version, "2.6.8")
        self.assertFalse(owner.broken)
        self.assertTrue(owner.enabled)
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.AUTOMATIC)
        # One quarantine write at the initial install, one terminal restore, and
        # nothing in between: the retry and its continuation only verified.
        self.assertEqual(
            self.policy.calls,
            [AddonUpdatePolicy.NEVER_CHECK, AddonUpdatePolicy.AUTOMATIC],
        )

    def test_held_retry_rejects_predicate_near_misses_without_mutation(self):
        _manifest, _profile, source_store, coordinator, held = (
            self._held_redlight_retry_case()
        )
        near_misses = (
            replace(held, phase=FrozenInstallPhase.AWAITING_RESTART),
            replace(held, status_code="OTHER_FAILURE"),
            replace(held, lifecycle_stage=FrozenLifecycleStage.NONE),
            replace(held, lifecycle_restart_count=2),
            replace(held, activation_hold_ids=("plugin.video.other",)),
            replace(held, activation_hold_released=True),
            replace(held, updater_guard_required=False),
            replace(held, original_update_policy=AddonUpdatePolicy.NOTIFY_ONLY),
            replace(held, configuration_manifest_path=""),
            replace(held, private_overlay_fingerprint=""),
        )
        for candidate in near_misses:
            with self.subTest(candidate=candidate.to_dict()):
                self.store.clear()
                self.store.create(candidate)
                policy_calls = tuple(self.policy.calls)
                with patch.object(
                    coordinator, "resume_after_restart"
                ) as resume:
                    result = coordinator.retry_held_quiescence(
                        expected_transaction=candidate,
                        current_session_id=SESSION_B,
                        artifact_source_store=source_store,
                        restart_store=self._restart_store(),
                    )
                self.assertEqual(result.code, "FROZEN_HELD_RETRY_NOT_ELIGIBLE")
                self.assertEqual(self.store.inspect(), candidate)
                self.assertEqual(tuple(self.policy.calls), policy_calls)
                resume.assert_not_called()

    def test_held_retry_rejects_same_session_and_preserves_generic_abandon_rejection(self):
        _manifest, _profile, source_store, coordinator, held = (
            self._held_redlight_retry_case()
        )
        policy_calls = tuple(self.policy.calls)
        mismatched_session = coordinator.retry_held_quiescence(
            expected_transaction=held,
            current_session_id=SESSION_A,
            artifact_source_store=source_store,
            restart_store=self._restart_store(),
        )
        self.assertEqual(
            mismatched_session.code, "FROZEN_HELD_RETRY_SESSION_MISMATCH"
        )
        self.assertEqual(self.store.inspect(), held)
        self.assertEqual(tuple(self.policy.calls), policy_calls)

        coordinator.session_id_provider = lambda: SESSION_A
        same_session = coordinator.retry_held_quiescence(
            expected_transaction=held,
            current_session_id=SESSION_A,
            artifact_source_store=source_store,
            restart_store=self._restart_store(),
        )
        self.assertEqual(same_session.code, "FROZEN_SAME_SESSION")
        self.assertEqual(self.store.inspect(), held)
        self.assertEqual(tuple(self.policy.calls), policy_calls)

        abandoned = coordinator.abandon()
        self.assertEqual(abandoned.outcome, "needs_attention")
        self.assertEqual(abandoned.code, "HELD_LIFECYCLE_CANNOT_BE_ABANDONED")
        self.assertEqual(self.store.inspect(), held)
        self.assertEqual(tuple(self.policy.calls), policy_calls)

    def test_held_retry_rejects_bm020_transaction_and_wrong_owner_version(self):
        _manifest, profile, source_store, coordinator, held = (
            self._held_redlight_retry_case()
        )
        restart_store = self._restart_store()
        bm020_transaction = self._bm020_transaction()
        restart_store.create(bm020_transaction)
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ):
            conflict = coordinator.retry_held_quiescence(
                expected_transaction=held,
                current_session_id=SESSION_B,
                artifact_source_store=source_store,
                restart_store=restart_store,
            )
        self.assertEqual(conflict.code, "BM020_TRANSACTION_PRESENT")
        self.assertEqual(restart_store.inspect(), bm020_transaction)
        self.assertEqual(self.store.inspect(), held)
        self.assertEqual(
            active_activation_hold_ids(self.store),
            frozenset({"plugin.video.redlight"}),
        )

        restart_store.clear()
        self.backend.installed["plugin.video.redlight"] = FrozenInstalledAddon(
            "plugin.video.redlight", "2.6.7", False
        )
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ):
            wrong_owner = coordinator.retry_held_quiescence(
                expected_transaction=held,
                current_session_id=SESSION_B,
                artifact_source_store=source_store,
                restart_store=restart_store,
            )
        self.assertEqual(wrong_owner.code, "FROZEN_HELD_RETRY_STATE_CHANGED")
        self.assertEqual(self.store.inspect(), held)
        self.assertEqual(
            active_activation_hold_ids(self.store),
            frozenset({"plugin.video.redlight"}),
        )

    def test_held_retry_requires_same_profile_bm020_store(self):
        _manifest, _profile, source_store, coordinator, held = (
            self._held_redlight_retry_case()
        )
        wrong_profile_store = TransactionStore(str(self.root / "other-profile"))
        policy_calls = tuple(self.policy.calls)
        with patch.object(coordinator, "resume_after_restart") as resume:
            result = coordinator.retry_held_quiescence(
                expected_transaction=held,
                current_session_id=SESSION_B,
                artifact_source_store=source_store,
                restart_store=wrong_profile_store,
            )

        self.assertEqual(result.code, "BM020_TRANSACTION_PROFILE_MISMATCH")
        self.assertEqual(self.store.inspect(), held)
        self.assertEqual(
            active_activation_hold_ids(self.store),
            frozenset({"plugin.video.redlight"}),
        )
        self.assertFalse(self.backend.installed["plugin.video.redlight"].enabled)
        self.assertEqual(tuple(self.policy.calls), policy_calls)
        resume.assert_not_called()

    def test_held_retry_closes_transaction_creation_window_before_rearm(self):
        _manifest, profile, source_store, coordinator, held = (
            self._held_redlight_retry_case()
        )
        restart_store = self._restart_store()
        bm020_transaction = self._bm020_transaction()
        original_locked_access = restart_store.locked_access
        original_rearm = self.store.rearm_held_quiescence

        @contextmanager
        def introduce_transaction_before_locked_snapshot():
            # This runs after the old final inspect returned no transaction and
            # before the new atomic inspection acquires the shared BM-020 lock.
            restart_store.create(bm020_transaction)
            with original_locked_access() as access:
                yield access

        restart_store.locked_access = introduce_transaction_before_locked_snapshot
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ), patch.object(self.store, "rearm_held_quiescence", wraps=original_rearm) as rearm, patch.object(
            coordinator, "resume_after_restart"
        ) as resume:
            result = coordinator.retry_held_quiescence(
                expected_transaction=held,
                current_session_id=SESSION_B,
                artifact_source_store=source_store,
                restart_store=restart_store,
            )

        self.assertEqual(result.code, "BM020_TRANSACTION_PRESENT")
        self.assertEqual(restart_store.inspect(), bm020_transaction)
        self.assertEqual(self.store.inspect(), held)
        self.assertEqual(
            active_activation_hold_ids(self.store),
            frozenset({"plugin.video.redlight"}),
        )
        self.assertFalse(self.backend.installed["plugin.video.redlight"].enabled)
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        self.assertNotIn(AddonUpdatePolicy.AUTOMATIC, self.policy.calls)
        rearm.assert_not_called()
        resume.assert_not_called()

    def test_held_retry_store_cas_rejects_same_phase_snapshot_drift(self):
        _manifest, _profile, _source_store, _coordinator, held = (
            self._held_redlight_retry_case()
        )
        drifted = self.store.transition_expected(
            transaction_id=held.transaction_id,
            expected_phase=FrozenInstallPhase.NEEDS_ATTENTION,
            new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
            status_code=held.status_code,
            status_message="different safe diagnostic",
        )
        with self.assertRaises(FrozenInstallStateConflict):
            self.store.rearm_held_quiescence(held)
        self.assertEqual(self.store.inspect(), drifted)
        self.assertEqual(drifted.phase, FrozenInstallPhase.NEEDS_ATTENTION)

    def test_held_retry_missing_exact_artifact_fails_closed(self):
        _manifest, profile, _source_store, coordinator, held = (
            self._held_redlight_retry_case()
        )
        empty_source = ArtifactStore(self.root / "missing-retained-artifacts")
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ), patch.object(coordinator, "resume_after_restart") as resume:
            result = coordinator.retry_held_quiescence(
                expected_transaction=held,
                current_session_id=SESSION_B,
                artifact_source_store=empty_source,
                restart_store=self._restart_store(),
            )
        self.assertEqual(result.code, "FROZEN_HELD_RETRY_VALIDATION_FAILED")
        self.assertEqual(self.store.inspect(), held)
        self.assertEqual(
            active_activation_hold_ids(self.store),
            frozenset({"plugin.video.redlight"}),
        )
        resume.assert_not_called()

    def test_held_retry_rejects_manifest_plan_and_overlay_identity_mismatch(self):
        manifest, profile, source_store, coordinator, held = (
            self._held_redlight_retry_case()
        )
        coordinator.manifest_loader = lambda _path: replace(
            manifest, name="changed manifest identity"
        )
        with patch.object(
            coordinator, "resume_after_restart"
        ) as resume:
            changed_manifest = coordinator.retry_held_quiescence(
                expected_transaction=held,
                current_session_id=SESSION_B,
                artifact_source_store=source_store,
                restart_store=self._restart_store(),
            )
        self.assertEqual(
            changed_manifest.code, "FROZEN_HELD_RETRY_VALIDATION_FAILED"
        )
        self.assertEqual(self.store.inspect(), held)
        resume.assert_not_called()

        coordinator.manifest_loader = lambda _path: manifest
        changed_plan = replace(held, install_plan_fingerprint="f" * 64)
        self.store.clear()
        self.store.create(changed_plan)
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ), patch.object(coordinator, "resume_after_restart") as resume:
            plan_mismatch = coordinator.retry_held_quiescence(
                expected_transaction=changed_plan,
                current_session_id=SESSION_B,
                artifact_source_store=source_store,
                restart_store=self._restart_store(),
            )
        self.assertEqual(plan_mismatch.code, "FROZEN_HELD_RETRY_VALIDATION_FAILED")
        self.assertEqual(self.store.inspect(), changed_plan)
        resume.assert_not_called()

        self.store.clear()
        self.store.create(held)
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ), patch.object(
            coordinator,
            "_private_overlay_metadata",
            return_value=("changed-overlay", "sha256:" + "9" * 64, False),
        ), patch.object(coordinator, "resume_after_restart") as resume:
            overlay_mismatch = coordinator.retry_held_quiescence(
                expected_transaction=held,
                current_session_id=SESSION_B,
                artifact_source_store=source_store,
                restart_store=self._restart_store(),
            )
        self.assertEqual(
            overlay_mismatch.code, "FROZEN_HELD_RETRY_VALIDATION_FAILED"
        )
        self.assertEqual(self.store.inspect(), held)
        resume.assert_not_called()

    def test_verification_failure_transitions_attention_without_a_write(self):
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
        )  # the fixture policy is NOTIFY_ONLY: Kodi did not persist NEVER_CHECK
        self.assertFalse(status.allowed)
        self.assertEqual(status.code, "FROZEN_UPDATER_NOT_QUARANTINED")
        self.assertEqual(self.store.inspect().phase, FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertEqual(self.policy.calls, [])

    # --- Beta updater-guard fix ------------------------------------------------
    # The initial install is the only place that writes the quarantine. Every
    # post-restart path only reads it, and anything but NEVER_CHECK fails closed.

    def _awaiting_transaction(self, stage=FrozenLifecycleStage.NONE, **overrides):
        held = stage in (
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART,
        )
        values = dict(
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
            lifecycle_stage=stage,
            activation_hold_ids=("plugin.video.redlight",) if held else (),
            activation_hold_released=False,
            lifecycle_restart_count=1 if held else 0,
        )
        values.update(overrides)
        return FrozenInstallTransaction(**values)

    PRESERVED_FIELDS = (
        "transaction_id", "build_id", "manifest_path", "device_profile_id",
        "manifest_fingerprint", "originating_kodi_session_id",
        "original_update_policy", "updater_guard_required",
        "configuration_manifest_path", "lifecycle_stage", "activation_hold_ids",
        "activation_hold_released", "lifecycle_restart_count",
        "install_plan_fingerprint", "private_overlay_id",
        "private_overlay_fingerprint", "private_overlay_required",
    )

    def _assert_failed_closed_and_preserved(self, original, code):
        durable = self.store.inspect()
        self.assertIsNotNone(durable, "the frozen transaction must not be cleared")
        self.assertEqual(durable.phase, FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertEqual(durable.status_code, code)
        for field in self.PRESERVED_FIELDS:
            self.assertEqual(getattr(durable, field), getattr(original, field), field)
        self.assertFalse(durable.activation_hold_released)
        self.assertEqual(
            active_activation_hold_ids(self.store), frozenset(original.activation_hold_ids)
        )

    def _tripwire_coordinator(self, tripped):
        def trip(name):
            def _trip(*_args, **_kwargs):
                tripped.append(name)
                raise AssertionError(f"{name} must not run after a failed verification")
            return _trip

        return FrozenInstallCoordinator(
            store=self.store,
            artifact_store=self.artifacts,
            policy_backend=self.policy,
            installer=self.backend,
            manifest_loader=trip("manifest_loader"),
            session_id_provider=lambda: SESSION_B,
            configuration_runner=trip("configuration_runner"),
            final_validator=trip("final_validator"),
            registry_backend=InMemoryRegistryBackend(self.backend),
        )

    def test_initial_install_from_automatic_writes_the_quarantine_once_and_reads_it_back(self):
        events = []
        store = self.store

        class OrderedPolicy(FakePolicy):
            def get_policy(inner_self):
                events.append("read")
                return super(OrderedPolicy, inner_self).get_policy()

            def set_policy(inner_self, policy):
                durable = store.inspect()
                events.append((
                    "write", AddonUpdatePolicy(policy),
                    durable.phase if durable else None,
                    durable.original_update_policy if durable else None,
                ))
                return super(OrderedPolicy, inner_self).set_policy(policy)

        self.policy = OrderedPolicy(AddonUpdatePolicy.AUTOMATIC)
        restart = SimpleNamespace(
            outcome="manual_restart_required",
            transaction=SimpleNamespace(transaction_id="33333333-3333-4333-8333-333333333333"),
        )
        result = self._coordinator(configuration_runner=lambda _request: restart).install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="test"
        )
        self.assertEqual(result.outcome, "awaiting_restart", (result.code, result.message))
        # capture original -> ownership persisted -> one write -> read-back
        self.assertEqual(events, [
            "read",
            ("write", AddonUpdatePolicy.NEVER_CHECK, FrozenInstallPhase.PREPARING, AddonUpdatePolicy.AUTOMATIC),
            "read",
        ])
        self.assertEqual(self.policy.calls, [AddonUpdatePolicy.NEVER_CHECK])
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        self.assertEqual(self.store.inspect().original_update_policy, AddonUpdatePolicy.AUTOMATIC)

    def test_startup_without_a_frozen_transaction_touches_no_updater_policy(self):
        status = ensure_frozen_install_guard(store=self.store, policy_backend=self.policy)
        self.assertTrue(status.allowed)
        self.assertIsNone(status.transaction)
        self.assertIsNone(run_frozen_install_startup(
            bm020_status=StartupStatus(StartupClassification.NO_TRANSACTION),
            store=self.store,
            policy_backend=self.policy,
        ))
        self.assertEqual((self.policy.reads, self.policy.calls), (0, []))

    def test_startup_with_never_check_continues_with_zero_setter_calls(self):
        for stage in (
            FrozenLifecycleStage.NONE,
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART,
        ):
            with self.subTest(stage=stage):
                self.store.clear()
                self.policy = FakePolicy(AddonUpdatePolicy.NEVER_CHECK)
                transaction = self._awaiting_transaction(stage)
                self.store.create(transaction)
                status = ensure_frozen_install_guard(store=self.store, policy_backend=self.policy)
                self.assertTrue(status.allowed, (status.code, status.message))
                self.assertEqual(self.policy.calls, [])
                self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
                self.assertEqual(self.store.inspect(), transaction)  # untouched

    def test_startup_verification_failure_fails_closed_and_preserves_the_held_transaction(self):
        class MalformedPolicy(FakePolicy):
            def get_policy(inner_self):
                super(MalformedPolicy, inner_self).get_policy()
                return "automatic"

        class UnreadablePolicy(FakePolicy):
            def get_policy(inner_self):
                super(UnreadablePolicy, inner_self).get_policy()
                raise RuntimeError("settings unavailable")

        cases = (
            ("automatic", lambda: FakePolicy(AddonUpdatePolicy.AUTOMATIC), "FROZEN_UPDATER_NOT_QUARANTINED"),
            ("notify only", lambda: FakePolicy(AddonUpdatePolicy.NOTIFY_ONLY), "FROZEN_UPDATER_NOT_QUARANTINED"),
            ("malformed", lambda: MalformedPolicy(AddonUpdatePolicy.NEVER_CHECK), "FROZEN_UPDATER_STATE_UNAVAILABLE"),
            ("unreadable", lambda: UnreadablePolicy(AddonUpdatePolicy.NEVER_CHECK), "FROZEN_UPDATER_STATE_UNAVAILABLE"),
        )
        for stage in (
            FrozenLifecycleStage.NONE,
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART,
        ):
            for label, make_policy, code in cases:
                with self.subTest(stage=stage, policy=label):
                    self.store.clear()
                    self.policy = make_policy()
                    before_value = self.policy.policy
                    transaction = self._awaiting_transaction(stage)
                    self.store.create(transaction)
                    status = ensure_frozen_install_guard(store=self.store, policy_backend=self.policy)
                    self.assertFalse(status.allowed)
                    self.assertEqual(status.code, code)
                    self.assertEqual(self.policy.calls, [])  # no changing write, ever
                    self.assertEqual(self.policy.policy, before_value)
                    self._assert_failed_closed_and_preserved(transaction, code)

    def test_startup_verification_failure_keeps_an_existing_attention_diagnostic(self):
        transaction = self._awaiting_transaction(
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART
        )
        self.store.create(transaction)
        held = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=FrozenInstallPhase.AWAITING_RESTART,
            new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
            status_code="FROZEN_MANIFEST_INVALID",
            status_message="outcome=failed; stage=frozen_manifest_validation",
        )
        self.policy = FakePolicy(AddonUpdatePolicy.AUTOMATIC)
        status = ensure_frozen_install_guard(store=self.store, policy_backend=self.policy)
        self.assertFalse(status.allowed)
        self.assertEqual(status.code, "FROZEN_UPDATER_NOT_QUARANTINED")
        self.assertEqual(self.store.inspect(), held)  # nothing rewritten
        self.assertEqual(self.policy.calls, [])

    def test_startup_verification_failure_blocks_the_frozen_continuation(self):
        for stage in (
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART,
        ):
            with self.subTest(stage=stage):
                self.store.clear()
                self.policy = FakePolicy(AddonUpdatePolicy.AUTOMATIC)
                transaction = self._awaiting_transaction(stage)
                self.store.create(transaction)
                tripped = []

                def trip(name):
                    def _trip(*_args, **_kwargs):
                        tripped.append(name)
                        raise AssertionError(name)
                    return _trip

                with patch.object(AddonUpdateGuard, "restore_original", side_effect=trip("restore_original")), \
                        patch.object(FrozenInstallCoordinator, "resume_after_restart", side_effect=trip("resume")), \
                        patch.object(FrozenInstallStore, "clear_expected", side_effect=trip("clear_expected")), \
                        patch.object(FrozenInstallStore, "clear", side_effect=trip("clear")):
                    result = run_frozen_install_startup(
                        bm020_status=StartupStatus(StartupClassification.NO_TRANSACTION),
                        store=self.store,
                        policy_backend=self.policy,
                        installer=self.backend,
                        manifest_loader=trip("manifest_loader"),
                        session_id_provider=lambda: SESSION_B,
                        configuration_runner=trip("configuration_runner"),
                    )
                self.assertEqual(tripped, [])
                self.assertEqual(result.outcome, "needs_attention")
                self.assertEqual(result.code, "FROZEN_UPDATER_NOT_QUARANTINED")
                self.assertEqual(self.policy.calls, [])
                self._assert_failed_closed_and_preserved(transaction, "FROZEN_UPDATER_NOT_QUARANTINED")

    def test_resume_after_restart_verification_failure_fails_closed_before_any_work(self):
        class MalformedPolicy(FakePolicy):
            def get_policy(inner_self):
                super(MalformedPolicy, inner_self).get_policy()
                return None

        class UnreadablePolicy(FakePolicy):
            def get_policy(inner_self):
                super(UnreadablePolicy, inner_self).get_policy()
                raise RuntimeError("settings unavailable")

        cases = (
            ("automatic", lambda: FakePolicy(AddonUpdatePolicy.AUTOMATIC), "FROZEN_UPDATER_NOT_QUARANTINED"),
            ("notify only", lambda: FakePolicy(AddonUpdatePolicy.NOTIFY_ONLY), "FROZEN_UPDATER_NOT_QUARANTINED"),
            ("malformed", lambda: MalformedPolicy(AddonUpdatePolicy.NEVER_CHECK), "FROZEN_UPDATER_STATE_UNAVAILABLE"),
            ("unreadable", lambda: UnreadablePolicy(AddonUpdatePolicy.NEVER_CHECK), "FROZEN_UPDATER_STATE_UNAVAILABLE"),
        )
        for stage in (
            FrozenLifecycleStage.NONE,
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART,
        ):
            for label, make_policy, code in cases:
                with self.subTest(stage=stage, policy=label):
                    self.store.clear()
                    self.policy = make_policy()
                    transaction = self._awaiting_transaction(stage)
                    self.store.create(transaction)
                    tripped = []
                    coordinator = self._tripwire_coordinator(tripped)
                    with patch.object(AddonUpdateGuard, "restore_original") as restore, \
                            patch.object(FrozenInstallCoordinator, "_finalize") as finalize, \
                            patch.object(FrozenInstallCoordinator, "install") as install, \
                            patch.object(FrozenInstallStore, "clear_expected") as clear_expected, \
                            patch.object(FrozenInstallStore, "clear") as clear:
                        result = coordinator.resume_after_restart(
                            bm020_result=SimpleNamespace()
                        )
                    self.assertEqual(result.outcome, "needs_attention")
                    self.assertEqual(result.code, code)
                    self.assertEqual(tripped, [])  # no manifest load, configuration, or validation
                    for spy in (restore, finalize, install, clear_expected, clear):
                        spy.assert_not_called()
                    self.assertEqual(self.policy.calls, [])
                    self._assert_failed_closed_and_preserved(transaction, code)

    def test_resume_after_restart_with_never_check_continues_with_zero_setter_calls_until_restore(self):
        self.policy = FakePolicy(AddonUpdatePolicy.NEVER_CHECK)
        transaction = self._awaiting_transaction(original_update_policy=AddonUpdatePolicy.NOTIFY_ONLY)
        self.store.create(transaction)
        manifest = self._manifest()
        # The fixture manifest is not this transaction's: it fails closed later, but
        # only after verification passed, which is all this test needs to show.
        calls_seen = []

        def manifest_loader(path):
            calls_seen.append(tuple(self.policy.calls))
            return manifest

        coordinator = FrozenInstallCoordinator(
            store=self.store, artifact_store=self.artifacts, policy_backend=self.policy,
            installer=self.backend, manifest_loader=manifest_loader,
            session_id_provider=lambda: SESSION_B,
        )
        coordinator.resume_after_restart()
        self.assertEqual(calls_seen, [()])  # the loader ran, so verification passed with no write
        self.assertEqual(self.policy.calls, [])

    def test_quiescence_continuation_verification_failure_is_read_only_and_keeps_the_hold(self):
        manifest, profile, source_store, coordinator, held = self._held_redlight_retry_case()
        for node in manifest.addons:  # the exact ZIPs are still in the store after a real restart
            self.artifacts.import_zip(
                source_store.read_bytes(node.artifact.sha256),
                expected_addon_id=node.addon_id,
                expected_version=node.version,
                source="test",
            )
        rearmed = self.store.rearm_held_quiescence(held)  # AWAITING_RESTART, quiescence, hold intact
        self.assertEqual(rearmed.phase, FrozenInstallPhase.AWAITING_RESTART)
        writes_before_restart = tuple(self.policy.calls)
        self.assertEqual(writes_before_restart, (AddonUpdatePolicy.NEVER_CHECK,))
        self.policy.policy = AddonUpdatePolicy.AUTOMATIC  # Kodi did not persist the write
        tripped = []

        def trip(name):
            def _trip(*_args, **_kwargs):
                tripped.append(name)
                raise AssertionError(name)
            return _trip

        coordinator.configuration_runner = trip("configuration_runner")
        coordinator.final_validator = trip("final_validator")
        with patch.object(
            FrozenInstallCoordinator, "_configuration_profile", return_value=profile
        ), patch.object(AddonUpdateGuard, "restore_original") as restore, \
                patch.object(FrozenInstallCoordinator, "_finalize") as finalize, \
                patch.object(FrozenInstallStore, "clear_expected") as clear_expected:
            result = coordinator.install(
                manifest,
                manifest_path="/fixture-held-frozen.json",
                configuration_manifest_path="/fixture-held-config.json",
                device_profile_id="test",
                interactive=False,
            )
        self.assertEqual(result.outcome, "needs_attention", (result.code, result.message))
        self.assertEqual(result.code, "FROZEN_UPDATER_NOT_QUARANTINED")
        self.assertEqual(tripped, [])
        for spy in (restore, finalize, clear_expected):
            spy.assert_not_called()
        self.assertEqual(tuple(self.policy.calls), writes_before_restart)  # no post-restart write
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.AUTOMATIC)
        self._assert_failed_closed_and_preserved(rearmed, "FROZEN_UPDATER_NOT_QUARANTINED")
        self.assertFalse(self.backend.installed["plugin.video.redlight"].enabled)

    def test_held_retry_verification_failure_leaves_the_reviewed_snapshot_untouched(self):
        for label, break_policy, code in (
            ("automatic", lambda p: setattr(p, "policy", AddonUpdatePolicy.AUTOMATIC), "FROZEN_UPDATER_NOT_QUARANTINED"),
            ("notify only", lambda p: setattr(p, "policy", AddonUpdatePolicy.NOTIFY_ONLY), "FROZEN_UPDATER_NOT_QUARANTINED"),
            ("malformed", lambda p: setattr(p, "policy", "automatic"), "FROZEN_UPDATER_STATE_UNAVAILABLE"),
        ):
            with self.subTest(policy=label):
                self.store.clear()
                _manifest, _profile, source_store, coordinator, held = self._held_redlight_retry_case()
                calls_before = tuple(self.policy.calls)
                break_policy(self.policy)
                with patch.object(coordinator, "resume_after_restart") as resume, \
                        patch.object(self.store, "rearm_held_quiescence") as rearm:
                    result = coordinator.retry_held_quiescence(
                        expected_transaction=held,
                        current_session_id=SESSION_B,
                        artifact_source_store=source_store,
                        restart_store=self._restart_store(),
                    )
                self.assertEqual((result.outcome, result.code), ("needs_attention", code))
                self.assertEqual(self.store.inspect(), held)  # byte-identical: not re-armed, not rewritten
                self.assertEqual(
                    active_activation_hold_ids(self.store),
                    frozenset({"plugin.video.redlight"}),
                )
                self.assertEqual(tuple(self.policy.calls), calls_before)  # zero writes
                resume.assert_not_called()
                rearm.assert_not_called()
                self.assertFalse(self.backend.installed["plugin.video.redlight"].enabled)

    def test_same_session_and_repeat_resume_protection_survive_verify_only_startup(self):
        self.policy = FakePolicy(AddonUpdatePolicy.NEVER_CHECK)
        transaction = self._awaiting_transaction(FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART)
        self.store.create(transaction)
        coordinator = FrozenInstallCoordinator(
            store=self.store, artifact_store=self.artifacts, policy_backend=self.policy,
            installer=self.backend, session_id_provider=lambda: SESSION_A,
        )
        same = coordinator.resume_after_restart()
        self.assertEqual((same.outcome, same.code), ("awaiting_restart", "SAME_SESSION"))
        self.assertEqual(self.store.inspect(), transaction)
        self.assertEqual((self.policy.reads, self.policy.calls), (0, []))  # session gate comes first
        # A transaction that already failed closed is never resumed again by a later startup.
        self.policy.policy = AddonUpdatePolicy.AUTOMATIC
        coordinator.session_id_provider = lambda: SESSION_B
        first = coordinator.resume_after_restart()
        self.assertEqual(first.code, "FROZEN_UPDATER_NOT_QUARANTINED")
        failed = self.store.inspect()
        reads_after_first = self.policy.reads
        again = coordinator.resume_after_restart()
        self.assertEqual((again.outcome, again.code), ("needs_attention", "FROZEN_TRANSACTION_NOT_AWAITING"))
        self.assertEqual(self.store.inspect(), failed)
        self.assertEqual((self.policy.reads, self.policy.calls), (reads_after_first, []))

    def test_only_the_initial_install_writes_the_quarantine(self):
        import ast
        from resources.lib import frozen_install as module

        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        calls = {}

        def visit(node, owner):
            for child in ast.iter_child_nodes(node):
                current = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    calls.setdefault(child.func.attr, []).append(current)
                visit(child, current)

        visit(tree, "<module>")
        for forbidden in ("reassert_required", "reassert", "engage", "set_policy"):
            self.assertNotIn(forbidden, calls, forbidden)
        self.assertEqual(calls.get("engage_with_original"), ["install"])
        self.assertEqual(sorted(calls.get("restore_original", [])), ["_finalize", "abandon"])
        self.assertEqual(
            sorted(calls.get("verify_quarantined", [])),
            ["ensure_frozen_install_guard", "install", "resume_after_restart", "retry_held_quiescence"],
        )

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
