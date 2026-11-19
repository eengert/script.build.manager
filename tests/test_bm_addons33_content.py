"""Synthetic offline tests for the Addons33 full logical content witness.

Every database is a disposable synthetic SQLite file built in a test-owned temporary
directory. No Kodi path, profile or product file is read.
"""
import ast
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from tools import bm_addons33_content as witness

SECRET = 'synthetic-private-addons-value'
INSTALLED_SQL = ('CREATE TABLE installed (id INTEGER PRIMARY KEY, addonID TEXT, enabled BOOLEAN, '
                 'installDate TEXT, lastUpdated TEXT, lastUsed TEXT, origin TEXT, disabledReason INTEGER)')
PLAIN_SQL = 'CREATE TABLE plain (a TEXT, b INTEGER)'
ALLOWED_IMPORTS = frozenset(('__future__', 'collections', 'dataclasses', 'json', 'os', 're', 'sqlite3',
                             'tempfile', 'urllib'))
RESULT_KEYS = frozenset(('schema', 'scope', 'status', 'reason', 'counts'))
COUNT_KEYS = frozenset(('schema_changes', 'pragma_changes', 'row_changes', 'schema_objects_before',
                        'schema_objects_after', 'tables_before', 'tables_after', 'rows_before', 'rows_after'))


def _has_fts5():
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('CREATE VIRTUAL TABLE probe USING fts5(body)')
        return True
    except sqlite3.Error:
        return False
    finally:
        connection.close()


HAS_FTS5 = _has_fts5()


def build(*statements, user_version=None):
    """Synthetic database bytes produced by SQLite itself in a private test directory."""
    with tempfile.TemporaryDirectory(prefix='bm-addons33-test-') as directory:
        path = os.path.join(directory, 'synthetic.db')
        connection = sqlite3.connect(path)
        try:
            for statement in statements:
                connection.execute(statement)
            if user_version is not None:
                connection.execute('PRAGMA user_version = %d' % user_version)
            connection.commit()
        finally:
            connection.close()
        with open(path, 'rb') as stream:
            return stream.read()


def installed_row(addon, enabled=1, last_used='2026-01-03'):
    return ("INSERT INTO installed (addonID, enabled, installDate, lastUpdated, lastUsed, origin, disabledReason) "
            "VALUES ('%s', %d, '2026-01-01', '2026-01-02', '%s', '', 0)" % (addon, enabled, last_used))


def installed_db(*rows, user_version=None):
    return build(INSTALLED_SQL, *rows, user_version=user_version)


def observed_rows(raw):
    """Rows read through a view that exposes rowid, using an independent SQLite connection."""
    with tempfile.TemporaryDirectory(prefix='bm-addons33-test-') as directory:
        path = os.path.join(directory, 'synthetic.db')
        with open(path, 'wb') as stream:
            stream.write(raw)
        connection = sqlite3.connect('file:' + path + '?mode=ro', uri=True)
        try:
            return connection.execute('SELECT identity, v FROM observed').fetchall()
        finally:
            connection.close()


def build_corrupt_table_page():
    """A valid header with an invalid b-tree page type on the installed table's root page."""
    with tempfile.TemporaryDirectory(prefix='bm-addons33-test-') as directory:
        path = os.path.join(directory, 'synthetic.db')
        connection = sqlite3.connect(path)
        try:
            connection.execute(INSTALLED_SQL)
            connection.execute(installed_row('script.synthetic'))
            connection.commit()
            rootpage = connection.execute(
                "SELECT rootpage FROM sqlite_master WHERE name = 'installed'").fetchone()[0]
        finally:
            connection.close()
        with open(path, 'rb') as stream:
            raw = bytearray(stream.read())
    page_size = int.from_bytes(raw[16:18], 'big')
    raw[(rootpage - 1) * page_size] = 0x07
    return bytes(raw)


def private_copies():
    return {name for name in os.listdir(tempfile.gettempdir()) if name.startswith('bm-addons33-content-')}


