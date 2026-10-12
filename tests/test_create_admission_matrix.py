"""Synthetic Create holds across supported admission/activation entry points."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from resources.lib.activation import reject_held_activation, ActivationHoldError
from resources.lib.addons import KodiRuntimeAddonBackend, AddonInstallError
from resources.lib.capture_lifecycle import CapturePhase, CaptureTransaction, CaptureLifecycleError, capture_activation_holds, require_no_capture
from resources.lib.frozen_install import FrozenInstallStore, FrozenInstallCoordinator, KodiRuntimeFrozenArtifactBackend, FrozenInstallError
from resources.lib.restart_coordinator import RestartCoordinator
from resources.lib.transaction import TransactionStore, TransactionStateConflict
from resources.lib.redlight_resource import REDLIGHT_ADDON_ID, REDLIGHT_VERSION
from tests.test_transaction import _transaction


def held_record():
    return CaptureTransaction('22222222-2222-4222-8222-222222222222', CapturePhase.AWAITING_RESTART,
        'sha256:' + 'a'*64, REDLIGHT_ADDON_ID, REDLIGHT_VERSION, False,
        '11111111-1111-4111-8111-111111111111', 1000, 2000)


class AdmissionMatrixTests(unittest.TestCase):
    def cases(self):
        held = held_record()
        return {
            'held': held.to_dict(),
            'restoring': replace(held, phase=CapturePhase.RESTORING, outcome='cancelled').to_dict(),
            'terminal_pending': replace(held, phase=CapturePhase.CANCELLED, outcome='cancelled', commit_pending=True).to_dict(),
            'malformed': {'private': 'SECRET'},
            'competing': held.to_dict(),
            'unknown_owner': {**held.to_dict(), 'owner_id': 'plugin.unknown'},
            'wrong_version': {**held.to_dict(), 'owner_version': '2.6.9'},
        }

    def test_protected_matrix_refuses_before_any_effect(self):
        for name, raw in self.cases().items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                profile = Path(temporary)
                root = profile / 'addon_data/script.build.manager'
                root.mkdir(parents=True)
                path = root / 'create_capture_transaction.json'
                path.write_text(json.dumps(raw))
                if name == 'competing':
                    (root / 'restart_transaction.json').write_text(json.dumps(_transaction().to_dict()))
                before = path.read_bytes()
                restart = TransactionStore(str(profile))
                store = FrozenInstallStore(root, create=False)
                manager = Mock()
                installer = Mock()
                coordinator = FrozenInstallCoordinator(artifact_store=Mock(), installer=installer, store=store, policy_backend=Mock())
                with patch('resources.lib.frozen_install.default_frozen_install_root', return_value=root), \
                        patch('resources.lib.build_library.authoritative_build_library') as next_stage:
                    with self.assertRaises(CaptureLifecycleError):
                        require_no_capture(root)
                    with self.assertRaises((ActivationHoldError, CaptureLifecycleError)):
                        reject_held_activation(REDLIGHT_ADDON_ID)
                    self.assertEqual(coordinator.install(Mock(), manifest_path='/unused', device_profile_id='desk').code, 'CAPTURE_LIFECYCLE_BLOCKED')
                    next_stage.assert_not_called()
                    self.assertEqual(RestartCoordinator(manager, store=restart).reconcile(_transaction().request).outcome.value, 'failed')
                    with self.assertRaises(TransactionStateConflict):
                        restart.create(_transaction())
                    with self.assertRaises(CaptureLifecycleError):
                        store.create(Mock())
                    native = KodiRuntimeAddonBackend()
                    with patch.object(native, '_xbmc') as xbmc, patch.object(native, '_resolve_package_url') as resolve:
                        with self.assertRaises(AddonInstallError):
                            native.invoke_install(REDLIGHT_ADDON_ID)
                        with self.assertRaises(AddonInstallError):
                            native.set_addon_enabled(REDLIGHT_ADDON_ID, True)
                        xbmc.assert_not_called()
                        resolve.assert_not_called()
                    frozen = KodiRuntimeFrozenArtifactBackend()
                    with patch.object(frozen, 'assert_mutable_target'), patch.object(frozen, '_rpc') as rpc:
                        with self.assertRaises(FrozenInstallError):
                            frozen.set_addon_enabled(REDLIGHT_ADDON_ID, True)
                        rpc.assert_not_called()
                manager.reconcile.assert_not_called()
                self.assertEqual(installer.mock_calls, [])
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse((root / 'frozen_install_transaction.json').exists())

    def test_released_terminal_does_not_invent_a_hold_or_block_restart_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            root = profile / 'addon_data/script.build.manager'
            root.mkdir(parents=True)
            terminal = replace(held_record(), phase=CapturePhase.CANCELLED, outcome='cancelled')
            path = root / 'create_capture_transaction.json'
            path.write_text(json.dumps(terminal.to_dict()))
            before = path.read_bytes()
            self.assertEqual(capture_activation_holds(root), frozenset())
            require_no_capture(root)
            restart = TransactionStore(str(profile))
            restart.create(_transaction())
            self.assertEqual(restart.read_snapshot(), _transaction())
            self.assertEqual(path.read_bytes(), before)

    def test_unknown_hold_provider_never_coerces_to_safe_admission(self):
        for value in (None, False, '', 0, {}, ['plugin.video.redlight']):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ActivationHoldError):
                    reject_held_activation(REDLIGHT_ADDON_ID, provider=lambda: value)
