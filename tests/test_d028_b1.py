"""B-1 namespace ambiguity: synthetic XML/ZIPs through real admission and Apply."""
from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resources.lib import frozen as frozen
from resources.lib import frozen_install as fi
from resources.lib import repository_preparation as prep
from resources.lib.plan_model import PlanState
from resources.lib.artifacts import ArtifactStore
from tests import test_frozen as capture
from tests import test_d028_admission as admission
from tests import test_d028_preparation as standalone
from tests.builtin_evidence import core_node
from tests.test_status import DEMO

CORE = '<import addon="xbmc.core" version="0.1.0"/>'
GUI = '<import addon="xbmc.gui" version="999.0.0"/>'
NAMESPACED = '<x:requires xmlns:x="urn:x">' + CORE + '</x:requires>'
PLAIN = '<requires>' + GUI + '</requires>'
BAD = {
    'A_namespaced_first': NAMESPACED + PLAIN,
    'B_plain_first': PLAIN + NAMESPACED,
    'C_two_plain': '<requires>' + CORE + '</requires>' + PLAIN,
    'D_namespaced_only': NAMESPACED,
    'E_namespaced_import': '<requires><x:import xmlns:x="urn:x" addon="xbmc.core" version="0.1.0"/></requires>',
}


def xml(aid, version, body):
    return f'<addon id="{aid}" version="{version}">{body}</addon>'.encode()


class B1DependencyTests(unittest.TestCase):
    def test_ambiguous_and_namespaced_xml_is_refused_by_both_callers(self):
        for label, body in BAD.items():
            for parser in (frozen._parse_dependency_edges, fi._admission_dependency_edges):
                with self.subTest(case=label, parser=parser.__name__):
                    with self.assertRaises(frozen.CaptureError):
                        parser(xml('plugin.test', '1.0.0', body), 'plugin.test')

    def test_valid_required_optional_and_versioned_edges_are_identical(self):
        body = ('<requires><import addon="script.required" version="2.3.4"/>'
                '<import addon="script.optional" version="1.2.0" optional="true"/>'
                '<import addon="xbmc.gui" version="5.17.0"/></requires>')
        expected = (frozen.DependencyEdge('script.optional', '1.2.0', True, ('plugin.test',)),
                    frozen.DependencyEdge('script.required', '2.3.4', False, ('plugin.test',)),
                    frozen.DependencyEdge('xbmc.gui', '5.17.0', False, ('plugin.test',)))
        for parser in (frozen._parse_dependency_edges, fi._admission_dependency_edges):
            self.assertEqual(expected, parser(xml('plugin.test', '1.0.0', body), 'plugin.test'))

    def test_zero_dependencies_absent_and_empty_requires_remain_valid(self):
        for body in ('', '<requires/>'):
            for parser in (frozen._parse_dependency_edges, fi._admission_dependency_edges):
                self.assertEqual((), parser(xml('plugin.test', '1.0.0', body), 'plugin.test'))

    def test_bad_identity_and_optionality_still_fail_closed(self):
        for declaration in ('<import addon="../bad"/>', '<import addon=""/>',
                            '<import addon="script.test" optional="maybe"/>', '<unknown/>'):
            for parser in (frozen._parse_dependency_edges, fi._admission_dependency_edges):
                with self.subTest(declaration=declaration, parser=parser.__name__):
                    with self.assertRaises(frozen.CaptureError):
                        parser(xml('plugin.test', '1.0.0', '<requires>'+declaration+'</requires>'), 'plugin.test')

    def test_capture_cannot_trust_ambiguous_dependency_evidence(self):
        for label, body in BAD.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                aid = 'plugin.test'
                payload = xml(aid, '1.0.0', body)
                backend = frozen.InMemoryInventoryBackend([capture._addon(aid)], {aid: payload},
                    package_cache={(aid, '1.0.0'): [('test.zip', capture._zip(aid, xml_bytes=payload))]})
                result = frozen.capture_frozen_build(backend=backend, store=ArtifactStore(Path(tmp)),
                    root_addon_ids=[aid], build_id='b1', name='B1', created_at='now')
                self.assertFalse(result.complete, label)
                self.assertTrue(result.errors, label)

    def test_resealed_manifest_cannot_hide_gui_from_exact_admission(self):
        f = admission.BuiltinAdmissionTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        m = f.manifest()
        owner = m.addons[0]
        for label, body in BAD.items():
            artifact = f.artifacts.import_zip(capture._zip(owner.addon_id, owner.version,
                xml_bytes=xml(owner.addon_id, owner.version, body)),
                expected_addon_id=owner.addon_id, expected_version=owner.version)
            forged = replace(m, addons=(replace(owner, artifact=artifact,
                dependency_edges=(frozen.DependencyEdge('xbmc.core', '0.1.0'),)), core_node()))
            forged = frozen.FrozenBuildManifest.from_json(forged.to_json())
            for validator in (fi.validate_frozen_manifest, fi.validate_frozen_install_plan):
                with self.subTest(case=label, validator=validator.__name__):
                    with self.assertRaises(fi.FrozenInstallValidationError):
                        validator(forged, f.artifacts)
        self.assertEqual([], f.backend.install_calls)
        self.assertEqual([], f.backend.enable_calls)

    def test_individual_abi_minima_remain_independently_verified(self):
        f = admission.BuiltinAdmissionTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        m = f.manifest()
        owner = m.addons[0]
        body = '<requires><import addon="xbmc.gui" version="5.16.0"/><import addon="xbmc.gui" version="5.17.0"/></requires>'
        artifact = f.artifacts.import_zip(capture._zip(owner.addon_id, owner.version,
            xml_bytes=xml(owner.addon_id, owner.version, body)),
            expected_addon_id=owner.addon_id, expected_version=owner.version)
        edges = frozen._parse_dependency_edges(xml(owner.addon_id, owner.version, body), owner.addon_id)
        self.assertEqual(['5.16.0', '5.17.0'], [edge.min_version for edge in edges])
        m = replace(m, addons=(replace(owner, artifact=artifact, dependency_edges=edges),)+m.addons[1:])
        plan = fi.validate_frozen_manifest(m, f.artifacts)
        with self.assertRaises(fi.FrozenPlatformRequirementError):
            fi.verify_platform_requirements(plan, f.backend, planned_versions=fi._planned_versions(plan, ()))
        self.assertEqual([], f.backend.install_calls)


