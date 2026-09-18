"""
Build Manager general add-on detection and installation (BM-011).

Public API
----------
AddonManager(backend).is_installed(addon_id) -> bool
    True if addon_id is installed in Kodi's database (enabled or disabled).
    Used as the idempotency guard: if True, install() returns ALREADY_INSTALLED.

AddonManager(backend).install(addon_id, desired_state="enabled") -> AddonInstallResult
    Install addon_id from configured Kodi repositories via the InstallAddon builtin.
    Returns ALREADY_INSTALLED if already present (no mutation).
    Returns INSTALLED on success (Kodi retrieved, verified, and registered the add-on).
    Returns FAILED with message on any error.
    The desired_state is preserved in the result; enable/disable reconciliation
    is deferred to BM-013 (not performed here).

KodiRuntimeAddonBackend()
    Backend for production use inside the Kodi Python runtime.
    Lazy-imports xbmc so the class is instantiable outside Kodi.
    Calling methods without Kodi loaded raises AddonInstallError.

AddonBackend
    Abstract backend interface. Subclass and override all methods to build
    a test fake. All abstract methods raise NotImplementedError by default.

Result types
------------
AddonStatus           -- ALREADY_INSTALLED | INSTALLED | FAILED
InstalledAddonInfo(addon_id, enabled, version)
AddonInstallResult(addon_id, status, desired_state, enabled, version, message)

Errors
------
AddonError             -- base class
AddonValidationError   -- invalid addon_id or input parameter
AddonInstallError      -- installation invocation or verification failure

Installation mechanism (BM-011)
--------------------------------
Normal Kodi add-on installation uses:

  xbmc.executebuiltin("InstallAddon(<addon_id>)")

This is the same code path the Kodi GUI uses. Kodi owns the download,
extraction, signature verification, dependency resolution, and database
registration. Build Manager does NOT download or extract the ZIP directly.

  * BM-010 bootstrap fallback (repository add-ons only): temp dir extraction
    + UpdateLocalAddons + SetAddonEnabled. Used because Kodi 21 exposes no
    non-interactive repository-bootstrap API.
  * BM-011 (this module): InstallAddon builtin → Kodi does everything.

The InstallAddon call is asynchronous; this module polls Addons.GetAddonDetails
until the add-on appears in Kodi's database, or until a timeout expires.

Security
--------
addon_id is strictly validated before any operation:
  - Must match [a-zA-Z0-9][a-zA-Z0-9._-]{0,99}
  - No parentheses, quotes, commas, semicolons, whitespace, or control chars
  - This prevents builtin injection via executebuiltin("InstallAddon(...)")
  - Validation runs before get_addon_details, invoke_install, and poll

Dependency traversal
--------------------
Kodi may install repository-declared dependencies automatically.
BM-011 records the installed add-on's final state but does NOT traverse
or verify dependencies. Dependency closure is BM-012 (out of scope here).

Enable/disable reconciliation
------------------------------
BM-011 installs add-ons but does not perform enable/disable reconciliation.
The desired_state is preserved in AddonInstallResult for the executor's
reference. BM-013 handles enable/disable transitions.

Stdlib only — no new runtime dependencies.
No shell commands, no direct ZIP downloads, no database edits.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AddonError(Exception):
    """Base class for all add-on operation errors."""


class AddonValidationError(AddonError):
    """Invalid add-on ID or input parameter."""


class AddonInstallError(AddonError):
    """Installation invocation or verification failure."""


# ---------------------------------------------------------------------------
# Addon ID validation
# ---------------------------------------------------------------------------

_ADDON_ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$')


def _validate_addon_id(addon_id: str, context: str = "addon_id") -> None:
    """Validate a Kodi add-on ID against a strict allowlist grammar.

    Accepted characters: ASCII letters, digits, dots, underscores, hyphens.
    First character must be a letter or digit (not dot, underscore, or hyphen).
    Maximum length: 100 characters.

    Rejected: parentheses, quotes, commas, semicolons, whitespace, control
    characters, empty string, or any character outside the allowlist.

    Raises AddonValidationError on any violation. This protects against
    builtin injection via executebuiltin("InstallAddon(...)").
    """
    if not isinstance(addon_id, str) or not addon_id:
        raise AddonValidationError(f"{context} must be a non-empty string")
    if not _ADDON_ID_RE.match(addon_id):
        raise AddonValidationError(
            f"{context} {addon_id!r} is not a valid Kodi add-on ID "
            f"(must match [a-zA-Z0-9][a-zA-Z0-9._-]{{0,99}})"
        )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class AddonStatus(str, Enum):
    """Outcome of an AddonManager.install() call."""
    ALREADY_INSTALLED = "already_installed"
    INSTALLED = "installed"
    FAILED = "failed"


@dataclass(frozen=True)
class InstalledAddonInfo:
    """Snapshot of an installed add-on's state from Kodi's database."""
    addon_id: str
    enabled: bool
    version: str


@dataclass(frozen=True)
class AddonInstallResult:
    """Immutable result of an AddonManager.install() call.

    Fields
    ------
    addon_id      -- the add-on that was requested
    status        -- ALREADY_INSTALLED | INSTALLED | FAILED
    desired_state -- the desired_state argument passed to install()
    enabled       -- observed enabled state from Kodi's database (None on FAILED)
    version       -- observed version string from Kodi's database (None on FAILED)
    message       -- human-readable description of the outcome
    """
    addon_id: str
    status: AddonStatus
    desired_state: str
    enabled: Optional[bool]
    version: Optional[str]
    message: str


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INSTALL_TIMEOUT: float = 120.0   # seconds to poll for install completion
_INSTALL_INTERVAL: float = 2.0    # seconds between poll attempts


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class AddonBackend:
    """Injectable backend for Kodi runtime calls.

    Override all methods in a concrete subclass. Defaults raise
    NotImplementedError so incomplete fakes surface missing stubs immediately.
    """

    def get_addon_details(self, addon_id: str) -> Optional[InstalledAddonInfo]:
        """Return installed state, or None if the add-on is not installed.

        Must return None (not raise) when the add-on is absent from Kodi's
        database. May raise AddonInstallError on genuine infrastructure failures
        (e.g. Kodi not responding, malformed JSON-RPC response).
        """
        raise NotImplementedError

    def invoke_install(self, addon_id: str) -> None:
        """Trigger Kodi to install addon_id from configured repositories.

        This call is expected to be asynchronous: it starts the install
        job and returns before completion. The caller polls poll_addon_installed()
        to determine when installation finishes.

        addon_id has already been validated by _validate_addon_id before this
        method is called.

        Raises AddonInstallError on hard failure (e.g. builtin unavailable,
        Kodi not running).
        """
        raise NotImplementedError

    def poll_addon_installed(
        self,
        addon_id: str,
        *,
        timeout: float = _INSTALL_TIMEOUT,
        interval: float = _INSTALL_INTERVAL,
    ) -> Optional[InstalledAddonInfo]:
        """Poll until addon_id appears in Kodi's database, or timeout expires.

        Returns InstalledAddonInfo when the add-on is detected as installed.
        Returns None on timeout (add-on did not appear within timeout seconds).
        Raises AddonInstallError on hard infrastructure failure.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# AddonManager (business logic; backend-injectable)
