"""D-032 practical precondition assessment, offline and fail-closed.

The assessment reads only values the driver has already produced: the two public
witnesses from public_state, the validated begin and after projections (including the
validated after.practical block), and two driver facts. It compares scope-specific
fields for S1, S2, S5 and S7, checks the five-file classifications for eligibility, and
lists each requirement that no witness in this flow establishes.

The after block also carries the Addons33 byte-identity witness (D-032 clarification of
2026-11-19). It is validated here, reported beside the S5_DATABASE limitation, and never
promotes it: this assessment has no authenticated scenario context, so S5_DATABASE stays
UNVERIFIED for every byte status, and a difference is never NOT_MET or a failure.

It reads and writes no file, changes no strict result, and never emits a practical PASS
or FAIL. In this task the assessment is always INCONCLUSIVE: no operation or ledger
correlation is supplied, the operation's expected result is not supplied, and the
limitation scopes cannot be justified without a future scenario.
"""
from __future__ import annotations

import hashlib
import re

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
_ADDONS_KEYS = frozenset(('count', 'enabled_state_source', 'entries', 'id_mismatch',
                          'skipped_invalid_names', 'skipped_non_directories', 'unreadable_addon_xml'))
_ADDON_COUNTERS = ('id_mismatch', 'skipped_invalid_names', 'skipped_non_directories', 'unreadable_addon_xml')
_ADDON_ENTRY_KEYS = frozenset(('enabled', 'id', 'version'))
_BUNDLE_KEYS = frozenset(('build_version', 'executable', 'identifier', 'info_plist_sha256',
                          'package_type', 'short_version'))
_ASSOCIATION_KEYS = frozenset(('device_profile_id', 'entry_id', 'resolution_fingerprint', 'schema_version'))
_BEGIN_KEYS = frozenset(('acquisition', 'files', 'scope_result'))
_AFTER_KEYS = _BEGIN_KEYS | frozenset(('practical', 'addons33_bytes'))
_BYTES_KEYS = frozenset(('schema', 'scope', 'status'))
_BYTES_STATUSES = frozenset(('BYTES_IDENTICAL', 'BYTES_DIFFERENT', 'UNVERIFIED'))
# Informational S5_DATABASE reasons by validated byte status. None of them is a promotion.
_S5_DATABASE_REASONS = {
    None: 'other_addons33_content_unverified',
    'BYTES_IDENTICAL': 'addons33_bytes_identical_scenario_unauthenticated',
    'BYTES_DIFFERENT': 'addons33_bytes_differ',
    'UNVERIFIED': 'addons33_bytes_unverified',
}
_FILE_ROW_KEYS = frozenset(('file', 'status'))
_PRACTICAL_KEYS = frozenset(('classification', 'files', 'qualification', 'schema', 'verdict'))
_PRACTICAL_ROW_KEYS = frozenset(('classification', 'file', 'maintenance', 'meaningful_count'))
# Producer grammars, each copied from the producer named beside it. The test suite checks
# the named patterns against those modules and the association and add-on grammars against
# the producer readers, so drift fails in the suite rather than in a native run.
_DIGEST_RE = re.compile(r'[0-9a-f]{64}')  # build_library._KEY
_VERSION_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.+~\-]{0,63}')  # bm_test_app._VERSION_RE
_ADDON_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}')  # bm_test_app._ADDON_ID_RE
_BUNDLE_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9.\-]{0,154}')  # bm_test_app._BUNDLE_ID_RE
_EXEC_NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._ \-]{0,127}')  # bm_test_app._EXEC_NAME_RE
_ASSOCIATION_PROFILE_RE = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}')  # AppliedBuildAssociation.from_dict
_LIBRARY_PROFILE_RE = re.compile(r'[A-Za-z0-9_.-]{1,100}')  # bm_test_app._LIBRARY_PROFILE_RE
_UNSAFE_TOKEN_RE = re.compile(r'<unsafe:[0-9a-f]{12}>')  # bm_test_app.census_build_library projection
_MAX_DEPTH = 16


class _Reject(Exception):
    """Malformed input. It carries no input text."""


def _need(condition):
    if not condition:
        raise _Reject()


