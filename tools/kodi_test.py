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
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
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
ADDON_INCLUDE: frozenset = frozenset({"addon.xml", "default.py", "resources"})

WEBSERVER_PORT = 8920
WEBSERVER_USERNAME = "bm-test"
WEBSERVER_PASSWORD = "bm-test-only"

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


def _make_bm011_addons_xml() -> bytes:
    """Build the addons.xml repository index listing the test add-on."""
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
        '</addons>\n'
    ).encode("utf-8")


def _make_bm011_repo_zip(server_port: int) -> bytes:
    """Build the test repository ZIP for BM-011, with info/datadir URLs pointing to localhost.

    The repository addon.xml includes <info>, <datadir>, and <checksum> elements
    so Kodi can fetch the add-on index and download the test add-on ZIP.
    The server must be running at server_port before Kodi tries to scan this repo.
    """
    base_url = f"http://127.0.0.1:{server_port}"
    addon_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{_TEST_REPO_ADDON_ID}"'
        ' name="Build Manager Test Repo"'
        ' version="2.0.0"'
        ' provider-name="Build Manager">'
        f'<extension point="xbmc.addon.repository" name="Build Manager Test">'
        f'<info compressed="false">{base_url}/addons.xml</info>'
        f'<datadir zip="false">{base_url}/</datadir>'
        f'<checksum>{base_url}/addons.xml.md5</checksum>'
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

    def log_message(self, fmt, *args) -> None:  # suppress request logging
        pass


