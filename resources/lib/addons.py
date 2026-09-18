"""
Build Manager general add-on detection and installation (BM-011).

Public API
----------
AddonManager(backend).is_installed(addon_id) -> bool
    True if addon_id is installed in Kodi's database (enabled or disabled).
    Used as the idempotency guard: if True, install() returns ALREADY_INSTALLED.

AddonManager(backend).install(addon_id, desired_state="enabled") -> AddonInstallResult
    Install addon_id from configured Kodi repositories via Build Manager's
    constrained package-install fallback (see Architecture below).
    Returns ALREADY_INSTALLED if already present (no mutation).
    Returns INSTALLED on success; result reflects final enabled state.
    Returns FAILED with message on any error.

KodiRuntimeAddonBackend()
    Backend for production use inside the Kodi Python runtime.
    Lazy-imports xbmc/xbmcvfs/xbmcaddon so the class is instantiable outside
    Kodi. Calling methods without Kodi loaded raises AddonInstallError.

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

Architecture (BM-011) — constrained package-install fallback
-------------------------------------------------------------
Kodi 21 does not expose an unattended, non-interactive add-on installation API.
The only GUI-level primitive, xbmc.executebuiltin("InstallAddon(id)"), always
presents a user confirmation dialog and cannot complete without a human click.

Build Manager therefore implements a constrained package-install fallback for
unattended provisioning:

  1. RESOLVE    — find addon_id in installed+enabled repository metadata
  2. DOWNLOAD   — fetch the ZIP from the repository's <datadir> URL
  3. VALIDATE   — check the ZIP: safe paths, addon.xml present, ID matches
  4. STAGE      — extract to a temporary staging directory
  5. RENAME     — atomic rename staging/{addon_id}/ → addons/{addon_id}/
  6. DISCOVER   — trigger Kodi to register the new add-on (UpdateLocalAddons)
  7. FINALIZE   — symmetric state enforcement: if discovered state ≠ desired,
                   call SetAddonEnabled(desired_enabled) via JSON-RPC
  8. VERIFY     — confirm Kodi reports the add-on with the expected state

This is NOT equivalent to Kodi's interactive InstallAddon workflow:
  - Kodi's own dependency resolver is not invoked (dependency closure is BM-012)
  - Kodi's signature verification is not applied (repository metadata is trusted)

Compared to BM-010 (repository bootstrap):
  BM-010 = install a *repository-type* add-on so Kodi can track its contents
  BM-011 = install a *normal add-on* using the repository index BM-010 set up

Repository metadata resolution
--------------------------------
Build Manager enumerates installed+enabled repository add-ons (via JSON-RPC
Addons.GetAddons), reads each repository's addon.xml to find the <info> URL,
fetches addons.xml, and searches for addon_id. The first match wins.

Package URL is constructed from the repository's <datadir zip="true"> URL
using the standard Kodi convention:
  {datadir}/{addon_id}/{version}/{addon_id}-{version}.zip

Download security
-----------------
  - Only http:// and https:// schemes; no file://, ftp://, or other
  - No embedded credentials (user:pass@host) in any URL
  - localhost permitted (for disposable test environments)
  - Size cap: _MAX_ADDON_ZIP_BYTES per addon ZIP, _MAX_ADDONS_XML_BYTES per index
  - Timeout: _FETCH_TIMEOUT seconds

ZIP validation
--------------
  - Must be a valid ZIP file
  - No absolute paths (starting with /)
  - No path traversal (..)
  - Must contain {addon_id}/addon.xml
  - addon.xml root element id attribute must exactly match requested addon_id
  - If expected_version is known, addon.xml version must match

Desired state
-------------
install(addon_id, desired_state="enabled"):
  Installs and enables the add-on. After Kodi registers it (which SyncInstalled
  records as disabled=0 by default in Kodi 21), the finalization step compares
  the discovered state to the desired state. If disabled, SetAddonEnabled(True)
  is called and the result is verified.

install(addon_id, desired_state="disabled"):
  Installs and leaves the add-on disabled. If Kodi registers the new add-on
  as disabled (the usual SyncInstalled default), no state change is made.
  If Kodi registers it as enabled, SetAddonEnabled(False) is called and
  the result is verified.

Both cases use the same symmetric finalization logic:
  if discovered_enabled != desired_enabled → SetAddonEnabled(desired_enabled)
Only "enabled" and "disabled" are accepted; any other value returns FAILED
before any backend mutation.

This is installation finalization, not general enable/disable reconciliation.
BM-013 handles drift for already-installed add-ons.

Dependency closure
------------------
BM-011 installs only the requested package. Kodi's dependency resolver is not
invoked, so required dependencies may not be installed automatically.
Dependency closure is deferred to BM-012.

Stdlib only — no new runtime dependencies.
No shell commands, no direct database edits.
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


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

    Raises AddonValidationError on any violation.
    """
    if not isinstance(addon_id, str) or not addon_id:
        raise AddonValidationError(f"{context} must be a non-empty string")
    if not _ADDON_ID_RE.match(addon_id):
        raise AddonValidationError(
            f"{context} {addon_id!r} is not a valid Kodi add-on ID "
            f"(must match [a-zA-Z0-9][a-zA-Z0-9._-]{{0,99}})"
        )


