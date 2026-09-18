"""
Build Manager enable/disable state reconciliation for managed add-ons (BM-013).

Public API
----------
AddonStateReconciler(backend).reconcile(desired_states, protected_dependency_ids)
    -> AddonStateReconcileResult

    Reconciles the enabled state of explicitly managed installed add-ons to
    match desired_states. Mutates only when drift exists; idempotent.

    desired_states: Dict[str, str]  mapping addon_id → "enabled" | "disabled"
    protected_dependency_ids: FrozenSet[str]  add-ons that must not be disabled
        (because BM-012 determined they are required dependencies of enabled roots).

KodiRuntimeAddonStateBackend()
    Production backend. Uses Addons.GetAddonDetails and Addons.SetAddonEnabled
    JSON-RPC. Lazy Kodi (xbmc) import.

AddonStateBackend
    Abstract backend interface. Override all methods in a concrete subclass.

Result types
------------
AddonStateStatus
    ALREADY_CORRECT | ENABLED | DISABLED | MISSING
    | BLOCKED_REQUIRED_DEPENDENCY | BLOCKED_SYSTEM | FAILED

AddonStateInfo(addon_id, enabled, version)
    Snapshot of an installed add-on's state.

AddonStateResult(addon_id, desired_state, status, was_enabled, now_enabled, message)
    Per-add-on result from reconcile().

AddonStateReconcileResult(results, all_correct, changed, failed)
    Aggregate result from reconcile().

Errors
------
AddonStateError             -- base class
AddonStateValidationError   -- invalid addon_id or desired_state

Architecture (BM-013)
----------------------
BM-013 reconciles enabled/disabled state for the explicitly managed add-on
set — the add-ons whose addon_ids are passed to reconcile() as desired_states.
It never touches unmanaged installed add-ons.

Managed scope
-------------
Only addon_ids present in desired_states are eligible for mutation. Unmanaged
installed add-ons are never queried or modified.

Valid desired states
--------------------
Only "enabled" and "disabled" are accepted. "absent" and any other string are
rejected before any backend call; the result for that add-on is FAILED.

Dependency protection
---------------------
The caller passes protected_dependency_ids (typically derived from a
DependencyClosure of enabled managed roots from BM-012). If desired_state is
"disabled" and addon_id is in protected_dependency_ids, the result is
BLOCKED_REQUIRED_DEPENDENCY and no mutation is performed. This prevents
BM-013 from fighting BM-012: a required dependency cannot be disabled even
if the manifest requests it.

The check occurs regardless of current installed state — a protected add-on
desired as disabled always produces BLOCKED_REQUIRED_DEPENDENCY, even if it
happens to be disabled already.

System add-on protection
------------------------
Any add-on whose ID begins with "xbmc." is a Kodi-provided builtin. These
are blocked unconditionally with BLOCKED_SYSTEM. No backend call is made.

Current state
-------------
Current enabled state is read from Kodi's installed database via
get_addon_details(), not from the filesystem. A not-installed add-on yields
MISSING; no installation is attempted.

Post-mutation verification
--------------------------
After every SetAddonEnabled call, get_addon_details() is called again to
verify the state change took effect. A successful API response is not enough.
Verification failure yields FAILED.

Idempotency
-----------
If the current enabled state already matches desired, ALREADY_CORRECT is
returned and no backend call is made.

Deterministic ordering
----------------------
reconcile() processes add-ons in lexical addon_id order regardless of dict
iteration order. Results are returned in the same order.

BM-012 boundary
---------------
BM-013 reconciles state for managed add-ons; BM-012 reconciles required
dependency closure. BM-013 never installs missing add-ons.

BM-014 boundary
---------------
BM-014 handles post-operation/global validation. BM-013's per-operation
verification (verify after each SetAddonEnabled) belongs here.

Stdlib only — no new runtime dependencies.
No shell commands, no direct database edits.
"""

from __future__ import annotations

import json as _json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, Optional, Tuple


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AddonStateError(Exception):
    """Base class for all add-on state operation errors."""


class AddonStateValidationError(AddonStateError):
    """Invalid addon_id or desired_state input."""


# ---------------------------------------------------------------------------
# Addon ID validation (mirrors BM-011; same grammar, local error class)
# ---------------------------------------------------------------------------

_ADDON_ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$')


