"""
Build Manager repository detection and installation (BM-010).

Public API
----------
RepositoryManager(backend).is_installed(addon_id) -> bool
    Check whether a repository add-on is currently installed in Kodi.

RepositoryManager(backend).install(repository) -> RepositoryInstallResult
    Install a repository from its manifest bootstrap_url.
    Returns ALREADY_INSTALLED if already present (no mutation).
    Returns INSTALLED on success.
    Returns FAILED with a message on any error.

KodiRuntimeRepositoryBackend()
    Backend for production use inside the Kodi Python runtime.
    Lazy-imports xbmc / xbmcvfs so the class is instantiable outside Kodi.
    Calling methods without Kodi loaded raises RepositoryInstallError.

RepositoryBackend
    Abstract backend interface. Subclass and override all methods to build
    a fake or stub backend for tests.

Result types
------------
RepositoryStatus    -- ALREADY_INSTALLED | INSTALLED | FAILED
RepositoryInstallResult(addon_id, status, message)

Errors
------
RepositoryError          -- base class
RepositoryValidationError -- invalid declaration or artifact
RepositoryInstallError   -- download, extraction, or Kodi-side failure

Installation mechanism
----------------------
Kodi repository bootstrap installs the repository add-on ZIP into
special://home/addons/{addon_id}/ using Python's zipfile, then calls
xbmc.executebuiltin("UpdateLocalAddons") to trigger Kodi's addon scanner.
Installation is verified by polling Addons.GetAddons via xbmc.executeJSONRPC
until the repository add-on appears or a timeout expires.

This is the standard Kodi-supported mechanism used by add-ons that need to
bootstrap repository dependencies. No Kodi databases are edited directly.

Security policy
---------------
- Only https and http URL schemes accepted.
- No embedded credentials in URLs (checked before download and after redirect).
- Redirects to disallowed schemes are rejected before following.
- Maximum download size: 50 MB (repository ZIPs are typically < 500 KB).
- Download timeout: 30 seconds.
- Verification timeout: 60 seconds.
- ZIP entries with absolute paths or .. traversal are rejected before extraction.
- Extraction target is always inside special://home/addons/{addon_id}.
- No shell commands, no database edits, no arbitrary path writes.

Stdlib only — no new runtime dependencies.
"""

from __future__ import annotations

import enum
import io
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Optional

from resources.lib.manifest import Repository


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RepositoryError(Exception):
    """Base class for all repository operation errors."""


class RepositoryValidationError(RepositoryError):
    """Repository declaration or bootstrap artifact is invalid."""


class RepositoryInstallError(RepositoryError):
    """Download, extraction, or Kodi-side installation failure."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class RepositoryStatus(str, enum.Enum):
    """Outcome of a repository install request."""
    ALREADY_INSTALLED = "already_installed"
    INSTALLED = "installed"
    FAILED = "failed"


@dataclass(frozen=True)
class RepositoryInstallResult:
    """Immutable result of a RepositoryManager.install() call."""
    addon_id: str
    status: RepositoryStatus
    message: str


# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES: FrozenSet[str] = frozenset({"https", "http"})
_MAX_ARTIFACT_BYTES: int = 50 * 1024 * 1024  # 50 MB
_DOWNLOAD_TIMEOUT: float = 30.0             # seconds
_VERIFY_TIMEOUT: float = 60.0              # seconds
_VERIFY_INTERVAL: float = 1.0             # seconds


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class RepositoryBackend:
    """Injectable backend for Kodi runtime calls.

    Override all methods in a concrete subclass. Defaults raise
    NotImplementedError so incomplete fakes surface missing stubs immediately.
    """

    def get_installed_addon_ids(self) -> FrozenSet[str]:
        """Return the frozenset of currently installed Kodi add-on IDs."""
        raise NotImplementedError

    def download_artifact(
        self,
        url: str,
        *,
        max_bytes: int = _MAX_ARTIFACT_BYTES,
        timeout: float = _DOWNLOAD_TIMEOUT,
    ) -> bytes:
        """Download the bootstrap artifact. Enforce size/timeout limits."""
        raise NotImplementedError

    def install_zip_to_addons(self, addon_id: str, zip_bytes: bytes) -> None:
        """Extract the repository ZIP into the Kodi addons directory."""
        raise NotImplementedError

    def trigger_addon_scan(self) -> None:
        """Signal Kodi to re-scan the addons directory."""
        raise NotImplementedError

    def poll_addon_installed(
        self,
        addon_id: str,
        *,
        timeout: float = _VERIFY_TIMEOUT,
        interval: float = _VERIFY_INTERVAL,
    ) -> bool:
        """Poll until addon_id appears installed or timeout expires."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# URL validation (applied before download and after each redirect)
