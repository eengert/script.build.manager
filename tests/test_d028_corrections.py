"""Regression proofs for the eight D-028 review corrections; disposable fixtures only."""
from dataclasses import replace
from unittest.mock import patch
from tests.test_frozen_install import PlatformProvidedInstallTests, PLATFORM_ID, PLATFORM_ROOT
from tests.test_frozen import _write_addon
from resources.lib.frozen import CaptureStatus, DependencyEdge
from resources.lib.frozen_install import KodiRuntimeFrozenArtifactBackend, verify_platform_requirements, validate_frozen_manifest
from resources.lib.frozen_resolution import default_exact_record, resolved_software_fingerprint, FrozenResolutionError


class RuntimeAuthorityCorrections(PlatformProvidedInstallTests):
    def test_runtime_rejects_replaced_root_after_first_read(self):
        backend = KodiRuntimeFrozenArtifactBackend()
        self.addCleanup(getattr(backend, "close", lambda: None))
        backend._addons_dir = lambda: self.home
        backend._application_addons_dir = lambda: self.application
        backend._rpc = lambda method, params: {"result": {"addons": self.entries}}
        self.assertIsNotNone(backend.read_installed_metadata(PLATFORM_ID))
        old = self.application.with_name('old-addons')
        self.application.rename(old)
        self.application.mkdir()
        _write_addon(self.application, PLATFORM_ID, version='5.1.0', point='xbmc.python.module')
        self.assertIsNone(backend.read_installed_metadata(PLATFORM_ID))

    def test_runtime_rejects_symlink_escape_after_first_read(self):
        backend = KodiRuntimeFrozenArtifactBackend()
        self.addCleanup(getattr(backend, "close", lambda: None))
        backend._addons_dir = lambda: self.home
        backend._application_addons_dir = lambda: self.application
        backend._rpc = lambda method, params: {"result": {"addons": self.entries}}
        self.assertIsNotNone(backend.read_installed_metadata(PLATFORM_ID))
        old = self.application.with_name('old-addons')
        self.application.rename(old)
        self.application.symlink_to(old, target_is_directory=True)
        self.assertIsNone(backend.read_installed_metadata(PLATFORM_ID))

    def test_zero_dependencies_capture_and_install(self):
        _write_addon(self.application, PLATFORM_ID, version='5.1.0', point='xbmc.python.module')
        manifest = self._capture()
        self.assertEqual(CaptureStatus.COMPLETE, manifest.capture_status)
        self.assertEqual((), next(n for n in manifest.addons if n.platform_provided).dependency_edges)
        from resources.lib.frozen import InstalledMetadata, InstalledOrigin
        self.backend.platform_metadata[PLATFORM_ID] = InstalledMetadata(
            (self.application / PLATFORM_ID / 'addon.xml').read_bytes(), InstalledOrigin.APPLICATION)
        self.assertEqual('complete', self._install(manifest=manifest).outcome)

    def test_optional_incoming_minimum_is_not_mandatory(self):
        root = next(n for n in self.manifest.addons if n.addon_id == PLATFORM_ROOT)
        manifest = replace(self.manifest, addons=tuple(
            replace(n, dependency_edges=(DependencyEdge(PLATFORM_ID, '99.0.0', True),))
            if n == root else n for n in self.manifest.addons))
        from tests.test_d028_target_closure import bind_synthetic_edges
        manifest = bind_synthetic_edges(manifest, self.artifacts, {PLATFORM_ROOT})
        self.assertEqual('complete', self._install(manifest=manifest).outcome)

    def test_platform_record_rejected_by_shared_fingerprint(self):
        node = next(n for n in self.manifest.addons if n.platform_provided)
        record = replace(default_exact_record(next(n for n in self.manifest.addons if n.addon_id == PLATFORM_ROOT)),
                         addon_id=node.addon_id, captured_version=node.version, resolved_version=node.version)
        with self.assertRaises(FrozenResolutionError):
            resolved_software_fingerprint(self.manifest, (record,))

    def test_frozen_install_rejects_platform_configuration_before_runner_or_mutation(self):
        from tests.test_build_manager import _desired
        from resources.lib.manifest import ConfigDeclarations, ManagedSettingScope
        from resources.lib.frozen_install import FrozenInstallCoordinator
        desired = replace(_desired(), config=ConfigDeclarations(
            managed_settings=(ManagedSettingScope(PLATFORM_ID, ('quality',)),)))
        with patch.object(FrozenInstallCoordinator, '_configuration_profile', return_value=desired):
            result = self._install(configuration_runner=lambda request: self.fail('configuration reached'))
        self.assertEqual('failed', result.outcome)
        self.assertEqual('PLATFORM_SOFTWARE_IMMUTABLE', result.code)
        self.assertEqual([], self.backend.install_calls)
        self.assertEqual([], self.backend.enable_calls)
        self.assertIsNone(self.store.inspect())

    def test_identity_binding_rejects_platform_artifact_record(self):
        from resources.lib.frozen_resolution import (
            FrozenInstallResolutionManifest, install_plan_fingerprint, _resolved_fingerprint_from_records)
        from resources.lib.build_identity import bind_resolutions, IdentityMismatch
        node = next(n for n in self.manifest.addons if n.platform_provided)
        record = replace(default_exact_record(next(n for n in self.manifest.addons if n.addon_id == PLATFORM_ROOT)),
                         addon_id=node.addon_id, captured_version=node.version, resolved_version=node.version)
        from resources.lib.frozen_resolution import ResolutionState
        record = replace(record, state=ResolutionState.INSTALLED)
        resolution = FrozenInstallResolutionManifest(
            self.manifest.build_id, self.manifest.fingerprint(), install_plan_fingerprint(self.manifest, ()),
            _resolved_fingerprint_from_records(self.manifest.fingerprint(), (record,)), (record,))
        with self.assertRaises(IdentityMismatch):
            bind_resolutions(self.manifest.build_id, self.manifest, resolution, policies=())

    def _target_child(self, child='script.module.zzz-child', edges=()):
        from tests.test_frozen_install import _zip
        from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
        artifact = self.artifacts.import_zip(_zip(child, '1.0.0', requires=tuple(
            (e.addon_id, e.min_version, e.optional) for e in edges)), expected_addon_id=child,
                                             expected_version='1.0.0')
        node = AddonCaptureNode(child, '1.0.0', 'xbmc.python.module', True,
                                ProvenanceStatus.VERIFIED_REPOSITORY,
                                artifact=artifact, dependency_edges=edges)
        self.manifest = replace(self.manifest, addons=self.manifest.addons + (node,))
        self._install_target(extra_imports=((child, '1.0.0', False),))
        return child

    def test_target_mandatory_child_is_installed_before_consuming_managed_parent(self):
        child = self._target_child()
        result = self._install()
        self.assertEqual('complete', result.outcome, (result.code, result.message))
        self.assertLess(self.backend.install_calls.index(child), self.backend.install_calls.index(PLATFORM_ROOT))

    def test_target_mandatory_child_cannot_be_left_disabled(self):
        child = self._target_child()
        self.manifest = replace(self.manifest, addons=tuple(
            replace(n, desired_enabled=False) if n.addon_id == child else n for n in self.manifest.addons))
        self._assert_blocked_before_mutation()

    def test_target_edges_cannot_create_cycle_through_managed_node(self):
        self._target_child(edges=(DependencyEdge(PLATFORM_ID, '1.0.0'),))
        self._assert_blocked_before_mutation()

    def test_optional_only_platform_node_can_be_missing(self):
        self.manifest = replace(self.manifest, addons=tuple(
            replace(n, optional=True) if n.platform_provided else
            replace(n, dependency_edges=(DependencyEdge(PLATFORM_ID, '99.0.0', True),))
            if n.addon_id == PLATFORM_ROOT else n for n in self.manifest.addons))
        from tests.test_d028_target_closure import bind_synthetic_edges
        self.manifest = bind_synthetic_edges(self.manifest, self.artifacts, {PLATFORM_ROOT})
        self._install_target(absent=True)
        self.assertEqual('complete', self._install().outcome)


