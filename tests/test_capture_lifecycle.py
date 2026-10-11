"""Disposable, synthetic lifecycle tests. Never load Kodi or a real profile."""
from contextlib import ExitStack, contextmanager
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
    CaptureStore, CaptureTransaction, D2Confirmation, capture_activation_holds, request_fingerprint, require_no_capture,
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

    def use_symlinked_profile(self):
        alias = self.profile / 'userdata'
        target = self.profile / 'trusted-userdata'
        target.mkdir()
        alias.symlink_to(target, target_is_directory=True)
        self.restart = TransactionStore(str(alias))
        # Use the spelling supplied by the profile translator, not a test-only root.
        self.alias_root = alias / 'addon_data' / 'script.build.manager'
        self.root = Path(self.restart.directory)
        self.store = CaptureStore(self.alias_root)

    def test_symlinked_profile_no_record_admission(self):
        self.use_symlinked_profile()
        require_no_capture(self.alias_root)
        self.assertEqual(capture_activation_holds(self.alias_root), frozenset())
        frozen = FrozenInstallStore(self.alias_root)
        self.assertEqual(active_activation_hold_ids(frozen), frozenset())
        with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.alias_root):
            reject_held_activation(REDLIGHT_ADDON_ID)
        self.assertIsNone(self.restart.read_snapshot())
        self.assertIsNone(FrozenInstallStore.read_snapshot(self.alias_root))

    def test_symlinked_profile_begin_hold_and_readonly_reconstruction(self):
        self.use_symlinked_profile()
        self.coordinator = self.make_coordinator()
        self.assertEqual(self.store.root, self.root)
        record = self.begin()
        self.assertEqual(self.begin(), record)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        self.assertEqual(capture_activation_holds(self.alias_root), frozenset({REDLIGHT_ADDON_ID}))
        self.assertEqual(active_activation_hold_ids(FrozenInstallStore(self.alias_root)), frozenset({REDLIGHT_ADDON_ID}))
        with self.assertRaises(CaptureLifecycleError):
            require_no_capture(self.alias_root)
        with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.alias_root):
            with self.assertRaises(ActivationHoldError):
                reject_held_activation(REDLIGHT_ADDON_ID)
        with self.assertRaises(TransactionStateConflict):
            self.restart.create(_transaction())
        with self.assertRaises(Exception):
            FrozenInstallStore(self.alias_root).create(Mock())
        before = {p.relative_to(self.profile): p.read_bytes() for p in self.profile.rglob('*') if p.is_file()}
        self.assertEqual(self.make_coordinator().reconstruct_request(record.operation_id,
            record.request_fingerprint), self.request)
        self.assertEqual(before, {p.relative_to(self.profile): p.read_bytes() for p in self.profile.rglob('*') if p.is_file()})

    def test_symlinked_profile_install_and_reconciliation_admission(self):
        from resources.lib.build_manager import BuildManager
        from resources.lib.frozen_install import FrozenInstallCoordinator
        self.use_symlinked_profile()
        manager = BuildManager(Mock())
        sentinel = object()
        with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.alias_root), \
                patch.object(manager, '_prepare', return_value=(None, sentinel)) as prepare:
            self.assertIs(manager.reconcile(_transaction().request), sentinel)
            prepare.assert_called_once()
        self.assertIsNone(RestartCoordinator(Mock(), store=self.restart)._pending_before_reconcile(_transaction().request))
        installer = FrozenInstallCoordinator(artifact_store=Mock(), installer=Mock(),
            store=FrozenInstallStore(self.alias_root), policy_backend=Mock())
        with patch('resources.lib.build_library.authoritative_build_library',
                   side_effect=RuntimeError('synthetic admission boundary')) as next_stage:
            with self.assertRaisesRegex(RuntimeError, 'synthetic admission boundary'):
                installer.install(Mock(), manifest_path='/unused', device_profile_id='desk',
                                  library_target=Mock())
        next_stage.assert_called_once()
        self.coordinator = self.make_coordinator()
        self.begin()
        with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.alias_root), \
                patch.object(manager, '_prepare') as prepare:
            result = manager.reconcile(_transaction().request)
            self.assertEqual(result.failure.code, 'CAPTURE_LIFECYCLE_BLOCKED')
            prepare.assert_not_called()
        with patch('resources.lib.build_library.authoritative_build_library') as next_stage:
            result = installer.install(Mock(), manifest_path='/unused', device_profile_id='desk')
            self.assertEqual(result.code, 'CAPTURE_LIFECYCLE_BLOCKED')
            next_stage.assert_not_called()
        restart_manager = Mock()
        result = RestartCoordinator(restart_manager, store=self.restart).reconcile(_transaction().request)
        self.assertFalse(result.reconcile_result.success)
        restart_manager.reconcile.assert_not_called()

    def test_canonical_root_matches_all_operation_stores(self):
        self.use_symlinked_profile()
        frozen = FrozenInstallStore(self.alias_root, create=False)
        self.coordinator = self.make_coordinator()
        self.assertEqual(self.store.root, Path(self.restart.directory))
        self.assertEqual(self.store.root, frozen.root.resolve())
        self.assertEqual(self.store.path.parent, Path(self.restart.lock_path).parent)
        record = self.begin()
        self.assertEqual(self.root.joinpath(self.store.path.name).read_bytes(),
                         self.alias_root.joinpath(self.store.path.name).read_bytes())
        self.assertEqual(self.store.read(), record)

    def test_absent_reconstruction_does_not_create_directories_or_locks(self):
        self.use_symlinked_profile()
        before = set(self.profile.rglob('*'))
        with self.assertRaises(CaptureLifecycleError):
            self.store.reconstruct_request(SESSION_A, request_fingerprint(self.request), now=self.now)
        self.assertEqual(before, set(self.profile.rglob('*')))
        self.assertFalse(self.root.exists())

    def test_root_replacement_and_alias_drift_refuse_authority(self):
        for defect in ('directory', 'symlink', 'missing', 'alias', 'restart_root'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temporary:
                profile = Path(temporary)
                target = profile / 'userdata'
                target.mkdir()
                alias = profile / 'alias'
                alias.symlink_to(target, target_is_directory=True)
                restart = TransactionStore(str(alias))
                root = Path(restart.directory)
                store = CaptureStore(alias / 'addon_data' / 'script.build.manager')
                operations = Operations()
                coordinator = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                    operations=operations, clock=lambda: self.now)
                record = coordinator.begin(self.request, confirmed=True)
                original = store.path.read_bytes()
                retained = root.with_name('retained')
                if defect in ('directory', 'symlink', 'missing'):
                    root.rename(retained)
                    if defect == 'directory':
                        root.mkdir()
                        (root / store.path.name).write_bytes(original)
                    elif defect == 'symlink':
                        root.symlink_to(retained, target_is_directory=True)
                else:
                    other = profile / 'other'
                    other.mkdir()
                    if defect == 'alias':
                        alias.unlink()
                        alias.symlink_to(other, target_is_directory=True)
                    else:
                        restart._translated_root = str(other)
                mutations = list(operations.mutations)
                with self.assertRaises(CaptureLifecycleError):
                    coordinator.recover(record.operation_id, self.request)
                with self.assertRaises(CaptureLifecycleError):
                    coordinator.begin(self.request, confirmed=True)
                self.assertEqual(operations.mutations, mutations)
                held = (retained if retained.exists() else root) / store.path.name
                self.assertEqual(held.read_bytes(), original)

    def test_descriptor_write_cannot_be_redirected_by_root_swap(self):
        import os
        record = self.begin()
        original = self.store.path.read_bytes()
        retained = self.root.with_name('retained')
        real_replace = os.replace
        def swap_before_replace(source, destination, **kwargs):
            self.root.rename(retained)
            self.root.mkdir()
            return real_replace(source, destination, **kwargs)
        with self.store.locked():
            with patch('resources.lib.capture_lifecycle.os.replace', side_effect=swap_before_replace):
                with self.assertRaises(CaptureLifecycleError):
                    self.store.save(record, replace(record, phase=CapturePhase.RESTORING, outcome='cancelled'))
        self.assertEqual(list(self.root.iterdir()), [])
        held = CaptureTransaction.from_dict(json.loads((retained / self.store.path.name).read_bytes()))
        self.assertTrue(held.held)
        self.assertEqual(held.operation_id, record.operation_id)
        self.assertNotEqual((retained / self.store.path.name).read_bytes(), original)
        self.assertFalse(list(retained.glob('.frozen-install.*.tmp')))
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_staging_collision_preserves_unowned_file_and_hold(self):
        record = self.begin()
        retained = self.root / ('.frozen-install.' + SESSION_B + '.tmp')
        retained.write_text('retained evidence')
        with self.store.locked(), patch('resources.lib.capture_lifecycle.uuid.uuid4', return_value=SESSION_B):
            with self.assertRaises(CaptureLifecycleError):
                self.store.save(record, replace(record, phase=CapturePhase.RESTORING, outcome='cancelled'))
        self.assertEqual(retained.read_text(), 'retained evidence')
        self.assertEqual(self.store.read(), record)

    def test_root_swap_from_state_callback_cannot_disable_owner(self):
        retained = self.root.with_name('retained')
        enabled = self.ops.enabled
        calls = 0
        def substitute(owner):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.root.rename(retained)
                self.root.mkdir()
            return enabled(owner)
        self.ops.enabled = substitute
        with self.assertRaises(CaptureLifecycleError):
            self.begin()
        self.assertEqual(self.ops.mutations, [])
        self.assertEqual(list(self.root.iterdir()), [])
        record = CaptureTransaction.from_dict(json.loads((retained / self.store.path.name).read_bytes()))
        self.assertEqual(record.phase, CapturePhase.PREPARING)
        self.assertTrue(record.held)

    def test_lock_substitution_during_callback_blocks_restore(self):
        record = self.begin()
        self.ops.session = SESSION_B
        def substitute(verify):
            path = self.root / 'create_capture_transaction.lock'
            path.rename(path.with_suffix('.retained'))
            path.touch()
            verify()
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, substitute)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        self.assertTrue(self.store.read().held)

    def test_unsafe_root_and_lock_symlinks_fail_before_disable(self):
        self.root.mkdir(parents=True)
        target = self.profile / 'sentinel'
        target.write_text('preserve')
        for name in ('create_capture_transaction.lock', 'frozen_install_transaction.lock',
                     Path(self.restart.lock_path).name):
            with self.subTest(name=name):
                path = self.root / name
                path.unlink(missing_ok=True)
                path.symlink_to(target)
                with self.assertRaises(CaptureLifecycleError):
                    self.begin()
                self.assertEqual(self.ops.mutations, [])
                self.assertEqual(target.read_text(), 'preserve')
                path.unlink()
        unsafe = self.profile / 'not-a-directory'
        unsafe.write_text('preserve')
        with self.assertRaises(CaptureLifecycleError):
            CaptureStore(unsafe / 'state')
        dangling = self.profile / 'dangling'
        dangling.symlink_to(self.profile / 'missing', target_is_directory=True)
        with self.assertRaises(CaptureLifecycleError):
            CaptureStore(dangling / 'state')
        loop = self.profile / 'loop'
        loop.symlink_to(loop, target_is_directory=True)
        with self.assertRaises(CaptureLifecycleError):
            CaptureStore(loop / 'state')

    def test_all_typed_declarations_round_trip_without_values(self):
        from resources.lib.create_capture import PublicSettingTarget
        from resources.lib.config import ConfigSettingType
        from resources.lib.manifest import PrivateSettingDeclaration
        self.request = replace(self.request,
            public_capture=PublicCaptureSpecification(
                (PublicSettingTarget('plugin.video.demo', 'public', ConfigSettingType.BOOL),),
                ('addon_data/plugin.video.demo/demo.xml',)),
            private_settings=(PrivateSettingDeclaration('plugin.video.demo', 'token', 'string',
                sensitivity='token'),))
        record = self.begin()
        self.assertEqual(self.make_coordinator().reconstruct_request(
            record.operation_id, record.request_fingerprint), self.request)
        self.assertNotIn('value', json.loads(record.request_metadata)['private_settings'][0])
        self.assertEqual(json.loads(record.request_metadata)['private_resources'], ['redlight.settings'])
        self.assertNotIn(SECRET, self.store.path.read_text())

    def test_missing_metadata_retains_hold_and_blocks_lifecycle(self):
        record = self.begin()
        value = json.loads(self.store.path.read_text())
        value.pop('request_metadata')
        self.store.path.write_text(json.dumps(value))
        self.ops.session = SESSION_B
        before = list(self.ops.mutations)
        callback = Mock()
        with self.assertRaises(CaptureLifecycleError):
            self.capture(record, callback)
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(capture_activation_holds(self.root), frozenset({REDLIGHT_ADDON_ID}))
        self.assertEqual(before, self.ops.mutations)
        callback.assert_not_called()

    def test_request_reconstruction_is_read_only_and_fresh_process(self):
        import os
        import subprocess
        import sys
        record = self.begin()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.coordinator.operations = Mock(side_effect=AssertionError("must not call operations"))
        restored = self.coordinator.reconstruct_request(record.operation_id, record.request_fingerprint)
        self.assertEqual(restored, self.request)
        self.assertEqual(request_fingerprint(restored), record.request_fingerprint)
        code = """import sys
from pathlib import Path
from resources.lib.capture_lifecycle import CaptureStore, request_fingerprint
r = CaptureStore(Path(sys.argv[1])).reconstruct_request(sys.argv[2], sys.argv[3], now=1000)
assert request_fingerprint(r) == sys.argv[3]
assert r.private_resources[0].owner_addon_id == 'plugin.video.redlight'
"""
        subprocess.run([sys.executable, '-c', code, str(self.root), record.operation_id,
                        record.request_fingerprint], check=True,
                       env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_reconstruction_rejects_unsafe_metadata_and_bindings(self):
        record = self.begin()
        original = self.store.path.read_bytes()
        for change in ('missing', 'corrupt', 'request', 'owner', 'catalog', 'oversize'):
            value = json.loads(original)
            if change == 'missing':
                value.pop('request_metadata')
            elif change == 'corrupt':
                value['request_metadata'] = SECRET
            elif change == 'request':
                metadata = json.loads(value['request_metadata'])
                metadata['description'] = 'substituted'
                value['request_metadata'] = json.dumps(metadata, sort_keys=True, separators=(',', ':'))
            elif change == 'owner':
                value['owner_version'] = '2.6.9'
            elif change == 'catalog':
                metadata = json.loads(value['request_metadata'])
                metadata['private_resources'] = ['untrusted.resource']
                value['request_metadata'] = json.dumps(metadata, sort_keys=True, separators=(',', ':'))
            else:
                value['request_metadata'] = 'x' * 17000
            self.store.path.write_text(json.dumps(value))
            with self.assertRaises(CaptureLifecycleError) as error:
                self.coordinator.reconstruct_request(record.operation_id, record.request_fingerprint)
            self.assertNotIn(SECRET, str(error.exception))
        self.store.path.write_bytes(original)
        for operation, fingerprint, now in ((SESSION_B, record.request_fingerprint, 1000),
                (record.operation_id, 'sha256:' + '0' * 64, 1000),
                (record.operation_id, record.request_fingerprint, record.expires_at)):
            self.now = now
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.reconstruct_request(operation, fingerprint)
        self.now = 1000
        target = self.root / 'retained.json'
        target.write_bytes(original)
        self.store.path.unlink()
        self.store.path.symlink_to(target)
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.reconstruct_request(record.operation_id, record.request_fingerprint)
        self.assertEqual(target.read_bytes(), original)
        self.store.path.unlink()
        self.store.path.write_bytes(original)
        alias = self.profile / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(CaptureLifecycleError):
            CaptureStore(alias).reconstruct_request(record.operation_id, record.request_fingerprint, now=1000)

    def test_request_and_hold_share_atomic_crash_boundary(self):
        for boundary in ('replace', 'directory_sync'):
            with self.subTest(boundary=boundary):
                self.store.path.unlink(missing_ok=True)
                self.ops.mutations.clear()
                target = ('resources.lib.frozen_install.os.replace' if boundary == 'replace' else
                          'resources.lib.capture_lifecycle.CaptureStore._sync_directory')
                with patch(target, side_effect=OSError(SECRET)):
                    with self.assertRaises(CaptureLifecycleError) as error:
                        self.begin()
                self.assertNotIn(SECRET, str(error.exception))
                self.assertEqual(self.ops.mutations, [])
                record = self.store.read()
                if boundary == 'replace':
                    self.assertIsNone(record)
                else:
                    self.assertTrue(record.held)
                    self.assertEqual(self.coordinator.reconstruct_request(
                        record.operation_id, record.request_fingerprint), self.request)
                self.assertFalse(list(self.root.glob('.frozen-install.*.tmp')))

    def test_complete_reconstruction_retains_no_capture_result_or_registration(self):
        record = self.begin()
        self.ops.session = SESSION_B
        self.capture(record, lambda verify: SECRET)
        fresh = self.make_coordinator()
        request = fresh.reconstruct_request(record.operation_id, record.request_fingerprint)
        self.assertEqual(request, self.request)
        self.assertEqual(self.store.read().safe_dict()['outcome'], 'complete')
        self.assertNotIn(SECRET, self.store.path.read_text())
        self.assertFalse(hasattr(request, 'public_bundle'))
        self.assertFalse(hasattr(self.store.read(), 'public_bundle'))

    def test_durable_before_disable_and_shared_hold_visible(self):
        def disable(owner, value):
            current = self.store.read()
            self.assertEqual(current.phase, CapturePhase.PREPARING)
            self.assertEqual(self.coordinator.reconstruct_request(
                current.operation_id, current.request_fingerprint), self.request)
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

    def test_first_terminal_directory_failure_retains_visible_hold(self):
        record = self.begin()
        sync = self.store._sync_directory
        observed = []
        def fail_terminal(fd):
            current = CaptureStore(self.root).read()
            if current.phase is CapturePhase.CANCELLED:
                observed.append(capture_activation_holds(self.root))
                raise OSError('synthetic terminal barrier failure')
            sync(fd)
        with patch.object(self.store, '_sync_directory', side_effect=fail_terminal):
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(observed, [frozenset({REDLIGHT_ADDON_ID})])
        self.assertTrue(CaptureStore(self.root).read().held)

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

    def test_owner_setter_failure_before_effect_never_publishes_terminal(self):
        record = self.begin()
        with patch.object(self.ops, 'set_enabled', side_effect=OSError('synthetic setter failure')) as setter:
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.recover(record.operation_id, self.request)
        setter.assert_called_once_with(REDLIGHT_ADDON_ID, True)
        current = self.store.read()
        self.assertEqual(current.phase, CapturePhase.RESTORING)
        self.assertFalse(current.commit_pending)
        self.assertTrue(current.held)
        self.assertFalse(self.ops.current_enabled)

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
        self.assertEqual(phases, [CapturePhase.RESTORING, CapturePhase.CANCELLED, CapturePhase.CANCELLED])
        self.assertFalse(recovered.held)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_expired_reconstruction_fresh_process_then_safe_cancellation(self):
        import os
        import subprocess
        import sys
        record = self.begin()
        self.now = record.expires_at + 1
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        code = """import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from resources.lib.capture_lifecycle import CaptureStore, CaptureLifecycleCoordinator, request_fingerprint
root = Path(sys.argv[1])
operations = Mock()
c = CaptureLifecycleCoordinator(store=CaptureStore(root),
    restart_store=SimpleNamespace(directory=str(root)), operations=operations,
    clock=lambda: float(sys.argv[4]))
r = c.reconstruct_request_for_recovery(sys.argv[2], sys.argv[3])
assert request_fingerprint(r) == sys.argv[3]
assert operations.mock_calls == []
"""
        subprocess.run([sys.executable, '-c', code, str(self.root), record.operation_id,
                        record.request_fingerprint, str(self.now)], check=True,
                       env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        fresh = self.make_coordinator()
        operations = fresh.operations
        fresh.operations = Mock()
        restored = fresh.reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
        self.assertEqual(restored, self.request)
        self.assertEqual(fresh.operations.mock_calls, [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        fresh.operations = operations
        callback = Mock()
        for action in (lambda: fresh.reconstruct_request(record.operation_id, record.request_fingerprint),
                       lambda: fresh.begin(restored, confirmed=True),
                       lambda: fresh.capture(record.operation_id, restored, callback)):
            with self.assertRaises(CaptureLifecycleError):
                action()
        callback.assert_not_called()
        result = fresh.recover(record.operation_id, restored)
        self.assertEqual(result.phase, CapturePhase.CANCELLED)
        self.assertTrue(self.ops.current_enabled)
        self.assertFalse(result.held)
        self.assertEqual(capture_activation_holds(self.root), frozenset())
        self.assertNotIn(SECRET, self.store.path.read_text())

    def test_expired_reconstruction_originally_disabled_stays_disabled(self):
        self.ops.current_enabled = False
        record = self.begin()
        self.now = record.expires_at
        fresh = self.make_coordinator()
        request = fresh.reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
        result = fresh.recover(record.operation_id, request)
        self.assertFalse(result.held)
        self.assertFalse(self.ops.current_enabled)
        self.assertEqual(self.ops.mutations, [])

    def test_recovery_reconstruction_rollback_binding_and_unsafe_records(self):
        record = self.begin()
        original = self.store.path.read_bytes()
        for operation, fingerprint, now in ((SESSION_B, record.request_fingerprint, record.expires_at),
                (record.operation_id, 'sha256:' + '0' * 64, record.expires_at),
                (record.operation_id, record.request_fingerprint, record.created_at - 1)):
            self.now = now
            with self.assertRaises(CaptureLifecycleError):
                self.make_coordinator().reconstruct_request_for_recovery(operation, fingerprint)
            self.assertEqual(self.store.path.read_bytes(), original)
        self.now = record.expires_at + 1
        for defect in ('missing', 'corrupt', 'substituted', 'symlink', 'oversize'):
            self.store.path.unlink(missing_ok=True)
            if defect == 'corrupt':
                self.store.path.write_text(SECRET)
            elif defect == 'substituted':
                value = json.loads(original)
                metadata = json.loads(value['request_metadata'])
                metadata['description'] = SECRET
                value['request_metadata'] = json.dumps(metadata, sort_keys=True, separators=(',', ':'))
                self.store.path.write_text(json.dumps(value))
            elif defect == 'symlink':
                target = self.root / 'retained-request-evidence.json'
                target.write_bytes(original)
                self.store.path.symlink_to(target)
            elif defect == 'oversize':
                self.store.path.write_bytes(b'x' * 17000)
            with self.assertRaises(CaptureLifecycleError) as error:
                self.make_coordinator().reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
            self.assertNotIn(SECRET, str(error.exception))
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_expired_reconstructed_request_does_not_bypass_recovery_authority(self):
        record = self.begin()
        self.now = record.expires_at + 1
        fresh = self.make_coordinator()
        request = fresh.reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
        for defect in ('owner', 'competing', 'restart', 'install'):
            with self.subTest(defect=defect):
                with patch.object(self.ops, 'owner_version', return_value='2.6.9' if defect == 'owner' else REDLIGHT_VERSION), \
                     patch.object(self.ops, 'competing_operation', return_value=defect == 'competing'), \
                     ExitStack() as stack:
                    if defect in ('restart', 'install'):
                        name, data = self.competing_fixture('restart' if defect == 'restart' else 'frozen')
                        path = self.root / name
                        path.write_bytes(data)
                        stack.callback(path.unlink)
                    with self.assertRaises(CaptureLifecycleError):
                        fresh.recover(record.operation_id, request)
                self.assertEqual(self.store.read(), record)
                self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
                self.assertTrue(record.held)

    def test_expired_complete_reconstruction_has_no_build_or_capture_result(self):
        from resources.lib.build_library import BuildLibrary
        library_root = self.profile.resolve() / 'synthetic-build-library'
        library_root.mkdir()
        library = BuildLibrary(library_root)
        self.assertEqual(library.list_builds(), ())
        record = self.begin()
        self.ops.session = SESSION_B
        self.capture(record, lambda verify: SECRET)
        self.now = record.expires_at + 1
        fresh = self.make_coordinator()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        request = fresh.reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
        result = fresh.recover(record.operation_id, request)
        self.assertEqual(result.phase, CapturePhase.COMPLETE)
        self.assertEqual(request, self.request)
        self.assertFalse(hasattr(request, 'public_bundle'))
        self.assertFalse(hasattr(result, 'public_bundle'))
        self.assertNotIn(SECRET, self.store.path.read_text())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(library.list_builds(), ())
        self.assertEqual(list(library_root.iterdir()), [])

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
        fresh = self.make_coordinator()
        request = fresh.reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
        result = fresh.recover(record.operation_id, request)
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

    def competing_fixture(self, kind):
        if kind == 'restart':
            return 'restart_transaction.json', _transaction().to_json().encode()
        from resources.lib.frozen_install import FrozenInstallTransaction, FrozenInstallPhase
        from resources.lib.update_guard import AddonUpdatePolicy
        record = FrozenInstallTransaction(
            transaction_id=SESSION_B, build_id='fixture', manifest_path='/fixture.json',
            device_profile_id='desk', manifest_fingerprint='a' * 64,
            phase=FrozenInstallPhase.AWAITING_RESTART,
            originating_kodi_session_id=SESSION_A,
            original_update_policy=AddonUpdatePolicy.AUTOMATIC,
            created_at='2026-09-21T00:00:00Z', updated_at='2026-09-21T00:00:00Z')
        return 'frozen_install_transaction.json', json.dumps(record.to_dict()).encode()

    @contextmanager
    def competing_read_swap(self, filename):
        from resources.lib.readonly_io import read_regular_file
        retained = self.root.with_name('retained-state')
        calls = []

        def swapped(path, **kwargs):
            if Path(path).name != filename:
                return read_regular_file(path, **kwargs)
            calls.append(kwargs.get('dir_fd'))
            self.root.rename(retained)
            self.root.mkdir()
            try:
                return read_regular_file(path, **kwargs)
            finally:
                self.root.rmdir()
                retained.rename(self.root)

        with ExitStack() as stack:
            for module in ('capture_lifecycle', 'transaction', 'frozen_install'):
                stack.enter_context(patch('resources.lib.' + module + '.read_regular_file', side_effect=swapped))
            yield calls

    @contextmanager
    def competing_record_move(self, filename):
        import os
        from resources.lib.readonly_io import read_regular_file
        path = self.root / filename
        moved = self.root.parent / ('moved-' + filename)
        observations = []

        def read(pathname, **kwargs):
            if Path(pathname).name != filename:
                return read_regular_file(pathname, **kwargs)
            fd = kwargs['dir_fd']
            before = os.fstat(fd)
            path.rename(moved)
            try:
                raw = read_regular_file(pathname, **kwargs)
            finally:
                moved.rename(path)
            after = os.fstat(fd)
            observations.append((raw, (before.st_mtime_ns, before.st_ctime_ns),
                                 (after.st_mtime_ns, after.st_ctime_ns), fd))
            return raw

        with patch('resources.lib.capture_lifecycle.read_regular_file', side_effect=read):
            yield observations

    def assert_move_detected(self, observations):
        self.assertTrue(observations)
        for raw, before, after, fd in observations:
            self.assertIsNone(raw)
            self.assertNotEqual(before, after)
            self.assertIsInstance(fd, int)

    def test_restart_record_move_refuses_begin_without_setter(self):
        self.assert_record_move_refuses_begin('restart')

    def test_frozen_record_move_refuses_begin_without_setter(self):
        self.assert_record_move_refuses_begin('frozen')

    def assert_record_move_refuses_begin(self, kind):
        import os
        name, data = self.competing_fixture(kind)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / name
        path.write_bytes(data)
        with self.competing_record_move(name) as observations:
            with self.assertRaises(CaptureLifecycleError):
                self.begin()
        self.assert_move_detected(observations)
        self.assertEqual(self.ops.mutations, [])
        self.assertEqual(path.read_bytes(), data)
        self.assertIsNone(self.store.read())
        self.assertIsNone(self.store._transition_fd)
        self.assertEqual(self.store._held_locks, {})
        with self.assertRaises(OSError):
            os.fstat(observations[-1][3])
        # Failed observation leaves all three locks available.
        path.unlink()
        with self.coordinator._exclusive():
            pass

    def test_record_move_refuses_recovery_and_retains_hold(self):
        record = self.begin()
        name, data = self.competing_fixture('restart')
        path = self.root / name
        path.write_bytes(data)
        with self.competing_record_move(name) as observations:
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.recover(record.operation_id, self.request)
        self.assert_move_detected(observations)
        self.assertEqual(self.store.read(), record)
        self.assertTrue(record.held)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        self.assertFalse(self.ops.current_enabled)
        self.assertIsNone(self.store._transition_fd)
        self.assertEqual(self.store._held_locks, {})

    def test_record_moves_refuse_activation_and_locked_checked(self):
        record = self.begin()
        for kind in ('restart', 'frozen'):
            name, data = self.competing_fixture(kind)
            path = self.root / name
            # Hold the transition before injecting competing durable state.
            with self.coordinator._exclusive():
                path.write_bytes(data)
                try:
                    for action in (lambda: capture_activation_holds(self.root),
                                   lambda: self.coordinator._checked(record.operation_id, self.request)):
                        with self.subTest(kind=kind), self.competing_record_move(name) as observations:
                            before = {p.name: p.read_bytes() for p in self.root.iterdir()}
                            with self.assertRaises(CaptureLifecycleError):
                                action()
                            self.assert_move_detected(observations)
                            self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
                finally:
                    path.unlink()
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_record_move_refuses_capture_before_callback(self):
        record = self.begin()
        self.ops.session = SESSION_B
        callback = Mock()
        name, data = self.competing_fixture('restart')
        path = self.root / name
        path.write_bytes(data)
        with self.competing_record_move(name) as observations:
            with self.assertRaises(CaptureLifecycleError):
                self.capture(record, callback)
        self.assert_move_detected(observations)
        callback.assert_not_called()
        self.assertEqual(self.store.read(), record)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_transition_descriptor_sampled_once_and_invalid_descriptors_refused(self):
        import os
        from unittest.mock import PropertyMock
        self.root.mkdir(parents=True, exist_ok=True)
        with self.store._directory() as fd:
            with patch.object(CaptureStore, '_transition_fd', new_callable=PropertyMock, create=True) as pin:
                pin.side_effect = [fd, None]
                self.assertFalse(self.store.competing_records_present())
                self.assertEqual(pin.call_count, 1)
        for invalid in (-1, fd, True, 'invalid'):
            with self.subTest(fd=invalid):
                self.store._transition_fd = invalid
                try:
                    with patch('resources.lib.capture_lifecycle.read_regular_file') as read:
                        with self.assertRaises(CaptureLifecycleError):
                            self.store.competing_records_present()
                        read.assert_not_called()
                finally:
                    self.store._transition_fd = None
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_immediate_record_moves_change_timestamps_without_sleep(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for kind in ('restart', 'frozen'):
            name, data = self.competing_fixture(kind)
            path = self.root / name
            path.write_bytes(data)
            with self.competing_record_move(name) as observations:
                for iteration in range(50):
                    with self.subTest(kind=kind, iteration=iteration):
                        with self.assertRaises(CaptureLifecycleError):
                            self.store.competing_records_present()
            self.assertEqual(len(observations), 50)
            self.assert_move_detected(observations)
            self.assertEqual(path.read_bytes(), data)
            path.unlink()

    def test_competing_restart_swap_blocks_begin_before_setter(self):
        name, data = self.competing_fixture('restart')
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.joinpath(name).write_bytes(data)
        with self.competing_read_swap(name) as calls:
            with self.assertRaises(CaptureLifecycleError):
                self.begin()
        self.assertTrue(calls)
        self.assertTrue(all(fd is not None for fd in calls))
        self.assertIsNone(self.store._transition_fd)
        self.assertEqual(self.store._held_locks, {})
        self.assertEqual(self.ops.mutations, [])
        self.assertEqual(self.root.joinpath(name).read_bytes(), data)
        self.assertIsNone(self.store.read())

    def test_competing_frozen_swap_blocks_begin_before_setter(self):
        name, data = self.competing_fixture('frozen')
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.joinpath(name).write_bytes(data)
        with self.competing_read_swap(name) as calls:
            with self.assertRaises(CaptureLifecycleError):
                self.begin()
        self.assertTrue(calls)
        self.assertTrue(all(fd is not None for fd in calls))
        self.assertIsNone(self.store._transition_fd)
        self.assertEqual(self.store._held_locks, {})
        self.assertEqual(self.ops.mutations, [])
        self.assertEqual(self.root.joinpath(name).read_bytes(), data)
        self.assertIsNone(self.store.read())

    def test_competing_swaps_block_activation_and_checked_without_writes(self):
        record = self.begin()
        for kind in ('restart', 'frozen'):
            name, data = self.competing_fixture(kind)
            path = self.root / name
            path.write_bytes(data)
            for action in (lambda: capture_activation_holds(self.root),
                           lambda: self.coordinator._checked(record.operation_id, self.request)):
                with self.subTest(kind=kind, action=action), self.competing_read_swap(name) as calls:
                    before = {p.name: p.read_bytes() for p in self.root.iterdir()}
                    with self.assertRaises(CaptureLifecycleError):
                        action()
                    self.assertTrue(calls)
                    self.assertTrue(all(fd is not None for fd in calls))
                    self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
            path.unlink()
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_locked_checked_uses_transition_descriptor_and_cleans_up(self):
        import os
        record = self.begin()
        for kind in ('restart', 'frozen'):
            with self.subTest(kind=kind):
                name, data = self.competing_fixture(kind)
                path = self.root / name
                with self.coordinator._exclusive():
                    fd = self.store._transition_fd
                    path.write_bytes(data)
                    try:
                        with self.competing_read_swap(name) as calls:
                            with self.assertRaises(CaptureLifecycleError):
                                self.coordinator._checked(record.operation_id, self.request)
                        self.assertEqual(calls, [fd])
                    finally:
                        path.unlink()
                self.assertIsNone(self.store._transition_fd)
                self.assertEqual(self.store._held_locks, {})
                with self.assertRaises(OSError):
                    os.fstat(fd)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_capture_transition_excludes_existing_store_locks(self):
        with self.coordinator._exclusive():
            for lock in (self.restart.acquire_lock(), FrozenInstallStore(self.root, create=False).locked()):
                acquired = False
                with self.assertRaises(Exception):
                    with lock:
                        acquired = True
                self.assertFalse(acquired)
        with self.restart.acquire_lock(), FrozenInstallStore(self.root, create=False).locked():
            pass
        self.assertIsNone(self.store._transition_fd)
        self.assertEqual(self.store._held_locks, {})

    def test_absent_competing_observation_creates_nothing_and_clean_begin_succeeds(self):
        before = set(self.profile.rglob('*'))
        self.assertFalse(self.store.competing_records_present())
        self.assertEqual(capture_activation_holds(self.root), frozenset())
        self.assertEqual(before, set(self.profile.rglob('*')))
        record = self.begin()
        self.assertEqual(record.phase, CapturePhase.AWAITING_RESTART)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertFalse(self.store.competing_records_present())
        self.assertEqual(capture_activation_holds(self.root), frozenset({REDLIGHT_ADDON_ID}))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_invalid_competing_records_fail_closed_at_all_read_sites(self):
        from resources.lib.readonly_io import read_regular_file, ReadOnlyStateError
        record = self.begin()
        for kind in ('restart', 'frozen'):
            name, data = self.competing_fixture(kind)
            path = self.root / name
            for defect in ('malformed', 'unsupported', 'symlink', 'oversize', 'unreadable'):
                with self.subTest(kind=kind, defect=defect):
                    if defect == 'symlink':
                        path.symlink_to(self.store.path)
                    else:
                        path.write_bytes(b'{' if defect == 'malformed' else
                            b'{"schema_version":999}' if defect == 'unsupported' else
                            b'x' * (4 * 1024 * 1024 + 1) if defect == 'oversize' else data)
                    def read(pathname, **kwargs):
                        if defect == 'unreadable' and Path(pathname).name == name:
                            raise ReadOnlyStateError('synthetic denied read')
                        return read_regular_file(pathname, **kwargs)
                    with patch('resources.lib.capture_lifecycle.read_regular_file', side_effect=read):
                        for action in (self.begin, lambda: capture_activation_holds(self.root),
                                       lambda: self.coordinator._checked(record.operation_id, self.request)):
                            with self.assertRaises(CaptureLifecycleError):
                                action()
                    path.unlink()
        self.assertEqual(self.store.read(), record)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

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
        for index, lock in enumerate((self.restart.acquire_lock(), FrozenInstallStore(self.root).locked(), self.store.locked())):
            with self.subTest(lock=index), lock:
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
        with patch.object(CaptureStore, '_sync_directory', side_effect=OSError(SECRET)):
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
                        self.assertTrue(current.commit_pending)
                    self.assertTrue(current.held)
                    fresh = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                        operations=ops, clock=lambda: 1000)
                    recovered = fresh.recover(current.operation_id, self.request)
                    self.assertIs(ops.current_enabled, True)
                    self.assertFalse(recovered.held)

    def test_terminal_publication_failure_matrix(self):
        import os
        for outcome in ('cancelled', 'failed', 'complete'):
            for original in (False, True):
                for boundary in ('write', 'file_sync', 'pending_replace', 'pending_sync',
                                 'release_replace', 'release_sync'):
                    with self.subTest(outcome=outcome, original=original, boundary=boundary), \
                            tempfile.TemporaryDirectory() as profile:
                        restart = TransactionStore(profile)
                        store = CaptureStore(Path(restart.directory))
                        ops = Operations(original)
                        coordinator = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                            operations=ops, clock=lambda: 1000)
                        record = coordinator.begin(self.request, confirmed=True)
                        # The owner setter has completed, but no terminal was published.
                        restoring = replace(record, phase=CapturePhase.RESTORING, outcome=outcome,
                            capture_session_id=SESSION_B if outcome == 'complete' else '')
                        with store.locked():
                            store.save(record, restoring)
                        ops.current_enabled = original
                        mutations = list(ops.mutations)
                        replace_file, fsync, fdopen, sync = os.replace, os.fsync, os.fdopen, store._sync_directory
                        publications, barriers = [], []
                        def publish(source, destination, **kwargs):
                            stage = 'release' if publications else 'pending'
                            if boundary == stage + '_replace':
                                raise OSError('synthetic replace failure')
                            replace_file(source, destination, **kwargs)
                            current = CaptureStore(store.root).read()
                            publications.append(current)
                            self.assertEqual(current.commit_pending, stage == 'pending')
                            self.assertEqual(ops.mutations, mutations)
                        def barrier(fd):
                            stage = 'pending' if len(publications) == 1 else 'release'
                            barriers.append(stage)
                            if boundary == stage + '_sync':
                                raise OSError('synthetic directory barrier failure')
                            sync(fd)
                        def file_sync(fd):
                            if boundary == 'file_sync':
                                raise OSError('synthetic file barrier failure')
                            fsync(fd)
                        def open_output(*args, **kwargs):
                            output = fdopen(*args, **kwargs)
                            if boundary == 'write':
                                proxy = Mock(wraps=output)
                                proxy.write.side_effect = OSError('synthetic write failure')
                                proxy.__enter__ = Mock(return_value=proxy)
                                proxy.__exit__ = Mock(side_effect=lambda *unused: output.close())
                                return proxy
                            return output
                        with patch('resources.lib.capture_lifecycle.os.replace', side_effect=publish), \
                                patch('resources.lib.capture_lifecycle.os.fsync', side_effect=file_sync), \
                                patch('resources.lib.capture_lifecycle.os.fdopen', side_effect=open_output), \
                                patch.object(store, '_sync_directory', side_effect=barrier):
                            with self.assertRaises(CaptureLifecycleError):
                                coordinator.recover(record.operation_id, self.request)
                        current = CaptureStore(store.root).read()
                        self.assertEqual(current.held, boundary != 'release_sync')
                        self.assertEqual(current.outcome, outcome)
                        self.assertEqual(ops.mutations, mutations)
                        self.assertFalse(list(store.root.glob('*.tmp')))
                        if boundary in ('release_replace', 'release_sync'):
                            self.assertEqual(barriers[0], 'pending')
                        # Fresh retry keeps the outcome even if cancellation is requested.
                        saves = []
                        save = store.save
                        def retry_save(expected, candidate):
                            saves.append(candidate)
                            return save(expected, candidate)
                        with patch.object(store, 'save', side_effect=retry_save):
                            result = coordinator.recover(record.operation_id, self.request)
                            self.assertEqual(coordinator.recover(record.operation_id, self.request), result)
                        self.assertEqual(result.outcome, outcome)
                        self.assertFalse(result.held)
                        self.assertEqual(ops.mutations, mutations)
                        if current.commit_pending:
                            self.assertEqual([r.commit_pending for r in saves], [True, False])
                        elif not current.held:
                            self.assertEqual(saves, [])

    def test_all_ordinary_outcomes_use_two_terminal_publications(self):
        for outcome in ('cancelled', 'failed', 'complete'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as profile:
                restart = TransactionStore(profile)
                store = CaptureStore(Path(restart.directory))
                ops = Operations()
                coordinator = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                    operations=ops, clock=lambda: 1000)
                record = coordinator.begin(self.request, confirmed=True)
                sync = store._sync_directory
                observations = []
                def barrier(fd):
                    current = CaptureStore(store.root).read()
                    if current.phase.value == outcome:
                        observations.append((current.commit_pending, current.held, list(ops.mutations)))
                    sync(fd)
                with patch.object(store, '_sync_directory', side_effect=barrier):
                    if outcome == 'cancelled':
                        coordinator.recover(record.operation_id, self.request)
                    else:
                        ops.session = SESSION_B
                        def callback(verify):
                            verify()
                            if outcome == 'failed':
                                raise ValueError('synthetic capture failure')
                        if outcome == 'failed':
                            with self.assertRaises(CaptureLifecycleError):
                                coordinator.capture(record.operation_id, self.request, callback)
                        else:
                            coordinator.capture(record.operation_id, self.request, callback)
                self.assertEqual([(p, h) for p, h, _ in observations], [(True, True), (False, False)])
                self.assertEqual(observations[0][2], observations[1][2])

    def pending_terminal(self, outcome='cancelled'):
        record = self.begin()
        pending = replace(record, phase=CapturePhase(outcome), outcome=outcome, commit_pending=True,
                          capture_session_id=SESSION_B if outcome == 'complete' else '')
        with self.store.locked():
            self.store.save(record, pending)
        self.ops.current_enabled = record.original_enabled
        return pending

    def test_pending_terminal_refuses_drift_and_wrong_request_without_setter(self):
        record = self.pending_terminal('complete')
        mutations = list(self.ops.mutations)
        before = self.store.path.read_bytes()
        for defect in ('version', 'enablement', 'unknown', 'request', 'operation', 'competing'):
            with self.subTest(defect=defect):
                self.ops.version = '2.6.9' if defect == 'version' else REDLIGHT_VERSION
                self.ops.current_enabled = False if defect == 'enablement' else None if defect == 'unknown' else True
                self.ops.competing = defect == 'competing'
                with self.assertRaises(CaptureLifecycleError):
                    self.coordinator.recover(SESSION_B if defect == 'operation' else record.operation_id,
                        replace(self.request, description='changed') if defect == 'request' else self.request)
                self.assertEqual(self.store.path.read_bytes(), before)
                self.assertEqual(self.ops.mutations, mutations)
                self.assertTrue(self.store.read().held)

    def test_pending_finalization_failure_requires_fresh_publication_again(self):
        record = self.pending_terminal('failed')
        mutations = list(self.ops.mutations)
        replacements = []
        import os
        publish = os.replace
        def observe(*args, **kwargs):
            publish(*args, **kwargs)
            replacements.append(CaptureStore(self.root).read())
        with patch('resources.lib.capture_lifecycle.os.replace', side_effect=observe), \
                patch.object(self.store, '_sync_directory', side_effect=OSError('failed retry barrier')):
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(replacements, [record])
        self.assertEqual(self.store.read(), record)
        self.assertTrue(self.store.read().held)
        with patch('resources.lib.capture_lifecycle.os.replace', side_effect=observe):
            released = self.make_coordinator().recover(record.operation_id, self.request)
        self.assertEqual(replacements, [record, record, replace(record, commit_pending=False)])
        self.assertEqual(released, replace(record, commit_pending=False))
        self.assertEqual(self.ops.mutations, mutations)

    def test_drift_between_terminal_publications_preserves_pending_hold(self):
        for drift in ('version', 'enablement', 'record'):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as profile:
                restart = TransactionStore(profile)
                store = CaptureStore(Path(restart.directory))
                ops = Operations()
                c = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                    operations=ops, clock=lambda: 1000)
                record = c.begin(self.request, confirmed=True)
                sync = store._sync_directory
                def barrier(fd):
                    sync(fd)
                    current = store.read()
                    if current.commit_pending:
                        if drift == 'version':
                            ops.version = '2.6.9'
                        elif drift == 'enablement':
                            ops.current_enabled = False
                        else:
                            store.path.write_text(json.dumps(replace(current,
                                operation_id=SESSION_B).to_dict()))
                with patch.object(store, '_sync_directory', side_effect=barrier):
                    with self.assertRaises(CaptureLifecycleError):
                        c.recover(record.operation_id, self.request)
                self.assertTrue(store.read().commit_pending)
                self.assertTrue(store.read().held)
                self.assertEqual(ops.mutations, [(REDLIGHT_ADDON_ID, False), (REDLIGHT_ADDON_ID, True)])

    def test_pending_terminal_shared_guards_are_creation_free_and_block_admission(self):
        import os
        record = self.pending_terminal()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        original_open = os.open
        def readonly(path, flags, *args, **kwargs):
            self.assertFalse(flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR | os.O_TRUNC))
            return original_open(path, flags, *args, **kwargs)
        with patch('os.open', side_effect=readonly), \
                patch.object(CaptureStore, '_lock', side_effect=AssertionError('new lock')):
            self.assertEqual(capture_activation_holds(self.root), frozenset({REDLIGHT_ADDON_ID}))
            self.assertEqual(active_activation_hold_ids(FrozenInstallStore(self.root, create=False)),
                             frozenset({REDLIGHT_ADDON_ID}))
            with self.assertRaises(CaptureLifecycleError):
                require_no_capture(self.root)
            with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.root):
                with self.assertRaises(ActivationHoldError):
                    reject_held_activation(REDLIGHT_ADDON_ID)
        callback = Mock()
        mutations = list(self.ops.mutations)
        for action in (lambda: self.begin(), lambda: self.capture(record, callback),
                       lambda: self.restart.create(_transaction()),
                       lambda: FrozenInstallStore(self.root).create(Mock())):
            with self.assertRaises(Exception):
                action()
        from resources.lib.build_manager import BuildManager
        from resources.lib.frozen_install import FrozenInstallCoordinator
        manager = BuildManager(Mock())
        with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=self.root), \
                patch.object(manager, '_prepare') as prepare:
            self.assertEqual(manager.reconcile(_transaction().request).failure.code, 'CAPTURE_LIFECYCLE_BLOCKED')
            prepare.assert_not_called()
        installer = FrozenInstallCoordinator(artifact_store=Mock(), installer=Mock(),
            store=FrozenInstallStore(self.root), policy_backend=Mock())
        with patch('resources.lib.build_library.authoritative_build_library') as next_stage:
            self.assertEqual(installer.install(Mock(), manifest_path='/unused', device_profile_id='desk').code,
                             'CAPTURE_LIFECYCLE_BLOCKED')
            next_stage.assert_not_called()
        restart_manager = Mock()
        self.assertFalse(RestartCoordinator(restart_manager, store=self.restart)
                         .reconcile(_transaction().request).reconcile_result.success)
        restart_manager.reconcile.assert_not_called()
        callback.assert_not_called()
        self.assertEqual(self.ops.mutations, mutations)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_commit_pending_strict_validation_and_legacy_released_recovery(self):
        record = self.pending_terminal()
        raw = record.to_dict()
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value=value):
                self.store.path.write_text(json.dumps({**raw, 'commit_pending': value}))
                with self.assertRaises(CaptureLifecycleError):
                    capture_activation_holds(self.root)
        for phase in (CapturePhase.PREPARING, CapturePhase.AWAITING_RESTART,
                      CapturePhase.CAPTURING, CapturePhase.RESTORING):
            with self.assertRaises(CaptureLifecycleError):
                replace(record, phase=phase, outcome='cancelled' if phase is CapturePhase.RESTORING else '',
                        capture_session_id=SESSION_B if phase is CapturePhase.CAPTURING else '')
        with self.assertRaises(CaptureLifecycleError):
            replace(record, outcome='failed')
        legacy = {**raw}
        del legacy['commit_pending']
        self.store.path.write_text(json.dumps(legacy))
        before = self.store.path.read_bytes()
        with patch.object(self.store, 'save', side_effect=AssertionError('legacy mutation')):
            result = self.coordinator.recover(record.operation_id, self.request)
        self.assertFalse(result.held)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_cross_process_terminal_visibility_at_both_barriers(self):
        import os
        import subprocess
        import sys
        record = self.begin()
        sync = self.store._sync_directory
        observed = []
        code = '''import sys
from pathlib import Path
from resources.lib.capture_lifecycle import CaptureStore, capture_activation_holds
root = Path(sys.argv[1])
r = CaptureStore(root).read()
assert r.operation_id == sys.argv[2]
assert r.commit_pending is (sys.argv[3] == 'True')
assert r.held is r.commit_pending
assert capture_activation_holds(root) == (frozenset({r.owner_id}) if r.commit_pending else frozenset())
'''
        def observe(fd):
            current = self.store.read()
            if current.phase is CapturePhase.CANCELLED:
                subprocess.run([sys.executable, '-c', code, str(self.root), record.operation_id,
                                str(current.commit_pending)], check=True,
                               env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                observed.append(current.commit_pending)
            sync(fd)
        with patch.object(self.store, '_sync_directory', side_effect=observe):
            self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(observed, [True, False])

    def test_process_exit_at_each_terminal_publication_and_barrier(self):
        import os
        import subprocess
        import sys
        code = '''import os, sys
from pathlib import Path
from unittest.mock import patch
from resources.lib.capture_lifecycle import CaptureStore, CaptureLifecycleCoordinator
from resources.lib.transaction import TransactionStore
from tests.test_capture_lifecycle import Operations
root = Path(sys.argv[1])
store = CaptureStore(root)
record = store.read()
ops = Operations(record.original_enabled)
ops.set_enabled = lambda *args: os._exit(91)
c = CaptureLifecycleCoordinator(store=store, restart_store=TransactionStore(sys.argv[2]),
    operations=ops, clock=lambda: 1000)
request = c.reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
stage, event, timing = sys.argv[3:]
counts = {'replace': 0, 'sync': 0}
publish, sync = os.replace, store._sync_directory
def boundary(kind, operation, *args, **kwargs):
    counts[kind] += 1
    current_stage = 'pending' if counts[kind] == 1 else 'release'
    hit = current_stage == stage and kind == event
    if hit and timing == 'before': os._exit(73)
    result = operation(*args, **kwargs)
    if hit and timing == 'after': os._exit(73)
    return result
with patch('resources.lib.capture_lifecycle.os.replace',
           side_effect=lambda *a, **kw: boundary('replace', publish, *a, **kw)), \
     patch.object(store, '_sync_directory', side_effect=lambda fd: boundary('sync', sync, fd)):
    c.recover(record.operation_id, request)
os._exit(92)
'''
        for stage in ('pending', 'release'):
            for event in ('replace', 'sync'):
                for timing in ('before', 'after'):
                    with self.subTest(stage=stage, event=event, timing=timing), \
                            tempfile.TemporaryDirectory() as profile:
                        restart = TransactionStore(profile)
                        store = CaptureStore(Path(restart.directory))
                        ops = Operations()
                        c = CaptureLifecycleCoordinator(store=store, restart_store=restart,
                            operations=ops, clock=lambda: 1000)
                        record = c.begin(self.request, confirmed=True)
                        restoring = replace(record, phase=CapturePhase.RESTORING, outcome='cancelled')
                        with store.locked():
                            store.save(record, restoring)
                        ops.current_enabled = True
                        result = subprocess.run([sys.executable, '-c', code, str(store.root), profile,
                                                 stage, event, timing],
                                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                        self.assertEqual(result.returncode, 73)
                        current = CaptureStore(store.root).read()
                        released = stage == 'release' and (event == 'sync' or timing == 'after')
                        self.assertEqual(current.held, not released)
                        if stage == 'pending' and event == 'replace' and timing == 'before':
                            self.assertEqual(current, restoring)
                        elif not released:
                            self.assertTrue(current.commit_pending)
                        self.assertEqual(current.operation_id, record.operation_id)
                        self.assertEqual(current.request_metadata, record.request_metadata)
                        mutations = list(ops.mutations)
                        recovered = c.recover(record.operation_id, self.request)
                        self.assertFalse(recovered.held)
                        self.assertEqual(recovered.outcome, 'cancelled')
                        self.assertEqual(c.recover(record.operation_id, self.request), recovered)
                        self.assertEqual(ops.mutations, mutations)

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



class D2RecoveryTests(unittest.TestCase):
    setUp = CaptureLifecycleTests.setUp
    make_coordinator = CaptureLifecycleTests.make_coordinator
    begin = CaptureLifecycleTests.begin
    capture = CaptureLifecycleTests.capture

    def candidate(self):
        self.ops.current_enabled = False
        record = self.begin()
        self.ops.current_enabled = True
        return record, self.coordinator.prepare_d2_confirmation(record.operation_id, self.request)

    def confirm(self, record, confirmation, confirmed=True):
        return self.coordinator.recover_d2(record.operation_id, self.request,
            confirmation=confirmation, confirmed=confirmed)

    def assert_protected(self):
        self.assertTrue(CaptureStore(self.root).read().held)
        self.assertEqual(capture_activation_holds(self.root), frozenset({REDLIGHT_ADDON_ID}))
        self.assertEqual(active_activation_hold_ids(FrozenInstallStore(self.root, create=False)),
                         frozenset({REDLIGHT_ADDON_ID}))
        with self.assertRaises(CaptureLifecycleError):
            require_no_capture(self.root)
        self.assertEqual(self.store._held_locks, {})
        self.assertIsNone(self.store._transition_fd)

    def test_decline_or_missing_confirmation_is_creation_free(self):
        record, confirmation = self.candidate()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch.object(self.store, '_lock', side_effect=AssertionError('lock on decline')):
            for consent, confirmed in ((confirmation, False), (confirmation, 1), (None, True)):
                with self.assertRaises(CaptureLifecycleError):
                    self.confirm(record, consent, confirmed)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(self.ops.mutations, [])
        self.assertFalse(self.store.read().d2_consent_id)
        self.assert_protected()

    def test_success_durable_consent_exact_owner_lock_order_and_p5(self):
        record, confirmation = self.candidate()
        setter, sync = self.ops.set_enabled, self.store._sync_directory
        barriers = []
        def barrier(fd):
            current = CaptureStore(self.root).read()
            barriers.append((current.phase, current.commit_pending, current.held))
            if current.held:
                self.assertEqual(capture_activation_holds(self.root), frozenset({REDLIGHT_ADDON_ID}))
            sync(fd)
        def disable(owner, value):
            current = CaptureStore(self.root).read()
            self.assertEqual(barriers, [(CapturePhase.RESTORING, False, True)])
            self.assertEqual(current.d2_consent_id, confirmation.consent_id)
            self.assertEqual(current.outcome, 'cancelled')
            self.assertFalse(current.original_enabled)
            self.assertEqual(list(self.store._held_locks), ['create_capture_transaction.lock',
                'frozen_install_transaction.lock', Path(self.restart.lock_path).name])
            self.assertEqual((owner, value), (REDLIGHT_ADDON_ID, False))
            setter(owner, value)
        with patch.object(self.store, '_sync_directory', side_effect=barrier), \
                patch.object(self.ops, 'set_enabled', side_effect=disable):
            result = self.confirm(record, confirmation)
        self.assertEqual(barriers, [(CapturePhase.RESTORING, False, True),
            (CapturePhase.CANCELLED, True, True), (CapturePhase.CANCELLED, False, False)])
        self.assertEqual(result, self.store.read())
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        self.assertFalse(result.held)
        self.assertEqual(self.make_coordinator().recover(record.operation_id, self.request, cancelled=False), result)
        self.assertNotIn(SECRET, self.store.path.read_text())
        self.assertNotIn('request_metadata', repr(confirmation))
        self.assertEqual(set(result.safe_dict()), {'operation_id', 'phase', 'held', 'outcome'})

    def test_intent_io_failure_matrix_requires_fresh_consent_and_barrier(self):
        import os
        for boundary in ('write', 'flush', 'file_sync', 'replace', 'directory_sync'):
            with self.subTest(boundary=boundary):
                self.setUp()
                record, confirmation = self.candidate()
                fdopen, fsync, publish, sync = os.fdopen, os.fsync, os.replace, self.store._sync_directory
                def open_output(*args, **kwargs):
                    output = fdopen(*args, **kwargs)
                    if boundary in ('write', 'flush'):
                        proxy = Mock(wraps=output)
                        getattr(proxy, boundary).side_effect = OSError(SECRET)
                        proxy.__enter__ = Mock(return_value=proxy)
                        proxy.__exit__ = Mock(side_effect=lambda *unused: output.close())
                        return proxy
                    return output
                def file_sync(fd):
                    if boundary == 'file_sync':
                        raise OSError(SECRET)
                    return fsync(fd)
                def replace_file(*args, **kwargs):
                    if boundary == 'replace':
                        raise OSError(SECRET)
                    return publish(*args, **kwargs)
                def barrier(fd):
                    if boundary == 'directory_sync':
                        raise OSError(SECRET)
                    return sync(fd)
                with patch('resources.lib.capture_lifecycle.os.fdopen', side_effect=open_output), \
                        patch('resources.lib.capture_lifecycle.os.fsync', side_effect=file_sync), \
                        patch('resources.lib.capture_lifecycle.os.replace', side_effect=replace_file), \
                        patch.object(self.store, '_sync_directory', side_effect=barrier):
                    with self.assertRaises(CaptureLifecycleError) as error:
                        self.confirm(record, confirmation)
                self.assertNotIn(SECRET, str(error.exception))
                self.assertEqual(self.ops.mutations, [])
                self.assert_protected()
                self.assertFalse(list(self.root.glob('*.tmp')))
                current = self.store.read()
                self.assertEqual(bool(current.d2_consent_id), boundary == 'directory_sync')
                fresh = self.make_coordinator()
                with self.assertRaises(CaptureLifecycleError):
                    fresh.recover(record.operation_id, self.request)
                renewed = fresh.prepare_d2_confirmation(record.operation_id, self.request)
                barrier_observations = []
                def retry_barrier(fd):
                    barrier_observations.append(self.store.read().d2_consent_id)
                    return sync(fd)
                setter = self.ops.set_enabled
                def retry_setter(owner, value):
                    self.assertEqual(barrier_observations, [renewed.consent_id])
                    setter(owner, value)
                with patch.object(self.store, '_sync_directory', side_effect=retry_barrier), \
                        patch.object(self.ops, 'set_enabled', side_effect=retry_setter):
                    result = fresh.recover_d2(record.operation_id, self.request,
                        confirmation=renewed, confirmed=True)
                self.assertFalse(result.held)
                self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_crash_boundaries_before_during_after_setter(self):
        for boundary in ('before_intent', 'after_intent', 'setter_before', 'setter_after',
                         'after_verification', 'before_pending', 'after_pending', 'before_release', 'after_release'):
            with self.subTest(boundary=boundary):
                self.setUp()
                record, confirmation = self.candidate()
                save, setter = self.store.save, self.ops.set_enabled
                checked = self.coordinator._terminal_checked
                def publication(expected, replacement):
                    stage = ('intent' if replacement.phase is CapturePhase.RESTORING else
                             'pending' if replacement.commit_pending else 'release')
                    if boundary == 'before_' + stage:
                        raise KeyboardInterrupt()
                    result = save(expected, replacement)
                    if boundary == 'after_' + stage:
                        raise KeyboardInterrupt()
                    return result
                def mutation(owner, value):
                    if boundary == 'setter_before':
                        raise KeyboardInterrupt()
                    setter(owner, value)
                    if boundary == 'setter_after':
                        raise KeyboardInterrupt()
                def verification(*args, **kwargs):
                    checked(*args, **kwargs)
                    if boundary == 'after_verification':
                        raise KeyboardInterrupt()
                with patch.object(self.store, 'save', side_effect=publication), \
                        patch.object(self.ops, 'set_enabled', side_effect=mutation), \
                        patch.object(self.coordinator, '_terminal_checked', side_effect=verification):
                    with self.assertRaises(KeyboardInterrupt):
                        self.confirm(record, confirmation)
                current = self.store.read()
                self.assertEqual(current.held, boundary != 'after_release')
                self.assertEqual(self.store._held_locks, {})
                self.assertIsNone(self.store._transition_fd)
                fresh = self.make_coordinator()
                reconstructed = fresh.reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
                if self.ops.current_enabled:
                    mutations = list(self.ops.mutations)
                    with self.assertRaises(CaptureLifecycleError):
                        fresh.recover(record.operation_id, reconstructed)
                    self.assertEqual(mutations, self.ops.mutations)
                    renewed = fresh.prepare_d2_confirmation(record.operation_id, reconstructed)
                    result = fresh.recover_d2(record.operation_id, reconstructed,
                        confirmation=renewed, confirmed=True)
                else:
                    result = fresh.recover(record.operation_id, reconstructed, cancelled=False)
                self.assertEqual(result.phase, CapturePhase.CANCELLED)
                self.assertFalse(result.held)
                self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_external_reenable_after_uncertain_setter_requires_renewed_consent(self):
        record, confirmation = self.candidate()
        setter = self.ops.set_enabled
        def uncertain(owner, value):
            setter(owner, value)
            raise RuntimeError(SECRET)
        with patch.object(self.ops, 'set_enabled', side_effect=uncertain):
            with self.assertRaises(CaptureLifecycleError):
                self.confirm(record, confirmation)
        self.ops.current_enabled = True  # Later independent operator action.
        fresh = self.make_coordinator()
        before = self.store.path.read_bytes()
        with self.assertRaises(CaptureLifecycleError):
            fresh.recover(record.operation_id, self.request)
        with self.assertRaises(CaptureLifecycleError):
            fresh.recover_d2(record.operation_id, self.request, confirmation=confirmation, confirmed=True)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        self.assert_protected()
        renewed = fresh.prepare_d2_confirmation(record.operation_id, self.request)
        result = fresh.recover_d2(record.operation_id, self.request, confirmation=renewed, confirmed=True)
        self.assertFalse(result.held)
        self.assertNotEqual(result.d2_consent_id, confirmation.consent_id)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)] * 2)

    def test_ambiguous_effect_remains_held_without_generic_replay(self):
        for effect in ('enabled', None, 1):
            self.setUp()
            record, confirmation = self.candidate()
            def setter(owner, value):
                self.ops.current_enabled = True if effect == 'enabled' else effect
            with patch.object(self.ops, 'set_enabled', side_effect=setter):
                with self.assertRaises(CaptureLifecycleError):
                    self.confirm(record, confirmation)
            self.assert_protected()
            with patch.object(self.ops, 'set_enabled', side_effect=AssertionError('replay')):
                with self.assertRaises(CaptureLifecycleError):
                    self.make_coordinator().recover(record.operation_id, self.request)

    def test_p5_write_and_barrier_failures_keep_d2_outcome_and_no_replay(self):
        import os
        for stage in ('pending', 'release'):
            for boundary in ('write', 'flush', 'file_sync', 'replace', 'directory_sync'):
                with self.subTest(stage=stage, boundary=boundary):
                    self.setUp()
                    record, confirmation = self.candidate()
                    save, fdopen, fsync, publish, sync = self.store.save, os.fdopen, os.fsync, os.replace, self.store._sync_directory
                    current_stage = ''
                    def saving(expected, replacement):
                        nonlocal current_stage
                        current_stage = ('intent' if replacement.phase is CapturePhase.RESTORING else
                                         'pending' if replacement.commit_pending else 'release')
                        return save(expected, replacement)
                    def fail_at(name):
                        if current_stage == stage and boundary == name:
                            raise OSError(SECRET)
                    def open_output(*args, **kwargs):
                        output = fdopen(*args, **kwargs)
                        if current_stage == stage and boundary in ('write', 'flush'):
                            proxy = Mock(wraps=output)
                            getattr(proxy, boundary).side_effect = OSError(SECRET)
                            proxy.__enter__ = Mock(return_value=proxy)
                            proxy.__exit__ = Mock(side_effect=lambda *unused: output.close())
                            return proxy
                        return output
                    def file_sync(fd):
                        fail_at('file_sync')
                        return fsync(fd)
                    def replace_file(*args, **kwargs):
                        fail_at('replace')
                        return publish(*args, **kwargs)
                    def barrier(fd):
                        fail_at('directory_sync')
                        return sync(fd)
                    with patch.object(self.store, 'save', side_effect=saving), \
                            patch('resources.lib.capture_lifecycle.os.fdopen', side_effect=open_output), \
                            patch('resources.lib.capture_lifecycle.os.fsync', side_effect=file_sync), \
                            patch('resources.lib.capture_lifecycle.os.replace', side_effect=replace_file), \
                            patch.object(self.store, '_sync_directory', side_effect=barrier):
                        with self.assertRaises(CaptureLifecycleError) as error:
                            self.confirm(record, confirmation)
                    self.assertNotIn(SECRET, str(error.exception))
                    current = self.store.read()
                    self.assertEqual(current.held, (stage, boundary) != ('release', 'directory_sync'))
                    self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
                    if current.held:
                        self.assert_protected()
                    result = self.make_coordinator().recover(record.operation_id, self.request, cancelled=False)
                    self.assertEqual(result.phase, CapturePhase.CANCELLED)
                    self.assertFalse(result.held)
                    self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_stale_and_mismatched_evidence_refused_without_write(self):
        for defect in ('operation', 'request', 'record', 'version', 'unknown', 'disabled',
                       'active', 'restart', 'frozen', 'corrupt', 'legacy'):
            with self.subTest(defect=defect):
                self.setUp()
                record, confirmation = self.candidate()
                operation, request = record.operation_id, self.request
                if defect == 'operation':
                    operation = SESSION_B
                elif defect == 'request':
                    request = replace(request, build_name='Changed')
                elif defect == 'record':
                    with self.store.locked():
                        self.store.save(record, replace(record, expires_at=record.expires_at - 1))
                elif defect == 'version':
                    self.ops.version = 'changed'
                elif defect == 'unknown':
                    self.ops.current_enabled = 1
                elif defect == 'disabled':
                    self.ops.current_enabled = False
                elif defect == 'active':
                    self.ops.competing = True
                elif defect == 'restart':
                    Path(self.restart.transaction_path).write_text(_transaction().to_json())
                elif defect == 'frozen':
                    name, raw = CaptureLifecycleTests.competing_fixture(self, 'frozen')
                    self.root.joinpath(name).write_bytes(raw)
                elif defect == 'corrupt':
                    self.store.path.write_text('{}')
                else:
                    with self.store.locked():
                        self.store.save(record, replace(record, request_metadata=''))
                before = self.store.path.read_bytes()
                with self.assertRaises(CaptureLifecycleError):
                    self.coordinator.recover_d2(operation, request, confirmation=confirmation, confirmed=True)
                self.assertEqual(before, self.store.path.read_bytes())
                self.assertEqual(self.ops.mutations, [])
                self.assertEqual(self.store._held_locks, {})
                self.assertIsNone(self.store._transition_fd)

    def test_terminal_pending_and_originally_enabled_cannot_acquire_consent(self):
        for source in ('enabled', 'terminal', 'pending'):
            self.setUp()
            self.ops.current_enabled = source == 'enabled'
            record = self.begin()
            if source != 'enabled':
                record = self.coordinator.recover(record.operation_id, self.request)
                if source == 'pending':
                    with self.store.locked():
                        record = self.store.save(record, replace(record, commit_pending=True))
            self.ops.current_enabled = True
            before = self.store.path.read_bytes()
            with self.assertRaises(CaptureLifecycleError):
                self.coordinator.prepare_d2_confirmation(record.operation_id, self.request)
            with self.assertRaises(CaptureLifecycleError):
                D2Confirmation(record, SESSION_B)
            self.assertEqual(before, self.store.path.read_bytes())

    def test_strict_d2_schema_and_legacy_compatibility(self):
        record, confirmation = self.candidate()
        legacy = record.to_dict()
        for field in ('d2_consent_id', 'd2_source_digest', 'd2_binding', 'commit_pending'):
            del legacy[field]
        self.assertEqual(CaptureTransaction.from_dict(legacy), record)
        self.confirm(record, confirmation)
        raw = self.store.read().to_dict()
        for field, value in (('d2_consent_id', ''), ('d2_consent_id', SESSION_A),
                             ('d2_source_digest', ''), ('d2_binding', True),
                             ('d2_binding', 'sha256:' + '0' * 64), ('original_enabled', True),
                             ('operation_id', SESSION_B), ('request_metadata', ''),
                             ('phase', 'failed'), ('outcome', 'failed')):
            with self.subTest(field=field):
                with self.assertRaises(CaptureLifecycleError):
                    CaptureTransaction.from_dict({**raw, field: value})
        for field in ('d2_consent_id', 'd2_source_digest', 'd2_binding'):
            incomplete = dict(raw)
            del incomplete[field]
            with self.assertRaises(CaptureLifecycleError):
                CaptureTransaction.from_dict(incomplete)
        for field, value in (('observed_enabled', 1), ('target_enabled', 0), ('outcome', 'failed')):
            with self.assertRaises(CaptureLifecycleError):
                replace(confirmation, **{field: value})

    def test_unconfirmed_generic_recovery_and_expired_d2(self):
        record, confirmation = self.candidate()
        self.now = record.expires_at + 1
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.recover(record.operation_id, self.request)
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.reconstruct_request(record.operation_id, record.request_fingerprint)
        request = self.coordinator.reconstruct_request_for_recovery(record.operation_id, record.request_fingerprint)
        result = self.coordinator.recover_d2(record.operation_id, request, confirmation=confirmation, confirmed=True)
        self.assertFalse(result.held)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_drift_after_intent_barrier_blocks_owner_mutation(self):
        for defect in ('owner', 'active', 'record', 'root', 'lock', 'unknown'):
            with self.subTest(defect=defect):
                self.setUp()
                record, confirmation = self.candidate()
                save = self.store.save
                def drift(expected, replacement):
                    result = save(expected, replacement)
                    if defect == 'owner':
                        self.ops.version = 'changed'
                    elif defect == 'active':
                        self.ops.competing = True
                    elif defect == 'record':
                        self.store.path.write_text('{}')
                    elif defect == 'root':
                        self.root.rename(self.root.with_name('retained-root'))
                        self.root.mkdir()
                    elif defect == 'lock':
                        lock = self.root / 'create_capture_transaction.lock'
                        lock.rename(lock.with_suffix('.retained'))
                        lock.write_text('')
                    else:
                        self.ops.current_enabled = None
                    return result
                with patch.object(self.store, 'save', side_effect=drift):
                    with self.assertRaises(CaptureLifecycleError):
                        self.confirm(record, confirmation)
                self.assertEqual(self.ops.mutations, [])
                self.assertEqual(self.store._held_locks, {})
                self.assertIsNone(self.store._transition_fd)

    def pending_terminal(self):
        record, confirmation = self.candidate()
        save = self.store.save
        def stop_pending(expected, replacement):
            result = save(expected, replacement)
            if replacement.commit_pending:
                raise KeyboardInterrupt()
            return result
        with patch.object(self.store, 'save', side_effect=stop_pending):
            with self.assertRaises(KeyboardInterrupt):
                self.confirm(record, confirmation)
        return self.store.read()

    def test_d2_pending_terminal_shared_guards(self):
        CaptureLifecycleTests.test_pending_terminal_shared_guards_are_creation_free_and_block_admission(self)

    def test_d2_lock_contention_retains_snapshot_and_closes_descriptors(self):
        import os
        record, confirmation = self.candidate()
        before = self.store.path.read_bytes()
        for lock in (self.restart.acquire_lock(), FrozenInstallStore(self.root).locked(), self.store.locked()):
            with lock:
                with self.assertRaises(CaptureLifecycleError):
                    self.confirm(record, confirmation)
            self.assertEqual(before, self.store.path.read_bytes())
            self.assertEqual(self.ops.mutations, [])
            self.assertEqual(self.store._held_locks, {})
            self.assertIsNone(self.store._transition_fd)
        opened = []
        original = self.store._directory
        @contextmanager
        def directory(*args, **kwargs):
            with original(*args, **kwargs) as fd:
                if fd is not None:
                    opened.append(fd)
                yield fd
        with patch.object(self.store, '_directory', side_effect=directory):
            self.confirm(record, confirmation)
        for fd in set(opened):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_d2_assessor_remains_advisory_and_truthful(self):
        from resources.lib.capture_recovery_assessor import assess_capture_recovery, RecoveryReason
        record = self.pending_terminal()
        before = self.store.path.read_bytes()
        mutations = list(self.ops.mutations)
        self.assertEqual(assess_capture_recovery(self.root, self.ops).reason,
                         RecoveryReason.TERMINAL_FINALIZATION_PENDING)
        self.ops.current_enabled = True
        self.assertEqual(assess_capture_recovery(self.root, self.ops).reason,
                         RecoveryReason.UNEXPECTED_ENABLEMENT)
        with self.assertRaises(CaptureLifecycleError):
            self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(mutations, self.ops.mutations)
        self.ops.current_enabled = False
        self.coordinator.recover(record.operation_id, self.request)
        self.assertEqual(assess_capture_recovery(self.root, self.ops).reason,
                         RecoveryReason.TERMINAL_NO_CAPTURE_HOLD)

    def test_owner_and_competition_drift_in_setter_never_terminalize(self):
        for defect in ('owner', 'active', 'enabled'):
            self.setUp()
            record, confirmation = self.candidate()
            setter = self.ops.set_enabled
            def drift(owner, value):
                setter(owner, value)
                if defect == 'owner':
                    self.ops.version = 'changed'
                elif defect == 'active':
                    self.ops.competing = True
                else:
                    self.ops.current_enabled = True
            with patch.object(self.ops, 'set_enabled', side_effect=drift):
                with self.assertRaises(CaptureLifecycleError):
                    self.confirm(record, confirmation)
            self.assertTrue(self.store.read().held)
            self.assertEqual(self.store.read().phase, CapturePhase.RESTORING)
            self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])

    def test_confirmation_cannot_cross_profile_with_copied_record(self):
        record, confirmation = self.candidate()
        other = D2RecoveryTests()
        other.setUp()
        self.addCleanup(other.doCleanups)
        with other.store.locked():
            other.store.save(None, record)
        other.ops.current_enabled = True
        before = other.store.path.read_bytes()
        with self.assertRaises(CaptureLifecycleError):
            other.coordinator.recover_d2(record.operation_id, self.request,
                confirmation=confirmation, confirmed=True)
        self.assertEqual(other.store.path.read_bytes(), before)
        self.assertEqual(other.ops.mutations, [])
        self.assertTrue(other.store.read().held)
        # A fresh explicit proposal made for B may authorize B independently.
        renewed = other.coordinator.prepare_d2_confirmation(record.operation_id, self.request)
        result = other.coordinator.recover_d2(record.operation_id, self.request,
            confirmation=renewed, confirmed=True)
        self.assertFalse(result.held)
        self.assertEqual(other.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        self.assertEqual(self.ops.mutations, [])
        self.assert_protected()

    def test_confirmation_cannot_cross_replaced_root_with_same_record(self):
        record, confirmation = self.candidate()
        retained = self.root.with_name('retained-root')
        self.root.rename(retained)
        self.root.mkdir()
        self.store = CaptureStore(self.root)
        self.coordinator = self.make_coordinator()
        with self.store.locked():
            self.store.save(None, record)
        before = self.store.path.read_bytes()
        with self.assertRaises(CaptureLifecycleError):
            self.confirm(record, confirmation)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.ops.mutations, [])
        self.assert_protected()

    def test_confirmation_aliases_share_the_same_canonical_profile_binding(self):
        CaptureLifecycleTests.use_symlinked_profile(self)
        self.coordinator = self.make_coordinator()
        record, confirmation = self.candidate()
        canonical = CaptureLifecycleCoordinator(store=CaptureStore(self.root),
            restart_store=self.restart, operations=self.ops, clock=lambda: self.now)
        result = canonical.recover_d2(record.operation_id, self.request,
            confirmation=confirmation, confirmed=True)
        self.assertFalse(result.held)
        self.assertEqual(self.ops.mutations, [(REDLIGHT_ADDON_ID, False)])
        self.assertNotIn(str(self.root), self.store.path.read_text())
        self.assertNotIn(str(self.root), repr(confirmation))

    def test_confirmation_invalid_or_mismatched_root_binding_fails_closed(self):
        record, confirmation = self.candidate()
        for value in ('', None, True, 'sha256:bad', SECRET):
            with self.assertRaises(CaptureLifecycleError) as error:
                replace(confirmation, root_binding=value)
            self.assertNotIn(SECRET, str(error.exception))
        wrong = replace(confirmation, root_binding='sha256:' + '0' * 64)
        before = self.store.path.read_bytes()
        with self.assertRaises(CaptureLifecycleError):
            self.confirm(record, wrong)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.ops.mutations, [])
        self.assert_protected()

    def test_disabled_during_consent_publication_skips_setter(self):
        record, confirmation = self.candidate()
        save = self.store.save
        def external_disable(expected, replacement):
            result = save(expected, replacement)
            self.ops.current_enabled = False
            return result
        with patch.object(self.store, 'save', side_effect=external_disable):
            result = self.confirm(record, confirmation)
        self.assertFalse(result.held)
        self.assertEqual(self.ops.mutations, [])


if __name__ == '__main__':
    unittest.main()
