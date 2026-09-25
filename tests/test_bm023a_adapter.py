"""Offline provenance, diagnostics, and packaging tests for BM-023A adapter."""

from __future__ import annotations

import ast
import hashlib
import json
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
from resources.lib.frozen_install import FrozenInstallCoordinator
from tools.bm023a_adapter_support import (
    ADAPTER_VERSION,
    AdapterBootstrapError,
    choose_missing_artifact_resolution,
    identify_adapter_result,
    parse_adapter_mode,
    recover_frozen_install,
    safe_failure_payload,
    stage_manifest_artifacts,
    verify_build_manager_source,
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
            and any(keyword.arg == "configuration_runner" for keyword in node.keywords)
        )
        callback_reference = next(
            keyword.value for keyword in install_call.keywords
            if keyword.arg == "configuration_runner"
        )
        self.assertIsInstance(callback_reference, ast.Name)
        callback_definition = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == callback_reference.id
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
            self.assertEqual(ADAPTER_VERSION, "0.0.6")
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
                names = set(archive.namelist())
                self.assertEqual(names, {
                    "script.build.manager.bm023a_driver/addon.xml",
                    "script.build.manager.bm023a_driver/default.py",
                    "script.build.manager.bm023a_driver/adapter_config.py",
                    "script.build.manager.bm023a_driver/adapter_support.py",
                })
                default = archive.read(
                    "script.build.manager.bm023a_driver/default.py"
                ).decode("utf-8")
                addon_xml = archive.read(
                    "script.build.manager.bm023a_driver/addon.xml"
                ).decode("utf-8")
            self.assertIn('import_module("resources.lib")', default)
            self.assertNotIn("resources.__file__", default)
            self.assertIn('version="0.0.6"', addon_xml)
            compile(default, "generated-default.py", "exec")


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

    def fixture(self, root: Path, *, phase="needs_attention", transaction_id=None):
        root.mkdir(parents=True, exist_ok=True)
        transaction = SimpleNamespace(
            transaction_id=transaction_id or "3f920c0f-dc69-4684-914b-1bb370a17ba0",
            phase=phase,
            original_update_policy=self.Policy.ORIGINAL,
            activation_hold_ids=(),
            activation_hold_released=True,
            resolution_records=(SimpleNamespace(addon_id="plugin.example"),),
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
        recovery_branch, install_branch = dispatch.split("        else:", 1)
        self.assertIn("recover_frozen_install(", recovery_branch)
        self.assertNotIn("coordinator.install(", recovery_branch)
        self.assertIn("coordinator.install(", install_branch)
        self.assertNotIn("recover_frozen_install(", install_branch)

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
        self.assertIn("parse_adapter_mode(sys.argv[1:])", source)
        self.assertIn('coordinator.install(', source)
        self.assertNotIn("eval(", source)
        self.assertNotIn("exec(", source)
        self.assertNotIn("sys.argv[2:]", source)


if __name__ == "__main__":
    unittest.main()
