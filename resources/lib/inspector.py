"""
Build Manager Kodi state inspector (BM-005).

Public API
----------
inspect_kodi_state() -> KodiState
    Inspect current Kodi state using the real Kodi runtime backend.

KodiStateInspector(backend=None).inspect() -> KodiState
    Inspector with injectable backend. Pass a backend for testing.

KodiRuntimeBackend()
    Real Kodi backend. Uses xbmc JSON-RPC at runtime; xbmc is imported
    lazily inside methods so this class is instantiable outside Kodi.
    Calling any method without Kodi loaded raises KodiInspectionError.

KodiBackend
    Abstract base for injectable backends. Subclass and override all four
    methods to build a fake or stub backend for tests.

Errors
------
KodiInspectionError
    Raised when Kodi state cannot be determined. Covers:
    - Kodi runtime (xbmc) unavailable
    - Malformed or missing fields in a JSON-RPC response
    Version and skin degraded gracefully to "" on non-fatal issues.

Platform mapping
----------------
Kodi condition            BM-005 platform ID
system.platform.tvos   -> tvos
system.platform.android-> android   (includes Fire TV — no reliable distinction)
system.platform.osx    -> macos
system.platform.ios    -> ios
system.platform.windows-> windows
system.platform.linux  -> linux
(none matched)         -> unknown

Precedence (first match wins when multiple flags are true):
  tvos > android > macos > ios > windows > linux > unknown

Fire TV: no Kodi condition reliably distinguishes Fire TV from other Android
devices, so it continues to normalize as "android" in BM-005.

JSON-RPC methods used (read-only)
----------------------------------
  Addons.GetAddons        — installed add-ons with enabled/version properties
  Application.GetProperties — Kodi version (major.minor)
xbmc.getSkinDir()         — active skin directory (==addon_id for all known skins)
xbmc.getCondVisibility()  — platform condition flags

No mutating JSON-RPC methods are called.

Stdlib only — no new runtime dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class KodiInspectionError(Exception):
    """Failed to inspect Kodi runtime state."""


# ---------------------------------------------------------------------------
# Typed output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InstalledAddon:
    """State of one installed Kodi add-on."""
    addon_id: str
    enabled: bool
    version: str    # "" when the runtime did not report a version


@dataclass(frozen=True)
class KodiState:
    """Immutable snapshot of Kodi runtime state.

    platform: BM-005 platform ID ("tvos", "android", "macos", "ios",
        "windows", "linux", or "unknown").
    kodi_version: "MAJOR.MINOR" (e.g. "21.0"), or "" when unavailable.
    active_skin: skin add-on ID ("skin.<name>"), or "" when unknown.
    addons: installed add-ons, sorted by addon_id for deterministic ordering.
    """
    platform: str
    kodi_version: str
    active_skin: str
    addons: Tuple[InstalledAddon, ...]


# ---------------------------------------------------------------------------
# Platform constants
# ---------------------------------------------------------------------------

# Maps BM-005 platform IDs to Kodi condition-visibility strings.
_PLATFORM_CONDITIONS: Dict[str, str] = {
    "tvos":    "system.platform.tvos",
    "android": "system.platform.android",
    "macos":   "system.platform.osx",
    "ios":     "system.platform.ios",
    "windows": "system.platform.windows",
    "linux":   "system.platform.linux",
}

# Evaluation order: first match wins when multiple flags are simultaneously true.
# tvos before ios: newer Kodi builds may satisfy both on Apple TV hardware.
# android before linux: some Android builds expose linux conditions too.
_PLATFORM_PRECEDENCE = ("tvos", "android", "macos", "ios", "windows", "linux")


# ---------------------------------------------------------------------------
# Backend interface (injectable for tests)
# ---------------------------------------------------------------------------

class KodiBackend:
    """Injectable backend interface for Kodi runtime calls.

    Override all methods in a concrete subclass. The default implementations
    raise NotImplementedError so an incomplete fake surfaces missing stubs
    immediately during testing.
    """

    def get_platform_flags(self) -> Dict[str, bool]:
        """Return {platform_id: bool} for every ID in _PLATFORM_PRECEDENCE."""
        raise NotImplementedError

    def get_kodi_version(self) -> str:
        """Return Kodi version as 'MAJOR.MINOR', or '' when unavailable."""
        raise NotImplementedError

    def get_active_skin(self) -> str:
        """Return active skin add-on ID (e.g. 'skin.arctic.fuse.3'), or ''."""
        raise NotImplementedError

    def get_installed_addons(self) -> List[Dict[str, object]]:
        """Return list of raw add-on dicts with 'addonid', 'enabled', 'version'."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# JSON-RPC response parsers (pure functions; testable without xbmc)
# ---------------------------------------------------------------------------