class ContentWitnessTests(unittest.TestCase):
    def compare(self, before, after):
        return witness.compare_databases(before, after)

    def assertReason(self, result, status, reason):
        self.assertEqual((result['status'], result['reason']), (status, reason))

    def assertInconclusive(self, result, reason):
        self.assertReason(result, witness.INCONCLUSIVE, reason)
        self.assertNotIn('counts', result)

    def assertSanitized(self, result):
        self.assertTrue(set(result) <= RESULT_KEYS, set(result))
        self.assertIn(result['reason'], witness.FIXED_REASONS)
        self.assertIn(result['status'], (witness.EXACT, witness.MEANINGFUL, witness.INCONCLUSIVE))
        self.assertEqual((result['schema'], result['scope']), (witness.SCHEMA, witness.SCOPE))
        if 'counts' in result:
            self.assertEqual(set(result['counts']), COUNT_KEYS)
            for value in result['counts'].values():
                self.assertIs(type(value), int)
        self.assertNotIn(SECRET, json.dumps(result, sort_keys=True))

    # Identity and ordering --------------------------------------------------

    def test_identical_databases_are_exact(self):
        database = installed_db(installed_row('script.synthetic'), installed_row('script.other', 0))
        result = self.compare(database, database)
        self.assertReason(result, witness.EXACT, 'logical_content_identical')
        self.assertEqual(result['counts']['row_changes'], 0)
        self.assertSanitized(result)

    def test_repeated_comparison_is_deterministic(self):
        before, after = installed_db(installed_row('a')), installed_db(installed_row('b'))
        self.assertEqual(self.compare(before, after), self.compare(before, after))

    def test_reordered_rows_are_exact(self):
        # Physical insertion order is not logical content while every rowid keeps its value.
        forward = build(PLAIN_SQL, "INSERT INTO plain(rowid, a, b) VALUES (1, 'x', 1)",
                        "INSERT INTO plain(rowid, a, b) VALUES (2, 'y', 2)",
                        "INSERT INTO plain(rowid, a, b) VALUES (3, 'z', 3)")
        reversed_ = build(PLAIN_SQL, "INSERT INTO plain(rowid, a, b) VALUES (3, 'z', 3)",
                          "INSERT INTO plain(rowid, a, b) VALUES (2, 'y', 2)",
                          "INSERT INTO plain(rowid, a, b) VALUES (1, 'x', 1)")
        result = self.compare(forward, reversed_)
        self.assertReason(result, witness.EXACT, 'logical_content_identical')

    def test_insertion_order_that_reassigns_rowids_is_meaningful(self):
        # The same declared rows in reverse insertion order carry different rowids.
        forward = build(PLAIN_SQL, "INSERT INTO plain VALUES ('x', 1)", "INSERT INTO plain VALUES ('y', 2)",
                        "INSERT INTO plain VALUES ('z', 3)")
        reversed_ = build(PLAIN_SQL, "INSERT INTO plain VALUES ('z', 3)", "INSERT INTO plain VALUES ('y', 2)",
                          "INSERT INTO plain VALUES ('x', 1)")
        result = self.compare(forward, reversed_)
        self.assertReason(result, witness.MEANINGFUL, 'rows_changed')
        self.assertEqual(result['counts']['row_changes'], 4)

    def test_observable_rowid_through_a_view_is_meaningful(self):
        # The view exposes rowid, so the same declared value at another rowid is observable.
        view = 'CREATE VIEW observed AS SELECT rowid AS identity, v FROM t'
        before = build('CREATE TABLE t(v TEXT)', view, "INSERT INTO t VALUES ('x')")
        after = build('CREATE TABLE t(v TEXT)', view, "INSERT INTO t VALUES ('y')",
                      "INSERT INTO t VALUES ('x')", "DELETE FROM t WHERE v = 'y'")
        self.assertEqual(observed_rows(before), [(1, 'x')])
        self.assertEqual(observed_rows(after), [(2, 'x')])
        result = self.compare(before, after)
        self.assertReason(result, witness.MEANINGFUL, 'rows_changed')
        self.assertEqual(result['counts']['row_changes'], 2)
        self.assertSanitized(result)

    def test_without_rowid_tables_compare_by_primary_key(self):
        schema = 'CREATE TABLE w(k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID'
        forward = build(schema, "INSERT INTO w VALUES ('a', '1')", "INSERT INTO w VALUES ('b', '2')")
        reversed_ = build(schema, "INSERT INTO w VALUES ('b', '2')", "INSERT INTO w VALUES ('a', '1')")
        self.assertReason(self.compare(forward, reversed_), witness.EXACT, 'logical_content_identical')
        changed = build(schema, "INSERT INTO w VALUES ('a', '1')", "INSERT INTO w VALUES ('b', '3')")
        self.assertReason(self.compare(forward, changed), witness.MEANINGFUL, 'rows_changed')

    def test_integer_primary_key_alias_is_compared_by_value(self):
        schema = 'CREATE TABLE ipk(id INTEGER PRIMARY KEY, v TEXT)'
        before = build(schema, "INSERT INTO ipk VALUES (1, 'x')", "INSERT INTO ipk VALUES (2, 'y')")
        reversed_ = build(schema, "INSERT INTO ipk VALUES (2, 'y')", "INSERT INTO ipk VALUES (1, 'x')")
        self.assertReason(self.compare(before, reversed_), witness.EXACT, 'logical_content_identical')
        swapped = build(schema, "INSERT INTO ipk VALUES (1, 'y')", "INSERT INTO ipk VALUES (2, 'x')")
        self.assertReason(self.compare(before, swapped), witness.MEANINGFUL, 'rows_changed')

    def test_shadowed_rowid_column_falls_back_to_an_unshadowed_alias(self):
        schema = 'CREATE TABLE sh(rowid TEXT, v TEXT)'
        before = build(schema, "INSERT INTO sh VALUES ('a', 'x')")
        same = build(schema, "INSERT INTO sh VALUES ('a', 'x')")
        self.assertReason(self.compare(before, same), witness.EXACT, 'logical_content_identical')
        moved = build(schema, "INSERT INTO sh VALUES ('z', 'q')", "INSERT INTO sh VALUES ('a', 'x')",
                      "DELETE FROM sh WHERE rowid = 'z'")
        self.assertReason(self.compare(before, moved), witness.MEANINGFUL, 'rows_changed')

    def test_table_with_every_rowid_alias_shadowed_is_inconclusive(self):
        valid = build('CREATE TABLE shadowed(rowid, _rowid_, oid)', 'INSERT INTO shadowed VALUES (1, 2, 3)')
        self.assertInconclusive(self.compare(valid, valid), 'unsupported_schema_object')

    def test_empty_database_is_exact_with_no_tables(self):
        empty = build('CREATE TABLE gone (x)', 'DROP TABLE gone')
        result = self.compare(empty, empty)
        self.assertReason(result, witness.EXACT, 'logical_content_identical')
        self.assertEqual(result['counts']['tables_before'], 0)

    # Rows -------------------------------------------------------------------

    def test_last_used_change_is_meaningful(self):
        before = installed_db(installed_row('script.synthetic', last_used='2026-01-03'))
        after = installed_db(installed_row('script.synthetic', last_used='2026-01-04'))
        result = self.compare(before, after)
        self.assertReason(result, witness.MEANINGFUL, 'rows_changed')
        self.assertEqual(result['counts']['row_changes'], 2)
        self.assertSanitized(result)

    def test_added_and_removed_rows_are_meaningful(self):
        base = build(PLAIN_SQL, "INSERT INTO plain VALUES ('x', 1)", "INSERT INTO plain VALUES ('y', 2)")
        more = build(PLAIN_SQL, "INSERT INTO plain VALUES ('x', 1)", "INSERT INTO plain VALUES ('y', 2)",
                     "INSERT INTO plain VALUES ('z', 3)")
        for before, after in ((base, more), (more, base)):
            with self.subTest(direction=before == base):
                result = self.compare(before, after)
                self.assertReason(result, witness.MEANINGFUL, 'rows_changed')
                self.assertEqual(result['counts']['row_changes'], 1)

    def test_duplicate_multiplicity_is_preserved(self):
        once = build(PLAIN_SQL, "INSERT INTO plain VALUES ('x', 1)")
        twice = build(PLAIN_SQL, "INSERT INTO plain VALUES ('x', 1)", "INSERT INTO plain VALUES ('x', 1)")
        for before, after in ((once, twice), (twice, once)):
            with self.subTest(direction=before == once):
                result = self.compare(before, after)
                self.assertReason(result, witness.MEANINGFUL, 'rows_changed')
                self.assertEqual(result['counts']['row_changes'], 1)

    def test_null_blob_text_integer_and_real_values_are_distinct(self):
        untyped = 'CREATE TABLE untyped (x)'
        cases = {
            'null_versus_empty_text': (PLAIN_SQL, "INSERT INTO plain VALUES (NULL, 1)",
                                       "INSERT INTO plain VALUES ('', 1)"),
            'blob_bytes_change': (PLAIN_SQL, "INSERT INTO plain VALUES (x'0001', 1)",
                                  "INSERT INTO plain VALUES (x'0002', 1)"),
            'text_versus_blob': (PLAIN_SQL, "INSERT INTO plain VALUES ('a', 1)",
                                 "INSERT INTO plain VALUES (x'61', 1)"),
            # Without affinity the stored type itself differs; TEXT affinity would coerce 1 to '1'.
            'integer_versus_text': (untyped, 'INSERT INTO untyped VALUES (1)',
                                    "INSERT INTO untyped VALUES ('1')"),
            'real_value_change': (PLAIN_SQL, 'INSERT INTO plain VALUES (1.5, 1.5)',
                                  'INSERT INTO plain VALUES (1.5, 1.25)'),
        }
        for name, (schema, left, right) in cases.items():
            with self.subTest(case=name):
                result = self.compare(build(schema, left), build(schema, right))
                self.assertReason(result, witness.MEANINGFUL, 'rows_changed')

    def test_identical_null_blob_text_and_real_values_are_exact(self):
        statements = (PLAIN_SQL, "INSERT INTO plain VALUES (NULL, NULL)", "INSERT INTO plain VALUES ('', 0)",
                      "INSERT INTO plain VALUES (x'00ff', 2)", "INSERT INTO plain VALUES ('text', -3)")
        database = build(*statements)
        result = self.compare(database, build(*statements))
        self.assertReason(result, witness.EXACT, 'logical_content_identical')

    # Schema -----------------------------------------------------------------

    def test_added_table_index_view_or_trigger_is_a_schema_change(self):
        base = installed_db(installed_row('script.synthetic'))
        additions = {
            'table': PLAIN_SQL,
            'index': 'CREATE INDEX ix_addon ON installed(addonID)',
            'view': 'CREATE VIEW v_addon AS SELECT addonID FROM installed',
            'trigger': 'CREATE TRIGGER tr_addon AFTER INSERT ON installed BEGIN SELECT 1; END',
        }
        for name, statement in additions.items():
            with self.subTest(object=name):
                changed = build(INSTALLED_SQL, installed_row('script.synthetic'), statement)
                result = self.compare(base, changed)
                self.assertReason(result, witness.MEANINGFUL, 'schema_changed')
                self.assertGreaterEqual(result['counts']['schema_changes'], 1)

    def test_definition_text_change_is_a_schema_change_even_when_only_whitespace(self):
        before = build('CREATE TABLE t (a TEXT)')
        after = build('CREATE TABLE t (a  TEXT)')
        result = self.compare(before, after)
        self.assertReason(result, witness.MEANINGFUL, 'schema_changed')

    def test_user_version_change_is_a_pragma_change(self):
        before = installed_db(installed_row('a'), user_version=0)
        after = installed_db(installed_row('a'), user_version=7)
        result = self.compare(before, after)
        self.assertReason(result, witness.MEANINGFUL, 'pragma_changed')
        self.assertEqual(result['counts']['pragma_changes'], 1)
        self.assertEqual(result['counts']['row_changes'], 0)

    # Refusals ---------------------------------------------------------------

    def test_inputs_must_be_bytes(self):
        valid = installed_db(installed_row('a'))
        for value in ('text', bytearray(valid), memoryview(valid), None):
            with self.subTest(type=type(value).__name__):
                self.assertInconclusive(self.compare(valid, value), 'input_not_bytes')

    def test_non_sqlite_and_short_inputs_are_inconclusive(self):
        valid = installed_db(installed_row('a'))
        for value in (b'', b'x' * 200, b'SQLite format 3\x00' + b'\x00' * 40):
            with self.subTest(length=len(value)):
                self.assertInconclusive(self.compare(valid, value), 'not_sqlite')

    def test_truncated_database_is_an_incomplete_read(self):
        valid = installed_db(installed_row('a'))
        self.assertInconclusive(self.compare(valid, valid[:-1]), 'malformed_database')

    def test_wal_header_is_refused_on_either_side(self):
        valid = installed_db(installed_row('a'))
        wal = bytearray(valid)
        wal[18] = 2
        wal[19] = 2
        self.assertInconclusive(self.compare(bytes(wal), valid), 'wal_mode_uncertain')
        self.assertInconclusive(self.compare(valid, bytes(wal)), 'wal_mode_uncertain')

    def test_real_wal_mode_file_is_refused(self):
        with tempfile.TemporaryDirectory(prefix='bm-addons33-test-') as directory:
            path = os.path.join(directory, 'wal.db')
            connection = sqlite3.connect(path)
            try:
                connection.execute('PRAGMA journal_mode = WAL')
                connection.execute(INSTALLED_SQL)
                connection.execute(installed_row('a'))
                connection.commit()
            finally:
                connection.close()
            with open(path, 'rb') as stream:
                wal = stream.read()
        self.assertEqual((wal[18], wal[19]), (2, 2))
        valid = installed_db(installed_row('a'))
        self.assertInconclusive(self.compare(wal, valid), 'wal_mode_uncertain')

    def test_unsupported_header_structures_are_refused(self):
        valid = installed_db(installed_row('a'))
        encoding = bytearray(valid)
        encoding[56:60] = (2).to_bytes(4, 'big')
        page = bytearray(valid)
        page[16:18] = (3).to_bytes(2, 'big')
        unknown = bytearray(valid)
        unknown[18] = 0
        unknown[19] = 0
        cases = {
            'unsupported_encoding': bytes(encoding),
            'unsupported_page_size': bytes(page),
            'malformed_database': bytes(unknown),
        }
        for reason, value in cases.items():
            with self.subTest(reason=reason):
                self.assertInconclusive(self.compare(valid, value), reason)

    def test_integrity_failure_is_inconclusive_and_never_meaningful(self):
        valid = installed_db(installed_row('a'))
        corrupt = build_corrupt_table_page()
        result = self.compare(valid, corrupt)
        self.assertEqual(result['status'], witness.INCONCLUSIVE)
        self.assertIn(result['reason'], ('integrity_failed', 'malformed_database'))
        self.assertSanitized(result)
        result = self.compare(corrupt, valid)
        self.assertEqual(result['status'], witness.INCONCLUSIVE)

    @unittest.skipUnless(HAS_FTS5, 'this SQLite build has no fts5 module')
    def test_virtual_table_is_an_unsupported_construct(self):
        valid = installed_db(installed_row('a'))
        virtual = build('CREATE VIRTUAL TABLE docs USING fts5(body)')
        self.assertInconclusive(self.compare(valid, virtual), 'virtual_table_unsupported')

    def test_budget_exhaustion_is_inconclusive(self):
        valid = installed_db(installed_row('a'))
        with mock.patch.object(witness, '_MAX_PROGRESS_STEPS', 1), \
             mock.patch.object(witness, '_PROGRESS_INTERVAL', 1):
            self.assertInconclusive(self.compare(valid, valid), 'budget_exhausted')

    # Resource caps ----------------------------------------------------------

    def test_database_size_cap(self):
        valid = installed_db(installed_row('a'))
        with mock.patch.object(witness, '_MAX_DATABASE_BYTES', 10):
            self.assertInconclusive(self.compare(valid, valid), 'input_too_large')

    def test_schema_object_cap(self):
        valid = build(PLAIN_SQL, 'CREATE TABLE other (x)')
        with mock.patch.object(witness, '_MAX_SCHEMA_OBJECTS', 1):
            self.assertInconclusive(self.compare(valid, valid), 'schema_object_cap')

    def test_per_table_row_cap(self):
        rows = [f"INSERT INTO plain VALUES ('r{n}', {n})" for n in range(3)]
        valid = build(PLAIN_SQL, *rows)
        with mock.patch.object(witness, '_MAX_ROWS_PER_TABLE', 2):
            self.assertInconclusive(self.compare(valid, valid), 'row_cap')

    def test_total_row_cap_across_tables(self):
        first = build('CREATE TABLE t1 (x)', 'INSERT INTO t1 VALUES (1)', 'INSERT INTO t1 VALUES (2)',
                      'CREATE TABLE t2 (x)', 'INSERT INTO t2 VALUES (3)', 'INSERT INTO t2 VALUES (4)')
        with mock.patch.object(witness, '_MAX_TOTAL_ROWS', 3):
            self.assertInconclusive(self.compare(first, first), 'row_cap')

    def test_value_size_cap(self):
        valid = build(PLAIN_SQL, "INSERT INTO plain VALUES ('abcdefgh', 1)")
        with mock.patch.object(witness, '_MAX_VALUE_BYTES', 4):
            self.assertInconclusive(self.compare(valid, valid), 'value_too_large')

    def test_projection_size_cap(self):
        valid = installed_db(installed_row('a'))
        with mock.patch.object(witness, '_MAX_PROJECTION_BYTES', 10):
            self.assertInconclusive(self.compare(valid, valid), 'projection_too_large')

    # Private copy, cleanup and interrupts ------------------------------------

    def test_private_copy_is_removed_after_success_and_refusal(self):
        before = private_copies()
        valid = installed_db(installed_row('a'))
        self.compare(valid, valid)
        self.compare(valid, valid[:-1])
        self.assertEqual(private_copies(), before)

    def test_private_copy_is_removed_when_projection_fails(self):
        before = private_copies()
        valid = installed_db(installed_row('a'))
        with mock.patch.object(witness, '_gather', side_effect=RuntimeError(SECRET)):
            result = self.compare(valid, valid)
        self.assertInconclusive(result, 'internal_error')
        self.assertEqual(private_copies(), before)

    def test_cleanup_failure_is_inconclusive(self):
        valid = installed_db(installed_row('a'))
        real_remove = witness._remove

        def remove_then_report_failure(directory):
            real_remove(directory)  # the private copy is still removed; only the report fails
            return False

        before = private_copies()
        with mock.patch.object(witness, '_remove', side_effect=remove_then_report_failure):
            self.assertInconclusive(self.compare(valid, valid), 'cleanup_failed')
        self.assertEqual(private_copies(), before)

    def test_connection_close_failure_is_inconclusive(self):
        valid = installed_db(installed_row('a'))
        real_close = witness._close_quietly

        def close_then_report_failure(connection):
            real_close(connection)  # the connection is really closed; only the report fails
            return False

        with mock.patch.object(witness, '_close_quietly', side_effect=close_then_report_failure):
            self.assertInconclusive(self.compare(valid, valid), 'cleanup_failed')

    def test_error_path_closes_the_connection(self):
        valid = installed_db(installed_row('a'))
        with mock.patch.object(witness, '_gather', side_effect=RuntimeError(SECRET)), \
             mock.patch.object(witness, '_close_quietly', wraps=witness._close_quietly) as close:
            result = self.compare(valid, valid)
        self.assertInconclusive(result, 'internal_error')
        self.assertTrue(close.called)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_keyboard_interrupt_and_system_exit_propagate_after_cleanup(self):
        valid = installed_db(installed_row('a'))
        for exc_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception=exc_type.__name__):
                before = private_copies()
                with mock.patch.object(witness, '_gather', side_effect=exc_type()), \
                     mock.patch.object(witness, '_close_quietly', wraps=witness._close_quietly) as close:
                    with self.assertRaises(exc_type):
                        self.compare(valid, valid)
                self.assertTrue(close.called)
                self.assertEqual(private_copies(), before)

    # Sanitization -----------------------------------------------------------

    def test_output_is_sanitized_and_carries_no_private_values(self):
        before = build(f'CREATE TABLE "secret-{SECRET}" (v TEXT)',
                       f"INSERT INTO \"secret-{SECRET}\" VALUES ('{SECRET}')")
        after = build(f'CREATE TABLE "secret-{SECRET}" (v TEXT)',
                      f"INSERT INTO \"secret-{SECRET}\" VALUES ('{SECRET}-changed')")
        result = self.compare(before, after)
        self.assertReason(result, witness.MEANINGFUL, 'rows_changed')
        self.assertSanitized(result)
        self.assertEqual(set(result), {'schema', 'scope', 'status', 'reason', 'counts'})

    def test_refusal_text_never_leaves_the_module(self):
        valid = installed_db(installed_row('a'))
        with mock.patch.object(witness, '_write_copy',
                               side_effect=OSError(f'/Users/example/{SECRET}')):
            result = self.compare(valid, valid)
        self.assertInconclusive(result, 'internal_error')
        self.assertNotIn(SECRET, json.dumps(result))

    def test_every_reason_is_drawn_from_the_fixed_vocabulary(self):
        valid = installed_db(installed_row('a'))
        cases = [
            self.compare(valid, valid), self.compare(valid, valid[:-1]), self.compare(b'', valid),
            self.compare(valid, installed_db(installed_row('b'))),
            self.compare(valid, build_corrupt_table_page()),
        ]
        for result in cases:
            with self.subTest(reason=result['reason']):
                self.assertSanitized(result)

    # Classification boundary and descriptor ownership ------------------------

    def recording_open(self):
        """Patch os.open to record every descriptor the module (or rmtree) obtains."""
        real_open = os.open
        opened = []

        def record(*args, **kwargs):
            descriptor = real_open(*args, **kwargs)
            opened.append(descriptor)
            return descriptor

        return mock.patch.object(witness.os, 'open', side_effect=record), opened

    def assertClosed(self, descriptor):
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_classification_failure_is_a_sanitized_inconclusive(self):
        valid = installed_db(installed_row('a'))
        with mock.patch.object(witness, '_difference', side_effect=MemoryError(SECRET)):
            result = self.compare(valid, valid)
        self.assertInconclusive(result, 'internal_error')
        self.assertNotIn(SECRET, json.dumps(result))

    def test_classification_interrupts_propagate(self):
        valid = installed_db(installed_row('a'))
        for exc_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception=exc_type.__name__):
                with mock.patch.object(witness, '_difference', side_effect=exc_type()):
                    with self.assertRaises(exc_type):
                        self.compare(valid, valid)

    def test_fdopen_failure_closes_the_descriptor_and_leaves_no_copy(self):
        valid = installed_db(installed_row('a'))
        before = private_copies()
        patcher, opened = self.recording_open()
        with patcher, mock.patch.object(witness.os, 'fdopen', side_effect=OSError(f'/tmp/{SECRET}')):
            result = self.compare(valid, valid)
        self.assertInconclusive(result, 'internal_error')
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertTrue(opened)
        for descriptor in opened:
            self.assertClosed(descriptor)
        self.assertEqual(private_copies(), before)

    def test_fdopen_interrupts_close_the_descriptor_and_propagate(self):
        valid = installed_db(installed_row('a'))
        for exc_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception=exc_type.__name__):
                before = private_copies()
                patcher, opened = self.recording_open()
                with patcher, mock.patch.object(witness.os, 'fdopen', side_effect=exc_type()):
                    with self.assertRaises(exc_type):
                        self.compare(valid, valid)
                self.assertTrue(opened)
                for descriptor in opened:
                    self.assertClosed(descriptor)
                self.assertEqual(private_copies(), before)

    def test_successful_stream_keeps_descriptor_ownership_and_closes_it_once(self):
        valid = installed_db(installed_row('a'))
        patcher, opened = self.recording_open()
        with patcher:
            result = self.compare(valid, valid)
        self.assertReason(result, witness.EXACT, 'logical_content_identical')
        self.assertTrue(opened)
        for descriptor in opened:
            self.assertClosed(descriptor)

    # Standalone boundary ----------------------------------------------------

    def test_module_is_standalone_and_imports_only_the_standard_library(self):
        with open(witness.__file__, encoding='utf-8') as stream:
            tree = ast.parse(stream.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        self.assertEqual(imported - ALLOWED_IMPORTS, set())
        self.assertNotIn('tools', imported)
        self.assertNotIn('resources', imported)


if __name__ == '__main__':
    unittest.main()
