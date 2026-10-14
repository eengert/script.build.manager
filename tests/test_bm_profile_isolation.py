"""Synthetic-only macOS filesystem qualification for the isolation helper."""
import ctypes
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from tools import bm_profile_isolation as p
from tools import bm_test_app as bm
from tests.test_bm_test_app import FilesystemTripwire


OP = 'a' * 32
PRIVATE = b'fabricated-private-value-never-report-671'


class Crash(Exception):
    pass


class Processes:
    running = False

    def list_all(self):
        return [bm.ProcessInfo(42, self.exe)] if self.running else []

    def command_line(self, pid):
        return (self.exe, '-p')


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tripwire = FilesystemTripwire()
        self.tripwire.start()
        self.tmp = tempfile.TemporaryDirectory(prefix='bm-isolation-', dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.assertEqual, self.tripwire.touched, [])
        self.addCleanup(self.tripwire.stop)
        self.root = Path(self.tmp.name) / 'Fake Test.app'
        macos = self.root / 'Contents/MacOS'
        macos.mkdir(parents=True)
        (macos / 'Kodi').write_bytes(b'fake-executable')
        (macos / 'Kodi').chmod(0o755)
        (self.root / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'org.xbmc.kodi', 'CFBundleExecutable': 'Kodi',
            'CFBundlePackageType': 'APPL'}))
        self.target = bm.TestAppTarget.for_tests(self.root)
        self.target.portable_data.mkdir(parents=True)
        self.fabricate(self.target.portable_data)
        self.process = Processes()
        self.process.exe = str(macos / 'Kodi')
        self.services = SimpleNamespace(target=self.target, process_lister=self.process)
        self.helper = p.Isolation(self.services, scratch=True)
        self.paths = self.helper.paths(OP)
        self.parent = self.target.portable_data.parent
        with p.directory(self.parent) as fd:
            self.before = p.snapshot(fd, self.paths['active'], self.helper.native)

    def fabricate(self, root):
        data = root / 'userdata/addon_data/script.build.manager'
        (data / 'private-overlays/nested').mkdir(parents=True)
        (data / 'private-overlays/nested/binary').write_bytes(PRIVATE + bytes(range(256)))
        (data / 'build-library').mkdir()
        for name in ('selection.json', 'registry.json', 'applied.json'):
            (data / 'build-library' / name).write_bytes(b'{"fabricated":true}')
        (root / 'addons').mkdir()
        database = root / 'userdata/Database'
        database.mkdir()
        conn = sqlite3.connect(str(database / 'fixture.db'))
        conn.execute('create table fixture(value blob)')
        conn.execute('insert into fixture values(?)', (PRIVATE,))
        conn.commit()
        conn.close()
        (database / 'fixture.db-wal').write_bytes(b'fabricated-wal\0' + PRIVATE)
        (database / 'fixture.db-shm').write_bytes(b'fabricated-shm\0' + PRIVATE)
        (data / 'private-overlays/nested/binary').chmod(0o640)
        lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        result = lib.setxattr(os.fsencode(data), b'user.bm-fixture', PRIVATE, len(PRIVATE), 0, 0)
        self.assertEqual(result, 0)

    def run_phase(self, phase, **kwargs):
        return self.helper.run(phase, OP, confirm=phase, portable=True, **kwargs)

    def fresh(self):
        self.target.portable_data.mkdir()
        self.fabricate(self.target.portable_data)
        (self.target.portable_data / 'fresh').write_bytes(b'new qualification fixture')

    def test_round_trip(self):
        self.assertEqual(self.run_phase('preserve')['phase'], 'preserved')
        self.fresh()
        with p.directory(self.parent) as fd:
            fresh = p.snapshot(fd, self.paths['active'], self.helper.native)
        self.assertEqual(self.run_phase('park')['phase'], 'parked')
        self.assertEqual(self.run_phase('restore')['phase'], 'restored')
        with p.directory(self.parent) as fd:
            p.verify(fd, self.paths['active'], self.before, self.helper.native)
            p.verify(fd, self.paths['parked'], fresh, self.helper.native)
        self.assertEqual(p.identity(self.target.portable_data.stat()), self.before[p.digest(b'')]['id'])

    def test_preview_no_io_and_gate(self):
        with mock.patch.object(self.helper, 'safety', side_effect=AssertionError):
            self.assertEqual(self.helper.preview(OP)['state'].split(';')[0], 'unobserved')
        for confirm, portable in ((None, True), ('park', True), ('preserve', False)):
            with self.assertRaises(p.Refusal):
                self.helper.run('preserve', OP, confirm=confirm, portable=portable)
        self.assertTrue(self.target.portable_data.is_dir())

    def test_collision_and_repeat(self):
        dest = self.parent / self.paths['original']
        dest.mkdir()
        (dest / 'sentinel').write_bytes(PRIVATE)
        with self.assertRaises(p.Refusal):
            self.run_phase('preserve')
        self.assertEqual((dest / 'sentinel').read_bytes(), PRIVATE)
        dest.joinpath('sentinel').unlink()
        dest.rmdir()  # scratch fixture only
        self.run_phase('preserve')
        self.fresh()
        with self.assertRaises(p.Refusal):
            self.run_phase('preserve')
        self.run_phase('park')
        with self.assertRaises(p.Refusal):
            self.run_phase('park')
        self.run_phase('restore')
        with self.assertRaises(p.Refusal):
            self.run_phase('restore')

    def test_wrong_stale_identity(self):
        self.run_phase('preserve')
        self.fresh()
        original = self.parent / self.paths['original']
        original.rename(original.with_name('retained-original'))
        original.mkdir()
        with self.assertRaises(p.Refusal):
            self.run_phase('park')
        self.assertTrue((self.parent / 'retained-original').is_dir())

    def test_changed_bytes_report_opaque(self):
        self.run_phase('preserve')
        original = self.parent / self.paths['original']
        (original / 'userdata/addon_data/script.build.manager/private-overlays/nested/binary').write_bytes(PRIVATE)
        self.fresh()
        with self.assertRaises(p.Refusal) as error:
            self.run_phase('park')
        self.assertIn('integrity_difference', str(error.exception))
        self.assertNotIn(PRIVATE.decode(), str(error.exception))
        self.assertNotIn('private-overlays', str(error.exception))

    def test_symlink_ancestor(self):
        resources = self.parent.parent
        moved = resources.with_name('retained-resources')
        resources.rename(moved)
        resources.symlink_to(moved)
        with self.assertRaises((p.Refusal, bm.HelperError, OSError)):
            self.run_phase('preserve')
        self.assertTrue((moved / 'Kodi/portable_data').is_dir())

    def test_symlink_tree(self):
        (self.target.portable_data / 'link').symlink_to(self.tmp.name)
        with self.assertRaises(p.Refusal):
            self.run_phase('preserve')

    def test_boundaries(self):
        for op in ('../escape', 'A' * 32, '', '0' * 33):
            with self.assertRaises(p.Refusal):
                self.helper.preview(op)
        with self.assertRaises(p.Refusal):
            p.Isolation(self.services)
        services = SimpleNamespace(target=bm.TestAppTarget.for_tests(Path('/Applications/Fake.app')))
        with self.assertRaises(p.Refusal):
            p.Isolation(services, scratch=True)

    def test_running_refusal(self):
        self.process.running = True
        with self.assertRaises(bm.HelperError):
            self.run_phase('preserve')
        self.assertTrue(self.target.portable_data.exists())

    def test_cross_volume_refusal(self):
        real_exists = p.exists
        def changed(fd, name):
            st = real_exists(fd, name)
            if name == 'portable_data' and st is not None:
                return SimpleNamespace(st_mode=st.st_mode, st_dev=st.st_dev + 1)
            return st
        with mock.patch.object(p, 'exists', side_effect=changed):
            with self.assertRaisesRegex(p.Refusal, 'cross_volume'):
                self.run_phase('preserve')

    def test_hold_and_stage_refusal(self):
        for name in ('frozen_install_transaction.json', 'restart_transaction.lock', 'activation_hold.json'):
            path = self.target.bm_data_dir / name
            path.write_bytes(PRIVATE)
            with self.assertRaisesRegex(p.Refusal, 'transaction_or_hold'):
                self.run_phase('preserve')
            path.unlink()
        self.target.stage_area.mkdir()
        with self.assertRaisesRegex(p.Refusal, 'stage_requires'):
            self.run_phase('preserve')

    def test_exclusive_rename_race(self):
        def collide(point):
            if point == 'before_rename_preserve':
                (self.parent / self.paths['original']).mkdir()
        self.helper.fault = collide
        with self.assertRaisesRegex(p.Refusal, 'exclusive_rename_failed'):
            self.run_phase('preserve')
        self.assertTrue(self.target.portable_data.exists())

    def test_durability_refusal_before_mutation(self):
        with mock.patch.object(self.helper.native, 'sync', side_effect=OSError):
            with self.assertRaises(OSError):
                self.run_phase('preserve')
        self.assertTrue(self.target.portable_data.exists())
        self.assertFalse((self.parent / self.paths['record']).exists())

    def test_corrupt_record(self):
        self.run_phase('preserve')
        self.fresh()
        record = self.parent / self.paths['record'] / '000.json'
        record.write_bytes(b'{broken')
        with self.assertRaises((ValueError, bm.HelperError)):
            self.run_phase('park')
        self.assertTrue(self.target.portable_data.exists())

    def test_metadata_acl_and_xattr_differences(self):
        path = self.target.bm_data_dir / 'private-overlays/nested/binary'
        subprocess.run(['/bin/chmod', '+a', 'everyone allow read', str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with p.directory(self.parent) as fd:
            before = p.snapshot(fd, self.paths['active'], self.helper.native)
            self.assertTrue(any(row['attrs'][1] != 'absent' for row in before.values()))
        self.run_phase('preserve')
        self.fresh()
        path = self.parent / self.paths['original'] / path.relative_to(self.target.portable_data)
        path.chmod(0o600)
        with self.assertRaisesRegex(p.Refusal, 'mode'):
            self.run_phase('park')

    def test_acl_difference(self):
        path = self.target.bm_data_dir / 'private-overlays/nested/binary'
        subprocess.run(['/bin/chmod', '+a', 'everyone allow read', str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.run_phase('preserve')
        self.fresh()
        path = self.parent / self.paths['original'] / path.relative_to(self.target.portable_data)
        subprocess.run(['/bin/chmod', '-N', str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self.assertRaisesRegex(p.Refusal, 'attrs'):
            self.run_phase('park')

    def test_xattr_failure_closed(self):
        with mock.patch.object(self.helper.native, 'attrs', side_effect=p.Refusal('xattrs_unavailable')):
            with self.assertRaisesRegex(p.Refusal, 'xattrs_unavailable'):
                self.run_phase('preserve')
        self.assertTrue(self.target.portable_data.exists())

    def test_partial_record_retained(self):
        real_write = os.write
        calls = []
        def partial(fd, data):
            if not calls:
                calls.append(True)
                return real_write(fd, data[:10])
            raise OSError('fabricated write failure')
        with mock.patch.object(os, 'write', side_effect=partial):
            with self.assertRaises(OSError):
                self.run_phase('preserve')
        record = self.parent / self.paths['record'] / '000.json'
        self.assertEqual(record.stat().st_size, 10)
        with self.assertRaises((ValueError, bm.HelperError)):
            self.run_phase('recover')
        self.assertTrue(self.target.portable_data.exists())

    def test_record_identity_binding(self):
        self.run_phase('preserve')
        self.fresh()
        record = self.parent / self.paths['record'] / '001.json'
        original = record.read_bytes()
        for field, value in (('operation', 'b' * 32), ('parent', [0, 0]),
                             ('previous', 'c' * 64), ('phase', 'restored'),
                             ('original', {PRIVATE.decode(): {}})):
            obj = json.loads(original)
            obj[field] = value
            record.write_bytes(p.encoded(obj))
            with self.assertRaises(p.Refusal) as error:
                self.run_phase('park')
            self.assertNotIn(PRIVATE.decode(), str(error.exception))
            self.assertTrue(self.target.portable_data.exists())
        record.write_bytes(original)

    def test_fresh_park_and_restore_collisions(self):
        self.run_phase('preserve')
        self.fresh()
        parked = self.parent / self.paths['parked']
        parked.mkdir()
        with self.assertRaisesRegex(p.Refusal, 'destination_collision'):
            self.run_phase('park')
        parked.rmdir()
        self.run_phase('park')
        self.target.portable_data.mkdir()
        (self.target.portable_data / 'sentinel').write_bytes(PRIVATE)
        with self.assertRaisesRegex(p.Refusal, 'destination_collision'):
            self.run_phase('restore')
        self.assertEqual((self.target.portable_data / 'sentinel').read_bytes(), PRIVATE)
        self.assertTrue(parked.exists())

    def test_ancestor_change_immediately_before_rename(self):
        def change(point):
            if point == 'before_rename_preserve':
                resources = self.parent.parent
                moved = resources.with_name('retained')
                resources.rename(moved)
                resources.symlink_to(moved)
        self.helper.fault = change
        with self.assertRaises((bm.HelperError, OSError, p.Refusal)):
            self.run_phase('preserve')
        self.assertTrue((self.parent.parent.with_name('retained') / 'Kodi/portable_data').exists())

    def test_ambiguous_recovery_retains_both(self):
        def crash(point):
            if point == 'after_record_prepared':
                raise Crash()
        self.helper.fault = crash
        with self.assertRaises(Crash):
            self.run_phase('preserve')
        (self.parent / self.paths['original']).mkdir()
        self.helper.fault = lambda point: None
        with self.assertRaisesRegex(p.Refusal, 'recovery_ambiguous'):
            self.run_phase('recover')
        self.assertTrue(self.target.portable_data.exists())
        self.assertTrue((self.parent / self.paths['original']).exists())

    def test_failure_transitions(self):
        # Every rename and durable record edge, using a new entirely synthetic
        # bundle per case. No cleanup is performed by the helper on exceptions.
        points = [('preserve', x) for x in ('before_journal_create', 'after_journal_create',
                                             'after_journal_sync')]
        for action, intent, final in (('preserve', 'prepared', 'preserved'),
                                      ('park', 'parking', 'parked'),
                                      ('restore', 'restoring', 'restored')):
            points += [(action, 'before_record_' + intent), (action, 'after_record_' + intent),
                       (action, 'after_write_' + intent), (action, 'after_file_sync_' + intent),
                       (action, 'before_rename_' + action), (action, 'after_rename_' + action),
                       (action, 'after_sync_' + action), (action, 'before_record_' + final),
                       (action, 'after_record_' + final),
                       (action, 'after_write_' + final), (action, 'after_file_sync_' + final)]
        for action, point in points:
            with self.subTest(action=action, point=point):
                # independent fixture lifecycle also enforces the tripwire
                case = IsolationTests('test_round_trip')
                case.setUp()
                try:
                    if action != 'preserve':
                        case.run_phase('preserve')
                        case.fresh()
                    fresh_evidence = None
                    if action != 'preserve':
                        with p.directory(case.parent) as fd:
                            fresh_evidence = p.snapshot(fd, case.paths['active'], case.helper.native)
                    if action == 'restore':
                        case.run_phase('park')
                    def fail(where):
                        if where == point:
                            raise Crash(point)
                    case.helper.fault = fail
                    with self.assertRaises(Crash):
                        case.run_phase(action)
                    case.helper.fault = lambda where: None
                    # Each original inode/byte tree remains at exactly one location.
                    locations = []
                    with p.directory(case.parent) as fd:
                        for name in (case.paths['active'], case.paths['original']):
                            st = p.exists(fd, name)
                            if st and p.identity(st) == case.before[p.digest(b'')]['id']:
                                p.verify(fd, name, case.before, case.helper.native)
                                locations.append(name)
                    self.assertEqual(len(locations), 1)
                    if fresh_evidence is not None:
                        with p.directory(case.parent) as fd:
                            name = (case.paths['parked'] if p.exists(fd, case.paths['parked']) else
                                    case.paths['active'])
                            p.verify(fd, name, fresh_evidence, case.helper.native)
                    # Explicit recovery either verifies intent without a rename,
                    # or refuses missing/terminal records while retaining all trees.
                    with mock.patch.object(case.helper.native, 'rename', side_effect=AssertionError):
                        record = case.parent / case.paths['record']
                        files = sorted(record.glob('*.json')) if record.exists() else []
                        if not files:
                            with self.assertRaises((p.Refusal, OSError)):
                                case.run_phase('recover')
                        else:
                            phase = json.loads(files[-1].read_bytes())['phase']
                            if phase in ('prepared', 'parking', 'restoring'):
                                result = case.run_phase('recover')
                                self.assertIn(result['phase'], ('cancelled', 'preserved', 'parked', 'restored'))
                            else:
                                with self.assertRaises(p.Refusal):
                                    case.run_phase('recover')
                finally:
                    case.doCleanups()


if __name__ == '__main__':
    unittest.main()