def _validate_addon_id(addon_id: str, context: str = "addon_id") -> None:
    """Validate a Kodi add-on ID.

    Accepted: ASCII letters, digits, dots, underscores, hyphens.
    First character must be a letter or digit.
    Maximum 100 characters.

    Raises AddonStateValidationError on any violation.
    """
    if not isinstance(addon_id, str) or not addon_id:
        raise AddonStateValidationError(f"{context} must be a non-empty string")
    if not _ADDON_ID_RE.match(addon_id):
        raise AddonStateValidationError(
            f"{context} {addon_id!r} is not a valid Kodi add-on ID "
            f"(must match [a-zA-Z0-9][a-zA-Z0-9._-]{{0,99}})"
        )


def _is_system_addon(addon_id: str) -> bool:
    """True if addon_id is a Kodi-provided builtin that must never be mutated."""
    return addon_id.startswith("xbmc.")


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class AddonStateStatus(str, Enum):
    """Per-add-on outcome from AddonStateReconciler.reconcile()."""
    ALREADY_CORRECT = "already_correct"
    ENABLED = "enabled"
    DISABLED = "disabled"
    MISSING = "missing"
    BLOCKED_REQUIRED_DEPENDENCY = "blocked_required_dependency"
    BLOCKED_SYSTEM = "blocked_system"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Data types (frozen)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AddonStateInfo:
    """Snapshot of an installed add-on's state from Kodi's database."""
    addon_id: str
    enabled: bool
    version: str


@dataclass(frozen=True)
class AddonStateResult:
    """Per-add-on result from reconcile().

    was_enabled: enabled state before reconcile (None if missing or failed
        before state could be read).
    now_enabled: enabled state after reconcile (None if missing, blocked, or
        failed). Equals was_enabled for ALREADY_CORRECT and BLOCKED statuses.
    """
    addon_id: str
    desired_state: str
    status: AddonStateStatus
    was_enabled: Optional[bool]
    now_enabled: Optional[bool]
    message: str


