"""
Unit tests for resources/lib/addons.py (BM-011).

All tests run without Kodi — no xbmc imports required.
Tests cover:
  VALIDATION     -- addon_id grammar enforcement (injection prevention)
  IS_INSTALLED   -- detection via backend.get_addon_details
  IDEMPOTENCY    -- ALREADY_INSTALLED when already present, no mutation
  HAPPY_PATH     -- INSTALLED when Kodi successfully installs the add-on
  INVALID_ID     -- FAILED before any backend call on bad addon_id
  INVOKE_FAIL    -- FAILED when invoke_install raises
  POLL_TIMEOUT   -- FAILED when poll returns None (install didn't complete)
  POLL_ERROR     -- FAILED when poll_addon_installed raises
  RESULT_FIELDS  -- all fields populated correctly on every path
  DESIRED_STATE  -- desired_state preserved verbatim in all results
  RUNTIME_BACKEND -- KodiRuntimeAddonBackend unit tests (mocked xbmc)
"""

import json
import unittest
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

from resources.lib.addons import (
    AddonBackend,
    AddonError,
    AddonInstallError,
    AddonInstallResult,
    AddonManager,
    AddonStatus,
    AddonValidationError,
    InstalledAddonInfo,
    KodiRuntimeAddonBackend,
    _INSTALL_INTERVAL,
    _INSTALL_TIMEOUT,
    _validate_addon_id,
)


# ---------------------------------------------------------------------------
# Fake backend for unit tests
# ---------------------------------------------------------------------------

class FakeAddonBackend(AddonBackend):
    """Configurable fake backend for AddonManager unit tests."""

    def __init__(
        self,
        installed: Optional[Dict[str, InstalledAddonInfo]] = None,
        invoke_error: Optional[Exception] = None,
        poll_result: Optional[InstalledAddonInfo] = None,
        poll_error: Optional[Exception] = None,
    ):
        self._installed: Dict[str, InstalledAddonInfo] = dict(installed or {})
        self._invoke_error = invoke_error
        self._poll_result = poll_result
        self._poll_error = poll_error
        self.invoke_calls: List[str] = []
        self.poll_calls: List[str] = []
        self.details_calls: List[str] = []

    def get_addon_details(self, addon_id: str) -> Optional[InstalledAddonInfo]:
        self.details_calls.append(addon_id)
        return self._installed.get(addon_id)

    def invoke_install(self, addon_id: str) -> None:
        self.invoke_calls.append(addon_id)
        if self._invoke_error is not None:
            raise self._invoke_error

    def poll_addon_installed(
        self,
        addon_id: str,
        *,
        timeout: float = _INSTALL_TIMEOUT,
        interval: float = _INSTALL_INTERVAL,
    ) -> Optional[InstalledAddonInfo]:
        self.poll_calls.append(addon_id)
        if self._poll_error is not None:
            raise self._poll_error
        return self._poll_result


def _make_info(
    addon_id: str = "plugin.video.test",
    enabled: bool = True,
    version: str = "1.0.0",
) -> InstalledAddonInfo:
    return InstalledAddonInfo(addon_id=addon_id, enabled=enabled, version=version)


# ---------------------------------------------------------------------------
# TestAddonIdValidation — addon_id grammar enforcement
# ---------------------------------------------------------------------------

