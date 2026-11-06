"""Synthetic-copy-only checks; no Kodi/profile/process access."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
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

    def native_gui(self):
        # Synthetic output shapes grounded in pinned Kodi Save implementations.
        def node(tag):
            if tag in w._GUI_CHILDREN:
                return '<'+tag+'>'+''.join(node(n) for n in w._GUI_CHILDREN[tag])+'</'+tag+'>'
            return '<'+tag+'>'+SECRET+'</'+tag+'>'
        return ('<settings version="2"><setting id="network.password" default="true">'
                +SECRET+'</setting>'+''.join(node(n) for n in sorted(w._GUI_SECTIONS))+'</settings>')

    def test_native_gui_subsettings_supported_without_private_output(self):
        for side in (self.before, self.after):
            self.path(side, 2).write_text(self.native_gui())
        self.assertEqual(self.compare()['scope_result'], 'PRESERVED')

    def test_native_gui_every_leaf_change_is_detected(self):
        original = self.native_gui()
        self.path(self.before, 2).write_text(original)
        root = w.ET.fromstring(original)
        for leaf in root.iter():
            if list(leaf) or leaf.tag in w._GUI_CHILDREN: continue
            with self.subTest(tag=leaf.tag):
                previous = leaf.text; leaf.text = 'changed'
                self.path(self.after, 2).write_bytes(w.ET.tostring(root))
                self.changed(2); leaf.text = previous

    def test_native_gui_structure_order_and_multiplicity_not_erased(self):
        raw = b'<settings version="2"><resolutions><resolution><description>x</description><subtitles>2</subtitles></resolution></resolutions></settings>'
        base = w.xml_projection(raw, 2)
        for changed in (
            raw.replace(b'<subtitles>2</subtitles>', b''),
            raw.replace(b'<subtitles>2</subtitles>', b'<pixelratio>2</pixelratio>'),
            raw.replace(b'<description>x</description><subtitles>2</subtitles>', b'<subtitles>2</subtitles><description>x</description>'),
            raw.replace(b'</resolutions>', b'<resolution><description>x</description><subtitles>2</subtitles></resolution></resolutions>'),
            raw.replace(b'>x<', b'> x <')):
            self.assertNotEqual(base, w.xml_projection(changed, 2))

    def test_native_gui_indentation_and_root_record_order_are_layout(self):
        raw = self.native_gui().encode()
        root = w.ET.fromstring(raw)
        root[:] = list(reversed(list(root)))
        w.ET.indent(root, space='  ')
        formatted = w.ET.tostring(root)
        self.assertEqual(w.xml_projection(raw, 2), w.xml_projection(formatted, 2))
        self.assertEqual(w.xml_projection(raw, 2), w.xml_projection(formatted.replace(b'\n', b'\r\n'), 2))

    def test_pinned_audio_root_grammar_and_only_supported_leaf_names(self):
        valid = b'<settings version="2"><audio><mute>false</mute><fvolumelevel>0.5</fvolumelevel></audio></settings>'
        baseline = w.xml_projection(valid, 2)
        for before, after in ((b'>false<', b'>true<'), (b'>0.5<', b'>0.6<')):
            self.assertNotEqual(baseline, w.xml_projection(valid.replace(before, after), 2))
        for raw in (valid.replace(b'fvolumelevel', b'volumelevel'),
                    valid.replace(b'<audio>', b'<general><audio>').replace(b'</audio>', b'</audio></general>')):
            with self.assertRaises(w.Unverified): w.xml_projection(raw, 2)

    def test_native_gui_unknown_paths_attributes_and_mixed_content_refuse(self):
        for section in ('<unknown/>', '<audio><unknown/></audio>', '<audio attr="x"/>',
                        '<audio><mute attr="x">true</mute></audio>',
                        '<audio>meaningful<mute>true</mute></audio>',
                        '<audio><mute>true</mute>meaningful</audio>',
                        '<audio><mute><nested/></mute></audio>',
                        '<audio><mute>true</mute><mute>false</mute></audio>',
                        '<audio/><audio/>', '<resolutions><overscan/></resolutions>'):
            with self.subTest(section=section), self.assertRaises(w.Unverified):
                w.xml_projection(('<settings version="2">'+section+'</settings>').encode(), 2)

    def test_native_gui_literal_cr_refuses_in_all_leaf_values(self):
        for tag in ('description', 'mute', 'systemtotaluptime', 'videofilter'):
            parent = {'description':'resolution', 'mute':'audio',
                      'systemtotaluptime':'general', 'videofilter':'defaultgamesettings'}[tag]
            body = '<'+parent+'><'+tag+'>one\rtwo</'+tag+'></'+parent+'>'
            if parent == 'resolution': body = '<resolutions>'+body+'</resolutions>'
            raw = ('<settings version="2">'+body+'</settings>').encode()
            with self.subTest(tag=tag), self.assertRaises(w.Unverified) as caught:
                w.xml_projection(raw, 2)
            self.assertEqual(caught.exception.args, ('xml_value_normalization_uncertain',))
            escaped = raw.replace(b'\r', b'&#13;')
            self.assertNotEqual(w.xml_projection(escaped, 2), w.xml_projection(raw.replace(b'\r',b'\n'), 2))

    def test_native_gui_whitespace_only_leaf_values_are_not_indentation(self):
        base = b'<settings version="2"><defaultgamesettings><videofilter> </videofilter></defaultgamesettings></settings>'
        self.assertNotEqual(w.xml_projection(base, 2), w.xml_projection(base.replace(b'> <', b'><'), 2))
        with self.assertRaises(w.Unverified):
            w.xml_projection(base.replace(b'> <', b'>\r<'), 2)

    def test_nested_xml_node_and_depth_bounds_refuse(self):
        for raw in (b'<settings version="2">'+b'<audio/>'*w.MAX_ROWS+b'<audio/></settings>',
                    b'<settings version="2">'+b'<audio>'*w.MAX_XML_DEPTH+b'</audio>'*w.MAX_XML_DEPTH+b'</settings>'):
            with self.assertRaises(w.Unverified) as caught:
                w.xml_projection(raw, 2)
            self.assertEqual(caught.exception.args, ('input_too_large',))

    def test_unknown_subsettings_not_admitted_to_other_xml_kinds(self):
        for kind in (3,4):
            with self.subTest(kind=kind), self.assertRaises(w.Unverified):
                w.xml_projection(b'<settings><audio><mute>true</mute></audio></settings>',kind)

    def test_only_xml_ascii_whitespace_is_layout_in_all_xml_scopes(self):
        cases = ((2, '<settings version="2">{0}<setting id="s">value</setting>{0}</settings>'),
                 (3, '<settings>{0}<setting id="s" type="string">value</setting>{0}</settings>'),
                 (4, '<settings>{0}<setting id="s" value="value">{0}</setting>{0}</settings>'),
                 (2, '<settings version="2">{0}<audio>{0}<mute>false</mute>{0}</audio>{0}</settings>'))
        for kind, template in cases:
            with self.subTest(kind=kind, template=template):
                expected = w.xml_projection(template.format('').encode(), kind)
                for layout in (' ', '\t', '\n', '\r\n', ' \t\r\n '):
                    self.assertEqual(expected, w.xml_projection(template.format(layout).encode(), kind))

    def test_unicode_whitespace_in_layout_positions_refuses(self):
        positions = ((2, '<settings version="2">{0}<setting id="s">v</setting></settings>'),
                     (2, '<settings version="2"><setting id="s">v</setting>{0}</settings>'),
                     (3, '<settings>{0}<setting id="s" type="string">v</setting></settings>'),
                     (3, '<settings><setting id="s" type="string">v</setting>{0}</settings>'),
                     (4, '<settings>{0}<setting id="s" value="v"/></settings>'),
                     (4, '<settings><setting id="s" value="v"/>{0}</settings>'),
                     (4, '<settings><setting id="s" value="v">{0}</setting></settings>'),
                     (2, '<settings version="2"><audio>{0}<mute>false</mute></audio></settings>'),
                     (2, '<settings version="2"><audio><mute>false</mute>{0}</audio></settings>'),
                     (2, '<settings version="2"><audio/>{0}</settings>'),
                     (2, '<settings version="2"><defaultaudiosettings>{0}</defaultaudiosettings></settings>'))
        for char in ('\u00a0', '\u2003', '\u2007', '\u2028', '\u2029', '\u3000'):
            for spelling in (char, '&#'+str(ord(char))+';'):
                for kind, template in positions:
                    with self.subTest(kind=kind, codepoint=ord(char), template=template), self.assertRaises(w.Unverified):
                        w.xml_projection(template.format(spelling).encode(), kind)

    def test_unicode_whitespace_is_preserved_as_value_data_and_changes_detected(self):
        for char in ('\u00a0', '\u2003', '\u3000'):
            for index in (2,3,4):
                path = self.path(self.after,index); raw = path.read_bytes()
                try:
                    path.write_bytes(raw.replace(SECRET.encode(), (SECRET+char).encode()))
                    self.changed(index)
                finally:
                    path.write_bytes(raw)
            base = b'<settings version="2"><resolutions><resolution><description>x</description></resolution></resolutions></settings>'
            changed = base.replace(b'>x<', ('>x'+char+'<').encode())
            self.assertNotEqual(w.xml_projection(base,2), w.xml_projection(changed,2))
            self.assertEqual(w.xml_projection(changed,2),w.xml_projection(changed,2))

    def test_unicode_layout_is_unverified_not_false_preserved_at_compare_level(self):
        for index in (2,3,4):
            path = self.path(self.after,index); raw = path.read_bytes()
            try:
                marker = b'<settings version="2">' if index == 2 else b'<settings>'
                path.write_bytes(raw.replace(marker,marker+'\u00a0'.encode()))
                self.unverified(index)
            finally:
                path.write_bytes(raw)

    def test_lifecycle_shaped_changes_remain_authoritative_strict_differences(self):
        raw = b'<settings version="2"><general><systemtotaluptime>10</systemtotaluptime><settinglevel>1</settinglevel></general><viewstates><musicfiles><viewmode>50</viewmode></musicfiles></viewstates></settings>'
        for side in (self.before,self.after): self.path(side,2).write_bytes(raw)
        for old,new in ((b'>10<',b'>11<'),(b'>50<',b'>51<'),(b'>1<',b'>2<')):
            with self.subTest(old=old):
                self.path(self.after,2).write_bytes(raw.replace(old,new));self.changed(2)
        self.path(self.after,2).write_bytes(raw)
        self.sql(1,'UPDATE sizes SET usecount=usecount+1, lastusetime=?',('synthetic-lifecycle-time',))
        self.changed(1)

    def test_same_maintenance_shaped_delta_cannot_identify_its_writer(self):
        raw = b'<settings version="2"><general><systemtotaluptime>10</systemtotaluptime></general></settings>'
        # Deliberately identical synthetic outcomes from two hypothesized writers.
        lifecycle = raw.replace(b'>10<',b'>11<')
        overwrite = raw.replace(b'>10<',b'>11<')
        self.assertEqual(w.xml_projection(lifecycle,2),w.xml_projection(overwrite,2))
        self.assertNotEqual(w.xml_projection(raw,2),w.xml_projection(lifecycle,2))
        for side in (self.before,self.after):self.path(side,2).write_bytes(raw)
        self.path(self.after,2).write_bytes(overwrite)
        self.changed(2)  # source plausibility must never manufacture PRESERVED

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


class ReviewBlockerTests(unittest.TestCase):
    """B1/B2 reproductions over synthetic data; operational output is captured."""
    setUp = PreservationTests.setUp
    populate = PreservationTests.populate
    path = PreservationTests.path

    def safe_compare(self):
        try:
            result = w.compare(self.before, self.after)
        except Exception:
            self.fail('ordinary comparison exception escaped (details withheld)')
        self.assertTrue(SECRET not in json.dumps(result), 'private result detected (withheld)')
        return result

    def cli(self):
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = w.main(['--before', str(self.before), '--after', str(self.after), '--offline-copies'])
        except Exception:
            self.fail('ordinary CLI exception escaped (details withheld)')
        self.assertEqual(err.getvalue(), '')
        self.assertTrue(SECRET not in out.getvalue(), 'private output detected (withheld)')
        value = json.loads(out.getvalue())
        self.assertLess(len(out.getvalue()), 8192)
        return status, value

    def unknown(self, result):
        self.assertEqual(result['scope_result'], 'UNVERIFIED')
        self.assertEqual(result['complete_preservation'], 'UNVERIFIED')
        if 'files' in result:
            self.assertTrue(all(row['status'] == 'UNVERIFIED' for row in result['files']))

    def test_B1_guisettings_CRLF_value_cannot_be_preserved_as_LF(self):
        for index in (2, 3):
            with self.subTest(index=index):
                before = self.path(self.before, index); after = self.path(self.after, index)
                original = before.read_bytes()
                before.write_bytes(original.replace(SECRET.encode(), b'a\r\nb'))
                after.write_bytes(original.replace(SECRET.encode(), b'a\nb'))
                result = self.safe_compare()
                self.assertNotEqual(result['files'][index]['status'], 'PRESERVED')
                before.write_bytes(original); after.write_bytes(original)

    def test_B1_keyboard_literal_TAB_cannot_be_preserved_as_SPACE(self):
        original = self.path(self.before, 4).read_bytes()
        self.path(self.before, 4).write_bytes(original.replace(SECRET.encode(), b'a\tb'))
        self.path(self.after, 4).write_bytes(original.replace(SECRET.encode(), b'a b'))
        self.assertNotEqual(self.safe_compare()['files'][4]['status'], 'PRESERVED')

    def test_B1_literal_attribute_normalization_all_supported_XML_files(self):
        for index in (2, 3, 4):
            for whitespace in (b'\t', b'\n', b'\r', b'\r\n'):
                with self.subTest(index=index, whitespace=whitespace):
                    before = self.path(self.before, index); after = self.path(self.after, index)
                    original = before.read_bytes()
                    # IDs are values too; do not let normalized identifiers merge records.
                    before.write_bytes(original.replace(b'id="', b'id="a'+whitespace, 1))
                    after.write_bytes(original.replace(b'id="', b'id="a ', 1))
                    self.assertNotEqual(self.safe_compare()['files'][index]['status'], 'PRESERVED')
                    before.write_bytes(original); after.write_bytes(original)

    def test_B1_character_references_keep_value_distinctions(self):
        for index, left, right in ((2, b'a&#13;b', b'a&#10;b'),
                                   (3, b'a&#xD;b', b'a&#xA;b'),
                                   (4, b'a&#9;b', b'a&#32;b')):
            before = self.path(self.before, index); after = self.path(self.after, index)
            original = before.read_bytes()
            before.write_bytes(original.replace(SECRET.encode(), left))
            after.write_bytes(original.replace(SECRET.encode(), right))
            self.assertEqual(self.safe_compare()['files'][index]['status'], 'CHANGED_OR_MISSING')
            before.write_bytes(original); after.write_bytes(original)
        original = self.path(self.before, 2).read_bytes()
        self.path(self.before, 2).write_bytes(original.replace(SECRET.encode(), b'a\rb'))
        self.path(self.after, 2).write_bytes(original.replace(SECRET.encode(), b'a&#13;b'))
        self.assertNotEqual(self.safe_compare()['files'][2]['status'], 'PRESERVED')

    def test_B1_LF_TAB_indentation_and_equivalent_references_remain_supported(self):
        for index in (2, 3, 4):
            path = self.path(self.after, index)
            raw = path.read_bytes().replace(b'><', b'>\n\t<').replace(SECRET.encode(), b'a&amp;b')
            self.path(self.before, index).write_bytes(
                self.path(self.before, index).read_bytes().replace(SECRET.encode(), b'a&#38;b'))
            path.write_bytes(raw)
        self.assertEqual(self.safe_compare()['scope_result'], 'PRESERVED')
        keyboard = self.path(self.after, 4)
        keyboard.write_bytes(keyboard.read_bytes().replace(b'/>', b'>\r\n\t</setting>'))
        self.assertEqual(self.safe_compare()['scope_result'], 'PRESERVED')
        self.path(self.before, 2).write_bytes(self.path(self.before, 2).read_bytes().replace(b'a&#38;b', b'a\nb'))
        self.path(self.after, 2).write_bytes(self.path(self.after, 2).read_bytes().replace(b'a&amp;b', b'a&#10;b'))
        self.assertEqual(self.safe_compare()['scope_result'], 'PRESERVED')

    def test_B2_reused_path_validation_exceptions_are_contained(self):
        for failure in (w.bm.HelperError('argument_path_invalid', secret=SECRET),
                        w.isolation.Refusal(SECRET)):
            with self.subTest(kind=type(failure).__name__), \
                    mock.patch.object(w.bm, 'is_forbidden_path', side_effect=failure):
                self.unknown(self.safe_compare())
                status, result = self.cli(); self.assertEqual(status, 2); self.unknown(result)

    def test_B2_runtime_errors_at_reader_parser_and_database_boundaries(self):
        for name in ('read_copy', 'xml_projection', 'database_projection', 'texture_projection'):
            with self.subTest(boundary=name), mock.patch.object(w, name, side_effect=RuntimeError(SECRET)):
                self.unknown(self.safe_compare())
                status, result = self.cli(); self.assertEqual(status, 2); self.unknown(result)

    def test_B2_comparison_operator_exception_invalidates_partial_observations(self):
        class InvalidComparison:
            def __eq__(self, other):
                raise RuntimeError(SECRET)
        with mock.patch.object(w, 'xml_projection', side_effect=lambda *a: InvalidComparison()):
            self.unknown(self.safe_compare())
            status, result = self.cli(); self.assertEqual(status, 2); self.unknown(result)

    def test_B2_runtime_cleanup_and_SQLite_close_exceptions_fail_closed(self):
        cleanup = w.tempfile.TemporaryDirectory.cleanup
        def fail(instance):
            cleanup(instance)
            raise RuntimeError(SECRET)
        with mock.patch.object(w.tempfile.TemporaryDirectory, 'cleanup', fail):
            self.unknown(self.safe_compare())
            status, result = self.cli(); self.assertEqual(status, 2); self.unknown(result)
        connect = w.sqlite3.connect
        class BadClose:
            def __init__(self, conn): self.conn = conn
            def __getattr__(self, name): return getattr(self.conn, name)
            def close(self):
                self.conn.close(); raise RuntimeError(SECRET)
        with mock.patch.object(w.sqlite3, 'connect', side_effect=lambda *a, **k: BadClose(connect(*a, **k))):
            self.unknown(self.safe_compare())
            status, result = self.cli(); self.assertEqual(status, 2); self.unknown(result)

    def test_B2_CLI_execution_and_serialization_boundaries_return_JSON_exit2(self):
        for owner, name in ((w, 'Parser'), (w.Parser, 'add_argument'), (w.Parser, 'parse_args'),
                             (w, 'compare'), (w.json, 'dumps')):
            with self.subTest(boundary=name), mock.patch.object(owner, name, side_effect=RuntimeError(SECRET)):
                status, result = self.cli(); self.assertEqual(status, 2); self.unknown(result)

    def test_B2_exception_strings_are_never_used_as_reason_values(self):
        with mock.patch.object(w, 'offline_root', side_effect=w.Unverified(SECRET)):
            self.unknown(self.safe_compare())
            status, result = self.cli(); self.assertEqual(status, 2); self.unknown(result)
        class BadString(RuntimeError):
            def __str__(self): raise RuntimeError(SECRET)
        with mock.patch.object(w, 'read_copy', side_effect=BadString(SECRET)):
            self.unknown(self.safe_compare())

    def test_B2_exact_CLI_exit_codes_and_known_refusal_reasons(self):
        status, result = self.cli(); self.assertEqual(status, 0)
        self.assertEqual(result['scope_result'], 'PRESERVED')
        path = self.path(self.after, 4)
        path.write_bytes(path.read_bytes().replace(SECRET.encode(), b'genuine change'))
        status, result = self.cli(); self.assertEqual(status, 1)
        self.assertEqual(result['scope_result'], 'CHANGED_OR_MISSING')
        path.write_bytes(b'<broken')
        status, result = self.cli(); self.assertEqual(status, 2)
        self.assertEqual(result['files'][4]['reason'], 'unsupported_or_malformed')
        self.assertEqual(w.compare('relative', self.after)['files'][0]['reason'], 'unsafe_root')

    def test_B2_fatal_BaseExceptions_are_not_indiscriminately_suppressed(self):
        for failure in (SystemExit(7), GeneratorExit()):
            with mock.patch.object(w, 'read_copy', side_effect=failure), self.assertRaises(type(failure)):
                w.compare(self.before, self.after)
            with mock.patch.object(w, 'compare', side_effect=failure), self.assertRaises(type(failure)):
                w.main(['--before', str(self.before), '--after', str(self.after), '--offline-copies'])


class StdoutFailureTests(unittest.TestCase):
    """Synthetic files/streams and explicitly authorized fd-closed child checks."""
    setUp = PreservationTests.setUp
    populate = PreservationTests.populate
    path = PreservationTests.path

    def invoke(self, stream):
        error = io.StringIO()
        with mock.patch.object(sys, 'stdout', stream), contextlib.redirect_stderr(error):
            try:
                code = w.main(['--before', str(self.before), '--after', str(self.after), '--offline-copies'])
            except Exception:
                raise AssertionError('output exception escaped (details withheld)') from None
        self.assertEqual(error.getvalue(), '')
        return code

    def test_stdout_None_and_closed_stream_are_output_failures(self):
        closed = io.StringIO(); closed.close()
        for stream in (None, closed):
            with self.subTest(channel='absent' if stream is None else 'closed'):
                self.assertEqual(self.invoke(stream), 2)

    def test_end_to_end_child_fd1_closed_never_returns_success_or_negative(self):
        path = self.path(self.after, 4); original = path.read_bytes()
        variants = (original, original.replace(SECRET.encode(), b'changed'), b'<broken')
        for state, raw in zip(('preserved', 'changed', 'unverified'), variants):
            with self.subTest(comparison=state):
                path.write_bytes(raw)
                child = subprocess.run(
                    [sys.executable, '-B', str(Path(w.__file__).absolute()), '--before', str(self.before),
                     '--after', str(self.after), '--offline-copies'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                    preexec_fn=lambda: os.close(1), check=False)
                self.assertEqual(child.returncode, 2)
                self.assertEqual(child.stdout, b'')
                self.assertEqual(child.stderr, b'')

    class Stream:
        closed = False
        def __init__(self): self.data = ''; self.writes = 0; self.flushes = 0
        def write(self, text):
            self.writes += 1; self.data += text; return len(text)
        def flush(self): self.flushes += 1

    def test_write_failure_returns2_without_sensitive_stderr(self):
        class Failure(self.Stream):
            def write(self, text): raise RuntimeError(SECRET)
        self.assertEqual(self.invoke(Failure()), 2)

    def test_flush_failure_returns2_even_after_a_successful_write(self):
        class Failure(self.Stream):
            def flush(self):
                self.flushes += 1; raise RuntimeError(SECRET)
        stream = Failure()
        self.assertEqual(self.invoke(stream), 2)
        self.assertEqual(stream.flushes, 1)
        # Bytes accepted by a stream are not evidence of downstream persistence.
        self.assertTrue(SECRET not in stream.data, 'private output detected (withheld)')

    def test_advertised_closed_descriptor_is_checked_before_writing(self):
        read_fd, write_fd = os.pipe(); os.close(read_fd); os.close(write_fd)
        class ClosedDescriptor(self.Stream):
            def fileno(self): return write_fd
        stream = ClosedDescriptor()
        # Keep the closed descriptor deterministic: this injected comparison does no IO.
        with mock.patch.object(w, 'compare', return_value={
                'scope_result': 'PRESERVED', 'complete_preservation': 'UNVERIFIED',
                'qualification': 'not_qualified'}):
            self.assertEqual(self.invoke(stream), 2)
        self.assertEqual(stream.writes, 0)

    def test_short_or_unconfirmed_write_never_returns0_or1(self):
        for written in (0, None):
            class Short(self.Stream):
                def write(self, text): return written
            self.assertEqual(self.invoke(Short()), 2)

    def test_StringIO_retains_exact_exit_codes_and_valid_bounded_JSON(self):
        path = self.path(self.after, 4); original = path.read_bytes()
        for raw, expected, status in ((original, 0, 'PRESERVED'),
                                     (original.replace(SECRET.encode(), b'changed'), 1, 'CHANGED_OR_MISSING'),
                                     (b'<broken', 2, 'UNVERIFIED')):
            path.write_bytes(raw); stream = io.StringIO()
            self.assertEqual(self.invoke(stream), expected)
            text = stream.getvalue(); payload = json.loads(text)
            self.assertLess(len(text), 8192)
            self.assertEqual(payload['scope_result'], status)
            self.assertEqual(payload['complete_preservation'], 'UNVERIFIED')
            self.assertEqual(payload['qualification'], 'not_qualified')
            self.assertTrue(SECRET not in text, 'private output detected (withheld)')
            self.assertNotIn('Traceback', text)


class BufferedStdoutTests(unittest.TestCase):
    """Exercise real buffered streams through ordinary child interpreter exit."""
    setUp = PreservationTests.setUp
    populate = PreservationTests.populate
    path = PreservationTests.path

    def child(self, mode, expected, status=None, regular=False):
        # No shutdown bypass, signal change, or stream repair: the interpreter
        # finalizes normally, exposing any JSON left in a failed Python buffer.
        driver = r'''
import errno, io, os, runpy, sys
sys.path.insert(0, sys.argv[1])
module = runpy.run_path(sys.argv[2])
mode = sys.argv[3]
original = sys.stdout
if mode == 'broken_pipe':
    reader, writer = os.pipe()
    os.close(reader)
    os.dup2(writer, 1)
    os.close(writer)
elif mode == 'read_only':
    descriptor = os.open(sys.argv[4], os.O_RDONLY)
    os.dup2(descriptor, 1)
    os.close(descriptor)
elif mode == 'closed':
    os.close(1)
elif mode == 'enospc':
    class Full(io.RawIOBase):
        def writable(self): return True
        def fileno(self): return 1
        def write(self, data): raise OSError(errno.ENOSPC, 'synthetic disk full')
    sys.stdout = io.TextIOWrapper(io.BufferedWriter(Full()), encoding='utf-8')
    def full_write(fd, data): raise OSError(errno.ENOSPC, 'synthetic disk full')
    os.write = full_write
elif mode in ('partial', 'write_error'):
    def descriptor_write(fd, data):
        if mode == 'partial': return len(data) - 1
        raise OSError(errno.EIO, 'synthetic write failure')
    os.write = descriptor_write
elif mode == 'StringIO':
    sys.stdout = io.StringIO()
elif mode in ('stream_write_error', 'stream_flush_error'):
    class Capture:
        closed = False
        def __init__(self): self.flushes = 0
        def write(self, text):
            if mode == 'stream_write_error': raise OSError('synthetic capture write failure')
            return len(text)
        def flush(self):
            self.flushes += 1
            if mode == 'stream_flush_error' and self.flushes == 1:
                raise OSError('synthetic capture flush failure')
    sys.stdout = Capture()
code = module['main'](['--before', sys.argv[4], '--after', sys.argv[5], '--offline-copies'])
if mode == 'StringIO':
    text = sys.stdout.getvalue()
    sys.stdout = original
    sys.stdout.write(text)
    sys.stdout.flush()
raise SystemExit(code)
'''
        # read_only needs a regular fixture, not the directory passed to main.
        driver = driver.replace('os.open(sys.argv[4], os.O_RDONLY)',
                                'os.open(sys.argv[4] + "/userdata/guisettings.xml", os.O_RDONLY)')
        output = self.base / 'child-output.json'
        with (output.open('wb') if regular else contextlib.nullcontext(subprocess.PIPE)) as channel:
            child = subprocess.run([sys.executable, '-B', '-c', driver,
                                    str(Path(w.__file__).absolute().parent),
                                    str(Path(w.__file__).absolute()), mode,
                                    str(self.before), str(self.after)],
                                   stdout=channel, stderr=subprocess.PIPE, timeout=20, check=False)
        stdout = output.read_bytes() if regular else child.stdout
        self.assertTrue(SECRET.encode() not in stdout + child.stderr,
                        'private output detected (withheld)')
        print('STDOUT_CHILD ' + json.dumps({'mode': mode, 'expected': expected,
              'exit': child.returncode, 'stdout': stdout.decode('utf-8'),
              'stderr': child.stderr.decode('utf-8')}), file=sys.stderr)
        self.assertEqual(child.returncode, expected)
        self.assertEqual(child.stderr, b'')
        if status is None:
            self.assertEqual(stdout, b'')
        else:
            self.assertLess(len(stdout), 8192)
            result = json.loads(stdout)
            self.assertEqual(result['scope_result'], status)
            self.assertEqual(result['complete_preservation'], 'UNVERIFIED')
            self.assertEqual(result['qualification'], 'not_qualified')

    def test_real_child_broken_pipe_has_no_shutdown_retry(self):
        self.child('broken_pipe', 2)

    def test_real_child_read_only_fd1_has_no_shutdown_retry(self):
        self.child('read_only', 2)

    def test_real_child_buffered_ENOSPC_has_no_shutdown_retry(self):
        self.child('enospc', 2)

    def test_real_child_previously_closed_fd1(self):
        self.child('closed', 2)

    def test_real_child_partial_or_failed_descriptor_write(self):
        for mode in ('partial', 'write_error'):
            with self.subTest(mode=mode): self.child(mode, 2)

    def test_child_descriptorless_write_and_flush_failure(self):
        for mode in ('stream_write_error', 'stream_flush_error'):
            with self.subTest(mode=mode): self.child(mode, 2)

    def test_child_regular_file_has_exact_JSON_and_exit_codes(self):
        self.success_cases('regular', regular=True)

    def test_child_StringIO_has_exact_JSON_and_exit_codes(self):
        self.success_cases('StringIO')

    def success_cases(self, mode, regular=False):
        path = self.path(self.after, 4); original = path.read_bytes()
        for raw, code, status in ((original, 0, 'PRESERVED'),
                                  (original.replace(SECRET.encode(), b'changed'), 1, 'CHANGED_OR_MISSING'),
                                  (b'<broken', 2, 'UNVERIFIED')):
            with self.subTest(status=status):
                path.write_bytes(raw)
                self.child(mode, code, status, regular)


class SQLiteLifetimeTests(unittest.TestCase):
    """Synthetic copies stay linked through close; only owners remove them."""
    setUp = PreservationTests.setUp
    populate = PreservationTests.populate
    path = PreservationTests.path
    fingerprint = PreservationTests.fingerprint

    def audited_compare(self, fault=None, affected=None):
        connect = sqlite3.connect; unlink = Path.unlink
        cleanup = tempfile.TemporaryDirectory.cleanup
        originals = {i: self.path(self.before, i).read_bytes() for i in (0, 1)}
        before = self.fingerprint(); copies = {}; events = []
        case = self

        class Connection:
            def __init__(self, connection, path, kind):
                self.connection = connection; self.path = path; self.kind = kind; self.closed = False
            def __getattr__(self, name): return getattr(self.connection, name)
            def execute(self, sql, *args):
                case.assertTrue(self.path.is_file(), 'copy must be linked during every query')
                case.assertFalse(self.closed)
                case.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ['copy.db'])
                events.append(('query', self.path))
                if fault == 'query' and self.kind == affected: raise sqlite3.OperationalError(SECRET)
                return self.connection.execute(sql, *args)
            def close(self):
                case.assertTrue(self.path.is_file(), 'copy must remain linked through close')
                self.connection.close(); self.closed = True; events.append(('close', self.path))
                if fault == 'close' and self.kind == affected: raise sqlite3.OperationalError(SECRET)

        def private_connection(database_uri, **kwargs):
            self.assertTrue(kwargs['uri']); self.assertTrue(database_uri.endswith('?mode=ro&immutable=1'))
            p = Path(w.urllib.parse.unquote(database_uri[5:].split('?')[0]))
            self.assertNotIn(str(self.before), str(p)); self.assertNotIn(str(self.after), str(p))
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(p.parent.stat().st_mode), 0o700)
            raw = p.read_bytes(); kind = next(i for i, data in originals.items() if data == raw)
            connection = connect(database_uri, **kwargs)
            # A write attempt must fail even while the private pathname exists.
            with self.assertRaises(sqlite3.OperationalError): connection.execute('CREATE TABLE forbidden(x)')
            wrapper = Connection(connection, p, kind); copies[p] = wrapper
            return wrapper

        def remove(p, *args, **kwargs):
            if p in copies:
                self.assertTrue(copies[p].closed, 'owner must close before unlink')
                events.append(('unlink', p))
                if fault == 'unlink' and copies[p].kind == affected: raise OSError(SECRET)
            return unlink(p, *args, **kwargs)

        def finalize(instance):
            cleanup(instance); events.append(('cleanup', Path(instance.name)))
            if fault == 'cleanup' and any(p.parent == Path(instance.name) and c.kind == affected
                                          for p, c in copies.items()): raise OSError(SECRET)

        with mock.patch.object(w.sqlite3, 'connect', side_effect=private_connection), \
             mock.patch.object(Path, 'unlink', remove), \
             mock.patch.object(w.tempfile.TemporaryDirectory, 'cleanup', finalize):
            result = w.compare(self.before, self.after)
        self.assertEqual(self.fingerprint(), before)
        self.assertTrue(copies)
        for p, connection in copies.items():
            self.assertTrue(connection.closed)
            self.assertFalse(p.exists()); self.assertFalse(p.parent.exists())
            self.assertLess(events.index(('close', p)), events.index(('unlink', p)))
            self.assertLess(events.index(('unlink', p)), events.index(('cleanup', p.parent)))
        encoded = json.dumps(result)
        self.assertTrue(SECRET not in encoded, 'private output detected (withheld)')
        self.assertNotIn('OperationalError', encoded); self.assertNotIn(str(self.base), encoded)
        self.assertEqual(result['complete_preservation'], 'UNVERIFIED')
        self.assertEqual(result['qualification'], 'not_qualified')
        return result, copies

    def test_direct_proxy_discovery_then_both_linked_projections(self):
        import _scproxy
        _scproxy._get_proxies()  # Discard settings; never inspect or log proxy values.
        result, copies = self.audited_compare()
        self.assertEqual(result['scope_result'], 'PRESERVED')
        self.assertEqual({c.kind for c in copies.values()}, {0, 1}); self.assertEqual(len(copies), 4)

    def test_linked_queries_close_unlink_cleanup_and_immutable_permissions(self):
        result, copies = self.audited_compare()
        self.assertEqual(result['scope_result'], 'PRESERVED'); self.assertEqual(len(copies), 4)

    def test_query_failure_cleans_both_projection_types(self):
        for kind in (0, 1):
            with self.subTest(kind=kind):
                result, _ = self.audited_compare('query', kind)
                self.assertEqual(result['scope_result'], 'UNVERIFIED')
                self.assertEqual(result['files'][kind]['status'], 'UNVERIFIED')

    def test_close_failure_cleans_both_and_never_publishes_success(self):
        for kind in (0, 1):
            with self.subTest(kind=kind):
                result, _ = self.audited_compare('close', kind)
                self.assertEqual(result['scope_result'], 'UNVERIFIED')
                self.assertEqual(result['files'][kind]['status'], 'UNVERIFIED')

    def test_unlink_failure_cleans_both_and_never_publishes_success(self):
        for kind in (0, 1):
            with self.subTest(kind=kind):
                result, _ = self.audited_compare('unlink', kind)
                self.assertEqual(result['scope_result'], 'UNVERIFIED')
                self.assertEqual(result['files'][kind]['status'], 'UNVERIFIED')

    def test_directory_cleanup_failure_cannot_publish_either_projection(self):
        for kind in (0, 1):
            with self.subTest(kind=kind):
                result, _ = self.audited_compare('cleanup', kind)
                self.assertEqual(result['scope_result'], 'UNVERIFIED')
                self.assertEqual(result['files'][kind]['status'], 'UNVERIFIED')
