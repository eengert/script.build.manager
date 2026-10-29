"""Runtime-owned recovery identity, exercised only with disposable offline state."""
from dataclasses import replace
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from resources.lib.build_library import BuildLibrary
from resources.lib.frozen_install import FrozenInstallCoordinator, FrozenInstallStore, FrozenInstallPhase
from resources.lib.frozen_resolution import resolution_fingerprint
from resources.lib.transaction import RestartTransaction
from tests import test_native_library_recovery as fixtures
from tools import bm023a_adapter_support as support
from tools import bm_test_app as host


class NativeRecoveryIdentityTests(unittest.TestCase):
    def setUp(self):
        # Existing typed synthetic native-library fixture and explicit isolated
        # test authority; no xbmcvfs module or host-profile substitution.
        self.fixture = fixtures.NativeLibraryRecoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.x = self.fixture.x
        self.tx = self.fixture.tx
        self.library = self.fixture.library
        self.restart = Path(self.x.restart_store.transaction_path)
        self.restart.parent.mkdir(parents=True, exist_ok=True)

    def read(self):
        with patch("resources.lib.build_library.default_build_library", return_value=self.library):
            return support.read_native_recovery_identity(self.x.store.root, self.restart)

    def tree(self):
        return {str(p.relative_to(self.x.base)): (p.is_dir(), None if p.is_dir() else p.read_bytes())
                for p in self.x.base.rglob("*")}

    def replace_transaction(self, **changes):
        self.x.store.clear_expected(transaction_id=self.tx.transaction_id, expected_phase=self.tx.phase)
        tx = replace(self.tx, resolution_fingerprint=resolution_fingerprint(self.tx.resolution_records), **changes)
        self.x.store.create(tx)
        return tx

    def test_authenticated_identity_is_exact_nine_key_recovery_request(self):
        self.assertEqual(self.read(), self.fixture.request)

    def test_reads_do_not_mutate_lock_update_associate_or_change_software(self):
        before = self.tree(), self.fixture.retained(), list(self.x.policy.calls)
        with patch.object(FrozenInstallStore, "locked", side_effect=AssertionError("lock forbidden")), \
                patch.object(FrozenInstallCoordinator, "abandon", side_effect=AssertionError("recovery forbidden")), \
                patch.object(self.x.policy, "set_policy", side_effect=AssertionError("policy forbidden")), \
                patch.object(self.x.backend, "install_exact", side_effect=AssertionError("software forbidden")):
            self.assertEqual(self.read(), self.fixture.request)
            self.assertEqual(self.read(), self.fixture.request)
        self.assertEqual((self.tree(), self.fixture.retained(), self.x.policy.calls), before)

    def test_missing_or_wrong_runtime_library_authority_omits_identity(self):
        for kwargs in ({"side_effect": ModuleNotFoundError("runtime unavailable")},
                       {"return_value": BuildLibrary(self.x.base / "wrong-library")}):
            before = self.tree()
            with patch("resources.lib.build_library.default_build_library", **kwargs):
                self.assertIsNone(support.read_native_recovery_identity(self.x.store.root, self.restart))
            self.assertEqual(self.tree(), before)

    def test_wrong_build_identity_refuses(self):
        self.replace_transaction(build_id="different")
        self.assertIsNone(self.read())

    def test_wrong_manifest_identity_refuses(self):
        self.replace_transaction(manifest_fingerprint="f" * 64)
        self.assertIsNone(self.read())

    def test_wrong_entry_identity_refuses(self):
        target = replace(self.fixture.target, source=replace(self.fixture.target.source,
                          entry_id=self.fixture.prior.entry_id))
        self.replace_transaction(library_target=target)
        self.assertIsNone(self.read())

    def test_profile_must_exist_in_authenticated_saved_manifest(self):
        target = replace(self.fixture.target, device_profile_id="not-declared")
        self.replace_transaction(library_target=target, device_profile_id="not-declared")
        self.assertIsNone(self.read())

    def test_symlinked_transaction_parent_is_refused_before_typed_read(self):
        alias = self.x.base / "alias"
        alias.symlink_to(self.x.store.root, target_is_directory=True)
        with patch.object(FrozenInstallStore, "read_snapshot", side_effect=AssertionError("unsafe read")) as reader:
            self.assertIsNone(support.read_native_recovery_identity(alias, self.restart))
            reader.assert_not_called()

    def test_tampered_saved_manifest_refuses(self):
        envelope = self.x.fixture.envelope(self.fixture.target.source.entry_id)
        bundle = json.loads(envelope.read_text())
        bundle["unexpected"] = "changed public content"
        envelope.write_text(json.dumps(bundle))
        self.assertIsNone(self.read())

    def test_unsupported_phase_or_failure_refuses(self):
        self.replace_transaction(status_code="OTHER")
        self.assertIsNone(self.read())
        self.replace_transaction(phase=FrozenInstallPhase.COMPLETE)
        self.assertIsNone(self.read())

    def test_private_or_unreleased_hold_owner_refuses(self):
        self.replace_transaction(private_overlay_id="private-value")
        self.assertIsNone(self.read())
        self.replace_transaction(activation_hold_ids=("synthetic.hold",), activation_hold_released=False)
        self.assertIsNone(self.read())

    def test_pending_publication_or_restart_owner_refuses(self):
        with patch.object(type(self.library), "pending_publication", return_value=object()):
            self.assertIsNone(self.read())
        self.restart.write_text("synthetic owner")
        self.assertIsNone(self.read())

    def test_missing_or_unsafe_transaction_paths_create_nothing(self):
        self.x.store.clear_expected(transaction_id=self.tx.transaction_id, expected_phase=self.tx.phase)
        before = self.tree()
        self.assertIsNone(self.read())
        self.assertEqual(self.tree(), before)
        for kind in ("symlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                path = self.x.store.transaction_path
                if kind == "symlink": path.symlink_to(self.x.base / "missing")
                elif kind == "fifo": os.mkfifo(path)
                else: path.mkdir()
                self.assertIsNone(self.read())
                if kind == "directory": path.rmdir()
                else: path.unlink()

    def test_changed_transaction_during_observation_omits_identity(self):
        original = support._platform_read
        calls = []
        def changed(path, limit):
            raw = original(path, limit)
            calls.append(path)
            return raw if len(calls) == 1 else raw + b" "
        with patch.object(support, "_platform_read", side_effect=changed):
            self.assertIsNone(self.read())

    def test_existing_sanitized_status_is_unchanged(self):
        def status():
            return support.read_adapter_status(self.x.store.transaction_path, self.x.store.lock_path,
                self.restart, self.x.restart_store.lock_path,
                type(self.tx).from_dict, RestartTransaction.from_dict)
        before = status()
        self.assertIsNotNone(self.read())
        self.assertEqual(status(), before)
        self.assertEqual(set(before), support.STATUS_KEYS)
        self.assertNotIn(self.tx.transaction_id, json.dumps(before))

    def test_host_projection_exposes_exact_identity(self):
        identity = self.read()
        raw = {"ok": True, "adapter_mode": "status", "status": {}, "recovery_identity": identity}
        projected, withheld = host.project_adapter_result("status", raw)
        self.assertEqual(projected["recovery_identity"], self.fixture.request)
        self.assertEqual(withheld["invalid_known_keys"], [])

    def test_host_projection_withholds_whole_malformed_or_private_identity(self):
        expected = self.fixture.request
        invalid = [None, {}, {**expected, "extra": "private-secret"}]
        invalid += [{k: v for k, v in expected.items() if k != field} for field in expected]
        invalid += [{**expected, field: "private/secret\n"} for field in expected]
        invalid += [{**expected, "original_update_policy": True},
                    {**expected, "original_update_policy": 3}]
        for identity in invalid:
            with self.subTest(identity=identity):
                projected, withheld = host.project_adapter_result("status", {
                    "ok": True, "adapter_mode": "status", "recovery_identity": identity})
                self.assertNotIn("recovery_identity", projected)
                self.assertEqual(withheld["invalid_known_keys"], ["recovery_identity"])
                self.assertNotIn("private", json.dumps([projected, withheld]))
