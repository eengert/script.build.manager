"""
Unit tests for resources/lib/addons.py (BM-011-C).

All tests run without Kodi — no xbmc imports required.
Tests cover:
  VALIDATION        -- addon_id grammar enforcement (injection prevention)
  URL_SECURITY      -- _validate_url accepts only safe http/https URLs
  FETCH_BYTES       -- _fetch_bytes: bounded download, error mapping
  ZIP_VALIDATION    -- _validate_addon_zip: safe paths, ID match, traversal
  STAGED_INSTALL    -- _staged_install: temp dir, atomic rename, cleanup
  IS_INSTALLED      -- detection via backend.get_addon_details
  IDEMPOTENCY       -- ALREADY_INSTALLED when already present, no mutation
  HAPPY_PATH        -- INSTALLED when Kodi successfully installs the add-on
  DESIRED_STATE     -- set_addon_enabled called symmetrically on enabled/disabled
  ENABLE_FAIL       -- FAILED when set_addon_enabled raises
  INVALID_ID        -- FAILED before any backend call on bad addon_id
  INVOKE_FAIL       -- FAILED when invoke_install raises
  POLL_TIMEOUT      -- FAILED when poll returns None (install didn't complete)
  POLL_ERROR        -- FAILED when poll_addon_installed raises
  RESULT_FIELDS     -- all fields populated correctly on every path
  RUNTIME_BACKEND   -- KodiRuntimeAddonBackend unit tests (mocked xbmc)
  REPO_RESOLUTION   -- _resolve_package_url scenarios
"""

import io
import json
import pathlib
import tempfile
import unittest
import urllib.request
import zipfile
from typing import Dict, List, Optional
from unittest.mock import MagicMock, call, patch

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
    _MAX_ADDON_ZIP_BYTES,
    _MAX_ADDONS_XML_BYTES,
    _SafeRedirectHandler,
    _validate_addon_id,
    _validate_addon_zip,
    _validate_url,
    _staged_install,
)


# ---------------------------------------------------------------------------
# Fake backend for unit tests
# ---------------------------------------------------------------------------

