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
            self._backend.set_skin_setting(addon_id)
            if not self._wait_for_visibility(True):
                return self._failed(
                    addon_id, self._safe_active_skin(),
                    "Skin confirmation dialog did not appear before timeout",
                )

            self._backend.confirm_skin_change()
            if not self._wait_for_visibility(False):
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

    def set_skin_setting(self, addon_id: str) -> None:
        response = self._rpc(
            "Settings.SetSettingValue",
            {"setting": self._SETTING, "value": addon_id},
        )
        if response["result"] != "OK":
            raise SkinError(
                "Settings.SetSettingValue returned malformed result: "
                f"{response['result']!r}"
            )

    def is_confirmation_visible(self) -> bool:
        visible = self._xbmc().getCondVisibility("Window.IsActive(yesnodialog)")
        if not isinstance(visible, (bool, int)):
            raise SkinError(f"Kodi returned malformed dialog visibility: {visible!r}")
        return bool(visible)

    def confirm_skin_change(self) -> None:
        self._xbmc().executebuiltin("SendClick(11)")
