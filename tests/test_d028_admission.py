"""Builtin admission through production boundaries; all state is disposable."""
from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib import frozen_install as fi
from resources.lib.frozen import (
    AddonCaptureNode, CaptureStatus, DependencyEdge, FrozenBuildManifest,
    InstalledMetadata, InstalledOrigin, ProvenanceStatus,
)
from resources.lib.artifacts import ArtifactStore
from resources.lib.addons import RepositoryPackage
from tests.builtin_evidence import SyntheticBuiltinBackend, core_node
from tests import test_frozen_install as old


class BuiltinAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.backend = SyntheticBuiltinBackend()
        self.backend.builtin_state["xbmc.gui"] = fi.FrozenInstalledAddon("xbmc.gui", "5.17.0", True)
        self.backend.builtin_abis["xbmc.gui"] = "5.17.0"
        self.gui = AddonCaptureNode("xbmc.gui", "5.17.0", "system", True,
            ProvenanceStatus.UNKNOWN, system=True, status=CaptureStatus.SYSTEM,
            dependency_edges=(DependencyEdge("xbmc.core", "0.1.0"),))

    def manifest(self, minimum="5.17.0", *, systems_only=False):
        aid = "plugin.video.admission"
        artifact = self.artifacts.import_zip(old._zip(aid, "1.0.0", requires=(("xbmc.gui", minimum),)),
                                            expected_addon_id=aid, expected_version="1.0.0")
        managed = AddonCaptureNode(aid, "1.0.0", "xbmc.python.pluginsource", True,
            ProvenanceStatus.UNKNOWN, artifact=artifact,
            dependency_edges=(DependencyEdge("xbmc.gui", minimum),))
        return FrozenBuildManifest(1, "admission", "Admission", "2026-10-20T00:00:00Z",
            "21.3", "macos", CaptureStatus.COMPLETE,
            (self.gui, core_node()) if systems_only else (managed, self.gui, core_node()))

    def verify(self, manifest=None, **kwargs):
        m = manifest or self.manifest()
        plan = fi.validate_frozen_manifest(m, self.artifacts)
        return fi.verify_platform_requirements(plan, self.backend,
            planned_versions=fi._planned_versions(plan, ()), **kwargs)

    def assert_blocked(self, manifest=None, **kwargs):
        with self.assertRaises(fi.FrozenPlatformRequirementError):
            self.verify(manifest, **kwargs)
        self.assertEqual([], self.backend.install_calls)
        self.assertEqual([], self.backend.enable_calls)
        self.assertEqual([], self.backend.repository_calls)

    def test_managed_builtin_minimum_999_is_rejected(self):
        self.assert_blocked(self.manifest("999.0.0"))

    def test_every_incoming_minimum_is_preserved(self):
        m = self.manifest()
        root = m.addons[0]
        m = replace(m, addons=(replace(root, dependency_edges=(
            DependencyEdge("xbmc.gui", "5.17.0"), DependencyEdge("xbmc.gui", "999.0.0"))),) + m.addons[1:])
        # Match the exact ZIP too: this test isolates admission of both minima.
        artifact = self.artifacts.import_zip(old._zip(root.addon_id, root.version,
            requires=(("xbmc.gui", "5.17.0"), ("xbmc.gui", "999.0.0"))),
            expected_addon_id=root.addon_id, expected_version=root.version)
        m = replace(m, addons=(replace(m.addons[0], artifact=artifact),) + m.addons[1:])
        self.assert_blocked(m)

    def test_system_only_graph_is_verified(self):
        verified = self.verify(self.manifest(systems_only=True))
        self.assertEqual({"xbmc.gui", "xbmc.core"}, set(verified.builtin_versions))
        self.backend.builtin_state.pop("xbmc.core")
        self.assert_blocked(self.manifest(systems_only=True))

    def test_unavailable_native_evidence_never_uses_installed_details_fallback(self):
        self.backend.read_verified_builtin_metadata = None
        self.assert_blocked()
        weak = fi.InMemoryFrozenArtifactBackend(installed=self.backend.builtin_state)
        self.assertFalse(fi._builtin_satisfies(weak, DependencyEdge("xbmc.gui", "5.17.0")))

    def test_rejecting_native_authority_cannot_be_overridden_by_metadata(self):
        self.backend.verify_builtin_requirement = lambda edge: False
        self.assert_blocked()

    def test_missing_disabled_broken_or_nonboolean_evidence_blocks(self):
        for state in (None, fi.FrozenInstalledAddon("xbmc.gui", "5.17.0", False),
                      fi.FrozenInstalledAddon("xbmc.gui", "5.17.0", True, True),
                      fi.FrozenInstalledAddon("xbmc.gui", "5.17.0", 1)):
            with self.subTest(state=state):
                self.backend.builtin_state["xbmc.gui"] = state
                self.assert_blocked()

    def test_abi_floor_and_strict_dotted_versions(self):
        for minimum in ("5.16.9", "5.17", "5.17.0+matrix.1", "bad"):
            with self.subTest(minimum=minimum):
                self.assert_blocked(self.manifest(minimum))
        self.verify(self.manifest("5.17.0"))
        self.backend.builtin_abis["xbmc.gui"] = "6.0.0"
        self.assert_blocked()

    def test_malformed_or_shadowed_metadata_is_not_authority(self):
        valid = self.backend.read_verified_builtin_metadata
        for xml, origin in ((b"broken", InstalledOrigin.APPLICATION),
                            (b'<addon id="wrong.id" version="5.17.0"/>', InstalledOrigin.APPLICATION),
                            (b'<addon id="xbmc.gui" version="5.17.0"/>', InstalledOrigin.APPLICATION),
                            (b'<addon id="xbmc.gui" version="5.17.0"><backwards-compatibility abi="5.17.0"/></addon>', InstalledOrigin.HOME)):
            with self.subTest(xml=xml, origin=origin):
                self.backend.verify_builtin_requirement = lambda edge: True
                self.backend.read_verified_builtin_metadata = lambda edge: (
                    InstalledMetadata(xml, origin) if edge.addon_id == "xbmc.gui" else valid(edge))
                self.assert_blocked()

    def test_builtin_target_declared_core_is_independently_verified(self):
        m = self.manifest()
        # Omit the source GUI/core edge: target metadata must still close it.
        m = replace(m, addons=tuple(replace(n, dependency_edges=()) if n.system else n for n in m.addons))
        original = self.backend.read_verified_builtin_metadata
        def reader(edge):
            if edge.addon_id != "xbmc.gui":
                return original(edge)
            return InstalledMetadata(b'<addon id="xbmc.gui" version="5.17.0">'
                b'<backwards-compatibility abi="5.17.0"/><requires>'
                b'<import addon="xbmc.core" version="999.0.0"/></requires></addon>', InstalledOrigin.APPLICATION)
        self.backend.read_verified_builtin_metadata = reader
        self.assert_blocked(m)

    def test_outgoing_system_missing_child_and_cycle_static_validation(self):
        m = self.manifest(systems_only=True)
        for nodes in ((self.gui,), (self.gui, replace(core_node(), dependency_edges=(DependencyEdge("xbmc.gui", "5.17.0"),)))):
            with self.subTest(nodes=nodes), self.assertRaises(fi.FrozenInstallValidationError):
                fi.validate_frozen_manifest(replace(m, addons=nodes), self.artifacts)

    def test_target_builtin_cycle_is_rejected(self):
        original = self.backend.read_verified_builtin_metadata
        def reader(edge):
            if edge.addon_id != "xbmc.core":
                return original(edge)
            return InstalledMetadata(b'<addon id="xbmc.core" version="0.1.0">'
                b'<backwards-compatibility abi="0.1.0"/><requires>'
                b'<import addon="xbmc.gui" version="5.17.0"/></requires></addon>', InstalledOrigin.APPLICATION)
        self.backend.read_verified_builtin_metadata = reader
        self.assert_blocked()

    def test_changed_observation_during_one_pass_is_rejected(self):
        m = self.manifest()
        root = m.addons[0]
        data = old._zip(root.addon_id, "1.0.0", requires=(("xbmc.gui", "05.17.0"), ("xbmc.gui", "5.17.0")))
        artifact = self.artifacts.import_zip(data, expected_addon_id=root.addon_id, expected_version="1.0.0")
        m = replace(m, addons=(replace(root, artifact=artifact, dependency_edges=(
            DependencyEdge("xbmc.gui", "05.17.0"), DependencyEdge("xbmc.gui", "5.17.0"))),) + m.addons[1:])
        original = self.backend.read_verified_builtin_metadata
        calls = []
        def reader(edge):
            metadata = original(edge)
            if edge.addon_id == "xbmc.gui":
                calls.append(edge.min_version)
                return InstalledMetadata(metadata.xml_bytes.replace(b"</addon>",
                    (b" " * len(calls)) + b"</addon>"), metadata.origin)
            return metadata
        self.backend.verify_builtin_requirement = lambda edge: True
        self.backend.read_verified_builtin_metadata = reader
        self.assert_blocked(m)

    def test_repository_actual_stronger_minimum_survives_id_collection(self):
        m = self.manifest()
        aid = m.addons[0].addon_id
        package = RepositoryPackage(aid, "repository.test", "2.0.0",
            old._zip(aid, "2.0.0", requires=(("xbmc.gui", "999.0.0"),)))
        requirements = fi._repository_required_addon_ids(None, packages=(package,))
        self.assertEqual((DependencyEdge("xbmc.gui", "999.0.0", False, (aid,)),),
                         requirements.dependencies.get(aid))
        self.assert_blocked(m, required_addon_ids=requirements)
        p = fi.validate_frozen_manifest(m, self.artifacts)
        with self.assertRaises(fi.FrozenInstallValidationError):
            fi._repository_package_required_dependencies(package, p, {}, frozenset(), platform_versions=self.verify(m))

    def test_repository_lower_abi_minimum_is_not_lost_by_consolidation(self):
        m = self.manifest()
        aid = m.addons[0].addon_id
        package = RepositoryPackage(aid, "repository.test", "2.0.0",
            old._zip(aid, "2.0.0", requires=(("xbmc.gui", "5.16.0"), ("xbmc.gui", "5.17.0"))))
        requirements = fi._repository_required_addon_ids(None, packages=(package,))
        self.assertEqual(2, len(requirements.dependencies[aid]))
        self.assert_blocked(m, required_addon_ids=requirements)

    def test_missing_target_core_declaration_is_unverifiable(self):
        reader = self.backend.read_verified_builtin_metadata
        def missing(edge):
            metadata = reader(edge)
            if edge.addon_id == "xbmc.gui":
                return replace(metadata, xml_bytes=metadata.xml_bytes.replace(
                    b'<requires><import addon="xbmc.core" version="0.1.0"/></requires>', b''))
            return metadata
        self.backend.read_verified_builtin_metadata = missing
        self.assert_blocked()

    def test_ambiguous_target_dependency_declarations_are_rejected(self):
        reader = self.backend.read_verified_builtin_metadata
        def ambiguous(edge):
            metadata = reader(edge)
            return replace(metadata, xml_bytes=metadata.xml_bytes.replace(
                b'</addon>', b'<requires/></addon>'))
        self.backend.read_verified_builtin_metadata = ambiguous
        self.assert_blocked()

    def test_preexecution_rejection_has_zero_transaction_policy_and_install_mutations(self):
        m = self.manifest("999.0.0")
        store = fi.FrozenInstallStore(self.root / "transaction")
        policy = old.FakePolicy(old.AddonUpdatePolicy.NOTIFY_ONLY)
        coordinator = fi.FrozenInstallCoordinator(store=store, artifact_store=self.artifacts,
            installer=self.backend, policy_backend=policy, session_id_provider=lambda: old.SESSION_A)
        with patch.object(store, "create", side_effect=AssertionError("transaction mutation")):
            result = coordinator.install(m, manifest_path="/synthetic.json", device_profile_id="test")
        self.assertEqual(fi.FrozenPlatformRequirementError.code, result.code)
        self.assertEqual([], policy.calls)
        self.assertEqual([], self.backend.install_calls)
        self.assertEqual([], self.backend.enable_calls)
        self.assertIsNone(store.inspect())

    def test_native_gui_resource_and_core_are_explicitly_unverified(self):
        backend = fi.KodiRuntimeFrozenArtifactBackend()
        self.addCleanup(backend.close)
        for aid in ("xbmc.gui", "kodi.resource", "xbmc.core"):
            with self.subTest(aid=aid):
                self.assertFalse(backend.verify_builtin_requirement(DependencyEdge(aid, "1.0.0")))
                self.assertIsNone(backend.read_verified_builtin_metadata(DependencyEdge(aid, "1.0.0")))

    def test_plan_approval_freshness_includes_builtin_metadata(self):
        from tests import test_plan as plans
        h = plans.PlanHarness(self, with_private=False, with_resource=False)
        del h.kodi.addons[plans.MODULE]
        h.deps.installed.pop(plans.MODULE, None)
        backend = SyntheticBuiltinBackend()
        service = h.plan_service(platform_backend=backend)
        target = h.plan_target()
        plan = service.preview(target)
        self.assertIsNotNone(plan.review, plan.to_safe_dict())
        self.assertEqual(plans.ReviewFreshness.CURRENT, service.validate(target, plan.review).freshness)
        reader = backend.read_verified_builtin_metadata
        backend.read_verified_builtin_metadata = lambda edge: replace(
            reader(edge), xml_bytes=reader(edge).xml_bytes + b"\n")
        self.assertNotEqual(plans.ReviewFreshness.CURRENT, service.validate(target, plan.review).freshness)

    def test_restart_resume_rejects_lost_builtin_before_install_or_configuration(self):
        m = self.manifest()
        store = fi.FrozenInstallStore(self.root / "transaction")
        policy = old.FakePolicy(old.AddonUpdatePolicy.NOTIFY_ONLY)
        restart = SimpleNamespace(outcome="manual_restart_required",
            transaction=SimpleNamespace(transaction_id="33333333-3333-4333-8333-333333333333"))
        coordinator = fi.FrozenInstallCoordinator(store=store, artifact_store=self.artifacts,
            installer=self.backend, policy_backend=policy, session_id_provider=lambda: old.SESSION_A,
            configuration_runner=lambda request: restart, manifest_loader=lambda path: m)
        initial = coordinator.install(m, manifest_path="/synthetic.json", device_profile_id="test")
        self.assertEqual("awaiting_restart", initial.outcome, (initial.code, initial.message))
        before = (list(self.backend.install_calls), list(self.backend.enable_calls))
        self.backend.builtin_state.pop("xbmc.core")
        with patch.object(coordinator, "configuration_runner", side_effect=AssertionError("configuration")):
            result = coordinator.resume_after_restart(current_session_id=old.SESSION_B)
        self.assertNotEqual("complete", result.outcome)
        self.assertEqual(fi.FrozenPlatformRequirementError.code, result.code)
        self.assertEqual(before, (self.backend.install_calls, self.backend.enable_calls))

    def test_final_verification_cannot_complete_after_builtin_loss(self):
        m = self.manifest()
        store = fi.FrozenInstallStore(self.root / "transaction")
        policy = old.FakePolicy(old.AddonUpdatePolicy.NOTIFY_ONLY)
        def configure(request):
            self.backend.builtin_state.pop("xbmc.core")
            return SimpleNamespace(outcome="complete")
        coordinator = fi.FrozenInstallCoordinator(store=store, artifact_store=self.artifacts,
            installer=self.backend, policy_backend=policy, session_id_provider=lambda: old.SESSION_A,
            configuration_runner=configure)
        result = coordinator.install(m, manifest_path="/synthetic.json", device_profile_id="test")
        self.assertEqual("needs_attention", result.outcome)
        self.assertEqual(fi.FrozenPlatformRequirementError.code, result.code)
        self.assertIsNotNone(store.inspect())
        self.assertEqual(old.AddonUpdatePolicy.NEVER_CHECK, policy.policy)

    def test_held_retry_checks_builtins_before_artifact_writes(self):
        case = old.FrozenInstallTest()
        case.setUp()
        self.addCleanup(case.tearDown)
        case.backend.builtin_state["xbmc.gui"] = self.backend.builtin_state["xbmc.gui"]
        case.backend.builtin_abis["xbmc.gui"] = "5.17.0"
        constructor = old.FrozenBuildManifest
        def graph(*args, **kwargs):
            m = constructor(*args, **kwargs)
            return replace(m, addons=m.addons + (self.gui, core_node()))
        with patch.object(old, "FrozenBuildManifest", graph):
            m, profile, source, coordinator, held = case._held_redlight_retry_case()
        case.backend.builtin_state.pop("xbmc.core")
        calls = (list(case.backend.install_calls), list(case.backend.enable_calls), list(case.policy.calls))
        with patch.object(case.artifacts, "import_zip", side_effect=AssertionError("artifact write")) as write:
            result = coordinator.retry_held_quiescence(expected_transaction=held,
                current_session_id=old.SESSION_B, artifact_source_store=source,
                restart_store=case._restart_store())
        write.assert_not_called()
        self.assertEqual("FROZEN_HELD_RETRY_VALIDATION_FAILED", result.code)
        self.assertEqual(held, case.store.inspect())
        self.assertEqual(calls, (case.backend.install_calls, case.backend.enable_calls, case.policy.calls))