class FakeAddonBackend(AddonBackend):
    """Configurable fake backend for AddonManager unit tests.

    After poll_addon_installed returns _poll_result, the result is registered
    in _installed so that subsequent get_addon_details calls find it.
    set_addon_enabled updates the installed entry to reflect the requested
    enabled bool (unless _set_enabled_error is set, in which case it raises).
    """

    def __init__(
        self,
        installed: Optional[Dict[str, InstalledAddonInfo]] = None,
        invoke_error: Optional[Exception] = None,
        poll_result: Optional[InstalledAddonInfo] = None,
        poll_error: Optional[Exception] = None,
        set_enabled_error: Optional[Exception] = None,
    ):
        self._installed: Dict[str, InstalledAddonInfo] = dict(installed or {})
        self._invoke_error = invoke_error
        self._poll_result = poll_result
        self._poll_error = poll_error
        self._set_enabled_error = set_enabled_error
        self.invoke_calls: List[str] = []
        self.poll_calls: List[str] = []
        self.details_calls: List[str] = []
        self.set_enabled_calls: List[tuple] = []

    def get_addon_details(self, addon_id: str) -> Optional[InstalledAddonInfo]:
        self.details_calls.append(addon_id)
        return self._installed.get(addon_id)

    def invoke_install(self, addon_id: str) -> None:
        self.invoke_calls.append(addon_id)
        if self._invoke_error is not None:
            raise self._invoke_error

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        self.set_enabled_calls.append((addon_id, enabled))
        if self._set_enabled_error is not None:
            raise self._set_enabled_error
        # Update the installed entry so get_addon_details reflects new state
        if addon_id in self._installed:
            old = self._installed[addon_id]
            self._installed[addon_id] = InstalledAddonInfo(
                addon_id=old.addon_id, enabled=enabled, version=old.version
            )

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
        if self._poll_result is not None:
            # Register poll result in _installed so get_addon_details finds it
            self._installed[addon_id] = self._poll_result
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
        # desired="disabled" + poll=disabled → set_addon_enabled NOT called → result reflects poll state
        result, _ = self._run(enabled=False, desired="disabled")
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

    def test_message_mentions_install_failed(self):
        result, _ = self._run()
        self.assertIn("install", result.message.lower())

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

    def test_custom_rejected_before_any_backend_call(self):
        be = FakeAddonBackend(poll_result=None)
        result = AddonManager(be).install("a.b", desired_state="custom")
        self.assertEqual(result.status, AddonStatus.FAILED)
        self.assertEqual(result.desired_state, "custom")
        self.assertEqual(be.invoke_calls, [])
        self.assertEqual(be.details_calls, [])

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

    # invoke_install — tests patch the internal helpers to isolate the orchestration

    def _make_test_zip(self, addon_id: str, version: str = "1.0.0") -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                f"{addon_id}/addon.xml",
                f'<?xml version="1.0"?><addon id="{addon_id}" version="{version}"/>',
            )
        return buf.getvalue()

    def _invoke_with_patches(self, addon_id="plugin.video.test", version="1.0.0"):
        """Run invoke_install with all internal helpers mocked out."""
        xbmc = MagicMock()
        be = self._backend(xbmc)
        zip_data = self._make_test_zip(addon_id, version)
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            with patch.object(be, "_resolve_package_url", return_value=(
                f"http://127.0.0.1:8922/{addon_id}/{version}/{addon_id}-{version}.zip",
                version,
            )), \
            patch(
                "resources.lib.addons._fetch_bytes", return_value=zip_data
            ), \
            patch(
                "resources.lib.addons._validate_addon_zip", return_value=version
            ), \
            patch(
                "resources.lib.addons._staged_install"
            ) as mock_stage, \
            patch.object(be, "_get_addons_dir", return_value=addons_dir):
                be.invoke_install(addon_id)
                return xbmc, mock_stage

    def test_invoke_install_calls_update_local_addons(self):
        xbmc, _ = self._invoke_with_patches()
        xbmc.executebuiltin.assert_called_once_with("UpdateLocalAddons")

    def test_invoke_install_does_not_call_install_addon_builtin(self):
        xbmc, _ = self._invoke_with_patches()
        builtin_arg = xbmc.executebuiltin.call_args[0][0]
        self.assertNotIn("InstallAddon", builtin_arg)

    def test_invoke_install_calls_staged_install(self):
        _, mock_stage = self._invoke_with_patches()
        mock_stage.assert_called_once()

    def test_invoke_install_raises_when_target_exists(self):
        xbmc = MagicMock()
        be = self._backend(xbmc)
        version = "1.0.0"
        addon_id = "plugin.video.test"
        zip_data = self._make_test_zip(addon_id)
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            # Pre-create target to simulate already-installed on disk
            (addons_dir / addon_id).mkdir()
            with patch.object(be, "_resolve_package_url", return_value=(
                f"http://127.0.0.1:8922/{addon_id}/{version}/{addon_id}-{version}.zip",
                version,
            )), \
            patch("resources.lib.addons._fetch_bytes", return_value=zip_data), \
            patch("resources.lib.addons._validate_addon_zip", return_value=version), \
            patch.object(be, "_get_addons_dir", return_value=addons_dir):
                with self.assertRaises(AddonInstallError):
                    be.invoke_install(addon_id)

    def test_invoke_install_raises_when_resolve_fails(self):
        xbmc = MagicMock()
        be = self._backend(xbmc)
        with patch.object(
            be, "_resolve_package_url",
            side_effect=AddonInstallError("no repos"),
        ):
            with self.assertRaises(AddonInstallError):
                be.invoke_install("plugin.video.test")

    # set_addon_enabled

    def test_set_addon_enabled_true_calls_jsonrpc(self):
        xbmc = MagicMock()
        xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0", "id": 1, "result": "OK"
        })
        be = self._backend(xbmc)
        be.set_addon_enabled("plugin.video.test", True)
        call_json = json.loads(xbmc.executeJSONRPC.call_args[0][0])
        self.assertEqual(call_json["method"], "Addons.SetAddonEnabled")
        self.assertEqual(call_json["params"]["addonid"], "plugin.video.test")
        self.assertTrue(call_json["params"]["enabled"])

    def test_set_addon_enabled_false_calls_jsonrpc(self):
        xbmc = MagicMock()
        xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0", "id": 1, "result": "OK"
        })
        be = self._backend(xbmc)
        be.set_addon_enabled("plugin.video.test", False)
        call_json = json.loads(xbmc.executeJSONRPC.call_args[0][0])
        self.assertEqual(call_json["params"]["enabled"], False)

    def test_set_addon_enabled_raises_on_json_error(self):
        xbmc = MagicMock()
        xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32602, "message": "addon not found"},
        })
        be = self._backend(xbmc)
        with self.assertRaises(AddonInstallError):
            be.set_addon_enabled("plugin.video.test", True)

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

    def test_set_addon_enabled_raises(self):
        with self.assertRaises(NotImplementedError):
            AddonBackend().set_addon_enabled("a.b", True)

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


