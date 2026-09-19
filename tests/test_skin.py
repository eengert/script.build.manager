"""Focused BM-018A skin activation and Kodi response tests."""

import json
import sys
import unittest
from typing import Dict, List
from unittest.mock import MagicMock, patch

from resources.lib.skin import (
    KodiRuntimeSkinBackend,
    SkinActivator,
    SkinBackend,
    SkinError,
    SkinResult,
    SkinState,
    SkinStatus,
    SkinValidationError,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeSkinBackend(SkinBackend):
    def __init__(
        self,
        *,
        active_reads=None,
        skins=None,
        setting="skin.estuary",
        dialog_visibility=None,
    ):
        self.active_reads = list(active_reads or ["skin.estuary"])
        self.skins: Dict[str, SkinState] = dict(skins or {})
        self.setting = setting
        self.dialog_visibility = list(dialog_visibility or [False, True, False])
        self.calls: List[str] = []
        self.observed_dialog = False

    def get_active_skin(self):
        self.calls.append("get_active")
        if len(self.active_reads) > 1:
            return self.active_reads.pop(0)
        return self.active_reads[0]

    def get_skin_state(self, addon_id):
        self.calls.append(f"get_state:{addon_id}")
        return self.skins.get(addon_id, SkinState(False, False))

    def get_skin_setting(self):
        self.calls.append("get_setting")
        return self.setting

    def set_skin_setting(self, addon_id):
        self.calls.append(f"set_setting:{addon_id}")
        self.setting = addon_id

    def is_confirmation_visible(self):
        visible = self.dialog_visibility[0]
        if len(self.dialog_visibility) > 1:
            self.dialog_visibility.pop(0)
        self.calls.append(f"dialog:{visible}")
        if visible:
            self.observed_dialog = True
        return visible

    def confirm_skin_change(self):
        if not self.observed_dialog:
            raise AssertionError("confirmation clicked before dialog was observed")
        self.calls.append("confirm")


def _backend(**kwargs):
    kwargs.setdefault("skins", {"skin.foo": SkinState(True, True)})
    kwargs.setdefault("active_reads", ["skin.estuary", "skin.foo"])
    return FakeSkinBackend(**kwargs)


class TestSkinActivator(unittest.TestCase):
    def _activate(self, backend, **kwargs):
        clock = FakeClock()
        result = SkinActivator(
            backend, timeout=0.02, interval=0.01,
            sleep=clock.sleep, clock=clock, **kwargs,
        ).activate("skin.foo")
        return result

    def test_invalid_id_rejected_before_backend(self):
        backend = FakeSkinBackend()
        with self.assertRaises(SkinValidationError):
            SkinActivator(backend).activate("skin.foo;evil")
        self.assertEqual(backend.calls, [])

    def test_already_active_is_mutation_free(self):
        backend = FakeSkinBackend(active_reads=["skin.foo"])
        result = SkinActivator(backend).activate("skin.foo")
        self.assertEqual(result.status, SkinStatus.ALREADY_ACTIVE)
        self.assertEqual(backend.calls, ["get_active"])

    def test_missing_and_disabled_are_non_mutating_failures(self):
        for state in (SkinState(False, False), SkinState(True, False)):
            backend = FakeSkinBackend(skins={"skin.foo": state})
            result = self._activate(backend)
            self.assertEqual(result.status, SkinStatus.FAILED)
            self.assertNotIn("set_setting:skin.foo", backend.calls)

    def test_pre_existing_dialog_is_mutation_free_failure(self):
        backend = _backend(dialog_visibility=[True])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("pre-existing Yes/No dialog", result.message)
        self.assertNotIn("set_setting:skin.foo", backend.calls)
        self.assertNotIn("confirm", backend.calls)

    def test_confirmation_observed_before_yes_and_stable_state_verified(self):
        backend = _backend()
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.ACTIVATED)
        self.assertEqual(backend.calls, [
            "get_active", "get_state:skin.foo", "dialog:False",
            "set_setting:skin.foo", "dialog:True", "confirm", "dialog:False",
            "get_setting", "get_active",
        ])

    def test_confirmation_never_appears_is_failure(self):
        backend = _backend(dialog_visibility=[False])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertNotIn("confirm", backend.calls)

    def test_confirmation_never_closes_is_failure(self):
        backend = _backend(dialog_visibility=[False, True, True])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("confirm", backend.calls)
        self.assertNotIn("get_setting", backend.calls)

    def test_temporary_load_then_revert_is_failure(self):
        backend = _backend(active_reads=["skin.estuary", "skin.estuary"])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("Loaded skin", result.message)

    def test_persisted_setting_mismatch_is_failure(self):
        class NonPersisting(FakeSkinBackend):
            def set_skin_setting(self, addon_id):
                self.calls.append(f"set_setting:{addon_id}")

        backend = NonPersisting(
            skins={"skin.foo": SkinState(True, True)}, setting="skin.other"
        )
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("Persisted skin setting", result.message)

    def test_loaded_skin_mismatch_is_failure(self):
        backend = _backend(active_reads=["skin.estuary", "skin.other"])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("Loaded skin", result.message)

    def test_backend_exception_is_failure(self):
        class Broken(FakeSkinBackend):
            def set_skin_setting(self, addon_id):
                raise SkinError("settings unavailable")

        result = self._activate(Broken(skins={"skin.foo": SkinState(True, True)}))
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("settings unavailable", result.message)


