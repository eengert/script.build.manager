"""Focused BM-022 frozen-install transaction and exact-artifact tests."""

import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from resources.lib.artifacts import ArtifactStore
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
    FrozenInstalledAddon,
    InMemoryFrozenArtifactBackend,
    ensure_frozen_install_guard,
    validate_frozen_manifest,
)
from resources.lib.update_guard import AddonUpdatePolicy, UpdatePolicyBackend


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
            ()
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
        result = self._coordinator(
            configuration_runner=lambda _request: SimpleNamespace(outcome="failed")
        ).install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="test"
        )
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        self.assertIsNotNone(self.store.inspect())

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
        self.assertEqual(resumed.outcome, "complete")
        self.assertIsNone(self.store.inspect())
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NOTIFY_ONLY)

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
