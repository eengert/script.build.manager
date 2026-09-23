import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib.build_manager import ReconcileRequest, ReconcileResult
from resources.lib.frozen_resolution import (
    InstallResolution,
    InstallResolutionRecord,
    ResolutionState,
)
from resources.lib.restart import RestartReport, RestartRequirement
from resources.lib.startup import StartupClassification, classify_startup_transaction
from resources.lib.transaction import (
    RestartTransaction,
    TransactionCorrupt,
    TransactionLockBusy,
    TransactionPhase,
    TransactionStateConflict,
    TransactionStore,
    TransactionUnsupportedSchema,
    prepare_restart_transaction,
)


FINGERPRINT = "sha256:" + "a" * 64
SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"


def _request() -> ReconcileRequest:
    return ReconcileRequest("/safe/build.json", "family-room")


def _result(*, success=True, requirement=RestartRequirement.KODI_RESTART):
    return ReconcileResult(
        success=success,
        request=_request(),
        desired_fingerprint=FINGERPRINT,
        restart_report=RestartReport(requirement, 1 if success else 0, 0 if success else 1),
    )


def _transaction(*, phase=TransactionPhase.AWAITING_RESTART) -> RestartTransaction:
    return RestartTransaction(
        transaction_id="33333333-3333-4333-8333-333333333333",
        phase=phase,
        request=_request(),
        desired_state_fingerprint=FINGERPRINT,
        restart_requirement=RestartRequirement.KODI_RESTART,
        originating_kodi_session_id=SESSION_A,
        created_at="2026-09-21T12:00:00+00:00",
        updated_at="2026-09-21T12:00:00+00:00",
    )


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TransactionStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestTransactionStore(StoreTestCase):
    def test_atomic_create_read_round_trip(self):
        transaction = _transaction()
        self.assertEqual(self.store.create(transaction), transaction)
        self.assertEqual(self.store.inspect(), transaction)
        self.assertTrue(Path(self.store.transaction_path).is_file())

    def test_deterministic_serialization(self):
        self.assertEqual(_transaction().to_json(), _transaction().to_json())
        self.assertEqual(
            _transaction().to_json(),
            json.dumps(_transaction().to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        )

    def test_frozen_install_resolution_survives_restart_transaction_round_trip(self):
        record = InstallResolutionRecord(
            "plugin.video.youtube",
            "7.4.4+unofficial.2",
            InstallResolution.SKIPPED,
            ResolutionState.SKIPPED,
        )
        request = ReconcileRequest(
            "/safe/build.json", "family-room", install_resolutions=(record,),
            source_software_fingerprint="a" * 64,
        )
        transaction = replace(_transaction(), request=request)

        restored = RestartTransaction.from_dict(transaction.to_dict())

        self.assertEqual(request, restored.request)
        self.assertEqual(
            "a" * 64, restored.request.source_software_fingerprint
        )
        self.assertEqual(InstallResolution.SKIPPED, restored.request.install_resolutions[0].resolution)
        self.assertEqual(ResolutionState.SKIPPED, restored.request.install_resolutions[0].state)

    def test_supported_schema_loads(self):
        self.store.create(_transaction())
        self.assertEqual(self.store.inspect().schema_version, 1)

    def test_malformed_json_fails_closed(self):
        Path(self.store.directory).mkdir(parents=True)
        Path(self.store.transaction_path).write_text("{not-json", encoding="utf-8")
        with self.assertRaises(TransactionCorrupt):
            self.store.inspect()

    def test_unsupported_schema_fails_closed(self):
        transaction = _transaction().to_dict()
        transaction["schema_version"] = 99
        Path(self.store.directory).mkdir(parents=True)
        Path(self.store.transaction_path).write_text(json.dumps(transaction), encoding="utf-8")
        with self.assertRaises(TransactionUnsupportedSchema):
            self.store.inspect()

    def test_missing_and_invalid_fields_fail_closed(self):
        transaction = _transaction().to_dict()
        transaction.pop("request")
        Path(self.store.directory).mkdir(parents=True)
        Path(self.store.transaction_path).write_text(json.dumps(transaction), encoding="utf-8")
        with self.assertRaises(TransactionCorrupt):
            self.store.inspect()
        transaction = _transaction().to_dict()
        transaction["phase"] = "not-a-phase"
        Path(self.store.transaction_path).write_text(json.dumps(transaction), encoding="utf-8")
        with self.assertRaises(TransactionCorrupt):
            self.store.inspect()

    def test_existing_valid_transaction_is_not_overwritten(self):
        original = _transaction()
        self.store.create(original)
        replacement = _transaction().with_phase(TransactionPhase.NEEDS_ATTENTION)
        with self.assertRaisesRegex(Exception, "already exists"):
            self.store.create(replacement)
        self.assertEqual(self.store.inspect(), original)

    def test_explicit_clear_removes_transaction(self):
        self.store.create(_transaction())
        self.assertTrue(self.store.clear())
        self.assertIsNone(self.store.inspect())
        self.assertFalse(Path(self.store.transaction_path).exists())

    def test_failed_write_does_not_destroy_prior_valid_transaction(self):
        original = _transaction()
        self.store.create(original)
        with patch.object(self.store, "_fsync_directory", side_effect=OSError("disk")):
            with self.assertRaises(Exception):
                self.store.update_phase(TransactionPhase.NEEDS_ATTENTION)
        self.assertEqual(self.store.inspect(), original)

    def test_lock_acquisition_is_rejected_while_held(self):
        first = self.store.acquire_lock()
        first.acquire()
        try:
            second = self.store.acquire_lock()
            with self.assertRaises(TransactionLockBusy):
                second.acquire()
        finally:
            first.release()

    def test_lock_releases_normally(self):
        with self.store.locked():
            pass
        with self.store.locked():
            pass

    def test_lock_is_released_when_owner_process_exits(self):
        ready = Path(self.tmp.name) / "lock-ready"
        project_root = Path(__file__).parents[1]
        code = (
            "import pathlib, sys, time; "
            "from resources.lib.transaction import TransactionStore; "
            "store = TransactionStore(sys.argv[1]); "
            "lock = store.acquire_lock(); lock.acquire(); "
            "pathlib.Path(sys.argv[2]).write_text('ready'); time.sleep(0.2)"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(project_root)
        child = subprocess.Popen(
            [sys.executable, "-c", code, self.tmp.name, str(ready)],
            cwd=str(project_root), env=env,
        )
        try:
            deadline = time.time() + 5
            while not ready.exists() and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            self.assertEqual(child.wait(timeout=5), 0)
            with self.store.locked():
                pass
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)

    def test_phase_update_is_durable(self):
        self.store.create(_transaction())
        updated = self.store.update_phase(TransactionPhase.NEEDS_ATTENTION)
        self.assertEqual(updated.phase, TransactionPhase.NEEDS_ATTENTION)
        self.assertEqual(self.store.inspect().phase, TransactionPhase.NEEDS_ATTENTION)

    def test_expected_transition_requires_matching_identity_and_phase(self):
        transaction = _transaction()
        self.store.create(transaction)
        updated = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=TransactionPhase.AWAITING_RESTART,
            new_phase=TransactionPhase.RESUMING,
        )
        self.assertEqual(updated.phase, TransactionPhase.RESUMING)
        with self.assertRaises(TransactionStateConflict):
            self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=TransactionPhase.AWAITING_RESTART,
                new_phase=TransactionPhase.NEEDS_ATTENTION,
            )

    def test_expected_clear_requires_matching_identity_and_phase(self):
        transaction = _transaction(phase=TransactionPhase.RESUMING)
        self.store.create(transaction)
        with self.assertRaises(TransactionStateConflict):
            self.store.clear_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=TransactionPhase.AWAITING_RESTART,
            )
        self.assertTrue(self.store.clear_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=TransactionPhase.RESUMING,
        ))

    def test_old_v1_record_without_status_fields_remains_readable(self):
        transaction = _transaction().to_dict()
        transaction.pop("status_code")
        transaction.pop("status_message")
        Path(self.store.directory).mkdir(parents=True)
        Path(self.store.transaction_path).write_text(json.dumps(transaction), encoding="utf-8")
        loaded = self.store.inspect()
        self.assertEqual(loaded.status_code, "")
        self.assertEqual(loaded.status_message, "")


