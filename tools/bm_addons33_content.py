"""Offline full logical content witness for Addons33.db bytes (D-032 S5_DATABASE).

Standalone: this module imports no other BM module, reads no Kodi path, writes no
product file, and returns only fixed status and reason codes plus bounded integer
counts. Its input is bytes from a quiescent, independently obtained copy of the
database. Bytes cannot prove that a rollback journal or sidecar is absent for that
copy, so the caller must establish quiescence. This module refuses the WAL states it
can see in the header.

The logical projection covers the complete content of the database: every schema
object (type, name, table and exact definition text), user_version and application_id,
and every ordinary table's complete typed rows as a multiset. Each row of a rowid table
carries its observable rowid, read through the first of rowid, _rowid_ or oid that no
column of the table shadows, because views and triggers can expose that identity. A
WITHOUT ROWID table is identified by its primary key columns, which are already row
content. A table whose rowid aliases are all shadowed is INCONCLUSIVE. Row order and
physical page layout are not compared. Index contents are covered by their definitions
and by integrity_check. A rowid renumbering, for example by a maintenance operation,
is an observable difference and is classified MEANINGFUL.

Classification: EXACT, MEANINGFUL or INCONCLUSIVE. There are no maintenance classes.
Any demonstrated difference is MEANINGFUL until separately adjudicated under D-032.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import os
import re
import sqlite3
import tempfile
import urllib.parse

SCHEMA = 'bm-addons33-content/1'
SCOPE = 'addons33_full_logical_content'
EXACT = 'EXACT'
MEANINGFUL = 'MEANINGFUL'
INCONCLUSIVE = 'INCONCLUSIVE'
FIXED_REASONS = frozenset((
    'logical_content_identical', 'schema_changed', 'pragma_changed', 'rows_changed',
    'input_not_bytes', 'input_too_large', 'not_sqlite', 'unsupported_page_size',
    'wal_mode_uncertain', 'malformed_database', 'unsupported_encoding', 'integrity_failed',
    'unsupported_schema_object', 'virtual_table_unsupported', 'schema_object_cap', 'row_cap',
    'value_too_large', 'unsupported_value_type', 'projection_too_large', 'budget_exhausted',
    'read_failed', 'unsupported_text', 'cleanup_failed', 'internal_error',
))

# Bounds. Module-level so that tests can lower them; each is read at use time.
_MAX_DATABASE_BYTES = 32 << 20
_MAX_SCHEMA_OBJECTS = 256
_MAX_ROWS_PER_TABLE = 10000
_MAX_TOTAL_ROWS = 50000
_MAX_VALUE_BYTES = 1 << 20
_MAX_PROJECTION_BYTES = 32 << 20
_PROGRESS_INTERVAL = 1000  # SQLite virtual-machine instructions per progress callback
_MAX_PROGRESS_STEPS = 20000
_MAX_COLUMNS = 1024
_ROWID_ALIASES = ('rowid', '_rowid_', 'oid')

_HEADER_BYTES = 100
_MAGIC = b'SQLite format 3\x00'
_SCHEMA_KINDS = frozenset(('table', 'index', 'view', 'trigger'))
_VIRTUAL_TABLE = re.compile(r'\s*CREATE\s+VIRTUAL\s+TABLE\b', re.IGNORECASE)
_TEXT_TAG = 'T'
_PRIVATE_PREFIX = 'bm-addons33-content-'


class _Refused(Exception):
    """Fixed-code refusal. The code is the only text that may leave this module."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _Projection:
    schema: tuple  # sorted (kind, name, table, definition-or-None)
    pragmas: tuple  # (user_version, application_id)
    rows: tuple  # sorted (table name, rowid alias or '', canonical row bytes); duplicates kept
    tables: int


class _Budget:
    __slots__ = ('steps', 'exhausted')

    def __init__(self):
        self.steps = 0
        self.exhausted = False

    def step(self):
        self.steps += 1
        if self.steps > _MAX_PROGRESS_STEPS:
            self.exhausted = True
            return 1
        return 0


def _check_header(raw):
    if type(raw) is not bytes:
        raise _Refused('input_not_bytes')
    if len(raw) > _MAX_DATABASE_BYTES:
        raise _Refused('input_too_large')
    if len(raw) < _HEADER_BYTES or raw[:16] != _MAGIC:
        raise _Refused('not_sqlite')
    page = int.from_bytes(raw[16:18], 'big')
    if page == 1:
        page = 65536
    if page < 512 or page > 65536 or page & (page - 1):
        raise _Refused('unsupported_page_size')
    if raw[18] == 2 or raw[19] == 2:
        raise _Refused('wal_mode_uncertain')
    if raw[18] != 1 or raw[19] != 1:
        raise _Refused('malformed_database')
    if int.from_bytes(raw[56:60], 'big') != 1:
        raise _Refused('unsupported_encoding')
    # SQLite files are whole pages; a shorter file is an incomplete read.
    if len(raw) % page:
        raise _Refused('malformed_database')


