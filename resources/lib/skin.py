"""Safe, injectable Kodi skin activation (BM-018A correction pass).

Skin selection is a Kodi setting, not a builtin. The production backend uses
the Settings JSON-RPC methods and waits for Kodi's keep/revert dialog before
clicking the established ``SendClick(11)`` Yes action. Success is reported
only after both the persisted setting and loaded skin are verified.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class SkinError(Exception):
    """Base class for skin activation errors."""


class SkinValidationError(SkinError):
    """The requested skin add-on ID is malformed."""


class SkinStatus(str, Enum):
    """Outcome of one activation request."""

    ALREADY_ACTIVE = "already_active"
    ACTIVATED = "activated"
    FAILED = "failed"


@dataclass(frozen=True)
class SkinResult:
    """Explicit result returned by :class:`SkinActivator`."""

    addon_id: str
    status: SkinStatus
    active_skin: Optional[str]
    message: str


@dataclass(frozen=True)
class SkinState:
    """Observable installed/enabled state for a skin add-on."""

    installed: bool
    enabled: bool


class SkinBackend:
    """Injectable runtime interface used by :class:`SkinActivator`."""

    def get_active_skin(self) -> str:
        raise NotImplementedError

    def get_skin_state(self, addon_id: str) -> SkinState:
        raise NotImplementedError

    def get_skin_setting(self) -> str:
        raise NotImplementedError

    def set_skin_setting(self, addon_id: str) -> None:
        raise NotImplementedError

    def is_confirmation_visible(self) -> bool:
        raise NotImplementedError

    def confirm_skin_change(self) -> None:
        raise NotImplementedError


def _validate_addon_id(addon_id: str) -> None:
    # Keep skin input policy aligned with BM-011 while preserving this module's
    # public validation exception.
    from resources.lib.addons import (  # noqa: PLC0415
        AddonValidationError,
        _validate_addon_id as validate_addon_id,
    )
    try:
        validate_addon_id(addon_id, context="skin addon_id")
    except AddonValidationError as exc:
        raise SkinValidationError(str(exc)) from exc


class SkinActivator:
    """Activate a skin with bounded confirmation and final-state checks."""

    def __init__(
        self,
        backend: SkinBackend,
        *,
        timeout: float = 10.0,
        interval: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout < 0 or interval < 0:
            raise ValueError("timeout and interval must be non-negative")
        self._backend = backend
        self._timeout = timeout
        self._interval = interval
        self._sleep = sleep
        self._clock = clock

    def activate(self, addon_id: str) -> SkinResult:
        """Make ``addon_id`` active, or return a deterministic failure result."""
        _validate_addon_id(addon_id)
        active: Optional[str] = None
        try:
            active = self._backend.get_active_skin()
            if active == addon_id:
                return SkinResult(
                    addon_id, SkinStatus.ALREADY_ACTIVE, active,
                    "Skin is already active; no mutation performed",
                )

            state = self._backend.get_skin_state(addon_id)
            if not state.installed:
                return self._failed(addon_id, active, "Skin is not installed")
            if not state.enabled:
                return self._failed(addon_id, active, "Skin is installed but disabled")

            # Do not claim ownership of a dialog that predates this operation.
            # The post-mutation visibility check must observe a newly-created
            # confirmation dialog before SendClick(11) is permitted.
            if self._backend.is_confirmation_visible():
                return self._failed(
                    addon_id, active,
                    "A pre-existing Yes/No dialog prevents safe skin activation",
                )

            # The setting mutation is synchronous only as an API call; Kodi's
            # UI confirmation is asynchronous and must be observed separately.
            prepare = getattr(self._backend, "prepare_skin_change", None)
            if callable(prepare):
                prepare()
            self._backend.set_skin_setting(addon_id)
            if not self._wait_for_confirmation(addon_id):
                return self._failed(
                    addon_id, self._safe_active_skin(),
                    "Skin confirmation dialog did not appear before timeout",
                )

            self._backend.confirm_skin_change()
            if not self._wait_for_confirmation_close(addon_id):
                return self._failed(
                    addon_id, self._safe_active_skin(),
                    "Skin confirmation dialog did not close before timeout",
                )

            persisted = self._backend.get_skin_setting()
            active = self._backend.get_active_skin()
            if persisted != addon_id:
                return self._failed(
                    addon_id, active,
                    f"Persisted skin setting is {persisted!r}, expected {addon_id!r}",
                )
            if active != addon_id:
                return self._failed(
                    addon_id, active,
                    f"Loaded skin is {active!r}, expected {addon_id!r}",
                )
            if not self._wait_for_stable_skin(addon_id):
                return self._failed(
                    addon_id, self._safe_active_skin(),
                    "Skin setting or loaded skin did not remain stable after confirmation",
                )
            return SkinResult(
                addon_id, SkinStatus.ACTIVATED, active,
                "Skin activated and persisted state verified",
            )
        except Exception as exc:
            return self._failed(addon_id, active, f"Skin activation failed: {exc}")

    def _wait_for_visibility(self, expected: bool) -> bool:
        deadline = self._clock() + self._timeout
        while True:
            if self._backend.is_confirmation_visible() == expected:
                return True
            if self._clock() >= deadline:
                return False
            self._sleep(self._interval)

    def _wait_for_confirmation(self, addon_id: str) -> bool:
        """Wait until the requested skin is loaded and its dialog is visible."""
        deadline = self._clock() + self._timeout
        while True:
            try:
                if (
                    self._backend.get_active_skin() == addon_id
                    and self._backend.is_confirmation_visible()
                ):
                    return True
            except Exception:
                pass
            if self._clock() >= deadline:
                return False
            self._sleep(self._interval)

    def _wait_for_confirmation_close(self, addon_id: str) -> bool:
        """Require the dialog to stay closed while the requested skin is active."""
        deadline = self._clock() + self._timeout
        samples_required = (
            2 if self._timeout < 1.0
            else max(2, min(4, int(1.0 / max(self._interval, 0.25))))
        )
        samples = 0
        while True:
            try:
                if not self._backend.is_confirmation_visible():
                    samples += 1
                    if samples >= samples_required:
                        return True
                else:
                    samples = 0
            except Exception:
                samples = 0
            if self._clock() >= deadline:
                return False
            self._sleep(self._interval)

    def _wait_for_stable_skin(self, addon_id: str) -> bool:
        """Require several consecutive desired-state samples after confirmation."""
        deadline = self._clock() + self._timeout
        # At the default interval this covers roughly two seconds of Kodi's
        # asynchronous keep/revert lifecycle without relying on a blind sleep.
        samples_required = (
            2 if self._timeout < 1.0
            else max(2, min(8, int(2.0 / max(self._interval, 0.25))))
        )
        samples = 0
        while True:
            try:
                if (
                    self._backend.get_skin_setting() == addon_id
                    and self._backend.get_active_skin() == addon_id
                ):
                    samples += 1
                    if samples >= samples_required:
                        return True
                else:
                    samples = 0
            except Exception:
                samples = 0
            if self._clock() >= deadline:
                return False
            self._sleep(self._interval)

    def _safe_active_skin(self) -> Optional[str]:
        try:
            return self._backend.get_active_skin()
        except Exception:
            return None

    @staticmethod
    def _failed(addon_id: str, active: Optional[str], message: str) -> SkinResult:
        return SkinResult(addon_id, SkinStatus.FAILED, active, message)


class KodiRuntimeSkinBackend(SkinBackend):
    """Kodi implementation; importing this class is safe outside Kodi."""

    _SETTING = "lookandfeel.skin"
    _NOT_FOUND = -32602

    def _xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise SkinError(f"Kodi runtime module (xbmc) is not available: {exc}") from exc

    def _rpc(self, method: str, params: dict, *, allow_error: bool = False) -> dict:
        xbmc = self._xbmc()
        request = json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params, "id": 1,
        })
        try:
            response = json.loads(xbmc.executeJSONRPC(request))
        except Exception as exc:
            raise SkinError(f"{method} JSON-RPC transport/JSON failure: {exc}") from exc
        if not isinstance(response, dict):
            raise SkinError(f"{method} returned malformed response: {response!r}")
        if "error" in response and not allow_error:
            raise SkinError(f"{method} JSON-RPC error: {response['error']!r}")
        if "error" not in response and "result" not in response:
            raise SkinError(f"{method} response lacks result: {response!r}")
        return response

    def get_active_skin(self) -> str:
        active = self._xbmc().getSkinDir()
        if not isinstance(active, str):
            raise SkinError(f"Kodi returned malformed active skin: {active!r}")
        return active

    def get_skin_state(self, addon_id: str) -> SkinState:
        response = self._rpc(
            "Addons.GetAddonDetails",
            {"addonid": addon_id, "properties": ["enabled"]},
            allow_error=True,
        )
        if "error" in response:
            error = response["error"]
            # Kodi 21 represents an absent add-on as JSON-RPC Invalid params.
            # Other protocol errors remain failures and are never reclassified.
            if isinstance(error, dict) and error.get("code") == self._NOT_FOUND:
                return SkinState(installed=False, enabled=False)
            raise SkinError(f"Addons.GetAddonDetails JSON-RPC error: {error!r}")
        result = response["result"]
        if not isinstance(result, dict) or "addon" not in result:
            raise SkinError(
                f"Addons.GetAddonDetails returned malformed result: {result!r}"
            )
        addon = result["addon"]
        if addon is None:
            return SkinState(installed=False, enabled=False)
        if not isinstance(addon, dict) or addon.get("addonid") != addon_id:
            raise SkinError(
                f"Addons.GetAddonDetails returned malformed addon: {addon!r}"
            )
        enabled = addon.get("enabled")
        if not isinstance(enabled, bool):
            raise SkinError(f"Kodi returned malformed enabled state: {enabled!r}")
        return SkinState(installed=True, enabled=enabled)

    def get_skin_setting(self) -> str:
        response = self._rpc(
            "Settings.GetSettingValue", {"setting": self._SETTING}
        )
        result = response["result"]
        if not isinstance(result, dict) or not isinstance(result.get("value"), str):
            raise SkinError(
                f"Settings.GetSettingValue returned malformed result: {result!r}"
            )
        return result["value"]

    def prepare_skin_change(self) -> None:
        """Move Kodi to Home before opening its skin keep/revert dialog."""
        xbmc = self._xbmc()
        xbmc.executebuiltin("ActivateWindow(home)")
        # Kodi's builtin dispatcher is asynchronous; let the Home transition
        # enter the event queue before changing the skin setting.
        sleeper = getattr(xbmc, "sleep", None)
        if callable(sleeper):
            sleeper(500)

    def set_skin_setting(self, addon_id: str) -> None:
        response = self._rpc(
            "Settings.SetSettingValue",
            {"setting": self._SETTING, "value": addon_id},
        )
        # Kodi versions differ here: older builds return the string ``OK``;
        # current JSON-RPC returns boolean true for Settings.SetSettingValue.
        if response["result"] not in ("OK", True):
            raise SkinError(
                "Settings.SetSettingValue returned malformed result: "
                f"{response['result']!r}"
            )

    def is_confirmation_visible(self) -> bool:
        xbmc = self._xbmc()
        for condition in ("Window.IsActive(yesnodialog)", "Window.IsActive(10100)"):
            visible = xbmc.getCondVisibility(condition)
            if not isinstance(visible, (bool, int)):
                raise SkinError(
                    f"Kodi returned malformed dialog visibility: {visible!r}"
                )
            if bool(visible):
                return True
        return False

    def confirm_skin_change(self) -> None:
        xbmc = self._xbmc()
        try:
            # The wait flag makes Kodi process the click before returning;
            # older Python bindings accept only the one-argument form.
            xbmc.executebuiltin("SendClick(11)", True)
        except TypeError:
            xbmc.executebuiltin("SendClick(11)")


class KodiRuntimeSkinSettingsBackend:
    """Dedicated adapter for Kodi's currently active skin-setting map.

    Skin settings are not add-on settings. Kodi exposes their typed read/write
    surface through ``Settings.GetSkinSettingValue`` and
    ``Settings.SetSkinSettingValue`` JSON-RPC methods. The adapter checks the
    active skin before either operation so a target cannot accidentally write a
    similarly named setting belonging to another skin.
    """

    _SUPPORTED_TYPES = frozenset(("bool", "string"))

    @staticmethod
    def _setting_type_name(setting_type) -> str:
        value = getattr(setting_type, "value", setting_type)
        if value not in KodiRuntimeSkinSettingsBackend._SUPPORTED_TYPES:
            raise SkinError(
                "skin settings support only bool and string targets, "
                f"got {value!r}"
            )
        return value

    def _xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise SkinError(
                f"Kodi runtime module (xbmc) is not available: {exc}"
            ) from exc

    def _rpc(self, method: str, params: dict):
        xbmc = self._xbmc()
        request = json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params, "id": 1,
        })
        try:
            response = json.loads(xbmc.executeJSONRPC(request))
        except Exception as exc:
            raise SkinError(f"{method} JSON-RPC transport/JSON failure: {exc}") from exc
        if not isinstance(response, dict):
            raise SkinError(f"{method} returned malformed response: {response!r}")
        if "error" in response:
            raise SkinError(f"{method} JSON-RPC error: {response['error']!r}")
        if "result" not in response:
            raise SkinError(f"{method} response lacks result: {response!r}")
        return response["result"]

    def _require_active(self, addon_id: str) -> None:
        active = self._xbmc().getSkinDir()
        if not isinstance(active, str) or not active:
            raise SkinError(f"Kodi returned an unavailable active skin: {active!r}")
        if active != addon_id:
            raise SkinError(
                f"requested skin {addon_id!r} is not active; Kodi reports {active!r}"
            )

    def get_setting(self, addon_id: str, key: str, setting_type) -> object:
        kind = self._setting_type_name(setting_type)
        self._require_active(addon_id)
        result = self._rpc("Settings.GetSkinSettingValue", {"setting": key})
        if not isinstance(result, dict) or "value" not in result:
            raise SkinError(
                f"Settings.GetSkinSettingValue returned malformed result: {result!r}"
            )
        value = result["value"]
        if kind == "bool" and not isinstance(value, bool):
            raise SkinError(
                f"skin setting {addon_id}/{key} returned non-bool value"
            )
        if kind == "string" and not isinstance(value, str):
            raise SkinError(
                f"skin setting {addon_id}/{key} returned non-string value"
            )
        return value

    def set_setting(self, addon_id: str, key: str, setting_type, value: object) -> None:
        kind = self._setting_type_name(setting_type)
        if kind == "bool" and not isinstance(value, bool):
            raise SkinError("skin bool targets require a boolean value")
        if kind == "string" and not isinstance(value, str):
            raise SkinError("skin string targets require a string value")
        self._require_active(addon_id)
        result = self._rpc(
            "Settings.SetSkinSettingValue",
            {"setting": key, "value": value},
        )
        if result is not True:
            raise SkinError(
                "Settings.SetSkinSettingValue returned a non-success result: "
                f"{result!r}"
            )
