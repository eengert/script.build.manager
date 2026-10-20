"""Exact scoped exclusion checks using synthetic cases; no process execution."""
import unittest

from tools.offline_test_suite import PS_ENVIRONMENT_EXCLUSIONS, select_scoped_tests, test_cases


class ScopedDiscoveryTests(unittest.TestCase):
    def cases(self, identities):
        class Case(unittest.TestCase):
            def __init__(self, identity):
                super().__init__()
                self.identity = identity

            def id(self):
                return self.identity

            def runTest(self):
                raise AssertionError('selection must never execute a test')
        return [Case(identity) for identity in identities]

    def test_only_exact_six_methods_are_removed(self):
        others = [PS_ENVIRONMENT_EXCLUSIONS[0] + '_similar',
                  'tests.test_bm_test_app.TestRealPsAndLsof.test_other',
                  'tests.test_security.Security.test_required']
        cases = self.cases([*PS_ENVIRONMENT_EXCLUSIONS, *others])
        suite = unittest.TestSuite([unittest.TestSuite(cases[:4]), unittest.TestSuite(cases[4:])])
        selected, inventory = select_scoped_tests(suite)
        self.assertEqual([*PS_ENVIRONMENT_EXCLUSIONS, *others], inventory)
        self.assertEqual(others, [test.id() for test in test_cases(selected)])

    def test_each_missing_or_misidentified_method_is_refused(self):
        for name in PS_ENVIRONMENT_EXCLUSIONS:
            for replacement in (None, name + '_wrong'):
                with self.subTest(name=name, replacement=replacement):
                    ids = [item for item in PS_ENVIRONMENT_EXCLUSIONS if item != name]
                    if replacement:
                        ids.append(replacement)
                    with self.assertRaises(ValueError):
                        select_scoped_tests(unittest.TestSuite(self.cases(ids)))

    def test_duplicate_excluded_identity_is_refused(self):
        for name in PS_ENVIRONMENT_EXCLUSIONS:
            with self.subTest(name=name):
                ids = [*PS_ENVIRONMENT_EXCLUSIONS, name]
                with self.assertRaises(ValueError):
                    select_scoped_tests(unittest.TestSuite(self.cases(ids)))

    def test_all_other_discovered_occurrences_are_preserved(self):
        other = 'tests.other.Case.test_required'
        ids = [*PS_ENVIRONMENT_EXCLUSIONS, other, other]
        selected, inventory = select_scoped_tests(unittest.TestSuite(self.cases(ids)))
        self.assertEqual(ids, inventory)
        self.assertEqual([other, other], [test.id() for test in test_cases(selected)])

    def test_authorized_names_resolve_to_current_real_methods_once(self):
        expected = {
            'tests.test_bm_test_app.TestRealPsAndLsof.test_real_ps_output_for_this_process_parses',
            'tests.test_bm_test_app.TestRealProcessIdentity.test_real_process_with_p_is_identified',
            'tests.test_bm_test_app.TestRealProcessIdentity.test_real_embedded_portable_text_and_option_value_are_refused',
            'tests.test_bm_test_app.TestRealProcessIdentity.test_real_spoofed_argv0_cannot_supply_executable_identity',
            'tests.test_bm_test_app.TestRealProcessIdentity.test_real_process_without_p_is_refused',
            'tests.test_bm_test_app.TestRealProcessIdentity.test_two_real_processes_are_refused',
        }
        self.assertEqual(expected, set(PS_ENVIRONMENT_EXCLUSIONS))
        for name in PS_ENVIRONMENT_EXCLUSIONS:
            cases = list(test_cases(unittest.defaultTestLoader.loadTestsFromName(name)))
            self.assertEqual([name], [test.id() for test in cases])
