"""Synthetic, in-memory checks for the D-032 practical preservation comparator.

Projections are built in memory. guisettings, Estuary and keyboard come from the
existing witness producer (xml_projection) applied to synthetic XML bytes.
Textures13 and Addons33 follow the shapes that texture_projection and
database_projection return. No file, profile, process, network or native
access happens here, and nothing is persisted.
"""
import contextlib
import copy
import dataclasses
import io
import json
import traceback
import unittest
from unittest import mock

from tools import bm_practical_preservation_comparator as pc
from tools import bm_public_preservation_witness as w

# Distinctive synthetic tokens. They sit in base content, so every result and
# every rejection path is checked for leakage.
SECRETS = (
    'SECRET-ADDON-4b1d', 'SECRET-URL-8e0f', 'SECRET-CACHED-2c9a', 'SECRET-HASH-6d3b',
    'SECRET-CHECK-7f44', 'SECRET-USE-0a8c', 'SECRET-PATH-3e5f', 'SECRET-SETTING-ID-5a7e',
    'SECRET-SETTING-VALUE-91c2', 'SECRET-ESTUARY-9b6d', 'SECRET-UPTIME-BAD-7c3a',
)

ADDONS_BASE = [('plugin.SECRET-ADDON-4b1d', True), ('script.beta', False)]
TEXTURE_BASE = [
    (1, 'image://SECRET-URL-8e0f', 'cache://SECRET-CACHED-2c9a', 'SECRET-HASH-6d3b', 'SECRET-CHECK-7f44'),
    (2, 'image://evicted-url', 'cache://evicted-cached', 'evicted-hash', None),
]
SIZES_BASE = [
    (1, 64, 64, 64, 3, 'SECRET-USE-0a8c'),
    (1, 128, 128, 128, 1, None),
    (2, 32, 32, 32, 7, 'time-b'),
]
PATH_BASE = [(1, 'library://SECRET-PATH-3e5f', 'video', 'texture-ref')]
ESTUARY_XML = (
    b'<settings version="2">'
    b'<setting id="skin.estuary.SECRET-SETTING-ID-5a7e" type="string">SECRET-ESTUARY-9b6d</setting>'
    b'<setting id="skin.estuary.flag" type="bool">true</setting>'
    b'</settings>'
)
KEYBOARD_XML = b'<settings><setting id="keyboard.layout" value="en-us"/></settings>'
EXACT = pc.FileSummary(pc.EXACT)


def enc(row):
    """Canonical row bytes, as texture_projection encodes each sqlite row."""
    return json.dumps(list(row), ensure_ascii=True).encode()


def textures(texture=TEXTURE_BASE, sizes=SIZES_BASE, path=PATH_BASE, version=(13, 0)):
    return [
        ('version', [enc(version)]),
        ('texture', sorted(enc(row) for row in texture)),
        ('sizes', sorted(enc(row) for row in sizes)),
        ('path', sorted(enc(row) for row in path)),
    ]


def gui_xml(uptime='123', level='standard', rss='false', mute='false', fvolume='0.5'):
    return (
        '<settings version="2">'
        '<setting id="services.SECRET-SETTING-ID-5a7e" default="true">SECRET-SETTING-VALUE-91c2</setting>'
        f'<setting id="lookandfeel.enablerssfeeds" default="false">{rss}</setting>'
        '<general>'
        f'<systemtotaluptime>{uptime}</systemtotaluptime>'
        f'<settinglevel>{level}</settinglevel>'
        '<eventlog><level>warning</level><showhigherlevels>false</showhigherlevels></eventlog>'
        '</general>'
        f'<audio><mute>{mute}</mute><fvolumelevel>{fvolume}</fvolumelevel></audio>'
        '</settings>'
    ).encode()


def gui(**kwargs):
    return w.xml_projection(gui_xml(**kwargs), 2)


def baseline(**overrides):
    projections = {
        'addons33': list(ADDONS_BASE),
        'textures13': textures(),
        'guisettings': gui(),
        'estuary': w.xml_projection(ESTUARY_XML, 3),
        'keyboard': w.xml_projection(KEYBOARD_XML, 4),
    }
    projections.update(overrides)
    return projections


def textures13_only(tables):
    """Baseline projections with only Textures13 replaced."""
    return baseline(textures13=tables)


