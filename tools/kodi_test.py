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
"""

from __future__ import annotations

import argparse
import base64
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
        from resources.lib.repository import _extract_zip_to_directory
        target = KODI_ADDONS_DIR / addon_id
        if target.exists():
            shutil.rmtree(target)
        _extract_zip_to_directory(zip_bytes, addon_id, target)

    def trigger_addon_scan(self) -> None:
        print("    trigger_addon_scan: restart Kodi to run UpdateLocalAddons")
        stop()
        launch()
        wait_for_ready(timeout=90.0)

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
                if addon_id in self.get_installed_addon_ids():
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
    """Live validation of BM-010 repository detection and installation.

    Sequence (12 steps):
     1  Reset disposable harness
     2  Install Build Manager
     3  Configure web server
     4  Launch Kodi
     5  Wait for ready
     6  Create test repository ZIP
     7  Start localhost HTTP server (127.0.0.1 only)
     8  Verify repository NOT yet installed
     9  Call RepositoryManager.install()
    10  Verify result status = INSTALLED
    11  Verify is_installed() now returns True
    12  Stop Kodi + shut down HTTP server

    ALL mutation occurs only in the disposable .kodi-test environment.
    """
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from resources.lib.manifest import Repository
    from resources.lib.repository import RepositoryManager, RepositoryStatus

    print("=== Build Manager BM-010 live validation: repository detection/install ===")
    verify_isolation()

    print("\n[1/12] reset")
    reset()

    print("\n[2/12] install Build Manager")
    install()

    print("\n[3/12] configure web server")
    configure_webserver()

    print("\n[4/12] launch Kodi")
    launch()

    print("\n[5/12] wait for ready (up to 90s)")
    try:
        wait_for_ready(timeout=90.0)
    except TimeoutError as exc:
        stop()
        raise RuntimeError(f"Validation failed at step 5: {exc}") from exc

    print("\n[6/12] create test repository ZIP")
    zip_bytes = _make_test_repo_zip()
    print(f"  {_TEST_REPO_ADDON_ID}: {len(zip_bytes)} bytes")

    print("\n[7/12] start localhost HTTP server (127.0.0.1 only)")

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

        print("\n[8/12] verify repository NOT yet installed")
        before = mgr.is_installed(_TEST_REPO_ADDON_ID)
        if before:
            stop()
            raise RuntimeError(
                f"Validation failed: {_TEST_REPO_ADDON_ID!r} already installed before test"
            )
        print(f"  is_installed({_TEST_REPO_ADDON_ID!r}) = False ✓")

        print("\n[9/12] install repository")
        result = mgr.install(test_repo)
        print(f"  result.status = {result.status.value!r}")
        print(f"  result.message = {result.message!r}")

        print("\n[10/12] verify result status = INSTALLED")
        if result.status != RepositoryStatus.INSTALLED:
            stop()
            raise RuntimeError(
                f"Validation failed: install returned {result.status.value!r} "
                f"— {result.message}"
            )
        print("  status = INSTALLED ✓")

        print("\n[11/12] verify is_installed() now returns True")
        after = mgr.is_installed(_TEST_REPO_ADDON_ID)
        if not after:
            stop()
            raise RuntimeError(
                f"Validation failed: {_TEST_REPO_ADDON_ID!r} not detected after install"
            )
        print(f"  is_installed({_TEST_REPO_ADDON_ID!r}) = True ✓")

    finally:
        print("\n[12/12] stop Kodi + shut down HTTP server")
        try:
            stop()
        except RuntimeError:
            pass
        server.shutdown()

    print("\n=== BM-010 validation PASSED ===\n")


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
        return 0
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