class TestPrepareRestartTransaction(StoreTestCase):
    def test_successful_none_does_not_create_transaction(self):
        result = prepare_restart_transaction(
            _request(), _result(requirement=RestartRequirement.NONE), SESSION_A, store=self.store
        )
        self.assertTrue(result.succeeded)
        self.assertFalse(result.created)
        self.assertIsNone(self.store.inspect())

    def test_failed_reconciliation_with_restart_does_not_create_transaction(self):
        result = prepare_restart_transaction(
            _request(), _result(success=False), SESSION_A, store=self.store
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.failure.code, "INVALID_RESTART_TRANSACTION")
        self.assertIsNone(self.store.inspect())

    def test_successful_restart_creates_awaiting_transaction(self):
        result = prepare_restart_transaction(
            _request(), _result(), SESSION_A, store=self.store
        )
        self.assertTrue(result.succeeded)
        self.assertTrue(result.created)
        self.assertEqual(result.transaction.phase, TransactionPhase.AWAITING_RESTART)

    def test_request_fingerprint_and_session_are_stored(self):
        result = prepare_restart_transaction(
            _request(), _result(), SESSION_A, store=self.store
        )
        stored = self.store.inspect()
        self.assertEqual(stored.request, _request())
        self.assertEqual(stored.desired_state_fingerprint, FINGERPRINT)
        self.assertEqual(stored.originating_kodi_session_id, SESSION_A)
        self.assertEqual(stored.transaction_id, result.transaction.transaction_id)

    def test_incompatible_active_transaction_is_rejected(self):
        self.store.create(_transaction())
        result = prepare_restart_transaction(
            _request(), _result(), SESSION_B, store=self.store
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.failure.code, "TRANSACTION_PERSISTENCE_FAILED")

    def test_secret_and_runtime_values_are_not_serialized(self):
        result = prepare_restart_transaction(
            _request(), _result(), SESSION_A, store=self.store
        )
        raw = Path(self.store.transaction_path).read_text(encoding="utf-8")
        self.assertNotIn("token", raw.lower())
        self.assertNotIn("password", raw.lower())
        self.assertNotIn("owner_result", raw)
        self.assertNotIn("action_results", raw)
        self.assertNotIn("KodiRuntime", raw)
        self.assertEqual(json.loads(raw)["request"], _request().to_dict())
        self.assertIsNotNone(result.transaction)

    def test_invalid_request_and_fingerprint_fail_closed(self):
        bad = ReconcileResult(
            success=True,
            request=_request(),
            desired_fingerprint="not-a-fingerprint",
            restart_report=RestartReport(RestartRequirement.KODI_RESTART, 1, 0),
        )
        result = prepare_restart_transaction(_request(), bad, SESSION_A, store=self.store)
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.store.inspect())


