#!/usr/bin/env python3
"""
Build Manager disposable Kodi test harness.

Creates an isolated Kodi environment under .kodi-test/ within the project
directory. The real Kodi profile is never touched.

Isolation model
---------------
Kodi on macOS resolves its profile from the process HOME environment variable:
  $HOME/Library/Application Support/Kodi

Overriding HOME to a project-local directory gives Kodi a completely isolated,
disposable profile with no connection to the real installation.

Commands
--------
  reset           Remove and recreate the disposable profile
  install         Copy script.build.manager into the disposable add-on folder
  configure       Write guisettings.xml to enable the JSON-RPC web server
  enable-webserver  Alias for configure
  launch          Start Kodi against the disposable profile
  wait            Poll JSON-RPC until Kodi is ready (or timeout)
  stop            Send SIGTERM to the disposable Kodi process; wait for exit
  restart         stop + launch
  inspect         Query disposable Kodi state via HTTP JSON-RPC
  status          Print current harness state (pid, paths, running/stopped)
  validate        Full live validation sequence (BM-009)
  validate-repo   BM-010 live validation: repository detection and installation
  validate-addon  BM-011 live validation: general add-on installation
  validate-dependencies  BM-012 live validation: dependency closure
  validate-addon-state   BM-013 live validation: enable/disable reconciliation
  validate-post-operations  BM-014 live validation: post-operation state validation
  validate-config BM-015 live validation: configuration package deployment
  validate-af3-package BM-018E live validation: production AF3 package
  validate-build-manager BM-020A live validation: production executor
  validate-build-manager-transaction BM-020B live validation: transaction startup
  validate-build-manager-manual-restart BM-020C1 live validation: manual restart handoff
  validate-build-manager-resume BM-020C live validation: automatic post-restart resume
  validate-frozen-capture BM-021B disposable exact-artifact capture proof
  validate-updater-guard BM-021B disposable global updater-guard proof
  validate-frozen-install BM-022 disposable exact frozen-install proof
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

# ---------------------------------------------------------------------------
# Paths — all resolved relative to this file's location
# ---------------------------------------------------------------------------

PROJECT = Path(__file__).resolve().parents[1]

ROOT = PROJECT / ".kodi-test"
HOME = ROOT / "home"
KODI_APPDATA_DIR = HOME / "Library" / "Application Support" / "Kodi"
KODI_USERDATA_DIR = KODI_APPDATA_DIR / "userdata"
KODI_ADDONS_DIR = KODI_APPDATA_DIR / "addons"
KODI_LOG_FILE = HOME / "Library" / "Logs" / "kodi.log"
PID_FILE = ROOT / "kodi.pid"

KODI = Path("/Applications/Kodi.app/Contents/MacOS/Kodi")
KODI_SYSTEM_ADDONS_DIR = KODI.parent.parent / "Resources" / "Kodi" / "addons"

ADDON_ID = "script.build.manager"
ADDON_INCLUDE: frozenset = frozenset({"addon.xml", "default.py", "service.py", "resources"})

WEBSERVER_PORT = 8920
WEBSERVER_USERNAME = "bm-test"
WEBSERVER_PASSWORD = "bm-test-only"

_BM022_REPO_ID = "repository.bm022.fixture"
_BM022_DEP_ID = "script.module.bm022.dep"
_BM022_APP_ID = "plugin.video.bm022.fixture"
_BM022_VERSION = "1.0.0"

# The real Kodi profile — this harness must never overlap with it.
NORMAL_APPDATA_DIR = Path.home() / "Library" / "Application Support" / "Kodi"

# Set by launch(); used in stop() for zombie-aware wait.
_process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]

# ---------------------------------------------------------------------------
# Path safety helpers
# ---------------------------------------------------------------------------


def _inside(child: Path, parent: Path) -> bool:
    """True if child equals parent or is nested inside it (both resolved)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _overlaps(a: Path, b: Path) -> bool:
    """True if a is inside b, b is inside a, or they are the same path."""
    return _inside(a, b) or _inside(b, a)


# ---------------------------------------------------------------------------
# Isolation check — must pass before any mutating operation
# ---------------------------------------------------------------------------


def verify_isolation() -> None:
    """Raise RuntimeError if disposable paths would overlap the real profile.

    Called by reset, install, configure_webserver, and launch before they
    touch the filesystem or spawn a process. Fails closed on any violation.
    """
    if ROOT.resolve() == Path("/").resolve():
        raise RuntimeError("ROOT must not be the filesystem root")
    if not _inside(ROOT, PROJECT):
        raise RuntimeError(
            f"Safety: ROOT {ROOT} is not inside PROJECT {PROJECT}"
        )
    if not _inside(HOME, ROOT):
        raise RuntimeError(
            f"Safety: HOME {HOME} is not inside ROOT {ROOT}"
        )
    if not _inside(KODI_APPDATA_DIR, HOME):
        raise RuntimeError(
            f"Safety: KODI_APPDATA_DIR {KODI_APPDATA_DIR} is not inside HOME {HOME}"
        )
    if _overlaps(KODI_APPDATA_DIR, NORMAL_APPDATA_DIR):
        raise RuntimeError(
            f"Safety: disposable profile {KODI_APPDATA_DIR} "
            f"overlaps real profile {NORMAL_APPDATA_DIR}"
        )


# ---------------------------------------------------------------------------
# Environment override
# ---------------------------------------------------------------------------


def _env() -> Dict[str, str]:
    """Return an env dict with HOME pointing to the disposable root."""
    env = dict(os.environ)
    env["HOME"] = str(HOME)
    env.pop("KODI_HOME", None)
    return env


# ---------------------------------------------------------------------------
# PID file
# ---------------------------------------------------------------------------


def _read_pid() -> Optional[int]:
    try:
        return int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _write_pid(pid: int) -> None:
    PID_FILE.write_text(str(pid))


def _clear_pid() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but is not ours


def _pid_is_kodi(pid: int) -> bool:
    """True if the process with this PID is the Kodi binary."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        name = result.stdout.strip()
        return name == "Kodi" or name == str(KODI)
    except (subprocess.SubprocessError, OSError):
        return False


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def status() -> Dict[str, Any]:
    """Return a dict describing current harness state (non-mutating)."""
    pid = _read_pid()
    running = False
    if pid is not None:
        if _pid_is_alive(pid):
            running = True
        else:
            _clear_pid()
            pid = None
    return {
        "running": running,
        "pid": pid,
        "root": str(ROOT),
        "home": str(HOME),
        "kodi_appdata": str(KODI_APPDATA_DIR),
        "addon_installed": (KODI_ADDONS_DIR / ADDON_ID).is_dir(),
        "webserver_configured": (KODI_USERDATA_DIR / "guisettings.xml").is_file(),
        "log": str(KODI_LOG_FILE),
    }


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def reset() -> None:
    """Remove the disposable profile root and recreate it with an empty structure."""
    verify_isolation()
    current = status()
    if current["running"]:
        stop()
    if ROOT.exists():
        # Extra guard: double-check before rmtree
        if not _inside(ROOT, PROJECT):
            raise RuntimeError(
                f"Safety: refusing rmtree — ROOT {ROOT} is not inside PROJECT {PROJECT}"
            )
        shutil.rmtree(ROOT)
    for directory in (
        ROOT,
        HOME,
        KODI_APPDATA_DIR,
        KODI_USERDATA_DIR,
        KODI_ADDONS_DIR,
        HOME / "Library" / "Logs",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    print(f"reset: disposable profile created at {ROOT}")


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def _verify_source(source: Path) -> None:
    """Raise ValueError if source is not a valid script.build.manager directory."""
    if not source.is_dir():
        raise ValueError(f"Source {source} is not a directory")
    addon_xml = source / "addon.xml"
    if not addon_xml.is_file():
        raise ValueError(f"Source {source} has no addon.xml")
    content = addon_xml.read_text(encoding="utf-8")
    if f'id="{ADDON_ID}"' not in content:
        raise ValueError(
            f"Source addon.xml does not declare addon id={ADDON_ID!r}"
        )


def _copy_addon_files(source: Path, target: Path) -> None:
    """Copy only the add-on distribution files (ADDON_INCLUDE) into target."""
    target.mkdir(parents=True, exist_ok=True)
    for name in sorted(ADDON_INCLUDE):
        src = source / name
        dst = target / name
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        elif src.is_file():
            shutil.copy2(src, dst)


def install(source: Optional[Path] = None) -> None:
    """Copy script.build.manager into the disposable Kodi add-on folder.

    The source defaults to PROJECT (the repo root), which contains addon.xml.
    Only files in ADDON_INCLUDE are copied — tests, tools, and docs are excluded.
    """
    verify_isolation()
    if source is None:
        source = PROJECT
    source = Path(source).resolve()
    _verify_source(source)
    if not KODI_ADDONS_DIR.is_dir():
        raise RuntimeError(
            "Disposable add-on folder not found — run reset first"
        )
    target = KODI_ADDONS_DIR / ADDON_ID
    if target.exists():
        shutil.rmtree(target)
    _copy_addon_files(source, target)
    print(f"install: {ADDON_ID} → {target}")


# ---------------------------------------------------------------------------
# Webserver configuration
# ---------------------------------------------------------------------------


_GUISETTINGS_XML = """\
<settings version="2">
  <setting id="services.webserver">true</setting>
  <setting id="services.webserverport">{port}</setting>
  <setting id="services.webserverusername">{username}</setting>
  <setting id="services.webserverpassword">{password}</setting>
  <setting id="services.zeroconf">false</setting>
</settings>
"""


def configure_webserver(
    port: int = WEBSERVER_PORT,
    username: str = WEBSERVER_USERNAME,
    password: str = WEBSERVER_PASSWORD,
) -> None:
    """Write guisettings.xml to enable the JSON-RPC web server.

    Must be called before launch. Raises RuntimeError if guisettings.xml
    already exists (run reset first to start clean).
    """
    verify_isolation()
    if not KODI_USERDATA_DIR.is_dir():
        raise RuntimeError(
            "Disposable userdata folder not found — run reset first"
        )
    settings_file = KODI_USERDATA_DIR / "guisettings.xml"
    if settings_file.exists():
        raise RuntimeError(
            f"guisettings.xml already exists at {settings_file}; "
            f"run reset to start fresh"
        )
    settings_file.write_text(
        _GUISETTINGS_XML.format(port=port, username=username, password=password),
        encoding="utf-8",
    )
    print(f"configure: web server on port {port} (user: {username!r})")


# ---------------------------------------------------------------------------
# Launch and stop
# ---------------------------------------------------------------------------


def launch() -> int:
    """Start Kodi against the disposable profile. Returns the PID."""
    global _process
    verify_isolation()
    if not KODI.is_file():
        raise RuntimeError(f"Kodi binary not found at {KODI}")
    existing_pid = _read_pid()
    if existing_pid is not None and _pid_is_alive(existing_pid):
        raise RuntimeError(
            f"Kodi is already running (pid {existing_pid})"
        )
    _process = subprocess.Popen(
        [str(KODI)],
        env=_env(),
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _write_pid(_process.pid)
    print(f"launch: Kodi started (pid {_process.pid})")
    return _process.pid


def stop(timeout: float = 30.0) -> None:
    """Send SIGTERM to the disposable Kodi process and wait for it to exit."""
    global _process
    pid = _read_pid()
    if pid is None:
        print("stop: Kodi is not running (no PID file)")
        return
    if not _pid_is_alive(pid):
        print(f"stop: Kodi (pid {pid}) has already exited")
        _clear_pid()
        _process = None
        return
    if not _pid_is_kodi(pid):
        raise RuntimeError(
            f"Safety: PID {pid} does not appear to be Kodi — refusing to stop it"
        )
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _clear_pid()
        _process = None
        return
    # Zombie-aware wait: if we own the process via _process, use wait() so the
    # kernel can reap the child immediately. Otherwise poll _pid_is_alive().
    if _process is not None and _process.pid == pid:
        try:
            _process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.kill(pid, signal.SIGKILL)
            _process.wait(timeout=5)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _pid_is_alive(pid):
                break
            time.sleep(0.2)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    _clear_pid()
    _process = None
    print(f"stop: Kodi (pid {pid}) stopped")


def restart() -> int:
    """Stop any running disposable Kodi and launch it again."""
    stop()
    return launch()


# ---------------------------------------------------------------------------
# JSON-RPC over HTTP
# ---------------------------------------------------------------------------


def jsonrpc(
    method: str,
    params: Optional[Dict[str, Any]] = None,
    port: int = WEBSERVER_PORT,
    username: str = WEBSERVER_USERNAME,
    password: str = WEBSERVER_PASSWORD,
) -> Any:
    """Make a JSON-RPC call to the disposable Kodi over HTTP.

    Returns the 'result' field from the response.
    Raises urllib.error.URLError on network failure, RuntimeError on JSON-RPC error.
    Always targets 127.0.0.1 — never a user-supplied host.
    """
    url = f"http://127.0.0.1:{port}/jsonrpc"
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params if params is not None else {},
        "id": 1,
    }).encode("utf-8")
    auth_b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_b64}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"JSON-RPC error from {method}: {body['error']}")
    return body.get("result")


def wait_for_ready(timeout: float = 60.0, interval: float = 0.5) -> None:
    """Poll JSONRPC.Ping until Kodi responds 'pong', or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    last_exc: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            result = jsonrpc("JSONRPC.Ping")
            if result == "pong":
                print("wait: Kodi ready (JSONRPC.Ping → 'pong')")
                return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        time.sleep(interval)
    msg = f"Kodi did not respond within {timeout}s"
    if last_exc is not None:
        msg += f" (last error: {last_exc})"
    raise TimeoutError(msg)


# ---------------------------------------------------------------------------
# Inspect — query disposable Kodi state via HTTP JSON-RPC
# ---------------------------------------------------------------------------

_INSPECT_PLATFORM_BOOLEANS: Dict[str, str] = {
    "tvos":    "System.Platform.tvOS",
    "android": "System.Platform.Android",
    "macos":   "System.Platform.OSX",
    "ios":     "System.Platform.iOS",
    "windows": "System.Platform.Windows",
    "linux":   "System.Platform.Linux",
}
_INSPECT_PLATFORM_PRECEDENCE = ("tvos", "android", "macos", "ios", "windows", "linux")


def inspect() -> Dict[str, Any]:
    """Query disposable Kodi state via HTTP JSON-RPC.

    Returns a dict with platform, kodi_version, active_skin, addon_count,
    and the raw addons list. Read-only — no Kodi state is mutated.
    """
    # Platform flags
    flags_result = jsonrpc(
        "XBMC.GetInfoBooleans",
        {"booleans": list(_INSPECT_PLATFORM_BOOLEANS.values())},
    )
    platform = "unknown"
    if isinstance(flags_result, dict):
        for pid in _INSPECT_PLATFORM_PRECEDENCE:
            cond = _INSPECT_PLATFORM_BOOLEANS[pid]
            if bool(flags_result.get(cond, False)):
                platform = pid
                break

    # Kodi version
    kodi_version = ""
    version_result = jsonrpc("Application.GetProperties", {"properties": ["version"]})
    if isinstance(version_result, dict):
        ver = version_result.get("version", {})
        if isinstance(ver, dict):
            major = ver.get("major")
            minor = ver.get("minor")
            if (
                isinstance(major, int) and not isinstance(major, bool)
                and isinstance(minor, int) and not isinstance(minor, bool)
            ):
                kodi_version = f"{major}.{minor}"

    # Active skin
    active_skin = ""
    skin_result = jsonrpc("Settings.GetSettingValue", {"setting": "lookandfeel.skin"})
    if isinstance(skin_result, dict):
        val = skin_result.get("value", "")
        if isinstance(val, str) and val.startswith("skin."):
            active_skin = val

    # Installed add-ons
    addons: List[Dict[str, Any]] = []
    addons_result = jsonrpc("Addons.GetAddons", {
        "installed": True,
        "properties": ["enabled", "version"],
    })
    if isinstance(addons_result, dict):
        raw = addons_result.get("addons", [])
        if isinstance(raw, list):
            addons = raw

    return {
        "platform": platform,
        "kodi_version": kodi_version,
        "active_skin": active_skin,
        "addon_count": len(addons),
        "addons": addons,
    }


# ---------------------------------------------------------------------------
# Live validation sequence
# ---------------------------------------------------------------------------


def validate() -> None:
    """Full live validation: reset → install → configure → launch → wait →
    verify JSON-RPC → verify add-on visible → inspect → stop → confirm exit
    → confirm real profile untouched.
    """
    print("=== Build Manager Kodi harness live validation ===")
    verify_isolation()

    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    print("\n[1/11] reset")
    reset()

    print("\n[2/11] install")
    install()

    print("\n[3/11] configure web server")
    configure_webserver()

    print("\n[4/11] launch")
    launch()

    print("\n[5/11] wait for ready (up to 90s)")
    try:
        wait_for_ready(timeout=90.0)
    except TimeoutError as exc:
        stop()
        raise RuntimeError(f"Validation failed at step 5: {exc}") from exc

    print("\n[6/11] verify JSONRPC.Ping")
    ping = jsonrpc("JSONRPC.Ping")
    if ping != "pong":
        stop()
        raise RuntimeError(f"Validation failed: JSONRPC.Ping returned {ping!r}")
    print(f"  JSONRPC.Ping → {ping!r} ✓")

    print("\n[7/11] verify Build Manager add-on is visible")
    try:
        addon_details = jsonrpc("Addons.GetAddonDetails", {
            "addonid": ADDON_ID,
            "properties": ["enabled", "version"],
        })
    except RuntimeError as exc:
        stop()
        raise RuntimeError(
            f"Validation failed: {ADDON_ID} not found via JSON-RPC: {exc}"
        ) from exc
    if not isinstance(addon_details, dict) or "addon" not in addon_details:
        stop()
        raise RuntimeError(
            f"Validation failed: unexpected Addons.GetAddonDetails response: {addon_details!r}"
        )
    addon_info = addon_details["addon"]
    print(
        f"  {ADDON_ID}: enabled={addon_info.get('enabled')!r}, "
        f"version={addon_info.get('version')!r} ✓"
    )

    print("\n[8/11] inspect Kodi state")
    state = inspect()
    print(f"  platform={state['platform']!r}, kodi_version={state['kodi_version']!r}")
    print(f"  active_skin={state['active_skin']!r}, addon_count={state['addon_count']}")

    print("\n[9/11] stop")
    stop()

    print("\n[10/11] confirm Kodi process exited")
    remaining_pid = _read_pid()
    if remaining_pid is not None:
        stop()
        raise RuntimeError(f"Validation failed: PID file still present after stop ({remaining_pid})")
    print("  PID file cleared ✓")

    print("\n[11/11] confirm real profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! "
                f"Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== Validation PASSED ===\n")


# ---------------------------------------------------------------------------
# Repository validation support (BM-010)
# ---------------------------------------------------------------------------

_TEST_REPO_ADDON_ID = "repository.build-manager-test"
_REPO_SERVER_PORT = 8921  # distinct from WEBSERVER_PORT (8920)


def _make_test_repo_zip() -> bytes:
    """Build a minimal valid repository ZIP for live validation.

    The ZIP contains repository.build-manager-test/addon.xml declaring the
    xbmc.addon.repository extension. This is the minimum Kodi requires to
    recognize an add-on as a repository.
    """
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_TEST_REPO_ADDON_ID}" name="Build Manager Test Repo"'
        ' version="1.0.0" provider-name="Build Manager">'
        '<extension point="xbmc.addon.repository" name="Build Manager Test"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Disposable test repository for BM-010 validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_TEST_REPO_ADDON_ID}/addon.xml", addon_xml.encode("utf-8"))
    return buf.getvalue()


class _HttpRepositoryBackend:
    """Repository backend for live validation. Uses HTTP JSON-RPC + filesystem.

    This backend is used only by validate_repo() in the disposable harness.
    It is never imported by production code.

    trigger_addon_scan() restarts Kodi (stop → launch → wait_for_ready) because
    UpdateLocalAddons is a Kodi GUI builtin not accessible via HTTP JSON-RPC.
    """

    def get_installed_addon_ids(self) -> FrozenSet[str]:
        req = {
            "jsonrpc": "2.0",
            "method": "Addons.GetAddons",
            "params": {"installed": True, "properties": ["enabled"]},
            "id": 1,
        }
        resp = jsonrpc("Addons.GetAddons", {"installed": True, "properties": ["enabled"]})
        if not isinstance(resp, dict):
            return frozenset()
        addons = resp.get("addons", [])
        if not isinstance(addons, list):
            return frozenset()
        return frozenset(
            a["addonid"]
            for a in addons
            if isinstance(a, dict) and "addonid" in a
        )

    def download_artifact(
        self,
        url: str,
        *,
        max_bytes: int = 50 * 1024 * 1024,
        timeout: float = 30.0,
    ) -> bytes:
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))
        from resources.lib.repository import _download_artifact
        return _download_artifact(url, max_bytes=max_bytes, timeout=timeout)

    def install_zip_to_addons(self, addon_id: str, zip_bytes: bytes) -> None:
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))
        from resources.lib.repository import RepositoryInstallError, _extract_zip_to_directory
        target = KODI_ADDONS_DIR / addon_id
        if target.exists():
            raise RepositoryInstallError(
                f"Target directory already exists: {target} (harness: manual cleanup required)"
            )
        tmp_dir: Optional[Path] = None
        try:
            tmp_dir = Path(tempfile.mkdtemp(dir=KODI_ADDONS_DIR))
            _extract_zip_to_directory(zip_bytes, addon_id, tmp_dir)
            has_files = any(p.is_file() for p in tmp_dir.rglob("*"))
            if not has_files:
                raise RepositoryInstallError(f"ZIP extraction produced no files for {addon_id!r}")
            os.rename(str(tmp_dir), str(target))
            tmp_dir = None
        except Exception:
            if tmp_dir is not None and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def trigger_addon_scan(self) -> None:
        print("    trigger_addon_scan: restart Kodi to run UpdateLocalAddons")
        stop()
        launch()
        wait_for_ready(timeout=90.0)

    def enable_addon(self, addon_id: str) -> None:
        _ENABLE_WAIT = 30.0
        deadline = time.monotonic() + _ENABLE_WAIT
        while time.monotonic() < deadline:
            if addon_id in self.get_installed_addon_ids():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(
                f"{addon_id!r} not registered in Kodi database after {_ENABLE_WAIT:.0f}s "
                f"(UpdateLocalAddons may not have run)"
            )
        result = jsonrpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": True})
        print(f"    enable_addon({addon_id!r}): SetAddonEnabled → {result!r}")

    def poll_addon_installed(
        self,
        addon_id: str,
        *,
        timeout: float = 60.0,
        interval: float = 1.0,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = jsonrpc("Addons.GetAddonDetails", {
                    "addonid": addon_id,
                    "properties": ["enabled"],
                })
                if isinstance(resp, dict):
                    addon = resp.get("addon", {})
                    if isinstance(addon, dict) and addon.get("enabled") is True:
                        return True
            except RuntimeError:
                pass
            time.sleep(interval)
        return False


class _SingleFileHandler(http.server.BaseHTTPRequestHandler):
    """Serve a single static file at any path. Binds only to 127.0.0.1."""

    _data: bytes = b""
    _content_type: str = "application/zip"

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", self._content_type)
        self.send_header("Content-Length", str(len(self._data)))
        self.end_headers()
        self.wfile.write(self._data)

    def log_message(self, fmt, *args):  # suppress request logging
        pass


def validate_repo() -> None:
    """Live validation of BM-010 repository detection and installation (corrected).

    Sequence (13 steps):
     1  Reset disposable harness
     2  Install Build Manager
     3  Configure web server
     4  Launch Kodi
     5  Wait for ready
     6  Create ZIP + start HTTP server + verify NOT installed
     7  Install repository via corrected mechanism
     8  Verify result.status = INSTALLED and is_installed() = True
     9  Restart disposable Kodi + wait for ready
    10  Verify repository still installed and enabled after restart
    11  Install again → verify ALREADY_INSTALLED (no mutation)
    12  Stop Kodi + shut down HTTP server
    13  Confirm real Kodi profile untouched

    ALL mutation occurs only in the disposable .kodi-test environment.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.manifest import Repository
    from resources.lib.repository import RepositoryManager, RepositoryStatus

    print("=== Build Manager BM-010-R live validation: repository detection/install ===")
    verify_isolation()

    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    print("\n[1/13] reset")
    reset()

    print("\n[2/13] install Build Manager")
    install()

    print("\n[3/13] configure web server")
    configure_webserver()

    print("\n[4/13] launch Kodi")
    launch()

    print("\n[5/13] wait for ready (up to 90s)")
    try:
        wait_for_ready(timeout=90.0)
    except TimeoutError as exc:
        stop()
        raise RuntimeError(f"Validation failed at step 5: {exc}") from exc

    print("\n[6/13] create ZIP + start HTTP server + verify NOT installed")
    zip_bytes = _make_test_repo_zip()
    print(f"  {_TEST_REPO_ADDON_ID}: {len(zip_bytes)} bytes")

    class _Handler(_SingleFileHandler):
        _data = zip_bytes  # type: ignore[assignment]

    server = http.server.HTTPServer(("127.0.0.1", _REPO_SERVER_PORT), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    repo_url = f"http://127.0.0.1:{_REPO_SERVER_PORT}/{_TEST_REPO_ADDON_ID}.zip"
    print(f"  serving {repo_url}")

    try:
        backend = _HttpRepositoryBackend()
        mgr = RepositoryManager(backend)
        test_repo = Repository(addon_id=_TEST_REPO_ADDON_ID, bootstrap_url=repo_url)

        before = mgr.is_installed(_TEST_REPO_ADDON_ID)
        if before:
            stop()
            raise RuntimeError(
                f"Validation failed: {_TEST_REPO_ADDON_ID!r} already installed before test"
            )
        print(f"  is_installed({_TEST_REPO_ADDON_ID!r}) = False ✓")

        print("\n[7/13] install repository via corrected mechanism")
        result = mgr.install(test_repo)
        print(f"  result.status = {result.status.value!r}")
        print(f"  result.message = {result.message!r}")

        print("\n[8/13] verify result.status = INSTALLED and is_installed() = True")
        if result.status != RepositoryStatus.INSTALLED:
            stop()
            raise RuntimeError(
                f"Validation failed: install returned {result.status.value!r} "
                f"— {result.message}"
            )
        print("  status = INSTALLED ✓")
        after = mgr.is_installed(_TEST_REPO_ADDON_ID)
        if not after:
            stop()
            raise RuntimeError(
                f"Validation failed: {_TEST_REPO_ADDON_ID!r} not detected after install"
            )
        print(f"  is_installed({_TEST_REPO_ADDON_ID!r}) = True ✓")

        print("\n[9/13] restart disposable Kodi + wait for ready")
        stop()
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            raise RuntimeError(f"Validation failed at step 9: {exc}") from exc
        print("  Kodi restarted ✓")

        print("\n[10/13] verify repository still installed and enabled after restart")
        after_restart = mgr.is_installed(_TEST_REPO_ADDON_ID)
        if not after_restart:
            stop()
            raise RuntimeError(
                f"Validation failed: {_TEST_REPO_ADDON_ID!r} not present after restart "
                f"(enabled=1 did not persist)"
            )
        print(f"  is_installed({_TEST_REPO_ADDON_ID!r}) = True after restart ✓")
        try:
            details_resp = jsonrpc("Addons.GetAddonDetails", {
                "addonid": _TEST_REPO_ADDON_ID,
                "properties": ["enabled"],
            })
            addon_info = details_resp.get("addon", {}) if isinstance(details_resp, dict) else {}
            enabled_after_restart = addon_info.get("enabled") is True
        except RuntimeError:
            enabled_after_restart = False
        if not enabled_after_restart:
            stop()
            raise RuntimeError(
                f"Validation failed: {_TEST_REPO_ADDON_ID!r} exists after restart "
                f"but enabled=False (SetAddonEnabled did not persist)"
            )
        print(f"  enabled=True after restart ✓")

        print("\n[11/13] install again → verify ALREADY_INSTALLED (no mutation)")
        result2 = mgr.install(test_repo)
        print(f"  result.status = {result2.status.value!r}")
        if result2.status != RepositoryStatus.ALREADY_INSTALLED:
            stop()
            raise RuntimeError(
                f"Validation failed: second install returned {result2.status.value!r} "
                f"instead of already_installed"
            )
        print("  status = ALREADY_INSTALLED ✓ (no mutation)")

    finally:
        print("\n[12/13] stop Kodi + shut down HTTP server")
        try:
            stop()
        except RuntimeError:
            pass
        server.shutdown()

    print("\n[13/13] confirm real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! "
                f"Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-010-R validation PASSED ===\n")


# ---------------------------------------------------------------------------
# Add-on installation validation support (BM-011)
# ---------------------------------------------------------------------------

_ADDON_SERVER_PORT = 8922           # distinct from Kodi (8920) and BM-010 repo (8921)
_BM011_TEST_ADDON_ID = "script.module.build-manager-test"
_BM011_TEST_ADDON_VERSION = "1.0.0"
_BM011_TEST_ADDON_ID_B = "script.module.build-manager-test-b"
_BM011_TEST_ADDON_VERSION_B = "1.0.0"
_HARNESS_TRIGGER_ADDON_ID = "script.build-manager-harness-trigger"
_HARNESS_TRIGGER_VERSION = "1.0.0"


def _make_bm011_test_addon_zip() -> bytes:
    """Build a minimal valid test add-on ZIP for BM-011 live validation.

    Creates script.module.build-manager-test as an xbmc.python.module add-on.
    The ZIP contains only addon.xml and lib/__init__.py — no execution required.
    """
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_BM011_TEST_ADDON_ID}"'
        f' name="Build Manager Test Module"'
        f' version="{_BM011_TEST_ADDON_VERSION}"'
        f' provider-name="Build Manager">'
        '<extension point="xbmc.python.module" library="lib"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Disposable test module for BM-011 validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM011_TEST_ADDON_ID}/addon.xml", addon_xml.encode("utf-8"))
        zf.writestr(f"{_BM011_TEST_ADDON_ID}/lib/__init__.py", b"")
    return buf.getvalue()


def _make_bm011_test_addon_b_zip() -> bytes:
    """Build a minimal valid test add-on ZIP for BM-011 disabled-path validation.

    Creates script.module.build-manager-test-b as an xbmc.python.module add-on.
    Used to prove desired_state='disabled' installs and leaves the addon disabled.
    """
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_BM011_TEST_ADDON_ID_B}"'
        f' name="Build Manager Test Module B"'
        f' version="{_BM011_TEST_ADDON_VERSION_B}"'
        f' provider-name="Build Manager">'
        '<extension point="xbmc.python.module" library="lib"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Disposable test module B for BM-011 disabled-path validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM011_TEST_ADDON_ID_B}/addon.xml", addon_xml.encode("utf-8"))
        zf.writestr(f"{_BM011_TEST_ADDON_ID_B}/lib/__init__.py", b"")
    return buf.getvalue()


def _make_bm011_addons_xml() -> bytes:
    """Build the addons.xml repository index listing both test add-ons."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<addons>\n'
        f'  <addon id="{_BM011_TEST_ADDON_ID}"'
        f' name="Build Manager Test Module"'
        f' version="{_BM011_TEST_ADDON_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <extension point="xbmc.python.module" library="lib"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">Disposable test module for BM-011 validation</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        f'  <addon id="{_BM011_TEST_ADDON_ID_B}"'
        f' name="Build Manager Test Module B"'
        f' version="{_BM011_TEST_ADDON_VERSION_B}"'
        f' provider-name="Build Manager">\n'
        '    <extension point="xbmc.python.module" library="lib"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">Disposable test module B for BM-011 disabled-path validation</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        '</addons>\n'
    ).encode("utf-8")


def _make_bm011_repo_zip(server_port: int) -> bytes:
    """Build the test repository ZIP for BM-011, with info/datadir URLs pointing to localhost.

    Kodi 21 requires the Kodi 19+ <dir> schema for repository addons. The older
    flat <info>/<datadir>/<checksum> format was dropped in Kodi 21 and causes:
      "uses old schema definition ... This is no longer supported"
    Each <dir> element carries the URL set for one Kodi version range (minversion).
    Without minversion/maxversion, the dir applies to all Kodi versions.

    zip="true" on <datadir> means addon ZIPs are served at:
      {datadir}/{addon_id}/{version}/{addon_id}-{version}.zip
    which matches how our HTTP server exposes the test addon ZIP.
    """
    base_url = f"http://127.0.0.1:{server_port}"
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_TEST_REPO_ADDON_ID}"'
        ' name="Build Manager Test Repo"'
        ' version="2.0.0"'
        ' provider-name="Build Manager">'
        f'<extension point="xbmc.addon.repository" name="Build Manager Test">'
        '<dir>'
        f'<info compressed="false">{base_url}/addons.xml</info>'
        f'<checksum>{base_url}/addons.xml.md5</checksum>'
        f'<datadir zip="true">{base_url}</datadir>'
        '</dir>'
        '</extension>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Disposable test repository for BM-011 validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_TEST_REPO_ADDON_ID}/addon.xml", addon_xml.encode("utf-8"))
    return buf.getvalue()


