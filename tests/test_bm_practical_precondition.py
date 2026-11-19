"""Synthetic offline tests for the D-032 practical precondition assessment."""
import copy
import json
import unittest
from unittest import mock

from resources.lib import build_library
from tools import bm_practical_precondition as precondition
from tools import bm_public_preservation_witness as witness
from tools import bm_test_app

SECRET = 'synthetic-private-precondition-value'
ENTRY = '9' * 64
PROFILE = 'profile-one'
EXACT_ROWS = [('EXACT', (), 0)] * 5
UNICODE_RAW = 'profi' + chr(0xED) + 'le'
SURROGATE_RAW = 'bad' + chr(0xD800)
# (raw profile, producer projection). The token is '<unsafe:' + sha256(raw.encode('utf-8',
# 'surrogatepass')).hexdigest()[:12] + '>', the rule bm_test_app.census_build_library applies.
UNSAFE_CASES = (
    ('bad profile!', '<unsafe:209d2da914f4>'),
    (UNICODE_RAW, '<unsafe:2ca9acfdc5cf>'),
    (SURROGATE_RAW, '<unsafe:ffa9f0468a10>'),
    ('a' * 101, '<unsafe:9d0793397991>'),
)
ASSOCIATION_GOOD = ('p', 'p' * 64, 'profile-one', 'profile.one_2', '0profile')
ASSOCIATION_BAD = ('Profile One', 'Profile-one', 'profile one', '-profile', '.profile', 'profile/one',
                   'p' * 65, 'profile' + chr(0xED), '')
ADDON_GOOD = (('plugin.video.example', '1.0.0'), ('a', 'a'), ('a' * 128, 'x' * 64),
              ('script_module-1.0', '1.0.0~beta+build_2'), ('script.synthetic', '19.0.0-alpha'))
ADDON_BAD_IDS = ('bad id!', '-addon', 'addon/x', 'a' * 129, '', 'addon' + chr(0xE9))
ADDON_BAD_VERSIONS = ('bad version!', '', '1 0', '-1.0', '1.0/2', 'v' * 65, '1.0' + chr(0xE9))
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


def bundle(**changes):
    """The bundle identity record bm_test_app.identify().report() emits."""
    value = {'build_version': '21.3.0', 'executable': 'Kodi', 'identifier': 'org.xbmc.kodi',
             'info_plist_sha256': '1' * 64, 'package_type': 'APPL', 'short_version': '21.3'}
    value.update(changes)
    return value


def association(fingerprint='f' * 64, **changes):
    """The applied association record AppliedBuildAssociation.to_dict() emits."""
    value = {'schema_version': 2, 'entry_id': ENTRY, 'device_profile_id': PROFILE,
             'resolution_fingerprint': fingerprint}
    value.update(changes)
    return value


