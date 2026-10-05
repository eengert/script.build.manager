"""Offline tests for tools/bm_test_app.py.

Every test uses temporary fixtures only. A filesystem tripwire fails any test
that touches the real Test.app, the normal Kodi application, or the normal Kodi
profile; the real Test.app is never contacted.
"""

from __future__ import annotations

import ast
import base64
import builtins
import contextlib
import copy
import ctypes
import errno
import hashlib
import http.server
import io
import json
import os
import plistlib
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import bm023a_adapter_support as adapter_support
from tools import bm_test_app as bm
from tools import build_bm023a_adapter

PROJECT = Path(__file__).resolve().parents[1]
REAL_CANDIDATE = "8789329054b77815c6f9548fd4ce9beacbe1d348"
SENTINEL_PASSWORD = "S3ntinel-Kodi-Password-DoNotLeak"
SENTINEL_PRIVATE = "SENTINEL-PRIVATE-REDLIGHT-VALUE-7731"
SENTINEL_OVERLAY_PATH = "/Users/example/private-sentinel/overlay-source-4821.json"
ADAPTER_VALUES = {
    "MANIFEST_PATH": "/Users/example/archive-sentinel/frozen-manifest-1177.json",
    "ARTIFACT_ROOT": "/Users/example/archive-sentinel/artifacts-2288",
    "CONFIGURATION_PATH": "/Users/example/archive-sentinel/configuration-3399.json",
    "OVERLAY_SOURCE": SENTINEL_OVERLAY_PATH,
    "DEVICE_PROFILE_ID": "fixture-device",
    "EXPECTED_OVERLAY_ID": "fixture-overlay-1.0",
}


# ---------------------------------------------------------------------------
# Safety net: nothing may touch the real Test.app, normal Kodi, or its profile
# ---------------------------------------------------------------------------

class FilesystemTripwire:
    """Records (and raises on) any access to a forbidden surface."""

    PATH_FUNCTIONS = (
        (os, "stat", (0,)), (os, "lstat", (0,)), (os, "scandir", (0,)), (os, "listdir", (0,)),
        (os, "open", (0,)), (os, "access", (0,)), (os, "readlink", (0,)), (os, "mkdir", (0,)),
        (os, "rename", (0, 1)), (os, "link", (0, 1)), (os, "unlink", (0,)), (os, "rmdir", (0,)),
        (os, "chmod", (0,)), (os, "utime", (0,)), (os, "symlink", (0, 1)),
    )

    def __init__(self) -> None:
        home = os.path.expanduser("~")
        bases = [
            "/Applications/Kodi.app",
            bm.AUTHORIZED_TEST_APP,
            "/Users/eengert/Library/Application Support/Kodi",
            os.path.join(home, "Library", "Application Support", "Kodi"),
        ]
        prefixes = set()
        for base in bases:
            prefixes.add(os.path.normpath(base).casefold())
            prefixes.add((bm._DATA_VOLUME_ALIAS + os.path.normpath(base)).casefold())
        self.prefixes = tuple(sorted(prefixes))
        self.touched = []
        self._patches = []

    def _check(self, api, value):
        if isinstance(value, int):
            return
        try:
            text = os.fsdecode(value)
        except Exception:
            return
        if not text:
            return
        # Independent policy: reject opaque namespaces at any component, and
        # collapse all leading separators before checking ordinary/Data aliases.
        parts = text.casefold().split("/")
        if any(part in (".vol", ".nofollow", ".resolve") for part in parts):
            self.touched.append((api, text))
            raise AssertionError("tripwire: opaque filesystem namespace")
        folded = os.path.normpath("/" + os.path.abspath(text).lstrip("/")).casefold()
        if any(folded == prefix or folded.startswith(prefix + "/") for prefix in self.prefixes):
            self.touched.append((api, text))
            raise AssertionError(f"tripwire: {api} touched forbidden path {text!r}")

    def _wrap(self, original, name, indexes):
        def guarded(*args, **kwargs):
            for index in indexes:
                if index < len(args):
                    self._check(name, args[index])
            for key in ("path", "src", "dst", "file"):
                if key in kwargs:
                    self._check(name, kwargs[key])
            return original(*args, **kwargs)
        return guarded

    def start(self):
        for module, name, indexes in self.PATH_FUNCTIONS:
            original = getattr(module, name)
            patcher = mock.patch.object(module, name, self._wrap(original, name, indexes))
            patcher.start()
            self._patches.append(patcher)
        for module, name in ((builtins, "open"), (io, "open")):
            original = getattr(module, name)
            patcher = mock.patch.object(module, name, self._wrap(original, name, (0,)))
            patcher.start()
            self._patches.append(patcher)
        original_connect = sqlite3.connect
        patcher = mock.patch.object(sqlite3, "connect", self._wrap(original_connect, "sqlite3.connect", (0,)))
        patcher.start()
        self._patches.append(patcher)
        return self

    def stop(self):
        while self._patches:
            self._patches.pop().stop()


