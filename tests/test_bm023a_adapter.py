"""Offline provenance, diagnostics, and packaging tests for BM-023A adapter."""

from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from enum import IntEnum
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

from resources.lib.artifacts import ArtifactStore
from resources.lib.frozen import FrozenBuildManifest
from resources.lib.frozen_install import (
    FrozenInstallCoordinator,
    FrozenInstallPhase,
    FrozenInstallTransaction,
    FrozenLifecycleStage,
)
from resources.lib.build_manager import ReconcileRequest
from resources.lib.restart import RestartRequirement
from resources.lib.transaction import RestartTransaction, TransactionPhase
from resources.lib.update_guard import AddonUpdatePolicy
from tools import bm023a_adapter_support
from tools.bm023a_adapter_support import (
    ADAPTER_VERSION,
    STATUS_KEYS,
    AdapterBootstrapError,
    choose_missing_artifact_resolution,
    identify_adapter_result,
    parse_adapter_mode,
    reject_cached_production_modules,
    recover_frozen_install,
    retry_held_frozen_install,
    safe_failure_payload,
    stage_manifest_artifacts,
    verify_build_manager_source,
    inspect_retained_inputs,
    read_adapter_status,
    repair_frozen_install_source,
    require_retained_inputs,
    verify_frozen_install_source,
    verify_production_module_sources,
)
from tools.build_bm023a_adapter import build_adapter, read_existing_adapter_config


