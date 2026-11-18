"""Synthetic offline tests for the D-032 practical precondition assessment."""
import copy
import json
import unittest
from unittest import mock

from tools import bm_practical_precondition as precondition
from tools import bm_public_preservation_witness as witness

SECRET = 'synthetic-private-precondition-value'
EXACT_ROWS = [('EXACT', (), 0)] * 5
OUTPUT_VOCABULARY = frozenset((
    'schema', 'assessment', 'reason', 'verdict', 'qualification', 'prerequisites', 'limitations',
    'id', 'status', 'counts', precondition.SCHEMA, 'INCONCLUSIVE', 'NOT_DECIDED', 'not_qualified',
    'MET', 'NOT_MET', 'UNVERIFIED', 'EXACT', 'MAINTENANCE_ONLY', 'MEANINGFUL',
    'S1', 'S2', 'S5', 'S7', 'FIVE_FILE', 'OPERATION_CORRELATION', 'EXPECTED_RESULT',
    'S4', 'S5_DATABASE', 'S6', 'S8', 'S9',
    'input_invalid', 'internal_error', 'not_reached', 'prerequisite_not_met',
    'prerequisite_unverified', 'limitation_unverified',
    'library_selection_or_tree_changed', 'library_selection_and_tree_match', 'witness_absent',
    'artifact_or_association_changed', 'artifacts_and_association_match',
    'identity_or_enabled_changed', 'identity_and_enabled_match', 'enabled_state_unavailable',
    'addons33_exact', 'addons33_inconclusive', 'addons33_not_exact', 'addons33_exact_and_identity_match',
    'quit_verified', 'quit_not_verified', 'quit_unverified',
    'source_binding_verified', 'source_binding_failed', 'source_binding_unverified',
    'owner_absent', 'owner_present', 'owner_unverified',
    'pending_publication_absent', 'pending_publication_present', 'pending_publication_unverified',
    'bundle_unchanged', 'bundle_changed', 'bundle_unverified', 'owner_pending_quit_and_source_verified',
    'eligible_classifications', 'meaningful_classification', 'classification_inconclusive',
    'correlation_verified', 'correlation_broken', 'correlation_missing', 'not_supplied',
    'no_witness', 'other_addons33_content_unverified', 'no_unmanaged_census',
    'no_source_tree_census', 'scenario_dependent',
))


def public(**changes):
    """Synthetic public witnesses with the shape public_state returns."""
    value = {
        'bundle': {'identifier': 'org.xbmc.kodi', 'version': '21.3'},
        'settings': {'readable': True, 'active_skin': 'skin.estuary', 'updater_policy': 'NOTIFY_ONLY'},
        'addons': {'count': 2, 'enabled_state_source': 'addons_db', 'id_mismatch': 0,
                   'skipped_invalid_names': 0, 'skipped_non_directories': 0, 'unreadable_addon_xml': 0,
                   'entries': [{'enabled': True, 'id': 'script.synthetic', 'version': '1.0.0'},
                               {'enabled': False, 'id': 'script.other', 'version': '2.0.0'}]},
        'library': {'root_present': True,
                    'registry': {'file_present': True, 'sha256': 'a' * 64, 'size': 120,
                                 'entry_count': 1, 'entry_ids': [SECRET]},
                    'selection': {'file_present': True, 'selected': True, 'sha256': 'b' * 64, 'size': 30,
                                  'entry_id': SECRET, 'device_profile_id': 'profile-one'}},
        'trees': {'build-library': {'registry.json': 'c' * 64},
                  'install_resolutions': {'resolution.json': 'd' * 64},
                  'frozen-artifacts': {'artifact.json': 'e' * 64}},
        'association': {'entry_id': SECRET, 'artifact': 'f' * 64},
        'selection': (SECRET, 'profile-one'),
        'owners_absent': True,
        'pending_publication_absent': True,
    }
    value.update(changes)
    return value


def practical(*rows):
    files = []
    labels = []
    for name, (label, maintenance, count) in zip(witness.FILES, rows):
        files.append({'file': name, 'classification': label,
                      'maintenance': [list(item) for item in maintenance], 'meaningful_count': count})
        labels.append(label)
    aggregate = next((label for label in ('INCONCLUSIVE', 'MEANINGFUL', 'MAINTENANCE_ONLY')
                      if label in labels), 'EXACT')
    return {'schema': 'bm-a15-practical-classification/1', 'classification': aggregate, 'files': files,
            'verdict': 'NOT_DECIDED', 'qualification': 'not_qualified'}