class TripwireTestCase(unittest.TestCase):
    """Base class: temp dir, tripwire, and a no-forbidden-access assertion."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="bm-test-app-test-")))
        self.addCleanup(self._remove_tmp)
        self.tripwire = FilesystemTripwire().start()
        self.addCleanup(self._check_tripwire)
        self.addCleanup(self.tripwire.stop)

    def _remove_tmp(self):
        for root, dirs, files in os.walk(self.tmp):
            for name in dirs:
                with contextlib.suppress(OSError):
                    os.chmod(os.path.join(root, name), 0o755)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _check_tripwire(self):
        # Runs after tripwire.stop is queued (LIFO): inspect recorded hits.
        self.assertEqual(self.tripwire.touched, [], "a forbidden surface was touched")


# ---------------------------------------------------------------------------
# Fakes and fixtures
# ---------------------------------------------------------------------------

def make_fake_app(base, *, name="Kodi Build Manager Test.app", executable="Kodi",
                  package_type="APPL", portable=True, addons=True, userdata=True):
    root = Path(base) / name
    (root / "Contents" / "MacOS").mkdir(parents=True)
    info = {
        "CFBundleIdentifier": "org.xbmc.kodi",
        "CFBundleExecutable": executable,
        "CFBundlePackageType": package_type,
        "CFBundleShortVersionString": "21.3",
        "CFBundleVersion": "21.3.0",
    }
    (root / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    exe = root / "Contents" / "MacOS" / executable
    exe.write_bytes(b"fake-kodi-binary\n")
    exe.chmod(0o755)
    portable_data = root / "Contents" / "Resources" / "Kodi" / "portable_data"
    if portable:
        portable_data.mkdir(parents=True)
        if addons:
            (portable_data / "addons").mkdir()
        if userdata:
            (portable_data / "userdata").mkdir()
    return bm.TestAppTarget.for_tests(root)


class FakeProcessLister:
    def __init__(self, processes=(), commands=None, fail=False):
        self.processes = list(processes)
        self.commands = dict(commands or {})
        self.fail = fail
        self.command_calls = []

    def list_all(self):
        if self.fail:
            raise bm.HelperError("process_listing_failed")
        return list(self.processes)

    def command_line(self, pid):
        self.command_calls.append(pid)
        command = self.commands.get(pid)
        if command is None or isinstance(command, tuple):
            return command
        # Legacy fixture strings represent simple argv only. Adversarial tests
        # supply tuples explicitly so embedded spaces preserve real boundaries.
        exe = next((p.exe for p in self.processes if p.pid == pid), "")
        ordinary = exe.removeprefix(bm._DATA_VOLUME_ALIAS)
        for alias in (bm._DATA_VOLUME_ALIAS + ordinary, ordinary):
            if command == alias or command.startswith(alias + " "):
                return (alias, *command[len(alias):].split())
        return (command,)

    def run_test_app(self, target, *, pid=4242, executable="Kodi", flags=" -p"):
        exe = os.fspath(target.macos_dir / executable)
        self.processes.append(bm.ProcessInfo(pid, exe))
        self.commands[pid] = exe + flags
        return pid


class FakeClock:
    """Deterministic clock; sleep() advances time and can fire a hook."""

    def __init__(self, start_ns=1_800_000_000_000_000_000):
        self.now_ns = start_ns
        self.mono = 5000.0
        self.sleeps = []
        self.on_sleep = None

    def time_ns(self):
        return self.now_ns

    def monotonic(self):
        return self.mono

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now_ns += int(seconds * 1e9)
        self.mono += seconds
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))

    def utcnow(self):
        return datetime.fromtimestamp(self.now_ns / 1e9, timezone.utc)


class FakeTransport:
    """Scriptable JSON-RPC server; records every request."""

    def __init__(self, handler=None):
        self.requests = []
        self.handler = handler or self.default_handler
        self.password = None
        self.username = "kodi"
        self.execute_hook = None
        self.details = {
            bm.DRIVER_ID: {"enabled": True, "version": "0.0.15"},
            bm.BUILD_MANAGER_ID: {"enabled": True, "version": "0.1.0"},
        }
        self.execute_result = "OK"

    def post(self, host, port, path, body, headers, timeout):
        request = {
            "host": host, "port": port, "path": path,
            "body": json.loads(body), "headers": dict(headers),
        }
        self.requests.append(request)
        return self.handler(request)

    def reply(self, result=None, error=None, status=200):
        document = {"jsonrpc": "2.0", "id": 1}
        if error is not None:
            document["error"] = error
        else:
            document["result"] = result
        return status, json.dumps(document).encode("utf-8")

    def default_handler(self, request):
        if self.password is not None:
            expected = "Basic " + base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            if request["headers"].get("Authorization") != expected:
                return 401, b""
        method, params = request["body"]["method"], request["body"]["params"]
        if method == "JSONRPC.Ping":
            return self.reply("pong")
        if method == "Addons.GetAddonDetails":
            detail = self.details.get(params["addonid"])
            if detail is None:
                return self.reply(error={"code": -32602, "message": "Invalid params."})
            return self.reply({"addon": dict(detail, addonid=params["addonid"])})
        if method == "Addons.ExecuteAddon":
            if self.execute_hook is not None:
                self.execute_hook(params)
            return self.reply(self.execute_result)
        return self.reply(error={"code": -32601, "message": "Method not found."})


def make_services(target, **overrides):
    values = dict(
        target=target,
        process_lister=FakeProcessLister(),
        listener_lookup=lambda port: set(),
        pid_alive=lambda pid: True,
        clock=FakeClock(),
        password_prompt=lambda prompt: (_ for _ in ()).throw(AssertionError("no prompt expected")),
        transport=FakeTransport(),
        git_exe=bm.find_git(),
        git_runner=subprocess.run,
        build_runner=subprocess.run,
        python_exe=sys.executable,
        tmp_root=None,
        repo_default=PROJECT,
        stdout=io.StringIO(),
        secrets=bm.SecretRegistry(),
    )
    values.update(overrides)
    return bm.Services(**values)


def run_cli(services, *argv):
    """Run main() against fake services; returns (exit code, parsed JSON, raw text)."""
    services.stdout = io.StringIO()
    code = bm.main(list(argv), services=services)
    text = services.stdout.getvalue()
    return code, json.loads(text), text


# --- Git fixture: a candidate repository built without touching the checkout ---

GIT_ENV = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo, *args, stdin=None, env=None, check=True):
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", **GIT_ENV, **(env or {})}
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.ignorecase=false", "-c", "core.precomposeunicode=false", *args],
        input=stdin, capture_output=True, env=environment, check=False,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {args} failed: {proc.stderr.decode(errors='replace')}")
    return proc.stdout


def tracked_product_files():
    """Tracked files of this checkout that make up product + builder inputs."""
    output = subprocess.run(
        ["git", "-C", str(PROJECT), "ls-files", "-z", "--", "tools", "resources",
         "addon.xml", "default.py", "service.py"],
        capture_output=True, check=True,
    ).stdout
    return [item.decode() for item in output.split(b"\0") if item]


def build_candidate_repo(base):
    """A repo whose HEAD commit mirrors the product tree plus unrelated files."""
    repo = Path(base) / "candidate-repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for relative in tracked_product_files():
        source = PROJECT / relative
        if "__pycache__" in relative or not source.is_file():
            continue
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for relative, content in {
        ".agent/HANDOFF.md": "agent notes\n", ".orchestrator/BOOTSTRAP.md": "orchestrator\n",
        "docs/NOTES.md": "docs\n", "tests/test_unrelated.py": "# unrelated\n",
        "README.md": "readme\n", "LICENSE.txt": "license\n", "changelog.md": "changes\n",
    }.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "candidate")
    return repo, git(repo, "rev-parse", "HEAD").decode().strip()


def commit_with_edits(repo, parent, edits, message="variant"):
    """Commit via plumbing on a private index; the working tree is untouched.

    edits: list of (mode, path, content-bytes | None); None removes the path.
    """
    index = Path(repo) / ".git" / "bm-test-index"
    env = {"GIT_INDEX_FILE": str(index)}
    git(repo, "read-tree", parent, env=env)
    for mode, path, content in edits:
        if content is None:
            git(repo, "update-index", "--force-remove", path, env=env)
            continue
        oid = git(repo, "hash-object", "-w", "--stdin", stdin=content).decode().strip()
        git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}", env=env)
    tree = git(repo, "write-tree", env=env).decode().strip()
    commit = git(repo, "commit-tree", tree, "-p", parent, "-m", message).decode().strip()
    index.unlink(missing_ok=True)
    return commit


def make_config(base, *, adapter=True, rpc=None, mode=0o600):
    document = {"schema": bm.CONFIG_SCHEMA}
    if adapter:
        document["adapter"] = dict(ADAPTER_VALUES)
    if rpc is not None:
        document["rpc"] = rpc
    path = Path(base) / "bm-config.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(mode)
    return path


def fingerprint(path):
    return bm.fingerprint_tree(Path(path))


FIXTURE = SimpleNamespace(base=None, repo=None, good=None, variants={}, plan=None, counter=0)


def setUpModule():
    FIXTURE.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="bm-test-app-fixture-")))
    FIXTURE.repo, FIXTURE.good = build_candidate_repo(FIXTURE.base)
    FIXTURE.variants = {}
    FIXTURE.plan = None


def tearDownModule():
    shutil.rmtree(FIXTURE.base, ignore_errors=True)


def variant(name, edits):
    """A cached variant of the good candidate commit (built with plumbing)."""
    if name not in FIXTURE.variants:
        FIXTURE.variants[name] = commit_with_edits(FIXTURE.repo, FIXTURE.good, edits, name)
    return FIXTURE.variants[name]


def hostile_commit(names, subtree="resources"):
    """A commit whose `subtree` holds entries with these (possibly hostile) names."""
    blob = git(FIXTURE.repo, "hash-object", "-w", "--stdin", stdin=b"x").decode().strip()
    inner = git(
        FIXTURE.repo, "mktree",
        stdin="".join(f"100644 blob {blob}\t{name}\n" for name in names).encode(),
    ).decode().strip()
    listing = git(FIXTURE.repo, "ls-tree", FIXTURE.good).decode().splitlines()
    kept = [line for line in listing if not line.endswith("\t" + subtree)]
    root = git(
        FIXTURE.repo, "mktree", stdin=("\n".join(kept + [f"040000 tree {inner}\t{subtree}"]) + "\n").encode()
    ).decode().strip()
    return git(FIXTURE.repo, "commit-tree", root, "-p", FIXTURE.good, "-m", "hostile").decode().strip()


def candidate_source(runner=subprocess.run):
    return bm.GitSource(FIXTURE.repo, bm.find_git(), runner)


def new_workspace(testcase):
    FIXTURE.counter += 1
    workspace = testcase.tmp / f"workspace-{FIXTURE.counter}"
    workspace.mkdir(mode=0o700)
    return workspace


def build_plan(testcase, commit, adapter=None, runner=subprocess.run):
    candidate = bm.load_candidate(candidate_source(), commit)
    driver = bm.build_driver(
        candidate, adapter or ADAPTER_VALUES, new_workspace(testcase), sys.executable, runner
    )
    return candidate, driver


def good_plan():
    """(candidate, driver, manifest) of the good commit, built once per run."""
    if FIXTURE.plan is None:
        candidate = bm.load_candidate(candidate_source(), FIXTURE.good)
        workspace = FIXTURE.base / "plan-workspace"
        workspace.mkdir(mode=0o700)
        driver = bm.build_driver(candidate, ADAPTER_VALUES, workspace, sys.executable)
        manifest = bm.build_manifest(
            candidate, driver, bm.config_fingerprint(ADAPTER_VALUES), "2026-10-04T12:00:00Z"
        )
        FIXTURE.plan = (candidate, driver, manifest)
    return FIXTURE.plan


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

class TestOutputHelpers(unittest.TestCase):
    def test_safe_text_passes_plain_ascii_and_hides_hostile_text(self):
        self.assertEqual(bm.safe_text("resources/lib/a.py"), "resources/lib/a.py")
        hostile = "name\nwith\x1b[31mcontrol"
        self.assertTrue(bm.safe_text(hostile).startswith("<unsafe:"))
        self.assertNotIn("control", bm.safe_text(hostile))
        self.assertTrue(bm.safe_text("x" * 500).startswith("<unsafe:"))

    def test_capped_lists_are_sorted_sanitized_and_flagged(self):
        names, truncated = bm.capped([f"n{i:03d}" for i in range(80, 0, -1)], cap=10)
        self.assertEqual(names[0], "n001")
        self.assertEqual(len(names), 10)
        self.assertTrue(truncated)
        self.assertEqual(bm.capped(["b", "a"]), (["a", "b"], False))

    def test_canonical_json_is_deterministic_ascii_and_rejects_nan(self):
        first = bm.canonical_json({"b": 1, "a": [2, {"z": "é"}]})
        self.assertEqual(first, bm.canonical_json({"a": [2, {"z": "é"}], "b": 1}))
        self.assertTrue(first.isascii())
        self.assertTrue(first.endswith("\n"))
        with self.assertRaises(ValueError):
            bm.canonical_json({"x": float("nan")})

    def test_helper_error_detail_is_scalar_and_sanitized(self):
        error = bm.HelperError("rpc_error", code=-32602, note="bad\nline", nested={"a": 1})
        self.assertEqual(error.code, "rpc_error")
        self.assertEqual(error.detail["code"], -32602)
        self.assertTrue(error.detail["note"].startswith("<unsafe:"))
        self.assertEqual(error.detail["nested"], "<unsupported>")

    def test_unknown_error_codes_collapse_to_internal_error(self):
        self.assertEqual(bm.HelperError("not_a_registered_code").code, "internal_error")

    def test_secret_registry_catches_raw_and_json_escaped_forms(self):
        registry = bm.SecretRegistry()
        registry.register('pa"ss\\word', minimum=4)
        registry.register("ab", minimum=4)
        self.assertTrue(registry.leaks('x pa"ss\\word y'))
        self.assertTrue(registry.leaks(bm.canonical_json({"v": 'pa"ss\\word'})))
        self.assertFalse(registry.leaks("ab"))
        self.assertFalse(registry.leaks("clean text"))

    def test_git_object_id_matches_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q")
            data = b"hello\nworld\n"
            expected = git(repo, "hash-object", "--stdin", stdin=data).decode().strip()
            self.assertEqual(bm.git_object_id(b"blob", data, "sha1"), expected)


# ---------------------------------------------------------------------------
# Hard production boundary
# ---------------------------------------------------------------------------

class TestPathBoundary(TripwireTestCase):
    def test_authorized_target_is_exactly_the_test_app_and_does_no_io(self):
        target = bm.TestAppTarget.authorized()
        self.assertEqual(os.fspath(target.root), "/Applications/Kodi Build Manager Test.app")
        self.assertTrue(target.production)
        self.assertEqual(
            os.fspath(target.portable_data),
            "/Applications/Kodi Build Manager Test.app/Contents/Resources/Kodi/portable_data",
        )
        self.assertEqual(
            os.fspath(target.result_path),
            os.fspath(target.portable_data / "userdata/addon_data/script.build.manager/bm023a_live_result.json"),
        )
        self.assertEqual(self.tripwire.touched, [])

    def test_production_target_rejects_every_other_spelling(self):
        for variant in (
            "/Applications/../Applications/Kodi Build Manager Test.app",
            "/applications/kodi build manager test.app",
            "/Applications/Kodi Build Manager Test.app/Contents",
            "Applications/Kodi Build Manager Test.app",
            "/private/Applications/Kodi Build Manager Test.app",
            "/Applications/Kodi Build Manager Test.app.copy",
            "/Applications/Kodi Build Manager Test 2.app",
        ):
            with self.subTest(variant=variant), self.assertRaises(bm.HelperError):
                bm.TestAppTarget(Path(variant), production=True)

    def test_aliases_are_refused_at_cli_and_config_entry_points_before_io(self):
        services = make_services(make_fake_app(self.tmp))
        spellings = ("//Applications/Kodi.app/x", "//Users/eengert/Library/Application Support/Kodi/x",
                     "/.vol/1/2", "/.nofollow/Applications/Kodi.app/x",
                     "/.resolve/Applications/Kodi.app/x",
                     "/System/Volumes/Data/Applications/Kodi.app/x",
                     "/System/Volumes/Data/Users/eengert/Library/Application Support/Kodi/x",
                     "/.vol/../safe", "/.nofollow/../safe", "/.resolve/../safe")
        for raw in spellings:
            with self.subTest(raw=raw):
                with mock.patch.object(bm.os, "lstat", side_effect=AssertionError("premature I/O")):
                    with self.assertRaises(bm.HelperError):
                        bm.check_cli_path(raw, services)
                for key in bm.ADAPTER_PATH_KEYS:
                    values = dict(ADAPTER_VALUES, **{key: raw})
                    cfg = make_config(self.tmp)
                    cfg.write_text(json.dumps({"schema": bm.CONFIG_SCHEMA, "adapter": values}))
                    with self.assertRaises(bm.HelperError):
                        bm.load_config(cfg, services)
        # Same canonical identity for Test.app exclusion and ordinary decoys.
        for prefix in ("/", "//", bm._DATA_VOLUME_ALIAS + "/"):
            raw = prefix + str(services.target.root).lstrip("/") + "/x"
            with mock.patch.object(bm.os, "lstat", side_effect=AssertionError("premature I/O")):
                with self.assertRaises(bm.HelperError) as raised:
                    bm.check_cli_path(raw, services)
                self.assertEqual(raised.exception.code, "argument_path_inside_test_app")
        outside = self.tmp / "outside"
        outside.mkdir()
        self.assertEqual(bm.check_cli_path(bm._DATA_VOLUME_ALIAS + str(outside), services), outside)

    def test_hostile_path_environment_cannot_redirect_git_discovery(self):
        with mock.patch.dict(os.environ, PATH="//Applications/Kodi.app"):
            self.assertEqual(bm.Services.production().git_exe, "/usr/bin/git")

    def test_tripwire_independently_catches_aliases(self):
        guard = FilesystemTripwire()
        for raw in ("//Applications/Kodi.app/x", "/.vol/1/2", "/.nofollow/x", "/.resolve/x",
                    "//System/Volumes/Data/Applications/Kodi.app/x"):
            with self.subTest(raw=raw), self.assertRaises(AssertionError):
                guard._check("probe", raw)  # pure string, never dispatch filesystem I/O

    def test_config_path_symlink_is_refused_before_adapter_handoff(self):
        services = make_services(make_fake_app(self.tmp))
        link = self.tmp / "link"
        link.symlink_to(self.tmp)
        for key in bm.ADAPTER_PATH_KEYS:
            values = dict(ADAPTER_VALUES, **{key: str(link / "input")})
            cfg = make_config(self.tmp)
            cfg.write_text(json.dumps({"schema": bm.CONFIG_SCHEMA, "adapter": values}))
            with self.assertRaises(bm.HelperError) as raised:
                bm.load_config(cfg, services)
            self.assertEqual(raised.exception.code, "argument_path_symlink")

    def test_pathlib_collapses_harmless_slash_spellings_to_the_exact_path(self):
        # These cannot be represented as a different Path, so they are the
        # authorized path itself and remain exactly authorized.
        for spelling in (
            "/Applications/Kodi Build Manager Test.app/",
            "/Applications//Kodi Build Manager Test.app",
        ):
            with self.subTest(spelling=spelling):
                self.assertEqual(Path(spelling), Path(bm.AUTHORIZED_TEST_APP))
                self.assertEqual(
                    os.fspath(bm.TestAppTarget(Path(spelling), production=True).root),
                    bm.AUTHORIZED_TEST_APP,
                )

    def test_normal_kodi_and_normal_profile_can_never_be_a_target(self):
        for forbidden in (
            "/Applications/Kodi.app",
            "/Applications/Kodi.app/Contents/Resources",
            "/Users/eengert/Library/Application Support/Kodi",
            "/Users/eengert/Library/Application Support/Kodi/userdata",
            "/applications/kodi.app",
            "/System/Volumes/Data/Applications/Kodi.app",
            "/System/Volumes/Data/Users/eengert/Library/Application Support/Kodi/addons",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertTrue(bm.is_forbidden_path(forbidden))
                with self.assertRaises(bm.HelperError) as raised:
                    bm.TestAppTarget.for_tests(forbidden)
                self.assertEqual(raised.exception.code, "target_path_forbidden")

    def test_forbidden_path_check_follows_the_current_home(self):
        with mock.patch.dict(os.environ, {"HOME": "/Users/someone-else"}):
            self.assertTrue(bm.is_forbidden_path("/Users/someone-else/Library/Application Support/Kodi/x"))
            self.assertFalse(bm.is_forbidden_path("/Users/someone-else/Library/Application Support/Other"))

    def test_lookalike_paths_are_not_forbidden(self):
        for allowed in (
            "/Applications/Kodi Build Manager Test.app",
            "/Applications/Kodi.app.backup-notes",
            "/Users/eengert/Library/Application Support/KodiOther",
            "/tmp/Kodi.app",
        ):
            with self.subTest(allowed=allowed):
                self.assertFalse(bm.is_forbidden_path(allowed))

    def test_paths_outside_the_target_are_not_authorized(self):
        target = make_fake_app(self.tmp)
        with self.assertRaises(bm.HelperError) as raised:
            target.require_chain(self.tmp / "elsewhere")
        self.assertEqual(raised.exception.code, "target_path_not_authorized")
        target.require_chain(target.addons_dir)

    def test_fake_target_must_be_absolute_and_normalized(self):
        for bad in ("relative/app", "/tmp/a/../b", "/"):
            with self.subTest(bad=bad), self.assertRaises(bm.HelperError):
                bm.TestAppTarget.for_tests(bad)

    def test_cli_has_no_app_override_flag_or_environment_override(self):
        services = make_services(make_fake_app(self.tmp))
        for flag in ("--app", "--target", "--app-path", "--test-app"):
            with self.subTest(flag=flag):
                code, payload, _ = run_cli(services, "identify", flag, "/tmp/other.app")
                self.assertEqual(code, bm.EXIT_USAGE)
                self.assertEqual(payload["error"]["code"], "argument_invalid")
        with mock.patch.dict(os.environ, {
            "BM_TEST_APP": str(self.tmp), "KODI_APP": str(self.tmp), "TEST_APP": str(self.tmp),
        }):
            self.assertEqual(
                os.fspath(bm.Services.production().target.root), bm.AUTHORIZED_TEST_APP
            )

    def test_services_production_wires_only_the_authorized_target(self):
        services = bm.Services.production()
        self.assertTrue(services.target.production)
        self.assertEqual(os.fspath(services.target.root), bm.AUTHORIZED_TEST_APP)
        self.assertEqual(self.tripwire.touched, [])

    def test_check_cli_path_refuses_forbidden_inside_app_and_symlinks(self):
        services = make_services(make_fake_app(self.tmp))
        outside = self.tmp / "outside"
        outside.mkdir()
        self.assertEqual(bm.check_cli_path(outside, services), outside)
        with self.assertRaises(bm.HelperError) as raised:
            bm.check_cli_path("/Applications/Kodi.app/Contents/Info.plist", services)
        self.assertEqual(raised.exception.code, "argument_path_forbidden")
        with self.assertRaises(bm.HelperError) as raised:
            bm.check_cli_path(services.target.addons_dir / "x", services)
        self.assertEqual(raised.exception.code, "argument_path_inside_test_app")
        link = self.tmp / "link"
        link.symlink_to(outside)
        with self.assertRaises(bm.HelperError) as raised:
            bm.check_cli_path(link / "child", services)
        self.assertEqual(raised.exception.code, "argument_path_symlink")
        with self.assertRaises(bm.HelperError):
            bm.check_cli_path("bad\x00path", services)

    def test_dot_dot_traversal_is_normalized_before_the_boundary_checks(self):
        services = make_services(make_fake_app(self.tmp))
        outside = self.tmp / "outside"
        outside.mkdir()
        app = services.target.root
        cases = {
            os.fspath(outside / ".." / ".." / ".." / ".." / ".." / ".." / ".." / ".." / "Applications" / "Kodi.app" / "x"):
                "argument_path_forbidden",
            "/tmp/x/../../Applications/Kodi.app/Contents/Info.plist": "argument_path_forbidden",
            "/Users/eengert/Documents/../Library/Application Support/Kodi/userdata": "argument_path_forbidden",
            os.fspath(outside / ".." / app.name / "Contents" / "evil"): "argument_path_inside_test_app",
            os.fspath(outside / ".." / ".." / outside.parent.name / app.name): "argument_path_inside_test_app",
        }
        for raw, code in cases.items():
            with self.subTest(path=raw[-60:]), self.assertRaises(bm.HelperError) as raised:
                bm.check_cli_path(raw, services)
            self.assertEqual(raised.exception.code, code)
        self.assertEqual(bm.check_cli_path(outside / ".." / "outside" / "ok", services), outside / "ok")
        self.assertEqual(self.tripwire.touched, [])

    def test_check_cli_path_never_touches_a_forbidden_target(self):
        services = make_services(make_fake_app(self.tmp))
        # Refused lexically, before any lstat could reach the forbidden tree.
        with self.assertRaises(bm.HelperError):
            bm.check_cli_path("/Users/eengert/Library/Application Support/Kodi/userdata/x", services)
        self.assertEqual(self.tripwire.touched, [])


# ---------------------------------------------------------------------------
# Filesystem primitives
# ---------------------------------------------------------------------------

class TestFilesystemPrimitives(TripwireTestCase):
    def test_read_regular_file_returns_bounded_bytes_and_identity(self):
        path = self.tmp / "f.bin"
        path.write_bytes(b"abc")
        result = bm.read_regular_file(path, 10)
        self.assertEqual(result.data, b"abc")
        self.assertEqual(result.st_size, 3)
        with self.assertRaises(bm.FsProblem) as raised:
            bm.read_regular_file(path, 2)
        self.assertEqual(raised.exception.kind, "too_large")

    def test_read_regular_file_refuses_symlinks_fifos_directories_and_absent(self):
        target = self.tmp / "real.txt"
        target.write_text("x")
        link = self.tmp / "link.txt"
        link.symlink_to(target)
        fifo = self.tmp / "fifo"
        os.mkfifo(fifo)
        directory = self.tmp / "dir"
        directory.mkdir()
        for path, kind in ((link, "not_regular"), (fifo, "not_regular"), (directory, "not_regular"),
                           (self.tmp / "missing", "absent"), (self.tmp / "real.txt" / "child", "absent")):
            with self.subTest(path=path.name), self.assertRaises(bm.FsProblem) as raised:
                bm.read_regular_file(path, 100)
            self.assertEqual(raised.exception.kind, kind)

    def test_fifo_without_writer_does_not_block(self):
        fifo = self.tmp / "blocking-fifo"
        os.mkfifo(fifo)
        started = threading.Event()
        outcome = []

        def attempt():
            started.set()
            try:
                bm.read_regular_file(fifo, 10)
            except bm.FsProblem as exc:
                outcome.append(exc.kind)

        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), "read blocked on a FIFO")
        self.assertEqual(outcome, ["not_regular"])

    def test_file_replaced_during_read_is_detected(self):
        path = self.tmp / "race.txt"
        path.write_text("original")
        real_fstat = os.fstat

        def swap_then_fstat(fd):
            os.replace(self._make_other(), path)
            return real_fstat(fd)

        with mock.patch.object(bm.os, "fstat", swap_then_fstat):
            with self.assertRaises(bm.FsProblem) as raised:
                bm.read_regular_file(path, 100)
        self.assertEqual(raised.exception.kind, "changed")

    def _make_other(self):
        other = self.tmp / "other.txt"
        other.write_text("replacement")
        return other

    def test_walk_tree_does_not_follow_symlinks_and_is_sorted(self):
        (self.tmp / "tree" / "sub").mkdir(parents=True)
        (self.tmp / "tree" / "b.txt").write_text("b")
        (self.tmp / "tree" / "sub" / "a.txt").write_text("a")
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        (self.tmp / "tree" / "escape").symlink_to(outside)
        os.mkfifo(self.tmp / "tree" / "pipe")
        entries = bm.walk_tree(self.tmp / "tree")
        self.assertEqual(
            [(e.rel, e.kind) for e in entries],
            [("b.txt", "file"), ("escape", "symlink"), ("pipe", "other"),
             ("sub", "dir"), ("sub/a.txt", "file")],
        )

    def test_walk_tree_is_bounded(self):
        (self.tmp / "many").mkdir()
        for index in range(12):
            (self.tmp / "many" / f"f{index}").write_text("x")
        with self.assertRaises(bm.FsProblem) as raised:
            bm.walk_tree(self.tmp / "many", max_entries=5)
        self.assertEqual(raised.exception.kind, "too_many_entries")
        deep = self.tmp / "deep"
        current = deep
        for index in range(6):
            current = current / f"d{index}"
        current.mkdir(parents=True)
        with self.assertRaises(bm.FsProblem) as raised:
            bm.walk_tree(deep, max_depth=3)
        self.assertEqual(raised.exception.kind, "too_deep")

    def test_reject_symlink_components_checks_every_ancestor_without_following(self):
        real = self.tmp / "real"
        real.mkdir()
        bm.reject_symlink_components(real / "not-yet-created" / "deeper")
        (self.tmp / "alias").symlink_to(real)
        with self.assertRaises(bm.FsProblem) as raised:
            bm.reject_symlink_components(self.tmp / "alias" / "child")
        self.assertEqual(raised.exception.kind, "symlink")

    def test_write_new_file_never_overwrites_or_follows(self):
        path = self.tmp / "new.txt"
        bm.write_new_file(path, b"one", 0o640)
        self.assertEqual(path.read_bytes(), b"one")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        with self.assertRaises(FileExistsError):
            bm.write_new_file(path, b"two")
        victim = self.tmp / "victim.txt"
        victim.write_text("keep")
        (self.tmp / "dangling").symlink_to(victim)
        with self.assertRaises(OSError):
            bm.write_new_file(self.tmp / "dangling", b"overwrite")
        self.assertEqual(victim.read_text(), "keep")

    def test_write_new_file_atomic_publishes_once_and_cleans_up(self):
        path = self.tmp / "evidence.json"
        bm.write_new_file_atomic(path, b"{}\n")
        self.assertEqual(path.read_bytes(), b"{}\n")
        with self.assertRaises(bm.HelperError) as raised:
            bm.write_new_file_atomic(path, b"changed")
        self.assertEqual(raised.exception.code, "output_exists")
        self.assertEqual(path.read_bytes(), b"{}\n")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["evidence.json"])

    def test_tree_digest_is_order_independent_and_content_sensitive(self):
        rows = [("b", "1" * 64, 2), ("a", "2" * 64, 3)]
        self.assertEqual(bm.tree_digest(rows), bm.tree_digest(reversed(rows)))
        self.assertNotEqual(bm.tree_digest(rows), bm.tree_digest([("b", "1" * 64, 2), ("a", "2" * 64, 4)]))


# ---------------------------------------------------------------------------
# Bundle identity (Info.plist)
# ---------------------------------------------------------------------------

class TestBundleIdentity(TripwireTestCase):
    def test_valid_bundle_reports_sanitized_identity(self):
        target = make_fake_app(self.tmp)
        info = bm.inspect_bundle(target)
        self.assertEqual(info.identifier, "org.xbmc.kodi")
        self.assertEqual(info.executable, "Kodi")
        self.assertEqual(info.package_type, "APPL")
        self.assertEqual(info.short_version, "21.3")
        self.assertEqual(
            info.info_plist_sha256, hashlib.sha256(target.info_plist.read_bytes()).hexdigest()
        )
        self.assertTrue(info.portable_data_present and info.addons_dir_present and info.userdata_dir_present)

    def test_missing_portable_data_is_reported_never_created(self):
        target = make_fake_app(self.tmp, portable=False)
        info = bm.inspect_bundle(target)
        self.assertFalse(info.portable_data_present or info.addons_dir_present or info.userdata_dir_present)
        self.assertFalse(target.portable_data.exists())

    def test_partial_layout_is_reported_precisely(self):
        info = bm.inspect_bundle(make_fake_app(self.tmp, userdata=False))
        self.assertTrue(info.portable_data_present and info.addons_dir_present)
        self.assertFalse(info.userdata_dir_present)

    def test_missing_bundle_and_missing_contents_fail_closed(self):
        with self.assertRaises(bm.HelperError) as raised:
            bm.inspect_bundle(bm.TestAppTarget.for_tests(self.tmp / "Kodi Build Manager Test.app"))
        self.assertEqual(raised.exception.code, "bundle_missing")
        (self.tmp / "Empty.app").mkdir()
        with self.assertRaises(bm.HelperError) as raised:
            bm.inspect_bundle(bm.TestAppTarget.for_tests(self.tmp / "Empty.app"))
        self.assertEqual(raised.exception.code, "bundle_missing")

    def test_info_plist_problems_fail_closed(self):
        for label, content in (
            ("not a plist", b"not a plist at all"),
            ("a list root", plistlib.dumps(["x"])),
            ("no executable", plistlib.dumps({"CFBundleIdentifier": "a.b", "CFBundlePackageType": "APPL"})),
            ("no identifier", plistlib.dumps({"CFBundleExecutable": "Kodi", "CFBundlePackageType": "APPL"})),
            ("wrong package type", plistlib.dumps({"CFBundleIdentifier": "a.b", "CFBundleExecutable": "Kodi", "CFBundlePackageType": "FMWK"})),
            ("hostile identifier", plistlib.dumps({"CFBundleIdentifier": "a b\n", "CFBundleExecutable": "Kodi", "CFBundlePackageType": "APPL"})),
            ("non-string executable", plistlib.dumps({"CFBundleIdentifier": "a.b", "CFBundleExecutable": 5, "CFBundlePackageType": "APPL"})),
        ):
            with self.subTest(label=label):
                target = make_fake_app(self._fresh(label))
                target.info_plist.write_bytes(content)
                with self.assertRaises(bm.HelperError) as raised:
                    bm.inspect_bundle(target)
                self.assertEqual(raised.exception.code, "info_plist_invalid")

    def _fresh(self, label):
        base = self.tmp / ("case-" + label.replace(" ", "-"))
        base.mkdir()
        return base

    def test_executable_name_must_be_a_plain_name_and_a_real_executable_file(self):
        for label, name in (("slash", "../Kodi"), ("dot", ".."), ("nested", "a/b")):
            with self.subTest(label=label):
                target = make_fake_app(self._fresh("name-" + label))
                target.info_plist.write_bytes(plistlib.dumps({
                    "CFBundleIdentifier": "a.b", "CFBundleExecutable": name, "CFBundlePackageType": "APPL",
                }))
                with self.assertRaises(bm.HelperError) as raised:
                    bm.inspect_bundle(target)
                self.assertIn(raised.exception.code, ("info_plist_invalid", "bundle_executable_invalid"))
        target = make_fake_app(self._fresh("noexec"))
        (target.macos_dir / "Kodi").chmod(0o644)
        with self.assertRaises(bm.HelperError) as raised:
            bm.inspect_bundle(target)
        self.assertEqual(raised.exception.code, "bundle_executable_invalid")
        target = make_fake_app(self._fresh("linkexec"))
        (target.macos_dir / "Kodi").unlink()
        real = self.tmp / "real-binary"
        real.write_bytes(b"x")
        real.chmod(0o755)
        (target.macos_dir / "Kodi").symlink_to(real)
        with self.assertRaises(bm.HelperError) as raised:
            bm.inspect_bundle(target)
        self.assertEqual(raised.exception.code, "bundle_executable_invalid")
        target = make_fake_app(self._fresh("missingexec"))
        (target.macos_dir / "Kodi").unlink()
        with self.assertRaises(bm.HelperError) as raised:
            bm.inspect_bundle(target)
        self.assertEqual(raised.exception.code, "bundle_executable_invalid")

    def test_symlinked_info_plist_is_refused(self):
        target = make_fake_app(self.tmp)
        real = self.tmp / "other.plist"
        real.write_bytes(target.info_plist.read_bytes())
        target.info_plist.unlink()
        target.info_plist.symlink_to(real)
        with self.assertRaises(bm.HelperError) as raised:
            bm.inspect_bundle(target)
        self.assertEqual(raised.exception.code, "info_plist_invalid")

    def test_symlinked_bundle_root_is_refused(self):
        real_base = self.tmp / "real"
        real_base.mkdir()
        make_fake_app(real_base, name="Actual.app")
        alias = self.tmp / "Kodi Build Manager Test.app"
        alias.symlink_to(real_base / "Actual.app")
        with self.assertRaises(bm.HelperError) as raised:
            bm.inspect_bundle(bm.TestAppTarget.for_tests(alias))
        self.assertEqual(raised.exception.code, "bundle_path_symlink")

    def test_symlinked_ancestor_of_the_bundle_is_refused(self):
        real_base = self.tmp / "real"
        real_base.mkdir()
        make_fake_app(real_base)
        alias = self.tmp / "alias"
        alias.symlink_to(real_base)
        with self.assertRaises(bm.HelperError) as raised:
            bm.inspect_bundle(bm.TestAppTarget.for_tests(alias / "Kodi Build Manager Test.app"))
        self.assertEqual(raised.exception.code, "bundle_path_symlink")

    def test_symlinked_layout_directories_are_refused(self):
        for label in ("portable_data", "addons", "userdata"):
            with self.subTest(label=label):
                target = make_fake_app(self._fresh("layout-" + label))
                elsewhere = self.tmp / ("elsewhere-" + label)
                elsewhere.mkdir()
                victim = {"portable_data": target.portable_data, "addons": target.addons_dir,
                          "userdata": target.userdata_dir}[label]
                if label == "portable_data":
                    shutil.rmtree(victim)
                else:
                    victim.rmdir()
                victim.symlink_to(elsewhere)
                with self.assertRaises(bm.HelperError) as raised:
                    bm.inspect_bundle(target)
                self.assertEqual(raised.exception.code, "bundle_path_symlink")


# ---------------------------------------------------------------------------
# Process identity
# ---------------------------------------------------------------------------

class TestProcessIdentity(TripwireTestCase):
    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)
        self.lister = FakeProcessLister([
            bm.ProcessInfo(1, "/sbin/launchd"),
            bm.ProcessInfo(2, "/usr/bin/python3"),
        ])
        self.services = make_services(self.target, process_lister=self.lister)

    def test_not_running(self):
        identity = bm.identify(self.services)
        self.assertEqual(identity.state, "not_running")
        self.assertIsNone(identity.pid)
        self.assertEqual(identity.test_app_process_count, 0)
        self.assertEqual(self.lister.command_calls, [])  # no command lines for unrelated pids

    def test_exactly_one_portable_process(self):
        self.lister.run_test_app(self.target, pid=4242)
        identity = bm.identify(self.services)
        self.assertEqual((identity.state, identity.pid), ("running_portable", 4242))
        self.assertEqual(self.lister.command_calls, [4242])
        report = identity.report()
        self.assertEqual(report["process"], {
            "pid": 4242, "portable_flag": True, "state": "running_portable", "test_app_process_count": 1,
        })

    def test_extra_arguments_are_fine_as_long_as_p_is_a_standalone_token(self):
        self.lister.run_test_app(self.target, flags=" --debug -p -fs")
        self.assertEqual(bm.identify(self.services).state, "running_portable")

    def test_process_without_p_flag_is_refused(self):
        for flags in ("", " --portable", " -pp", " --standalone", " -fs --debug"):
            with self.subTest(flags=flags):
                lister = FakeProcessLister()
                lister.run_test_app(self.target, flags=flags)
                with self.assertRaises(bm.HelperError) as raised:
                    bm.identify(make_services(self.target, process_lister=lister))
                self.assertEqual(raised.exception.code, "test_app_not_portable")

    def test_p_inside_another_token_does_not_count(self):
        lister = FakeProcessLister()
        lister.run_test_app(self.target, flags=" --data=-p --path=/x-p")
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(make_services(self.target, process_lister=lister))
        self.assertEqual(raised.exception.code, "test_app_not_portable")

    def test_multiple_test_app_processes_are_refused(self):
        self.lister.run_test_app(self.target, pid=10)
        self.lister.run_test_app(self.target, pid=11)
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services)
        self.assertEqual(raised.exception.code, "multiple_test_app_processes")
        self.assertEqual(raised.exception.detail["process_count"], 2)

    def test_normal_kodi_is_a_foreign_process_and_is_never_touched(self):
        self.lister.processes.append(bm.ProcessInfo(777, "/Applications/Kodi.app/Contents/MacOS/Kodi"))
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services)
        self.assertEqual(raised.exception.code, "foreign_kodi_process_present")
        self.assertEqual(raised.exception.detail["foreign_kodi_process_count"], 1)
        self.assertEqual(self.lister.command_calls, [])  # not even its command line is read
        self.assertEqual(self.tripwire.touched, [])

    def test_foreign_process_wins_even_next_to_a_valid_test_app(self):
        self.lister.run_test_app(self.target, pid=4242)
        self.lister.processes.append(bm.ProcessInfo(778, "/Applications/Kodi.app/Contents/MacOS/Kodi"))
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services)
        self.assertEqual(raised.exception.code, "foreign_kodi_process_present")

    def test_process_inside_the_bundle_but_not_the_main_executable_is_refused(self):
        self.lister.processes.append(
            bm.ProcessInfo(5, os.fspath(self.target.root / "Contents" / "MacOS" / "Helper"))
        )
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services)
        self.assertEqual(raised.exception.code, "test_app_process_mismatch")

    def test_other_bundle_with_the_same_executable_name_is_foreign(self):
        for exe in (
            "/private/var/folders/xx/AppTranslocation/yy/d/Kodi Build Manager Test.app/Contents/MacOS/Kodi",
            os.fspath(self.tmp / "Kodi Build Manager Test.app.bak" / "Contents" / "MacOS" / "Kodi"),
            "/applications/kodi build manager test.app/contents/macos/kodi",
        ):
            with self.subTest(exe=exe):
                lister = FakeProcessLister([bm.ProcessInfo(9, exe)])
                with self.assertRaises(bm.HelperError) as raised:
                    bm.identify(make_services(self.target, process_lister=lister))
                self.assertEqual(raised.exception.code, "foreign_kodi_process_present")

    def test_command_line_must_match_the_listed_executable(self):
        pid = self.lister.run_test_app(self.target)
        exe = self.lister.processes[-1].exe
        for label, command in (
            ("missing", None),
            ("different argv0", "/somewhere/else/Kodi -p"),
            ("prefix only", exe + "x -p"),
            ("relative argv0", "Kodi -p"),
        ):
            with self.subTest(label=label):
                self.lister.commands[pid] = command
                with self.assertRaises(bm.HelperError) as raised:
                    bm.identify(self.services)
                self.assertEqual(raised.exception.code, "test_app_process_ambiguous")

    def test_data_volume_alias_of_the_main_executable_is_recognized(self):
        exe = bm._DATA_VOLUME_ALIAS + os.fspath(self.target.macos_dir / "Kodi")
        lister = FakeProcessLister([bm.ProcessInfo(33, exe)], {33: exe + " -p"})
        identity = bm.identify(make_services(self.target, process_lister=lister))
        self.assertEqual(identity.pid, 33)

    def test_command_line_may_use_either_known_spelling_of_the_executable(self):
        exe = os.fspath(self.target.macos_dir / "Kodi")
        alias = bm._DATA_VOLUME_ALIAS + exe
        for listed, command in ((exe, alias + " -p"), (alias, exe + " -p"), (alias, alias + " -p")):
            with self.subTest(listed=listed[:30], command=command[:30]):
                lister = FakeProcessLister([bm.ProcessInfo(44, listed)], {44: command})
                self.assertEqual(bm.identify(make_services(self.target, process_lister=lister)).pid, 44)
        lister = FakeProcessLister([bm.ProcessInfo(44, exe)], {44: alias + " --portable"})
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(make_services(self.target, process_lister=lister))
        self.assertEqual(raised.exception.code, "test_app_not_portable")

    def test_listing_failures_fail_closed(self):
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(make_services(self.target, process_lister=FakeProcessLister(fail=True)))
        self.assertEqual(raised.exception.code, "process_listing_failed")

        class Exploding(FakeProcessLister):
            def list_all(self):
                raise RuntimeError("boom with /secret/path")

        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(make_services(self.target, process_lister=Exploding()))
        self.assertEqual(raised.exception.code, "process_listing_failed")
        self.assertNotIn("secret", json.dumps(raised.exception.detail))

    def test_require_modes(self):
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services, require="running")
        self.assertEqual(raised.exception.code, "test_app_not_running")
        self.assertEqual(bm.identify(self.services, require="not_running").state, "not_running")
        self.lister.run_test_app(self.target, pid=55)
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services, require="not_running")
        self.assertEqual(raised.exception.code, "test_app_running")
        self.assertEqual(bm.identify(self.services, require="running").pid, 55)

    def test_kodi_like_heuristic_is_string_only(self):
        positives = (
            "/Applications/Kodi.app/Contents/MacOS/Kodi",
            "/Users/x/Applications/Kodi 21.app/Contents/MacOS/Kodi",
            "/opt/kodi/bin/kodi.bin",
            "/Applications/XBMC.app/Contents/MacOS/XBMC",
            "/Applications/kodi.app/contents/macos/anything",
        )
        negatives = (
            "/usr/bin/python3",
            "/bin/zsh",
            "/Users/eengert/Documents/Kodi/tools/run",
            "/Applications/Claude.app/Contents/MacOS/Claude",
            "/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude/runner",
            "",
        )
        for exe in positives:
            with self.subTest(positive=exe):
                self.assertTrue(bm._kodi_like(exe))
        for exe in negatives:
            with self.subTest(negative=exe):
                self.assertFalse(bm._kodi_like(exe))
        self.assertEqual(self.tripwire.touched, [])


# ---------------------------------------------------------------------------
# ps / lsof parsing and the real-process integration
# ---------------------------------------------------------------------------

def fake_runner(outputs):
    """subprocess.run stand-in: outputs maps a command prefix to (code, stdout)."""
    calls = []

    def run(command, **kwargs):
        calls.append((list(command), kwargs))
        for prefix, (code, stdout) in outputs.items():
            if list(command)[:len(prefix)] == list(prefix):
                return SimpleNamespace(returncode=code, stdout=stdout, stderr=b"")
        raise AssertionError(f"unexpected command {command}")

    run.calls = calls
    return run


class TestPsAndLsofParsing(TripwireTestCase):
    def test_parse_ps_listing_keeps_paths_with_spaces(self):
        text = (
            "    1 /sbin/launchd\n"
            "  523 /Applications/Kodi Build Manager Test.app/Contents/MacOS/Kodi\n"
            "99999 /usr/libexec/with  two  spaces\n"
            "not a process line\n"
            "\n"
        )
        parsed = bm.parse_ps_listing(text)
        self.assertEqual(
            [(p.pid, p.exe) for p in parsed],
            [(1, "/sbin/launchd"),
             (523, "/Applications/Kodi Build Manager Test.app/Contents/MacOS/Kodi"),
             (99999, "/usr/libexec/with  two  spaces")],
        )

    def test_ps_lister_commands_are_fixed_argv_without_a_shell(self):
        runner = fake_runner({
            ("/bin/ps", "-axww"): (0, b"  7 /bin/x y\n"),
            ("/bin/ps", "-ww"): (0, b"/bin/x y -p\n"),
        })
        lister = bm.PsProcessLister(runner, native=SimpleNamespace(executable=lambda pid: "/bin/x y", argv=lambda pid: ("/bin/x y", "-p")))
        self.assertEqual(lister.list_all(), [bm.ProcessInfo(7, "/bin/x y")])
        self.assertEqual(lister.command_line(7), ("/bin/x y", "-p"))
        (listing,) = runner.calls
        self.assertEqual(listing[0], ["/bin/ps", "-axww", "-o", "pid=,comm="])
        for _, kwargs in runner.calls:
            self.assertIs(kwargs["shell"], False)
            self.assertEqual(set(kwargs["env"]), {"PATH", "LC_ALL"})

    def test_ps_failures_fail_closed(self):
        lister = bm.PsProcessLister(fake_runner({("/bin/ps",): (1, b"")}), native=SimpleNamespace(executable=lambda pid: None, argv=lambda pid: None))
        with self.assertRaises(bm.HelperError) as raised:
            lister.list_all()
        self.assertEqual(raised.exception.code, "process_listing_failed")
        self.assertIsNone(lister.command_line(1))

        def raising(*args, **kwargs):
            raise OSError("no ps")

        with self.assertRaises(bm.HelperError):
            bm.PsProcessLister(raising).list_all()

    def test_kernel_argv_agreement_preserves_data_volume_aliases(self):
        for kernel, argv0 in (("/fake/Kodi", bm._DATA_VOLUME_ALIAS + "/fake/Kodi"),
                              (bm._DATA_VOLUME_ALIAS + "/fake/Kodi", "/fake/Kodi")):
            native = SimpleNamespace(executable=lambda pid: kernel,
                                     argv=lambda pid: (argv0, "-p"))
            self.assertEqual(bm.PsProcessLister(native=native).command_line(7), (argv0, "-p"))

    def test_native_argv_parser_preserves_boundaries_and_ignores_environment(self):
        argv = ("/fake/Kodi", "-p", "--note=hello -p world", "")
        raw = len(argv).to_bytes(4, sys.byteorder, signed=True)
        raw += b"/fake/Kodi\0\0\0" + b"\0".join(a.encode() for a in argv) + b"\0"
        raw += b"PRIVATE_VALUE=do-not-parse\0"
        self.assertEqual(bm.MacProcessReader.parse_argv(raw), argv)
        for malformed in (b"", b"\0" * 4, raw[:12], raw[:40]):
            self.assertIsNone(bm.MacProcessReader.parse_argv(malformed))

    def test_process_listing_uses_kernel_path_and_refuses_unreadable_identity(self):
        runner = fake_runner({("/bin/ps",): (0, b"7 /spoofed/argv0\n")})
        native = SimpleNamespace(executable=lambda pid: "/real/executable")
        self.assertEqual(bm.PsProcessLister(runner, native=native).list_all(),
                         [bm.ProcessInfo(7, "/real/executable")])
        native.executable = lambda pid: None
        with self.assertRaises(bm.HelperError) as raised:
            bm.PsProcessLister(runner, native=native).list_all()
        self.assertEqual(raised.exception.code, "process_listing_failed")

    def test_lsof_parser(self):
        run = fake_runner({("/usr/sbin/lsof",): (0, b"p100\nf3\np200\n")})
        self.assertEqual(bm.lsof_listener_pids(8080, run), {100, 200})
        self.assertEqual(run.calls[0][0], ["/usr/sbin/lsof", "-nP", "-iTCP:8080", "-sTCP:LISTEN", "-Fp"])
        self.assertEqual(bm.lsof_listener_pids(1, fake_runner({("/usr/sbin/lsof",): (1, b"")})), set())

    def test_lsof_errors_fail_closed(self):
        for code, out in ((2, b""), (1, b"p5\n"), (127, b"")):
            with self.subTest(code=code), self.assertRaises(bm.HelperError) as raised:
                bm.lsof_listener_pids(1, fake_runner({("/usr/sbin/lsof",): (code, out)}))
            self.assertEqual(raised.exception.code, "listener_lookup_failed")

        def raising(*args, **kwargs):
            raise subprocess.TimeoutExpired("lsof", 1)

        with self.assertRaises(bm.HelperError):
            bm.lsof_listener_pids(1, raising)


class FakeLibProc:
    """libSystem stand-in reproducing proc_pidpath's return value and errno.

    outcomes maps pid -> (result, errno or None, path bytes). None leaves errno
    untouched; the real call also leaves it alone on success.
    """

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def proc_pidpath(self, pid, buffer, size):
        self.calls.append(pid)
        result, err, path = self.outcomes[pid]
        if path:
            ctypes.memmove(buffer, path + b"\0", len(path) + 1)
        if err is not None:
            ctypes.set_errno(err)
        return result


def ok_path(path):
    return (len(path), None, path.encode())


def failed(err, result=0):
    return (result, err, b"")


def mac_reader(outcomes):
    """The real MacProcessReader logic over a fake libSystem."""
    reader = bm.MacProcessReader.__new__(bm.MacProcessReader)
    reader.lib = FakeLibProc(outcomes)
    return reader


class TestProcessCensusRace(TripwireTestCase):
    """Only a pid the kernel proved gone (ESRCH) may leave the ps census."""

    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)

    def lister(self, native, *pids):
        listing = "".join(f"{pid} /stale/ps/comm/{pid}\n" for pid in pids)
        return bm.PsProcessLister(fake_runner({("/bin/ps",): (0, listing.encode())}), native=native)

    def test_esrch_pid_is_omitted_and_the_census_succeeds(self):
        native = mac_reader({
            7: ok_path("/sbin/launchd"),
            8: failed(errno.ESRCH),
            9: ok_path("/usr/bin/python3"),
        })
        lister = self.lister(native, 7, 8, 9)
        self.assertEqual(lister.list_all(),
                         [bm.ProcessInfo(7, "/sbin/launchd"), bm.ProcessInfo(9, "/usr/bin/python3")])
        self.assertEqual(native.lib.calls, [7, 8, 9])
        services = make_services(self.target, process_lister=lister)
        self.assertEqual(bm.identify(services).state, "not_running")

    def test_every_pid_vanishing_is_an_empty_census_not_an_error(self):
        lister = self.lister(mac_reader({4: failed(errno.ESRCH), 5: failed(errno.ESRCH)}), 4, 5)
        self.assertEqual(lister.list_all(), [])

    def test_any_other_native_failure_still_fails_closed(self):
        cases = (
            ("EPERM", failed(errno.EPERM)),
            ("EACCES", failed(errno.EACCES)),
            ("EIO", failed(errno.EIO)),
            ("EINVAL", failed(errno.EINVAL)),
            ("ENOENT", failed(errno.ENOENT)),
            ("errno zero", failed(0)),
            ("negative result with ESRCH", failed(errno.ESRCH, result=-1)),
            ("oversized result with ESRCH", failed(errno.ESRCH, result=4096)),
        )
        for label, outcome in cases:
            with self.subTest(label=label):
                lister = self.lister(mac_reader({7: ok_path("/sbin/launchd"), 8: outcome}), 7, 8)
                with self.assertRaises(bm.HelperError) as raised:
                    lister.list_all()
                self.assertEqual(raised.exception.code, "process_listing_failed")
                with self.assertRaises(bm.HelperError) as raised:
                    bm.identify(make_services(self.target, process_lister=lister))
                self.assertEqual(raised.exception.code, "process_listing_failed")

    def test_stale_errno_is_never_mistaken_for_esrch(self):
        # The fake fails without touching errno, as a failure with no errno of
        # its own would: a leftover ESRCH must not make the pid look vanished.
        lister = self.lister(mac_reader({8: failed(None)}), 8)
        ctypes.set_errno(errno.ESRCH)
        self.assertIsNone(lister.native.executable(8))
        ctypes.set_errno(errno.ESRCH)
        with self.assertRaises(bm.HelperError) as raised:
            lister.list_all()
        self.assertEqual(raised.exception.code, "process_listing_failed")

    def test_a_vanished_pid_cannot_excuse_an_unreadable_one(self):
        lister = self.lister(mac_reader({8: failed(errno.ESRCH), 9: failed(errno.EPERM)}), 8, 9)
        with self.assertRaises(bm.HelperError) as raised:
            lister.list_all()
        self.assertEqual(raised.exception.code, "process_listing_failed")

    def test_native_reader_reports_each_outcome_distinctly(self):
        native = mac_reader({
            1: ok_path("/real/exe"), 2: failed(errno.ESRCH), 3: failed(errno.EPERM), 4: failed(0),
        })
        self.assertEqual(native.executable(1), "/real/exe")
        with self.assertRaises(bm.ProcessVanished):
            native.executable(2)
        self.assertIsNone(native.executable(3))
        self.assertIsNone(native.executable(4))

    def native_by_pid(self, paths):
        """Per-pid executable fake; a value of None means the pid vanished."""
        def executable(pid):
            if paths[pid] is None:
                raise bm.ProcessVanished()
            return paths[pid]
        return SimpleNamespace(executable=executable, argv=lambda pid: (paths[pid], "-p"))

    def test_classification_is_unchanged_next_to_a_vanished_pid(self):
        exe = os.fspath(self.target.macos_dir / "Kodi")
        scenarios = (
            ("test app", {1: "/sbin/launchd", 8: None, 4242: exe}, None),
            ("foreign kodi", {1: "/sbin/launchd", 8: None, 777: "/Applications/Kodi.app/Contents/MacOS/Kodi"},
             "foreign_kodi_process_present"),
            ("inside bundle", {8: None, 5: os.fspath(self.target.root / "Contents" / "MacOS" / "Helper")},
             "test_app_process_mismatch"),
            ("two test apps", {8: None, 10: exe, 11: exe}, "multiple_test_app_processes"),
        )
        for label, paths, expected_error in scenarios:
            with self.subTest(label=label):
                lister = self.lister(self.native_by_pid(paths), *paths)
                services = make_services(self.target, process_lister=lister)
                if expected_error:
                    with self.assertRaises(bm.HelperError) as raised:
                        bm.identify(services)
                    self.assertEqual(raised.exception.code, expected_error)
                else:
                    identity = bm.identify(services)
                    self.assertEqual((identity.state, identity.pid, identity.test_app_process_count),
                                     ("running_portable", 4242, 1))

    def test_target_vanishing_after_the_census_is_ambiguous_not_trusted(self):
        exe = os.fspath(self.target.macos_dir / "Kodi")
        lookups = []

        def executable(pid):
            lookups.append(pid)
            if len(lookups) > 1:
                raise bm.ProcessVanished()
            return exe

        native = SimpleNamespace(executable=executable, argv=lambda pid: (exe, "-p"))
        lister = self.lister(native, 4242)
        self.assertIsNone(lister.command_line(4242))
        lookups.clear()
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(make_services(self.target, process_lister=lister))
        self.assertEqual(raised.exception.code, "test_app_process_ambiguous")


@unittest.skipUnless(sys.platform == "darwin", "proc_pidpath is macOS only")
class TestRealVanishedProcess(TripwireTestCase):
    """A real disposable process that has exited; no Kodi process is involved."""

    def test_real_exited_pid_is_recognized_as_vanished(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child.wait()  # reaped: the pid is gone, no zombie is left behind
        reader = bm.MacProcessReader()
        with self.assertRaises(bm.ProcessVanished):
            reader.executable(child.pid)
        lister = bm.PsProcessLister(native=reader)
        stale = [bm.ProcessInfo(child.pid, "stale"), bm.ProcessInfo(os.getpid(), "stale")]
        census = lister.kernel_processes(stale)
        self.assertEqual([process.pid for process in census], [os.getpid()])
        self.assertTrue(census[0].exe.startswith("/"))
        self.assertIsNone(lister.command_line(child.pid))


@unittest.skipUnless(os.path.exists("/bin/ps") and os.path.exists("/usr/sbin/lsof"), "needs ps and lsof")
class TestRealPsAndLsof(TripwireTestCase):
    """Real ps/lsof, scoped to this test's own processes and sockets."""

    def test_real_ps_output_for_this_process_parses(self):
        lister = bm.PsProcessLister()
        code, text = lister._ps(["-ww", "-p", str(os.getpid()), "-o", "pid=,comm="])
        self.assertEqual(code, 0)
        parsed = bm.parse_ps_listing(text)
        self.assertEqual([p.pid for p in parsed], [os.getpid()])
        self.assertTrue(parsed[0].exe.startswith("/"))
        command = lister.native.argv(os.getpid())
        self.assertIsInstance(command, tuple)
        self.assertTrue(command[0].startswith("/"))
        executable = lister.native.executable(os.getpid())
        self.assertTrue(executable.startswith("/"))
        # Python framework launchers may supply a different argv[0]. The
        # target identity reader must refuse that disagreement, not rewrite it.
        expected = command if command[0] == executable else None
        self.assertEqual(lister.command_line(os.getpid()), expected)
        self.assertIsNone(lister.command_line(2 ** 22 + os.getpid()))

    def test_real_lsof_finds_this_process_as_the_listener(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            self.assertEqual(bm.lsof_listener_pids(port), {os.getpid()})
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        self.assertEqual(bm.lsof_listener_pids(free), set())


FAKE_KODI_SOURCE = "#include <unistd.h>\nint main(int c, char **v) { sleep(120); return 0; }\n"


@unittest.skipUnless(shutil.which("cc") and os.path.exists("/bin/ps"), "needs a C compiler and ps")
class TestRealProcessIdentity(TripwireTestCase):
    """A real process in a real spaced bundle path, seen through the real ps."""

    class PidScopedLister(bm.PsProcessLister):
        """Real ps, restricted to named pids so no other process is ever read."""

        def __init__(self, pids):
            super().__init__()
            self.pids = pids

        def list_all(self):
            if not self.pids:
                return []
            code, text = self._ps(["-ww", "-p", ",".join(str(p) for p in self.pids), "-o", "pid=,comm="])
            return self.kernel_processes(bm.parse_ps_listing(text)) if code == 0 else []

    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)
        source = self.tmp / "fake_kodi.c"
        source.write_text(FAKE_KODI_SOURCE)
        built = subprocess.run(
            ["cc", "-o", os.fspath(self.target.macos_dir / "Kodi"), os.fspath(source)],
            capture_output=True,
        )
        if built.returncode != 0:
            self.skipTest("could not compile the fake Kodi")
        self.children = []
        self.addCleanup(self._reap)

    def _reap(self):
        for child in self.children:
            child.kill()
            child.wait()

    def spawn(self, *flags):
        child = subprocess.Popen(
            [os.fspath(self.target.macos_dir / "Kodi"), *flags],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.children.append(child)
        return child

    def services(self):
        return make_services(
            self.target, process_lister=self.PidScopedLister([c.pid for c in self.children])
        )

    def test_real_process_with_p_is_identified(self):
        child = self.spawn("-p")
        identity = bm.identify(self.services(), require="running")
        self.assertEqual((identity.state, identity.pid), ("running_portable", child.pid))

    def test_real_embedded_portable_text_and_option_value_are_refused(self):
        for flags in (("--portable",), ("--debug -p",), ("--note=hello -p world",),
                      ("--log=/tmp/my -p dir/kodi.log",), ("--datadir", "-p")):
            with self.subTest(flags=flags):
                child = self.spawn(*flags)
                with self.assertRaises(bm.HelperError) as raised:
                    bm.identify(self.services(), require="running")
                self.assertEqual(raised.exception.code, "test_app_not_portable")
                child.kill()
                child.wait()
                self.children.remove(child)

    def test_real_spoofed_argv0_cannot_supply_executable_identity(self):
        other = self.tmp / "foreign-executable"
        shutil.copyfile(self.target.macos_dir / "Kodi", other)
        other.chmod(0o755)
        child = subprocess.Popen([str(self.target.macos_dir / "Kodi"), "-p"],
                                 executable=str(other), stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        self.children.append(child)
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services(), require="running")
        self.assertEqual(raised.exception.code, "test_app_not_running")
        # Also fail closed when the real target has a spoofed argv[0].
        child.kill()
        child.wait()
        self.children.remove(child)
        child = subprocess.Popen([str(other), "-p"],
                                 executable=str(self.target.macos_dir / "Kodi"),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.children.append(child)
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services(), require="running")
        self.assertEqual(raised.exception.code, "test_app_process_ambiguous")

    def test_real_process_without_p_is_refused(self):
        self.spawn()
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services())
        self.assertEqual(raised.exception.code, "test_app_not_portable")

    def test_two_real_processes_are_refused(self):
        self.spawn("-p")
        self.spawn("-p")
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(self.services())
        self.assertEqual(raised.exception.code, "multiple_test_app_processes")

    def test_not_running_when_no_child_exists(self):
        self.assertEqual(bm.identify(self.services()).state, "not_running")



# ---------------------------------------------------------------------------
# Git object-level candidate source
# ---------------------------------------------------------------------------

def tampering_runner(mutate):
    """subprocess.run that rewrites the stdout of `git cat-file --batch`."""
    def run(command, **kwargs):
        proc = subprocess.run(command, **kwargs)
        if "cat-file" in command and "--batch" in command:
            return SimpleNamespace(returncode=proc.returncode, stdout=mutate(proc.stdout), stderr=proc.stderr)
        return proc
    return run


