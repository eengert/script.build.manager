"""Standalone prepared continuation and mutation-order evidence, synthetic bytes only."""
from dataclasses import replace
from unittest.mock import patch
import unittest
from resources.lib import repository_preparation as prep
from resources.lib import frozen_install as fi
from resources.lib.plan import PlanTarget
from resources.lib.plan_model import DecisionChoice, PlanState, ReviewFreshness
from resources.lib.frozen_resolution import ResolutionChoice
from tests import test_repository_preparation as preparation_fixture
from tests.test_status import DEMO
from tests.test_frozen_install import _zip


class StandalonePreparationTests(unittest.TestCase):
    def setUp(self):
        self.f = preparation_fixture.RepositoryPreparationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.target()  # write faithful captured source, no runtime access
        f = self.f.f.fixture
        (f.packages / "shared").mkdir(parents=True)
        f.write_sources()
        source = prep.StandalonePreparationSource(str(f.frozen_path), f.frozen.fingerprint(),
            'desk', tuple(prep.resolve_manifest(
                __import__('resources.lib.manifest', fromlist=['load_manifest_file']).load_manifest_file(str(f.manifest_path)),
                'desk').frozen_install_policies), None, str(f.packages))
        self.target = PlanTarget('', 'desk', str(f.frozen_path), standalone_source=source,
                                choices=((DEMO, DecisionChoice.INSTALL_CURRENT),))
        h = self.f.harness()
        for node in self.f.nodes:
            h.kodi.addons.pop(node.addon_id, None)
            h.deps.installed.pop(node.addon_id, None)
        self.service = h.plan_service(artifact_store=self.f.store)
        self.coordinator = self.f.f.coordinator()
        self.coordinator.configuration_runner = None

    def prepare(self):
        result = prep.RepositoryPreparationService(self.f.store, download=self.f.download,
                                                   platform_backend=self.f.f.backend).prepare(self.target)
        self.assertEqual(prep.PreparationCode.READY, result.code)
        return replace(self.target, prepared_resolution=result.prepared)

    def test_unresolved_decisions_never_receive_apply_identity(self):
        undecided = self.service.preview(replace(self.target, choices=()))
        self.assertEqual(PlanState.DECISION_REQUIRED, undecided.state, undecided.to_safe_dict())
        plan = self.service.preview(self.target)
        self.assertEqual(PlanState.RESOLUTION_REQUIRED, plan.state, plan.to_safe_dict())
        self.assertIsNone(plan.review)
        with self.f.f.isolated():
            result = self.coordinator.install(self.f.f.fixture.frozen,
                manifest_path=self.target.software_manifest_path, device_profile_id='desk',
                install_policies=self.target.standalone_source.policies,
                resolution_choices={DEMO: ResolutionChoice.INSTALL_CURRENT})
        self.assertEqual('PREPARATION_REQUIRED', result.code)
        self.assertEqual('preparation_required', result.outcome)
        self.assertEqual([], self.f.downloads)
        self.f.f.assert_no_mutation()

    def test_prepare_review_apply_pins_bytes_with_repository_absent(self):
        events = []
        download = self.f.download
        def acquire(*a, **kw):
            self.assertIsNone(self.f.f.store.inspect())
            self.assertEqual([], self.f.f.backend.install_calls)
            self.assertEqual([], self.f.f.policy.calls)
            events.append('download')
            return download(*a, **kw)
        self.f.download = acquire
        target = self.prepare()
        plan = self.service.preview(target)
        self.assertEqual(PlanState.CHANGES_READY, plan.state, plan.to_safe_dict())
        self.assertEqual('2.0.0', next(r for r in plan.software if r.addon_id == DEMO).version)
        self.assertEqual(ReviewFreshness.CURRENT, self.service.validate(target, plan.review).freshness)
        self.f.package = b'changed remote after approval'
        original_create = self.coordinator.store.create
        def create(t):
            self.assertEqual(['download', 'download'], events)
            self.assertEqual([], self.f.f.policy.calls)
            self.assertEqual([], self.f.f.backend.install_calls)
            events.append('transaction')
            return original_create(t)
        with self.f.f.isolated(), patch.object(self.coordinator.store, 'create', side_effect=create), \
             patch.object(self.f.f.backend, 'resolve_repository_current', side_effect=AssertionError('late fetch')):
            result = self.coordinator.install_prepared(target, plan.review, plan_service=self.service)
        self.assertEqual('complete', result.outcome, result)
        self.assertEqual(['download', 'download', 'transaction'], events)
        record = next(r for r in result.resolution_manifest.records if r.addon_id == DEMO)
        self.assertEqual(target.prepared_resolution.records[0].artifact_sha256, record.artifact_sha256)

    def test_missing_or_corrupt_prepared_bytes_blocks_before_transaction(self):
        target = self.prepare()
        review = self.service.preview(target).review
        self.f.store.artifact_path(target.prepared_resolution.records[0].artifact_sha256).write_bytes(b'corrupt')
        with self.f.f.isolated():
            result = self.coordinator.install_prepared(target, review, plan_service=self.service)
        self.assertEqual('REVIEW_REQUIRED', result.code)
        self.f.f.assert_no_mutation()
        self.assertIsNone(self.f.f.store.inspect())

    def test_changed_prepared_identity_requires_new_review(self):
        old = self.prepare()
        review = self.service.preview(old).review
        self.f.package = _zip(DEMO, '3.0.0')
        self.f.index = f'<addons><addon id="{DEMO}" version="3.0.0"/></addons>'.encode()
        self.f.download = lambda url, **kw: self.f.index if url.endswith('addons.xml') else self.f.package
        new = self.prepare()
        with self.f.f.isolated():
            result = self.coordinator.install_prepared(new, review, plan_service=self.service)
        self.assertEqual('REVIEW_REQUIRED', result.code)
        self.f.f.assert_no_mutation()

    def test_low_level_apply_cannot_substitute_another_prepared_record(self):
        target = self.prepare()
        review = self.service.preview(target).review
        self.f.package = _zip(DEMO, '2.0.0')  # same version, different actual ZIP requirements
        other = self.prepare()
        self.assertNotEqual(other.prepared_resolution, target.prepared_resolution)
        with self.f.f.isolated():
            result = self.coordinator.install(None, manifest_path=target.software_manifest_path,
                configuration_manifest_path='', device_profile_id='desk',
                install_policies=target.standalone_source.policies,
                resolution_choices={DEMO: ResolutionChoice.INSTALL_CURRENT},
                prepared_resolution=other.prepared_resolution, standalone_target=target,
                review=review, plan_service=self.service)
        self.assertEqual('failed', result.outcome)
        self.f.f.assert_no_mutation()

    def test_configured_continuation_requires_its_configuration_owner(self):
        source = replace(self.target.standalone_source,
                         configuration_manifest_path=str(self.f.f.fixture.manifest_path))
        self.target = replace(self.target, standalone_source=source,
                              configuration_manifest_path=source.configuration_manifest_path)
        target = self.prepare()
        review = self.service.preview(target).review
        with self.f.f.isolated():
            result = self.coordinator.install_prepared(target, review, plan_service=self.service)
        self.assertEqual('CONFIGURATION_RUNNER_REQUIRED', result.code)
        self.f.f.assert_no_mutation()

    def test_configured_continuation_reuses_real_configuration_and_restart_services(self):
        from resources.lib.build_manager import BuildManager
        from resources.lib.manifest import load_manifest_file
        from resources.lib.restart_coordinator import RestartCoordinator
        from tests.test_frozen_install import SESSION_A
        source = replace(self.target.standalone_source,
                         configuration_manifest_path=str(self.f.f.fixture.manifest_path))
        self.target = replace(self.target, standalone_source=source,
                              configuration_manifest_path=source.configuration_manifest_path)
        target = self.prepare()
        plan = self.service.preview(target)
        self.assertEqual(PlanState.CHANGES_READY, plan.state, plan.to_safe_dict())
        manager = self.f.f.manager()
        manager = BuildManager(replace(manager._owners, manifest_loader=load_manifest_file,
            config_loader=source.load()[2], frozen_manifest_loader=fi._default_manifest_loader))
        runner = RestartCoordinator(manager, store=self.f.f.restart_store,
                                    session_id_provider=lambda: SESSION_A)
        self.coordinator.configuration_runner = runner.reconcile
        with self.f.f.isolated():
            result = self.coordinator.install_prepared(target, plan.review, plan_service=self.service)
        self.assertEqual('complete', result.outcome, (result.code, result.message))
        self.assertEqual('high', self.f.f.config.settings[(DEMO, 'quality')])
        self.assertEqual(b'<keymap/>', self.f.f.config.files['userdata/keymaps/demo.xml'])

    def test_replacement_unavailable_no_transaction(self):
        self.f.index = b'<addons/>'
        result = prep.RepositoryPreparationService(self.f.store, download=self.f.download,
            platform_backend=self.f.f.backend).prepare(self.target)
        self.assertEqual(prep.PreparationCode.ADDON_UNAVAILABLE, result.code)
        self.assertIsNone(self.f.f.store.inspect())
        self.f.f.assert_no_mutation()

    def builtin_graph(self):
        from pathlib import Path
        from tests.builtin_evidence import SyntheticBuiltinBackend, core_node
        from resources.lib.frozen import AddonCaptureNode, CaptureStatus, DependencyEdge, ProvenanceStatus
        gui = AddonCaptureNode('xbmc.gui', '5.17.0', 'system', True,
            ProvenanceStatus.UNKNOWN, system=True, status=CaptureStatus.SYSTEM,
            dependency_edges=(DependencyEdge('xbmc.core', '0.1.0'),))
        frozen = replace(self.f.f.fixture.frozen, addons=self.f.f.fixture.frozen.addons + (gui, core_node()))
        Path(self.target.software_manifest_path).write_text(frozen.to_json())
        source = replace(self.target.standalone_source, admitted_fingerprint=frozen.fingerprint())
        self.target = replace(self.target, standalone_source=source)
        backend = SyntheticBuiltinBackend()
        backend.builtin_state['xbmc.gui'] = fi.FrozenInstalledAddon('xbmc.gui', '5.17.0', True)
        backend.builtin_abis['xbmc.gui'] = '5.17.0'
        return backend

    def test_stronger_zip_requirement_refuses_before_import_or_mutation(self):
        backend = self.builtin_graph()
        self.f.package = _zip(DEMO, '2.0.0', requires=(('xbmc.gui', '999.0.0'),))
        with patch.object(self.f.store, 'import_zip', side_effect=AssertionError('premature import')):
            result = prep.RepositoryPreparationService(self.f.store, download=self.f.download,
                platform_backend=backend).prepare(self.target)
        self.assertEqual(prep.PreparationCode.INCOMPATIBLE, result.code)
        self.f.f.assert_no_mutation()

    def test_source_change_during_preparation_is_rejected(self):
        original = self.f.download
        def changed(*a, **kw):
            data = original(*a, **kw)
            from pathlib import Path
            Path(self.target.software_manifest_path).write_text('{}')
            return data
        result = prep.RepositoryPreparationService(self.f.store, download=changed,
            platform_backend=self.f.f.backend).prepare(self.target)
        self.assertEqual(prep.PreparationCode.TARGET_INVALID, result.code)
        self.f.f.assert_no_mutation()

    def test_lost_builtin_proof_after_review_blocks_before_transaction(self):
        backend = self.builtin_graph()
        self.f.package = _zip(DEMO, '2.0.0', requires=(('xbmc.gui', '5.17.0'),))
        result = prep.RepositoryPreparationService(self.f.store, download=self.f.download,
                                                  platform_backend=backend).prepare(self.target)
        self.assertEqual(prep.PreparationCode.READY, result.code)
        target = replace(self.target, prepared_resolution=result.prepared)
        h = self.f.harness()
        service = h.plan_service(artifact_store=self.f.store, platform_backend=backend)
        plan = service.preview(target)
        self.assertEqual(PlanState.CHANGES_READY, plan.state, plan.to_safe_dict())
        backend.builtin_state.pop('xbmc.gui')
        self.coordinator.installer = backend
        with self.f.f.isolated():
            result = self.coordinator.install_prepared(target, plan.review, plan_service=service)
        self.assertEqual('REVIEW_REQUIRED', result.code)
        self.assertIsNone(self.f.f.store.inspect())
        self.assertEqual([], self.f.f.policy.calls)
        self.assertEqual([], backend.install_calls)