def _install_harness_trigger_script() -> None:
    """Write the harness trigger script directly into the disposable addons dir.

    This tiny script addon is harness-only — it is never installed in production.
    It accepts an add-on ID as sys.argv[2] and calls xbmc.executebuiltin
    ("InstallAddon(addon_id)"). The harness invokes it via Addons.ExecuteAddon
    to trigger Kodi's normal repository-backed install flow.

    The trigger is written before Kodi starts. After Kodi launches (or restarts
    via trigger_addon_scan), it registers the script via UpdateLocalAddons/
    SyncInstalled, making it available for Addons.ExecuteAddon calls.
    """
    verify_isolation()
    target = KODI_ADDONS_DIR / _HARNESS_TRIGGER_ADDON_ID
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_HARNESS_TRIGGER_ADDON_ID}"'
        ' name="Build Manager Harness Trigger"'
        f' version="{_HARNESS_TRIGGER_VERSION}"'
        ' provider-name="Build Manager">'
        '<extension point="xbmc.python.script" library="default.py"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Harness-only trigger for BM-011 live validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    (target / "addon.xml").write_text(addon_xml, encoding="utf-8")

    # Supports two commands via sys.argv[2]:
    #   "update_repos" → UpdateAddonRepos (force repo scan after enabling a repo)
    #   "<addon_id>"   → InstallAddon(<addon_id>) (production KodiRuntime path)
    trigger_py = (
        "import sys\n"
        "import xbmc\n"
        "param = sys.argv[2] if len(sys.argv) > 2 else ''\n"
        "if param == 'update_repos':\n"
        "    xbmc.executebuiltin('UpdateAddonRepos')\n"
        "elif param:\n"
        "    xbmc.executebuiltin('InstallAddon(' + param + ')')\n"
    )
    (target / "default.py").write_text(trigger_py, encoding="utf-8")
    print(f"  harness trigger script written to {target}")


class _MultiFileHandler(http.server.BaseHTTPRequestHandler):
    """Serve multiple static files by path. Binds only to 127.0.0.1.

    Class-level _files dict maps URL path → bytes. Paths not in the dict
    return 404. Content-Type is inferred from the path extension.
    """

    _files: Dict[str, bytes] = {}

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        data = self._files.get(path)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        if path.endswith(".xml") or path.endswith(".md5"):
            content_type = "application/xml"
        else:
            content_type = "application/zip"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args) -> None:
        import sys
        port = self.server.server_address[1]
        print(f"  [http:{port}] {fmt % args}", file=sys.stderr, flush=True)


class _HttpAddonBackend:
    """Add-on backend for BM-011 live validation. Mirrors the production algorithm.

    invoke_install() uses the same constrained package-install fallback as
    KodiRuntimeAddonBackend:
      1. Resolve ZIP URL from installed+enabled repository metadata
      2. Download ZIP via HTTP (using _fetch_bytes from resources.lib.addons)
      3. Validate ZIP (using _validate_addon_zip from resources.lib.addons)
      4. Staged extract → atomic rename (using _staged_install)
      5. Restart Kodi (harness substitute for UpdateLocalAddons builtin)

    set_addon_enabled() is separate — called by AddonManager.install() after poll.

    The only harness-specific difference from production:
      - Production calls xbmc.executebuiltin("UpdateLocalAddons") for discovery.
      - Harness calls stop() + launch() + wait_for_ready() instead, which achieves
        the same result (Kodi discovers newly placed addons at startup).
    """

    def _ensure_project_in_sys_path(self) -> None:
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))

    def get_addon_details(self, addon_id: str) -> Optional["InstalledAddonInfo"]:
        self._ensure_project_in_sys_path()
        from resources.lib.addons import InstalledAddonInfo
        try:
            resp = jsonrpc("Addons.GetAddonDetails", {
                "addonid": addon_id,
                "properties": ["enabled", "version"],
            })
            if not isinstance(resp, dict):
                return None
            addon = resp.get("addon", {})
            if not isinstance(addon, dict) or addon.get("addonid") != addon_id:
                return None
            return InstalledAddonInfo(
                addon_id=addon_id,
                enabled=bool(addon.get("enabled", False)),
                version=str(addon.get("version", "")),
            )
        except RuntimeError:
            return None

    def _resolve_package_url(self, addon_id: str) -> tuple:
        """Resolve addon_id in installed+enabled repos. Returns (zip_url, version).

        Mirrors KodiRuntimeAddonBackend._resolve_package_url but uses:
          - jsonrpc() HTTP calls instead of xbmc.executeJSONRPC
          - Direct filesystem reads instead of xbmcvfs.File
          - Same _fetch_bytes for addons.xml download
          - Same URL construction logic
        """
        self._ensure_project_in_sys_path()
        import xml.etree.ElementTree as ET
        from resources.lib.addons import (
            AddonInstallError, _fetch_bytes, _validate_url,
            _MAX_ADDONS_XML_BYTES,
        )

        # Get all installed repository add-ons
        try:
            repos_resp = jsonrpc("Addons.GetAddons", {
                "type": "xbmc.addon.repository",
                "installed": True,
            })
        except RuntimeError as exc:
            raise AddonInstallError(
                f"Addons.GetAddons(repository) failed: {exc}"
            ) from exc

        if not isinstance(repos_resp, dict):
            raise AddonInstallError(
                f"Addons.GetAddons returned non-dict: {repos_resp!r}"
            )

        addons_list = repos_resp.get("addons") or []
        repo_ids = [
            a["addonid"]
            for a in addons_list
            if isinstance(a, dict) and "addonid" in a
        ]

        if not repo_ids:
            raise AddonInstallError(
                f"No installed repository add-ons; cannot resolve {addon_id!r}"
            )

        for repo_id in repo_ids:
            # Check if repo is enabled
            try:
                det_resp = jsonrpc("Addons.GetAddonDetails", {
                    "addonid": repo_id,
                    "properties": ["enabled"],
                })
            except RuntimeError:
                continue
            repo_detail = det_resp.get("addon", {}) if isinstance(det_resp, dict) else {}
            if not isinstance(repo_detail, dict) or not repo_detail.get("enabled"):
                continue

            # Read repo's addon.xml from the addons filesystem
            addon_xml_path = KODI_ADDONS_DIR / repo_id / "addon.xml"
            try:
                xml_bytes = addon_xml_path.read_bytes()
            except OSError:
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

                    # Fetch and parse addons.xml
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
                            _validate_url(datadir_url,
                                          context=f"{repo_id} <datadir> URL")
                        except AddonInstallError:
                            continue
                        pkg_url = (
                            datadir_url.rstrip("/")
                            + f"/{addon_id}/{version}/{addon_id}-{version}.zip"
                        )
                        print(
                            f"  [resolve] found {addon_id!r} v{version} in {repo_id!r}"
                        )
                        print(f"  [resolve] package URL: {pkg_url}")
                        return pkg_url, version

        raise AddonInstallError(
            f"{addon_id!r} not found in any installed+enabled repository"
        )

    def invoke_install(self, addon_id: str) -> None:
        """Install addon_id via the constrained package-install fallback.

        Mirrors KodiRuntimeAddonBackend.invoke_install exactly, using the
        same shared helpers from resources.lib.addons:
          resolve → _fetch_bytes → _validate_addon_zip → _staged_install

        Harness-specific: restarts Kodi instead of UpdateLocalAddons so that
        FindAddons discovers the newly placed addon directory at startup.
        """
        self._ensure_project_in_sys_path()
        from resources.lib.addons import (
            AddonInstallError, _fetch_bytes, _validate_addon_zip,
            _staged_install, _MAX_ADDON_ZIP_BYTES,
        )

        # 1. Resolve package URL from repository metadata
        pkg_url, version = self._resolve_package_url(addon_id)

        # 2. Download ZIP via HTTP (same _fetch_bytes as production)
        print(f"  [invoke_install] fetching {pkg_url}")
        zip_data = _fetch_bytes(pkg_url, max_bytes=_MAX_ADDON_ZIP_BYTES)
        print(f"  [invoke_install] downloaded {len(zip_data)} bytes")

        # 3. Validate ZIP (same _validate_addon_zip as production)
        found_version = _validate_addon_zip(zip_data, addon_id,
                                            expected_version=version)
        print(f"  [invoke_install] ZIP validated (version={found_version!r})")

        # 4. Staged install (same _staged_install as production)
        target = KODI_ADDONS_DIR / addon_id
        if target.exists():
            raise AddonInstallError(
                f"Target already exists: {addon_id!r} — "
                f"should have been caught by is_installed() check"
            )
        _staged_install(zip_data, addon_id, KODI_ADDONS_DIR)
        print(f"  [invoke_install] staged install complete → {target}")

        # 5. Trigger discovery: restart Kodi (harness substitute for UpdateLocalAddons)
        print("  [invoke_install] restarting Kodi (FindAddons discovers new addon)")
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        print("  [invoke_install] Kodi ready after restart ✓")

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        """Set enabled state of addon_id via Addons.SetAddonEnabled JSON-RPC.

        Called by AddonManager.install() after poll to finalize desired_state.
        SyncInstalled registers newly discovered addons as disabled (enabled=0)
        by default in Kodi 21; this call enables or disables them as requested.
        """
        self._ensure_project_in_sys_path()
        from resources.lib.addons import AddonInstallError
        try:
            jsonrpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": enabled})
        except RuntimeError as exc:
            raise AddonInstallError(
                f"SetAddonEnabled({addon_id!r}, {enabled}) failed: {exc}"
            ) from exc
        print(f"  [set_addon_enabled] {addon_id!r} enabled={enabled} via SetAddonEnabled ✓")

    def poll_addon_installed(
        self,
        addon_id: str,
        *,
        timeout: float = 120.0,
        interval: float = 2.0,
    ) -> Optional["InstalledAddonInfo"]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            info = self.get_addon_details(addon_id)
            if info is not None:
                return info
            time.sleep(interval)
        return None


def _wait_for_addon_in_repo_index(
    addon_id: str,
    timeout: float = 60.0,
    interval: float = 3.0,
) -> bool:
    """Poll until addon_id appears in Kodi's repository index (installed=False).

    Returns True when the add-on is found. Returns False on timeout.
    The repository must already be installed and Kodi must have scanned it.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = jsonrpc("Addons.GetAddons", {"installed": False})
            if isinstance(resp, dict):
                addons = resp.get("addons") or []
                ids = {
                    a["addonid"]
                    for a in addons
                    if isinstance(a, dict) and "addonid" in a
                }
                if addon_id in ids:
                    return True
        except (RuntimeError, Exception):  # noqa: BLE001
            pass
        time.sleep(interval)
    return False


def validate_addon() -> None:
    """Live validation of BM-011 general add-on detection and installation.

    Sequence (19 steps):
     1  Reset disposable harness
     2  Install Build Manager + harness trigger script
     3  Configure web server
     4  Create test content + start HTTP server (127.0.0.1:8922)
     5  Launch Kodi + wait for ready
     6  Verify test add-on A NOT installed before any action
     7  Install test repository via BM-010 RepositoryManager.install
        (includes UpdateLocalAddons restart; trigger script registered)
     8  Wait for Kodi to index the test repository (fetches addons.xml)
     9  Verify test add-on A still NOT installed (available but not installed)
    10  Install addon A via AddonManager.install desired_state='enabled'
    11  Verify result.status == INSTALLED
    12  Verify Addons.GetAddonDetails: addon A installed + enabled
    13  Install addon B via AddonManager.install desired_state='disabled' (proves disabled path)
    14  Verify Addons.GetAddonDetails: addon B installed + enabled=False
    15  Restart disposable Kodi + wait for ready
    16  Verify addon A still enabled + addon B still disabled after restart
    17  Install both again → verify ALREADY_INSTALLED (idempotency)
    18  Stop Kodi + shut down HTTP server
    19  Confirm real Kodi profile untouched

    NOTE on step 10: Both harness and production use the same constrained
    package-install fallback algorithm (resolve → download → validate →
    staged install → discover). _HttpAddonBackend.invoke_install mirrors
    KodiRuntimeAddonBackend.invoke_install using the shared helpers from
    resources.lib.addons (_fetch_bytes, _validate_addon_zip, _staged_install).
    The only harness-specific difference: harness restarts Kodi instead of
    calling UpdateLocalAddons (which is a Kodi builtin unavailable outside Kodi).
    HTTP server logs prove Build Manager's algorithm fetched addons.xml and
    the addon ZIP from the repository.

    ALL mutation occurs only in the disposable .kodi-test environment.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.addons import AddonManager, AddonStatus
    from resources.lib.manifest import Repository
    from resources.lib.repository import RepositoryManager, RepositoryStatus

    print("=== Build Manager BM-011 live validation: general add-on installation ===")
    verify_isolation()

    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    print("\n[1/19] reset")
    reset()

    print("\n[2/19] install Build Manager + harness trigger script")
    install()
    _install_harness_trigger_script()

    print("\n[3/19] configure web server")
    configure_webserver()

    print("\n[4/19] create test content + start HTTP server (127.0.0.1:8922)")
    addon_zip = _make_bm011_test_addon_zip()
    addon_zip_b = _make_bm011_test_addon_b_zip()
    addons_xml = _make_bm011_addons_xml()
    addons_xml_md5 = hashlib.md5(addons_xml).hexdigest().encode("utf-8")
    repo_zip = _make_bm011_repo_zip(_ADDON_SERVER_PORT)
    print(f"  test repo ZIP: {len(repo_zip)} bytes")
    print(f"  addons.xml: {len(addons_xml)} bytes (md5={addons_xml_md5.decode()})")
    print(f"  test addon A ZIP: {len(addon_zip)} bytes")
    print(f"  test addon B ZIP: {len(addon_zip_b)} bytes")

    addon_zip_path = (
        f"/{_BM011_TEST_ADDON_ID}/{_BM011_TEST_ADDON_VERSION}"
        f"/{_BM011_TEST_ADDON_ID}-{_BM011_TEST_ADDON_VERSION}.zip"
    )
    addon_zip_b_path = (
        f"/{_BM011_TEST_ADDON_ID_B}/{_BM011_TEST_ADDON_VERSION_B}"
        f"/{_BM011_TEST_ADDON_ID_B}-{_BM011_TEST_ADDON_VERSION_B}.zip"
    )
    server_files = {
        f"/{_TEST_REPO_ADDON_ID}.zip": repo_zip,
        "/addons.xml": addons_xml,
        "/addons.xml.md5": addons_xml_md5,
        addon_zip_path: addon_zip,
        addon_zip_b_path: addon_zip_b,
    }

    class _Handler(_MultiFileHandler):
        _files = server_files  # type: ignore[assignment]

    server = http.server.HTTPServer(("127.0.0.1", _ADDON_SERVER_PORT), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    repo_url = f"http://127.0.0.1:{_ADDON_SERVER_PORT}/{_TEST_REPO_ADDON_ID}.zip"
    print(f"  HTTP server started: serving {len(server_files)} paths on port {_ADDON_SERVER_PORT}")

    repo_backend = _HttpRepositoryBackend()
    addon_backend = _HttpAddonBackend()
    repo_mgr = RepositoryManager(repo_backend)
    addon_mgr = AddonManager(addon_backend)
    test_repo = Repository(addon_id=_TEST_REPO_ADDON_ID, bootstrap_url=repo_url)

    try:
        print("\n[5/19] launch Kodi + wait for ready (up to 90s)")
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            stop()
            raise RuntimeError(f"Validation failed at step 5: {exc}") from exc

        print("\n[6/19] verify test add-on NOT installed before any action")
        if addon_mgr.is_installed(_BM011_TEST_ADDON_ID):
            stop()
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID!r} already installed before test"
            )
        print(f"  is_installed({_BM011_TEST_ADDON_ID!r}) = False ✓")

        print("\n[7/19] install test repository via BM-010 RepositoryManager.install")
        print("  (trigger_addon_scan restarts Kodi; harness trigger script registered)")
        repo_result = repo_mgr.install(test_repo)
        print(f"  repo result.status = {repo_result.status.value!r}")
        if repo_result.status != RepositoryStatus.INSTALLED:
            raise RuntimeError(
                f"Validation failed: repo install returned {repo_result.status.value!r} "
                f"— {repo_result.message}"
            )
        print(f"  {_TEST_REPO_ADDON_ID!r} installed ✓")
        # Kodi 21's SyncInstalled registers newly-discovered addons as disabled=0.
        # Enable the harness trigger script explicitly so Addons.ExecuteAddon accepts it.
        jsonrpc("Addons.SetAddonEnabled", {
            "addonid": _HARNESS_TRIGGER_ADDON_ID,
            "enabled": True,
        })
        trigger_detail = jsonrpc("Addons.GetAddonDetails", {
            "addonid": _HARNESS_TRIGGER_ADDON_ID,
            "properties": ["enabled"],
        })
        if not (
            isinstance(trigger_detail, dict)
            and isinstance(trigger_detail.get("addon"), dict)
            and trigger_detail["addon"].get("enabled") is True
        ):
            raise RuntimeError(
                f"Validation failed: could not enable harness trigger "
                f"{_HARNESS_TRIGGER_ADDON_ID!r}: {trigger_detail!r}"
            )
        print(f"  harness trigger {_HARNESS_TRIGGER_ADDON_ID!r} enabled ✓")
        # Force an immediate repository scan so Kodi indexes the test addon
        jsonrpc("Addons.ExecuteAddon", {
            "addonid": _HARNESS_TRIGGER_ADDON_ID,
            "params": "update_repos",
            "wait": False,
        })
        print("  triggered UpdateAddonRepos via harness ✓")

        print("\n[8/19] wait for Kodi to index test repository (up to 90s)")
        found = _wait_for_addon_in_repo_index(_BM011_TEST_ADDON_ID, timeout=90.0)
        if found:
            print(f"  {_BM011_TEST_ADDON_ID!r} found in Kodi repo index ✓")
        else:
            print(
                f"  WARNING: {_BM011_TEST_ADDON_ID!r} not yet in Kodi repo index "
                f"after 90s; proceeding (InstallAddon may still succeed)"
            )

        print("\n[9/19] verify test add-on still NOT installed (available, not installed)")
        if addon_mgr.is_installed(_BM011_TEST_ADDON_ID):
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID!r} appeared as installed "
                f"before AddonManager.install was called"
            )
        print(f"  is_installed({_BM011_TEST_ADDON_ID!r}) = False ✓ (available, not installed)")

        print("\n[10/19] install test add-on via AddonManager.install")
        print("  (production algorithm: resolve repo metadata → download → validate → stage → restart)")

        install_result = addon_mgr.install(_BM011_TEST_ADDON_ID, desired_state="enabled")
        print(f"  result.status = {install_result.status.value!r}")
        print(f"  result.enabled = {install_result.enabled!r}")
        print(f"  result.version = {install_result.version!r}")
        print(f"  result.message = {install_result.message!r}")

        print("\n[11/19] verify result.status == INSTALLED")
        if install_result.status != AddonStatus.INSTALLED:
            raise RuntimeError(
                f"Validation failed: install returned {install_result.status.value!r} "
                f"— {install_result.message}"
            )
        print("  status = INSTALLED ✓")

        print("\n[12/19] verify Addons.GetAddonDetails: installed + enabled")
        try:
            details_resp = jsonrpc("Addons.GetAddonDetails", {
                "addonid": _BM011_TEST_ADDON_ID,
                "properties": ["enabled", "version"],
            })
            addon_info = details_resp.get("addon", {}) if isinstance(details_resp, dict) else {}
            api_enabled = addon_info.get("enabled") is True
            api_version = addon_info.get("version", "")
        except RuntimeError as exc:
            raise RuntimeError(
                f"Validation failed: Addons.GetAddonDetails({_BM011_TEST_ADDON_ID!r}) "
                f"raised: {exc}"
            ) from exc
        if not api_enabled:
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID!r} installed but enabled=False"
            )
        print(f"  enabled=True, version={api_version!r} ✓")

        # Confirm files are present in the addons dir (Kodi extracted them)
        addon_dir = KODI_ADDONS_DIR / _BM011_TEST_ADDON_ID
        if not addon_dir.is_dir():
            raise RuntimeError(
                f"Validation failed: add-on directory {addon_dir} not found"
            )
        addon_xml_path = addon_dir / "addon.xml"
        if not addon_xml_path.is_file():
            raise RuntimeError(
                f"Validation failed: {addon_dir}/addon.xml missing"
            )
        print(f"  addon directory present: {addon_dir} ✓")

        print("\n[13/19] install addon B with desired_state='disabled'")
        print("  (proves symmetric finalization: discovered enabled → SetAddonEnabled(False))")
        install_b_result = addon_mgr.install(_BM011_TEST_ADDON_ID_B, desired_state="disabled")
        print(f"  result.status = {install_b_result.status.value!r}")
        print(f"  result.enabled = {install_b_result.enabled!r}")
        print(f"  result.message = {install_b_result.message!r}")
        if install_b_result.status != AddonStatus.INSTALLED:
            raise RuntimeError(
                f"Validation failed: addon B install returned {install_b_result.status.value!r} "
                f"— {install_b_result.message}"
            )
        print(f"  status = INSTALLED ✓")

        print("\n[14/19] verify addon B is installed but disabled (enabled=False)")
        try:
            details_b = jsonrpc("Addons.GetAddonDetails", {
                "addonid": _BM011_TEST_ADDON_ID_B,
                "properties": ["enabled", "version"],
            })
            addon_b_info = details_b.get("addon", {}) if isinstance(details_b, dict) else {}
            b_enabled = addon_b_info.get("enabled")
            b_version = addon_b_info.get("version", "")
        except RuntimeError as exc:
            raise RuntimeError(
                f"Validation failed: Addons.GetAddonDetails({_BM011_TEST_ADDON_ID_B!r}) "
                f"raised: {exc}"
            ) from exc
        if b_enabled is not False:
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID_B!r} expected enabled=False "
                f"but got enabled={b_enabled!r}"
            )
        print(f"  enabled=False, version={b_version!r} ✓ (disabled-path proven)")

        print("\n[15/19] restart disposable Kodi + wait for ready")
        stop()
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            raise RuntimeError(f"Validation failed at step 15: {exc}") from exc
        print("  Kodi restarted ✓")

        print("\n[16/19] verify addon A still enabled + addon B still disabled after restart")
        after_restart = addon_mgr.is_installed(_BM011_TEST_ADDON_ID)
        if not after_restart:
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID!r} not present after restart"
            )
        try:
            details2 = jsonrpc("Addons.GetAddonDetails", {
                "addonid": _BM011_TEST_ADDON_ID,
                "properties": ["enabled"],
            })
            addon_info2 = details2.get("addon", {}) if isinstance(details2, dict) else {}
            enabled_after = addon_info2.get("enabled") is True
        except RuntimeError:
            enabled_after = False
        if not enabled_after:
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID!r} present after restart "
                f"but enabled=False"
            )
        print(f"  addon A: enabled=True after restart ✓")
        # Verify addon B remains disabled after restart
        try:
            details_b2 = jsonrpc("Addons.GetAddonDetails", {
                "addonid": _BM011_TEST_ADDON_ID_B,
                "properties": ["enabled"],
            })
            addon_b2 = details_b2.get("addon", {}) if isinstance(details_b2, dict) else {}
            b_enabled_after = addon_b2.get("enabled")
        except RuntimeError:
            b_enabled_after = None
        if b_enabled_after is not False:
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID_B!r} expected enabled=False "
                f"after restart but got enabled={b_enabled_after!r}"
            )
        print(f"  addon B: enabled=False after restart ✓")

        print("\n[17/19] install both again → verify ALREADY_INSTALLED (idempotency)")
        result2 = addon_mgr.install(_BM011_TEST_ADDON_ID, desired_state="enabled")
        print(f"  addon A result.status = {result2.status.value!r}")
        if result2.status != AddonStatus.ALREADY_INSTALLED:
            raise RuntimeError(
                f"Validation failed: second install of addon A returned {result2.status.value!r} "
                f"instead of already_installed"
            )
        result2b = addon_mgr.install(_BM011_TEST_ADDON_ID_B, desired_state="disabled")
        print(f"  addon B result.status = {result2b.status.value!r}")
        if result2b.status != AddonStatus.ALREADY_INSTALLED:
            raise RuntimeError(
                f"Validation failed: second install of addon B returned {result2b.status.value!r} "
                f"instead of already_installed"
            )
        print("  status = ALREADY_INSTALLED ✓ (no mutation)")

    finally:
        print("\n[18/19] stop Kodi + shut down HTTP server")
        try:
            stop()
        except RuntimeError:
            pass
        server.shutdown()

    print("\n[19/19] confirm real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! "
                f"Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-011-C-final validation PASSED (19/19) ===\n")


# ---------------------------------------------------------------------------
# Dependency closure validation support (BM-012)
# ---------------------------------------------------------------------------

_BM012_ROOT_ID = "plugin.video.bm012-root"
_BM012_ROOT_VERSION = "1.0.0"
_BM012_A_ID = "script.module.bm012-a"
_BM012_A_VERSION = "1.0.0"
_BM012_B_ID = "script.module.bm012-b"
_BM012_B_VERSION = "1.0.0"
_BM012_OPTIONAL_ID = "script.module.bm012-optional"
_BM012_OPTIONAL_VERSION = "1.0.0"


def _make_bm012_root_zip() -> bytes:
    """Build the root add-on ZIP for BM-012 live validation.

    plugin.video.bm012-root has a <requires> block with:
      - script.module.bm012-a  (required) — will be MISSING pre-reconcile
      - script.module.bm012-optional (optional="true") — never installed
    bm012-a in turn requires bm012-b, proving iterative closure (two rounds).
    """
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_BM012_ROOT_ID}"'
        f' name="BM-012 Root Plugin"'
        f' version="{_BM012_ROOT_VERSION}"'
        f' provider-name="Build Manager">'
        '<requires>'
        '<import addon="xbmc.python" version="3.0.0"/>'
        f'<import addon="{_BM012_A_ID}" version="{_BM012_A_VERSION}"/>'
        f'<import addon="{_BM012_OPTIONAL_ID}" version="{_BM012_OPTIONAL_VERSION}"'
        ' optional="true"/>'
        '</requires>'
        '<extension point="xbmc.python.pluginsource" library="default.py"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Root add-on for BM-012 dep closure validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM012_ROOT_ID}/addon.xml", addon_xml.encode("utf-8"))
        zf.writestr(f"{_BM012_ROOT_ID}/default.py", b"")
    return buf.getvalue()


def _make_bm012_a_zip() -> bytes:
    """Build script.module.bm012-a ZIP. Requires bm012-b (transitive dep)."""
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_BM012_A_ID}"'
        f' name="BM-012 Module A"'
        f' version="{_BM012_A_VERSION}"'
        f' provider-name="Build Manager">'
        '<requires>'
        '<import addon="xbmc.python" version="3.0.0"/>'
        f'<import addon="{_BM012_B_ID}" version="{_BM012_B_VERSION}"/>'
        '</requires>'
        '<extension point="xbmc.python.module" library="lib"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Module A for BM-012 dep closure validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM012_A_ID}/addon.xml", addon_xml.encode("utf-8"))
        zf.writestr(f"{_BM012_A_ID}/lib/__init__.py", b"")
    return buf.getvalue()


def _make_bm012_b_zip() -> bytes:
    """Build script.module.bm012-b ZIP. Only requires xbmc.python (SYSTEM)."""
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_BM012_B_ID}"'
        f' name="BM-012 Module B"'
        f' version="{_BM012_B_VERSION}"'
        f' provider-name="Build Manager">'
        '<requires>'
        '<import addon="xbmc.python" version="3.0.0"/>'
        '</requires>'
        '<extension point="xbmc.python.module" library="lib"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Module B for BM-012 dep closure validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM012_B_ID}/addon.xml", addon_xml.encode("utf-8"))
        zf.writestr(f"{_BM012_B_ID}/lib/__init__.py", b"")
    return buf.getvalue()


def _make_bm012_optional_zip() -> bytes:
    """Build script.module.bm012-optional ZIP. Served but never installed.

    Listed in addons.xml and served by the HTTP server to prove the optional
    policy: even though the ZIP is available, DependencyResolver never installs
    add-ons declared with optional="true".
    """
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_BM012_OPTIONAL_ID}"'
        f' name="BM-012 Optional Module"'
        f' version="{_BM012_OPTIONAL_VERSION}"'
        f' provider-name="Build Manager">'
        '<requires>'
        '<import addon="xbmc.python" version="3.0.0"/>'
        '</requires>'
        '<extension point="xbmc.python.module" library="lib"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Optional module for BM-012 dep closure validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM012_OPTIONAL_ID}/addon.xml", addon_xml.encode("utf-8"))
        zf.writestr(f"{_BM012_OPTIONAL_ID}/lib/__init__.py", b"")
    return buf.getvalue()


