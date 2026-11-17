"""Pure, in-memory D-032 practical preservation comparator.

Operates only on the five in-memory projections that
tools/bm_public_preservation_witness.py already produces: Addons33, Textures13,
guisettings.xml, the Estuary settings and the keyboard peripheral settings. It
does no file, profile, process, network or clock access, persists nothing and
logs nothing.

Output is one FileSummary per file, carrying only a verdict, closed class names
and counts: EXACT, MAINTENANCE_ONLY or MEANINGFUL. No path, value, row identity,
raw XML or SQL, hash or digest leaves this module. Malformed, unexpected or
ambiguous input raises ComparatorRejected, which is never a maintenance verdict.

Closed maintenance classes (D-032; docs/A15_NATIVE_PRESERVATION_RUNBOOK.md):
  M1_UPTIME                 general/systemtotaluptime text only; structure identical
  M2_SIZES_USECOUNT         sizes.usecount on a sizes row that is retained
  M2_SIZES_LASTUSETIME      sizes.lastusetime on a sizes row that is retained
  M2_TEXTURE_LASTHASHCHECK  texture.lasthashcheck on a texture row that is retained
  M2_CACHE_ROW_CREATE       texture rows created (identity is the primary key)
  M2_CACHE_ROW_EVICT        texture rows evicted (identity is the primary key)
  M2_CACHE_SIZES_CREATE     sizes rows belonging to created texture rows
  M2_CACHE_SIZES_EVICT      sizes rows belonging to evicted texture rows

Reviewer notes:
- Textures13: the baseline must have the exact projected schema (table order,
  column arity and types, version 13), otherwise the input is rejected. A schema
  difference in the later state is MEANINGFUL. The projection does not carry the
  sqlite_master text, so the existing producer remains the authority for the
  full CREATE statements.
- Sizes rows are maintenance only when their parent texture row is created or
  evicted in the same comparison (D-032 clarification, 2026-11-17). A sizes row
  added or removed under a retained texture row is MEANINGFUL, and no other sizes
  lifecycle is accepted.
- Duplicate sizes identity keys (idtexture, size, width, height) are ambiguous and
  rejected, because matching them would require an inference.
- The uptime value must be canonical non-negative decimal text. D-032 allows any
  change to it, so this module does not require the counter to grow.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from typing import Tuple

PROTECTED_KEYS = ('addons33', 'textures13', 'guisettings', 'estuary', 'keyboard')

EXACT = 'EXACT'
MAINTENANCE_ONLY = 'MAINTENANCE_ONLY'
MEANINGFUL = 'MEANINGFUL'

M1_UPTIME = 'M1_UPTIME'
M2_SIZES_USECOUNT = 'M2_SIZES_USECOUNT'
M2_SIZES_LASTUSETIME = 'M2_SIZES_LASTUSETIME'
M2_TEXTURE_LASTHASHCHECK = 'M2_TEXTURE_LASTHASHCHECK'
M2_CACHE_ROW_CREATE = 'M2_CACHE_ROW_CREATE'
M2_CACHE_ROW_EVICT = 'M2_CACHE_ROW_EVICT'
M2_CACHE_SIZES_CREATE = 'M2_CACHE_SIZES_CREATE'
M2_CACHE_SIZES_EVICT = 'M2_CACHE_SIZES_EVICT'
ALLOWED_CLASSES = frozenset((
    M1_UPTIME, M2_SIZES_USECOUNT, M2_SIZES_LASTUSETIME, M2_TEXTURE_LASTHASHCHECK,
    M2_CACHE_ROW_CREATE, M2_CACHE_ROW_EVICT, M2_CACHE_SIZES_CREATE, M2_CACHE_SIZES_EVICT,
))

__all__ = (
    'ALLOWED_CLASSES', 'ComparatorRejected', 'EXACT', 'FileSummary', 'MAINTENANCE_ONLY',
    'MEANINGFUL', 'PROTECTED_KEYS', 'compare_file', 'compare_protected_files',
)

# Canonical non-negative decimal integer, as Kodi's int serializer writes it.
_UPTIME_TEXT = re.compile(r'0|[1-9][0-9]{0,17}')
# Flattened key of general/systemtotaluptime: its first and only occurrence.
_UPTIME_PATH = ('node', 'general', ('systemtotaluptime', 0))
_MAX_DEPTH = 32
# Order and column kinds mirror texture_projection in tools/bm_public_preservation_witness.py.
# 'i' is an integer column and 't' is a text column.
_TEXTURE_TABLES = (('version', 'ii'), ('texture', 'itttt'), ('sizes', 'iiiiit'), ('path', 'ittt'))


@dataclass(frozen=True)
class FileSummary:
    """Sanitized verdict for one protected file: a verdict, closed class names and counts."""

    verdict: str
    maintenance: Tuple[Tuple[str, int], ...] = ()
    meaningful_count: int = 0


class ComparatorRejected(ValueError):
    """Malformed, unexpected or ambiguous input. Never a maintenance verdict.

    The message and arguments carry a logical scope and a fixed reason code only.
    """

    def __init__(self, scope, reason):
        super().__init__(scope, reason)
        self.scope = scope
        self.reason = reason

    def __str__(self):
        return f'{self.scope or "input"}: {self.reason}'


class _Reject(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _reject(reason):
    raise _Reject(reason)


def _is_seq(value):
    return isinstance(value, (list, tuple))


def _need_seq(value):
    if not _is_seq(value):
        _reject('unexpected_shape')
    return value


def _pairs(items, check_value):
    seen = set()
    pairs = []
    for item in _need_seq(items):
        if not _is_seq(item) or len(item) != 2 or type(item[0]) is not str:
            _reject('unexpected_shape')
        if item[0] in seen:
            _reject('ambiguous_key')
        seen.add(item[0])
        check_value(item[1])
        pairs.append((item[0], item[1]))
    return pairs


def _no_value_check(value):
    return None


def _text_value(value):
    if type(value) is not str:
        _reject('unexpected_shape')


def _setting_value(value):
    if not _is_seq(value) or not 1 <= len(value) <= 3:
        _reject('unexpected_shape')
    for part in value:
        if part is not None and type(part) not in (str, bool):
            _reject('unexpected_shape')


def _check_node(node, depth=0):
    if depth > _MAX_DEPTH or not _is_seq(node) or len(node) != 3:
        _reject('unexpected_shape')
    tag, text, children = node
    if type(tag) is not str or type(text) is not str or not _is_seq(children):
        _reject('unexpected_shape')
    if children and text:
        _reject('unexpected_shape')
    seen = set()
    for child in children:
        if not _is_seq(child) or len(child) != 3 or type(child[0]) is not str:
            _reject('unexpected_shape')
        # Mirrors the producer: only resolutions may repeat a child element.
        if child[0] in seen and tag != 'resolutions':
            _reject('ambiguous_key')
        seen.add(child[0])
        _check_node(child, depth + 1)


def _flatten_node(path, node, flat):
    tag, text, children = node
    flat[path] = (text, tuple(child[0] for child in children))
    occurrences = {}
    for child in children:
        index = occurrences.get(child[0], 0)
        occurrences[child[0]] = index + 1
        _flatten_node(path + ((child[0], index),), child, flat)


def _gui_parts(projection):
    if not _is_seq(projection) or len(projection) != 3:
        _reject('unexpected_shape')
    attrs = _pairs(projection[0], _text_value)
    rows = _pairs(projection[1], _setting_value)
    sections = _pairs(projection[2], _no_value_check)
    for name, node in sections:
        _check_node(node)
        if node[0] != name:
            _reject('unexpected_shape')
    return attrs, rows, sections


def _settings_parts(projection):
    if not _is_seq(projection) or len(projection) != 2:
        _reject('unexpected_shape')
    return _pairs(projection[0], _text_value), _pairs(projection[1], _setting_value)


def _flatten(attrs, rows, sections=()):
    flat = {}
    for name, value in attrs:
        flat[('attr', name)] = value
    for key, value in rows:
        flat[('setting', key)] = tuple(value)
    for name, node in sections:
        _flatten_node(('node', name), node, flat)
    return flat


def _differing(left, right, skip=None):
    keys = set(left) | set(right)
    keys.discard(skip)
    return sum(1 for key in keys if left.get(key) != right.get(key))


def _summary(meaningful, maintenance):
    if meaningful:
        return FileSummary(MEANINGFUL, (), meaningful)
    classes = tuple(sorted((name, count) for name, count in maintenance.items() if count))
    if classes:
        return FileSummary(MAINTENANCE_ONLY, classes)
    return FileSummary(EXACT)


def _check_uptime(text):
    if type(text) is not str or _UPTIME_TEXT.fullmatch(text) is None:
        _reject('malformed_uptime')


def _compare_guisettings(before, after):
    left = _flatten(*_gui_parts(before))
    right = _flatten(*_gui_parts(after))
    maintenance = {}
    skip = None
    old, new = left.get(_UPTIME_PATH), right.get(_UPTIME_PATH)
    # The M1 exception needs the same leaf on both sides. Its text is always
    # validated, even when unchanged, so malformed uptime is never treated as harmless.
    if old is not None and new is not None and old[1] == () and new[1] == ():
        _check_uptime(old[0])
        _check_uptime(new[0])
        skip = _UPTIME_PATH
        if old[0] != new[0]:
            maintenance[M1_UPTIME] = 1
    return _summary(_differing(left, right, skip), maintenance)


def _compare_settings(before, after):
    # Estuary and keyboard peripheral settings: exact, with no maintenance exception.
    left = _flatten(*_settings_parts(before))
    right = _flatten(*_settings_parts(after))
    return _summary(_differing(left, right), {})


def _addon_map(projection):
    entries = {}
    for item in _need_seq(projection):
        if (not _is_seq(item) or len(item) != 2 or type(item[0]) is not str
                or not item[0] or type(item[1]) is not bool):
            _reject('unexpected_shape')
        if item[0] in entries:
            _reject('ambiguous_key')
        entries[item[0]] = item[1]
    return entries


def _compare_addons33(before, after):
    # Installed identity and enabled state: exact, with no maintenance exception.
    return _summary(_differing(_addon_map(before), _addon_map(after)), {})


def _load_json(blob):
    try:
        return json.loads(blob.decode('ascii'))
    except Exception:
        return None


def _decode_row(blob):
    if type(blob) is not bytes:
        _reject('malformed_row')
    value = _load_json(blob)
    if not isinstance(value, list) or json.dumps(value, ensure_ascii=True).encode('ascii') != blob:
        _reject('malformed_row')
    for item in value:
        if item is not None and type(item) not in (int, str):
            _reject('malformed_row')
    return tuple(value)


def _decode_tables(projection):
    seen = set()
    tables = []
    for item in _need_seq(projection):
        if not _is_seq(item) or len(item) != 2 or type(item[0]) is not str:
            _reject('unexpected_shape')
        name, blobs = item
        if name in seen:
            _reject('ambiguous_key')
        seen.add(name)
        tables.append((name, [_decode_row(blob) for blob in _need_seq(blobs)]))
    return tables


def _is_exact(tables):
    if [name for name, _ in tables] != [name for name, _ in _TEXTURE_TABLES]:
        return False
    for (_, rows), (_, pattern) in zip(tables, _TEXTURE_TABLES):
        for row in rows:
            if len(row) != len(pattern):
                return False
            for value, kind in zip(row, pattern):
                wanted = int if kind == 'i' else str
                if value is not None and type(value) is not wanted:
                    return False
    version = dict(tables)['version']
    return len(version) == 1 and version[0][0] == 13 and type(version[0][1]) is int


def _check_exact_identities(tables):
    tables = dict(tables)
    texture_ids = [row[0] for row in tables['texture']]
    path_ids = [row[0] for row in tables['path']]
    if len(set(texture_ids)) != len(texture_ids) or len(set(path_ids)) != len(path_ids):
        _reject('ambiguous_key')
    if any(type(value) is not int for value in texture_ids + path_ids):
        _reject('malformed_row')
    known = set(texture_ids)
    keys = []
    for row in tables['sizes']:
        if type(row[0]) is not int or row[0] not in known:
            _reject('orphan_row')
        keys.append(row[:4])
    if len(set(keys)) != len(keys):
        _reject('ambiguous_key')


def _compare_exact(before, after):
    old, new = dict(before), dict(after)
    meaningful = 0
    if old['version'] != new['version']:
        meaningful += 1
    old_path = {row[0]: row for row in old['path']}
    new_path = {row[0]: row for row in new['path']}
    meaningful += sum(1 for key in old_path.keys() | new_path.keys()
                      if old_path.get(key) != new_path.get(key))
    old_texture = {row[0]: row for row in old['texture']}
    new_texture = {row[0]: row for row in new['texture']}
    created = new_texture.keys() - old_texture.keys()
    evicted = old_texture.keys() - new_texture.keys()
    lasthashcheck = 0
    for key in old_texture.keys() & new_texture.keys():
        was, now = old_texture[key], new_texture[key]
        if was[1:4] != now[1:4]:  # url, cachedurl, imagehash must stay identical
            meaningful += 1
        if was[4] != now[4]:
            lasthashcheck += 1
    old_sizes = {row[:4]: row for row in old['sizes']}
    new_sizes = {row[:4]: row for row in new['sizes']}
    usecount = lastusetime = 0
    for key in old_sizes.keys() & new_sizes.keys():
        was, now = old_sizes[key], new_sizes[key]
        if was[4] != now[4]:
            usecount += 1
        if was[5] != now[5]:
            lastusetime += 1
    added = new_sizes.keys() - old_sizes.keys()
    removed = old_sizes.keys() - new_sizes.keys()
    sizes_created = sum(1 for key in added if key[0] in created)
    sizes_evicted = sum(1 for key in removed if key[0] in evicted)
    meaningful += sum(1 for key in added if key[0] not in created)
    meaningful += sum(1 for key in removed if key[0] not in evicted)
    return _summary(meaningful, {
        M2_TEXTURE_LASTHASHCHECK: lasthashcheck,
        M2_SIZES_USECOUNT: usecount,
        M2_SIZES_LASTUSETIME: lastusetime,
        M2_CACHE_ROW_CREATE: len(created),
        M2_CACHE_ROW_EVICT: len(evicted),
        M2_CACHE_SIZES_CREATE: sizes_created,
        M2_CACHE_SIZES_EVICT: sizes_evicted,
    })


def _compare_textures(before, after):
    old = _decode_tables(before)
    if not _is_exact(old):
        _reject('unexpected_schema')
    new = _decode_tables(after)
    if not _is_exact(new):
        # A later schema difference is itself a change, never maintenance.
        return FileSummary(MEANINGFUL, (), 1)
    _check_exact_identities(old)
    _check_exact_identities(new)
    return _compare_exact(old, new)


_COMPARATORS = {
    'addons33': _compare_addons33,
    'textures13': _compare_textures,
    'guisettings': _compare_guisettings,
    'estuary': _compare_settings,
    'keyboard': _compare_settings,
}


def compare_file(key, before, after):
    """Return the sanitized summary for one protected file, or raise ComparatorRejected."""
    if type(key) is not str or key not in _COMPARATORS:
        raise ComparatorRejected(None, 'invalid_input')
    reason = None
    try:
        summary = _COMPARATORS[key](before, after)
    except _Reject as exc:
        reason = exc.reason
    except Exception:
        reason = 'internal_error'
    # Raised outside the handler so no input-bearing exception is chained.
    if reason is not None:
        raise ComparatorRejected(key, reason)
    return summary


def _snapshot(mapping):
    """Read one mapping's five projections once. Returns (values, reason).

    Any Exception raised by the caller's mapping (isinstance, iteration, hashing,
    equality or lookup) becomes the fixed code 'mapping_error', so caller text never
    reaches the public API. BaseException (interrupts, exit) is not caught.
    """
    try:
        if not isinstance(mapping, Mapping):
            return None, 'invalid_input'
        if set(mapping) != set(PROTECTED_KEYS):
            return None, 'invalid_input'
        return tuple(mapping[key] for key in PROTECTED_KEYS), None
    except Exception:
        return None, 'mapping_error'


def compare_protected_files(before, after):
    """Compare two complete sets of the five in-memory projections.

    Both mappings must carry exactly PROTECTED_KEYS. Returns one FileSummary per key.
    A structural mismatch raises 'invalid_input'; a fault inside a caller's mapping
    raises 'mapping_error'. Neither chains the caller's exception. The comparator
    cannot clear exception context that a caller holds in its own frames.
    """
    old, reason = _snapshot(before)
    if reason is None:
        new, reason = _snapshot(after)
    # Raised outside every handler, so no caller exception is chained.
    if reason is not None:
        raise ComparatorRejected(None, reason)
    return {key: compare_file(key, left, right)
            for key, left, right in zip(PROTECTED_KEYS, old, new)}