# ---------------------------------------------------------------------------
# TestValidateUrl — URL security
# ---------------------------------------------------------------------------

class TestValidateUrl(unittest.TestCase):
    """_validate_url accepts only safe http/https URLs; rejects all else."""

    def test_http_allowed(self):
        _validate_url("http://example.com/addons.xml")

    def test_https_allowed(self):
        _validate_url("https://example.com/addons.xml")

    def test_localhost_http_allowed(self):
        _validate_url("http://127.0.0.1:8922/addons.xml")

    def test_file_scheme_rejected(self):
        with self.assertRaises(AddonInstallError):
            _validate_url("file:///etc/passwd")

    def test_ftp_scheme_rejected(self):
        with self.assertRaises(AddonInstallError):
            _validate_url("ftp://example.com/file.zip")

    def test_no_scheme_rejected(self):
        with self.assertRaises(AddonInstallError):
            _validate_url("example.com/file.zip")

    def test_empty_string_rejected(self):
        with self.assertRaises(AddonInstallError):
            _validate_url("")

    def test_none_rejected(self):
        with self.assertRaises(AddonInstallError):
            _validate_url(None)  # type: ignore[arg-type]

    def test_credentials_rejected(self):
        with self.assertRaises(AddonInstallError):
            _validate_url("http://user:pass@example.com/file.zip")

    def test_username_only_rejected(self):
        with self.assertRaises(AddonInstallError):
            _validate_url("http://user@example.com/file.zip")

    def test_missing_host_rejected(self):
        with self.assertRaises(AddonInstallError):
            _validate_url("http:///path")

    def test_context_appears_in_error(self):
        with self.assertRaises(AddonInstallError) as ctx:
            _validate_url("ftp://x.com", context="datadir URL")
        self.assertIn("datadir URL", str(ctx.exception))


# ---------------------------------------------------------------------------
# TestValidateAddonZip — ZIP content validation
# ---------------------------------------------------------------------------

def _make_zip(addon_id: str, version: str = "1.0.0", extra_files=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"{addon_id}/addon.xml",
            f'<?xml version="1.0"?><addon id="{addon_id}" version="{version}"/>',
        )
        for name, data in (extra_files or []):
            zf.writestr(name, data)
    return buf.getvalue()


class TestValidateAddonZip(unittest.TestCase):
    """_validate_addon_zip: version returned on success; various failures raise AddonInstallError."""

    def test_valid_zip_returns_version(self):
        data = _make_zip("plugin.video.test", "2.1.0")
        ver = _validate_addon_zip(data, "plugin.video.test")
        self.assertEqual(ver, "2.1.0")

    def test_expected_version_match_ok(self):
        data = _make_zip("plugin.video.test", "1.0.0")
        ver = _validate_addon_zip(data, "plugin.video.test", expected_version="1.0.0")
        self.assertEqual(ver, "1.0.0")

    def test_expected_version_mismatch_raises(self):
        data = _make_zip("plugin.video.test", "2.0.0")
        with self.assertRaises(AddonInstallError):
            _validate_addon_zip(data, "plugin.video.test", expected_version="1.0.0")

    def test_invalid_zip_raises(self):
        with self.assertRaises(AddonInstallError):
            _validate_addon_zip(b"not a zip", "plugin.video.test")

    def test_missing_addon_xml_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plugin.video.test/README.txt", "hello")
        with self.assertRaises(AddonInstallError):
            _validate_addon_zip(buf.getvalue(), "plugin.video.test")

    def test_id_mismatch_raises(self):
        data = _make_zip("plugin.video.test")
        with self.assertRaises(AddonInstallError):
            _validate_addon_zip(data, "plugin.video.other")

    def test_traversal_path_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plugin.video.test/addon.xml",
                        '<addon id="plugin.video.test" version="1.0"/>')
            zf.writestr("plugin.video.test/../../../evil.py", "harm")
        with self.assertRaises(AddonInstallError):
            _validate_addon_zip(buf.getvalue(), "plugin.video.test")

    def test_absolute_path_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plugin.video.test/addon.xml",
                        '<addon id="plugin.video.test" version="1.0"/>'),
            zf.writestr("/etc/evil", "harm")
        with self.assertRaises(AddonInstallError):
            _validate_addon_zip(buf.getvalue(), "plugin.video.test")

    def test_malformed_addon_xml_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plugin.video.test/addon.xml", "<<<not xml")
        with self.assertRaises(AddonInstallError):
            _validate_addon_zip(buf.getvalue(), "plugin.video.test")

    def test_no_version_attribute_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plugin.video.test/addon.xml",
                        '<addon id="plugin.video.test"/>')
        with self.assertRaises(AddonInstallError):
            _validate_addon_zip(buf.getvalue(), "plugin.video.test")

    def test_extra_files_ok(self):
        data = _make_zip("plugin.video.test", extra_files=[
            ("plugin.video.test/resources/data.json", "{}"),
        ])
        ver = _validate_addon_zip(data, "plugin.video.test")
        self.assertEqual(ver, "1.0.0")