def public(**changes):
    """Synthetic public witnesses with the shape public_state returns."""
    value = {
        'bundle': bundle(),
        'settings': {'readable': True, 'active_skin': 'skin.estuary', 'updater_policy': 'NOTIFY_ONLY'},
        'addons': {'count': 2, 'enabled_state_source': 'addons_db', 'id_mismatch': 0,
                   'skipped_invalid_names': 0, 'skipped_non_directories': 0, 'unreadable_addon_xml': 0,
                   'entries': [{'enabled': True, 'id': 'script.synthetic', 'version': '1.0.0'},
                               {'enabled': False, 'id': 'script.other', 'version': '2.0.0'}]},
        'library': {'root_present': True,
                    'registry': {'file_present': True, 'sha256': 'a' * 64, 'size': 120,
                                 'entry_count': 1, 'entry_ids': [ENTRY]},
                    'selection': {'file_present': True, 'selected': True, 'sha256': 'b' * 64, 'size': 30,
                                  'entry_id': ENTRY, 'device_profile_id': PROFILE}},
        'trees': {'build-library': {'registry.json': 'c' * 64},
                  'install_resolutions': {'resolution.json': 'd' * 64},
                  'frozen-artifacts': {'artifact.json': 'e' * 64}},
        'association': association(),
        'selection': (ENTRY, PROFILE),
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


def strict_for(label):
    """The strict status the driver derives: only EXACT or INCONCLUSIVE is PRESERVED."""
    return 'PRESERVED' if label in ('EXACT', 'INCONCLUSIVE') else 'CHANGED_OR_MISSING'


def after_block(*rows, statuses=None):
    rows = rows or EXACT_ROWS
    if statuses is None:
        statuses = [strict_for(row[0]) for row in rows]
    scope = 'PRESERVED' if all(status == 'PRESERVED' for status in statuses) else 'CHANGED_OR_MISSING'
    return {'acquisition': 'ACQUIRED', 'scope_result': scope,
            'files': [{'file': name, 'status': status} for name, status in zip(witness.FILES, statuses)],
            'practical': practical(*rows)}


def begin_block():
    return {'acquisition': 'ACQUIRED', 'scope_result': 'UNVERIFIED',
            'files': [{'file': name, 'status': 'UNVERIFIED'} for name in witness.FILES]}


def assess(**overrides):
    arguments = {'public_before': public(), 'public_after': public(), 'begin': begin_block(),
                 'after': after_block(), 'quit_verified': True, 'source_bound': True, 'correlation': None}
    arguments.update(overrides)
    return precondition.assess(**arguments)


def selection_pair(raw, projected):
    """The top-level raw selection profile and the library record that projects it."""
    library = copy.deepcopy(public()['library'])
    library['selection']['device_profile_id'] = projected
    return {'library': library, 'selection': (ENTRY, raw)}


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
    def assertInvalid(self, block):
        """Malformed evidence: a sanitized blocked assessment with no MET prerequisite."""
        self.assertEqual(block['assessment'], 'INCONCLUSIVE')
        self.assertEqual(block['reason'], 'input_invalid')
        self.assertEqual({(item['status'], item['reason']) for item in block['prerequisites']},
                         {('UNVERIFIED', 'input_invalid')})
        self.assertNotIn(SECRET, json.dumps(block))

    def assertInvalidAtBothBoundaries(self, **changes):
        """The same malformed record at public_before and public_after fails closed."""
        self.assertInvalid(assess(public_before=public(**changes), public_after=public(**copy.deepcopy(changes))))

    def assertAcceptedAtBothBoundaries(self, **changes):
        block = assess(public_before=public(**changes), public_after=public(**copy.deepcopy(changes)))
        self.assertNotEqual(block['reason'], 'input_invalid')
        return block

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
        selected = copy.deepcopy(base['library'])
        selected['selection']['device_profile_id'] = 'profile-two'
        trees = copy.deepcopy(base['trees'])
        trees['build-library']['registry.json'] = '0' * 64
        changes = [{'library': library}, {'library': selected, 'selection': (ENTRY, 'profile-two')},
                   {'trees': trees}]
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
        block = assess(public_after=public(association=association('0' * 64)))
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

    def test_strict_change_coexists_with_permitted_maintenance_without_rejection(self):
        after = after_block(('EXACT', (), 0),
                            ('MAINTENANCE_ONLY', (('M2_SIZES_LASTUSETIME', 2),), 0), *EXACT_ROWS[2:])
        self.assertEqual(after['scope_result'], 'CHANGED_OR_MISSING')
        self.assertEqual(after['files'][1]['status'], 'CHANGED_OR_MISSING')
        block = assess(after=after)
        self.assertEqual(entry(block, 'FIVE_FILE')['status'], 'MET')
        self.assertNotEqual(block['reason'], 'input_invalid')

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
            'bundle_changed': (dict(public_after=public(bundle=bundle(identifier='org.example.other'))),
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

    def test_absent_bundle_and_absent_top_level_selection_stay_unverified(self):
        block = assess(public_before=public(bundle=None), public_after=public(bundle=None))
        self.assertEqual(entry(block, 'S7'), {'id': 'S7', 'status': 'UNVERIFIED', 'reason': 'bundle_unverified'})
        block = assess(public_before=public(selection=None), public_after=public(selection=None))
        self.assertEqual(entry(block, 'S1'), {'id': 'S1', 'status': 'UNVERIFIED', 'reason': 'witness_absent'})

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
                self.assertInvalid(assess(**overrides))

    def test_begin_projection_must_match_the_driver_schema(self):
        files = begin_block()['files']
        cases = {
            'begin_without_files': {'acquisition': 'ACQUIRED', 'scope_result': 'UNVERIFIED'},
            'begin_files_short': dict(begin_block(), files=files[:4]),
            'begin_file_not_unverified': dict(begin_block(), files=[dict(row, status='PRESERVED') for row in files]),
            'begin_scope_not_unverified': dict(begin_block(), scope_result='PRESERVED'),
            'begin_extra_key': dict(begin_block(), extra=SECRET),
        }
        for name, begin in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(begin=begin))

    def test_after_projection_requires_files_scope_and_the_driver_shape(self):
        without_files = after_block()
        del without_files['files']
        without_scope = after_block()
        del without_scope['scope_result']
        scope_contradicts = after_block(('MEANINGFUL', (), 1), *EXACT_ROWS[1:])
        scope_contradicts['scope_result'] = 'PRESERVED'
        short_files = after_block()
        short_files['files'] = short_files['files'][:4]
        unknown_status = after_block()
        unknown_status['files'][0]['status'] = 'UNKNOWN'
        extra_key = after_block()
        extra_key['extra'] = SECRET
        cases = {'after_without_files': without_files, 'after_without_scope_result': without_scope,
                 'scope_contradicts_files': scope_contradicts, 'after_files_short': short_files,
                 'file_status_unknown': unknown_status, 'after_extra_key': extra_key}
        for name, after in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(after=after))

    def test_strict_status_and_practical_classification_must_agree(self):
        preserved = ('PRESERVED',) * 5
        cases = {
            # Strict Addons33 CHANGED_OR_MISSING paired with practical EXACT.
            'addons_changed_practical_exact': after_block(
                statuses=('CHANGED_OR_MISSING',) + preserved[1:]),
            # Strict PRESERVED is never paired with a maintenance class.
            'preserved_with_maintenance': after_block(
                ('EXACT', (), 0), ('MAINTENANCE_ONLY', (('M2_SIZES_USECOUNT', 1),), 0), *EXACT_ROWS[2:],
                statuses=preserved),
            # Strict PRESERVED is never paired with MEANINGFUL.
            'preserved_with_meaningful': after_block(
                ('EXACT', (), 0), ('EXACT', (), 0), ('MEANINGFUL', (), 1), *EXACT_ROWS[3:],
                statuses=preserved),
            # Strict CHANGED_OR_MISSING is never paired with EXACT, on any file.
            'textures_changed_exact': after_block(
                statuses=(preserved[0], 'CHANGED_OR_MISSING') + preserved[2:]),
        }
        for name, after in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(after=after))

    def test_invalid_practical_aggregate_is_rejected(self):
        for name, aggregate in (('meaningful_over_exact_rows', 'MEANINGFUL'),
                                ('maintenance_over_exact_rows', 'MAINTENANCE_ONLY'),
                                ('unknown_label', 'PASS')):
            with self.subTest(case=name):
                after = after_block()
                after['practical']['classification'] = aggregate
                self.assertInvalid(assess(after=after))
        after = after_block()
        del after['practical']['classification']
        self.assertInvalid(assess(after=after))

    def test_maintenance_classes_must_be_approved_unique_ordered_and_counted(self):
        cases = {
            'duplicate_class': ('MAINTENANCE_ONLY', (('M2_SIZES_USECOUNT', 1), ('M2_SIZES_USECOUNT', 1)), 0),
            'unsorted_classes': ('MAINTENANCE_ONLY', (('M2_TEXTURE_LASTHASHCHECK', 1), ('M2_SIZES_USECOUNT', 1)), 0),
            'zero_count': ('MAINTENANCE_ONLY', (('M2_SIZES_USECOUNT', 0),), 0),
            'negative_count': ('MAINTENANCE_ONLY', (('M2_SIZES_USECOUNT', -1),), 0),
            'boolean_count': ('MAINTENANCE_ONLY', (('M2_SIZES_USECOUNT', True),), 0),
            'empty_maintenance_list': ('MAINTENANCE_ONLY', (), 0),
            'unknown_class': ('MAINTENANCE_ONLY', (('M2_UNREVIEWED', 1),), 0),
            'm1_class_on_textures': ('MAINTENANCE_ONLY', (('M1_UPTIME', 1),), 0),
            'exact_with_maintenance': ('EXACT', (('M2_SIZES_USECOUNT', 1),), 0),
            'meaningful_with_maintenance': ('MEANINGFUL', (('M2_SIZES_USECOUNT', 1),), 1),
        }
        for name, row in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(after=after_block(('EXACT', (), 0), row, *EXACT_ROWS[2:])))
        block = assess(after=after_block(('EXACT', (), 0),
                                         ('MAINTENANCE_ONLY', (('M2_SIZES_LASTUSETIME', 2),
                                                               ('M2_SIZES_USECOUNT', 1)), 0),
                                         *EXACT_ROWS[2:]))
        self.assertEqual(entry(block, 'FIVE_FILE')['status'], 'MET')

    def test_frozen_artifact_leaves_must_be_digests_not_numbers(self):
        base = public()
        cases = {
            'numeric_top_leaf': {'artifact.json': 5},
            'numeric_nested_leaf': {'nested': {'artifact.json': 5}},
            'boolean_leaf': {'artifact.json': True},
            'null_leaf': {'artifact.json': None},
            'short_digest_leaf': {'artifact.json': 'e' * 63},
            'uppercase_digest_leaf': {'artifact.json': 'E' * 64},
            'slash_in_name': {'a/b.json': 'e' * 64},
            'empty_name': {'': 'e' * 64},
            'tree_is_a_digest': 'e' * 64,
        }
        for name, tree in cases.items():
            with self.subTest(case=name):
                trees = copy.deepcopy(base['trees'])
                trees['frozen-artifacts'] = tree
                self.assertInvalid(assess(public_before=public(trees=trees),
                                          public_after=public(trees=copy.deepcopy(trees))))

    def test_empty_directories_and_nested_digests_remain_valid(self):
        trees = copy.deepcopy(public()['trees'])
        trees['frozen-artifacts'] = {'empty': {}, 'nested': {'a.json': 'e' * 64}}
        block = assess(public_before=public(trees=trees), public_after=public(trees=copy.deepcopy(trees)))
        self.assertEqual(entry(block, 'S2')['status'], 'MET')
        self.assertNotEqual(block['reason'], 'input_invalid')

    def test_registry_witness_requires_digest_size_and_consistent_entries(self):
        def library_with(**registry_changes):
            library = copy.deepcopy(public()['library'])
            library['registry'].update(registry_changes)
            return library

        cases = {
            'present_without_digest': library_with(sha256=None),
            'present_without_size': library_with(size=None),
            'present_negative_size': library_with(size=-1),
            'present_text_size': library_with(size='120'),
            'present_uppercase_digest': library_with(sha256='A' * 64),
            'present_short_digest': library_with(sha256='a' * 63),
            'absent_with_digest': library_with(file_present=False),
            'entry_count_mismatch': library_with(entry_count=2),
            'entry_ids_unsorted': library_with(entry_ids=[ENTRY, '8' * 64], entry_count=2),
            'entry_ids_duplicate': library_with(entry_ids=[ENTRY, ENTRY], entry_count=2),
            'entry_id_not_digest': library_with(entry_ids=['not-a-digest'], entry_count=1),
        }
        for name, library in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(public_before=public(library=library),
                                          public_after=public(library=copy.deepcopy(library))))

    def test_selection_witness_must_agree_with_the_registry_and_root(self):
        def selection_with(**changes):
            library = copy.deepcopy(public()['library'])
            library['selection'].update(changes)
            return library

        def root_absent():
            library = copy.deepcopy(public()['library'])
            library['root_present'] = False
            return library

        cases = {
            'selected_entry_not_in_registry': selection_with(entry_id='7' * 64),
            'selected_without_file': selection_with(file_present=False),
            'unselected_with_entry': selection_with(selected=False),
            'selected_without_profile': selection_with(device_profile_id=None),
            'root_absent_with_registry': root_absent(),
        }
        for name, library in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(public_before=public(library=library),
                                          public_after=public(library=copy.deepcopy(library))))

    def test_top_level_selection_must_agree_with_the_library_selection(self):
        self.assertInvalid(assess(public_before=public(selection=(ENTRY, 'profile-two')),
                                  public_after=public(selection=(ENTRY, 'profile-two'))))
        self.assertInvalid(assess(public_before=public(selection=('8' * 64, PROFILE)),
                                  public_after=public(selection=('8' * 64, PROFILE))))

    def test_unsafe_profile_projection_is_the_producer_digest_token(self):
        for raw, token in UNSAFE_CASES:
            with self.subTest(raw_length=len(raw)):
                block = self.assertAcceptedAtBothBoundaries(**selection_pair(raw, token))
                self.assertEqual(entry(block, 'S1')['status'], 'MET')

    def test_unsafe_profile_projection_rejects_arbitrary_wrong_and_unmasked_values(self):
        raw, token = UNSAFE_CASES[0]
        cases = {
            'arbitrary_token': (raw, '<unsafe:0123456789ab>'),
            'token_of_another_raw_profile': (raw, UNSAFE_CASES[1][1]),
            'uppercase_digest': (raw, '<unsafe:' + token[len('<unsafe:'):-1].upper() + '>'),
            'unmasked_unsafe_raw': (raw, raw),
            'unmasked_unicode_raw': (UNICODE_RAW, UNICODE_RAW),
            'unmasked_long_raw': ('a' * 101, 'a' * 101),
            'token_for_an_in_grammar_profile': (PROFILE, '<unsafe:9a13cbbc3edc>'),
        }
        for name, (raw_profile, projected) in cases.items():
            with self.subTest(case=name):
                self.assertInvalidAtBothBoundaries(**selection_pair(raw_profile, projected))
        leaked = assess(public_before=public(**selection_pair(raw, raw)),
                        public_after=public(**selection_pair(raw, raw)))
        self.assertInvalid(leaked)
        self.assertNotIn(raw, json.dumps(leaked))

    def test_profile_inside_the_identifier_grammar_projects_unchanged(self):
        for raw in (PROFILE, 'a' * 100, 'A.b_c-9'):
            with self.subTest(length=len(raw)):
                block = self.assertAcceptedAtBothBoundaries(**selection_pair(raw, raw))
                self.assertEqual(entry(block, 'S1')['status'], 'MET')

    def test_library_projection_shape_is_checked_even_without_a_top_level_selection(self):
        for projected in ('bad profile!', 'profile one', '<unsafe:0123456789AB>', '<unsafe:01234567>'):
            with self.subTest(projected=projected):
                library = copy.deepcopy(public()['library'])
                library['selection']['device_profile_id'] = projected
                self.assertInvalidAtBothBoundaries(library=library, selection=None)

    def test_association_profile_must_match_the_applied_association_grammar(self):
        for profile in ASSOCIATION_BAD:
            with self.subTest(profile=profile):
                self.assertInvalidAtBothBoundaries(association=association(device_profile_id=profile))
        for profile in ASSOCIATION_GOOD:
            with self.subTest(profile=profile):
                block = self.assertAcceptedAtBothBoundaries(association=association(device_profile_id=profile))
                self.assertEqual(entry(block, 'S2')['status'], 'MET')

    def test_bundle_identifier_and_executable_must_match_the_producer_grammars(self):
        bad = (
            {'identifier': 'org example'}, {'identifier': 'org_example'}, {'identifier': '-org.example'},
            {'identifier': 'org/example'}, {'identifier': 'a' * 156}, {'identifier': 'org' + chr(0xE9)},
            {'identifier': ''}, {'executable': ''}, {'executable': ' Kodi'}, {'executable': 'Kodi;rm'},
            {'executable': 'Kodi/Exec'}, {'executable': '.hidden'}, {'executable': '..'},
            {'executable': 'Kodi' + chr(10) + 'X'}, {'executable': 'a' * 129},
            {'executable': 'Kodi' + chr(0xE9)},
        )
        for changes in bad:
            with self.subTest(changes=changes):
                self.assertInvalidAtBothBoundaries(bundle=bundle(**changes))
        good = (
            {'identifier': 'org.example.app', 'executable': 'Kodi'},
            {'identifier': 'a', 'executable': 'a'},
            {'identifier': 'a' * 155, 'executable': 'Kodi Test 2'},
            {'identifier': 'org-example.app1', 'executable': 'Kodi-Build_1.0'},
            {'identifier': 'org.xbmc.kodi', 'executable': 'a' * 128},
        )
        for changes in good:
            with self.subTest(changes=changes):
                block = self.assertAcceptedAtBothBoundaries(bundle=bundle(**changes))
                self.assertEqual(entry(block, 'S7')['status'], 'MET')

    def test_bundle_versions_follow_the_producer_grammar_and_may_be_absent(self):
        for changes in ({'build_version': ''}, {'build_version': '1 0'}, {'short_version': '-21'},
                        {'short_version': 'v' * 65}):
            with self.subTest(changes=changes):
                self.assertInvalidAtBothBoundaries(bundle=bundle(**changes))
        block = self.assertAcceptedAtBothBoundaries(bundle=bundle(build_version=None, short_version=None))
        self.assertEqual(entry(block, 'S7')['status'], 'MET')

    def test_addon_identifier_and_version_must_match_the_producer_grammars(self):
        def census(**entry_changes):
            addons = copy.deepcopy(public()['addons'])
            addons['entries'][0].update(entry_changes)
            return addons

        for identifier in ADDON_BAD_IDS:
            with self.subTest(identifier=identifier):
                self.assertInvalidAtBothBoundaries(addons=census(id=identifier))
        for version in ADDON_BAD_VERSIONS:
            with self.subTest(version=version):
                self.assertInvalidAtBothBoundaries(addons=census(version=version))
        for identifier, version in ADDON_GOOD:
            with self.subTest(identifier=identifier, version=version):
                block = self.assertAcceptedAtBothBoundaries(addons=census(id=identifier, version=version))
                self.assertEqual(entry(block, 'S5')['status'], 'MET')

    def test_bundle_identity_must_be_the_real_bundle_record(self):
        without_digest = bundle()
        del without_digest['info_plist_sha256']
        cases = {
            'integer_bundle': 5,
            'bundle_missing_digest': without_digest,
            'bundle_extra_key': bundle(version='21.3'),
            'bundle_not_app': bundle(package_type='PKG'),
            'executable_with_slash': bundle(executable='bin/Kodi'),
            'bad_short_version': bundle(short_version='21 beta'),
            'digest_not_hex': bundle(info_plist_sha256='G' * 64),
            'empty_identifier': bundle(identifier=''),
        }
        for name, value in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(public_before=public(bundle=value),
                                          public_after=public(bundle=copy.deepcopy(value))))

    def test_association_must_be_the_applied_association_record(self):
        cases = {
            'numeric_fingerprint': association(fingerprint=7),
            'wrong_schema_version': association(schema_version=3),
            'boolean_schema_version': association(schema_version=True),
            'association_extra_key': association(artifact='f' * 64),
            'association_entry_not_digest': association(entry_id='x'),
            'association_empty_profile': association(device_profile_id=''),
        }
        for name, value in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(public_before=public(association=value),
                                          public_after=public(association=copy.deepcopy(value))))

    def test_addon_census_must_be_complete_and_consistent(self):
        base = public()['addons']
        unavailable_bool = copy.deepcopy(base)
        unavailable_bool['enabled_state_source'] = 'unavailable'
        cases = {
            'count_mismatch': dict(base, count=9),
            'unreadable_addon_xml': dict(base, unreadable_addon_xml=1),
            'id_mismatch': dict(base, id_mismatch=1),
            'skipped_invalid_names': dict(base, skipped_invalid_names=1),
            'skipped_non_directories': dict(base, skipped_non_directories=1),
            'missing_counter': {k: v for k, v in base.items() if k != 'id_mismatch'},
            'unavailable_with_boolean_enabled': unavailable_bool,
        }
        for name, addons in cases.items():
            with self.subTest(case=name):
                self.assertInvalid(assess(public_before=public(addons=addons),
                                          public_after=public(addons=copy.deepcopy(addons))))

    def test_output_uses_only_the_fixed_vocabulary_and_no_private_values(self):
        blocks = [assess(), assess(correlation='VERIFIED'), assess(correlation='BROKEN'),
                  assess(public_after=public(owners_absent=None)),
                  assess(public_after=public(library=None)),
                  assess(after=after_block(('MEANINGFUL', (), 1), *EXACT_ROWS[1:])),
                  assess(public_after=public(library=None), after=after_block(
                      ('MAINTENANCE_ONLY', (('M2_SIZES_USECOUNT', 0),), 0), *EXACT_ROWS[1:])),
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

    def test_interrupts_and_system_exit_propagate(self):
        for exc_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception=exc_type.__name__):
                with mock.patch.object(precondition, '_assess', side_effect=exc_type()):
                    with self.assertRaises(exc_type):
                        assess()

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


