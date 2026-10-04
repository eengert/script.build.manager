"""Focused BM-018A skin activation and Kodi response tests."""

import json
import sys
import unittest
from typing import Dict, List
from unittest.mock import MagicMock, patch

from resources.lib.skin import (
    KodiRuntimeSkinBackend,
    KodiRuntimeSkinSettingsBackend,
    _SkinRpcError,
    SkinActivator,
    SkinBackend,
    SkinError,
    SkinFailureCode,
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
        self.dialog_visibility = list(dialog_visibility or [False, True, True, False])
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
        self.assertIsNone(result.failure_code)

    def test_missing_and_disabled_are_non_mutating_failures(self):
        for state in (SkinState(False, False), SkinState(True, False)):
            backend = FakeSkinBackend(skins={"skin.foo": state})
            result = self._activate(backend)
            self.assertEqual(result.status, SkinStatus.FAILED)
            self.assertEqual(
                result.failure_code,
                SkinFailureCode.TARGET_SKIN_NOT_AVAILABLE
                if not state.installed else SkinFailureCode.TARGET_SKIN_DISABLED,
            )
            self.assertNotIn("set_setting:skin.foo", backend.calls)

    def test_pre_existing_dialog_is_mutation_free_failure(self):
        backend = _backend(dialog_visibility=[True])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertEqual(
            result.failure_code, SkinFailureCode.PREEXISTING_CONFIRMATION_DIALOG
        )
        self.assertIn("pre-existing Yes/No dialog", result.message)
        self.assertNotIn("set_setting:skin.foo", backend.calls)
        self.assertNotIn("confirm", backend.calls)

    def test_confirmation_observed_before_yes_and_stable_state_verified(self):
        backend = _backend()
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.ACTIVATED)
        self.assertIsNone(result.failure_code)
        self.assertEqual(backend.calls, [
            "get_active", "get_state:skin.foo", "dialog:False",
            "set_setting:skin.foo", "get_active", "dialog:True",
            "confirm", "dialog:True", "dialog:False", "dialog:False",
            "get_setting", "get_active", "get_setting", "get_active",
            "get_setting", "get_active",
        ])

    def test_confirmation_never_appears_is_failure(self):
        backend = _backend(dialog_visibility=[False])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertEqual(result.failure_code, SkinFailureCode.CONFIRMATION_NOT_OBSERVED)
        self.assertNotIn("confirm", backend.calls)

    def test_confirmation_never_closes_is_failure(self):
        backend = _backend(dialog_visibility=[False, True, True])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertEqual(result.failure_code, SkinFailureCode.CONFIRMATION_NOT_CLOSED)
        self.assertIn("confirm", backend.calls)
        self.assertNotIn("get_setting", backend.calls)

    def test_temporary_load_then_revert_is_failure(self):
        backend = _backend(active_reads=["skin.estuary", "skin.foo", "skin.estuary"])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("Loaded skin", result.message)
        self.assertEqual(result.failure_code, SkinFailureCode.TARGET_SKIN_NOT_ACTIVE)

    def test_persisted_setting_mismatch_is_failure(self):
        class NonPersisting(FakeSkinBackend):
            def set_skin_setting(self, addon_id):
                self.calls.append(f"set_setting:{addon_id}")

        backend = NonPersisting(
            active_reads=["skin.estuary", "skin.foo"],
            skins={"skin.foo": SkinState(True, True)}, setting="skin.other"
        )
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("Persisted skin setting", result.message)
        self.assertEqual(result.failure_code, SkinFailureCode.TARGET_SKIN_NOT_PERSISTED)

    def test_loaded_skin_mismatch_is_failure(self):
        backend = _backend(active_reads=["skin.estuary", "skin.foo", "skin.other"])
        result = self._activate(backend)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("Loaded skin", result.message)
        self.assertEqual(result.failure_code, SkinFailureCode.TARGET_SKIN_NOT_ACTIVE)

    def test_backend_exception_is_failure(self):
        class Broken(FakeSkinBackend):
            def set_skin_setting(self, addon_id):
                raise SkinError("settings unavailable")

        result = self._activate(Broken(skins={"skin.foo": SkinState(True, True)}))
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("settings unavailable", result.message)
        self.assertEqual(result.failure_code, SkinFailureCode.SET_SKIN_COMMAND_FAILED)

    def test_initial_and_target_state_read_failures_have_distinct_codes(self):
        class InitialReadFails(FakeSkinBackend):
            def get_active_skin(self):
                raise RuntimeError("private path and secret")

        class TargetReadFails(FakeSkinBackend):
            def get_skin_state(self, _addon_id):
                raise RuntimeError("private path and secret")

        for backend, expected in (
            (InitialReadFails(), SkinFailureCode.INITIAL_SKIN_STATE_READ_FAILED),
            (
                TargetReadFails(skins={"skin.foo": SkinState(True, True)}),
                SkinFailureCode.TARGET_SKIN_STATE_READ_FAILED,
            ),
        ):
            with self.subTest(expected=expected):
                result = self._activate(backend)
                self.assertEqual(result.failure_code, expected)
                self.assertNotIn("private", result.failure_code.value.lower())

    def test_confirmation_state_read_and_preparation_failures_have_distinct_codes(self):
        class DialogReadFails(FakeSkinBackend):
            def is_confirmation_visible(self):
                raise RuntimeError("private dialog path")

        class PreparationFails(FakeSkinBackend):
            def prepare_skin_change(self):
                raise RuntimeError("private preparation path")

        for backend, expected in (
            (
                DialogReadFails(skins={"skin.foo": SkinState(True, True)}),
                SkinFailureCode.CONFIRMATION_STATE_READ_FAILED,
            ),
            (
                PreparationFails(skins={"skin.foo": SkinState(True, True)}),
                SkinFailureCode.SKIN_CHANGE_PREPARATION_FAILED,
            ),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(self._activate(backend).failure_code, expected)

    def test_confirmation_poll_read_failures_are_distinct_from_timeouts(self):
        class PollDialogReadFails(FakeSkinBackend):
            def __init__(self):
                super().__init__(
                    active_reads=["skin.estuary", "skin.foo"],
                    skins={"skin.foo": SkinState(True, True)},
                )
                self.dialog_reads = 0

            def is_confirmation_visible(self):
                self.dialog_reads += 1
                if self.dialog_reads == 1:
                    return False
                raise RuntimeError("untrusted dialog diagnostic")

        result = self._activate(PollDialogReadFails())
        self.assertEqual(
            result.failure_code, SkinFailureCode.CONFIRMATION_STATE_READ_FAILED
        )

    def test_confirmation_close_poll_read_failure_is_safely_reported(self):
        class ClosePollReadFails(FakeSkinBackend):
            def __init__(self):
                super().__init__(
                    active_reads=["skin.estuary", "skin.foo"],
                    skins={"skin.foo": SkinState(True, True)},
                )
                self.dialog_reads = 0

            def is_confirmation_visible(self):
                self.dialog_reads += 1
                if self.dialog_reads == 1:
                    return False
                if self.dialog_reads == 2:
                    self.observed_dialog = True
                    return True
                raise RuntimeError("untrusted dialog diagnostic")

        result = self._activate(ClosePollReadFails())
        self.assertEqual(
            result.failure_code, SkinFailureCode.CONFIRMATION_STATE_READ_FAILED
        )

    def test_stability_poll_read_failure_is_safely_reported(self):
        class StabilityReadFails(FakeSkinBackend):
            def __init__(self):
                super().__init__(
                    active_reads=["skin.estuary", "skin.foo"],
                    skins={"skin.foo": SkinState(True, True)},
                )
                self.setting_reads = 0

            def get_skin_setting(self):
                self.setting_reads += 1
                if self.setting_reads == 1:
                    return self.setting
                raise RuntimeError("untrusted persisted setting")

        result = self._activate(StabilityReadFails())
        self.assertEqual(
            result.failure_code, SkinFailureCode.PERSISTED_SKIN_READ_FAILED
        )

    def test_jsonrpc_failure_uses_only_static_code(self):
        class RpcFails(FakeSkinBackend):
            def set_skin_setting(self, _addon_id):
                raise _SkinRpcError(
                    "/private/profile/secret-token", code=-1,
                    failure_code=SkinFailureCode.JSONRPC_FAILURE,
                )

        result = self._activate(RpcFails(
            active_reads=["skin.estuary", "skin.foo"],
            skins={"skin.foo": SkinState(True, True)},
        ))
        self.assertEqual(result.failure_code, SkinFailureCode.JSONRPC_FAILURE)
        self.assertRegex(result.failure_code.value, r"^[A-Z0-9_]+$")
        self.assertNotIn("/private", result.failure_code.value)
        self.assertNotIn("secret-token", result.failure_code.value)

    def test_confirmation_action_failure_has_static_code(self):
        class ConfirmationFails(FakeSkinBackend):
            def confirm_skin_change(self):
                raise RuntimeError("private confirmation path")

        result = self._activate(ConfirmationFails(
            active_reads=["skin.estuary", "skin.foo"],
            skins={"skin.foo": SkinState(True, True)},
        ))
        self.assertEqual(result.failure_code, SkinFailureCode.CONFIRMATION_ACTION_FAILED)

    def test_persisted_and_active_read_failures_have_distinct_codes(self):
        class PersistedReadFails(FakeSkinBackend):
            def get_skin_setting(self):
                raise RuntimeError("private settings path")

        class ActiveReadFails(FakeSkinBackend):
            def __init__(self):
                super().__init__(
                    active_reads=["skin.estuary", "skin.foo"],
                    skins={"skin.foo": SkinState(True, True)},
                )
                self.active_count = 0

            def get_active_skin(self):
                self.active_count += 1
                if self.active_count == 3:
                    raise RuntimeError("private skin path")
                return super().get_active_skin()

        self.assertEqual(
            self._activate(PersistedReadFails(
                active_reads=["skin.estuary", "skin.foo"],
                skins={"skin.foo": SkinState(True, True)},
            )).failure_code,
            SkinFailureCode.PERSISTED_SKIN_READ_FAILED,
        )
        self.assertEqual(
            self._activate(ActiveReadFails()).failure_code,
            SkinFailureCode.ACTIVE_SKIN_READ_FAILED,
        )

    def test_unstable_skin_after_confirmation_has_distinct_code(self):
        backend = _backend(
            active_reads=["skin.estuary", "skin.foo", "skin.foo", "skin.estuary"]
        )
        result = self._activate(backend)
        self.assertEqual(result.failure_code, SkinFailureCode.SKIN_DID_NOT_REMAIN_STABLE)

    def test_failure_codes_are_finite_and_results_retain_compatibility(self):
        values = {item.value for item in SkinFailureCode}
        self.assertEqual(len(values), len(SkinFailureCode))
        self.assertTrue(all(value.isascii() and value.isupper() for value in values))
        # Existing positional constructors remain valid; successful callers
        # gain the new optional field without changing their argument order.
        result = SkinResult("skin.foo", SkinStatus.ACTIVATED, "skin.foo", "ok")
        self.assertIsNone(result.failure_code)

    def test_unknown_failure_fallback_does_not_retain_untrusted_code_text(self):
        result = SkinActivator._failed(
            "skin.foo", "skin.estuary", "/private/secret diagnostic",
            "/private/secret-code",
        )
        self.assertEqual(result.failure_code, SkinFailureCode.UNKNOWN_SAFE_FAILURE)
        self.assertNotIn("private", result.failure_code.value.lower())


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
            with self.assertRaises(SkinError) as caught:
                backend.set_skin_setting("skin.foo")
        self.assertEqual(
            caught.exception.failure_code, SkinFailureCode.JSONRPC_FAILURE
        )

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


class TestKodiRuntimeSkinSettingsBackend(unittest.TestCase):
    def _backend(self, responses, active="skin.foo"):
        xbmc = MagicMock()
        xbmc.getSkinDir.return_value = active
        xbmc.executeJSONRPC.side_effect = [json.dumps(value) for value in responses]
        return KodiRuntimeSkinSettingsBackend(), xbmc

    @staticmethod
    def _vfs(xml):
        xbmcvfs = MagicMock()
        handle = MagicMock()
        handle.read.return_value = xml
        xbmcvfs.File.return_value = handle
        return xbmcvfs

    @staticmethod
    def _missing():
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32602, "message": "Invalid params."},
            "id": 1,
        }

    def test_bool_read_and_write_use_skin_jsonrpc_namespace(self):
        backend, xbmc = self._backend([
            {"jsonrpc": "2.0", "result": {"value": False}, "id": 1},
            {"jsonrpc": "2.0", "result": True, "id": 1},
            {"jsonrpc": "2.0", "result": {"value": True}, "id": 1},
        ])
        xbmcvfs = self._vfs(
            "<settings><setting id=\"feature\" type=\"bool\">true</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            self.assertFalse(backend.get_setting("skin.foo", "feature", "bool"))
            backend.set_setting("skin.foo", "feature", "bool", True)
        requests = [json.loads(call.args[0]) for call in xbmc.executeJSONRPC.call_args_list]
        self.assertEqual(requests[0]["method"], "Settings.GetSkinSettingValue")
        self.assertEqual(requests[0]["params"], {"setting": "feature"})
        self.assertEqual(requests[1]["method"], "Settings.SetSkinSettingValue")
        self.assertEqual(requests[1]["params"], {"setting": "feature", "value": True})
        xbmc.executebuiltin.assert_called_once_with("Skin.SetBool(feature)", True)

    def test_string_write_accepts_kodis_written_value_response(self):
        backend, xbmc = self._backend([
            {"jsonrpc": "2.0", "result": "Standard", "id": 1},
            {"jsonrpc": "2.0", "result": {"value": "Standard"}, "id": 1},
        ])
        xbmcvfs = self._vfs(
            "<settings><setting id=\"mode\" type=\"string\">Standard</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            backend.set_setting("skin.foo", "mode", "string", "Standard")
        xbmc.executebuiltin.assert_called_once_with("Skin.SetString(mode,Standard)", True)

    def test_af3_setting_falls_back_to_kodi_lowercase_id(self):
        backend, xbmc = self._backend([
            {"jsonrpc": "2.0", "error": {"code": -32602}, "id": 1},
            {"jsonrpc": "2.0", "result": {"value": False}, "id": 1},
        ])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            self.assertFalse(
                backend.get_setting("skin.foo", "HomeSwitcher.EnableIcons", "bool")
            )
        requests = [json.loads(call.args[0]) for call in xbmc.executeJSONRPC.call_args_list]
        self.assertEqual(requests[0]["params"], {"setting": "HomeSwitcher.EnableIcons"})
        self.assertEqual(requests[1]["params"], {"setting": "homeswitcher.enableicons"})

    def test_double_invalid_params_falls_back_to_effective_bool(self):
        backend, xbmc = self._backend([self._missing(), self._missing()])
        xbmc.getCondVisibility.return_value = True
        xbmcvfs = self._vfs(
            "<settings><setting id=\"view.usedetailedlistlabels\" "
            "type=\"bool\">true</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            self.assertTrue(
                backend.get_setting(
                    "skin.foo", "View.UseDetailedListLabels", "bool"
                )
            )
        xbmc.getCondVisibility.assert_called_once_with(
            "Skin.HasSetting(View.UseDetailedListLabels)"
        )

    def test_double_invalid_params_falls_back_to_effective_string(self):
        backend, xbmc = self._backend([self._missing(), self._missing()])
        xbmc.getInfoLabel.return_value = "Previous"
        xbmcvfs = self._vfs(
            "<settings><setting id=\"navigation.onback\" "
            "type=\"string\">Previous</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            self.assertEqual(
                backend.get_setting("skin.foo", "Navigation.OnBack", "string"),
                "Previous",
            )
        xbmc.getInfoLabel.assert_called_once_with(
            "Skin.String(Navigation.OnBack)"
        )

    def test_fallback_rejects_unknown_setting(self):
        backend, xbmc = self._backend([self._missing(), self._missing()])
        xbmcvfs = self._vfs(
            "<settings><setting id=\"other.setting\" "
            "type=\"bool\">false</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            with self.assertRaises(SkinError):
                backend.get_setting("skin.foo", "Unknown.Setting", "bool")
        xbmc.getCondVisibility.assert_not_called()

    def test_fallback_rejects_xml_type_mismatch(self):
        backend, xbmc = self._backend([self._missing(), self._missing()])
        xbmcvfs = self._vfs(
            "<settings><setting id=\"view.usedetailedlistlabels\" "
            "type=\"string\">true</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            with self.assertRaises(SkinError):
                backend.get_setting(
                    "skin.foo", "View.UseDetailedListLabels", "bool"
                )
        xbmc.getCondVisibility.assert_not_called()

    def test_fallback_rejects_malformed_xml(self):
        backend, xbmc = self._backend([self._missing(), self._missing()])
        xbmcvfs = self._vfs("<settings>")
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            with self.assertRaises(SkinError):
                backend.get_setting("skin.foo", "View.UseDetailedListLabels", "bool")

    def test_unrelated_jsonrpc_error_never_invokes_fallback(self):
        backend, xbmc = self._backend([{
            "jsonrpc": "2.0",
            "error": {"code": -1, "message": "offline"},
            "id": 1,
        }])
        xbmcvfs = self._vfs(
            "<settings><setting id=\"view.usedetailedlistlabels\" "
            "type=\"bool\">true</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            with self.assertRaises(SkinError):
                backend.get_setting(
                    "skin.foo", "View.UseDetailedListLabels", "bool"
                )
        xbmcvfs.File.assert_not_called()
        xbmc.getCondVisibility.assert_not_called()

    def test_fallback_write_bool_uses_builtin_and_strict_readback(self):
        backend, xbmc = self._backend([
            self._missing(), self._missing(),
            self._missing(), self._missing(),
        ])
        xbmc.getCondVisibility.return_value = True
        xbmcvfs = self._vfs(
            "<settings><setting id=\"view.usedetailedlistlabels\" "
            "type=\"bool\">true</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            backend.set_setting(
                "skin.foo", "View.UseDetailedListLabels", "bool", True
            )
        xbmc.executebuiltin.assert_called_once_with(
            "Skin.SetBool(View.UseDetailedListLabels)", True
        )

    def test_fallback_write_string_empty_to_nonempty_is_safe(self):
        backend, xbmc = self._backend([
            self._missing(), self._missing(),
            self._missing(), self._missing(),
        ])
        xbmc.getInfoLabel.return_value = "Previous"
        xbmcvfs = self._vfs(
            "<settings><setting id=\"navigation.onback\" "
            "type=\"string\">Previous</setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            backend.set_setting(
                "skin.foo", "Navigation.OnBack", "string", "Previous"
            )
        xbmc.executebuiltin.assert_called_once_with(
            "Skin.SetString(Navigation.OnBack,Previous)", True
        )

    def test_fallback_rejects_unsafe_builtin_value(self):
        backend, xbmc = self._backend([self._missing(), self._missing()])
        xbmcvfs = self._vfs(
            "<settings><setting id=\"navigation.onback\" "
            "type=\"string\"></setting></settings>"
        )
        with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcvfs": xbmcvfs}):
            with self.assertRaises(SkinError):
                backend.set_setting(
                    "skin.foo", "Navigation.OnBack", "string", "Previous,evil"
                )
        xbmc.executebuiltin.assert_not_called()

    def test_string_read_is_typed_and_wrong_active_skin_fails_before_rpc(self):
        backend, xbmc = self._backend([
            {"jsonrpc": "2.0", "result": {"value": "Standard"}, "id": 1},
        ])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            self.assertEqual(
                backend.get_setting("skin.foo", "mode", "string"), "Standard"
            )
        wrong, wrong_xbmc = self._backend([], active="skin.estuary")
        with patch.dict(sys.modules, {"xbmc": wrong_xbmc}):
            with self.assertRaises(SkinError):
                wrong.set_setting("skin.foo", "mode", "string", "Standard")
        wrong_xbmc.executeJSONRPC.assert_not_called()

    def test_skin_target_rejects_numeric_type(self):
        backend, xbmc = self._backend([])
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            with self.assertRaises(SkinError):
                backend.get_setting("skin.foo", "count", "int")


if __name__ == "__main__":
    unittest.main()