def _close_descriptor(descriptor):
    try:
        os.close(descriptor)
    except OSError:
        pass  # a failed fdopen may already have released the descriptor


def _write_copy(directory, raw):
    path = os.path.join(directory, 'copy.db')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        stream = os.fdopen(descriptor, 'wb')
    except BaseException:
        # Ownership never reached the stream, so this function still owns the descriptor.
        _close_descriptor(descriptor)
        raise
    with stream:  # from here the stream owns the descriptor and closes it exactly once
        if stream.write(raw) != len(raw):
            raise _Refused('read_failed')
    return path


def _close_quietly(connection):
    try:
        connection.close()
    except Exception:
        return False
    return True


def _open(path, budget):
    uri = 'file:' + urllib.parse.quote(path) + '?mode=ro&immutable=1'
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    try:
        connection.execute('PRAGMA query_only = 1')
        connection.execute('PRAGMA trusted_schema = OFF')
        connection.set_progress_handler(budget.step, _PROGRESS_INTERVAL)
    except BaseException:
        _close_quietly(connection)
        raise
    return connection


def _translate(exc, budget):
    if isinstance(exc, _Refused):
        return exc
    if budget.exhausted:
        return _Refused('budget_exhausted')
    if isinstance(exc, UnicodeDecodeError):
        return _Refused('unsupported_text')
    if isinstance(exc, sqlite3.OperationalError):
        return _Refused('read_failed')
    if isinstance(exc, sqlite3.DatabaseError):
        return _Refused('malformed_database')
    return _Refused('internal_error')


def _rows(connection, sql, factory, cap, code, params=()):
    connection.text_factory = factory
    cursor = connection.execute(sql, params)
    try:
        found = []
        for row in cursor:
            if len(found) >= cap:
                raise _Refused(code)
            found.append(row)
        return found
    finally:
        cursor.close()


def _text(raw):
    if type(raw) is not bytes:
        raise _Refused('unsupported_schema_object')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        raise _Refused('unsupported_text') from None


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _identity_alias(connection, name):
    """The rowid alias that observes a rowid table's row identity, or None for WITHOUT ROWID.

    rowid, _rowid_ and oid name the same implicit rowid unless a column shadows that name.
    A probe that fails with 'no such column' on an unshadowed alias means that the table
    has no rowid. Any other failure propagates, so it is never read as WITHOUT ROWID.
    """
    columns = {_text(raw).lower() for (raw,) in _rows(
        connection, 'SELECT name FROM pragma_table_xinfo(?)', bytes, _MAX_COLUMNS,
        'schema_object_cap', (name,))}
    if all(alias in columns for alias in _ROWID_ALIASES):
        raise _Refused('unsupported_schema_object')
    for alias in _ROWID_ALIASES:
        if alias in columns:
            continue
        try:
            connection.execute('SELECT ' + alias + ' FROM ' + _quote(name) + ' LIMIT 0').close()
        except sqlite3.OperationalError as exc:
            if 'no such column' in str(exc):
                return None
            raise
        return alias
    raise _Refused('unsupported_schema_object')


def _single_int(connection, sql):
    found = _rows(connection, sql, bytes, 1, 'malformed_database')
    if len(found) != 1 or type(found[0][0]) is not int:
        raise _Refused('malformed_database')
    return found[0][0]


def _tagged(raw):
    # TEXT arrives as a tagged tuple and BLOB as plain bytes, so the two stay distinct.
    return (_TEXT_TAG, raw)


def _check_value(raw):
    if len(raw) > _MAX_VALUE_BYTES:
        raise _Refused('value_too_large')


def _cell(value):
    if value is None:
        return ['N']
    if type(value) is int:
        return ['I', value]
    if type(value) is float:
        return ['R', value.hex()]
    if type(value) is bytes:
        _check_value(value)
        return ['B', value.hex()]
    if type(value) is tuple and len(value) == 2 and value[0] == _TEXT_TAG and type(value[1]) is bytes:
        _check_value(value[1])
        return ['T', value[1].hex()]
    raise _Refused('unsupported_value_type')