# ---------------------------------------------------------------------------

def _validate_url_policy(url: str, *, context: str = "URL") -> None:
    """Enforce BM-010 URL policy. Raises RepositoryValidationError on violation."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:  # noqa: BLE001
        raise RepositoryValidationError(f"{context}: malformed URL: {exc}") from exc

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise RepositoryValidationError(
            f"{context}: scheme {parsed.scheme!r} is not allowed "
            f"(only 'https' and 'http' are accepted)"
        )
    if not parsed.netloc:
        raise RepositoryValidationError(
            f"{context}: URL must have a host"
        )
    if parsed.username or parsed.password:
        raise RepositoryValidationError(
            f"{context}: URL must not contain embedded credentials"
        )


# ---------------------------------------------------------------------------
# Redirect handler — validates scheme on every redirect before following
# ---------------------------------------------------------------------------

class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject any redirect to a disallowed URL scheme before following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise RepositoryInstallError(
                f"Redirect to disallowed URL scheme {parsed.scheme!r} rejected"
            )
        if parsed.username or parsed.password:
            raise RepositoryInstallError(
                "Redirect to URL with embedded credentials rejected"
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


# ---------------------------------------------------------------------------
# Download helper (used by KodiRuntimeRepositoryBackend and tests)
# ---------------------------------------------------------------------------

def _download_artifact(
    url: str,
    *,
    max_bytes: int = _MAX_ARTIFACT_BYTES,
    timeout: float = _DOWNLOAD_TIMEOUT,
) -> bytes:
    """Download url with bounded size and timeout, enforcing scheme safety on redirects.

    Raises RepositoryValidationError for policy violations.
    Raises RepositoryInstallError for network/I/O failures.
    """
    _validate_url_policy(url, context="bootstrap_url")
    opener = _build_safe_opener()
    try:
        with opener.open(url, timeout=timeout) as resp:
            chunks = []
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RepositoryInstallError(
                        f"Artifact exceeds maximum size of {max_bytes} bytes"
                    )
                chunks.append(chunk)
    except RepositoryError:
        raise
    except urllib.error.URLError as exc:
        raise RepositoryInstallError(f"Download failed: {exc}") from exc

    data = b"".join(chunks)
    if not data:
        raise RepositoryInstallError("Downloaded artifact is empty")
    return data


# ---------------------------------------------------------------------------
# ZIP validation (applied before any extraction)
# ---------------------------------------------------------------------------

def _validate_zip_entries(names: list) -> None:
    """Reject any ZIP entry name that contains a path traversal or absolute path."""
    for name in names:
        normalized = name.replace("\\", "/")
        parts = [p for p in normalized.split("/") if p]
        if not parts:
            continue
        # Absolute Unix path
        if normalized.startswith("/"):
            raise RepositoryValidationError(
                f"ZIP contains absolute path: {name!r}"
            )
        # Windows absolute path (e.g. C:/, //server)
        if parts[0].endswith(":"):
            raise RepositoryValidationError(
                f"ZIP contains absolute path: {name!r}"
            )
        # Parent-directory traversal
        if ".." in parts:
            raise RepositoryValidationError(
                f"ZIP contains path traversal: {name!r}"
            )
        # Null bytes
        if "\x00" in name:
            raise RepositoryValidationError(
                f"ZIP entry name contains null byte: {name!r}"
            )


def _find_addon_xml(names: list) -> Optional[str]:
    """Return the ZIP entry name of addon.xml at depth 1 or 2, or None."""
    for name in sorted(names):
        parts = [p for p in name.replace("\\", "/").split("/") if p]
        if parts and parts[-1] == "addon.xml" and len(parts) <= 2:
            return name
    return None


def validate_repository_zip(zip_bytes: bytes, expected_addon_id: str) -> None:
    """Validate a repository bootstrap ZIP artifact.

    Raises RepositoryValidationError if:
    - Not a valid ZIP file
    - Contains path traversal or absolute paths
    - No addon.xml found at depth ≤ 2
    - addon.xml declares a different add-on ID
    - addon.xml does not declare xbmc.addon.repository extension
    """
    if not zip_bytes:
        raise RepositoryValidationError("Artifact is empty")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise RepositoryValidationError(f"Not a valid ZIP: {exc}") from exc

    with zf:
        names = zf.namelist()

    _validate_zip_entries(names)

    addon_xml_path = _find_addon_xml(names)
    if addon_xml_path is None:
        raise RepositoryValidationError(
            f"ZIP does not contain addon.xml at depth ≤ 2 (entries: {len(names)})"
        )

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        addon_xml_bytes = zf.read(addon_xml_path)

    try:
        root = ET.fromstring(addon_xml_bytes.decode("utf-8", errors="replace"))
    except ET.ParseError as exc:
        raise RepositoryValidationError(f"addon.xml is not valid XML: {exc}") from exc

    declared_id = root.get("id", "")
    if declared_id != expected_addon_id:
        raise RepositoryValidationError(
            f"addon.xml declares id={declared_id!r}, expected {expected_addon_id!r}"
        )

    has_repo_ext = any(
        ext.get("point") == "xbmc.addon.repository"
        for ext in root.findall("extension")
    )
    if not has_repo_ext:
        raise RepositoryValidationError(
            f"addon.xml for {expected_addon_id!r} does not declare "
            f"extension point='xbmc.addon.repository'"
        )


# ---------------------------------------------------------------------------
# ZIP extraction helper (path-safe; used by KodiRuntimeRepositoryBackend)
# ---------------------------------------------------------------------------

def _extract_zip_to_directory(zip_bytes: bytes, addon_id: str, target: Path) -> None:
    """Extract repository ZIP contents to target, enforcing path safety.

    ZIP entries may be flat (addon.xml, ...) or prefixed (addon_id/addon.xml, ...).
    Only entries under the add-on prefix (or at root for flat ZIPs) are extracted.
    Every destination path is checked to be inside target before writing.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()

    prefix = f"{addon_id}/"
    has_prefix = any(n.startswith(prefix) and n != prefix for n in names)

    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in names:
            if name.endswith("/"):
                continue  # directory entry; created lazily
            if has_prefix:
                if not name.startswith(prefix):
                    continue
                rel = name[len(prefix):]
            else:
                rel = name
            if not rel:
                continue

            dest = target / rel
            dest_resolved = dest.resolve()

            # Final containment check before write
            try:
                dest_resolved.relative_to(target_resolved)
            except ValueError:
                raise RepositoryInstallError(
                    f"ZIP entry {name!r} would escape installation directory"
                )

            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src:
                dest.write_bytes(src.read())