def _make_bm012_addons_xml() -> bytes:
    """Build the addons.xml index listing all four BM-012 test add-ons."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<addons>\n'
        f'  <addon id="{_BM012_ROOT_ID}"'
        f' name="BM-012 Root Plugin"'
        f' version="{_BM012_ROOT_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        f'      <import addon="{_BM012_A_ID}" version="{_BM012_A_VERSION}"/>\n'
        f'      <import addon="{_BM012_OPTIONAL_ID}" version="{_BM012_OPTIONAL_VERSION}"'
        ' optional="true"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">Root add-on for BM-012 dep closure validation</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        f'  <addon id="{_BM012_A_ID}"'
        f' name="BM-012 Module A"'
        f' version="{_BM012_A_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        f'      <import addon="{_BM012_B_ID}" version="{_BM012_B_VERSION}"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.module" library="lib"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">Module A for BM-012 dep closure validation</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        f'  <addon id="{_BM012_B_ID}"'
        f' name="BM-012 Module B"'
        f' version="{_BM012_B_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.module" library="lib"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">Module B for BM-012 dep closure validation</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        f'  <addon id="{_BM012_OPTIONAL_ID}"'
        f' name="BM-012 Optional Module"'
        f' version="{_BM012_OPTIONAL_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.module" library="lib"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">Optional module for BM-012 dep closure validation</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        '</addons>\n'
    ).encode("utf-8")


class _HttpDependencyBackend:
    """DependencyBackend for BM-012 live validation against disposable Kodi.

    Delegates install_addon() to AddonManager(_HttpAddonBackend()) — the same
    constrained package-install path as KodiRuntimeDependencyBackend.
    Reads addon.xml from the disposable addons filesystem (KODI_ADDONS_DIR).
    Uses _HttpAddonBackend.get_addon_details() and set_addon_enabled() for
    Kodi API calls.

    The only harness-specific differences from production:
      - invoke_install() restarts Kodi (stop + launch + wait_for_ready) instead
        of calling UpdateLocalAddons (a Kodi GUI builtin).
      - read_addon_xml() reads from the filesystem instead of xbmcvfs.File().
    """

    def __init__(self, addon_backend: "_HttpAddonBackend") -> None:
        self._addon_backend = addon_backend

    def _ensure_project_in_sys_path(self) -> None:
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))

    def get_addon_details(self, addon_id: str):
        return self._addon_backend.get_addon_details(addon_id)

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        """Read addon.xml from KODI_ADDONS_DIR/{addon_id}/addon.xml."""
        path = KODI_ADDONS_DIR / addon_id / "addon.xml"
        try:
            return path.read_bytes() if path.exists() else None
        except OSError:
            return None

    def install_addon(self, addon_id: str, desired_state: str = "enabled"):
        """Install via AddonManager(_HttpAddonBackend). Mirrors production."""
        self._ensure_project_in_sys_path()
        from resources.lib.addons import AddonManager
        mgr = AddonManager(self._addon_backend)
        return mgr.install(addon_id, desired_state=desired_state)

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        """Enable/disable via Addons.SetAddonEnabled. Raises DependencyError on failure."""
        self._ensure_project_in_sys_path()
        from resources.lib.dependencies import DependencyError
        try:
            self._addon_backend.set_addon_enabled(addon_id, enabled)
        except Exception as exc:
            raise DependencyError(
                f"set_addon_enabled({addon_id!r}, {enabled}) failed: {exc}"
            ) from exc


def validate_dependencies() -> None:
    """Live validation of BM-012 dependency closure discovery and reconciliation.

    Dependency graph:
      plugin.video.bm012-root
        └── script.module.bm012-a   (required, MISSING pre-reconcile)
              └── script.module.bm012-b   (required, MISSING until round 2)
        └── script.module.bm012-optional (optional="true" — never installed)

    Reconcile rounds:
      Round 1: root is installed+enabled; A is MISSING → install A (restart)
      Round 2: A is installed; B is MISSING → install B (restart)
      Round 3: B is installed → all required satisfied → stable

    Sequence (18 steps):
      1  Reset disposable harness + install Build Manager + configure web server
      2  Build BM-012 test ZIPs + addons.xml + repo ZIP; start HTTP server (127.0.0.1:8922)
      3  Launch Kodi + wait for ready
      4  Verify pre-conditions: bm012-root, bm012-a, bm012-b, bm012-optional not installed
      5  Install test repository via BM-010 RepositoryManager.install
      6  Verify test repository installed + enabled
      7  Install bm012-root via AddonManager.install (desired_state='enabled')
      8  Verify bm012-root installed + enabled; addon.xml readable on filesystem
      9  resolve_closure(['bm012-root']) pre-reconcile — pure read, no mutation
     10  Verify closure: bm012-a = MISSING, bm012-optional = OPTIONAL
     11  reconcile_dependencies(['bm012-root']) — installs A (round 1), then B (round 2)
     12  Verify result.all_required_satisfied = True
     13  Verify actions include INSTALLED 'script.module.bm012-a'
     14  Verify actions include INSTALLED 'script.module.bm012-b'
     15  Verify bm012-optional NOT in INSTALLED actions (optional policy)
     16  Verify Kodi API: bm012-a installed + enabled (Addons.GetAddonDetails)
     17  Verify Kodi API: bm012-b installed + enabled (Addons.GetAddonDetails)
     18  Verify real Kodi profile untouched + stop Kodi + shut down HTTP server

    ALL mutation occurs only in the disposable .kodi-test environment.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.addons import AddonManager, AddonStatus
    from resources.lib.dependencies import DependencyResolver, DependencyStatus
    from resources.lib.manifest import Repository
    from resources.lib.repository import RepositoryManager, RepositoryStatus

    print("=== Build Manager BM-012 live validation: dependency closure ===")
    verify_isolation()

    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    print("\n[1/18] reset disposable harness + install Build Manager + configure web server")
    reset()
    install(source=PROJECT)
    configure_webserver()

    print("\n[2/18] build BM-012 test ZIPs + addons.xml + repo ZIP; start HTTP server")
    root_zip = _make_bm012_root_zip()
    a_zip = _make_bm012_a_zip()
    b_zip = _make_bm012_b_zip()
    optional_zip = _make_bm012_optional_zip()
    addons_xml = _make_bm012_addons_xml()
    addons_xml_md5 = hashlib.md5(addons_xml).hexdigest().encode("utf-8")
    repo_zip = _make_bm011_repo_zip(_ADDON_SERVER_PORT)
    print(f"  repo ZIP: {len(repo_zip)} bytes")
    print(f"  addons.xml: {len(addons_xml)} bytes (md5={addons_xml_md5.decode()})")
    print(f"  bm012-root ZIP: {len(root_zip)} bytes")
    print(f"  bm012-a ZIP: {len(a_zip)} bytes")
    print(f"  bm012-b ZIP: {len(b_zip)} bytes")
    print(f"  bm012-optional ZIP: {len(optional_zip)} bytes")

    def _zip_path(addon_id: str, version: str) -> str:
        return f"/{addon_id}/{version}/{addon_id}-{version}.zip"

    server_files = {
        f"/{_TEST_REPO_ADDON_ID}.zip": repo_zip,
        "/addons.xml": addons_xml,
        "/addons.xml.md5": addons_xml_md5,
        _zip_path(_BM012_ROOT_ID, _BM012_ROOT_VERSION): root_zip,
        _zip_path(_BM012_A_ID, _BM012_A_VERSION): a_zip,
        _zip_path(_BM012_B_ID, _BM012_B_VERSION): b_zip,
        _zip_path(_BM012_OPTIONAL_ID, _BM012_OPTIONAL_VERSION): optional_zip,
    }

    class _Handler(_MultiFileHandler):
        _files = server_files  # type: ignore[assignment]

    server = http.server.HTTPServer(("127.0.0.1", _ADDON_SERVER_PORT), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    repo_url = f"http://127.0.0.1:{_ADDON_SERVER_PORT}/{_TEST_REPO_ADDON_ID}.zip"
    print(f"  HTTP server started: serving {len(server_files)} paths on port {_ADDON_SERVER_PORT}")

    addon_backend = _HttpAddonBackend()
    dep_backend = _HttpDependencyBackend(addon_backend)
    repo_backend = _HttpRepositoryBackend()
    addon_mgr = AddonManager(addon_backend)
    repo_mgr = RepositoryManager(repo_backend)
    test_repo = Repository(addon_id=_TEST_REPO_ADDON_ID, bootstrap_url=repo_url)
    resolver = DependencyResolver(dep_backend)

    try:
        print("\n[3/18] launch Kodi + wait for ready (up to 90s)")
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            stop()
            raise RuntimeError(f"Validation failed at step 3: {exc}") from exc

        print("\n[4/18] verify pre-conditions: bm012 add-ons not installed")
        for pre_id in (_BM012_ROOT_ID, _BM012_A_ID, _BM012_B_ID, _BM012_OPTIONAL_ID):
            if addon_mgr.is_installed(pre_id):
                stop()
                raise RuntimeError(
                    f"Validation failed: {pre_id!r} already installed before test"
                )
        print(f"  bm012-root, bm012-a, bm012-b, bm012-optional: all not installed ✓")

        print("\n[5/18] install test repository via BM-010 RepositoryManager.install")
        repo_result = repo_mgr.install(test_repo)
        print(f"  repo result.status = {repo_result.status.value!r}")
        if repo_result.status != RepositoryStatus.INSTALLED:
            raise RuntimeError(
                f"Validation failed: repo install returned {repo_result.status.value!r} "
                f"— {repo_result.message}"
            )
        print(f"  {_TEST_REPO_ADDON_ID!r} installed ✓")

        print("\n[6/18] verify test repository installed + enabled via Addons.GetAddonDetails")
        repo_detail = jsonrpc("Addons.GetAddonDetails", {
            "addonid": _TEST_REPO_ADDON_ID,
            "properties": ["enabled"],
        })
        if not (
            isinstance(repo_detail, dict)
            and isinstance(repo_detail.get("addon"), dict)
            and repo_detail["addon"].get("enabled") is True
        ):
            raise RuntimeError(
                f"Validation failed: test repo not enabled after install: {repo_detail!r}"
            )
        print(f"  {_TEST_REPO_ADDON_ID!r} enabled=True ✓")

        print("\n[7/18] install bm012-root via AddonManager.install (desired_state='enabled')")
        print("  (triggers constrained package-install: resolve → download → validate → stage → restart)")
        root_result = addon_mgr.install(_BM012_ROOT_ID, desired_state="enabled")
        print(f"  root result.status = {root_result.status.value!r}")
        if root_result.status not in (AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED):
            raise RuntimeError(
                f"Validation failed: bm012-root install returned {root_result.status.value!r} "
                f"— {root_result.message}"
            )
        print(f"  {_BM012_ROOT_ID!r} installed ✓")

        print("\n[8/18] verify bm012-root installed+enabled; addon.xml readable on filesystem")
        root_details = addon_backend.get_addon_details(_BM012_ROOT_ID)
        if root_details is None:
            raise RuntimeError(
                f"Validation failed: Addons.GetAddonDetails({_BM012_ROOT_ID!r}) returned None"
            )
        if not root_details.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM012_ROOT_ID!r} installed but enabled=False"
            )
        print(f"  {_BM012_ROOT_ID!r} enabled=True (v{root_details.version}) ✓")
        root_xml_bytes = dep_backend.read_addon_xml(_BM012_ROOT_ID)
        if not root_xml_bytes:
            raise RuntimeError(
                f"Validation failed: addon.xml not readable for {_BM012_ROOT_ID!r}"
            )
        print(f"  addon.xml readable ({len(root_xml_bytes)} bytes) ✓")

        print("\n[9/18] resolve_closure([bm012-root]) — pure read, no mutation")
        pre_closure = resolver.resolve_closure([_BM012_ROOT_ID])
        print(f"  closure nodes: {[(n.addon_id, n.status.value) for n in pre_closure.nodes]}")

        print("\n[10/18] verify closure: bm012-a = MISSING, bm012-optional = OPTIONAL")
        pre_statuses = {n.addon_id: n.status for n in pre_closure.nodes}
        if pre_statuses.get(_BM012_A_ID) != DependencyStatus.MISSING:
            raise RuntimeError(
                f"Validation failed: expected bm012-a=MISSING, got {pre_statuses.get(_BM012_A_ID)!r}"
            )
        print(f"  {_BM012_A_ID!r} = MISSING ✓")
        opt_statuses = {n.addon_id: n.status for n in pre_closure.optional_skipped}
        if _BM012_OPTIONAL_ID not in opt_statuses:
            raise RuntimeError(
                f"Validation failed: bm012-optional not in optional_skipped; got {pre_statuses!r}"
            )
        print(f"  {_BM012_OPTIONAL_ID!r} = OPTIONAL ✓")

        print("\n[11/18] reconcile_dependencies([bm012-root])")
        print("  (round 1: installs bm012-a + restart; round 2: installs bm012-b + restart)")
        result = resolver.reconcile_dependencies([_BM012_ROOT_ID])
        print(f"  all_required_satisfied = {result.all_required_satisfied}")
        print(f"  actions: {[(a.addon_id, a.kind.value) for a in result.actions]}")
        print(f"  unresolved: {[n.addon_id for n in result.unresolved]}")

        print("\n[12/18] verify result.all_required_satisfied = True")
        if not result.all_required_satisfied:
            raise RuntimeError(
                f"Validation failed: all_required_satisfied=False; "
                f"unresolved={[n.addon_id for n in result.unresolved]}"
            )
        print("  all_required_satisfied = True ✓")

        print("\n[13/18] verify INSTALLED action for script.module.bm012-a")
        installed_ids = {
            a.addon_id for a in result.actions
            if a.kind.value == "installed"
        }
        if _BM012_A_ID not in installed_ids:
            raise RuntimeError(
                f"Validation failed: no INSTALLED action for {_BM012_A_ID!r}; "
                f"installed_ids={installed_ids!r}"
            )
        print(f"  {_BM012_A_ID!r} INSTALLED ✓")

        print("\n[14/18] verify INSTALLED action for script.module.bm012-b")
        if _BM012_B_ID not in installed_ids:
            raise RuntimeError(
                f"Validation failed: no INSTALLED action for {_BM012_B_ID!r}; "
                f"installed_ids={installed_ids!r}"
            )
        print(f"  {_BM012_B_ID!r} INSTALLED ✓")

        print("\n[15/18] verify bm012-optional NOT in INSTALLED actions (optional policy)")
        if _BM012_OPTIONAL_ID in installed_ids:
            raise RuntimeError(
                f"Validation failed: {_BM012_OPTIONAL_ID!r} was installed — "
                "optional deps must never be installed by BM-012"
            )
        print(f"  {_BM012_OPTIONAL_ID!r} NOT installed ✓ (optional policy enforced)")

        print("\n[16/18] verify Kodi API: bm012-a installed + enabled")
        a_details = addon_backend.get_addon_details(_BM012_A_ID)
        if a_details is None:
            raise RuntimeError(
                f"Validation failed: Addons.GetAddonDetails({_BM012_A_ID!r}) returned None"
            )
        if not a_details.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM012_A_ID!r} installed but enabled=False"
            )
        print(f"  {_BM012_A_ID!r} enabled=True (v{a_details.version}) ✓")

        print("\n[17/18] verify Kodi API: bm012-b installed + enabled")
        b_details = addon_backend.get_addon_details(_BM012_B_ID)
        if b_details is None:
            raise RuntimeError(
                f"Validation failed: Addons.GetAddonDetails({_BM012_B_ID!r}) returned None"
            )
        if not b_details.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM012_B_ID!r} installed but enabled=False"
            )
        print(f"  {_BM012_B_ID!r} enabled=True (v{b_details.version}) ✓")

    finally:
        print("\n[18/18] stop Kodi + shut down HTTP server")
        try:
            stop()
        except RuntimeError:
            pass
        server.shutdown()

    print("\n[18/18] verify real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! "
                f"Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-012 validation PASSED (18/18) ===\n")


# ---------------------------------------------------------------------------
# BM-013: enable/disable state reconciliation
# ---------------------------------------------------------------------------

_BM013_ENABLED_ID = "plugin.video.bm013-enabled"
_BM013_ENABLED_VERSION = "1.0.0"
_BM013_DISABLED_ID = "plugin.video.bm013-disabled"
_BM013_DISABLED_VERSION = "1.0.0"
_BM013_PROTECTED_ID = "script.module.bm013-protected"
_BM013_PROTECTED_VERSION = "1.0.0"


def _make_bm013_enabled_zip() -> bytes:
    """Build the 'enabled' test add-on ZIP for BM-013 live validation.

    plugin.video.bm013-enabled — no dependencies; installed+enabled throughout.
    """
    import io
    import zipfile
    buf = io.BytesIO()
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{_BM013_ENABLED_ID}"'
        f' name="BM-013 Enabled Plugin"'
        f' version="{_BM013_ENABLED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '  <requires>\n'
        '    <import addon="xbmc.python" version="3.0.0"/>\n'
        '  </requires>\n'
        '  <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '  <extension point="xbmc.addon.metadata">\n'
        '    <summary lang="en_gb">BM-013 enabled-state test plugin</summary>\n'
        '    <platform>all</platform>\n'
        '  </extension>\n'
        '</addon>\n'
    ).encode("utf-8")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM013_ENABLED_ID}/addon.xml", addon_xml)
        zf.writestr(f"{_BM013_ENABLED_ID}/default.py", b"# BM-013 test\n")
    return buf.getvalue()


def _make_bm013_disabled_zip() -> bytes:
    """Build the 'disabled' test add-on ZIP for BM-013 live validation.

    plugin.video.bm013-disabled — installed+enabled initially; reconcile will
    set it disabled to prove the DISABLED outcome.
    """
    import io
    import zipfile
    buf = io.BytesIO()
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{_BM013_DISABLED_ID}"'
        f' name="BM-013 Disabled Plugin"'
        f' version="{_BM013_DISABLED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '  <requires>\n'
        '    <import addon="xbmc.python" version="3.0.0"/>\n'
        '  </requires>\n'
        '  <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '  <extension point="xbmc.addon.metadata">\n'
        '    <summary lang="en_gb">BM-013 disabled-state test plugin</summary>\n'
        '    <platform>all</platform>\n'
        '  </extension>\n'
        '</addon>\n'
    ).encode("utf-8")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM013_DISABLED_ID}/addon.xml", addon_xml)
        zf.writestr(f"{_BM013_DISABLED_ID}/default.py", b"# BM-013 test\n")
    return buf.getvalue()


def _make_bm013_protected_zip() -> bytes:
    """Build the 'protected dependency' test add-on ZIP for BM-013 live validation.

    script.module.bm013-protected — installed+enabled; passed in
    protected_dependency_ids to prove BLOCKED_REQUIRED_DEPENDENCY.
    """
    import io
    import zipfile
    buf = io.BytesIO()
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{_BM013_PROTECTED_ID}"'
        f' name="BM-013 Protected Module"'
        f' version="{_BM013_PROTECTED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '  <requires>\n'
        '    <import addon="xbmc.python" version="3.0.0"/>\n'
        '  </requires>\n'
        '  <extension point="xbmc.python.module" library="lib"/>\n'
        '  <extension point="xbmc.addon.metadata">\n'
        '    <summary lang="en_gb">BM-013 protected-dependency test module</summary>\n'
        '    <platform>all</platform>\n'
        '  </extension>\n'
        '</addon>\n'
    ).encode("utf-8")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM013_PROTECTED_ID}/addon.xml", addon_xml)
        zf.writestr(f"{_BM013_PROTECTED_ID}/lib/__init__.py", b"# BM-013 test\n")
    return buf.getvalue()


def _make_bm013_addons_xml() -> bytes:
    """Build the addons.xml index listing all three BM-013 test add-ons."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<addons>\n'
        f'  <addon id="{_BM013_ENABLED_ID}"'
        f' name="BM-013 Enabled Plugin"'
        f' version="{_BM013_ENABLED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">BM-013 enabled-state test plugin</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        f'  <addon id="{_BM013_DISABLED_ID}"'
        f' name="BM-013 Disabled Plugin"'
        f' version="{_BM013_DISABLED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">BM-013 disabled-state test plugin</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        f'  <addon id="{_BM013_PROTECTED_ID}"'
        f' name="BM-013 Protected Module"'
        f' version="{_BM013_PROTECTED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.module" library="lib"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">BM-013 protected-dependency test module</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        '</addons>\n'
    ).encode("utf-8")


class _HttpAddonStateBackend:
    """AddonStateBackend for BM-013 live validation against disposable Kodi.

    Wraps jsonrpc() HTTP calls. Raises AddonStateError on infrastructure failure
    (JSON-RPC transport error, Kodi unreachable). Returns None only for JSON-RPC
    error code -32602 (not installed). All other JSON-RPC error codes raise
    AddonStateError. This matches the contract of KodiRuntimeAddonStateBackend.
    """

    def _ensure_project_in_sys_path(self) -> None:
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))

    def get_addon_details(self, addon_id: str) -> Optional["AddonStateInfo"]:
        self._ensure_project_in_sys_path()
        from resources.lib.addon_state import AddonStateError, AddonStateInfo
        try:
            resp = jsonrpc("Addons.GetAddonDetails", {
                "addonid": addon_id,
                "properties": ["enabled", "version"],
            })
        except RuntimeError as exc:
            raise AddonStateError(
                f"Addons.GetAddonDetails({addon_id!r}) failed: {exc}"
            ) from exc
        if not isinstance(resp, dict):
            raise AddonStateError(
                f"Addons.GetAddonDetails({addon_id!r}) non-dict result: {resp!r}"
            )
        addon = resp.get("addon")
        if addon is None:
            return None
        if not isinstance(addon, dict) or addon.get("addonid") != addon_id:
            raise AddonStateError(
                f"Addons.GetAddonDetails({addon_id!r}) unexpected response: {resp!r}"
            )
        return AddonStateInfo(
            addon_id=addon_id,
            enabled=bool(addon.get("enabled", False)),
            version=str(addon.get("version", "")),
        )

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        self._ensure_project_in_sys_path()
        from resources.lib.addon_state import AddonStateError
        try:
            jsonrpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": enabled})
        except RuntimeError as exc:
            raise AddonStateError(
                f"Addons.SetAddonEnabled({addon_id!r}, {enabled}) failed: {exc}"
            ) from exc
        print(f"  [set_addon_enabled] {addon_id!r} enabled={enabled} ✓")


def validate_addon_state() -> None:
    """Live validation of BM-013 enable/disable state reconciliation.

    Three test add-ons (all installed from test repo via AddonManager):
      plugin.video.bm013-enabled   — stays enabled throughout (ALREADY_CORRECT)
      plugin.video.bm013-disabled  — starts enabled; reconcile sets it disabled (DISABLED)
      script.module.bm013-protected — protected dep; desired=disabled is BLOCKED

    Sequence (16 steps):
      1  Reset disposable harness + install Build Manager + configure web server
      2  Build BM-013 test ZIPs + addons.xml + repo ZIP; start HTTP server (127.0.0.1:8922)
      3  Launch Kodi + wait for ready
      4  Verify pre-conditions: bm013-enabled, bm013-disabled, bm013-protected not installed
      5  Install test repository via BM-010 RepositoryManager.install
      6  Install bm013-enabled via AddonManager.install (desired_state='enabled')
      7  Install bm013-disabled via AddonManager.install (desired_state='enabled')
      8  Install bm013-protected via AddonManager.install (desired_state='enabled')
      9  Verify initial Kodi state: all three installed + enabled
     10  reconcile({disabled:"disabled"}) → DISABLED; verify Kodi API enabled=False
     11  reconcile({disabled:"disabled"}) again → ALREADY_CORRECT (idempotency)
     12  reconcile({enabled:"enabled", protected:"disabled"}, protected={protected})
         → enabled=ALREADY_CORRECT, protected=BLOCKED_REQUIRED_DEPENDENCY
     13  Verify all_correct=False; both results have expected statuses
     14  Restart Kodi; verify bm013-disabled still disabled after restart (persistence)
     15  reconcile({enabled:"enabled", disabled:"enabled"}) → enabled=ALREADY_CORRECT, disabled=ENABLED
     16  Verify real Kodi profile untouched + stop Kodi + shut down HTTP server

    ALL mutation occurs only in the disposable .kodi-test environment.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.addon_state import AddonStateReconciler, AddonStateStatus
    from resources.lib.addons import AddonManager, AddonStatus
    from resources.lib.manifest import Repository
    from resources.lib.repository import RepositoryManager, RepositoryStatus

    print("=== Build Manager BM-013 live validation: enable/disable reconciliation ===")
    verify_isolation()

    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    print("\n[1/16] reset disposable harness + install Build Manager + configure web server")
    reset()
    install(source=PROJECT)
    configure_webserver()

    print("\n[2/16] build BM-013 test ZIPs + addons.xml + repo ZIP; start HTTP server")
    enabled_zip = _make_bm013_enabled_zip()
    disabled_zip = _make_bm013_disabled_zip()
    protected_zip = _make_bm013_protected_zip()
    addons_xml = _make_bm013_addons_xml()
    addons_xml_md5 = hashlib.md5(addons_xml).hexdigest().encode("utf-8")
    repo_zip = _make_bm011_repo_zip(_ADDON_SERVER_PORT)
    print(f"  repo ZIP: {len(repo_zip)} bytes")
    print(f"  addons.xml: {len(addons_xml)} bytes (md5={addons_xml_md5.decode()})")
    print(f"  bm013-enabled ZIP: {len(enabled_zip)} bytes")
    print(f"  bm013-disabled ZIP: {len(disabled_zip)} bytes")
    print(f"  bm013-protected ZIP: {len(protected_zip)} bytes")

    def _zip_path(addon_id: str, version: str) -> str:
        return f"/{addon_id}/{version}/{addon_id}-{version}.zip"

    server_files = {
        f"/{_TEST_REPO_ADDON_ID}.zip": repo_zip,
        "/addons.xml": addons_xml,
        "/addons.xml.md5": addons_xml_md5,
        _zip_path(_BM013_ENABLED_ID, _BM013_ENABLED_VERSION): enabled_zip,
        _zip_path(_BM013_DISABLED_ID, _BM013_DISABLED_VERSION): disabled_zip,
        _zip_path(_BM013_PROTECTED_ID, _BM013_PROTECTED_VERSION): protected_zip,
    }

    class _Handler(_MultiFileHandler):
        _files = server_files  # type: ignore[assignment]

    server = http.server.HTTPServer(("127.0.0.1", _ADDON_SERVER_PORT), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    repo_url = f"http://127.0.0.1:{_ADDON_SERVER_PORT}/{_TEST_REPO_ADDON_ID}.zip"
    print(f"  HTTP server started: serving {len(server_files)} paths on port {_ADDON_SERVER_PORT}")

    addon_backend = _HttpAddonBackend()
    state_backend = _HttpAddonStateBackend()
    repo_backend = _HttpRepositoryBackend()
    addon_mgr = AddonManager(addon_backend)
    repo_mgr = RepositoryManager(repo_backend)
    reconciler = AddonStateReconciler(state_backend)
    test_repo = Repository(addon_id=_TEST_REPO_ADDON_ID, bootstrap_url=repo_url)

    try:
        print("\n[3/16] launch Kodi + wait for ready (up to 90s)")
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            stop()
            raise RuntimeError(f"Validation failed at step 3: {exc}") from exc

        print("\n[4/16] verify pre-conditions: bm013 add-ons not installed")
        for pre_id in (_BM013_ENABLED_ID, _BM013_DISABLED_ID, _BM013_PROTECTED_ID):
            if addon_mgr.is_installed(pre_id):
                stop()
                raise RuntimeError(
                    f"Validation failed: {pre_id!r} already installed before test"
                )
        print("  bm013-enabled, bm013-disabled, bm013-protected: all not installed ✓")

        print("\n[5/16] install test repository via BM-010 RepositoryManager.install")
        repo_result = repo_mgr.install(test_repo)
        print(f"  repo result.status = {repo_result.status.value!r}")
        if repo_result.status != RepositoryStatus.INSTALLED:
            raise RuntimeError(
                f"Validation failed: repo install returned {repo_result.status.value!r} "
                f"— {repo_result.message}"
            )
        print(f"  {_TEST_REPO_ADDON_ID!r} installed ✓")

        print("\n[6/16] install bm013-enabled via AddonManager.install (desired_state='enabled')")
        en_result = addon_mgr.install(_BM013_ENABLED_ID, desired_state="enabled")
        print(f"  bm013-enabled result.status = {en_result.status.value!r}")
        if en_result.status not in (AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED):
            raise RuntimeError(
                f"Validation failed: bm013-enabled install returned {en_result.status.value!r} "
                f"— {en_result.message}"
            )
        print(f"  {_BM013_ENABLED_ID!r} installed ✓")

        print("\n[7/16] install bm013-disabled via AddonManager.install (desired_state='enabled')")
        dis_result = addon_mgr.install(_BM013_DISABLED_ID, desired_state="enabled")
        print(f"  bm013-disabled result.status = {dis_result.status.value!r}")
        if dis_result.status not in (AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED):
            raise RuntimeError(
                f"Validation failed: bm013-disabled install returned {dis_result.status.value!r} "
                f"— {dis_result.message}"
            )
        print(f"  {_BM013_DISABLED_ID!r} installed ✓")

        print("\n[8/16] install bm013-protected via AddonManager.install (desired_state='enabled')")
        prot_result = addon_mgr.install(_BM013_PROTECTED_ID, desired_state="enabled")
        print(f"  bm013-protected result.status = {prot_result.status.value!r}")
        if prot_result.status not in (AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED):
            raise RuntimeError(
                f"Validation failed: bm013-protected install returned {prot_result.status.value!r} "
                f"— {prot_result.message}"
            )
        print(f"  {_BM013_PROTECTED_ID!r} installed ✓")

        print("\n[9/16] verify initial Kodi state: all three installed + enabled")
        for chk_id in (_BM013_ENABLED_ID, _BM013_DISABLED_ID, _BM013_PROTECTED_ID):
            det = state_backend.get_addon_details(chk_id)
            if det is None:
                raise RuntimeError(
                    f"Validation failed: {chk_id!r} not found via GetAddonDetails"
                )
            if not det.enabled:
                raise RuntimeError(
                    f"Validation failed: {chk_id!r} installed but enabled=False"
                )
            print(f"  {chk_id!r} enabled=True (v{det.version}) ✓")

        print(
            "\n[10/16] reconcile({bm013-disabled:'disabled'}) "
            "→ DISABLED; verify Kodi API enabled=False"
        )
        r10 = reconciler.reconcile({_BM013_DISABLED_ID: "disabled"})
        r10_dis = r10.results[0]
        print(f"  bm013-disabled status = {r10_dis.status.value!r}")
        if r10_dis.status != AddonStateStatus.DISABLED:
            raise RuntimeError(
                f"Validation failed: expected DISABLED, got {r10_dis.status.value!r} "
                f"— {r10_dis.message}"
            )
        print(f"  {_BM013_DISABLED_ID!r} status=DISABLED ✓")
        after_dis = state_backend.get_addon_details(_BM013_DISABLED_ID)
        if after_dis is None or after_dis.enabled:
            raise RuntimeError(
                f"Validation failed: Kodi API shows bm013-disabled enabled after disable; "
                f"details={after_dis!r}"
            )
        print(f"  Kodi API: {_BM013_DISABLED_ID!r} enabled=False ✓")

        print(
            "\n[11/16] reconcile({bm013-disabled:'disabled'}) again "
            "→ ALREADY_CORRECT (idempotency)"
        )
        r11 = reconciler.reconcile({_BM013_DISABLED_ID: "disabled"})
        r11_dis = r11.results[0]
        print(f"  bm013-disabled status = {r11_dis.status.value!r}")
        if r11_dis.status != AddonStateStatus.ALREADY_CORRECT:
            raise RuntimeError(
                f"Validation failed: expected ALREADY_CORRECT, got {r11_dis.status.value!r} "
                f"— {r11_dis.message}"
            )
        print(f"  {_BM013_DISABLED_ID!r} ALREADY_CORRECT ✓ (idempotency confirmed)")

        print(
            "\n[12/16] reconcile({enabled:'enabled', protected:'disabled'}, "
            "protected={protected})"
        )
        r12 = reconciler.reconcile(
            {_BM013_ENABLED_ID: "enabled", _BM013_PROTECTED_ID: "disabled"},
            protected_dependency_ids=frozenset({_BM013_PROTECTED_ID}),
        )
        r12_map = {r.addon_id: r for r in r12.results}
        print(
            f"  bm013-enabled status = {r12_map[_BM013_ENABLED_ID].status.value!r}"
        )
        print(
            f"  bm013-protected status = {r12_map[_BM013_PROTECTED_ID].status.value!r}"
        )

        print("\n[13/16] verify all_correct=False; results match expected statuses")
        if r12.all_correct:
            raise RuntimeError(
                "Validation failed: all_correct=True but expected False "
                "(BLOCKED_REQUIRED_DEPENDENCY should make it False)"
            )
        print(f"  all_correct=False ✓")

        if r12_map[_BM013_ENABLED_ID].status != AddonStateStatus.ALREADY_CORRECT:
            raise RuntimeError(
                f"Validation failed: bm013-enabled expected ALREADY_CORRECT, "
                f"got {r12_map[_BM013_ENABLED_ID].status.value!r}"
            )
        print(f"  {_BM013_ENABLED_ID!r} ALREADY_CORRECT ✓")

        if r12_map[_BM013_PROTECTED_ID].status != AddonStateStatus.BLOCKED_REQUIRED_DEPENDENCY:
            raise RuntimeError(
                f"Validation failed: bm013-protected expected BLOCKED_REQUIRED_DEPENDENCY, "
                f"got {r12_map[_BM013_PROTECTED_ID].status.value!r}"
            )
        print(f"  {_BM013_PROTECTED_ID!r} BLOCKED_REQUIRED_DEPENDENCY ✓")

        print("\n[14/16] restart Kodi; verify bm013-disabled still disabled after restart")
        restart()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            stop()
            raise RuntimeError(f"Validation failed at step 14 (restart wait): {exc}") from exc
        after_restart = state_backend.get_addon_details(_BM013_DISABLED_ID)
        if after_restart is None:
            raise RuntimeError(
                f"Validation failed: {_BM013_DISABLED_ID!r} not found after restart"
            )
        if after_restart.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM013_DISABLED_ID!r} enabled=True after restart "
                f"— disabled state did not persist"
            )
        print(f"  {_BM013_DISABLED_ID!r} enabled=False after restart ✓ (persistence confirmed)")

        print(
            "\n[15/16] reconcile({enabled:'enabled', disabled:'enabled'}) "
            "→ enabled=ALREADY_CORRECT, disabled=ENABLED"
        )
        r15 = reconciler.reconcile(
            {_BM013_ENABLED_ID: "enabled", _BM013_DISABLED_ID: "enabled"}
        )
        r15_map = {r.addon_id: r for r in r15.results}
        print(
            f"  bm013-enabled status = {r15_map[_BM013_ENABLED_ID].status.value!r}"
        )
        print(
            f"  bm013-disabled status = {r15_map[_BM013_DISABLED_ID].status.value!r}"
        )
        if r15_map[_BM013_ENABLED_ID].status != AddonStateStatus.ALREADY_CORRECT:
            raise RuntimeError(
                f"Validation failed: bm013-enabled expected ALREADY_CORRECT, "
                f"got {r15_map[_BM013_ENABLED_ID].status.value!r}"
            )
        print(f"  {_BM013_ENABLED_ID!r} ALREADY_CORRECT ✓")
        if r15_map[_BM013_DISABLED_ID].status != AddonStateStatus.ENABLED:
            raise RuntimeError(
                f"Validation failed: bm013-disabled expected ENABLED, "
                f"got {r15_map[_BM013_DISABLED_ID].status.value!r}"
            )
        print(f"  {_BM013_DISABLED_ID!r} ENABLED ✓")
        if not r15.all_correct:
            raise RuntimeError(
                "Validation failed: all_correct=False after re-enable; expected True"
            )
        print(f"  all_correct=True ✓")

    finally:
        print("\n[16/16] stop Kodi + shut down HTTP server")
        try:
            stop()
        except RuntimeError:
            pass
        server.shutdown()

    print("\n[16/16] verify real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! "
                f"Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-013 validation PASSED (16/16) ===\n")


# ---------------------------------------------------------------------------
# BM-014: post-operation state validation
# ---------------------------------------------------------------------------

_BM014_ENABLED_ID = "plugin.video.bm014-enabled"
_BM014_ENABLED_VERSION = "1.0.0"
_BM014_DISABLED_ID = "plugin.video.bm014-disabled"
_BM014_DISABLED_VERSION = "1.0.0"


def _make_bm014_enabled_zip() -> bytes:
    """Build the 'enabled' test add-on ZIP for BM-014 live validation.

    plugin.video.bm014-enabled — desired state 'enabled'; only xbmc.python dep.
    """
    buf = io.BytesIO()
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{_BM014_ENABLED_ID}"'
        f' name="BM-014 Enabled Plugin"'
        f' version="{_BM014_ENABLED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '  <requires>\n'
        '    <import addon="xbmc.python" version="3.0.0"/>\n'
        '  </requires>\n'
        '  <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '  <extension point="xbmc.addon.metadata">\n'
        '    <summary lang="en_gb">BM-014 post-op validation enabled plugin</summary>\n'
        '    <platform>all</platform>\n'
        '  </extension>\n'
        '</addon>\n'
    ).encode("utf-8")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM014_ENABLED_ID}/addon.xml", addon_xml)
        zf.writestr(f"{_BM014_ENABLED_ID}/default.py", b"# BM-014 test\n")
    return buf.getvalue()


def _make_bm014_disabled_zip() -> bytes:
    """Build the 'disabled' test add-on ZIP for BM-014 live validation.

    plugin.video.bm014-disabled — desired state 'disabled'; only xbmc.python dep.
    Installed enabled, then set disabled before validation to prove drift detection.
    """
    buf = io.BytesIO()
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{_BM014_DISABLED_ID}"'
        f' name="BM-014 Disabled Plugin"'
        f' version="{_BM014_DISABLED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '  <requires>\n'
        '    <import addon="xbmc.python" version="3.0.0"/>\n'
        '  </requires>\n'
        '  <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '  <extension point="xbmc.addon.metadata">\n'
        '    <summary lang="en_gb">BM-014 post-op validation disabled plugin</summary>\n'
        '    <platform>all</platform>\n'
        '  </extension>\n'
        '</addon>\n'
    ).encode("utf-8")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM014_DISABLED_ID}/addon.xml", addon_xml)
        zf.writestr(f"{_BM014_DISABLED_ID}/default.py", b"# BM-014 test\n")
    return buf.getvalue()