def _row_bytes(row):
    cells = [_cell(value) for value in row]
    return json.dumps(cells, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _schema_key(item):
    return (item[0], item[1], item[2], item[3] is None, item[3] or '')


def _gather(connection, budget):
    integrity = _rows(connection, 'PRAGMA integrity_check', bytes, 1, 'integrity_failed')
    if integrity != [(b'ok',)]:
        raise _Refused('integrity_failed')
    user_version = _single_int(connection, 'PRAGMA user_version')
    application_id = _single_int(connection, 'PRAGMA application_id')
    objects = _rows(connection, 'SELECT type, name, tbl_name, sql FROM sqlite_master', bytes,
                    _MAX_SCHEMA_OBJECTS, 'schema_object_cap')
    size = 0
    schema = []
    tables = []
    for kind_raw, name_raw, table_raw, sql_raw in objects:
        kind = _text(kind_raw)
        if kind not in _SCHEMA_KINDS:
            raise _Refused('unsupported_schema_object')
        name = _text(name_raw)
        table = _text(table_raw)
        sql = None if sql_raw is None else _text(sql_raw)
        if kind == 'table':
            if sql is None:
                raise _Refused('unsupported_schema_object')
            if _VIRTUAL_TABLE.match(sql):
                raise _Refused('virtual_table_unsupported')
            tables.append(name)
        schema.append((kind, name, table, sql))
        size += len(name_raw) + len(table_raw) + len(sql_raw or b'')
        if size > _MAX_PROJECTION_BYTES:
            raise _Refused('projection_too_large')
    schema.sort(key=_schema_key)
    all_rows = []
    total_rows = 0
    for name in sorted(tables):
        alias = _identity_alias(connection, name)
        select = '*' if alias is None else alias + ', *'
        found = _rows(connection, 'SELECT ' + select + ' FROM ' + _quote(name), _tagged,
                      _MAX_ROWS_PER_TABLE, 'row_cap')
        total_rows += len(found)
        if total_rows > _MAX_TOTAL_ROWS:
            raise _Refused('row_cap')
        for row in found:
            encoded = _row_bytes(row)
            size += len(encoded)
            if size > _MAX_PROJECTION_BYTES:
                raise _Refused('projection_too_large')
            all_rows.append((name, alias or '', encoded))
    all_rows.sort()
    return _Projection(schema=tuple(schema), pragmas=(user_version, application_id),
                       rows=tuple(all_rows), tables=len(tables))


def _read_projection(path):
    budget = _Budget()
    try:
        connection = _open(path, budget)
    except Exception as exc:
        raise _translate(exc, budget) from None
    try:
        projection = _gather(connection, budget)
    except Exception as exc:
        _close_quietly(connection)
        raise _translate(exc, budget) from None
    except BaseException:
        _close_quietly(connection)
        raise
    if not _close_quietly(connection):
        raise _Refused('cleanup_failed')
    return projection


def _remove(directory):
    try:
        directory.cleanup()
    except Exception:
        return False
    return True


def _project_database(raw):
    _check_header(raw)
    directory = tempfile.TemporaryDirectory(prefix=_PRIVATE_PREFIX)
    try:
        path = _write_copy(directory.name, raw)
        projection = _read_projection(path)
    except BaseException:
        # Cleanup is attempted on every path; an interrupt or refusal is never masked.
        _remove(directory)
        raise
    if not _remove(directory):
        raise _Refused('cleanup_failed')
    return projection


def _difference(left, right):
    return sum((left - right).values()) + sum((right - left).values())


def _result(status, reason, counts=None):
    result = {'schema': SCHEMA, 'scope': SCOPE, 'status': status, 'reason': reason}
    if counts is not None:
        result['counts'] = dict(counts)
    return result


def _classify(before, after):
    counts = {
        'schema_changes': _difference(Counter(before.schema), Counter(after.schema)),
        'pragma_changes': sum(1 for left, right in zip(before.pragmas, after.pragmas) if left != right),
        'row_changes': _difference(Counter(before.rows), Counter(after.rows)),
        'schema_objects_before': len(before.schema),
        'schema_objects_after': len(after.schema),
        'tables_before': before.tables,
        'tables_after': after.tables,
        'rows_before': len(before.rows),
        'rows_after': len(after.rows),
    }
    if counts['schema_changes']:
        return _result(MEANINGFUL, 'schema_changed', counts)
    if counts['pragma_changes']:
        return _result(MEANINGFUL, 'pragma_changed', counts)
    if counts['row_changes']:
        return _result(MEANINGFUL, 'rows_changed', counts)
    return _result(EXACT, 'logical_content_identical', counts)


def compare_databases(before, after):
    """Compare two Addons33 database byte strings. Returns a sanitized result only.

    EXACT when both are valid and their logical content is identical; MEANINGFUL when
    both are valid and any schema, pragma or row difference is demonstrated;
    INCONCLUSIVE when either side cannot be safely and completely established.
    KeyboardInterrupt and SystemExit propagate.
    """
    try:
        left = _project_database(before)
    except _Refused as exc:
        return _result(INCONCLUSIVE, exc.code)
    except Exception:
        return _result(INCONCLUSIVE, 'internal_error')
    try:
        right = _project_database(after)
    except _Refused as exc:
        return _result(INCONCLUSIVE, exc.code)
    except Exception:
        return _result(INCONCLUSIVE, 'internal_error')
    try:
        return _classify(left, right)
    except Exception:
        # The fixed-code boundary covers classification as well as projection.
        return _result(INCONCLUSIVE, 'internal_error')