from tests.test_plan import PlanHarness, PlatformProvidedPlan
from resources.lib.plan_model import PlanState
from resources.lib.frozen_install import FrozenInstalledAddon
from tests.builtin_evidence import SyntheticBuiltinBackend as InMemoryFrozenArtifactBackend, close_python
from resources.lib.frozen import InstalledMetadata, InstalledOrigin
from tests.test_frozen import _xml


class PlatformPlanCorrections(PlatformProvidedPlan):
    def _service(self, h, backend):
        from resources.lib.plan import BuildPlanService
        owners = h.plan_owners()
        object.__setattr__(owners, 'platform_backend', backend)
        return BuildPlanService(owners)

    def _fixture(self):
        h = PlanHarness(self)
        h.set_graph(platform=((self.PLATFORM, '5.1.0', 'xbmc.python.module', ('xbmc.python',)),))
        h.save_overlay()
        backend = InMemoryFrozenArtifactBackend()
        backend.installed[self.PLATFORM] = FrozenInstalledAddon(self.PLATFORM, '6.0.0', True)
        backend.installed['xbmc.python'] = FrozenInstalledAddon('xbmc.python', '3.0.1', True)
        backend.platform_metadata[self.PLATFORM] = InstalledMetadata(
            _xml(self.PLATFORM, '6.0.0', imports=(('xbmc.python', '3.0.0', False),),
                 point='xbmc.python.module'), InstalledOrigin.APPLICATION)
        return h, backend

    def test_missing_platform_requirement_blocks_plan_and_no_changes(self):
        h, backend = self._fixture()
        backend.installed.pop(self.PLATFORM)
        plan = self._service(h, backend).preview(h.plan_target())
        self.assertEqual(PlanState.BLOCKED, plan.state)
        self.assertTrue(plan.blockers)

    def test_missing_platform_requirement_never_reports_healthy_repair(self):
        from unittest.mock import Mock
        from resources.lib.update_repair_workflow import UpdateRepairWorkflow
        from types import SimpleNamespace
        h, backend = self._fixture()
        backend.installed.pop(self.PLATFORM)
        ui = Mock()
        workflow = UpdateRepairWorkflow(Mock(), self._service(h, backend), Mock(), Mock())
        workflow._check(ui, SimpleNamespace(desired=h.plan_target()))
        ui.repair_show_healthy.assert_not_called()
        ui.repair_show.assert_called_once()

    def test_verified_platform_version_binds_review_and_change_is_stale(self):
        h, backend = self._fixture()
        from tests.test_status import DEMO
        del h.kodi.addons[DEMO]
        h.deps.installed.pop(DEMO, None)
        service = self._service(h, backend)
        plan = service.preview(h.plan_target())
        self.assertIsNotNone(plan.review)
        backend.installed[self.PLATFORM] = FrozenInstalledAddon(self.PLATFORM, '7.0.0', True)
        backend.platform_metadata[self.PLATFORM] = InstalledMetadata(
            _xml(self.PLATFORM, '7.0.0', imports=(('xbmc.python', '3.0.0', False),),
                 point='xbmc.python.module'), InstalledOrigin.APPLICATION)
        self.assertFalse(service.validate(h.plan_target(), plan.review).is_current)