# ---------------------------------------------------------------------------
# TestStagedInstall — staged extraction + atomic rename
# ---------------------------------------------------------------------------

class TestStagedInstall(unittest.TestCase):
    """_staged_install: extracts to temp dir, renames atomically, cleans up staging."""

    def test_happy_path_places_addon_in_addons_dir(self):
        data = _make_zip("plugin.video.test")
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            _staged_install(data, "plugin.video.test", addons_dir)
            self.assertTrue((addons_dir / "plugin.video.test").is_dir())

    def test_addon_xml_present_after_install(self):
        data = _make_zip("plugin.video.test")
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            _staged_install(data, "plugin.video.test", addons_dir)
            self.assertTrue((addons_dir / "plugin.video.test" / "addon.xml").is_file())

    def test_staging_dir_cleaned_up_on_success(self):
        data = _make_zip("plugin.video.test")
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            _staged_install(data, "plugin.video.test", addons_dir)
            staging = addons_dir / "_bm011_staging_plugin.video.test"
            self.assertFalse(staging.exists())

    def test_stale_staging_dir_cleaned_before_install(self):
        data = _make_zip("plugin.video.test")
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            staging = addons_dir / "_bm011_staging_plugin.video.test"
            staging.mkdir()
            (staging / "leftover.txt").write_text("stale")
            _staged_install(data, "plugin.video.test", addons_dir)
            self.assertFalse(staging.exists())
            self.assertTrue((addons_dir / "plugin.video.test").is_dir())

    def test_invalid_zip_raises_and_no_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            with self.assertRaises(AddonInstallError):
                _staged_install(b"garbage", "plugin.video.test", addons_dir)
            self.assertFalse((addons_dir / "plugin.video.test").exists())

    def test_staging_cleaned_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            try:
                _staged_install(b"garbage", "plugin.video.test", addons_dir)
            except AddonInstallError:
                pass
            staging = addons_dir / "_bm011_staging_plugin.video.test"
            self.assertFalse(staging.exists())

    def test_zip_missing_expected_subdir_raises(self):
        # ZIP has wrong top-level directory name
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("wrong.name/addon.xml", '<addon id="wrong.name" version="1.0"/>')
        with tempfile.TemporaryDirectory() as tmp:
            addons_dir = pathlib.Path(tmp)
            with self.assertRaises(AddonInstallError):
                _staged_install(buf.getvalue(), "plugin.video.test", addons_dir)


# ---------------------------------------------------------------------------
# TestDesiredStateEnable — set_addon_enabled called when poll returns disabled
# ---------------------------------------------------------------------------