# ---------------------------------------------------------------------------
# URL security
# ---------------------------------------------------------------------------

def _validate_url(url: str, context: str = "url") -> None:
    """Raise AddonInstallError if url is not a safe http/https URL.

    Rejected: file://, ftp://, and any other non-http/https scheme.
    Rejected: embedded credentials (user:pass@host).
    Rejected: missing or empty host.
    localhost is permitted (required for disposable test environments).
    """
    if not isinstance(url, str) or not url:
        raise AddonInstallError(f"{context}: URL must be a non-empty string")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise AddonInstallError(
            f"{context}: unsupported scheme {parsed.scheme!r} — "
            f"only http and https are permitted"
        )
    if parsed.username or parsed.password:
        raise AddonInstallError(
            f"{context}: embedded credentials are not permitted in URLs"
        )
    if not parsed.netloc or not parsed.hostname:
        raise AddonInstallError(f"{context}: missing host in URL")


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

_MAX_ADDONS_XML_BYTES: int = 10 * 1024 * 1024   # 10 MB per repository index
_MAX_ADDON_ZIP_BYTES: int = 100 * 1024 * 1024    # 100 MB per addon ZIP
_FETCH_TIMEOUT: float = 30.0                       # seconds

_ALLOWED_DOWNLOAD_SCHEMES = ("http", "https")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject any redirect to a disallowed URL scheme before following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme not in _ALLOWED_DOWNLOAD_SCHEMES:
            raise AddonInstallError(
                f"Redirect to disallowed URL scheme {parsed.scheme!r} rejected"
            )
        if parsed.username or parsed.password:
            raise AddonInstallError(
                "Redirect to URL with embedded credentials rejected"
            )
        if not parsed.netloc or not parsed.hostname:
            raise AddonInstallError(
                "Redirect to URL with missing or invalid host rejected"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_safe_opener() -> urllib.request.OpenerDirector:
    """Build an OpenerDirector without FileHandler; uses _SafeRedirectHandler."""
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    # Remove FileHandler so file:// cannot be opened even on redirect
    opener.handlers = [
        h for h in opener.handlers
        if not isinstance(h, urllib.request.FileHandler)
    ]
    return opener


def _fetch_bytes(url: str, max_bytes: int, timeout: float = _FETCH_TIMEOUT) -> bytes:
    """Download url with security constraints. Raises AddonInstallError on failure.

    - url must pass _validate_url (http/https, no credentials)
    - Response body is capped at max_bytes; exceeding it raises AddonInstallError
    - Redirects are validated by _SafeRedirectHandler (scheme + credentials check)
    - Uses urllib; no third-party dependencies
    """
    _validate_url(url, context="download URL")
    opener = _build_safe_opener()
    try:
        with opener.open(url, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
    except AddonInstallError:
        raise
    except urllib.error.URLError as exc:
        raise AddonInstallError(f"Download failed {url!r}: {exc}") from exc
    except Exception as exc:
        raise AddonInstallError(f"Download failed {url!r}: {exc}") from exc

    if len(data) > max_bytes:
        raise AddonInstallError(
            f"Download of {url!r} exceeded size limit ({max_bytes} bytes)"
        )
    return data


# ---------------------------------------------------------------------------
# ZIP validation
# ---------------------------------------------------------------------------

def _validate_addon_zip(
    data: bytes,
    addon_id: str,
    expected_version: Optional[str] = None,
) -> str:
    """Validate addon ZIP content. Returns the version string found in addon.xml.

    Checks:
      - Valid ZIP format
      - No absolute paths (starts with /)
      - No path traversal (..)
      - {addon_id}/addon.xml present
      - addon.xml root id attribute matches addon_id exactly
      - addon.xml has a non-empty version attribute
      - If expected_version is provided, addon.xml version matches

    Raises AddonInstallError on any violation.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AddonInstallError(f"Invalid ZIP: {exc}") from exc

    with zf:
        names = zf.namelist()

        # Safe path check: no absolute paths, no traversal
        for name in names:
            if name.startswith("/"):
                raise AddonInstallError(
                    f"Unsafe path in ZIP (absolute): {name!r}"
                )
            for part in name.split("/"):
                if part == "..":
                    raise AddonInstallError(
                        f"Path traversal in ZIP: {name!r}"
                    )

        addon_xml_name = f"{addon_id}/addon.xml"
        if addon_xml_name not in names:
            raise AddonInstallError(
                f"addon.xml not found at {addon_xml_name!r} in ZIP "
                f"(ZIP contains: {names[:5]!r}{'...' if len(names) > 5 else ''})"
            )

        try:
            xml_bytes = zf.read(addon_xml_name)
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise AddonInstallError(
                f"Failed to parse {addon_xml_name}: {exc}"
            ) from exc
        except Exception as exc:
            raise AddonInstallError(
                f"Failed to read {addon_xml_name}: {exc}"
            ) from exc

        found_id = root.get("id")
        if found_id != addon_id:
            raise AddonInstallError(
                f"addon.xml id {found_id!r} does not match requested {addon_id!r}"
            )

        found_version = (root.get("version") or "").strip()
        if not found_version:
            raise AddonInstallError(
                f"addon.xml for {addon_id!r} has no version attribute"
            )

        if expected_version is not None and found_version != expected_version:
            raise AddonInstallError(
                f"addon.xml version {found_version!r} does not match "
                f"expected {expected_version!r}"
            )

        return found_version


# ---------------------------------------------------------------------------
# Staged install
# ---------------------------------------------------------------------------

def _staged_install(
    zip_data: bytes,
    addon_id: str,
    addons_dir: pathlib.Path,
) -> None:
    """Extract addon ZIP via staging directory; atomic rename to addons_dir/addon_id.

    Staging directory: addons_dir/_bm011_staging_{addon_id}/
    On success: staging/{addon_id}/ is renamed to addons_dir/{addon_id}/
    On failure: staging directory is cleaned up; no partial target remains.

    Raises AddonInstallError if:
      - The target addons_dir/{addon_id} already exists (caller must check)
      - The ZIP does not produce a {addon_id}/ directory after extraction
      - Any filesystem operation fails
    """
    target = addons_dir / addon_id
    staging = addons_dir / f"_bm011_staging_{addon_id}"

    if staging.exists():
        shutil.rmtree(staging)

    try:
        staging.mkdir()
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            zf.extractall(staging)

        extracted = staging / addon_id
        if not extracted.is_dir():
            raise AddonInstallError(
                f"ZIP extraction did not produce expected directory {addon_id!r}"
            )

        extracted.rename(target)

    except AddonInstallError:
        raise
    except Exception as exc:
        raise AddonInstallError(
            f"Staged install failed for {addon_id!r}: {exc}"
        ) from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


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
        """Install addon_id using the constrained package-install fallback.

        The full installation sequence:
          1. Resolve package URL from installed+enabled repository metadata
          2. Download ZIP from repository datadir URL
          3. Validate ZIP (safe paths, addon.xml, ID match)
          4. Staged extract → atomic rename to addons directory
          5. Trigger Kodi to discover the new add-on (UpdateLocalAddons or restart)

        This call is synchronous and blocks until Kodi has been notified to
        perform discovery. Enable/disable state is handled separately by
        set_addon_enabled(), which AddonManager.install() calls based on desired_state.

        addon_id has already been validated by _validate_addon_id before this
        method is called.

        Raises AddonInstallError on any failure.
        """
        raise NotImplementedError

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        """Set the enabled state of addon_id via the Kodi API (SetAddonEnabled).

        Called by AddonManager.install() to finalize desired_state after
        discovery. enabled=True enables; enabled=False disables.

        Raises AddonInstallError on failure.
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

        Returns InstalledAddonInfo when the add-on is detected as installed
        (enabled or disabled). Returns None on timeout.
        Raises AddonInstallError on hard infrastructure failure.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# AddonManager (business logic; backend-injectable)
# ---------------------------------------------------------------------------

class AddonManager:
    """General add-on detection and installation. Requires an injectable backend.

    Uses Build Manager's constrained package-install fallback (see module
    docstring for full architecture). Does NOT use Kodi's InstallAddon builtin
    (which requires interactive user confirmation in Kodi 21).

    BM-011 is the install primitive. Dependency closure is BM-012.
    Enable/disable drift reconciliation for already-installed add-ons is BM-013.

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
        Returns INSTALLED on success.
        Returns FAILED with a descriptive message on any error.

        desired_state controls the final enabled state:
          "enabled"  → install and enable (SetAddonEnabled called after discovery)
          "disabled" → install and leave disabled or explicitly disable if discovered enabled

        Only "enabled" and "disabled" are accepted. Any other value returns FAILED
        immediately without invoking any backend method.

        This is installation finalization. BM-013 handles drift reconciliation
        for add-ons that were already installed.
        """
        if desired_state not in ("enabled", "disabled"):
            return AddonInstallResult(
                addon_id=addon_id,
                status=AddonStatus.FAILED,
                desired_state=desired_state,
                enabled=None,
                version=None,
                message=f"Invalid desired_state {desired_state!r}: must be 'enabled' or 'disabled'",
            )

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

        # Install: resolve, download, validate, stage, rename, discover
        try:
            self._backend.invoke_install(addon_id)
        except AddonInstallError as exc:
            return AddonInstallResult(
                addon_id=addon_id,
                status=AddonStatus.FAILED,
                desired_state=desired_state,
                enabled=None,
                version=None,
                message=f"Install failed: {exc}",
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
                    f"(timeout; add-on may be unavailable in configured repositories)"
                ),
            )

        # Finalize desired_state symmetrically: call set_addon_enabled only when
        # the discovered state differs from what was requested.
        desired_enabled = (desired_state == "enabled")
        if info.enabled != desired_enabled:
            try:
                self._backend.set_addon_enabled(addon_id, desired_enabled)
            except AddonInstallError as exc:
                return AddonInstallResult(
                    addon_id=addon_id,
                    status=AddonStatus.FAILED,
                    desired_state=desired_state,
                    enabled=None,
                    version=None,
                    message=f"State change failed after install: {exc}",
                )
            # Verify state change took effect
            info = self._backend.get_addon_details(addon_id)
            if info is None or info.enabled != desired_enabled:
                return AddonInstallResult(
                    addon_id=addon_id,
                    status=AddonStatus.FAILED,
                    desired_state=desired_state,
                    enabled=None,
                    version=None,
                    message=(
                        f"State verification failed: {addon_id!r} expected "
                        f"enabled={desired_enabled} after SetAddonEnabled"
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
# Production backend — Kodi runtime (xbmc / xbmcvfs / xbmcaddon)
# ---------------------------------------------------------------------------

class KodiRuntimeAddonBackend(AddonBackend):
    """Production backend. Implements the constrained package-install fallback.

    All Kodi modules (xbmc, xbmcvfs, xbmcaddon) are imported lazily inside
    each method so this class is instantiable outside Kodi.
    Calling methods without Kodi loaded raises AddonInstallError.

    Install sequence (invoke_install):
      1. Enumerate installed+enabled repository add-ons via JSON-RPC
      2. Read each repo's addon.xml (xbmcvfs) to get <info> URL
      3. Fetch addons.xml from <info> URL; search for addon_id
      4. Construct ZIP URL from <datadir> URL + version
      5. Download and validate the ZIP
      6. Staged extraction → atomic rename to special://home/addons/{addon_id}
      7. xbmc.executebuiltin("UpdateLocalAddons") — Kodi discovers new add-on
    """

    def _xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise AddonInstallError(
                "Kodi runtime module (xbmc) is not available"
            ) from exc

    def _get_addons_dir(self) -> pathlib.Path:
        try:
            import xbmcvfs  # noqa: PLC0415
        except ImportError as exc:
            raise AddonInstallError(f"xbmcvfs is not available: {exc}") from exc
        return pathlib.Path(xbmcvfs.translatePath("special://home/addons"))

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

    def _resolve_package_url(self, addon_id: str) -> Tuple[str, str]:
        """Find addon_id in installed+enabled repositories. Returns (zip_url, version).

        Enumerates repositories via JSON-RPC, reads each repo's addon.xml via
        xbmcvfs, fetches its addons.xml, and returns the first match.
        Repositories are iterated in lexical order of their addon ID so that
        resolution is deterministic regardless of Kodi return order.
        Raises AddonInstallError if addon_id is not found in any enabled repo.
        """
        xbmc = self._xbmc()
        try:
            import xbmcaddon  # noqa: PLC0415
            import xbmcvfs    # noqa: PLC0415
        except ImportError as exc:
            raise AddonInstallError(f"Kodi module unavailable: {exc}") from exc

        # Get all installed repository add-ons
        repos_req = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.GetAddons",
            "params": {"type": "xbmc.addon.repository", "installed": True},
            "id": 1,
        })
        try:
            repos_resp = json.loads(xbmc.executeJSONRPC(repos_req))
        except Exception as exc:
            raise AddonInstallError(
                f"Addons.GetAddons(repository) failed: {exc}"
            ) from exc

        if "error" in repos_resp or not isinstance(repos_resp.get("result"), dict):
            raise AddonInstallError(
                f"Addons.GetAddons returned error: {repos_resp.get('error', repos_resp)}"
            )

        addons_list = repos_resp["result"].get("addons") or []
        repo_ids = sorted(
            a["addonid"]
            for a in addons_list
            if isinstance(a, dict) and "addonid" in a
        )

        if not repo_ids:
            raise AddonInstallError(
                f"No installed repository add-ons found; cannot resolve {addon_id!r}"
            )

        for repo_id in repo_ids:
            # Skip disabled repos
            det_req = json.dumps({
                "jsonrpc": "2.0",
                "method": "Addons.GetAddonDetails",
                "params": {"addonid": repo_id, "properties": ["enabled"]},
                "id": 1,
            })
            try:
                det_resp = json.loads(xbmc.executeJSONRPC(det_req))
            except Exception:
                continue
            repo_detail = (
                det_resp.get("result", {}).get("addon", {})
                if isinstance(det_resp.get("result"), dict)
                else {}
            )
            if not isinstance(repo_detail, dict) or not repo_detail.get("enabled"):
                continue

            # Read the repo's addon.xml via xbmcvfs
            try:
                repo_path = xbmcaddon.Addon(repo_id).getAddonInfo("path")
            except Exception:
                continue

            addon_xml_path = repo_path.rstrip("/") + "/addon.xml"
            try:
                f = xbmcvfs.File(addon_xml_path)
                xml_raw = f.read()
                f.close()
                xml_bytes = (
                    xml_raw.encode("utf-8") if isinstance(xml_raw, str) else xml_raw
                )
            except Exception:
                continue

            try:
                repo_root = ET.fromstring(xml_bytes)
            except ET.ParseError:
                continue

            # Parse <extension point="xbmc.addon.repository"> → <dir> elements
            for ext in repo_root.findall("extension"):
                if ext.get("point") != "xbmc.addon.repository":
                    continue
                for dir_el in ext.findall("dir"):
                    info_el = dir_el.find("info")
                    datadir_el = dir_el.find("datadir")
                    if info_el is None or datadir_el is None:
                        continue
                    info_url = (info_el.text or "").strip()
                    datadir_url = (datadir_el.text or "").strip()
                    zip_flag = datadir_el.get("zip", "false").lower() == "true"
                    if not info_url or not datadir_url or not zip_flag:
                        continue

                    # Fetch and parse the repository's addons.xml
                    try:
                        _validate_url(info_url, context=f"{repo_id} <info> URL")
                        addons_xml_data = _fetch_bytes(
                            info_url, max_bytes=_MAX_ADDONS_XML_BYTES
                        )
                        addons_root = ET.fromstring(addons_xml_data)
                    except (AddonInstallError, ET.ParseError):
                        continue

                    for addon_el in addons_root.findall("addon"):
                        if addon_el.get("id") != addon_id:
                            continue
                        version = (addon_el.get("version") or "").strip()
                        if not version:
                            continue
                        try:
                            _validate_url(
                                datadir_url, context=f"{repo_id} <datadir> URL"
                            )
                        except AddonInstallError:
                            continue
                        pkg_url = (
                            datadir_url.rstrip("/")
                            + f"/{addon_id}/{version}/{addon_id}-{version}.zip"
                        )
                        return pkg_url, version

        raise AddonInstallError(
            f"{addon_id!r} not found in any installed+enabled repository"
        )

    def invoke_install(self, addon_id: str) -> None:
        """Install addon_id via the constrained package-install fallback.

        Sequence: resolve URL → download → validate → staged extract →
        UpdateLocalAddons. Does not enable; that is set_addon_enabled()'s job.
        """
        # 1. Resolve package URL from configured repositories
        pkg_url, version = self._resolve_package_url(addon_id)

        # 2. Download ZIP
        zip_data = _fetch_bytes(pkg_url, max_bytes=_MAX_ADDON_ZIP_BYTES)

        # 3. Validate ZIP
        _validate_addon_zip(zip_data, addon_id, expected_version=version)

        # 4. Staged install
        addons_dir = self._get_addons_dir()
        target = addons_dir / addon_id
        if target.exists():
            raise AddonInstallError(
                f"Target already exists: {addon_id!r} "
                f"— should have been caught by is_installed() check"
            )
        _staged_install(zip_data, addon_id, addons_dir)

        # 5. Trigger Kodi to discover the new add-on
        xbmc = self._xbmc()
        xbmc.executebuiltin("UpdateLocalAddons")

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        """Set enabled state of addon_id via Addons.SetAddonEnabled JSON-RPC."""
        xbmc = self._xbmc()
        req = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.SetAddonEnabled",
            "params": {"addonid": addon_id, "enabled": enabled},
            "id": 1,
        })
        try:
            resp = json.loads(xbmc.executeJSONRPC(req))
        except Exception as exc:
            raise AddonInstallError(
                f"Addons.SetAddonEnabled({addon_id!r}, {enabled}) failed: {exc}"
            ) from exc
        if "error" in resp:
            raise AddonInstallError(
                f"Addons.SetAddonEnabled({addon_id!r}, {enabled}) returned error: {resp['error']}"
            )

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