class TestGitSource(TripwireTestCase):
    def test_resolve_commit_returns_the_exact_identity(self):
        identity = candidate_source().resolve_commit(FIXTURE.good)
        self.assertEqual(identity.commit, FIXTURE.good)
        self.assertEqual(
            identity.tree, git(FIXTURE.repo, "rev-parse", FIXTURE.good + "^{tree}").decode().strip()
        )
        self.assertEqual(identity.object_format, "sha1")

    def test_only_full_lowercase_object_ids_are_accepted(self):
        for bad in (
            FIXTURE.good[:7], FIXTURE.good[:39], FIXTURE.good + "0", FIXTURE.good.upper(), "HEAD",
            "master", FIXTURE.good + "^{tree}", "", FIXTURE.good + "\n", " " + FIXTURE.good,
            "g" * 40, "refs/heads/master", FIXTURE.good + "~1", "-" + FIXTURE.good[1:],
        ):
            with self.subTest(candidate=bad), self.assertRaises(bm.HelperError) as raised:
                candidate_source().resolve_commit(bad)
            self.assertEqual(raised.exception.code, "candidate_id_invalid")

    def test_missing_commit_is_reported(self):
        for missing in ("0" * 40, "1234567890abcdef1234567890abcdef12345678"):
            with self.subTest(missing=missing), self.assertRaises(bm.HelperError) as raised:
                candidate_source().resolve_commit(missing)
            self.assertEqual(raised.exception.code, "candidate_commit_missing")

    def test_trees_blobs_and_tags_are_not_commits(self):
        tree = git(FIXTURE.repo, "rev-parse", FIXTURE.good + "^{tree}").decode().strip()
        blob = git(FIXTURE.repo, "rev-parse", FIXTURE.good + ":addon.xml").decode().strip()
        git(FIXTURE.repo, "tag", "-a", "bm-test-tag", FIXTURE.good, "-m", "tag")
        try:
            tag = git(FIXTURE.repo, "rev-parse", "bm-test-tag").decode().strip()
        finally:
            git(FIXTURE.repo, "tag", "-d", "bm-test-tag")
        for label, oid in (("tree", tree), ("blob", blob), ("tag", tag)):
            with self.subTest(kind=label), self.assertRaises(bm.HelperError) as raised:
                candidate_source().resolve_commit(oid)
            self.assertEqual(raised.exception.code, "candidate_not_a_commit")

    def test_git_failures_never_echo_stderr(self):
        def failing(command, **kwargs):
            return SimpleNamespace(
                returncode=128, stdout=b"", stderr=SENTINEL_OVERLAY_PATH.encode(),
            )

        with self.assertRaises(bm.HelperError) as raised:
            candidate_source(failing).resolve_commit(FIXTURE.good)
        self.assertEqual(raised.exception.code, "candidate_commit_missing")
        self.assertEqual(raised.exception.detail["returncode"], 128)
        self.assertNotIn("sentinel", json.dumps(raised.exception.detail))

    def test_unavailable_git_and_runner_errors_fail_closed(self):
        with self.assertRaises(bm.HelperError) as raised:
            bm.GitSource(FIXTURE.repo, None)
        self.assertEqual(raised.exception.code, "candidate_git_unavailable")
        for error in (OSError("no git"), subprocess.TimeoutExpired("git", 1)):
            def raising(command, **kwargs):
                raise error

            with self.subTest(error=type(error).__name__), self.assertRaises(bm.HelperError) as raised:
                candidate_source(raising).list_tree(
                    bm.CommitIdentity(FIXTURE.good, "0" * 40, "sha1"), ["addon.xml"]
                )
            self.assertEqual(raised.exception.code, "candidate_git_failed")

    def test_git_environment_is_scrubbed_and_pinned(self):
        seen = []

        def spy(command, **kwargs):
            seen.append(dict(kwargs["env"]))
            self.assertIs(kwargs["shell"], False)
            return subprocess.run(command, **kwargs)

        with mock.patch.dict(os.environ, {
            "GIT_DIR": "/nonexistent", "GIT_WORK_TREE": "/nonexistent", "GIT_INDEX_FILE": "/nonexistent",
            "BM_SECRET_ENV": "do-not-forward", "HOME": str(self.tmp), "GIT_EXTERNAL_DIFF": "/bin/false",
        }):
            candidate_source(spy).resolve_commit(FIXTURE.good)
        self.assertTrue(seen)
        for env in seen:
            self.assertEqual(env["GIT_NO_REPLACE_OBJECTS"], "1")
            self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
            self.assertEqual(env["GIT_LITERAL_PATHSPECS"], "1")
            for forbidden in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "BM_SECRET_ENV", "HOME", "GIT_EXTERNAL_DIFF"):
                self.assertNotIn(forbidden, env)

    def test_unsafe_tree_entries_are_refused(self):
        cases = {
            "symlink": variant("symlink", [("120000", "resources/lib/link.py", b"/etc/passwd")]),
            "gitlink": variant("gitlink", [("160000", "resources/submodule", FIXTURE.good.encode())]),
            "dotdot": hostile_commit([".."]),
            "dotgit": hostile_commit([".git"]),
            "backslash": hostile_commit(["a\\b"]),
            "control": hostile_commit(["bad\x01name"]),
        }
        for label, commit in cases.items():
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                bm.load_candidate(candidate_source(), commit)
            self.assertEqual(raised.exception.code, "candidate_unsafe_entry")

    def test_repository_path_validation(self):
        for bad in ("", "/abs", "a/", "a//b", "a/../b", "./a", "a/./b", ".git/config", "a/.GIT/x",
                    "a\\b", "x" * 241, "a/\x00"):
            with self.subTest(path=bad), self.assertRaises(bm.HelperError):
                bm.validate_repo_path(bad)
        bm.validate_repo_path("resources/lib/a-b_c.py")

    def test_case_and_unicode_collisions_are_refused(self):
        cases = {
            "case": variant("case", [("100644", "resources/Case.py", b"a"), ("100644", "resources/case.py", b"b")]),
            "nfd": variant("nfd", [("100644", "resources/ré.py", b"a"), ("100644", "resources/ré.py", b"b")]),
            "parent": variant("parent", [("100644", "resources/lib2", b"a"), ("100644", "resources/LIB2/x.py", b"b")]),
        }
        for label, commit in cases.items():
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                bm.load_candidate(candidate_source(), commit)
            self.assertEqual(raised.exception.code, "candidate_path_collision")

    def test_required_files_must_exist(self):
        for required in (
            "addon.xml", "default.py", "service.py", "resources/lib/__init__.py",
            "resources/lib/frozen_install.py", "tools/build_bm023a_adapter.py",
            "tools/bm023a_adapter_support.py", "tools/bm023a_adapter/default.py.in",
            "tools/bm023a_adapter/addon.xml.in", "tools/__init__.py",
        ):
            commit = variant("without-" + required, [("100644", required, None)])
            with self.subTest(removed=required), self.assertRaises(bm.HelperError) as raised:
                bm.load_candidate(candidate_source(), commit)
            self.assertEqual(raised.exception.code, "candidate_incomplete")

    def test_addon_xml_must_describe_build_manager(self):
        original = (PROJECT / "addon.xml").read_bytes()
        cases = {
            "other-id": original.replace(b'id="script.build.manager"', b'id="script.other"'),
            "doctype": original.replace(b"<addon", b"<!DOCTYPE addon [<!ENTITY x 'y'>]><addon", 1),
            "malformed": b"<addon id=",
            "no-version": original.replace(b'version="0.1.0"', b""),
            "wrong-root": b"<notaddon id='script.build.manager' version='1'/>",
        }
        for label, content in cases.items():
            commit = variant("addonxml-" + label, [("100644", "addon.xml", content)])
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                bm.load_candidate(candidate_source(), commit)
            self.assertEqual(raised.exception.code, "candidate_addon_xml_invalid")

    def test_adapter_version_must_be_a_literal(self):
        support = (PROJECT / "tools/bm023a_adapter_support.py").read_bytes()
        dynamic = support.replace(b'ADAPTER_VERSION = "0.0.15"', b'ADAPTER_VERSION = "0.0." + str(15)')
        commit = variant("dynamic-version", [("100644", "tools/bm023a_adapter_support.py", dynamic)])
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_candidate(candidate_source(), commit)
        self.assertEqual(raised.exception.code, "candidate_incomplete")

    def test_size_and_count_limits_fail_closed(self):
        with mock.patch.object(bm, "MAX_BLOB_BYTES", 10), self.assertRaises(bm.HelperError) as raised:
            bm.load_candidate(candidate_source(), FIXTURE.good)
        self.assertEqual(raised.exception.code, "candidate_blob_too_large")
        with mock.patch.object(bm, "MAX_CANDIDATE_BYTES", 100), self.assertRaises(bm.HelperError) as raised:
            bm.load_candidate(candidate_source(), FIXTURE.good)
        self.assertEqual(raised.exception.code, "candidate_too_large")
        with mock.patch.object(bm, "MAX_CANDIDATE_FILES", 5), self.assertRaises(bm.HelperError) as raised:
            bm.load_candidate(candidate_source(), FIXTURE.good)
        self.assertEqual(raised.exception.code, "candidate_too_large")
        with mock.patch.object(bm, "MAX_GIT_OUTPUT", 50), self.assertRaises(bm.HelperError) as raised:
            bm.load_candidate(candidate_source(), FIXTURE.good)
        self.assertEqual(raised.exception.code, "candidate_git_output_too_large")

    def test_blob_stream_tampering_is_detected(self):
        def first_content_offset(output):
            return output.find(b"\n") + 1

        def flip(output):
            index = first_content_offset(output)
            return output[:index] + bytes([output[index] ^ 1]) + output[index + 1:]

        def truncate(output):
            return output[:-30]

        def missing(output):
            return output.split(b" ", 1)[0] + b" missing\n"

        def bad_size(output):
            head, rest = output.split(b"\n", 1)
            return head.rsplit(b" ", 1)[0] + b" 12x\n" + rest

        def wrong_oid(output):
            return b"0" * 40 + output[40:]

        for label, mutate, code in (
            ("flip", flip, "candidate_blob_mismatch"),
            ("truncate", truncate, "candidate_blob_stream_malformed"),
            ("missing", missing, "candidate_blob_missing"),
            ("bad-size", bad_size, "candidate_blob_stream_malformed"),
            ("wrong-oid", wrong_oid, "candidate_blob_missing"),
        ):
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                bm.load_candidate(candidate_source(tampering_runner(mutate)), FIXTURE.good)
            self.assertEqual(raised.exception.code, code)

    def test_malformed_ls_tree_output_is_refused(self):
        def garbage(command, **kwargs):
            proc = subprocess.run(command, **kwargs)
            if "ls-tree" in command:
                return SimpleNamespace(returncode=0, stdout=b"not a tree record\0", stderr=b"")
            return proc

        with self.assertRaises(bm.HelperError) as raised:
            bm.load_candidate(candidate_source(garbage), FIXTURE.good)
        self.assertEqual(raised.exception.code, "candidate_tree_malformed")

    def test_product_set_is_exactly_the_runtime_content(self):
        candidate = bm.load_candidate(candidate_source(), FIXTURE.good)
        paths = [item.path for item in candidate.product]
        expected = git(
            FIXTURE.repo, "ls-tree", "-r", "--name-only", FIXTURE.good, "--",
            "addon.xml", "default.py", "service.py", "resources",
        ).decode().split("\n")
        self.assertEqual(sorted(paths), sorted(p for p in expected if p))
        for path in paths:
            self.assertTrue(path in bm.PRODUCT_ROOT_FILES or path.startswith("resources/"), path)
        for excluded in (".agent", ".orchestrator", "tests", "docs", "tools", "README.md", "LICENSE.txt", "changelog.md"):
            self.assertFalse([p for p in paths if p == excluded or p.startswith(excluded + "/")], excluded)
        for required in bm.PRODUCT_REQUIRED:
            self.assertIn(required, paths)

    def test_blob_bytes_are_the_git_blobs(self):
        candidate = bm.load_candidate(candidate_source(), FIXTURE.good)
        for item in (*candidate.product, *candidate.tools):
            self.assertEqual(
                item.data, git(FIXTURE.repo, "cat-file", "blob", item.blob), item.path
            )
            self.assertEqual(item.sha256, hashlib.sha256(item.data).hexdigest())

    def test_dirty_working_tree_cannot_change_the_candidate(self):
        victim = FIXTURE.repo / "resources" / "lib" / "utils.py"
        original = victim.read_bytes()
        evil = FIXTURE.repo / "resources" / "lib" / "untracked_evil.py"
        addon_xml = FIXTURE.repo / "addon.xml"
        addon_original = addon_xml.read_bytes()
        try:
            victim.write_bytes(original + b"\n# DIRTY-WORKING-TREE-BYTES\n")
            evil.write_bytes(b"print('evil')\n")
            addon_xml.write_bytes(addon_original.replace(b"0.1.0", b"9.9.9"))
            candidate = bm.load_candidate(candidate_source(), FIXTURE.good)
        finally:
            victim.write_bytes(original)
            addon_xml.write_bytes(addon_original)
            evil.unlink(missing_ok=True)
        self.assertNotIn(b"DIRTY-WORKING-TREE-BYTES", candidate.product_file("resources/lib/utils.py").data)
        self.assertNotIn("resources/lib/untracked_evil.py", [i.path for i in candidate.product])
        self.assertEqual(candidate.addon_version, "0.1.0")

    def test_checked_out_head_is_not_assumed_to_be_the_candidate(self):
        other = variant("other-head", [("100644", "resources/lib/utils.py", b"# a different commit\n")])
        git(FIXTURE.repo, "checkout", "-q", "--detach", other)
        try:
            self.assertEqual(
                git(FIXTURE.repo, "rev-parse", "HEAD").decode().strip(), other
            )
            candidate = bm.load_candidate(candidate_source(), FIXTURE.good)
        finally:
            git(FIXTURE.repo, "checkout", "-q", "--detach", FIXTURE.good)
        self.assertNotEqual(candidate.product_file("resources/lib/utils.py").data, b"# a different commit\n")
        self.assertEqual(candidate.identity.commit, FIXTURE.good)

    def test_replace_refs_cannot_substitute_bytes(self):
        blob = git(FIXTURE.repo, "rev-parse", FIXTURE.good + ":resources/lib/utils.py").decode().strip()
        fake = git(FIXTURE.repo, "hash-object", "-w", "--stdin", stdin=b"REPLACED\n").decode().strip()
        git(FIXTURE.repo, "replace", blob, fake)
        try:
            self.assertEqual(git(FIXTURE.repo, "cat-file", "blob", blob), b"REPLACED\n")  # replace is live
            candidate = bm.load_candidate(candidate_source(), FIXTURE.good)
        finally:
            git(FIXTURE.repo, "replace", "-d", blob)
        self.assertNotEqual(candidate.product_file("resources/lib/utils.py").data, b"REPLACED\n")

    def test_attributes_and_keyword_substitution_cannot_change_bytes(self):
        content = b"line one\nline two $Id$ $Format:%H$\n"
        commit = variant("attributes", [
            ("100644", ".gitattributes", b"* text eol=crlf\n*.py ident export-subst\n"),
            ("100644", "resources/lib/attr_probe.py", content),
        ])
        candidate = bm.load_candidate(candidate_source(), commit)
        self.assertEqual(candidate.product_file("resources/lib/attr_probe.py").data, content)
        self.assertNotIn(".gitattributes", [i.path for i in candidate.product])


@unittest.skipUnless(
    subprocess.run(["git", "-C", str(PROJECT), "cat-file", "-e", REAL_CANDIDATE + "^{commit}"],
                   capture_output=True).returncode == 0,
    "reviewed candidate commit is not present in this clone",
)
class TestRealReviewedCandidate(TripwireTestCase):
    """The helper must support the reviewed candidate 8789329 from the real repo."""

    def setUp(self):
        super().setUp()
        self.source = bm.GitSource(PROJECT, bm.find_git())
        self.candidate = bm.load_candidate(self.source, REAL_CANDIDATE)

    def test_identity_matches_the_reviewed_commit(self):
        self.assertEqual(self.candidate.identity.commit, REAL_CANDIDATE)
        self.assertEqual(self.candidate.identity.tree, "9e51f5dbf30aba3a795d98bea77d93572b5c81df")
        self.assertEqual(self.candidate.resources_tree, "5032525c6bee4e7247dddda255350450f8b5d2fd")
        self.assertEqual(self.candidate.addon_version, "0.1.0")
        self.assertEqual(self.candidate.adapter_version, "0.0.15")

    def test_product_set_is_the_46_runtime_files(self):
        self.assertEqual(len(self.candidate.product), 46)
        self.assertEqual(sum(item.size for item in self.candidate.product), 989437)
        self.assertEqual({item.mode for item in self.candidate.product}, {"100644"})
        for path in ("addon.xml", "default.py", "service.py", "resources/lib/frozen_install.py"):
            self.assertIn(path, [item.path for item in self.candidate.product])

    def test_bytes_equal_the_git_blobs_of_the_candidate(self):
        for item in self.candidate.product:
            blob = subprocess.run(
                ["git", "-C", str(PROJECT), "cat-file", "blob", item.blob], capture_output=True, check=True
            ).stdout
            self.assertEqual(item.data, blob, item.path)

    def test_reviewed_candidate_stages_into_a_fake_bundle_and_verifies_against_git(self):
        target = make_fake_app(self.tmp)
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        evidence = self.tmp / "evidence"
        evidence.mkdir()
        services = make_services(target, process_lister=FakeProcessLister(), tmp_root=scratch)
        payload = bm.run_stage(
            services, candidate_id=REAL_CANDIDATE, config={"adapter": dict(ADAPTER_VALUES), "rpc": {}},
            repo=PROJECT, evidence_dir=evidence, dry_run=False,
        )
        manifest = payload["manifest"]
        self.assertEqual(manifest["candidate"]["commit"], REAL_CANDIDATE)
        self.assertEqual(manifest["build_manager"]["file_count"], 46)
        self.assertEqual(manifest["driver"]["adapter_version"], "0.0.15")
        result = bm.verify_installed(services, manifest, git_repo=PROJECT)
        self.assertTrue(result["installed_equals_candidate"])
        staged = {e.rel for e in bm.walk_tree(target.addon_dir(bm.BUILD_MANAGER_ID)) if e.kind == "file"}
        expected = subprocess.run(
            ["git", "-C", str(PROJECT), "ls-tree", "-r", "--name-only", REAL_CANDIDATE, "--",
             "addon.xml", "default.py", "service.py", "resources"], capture_output=True, text=True, check=True,
        ).stdout.split()
        self.assertEqual(staged, set(expected))
        self.assertEqual(list(scratch.iterdir()), [])

    def test_driver_is_built_from_the_candidate_and_binds_its_frozen_install(self):
        driver = bm.build_driver(self.candidate, ADAPTER_VALUES, new_workspace(self), sys.executable)
        self.assertEqual(driver.adapter_version, "0.0.15")
        self.assertEqual(driver.addon_version, "0.0.15")
        frozen = self.candidate.product_file("resources/lib/frozen_install.py")
        self.assertEqual(driver.frozen_install_sha256, frozen.sha256)
        self.assertEqual(driver.data("bundled_frozen_install.py"), frozen.data)


# ---------------------------------------------------------------------------
# Driver build from the candidate export
# ---------------------------------------------------------------------------

REAL_BUILDER = (PROJECT / "tools" / "build_bm023a_adapter.py").read_text(encoding="utf-8")


def patched_builder(old, new):
    assert old in REAL_BUILDER, old
    return REAL_BUILDER.replace(old, new, 1).encode("utf-8")


class TestDriverBuild(TripwireTestCase):
    def test_driver_comes_from_the_candidate_export_not_the_working_tree(self):
        original_default = (PROJECT / "tools/bm023a_adapter/default.py.in").read_bytes()
        original_frozen = (PROJECT / "resources/lib/frozen_install.py").read_bytes()
        commit = variant("driver-marker", [
            ("100644", "tools/bm023a_adapter/default.py.in", original_default + b"\n# CANDIDATE-MARKER-9137\n"),
            ("100644", "resources/lib/frozen_install.py", original_frozen + b"\n# frozen marker 5521\n"),
        ])
        candidate, driver = build_plan(self, commit)
        self.assertIn(b"CANDIDATE-MARKER-9137", driver.data("default.py"))
        self.assertTrue(driver.data("bundled_frozen_install.py").endswith(b"# frozen marker 5521\n"))
        self.assertEqual(driver.frozen_install_sha256, hashlib.sha256(driver.data("bundled_frozen_install.py")).hexdigest())
        self.assertNotIn(b"CANDIDATE-MARKER-9137", original_default)
        self.assertNotIn(b"frozen marker 5521", (PROJECT / "resources/lib/frozen_install.py").read_bytes())
        self.assertEqual(driver.frozen_install_sha256, candidate.product_file("resources/lib/frozen_install.py").sha256)

    def test_driver_has_exactly_the_expected_files_and_versions(self):
        candidate, driver, _ = good_plan()
        self.assertEqual([name for name, _ in driver.files], sorted(bm.DRIVER_FILES))
        self.assertEqual(driver.addon_version, driver.adapter_version)
        self.assertEqual(driver.adapter_version, candidate.adapter_version)

    def test_adapter_config_carries_the_values_and_the_frozen_digest(self):
        candidate, driver, _ = good_plan()
        generated = bm._parse_adapter_config(driver.data("adapter_config.py"))
        for key in bm.ADAPTER_CONFIG_KEYS:
            self.assertEqual(generated[key], ADAPTER_VALUES[key])
        self.assertEqual(
            generated["EXPECTED_FROZEN_INSTALL_SHA256"],
            candidate.product_file("resources/lib/frozen_install.py").sha256,
        )

    def test_config_reaches_the_builder_by_private_file_never_argv_or_env(self):
        captured = {}

        def spy(command, **kwargs):
            captured["command"], captured["env"] = list(command), dict(kwargs["env"])
            captured["shell"], captured["cwd"] = kwargs["shell"], kwargs["cwd"]
            config = Path(command[command.index("--reuse-config-from") + 1])
            captured["config_mode"] = stat.S_IMODE(config.stat().st_mode)
            captured["config_text"] = config.read_text()
            return subprocess.run(command, **kwargs)

        build_plan(self, FIXTURE.good, runner=spy)
        everything = " ".join(captured["command"]) + " " + " ".join(captured["env"].values())
        for key, value in ADAPTER_VALUES.items():
            self.assertNotIn(value, everything, key)
        self.assertIs(captured["shell"], False)
        self.assertEqual(captured["config_mode"], 0o600)
        self.assertIn(SENTINEL_OVERLAY_PATH, captured["config_text"])  # in the private file only
        self.assertEqual(captured["command"][1:3], ["-I", "-B"])
        self.assertTrue(captured["command"][3].endswith("/export/tools/build_bm023a_adapter.py"))
        self.assertLessEqual(set(captured["env"]), {"PATH", "LC_ALL", "LANG", "PYTHONDONTWRITEBYTECODE"})

    def test_export_holds_only_candidate_files(self):
        candidate = bm.load_candidate(candidate_source(), FIXTURE.good)
        workspace = new_workspace(self)
        export = bm.export_candidate(workspace, candidate)
        listing = {e.rel for e in bm.walk_tree(export) if e.kind == "file"}
        self.assertEqual(listing, {i.path for i in (*candidate.product, *candidate.tools)})
        self.assertNotIn(".agent/HANDOFF.md", listing)
        self.assertNotIn("README.md", listing)

    def test_builder_defects_in_the_candidate_are_detected(self):
        defects = {
            "driver_build_failed": patched_builder("def main() -> int:\n", "def main() -> int:\n    raise SystemExit(3)\n"),
            "driver_output_unexpected": patched_builder(
                '    archive_path = output_dir / f"{DRIVER_ADDON_ID}.zip"',
                '    (package_root / "extra.txt").write_text("x")\n    archive_path = output_dir / f"{DRIVER_ADDON_ID}.zip"',
            ),
            "driver_source_mismatch": patched_builder(
                'shutil.copyfile(TEMPLATE_ROOT / "default.py.in", package_root / "default.py")',
                '(package_root / "default.py").write_bytes((TEMPLATE_ROOT / "default.py.in").read_bytes() + b"# tampered\\n")',
            ),
            "driver_config_mismatch": patched_builder(
                "render_config(values)", 'render_config(dict(values, DEVICE_PROFILE_ID="other-device"))'
            ),
        }
        for code, source in defects.items():
            commit = variant("builder-" + code, [("100644", "tools/build_bm023a_adapter.py", source)])
            with self.subTest(code=code), self.assertRaises(bm.HelperError) as raised:
                build_plan(self, commit)
            self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.detail.get("returncode", None), None)

    def test_builder_exit_status_is_reported_without_output_text(self):
        source = patched_builder("def main() -> int:\n", "def main() -> int:\n    print('SECRET-BUILDER-OUTPUT')\n    raise SystemExit(3)\n")
        commit = variant("builder-exit-3", [("100644", "tools/build_bm023a_adapter.py", source)])
        with self.assertRaises(bm.HelperError) as raised:
            build_plan(self, commit)
        self.assertEqual(raised.exception.code, "driver_build_failed")
        self.assertEqual(raised.exception.detail["returncode"], 3)
        self.assertNotIn("SECRET-BUILDER-OUTPUT", json.dumps(raised.exception.detail))

    def test_symlink_or_missing_files_in_builder_output_are_refused(self):
        link = patched_builder(
            '    archive_path = output_dir / f"{DRIVER_ADDON_ID}.zip"',
            '    (package_root / "link").symlink_to("/etc/hosts")\n    archive_path = output_dir / f"{DRIVER_ADDON_ID}.zip"',
        )
        missing = patched_builder(
            "    return archive_path\n", '    (package_root / "adapter_config.py").unlink()\n    return archive_path\n'
        )
        for label, source in (("link", link), ("missing", missing)):
            commit = variant("builder-output-" + label, [("100644", "tools/build_bm023a_adapter.py", source)])
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                build_plan(self, commit)
            self.assertEqual(raised.exception.code, "driver_output_unexpected")

    def test_frozen_digest_and_version_must_agree_with_the_candidate(self):
        digest = patched_builder(
            "expected_frozen_install_sha256 = hashlib.sha256(frozen_install_bytes).hexdigest()",
            'expected_frozen_install_sha256 = "0" * 64',
        )
        commit = variant("builder-digest", [("100644", "tools/build_bm023a_adapter.py", digest)])
        with self.assertRaises(bm.HelperError) as raised:
            build_plan(self, commit)
        self.assertEqual(raised.exception.code, "driver_config_mismatch")
        xml = (PROJECT / "tools/bm023a_adapter/addon.xml.in").read_bytes().replace(b'version="0.0.15"', b'version="0.0.99"')
        commit = variant("driver-version", [("100644", "tools/bm023a_adapter/addon.xml.in", xml)])
        with self.assertRaises(bm.HelperError) as raised:
            build_plan(self, commit)
        self.assertEqual(raised.exception.code, "driver_version_mismatch")

    def test_runner_errors_are_reported_as_build_failures(self):
        for error in (OSError("no python"), subprocess.TimeoutExpired("python", 1)):
            def raising(command, **kwargs):
                raise error

            with self.subTest(error=type(error).__name__), self.assertRaises(bm.HelperError) as raised:
                build_plan(self, FIXTURE.good, runner=raising)
            self.assertEqual(raised.exception.code, "driver_build_failed")

    def test_builder_inputs_match_this_checkouts_builder_contract(self):
        # Compatibility canaries: the helper's pins must equal the real builder's.
        self.assertEqual(bm.ADAPTER_CONFIG_KEYS, build_bm023a_adapter.CONFIG_KEYS)
        self.assertEqual(bm.DRIVER_ID, adapter_support.DRIVER_ADDON_ID)
        self.assertEqual(bm.BUILD_MANAGER_ID, adapter_support.ADDON_ID)
        self.assertLessEqual(set(bm.BUILDER_REQUIRED), set(tracked_product_files()))
        self.assertLessEqual(set(bm.PRODUCT_REQUIRED), set(tracked_product_files()))
        with tempfile.TemporaryDirectory() as out:
            build_bm023a_adapter.build_adapter(Path(out), dict(ADAPTER_VALUES))
            produced = sorted(p.name for p in (Path(out) / bm.DRIVER_ID).iterdir())
        self.assertEqual(produced, sorted(bm.DRIVER_FILES))
        candidate, driver, _ = good_plan()
        with tempfile.TemporaryDirectory() as out:
            build_bm023a_adapter.build_adapter(Path(out), dict(ADAPTER_VALUES))
            for name, source in bm.DRIVER_SOURCE_PATHS.items():
                self.assertEqual((Path(out) / bm.DRIVER_ID / name).read_bytes(), (PROJECT / source).read_bytes(), name)


# ---------------------------------------------------------------------------
# Machine-local configuration
# ---------------------------------------------------------------------------

class TestConfig(TripwireTestCase):
    def setUp(self):
        super().setUp()
        self.services = make_services(make_fake_app(self.tmp))

    def write(self, document, mode=0o600, name="cfg.json"):
        path = self.tmp / name
        path.write_text(json.dumps(document) if not isinstance(document, str) else document, encoding="utf-8")
        path.chmod(mode)
        return path

    def adapter(self, **overrides):
        return dict(ADAPTER_VALUES, **overrides)

    def assertConfigError(self, document, code=None, **kwargs):
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_config(self.write(document, **kwargs), self.services)
        if code is not None:
            self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_valid_config_is_normalized_and_registers_its_paths_as_secrets(self):
        path = make_config(self.tmp, rpc={"host": "localhost", "port": 8089, "username": "kodi-user"})
        config = bm.load_config(path, self.services)
        self.assertEqual(config["adapter"], ADAPTER_VALUES)
        self.assertEqual(config["rpc"], {"host": "127.0.0.1", "port": 8089, "username": "kodi-user"})
        for key in bm.ADAPTER_PATH_KEYS:
            self.assertTrue(self.services.secrets.leaks(ADAPTER_VALUES[key]), key)
        self.assertFalse(self.services.secrets.leaks("fixture-device"))

    def test_adapter_and_rpc_sections_are_optional(self):
        config = bm.load_config(make_config(self.tmp, adapter=False), self.services)
        self.assertEqual(config, {"adapter": None, "rpc": {}})

    def test_group_readable_config_is_allowed_but_not_writable(self):
        bm.load_config(make_config(self.tmp, mode=0o644), self.services)
        for mode in (0o620, 0o602, 0o666):
            with self.subTest(mode=oct(mode)):
                self.assertConfigError({"schema": bm.CONFIG_SCHEMA}, "config_unsafe_permissions", mode=mode)

    def test_schema_is_closed(self):
        good = {"schema": bm.CONFIG_SCHEMA, "adapter": self.adapter()}
        for label, document in (
            ("wrong schema", dict(good, schema="other/1")),
            ("no schema", {"adapter": self.adapter()}),
            ("unknown top key", dict(good, extra=1)),
            ("root list", ["x"]),
            ("adapter not object", dict(good, adapter=["x"])),
            ("adapter missing key", dict(good, adapter={k: v for k, v in self.adapter().items() if k != "OVERLAY_SOURCE"})),
            ("adapter extra key", dict(good, adapter=self.adapter(EXTRA="x"))),
            ("rpc extra key", dict(good, rpc={"host": "127.0.0.1", "extra": 1})),
            ("rpc not object", dict(good, rpc=5)),
        ):
            with self.subTest(case=label):
                self.assertConfigError(document, "config_invalid")

    def test_adapter_values_are_validated(self):
        for key, value in (
            ("MANIFEST_PATH", ""), ("MANIFEST_PATH", 5), ("MANIFEST_PATH", "relative/path.json"),
            ("MANIFEST_PATH", "/a/../b.json"), ("MANIFEST_PATH", "/a//b.json"), ("MANIFEST_PATH", "/x\ny.json"),
            ("OVERLAY_SOURCE", "/x\x00y"), ("ARTIFACT_ROOT", "/" + "a" * 5000),
            ("DEVICE_PROFILE_ID", "has space"), ("DEVICE_PROFILE_ID", "../x"), ("EXPECTED_OVERLAY_ID", ""),
            ("EXPECTED_OVERLAY_ID", "x" * 200),
        ):
            with self.subTest(key=key, value=repr(value)[:30]):
                self.assertConfigError({"schema": bm.CONFIG_SCHEMA, "adapter": self.adapter(**{key: value})}, "config_invalid")

    def test_adapter_paths_inside_normal_kodi_are_refused(self):
        for bad in ("/Applications/Kodi.app/Contents/x.json", "/Users/eengert/Library/Application Support/Kodi/x"):
            with self.subTest(bad=bad):
                self.assertConfigError(
                    {"schema": bm.CONFIG_SCHEMA, "adapter": self.adapter(OVERLAY_SOURCE=bad)}, "argument_path_forbidden"
                )

    def test_credential_fields_are_refused_anywhere(self):
        for document in (
            {"schema": bm.CONFIG_SCHEMA, "rpc": {"password": "x"}},
            {"schema": bm.CONFIG_SCHEMA, "rpc": {"Password": "x"}},
            {"schema": bm.CONFIG_SCHEMA, "rpc": {"api_key": "x"}},
            {"schema": bm.CONFIG_SCHEMA, "token": "x"},
            {"schema": bm.CONFIG_SCHEMA, "adapter": self.adapter(), "auth": {"user": "x"}},
            {"schema": bm.CONFIG_SCHEMA, "rpc": {"host": "127.0.0.1", "nested": [{"secret": "x"}]}},
            {"schema": bm.CONFIG_SCHEMA, "rpc": {"cookie": "x"}},
        ):
            with self.subTest(document=document):
                self.assertConfigError(document, "config_credential_field")

    def test_rpc_values_are_validated(self):
        for host in ("192.168.1.5", "0.0.0.0", "example.com", "::ffff:127.0.0.1", "127.0.0.1.evil.com",
                     "localhost.evil", "", 5, None, "10.0.0.1", "::", "fe80::1", "::1%lo0", "::ffff:7f00:1",
                     "127.1", "2130706433", "0x7f.0.0.1", " 127.0.0.1", "127.0.0.1 ", "[::1]", "LOCALHOST"):
            with self.subTest(host=host):
                self.assertConfigError({"schema": bm.CONFIG_SCHEMA, "rpc": {"host": host}}, "rpc_host_not_loopback")
        for host, expected in (("127.0.0.1", "127.0.0.1"), ("::1", "::1"), ("localhost", "127.0.0.1"), ("127.5.5.5", "127.5.5.5")):
            with self.subTest(good=host):
                self.assertEqual(bm.validate_loopback_host(host), expected)
        for port in (0, 65536, -1, "80", True, 1.5, None, 10 ** 9):
            with self.subTest(port=port):
                self.assertConfigError({"schema": bm.CONFIG_SCHEMA, "rpc": {"port": port}}, "rpc_port_invalid")
        for user in ("", "a b", "x" * 65, "a;b", 5, "a\nb"):
            with self.subTest(user=user):
                self.assertConfigError({"schema": bm.CONFIG_SCHEMA, "rpc": {"username": user}}, "config_invalid")

    def test_file_level_problems(self):
        self.assertConfigError("not json", "config_invalid")
        self.assertConfigError('{"schema": "bm-test-app-config/1", "schema": "x"}', "config_invalid")
        self.assertConfigError("[]", "config_invalid")
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_config(self.tmp / "missing.json", self.services)
        self.assertEqual(raised.exception.code, "argument_path_not_found")
        directory = self.tmp / "adir"
        directory.mkdir()
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_config(directory, self.services)
        self.assertEqual(raised.exception.code, "config_unreadable")
        real = self.write({"schema": bm.CONFIG_SCHEMA}, name="real.json")
        link = self.tmp / "link.json"
        link.symlink_to(real)
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_config(link, self.services)
        self.assertEqual(raised.exception.code, "argument_path_symlink")
        big = self.write({"schema": bm.CONFIG_SCHEMA, "pad": "x" * 100000}, name="big.json")
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_config(big, self.services)
        self.assertEqual(raised.exception.code, "config_unreadable")

    def test_config_inside_the_test_app_is_refused(self):
        inside = self.services.target.root / "Contents" / "cfg.json"
        inside.write_text("{}")
        inside.chmod(0o600)
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_config(inside, self.services)
        self.assertEqual(raised.exception.code, "argument_path_inside_test_app")

    def test_fingerprint_is_deterministic_value_sensitive_and_opaque(self):
        first = bm.config_fingerprint(ADAPTER_VALUES)
        self.assertEqual(first, bm.config_fingerprint(dict(reversed(list(ADAPTER_VALUES.items())))))
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")
        for key in ADAPTER_VALUES:
            changed = dict(ADAPTER_VALUES, **{key: ADAPTER_VALUES[key] + "x"})
            self.assertNotEqual(first, bm.config_fingerprint(changed), key)
        for value in ADAPTER_VALUES.values():
            self.assertNotIn(value, first)


# ---------------------------------------------------------------------------
# Stage manifest
# ---------------------------------------------------------------------------

def manifest_copy():
    return json.loads(json.dumps(good_plan()[2]))


