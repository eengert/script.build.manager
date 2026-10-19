"""Synthetic reconciliation through real public loader and private overlay owners."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from resources.lib.addons import PreparedAddonInstall
from resources.lib.af3 import AF3PolicyError
from resources.lib.build_manager import BuildManager, ReconcileRequest
from resources.lib.config import ConfigPackageLoader, ConfigurationManager, EffectiveConfiguration
from resources.lib.inspector import InstalledAddon
from resources.lib.manifest import (AddonEntry, ConfigDeclarations, PrivateOverlayRef,
    PrivateSettingDeclaration, SettingTargetKind)
from resources.lib.private_overlay import (PrivateOverlay, PrivateOverlayEntry,
    PrivateOverlayManager, PrivateOverlayStore, PreparedPrivateOverlay, PrivateOverlayMetadata)
from resources.lib.config import ConfigSettingType
from tests.test_af3_catalog import AF3, OLD_KEY
from tests.test_af3_identity import configuration
from tests.test_af3_reconciliation_safety import scenario
from tests.test_build_manager import _Owners, _desired, _state, _Outcome
from tests.test_private_overlay import FakeBackend
from tests.test_repository_preparation import _zip


def private_scenario(owner=AF3, before='3.3.12', planned='3.3.12', overlay=True,
                     required=True, public=None, declarations=True):
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        declaration = PrivateSettingDeclaration(owner, OLD_KEY, 'bool', required,
                                               target_kind=SettingTargetKind.SKIN)
        config = ConfigDeclarations(private_settings=(declaration,) if declarations else ())
        if owner == AF3 and declarations:
            from resources.lib.manifest import _parse_config
            config = _parse_config({'private_settings': [dict(addon_id=owner, key=OLD_KEY,
                type='bool', target='skin', required=required)]}, label='config')
        desired = replace(_desired((AddonEntry(AF3, 'enabled'),),
            PrivateOverlayRef('local_file', overlay_id='synthetic', required=required)), config=config)
        state = _state(*(() if before is None else (InstalledAddon(AF3, True, before),)))
        f = _Owners(desired, [state, _state(InstalledAddon(AF3, True, planned))],
                    (AF3,), {AF3: _Outcome(changed=True)})
        f.dependency_installer.prepare_package = Mock(return_value=
            PreparedAddonInstall(AF3, planned, _zip(AF3, planned)))
        backend = FakeBackend({(owner, OLD_KEY): False})
        backend.get_skin_setting = backend.get_setting
        backend.set_skin_setting = backend.set_setting
        cm = ConfigurationManager(backend)
        store = PrivateOverlayStore(Path(tmp)/'profile')
        if overlay:
            store.save(PrivateOverlay('synthetic', desired.build.id, (
                PrivateOverlayEntry(owner, OLD_KEY, ConfigSettingType.BOOL, True,
                                    target_kind=SettingTargetKind.SKIN),)))
        pm = PrivateOverlayManager(cm, store=store)
        loader = ConfigPackageLoader(tmp) if public is None else SimpleNamespace(resolve=lambda _: public)
        f.owners = replace(f.owners, config_loader=loader, config_manager=cm, private_overlay_manager=pm)
        stack.enter_context(patch('resources.lib.capture_lifecycle.require_no_capture'))
        stack.enter_context(patch('resources.lib.frozen_install.FrozenInstallStore',
            return_value=SimpleNamespace(inspect=lambda: None)))
        stack.enter_context(patch('resources.lib.frozen_install.active_activation_hold_ids', return_value=frozenset()))
        result = BuildManager(f.owners).reconcile(ReconcileRequest('fixture', 'dev'))
        return result, f, backend


class AF3PrivatePolicyTests(unittest.TestCase):
    def test_desired_addon_identity_refused_at_preflight_before_planned_install(self):
        from resources.lib.build_manager import ReconcilePhase
        from resources.lib.planner import INSTALL_ADDON, plan_changes
        for owner in (AF3+'\n', AF3.upper()):
            with self.subTest(owner=repr(owner)), ExitStack() as stack:
                desired = _desired((AddonEntry(owner, 'enabled'),))
                actual = _state()
                planned = plan_changes(desired, actual)
                self.assertTrue(any(a.kind == INSTALL_ADDON and a.addon_id == owner
                                    for a in planned.actions))
                f = _Owners(desired, [actual, actual], (owner,),
                            {owner: _Outcome(changed=True)})
                public, private = Mock(), Mock()
                f.owners = replace(f.owners, config_manager=public,
                                   private_overlay_manager=private)
                stack.enter_context(patch('resources.lib.capture_lifecycle.require_no_capture'))
                stack.enter_context(patch('resources.lib.frozen_install.FrozenInstallStore',
                    return_value=SimpleNamespace(inspect=lambda: None)))
                stack.enter_context(patch('resources.lib.frozen_install.active_activation_hold_ids',
                                          return_value=frozenset()))
                result = BuildManager(f.owners).reconcile(ReconcileRequest('fixture', 'dev'))
                self.assertFalse(result.success)
                self.assertEqual(result.failure.phase, ReconcilePhase.PREFLIGHT)
                self.assertEqual(result.failure.code, 'AF3_CONFIGURATION_INCOMPATIBLE')
                self.assertEqual(result.action_results, ())
                self.assertEqual(f.dependency_installer.calls, [])
                self.assertEqual(f.sets, [])
                public.apply.assert_not_called()
                private.apply.assert_not_called()

    def test_plan_private_3312_admission_is_unavailable(self):
        from resources.lib.plan import BuildPlanService
        from resources.lib.plan_model import SettingsPlanKind
        from resources.lib.status_model import CheckGap
        from tests.test_plan import PlanHarness, SKIN_TYPE
        h = PlanHarness(self, with_private=False, with_resource=False)
        h.set_graph(extra=((AF3, '3.3.12', SKIN_TYPE, ()),))
        declaration = PrivateSettingDeclaration(AF3, OLD_KEY, 'bool', False,
                                                target_kind=SettingTargetKind.SKIN)
        h.desired = replace(h.desired, config=replace(h.desired.config,
                            private_settings=(declaration,)))
        service = h.plan_service()
        original = BuildPlanService._settings
        reached = []

        def record_settings(service, desired, effective, actual_map, final_map, gaps, material):
            reached.append((final_map[AF3].version, desired.config.private_settings))
            return original(service, desired, effective, actual_map, final_map, gaps, material)

        with patch.object(BuildPlanService, '_settings', record_settings), h.instrumented():
            plan = service.preview(h.plan_target())
        h.assert_untouched()
        self.assertEqual(reached, [('3.3.12', (declaration,))])
        self.assertEqual(plan.blockers, ())
        self.assertEqual(plan.settings.kind, SettingsPlanKind.UNAVAILABLE)
        self.assertIn(CheckGap.AF3_CONFIGURATION_INCOMPATIBLE, plan.gaps)

    def test_rb1_newline_reconcile_zero_mutations(self):
        result, f, settings = scenario(package='fixture', before=None,
                                      config=configuration(AF3+'\n', 'skin'))
        self.assertFalse(result.success)
        self.assertFalse(f.dependency_installer.calls or f.sets or settings.writes)

    def test_rb2_private_only_zero_mutations(self):
        result, f, backend = private_scenario()
        self.assertFalse(result.success)
        self.assertFalse(f.dependency_installer.calls or f.sets or backend.writes)

    def test_private_preflight_matrix(self):
        for before in (None, '3.3.12', ''):
            for overlay, required in ((True, True), (True, False), (False, False)):
                for mixed in (False, True):
                    with self.subTest(before=before, overlay=overlay, required=required, mixed=mixed):
                        public = configuration(AF3, 'skin') if mixed else None
                        r, f, b = private_scenario(before=before, overlay=overlay,
                                                  required=required, public=public)
                        self.assertFalse(r.success)
                        self.assertFalse(f.dependency_installer.calls or f.sets or b.writes)

    def test_noncanonical_private_declarations_without_overlay(self):
        for owner in (AF3.upper(), AF3+'\n', AF3+'\r\n', AF3.upper()+'\n', AF3+'\t', ' '+AF3):
            with self.subTest(owner=repr(owner)):
                r, f, b = private_scenario(owner, before=None, overlay=False, required=False)
                self.assertFalse(r.success)
                self.assertFalse(f.dependency_installer.calls or f.sets or b.writes)

    def test_actual_configure_checks_declarations_and_prepared_entries(self):
        from resources.lib.planner import CONFIGURE, PlanAction
        for owner in (AF3, AF3.upper(), AF3+'\n', AF3+'\r\n'):
            declaration = PrivateSettingDeclaration(owner, OLD_KEY, 'bool')
            for source in ('desired', 'prepared', 'entry'):
                with self.subTest(owner=repr(owner), source=source):
                    desired = replace(_desired(), config=ConfigDeclarations(
                        private_settings=(declaration,) if source == 'desired' else ()))
                    prepared = PreparedPrivateOverlay(
                        SimpleNamespace(entries=(declaration,)) if source == 'entry' else None,
                        None, (declaration,) if source == 'prepared' else ())
                    f = _Owners(desired, [_state(InstalledAddon(AF3, True, '3.3.12'))], (), {})
                    public, private = Mock(), Mock()
                    owners = replace(f.owners, config_manager=public, private_overlay_manager=private)
                    r = BuildManager(owners)._dispatch_action(PlanAction(CONFIGURE, '', '', '', ''),
                        desired, EffectiveConfiguration(), frozenset(), prepared, None, '3.3.12')
                    self.assertFalse(r.succeeded)
                    public.apply.assert_not_called()
                    private.apply.assert_not_called()

    def test_direct_private_apis_fail_closed_before_any_write(self):
        for owner in (AF3, AF3.upper(), AF3+'\n', AF3+'\r\n', AF3+'\t'):
            setting = replace(configuration(AF3, 'skin').settings[0], addon_id=owner)
            declaration = PrivateSettingDeclaration(owner, setting.key, 'bool')
            for versions in (None, {}, {AF3: ''}, {AF3: '3.3.12'}):
                backend = FakeBackend()
                cm = ConfigurationManager(backend)
                delegated = Mock(wraps=cm)
                pm = PrivateOverlayManager(delegated)
                for prepared in (PreparedPrivateOverlay(None, None, (declaration,)),
                    PreparedPrivateOverlay(
                        overlay := PrivateOverlay('synthetic', 'test-build', (
                            PrivateOverlayEntry(owner, setting.key, setting.setting_type,
                                                True, setting.target_kind),)),
                        PrivateOverlayMetadata(overlay.overlay_id, overlay.fingerprint, True, True))):
                    with self.subTest(owner=repr(owner), versions=versions), self.assertRaises(AF3PolicyError):
                        pm.apply(prepared, target_versions=versions)
                    delegated.apply_settings.assert_not_called()
                with self.assertRaises(AF3PolicyError):
                    cm.apply_settings((setting,), effective_identity='synthetic', target_versions=versions)
                self.assertEqual(backend.writes, [])

    def test_public_programmatic_whitespace_never_writes(self):
        for owner in (AF3+'\r\n', AF3+' ', AF3+'\t', '\t'+AF3, AF3.upper()+'\r\n'):
            config = configuration(AF3, 'skin')
            config = replace(config, settings=(replace(config.settings[0], addon_id=owner),))
            for before in (None, '3.3.12'):
                r, f, b = scenario(package='fixture', before=before, config=config)
                self.assertFalse(r.success)
                self.assertFalse(f.dependency_installer.calls or f.sets or b.writes)
            backend = FakeBackend()
            with self.assertRaises(AF3PolicyError):
                ConfigurationManager(backend).apply(config)
            self.assertEqual(backend.writes, [])

    def test_legacy_and_unrelated_private_workflows_remain_supported(self):
        for owner, before in ((AF3, '3.2.19'), ('plugin.fixture', '3.3.12'),
                              ('skin.arctic.fuse.30', '3.3.12')):
            r, f, b = private_scenario(owner, before=before, planned=before)
            self.assertTrue(r.success, r.to_dict())
            self.assertEqual(b.writes, [(owner, OLD_KEY)])
            self.assertFalse(f.dependency_installer.calls)

    def test_manifest_newline_declarations_rejected_through_reconciliation(self):
        from resources.lib.manifest import _parse_config
        from resources.lib.af3 import validate_configuration_version
        # Existing regex match accepts terminal LF; fullmatch would reject it.
        # Keep global Kodi identity policy unchanged and enforce AF3 locally.
        for private in (False, True):
            row = dict(addon_id=AF3+'\n', target='skin')
            row.update(dict(key=OLD_KEY, type='bool') if private else dict(keys=[OLD_KEY]))
            parsed = _parse_config({'private_settings' if private else 'managed_settings': [row]}, label='config')
            if private:
                with self.assertRaises(AF3PolicyError):
                    validate_configuration_version(EffectiveConfiguration(), {AF3: '3.3.12'}, parsed.private_settings)
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    folder = Path(tmp)/'fixture'; folder.mkdir()
                    import json
                    (folder/'package.json').write_text(json.dumps(dict(schema_version=1,id='fixture',settings=[
                        dict(addon_id=AF3+'\n',target='skin',key=OLD_KEY,type='bool',value=True)])))
                    from resources.lib.config import ConfigPackageError
                    with self.assertRaises(ConfigPackageError):
                        ConfigPackageLoader(tmp).resolve(replace(parsed, packages=('fixture',)))

    def test_private_planned_final_version_and_conflicting_evidence(self):
        from resources.lib.planner import Plan, PlanAction, INSTALL_ADDON
        from resources.lib.af3 import AF3TargetVersionError
        declaration = PrivateSettingDeclaration(AF3, OLD_KEY, 'bool')
        actual = _state(InstalledAddon(AF3, True, '3.2.19'))
        f = _Owners(_desired(), [actual], (), {})
        plan = Plan((PlanAction(INSTALL_ADDON, AF3, '', '', ''),))
        manager = BuildManager(f.owners)
        for version in ('3.3.12', '', 'unknown'):
            f.dependency_installer.prepare_package = Mock(return_value=PreparedAddonInstall(AF3, version, _zip(AF3, version)) if version == '3.3.12' else None)
            with self.subTest(version=version), self.assertRaises(AF3PolicyError):
                manager._prepare_af3(EffectiveConfiguration(), actual, plan,
                    ReconcileRequest('fixture', 'dev'), None, (declaration,))
            self.assertFalse(f.dependency_installer.calls or f.sets)
        f.dependency_installer.prepare_package = Mock(return_value=PreparedAddonInstall(AF3, '3.2.19', _zip(AF3, '3.2.19')))
        frozen = SimpleNamespace(addons=(SimpleNamespace(addon_id=AF3, version='3.3.12'),))
        with self.assertRaises(AF3TargetVersionError):
            manager._prepare_af3(EffectiveConfiguration(), actual, plan,
                ReconcileRequest('fixture', 'dev'), frozen, (declaration,))
        duplicate = _state(InstalledAddon(AF3, True, '3.2.19'), InstalledAddon(AF3, True, '3.3.12'))
        with self.assertRaises(AF3TargetVersionError):
            manager._prepare_af3(EffectiveConfiguration(), duplicate, plan,
                ReconcileRequest('fixture', 'dev'), None, (declaration,))

    def test_prepared_entries_are_audited_at_preflight(self):
        from resources.lib.planner import Plan
        for owner in (AF3, AF3+'\n', AF3.upper()):
            f = _Owners(_desired(), [], (), {})
            entry = PrivateSettingDeclaration(owner, OLD_KEY, 'bool')
            with self.assertRaises(AF3PolicyError):
                BuildManager(f.owners)._prepare_af3(EffectiveConfiguration(),
                    _state(InstalledAddon(AF3, True, '3.3.12')), Plan(()),
                    ReconcileRequest('fixture', 'dev'), None, (),
                    PreparedPrivateOverlay(SimpleNamespace(entries=(entry,)), None))
            self.assertFalse(f.dependency_installer.calls or f.sets)

    def test_absent_private_manager_gate(self):
        cm = Mock()
        prepared = PreparedPrivateOverlay(None, None, (PrivateSettingDeclaration(AF3, OLD_KEY, 'bool'),))
        with self.assertRaises(AF3PolicyError):
            PrivateOverlayManager(cm).apply(prepared, target_versions={AF3: '3.3.12'})
        cm.apply_settings.assert_not_called()