class B1PreparedApplyTests(unittest.TestCase):
    def exercise(self, body):
        f = standalone.StandalonePreparationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        backend = f.builtin_graph()
        backend.installed = f.f.f.backend.installed
        from resources.lib.build_manager import BuildManager
        from resources.lib.manifest import load_manifest_file
        from resources.lib.restart_coordinator import RestartCoordinator
        from resources.lib.transaction import TransactionStore
        from tests.test_frozen_install import SESSION_A
        source = replace(f.target.standalone_source,
            configuration_manifest_path=str(f.f.f.fixture.manifest_path))
        f.target = replace(f.target, standalone_source=source,
            configuration_manifest_path=source.configuration_manifest_path)
        manager = f.f.f.manager()
        manager = BuildManager(replace(manager._owners, manifest_loader=load_manifest_file,
            config_loader=source.load()[2], frozen_manifest_loader=fi._default_manifest_loader))
        runner = RestartCoordinator(manager, store=f.f.f.restart_store,
            session_id_provider=lambda: SESSION_A)
        f.coordinator.configuration_runner = runner.reconcile
        f.f.package = capture._zip(DEMO, '2.0.0', xml_bytes=xml(DEMO, '2.0.0', body))
        service = f.f.harness().plan_service(artifact_store=f.f.store, platform_backend=backend)
        f.coordinator.installer = backend
        prepared = prep.RepositoryPreparationService(f.f.store, download=f.f.download,
            platform_backend=backend).prepare(f.target)
        target = replace(f.target, prepared_resolution=prepared.prepared) if prepared.prepared else f.target
        plan = service.preview(target)
        original_create = TransactionStore.create
        with f.f.f.isolated(), patch.object(f.coordinator.store, 'create',
                wraps=f.coordinator.store.create) as frozen_create, \
                patch.object(TransactionStore, 'create', autospec=True,
                    side_effect=original_create) as config_create:
            result = f.coordinator.install_prepared(target, plan.review, plan_service=service)
        observed = {'preparation': prepared.code.value, 'preview': plan.state.value,
            'apply_outcome': result.outcome, 'apply_code': result.code, 'apply_message': result.message,
            'transaction_present': f.coordinator.store.inspect() is not None,
            'frozen_transaction_creates': frozen_create.call_count, 'config_transaction_creates': config_create.call_count,
            'updater_mutations': len(f.f.f.policy.calls), 'installs': len(backend.install_calls),
            'configuration_mutations': len(f.f.f.config.mutations)}
        print('B1_PRODUCT_PATH ' + json.dumps(observed), flush=True)
        return f, backend, observed

    def assert_refused(self, body):
        f, backend, observed = self.exercise(body)
        self.assertNotEqual('complete', observed['apply_outcome'], observed)
        self.assertNotEqual(prep.PreparationCode.READY.value, observed['preparation'], observed)
        self.assertNotEqual(PlanState.CHANGES_READY.value, observed['preview'], observed)
        self.assertFalse(observed['transaction_present'], observed)
        self.assertEqual(0, observed['frozen_transaction_creates'], observed)
        self.assertEqual(0, observed['config_transaction_creates'], observed)
        self.assertEqual(0, observed['updater_mutations'], observed)
        self.assertEqual(0, observed['installs'], observed)
        self.assertEqual(0, observed['configuration_mutations'], observed)
        self.assertEqual([], backend.enable_calls)
        f.f.f.assert_no_mutation()

    def test_namespaced_first_repository_prepare_review_apply_is_refused(self):
        self.assert_refused(BAD['A_namespaced_first'])

    def test_remaining_namespace_and_ambiguity_orders_cannot_reach_apply(self):
        for label in list(BAD)[1:]:
            with self.subTest(case=label):
                self.assert_refused(BAD[label])

    def test_ordinary_and_zero_dependency_packages_complete_configured_apply(self):
        for body in ('<requires>' + CORE + '</requires>', ''):
            with self.subTest(body=body):
                f, backend, observed = self.exercise(body)
                self.assertEqual('ready', observed['preparation'], observed)
                self.assertEqual('changes_ready', observed['preview'], observed)
                self.assertEqual('complete', observed['apply_outcome'], observed)
                self.assertEqual(1, observed['frozen_transaction_creates'])
                self.assertGreater(observed['configuration_mutations'], 0)

    def test_previously_prepared_and_reviewed_ambiguous_zip_is_refused_at_apply(self):
        # Simulate retained approval from the rejected parser, then use current
        # real preview/validation/admission at Apply. No source hashing bypass.
        f = standalone.StandalonePreparationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        backend = f.builtin_graph()
        f.f.package = capture._zip(DEMO, '2.0.0',
            xml_bytes=xml(DEMO, '2.0.0', BAD['A_namespaced_first']))
        service = f.f.harness().plan_service(artifact_store=f.f.store, platform_backend=backend)
        legacy = lambda root, aid: next((n for n in root if n.tag.rsplit('}', 1)[-1] == 'requires'), None)
        with patch.object(frozen, '_dependency_requires', legacy):
            prepared = prep.RepositoryPreparationService(f.f.store, download=f.f.download,
                platform_backend=backend).prepare(f.target)
            self.assertEqual(prep.PreparationCode.READY, prepared.code)
            target = replace(f.target, prepared_resolution=prepared.prepared)
            review_plan = service.preview(target)
            self.assertEqual(PlanState.CHANGES_READY, review_plan.state)
        f.coordinator.installer = backend
        with f.f.f.isolated(), patch.object(f.coordinator.store, 'create',
                wraps=f.coordinator.store.create) as creates:
            result = f.coordinator.install_prepared(target, review_plan.review, plan_service=service)
        self.assertNotEqual('complete', result.outcome)
        self.assertEqual(0, creates.call_count)
        self.assertEqual([], backend.install_calls)
        self.assertEqual([], f.f.f.policy.calls)
        self.assertEqual([], f.f.f.config.mutations)
        self.assertIsNone(f.coordinator.store.inspect())