class TestManifest(TripwireTestCase):
    def test_manifest_validates_and_binds_the_exact_staged_product_set(self):
        candidate, driver, manifest = good_plan()
        self.assertIs(bm.validate_manifest(manifest), manifest)
        self.assertEqual(manifest["candidate"]["commit"], FIXTURE.good)
        self.assertEqual(manifest["candidate"]["tree"], candidate.identity.tree)
        self.assertEqual(manifest["candidate"]["resources_tree"], candidate.resources_tree)
        paths = [entry["path"] for entry in manifest["build_manager"]["files"]]
        self.assertEqual(paths, sorted(item.path for item in candidate.product))
        self.assertEqual(manifest["build_manager"]["addon_version"], "0.1.0")
        self.assertEqual(manifest["driver"]["adapter_version"], "0.0.15")
        self.assertEqual(manifest["driver"]["default_py_sha256"], hashlib.sha256(driver.data("default.py")).hexdigest())
        self.assertEqual(manifest["driver"]["frozen_install_sha256"], driver.frozen_install_sha256)
        self.assertEqual(manifest["build_manager"]["file_count"], len(paths))
        for entry in manifest["build_manager"]["files"]:
            item = candidate.product_file(entry["path"])
            self.assertEqual((entry["sha256"], entry["size"], entry["git_blob"], entry["git_mode"]),
                             (item.sha256, item.size, item.blob, item.mode))

    def test_driver_entries_record_their_candidate_sources(self):
        candidate, _, manifest = good_plan()
        by_name = {entry["path"]: entry for entry in manifest["driver"]["files"]}
        self.assertTrue(by_name["adapter_config.py"]["generated"])
        self.assertIsNone(by_name["adapter_config.py"]["source_git_blob"])
        for name, source in bm.DRIVER_SOURCE_PATHS.items():
            self.assertFalse(by_name[name]["generated"])
            self.assertEqual(by_name[name]["source_git_path"], source)
            self.assertEqual(by_name[name]["source_git_blob"], candidate.source_file(source).blob)

    def test_manifest_contains_no_private_values_or_machine_paths(self):
        text = bm.canonical_json(good_plan()[2])
        for key, value in ADAPTER_VALUES.items():
            self.assertNotIn(value, text, key)
        self.assertNotIn("/Users/", text)
        self.assertNotIn(str(FIXTURE.repo), text)
        self.assertNotIn("Authorization", text)

    def test_manifest_bytes_are_deterministic_ascii_json(self):
        manifest = good_plan()[2]
        first = bm.manifest_bytes(manifest)
        self.assertEqual(first, bm.manifest_bytes(json.loads(first)))
        self.assertTrue(first.isascii())
        self.assertEqual(json.loads(first)["schema"], bm.MANIFEST_SCHEMA)

    def test_every_tampering_is_rejected(self):
        def set_path(document, *keys, value):
            node = document
            for key in keys[:-1]:
                node = node[key]
            node[keys[-1]] = value

        mutations = {
            "schema": lambda d: set_path(d, "schema", value="x/1"),
            "created_utc": lambda d: set_path(d, "created_utc", value="yesterday"),
            "extra top key": lambda d: d.update(extra=1),
            "missing key": lambda d: d.pop("tool"),
            "tool name": lambda d: set_path(d, "tool", "name", value="other"),
            "ignored artifacts": lambda d: set_path(d, "ignored_runtime_artifacts", value=["__pycache__", ".git"]),
            "fingerprint format": lambda d: set_path(d, "configuration_fingerprint", value="md5:abc"),
            "commit not hex": lambda d: set_path(d, "candidate", "commit", value="Z" * 40),
            "object format": lambda d: set_path(d, "candidate", "object_format", value="md5"),
            "bm addon id": lambda d: set_path(d, "build_manager", "addon_id", value="script.other"),
            "bm install dir": lambda d: set_path(d, "build_manager", "install_dir", value="script.other"),
            "driver install dir": lambda d: set_path(d, "driver", "install_dir", value="elsewhere"),
            "bm version": lambda d: set_path(d, "build_manager", "addon_version", value="v 1"),
            "file count": lambda d: set_path(d, "build_manager", "file_count", value=1),
            "total bytes": lambda d: set_path(d, "build_manager", "total_bytes", value=1),
            "tree digest": lambda d: set_path(d, "build_manager", "tree_sha256", value="0" * 64),
            "driver tree digest": lambda d: set_path(d, "driver", "tree_sha256", value="0" * 64),
            "file sha": lambda d: set_path(d, "build_manager", "files", 0, "sha256", value="0" * 64),
            "file sha short": lambda d: set_path(d, "build_manager", "files", 0, "sha256", value="abc"),
            "file size negative": lambda d: set_path(d, "build_manager", "files", 0, "size", value=-1),
            "file size bool": lambda d: set_path(d, "build_manager", "files", 0, "size", value=True),
            "file extra key": lambda d: d["build_manager"]["files"][0].update(extra=1),
            "file git mode": lambda d: set_path(d, "build_manager", "files", 0, "git_mode", value="120000"),
            "path traversal": lambda d: set_path(d, "build_manager", "files", 0, "path", value="../x"),
            "path absolute": lambda d: set_path(d, "build_manager", "files", 0, "path", value="/etc/x"),
            "path dot git": lambda d: set_path(d, "build_manager", "files", 0, "path", value=".git/x"),
            "unsorted": lambda d: d["build_manager"]["files"].reverse(),
            "duplicate path": lambda d: d["build_manager"]["files"].insert(1, dict(d["build_manager"]["files"][0])),
            "driver file removed": lambda d: d["driver"]["files"].pop(),
            "driver generated flag": lambda d: set_path(d, "driver", "files", 0, "generated", value=False),
            "driver source blob": lambda d: set_path(d, "driver", "files", 1, "source_git_blob", value=None),
            "driver source path": lambda d: set_path(d, "driver", "files", 1, "source_git_path", value="tools/other.py"),
            "root not object": lambda d: None,
        }
        for label, mutate in mutations.items():
            document = manifest_copy()
            if label == "root not object":
                document = ["not", "an", "object"]
            else:
                mutate(document)
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                bm.validate_manifest(document)
            self.assertEqual(raised.exception.code, "manifest_invalid", label)

    def test_case_colliding_manifest_paths_are_rejected(self):
        document = manifest_copy()
        first = dict(document["build_manager"]["files"][0])
        clash = dict(first, path=first["path"].upper() if first["path"].upper() != first["path"] else first["path"] + "X")
        document["build_manager"]["files"] = sorted([first, clash], key=lambda e: e["path"]) + document["build_manager"]["files"][1:]
        with self.assertRaises(bm.HelperError):
            bm.validate_manifest(document)

    def test_load_manifest_from_file_returns_the_hash_of_the_exact_bytes(self):
        services = make_services(make_fake_app(self.tmp))
        data = bm.manifest_bytes(good_plan()[2])
        path = self.tmp / "stage_manifest.json"
        path.write_bytes(data)
        manifest, digest = bm.load_manifest(path, services)
        self.assertEqual(manifest, good_plan()[2])
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())

    def test_load_manifest_failure_modes(self):
        services = make_services(make_fake_app(self.tmp))
        data = bm.manifest_bytes(good_plan()[2])
        cases = {
            "invalid json": (b"{nope", "manifest_invalid"),
            "duplicate keys": (b'{"schema": "a", "schema": "b"}', "manifest_invalid"),
            "bad utf8": (b"\xff\xfe\x00", "manifest_invalid"),
        }
        for label, (content, code) in cases.items():
            path = self.tmp / (label.replace(" ", "_") + ".json")
            path.write_bytes(content)
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                bm.load_manifest(path, services)
            self.assertEqual(raised.exception.code, code)
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_manifest(self.tmp / "missing.json", services)
        self.assertEqual(raised.exception.code, "argument_path_not_found")
        big = self.tmp / "big.json"
        big.write_bytes(data)
        with mock.patch.object(bm, "MAX_MANIFEST_BYTES", 100), self.assertRaises(bm.HelperError) as raised:
            bm.load_manifest(big, services)
        self.assertEqual(raised.exception.code, "manifest_too_large")
        link = self.tmp / "link.json"
        link.symlink_to(big)
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_manifest(link, services)
        self.assertEqual(raised.exception.code, "argument_path_symlink")
        inside = services.target.root / "Contents" / "m.json"
        inside.write_bytes(data)
        with self.assertRaises(bm.HelperError) as raised:
            bm.load_manifest(inside, services)
        self.assertEqual(raised.exception.code, "argument_path_inside_test_app")



# ---------------------------------------------------------------------------
# Shared helpers for verify / stage / run
# ---------------------------------------------------------------------------

def stage_inputs():
    candidate, driver, manifest = good_plan()
    new_files = {
        bm.BUILD_MANAGER_ID: [
            (item.path, item.data, 0o755 if item.mode == "100755" else 0o644)
            for item in sorted(candidate.product, key=lambda item: item.path)
        ],
        bm.DRIVER_ID: [(name, data, 0o644) for name, data in driver.files],
    }
    return manifest, new_files


def install_good(target):
    manifest, new_files = stage_inputs()
    for addon_id, files in new_files.items():
        bm.write_tree(target.addon_dir(addon_id), files)
    return manifest


def install_old(target, label="old"):
    """A different pre-existing install with a stray file and a pycache."""
    for addon_id in (bm.BUILD_MANAGER_ID, bm.DRIVER_ID):
        bm.write_tree(target.addon_dir(addon_id), [
            ("addon.xml", f"<addon id='{addon_id}' version='0.0.1'/>".encode(), 0o644),
            ("default.py", f"# {label} {addon_id}\n".encode(), 0o644),
            ("notes/stray.txt", b"unmanaged leftover\n", 0o600),
            ("resources/lib/__pycache__/x.cpython-310.pyc", b"pyc", 0o644),
        ])


def rebuild_totals(manifest):
    for key in ("build_manager", "driver"):
        tree = manifest[key]
        tree["file_count"] = len(tree["files"])
        tree["total_bytes"] = sum(entry["size"] for entry in tree["files"])
        tree["tree_sha256"] = bm.tree_digest((e["path"], e["sha256"], e["size"]) for e in tree["files"])


class AccessRecorder:
    """Logs (never blocks) every path-taking call that touches given prefixes."""

    FUNCTIONS = FilesystemTripwire.PATH_FUNCTIONS

    def __init__(self, *prefixes):
        self.prefixes = tuple(os.fspath(p) for p in prefixes)
        self.log = []
        self._patches = []

    def _note(self, api, value):
        if isinstance(value, int):
            return
        try:
            text = os.fsdecode(value)
        except Exception:
            return
        if any(text == p or text.startswith(p + "/") for p in self.prefixes):
            self.log.append((api, text))

    def start(self):
        recorder = self
        for module, name, indexes in self.FUNCTIONS + ((os, "scandir", (0,)),):
            original = getattr(module, name)

            def wrapper(*args, __orig=original, __name=name, __idx=indexes, **kwargs):
                for index in __idx:
                    if index < len(args):
                        recorder._note(__name, args[index])
                return __orig(*args, **kwargs)

            patcher = mock.patch.object(module, name, wrapper)
            patcher.start()
            self._patches.append(patcher)
        for module in (builtins, io):
            original = module.open

            def opener(*args, __orig=original, **kwargs):
                if args:
                    recorder._note("open", args[0])
                return __orig(*args, **kwargs)

            patcher = mock.patch.object(module, "open", opener)
            patcher.start()
            self._patches.append(patcher)
        original_connect = sqlite3.connect

        def connect(*args, **kwargs):
            if args:
                target = args[0]
                if isinstance(target, str) and target.startswith("file:"):
                    target = target[5:].split("?", 1)[0]
                    from urllib.parse import unquote
                    target = unquote(target)
                recorder._note("sqlite3.connect", target)
            return original_connect(*args, **kwargs)

        patcher = mock.patch.object(sqlite3, "connect", connect)
        patcher.start()
        self._patches.append(patcher)
        return self

    def stop(self):
        while self._patches:
            self._patches.pop().stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

class TestVerify(TripwireTestCase):
    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)
        self.services = make_services(self.target)
        self.manifest = install_good(self.target)
        self.bm_dir = self.target.addon_dir(bm.BUILD_MANAGER_ID)
        self.driver_dir = self.target.addon_dir(bm.DRIVER_ID)

    def verify(self, manifest=None, git=True):
        return bm.verify_installed(
            self.services, manifest or self.manifest, git_repo=FIXTURE.repo if git else None
        )

    def report(self, result, addon_id=bm.BUILD_MANAGER_ID):
        return result["trees"][addon_id]

    def test_clean_install_equals_manifest_and_candidate(self):
        result = self.verify()
        self.assertTrue(result["installed_equals_manifest"])
        self.assertTrue(result["installed_equals_candidate"])
        self.assertEqual(result["git_binding"]["problems"], [])
        for addon_id, report in result["trees"].items():
            with self.subTest(addon_id=addon_id):
                self.assertTrue(report["ok"])
                self.assertEqual(report["problems"], [])
                self.assertEqual(report["tree_sha256_actual"], report["tree_sha256_expected"])
                self.assertEqual(report["found_file_count"], report["expected_file_count"])
                self.assertEqual(
                    (report["missing_count"], report["unexpected_count"], report["modified_count"]), (0, 0, 0)
                )
        self.assertEqual(self.report(result)["expected_file_count"], self.manifest["build_manager"]["file_count"])

    def test_without_the_git_check_the_candidate_claim_is_withheld(self):
        result = self.verify(git=False)
        self.assertTrue(result["installed_equals_manifest"])
        self.assertFalse(result["installed_equals_candidate"])
        self.assertEqual(result["git_binding"], {"checked": False})

    def test_missing_file(self):
        (self.bm_dir / "resources" / "lib" / "utils.py").unlink()
        result = self.verify()
        report = self.report(result)
        self.assertFalse(result["installed_equals_manifest"] or result["installed_equals_candidate"])
        self.assertEqual(report["missing"], ["resources/lib/utils.py"])
        self.assertIn("missing_files", report["problems"])
        self.assertNotEqual(report["tree_sha256_actual"], report["tree_sha256_expected"])
        self.assertTrue(self.report(result, bm.DRIVER_ID)["ok"])

    def test_unexpected_file_and_directory(self):
        (self.bm_dir / "resources" / "lib" / "evil.py").write_text("print('x')")
        (self.bm_dir / "resources" / "empty_dir").mkdir()
        report = self.report(self.verify())
        self.assertEqual(report["unexpected"], ["resources/lib/evil.py"])
        self.assertEqual(report["unexpected_directories"], ["resources/empty_dir"])
        self.assertIn("unexpected_files", report["problems"])
        self.assertIn("unexpected_directories", report["problems"])

    def test_modified_file_same_size_and_different_size(self):
        service = self.bm_dir / "service.py"
        data = bytearray(service.read_bytes())
        data[0] ^= 1
        service.write_bytes(bytes(data))
        (self.bm_dir / "default.py").write_bytes(b"short")
        report = self.report(self.verify())
        self.assertEqual(report["modified"], ["default.py", "service.py"])
        self.assertIn("modified_files", report["problems"])

    def test_driver_tree_is_checked_too(self):
        (self.driver_dir / "adapter_config.py").write_text("MANIFEST_PATH = 'other'\n")
        result = self.verify()
        self.assertFalse(result["installed_equals_manifest"])
        self.assertEqual(self.report(result, bm.DRIVER_ID)["modified"], ["adapter_config.py"])
        self.assertTrue(self.report(result)["ok"])

    def test_symlinked_file_is_never_followed_even_with_identical_content(self):
        target_file = self.bm_dir / "resources" / "lib" / "utils.py"
        copy_of = self.tmp / "copy-of-utils.py"
        copy_of.write_bytes(target_file.read_bytes())
        target_file.unlink()
        target_file.symlink_to(copy_of)
        report = self.report(self.verify())
        self.assertEqual(report["symlinks"], ["resources/lib/utils.py"])
        self.assertEqual(report["missing"], ["resources/lib/utils.py"])
        self.assertIn("symlinks_present", report["problems"])

    def test_symlinked_directory_escape_is_flagged_and_not_traversed(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("outside secret")
        (self.bm_dir / "resources" / "escape").symlink_to(outside)
        report = self.report(self.verify())
        self.assertEqual(report["symlinks"], ["resources/escape"])
        self.assertNotIn("resources/escape/secret.txt", report["unexpected"])
        self.assertEqual(report["found_file_count"], report["expected_file_count"])

    def test_special_files_are_flagged(self):
        os.mkfifo(self.bm_dir / "resources" / "pipe")
        report = self.report(self.verify())
        self.assertEqual(report["special"], ["resources/pipe"])
        self.assertIn("special_files_present", report["problems"])

    def test_pycache_is_the_only_tolerated_runtime_artifact(self):
        cache = self.bm_dir / "resources" / "lib" / "__pycache__"
        cache.mkdir()
        (cache / "utils.cpython-310.pyc").write_bytes(b"\x00bytecode")
        (cache / "other.cpython-310.opt-1.pyc").write_bytes(b"\x00bytecode")
        (self.bm_dir / "__pycache__").mkdir()
        (self.bm_dir / "__pycache__" / "service.cpython-310.pyc").write_bytes(b"x")
        result = self.verify()
        report = self.report(result)
        self.assertTrue(result["installed_equals_candidate"])
        self.assertEqual((report["ignored_pycache_dirs"], report["ignored_pyc_files"]), (2, 3))

    def test_pycache_cannot_hide_anything_else(self):
        cache = self.bm_dir / "resources" / "lib" / "__pycache__"
        cache.mkdir()
        cases = {
            "notes.txt": lambda p: p.write_text("not bytecode"),
            "has space.pyc": lambda p: p.write_bytes(b"x"),
            "subdir": lambda p: p.mkdir(),
        }
        for name, build in cases.items():
            with self.subTest(entry=name):
                path = cache / name
                build(path)
                report = self.report(self.verify())
                self.assertFalse(report["ok"], name)
                self.assertTrue(
                    report["unexpected"] or report["unexpected_directories"] or report["problems"], name
                )
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
        link = cache / "evil.pyc"
        link.symlink_to(self.tmp / "target.pyc")
        self.assertIn("symlinks_present", self.report(self.verify())["problems"])
        link.unlink()
        shutil.rmtree(cache)
        (self.bm_dir / "__pycache__").write_text("a file named like a cache")
        self.assertEqual(self.report(self.verify())["unexpected"], ["__pycache__"])

    def test_nested_pycache_is_not_tolerated(self):
        nested = self.bm_dir / "__pycache__" / "__pycache__"
        nested.mkdir(parents=True)
        (nested / "x.pyc").write_bytes(b"x")
        self.assertFalse(self.report(self.verify())["ok"])

    def test_install_directory_problems(self):
        shutil.rmtree(self.bm_dir)
        report = self.report(self.verify())
        self.assertIn("addon_dir_missing", report["problems"])
        self.assertEqual(report["missing_count"], report["expected_file_count"])
        self.bm_dir.write_text("a regular file in place of the add-on")
        self.assertIn("addon_dir_not_directory", self.report(self.verify())["problems"])

    def test_symlinked_install_directory_or_ancestor_is_refused(self):
        real = self.tmp / "real-copy"
        shutil.copytree(self.bm_dir, real, symlinks=True)
        shutil.rmtree(self.bm_dir)
        self.bm_dir.symlink_to(real)
        self.assertEqual(self.report(self.verify())["problems"], ["addon_dir_path_symlink"])
        self.bm_dir.unlink()
        shutil.move(str(real), str(self.bm_dir))
        self.assertTrue(self.report(self.verify())["ok"])
        moved = self.target.portable_data / "real_addons"
        self.target.addons_dir.rename(moved)
        self.target.addons_dir.symlink_to(moved)
        result = self.verify()
        for addon_id in (bm.BUILD_MANAGER_ID, bm.DRIVER_ID):
            self.assertEqual(self.report(result, addon_id)["problems"], ["addon_dir_path_symlink"])
        self.assertFalse(result["installed_equals_manifest"])

    def test_unreadable_and_oversized_files_fail_closed(self):
        with mock.patch.object(bm, "MAX_BLOB_BYTES", 10):
            report = self.report(self.verify(git=False))
        self.assertIn("unreadable_files", report["problems"])
        self.assertFalse(report["ok"])

    def test_lists_are_capped_and_flagged(self):
        for index in range(80):
            (self.bm_dir / f"extra{index:03d}.txt").write_text("x")
        report = self.report(self.verify())
        self.assertEqual(report["unexpected_count"], 80)
        self.assertEqual(len(report["unexpected"]), bm.LIST_CAP)
        self.assertTrue(report["lists_truncated"])

    def test_hostile_file_names_are_sanitized_in_the_output(self):
        hostile = "evil\nname\x1b[31m.txt"
        (self.bm_dir / hostile).write_text("x")
        text = bm.canonical_json(self.verify())
        self.assertNotIn("\x1b", text)
        self.assertNotIn("evil", text)
        self.assertIn("<unsafe:", text)

    def test_verification_is_read_only(self):
        before_fp = fingerprint(self.target.root)
        before_times = {p: p.stat().st_mtime_ns for p in self.target.root.rglob("*")}
        self.verify()
        self.verify(git=False)
        self.assertEqual(fingerprint(self.target.root), before_fp)
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.target.root.rglob("*")}, before_times)

    def test_manifest_blob_that_disagrees_with_the_bytes_is_flagged(self):
        manifest = manifest_copy()
        manifest["build_manager"]["files"][0]["git_blob"] = "0" * 40
        result = self.verify(manifest)
        self.assertIn("git_blob_mismatch", self.report(result)["problems"])
        self.assertIn("product_blob_mismatch", result["git_binding"]["problems"])
        self.assertFalse(result["installed_equals_candidate"])

    def test_git_binding_detects_a_manifest_that_does_not_describe_the_commit(self):
        cases = {
            "tree": ("candidate", "tree", "0" * 40, "tree_mismatch"),
            "resources tree": ("candidate", "resources_tree", "0" * 40, "resources_tree_mismatch"),
        }
        for label, (section, key, value, expected) in cases.items():
            manifest = manifest_copy()
            manifest[section][key] = value
            with self.subTest(case=label):
                result = self.verify(manifest)
                self.assertIn(expected, result["git_binding"]["problems"])
                self.assertFalse(result["installed_equals_candidate"])

    def test_git_binding_detects_a_different_product_set(self):
        manifest = manifest_copy()
        manifest["build_manager"]["files"].pop()
        rebuild_totals(manifest)
        bm.validate_manifest(manifest)
        result = self.verify(manifest)
        self.assertIn("product_set_mismatch", result["git_binding"]["problems"])
        self.assertEqual(len(self.report(result)["unexpected"]), 1)

    def test_git_binding_detects_driver_source_blob_drift(self):
        manifest = manifest_copy()
        for entry in manifest["driver"]["files"]:
            if entry["source_git_blob"]:
                entry["source_git_blob"] = "0" * 40
                break
        self.assertIn("driver_source_blob_mismatch", self.verify(manifest)["git_binding"]["problems"])

    def test_git_binding_reports_missing_commit_or_git_failure(self):
        manifest = manifest_copy()
        manifest["candidate"]["commit"] = "1" * 40
        result = self.verify(manifest)
        self.assertEqual(result["git_binding"], {"checked": True, "ok": False, "problems": ["candidate_commit_missing"]})
        self.services.git_exe = None
        result = self.verify()
        self.assertEqual(result["git_binding"]["problems"], ["candidate_git_unavailable"])
        self.assertFalse(result["installed_equals_candidate"])


# ---------------------------------------------------------------------------
# stage
# ---------------------------------------------------------------------------

class StageTestCase(TripwireTestCase):
    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)
        self.lister = FakeProcessLister()
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir()
        self.evidence = self.tmp / "evidence"
        self.evidence.mkdir()
        self.services = make_services(self.target, process_lister=self.lister, tmp_root=self.scratch)
        self.config = {"adapter": dict(ADAPTER_VALUES), "rpc": {}}
        self.ids = (bm.BUILD_MANAGER_ID, bm.DRIVER_ID)

    def stage(self, *, dry_run=False, candidate=None, evidence="default", repo=None):
        return bm.run_stage(
            self.services,
            candidate_id=candidate or FIXTURE.good,
            config=self.config,
            repo=repo or FIXTURE.repo,
            evidence_dir=self.evidence if evidence == "default" else evidence,
            dry_run=dry_run,
        )

    def live_fingerprints(self):
        return {
            addon_id: (fingerprint(self.target.addon_dir(addon_id))
                       if (self.target.addons_dir / addon_id).exists() else None)
            for addon_id in self.ids
        }

    def run_dirs(self):
        return sorted(self.evidence.iterdir())

    def stage_area(self):
        return self.target.stage_area