# ---------------------------------------------------------------------------
# Repository manager (business logic; backend-injectable)
# ---------------------------------------------------------------------------

class RepositoryManager:
    """Repository detection and installation. Requires an injectable backend.

    Usage (real Kodi runtime):
        mgr = RepositoryManager(KodiRuntimeRepositoryBackend())
        result = mgr.install(repository)

    Usage (tests, no Kodi required):
        mgr = RepositoryManager(FakeRepositoryBackend(...))
        result = mgr.install(repository)
    """

    def __init__(self, backend: RepositoryBackend) -> None:
        self._backend = backend

    def is_installed(self, addon_id: str) -> bool:
        """True if the add-on is currently reported installed by Kodi."""
        return addon_id in self._backend.get_installed_addon_ids()

    def install(self, repository: Repository) -> RepositoryInstallResult:
        """Install a repository from its manifest bootstrap_url.

        Returns ALREADY_INSTALLED (no mutation) if already present.
        Returns INSTALLED on success.
        Returns FAILED with a message describing the failure.
        """
        addon_id = repository.addon_id

        # Detection: already installed? No mutation.
        if self.is_installed(addon_id):
            return RepositoryInstallResult(
                addon_id=addon_id,
                status=RepositoryStatus.ALREADY_INSTALLED,
                message=f"{addon_id!r} is already installed",
            )

        if not repository.bootstrap_url:
            return RepositoryInstallResult(
                addon_id=addon_id,
                status=RepositoryStatus.FAILED,
                message=f"{addon_id!r} has no bootstrap_url",
            )

        # Download
        try:
            zip_bytes = self._backend.download_artifact(repository.bootstrap_url)
        except RepositoryError as exc:
            return RepositoryInstallResult(
                addon_id=addon_id,
                status=RepositoryStatus.FAILED,
                message=f"Download failed: {exc}",
            )

        # Validate
        try:
            validate_repository_zip(zip_bytes, addon_id)
        except RepositoryValidationError as exc:
            return RepositoryInstallResult(
                addon_id=addon_id,
                status=RepositoryStatus.FAILED,
                message=f"Artifact rejected: {exc}",
            )

        # Install + trigger scan + verify
        try:
            self._backend.install_zip_to_addons(addon_id, zip_bytes)
        except RepositoryError as exc:
            return RepositoryInstallResult(
                addon_id=addon_id,
                status=RepositoryStatus.FAILED,
                message=f"Installation failed: {exc}",
            )

        try:
            self._backend.trigger_addon_scan()
        except RepositoryError as exc:
            return RepositoryInstallResult(
                addon_id=addon_id,
                status=RepositoryStatus.FAILED,
                message=f"Addon scan failed: {exc}",
            )

        try:
            installed = self._backend.poll_addon_installed(addon_id)
        except RepositoryError as exc:
            return RepositoryInstallResult(
                addon_id=addon_id,
                status=RepositoryStatus.FAILED,
                message=f"Verification failed: {exc}",
            )

        if not installed:
            return RepositoryInstallResult(
                addon_id=addon_id,
                status=RepositoryStatus.FAILED,
                message=(
                    f"{addon_id!r} was not detected after installation "
                    f"(verification timeout)"
                ),
            )

        return RepositoryInstallResult(
            addon_id=addon_id,
            status=RepositoryStatus.INSTALLED,
            message=f"{addon_id!r} installed successfully",
        )


