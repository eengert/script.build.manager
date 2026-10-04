"""Offline safety tests for the isolated BM-023A macOS runtime tooling."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tools.bm023a_runtime as runtime  # noqa: E402


class RuntimeFixture(unittest.TestCase):
    def setUp(self):
        temp_parent = Path(tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(dir=temp_parent)
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.project = base / "project"
        self.root = self.project / ".bm023a-test-runtime"
        self.home = self.root / "home"
        self.marker = self.root / "BM023A_TEST_STATE.txt"
        self.app = self.root / "distribution" / "Kodi.app"
        self.project.mkdir()
        (self.project / ".gitignore").write_text(".bm023a-test-runtime/\n", encoding="utf-8")
        self.root.mkdir()
        self.home.mkdir()
        self.marker.write_text(runtime.RUNTIME_MARKER_TEXT, encoding="utf-8")
        self.app.mkdir(parents=True)
        self.patches = patch.multiple(
            runtime,
            PROJECT_ROOT=self.project,
            RUNTIME_ROOT=self.root,
            RUNTIME_HOME=self.home,
            RUNTIME_MARKER=self.marker,
            STAGED_KODI_APP=self.app,
        )
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.normal_home = base / "normal-user-home"


class TestIsolatedProfileMapping(RuntimeFixture):
    def test_home_resolves_to_expected_macos_profile_root(self):
        paths = runtime.verify_runtime_layout(self.home, inherited_home=self.normal_home)
        self.assertEqual(
            paths.kodi_home,
            self.home / "Library" / "Application Support" / "Kodi",
        )
        self.assertEqual(paths.userdata, paths.kodi_home / "userdata")
        self.assertEqual(paths.addons, paths.kodi_home / "addons")
        self.assertEqual(paths.log_file, self.home / "Library" / "Logs" / "kodi.log")

    def test_inherited_normal_home_is_rejected(self):
        with self.assertRaisesRegex(runtime.RuntimeSafetyError, "normal HOME"):
            runtime.verify_runtime_layout(self.home, inherited_home=self.home)

    def test_normal_kodi_profile_overlap_is_rejected_lexically(self):
        # The inherited HOME is deliberately chosen so its profile would sit
        # beneath the candidate test HOME. No normal-profile file is created.
        inherited = self.home / "Library" / "Application Support" / "Kodi"
        with self.assertRaisesRegex(runtime.RuntimeSafetyError, "normal Kodi profile"):
            runtime.verify_runtime_layout(self.home, inherited_home=inherited)

    def test_expected_home_outside_project_runtime_is_rejected(self):
        with self.assertRaisesRegex(runtime.RuntimeSafetyError, "project BM-023A isolated HOME"):
            runtime.verify_runtime_layout(self.normal_home / "other", inherited_home=self.normal_home)


class TestPathAndAppSafety(RuntimeFixture):
    def test_symlink_in_home_path_is_rejected_before_descendant_lookup(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.home / "Library").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(runtime.RuntimeSafetyError, "symlink"):
            runtime.verify_runtime_layout(self.home, inherited_home=self.normal_home)

    def test_unsafe_app_profile_combination_is_rejected(self):
        outside_app = Path(self.temp.name) / "unapproved" / "Kodi.app"
        with self.assertRaisesRegex(runtime.RuntimeSafetyError, "dedicated runtime path"):
            runtime.verify_runtime_layout(
                self.home,
                inherited_home=self.normal_home,
                app_bundle=outside_app,
            )

class TestMigration(RuntimeFixture):
    def _source_tree(self):
        source = Path(self.temp.name) / "portable_data"
        (source / "addons" / "packages").mkdir(parents=True)
        (source / "addons" / "packages" / "redlight.zip").write_bytes(b"addon-package")
        (source / "media").mkdir(parents=True)
        (source / "userdata" / "Database").mkdir(parents=True)
        (source / "userdata" / "Database" / "Addons33.db").write_bytes(b"database-fixture")
        (source / "userdata" / "addon_data" / "script.build.manager").mkdir(parents=True)
        (source / "userdata" / "addon_data" / "script.build.manager" / "frozen_install_transaction.json").write_bytes(b"transaction-fixture")
        (source / "temp").mkdir()
        (source / "temp" / "kodi.log").write_text("log-fixture", encoding="utf-8")
        (source / "system").mkdir()
        return source

    def test_mapping_copies_addons_and_userdata_to_normal_home_layout(self):
        source = self._source_tree()
        entries = runtime.migration_plan(source, self.home)
        self.assertEqual(
            [(entry.source.name, entry.destination.relative_to(self.home).as_posix()) for entry in entries],
            [
                ("addons", "Library/Application Support/Kodi/addons"),
                ("media", "Library/Application Support/Kodi/media"),
                ("userdata", "Library/Application Support/Kodi/userdata"),
            ],
        )
        self.assertEqual(runtime.OMITTED_PORTABLE_ROOTS, ("system", "temp"))

    def test_migration_preserves_source_and_copies_state_bytes(self):
        source = self._source_tree()
        before = {
            name: runtime._tree_manifest(source / name)
            for name in runtime.MIGRATED_ROOTS
        }
        paths = runtime.migrate_portable_state(source, self.home)
        after = {
            name: runtime._tree_manifest(source / name)
            for name in runtime.MIGRATED_ROOTS
        }
        self.assertEqual(before, after)
        for name in runtime.MIGRATED_ROOTS:
            self.assertEqual(runtime._tree_manifest(source / name), runtime._tree_manifest(paths.kodi_home / name))
        self.assertFalse((paths.kodi_home / "temp").exists())
        self.assertTrue((source / "temp" / "kodi.log").is_file())

    def test_migration_rejects_symlink_escape(self):
        source = self._source_tree()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (source / "userdata" / "outside-link").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(runtime.RuntimeSafetyError, "symlink"):
            runtime.migrate_portable_state(source, self.home)
        self.assertFalse((self.home / "Library" / "Application Support" / "Kodi").exists())


class TestChildEnvironment(RuntimeFixture):
    def test_home_and_redirecting_environment_are_controlled(self):
        inherited = {
            "HOME": str(self.normal_home),
            "KODI_HOME": "/unsafe/kodi-home",
            "KODI_PROFILE": "/unsafe/profile",
            "XBMC_HOME": "/unsafe/xbmc-home",
            "PYTHONHOME": "/unsafe/python-home",
            "PYTHONPATH": "/unsafe/python-path",
            "XDG_CONFIG_HOME": "/unsafe/config",
            "XDG_DATA_HOME": "/unsafe/data",
            "XDG_CACHE_HOME": "/unsafe/cache",
            "PYTHONDONTWRITEBYTECODE": "inherited",
        }
        env = runtime.build_child_environment(self.home, inherited=inherited)
        self.assertEqual(env["HOME"], str(self.home))
        self.assertEqual(env["TMPDIR"], str(self.root / "tmp"))
        for key in ("KODI_HOME", "KODI_PROFILE", "XBMC_HOME", "XBMC_PROFILE", "PYTHONHOME", "PYTHONPATH"):
            self.assertNotIn(key, env)
        self.assertEqual(env["XDG_CONFIG_HOME"], str(self.home / ".config"))
        self.assertEqual(env["XDG_DATA_HOME"], str(self.home / ".local" / "share"))
        self.assertEqual(env["XDG_CACHE_HOME"], str(self.home / ".cache"))
        self.assertEqual(
            env["PYTHONPYCACHEPREFIX"],
            str(self.home / ".cache" / "python-bytecode"),
        )
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", env)

    def test_optional_bytecode_suppression_is_passed_to_child(self):
        env = runtime.build_child_environment(
            self.home,
            inherited={"HOME": str(self.normal_home)},
            suppress_python_bytecode=True,
        )
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")


class TestBundleMutationDefense(RuntimeFixture):
    def test_bundle_manifest_detects_added_and_changed_files(self):
        executable = self.app / "Contents" / "MacOS" / "Kodi"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"signed-binary-fixture")
        before = runtime.capture_bundle_manifest(self.app)
        executable.write_bytes(b"changed-binary-fixture")
        (self.app / "generated.pyc").write_bytes(b"unexpected-cache")
        after = runtime.capture_bundle_manifest(self.app)
        differences = runtime.compare_bundle_manifests(before, after)
        self.assertIn("Contents/MacOS/Kodi", differences["changed"])
        self.assertIn("generated.pyc", differences["added"])

    def test_launcher_passes_controlled_home_and_never_adds_portable_flag(self):
        paths = runtime.paths_for_home(self.home)
        paths.userdata.mkdir(parents=True)
        paths.addons.mkdir(parents=True)
        fake_executable = self.app / "Contents" / "MacOS" / "Kodi"
        fake_executable.parent.mkdir(parents=True)
        fake_executable.write_bytes(b"fixture")
        sentinel = {"schema": 1, "entries": [], "sha256": "unchanged"}
        popen_call = {}

        class FinishedProcess:
            def wait(self):
                return 0

        def fake_popen(argv, *, cwd, env):
            popen_call.update(argv=argv, cwd=cwd, env=env)
            return FinishedProcess()

        with (
            patch.object(runtime, "verify_kodi_app", return_value=(fake_executable, {})),
            patch.object(runtime, "capture_bundle_manifest", return_value=sentinel),
            patch.object(runtime, "_save_manifest"),
            patch.object(runtime.subprocess, "Popen", side_effect=fake_popen),
        ):
            result = runtime.launch_kodi(
                self.app,
                self.home,
                inherited_env={
                    "HOME": str(self.normal_home),
                    "KODI_HOME": "/unsafe",
                    "XDG_CONFIG_HOME": "/unsafe",
                    "PYTHONHOME": "/unsafe",
                    "PYTHONPATH": "/unsafe",
                },
            )
        self.assertEqual(result, 0)
        self.assertEqual(popen_call["argv"], [str(fake_executable)])
        self.assertNotIn("-p", popen_call["argv"])
        self.assertEqual(popen_call["env"]["HOME"], str(self.home))
        self.assertNotIn("KODI_HOME", popen_call["env"])
        self.assertNotIn("PYTHONHOME", popen_call["env"])
        self.assertEqual(popen_call["cwd"], str(self.root))


class TestSourceHygiene(RuntimeFixture):
    def test_tracked_runtime_code_has_no_machine_specific_absolute_paths(self):
        paths = (
            _PROJECT_ROOT / "tools" / "bm023a_runtime.py",
            _PROJECT_ROOT / "tests" / "test_bm023a_runtime.py",
        )
        for path in paths:
            source = path.read_text(encoding="utf-8")
            users_prefix = "/" + "Users" + "/"
            applications_prefix = "/" + "Applications" + "/"
            self.assertNotIn(users_prefix, source)
            self.assertNotIn(applications_prefix, source)
            self.assertNotIn("candidate-" + "FrozenManifest-v1.json", source)


if __name__ == "__main__":
    unittest.main()