class TestDesiredStateEnable(unittest.TestCase):
    """install() with desired_state='enabled' calls set_addon_enabled(True) when poll returns disabled."""

    def test_set_enabled_called_when_poll_returns_disabled(self):
        poll_info = _make_info("plugin.video.test", enabled=False)
        be = FakeAddonBackend(poll_result=poll_info)
        AddonManager(be).install("plugin.video.test", desired_state="enabled")
        self.assertEqual(be.set_enabled_calls, [("plugin.video.test", True)])

    def test_set_enabled_not_called_when_poll_returns_enabled(self):
        poll_info = _make_info("plugin.video.test", enabled=True)
        be = FakeAddonBackend(poll_result=poll_info)
        AddonManager(be).install("plugin.video.test", desired_state="enabled")
        self.assertEqual(be.set_enabled_calls, [])

    def test_result_enabled_after_enable(self):
        poll_info = _make_info("plugin.video.test", enabled=False)
        be = FakeAddonBackend(poll_result=poll_info)
        result = AddonManager(be).install("plugin.video.test", desired_state="enabled")
        self.assertEqual(result.status, AddonStatus.INSTALLED)
        self.assertTrue(result.enabled)

    def test_result_version_preserved_after_enable(self):
        poll_info = _make_info("plugin.video.test", enabled=False, version="3.2.1")
        be = FakeAddonBackend(poll_result=poll_info)
        result = AddonManager(be).install("plugin.video.test", desired_state="enabled")
        self.assertEqual(result.version, "3.2.1")


# ---------------------------------------------------------------------------
# TestDesiredStateDisable — set_addon_enabled(False) called when poll returns enabled
# ---------------------------------------------------------------------------

class TestDesiredStateDisable(unittest.TestCase):
    """install() with desired_state='disabled' calls set_addon_enabled(False) when poll returns enabled."""

    def test_set_enabled_false_called_when_poll_returns_enabled(self):
        poll_info = _make_info("plugin.video.test", enabled=True)
        be = FakeAddonBackend(poll_result=poll_info)
        AddonManager(be).install("plugin.video.test", desired_state="disabled")
        self.assertEqual(be.set_enabled_calls, [("plugin.video.test", False)])

    def test_set_enabled_not_called_when_poll_returns_disabled(self):
        poll_info = _make_info("plugin.video.test", enabled=False)
        be = FakeAddonBackend(poll_result=poll_info)
        AddonManager(be).install("plugin.video.test", desired_state="disabled")
        self.assertEqual(be.set_enabled_calls, [])

    def test_result_enabled_false_when_desired_disabled(self):
        poll_info = _make_info("plugin.video.test", enabled=False)
        be = FakeAddonBackend(poll_result=poll_info)
        result = AddonManager(be).install("plugin.video.test", desired_state="disabled")
        self.assertFalse(result.enabled)

    def test_status_installed_when_desired_disabled(self):
        poll_info = _make_info("plugin.video.test", enabled=False)
        be = FakeAddonBackend(poll_result=poll_info)
        result = AddonManager(be).install("plugin.video.test", desired_state="disabled")
        self.assertEqual(result.status, AddonStatus.INSTALLED)


# ---------------------------------------------------------------------------
# TestSetAddonEnabledFails — FAILED when set_addon_enabled raises
# ---------------------------------------------------------------------------

class TestSetAddonEnabledFails(unittest.TestCase):
    """install() returns FAILED when set_addon_enabled raises AddonInstallError."""

    def _run(self, desired_state="enabled", poll_enabled=False):
        poll_info = _make_info("plugin.video.test", enabled=poll_enabled)
        be = FakeAddonBackend(
            poll_result=poll_info,
            set_enabled_error=AddonInstallError("SetAddonEnabled rejected"),
        )
        return AddonManager(be).install("plugin.video.test", desired_state=desired_state)

    def test_status_failed_on_enable(self):
        self.assertEqual(self._run(desired_state="enabled", poll_enabled=False).status, AddonStatus.FAILED)

    def test_status_failed_on_disable(self):
        self.assertEqual(self._run(desired_state="disabled", poll_enabled=True).status, AddonStatus.FAILED)

    def test_message_mentions_state_change(self):
        self.assertIn("state", self._run().message.lower())

    def test_enabled_none_on_fail(self):
        self.assertIsNone(self._run().enabled)

    def test_version_none_on_fail(self):
        self.assertIsNone(self._run().version)


# ---------------------------------------------------------------------------
# TestRepoResolution — _resolve_package_url scenarios (mocked Kodi)
# ---------------------------------------------------------------------------

def _make_addons_xml(addon_id: str, version: str) -> bytes:
    return (
        f'<?xml version="1.0"?><addons>'
        f'<addon id="{addon_id}" version="{version}"/>'
        f'</addons>'
    ).encode()


