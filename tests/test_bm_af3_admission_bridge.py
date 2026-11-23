"""Offline adversarial checks for the two AF3 admission procedures."""
import os
from pathlib import Path
import time
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import bm_af3_adapter_stage as stage
from tools import bm_af3_origin as origin
from tools import bm_profile_isolation as fs
from tools import bm_test_app as host


class OriginTests(unittest.TestCase):
    def test_only_pinned_home_locations_are_accepted(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as folder:
            target = host.TestAppTarget(Path(folder))
            for aid in host._adapter._AF3_PACKAGES:
                target.addon_dir(aid).mkdir(parents=True)

            def reply(method, parameters):
                self.assertEqual(method, 'Addons.GetAddonDetails')
                aid = parameters['addonid']
                return {'addon': {'addonid': aid, 'version': host._adapter._AF3_PACKAGES[aid][0],
                                  'enabled': True, 'broken': False, 'path': spelling(aid)}}

            client = SimpleNamespace(call=reply)
            for spelling in (lambda aid: str(target.addon_dir(aid)),
                             lambda aid: '/System/Volumes/Data' + str(target.addon_dir(aid)) + '/',
                             lambda aid: 'special://home/addons/' + aid):
                self.assertEqual(len(origin.home_registration(client, target)), 17)
            for spelling in (lambda aid: 'special://xbmc/addons/' + aid,
                             lambda aid: 'special://home/addons/../addons/' + aid,
                             lambda aid: str(target.addon_dir(aid)) + '/unexpected'):
                with self.assertRaisesRegex(fs.Refusal, 'af3_witness_not_home'):
                    origin.home_registration(client, target)
            first = next(iter(host._adapter._AF3_PACKAGES))
            target.addon_dir(first).rmdir()
            target.addon_dir(first).symlink_to(target.addons_dir)
            spelling = lambda aid: 'special://home/addons/' + aid
            with self.assertRaises(OSError):
                origin.home_registration(client, target)

    def test_cache_format_source_and_freshness_are_required(self):
        source = [0, 0, 0, 1, 123, 20_000_000_010]
        row = [0, 0, 0, 1, 17, 31_000_000_000, 31_000_000_000, 0, 0, 0, 31.0]
        valid = b'\xa7\r\r\n' + struct.pack('<III', 0, 20, 123) + b'body'
        self.assertEqual(origin.cache_witness(valid, row, source, 30_000_000_000, 32_000_000_000),
                         fs.digest(valid))
        for bad, expected in ((b'bad!' + valid[4:], 'format'),
                              (valid[:4] + struct.pack('<III', 0, 21, 123) + b'body', 'header'),
                              (valid[:4] + struct.pack('<III', 3, 20, 123) + b'body', 'header')):
            with self.assertRaisesRegex(fs.Refusal, expected):
                origin.cache_witness(bad, row, source, 30_000_000_000, 32_000_000_000)
        with self.assertRaisesRegex(fs.Refusal, 'not_fresh'):
            origin.cache_witness(valid, row, source, 31_500_000_000, 32_000_000_000)

    def test_runtime_marker_and_auth_are_required(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as folder:
            target = host.TestAppTarget(Path(folder))
            target.addons_dir.mkdir(parents=True)
            with fs.directory(target.addons_dir) as fd:
                root_identity = fs.identity(os.fstat(fd))
            baseline = {'schema': 1, 'phase': 'stopped_cache_free', 'recorded_ns': 1,
                        'projection_sha256': 'sealed', 'addons_identity': root_identity}
            client = SimpleNamespace(authenticated=False, call=lambda *_: 'pong')
            with patch.object(origin, 'identify', return_value=SimpleNamespace(pid=8)), \
                 patch.object(origin, 'verify_zip', return_value='sealed'), \
                 patch.object(origin, 'home_registration', return_value={}), \
                 patch.object(host, 'RpcClient', return_value=client):
                with self.assertRaisesRegex(fs.Refusal, 'pid_changed'):
                    origin.observe(SimpleNamespace(target=target), None, baseline, 9)
                with self.assertRaisesRegex(fs.Refusal, 'not_authenticated'):
                    origin.observe(SimpleNamespace(target=target), None, baseline, 8)
                client.authenticated = True
                client.call = lambda method, _: 'pong' if method == 'JSONRPC.Ping' else {origin.LABEL: ''}
                with self.assertRaisesRegex(fs.Refusal, 'startup_marker_missing'):
                    origin.observe(SimpleNamespace(target=target), None, baseline, 8)

    @unittest.skipUnless(sys.platform == 'darwin', 'requires Darwin file metadata')
    def test_complete_mock_receipt_is_limited_to_one_source_chain(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as folder:
            target = host.TestAppTarget(Path(folder))
            target.addons_dir.mkdir(parents=True)
            since = time.time_ns() - 2_000_000_000
            with fs.directory(target.addons_dir) as fd:
                root_identity = fs.identity(os.fstat(fd))
            source = [0, 0, 0, 1, 123, 20_000_000_000]
            mounted = {origin.MONITOR: source}
            baseline = {'schema': 1, 'phase': 'stopped_cache_free', 'recorded_ns': since,
                        'projection_sha256': 'sealed', 'addons_identity': root_identity,
                        'sources': mounted}
            pyc = target.addons_dir / origin.PYC
            pyc.parent.mkdir(parents=True)
            raw = b'\xa7\r\r\n' + struct.pack('<III', 0, 20, 123) + b'mock'
            pyc.write_bytes(raw)
            client = SimpleNamespace(authenticated=True, call=lambda method, _: (
                'pong' if method == 'JSONRPC.Ping' else {origin.LABEL: 'True'}))
            with patch.object(origin, 'identify', return_value=SimpleNamespace(pid=8)), \
                 patch.object(origin, 'verify_zip', return_value='sealed'), \
                 patch.object(origin, 'home_registration', return_value={}), \
                 patch.object(origin, 'source_tokens', return_value=mounted), \
                 patch.object(host, 'RpcClient', return_value=client):
                result = origin.observe(SimpleNamespace(target=target), fs.Native(), baseline, 8)
                self.assertEqual(result['scope'], 'tmdb_helper_monitor_initialization_only')
                self.assertEqual(result['fresh_monitor_cache_sha256'], fs.digest(raw))
                self.assertNotIn('qualification', result)


@unittest.skipUnless(sys.platform == 'darwin', 'requires Darwin atomic exchange')
class StageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        self.target = host.TestAppTarget(Path(temporary.name))
        self.driver = self.target.addon_dir(host.DRIVER_ID)
        self.driver.mkdir(parents=True)
        self.live = self.driver / stage.CONFIG
        self.area = self.target.portable_data / stage.AREA
        self.live.write_bytes(b'original config')
        self.live.chmod(0o640)
        self.inode = self.live.stat().st_ino
        self.native = fs.Native()
        self.other = self.driver / 'default.py'
        self.other.write_bytes(b'unchanged')
        self.running = False

    def stopped(self):
        fs.need(not self.running, 'fixture_running')

    def verify(self, state):
        fs.need(self.other.read_bytes() == b'unchanged', 'fixture_source_mismatch')
        self.assertEqual(self.live.read_bytes(), (b'original config' if state == 'original'
                                                 else b'candidate config'))
        return state

    def operate(self, action, **changes):
        args = dict(original_sha=fs.digest(b'original config'),
                    candidate_sha=fs.digest(b'candidate config'), stopped=self.stopped,
                    verify=self.verify, native=self.native)
        args.update(changes)
        return stage.transact(self.target, action, b'candidate config', **args)

    def test_atomic_stage_rollback_and_repeat(self):
        self.assertEqual(self.operate('stage')['status'], 'staged')
        self.assertEqual((self.area / stage.SLOT).read_bytes(), b'original config')
        self.assertEqual((self.area / stage.SLOT).stat().st_ino, self.inode)
        self.assertFalse(self.operate('stage')['changed'])
        self.assertEqual(self.operate('restore')['status'], 'restored')
        self.assertEqual(self.live.stat().st_ino, self.inode)
        self.assertEqual(self.live.stat().st_mode & 0o777, 0o640)
        self.assertFalse(self.operate('restore')['changed'])

    def test_recovers_interruption_after_exchange_in_both_directions(self):
        def interrupted(*args):
            stage.exchange(*args)
            raise KeyboardInterrupt

        for action, expected in (('stage', 'staged'), ('restore', 'restored')):
            with self.assertRaises(KeyboardInterrupt):
                self.operate(action, swap=interrupted)
            result = self.operate(action)
            self.assertEqual(result['status'], expected)
            self.assertFalse(result['changed'])

    def test_running_wrong_target_and_mismatched_source_refuse(self):
        self.running = True
        with self.assertRaisesRegex(fs.Refusal, 'fixture_running'):
            self.operate('stage')
        self.running = False
        self.other.write_bytes(b'mismatch')
        with self.assertRaisesRegex(fs.Refusal, 'fixture_source_mismatch'):
            self.operate('stage')
        self.assertFalse(self.area.exists())
        with patch.object(host.Services, 'production', return_value=SimpleNamespace(target=self.target)):
            with self.assertRaisesRegex(fs.Refusal, 'wrong_target'):
                stage.run('stage')

    def test_byte_identical_replacement_and_symlink_refuse_restore(self):
        self.operate('stage')
        slot = self.area / stage.SLOT
        displaced = self.area / 'independent-copy'
        self.live.rename(displaced)
        self.live.write_bytes(displaced.read_bytes())
        with self.assertRaisesRegex(fs.Refusal, 'transaction_collision'):
            self.operate('restore')
        self.live.unlink()
        self.live.symlink_to(displaced)
        with self.assertRaises(OSError):
            self.operate('restore')
        self.assertEqual(slot.read_bytes(), b'original config')
        self.assertEqual(displaced.read_bytes(), b'candidate config')

    def test_collision_and_partial_slot_preserve_everything(self):
        self.area.mkdir(mode=0o700)
        slot = self.area / stage.SLOT
        slot.write_bytes(b'partial')
        with self.assertRaisesRegex(fs.Refusal, 'candidate_slot_mismatch'):
            self.operate('stage')
        self.assertEqual(slot.read_bytes(), b'partial')
        self.assertEqual(self.live.read_bytes(), b'original config')
        slot.unlink()
        self.operate('stage')
        self.live.write_bytes(b'unexpected')
        with self.assertRaisesRegex(fs.Refusal, 'installed_config_mismatch'):
            self.operate('restore')
        self.assertEqual(slot.read_bytes(), b'original config')
        self.assertEqual(self.live.read_bytes(), b'unexpected')


@unittest.skipUnless(sys.platform == 'darwin', 'requires Darwin atomic exchange')
class ExactStageTests(unittest.TestCase):
    def test_release_pair_and_launch_admission_round_trip(self):
        import json
        from tests import test_af3_zip_binding as fixture

        world = fixture.ExactZipBindingTests()
        world.setUpClass()
        self.addCleanup(world.doCleanups)
        world.setUp()
        stage_manifest = world.stage
        old_hashes = {row['path']: row['sha256'] for row in stage_manifest['build_manager']['files']}
        new_binding = host._parse_adapter_config(world.config)['PLATFORM_SOURCE_BINDING']
        old_binding = host._adapter.platform_source_binding(
            old_hashes, json.loads(new_binding)['adapter'], host._AF3_ZIP_COMMIT,
            host._adapter._AF3_MANIFEST_SHA)
        original = world.config.replace(repr(new_binding).encode('ascii'), repr(old_binding).encode('ascii'))
        self.assertEqual(fs.digest(original), stage.ORIGINAL)
        config = world.driver / stage.CONFIG
        config.write_bytes(original)
        inode = config.stat().st_ino

        def stopped():
            self.assertEqual(host.identify(world.services, require='not_running').state, 'not_running')

        for action, tree in (('stage', stage.CANDIDATE_TREE), ('restore', host._AF3_ZIP_PRIOR_DRIVER_TREE)):
            result = stage.transact(
                world.target, action, world.config, original_sha=stage.ORIGINAL,
                candidate_sha=stage.CANDIDATE, stopped=stopped, native=fs.Native(),
                verify=lambda state: stage.verify_installation(world.services, state, world.config))
            self.assertEqual(result['verification']['adapter_tree_sha256'], tree)
            self.assertEqual(result['verification']['product_tree_sha256'], host._AF3_ZIP_TREE)
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(config.stat().st_ino, inode)
