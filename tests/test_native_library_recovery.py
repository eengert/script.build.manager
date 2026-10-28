"""Synthetic native Create/Install recovery through the existing abandon owner."""
from dataclasses import replace
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from resources.lib.frozen_install import (
    FrozenInstallCoordinator, FrozenInstallStore, FrozenInstallPhase,
    FrozenInstallStateConflict,
)
from resources.lib.update_guard import AddonUpdatePolicy
from resources.lib.frozen_resolution import resolution_fingerprint
from tests import test_library_install as fixtures
from tools.bm023a_adapter_support import (
    AdapterBootstrapError, recover_frozen_install, recover_library_frozen_install,
)


class NativeLibraryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.x = fixtures.LibraryInstallTests()
        self.x.setUp()
        self.addCleanup(self.x.doCleanups)
        self.library = self.x.fixture.library
        self.prior = self.x.seed_prior_association()
        self.target = self.x.target()
        self.x.policy.policy = AddonUpdatePolicy.AUTOMATIC
        coordinator = self.x.coordinator()
        with self.x.isolated(), patch.object(coordinator.store, "save_resolution_manifest",
                                             side_effect=OSError("synthetic persistence failure")):
            result = coordinator.install_target(self.target, interactive=False)
        self.assertEqual(result.code, "RESOLUTION_PERSISTENCE_FAILED")
        self.tx = self.x.store.inspect()
        self.assertEqual(self.tx.phase, FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertEqual(self.x.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        self.request = {
            "schema": "bm-library-recovery/1", "transaction_id": self.tx.transaction_id,
            "build_id": self.tx.build_id, "entry_id": self.target.source.entry_id,
            "device_profile_id": self.tx.device_profile_id,
            "manifest_fingerprint": self.tx.manifest_fingerprint,
            "phase": "needs_attention", "status_code": "RESOLUTION_PERSISTENCE_FAILED",
            "original_update_policy": int(AddonUpdatePolicy.AUTOMATIC),
        }

    def recover(self, request=None):
        with patch("resources.lib.build_library.default_build_library", return_value=self.library):
            return recover_library_frozen_install(
                self.request if request is None else request, store=self.x.store,
                policy_backend=self.x.policy, installer=self.x.backend,
                restart_transaction_path=Path(self.x.restart_store.transaction_path))

    def retained(self):
        return ({str(p.relative_to(self.library.root)): p.read_bytes()
                 for p in Path(self.library.root).rglob("*") if p.is_file()},
                {p.name: p.read_bytes() for p in self.x.store.resolutions_dir.glob("*.json")},
                dict(self.x.backend.installed), list(self.x.backend.install_calls),
                list(self.x.backend.enable_calls), list(self.x.config.mutations))

    def test_matching_native_transaction_restores_without_rollback_or_publication(self):
        before = self.retained()
        original = FrozenInstallCoordinator.abandon
        with patch.object(FrozenInstallCoordinator, "abandon", autospec=True,
                          side_effect=lambda owner, **kw: original(owner, **kw)) as abandon:
            result = self.recover()
        self.assertTrue(result["ok"])
        self.assertTrue(result["transaction_cleared"])
        self.assertTrue(result["updater_policy_restored"])
        self.assertEqual(abandon.call_count, 1)
        self.assertEqual(abandon.call_args.kwargs, {"acknowledge_restore_failure": False})
        self.assertIsNone(self.x.store.inspect())
        self.assertEqual(self.x.policy.policy, AddonUpdatePolicy.AUTOMATIC)
        self.assertEqual(self.retained(), before)
        self.assertEqual(self.library.current_applied_association(), self.prior)

    def test_every_request_identity_mismatch_refuses_before_mutation(self):
        changes = {
            "transaction_id": "00000000-0000-0000-0000-000000000001",
            "build_id": "different", "entry_id": "f" * 64,
            "device_profile_id": "other", "manifest_fingerprint": "f" * 64,
            "phase": "complete", "status_code": "OTHER",
            "original_update_policy": int(AddonUpdatePolicy.NOTIFY_ONLY),
            "schema": "other", "root": "/untrusted",
        }
        before = self.retained(), self.x.store.transaction_path.read_bytes(), list(self.x.policy.calls)
        for field, value in changes.items():
            with self.subTest(field=field), self.assertRaises(AdapterBootstrapError):
                self.recover({**self.request, field: value})
            self.assertEqual((self.retained(), self.x.store.transaction_path.read_bytes(),
                              self.x.policy.calls), before)

    def test_existing_standalone_path_cannot_bind_native_library_transaction(self):
        _, manifest, _ = self.target.load()
        calls = list(self.x.policy.calls)
        with self.assertRaises(AdapterBootstrapError):
            recover_frozen_install(self.x.coordinator(), self.x.store, self.x.policy,
                self.x.backend, Path(self.x.restart_store.transaction_path), manifest=manifest,
                manifest_path=str(self.x.base / "standalone.json"), configuration_manifest_path="",
                device_profile_id=self.tx.device_profile_id, expected_overlay_id="",
                needs_attention_phase=FrozenInstallPhase.NEEDS_ATTENTION,
                update_policy_type=AddonUpdatePolicy)
        self.assertEqual(self.x.store.inspect(), self.tx)
        self.assertEqual(self.x.policy.calls, calls)

    def test_missing_runtime_library_authority_refuses_without_mutation(self):
        calls = list(self.x.policy.calls)
        with patch("resources.lib.build_library.default_build_library", side_effect=OSError("private detail")), \
                self.assertRaises(AdapterBootstrapError) as raised:
            recover_library_frozen_install(self.request, store=self.x.store,
                policy_backend=self.x.policy, installer=self.x.backend,
                restart_transaction_path=Path(self.x.restart_store.transaction_path))
        self.assertEqual(str(raised.exception), "recovery_identity_mismatch")
        self.assertEqual(self.x.store.inspect(), self.tx)
        self.assertEqual(self.x.policy.calls, calls)

    def test_transaction_identity_and_unsafe_states_refuse(self):
        # Persist synthetic states with the real store API, never by editing files.
        variants = (
            {"build_id": "other"}, {"manifest_fingerprint": "f" * 64},
            {"device_profile_id": "other", "library_target": replace(self.target, device_profile_id="other")},
            {"activation_hold_ids": ("synthetic.hold",), "activation_hold_released": False},
            {"private_overlay_id": "unexpected"},
            {"phase": FrozenInstallPhase.PUBLICATION_PENDING},
        )
        self.x.store.clear_expected(transaction_id=self.tx.transaction_id, expected_phase=self.tx.phase)
        for changes in variants:
            tx = replace(self.tx, resolution_fingerprint=resolution_fingerprint(self.tx.resolution_records),
                         **changes)
            self.x.store.create(tx)
            before = self.x.store.transaction_path.read_bytes(), list(self.x.policy.calls), self.retained()
            with self.subTest(changes=changes), self.assertRaises(AdapterBootstrapError):
                self.recover()
            self.assertEqual((self.x.store.transaction_path.read_bytes(), self.x.policy.calls,
                              self.retained()), before)
            if tx.phase is not FrozenInstallPhase.PUBLICATION_PENDING:
                self.x.store.clear_expected(transaction_id=tx.transaction_id, expected_phase=tx.phase)

    def test_pending_publication_or_restart_owner_refuses(self):
        for method in ("pending_publication",):
            with patch.object(type(self.library), method, return_value=object()), \
                    self.assertRaises(AdapterBootstrapError):
                self.recover()
        path = Path(self.x.restart_store.transaction_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic restart owner")
        with self.assertRaises(AdapterBootstrapError):
            self.recover()
        self.assertEqual(self.x.store.inspect(), self.tx)
        self.assertEqual(self.x.policy.policy, AddonUpdatePolicy.NEVER_CHECK)

    def test_restore_failure_retains_transaction_and_quarantine(self):
        before = self.retained()
        self.x.policy.fail_after = len(self.x.policy.calls)
        with self.assertRaises(AdapterBootstrapError):
            self.recover()
        after = self.x.store.inspect()
        self.assertEqual(after.transaction_id, self.tx.transaction_id)
        # Existing abandon preserves an already-failed transaction's diagnostic.
        self.assertEqual(after, self.tx)
        self.assertEqual(self.x.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        self.assertEqual(self.retained(), before)

    def test_legacy_resolution_identity_is_recoverable_without_rewriting_records(self):
        self.x.store.clear_expected(transaction_id=self.tx.transaction_id, expected_phase=self.tx.phase)
        self.x.store.create(replace(self.tx,
            resolution_fingerprint=resolution_fingerprint(self.tx.resolution_records)))
        before = self.retained()
        self.assertTrue(self.recover()["ok"])
        self.assertEqual(self.retained(), before)

    def test_matching_transaction_stays_locked_through_policy_restore(self):
        original = self.x.policy.set_policy
        def restore(policy):
            with self.assertRaises(FrozenInstallStateConflict):
                with FrozenInstallStore(self.x.store.root).locked():
                    self.fail("competing writer acquired the recovery lock")
            return original(policy)
        with patch.object(self.x.policy, "set_policy", side_effect=restore):
            self.assertTrue(self.recover()["ok"])

    def test_recovery_access_cannot_escape_owner_or_lock_lifetime(self):
        errors = []
        with self.x.store.locked_recovery_access() as access:
            self.assertEqual(access.inspect(), self.tx)
            def foreign_thread():
                try:
                    access.inspect()
                except FrozenInstallStateConflict:
                    errors.append("refused")
            thread = threading.Thread(target=foreign_thread)
            thread.start(); thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, ["refused"])
        with self.assertRaises(FrozenInstallStateConflict):
            access.inspect()