class TestAddonIdValidation(unittest.TestCase):
    """_validate_addon_id: valid IDs accepted; invalid IDs raise AddonValidationError."""

    # Valid IDs
    def test_simple_dot_separated(self):
        _validate_addon_id("plugin.video.test")

    def test_script_module(self):
        _validate_addon_id("script.module.example")

    def test_repository(self):
        _validate_addon_id("repository.example-repo")

    def test_single_char(self):
        _validate_addon_id("a")

    def test_alphanumeric_only(self):
        _validate_addon_id("abc123")

    def test_uppercase_allowed(self):
        _validate_addon_id("Plugin.Video.Test")

    def test_digits_allowed(self):
        _validate_addon_id("plugin123.video456")

    def test_hyphens_allowed(self):
        _validate_addon_id("plugin-name")

    def test_underscores_allowed(self):
        _validate_addon_id("plugin_name_v2")

    def test_mixed_separators(self):
        _validate_addon_id("script.build-manager.test_v2")

    def test_max_length_100(self):
        _validate_addon_id("a" * 100)

    # Invalid IDs
    def test_empty_string_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("")

    def test_space_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon id")

    def test_open_paren_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon(id)")

    def test_close_paren_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon)id")

    def test_comma_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon,id")

    def test_semicolon_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon;id")

    def test_double_quote_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id('"addon"')

    def test_single_quote_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon'id")

    def test_newline_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon\nid")

    def test_tab_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon\tid")

    def test_null_byte_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon\x00id")

    def test_control_char_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("addon\x1fid")

    def test_starts_with_hyphen_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("-addon")

    def test_starts_with_dot_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id(".addon")

    def test_starts_with_underscore_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("_addon")

    def test_101_chars_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("a" * 101)

    def test_non_string_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id(None)  # type: ignore[arg-type]

    def test_injection_chars_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("a;xbmc.executebuiltin(evil)")

    def test_slash_raises(self):
        with self.assertRaises(AddonValidationError):
            _validate_addon_id("plugin/video/test")


# ---------------------------------------------------------------------------
# TestIsInstalled — detection via backend
# ---------------------------------------------------------------------------

class TestIsInstalled(unittest.TestCase):
    """AddonManager.is_installed returns correct booleans."""

    def test_installed_returns_true(self):
        info = _make_info("plugin.video.test")
        be = FakeAddonBackend(installed={"plugin.video.test": info})
        self.assertTrue(AddonManager(be).is_installed("plugin.video.test"))

    def test_not_installed_returns_false(self):
        be = FakeAddonBackend()
        self.assertFalse(AddonManager(be).is_installed("plugin.video.test"))

    def test_disabled_addon_returns_true(self):
        info = _make_info("plugin.video.test", enabled=False)
        be = FakeAddonBackend(installed={"plugin.video.test": info})
        self.assertTrue(AddonManager(be).is_installed("plugin.video.test"))

    def test_invalid_id_raises(self):
        be = FakeAddonBackend()
        with self.assertRaises(AddonValidationError):
            AddonManager(be).is_installed("bad(id)")

    def test_empty_id_raises(self):
        be = FakeAddonBackend()
        with self.assertRaises(AddonValidationError):
            AddonManager(be).is_installed("")


# ---------------------------------------------------------------------------
# TestInstallAlreadyInstalled — idempotency
# ---------------------------------------------------------------------------

class TestInstallAlreadyInstalled(unittest.TestCase):
    """install() returns ALREADY_INSTALLED with no mutation when detected."""

    def _run(self, addon_id="plugin.video.test", enabled=True, version="1.0.0", desired="enabled"):
        info = _make_info(addon_id, enabled=enabled, version=version)
        be = FakeAddonBackend(installed={addon_id: info})
        result = AddonManager(be).install(addon_id, desired_state=desired)
        return result, be

    def test_status_already_installed(self):
        result, _ = self._run()
        self.assertEqual(result.status, AddonStatus.ALREADY_INSTALLED)

    def test_no_invoke_call(self):
        _, be = self._run()
        self.assertEqual(be.invoke_calls, [])

    def test_no_poll_call(self):
        _, be = self._run()
        self.assertEqual(be.poll_calls, [])

    def test_enabled_from_existing(self):
        result, _ = self._run(enabled=True)
        self.assertTrue(result.enabled)

    def test_disabled_addon_enabled_false(self):
        result, _ = self._run(enabled=False)
        self.assertFalse(result.enabled)

    def test_version_from_existing(self):
        result, _ = self._run(version="2.5.1")
        self.assertEqual(result.version, "2.5.1")

    def test_desired_state_preserved(self):
        result, _ = self._run(desired="disabled")
        self.assertEqual(result.desired_state, "disabled")

    def test_addon_id_in_result(self):
        result, _ = self._run(addon_id="script.module.foo")
        self.assertEqual(result.addon_id, "script.module.foo")

    def test_message_mentions_already(self):
        result, _ = self._run()
        self.assertIn("already", result.message.lower())