class TestKodiRuntimeSkinBackend(unittest.TestCase):
    def _backend(self, responses):
        xbmc = MagicMock()
        xbmc.executeJSONRPC.side_effect = [json.dumps(value) for value in responses]
        return KodiRuntimeSkinBackend(), xbmc

    def test_setting_mutation_request_is_valid(self):
        backend, xbmc = self._backend([{"jsonrpc": "2.0", "result": "OK", "id": 1}])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            backend.set_skin_setting("skin.foo")
        request = json.loads(xbmc.executeJSONRPC.call_args.args[0])
        self.assertEqual(request["method"], "Settings.SetSettingValue")
        self.assertEqual(request["params"], {
            "setting": "lookandfeel.skin", "value": "skin.foo",
        })

    def test_setting_mutation_jsonrpc_error_is_failure(self):
        backend, xbmc = self._backend([{
            "jsonrpc": "2.0", "error": {"code": -1, "message": "bad"}, "id": 1,
        }])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            with self.assertRaises(SkinError):
                backend.set_skin_setting("skin.foo")

    def test_setting_mutation_malformed_response_is_failure(self):
        backend, xbmc = self._backend([{"jsonrpc": "2.0", "id": 1}])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            with self.assertRaises(SkinError):
                backend.set_skin_setting("skin.foo")

    def test_setting_read_is_strict(self):
        backend, xbmc = self._backend([{
            "jsonrpc": "2.0", "result": {"value": "skin.foo"}, "id": 1,
        }])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            self.assertEqual(backend.get_skin_setting(), "skin.foo")

    def test_addon_not_found_is_distinguished(self):
        backend, xbmc = self._backend([{
            "jsonrpc": "2.0", "error": {"code": -32602}, "id": 1,
        }])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            self.assertEqual(backend.get_skin_state("skin.foo"), SkinState(False, False))

    def test_addon_protocol_error_is_not_not_installed(self):
        backend, xbmc = self._backend([{
            "jsonrpc": "2.0", "error": {"code": -1, "message": "offline"}, "id": 1,
        }])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            with self.assertRaises(SkinError):
                backend.get_skin_state("skin.foo")

    def test_addon_malformed_response_is_failure(self):
        backend, xbmc = self._backend([{"jsonrpc": "2.0", "result": {}, "id": 1}])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            with self.assertRaises(SkinError):
                backend.get_skin_state("skin.foo")

    def test_dialog_visibility_uses_proven_condition(self):
        backend, xbmc = self._backend([])
        xbmc.getCondVisibility.return_value = 1
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            self.assertTrue(backend.is_confirmation_visible())
        xbmc.getCondVisibility.assert_called_once_with("Window.IsActive(yesnodialog)")


if __name__ == "__main__":
    unittest.main()
