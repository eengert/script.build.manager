"""Safe, injectable Kodi skin activation (BM-018A).

The business logic is deliberately independent of Kodi.  The production
backend lazy-imports ``xbmc`` and uses Kodi's builtins for activation and the
project-proven ``SendClick(11)`` confirmation.  Activation is never reported
successful until the active skin is read back and matches the request.
"""

from __future__ import annotations

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

    def activate_skin(self, addon_id: str) -> None:
        raise NotImplementedError

    def confirm_skin_change(self) -> None:
        raise NotImplementedError


def _validate_addon_id(addon_id: str) -> None:
    # Keep skin input policy aligned with BM-011.  The import is local so this
    # module remains lightweight and the validation contract stays skin-specific.
    from resources.lib.addons import (  # noqa: PLC0415
        AddonValidationError,
        _validate_addon_id as validate_addon_id,
    )
    try:
        validate_addon_id(addon_id, context="skin addon_id")
    except AddonValidationError as exc:
        raise SkinValidationError(str(exc)) from exc


class SkinActivator:
    """Activate a skin with verification and bounded retry polling."""

    def __init__(
        self,
        backend: SkinBackend,
        *,
        timeout: float = 10.0,
        interval: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout < 0 or interval < 0:
            raise ValueError("timeout and interval must be non-negative")
        self._backend = backend
        self._timeout = timeout
        self._interval = interval
        self._sleep = sleep

    def activate(self, addon_id: str) -> SkinResult:
        """Make ``addon_id`` active, or return a deterministic failure result."""
        _validate_addon_id(addon_id)
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

            self._backend.activate_skin(addon_id)
            self._backend.confirm_skin_change()
            final = self._poll_active(addon_id)
            if final == addon_id:
                return SkinResult(
                    addon_id, SkinStatus.ACTIVATED, final,
                    "Skin activated and verified",
                )
            return self._failed(
                addon_id, final,
                f"Skin did not remain active before timeout (active={final!r})",
            )
        except Exception as exc:
            return self._failed(addon_id, None, f"Skin activation failed: {exc}")

    def _poll_active(self, addon_id: str) -> Optional[str]:
        deadline = time.monotonic() + self._timeout
        while True:
            active = self._backend.get_active_skin()
            if active == addon_id or time.monotonic() >= deadline:
                return active
            self._sleep(self._interval)

    @staticmethod
    def _failed(addon_id: str, active: Optional[str], message: str) -> SkinResult:
        return SkinResult(addon_id, SkinStatus.FAILED, active, message)


class KodiRuntimeSkinBackend(SkinBackend):
    """Kodi implementation; importing this class is safe outside Kodi."""

    def _xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise SkinError(f"Kodi runtime module (xbmc) is not available: {exc}") from exc

    def get_active_skin(self) -> str:
        active = self._xbmc().getSkinDir()
        if not isinstance(active, str):
            raise SkinError(f"Kodi returned malformed active skin: {active!r}")
        return active

    def get_skin_state(self, addon_id: str) -> SkinState:
        import json  # noqa: PLC0415

        xbmc = self._xbmc()
        request = json.dumps({
            "jsonrpc": "2.0", "method": "Addons.GetAddonDetails",
            "params": {"addonid": addon_id, "properties": ["enabled"]}, "id": 1,
        })
        response = json.loads(xbmc.executeJSONRPC(request))
        addon = response.get("result", {}).get("addon")
        if addon is None:
            return SkinState(installed=False, enabled=False)
        enabled = addon.get("enabled")
        if not isinstance(enabled, bool):
            raise SkinError(f"Kodi returned malformed enabled state: {enabled!r}")
        return SkinState(installed=True, enabled=enabled)

    def activate_skin(self, addon_id: str) -> None:
        self._xbmc().executebuiltin(f"Skin.SetSkin({addon_id})")

    def confirm_skin_change(self) -> None:
        self._xbmc().executebuiltin("SendClick(11)")