# ---------------------------------------------------------------------------
# TestInstallHappyPath — INSTALLED on success
# ---------------------------------------------------------------------------

class TestInstallHappyPath(unittest.TestCase):
    """install() returns INSTALLED when Kodi successfully installs the add-on."""

    def _run(self, addon_id="plugin.video.test", enabled=True, version="1.0.0", desired="enabled"):
        poll_info = _make_info(addon_id, enabled=enabled, version=version)
        be = FakeAddonBackend(poll_result=poll_info)
        result = AddonManager(be).install(addon_id, desired_state=desired)
        return result, be

    def test_status_installed(self):
        result, _ = self._run()
        self.assertEqual(result.status, AddonStatus.INSTALLED)

    def test_invoke_called_once(self):
        _, be = self._run()
        self.assertEqual(len(be.invoke_calls), 1)

    def test_invoke_called_with_addon_id(self):
        _, be = self._run(addon_id="plugin.video.test")
        self.assertEqual(be.invoke_calls[0], "plugin.video.test")

    def test_poll_called_once(self):
        _, be = self._run()
        self.assertEqual(len(be.poll_calls), 1)

    def test_poll_called_with_addon_id(self):
        _, be = self._run(addon_id="plugin.video.test")
        self.assertEqual(be.poll_calls[0], "plugin.video.test")

    def test_enabled_from_poll(self):
        result, _ = self._run(enabled=True)
        self.assertTrue(result.enabled)

    def test_disabled_from_poll(self):
        result, _ = self._run(enabled=False)
        self.assertFalse(result.enabled)

    def test_version_from_poll(self):
        result, _ = self._run(version="3.1.0")
        self.assertEqual(result.version, "3.1.0")

    def test_desired_state_default_enabled(self):
        poll_info = _make_info()
        be = FakeAddonBackend(poll_result=poll_info)
        result = AddonManager(be).install("plugin.video.test")
        self.assertEqual(result.desired_state, "enabled")

    def test_desired_state_disabled_preserved(self):
        result, _ = self._run(desired="disabled")
        self.assertEqual(result.desired_state, "disabled")

    def test_addon_id_in_result(self):
        result, _ = self._run(addon_id="script.module.foo")
        self.assertEqual(result.addon_id, "script.module.foo")

    def test_message_mentions_installed(self):
        result, _ = self._run()
        self.assertIn("installed", result.message.lower())

    def test_details_called_before_invoke(self):
        poll_info = _make_info()
        be = FakeAddonBackend(poll_result=poll_info)
        calls = []
        orig_details = be.get_addon_details
        orig_invoke = be.invoke_install
        def tracked_details(addon_id):
            calls.append(("details", addon_id))
            return orig_details(addon_id)
        def tracked_invoke(addon_id):
            calls.append(("invoke", addon_id))
            orig_invoke(addon_id)
        be.get_addon_details = tracked_details
        be.invoke_install = tracked_invoke
        AddonManager(be).install("plugin.video.test")
        self.assertEqual(calls[0][0], "details")
        self.assertEqual(calls[1][0], "invoke")


# ---------------------------------------------------------------------------
# TestInstallInvalidId — FAILED before any backend call
# ---------------------------------------------------------------------------

