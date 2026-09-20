import tempfile
import unittest
from dataclasses import replace

from resources.lib.build_manager import (
    BuildManager,
    BuildManagerOwners,
    ReconcileRequest,
    fingerprint_resolved_build,
)
from resources.lib.dependencies import DependencyClosure
from resources.lib.inspector import InstalledAddon, KodiState
from resources.lib.manifest import AddonEntry, BuildInfo, PrivateOverlayRef
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


if __name__ == "__main__":
    unittest.main()