# ---------------------------------------------------------------------------
# Production backend — Kodi runtime (xbmc / xbmcvfs)
# ---------------------------------------------------------------------------

class KodiRuntimeRepositoryBackend(RepositoryBackend):
    """Production backend using xbmc/xbmcvfs. Lazy-imports Kodi modules.

    Kodi modules are imported inside each method so this class is
    instantiable outside Kodi. Calling methods without Kodi loaded raises
    RepositoryInstallError.
    """

    def _xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise RepositoryInstallError(
                "Kodi runtime module (xbmc) is not available"
            ) from exc

    def _xbmcvfs(self):
        try:
            import xbmcvfs  # noqa: PLC0415
            return xbmcvfs
        except ImportError as exc:
            raise RepositoryInstallError(
                "Kodi runtime module (xbmcvfs) is not available"
            ) from exc

    def get_installed_addon_ids(self) -> FrozenSet[str]:
        xbmc = self._xbmc()
        req = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.GetAddons",
            "params": {"installed": True, "properties": ["enabled"]},
            "id": 1,
        })
        try:
            resp = json.loads(xbmc.executeJSONRPC(req))
        except (json.JSONDecodeError, Exception) as exc:
            raise RepositoryInstallError(
                f"Addons.GetAddons failed: {exc}"
            ) from exc
        addons = resp.get("result", {}).get("addons", [])
        return frozenset(
            a["addonid"] for a in addons if isinstance(a, dict) and "addonid" in a
        )

    def download_artifact(
        self,
        url: str,
        *,
        max_bytes: int = _MAX_ARTIFACT_BYTES,
        timeout: float = _DOWNLOAD_TIMEOUT,
    ) -> bytes:
        return _download_artifact(url, max_bytes=max_bytes, timeout=timeout)

    def install_zip_to_addons(self, addon_id: str, zip_bytes: bytes) -> None:
        xbmcvfs = self._xbmcvfs()
        addons_dir_raw = xbmcvfs.translatePath("special://home/addons")
        addons_dir = Path(addons_dir_raw)
        target = addons_dir / addon_id

        # Safety: confirm target is inside addons_dir
        try:
            target.resolve().relative_to(addons_dir.resolve())
        except ValueError:
            raise RepositoryInstallError(
                f"Safety: installation target {target} is outside addons directory"
            )

        if target.exists():
            shutil.rmtree(target)

        _extract_zip_to_directory(zip_bytes, addon_id, target)

    def trigger_addon_scan(self) -> None:
        xbmc = self._xbmc()
        xbmc.executebuiltin("UpdateLocalAddons")

    def poll_addon_installed(
        self,
        addon_id: str,
        *,
        timeout: float = _VERIFY_TIMEOUT,
        interval: float = _VERIFY_INTERVAL,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if addon_id in self.get_installed_addon_ids():
                    return True
            except RepositoryInstallError:
                pass
            time.sleep(interval)
        return False