def edit_general(projection, change):
    """Return the guisettings projection with general's children replaced by change(children)."""
    attrs, rows, sections = projection
    edited = []
    for name, node in sections:
        if name == 'general':
            tag, text, children = node
            node = (tag, text, tuple(change(children)))
        edited.append((name, node))
    return (attrs, rows, tuple(edited))


def set_uptime(text):
    return lambda children: tuple(
        (child[0], text, child[2]) if child[0] == 'systemtotaluptime' else child
        for child in children)


def meaningful(count):
    return pc.FileSummary(pc.MEANINGFUL, (), count)


def maintenance(*pairs):
    return pc.FileSummary(pc.MAINTENANCE_ONLY, tuple(pairs))


class ComparatorTestCase(unittest.TestCase):
    def compare(self, before, after):
        result = pc.compare_protected_files(before, after)
        self.assertEqual(tuple(result), pc.PROTECTED_KEYS)
        for summary in result.values():
            self.assert_sanitized(summary)
        return result

    def assert_sanitized(self, summary):
        self.assertIn(summary.verdict, (pc.EXACT, pc.MAINTENANCE_ONLY, pc.MEANINGFUL))
        self.assertEqual([field.name for field in dataclasses.fields(summary)],
                         ['verdict', 'maintenance', 'meaningful_count'])
        for name, count in summary.maintenance:
            self.assertIn(name, pc.ALLOWED_CLASSES)
            self.assertIs(type(count), int)
            self.assertGreater(count, 0)
        self.assertIs(type(summary.meaningful_count), int)
        if summary.verdict == pc.MEANINGFUL:
            self.assertGreater(summary.meaningful_count, 0)
            self.assertEqual(summary.maintenance, ())
        elif summary.verdict == pc.MAINTENANCE_ONLY:
            self.assertTrue(summary.maintenance)
            self.assertEqual(summary.meaningful_count, 0)
        else:
            self.assertEqual(summary, EXACT)

    def assert_only(self, result, key, expected):
        for name in pc.PROTECTED_KEYS:
            with self.subTest(file=name):
                self.assertEqual(result[name], expected if name == key else EXACT)


class PositiveControlTests(ComparatorTestCase):
    def test_identical_projections_are_exact_for_every_file(self):
        result = self.compare(baseline(), baseline())
        for name in pc.PROTECTED_KEYS:
            self.assertEqual(result[name], EXACT)

    def test_uptime_only_change_is_m1_maintenance_for_guisettings_only(self):
        result = self.compare(baseline(), baseline(guisettings=gui(uptime='456')))
        self.assert_only(result, 'guisettings', maintenance(('M1_UPTIME', 1)))

    def test_canonical_uptime_zero_and_eighteen_digits_are_valid(self):
        for after in ('0', '999999999999999999'):
            with self.subTest(after=after):
                result = self.compare(baseline(), baseline(guisettings=gui(uptime=after)))
                self.assert_only(result, 'guisettings', maintenance(('M1_UPTIME', 1)))

    def test_each_permitted_m2_metadata_change_maps_to_its_class(self):
        cases = {
            'sizes.usecount': (
                textures(sizes=[(1, 64, 64, 64, 4, 'SECRET-USE-0a8c'),
                                (1, 128, 128, 128, 2, None), SIZES_BASE[2]]),
                maintenance(('M2_SIZES_USECOUNT', 2))),
            'sizes.lastusetime': (
                textures(sizes=[SIZES_BASE[0], SIZES_BASE[1], (2, 32, 32, 32, 7, 'time-c')]),
                maintenance(('M2_SIZES_LASTUSETIME', 1))),
            'texture.lasthashcheck': (
                textures(texture=[TEXTURE_BASE[0],
                                  (2, 'image://evicted-url', 'cache://evicted-cached', 'evicted-hash', 'checked-now')]),
                maintenance(('M2_TEXTURE_LASTHASHCHECK', 1))),
        }
        for label, (after, expected) in cases.items():
            with self.subTest(change=label):
                result = self.compare(baseline(), baseline(textures13=after))
                self.assert_only(result, 'textures13', expected)

    def test_texture_cache_creation_and_eviction_keep_retained_identities(self):
        after = textures(
            texture=[TEXTURE_BASE[0], (3, 'image://created', 'cache://created', 'created-hash', None)],
            sizes=[SIZES_BASE[0], SIZES_BASE[1], (3, 16, 16, 16, 1, 'time-c'), (3, 48, 48, 48, 1, None)])
        result = self.compare(baseline(), baseline(textures13=after))
        self.assert_only(result, 'textures13', maintenance(
            ('M2_CACHE_ROW_CREATE', 1), ('M2_CACHE_ROW_EVICT', 1),
            ('M2_CACHE_SIZES_CREATE', 2), ('M2_CACHE_SIZES_EVICT', 1)))

    def test_permitted_combination_of_maintenance_changes_is_reported_per_file_and_class(self):
        after = textures(
            texture=[(1, TEXTURE_BASE[0][1], TEXTURE_BASE[0][2], TEXTURE_BASE[0][3], 'checked-now'),
                     (3, 'image://created', 'cache://created', 'created-hash', None)],
            sizes=[(1, 64, 64, 64, 4, 'SECRET-USE-0a8c'), (1, 128, 128, 128, 1, 'time-x'),
                   (3, 16, 16, 16, 1, 'time-c')])
        result = self.compare(baseline(), baseline(guisettings=gui(uptime='456'), textures13=after))
        self.assertEqual(result['guisettings'], maintenance(('M1_UPTIME', 1)))
        self.assertEqual(result['textures13'], maintenance(
            ('M2_CACHE_ROW_CREATE', 1), ('M2_CACHE_ROW_EVICT', 1), ('M2_CACHE_SIZES_CREATE', 1),
            ('M2_CACHE_SIZES_EVICT', 1), ('M2_SIZES_LASTUSETIME', 1), ('M2_SIZES_USECOUNT', 1),
            ('M2_TEXTURE_LASTHASHCHECK', 1)))
        for name in ('addons33', 'estuary', 'keyboard'):
            self.assertEqual(result[name], EXACT)

    def test_compare_file_agrees_with_the_five_file_comparison(self):
        before, after = baseline(), baseline(guisettings=gui(uptime='456'))
        full = self.compare(before, after)
        for name in pc.PROTECTED_KEYS:
            with self.subTest(file=name):
                self.assertEqual(pc.compare_file(name, before[name], after[name]), full[name])