class TestStage(StageTestCase):
    def test_hostile_tmpdir_cannot_redirect_workspace(self):
        decoy = self.target.root / "hostile-temp"
        decoy.mkdir()
        self.services.tmp_root = None  # exercise the production fallback
        original = bm.build_driver
        roots = []
        def observe(candidate, values, workspace, *args):
            roots.append(workspace.parent)
            return original(candidate, values, workspace, *args)
        with mock.patch.dict(os.environ, TMPDIR=str(decoy)), mock.patch.object(tempfile, "tempdir", None), \
                mock.patch.object(bm, "build_driver", side_effect=observe):
            self.stage(dry_run=True)
        self.assertEqual(roots, [Path("/private/tmp")])
        self.assertEqual(list(decoy.iterdir()), [])

    def test_workspace_root_must_pass_policy_before_creation(self):
        for root in ("/.vol/1/2", "//Applications/Kodi.app/tmp", str(self.target.root)):
            self.services.tmp_root = Path(root)
            with mock.patch.object(bm.tempfile, "mkdtemp", side_effect=AssertionError("workspace I/O")):
                with self.assertRaises(bm.HelperError):
                    self.stage(dry_run=True)
        link = self.tmp / "temp-link"
        link.symlink_to(self.scratch)
        self.services.tmp_root = link
        with self.assertRaises(bm.HelperError) as raised:
            self.stage(dry_run=True)
        self.assertEqual(raised.exception.code, "argument_path_symlink")

    def test_internal_bundle_symlink_ancestors_fail_before_stage_mutation(self):
        for relative in ("Resources", "Resources/Kodi"):
            with self.subTest(relative=relative):
                target = make_fake_app(self.tmp / relative.replace("/", "-"))
                victim = target.contents_dir / relative
                decoy = self.tmp / (relative.replace("/", "-") + "-decoy")
                victim.rename(decoy)
                victim.symlink_to(decoy)
                before = fingerprint(decoy)
                self.services.target = target
                with self.assertRaises(bm.HelperError) as raised:
                    self.stage()
                self.assertEqual(raised.exception.code, "bundle_path_symlink")
                self.assertEqual(fingerprint(decoy), before)
                self.assertFalse((decoy / "portable_data/.bm-stage").exists())
                self.assertEqual(self.run_dirs(), [])

    def test_pre_swap_rejected_ancestor_is_preserved_during_failure_cleanup(self):
        target = self.target
        resources = target.contents_dir / "Resources"
        decoy = self.tmp / "relocated-resources"
        original_swap = bm._swap_in
        injected_state = []

        def inject_ancestor_symlink(target, area, addon_ids):
            resources.rename(decoy)
            resources.symlink_to(decoy, target_is_directory=True)
            relocated_area = decoy / "Kodi" / "portable_data" / ".bm-stage"
            sentinel = relocated_area / "review-sentinel.txt"
            sentinel.write_text("preserve me")
            injected_state.append((relocated_area.is_dir(), sentinel.exists()))
            return original_swap(target, area, addon_ids)

        with mock.patch.object(bm, "_swap_in", side_effect=inject_ancestor_symlink), \
                mock.patch.object(bm, "_remove_stage_area", wraps=bm._remove_stage_area) as cleanup:
            with self.assertRaises(bm.HelperError) as raised:
                self.stage()

        self.assertEqual(raised.exception.code, "bundle_path_symlink")
        cleanup.assert_called_once_with(target, discard_old=False)
        relocated_area = decoy / "Kodi" / "portable_data" / ".bm-stage"
        sentinel = relocated_area / "review-sentinel.txt"
        self.assertEqual(injected_state, [(True, True)])
        self.assertTrue(resources.is_symlink())
        self.assertTrue(sentinel.exists(), "failure cleanup deleted the relocated stage sentinel")
        self.assertTrue(relocated_area.is_dir())
        self.assertEqual(sentinel.read_text(), "preserve me")

        resources.unlink()
        decoy.rename(resources)
        self.services.clock.now_ns += 10 * 10 ** 9
        with self.assertRaises(bm.HelperError) as raised:
            self.stage()
        self.assertEqual(raised.exception.code, "stage_area_exists")
        self.assertEqual((target.stage_area / "review-sentinel.txt").read_text(), "preserve me")

    def test_backup_swap_race_preserves_unrecorded_old_bytes_and_blocks_next_stage(self):
        for existed in (True, False):
            with self.subTest(existed=existed):
                # Separate fixture for an existing and newly appeared live tree.
                target = make_fake_app(self.tmp / str(existed))
                self.target = target
                self.services.target = target
                if existed:
                    install_old(target)
                original = bm._swap_in
                def inject(target, area, ids):
                    live = target.addon_dir(bm.BUILD_MANAGER_ID)
                    live.mkdir(exist_ok=True)
                    (live / "race.txt").write_bytes(b"unrecorded live bytes")
                    return original(target, area, ids)
                with mock.patch.object(bm, "_swap_in", side_effect=inject):
                    with self.assertRaises(bm.HelperError) as raised:
                        self.stage()
                self.assertEqual(raised.exception.code, "stage_backup_failed")
                old = self.stage_area() / "old" / bm.BUILD_MANAGER_ID
                self.assertEqual((old / "race.txt").read_bytes(), b"unrecorded live bytes")
                run_dir = self.run_dirs()[-1]
                self.assertTrue((run_dir / "stage_manifest.json").is_file())
                record = json.loads((run_dir / "stage_result.json").read_text())
                self.assertFalse(record["ok"])
                self.assertFalse(any((run_dir / "replaced").rglob("race.txt")))
                self.services.clock.now_ns += 10 * 10 ** 9
                with self.assertRaises(bm.HelperError) as raised:
                    self.stage()
                self.assertEqual(raised.exception.code, "stage_area_exists")
                self.assertEqual((old / "race.txt").read_bytes(), b"unrecorded live bytes")
                self.services.clock.now_ns += 10 * 10 ** 9

    def test_dry_run_builds_and_reports_but_changes_nothing(self):
        before = fingerprint(self.target.root)
        payload = self.stage(dry_run=True, evidence=None)
        self.assertTrue(payload["ok"] and payload["dry_run"])
        self.assertEqual(payload["would_replace"], {bm.BUILD_MANAGER_ID: False, bm.DRIVER_ID: False})
        self.assertEqual(fingerprint(self.target.root), before)
        self.assertEqual(self.run_dirs(), [])
        self.assertEqual(list(self.scratch.iterdir()), [])
        expected = copy.deepcopy(good_plan()[2])
        expected["created_utc"] = payload["manifest"]["created_utc"]
        self.assertEqual(payload["manifest"], expected)

    def test_dry_run_reports_what_it_would_replace(self):
        install_old(self.target)
        payload = self.stage(dry_run=True)
        self.assertEqual(payload["would_replace"], {bm.BUILD_MANAGER_ID: True, bm.DRIVER_ID: True})

    def test_fresh_stage_installs_exactly_the_candidate_and_binds_the_manifest(self):
        payload = self.stage()
        self.assertTrue(payload["ok"])
        (run_dir,) = self.run_dirs()
        self.assertRegex(run_dir.name, r"^stage-\d{8}T\d{6}Z-" + FIXTURE.good[:12] + "$")
        manifest_file = run_dir / "stage_manifest.json"
        self.assertEqual(manifest_file.read_bytes(), bm.manifest_bytes(payload["manifest"]))
        for evidence_file in (manifest_file, run_dir / "stage_result.json"):
            self.assertEqual(stat.S_IMODE(evidence_file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
        self.assertEqual(payload["manifest_sha256"], hashlib.sha256(manifest_file.read_bytes()).hexdigest())
        self.assertEqual(json.loads((run_dir / "stage_result.json").read_text())["ok"], True)
        result = bm.verify_installed(self.services, payload["manifest"], git_repo=FIXTURE.repo)
        self.assertTrue(result["installed_equals_candidate"])
        self.assertEqual(payload["post_stage_verify"]["installed_equals_manifest"], True)
        self.assertEqual(payload["replaced"], {a: {"backed_up": False, "existed": False} for a in self.ids})
        self.assertTrue(payload["stage_area_removed"])
        self.assertFalse(self.stage_area().exists())

    def test_only_the_runtime_product_set_is_staged(self):
        payload = self.stage()
        staged = {e.rel for e in bm.walk_tree(self.target.addon_dir(bm.BUILD_MANAGER_ID)) if e.kind == "file"}
        self.assertEqual(staged, {e["path"] for e in payload["manifest"]["build_manager"]["files"]})
        for path in staged:
            self.assertTrue(path in bm.PRODUCT_ROOT_FILES or path.startswith("resources/"), path)
        for excluded in (".agent", ".orchestrator", "tests", "docs", "tools", "README.md", "LICENSE.txt"):
            self.assertFalse((self.target.addon_dir(bm.BUILD_MANAGER_ID) / excluded).exists(), excluded)
        driver = {e.rel for e in bm.walk_tree(self.target.addon_dir(bm.DRIVER_ID))}
        self.assertEqual(driver, set(bm.DRIVER_FILES))

    def test_staged_bytes_come_from_git_objects_not_the_working_tree(self):
        victim = FIXTURE.repo / "resources" / "lib" / "utils.py"
        original = victim.read_bytes()
        evil = FIXTURE.repo / "resources" / "lib" / "untracked_evil.py"
        try:
            victim.write_bytes(original + b"\n# DIRTY\n")
            evil.write_bytes(b"print('evil')\n")
            self.stage()
        finally:
            victim.write_bytes(original)
            evil.unlink(missing_ok=True)
        live = self.target.addon_dir(bm.BUILD_MANAGER_ID)
        self.assertNotIn(b"# DIRTY", (live / "resources/lib/utils.py").read_bytes())
        self.assertFalse((live / "resources/lib/untracked_evil.py").exists())
        blob = git(FIXTURE.repo, "cat-file", "blob", FIXTURE.good + ":resources/lib/utils.py")
        self.assertEqual((live / "resources/lib/utils.py").read_bytes(), blob)

    def test_staging_from_a_checkout_that_is_not_the_candidate(self):
        other = variant("other-head", [("100644", "resources/lib/utils.py", b"# a different commit\n")])
        git(FIXTURE.repo, "checkout", "-q", "--detach", other)
        try:
            self.stage()
        finally:
            git(FIXTURE.repo, "checkout", "-q", "--detach", FIXTURE.good)
        staged = (self.target.addon_dir(bm.BUILD_MANAGER_ID) / "resources/lib/utils.py").read_bytes()
        self.assertNotEqual(staged, b"# a different commit\n")

    def test_existing_install_is_backed_up_verified_and_replaced(self):
        install_old(self.target)
        before = self.live_fingerprints()
        payload = self.stage()
        (run_dir,) = self.run_dirs()
        for addon_id in self.ids:
            info = payload["replaced"][addon_id]
            backup = Path(info["backup_dir"])
            self.assertTrue(info["backed_up"] and info["existed"])
            self.assertEqual(backup, run_dir / "replaced" / addon_id)
            self.assertEqual(fingerprint(backup), before[addon_id])
            self.assertEqual(info["backup_tree_digest"], before[addon_id]["digest"])
            self.assertFalse(bm.is_inside(backup, self.target.root), "evidence must live outside the app")
            self.assertTrue((backup / "notes" / "stray.txt").exists())
            self.assertTrue((backup / "resources/lib/__pycache__/x.cpython-310.pyc").exists())
        self.assertTrue(bm.verify_installed(self.services, payload["manifest"], git_repo=None)["installed_equals_manifest"])

    def test_restaging_keeps_every_earlier_backup(self):
        install_old(self.target)
        self.stage()
        self.services.clock.now_ns += 10 * 10 ** 9
        second = self.stage()
        self.assertEqual(len(self.run_dirs()), 2)
        self.assertTrue(all(i["backed_up"] for i in second["replaced"].values()))
        for run_dir in self.run_dirs():
            self.assertTrue((run_dir / "replaced").is_dir())

    def test_refuses_whenever_the_test_app_is_not_cleanly_stopped(self):
        scenarios = {
            "running": lambda: self.lister.run_test_app(self.target, pid=11),
            "not portable": lambda: self.lister.run_test_app(self.target, pid=12, flags=""),
            "two processes": lambda: (self.lister.run_test_app(self.target, pid=13),
                                      self.lister.run_test_app(self.target, pid=14)),
            "normal kodi": lambda: self.lister.processes.append(
                bm.ProcessInfo(15, "/Applications/Kodi.app/Contents/MacOS/Kodi")),
        }
        expected = {
            "running": "test_app_running", "not portable": "test_app_not_portable",
            "two processes": "multiple_test_app_processes", "normal kodi": "foreign_kodi_process_present",
        }
        install_old(self.target)
        for label, arrange in scenarios.items():
            self.lister.processes.clear()
            self.lister.commands.clear()
            arrange()
            before = fingerprint(self.target.root)
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                self.stage()
            self.assertEqual(raised.exception.code, expected[label])
            self.assertEqual(fingerprint(self.target.root), before)
            self.assertEqual(self.run_dirs(), [])
            self.assertEqual(list(self.scratch.iterdir()), [])

    def test_a_launch_between_the_build_and_the_swap_is_caught_and_rolled_back(self):
        install_old(self.target)
        before = self.live_fingerprints()
        lister = self.lister
        original = lister.list_all
        calls = []

        def launch_after_first_check():
            calls.append(1)
            if len(calls) > 1 and not lister.processes:
                lister.run_test_app(self.target, pid=77)
            return original()

        lister.list_all = launch_after_first_check
        with self.assertRaises(bm.HelperError) as raised:
            self.stage()
        self.assertEqual(raised.exception.code, "test_app_running")
        self.assertEqual(self.live_fingerprints(), before)
        self.assertFalse(self.stage_area().exists())
        (run_dir,) = self.run_dirs()
        self.assertTrue((run_dir / "stage_manifest.json").exists())
        result = json.loads((run_dir / "stage_result.json").read_text())
        self.assertEqual((result["ok"], result["error"]["code"]), (False, "test_app_running"))
        self.assertTrue((run_dir / "replaced" / bm.BUILD_MANAGER_ID).is_dir())  # evidence kept

    def test_layout_problems_refuse_before_any_work(self):
        for label, kwargs, code in (
            ("no portable_data", {"portable": False}, "layout_missing"),
            ("no addons", {"addons": False}, "layout_missing"),
        ):
            base = self.tmp / ("layout-" + label.replace(" ", "-"))
            base.mkdir()
            target = make_fake_app(base, **kwargs)
            services = make_services(target, tmp_root=self.scratch)
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                bm.run_stage(services, candidate_id=FIXTURE.good, config=self.config,
                             repo=FIXTURE.repo, evidence_dir=self.evidence, dry_run=False)
            self.assertEqual(raised.exception.code, code)
        base = self.tmp / "layout-symlink"
        base.mkdir()
        target = make_fake_app(base)
        moved = target.portable_data / "real_addons"
        target.addons_dir.rename(moved)
        target.addons_dir.symlink_to(moved)
        with self.assertRaises(bm.HelperError) as raised:
            bm.run_stage(make_services(target, tmp_root=self.scratch), candidate_id=FIXTURE.good,
                         config=self.config, repo=FIXTURE.repo, evidence_dir=self.evidence, dry_run=False)
        self.assertEqual(raised.exception.code, "bundle_path_symlink")

    def test_a_stale_stage_area_blocks_and_is_left_untouched(self):
        install_old(self.target)
        precious = self.stage_area() / "old" / "script.build.manager"
        precious.mkdir(parents=True)
        (precious / "irreplaceable.txt").write_text("only copy")
        before_area = fingerprint(self.stage_area())
        before_live = self.live_fingerprints()
        with self.assertRaises(bm.HelperError) as raised:
            self.stage()
        self.assertEqual(raised.exception.code, "stage_area_exists")
        self.assertEqual(fingerprint(self.stage_area()), before_area)
        self.assertEqual(self.live_fingerprints(), before_live)

    def test_evidence_directory_problems(self):
        self.stage(dry_run=True, evidence=None)  # dry run needs none
        with self.assertRaises(bm.HelperError) as raised:
            self.stage(evidence=None)
        self.assertEqual(raised.exception.code, "evidence_dir_invalid")
        with self.assertRaises(bm.HelperError) as raised:
            self.stage(evidence=self.tmp / "no-such-dir")
        self.assertEqual(raised.exception.code, "evidence_dir_invalid")
        plain = self.tmp / "a-file"
        plain.write_text("x")
        with self.assertRaises(bm.HelperError):
            self.stage(evidence=plain)
        alias = self.tmp / "alias"
        alias.symlink_to(self.evidence)
        with self.assertRaises(bm.HelperError):
            self.stage(evidence=alias)
        self.assertEqual(fingerprint(self.target.addons_dir)["files"], 0)

    def test_evidence_run_directory_collision_is_refused_before_any_change(self):
        install_old(self.target)
        before = self.live_fingerprints()
        stamp = bm.iso_utc(self.services.clock.utcnow()).replace("-", "").replace(":", "")
        (self.evidence / f"stage-{stamp}-{FIXTURE.good[:12]}").mkdir()
        with self.assertRaises(bm.HelperError) as raised:
            self.stage()
        self.assertEqual(raised.exception.code, "evidence_exists")
        self.assertEqual(self.live_fingerprints(), before)

    def test_candidate_errors_fail_before_any_mutation_and_clean_the_workspace(self):
        install_old(self.target)
        before = fingerprint(self.target.root)
        for candidate, code in (
            ("0" * 40, "candidate_commit_missing"), (FIXTURE.good[:8], "candidate_id_invalid"),
            ("master", "candidate_id_invalid"),
        ):
            with self.subTest(candidate=candidate), self.assertRaises(bm.HelperError) as raised:
                self.stage(candidate=candidate)
            self.assertEqual(raised.exception.code, code)
        with mock.patch.object(bm, "export_candidate", side_effect=bm.HelperError("candidate_export_failed")):
            with self.assertRaises(bm.HelperError) as raised:
                self.stage()
        self.assertEqual(raised.exception.code, "candidate_export_failed")
        failing = variant("builder-exit-3", [("100644", "tools/build_bm023a_adapter.py", patched_builder(
            "def main() -> int:\n", "def main() -> int:\n    raise SystemExit(3)\n"))])
        with self.assertRaises(bm.HelperError) as raised:
            self.stage(candidate=failing)
        self.assertEqual(raised.exception.code, "driver_build_failed")
        self.assertEqual(fingerprint(self.target.root), before)
        self.assertEqual(self.run_dirs(), [])
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_missing_adapter_config_section_is_refused(self):
        self.config["adapter"] = None
        with self.assertRaises(bm.HelperError) as raised:
            self.stage()
        self.assertEqual(raised.exception.code, "config_missing_section")

    def test_stage_never_touches_userdata(self):
        userdata = self.target.userdata_dir
        (userdata / "addon_data" / "plugin.video.redlight").mkdir(parents=True)
        (userdata / "addon_data" / "plugin.video.redlight" / "settings.xml").write_text(SENTINEL_PRIVATE)
        (userdata / "addon_data" / bm.BUILD_MANAGER_ID).mkdir()
        (userdata / "addon_data" / bm.BUILD_MANAGER_ID / "frozen_install_transaction.json").write_text("{}")
        before = fingerprint(userdata)
        with AccessRecorder(userdata) as recorder:
            self.stage()
        # Only the directory entry itself may be lstat'ed (layout report);
        # nothing beneath it is ever opened, listed, or stat'ed.
        beneath = [entry for entry in recorder.log if entry[1] != os.fspath(userdata)]
        self.assertEqual(beneath, [])
        self.assertEqual({api for api, _ in recorder.log}, {"lstat"})
        self.assertEqual(fingerprint(userdata), before)

    def test_staging_area_shares_a_filesystem_and_all_renames_stay_inside_the_app(self):
        install_old(self.target)
        renames = []
        original = os.rename

        def spy(src, dst, *args, **kwargs):
            renames.append((os.fspath(src), os.fspath(dst)))
            return original(src, dst, *args, **kwargs)

        with mock.patch.object(os, "rename", spy):
            self.stage()
        self.assertEqual(len(renames), 4)  # live->old and new->live for both add-ons
        for source, destination in renames:
            self.assertTrue(bm.is_inside(source, self.target.portable_data), source)
            self.assertTrue(bm.is_inside(destination, self.target.portable_data), destination)
        self.assertEqual(
            os.stat(self.target.portable_data).st_dev, os.stat(self.target.addons_dir).st_dev
        )

    def test_modes_of_staged_files(self):
        self.stage()
        live = self.target.addon_dir(bm.BUILD_MANAGER_ID)
        for entry in bm.walk_tree(live):
            expected = 0o644 if entry.kind == "file" else 0o755
            self.assertEqual(stat.S_IMODE((live / entry.rel).stat().st_mode), expected, entry.rel)

    def test_outputs_and_evidence_never_contain_machine_local_values(self):
        payload = self.stage()
        texts = [bm.canonical_json(payload)]
        for path in self.evidence.rglob("*"):
            if path.is_file() and "replaced" not in path.parts:
                texts.append(path.read_text())
        for text in texts:
            for key, value in ADAPTER_VALUES.items():
                self.assertNotIn(value, text, key)

    def test_a_staging_area_on_another_device_is_refused_before_anything_moves(self):
        install_old(self.target)
        before = self.live_fingerprints()
        with mock.patch.object(bm, "_same_device", return_value=False):
            with self.assertRaises(bm.HelperError) as raised:
                self.stage()
        self.assertEqual(raised.exception.code, "stage_area_invalid")
        self.assertEqual(raised.exception.detail["reason"], "cross_device")
        self.assertEqual(self.live_fingerprints(), before)
        self.assertFalse(self.stage_area().exists())

    def test_same_device_check_is_real(self):
        self.assertTrue(bm._same_device(self.target.portable_data, self.target.addons_dir))
        self.assertFalse(bm._same_device(self.target.portable_data, self.tmp / "no-such-path"))

    def test_evidence_directory_overlapping_a_config_value_is_refused_up_front(self):
        overlapping = Path(ADAPTER_VALUES["ARTIFACT_ROOT"])
        self.services.secrets.register(os.fspath(overlapping), minimum=8)
        base = self.tmp / "overlap-base"
        base.mkdir()
        self.services.secrets.register(os.fspath(base), minimum=8)
        before = fingerprint(self.target.root)
        with self.assertRaises(bm.HelperError) as raised:
            self.stage(evidence=base)
        self.assertEqual(raised.exception.code, "evidence_dir_invalid")
        self.assertEqual(raised.exception.detail["reason"], "overlaps_config_value")
        self.assertEqual(fingerprint(self.target.root), before)
        self.assertEqual(list(base.iterdir()), [])

    def test_stage_never_prompts_for_credentials(self):
        self.services.password_prompt = lambda prompt: self.fail("stage must not prompt")
        self.stage()


class TestStageFailureInjection(StageTestCase):
    """Every failure leaves the live add-ons byte-identical and evidence intact."""

    def setUp(self):
        super().setUp()
        self.manifest, self.new_files = stage_inputs()
        self.run_dir = self.evidence / "run"
        self.run_dir.mkdir()

    def apply(self):
        return bm._apply_stage(self.services, self.manifest, self.new_files, self.run_dir, self.ids)

    def fail_rename(self, predicate, error=None):
        original = os.rename
        error = error or OSError(errno.EIO, "injected rename failure")

        def faulty(src, dst, *args, **kwargs):
            if predicate(os.fspath(src), os.fspath(dst)):
                raise error
            return original(src, dst, *args, **kwargs)

        return mock.patch.object(os, "rename", faulty)

    def assertUnchanged(self, before):
        self.assertEqual(self.live_fingerprints(), before)

    def test_success_replaces_and_clears_the_area(self):
        install_old(self.target)
        result = self.apply()
        self.assertTrue(result["post_stage_verify"]["installed_equals_manifest"])
        self.assertTrue(result["stage_area_removed"])
        self.assertFalse(self.stage_area().exists())

    def test_write_failure_leaves_everything_untouched(self):
        install_old(self.target)
        before = self.live_fingerprints()
        original = bm.write_new_file
        calls = []

        def flaky(path, data, mode=0o644):
            calls.append(path)
            if len(calls) == 5:
                raise OSError(errno.ENOSPC, "disk full")
            return original(path, data, mode)

        with mock.patch.object(bm, "write_new_file", flaky), self.assertRaises(bm.HelperError) as raised:
            self.apply()
        self.assertEqual(raised.exception.code, "stage_write_failed")
        self.assertUnchanged(before)
        self.assertFalse(self.stage_area().exists())
        self.assertFalse((self.run_dir / "replaced").exists())

    def test_a_corrupted_new_tree_is_caught_before_anything_moves(self):
        install_old(self.target)
        before = self.live_fingerprints()
        original = bm.write_new_file

        def corrupting(path, data, mode=0o644):
            if os.fspath(path).endswith("/new/script.build.manager/service.py"):
                data = data + b"# corrupted\n"
            return original(path, data, mode)

        with mock.patch.object(bm, "write_new_file", corrupting), self.assertRaises(bm.HelperError) as raised:
            self.apply()
        self.assertEqual(raised.exception.code, "stage_new_tree_mismatch")
        self.assertUnchanged(before)
        self.assertFalse((self.run_dir / "replaced").exists())
        self.assertFalse(self.stage_area().exists())

    def test_backup_failures_stop_before_the_swap(self):
        install_old(self.target)
        before = self.live_fingerprints()
        with mock.patch.object(bm, "copy_tree_exact", side_effect=OSError(errno.EIO, "copy failed")):
            with self.assertRaises(bm.HelperError) as raised:
                self.apply()
        self.assertEqual(raised.exception.code, "stage_backup_failed")
        self.assertUnchanged(before)
        self.assertFalse(self.stage_area().exists())
        original = bm.fingerprint_tree
        calls = []

        def disagreeing(root):
            calls.append(root)
            result = original(root)
            if len(calls) % 2 == 0:
                result = dict(result, digest="0" * 64)
            return result

        run_two = self.evidence / "run2"
        run_two.mkdir()
        with mock.patch.object(bm, "fingerprint_tree", disagreeing), self.assertRaises(bm.HelperError) as raised:
            bm._apply_stage(self.services, self.manifest, self.new_files, run_two, self.ids)
        self.assertEqual(raised.exception.code, "stage_backup_failed")
        self.assertUnchanged(before)

    def test_special_files_make_the_backup_fail_closed(self):
        install_old(self.target)
        os.mkfifo(self.target.addon_dir(bm.BUILD_MANAGER_ID) / "pipe")
        before = self.live_fingerprints()
        with self.assertRaises(bm.HelperError) as raised:
            self.apply()
        self.assertEqual(raised.exception.code, "stage_backup_failed")
        self.assertUnchanged(before)

    def test_first_rename_failure(self):
        install_old(self.target)
        before = self.live_fingerprints()
        live = os.fspath(self.target.addon_dir(bm.BUILD_MANAGER_ID))
        with self.fail_rename(lambda src, dst: src == live), self.assertRaises(bm.HelperError) as raised:
            self.apply()
        self.assertEqual(raised.exception.code, "stage_swap_failed")
        self.assertUnchanged(before)
        self.assertFalse(self.stage_area().exists())

    def test_second_rename_failure_restores_the_moved_aside_tree(self):
        install_old(self.target)
        before = self.live_fingerprints()
        with self.fail_rename(lambda src, dst: src.endswith("/new/" + bm.BUILD_MANAGER_ID)):
            with self.assertRaises(bm.HelperError) as raised:
                self.apply()
        self.assertEqual(raised.exception.code, "stage_swap_failed")
        self.assertUnchanged(before)
        self.assertFalse(self.stage_area().exists())

    def test_failure_on_the_second_addon_rolls_back_the_first_too(self):
        install_old(self.target)
        before = self.live_fingerprints()
        with self.fail_rename(lambda src, dst: src.endswith("/new/" + bm.DRIVER_ID)):
            with self.assertRaises(bm.HelperError) as raised:
                self.apply()
        self.assertEqual(raised.exception.code, "stage_swap_failed")
        self.assertUnchanged(before)
        self.assertFalse(self.stage_area().exists())

    def test_fresh_install_failure_leaves_no_partial_install(self):
        with self.fail_rename(lambda src, dst: src.endswith("/new/" + bm.DRIVER_ID)):
            with self.assertRaises(bm.HelperError):
                self.apply()
        self.assertEqual(list(self.target.addons_dir.iterdir()), [])
        self.assertFalse(self.stage_area().exists())

    def test_post_verification_failure_rolls_everything_back(self):
        install_old(self.target)
        before = self.live_fingerprints()
        bogus = {"installed_equals_manifest": False, "trees": {}}
        with mock.patch.object(bm, "verify_installed", return_value=bogus):
            with self.assertRaises(bm.HelperError) as raised:
                self.apply()
        self.assertEqual(raised.exception.code, "stage_post_verify_failed")
        self.assertUnchanged(before)
        self.assertFalse(self.stage_area().exists())

    def test_interrupt_during_the_swap_rolls_back_and_propagates(self):
        install_old(self.target)
        before = self.live_fingerprints()
        count = []
        original = os.rename

        def interrupting(src, dst, *args, **kwargs):
            count.append(1)
            if len(count) == 2:
                raise KeyboardInterrupt
            return original(src, dst, *args, **kwargs)

        with mock.patch.object(os, "rename", interrupting), self.assertRaises(KeyboardInterrupt):
            self.apply()
        self.assertUnchanged(before)
        self.assertFalse(self.stage_area().exists())

    def test_interrupt_right_after_a_rename_is_still_rolled_back(self):
        # The step is recorded before the rename, so a late interrupt cannot
        # strand a moved-aside tree.
        install_old(self.target)
        before = self.live_fingerprints()
        original = os.rename
        count = []

        def interrupt_after(src, dst, *args, **kwargs):
            result = original(src, dst, *args, **kwargs)
            count.append(1)
            if len(count) == 1:
                raise KeyboardInterrupt
            return result

        with mock.patch.object(os, "rename", interrupt_after), self.assertRaises(KeyboardInterrupt):
            self.apply()
        self.assertUnchanged(before)

    def test_rollback_failure_preserves_the_moved_aside_tree(self):
        install_old(self.target)
        before = self.live_fingerprints()
        bm_fp = before[bm.BUILD_MANAGER_ID]

        def predicate(src, dst):
            return src.endswith("/new/" + bm.DRIVER_ID) or "/old/" in src

        with self.fail_rename(predicate), self.assertRaises(bm.HelperError) as raised:
            self.apply()
        self.assertEqual(raised.exception.code, "rollback_failed")
        self.assertGreaterEqual(raised.exception.detail["failed_steps"], 1)
        preserved = self.stage_area() / "old" / bm.BUILD_MANAGER_ID
        self.assertTrue(preserved.is_dir(), "the replaced tree must survive a failed rollback")
        self.assertEqual(fingerprint(preserved), bm_fp)
        # and so does the independent evidence copy
        self.assertEqual(fingerprint(self.run_dir / "replaced" / bm.BUILD_MANAGER_ID), bm_fp)

    def test_backup_recheck_failure_after_the_swap_keeps_the_old_trees(self):
        install_old(self.target)
        before = self.live_fingerprints()
        with mock.patch.object(bm, "_recheck_backups", side_effect=bm.HelperError("stage_backup_failed")):
            with self.assertRaises(bm.HelperError) as raised:
                self.apply()
        self.assertEqual(raised.exception.code, "stage_backup_failed")
        for addon_id in self.ids:
            self.assertEqual(fingerprint(self.stage_area() / "old" / addon_id), before[addon_id])
        self.assertTrue(bm.verify_installed(self.services, self.manifest, git_repo=None)["installed_equals_manifest"])

    def test_remove_stage_area_is_gated_on_old_being_empty(self):
        (self.stage_area() / "old" / "x").mkdir(parents=True)
        (self.stage_area() / "old" / "x" / "f").write_text("keep")
        self.assertFalse(bm._remove_stage_area(self.target, discard_old=False))
        self.assertTrue(self.stage_area().exists())
        self.assertTrue(bm._remove_stage_area(self.target, discard_old=True))
        self.assertFalse(self.stage_area().exists())
        (self.stage_area() / "old").mkdir(parents=True)
        self.assertTrue(bm._remove_stage_area(self.target, discard_old=False))

    def test_remove_stage_area_never_follows_a_symlink(self):
        precious = self.tmp / "precious"
        precious.mkdir()
        (precious / "keep.txt").write_text("keep")
        self.stage_area().symlink_to(precious)
        self.assertFalse(bm._remove_stage_area(self.target, discard_old=True))
        self.assertTrue((precious / "keep.txt").exists())

    def test_failure_records_stage_result_evidence(self):
        payload = {"candidate": self.manifest["candidate"], "manifest_sha256": "a" * 64}
        bm._record_stage_failure(self.run_dir, payload, bm.HelperError("stage_swap_failed"))
        record = json.loads((self.run_dir / "stage_result.json").read_text())
        self.assertEqual((record["ok"], record["error"]["code"]), (False, "stage_swap_failed"))
        other = self.evidence / "other"
        other.mkdir()
        bm._record_stage_failure(other, payload, KeyboardInterrupt())
        self.assertEqual(json.loads((other / "stage_result.json").read_text())["error"]["code"], "interrupted")
        bm._record_stage_failure(other, payload, RuntimeError("never raised"))  # best effort: no exception

    def test_a_concurrent_stage_is_excluded_by_the_exclusive_area(self):
        self.stage_area().mkdir()
        with self.assertRaises(bm.HelperError) as raised:
            self.apply()
        self.assertEqual(raised.exception.code, "stage_area_exists")
        self.assertTrue(self.stage_area().is_dir())


class TestStageHelpers(TripwireTestCase):
    def test_copy_tree_exact_preserves_modes_times_and_symlinks_without_following(self):
        source = self.tmp / "src"
        (source / "sub").mkdir(parents=True)
        (source / "a.txt").write_bytes(b"alpha")
        os.chmod(source / "a.txt", 0o640)
        os.utime(source / "a.txt", ns=(10 ** 18, 10 ** 18))
        (source / "sub" / "b.txt").write_bytes(b"beta")
        outside = self.tmp / "outside.txt"
        outside.write_text("outside")
        (source / "link").symlink_to(outside)
        destination = self.tmp / "dst"
        bm.copy_tree_exact(source, destination)
        self.assertEqual(bm.fingerprint_tree(source), bm.fingerprint_tree(destination))
        self.assertEqual(stat.S_IMODE((destination / "a.txt").stat().st_mode), 0o640)
        self.assertEqual((destination / "a.txt").stat().st_mtime_ns, 10 ** 18)
        self.assertTrue((destination / "link").is_symlink())
        self.assertEqual(os.readlink(destination / "link"), str(outside))
        with self.assertRaises(OSError):
            bm.copy_tree_exact(source, destination)  # never merges into an existing tree

    def test_fingerprint_distinguishes_content_symlink_targets_and_special_files(self):
        base = self.tmp / "fp"
        base.mkdir()
        (base / "f").write_text("x")
        first = bm.fingerprint_tree(base)
        (base / "f").write_text("y")
        self.assertNotEqual(first["digest"], bm.fingerprint_tree(base)["digest"])
        (base / "f").write_text("x")
        self.assertEqual(first["digest"], bm.fingerprint_tree(base)["digest"])
        (base / "l").symlink_to("one")
        with_link = bm.fingerprint_tree(base)
        (base / "l").unlink()
        (base / "l").symlink_to("two")
        self.assertNotEqual(with_link["digest"], bm.fingerprint_tree(base)["digest"])
        os.mkfifo(base / "p")
        self.assertEqual(bm.fingerprint_tree(base)["special"], 1)

    def test_write_tree_creates_exactly_the_given_files(self):
        root = self.tmp / "tree"
        bm.write_tree(root, [("a.txt", b"1", 0o644), ("d/e/f.txt", b"2", 0o755)])
        self.assertEqual(
            sorted((e.rel, e.kind) for e in bm.walk_tree(root)),
            [("a.txt", "file"), ("d", "dir"), ("d/e", "dir"), ("d/e/f.txt", "file")],
        )
        self.assertEqual(stat.S_IMODE((root / "d/e/f.txt").stat().st_mode), 0o755)
        with self.assertRaises(OSError):
            bm.write_tree(root, [])  # the root must not pre-exist

    def test_live_state_classification(self):
        self.assertEqual(bm._live_state(self.tmp / "absent"), "absent")
        (self.tmp / "d").mkdir()
        self.assertEqual(bm._live_state(self.tmp / "d"), "dir")
        (self.tmp / "l").symlink_to(self.tmp / "d")
        with self.assertRaises(bm.HelperError) as raised:
            bm._live_state(self.tmp / "l")
        self.assertEqual(raised.exception.code, "bundle_path_symlink")
        (self.tmp / "f").write_text("x")
        with self.assertRaises(bm.HelperError) as raised:
            bm._live_state(self.tmp / "f")
        self.assertEqual(raised.exception.code, "layout_missing")



# ---------------------------------------------------------------------------
# run: adapter invocation over loopback JSON-RPC
# ---------------------------------------------------------------------------

STATUS_VALUES = {key: None for key in adapter_support.STATUS_KEYS}
STATUS_VALUES.update({
    "adapter_version": "0.0.15", "frozen_transaction_state": "present", "restart_transaction_state": "absent",
    "frozen_phase": "needs_attention", "frozen_lifecycle_stage": "quiescence_awaiting_restart",
    "frozen_lifecycle_restart_count": 1, "frozen_status_code": "FROZEN_MANIFEST_INVALID",
    "activation_hold_count": 1, "redlight_hold_present": True, "activation_hold_released": False,
    "updater_guard_required": True, "private_overlay_required": True, "original_update_policy": "AUTOMATIC",
    "resolution_record_count": 61, "restart_attempt_count": None, "restart_status_code": None,
    "restart_transaction_linked": None, "frozen_lock_file_present": False, "restart_lock_file_present": False,
    "restart_phase": None,
})
INSTALL_TRANSACTION = {
    "phase": "complete", "lifecycle_stage": "activation_released", "lifecycle_restart_count": 2,
    "activation_hold_ids": [], "activation_hold_released": True, "private_overlay_required": True,
    "original_update_policy": 0, "updater_guard_required": True, "status_code": "",
    "resolution_records": [{
        "addon_id": "plugin.video.example", "resolution": "install", "state": "installed",
        "resolved_version": "1.0.0", "desired_enabled": True, "repository_id": "repository.example",
    }],
}
ADAPTER_PAYLOADS = {
    "install": {
        "ok": True, "adapter_mode": "install", "outcome": "complete", "code": None,
        "frozen_manifest_fingerprint": "sha256:" + "a" * 64, "overlay_imported": True,
        "transaction": INSTALL_TRANSACTION, "installation_order": ["plugin.video.example"],
        "installed": {"plugin.video.example": {"version": "1.0.0", "enabled": True, "broken": False}},
        "updater_policy": 0,
        "frozen_install_source": {"sha256_before": "b" * 64, "sha256_after": "b" * 64, "replaced": False},
        "retained_inputs": {
            "manifest_present": True, "manifest_readable": True, "artifact_store_present": True,
            "artifact_store_readable": True, "artifact_entry_count": 61,
        },
    },
    "retry": {
        "ok": True, "adapter_mode": "retry", "retry_invoked": True, "outcome": "complete",
        "transaction": {
            "phase": "complete", "lifecycle_stage": "activation_released", "lifecycle_restart_count": 2,
            "activation_hold_ids": [], "activation_hold_released": True, "updater_guard_required": True,
        },
    },
    "recover": {
        "ok": True, "adapter_mode": "recover", "transaction_cleared": True, "original_update_policy": 0,
        "update_policy_after": 0, "updater_policy_restored": True, "restart_transaction_present": False,
        "af3_installed": True, "frozen_addons_retained": True,
    },
    "status": {"ok": True, "adapter_mode": "status", "status": STATUS_VALUES},
}


def adapter_payload(mode, **overrides):
    payload = copy.deepcopy(ADAPTER_PAYLOADS[mode])
    payload.update(overrides)
    return payload


class RunWorld:
    """A fake running Test.app, a scripted Kodi RPC server, and a fake adapter."""

    def __init__(self, testcase, name="world", pid=4242):
        base = testcase.tmp / name
        base.mkdir()
        self.tc = testcase
        self.pid = pid
        self.target = make_fake_app(base)
        self.manifest = install_good(self.target)
        self.lister = FakeProcessLister()
        self.lister.run_test_app(self.target, pid=pid)
        self.clock = FakeClock()
        self.transport = FakeTransport()
        self.events = []
        self.executed = []
        self.prompts = []
        self.listener_pids = {pid}
        self.alive = True
        self.password_to_return = None
        self.transport.execute_hook = lambda params: self.executed.append(dict(params))
        real_post = self.transport.post

        def logging_post(host, port, path, body, headers, timeout):
            self.events.append(("request", json.loads(body)["method"]))
            return real_post(host, port, path, body, headers, timeout)

        self.transport.post = logging_post

        def lookup(port):
            self.events.append(("listener", port))
            return set(self.listener_pids)

        def prompt(text):
            self.prompts.append(text)
            return self.password_to_return

        self.services = make_services(
            self.target, process_lister=self.lister, listener_lookup=lookup, clock=self.clock,
            transport=self.transport, pid_alive=lambda p: self.alive, password_prompt=prompt,
        )

    def write_result(self, payload, *, mtime_ns=None, raw=None):
        directory = self.target.bm_data_dir
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / ".result.tmp"
        temporary.write_bytes(raw if raw is not None else json.dumps(payload).encode("utf-8"))
        os.replace(temporary, self.target.result_path)
        moment = self.clock.now_ns if mtime_ns is None else mtime_ns
        os.utime(self.target.result_path, ns=(moment, moment))

    def produce_on_sleep(self, payload, at=1, **kwargs):
        self.clock.on_sleep = lambda count: self.write_result(payload, **kwargs) if count == at else None

    def run(self, mode="status", *, timeout=30, rpc=None, git_repo=None, manifest=None):
        return bm.run_adapter(
            self.services, mode=mode, manifest=manifest or self.manifest, manifest_sha256="f" * 64,
            rpc={"port": 8080} if rpc is None else rpc, git_repo=git_repo, timeout=timeout,
        )

    def methods(self):
        return [name for kind, name in self.events if kind == "request"]


class TestRun(TripwireTestCase):
    def world(self, name="world", **kwargs):
        return RunWorld(self, name, **kwargs)

    def test_each_mode_invokes_the_driver_once_and_reports_the_fresh_result(self):
        for mode in bm.ADAPTER_MODES:
            with self.subTest(mode=mode):
                world = self.world("w-" + mode)
                world.produce_on_sleep(adapter_payload(mode))
                payload = world.run(mode)
                self.assertTrue(payload["ok"] and payload["adapter_ok"])
                self.assertEqual(payload["result"], adapter_payload(mode))
                self.assertEqual(payload["freshness"]["verdict"], "fresh")
                self.assertFalse(payload["freshness"]["preexisting_result"])
                self.assertEqual(payload["invocation"]["mode"], mode)
                self.assertEqual(payload["invocation"]["test_app_pid"], 4242)
                self.assertEqual(payload["invocation"]["rpc_host"], "127.0.0.1")
                self.assertEqual(
                    world.methods(),
                    ["JSONRPC.Ping", "Addons.GetAddonDetails", "Addons.GetAddonDetails", "Addons.ExecuteAddon"],
                )
                self.assertEqual(world.executed, [{"addonid": bm.DRIVER_ID, "params": mode, "wait": False}])
                self.assertEqual(payload["kodi_addon_view"], {
                    bm.DRIVER_ID: {"enabled": True, "version": "0.0.15"},
                    bm.BUILD_MANAGER_ID: {"enabled": True, "version": "0.1.0"},
                })
                self.assertTrue(payload["stage_verification"]["installed_equals_manifest"])
                self.assertEqual(payload["process_after"]["state"], "running_portable")

    def test_the_installed_trees_are_verified_again_after_the_run(self):
        world = self.world()
        world.produce_on_sleep(adapter_payload("status"))
        payload = world.run("status")
        self.assertEqual(payload["post_run_verification"], {
            "installed_equals_manifest": True,
            "problems": {bm.BUILD_MANAGER_ID: [], bm.DRIVER_ID: []},
        })
        world = self.world("w-drift")

        def tamper_then_write(count):
            (world.target.addon_dir(bm.BUILD_MANAGER_ID) / "service.py").write_text("# replaced by an updater\n")
            world.write_result(adapter_payload("status"))

        world.clock.on_sleep = tamper_then_write
        drifted = world.run("status")
        self.assertTrue(drifted["ok"] and drifted["adapter_ok"])
        self.assertFalse(drifted["post_run_verification"]["installed_equals_manifest"])
        self.assertEqual(drifted["post_run_verification"]["problems"][bm.BUILD_MANAGER_ID], ["modified_files"])

    def test_listener_pid_is_verified_before_every_single_request(self):
        world = self.world()
        world.produce_on_sleep(adapter_payload("status"))
        world.run("status")
        requests = [i for i, event in enumerate(world.events) if event[0] == "request"]
        self.assertEqual(len(requests), 4)
        for index in requests:
            self.assertEqual(world.events[index - 1][0], "listener", world.events)
        self.assertEqual(world.events[0][0], "listener")

    def test_listener_mismatch_is_refused_before_any_request_is_sent(self):
        for label, pids, code in (
            ("other pid", {9999}, "listener_pid_mismatch"),
            ("shared port", {4242, 9999}, "listener_pid_mismatch"),
            ("nobody", set(), "listener_not_found"),
        ):
            world = self.world("w-" + label.replace(" ", "-"))
            world.listener_pids = pids
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                world.run("status")
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(world.transport.requests, [])
            self.assertEqual(world.prompts, [])

    def test_listener_change_mid_run_is_caught_on_the_next_request(self):
        world = self.world()
        original = world.transport.default_handler

        def swap_listener_after_ping(request):
            if request["body"]["method"] == "JSONRPC.Ping":
                world.listener_pids = {31337}
            return original(request)

        world.transport.handler = swap_listener_after_ping
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "listener_pid_mismatch")
        self.assertEqual(world.methods(), ["JSONRPC.Ping"])

    def test_non_loopback_hosts_never_connect(self):
        for host in ("192.168.1.10", "example.com", "0.0.0.0", "::ffff:127.0.0.1", "10.0.0.1"):
            world = self.world("w-" + host.replace(":", "_").replace(".", "_"))
            with self.subTest(host=host), mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("resolver used")):
                with self.assertRaises(bm.HelperError) as raised:
                    world.run("status", rpc={"host": host, "port": 8080})
            self.assertEqual(raised.exception.code, "rpc_host_not_loopback")
            self.assertEqual(world.transport.requests, [])
            self.assertEqual(world.events, [])

    def test_requests_always_target_the_literal_loopback_address(self):
        world = self.world()
        world.produce_on_sleep(adapter_payload("status"))
        world.run("status", rpc={"host": "localhost", "port": 8123})
        for request in world.transport.requests:
            self.assertEqual((request["host"], request["port"], request["path"]), ("127.0.0.1", 8123, "/jsonrpc"))
            self.assertEqual(request["headers"]["Connection"], "close")
            self.assertNotIn("Authorization", request["headers"])

    def test_port_is_required_and_validated(self):
        world = self.world()
        for rpc in ({}, {"port": 0}, {"port": 70000}, {"port": "80"}, {"host": "127.0.0.1"}):
            with self.subTest(rpc=rpc), self.assertRaises(bm.HelperError) as raised:
                world.run("status", rpc=rpc)
            self.assertEqual(raised.exception.code, "rpc_port_invalid")
        self.assertEqual(world.transport.requests, [])

    def test_requires_one_clean_portable_instance(self):
        world = self.world("w-stopped")
        world.lister.processes.clear()
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "test_app_not_running")
        world = self.world("w-nop")
        world.lister.commands[4242] = world.lister.processes[-1].exe
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "test_app_not_portable")
        world = self.world("w-foreign")
        world.lister.processes.append(bm.ProcessInfo(5, "/Applications/Kodi.app/Contents/MacOS/Kodi"))
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "foreign_kodi_process_present")
        for each in ("w-stopped", "w-nop", "w-foreign"):
            self.assertEqual(self.tripwire.touched, [], each)

    def test_unverified_installed_tree_is_refused_before_any_request(self):
        world = self.world()
        (world.target.addon_dir(bm.BUILD_MANAGER_ID) / "service.py").write_text("# tampered\n")
        with self.assertRaises(bm.HelperError) as raised:
            world.run("install")
        self.assertEqual(raised.exception.code, "installed_tree_mismatch")
        self.assertEqual(world.transport.requests, [])
        self.assertEqual(world.executed, [])

    def test_git_binding_failure_is_refused_before_any_request(self):
        world = self.world()
        manifest = copy.deepcopy(world.manifest)
        manifest["candidate"]["tree"] = "0" * 40
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status", git_repo=FIXTURE.repo, manifest=manifest)
        self.assertEqual(raised.exception.code, "installed_tree_mismatch")
        self.assertEqual(world.transport.requests, [])
        world = self.world("w-good")
        world.produce_on_sleep(adapter_payload("status"))
        payload = world.run("status", git_repo=FIXTURE.repo)
        self.assertTrue(payload["stage_verification"]["installed_equals_candidate"])

    # --- credentials ---------------------------------------------------

    def test_unauthenticated_kodi_never_triggers_a_prompt(self):
        world = self.world()
        world.produce_on_sleep(adapter_payload("status"))
        payload = world.run("status")
        self.assertFalse(payload["invocation"]["authenticated"])
        self.assertEqual(world.prompts, [])

    def test_password_is_prompted_once_used_in_memory_and_never_leaked(self):
        world = self.world()
        world.transport.password = SENTINEL_PASSWORD
        world.transport.username = "alice"
        world.password_to_return = SENTINEL_PASSWORD
        world.produce_on_sleep(adapter_payload("status"))
        environment_before = dict(os.environ)
        argv_before = list(sys.argv)
        payload = world.run("status", rpc={"port": 8080, "username": "alice"})
        self.assertTrue(payload["invocation"]["authenticated"])
        self.assertEqual(len(world.prompts), 1)
        self.assertIn("alice", world.prompts[0])
        self.assertNotIn(SENTINEL_PASSWORD, world.prompts[0])
        token = base64.b64encode(f"alice:{SENTINEL_PASSWORD}".encode()).decode()
        authorized = [r for r in world.transport.requests if "Authorization" in r["headers"]]
        self.assertGreaterEqual(len(authorized), 4)
        self.assertEqual({r["headers"]["Authorization"] for r in authorized}, {"Basic " + token})
        self.assertNotIn("Authorization", world.transport.requests[0]["headers"])  # first try is anonymous
        text = bm.canonical_json(payload)
        for leaked in (SENTINEL_PASSWORD, token, "Authorization", "Basic "):
            self.assertNotIn(leaked, text)
        self.assertFalse(world.services.secrets.leaks(text))
        self.assertTrue(world.services.secrets.leaks(SENTINEL_PASSWORD))
        self.assertEqual(dict(os.environ), environment_before)
        self.assertEqual(sys.argv, argv_before)
        self.assertFalse(any(SENTINEL_PASSWORD in value for value in os.environ.values()))
        for request in world.transport.requests:  # never in the request body either
            self.assertNotIn(SENTINEL_PASSWORD, json.dumps(request["body"]))
            self.assertNotIn(SENTINEL_PASSWORD, json.dumps({k: v for k, v in request.items() if k != "headers"}))

    def test_wrong_password_fails_without_retry_loops(self):
        world = self.world()
        world.transport.password = "the-right-password"
        world.password_to_return = SENTINEL_PASSWORD
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "rpc_auth_failed")
        self.assertEqual(len(world.prompts), 1)
        self.assertEqual(len(world.transport.requests), 2)
        self.assertNotIn(SENTINEL_PASSWORD, json.dumps(raised.exception.detail))

    def test_missing_or_unavailable_credentials_fail_closed(self):
        world = self.world()
        world.transport.password = "x" * 12
        world.password_to_return = ""
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "credential_missing")
        world = self.world("w-no-tty")
        world.transport.password = "x" * 12

        def no_terminal(prompt):
            raise bm.HelperError("credential_prompt_unavailable")

        world.services.password_prompt = no_terminal
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "credential_prompt_unavailable")
        self.assertEqual(world.executed, [])

    def test_credential_prompt_never_falls_back_to_stdin(self):
        with mock.patch.object(bm.os, "open", side_effect=OSError("no tty")), \
                mock.patch("sys.stdin", io.StringIO(SENTINEL_PASSWORD + "\n")):
            with self.assertRaises(bm.HelperError) as raised:
                bm.interactive_password_prompt("prompt: ")
        self.assertEqual(raised.exception.code, "credential_prompt_unavailable")

    def test_getpass_fallback_warning_is_treated_as_unavailable(self):
        def fallback(prompt):
            import warnings as _warnings
            _warnings.warn("echo", __import__("getpass").GetPassWarning)
            return "typed-but-echoed"

        with mock.patch.object(bm.os, "open", return_value=99), mock.patch.object(bm.os, "close"), \
                mock.patch.object(bm.getpass, "getpass", fallback):
            with self.assertRaises(bm.HelperError) as raised:
                bm.interactive_password_prompt("p: ")
        self.assertEqual(raised.exception.code, "credential_prompt_unavailable")

    def test_secret_registry_receives_password_token_and_header(self):
        world = self.world()
        world.transport.password = SENTINEL_PASSWORD
        world.password_to_return = SENTINEL_PASSWORD
        world.produce_on_sleep(adapter_payload("status"))
        world.run("status")
        token = base64.b64encode(f"kodi:{SENTINEL_PASSWORD}".encode()).decode()
        for secret in (SENTINEL_PASSWORD, token, "Basic " + token):
            self.assertTrue(world.services.secrets.leaks(secret))

    # --- freshness -----------------------------------------------------

    def test_an_unchanged_preexisting_result_is_stale_and_never_trusted(self):
        world = self.world()
        world.write_result(adapter_payload("status"), mtime_ns=world.clock.now_ns - 3600 * 10 ** 9)
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status", timeout=5)
        self.assertEqual(raised.exception.code, "result_stale")
        self.assertEqual(raised.exception.detail["last_observation"], "stale")
        self.assertEqual(len(world.clock.sleeps), 5)

    def test_a_touched_but_not_rewritten_result_is_still_stale(self):
        world = self.world()
        world.write_result(adapter_payload("status"), mtime_ns=world.clock.now_ns - 3600 * 10 ** 9)

        def touch(count):
            moment = world.clock.now_ns
            os.utime(world.target.result_path, ns=(moment, moment))

        world.clock.on_sleep = touch
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status", timeout=3)
        self.assertEqual(raised.exception.code, "result_stale")

    def test_a_rewritten_result_with_identical_bytes_is_fresh(self):
        world = self.world()
        payload = adapter_payload("status")
        world.write_result(payload, mtime_ns=world.clock.now_ns - 3600 * 10 ** 9)
        world.produce_on_sleep(payload)
        result = world.run("status")
        self.assertEqual(result["freshness"]["verdict"], "fresh")
        self.assertTrue(result["freshness"]["preexisting_result"])
        self.assertTrue(result["freshness"]["changed_since_before"])

    def test_a_replaced_but_backdated_result_is_stale(self):
        world = self.world()
        world.write_result(adapter_payload("status"), mtime_ns=world.clock.now_ns - 7200 * 10 ** 9)
        world.produce_on_sleep(
            adapter_payload("status", marker_field="x"), mtime_ns=world.clock.now_ns - 3600 * 10 ** 9
        )
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status", timeout=4)
        self.assertEqual(raised.exception.code, "result_stale")

    def test_no_result_at_all_times_out_as_not_produced(self):
        world = self.world()
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status", timeout=3)
        self.assertEqual(raised.exception.code, "result_not_produced")
        self.assertEqual(len(world.executed), 1)  # invoked exactly once, never re-sent

    def test_a_result_from_the_future_is_refused(self):
        world = self.world()
        world.produce_on_sleep(adapter_payload("status"), mtime_ns=world.clock.now_ns + 3600 * 10 ** 9)
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "result_from_future")

    def test_result_arriving_later_is_picked_up(self):
        world = self.world()
        world.produce_on_sleep(adapter_payload("status"), at=7)
        payload = world.run("status", timeout=60)
        self.assertEqual(payload["freshness"]["verdict"], "fresh")
        self.assertEqual(len(world.clock.sleeps), 7)

    def test_a_transiently_unreadable_result_is_retried(self):
        world = self.world()
        world.produce_on_sleep(adapter_payload("status"))
        original = bm.read_regular_file
        calls = []

        def flaky(path, limit):
            if os.fspath(path) == os.fspath(world.target.result_path):
                calls.append(1)
                if len(calls) == 3:
                    raise bm.FsProblem("changed")
            return original(path, limit)

        with mock.patch.object(bm, "read_regular_file", flaky):
            payload = world.run("status", timeout=30)
        self.assertEqual(payload["freshness"]["verdict"], "fresh")

    def test_kodi_exiting_without_a_result_is_reported(self):
        world = self.world()

        def die(count):
            world.alive = False

        world.clock.on_sleep = die
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status", timeout=600)
        self.assertEqual(raised.exception.code, "kodi_exited_before_result")
        self.assertEqual(len(world.clock.sleeps), bm.LIVENESS_EVERY_POLLS - 1)  # checked before the 5th sleep

    def test_process_after_reports_a_restart_or_ambiguity_without_failing(self):
        world = self.world()

        def restart_and_write(count):
            world.write_result(adapter_payload("status"))
            world.lister.processes.clear()

        world.clock.on_sleep = restart_and_write
        self.assertEqual(world.run("status")["process_after"]["state"], "not_running")
        world = self.world("w-multi")

        def duplicate_and_write(count):
            world.write_result(adapter_payload("status"))
            world.lister.run_test_app(world.target, pid=999)

        world.clock.on_sleep = duplicate_and_write
        self.assertEqual(world.run("status")["process_after"], {"error": "multiple_test_app_processes"})

    def test_result_path_must_not_be_a_symlink_or_live_in_a_symlinked_directory(self):
        world = self.world()
        outside = self.tmp / "outside-result.json"
        outside.write_text(json.dumps(adapter_payload("status")))
        world.target.bm_data_dir.mkdir(parents=True)
        world.target.result_path.symlink_to(outside)
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "result_path_unsafe")
        self.assertEqual(world.transport.requests, [])
        world = self.world("w-dirlink")
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        world.target.addon_data_dir.mkdir(parents=True)
        world.target.bm_data_dir.symlink_to(elsewhere)
        with self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "result_path_unsafe")

    # --- result validation ----------------------------------------------

    def test_adapter_mode_must_match_the_requested_mode(self):
        for requested, observed in (("install", "status"), ("status", "install"), ("retry", "recover"),
                                    ("status", "unselected"), ("install", None), ("install", "evil\nmode"), ("status", 7)):
            world = self.world(f"w-{requested}-{observed}".replace("\n", "_").replace(" ", "_"))
            payload = adapter_payload("status")
            if observed is None:
                payload.pop("adapter_mode")
            else:
                payload["adapter_mode"] = observed
            world.produce_on_sleep(payload)
            with self.subTest(requested=requested, observed=observed), self.assertRaises(bm.HelperError) as raised:
                world.run(requested)
            self.assertEqual(raised.exception.code, "adapter_mode_mismatch")
            self.assertEqual(raised.exception.detail["expected_mode"], requested)
            self.assertNotIn("evil", json.dumps(raised.exception.detail))

    def test_malformed_results_fail_closed(self):
        cases = {
            "invalid json": b"{not json",
            "root list": b"[1, 2]",
            "bad utf8": b"\xff\xfe",
            "ok missing": json.dumps({"adapter_mode": "status"}).encode(),
            "ok not bool": json.dumps({"adapter_mode": "status", "ok": "yes"}).encode(),
            "empty": b"",
        }
        for label, raw in cases.items():
            world = self.world("w-" + label.replace(" ", "-"))
            world.produce_on_sleep(None, raw=raw)
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                world.run("status")
            self.assertEqual(raised.exception.code, "result_malformed")

    def test_oversized_result_is_refused(self):
        world = self.world()
        world.produce_on_sleep(adapter_payload("status", padding="x" * 200))
        with mock.patch.object(bm, "MAX_RESULT_BYTES", 100), self.assertRaises(bm.HelperError) as raised:
            world.run("status")
        self.assertEqual(raised.exception.code, "result_malformed")

    def test_adapter_reported_failure_is_relayed_as_evidence_with_a_distinct_status(self):
        world = self.world()
        failure = {
            "ok": False, "adapter_mode": "install", "error_type": "OSError",
            "adapter_stage": "LOAD_FROZEN_MANIFEST", "failing_callable": "pathlib.Path",
            "failure_category": "retained_manifest_missing",
            "retained_inputs": {"manifest_present": False, "manifest_readable": False,
                                "artifact_store_present": True, "artifact_store_readable": True,
                                "artifact_entry_count": 0},
        }
        world.produce_on_sleep(failure)
        payload = world.run("install")
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["adapter_ok"])
        self.assertEqual(payload["result"], failure)

    # --- RPC-level failures ----------------------------------------------

    def test_rpc_protocol_failures_fail_closed(self):
        def with_handler(name, handler, code):
            world = self.world("w-" + name)
            world.transport.handler = handler
            with self.subTest(case=name), self.assertRaises(bm.HelperError) as raised:
                world.run("status")
            self.assertEqual(raised.exception.code, code, name)
            self.assertEqual(world.executed, [])
            return raised.exception

        reply = FakeTransport().reply
        with_handler("http 500", lambda r: (500, b"oops"), "rpc_http_error")
        with_handler("http 302", lambda r: (302, b""), "rpc_http_error")
        with_handler("not json", lambda r: (200, b"<html>"), "rpc_response_invalid")
        with_handler("wrong id", lambda r: (200, json.dumps({"jsonrpc": "2.0", "id": 2, "result": "pong"}).encode()), "rpc_response_invalid")
        with_handler("wrong version", lambda r: (200, json.dumps({"jsonrpc": "1.0", "id": 1, "result": "pong"}).encode()), "rpc_response_invalid")
        with_handler("no result", lambda r: (200, json.dumps({"jsonrpc": "2.0", "id": 1}).encode()), "rpc_response_invalid")
        with_handler("not pong", lambda r: reply("nope"), "rpc_response_invalid")
        error = with_handler("rpc error", lambda r: reply(error={"code": -32601, "message": "secret detail"}), "rpc_error")
        self.assertEqual(error.detail["rpc_code"], -32601)
        self.assertNotIn("secret", json.dumps(error.detail))
        with_handler("too large", lambda r: (200, b"x" * (bm.MAX_RPC_BYTES + 1)), "rpc_response_too_large")

        def raising(request):
            raise ConnectionRefusedError("connection refused to /secret/path")

        error = with_handler("transport", raising, "rpc_transport_failed")
        self.assertNotIn("secret", json.dumps(error.detail))

    def test_execute_rejection_is_an_error_not_success(self):
        world = self.world()
        world.transport.execute_result = "Failed"
        with self.assertRaises(bm.HelperError) as raised:
            world.run("install")
        self.assertEqual(raised.exception.code, "rpc_execute_rejected")

    def test_ok_from_execute_addon_alone_is_never_success(self):
        world = self.world()  # Kodi says OK but the adapter never writes a result
        with self.assertRaises(bm.HelperError) as raised:
            world.run("install", timeout=2)
        self.assertEqual(raised.exception.code, "result_not_produced")

    def test_kodi_addon_view_must_match_the_staged_versions(self):
        cases = {
            "driver disabled": ({bm.DRIVER_ID: {"enabled": False, "version": "0.0.15"}}, "addon_view_mismatch"),
            "driver version": ({bm.DRIVER_ID: {"enabled": True, "version": "0.0.14"}}, "addon_view_mismatch"),
            "bm disabled": ({bm.BUILD_MANAGER_ID: {"enabled": False, "version": "0.1.0"}}, "addon_view_mismatch"),
            "bm version": ({bm.BUILD_MANAGER_ID: {"enabled": True, "version": "9.9.9"}}, "addon_view_mismatch"),
            "enabled type": ({bm.DRIVER_ID: {"enabled": "yes", "version": "0.0.15"}}, "addon_view_mismatch"),
            "version type": ({bm.DRIVER_ID: {"enabled": True, "version": "bad version!"}}, "addon_view_mismatch"),
        }
        for label, (details, code) in cases.items():
            world = self.world("w-" + label.replace(" ", "-"))
            world.transport.details.update(details)
            with self.subTest(case=label), self.assertRaises(bm.HelperError) as raised:
                world.run("status")
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn("Addons.ExecuteAddon", world.methods())
        for missing in (bm.DRIVER_ID, bm.BUILD_MANAGER_ID):
            world = self.world("w-missing-" + missing[-6:])
            del world.transport.details[missing]
            with self.subTest(missing=missing), self.assertRaises(bm.HelperError) as raised:
                world.run("status")
            self.assertEqual(raised.exception.code, "addon_not_visible_to_kodi")
            self.assertNotIn("Addons.ExecuteAddon", world.methods())

    def test_timeout_defaults_exist_for_every_mode(self):
        self.assertEqual(set(bm.DEFAULT_TIMEOUTS), set(bm.ADAPTER_MODES))
        self.assertTrue(all(0 < value <= 7200 for value in bm.DEFAULT_TIMEOUTS.values()))