class TestStartupClassification(StoreTestCase):
    def test_no_transaction_is_fast_path(self):
        status = classify_startup_transaction(SESSION_A, store=self.store)
        self.assertEqual(status.classification, StartupClassification.NO_TRANSACTION)
        self.assertFalse(Path(self.store.transaction_path).exists())

    def test_same_session_is_not_resume_eligible(self):
        self.store.create(_transaction())
        status = classify_startup_transaction(SESSION_A, store=self.store)
        self.assertEqual(status.classification, StartupClassification.SAME_SESSION_AWAITING_RESTART)
        self.assertFalse(status.eligible_for_resume)
        self.assertEqual(self.store.inspect().phase, TransactionPhase.AWAITING_RESTART)

    def test_new_session_is_ready_for_resume(self):
        self.store.create(_transaction())
        status = classify_startup_transaction(SESSION_B, store=self.store)
        self.assertEqual(status.classification, StartupClassification.READY_FOR_RESUME)
        self.assertTrue(status.eligible_for_resume)
        self.assertEqual(self.store.inspect().phase, TransactionPhase.AWAITING_RESTART)

    def test_corrupt_transaction_is_preserved_and_invalid(self):
        Path(self.store.directory).mkdir(parents=True)
        Path(self.store.transaction_path).write_text("[]", encoding="utf-8")
        status = classify_startup_transaction(SESSION_B, store=self.store)
        self.assertEqual(status.classification, StartupClassification.INVALID_TRANSACTION)
        self.assertTrue(Path(self.store.transaction_path).exists())

    def test_unsupported_schema_is_invalid_and_preserved(self):
        payload = _transaction().to_dict()
        payload["schema_version"] = 44
        Path(self.store.directory).mkdir(parents=True)
        Path(self.store.transaction_path).write_text(json.dumps(payload), encoding="utf-8")
        status = classify_startup_transaction(SESSION_B, store=self.store)
        self.assertEqual(status.classification, StartupClassification.INVALID_TRANSACTION)
        self.assertEqual(status.code, "TRANSACTION_UNSUPPORTED_SCHEMA")

    def test_non_awaiting_phase_needs_attention(self):
        self.store.create(_transaction(phase=TransactionPhase.NEEDS_ATTENTION))
        status = classify_startup_transaction(SESSION_B, store=self.store)
        self.assertEqual(status.classification, StartupClassification.NEEDS_ATTENTION)

    def test_startup_has_no_reconcile_or_restart_dependency(self):
        # The production classifier only reads and compares transaction state;
        # these names are intentionally absent from its callable contract.
        import resources.lib.startup as startup
        self.assertFalse(hasattr(startup, "BuildManager"))
        self.assertFalse(hasattr(startup, "restart_kodi"))