def _make_bm014_addons_xml() -> bytes:
    """Build the addons.xml index for both BM-014 test add-ons."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<addons>\n'
        f'  <addon id="{_BM014_ENABLED_ID}"'
        f' name="BM-014 Enabled Plugin"'
        f' version="{_BM014_ENABLED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">BM-014 post-op validation enabled plugin</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        f'  <addon id="{_BM014_DISABLED_ID}"'
        f' name="BM-014 Disabled Plugin"'
        f' version="{_BM014_DISABLED_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">BM-014 post-op validation disabled plugin</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        '</addons>\n'
    ).encode("utf-8")


class _HttpKodiStateBackend:
    """KodiBackend implementation for KodiStateInspector in the disposable harness.

    All calls go to the disposable Kodi's JSON-RPC web server via jsonrpc().
    Reuses the same platform condition map as inspect() so results are consistent.
    """

    def get_platform_flags(self) -> Dict[str, bool]:
        flags_result = jsonrpc(
            "XBMC.GetInfoBooleans",
            {"booleans": list(_INSPECT_PLATFORM_BOOLEANS.values())},
        )
        if not isinstance(flags_result, dict):
            return {pid: False for pid in _INSPECT_PLATFORM_PRECEDENCE}
        return {
            pid: bool(flags_result.get(_INSPECT_PLATFORM_BOOLEANS[pid], False))
            for pid in _INSPECT_PLATFORM_PRECEDENCE
        }

    def get_kodi_version(self) -> str:
        version_result = jsonrpc("Application.GetProperties", {"properties": ["version"]})
        if not isinstance(version_result, dict):
            return ""
        ver = version_result.get("version", {})
        if not isinstance(ver, dict):
            return ""
        major = ver.get("major")
        minor = ver.get("minor")
        if (
            isinstance(major, int) and not isinstance(major, bool)
            and isinstance(minor, int) and not isinstance(minor, bool)
        ):
            return f"{major}.{minor}"
        return ""

    def get_active_skin(self) -> str:
        skin_result = jsonrpc("Settings.GetSettingValue", {"setting": "lookandfeel.skin"})
        if not isinstance(skin_result, dict):
            return ""
        val = skin_result.get("value", "")
        return val if isinstance(val, str) and val.startswith("skin.") else ""

    def get_installed_addons(self) -> List[Dict[str, Any]]:
        addons_result = jsonrpc("Addons.GetAddons", {
            "installed": True,
            "properties": ["enabled", "version"],
        })
        if not isinstance(addons_result, dict):
            return []
        raw = addons_result.get("addons", [])
        return raw if isinstance(raw, list) else []


def validate_post_operations() -> None:
    """Live validation of BM-014 post-operation state validation.

    Two test add-ons (installed from test repo via AddonManager):
      plugin.video.bm014-enabled   — desired 'enabled'; installed enabled
      plugin.video.bm014-disabled  — desired 'disabled'; installed then set disabled

    Validates: test repo installed+enabled (REPOSITORY domain), both add-ons
    in correct state (ADDON domain), xbmc.python satisfied (DEPENDENCY domain),
    active skin installed+active (SKIN domain), no config (no CONFIGURATION check).

    Sequence (19 steps):
      1  Reset disposable harness + install Build Manager + configure web server
      2  Build BM-014 test ZIPs + addons.xml + repo ZIP; start HTTP server (127.0.0.1:8922)
      3  Launch Kodi + wait for ready
      4  Verify pre-conditions: bm014-enabled, bm014-disabled not installed
      5  Install test repository via BM-010 RepositoryManager.install
      6  Verify test repository installed + enabled
      7  Install bm014-enabled via AddonManager.install (desired_state='enabled'); verify enabled
      8  Install bm014-disabled via AddonManager.install (desired_state='enabled');
         set disabled via Addons.SetAddonEnabled(False); verify enabled=False
      9  Inspect KodiState via KodiStateInspector(_HttpKodiStateBackend)
     10  Resolve dependency closure for bm014-enabled (xbmc.python → SYSTEM)
     11  Build ResolvedBuild (desired): test repo required, bm014-enabled=enabled,
         bm014-disabled=disabled, skin=active skin, config=None
     12  validate_build_state(desired, actual, closure) → PASS
         Verify is_valid=True, is_complete=True, passed=True
         Verify validator made zero Kodi mutations (read-only proof)
     13  Introduce drift: Addons.SetAddonEnabled(bm014-disabled, True) outside validator
     14  Re-inspect KodiState after drift
     15  validate_build_state(desired, drifted_actual, closure) → FAIL on bm014-disabled
         Verify is_valid=False, is_complete unchanged, validator still made zero mutations
     16  Repair drift: Addons.SetAddonEnabled(bm014-disabled, False) outside validator
     17  Re-inspect KodiState after repair
     18  validate_build_state(desired, repaired_actual, closure) → PASS
         Verify passed=True; validator still made zero mutations total
     19  Stop Kodi + shut down HTTP server; verify real profile untouched

    ALL mutation occurs only in the disposable .kodi-test environment.
    The BM-014 validator itself never calls SetAddonEnabled or any mutating API.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.addons import AddonManager
    from resources.lib.dependencies import DependencyResolver, DependencyStatus
    from resources.lib.inspector import KodiStateInspector
    from resources.lib.manifest import AddonEntry, BuildInfo, Repository, SkinEntry
    from resources.lib.repository import RepositoryManager, RepositoryStatus
    from resources.lib.resolver import ResolvedBuild
    from resources.lib.validator import (
        ValidationStatus,
        validate_build_state,
    )

    print("=== Build Manager BM-014 live validation: post-operation state validation ===")
    verify_isolation()

    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    print("\n[1/19] reset disposable harness + install Build Manager + configure web server")
    reset()
    install(source=PROJECT)
    configure_webserver()

    print("\n[2/19] build BM-014 test ZIPs + addons.xml + repo ZIP; start HTTP server")
    enabled_zip = _make_bm014_enabled_zip()
    disabled_zip = _make_bm014_disabled_zip()
    addons_xml = _make_bm014_addons_xml()
    addons_xml_md5 = hashlib.md5(addons_xml).hexdigest().encode("utf-8")
    repo_zip = _make_bm011_repo_zip(_ADDON_SERVER_PORT)
    print(f"  repo ZIP: {len(repo_zip)} bytes")
    print(f"  addons.xml: {len(addons_xml)} bytes (md5={addons_xml_md5.decode()})")
    print(f"  bm014-enabled ZIP: {len(enabled_zip)} bytes")
    print(f"  bm014-disabled ZIP: {len(disabled_zip)} bytes")

    def _zip_path(addon_id: str, version: str) -> str:
        return f"/{addon_id}/{version}/{addon_id}-{version}.zip"

    server_files = {
        f"/{_TEST_REPO_ADDON_ID}.zip": repo_zip,
        "/addons.xml": addons_xml,
        "/addons.xml.md5": addons_xml_md5,
        _zip_path(_BM014_ENABLED_ID, _BM014_ENABLED_VERSION): enabled_zip,
        _zip_path(_BM014_DISABLED_ID, _BM014_DISABLED_VERSION): disabled_zip,
    }

    class _Handler(_MultiFileHandler):
        _files = server_files  # type: ignore[assignment]

    server = http.server.HTTPServer(("127.0.0.1", _ADDON_SERVER_PORT), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    repo_url = f"http://127.0.0.1:{_ADDON_SERVER_PORT}/{_TEST_REPO_ADDON_ID}.zip"
    print(f"  HTTP server started: serving {len(server_files)} paths on port {_ADDON_SERVER_PORT}")

    addon_backend = _HttpAddonBackend()
    dep_backend = _HttpDependencyBackend(addon_backend)
    state_backend = _HttpAddonStateBackend()
    state_inspector_backend = _HttpKodiStateBackend()
    addon_mgr = AddonManager(addon_backend)
    repo_mgr = RepositoryManager(_HttpRepositoryBackend())
    resolver = DependencyResolver(dep_backend)
    inspector = KodiStateInspector(backend=state_inspector_backend)
    test_repo = Repository(addon_id=_TEST_REPO_ADDON_ID, bootstrap_url=repo_url)

    try:
        print("\n[3/19] launch Kodi + wait for ready (up to 90s)")
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            stop()
            raise RuntimeError(f"Validation failed at step 3: {exc}") from exc

        print("\n[4/19] verify pre-conditions: bm014 add-ons not installed")
        for aid in (_BM014_ENABLED_ID, _BM014_DISABLED_ID):
            if addon_mgr.is_installed(aid):
                raise RuntimeError(
                    f"Validation failed: {aid!r} already installed before test"
                )
            print(f"  is_installed({aid!r}) = False ✓")

        print("\n[5/19] install test repository via RepositoryManager.install")
        repo_result = repo_mgr.install(test_repo)
        if repo_result.status != RepositoryStatus.INSTALLED:
            raise RuntimeError(
                f"Validation failed: repo install status={repo_result.status!r}: "
                f"{repo_result.message}"
            )
        print(f"  repository {_TEST_REPO_ADDON_ID!r} installed ✓")

        print("\n[6/19] verify test repository installed + enabled")
        repo_details = addon_backend.get_addon_details(_TEST_REPO_ADDON_ID)
        if repo_details is None:
            raise RuntimeError(
                f"Validation failed: {_TEST_REPO_ADDON_ID!r} not found via "
                "Addons.GetAddonDetails after install"
            )
        if not repo_details.enabled:
            raise RuntimeError(
                f"Validation failed: {_TEST_REPO_ADDON_ID!r} installed but enabled=False"
            )
        print(f"  {_TEST_REPO_ADDON_ID!r} enabled=True (v{repo_details.version}) ✓")

        print(f"\n[7/19] install {_BM014_ENABLED_ID!r} (desired_state='enabled'); verify enabled")
        en_result = addon_mgr.install(_BM014_ENABLED_ID, desired_state="enabled")
        from resources.lib.addons import AddonStatus
        if en_result.status not in (AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED):
            raise RuntimeError(
                f"Validation failed: {_BM014_ENABLED_ID!r} install "
                f"status={en_result.status!r}: {en_result.message}"
            )
        en_details = addon_backend.get_addon_details(_BM014_ENABLED_ID)
        if en_details is None or not en_details.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM014_ENABLED_ID!r} not enabled after install"
            )
        print(f"  {_BM014_ENABLED_ID!r} installed+enabled (v{en_details.version}) ✓")

        print(
            f"\n[8/19] install {_BM014_DISABLED_ID!r} then set disabled; verify enabled=False"
        )
        dis_result = addon_mgr.install(_BM014_DISABLED_ID, desired_state="enabled")
        if dis_result.status not in (AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED):
            raise RuntimeError(
                f"Validation failed: {_BM014_DISABLED_ID!r} install "
                f"status={dis_result.status!r}: {dis_result.message}"
            )
        # Set disabled via Addons.SetAddonEnabled (outside validator — harness mutation)
        state_backend.set_addon_enabled(_BM014_DISABLED_ID, False)
        dis_details = addon_backend.get_addon_details(_BM014_DISABLED_ID)
        if dis_details is None or dis_details.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM014_DISABLED_ID!r} not disabled after "
                "Addons.SetAddonEnabled(False)"
            )
        print(f"  {_BM014_DISABLED_ID!r} installed+disabled (v{dis_details.version}) ✓")

        print("\n[9/19] inspect KodiState via KodiStateInspector(_HttpKodiStateBackend)")
        actual = inspector.inspect()
        actual_map = {a.addon_id: a for a in actual.addons}
        if _BM014_ENABLED_ID not in actual_map:
            raise RuntimeError(
                f"Validation failed: {_BM014_ENABLED_ID!r} absent from KodiState"
            )
        if _BM014_DISABLED_ID not in actual_map:
            raise RuntimeError(
                f"Validation failed: {_BM014_DISABLED_ID!r} absent from KodiState"
            )
        print(
            f"  KodiState: {len(actual.addons)} addons, "
            f"skin={actual.active_skin!r}, version={actual.kodi_version!r}"
        )
        print(
            f"  {_BM014_ENABLED_ID!r} enabled={actual_map[_BM014_ENABLED_ID].enabled} ✓"
        )
        print(
            f"  {_BM014_DISABLED_ID!r} enabled={actual_map[_BM014_DISABLED_ID].enabled} ✓"
        )

        print(
            f"\n[10/19] resolve dependency closure for {_BM014_ENABLED_ID!r} "
            "(xbmc.python → SYSTEM)"
        )
        closure = resolver.resolve_closure([_BM014_ENABLED_ID])
        system_nodes = [n for n in closure.nodes if n.status == DependencyStatus.SYSTEM]
        if not system_nodes:
            raise RuntimeError(
                "Validation failed: expected at least one SYSTEM node (xbmc.python) "
                "in closure; none found"
            )
        print(
            f"  closure: {len(closure.nodes)} node(s); "
            f"SYSTEM: {[n.addon_id for n in system_nodes]} ✓"
        )

        print("\n[11/19] build ResolvedBuild (desired)")
        active_skin = actual.active_skin
        desired = ResolvedBuild(
            build=BuildInfo(id="bm014-test", version="1.0.0", name="BM-014 Test Build"),
            engine_min_version="1.0.0",
            platform_profile_id=actual.platform,
            device_profile_id="disposable-kodi-test",
            repositories=(
                Repository(addon_id=_TEST_REPO_ADDON_ID, bootstrap_url=repo_url, required=True),
            ),
            addons=(
                AddonEntry(addon_id=_BM014_ENABLED_ID, state="enabled"),
                AddonEntry(addon_id=_BM014_DISABLED_ID, state="disabled"),
            ),
            skin=SkinEntry(addon_id=active_skin) if active_skin else None,
            config=None,
            optional_groups_applied=(),
            restart_policy=None,
            private_overlay=None,
        )
        print(f"  desired: repo={_TEST_REPO_ADDON_ID!r} (required), "
              f"addons=[{_BM014_ENABLED_ID!r}=enabled, {_BM014_DISABLED_ID!r}=disabled], "
              f"skin={active_skin!r}")

        print("\n[12/19] validate_build_state(desired, actual, closure) → PASS")
        # Track that validate_build_state makes zero Kodi mutations.
        # Since the validator is pure Python with no backend calls,
        # we verify this by confirming Kodi state is identical before and after.
        state_before = {a.addon_id: a.enabled for a in actual.addons}
        report = validate_build_state(desired, actual, closure)
        state_after = {a.addon_id: a.enabled for a in actual.addons}

        if state_before != state_after:
            raise RuntimeError(
                "Validation FAILED: validate_build_state mutated actual.addons "
                "(read-only guarantee violated)"
            )
        if not report.passed:
            fail_msgs = [f"  FAIL: [{c.domain.value}] {c.subject}: {c.reason}"
                        for c in report.failures]
            nc_msgs = [f"  NOT_CHECKED: [{c.domain.value}] {c.subject}: {c.reason}"
                      for c in report.not_checked]
            detail = "\n".join(fail_msgs + nc_msgs)
            raise RuntimeError(
                f"Validation failed: expected PASS but got:\n"
                f"  is_valid={report.is_valid} is_complete={report.is_complete}\n"
                f"{detail}"
            )
        print(
            f"  is_valid={report.is_valid} is_complete={report.is_complete} "
            f"passed={report.passed} ✓"
        )
        print(
            f"  {len(report.passes)} PASS, {len(report.failures)} FAIL, "
            f"{len(report.warnings)} WARNING, {len(report.not_checked)} NOT_CHECKED ✓"
        )
        print("  validator made zero Kodi mutations (read-only guarantee) ✓")

        print(
            f"\n[13/19] introduce drift: Addons.SetAddonEnabled"
            f"({_BM014_DISABLED_ID!r}, True) outside validator"
        )
        state_backend.set_addon_enabled(_BM014_DISABLED_ID, True)
        drift_details = addon_backend.get_addon_details(_BM014_DISABLED_ID)
        if drift_details is None or not drift_details.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM014_DISABLED_ID!r} not enabled after drift injection"
            )
        print(f"  {_BM014_DISABLED_ID!r} now enabled=True (drift injected) ✓")

        print("\n[14/19] re-inspect KodiState after drift")
        drifted_actual = inspector.inspect()
        drifted_map = {a.addon_id: a for a in drifted_actual.addons}
        if _BM014_DISABLED_ID not in drifted_map or not drifted_map[_BM014_DISABLED_ID].enabled:
            raise RuntimeError(
                f"Validation failed: KodiState does not reflect drift for "
                f"{_BM014_DISABLED_ID!r}"
            )
        print(
            f"  drifted KodiState: {_BM014_DISABLED_ID!r} "
            f"enabled={drifted_map[_BM014_DISABLED_ID].enabled} ✓"
        )

        print(
            "\n[15/19] validate_build_state(desired, drifted_actual, closure) "
            "→ FAIL on bm014-disabled"
        )
        drifted_report = validate_build_state(desired, drifted_actual, closure)
        if drifted_report.is_valid:
            raise RuntimeError(
                "Validation failed: expected FAIL for drifted state but got is_valid=True"
            )
        failed_subjects = [c.subject for c in drifted_report.failures]
        if _BM014_DISABLED_ID not in failed_subjects:
            raise RuntimeError(
                f"Validation failed: expected FAIL for {_BM014_DISABLED_ID!r}; "
                f"actual failures: {failed_subjects!r}"
            )
        print(f"  is_valid=False ✓; FAIL on {_BM014_DISABLED_ID!r} ✓")
        print(f"  failure reason: {drifted_report.failures[0].reason!r} ✓")

        print(
            f"\n[16/19] repair drift: Addons.SetAddonEnabled"
            f"({_BM014_DISABLED_ID!r}, False) outside validator"
        )
        state_backend.set_addon_enabled(_BM014_DISABLED_ID, False)
        repaired_details = addon_backend.get_addon_details(_BM014_DISABLED_ID)
        if repaired_details is None or repaired_details.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM014_DISABLED_ID!r} not disabled after repair"
            )
        print(f"  {_BM014_DISABLED_ID!r} now enabled=False (drift repaired) ✓")

        print("\n[17/19] re-inspect KodiState after repair")
        repaired_actual = inspector.inspect()
        repaired_map = {a.addon_id: a for a in repaired_actual.addons}
        if _BM014_DISABLED_ID not in repaired_map or repaired_map[_BM014_DISABLED_ID].enabled:
            raise RuntimeError(
                f"Validation failed: KodiState does not reflect repair for "
                f"{_BM014_DISABLED_ID!r}"
            )
        print(
            f"  repaired KodiState: {_BM014_DISABLED_ID!r} "
            f"enabled={repaired_map[_BM014_DISABLED_ID].enabled} ✓"
        )

        print("\n[18/19] validate_build_state(desired, repaired_actual, closure) → PASS")
        repaired_report = validate_build_state(desired, repaired_actual, closure)
        if not repaired_report.passed:
            fail_msgs = [f"  FAIL: [{c.domain.value}] {c.subject}: {c.reason}"
                        for c in repaired_report.failures]
            nc_msgs = [f"  NOT_CHECKED: [{c.domain.value}] {c.subject}: {c.reason}"
                      for c in repaired_report.not_checked]
            detail = "\n".join(fail_msgs + nc_msgs)
            raise RuntimeError(
                f"Validation failed: expected PASS after repair but got:\n"
                f"  is_valid={repaired_report.is_valid} "
                f"is_complete={repaired_report.is_complete}\n{detail}"
            )
        print(
            f"  is_valid={repaired_report.is_valid} is_complete={repaired_report.is_complete} "
            f"passed={repaired_report.passed} ✓"
        )
        print("  validator still made zero Kodi mutations throughout ✓")

    finally:
        print("\n[19/19] stop Kodi + shut down HTTP server")
        try:
            stop()
        except RuntimeError:
            pass
        server.shutdown()

    print("\n[19/19] verify real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! "
                f"Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-014 validation PASSED (19/19) ===\n")


# ---------------------------------------------------------------------------
# BM-015 live validation — configuration package deployment
# ---------------------------------------------------------------------------

_BM015_TEST_ADDON_ID = "plugin.video.bm015-config"
_BM015_TEST_ADDON_VERSION = "1.0.0"

_BM015_RUNNER_ADDON_ID = "script.build-manager-harness-config"
_BM015_RUNNER_VERSION = "1.0.0"

_BM015_PACKAGE_COMMON = "bm015-common"
_BM015_PACKAGE_DEVICE = "bm015-device"

_BM015_MANAGED_FILE = f"addon_data/{_BM015_TEST_ADDON_ID}/bm015-managed.txt"
_BM015_UNMANAGED_FILE = f"addon_data/{_BM015_TEST_ADDON_ID}/bm015-unmanaged.txt"

_BM015_JOB_FILE = "bm015-job.json"
_BM015_RESULT_FILE = "bm015-result.json"

# Synthetic, obviously non-secret values. Public configuration packages must
# never contain credentials; these fixtures deliberately look like test data.
_BM015_DEFAULTS = {
    "bm015.text": "initial-text",
    "bm015.bool": False,
    "bm015.int": 1,
    "bm015.number": 0.5,
    "bm015.unmanaged": "unmanaged-initial",
}
_BM015_COMMON_VALUES = {
    "bm015.text": "common-layer-text",
    "bm015.bool": True,
    "bm015.int": 7,
    "bm015.number": 0.25,
}
_BM015_DEVICE_VALUES = {
    "bm015.text": "device-layer-text",
    "bm015.int": 42,
    "bm015.number": 1.5,
}
#: Winning values after common -> device overlay.
_BM015_EXPECTED = {
    "bm015.text": "device-layer-text",
    "bm015.bool": True,
    "bm015.int": 42,
    "bm015.number": 1.5,
}
_BM015_EXPECTED_PACKAGE = {
    "bm015.text": _BM015_PACKAGE_DEVICE,
    "bm015.bool": _BM015_PACKAGE_COMMON,
    "bm015.int": _BM015_PACKAGE_DEVICE,
    "bm015.number": _BM015_PACKAGE_DEVICE,
}
_BM015_SETTING_TYPES = {
    "bm015.text": "string",
    "bm015.bool": "bool",
    "bm015.int": "int",
    "bm015.number": "number",
    "bm015.unmanaged": "string",
}

_BM015_COMMON_FILE_CONTENT = b"bm015 common-layer managed content\n"
_BM015_DEVICE_FILE_CONTENT = b"bm015 device-layer managed content\n"
_BM015_UNMANAGED_CONTENT = b"bm015 unmanaged sibling - must never change\n"


def _make_bm015_test_addon_zip() -> bytes:
    """Build the BM-015 test add-on ZIP with real Kodi setting definitions.

    plugin.video.bm015-config declares five settings covering every supported
    type plus one deliberately unmanaged control setting:

        bm015.text       string   default 'initial-text'
        bm015.bool       boolean  default false
        bm015.int        integer  default 1
        bm015.number     number   default 0.5
        bm015.unmanaged  string   default 'unmanaged-initial'  (never managed)

    All values are synthetic. No real credentials or real add-on configuration
    is used anywhere in this fixture.
    """
    buf = io.BytesIO()
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<addon id="{_BM015_TEST_ADDON_ID}"'
        f' name="BM-015 Config Plugin"'
        f' version="{_BM015_TEST_ADDON_VERSION}"'
        f' provider-name="Build Manager">\n'
        '  <requires>\n'
        '    <import addon="xbmc.python" version="3.0.0"/>\n'
        '  </requires>\n'
        '  <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '  <extension point="xbmc.addon.metadata">\n'
        '    <summary lang="en_gb">BM-015 configuration deployment test plugin</summary>\n'
        '    <platform>all</platform>\n'
        '  </extension>\n'
        '</addon>\n'
    ).encode("utf-8")

    settings_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<settings version="1">\n'
        '  <section id="bm015">\n'
        '    <category id="general" label="30000">\n'
        '      <group id="1" label="30000">\n'
        '        <setting id="bm015.text" type="string" label="30001">\n'
        '          <level>0</level>\n'
        f'          <default>{_BM015_DEFAULTS["bm015.text"]}</default>\n'
        '          <control type="edit" format="string"/>\n'
        '        </setting>\n'
        '        <setting id="bm015.bool" type="boolean" label="30002">\n'
        '          <level>0</level>\n'
        '          <default>false</default>\n'
        '          <control type="toggle"/>\n'
        '        </setting>\n'
        '        <setting id="bm015.int" type="integer" label="30003">\n'
        '          <level>0</level>\n'
        f'          <default>{_BM015_DEFAULTS["bm015.int"]}</default>\n'
        '          <control type="edit" format="integer"/>\n'
        '        </setting>\n'
        '        <setting id="bm015.number" type="number" label="30004">\n'
        '          <level>0</level>\n'
        f'          <default>{_BM015_DEFAULTS["bm015.number"]}</default>\n'
        '          <control type="edit" format="number"/>\n'
        '        </setting>\n'
        '        <setting id="bm015.unmanaged" type="string" label="30005">\n'
        '          <level>0</level>\n'
        f'          <default>{_BM015_DEFAULTS["bm015.unmanaged"]}</default>\n'
        '          <control type="edit" format="string"/>\n'
        '        </setting>\n'
        '      </group>\n'
        '    </category>\n'
        '  </section>\n'
        '</settings>\n'
    ).encode("utf-8")

    strings_po = (
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '\n'
        'msgctxt "#30000"\nmsgid "BM-015"\nmsgstr ""\n\n'
        'msgctxt "#30001"\nmsgid "Text"\nmsgstr ""\n\n'
        'msgctxt "#30002"\nmsgid "Bool"\nmsgstr ""\n\n'
        'msgctxt "#30003"\nmsgid "Int"\nmsgstr ""\n\n'
        'msgctxt "#30004"\nmsgid "Number"\nmsgstr ""\n\n'
        'msgctxt "#30005"\nmsgid "Unmanaged"\nmsgstr ""\n'
    ).encode("utf-8")

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_BM015_TEST_ADDON_ID}/addon.xml", addon_xml)
        zf.writestr(f"{_BM015_TEST_ADDON_ID}/default.py", b"# BM-015 test\n")
        zf.writestr(f"{_BM015_TEST_ADDON_ID}/resources/settings.xml", settings_xml)
        zf.writestr(
            f"{_BM015_TEST_ADDON_ID}/resources/language/resource.language.en_gb/strings.po",
            strings_po,
        )
    return buf.getvalue()


