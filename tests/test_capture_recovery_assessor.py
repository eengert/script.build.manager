"""Synthetic read-only advisory snapshots; no Kodi/profile runtime access."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from resources.lib.capture_lifecycle import (
    CaptureLifecycleCoordinator, CapturePhase, CaptureStore, CaptureTransaction, _request_metadata,
    request_fingerprint,
)
from resources.lib.capture_recovery_assessor import (
    CaptureRecoveryAssessment, RecoveryReason as R, assess_capture_recovery,
)
from resources.lib.create_capture import CreateBuildRequest, PublicCaptureSpecification
from resources.lib.redlight_resource import REDLIGHT_ADDON_ID, REDLIGHT_VERSION, redlight_declaration


SECRET = "PRIVATE_NEVER_SERIALIZE_492"
SESSION = "11111111-1111-4111-8111-111111111111"
OPERATION = "22222222-2222-4222-8222-222222222222"
CAPTURE_SESSION = "33333333-3333-4333-8333-333333333333"


class RecoveryAssessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name)
        self.root = self.profile / "state"
        self.request = CreateBuildRequest('demo', '1.0.0', 'Demo', 'macos', 'Mac', 'desk', 'Desk',
            (REDLIGHT_ADDON_ID,), False, PublicCaptureSpecification(), 'captured',
            private_resources=(redlight_declaration(),), private_overlay_id='demo-private')
        self.request = replace(self.request, description=SECRET)
        self.record = CaptureTransaction(OPERATION, CapturePhase.AWAITING_RESTART,
            request_fingerprint(self.request), REDLIGHT_ADDON_ID, REDLIGHT_VERSION,
            True, SESSION, 1000, 2000, request_metadata=_request_metadata(self.request))
        # Expose forbidden capabilities so even a caught accidental call is visible.
        self.ops = Mock(spec_set=['owner_version', 'enabled', 'competing_operation',
                                 'set_enabled', 'restart', 'install', 'apply', 'register'])
        for name in ('set_enabled', 'restart', 'install', 'apply', 'register'):
            getattr(self.ops, name).side_effect = AssertionError('mutation')
        self.ops.owner_version.return_value = REDLIGHT_VERSION
        self.ops.enabled.return_value = False
        self.ops.competing_operation.return_value = False

    def write(self, record=None):
        self.root.mkdir(exist_ok=True)
        (self.root / 'create_capture_transaction.json').write_text(
            json.dumps((record or self.record).to_dict()))

    def snapshot(self):
        result = {}
        for path in self.profile.rglob('*'):
            info = path.lstat()
            result[str(path.relative_to(self.profile))] = (
                info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns,
                os.readlink(path) if path.is_symlink() else
                path.read_bytes() if path.is_file() else None)
        return result

    def assess(self, expected):
        before = self.snapshot()
        # Any write/open-for-write, lock or lifecycle transition is a test failure.
        original_open = os.open
        def read_only_open(path, flags, *args, **kwargs):
            self.assertFalse(flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR | os.O_TRUNC))
            return original_open(path, flags, *args, **kwargs)
        with patch('os.open', side_effect=read_only_open), \
                patch('os.mkdir', side_effect=AssertionError('directory creation')), \
                patch.object(CaptureStore, 'save', side_effect=AssertionError('state write')), \
                patch.object(CaptureStore, '_lock', side_effect=AssertionError('lock')), \
                patch.object(CaptureLifecycleCoordinator, 'begin', side_effect=AssertionError('begin')), \
                patch.object(CaptureLifecycleCoordinator, 'capture', side_effect=AssertionError('capture')), \
                patch.object(CaptureLifecycleCoordinator, 'recover', side_effect=AssertionError('recover')), \
                patch.object(CaptureLifecycleCoordinator, '_restore', side_effect=AssertionError('restore')):
            result = assess_capture_recovery(self.root, self.ops)
        self.assertEqual(result.reason, expected)
        self.assertEqual(before, self.snapshot())
        self.assertNotIn(SECRET, repr(result))
        serialized = json.dumps(result.safe_dict())
        self.assertNotIn(SECRET, serialized)
        self.assertNotIn(str(self.profile), serialized)
        self.assertEqual(set(result.safe_dict()), {'reason', 'next_step', 'advisory_only'})
        self.assertIs(result.safe_dict()['advisory_only'], True)
        self.assertTrue(all(call[0] in ('owner_version', 'enabled', 'competing_operation')
                            for call in self.ops.mock_calls))
        for call in self.ops.owner_version.call_args_list + self.ops.enabled.call_args_list:
            self.assertEqual(call.args, (REDLIGHT_ADDON_ID,))
        return result

    def test_absent_root_and_absent_record_are_only_observations(self):
        self.assess(R.NO_RECORD_OBSERVED)
        self.assertFalse(self.root.exists())
        self.root.mkdir()
        self.assess(R.NO_RECORD_OBSERVED)
        self.ops.assert_not_called()
        self.assertEqual(self.ops.mock_calls, [])

    def test_nonterminal_original_and_current_boolean_combinations(self):
        for original in (False, True):
            for current in (False, True):
                with self.subTest(original=original, current=current):
                    self.write(replace(self.record, original_enabled=original))
                    self.ops.enabled.return_value = current
                    self.assess(R.UNEXPECTED_ENABLEMENT if not original and current
                                else R.ORDINARY_RECOVERY_POTENTIAL)

    def test_all_nonterminal_phases_are_advisory_only(self):
        for phase in (CapturePhase.PREPARING, CapturePhase.AWAITING_RESTART,
                      CapturePhase.CAPTURING, CapturePhase.RESTORING):
            with self.subTest(phase=phase):
                self.write(replace(self.record, phase=phase,
                    capture_session_id=CAPTURE_SESSION if phase is CapturePhase.CAPTURING else '',
                    outcome='cancelled' if phase is CapturePhase.RESTORING else ''))
                self.assess(R.ORDINARY_RECOVERY_POTENTIAL)

    def test_terminal_records_and_mismatches(self):
        for phase in (CapturePhase.COMPLETE, CapturePhase.CANCELLED, CapturePhase.FAILED):
            for original in (False, True):
                with self.subTest(phase=phase, original=original):
                    self.write(replace(self.record, phase=phase, outcome=phase.value,
                        capture_session_id=CAPTURE_SESSION if phase is CapturePhase.COMPLETE else '',
                        original_enabled=original))
                    self.ops.enabled.return_value = original
                    self.assess(R.TERMINAL_NO_CAPTURE_HOLD)
                    self.ops.enabled.return_value = not original
                    mismatch = self.assess(R.UNEXPECTED_ENABLEMENT)
                    self.assertEqual(mismatch.safe_dict()['next_step'],
                                     'OPERATOR_ENABLEMENT_REVIEW')
                    self.assertIs(mismatch.safe_dict()['advisory_only'], True)

    def test_identity_problems_take_priority_over_d2(self):
        self.write(replace(self.record, original_enabled=False))
        self.ops.enabled.return_value = True
        for version in ('2.6.9', '', None, 268, True, SECRET):
            with self.subTest(version=version):
                self.ops.owner_version.return_value = version
                self.assess(R.OWNER_IDENTITY_UNVERIFIED)
        self.ops.owner_version.side_effect = RuntimeError(SECRET)
        self.assess(R.OWNER_IDENTITY_UNVERIFIED)
        self.ops.owner_version.side_effect = None
        self.ops.owner_version.return_value = '2.6.9'
        for original, current in ((False, True), (True, False)):
            with self.subTest(terminal_original=original, terminal_current=current):
                self.write(replace(self.record, phase=CapturePhase.COMPLETE, outcome='complete',
                    capture_session_id=CAPTURE_SESSION, original_enabled=original))
                self.ops.enabled.return_value = current
                self.assess(R.OWNER_IDENTITY_UNVERIFIED)

    def test_inconsistent_identity_and_enablement(self):
        self.write()
        self.ops.owner_version.side_effect = [REDLIGHT_VERSION, '2.6.9']
        self.assess(R.OWNER_IDENTITY_UNVERIFIED)
        self.ops.owner_version.side_effect = None
        self.ops.enabled.side_effect = [False, True]
        self.assess(R.OBSERVATIONS_UNVERIFIABLE)

    def test_unknown_enabled_and_failed_inspections(self):
        self.write()
        for value in (None, 0, 1, 'false', SECRET):
            self.ops.enabled.return_value = value
            self.assess(R.OBSERVATIONS_UNVERIFIABLE)
        self.ops.enabled.side_effect = RuntimeError(SECRET)
        self.assess(R.OBSERVATIONS_UNVERIFIABLE)
        self.ops.enabled.side_effect = None
        self.ops.enabled.return_value = False
        self.ops.competing_operation.side_effect = RuntimeError(SECRET)
        self.assess(R.OBSERVATIONS_UNVERIFIABLE)

    def test_external_competitors_require_exact_false(self):
        self.write()
        for value in (True, None, 0, 'false'):
            self.ops.competing_operation.return_value = value
            self.assess(R.OBSERVATIONS_UNVERIFIABLE)

    def test_legacy_and_corrupt_metadata(self):
        self.write(replace(self.record, request_metadata=''))
        self.assess(R.LEGACY_REQUEST_UNAVAILABLE)
        data = self.record.to_dict()
        del data['request_metadata']
        self.store_path.write_text(json.dumps(data))
        self.assess(R.LEGACY_REQUEST_UNAVAILABLE)
        self.ops.owner_version.return_value = '2.6.9'
        self.assess(R.OWNER_IDENTITY_UNVERIFIED)
        self.write()
        data = self.record.to_dict()
        data['request_metadata'] = SECRET
        self.store_path.write_text(json.dumps(data))
        self.assess(R.STATE_UNVERIFIABLE)

    @property
    def store_path(self):
        return self.root / 'create_capture_transaction.json'

    def test_malformed_missing_fields_and_unreadable(self):
        self.write()
        for data in (SECRET, '{', '{}', json.dumps({**self.record.to_dict(), 'original_enabled': 0})):
            self.store_path.write_text(data)
            self.assess(R.STATE_UNVERIFIABLE)
        self.write()
        with patch.object(CaptureStore, 'read', side_effect=PermissionError(SECRET)):
            self.assess(R.STATE_UNVERIFIABLE)

    def test_unsafe_state_file_and_final_directory_symlinks(self):
        self.root.mkdir()
        target = self.profile / 'secret-target'
        target.write_text(SECRET)
        self.store_path.symlink_to(target)
        self.assess(R.STATE_UNVERIFIABLE)
        self.store_path.unlink()
        self.store_path.mkdir()
        self.assess(R.STATE_UNVERIFIABLE)
        self.store_path.rmdir()
        self.root.rmdir()
        self.root.symlink_to(self.profile, target_is_directory=True)
        self.assess(R.PATH_UNVERIFIABLE)

    def test_trusted_profile_alias_is_not_rejected(self):
        self.write()
        alias = self.profile / 'alias'
        alias.symlink_to(self.profile, target_is_directory=True)
        self.root = alias / 'state'
        self.assess(R.ORDINARY_RECOVERY_POTENTIAL)

    def test_conflicting_record_reads(self):
        self.write()
        for reads in ([self.record, None], [None, self.record],
                      [self.record, replace(self.record, original_enabled=False)]):
            with patch.object(CaptureStore, 'read', side_effect=reads):
                self.assess(R.OBSERVATIONS_UNVERIFIABLE)

    def test_competing_durable_state(self):
        self.write()
        with patch.object(CaptureStore, 'competing_records_present', return_value=True):
            self.assess(R.OBSERVATIONS_UNVERIFIABLE)
        with patch.object(CaptureStore, 'competing_records_present', side_effect=[False, True]):
            self.assess(R.OBSERVATIONS_UNVERIFIABLE)
        # Use the accepted competing-record reader's actual filename.
        from resources.lib.transaction import TRANSACTION_FILENAME
        (self.root / TRANSACTION_FILENAME).write_text(SECRET)
        self.assess(R.STATE_UNVERIFIABLE)
        from tests.test_transaction import _transaction
        (self.root / TRANSACTION_FILENAME).write_text(_transaction().to_json())
        self.assess(R.OBSERVATIONS_UNVERIFIABLE)

    def test_fifo_oversized_and_invalid_encoding_remain_generic(self):
        self.root.mkdir()
        os.mkfifo(self.store_path)
        self.assess(R.STATE_UNVERIFIABLE)
        self.store_path.unlink()
        self.store_path.write_bytes(b'x' * (16 * 1024 + 1))
        self.assess(R.STATE_UNVERIFIABLE)
        self.store_path.write_bytes(b'\xff\xfe')
        self.assess(R.STATE_UNVERIFIABLE)

    def test_path_failure_after_construction_cannot_be_subtyped(self):
        self.write()
        with patch.object(CaptureStore, '_validate_directory', side_effect=OSError(SECRET)):
            self.assess(R.STATE_UNVERIFIABLE)

    def test_competing_state_prioritized_over_identity_and_enablement(self):
        self.write(replace(self.record, original_enabled=False))
        self.ops.owner_version.return_value = '2.6.9'
        self.ops.enabled.return_value = True
        self.ops.competing_operation.return_value = True
        self.assess(R.OBSERVATIONS_UNVERIFIABLE)

    def test_inconsistent_external_inspection(self):
        self.write()
        self.ops.competing_operation.side_effect = [False, True]
        self.assess(R.OBSERVATIONS_UNVERIFIABLE)

    def test_no_runtime_composition(self):
        from resources.lib.create_workflow import runtime_create_workflow
        from resources.lib.startup import run_startup
        self.assertNotIn('assess_capture_recovery', runtime_create_workflow.__code__.co_names)
        self.assertNotIn('assess_capture_recovery', run_startup.__code__.co_names)

    def test_result_rejects_arbitrary_diagnostic_text(self):
        with self.assertRaises(ValueError) as caught:
            CaptureRecoveryAssessment(SECRET)
        self.assertNotIn(SECRET, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
