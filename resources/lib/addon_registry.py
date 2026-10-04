"""Fail-closed Kodi add-on registry readiness for held configuration owners.

Kodi's ``UpdateLocalAddons`` builtin discovers add-ons already present on disk
and registers them disabled. The builtin may complete asynchronously, so
callers verify readiness through Kodi's supported add-on state API with a
bounded poll. This module never installs or enables an add-on.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol, Sequence

from resources.lib.addon_state import AddonStateInfo, KodiRuntimeAddonStateBackend
from resources.lib.activation import current_activation_holds


_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_POLL_INTERVAL = 0.5


class AddonRegistryReadinessCode(str, Enum):
    NO_ADDONS_REQUIRED = "no_addons_required"
    ALREADY_REGISTERED = "already_registered"
    REGISTERED_AFTER_REFRESH = "registered_after_refresh"
    NOT_REGISTERED_AFTER_REFRESH = "not_registered_after_refresh"
    WRONG_ADDON_ID = "wrong_addon_id"
    WRONG_VERSION = "wrong_version"
    UNEXPECTEDLY_ENABLED = "unexpectedly_enabled"
    ACTIVATION_HOLD_MISSING = "activation_hold_missing"
    ACTIVATION_HOLD_UNAVAILABLE = "activation_hold_unavailable"
    REGISTRY_QUERY_FAILED = "registry_query_failed"
    REFRESH_FAILED = "refresh_failed"
    INVALID_EXPECTATION = "invalid_expectation"


@dataclass(frozen=True)
class StagedAddonExpectation:
    """Exact registered state required before configuring one held add-on."""

    addon_id: str
    expected_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.addon_id, str) or not _ADDON_ID.fullmatch(self.addon_id):
            raise ValueError("staged add-on ID is invalid")
        if (
            not isinstance(self.expected_version, str)
            or not self.expected_version
            or len(self.expected_version) > 128
            or any(ord(char) < 0x20 for char in self.expected_version)
        ):
            raise ValueError("staged add-on version is invalid")


@dataclass(frozen=True)
class AddonRegistryItemReadiness:
    addon_id: str
    expected_version: str
    code: AddonRegistryReadinessCode
    registered_version: str = ""
    enabled: Optional[bool] = None
    poll_count: int = 0

    @property
    def ready(self) -> bool:
        return self.code in {
            AddonRegistryReadinessCode.ALREADY_REGISTERED,
            AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH,
        }

    def to_dict(self) -> dict:
        return {
            "addon_id": self.addon_id,
            "expected_version": self.expected_version,
            "code": self.code.value,
            "registered_version": self.registered_version,
            "enabled": self.enabled,
            "poll_count": self.poll_count,
        }


@dataclass(frozen=True)
class AddonRegistryReadinessResult:
    code: AddonRegistryReadinessCode
    items: tuple[AddonRegistryItemReadiness, ...] = ()
    refresh_attempted: bool = False
    poll_count: int = 0
    message: str = ""

    @property
    def ready(self) -> bool:
        return self.code in {
            AddonRegistryReadinessCode.NO_ADDONS_REQUIRED,
            AddonRegistryReadinessCode.ALREADY_REGISTERED,
            AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH,
        }

    def to_dict(self) -> dict:
        return {
            "code": self.code.value,
            "items": [item.to_dict() for item in self.items],
            "refresh_attempted": self.refresh_attempted,
            "poll_count": self.poll_count,
            "message": self.message,
        }


class AddonRegistryBackend(Protocol):
    """Supported Kodi API operations needed for local registry readiness."""

    def get_addon_details(self, addon_id: str) -> Optional[AddonStateInfo]: ...

    def refresh_local_addons(self) -> None: ...


class KodiRuntimeAddonRegistryBackend:
    """Use Kodi JSON-RPC and the non-enabling local add-on refresh builtin."""

    def __init__(self, state_backend=None) -> None:
        self._state_backend = state_backend or KodiRuntimeAddonStateBackend()

    def get_addon_details(self, addon_id: str) -> Optional[AddonStateInfo]:
        return self._state_backend.get_addon_details(addon_id)

    def refresh_local_addons(self) -> None:
        try:
            import xbmc  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("Kodi runtime is unavailable") from exc
        xbmc.executebuiltin("UpdateLocalAddons")


def _log_registry_state(stage: str, addon_id: str, state, readiness: str = "") -> None:
    """Emit a value-free registry checkpoint for disposable lifecycle audits."""
    if state is None:
        details = "state=missing version=unknown enabled=unknown"
    else:
        version = getattr(state, "version", "")
        if not isinstance(version, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}", version
        ):
            version = "unknown"
        enabled = getattr(state, "enabled", None)
        enabled_text = str(enabled).lower() if isinstance(enabled, bool) else "unknown"
        details = f"state=registered version={version} enabled={enabled_text}"
    suffix = f" readiness={readiness}" if readiness else ""
    try:
        import xbmc  # noqa: PLC0415
        xbmc.log(
            f"Build Manager held add-on registry stage={stage}: addon_id={addon_id} "
            f"{details}{suffix}",
            xbmc.LOGINFO,
        )
    except (ImportError, AttributeError, RuntimeError):
        pass


def _result(
    code: AddonRegistryReadinessCode,
    items: Sequence[AddonRegistryItemReadiness],
    *,
    refresh_attempted: bool,
    poll_count: int,
) -> AddonRegistryReadinessResult:
    messages = {
        AddonRegistryReadinessCode.NO_ADDONS_REQUIRED: "no held add-ons require configuration readiness",
        AddonRegistryReadinessCode.ALREADY_REGISTERED: "held add-ons are registered at the expected disabled versions",
        AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH: "held add-ons registered at the expected disabled versions after local refresh",
        AddonRegistryReadinessCode.NOT_REGISTERED_AFTER_REFRESH: "a held add-on remained absent after bounded local refresh polling",
        AddonRegistryReadinessCode.WRONG_ADDON_ID: "Kodi returned a different add-on ID during readiness verification",
        AddonRegistryReadinessCode.WRONG_VERSION: "a held add-on is registered at an unexpected version",
        AddonRegistryReadinessCode.UNEXPECTEDLY_ENABLED: "a held add-on became enabled during registry readiness",
        AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING: "an activation hold was not active during registry readiness",
        AddonRegistryReadinessCode.ACTIVATION_HOLD_UNAVAILABLE: "activation hold state could not be verified",
        AddonRegistryReadinessCode.REGISTRY_QUERY_FAILED: "Kodi add-on registry state could not be queried",
        AddonRegistryReadinessCode.REFRESH_FAILED: "Kodi local add-on refresh could not be requested",
        AddonRegistryReadinessCode.INVALID_EXPECTATION: "held add-on readiness expectations are invalid",
    }
    return AddonRegistryReadinessResult(
        code,
        tuple(items),
        refresh_attempted=refresh_attempted,
        poll_count=poll_count,
        message=messages[code],
    )


def ensure_staged_addons_registered_for_configuration(
    expectations: Sequence[StagedAddonExpectation],
    *,
    backend: Optional[AddonRegistryBackend] = None,
    activation_hold_provider: Optional[Callable[[], object]] = None,
    timeout: float = _DEFAULT_TIMEOUT,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> AddonRegistryReadinessResult:
    """Ensure every held add-on is registered at its exact disabled version.

    The local refresh builtin is invoked once at most for the whole batch.
    Missing add-ons are polled via the supported state API until all are ready
    or the strict monotonic deadline expires. No install, enable, or database
    operation is exposed by the backend.
    """
    try:
        supplied = tuple(expectations)
        if (
            any(not isinstance(item, StagedAddonExpectation) for item in supplied)
            or len({item.addon_id for item in supplied}) != len(supplied)
            or not math.isfinite(float(timeout))
            or float(timeout) <= 0
            or not math.isfinite(float(poll_interval))
            or float(poll_interval) <= 0
        ):
            raise ValueError("invalid staged add-on readiness request")
        requested = tuple(sorted(supplied, key=lambda item: item.addon_id))
    except (TypeError, ValueError, OverflowError):
        return _result(
            AddonRegistryReadinessCode.INVALID_EXPECTATION,
            (), refresh_attempted=False, poll_count=0,
        )

    if not requested:
        return _result(
            AddonRegistryReadinessCode.NO_ADDONS_REQUIRED,
            (), refresh_attempted=False, poll_count=0,
        )
    target = backend or KodiRuntimeAddonRegistryBackend()
    items: dict[str, AddonRegistryItemReadiness] = {}

    def fail(code: AddonRegistryReadinessCode, *, refreshed: bool, polls: int):
        return _result(code, tuple(items[key] for key in sorted(items)),
                       refresh_attempted=refreshed, poll_count=polls)

    def verify_holds() -> bool:
        try:
            holds = current_activation_holds(activation_hold_provider)
        except Exception:
            raise RuntimeError("activation hold state is unavailable")
        return all(item.addon_id in holds for item in requested)

    try:
        if not verify_holds():
            return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING,
                        refreshed=False, polls=0)
    except RuntimeError:
        return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_UNAVAILABLE,
                    refreshed=False, polls=0)

    missing = []
    try:
        for item in requested:
            state = target.get_addon_details(item.addon_id)
            _log_registry_state("before_refresh", item.addon_id, state)
            if state is None:
                missing.append(item)
                continue
            if getattr(state, "addon_id", None) != item.addon_id:
                items[item.addon_id] = AddonRegistryItemReadiness(
                    item.addon_id, item.expected_version,
                    AddonRegistryReadinessCode.WRONG_ADDON_ID,
                    str(getattr(state, "version", "")),
                    getattr(state, "enabled", None),
                )
                return fail(AddonRegistryReadinessCode.WRONG_ADDON_ID,
                            refreshed=False, polls=0)
            version = getattr(state, "version", "")
            enabled = getattr(state, "enabled", None)
            if version != item.expected_version:
                code = AddonRegistryReadinessCode.WRONG_VERSION
            elif enabled is not False:
                code = AddonRegistryReadinessCode.UNEXPECTEDLY_ENABLED
            else:
                code = AddonRegistryReadinessCode.ALREADY_REGISTERED
            items[item.addon_id] = AddonRegistryItemReadiness(
                item.addon_id, item.expected_version, code,
                str(version) if isinstance(version, str) else "", enabled,
            )
            if code not in {
                AddonRegistryReadinessCode.ALREADY_REGISTERED,
                AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH,
            }:
                return fail(code, refreshed=False, polls=0)
    except Exception:
        return fail(AddonRegistryReadinessCode.REGISTRY_QUERY_FAILED,
                    refreshed=False, polls=0)

    if not missing:
        try:
            if not verify_holds():
                return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING,
                            refreshed=False, polls=0)
        except RuntimeError:
            return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_UNAVAILABLE,
                        refreshed=False, polls=0)
        return _result(AddonRegistryReadinessCode.ALREADY_REGISTERED,
                       tuple(items[key] for key in sorted(items)),
                       refresh_attempted=False, poll_count=0)

    try:
        if not verify_holds():
            return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING,
                        refreshed=False, polls=0)
    except RuntimeError:
        return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_UNAVAILABLE,
                    refreshed=False, polls=0)
    try:
        target.refresh_local_addons()
    except Exception:
        try:
            import xbmc  # noqa: PLC0415
            xbmc.log(
                "Build Manager held add-on registry refresh: result=failed",
                xbmc.LOGERROR,
            )
        except (ImportError, AttributeError, RuntimeError):
            pass
        return fail(AddonRegistryReadinessCode.REFRESH_FAILED,
                    refreshed=True, polls=0)
    try:
        import xbmc  # noqa: PLC0415
        xbmc.log(
            "Build Manager held add-on registry refresh: result=requested",
            xbmc.LOGINFO,
        )
    except (ImportError, AttributeError, RuntimeError):
        pass

    # Recheck the whole held set after refresh. An already-registered held
    # add-on must remain exact and disabled while Kodi discovers the missing
    # package; checking only the newly discovered entries would miss a state
    # change caused during that refresh.
    pending = {item.addon_id: item for item in requested}
    deadline = monotonic() + float(timeout)
    polls = 0
    while pending:
        try:
            if not verify_holds():
                return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING,
                            refreshed=True, polls=polls)
        except RuntimeError:
            return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_UNAVAILABLE,
                        refreshed=True, polls=polls)
        polls += 1
        try:
            for addon_id in sorted(tuple(pending)):
                expectation = pending[addon_id]
                state = target.get_addon_details(addon_id)
                if state is None:
                    continue
                if getattr(state, "addon_id", None) != addon_id:
                    items[addon_id] = AddonRegistryItemReadiness(
                        addon_id, expectation.expected_version,
                        AddonRegistryReadinessCode.WRONG_ADDON_ID,
                        str(getattr(state, "version", "")),
                        getattr(state, "enabled", None), polls,
                    )
                    return fail(AddonRegistryReadinessCode.WRONG_ADDON_ID,
                                refreshed=True, polls=polls)
                version = getattr(state, "version", "")
                enabled = getattr(state, "enabled", None)
                if version != expectation.expected_version:
                    code = AddonRegistryReadinessCode.WRONG_VERSION
                elif enabled is not False:
                    code = AddonRegistryReadinessCode.UNEXPECTEDLY_ENABLED
                else:
                    code = AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH
                items[addon_id] = AddonRegistryItemReadiness(
                    addon_id, expectation.expected_version, code,
                    str(version) if isinstance(version, str) else "", enabled, polls,
                )
                _log_registry_state(
                    "after_refresh", addon_id, state, code.value
                )
                if code is not AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH:
                    return fail(code, refreshed=True, polls=polls)
                pending.pop(addon_id)
        except Exception:
            return fail(AddonRegistryReadinessCode.REGISTRY_QUERY_FAILED,
                        refreshed=True, polls=polls)
        if not pending:
            break
        try:
            if not verify_holds():
                return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING,
                            refreshed=True, polls=polls)
        except RuntimeError:
            return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_UNAVAILABLE,
                        refreshed=True, polls=polls)
        remaining = deadline - monotonic()
        if remaining <= 0:
            for addon_id, expectation in pending.items():
                items[addon_id] = AddonRegistryItemReadiness(
                    addon_id, expectation.expected_version,
                    AddonRegistryReadinessCode.NOT_REGISTERED_AFTER_REFRESH,
                    poll_count=polls,
                )
                _log_registry_state(
                    "after_refresh", addon_id, None,
                    AddonRegistryReadinessCode.NOT_REGISTERED_AFTER_REFRESH.value,
                )
            return fail(AddonRegistryReadinessCode.NOT_REGISTERED_AFTER_REFRESH,
                        refreshed=True, polls=polls)
        sleeper(min(float(poll_interval), remaining))

    try:
        if not verify_holds():
            return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING,
                        refreshed=True, polls=polls)
    except RuntimeError:
        return fail(AddonRegistryReadinessCode.ACTIVATION_HOLD_UNAVAILABLE,
                    refreshed=True, polls=polls)
    return _result(
        AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH,
        tuple(items[key] for key in sorted(items)),
        refresh_attempted=True,
        poll_count=polls,
    )


def ensure_staged_addon_registered_for_configuration(
    addon_id: str,
    expected_version: str,
    **kwargs,
) -> AddonRegistryReadinessResult:
    """Single-add-on convenience form of the batch readiness operation."""
    try:
        expectation = StagedAddonExpectation(addon_id, expected_version)
    except (TypeError, ValueError):
        return _result(
            AddonRegistryReadinessCode.INVALID_EXPECTATION,
            (), refresh_attempted=False, poll_count=0,
        )
    return ensure_staged_addons_registered_for_configuration((expectation,), **kwargs)