def _make_bm015_addons_xml() -> bytes:
    """Build the addons.xml index listing the BM-015 test add-on."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<addons>\n'
        f'  <addon id="{_BM015_TEST_ADDON_ID}"'
        f' name="BM-015 Config Plugin"'
        f' version="{_BM015_TEST_ADDON_VERSION}"'
        f' provider-name="Build Manager">\n'
        '    <requires>\n'
        '      <import addon="xbmc.python" version="3.0.0"/>\n'
        '    </requires>\n'
        '    <extension point="xbmc.python.pluginsource" library="default.py"/>\n'
        '    <extension point="xbmc.addon.metadata">\n'
        '      <summary lang="en_gb">BM-015 configuration deployment test plugin</summary>\n'
        '      <platform>all</platform>\n'
        '    </extension>\n'
        '  </addon>\n'
        '</addons>\n'
    ).encode("utf-8")


def _bm015_installed_packages_root() -> Path:
    """Embedded package root inside the DISPOSABLE installed Build Manager copy."""
    return (
        KODI_ADDONS_DIR / ADDON_ID / "resources" / "config" / "packages"
    )


def _write_bm015_packages() -> None:
    """Write the two layered BM-015 test packages into the installed add-on.

    They are written into the disposable profile's copy of Build Manager, at
    exactly the production embedded location (resources/config/packages), so the
    live run exercises default_packages_root() the way production will. The
    project working tree is never modified.

    bm015-common supplies all four managed settings plus the managed file.
    bm015-device overrides three settings and the managed file, leaving
    bm015.bool owned by the common layer. This proves live overlay precedence.
    """
    verify_isolation()
    root = _bm015_installed_packages_root()
    if not root.is_dir():
        raise RuntimeError(
            f"expected embedded package root at {root}; is resources/config/"
            f"packages present in the project and copied by install()?"
        )

    common_dir = root / _BM015_PACKAGE_COMMON
    device_dir = root / _BM015_PACKAGE_DEVICE
    for directory in (common_dir, device_dir):
        if directory.exists():
            shutil.rmtree(directory)
        (directory / "files").mkdir(parents=True)

    common_descriptor = {
        "schema_version": 1,
        "id": _BM015_PACKAGE_COMMON,
        "settings": [
            {
                "addon_id": _BM015_TEST_ADDON_ID,
                "key": key,
                "type": _BM015_SETTING_TYPES[key],
                "value": value,
            }
            for key, value in _BM015_COMMON_VALUES.items()
        ],
        "files": [{
            "source": "files/bm015-managed.txt",
            "destination": _BM015_MANAGED_FILE,
        }],
    }
    device_descriptor = {
        "schema_version": 1,
        "id": _BM015_PACKAGE_DEVICE,
        "settings": [
            {
                "addon_id": _BM015_TEST_ADDON_ID,
                "key": key,
                "type": _BM015_SETTING_TYPES[key],
                "value": value,
            }
            for key, value in _BM015_DEVICE_VALUES.items()
        ],
        "files": [{
            "source": "files/bm015-managed.txt",
            "destination": _BM015_MANAGED_FILE,
        }],
    }

    (common_dir / "package.json").write_text(
        json.dumps(common_descriptor, indent=2), encoding="utf-8"
    )
    (device_dir / "package.json").write_text(
        json.dumps(device_descriptor, indent=2), encoding="utf-8"
    )
    (common_dir / "files" / "bm015-managed.txt").write_bytes(
        _BM015_COMMON_FILE_CONTENT
    )
    (device_dir / "files" / "bm015-managed.txt").write_bytes(
        _BM015_DEVICE_FILE_CONTENT
    )
    print(f"  wrote {_BM015_PACKAGE_COMMON!r} and {_BM015_PACKAGE_DEVICE!r} to {root}")


def _install_bm015_config_runner() -> None:
    """Write the disposable BM-015 configuration runner into the test profile.

    Kodi's typed add-on Settings API (xbmcaddon.Addon(id).getSettings()) is an
    in-process API with no JSON-RPC equivalent, so BM-015 cannot be live-proven
    from outside Kodi. This tiny script add-on runs INSIDE the disposable Kodi
    and drives the real production code path:

        ConfigPackageLoader(default_packages_root()).resolve(declarations)
        ConfigurationManager(KodiRuntimeConfigurationBackend()).apply(effective)

    It contains no configuration logic of its own — it only marshals a job file
    into the production API and serializes the production result back out.

    This runner is harness-only. It is written directly into .kodi-test and is
    never part of the shipped add-on; the production add-on carries no test
    execution hook of any kind.
    """
    verify_isolation()
    target = KODI_ADDONS_DIR / _BM015_RUNNER_ADDON_ID
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_BM015_RUNNER_ADDON_ID}"'
        ' name="Build Manager Harness Config Runner"'
        f' version="{_BM015_RUNNER_VERSION}"'
        ' provider-name="Build Manager">'
        '<extension point="xbmc.python.script" library="default.py"/>'
        '<extension point="xbmc.addon.metadata">'
        '<summary lang="en_gb">Harness-only runner for BM-015 live validation</summary>'
        '<platform>all</platform>'
        '</extension>'
        '</addon>'
    )
    (target / "addon.xml").write_text(addon_xml, encoding="utf-8")

    runner_py = '''"""Harness-only BM-015/BM-018D runner. Executes production code."""
import json
import os
import sys
import traceback

import xbmcvfs

PROFILE = xbmcvfs.translatePath("special://profile/")
JOB_PATH = os.path.join(PROFILE, "%(job)s")
RESULT_PATH = os.path.join(PROFILE, "%(result)s")


def _load_production_modules(addon_root):
    # Drop any previously imported copy so each invocation imports fresh from
    # the installed Build Manager add-on.
    for name in [m for m in list(sys.modules)
                 if m == "resources" or m.startswith("resources.")]:
        del sys.modules[name]
    if addon_root in sys.path:
        sys.path.remove(addon_root)
    sys.path.insert(0, addon_root)
    import resources.lib.config as config
    import resources.lib.manifest as manifest
    return config, manifest


def _declarations(manifest, job):
    return manifest.ConfigDeclarations(
        packages=tuple(job.get("packages", [])),
        managed_settings=tuple(
            manifest.ManagedSettingScope(
                target_kind=manifest.SettingTargetKind(
                    scope.get("target", "addon")
                ),
                addon_id=scope["addon_id"], keys=tuple(scope["keys"])
            )
            for scope in job.get("managed_settings", [])
        ),
        managed_files=tuple(job.get("managed_files", [])),
    )


def _operation(result):
    return {
        "kind": result.kind.value,
        "target": result.target,
        "addon_id": result.addon_id,
        "key": result.key,
        "destination": result.destination,
        "package_id": result.package_id,
        "status": result.status.value,
        "expected_identity": result.expected_identity,
        "previous_identity": result.previous_identity,
        "detail": result.detail,
    }


def _run_apply(config, manifest, job):
    loader = config.ConfigPackageLoader(config.default_packages_root())
    effective = loader.resolve(_declarations(manifest, job))
    manager = config.ConfigurationManager(
        config.KodiRuntimeConfigurationBackend()
    )
    applied = manager.apply(effective)
    state = applied.validation_state
    return {
        "packages_root": loader.packages_root,
        "packages": list(effective.packages),
        "operations": [_operation(r) for r in applied.results],
        "all_applied": applied.all_applied,
        "changed": [r.target for r in applied.changed],
        "unchanged": [r.target for r in applied.unchanged],
        "failed": [r.target for r in applied.failed],
        "effective_identity": effective.identity,
        "validation_state": {
            "effective_identity": state.effective_identity,
            "setting_targets": [list(t) for t in state.setting_targets],
            "file_targets": list(state.file_targets),
            "verified_settings": [list(t) for t in state.verified_settings],
            "verified_files": list(state.verified_files),
            "is_fully_verified": state.is_fully_verified,
        },
    }


def _run_observe(config, job):
    """Read raw typed values through the production Kodi runtime backend."""
    backend = config.KodiRuntimeConfigurationBackend()
    observed = {}
    for probe in job.get("observe", []):
        setting_type = config.ConfigSettingType(probe["type"])
        try:
            target_kind = config.ConfigTargetKind(
                probe.get("target", "addon")
            )
            if target_kind == config.ConfigTargetKind.SKIN:
                value = backend.get_skin_setting(
                    probe["addon_id"], probe["key"], setting_type
                )
            else:
                value = backend.get_setting(
                    probe["addon_id"], probe["key"], setting_type
                )
            observed[probe["key"]] = {"ok": True, "value": value}
        except Exception as exc:
            observed[probe["key"]] = {"ok": False, "error": str(exc)}
    return {"observed": observed}


def _run_activate(skin, job):
    """Run BM-018A activation inside Kodi, including its confirmation gate."""
    backend = skin.KodiRuntimeSkinBackend()
    result = skin.SkinActivator(backend, timeout=30.0).activate(
        job["skin_id"]
    )
    return {
        "status": result.status.value,
        "addon_id": result.addon_id,
        "active_skin": result.active_skin,
        "message": result.message,
        "persisted_skin": backend.get_skin_setting(),
        "loaded_skin": backend.get_active_skin(),
    }


def _run_external_skin_write(config, job):
    """Perform a harness-only external skin-setting write for drift testing."""
    backend = config.KodiRuntimeConfigurationBackend()
    target_kind = config.ConfigTargetKind(job.get("target", "skin"))
    if target_kind != config.ConfigTargetKind.SKIN:
        raise ValueError("BM-018D external writes must target skin settings")
    setting_type = config.ConfigSettingType(job["type"])
    backend.set_skin_setting(
        job["skin_id"], job["key"], setting_type, job["value"]
    )
    return {"written": True}


def _run_build_manager(addon_root, job):
    """Invoke the real BM-020A executor inside disposable Kodi."""
    from resources.lib.build_manager import BuildManager, ReconcileRequest

    manifest_filename = job.get("manifest_filename", "bm020a-executor.example.json")
    if (
        not isinstance(manifest_filename, str)
        or not manifest_filename.endswith(".json")
        or os.path.basename(manifest_filename) != manifest_filename
    ):
        raise ValueError("manifest_filename must be a fixture JSON filename")
    manifest_path = os.path.join(
        addon_root, "resources", "builds", "examples", manifest_filename
    )
    request = ReconcileRequest(
        manifest_path=manifest_path,
        device_profile_id=job.get("device_profile_id", "family-room"),
    )
    result = BuildManager().reconcile(request)
    payload = result.to_dict()
    if result.validation_report is not None:
        payload["validation_checks"] = [
            {
                "domain": check.domain.value,
                "subject": check.subject,
                "status": check.status.value,
                "expected": check.expected,
                "actual_state": check.actual_state,
                "reason": check.reason,
            }
            for check in result.validation_report.checks
        ]
    configure_result = next(
        (
            item.owner_result
            for item in result.action_results
            if item.action.kind == "CONFIGURE"
        ),
        None,
    )
    if configure_result is not None:
        payload["configuration_summary"] = {
            "setting_targets": [item.target for item in configure_result.settings],
            "file_targets": [item.target for item in configure_result.files],
            "changed_targets": [item.target for item in configure_result.changed],
            "unchanged_targets": [item.target for item in configure_result.unchanged],
        }
    payload["owner_dispatch"] = [
        {
            "action_kind": action["kind"],
            "owner": {
                "INSTALL_REPOSITORY": "RepositoryManager",
                "INSTALL_ADDON": "DependencyAwareInstaller",
                "ENABLE_ADDON": "AddonStateReconciler",
                "DISABLE_ADDON": "AddonStateReconciler",
                "SET_SKIN": "SkinActivator",
                "CONFIGURE": "ConfigurationManager",
            }.get(action["kind"], "unknown"),
        }
        for action in payload["planned_actions"]
    ]
    return payload


def main():
    payload = {"ok": False}
    nonce = ""
    try:
        with open(JOB_PATH, "r") as handle:
            job = json.load(handle)
        nonce = job.get("nonce", "")
        addon_root = xbmcvfs.translatePath(job["addon_root"])
        config, manifest = _load_production_modules(addon_root)
        if job.get("mode") == "activate":
            import resources.lib.skin as skin
            payload = _run_activate(skin, job)
        elif job.get("mode") == "external_skin_write":
            payload = _run_external_skin_write(config, job)
        elif job.get("mode") == "observe":
            payload = _run_observe(config, job)
        elif job.get("mode") == "bootstrap_skin_schema":
            import xbmc
            commands = (
                "Skin.SetBool(View.UseDetailedListLabels)",
                "Skin.SetBool(Widgets.EnableShowMore)",
                "Skin.SetBool(Widgets.DisableNoResultsItem)",
                "Skin.Reset(Widgets.DisableNoResultsItem)",
                "Skin.SetString(Navigation.OnBack,Previous)",
            )
            for command in commands:
                try:
                    xbmc.executebuiltin(command, True)
                except TypeError:
                    xbmc.executebuiltin(command)
            payload = {"written": list(commands)}
        elif job.get("mode") == "build_manager":
            payload = _run_build_manager(addon_root, job)
        elif job.get("mode") == "frozen_install":
            from pathlib import Path
            from resources.lib.artifacts import ArtifactStore
            from resources.lib.build_manager import BuildManager, ReconcileResult
            from resources.lib.frozen import FrozenBuildManifest
            from resources.lib.frozen_install import (
                FrozenInstallCoordinator,
                FrozenInstallStore,
                KodiRuntimeFrozenArtifactBackend,
            )
            from resources.lib.restart import RestartReport, RestartRequirement
            from resources.lib.restart_coordinator import RestartCoordinator
            from resources.lib.update_guard import KodiJsonRpcUpdatePolicyBackend

            def _policy_rpc(method, params):
                import xbmc
                response = json.loads(xbmc.executeJSONRPC(json.dumps({
                    "jsonrpc": "2.0", "method": method, "params": params, "id": 1,
                })))
                return response.get("result", response)

            manifest_path = job["manifest_path"]
            configuration_path = job["configuration_manifest_path"]
            manifest = FrozenBuildManifest.from_json(
                Path(manifest_path).read_text(encoding="utf-8")
            )
            manager = BuildManager()
            if job.get("force_restart"):
                def _configure_then_request_restart(configuration_request):
                    real_result = manager.reconcile(configuration_request)
                    if not real_result.success or not real_result.desired_fingerprint:
                        failure = (
                            real_result.failure.to_dict()
                            if real_result.failure is not None
                            else {"code": "UNKNOWN", "message": "no failure detail"}
                        )
                        failure["actions"] = [
                            {
                                "action": result.action.kind,
                                "addon_id": result.action.addon_id,
                                "succeeded": result.succeeded,
                                "changed": result.changed,
                                "message": result.message,
                                "owner_failures": [
                                    getattr(failed, "detail", "")
                                    for failed in getattr(result.owner_result, "failed", ())
                                ],
                            }
                            for result in real_result.action_results
                        ]
                        owner_failures = [
                            getattr(failed, "detail", "")
                            for result in real_result.action_results
                            for failed in getattr(result.owner_result, "failed", ())
                            if getattr(failed, "detail", "")
                        ]
                        if owner_failures:
                            failure["message"] = owner_failures[0]
                        raise RuntimeError(
                            "BM-022 configuration failed: "
                            f"{failure}"
                        )
                    trigger = ReconcileResult(
                        success=True,
                        request=configuration_request,
                        desired_fingerprint=real_result.desired_fingerprint,
                        restart_report=RestartReport(RestartRequirement.KODI_RESTART, 1, 0),
                    )
                    return RestartCoordinator(manager).handle_result(configuration_request, trigger)

                configuration_runner = _configure_then_request_restart
            else:
                configuration_runner = lambda request: RestartCoordinator(manager).reconcile(request)
            coordinator = FrozenInstallCoordinator(
                store=FrozenInstallStore(),
                artifact_store=ArtifactStore(Path(job["artifact_root"])),
                policy_backend=KodiJsonRpcUpdatePolicyBackend(_policy_rpc),
                installer=KodiRuntimeFrozenArtifactBackend(),
                configuration_runner=configuration_runner,
            )
            result = coordinator.install(
                manifest,
                manifest_path=manifest_path,
                device_profile_id=job["device_profile_id"],
                configuration_manifest_path=configuration_path,
            )
            installed = {}
            for node in manifest.addons:
                if node.system:
                    continue
                detail = coordinator.installer.get_addon_details(node.addon_id)
                installed[node.addon_id] = (
                    {
                        "version": detail.version,
                        "enabled": detail.enabled,
                        "broken": detail.broken,
                    }
                    if detail is not None else None
                )
            transaction = FrozenInstallStore().inspect()
            policy_readback = _policy_rpc(
                "Settings.GetSettingValue",
                {"setting": "general.addonupdates"},
            )
            payload = {
                "outcome": result.outcome,
                "code": result.code,
                "message": result.message,
                "transaction": transaction.to_dict() if transaction else None,
                "installed": installed,
                "installation_order": list(coordinator.installer.install_order),
                "policy": policy_readback.get("value") if isinstance(policy_readback, dict) else None,
                "policy_readback": policy_readback,
            }
        elif job.get("mode") == "frozen_inspect":
            from resources.lib.frozen_install import FrozenInstallStore
            transaction = FrozenInstallStore().inspect()
            payload = {"transaction": transaction.to_dict() if transaction else None}
        elif job.get("mode") == "frozen_observe_setting":
            import xbmcaddon
            addon = xbmcaddon.Addon(job["addon_id"])
            payload = {"value": addon.getSettingBool(job["key"])}
        elif job.get("mode") == "transaction_prepare":
            from resources.lib.build_manager import ReconcileRequest, ReconcileResult
            from resources.lib.restart import RestartReport, RestartRequirement
            from resources.lib.transaction import (
                TransactionStore,
                prepare_restart_transaction,
            )
            request = ReconcileRequest(
                manifest_path="/harness/bm020b-selector-only.json",
                device_profile_id="bm020b-disposable",
            )
            reconcile_result = ReconcileResult(
                success=True,
                request=request,
                desired_fingerprint="sha256:" + "b" * 64,
                restart_report=RestartReport(
                    RestartRequirement.KODI_RESTART, 1, 0
                ),
            )
            prepared = prepare_restart_transaction(
                request,
                reconcile_result,
                job["session_id"],
                store=TransactionStore(),
            )
            payload = {
                "created": prepared.created,
                "succeeded": prepared.succeeded,
                "failure": (
                    {"code": prepared.failure.code, "message": prepared.failure.message}
                    if prepared.failure else None
                ),
                "transaction": (
                    prepared.transaction.to_dict() if prepared.transaction else None
                ),
            }
        elif job.get("mode") == "transaction_session":
            from resources.lib.session import get_current_kodi_session_id
            payload = {"session_id": get_current_kodi_session_id()}
        elif job.get("mode") == "transaction_startup_property":
            import xbmcgui
            from resources.lib.startup import STARTUP_CLASSIFICATION_PROPERTY
            payload = {
                "classification": xbmcgui.Window(10000).getProperty(
                    STARTUP_CLASSIFICATION_PROPERTY
                )
            }
        elif job.get("mode") == "transaction_resume_properties":
            import xbmcgui
            from resources.lib.startup import (
                RESUME_FINGERPRINT_PROPERTY,
                RESUME_OUTCOME_PROPERTY,
                RESUME_REQUIREMENT_PROPERTY,
                STARTUP_CLASSIFICATION_PROPERTY,
            )
            window = xbmcgui.Window(10000)
            payload = {
                "classification": window.getProperty(STARTUP_CLASSIFICATION_PROPERTY),
                "resume_outcome": window.getProperty(RESUME_OUTCOME_PROPERTY),
                "resume_fingerprint": window.getProperty(RESUME_FINGERPRINT_PROPERTY),
                "resume_requirement": window.getProperty(RESUME_REQUIREMENT_PROPERTY),
            }
        elif job.get("mode") == "transaction_classify":
            from resources.lib.startup import classify_startup_transaction
            from resources.lib.transaction import TransactionStore
            status = classify_startup_transaction(
                job["session_id"], store=TransactionStore()
            )
            payload = {
                "classification": status.classification.value,
                "eligible_for_resume": status.eligible_for_resume,
                "code": status.code,
                "message": status.message,
                "transaction": (
                    status.transaction.to_dict() if status.transaction else None
                ),
            }
        elif job.get("mode") == "transaction_clear":
            from resources.lib.transaction import TransactionStore
            payload = {"cleared": TransactionStore().clear()}
        elif job.get("mode") == "transaction_inspect":
            from resources.lib.transaction import TransactionStore
            transaction = TransactionStore().inspect()
            payload = {
                "transaction": transaction.to_dict() if transaction else None,
            }
        elif job.get("mode") == "restart_manual_trigger":
            from resources.lib.build_manager import BuildManager, ReconcileRequest, ReconcileResult
            from resources.lib.restart import RestartReport, RestartRequirement
            from resources.lib.restart_coordinator import (
                RestartCapabilityResolver,
                RestartCoordinator,
            )
            from resources.lib.session import get_current_kodi_session_id

            manifest_path = os.path.join(
                addon_root, "resources", "builds", "examples",
                job.get("manifest_filename", "bm020a-executor.example.json"),
            )
            request = ReconcileRequest(
                manifest_path=manifest_path,
                device_profile_id=job.get("device_profile_id", "bm020a-disposable"),
            )
            manager = BuildManager()
            real_result = manager.reconcile(request)
            if not real_result.success or not real_result.desired_fingerprint:
                payload = {
                    "real_result": real_result.to_dict(),
                    "coordinator": None,
                    "session_id": get_current_kodi_session_id(),
                }
            else:
                # This typed result is the test-only hypothetical trigger. The
                # request and fingerprint are real; only the restart requirement
                # is synthetic because no current production operation needs it.
                trigger = ReconcileResult(
                    success=True,
                    request=request,
                    desired_fingerprint=real_result.desired_fingerprint,
                    restart_report=RestartReport(
                        RestartRequirement.KODI_RESTART, 1, 0
                    ),
                )
                coordinator = RestartCoordinator(
                    manager,
                    capability_resolver=RestartCapabilityResolver(
                        platform_id=job.get("platform", "macos")
                    ),
                )
                coordinated = coordinator.handle_result(request, trigger)
                payload = {
                    "real_result": real_result.to_dict(),
                    "trigger": trigger.to_dict(),
                    "coordinator": coordinated.to_dict(),
                    "session_id": get_current_kodi_session_id(),
                }
        else:
            payload = _run_apply(config, manifest, job)
        payload["ok"] = True
    except Exception as exc:
        payload = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    payload["nonce"] = nonce
    with open(RESULT_PATH, "w") as handle:
        json.dump(payload, handle)


main()
''' % {"job": _BM015_JOB_FILE, "result": _BM015_RESULT_FILE}
    (target / "default.py").write_text(runner_py, encoding="utf-8")
    print(f"  BM-015 config runner written to {target}")


def _bm015_run_job(job: Dict[str, Any], *, timeout: float = 90.0) -> Dict[str, Any]:
    """Execute one job inside the disposable Kodi and return the parsed result."""
    job_path = KODI_USERDATA_DIR / _BM015_JOB_FILE
    result_path = KODI_USERDATA_DIR / _BM015_RESULT_FILE

    payload = dict(job)
    payload.setdefault("addon_root", f"special://home/addons/{ADDON_ID}")
    payload["nonce"] = f"{time.time_ns():x}"

    if result_path.exists():
        result_path.unlink()
    job_path.write_text(json.dumps(payload), encoding="utf-8")

    jsonrpc("Addons.ExecuteAddon", {
        "addonid": _BM015_RUNNER_ADDON_ID,
        "wait": False,
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        if result_path.exists():
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
            except ValueError:
                time.sleep(0.2)
                continue
            if data.get("nonce") == payload["nonce"]:
                return data
        time.sleep(0.25)
    raise RuntimeError(
        f"BM-015 runner produced no result within {timeout}s "
        f"(mode={payload.get('mode', 'apply')})"
    )


def _bm015_declarations(*, managed_keys=None, packages=None, managed_files=None):
    """Build the job fragment describing manifest-declared configuration."""
    keys = list(_BM015_EXPECTED) if managed_keys is None else list(managed_keys)
    return {
        "packages": list(
            packages if packages is not None
            else [_BM015_PACKAGE_COMMON, _BM015_PACKAGE_DEVICE]
        ),
        "managed_settings": [{"addon_id": _BM015_TEST_ADDON_ID, "keys": keys}],
        "managed_files": list(
            managed_files if managed_files is not None else [_BM015_MANAGED_FILE]
        ),
    }


def _bm015_apply(**kwargs) -> Dict[str, Any]:
    job = _bm015_declarations(**kwargs)
    job["mode"] = "apply"
    return _bm015_run_job(job)


def _bm015_observe(keys=None) -> Dict[str, Any]:
    probes = list(_BM015_SETTING_TYPES) if keys is None else list(keys)
    result = _bm015_run_job({
        "mode": "observe",
        "observe": [
            {
                "addon_id": _BM015_TEST_ADDON_ID,
                "key": key,
                "type": _BM015_SETTING_TYPES[key],
            }
            for key in probes
        ],
    })
    if not result.get("ok"):
        raise RuntimeError(
            f"BM-015 observe failed: {result.get('error_type')}: "
            f"{result.get('error')}"
        )
    values = {}
    for key, entry in result["observed"].items():
        if not entry.get("ok"):
            raise RuntimeError(
                f"BM-015 observe could not read {key!r}: {entry.get('error')}"
            )
        values[key] = entry["value"]
    return values


def _bm015_assert_values(observed: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Compare observed typed values against expectations, number-aware."""
    for key, want in expected.items():
        got = observed[key]
        if isinstance(want, float) or isinstance(got, float):
            same = f"{float(got):.6g}" == f"{float(want):.6g}"
        elif isinstance(want, bool) or isinstance(got, bool):
            same = bool(got) is bool(want)
        else:
            same = got == want
        if not same:
            raise RuntimeError(
                f"Validation failed: setting {key!r} is {got!r}, expected {want!r}"
            )


def _bm015_managed_path() -> Path:
    return KODI_USERDATA_DIR / Path(*_BM015_MANAGED_FILE.split("/"))


def _bm015_unmanaged_path() -> Path:
    return KODI_USERDATA_DIR / Path(*_BM015_UNMANAGED_FILE.split("/"))


def _bm015_drift_setting_on_disk(key: str, value: str) -> None:
    """Externally rewrite a managed setting in the add-on's settings.xml.

    Performed with Kodi STOPPED so the edit is a genuine external change rather
    than one Kodi could overwrite from memory.
    """
    import xml.etree.ElementTree as ET
    path = KODI_USERDATA_DIR / "addon_data" / _BM015_TEST_ADDON_ID / "settings.xml"
    if not path.is_file():
        raise RuntimeError(f"expected Kodi-written settings at {path}")
    tree = ET.parse(str(path))
    root = tree.getroot()
    for element in root.iter("setting"):
        if element.get("id") == key:
            element.text = value
            tree.write(str(path), encoding="UTF-8", xml_declaration=True)
            return
    raise RuntimeError(f"setting {key!r} not present in {path}")


def _bm015_read_setting_on_disk(key: str) -> Optional[str]:
    import xml.etree.ElementTree as ET
    path = KODI_USERDATA_DIR / "addon_data" / _BM015_TEST_ADDON_ID / "settings.xml"
    if not path.is_file():
        return None
    for element in ET.parse(str(path)).getroot().iter("setting"):
        if element.get("id") == key:
            return element.text
    return None


