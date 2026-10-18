"""Exact-version AF3 catalog compatibility, without Kodi/profile access."""
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from resources.lib.create_workflow import TrustedCaptureCatalog
from resources.lib.config import (ConfigPackageLoader, EffectiveConfiguration,
    default_packages_root)

AF3 = 'skin.arctic.fuse.3'
OLD_KEY = 'HomeSwitcher.EnableIconText'


class CaptureCatalogVersionTests(unittest.TestCase):
    def test_3312_capture_excludes_unsupported_target(self):
        spec, private, resources = TrustedCaptureCatalog().compose(
            (AF3,), AF3, False, {AF3: '3.3.12'})
        self.assertNotIn(OLD_KEY, {s.key for s in spec.settings})
        self.assertEqual(len(spec.settings), 15)
        self.assertFalse(spec.files or private or resources)

    def test_legacy_catalog_is_preserved(self):
        catalog = TrustedCaptureCatalog()
        spec, _, _ = catalog.compose((AF3,), AF3, False, {AF3: '3.2.19'})
        self.assertIn(OLD_KEY, {s.key for s in spec.settings})
        self.assertEqual(len(spec.settings), 16)

    def test_new_package_keeps_other_policy_values_and_text_mode(self):
        loader = ConfigPackageLoader(default_packages_root())
        old = loader.load_package('af3-common')
        new = loader.load_package('af3-3.3.12')
        expected = {s.key: (s.setting_type, s.value) for s in old.settings if s.key != OLD_KEY}
        self.assertEqual({s.key: (s.setting_type, s.value) for s in new.settings}, expected)
        self.assertEqual(expected['HomeSwitcher.EnableIcons'][1], False)
        self.assertEqual(new.files, ())

    def test_new_example_resolves_exact_scope(self):
        from resources.lib.manifest import load_manifest_file
        from resources.lib.resolver import resolve_manifest
        from resources.lib.af3 import validate_configuration_version
        path = Path(__file__).resolve().parents[1] / 'resources/builds/examples/af3-3.3.12.example.json'
        desired = resolve_manifest(load_manifest_file(str(path)), 'bm020a-disposable')
        effective = ConfigPackageLoader(default_packages_root()).resolve(desired.config)
        validate_configuration_version(effective, {AF3: '3.3.12'})
        self.assertEqual(len(effective.settings), 15)


def effective(package='af3-common'):
    loaded = ConfigPackageLoader(default_packages_root()).load_package(package)
    return EffectiveConfiguration(packages=(package,), settings=loaded.settings)


