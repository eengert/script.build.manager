"""Offline namespace/classifier evidence, not production startup execution."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from resources.lib.capture_lifecycle import CapturePhase, CaptureStore, CaptureTransaction
from resources.lib.create_status import observe_create_state
from resources.lib.status_model import CreateObservation as C
from resources.lib.startup import classify_startup_transaction, StartupClassification
from resources.lib.transaction import TransactionStore, TransactionError
from resources.lib.redlight_resource import REDLIGHT_ADDON_ID, REDLIGHT_VERSION


def record():
    return CaptureTransaction('22222222-2222-4222-8222-222222222222',
        CapturePhase.AWAITING_RESTART, 'sha256:' + 'a'*64,
        REDLIGHT_ADDON_ID, REDLIGHT_VERSION, False,
        '11111111-1111-4111-8111-111111111111', 1000, 2000)


class ReadOnlyRestartView:
    """Inject the supported read_snapshot capability; never call locked inspect."""
    def __init__(self, profile):
        self.store = TransactionStore(str(profile))

    def inspect(self):
        return self.store.read_snapshot()


class StartupIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name)
        self.root = self.profile / 'addon_data/script.build.manager'

    def write(self, raw):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'create_capture_transaction.json').write_text(json.dumps(raw))

    def snapshot(self):
        return {str(p.relative_to(self.profile)): (p.stat().st_mtime_ns,
                p.read_bytes() if p.is_file() else None) for p in self.profile.rglob('*')}

    def observe(self, expected):
        before = self.snapshot()
        opened = os.open
        def read_only(path, flags, *args, **kwargs):
            self.assertFalse(flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR | os.O_TRUNC))
            return opened(path, flags, *args, **kwargs)
        with patch('os.open', side_effect=read_only), \
                patch('os.mkdir', side_effect=AssertionError('creation')), \
                patch.object(CaptureStore, '_lock', side_effect=AssertionError('lock')), \
                patch.object(CaptureStore, 'save', side_effect=AssertionError('mutation')), \
                patch.object(TransactionStore, 'inspect', side_effect=AssertionError('locked inspection')):
            self.assertEqual(observe_create_state(self.root), expected)
            status = classify_startup_transaction('new-session', store=ReadOnlyRestartView(self.profile))
            self.assertIs(status.classification, StartupClassification.NO_TRANSACTION)
            self.assertFalse(status.eligible_for_resume)
        self.assertEqual(before, self.snapshot())

    def test_all_held_and_terminal_phases_stay_out_of_restart_resume(self):
        base = record()
        for phase in (CapturePhase.PREPARING, CapturePhase.AWAITING_RESTART,
                      CapturePhase.CAPTURING, CapturePhase.RESTORING):
            self.write(replace(base, phase=phase, outcome='cancelled' if phase is CapturePhase.RESTORING else '',
                capture_session_id='33333333-3333-4333-8333-333333333333' if phase is CapturePhase.CAPTURING else '').to_dict())
            self.observe(C.HELD)
        for phase, outcome in ((CapturePhase.COMPLETE, 'complete'),
                               (CapturePhase.FAILED, 'failed'), (CapturePhase.CANCELLED, 'cancelled')):
            for pending in (True, False):
                self.write(replace(base, phase=phase, outcome=outcome, commit_pending=pending,
                    capture_session_id='33333333-3333-4333-8333-333333333333').to_dict())
                self.observe(C.TERMINAL_PENDING if pending else C.TERMINAL_RELEASED)

    def test_invalid_create_requires_attention_without_becoming_restart(self):
        self.write({'private': 'SECRET/private/path', 'phase': 'awaiting_restart'})
        self.observe(C.UNVERIFIABLE)

    def test_absence_means_only_no_record_observed(self):
        self.observe(C.NO_RECORD_OBSERVED)
        self.assertFalse(self.root.exists())

    def test_create_payload_under_restart_filename_is_rejected(self):
        self.write(record().to_dict())
        (self.root / 'restart_transaction.json').write_text(json.dumps(record().to_dict()))
        before = self.snapshot()
        with self.assertRaises(TransactionError):
            ReadOnlyRestartView(self.profile).inspect()
        status = classify_startup_transaction('new-session', store=ReadOnlyRestartView(self.profile))
        self.assertIs(status.classification, StartupClassification.INVALID_TRANSACTION)
        self.assertFalse(status.eligible_for_resume)
        self.assertEqual(before, self.snapshot())