def validate_config() -> None:
    """Live validation of BM-015 configuration package deployment.

    Exercises the REAL production path end to end. Kodi's typed add-on Settings
    API is in-process only, so the production ConfigPackageLoader,
    ConfigurationManager and KodiRuntimeConfigurationBackend are executed inside
    the disposable Kodi through a harness-only runner script add-on. Nothing is
    simulated: settings go through xbmcaddon.Addon(id).getSettings() and managed
    files are resolved through xbmcvfs.translatePath('special://profile/').

    Test add-on: plugin.video.bm015-config, installed from the disposable test
    repository, declaring one setting of each supported type plus one
    deliberately unmanaged setting.

    Packages (written into the disposable copy of Build Manager at the
    production embedded location resources/config/packages):
      bm015-common  — all four managed settings + managed file
      bm015-device  — overrides text/int/number + managed file
    bm015.bool therefore stays owned by the common layer, proving live overlay.

    Sequence (24 steps):
       1  Reset disposable harness + install Build Manager + configure web server
       2  Write BM-015 packages into the installed add-on's embedded package root
       3  Build test add-on ZIP + addons.xml + repo ZIP; start HTTP server (8922)
       4  Install harness trigger + BM-015 config runner into the disposable profile
       5  Launch Kodi + wait for ready
       6  Install test repository via RepositoryManager.install
       7  Enable harness add-ons; trigger a repository scan
       8  Install plugin.video.bm015-config via AddonManager.install; verify enabled
       9  Establish initial state: unmanaged sibling file present, managed file absent
      10  Observe baseline typed values through the production Kodi backend
      11  Apply BM-015 through the production path, in-process, inside Kodi
      12  Verify the apply result: operation count, statuses, overlay winners
      13  Verify typed setting values through the production Kodi backend
      14  Verify managed file exact byte content on disk
      15  Verify the unmanaged setting is untouched
      16  Verify the unmanaged sibling file is untouched
      17  Apply the identical configuration again -> zero mutations (idempotency)
      18  Feed BM-015's validation_state to BM-014 -> CONFIGURATION domain PASS
      19  Drift a managed setting externally (Kodi stopped, settings.xml edited)
      20  Drift the managed file externally
      21  Preflight proof: an ownership-violating job fails with zero mutations
      22  Reapply the correct configuration -> both drifts repaired and verified
      23  Restart Kodi -> verify persistence; a third apply makes zero mutations
      24  Stop Kodi + shut down HTTP server; verify the real Kodi profile untouched

    ALL mutation occurs only inside .kodi-test. The real Kodi profile is never
    read, written, or modified.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.addons import AddonManager, AddonStatus
    from resources.lib.config import (
        ConfigPackageLoader,
        ConfigurationValidationState,
    )
    from resources.lib.dependencies import DependencyResolver
    from resources.lib.inspector import KodiStateInspector
    from resources.lib.manifest import (
        AddonEntry,
        BuildInfo,
        ConfigDeclarations,
        ManagedSettingScope,
        Repository,
        SkinEntry,
    )
    from resources.lib.repository import RepositoryManager, RepositoryStatus
    from resources.lib.resolver import ResolvedBuild
    from resources.lib.validator import (
        ValidationDomain,
        ValidationStatus,
        validate_build_state,
    )

    print("=== Build Manager BM-015 live validation: configuration deployment ===")
    verify_isolation()

    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    print("\n[1/24] reset disposable harness + install Build Manager + configure web server")
    reset()
    install(source=PROJECT)
    configure_webserver()

    print("\n[2/24] write BM-015 packages into the installed embedded package root")
    _write_bm015_packages()

    print("\n[3/24] build BM-015 test add-on ZIP + addons.xml + repo ZIP; start HTTP server")
    test_addon_zip = _make_bm015_test_addon_zip()
    addons_xml = _make_bm015_addons_xml()
    addons_xml_md5 = hashlib.md5(addons_xml).hexdigest().encode("utf-8")
    repo_zip = _make_bm011_repo_zip(_ADDON_SERVER_PORT)
    server_files = {
        f"/{_TEST_REPO_ADDON_ID}.zip": repo_zip,
        "/addons.xml": addons_xml,
        "/addons.xml.md5": addons_xml_md5,
        (
            f"/{_BM015_TEST_ADDON_ID}/{_BM015_TEST_ADDON_VERSION}/"
            f"{_BM015_TEST_ADDON_ID}-{_BM015_TEST_ADDON_VERSION}.zip"
        ): test_addon_zip,
    }

    class _Handler(_MultiFileHandler):
        _files = server_files  # type: ignore[assignment]

    server = http.server.HTTPServer(("127.0.0.1", _ADDON_SERVER_PORT), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    repo_url = f"http://127.0.0.1:{_ADDON_SERVER_PORT}/{_TEST_REPO_ADDON_ID}.zip"
    print(f"  serving {len(server_files)} paths on 127.0.0.1:{_ADDON_SERVER_PORT}")

    print("\n[4/24] install harness trigger + BM-015 config runner")
    _install_harness_trigger_script()
    _install_bm015_config_runner()

    addon_backend = _HttpAddonBackend()
    addon_mgr = AddonManager(addon_backend)
    repo_mgr = RepositoryManager(_HttpRepositoryBackend())
    inspector = KodiStateInspector(backend=_HttpKodiStateBackend())
    dep_resolver = DependencyResolver(_HttpDependencyBackend(addon_backend))
    test_repo = Repository(addon_id=_TEST_REPO_ADDON_ID, bootstrap_url=repo_url)

    managed_path = _bm015_managed_path()
    unmanaged_path = _bm015_unmanaged_path()

    try:
        print("\n[5/24] launch Kodi + wait for ready (up to 90s)")
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            stop()
            raise RuntimeError(f"Validation failed at step 5: {exc}") from exc

        print("\n[6/24] install test repository via RepositoryManager.install")
        repo_result = repo_mgr.install(test_repo)
        if repo_result.status != RepositoryStatus.INSTALLED:
            raise RuntimeError(
                f"Validation failed: repo install status="
                f"{repo_result.status.value!r}: {repo_result.message}"
            )
        print(f"  repository {_TEST_REPO_ADDON_ID!r} installed ✓")

        print("\n[7/24] enable harness add-ons; trigger repository scan")
        for harness_id in (_HARNESS_TRIGGER_ADDON_ID, _BM015_RUNNER_ADDON_ID):
            jsonrpc("Addons.SetAddonEnabled",
                    {"addonid": harness_id, "enabled": True})
            detail = jsonrpc("Addons.GetAddonDetails",
                             {"addonid": harness_id, "properties": ["enabled"]})
            if not (
                isinstance(detail, dict)
                and isinstance(detail.get("addon"), dict)
                and detail["addon"].get("enabled") is True
            ):
                raise RuntimeError(
                    f"Validation failed: could not enable {harness_id!r}: {detail!r}"
                )
            print(f"  {harness_id!r} enabled ✓")
        jsonrpc("Addons.ExecuteAddon", {
            "addonid": _HARNESS_TRIGGER_ADDON_ID,
            "params": "update_repos",
            "wait": False,
        })
        _wait_for_addon_in_repo_index(_BM015_TEST_ADDON_ID, timeout=90.0)

        print(f"\n[8/24] install {_BM015_TEST_ADDON_ID!r} via AddonManager.install")
        install_result = addon_mgr.install(
            _BM015_TEST_ADDON_ID, desired_state="enabled"
        )
        if install_result.status not in (
            AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED
        ):
            raise RuntimeError(
                f"Validation failed: {_BM015_TEST_ADDON_ID!r} install status="
                f"{install_result.status.value!r}: {install_result.message}"
            )
        details = addon_backend.get_addon_details(_BM015_TEST_ADDON_ID)
        if details is None or not details.enabled:
            raise RuntimeError(
                f"Validation failed: {_BM015_TEST_ADDON_ID!r} not enabled "
                f"after install"
            )
        print(f"  {_BM015_TEST_ADDON_ID!r} installed+enabled (v{details.version}) ✓")

        print("\n[9/24] establish initial state (unmanaged sibling present, managed absent)")
        unmanaged_path.parent.mkdir(parents=True, exist_ok=True)
        unmanaged_path.write_bytes(_BM015_UNMANAGED_CONTENT)
        if managed_path.exists():
            managed_path.unlink()
        print(f"  unmanaged sibling written: {unmanaged_path.name} ✓")
        print(f"  managed file absent: {managed_path.name} ✓")

        print("\n[10/24] observe baseline typed values through the production backend")
        baseline = _bm015_observe()
        _bm015_assert_values(baseline, _BM015_DEFAULTS)
        for key in sorted(_BM015_DEFAULTS):
            print(f"  {key} = {baseline[key]!r} (add-on default) ✓")
        for key, expected in _BM015_EXPECTED.items():
            if baseline[key] == expected:
                raise RuntimeError(
                    f"Validation failed: {key!r} already equals the package value "
                    f"before deployment; drift repair could not be proven"
                )
        print("  every managed setting differs from its package value ✓")

        print("\n[11/24] apply BM-015 through the production path inside Kodi")
        applied = _bm015_apply()
        if not applied.get("ok"):
            raise RuntimeError(
                f"Validation failed: apply raised "
                f"{applied.get('error_type')}: {applied.get('error')}\n"
                f"{applied.get('traceback', '')}"
            )
        print(f"  packages_root = {applied['packages_root']!r}")
        print(f"  packages applied = {applied['packages']}")
        if applied["packages"] != [_BM015_PACKAGE_COMMON, _BM015_PACKAGE_DEVICE]:
            raise RuntimeError(
                f"Validation failed: unexpected package order {applied['packages']}"
            )
        expected_root = str(
            _bm015_installed_packages_root().resolve()
        )
        if os.path.realpath(applied["packages_root"]) != os.path.realpath(expected_root):
            raise RuntimeError(
                f"Validation failed: default_packages_root() resolved to "
                f"{applied['packages_root']!r}, expected {expected_root!r}"
            )
        print("  default_packages_root() resolved to the installed add-on ✓")

        print("\n[12/24] verify apply result: statuses and overlay winners")
        if not applied["all_applied"]:
            raise RuntimeError(
                f"Validation failed: operations failed: {applied['failed']}"
            )
        operations = {op["target"]: op for op in applied["operations"]}
        if len(operations) != 5:
            raise RuntimeError(
                f"Validation failed: expected 5 operations, got {len(operations)}: "
                f"{sorted(operations)}"
            )
        for key, package_id in _BM015_EXPECTED_PACKAGE.items():
            target = f"{_BM015_TEST_ADDON_ID}/{key}"
            op = operations[target]
            if op["status"] != "updated":
                raise RuntimeError(
                    f"Validation failed: {target} status={op['status']!r}, "
                    f"expected 'updated'"
                )
            if op["package_id"] != package_id:
                raise RuntimeError(
                    f"Validation failed: {target} winning package was "
                    f"{op['package_id']!r}, expected {package_id!r}"
                )
            print(f"  {target} updated by {package_id!r} ✓")
        file_op = operations[_BM015_MANAGED_FILE]
        if file_op["status"] != "created":
            raise RuntimeError(
                f"Validation failed: managed file status={file_op['status']!r}, "
                f"expected 'created'"
            )
        if file_op["package_id"] != _BM015_PACKAGE_DEVICE:
            raise RuntimeError(
                f"Validation failed: managed file supplied by "
                f"{file_op['package_id']!r}, expected {_BM015_PACKAGE_DEVICE!r}"
            )
        print(f"  {_BM015_MANAGED_FILE} created by {_BM015_PACKAGE_DEVICE!r} ✓")
        for op in applied["operations"]:
            for value in (_BM015_EXPECTED["bm015.text"],
                          _BM015_COMMON_VALUES["bm015.text"]):
                if value in json.dumps(op):
                    raise RuntimeError(
                        f"Validation failed: raw setting value leaked into the "
                        f"operation result for {op['target']}"
                    )
        print("  no raw setting value appears in any operation result ✓")

        print("\n[13/24] verify typed setting values through the production backend")
        observed = _bm015_observe()
        _bm015_assert_values(observed, _BM015_EXPECTED)
        for key in sorted(_BM015_EXPECTED):
            print(f"  {key} = {observed[key]!r} ✓")

        print("\n[14/24] verify managed file exact byte content")
        if not managed_path.is_file():
            raise RuntimeError(f"Validation failed: {managed_path} was not created")
        content = managed_path.read_bytes()
        if content != _BM015_DEVICE_FILE_CONTENT:
            raise RuntimeError(
                f"Validation failed: managed file content is {content!r}, "
                f"expected the device-layer content"
            )
        print(f"  {managed_path.name} matches the device-layer content exactly ✓")

        print("\n[15/24] verify the unmanaged setting is untouched")
        if observed["bm015.unmanaged"] != _BM015_DEFAULTS["bm015.unmanaged"]:
            raise RuntimeError(
                f"Validation failed: unmanaged setting changed to "
                f"{observed['bm015.unmanaged']!r}"
            )
        print(f"  bm015.unmanaged = {observed['bm015.unmanaged']!r} (unchanged) ✓")

        print("\n[16/24] verify the unmanaged sibling file is untouched")
        if unmanaged_path.read_bytes() != _BM015_UNMANAGED_CONTENT:
            raise RuntimeError(
                f"Validation failed: unmanaged sibling {unmanaged_path} changed"
            )
        siblings = sorted(p.name for p in managed_path.parent.iterdir())
        print(f"  {unmanaged_path.name} unchanged ✓")
        print(f"  addon_data contents: {siblings}")

        print("\n[17/24] apply identical configuration again → zero mutations")
        again = _bm015_apply()
        if not again.get("ok"):
            raise RuntimeError(
                f"Validation failed: second apply raised "
                f"{again.get('error_type')}: {again.get('error')}"
            )
        if again["changed"]:
            raise RuntimeError(
                f"Validation failed: idempotency violated, second apply changed "
                f"{again['changed']}"
            )
        if len(again["unchanged"]) != 5:
            raise RuntimeError(
                f"Validation failed: expected 5 ALREADY_CORRECT results, got "
                f"{len(again['unchanged'])}"
            )
        print("  5/5 operations ALREADY_CORRECT, 0 mutations ✓")

        print("\n[18/24] feed BM-015 artifacts to BM-014 validate_build_state")
        snapshot = again["validation_state"]
        if not snapshot["is_fully_verified"]:
            raise RuntimeError(
                f"Validation failed: snapshot not fully verified: {snapshot}"
            )
        state = ConfigurationValidationState(
            effective_identity=snapshot["effective_identity"],
            setting_targets=tuple(
                tuple(t) for t in snapshot["setting_targets"]
            ),
            file_targets=tuple(snapshot["file_targets"]),
            verified_settings=tuple(
                tuple(t) for t in snapshot["verified_settings"]
            ),
            verified_files=tuple(snapshot["verified_files"]),
        )

        config_declarations = ConfigDeclarations(
            packages=(_BM015_PACKAGE_COMMON, _BM015_PACKAGE_DEVICE),
            managed_settings=(
                ManagedSettingScope(
                    addon_id=_BM015_TEST_ADDON_ID,
                    keys=tuple(_BM015_EXPECTED),
                ),
            ),
            managed_files=(_BM015_MANAGED_FILE,),
        )
        # Resolve the same packages outside Kodi (the loader is pure) to obtain
        # the EffectiveConfiguration BM-014 needs as its expected snapshot.
        harness_loader = ConfigPackageLoader(
            str(_bm015_installed_packages_root())
        )
        effective = harness_loader.resolve(config_declarations)
        if effective.identity != again["effective_identity"]:
            raise RuntimeError(
                f"Validation failed: effective identity resolved in Kodi "
                f"({again['effective_identity']}) differs from the identity "
                f"resolved by the harness ({effective.identity})"
            )
        if state.effective_identity != effective.identity:
            raise RuntimeError(
                "Validation failed: snapshot is not bound to the effective "
                "configuration identity"
            )
        print(f"  effective identity = {effective.identity}")
        print("  in-Kodi and harness resolutions agree on the identity ✓")

        actual = inspector.inspect()
        desired = ResolvedBuild(
            build=BuildInfo(id="bm015-test", version="1.0.0",
                            name="BM-015 Test Build"),
            engine_min_version="1.0.0",
            platform_profile_id=actual.platform,
            device_profile_id="disposable-kodi-test",
            repositories=(
                Repository(addon_id=_TEST_REPO_ADDON_ID,
                           bootstrap_url=repo_url, required=True),
            ),
            addons=(AddonEntry(addon_id=_BM015_TEST_ADDON_ID, state="enabled"),),
            skin=SkinEntry(addon_id=actual.active_skin),
            config=config_declarations,
            optional_groups_applied=(),
            restart_policy=None,
            private_overlay=None,
        )
        closure = dep_resolver.resolve_closure([_BM015_TEST_ADDON_ID])

        def _config_checks(report):
            return [
                c for c in report.checks
                if c.domain == ValidationDomain.CONFIGURATION
            ]

        def _expect_not_checked(label, **kwargs):
            checks = _config_checks(
                validate_build_state(desired, actual, closure, **kwargs)
            )
            if (len(checks) != 1
                    or checks[0].status != ValidationStatus.NOT_CHECKED):
                raise RuntimeError(
                    f"Validation failed: {label} must yield a single "
                    f"NOT_CHECKED configuration check, got "
                    f"{[(c.subject, c.status.value) for c in checks]}"
                )
            print(f"  {label}: CONFIGURATION = NOT_CHECKED ✓")

        _expect_not_checked("no artifacts")
        _expect_not_checked("state only", configuration_state=state)
        _expect_not_checked("effective only", effective_configuration=effective)

        report = validate_build_state(
            desired, actual, closure,
            configuration_state=state, effective_configuration=effective,
        )
        config_checks = _config_checks(report)
        if len(config_checks) != 5 or not all(
            c.status == ValidationStatus.PASS for c in config_checks
        ):
            detail = "\n".join(
                f"    [{c.status.value}] {c.subject}: {c.reason}"
                for c in config_checks
            )
            raise RuntimeError(
                f"Validation failed: expected 5 PASS configuration checks:\n{detail}"
            )
        if not report.passed:
            detail = "\n".join(
                f"    [{c.status.value}] {c.domain.value} {c.subject}: {c.reason}"
                for c in report.failures + report.not_checked
            )
            raise RuntimeError(f"Validation failed: report not passed:\n{detail}")
        print("  matching pair: 5/5 CONFIGURATION checks PASS, passed=True ✓")

        partial = ConfigurationValidationState(
            effective_identity=state.effective_identity,
            setting_targets=state.setting_targets[:1],
            verified_settings=state.verified_settings[:1],
        )
        _expect_not_checked(
            "partial state",
            configuration_state=partial, effective_configuration=effective,
        )

        # Stale artifact: the managed scope is identical, only the desired
        # content differs. Scope comparison alone would false-pass here.
        stale_declarations = ConfigDeclarations(
            packages=(_BM015_PACKAGE_COMMON,),
            managed_settings=config_declarations.managed_settings,
            managed_files=config_declarations.managed_files,
        )
        stale_effective = harness_loader.resolve(stale_declarations)
        stale_targets = {(s.addon_id, s.key) for s in stale_effective.settings}
        if stale_targets != {(s.addon_id, s.key) for s in effective.settings}:
            raise RuntimeError(
                "Validation failed: the stale fixture must have an identical "
                "managed scope for this proof to mean anything"
            )
        if stale_effective.identity == effective.identity:
            raise RuntimeError(
                "Validation failed: differing desired values must produce "
                "different effective identities"
            )
        print(f"  stale identity    = {stale_effective.identity}")
        stale_state = ConfigurationValidationState(
            effective_identity=stale_effective.identity,
            setting_targets=state.setting_targets,
            file_targets=state.file_targets,
            verified_settings=state.verified_settings,
            verified_files=state.verified_files,
        )
        _expect_not_checked(
            "stale state (same scope, different desired content)",
            configuration_state=stale_state, effective_configuration=effective,
        )

        print("\n[19/24] drift a managed setting externally (Kodi stopped)")
        stop()
        _bm015_drift_setting_on_disk("bm015.text", "externally-drifted")
        on_disk = _bm015_read_setting_on_disk("bm015.text")
        if on_disk != "externally-drifted":
            raise RuntimeError(
                f"Validation failed: external drift not written, settings.xml "
                f"holds {on_disk!r}"
            )
        print(f"  settings.xml bm015.text = {on_disk!r} (external drift) ✓")
        launch()
        wait_for_ready(timeout=90.0)
        drifted = _bm015_observe(["bm015.text"])
        if drifted["bm015.text"] != "externally-drifted":
            raise RuntimeError(
                f"Validation failed: Kodi reports {drifted['bm015.text']!r} after "
                f"external drift"
            )
        print(f"  Kodi reports bm015.text = {drifted['bm015.text']!r} ✓")

        print("\n[20/24] drift the managed file externally")
        managed_path.write_bytes(b"externally drifted managed content\n")
        print(f"  {managed_path.name} overwritten outside Build Manager ✓")

        print("\n[21/24] preflight proof: ownership violation causes zero mutations")
        bad = _bm015_apply(managed_keys=["bm015.text", "bm015.bool", "bm015.number"])
        if bad.get("ok"):
            raise RuntimeError(
                "Validation failed: an ownership-violating job was accepted"
            )
        if bad.get("error_type") != "ConfigOwnershipError":
            raise RuntimeError(
                f"Validation failed: expected ConfigOwnershipError, got "
                f"{bad.get('error_type')}: {bad.get('error')}"
            )
        print(f"  ConfigOwnershipError: {bad['error']}")
        still_drifted = _bm015_observe(["bm015.text"])
        if still_drifted["bm015.text"] != "externally-drifted":
            raise RuntimeError(
                "Validation failed: a failed preflight mutated a setting"
            )
        if managed_path.read_bytes() != b"externally drifted managed content\n":
            raise RuntimeError(
                "Validation failed: a failed preflight mutated the managed file"
            )
        print("  drifted setting and drifted file both untouched ✓")

        print("\n[22/24] reapply correct configuration → both drifts repaired")
        repaired = _bm015_apply()
        if not repaired.get("ok"):
            raise RuntimeError(
                f"Validation failed: repair apply raised "
                f"{repaired.get('error_type')}: {repaired.get('error')}"
            )
        repaired_ops = {op["target"]: op for op in repaired["operations"]}
        text_target = f"{_BM015_TEST_ADDON_ID}/bm015.text"
        if repaired_ops[text_target]["status"] != "updated":
            raise RuntimeError(
                f"Validation failed: drifted setting status="
                f"{repaired_ops[text_target]['status']!r}, expected 'updated'"
            )
        if repaired_ops[_BM015_MANAGED_FILE]["status"] != "updated":
            raise RuntimeError(
                f"Validation failed: drifted file status="
                f"{repaired_ops[_BM015_MANAGED_FILE]['status']!r}, expected 'updated'"
            )
        if sorted(repaired["changed"]) != sorted([text_target, _BM015_MANAGED_FILE]):
            raise RuntimeError(
                f"Validation failed: expected exactly the two drifted targets to "
                f"change, got {repaired['changed']}"
            )
        print(f"  {text_target} repaired (UPDATED) ✓")
        print(f"  {_BM015_MANAGED_FILE} repaired (UPDATED) ✓")
        print("  the three undrifted targets stayed ALREADY_CORRECT ✓")
        after_repair = _bm015_observe()
        _bm015_assert_values(after_repair, _BM015_EXPECTED)
        if managed_path.read_bytes() != _BM015_DEVICE_FILE_CONTENT:
            raise RuntimeError("Validation failed: managed file not repaired")
        if after_repair["bm015.unmanaged"] != _BM015_DEFAULTS["bm015.unmanaged"]:
            raise RuntimeError(
                "Validation failed: unmanaged setting changed during repair"
            )
        if unmanaged_path.read_bytes() != _BM015_UNMANAGED_CONTENT:
            raise RuntimeError(
                "Validation failed: unmanaged sibling changed during repair"
            )
        print("  values, file content, and both unmanaged targets verified ✓")

        print("\n[23/24] restart Kodi → verify persistence and a zero-mutation apply")
        restart()
        wait_for_ready(timeout=90.0)
        persisted = _bm015_observe()
        _bm015_assert_values(persisted, _BM015_EXPECTED)
        if persisted["bm015.unmanaged"] != _BM015_DEFAULTS["bm015.unmanaged"]:
            raise RuntimeError(
                "Validation failed: unmanaged setting changed across restart"
            )
        if managed_path.read_bytes() != _BM015_DEVICE_FILE_CONTENT:
            raise RuntimeError(
                "Validation failed: managed file did not persist across restart"
            )
        if unmanaged_path.read_bytes() != _BM015_UNMANAGED_CONTENT:
            raise RuntimeError(
                "Validation failed: unmanaged sibling changed across restart"
            )
        print("  all four managed settings persisted across restart ✓")
        print("  managed file content persisted across restart ✓")
        print("  both unmanaged targets unchanged across restart ✓")
        third = _bm015_apply()
        if not third.get("ok") or third["changed"]:
            raise RuntimeError(
                f"Validation failed: post-restart apply changed "
                f"{third.get('changed')} (expected none)"
            )
        print("  post-restart apply: 0 mutations ✓")

    finally:
        print("\n[24/24] stop Kodi + shut down HTTP server")
        try:
            stop()
        except RuntimeError:
            pass
        server.shutdown()

    print("\n[24/24] verify real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! "
                f"Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-015 validation PASSED (24/24) ===\n")


# ---------------------------------------------------------------------------
# BM-018D live validation — typed AF3 skin configuration
# ---------------------------------------------------------------------------

_BM018D_SKIN_ID = "skin.arctic.fuse.3"
_BM018D_PACKAGE = "bm018d-af3"
_BM018D_BOOL_KEY = "HomeSwitcher.EnableIcons"
_BM018D_STRING_KEY = "HomeSwitcher.Home.Mode"
# A real AF3 string key intentionally outside the synthetic package's owned
# targets. Kodi rejects unknown skin-setting keys, so the unmanaged probe must
# exercise an existing schema entry rather than invent one.
_BM018D_UNMANAGED_KEY = "TMDbHelper.Corner.Radius"
_BM018D_BOOL_VALUE = True
_BM018D_STRING_VALUE = "Standard"
_BM018D_UNMANAGED_VALUE = "leave-me-alone"
_BM018D_AF3_SOURCE_ROOT = (
    Path.home() / "Library" / "Application Support" / "Kodi" / "addons"
)
_BM018E_MANIFEST = PROJECT / "resources" / "builds" / "examples" / "eric-main.example.json"
_BM018E_PROFILE = "family-room"
_BM020A_FIXTURE = "bm020a-executor.example.json"
_BM020A_PROFILE = "bm020a-disposable"
_BM020A_MANAGED_SETTINGS = {
    "HomeSwitcher.Vertical": ("bool", False),
    "HomeSwitcher.EnableIcons": ("bool", False),
    "HomeSwitcher.EnableIconText": ("bool", True),
    "HomeSwitcher.DisableHeader": ("bool", True),
    "HomeSwitcher.DisableDate": ("bool", True),
    "HomeSwitcher.DisableSearch": ("bool", False),
    "HomeSwitcher.DisableFirstWidgetFocus": ("bool", False),
    "HomeSwitcher.LoopBack": ("bool", False),
    "Spotlight.EnableSlide": ("bool", False),
    "Spotlight.UseMenuButton": ("bool", False),
    "View.UseDetailedListLabels": ("bool", True),
    "Widgets.EnableShowMore": ("bool", True),
    "Widgets.DisableNoResultsItem": ("bool", False),
    "Navigation.OnBack": ("string", "Previous"),
    "Seekbar.TimeDisplay": ("string", "Combined"),
    "Skin.FlixArt.Size": ("string", "ExtraLarge"),
}
_BM020A_UNMANAGED_KEY = "TMDbHelper.Corner.Radius"
_BM020A_UNMANAGED_VALUE = "bm020a-unmanaged"


def _bm018d_copy_af3_and_dependencies() -> tuple[str, ...]:
    """Copy AF3 and its complete transitive dependency closure.

    The source is the installed AF3 add-on tree, read-only. No profile data is
    copied. Built-in Kodi dependencies are supplied by Kodi and are skipped;
    every non-built-in declared dependency must be available in the installed
    add-on tree or the validation fails closed.
    """
    verify_isolation()
    source_root = _BM018D_AF3_SOURCE_ROOT
    if not (source_root / _BM018D_SKIN_ID / "addon.xml").is_file():
        raise RuntimeError(
            f"installed AF3 source not found at {source_root / _BM018D_SKIN_ID}"
        )

    pending = [_BM018D_SKIN_ID]
    seen = set()
    while pending:
        addon_id = pending.pop(0)
        if addon_id in seen or addon_id.startswith(("xbmc.", "kodi.")):
            continue
        seen.add(addon_id)
        source = source_root / addon_id
        if not (source / "addon.xml").is_file():
            system_source = KODI_SYSTEM_ADDONS_DIR / addon_id
            if (system_source / "addon.xml").is_file():
                source = system_source
        addon_xml = source / "addon.xml"
        if not addon_xml.is_file():
            raise RuntimeError(
                f"AF3 declared dependency {addon_id!r} is not available at {source}"
            )
        target = KODI_ADDONS_DIR / addon_id
        if target.exists():
            if not _inside(target, KODI_ADDONS_DIR):
                raise RuntimeError(f"unsafe AF3 target path: {target}")
            shutil.rmtree(target)
        shutil.copytree(source, target)
        try:
            root = ET.parse(addon_xml).getroot()
        except (ET.ParseError, OSError) as exc:
            raise RuntimeError(f"cannot parse AF3 add-on metadata {addon_xml}: {exc}") from exc
        for import_node in root.findall("./requires/import"):
            dependency = import_node.get("addon", "")
            if dependency and dependency not in seen:
                pending.append(dependency)
    print(
        f"  copied {_BM018D_SKIN_ID!r} and {len(seen) - 1} declared "
        f"non-built-in dependencies into {KODI_ADDONS_DIR} ✓"
    )
    return tuple(sorted(seen))


def _bm018d_verify_dependency_state(addon_ids: tuple[str, ...]) -> None:
    """Verify installed/enabled/not-broken state for AF3's full closure."""
    unhealthy = []
    for addon_id in addon_ids:
        detail = jsonrpc("Addons.GetAddonDetails", {
            "addonid": addon_id,
            "properties": ["enabled", "version", "broken"],
        })
        addon = detail.get("addon") if isinstance(detail, dict) else None
        if not isinstance(addon, dict):
            unhealthy.append((addon_id, "missing", detail))
            continue
        if addon.get("broken") is not False:
            unhealthy.append((addon_id, "broken", addon))
            continue
        if addon.get("enabled") is not True:
            jsonrpc("Addons.SetAddonEnabled", {
                "addonid": addon_id,
                "enabled": True,
            })
            detail = jsonrpc("Addons.GetAddonDetails", {
                "addonid": addon_id,
                "properties": ["enabled", "version", "broken"],
            })
            addon = detail.get("addon") if isinstance(detail, dict) else None
        status = (
            isinstance(addon, dict)
            and addon.get("enabled") is True,
            isinstance(addon, dict)
            and addon.get("broken") is False,
            addon.get("version") if isinstance(addon, dict) else None,
        )
        if not status[0] or not status[1]:
            unhealthy.append((addon_id, status, addon))
        print(
            f"  {addon_id}: installed=True enabled="
            f"{addon.get('enabled') if isinstance(addon, dict) else None!r} "
            f"broken={addon.get('broken') if isinstance(addon, dict) else None!r} "
            f"version={addon.get('version') if isinstance(addon, dict) else None!r}"
        )
    if unhealthy:
        raise RuntimeError(
            "AF3 dependency closure has unhealthy add-ons: "
            f"{unhealthy!r}"
        )
    print(f"  verified {len(addon_ids)}/{len(addon_ids)} AF3 closure add-ons healthy ✓")


def _bm018d_seed_first_run_guard() -> None:
    """Seed one synthetic AF3 first-run marker in the disposable profile.

    This marker is disposable test state only; no real profile settings or
    generated state are copied.
    """
    verify_isolation()
    target = (
        KODI_USERDATA_DIR / "addon_data" / _BM018D_SKIN_ID / "settings.xml"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '<settings>\n'
        '  <setting id="home.firstrun" type="bool">true</setting>\n'
        '</settings>\n',
        encoding="utf-8",
    )
    print("  seeded synthetic AF3 first-run guard in disposable profile ✓")


def _bm018d_warm_af3_runtime() -> None:
    """Let AF3 complete its first-run generated-state initialization once.

    AF3 3.2.19 and script.skinvariables generate/reload skin XML on the first
    activation of an otherwise empty profile. Kodi accepts the first skin
    confirmation, but that reload races the keep/revert transaction and Kodi
    falls back to Estuary while leaving the persisted setting at Estuary. The
    generated state is disposable runtime state, so initialize it here and
    then return to Estuary before the BM-018A gate.
    """
    first = _bm018d_activate(_BM018D_SKIN_ID)
    if first.get("status") == "activated":
        print("  AF3 first-run warm-up activated cleanly ✓")
    elif (
        first.get("active_skin") == "skin.estuary"
        and first.get("persisted_skin") == "skin.estuary"
    ):
        print(
            "  AF3 first-run warm-up reproduced the observed generated-state "
            "fallback; disposable AF3 runtime is now initialized ✓"
        )
    else:
        raise RuntimeError(f"AF3 warm-up had an unexpected result: {first}")
    if first.get("active_skin") != "skin.estuary":
        returned = _bm018d_activate("skin.estuary")
        if returned.get("status") != "activated":
            raise RuntimeError(f"could not return disposable Kodi to Estuary: {returned}")

    # Four AF3 settings are real Skin.* variables but are not present in
    # Kodi's typed m_settings map on a pristine profile. Exercise their
    # runtime paths once while AF3 is active so Kodi emits typed entries in
    # the disposable settings.xml. The production adapter still uses that
    # file only as a key/type eligibility guard; effective values continue to
    # come from Skin.HasSetting/Skin.String.
    bootstrap = _bm018d_activate(_BM018D_SKIN_ID)
    if bootstrap.get("status") not in ("activated", "already_active"):
        raise RuntimeError(f"could not activate AF3 for fallback bootstrap: {bootstrap}")
    bootstrap_result = _bm018d_run_job({"mode": "bootstrap_skin_schema"})
    if not bootstrap_result.get("ok"):
        raise RuntimeError(
            "AF3 fallback schema bootstrap failed: "
            f"{bootstrap_result.get('error_type')}: {bootstrap_result.get('error')}"
        )
    deadline = time.time() + 5.0
    fallback_ids = {
        "view.usedetailedlistlabels": "bool",
        "widgets.enableshowmore": "bool",
        "widgets.disablenoresultsitem": "bool",
        "navigation.onback": "string",
    }
    settings_path = (
        KODI_USERDATA_DIR / "addon_data" / _BM018D_SKIN_ID / "settings.xml"
    )
    while True:
        try:
            root = ET.parse(settings_path).getroot()
            observed = {
                (node.get("id") or node.get("name", "")).casefold(): node.get("type")
                for node in root.findall("setting")
            }
            if all(observed.get(key) == kind for key, kind in fallback_ids.items()):
                break
        except (ET.ParseError, OSError):
            pass
        if time.time() >= deadline:
            raise RuntimeError(
                "AF3 fallback schema bootstrap did not persist all typed entries"
            )
        time.sleep(0.1)
    returned = _bm018d_activate("skin.estuary")
    if returned.get("status") != "activated":
        raise RuntimeError(f"could not return disposable Kodi to Estuary: {returned}")
    print("  AF3 fallback Skin.* schema entries persisted in disposable profile ✓")


def _bm018d_install_runner() -> None:
    """Install the existing harness runner used for in-process Kodi APIs."""
    _install_bm015_config_runner()


def _bm018d_run_job(job: Dict[str, Any], *, timeout: float = 90.0) -> Dict[str, Any]:
    """Run one BM-018D operation through the installed production modules."""
    return _bm015_run_job(job, timeout=timeout)


def _bm018d_activate(skin_id: str) -> Dict[str, Any]:
    result = _bm018d_run_job({"mode": "activate", "skin_id": skin_id})
    if not result.get("ok"):
        raise RuntimeError(
            f"BM-018A activation runner failed: {result.get('error_type')}: "
            f"{result.get('error')}\n{result.get('traceback', '')}"
        )
    return result


def _write_bm018d_package() -> None:
    """Write a synthetic typed AF3 package into the disposable add-on copy."""
    verify_isolation()
    root = _bm015_installed_packages_root()
    package_dir = root / _BM018D_PACKAGE
    if package_dir.exists():
        if not _inside(package_dir, root):
            raise RuntimeError(f"unsafe BM-018D package path: {package_dir}")
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)
    descriptor = {
        "schema_version": 1,
        "id": _BM018D_PACKAGE,
        "settings": [
            {
                "target": "skin",
                "addon_id": _BM018D_SKIN_ID,
                "key": _BM018D_BOOL_KEY,
                "type": "bool",
                "value": _BM018D_BOOL_VALUE,
            },
            {
                "target": "skin",
                "addon_id": _BM018D_SKIN_ID,
                "key": _BM018D_STRING_KEY,
                "type": "string",
                "value": _BM018D_STRING_VALUE,
            },
        ],
    }
    (package_dir / "package.json").write_text(
        json.dumps(descriptor, indent=2), encoding="utf-8"
    )
    print(f"  wrote synthetic typed AF3 package to {package_dir} ✓")


def _bm018d_declarations(*, managed_keys=None) -> Dict[str, Any]:
    keys = [
        _BM018D_BOOL_KEY,
        _BM018D_STRING_KEY,
    ] if managed_keys is None else list(managed_keys)
    return {
        "packages": [_BM018D_PACKAGE],
        "managed_settings": [{
            "target": "skin",
            "addon_id": _BM018D_SKIN_ID,
            "keys": keys,
        }],
        "managed_files": [],
    }


def _bm018d_apply(*, managed_keys=None) -> Dict[str, Any]:
    job = _bm018d_declarations(managed_keys=managed_keys)
    job["mode"] = "apply"
    return _bm018d_run_job(job)


def _bm018d_observe(keys=None) -> Dict[str, Any]:
    keys = [
        _BM018D_BOOL_KEY,
        _BM018D_STRING_KEY,
    ] if keys is None else list(keys)
    result = _bm018d_run_job({
        "mode": "observe",
        "observe": [
            {
                "target": "skin",
                "addon_id": _BM018D_SKIN_ID,
                "key": key,
                "type": "bool" if key == _BM018D_BOOL_KEY else "string",
            }
            for key in keys
        ],
    })
    if not result.get("ok"):
        raise RuntimeError(
            f"BM-018D observe failed: {result.get('error_type')}: "
            f"{result.get('error')}"
        )
    observed = {}
    for key, entry in result.get("observed", {}).items():
        if not entry.get("ok"):
            raise RuntimeError(
                f"BM-018D observe could not read {key!r}: {entry.get('error')}"
            )
        observed[key] = entry["value"]
    return observed


def _bm018d_external_write(key: str, value: Any, setting_type: str) -> None:
    result = _bm018d_run_job({
        "mode": "external_skin_write",
        "target": "skin",
        "skin_id": _BM018D_SKIN_ID,
        "key": key,
        "type": setting_type,
        "value": value,
    })
    if not result.get("ok"):
        raise RuntimeError(
            f"BM-018D external write failed: {result.get('error_type')}: "
            f"{result.get('error')}"
        )


def _bm018e_apply(declarations) -> Dict[str, Any]:
    """Apply the production AF3 configuration through the live runner."""
    return _bm018d_run_job({
        "mode": "apply",
        "packages": list(declarations.packages),
        "managed_settings": [
            {
                "target": scope.target_kind.value,
                "addon_id": scope.addon_id,
                "keys": list(scope.keys),
            }
            for scope in declarations.managed_settings
        ],
        "managed_files": list(declarations.managed_files),
    })


def _bm018e_observe(effective) -> Dict[str, Any]:
    """Read every production AF3 target through the typed runtime backend."""
    result = _bm018d_run_job({
        "mode": "observe",
        "observe": [
            {
                "target": setting.target_kind.value,
                "addon_id": setting.addon_id,
                "key": setting.key,
                "type": setting.setting_type.value,
            }
            for setting in effective.settings
        ],
    })
    if not result.get("ok"):
        raise RuntimeError(
            f"BM-018E observe failed: {result.get('error_type')}: "
            f"{result.get('error')}"
        )
    observed = {}
    for key, entry in result.get("observed", {}).items():
        if not entry.get("ok"):
            raise RuntimeError(
                f"BM-018E observe could not read {key!r}: {entry.get('error')}"
            )
        observed[key] = entry["value"]
    return observed


