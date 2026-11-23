"""Exercise the observer CLI with real RPC guards and a mock Keychain."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests import test_bm_test_app as helper
from tests.test_bm_test_app_keychain import FakeRunner, SENTINEL, STDERR_SENTINEL, item_bytes
from tools import bm_af3_origin as origin
from tools import bm_profile_isolation as fs
from tools import bm_test_app as host
from tools import bm_test_app_keychain as kc


@unittest.skipUnless(sys.platform == 'darwin', 'requires Darwin file metadata')
class OriginKeychainTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(dir='/private/tmp')))
        target = host.TestAppTarget(root)
        for aid in host._adapter._AF3_PACKAGES:
            target.addon_dir(aid).mkdir(parents=True)
        self.target = target
        self.interactive = Mock(return_value=SENTINEL)
        self.runner = FakeRunner(stdout=item_bytes())
        self.factory = stack.enter_context(patch.object(
            kc, 'make_keychain_password_prompt',
            side_effect=lambda: self.factory_impl(self.runner)))
        identity = SimpleNamespace(pid=8, bundle=SimpleNamespace(info_plist_sha256=origin.cache.INFO_SHA))
        stack.enter_context(patch.object(host, 'identify', return_value=identity))
        stack.enter_context(patch.object(origin, 'verify_zip', return_value='sealed'))
        self.source = [0, 0, 0, 1, 123, 20_000_000_000]
        self.tokens = stack.enter_context(patch.object(
            origin, 'source_tokens', return_value={origin.MONITOR: self.source}))
        since = time.time_ns() - 2_000_000_000
        with fs.directory(target.addons_dir) as fd:
            addons_identity = fs.identity(os.fstat(fd))
        self.baseline = root.parent / (root.name + '-baseline.json')
        self.addCleanup(self.baseline.unlink)
        raw = fs.encoded(dict(schema=1, phase='stopped_cache_free', recorded_ns=since,
                              projection_sha256='sealed', addons_identity=addons_identity,
                              sources={origin.MONITOR: self.source}))
        self.baseline.write_bytes(raw)
        self.digest = fs.digest(raw)
        pyc = target.addons_dir / origin.PYC
        pyc.parent.mkdir(parents=True)
        pyc.write_bytes(b'\xa7\r\r\n' + struct.pack('<III', 0, 20, 123) + b'mock')
        self.listeners = {8}
        self.requests = []
        self.wrong_origin = False
        services = helper.make_services(target, password_prompt=self.interactive,
            listener_lookup=lambda _: self.listeners, transport=SimpleNamespace(post=self.post))
        stack.enter_context(patch.object(host.Services, 'production', return_value=services))

    factory_impl = staticmethod(kc.make_keychain_password_prompt)

    def post(self, hostname, port, path, body, headers, timeout):
        self.assertEqual((hostname, port, path), ('127.0.0.1', 8080, '/jsonrpc'))
        request = json.loads(body)
        self.requests.append(request['method'])
        expected = 'Basic ' + base64.b64encode(('kodi:' + SENTINEL).encode()).decode()
        if headers.get('Authorization') != expected:
            return 401, b''
        if request['method'] == 'JSONRPC.Ping':
            result = 'pong'
        elif request['method'] == 'Addons.GetAddonDetails':
            aid = request['params']['addonid']
            result = {'addon': {'addonid': aid, 'version': host._adapter._AF3_PACKAGES[aid][0],
                       'enabled': True, 'broken': False,
                       'path': ('special://xbmc/addons/' if self.wrong_origin
                                else 'special://home/addons/') + aid}}
        else:
            self.assertEqual(request['method'], 'XBMC.GetInfoLabels')
            result = {origin.LABEL: 'True'}
        return 200, json.dumps(dict(jsonrpc='2.0', id=1, result=result)).encode()

    def invoke(self, *, keychain=True, pid=8, error=None):
        argv = ['observer', 'observe', '--baseline', str(self.baseline),
                '--baseline-sha256', self.digest, '--expected-pid', str(pid)]
        if keychain:
            argv.append('--keychain')
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            if error is None:
                origin.main()
            else:
                with self.assertRaises(SystemExit) as failed:
                    origin.main()
                self.assertEqual(failed.exception.code, 1)
                self.assertIn(error, stderr.getvalue())
                self.assertEqual(stdout.getvalue(), '')
        visible = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(SENTINEL, visible)
        self.assertNotIn(STDERR_SENTINEL, visible)
        return json.loads(stdout.getvalue()) if error is None else None

    def test_keychain_authenticates_and_emits_only_public_observation(self):
        result = self.invoke()
        self.assertTrue(result['authenticated'])
        self.assertEqual(len(result['registration']), 17)
        self.assertEqual(self.runner.calls[0][0], list(kc.LOOKUP_ARGV))
        self.assertEqual(len(self.runner.calls), 1)
        self.interactive.assert_not_called()

    def test_interactive_is_default(self):
        self.assertTrue(self.invoke(keychain=False)['authenticated'])
        self.interactive.assert_called_once()
        self.factory.assert_not_called()

    def test_lookup_failures_never_repeat_request_or_fall_back(self):
        for runner in (FakeRunner(returncode=44), FakeRunner(returncode=36, stdout=item_bytes()),
                       FakeRunner(stdout=item_bytes(SENTINEL + '\ninvalid')),
                       FakeRunner(raises=PermissionError(STDERR_SENTINEL))):
            with self.subTest(returncode=runner.returncode):
                self.runner = runner
                self.requests.clear()
                self.invoke(error='credential_')
                self.assertEqual(self.requests, ['JSONRPC.Ping'])
                self.interactive.assert_not_called()

    def test_wrong_pid_or_listener_refuses_before_lookup(self):
        self.invoke(pid=9, error='af3_witness_pid_changed')
        self.listeners = {9}
        self.invoke(error='listener_pid_mismatch')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.runner.calls, [])

    def test_wrong_home_or_changed_source_refuses_after_authentication(self):
        self.wrong_origin = True
        self.invoke(error='af3_witness_not_home')
        self.wrong_origin = False
        self.tokens.return_value = {}
        self.invoke(error='af3_witness_source_changed')
        self.assertEqual(len(self.runner.calls), 2)
