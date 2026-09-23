import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib.build_manager import (
    BuildManager,
    BuildManagerOwners,
    ReconcileRequest,
    fingerprint_resolved_build,
)
from resources.lib.dependencies import DependencyClosure
from resources.lib.dependencies import DependencyNode, DependencyStatus
from resources.lib.inspector import InstalledAddon, KodiState
from resources.lib.frozen_resolution import (
    InstallResolution,
    InstallResolutionRecord,
    ResolutionState,
)
from resources.lib.installed_addon_source import InstalledAddonSourceResolver
from resources.lib.manifest import (
    AddonEntry,
    BuildInfo,
    ConfigDeclarations,
    PrivateOverlayRef,
)
from resources.lib.private_overlay import PrivateOverlayMetadata
from resources.lib.private_resource import StructuredPrivateResourceDeclaration
from resources.lib.redlight_resource import redlight_declaration
from resources.lib.resolver import ResolvedBuild
from resources.lib.restart import RestartReport, RestartRequirement


class _Inspector:
    def __init__(self, states):
        self.states = list(states)
        self.calls = 0

    def inspect(self):
        self.calls += 1
        return self.states[min(self.calls - 1, len(self.states) - 1)]


class _DependencyResolver:
    def __init__(self, roots):
        self.roots = tuple(roots)
        self.calls = []

    def resolve_closure(self, roots, **kwargs):
        self.calls.append((tuple(roots), kwargs))
        return DependencyClosure(root_addon_ids=self.roots, nodes=())


class _ConfigLoader:
    def resolve(self, config):
        from resources.lib.config import EffectiveConfiguration
        return EffectiveConfiguration()


class _Outcome:
    def __init__(self, *, succeeded=True, changed=False, message="ok", report=None):
        self.succeeded = succeeded
        self.changed = changed
        self.message = message
        self.restart_report = report or RestartReport()


class _DependencyInstaller:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def install(self, addon_id, **kwargs):
        self.calls.append((addon_id, kwargs))
        return self.outcomes[addon_id]


class _Owners:
    def __init__(self, desired, states, dependency_roots, outcomes):
        self.inspector = _Inspector(states)
        self.dependency_resolver = _DependencyResolver(dependency_roots)
        self.dependency_installer = _DependencyInstaller(outcomes)
        self.manifest = object()
        self.sets = []

        class _State:
            def reconcile(inner, *args, **kwargs):
                self.sets.append((args, kwargs))
                return type("StateResult", (), {
                    "all_correct": True,
                    "changed": (),
                    "failed": (),
                    "results": (),
                })()

        class _Unused:
            def install(inner, *args, **kwargs):
                return _Outcome()

            def activate(inner, *args, **kwargs):
                return _Outcome()

            def apply(inner, *args, **kwargs):
                return _Outcome()

        self._state = _State()
        self._unused = _Unused()
        self.owners = BuildManagerOwners(
            inspector=self.inspector,
            manifest_loader=lambda path: self.manifest,
            resolver=lambda manifest, device: desired,
            dependency_resolver=self.dependency_resolver,
            repository_manager=self._unused,
            dependency_installer=self.dependency_installer,
            addon_state_reconciler=self._state,
            skin_activator=self._unused,
            config_loader=_ConfigLoader(),
            config_manager=self._unused,
        )


def _desired(addons=(), private=None):
    return ResolvedBuild(
        build=BuildInfo("test-build", "1.0.0"),
        engine_min_version="",
        platform_profile_id="macos",
        device_profile_id="dev",
        repositories=(),
        addons=tuple(addons),
        skin=None,
        config=None,
        optional_groups_applied=(),
        restart_policy=None,
        private_overlay=private,
    )


def _state(*addons):
    return KodiState("macos", "21.0", "", tuple(addons))