import unittest
from types import SimpleNamespace
from resources.lib.manifest import ConfigDeclarations, ManagedSettingScope, PrivateSettingDeclaration, AddonEntry
from resources.lib.config import EffectiveConfiguration, ConfigFile


class PlatformMutationCorrections(unittest.TestCase):
    def test_every_configuration_ownership_route_is_rejected(self):
        from resources.lib.platform_policy import reject_platform_mutations, PlatformMutationError
        from resources.lib.redlight_resource import redlight_declaration
        resource = replace(redlight_declaration(), owner_addon_id=PLATFORM_ID)
        for config in (
            ConfigDeclarations(managed_settings=(ManagedSettingScope(PLATFORM_ID, ('quality',)),)),
            ConfigDeclarations(private_settings=(PrivateSettingDeclaration(PLATFORM_ID, 'token', 'string'),)),
            ConfigDeclarations(managed_files=(f'addon_data/{PLATFORM_ID}/settings.xml',)),
            ConfigDeclarations(structured_private_resources=(resource,)),
        ):
            desired = SimpleNamespace(addons=(), repositories=(), skin=None, config=config)
            with self.subTest(config=config), self.assertRaises(PlatformMutationError):
                reject_platform_mutations(desired, {PLATFORM_ID})

    def test_reconciliation_rejects_platform_addon_state_before_execution(self):
        from tests.test_build_manager import _Owners, _desired, _state
        from resources.lib.build_manager import BuildManager, ReconcileRequest
        desired = _desired(addons=(AddonEntry(PLATFORM_ID, 'disabled'),))
        owners = _Owners(desired, [_state()], (), {})
        backend = InMemoryFrozenArtifactBackend()
        backend.platform_metadata[PLATFORM_ID] = InstalledMetadata(
            _xml(PLATFORM_ID, '5.1.0', point='xbmc.python.module'), InstalledOrigin.APPLICATION)
        object.__setattr__(owners.owners, "platform_backend", backend)
        result = BuildManager(owners.owners).reconcile(ReconcileRequest('/test.json', 'dev'))
        self.assertFalse(result.success)
        self.assertEqual([], owners.sets)
        self.assertEqual([], owners.dependency_installer.calls)

    def test_reconciliation_rejects_platform_public_setting_before_apply(self):
        from tests.test_build_manager import _Owners, _desired, _state
        from resources.lib.build_manager import BuildManager, ReconcileRequest
        desired = replace(_desired(), config=ConfigDeclarations(
            managed_settings=(ManagedSettingScope(PLATFORM_ID, ('quality',)),)))
        owners = _Owners(desired, [_state()], (), {})
        backend = InMemoryFrozenArtifactBackend()
        backend.platform_metadata[PLATFORM_ID] = InstalledMetadata(
            _xml(PLATFORM_ID, '5.1.0', point='xbmc.python.module'), InstalledOrigin.APPLICATION)
        object.__setattr__(owners.owners, "platform_backend", backend)
        with patch.object(owners.owners.config_manager, 'apply', side_effect=AssertionError('mutation')):
            result = BuildManager(owners.owners).reconcile(ReconcileRequest('/test.json', 'dev'))
        self.assertFalse(result.success)

    def test_library_rejects_platform_setting_file_and_layer_targets(self):
        from tests.test_build_library import LibraryTests
        from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
        import json
        for kind in ('setting', 'file', 'layer', 'optional-layer'):
            f = LibraryTests()
            f.setUp()
            try:
                node = AddonCaptureNode(PLATFORM_ID, '5.1.0', 'xbmc.python.module', True,
                                        ProvenanceStatus.UNKNOWN, platform_provided=True,
                                        status=CaptureStatus.PLATFORM_PROVIDED,
                                        dependency_edges=(DependencyEdge('xbmc.python'),))
                f.frozen = replace(f.frozen, schema_version=2, addons=(node,))
                if kind == 'setting':
                    f.raw['config']['managed_settings'][0]['addon_id'] = PLATFORM_ID
                    f.descriptor['settings'][0]['addon_id'] = PLATFORM_ID
                elif kind == 'file':
                    dest = f'addon_data/{PLATFORM_ID}/settings.xml'
                    f.raw['config']['managed_files'] = [dest]
                    f.descriptor['files'][0]['destination'] = dest
                elif kind == 'optional-layer':
                    f.raw['optional'] = [{'id': 'later', 'addons': [{'addon_id': PLATFORM_ID, 'state': 'disabled'}]}]
                else:
                    f.raw['device_profiles']['other']['addons'] = [{'addon_id': PLATFORM_ID, 'state': 'disabled'}]
                f.write_sources()
                from resources.lib.build_library import LibraryError
                with self.subTest(kind=kind), self.assertRaises(LibraryError):
                    f.register()
            finally:
                f.doCleanups()