# ---------------------------------------------------------------------------

class AddonManager:
    """General add-on detection and installation. Requires an injectable backend.

    Uses Kodi's repository-backed installation (InstallAddon builtin).
    Does NOT download or extract add-on ZIPs directly (that is BM-010's
    repository bootstrap fallback for repository-type add-ons only).

    BM-011 is the primitive. Dependency traversal is BM-012.
    Enable/disable reconciliation is BM-013.

    Usage (real Kodi runtime):
        mgr = AddonManager(KodiRuntimeAddonBackend())
        result = mgr.install("plugin.video.example")

    Usage (tests, no Kodi required):
        mgr = AddonManager(FakeAddonBackend(...))
        result = mgr.install("plugin.video.example")
    """

    def __init__(self, backend: AddonBackend) -> None:
        self._backend = backend

    def is_installed(self, addon_id: str) -> bool:
        """True if the add-on is in Kodi's installed database (enabled or disabled).

        Raises AddonValidationError for invalid addon_id.
        """
        _validate_addon_id(addon_id)
        return self._backend.get_addon_details(addon_id) is not None

    def install(
        self,
        addon_id: str,
        desired_state: str = "enabled",
    ) -> AddonInstallResult:
        """Install addon_id from configured Kodi repositories.

        Returns ALREADY_INSTALLED (no mutation) if already in Kodi's database.
        Returns INSTALLED on success: Kodi retrieved, extracted, and registered
        the add-on from a repository.
        Returns FAILED with a descriptive message on any error.

        desired_state is preserved in the result for the executor's reference.
        Enable/disable reconciliation is NOT performed here (that is BM-013).
        """
        # Validate addon_id before any operation — prevent injection
        try:
            _validate_addon_id(addon_id)
        except AddonValidationError as exc:
            return AddonInstallResult(
                addon_id=addon_id,
                status=AddonStatus.FAILED,
                desired_state=desired_state,
                enabled=None,
                version=None,
                message=f"Invalid add-on ID: {exc}",
            )

        # Idempotency guard: already in Kodi's database → no mutation
        existing = self._backend.get_addon_details(addon_id)
        if existing is not None:
            return AddonInstallResult(
                addon_id=addon_id,
                status=AddonStatus.ALREADY_INSTALLED,
                desired_state=desired_state,
                enabled=existing.enabled,
                version=existing.version,
                message=f"{addon_id!r} is already installed (enabled={existing.enabled})",
            )

        # Invoke Kodi's repository-backed install (asynchronous)
        try:
            self._backend.invoke_install(addon_id)
        except AddonInstallError as exc:
            return AddonInstallResult(
                addon_id=addon_id,
                status=AddonStatus.FAILED,
                desired_state=desired_state,
                enabled=None,
                version=None,
                message=f"Install invocation failed: {exc}",
            )

        # Poll until Kodi registers the add-on in its database
        try:
            info = self._backend.poll_addon_installed(addon_id)
        except AddonInstallError as exc:
            return AddonInstallResult(
                addon_id=addon_id,
                status=AddonStatus.FAILED,
                desired_state=desired_state,
                enabled=None,
                version=None,
                message=f"Install verification failed: {exc}",
            )

        if info is None:
            return AddonInstallResult(
                addon_id=addon_id,
                status=AddonStatus.FAILED,
                desired_state=desired_state,
                enabled=None,
                version=None,
                message=(
                    f"{addon_id!r} not detected in Kodi database after install "
                    f"(poll timeout; add-on may be unavailable in configured repositories)"
                ),
            )

        return AddonInstallResult(
            addon_id=addon_id,
            status=AddonStatus.INSTALLED,
            desired_state=desired_state,
            enabled=info.enabled,
            version=info.version,
            message=(
                f"{addon_id!r} installed by Kodi "
                f"(enabled={info.enabled}, version={info.version!r})"
            ),
        )


