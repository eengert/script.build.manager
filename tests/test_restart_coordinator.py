import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from resources.lib.build_manager import ReconcileRequest, ReconcileResult
from resources.lib.restart import RestartReport, RestartRequirement
from resources.lib.restart_coordinator import (
    RestartCapability,
    RestartCapabilityResolver,
    RestartCoordinator,
    RestartOutcome,
)
from resources.lib.startup import StartupClassification, classify_startup_transaction
from resources.lib.transaction import TransactionPhase, TransactionStore


FINGERPRINT = "sha256:" + "c" * 64
SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"


def _request() -> ReconcileRequest:
    return ReconcileRequest("/safe/build.json", "family-room")


def _result(*, success=True, requirement=RestartRequirement.KODI_RESTART):
    return ReconcileResult(
        success=success,
        request=_request(),
        desired_fingerprint=FINGERPRINT,
        restart_report=RestartReport(
            requirement,
            1 if success and requirement is not RestartRequirement.NONE else 0,
            0 if success else 1,
        ),
    )


class _Manager:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def reconcile(self, request):
        self.calls.append(request)
        return self.result


class CoordinatorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TransactionStore(self.tmp.name)
        self.manager = _Manager(_result())
        self.capability = RestartCapabilityResolver(platform_id="macos")
        self.restart_adapter = Mock()

    def tearDown(self):
        self.tmp.cleanup()

    def _coordinator(self, manager=None, capability=None):
        return RestartCoordinator(
            manager or self.manager,
            capability_resolver=capability or self.capability,
            session_id_provider=lambda: SESSION_A,
            store=self.store,
        )

    def test_current_platforms_resolve_to_manual(self):
        for platform_id in ("macos", "android", "shield", "fire_os", "tvos"):
            self.assertEqual(
                RestartCapabilityResolver(platform_id=platform_id).resolve(),
                RestartCapability.MANUAL_APP_RESTART_REQUIRED,
            )

    def test_aliases_and_unknown_platforms_are_conservative(self):
        self.assertEqual(
            RestartCapabilityResolver(platform_id="darwin").resolve(),
            RestartCapability.MANUAL_APP_RESTART_REQUIRED,
        )
        self.assertEqual(
            RestartCapabilityResolver(platform_id="unproven-platform").resolve(),
            RestartCapability.MANUAL_APP_RESTART_REQUIRED,
        )

    def test_capability_resolver_is_injectable(self):
        resolver = Mock()
        resolver.resolve.return_value = RestartCapability.MANUAL_APP_RESTART_REQUIRED
        result = self._coordinator(capability=resolver).handle_result(_request(), _result())
        self.assertEqual(result.outcome, RestartOutcome.MANUAL_RESTART_REQUIRED)
        resolver.resolve.assert_called_once_with()

    def test_success_none_is_complete_without_transaction(self):
        manager = _Manager(_result(requirement=RestartRequirement.NONE))
        result = self._coordinator(manager).reconcile(_request())
        self.assertEqual(result.outcome, RestartOutcome.COMPLETE)
        self.assertIsNone(self.store.inspect())

    def test_failed_restart_requirement_never_prepares_transaction(self):
        manager = _Manager(_result(success=False))
        result = self._coordinator(manager).reconcile(_request())
        self.assertEqual(result.outcome, RestartOutcome.FAILED)
        self.assertIsNone(self.store.inspect())

    def test_manual_restart_persists_transaction_without_adapter(self):
        result = self._coordinator().reconcile(_request())
        self.assertEqual(result.outcome, RestartOutcome.MANUAL_RESTART_REQUIRED)
        self.assertEqual(result.capability, RestartCapability.MANUAL_APP_RESTART_REQUIRED)
        self.assertEqual(result.message, "Restart Kodi completely to continue.")
        self.assertEqual(result.transaction.restart_attempt_count, 0)
        self.assertEqual(self.store.inspect(), result.transaction)
        self.restart_adapter.assert_not_called()

    def test_repeated_same_session_call_reuses_transaction(self):
        coordinator = self._coordinator()
        first = coordinator.reconcile(_request())
        second = coordinator.reconcile(_request())
        self.assertEqual(second.outcome, RestartOutcome.MANUAL_RESTART_REQUIRED)
        self.assertEqual(second.transaction.transaction_id, first.transaction.transaction_id)
        self.assertEqual(second.transaction.restart_attempt_count, 0)
        self.assertEqual(len(self.manager.calls), 1)

    def test_new_session_does_not_reconcile_before_resume_implementation(self):
        first = self._coordinator().reconcile(_request())
        coordinator = RestartCoordinator(
            self.manager,
            capability_resolver=self.capability,
            session_id_provider=lambda: SESSION_B,
            store=self.store,
        )
        result = coordinator.reconcile(_request())
        self.assertEqual(result.outcome, RestartOutcome.FAILED)
        self.assertEqual(result.failure.code, "RESUME_PENDING")
        self.assertEqual(len(self.manager.calls), 1)
        self.assertEqual(self.store.inspect().transaction_id, first.transaction.transaction_id)

    def test_new_session_with_zero_attempts_is_ready_for_resume(self):
        result = self._coordinator().reconcile(_request())
        status = classify_startup_transaction(SESSION_B, store=self.store)
        self.assertEqual(status.classification, StartupClassification.READY_FOR_RESUME)
        self.assertTrue(status.eligible_for_resume)
        self.assertEqual(status.transaction.transaction_id, result.transaction.transaction_id)
        self.assertEqual(status.transaction.restart_attempt_count, 0)

    def test_automatic_capability_fails_closed_without_adapter(self):
        resolver = RestartCapabilityResolver(
            platform_id="test",
            capabilities={"test": RestartCapability.AUTOMATIC_APP_RESTART},
        )
        result = self._coordinator(capability=resolver).reconcile(_request())
        self.assertEqual(result.outcome, RestartOutcome.FAILED)
        self.assertEqual(
            result.failure.code, "AUTOMATIC_RESTART_ADAPTER_UNAVAILABLE"
        )
        self.assertIsNone(self.store.inspect())

    def test_active_corrupt_transaction_fails_closed(self):
        Path(self.store.directory).mkdir(parents=True)
        Path(self.store.transaction_path).write_text("{bad", encoding="utf-8")
        result = self._coordinator().reconcile(_request())
        self.assertEqual(result.outcome, RestartOutcome.FAILED)
        self.assertEqual(result.failure.code, "TRANSACTION_CORRUPT")
        self.assertTrue(Path(self.store.transaction_path).exists())

    def test_result_serialization_contains_only_safe_handoff_state(self):
        result = self._coordinator().reconcile(_request())
        encoded = json.dumps(result.to_dict(), sort_keys=True)
        self.assertIn("manual_restart_required", encoded)
        self.assertIn("Restart Kodi completely to continue.", encoded)
        self.assertNotIn("owner_result", encoded)
        self.assertNotIn("password", encoded.lower())

    def test_non_awaiting_active_transaction_is_not_reused(self):
        first = self._coordinator().reconcile(_request())
        self.store.update_phase(TransactionPhase.NEEDS_ATTENTION)
        result = self._coordinator().reconcile(_request())
        self.assertEqual(result.outcome, RestartOutcome.FAILED)
        self.assertEqual(result.failure.code, "ACTIVE_TRANSACTION_CONFLICT")
        self.assertEqual(self.store.inspect().transaction_id, first.transaction.transaction_id)


if __name__ == "__main__":
    unittest.main()
