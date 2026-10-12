"""Synthetic creation-free record observations; no Kodi or recovery advice."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, PropertyMock

from resources.lib.capture_lifecycle import CaptureStore, CaptureTransaction, CapturePhase
from resources.lib.create_status import observe_create_state
from resources.lib.status import default_status_owners
from resources.lib.status_model import CreateObservation as C
from resources.lib.redlight_resource import REDLIGHT_ADDON_ID, REDLIGHT_VERSION

OPERATION = '22222222-2222-4222-8222-222222222222'
SESSION = '11111111-1111-4111-8111-111111111111'
FINGERPRINT = 'sha256:' + 'a' * 64


class CreateRecordObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name)
        self.root = self.profile / 'addon_data' / 'script.build.manager'
        self.record = CaptureTransaction(OPERATION, CapturePhase.AWAITING_RESTART,
            FINGERPRINT, REDLIGHT_ADDON_ID, REDLIGHT_VERSION, False, SESSION, 1000, 2000)

    def write(self, record):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'create_capture_transaction.json').write_text(json.dumps(record.to_dict()))

    def snapshot(self):
        return {str(p.relative_to(self.profile)): (p.lstat().st_ino, p.lstat().st_mtime_ns,
                 p.read_bytes() if p.is_file() else None) for p in self.profile.rglob('*')}

    def observe(self):
        before = self.snapshot()
        flags_seen = []
        original_open = os.open
        def opened(path, flags, *a, **kw):
            flags_seen.append(flags)
            return original_open(path, flags, *a, **kw)
        with patch('os.open', side_effect=opened), \
             patch('os.mkdir', side_effect=AssertionError('mkdir')) as mkdir, \
             patch.object(CaptureStore, '_lock', side_effect=AssertionError('lock')) as lock, \
             patch.object(CaptureStore, 'save', side_effect=AssertionError('write')) as save:
            result = observe_create_state(self.root)
        mkdir.assert_not_called()
        lock.assert_not_called()
        save.assert_not_called()
        self.assertFalse(any(f & (os.O_CREAT | os.O_WRONLY | os.O_RDWR | os.O_TRUNC)
                             for f in flags_seen))
        self.assertEqual(before, self.snapshot())
        for private in (str(self.profile), OPERATION, SESSION, FINGERPRINT):
            self.assertNotIn(private, repr(result))
        return result

    def test_missing_directories_stay_missing(self):
        self.assertEqual(self.observe(), C.NO_RECORD_OBSERVED)
        self.assertFalse(self.root.exists())

    def test_existing_empty_directory_is_unchanged(self):
        self.root.mkdir(parents=True)
        self.assertEqual(self.observe(), C.NO_RECORD_OBSERVED)

    def test_hold_pending_release_and_fresh_reads(self):
        self.write(self.record)
        self.assertEqual(self.observe(), C.HELD)
        for phase, outcome in ((CapturePhase.COMPLETE, 'complete'),
                               (CapturePhase.FAILED, 'failed'),
                               (CapturePhase.CANCELLED, 'cancelled')):
            terminal = replace(self.record, phase=phase, outcome=outcome, commit_pending=True,
                               capture_session_id='33333333-3333-4333-8333-333333333333')
            self.write(terminal)
            self.assertEqual(self.observe(), C.TERMINAL_PENDING)
            self.write(replace(terminal, commit_pending=False))
            self.assertEqual(self.observe(), C.TERMINAL_RELEASED)

    def test_malformed_and_unreadable_are_unknown(self):
        self.root.mkdir(parents=True)
        path = self.root / 'create_capture_transaction.json'
        for raw in ('not json SECRET/path', '{}', json.dumps(dict(self.record.to_dict(), commit_pending='True'))):
            path.write_text(raw)
            self.assertEqual(self.observe(), C.UNVERIFIABLE)
        path.unlink()
        path.mkdir()
        self.assertEqual(self.observe(), C.UNVERIFIABLE)

    def test_symlink_record_is_not_followed(self):
        self.root.mkdir(parents=True)
        target = self.profile / 'private'
        target.write_text('SECRET')
        (self.root / 'create_capture_transaction.json').symlink_to(target)
        self.assertEqual(self.observe(), C.UNVERIFIABLE)
        self.assertEqual(target.read_text(), 'SECRET')

    def test_disagreeing_reads_are_unknown(self):
        for first, second in ((None, self.record), (self.record, None),
                              (self.record, replace(self.record, expires_at=3000))):
            with patch.object(CaptureStore, 'read', side_effect=[first, second]):
                self.assertEqual(observe_create_state(self.root), C.UNVERIFIABLE)

    def test_exception_text_does_not_escape(self):
        with patch.object(CaptureStore, 'read', side_effect=RuntimeError('SECRET/private/profile')):
            self.assertEqual(observe_create_state(self.root), C.UNVERIFIABLE)

    def test_production_observer_is_lazy_and_uses_canonical_directory(self):
        with patch('resources.lib.create_status.observe_create_state') as observe, \
             patch('resources.lib.status._runtime_profile_root', side_effect=AssertionError('live')):
            owners = default_status_owners()
            observe.assert_not_called()
        self.write(self.record)
        with patch('resources.lib.transaction.TransactionStore.profile_directory',
                   new_callable=PropertyMock,
                   return_value=str(self.profile)):
            self.assertEqual(owners.create_observer(), C.HELD)

    def test_adapter_reaches_only_accepted_read_capabilities(self):
        import ast
        tree = ast.parse((Path(__file__).parents[1] / 'resources/lib/create_status.py').read_text())
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertEqual(calls, {'read'})
        names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                 for alias in node.names}
        self.assertNotIn('CaptureLifecycleCoordinator', names)
