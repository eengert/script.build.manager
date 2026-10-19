"""Ordinary reconciliation preflight and mutation-boundary AF3 regressions."""
from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from resources.lib.addons import PreparedAddonInstall
from resources.lib.build_manager import BuildManager, ReconcileRequest
from resources.lib.config import ConfigurationBackend, ConfigurationManager
from resources.lib.inspector import InstalledAddon
from resources.lib.manifest import AddonEntry, ConfigDeclarations, ManagedSettingScope, SettingTargetKind
from resources.lib.restart import RestartReport, RestartRequirement
from tests.test_af3_catalog import AF3, OLD_KEY, effective
from tests.test_build_manager import _Owners, _desired, _state, _Outcome
from tests.test_repository_preparation import _zip


class MemorySettings(ConfigurationBackend):
    def __init__(self, config):
        self.values = {(s.addon_id, s.key): s.value for s in config.settings}
        first = config.settings[0]
        self.values[(first.addon_id, first.key)] = not first.value
        self.writes = []

    def get_skin_setting(self, owner, key, kind):
        return self.values[(owner, key)]

    get_setting = get_skin_setting

    def set_skin_setting(self, owner, key, kind, value):
        self.writes.append((owner, key))
        self.values[(owner, key)] = value

    set_setting = set_skin_setting


def scenario(package='af3-3.3.12', before=None, after='3.3.12', *, manager_class=BuildManager,
             install_version='3.3.12', restart=False, resolve=True, plan_upgrade=False, real_installers=False, config=None):
    config = effective(package) if config is None else config
    declared = ConfigDeclarations(packages=(package,), managed_settings=(
        ManagedSettingScope(config.settings[0].addon_id, tuple(s.key for s in config.settings),
                            SettingTargetKind(config.settings[0].target_kind.value)),))
    desired = replace(_desired((AddonEntry(AF3, 'enabled'),)), config=declared)
    states = [_state(*(() if before is None else (InstalledAddon(AF3, True, before),))),
              _state(*(() if after is None else (InstalledAddon(AF3, True, after),)))]
    report = RestartReport(RestartRequirement.KODI_RESTART, 1, 0) if restart else RestartReport()
    fixture = _Owners(desired, states, (AF3,), {AF3: _Outcome(changed=True, report=report)})
    fixture.dependency_installer.prepare_package = Mock(return_value=(
        PreparedAddonInstall(AF3, install_version, _zip(AF3, install_version)) if resolve else None))
    if real_installers:
        from resources.lib.addons import AddonManager, InstalledAddonInfo
        from resources.lib.dependencies import DependencyAwareInstaller, DependencyResolver
        from tests.test_addon_manager import FakeAddonBackend
        from tests.test_dependencies import FakeDependencyBackend, _xml
        backend = FakeAddonBackend(
            installed={} if before is None else {AF3: InstalledAddonInfo(AF3, True, before)},
            poll_result=InstalledAddonInfo(AF3, True, install_version))
        backend.prepare_package = fixture.dependency_installer.prepare_package
        backend.invoke_prepared_install = Mock()
        resolver = DependencyResolver(FakeDependencyBackend(addon_xmls={AF3: _xml(AF3, install_version)}))
        fixture.dependency_installer = DependencyAwareInstaller(resolver, AddonManager(backend))
        fixture.owners = replace(fixture.owners, dependency_resolver=resolver,
                                dependency_installer=fixture.dependency_installer)
    settings = MemorySettings(config)
    fixture.owners = replace(fixture.owners, config_loader=SimpleNamespace(resolve=lambda _: config),
                            config_manager=ConfigurationManager(settings))
    with ExitStack() as stack:
        stack.enter_context(patch('resources.lib.capture_lifecycle.require_no_capture'))
        stack.enter_context(patch('resources.lib.frozen_install.FrozenInstallStore',
            return_value=SimpleNamespace(inspect=lambda: None)))
        stack.enter_context(patch('resources.lib.frozen_install.active_activation_hold_ids', return_value=frozenset()))
        if plan_upgrade:
            from resources.lib.planner import plan_changes, Plan, PlanAction, INSTALL_ADDON
            plan = plan_changes(desired, states[0])
            # This owner seam represents an otherwise-supported explicit upgrade.
            # Production AddonManager still refuses replacement of existing bytes.
            stack.enter_context(patch('resources.lib.build_manager.plan_changes', return_value=Plan((
                PlanAction(INSTALL_ADDON, AF3, 'enabled', 'installed', 'verified upgrade'), *plan.actions))))
        result = manager_class(fixture.owners).reconcile(ReconcileRequest('fixture', 'dev'))
    return result, fixture, settings