def validate_af3_package() -> None:
    """Live BM-018E validation using the checked-in production AF3 package.

    The manifest and profile are loaded from the installed Build Manager copy,
    the winning skin package is resolved from ``skin.config_packages``, and
    the resulting typed settings are applied by the production BM-015 runner.
    AF3 and its complete installed dependency closure are copied read-only
    from the real add-on tree into the disposable profile. No real profile or
    device is touched.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.config import ConfigPackageLoader, ConfigSettingType
    from resources.lib.inspector import KodiStateInspector
    from resources.lib.manifest import (
        ConfigDeclarations,
        ManagedSettingScope,
        SettingTargetKind,
        load_manifest_file,
    )
    from resources.lib.planner import CONFIGURE, SET_SKIN, plan_changes
    from resources.lib.resolver import resolve_manifest

    print("=== Build Manager BM-018E live validation: production AF3 package ===")
    verify_isolation()
    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    try:
        print("\n[1/14] reset disposable profile and install production add-on")
        reset()
        install(source=PROJECT)
        installed_manifest = KODI_ADDONS_DIR / ADDON_ID / "resources" / "builds" / "examples" / _BM018E_MANIFEST.name
        manifest = load_manifest_file(str(installed_manifest))
        desired = resolve_manifest(manifest, _BM018E_PROFILE)
        if desired.skin is None or desired.skin.addon_id != _BM018D_SKIN_ID:
            raise RuntimeError(f"production profile resolved unexpected skin: {desired.skin!r}")
        if tuple(desired.skin.config_packages) != ("af3-common",):
            raise RuntimeError(
                f"production skin selected unexpected packages: {desired.skin.config_packages!r}"
            )
        if desired.config is None:
            raise RuntimeError("production profile resolved no configuration declarations")
        skin_scopes = tuple(
            scope for scope in desired.config.managed_settings
            if scope.target_kind is SettingTargetKind.SKIN
        )
        if len(skin_scopes) != 1 or skin_scopes[0].addon_id != _BM018D_SKIN_ID:
            raise RuntimeError(f"production manifest resolved unexpected AF3 ownership: {skin_scopes!r}")
        af3_declarations = ConfigDeclarations(
            packages=desired.skin.config_packages,
            managed_settings=skin_scopes,
            managed_files=(),
        )
        package_root = _bm015_installed_packages_root()
        effective = ConfigPackageLoader(str(package_root)).resolve(af3_declarations)
        if effective.packages != ("af3-common",) or len(effective.settings) != 16:
            raise RuntimeError(
                f"production AF3 package resolved unexpected effective configuration: "
                f"packages={effective.packages!r}, settings={len(effective.settings)}, "
                f"files={len(effective.files)}"
            )
        if effective.files:
            raise RuntimeError("production af3-common unexpectedly contains file targets")
        expected = {setting.key: setting.value for setting in effective.settings}
        expected_types = {setting.key: setting.setting_type for setting in effective.settings}
        if any(setting.setting_type not in (ConfigSettingType.BOOL, ConfigSettingType.STRING)
               for setting in effective.settings):
            raise RuntimeError("production AF3 package contains a non-bool/string target")
        print(
            f"  resolved installed manifest={installed_manifest} profile={_BM018E_PROFILE!r} "
            f"skin={desired.skin.addon_id!r} packages={effective.packages!r} "
            f"settings={len(effective.settings)} files=0 ✓"
        )
        af3_closure = _bm018d_copy_af3_and_dependencies()
        _bm018d_install_runner()
        configure_webserver()

        print("\n[2/14] launch disposable Kodi with Estuary")
        launch()
        wait_for_ready(timeout=90.0)
        initial = inspect()
        if initial["active_skin"] != "skin.estuary":
            raise RuntimeError(f"expected Estuary before BM-018E, got {initial['active_skin']!r}")
        print("  Estuary active before BM-018A activation ✓")

        runner_detail = jsonrpc("Addons.GetAddonDetails", {
            "addonid": _BM015_RUNNER_ADDON_ID,
            "properties": ["enabled"],
        })
        runner = runner_detail.get("addon") if isinstance(runner_detail, dict) else None
        if not isinstance(runner, dict):
            raise RuntimeError(
                f"BM-018E in-process runner was not discovered: {runner_detail!r}"
            )
        if runner.get("enabled") is not True:
            jsonrpc("Addons.SetAddonEnabled", {
                "addonid": _BM015_RUNNER_ADDON_ID,
                "enabled": True,
            })
        print("  BM-018E in-process runner discovered and enabled ✓")

        print("\n[3/14] verify AF3 dependency closure")
        _bm018d_verify_dependency_state(af3_closure)

        print("\n[4/14] prove production planner ordering")
        actual = KodiStateInspector(backend=_HttpKodiStateBackend()).inspect()
        plan = plan_changes(desired, actual)
        kinds = [action.kind for action in plan.actions]
        skin_index = kinds.index(SET_SKIN)
        config_index = kinds.index(CONFIGURE)
        if skin_index >= config_index:
            raise RuntimeError(f"production planner order was {kinds!r}")
        print(f"  planner actions include SET_SKIN -> CONFIGURE at {skin_index} -> {config_index} ✓")

        print("\n[5/14] bootstrap AF3 generated runtime state in disposable profile")
        _bm018d_warm_af3_runtime()

        print("\n[6/14] activate AF3 through BM-018A")
        activated = _bm018d_activate(_BM018D_SKIN_ID)
        if (
            activated.get("status") != "activated"
            or activated.get("persisted_skin") != _BM018D_SKIN_ID
            or activated.get("loaded_skin") != _BM018D_SKIN_ID
        ):
            raise RuntimeError(f"BM-018A did not keep AF3 active: {activated}")
        print("  confirmation accepted, persisted skin and xbmc.getSkinDir() are AF3 ✓")

        print("\n[7/14] preserve unmanaged AF3 setting")
        _bm018d_external_write(_BM018D_UNMANAGED_KEY, _BM018D_UNMANAGED_VALUE, "string")
        print(f"  {_BM018D_UNMANAGED_KEY} seeded outside managed scope ✓")

        print("\n[8/14] apply actual af3-common package")
        applied = _bm018e_apply(af3_declarations)
        if not applied.get("ok") or not applied.get("all_applied"):
            raise RuntimeError(f"production AF3 apply failed: {applied}")
        if applied.get("packages") != ["af3-common"]:
            raise RuntimeError(f"runner used unexpected packages: {applied.get('packages')!r}")
        if applied["validation_state"]["file_targets"]:
            raise RuntimeError(f"production package deployed files: {applied['validation_state']['file_targets']!r}")
        observed = _bm018e_observe(effective)
        if observed != expected:
            raise RuntimeError(f"production AF3 read-back mismatch: {observed!r}")
        if len(applied.get("operations", [])) != 16:
            raise RuntimeError(f"expected 16 production AF3 operations: {applied.get('operations')!r}")
        print("  16 typed settings applied; authoritative read-back matches; files=[] ✓")

        print("\n[9/14] reapply production package idempotently")
        identical = _bm018e_apply(af3_declarations)
        if not identical.get("ok") or identical.get("changed"):
            raise RuntimeError(f"production AF3 idempotency failed: {identical}")
        if len(identical.get("unchanged", [])) != 16:
            raise RuntimeError(f"expected 16 unchanged production AF3 settings: {identical}")
        print("  16/16 already correct; zero mutations ✓")

        print("\n[10/14] repair managed drift and verify unmanaged preservation")
        drift_key = next(key for key, kind in expected_types.items() if kind is ConfigSettingType.STRING)
        _bm018d_external_write(drift_key, "ExternallyDrifted", "string")
        repaired = _bm018e_apply(af3_declarations)
        if repaired.get("changed") != [f"skin:{_BM018D_SKIN_ID}/{drift_key}"]:
            raise RuntimeError(f"expected one production AF3 drift repair: {repaired}")
        unmanaged = _bm018d_run_job({
            "mode": "observe",
            "observe": [{
                "target": "skin", "addon_id": _BM018D_SKIN_ID,
                "key": _BM018D_UNMANAGED_KEY, "type": "string",
            }],
        })
        if not unmanaged.get("ok") or unmanaged["observed"][_BM018D_UNMANAGED_KEY].get("value") != _BM018D_UNMANAGED_VALUE:
            raise RuntimeError(f"unmanaged production AF3 setting changed: {unmanaged}")
        print(f"  repaired {drift_key}; unmanaged {_BM018D_UNMANAGED_KEY} preserved ✓")

        print("\n[11/14] reject incomplete ownership before mutation")
        before = _bm018e_observe(effective)
        incomplete = ConfigDeclarations(
            packages=af3_declarations.packages,
            managed_settings=(ManagedSettingScope(
                target_kind=SettingTargetKind.SKIN,
                addon_id=_BM018D_SKIN_ID,
                keys=tuple(key for key in skin_scopes[0].keys if key != drift_key),
            ),),
            managed_files=(),
        )
        rejected = _bm018e_apply(incomplete)
        after = _bm018e_observe(effective)
        if rejected.get("ok") or rejected.get("error_type") != "ConfigOwnershipError" or after != before:
            raise RuntimeError(f"production ownership gate did not fail closed: {rejected}")
        print("  ConfigOwnershipError with zero AF3 mutations ✓")

        print("\n[12/14] restart and verify AF3 persistence")
        restart()
        wait_for_ready(timeout=90.0)
        persisted = inspect()
        if persisted["active_skin"] != _BM018D_SKIN_ID:
            raise RuntimeError(f"AF3 did not remain active after restart: {persisted}")
        after_restart = _bm018e_observe(effective)
        if after_restart != expected:
            raise RuntimeError(f"production AF3 values did not persist: {after_restart!r}")
        post_restart = _bm018e_apply(af3_declarations)
        if not post_restart.get("ok") or post_restart.get("changed"):
            raise RuntimeError(f"post-restart production AF3 apply was not idempotent: {post_restart}")
        print("  AF3 active, all 16 values persisted, post-restart apply made 0 mutations ✓")

        print("\n[13/14] wrong-skin deployment fails before mutation")
        estuary = _bm018d_activate("skin.estuary")
        if estuary.get("status") != "activated":
            raise RuntimeError(f"could not switch disposable Kodi to Estuary: {estuary}")
        wrong_skin = _bm018e_apply(af3_declarations)
        if (
            not wrong_skin.get("ok")
            or wrong_skin.get("changed")
            or len(wrong_skin.get("failed", [])) != 16
        ):
            raise RuntimeError(f"wrong-skin production deployment did not fail safely: {wrong_skin}")
        _bm018d_activate(_BM018D_SKIN_ID)
        if _bm018e_observe(effective) != expected:
            raise RuntimeError("wrong-skin attempt changed production AF3 values")
        print("  Estuary rejected production AF3 deployment before mutation ✓")
    finally:
        print("\n[14/14] stop disposable Kodi")
        try:
            stop()
        except RuntimeError:
            pass

    print("\n[14/14] verify real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")
    print("\n=== BM-018E production AF3 validation PASSED ===\n")


def validate_skin_config() -> None:
    """Live BM-018D validation of typed AF3 skin-setting deployment.

    The test profile is disposable and the real Kodi profile is never read or
    written. AF3 add-on files are copied from the installed source tree only;
    real profile settings, generated state, and private/authentication data are
    not copied.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.config import (
        ConfigPackageLoader,
        ConfigurationValidationState,
    )
    from resources.lib.dependencies import DependencyClosure
    from resources.lib.inspector import KodiStateInspector
    from resources.lib.manifest import (
        AddonEntry,
        BuildInfo,
        ConfigDeclarations,
        ManagedSettingScope,
        SettingTargetKind,
        SkinEntry,
    )
    from resources.lib.resolver import ResolvedBuild
    from resources.lib.validator import (
        ValidationDomain,
        ValidationStatus,
        validate_build_state,
    )

    print("=== Build Manager BM-018D live validation: typed AF3 skin configuration ===")
    verify_isolation()
    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    print("\n[1/17] reset disposable profile")
    reset()
    print("\n[2/17] install Build Manager and AF3 dependency closure")
    install(source=PROJECT)
    af3_closure = _bm018d_copy_af3_and_dependencies()
    _bm018d_seed_first_run_guard()
    _write_bm018d_package()
    _bm018d_install_runner()
    configure_webserver()

    try:
        print("\n[3/17] launch Kodi with Estuary and wait for JSON-RPC")
        launch()
        wait_for_ready(timeout=90.0)
        initial = inspect()
        if initial["active_skin"] != "skin.estuary":
            raise RuntimeError(
                f"expected disposable Kodi to start in Estuary, got {initial['active_skin']!r}"
            )
        print("  Estuary active before BM-018A activation ✓")

        runner_detail = jsonrpc("Addons.GetAddonDetails", {
            "addonid": _BM015_RUNNER_ADDON_ID, "properties": ["enabled"],
        })
        if not isinstance(runner_detail, dict) or not isinstance(
            runner_detail.get("addon"), dict
        ):
            raise RuntimeError(
                f"harness runner was not discovered by disposable Kodi: {runner_detail!r}"
            )
        if runner_detail["addon"].get("enabled") is not True:
            jsonrpc("Addons.SetAddonEnabled", {
                "addonid": _BM015_RUNNER_ADDON_ID, "enabled": True,
            })
        print("  BM-018D in-process runner discovered and enabled ✓")

        print("\n[4/17] verify AF3 transitive dependency closure state")
        _bm018d_verify_dependency_state(af3_closure)

        print("\n[5/17] initialize disposable AF3 runtime state")
        _bm018d_warm_af3_runtime()

        print("\n[6/17] activate AF3 through BM-018A")
        detail = jsonrpc("Addons.GetAddonDetails", {
            "addonid": _BM018D_SKIN_ID, "properties": ["enabled"],
        })
        addon = detail.get("addon") if isinstance(detail, dict) else None
        if not isinstance(addon, dict):
            raise RuntimeError(f"AF3 was not discovered by disposable Kodi: {detail!r}")
        if addon.get("enabled") is not True:
            jsonrpc("Addons.SetAddonEnabled", {
                "addonid": _BM018D_SKIN_ID, "enabled": True,
            })
        activated = _bm018d_activate(_BM018D_SKIN_ID)
        if activated.get("status") != "activated":
            raise RuntimeError(f"BM-018A did not activate AF3: {activated}")
        if activated.get("persisted_skin") != _BM018D_SKIN_ID:
            raise RuntimeError(f"AF3 persisted setting mismatch: {activated}")
        if activated.get("loaded_skin") != _BM018D_SKIN_ID:
            raise RuntimeError(f"AF3 loaded skin mismatch: {activated}")
        print("  confirmation dialog observed, SendClick(11) completed, persisted setting and xbmc.getSkinDir() agree ✓")

        print("\n[7/17] seed one unmanaged AF3 skin setting and read typed baseline")
        _bm018d_external_write(_BM018D_UNMANAGED_KEY, _BM018D_UNMANAGED_VALUE, "string")
        baseline = _bm018d_observe()
        if not isinstance(baseline[_BM018D_BOOL_KEY], bool):
            raise RuntimeError(f"AF3 bool read-back was not bool: {baseline}")
        if not isinstance(baseline[_BM018D_STRING_KEY], str):
            raise RuntimeError(f"AF3 string read-back was not string: {baseline}")
        print(f"  typed baseline = {baseline} ✓")

        print("\n[8/17] apply synthetic AF3 bool+string package")
        applied = _bm018d_apply()
        if not applied.get("ok") or not applied.get("all_applied"):
            raise RuntimeError(
                f"BM-018D apply failed: {applied.get('error_type')}: "
                f"{applied.get('error')}"
            )
        operations = {op["target"]: op for op in applied["operations"]}
        expected_targets = {
            f"skin:{_BM018D_SKIN_ID}/{_BM018D_BOOL_KEY}",
            f"skin:{_BM018D_SKIN_ID}/{_BM018D_STRING_KEY}",
        }
        if set(operations) != expected_targets:
            raise RuntimeError(f"unexpected skin operation targets: {sorted(operations)}")
        observed = _bm018d_observe()
        if observed != {
            _BM018D_BOOL_KEY: _BM018D_BOOL_VALUE,
            _BM018D_STRING_KEY: _BM018D_STRING_VALUE,
        }:
            raise RuntimeError(f"AF3 read-back mismatch after apply: {observed}")
        print("  bool and string values applied and read back through dedicated skin backend ✓")
        print("\n[9/17] reapply identical package → zero mutations")
        identical = _bm018d_apply()
        if not identical.get("ok") or identical.get("changed"):
            raise RuntimeError(f"skin idempotency failed: {identical}")
        if len(identical.get("unchanged", [])) != 2:
            raise RuntimeError(f"expected 2 ALREADY_CORRECT skin settings: {identical}")
        print("  2/2 ALREADY_CORRECT, 0 mutations ✓")

        print("\n[10/17] externally drift one managed skin setting")
        _bm018d_external_write(_BM018D_STRING_KEY, "ExternallyDrifted", "string")
        drifted = _bm018d_observe()
        if drifted[_BM018D_STRING_KEY] != "ExternallyDrifted":
            raise RuntimeError(f"external AF3 drift was not visible: {drifted}")
        repaired = _bm018d_apply()
        if not repaired.get("ok"):
            raise RuntimeError(f"AF3 drift repair failed: {repaired}")
        changed = repaired.get("changed", [])
        expected_changed = [f"skin:{_BM018D_SKIN_ID}/{_BM018D_STRING_KEY}"]
        if changed != expected_changed:
            raise RuntimeError(f"expected exactly one repaired skin target: {changed}")
        print("  exactly one drifted string target repaired; bool remained unchanged ✓")

        print("\n[11/17] verify unmanaged skin setting is unchanged")
        # The unmanaged probe is intentionally outside the package and is read
        # through a direct in-Kodi job so the production typed adapter is still
        # the observation surface.
        unmanaged = _bm018d_run_job({
            "mode": "observe",
            "observe": [{
                "target": "skin", "addon_id": _BM018D_SKIN_ID,
                "key": _BM018D_UNMANAGED_KEY, "type": "string",
            }],
        })
        if not unmanaged.get("ok") or unmanaged["observed"][_BM018D_UNMANAGED_KEY].get("value") != _BM018D_UNMANAGED_VALUE:
            raise RuntimeError(f"unmanaged AF3 setting changed: {unmanaged}")
        print(f"  {_BM018D_UNMANAGED_KEY} remained unchanged ✓")

        print("\n[12/17] BM-014 CONFIGURATION validation with effective config + snapshot")
        package_root = _bm015_installed_packages_root()
        declarations = ConfigDeclarations(
            packages=(_BM018D_PACKAGE,),
            managed_settings=(ManagedSettingScope(
                target_kind=SettingTargetKind.SKIN,
                addon_id=_BM018D_SKIN_ID,
                keys=(_BM018D_BOOL_KEY, _BM018D_STRING_KEY),
            ),),
        )
        effective = ConfigPackageLoader(str(package_root)).resolve(declarations)
        snapshot = repaired["validation_state"]
        state = ConfigurationValidationState(
            effective_identity=snapshot["effective_identity"],
            setting_targets=tuple(tuple(t) for t in snapshot["setting_targets"]),
            file_targets=tuple(snapshot["file_targets"]),
            verified_settings=tuple(tuple(t) for t in snapshot["verified_settings"]),
            verified_files=tuple(snapshot["verified_files"]),
        )
        actual = KodiStateInspector(backend=_HttpKodiStateBackend()).inspect()
        desired = ResolvedBuild(
            build=BuildInfo(id="bm018d-test", version="1.0.0", name="BM-018D Test"),
            engine_min_version="1.0.0",
            platform_profile_id=actual.platform,
            device_profile_id="disposable-kodi-test",
            repositories=(),
            addons=(),
            skin=SkinEntry(addon_id=_BM018D_SKIN_ID),
            config=declarations,
            optional_groups_applied=(),
            restart_policy=None,
            private_overlay=None,
        )
        report = validate_build_state(
            desired, actual, DependencyClosure(root_addon_ids=(), nodes=()),
            configuration_state=state, effective_configuration=effective,
        )
        config_checks = [c for c in report.checks if c.domain == ValidationDomain.CONFIGURATION]
        if len(config_checks) != 2 or not all(c.status == ValidationStatus.PASS for c in config_checks):
            raise RuntimeError(f"BM-014 configuration checks did not pass: {config_checks}")
        print("  effective configuration and validation snapshot: 2/2 CONFIGURATION PASS ✓")

        print("\n[13/17] ownership preflight failure → zero mutation")
        before = _bm018d_observe()
        bad = _bm018d_apply(managed_keys=[_BM018D_BOOL_KEY])
        if bad.get("ok") or bad.get("error_type") != "ConfigOwnershipError":
            raise RuntimeError(f"ownership preflight did not fail as expected: {bad}")
        after = _bm018d_observe()
        if after != before:
            raise RuntimeError(f"ownership preflight mutated AF3 settings: {before} -> {after}")
        print("  ConfigOwnershipError and zero skin mutations confirmed ✓")

        print("\n[14/17] restart Kodi → verify AF3 settings and active skin persist")
        restart()
        wait_for_ready(timeout=90.0)
        persisted = inspect()
        if persisted["active_skin"] != _BM018D_SKIN_ID:
            raise RuntimeError(f"AF3 did not remain active after restart: {persisted}")
        after_restart = _bm018d_observe()
        if after_restart != {
            _BM018D_BOOL_KEY: _BM018D_BOOL_VALUE,
            _BM018D_STRING_KEY: _BM018D_STRING_VALUE,
        }:
            raise RuntimeError(f"AF3 settings did not persist: {after_restart}")
        post_restart = _bm018d_apply()
        if not post_restart.get("ok") or post_restart.get("changed"):
            raise RuntimeError(f"post-restart apply was not idempotent: {post_restart}")
        print("  AF3 active, typed values persisted, and post-restart apply made 0 mutations ✓")

        print("\n[15/17] wrong active skin precondition → safe failure")
        estuary = _bm018d_activate("skin.estuary")
        if estuary.get("status") != "activated":
            raise RuntimeError(f"could not switch disposable profile to Estuary: {estuary}")
        wrong_skin = _bm018d_apply()
        if (
            not wrong_skin.get("ok")
            or wrong_skin.get("all_applied")
            or wrong_skin.get("changed")
            or len(wrong_skin.get("failed", [])) != 2
        ):
            raise RuntimeError(f"wrong-skin precondition did not fail safely: {wrong_skin}")
        print("  active Estuary rejected AF3 target before mutation ✓")
        _bm018d_activate(_BM018D_SKIN_ID)
        final_values = _bm018d_observe()
        if final_values != {
            _BM018D_BOOL_KEY: _BM018D_BOOL_VALUE,
            _BM018D_STRING_KEY: _BM018D_STRING_VALUE,
        }:
            raise RuntimeError(f"wrong-skin attempt changed AF3 values: {final_values}")
        print("  AF3 values unchanged after wrong-skin attempt ✓")

    finally:
        print("\n[16/17] stop Kodi")
        try:
            stop()
        except RuntimeError:
            pass

    print("\n[17/17] verify real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")
    print("\n=== BM-018D validation PASSED (17/17) ===\n")


# ---------------------------------------------------------------------------
# BM-020A live validation — production reconciliation executor
# ---------------------------------------------------------------------------

def _bm020a_run_job(
    *, device_profile_id: str = _BM020A_PROFILE
) -> Dict[str, Any]:
    """Invoke BuildManager.reconcile() inside disposable Kodi."""
    return _bm015_run_job({
        "mode": "build_manager",
        "device_profile_id": device_profile_id,
        "manifest_filename": _BM020A_FIXTURE,
    }, timeout=120.0)


def _bm020b_run_job(mode: str, **kwargs) -> Dict[str, Any]:
    """Invoke a narrowly scoped BM-020B harness seam inside disposable Kodi."""
    return _bm015_run_job({"mode": mode, **kwargs}, timeout=30.0)


def _bm020c1_wait_startup_classification(
    expected: str, *, timeout: float = 30.0
) -> Dict[str, Any]:
    """Wait for service classification, not merely JSON-RPC readiness."""
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = _bm020b_run_job("transaction_startup_property")
        if last.get("classification") == expected:
            return last
        time.sleep(0.25)
    raise RuntimeError(
        f"startup classification did not become {expected!r}: {last!r}"
    )


def _bm020c_wait_resume_completion(
    expected_fingerprint: str, *, timeout: float = 60.0
) -> Dict[str, Any]:
    """Wait on service-published completion and durable transaction removal."""
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = _bm020b_run_job("transaction_resume_properties")
        inspected = _bm020b_run_job("transaction_inspect")
        if (
            last.get("resume_outcome") == "completed"
            and last.get("resume_fingerprint") == expected_fingerprint
            and last.get("resume_requirement") == "none"
            and inspected.get("transaction") is None
        ):
            last["transaction"] = None
            return last
        time.sleep(0.25)
    raise RuntimeError(
        f"automatic resume did not complete: properties={last!r}, "
        f"transaction={inspected!r}"
    )


def _bm020b_log_text() -> str:
    if not KODI_LOG_FILE.is_file():
        return ""
    return KODI_LOG_FILE.read_text(encoding="utf-8", errors="replace")


def _bm020b_enable_production_addon() -> None:
    """Enable the copied production add-on before its next Kodi startup."""
    detail = jsonrpc("Addons.GetAddonDetails", {
        "addonid": ADDON_ID,
        "properties": ["enabled"],
    })
    addon = detail.get("addon") if isinstance(detail, dict) else None
    if not isinstance(addon, dict):
        raise RuntimeError(f"Build Manager add-on was not discovered: {detail!r}")
    if addon.get("enabled") is not True:
        jsonrpc("Addons.SetAddonEnabled", {
            "addonid": ADDON_ID,
            "enabled": True,
        })
    print("  disposable Build Manager service add-on enabled ✓")


def validate_build_manager_transaction() -> None:
    """Prove BM-020B transaction classification across a real Kodi restart."""
    print("=== Build Manager BM-020B live validation: transaction startup ===")
    verify_isolation()
    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    try:
        print("\n[1/9] reset, install, configure, and install the harness runner")
        reset()
        install(source=PROJECT)
        configure_webserver()
        _install_bm015_config_runner()

        print("\n[2/9] enable the service add-on and prove its startup fast path")
        launch()
        wait_for_ready(timeout=90.0)
        _bm020b_enable_production_addon()
        # A copied add-on is initially disabled in a fresh disposable profile.
        # Restarting after the explicit enable mirrors normal installation of an
        # enabled production package and proves Kodi's automatic service load.
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        initial_status = _bm020b_run_job("transaction_startup_property")
        if initial_status.get("classification") != "no_transaction":
            raise RuntimeError("BM-020B service did not report the no-transaction fast path")
        print("  xbmc.service startup fast path reported no transaction ✓")
        first_session = _bm020b_run_job("transaction_session")
        if not first_session.get("ok") or not first_session.get("session_id"):
            raise RuntimeError(f"could not obtain first Kodi session: {first_session}")
        session_id = first_session["session_id"]
        print("  first process session identity obtained ✓")

        print("\n[3/9] create a real awaiting-restart transaction through production storage")
        prepared = _bm020b_run_job("transaction_prepare", session_id=session_id)
        if not prepared.get("ok") or not prepared.get("succeeded") or not prepared.get("created"):
            raise RuntimeError(f"transaction preparation failed: {prepared}")
        print("  AWAITING_RESTART transaction created without invoking restart ✓")

        print("\n[4/9] classify the pending transaction in the same Kodi process")
        same = _bm020b_run_job("transaction_classify", session_id=session_id)
        if (
            not same.get("ok")
            or same.get("classification") != "same_session_awaiting_restart"
            or same.get("eligible_for_resume")
        ):
            raise RuntimeError(f"same-session classification failed: {same}")
        print("  SAME_SESSION classification preserved the transaction and did not resume ✓")

        print("\n[5/9] externally stop and relaunch disposable Kodi")
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        second_session = _bm020b_run_job("transaction_session")
        if not second_session.get("ok") or second_session.get("session_id") == session_id:
            raise RuntimeError(f"Kodi process did not receive a new session ID: {second_session}")
        print("  external process boundary produced a different session identity ✓")

        print("\n[6/9] prove automatic service classification after restart")
        restarted_status = _bm020b_run_job("transaction_startup_property")
        if restarted_status.get("classification") != "ready_for_resume":
            raise RuntimeError("service did not automatically report READY_FOR_RESUME after restart")
        ready = _bm020b_run_job(
            "transaction_classify", session_id=second_session["session_id"]
        )
        if (
            not ready.get("ok")
            or ready.get("classification") != "ready_for_resume"
            or not ready.get("eligible_for_resume")
        ):
            raise RuntimeError(f"new-session classification failed: {ready}")
        print("  service reported READY_FOR_RESUME; transaction remained durable ✓")

        print("\n[7/9] explicitly clear the transaction through the recovery API")
        cleared = _bm020b_run_job("transaction_clear")
        if not cleared.get("ok") or not cleared.get("cleared"):
            raise RuntimeError(f"explicit transaction clear failed: {cleared}")
        inspected = _bm020b_run_job("transaction_inspect")
        if not inspected.get("ok") or inspected.get("transaction") is not None:
            raise RuntimeError(f"cleared transaction is still present: {inspected}")
        print("  explicit clear removed the pending transaction ✓")

        print("\n[8/9] verify normal startup returns to the fast path")
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        final_status = _bm020b_run_job("transaction_startup_property")
        if final_status.get("classification") != "no_transaction":
            raise RuntimeError("service did not return to the no-transaction fast path")
        print("  no-transaction startup remained silent and did not create a record ✓")
    finally:
        print("\n[9/9] stop disposable Kodi and verify the real profile")
        try:
            stop()
        except RuntimeError:
            pass
        if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
            current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
            if current_mtime_ns != real_mtime_ns:
                raise RuntimeError(
                    f"Validation FAILED: real profile mtime changed! "
                    f"Was {real_mtime_ns}, now {current_mtime_ns}"
                )
        print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("  production BuildManager did not restart Kodi or resume reconciliation ✓")
    print("\n=== BM-020B transaction validation PASSED (9/9) ===\n")


def validate_build_manager_manual_restart() -> None:
    """Prove BM-020C1's manual restart handoff across disposable processes."""
    print("=== Build Manager BM-020C1 live validation: manual restart handoff ===")
    verify_isolation()
    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    try:
        print("\n[1/8] reset disposable profile and prepare the real BM-020A fixture")
        reset()
        install(source=PROJECT)
        af3_closure = _bm018d_copy_af3_and_dependencies()
        _bm018d_seed_first_run_guard()
        _install_bm015_config_runner()
        configure_webserver()

        print("\n[2/8] launch Kodi and enable the production service add-on")
        launch()
        wait_for_ready(timeout=90.0)
        _bm020b_enable_production_addon()
        _bm018d_verify_dependency_state(af3_closure)
        _bm020a_ensure_runner_enabled()
        _bm018d_warm_af3_runtime()
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        _bm020c1_wait_startup_classification("no_transaction")
        first_session = _bm020b_run_job("transaction_session")
        if not first_session.get("ok") or not first_session.get("session_id"):
            raise RuntimeError(f"could not obtain first Kodi session: {first_session}")
        first_session_id = first_session["session_id"]
        first_pid = status().get("pid")
        print(f"  first session={first_session_id}; pid={first_pid} ✓")

        print("\n[3/8] run real reconciliation and pass the typed manual trigger")
        triggered = _bm020b_run_job(
            "restart_manual_trigger",
            manifest_filename=_BM020A_FIXTURE,
            device_profile_id=_BM020A_PROFILE,
            platform="macos",
        )
        if not triggered.get("ok"):
            raise RuntimeError(f"manual trigger runner failed: {triggered}")
        real_result = triggered.get("real_result") or {}
        coordinator = triggered.get("coordinator") or {}
        transaction = coordinator.get("transaction") or {}
        if (
            not real_result.get("success")
            or not real_result.get("desired_fingerprint")
            or coordinator.get("outcome") != "manual_restart_required"
            or coordinator.get("capability") != "manual_app_restart_required"
            or transaction.get("phase") != "awaiting_restart"
            or transaction.get("restart_attempt_count") != 0
        ):
            raise RuntimeError(f"manual handoff contract failed: {triggered}")
        if status().get("pid") != first_pid or not status().get("running"):
            raise RuntimeError("manual coordinator unexpectedly stopped Kodi")
        print("  real fingerprint persisted with AWAITING_RESTART/count=0 ✓")
        print("  Kodi remained in the same process; no production restart invoked ✓")

        print("\n[4/8] prove same-session behavior")
        same = _bm020b_run_job(
            "transaction_classify", session_id=first_session_id
        )
        if (
            not same.get("ok")
            or same.get("classification") != "same_session_awaiting_restart"
            or same.get("eligible_for_resume")
            or (same.get("transaction") or {}).get("restart_attempt_count") != 0
        ):
            raise RuntimeError(f"same-session manual handoff failed: {same}")
        print("  SAME_SESSION classification preserved count=0 and did not resume ✓")

        print("\n[5/8] externally restart disposable Kodi through the harness only")
        restart()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        second_session = _bm020b_run_job("transaction_session")
        if (
            not second_session.get("ok")
            or second_session.get("session_id") == first_session_id
        ):
            raise RuntimeError(f"manual restart did not create a new session: {second_session}")
        second_session_id = second_session["session_id"]
        print(f"  new session={second_session_id} differs from the first ✓")

        print("\n[6/8] prove BM-020B handoff readiness without resume yet")
        _bm020c1_wait_startup_classification("ready_for_resume")
        ready = _bm020b_run_job(
            "transaction_classify", session_id=second_session_id
        )
        if (
            not ready.get("ok")
            or ready.get("classification") != "ready_for_resume"
            or not ready.get("eligible_for_resume")
            or (ready.get("transaction") or {}).get("restart_attempt_count") != 0
        ):
            raise RuntimeError(f"manual new-session handoff failed: {ready}")
        print("  READY_FOR_RESUME accepted with manual count=0; no reconcile yet ✓")

        print("\n[7/8] explicitly clear the BM-020C1 handoff")
        cleared = _bm020b_run_job("transaction_clear")
        if not cleared.get("ok") or not cleared.get("cleared"):
            raise RuntimeError(f"manual handoff clear failed: {cleared}")
        inspected = _bm020b_run_job("transaction_inspect")
        if not inspected.get("ok") or inspected.get("transaction") is not None:
            raise RuntimeError(f"manual handoff remained after clear: {inspected}")
        print("  explicit clear removed the pending transaction ✓")
    finally:
        print("\n[8/8] stop disposable Kodi and verify the real profile")
        try:
            stop()
        except RuntimeError:
            pass
        if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
            current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
            if current_mtime_ns != real_mtime_ns:
                raise RuntimeError(
                    f"Validation FAILED: real profile mtime changed! "
                    f"Was {real_mtime_ns}, now {current_mtime_ns}"
                )
        print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-020C1 manual restart validation PASSED (8/8) ===\n")


def validate_build_manager_resume() -> None:
    """Prove automatic BM-020C resume after a harness-only restart."""
    print("=== Build Manager BM-020C live validation: post-restart resume ===")
    verify_isolation()
    real_mtime_ns: Optional[int] = None
    if NORMAL_APPDATA_DIR.exists():
        real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns

    try:
        print("\n[1/8] reset disposable profile and prepare the real BM-020A fixture")
        reset()
        install(source=PROJECT)
        af3_closure = _bm018d_copy_af3_and_dependencies()
        _bm018d_seed_first_run_guard()
        _install_bm015_config_runner()
        configure_webserver()

        print("\n[2/8] launch Kodi, warm AF3, and establish the no-transaction state")
        launch()
        wait_for_ready(timeout=90.0)
        _bm020b_enable_production_addon()
        _bm018d_verify_dependency_state(af3_closure)
        _bm020a_ensure_runner_enabled()
        _bm018d_warm_af3_runtime()
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        _bm020c1_wait_startup_classification("no_transaction")
        first_session = _bm020b_run_job("transaction_session")
        if not first_session.get("ok") or not first_session.get("session_id"):
            raise RuntimeError(f"could not obtain first Kodi session: {first_session}")
        first_session_id = first_session["session_id"]
        print(f"  first session={first_session_id}; AF3 closure 18/18 healthy ✓")

        print("\n[3/8] run real reconciliation and create the test-only restart handoff")
        triggered = _bm020b_run_job(
            "restart_manual_trigger",
            manifest_filename=_BM020A_FIXTURE,
            device_profile_id=_BM020A_PROFILE,
            platform="macos",
        )
        real_result = triggered.get("real_result") or {}
        coordinator = triggered.get("coordinator") or {}
        transaction = coordinator.get("transaction") or {}
        if (
            not triggered.get("ok")
            or not real_result.get("success")
            or not real_result.get("desired_fingerprint")
            or coordinator.get("outcome") != "manual_restart_required"
            or transaction.get("phase") != "awaiting_restart"
            or transaction.get("restart_attempt_count") != 0
        ):
            raise RuntimeError(f"automatic-resume handoff setup failed: {triggered!r}")
        original_fingerprint = real_result["desired_fingerprint"]
        print("  real fingerprint persisted with AWAITING_RESTART/count=0 ✓")
        print("  production coordinator left Kodi running ✓")

        print("\n[4/8] prove same-session service behavior remains non-resuming")
        same = _bm020b_run_job("transaction_classify", session_id=first_session_id)
        if (
            same.get("classification") != "same_session_awaiting_restart"
            or same.get("eligible_for_resume")
        ):
            raise RuntimeError(f"same-session service behavior failed: {same!r}")
        print("  SAME_SESSION_AWAITING_RESTART preserved the handoff ✓")

        print("\n[5/8] externally restart disposable Kodi through the harness only")
        restart()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        second_session = _bm020b_run_job("transaction_session")
        if (
            not second_session.get("ok")
            or second_session.get("session_id") == first_session_id
        ):
            raise RuntimeError(f"restart did not create a new session: {second_session!r}")
        print("  new Kodi session differs from originating session ✓")

        print("\n[6/8] wait for service.py to preview, claim, reconcile, and clear")
        resumed = _bm020c_wait_resume_completion(original_fingerprint)
        if resumed.get("classification") != "no_transaction":
            raise RuntimeError(f"resume service did not return no_transaction: {resumed!r}")
        print("  service automatically resumed normal BuildManager reconciliation ✓")
        print("  final fingerprint matched; RestartRequirement.NONE; transaction cleared ✓")

        print("\n[7/8] verify AF3 state and no second handoff")
        observed = _bm020a_observe()
        expected_values = {
            key: value for key, (_setting_type, value) in _BM020A_MANAGED_SETTINGS.items()
        }
        if {key: observed.get(key) for key in expected_values} != expected_values:
            raise RuntimeError(f"resumed AF3 settings mismatch: {observed!r}")
        if inspect().get("active_skin") != _BM018D_SKIN_ID:
            raise RuntimeError(f"resumed active skin mismatch: {inspect()!r}")
        if _bm020b_run_job("transaction_inspect").get("transaction") is not None:
            raise RuntimeError("resumed reconciliation left a second transaction")
        print("  all 16 AF3 managed settings verified; unmanaged preservation remains covered by BM-020A ✓")
        print("  no second restart or handoff exists ✓")

        print("\n[8/8] restart again and verify the normal no-transaction fast path")
        restart()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        _bm020c1_wait_startup_classification("no_transaction")
        final = _bm020b_run_job("transaction_inspect")
        if final.get("transaction") is not None:
            raise RuntimeError(f"later startup found stale transaction: {final!r}")
        print("  later startup remained NO_TRANSACTION with no automatic retry ✓")
    finally:
        try:
            stop()
        except RuntimeError:
            pass
        if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
            current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
            if current_mtime_ns != real_mtime_ns:
                raise RuntimeError(
                    f"Validation FAILED: real profile mtime changed! "
                    f"Was {real_mtime_ns}, now {current_mtime_ns}"
                )
        print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-020C post-restart resume validation PASSED (8/8) ===\n")


