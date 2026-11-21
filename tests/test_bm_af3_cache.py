"""Disposable APFS transaction tests. Never use the fixed Test.app."""
import io
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tools import bm_af3_cache as cache
from tools import bm_profile_isolation as fs


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS exclusive rename')
class CacheQuarantineTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(scratch.cleanup)
        self.addons = Path(scratch.name) / 'addons'
        self.package = self.addons / 'synthetic'
        self.package.mkdir(parents=True)
        self.native = fs.Native()
        self.inventory = {}
        self.sources = {}
        self.payload = {}
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, 'w') as archive:
            for module in ('first', 'second', 'third'):
                source = self.package / (module + '.py')
                source.write_text('value = "cache"\n')
                os.utime(source, ns=(1710000000000000000,) * 2)
                compiled = Path(py_compile.compile(str(source), doraise=True))
                source.write_text('value = "fresh"\n')
                os.utime(source, ns=(1710000000000000000,) * 2)
                name = compiled.relative_to(self.addons).as_posix()
                compiled.chmod(0o640)
                subprocess.run(['/usr/bin/xattr', '-w', 'test.af3', module, str(compiled)], check=True)
                with fs.directory(compiled.parent) as fd:
                    data, identity = cache.file_record(fd, compiled.name, self.native, cache.LIMIT)
                self.payload[name] = (data, identity)
                self.inventory[name] = {'sha256': fs.digest(data), 'size': len(data), 'identity': identity[:7]}
                self.sources[source.relative_to(self.addons).as_posix()] = fs.digest(source.read_bytes())
                archive.writestr(name, data)
        self.backup = archive_bytes.getvalue()

    def operation(self, action, **overrides):
        options = dict(action=action, stopped=lambda: None, native=self.native)
        options.update(overrides)
        return cache.transact(self.addons, self.inventory, self.backup, self.sources, {'synthetic'}, **options)

    def module_value(self):
        return subprocess.check_output(
            [sys.executable, '-I', '-B', '-c',
             'import sys; sys.path.insert(0, sys.argv[1]); import first; print(first.value)',
             str(self.package)], text=True).strip()

    def assert_restored(self):
        for name, (data, before) in self.payload.items():
            path = self.addons / name
            with fs.directory(path.parent) as fd:
                actual, after = cache.file_record(fd, path.name, self.native, cache.LIMIT)
            self.assertEqual(actual, data)
            self.assertEqual(after[:6] + after[7:], before[:6] + before[7:])

    def test_source_fallback_metadata_and_repeats(self):
        self.assertEqual(self.module_value(), 'cache')
        self.assertEqual(self.operation('quarantine')['moved'], 3)
        self.assertEqual(self.module_value(), 'fresh')
        self.assertEqual(self.operation('quarantine')['moved'], 0)
        self.assertEqual(self.operation('restore')['moved'], 3)
        self.assert_restored()
        self.assertEqual(self.operation('restore')['moved'], 0)
        self.assertEqual(self.module_value(), 'cache')
        with self.assertRaisesRegex(fs.Refusal, 'restoration_already_requested'):
            self.operation('quarantine')

    def test_interruption_after_exclusive_move(self):
        real = self.native.rename_between

        def interrupted(src, leaf, dst, destination):
            real(src, leaf, dst, destination)
            if destination == '001.pyc':
                raise KeyboardInterrupt

        from unittest.mock import patch
        with patch.object(self.native, 'rename_between', interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.operation('quarantine')
        self.assertEqual(self.operation('quarantine')['moved'], 1)
        self.assertEqual(self.operation('restore')['moved'], 3)
        self.assert_restored()

    def test_mid_restore_failure_and_retry(self):
        self.operation('quarantine')
        real = self.native.rename_between

        def fail_second(src, leaf, dst, destination):
            if leaf == '001.pyc':
                raise OSError('injected failure')
            real(src, leaf, dst, destination)

        from unittest.mock import patch
        with patch.object(self.native, 'rename_between', fail_second):
            with self.assertRaises(OSError):
                self.operation('restore')
        self.assertEqual(self.operation('restore')['moved'], 2)
        self.assert_restored()

    def test_collision_preserves_both_files(self):
        self.operation('quarantine')
        name = sorted(self.inventory)[0]
        destination = self.addons / name
        destination.write_bytes(b'new cache')
        outcome = self.operation('restore')
        self.assertEqual(outcome, {'status': 'collision', 'paths': [name], 'moved': 0})
        self.assertEqual(destination.read_bytes(), b'new cache')
        self.assertEqual((self.addons.parent / cache.AREA / '000.pyc').read_bytes(),
                         self.payload[name][0])

    def test_unexpected_cache_and_symlink_refused(self):
        unexpected = self.package / 'extra.pyc'
        unexpected.write_bytes(b'extra')
        with self.assertRaisesRegex(fs.Refusal, 'unexpected_cache'):
            self.operation('quarantine')
        unexpected.unlink()
        unexpected.symlink_to(self.package / 'first.py')
        with self.assertRaisesRegex(fs.Refusal, 'unsafe_package_member'):
            self.operation('quarantine')
        self.assert_restored()

    def test_stopped_guard_refuses_before_moves(self):
        def running():
            raise fs.Refusal('running')

        with self.assertRaisesRegex(fs.Refusal, 'running'):
            self.operation('quarantine', stopped=running)
        self.assertFalse((self.addons.parent / cache.AREA).exists())
        self.assert_restored()