def _grammar(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def _digest(value):
    return _grammar(_DIGEST_RE, value)


def _text(value):
    return type(value) is str and value != ''


def _check_flag(value):
    _need(value is None or type(value) is bool)


def _check_registry(registry):
    _need(type(registry) is dict and set(registry) == _REGISTRY_KEYS)
    present = registry['file_present']
    _need(type(present) is bool)
    ids = registry['entry_ids']
    _need(type(ids) is list and all(_digest(item) for item in ids))
    # Driver order: sorted keys of the registry entries, each key once.
    _need(ids == sorted(set(ids)) and type(registry['entry_count']) is int
          and registry['entry_count'] == len(ids))
    if present:
        _need(_digest(registry['sha256']) and type(registry['size']) is int and registry['size'] >= 0)
    else:
        _need(registry['sha256'] is None and registry['size'] is None and not ids
              and registry['entry_count'] == 0)
    return present, frozenset(ids)


def _check_library_selection(selection, registry_present, entry_ids):
    _need(type(selection) is dict and set(selection) == _SELECTION_KEYS)
    present, chosen = selection['file_present'], selection['selected']
    _need(type(present) is bool and type(chosen) is bool)
    if present:
        _need(_digest(selection['sha256']) and type(selection['size']) is int and selection['size'] >= 0)
    else:
        _need(selection['sha256'] is None and selection['size'] is None)
    if chosen:
        _need(present and registry_present and _digest(selection['entry_id'])
              and selection['entry_id'] in entry_ids and _projected_profile_shape(selection['device_profile_id']))
    else:
        _need(selection['entry_id'] is None and selection['device_profile_id'] is None)
    return present, chosen


def _check_library(value):
    if value is None:
        return
    _need(type(value) is dict and set(value) == _LIBRARY_KEYS)
    root = value['root_present']
    _need(type(root) is bool)
    registry_present, entry_ids = _check_registry(value['registry'])
    selection_present, chosen = _check_library_selection(value['selection'], registry_present, entry_ids)
    if not root:
        # The driver census reports an absent root with every nested witness absent.
        _need(not registry_present and not selection_present and not chosen)


def _projected_profile(raw):
    # bm_test_app.census_build_library: a raw profile inside the identifier grammar is projected
    # unchanged; any other raw profile is projected to a digest token of its UTF-8 bytes.
    if _LIBRARY_PROFILE_RE.fullmatch(raw) is not None:
        return raw
    return '<unsafe:' + hashlib.sha256(raw.encode('utf-8', 'surrogatepass')).hexdigest()[:12] + '>'


def _projected_profile_shape(value):
    # Any value the census can project: the profile itself, or an unsafe token.
    return _grammar(_LIBRARY_PROFILE_RE, value) or _grammar(_UNSAFE_TOKEN_RE, value)


def _check_selection_agreement(library, selection):
    if library is None or selection is None:
        return
    # The top-level selection carries the raw profile; the library record must be its exact projection.
    record = library['selection']
    _need(record['selected'] is True and record['entry_id'] == selection[0]
          and record['device_profile_id'] == _projected_profile(selection[1]))


def _check_directory(node, depth):
    _need(type(node) is dict and depth <= _MAX_DEPTH)
    for name, child in node.items():
        _need(type(name) is str and name not in ('', '.', '..') and '/' not in name and '\x00' not in name)
        if type(child) is dict:
            _check_directory(child, depth + 1)
        else:
            # A file leaf is the SHA-256 of its bytes; anything else is not a tree witness.
            _need(_digest(child))


def _check_trees(value):
    if value is None:
        return
    _need(type(value) is dict and set(value) == _TREE_KEYS)
    for tree in value.values():
        if tree is not None:
            _check_directory(tree, 0)


def _check_association(value):
    if value is None:
        return
    _need(type(value) is dict and set(value) == _ASSOCIATION_KEYS)
    version = value['schema_version']
    _need(type(version) is int and version == 2)
    _need(_digest(value['entry_id']) and _grammar(_ASSOCIATION_PROFILE_RE, value['device_profile_id'])
          and _digest(value['resolution_fingerprint']))


def _check_selection(value):
    if value is None:
        return
    _need(type(value) in (list, tuple) and len(value) == 2)
    # The raw profile may be any exact str, including '': the census projects it to a token,
    # and _check_selection_agreement requires that exact projection.
    _need(_digest(value[0]) and type(value[1]) is str)


def _addon_pairs(addons):
    _need(type(addons) is dict and set(addons) == _ADDONS_KEYS)
    source = addons['enabled_state_source']
    _need(type(source) is str and source in ('addons_db', 'unavailable'))
    # Only a census with no skipped, mismatched or unreadable addon is admissible evidence.
    for counter in _ADDON_COUNTERS:
        _need(type(addons[counter]) is int and addons[counter] == 0)
    entries = addons['entries']
    _need(type(addons['count']) is int and type(entries) is list and addons['count'] == len(entries))
    seen = set()
    pairs = []
    for entry in entries:
        _need(type(entry) is dict and set(entry) == _ADDON_ENTRY_KEYS)
        identifier, enabled = entry['id'], entry['enabled']
        _need(_grammar(_ADDON_ID_RE, identifier) and _grammar(_VERSION_RE, entry['version']))
        _need(identifier not in seen)
        seen.add(identifier)
        if source == 'addons_db':
            _need(type(enabled) is bool)
        else:
            # The census reports no enabled state without the addons database.
            _need(enabled is None)
        pairs.append((identifier, enabled))
    return (sorted(pairs) if source == 'addons_db' else None), source


def _check_bundle(value):
    if value is None:
        return
    _need(type(value) is dict and set(value) == _BUNDLE_KEYS)
    _need(_grammar(_BUNDLE_ID_RE, value['identifier']) and _grammar(_EXEC_NAME_RE, value['executable']))
    _need(value['package_type'] == 'APPL')
    for key in ('build_version', 'short_version'):
        text = value[key]
        _need(text is None or _grammar(_VERSION_RE, text))
    _need(_digest(value['info_plist_sha256']))


def _check_public(value):
    _need(type(value) is dict and _PUBLIC_KEYS <= set(value))
    _check_library(value['library'])
    _check_trees(value['trees'])
    _check_association(value['association'])
    _check_selection(value['selection'])
    _check_selection_agreement(value['library'], value['selection'])
    if value['addons'] is not None:
        _addon_pairs(value['addons'])
    _check_bundle(value['bundle'])
    _check_flag(value.get('owners_absent'))
    _check_flag(value.get('pending_publication_absent'))


def _check_rows(rows, allowed):
    _need(type(rows) is list and len(rows) == len(witness.FILES))
    statuses = []
    for row, name in zip(rows, witness.FILES):
        _need(type(row) is dict and set(row) == _FILE_ROW_KEYS and row['file'] == name)
        status = row['status']
        _need(type(status) is str and status in allowed)
        statuses.append(status)
    return statuses


def _check_begin(value):
    _need(type(value) is dict and set(value) == _BEGIN_KEYS)
    _need(value['acquisition'] == 'ACQUIRED' and value['scope_result'] == 'UNVERIFIED')
    _check_rows(value['files'], ('UNVERIFIED',))


def _aggregate(labels):
    for label in ('INCONCLUSIVE', 'MEANINGFUL', 'MAINTENANCE_ONLY'):
        if label in labels:
            return label
    return 'EXACT'


def _check_practical(value, statuses):
    _need(type(value) is dict and set(value) == _PRACTICAL_KEYS)
    _need(value['schema'] == 'bm-a15-practical-classification/1' and value['verdict'] == 'NOT_DECIDED'
          and value['qualification'] == 'not_qualified')
    rows = value['files']
    _need(type(rows) is list and len(rows) == len(witness.FILES))
    labels = []
    for index, (row, name, status) in enumerate(zip(rows, witness.FILES, statuses)):
        _need(type(row) is dict and set(row) == _PRACTICAL_ROW_KEYS and row['file'] == name)
        label, maintenance, count = row['classification'], row['maintenance'], row['meaningful_count']
        _need(type(label) is str and label in LABELS)
        _need(type(maintenance) is list and type(count) is int and count >= 0)
        names = []
        for item in maintenance:
            _need(type(item) is list and len(item) == 2 and type(item[0]) is str
                  and item[0] in _MAINTENANCE_BY_INDEX[index] and type(item[1]) is int and item[1] > 0)
            names.append(item[0])
        # Driver order: class names unique and sorted.
        _need(names == sorted(set(names)))
        if label in ('EXACT', 'INCONCLUSIVE'):
            _need(not maintenance and count == 0)
        elif label == 'MAINTENANCE_ONLY':
            _need(bool(maintenance) and count == 0)
        else:
            _need(not maintenance and count >= 1)
        # The strict result constrains the classification: an unchanged projection is
        # EXACT or INCONCLUSIVE, and a changed projection is never EXACT.
        if status == 'PRESERVED':
            _need(label in ('EXACT', 'INCONCLUSIVE'))
        else:
            _need(label != 'EXACT')
        labels.append(label)
    _need(value['classification'] == _aggregate(labels))
    return labels


def _check_addons33_bytes(value, statuses, labels):
    _need(type(value) is dict and set(value) == _BYTES_KEYS)
    schema, scope, status = value['schema'], value['scope'], value['status']
    _need(type(schema) is str and type(scope) is str and type(status) is str)
    _need(schema == 'bm-a15-addons33-bytes/1' and scope == 'addons33_file_bytes')
    _need(status in _BYTES_STATUSES)
    if status == 'BYTES_IDENTICAL':
        # Identical bytes imply an identical projection. A difference of bytes needs no such check.
        _need(statuses[0] == 'PRESERVED' and labels[0] in ('EXACT', 'INCONCLUSIVE'))
    return status


def _check_after(value):
    _need(type(value) is dict and set(value) == _AFTER_KEYS)
    _need(value['acquisition'] == 'ACQUIRED')
    statuses = _check_rows(value['files'], ('PRESERVED', 'CHANGED_OR_MISSING'))
    scope = 'PRESERVED' if all(status == 'PRESERVED' for status in statuses) else 'CHANGED_OR_MISSING'
    _need(value['scope_result'] == scope)
    labels = _check_practical(value['practical'], statuses)
    return labels, _check_addons33_bytes(value['addons33_bytes'], statuses, labels)


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


def _limitations(bytes_status=None):
    # Structural: no witness in this flow establishes these scopes, and no scenario
    # justifies excluding them. A future scenario must justify any exclusion. The validated
    # Addons33 byte status refines only the reason of S5_DATABASE. It never promotes it,
    # because no authenticated scenario context reaches this assessment.
    return [
        _entry('S4', UNVERIFIED, 'no_witness'),
        _entry('S5_DATABASE', UNVERIFIED, _S5_DATABASE_REASONS[bytes_status]),
        _entry('S6', UNVERIFIED, 'no_unmanaged_census'),
        _entry('S8', UNVERIFIED, 'no_source_tree_census'),
        _entry('S9', UNVERIFIED, 'scenario_dependent'),
    ]


def _block(prerequisites, reason, bytes_status=None):
    return {'schema': SCHEMA, 'assessment': ASSESSMENT, 'reason': reason,
            'verdict': 'NOT_DECIDED', 'qualification': 'not_qualified',
            'prerequisites': prerequisites, 'limitations': _limitations(bytes_status)}


def _assessed(prerequisites, bytes_status):
    statuses = {item['status'] for item in prerequisites}
    if NOT_MET in statuses:
        reason = 'prerequisite_not_met'
    elif UNVERIFIED in statuses:
        reason = 'prerequisite_unverified'
    else:
        reason = 'limitation_unverified'
    return _block(prerequisites, reason, bytes_status)


def _blocked(reason):
    return _block([_entry(identifier, UNVERIFIED, reason) for identifier in PREREQUISITE_IDS], reason)


def _assess(public_before, public_after, begin, after, quit_verified, source_bound, correlation):
    # Every input is validated before any prerequisite is computed, so malformed evidence
    # can never contribute a MET, even when before and after are identical.
    _check_public(public_before)
    _check_public(public_after)
    _check_begin(begin)
    labels, bytes_status = _check_after(after)
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
    ], bytes_status)


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