def after_block(*rows):
    return {'acquisition': 'ACQUIRED', 'scope_result': 'PRESERVED',
            'files': [{'file': name, 'status': 'PRESERVED'} for name in witness.FILES],
            'practical': practical(*(rows or EXACT_ROWS))}


def begin_block():
    return {'acquisition': 'ACQUIRED', 'scope_result': 'UNVERIFIED',
            'files': [{'file': name, 'status': 'UNVERIFIED'} for name in witness.FILES]}


def assess(**overrides):
    arguments = {'public_before': public(), 'public_after': public(), 'begin': begin_block(),
                 'after': after_block(), 'quit_verified': True, 'source_bound': True, 'correlation': None}
    arguments.update(overrides)
    return precondition.assess(**arguments)


def entry(block, identifier):
    return next(item for item in block['prerequisites'] if item['id'] == identifier)


def strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


class PreconditionTests(unittest.TestCase):
    def test_exact_witnesses_meet_each_assessed_prerequisite_yet_stay_inconclusive(self):
        block = assess()
        for identifier in ('S1', 'S2', 'S5', 'S7', 'FIVE_FILE'):
            self.assertEqual(entry(block, identifier)['status'], 'MET', identifier)
        self.assertEqual(entry(block, 'FIVE_FILE')['counts'],
                         {'EXACT': 5, 'MAINTENANCE_ONLY': 0, 'MEANINGFUL': 0, 'INCONCLUSIVE': 0})
        self.assertEqual(entry(block, 'OPERATION_CORRELATION'),
                         {'id': 'OPERATION_CORRELATION', 'status': 'UNVERIFIED', 'reason': 'correlation_missing'})
        self.assertEqual(entry(block, 'EXPECTED_RESULT'),
                         {'id': 'EXPECTED_RESULT', 'status': 'UNVERIFIED', 'reason': 'not_supplied'})
        self.assertEqual(block['assessment'], 'INCONCLUSIVE')
        self.assertEqual(block['reason'], 'prerequisite_unverified')
        self.assertEqual(block['verdict'], 'NOT_DECIDED')
        self.assertEqual(block['qualification'], 'not_qualified')

    def test_verified_correlation_still_inconclusive_because_expected_result_is_unsupplied(self):
        block = assess(correlation='VERIFIED')
        self.assertEqual(entry(block, 'OPERATION_CORRELATION')['status'], 'MET')
        self.assertEqual(entry(block, 'EXPECTED_RESULT')['status'], 'UNVERIFIED')
        self.assertEqual(block['reason'], 'prerequisite_unverified')
        self.assertEqual(block['assessment'], 'INCONCLUSIVE')

    def test_unjustified_scope_limitations_stay_unverified_and_listed(self):
        block = assess(correlation='VERIFIED')
        limitations = {item['id']: item for item in block['limitations']}
        self.assertEqual(set(limitations), {'S4', 'S5_DATABASE', 'S6', 'S8', 'S9'})
        for item in limitations.values():
            self.assertEqual(item['status'], 'UNVERIFIED')

    def test_changed_library_selection_or_build_tree_fails_s1(self):
        base = public()
        library = copy.deepcopy(base['library'])
        library['registry']['sha256'] = '0' * 64
        trees = copy.deepcopy(base['trees'])
        trees['build-library']['registry.json'] = '0' * 64
        changes = [{'library': library}, {'selection': (SECRET, 'profile-two')}, {'trees': trees}]
        for change in changes:
            with self.subTest(change=sorted(change)):
                block = assess(public_after=public(**change))
                self.assertEqual(entry(block, 'S1'),
                                 {'id': 'S1', 'status': 'NOT_MET', 'reason': 'library_selection_or_tree_changed'})
                self.assertEqual(block['reason'], 'prerequisite_not_met')

    def test_changed_frozen_artifacts_install_resolutions_or_association_fails_s2(self):
        base = public()
        for name in ('frozen-artifacts', 'install_resolutions'):
            with self.subTest(tree=name):
                trees = copy.deepcopy(base['trees'])
                trees[name] = {'changed.json': '0' * 64}
                block = assess(public_after=public(trees=trees))
                self.assertEqual(entry(block, 'S2')['status'], 'NOT_MET')
                self.assertEqual(entry(block, 'S2')['reason'], 'artifact_or_association_changed')
        block = assess(public_after=public(association={'entry_id': SECRET, 'artifact': '0' * 64}))
        self.assertEqual(entry(block, 'S2')['status'], 'NOT_MET')

    def test_addons33_identity_or_enabled_change_fails_s5(self):
        flipped = copy.deepcopy(public()['addons'])
        flipped['entries'][1]['enabled'] = True
        block = assess(public_after=public(addons=flipped))
        self.assertEqual(entry(block, 'S5')['status'], 'NOT_MET')
        self.assertEqual(entry(block, 'S5')['reason'], 'identity_or_enabled_changed')

    def test_addons33_meaningful_classification_fails_s5(self):
        block = assess(after=after_block(('MEANINGFUL', (), 1), *EXACT_ROWS[1:]))
        self.assertEqual(entry(block, 'S5'), {'id': 'S5', 'status': 'NOT_MET', 'reason': 'addons33_not_exact'})

    def test_addons_version_is_outside_the_s5_scope(self):
        versioned = copy.deepcopy(public()['addons'])
        versioned['entries'][0]['version'] = '9.9.9'
        block = assess(public_after=public(addons=versioned))
        self.assertEqual(entry(block, 'S5')['status'], 'MET')

    def test_permitted_m1_and_m2_maintenance_keeps_five_file_eligibility(self):
        rows = [('EXACT', (), 0),
                ('MAINTENANCE_ONLY', (('M2_SIZES_USECOUNT', 1), ('M2_TEXTURE_LASTHASHCHECK', 1)), 0),
                ('MAINTENANCE_ONLY', (('M1_UPTIME', 1),), 0),
                ('EXACT', (), 0), ('EXACT', (), 0)]
        block = assess(after=after_block(*rows))
        self.assertEqual(entry(block, 'FIVE_FILE')['status'], 'MET')
        self.assertEqual(entry(block, 'FIVE_FILE')['counts'],
                         {'EXACT': 3, 'MAINTENANCE_ONLY': 2, 'MEANINGFUL': 0, 'INCONCLUSIVE': 0})
        self.assertEqual(entry(block, 'S5')['status'], 'MET')
        self.assertEqual(block['assessment'], 'INCONCLUSIVE')

    def test_meaningful_or_inconclusive_classification_prevents_eligibility(self):
        meaningful = list(EXACT_ROWS)
        meaningful[2] = ('MEANINGFUL', (), 1)
        block = assess(after=after_block(*meaningful))
        self.assertEqual(entry(block, 'FIVE_FILE')['status'], 'NOT_MET')
        self.assertEqual(entry(block, 'FIVE_FILE')['reason'], 'meaningful_classification')
        inconclusive = list(EXACT_ROWS)
        inconclusive[1] = ('INCONCLUSIVE', (), 0)
        block = assess(after=after_block(*inconclusive))
        self.assertEqual(entry(block, 'FIVE_FILE')['status'], 'UNVERIFIED')
        self.assertEqual(entry(block, 'FIVE_FILE')['reason'], 'classification_inconclusive')
        addons_inconclusive = list(EXACT_ROWS)
        addons_inconclusive[0] = ('INCONCLUSIVE', (), 0)
        block = assess(after=after_block(*addons_inconclusive))
        self.assertEqual(entry(block, 'S5'), {'id': 'S5', 'status': 'UNVERIFIED', 'reason': 'addons33_inconclusive'})

    def test_absent_transaction_owner_is_met_and_unverified_owner_is_not(self):
        block = assess()
        self.assertEqual(entry(block, 'S7')['status'], 'MET')
        self.assertEqual(entry(block, 'S7')['reason'], 'owner_pending_quit_and_source_verified')
        unverified = assess(public_after=public(owners_absent=None))
        self.assertEqual(entry(unverified, 'S7'), {'id': 'S7', 'status': 'UNVERIFIED', 'reason': 'owner_unverified'})
        present = assess(public_after=public(owners_absent=False))
        self.assertEqual(entry(present, 'S7'), {'id': 'S7', 'status': 'NOT_MET', 'reason': 'owner_present'})

    def test_pending_publication_quit_and_source_binding_are_each_required(self):
        cases = {
            'pending_unverified': (dict(public_after=public(pending_publication_absent=None)),
                                   ('UNVERIFIED', 'pending_publication_unverified')),
            'pending_present': (dict(public_before=public(pending_publication_absent=False)),
                                ('NOT_MET', 'pending_publication_present')),
            'quit_unverified': (dict(quit_verified=None), ('UNVERIFIED', 'quit_unverified')),
            'quit_not_verified': (dict(quit_verified=False), ('NOT_MET', 'quit_not_verified')),
            'source_unverified': (dict(source_bound=None), ('UNVERIFIED', 'source_binding_unverified')),
            'source_failed': (dict(source_bound=False), ('NOT_MET', 'source_binding_failed')),
            'bundle_changed': (dict(public_after=public(bundle={'identifier': 'other'})),
                               ('NOT_MET', 'bundle_changed')),
        }
        for name, (overrides, expected) in cases.items():
            with self.subTest(case=name):
                block = assess(**overrides)
                self.assertEqual((entry(block, 'S7')['status'], entry(block, 'S7')['reason']), expected)
                self.assertEqual(block['assessment'], 'INCONCLUSIVE')

    def test_missing_correlation_is_unverified_and_broken_correlation_is_not_met(self):
        missing = assess(correlation=None)
        self.assertEqual(entry(missing, 'OPERATION_CORRELATION'),
                         {'id': 'OPERATION_CORRELATION', 'status': 'UNVERIFIED', 'reason': 'correlation_missing'})
        self.assertEqual(missing['reason'], 'prerequisite_unverified')
        broken = assess(correlation='BROKEN')
        self.assertEqual(entry(broken, 'OPERATION_CORRELATION'),
                         {'id': 'OPERATION_CORRELATION', 'status': 'NOT_MET', 'reason': 'correlation_broken'})
        self.assertEqual(broken['reason'], 'prerequisite_not_met')
        self.assertEqual(broken['assessment'], 'INCONCLUSIVE')

    def test_absent_witnesses_are_unverified_and_never_invented(self):
        block = assess(public_after=public(library=None))
        self.assertEqual(entry(block, 'S1'), {'id': 'S1', 'status': 'UNVERIFIED', 'reason': 'witness_absent'})
        block = assess(public_after=public(trees=None))
        self.assertEqual(entry(block, 'S1')['status'], 'UNVERIFIED')
        self.assertEqual(entry(block, 'S2')['status'], 'UNVERIFIED')
        block = assess(public_after=public(association=None))
        self.assertEqual(entry(block, 'S2')['status'], 'UNVERIFIED')
        block = assess(public_after=public(addons=None))
        self.assertEqual(entry(block, 'S5'), {'id': 'S5', 'status': 'UNVERIFIED', 'reason': 'witness_absent'})
        unavailable = copy.deepcopy(public()['addons'])
        unavailable['enabled_state_source'] = 'unavailable'
        for item in unavailable['entries']:
            item['enabled'] = None
        block = assess(public_after=public(addons=unavailable))
        self.assertEqual(entry(block, 'S5'),
                         {'id': 'S5', 'status': 'UNVERIFIED', 'reason': 'enabled_state_unavailable'})

    def test_malformed_inputs_fail_closed_with_a_sanitized_reason(self):
        good = public()
        library = copy.deepcopy(good['library'])
        library['extra'] = SECRET
        registry = copy.deepcopy(good['library'])
        registry['registry']['entry_ids'] = SECRET
        duplicate = copy.deepcopy(good['addons'])
        duplicate['entries'].append(dict(duplicate['entries'][0]))
        enabled_text = copy.deepcopy(good['addons'])
        enabled_text['entries'][0]['enabled'] = SECRET
        no_practical = after_block()
        del no_practical['practical']
        wrong_file = after_block(*EXACT_ROWS)
        wrong_file['practical']['files'][0]['file'] = 'other.xml'
        pass_label = after_block(*EXACT_ROWS)
        pass_label['practical']['files'][1]['classification'] = 'PASS'
        pass_verdict = after_block(*EXACT_ROWS)
        pass_verdict['practical']['verdict'] = 'PASS'
        cases = {
            'public_not_mapping': dict(public_before=None),
            'public_missing_bundle': dict(public_before={k: v for k, v in public().items() if k != 'bundle'}),
            'library_extra_field': dict(public_before=public(library=library)),
            'registry_ids_not_a_list': dict(public_after=public(library=registry)),
            'trees_extra_key': dict(public_after=public(trees=dict(good['trees'], extra=SECRET))),
            'addons_duplicate_identifier': dict(public_after=public(addons=duplicate)),
            'addons_enabled_not_boolean': dict(public_after=public(addons=enabled_text)),
            'owners_flag_is_text': dict(public_after=public(owners_absent='yes')),
            'begin_not_acquired': dict(begin=dict(begin_block(), acquisition='REFUSED')),
            'after_without_practical': dict(after=no_practical),
            'practical_file_name_mismatch': dict(after=wrong_file),
            'practical_label_not_closed': dict(after=pass_label),
            'practical_verdict_pass': dict(after=pass_verdict),
            'maintenance_on_wrong_file': dict(after=after_block(
                ('MAINTENANCE_ONLY', (('M1_UPTIME', 1),), 0), *EXACT_ROWS[1:])),
            'exact_row_with_count': dict(after=after_block(('EXACT', (), 1), *EXACT_ROWS[1:])),
            'quit_flag_is_text': dict(quit_verified='yes'),
            'source_flag_is_integer': dict(source_bound=1),
            'correlation_not_closed': dict(correlation='PASS'),
        }
        for name, overrides in cases.items():
            with self.subTest(case=name):
                block = assess(**overrides)
                self.assertEqual(block['assessment'], 'INCONCLUSIVE')
                self.assertEqual(block['reason'], 'input_invalid')
                self.assertEqual({(item['status'], item['reason']) for item in block['prerequisites']},
                                 {('UNVERIFIED', 'input_invalid')})
                self.assertNotIn(SECRET, json.dumps(block))

    def test_output_uses_only_the_fixed_vocabulary_and_no_private_values(self):
        blocks = [assess(), assess(correlation='VERIFIED'), assess(correlation='BROKEN'),
                  assess(public_after=public(owners_absent=None)),
                  assess(public_after=public(library=None)),
                  assess(after=after_block(('MEANINGFUL', (), 1), *EXACT_ROWS[1:])),
                  precondition.not_reached()]
        for block in blocks:
            text = json.dumps(block, sort_keys=True)
            self.assertNotIn(SECRET, text)
            self.assertNotIn('a' * 64, text)
            self.assertNotIn('f' * 64, text)
            for value in strings(block):
                self.assertIn(value, OUTPUT_VOCABULARY)

    def test_assessment_never_emits_a_practical_pass_or_fail(self):
        scenarios = [assess(), assess(correlation='VERIFIED'), assess(correlation='BROKEN'),
                     assess(after=after_block(('MEANINGFUL', (), 1), *EXACT_ROWS[1:])),
                     assess(public_after=public(library=None)), assess(quit_verified=None),
                     assess(correlation='PASS'), precondition.not_reached()]
        for block in scenarios:
            with self.subTest(reason=block['reason']):
                self.assertEqual(block['assessment'], 'INCONCLUSIVE')
                text = json.dumps(block)
                self.assertNotIn('PASS', text)
                self.assertNotIn('FAIL', text)

    def test_not_reached_is_inconclusive_and_fully_unverified(self):
        block = precondition.not_reached()
        self.assertEqual(block['assessment'], 'INCONCLUSIVE')
        self.assertEqual(block['reason'], 'not_reached')
        self.assertEqual({(item['status'], item['reason']) for item in block['prerequisites']},
                         {('UNVERIFIED', 'not_reached')})

    def test_unexpected_fault_is_a_sanitized_inconclusive_block(self):
        with mock.patch.object(precondition, '_assess', side_effect=RuntimeError(SECRET)):
            block = assess()
        self.assertEqual(block['assessment'], 'INCONCLUSIVE')
        self.assertEqual(block['reason'], 'internal_error')
        self.assertNotIn(SECRET, json.dumps(block))

    def test_inputs_are_not_mutated(self):
        before, after_public, begin, after = public(), public(), begin_block(), after_block()
        snapshot = copy.deepcopy((before, after_public, begin, after))
        precondition.assess(public_before=before, public_after=after_public, begin=begin, after=after,
                            quit_verified=True, source_bound=True, correlation='VERIFIED')
        self.assertEqual((before, after_public, begin, after), snapshot)

    def test_assessment_reads_and_writes_nothing(self):
        with mock.patch('builtins.open', side_effect=AssertionError('io')), \
             mock.patch('os.open', side_effect=AssertionError('io')), \
             mock.patch('os.write', side_effect=AssertionError('io')), \
             mock.patch('tempfile.TemporaryDirectory', side_effect=AssertionError('io')):
            block = assess()
        self.assertEqual(block['assessment'], 'INCONCLUSIVE')


if __name__ == '__main__':
    unittest.main()