class TestBm023aAdapterSourceVerification(unittest.TestCase):
    def make_install(self, root: Path):
        addons_root = root / "addons"
        addon_root = addons_root / "script.build.manager"
        package = addon_root / "resources" / "lib"
        package.mkdir(parents=True)
        package_file = package / "__init__.py"
        package_file.write_text("# fixture package\n", encoding="utf-8")
        module = ModuleType("resources.lib")
        module.__file__ = str(package_file)
        module.__path__ = [str(package)]
        return addons_root, addon_root, package_file, module

    def test_namespace_parent_has_no_file_but_concrete_lib_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons, addon, _, lib_module = self.make_install(Path(tmp))
            namespace_resources = ModuleType("resources")
            namespace_resources.__file__ = None
            self.assertIsNone(namespace_resources.__file__)
            self.assertEqual(
                verify_build_manager_source(addons, addon, lib_module),
                Path(lib_module.__file__).resolve(),
            )

    def test_concrete_resources_lib_package_provenance_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons, addon, package_file, lib_module = self.make_install(Path(tmp))
            self.assertEqual(
                verify_build_manager_source(addons, addon, lib_module),
                package_file.resolve(),
            )

    def test_module_inside_expected_addon_root_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons, addon, package_file, lib_module = self.make_install(Path(tmp))
            actual = verify_build_manager_source(addons, addon, lib_module)
            self.assertTrue(actual.is_relative_to(addon.resolve()))
            self.assertEqual(actual, package_file.resolve())

    def test_module_outside_expected_addon_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addons, addon, _, _ = self.make_install(root)
            outside = root / "host" / "resources" / "lib" / "__init__.py"
            outside.parent.mkdir(parents=True)
            outside.write_text("# host package\n", encoding="utf-8")
            host_module = ModuleType("resources.lib")
            host_module.__file__ = str(outside)
            with self.assertRaises(AdapterBootstrapError) as raised:
                verify_build_manager_source(addons, addon, host_module)
            self.assertEqual(raised.exception.failure_category, "module_source_mismatch")

    def test_symlinked_package_file_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addons, addon, package_file, lib_module = self.make_install(root)
            outside = root / "outside.py"
            outside.write_text("# escaped source\n", encoding="utf-8")
            package_file.unlink()
            try:
                package_file.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {type(exc).__name__}")
            lib_module.__file__ = str(package_file)
            with self.assertRaises(AdapterBootstrapError) as raised:
                verify_build_manager_source(addons, addon, lib_module)
            self.assertEqual(raised.exception.failure_category, "module_source_mismatch")

    def test_wrong_addon_installation_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addons, addon, _, lib_module = self.make_install(root)
            wrong_addons = root / "other-addons"
            wrong_addons.mkdir()
            with self.assertRaises(AdapterBootstrapError) as raised:
                verify_build_manager_source(wrong_addons, addon, lib_module)
            self.assertEqual(raised.exception.failure_category, "addon_root_mismatch")

    def test_host_or_project_resources_package_cannot_masquerade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addons, addon, _, _ = self.make_install(root)
            project_file = root / "project" / "resources" / "lib" / "__init__.py"
            project_file.parent.mkdir(parents=True)
            project_file.write_text("# project package\n", encoding="utf-8")
            project_module = ModuleType("resources.lib")
            project_module.__file__ = str(project_file)
            with self.assertRaises(AdapterBootstrapError):
                verify_build_manager_source(addons, addon, project_module)

    def test_resources_lib_with_no_concrete_file_has_safe_path_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons, addon, _, _ = self.make_install(Path(tmp))
            namespace_lib = ModuleType("resources.lib")
            namespace_lib.__file__ = None
            with self.assertRaises(AdapterBootstrapError) as raised:
                verify_build_manager_source(addons, addon, namespace_lib)
            self.assertEqual(raised.exception.stage, "VERIFY_BUILD_MANAGER_SOURCE")
            self.assertEqual(raised.exception.failing_callable, "pathlib.Path")
            self.assertEqual(raised.exception.failure_category, "path_argument_is_none")

    def test_old_namespace_package_expression_reproduces_original_typeerror(self):
        old_resources = ModuleType("resources")
        old_resources.__file__ = None
        with self.assertRaises(TypeError):
            Path(old_resources.__file__)

    def test_preloaded_production_child_module_fails_with_fixed_cache_diagnostic(self):
        cached = {"resources.lib.frozen_install": ModuleType("resources.lib.frozen_install")}
        with self.assertRaises(AdapterBootstrapError) as raised:
            reject_cached_production_modules(
                ("resources.lib.frozen_install",), cached
            )
        payload = safe_failure_payload(
            "IMPORT_PRODUCTION_MODULES", "importlib.import_module", raised.exception
        )
        self.assertEqual(payload["adapter_stage"], "IMPORT_PRODUCTION_MODULES")
        self.assertEqual(payload["failing_callable"], "importlib.import_module")
        self.assertEqual(payload["failure_category"], "module_cache_preloaded")
        self.assertEqual(
            set(payload),
            {"ok", "error_type", "adapter_stage", "failing_callable", "failure_category"},
        )

    def test_production_child_module_must_bind_to_exact_installed_file(self):
        import importlib.machinery

        with tempfile.TemporaryDirectory() as tmp:
            addons, addon, _, _ = self.make_install(Path(tmp))
            package = addon / "resources" / "lib"
            expected_file = package / "frozen_install.py"
            expected_file.write_text("# installed source\n", encoding="utf-8")
            module = ModuleType("resources.lib.frozen_install")
            module.__file__ = str(expected_file)
            module.__spec__ = importlib.machinery.ModuleSpec(
                module.__name__, loader=None, origin=str(expected_file)
            )
            verify_production_module_sources(
                addon, {module.__name__: module}
            )

            outside = Path(tmp) / "other-addon" / "frozen_install.py"
            outside.parent.mkdir()
            outside.write_text("# mismatched source\n", encoding="utf-8")
            module.__file__ = str(outside)
            module.__spec__ = importlib.machinery.ModuleSpec(
                module.__name__, loader=None, origin=str(outside)
            )
            with self.assertRaises(AdapterBootstrapError) as raised:
                verify_production_module_sources(
                    addon, {module.__name__: module}
                )
            self.assertEqual(raised.exception.failure_category, "module_source_mismatch")

    def test_frozen_install_source_must_match_adapter_build_fingerprint(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            addons, addon, _, _ = self.make_install(Path(tmp))
            source_file = addon / "resources" / "lib" / "frozen_install.py"
            source_file.write_text("# reviewed source\n", encoding="utf-8")
            expected = hashlib.sha256(source_file.read_bytes()).hexdigest()
            verify_frozen_install_source(addon, expected)

            source_file.write_text("# other on-disk source\n", encoding="utf-8")
            with self.assertRaises(AdapterBootstrapError) as raised:
                verify_frozen_install_source(addon, expected)
            self.assertEqual(raised.exception.stage, "VERIFY_BUILD_MANAGER_SOURCE")
            self.assertEqual(raised.exception.failure_category, "module_source_mismatch")
            observed = hashlib.sha256(source_file.read_bytes()).hexdigest()
            self.assertNotEqual(expected, observed)
            self.assertEqual(raised.exception.expected_sha256, expected)
            self.assertEqual(raised.exception.observed_sha256, observed)

            secret_path = str(addon / "private" / "overlay.json")
            raised.exception.args = ("PRIVATE_RESULT_VALUE", secret_path)
            payload = safe_failure_payload(
                "LOCATE_BUILD_MANAGER", "xbmcvfs.translatePath", raised.exception
            )
            self.assertEqual(
                set(payload),
                {
                    "ok",
                    "error_type",
                    "adapter_stage",
                    "failing_callable",
                    "failure_category",
                    "expected_sha256",
                    "observed_sha256",
                },
            )
            self.assertEqual(payload["expected_sha256"], expected)
            self.assertEqual(payload["observed_sha256"], observed)
            serialized = json.dumps(payload)
            self.assertNotIn("PRIVATE_RESULT_VALUE", serialized)
            self.assertNotIn(secret_path, serialized)

            source_file.write_text("# reviewed source\n", encoding="utf-8")
            source_file.unlink()
            with self.assertRaises(AdapterBootstrapError) as missing:
                verify_frozen_install_source(addon, expected)
            self.assertEqual(missing.exception.failure_category, "module_source_missing")
            missing_payload = safe_failure_payload(
                "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", missing.exception
            )
            self.assertEqual(
                set(missing_payload),
                {"ok", "error_type", "adapter_stage", "failing_callable", "failure_category"},
            )

            source_file.write_text("# reviewed source\n", encoding="utf-8")
            with patch.object(Path, "read_bytes", side_effect=PermissionError("private path")):
                with self.assertRaises(AdapterBootstrapError) as unreadable:
                    verify_frozen_install_source(addon, expected)
            self.assertEqual(
                unreadable.exception.failure_category, "module_source_unreadable"
            )
            unreadable_payload = safe_failure_payload(
                "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", unreadable.exception
            )
            self.assertEqual(
                set(unreadable_payload),
                {"ok", "error_type", "adapter_stage", "failing_callable", "failure_category"},
            )
            self.assertNotIn("private path", json.dumps(unreadable_payload))

    def test_corrected_concrete_package_verification_passes_same_namespace_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons, addon, _, lib_module = self.make_install(Path(tmp))
            namespace_resources = ModuleType("resources")
            namespace_resources.__file__ = None
            self.assertIsNone(namespace_resources.__file__)
            self.assertTrue(
                verify_build_manager_source(addons, addon, lib_module).is_file()
            )


class TestBm023aAdapterDiagnosticsAndPackaging(unittest.TestCase):
    def test_current_install_call_signature_binds(self):
        import inspect

        inspect.signature(FrozenInstallCoordinator.install).bind(
            object(),
            FrozenBuildManifest,
            manifest_path="manifest",
            device_profile_id="profile",
            configuration_manifest_path="configuration",
            interactive=True,
        )

    def test_frozen_retry_callback_forwards_transaction_access(self):
        template = Path(__file__).parents[1] / "tools/bm023a_adapter/default.py.in"
        tree = ast.parse(template.read_text(encoding="utf-8"))
        install_call = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "FrozenInstallCoordinator"
            and any(
                keyword.arg == "configuration_runner"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "run_configuration"
                for keyword in node.keywords
            )
        )
        callback_reference = next(
            keyword.value for keyword in install_call.keywords
            if keyword.arg == "configuration_runner"
        )
        self.assertIsInstance(callback_reference, ast.Name)
        callback_definition = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "run_configuration"
        )
        calls = []
        expected_result = object()
        expected_manager = object()

        class RecordingRestartCoordinator:
            def __init__(self, manager):
                self.manager = manager

            def reconcile(self, request, *, transaction_access=None):
                calls.append((self.manager, request, transaction_access))
                return expected_result

        namespace = {
            "manager": expected_manager,
            "restart_module": SimpleNamespace(
                RestartCoordinator=RecordingRestartCoordinator
            ),
        }
        callback_module = ast.Module(
            body=[callback_definition], type_ignores=[]
        )
        exec(
            compile(callback_module, str(template), "exec"),
            namespace,
        )

        request = object()
        transaction_access = object()
        result = namespace[callback_reference.id](
            request, transaction_access=transaction_access
        )
        self.assertIs(result, expected_result)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], expected_manager)
        self.assertIs(calls[0][1], request)
        self.assertIs(calls[0][2], transaction_access)

    def test_held_retry_callback_binds_shared_store_and_forwards_capability(self):
        template = Path(__file__).parents[1] / "tools/bm023a_adapter/default.py.in"
        tree = ast.parse(template.read_text(encoding="utf-8"))
        callback = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "run_held_retry_configuration"
        )
        calls = []
        manager = object()
        restart_store = object()
        expected = object()

        class RecordingRestartCoordinator:
            def __init__(self, actual_manager, *, store):
                self.manager = actual_manager
                self.store = store

            def reconcile(self, request, *, transaction_access=None):
                calls.append((self.manager, self.store, request, transaction_access))
                return expected

        namespace = {
            "manager": manager,
            "restart_store": restart_store,
            "restart_module": SimpleNamespace(
                RestartCoordinator=RecordingRestartCoordinator
            ),
        }
        exec(compile(ast.Module(body=[callback], type_ignores=[]), str(template), "exec"), namespace)
        request = object()
        access = object()
        result = namespace[callback.name](request, transaction_access=access)
        self.assertIs(result, expected)
        self.assertEqual(calls, [(manager, restart_store, request, access)])

    def test_source_failure_has_safe_stage_callable_and_category(self):
        fake_private_value = "DO_NOT_SERIALIZE_PRIVATE_VALUE"
        error = AdapterBootstrapError(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "path_argument_is_none"
        )
        error.args = (fake_private_value,)
        payload = safe_failure_payload(
            "IMPORT_RESOURCES", "importlib.import_module", error
        )
        self.assertEqual(payload["adapter_stage"], "VERIFY_BUILD_MANAGER_SOURCE")
        self.assertEqual(payload["failing_callable"], "pathlib.Path")
        self.assertEqual(payload["failure_category"], "path_argument_is_none")

    def test_payload_omits_exception_text_traceback_and_paths(self):
        fake_private_value = "DO_NOT_SERIALIZE_PRIVATE_VALUE"
        fake_path = "/private/overlay/fake.json"
        error = RuntimeError(f"{fake_private_value} {fake_path}")
        payload = safe_failure_payload(
            "LOAD_PRIVATE_OVERLAY", "PrivateOverlayStore.import_file", error
        )
        serialized = json.dumps(payload)
        self.assertNotIn(fake_private_value, serialized)
        self.assertNotIn(fake_path, serialized)
        self.assertNotIn(str(error), serialized)
        self.assertNotIn("traceback", serialized.lower())

    def test_unknown_failure_labels_are_replaced_by_allowlisted_values(self):
        payload = safe_failure_payload(
            "secret-path", "arbitrary_callable", RuntimeError("sensitive detail"),
            category="unapproved_category",
        )
        self.assertEqual(payload["adapter_stage"], "LOCATE_BUILD_MANAGER")
        self.assertEqual(payload["failing_callable"], "result_serializer")
        self.assertEqual(payload["failure_category"], "operation_failed")

    def test_generator_extracts_only_allowlisted_literal_configuration(self):
        source_text = "\n".join((
            "MANIFEST_PATH = '/safe/manifest.json'",
            "ARTIFACT_ROOT = '/safe/artifacts'",
            "CONFIGURATION_PATH = '/safe/config.json'",
            "OVERLAY_SOURCE = '/sensitive/path/never-print.json'",
            "DEVICE_PROFILE_ID = 'family-room'",
            "EXPECTED_OVERLAY_ID = 'overlay-id'",
            "UNRELATED = '/must/not/be-copied'",
        ))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "old.py"
            source.write_text(source_text, encoding="utf-8")
            values = read_existing_adapter_config(source)
        self.assertEqual(set(values), {
            "MANIFEST_PATH", "ARTIFACT_ROOT", "CONFIGURATION_PATH",
            "OVERLAY_SOURCE", "DEVICE_PROFILE_ID", "EXPECTED_OVERLAY_ID",
        })
        self.assertNotIn("UNRELATED", values)

    def test_builder_emits_version_bumped_installable_zip_with_verified_modules(self):
        values = {
            "MANIFEST_PATH": "/fixture/manifest.json",
            "ARTIFACT_ROOT": "/fixture/artifacts",
            "CONFIGURATION_PATH": "/fixture/config.json",
            "OVERLAY_SOURCE": "/fixture/overlay.json",
            "DEVICE_PROFILE_ID": "fixture-profile",
            "EXPECTED_OVERLAY_ID": "fixture-overlay",
        }
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = build_adapter(Path(tmp), values)
            self.assertEqual(ADAPTER_VERSION, "0.0.15")
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
                names = set(archive.namelist())
                self.assertEqual(names, {
                    "script.build.manager.bm023a_driver/addon.xml",
                    "script.build.manager.bm023a_driver/default.py",
                    "script.build.manager.bm023a_driver/adapter_config.py",
                    "script.build.manager.bm023a_driver/adapter_support.py",
                    "script.build.manager.bm023a_driver/bundled_frozen_install.py",
                })
                bundled_bytes = archive.read(
                    "script.build.manager.bm023a_driver/bundled_frozen_install.py"
                )
                default = archive.read(
                    "script.build.manager.bm023a_driver/default.py"
                ).decode("utf-8")
                adapter_config = archive.read(
                    "script.build.manager.bm023a_driver/adapter_config.py"
                ).decode("utf-8")
                addon_xml = archive.read(
                    "script.build.manager.bm023a_driver/addon.xml"
                ).decode("utf-8")
            self.assertIn('import_module("resources.lib")', default)
            self.assertNotIn("resources.__file__", default)
            self.assertIn("EXPECTED_FROZEN_INSTALL_SHA256 = ", adapter_config)
            config_tree = ast.parse(adapter_config)
            expected_digest = next(
                ast.literal_eval(node.value)
                for node in config_tree.body
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "EXPECTED_FROZEN_INSTALL_SHA256"
            )
            frozen_install_source = (
                Path(__file__).parents[1] / "resources/lib/frozen_install.py"
            )
            self.assertEqual(
                expected_digest,
                hashlib.sha256(frozen_install_source.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                hashlib.sha256(bundled_bytes).hexdigest(), expected_digest
            )
            self.assertIn('version="0.0.15"', addon_xml)
            compile(default, "generated-default.py", "exec")


class TestBm023aFrozenInstallRepair(unittest.TestCase):
    PINNED = b"# pinned reviewed frozen_install source\n"
    STALE = b"# stale installed frozen_install source\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.addon = self.root / "addons" / "script.build.manager"
        self.lib = self.addon / "resources" / "lib"
        self.lib.mkdir(parents=True)
        self.target = self.lib / "frozen_install.py"
        self.sibling = self.lib / "transaction.py"
        self.sibling.write_bytes(b"# sibling\n")
        self.bundled = self.root / "bundle" / "bundled_frozen_install.py"
        self.bundled.parent.mkdir()
        self.bundled.write_bytes(self.PINNED)
        self.backups = self.root / "backups"
        self.pin = hashlib.sha256(self.PINNED).hexdigest()

    def repair(self, addon=None, pin=None):
        return repair_frozen_install_source(
            self.addon if addon is None else addon,
            self.pin if pin is None else pin,
            self.backups,
            self.bundled,
        )

    def assert_failure(self, category):
        with self.assertRaises(AdapterBootstrapError) as caught:
            self.repair()
        self.assertEqual(caught.exception.failure_category, category)
        self.assertEqual(caught.exception.stage, "VERIFY_BUILD_MANAGER_SOURCE")
        return caught.exception

    def test_mismatch_is_backed_up_replaced_and_reverified(self):
        self.target.write_bytes(self.STALE)
        record = self.repair()
        self.assertEqual(self.target.read_bytes(), self.PINNED)
        self.assertEqual(record, {
            "sha256_before": hashlib.sha256(self.STALE).hexdigest(),
            "sha256_after": self.pin,
            "replaced": True,
        })
        backups = list(self.backups.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.STALE)
        self.assertEqual(sorted(p.name for p in self.lib.iterdir()),
                         ["frozen_install.py", "transaction.py"])
        self.assertEqual(self.sibling.read_bytes(), b"# sibling\n")
        verify_frozen_install_source(self.addon, self.pin)

    def test_match_is_untouched_and_needs_no_bundle_or_backup(self):
        self.target.write_bytes(self.PINNED)
        self.bundled.unlink()
        before = self.target.stat()
        record = self.repair()
        self.assertEqual(record, {
            "sha256_before": self.pin, "sha256_after": self.pin, "replaced": False,
        })
        self.assertEqual(self.target.read_bytes(), self.PINNED)
        self.assertEqual(self.target.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertFalse(self.backups.exists())

    def test_bundled_hash_mismatch_fails_closed_without_changes(self):
        self.target.write_bytes(self.STALE)
        self.bundled.write_bytes(b"# tampered bundle\n")
        self.assert_failure("bundled_source_mismatch")
        self.assertEqual(self.target.read_bytes(), self.STALE)
        self.assertFalse(self.backups.exists())

    def test_missing_bundle_fails_closed(self):
        self.target.write_bytes(self.STALE)
        self.bundled.unlink()
        self.assert_failure("bundled_source_mismatch")
        self.assertEqual(self.target.read_bytes(), self.STALE)

    def test_symlinked_target_fails_closed_and_outside_file_is_untouched(self):
        outside = self.root / "outside.py"
        outside.write_bytes(self.STALE)
        self.target.symlink_to(outside)
        self.assert_failure("source_target_invalid")
        self.assertEqual(outside.read_bytes(), self.STALE)
        self.assertTrue(self.target.is_symlink())
        self.assertFalse(self.backups.exists())

    def test_symlinked_package_directory_fails_closed(self):
        real_lib = self.root / "real-lib"
        self.lib.rename(real_lib)
        self.lib.symlink_to(real_lib, target_is_directory=True)
        (real_lib / "frozen_install.py").write_bytes(self.STALE)
        self.assert_failure("source_target_invalid")
        self.assertEqual((real_lib / "frozen_install.py").read_bytes(), self.STALE)

    def test_traversal_and_symlinked_addon_root_fail_closed(self):
        self.target.write_bytes(self.STALE)
        traversal = self.root / "addons" / "other" / ".." / "script.build.manager"
        (self.root / "addons" / "other").mkdir()
        with self.assertRaises(AdapterBootstrapError) as caught:
            self.repair(addon=traversal)
        self.assertEqual(caught.exception.failure_category, "source_target_invalid")
        link = self.root / "addons" / "link"
        link.symlink_to(self.addon, target_is_directory=True)
        with self.assertRaises(AdapterBootstrapError) as caught:
            self.repair(addon=link)
        self.assertEqual(caught.exception.failure_category, "source_target_invalid")
        self.assertEqual(self.target.read_bytes(), self.STALE)

    def test_wrong_addon_directory_name_fails_closed(self):
        other = self.root / "addons" / "script.other"
        (other / "resources" / "lib").mkdir(parents=True)
        (other / "resources" / "lib" / "frozen_install.py").write_bytes(self.STALE)
        with self.assertRaises(AdapterBootstrapError) as caught:
            self.repair(addon=other)
        self.assertEqual(caught.exception.failure_category, "source_target_invalid")
        self.assertEqual(
            (other / "resources" / "lib" / "frozen_install.py").read_bytes(), self.STALE
        )

    def test_replacement_failure_preserves_original(self):
        from unittest.mock import patch

        self.target.write_bytes(self.STALE)
        real_replace = os.replace

        def fail_for_target(source, destination, *args, **kwargs):
            if Path(destination) == self.target:
                raise OSError("simulated replace failure")
            return real_replace(source, destination, *args, **kwargs)

        with patch("tools.bm023a_adapter_support.os.replace", fail_for_target):
            error = self.assert_failure("source_replace_failed")
        self.assertNotIn("simulated", str(error))
        self.assertEqual(self.target.read_bytes(), self.STALE)
        self.assertEqual(sorted(p.name for p in self.lib.iterdir()),
                         ["frozen_install.py", "transaction.py"])

    def test_reverify_failure_restores_original(self):
        from unittest.mock import patch

        self.target.write_bytes(self.STALE)
        real_replace = os.replace
        calls = []

        def corrupting_replace(source, destination, *args, **kwargs):
            calls.append(Path(destination))
            if len(calls) == 1:
                Path(source).write_bytes(b"# corrupted in flight\n")
            return real_replace(source, destination, *args, **kwargs)

        with patch("tools.bm023a_adapter_support.os.replace", corrupting_replace):
            self.assert_failure("source_reverify_failed")
        self.assertEqual(self.target.read_bytes(), self.STALE)

    def test_only_sanitized_hashes_are_recorded_and_no_other_files_are_touched(self):
        private = self.addon / "settings.xml"
        private.write_bytes(b"secret")
        self.target.write_bytes(self.STALE)
        record = self.repair()
        self.assertEqual(set(record), {"sha256_before", "sha256_after", "replaced"})
        self.assertEqual(private.read_bytes(), b"secret")
        self.assertEqual(
            sorted(p.name for p in self.addon.iterdir()), ["resources", "settings.xml"]
        )

    def test_invalid_pin_and_none_root_are_sanitized(self):
        with self.assertRaises(AdapterBootstrapError) as caught:
            self.repair(pin="not-a-digest")
        self.assertEqual(caught.exception.failure_category, "invalid_input")
        with self.assertRaises(AdapterBootstrapError) as caught:
            repair_frozen_install_source(None, self.pin, self.backups, self.bundled)
        self.assertEqual(caught.exception.failure_category, "path_argument_is_none")

    def test_verify_frozen_install_source_still_rejects_mismatch(self):
        self.target.write_bytes(self.STALE)
        with self.assertRaises(AdapterBootstrapError) as caught:
            verify_frozen_install_source(self.addon, self.pin)
        self.assertEqual(caught.exception.failure_category, "module_source_mismatch")


class TestBm023aRetainedInputsDiagnostics(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.manifest = self.root / "manifest.json"
        self.artifact_root = self.root / "retained"

    def populate(self, *, manifest=True, entries=1):
        if manifest:
            self.manifest.write_text("{}", encoding="utf-8")
        if entries is not None:
            (self.artifact_root / "artifacts").mkdir(parents=True)
            for index in range(entries):
                (self.artifact_root / "artifacts" / f"e{index}").write_bytes(b"x")

    def inspect(self):
        return inspect_retained_inputs(str(self.manifest), str(self.artifact_root))

    def category(self, record):
        with self.assertRaises(AdapterBootstrapError) as raised:
            require_retained_inputs(record)
        self.assertEqual(raised.exception.stage, "LOAD_FROZEN_MANIFEST")
        self.assertEqual(raised.exception.failing_callable, "pathlib.Path")
        return raised.exception.failure_category

    def test_present_manifest_and_artifacts_pass_with_count(self):
        self.populate(entries=3)
        record = self.inspect()
        self.assertEqual(set(record), bm023a_adapter_support.RETAINED_INPUTS_KEYS)
        self.assertEqual(record["artifact_entry_count"], 3)
        self.assertIsNone(require_retained_inputs(record))

    def test_missing_manifest_is_distinct(self):
        self.populate(manifest=False)
        record = self.inspect()
        self.assertFalse(record["manifest_present"])
        self.assertEqual(self.category(record), "retained_manifest_missing")

    def test_manifest_directory_is_treated_as_missing(self):
        self.populate(manifest=False)
        self.manifest.mkdir()
        self.assertEqual(self.category(self.inspect()), "retained_manifest_missing")

    def test_unreadable_manifest_is_distinct(self):
        self.populate()
        self.manifest.chmod(0)
        self.addCleanup(self.manifest.chmod, 0o600)
        if os.access(self.manifest, os.R_OK):
            self.skipTest("file permissions are not enforced")
        record = self.inspect()
        self.assertTrue(record["manifest_present"])
        self.assertFalse(record["manifest_readable"])
        self.assertEqual(self.category(record), "retained_manifest_unreadable")

    def test_empty_artifact_store_is_reported_with_zero_count(self):
        self.populate(entries=0)
        record = self.inspect()
        self.assertTrue(record["artifact_store_present"])
        self.assertEqual(record["artifact_entry_count"], 0)
        self.assertEqual(self.category(record), "retained_artifacts_missing")

    def test_absent_artifact_store_is_reported(self):
        self.populate(entries=None)
        record = self.inspect()
        self.assertFalse(record["artifact_store_present"])
        self.assertEqual(self.category(record), "retained_artifacts_missing")

    def test_manifest_failure_takes_precedence_and_record_keeps_both_facts(self):
        self.populate(manifest=False, entries=0)
        record = self.inspect()
        self.assertEqual(self.category(record), "retained_manifest_missing")
        self.assertEqual(record["artifact_entry_count"], 0)

    def test_record_contains_only_booleans_and_a_count_and_no_paths(self):
        self.populate(manifest=False, entries=None)
        record = self.inspect()
        for key, value in record.items():
            self.assertIsInstance(value, (bool, int), key)
        self.assertNotIn(str(self.root), json.dumps(record))
        self.assertEqual(
            inspect_retained_inputs(None, None),
            {
                "manifest_present": False, "manifest_readable": False,
                "artifact_store_present": False, "artifact_store_readable": False,
                "artifact_entry_count": 0,
            },
        )

    def test_failure_payload_for_missing_input_has_no_paths_or_exception_text(self):
        self.populate(manifest=False)
        error = None
        try:
            require_retained_inputs(self.inspect())
        except AdapterBootstrapError as raised:
            error = raised
        payload = safe_failure_payload("LOAD_FROZEN_MANIFEST", "pathlib.Path", error)
        self.assertEqual(payload["failure_category"], "retained_manifest_missing")
        self.assertNotIn(str(self.root), json.dumps(payload))

    def test_file_and_permission_errors_are_safe_error_types(self):
        for error in (FileNotFoundError("/private/tmp/secret"), PermissionError("/x")):
            payload = safe_failure_payload("LOAD_FROZEN_MANIFEST", "pathlib.Path", error)
            self.assertEqual(payload["error_type"], type(error).__name__)
            self.assertEqual(payload["failure_category"], "path_missing_or_unreadable")
            self.assertNotIn("/", json.dumps(payload))

    def test_allowlists_cover_every_label_the_adapter_can_emit(self):
        support = bm023a_adapter_support
        template = (Path(__file__).parents[1] / "tools/bm023a_adapter/default.py.in")
        sources = {
            "support": Path(support.__file__).read_text(encoding="utf-8"),
            "entrypoint": template.read_text(encoding="utf-8"),
        }
        import re

        categories = set()
        stages = set()
        callables = set()
        for text in sources.values():
            for match in re.finditer(
                r"(?:_bootstrap_error|AdapterBootstrapError)\(\s*"
                r'("?[A-Za-z_"]+"?),\s*("?[A-Za-z_.\"]+"?),\s*"([a-z_]+)"',
                text,
            ):
                first, second, category = match.groups()
                categories.add(category)
                if first.startswith('"'):
                    stages.add(first.strip('"'))
                if second.startswith('"'):
                    callables.add(second.strip('"'))
            for match in re.finditer(r'\bcategory = "([a-z_]+)"', text):
                categories.add(match.group(1))
            for match in re.finditer(r'STAGE = "([A-Z_]+)"', text):
                stages.add(match.group(1))
            for match in re.finditer(r'FAILING_CALLABLE = "([A-Za-z_.]+)"', text):
                callables.add(match.group(1))
        self.assertTrue({"retained_manifest_missing", "retained_manifest_unreadable",
                         "retained_artifacts_missing"} <= categories)
        self.assertLessEqual(categories, support.FAILURE_CATEGORIES)
        self.assertLessEqual(stages, support.ADAPTER_STAGES)
        self.assertLessEqual(callables, support.ADAPTER_CALLABLES)
        self.assertTrue({"FileNotFoundError", "PermissionError"} <= support.SAFE_ERROR_TYPES)
        self.assertIn("LOAD_FROZEN_MANIFEST", support.ADAPTER_STAGES)
        for name in ("inspect_retained_inputs", "require_retained_inputs"):
            self.assertIn(name, sources["entrypoint"])


class TestBm023aGeneratedEntrypointDispatch(unittest.TestCase):
    def test_generated_entrypoint_dispatches_modes_and_initializes_legacy_retry_store(self):
        import importlib
        import importlib.machinery
        import importlib.util
        import runpy
        from unittest.mock import patch

        def execute(
            mode,
            *,
            create_retained_source=True,
            create_durable_root=True,
            precreate_durable_artifacts=True,
            retry_api_available=True,
            preload_frozen_install=False,
            frozen_install_source_matches=True,
            create_manifest=True,
            manifest_unreadable=False,
            artifact_entries=1,
            recovery_changes=None,
        ):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                profile_root = (
                    root / "Kodi Build Manager Test.app" / "Contents" / "Resources"
                    / "Kodi" / "portable_data" / "userdata"
                )
                addons_root = profile_root.parent / "addons"
                addon_root = addons_root / "script.build.manager"
                lib_root = addon_root / "resources" / "lib"
                lib_root.mkdir(parents=True)
                lib_init = lib_root / "__init__.py"
                lib_init.write_text("# fixture package\n", encoding="utf-8")
                production_source_paths = {}
                reviewed_frozen_install_source = (
                    Path(__file__).parents[1] / "resources/lib/frozen_install.py"
                )
                for module_name in (
                    "resources.lib.artifacts",
                    "resources.lib.frozen_install",
                    "resources.lib.restart_coordinator",
                    "resources.lib.update_guard",
                    "resources.lib.build_manager",
                    "resources.lib.frozen",
                    "resources.lib.private_overlay",
                ):
                    module_source = lib_root / f"{module_name.rsplit('.', 1)[1]}.py"
                    if module_name == "resources.lib.frozen_install":
                        module_source.write_bytes(
                            reviewed_frozen_install_source.read_bytes()
                            if frozen_install_source_matches
                            else b"# on-disk source without the reviewed API\n"
                        )
                    else:
                        module_source.write_text("# fixture production source\n", encoding="utf-8")
                    production_source_paths[module_name] = module_source
                profile_root.mkdir(parents=True)
                addons_root.mkdir(parents=True, exist_ok=True)

                manifest_path = root / "reviewed-manifest.json"
                if create_manifest:
                    manifest_path.write_text("{}", encoding="utf-8")
                    if manifest_unreadable:
                        manifest_path.chmod(0)
                        if os.access(manifest_path, os.R_OK):
                            self.skipTest("file permissions are not enforced")
                configuration_path = root / "reviewed-configuration.json"
                configuration_path.write_text("{}", encoding="utf-8")
                overlay_path = root / "reviewed-overlay.json"
                overlay_path.write_text("{}", encoding="utf-8")
                artifact_root = root / "retained-artifacts"
                if create_retained_source:
                    (artifact_root / "artifacts").mkdir(parents=True)
                    for index in range(artifact_entries):
                        (artifact_root / "artifacts" / f"entry-{index}").write_bytes(b"x")
                durable_root = root / "profile-frozen"
                durable_artifacts_dir = (
                    durable_root / "frozen-artifacts" / "artifacts"
                )
                if create_durable_root:
                    durable_root.mkdir(parents=True)
                    if precreate_durable_artifacts:
                        durable_artifacts_dir.mkdir(parents=True)

                values = {
                    "MANIFEST_PATH": str(manifest_path),
                    "ARTIFACT_ROOT": str(artifact_root),
                    "CONFIGURATION_PATH": str(configuration_path),
                    "OVERLAY_SOURCE": str(overlay_path),
                    "DEVICE_PROFILE_ID": "reviewed-profile",
                    "EXPECTED_OVERLAY_ID": "reviewed-overlay",
                }
                archive = build_adapter(root / "generated", values)
                generated_root = archive.parent / "script.build.manager.bm023a_driver"
                entrypoint = generated_root / "default.py"

                class Policy(IntEnum):
                    AUTOMATIC = 0

                class Phase:
                    NEEDS_ATTENTION = object()

                class Lifecycle:
                    QUIESCENCE_AWAITING_RESTART = object()

                manifest = SimpleNamespace(
                    build_id="reviewed-build",
                    addons=(),
                    fingerprint=lambda: "a" * 64,
                )
                transaction = SimpleNamespace(
                    transaction_id="3f920c0f-dc69-4684-914b-1bb370a17ba0",
                    build_id=manifest.build_id,
                    manifest_path=str(manifest_path),
                    device_profile_id=values["DEVICE_PROFILE_ID"],
                    manifest_fingerprint=manifest.fingerprint(),
                    phase=Phase.NEEDS_ATTENTION,
                    status_code="FROZEN_MANIFEST_INVALID",
                    lifecycle_stage=Lifecycle.QUIESCENCE_AWAITING_RESTART,
                    lifecycle_restart_count=1,
                    activation_hold_ids=("plugin.video.redlight",),
                    activation_hold_released=False,
                    updater_guard_required=True,
                    original_update_policy=Policy.AUTOMATIC,
                    install_plan_fingerprint="b" * 64,
                    resolution_fingerprint="c" * 64,
                    configuration_manifest_path=str(configuration_path),
                    private_overlay_id=values["EXPECTED_OVERLAY_ID"],
                    private_overlay_fingerprint="sha256:" + "d" * 64,
                    private_overlay_required=True,
                )
                real_recovery = mode == "recover" and recovery_changes is not None
                recovery_transaction = SimpleNamespace(**{
                    **vars(transaction),
                    "phase": Phase.NEEDS_ATTENTION,
                    "activation_hold_ids": (),
                    "activation_hold_released": True,
                    "resolution_records": (),
                    **(recovery_changes or {}),
                })
                dispatch = {"recover": [], "retry": [], "install": []}
                if real_recovery:
                    dispatch["abandon"] = []
                coordinator_calls = []
                restart_store_instances = []
                restart_coordinator_instances = []
                reconcile_calls = []
                callback_invocations = []
                manager = object()

                class FakeFrozenStore:
                    def __init__(self, root=None):
                        self.root = Path(root) if root is not None else durable_root
                        self.current = (
                            transaction if mode == "retry"
                            else recovery_transaction
                            if real_recovery and "__absent__" not in recovery_changes
                            else None
                        )

                    def inspect(self):
                        return self.current

                class FakeInstaller:
                    install_order = []

                    def get_addon_details(self, addon_id):
                        return None

                class FakeCoordinator:
                    def __init__(self, **kwargs):
                        self.kwargs = kwargs
                        self.installer = kwargs["installer"]
                        self.configuration_runner = kwargs.get("configuration_runner")
                        coordinator_calls.append(self)

                    def install(self, *args, **kwargs):
                        dispatch["install"].append((args, kwargs))
                        return SimpleNamespace(outcome="complete", code="ok")

                    def abandon(self, *, acknowledge_restore_failure=True):
                        dispatch["abandon"].append(acknowledge_restore_failure)
                        return SimpleNamespace(outcome="complete")

                    def retry_held_quiescence(self, **kwargs):
                        dispatch["retry"].append(kwargs)
                        request = object()
                        transaction_access = object()
                        callback_result = self.configuration_runner(
                            request, transaction_access=transaction_access
                        )
                        callback_invocations.append(
                            (request, transaction_access, callback_result)
                        )
                        return SimpleNamespace(
                            outcome="complete",
                            transaction=SimpleNamespace(
                                phase="complete",
                                lifecycle_stage="activation_released",
                                lifecycle_restart_count=1,
                                activation_hold_ids=("plugin.video.redlight",),
                                activation_hold_released=True,
                                updater_guard_required=False,
                            ),
                        )

                if not retry_api_available:
                    del FakeCoordinator.retry_held_quiescence

                class FakeTransactionStore:
                    def __init__(self):
                        self.transaction_path = root / "restart-transaction.json"
                        restart_store_instances.append(self)

                class FakeRestartCoordinator:
                    def __init__(self, actual_manager, *, store=None):
                        self.manager = actual_manager
                        self.store = store
                        restart_coordinator_instances.append(self)

                    def reconcile(self, request, *, transaction_access=None):
                        reconcile_calls.append(
                            (self.manager, self.store, request, transaction_access)
                        )
                        return "reconciled"

                class FakeUpdatePolicyBackend:
                    def __init__(self, rpc):
                        self.rpc = rpc

                    def get_policy(self):
                        return int(Policy.AUTOMATIC)

                class FakePrivateOverlayStore:
                    def import_file(self, path):
                        return SimpleNamespace(overlay_id=values["EXPECTED_OVERLAY_ID"])

                def bind_production_source(module):
                    source_path = production_source_paths[module.__name__]
                    module.__file__ = str(source_path)
                    module.__spec__ = importlib.machinery.ModuleSpec(
                        module.__name__, loader=None, origin=str(source_path)
                    )
                    return module

                frozen_install_module = bind_production_source(
                    ModuleType("resources.lib.frozen_install")
                )
                frozen_install_module.default_frozen_install_root = lambda: durable_root
                frozen_install_module.FrozenInstallStore = FakeFrozenStore
                frozen_install_module.FrozenInstallCoordinator = FakeCoordinator
                frozen_install_module.FrozenInstallTransaction = type(transaction)
                frozen_install_module.FrozenInstallPhase = Phase
                frozen_install_module.FrozenLifecycleStage = Lifecycle
                frozen_install_module.KodiRuntimeFrozenArtifactBackend = FakeInstaller

                artifacts_module = bind_production_source(
                    ModuleType("resources.lib.artifacts")
                )
                artifacts_module.ArtifactStore = ArtifactStore
                restart_module = bind_production_source(
                    ModuleType("resources.lib.restart_coordinator")
                )
                restart_module.TransactionStore = FakeTransactionStore
                restart_module.RestartCoordinator = FakeRestartCoordinator
                update_guard_module = bind_production_source(
                    ModuleType("resources.lib.update_guard")
                )
                update_guard_module.KodiJsonRpcUpdatePolicyBackend = FakeUpdatePolicyBackend
                update_guard_module.AddonUpdatePolicy = Policy
                build_manager_module = bind_production_source(
                    ModuleType("resources.lib.build_manager")
                )
                build_manager_module.BuildManager = lambda: manager
                frozen_module = bind_production_source(
                    ModuleType("resources.lib.frozen")
                )
                frozen_module.FrozenBuildManifest = SimpleNamespace(
                    from_json=lambda _text: manifest
                )
                private_overlay_module = bind_production_source(
                    ModuleType("resources.lib.private_overlay")
                )
                private_overlay_module.PrivateOverlayStore = FakePrivateOverlayStore

                resources_lib_module = ModuleType("resources.lib")
                resources_lib_module.__file__ = str(lib_init)
                resources_lib_module.__path__ = [str(lib_root)]

                xbmc_module = ModuleType("xbmc")
                xbmc_module.executeJSONRPC = lambda _request: json.dumps(
                    {"result": {"value": int(Policy.AUTOMATIC)}}
                )
                xbmcvfs_module = ModuleType("xbmcvfs")
                translated_paths = {
                    "special://profile/": profile_root,
                    "special://home/addons": addons_root,
                    "special://home/addons/script.build.manager": addon_root,
                }
                xbmcvfs_module.translatePath = lambda path: str(translated_paths[path])

                adapter_config_module = ModuleType("adapter_config")
                for key, value in values.items():
                    setattr(adapter_config_module, key, value)
                adapter_config_module.EXPECTED_FROZEN_INSTALL_SHA256 = hashlib.sha256(
                    reviewed_frozen_install_source.read_bytes()
                ).hexdigest()

                support_spec = importlib.util.spec_from_file_location(
                    "adapter_support", generated_root / "adapter_support.py"
                )
                support_module = importlib.util.module_from_spec(support_spec)
                support_spec.loader.exec_module(support_module)
                actual_retry_helper = support_module.retry_held_frozen_install
                actual_recovery_helper = support_module.recover_frozen_install

                def tracked_recovery(*args, **kwargs):
                    dispatch["recover"].append((args, kwargs))
                    if real_recovery:
                        store = args[1]
                        original_inspect = store.inspect

                        def cleared_after_abandon():
                            return None if dispatch["abandon"] else original_inspect()

                        store.inspect = cleared_after_abandon
                        return actual_recovery_helper(*args, **kwargs)
                    return {"ok": True}

                def tracked_retry(*args, **kwargs):
                    dispatch["retry"].append("adapter helper")
                    return actual_retry_helper(*args, **kwargs)

                support_module.recover_frozen_install = tracked_recovery
                support_module.retry_held_frozen_install = tracked_retry

                stub_modules = {
                    "xbmc": xbmc_module,
                    "xbmcvfs": xbmcvfs_module,
                    "adapter_config": adapter_config_module,
                    "adapter_support": support_module,
                }
                production_modules = {
                    "resources.lib": resources_lib_module,
                    "resources.lib.artifacts": artifacts_module,
                    "resources.lib.frozen_install": frozen_install_module,
                    "resources.lib.restart_coordinator": restart_module,
                    "resources.lib.update_guard": update_guard_module,
                    "resources.lib.build_manager": build_manager_module,
                    "resources.lib.frozen": frozen_module,
                    "resources.lib.private_overlay": private_overlay_module,
                }
                cached_module_names = (
                    "resources",
                    *production_modules.keys(),
                )
                saved_modules = {
                    name: sys.modules.pop(name)
                    for name in cached_module_names
                    if name in sys.modules
                }
                if preload_frozen_install:
                    sys.modules["resources.lib.frozen_install"] = frozen_install_module

                original_import_module = importlib.import_module

                def import_production_module(name, package=None):
                    if name in production_modules:
                        return production_modules[name]
                    return original_import_module(name, package)

                saved_path = list(sys.path)
                saved_argv = sys.argv
                try:
                    sys.path.insert(0, str(generated_root))
                    sys.argv = [str(entrypoint), mode]
                    with patch.dict(sys.modules, stub_modules):
                        with patch.object(
                            importlib, "import_module", import_production_module
                        ):
                            runpy.run_path(str(entrypoint), run_name="__main__")
                finally:
                    sys.path[:] = saved_path
                    sys.argv = saved_argv
                    for name in cached_module_names:
                        sys.modules.pop(name, None)
                    sys.modules.update(saved_modules)

                result_path = (
                    profile_root / "addon_data" / "script.build.manager"
                    / "bm023a_live_result.json"
                )
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                return (
                    payload,
                    dispatch,
                    coordinator_calls,
                    restart_store_instances,
                    restart_coordinator_instances,
                    reconcile_calls,
                    callback_invocations,
                    transaction,
                    manager,
                    durable_artifacts_dir.is_dir(),
                )

        for mode in ("install", "recover", "retry"):
            with self.subTest(mode=mode):
                (
                    payload,
                    dispatch,
                    coordinator_calls,
                    restart_store_instances,
                    restart_coordinator_instances,
                    reconcile_calls,
                    callback_invocations,
                    transaction,
                    manager,
                    durable_artifacts_initialized,
                ) = execute(
                    mode,
                    precreate_durable_artifacts=(mode != "retry"),
                )
                self.assertEqual(payload["adapter_mode"], mode)
                self.assertTrue(payload["ok"])
                if mode == "install":
                    self.assertEqual(len(dispatch["install"]), 1)
                    self.assertEqual(dispatch["recover"], [])
                    self.assertEqual(dispatch["retry"], [])
                    self.assertEqual(len(coordinator_calls), 1)
                elif mode == "recover":
                    self.assertEqual(len(dispatch["recover"]), 1)
                    self.assertEqual(dispatch["install"], [])
                    self.assertEqual(dispatch["retry"], [])
                    self.assertEqual(len(coordinator_calls), 1)
                else:
                    self.assertTrue(durable_artifacts_initialized)
                    self.assertEqual(dispatch["install"], [])
                    self.assertEqual(
                        [call for call in dispatch["retry"] if call == "adapter helper"],
                        ["adapter helper"],
                    )
                    retry_calls = [
                        call for call in dispatch["retry"] if isinstance(call, dict)
                    ]
                    self.assertEqual(len(retry_calls), 1)
                    self.assertEqual(dispatch["recover"], [])
                    self.assertIs(retry_calls[0]["expected_transaction"], transaction)
                    self.assertEqual(len(coordinator_calls), 1)
                    self.assertEqual(len(restart_store_instances), 1)
                    self.assertEqual(len(restart_coordinator_instances), 1)
                    self.assertIs(restart_coordinator_instances[0].manager, manager)
                    self.assertIs(
                        restart_coordinator_instances[0].store,
                        retry_calls[0]["restart_store"],
                    )
                    self.assertEqual(len(reconcile_calls), 1)
                    self.assertEqual(len(callback_invocations), 1)
                    request, transaction_access, callback_result = callback_invocations[0]
                    self.assertIs(reconcile_calls[0][2], request)
                    self.assertIs(reconcile_calls[0][3], transaction_access)
                    self.assertEqual(callback_result, "reconciled")

        with self.subTest(missing="durable root"):
            payload = execute(
                "retry",
                create_durable_root=False,
                precreate_durable_artifacts=False,
            )
            payload = payload[0]
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["adapter_stage"], "CHECK_RETRY_PRECONDITIONS")
            self.assertEqual(payload["failure_category"], "path_missing_or_unreadable")

        with self.subTest(missing="retained source store"):
            result = execute(
                "retry",
                create_retained_source=False,
                precreate_durable_artifacts=False,
            )
            payload, durable_artifacts_initialized = result[0], result[-1]
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["adapter_stage"], "LOAD_FROZEN_MANIFEST")
            self.assertEqual(payload["failure_category"], "retained_artifacts_missing")
            self.assertFalse(durable_artifacts_initialized)

        with self.subTest(missing="retry coordinator API"):
            result = execute("retry", retry_api_available=False)
            payload, dispatch, coordinator_calls = result[:3]
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["adapter_mode"], "retry")
            self.assertEqual(payload["adapter_stage"], "INVOKE_RETRY")
            self.assertEqual(
                payload["failing_callable"],
                "FrozenInstallCoordinator.retry_held_quiescence",
            )
            self.assertEqual(payload["failure_category"], "retry_api_unavailable")
            self.assertEqual(dispatch["retry"], ["adapter helper"])
            self.assertEqual(len(coordinator_calls), 1)
            self.assertEqual(dispatch["install"], [])
            self.assertEqual(dispatch["recover"], [])

        with self.subTest(stale="preloaded frozen_install module"):
            result = execute("retry", preload_frozen_install=True)
            payload, dispatch, coordinator_calls = result[:3]
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["adapter_mode"], "retry")
            self.assertEqual(payload["adapter_stage"], "IMPORT_PRODUCTION_MODULES")
            self.assertEqual(
                payload["failing_callable"], "importlib.import_module"
            )
            self.assertEqual(payload["failure_category"], "module_cache_preloaded")
            self.assertEqual(dispatch, {"recover": [], "retry": [], "install": []})
            self.assertEqual(coordinator_calls, [])

        with self.subTest(mismatch="frozen_install source is repaired from bundle"):
            result = execute("retry", frozen_install_source_matches=False)
            payload = result[0]
            reviewed_digest = hashlib.sha256(
                (
                    Path(__file__).parents[1] / "resources/lib/frozen_install.py"
                ).read_bytes()
            ).hexdigest()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["adapter_mode"], "retry")
            self.assertEqual(
                payload["frozen_install_source"],
                {
                    "sha256_before": hashlib.sha256(
                        b"# on-disk source without the reviewed API\n"
                    ).hexdigest(),
                    "sha256_after": reviewed_digest,
                    "replaced": True,
                },
            )

        with self.subTest(match="frozen_install source is left untouched"):
            payload = execute("retry")[0]
            record = payload["frozen_install_source"]
            self.assertFalse(record["replaced"])
            self.assertEqual(record["sha256_before"], record["sha256_after"])

        expected_records = {
            "manifest_missing": (
                {"create_manifest": False},
                "retained_manifest_missing",
                {
                    "manifest_present": False, "manifest_readable": False,
                    "artifact_store_present": True, "artifact_store_readable": True,
                    "artifact_entry_count": 1,
                },
            ),
            "manifest_unreadable": (
                {"manifest_unreadable": True},
                "retained_manifest_unreadable",
                {
                    "manifest_present": True, "manifest_readable": False,
                    "artifact_store_present": True, "artifact_store_readable": True,
                    "artifact_entry_count": 1,
                },
            ),
            "artifact_store_empty": (
                {"artifact_entries": 0},
                "retained_artifacts_missing",
                {
                    "manifest_present": True, "manifest_readable": True,
                    "artifact_store_present": True, "artifact_store_readable": True,
                    "artifact_entry_count": 0,
                },
            ),
            "artifact_store_absent": (
                {"create_retained_source": False},
                "retained_artifacts_missing",
                {
                    "manifest_present": True, "manifest_readable": True,
                    "artifact_store_present": False, "artifact_store_readable": False,
                    "artifact_entry_count": 0,
                },
            ),
        }
        for mode in ("retry", "install"):
            for name, (options, category, record) in expected_records.items():
                with self.subTest(mode=mode, retained=name):
                    result = execute(
                        mode, precreate_durable_artifacts=(mode != "retry"), **options
                    )
                    payload, dispatch, coordinator_calls = result[:3]
                    self.assertFalse(payload["ok"])
                    self.assertEqual(payload["adapter_mode"], mode)
                    self.assertEqual(payload["adapter_stage"], "LOAD_FROZEN_MANIFEST")
                    self.assertEqual(payload["failing_callable"], "pathlib.Path")
                    self.assertEqual(payload["failure_category"], category)
                    self.assertEqual(payload["error_type"], "Exception")
                    self.assertEqual(payload["retained_inputs"], record)
                    self.assertEqual(dispatch, {"recover": [], "retry": [], "install": []})
                    self.assertEqual(coordinator_calls, [])
                    serialized = json.dumps(payload)
                    self.assertNotIn("/", serialized)
                    self.assertNotIn("reviewed-manifest", serialized)

        for mode in ("retry", "install"):
            with self.subTest(mode=mode, retained="present"):
                payload = execute(mode, precreate_durable_artifacts=(mode != "retry"))[0]
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["adapter_mode"], mode)
                self.assertEqual(
                    payload["retained_inputs"],
                    {
                        "manifest_present": True, "manifest_readable": True,
                        "artifact_store_present": True, "artifact_store_readable": True,
                        "artifact_entry_count": 1,
                    },
                )
                self.assertNotIn("failure_category", payload)

        for name, options, category in (
            ("manifest_missing", {"create_manifest": False}, "retained_manifest_missing"),
            ("manifest_unreadable", {"manifest_unreadable": True}, "retained_manifest_unreadable"),
        ):
            with self.subTest(mode="recover", retained=name):
                result = execute("recover", recovery_changes={}, **options)
                payload, dispatch = result[0], result[1]
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["adapter_mode"], "recover")
                self.assertEqual(payload["adapter_stage"], "LOAD_FROZEN_MANIFEST")
                self.assertEqual(payload["failure_category"], category)
                self.assertEqual(dispatch["recover"], [])
                self.assertEqual(dispatch["abandon"], [])

        with self.subTest(mode="recover", retained="empty artifact store is not required"):
            payload = execute("recover", recovery_changes={}, artifact_entries=0)[0]
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["retained_inputs"]["manifest_readable"])

        with self.subTest(mode="recover", identity="exact intended identity"):
            result = execute("recover", recovery_changes={})
            payload, dispatch = result[0], result[1]
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(payload["adapter_mode"], "recover")
            self.assertEqual(len(dispatch["recover"]), 1)
            self.assertEqual(dispatch["abandon"], [False])
            self.assertEqual(result[2][0].kwargs["installer"].install_order, [])

        wrong_identities = {
            "transaction_id_and_build": {
                "transaction_id": "9b0f4a86-2f3c-4d2e-8a55-0c5f6d1e7a10",
                "build_id": "other-build",
            },
            "manifest_fingerprint": {"manifest_fingerprint": "e" * 64},
            "manifest_path": {"manifest_path": "/other/manifest.json"},
            "configuration_manifest_path": {"configuration_manifest_path": "/other/config.json"},
            "device_profile_id": {"device_profile_id": "other-profile"},
            "private_overlay_id": {"private_overlay_id": "other-overlay"},
        }
        for name, changes in wrong_identities.items():
            with self.subTest(mode="recover", identity=name):
                result = execute("recover", recovery_changes=changes)
                payload, dispatch = result[0], result[1]
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["adapter_mode"], "recover")
                self.assertEqual(payload["adapter_stage"], "CHECK_RECOVERY_PRECONDITIONS")
                self.assertEqual(payload["failing_callable"], "FrozenInstallStore.inspect")
                self.assertEqual(payload["failure_category"], "recovery_identity_mismatch")
                self.assertEqual(len(dispatch["recover"]), 1)
                self.assertEqual(dispatch["abandon"], [])
                serialized = json.dumps(payload)
                self.assertNotIn("/", serialized)
                self.assertNotIn("other-", serialized)
                self.assertNotIn("9b0f4a86", serialized)

        for name, changes, category in (
            ("malformed uuid", {"transaction_id": "not-a-uuid"}, "transaction_identity_invalid"),
            ("wrong phase", {"phase": "complete"}, "recovery_phase_mismatch"),
        ):
            with self.subTest(mode="recover", identity=name):
                result = execute("recover", recovery_changes=changes)
                payload, dispatch = result[0], result[1]
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["failure_category"], category)
                self.assertEqual(dispatch["abandon"], [])

        with self.subTest(mode="recover", identity="absent transaction"):
            result = execute("recover", recovery_changes={"__absent__": True})
            payload, dispatch = result[0], result[1]
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["failure_category"], "transaction_missing")
            self.assertEqual(dispatch["abandon"], [])