class TestSessionIdentity(unittest.TestCase):
    class Window:
        def __init__(self):
            self.properties = {}

        def getProperty(self, key):
            return self.properties.get(key, "")

        def setProperty(self, key, value):
            self.properties[key] = value

    def test_same_process_returns_same_id(self):
        from resources.lib.session import get_current_kodi_session_id
        window = self.Window()
        first = get_current_kodi_session_id(window=window, token_factory=lambda: SESSION_A)
        second = get_current_kodi_session_id(window=window, token_factory=lambda: SESSION_B)
        self.assertEqual(first, SESSION_A)
        self.assertEqual(second, SESSION_A)

    def test_new_process_seam_returns_different_id(self):
        from resources.lib.session import get_current_kodi_session_id
        first = get_current_kodi_session_id(window=self.Window(), token_factory=lambda: SESSION_A)
        second = get_current_kodi_session_id(window=self.Window(), token_factory=lambda: SESSION_B)
        self.assertNotEqual(first, second)


class TestAddonPackaging(unittest.TestCase):
    def test_service_extension_and_entrypoint_exist(self):
        addon_xml = Path(__file__).parents[1] / "addon.xml"
        source = addon_xml.read_text(encoding="utf-8")
        self.assertIn('<extension point="xbmc.service" library="service.py" />', source)
        self.assertTrue((addon_xml.parent / "service.py").is_file())

    def test_default_entrypoint_remains_available(self):
        self.assertTrue((Path(__file__).parents[1] / "default.py").is_file())


class TestServiceDelegation(unittest.TestCase):
    def test_service_delegates_to_startup_foundation(self):
        import service

        status = SimpleNamespace(
            classification=SimpleNamespace(value="no_transaction")
        )
        with patch("resources.lib.startup.run_startup", return_value=status) as run:
            with patch.dict(sys.modules, {"xbmc": SimpleNamespace(LOGDEBUG=0, LOGINFO=1, log=lambda *_args: None)}):
                service.main()
        run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