class LinkedResumeAdmissionTests(unittest.TestCase):
    def test_nonheld_linked_resume_checks_packages_before_early_return(self):
        from types import SimpleNamespace
        from tests import test_library_install as lib
        from tests.test_frozen_install import SESSION_B
        f = lib.LibraryInstallTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        target = f.target()
        initial = f.awaiting(target)
        self.assertFalse(initial.transaction.activation_hold_ids)
        request = f.restart_store.inspect().request
        preview = SimpleNamespace(request=request, success=True)
        coordinator = f.coordinator(session=SESSION_B)
        def check():
            return fi.ensure_frozen_resume_registry_ready(SimpleNamespace(request=request), preview, SESSION_B,
                store=f.store, artifact_store=f.artifacts, policy_backend=f.policy,
                coordinator_factory=lambda **kw: coordinator,
                registry_backend=SimpleNamespace(refresh_local_addons=lambda: self.fail('nonheld registry refresh')))
        before = (f.store.inspect(), list(f.policy.calls), list(f.config.mutations), list(f.backend.install_calls))
        self.assertTrue(check().allowed)
        digest = initial.transaction.resolution_records[0].artifact_sha256
        f.artifacts.artifact_path(digest).write_bytes(b'corrupt')
        self.assertFalse(check().allowed)
        self.assertEqual(before, (f.store.inspect(), f.policy.calls, f.config.mutations, f.backend.install_calls))

    def test_held_retry_validates_retained_source_bytes_before_import(self):
        from tests import test_frozen_install as old
        f = old.FrozenInstallTest()
        f.setUp()
        self.addCleanup(f.tearDown)
        manifest, profile, source, coordinator, held = f._held_redlight_retry_case()
        source.artifact_path(manifest.addons[0].artifact.sha256).write_bytes(b'corrupt')
        before = (f.store.inspect(), list(f.policy.calls), list(f.backend.install_calls))
        with patch.object(f.artifacts, 'import_zip', side_effect=AssertionError('premature artifact import')) as write:
            result = coordinator.retry_held_quiescence(expected_transaction=held,
                current_session_id=old.SESSION_B, artifact_source_store=source,
                restart_store=f._restart_store())
        self.assertEqual('FROZEN_HELD_RETRY_VALIDATION_FAILED', result.code)
        write.assert_not_called()
        self.assertEqual(before, (f.store.inspect(), f.policy.calls, f.backend.install_calls))