class TestInstallInvalidId(unittest.TestCase):
    """install() with invalid addon_id returns FAILED without calling backend."""

    def _run(self, addon_id):
        be = FakeAddonBackend()
        result = AddonManager(be).install(addon_id)
        return result, be

    def test_status_failed_on_empty(self):
        result, _ = self._run("")
        self.assertEqual(result.status, AddonStatus.FAILED)

    def test_status_failed_on_paren(self):
        result, _ = self._run("addon(id)")
        self.assertEqual(result.status, AddonStatus.FAILED)

    def test_no_invoke_on_invalid(self):
        _, be = self._run("addon;id")
        self.assertEqual(be.invoke_calls, [])

    def test_no_poll_on_invalid(self):
        _, be = self._run("addon,id")
        self.assertEqual(be.poll_calls, [])

    def test_message_mentions_invalid(self):
        result, _ = self._run("bad id")
        self.assertIn("Invalid", result.message)

    def test_enabled_none_on_invalid(self):
        result, _ = self._run("")
        self.assertIsNone(result.enabled)

    def test_version_none_on_invalid(self):
        result, _ = self._run("")
        self.assertIsNone(result.version)


# ---------------------------------------------------------------------------
# TestInstallInvocationFailure — FAILED when invoke_install raises
# ---------------------------------------------------------------------------

class TestInstallInvocationFailure(unittest.TestCase):
    """install() returns FAILED when invoke_install raises AddonInstallError."""

    def _run(self, desired="enabled"):
        err = AddonInstallError("builtin not available")
        be = FakeAddonBackend(invoke_error=err)
        result = AddonManager(be).install("plugin.video.test", desired_state=desired)
        return result, be

    def test_status_failed(self):
        result, _ = self._run()
        self.assertEqual(result.status, AddonStatus.FAILED)

    def test_no_poll_after_invoke_fail(self):
        _, be = self._run()
        self.assertEqual(be.poll_calls, [])

    def test_message_mentions_invocation(self):
        result, _ = self._run()
        self.assertIn("invocation", result.message.lower())

    def test_enabled_none(self):
        result, _ = self._run()
        self.assertIsNone(result.enabled)

    def test_version_none(self):
        result, _ = self._run()
        self.assertIsNone(result.version)

    def test_desired_state_preserved(self):
        result, _ = self._run(desired="disabled")
        self.assertEqual(result.desired_state, "disabled")

    def test_addon_id_in_result(self):
        result, _ = self._run()
        self.assertEqual(result.addon_id, "plugin.video.test")


# ---------------------------------------------------------------------------
# TestInstallPollTimeout — FAILED when poll returns None
# ---------------------------------------------------------------------------

class TestInstallPollTimeout(unittest.TestCase):
    """install() returns FAILED when poll_addon_installed returns None (timeout)."""

    def _run(self, desired="enabled"):
        be = FakeAddonBackend(poll_result=None)
        result = AddonManager(be).install("plugin.video.test", desired_state=desired)
        return result, be

    def test_status_failed(self):
        result, _ = self._run()
        self.assertEqual(result.status, AddonStatus.FAILED)

    def test_invoke_was_called(self):
        _, be = self._run()
        self.assertEqual(len(be.invoke_calls), 1)

    def test_poll_was_called(self):
        _, be = self._run()
        self.assertEqual(len(be.poll_calls), 1)

    def test_message_mentions_timeout(self):
        result, _ = self._run()
        self.assertIn("timeout", result.message.lower())

    def test_enabled_none(self):
        result, _ = self._run()
        self.assertIsNone(result.enabled)

    def test_version_none(self):
        result, _ = self._run()
        self.assertIsNone(result.version)

    def test_desired_state_preserved(self):
        result, _ = self._run(desired="disabled")
        self.assertEqual(result.desired_state, "disabled")


# ---------------------------------------------------------------------------
# TestInstallPollError — FAILED when poll raises
# ---------------------------------------------------------------------------

