"""Disposable, synthetic lifecycle tests. Never load Kodi or a real profile."""
from dataclasses import replace
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from resources.lib.activation import reject_held_activation, ActivationHoldError
from resources.lib.capture_lifecycle import (
    CaptureLifecycleCoordinator, CaptureLifecycleError, CapturePhase,
    CaptureStore, CaptureTransaction, capture_activation_holds, request_fingerprint,
)
from resources.lib.create_capture import CreateBuildRequest, PublicCaptureSpecification
from resources.lib.frozen_install import FrozenInstallStore, active_activation_hold_ids
from resources.lib.redlight_resource import REDLIGHT_ADDON_ID, REDLIGHT_VERSION, redlight_declaration
from resources.lib.restart_coordinator import RestartCoordinator
from resources.lib.transaction import TransactionStore, TransactionStateConflict
from tests.test_transaction import _transaction, SESSION_A, SESSION_B


SECRET = "TOKEN_DO_NOT_EMIT_4293"


class Operations:
    def __init__(self, enabled=True):
        self.current_enabled = enabled
        self.version = REDLIGHT_VERSION
        self.session = SESSION_A
        self.restart_verified = True
        self.competing = False
        self.mutations = []

    def session_id(self):
        return self.session

    def owner_version(self, owner):
        assert owner == REDLIGHT_ADDON_ID
        return self.version

    def enabled(self, owner):
        assert owner == REDLIGHT_ADDON_ID
        return self.current_enabled

    def set_enabled(self, owner, value):
        assert owner == REDLIGHT_ADDON_ID and type(value) is bool
        self.mutations.append((owner, value))
        self.current_enabled = value

    def competing_operation(self):
        return self.competing

    def verify_restart(self, operation_id, old, new):
        return self.restart_verified


class CaptureLifecycleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)
        self.restart = TransactionStore(str(self.profile))
        self.root = Path(self.restart.directory)
        self.store = CaptureStore(self.root)
        self.ops = Operations()
        self.now = 1000
        self.request = CreateBuildRequest('demo', '1.0.0', 'Demo', 'macos', 'Mac', 'desk', 'Desk',
            (REDLIGHT_ADDON_ID,), False, PublicCaptureSpecification(), 'captured',
            private_resources=(redlight_declaration(),), private_overlay_id='demo-private')
        self.coordinator = self.make_coordinator()

    def make_coordinator(self):
        return CaptureLifecycleCoordinator(store=self.store, restart_store=self.restart,
            operations=self.ops, clock=lambda: self.now)

    def begin(self):
        return self.coordinator.begin(self.request, confirmed=True)

    def capture(self, record, callback=None):
        return self.coordinator.capture(record.operation_id, self.request, callback or (lambda verify: verify()))

    def test_durable_before_disable_and_shared_hold_visible(self):
        def disable(owner, value):
            current = self.store.read()
            self.assertEqual(current.phase, CapturePhase.PREPARING)
            self.assertTrue(current.original_enabled)
            self.assertEqual(capture_activation_holds(self.root), frozenset({owner}))
            self.ops.current_enabled = value
        self.ops.set_enabled = disable
        record = self.begin()
        self.assertEqual(record.phase, CapturePhase.AWAITING_RESTART)
        self.assertEqual(active_activation_hold_ids(FrozenInstallStore(self.root)), frozenset({REDLIGHT_ADDON_ID}))
        with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.root):
            with self.assertRaises(ActivationHoldError):
                reject_held_activation(REDLIGHT_ADDON_ID)

    def test_reconstructed_coordinator_captures_new_session_and_restores(self):
        record = self.begin()
        self.ops.session = SESSION_B
        self.coordinator = self.make_coordinator()
        def read(verify):
            verify()
            self.assertEqual(self.store.read().phase, CapturePhase.CAPTURING)
            return SECRET
        self.assertEqual(self.capture(record, read), SECRET)
        self.assertTrue(self.ops.current_enabled)
        self.assertEqual(self.store.read().phase, CapturePhase.COMPLETE)
        self.assertEqual(active_activation_hold_ids(FrozenInstallStore(self.root)), frozenset())
        self.assertNotIn(SECRET, self.store.path.read_text())
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False), (REDLIGHT_ADDON_ID, True)])

    def test_originally_disabled_remains_disabled_and_still_requires_restart(self):
        self.ops.current_enabled = False
        record = self.begin()
        self.assertEqual(self.ops.mutations, [])
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record)
        self.ops.session = SESSION_B
        self.capture(record)
        self.assertIs(self.ops.current_enabled, False)
        self.assertEqual(self.ops.mutations, [])

    def test_confirmation_and_owner_admission_make_no_mutation(self):
        for confirm, version, enabled in ((False, REDLIGHT_VERSION, True), (1, REDLIGHT_VERSION, True),
                                          (True, '2.6.9', True), (True, REDLIGHT_VERSION, None)):
            with self.subTest(confirm=confirm, version=version, enabled=enabled):
                self.ops.version, self.ops.current_enabled = version, enabled
                with self.assertRaises(CaptureLifecycleError):
                    self.coordinator.begin(self.request, confirmed=confirm)
                self.assertIsNone(self.store.read())
                self.assertEqual(self.ops.mutations, [])

    def test_same_session_and_unverified_restart_never_call_capture(self):
        record = self.begin()
        callback = Mock()
        for session, proof in ((SESSION_A, True), (SESSION_B, False), (SESSION_B, None), (SESSION_B, 1), ('', True)):
            self.ops.session, self.ops.restart_verified = session, proof
            with self.assertRaises(CaptureLifecycleError):
                self.capture(record, callback)
            self.assertEqual(self.store.read(), record)
        callback.assert_not_called()

    def test_request_owner_operation_stale_and_enablement_drift_fail_closed(self):
        record = self.begin()
        self.ops.session = SESSION_B
        callback = Mock()
        cases = [lambda: setattr(self.ops, 'version', '2.6.9'),
                 lambda: setattr(self.ops, 'current_enabled', True),
                 lambda: setattr(self.ops, 'competing', True),
                 lambda: setattr(self, 'now', record.expires_at)]
        for change in cases:
            self.ops.version, self.ops.current_enabled, self.ops.competing, self.now = REDLIGHT_VERSION, False, False, 1000
            change()
            with self.assertRaises(CaptureLifecycleError):
                self.capture(record, callback)
            self.assertEqual(self.store.read(), record)
        self.now, self.ops.competing = 1000, False
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.capture(SESSION_B, self.request, callback)
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.capture(record.operation_id, replace(self.request, description='changed'), callback)
        callback.assert_not_called()

    def test_every_request_field_changes_binding(self):
        for field, value in [('description', 'new'), ('build_name', 'New'), ('device_label', 'New'),
                             ('build_version', '2.0.0'), ('private_overlay_id', 'different')]:
            with self.subTest(field=field):
                self.assertNotEqual(request_fingerprint(self.request), request_fingerprint(replace(self.request, **{field: value})))

    def test_missing_corrupt_unsafe_and_malformed_record_never_capture(self):
        record = self.begin()
        callback = Mock()
        original = self.store.path.read_bytes()
        for content in (None, b'{', b'{}', b'[]', b'x' * 17000):
            with self.subTest(content_size=None if content is None else len(content)):
                self.store.path.unlink(missing_ok=True)
                if content is not None:
                    self.store.path.write_bytes(content)
                with self.assertRaises(CaptureLifecycleError):
                    self.capture(record, callback)
        self.store.path.unlink()
        target = self.profile / 'target'
        target.write_bytes(original)
        self.store.path.symlink_to(target)
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, callback)
        self.assertEqual(target.read_bytes(), original)
        callback.assert_not_called()

    def test_corrupt_record_blocks_shared_activation(self):
        self.begin()
        self.store.path.write_text(SECRET)
        with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.root):
            with self.assertRaises(CaptureLifecycleError) as cm:
                reject_held_activation(REDLIGHT_ADDON_ID)
        self.assertNotIn(SECRET, str(cm.exception))

    def test_schema_phase_owner_and_type_corruption(self):
        record = self.begin()
        raw = record.to_dict()
        for field, value in [('schema_version', True), ('operation_kind', 'install'), ('original_enabled', 1),
                             ('expires_at', float('nan')), ('owner_version', '2.6.9'), ('operation_id', 'wrong'),
                             ('phase', 'apply'), ('outcome', SECRET), ('phase', 'complete'), ('extra', SECRET)]:
            with self.subTest(field=field, value=value):
                with self.assertRaises(CaptureLifecycleError):
                    CaptureTransaction.from_dict({**raw, field: value})

    def test_cancel_same_session_restores_only_enabled_state(self):
        record = self.begin()
        result = self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(result.phase, CapturePhase.CANCELLED)
        self.assertTrue(self.ops.current_enabled)
        self.assertEqual(self.coordinator.recover(record.operation_id, self.request), result)

    def test_capture_failure_restores_and_sanitizes_exception(self):
        record = self.begin()
        self.ops.session = SESSION_B
        def fail(verify):
            verify()
            raise RuntimeError(SECRET)
        with self.assertRaises(CaptureLifecycleError) as cm:
            self.capture(record, fail)
        self.assertIsNone(cm.exception.__cause__)
        self.assertNotIn(SECRET, str(cm.exception))
        self.assertTrue(self.ops.current_enabled)
        self.assertEqual(self.store.read().phase, CapturePhase.FAILED)

    def test_restore_failure_retains_hold_and_can_recover_after_interruption(self):
        record = self.begin()
        original = self.ops.set_enabled
        def failed_restore(owner, value):
            original(owner, value)
            if value:
                raise RuntimeError(SECRET)  # effect happened, acknowledgment lost
        self.ops.set_enabled = failed_restore
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(self.store.read().phase, CapturePhase.RESTORING)
        self.assertEqual(capture_activation_holds(self.root), frozenset({REDLIGHT_ADDON_ID}))
        self.ops.set_enabled = original
        recovered = self.make_coordinator().recover(record.operation_id, self.request)
        self.assertEqual(recovered.phase, CapturePhase.CANCELLED)
        self.assertEqual(self.ops.mutations.count((REDLIGHT_ADDON_ID, True)), 1)

    def test_original_enabled_manual_restore_is_durable_noop(self):
        record = self.begin()
        self.ops.current_enabled = True
        save = self.store.save
        phases = []
        def observe(expected, candidate):
            phases.append(candidate.phase)
            if candidate.phase is CapturePhase.CANCELLED:
                self.assertTrue(self.store.read().held)
            return save(expected, candidate)
        self.store.save = observe
        recovered = self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(phases, [CapturePhase.RESTORING, CapturePhase.CANCELLED])
        self.assertFalse(recovered.held)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_expired_awaiting_restart_recovers_without_capture_authority(self):
        record = self.begin()
        self.now = record.expires_at
        self.ops.session = SESSION_B
        callback = Mock()
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, callback)
        with self.assertRaises(CaptureLifecycleError):
            self.begin()
        callback.assert_not_called()
        self.ops.verify_restart = Mock(side_effect=AssertionError('restart authority'))
        result = self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(result.phase, CapturePhase.CANCELLED)
        self.assertTrue(self.ops.current_enabled)
        self.assertEqual(capture_activation_holds(self.root), frozenset())
        self.ops.verify_restart.assert_not_called()

    def test_expired_interrupted_restoration_finishes(self):
        record = self.begin()
        setter = self.ops.set_enabled
        def interrupt(owner, enabled):
            setter(owner, enabled)
            raise RuntimeError(SECRET)
        self.ops.set_enabled = interrupt
        with self.assertRaises(CaptureLifecycleError) as cm:
            self.coordinator.recover(record.operation_id, self.request, cancelled=False)
        self.assertNotIn(SECRET, str(cm.exception))
        self.assertEqual(self.store.read().phase, CapturePhase.RESTORING)
        self.now = record.expires_at + 1
        self.ops.set_enabled = Mock(side_effect=AssertionError('unnecessary setter'))
        result = self.make_coordinator().recover(record.operation_id, self.request)
        self.assertEqual(result.phase, CapturePhase.FAILED)
        self.assertFalse(result.held)
        self.ops.set_enabled.assert_not_called()
        self.assertNotIn(SECRET, self.store.path.read_text())

    def test_original_disabled_unexpected_enablement_blocks_recovery(self):
        self.ops.current_enabled = False
        record = self.begin()
        self.ops.current_enabled = True
        self.now = record.expires_at
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(self.store.read(), record)
        self.assertEqual(self.ops.mutations, [])

    def test_expired_recovery_identity_and_authority_checks(self):
        record = self.begin()
        self.now = record.expires_at
        for defect in ('request', 'operation', 'version', 'competing', 'corrupt'):
            with self.subTest(defect=defect):
                self.ops.version = REDLIGHT_VERSION
                self.ops.competing = False
                self.store.path.write_text(json.dumps(record.to_dict()))
                request, operation = self.request, record.operation_id
                if defect == 'request':
                    request = replace(request, description=SECRET)
                elif defect == 'operation':
                    operation = SESSION_B
                elif defect == 'version':
                    self.ops.version = '2.6.9'
                elif defect == 'competing':
                    self.ops.competing = True
                else:
                    self.store.path.write_text(SECRET)
                before = self.store.path.read_bytes()
                with self.assertRaises(CaptureLifecycleError) as cm:
                    self.coordinator.recover(operation, request)
                self.assertNotIn(SECRET, str(cm.exception))
                self.assertEqual(before, self.store.path.read_bytes())
                self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_enablement_race_after_callback_verification_blocks_completion(self):
        record = self.begin()
        self.ops.session = SESSION_B
        enabled = self.ops.enabled
        reads = 0
        def race(owner):
            nonlocal reads
            reads += 1
            # Admission and post-callback verification pass; restoration races.
            if reads == 3:
                self.ops.current_enabled = True
            return enabled(owner)
        self.ops.enabled = race
        with self.assertRaises(CaptureLifecycleError) as cm:
            self.capture(record, lambda verify: SECRET)
        self.assertNotIn(SECRET, str(cm.exception))
        self.assertEqual(self.store.read().phase, CapturePhase.CAPTURING)
        self.assertTrue(self.store.read().held)
        self.assertNotIn(SECRET, self.store.path.read_text())
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_disable_failure_before_effect_is_explicitly_recoverable(self):
        self.ops.set_enabled = Mock(side_effect=RuntimeError(SECRET))
        with self.assertRaises(CaptureLifecycleError):
            self.begin()
        record = self.store.read()
        self.assertEqual(record.phase, CapturePhase.PREPARING)
        self.assertTrue(self.ops.current_enabled)
        result = self.make_coordinator().recover(record.operation_id, self.request)
        self.assertEqual(result.phase, CapturePhase.CANCELLED)

    def test_crashed_capture_is_not_automatically_replayed(self):
        record = self.begin()
        self.ops.session = SESSION_B
        with self.store.locked():
            crashed = self.store.save(record, replace(record, phase=CapturePhase.CAPTURING, capture_session_id=SESSION_B))
        with self.assertRaises(CaptureLifecycleError):
            self.capture(crashed)
        self.assertEqual(self.store.read(), crashed)
        self.coordinator.recover(record.operation_id, self.request, cancelled=False)
        self.assertEqual(self.store.read().phase, CapturePhase.FAILED)

    def test_competing_durable_restart_or_frozen_state_blocks_begin(self):
        self.restart.create(_transaction())
        with self.assertRaises(CaptureLifecycleError):
            self.begin()
        self.assertIsNone(self.store.read())
        self.assertEqual(self.ops.mutations, [])

    def test_corrupt_frozen_state_blocks_begin(self):
        frozen = FrozenInstallStore(self.root)
        frozen.transaction_path.write_text(SECRET)
        with self.assertRaises(CaptureLifecycleError):
            self.begin()
        self.assertIsNone(self.store.read())
        self.assertEqual(self.ops.mutations, [])

    def test_install_and_restart_creation_cannot_cross_capture_hold(self):
        self.begin()
        with self.assertRaises(TransactionStateConflict):
            self.restart.create(_transaction())
        with self.assertRaises(CaptureLifecycleError):
            FrozenInstallStore(self.root).create(Mock())
        self.assertIsNone(self.restart.read_snapshot())
        self.assertIsNone(FrozenInstallStore.read_snapshot(self.root))

    def test_restart_reconcile_checks_before_manager(self):
        self.begin()
        manager = Mock()
        result = RestartCoordinator(manager, store=self.restart).reconcile(_transaction().request)
        self.assertEqual(result.outcome.value, 'failed')
        manager.reconcile.assert_not_called()

    def test_existing_transaction_locks_block_begin(self):
        for lock in (self.restart.acquire_lock(), FrozenInstallStore(self.root).locked(), self.store.locked()):
            with self.subTest(lock=str(lock.path)), lock:
                with self.assertRaises(CaptureLifecycleError):
                    self.begin()
                self.assertIsNone(self.store.read())
        self.assertEqual(self.ops.mutations, [])

    def test_new_operation_replaces_only_terminal_record(self):
        first = self.begin()
        self.assertEqual(self.begin(), first)
        self.coordinator.recover(first.operation_id, self.request)
        second = self.begin()
        self.assertNotEqual(first.operation_id, second.operation_id)
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.recover(first.operation_id, self.request)

    def test_callbacks_cannot_change_phase_or_enable_owner_silently(self):
        record = self.begin()
        self.ops.session = SESSION_B
        def unsafe(verify):
            self.ops.current_enabled = True
            return SECRET
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, unsafe)
        self.assertEqual(self.store.read().phase, CapturePhase.CAPTURING)
        self.assertEqual(len(self.ops.mutations), 1)

    def test_no_runtime_composition_or_startup_invocation(self):
        from resources.lib.create_workflow import runtime_create_workflow
        from resources.lib.startup import run_startup
        self.assertNotIn('CaptureLifecycleCoordinator', runtime_create_workflow.__code__.co_names)
        self.assertNotIn('CaptureLifecycleCoordinator', run_startup.__code__.co_names)

    def test_real_adapter_capture_reads_existing_store_without_initialize_or_write(self):
        from resources.lib.redlight_resource import RedLightSettingsAdapter
        from resources.lib.private_resource import ResourceLifecycle
        record = self.begin()
        self.ops.session = SESSION_B
        adapter = RedLightSettingsAdapter(self.profile, lifecycle=ResourceLifecycle.QUIESCED,
            initialized=True, activation_hold_provider=lambda owner: owner in capture_activation_holds(self.root),
            enabled_state_provider=self.ops.enabled)
        adapter.database_path.parent.mkdir(parents=True)
        with sqlite3.connect(adapter.database_path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE settings (setting_id text not null unique, setting_type text, setting_default text, setting_value text)')
            db.execute('INSERT INTO settings VALUES (?, ?, ?, ?)', ('trakt.token', 'string', '', SECRET))
        before = {p.name: p.read_bytes() for p in adapter.database_path.parent.iterdir()}
        def read(verify):
            verify()
            return adapter.capture(self.request.private_resources[0])
        with patch.object(adapter, 'initialize', side_effect=AssertionError('initializer called')), \
             patch.object(adapter, 'apply', side_effect=AssertionError('writer called')):
            overlay, result = self.capture(record, read)
        self.assertEqual(result.outcome, 'captured')
        self.assertEqual(next(v.value for v in overlay.values if v.field_id == 'trakt.token'), SECRET)
        self.assertEqual(before, {p.name: p.read_bytes() for p in adapter.database_path.parent.iterdir()})
        self.assertNotIn(SECRET, self.store.path.read_text())

    def test_direct_apply_fails_before_prepare(self):
        from resources.lib.build_manager import BuildManager
        self.begin()
        manager = BuildManager(Mock())
        with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.root), \
             patch.object(manager, '_prepare') as prepare:
            result = manager.reconcile(_transaction().request)
        self.assertFalse(result.success)
        self.assertEqual(result.failure.code, 'CAPTURE_LIFECYCLE_BLOCKED')
        prepare.assert_not_called()

    def test_install_fails_before_artifact_or_updater_work(self):
        from resources.lib.frozen_install import FrozenInstallCoordinator
        backend, guard = Mock(), Mock()
        coordinator = FrozenInstallCoordinator(artifact_store=Mock(), installer=backend,
            store=FrozenInstallStore(self.root), policy_backend=guard)
        self.begin()
        result = coordinator.install(Mock(), manifest_path='/unused', device_profile_id='desk')
        self.assertFalse(result.succeeded)
        self.assertEqual(backend.mock_calls, [])
        self.assertEqual(guard.mock_calls, [])

    def test_lost_record_or_competitor_during_capture_does_not_return_private_result(self):
        record = self.begin()
        self.ops.session = SESSION_B
        def lose(verify):
            self.store.path.unlink()
            return SECRET
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, lose)
        self.assertEqual(len(self.ops.mutations), 1)

    def test_failed_durability_before_disable_keeps_owner_unchanged(self):
        with patch.object(FrozenInstallStore, '_fsync_directory_strict', side_effect=OSError(SECRET)):
            with self.assertRaises(CaptureLifecycleError):
                self.begin()
        self.assertEqual(self.ops.mutations, [])
        self.assertEqual(self.store.read().phase, CapturePhase.PREPARING)
        self.assertTrue(self.store.read().held)

    def test_competing_record_after_begin_blocks_shared_guard_and_recovery(self):
        record = self.begin()
        Path(self.restart.transaction_path).write_text(_transaction().to_json())
        with self.assertRaises(CaptureLifecycleError):
            active_activation_hold_ids(FrozenInstallStore(self.root))
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(self.store.read(), record)
        self.assertEqual(len(self.ops.mutations), 1)

    def test_rolled_back_clock_retains_hold_without_restoration(self):
        record = self.begin()
        for now in (record.created_at - 1,):
            self.now = now
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.recover(record.operation_id, self.request)
            self.assertEqual(self.store.read(), record)
            self.assertEqual(capture_activation_holds(self.root), frozenset({REDLIGHT_ADDON_ID}))
        self.assertEqual(len(self.ops.mutations), 1)

    def test_restore_no_effect_failure_and_durable_cas_failure_retain_hold(self):
        record = self.begin()
        self.ops.set_enabled = Mock(side_effect=RuntimeError(SECRET))
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(self.store.read().phase, CapturePhase.RESTORING)
        self.assertIs(self.ops.current_enabled, False)
        self.assertTrue(self.store.read().held)
        # Restart recovery retries only the recorded original enablement.
        self.ops.set_enabled = lambda owner, value: setattr(self.ops, 'current_enabled', value)
        with self.store.locked():
            with self.assertRaises(CaptureLifecycleError):
                self.store.save(record, record)
        self.coordinator.recover(record.operation_id, self.request)
        self.assertTrue(self.ops.current_enabled)

    def test_new_session_uuid_without_restart_proof_retains_capture_hold(self):
        record = self.begin()
        self.ops.session = SESSION_B
        self.ops.restart_verified = False
        callback = Mock()
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, callback)
        callback.assert_not_called()
        self.assertTrue(self.store.read().held)

    def test_restart_proof_lost_during_capture_never_releases_hold(self):
        record = self.begin()
        self.ops.session = SESSION_B
        def lose(verify):
            self.ops.restart_verified = False
            return SECRET
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, lose)
        self.assertEqual(self.store.read().phase, CapturePhase.CAPTURING)
        self.assertIs(self.ops.current_enabled, False)
        self.assertTrue(self.store.read().held)

    def test_competing_operation_during_capture_never_restores_or_returns_result(self):
        record = self.begin()
        self.ops.session = SESSION_B
        def compete(verify):
            self.ops.competing = True
            return SECRET
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, compete)
        self.assertTrue(self.store.read().held)
        self.assertIs(self.ops.current_enabled, False)

    def test_unknown_enabled_state_during_restore_is_not_coerced(self):
        record = self.begin()
        for value in (None, 0, 1, 'false'):
            self.ops.current_enabled = value
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.recover(record.operation_id, self.request)
            self.assertEqual(self.store.read(), record)
        self.assertEqual(len(self.ops.mutations), 1)

    def test_declined_consent_has_zero_lifecycle_files_or_operation_calls(self):
        self.coordinator.operations = Mock()
        for confirmed in (False, None, 1, 'yes'):
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.begin(self.request, confirmed=confirmed)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.coordinator.operations.mock_calls, [])

    def test_crash_before_and_after_every_phase_persistence(self):
        # Exercise real save/reconstruction with process-interruption semantics.
        for phase in (CapturePhase.PREPARING, CapturePhase.AWAITING_RESTART,
                      CapturePhase.CAPTURING, CapturePhase.RESTORING, CapturePhase.COMPLETE):
            for after in (False, True):
                with self.subTest(phase=phase, after=after), tempfile.TemporaryDirectory() as profile:
                    restart = TransactionStore(profile)
                    store = CaptureStore(Path(restart.directory))
                    ops = Operations()
                    coordinator = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                        operations=ops, clock=lambda: 1000)
                    save = store.save
                    crashed = False
                    def crash(expected, candidate):
                        nonlocal crashed
                        if candidate.phase is phase and not crashed:
                            crashed = True
                            if after:
                                save(expected, candidate)
                            raise KeyboardInterrupt()
                        return save(expected, candidate)
                    store.save = crash
                    with self.assertRaises(KeyboardInterrupt):
                        record = coordinator.begin(self.request, confirmed=True)
                        ops.session = SESSION_B
                        coordinator.capture(record.operation_id, self.request, lambda verify: verify())
                    current = store.read()
                    store.save = save
                    if current is None:
                        self.assertEqual(ops.mutations, [])
                        continue
                    if current.phase is CapturePhase.COMPLETE:
                        self.assertIs(ops.current_enabled, True)
                        self.assertFalse(current.held)
                        continue
                    self.assertTrue(current.held)
                    fresh = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                        operations=ops, clock=lambda: 1000)
                    recovered = fresh.recover(current.operation_id, self.request)
                    self.assertIs(ops.current_enabled, True)
                    self.assertFalse(recovered.held)

    def test_crash_after_disable_and_after_enable_is_recoverable(self):
        for value in (False, True):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as profile:
                restart = TransactionStore(profile)
                store = CaptureStore(Path(restart.directory))
                ops = Operations()
                coordinator = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                    operations=ops, clock=lambda: 1000)
                setter = ops.set_enabled
                def crash(owner, enabled):
                    setter(owner, enabled)
                    if enabled is value:
                        raise KeyboardInterrupt()
                ops.set_enabled = crash
                with self.assertRaises(KeyboardInterrupt):
                    record = coordinator.begin(self.request, confirmed=True)
                    coordinator.recover(record.operation_id, self.request)
                current = store.read()
                self.assertTrue(current.held)
                ops.set_enabled = setter
                coordinator.recover(current.operation_id, self.request)
                self.assertTrue(ops.current_enabled)
                self.assertEqual(ops.mutations.count((REDLIGHT_ADDON_ID, True)), 1)

    def test_preparation_retry_uses_original_identity_without_repeated_disable(self):
        setter = self.ops.set_enabled
        def crash(owner, enabled):
            setter(owner, enabled)
            raise KeyboardInterrupt()
        self.ops.set_enabled = crash
        with self.assertRaises(KeyboardInterrupt):
            self.begin()
        before = self.store.read()
        self.ops.set_enabled = setter
        resumed = self.make_coordinator().begin(self.request, confirmed=True)
        self.assertEqual(before.operation_id, resumed.operation_id)
        self.assertTrue(resumed.original_enabled)
        self.assertEqual(resumed.phase, CapturePhase.AWAITING_RESTART)
        self.assertEqual(self.begin(), resumed)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])


if __name__ == '__main__':
    unittest.main()