class NegativeControlTests(ComparatorTestCase):
    def test_any_other_guisettings_leaf_is_meaningful(self):
        cases = {
            'settinglevel': gui(level='advanced'),
            'root setting': gui(rss='true'),
            'audio mute': gui(mute='true'),
            'audio volume': gui(fvolume='0.6'),
        }
        for label, after in cases.items():
            with self.subTest(change=label):
                result = self.compare(baseline(), baseline(guisettings=after))
                self.assert_only(result, 'guisettings', meaningful(1))

    def test_uptime_plus_another_leaf_is_meaningful_and_uptime_is_not_counted(self):
        for after in (gui(uptime='456', level='advanced'), gui(uptime='456', rss='true')):
            with self.subTest(after=after):
                result = self.compare(baseline(), baseline(guisettings=after))
                self.assert_only(result, 'guisettings', meaningful(1))

    def test_structural_change_to_the_uptime_element_is_meaningful(self):
        base = gui()
        cases = {
            'element becomes a container': (edit_general(base, lambda children: tuple(
                ('systemtotaluptime', '', (('x', '1', ()),)) if child[0] == 'systemtotaluptime' else child
                for child in children)), 2),
            'element removed': (edit_general(base, lambda children: tuple(
                child for child in children if child[0] != 'systemtotaluptime')), 2),
            'element moved within general': (edit_general(base, lambda children: (
                (children[1], children[0]) + tuple(children[2:]))), 1),
        }
        for label, (after, count) in cases.items():
            with self.subTest(change=label):
                result = self.compare(baseline(), baseline(guisettings=after))
                self.assert_only(result, 'guisettings', meaningful(count))

    def test_retained_texture_identity_fields_are_meaningful(self):
        cases = {
            'url': [(1, 'image://changed-url', TEXTURE_BASE[0][2], TEXTURE_BASE[0][3], TEXTURE_BASE[0][4]),
                    TEXTURE_BASE[1]],
            'cachedurl': [(1, TEXTURE_BASE[0][1], 'cache://changed-cached', TEXTURE_BASE[0][3], TEXTURE_BASE[0][4]),
                          TEXTURE_BASE[1]],
            'imagehash': [(1, TEXTURE_BASE[0][1], TEXTURE_BASE[0][2], 'changed-hash', TEXTURE_BASE[0][4]),
                          TEXTURE_BASE[1]],
        }
        for label, texture in cases.items():
            with self.subTest(field=label):
                result = self.compare(baseline(), baseline(textures13=textures(texture=texture)))
                self.assert_only(result, 'textures13', meaningful(1))

    def test_identity_change_with_a_usecount_change_is_meaningful_with_identity_count(self):
        after = textures(
            texture=[(1, 'image://changed-url', TEXTURE_BASE[0][2], TEXTURE_BASE[0][3], TEXTURE_BASE[0][4]),
                     TEXTURE_BASE[1]],
            sizes=[(1, 64, 64, 64, 4, 'SECRET-USE-0a8c'), SIZES_BASE[1], SIZES_BASE[2]])
        result = self.compare(baseline(), baseline(textures13=after))
        self.assert_only(result, 'textures13', meaningful(1))

    def test_other_texture_or_sizes_or_version_fields_are_meaningful(self):
        cases = {
            'sizes width changes, so the identity key changes': (
                textures(sizes=[(1, 64, 96, 64, 3, 'SECRET-USE-0a8c'), SIZES_BASE[1], SIZES_BASE[2]]), 2),
            'sizes row added under a retained texture': (
                textures(sizes=SIZES_BASE + [(1, 256, 256, 256, 0, None)]), 1),
            'sizes row removed under a retained texture': (
                textures(sizes=[SIZES_BASE[0], SIZES_BASE[2]]), 1),
            'path row content changed': (
                textures(path=[(1, 'library://SECRET-PATH-3e5f', 'music', 'texture-ref')]), 1),
            'path row added': (
                textures(path=PATH_BASE + [(2, 'library://other', 'music', None)]), 1),
            'version row changed': (textures(version=(13, 1)), 1),
        }
        for label, (after, count) in cases.items():
            with self.subTest(change=label):
                result = self.compare(baseline(), baseline(textures13=after))
                self.assert_only(result, 'textures13', meaningful(count))

    def test_textures_schema_difference_in_the_later_state_is_meaningful(self):
        cases = {
            'extra table': textures() + [('extra', [enc([1])])],
            'texture row with fewer columns': textures(texture=[
                (1, 'image://SECRET-URL-8e0f', 'cache://SECRET-CACHED-2c9a', 'SECRET-HASH-6d3b')]),
            'version 14': textures(version=(14, 0)),
        }
        for label, after in cases.items():
            with self.subTest(change=label):
                result = self.compare(baseline(), baseline(textures13=after))
                self.assert_only(result, 'textures13', meaningful(1))

    def test_addons33_estuary_and_keyboard_changes_are_meaningful_without_exception(self):
        estuary_changed = w.xml_projection(ESTUARY_XML.replace(b'SECRET-ESTUARY-9b6d', b'changed-value'), 3)
        estuary_added = w.xml_projection(ESTUARY_XML.replace(
            b'</settings>', b'<setting id="skin.estuary.extra" type="bool">false</setting></settings>'), 3)
        keyboard_changed = w.xml_projection(KEYBOARD_XML.replace(b'en-us', b'de-de'), 4)
        cases = {
            'addons33 enabled flag flipped': ('addons33', [('plugin.SECRET-ADDON-4b1d', False), ('script.beta', False)]),
            'addons33 entry added': ('addons33', ADDONS_BASE + [('script.gamma', True)]),
            'estuary value changed': ('estuary', estuary_changed),
            'estuary setting added': ('estuary', estuary_added),
            'keyboard value changed': ('keyboard', keyboard_changed),
        }
        for label, (key, after) in cases.items():
            with self.subTest(change=label):
                result = self.compare(baseline(), baseline(**{key: after}))
                self.assert_only(result, key, meaningful(1))


