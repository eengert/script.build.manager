"""AF3 spelling is a validation boundary, never a target alias."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from resources.lib.af3 import (AF3PolicyError, has_configuration,
    validate_configuration_version, validate_skin_settings)
from resources.lib.config import (ConfigPackageLoader, ConfigPackageError,
    EffectiveConfiguration, _parse_descriptor)
from resources.lib.manifest import ConfigDeclarations, ManagedSettingScope, SettingTargetKind
from tests.test_af3_catalog import AF3
from tests.test_af3_reconciliation_safety import scenario

VARIANTS = ('Skin.Arctic.Fuse.3', AF3.upper(), 'skin.arctic.Fuse.3')


def configuration(owner, target, both=False):
    rows = [dict(addon_id=owner, key='HomeSwitcher.EnableIcons', type='bool', value=True)]
    if both:
        rows.append(dict(addon_id=owner, key='HomeSwitcher.EnableIconText', type='bool', value=True))
    if target is not None:
        for row in rows:
            row['target'] = target
    pkg = _parse_descriptor(dict(schema_version=1, id='fixture', settings=rows),
                            package_id='fixture', package_dir='')
    return EffectiveConfiguration(packages=('fixture',), settings=pkg.settings)


class AF3IdentityTests(unittest.TestCase):
    def test_case_variant_is_protected_and_refused_for_all_target_kinds(self):
        for owner in VARIANTS:
            for target in ('skin', 'addon', None):
                config = configuration(owner, target)
                with self.subTest(owner=owner, target=target):
                    self.assertTrue(has_configuration(config))
                    for version in ('3.3.12', '3.2.19', None):
                        with self.assertRaises(AF3PolicyError):
                            validate_configuration_version(config, {AF3: version})
                    with self.assertRaises(AF3PolicyError):
                        validate_skin_settings({s.target: s for s in config.settings})
                    self.assertEqual(config.settings[0].addon_id, owner)

    def test_variant_and_mixed_owner_modes_cannot_evade_mutual_exclusion(self):
        for target in ('skin', 'addon', None):
            for owner in VARIANTS:
                config = configuration(owner, target, both=True)
                for mixed in (False, True):
                    rows = config.settings if not mixed else (
                        replace(config.settings[0], addon_id=AF3), config.settings[1])
                    with self.subTest(target=target, owner=owner, mixed=mixed):
                        with self.assertRaises(AF3PolicyError):
                            validate_skin_settings({s.target: s for s in rows})
        canonical = configuration(AF3, 'skin', both=True)
        with self.assertRaisesRegex(AF3PolicyError, 'mutually exclusive'):
            validate_skin_settings({s.target: s for s in canonical.settings})

    def test_reconcile_refuses_variants_before_install_or_write(self):
        for before in (None, '3.3.12'):
            for target in ('skin', 'addon', None):
                for owner in VARIANTS:
                    with self.subTest(before=before, target=target, owner=owner):
                        result, fixture, settings = scenario(package='fixture', before=before,
                            config=configuration(owner, target))
                        self.assertFalse(result.success)
                        self.assertEqual(result.failure.code, 'AF3_CONFIGURATION_INCOMPATIBLE')
                        self.assertFalse(fixture.dependency_installer.calls or fixture.sets or settings.writes)

    def test_actual_configure_gate_refuses_variant_before_public_private_writes(self):
        from resources.lib.build_manager import BuildManager
        from resources.lib.planner import PlanAction, CONFIGURE
        from tests.test_build_manager import _Owners, _desired, _state
        from resources.lib.inspector import InstalledAddon
        for target in ('skin', 'addon', None):
            fixture = _Owners(_desired(), [_state(InstalledAddon(AF3, True, '3.3.12'))], (), {})
            public, private = Mock(), Mock()
            manager = BuildManager(replace(fixture.owners, config_manager=public, private_overlay_manager=private))
            result = manager._dispatch_action(PlanAction(CONFIGURE, '', '', '', ''), _desired(),
                configuration(VARIANTS[0], target), frozenset(), SimpleNamespace(resource_declarations=()), None, '3.3.12')
            self.assertFalse(result.succeeded)
            self.assertIn('AF3_CONFIGURATION_INCOMPATIBLE', str(result))
            public.apply.assert_not_called()
            private.apply.assert_not_called()

    def test_real_loader_declared_variant_refused_without_rewriting_sources(self):
        for target in ('skin', 'addon', None):
            for owner in (VARIANTS[0], AF3, 'Plugin.Other'):
                with self.subTest(target=target, owner=owner), tempfile.TemporaryDirectory() as tmp:
                    config = configuration(owner, target)
                    folder = Path(tmp) / 'fixture'; folder.mkdir()
                    row = dict(addon_id=owner, key=config.settings[0].key, type='bool', value=True)
                    if target is not None:
                        row['target'] = target
                    source = folder / 'package.json'
                    source.write_text(json.dumps(dict(schema_version=1, id='fixture', settings=[row])))
                    retained = source.read_bytes()
                    declarations = ConfigDeclarations(packages=('fixture',), managed_settings=(
                        ManagedSettingScope(owner, (row['key'],), SettingTargetKind(target or 'addon')),))
                    loader = ConfigPackageLoader(tmp)
                    if owner in VARIANTS:
                        with self.assertRaises(ConfigPackageError):
                            loader.resolve(declarations)
                    else:
                        resolved = loader.resolve(declarations)
                        self.assertEqual(resolved.settings[0].addon_id, owner)
                    self.assertEqual(source.read_bytes(), retained)

    def test_canonical_and_unrelated_positive_controls(self):
        for target in ('skin', 'addon', None):
            for owner in (AF3, 'Plugin.Other', 'skin.arctic.fuse.30'):
                config = configuration(owner, target)
                validate_configuration_version(config, {AF3: '3.3.12'})
                validate_skin_settings({s.target: s for s in config.settings})
                result, fixture, settings = scenario(package='fixture', before='3.3.12', config=config)
                self.assertTrue(result.success, result.to_dict())
                self.assertTrue(settings.writes)
                self.assertFalse(fixture.dependency_installer.calls)