class TestInstallPollError(unittest.TestCase):
    """install() returns FAILED when poll_addon_installed raises AddonInstallError."""

    def _run(self):
        err = AddonInstallError("poll infrastructure error")
        be = FakeAddonBackend(poll_error=err)
        result = AddonManager(be).install("plugin.video.test")
        return result, be

    def test_status_failed(self):
        result, _ = self._run()
        self.assertEqual(result.status, AddonStatus.FAILED)

    def test_message_mentions_verification(self):
        result, _ = self._run()
        self.assertIn("verification", result.message.lower())

    def test_invoke_was_called(self):
        _, be = self._run()
        self.assertEqual(len(be.invoke_calls), 1)

    def test_enabled_none(self):
        result, _ = self._run()
        self.assertIsNone(result.enabled)


# ---------------------------------------------------------------------------
# TestResultFields — all fields populated on every path
# ---------------------------------------------------------------------------

class TestResultFields(unittest.TestCase):
    """AddonInstallResult fields are always populated correctly."""

    def test_installed_result_has_all_fields(self):
        poll_info = _make_info("plugin.video.test", enabled=True, version="1.0.0")
        be = FakeAddonBackend(poll_result=poll_info)
        result = AddonManager(be).install("plugin.video.test", desired_state="enabled")
        self.assertEqual(result.addon_id, "plugin.video.test")
        self.assertEqual(result.status, AddonStatus.INSTALLED)
        self.assertEqual(result.desired_state, "enabled")
        self.assertTrue(result.enabled)
        self.assertEqual(result.version, "1.0.0")
        self.assertIsInstance(result.message, str)

    def test_already_installed_result_has_all_fields(self):
        info = _make_info("plugin.video.test", enabled=False, version="2.0.0")
        be = FakeAddonBackend(installed={"plugin.video.test": info})
        result = AddonManager(be).install("plugin.video.test", desired_state="disabled")
        self.assertEqual(result.addon_id, "plugin.video.test")
        self.assertEqual(result.status, AddonStatus.ALREADY_INSTALLED)
        self.assertEqual(result.desired_state, "disabled")
        self.assertFalse(result.enabled)
        self.assertEqual(result.version, "2.0.0")
        self.assertIsInstance(result.message, str)

    def test_failed_result_has_none_fields(self):
        result = AddonManager(FakeAddonBackend()).install("bad id")
        self.assertEqual(result.status, AddonStatus.FAILED)
        self.assertIsNone(result.enabled)
        self.assertIsNone(result.version)
        self.assertIsInstance(result.message, str)

    def test_result_is_immutable(self):
        poll_info = _make_info()
        be = FakeAddonBackend(poll_result=poll_info)
        result = AddonManager(be).install("plugin.video.test")
        with self.assertRaises((TypeError, AttributeError)):
            result.status = AddonStatus.FAILED  # type: ignore[misc]

    def test_installed_info_is_immutable(self):
        info = _make_info()
        with self.assertRaises((TypeError, AttributeError)):
            info.enabled = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestDesiredState — preserved verbatim in all result paths
# ---------------------------------------------------------------------------

class TestDesiredState(unittest.TestCase):
    """desired_state passes through to result on every code path."""

    def test_enabled_in_installed_result(self):
        be = FakeAddonBackend(poll_result=_make_info())
        result = AddonManager(be).install("a.b", desired_state="enabled")
        self.assertEqual(result.desired_state, "enabled")

    def test_disabled_in_installed_result(self):
        be = FakeAddonBackend(poll_result=_make_info())
        result = AddonManager(be).install("a.b", desired_state="disabled")
        self.assertEqual(result.desired_state, "disabled")

    def test_custom_in_failed_result(self):
        be = FakeAddonBackend(poll_result=None)
        result = AddonManager(be).install("a.b", desired_state="custom")
        self.assertEqual(result.desired_state, "custom")

    def test_default_is_enabled(self):
        be = FakeAddonBackend(poll_result=_make_info())
        result = AddonManager(be).install("a.b")
        self.assertEqual(result.desired_state, "enabled")

    def test_in_already_installed_result(self):
        be = FakeAddonBackend(installed={"a.b": _make_info("a.b")})
        result = AddonManager(be).install("a.b", desired_state="disabled")
        self.assertEqual(result.desired_state, "disabled")