def _make_repo_addon_xml(info_url: str, datadir_url: str) -> bytes:
    return (
        '<?xml version="1.0"?>'
        '<addon id="repository.test" version="1.0">'
        '<extension point="xbmc.addon.repository" name="Test Repo">'
        f'<dir><info compressed="false">{info_url}</info>'
        f'<checksum>{info_url}.md5</checksum>'
        f'<datadir zip="true">{datadir_url}</datadir></dir>'
        '</extension>'
        '</addon>'
    ).encode()


class TestRepoResolution(unittest.TestCase):
    """_resolve_package_url: mocked xbmc/xbmcvfs/xbmcaddon, mocked HTTP."""

    def _mock_xbmc(self, repo_ids, enabled_repos, addon_xml_content, addons_xml_content):
        """Build a mock xbmc that returns repo list, details, and addon XML."""
        xbmc_mock = MagicMock()
        call_count = [0]

        def execute_jsonrpc(req_str):
            req = json.loads(req_str)
            if req["method"] == "Addons.GetAddons":
                return json.dumps({
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"addons": [{"addonid": r} for r in repo_ids]},
                })
            if req["method"] == "Addons.GetAddonDetails":
                repo_id = req["params"]["addonid"]
                enabled = repo_id in enabled_repos
                return json.dumps({
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"addon": {"addonid": repo_id, "enabled": enabled}},
                })
            return json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -1}})

        xbmc_mock.executeJSONRPC.side_effect = execute_jsonrpc
        return xbmc_mock

    def _backend_with_mocks(self, repo_ids, enabled_repos,
                             addon_xml_bytes, addons_xml_bytes,
                             info_url="http://127.0.0.1:8922/addons.xml",
                             datadir_url="http://127.0.0.1:8922"):
        be = KodiRuntimeAddonBackend()
        xbmc_mock = self._mock_xbmc(repo_ids, enabled_repos, addon_xml_bytes, addons_xml_bytes)
        be._xbmc = lambda: xbmc_mock

        addon_xml = _make_repo_addon_xml(info_url, datadir_url)
        addons_xml = addons_xml_bytes

        fake_file = MagicMock()
        fake_file.read.return_value = addon_xml.decode("utf-8")

        xbmcaddon_mock = MagicMock()
        xbmcaddon_mock.Addon.return_value.getAddonInfo.return_value = "/kodi/addons/repo/"
        xbmcvfs_mock = MagicMock()
        xbmcvfs_mock.File.return_value = fake_file

        return be, xbmc_mock, xbmcaddon_mock, xbmcvfs_mock, addons_xml

    def test_found_in_first_repo_returns_url_and_version(self):
        addons_xml = _make_addons_xml("plugin.video.test", "2.0.0")
        be, _, xbmcaddon_m, xbmcvfs_m, addons_xml_data = self._backend_with_mocks(
            repo_ids=["repository.test"],
            enabled_repos={"repository.test"},
            addon_xml_bytes=b"",
            addons_xml_bytes=addons_xml,
        )
        with patch.dict("sys.modules", {
            "xbmcaddon": xbmcaddon_m, "xbmcvfs": xbmcvfs_m,
        }), patch("resources.lib.addons._fetch_bytes", return_value=addons_xml_data):
            url, version = be._resolve_package_url("plugin.video.test")
        self.assertIn("plugin.video.test", url)
        self.assertIn("2.0.0", url)
        self.assertEqual(version, "2.0.0")

    def test_url_ends_with_expected_zip_filename(self):
        addons_xml = _make_addons_xml("plugin.video.test", "1.5.0")
        be, _, xbmcaddon_m, xbmcvfs_m, addons_xml_data = self._backend_with_mocks(
            repo_ids=["repository.test"],
            enabled_repos={"repository.test"},
            addon_xml_bytes=b"",
            addons_xml_bytes=addons_xml,
        )
        with patch.dict("sys.modules", {
            "xbmcaddon": xbmcaddon_m, "xbmcvfs": xbmcvfs_m,
        }), patch("resources.lib.addons._fetch_bytes", return_value=addons_xml_data):
            url, _ = be._resolve_package_url("plugin.video.test")
        self.assertTrue(url.endswith("plugin.video.test/1.5.0/plugin.video.test-1.5.0.zip"))

    def test_not_found_raises(self):
        addons_xml = _make_addons_xml("plugin.video.other", "1.0.0")
        be, _, xbmcaddon_m, xbmcvfs_m, addons_xml_data = self._backend_with_mocks(
            repo_ids=["repository.test"],
            enabled_repos={"repository.test"},
            addon_xml_bytes=b"",
            addons_xml_bytes=addons_xml,
        )
        with patch.dict("sys.modules", {
            "xbmcaddon": xbmcaddon_m, "xbmcvfs": xbmcvfs_m,
        }), patch("resources.lib.addons._fetch_bytes", return_value=addons_xml_data):
            with self.assertRaises(AddonInstallError):
                be._resolve_package_url("plugin.video.test")

    def test_disabled_repo_skipped(self):
        addons_xml = _make_addons_xml("plugin.video.test", "1.0.0")
        be, _, xbmcaddon_m, xbmcvfs_m, addons_xml_data = self._backend_with_mocks(
            repo_ids=["repository.disabled", "repository.enabled"],
            enabled_repos={"repository.enabled"},
            addon_xml_bytes=b"",
            addons_xml_bytes=addons_xml,
        )
        repo_addon_xml = _make_repo_addon_xml(
            "http://127.0.0.1:8922/addons.xml",
            "http://127.0.0.1:8922",
        )
        fake_file = MagicMock()
        fake_file.read.return_value = repo_addon_xml.decode("utf-8")
        xbmcvfs_m.File.return_value = fake_file

        with patch.dict("sys.modules", {
            "xbmcaddon": xbmcaddon_m, "xbmcvfs": xbmcvfs_m,
        }), patch("resources.lib.addons._fetch_bytes", return_value=addons_xml_data):
            url, version = be._resolve_package_url("plugin.video.test")
        self.assertIn("plugin.video.test", url)

    def test_no_repos_raises(self):
        be = KodiRuntimeAddonBackend()
        xbmc_mock = MagicMock()
        xbmc_mock.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "result": {"addons": []},
        })
        be._xbmc = lambda: xbmc_mock
        xbmcaddon_m = MagicMock()
        xbmcvfs_m = MagicMock()
        with patch.dict("sys.modules", {
            "xbmcaddon": xbmcaddon_m, "xbmcvfs": xbmcvfs_m,
        }):
            with self.assertRaises(AddonInstallError):
                be._resolve_package_url("plugin.video.test")


