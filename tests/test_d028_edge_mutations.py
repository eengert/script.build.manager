"""Guard removal must cause an assertion failure, never count test errors."""
import inspect
import textwrap
import unittest
from unittest.mock import patch
from resources.lib import frozen_install as fi
from tests import test_d028_exact_edges as exact
from tests import test_d028_admission as admission


class ExactEdgeMutationTests(unittest.TestCase):
    def mutation(self, function, before, after, case_type, test):
        def run():
            result = unittest.TestResult()
            case_type(test).run(result)
            return result
        # AF3 tests normally obtain these through unittest's class fixture.
        if case_type is exact.ExactArtifactEdgesTests:
            case_type.setUpClass()
        baseline = run()
        self.assertEqual((0, 0, 0), (len(baseline.failures), len(baseline.errors), len(baseline.skipped)),
                         str(baseline.errors or baseline.failures))
        source = textwrap.dedent(inspect.getsource(getattr(fi, function)))
        self.assertIn(before, source)
        namespace = dict(fi.__dict__)
        exec(compile(source.replace(before, after, 1), '<isolated guard mutation>', 'exec'), namespace)
        with patch.object(fi, function, namespace[function]):
            mutant = run()
        self.assertEqual([], mutant.errors, str(mutant.errors))
        self.assertEqual([], mutant.skipped)
        self.assertGreater(len(mutant.failures), 0, 'guard removal did not trigger the security assertion')
        print('MUTATION_ASSERTION_PASS ' + function + ':' + test, flush=True)

    def test_artifact_equality_guard(self):
        self.mutation('_validate_frozen_manifest_core',
            'if _canonical_artifact_edges(actual_edges, node.addon_id) != _canonical_artifact_edges(',
            'if False and _canonical_artifact_edges(actual_edges, node.addon_id) != _canonical_artifact_edges(',
            exact.ExactArtifactEdgesTests, 'test_v2_resealed_manifest_drops_gui_edge_and_node')

    def test_admission_binding_guard(self):
        self.mutation('verify_platform_requirements',
            'target_requirements[node.addon_id] = tuple(target_requirements.get(node.addon_id, ())) + tuple(exact_edges)',
            'pass', exact.ExactArtifactEdgesTests,
            'test_bound_artifact_requirements_survive_manifest_edge_removal_at_admission')

    def test_unavailable_binding_guard(self):
        self.mutation('verify_platform_requirements',
            'raise _platform_unsatisfied("exact artifact requirements are unavailable: " + node.addon_id)',
            'pass', exact.ExactArtifactEdgesTests, 'test_unbound_managed_plan_is_not_admission_authority')

    def test_f7_replacement_minima(self):
        self.mutation('_repository_required_addon_ids',
            'required.dependencies[addon_id] = edges', 'required.dependencies[addon_id] = ()',
            admission.BuiltinAdmissionTests, 'test_repository_actual_stronger_minimum_survives_id_collection')


class PreparationBoundaryMutationTests(unittest.TestCase):
    def assert_detected(self, owner, method, before, after, case_type, test):
        def run():
            result = unittest.TestResult()
            case_type(test).run(result)
            return result
        baseline = run()
        self.assertEqual((0, 0, 0), (len(baseline.failures), len(baseline.errors), len(baseline.skipped)),
                         str(baseline.errors or baseline.failures))
        source = textwrap.dedent(inspect.getsource(getattr(owner, method)))
        self.assertIn(before, source)
        namespace = dict(inspect.getmodule(getattr(owner, method)).__dict__)
        exec(compile(source.replace(before, after), '<isolated preparation guard mutation>', 'exec'), namespace)
        with patch.object(owner, method, namespace[method]):
            mutant = run()
        self.assertEqual([], mutant.errors, str(mutant.errors))
        self.assertEqual([], mutant.skipped)
        self.assertTrue(mutant.failures, 'critical guard removal escaped the intended assertion')
        print('MUTATION_ASSERTION_PASS ' + method + ':' + test, flush=True)

    def test_preparation_records_are_supplied_to_admission(self):
        from resources.lib.repository_preparation import RepositoryPreparationService
        from tests import test_d028_preparation as cases
        self.assert_detected(RepositoryPreparationService, 'prepare',
            'skipped=skipped, resolutions=records,', 'skipped=skipped,',
            cases.StandalonePreparationTests, 'test_prepare_review_apply_pins_bytes_with_repository_absent')

    def test_standalone_actual_prepared_identity_needs_fresh_review(self):
        from tests import test_d028_preparation as cases
        self.assert_detected(fi.FrozenInstallCoordinator, 'install',
            'not plan_service.validate(standalone_target, review).is_current', 'False',
            cases.StandalonePreparationTests, 'test_changed_prepared_identity_requires_new_review')

    def test_nonheld_resume_cannot_bypass_common_package_admission(self):
        from tests import test_d028_preparation as cases
        self.assert_detected(fi, 'ensure_frozen_resume_registry_ready',
            'plan, records, _ = coordinator._restore_resolution(manifest, transaction)',
            'plan, records = None, ()', cases.LinkedResumeAdmissionTests,
            'test_nonheld_linked_resume_checks_packages_before_early_return')