# ---------------------------------------------------------------------------
# Result projection
# ---------------------------------------------------------------------------

class TestResultProjection(unittest.TestCase):
    def project(self, mode, payload):
        return bm.project_adapter_result(mode, payload)

    def test_valid_payloads_pass_through_unchanged(self):
        for mode in bm.ADAPTER_MODES:
            with self.subTest(mode=mode):
                projected, withheld = self.project(mode, adapter_payload(mode))
                self.assertEqual(projected, adapter_payload(mode))
                self.assertEqual(withheld, {"invalid_known_keys": [], "unknown_key_count": 0, "unknown_key_names": []})

    def test_unknown_keys_are_withheld_never_echoed(self):
        payload = adapter_payload("install", password="INJECTED-SECRET-123", traceback="INJECTED-TRACE",
                                  **{"overlay values": "INJECTED-OVERLAY"})
        projected, withheld = self.project("install", payload)
        text = json.dumps([projected, withheld])
        for injected in ("INJECTED-SECRET-123", "INJECTED-TRACE", "INJECTED-OVERLAY"):
            self.assertNotIn(injected, text)
        self.assertEqual(withheld["unknown_key_count"], 3)
        self.assertEqual(withheld["unknown_key_names"], ["password", "traceback"])  # unsafe names are only counted

    def test_invalid_known_values_withhold_the_whole_field(self):
        cases = {
            "install": {"outcome": "Complete!", "transaction": {"phase": "INJECTED"}, "installed": {"bad id": {}},
                        "installation_order": ["x"] * 600, "updater_policy": 9, "overlay_imported": "yes",
                        "frozen_manifest_fingerprint": "not-a-fingerprint"},
            "retry": {"outcome": "INJECTED", "retry_invoked": 1},
            "recover": {"transaction_cleared": "true", "original_update_policy": -1},
            "status": {"status": dict(STATUS_VALUES, frozen_phase="INJECTED")},
        }
        for mode, overrides in cases.items():
            with self.subTest(mode=mode):
                projected, withheld = self.project(mode, adapter_payload(mode, **overrides))
                for key in overrides:
                    self.assertNotIn(key, projected, key)
                self.assertEqual(sorted(withheld["invalid_known_keys"]), sorted(overrides))
                self.assertNotIn("INJECTED", json.dumps([projected, withheld]))

    def test_unknown_public_codes_become_null_like_the_adapter_itself(self):
        projected, _ = self.project("status", adapter_payload("status", status=dict(
            STATUS_VALUES, frozen_status_code="FROZEN_PRIVATE_VALUE_X", restart_status_code="NOT_PUBLIC")))
        self.assertIsNone(projected["status"]["frozen_status_code"])
        self.assertIsNone(projected["status"]["restart_status_code"])
        self.assertEqual(projected["status"]["frozen_phase"], "needs_attention")
        installed, _ = self.project("install", adapter_payload("install", code="SOMETHING_PRIVATE"))
        self.assertIsNone(installed["code"])
        transaction = dict(INSTALL_TRANSACTION, status_code="SOMETHING_PRIVATE")
        installed, _ = self.project("install", adapter_payload("install", transaction=transaction))
        self.assertIsNone(installed["transaction"]["status_code"])

    def test_public_codes_are_preserved(self):
        for code in sorted(adapter_support.STATUS_FROZEN_CODES)[:5]:
            projected, _ = self.project("status", adapter_payload("status", status=dict(STATUS_VALUES, frozen_status_code=code)))
            self.assertEqual(projected["status"]["frozen_status_code"], code)

    def test_nested_unknown_keys_are_dropped(self):
        transaction = dict(INSTALL_TRANSACTION, private_note="INJECTED-NESTED")
        projected, _ = self.project("install", adapter_payload("install", transaction=transaction))
        self.assertNotIn("INJECTED-NESTED", json.dumps(projected))
        self.assertNotIn("private_note", projected["transaction"])

    def test_failure_labels_are_allowlisted(self):
        failure = {"ok": False, "adapter_mode": "status", "error_type": "OSError", "adapter_stage": "READ_STATUS",
                   "failing_callable": "read_adapter_status", "failure_category": "operation_failed",
                   "expected_sha256": "a" * 64, "observed_sha256": "b" * 64}
        projected, withheld = self.project("status", dict(failure))
        self.assertEqual(projected, failure)
        hostile = dict(failure, failure_category="EVIL\nCATEGORY", adapter_stage="/etc/passwd",
                       error_type="Traceback (most recent call last)", expected_sha256="not-hex")
        projected, withheld = self.project("status", hostile)
        for key in ("failure_category", "adapter_stage", "error_type", "expected_sha256"):
            self.assertNotIn(key, projected)
        self.assertNotIn("EVIL", json.dumps([projected, withheld]))

    def test_structurally_invalid_results_raise(self):
        for raw in ([], "text", None, 5, {"adapter_mode": "status"}, {"ok": "no", "adapter_mode": "status"}):
            with self.subTest(raw=raw), self.assertRaises(bm.HelperError) as raised:
                self.project("status", raw)
            self.assertEqual(raised.exception.code, "result_malformed")

    def test_every_status_key_has_a_validator(self):
        self.assertEqual(set(STATUS_VALUES), set(adapter_support.STATUS_KEYS))
        record = bm._STATUS_RECORD(STATUS_VALUES)
        self.assertEqual(set(record), set(adapter_support.STATUS_KEYS))

    def test_projection_allowlists_cover_the_adapters_own_vocabularies(self):
        for label in adapter_support.ADAPTER_STAGES:
            bm._COMMON_FIELDS["adapter_stage"](label)
        for label in adapter_support.ADAPTER_CALLABLES:
            bm._COMMON_FIELDS["failing_callable"](label)
        for label in adapter_support.FAILURE_CATEGORIES:
            bm._COMMON_FIELDS["failure_category"](label)
        for label in adapter_support.SAFE_ERROR_TYPES:
            bm._COMMON_FIELDS["error_type"](label)
        self.assertEqual(bm._COMMON_FIELDS["error_type"]("not_started"), "not_started")


# ---------------------------------------------------------------------------
# run against a real loopback HTTP server, real lsof, real transport
# ---------------------------------------------------------------------------

class KodiHttpFake:
    """A tiny real HTTP JSON-RPC server hosted by this test process."""

    def __init__(self, *, password=None, username="kodi", on_execute=None, redirect=None, oversize=False):
        self.requests = []
        self.password = password
        self.username = username
        self.on_execute = on_execute
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
                if redirect is not None:
                    self.send_response(302)
                    self.send_header("Location", redirect)
                    self.end_headers()
                    return
                if oversize:
                    payload = b"x" * (bm.MAX_RPC_BYTES + 10)
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if outer.password is not None:
                    expected = "Basic " + base64.b64encode(f"{outer.username}:{outer.password}".encode()).decode()
                    if self.headers.get("Authorization") != expected:
                        self.send_response(401)
                        self.send_header("WWW-Authenticate", 'Basic realm="Kodi"')
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                method, params = body["method"], body.get("params", {})
                if method == "JSONRPC.Ping":
                    result = "pong"
                elif method == "Addons.GetAddonDetails":
                    version = {bm.DRIVER_ID: "0.0.15", bm.BUILD_MANAGER_ID: "0.1.0"}[params["addonid"]]
                    result = {"addon": {"addonid": params["addonid"], "enabled": True, "version": version}}
                elif method == "Addons.ExecuteAddon":
                    result = "OK"
                    if outer.on_execute is not None:
                        outer.on_execute(params)
                else:
                    result = None
                payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@unittest.skipUnless(os.path.exists("/usr/sbin/lsof"), "needs lsof")
class TestRunOverRealLoopback(TripwireTestCase):
    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)
        self.manifest = install_good(self.target)
        self.lister = FakeProcessLister()
        self.lister.run_test_app(self.target, pid=os.getpid())  # this process hosts the fake Kodi
        patcher = mock.patch.object(bm, "POLL_INTERVAL_SECONDS", 0.05)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.prompts = []
        self.lsof_calls = []

        def spying_runner(command, **kwargs):
            self.lsof_calls.append((list(command), dict(kwargs.get("env", {}))))
            return subprocess.run(command, **kwargs)

        self.services = make_services(
            self.target, process_lister=self.lister, clock=bm.SystemClock(), transport=bm.HttpTransport(),
            listener_lookup=lambda port: bm.lsof_listener_pids(port, spying_runner),
            pid_alive=bm.default_pid_alive,
            password_prompt=lambda prompt: (self.prompts.append(prompt), SENTINEL_PASSWORD)[1],
        )

    def write_result_soon(self, payload, delay=0.15):
        def write():
            directory = self.target.bm_data_dir
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / ".result.tmp"
            temporary.write_text(json.dumps(payload))
            os.replace(temporary, self.target.result_path)

        return lambda params: threading.Timer(delay, write).start()

    def run_mode(self, server, mode="status", **kwargs):
        return bm.run_adapter(
            self.services, mode=mode, manifest=self.manifest, manifest_sha256="f" * 64,
            rpc={"port": server.port}, git_repo=None, timeout=kwargs.pop("timeout", 20), **kwargs,
        )

    def test_full_run_through_real_http_real_lsof_and_real_mtimes(self):
        with KodiHttpFake(on_execute=lambda p: self.write_result_soon(adapter_payload("status"))(p)) as server:
            payload = self.run_mode(server)
        self.assertTrue(payload["adapter_ok"])
        self.assertEqual(payload["freshness"]["verdict"], "fresh")
        self.assertEqual(payload["result"], adapter_payload("status"))
        self.assertEqual([r["body"]["method"] for r in server.requests],
                         ["JSONRPC.Ping", "Addons.GetAddonDetails", "Addons.GetAddonDetails", "Addons.ExecuteAddon"])
        for request in server.requests:
            self.assertEqual(request["path"], "/jsonrpc")
            self.assertEqual(request["headers"]["Host"], f"127.0.0.1:{server.port}")
            self.assertNotIn("Authorization", request["headers"])
        self.assertEqual(self.prompts, [])
        self.assertGreaterEqual(len(self.lsof_calls), 4)

    def test_real_basic_auth_flow_and_no_credential_leaks_anywhere(self):
        with KodiHttpFake(password=SENTINEL_PASSWORD,
                          on_execute=lambda p: self.write_result_soon(adapter_payload("status"))(p)) as server:
            payload = self.run_mode(server)
        self.assertTrue(payload["invocation"]["authenticated"])
        token = base64.b64encode(f"kodi:{SENTINEL_PASSWORD}".encode()).decode()
        self.assertEqual(server.requests[0]["headers"].get("Authorization"), None)
        self.assertEqual(server.requests[1]["headers"]["Authorization"], "Basic " + token)
        text = bm.canonical_json(payload)
        for leaked in (SENTINEL_PASSWORD, token):
            self.assertNotIn(leaked, text)
        for command, env in self.lsof_calls:  # helper subprocesses never see the secret
            self.assertNotIn(SENTINEL_PASSWORD, " ".join(command) + " ".join(env.values()))
        self.assertEqual(len(self.prompts), 1)

    def test_wrong_real_password_is_rejected(self):
        with KodiHttpFake(password="a-different-password") as server:
            with self.assertRaises(bm.HelperError) as raised:
                self.run_mode(server)
        self.assertEqual(raised.exception.code, "rpc_auth_failed")
        self.assertEqual(len(server.requests), 2)

    def test_a_listener_that_is_not_the_test_app_receives_nothing(self):
        self.lister.processes[:] = []
        self.lister.commands.clear()
        self.lister.run_test_app(self.target, pid=os.getpid() + 4242)  # authorized pid is someone else
        with KodiHttpFake() as server:
            with self.assertRaises(bm.HelperError) as raised:
                self.run_mode(server)
        self.assertEqual(raised.exception.code, "listener_pid_mismatch")
        self.assertEqual(server.requests, [])

    def test_no_listener_at_all(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        with self.assertRaises(bm.HelperError) as raised:
            bm.run_adapter(self.services, mode="status", manifest=self.manifest, manifest_sha256="f" * 64,
                           rpc={"port": free}, git_repo=None, timeout=5)
        self.assertEqual(raised.exception.code, "listener_not_found")

    def test_proxy_environment_variables_are_ignored(self):
        with KodiHttpFake(on_execute=lambda p: self.write_result_soon(adapter_payload("status"))(p)) as server, \
                KodiHttpFake() as proxy, mock.patch.dict(os.environ, {
                    "http_proxy": f"http://127.0.0.1:{proxy.port}", "HTTP_PROXY": f"http://127.0.0.1:{proxy.port}",
                    "all_proxy": f"http://127.0.0.1:{proxy.port}"}):
            payload = self.run_mode(server)
        self.assertTrue(payload["adapter_ok"])
        self.assertEqual(proxy.requests, [])
        self.assertEqual(len(server.requests), 4)

    def test_redirects_are_never_followed(self):
        with KodiHttpFake() as victim, KodiHttpFake(redirect=f"http://127.0.0.1:{victim.port}/jsonrpc") as server:
            with self.assertRaises(bm.HelperError) as raised:
                self.run_mode(server)
        self.assertEqual(raised.exception.code, "rpc_http_error")
        self.assertEqual(raised.exception.detail["status"], 302)
        self.assertEqual(victim.requests, [])

    def test_oversized_real_response_is_refused(self):
        with KodiHttpFake(oversize=True) as server:
            with self.assertRaises(bm.HelperError) as raised:
                self.run_mode(server)
        self.assertEqual(raised.exception.code, "rpc_response_too_large")



# ---------------------------------------------------------------------------
# snapshot: secret-blind census
# ---------------------------------------------------------------------------

FROZEN_ID = "3f920c0f-dc69-4684-914b-1bb370a17ba0"
RESTART_ID = "6a1b2c3d-1111-4222-8333-444455556666"
SESSION_ID = "9d8c7b6a-0000-4111-8222-333344445555"
STATUS_MESSAGE = "SENTINEL-STATUS-MESSAGE leaking /Users/example/private"
GUISETTINGS = """<settings version="2">
    <setting id="general.addonupdates">2</setting>
    <setting id="lookandfeel.skin">skin.arctic.fuse.3</setting>
    <setting id="services.webserver" default="true">true</setting>
    <setting id="services.webserverport">8089</setting>
    <setting id="services.webserverusername">kodi</setting>
    <setting id="services.webserverpassword">%s</setting>
</settings>
""" % SENTINEL_PASSWORD


def frozen_record(**overrides):
    record = {
        "schema_version": 3, "transaction_id": FROZEN_ID, "build_id": "fixture-build",
        "manifest_path": ADAPTER_VALUES["MANIFEST_PATH"], "device_profile_id": "fixture-device",
        "manifest_fingerprint": "sha256:" + "a" * 64, "phase": "needs_attention",
        "originating_kodi_session_id": SESSION_ID, "original_update_policy": 0, "updater_guard_required": True,
        "restart_transaction_id": RESTART_ID, "created_at": "2026-10-04T00:00:00Z", "updated_at": "2026-10-04T00:01:00Z",
        "status_code": "FROZEN_MANIFEST_INVALID", "status_message": STATUS_MESSAGE,
        "private_overlay_id": ADAPTER_VALUES["EXPECTED_OVERLAY_ID"], "private_overlay_fingerprint": "sha256:" + "c" * 64,
        "private_overlay_required": True, "install_plan_fingerprint": "sha256:" + "d" * 64,
        "policies": [], "resolution_records": [{"addon_id": "plugin.video.redlight", "resolution": "install"}] * 3,
        "resolution_fingerprint": "", "resolved_software_fingerprint": "",
        "configuration_manifest_path": ADAPTER_VALUES["CONFIGURATION_PATH"],
        "lifecycle_stage": "quiescence_awaiting_restart", "activation_hold_ids": ["plugin.video.redlight"],
        "activation_hold_released": False, "lifecycle_restart_count": 1,
    }
    record.update(overrides)
    return record


def restart_record(**overrides):
    record = {
        "transaction_id": RESTART_ID, "phase": "awaiting_restart", "restart_attempt_count": 1,
        "status_code": "RESTART_REQUIRED_AFTER_RESUME", "status_message": STATUS_MESSAGE,
    }
    record.update(overrides)
    return record


def make_profile(target):
    """A rich fake portable profile: public metadata plus plenty of private data."""
    addons = target.addons_dir
    for addon_id, version in (
        ("plugin.video.redlight", "2.6.8"), ("skin.arctic.fuse.3", "3.1.0"), ("repository.example", "1.0.0"),
    ):
        (addons / addon_id).mkdir()
        (addons / addon_id / "addon.xml").write_text(f'<addon id="{addon_id}" version="{version}" name="n"/>')
    (addons / "packages").mkdir()
    (addons / "packages" / "cached.zip").write_bytes(b"zip")
    (addons / "temp").mkdir()
    userdata = target.userdata_dir
    database = userdata / "Database"
    database.mkdir()
    for number, rows in (
        (27, [("old.addon", 1)]),
        (33, [(bm.BUILD_MANAGER_ID, 1), (bm.DRIVER_ID, 1), ("plugin.video.redlight", 0),
              ("skin.arctic.fuse.3", 1), ("repository.example", 1)]),
    ):
        connection = sqlite3.connect(database / f"Addons{number}.db")
        connection.execute(
            "CREATE TABLE installed (id INTEGER PRIMARY KEY, addonID TEXT UNIQUE, enabled BOOLEAN, "
            "installDate TEXT, lastUpdated TEXT, lastUsed TEXT, origin TEXT NOT NULL DEFAULT '', "
            "disabledReason INTEGER NOT NULL DEFAULT 0)"
        )
        connection.executemany("INSERT INTO installed (addonID, enabled) VALUES (?, ?)", rows)
        connection.commit()
        connection.close()
    (database / "Textures13.db").write_text(SENTINEL_PRIVATE)
    (userdata / "guisettings.xml").write_text(GUISETTINGS)
    for name in ("passwords.xml", "sources.xml", "advancedsettings.xml"):
        (userdata / name).write_text(f"<x>{SENTINEL_PRIVATE}</x>")
    data = userdata / "addon_data"
    (data / "plugin.video.redlight" / "tokens").mkdir(parents=True)
    (data / "plugin.video.redlight" / "settings.xml").write_text(SENTINEL_PRIVATE)
    (data / "plugin.video.redlight" / "tokens" / "trakt.json").write_text(SENTINEL_PRIVATE)
    own = data / bm.BUILD_MANAGER_ID
    (own / "private_overlays").mkdir(parents=True)
    (own / "private_overlays" / "overlay.json").write_text(SENTINEL_PRIVATE)
    (own / "frozen-artifacts").mkdir()
    (own / "frozen-artifacts" / "artifact.zip").write_bytes(b"zip")
    (own / "frozen_install_transaction.json").write_text(json.dumps(frozen_record()))
    (own / "frozen_install_transaction.lock").write_bytes(b"")
    (own / "restart_transaction.json").write_text(json.dumps(restart_record()))
    (own / "restart_transaction.lock").write_bytes(b"lock!")
    (own / bm.RESULT_FILENAME).write_text(json.dumps(adapter_payload("status")))
    (data / "other.addon").mkdir()
    (data / "other.addon" / "settings.xml").write_text(SENTINEL_PRIVATE)


class SnapshotTestCase(TripwireTestCase):
    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)
        self.manifest = install_good(self.target)
        make_profile(self.target)
        self.lister = FakeProcessLister()
        self.services = make_services(self.target, process_lister=self.lister)
        self.userdata = self.target.userdata_dir

    def snapshot(self, manifest=None, **kwargs):
        return bm.run_snapshot(
            self.services, manifest=manifest, manifest_sha256="e" * 64 if manifest else None, git_repo=None, **kwargs
        )