# ---------------------------------------------------------------------------
# TestSafeRedirectHandler — redirect security
# ---------------------------------------------------------------------------

class TestSafeRedirectHandler(unittest.TestCase):
    """_SafeRedirectHandler rejects disallowed schemes and credentials on redirect."""

    def _handler(self):
        return _SafeRedirectHandler()

    def _fake_req(self, url):
        return urllib.request.Request(url)

    def test_http_redirect_accepted(self):
        h = self._handler()
        req = self._fake_req("http://example.com/")
        result = h.redirect_request(req, None, 302, "Found", {}, "http://example.com/other")
        self.assertIsNotNone(result)

    def test_https_redirect_accepted(self):
        h = self._handler()
        req = self._fake_req("http://example.com/")
        result = h.redirect_request(req, None, 302, "Found", {}, "https://example.com/other")
        self.assertIsNotNone(result)

    def test_file_redirect_rejected(self):
        h = self._handler()
        req = self._fake_req("http://example.com/")
        with self.assertRaises(AddonInstallError):
            h.redirect_request(req, None, 302, "Found", {}, "file:///etc/passwd")

    def test_ftp_redirect_rejected(self):
        h = self._handler()
        req = self._fake_req("http://example.com/")
        with self.assertRaises(AddonInstallError):
            h.redirect_request(req, None, 302, "Found", {}, "ftp://example.com/file")

    def test_credentials_in_redirect_rejected(self):
        h = self._handler()
        req = self._fake_req("http://example.com/")
        with self.assertRaises(AddonInstallError):
            h.redirect_request(req, None, 302, "Found", {}, "http://user:pass@example.com/")

    def test_malformed_scheme_rejected(self):
        h = self._handler()
        req = self._fake_req("http://example.com/")
        with self.assertRaises(AddonInstallError):
            h.redirect_request(req, None, 302, "Found", {}, "javascript:alert(1)")


# ---------------------------------------------------------------------------
# TestDesiredStateValidation — invalid desired_state rejected before any backend call
# ---------------------------------------------------------------------------