# ---------------------------------------------------------------------------
# Production backend — Kodi runtime (xbmc)
# ---------------------------------------------------------------------------

class KodiRuntimeAddonBackend(AddonBackend):
    """Production backend using xbmc. Lazy-imports Kodi modules.

    Kodi modules are imported inside each method so this class is
    instantiable outside Kodi. Calling methods without Kodi loaded raises
    AddonInstallError.
    """

    def _xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise AddonInstallError(
                "Kodi runtime module (xbmc) is not available"
            ) from exc

    def get_addon_details(self, addon_id: str) -> Optional[InstalledAddonInfo]:
        """Query Addons.GetAddonDetails. Returns None if not installed or on error."""
        xbmc = self._xbmc()
        req = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.GetAddonDetails",
            "params": {"addonid": addon_id, "properties": ["enabled", "version"]},
            "id": 1,
        })
        try:
            resp = json.loads(xbmc.executeJSONRPC(req))
        except (json.JSONDecodeError, Exception) as exc:
            raise AddonInstallError(
                f"Addons.GetAddonDetails({addon_id!r}) failed: {exc}"
            ) from exc
        if "error" in resp:
            return None
        result_val = resp.get("result", {})
        if not isinstance(result_val, dict):
            return None
        addon = result_val.get("addon", {})
        if not isinstance(addon, dict) or addon.get("addonid") != addon_id:
            return None
        enabled = addon.get("enabled")
        version = addon.get("version", "")
        return InstalledAddonInfo(
            addon_id=addon_id,
            enabled=bool(enabled) if isinstance(enabled, bool) else False,
            version=str(version) if version else "",
        )

    def invoke_install(self, addon_id: str) -> None:
        """Trigger Kodi to install addon_id via the InstallAddon builtin.

        addon_id must already be validated by _validate_addon_id before this
        is called (enforced by AddonManager.install). The validated addon_id
        contains only [a-zA-Z0-9._-], preventing builtin injection.
        """
        xbmc = self._xbmc()
        xbmc.executebuiltin(f"InstallAddon({addon_id})")

    def poll_addon_installed(
        self,
        addon_id: str,
        *,
        timeout: float = _INSTALL_TIMEOUT,
        interval: float = _INSTALL_INTERVAL,
    ) -> Optional[InstalledAddonInfo]:
        """Poll Addons.GetAddonDetails until addon_id appears in Kodi's database."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                info = self.get_addon_details(addon_id)
                if info is not None:
                    return info
            except AddonInstallError:
                pass
            time.sleep(interval)
        return None