class TestSnapshot(SnapshotTestCase):
    def test_census_reports_the_expected_sanitized_state(self):
        payload = self.snapshot()
        self.assertTrue(payload["ok"])
        addons = {e["id"]: e for e in payload["installed_addons"]["entries"]}
        self.assertEqual(
            sorted(addons),
            sorted([bm.BUILD_MANAGER_ID, bm.DRIVER_ID, "plugin.video.redlight", "skin.arctic.fuse.3", "repository.example"]),
        )
        self.assertEqual(payload["installed_addons"]["count"], 5)
        self.assertEqual(payload["installed_addons"]["enabled_state_source"], "addons_db")
        self.assertIs(addons["plugin.video.redlight"]["enabled"], False)
        self.assertIs(addons["skin.arctic.fuse.3"]["enabled"], True)
        self.assertEqual(addons["plugin.video.redlight"]["version"], "2.6.8")
        self.assertEqual(payload["build_manager"], {"installed": True, "version": "0.1.0"})
        self.assertEqual(payload["driver"], {"installed": True, "version": "0.0.15"})
        self.assertEqual(payload["settings"], {
            "active_skin": "skin.arctic.fuse.3", "present": True, "readable": True,
            "source": "guisettings.xml", "updater_policy": "NEVER_CHECK",
        })
        transactions = payload["transactions"]
        self.assertEqual(transactions["frozen_transaction_state"], "present")
        self.assertEqual(transactions["restart_transaction_state"], "present")
        self.assertEqual(transactions["frozen_phase"], "needs_attention")
        self.assertEqual(transactions["frozen_lifecycle_stage"], "quiescence_awaiting_restart")
        self.assertEqual(transactions["frozen_lifecycle_restart_count"], 1)
        self.assertEqual(transactions["frozen_status_code"], "FROZEN_MANIFEST_INVALID")
        self.assertEqual((transactions["activation_hold_count"], transactions["redlight_hold_present"]), (1, True))
        self.assertIs(transactions["activation_hold_released"], False)
        self.assertEqual(transactions["original_update_policy"], "AUTOMATIC")
        self.assertEqual(transactions["resolution_record_count"], 3)
        self.assertEqual(transactions["restart_phase"], "awaiting_restart")
        self.assertEqual(transactions["restart_status_code"], "RESTART_REQUIRED_AFTER_RESUME")
        self.assertIs(transactions["restart_transaction_linked"], True)
        self.assertEqual((transactions["frozen_lock_file_present"], transactions["restart_lock_file_present"]), (True, True))
        self.assertEqual(transactions["sizes"]["restart_lock_file"], 5)
        self.assertEqual(transactions["sizes"]["frozen_lock_file"], 0)
        self.assertNotIn("adapter_version", transactions)
        self.assertEqual(payload["adapter_result_file"]["projection"], adapter_payload("status"))
        self.assertIsNone(payload["stage_manifest"])
        self.assertTrue(payload["private_data"]["denylist_enforced"])
        self.assertEqual(payload["private_data"]["denied_addon_data_ids"], ["plugin.video.redlight"])

    def test_output_never_contains_private_or_machine_specific_values(self):
        text = bm.canonical_json(self.snapshot(self.manifest))
        for secret in (
            SENTINEL_PASSWORD, SENTINEL_PRIVATE, "SENTINEL-STATUS-MESSAGE", STATUS_MESSAGE, FROZEN_ID,
            RESTART_ID, SESSION_ID, ADAPTER_VALUES["MANIFEST_PATH"], ADAPTER_VALUES["CONFIGURATION_PATH"],
            ADAPTER_VALUES["EXPECTED_OVERLAY_ID"], "fixture-device", "fixture-build", "webserverpassword",
            "webserverusername", "8089",
        ):
            self.assertNotIn(secret, text, secret)

    def test_private_and_unlisted_files_are_never_opened_listed_or_statted(self):
        with AccessRecorder(self.userdata, self.target.addons_dir) as recorder:
            self.snapshot()
        accessed = [path for _, path in recorder.log]
        for fragment in (
            "addon_data/plugin.video.redlight", "private_overlays", "frozen-artifacts", "passwords.xml",
            "sources.xml", "advancedsettings.xml", "Textures13", "/addons/packages", "/addons/temp",
            "other.addon", "tokens", "trakt.json",
        ):
            self.assertFalse([p for p in accessed if fragment in p], fragment)
        for expected in ("guisettings.xml", "Addons33.db", "frozen_install_transaction.json",
                         "restart_transaction.lock", bm.RESULT_FILENAME, "script.build.manager/addon.xml"):
            self.assertTrue([p for p in accessed if p.endswith(expected)], expected)
        self.assertFalse([p for p in accessed if p.endswith("Addons27.db")])  # only the newest DB is opened

    def test_read_guard_denylist_is_explicit_and_case_insensitive(self):
        guard = bm.ReadGuard(self.target)
        data = self.target.addon_data_dir
        for denied in (
            data / "plugin.video.redlight" / "settings.xml",
            data / "PLUGIN.VIDEO.REDLIGHT" / "settings.xml",
            data / "Plugin.Video.RedLight",
            data / bm.BUILD_MANAGER_ID / ".." / "plugin.video.redlight" / "settings.xml",
            data / "plugin.video.redlight" / "tokens" / "trakt.json",
            data / bm.BUILD_MANAGER_ID / "private_overlays" / "overlay.json",
            data / bm.BUILD_MANAGER_ID / "PRIVATE_OVERLAYS" / "overlay.json",
            data / bm.BUILD_MANAGER_ID / "private_overlays",
        ):
            with self.subTest(denied=os.fspath(denied)[-60:]), self.assertRaises(bm.HelperError) as raised:
                guard.require(denied)
            self.assertEqual(raised.exception.code, "private_path_denied")
        self.assertEqual(guard.refused, 8)

    def test_read_guard_allowlist_is_positive_and_closed(self):
        guard = bm.ReadGuard(self.target)
        userdata, addons = self.target.userdata_dir, self.target.addons_dir
        for allowed in (
            addons / "plugin.video.redlight" / "addon.xml", addons / bm.BUILD_MANAGER_ID / "addon.xml",
            userdata / "guisettings.xml", userdata / "Database" / "Addons33.db",
            self.target.bm_data_dir / "frozen_install_transaction.json",
            self.target.bm_data_dir / "frozen_install_transaction.lock",
            self.target.bm_data_dir / "restart_transaction.json",
            self.target.bm_data_dir / "restart_transaction.lock", self.target.result_path,
        ):
            with self.subTest(allowed=os.fspath(allowed)[-50:]):
                self.assertEqual(guard.require(allowed), allowed)
        for refused in (
            userdata / "passwords.xml", userdata / "sources.xml", userdata / "advancedsettings.xml",
            userdata / "Database" / "Textures13.db", userdata / "Database" / "Addons33.db-wal",
            userdata / "Database" / "Addons.db", userdata / "Database" / "Addonsx.db",
            self.target.bm_data_dir / "frozen-artifacts" / "artifact.zip", self.target.bm_data_dir / "settings.xml",
            self.target.addon_data_dir / "other.addon" / "settings.xml",
            addons / "packages" / "cached.zip", addons / bm.BUILD_MANAGER_ID / "default.py",
            addons / bm.BUILD_MANAGER_ID / "resources" / "settings.xml", addons / "bad name" / "addon.xml",
            addons / bm.BUILD_MANAGER_ID / "addon.xml.bak", self.target.portable_data / "temp" / "kodi.log",
            self.target.root / "Contents" / "Info.plist", Path("/etc/passwd"), self.tmp / "elsewhere.xml",
        ):
            with self.subTest(refused=os.fspath(refused)[-50:]), self.assertRaises(bm.HelperError) as raised:
                guard.require(refused)
            self.assertEqual(raised.exception.code, "read_not_allowlisted")

    def test_read_guard_refuses_symlinked_directories_in_the_chain(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "frozen_install_transaction.json").write_text("{}")
        shutil.rmtree(self.target.bm_data_dir)
        self.target.bm_data_dir.symlink_to(elsewhere)
        guard = bm.ReadGuard(self.target)
        with self.assertRaises(bm.HelperError) as raised:
            guard.require(self.target.bm_data_dir / "frozen_install_transaction.json")
        self.assertEqual(raised.exception.code, "bundle_path_symlink")
        with self.assertRaises(bm.HelperError):
            self.snapshot()

    def test_symlinked_transaction_file_is_unreadable_and_never_followed(self):
        outside = self.tmp / "outside.json"
        outside.write_text(json.dumps(frozen_record(status_code="FROZEN_RESUME_FAILED")))
        record = self.target.bm_data_dir / "frozen_install_transaction.json"
        record.unlink()
        record.symlink_to(outside)
        payload = self.snapshot()
        self.assertEqual(payload["transactions"]["frozen_transaction_state"], "unreadable")
        self.assertIsNone(payload["transactions"]["frozen_phase"])
        self.assertIsNone(payload["transactions"]["sizes"]["frozen_transaction_file"])

    def test_fifo_transaction_file_does_not_block(self):
        record = self.target.bm_data_dir / "restart_transaction.json"
        record.unlink()
        os.mkfifo(record)
        done = []
        worker = threading.Thread(target=lambda: done.append(self.snapshot()), daemon=True)
        worker.start()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "snapshot blocked on a FIFO")
        self.assertEqual(done[0]["transactions"]["restart_transaction_state"], "unreadable")

    def test_corrupt_and_oversized_transaction_files_report_state_only(self):
        (self.target.bm_data_dir / "frozen_install_transaction.json").write_text("{corrupt")
        (self.target.bm_data_dir / "restart_transaction.json").write_text(json.dumps(["not", "an", "object"]))
        payload = self.snapshot()
        self.assertEqual(payload["transactions"]["frozen_transaction_state"], "invalid")
        self.assertEqual(payload["transactions"]["restart_transaction_state"], "invalid")
        (self.target.bm_data_dir / "frozen_install_transaction.json").write_text(" " * (1024 * 1024 + 10))
        self.assertEqual(self.snapshot()["transactions"]["frozen_transaction_state"], "invalid")

    def test_hostile_transaction_values_are_dropped_not_echoed(self):
        record = frozen_record(phase="INJECTED-PHASE", lifecycle_stage="INJECTED-STAGE",
                               status_code="INJECTED-CODE", lifecycle_restart_count=10 ** 9)
        (self.target.bm_data_dir / "frozen_install_transaction.json").write_text(json.dumps(record))
        payload = self.snapshot()
        text = bm.canonical_json(payload)
        self.assertNotIn("INJECTED", text)
        self.assertIsNone(payload["transactions"]["frozen_phase"])
        self.assertIsNone(payload["transactions"]["frozen_status_code"])
        self.assertIsNone(payload["transactions"]["frozen_lifecycle_restart_count"])

    def test_empty_profile_reports_absence_and_creates_nothing(self):
        base = self.tmp / "empty"
        base.mkdir()
        target = make_fake_app(base)
        services = make_services(target, process_lister=FakeProcessLister())
        before = fingerprint(target.root)
        payload = bm.run_snapshot(services, manifest=None, manifest_sha256=None, git_repo=None)
        self.assertEqual(fingerprint(target.root), before)
        self.assertEqual(payload["installed_addons"]["count"], 0)
        self.assertEqual(payload["installed_addons"]["enabled_state_source"], "unavailable")
        self.assertEqual(payload["transactions"]["frozen_transaction_state"], "absent")
        self.assertIs(payload["transactions"]["frozen_lock_file_present"], False)
        self.assertEqual(payload["settings"]["present"], False)
        self.assertEqual(payload["adapter_result_file"], {"present": False})
        self.assertEqual(payload["build_manager"], {"installed": False, "version": None})

    def test_database_variants_degrade_to_unavailable(self):
        database = self.userdata / "Database"
        (database / "Addons33.db").write_bytes(b"this is not an sqlite database" * 20)
        payload = self.snapshot()
        self.assertEqual(payload["installed_addons"]["enabled_state_source"], "unavailable")
        self.assertTrue(all(e["enabled"] is None for e in payload["installed_addons"]["entries"]))
        (database / "Addons33.db").unlink()
        connection = sqlite3.connect(database / "Addons33.db")
        connection.execute("CREATE TABLE other (x)")
        connection.commit()
        connection.close()
        self.assertEqual(self.snapshot()["installed_addons"]["enabled_state_source"], "unavailable")

    def test_newest_database_is_selected_and_decoys_are_ignored(self):
        database = self.userdata / "Database"
        for name in ("Addons99.db-journal", "Addons.db", "Addonsx.db", "Addons34.db.bak"):
            (database / name).write_text("decoy")
        self.assertEqual(self.snapshot()["installed_addons"]["enabled_state_source"], "addons_db")
        connection = sqlite3.connect(database / "Addons40.db")
        connection.execute("CREATE TABLE installed (addonID TEXT, enabled BOOLEAN)")
        connection.execute("INSERT INTO installed VALUES ('plugin.video.redlight', 1)")
        connection.commit()
        connection.close()
        entries = {e["id"]: e for e in self.snapshot()["installed_addons"]["entries"]}
        self.assertIs(entries["plugin.video.redlight"]["enabled"], True)
        self.assertIsNone(entries["skin.arctic.fuse.3"]["enabled"])

    def test_reading_the_database_changes_nothing(self):
        database = self.userdata / "Database"
        before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in database.iterdir()}
        self.snapshot()
        self.snapshot()
        self.assertEqual({p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in database.iterdir()}, before)
        self.assertEqual(sorted(before), sorted(p.name for p in database.iterdir()))

    def test_hostile_addon_metadata_is_skipped_and_counted(self):
        addons = self.target.addons_dir
        (addons / "doctype.addon").mkdir()
        (addons / "doctype.addon" / "addon.xml").write_text('<!DOCTYPE a [<!ENTITY x "y">]><addon id="doctype.addon" version="1"/>')
        (addons / "mismatch.addon").mkdir()
        (addons / "mismatch.addon" / "addon.xml").write_text('<addon id="other.id" version="1"/>')
        (addons / "no.xml").mkdir()
        (addons / "bad name").mkdir()
        (addons / "a-file.txt").write_text("x")
        (addons / "linked.addon").symlink_to(self.tmp)
        (addons / "xml.link").mkdir()
        (addons / "xml.link" / "addon.xml").symlink_to(self.tmp / "target.xml")
        (addons / "huge.addon").mkdir()
        (addons / "huge.addon" / "addon.xml").write_text("<addon id='huge.addon' version='1'/>" + " " * (bm.MAX_XML_BYTES + 1))
        payload = self.snapshot()["installed_addons"]
        ids = {e["id"] for e in payload["entries"]}
        for hostile in ("doctype.addon", "mismatch.addon", "no.xml", "linked.addon", "xml.link", "huge.addon"):
            self.assertNotIn(hostile, ids)
        self.assertEqual(payload["count"], 5)
        self.assertEqual(payload["id_mismatch"], 1)
        self.assertEqual(payload["skipped_invalid_names"], 1)
        self.assertEqual(payload["skipped_non_directories"], 2)  # the file and the symlink
        self.assertEqual(payload["unreadable_addon_xml"], 4)

    def test_guisettings_extraction_returns_only_the_wanted_values(self):
        wanted = ("general.addonupdates", "lookandfeel.skin")
        values = bm.extract_settings(GUISETTINGS.encode(), wanted)
        self.assertEqual(values, {"general.addonupdates": "2", "lookandfeel.skin": "skin.arctic.fuse.3"})
        self.assertNotIn(SENTINEL_PASSWORD, json.dumps(values))
        duplicate = GUISETTINGS.replace("</settings>", '<setting id="lookandfeel.skin">skin.other</setting></settings>')
        self.assertIsNone(bm.extract_settings(duplicate.encode(), wanted)["lookandfeel.skin"])
        self.assertEqual(bm.extract_settings(b"<settings/>", wanted), {key: None for key in wanted})
        for hostile in (b'<!DOCTYPE s [<!ENTITY x "y">]><settings/>', b"<settings><!ENTITY"):
            with self.assertRaises(ValueError):
                bm.extract_settings(hostile, wanted)
        with self.assertRaises(ET_ParseError):
            bm.extract_settings(b"<settings><setting", wanted)

    def test_guisettings_values_are_validated(self):
        path = self.userdata / "guisettings.xml"
        for body, policy, skin in (
            ('<setting id="general.addonupdates">7</setting><setting id="lookandfeel.skin">ok.skin</setting>', None, "ok.skin"),
            ('<setting id="general.addonupdates">0</setting><setting id="lookandfeel.skin">bad skin!</setting>', "AUTOMATIC", None),
            ('<setting id="general.addonupdates">1</setting>', "NOTIFY_ONLY", None),
            ('<setting id="general.addonupdates"></setting><setting id="lookandfeel.skin"></setting>', None, None),
        ):
            path.write_text(f"<settings>{body}</settings>")
            report = bm.read_guisettings(self.target, bm.ReadGuard(self.target))
            self.assertEqual((report["updater_policy"], report["active_skin"]), (policy, skin), body)
        path.write_text("<settings><setting")
        self.assertEqual(
            bm.read_guisettings(self.target, bm.ReadGuard(self.target)),
            {"active_skin": None, "present": True, "readable": False, "source": "guisettings.xml", "updater_policy": None},
        )
        path.write_text(" " * (bm.MAX_XML_BYTES + 1))
        self.assertFalse(bm.read_guisettings(self.target, bm.ReadGuard(self.target))["readable"])
        path.unlink()
        self.assertEqual(bm.read_guisettings(self.target, bm.ReadGuard(self.target))["present"], False)

    def test_manifest_option_adds_identity_and_installed_tree_verification(self):
        payload = self.snapshot(self.manifest)
        identity = payload["stage_manifest"]
        self.assertEqual(identity["candidate_commit"], FIXTURE.good)
        self.assertEqual(identity["manifest_sha256"], "e" * 64)
        self.assertEqual(identity["build_manager_version"], "0.1.0")
        self.assertEqual(identity["driver_adapter_version"], "0.0.15")
        self.assertEqual(identity["configuration_fingerprint"], bm.config_fingerprint(ADAPTER_VALUES))
        self.assertTrue(payload["stage_verification"]["installed_equals_manifest"])
        (self.target.addon_dir(bm.BUILD_MANAGER_ID) / "service.py").write_text("# drift\n")
        drifted = self.snapshot(self.manifest)
        self.assertTrue(drifted["ok"])  # a census still completes
        self.assertFalse(drifted["stage_verification"]["installed_equals_manifest"])

    def test_snapshot_is_allowed_while_running_but_needs_a_clean_identity(self):
        self.lister.run_test_app(self.target, pid=321)
        self.assertEqual(self.snapshot()["identity"]["process"]["state"], "running_portable")
        self.lister.processes.append(bm.ProcessInfo(9, "/Applications/Kodi.app/Contents/MacOS/Kodi"))
        with self.assertRaises(bm.HelperError) as raised:
            self.snapshot()
        self.assertEqual(raised.exception.code, "foreign_kodi_process_present")
        self.lister.processes.pop()
        self.lister.commands[321] = self.lister.processes[0].exe
        with self.assertRaises(bm.HelperError) as raised:
            self.snapshot()
        self.assertEqual(raised.exception.code, "test_app_not_portable")

    def test_missing_layout_is_refused(self):
        base = self.tmp / "nolayout"
        base.mkdir()
        target = make_fake_app(base, userdata=False)
        with self.assertRaises(bm.HelperError) as raised:
            bm.run_snapshot(make_services(target), manifest=None, manifest_sha256=None, git_repo=None)
        self.assertEqual(raised.exception.code, "layout_missing")

    def test_snapshot_is_read_only_and_deterministic(self):
        before = fingerprint(self.target.root)
        times = {p: p.stat().st_mtime_ns for p in self.target.root.rglob("*")}
        first = bm.canonical_json(self.snapshot(self.manifest))
        second = bm.canonical_json(self.snapshot(self.manifest))
        self.assertEqual(first, second)
        self.assertEqual(fingerprint(self.target.root), before)
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.target.root.rglob("*")}, times)

    def test_result_file_census_handles_unusual_content(self):
        result = self.target.result_path
        result.write_text("{not json")
        self.assertEqual(self.snapshot()["adapter_result_file"]["projection_error"], "result_malformed")
        result.write_text(json.dumps({"ok": True, "adapter_mode": "mystery"}))
        self.assertEqual(self.snapshot()["adapter_result_file"]["projection_error"], "result_malformed")
        result.write_text(json.dumps(adapter_payload("retry", leaked=SENTINEL_PRIVATE)))
        report = self.snapshot()["adapter_result_file"]
        self.assertEqual(report["projection"]["adapter_mode"], "retry")
        self.assertEqual(report["withheld"]["unknown_key_count"], 1)
        self.assertNotIn(SENTINEL_PRIVATE, json.dumps(report))
        result.unlink()
        result.symlink_to(self.tmp / "target.json")
        with self.assertRaises(bm.HelperError) as raised:
            self.snapshot()
        self.assertEqual(raised.exception.code, "result_path_unsafe")


ET_ParseError = __import__("xml.etree.ElementTree", fromlist=["ParseError"]).ParseError


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

class TestCli(TripwireTestCase):
    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)
        self.lister = FakeProcessLister()
        self.services = make_services(self.target, process_lister=self.lister, tmp_root=self.tmp)
        self.manifest_file = self.tmp / "stage_manifest.json"
        self.manifest_file.write_bytes(bm.manifest_bytes(good_plan()[2]))

    def test_identify_prints_one_deterministic_sorted_ascii_json_document(self):
        code, payload, text = run_cli(self.services, "identify")
        self.assertEqual(code, bm.EXIT_OK)
        self.assertEqual(text, bm.canonical_json(json.loads(text)))
        self.assertTrue(text.isascii())
        self.assertEqual(payload["schema"], bm.OUTPUT_SCHEMA)
        self.assertEqual(payload["command"], "identify")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["process"]["state"], "not_running")
        self.assertEqual(payload["bundle"]["identifier"], "org.xbmc.kodi")
        _, _, again = run_cli(self.services, "identify")
        self.assertEqual(text, again)

    def test_tool_identity_binds_the_evidence_to_this_exact_helper(self):
        _, payload, _ = run_cli(self.services, "identify")
        self.assertEqual(payload["tool"]["sha256"], hashlib.sha256(Path(bm.__file__).read_bytes()).hexdigest())
        self.assertEqual(payload["tool"]["name"], "bm_test_app")

    def test_usage_errors_exit_two_with_a_fixed_code_and_no_echo(self):
        for argv in (
            [], ["bogus"], ["stage"], ["run", "install"], ["run", "reboot", "--manifest", "x"],
            ["run", "status", "--manifest", "x", "--rpc-port", "abc"], ["verify", "--manifest"],
            ["identify", "--app", "/tmp/x"], ["identify", "extra"], ["stage", "--candidate", "SECRET-ECHO"],
        ):
            with self.subTest(argv=argv):
                code, payload, text = run_cli(self.services, *argv)
                self.assertEqual(code, bm.EXIT_USAGE)
                self.assertEqual(payload["error"]["code"], "argument_invalid")
                self.assertNotIn("SECRET-ECHO", text)
                self.assertIs(payload["ok"], False)

    def test_exit_codes_distinguish_failure_classes(self):
        self.lister.processes.append(bm.ProcessInfo(7, "/Applications/Kodi.app/Contents/MacOS/Kodi"))
        code, payload, _ = run_cli(self.services, "identify")
        self.assertEqual((code, payload["error"]["code"]), (bm.EXIT_FAILED, "foreign_kodi_process_present"))
        self.lister.processes.clear()
        code, payload, _ = run_cli(self.services, "stage", "--candidate", FIXTURE.good, "--config", str(self.tmp / "nope.json"))
        self.assertEqual((code, payload["error"]["code"]), (bm.EXIT_USAGE, "argument_path_not_found"))

    def test_output_file_is_exclusive_and_matches_stdout(self):
        out = self.tmp / "evidence.json"
        code, _, text = run_cli(self.services, "identify", "--output", str(out))
        self.assertEqual(code, 0)
        self.assertEqual(out.read_text(), text)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        original = out.read_text()
        code, payload, _ = run_cli(self.services, "identify", "--output", str(out))
        self.assertEqual((code, payload["error"]["code"]), (bm.EXIT_USAGE, "output_exists"))
        self.assertEqual(out.read_text(), original)

    def test_output_path_hygiene(self):
        cases = {
            "missing parent": (str(self.tmp / "no" / "x.json"), "argument_path_not_found"),
            "inside app": (str(self.target.root / "Contents" / "out.json"), "argument_path_inside_test_app"),
            "normal kodi": ("/Applications/Kodi.app/out.json", "argument_path_forbidden"),
            "normal profile": ("/Users/eengert/Library/Application Support/Kodi/out.json", "argument_path_forbidden"),
        }
        link = self.tmp / "linkdir"
        link.symlink_to(self.tmp)
        cases["symlinked dir"] = (str(link / "out.json"), "argument_path_symlink")
        for label, (target, code) in cases.items():
            with self.subTest(case=label):
                result, payload, _ = run_cli(self.services, "identify", "--output", target)
                self.assertEqual((result, payload["error"]["code"]), (bm.EXIT_USAGE, code))
        self.assertEqual(self.tripwire.touched, [])

    def test_failures_are_also_written_as_evidence(self):
        self.lister.processes.append(bm.ProcessInfo(7, "/Applications/Kodi.app/Contents/MacOS/Kodi"))
        out = self.tmp / "failure.json"
        code, payload, text = run_cli(self.services, "identify", "--output", str(out))
        self.assertEqual(code, bm.EXIT_FAILED)
        self.assertEqual(json.loads(out.read_text())["error"]["code"], "foreign_kodi_process_present")

    def test_unexpected_exceptions_never_leak_their_text(self):
        with mock.patch.object(bm, "identify", side_effect=RuntimeError("SENSITIVE-DETAIL /Users/x/secret")):
            code, payload, text = run_cli(self.services, "identify")
        self.assertEqual(code, bm.EXIT_FAILED)
        self.assertEqual(payload["error"]["code"], "unexpected_error")
        self.assertEqual(payload["error"]["detail"], {"exception_type": "RuntimeError"})
        self.assertNotIn("SENSITIVE", text)

    def test_keyboard_interrupt_is_reported_as_interrupted(self):
        with mock.patch.object(bm, "identify", side_effect=KeyboardInterrupt):
            code, payload, _ = run_cli(self.services, "identify")
        self.assertEqual((code, payload["error"]["code"]), (bm.EXIT_INTERRUPTED, "interrupted"))

    def test_registered_secrets_block_the_whole_output(self):
        self.services.secrets.register("org.xbmc.kodi")
        out = self.tmp / "blocked.json"
        code, payload, text = run_cli(self.services, "identify", "--output", str(out))
        self.assertEqual((code, payload["error"]["code"]), (bm.EXIT_FAILED, "output_blocked_secret_detected"))
        self.assertNotIn("org.xbmc.kodi", text)
        self.assertFalse(out.exists())

    def test_stage_verify_snapshot_end_to_end_through_the_cli(self):
        config = make_config(self.tmp)
        evidence = self.tmp / "evidence"
        evidence.mkdir()
        code, payload, text = run_cli(
            self.services, "stage", "--candidate", FIXTURE.good, "--config", str(config),
            "--evidence-dir", str(evidence), "--repo", str(FIXTURE.repo),
        )
        self.assertEqual((code, payload["ok"]), (0, True), text[:300])
        for value in ADAPTER_VALUES.values():
            if value.startswith("/"):
                self.assertNotIn(value, text)
        manifest_path = payload["evidence"]["manifest_path"]
        code, verified, _ = run_cli(self.services, "verify", "--manifest", manifest_path, "--repo", str(FIXTURE.repo))
        self.assertEqual(code, 0)
        self.assertTrue(verified["installed_equals_candidate"])
        self.assertEqual(verified["manifest_sha256"], payload["manifest_sha256"])
        self.assertEqual(verified["candidate_commit"], FIXTURE.good)
        code, weak, _ = run_cli(self.services, "verify", "--manifest", manifest_path, "--no-git-binding")
        self.assertEqual(code, 0)
        self.assertFalse(weak["installed_equals_candidate"])
        code, snap, _ = run_cli(self.services, "snapshot", "--manifest", manifest_path, "--repo", str(FIXTURE.repo))
        self.assertEqual((code, snap["ok"]), (0, True))
        self.assertTrue(snap["stage_verification"]["installed_equals_candidate"])
        (self.target.addon_dir(bm.BUILD_MANAGER_ID) / "service.py").write_text("# drift\n")
        code, bad, _ = run_cli(self.services, "verify", "--manifest", manifest_path, "--repo", str(FIXTURE.repo))
        self.assertEqual((code, bad["ok"]), (bm.EXIT_FAILED, False))

    def test_stage_dry_run_via_cli_needs_no_evidence_dir_and_changes_nothing(self):
        before = fingerprint(self.target.root)
        code, payload, _ = run_cli(
            self.services, "stage", "--candidate", FIXTURE.good, "--config", str(make_config(self.tmp)),
            "--repo", str(FIXTURE.repo), "--dry-run",
        )
        self.assertEqual((code, payload["dry_run"]), (0, True))
        self.assertEqual(fingerprint(self.target.root), before)

    def test_cli_path_arguments_are_hygienic(self):
        config = make_config(self.tmp)
        inside = self.target.root / "Contents" / "evidence"
        inside.mkdir()
        for flag, value, code in (
            ("--evidence-dir", str(inside), "argument_path_inside_test_app"),
            ("--repo", "/Applications/Kodi.app", "argument_path_forbidden"),
        ):
            with self.subTest(flag=flag):
                result, payload, _ = run_cli(
                    self.services, "stage", "--candidate", FIXTURE.good, "--config", str(config), flag, value
                )
                self.assertEqual((result, payload["error"]["code"]), (bm.EXIT_USAGE, code))
        loose = self.tmp / "loose.json"
        loose.write_text(json.dumps({"schema": bm.CONFIG_SCHEMA}))
        loose.chmod(0o666)
        result, payload, _ = run_cli(self.services, "stage", "--candidate", FIXTURE.good, "--config", str(loose))
        self.assertEqual((result, payload["error"]["code"]), (bm.EXIT_USAGE, "config_unsafe_permissions"))

    def test_run_through_the_cli_maps_adapter_outcomes_to_exit_codes(self):
        world = RunWorld(self, "cli-run")
        manifest_file = self.tmp / "cli-manifest.json"
        manifest_file.write_bytes(bm.manifest_bytes(world.manifest))
        world.produce_on_sleep(adapter_payload("status"))
        code, payload, text = run_cli(
            world.services, "run", "status", "--manifest", str(manifest_file), "--rpc-port", "8080", "--no-git-binding"
        )
        self.assertEqual((code, payload["ok"], payload["adapter_ok"]), (0, True, True), text[:300])
        self.assertEqual(payload["invocation"]["rpc_port"], 8080)
        failing = RunWorld(self, "cli-run-fail")
        failure = {"ok": False, "adapter_mode": "retry", "error_type": "OSError", "adapter_stage": "INVOKE_RETRY",
                   "failing_callable": "FrozenInstallCoordinator.retry_held_quiescence",
                   "failure_category": "retry_invocation_failed"}
        failing.produce_on_sleep(failure)
        code, payload, _ = run_cli(
            failing.services, "run", "retry", "--manifest", str(manifest_file), "--rpc-port", "8080", "--no-git-binding"
        )
        self.assertEqual((code, payload["ok"], payload["adapter_ok"]), (bm.EXIT_ADAPTER_FAILED, True, False))
        stale = RunWorld(self, "cli-run-stale")
        code, payload, _ = run_cli(
            stale.services, "run", "status", "--manifest", str(manifest_file), "--rpc-port", "8080",
            "--timeout", "2", "--no-git-binding",
        )
        self.assertEqual((code, payload["error"]["code"]), (bm.EXIT_FAILED, "result_not_produced"))

    def test_run_cli_rpc_precedence_and_validation(self):
        world = RunWorld(self, "cli-rpc")
        manifest_file = self.tmp / "rpc-manifest.json"
        manifest_file.write_bytes(bm.manifest_bytes(world.manifest))
        config = make_config(self.tmp, adapter=False, rpc={"host": "127.0.0.1", "port": 9001, "username": "cfguser"})
        world.produce_on_sleep(adapter_payload("status"))
        code, payload, _ = run_cli(world.services, "run", "status", "--manifest", str(manifest_file),
                                   "--config", str(config), "--rpc-port", "9002", "--no-git-binding")
        self.assertEqual(code, 0)
        self.assertEqual(payload["invocation"]["rpc_port"], 9002)  # the command line wins
        for extra, expected in (
            (["--rpc-host", "10.1.2.3"], "rpc_host_not_loopback"), (["--rpc-port", "0"], "rpc_port_invalid"),
            (["--rpc-user", "bad user"], "rpc_config_invalid"), (["--timeout", "0"], "argument_invalid"),
            (["--timeout", "99999"], "argument_invalid"),
        ):
            with self.subTest(extra=extra):
                other = RunWorld(self, "cli-rpc-" + extra[0][2:] + extra[1].replace(".", "_").replace(" ", "_"))
                code, payload, _ = run_cli(other.services, "run", "status", "--manifest", str(manifest_file),
                                           "--rpc-port", "8080", *extra, "--no-git-binding")
                self.assertEqual((code, payload["error"]["code"]), (bm.EXIT_USAGE, expected))
                self.assertEqual(other.transport.requests, [])

    def test_the_real_entry_point_has_no_override_and_touches_nothing_on_usage_errors(self):
        # Runs the actual script in a subprocess with its production wiring; the
        # argument error is raised before any target is touched.
        for argv in (["identify", "--app", "/tmp/not-the-test-app"], ["bogus"], []):
            proc = subprocess.run(
                [sys.executable, "-B", str(PROJECT / "tools" / "bm_test_app.py"), *argv],
                capture_output=True, text=True, cwd=str(self.tmp),
            )
            self.assertEqual(proc.returncode, bm.EXIT_USAGE, argv)
            document = json.loads(proc.stdout)
            self.assertEqual(document["error"]["code"], "argument_invalid")
            self.assertEqual(proc.stderr, "")
        proc = subprocess.run(
            [sys.executable, "-B", str(PROJECT / "tools" / "bm_test_app.py"), "--help"],
            capture_output=True, text=True, cwd=str(self.tmp),
        )
        self.assertEqual(proc.returncode, 0)
        for subcommand in ("identify", "stage", "verify", "run", "snapshot"):
            self.assertIn(subcommand, proc.stdout)
        self.assertNotIn("--app", proc.stdout)


# ---------------------------------------------------------------------------
# Static safety properties of the helper source
# ---------------------------------------------------------------------------

HELPER_SOURCE = (PROJECT / "tools" / "bm_test_app.py").read_text(encoding="utf-8")
HELPER_TREE = ast.parse(HELPER_SOURCE)


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def enclosing_functions():
    """Map each Call node to the name of its innermost enclosing function."""
    owners = {}

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            current = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
            if isinstance(child, ast.Call):
                owners[child] = current
            visit(child, current)

    visit(HELPER_TREE, "<module>")
    return owners


