"""D-032 practical precondition assessment, offline and fail-closed.

The assessment reads only values the driver has already produced: the two public
witnesses from public_state, the validated begin and after projections (including the
validated after.practical block), and two driver facts. It compares scope-specific
fields for S1, S2, S5 and S7, checks the five-file classifications for eligibility, and
lists each requirement that no witness in this flow establishes.

It reads and writes no file, changes no strict result, and never emits a practical PASS
or FAIL. In this task the assessment is always INCONCLUSIVE: no operation or ledger
correlation is supplied, the operation's expected result is not supplied, and the
limitation scopes cannot be justified without a future scenario.
"""
from __future__ import annotations

from tools import bm_public_preservation_witness as witness

SCHEMA = 'bm-a15-practical-precondition/1'
ASSESSMENT = 'INCONCLUSIVE'
MET = 'MET'
NOT_MET = 'NOT_MET'
UNVERIFIED = 'UNVERIFIED'
LABELS = ('EXACT', 'MAINTENANCE_ONLY', 'MEANINGFUL', 'INCONCLUSIVE')
PREREQUISITE_IDS = ('S1', 'S2', 'S5', 'S7', 'FIVE_FILE', 'OPERATION_CORRELATION', 'EXPECTED_RESULT')

_M1 = frozenset(('M1_UPTIME',))
_M2 = frozenset(('M2_SIZES_USECOUNT', 'M2_SIZES_LASTUSETIME', 'M2_TEXTURE_LASTHASHCHECK',
                 'M2_CACHE_ROW_CREATE', 'M2_CACHE_ROW_EVICT', 'M2_CACHE_SIZES_CREATE',
                 'M2_CACHE_SIZES_EVICT'))
_NO_CLASSES = frozenset()
# Approved maintenance vocabulary per protected file, in witness order. Mirrors the driver.
_MAINTENANCE_BY_INDEX = (_NO_CLASSES, _M2, _M1, _NO_CLASSES, _NO_CLASSES)
_PUBLIC_KEYS = frozenset(('addons', 'association', 'bundle', 'library', 'selection', 'trees'))
_TREE_KEYS = frozenset(('build-library', 'frozen-artifacts', 'install_resolutions'))
_LIBRARY_KEYS = frozenset(('registry', 'root_present', 'selection'))
_REGISTRY_KEYS = frozenset(('entry_count', 'entry_ids', 'file_present', 'sha256', 'size'))
_SELECTION_KEYS = frozenset(('device_profile_id', 'entry_id', 'file_present', 'selected', 'sha256', 'size'))
_ADDON_ENTRY_KEYS = frozenset(('enabled', 'id', 'version'))
_PRACTICAL_KEYS = frozenset(('classification', 'files', 'qualification', 'schema', 'verdict'))
_PRACTICAL_ROW_KEYS = frozenset(('classification', 'file', 'maintenance', 'meaningful_count'))
_MAX_DEPTH = 16


class _Reject(Exception):
    """Malformed input. It carries no input text."""


def _need(condition):
    if not condition:
        raise _Reject()


def _text_or_none(value):
    return value is None or type(value) is str


def _int_or_none(value):
    return value is None or type(value) is int


def _check_flag(value):
    _need(value is None or type(value) is bool)


def _json_like(value, depth=0):
    if depth > _MAX_DEPTH:
        return False
    if value is None or type(value) in (str, int, float, bool):
        return True
    if type(value) is list:
        return all(_json_like(item, depth + 1) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json_like(item, depth + 1) for key, item in value.items())
    return False


def _check_library(value):
    if value is None:
        return
    _need(type(value) is dict and set(value) == _LIBRARY_KEYS and type(value['root_present']) is bool)
    registry, selection = value['registry'], value['selection']
    _need(type(registry) is dict and set(registry) == _REGISTRY_KEYS)
    _need(type(registry['file_present']) is bool and _text_or_none(registry['sha256'])
          and _int_or_none(registry['size']) and type(registry['entry_count']) is int)
    _need(type(registry['entry_ids']) is list and all(type(item) is str for item in registry['entry_ids']))
    _need(type(selection) is dict and set(selection) == _SELECTION_KEYS)
    _need(type(selection['file_present']) is bool and type(selection['selected']) is bool)
    _need(_text_or_none(selection['sha256']) and _int_or_none(selection['size']))
    _need(_text_or_none(selection['entry_id']) and _text_or_none(selection['device_profile_id']))


def _check_trees(value):
    if value is None:
        return
    _need(type(value) is dict and set(value) == _TREE_KEYS)
    for tree in value.values():
        _need(tree is None or (type(tree) is dict and _json_like(tree)))


def _check_association(value):
    _need(value is None or (type(value) is dict and _json_like(value)))


def _check_selection(value):
    if value is None:
        return
    _need(type(value) in (list, tuple) and len(value) == 2 and all(_text_or_none(item) for item in value))


