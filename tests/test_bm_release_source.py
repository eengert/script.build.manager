"""Synthetic Git objects and scratch exports only; no runtime/profile access."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import bm_release_source as r

SECRET = 'synthetic-private-value-must-never-export'


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bm-release-test-', dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.repo = self.root / 'objects'; self.repo.mkdir()
        self.output = self.root / 'export'; self.manifest = self.root / 'r3.json'
        self.files = {'addon.xml': b'<addon id="script.build.manager" version="0.1.0"/>',
                      'default.py': b'# synthetic script\n', 'service.py': b'# synthetic service\n',
                      'resources/images/icon.png': b'synthetic-icon', r.EXCLUSION: b'{"id":"synthetic-fixture"}'}
        self.files.update({f'resources/assets/file{i:03}.bin': str(i).encode() for i in range(71)})
        self.command('init', '-q')
        for p, raw in self.files.items():
            target = self.repo / p; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        self.command('add', '.')
        self.command('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
                     '-c', 'commit.gpgsign=false', 'commit', '-qm', 'synthetic source')
        self.commit = self.command('rev-parse', 'HEAD').decode().strip()
        self.tree = self.command('rev-parse', 'HEAD^{tree}').decode().strip()
        entries = []
        for p, raw in sorted(self.files.items()):
            blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            entries.append(dict(path=p, git_mode='100644', git_blob=blob,
                                sha256=r.digest(raw), size=len(raw)))
        self.record = {'candidate': {'commit': self.commit, 'tree': self.tree},
                       'build_manager': {'files': entries, 'file_count': 76,
                                         'total_bytes': sum(map(len, self.files.values()))}}
        fixture = next(e for e in entries if e['path'] == r.EXCLUSION)
        for name, value in [('COMMIT', self.commit), ('TREE', self.tree),
                            ('EXCLUSION_BLOB', fixture['git_blob']), ('EXCLUSION_SHA256', fixture['sha256'])]:
            patch = mock.patch.object(r, name, value); patch.start(); self.addCleanup(patch.stop)
        self.authorize_manifest()

    def command(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL,
                                       env=dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null'))

    def authorize_manifest(self):
        # Test-only authority: CLI/production exposes no alternate pins or exclusions.
        self.manifest.write_bytes(r.encoded(self.record))
        patch = mock.patch.object(r, 'MANIFEST_SHA256', r.digest(self.manifest.read_bytes()))
        patch.start(); self.addCleanup(patch.stop)

    def export(self):
        return r.export(self.repo, self.manifest, self.output)

    def verify(self):
        return r.verify_export(self.repo, self.manifest, self.output)

    def refused(self, operation):
        with self.assertRaises((r.Refusal, OSError, ValueError, KeyError, StopIteration)):
            operation()

    def test_exact_76_admitted_one_exclusion_75_exported(self):
        admitted, manifest = r.admit(self.repo, self.manifest)
        self.assertEqual(admitted, self.files)
        result = self.export(); self.assertTrue(result['ok'])
        self.assertEqual(len(manifest['included']), 75); self.assertEqual(len(manifest['excluded']), 1)
        self.assertEqual(manifest['excluded'][0]['path'], r.EXCLUSION)
        for entry in manifest['included']:
            self.assertEqual((self.output/r.PRODUCT/entry['path']).read_bytes(), self.files[entry['path']])
        self.assertFalse((self.output/r.PRODUCT/r.EXCLUSION).exists())
        self.assertEqual(result['release_manifest_sha256'], r.digest((self.output/'release-source.json').read_bytes()))
        self.assertEqual(result, self.verify())

    def test_tampered_manifest_and_expected_digest_refused_before_output(self):
        self.manifest.write_bytes(self.manifest.read_bytes()+b' ')
        self.refused(self.export); self.assertFalse(self.output.exists())
        with mock.patch.object(r, 'MANIFEST_SHA256', '0'*64): self.refused(self.export)

    def test_wrong_product_commit_and_tree(self):
        for field in ('commit', 'tree'):
            with self.subTest(field=field):
                original = self.record['candidate'][field]; self.record['candidate'][field] = '0'*40
                self.authorize_manifest(); self.refused(self.export); self.record['candidate'][field] = original

    def test_actual_git_tree_identity_is_required(self):
        original = r.git
        def wrong(repo, *args):
            if args == ('rev-parse', r.COMMIT+'^{tree}'): return b'0'*40+b'\n'
            return original(repo, *args)
        with mock.patch.object(r, 'git', side_effect=wrong): self.refused(self.export)

    def test_fixture_blob_and_checksum_mismatch(self):
        fixture = next(e for e in self.record['build_manager']['files'] if e['path'] == r.EXCLUSION)
        for field in ('git_blob', 'sha256'):
            with self.subTest(field=field):
                old = fixture[field]; fixture[field] = '0'*len(old)
                self.authorize_manifest(); self.refused(self.export); fixture[field] = old

    def test_exclusion_policy_mismatch_cannot_silently_omit(self):
        with mock.patch.object(r, 'EXCLUSION_SHA256', '0'*64): self.refused(self.export)

    def test_missing_changed_ordinary_blob_and_wrong_git_mode(self):
        original = r.git
        target = next(e for e in self.record['build_manager']['files'] if e['path'] == 'default.py')
        for kind in ('missing', 'changed', 'symlink'):
            def damaged(repo, *args):
                if args == ('cat-file', 'blob', target['git_blob']) and kind == 'changed': return SECRET.encode()
                if args == ('ls-tree', '-z', r.COMMIT, '--', 'default.py'):
                    if kind == 'missing': return b''
                    if kind == 'symlink': return original(repo, *args).replace(b'100644', b'120000')
                return original(repo, *args)
            with self.subTest(kind=kind), mock.patch.object(r, 'git', side_effect=damaged):
                self.refused(self.export)

    def test_second_exclusion_and_missing_source_entry(self):
        self.record['build_manager']['files'].pop(); self.authorize_manifest()
        self.refused(self.export); self.assertFalse(self.output.exists())

    def test_extra_manifest_entry_is_not_filtered(self):
        self.record['build_manager']['files'].append(dict(self.record['build_manager']['files'][0]))
        self.authorize_manifest(); self.refused(self.export)

    def test_unsafe_hidden_test_and_private_paths(self):
        for name in ('../escape', '/absolute', 'resources/../escape', 'resources//bad',
                     'resources\\bad', '.agent/history', 'resources/.credentials', 'tests/fixture',
                     'tools/driver.py', 'resources/test/fixture'):
            with self.subTest(path=name): self.refused(lambda: r.relative(name))

    def test_duplicate_and_case_collision(self):
        entries = self.record['build_manager']['files']
        for name in (entries[0]['path'], entries[0]['path'].upper()):
            old = entries[-1]['path']; entries[-1]['path'] = name
            self.authorize_manifest(); self.refused(self.export); entries[-1]['path'] = old

    def test_duplicate_JSON_keys_are_refused(self):
        self.refused(lambda: r.decode(b'{"included":[],"included":["private"]}'))

    def test_manifest_symlink_hardlink_and_special_type(self):
        original = self.manifest.read_bytes(); self.manifest.unlink()
        target = self.root/'target'; target.write_bytes(original)
        self.manifest.symlink_to(target); self.refused(self.export); self.manifest.unlink()
        os.link(target, self.manifest); self.refused(self.export); self.manifest.unlink(); target.unlink()
        os.mkfifo(self.manifest); self.refused(self.export)

    def test_manifest_identity_race(self):
        original = r.git; changed = False
        def replace(repo, *args):
            nonlocal changed
            if not changed:
                changed = True; raw = self.manifest.read_bytes(); self.manifest.unlink(); self.manifest.write_bytes(raw)
            return original(repo, *args)
        with mock.patch.object(r, 'git', side_effect=replace): self.refused(self.export)
        self.assertFalse(self.output.exists())

    def test_repository_source_substitution_race(self):
        original = r.binding
        def swapped(value, expected):
            if Path(value) == self.repo:
                self.repo.rename(self.root/'displaced-repository'); self.repo.mkdir()
            return original(value, expected)
        with mock.patch.object(r, 'binding', side_effect=swapped): self.refused(self.export)

    def test_checkout_bytes_and_private_untracked_files_never_supply_source(self):
        (self.repo/'default.py').write_text(SECRET)
        (self.repo/'.credentials').write_text(SECRET)
        self.export()
        self.assertEqual((self.output/r.PRODUCT/'default.py').read_bytes(), self.files['default.py'])
        self.assertNotIn(SECRET.encode(), b''.join(p.read_bytes() for p in self.output.rglob('*') if p.is_file()))
        self.refused(lambda: r.verify_export(self.repo, self.manifest, self.repo))

    def test_plain_development_directory_is_not_a_Git_source(self):
        development = self.root/'development'; development.mkdir(); (development/'addon.xml').write_text(SECRET)
        self.refused(lambda: r.export(development, self.manifest, self.output))

    def test_unsafe_output_ancestry_and_existing_output(self):
        link = self.root/'link'; link.symlink_to(self.root, target_is_directory=True)
        self.refused(lambda: r.export(self.repo, self.manifest, link/'new'))
        self.refused(lambda: r.export(self.repo, self.manifest, self.root/'..'/'escaped'))
        self.refused(lambda: r.export(self.repo, self.manifest, '/private/tmp'))
        self.output.mkdir(); (self.output/'sentinel').write_text('preserve')
        self.refused(self.export); self.assertEqual((self.output/'sentinel').read_text(), 'preserve')

    def test_export_directory_substitution_refused(self):
        original = r.put; once = False
        def substitute(fd, name, data):
            nonlocal once
            if not once:
                once = True; self.output.rename(self.root/'moved'); self.output.mkdir()
            original(fd, name, data)
        with mock.patch.object(r, 'put', side_effect=substitute): self.refused(self.export)

    def test_incomplete_write_preserves_partial_and_never_validates(self):
        with mock.patch.object(r.os, 'write', return_value=0): self.refused(self.export)
        self.assertTrue(self.output.exists()); self.assertFalse((self.output/'release-source.json').exists())
        self.refused(self.verify)

    def test_close_cleanup_failure_cannot_return_success(self):
        original = os.close
        def close_failure(fd):
            written_file = (stat.S_ISREG(os.fstat(fd).st_mode)
                            and fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_WRONLY)
            original(fd)
            if written_file: raise OSError(SECRET)
        with mock.patch.object(r.os, 'close', side_effect=close_failure): self.refused(self.export)
        self.assertTrue(self.output.exists()); self.assertFalse((self.output/'release-source.json').exists())

    def test_export_tampering_extra_hidden_private_and_symlink(self):
        self.export()
        for name in ('.agent', '.credentials', 'unexpected.bin'):
            target = self.output/r.PRODUCT/name; target.write_text(SECRET)
            self.refused(self.verify); target.unlink()
        victim = self.output/r.PRODUCT/'default.py'; victim.unlink(); victim.symlink_to(self.repo/'default.py')
        self.refused(self.verify)

    def test_export_missing_changed_modes_and_second_exclusion(self):
        self.export(); victim = self.output/r.PRODUCT/'default.py'; raw = victim.read_bytes()
        victim.write_text(SECRET); self.refused(self.verify)
        victim.unlink(); self.refused(self.verify); victim.write_bytes(raw)
        victim.chmod(0o600); self.refused(self.verify); victim.chmod(0o644)
        m = self.output/'release-source.json'; data = json.loads(m.read_text()); data['excluded'].append({'path':'default.py'})
        m.write_bytes(r.encoded(data)); self.refused(self.verify)

    def test_export_reader_replacement_race(self):
        self.export(); original = r.read_at; once = False
        def replacing(fd, name):
            nonlocal once
            value = original(fd, name)
            if name == 'default.py' and not once:
                once = True; p = self.output/r.PRODUCT/name; raw = p.read_bytes(); p.unlink(); p.write_bytes(raw)
            return value
        with mock.patch.object(r, 'read_at', side_effect=replacing): self.refused(self.verify)

    def test_repeated_export_is_byte_identical_but_never_reuses_output(self):
        first = self.export(); self.refused(self.export)
        self.output = self.root/'second'; second = self.export()
        self.assertEqual(first['release_manifest_sha256'], second['release_manifest_sha256'])

    def test_CLI_refusal_is_sanitized_and_no_source_override(self):
        for argv in (['--source', str(self.repo)], ['export', '--repository', str(self.repo),
                     '--manifest', str(self.manifest), '--output', str(self.root/'..'/'private')]):
            captured = []
            with mock.patch.object(r.os, 'write', side_effect=lambda fd, b: captured.append(b) or len(b)):
                self.assertEqual(r.main(argv), 2)
            result = json.loads(b''.join(captured)); self.assertFalse(result['ok'])
            self.assertNotIn(SECRET.encode(), b''.join(captured)); self.assertNotIn(str(self.root).encode(), b''.join(captured))

    def test_CLI_unexpected_private_exception_is_contained(self):
        captured = []
        with mock.patch.object(r, 'export', side_effect=RuntimeError(SECRET)), \
             mock.patch.object(r.os, 'write', side_effect=lambda fd,b: captured.append(b) or len(b)):
            self.assertEqual(r.main(['export','--repository',str(self.repo),'--manifest',str(self.manifest),
                                     '--output',str(self.output)]),2)
        self.assertNotIn(SECRET.encode(), b''.join(captured))