class TestStaticSafety(unittest.TestCase):
    @staticmethod
    def _branch_constants(node):
        """String constants a code expression can evaluate to (not its conditions)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.IfExp):
            yield from TestStaticSafety._branch_constants(node.body)
            yield from TestStaticSafety._branch_constants(node.orelse)

    def error_codes_used(self):
        used = set()
        for node in ast.walk(HELPER_TREE):
            if isinstance(node, ast.FunctionDef):
                # A parameter named `failure` carries an error code; count its default.
                arguments = node.args.args + node.args.kwonlyargs
                defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
                defaults += list(node.args.kw_defaults)
                for argument, default in zip(arguments, defaults):
                    if argument.arg == "failure" and default is not None:
                        used.update(self._branch_constants(default))
            if not isinstance(node, ast.Call):
                continue
            candidates = []
            if isinstance(node.func, ast.Name) and node.func.id == "HelperError" and node.args:
                candidates.append(node.args[0])
            candidates += [kw.value for kw in node.keywords if kw.arg == "failure"]
            for candidate in candidates:
                used.update(self._branch_constants(candidate))
        return used

    def test_every_emitted_error_code_is_registered_and_every_registered_code_is_used(self):
        used = self.error_codes_used()
        self.assertEqual(used - bm.ERROR_CODES, set(), "unregistered codes")
        self.assertEqual(bm.ERROR_CODES - used - {"internal_error"}, set(), "dead codes")
        self.assertLessEqual(bm._USAGE_CODES, bm.ERROR_CODES)

    def test_no_shell_and_every_subprocess_call_is_bounded(self):
        for node in ast.walk(HELPER_TREE):
            if isinstance(node, ast.Call):
                keywords = {kw.arg: kw.value for kw in node.keywords}
                if "shell" in keywords:
                    self.assertIsInstance(keywords["shell"], ast.Constant)
                    self.assertIs(keywords["shell"].value, False)
                if "env" in keywords:
                    self.assertIn("timeout", keywords, ast.dump(node)[:80])
                    self.assertIn("shell", keywords)
        self.assertNotIn("shell=True", HELPER_SOURCE)

    def test_no_environment_credentials_no_stdin_prompts_no_dynamic_code(self):
        banned_attributes = {"os.environ", "os.getenv", "os.putenv", "os.system", "os.popen", "os.execv", "os.spawnv"}
        banned_names = {"input", "eval", "exec", "compile", "__import__", "breakpoint"}
        for node in ast.walk(HELPER_TREE):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(dotted(node), banned_attributes)
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, banned_names)
        owners = enclosing_functions()
        getpass_callers = {owners[n] for n in owners if dotted(n.func) == "getpass.getpass"}
        self.assertEqual(getpass_callers, {"interactive_password_prompt"})

    def test_only_expected_modules_are_imported_and_no_network_libraries(self):
        imported = set()
        for node in ast.walk(HELPER_TREE):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        allowed = {
            "__future__", "argparse", "ast", "base64", "ctypes", "errno", "getpass", "hashlib", "http", "io", "ipaddress", "json",
            "os", "plistlib", "re", "secrets", "shutil", "sqlite3", "stat", "subprocess", "sys", "tempfile",
            "time", "unicodedata", "urllib", "warnings", "xml", "dataclasses", "datetime", "pathlib", "types",
            "typing", "tools",
        }
        self.assertEqual(imported - allowed, set())
        for network in ("socket", "requests", "ssl", "ftplib", "smtplib", "telnetlib", "xmlrpc", "webbrowser"):
            self.assertNotIn(network, imported)
        for node in ast.walk(HELPER_TREE):
            if isinstance(node, ast.ImportFrom) and node.module == "urllib":
                self.fail("urllib.* helpers other than urllib.parse are not allowed")
        self.assertNotIn("urllib.request", HELPER_SOURCE)

    def test_forbidden_surfaces_appear_only_as_the_lexical_denylist_constants(self):
        self.assertEqual(HELPER_SOURCE.count("/Applications/Kodi.app"), 1)
        self.assertEqual(HELPER_SOURCE.count("Library/Application Support/Kodi"), 1)
        for node in HELPER_TREE.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in ("_NORMAL_KODI_APP", "_NORMAL_KODI_PROFILE_LITERAL")
                for t in node.targets
            ):
                break
        else:
            self.fail("denylist constants missing")

    def test_destructive_operations_are_confined_to_named_functions(self):
        owners = enclosing_functions()
        found = {}
        for node, owner in owners.items():
            name = dotted(node.func)
            if name in {"shutil.rmtree", "os.unlink", "os.remove", "os.rmdir", "shutil.move", "os.replace",
                        "os.rename", "os.link", "os.symlink", "shutil.copytree", "os.truncate"}:
                found.setdefault(name, set()).add(owner)
        self.assertEqual(found, {
            "shutil.rmtree": {"run_stage", "_remove_stage_area"},
            "os.unlink": {"write_new_file_atomic"},
            "os.rename": {"_swap_in", "_rollback"},
            "os.link": {"write_new_file_atomic"},
            "os.symlink": {"copy_tree_exact"},
        })

    def test_only_the_production_wiring_constructs_the_authorized_target(self):
        owners = enclosing_functions()
        callers = {owner for node, owner in owners.items() if dotted(node.func) == "TestAppTarget.authorized"}
        self.assertEqual(callers, {"production"})
        self.assertEqual(
            {owner for node, owner in owners.items() if dotted(node.func) == "cls" and False}, set()
        )

    def test_error_details_never_carry_credential_field_names(self):
        banned = {"password", "token", "authorization", "secret", "header", "credential", "cookie"}
        for node in ast.walk(HELPER_TREE):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "HelperError":
                for keyword in node.keywords:
                    self.assertNotIn((keyword.arg or "").lower(), banned)

    def test_module_has_no_import_time_side_effects(self):
        allowed = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign, ast.If)
        for node in HELPER_TREE.body:
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)  # the docstring only
                continue
            self.assertIsInstance(node, allowed, ast.dump(node)[:60])
            if isinstance(node, ast.If):
                condition = ast.unparse(node.test)
                self.assertIn(condition, ("str(PROJECT) not in sys.path", "__name__ == '__main__'"))

    def test_helper_imports_only_the_adapter_vocabulary_from_this_repository(self):
        repo_imports = []
        for node in ast.walk(HELPER_TREE):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tools":
                repo_imports.append((node.module, tuple(alias.name for alias in node.names)))
            if isinstance(node, ast.Import):
                self.assertFalse([a for a in node.names if a.name.split(".")[0] in ("tools", "resources", "xbmc", "xbmcvfs")])
        self.assertEqual(repo_imports, [("tools", ("bm023a_adapter_support",))])



class TestSanctionedAuxiliaryProcess(TripwireTestCase):
    """Exactly one kernel-identified XBMCHelper at its exact path is a sanctioned
    auxiliary; nothing broader is. Fake process listings only: no live Kodi."""

    MAIN_PID = 4242
    AUX_PID = 5151
    LOOKALIKES = (
        "Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper2",
        "Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper-copy",
        "Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper ",
        "Contents/Resources/Kodi/tools/darwin/runtime/xbmchelper",
        "Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper/XBMCHelper",
        "Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper.app/Contents/MacOS/XBMCHelper",
        "Contents/Resources/Kodi/tools/darwin/runtime/../runtime/XBMCHelper",
        "Contents/Resources/Kodi/tools/darwin/runtime//XBMCHelper",
        "Contents/Resources/Kodi/tools/darwin/XBMCHelper",
        "Contents/Resources/Kodi/tools/darwin/other/XBMCHelper",
        "Contents/Resources/Kodi/tools/XBMCHelper",
        "Contents/MacOS/XBMCHelper",
    )

    def setUp(self):
        super().setUp()
        self.target = make_fake_app(self.tmp)
        self.aux = os.fspath(self.target.auxiliary_executable)
        self.aux_alias = bm._DATA_VOLUME_ALIAS + self.aux
        self.lister = FakeProcessLister([
            bm.ProcessInfo(1, "/sbin/launchd"),
            bm.ProcessInfo(2, "/usr/bin/python3"),
        ])
        self.services = make_services(self.target, process_lister=self.lister)

    def inside(self, relative):
        # String concatenation on purpose: pathlib would normalize some lookalikes.
        return f"{os.fspath(self.target.root)}/{relative}"

    def lister_with(self, *processes, main=True, flags=" -p"):
        lister = FakeProcessLister()
        if main:
            lister.run_test_app(self.target, pid=self.MAIN_PID, flags=flags)
        lister.processes.extend(processes)
        return lister

    def refusal(self, lister, **kwargs):
        with self.assertRaises(bm.HelperError) as raised:
            bm.identify(make_services(self.target, process_lister=lister), **kwargs)
        return raised.exception

    # -- the exact sanctioned identity ---------------------------------------

    def test_the_sanctioned_path_is_exact_and_derived_from_the_bundle_root(self):
        authorized = bm.TestAppTarget.authorized()
        expected = (
            "/Applications/Kodi Build Manager Test.app"
            "/Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper"
        )
        self.assertEqual(os.fspath(authorized.auxiliary_executable), expected)
        self.assertEqual(
            authorized.auxiliary_aliases(), (expected, "/System/Volumes/Data" + expected)
        )
        self.assertEqual(
            self.aux,
            os.fspath(self.target.root / "Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper"),
        )
        self.assertEqual(self.target.auxiliary_aliases(), (self.aux, self.aux_alias))

    def test_classification_puts_only_the_exact_path_in_the_auxiliary_bucket(self):
        main = bm.ProcessInfo(1, os.fspath(self.target.macos_dir / "Kodi"))
        exact = [bm.ProcessInfo(2, self.aux), bm.ProcessInfo(3, self.aux_alias)]
        lookalikes = [bm.ProcessInfo(10 + i, self.inside(rel)) for i, rel in enumerate(self.LOOKALIKES)]
        outside = [
            bm.ProcessInfo(40, "/usr/local/bin/XBMCHelper"),
            bm.ProcessInfo(41, os.fspath(self.tmp / "Kodi Build Manager Test.app.bak"
                                         / "Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper")),
        ]
        view = bm.classify_processes([main, *exact, *lookalikes, *outside], self.target, "Kodi")
        self.assertEqual([p.pid for p in view.test_app], [1])
        self.assertEqual([p.pid for p in view.auxiliary], [2, 3])
        self.assertEqual([p.pid for p in view.inside_bundle_other], [p.pid for p in lookalikes])
        self.assertEqual([p.pid for p in view.foreign], [40, 41])

    # -- required cases -------------------------------------------------------

    def test_1_one_main_portable_process_without_auxiliary_passes_unchanged(self):
        lister = self.lister_with()
        identity = bm.identify(make_services(self.target, process_lister=lister))
        self.assertEqual(
            (identity.state, identity.pid, identity.test_app_process_count,
             identity.auxiliary_process_count),
            ("running_portable", self.MAIN_PID, 1, 0),
        )
        self.assertEqual(identity.report()["process"], {
            "pid": self.MAIN_PID, "portable_flag": True, "state": "running_portable",
            "test_app_process_count": 1,
        })

    def test_2_one_main_plus_exactly_one_exact_xbmchelper_passes_and_is_auditable(self):
        lister = self.lister_with(bm.ProcessInfo(self.AUX_PID, self.aux))
        lister.commands[self.AUX_PID] = "garbage that must never be consulted"
        identity = bm.identify(make_services(self.target, process_lister=lister))
        self.assertEqual((identity.state, identity.pid), ("running_portable", self.MAIN_PID))
        self.assertEqual((identity.test_app_process_count, identity.auxiliary_process_count), (1, 1))
        self.assertEqual(lister.command_calls, [self.MAIN_PID])  # no argv for the auxiliary
        process = identity.report()["process"]
        self.assertEqual(process, {
            "pid": self.MAIN_PID, "portable_flag": True, "state": "running_portable",
            "test_app_process_count": 1, "auxiliary": "XBMCHelper", "auxiliary_process_count": 1,
        })
        self.assertNotIn(self.AUX_PID, process.values())
        self.assertNotIn(self.aux, bm.canonical_json(identity.report()))

    def test_2b_listing_order_does_not_matter(self):
        lister = FakeProcessLister([bm.ProcessInfo(self.AUX_PID, self.aux)])
        lister.run_test_app(self.target, pid=self.MAIN_PID)
        self.assertEqual(bm.identify(make_services(self.target, process_lister=lister)).pid, self.MAIN_PID)

    def test_3_data_volume_alias_of_the_exact_xbmchelper_passes(self):
        lister = self.lister_with(bm.ProcessInfo(self.AUX_PID, self.aux_alias))
        identity = bm.identify(make_services(self.target, process_lister=lister))
        self.assertEqual((identity.state, identity.auxiliary_process_count), ("running_portable", 1))
        main_alias = bm._DATA_VOLUME_ALIAS + os.fspath(self.target.macos_dir / "Kodi")
        lister = FakeProcessLister(
            [bm.ProcessInfo(33, main_alias), bm.ProcessInfo(34, self.aux_alias)], {33: main_alias + " -p"}
        )
        identity = bm.identify(make_services(self.target, process_lister=lister))
        self.assertEqual((identity.pid, identity.auxiliary_process_count), (33, 1))
        self.assertEqual(lister.command_calls, [33])

    def test_4_xbmchelper_alone_fails_closed_for_both_spellings(self):
        for label, path in (("plain", self.aux), ("alias", self.aux_alias)):
            with self.subTest(label=label):
                lister = FakeProcessLister([bm.ProcessInfo(self.AUX_PID, path)])
                error = self.refusal(lister)
                self.assertEqual(error.code, "test_app_process_mismatch")
                self.assertEqual(error.detail, {
                    "auxiliary_process_count": 1, "process_count": 1, "test_app_process_count": 0,
                })
                self.assertEqual(lister.command_calls, [])  # never reads the auxiliary's argv

    def test_5_more_than_one_xbmchelper_fails_closed(self):
        for label, paths in (
            ("two exact", (self.aux, self.aux)),
            ("exact and alias", (self.aux, self.aux_alias)),
            ("two aliases", (self.aux_alias, self.aux_alias)),
        ):
            with self.subTest(label=label):
                lister = self.lister_with(
                    bm.ProcessInfo(self.AUX_PID, paths[0]), bm.ProcessInfo(self.AUX_PID + 1, paths[1])
                )
                error = self.refusal(lister)
                self.assertEqual(error.code, "test_app_process_mismatch")
                self.assertEqual(error.detail, {
                    "auxiliary_process_count": 2, "process_count": 2, "test_app_process_count": 1,
                })

    def test_6_main_plus_exact_xbmchelper_plus_any_other_in_bundle_executable_fails_closed(self):
        for relative in (
            "Contents/MacOS/Helper",
            "Contents/Resources/Kodi/tools/darwin/runtime/OtherTool",
            "Contents/Frameworks/Thing",
        ):
            with self.subTest(relative=relative):
                lister = self.lister_with(
                    bm.ProcessInfo(self.AUX_PID, self.aux), bm.ProcessInfo(6, self.inside(relative))
                )
                error = self.refusal(lister)
                self.assertEqual(error.code, "test_app_process_mismatch")
                self.assertEqual(error.detail, {"process_count": 1})  # the existing mismatch policy

    def test_7_lookalike_paths_inside_the_bundle_are_not_the_sanctioned_auxiliary(self):
        for relative in self.LOOKALIKES:
            for with_main in (True, False):
                with self.subTest(relative=relative, with_main=with_main):
                    lister = self.lister_with(bm.ProcessInfo(self.AUX_PID, self.inside(relative)), main=with_main)
                    error = self.refusal(lister)
                    self.assertEqual(error.code, "test_app_process_mismatch")
                    self.assertEqual(error.detail, {"process_count": 1})

    def test_8_basename_only_xbmchelper_outside_the_exact_path_is_never_sanctioned(self):
        outside = (
            "/usr/local/bin/XBMCHelper",
            "/private/tmp/XBMCHelper",
            os.fspath(self.tmp / "Kodi Build Manager Test.app.bak"
                      / "Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper"),
            "/private/var/folders/xx/AppTranslocation/yy/d/Kodi Build Manager Test.app"
            "/Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper",
            self.aux.casefold(),
        )
        for exe in outside:
            for with_main in (True, False):
                with self.subTest(exe=exe[-40:], with_main=with_main):
                    lister = self.lister_with(bm.ProcessInfo(self.AUX_PID, exe), main=with_main)
                    error = self.refusal(lister)
                    self.assertEqual(error.code, "foreign_kodi_process_present")
                    self.assertEqual(error.detail, {"foreign_kodi_process_count": 1})

    def test_9_multiple_main_processes_remain_rejected_with_or_without_an_auxiliary(self):
        for auxiliaries in ((), (bm.ProcessInfo(self.AUX_PID, self.aux),)):
            with self.subTest(auxiliaries=len(auxiliaries)):
                lister = self.lister_with(*auxiliaries)
                lister.run_test_app(self.target, pid=self.MAIN_PID + 1)
                error = self.refusal(lister)
                self.assertEqual(error.code, "multiple_test_app_processes")
                self.assertEqual(error.detail["process_count"], 2)

    def test_10_foreign_kodi_remains_rejected_next_to_a_valid_pair_or_a_lone_auxiliary(self):
        foreign = bm.ProcessInfo(778, "/Applications/Kodi.app/Contents/MacOS/Kodi")
        for label, lister in (
            ("valid pair", self.lister_with(bm.ProcessInfo(self.AUX_PID, self.aux), foreign)),
            ("lone auxiliary", self.lister_with(bm.ProcessInfo(self.AUX_PID, self.aux), foreign, main=False)),
        ):
            with self.subTest(label=label):
                self.assertEqual(self.refusal(lister).code, "foreign_kodi_process_present")
                self.assertEqual(lister.command_calls, [])  # not even the main command line is read

    def test_11_main_without_valid_standalone_p_is_refused_even_with_an_auxiliary(self):
        for flags in ("", " --portable", " -pp", " --standalone", " -fs --debug", " --data=-p"):
            with self.subTest(flags=flags):
                lister = self.lister_with(bm.ProcessInfo(self.AUX_PID, self.aux), flags=flags)
                self.assertEqual(self.refusal(lister).code, "test_app_not_portable")
                self.assertEqual(lister.command_calls, [self.MAIN_PID])
        exe = os.fspath(self.target.macos_dir / "Kodi")
        for label, command in (
            ("missing argv", None),
            ("different argv0", "/somewhere/else/Kodi -p"),
            ("prefix only", exe + "x -p"),
            ("relative argv0", "Kodi -p"),
        ):
            with self.subTest(label=label):
                lister = self.lister_with(bm.ProcessInfo(self.AUX_PID, self.aux))
                lister.commands[self.MAIN_PID] = command
                self.assertEqual(self.refusal(lister).code, "test_app_process_ambiguous")
                self.assertEqual(lister.command_calls, [self.MAIN_PID])

    def test_12_require_not_running_fails_while_a_detached_xbmchelper_remains(self):
        for path in (self.aux, self.aux_alias):
            for require in ("not_running", "running", None):
                with self.subTest(path=path[:12], require=require):
                    lister = FakeProcessLister([bm.ProcessInfo(self.AUX_PID, path)])
                    error = self.refusal(lister, require=require)
                    self.assertEqual(error.code, "test_app_process_mismatch")

    def test_13_require_not_running_succeeds_only_when_every_bundle_process_is_absent(self):
        helper = bm.ProcessInfo(6, self.inside("Contents/MacOS/Helper"))
        aux = bm.ProcessInfo(self.AUX_PID, self.aux)
        scenarios = (
            ("main", dict(main=True), (), "test_app_running"),
            ("main + auxiliary", dict(main=True), (aux,), "test_app_running"),
            ("auxiliary only", dict(main=False), (aux,), "test_app_process_mismatch"),
            ("other in-bundle only", dict(main=False), (helper,), "test_app_process_mismatch"),
            ("main + auxiliary + other", dict(main=True), (aux, helper), "test_app_process_mismatch"),
        )
        for label, options, extras, code in scenarios:
            with self.subTest(label=label):
                lister = self.lister_with(*extras, main=options["main"])
                self.assertEqual(self.refusal(lister, require="not_running").code, code)
        clean = make_services(self.target, process_lister=FakeProcessLister([
            bm.ProcessInfo(1, "/sbin/launchd"), bm.ProcessInfo(2, "/usr/bin/python3"),
        ]))
        identity = bm.identify(clean, require="not_running")
        self.assertEqual((identity.state, identity.pid, identity.auxiliary_process_count),
                         ("not_running", None, 0))
        paired = make_services(self.target, process_lister=self.lister_with(aux))
        self.assertEqual(bm.identify(paired, require="running").pid, self.MAIN_PID)

    # -- the consumers of identify -----------------------------------------------

    def test_cli_identify_reports_the_auxiliary_by_fixed_name_and_count_only(self):
        services = make_services(self.target, process_lister=self.lister_with(bm.ProcessInfo(self.AUX_PID, self.aux)))
        code, payload, text = run_cli(services, "identify")
        self.assertEqual(code, bm.EXIT_OK)
        self.assertEqual(text, bm.canonical_json(json.loads(text)))
        self.assertEqual(payload["process"]["auxiliary"], "XBMCHelper")
        self.assertEqual(payload["process"]["auxiliary_process_count"], 1)
        self.assertNotIn("runtime/XBMCHelper", text)
        self.assertNotIn(self.aux, text)
        self.assertNotIn("test_app_process_mismatch", text)

    def test_cli_identify_refuses_a_detached_auxiliary_with_a_stable_code(self):
        services = make_services(self.target, process_lister=FakeProcessLister([bm.ProcessInfo(self.AUX_PID, self.aux)]))
        code, payload, text = run_cli(services, "identify")
        self.assertEqual((code, payload["ok"], payload["error"]["code"]), (bm.EXIT_FAILED, False, "test_app_process_mismatch"))
        self.assertEqual(payload["error"]["detail"], {
            "auxiliary_process_count": 1, "process_count": 1, "test_app_process_count": 0,
        })
        self.assertNotIn(self.aux, text)


class TestStageRefusesWhileAuxiliaryRemains(StageTestCase):
    def test_a_detached_xbmchelper_blocks_staging_without_touching_anything(self):
        install_old(self.target)
        self.lister.processes.append(bm.ProcessInfo(15, os.fspath(self.target.auxiliary_executable)))
        before = fingerprint(self.target.root)
        with self.assertRaises(bm.HelperError) as raised:
            self.stage()
        self.assertEqual(raised.exception.code, "test_app_process_mismatch")
        self.assertEqual(fingerprint(self.target.root), before)
        self.assertEqual(self.run_dirs(), [])
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_a_running_main_with_its_auxiliary_is_still_not_cleanly_stopped(self):
        install_old(self.target)
        self.lister.run_test_app(self.target, pid=16)
        self.lister.processes.append(bm.ProcessInfo(17, os.fspath(self.target.auxiliary_executable)))
        before = fingerprint(self.target.root)
        with self.assertRaises(bm.HelperError) as raised:
            self.stage()
        self.assertEqual(raised.exception.code, "test_app_running")
        self.assertEqual(fingerprint(self.target.root), before)
        self.assertEqual(self.run_dirs(), [])


class TestSnapshotWithAuxiliary(SnapshotTestCase):
    def test_snapshot_reports_the_sanctioned_auxiliary_beside_the_main_process(self):
        self.lister.run_test_app(self.target, pid=321)
        self.lister.processes.append(bm.ProcessInfo(322, os.fspath(self.target.auxiliary_executable)))
        process = self.snapshot()["identity"]["process"]
        self.assertEqual((process["state"], process["pid"]), ("running_portable", 321))
        self.assertEqual((process["auxiliary"], process["auxiliary_process_count"]), ("XBMCHelper", 1))

    def test_snapshot_refuses_a_detached_auxiliary(self):
        self.lister.processes.append(bm.ProcessInfo(322, os.fspath(self.target.auxiliary_executable)))
        with self.assertRaises(bm.HelperError) as raised:
            self.snapshot()
        self.assertEqual(raised.exception.code, "test_app_process_mismatch")


# ---------------------------------------------------------------------------
# Install result projection: the adapter's "" spelling of an absent optional string
# ---------------------------------------------------------------------------

def adapter_record(addon_id="plugin.video.fake", **overrides):
    """A resolution record shaped like the adapter's _safe_transaction output.

    The adapter copies the product dataclass attributes, so an absent optional
    string is "" and never null: an exact-artifact record has no repository and
    a skipped record has neither a repository nor a resolved version.
    """
    record = {
        "addon_id": addon_id, "resolution": "exact", "state": "installed",
        "resolved_version": "1.2.3", "desired_enabled": True, "repository_id": "",
    }
    record.update(overrides)
    return record


def skipped_adapter_record(addon_id="plugin.video.fake", **overrides):
    return adapter_record(addon_id, **dict(
        {"resolution": "skipped", "state": "skipped", "resolved_version": ""}, **overrides))


def fallback_adapter_record(addon_id="plugin.video.fake", **overrides):
    """A repository-fallback record with every optional string present.

    Valid with or without the "" rule, so a test that corrupts one field of it
    fails because of that field alone.
    """
    return adapter_record(addon_id, **dict(
        {"resolution": "repository_current", "repository_id": "repository.fake", "resolved_version": "2.0.0"},
        **overrides))


class TestInstallResolutionRecordProjection(unittest.TestCase):
    def project(self, records, **transaction):
        payload = adapter_payload(
            "install", transaction=dict(INSTALL_TRANSACTION, resolution_records=records, **transaction))
        return bm.project_adapter_result("install", payload)

    def assert_transaction_withheld(self, records, **transaction):
        projected, withheld = self.project(records, **transaction)
        self.assertNotIn("transaction", projected)
        self.assertEqual(withheld["invalid_known_keys"], ["transaction"])
        return projected, withheld

    def test_empty_optional_strings_project_successfully(self):
        projected, _ = self.project([adapter_record(), skipped_adapter_record("plugin.video.fake2")])
        self.assertIn("transaction", projected)
        records = projected["transaction"]["resolution_records"]
        self.assertEqual([record["addon_id"] for record in records], ["plugin.video.fake", "plugin.video.fake2"])
        self.assertEqual(
            [(record["resolution"], record["state"], record["desired_enabled"]) for record in records],
            [("exact", "installed", True), ("skipped", "skipped", True)],
        )

    def test_empty_optional_strings_project_as_null_not_as_empty_strings(self):
        projected, _ = self.project([adapter_record(), skipped_adapter_record("plugin.video.fake2")])
        self.assertIn("transaction", projected)
        exact, skipped = projected["transaction"]["resolution_records"]
        self.assertIsNone(exact["repository_id"])
        self.assertIsNone(skipped["repository_id"])
        self.assertIsNone(skipped["resolved_version"])
        for record in (exact, skipped):
            self.assertNotIn("", record.values())

    def test_adapter_shaped_transaction_is_not_an_invalid_known_key(self):
        _, withheld = self.project([adapter_record(), skipped_adapter_record("plugin.video.fake2")])
        self.assertNotIn("transaction", withheld["invalid_known_keys"])
        self.assertEqual(withheld, {"invalid_known_keys": [], "unknown_key_count": 0, "unknown_key_names": []})

    def test_null_spelling_is_still_accepted(self):
        projected, withheld = self.project([
            adapter_record(repository_id=None),
            skipped_adapter_record("plugin.video.fake2", repository_id=None, resolved_version=None),
        ])
        self.assertEqual(withheld["invalid_known_keys"], [])
        exact, skipped = projected["transaction"]["resolution_records"]
        self.assertEqual((exact["repository_id"], exact["resolved_version"]), (None, "1.2.3"))
        self.assertEqual((skipped["repository_id"], skipped["resolved_version"]), (None, None))

    def test_projection_is_idempotent_on_the_canonical_null_form(self):
        projected, _ = self.project([adapter_record(), skipped_adapter_record("plugin.video.fake2")])
        self.assertIn("transaction", projected)
        again, withheld = bm.project_adapter_result("install", projected)
        self.assertEqual(again, projected)
        self.assertEqual(withheld["invalid_known_keys"], [])

    def test_nonempty_repository_id_is_unchanged(self):
        for repository_id in ("repository.fake", "repo-1_x.y", "a", "R" * 128):
            for version in ("2.0.0", ""):  # a selected-only fallback record has no resolved version yet
                with self.subTest(repository_id=repository_id, resolved_version=version):
                    projected, withheld = self.project(
                        [fallback_adapter_record(repository_id=repository_id, resolved_version=version)])
                    self.assertEqual(withheld["invalid_known_keys"], [])
                    self.assertIn("transaction", projected)
                    self.assertEqual(projected["transaction"]["resolution_records"][0]["repository_id"], repository_id)

    def test_nonempty_resolved_version_is_unchanged(self):
        versions = ("1.0.0", "0.0.6+matrix.1", "999.6.1+matrix.1", "7.4.4+unofficial.2", "2024.1~rc1", "1" * 64)
        for version in versions:
            for make in (adapter_record, fallback_adapter_record):  # exact (no repository) and fallback records
                with self.subTest(resolved_version=version, record=make.__name__):
                    projected, withheld = self.project([make(resolved_version=version)])
                    self.assertEqual(withheld["invalid_known_keys"], [])
                    self.assertIn("transaction", projected)
                    self.assertEqual(projected["transaction"]["resolution_records"][0]["resolved_version"], version)

    def test_every_adapter_combination_of_present_and_absent_fields_projects(self):
        cases = (  # (repository_id, resolved_version) as the adapter writes them -> as projected
            (("", "1.2.3"), (None, "1.2.3")),  # exact artifact
            (("", ""), (None, None)),  # skipped
            (("repository.fake", ""), ("repository.fake", None)),  # repository fallback, selected only
            (("repository.fake", "2.0.0"), ("repository.fake", "2.0.0")),  # repository fallback, resolved
        )
        for (repository_id, version), expected in cases:
            with self.subTest(repository_id=repository_id, resolved_version=version):
                projected, withheld = self.project(
                    [adapter_record(repository_id=repository_id, resolved_version=version)])
                self.assertEqual(withheld["invalid_known_keys"], [])
                self.assertIn("transaction", projected)
                record = projected["transaction"]["resolution_records"][0]
                self.assertEqual((record["repository_id"], record["resolved_version"]), expected)

    def test_whitespace_is_not_treated_as_absent(self):
        for field in ("repository_id", "resolved_version"):
            for blank in (" ", "  ", "\t", "\n", "\u00a0", " \t "):
                with self.subTest(field=field, blank=blank):
                    self.assert_transaction_withheld([fallback_adapter_record(**{field: blank})])

    def test_invalid_repository_ids_stay_invalid(self):
        invalid = ("bad id", "-leading", ".leading", "a/b", "x" * 129, "repo\n", "INJECTED-SECRET id", "r\u00e9po",
                   0, False, 5, 1.5, [], {}, ["repository.fake"])
        for value in invalid:
            with self.subTest(repository_id=value):
                projected, withheld = self.assert_transaction_withheld(
                    [fallback_adapter_record(repository_id=value)])
                self.assertNotIn("INJECTED", json.dumps([projected, withheld]))

    def test_invalid_versions_stay_invalid(self):
        invalid = ("bad version", "+leading", "~1", "1.0 0", "v" * 65, "1.0\n", "INJECTED-SECRET ver", "1.0/x",
                   "1.0\u00e9", 0, False, 5, 1.5, [], {}, ["1.0.0"])
        for value in invalid:
            with self.subTest(resolved_version=value):
                projected, withheld = self.assert_transaction_withheld(
                    [fallback_adapter_record(resolved_version=value)])
                self.assertNotIn("INJECTED", json.dumps([projected, withheld]))

    def test_one_invalid_record_still_withholds_the_whole_transaction(self):
        self.assert_transaction_withheld([adapter_record(), skipped_adapter_record("plugin.video.fake2"),
                                          fallback_adapter_record("plugin.video.fake3", repository_id="bad id")])

    def test_empty_strings_in_other_fields_are_still_rejected(self):
        projected, withheld = self.project([fallback_adapter_record()])  # the baseline the cases below corrupt
        self.assertIn("transaction", projected)
        for field in ("addon_id", "resolution", "state", "desired_enabled"):
            with self.subTest(record_field=field):
                self.assert_transaction_withheld([fallback_adapter_record(**{field: ""})])
        for field in ("phase", "lifecycle_stage", "lifecycle_restart_count", "original_update_policy",
                      "activation_hold_released", "private_overlay_required", "updater_guard_required"):
            with self.subTest(transaction_field=field):
                self.assert_transaction_withheld([fallback_adapter_record()], **{field: ""})
        with self.subTest(transaction_field="activation_hold_ids"):
            self.assert_transaction_withheld([fallback_adapter_record()], activation_hold_ids=[""])
        elsewhere = {
            "installed": {"plugin.video.fake": {"version": "", "enabled": True, "broken": False}},
            "updater_policy": "", "frozen_manifest_fingerprint": "", "overlay_imported": "",
            "retained_inputs": {"artifact_entry_count": ""}, "frozen_install_source": {"sha256_before": ""},
        }
        for key, value in elsewhere.items():
            with self.subTest(install_field=key):
                projected, withheld = bm.project_adapter_result("install", adapter_payload("install", **{key: value}))
                self.assertNotIn(key, projected)
                self.assertEqual(withheld["invalid_known_keys"], [key])
        with self.subTest(status_field="adapter_version"):
            projected, withheld = bm.project_adapter_result(
                "status", adapter_payload("status", status=dict(STATUS_VALUES, adapter_version="")))
            self.assertNotIn("status", projected)
            self.assertEqual(withheld["invalid_known_keys"], ["status"])

    def test_generic_optional_validator_still_rejects_the_empty_string(self):
        optional_version = bm._opt(bm._v_match(bm._VERSION_RE))
        with self.assertRaises(ValueError):
            optional_version("")
        self.assertIsNone(optional_version(None))
        self.assertEqual(optional_version("1.0.0"), "1.0.0")

    def test_youtube_style_skipped_record_projects_safely(self):
        projected, withheld = self.project([skipped_adapter_record("plugin.video.youtube")])
        self.assertEqual(withheld["invalid_known_keys"], [])
        self.assertIn("transaction", projected)
        self.assertEqual(projected["transaction"]["resolution_records"], [{
            "addon_id": "plugin.video.youtube", "resolution": "skipped", "state": "skipped",
            "repository_id": None, "resolved_version": None, "desired_enabled": True,
        }])

    def test_exact_artifact_record_with_empty_repository_metadata_projects_correctly(self):
        projected, withheld = self.project([adapter_record("plugin.video.fake", resolved_version="6.09.04")])
        self.assertEqual(withheld["invalid_known_keys"], [])
        self.assertIn("transaction", projected)
        self.assertEqual(projected["transaction"]["resolution_records"], [{
            "addon_id": "plugin.video.fake", "resolution": "exact", "state": "installed",
            "repository_id": None, "resolved_version": "6.09.04", "desired_enabled": True,
        }])

    def test_unknown_key_withholding_is_unchanged(self):
        for absent in ("", None):
            with self.subTest(absent=absent):
                record = adapter_record(repository_id=absent, injected_record_key="INJECTED-RECORD")
                payload = adapter_payload(
                    "install", password="INJECTED-SECRET-123", **{"overlay values": "INJECTED-OVERLAY"},
                    transaction=dict(INSTALL_TRANSACTION, resolution_records=[record], private_note="INJECTED-NESTED"))
                projected, withheld = bm.project_adapter_result("install", payload)
                self.assertIn("transaction", projected)
                self.assertEqual(withheld["invalid_known_keys"], [])
                self.assertEqual(withheld["unknown_key_count"], 2)
                self.assertEqual(withheld["unknown_key_names"], ["password"])  # unsafe names are only counted
                self.assertNotIn("private_note", projected["transaction"])
                self.assertNotIn("injected_record_key", projected["transaction"]["resolution_records"][0])
                text = json.dumps([projected, withheld])
                for injected in ("INJECTED-SECRET-123", "INJECTED-OVERLAY", "INJECTED-NESTED", "INJECTED-RECORD"):
                    self.assertNotIn(injected, text)


class TestSnapshotProjectsAdapterShapedInstallResult(SnapshotTestCase):
    def test_install_result_with_empty_optional_strings_keeps_its_transaction(self):
        transaction = dict(
            INSTALL_TRANSACTION, phase="awaiting_restart", lifecycle_stage="quiescence_awaiting_restart",
            lifecycle_restart_count=1, activation_hold_ids=["plugin.video.redlight"], activation_hold_released=False,
            status_code="QUIESCENCE_RESTART_REQUIRED",
            resolution_records=[adapter_record("plugin.video.fake"), skipped_adapter_record("plugin.video.youtube")],
        )
        self.target.result_path.write_text(json.dumps(adapter_payload(
            "install", outcome="awaiting_restart", code="QUIESCENCE_RESTART_REQUIRED", transaction=transaction)))
        report = self.snapshot()["adapter_result_file"]
        self.assertEqual(report["withheld"]["invalid_known_keys"], [])
        self.assertIn("transaction", report["projection"])
        projected = report["projection"]["transaction"]
        self.assertEqual(projected["phase"], "awaiting_restart")
        self.assertEqual(projected["activation_hold_ids"], ["plugin.video.redlight"])
        self.assertEqual(projected["resolution_records"], [
            {"addon_id": "plugin.video.fake", "resolution": "exact", "state": "installed",
             "repository_id": None, "resolved_version": "1.2.3", "desired_enabled": True},
            {"addon_id": "plugin.video.youtube", "resolution": "skipped", "state": "skipped",
             "repository_id": None, "resolved_version": None, "desired_enabled": True},
        ])


# --- END OF TESTS MARKER (new test classes are inserted above this line) ---

if __name__ == "__main__":
    unittest.main()