class TestBm023aRetainedArtifactStaging(unittest.TestCase):
    @staticmethod
    def addon_zip(addon_id="plugin.example", version="1.2.3"):
        import io

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(
                f"{addon_id}/addon.xml",
                f'<addon id="{addon_id}" version="{version}" />',
            )
            archive.writestr(f"{addon_id}/default.py", "# fixture\n")
        return stream.getvalue()

    @staticmethod
    def node(addon_id, version, artifact, *, system=False):
        return SimpleNamespace(
            addon_id=addon_id,
            version=version,
            artifact=artifact,
            system=system,
        )

    def test_exact_retained_artifact_is_staged_with_its_identity(self):
        zip_bytes = self.addon_zip()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_store = ArtifactStore(root / "retained")
            retained = source_store.import_zip(
                zip_bytes,
                expected_addon_id="plugin.example",
                expected_version="1.2.3",
                source="fixture-retained",
            )
            durable_root = root / "profile-local" / "frozen-artifacts"
            durable_store = ArtifactStore(durable_root)
            manifest = SimpleNamespace(addons=(
                self.node("plugin.example", "1.2.3", retained),
            ))

            stage_manifest_artifacts(manifest, source_store, durable_store)

            staged = durable_store.get_metadata(retained.sha256)
            self.assertEqual(staged.sha256, retained.sha256)
            self.assertEqual(staged.size, retained.size)
            self.assertEqual(staged.addon_id, "plugin.example")
            self.assertEqual(staged.version, "1.2.3")
            self.assertEqual(staged.source, "bm023a-retained-artifact")
            self.assertEqual(durable_store.read_bytes(retained.sha256), zip_bytes)

    def test_artifactless_and_system_nodes_are_not_staged_and_resolution_is_preserved(self):
        class TrackingSourceStore:
            read_calls = []

            def read_bytes(self, sha256):
                self.read_calls.append(sha256)
                raise AssertionError("artifactless node must not be read")

        class TrackingDurableStore:
            import_calls = []

            def import_zip(self, *args, **kwargs):
                self.import_calls.append((args, kwargs))
                raise AssertionError("artifactless node must not be imported")

        source_store = TrackingSourceStore()
        durable_store = TrackingDurableStore()
        system_artifact = SimpleNamespace(sha256="a" * 64, size=1)
        manifest = SimpleNamespace(addons=(
            self.node("plugin.video.youtube", "7.4.4+unofficial.2", None),
            self.node("script.module.optional", "1.0.0", None),
            self.node("xbmc.python", "3.0.0", system_artifact, system=True),
        ))

        stage_manifest_artifacts(manifest, source_store, durable_store)

        self.assertEqual(source_store.read_calls, [])
        self.assertEqual(durable_store.import_calls, [])
        choices = SimpleNamespace(SKIP="skip", CANCEL="cancel")
        self.assertEqual(
            choose_missing_artifact_resolution(
                SimpleNamespace(addon_id="plugin.video.youtube", skip_allowed=True),
                choices,
            ),
            "skip",
        )
        self.assertEqual(
            choose_missing_artifact_resolution(
                SimpleNamespace(addon_id="plugin.video.youtube", skip_allowed=False),
                choices,
            ),
            "cancel",
        )
        self.assertEqual(
            choose_missing_artifact_resolution(
                SimpleNamespace(
                    addon_id="plugin.repository.example",
                    skip_allowed=False,
                    repository_id="repository.example",
                ),
                choices,
            ),
            "cancel",
        )

    def test_missing_corrupt_and_mismatched_artifacts_fail_with_safe_diagnostics(self):
        zip_bytes = self.addon_zip()
        digest = hashlib.sha256(zip_bytes).hexdigest()
        cases = ("missing", "corrupt", "mismatch")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source_store = ArtifactStore(root / "retained")
                durable_store = ArtifactStore(root / "profile-local" / "frozen-artifacts")
                retained = SimpleNamespace(sha256=digest, size=len(zip_bytes))
                if case == "corrupt":
                    corrupt_path = source_store.artifact_path(digest)
                    corrupt_path.write_bytes(b"corrupt retained ZIP bytes")
                elif case == "mismatch":
                    source_store.import_zip(
                        zip_bytes,
                        expected_addon_id="plugin.example",
                        expected_version="1.2.3",
                    )

                    class MismatchedStore:
                        def import_zip(self, *args, **kwargs):
                            return SimpleNamespace(sha256="0" * 64, size=len(zip_bytes) + 1)

                    durable_store = MismatchedStore()

                manifest = SimpleNamespace(addons=(
                    self.node("plugin.example", "1.2.3", retained),
                ))
                with self.assertRaises(AdapterBootstrapError) as raised:
                    stage_manifest_artifacts(manifest, source_store, durable_store)

                payload = safe_failure_payload(
                    "STAGE_RETAINED_ARTIFACTS",
                    "ArtifactStore.read_bytes",
                    raised.exception,
                )
                serialized = json.dumps(payload)
                self.assertEqual(payload["adapter_stage"], "STAGE_RETAINED_ARTIFACTS")
                self.assertEqual(payload["failure_category"], "artifact_stage_failed")
                self.assertNotIn(str(root), serialized)
                self.assertNotIn("corrupt retained ZIP bytes", serialized)
                self.assertEqual(set(payload), {
                    "ok", "error_type", "adapter_stage", "failing_callable",
                    "failure_category",
                })

    def test_install_coordinator_receives_profile_local_durable_store(self):
        template = Path(__file__).parents[1] / "tools/bm023a_adapter/default.py.in"
        tree = ast.parse(template.read_text(encoding="utf-8"))
        coordinator_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "FrozenInstallCoordinator"
        ]
        install_call = next(
            call for call in coordinator_calls
            if any(keyword.arg == "configuration_runner" for keyword in call.keywords)
        )
        artifact_store = next(
            keyword.value for keyword in install_call.keywords
            if keyword.arg == "artifact_store"
        )
        self.assertIsInstance(artifact_store, ast.Name)
        self.assertEqual(artifact_store.id, "durable_store")

        durable_root_assignment = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "durable_root" for target in node.targets)
        )
        self.assertIsInstance(durable_root_assignment.value, ast.Call)
        self.assertIsInstance(durable_root_assignment.value.func, ast.Attribute)
        self.assertEqual(durable_root_assignment.value.func.attr, "default_frozen_install_root")

        durable_store_assignment = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "durable_store" for target in node.targets)
        )
        self.assertIsInstance(durable_store_assignment.value, ast.Call)
        self.assertEqual(durable_store_assignment.value.func.attr, "ArtifactStore")
        durable_path = durable_store_assignment.value.args[0]
        self.assertIsInstance(durable_path, ast.BinOp)
        self.assertIsInstance(durable_path.left, ast.Name)
        self.assertEqual(durable_path.left.id, "durable_root")
        self.assertEqual(durable_path.right.value, "frozen-artifacts")

        recovery_call = next(call for call in coordinator_calls if call is not install_call)
        recovery_artifact_store = next(
            keyword.value for keyword in recovery_call.keywords
            if keyword.arg == "artifact_store"
        )
        self.assertIsInstance(recovery_artifact_store, ast.Call)
        self.assertEqual(recovery_artifact_store.func.attr, "ArtifactStore")