class RepositoryPlatformCorrections(unittest.TestCase):
    def setUp(self):
        from tests.test_repository_preparation import RepositoryPreparationTests
        self.f = RepositoryPreparationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
        self.f.nodes.append(AddonCaptureNode(
            PLATFORM_ID, '1.0.0', 'xbmc.python.module', True, ProvenanceStatus.UNKNOWN,
            platform_provided=True, status=CaptureStatus.PLATFORM_PROVIDED,
            optional=getattr(self, 'source_optional', False),
            dependency_edges=(DependencyEdge('xbmc.python', '3.0.0'),)))
        self.f.nodes.append(AddonCaptureNode('xbmc.python', '3.0.1', 'system', True,
                                             ProvenanceStatus.UNKNOWN, system=True, status=CaptureStatus.SYSTEM))
        self.f.nodes = list(close_python(replace(self.f.f.fixture.frozen, schema_version=2, addons=tuple(self.f.nodes))).addons)
        self.f.fixture = self.f.f.fixture
        self.f.fixture.frozen = replace(self.f.fixture.frozen, schema_version=2, addons=tuple(self.f.nodes))
        from tests.test_frozen_install import _zip
        from tests.test_status import DEMO
        self.f.package = _zip(DEMO, '2.0.0', requires=((PLATFORM_ID, '5.0.0'),))
        previous = self.f.f.backend
        self.backend = InMemoryFrozenArtifactBackend(
            installed=previous.installed, repository_packages=previous.repository_packages,
            platform_metadata=previous.platform_metadata)
        self.f.f.backend = self.backend
        self.backend.installed[PLATFORM_ID] = FrozenInstalledAddon(PLATFORM_ID, '6.0.0', True)
        self.backend.installed['xbmc.python'] = FrozenInstalledAddon('xbmc.python', '3.0.1', True)
        self.backend.platform_metadata[PLATFORM_ID] = InstalledMetadata(
            _xml(PLATFORM_ID, '6.0.0', imports=(('xbmc.python', '3.0.0', False),),
                 point='xbmc.python.module'), InstalledOrigin.APPLICATION)
        self.target = self.f.target()

    def _prepare(self):
        from resources.lib.repository_preparation import RepositoryPreparationService
        service = RepositoryPreparationService(self.f.store, download=self.f.download)
        service.platform_backend = self.backend
        return service.prepare(self.target)

    def test_repository_preparation_and_plan_use_verified_target_version(self):
        from resources.lib.repository_preparation import PreparationCode
        from resources.lib.resolver import resolve_manifest
        from resources.lib.plan import BuildPlanService, ReadOnlyArtifactStore
        result = self._prepare()
        self.assertEqual(PreparationCode.READY, result.code)
        h = self.f.harness()
        target = replace(self.target, prepared_resolution=result.prepared)
        owners = h.plan_owners(status=h.owners(resolver=resolve_manifest),
                               artifact_store=ReadOnlyArtifactStore(self.f.store.root))
        object.__setattr__(owners, 'platform_backend', self.backend)
        plan = BuildPlanService(owners).preview(target)
        self.assertEqual(PlanState.CHANGES_READY, plan.state, (plan.blockers, plan.gaps))
        self.assertIsNotNone(plan.review)

    def test_restart_restoration_uses_verified_platform_version(self):
        from resources.lib.frozen_install import FrozenInstallPhase
        from resources.lib.frozen_resolution import (default_exact_record, install_plan_fingerprint,
            resolution_fingerprint, ResolutionState)
        from resources.lib.resolver import resolve_manifest
        from types import SimpleNamespace
        from resources.lib.frozen_resolution import InstallResolutionRecord, InstallResolution
        from tests.test_status import DEMO
        from tests.test_plan import REPOSITORY
        metadata = self.f.store.import_zip(self.f.package, expected_addon_id=DEMO, expected_version='2.0.0')
        public, manifest, loader = self.f.install_target.load()
        desired = resolve_manifest(public, 'desk')
        captured = next(n for n in manifest.addons if n.addon_id == DEMO)
        prepared = {DEMO: InstallResolutionRecord(DEMO, captured.version, InstallResolution.REPOSITORY_CURRENT,
                     ResolutionState.RESOLVED, captured.desired_enabled, REPOSITORY, '2.0.0', metadata.sha256, metadata.size)}
        records = tuple(replace(prepared.get(n.addon_id) or default_exact_record(n), state=ResolutionState.INSTALLED)
                        for n in manifest.addons if not n.system and not n.platform_provided
                        and not n.is_absent_optional_dependency)
        transaction = SimpleNamespace(
            policies=desired.frozen_install_policies, resolution_records=records,
            install_plan_fingerprint=install_plan_fingerprint(manifest, desired.frozen_install_policies),
            manifest_fingerprint=manifest.fingerprint(), resolution_fingerprint=resolution_fingerprint(records),
            resolved_software_fingerprint=resolved_software_fingerprint(manifest, records))
        coordinator = self.f.f.coordinator()
        with patch.object(coordinator, '_make_resolution_manifest', return_value=None):
            plan, restored, _ = coordinator._restore_resolution(manifest, transaction)
        self.assertEqual(records, restored)
        self.assertIn(PLATFORM_ID, plan.nodes)


class RepositoryOptionalPlatformCorrections(RepositoryPlatformCorrections):
    """A mandatory repository edge promotes its platform dependency, not unrelated optional nodes."""
    source_optional = True