class TestDesiredStateValidation(unittest.TestCase):
    """install() with invalid desired_state returns FAILED before touching any backend."""

    def test_custom_rejected(self):
        be = FakeAddonBackend()
        result = AddonManager(be).install("a.b", desired_state="custom")
        self.assertEqual(result.status, AddonStatus.FAILED)

    def test_arbitrary_string_rejected(self):
        be = FakeAddonBackend()
        result = AddonManager(be).install("a.b", desired_state="ENABLED")
        self.assertEqual(result.status, AddonStatus.FAILED)

    def test_no_invoke_on_invalid_state(self):
        be = FakeAddonBackend()
        AddonManager(be).install("a.b", desired_state="custom")
        self.assertEqual(be.invoke_calls, [])

    def test_no_details_on_invalid_state(self):
        be = FakeAddonBackend()
        AddonManager(be).install("a.b", desired_state="custom")
        self.assertEqual(be.details_calls, [])

    def test_enabled_accepted(self):
        be = FakeAddonBackend(poll_result=_make_info())
        result = AddonManager(be).install("a.b", desired_state="enabled")
        self.assertNotEqual(result.status, AddonStatus.FAILED)

    def test_disabled_accepted(self):
        be = FakeAddonBackend(poll_result=_make_info())
        result = AddonManager(be).install("a.b", desired_state="disabled")
        self.assertNotEqual(result.status, AddonStatus.FAILED)

    def test_invalid_state_preserved_in_result(self):
        be = FakeAddonBackend()
        result = AddonManager(be).install("a.b", desired_state="custom")
        self.assertEqual(result.desired_state, "custom")


# ---------------------------------------------------------------------------
# TestStateFinalizationSymmetry — 8 symmetric finalization cases
# ---------------------------------------------------------------------------

class TestStateFinalizationSymmetry(unittest.TestCase):
    """Symmetric desired_state finalization: set_addon_enabled called only when state differs."""

    def _install(self, desired_state, poll_enabled, set_enabled_error=None):
        poll_info = _make_info("plugin.video.test", enabled=poll_enabled)
        be = FakeAddonBackend(
            poll_result=poll_info,
            set_enabled_error=set_enabled_error,
        )
        result = AddonManager(be).install("plugin.video.test", desired_state=desired_state)
        return result, be

    def test_desired_enabled_poll_disabled_calls_set_enabled_true(self):
        _, be = self._install("enabled", poll_enabled=False)
        self.assertEqual(be.set_enabled_calls, [("plugin.video.test", True)])

    def test_desired_enabled_poll_enabled_no_set_call(self):
        _, be = self._install("enabled", poll_enabled=True)
        self.assertEqual(be.set_enabled_calls, [])

    def test_desired_disabled_poll_disabled_no_set_call(self):
        _, be = self._install("disabled", poll_enabled=False)
        self.assertEqual(be.set_enabled_calls, [])

    def test_desired_disabled_poll_enabled_calls_set_enabled_false(self):
        _, be = self._install("disabled", poll_enabled=True)
        self.assertEqual(be.set_enabled_calls, [("plugin.video.test", False)])

    def test_state_change_failure_returns_failed(self):
        result, _ = self._install(
            "enabled", poll_enabled=False,
            set_enabled_error=AddonInstallError("rejected"),
        )
        self.assertEqual(result.status, AddonStatus.FAILED)

    def test_state_change_failure_enabled_is_none(self):
        result, _ = self._install(
            "enabled", poll_enabled=False,
            set_enabled_error=AddonInstallError("rejected"),
        )
        self.assertIsNone(result.enabled)

    def test_invalid_desired_state_returns_failed_no_mutation(self):
        be = FakeAddonBackend(poll_result=_make_info())
        result = AddonManager(be).install("plugin.video.test", desired_state="custom")
        self.assertEqual(result.status, AddonStatus.FAILED)
        self.assertEqual(be.invoke_calls, [])

    def test_valid_states_accepted(self):
        for state in ("enabled", "disabled"):
            be = FakeAddonBackend(poll_result=_make_info("plugin.video.test"))
            result = AddonManager(be).install("plugin.video.test", desired_state=state)
            self.assertIn(result.status, (AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED))


if __name__ == "__main__":
    unittest.main()