class B1ResumeTests(unittest.TestCase):
    def test_resume_restore_rejects_resealed_ambiguous_source(self):
        from tests.test_frozen_install import FakePolicy, SESSION_A, SESSION_B
        from resources.lib.update_guard import AddonUpdatePolicy
        f = admission.BuiltinAdmissionTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        m = f.manifest()
        owner = m.addons[0]
        artifact = f.artifacts.import_zip(capture._zip(owner.addon_id, owner.version,
            xml_bytes=xml(owner.addon_id, owner.version, BAD['A_namespaced_first'])),
            expected_addon_id=owner.addon_id, expected_version=owner.version)
        m = replace(m, addons=(replace(owner, artifact=artifact,
            dependency_edges=(frozen.DependencyEdge('xbmc.core', '0.1.0'),)), core_node()))
        path = f.root / 'frozen.json'
        path.write_text(m.to_json())
        m = frozen.FrozenBuildManifest.from_json(path.read_text())
        transaction = fi.FrozenInstallTransaction(
            transaction_id='33333333-3333-4333-8333-333333333333', build_id=m.build_id,
            manifest_path=str(path), device_profile_id='desk', manifest_fingerprint=m.fingerprint(),
            phase=fi.FrozenInstallPhase.AWAITING_RESTART, originating_kodi_session_id=SESSION_A,
            original_update_policy=AddonUpdatePolicy.NOTIFY_ONLY,
            created_at='2026-10-21T00:00:00Z', updated_at='2026-10-21T00:00:00Z')
        store = fi.FrozenInstallStore(f.root/'transaction')
        store.create(transaction)
        durable = store.inspect()
        f.backend.installed[owner.addon_id] = fi.FrozenInstalledAddon(owner.addon_id, owner.version, True)
        policy = FakePolicy(AddonUpdatePolicy.NEVER_CHECK)
        coordinator = fi.FrozenInstallCoordinator(store=store, artifact_store=f.artifacts,
            policy_backend=policy, installer=f.backend, session_id_provider=lambda: SESSION_B)
        before = store.transaction_path.read_bytes()
        legacy = lambda root, aid: next((n for n in root if n.tag.rsplit('}', 1)[-1] == 'requires'), None)
        with patch.object(frozen, '_dependency_requires', legacy):
            coordinator._restore_resolution(m, durable)  # faithfully reachable with rejected parser
        with self.assertRaises(fi.FrozenInstallValidationError):
            coordinator._restore_resolution(m, durable)
        self.assertEqual(before, store.transaction_path.read_bytes())
        self.assertEqual([], policy.calls)
        self.assertEqual([], f.backend.install_calls)
        self.assertEqual([], f.backend.enable_calls)