class _HttpAddonBackend:
    """Add-on backend for BM-011 live validation. Uses HTTP JSON-RPC.

    invoke_install() triggers Kodi's InstallAddon builtin via the harness
    trigger script (Addons.ExecuteAddon). This is equivalent to what
    KodiRuntimeAddonBackend.invoke_install() does from inside Kodi.
    """

    def get_addon_details(self, addon_id: str) -> Optional["InstalledAddonInfo"]:
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))
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

    def invoke_install(self, addon_id: str) -> None:
        """Invoke InstallAddon via the harness trigger script + Addons.ExecuteAddon.

        The trigger script calls xbmc.executebuiltin("InstallAddon(addon_id)"),
        which is the production KodiRuntimeAddonBackend.invoke_install path.
        This proves Kodi itself handles the download, extraction, and registration.
        """
        if str(PROJECT) not in sys.path:
            sys.path.insert(0, str(PROJECT))
        from resources.lib.addons import AddonInstallError
        try:
            jsonrpc("Addons.ExecuteAddon", {
                "addonid": _HARNESS_TRIGGER_ADDON_ID,
                "params": addon_id,
                "wait": False,
            })
        except RuntimeError as exc:
            raise AddonInstallError(
                f"Addons.ExecuteAddon(trigger, {addon_id!r}) failed: {exc}"
            ) from exc

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

    Sequence (17 steps):
     1  Reset disposable harness
     2  Install Build Manager + harness trigger script
     3  Configure web server
     4  Create test content + start HTTP server (127.0.0.1:8922)
     5  Launch Kodi + wait for ready
     6  Verify test add-on NOT installed before any action
     7  Install test repository via BM-010 RepositoryManager.install
        (includes UpdateLocalAddons restart; trigger script registered)
     8  Wait for Kodi to index the test repository (fetches addons.xml)
     9  Verify test add-on still NOT installed (available but not installed)
    10  Install test add-on via AddonManager.install (Kodi owns the install)
    11  Verify result.status == INSTALLED
    12  Verify Addons.GetAddonDetails: installed + enabled
    13  Restart disposable Kodi + wait for ready
    14  Verify test add-on still installed and enabled after restart
    15  Install again → verify ALREADY_INSTALLED (idempotency)
    16  Stop Kodi + shut down HTTP server
    17  Confirm real Kodi profile untouched

    CRITICAL PROOF: Kodi itself retrieves and installs the test add-on from
    the enabled test repository. Build Manager does NOT download or extract
    the add-on ZIP directly (that is BM-010's repository bootstrap fallback).

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

    print("\n[1/17] reset")
    reset()

    print("\n[2/17] install Build Manager + harness trigger script")
    install()
    _install_harness_trigger_script()

    print("\n[3/17] configure web server")
    configure_webserver()

    print("\n[4/17] create test content + start HTTP server (127.0.0.1:8922)")
    addon_zip = _make_bm011_test_addon_zip()
    addons_xml = _make_bm011_addons_xml()
    addons_xml_md5 = hashlib.md5(addons_xml).hexdigest().encode("utf-8")
    repo_zip = _make_bm011_repo_zip(_ADDON_SERVER_PORT)
    print(f"  test repo ZIP: {len(repo_zip)} bytes")
    print(f"  addons.xml: {len(addons_xml)} bytes (md5={addons_xml_md5.decode()})")
    print(f"  test addon ZIP: {len(addon_zip)} bytes")

    addon_zip_path = (
        f"/{_BM011_TEST_ADDON_ID}/{_BM011_TEST_ADDON_VERSION}"
        f"/{_BM011_TEST_ADDON_ID}-{_BM011_TEST_ADDON_VERSION}.zip"
    )
    server_files = {
        f"/{_TEST_REPO_ADDON_ID}.zip": repo_zip,
        "/addons.xml": addons_xml,
        "/addons.xml.md5": addons_xml_md5,
        addon_zip_path: addon_zip,
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
        print("\n[5/17] launch Kodi + wait for ready (up to 90s)")
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            stop()
            raise RuntimeError(f"Validation failed at step 5: {exc}") from exc

        print("\n[6/17] verify test add-on NOT installed before any action")
        if addon_mgr.is_installed(_BM011_TEST_ADDON_ID):
            stop()
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID!r} already installed before test"
            )
        print(f"  is_installed({_BM011_TEST_ADDON_ID!r}) = False ✓")

        print("\n[7/17] install test repository via BM-010 RepositoryManager.install")
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

        print("\n[8/17] wait for Kodi to index test repository (up to 90s)")
        found = _wait_for_addon_in_repo_index(_BM011_TEST_ADDON_ID, timeout=90.0)
        if found:
            print(f"  {_BM011_TEST_ADDON_ID!r} found in Kodi repo index ✓")
        else:
            print(
                f"  WARNING: {_BM011_TEST_ADDON_ID!r} not yet in Kodi repo index "
                f"after 90s; proceeding (InstallAddon may still succeed)"
            )

        print("\n[9/17] verify test add-on still NOT installed (available, not installed)")
        if addon_mgr.is_installed(_BM011_TEST_ADDON_ID):
            raise RuntimeError(
                f"Validation failed: {_BM011_TEST_ADDON_ID!r} appeared as installed "
                f"before AddonManager.install was called"
            )
        print(f"  is_installed({_BM011_TEST_ADDON_ID!r}) = False ✓ (available, not installed)")

        print("\n[10/17] install test add-on via AddonManager.install")
        print("  (Kodi retrieves and installs from the test repository — BM-011 path)")
        install_result = addon_mgr.install(_BM011_TEST_ADDON_ID, desired_state="enabled")
        print(f"  result.status = {install_result.status.value!r}")
        print(f"  result.enabled = {install_result.enabled!r}")
        print(f"  result.version = {install_result.version!r}")
        print(f"  result.message = {install_result.message!r}")

        print("\n[11/17] verify result.status == INSTALLED")
        if install_result.status != AddonStatus.INSTALLED:
            raise RuntimeError(
                f"Validation failed: install returned {install_result.status.value!r} "
                f"— {install_result.message}"
            )
        print("  status = INSTALLED ✓")

        print("\n[12/17] verify Addons.GetAddonDetails: installed + enabled")
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
                f"Validation failed: add-on directory {addon_dir} not found "
                f"(Kodi did not extract the add-on ZIP)"
            )
        addon_xml_path = addon_dir / "addon.xml"
        if not addon_xml_path.is_file():
            raise RuntimeError(
                f"Validation failed: {addon_dir}/addon.xml missing"
            )
        print(f"  addon directory present: {addon_dir} ✓")
        print("  CRITICAL PROOF: files extracted by Kodi (not by Build Manager) ✓")

        print("\n[13/17] restart disposable Kodi + wait for ready")
        stop()
        launch()
        try:
            wait_for_ready(timeout=90.0)
        except TimeoutError as exc:
            raise RuntimeError(f"Validation failed at step 13: {exc}") from exc
        print("  Kodi restarted ✓")

        print("\n[14/17] verify test add-on still installed and enabled after restart")
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
        print(f"  enabled=True after restart ✓")
        print(f"  is_installed({_BM011_TEST_ADDON_ID!r}) = True after restart ✓")

        print("\n[15/17] install again → verify ALREADY_INSTALLED (idempotency)")
        result2 = addon_mgr.install(_BM011_TEST_ADDON_ID, desired_state="enabled")
        print(f"  result.status = {result2.status.value!r}")
        if result2.status != AddonStatus.ALREADY_INSTALLED:
            raise RuntimeError(
                f"Validation failed: second install returned {result2.status.value!r} "
                f"instead of already_installed"
            )
        print("  status = ALREADY_INSTALLED ✓ (no mutation)")

    finally:
        print("\n[16/17] stop Kodi + shut down HTTP server")
        try:
            stop()
        except RuntimeError:
            pass
        server.shutdown()

    print("\n[17/17] confirm real Kodi profile untouched")
    if real_mtime_ns is not None and NORMAL_APPDATA_DIR.exists():
        current_mtime_ns = NORMAL_APPDATA_DIR.stat().st_mtime_ns
        if current_mtime_ns != real_mtime_ns:
            raise RuntimeError(
                f"Validation FAILED: real profile mtime changed! "
                f"Was {real_mtime_ns}, now {current_mtime_ns}"
            )
    print(f"  {NORMAL_APPDATA_DIR} unchanged ✓")

    print("\n=== BM-011 validation PASSED ===\n")


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
        return 0
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