class RejectionTests(ComparatorTestCase):
    def assert_rejected(self, before, after, reason):
        with self.assertRaises(pc.ComparatorRejected) as caught:
            pc.compare_protected_files(before, after)
        self.assertEqual(caught.exception.reason, reason)

    def test_non_mapping_or_wrong_key_set_is_rejected(self):
        self.assert_rejected(None, baseline(), 'invalid_input')
        missing = baseline()
        del missing['keyboard']
        self.assert_rejected(missing, baseline(), 'invalid_input')
        extra = baseline()
        extra['unexpected'] = 'value'
        self.assert_rejected(baseline(), extra, 'invalid_input')

    def test_unknown_or_invalid_file_key_is_rejected(self):
        with self.assertRaises(pc.ComparatorRejected) as caught:
            pc.compare_file('shadow', baseline()['guisettings'], baseline()['guisettings'])
        self.assertEqual(caught.exception.reason, 'invalid_input')
        with self.assertRaises(pc.ComparatorRejected) as caught:
            pc.compare_file(None, None, None)
        self.assertEqual(caught.exception.reason, 'invalid_input')

    def test_malformed_uptime_is_rejected_even_when_unchanged(self):
        base = gui()
        for text in ('', '012', '-1', '1.5', 'abc', ' 12', '1234567890123456789', 'SECRET-UPTIME-BAD-7c3a'):
            with self.subTest(text=text):
                bad = edit_general(base, set_uptime(text))
                self.assert_rejected(baseline(guisettings=bad), baseline(guisettings=bad), 'malformed_uptime')
                self.assert_rejected(baseline(), baseline(guisettings=bad), 'malformed_uptime')

    def test_duplicate_uptime_child_is_ambiguous_and_rejected(self):
        duplicate = edit_general(gui(), lambda children: children + (children[0],))
        self.assert_rejected(baseline(), baseline(guisettings=duplicate), 'ambiguous_key')
        self.assert_rejected(baseline(guisettings=duplicate), baseline(), 'ambiguous_key')

    def test_malformed_guisettings_shapes_are_rejected(self):
        attrs, rows, sections = gui()
        by_name = dict(sections)
        swapped = (('general', by_name['audio']), ('audio', by_name['general']))
        cases = {
            'two-part projection': ((attrs, rows), 'unexpected_shape'),
            'section name does not match its node': ((attrs, rows, swapped), 'unexpected_shape'),
            'duplicate root setting key': ((attrs, rows + [rows[0]], sections), 'ambiguous_key'),
            'nested setting value': ((attrs, [(rows[0][0], ('serialized_text', None, ['x']))] + list(rows[1:]),
                                      sections), 'unexpected_shape'),
        }
        for label, (bad, reason) in cases.items():
            with self.subTest(shape=label):
                self.assert_rejected(baseline(), baseline(guisettings=bad), reason)

    def test_malformed_settings_shapes_are_rejected(self):
        estuary_attrs, estuary_rows = w.xml_projection(ESTUARY_XML, 3)
        keyboard_attrs, keyboard_rows = w.xml_projection(KEYBOARD_XML, 4)
        cases = {
            'estuary three-part projection': ('estuary', (estuary_attrs, estuary_rows, ()), 'unexpected_shape'),
            'estuary nested value': ('estuary', (estuary_attrs, [(estuary_rows[0][0], ('string', ['x']))]
                                                 + list(estuary_rows[1:])), 'unexpected_shape'),
            'keyboard duplicated key': ('keyboard', (keyboard_attrs, keyboard_rows + keyboard_rows),
                                        'ambiguous_key'),
        }
        for label, (key, bad, reason) in cases.items():
            with self.subTest(shape=label):
                self.assert_rejected(baseline(), baseline(**{key: bad}), reason)

    def test_malformed_texture_rows_are_rejected_in_either_position(self):
        def with_table(table, blobs):
            return [(name, blobs if name == table else rows) for name, rows in textures()]

        cases = {
            'non-canonical spacing': (
                with_table('texture', [enc(TEXTURE_BASE[0]).replace(b', ', b',')]), 'malformed_row'),
            'boolean column': (with_table('texture', [b'[1, "a", "b", "c", true]']), 'malformed_row'),
            'float column': (with_table('texture', [b'[1.0, "a", "b", "c", null]']), 'malformed_row'),
            'truncated json': (with_table('texture', [b'[1, "SECRET-URL-8e0f"']), 'malformed_row'),
            'text instead of bytes': (with_table('texture', ['[1, "a", "b", "c", null]']), 'malformed_row'),
            'duplicate texture id': (
                with_table('texture', sorted(enc(row) for row in TEXTURE_BASE + [TEXTURE_BASE[0]])),
                'ambiguous_key'),
            'duplicate sizes identity': (
                with_table('sizes', sorted(enc(row) for row in SIZES_BASE + [(1, 64, 64, 64, 9, None)])),
                'ambiguous_key'),
            'orphan sizes row': (
                with_table('sizes', sorted(enc(row) for row in SIZES_BASE + [(99, 1, 1, 1, 1, None)])),
                'orphan_row'),
        }
        for label, (bad, reason) in cases.items():
            with self.subTest(case=label):
                self.assert_rejected(textures13_only(bad), baseline(), reason)
                self.assert_rejected(baseline(), textures13_only(bad), reason)

    def test_baseline_with_a_non_exact_schema_is_rejected(self):
        for label, bad in (('version 14', textures(version=(14, 0))),
                           ('null version column', textures(version=(13, None)))):
            with self.subTest(case=label):
                self.assert_rejected(textures13_only(bad), baseline(), 'unexpected_schema')

    def test_malformed_addons33_is_rejected_in_either_position(self):
        cases = {
            'duplicate identifier': (ADDONS_BASE + [ADDONS_BASE[1]], 'ambiguous_key'),
            'integer enabled flag': ([('script.beta', 0)], 'unexpected_shape'),
            'non-text identifier': ([(7, True)], 'unexpected_shape'),
            'empty identifier': ([('', True)], 'unexpected_shape'),
        }
        for label, (bad, reason) in cases.items():
            with self.subTest(case=label):
                self.assert_rejected(baseline(addons33=bad), baseline(), reason)
                self.assert_rejected(baseline(), baseline(addons33=bad), reason)


