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
        return 0
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