# ---------------------------------------------------------------------------
# TestAddonStatusEnum
# ---------------------------------------------------------------------------

class TestAddonStatusEnum(unittest.TestCase):
    def test_values(self):
        self.assertEqual(AddonStatus.ALREADY_INSTALLED.value, "already_installed")
        self.assertEqual(AddonStatus.INSTALLED.value, "installed")
        self.assertEqual(AddonStatus.FAILED.value, "failed")

    def test_str_comparison(self):
        self.assertEqual(AddonStatus.INSTALLED, "installed")


# ---------------------------------------------------------------------------
# TestKodiRuntimeBackend — unit tests with mocked xbmc
# ---------------------------------------------------------------------------

class TestKodiRuntimeBackend(unittest.TestCase):
    """KodiRuntimeAddonBackend: verify correct JSON-RPC usage (no real Kodi)."""

    def _backend(self, xbmc_mock):
        be = KodiRuntimeAddonBackend()
        be._xbmc = lambda: xbmc_mock
        return be

    def _xbmc_response(self, xbmc_mock, result_body: dict):
        xbmc_mock.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": result_body,
        })

    def _xbmc_error(self, xbmc_mock, code=-32602):
        xbmc_mock.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": code, "message": "Not Found"},
        })

    # get_addon_details

    def test_get_addon_details_returns_info_when_found(self):
        xbmc = MagicMock()
        self._xbmc_response(xbmc, {
            "addon": {"addonid": "plugin.video.test", "enabled": True, "version": "1.0.0"}
        })
        be = self._backend(xbmc)
        info = be.get_addon_details("plugin.video.test")
        self.assertIsNotNone(info)
        self.assertEqual(info.addon_id, "plugin.video.test")
        self.assertTrue(info.enabled)
        self.assertEqual(info.version, "1.0.0")

    def test_get_addon_details_returns_none_when_not_found(self):
        xbmc = MagicMock()
        self._xbmc_error(xbmc)
        be = self._backend(xbmc)
        info = be.get_addon_details("not.installed")
        self.assertIsNone(info)

    def test_get_addon_details_uses_get_addon_details_jsonrpc(self):
        xbmc = MagicMock()
        self._xbmc_response(xbmc, {
            "addon": {"addonid": "a.b", "enabled": True, "version": "1.0.0"}
        })
        be = self._backend(xbmc)
        be.get_addon_details("a.b")
        call_arg = xbmc.executeJSONRPC.call_args[0][0]
        call_json = json.loads(call_arg)
        self.assertEqual(call_json["method"], "Addons.GetAddonDetails")

    def test_get_addon_details_requests_enabled_property(self):
        xbmc = MagicMock()
        self._xbmc_response(xbmc, {
            "addon": {"addonid": "a.b", "enabled": True, "version": "1.0.0"}
        })
        be = self._backend(xbmc)
        be.get_addon_details("a.b")
        call_json = json.loads(xbmc.executeJSONRPC.call_args[0][0])
        self.assertIn("enabled", call_json["params"]["properties"])

    def test_get_addon_details_requests_version_property(self):
        xbmc = MagicMock()
        self._xbmc_response(xbmc, {
            "addon": {"addonid": "a.b", "enabled": True, "version": "2.0.0"}
        })
        be = self._backend(xbmc)
        be.get_addon_details("a.b")
        call_json = json.loads(xbmc.executeJSONRPC.call_args[0][0])
        self.assertIn("version", call_json["params"]["properties"])

    def test_get_addon_details_disabled_addon(self):
        xbmc = MagicMock()
        self._xbmc_response(xbmc, {
            "addon": {"addonid": "plugin.video.test", "enabled": False, "version": "1.0.0"}
        })
        be = self._backend(xbmc)
        info = be.get_addon_details("plugin.video.test")
        self.assertIsNotNone(info)
        self.assertFalse(info.enabled)

    def test_get_addon_details_returns_none_on_id_mismatch(self):
        xbmc = MagicMock()
        self._xbmc_response(xbmc, {
            "addon": {"addonid": "different.addon", "enabled": True, "version": "1.0.0"}
        })
        be = self._backend(xbmc)
        info = be.get_addon_details("plugin.video.test")
        self.assertIsNone(info)

    def test_get_addon_details_returns_none_on_missing_result(self):
        xbmc = MagicMock()
        xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0", "id": 1, "result": None
        })
        be = self._backend(xbmc)
        info = be.get_addon_details("plugin.video.test")
        self.assertIsNone(info)

    # invoke_install

    def test_invoke_install_calls_executebuiltin(self):
        xbmc = MagicMock()
        be = self._backend(xbmc)
        be.invoke_install("plugin.video.test")
        xbmc.executebuiltin.assert_called_once()

    def test_invoke_install_includes_addon_id_in_builtin(self):
        xbmc = MagicMock()
        be = self._backend(xbmc)
        be.invoke_install("plugin.video.test")
        call_arg = xbmc.executebuiltin.call_args[0][0]
        self.assertIn("plugin.video.test", call_arg)
        self.assertIn("InstallAddon", call_arg)

    def test_invoke_install_does_not_call_jsonrpc(self):
        xbmc = MagicMock()
        be = self._backend(xbmc)
        be.invoke_install("plugin.video.test")
        xbmc.executeJSONRPC.assert_not_called()

    # poll_addon_installed

    def test_poll_returns_info_on_first_success(self):
        xbmc = MagicMock()
        self._xbmc_response(xbmc, {
            "addon": {"addonid": "plugin.video.test", "enabled": True, "version": "1.0.0"}
        })
        be = self._backend(xbmc)
        info = be.poll_addon_installed("plugin.video.test", timeout=5.0, interval=0.0)
        self.assertIsNotNone(info)
        self.assertEqual(info.addon_id, "plugin.video.test")

    def test_poll_returns_none_on_timeout(self):
        xbmc = MagicMock()
        self._xbmc_error(xbmc)
        be = self._backend(xbmc)
        info = be.poll_addon_installed("not.installed", timeout=0.01, interval=0.001)
        self.assertIsNone(info)

    # xbmc unavailable

    def test_raises_when_xbmc_unavailable(self):
        be = KodiRuntimeAddonBackend()
        with patch.dict("sys.modules", {"xbmc": None}):
            with self.assertRaises(AddonInstallError):
                be.get_addon_details("plugin.video.test")


# ---------------------------------------------------------------------------
# TestAddonBackendInterface — abstract base stubs NotImplementedError
# ---------------------------------------------------------------------------

class TestAddonBackendInterface(unittest.TestCase):
    def test_get_addon_details_raises(self):
        with self.assertRaises(NotImplementedError):
            AddonBackend().get_addon_details("a.b")

    def test_invoke_install_raises(self):
        with self.assertRaises(NotImplementedError):
            AddonBackend().invoke_install("a.b")

    def test_poll_addon_installed_raises(self):
        with self.assertRaises(NotImplementedError):
            AddonBackend().poll_addon_installed("a.b")


# ---------------------------------------------------------------------------
# TestAddonErrorHierarchy
# ---------------------------------------------------------------------------

class TestAddonErrorHierarchy(unittest.TestCase):
    def test_validation_error_is_addon_error(self):
        self.assertTrue(issubclass(AddonValidationError, AddonError))

    def test_install_error_is_addon_error(self):
        self.assertTrue(issubclass(AddonInstallError, AddonError))


if __name__ == "__main__":
    unittest.main()