@dataclass(frozen=True)
class AddonStateReconcileResult:
    """Aggregate result of AddonStateReconciler.reconcile().

    results: all per-add-on results, in lexical addon_id order.
    all_correct: True when every result has status ALREADY_CORRECT, ENABLED,
        or DISABLED. False when any are FAILED, MISSING, or BLOCKED.
    changed: subset of results where an actual mutation occurred
        (status ENABLED or DISABLED).
    failed: subset of results where status is FAILED.
    """
    results: Tuple[AddonStateResult, ...]
    all_correct: bool
    changed: Tuple[AddonStateResult, ...]
    failed: Tuple[AddonStateResult, ...]


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class AddonStateBackend:
    """Injectable backend for Kodi runtime calls in BM-013.

    Override all methods in a concrete subclass. Defaults raise
    NotImplementedError so incomplete fakes surface missing stubs immediately.
    """

    def get_addon_details(self, addon_id: str) -> Optional[AddonStateInfo]:
        """Return installed state, or None if the add-on is not installed.

        Returns None ONLY when the add-on is genuinely absent from Kodi's
        database. Raises AddonStateError on infrastructure failure (JSON-RPC
        error, Kodi unreachable, malformed response). This distinction
        prevents infrastructure failures from being misclassified as MISSING.
        """
        raise NotImplementedError

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        """Set the enabled state of addon_id.

        Raises AddonStateError on any failure. On success the caller will
        re-query get_addon_details() to verify the state change.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# AddonStateReconciler (business logic; backend-injectable)
# ---------------------------------------------------------------------------

class AddonStateReconciler:
    """Reconcile the enabled state of explicitly managed installed add-ons.

    Only add-ons present in desired_states are eligible for mutation.
    Unmanaged installed add-ons are never queried or modified.

    Usage (real Kodi runtime):
        reconciler = AddonStateReconciler(KodiRuntimeAddonStateBackend())
        result = reconciler.reconcile(
            {"plugin.video.foo": "enabled", "plugin.video.bar": "disabled"},
            protected_dependency_ids=frozenset(required_dep_ids),
        )

    Usage (tests, no Kodi required):
        reconciler = AddonStateReconciler(FakeAddonStateBackend(...))
        result = reconciler.reconcile(...)
    """

    def __init__(self, backend: AddonStateBackend) -> None:
        self._backend = backend

    def reconcile(
        self,
        desired_states: Dict[str, str],
        protected_dependency_ids: FrozenSet[str] = frozenset(),
    ) -> AddonStateReconcileResult:
        """Reconcile enabled state for all managed add-ons in desired_states.

        Processes add-ons in lexical addon_id order. One failed item does not
        prevent reconciliation of independent items; all results are returned.

        desired_states: addon_id → "enabled" | "disabled"
        protected_dependency_ids: addon_ids that must not be disabled.
            Typically derived from DependencyClosure.satisfied + needs_enable
            of enabled managed roots (from BM-012). Optional-only deps and
            unrelated add-ons must not be passed here.
        """
        results = []
        for addon_id in sorted(desired_states):
            desired_state = desired_states[addon_id]
            result = self._reconcile_one(
                addon_id, desired_state, protected_dependency_ids
            )
            results.append(result)

        results_tuple = tuple(results)
        _success = (
            AddonStateStatus.ALREADY_CORRECT,
            AddonStateStatus.ENABLED,
            AddonStateStatus.DISABLED,
        )
        all_correct = all(r.status in _success for r in results_tuple)
        changed = tuple(
            r for r in results_tuple
            if r.status in (AddonStateStatus.ENABLED, AddonStateStatus.DISABLED)
        )
        failed = tuple(r for r in results_tuple if r.status == AddonStateStatus.FAILED)

        return AddonStateReconcileResult(
            results=results_tuple,
            all_correct=all_correct,
            changed=changed,
            failed=failed,
        )

    def _reconcile_one(
        self,
        addon_id: str,
        desired_state: str,
        protected: FrozenSet[str],
    ) -> AddonStateResult:
        """Reconcile one add-on. Returns an AddonStateResult."""
        # Validate addon_id (before any backend call)
        try:
            _validate_addon_id(addon_id)
        except AddonStateValidationError as exc:
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.FAILED,
                was_enabled=None,
                now_enabled=None,
                message=f"Invalid add-on ID: {exc}",
            )

        # Validate desired_state (before any backend call)
        if desired_state not in ("enabled", "disabled"):
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.FAILED,
                was_enabled=None,
                now_enabled=None,
                message=(
                    f"Invalid desired_state {desired_state!r}: "
                    f"must be 'enabled' or 'disabled'"
                ),
            )

        # System add-on protection: never mutate xbmc.* (before backend call)
        if _is_system_addon(addon_id):
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.BLOCKED_SYSTEM,
                was_enabled=None,
                now_enabled=None,
                message=(
                    f"{addon_id!r} is a Kodi system add-on and cannot be modified"
                ),
            )

        desired_enabled = desired_state == "enabled"

        # Dependency protection: a required dependency must not be disabled.
        # The check is independent of current state — even if already disabled,
        # a protected add-on desired as disabled is a configuration conflict
        # (BM-012 needs it enabled; manifest wants it disabled).
        if not desired_enabled and addon_id in protected:
            # Query current state for the diagnostic message; ignore errors here.
            was_enabled: Optional[bool] = None
            try:
                _info = self._backend.get_addon_details(addon_id)
                if _info is not None:
                    was_enabled = _info.enabled
            except AddonStateError:
                pass

            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.BLOCKED_REQUIRED_DEPENDENCY,
                was_enabled=was_enabled,
                now_enabled=was_enabled,
                message=(
                    f"{addon_id!r} is a required dependency and cannot be disabled; "
                    f"resolve the conflict between manifest and dependency closure"
                ),
            )

        # Get current installed state
        try:
            current = self._backend.get_addon_details(addon_id)
        except AddonStateError as exc:
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.FAILED,
                was_enabled=None,
                now_enabled=None,
                message=f"State query failed for {addon_id!r}: {exc}",
            )

        if current is None:
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.MISSING,
                was_enabled=None,
                now_enabled=None,
                message=f"{addon_id!r} is not installed",
            )

        was_enabled = current.enabled

        # Idempotency: already in the desired state — no mutation
        if current.enabled == desired_enabled:
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.ALREADY_CORRECT,
                was_enabled=was_enabled,
                now_enabled=was_enabled,
                message=(
                    f"{addon_id!r} already "
                    f"{'enabled' if desired_enabled else 'disabled'}"
                ),
            )

        # Apply state change
        try:
            self._backend.set_addon_enabled(addon_id, desired_enabled)
        except AddonStateError as exc:
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.FAILED,
                was_enabled=was_enabled,
                now_enabled=None,
                message=(
                    f"SetAddonEnabled({addon_id!r}, {desired_enabled}) failed: {exc}"
                ),
            )

        # Verify state change took effect
        try:
            after = self._backend.get_addon_details(addon_id)
        except AddonStateError as exc:
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.FAILED,
                was_enabled=was_enabled,
                now_enabled=None,
                message=f"Verification query failed for {addon_id!r}: {exc}",
            )

        if after is None:
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.FAILED,
                was_enabled=was_enabled,
                now_enabled=None,
                message=(
                    f"Verification failed: {addon_id!r} not found in Kodi "
                    f"database after SetAddonEnabled"
                ),
            )

        if after.enabled != desired_enabled:
            return AddonStateResult(
                addon_id=addon_id,
                desired_state=desired_state,
                status=AddonStateStatus.FAILED,
                was_enabled=was_enabled,
                now_enabled=after.enabled,
                message=(
                    f"Verification mismatch for {addon_id!r}: "
                    f"expected enabled={desired_enabled}, "
                    f"got enabled={after.enabled}"
                ),
            )

        success_status = (
            AddonStateStatus.ENABLED if desired_enabled else AddonStateStatus.DISABLED
        )
        return AddonStateResult(
            addon_id=addon_id,
            desired_state=desired_state,
            status=success_status,
            was_enabled=was_enabled,
            now_enabled=desired_enabled,
            message=(
                f"{addon_id!r} "
                f"{'enabled' if desired_enabled else 'disabled'} successfully"
            ),
        )


# ---------------------------------------------------------------------------
# Production backend — Kodi runtime (xbmc)
# ---------------------------------------------------------------------------

class KodiRuntimeAddonStateBackend(AddonStateBackend):
    """Production backend. Uses Kodi's JSON-RPC API.

    All Kodi modules (xbmc) are imported lazily inside each method so this
    class is instantiable outside Kodi. Calling methods without Kodi loaded
    raises AddonStateError.
    """

    def _xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise AddonStateError(
                f"Kodi runtime module (xbmc) is not available: {exc}"
            ) from exc

    def get_addon_details(self, addon_id: str) -> Optional[AddonStateInfo]:
        """Query Addons.GetAddonDetails via JSON-RPC.

        Returns None ONLY when Kodi reports JSON-RPC error code -32602
        (Invalid params — the Kodi 21 response for a not-installed add-on).
        All other error codes raise AddonStateError.
        """
        xbmc = self._xbmc()
        req = _json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.GetAddonDetails",
            "params": {"addonid": addon_id, "properties": ["enabled", "version"]},
            "id": 1,
        })
        try:
            raw = xbmc.executeJSONRPC(req)
            resp = _json.loads(raw)
        except Exception as exc:
            raise AddonStateError(
                f"Addons.GetAddonDetails({addon_id!r}) infrastructure failure: {exc}"
            ) from exc

        if "error" in resp:
            error_obj = resp["error"]
            if isinstance(error_obj, dict) and error_obj.get("code") == -32602:
                return None  # Kodi 21: not installed
            raise AddonStateError(
                f"Addons.GetAddonDetails({addon_id!r}) JSON-RPC error: "
                f"{error_obj!r}"
            )

        result_val = resp.get("result")
        if not isinstance(result_val, dict):
            raise AddonStateError(
                f"Addons.GetAddonDetails({addon_id!r}) malformed response: "
                f"{resp!r}"
            )

        addon = result_val.get("addon")
        if addon is None:
            return None  # not present in result
        if not isinstance(addon, dict):
            raise AddonStateError(
                f"Addons.GetAddonDetails({addon_id!r}) addon field not a dict: "
                f"{addon!r}"
            )
        if addon.get("addonid") != addon_id:
            raise AddonStateError(
                f"Addons.GetAddonDetails({addon_id!r}) returned wrong id: "
                f"{addon.get('addonid')!r}"
            )

        enabled = addon.get("enabled")
        version = addon.get("version", "")
        return AddonStateInfo(
            addon_id=addon_id,
            enabled=bool(enabled) if isinstance(enabled, bool) else False,
            version=str(version) if version else "",
        )

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        """Set enabled state via Addons.SetAddonEnabled JSON-RPC."""
        xbmc = self._xbmc()
        req = _json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.SetAddonEnabled",
            "params": {"addonid": addon_id, "enabled": enabled},
            "id": 1,
        })
        try:
            resp = _json.loads(xbmc.executeJSONRPC(req))
        except Exception as exc:
            raise AddonStateError(
                f"Addons.SetAddonEnabled({addon_id!r}, {enabled}) failed: {exc}"
            ) from exc
        if "error" in resp:
            raise AddonStateError(
                f"Addons.SetAddonEnabled({addon_id!r}, {enabled}) "
                f"JSON-RPC error: {resp['error']!r}"
            )