class B1MutationTests(unittest.TestCase):
    def assert_detected(self, case):
        result = unittest.TestResult()
        case.run(result)
        self.assertEqual([], result.errors, str(result.errors))
        self.assertEqual([], result.skipped)
        self.assertGreater(len(result.failures), 0, 'B-1 protection removal escaped assertions')

    def test_selector_removal_reopens_actual_prepared_apply_and_is_detected(self):
        legacy = lambda root, aid: next((n for n in root if n.tag.rsplit('}', 1)[-1] == 'requires'), None)
        with patch.object(frozen, '_dependency_requires', legacy):
            self.assert_detected(B1PreparedApplyTests('test_namespaced_first_repository_prepare_review_apply_is_refused'))
        print('B1_MUTATION_ASSERTION_PASS shared_selector:configured_prepare_review_apply', flush=True)

    def test_namespace_import_guard_removal_is_detected(self):
        import inspect
        source = inspect.getsource(frozen._parse_dependency_edges)
        before = 'if child.tag != "import":'
        self.assertIn(before, source)
        namespace = dict(frozen.__dict__)
        exec(compile(source.replace(before, 'if child.tag.rsplit("}", 1)[-1] != "import":'),
            '<isolated B-1 import guard mutation>', 'exec'), namespace)
        with patch.object(frozen, '_parse_dependency_edges', namespace['_parse_dependency_edges']):
            self.assert_detected(B1DependencyTests('test_ambiguous_and_namespaced_xml_is_refused_by_both_callers'))
        print('B1_MUTATION_ASSERTION_PASS namespace_import:dependency_extraction', flush=True)