class ProducerGrammarTests(unittest.TestCase):
    """The validator's grammars are the producers' grammars, checked against the producers."""

    def test_named_patterns_are_the_producer_patterns(self):
        pairs = (
            (precondition._VERSION_RE, bm_test_app._VERSION_RE),
            (precondition._ADDON_ID_RE, bm_test_app._ADDON_ID_RE),
            (precondition._BUNDLE_ID_RE, bm_test_app._BUNDLE_ID_RE),
            (precondition._EXEC_NAME_RE, bm_test_app._EXEC_NAME_RE),
            (precondition._LIBRARY_PROFILE_RE, bm_test_app._LIBRARY_PROFILE_RE),
        )
        for ours, theirs in pairs:
            with self.subTest(pattern=theirs.pattern):
                self.assertEqual(ours.pattern, theirs.pattern)

    def test_association_profile_grammar_agrees_with_the_applied_association_reader(self):
        for profile in ASSOCIATION_GOOD + ASSOCIATION_BAD:
            with self.subTest(profile=profile):
                record = association(device_profile_id=profile)
                try:
                    build_library.AppliedBuildAssociation.from_dict(copy.deepcopy(record))
                    producer_accepts = True
                except Exception:
                    producer_accepts = False
                block = assess(public_before=public(association=record),
                               public_after=public(association=copy.deepcopy(record)))
                self.assertEqual(block['reason'] != 'input_invalid', producer_accepts)

    def test_addon_grammar_agrees_with_the_addon_xml_reader(self):
        cases = list(ADDON_GOOD) + [(identifier, '1.0') for identifier in ADDON_BAD_IDS] + \
            [('script.a', version) for version in ADDON_BAD_VERSIONS]
        for identifier, version in cases:
            with self.subTest(identifier=identifier, version=version):
                xml = ('<addon id="%s" version="%s"/>' % (identifier, version)).encode('utf-8')
                try:
                    producer_accepts = bm_test_app.parse_addon_xml(xml) == (identifier, version)
                except Exception:
                    producer_accepts = False
                addons = copy.deepcopy(public()['addons'])
                addons['entries'][0].update(id=identifier, version=version)
                block = assess(public_before=public(addons=addons),
                               public_after=public(addons=copy.deepcopy(addons)))
                self.assertEqual(block['reason'] != 'input_invalid', producer_accepts)


if __name__ == '__main__':
    unittest.main()