class TestBm023aRecoveryAdapter(unittest.TestCase):
    class Policy(IntEnum):
        ORIGINAL = 1
        GUARDED = 2

    class Phase:
        NEEDS_ATTENTION = "needs_attention"

    IDENTITY = {
        "build_id": "reviewed-build",
        "manifest_path": "/reviewed/manifest.json",
        "manifest_fingerprint": "a" * 64,
        "configuration_manifest_path": "/reviewed/configuration.json",
        "device_profile_id": "reviewed-profile",
        "private_overlay_id": "reviewed-overlay",
    }

    def fixture(self, root: Path, *, phase="needs_attention", transaction_id=None):
        root.mkdir(parents=True, exist_ok=True)
        transaction = SimpleNamespace(
            transaction_id=transaction_id or "3f920c0f-dc69-4684-914b-1bb370a17ba0",
            phase=phase,
            original_update_policy=self.Policy.ORIGINAL,
            activation_hold_ids=(),
            activation_hold_released=True,
            resolution_records=(SimpleNamespace(addon_id="plugin.example"),),
            build_id=self.IDENTITY["build_id"],
            manifest_path=self.IDENTITY["manifest_path"],
            manifest_fingerprint=self.IDENTITY["manifest_fingerprint"],
            configuration_manifest_path=self.IDENTITY["configuration_manifest_path"],
            device_profile_id=self.IDENTITY["device_profile_id"],
            private_overlay_id=self.IDENTITY["private_overlay_id"],
        )
        store = SimpleNamespace(root=root, current=transaction)
        store.inspect = lambda: store.current
        policy = SimpleNamespace(current=self.Policy.GUARDED)
        policy.get_policy = lambda: policy.current
        installer = SimpleNamespace(present={"plugin.example", "skin.arctic.fuse.3"})
        installer.get_addon_details = lambda addon_id: (
            object() if addon_id in installer.present else None
        )
        calls = []

        def abandon(*, acknowledge_restore_failure=True):
            calls.append(acknowledge_restore_failure)
            policy.current = transaction.original_update_policy
            store.current = None
            return SimpleNamespace(outcome="complete")

        coordinator = SimpleNamespace(abandon=abandon)
        restart_path = root / "restart_transaction.json"
        restart_path.write_text("retained", encoding="utf-8")
        return store, policy, installer, coordinator, restart_path, calls

    def run_recovery(self, fixture):
        return recover_frozen_install(
            fixture[3], fixture[0], fixture[1], fixture[2], fixture[4],
            manifest=SimpleNamespace(
                build_id=self.IDENTITY["build_id"],
                fingerprint=lambda: self.IDENTITY["manifest_fingerprint"],
            ),
            manifest_path=self.IDENTITY["manifest_path"],
            configuration_manifest_path=self.IDENTITY["configuration_manifest_path"],
            device_profile_id=self.IDENTITY["device_profile_id"],
            expected_overlay_id=self.IDENTITY["private_overlay_id"],
            needs_attention_phase=self.Phase.NEEDS_ATTENTION,
            update_policy_type=self.Policy,
        )

    def test_previous_jsonrpc_shape_reproduces_old_sysargv_slice_bug_offline(self):
        # The old request supplied params="recover". Kodi exposes the script
        # path as argv[0] and that one add-on argument as argv[1].
        simulated_sys_argv = ["default.py", "recover"]
        self.assertEqual(simulated_sys_argv[2:], [])
        with self.assertRaises(AdapterBootstrapError) as raised:
            parse_adapter_mode(simulated_sys_argv[2:])
        self.assertEqual(raised.exception.failure_category, "mode_missing")
        self.assertEqual(parse_adapter_mode(simulated_sys_argv[1:]), "recover")

    def test_corrected_jsonrpc_argument_shapes_select_recover(self):
        self.assertEqual(parse_adapter_mode(["recover"]), "recover")
        self.assertEqual(parse_adapter_mode(["?mode=recover"]), "recover")

    def test_retry_mode_requires_one_explicit_allowlisted_token(self):
        self.assertEqual(parse_adapter_mode(["retry"]), "retry")
        self.assertEqual(parse_adapter_mode(["?mode=retry"]), "retry")
        for args in ([], ["retry;install"], ["?mode=retry&mode=install"], ["retry", "extra"]):
            with self.subTest(args=args), self.assertRaises(AdapterBootstrapError):
                parse_adapter_mode(list(args))

    def test_install_requires_an_explicit_allowlisted_mode(self):
        self.assertEqual(parse_adapter_mode(["install"]), "install")
        self.assertEqual(parse_adapter_mode(["?mode=install"]), "install")
        for args in ([], [""]):
            with self.subTest(args=args), self.assertRaises(AdapterBootstrapError) as raised:
                parse_adapter_mode(list(args))
            self.assertEqual(raised.exception.failure_category, "mode_missing")

    def test_explicit_recover_selects_only_fixed_recovery_mode(self):
        self.assertEqual(parse_adapter_mode(["recover"]), "recover")
        for args in (["eval:1"], ["recover", "extra"], ["module.method"]):
            with self.subTest(args=args), self.assertRaises(AdapterBootstrapError):
                parse_adapter_mode(list(args))

    def test_unknown_mode_is_rejected_before_mutation(self):
        for args in (["install;recover"], ["?mode=recover&mode=install"], ["recover", "extra"]):
            with self.subTest(args=args), self.assertRaises(AdapterBootstrapError) as raised:
                parse_adapter_mode(list(args))
            self.assertEqual(raised.exception.failure_category, "mode_invalid")

    def test_result_identity_distinguishes_modes_and_preselection_failure(self):
        self.assertEqual(
            identify_adapter_result({"ok": True}, "install"),
            {"ok": True, "adapter_mode": "install"},
        )
        self.assertEqual(
            identify_adapter_result({"ok": True}, "recover"),
            {"ok": True, "adapter_mode": "recover"},
        )
        self.assertEqual(
            identify_adapter_result({"ok": True}, "retry"),
            {"ok": True, "adapter_mode": "retry"},
        )
        failure = identify_adapter_result({"ok": False, "failure_category": "mode_missing"}, "unselected")
        self.assertEqual(failure["adapter_mode"], "unselected")
        self.assertEqual(failure["failure_category"], "mode_missing")

    def test_recovery_calls_abandon_once_with_false_and_reports_safe_postconditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            payload = self.run_recovery(fixture)
            self.assertEqual(fixture[-1], [False])
            self.assertEqual(payload, {
                "ok": True,
                "adapter_mode": "recover",
                "transaction_cleared": True,
                "original_update_policy": 1,
                "update_policy_after": 1,
                "updater_policy_restored": True,
                "restart_transaction_present": True,
                "af3_installed": True,
                "frozen_addons_retained": True,
            })
            self.assertEqual(fixture[4].read_text(encoding="utf-8"), "retained")

    def test_recovery_result_remains_explicitly_tagged_and_install_path_is_not_called(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            # An install callable is deliberately present and must remain unused.
            install_calls = []
            fixture[3].install = lambda *args, **kwargs: install_calls.append(True)
            payload = identify_adapter_result(self.run_recovery(fixture), "recover")
            self.assertEqual(payload["adapter_mode"], "recover")
            self.assertEqual(fixture[-1], [False])
            self.assertEqual(install_calls, [])

    def test_install_result_is_explicitly_tagged(self):
        payload = identify_adapter_result({"ok": True, "outcome": "complete"}, "install")
        self.assertEqual(payload["adapter_mode"], "install")

    def test_recovery_and_install_calls_are_in_disjoint_dispatch_branches(self):
        source = (Path(__file__).parents[1] / "tools/bm023a_adapter/default.py.in").read_text()
        dispatch = source.split('if mode == "recover":', 1)[1]
        recovery_branch, after_recovery = dispatch.split('        elif mode == "retry":', 1)
        retry_branch, install_branch = after_recovery.split("        else:", 1)
        self.assertIn("recover_frozen_install(", recovery_branch)
        self.assertNotIn("coordinator.install(", recovery_branch)
        self.assertIn("retry_held_frozen_install(", retry_branch)
        self.assertIn("source_store", retry_branch)
        self.assertIn("restart_store", retry_branch)
        self.assertNotIn("coordinator.install(", retry_branch)
        self.assertIn("coordinator.install(", install_branch)
        self.assertNotIn("recover_frozen_install(", install_branch)
        self.assertNotIn("retry_held_frozen_install(", install_branch)

    def test_no_transaction_is_rejected_without_abandon(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            fixture[0].current = None
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_recovery(fixture)
            self.assertEqual(raised.exception.failure_category, "transaction_missing")
            self.assertEqual(fixture[-1], [])

    def test_wrong_phase_is_rejected_without_abandon(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store", phase="complete")
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_recovery(fixture)
            self.assertEqual(raised.exception.failure_category, "recovery_phase_mismatch")
            self.assertEqual(fixture[-1], [])

    def test_invalid_transaction_identity_is_rejected_without_abandon(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store", transaction_id="not-a-uuid")
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_recovery(fixture)
            self.assertEqual(raised.exception.failure_category, "transaction_identity_invalid")
            self.assertEqual(fixture[-1], [])

    def test_wrong_but_valid_transaction_identity_is_rejected_without_abandon(self):
        other = {
            "build_id": "other-build",
            "manifest_path": "/other/manifest.json",
            "manifest_fingerprint": "b" * 64,
            "configuration_manifest_path": "/other/configuration.json",
            "device_profile_id": "other-profile",
            "private_overlay_id": "other-overlay",
        }
        cases = {field: {field: value} for field, value in other.items()}
        cases["different valid transaction"] = {
            "transaction_id": "9b0f4a86-2f3c-4d2e-8a55-0c5f6d1e7a10", **other,
        }
        for name, changes in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                fixture = self.fixture(Path(tmp) / "store")
                for field, value in changes.items():
                    setattr(fixture[0].current, field, value)
                with self.assertRaises(AdapterBootstrapError) as raised:
                    self.run_recovery(fixture)
                self.assertEqual(
                    raised.exception.failure_category, "recovery_identity_mismatch"
                )
                self.assertEqual(raised.exception.stage, "CHECK_RECOVERY_PRECONDITIONS")
                self.assertEqual(fixture[-1], [])
                self.assertIsNotNone(fixture[0].current)

    def test_missing_identity_field_is_rejected_without_abandon(self):
        for field in TestBm023aRecoveryAdapter.IDENTITY:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                fixture = self.fixture(Path(tmp) / "store")
                delattr(fixture[0].current, field)
                with self.assertRaises(AdapterBootstrapError) as raised:
                    self.run_recovery(fixture)
                self.assertEqual(
                    raised.exception.failure_category, "recovery_identity_mismatch"
                )
                self.assertEqual(fixture[-1], [])

    def test_identity_mismatch_diagnostic_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            fixture[0].current.manifest_path = "/private/other/manifest.json"
            fixture[0].current.private_overlay_id = "private-overlay-secret"
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_recovery(fixture)
            payload = safe_failure_payload(
                "CHECK_RECOVERY_PRECONDITIONS", "FrozenInstallStore.inspect", raised.exception
            )
            serialized = json.dumps(payload)
            for fragment in ("/private", "manifest.json", "private-overlay-secret",
                             "reviewed-overlay", "reviewed-build", "a" * 16):
                self.assertNotIn(fragment, serialized)
            self.assertEqual(payload["failure_category"], "recovery_identity_mismatch")
            self.assertEqual(set(payload), {
                "ok", "error_type", "adapter_stage", "failing_callable", "failure_category"
            })

    def test_missing_original_policy_is_rejected_without_abandon(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            fixture[0].current.original_update_policy = None
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_recovery(fixture)
            self.assertEqual(raised.exception.failure_category, "original_policy_missing")
            self.assertEqual(fixture[-1], [])

    def test_unreleased_activation_hold_is_rejected_without_abandon(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            fixture[0].current.activation_hold_ids = ("plugin.example",)
            fixture[0].current.activation_hold_released = False
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_recovery(fixture)
            self.assertEqual(raised.exception.failure_category, "unsupported_recovery_state")
            self.assertEqual(fixture[-1], [])

    def test_held_redlight_quiescence_needs_attention_is_rejected_without_abandon(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            held = fixture[0].current
            held.activation_hold_ids = ("plugin.video.redlight",)
            held.activation_hold_released = False
            held.lifecycle_stage = "quiescence_awaiting_restart"
            held.lifecycle_restart_count = 1
            held.updater_guard_required = True
            held.status_message = "PRIVATE_RESULT_DETAIL_DO_NOT_EMIT"
            policy_before = fixture[1].current
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_recovery(fixture)
            self.assertEqual(raised.exception.failure_category, "unsupported_recovery_state")
            self.assertEqual(raised.exception.stage, "CHECK_RECOVERY_PRECONDITIONS")
            self.assertEqual(fixture[-1], [])
            self.assertIs(fixture[0].current, held)
            self.assertEqual(fixture[1].current, policy_before)
            self.assertTrue(fixture[4].exists())
            payload = safe_failure_payload(
                "CHECK_RECOVERY_PRECONDITIONS", "FrozenInstallStore.inspect", raised.exception
            )
            serialized = json.dumps(payload)
            for fragment in ("PRIVATE_RESULT_DETAIL", "redlight", "/reviewed", "reviewed-build"):
                self.assertNotIn(fragment, serialized)
            self.assertEqual(payload["failure_category"], "unsupported_recovery_state")

    def test_missing_store_directory_is_rejected_without_abandon(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            fixture[0].root = Path(tmp) / "missing"
            with self.assertRaises(AdapterBootstrapError):
                self.run_recovery(fixture)
            self.assertEqual(fixture[-1], [])

    def test_recovery_preserves_installed_addons_and_restart_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            before = fixture[4].read_bytes()
            self.run_recovery(fixture)
            self.assertEqual(fixture[2].present, {"plugin.example", "skin.arctic.fuse.3"})
            self.assertEqual(fixture[4].read_bytes(), before)

    def test_abandon_exception_is_sanitized(self):
        secret = "private-token-should-never-escape"
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(Path(tmp) / "store")
            fixture[3].abandon = lambda **kwargs: (_ for _ in ()).throw(RuntimeError(secret))
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_recovery(fixture)
            payload = safe_failure_payload(
                "CHECK_RECOVERY_PRECONDITIONS", "FrozenInstallStore.inspect", raised.exception
            )
            self.assertNotIn(secret, json.dumps(payload))
            self.assertEqual(payload["adapter_stage"], "INVOKE_RECOVERY")
            self.assertEqual(payload["failing_callable"], "FrozenInstallCoordinator.abandon")
            self.assertEqual(set(payload), {
                "ok", "error_type", "adapter_stage", "failing_callable", "failure_category"
            })
            tagged = identify_adapter_result(payload, "unselected")
            self.assertEqual(tagged["adapter_mode"], "unselected")
            self.assertNotIn(secret, json.dumps(tagged))

    def test_adapter_has_no_arbitrary_dispatch_and_keeps_install_branch(self):
        root = Path(__file__).parents[1]
        source = (root / "tools/bm023a_adapter/default.py.in").read_text()
        self.assertIn('if mode == "recover":', source)
        self.assertIn('elif mode == "retry":', source)
        self.assertIn("parse_adapter_mode(sys.argv[1:])", source)
        self.assertIn('coordinator.install(', source)
        self.assertNotIn("eval(", source)
        self.assertNotIn("exec(", source)
        self.assertNotIn("sys.argv[2:]", source)


class TestBm023aHeldRetryAdapter(unittest.TestCase):
    class Policy(IntEnum):
        AUTOMATIC = 0
        NOTIFY_ONLY = 1

    class Phase:
        NEEDS_ATTENTION = object()
        AWAITING_RESTART = object()

    class Lifecycle:
        QUIESCENCE_AWAITING_RESTART = object()
        NONE = object()

    def fixture(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        frozen_root = root / "frozen"
        frozen_root.mkdir()
        manifest_path = root / "reviewed-manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")
        configuration_path = root / "reviewed-configuration.json"
        configuration_path.write_text("{}", encoding="utf-8")
        manifest = SimpleNamespace(
            build_id="bm023a-reviewed-build",
            fingerprint=lambda: "a" * 64,
        )
        transaction = SimpleNamespace(
            transaction_id="3f920c0f-dc69-4684-914b-1bb370a17ba0",
            build_id=manifest.build_id,
            manifest_path=str(manifest_path),
            device_profile_id="reviewed-profile",
            manifest_fingerprint=manifest.fingerprint(),
            phase=self.Phase.NEEDS_ATTENTION,
            status_code="FROZEN_MANIFEST_INVALID",
            lifecycle_stage=self.Lifecycle.QUIESCENCE_AWAITING_RESTART,
            lifecycle_restart_count=1,
            activation_hold_ids=("plugin.video.redlight",),
            activation_hold_released=False,
            updater_guard_required=True,
            original_update_policy=self.Policy.AUTOMATIC,
            install_plan_fingerprint="b" * 64,
            resolution_fingerprint="c" * 64,
            configuration_manifest_path=str(configuration_path),
            private_overlay_id="reviewed-overlay",
            private_overlay_fingerprint="sha256:" + "d" * 64,
            private_overlay_required=True,
            status_message="PRIVATE_FAILURE_DETAIL_DO_NOT_EMIT",
        )
        store = SimpleNamespace(root=frozen_root, current=transaction)
        store.inspect = lambda: store.current
        source_store = object()
        restart_store = object()
        result_transaction = SimpleNamespace(
            phase="needs_attention",
            lifecycle_stage="quiescence_awaiting_restart",
            lifecycle_restart_count=1,
            activation_hold_ids=("plugin.video.redlight",),
            activation_hold_released=False,
            updater_guard_required=True,
            status_message="PRIVATE_RESULT_DETAIL_DO_NOT_EMIT",
            manifest_path="/private/result/path",
        )
        result = SimpleNamespace(
            outcome="needs_attention",
            code="PRIVATE_RESULT_CODE_DO_NOT_EMIT",
            message="PRIVATE_RESULT_MESSAGE_DO_NOT_EMIT",
            transaction=result_transaction,
        )
        calls = []

        class Coordinator:
            def retry_held_quiescence(_self, **kwargs):
                calls.append(kwargs)
                return result

        args = {
            "coordinator": Coordinator(),
            "store": store,
            "artifact_source_store": source_store,
            "restart_store": restart_store,
            "manifest": manifest,
            "manifest_path": str(manifest_path),
            "configuration_manifest_path": str(configuration_path),
            "device_profile_id": "reviewed-profile",
            "expected_overlay_id": "reviewed-overlay",
            "transaction_type": type(transaction),
            "needs_attention_phase": self.Phase.NEEDS_ATTENTION,
            "quiescence_awaiting_restart_stage": self.Lifecycle.QUIESCENCE_AWAITING_RESTART,
            "automatic_update_policy": self.Policy.AUTOMATIC,
        }
        return args, transaction, source_store, restart_store, calls

    def run_retry(self, args):
        call_args = dict(args)
        coordinator = call_args.pop("coordinator")
        store = call_args.pop("store")
        source_store = call_args.pop("artifact_source_store")
        restart_store = call_args.pop("restart_store")
        return retry_held_frozen_install(
            coordinator, store, source_store, restart_store, **call_args
        )

    def test_retry_dispatches_once_with_reviewed_snapshot_and_shared_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, transaction, source_store, restart_store, calls = self.fixture(Path(tmp))
            payload = self.run_retry(args)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0]["expected_transaction"], transaction)
        self.assertIs(calls[0]["artifact_source_store"], source_store)
        self.assertIs(calls[0]["restart_store"], restart_store)
        self.assertNotIn("current_session_id", calls[0])
        self.assertEqual(payload["adapter_mode"], "retry")
        self.assertTrue(payload["retry_invoked"])

    def test_retry_missing_coordinator_api_fails_closed_with_fixed_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, _transaction, _source_store, _restart_store, calls = self.fixture(Path(tmp))
            args["coordinator"] = SimpleNamespace()
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_retry(args)
        error = raised.exception
        self.assertEqual(error.stage, "INVOKE_RETRY")
        self.assertEqual(
            error.failing_callable,
            "FrozenInstallCoordinator.retry_held_quiescence",
        )
        self.assertEqual(error.failure_category, "retry_api_unavailable")
        payload = safe_failure_payload("CHECK_RETRY_PRECONDITIONS", "result_serializer", error)
        self.assertEqual(payload["adapter_stage"], "INVOKE_RETRY")
        self.assertEqual(
            payload["failing_callable"],
            "FrozenInstallCoordinator.retry_held_quiescence",
        )
        self.assertEqual(payload["failure_category"], "retry_api_unavailable")
        self.assertEqual(calls, [])

    def test_retry_invocation_exception_has_static_sanitized_category(self):
        private_value = "PRIVATE_RETRY_EXCEPTION_VALUE_DO_NOT_EMIT"
        private_path = "/private/retry/exception/path"
        calls = []

        def fail_retry(**kwargs):
            calls.append(kwargs)
            raise RuntimeError(f"{private_value} {private_path}")

        with tempfile.TemporaryDirectory() as tmp:
            args, transaction, _source_store, _restart_store, _calls = self.fixture(Path(tmp))
            args["coordinator"].retry_held_quiescence = fail_retry
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_retry(args)

            payload = safe_failure_payload(
                "CHECK_RETRY_PRECONDITIONS",
                "FrozenInstallStore.inspect",
                raised.exception,
            )
            serialized = json.dumps(payload)

            self.assertEqual(payload["adapter_stage"], "INVOKE_RETRY")
            self.assertEqual(
                payload["failing_callable"],
                "FrozenInstallCoordinator.retry_held_quiescence",
            )
            self.assertEqual(payload["failure_category"], "retry_invocation_failed")
            self.assertNotIn(private_value, serialized)
            self.assertNotIn(private_path, serialized)
            self.assertNotIn("RuntimeError:", serialized)
            self.assertNotIn("traceback", serialized.lower())
            self.assertEqual(len(calls), 1)
            self.assertIs(calls[0]["expected_transaction"], transaction)
            self.assertEqual(transaction.activation_hold_ids, ("plugin.video.redlight",))
            self.assertFalse(transaction.activation_hold_released)
            self.assertIs(args["store"].current, transaction)

    def test_retry_result_shape_contains_only_sanitized_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, _transaction, _source_store, _restart_store, _calls = self.fixture(Path(tmp))
            payload = self.run_retry(args)
        self.assertEqual(set(payload), {
            "ok", "adapter_mode", "retry_invoked", "outcome", "transaction"
        })
        self.assertEqual(payload["outcome"], "needs_attention")
        self.assertEqual(set(payload["transaction"]), {
            "phase", "lifecycle_stage", "lifecycle_restart_count",
            "activation_hold_ids", "activation_hold_released",
            "updater_guard_required",
        })
        serialized = json.dumps(payload)
        for private_text in (
            "PRIVATE_FAILURE_DETAIL_DO_NOT_EMIT",
            "PRIVATE_RESULT_DETAIL_DO_NOT_EMIT",
            "PRIVATE_RESULT_CODE_DO_NOT_EMIT",
            "PRIVATE_RESULT_MESSAGE_DO_NOT_EMIT",
            "/private/result/path",
        ):
            self.assertNotIn(private_text, serialized)

    def test_retry_fail_closed_preconditions_never_call_coordinator(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, _transaction, _source_store, _restart_store, calls = self.fixture(Path(tmp))
            mutations = (
                ("phase", self.Phase.AWAITING_RESTART),
                ("status_code", "OTHER_FAILURE"),
                ("lifecycle_stage", self.Lifecycle.NONE),
                ("lifecycle_restart_count", 2),
                ("activation_hold_ids", ("plugin.video.other",)),
                ("activation_hold_released", True),
                ("updater_guard_required", False),
                ("original_update_policy", self.Policy.NOTIFY_ONLY),
                ("install_plan_fingerprint", ""),
                ("resolution_fingerprint", ""),
                ("manifest_path", "/other/reviewed-manifest.json"),
                ("build_id", "other-build"),
                ("manifest_fingerprint", "e" * 64),
                ("configuration_manifest_path", "/other/configuration.json"),
                ("device_profile_id", "other-profile"),
                ("private_overlay_id", "other-overlay"),
                ("private_overlay_fingerprint", ""),
            )
            original = args["store"].current
            for field, value in mutations:
                with self.subTest(field=field):
                    args["store"].current = SimpleNamespace(**vars(original))
                    setattr(args["store"].current, field, value)
                    with self.assertRaises(AdapterBootstrapError):
                        self.run_retry(args)
                    self.assertEqual(calls, [])
            args["store"].current = None
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_retry(args)
            self.assertEqual(raised.exception.failure_category, "transaction_missing")
            self.assertEqual(calls, [])

    def test_retry_rejects_invalid_snapshot_type_and_transaction_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, transaction, _source_store, _restart_store, calls = self.fixture(Path(tmp))
            args["store"].current = object()
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_retry(args)
            self.assertEqual(raised.exception.failure_category, "retry_snapshot_invalid")
            args["store"].current = SimpleNamespace(**vars(transaction))
            args["store"].current.transaction_id = "not-a-uuid"
            with self.assertRaises(AdapterBootstrapError) as raised:
                self.run_retry(args)
            self.assertEqual(raised.exception.failure_category, "transaction_identity_invalid")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()


SECRET = "PRIVATE-SENTINEL-4f9c"
FROZEN_ID = "33333333-3333-4333-8333-333333333333"
RESTART_ID = "44444444-4444-4444-8444-444444444444"
SESSION = "55555555-5555-4555-8555-555555555555"


def _frozen_transaction(**changes):
    values = dict(
        transaction_id=FROZEN_ID,
        build_id=SECRET + "-build",
        manifest_path="/" + SECRET + "/manifest.json",
        device_profile_id=SECRET + "-profile",
        manifest_fingerprint="a" * 64,
        phase=FrozenInstallPhase.NEEDS_ATTENTION,
        originating_kodi_session_id=SESSION,
        original_update_policy=AddonUpdatePolicy.AUTOMATIC,
        created_at="2026-09-21T00:00:00Z",
        updated_at="2026-09-21T00:00:00Z",
        status_code="FROZEN_MANIFEST_INVALID",
        status_message=SECRET + " message",
        restart_transaction_id=RESTART_ID,
        configuration_manifest_path="/" + SECRET + "/configuration.json",
        lifecycle_stage=FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
        activation_hold_ids=("plugin.video.redlight", "plugin.private." + SECRET),
        activation_hold_released=False,
        lifecycle_restart_count=1,
        private_overlay_id=SECRET + "-overlay",
        private_overlay_required=True,
    )
    values.update(changes)
    return FrozenInstallTransaction(**values)


def _restart_transaction(**changes):
    values = dict(
        transaction_id=RESTART_ID,
        phase=TransactionPhase.NEEDS_ATTENTION,
        request=ReconcileRequest(
            manifest_path="/" + SECRET + "/manifest.json",
            device_profile_id=SECRET + "-profile",
        ),
        desired_state_fingerprint="sha256:" + "b" * 64,
        restart_requirement=RestartRequirement.KODI_RESTART,
        originating_kodi_session_id=SESSION,
        restart_attempt_count=2,
        created_at="2026-09-21T00:00:00Z",
        updated_at="2026-09-21T00:00:00Z",
        status_code="PREVIEW_FAILED",
        status_message=SECRET + " restart message",
    )
    values.update(changes)
    return RestartTransaction(**values)


def _tree_snapshot(root: Path):
    snapshot = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        snapshot[str(path.relative_to(root))] = (
            None if path.is_dir() else path.read_bytes(),
            info.st_mtime_ns,
            info.st_ino,
            info.st_size,
        )
    return snapshot


class TestBm023aStatusMode(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.frozen_path = self.root / "frozen_install_transaction.json"
        self.frozen_lock = self.root / "frozen_install_transaction.lock"
        self.restart_path = self.root / "restart_transaction.json"
        self.restart_lock = self.root / "restart_transaction.lock"

    def read(self):
        return read_adapter_status(
            self.frozen_path, self.frozen_lock, self.restart_path, self.restart_lock,
            FrozenInstallTransaction.from_dict, RestartTransaction.from_dict,
        )

    def write_state(self, frozen=None, restart=None, locks=True):
        if frozen is not None:
            self.frozen_path.write_text(
                json.dumps(frozen.to_dict(), sort_keys=True), encoding="utf-8"
            )
        if restart is not None:
            self.restart_path.write_text(restart.to_json() + "\n", encoding="utf-8")
        if locks:
            self.frozen_lock.write_bytes(b"")
            self.restart_lock.write_bytes(b"")

    def test_status_mode_is_an_explicit_allowlisted_token_and_tags_results(self):
        self.assertEqual(parse_adapter_mode(["status"]), "status")
        self.assertEqual(parse_adapter_mode(["?mode=status"]), "status")
        for bad in ([], [""], ["Status"], ["status", "install"], ["status "], ["?mode=statu"]):
            with self.subTest(arguments=bad), self.assertRaises(AdapterBootstrapError):
                parse_adapter_mode(bad)
        self.assertEqual(
            identify_adapter_result({"ok": True}, "status")["adapter_mode"], "status"
        )

    def test_absent_state_reports_fixed_schema_with_no_values(self):
        status = self.read()
        self.assertEqual(set(status), STATUS_KEYS)
        self.assertEqual(status["adapter_version"], ADAPTER_VERSION)
        self.assertEqual(status["frozen_transaction_state"], "absent")
        self.assertEqual(status["restart_transaction_state"], "absent")
        self.assertIs(status["frozen_lock_file_present"], False)
        self.assertIs(status["restart_lock_file_present"], False)
        for key in STATUS_KEYS - {
            "adapter_version", "frozen_transaction_state", "restart_transaction_state",
            "frozen_lock_file_present", "restart_lock_file_present",
        }:
            self.assertIsNone(status[key], key)

    def test_present_state_reports_exact_allowlisted_values_only(self):
        self.write_state(_frozen_transaction(), _restart_transaction())
        status = self.read()
        self.assertEqual(set(status), STATUS_KEYS)
        self.assertEqual(status, {
            "adapter_version": ADAPTER_VERSION,
            "frozen_transaction_state": "present",
            "frozen_phase": "needs_attention",
            "frozen_lifecycle_stage": "quiescence_awaiting_restart",
            "frozen_lifecycle_restart_count": 1,
            "frozen_status_code": "FROZEN_MANIFEST_INVALID",
            "activation_hold_count": 2,
            "redlight_hold_present": True,
            "activation_hold_released": False,
            "updater_guard_required": True,
            "private_overlay_required": True,
            "original_update_policy": "AUTOMATIC",
            "resolution_record_count": 0,
            "restart_transaction_state": "present",
            "restart_phase": "needs_attention",
            "restart_attempt_count": 2,
            "restart_status_code": "PREVIEW_FAILED",
            "restart_transaction_linked": True,
            "frozen_lock_file_present": True,
            "restart_lock_file_present": True,
        })

    def test_unlinked_restart_transaction_is_reported_as_false(self):
        other = "66666666-6666-4666-8666-666666666666"
        self.write_state(_frozen_transaction(), _restart_transaction(transaction_id=other))
        self.assertIs(self.read()["restart_transaction_linked"], False)

    def test_output_never_contains_private_values_paths_ids_or_message_text(self):
        self.write_state(_frozen_transaction(), _restart_transaction())
        serialized = json.dumps(self.read(), sort_keys=True)
        for forbidden in (
            SECRET, "/", FROZEN_ID, RESTART_ID, SESSION, "manifest", "message",
            "a" * 64, "b" * 64, "plugin.private",
        ):
            self.assertNotIn(forbidden, serialized, forbidden)

    def test_hostile_status_codes_are_dropped_not_echoed(self):
        for code in ("/private/tmp/" + SECRET, SECRET.lower(), "lower_case", "A" * 65, ""):
            with self.subTest(code=code):
                frozen = _frozen_transaction(status_code=code)
                restart = _restart_transaction(status_code=code)
                self.write_state(frozen, restart)
                status = self.read()
                if len(code) <= 96:
                    self.assertIsNone(status["frozen_status_code"])
                    self.assertIsNone(status["restart_status_code"])
                self.assertNotIn(SECRET, json.dumps(status))

    def test_uppercase_private_status_codes_are_not_public_codes(self):
        for code in ("PRIVATE_SENTINEL_TOKEN_4F9C", "SECRET_PATH_HOME_ERICS_PROFILE",
                     "FROZEN_PRIVATE_SENTINEL", "RESTART_PRIVATE_SENTINEL"):
            with self.subTest(code=code):
                self.write_state(_frozen_transaction(status_code=code),
                                 _restart_transaction(status_code=code))
                status = self.read()
                self.assertEqual(status["frozen_transaction_state"], "present")
                self.assertEqual(status["restart_transaction_state"], "present")
                self.assertIsNone(status["frozen_status_code"])
                self.assertIsNone(status["restart_status_code"])
                self.assertNotIn(code, json.dumps(status))

    def test_product_status_code_allowlists_preserve_known_public_codes(self):
        for code in bm023a_adapter_support.STATUS_FROZEN_CODES:
            with self.subTest(frozen_code=code):
                self.write_state(_frozen_transaction(status_code=code), locks=False)
                self.assertEqual(self.read()["frozen_status_code"], code)
        for code in bm023a_adapter_support.STATUS_RESTART_CODES:
            with self.subTest(restart_code=code):
                self.write_state(restart=_restart_transaction(status_code=code), locks=False)
                self.assertEqual(self.read()["restart_status_code"], code)

    def test_code_from_the_other_transaction_domain_is_dropped(self):
        self.write_state(_frozen_transaction(status_code="PREVIEW_FAILED"),
                         _restart_transaction(status_code="FROZEN_MANIFEST_INVALID"))
        status = self.read()
        self.assertIsNone(status["frozen_status_code"])
        self.assertIsNone(status["restart_status_code"])

    def test_public_status_codes_come_from_product_definitions(self):
        project = Path(__file__).parents[1]
        literals = set()
        for name in ("frozen_install", "resume", "build_manager"):
            tree = ast.parse((project / "resources/lib" / (name + ".py")).read_text())
            literals.update(node.value for node in ast.walk(tree)
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))
        for code in bm023a_adapter_support.STATUS_FROZEN_CODES:
            with self.subTest(code=code):
                if code.startswith("FROZEN_CONFIGURATION_") and code not in literals:
                    self.assertIn(code.removeprefix("FROZEN_CONFIGURATION_"), literals)
                else:
                    self.assertIn(code, literals)
        self.assertLessEqual(bm023a_adapter_support.STATUS_RESTART_CODES, literals)

    def _read_in_subprocess(self, *, replace_with_fifo=False):
        # Contain a regression to a blocking FIFO open in a disposable child.
        script = '''
import json, os, sys
from pathlib import Path
from unittest.mock import patch
from tests.test_bm023a_adapter import FrozenInstallTransaction, RestartTransaction
from tools.bm023a_adapter_support import read_adapter_status
root = Path(sys.argv[1])
original_open = os.open
def replacing_open(path, flags, *args, **kwargs):
    Path(path).unlink()
    os.mkfifo(path)
    return original_open(path, flags, *args, **kwargs)
with patch("os.open", replacing_open if sys.argv[2] == "race" else original_open):
    status = read_adapter_status(
        root / "frozen_install_transaction.json", root / "frozen_install_transaction.lock",
        root / "restart_transaction.json", root / "restart_transaction.lock",
        FrozenInstallTransaction.from_dict, RestartTransaction.from_dict)
print(json.dumps(status))
'''
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(self.root),
             "race" if replace_with_fifo else "plain"],
            cwd=Path(__file__).parents[1], capture_output=True, text=True,
            timeout=5, check=True,
        )
        status = json.loads(result.stdout)
        for key in ("frozen_transaction_state", "restart_transaction_state"):
            self.assertEqual(status[key], "unreadable")
        for key in ("frozen_phase", "restart_phase", "frozen_status_code",
                    "restart_status_code", "restart_transaction_linked"):
            self.assertIsNone(status[key])
        return status

    def test_fifo_records_without_writers_return_without_blocking(self):
        for path in (self.frozen_path, self.restart_path):
            os.mkfifo(path)
        self._read_in_subprocess()
        self.assertEqual({p.name for p in self.root.iterdir()},
                         {self.frozen_path.name, self.restart_path.name})

    def test_regular_records_replaced_by_fifos_before_open_do_not_block(self):
        self.write_state(_frozen_transaction(), _restart_transaction(), locks=False)
        self._read_in_subprocess(replace_with_fifo=True)

    def test_symlink_records_to_regular_files_or_fifos_are_rejected(self):
        regular = self.root / "regular.json"
        regular.write_text(json.dumps(_frozen_transaction().to_dict()), encoding="utf-8")
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        self.frozen_path.symlink_to(regular)
        self.restart_path.symlink_to(fifo)
        self._read_in_subprocess()

    def test_regular_file_replacement_before_open_is_rejected(self):
        from unittest.mock import patch

        self.write_state(_frozen_transaction(), _restart_transaction(), locks=False)
        original_open = os.open
        def replacing_open(path, flags, *args, **kwargs):
            replacement = Path(path).with_suffix(".replacement")
            replacement.write_bytes(Path(path).read_bytes())
            os.replace(replacement, path)
            return original_open(path, flags, *args, **kwargs)
        with patch("os.open", replacing_open):
            status = self.read()
        self.assertEqual(status["frozen_transaction_state"], "unreadable")
        self.assertEqual(status["restart_transaction_state"], "unreadable")

    def test_path_replacement_after_open_is_rejected(self):
        from unittest.mock import patch

        self.write_state(_frozen_transaction(), _restart_transaction(), locks=False)
        original_open = os.open
        def replacing_open(path, flags, *args, **kwargs):
            fd = original_open(path, flags, *args, **kwargs)
            Path(path).unlink()
            os.mkfifo(path)
            return fd
        with patch("os.open", replacing_open):
            status = self.read()
        self.assertEqual(status["frozen_transaction_state"], "unreadable")
        self.assertEqual(status["restart_transaction_state"], "unreadable")

    def test_regular_records_replaced_by_symlinks_or_directories_are_rejected(self):
        from unittest.mock import Mock, patch

        for replacement_type in ("symlink", "directory"):
            with self.subTest(replacement_type=replacement_type):
                record = self.root / replacement_type
                record.write_text("{}", encoding="utf-8")
                target = self.root / (replacement_type + "-target")
                target.write_text("{}", encoding="utf-8")
                original_open = os.open
                def replacing_open(path, flags, *args, **kwargs):
                    Path(path).unlink()
                    if replacement_type == "symlink":
                        Path(path).symlink_to(target)
                    else:
                        Path(path).mkdir()
                    return original_open(path, flags, *args, **kwargs)
                loader = Mock(side_effect=AssertionError("replacement decoded"))
                with patch("os.open", replacing_open):
                    state, value = bm023a_adapter_support._status_load(record, 128, loader)
                self.assertEqual((state, value), ("unreadable", None))
                loader.assert_not_called()

    def test_missing_nonblocking_or_nofollow_flag_fails_closed_without_open(self):
        from unittest.mock import patch

        self.write_state(_frozen_transaction(), _restart_transaction(), locks=False)
        for flag in ("O_NONBLOCK", "O_NOFOLLOW"):
            with self.subTest(flag=flag), patch.dict(os.__dict__):
                os.__dict__.pop(flag, None)
                with patch("os.open", side_effect=AssertionError("unsafe open")):
                    status = self.read()
                self.assertEqual(status["frozen_transaction_state"], "unreadable")
                self.assertEqual(status["restart_transaction_state"], "unreadable")

    def test_nonregular_open_descriptor_is_rejected_and_closed_before_read(self):
        import stat
        from unittest.mock import Mock, patch

        self.frozen_path.write_text("{}", encoding="utf-8")
        original_fstat = os.fstat
        original_open = os.open
        for mode in (stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK, stat.S_IFDIR):
            with self.subTest(mode=mode):
                descriptors = []
                def recording_open(*args, **kwargs):
                    fd = original_open(*args, **kwargs)
                    descriptors.append(fd)
                    return fd
                def nonregular_fstat(fd):
                    info = original_fstat(fd)
                    return SimpleNamespace(st_mode=mode, st_dev=info.st_dev, st_ino=info.st_ino)
                loader = Mock(side_effect=AssertionError("nonregular file decoded"))
                with patch("os.open", recording_open), patch("os.fstat", nonregular_fstat), \
                        patch("os.fdopen", side_effect=AssertionError("nonregular file read")):
                    state, value = bm023a_adapter_support._status_load(self.frozen_path, 128, loader)
                self.assertEqual((state, value), ("unreadable", None))
                loader.assert_not_called()
                self.assertEqual(len(descriptors), 1)
                with self.assertRaises(OSError):
                    original_fstat(descriptors[0])

    def test_unexpected_enum_and_count_values_are_dropped(self):
        frozen = SimpleNamespace(
            phase="not-a-phase", lifecycle_stage=SECRET, lifecycle_restart_count=True,
            status_code=SECRET, activation_hold_ids=[SECRET], activation_hold_released="yes",
            updater_guard_required=1, private_overlay_required=None,
            original_update_policy=SimpleNamespace(name=SECRET),
            resolution_records=[object(), object()], restart_transaction_id="",
        )
        restart = SimpleNamespace(
            phase=SECRET, restart_attempt_count=10**9, status_code=SECRET, transaction_id="",
        )
        self.frozen_path.write_text("{}", encoding="utf-8")
        self.restart_path.write_text("{}", encoding="utf-8")
        status = read_adapter_status(
            self.frozen_path, self.frozen_lock, self.restart_path, self.restart_lock,
            lambda _value: frozen, lambda _value: restart,
        )
        self.assertEqual(set(status), STATUS_KEYS)
        self.assertNotIn(SECRET, json.dumps(status))
        for key in (
            "frozen_phase", "frozen_lifecycle_stage", "frozen_lifecycle_restart_count",
            "frozen_status_code", "activation_hold_released", "updater_guard_required",
            "private_overlay_required", "original_update_policy", "restart_phase",
            "restart_attempt_count", "restart_status_code",
        ):
            self.assertIsNone(status[key], key)
        self.assertEqual(status["resolution_record_count"], 2)
        self.assertIs(status["restart_transaction_linked"], False)

    def test_corrupt_oversized_and_unreadable_records_report_state_only(self):
        corrupt = "{" + SECRET
        cases = {
            "invalid": (corrupt, "invalid"),
            "oversized": (SECRET * 200000, "invalid"),
            "wrong-schema": (json.dumps({"private": SECRET}), "invalid"),
        }
        for label, (text, expected) in cases.items():
            with self.subTest(label=label):
                self.frozen_path.write_text(text, encoding="utf-8")
                self.restart_path.write_text(text, encoding="utf-8")
                status = self.read()
                self.assertEqual(status["frozen_transaction_state"], expected)
                self.assertEqual(status["restart_transaction_state"], expected)
                self.assertIsNone(status["frozen_phase"])
                self.assertNotIn(SECRET, json.dumps(status))
        self.frozen_path.chmod(0)
        self.restart_path.chmod(0)
        try:
            if os.access(self.frozen_path, os.R_OK):
                self.skipTest("file permissions are not enforced")
            status = self.read()
            self.assertEqual(status["frozen_transaction_state"], "unreadable")
            self.assertEqual(status["restart_transaction_state"], "unreadable")
        finally:
            self.frozen_path.chmod(0o600)
            self.restart_path.chmod(0o600)

    def test_directory_in_place_of_transaction_is_unreadable(self):
        self.frozen_path.mkdir()
        self.assertEqual(self.read()["frozen_transaction_state"], "unreadable")

    def test_reading_mutates_nothing_and_creates_nothing(self):
        self.write_state(_frozen_transaction(), _restart_transaction())
        before = _tree_snapshot(self.root)
        self.read()
        self.read()
        self.assertEqual(_tree_snapshot(self.root), before)

    def test_absent_files_and_directories_are_not_created(self):
        missing = self.root / "never" / "created"
        read_adapter_status(
            missing / "f.json", missing / "f.lock", missing / "r.json", missing / "r.lock",
            FrozenInstallTransaction.from_dict, RestartTransaction.from_dict,
        )
        self.assertFalse((self.root / "never").exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_held_exclusive_lock_is_neither_waited_on_nor_disturbed(self):
        self.write_state(_frozen_transaction(), _restart_transaction())
        handles = []
        try:
            for lock in (self.frozen_lock, self.restart_lock):
                handle = lock.open("a+")
                handles.append(handle)
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            status = self.read()
            self.assertEqual(status["frozen_transaction_state"], "present")
            self.assertEqual(status["restart_transaction_state"], "present")
            for handle in handles:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            for handle in handles:
                handle.close()

    def test_status_source_has_no_mutating_or_locking_calls(self):
        support = Path(bm023a_adapter_support.__file__).read_text(encoding="utf-8")
        start = support.index("def _status_file_present")
        end = support.index("def choose_missing_artifact_resolution")
        body = support[start:end]
        for forbidden in (
            "flock", "mkdir", "makedirs", "unlink", "rename", "replace(", "write",
            "touch", "chmod", "remove", "rmtree", "mkstemp", "O_CREAT",
            "import_module", "FrozenInstallStore", "TransactionStore", "abandon",
        ):
            self.assertNotIn(forbidden, body, forbidden)
        self.assertIn("os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW", body)
        self.assertIn('os.fdopen(fd, "rb", closefd=False)', body)

    def test_entrypoint_status_branch_never_constructs_stores_or_coordinators(self):
        source = (
            Path(__file__).parents[1] / "tools/bm023a_adapter/default.py.in"
        ).read_text(encoding="utf-8")
        start = source.index('        if mode == "status":\n            frozen_install_module')
        end = source.index('        if mode == "status":\n            pass')
        branch = source[start:end]
        for forbidden in (
            "FrozenInstallStore", "FrozenInstallCoordinator", "TransactionStore.inspect",
            ".inspect(", "locked", "abandon", "repair_frozen_install_source",
            "retry_held", "recover_frozen", "install(", "stage_manifest_artifacts",
            "PrivateOverlayStore", "_rpc", "executeJSONRPC",
        ):
            self.assertNotIn(forbidden, branch, forbidden)
        self.assertIn("repair_frozen_install_source", source)
        self.assertIn('if mode != "status":\n            FROZEN_INSTALL_SOURCE_RECORD', source)

    def test_allowlists_cover_status_labels(self):
        self.assertIn("READ_STATUS", bm023a_adapter_support.ADAPTER_STAGES)
        self.assertIn("read_adapter_status", bm023a_adapter_support.ADAPTER_CALLABLES)
        self.assertEqual(
            bm023a_adapter_support.STATUS_FROZEN_PHASES,
            {member.value for member in FrozenInstallPhase},
        )
        self.assertEqual(
            bm023a_adapter_support.STATUS_LIFECYCLE_STAGES,
            {member.value for member in FrozenLifecycleStage},
        )
        self.assertEqual(
            bm023a_adapter_support.STATUS_RESTART_PHASES,
            {member.value for member in TransactionPhase},
        )
        self.assertEqual(
            bm023a_adapter_support.STATUS_UPDATE_POLICIES,
            {member.name for member in AddonUpdatePolicy},
        )


class TestBm023aStatusEntrypoint(unittest.TestCase):
    def run_status(self, *, with_state=True, frozen_install_matches=True):
        import importlib
        import runpy
        from unittest.mock import patch

        project = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_root = (
                root / "Kodi Build Manager Test.app" / "Contents" / "Resources"
                / "Kodi" / "portable_data" / "userdata"
            )
            addons_root = profile_root.parent / "addons"
            addon_root = addons_root / "script.build.manager"
            (addon_root / "resources").mkdir(parents=True)
            shutil.copytree(
                project / "resources" / "lib", addon_root / "resources" / "lib",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            if not frozen_install_matches:
                (addon_root / "resources" / "lib" / "frozen_install.py").write_text(
                    "# tampered\n", encoding="utf-8"
                )
            data_dir = profile_root / "addon_data" / "script.build.manager"
            data_dir.mkdir(parents=True)
            if with_state:
                (data_dir / "frozen_install_transaction.json").write_text(
                    json.dumps(_frozen_transaction().to_dict()), encoding="utf-8"
                )
                (data_dir / "restart_transaction.json").write_text(
                    _restart_transaction().to_json() + "\n", encoding="utf-8"
                )
                (data_dir / "frozen_install_transaction.lock").write_bytes(b"")
                (data_dir / "restart_transaction.lock").write_bytes(b"")
            values = {key: str(root / key.lower()) for key in (
                "MANIFEST_PATH", "ARTIFACT_ROOT", "CONFIGURATION_PATH", "OVERLAY_SOURCE",
            )}
            values.update({"DEVICE_PROFILE_ID": "p", "EXPECTED_OVERLAY_ID": "o"})
            archive = build_adapter(root / "generated", values)
            generated_root = archive.parent / "script.build.manager.bm023a_driver"
            entrypoint = generated_root / "default.py"

            xbmc_module = ModuleType("xbmc")
            xbmc_module.executeJSONRPC = lambda _request: self.fail("status must not call JSON-RPC")
            xbmcvfs_module = ModuleType("xbmcvfs")
            translated = {
                "special://profile/": profile_root,
                "special://home/addons": addons_root,
                "special://home/addons/script.build.manager": addon_root,
                "special://profile/addon_data/script.build.manager": data_dir,
            }
            xbmcvfs_module.translatePath = lambda path: str(translated[path])

            cached = [
                name for name in sys.modules
                if name == "resources" or name.startswith("resources.")
                or name in ("adapter_config", "adapter_support")
            ]
            saved_modules = {name: sys.modules.pop(name) for name in cached}
            saved_path = list(sys.path)
            saved_argv = sys.argv
            before = _tree_snapshot(profile_root)
            try:
                sys.path.insert(0, str(generated_root))
                sys.argv = [str(entrypoint), "status"]
                with patch.dict(sys.modules, {"xbmc": xbmc_module, "xbmcvfs": xbmcvfs_module}):
                    runpy.run_path(str(entrypoint), run_name="__main__")
                    imported = {
                        name for name in sys.modules if name.startswith("resources.lib.")
                    }
            finally:
                sys.path[:] = saved_path
                sys.argv = saved_argv
                for name in [
                    n for n in sys.modules
                    if n == "resources" or n.startswith("resources.")
                    or n in ("adapter_config", "adapter_support")
                ]:
                    sys.modules.pop(name, None)
                sys.modules.update(saved_modules)
            result_path = data_dir / "bm023a_live_result.json"
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            after = _tree_snapshot(profile_root)
            result_key = str(result_path.relative_to(profile_root))
            directories = lambda snap: {k for k, v in snap.items() if v[0] is None}
            self.assertEqual(directories(before), directories(after))
            changed = {
                key for key in set(before) | set(after)
                if before.get(key) != after.get(key) and key not in directories(before)
            }
            backups = (data_dir.parent / "script.build.manager.bm023a_driver").exists()
            return payload, changed, result_key, imported, backups

    def test_generated_status_run_writes_only_the_sanitized_result(self):
        payload, changed, result_key, imported, backups = self.run_status()
        self.assertEqual(set(payload), {"ok", "adapter_mode", "status"})
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["adapter_mode"], "status")
        self.assertEqual(set(payload["status"]), STATUS_KEYS)
        self.assertEqual(payload["status"]["frozen_phase"], "needs_attention")
        self.assertEqual(payload["status"]["frozen_lifecycle_restart_count"], 1)
        self.assertEqual(payload["status"]["restart_attempt_count"], 2)
        self.assertIs(payload["status"]["redlight_hold_present"], True)
        self.assertIs(payload["status"]["restart_transaction_linked"], True)
        serialized = json.dumps(payload)
        for forbidden in (SECRET, "/", FROZEN_ID, RESTART_ID, SESSION):
            self.assertNotIn(forbidden, serialized, forbidden)
        self.assertEqual(changed, {result_key})
        self.assertFalse(backups)
        self.assertNotIn("resources.lib.restart_coordinator", imported)

    def test_generated_status_run_with_no_state_creates_no_state_files(self):
        payload, changed, result_key, _imported, _backups = self.run_status(with_state=False)
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["status"]["frozen_transaction_state"], "absent")
        self.assertEqual(payload["status"]["restart_transaction_state"], "absent")
        self.assertEqual(changed, {result_key})

    def test_source_mismatch_fails_closed_without_repair_or_state_read(self):
        payload, changed, result_key, _imported, backups = self.run_status(
            frozen_install_matches=False
        )
        self.assertIs(payload["ok"], False)
        self.assertEqual(payload["adapter_mode"], "status")
        self.assertNotIn("status", payload)
        self.assertNotIn("frozen_install_source", payload)
        self.assertEqual(changed, {result_key})
        self.assertFalse(backups)
        self.assertNotIn(SECRET, json.dumps(payload))