class PrivacyAndPersistenceTests(ComparatorTestCase):
    def test_results_never_carry_injected_values(self):
        after = baseline(
            guisettings=gui(uptime='456', level='advanced'),
            textures13=textures(sizes=[(1, 64, 64, 64, 4, 'SECRET-USE-0a8c'), SIZES_BASE[1], SIZES_BASE[2]]),
            addons33=[('plugin.SECRET-ADDON-4b1d', False), ('script.beta', False)],
        )
        result = self.compare(baseline(), after)
        self.assertEqual(result['guisettings'].verdict, pc.MEANINGFUL)
        self.assertEqual(result['textures13'].verdict, pc.MAINTENANCE_ONLY)
        rendered = repr(result)
        for token in SECRETS:
            self.assertNotIn(token, rendered)

    def test_rejections_carry_no_input_values_and_no_chained_context(self):
        cases = {
            'uptime': baseline(guisettings=edit_general(gui(), set_uptime('SECRET-UPTIME-BAD-7c3a'))),
            'addon flag': baseline(addons33=[('SECRET-ADDON-4b1d', 1)]),
            'texture row': textures13_only([
                ('version', [enc((13, 0))]), ('texture', [b'[SECRET-URL-8e0f']), ('sizes', []), ('path', [])]),
        }
        for label, bad in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(pc.ComparatorRejected) as caught:
                    pc.compare_protected_files(bad, bad)
                error = caught.exception
                report = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
                for text in (report, repr(error), str(error), repr(error.args)):
                    for token in SECRETS:
                        self.assertNotIn(token, text)
                self.assertIsNone(error.__cause__)
                self.assertIsNone(error.__context__)

    def test_comparison_writes_no_output_and_logs_nothing(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertNoLogs(level='DEBUG'):
            self.compare(baseline(), baseline(guisettings=gui(uptime='456')))
            with self.assertRaises(pc.ComparatorRejected):
                pc.compare_protected_files(None, baseline())
        self.assertEqual(out.getvalue() + err.getvalue(), '')

    def test_comparison_performs_no_file_or_directory_io(self):
        before, after = baseline(), baseline(guisettings=gui(uptime='456'))

        def forbidden(*args, **kwargs):
            raise AssertionError('file or directory access attempted')

        with mock.patch('builtins.open', side_effect=forbidden), \
                mock.patch('os.open', side_effect=forbidden), \
                mock.patch('os.write', side_effect=forbidden), \
                mock.patch('os.mkdir', side_effect=forbidden), \
                mock.patch('tempfile.mkstemp', side_effect=forbidden), \
                mock.patch('tempfile.TemporaryDirectory', side_effect=forbidden):
            result = pc.compare_protected_files(before, after)
        self.assertEqual(result['guisettings'], maintenance(('M1_UPTIME', 1)))

    def test_module_has_no_persistence_hashing_or_process_dependencies(self):
        for name in ('hashlib', 'pickle', 'marshal', 'shelve', 'tempfile', 'os', 'sys',
                     'subprocess', 'socket', 'logging', 'pathlib', 'io'):
            with self.subTest(module=name):
                self.assertFalse(hasattr(pc, name))

    def test_inputs_are_not_mutated_and_results_repeat(self):
        before, after = baseline(), baseline(guisettings=gui(uptime='456'))
        snapshot = copy.deepcopy((before, after))
        first = self.compare(before, after)
        self.assertEqual(first, self.compare(before, after))
        self.assertEqual((before, after), snapshot)


if __name__ == '__main__':
    unittest.main()