def _parse_addon_response(response_text: str) -> List[Dict[str, object]]:
    """Parse an Addons.GetAddons JSON-RPC response.

    Returns the list of raw add-on dicts. Raises KodiInspectionError on:
    - invalid JSON
    - response is not an object
    - 'result' field missing
    - 'result' is not an object
    - 'result.addons' is present but not an array

    A missing 'addons' key inside result returns [].
    """
    try:
        response = json.loads(response_text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise KodiInspectionError(
            f"Addons.GetAddons: invalid JSON in response: {exc}"
        ) from exc

    if not isinstance(response, dict):
        raise KodiInspectionError(
            "Addons.GetAddons: response must be a JSON object"
        )
    if "result" not in response:
        raise KodiInspectionError(
            "Addons.GetAddons: 'result' field missing from response"
        )
    result = response["result"]
    if not isinstance(result, dict):
        raise KodiInspectionError(
            f"Addons.GetAddons: 'result' must be an object, "
            f"got {type(result).__name__}"
        )
    addons_raw = result.get("addons", [])
    if not isinstance(addons_raw, list):
        raise KodiInspectionError(
            f"Addons.GetAddons: 'result.addons' must be an array, "
            f"got {type(addons_raw).__name__}"
        )
    return addons_raw


def _parse_version_response(response_text: str) -> str:
    """Parse an Application.GetProperties version response.

    Returns 'MAJOR.MINOR' on success. Returns '' for any response that is
    missing, malformed, or incomplete. Never raises KodiInspectionError
    because Kodi version is 'if available'.
    """
    try:
        response = json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(response, dict):
        return ""
    result = response.get("result")
    if not isinstance(result, dict):
        return ""
    version = result.get("version")
    if not isinstance(version, dict):
        return ""
    major = version.get("major")
    minor = version.get("minor")
    if isinstance(major, int) and isinstance(minor, int):
        return f"{major}.{minor}"
    return ""


# ---------------------------------------------------------------------------
# Add-on list normalizer (pure function; testable without xbmc)
# ---------------------------------------------------------------------------

def _parse_addon_list(raw: List[object]) -> Tuple[InstalledAddon, ...]:
    """Convert a raw add-on list to a sorted tuple of InstalledAddon.

    Malformed entries are silently skipped:
    - entry is not a dict
    - 'addonid' is absent, non-str, or empty

    Field defaults for present-but-wrong-type values:
    - enabled: False when absent or non-bool
    - version: "" when absent or non-str

    Output is sorted by addon_id for deterministic ordering.
    """
    out: List[InstalledAddon] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        addon_id = item.get("addonid")
        if not isinstance(addon_id, str) or not addon_id:
            continue
        enabled_raw = item.get("enabled")
        enabled = enabled_raw if isinstance(enabled_raw, bool) else False
        version_raw = item.get("version")
        version = version_raw if isinstance(version_raw, str) else ""
        out.append(InstalledAddon(addon_id=addon_id, enabled=enabled, version=version))
    out.sort(key=lambda a: a.addon_id)
    return tuple(out)


# ---------------------------------------------------------------------------
# Real Kodi runtime backend
# ---------------------------------------------------------------------------

class KodiRuntimeBackend(KodiBackend):
    """Backend that calls real Kodi runtime APIs (xbmc / JSON-RPC).

    xbmc is imported lazily inside each method so this class is instantiable
    outside Kodi. Calling any method without Kodi loaded raises
    KodiInspectionError rather than ImportError.
    """

    def _get_xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise KodiInspectionError(
                "Kodi runtime module (xbmc) is not available"
            ) from exc

    def get_platform_flags(self) -> Dict[str, bool]:
        xbmc = self._get_xbmc()
        return {
            pid: bool(xbmc.getCondVisibility(cond))
            for pid, cond in _PLATFORM_CONDITIONS.items()
        }

    def get_kodi_version(self) -> str:
        xbmc = self._get_xbmc()
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "Application.GetProperties",
            "params": {"properties": ["version"]},
            "id": 1,
        })
        response_text = xbmc.executeJSONRPC(request)
        return _parse_version_response(response_text)

    def get_active_skin(self) -> str:
        xbmc = self._get_xbmc()
        skin_dir = xbmc.getSkinDir()
        if isinstance(skin_dir, str) and skin_dir.startswith("skin."):
            return skin_dir
        return ""

    def get_installed_addons(self) -> List[Dict[str, object]]:
        xbmc = self._get_xbmc()
        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.GetAddons",
            "params": {
                "installed": True,
                "properties": ["enabled", "version"],
            },
            "id": 2,
        })
        response_text = xbmc.executeJSONRPC(request)
        return _parse_addon_response(response_text)


# ---------------------------------------------------------------------------
# Inspector
# ---------------------------------------------------------------------------

class KodiStateInspector:
    """Read-only Kodi state inspector with injectable backend.

    Usage (real Kodi runtime):
        state = KodiStateInspector().inspect()

    Usage (tests, no Kodi runtime required):
        state = KodiStateInspector(backend=FakeBackend(...)).inspect()

    inspect() raises KodiInspectionError when platform detection or add-on
    listing fails. kodi_version and active_skin degrade gracefully to "".
    inspect() does not mutate any Kodi state.
    """

    def __init__(self, backend: Optional[KodiBackend] = None) -> None:
        self._backend = backend if backend is not None else KodiRuntimeBackend()

    def inspect(self) -> KodiState:
        """Inspect current Kodi state and return an immutable KodiState.

        Raises:
            KodiInspectionError: if the backend cannot provide required state
                (platform flags, installed add-ons).
        """
        platform = self._detect_platform()
        kodi_version = self._backend.get_kodi_version()
        active_skin = self._backend.get_active_skin()
        raw_addons = self._backend.get_installed_addons()
        addons = _parse_addon_list(raw_addons)
        return KodiState(
            platform=platform,
            kodi_version=kodi_version,
            active_skin=active_skin,
            addons=addons,
        )

    def _detect_platform(self) -> str:
        flags = self._backend.get_platform_flags()
        for platform_id in _PLATFORM_PRECEDENCE:
            if flags.get(platform_id):
                return platform_id
        return "unknown"


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def inspect_kodi_state() -> KodiState:
    """Inspect current Kodi state using the real Kodi runtime backend.

    Raises:
        KodiInspectionError: if the Kodi runtime is unavailable or fails.
    """
    return KodiStateInspector().inspect()