def _addon_pairs(addons):
    _need(type(addons) is dict and type(addons.get('enabled_state_source')) is str
          and type(addons.get('entries')) is list)
    source = addons['enabled_state_source']
    seen = set()
    pairs = []
    for entry in addons['entries']:
        _need(type(entry) is dict and set(entry) == _ADDON_ENTRY_KEYS)
        identifier, enabled = entry['id'], entry['enabled']
        _need(type(identifier) is str and identifier != '' and type(entry['version']) is str)
        _need(identifier not in seen)
        seen.add(identifier)
        if source == 'addons_db':
            _need(type(enabled) is bool)
        else:
            _need(enabled is None or type(enabled) is bool)
        pairs.append((identifier, enabled))
    return (sorted(pairs) if source == 'addons_db' else None), source


def _check_public(value):
    _need(type(value) is dict and _PUBLIC_KEYS <= set(value))
    _check_library(value['library'])
    _check_trees(value['trees'])
    _check_association(value['association'])
    _check_selection(value['selection'])
    if value['addons'] is not None:
        _addon_pairs(value['addons'])
    _check_flag(value.get('owners_absent'))
    _check_flag(value.get('pending_publication_absent'))


def _check_begin(value):
    _need(type(value) is dict and value.get('acquisition') == 'ACQUIRED')


def _check_after(value):
    _need(type(value) is dict and value.get('acquisition') == 'ACQUIRED')
    practical = value.get('practical')
    _need(type(practical) is dict and set(practical) == _PRACTICAL_KEYS)
    _need(practical['schema'] == 'bm-a15-practical-classification/1'
          and practical['verdict'] == 'NOT_DECIDED' and practical['qualification'] == 'not_qualified')
    rows = practical['files']
    _need(type(rows) is list and len(rows) == len(witness.FILES))
    labels = []
    for index, (row, name) in enumerate(zip(rows, witness.FILES)):
        _need(type(row) is dict and set(row) == _PRACTICAL_ROW_KEYS and row['file'] == name)
        label, maintenance, count = row['classification'], row['maintenance'], row['meaningful_count']
        _need(type(label) is str and label in LABELS)
        _need(type(maintenance) is list and type(count) is int and count >= 0)
        for item in maintenance:
            _need(type(item) is list and len(item) == 2 and type(item[0]) is str
                  and item[0] in _MAINTENANCE_BY_INDEX[index] and type(item[1]) is int and item[1] > 0)
        if label in ('EXACT', 'INCONCLUSIVE'):
            _need(not maintenance and count == 0)
        elif label == 'MAINTENANCE_ONLY':
            _need(bool(maintenance) and count == 0)
        else:
            _need(not maintenance and count >= 1)
        labels.append(label)
    return labels


def _entry(identifier, status, reason):
    return {'id': identifier, 'status': status, 'reason': reason}


def _combine(checks, met_reason):
    for status, reason in checks:
        if status == NOT_MET:
            return NOT_MET, reason
    for status, reason in checks:
        if status == UNVERIFIED:
            return UNVERIFIED, reason
    return MET, met_reason


def _flag_status(value, met, not_met, unverified):
    if value is True:
        return MET, met
    if value is False:
        return NOT_MET, not_met
    return UNVERIFIED, unverified


def _pairs_status(pairs, changed, matched):
    present = [(left, right) for left, right in pairs if left is not None and right is not None]
    if any(left != right for left, right in present):
        return NOT_MET, changed
    if len(present) != len(pairs):
        return UNVERIFIED, 'witness_absent'
    return MET, matched


def _tree(public, name):
    return None if public['trees'] is None else public['trees'][name]


def _s1(before, after):
    status, reason = _pairs_status(
        [(before['library'], after['library']),
         (before['selection'], after['selection']),
         (_tree(before, 'build-library'), _tree(after, 'build-library'))],
        'library_selection_or_tree_changed', 'library_selection_and_tree_match')
    return _entry('S1', status, reason)


def _s2(before, after):
    status, reason = _pairs_status(
        [(_tree(before, 'frozen-artifacts'), _tree(after, 'frozen-artifacts')),
         (_tree(before, 'install_resolutions'), _tree(after, 'install_resolutions')),
         (before['association'], after['association'])],
        'artifact_or_association_changed', 'artifacts_and_association_match')
    return _entry('S2', status, reason)


def _identity_status(before, after):
    if before is None or after is None:
        return UNVERIFIED, 'witness_absent'
    pairs_before, source_before = _addon_pairs(before)
    pairs_after, source_after = _addon_pairs(after)
    if source_before != 'addons_db' or source_after != 'addons_db':
        return UNVERIFIED, 'enabled_state_unavailable'
    if pairs_before != pairs_after:
        return NOT_MET, 'identity_or_enabled_changed'
    return MET, 'identity_and_enabled_match'