class TestBuildManager(unittest.TestCase):
    def test_request_is_safe_and_serializable(self):
        request = ReconcileRequest("/tmp/build.json", "family-room")
        self.assertEqual(
            request.to_dict(),
            {"manifest_path": "/tmp/build.json", "device_profile_id": "family-room"},
        )
        self.assertNotIn("runtime", request.to_json())
        with self.assertRaises(ValueError):
            ReconcileRequest("", "family-room")

    def test_explicit_frozen_skip_is_excluded_from_configuration_desired_state(self):
        from resources.lib.frozen_resolution import (
            InstallResolution,
            InstallResolutionRecord,
            ResolutionState,
        )

        youtube = "plugin.video.youtube"
        record = InstallResolutionRecord(
            youtube, "7.4.4+unofficial.2", InstallResolution.SKIPPED,
            ResolutionState.SKIPPED,
        )
        owners = _Owners(
            _desired((AddonEntry(youtube, "enabled"),)),
            [_state(), _state()], (), {},
        )
        request = ReconcileRequest("m", "family-room", install_resolutions=(record,))
        result = BuildManager(owners.owners).reconcile(request)

        self.assertTrue(result.success)
        self.assertFalse(any(action.addon_id == youtube for action in result.planned_actions))
        self.assertEqual(record.to_dict(), request.to_dict()["install_resolutions"][0])
        self.assertEqual([], owners.dependency_installer.calls)

    def test_source_software_fingerprint_is_forwarded_to_private_overlay(self):
        from resources.lib.frozen_resolution import (
            InstallResolution,
            InstallResolutionRecord,
            ResolutionState,
        )

        source_fingerprint = "a" * 64
        calls = []

        class _PrivateOverlayManager:
            def prepare(self, *args, **kwargs):
                calls.append(kwargs)
                return object()

        desired = _desired(
            (AddonEntry("plugin.video.youtube", "enabled"),),
            private=PrivateOverlayRef("local_file", overlay_id="fixture-overlay"),
        )
        owners = _Owners(desired, [_state()], (), {})
        owners.owners = replace(
            owners.owners, private_overlay_manager=_PrivateOverlayManager()
        )
        record = InstallResolutionRecord(
            "plugin.video.youtube", "7.4.4+unofficial.2",
            InstallResolution.SKIPPED, ResolutionState.SKIPPED,
        )
        request = ReconcileRequest(
            "build.json", "family-room", install_resolutions=(record,),
            source_software_fingerprint=source_fingerprint,
        )

        prepared, failure = BuildManager(owners.owners)._prepare(request)

        self.assertIsNone(failure)
        self.assertIsNotNone(prepared)
        self.assertEqual(
            source_fingerprint, calls[0]["source_software_fingerprint"]
        )

    def test_source_software_fingerprint_is_a_sha256_without_requiring_resolution(self):
        request = ReconcileRequest(
            "build.json", "family-room", source_software_fingerprint="a" * 64
        )
        self.assertEqual("a" * 64, request.source_software_fingerprint)
        with self.assertRaises(ValueError):
            ReconcileRequest("build.json", "family-room", source_software_fingerprint="A" * 64)

    def test_explicit_frozen_skip_fails_if_configuration_requires_dependency(self):
        from resources.lib.frozen_resolution import (
            InstallResolution,
            InstallResolutionRecord,
            ResolutionState,
        )

        youtube = "plugin.video.youtube"
        record = InstallResolutionRecord(
            youtube, "7.4.4+unofficial.2", InstallResolution.SKIPPED,
            ResolutionState.SKIPPED,
        )
        app = "plugin.video.app"
        actual = _state(InstalledAddon(app, True, "1.0.0"))
        owners = _Owners(
            _desired((AddonEntry(app, "enabled"), AddonEntry(youtube, "enabled"))),
            [actual, actual], (app,), {},
        )
        owners.dependency_resolver.resolve_closure = lambda roots, **kwargs: DependencyClosure(
            root_addon_ids=tuple(roots),
            nodes=(DependencyNode(
                addon_id=youtube,
                required_by=(app,),
                status=DependencyStatus.MISSING_REQUIRED,
                installed_version=None,
                installed_enabled=None,
                min_version_required="",
                optional=False,
            ),),
        )
        result = BuildManager(owners.owners).reconcile(
            ReconcileRequest("m", "family-room", install_resolutions=(record,))
        )

        self.assertFalse(result.success)
        self.assertEqual("PREFLIGHT_FAILED", result.failure.code)
        self.assertEqual([], owners.dependency_installer.calls)

    def test_explicit_frozen_skip_fails_closed_when_managed_addon_is_not_installed(self):
        from resources.lib.frozen_resolution import (
            InstallResolution,
            InstallResolutionRecord,
            ResolutionState,
        )

        youtube = "plugin.video.youtube"
        record = InstallResolutionRecord(
            youtube, "7.4.4+unofficial.2", InstallResolution.SKIPPED,
            ResolutionState.SKIPPED,
        )
        owners = _Owners(
            _desired((AddonEntry("plugin.video.app", "enabled"),)),
            [_state(), _state()], (), {},
        )
        result = BuildManager(owners.owners).reconcile(
            ReconcileRequest("m", "family-room", install_resolutions=(record,))
        )

        self.assertFalse(result.success)
        self.assertEqual("PREFLIGHT_FAILED", result.failure.code)
        self.assertEqual([], owners.dependency_installer.calls)

    def test_dispatch_covers_every_planner_action(self):
        from resources.lib import planner
        expected = {
            planner.INSTALL_REPOSITORY,
            planner.INSTALL_ADDON,
            planner.ENABLE_ADDON,
            planner.DISABLE_ADDON,
            planner.SET_SKIN,
            planner.CONFIGURE,
        }
        self.assertEqual(BuildManager.ACTION_KINDS, expected)

    def test_fingerprint_is_deterministic_and_excludes_private_overlay(self):
        first = _desired((AddonEntry("plugin.b", "enabled"), AddonEntry("plugin.a", "disabled")))
        second = _desired((AddonEntry("plugin.a", "disabled"), AddonEntry("plugin.b", "enabled")))
        self.assertEqual(fingerprint_resolved_build(first), fingerprint_resolved_build(second))
        private = replace(first, private_overlay=PrivateOverlayRef("private", "secret-path"))
        self.assertEqual(fingerprint_resolved_build(first), fingerprint_resolved_build(private))

    def test_noop_is_idempotent_and_has_no_restart(self):
        desired = _desired((AddonEntry("plugin.example", "enabled"),))
        owners = _Owners(
            desired,
            [_state(InstalledAddon("plugin.example", True, "1.0"))],
            ("plugin.example",),
            {},
        )
        manager = BuildManager(owners.owners)
        request = ReconcileRequest("manifest.json", "dev")
        first = manager.reconcile(request)
        second = manager.reconcile(request)
        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(first.planned_actions, ())
        self.assertEqual(first.restart_report, RestartReport())
        self.assertEqual(first.desired_fingerprint, second.desired_fingerprint)
        self.assertEqual(owners.dependency_resolver.calls[-1][1], {"require_root_metadata": True})

    def test_preview_matches_reconcile_fingerprint_without_owner_mutation(self):
        desired = _desired((AddonEntry("plugin.example", "enabled"),))
        owners = _Owners(
            desired,
            [_state(InstalledAddon("plugin.example", True, "1.0"))],
            ("plugin.example",),
            {},
        )
        manager = BuildManager(owners.owners)
        request = ReconcileRequest("manifest.json", "dev")

        preview = manager.preview(request)
        reconciled = manager.reconcile(request)

        self.assertTrue(preview.success)
        self.assertTrue(reconciled.success)
        self.assertEqual(preview.desired_fingerprint, reconciled.desired_fingerprint)
        self.assertEqual(owners.dependency_installer.calls, [])
        self.assertEqual(owners.sets, [])

    def test_preview_failure_is_structured(self):
        desired = _desired()
        owners = _Owners(desired, [_state()], (), {})

        def fail(_path):
            raise ValueError("private manifest token should not escape")

        owners.owners = replace(owners.owners, manifest_loader=fail)
        result = BuildManager(owners.owners).preview(
            ReconcileRequest("manifest.json", "dev")
        )
        self.assertFalse(result.success)
        self.assertEqual(result.failure.phase.value, "load")
        self.assertEqual(result.failure.code, "MANIFEST_LOAD_FAILED")
        self.assertLessEqual(len(result.failure.message), 500)

    def test_executes_in_plan_order_and_preserves_restart_before_failure(self):
        desired = _desired((
            AddonEntry("plugin.a", "enabled"),
            AddonEntry("plugin.b", "enabled"),
        ))
        owners = _Owners(
            desired,
            [_state(), _state(InstalledAddon("plugin.a", True, "1.0"))],
            ("plugin.a", "plugin.b"),
            {
                "plugin.a": _Outcome(
                    changed=True,
                    report=RestartReport(RestartRequirement.KODI_RESTART, 1, 0),
                ),
                "plugin.b": _Outcome(succeeded=False, message="install failed"),
            },
        )
        result = BuildManager(owners.owners).reconcile(ReconcileRequest("m", "dev"))
        self.assertFalse(result.success)
        self.assertEqual([r.action.addon_id for r in result.action_results], ["plugin.a", "plugin.b"])
        self.assertEqual(result.restart_report.requirement, RestartRequirement.KODI_RESTART)
        self.assertEqual(owners.dependency_installer.calls[0][0], "plugin.a")
        self.assertEqual(len(owners.dependency_installer.calls), 2)

    def test_authorized_lifecycle_projects_held_owner_disabled_and_rejects_other_request(self):
        from resources.lib.frozen_install import (
            FrozenInstallPhase,
            FrozenLifecycleStage,
        )
        from resources.lib.planner import ENABLE_ADDON

        owner_id = "plugin.video.redlight"
        declaration = redlight_declaration()
        record = InstallResolutionRecord(
            owner_id,
            "2.6.8",
            InstallResolution.EXACT,
            ResolutionState.INSTALLED,
            resolved_version="2.6.8",
            artifact_sha256="c" * 64,
            artifact_size=1261957,
        )
        desired = replace(
            _desired(
                (AddonEntry(owner_id, "enabled"),),
                PrivateOverlayRef("local_file", overlay_id="fixture-overlay"),
            ),
            config=ConfigDeclarations(structured_private_resources=(declaration,)),
        )
        owners = _Owners(
            desired,
            [_state(InstalledAddon(owner_id, False, "2.6.8"))],
            (owner_id,),
            {},
        )
        metadata = PrivateOverlayMetadata(
            "fixture-overlay", "sha256:" + "3" * 64, True, True
        )

        class _PrivateOverlayManager:
            def prepare(self, *args, **kwargs):
                return SimpleNamespace(
                    metadata=metadata,
                    overlay=SimpleNamespace(resources=()),
                    resource_declarations=(declaration,),
                )

            def verify_configured_resources(self, _prepared):
                return True

        owners.owners = replace(
            owners.owners,
            private_overlay_manager=_PrivateOverlayManager(),
        )
        transaction_id = "33333333-3333-4333-8333-333333333333"
        transaction = SimpleNamespace(
            transaction_id=transaction_id,
            phase=FrozenInstallPhase.CONFIGURING,
            lifecycle_stage=FrozenLifecycleStage.CONFIGURING,
            activation_hold_released=False,
            activation_hold_ids=(owner_id,),
            configuration_manifest_path="manifest.json",
            device_profile_id="dev",
            manifest_fingerprint="a" * 64,
            resolution_records=(record,),
            private_overlay_id="fixture-overlay",
            private_overlay_fingerprint=metadata.fingerprint,
            private_overlay_required=True,
        )
        fake_store = SimpleNamespace(inspect=lambda: transaction)
        request = ReconcileRequest(
            "manifest.json", "dev",
            install_resolutions=(record,),
            source_software_fingerprint="a" * 64,
            frozen_transaction_id=transaction_id,
        )
        with tempfile.TemporaryDirectory() as source_temp:
            addons_root = Path(source_temp) / "home" / "addons"
            installed_root = addons_root / owner_id
            installed_root.mkdir(parents=True)
            (installed_root / "addon.xml").write_text(
                f'<addon id="{owner_id}" version="2.6.8"/>', encoding="utf-8"
            )
            source_resolver = InstalledAddonSourceResolver(lambda: addons_root)
            owners.owners = replace(
                owners.owners,
                installed_addon_source_resolver=source_resolver,
            )
            with (
                patch("resources.lib.frozen_install.FrozenInstallStore", return_value=fake_store),
                patch(
                    "resources.lib.frozen_install.active_activation_hold_ids",
                    return_value=frozenset({owner_id}),
                ),
            ):
                preview = BuildManager(owners.owners).preview(request)
                unrelated = BuildManager(owners.owners).preview(
                    replace(request, frozen_transaction_id="")
                )
        self.assertTrue(preview.success)
        self.assertFalse(any(
            action.kind == ENABLE_ADDON for action in preview.planned_actions
        ))
        self.assertFalse(unrelated.success)
        self.assertEqual(unrelated.failure.code, "PREFLIGHT_FAILED")

    def test_wrong_registry_version_fails_before_installed_source_resolution(self):
        from resources.lib.frozen_install import FrozenInstallPhase, FrozenLifecycleStage

        owner_id = "plugin.video.redlight"
        declaration = redlight_declaration()
        record = InstallResolutionRecord(
            owner_id, "2.6.8", InstallResolution.EXACT, ResolutionState.INSTALLED,
            resolved_version="2.6.8", artifact_sha256="d" * 64, artifact_size=100,
        )
        desired = replace(
            _desired(
                (AddonEntry(owner_id, "enabled"),),
                PrivateOverlayRef("local_file", overlay_id="fixture-overlay"),
            ),
            config=ConfigDeclarations(structured_private_resources=(declaration,)),
        )
        owners = _Owners(desired, [_state(InstalledAddon(owner_id, False, "2.6.7"))], (owner_id,), {})
        transaction_id = "55555555-5555-4555-8555-555555555555"
        transaction = SimpleNamespace(
            transaction_id=transaction_id,
            phase=FrozenInstallPhase.CONFIGURING,
            lifecycle_stage=FrozenLifecycleStage.CONFIGURING,
            activation_hold_released=False,
            activation_hold_ids=(owner_id,),
            configuration_manifest_path="manifest.json",
            device_profile_id="dev",
            manifest_fingerprint="e" * 64,
            resolution_records=(record,),
            private_overlay_id="fixture-overlay",
            private_overlay_fingerprint="sha256:" + "5" * 64,
            private_overlay_required=True,
        )
        calls = []

        class SourceResolver:
            def resolve(self, identity):
                calls.append(identity)
                raise AssertionError("registry mismatch must fail before source lookup")

        apply_calls = []

        owners.owners = replace(
            owners.owners,
            installed_addon_source_resolver=SourceResolver(),
            private_overlay_manager=SimpleNamespace(
                prepare=lambda *args, **kwargs: SimpleNamespace(
                    metadata=SimpleNamespace(
                        overlay_id="fixture-overlay",
                        fingerprint="sha256:" + "5" * 64,
                        required=True,
                    ),
                    overlay=SimpleNamespace(resources=()),
                    resource_declarations=(declaration,),
                ),
                verify_configured_resources=lambda _prepared: True,
                apply=lambda *args, **kwargs: apply_calls.append((args, kwargs)),
            ),
        )
        fake_store = SimpleNamespace(inspect=lambda: transaction)
        request = ReconcileRequest(
            "manifest.json", "dev", install_resolutions=(record,),
            source_software_fingerprint="e" * 64,
            frozen_transaction_id=transaction_id,
        )
        with (
            patch("resources.lib.frozen_install.FrozenInstallStore", return_value=fake_store),
            patch("resources.lib.frozen_install.active_activation_hold_ids", return_value=frozenset({owner_id})),
        ):
            result = BuildManager(owners.owners).reconcile(request)
        self.assertFalse(result.success)
        self.assertEqual(result.failure.code, "PREFLIGHT_FAILED")
        self.assertEqual(calls, [])
        self.assertEqual(apply_calls, [])

    def test_enabled_held_owner_fails_before_installed_source_resolution(self):
        from resources.lib.frozen_install import FrozenInstallPhase, FrozenLifecycleStage

        owner_id = "plugin.video.redlight"
        declaration = redlight_declaration()
        record = InstallResolutionRecord(
            owner_id, "2.6.8", InstallResolution.EXACT, ResolutionState.INSTALLED,
            resolved_version="2.6.8", artifact_sha256="f" * 64, artifact_size=100,
        )
        desired = replace(
            _desired(
                (AddonEntry(owner_id, "enabled"),),
                PrivateOverlayRef("local_file", overlay_id="fixture-overlay"),
            ),
            config=ConfigDeclarations(structured_private_resources=(declaration,)),
        )
        owners = _Owners(desired, [_state(InstalledAddon(owner_id, True, "2.6.8"))], (owner_id,), {})
        transaction_id = "66666666-6666-4666-8666-666666666666"
        transaction = SimpleNamespace(
            transaction_id=transaction_id,
            phase=FrozenInstallPhase.CONFIGURING,
            lifecycle_stage=FrozenLifecycleStage.CONFIGURING,
            activation_hold_released=False,
            activation_hold_ids=(owner_id,),
            configuration_manifest_path="manifest.json",
            device_profile_id="dev",
            manifest_fingerprint="f" * 64,
            resolution_records=(record,),
            private_overlay_id="fixture-overlay",
            private_overlay_fingerprint="sha256:" + "6" * 64,
            private_overlay_required=True,
        )
        calls = []
        apply_calls = []
        owners.owners = replace(
            owners.owners,
            installed_addon_source_resolver=SimpleNamespace(
                resolve=lambda identity: calls.append(identity)
            ),
            private_overlay_manager=SimpleNamespace(
                prepare=lambda *args, **kwargs: SimpleNamespace(
                    metadata=SimpleNamespace(
                        overlay_id="fixture-overlay",
                        fingerprint="sha256:" + "6" * 64,
                        required=True,
                    ),
                    overlay=SimpleNamespace(resources=()),
                    resource_declarations=(declaration,),
                ),
                verify_configured_resources=lambda _prepared: True,
                apply=lambda *args, **kwargs: apply_calls.append((args, kwargs)),
            ),
        )
        fake_store = SimpleNamespace(inspect=lambda: transaction)
        request = ReconcileRequest(
            "manifest.json", "dev", install_resolutions=(record,),
            source_software_fingerprint="f" * 64,
            frozen_transaction_id=transaction_id,
        )
        with (
            patch("resources.lib.frozen_install.FrozenInstallStore", return_value=fake_store),
            patch("resources.lib.frozen_install.active_activation_hold_ids", return_value=frozenset({owner_id})),
        ):
            result = BuildManager(owners.owners).reconcile(request)
        self.assertFalse(result.success)
        self.assertEqual(result.failure.code, "PREFLIGHT_FAILED")
        self.assertEqual(calls, [])
        self.assertEqual(apply_calls, [])

    def test_ordinary_resource_does_not_require_installed_owner_source(self):
        declaration = replace(
            redlight_declaration(), configure_before_activation=False
        )
        desired = replace(
            _desired(
                (AddonEntry("plugin.video.redlight", "enabled"),),
                PrivateOverlayRef("local_file", overlay_id="ordinary-resource"),
            ),
            config=ConfigDeclarations(structured_private_resources=(declaration,)),
        )
        owners = _Owners(
            desired,
            [_state(InstalledAddon("plugin.video.redlight", True, "2.6.8"))],
            ("plugin.video.redlight",),
            {},
        )
        calls = []
        owners.owners = replace(
            owners.owners,
            installed_addon_source_resolver=SimpleNamespace(
                resolve=lambda identity: calls.append(identity)
            ),
            private_overlay_manager=SimpleNamespace(
                prepare=lambda *args, **kwargs: SimpleNamespace(
                    metadata=None,
                    overlay=SimpleNamespace(resources=()),
                    resource_declarations=(declaration,),
                ),
                verify_configured_resources=lambda _prepared: True,
            ),
        )
        fake_store = SimpleNamespace(inspect=lambda: None)
        with (
            patch("resources.lib.frozen_install.FrozenInstallStore", return_value=fake_store),
            patch("resources.lib.frozen_install.active_activation_hold_ids", return_value=frozenset()),
        ):
            result = BuildManager(owners.owners).preview(ReconcileRequest("manifest.json", "dev"))
        self.assertTrue(result.success)
        self.assertEqual(calls, [])

    def test_configure_exception_text_is_not_serialized(self):
        fake_secret = "BM017F_FAKE_EXCEPTION_SECRET_92f1"
        desired = replace(_desired(), config=ConfigDeclarations())
        owners = _Owners(desired, [_state()], (), {})

        class FailingConfigManager:
            def apply(self, _effective):
                raise RuntimeError(fake_secret)

        owners.owners = replace(
            owners.owners,
            config_manager=FailingConfigManager(),
        )
        with (
            patch(
                "resources.lib.frozen_install.FrozenInstallStore",
                return_value=SimpleNamespace(inspect=lambda: None),
            ),
            patch(
                "resources.lib.frozen_install.active_activation_hold_ids",
                return_value=frozenset(),
            ),
        ):
            result = BuildManager(owners.owners).reconcile(
                ReconcileRequest("manifest.json", "dev")
            )
        encoded = json.dumps(result.to_dict(), sort_keys=True)
        self.assertFalse(result.success)
        self.assertEqual(result.action_results[0].action.kind, "CONFIGURE")
        self.assertIn("ACTION_EXECUTION_FAILED", encoded)
        self.assertNotIn(fake_secret, encoded)

    def test_unheld_addon_cannot_reference_held_optional_dependency(self):
        from resources.lib.frozen_install import FrozenInstallPhase, FrozenLifecycleStage

        owner_id = "plugin.video.redlight"
        consumer_id = "plugin.video.optional.consumer"
        declaration = redlight_declaration()
        desired = replace(
            _desired(
                (AddonEntry(owner_id, "enabled"), AddonEntry(consumer_id, "enabled")),
                PrivateOverlayRef("local_file", overlay_id="fixture-overlay"),
            ),
            config=ConfigDeclarations(structured_private_resources=(declaration,)),
        )
        owners = _Owners(
            desired,
            [_state(
                InstalledAddon(owner_id, False, "2.6.8"),
                InstalledAddon(consumer_id, True, "1.0.0"),
            )],
            (owner_id, consumer_id),
            {},
        )
        metadata = PrivateOverlayMetadata(
            "fixture-overlay", "sha256:" + "4" * 64, True, True
        )

        class _PrivateOverlayManager:
            def prepare(self, *args, **kwargs):
                return SimpleNamespace(
                    metadata=metadata,
                    overlay=SimpleNamespace(resources=()),
                    resource_declarations=(declaration,),
                )

            def verify_configured_resources(self, _prepared):
                return True

        owners.owners = replace(
            owners.owners,
            private_overlay_manager=_PrivateOverlayManager(),
        )
        optional_dependency = DependencyNode(
            addon_id=owner_id,
            required_by=(consumer_id,),
            status=DependencyStatus.OPTIONAL,
            installed_version=None,
            installed_enabled=None,
            min_version_required="",
            optional=True,
        )
        owners.dependency_resolver.resolve_closure = lambda roots, **kwargs: DependencyClosure(
            root_addon_ids=tuple(roots), nodes=(optional_dependency,)
        )
        transaction_id = "44444444-4444-4444-8444-444444444444"
        transaction = SimpleNamespace(
            transaction_id=transaction_id,
            phase=FrozenInstallPhase.CONFIGURING,
            lifecycle_stage=FrozenLifecycleStage.CONFIGURING,
            activation_hold_released=False,
            activation_hold_ids=(owner_id,),
            configuration_manifest_path="manifest.json",
            device_profile_id="dev",
            manifest_fingerprint="b" * 64,
            resolution_records=(),
            private_overlay_id="fixture-overlay",
            private_overlay_fingerprint=metadata.fingerprint,
            private_overlay_required=True,
        )
        request = ReconcileRequest(
            "manifest.json", "dev",
            source_software_fingerprint="b" * 64,
            frozen_transaction_id=transaction_id,
        )
        with (
            patch("resources.lib.frozen_install.FrozenInstallStore", return_value=SimpleNamespace(inspect=lambda: transaction)),
            patch("resources.lib.frozen_install.active_activation_hold_ids", return_value=frozenset({owner_id})),
        ):
            result = BuildManager(owners.owners).preview(request)

        self.assertFalse(result.success)
        self.assertEqual(result.failure.code, "PREFLIGHT_FAILED")


if __name__ == "__main__":
    unittest.main()
