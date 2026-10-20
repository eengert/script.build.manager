"""Target metadata promotion must close over captured mandatory dependencies."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from tests import test_frozen_install as fi, test_plan as pt
from tests.test_frozen import _xml
from resources.lib.frozen import (
    AddonCaptureNode, CaptureStatus, DependencyEdge, InstalledMetadata, InstalledOrigin,
    ProvenanceStatus,
)
from resources.lib.frozen_install import (
    FrozenInstallCoordinator, FrozenInstalledAddon, FrozenPlatformRequirementError,
    InMemoryFrozenArtifactBackend, verify_platform_requirements, validate_frozen_manifest,
)
from resources.lib.plan import BuildPlanService
from resources.lib.plan_model import PlanState

C = 'script.module.closure-c'
Q = 'script.module.closure-q'
D = 'script.module.closure-d'
S = 'script.module.closure-s'

from tests.builtin_evidence import SyntheticBuiltinBackend


def platform(aid):
    return AddonCaptureNode(aid, '1.0.0', 'xbmc.python.module', True,
                            ProvenanceStatus.UNKNOWN, optional=True,
                            platform_provided=True, status=CaptureStatus.PLATFORM_PROVIDED)


def observe(backend, aid, *, imports=(), version='1.0.0'):
    backend.installed[aid] = FrozenInstalledAddon(aid, version, True)
    backend.platform_metadata[aid] = InstalledMetadata(
        _xml(aid, version, imports=imports, point='xbmc.python.module'),
        InstalledOrigin.APPLICATION)


class TargetClosureInstall(unittest.TestCase):
    setUp = fi.PlatformProvidedInstallTests.setUp
    _capture = fi.PlatformProvidedInstallTests._capture
    _install_target = fi.PlatformProvidedInstallTests._install_target
    _install = fi.PlatformProvidedInstallTests._install
    _assert_blocked_before_mutation = fi.PlatformProvidedInstallTests._assert_blocked_before_mutation

    def closure(self, *, promote=True, levels=1):
        self.manifest = self._capture()
        children = []
        for aid, dependency in ((C, Q), (D, S))[:levels]:
            artifact = self.artifacts.import_zip(fi._zip(aid, '1.0.0', requires=((dependency, '1.0.0'),)),
                                                 expected_addon_id=aid, expected_version='1.0.0')
            children.extend((AddonCaptureNode(
                aid, '1.0.0', 'xbmc.python.module', True, ProvenanceStatus.VERIFIED_REPOSITORY,
                artifact=artifact, optional=True, dependency_edges=(DependencyEdge(dependency, '1.0.0'),)),
                platform(dependency)))
        self.manifest = replace(self.manifest, addons=tuple(
            replace(n, dependency_edges=n.dependency_edges + (DependencyEdge(C, '1.0.0', True),))
            if n.addon_id == fi.PLATFORM_ROOT else n for n in self.manifest.addons) + tuple(children))
        self._install_target(extra_imports=((C, '1.0.0', False),) if promote else ())
        observe(self.backend, Q, imports=((D, '1.0.0', False),) if levels == 2 else ())
        if levels == 2:
            observe(self.backend, S)

    def verified(self):
        return verify_platform_requirements(validate_frozen_manifest(self.manifest, self.artifacts),
            self.backend, planned_versions={n.addon_id: n.version for n in self.manifest.addons})

    def test_missing_promoted_platform_blocks_before_mutation(self):
        self.closure()
        self.backend.installed.pop(Q)
        self._assert_blocked_before_mutation()

    def test_compatible_closure_succeeds_in_dependency_order(self):
        self.closure()
        self.assertIn(Q, self.verified())
        result = self._install()
        self.assertEqual('complete', result.outcome, (result.code, result.message))
        self.assertLess(self.backend.install_calls.index(C), self.backend.install_calls.index(fi.PLATFORM_ROOT))
        self.assertNotIn(Q, self.backend.install_calls)
        self.assertNotIn(Q, [aid for aid, _ in self.backend.enable_calls])

    def test_multiple_alternating_promotion_levels(self):
        self.closure(levels=2)
        self.assertIn(S, self.verified())
        self.backend.installed.pop(S)
        self._assert_blocked_before_mutation()

    def test_multiple_promotion_levels_succeed_in_dependency_order(self):
        self.closure(levels=2)
        result = self._install()
        self.assertEqual('complete', result.outcome, (result.code, result.message))
        self.assertLess(self.backend.install_calls.index(D), self.backend.install_calls.index(C))
        self.assertLess(self.backend.install_calls.index(C), self.backend.install_calls.index(fi.PLATFORM_ROOT))

    def test_optional_descendant_of_promoted_managed_node_remains_optional(self):
        self.closure()
        self.manifest = replace(self.manifest, addons=tuple(
            replace(n, dependency_edges=n.dependency_edges + (DependencyEdge(S, '99.0.0', True),))
            if n.addon_id == C else n for n in self.manifest.addons) + (platform(S),))
        self.assertNotIn(S, self.verified())
        self.assertEqual('complete', self._install().outcome)

    def test_missing_captured_child_below_promoted_managed_node_fails_closed(self):
        self.closure()
        self.manifest = replace(self.manifest, addons=tuple(n for n in self.manifest.addons if n.addon_id != Q))
        result = self._install()
        self.assertEqual('failed', result.outcome, (result.code, result.message))
        self.assertEqual([], self.backend.install_calls)
        self.assertEqual([], self.backend.enable_calls)
        self.assertIsNone(self.store.inspect())

    def test_optional_only_closure_is_not_promoted(self):
        self.closure(promote=False)
        self.backend.installed.pop(Q)
        self.assertNotIn(Q, self.verified())
        self.assertEqual('complete', self._install().outcome)

    def test_optional_target_edge_does_not_promote_closure(self):
        self.closure()
        self._install_target(extra_imports=((C, '99.0.0', True),))
        self.backend.installed.pop(Q, None)
        self.assertEqual('complete', self._install().outcome)

    def test_promoted_requirement_receives_all_health_checks(self):
        for fault in ('disabled', 'broken', 'missing-metadata', 'home', 'identity', 'type', 'version', 'minimum', 'builtin'):
            with self.subTest(fault=fault):
                self.closure()
                if fault in ('disabled', 'broken', 'version', 'minimum'):
                    version = {'version': 'unknown', 'minimum': '0.1.0'}.get(fault, '1.0.0')
                    observe(self.backend, Q, version=version)
                    self.backend.installed[Q] = FrozenInstalledAddon(Q, version, fault != 'disabled', fault == 'broken')
                elif fault == 'missing-metadata':
                    self.backend.platform_metadata.pop(Q)
                elif fault == 'home':
                    self.backend.platform_metadata[Q] = replace(self.backend.platform_metadata[Q], origin=InstalledOrigin.HOME)
                elif fault in ('identity', 'type'):
                    self.backend.platform_metadata[Q] = InstalledMetadata(
                        _xml('script.module.wrong' if fault == 'identity' else Q, '1.0.0',
                             point='xbmc.python.pluginsource' if fault == 'type' else 'xbmc.python.module'),
                        InstalledOrigin.APPLICATION)
                else:
                    observe(self.backend, Q, imports=(('xbmc.python', '99.0.0', False),))
                with self.assertRaises(FrozenPlatformRequirementError):
                    self.verified()

    def test_promoted_parent_minimum_applies_to_previously_verified_platform(self):
        self.closure()
        self.manifest = replace(self.manifest, addons=tuple(
            replace(n, dependency_edges=n.dependency_edges + (DependencyEdge(Q, '0.1.0'),))
            if n.addon_id == fi.PLATFORM_ROOT else n for n in self.manifest.addons))
        observe(self.backend, Q, version='0.5.0')
        self._assert_blocked_before_mutation()

    def test_target_cycle_through_promoted_closure_fails_closed(self):
        self.closure()
        observe(self.backend, Q, imports=((fi.PLATFORM_ROOT, '2.6.8', False),))
        self._assert_blocked_before_mutation()

    def test_missing_target_child_below_promoted_platform_fails_closed(self):
        self.closure()
        observe(self.backend, Q, imports=(('script.module.unrepresented', '1.0.0', False),))
        self._assert_blocked_before_mutation()

    def test_resume_rechecks_promoted_requirement_before_mutation(self):
        self.closure()
        restart = SimpleNamespace(outcome='manual_restart_required', transaction=SimpleNamespace(
            transaction_id='33333333-3333-4333-8333-333333333333'))
        first = self._install(configuration_runner=lambda request: restart)
        self.assertEqual('awaiting_restart', first.outcome, (first.code, first.message))
        self.backend.installed.pop(Q)
        calls = (list(self.backend.install_calls), list(self.backend.enable_calls), list(self.policy.calls))
        result = FrozenInstallCoordinator(store=self.store, artifact_store=self.artifacts,
            policy_backend=self.policy, installer=self.backend, manifest_loader=lambda path: self.manifest,
            session_id_provider=lambda: fi.SESSION_B).resume_after_restart()
        self.assertNotEqual('complete', result.outcome)
        self.assertEqual(fi.PLATFORM_CODE, result.code)
        self.assertEqual(calls, (self.backend.install_calls, self.backend.enable_calls, self.policy.calls))
        self.assertIsNotNone(self.store.inspect())

    def test_final_completion_rechecks_promoted_requirement(self):
        self.closure()
        def configure(request):
            self.backend.installed.pop(Q)
            return SimpleNamespace(outcome='complete')
        result = self._install(configuration_runner=configure)
        self.assertEqual('needs_attention', result.outcome, (result.code, result.message))
        self.assertEqual(fi.PLATFORM_CODE, result.code)


class TargetClosurePlan(unittest.TestCase):
    def fixture(self, *, promote=True):
        h = pt.PlanHarness(self)
        h.set_graph(platform=((fi.PLATFORM_ID, '5.1.0', 'xbmc.python.module', ()),
                              (Q, '1.0.0', 'xbmc.python.module', ())))
        h.frozen = replace(h.frozen, addons=tuple(
            replace(n, dependency_edges=(DependencyEdge(fi.PLATFORM_ID, '1.0.0'),
                                        DependencyEdge(pt.MODULE, '2.0.0', True))) if n.addon_id == pt.DEMO else
            replace(n, optional=True, dependency_edges=(DependencyEdge(Q, '1.0.0'),)) if n.addon_id == pt.MODULE else
            replace(n, optional=True) if n.addon_id == Q else n for n in h.frozen.addons))
        h.save_overlay()
        backend = SyntheticBuiltinBackend()
        observe(backend, fi.PLATFORM_ID, version='5.1.0',
                imports=((pt.MODULE, '2.0.0', False),) if promote else ())
        observe(backend, Q)
        service = BuildPlanService(h.plan_owners(platform_backend=backend))
        return h, backend, service

    def test_missing_promoted_platform_blocks_plan(self):
        h, backend, service = self.fixture()
        backend.installed.pop(Q)
        plan = service.preview(h.plan_target())
        self.assertEqual(PlanState.BLOCKED, plan.state)
        self.assertTrue(plan.blockers)

    def test_missing_promoted_platform_never_reports_healthy_repair(self):
        from resources.lib.update_repair_workflow import UpdateRepairWorkflow
        h, backend, service = self.fixture()
        backend.installed.pop(Q)
        ui = Mock()
        UpdateRepairWorkflow(Mock(), service, Mock(), Mock())._check(ui, SimpleNamespace(desired=h.plan_target()))
        ui.repair_show_healthy.assert_not_called()
        ui.repair_show.assert_called_once()

    def test_compatible_promoted_closure_reports_no_changes(self):
        h, backend, service = self.fixture()
        self.assertEqual(PlanState.NO_CHANGES, service.preview(h.plan_target()).state)

    def test_optional_only_missing_platform_still_reports_no_changes(self):
        h, backend, service = self.fixture(promote=False)
        backend.installed.pop(Q)
        self.assertEqual(PlanState.NO_CHANGES, service.preview(h.plan_target()).state)