class AF3ReconciliationSafety(unittest.TestCase):
    def test_absent_legacy_target_rejected_before_all_mutation(self):
        result, f, settings = scenario('af3-common')
        self.assertFalse(result.success)
        self.assertEqual(result.failure.code, 'AF3_CONFIGURATION_INCOMPATIBLE')
        self.assertFalse(f.dependency_installer.calls or f.sets or settings.writes)

    def test_absent_supported_catalog_installs_and_configures_in_one_run(self):
        result, f, settings = scenario()
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(len(f.dependency_installer.calls), 1)
        prepared = f.dependency_installer.calls[0][1]['prepared_package']
        self.assertEqual(prepared.version, '3.3.12')
        self.assertTrue(settings.writes)

    def test_ordinary_addon_and_dependency_owners_consume_prepared_bytes(self):
        result, f, settings = scenario(real_installers=True)
        self.assertTrue(result.success, result.to_dict())
        backend = f.dependency_installer._addon_manager._backend
        backend.invoke_prepared_install.assert_called_once_with(backend.prepare_package.return_value)
        self.assertTrue(settings.writes)

    def test_actual_version_rechecked_after_install(self):
        for after in ('3.2.19', '3.3.13', '', None):
            with self.subTest(after=after):
                result, f, settings = scenario(after=after)
                self.assertFalse(result.success)
                self.assertEqual(len(f.dependency_installer.calls), 1)
                self.assertFalse(settings.writes)
                self.assertIn('AF3_ACTUAL_VERSION_MISMATCH', str(result.to_dict()))

    def test_synthetic_install_plan_checks_final_not_old_version(self):
        result, f, settings = scenario(before='3.2.19', plan_upgrade=True)
        self.assertTrue(result.success, result.to_dict())
        self.assertTrue(settings.writes)

    def test_synthetic_legacy_install_plan_denied_before_install(self):
        result, f, settings = scenario('af3-common', before='3.2.19', plan_upgrade=True)
        self.assertEqual(result.failure.code, 'AF3_CONFIGURATION_INCOMPATIBLE')
        self.assertFalse(f.dependency_installer.calls or settings.writes)

    def test_installed_3312_resume_configures_full_scope_without_reinstall(self):
        # Re-enter reconciliation with AF3 already installed. This offline
        # installed-state input makes no claim that a restart was observed.
        result, f, settings = scenario(before='3.3.12', real_installers=True)
        self.assertTrue(result.success, result.to_dict())
        config = effective('af3-3.3.12')
        self.assertEqual(len(config.settings), 15)
        self.assertEqual(settings.values, {(s.addon_id, s.key): s.value for s in config.settings})
        self.assertTrue(settings.writes)
        backend = f.dependency_installer._addon_manager._backend
        backend.prepare_package.assert_not_called()
        backend.invoke_prepared_install.assert_not_called()
        self.assertFalse(result.restart_report.requires_restart)

    def test_production_installer_refuses_unsupported_3219_replacement(self):
        # The ordinary production planner does not authorize replacement.
        result, f, settings = scenario(before='3.2.19', after='3.2.19', real_installers=True)
        self.assertFalse(result.success)
        self.assertEqual(result.failure.code, 'AF3_CONFIGURATION_INCOMPATIBLE')
        self.assertFalse(settings.writes)
        f.dependency_installer._addon_manager._backend.invoke_prepared_install.assert_not_called()
        # Force the requested replacement action, but retain production installer
        # admission and the actually installed old version through CONFIGURE.
        result, f, settings = scenario(before='3.2.19', after='3.2.19',
                                      plan_upgrade=True, real_installers=True)
        self.assertFalse(result.success)
        self.assertIn('AF3_ACTUAL_VERSION_MISMATCH', str(result.to_dict()))
        self.assertFalse(settings.writes)
        backend = f.dependency_installer._addon_manager._backend
        backend.invoke_prepared_install.assert_not_called()
        self.assertEqual(backend.get_addon_details(AF3).version, '3.2.19')

    def test_unknown_prepared_identity_denied_before_install(self):
        result, f, settings = scenario(resolve=False)
        self.assertEqual(result.failure.code, 'AF3_TARGET_VERSION_UNVERIFIED')
        self.assertFalse(f.dependency_installer.calls or settings.writes)

    def test_restart_required_install_cannot_reach_configuration(self):
        result, f, settings = scenario(restart=True)
        self.assertFalse(result.success)
        self.assertTrue(result.restart_report.requires_restart)
        self.assertEqual(result.failure.code, 'AF3_CONFIGURATION_RESTART_REQUIRED')
        self.assertFalse(settings.writes)

    def test_all_target_kinds_cannot_bypass_key_exclusion(self):
        from resources.lib.manifest import validate_manifest
        from resources.lib.config import _parse_descriptor, EffectiveConfiguration
        from resources.lib.af3 import validate_configuration_version, AF3PolicyError
        for target in (None, 'addon', 'skin'):
            row = dict(addon_id=AF3, key=OLD_KEY, type='bool', value=False)
            if target is not None:
                row['target'] = target
            pkg = _parse_descriptor(dict(schema_version=1, id='test', settings=[row]),
                package_id='test', package_dir='')
            with self.assertRaisesRegex(AF3PolicyError, 'incompatible'):
                validate_configuration_version(EffectiveConfiguration(settings=pkg.settings), {AF3:'3.3.12'})
            unrelated = replace(pkg.settings[0], addon_id='plugin.other')
            validate_configuration_version(EffectiveConfiguration(settings=(unrelated,)), {AF3:'3.3.12'})

    def test_mismatch_denies_public_and_private_writers(self):
        f = _Owners(_desired(), [_state(InstalledAddon(AF3, True, '3.2.19'))], (), {})
        public, private = Mock(), Mock()
        owners = replace(f.owners, config_manager=public, private_overlay_manager=private)
        from resources.lib.planner import PlanAction, CONFIGURE
        result = BuildManager(owners)._dispatch_action(PlanAction(CONFIGURE, '', '', '', ''),
            _desired(), effective('af3-3.3.12'), frozenset(), object(), None, '3.3.12')
        self.assertFalse(result.succeeded)
        public.apply.assert_not_called(); private.apply.assert_not_called()


if __name__ == '__main__':
    unittest.main()
