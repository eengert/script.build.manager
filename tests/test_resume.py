import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resources.lib.build_manager import ReconcileRequest, ReconcileResult
from resources.lib.restart import RestartReport, RestartRequirement
from resources.lib.resume import ResumeCoordinator, ResumeOutcome, ResumeResult
from resources.lib.startup import StartupClassification, run_startup
from resources.lib.transaction import (
    RestartTransaction,
    TransactionPhase,
    TransactionStore,
)


FINGERPRINT = "sha256:" + "d" * 64
OTHER_FINGERPRINT = "sha256:" + "e" * 64
SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"


def _request() -> ReconcileRequest:
    return ReconcileRequest("/safe/build.json", "disposable")


def _result(*, success=True, fingerprint=FINGERPRINT, requirement=RestartRequirement.NONE):
    return ReconcileResult(
        success=success,
        request=_request(),
        desired_fingerprint=fingerprint,
        restart_report=RestartReport(requirement, 1 if requirement is not RestartRequirement.NONE else 0, 0 if success else 1),
    )


def _transaction(*, phase=TransactionPhase.AWAITING_RESTART, fingerprint=FINGERPRINT):
    return RestartTransaction(
        transaction_id="33333333-3333-4333-8333-333333333333",
        phase=phase,
        request=_request(),
        desired_state_fingerprint=fingerprint,
        restart_requirement=RestartRequirement.KODI_RESTART,
        originating_kodi_session_id=SESSION_A,
        created_at="2026-09-21T12:00:00+00:00",
        updated_at="2026-09-21T12:00:00+00:00",
    )


class _Manager:
    def __init__(self, preview=None, reconcile=None):
        self.preview_result = preview or _result()
        self.reconcile_result = reconcile or _result()
        self.preview_calls = []
        self.reconcile_calls = []
        self.preview_hook = None

    def preview(self, request):
        self.preview_calls.append(request)
        if self.preview_hook:
            self.preview_hook()
        return self.preview_result

    def reconcile(self, request):
        self.reconcile_calls.append(request)
        return self.reconcile_result


class _StartupResume:
    def __init__(self):
        self.calls = []

    def resume(self, transaction, *, current_session_id):
        self.calls.append((transaction, current_session_id))
        return ResumeResult(ResumeOutcome.COMPLETED)


class ResumeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TransactionStore(self.tmp.name)
        self.store.create(_transaction())
        self.manager = _Manager()

    def tearDown(self):
        self.tmp.cleanup()

    def _coordinator(self, manager=None, session=SESSION_B):
        return ResumeCoordinator(
            manager or self.manager,
            store=self.store,
            session_id_provider=lambda: session,
        )

    def test_matching_preview_claims_resumes_from_beginning_and_clears(self):
        result = self._coordinator().resume(self.store.inspect())
        self.assertEqual(result.outcome, ResumeOutcome.COMPLETED)
        self.assertEqual(self.manager.preview_calls, [_request()])
        self.assertEqual(self.manager.reconcile_calls, [_request()])
        self.assertIsNone(self.store.inspect())

    def test_same_session_never_previews_or_reconciles(self):
        result = self._coordinator(session=SESSION_A).resume(self.store.inspect())
        self.assertEqual(result.failure.code, "SAME_SESSION")
        self.assertEqual(self.manager.preview_calls, [])
        self.assertEqual(self.manager.reconcile_calls, [])
        self.assertEqual(self.store.inspect().phase, TransactionPhase.AWAITING_RESTART)

    def test_preview_mismatch_enters_attention_without_reconcile(self):
        self.manager.preview_result = _result(fingerprint=OTHER_FINGERPRINT)
        result = self._coordinator().resume(self.store.inspect())
        self.assertEqual(result.outcome, ResumeOutcome.NEEDS_ATTENTION)
        self.assertEqual(result.failure.code, "FINGERPRINT_MISMATCH")
        self.assertEqual(self.manager.reconcile_calls, [])
        current = self.store.inspect()
        self.assertEqual(current.phase, TransactionPhase.NEEDS_ATTENTION)
        self.assertEqual(current.status_code, "FINGERPRINT_MISMATCH")

    def test_preview_failure_enters_attention_without_reconcile(self):
        self.manager.preview_result = _result(success=False)
        result = self._coordinator().resume(self.store.inspect())
        self.assertEqual(result.failure.code, "PREVIEW_FAILED")
        self.assertEqual(self.manager.reconcile_calls, [])
        self.assertEqual(self.store.inspect().phase, TransactionPhase.NEEDS_ATTENTION)

    def test_stale_transaction_id_cannot_be_claimed(self):
        stale = _transaction()
        stale = RestartTransaction(
            transaction_id="44444444-4444-4444-8444-444444444444",
            phase=stale.phase,
            request=stale.request,
            desired_state_fingerprint=stale.desired_state_fingerprint,
            restart_requirement=stale.restart_requirement,
            originating_kodi_session_id=stale.originating_kodi_session_id,
            created_at=stale.created_at,
            updated_at=stale.updated_at,
        )
        result = self._coordinator().resume(stale)
        self.assertEqual(result.failure.code, "TRANSACTION_ID_MISMATCH")
        self.assertEqual(self.manager.reconcile_calls, [])
        self.assertEqual(self.store.inspect().phase, TransactionPhase.AWAITING_RESTART)

    def test_concurrent_change_between_preview_and_claim_fails_closed(self):
        def change_state():
            self.store.transition_expected(
                transaction_id=self.store.inspect().transaction_id,
                expected_phase=TransactionPhase.AWAITING_RESTART,
                new_phase=TransactionPhase.NEEDS_ATTENTION,
                status_code="TEST_CONCURRENT_CHANGE",
                status_message="test state changed",
            )

        self.manager.preview_hook = change_state
        result = self._coordinator().resume(self.store.inspect())
        self.assertEqual(result.failure.code, "RESUME_CLAIM_CONFLICT")
        self.assertEqual(self.manager.reconcile_calls, [])
        self.assertEqual(self.store.inspect().status_code, "TEST_CONCURRENT_CHANGE")

    def test_final_fingerprint_change_is_preserved_for_recovery(self):
        self.manager.reconcile_result = _result(fingerprint=OTHER_FINGERPRINT)
        result = self._coordinator().resume(self.store.inspect())
        self.assertEqual(result.failure.code, "FINAL_FINGERPRINT_MISMATCH")
        self.assertEqual(self.store.inspect().phase, TransactionPhase.NEEDS_ATTENTION)

    def test_restart_requirement_after_resume_does_not_create_new_handoff(self):
        self.manager.reconcile_result = _result(requirement=RestartRequirement.KODI_RESTART)
        result = self._coordinator().resume(self.store.inspect())
        self.assertEqual(result.failure.code, "RESTART_REQUIRED_AFTER_RESUME")
        current = self.store.inspect()
        self.assertEqual(current.phase, TransactionPhase.NEEDS_ATTENTION)
        self.assertEqual(current.transaction_id, "33333333-3333-4333-8333-333333333333")

    def test_reconcile_failure_preserves_transaction_for_explicit_recovery(self):
        self.manager.reconcile_result = _result(success=False)
        result = self._coordinator().resume(self.store.inspect())
        self.assertEqual(result.outcome, ResumeOutcome.NEEDS_ATTENTION)
        self.assertEqual(self.store.inspect().phase, TransactionPhase.NEEDS_ATTENTION)
        self.assertTrue(Path(self.store.transaction_path).exists())

    def test_resuming_transaction_is_not_retried_on_startup(self):
        self.store.update_phase(TransactionPhase.RESUMING)
        with patch("resources.lib.startup.get_current_kodi_session_id", return_value=SESSION_B):
            status = run_startup(
                store=self.store,
                resume_coordinator=self._coordinator(),
            )
        self.assertEqual(status.classification, StartupClassification.NEEDS_ATTENTION)
        self.assertEqual(self.manager.reconcile_calls, [])

    def test_ready_startup_invokes_only_the_resume_coordinator(self):
        coordinator = _StartupResume()
        with patch("resources.lib.startup.get_current_kodi_session_id", return_value=SESSION_B):
            status = run_startup(
                store=self.store,
                resume_coordinator=coordinator,
            )
        self.assertEqual(status.classification, StartupClassification.NO_TRANSACTION)
        self.assertEqual(len(coordinator.calls), 1)
        self.assertEqual(coordinator.calls[0][1], SESSION_B)

    def test_needs_attention_startup_does_not_mutate(self):
        self.store.transition_expected(
            transaction_id=self.store.inspect().transaction_id,
            expected_phase=TransactionPhase.AWAITING_RESTART,
            new_phase=TransactionPhase.NEEDS_ATTENTION,
            status_code="TEST_FAILURE",
            status_message="safe reason",
        )
        with patch("resources.lib.startup.get_current_kodi_session_id", return_value=SESSION_B):
            status = run_startup(
                store=self.store,
                resume_coordinator=self._coordinator(),
            )
        self.assertEqual(status.classification, StartupClassification.NEEDS_ATTENTION)
        self.assertEqual(self.manager.reconcile_calls, [])
        self.assertEqual(self.store.inspect().status_message, "safe reason")

    def test_explicit_clear_remains_available(self):
        self.store.update_phase(TransactionPhase.NEEDS_ATTENTION)
        self.assertTrue(self.store.clear())
        self.assertIsNone(self.store.inspect())

    def test_failure_diagnostics_are_bounded_and_secret_safe(self):
        self.manager.preview_result = ReconcileResult(
            success=False,
            request=_request(),
            desired_fingerprint=FINGERPRINT,
            failure=type("Failure", (), {"code": "PREFLIGHT_FAILED", "message": "token=password"})(),
        )
        result = self._coordinator().resume(self.store.inspect())
        self.assertEqual(result.failure.code, "PREVIEW_FAILED")
        raw = self.store.transaction_path
        text = Path(raw).read_text(encoding="utf-8")
        self.assertNotIn("token=password", text)
        self.assertLessEqual(len(self.store.inspect().status_message), 512)


if __name__ == "__main__":
    unittest.main()