def _s5(before, after, labels):
    identity = _identity_status(before['addons'], after['addons'])
    addons33 = labels[0]
    if addons33 == 'EXACT':
        exact = (MET, 'addons33_exact')
    elif addons33 == 'INCONCLUSIVE':
        exact = (UNVERIFIED, 'addons33_inconclusive')
    else:
        exact = (NOT_MET, 'addons33_not_exact')
    status, reason = _combine([identity, exact], 'addons33_exact_and_identity_match')
    return _entry('S5', status, reason)


def _bundle_status(before, after):
    if before is None or after is None:
        return UNVERIFIED, 'bundle_unverified'
    if before == after:
        return MET, 'bundle_unchanged'
    return NOT_MET, 'bundle_changed'


def _s7(before, after, quit_verified, source_bound):
    checks = [
        _flag_status(quit_verified, 'quit_verified', 'quit_not_verified', 'quit_unverified'),
        _flag_status(source_bound, 'source_binding_verified', 'source_binding_failed',
                     'source_binding_unverified'),
        _flag_status(before.get('owners_absent'), 'owner_absent', 'owner_present', 'owner_unverified'),
        _flag_status(after.get('owners_absent'), 'owner_absent', 'owner_present', 'owner_unverified'),
        _flag_status(before.get('pending_publication_absent'), 'pending_publication_absent',
                     'pending_publication_present', 'pending_publication_unverified'),
        _flag_status(after.get('pending_publication_absent'), 'pending_publication_absent',
                     'pending_publication_present', 'pending_publication_unverified'),
        _bundle_status(before['bundle'], after['bundle']),
    ]
    status, reason = _combine(checks, 'owner_pending_quit_and_source_verified')
    return _entry('S7', status, reason)


def _five_file(labels):
    counts = {label: 0 for label in LABELS}
    for label in labels:
        counts[label] += 1
    if counts['MEANINGFUL']:
        status, reason = NOT_MET, 'meaningful_classification'
    elif counts['INCONCLUSIVE']:
        status, reason = UNVERIFIED, 'classification_inconclusive'
    else:
        status, reason = MET, 'eligible_classifications'
    return dict(_entry('FIVE_FILE', status, reason), counts=counts)


def _correlation_entry(correlation):
    if correlation is None:
        return _entry('OPERATION_CORRELATION', UNVERIFIED, 'correlation_missing')
    if correlation == 'VERIFIED':
        return _entry('OPERATION_CORRELATION', MET, 'correlation_verified')
    return _entry('OPERATION_CORRELATION', NOT_MET, 'correlation_broken')


def _limitations():
    # Structural: no witness in this flow establishes these scopes, and no scenario
    # justifies excluding them. A future scenario must justify any exclusion.
    return [
        _entry('S4', UNVERIFIED, 'no_witness'),
        _entry('S5_DATABASE', UNVERIFIED, 'other_addons33_content_unverified'),
        _entry('S6', UNVERIFIED, 'no_unmanaged_census'),
        _entry('S8', UNVERIFIED, 'no_source_tree_census'),
        _entry('S9', UNVERIFIED, 'scenario_dependent'),
    ]


def _block(prerequisites, reason):
    return {'schema': SCHEMA, 'assessment': ASSESSMENT, 'reason': reason,
            'verdict': 'NOT_DECIDED', 'qualification': 'not_qualified',
            'prerequisites': prerequisites, 'limitations': _limitations()}


def _assessed(prerequisites):
    statuses = {item['status'] for item in prerequisites}
    if NOT_MET in statuses:
        reason = 'prerequisite_not_met'
    elif UNVERIFIED in statuses:
        reason = 'prerequisite_unverified'
    else:
        reason = 'limitation_unverified'
    return _block(prerequisites, reason)


def _blocked(reason):
    return _block([_entry(identifier, UNVERIFIED, reason) for identifier in PREREQUISITE_IDS], reason)


def _assess(public_before, public_after, begin, after, quit_verified, source_bound, correlation):
    _check_public(public_before)
    _check_public(public_after)
    _check_begin(begin)
    labels = _check_after(after)
    _check_flag(quit_verified)
    _check_flag(source_bound)
    _need(correlation is None or (type(correlation) is str and correlation in ('VERIFIED', 'BROKEN')))
    return _assessed([
        _s1(public_before, public_after),
        _s2(public_before, public_after),
        _s5(public_before, public_after, labels),
        _s7(public_before, public_after, quit_verified, source_bound),
        _five_file(labels),
        _correlation_entry(correlation),
        _entry('EXPECTED_RESULT', UNVERIFIED, 'not_supplied'),
    ])


def assess(*, public_before, public_after, begin, after, quit_verified, source_bound, correlation=None):
    """Return the sanitized precondition block. Ordinary exceptions become fixed reason codes;
    interrupts propagate. It never reports PASS or FAIL."""
    try:
        return _assess(public_before, public_after, begin, after, quit_verified, source_bound, correlation)
    except _Reject:
        return _blocked('input_invalid')
    except Exception:
        return _blocked('internal_error')


def not_reached():
    """The block recorded when the driver never reaches the finish."""
    return _blocked('not_reached')
