"""
BM-009 unit tests for tools/kodi_test.py.

Tests cover path safety, process state, command dispatch, install paths, and
readiness — all without launching real Kodi.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is importable (allows `import tools.kodi_test`)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tools.kodi_test as harness  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: patch multiple module-level constants at once
# ---------------------------------------------------------------------------

def _patch_constants(**kwargs):
    return patch.multiple("tools.kodi_test", **kwargs)


# ---------------------------------------------------------------------------
# PATH SAFETY — _inside() and _overlaps()
# ---------------------------------------------------------------------------

class TestInside(unittest.TestCase):
    def test_child_inside_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            child = parent / "a" / "b"
            self.assertTrue(harness._inside(child, parent))

    def test_exact_same_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.assertTrue(harness._inside(p, p))

    def test_sibling_not_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "alpha"
            b = root / "beta"
            self.assertFalse(harness._inside(a, b))

    def test_parent_not_inside_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            child = parent / "sub"
            self.assertFalse(harness._inside(parent, child))

    def test_prefix_not_matched_as_inside(self):
        # "/foo/bar" should NOT be inside "/foo/b" even though it starts the same
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "foo" / "bar"
            b = root / "foo" / "b"
            self.assertFalse(harness._inside(a, b))

    def test_deep_nesting(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            child = parent / "a" / "b" / "c" / "d"
            self.assertTrue(harness._inside(child, parent))


class TestOverlaps(unittest.TestCase):
    def test_non_overlapping_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(harness._overlaps(root / "a", root / "b"))

    def test_parent_child_overlaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            child = parent / "sub"
            self.assertTrue(harness._overlaps(parent, child))

    def test_child_parent_overlaps_symmetric(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            child = parent / "sub"
            self.assertTrue(harness._overlaps(child, parent))

    def test_equal_paths_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.assertTrue(harness._overlaps(p, p))


# ---------------------------------------------------------------------------
# PATH SAFETY — verify_isolation()
# ---------------------------------------------------------------------------

class TestVerifyIsolation(unittest.TestCase):
    def _make_valid_layout(self, base: Path):
        project = base / "project"
        root = project / ".kodi-test"
        home = root / "home"
        appdata = home / "Library" / "Application Support" / "Kodi"
        normal = base / "other" / "Kodi"  # disjoint
        return project, root, home, appdata, normal

    def test_valid_layout_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, root, home, appdata, normal = self._make_valid_layout(Path(tmp))
            with _patch_constants(
                PROJECT=project, ROOT=root, HOME=home,
                KODI_APPDATA_DIR=appdata, NORMAL_APPDATA_DIR=normal,
            ):
                harness.verify_isolation()  # must not raise

    def test_root_is_filesystem_root_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _, home, appdata, normal = self._make_valid_layout(Path(tmp))
            with _patch_constants(
                PROJECT=project, ROOT=Path("/"), HOME=home,
                KODI_APPDATA_DIR=appdata, NORMAL_APPDATA_DIR=normal,
            ):
                with self.assertRaisesRegex(RuntimeError, "filesystem root"):
                    harness.verify_isolation()

    def test_root_outside_project_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.TemporaryDirectory() as tmp2:
                project, _, home, appdata, normal = self._make_valid_layout(Path(tmp))
                root_outside = Path(tmp2) / ".kodi-test"
                with _patch_constants(
                    PROJECT=project, ROOT=root_outside, HOME=home,
                    KODI_APPDATA_DIR=appdata, NORMAL_APPDATA_DIR=normal,
                ):
                    with self.assertRaisesRegex(RuntimeError, "not inside PROJECT"):
                        harness.verify_isolation()

    def test_home_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, root, _, appdata, normal = self._make_valid_layout(Path(tmp))
            home_outside = project / "somewhere_else"
            with _patch_constants(
                PROJECT=project, ROOT=root, HOME=home_outside,
                KODI_APPDATA_DIR=appdata, NORMAL_APPDATA_DIR=normal,
            ):
                with self.assertRaisesRegex(RuntimeError, "not inside ROOT"):
                    harness.verify_isolation()

    def test_appdata_outside_home_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, root, home, _, normal = self._make_valid_layout(Path(tmp))
            appdata_outside = project / ".kodi-test" / "detached"
            with _patch_constants(
                PROJECT=project, ROOT=root, HOME=home,
                KODI_APPDATA_DIR=appdata_outside, NORMAL_APPDATA_DIR=normal,
            ):
                with self.assertRaisesRegex(RuntimeError, "not inside HOME"):
                    harness.verify_isolation()

    def test_real_profile_overlap_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, root, home, appdata, _ = self._make_valid_layout(Path(tmp))
            # normal IS appdata — direct overlap
            with _patch_constants(
                PROJECT=project, ROOT=root, HOME=home,
                KODI_APPDATA_DIR=appdata, NORMAL_APPDATA_DIR=appdata,
            ):
                with self.assertRaisesRegex(RuntimeError, "overlaps real profile"):
                    harness.verify_isolation()

    def test_real_profile_parent_of_appdata_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, root, home, appdata, _ = self._make_valid_layout(Path(tmp))
            # normal is a parent of appdata — still overlaps
            normal_parent = appdata.parent
            with _patch_constants(
                PROJECT=project, ROOT=root, HOME=home,
                KODI_APPDATA_DIR=appdata, NORMAL_APPDATA_DIR=normal_parent,
            ):
                with self.assertRaisesRegex(RuntimeError, "overlaps real profile"):
                    harness.verify_isolation()


# ---------------------------------------------------------------------------
# RESET path safety
# ---------------------------------------------------------------------------

class TestResetPathSafety(unittest.TestCase):
    def test_reset_refuses_root_outside_project(self):
        """reset() must refuse to rmtree when ROOT is not inside PROJECT."""
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.TemporaryDirectory() as tmp2:
                project = Path(tmp)
                root = Path(tmp2) / ".kodi-test"
                root.mkdir(parents=True)
                home = root / "home"
                appdata = home / "Library" / "Application Support" / "Kodi"
                normal = project / "other" / "Kodi"
                with _patch_constants(
                    PROJECT=project, ROOT=root, HOME=home,
                    KODI_APPDATA_DIR=appdata,
                    KODI_USERDATA_DIR=appdata / "userdata",
                    KODI_ADDONS_DIR=appdata / "addons",
                    NORMAL_APPDATA_DIR=normal,
                    PID_FILE=root / "kodi.pid",
                ):
                    with self.assertRaises(RuntimeError):
                        harness.reset()

    def test_reset_creates_expected_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            root = project / ".kodi-test"
            home = root / "home"
            appdata = home / "Library" / "Application Support" / "Kodi"
            userdata = appdata / "userdata"
            addons = appdata / "addons"
            normal = base / "other" / "Kodi"
            project.mkdir()
            with _patch_constants(
                PROJECT=project, ROOT=root, HOME=home,
                KODI_APPDATA_DIR=appdata,
                KODI_USERDATA_DIR=userdata,
                KODI_ADDONS_DIR=addons,
                NORMAL_APPDATA_DIR=normal,
                PID_FILE=root / "kodi.pid",
                _process=None,
            ):
                with patch.object(harness, "status", return_value={"running": False}):
                    harness.reset()
            self.assertTrue(addons.is_dir())
            self.assertTrue(userdata.is_dir())


# ---------------------------------------------------------------------------
# INSTALL paths
# ---------------------------------------------------------------------------

class TestInstallPaths(unittest.TestCase):
    def test_target_resolves_inside_addons_dir(self):
        target = harness.KODI_ADDONS_DIR / harness.ADDON_ID
        self.assertTrue(harness._inside(target, harness.KODI_ADDONS_DIR))

    def test_addons_dir_inside_root(self):
        self.assertTrue(harness._inside(harness.KODI_ADDONS_DIR, harness.ROOT))

    def test_default_source_is_project_root_with_addon_xml(self):
        addon_xml = harness.PROJECT / "addon.xml"
        self.assertTrue(addon_xml.is_file(), f"addon.xml not found at {addon_xml}")

    def test_default_source_has_correct_addon_id(self):
        content = (harness.PROJECT / "addon.xml").read_text(encoding="utf-8")
        self.assertIn(f'id="{harness.ADDON_ID}"', content)

    def test_verify_source_rejects_nonexistent_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist"
            with self.assertRaises(ValueError):
                harness._verify_source(missing)

    def test_verify_source_rejects_directory_without_addon_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            with self.assertRaises(ValueError):
                harness._verify_source(source)

    def test_verify_source_rejects_wrong_addon_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / "addon.xml").write_text('<addon id="wrong.thing">')
            with self.assertRaises(ValueError):
                harness._verify_source(source)

    def test_verify_source_accepts_project_root(self):
        harness._verify_source(harness.PROJECT)  # must not raise

    def test_copy_addon_files_includes_addon_xml_default_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"
            target = Path(tmp) / "dst"
            source.mkdir()
            (source / "addon.xml").write_text('<addon id="script.build.manager">')
            (source / "default.py").write_text("# main")
            (source / "resources").mkdir()
            (source / "resources" / "settings.xml").write_text("<settings/>")
            harness._copy_addon_files(source, target)
            self.assertTrue((target / "addon.xml").is_file())
            self.assertTrue((target / "default.py").is_file())
            self.assertTrue((target / "resources").is_dir())
            self.assertTrue((target / "resources" / "settings.xml").is_file())

    def test_copy_addon_files_excludes_tests_and_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"
            target = Path(tmp) / "dst"
            source.mkdir()
            (source / "addon.xml").write_text('<addon id="script.build.manager">')
            (source / "tests").mkdir()
            (source / "tests" / "test_foo.py").write_text("# test")
            (source / "tools").mkdir()
            (source / "tools" / "kodi_test.py").write_text("# harness")
            (source / "docs").mkdir()
            (source / "docs" / "TESTING.md").write_text("# docs")
            harness._copy_addon_files(source, target)
            self.assertFalse((target / "tests").exists())
            self.assertFalse((target / "tools").exists())
            self.assertFalse((target / "docs").exists())

    def test_copy_addon_files_overwrites_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"
            target = Path(tmp) / "dst"
            source.mkdir()
            (source / "addon.xml").write_text('<addon id="script.build.manager" version="2">')
            target.mkdir()
            (target / "addon.xml").write_text('<addon id="script.build.manager" version="1">')
            harness._copy_addon_files(source, target)
            content = (target / "addon.xml").read_text()
            self.assertIn('version="2"', content)


# ---------------------------------------------------------------------------
# PROCESS STATE — PID file and status
# ---------------------------------------------------------------------------

class TestPidFile(unittest.TestCase):
    def test_read_pid_returns_none_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(harness, "PID_FILE", Path(tmp) / "kodi.pid"):
                self.assertIsNone(harness._read_pid())

    def test_read_pid_returns_none_for_corrupt_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text("not-an-integer")
            with patch.object(harness, "PID_FILE", pid_file):
                self.assertIsNone(harness._read_pid())

    def test_read_pid_returns_int_for_valid_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text("42\n")
            with patch.object(harness, "PID_FILE", pid_file):
                self.assertEqual(harness._read_pid(), 42)

    def test_clear_pid_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text("1")
            with patch.object(harness, "PID_FILE", pid_file):
                harness._clear_pid()
            self.assertFalse(pid_file.exists())

    def test_clear_pid_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "kodi.pid"
            with patch.object(harness, "PID_FILE", missing):
                harness._clear_pid()  # must not raise


class TestStatus(unittest.TestCase):
    def test_status_stopped_when_no_pid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            with patch.object(harness, "PID_FILE", pid_file):
                s = harness.status()
                self.assertFalse(s["running"])
                self.assertIsNone(s["pid"])

    def test_status_stopped_when_pid_not_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text("999999999")  # very unlikely to exist
            with patch.object(harness, "PID_FILE", pid_file):
                s = harness.status()
                self.assertFalse(s["running"])
                self.assertIsNone(s["pid"])

    def test_status_running_when_pid_alive(self):
        own_pid = os.getpid()
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text(str(own_pid))
            with patch.object(harness, "PID_FILE", pid_file):
                s = harness.status()
                self.assertTrue(s["running"])
                self.assertEqual(s["pid"], own_pid)

    def test_status_clears_stale_pid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text("999999999")
            with patch.object(harness, "PID_FILE", pid_file):
                harness.status()
            self.assertFalse(pid_file.exists())


# ---------------------------------------------------------------------------
# PROCESS STATE — stop()
# ---------------------------------------------------------------------------

class TestStop(unittest.TestCase):
    def test_stop_with_no_pid_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            with patch.object(harness, "PID_FILE", pid_file):
                harness.stop()  # must not raise

    def test_stop_with_dead_pid_clears_file_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text("999999999")
            with patch.object(harness, "PID_FILE", pid_file):
                harness.stop()  # must not raise
            self.assertFalse(pid_file.exists())

    def test_stop_refuses_to_kill_non_kodi_process(self):
        own_pid = os.getpid()
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text(str(own_pid))
            with (
                patch.object(harness, "PID_FILE", pid_file),
                patch.object(harness, "_pid_is_kodi", return_value=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "not appear to be Kodi"):
                    harness.stop()
            # PID file must not be touched when we refuse
            self.assertTrue(pid_file.exists())

    def test_stop_clears_pid_file_after_stopping_kodi(self):
        own_pid = os.getpid()
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "kodi.pid"
            pid_file.write_text(str(own_pid))
            # Mock _pid_is_kodi=True, os.kill to no-op, _pid_is_alive to
            # return False after SIGTERM so we don't actually kill ourselves
            call_count = {"n": 0}
            def fake_kill(pid, sig):
                call_count["n"] += 1
            original_is_alive = harness._pid_is_alive
            def fake_is_alive(pid):
                # First call (from stop() alive check): True. After SIGTERM: False.
                return call_count["n"] == 0
            with (
                patch.object(harness, "PID_FILE", pid_file),
                patch.object(harness, "_pid_is_kodi", return_value=True),
                patch.object(harness, "_process", None),
                patch("os.kill", side_effect=fake_kill),
                patch.object(harness, "_pid_is_alive", side_effect=fake_is_alive),
            ):
                harness.stop(timeout=1.0)
            self.assertFalse(pid_file.exists())


# ---------------------------------------------------------------------------
# COMMAND DISPATCH
# ---------------------------------------------------------------------------

class TestCommandDispatch(unittest.TestCase):
    """Verify CLI commands route to the correct functions."""

    def _run_cmd(self, *argv, side_effects=None):
        """Patch all command functions and run main(). Returns (returncode, called)."""
        called = {}

        def make_noop(name, ret=None):
            def fn(*a, **kw):
                called[name] = True
                return ret
            return fn

        patches = {
            "reset": make_noop("reset"),
            "install": make_noop("install"),
            "configure_webserver": make_noop("configure_webserver"),
            "launch": make_noop("launch", ret=1234),
            "wait_for_ready": make_noop("wait_for_ready"),
            "stop": make_noop("stop"),
            "restart": make_noop("restart", ret=1234),
            "inspect": make_noop("inspect", ret={"platform": "macos", "kodi_version": "21.1",
                                                   "active_skin": "skin.estuary",
                                                   "addon_count": 0, "addons": []}),
            "status": make_noop("status", ret={"running": False, "pid": None,
                                                "root": "/r", "home": "/h",
                                                "kodi_appdata": "/a",
                                                "addon_installed": False,
                                                "webserver_configured": False,
                                                "log": "/l"}),
            "validate": make_noop("validate"),
            "validate_af3_package": make_noop("validate_af3_package"),
            "validate_build_manager": make_noop("validate_build_manager"),
        }
        if side_effects:
            patches.update(side_effects)

        with patch.multiple("tools.kodi_test", **patches):
            rc = harness.main(list(argv))
        return rc, called

    def test_reset_routes(self):
        rc, called = self._run_cmd("reset")
        self.assertEqual(rc, 0)
        self.assertIn("reset", called)

    def test_install_routes(self):
        rc, called = self._run_cmd("install")
        self.assertEqual(rc, 0)
        self.assertIn("install", called)

    def test_validate_af3_package_routes(self):
        rc, called = self._run_cmd("validate-af3-package")
        self.assertEqual(rc, 0)
        self.assertIn("validate_af3_package", called)

    def test_validate_build_manager_routes(self):
        rc, called = self._run_cmd("validate-build-manager")
        self.assertEqual(rc, 0)
        self.assertIn("validate_build_manager", called)

    def test_configure_routes(self):
        rc, called = self._run_cmd("configure")
        self.assertEqual(rc, 0)
        self.assertIn("configure_webserver", called)

    def test_enable_webserver_routes_to_configure(self):
        rc, called = self._run_cmd("enable-webserver")
        self.assertEqual(rc, 0)
        self.assertIn("configure_webserver", called)

    def test_launch_routes(self):
        rc, called = self._run_cmd("launch")
        self.assertEqual(rc, 0)
        self.assertIn("launch", called)

    def test_wait_routes(self):
        rc, called = self._run_cmd("wait")
        self.assertEqual(rc, 0)
        self.assertIn("wait_for_ready", called)

    def test_stop_routes(self):
        rc, called = self._run_cmd("stop")
        self.assertEqual(rc, 0)
        self.assertIn("stop", called)

    def test_restart_routes(self):
        rc, called = self._run_cmd("restart")
        self.assertEqual(rc, 0)
        self.assertIn("restart", called)

    def test_inspect_routes(self):
        rc, called = self._run_cmd("inspect")
        self.assertEqual(rc, 0)
        self.assertIn("inspect", called)

    def test_status_routes(self):
        rc, called = self._run_cmd("status")
        self.assertEqual(rc, 0)
        self.assertIn("status", called)

    def test_validate_routes(self):
        rc, called = self._run_cmd("validate")
        self.assertEqual(rc, 0)
        self.assertIn("validate", called)

    def test_runtime_error_returns_exit_code_1(self):
        rc, _ = self._run_cmd(
            "reset",
            side_effects={"reset": MagicMock(side_effect=RuntimeError("test error"))},
        )
        self.assertEqual(rc, 1)

    def test_unknown_command_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            harness.main(["totally-unknown-command"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_wait_with_timeout_flag(self):
        """--timeout is forwarded to wait_for_ready."""
        received_timeout = {}

        def fake_wait_for_ready(timeout=60.0, interval=0.5):
            received_timeout["v"] = timeout

        with patch.object(harness, "wait_for_ready", side_effect=fake_wait_for_ready):
            harness.main(["wait", "--timeout", "120"])
        self.assertAlmostEqual(received_timeout["v"], 120.0)


# ---------------------------------------------------------------------------
# READINESS — wait_for_ready()
# ---------------------------------------------------------------------------

class TestReadiness(unittest.TestCase):
    def test_succeeds_immediately_on_pong(self):
        with patch.object(harness, "jsonrpc", return_value="pong"):
            harness.wait_for_ready(timeout=5.0, interval=0.001)  # must not raise

    def test_tolerates_transient_failures(self):
        call_count = {"n": 0}

        def flaky_jsonrpc(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 4:
                raise ConnectionRefusedError("not ready")
            return "pong"

        with patch.object(harness, "jsonrpc", side_effect=flaky_jsonrpc):
            harness.wait_for_ready(timeout=10.0, interval=0.001)
        self.assertGreaterEqual(call_count["n"], 4)

    def test_raises_timeout_error_when_never_ready(self):
        with patch.object(harness, "jsonrpc", side_effect=ConnectionRefusedError("down")):
            with self.assertRaises(TimeoutError):
                harness.wait_for_ready(timeout=0.05, interval=0.001)

    def test_timeout_error_message_includes_last_error(self):
        with patch.object(harness, "jsonrpc", side_effect=ConnectionRefusedError("port closed")):
            with self.assertRaises(TimeoutError) as ctx:
                harness.wait_for_ready(timeout=0.05, interval=0.001)
        self.assertIn("port closed", str(ctx.exception))

    def test_unexpected_response_does_not_succeed(self):
        with patch.object(harness, "jsonrpc", return_value="nope"):
            with self.assertRaises(TimeoutError):
                harness.wait_for_ready(timeout=0.05, interval=0.001)


# ---------------------------------------------------------------------------
# WEBSERVER CONFIGURATION
# ---------------------------------------------------------------------------

class TestConfigureWebserver(unittest.TestCase):
    def test_writes_guisettings_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            userdata = Path(tmp) / "userdata"
            userdata.mkdir()
            with (
                patch.object(harness, "KODI_USERDATA_DIR", userdata),
                patch.object(harness, "verify_isolation"),
            ):
                harness.configure_webserver(port=9001, username="u", password="p")
            settings = userdata / "guisettings.xml"
            self.assertTrue(settings.is_file())
            content = settings.read_text()
            self.assertIn("9001", content)
            self.assertIn("services.webserver", content)

    def test_refuses_if_settings_file_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            userdata = Path(tmp) / "userdata"
            userdata.mkdir()
            existing = userdata / "guisettings.xml"
            existing.write_text("<settings/>")
            with (
                patch.object(harness, "KODI_USERDATA_DIR", userdata),
                patch.object(harness, "verify_isolation"),
            ):
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    harness.configure_webserver()

    def test_refuses_if_userdata_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "userdata"
            with (
                patch.object(harness, "KODI_USERDATA_DIR", missing),
                patch.object(harness, "verify_isolation"),
            ):
                with self.assertRaises(RuntimeError):
                    harness.configure_webserver()


# ---------------------------------------------------------------------------
# CONSTANTS — sanity checks
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_project_resolves_to_repo_root(self):
        self.assertTrue((harness.PROJECT / "addon.xml").is_file())

    def test_root_is_inside_project(self):
        self.assertTrue(harness._inside(harness.ROOT, harness.PROJECT))

    def test_home_is_inside_root(self):
        self.assertTrue(harness._inside(harness.HOME, harness.ROOT))

    def test_kodi_appdata_is_inside_home(self):
        self.assertTrue(harness._inside(harness.KODI_APPDATA_DIR, harness.HOME))

    def test_addons_dir_is_inside_appdata(self):
        self.assertTrue(harness._inside(harness.KODI_ADDONS_DIR, harness.KODI_APPDATA_DIR))

    def test_root_does_not_overlap_normal_appdata(self):
        self.assertFalse(harness._overlaps(harness.KODI_APPDATA_DIR, harness.NORMAL_APPDATA_DIR))

    def test_addon_id_is_correct(self):
        self.assertEqual(harness.ADDON_ID, "script.build.manager")

    def test_webserver_port_differs_from_common_defaults(self):
        # Not 8080 or 8899 (Backup Pro) to avoid port collisions
        self.assertNotEqual(harness.WEBSERVER_PORT, 8080)
        self.assertNotEqual(harness.WEBSERVER_PORT, 8899)

    def test_addon_include_contains_expected_files(self):
        self.assertIn("addon.xml", harness.ADDON_INCLUDE)
        self.assertIn("default.py", harness.ADDON_INCLUDE)
        self.assertIn("resources", harness.ADDON_INCLUDE)

    def test_bm011_addon_server_port_distinct(self):
        self.assertNotEqual(harness._ADDON_SERVER_PORT, harness.WEBSERVER_PORT)
        self.assertNotEqual(harness._ADDON_SERVER_PORT, harness._REPO_SERVER_PORT)

    def test_bm011_test_addon_id(self):
        self.assertEqual(harness._BM011_TEST_ADDON_ID, "script.module.build-manager-test")

    def test_harness_trigger_addon_id(self):
        self.assertIn("harness", harness._HARNESS_TRIGGER_ADDON_ID)


# ---------------------------------------------------------------------------
# BM-011 content builders
# ---------------------------------------------------------------------------

class TestBm011ContentBuilders(unittest.TestCase):
    """_make_bm011_test_addon_zip, _make_bm011_addons_xml, _make_bm011_repo_zip."""

    def test_test_addon_zip_is_valid_zip(self):
        import zipfile, io
        data = harness._make_bm011_test_addon_zip()
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))

    def test_test_addon_zip_contains_addon_xml(self):
        import zipfile, io
        data = harness._make_bm011_test_addon_zip()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        self.assertTrue(any("addon.xml" in n for n in names))

    def test_test_addon_zip_declares_correct_id(self):
        import zipfile, io
        data = harness._make_bm011_test_addon_zip()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read(f"{harness._BM011_TEST_ADDON_ID}/addon.xml").decode("utf-8")
        self.assertIn(harness._BM011_TEST_ADDON_ID, xml)

    def test_test_addon_zip_has_no_path_traversal(self):
        import zipfile, io
        data = harness._make_bm011_test_addon_zip()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                self.assertNotIn("..", name)

    def test_addons_xml_is_valid_utf8(self):
        xml = harness._make_bm011_addons_xml()
        self.assertIsInstance(xml, bytes)
        xml.decode("utf-8")  # must not raise

    def test_addons_xml_contains_test_addon_id(self):
        xml = harness._make_bm011_addons_xml()
        self.assertIn(harness._BM011_TEST_ADDON_ID.encode(), xml)

    def test_addons_xml_starts_with_xml_decl(self):
        xml = harness._make_bm011_addons_xml()
        self.assertTrue(xml.startswith(b"<?xml"))

    def test_repo_zip_is_valid_zip(self):
        import zipfile, io
        data = harness._make_bm011_repo_zip(8922)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))

    def test_repo_zip_contains_info_url(self):
        import zipfile, io
        data = harness._make_bm011_repo_zip(8922)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read(f"{harness._TEST_REPO_ADDON_ID}/addon.xml").decode("utf-8")
        self.assertIn("127.0.0.1:8922", xml)
        self.assertIn("addons.xml", xml)

    def test_repo_zip_contains_datadir_url(self):
        import zipfile, io
        data = harness._make_bm011_repo_zip(8922)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read(f"{harness._TEST_REPO_ADDON_ID}/addon.xml").decode("utf-8")
        self.assertIn("datadir", xml)

    def test_repo_zip_declares_repository_extension(self):
        import zipfile, io
        data = harness._make_bm011_repo_zip(8922)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read(f"{harness._TEST_REPO_ADDON_ID}/addon.xml").decode("utf-8")
        self.assertIn("xbmc.addon.repository", xml)

    def test_repo_zip_port_is_embedded(self):
        import zipfile, io
        for port in [8922, 9999]:
            data = harness._make_bm011_repo_zip(port)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                xml = zf.read(f"{harness._TEST_REPO_ADDON_ID}/addon.xml").decode("utf-8")
            self.assertIn(f"127.0.0.1:{port}", xml)

    def test_repo_zip_uses_dir_schema(self):
        # Kodi 21 dropped the flat <info>/<datadir>/<checksum> format.
        # The extension must use <dir> elements or Kodi silently ignores the repo.
        import zipfile, io
        data = harness._make_bm011_repo_zip(8922)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read(f"{harness._TEST_REPO_ADDON_ID}/addon.xml").decode("utf-8")
        self.assertIn("<dir>", xml)

    def test_repo_zip_datadir_zip_true(self):
        # zip="true" tells Kodi addon ZIPs are at {datadir}/{id}/{ver}/{id}-{ver}.zip.
        # zip="false" would tell Kodi to look for unwrapped files, which we don't serve.
        import zipfile, io
        data = harness._make_bm011_repo_zip(8922)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read(f"{harness._TEST_REPO_ADDON_ID}/addon.xml").decode("utf-8")
        self.assertIn('zip="true"', xml)
        self.assertNotIn('zip="false"', xml)


# ---------------------------------------------------------------------------
# _MultiFileHandler
# ---------------------------------------------------------------------------

class TestMultiFileHandler(unittest.TestCase):
    """_MultiFileHandler serves files by path and 404s for unknown paths."""

    def _make_handler(self, files):
        import io as _io
        from http.server import BaseHTTPRequestHandler
        wbuf = _io.BytesIO()

        class _H(harness._MultiFileHandler):
            _files = files

            def __init__(self):
                pass  # skip real __init__

            def send_response(self, code):
                self._resp_code = code

            def send_header(self, k, v):
                pass

            def end_headers(self):
                pass

            @property
            def wfile(self):
                return wbuf

        return _H(), wbuf

    def test_returns_200_for_known_path(self):
        h, _ = self._make_handler({"/test.zip": b"DATA"})
        h.path = "/test.zip"
        h.do_GET()
        self.assertEqual(h._resp_code, 200)

    def test_returns_404_for_unknown_path(self):
        h, _ = self._make_handler({"/test.zip": b"DATA"})
        h.path = "/not-found.zip"
        h.do_GET()
        self.assertEqual(h._resp_code, 404)

    def test_writes_correct_content(self):
        payload = b"HELLO_KODI_ZIP"
        h, wbuf = self._make_handler({"/repo.zip": payload})
        h.path = "/repo.zip"
        h.do_GET()
        self.assertIn(payload, wbuf.getvalue())


# ---------------------------------------------------------------------------
# BM-011 CLI route
# ---------------------------------------------------------------------------

class TestValidateAddonCliRoute(unittest.TestCase):
    """CLI routes validate-addon to validate_addon()."""

    def test_validate_addon_routes(self):
        called = {}

        def fake_validate_addon():
            called["yes"] = True

        with patch.object(harness, "validate_addon", side_effect=fake_validate_addon):
            rc = harness.main(["validate-addon"])
        self.assertEqual(rc, 0)
        self.assertIn("yes", called)


if __name__ == "__main__":
    unittest.main()