def _bm020a_observe() -> Dict[str, Any]:
    result = _bm018d_run_job({
        "mode": "observe",
        "observe": [
            {
                "target": "skin",
                "addon_id": _BM018D_SKIN_ID,
                "key": key,
                "type": setting_type,
            }
            for key, (setting_type, _value) in _BM020A_MANAGED_SETTINGS.items()
        ] + [{
            "target": "skin",
            "addon_id": _BM018D_SKIN_ID,
            "key": _BM020A_UNMANAGED_KEY,
            "type": "string",
        }],
    })
    if not result.get("ok"):
        raise RuntimeError(
            f"BM-020A typed observation failed: {result.get('error_type')}: "
            f"{result.get('error')}"
        )
    observed = {}
    for key, entry in result.get("observed", {}).items():
        if not entry.get("ok"):
            raise RuntimeError(
                f"BM-020A typed observation could not read {key!r}: "
                f"{entry.get('error')}"
            )
        observed[key] = entry["value"]
    return observed


def _bm020a_ensure_runner_enabled() -> None:
    detail = jsonrpc("Addons.GetAddonDetails", {
        "addonid": _BM015_RUNNER_ADDON_ID,
        "properties": ["enabled"],
    })
    addon = detail.get("addon") if isinstance(detail, dict) else None
    if not isinstance(addon, dict):
        raise RuntimeError(f"BM-020A runner was not discovered: {detail!r}")
    if addon.get("enabled") is not True:
        jsonrpc("Addons.SetAddonEnabled", {
            "addonid": _BM015_RUNNER_ADDON_ID,
            "enabled": True,
        })
    print("  BM-020A in-process runner discovered and enabled ✓")


def validate_build_manager() -> None:
    """Run BM-020A against the explicit AF3 disposable executor fixture."""
    print("=== Build Manager BM-020A live validation: production executor ===")
    verify_isolation()

    try:
        print("\n[1/6] reset disposable profile and prepare AF3 fixture")
        reset()
        install(source=PROJECT)
        af3_closure = _bm018d_copy_af3_and_dependencies()
        _bm018d_seed_first_run_guard()
        _bm018d_install_runner()
        configure_webserver()
        print(
            f"  fixture={_BM020A_FIXTURE!r} profile={_BM020A_PROFILE!r}; "
            f"copied AF3 closure={len(af3_closure)}; real af3-common remains in installed Build Manager ✓"
        )

        print("\n[2/6] launch disposable Kodi and inspect initial state")
        launch()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        before = inspect()
        if before.get("active_skin") != "skin.estuary":
            raise RuntimeError(
                f"expected disposable Kodi to start on Estuary, got {before!r}"
            )
        print("  disposable Kodi started on Estuary ✓")
        _bm018d_verify_dependency_state(af3_closure)
        _bm018d_warm_af3_runtime()
        warmed = inspect()
        if warmed.get("active_skin") != "skin.estuary":
            raise RuntimeError(
                f"AF3 fixture preparation did not return to Estuary: {warmed!r}"
            )
        print("  AF3 disposable runtime prepared and returned to Estuary ✓")

        print("\n[3/6] invoke production BuildManager.reconcile() with fixture")
        first = _bm020a_run_job(device_profile_id=_BM020A_PROFILE)
        print(json.dumps(first, indent=2, sort_keys=True, default=str))
        if not first.get("ok"):
            raise RuntimeError(
                f"BM-020A runner failed: {first.get('error_type')}: "
                f"{first.get('error')}"
            )
        if not first.get("success"):
            failure = first.get("failure") or {}
            raise RuntimeError(
                "BM-020A disposable gate blocked before a successful pass: "
                f"phase={failure.get('phase')!r} code={failure.get('code')!r} "
                f"message={failure.get('message')!r}"
            )

        request = first.get("request") or {}
        if request.get("device_profile_id") != _BM020A_PROFILE:
            raise RuntimeError(f"unexpected executor request: {request!r}")
        if not request.get("manifest_path", "").endswith(
            f"/resources/builds/examples/{_BM020A_FIXTURE}"
        ):
            raise RuntimeError(f"unexpected fixture manifest path: {request!r}")
        if not first.get("desired_fingerprint"):
            raise RuntimeError("executor returned no desired-state fingerprint")
        if first.get("restart_report", {}).get("requirement") != "none":
            raise RuntimeError(
                f"unexpected first-pass restart requirement: {first.get('restart_report')!r}"
            )
        first_kinds = [action["kind"] for action in first.get("planned_actions", [])]
        if first_kinds != ["SET_SKIN", "CONFIGURE"]:
            raise RuntimeError(f"unexpected fixture planner actions: {first_kinds!r}")
        first_owners = [entry["owner"] for entry in first.get("owner_dispatch", [])]
        if first_owners != ["SkinActivator", "ConfigurationManager"]:
            raise RuntimeError(f"unexpected fixture owner dispatch: {first_owners!r}")
        if not all(result.get("succeeded") for result in first.get("action_results", [])):
            raise RuntimeError(f"fixture action failed: {first.get('action_results')!r}")
        configure_result = next(
            result for result in first["action_results"]
            if result["action"]["kind"] == "CONFIGURE"
        )
        if not configure_result.get("changed"):
            raise RuntimeError(
                f"fixture did not reconcile af3-common configuration: {configure_result!r}"
            )
        if first.get("validation_passed") is not True:
            raise RuntimeError(f"fixture post-validation did not pass: {first!r}")
        summary = first.get("configuration_summary") or {}
        if summary.get("file_targets") != []:
            raise RuntimeError(
                f"production af3-common unexpectedly planned file deployment: {summary!r}"
            )
        expected_targets = [
            f"skin:{_BM018D_SKIN_ID}/{key}"
            for key in sorted(_BM020A_MANAGED_SETTINGS)
        ]
        if sorted(summary.get("setting_targets", [])) != expected_targets:
            raise RuntimeError(
                f"production af3-common setting scope mismatch: {summary!r}"
            )
        first_values = _bm020a_observe()
        expected_values = {
            key: value for key, (_setting_type, value) in _BM020A_MANAGED_SETTINGS.items()
        }
        if {
            key: first_values.get(key) for key in expected_values
        } != expected_values:
            raise RuntimeError(
                f"production af3-common typed read-back mismatch: {first_values!r}"
            )
        _bm018d_external_write(
            _BM020A_UNMANAGED_KEY, _BM020A_UNMANAGED_VALUE, "string"
        )
        unmanaged_baseline = _bm020a_observe()
        if unmanaged_baseline.get(_BM020A_UNMANAGED_KEY) != _BM020A_UNMANAGED_VALUE:
            raise RuntimeError(f"could not seed unmanaged preservation probe: {unmanaged_baseline!r}")
        print("  all 16 production settings read back exactly; files=[] ✓")
        print("  production executor first pass succeeded with RestartRequirement.NONE ✓")

        print("\n[4/6] rerun the exact fixture request and verify idempotency")
        second = _bm020a_run_job(device_profile_id=_BM020A_PROFILE)
        print(json.dumps(second, indent=2, sort_keys=True, default=str))
        if not second.get("ok") or not second.get("success"):
            raise RuntimeError(f"BM-020A second pass failed: {second!r}")
        if second.get("desired_fingerprint") != first.get("desired_fingerprint"):
            raise RuntimeError("BM-020A fingerprint changed between identical passes")
        if second.get("restart_report", {}).get("requirement") != "none":
            raise RuntimeError(
                f"unexpected second-pass restart requirement: {second.get('restart_report')!r}"
            )
        second_kinds = [action["kind"] for action in second.get("planned_actions", [])]
        if second_kinds != ["CONFIGURE"]:
            raise RuntimeError(f"second pass had unexpected actions: {second_kinds!r}")
        if any(result.get("changed") for result in second.get("action_results", [])):
            raise RuntimeError(
                f"second pass performed an unnecessary mutation: {second.get('action_results')!r}"
            )
        if not all(result.get("succeeded") for result in second.get("action_results", [])):
            raise RuntimeError(f"second pass action failed: {second.get('action_results')!r}")
        second_values = _bm020a_observe()
        if second_values.get(_BM020A_UNMANAGED_KEY) != _BM020A_UNMANAGED_VALUE:
            raise RuntimeError(f"unmanaged setting changed during idempotent pass: {second_values!r}")
        print("  exact request retained its fingerprint and produced no mutation ✓")

        print("\n[5/6] drift one managed setting and repair it")
        _bm018d_external_write("Navigation.OnBack", "Home", "string")
        drifted = _bm020a_observe()
        if drifted.get("Navigation.OnBack") != "Home":
            raise RuntimeError(f"managed drift was not observable: {drifted!r}")
        repaired = _bm020a_run_job(device_profile_id=_BM020A_PROFILE)
        if not repaired.get("ok") or not repaired.get("success"):
            raise RuntimeError(f"BM-020A drift repair failed: {repaired!r}")
        if repaired.get("desired_fingerprint") != first.get("desired_fingerprint"):
            raise RuntimeError("drift repair changed the desired-state fingerprint")
        repair_summary = repaired.get("configuration_summary") or {}
        if repair_summary.get("changed_targets") != [
            f"skin:{_BM018D_SKIN_ID}/Navigation.OnBack"
        ]:
            raise RuntimeError(f"unexpected drift repair targets: {repair_summary!r}")
        repaired_values = _bm020a_observe()
        if {
            key: repaired_values.get(key) for key in expected_values
        } != expected_values:
            raise RuntimeError(f"production drift repair read-back mismatch: {repaired_values!r}")
        if repaired_values.get(_BM020A_UNMANAGED_KEY) != _BM020A_UNMANAGED_VALUE:
            raise RuntimeError("unmanaged setting changed during drift repair")
        print("  managed drift repaired; all 16 values and unmanaged preservation verified ✓")

        print("\n[6/6] invalid selector smoke check")
        unchanged_before = inspect()
        invalid = _bm020a_run_job(device_profile_id="does-not-exist")
        unchanged_after = inspect()
        if (
            not invalid.get("ok")
            or invalid.get("success")
            or (invalid.get("failure") or {}).get("phase") != "resolve"
            or unchanged_before != unchanged_after
        ):
            raise RuntimeError(
                f"invalid selector did not fail closed without mutation: {invalid!r}"
            )
        print("  invalid selector failed in resolve phase; disposable state unchanged ✓")
        print("\n[6/6] combined evidence boundary")
        print(
            "  live executor composition proven here; repository/add-on installation "
            "and dedicated AF3/configuration behavior remain covered by existing gates ✓"
        )
    finally:
        print("\nstop disposable Kodi")
        try:
            stop()
        except RuntimeError:
            pass

    print("real Kodi profile was not accessed by this gate ✓")
    print("\n=== BM-020A validation PASSED ===\n")


def validate_frozen_capture() -> None:
    """Exercise BM-021B capture against only the disposable AF3 fixture."""
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.artifacts import ArtifactStore
    from resources.lib.frozen import KodiInventoryBackend, capture_frozen_build

    print("=== Build Manager BM-021B live validation: frozen capture ===")
    verify_isolation()
    try:
        print("\n[1/4] reset and prepare the disposable AF3 closure")
        reset()
        install(source=PROJECT)
        af3_closure = _bm018d_copy_af3_and_dependencies()
        _bm018d_seed_first_run_guard()
        _bm018d_install_runner()
        configure_webserver()
        launch()
        wait_for_ready(timeout=90.0)
        _bm020a_ensure_runner_enabled()
        _bm018d_verify_dependency_state(af3_closure)
        _bm018d_warm_af3_runtime()
        if inspect().get("active_skin") != "skin.estuary":
            raise RuntimeError("capture proof must finish on disposable Estuary")
        print(f"  disposable AF3 closure prepared ({len(af3_closure)} nodes) ✓")

        print("\n[2/4] capture representative installed software")
        backend = KodiInventoryBackend(
            jsonrpc,
            addons_dir=KODI_ADDONS_DIR,
            package_cache_dir=KODI_APPDATA_DIR / "addons" / "packages",
        )
        store = ArtifactStore(ROOT / "bm021b-artifacts")
        result = capture_frozen_build(
            backend=backend,
            store=store,
            root_addon_ids=(
                _BM018D_SKIN_ID,
                "plugin.video.themoviedb.helper",
                "metadata.themoviedb.org.python",
                "script.module.pil",
            ),
            build_id="bm021b-disposable-proof",
            name="BM-021B disposable proof",
            created_at="2026-09-21T00:00:00Z",
            platform="macos",
        )
        print(json.dumps(result.manifest.to_dict(), indent=2, sort_keys=True))
        for node in result.manifest.addons:
            print(
                f"  {node.addon_id}: version={node.version!r} status={node.status.value!r} "
                f"artifact={'yes' if node.artifact else 'no'} provenance={node.provenance.value!r}"
            )
        if not any(node.addon_id == _BM018D_SKIN_ID for node in result.manifest.addons):
            raise RuntimeError("AF3 was absent from the captured inventory")
        print("  installed identity, dependency classification, and honest artifact availability recorded ✓")

        print("\n[3/4] verify exact artifact bytes and duplicate reuse")
        artifact_nodes = [node for node in result.manifest.addons if node.artifact is not None]
        if artifact_nodes:
            node = artifact_nodes[0]
            data = store.read_bytes(node.artifact.sha256)
            reused = store.import_zip(
                data,
                expected_addon_id=node.addon_id,
                expected_version=node.version,
                source="duplicate-proof",
            )
            if reused.sha256 != node.artifact.sha256:
                raise RuntimeError("duplicate artifact import changed the digest")
            print(f"  {len(artifact_nodes)} exact artifact(s) hashed, read back, and deduplicated ✓")
        else:
            print("  no disposable cache artifact was available; capture correctly remains incomplete")

        print("\n[4/4] enforce incomplete-capture boundary")
        if not result.complete:
            print(f"  capture status={result.manifest.capture_status.value}; no COMPLETE claim made ✓")
        else:
            print("  all selected required nodes had exact artifacts; COMPLETE is justified ✓")
    finally:
        print("\nstop disposable Kodi")
        try:
            stop()
        except RuntimeError:
            pass
    print("real Kodi profile was not accessed by this gate ✓")
    print("\n=== BM-021B frozen capture validation FINISHED ===\n")


def validate_updater_guard() -> None:
    """Prove the global updater setting through two disposable restarts."""
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.update_guard import (
        AddonUpdatePolicy,
        AddonUpdateGuard,
        KodiJsonRpcUpdatePolicyBackend,
    )

    print("=== Build Manager BM-021B live validation: global updater guard ===")
    verify_isolation()
    guard = None
    restored = False
    try:
        reset()
        install(source=PROJECT)
        configure_webserver()
        launch()
        wait_for_ready(timeout=90.0)
        backend = KodiJsonRpcUpdatePolicyBackend(jsonrpc)
        guard = AddonUpdateGuard(backend)
        original = backend.get_policy()
        print(f"  initial policy={original.name} read through Settings.GetSettingValue ✓")
        guard.engage()
        if backend.get_policy() != AddonUpdatePolicy.NEVER_CHECK:
            raise RuntimeError("NEVER_CHECK was not read back after setting it")
        print("  NEVER_CHECK set and read back through Settings.SetSettingValue ✓")
        log_before_restart = _bm020b_log_text()
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        persisted = backend.get_policy()
        if persisted != AddonUpdatePolicy.NEVER_CHECK:
            guard.reassert()
            if backend.get_policy() != AddonUpdatePolicy.NEVER_CHECK:
                raise RuntimeError("NEVER_CHECK could not be deterministically reasserted after restart")
            print(
                f"  NEVER_CHECK did not persist (observed {persisted.name}); "
                "deterministic reassertion succeeded before any capture mutation ✓"
            )
        else:
            print("  NEVER_CHECK survived the disposable restart ✓")
        log_after_restart = _bm020b_log_text()
        appended = log_after_restart[len(log_before_restart):]
        forbidden = ("running scheduled update", "checking for updates")
        if any(marker in appended for marker in forbidden):
            raise RuntimeError("repository updater activity occurred while NEVER_CHECK was active")
        print("  no scheduled updater activity appeared while NEVER_CHECK was active ✓")
        guard.restore()
        restored = True
        if backend.get_policy() != original:
            raise RuntimeError("original updater policy did not restore")
        print(f"  original policy={original.name} restored and verified ✓")
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        if backend.get_policy() != original:
            raise RuntimeError("restored updater policy did not survive restart")
        print("  restored policy survived the second disposable restart ✓")
    finally:
        if guard is not None and guard.engaged and not restored:
            print("  guard remains engaged after failure; no silent restoration performed")
        try:
            stop()
        except RuntimeError:
            pass
    print("supported Settings API only; no Kodi database writes; real profile untouched ✓")
    print("\n=== BM-021B updater guard validation PASSED ===\n")


# ---------------------------------------------------------------------------
# BM-022: exact frozen installation
# ---------------------------------------------------------------------------

def _make_bm022_fixture_zip(
    addon_id: str,
    version: str,
    *,
    requires: Optional[List[tuple]] = None,
    repository: bool = False,
    setting: bool = False,
) -> bytes:
    """Create a real, self-contained Kodi ZIP for the BM-022 disposable gate."""
    requires = requires or []
    requires_xml = "".join(
        f'<import addon="{addon}" version="{minimum}"/>'
        for addon, minimum in requires
    )
    extension = (
        '<extension point="xbmc.addon.repository">'
        '<dir><info>http://127.0.0.1:9999/addons.xml</info>'
        '<datadir zip="true">http://127.0.0.1:9999/</datadir></dir>'
        '</extension>'
        if repository else
        '<extension point="xbmc.python.pluginsource" library="default.py"/>'
    )
    xml = (
        f'<addon id="{addon_id}" name="{addon_id}" version="{version}" '
        'provider-name="Build Manager">'
        f'<requires>{requires_xml}</requires>{extension}'
        '<extension point="xbmc.addon.metadata"><summary lang="en_gb">'
        'BM-022 disposable fixture</summary><platform>all</platform></extension>'
        '</addon>'
    ).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{addon_id}/addon.xml", xml)
        if repository:
            archive.writestr(f"{addon_id}/icon.png", b"BM-022 repository fixture")
        else:
            archive.writestr(f"{addon_id}/default.py", b"# BM-022 fixture")
            if setting:
                archive.writestr(
                    f"{addon_id}/resources/settings.xml",
                    b'<settings version="1">'
                    b'<section id="bm022"><category id="general" label="30000">'
                    b'<group id="1" label="30000">'
                    b'<setting id="bm022.enabled" type="boolean" label="30001">'
                    b'<level>0</level><default>false</default>'
                    b'<control type="toggle"/>'
                    b'</setting></group></category></section></settings>',
                )
    return buf.getvalue()


def _prepare_bm022_fixture() -> Dict[str, Path]:
    """Build a complete fixture in the disposable profile's artifact store."""
    from resources.lib.artifacts import ArtifactStore
    from resources.lib.frozen import (
        AddonCaptureNode,
        CaptureStatus,
        DependencyEdge,
        FrozenBuildManifest,
        ProvenanceStatus,
    )

    artifact_root = KODI_USERDATA_DIR / "addon_data" / ADDON_ID / "frozen-artifacts"
    artifact_store = ArtifactStore(artifact_root)
    definitions = (
        (
            _BM022_REPO_ID,
            _make_bm022_fixture_zip(_BM022_REPO_ID, _BM022_VERSION, repository=True),
            "xbmc.addon.repository",
            False,
            (),
        ),
        (
            _BM022_DEP_ID,
            _make_bm022_fixture_zip(_BM022_DEP_ID, _BM022_VERSION),
            "xbmc.python.module",
            True,
            (),
        ),
        (
            _BM022_APP_ID,
            _make_bm022_fixture_zip(
                _BM022_APP_ID,
                _BM022_VERSION,
                requires=((_BM022_DEP_ID, _BM022_VERSION),),
                setting=True,
            ),
            "xbmc.python.pluginsource",
            True,
            (DependencyEdge(_BM022_DEP_ID, _BM022_VERSION, False, (_BM022_APP_ID,)),),
        ),
    )
    nodes = []
    hashes = {}
    for addon_id, data, addon_type, enabled, edges in definitions:
        metadata = artifact_store.import_zip(
            data,
            expected_addon_id=addon_id,
            expected_version=_BM022_VERSION,
            source="bm022-test-fixture",
        )
        hashes[addon_id] = metadata.sha256
        nodes.append(AddonCaptureNode(
            addon_id=addon_id,
            version=_BM022_VERSION,
            addon_type=addon_type,
            desired_enabled=enabled,
            provenance=ProvenanceStatus.MANUAL_OR_UNKNOWN,
            provenance_detail={"fixture": "repository-owned-test-artifact"},
            artifact=metadata,
            dependency_edges=edges,
            status=CaptureStatus.COMPLETE,
        ))
    nodes.append(AddonCaptureNode(
        addon_id="xbmc.python",
        version="3.0.1",
        addon_type="system",
        desired_enabled=True,
        provenance=ProvenanceStatus.UNKNOWN,
        system=True,
        status=CaptureStatus.SYSTEM,
    ))
    manifest = FrozenBuildManifest(
        schema_version=1,
        build_id="bm022-disposable-fixture",
        name="BM-022 complete disposable fixture",
        created_at="2026-09-21T00:00:00Z",
        kodi_version="21.1",
        platform="macos",
        capture_status=CaptureStatus.COMPLETE,
        addons=tuple(nodes),
        source_metadata={"fixture": "test-only-real-kodi-zips"},
    )
    manifest_path = ROOT / "bm022-frozen-manifest.json"
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    configuration_path = ROOT / "bm022-configuration-manifest.json"
    configuration_path.write_text(json.dumps({
        "schema_version": 1,
        "engine_min_version": "0.1.0",
        "build": {
            "id": "bm022-configuration-fixture",
            "version": "1.0.0",
            "name": "BM-022 configuration fixture",
            "description": "Disposable test-only configuration binding.",
        },
        "addons": [{"addon_id": _BM022_APP_ID, "state": "enabled"}],
        "config": {
            "packages": ["bm022-fixture"],
            "managed_settings": [{
                "target": "addon",
                "addon_id": _BM022_APP_ID,
                "keys": ["bm022.enabled"],
            }],
            "managed_files": [],
        },
        "platform_profiles": {"disposable": {"label": "BM-022 disposable"}},
        "device_profiles": {
            "bm022-disposable": {
                "label": "BM-022 disposable configuration",
                "extends": "disposable",
            }
        },
    }, indent=2) + "\n", encoding="utf-8")
    return {
        "artifact_root": artifact_root,
        "manifest_path": manifest_path,
        "configuration_path": configuration_path,
        "hashes": hashes,
    }


def validate_frozen_install() -> None:
    """Prove exact install, restart reassertion, configuration, and release."""
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.update_guard import AddonUpdatePolicy, KodiJsonRpcUpdatePolicyBackend

    print("=== Build Manager BM-022 live validation: frozen installation ===")
    verify_isolation()
    real_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns if NORMAL_APPDATA_DIR.exists() else None
    try:
        print("\n[1/18] reset, install Build Manager, and prepare complete fixture")
        reset()
        install(source=PROJECT)
        fixture = _prepare_bm022_fixture()
        _install_bm015_config_runner()
        configure_webserver()
        launch()
        wait_for_ready(timeout=90.0)
        jsonrpc("Addons.SetAddonEnabled", {
            "addonid": ADDON_ID,
            "enabled": True,
        })
        production_detail = jsonrpc("Addons.GetAddonDetails", {
            "addonid": ADDON_ID,
            "properties": ["enabled"],
        })
        if not (
            isinstance(production_detail, dict)
            and isinstance(production_detail.get("addon"), dict)
            and production_detail["addon"].get("enabled") is True
        ):
            raise RuntimeError(
                f"BM-022 production add-on could not be enabled: {production_detail!r}"
            )
        jsonrpc("Addons.SetAddonEnabled", {
            "addonid": _BM015_RUNNER_ADDON_ID,
            "enabled": True,
        })
        runner_detail = jsonrpc("Addons.GetAddonDetails", {
            "addonid": _BM015_RUNNER_ADDON_ID,
            "properties": ["enabled"],
        })
        if not (
            isinstance(runner_detail, dict)
            and isinstance(runner_detail.get("addon"), dict)
            and runner_detail["addon"].get("enabled") is True
        ):
            raise RuntimeError(f"BM-022 runner could not be enabled: {runner_detail!r}")
        original = KodiJsonRpcUpdatePolicyBackend(jsonrpc).get_policy()
        print(f"  original global updater policy={original.name} ✓")
        print("  complete fixture contains repository, dependency, ordinary add-on, and system boundary ✓")

        print("\n[2/18] start production BM-022 coordinator and persist transaction")
        started = _bm015_run_job({
            "mode": "frozen_install",
            "manifest_path": str(fixture["manifest_path"]),
            "configuration_manifest_path": str(fixture["configuration_path"]),
            "artifact_root": str(fixture["artifact_root"]),
            "device_profile_id": "bm022-disposable",
            "force_restart": True,
        })
        if not started.get("ok") or started.get("outcome") != "awaiting_restart":
            raise RuntimeError(f"BM-022 coordinator did not reach restart handoff: {started}")
        if started.get("policy") != int(AddonUpdatePolicy.NEVER_CHECK):
            raise RuntimeError("BM-022 did not leave NEVER_CHECK active at restart handoff")
        tx = started.get("transaction") or {}
        if tx.get("phase") != "awaiting_restart":
            raise RuntimeError(f"unexpected frozen transaction phase: {tx}")
        print("  transaction persisted before mutation and phase=awaiting_restart ✓")
        print("  NEVER_CHECK verified before exact package installation ✓")

        print("\n[3/18] verify exact frozen versions and dependency ordering")
        expected_versions = {
            _BM022_REPO_ID: _BM022_VERSION,
            _BM022_DEP_ID: _BM022_VERSION,
            _BM022_APP_ID: _BM022_VERSION,
        }
        for addon_id, version in expected_versions.items():
            detail = jsonrpc("Addons.GetAddonDetails", {
                "addonid": addon_id, "properties": ["enabled", "version"]
            }).get("addon", {})
            if detail.get("version") != version:
                raise RuntimeError(f"wrong exact version for {addon_id}: {detail}")
            print(f"  {addon_id} installed exactly at {version} ✓")
        expected_order = [_BM022_REPO_ID, _BM022_DEP_ID, _BM022_APP_ID]
        if started.get("installation_order") != expected_order:
            raise RuntimeError(
                "unexpected deterministic installation order: "
                f"{started.get('installation_order')}"
            )
        print("  repository → dependency → ordinary add-on ordering verified ✓")

        print("\n[4/18] verify BM-020 restart transaction and exact artifact selection")
        bm020_tx = _bm015_run_job({"mode": "transaction_inspect"})
        if not bm020_tx.get("ok") or not bm020_tx.get("transaction"):
            raise RuntimeError(f"BM-020 transaction missing at restart boundary: {bm020_tx}")
        for addon_id, digest in fixture["hashes"].items():
            print(f"  {addon_id}: artifact_sha256={digest} exact fixture selected ✓")

        print("\n[5/18] cross Kodi restart and allow startup coordinator to resume")
        stop()
        launch()
        wait_for_ready(timeout=90.0)
        deadline = time.time() + 60.0
        final_tx = None
        while time.time() < deadline:
            final_tx = _bm015_run_job({"mode": "frozen_inspect"})
            if final_tx.get("ok") and final_tx.get("transaction") is None:
                break
            time.sleep(0.5)
        if final_tx.get("transaction") is not None:
            raise RuntimeError(f"frozen transaction did not finalize after restart: {final_tx}")
        print("  frozen transaction survived restart and later cleared after resume ✓")

        log_after = KODI_LOG_FILE.read_text(encoding="utf-8", errors="replace") if KODI_LOG_FILE.exists() else ""
        guard_marker = "BM-022 updater guard reasserted before BM-020 startup"
        resume_marker = "Build Manager BM-020C startup"
        guard_index = log_after.rfind(guard_marker)
        resume_index = log_after.rfind(resume_marker)
        if guard_index < 0 or resume_index < 0:
            raise RuntimeError("restart log did not contain BM-022 guard and BM-020 startup evidence")
        if guard_index > resume_index:
            raise RuntimeError("BM-020 startup log preceded BM-022 guard reassertion")
        print("  log ordering proves updater guard reasserted before BM-020 startup ✓")

        print("\n[6/18] verify configuration, final state, and updater restoration")
        setting = _bm015_run_job({
            "mode": "frozen_observe_setting",
            "addon_id": _BM022_APP_ID,
            "key": "bm022.enabled",
        })
        if not setting.get("ok") or setting.get("value") is not True:
            raise RuntimeError(f"configuration was not applied through Build Manager: {setting}")
        final_policy = KodiJsonRpcUpdatePolicyBackend(jsonrpc).get_policy()
        if final_policy != original:
            raise RuntimeError(f"original updater policy was not restored: {final_policy.name}")
        if _bm015_run_job({"mode": "transaction_inspect"}).get("transaction") is not None:
            raise RuntimeError("BM-020 transaction remained after frozen completion")
        print("  existing Build Manager configuration path succeeded ✓")
        print(f"  original updater policy={original.name} restored and verified ✓")
        print("  BM-020 transaction absent and final frozen release complete ✓")
    finally:
        try:
            stop()
        except RuntimeError:
            pass
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists() and NORMAL_APPDATA_DIR.stat().st_mtime_ns != real_mtime_ns:
        raise RuntimeError("real Kodi profile mtime changed during BM-022 gate")
    print("  real Kodi profile remained untouched ✓")
    print("\n=== BM-022 frozen installation validation PASSED ===\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Manager disposable Kodi test harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    sub.add_parser("reset", help="Remove and recreate the disposable profile")

    p_install = sub.add_parser("install", help="Copy script.build.manager into the disposable profile")
    p_install.add_argument(
        "--source", type=Path, metavar="DIR",
        help="Add-on source directory (default: project root)",
    )

    sub.add_parser("configure", help="Write guisettings.xml to enable JSON-RPC web server")
    sub.add_parser("enable-webserver", help="Alias for configure")

    sub.add_parser("launch", help="Start Kodi with the disposable profile")

    p_wait = sub.add_parser("wait", help="Wait for Kodi JSON-RPC to become available")
    p_wait.add_argument(
        "--timeout", type=float, default=60.0, metavar="SECS",
        help="Seconds to wait (default: 60)",
    )

    sub.add_parser("stop", help="Send SIGTERM to the disposable Kodi process")
    sub.add_parser("restart", help="Stop then relaunch Kodi")

    sub.add_parser("inspect", help="Query disposable Kodi state via HTTP JSON-RPC")
    sub.add_parser("status", help="Print current harness state")
    sub.add_parser("validate", help="Run the full live validation sequence")
    sub.add_parser("validate-repo", help="BM-010 live validation: repository detection/install")
    sub.add_parser("validate-addon", help="BM-011 live validation: general add-on installation")
    sub.add_parser("validate-dependencies", help="BM-012 live validation: dependency closure discovery/reconciliation")
    sub.add_parser("validate-addon-state", help="BM-013 live validation: enable/disable state reconciliation")
    sub.add_parser("validate-post-operations", help="BM-014 live validation: post-operation state validation")
    sub.add_parser("validate-config", help="BM-015 live validation: configuration package deployment")
    sub.add_parser("validate-af3-package", help="BM-018E live validation: production AF3 package")
    sub.add_parser("validate-skin-config", help="BM-018D live validation: typed AF3 skin configuration")
    sub.add_parser("validate-build-manager", help="BM-020A live validation: production executor")
    sub.add_parser("validate-build-manager-transaction", help="BM-020B live validation: transaction startup")
    sub.add_parser("validate-build-manager-manual-restart", help="BM-020C1 live validation: manual restart handoff")
    sub.add_parser("validate-build-manager-resume", help="BM-020C live validation: automatic post-restart resume")
    sub.add_parser("validate-frozen-capture", help="BM-021B disposable exact-artifact capture proof")
    sub.add_parser("validate-updater-guard", help="BM-021B disposable global updater-guard proof")
    sub.add_parser("validate-frozen-install", help="BM-022 disposable exact frozen-install proof")

    args = parser.parse_args(argv)
    cmd: str = args.command

    try:
        if cmd == "reset":
            reset()
        elif cmd == "install":
            install(source=getattr(args, "source", None))
        elif cmd in ("configure", "enable-webserver"):
            configure_webserver()
        elif cmd == "launch":
            launch()
        elif cmd == "wait":
            wait_for_ready(timeout=args.timeout)
        elif cmd == "stop":
            stop()
        elif cmd == "restart":
            restart()
        elif cmd == "inspect":
            state = inspect()
            print(json.dumps(state, indent=2, default=str))
        elif cmd == "status":
            s = status()
            for k, v in s.items():
                print(f"{k}: {v}")
        elif cmd == "validate":
            validate()
        elif cmd == "validate-repo":
            validate_repo()
        elif cmd == "validate-addon":
            validate_addon()
        elif cmd == "validate-dependencies":
            validate_dependencies()
        elif cmd == "validate-addon-state":
            validate_addon_state()
        elif cmd == "validate-post-operations":
            validate_post_operations()
        elif cmd == "validate-config":
            validate_config()
        elif cmd == "validate-skin-config":
            validate_skin_config()
        elif cmd == "validate-af3-package":
            validate_af3_package()
        elif cmd == "validate-build-manager":
            validate_build_manager()
        elif cmd == "validate-build-manager-transaction":
            validate_build_manager_transaction()
        elif cmd == "validate-build-manager-manual-restart":
            validate_build_manager_manual_restart()
        elif cmd == "validate-build-manager-resume":
            validate_build_manager_resume()
        elif cmd == "validate-frozen-capture":
            validate_frozen_capture()
        elif cmd == "validate-updater-guard":
            validate_updater_guard()
        elif cmd == "validate-frozen-install":
            validate_frozen_install()
        return 0
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
