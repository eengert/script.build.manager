"""Synthetic-copy-only checks; no Kodi/profile/process access."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from tools import bm_public_preservation_witness as w
from tests.test_bm_test_app import FilesystemTripwire

SECRET = 'fabricated-credential-low-entropy-1234'


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.tripwire = FilesystemTripwire(); self.tripwire.start()
        self.addCleanup(self.tripwire.stop)
        self.addCleanup(self.assertEqual, self.tripwire.touched, [])
        self.temp = tempfile.TemporaryDirectory(prefix='bm-semantic-test-', dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.before = self.base / 'before'; self.after = self.base / 'after'
        self.populate(self.before)
        shutil.copytree(self.before, self.after)

    def path(self, side, i):
        return side / w.FILES[i]

    def populate(self, root):
        for name in w.FILES:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path(root, 0)) as db:
            db.execute('CREATE TABLE installed (id INTEGER PRIMARY KEY, addonID TEXT UNIQUE, enabled BOOLEAN, '
                       'installDate TEXT, lastUpdated TEXT, lastUsed TEXT, origin TEXT, disabledReason INTEGER)')
            db.execute('INSERT INTO installed VALUES (1, ?, 1, ?, ?, ?, ?, 0)',
                       ('script.synthetic', SECRET, SECRET, SECRET, SECRET))
        with sqlite3.connect(self.path(root, 1)) as db:
            for statement in w.TEXTURE_SQL:
                db.execute(statement)
            db.execute('INSERT INTO version VALUES (13,0)')
            db.execute('INSERT INTO texture VALUES (1,?,?,?,?)', (SECRET, SECRET, SECRET, SECRET))
            db.execute('INSERT INTO sizes VALUES (1,1,1920,1080,4,?)', (SECRET,))
            db.execute('INSERT INTO path VALUES (1,?,?,?)', (SECRET, SECRET, SECRET))
        self.path(root, 2).write_text('<settings version="2"><setting id="general.addonupdates">0</setting>'
                                    '<setting id="network.password" default="false">'+SECRET+'</setting></settings>')
        self.path(root, 3).write_text('<settings><setting id="flag" type="bool">true</setting>'
                                    '<setting id="private.label" type="string">'+SECRET+'</setting></settings>')
        self.path(root, 4).write_text('<settings><setting id="layout" value="'+SECRET+'"/></settings>')

    def compare(self):
        result = w.compare(self.before, self.after)
        self.assertEqual(result['complete_preservation'], 'UNVERIFIED')
        self.assertEqual(result['qualification'], 'not_qualified')
        encoded = json.dumps(result)
        self.assertNotIn(SECRET, encoded)
        self.assertNotIn(hashlib.sha256(SECRET.encode()).hexdigest(), encoded)
        self.assertNotIn('network.password', encoded)
        self.assertNotIn(str(self.base), encoded)
        return result

    def changed(self, index):
        result = self.compare()
        self.assertEqual(result['files'][index]['status'], 'CHANGED_OR_MISSING')
        self.assertEqual(result['scope_result'], 'CHANGED_OR_MISSING')

    def unverified(self, index=None):
        result = self.compare()
        self.assertEqual(result['scope_result'], 'UNVERIFIED')
        if index is not None:
            self.assertEqual(result['files'][index]['status'], 'UNVERIFIED')
        return result

    def sql(self, index, query, params=()):
        with sqlite3.connect(self.path(self.after, index)) as db:
            db.execute(query, params)

    def fingerprint(self):
        return {str(p.relative_to(side)) + str(n):
                (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
                for n, side in enumerate((self.before, self.after)) for p in side.rglob('*') if p.is_file()}

    def test_equal_and_no_persisted_value_hashes(self):
        result = self.compare()
        self.assertEqual(result['scope_result'], 'PRESERVED')
        self.assertTrue(all(r['status'] == 'PRESERVED' for r in result['files']))
        self.assertIn('UNVERIFIED', result['files'][0]['scope'])
        self.assertEqual(result, self.compare())  # no key/value digest leaks between invocations

    def test_equivalent_xml_layout_and_attribute_record_order(self):
        self.path(self.after, 2).write_text('<settings version="2">\n <setting default="false" id="network.password">'
                                          +SECRET+'</setting>\n<setting id="general.addonupdates">0</setting>\n</settings>')
        self.path(self.after, 3).write_text('<settings>\n<setting type="string" id="private.label">'+SECRET+
                                          '</setting><setting type="bool" id="flag">true</setting></settings>')
        self.path(self.after, 4).write_text('<settings>\n <setting value="'+SECRET+'" id="layout" />\n</settings>')
        self.assertEqual(self.compare()['scope_result'], 'PRESERVED')

    def test_sqlite_physical_layout_is_not_record_identity(self):
        with sqlite3.connect(self.path(self.after, 1)) as db:
            db.execute('PRAGMA page_size=8192'); db.execute('VACUUM')
        self.assertNotEqual(self.path(self.before, 1).read_bytes(), self.path(self.after, 1).read_bytes())
        self.assertEqual(self.compare()['scope_result'], 'PRESERVED')

    def test_setting_overwrite_is_detected_for_each_xml(self):
        for index in (2, 3, 4):
            with self.subTest(index=index):
                path = self.path(self.after, index); original = path.read_bytes()
                path.write_bytes(original.replace(SECRET.encode(), b'overwritten'))
                self.changed(index); path.write_bytes(original)

    def test_deleted_setting_detected_for_each_xml(self):
        for index in (2, 3, 4):
            with self.subTest(index=index):
                path = self.path(self.after, index); original = path.read_bytes()
                root = w.ET.fromstring(original); root.remove(root[-1])
                path.write_bytes(w.ET.tostring(root)); self.changed(index); path.write_bytes(original)

    def test_bool_default_and_string_whitespace_changes_detected(self):
        for index, old, new in ((3, b'>true<', b'>false<'), (2, b'default="false"', b'default="true"'),
                                (3, SECRET.encode(), (' '+SECRET+' ').encode())):
            path = self.path(self.after, index); original = path.read_bytes()
            path.write_bytes(original.replace(old, new)); self.changed(index); path.write_bytes(original)

    def test_root_version_metadata_is_compared_not_discarded(self):
        path = self.path(self.after, 3)
        path.write_bytes(path.read_bytes().replace(b'<settings>', b'<settings version="2">'))
        self.changed(3)

    def test_missing_file_detected_after_valid_counterpart(self):
        for index in range(5):
            path = self.path(self.after, index); original = path.read_bytes()
            path.unlink(); self.changed(index); path.write_bytes(original)
        self.path(self.before, 4).unlink(); self.path(self.after, 4).unlink()
        self.unverified(4)

    def test_addons_accepted_projection_is_not_broadened(self):
        self.sql(0, 'UPDATE installed SET lastUsed=?, origin=?', ('changed', 'changed'))
        self.sql(0, 'CREATE TABLE opaque (secret TEXT)')
        self.sql(0, 'INSERT INTO opaque VALUES (?)', (SECRET,))
        self.assertEqual(self.compare()['files'][0]['status'], 'PRESERVED')
        self.assertEqual(self.compare()['complete_preservation'], 'UNVERIFIED')
        for statement in ('UPDATE installed SET enabled=0', 'DELETE FROM installed'):
            path = self.path(self.after, 0); raw = path.read_bytes()
            self.sql(0, statement); self.changed(0); path.write_bytes(raw)

    def test_texture_records_and_maintenance_fields_never_assumed_harmless(self):
        cases = ('UPDATE texture SET imagehash="changed"', 'DELETE FROM texture',
                 'UPDATE sizes SET width=1', 'UPDATE sizes SET usecount=usecount+1',
                 'DELETE FROM path', 'UPDATE version SET iCompressCount=1')
        for statement in cases:
            path = self.path(self.after, 1); raw = path.read_bytes()
            self.sql(1, statement); self.changed(1); path.write_bytes(raw)

    def test_duplicate_texture_rows_are_compared_as_multiset(self):
        self.sql(1, 'INSERT INTO sizes SELECT * FROM sizes'); self.changed(1)

    def test_unsupported_database_schema_and_record_types(self):
        for statement in ('CREATE TABLE other (secret TEXT)', 'DROP INDEX idxTexture',
                          'UPDATE version SET idVersion=99', 'UPDATE sizes SET width="not-an-integer"'):
            path = self.path(self.after, 1); raw = path.read_bytes()
            self.sql(1, statement); self.unverified(1); path.write_bytes(raw)
        self.sql(0, 'ALTER TABLE installed ADD COLUMN unexpected TEXT'); self.unverified(0)

    def test_sql_normalization_preserves_token_boundaries(self):
        self.assertNotEqual(w.sql_normalize('CREATE TABLE x (id INTEGER PRIMARY KEY)'),
                            w.sql_normalize('CREATE TABLE x (id INTEGERPRIMARYKEY)'))
        for sql in ('CREATE TABLE x(id text CHECK(id="secret"))', 'CREATE /*comment*/ TABLE x(id int)'):
            with self.assertRaises(w.Unverified):
                w.sql_normalize(sql)

    def test_any_sqlite_sidecar_including_empty_or_symlink_refuses(self):
        for index in (0, 1):
            for suffix in ('-wal', '-shm', '-journal'):
                sidecar = Path(str(self.path(self.after, index)) + suffix)
                sidecar.write_bytes(b''); self.unverified(index); sidecar.unlink()
                sidecar.symlink_to(self.base / 'absent'); self.unverified(index); sidecar.unlink()

    def test_wal_header_without_sidecars_is_unverified(self):
        for index in (0, 1):
            path = self.path(self.after, index); raw = path.read_bytes()
            modified = bytearray(raw); modified[18:20] = b'\x02\x02'; path.write_bytes(modified)
            self.unverified(index); path.write_bytes(raw)

    def test_committed_wal_records_are_not_silently_omitted(self):
        path = self.path(self.after, 1)
        db = sqlite3.connect(path)
        try:
            db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('DELETE FROM texture'); db.commit()
            self.assertTrue(Path(str(path)+'-wal').exists())
            self.unverified(1)
        finally:
            db.close()

    def test_malformed_xml_entities_unknown_shapes_and_types(self):
        for raw in (b'<settings', b'<!DOCTYPE settings [<!ENTITY x "secret">]><settings/>',
                    b'<settings><unknown/></settings>', b'<settings><setting id="a" type="number">1</setting></settings>',
                    b'<settings><setting id="a" type="bool">maybe</setting></settings>',
                    b'<settings><setting id="a" type="bool">true</setting><setting id="a" type="bool">false</setting></settings>',
                    b'<settings><setting id="a" type="string"><nested/></setting></settings>',
                    b'<settings><!--secret--></settings>'):
            self.path(self.after, 3).write_bytes(raw); self.unverified(3)
        self.path(self.after, 2).write_text('<settings version="2"><audio><value>1</value></audio></settings>')
        self.unverified(2)

    def test_malformed_database_unverified(self):
        self.path(self.after, 1).write_bytes(b'not sqlite '+SECRET.encode()); self.unverified(1)

    def test_symlink_leaf_ancestor_hardlink_and_special_node_rejection(self):
        path = self.path(self.after, 4); raw = path.read_bytes()
        path.unlink(); path.symlink_to(self.path(self.before, 4)); self.unverified(); path.unlink()
        os.link(self.path(self.before, 4), path); self.unverified(); path.unlink()
        os.mkfifo(path); self.unverified(); path.unlink(); path.write_bytes(raw)
        parent = path.parent; moved = parent.with_name('saved'); parent.rename(moved)
        parent.symlink_to(moved); self.unverified(); parent.unlink(); moved.rename(parent)
        with self.assertRaises(w.Unverified):
            w.offline_root('/Applications/Kodi Build Manager Test.app')

    def test_oversized_input_is_unverified(self):
        self.path(self.after, 2).write_bytes(b'x'*(w.MAX_XML+1)); self.unverified()
        with mock.patch.object(w, 'MAX_DB', 100):
            self.unverified()

    def test_unsafe_roots_are_rejected_before_any_filesystem_read(self):
        for root in ('relative', '/private/tmp/../secret', '/Applications/Kodi.app',
                     '/Users/eengert/Library/Application Support/Kodi', '/private/tmp/Fake.app/profile'):
            with mock.patch.object(w.isolation, 'directory', side_effect=AssertionError('must not read')):
                result = w.compare(root, self.after)
                self.assertEqual(result['scope_result'], 'UNVERIFIED')
        self.assertEqual(w.compare(self.before, self.before)['scope_result'], 'UNVERIFIED')

    def test_input_replacement_during_final_validation_is_unverified(self):
        original = w.read_copy; calls = [0]
        def moving(*args):
            calls[0] += 1
            if calls[0] == 11:
                self.path(self.before, 4).write_text('<settings/>')
            return original(*args)
        with mock.patch.object(w, 'read_copy', side_effect=moving):
            self.unverified()

    def test_no_input_writes_and_sqlite_only_on_private_immutable_copy(self):
        before = self.fingerprint(); connect = w.sqlite3.connect; uris = []
        def readonly(database, **kwargs):
            uris.append(database)
            self.assertTrue(kwargs['uri']); self.assertIn('mode=ro&immutable=1', database)
            self.assertNotIn(str(self.before), database); self.assertNotIn(str(self.after), database)
            return connect(database, **kwargs)
        with mock.patch.object(w.sqlite3, 'connect', side_effect=readonly):
            result = self.compare()
            self.assertEqual(result['scope_result'], 'PRESERVED', result)
        self.assertEqual(self.fingerprint(), before); self.assertEqual(len(uris), 4)
        self.assertEqual(sorted(self.base.iterdir()), [self.after, self.before])

    def test_private_copy_cleanup_failure_cannot_report_preserved(self):
        cleanup = w.tempfile.TemporaryDirectory.cleanup
        def fail(instance):
            cleanup(instance)
            raise OSError(SECRET)
        with mock.patch.object(w.tempfile.TemporaryDirectory, 'cleanup', fail):
            self.unverified(0)

    def test_sqlite_close_failure_cannot_report_preserved(self):
        connect = w.sqlite3.connect
        class FailingClose:
            def __init__(self, value): self.value = value
            def __getattr__(self, name): return getattr(self.value, name)
            def close(self):
                self.value.close(); raise sqlite3.Error(SECRET)
        with mock.patch.object(w.sqlite3, 'connect', side_effect=lambda *a, **k: FailingClose(connect(*a, **k))):
            self.unverified(0)

    def test_cli_emits_only_sanitized_result(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = w.main(['--before', str(self.before), '--after', str(self.after), '--offline-copies'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['complete_preservation'], 'UNVERIFIED')
        self.assertNotIn(SECRET, output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = w.main(['--before', SECRET])
        self.assertEqual(code, 2); self.assertNotIn(SECRET, output.getvalue())