class VersionPreflightTests(unittest.TestCase):
    def test_legacy_16_target_is_rejected_including_false_or_captured_values(self):
        from resources.lib.af3 import AF3PolicyError, validate_configuration_version
        old = effective()
        for value in (False, True):
            for package in ('af3-common', 'captured-public'):
                config = replace(old, packages=(package,), settings=tuple(
                    replace(s, value=value) if s.key == OLD_KEY else s for s in old.settings))
                with self.subTest(value=value, package=package):
                    with self.assertRaisesRegex(AF3PolicyError, 'incompatible'):
                        validate_configuration_version(config, {AF3: '3.3.12'})

    def test_versioned_package_requires_exact_version(self):
        from resources.lib.af3 import AF3PolicyError, validate_configuration_version
        config = effective('af3-3.3.12')
        for version in (None, '', '3.2.19', '3.3.13', '3.3.12+unknown'):
            with self.subTest(version=version):
                with self.assertRaisesRegex(AF3PolicyError, 'exact target version'):
                    validate_configuration_version(config, {AF3: version})
        validate_configuration_version(config, {AF3: '3.3.12'})
        validate_configuration_version(effective(), {AF3: '3.2.19'})

    def test_reconciliation_fails_before_mutating_owners(self):
        from tests.test_build_manager import _Owners, _desired, _state
        from resources.lib.build_manager import BuildManager, ReconcileRequest
        from resources.lib.inspector import InstalledAddon
        fixture = _Owners(_desired(), [_state(InstalledAddon(AF3, True, '3.3.12'))], (), {})
        loader = Mock(); loader.resolve.return_value = effective()
        owners = replace(fixture.owners, config_loader=loader)
        result = BuildManager(owners).reconcile(ReconcileRequest('m', 'dev'))
        self.assertFalse(result.success)
        self.assertIn('incompatible', str(result.to_dict()))
        self.assertEqual(fixture.sets, [])
        self.assertEqual(fixture.dependency_installer.calls, [])

    def test_review_uses_planned_target_version_before_settings_reads(self):
        from resources.lib.plan import BuildPlanService
        from resources.lib.plan_model import SettingsPlanKind
        from resources.lib.status_model import CheckGap
        service = object.__new__(BuildPlanService)
        inspector = Mock()
        service._o = SimpleNamespace(status=SimpleNamespace(configuration_inspector=inspector))
        service._log_failure = Mock()
        gaps, material = [], {}
        result = service._settings(SimpleNamespace(config=object()), effective(), {},
            {AF3: SimpleNamespace(version='3.3.12')}, gaps, material)
        self.assertEqual(result.kind, SettingsPlanKind.UNAVAILABLE)
        self.assertIn(CheckGap.CONFIGURATION_UNAVAILABLE, gaps)
        inspector.inspect.assert_not_called()

    def test_public_library_rejects_legacy_target_without_rewriting_it(self):
        from tests.test_build_library import LibraryTests
        from resources.lib.build_library import LibraryError
        from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
        fixture = LibraryTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.raw['addons'] = [{'addon_id': AF3, 'state': 'enabled'}]
        fixture.raw['config']['managed_settings'] = [{'target': 'skin', 'addon_id': AF3, 'keys': [OLD_KEY]}]
        fixture.raw['config']['managed_files'] = []
        fixture.descriptor['settings'] = [{'target': 'skin', 'addon_id': AF3, 'key': OLD_KEY, 'type': 'bool', 'value': True}]
        fixture.descriptor['files'] = []
        node = AddonCaptureNode(AF3, '3.3.12', 'xbmc.gui.skin', True, ProvenanceStatus.MANUAL_OR_UNKNOWN)
        fixture.frozen = replace(fixture.frozen, addons=(node,))
        fixture.write_sources()
        before = fixture.manifest_path.read_bytes()
        with self.assertRaisesRegex(LibraryError, 'AF3 configuration incompatible'):
            fixture.register()
        self.assertEqual(fixture.manifest_path.read_bytes(), before)
        fixture.frozen = replace(fixture.frozen, addons=(replace(node, version='3.2.19'),))
        fixture.write_sources()
        entry = fixture.register()
        self.assertEqual(fixture.effective(entry.entry_id).settings[0].key, OLD_KEY)
        # Reproduce a 16-key-era library record admitted by the old validator,
        # then read it through the current supported source API without writes.
        fixture.raw['build']['version'] = '1.0.1'
        fixture.frozen = replace(fixture.frozen, addons=(node,))
        fixture.write_sources()
        with patch('resources.lib.af3.validate_configuration_version', return_value=None):
            prior_entry = fixture.register()
        envelope = fixture.envelope(prior_entry.entry_id)
        retained = envelope.read_bytes()
        from resources.lib.build_library import LibrarySource
        with self.assertRaisesRegex(LibraryError, 'AF3 configuration incompatible'):
            LibrarySource(str(fixture.root), prior_entry.entry_id).load()
        self.assertEqual(envelope.read_bytes(), retained)

    def test_repository_binding_checks_resolved_not_captured_version(self):
        from resources.lib import repository_preparation as prep
        from resources.lib.artifacts import validate_addon_zip
        from tests.test_repository_preparation import _zip
        node = SimpleNamespace(addon_id=AF3, version='3.2.19', system=False,
            platform_provided=False, is_absent_optional_dependency=False, desired_enabled=True)
        record = SimpleNamespace(addon_id=AF3, captured_version='3.2.19',
            desired_enabled=True, repository_id='repository.demo', resolved_version='3.3.12')
        package = _zip(AF3, '3.3.12')
        metadata = validate_addon_zip(package, expected_addon_id=AF3, expected_version='3.3.12')
        record.artifact_sha256, record.artifact_size = metadata.sha256, len(package)
        checked = SimpleNamespace(records=(record,), to_dict=lambda: {})
        store = SimpleNamespace(get_metadata=lambda _: metadata, read_bytes=lambda _: package)
        desired = SimpleNamespace(config=None, frozen_install_policies=())
        policy = SimpleNamespace(repository_fallback_allowed=True, repository_id='repository.demo')
        loader = Mock(); loader.resolve.return_value = effective()
        with patch.object(prep.PreparedRepositoryResolution, 'from_dict', return_value=checked), \
             patch.object(prep, '_binding', return_value={}), \
             patch.object(prep, 'effective_policy', return_value=policy), \
             patch.object(prep, '_trusted_repository_id', return_value='repository.demo'):
            with self.assertRaises(prep.PreparationError) as error:
                prep.bind_prepared(checked, object(), 'desk', desired,
                    SimpleNamespace(addons=(node,)), loader, store)
        self.assertEqual(error.exception.code, prep.PreparationCode.TARGET_INVALID)


if __name__ == '__main__':
    unittest.main()
