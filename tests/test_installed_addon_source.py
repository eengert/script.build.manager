"""Path-safety tests for BM-017F verified installed add-on sources."""

import tempfile
import unittest
from pathlib import Path

from resources.lib.installed_addon_source import (
    InstalledAddonSourceError,
    InstalledAddonSourceResolver,
    ManagedAddonSourceIdentity,
    PrivateResourceOwnerContext,
)


OWNER_ID = "plugin.video.redlight"
VERSION = "2.6.8"
TRANSACTION_ID = "11111111-1111-4111-8111-111111111111"
MANIFEST_FINGERPRINT = "a" * 64
ARTIFACT_SHA256 = "64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927"


class InstalledAddonSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "home" / "addons"
        self.root.mkdir(parents=True)
        self.installed = self.root / OWNER_ID
        self.installed.mkdir()
        self._write_addon_xml(OWNER_ID, VERSION)
        self.identity = ManagedAddonSourceIdentity(
            OWNER_ID,
            VERSION,
            ARTIFACT_SHA256,
            1_261_957,
            TRANSACTION_ID,
            MANIFEST_FINGERPRINT,
        )
        self.resolver = InstalledAddonSourceResolver(lambda: self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_addon_xml(self, addon_id, version):
        (self.installed / "addon.xml").write_text(
            f'<addon id="{addon_id}" version="{version}" name="fixture"/>',
            encoding="utf-8",
        )

    def test_exact_held_owner_source_is_bound_to_frozen_artifact_identity(self):
        source = self.resolver.resolve(self.identity)
        context = PrivateResourceOwnerContext(
            OWNER_ID, VERSION, VERSION, False, True, source
        )
        self.assertTrue(source.verified)
        self.assertEqual(source.installed_root, self.installed.resolve())
        self.assertEqual(source.artifact_sha256, ARTIFACT_SHA256)
        self.assertEqual(source.artifact_size, 1_261_957)
        self.assertTrue(context.matches(OWNER_ID, VERSION))
        self.assertEqual(
            source.safe_dict()["frozen_transaction_id"], TRANSACTION_ID
        )

    def test_addon_xml_id_mismatch_fails_closed(self):
        self._write_addon_xml("plugin.video.other", VERSION)
        with self.assertRaisesRegex(InstalledAddonSourceError, "ID does not match"):
            self.resolver.resolve(self.identity)

    def test_addon_xml_version_mismatch_fails_closed(self):
        self._write_addon_xml(OWNER_ID, "2.6.7")
        with self.assertRaisesRegex(InstalledAddonSourceError, "version does not match"):
            self.resolver.resolve(self.identity)

    def test_source_symlink_outside_expected_kodi_addons_root_fails_closed(self):
        outside = Path(self.tmp.name) / "outside" / OWNER_ID
        outside.mkdir(parents=True)
        (outside / "addon.xml").write_text(
            f'<addon id="{OWNER_ID}" version="{VERSION}"/>', encoding="utf-8"
        )
        self.installed.rename(self.root / "saved")
        self.installed.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(InstalledAddonSourceError, "outside Kodi"):
            self.resolver.resolve(self.identity)

    def test_missing_addon_xml_fails_closed(self):
        (self.installed / "addon.xml").unlink()
        with self.assertRaises(InstalledAddonSourceError) as caught:
            self.resolver.resolve(self.identity)
        self.assertEqual(caught.exception.code, "INSTALLED_ADDON_XML_INVALID")

    def test_missing_installed_root_fails_closed(self):
        self.installed.rename(self.root / "saved")
        with self.assertRaises(InstalledAddonSourceError) as caught:
            self.resolver.resolve(self.identity)
        self.assertEqual(caught.exception.code, "INSTALLED_ADDON_SOURCE_MISSING")

    def test_revalidation_detects_source_metadata_change(self):
        source = self.resolver.resolve(self.identity)
        self._write_addon_xml(OWNER_ID, "2.6.7")
        with self.assertRaises(InstalledAddonSourceError):
            source.revalidate()

    def test_manifest_cannot_supply_an_arbitrary_source_path(self):
        self.assertNotIn("path", ManagedAddonSourceIdentity.__dataclass_fields__)
        source = self.resolver.resolve(self.identity)
        self.assertEqual(source.installed_root.parent, self.root.resolve())

    def _write_python_module_metadata(self, library="resources/lib/"):
        python_root = self.installed / "resources" / "lib"
        python_root.mkdir(parents=True, exist_ok=True)
        (self.installed / "addon.xml").write_text(
            f'<addon id="{OWNER_ID}" version="{VERSION}">'
            f'<extension point="xbmc.python.module" library="{library}"/>'
            '</addon>',
            encoding="utf-8",
        )

    def test_red_light_import_root_is_verified_resources_lib_not_addon_root(self):
        self._write_python_module_metadata()
        source = self.resolver.resolve(self.identity)
        import_root = source.resources_lib_root()
        (import_root / "caches").mkdir()
        (import_root / "modules").mkdir()
        (import_root / "caches" / "base_cache.py").write_text("", encoding="utf-8")
        (import_root / "modules" / "kodi_utils.py").write_text("", encoding="utf-8")

        self.assertEqual(import_root, (self.installed / "resources" / "lib").resolve())
        self.assertNotEqual(import_root, self.installed.resolve())
        self.assertFalse((self.installed / "caches").exists())
        self.assertTrue((import_root / "caches" / "base_cache.py").is_file())
        self.assertTrue((import_root / "modules" / "kodi_utils.py").is_file())

    def test_python_module_path_traversal_is_rejected(self):
        self._write_python_module_metadata("../outside")
        source = self.resolver.resolve(self.identity)
        with self.assertRaises(InstalledAddonSourceError) as caught:
            source.python_module_roots()
        self.assertEqual(caught.exception.code, "PYTHON_MODULE_ROOT_INVALID")

    def test_python_module_symlink_escape_is_rejected(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        self._write_python_module_metadata()
        (self.installed / "resources" / "lib").rmdir()
        (self.installed / "resources").rmdir()
        (self.installed / "resources").symlink_to(outside, target_is_directory=True)
        source = self.resolver.resolve(self.identity)
        with self.assertRaises(InstalledAddonSourceError) as caught:
            source.resources_lib_root()
        self.assertEqual(caught.exception.code, "PYTHON_MODULE_ROOT_OUTSIDE_ROOT")

    def test_missing_resources_lib_fails_closed(self):
        (self.installed / "addon.xml").write_text(
            f'<addon id="{OWNER_ID}" version="{VERSION}">'
            '<extension point="xbmc.python.module" library="resources/lib"/>'
            '</addon>',
            encoding="utf-8",
        )
        source = self.resolver.resolve(self.identity)
        with self.assertRaises(InstalledAddonSourceError) as caught:
            source.resources_lib_root()
        self.assertEqual(caught.exception.code, "PYTHON_MODULE_ROOT_UNAVAILABLE")

    def test_resources_lib_import_root_still_rejects_wrong_owner_identity(self):
        self._write_python_module_metadata()
        source = self.resolver.resolve(self.identity)
        self._write_addon_xml("plugin.video.other", VERSION)
        with self.assertRaises(InstalledAddonSourceError) as caught:
            source.resources_lib_root()
        self.assertEqual(caught.exception.code, "INSTALLED_ADDON_ID_MISMATCH")
        self._write_addon_xml(OWNER_ID, "2.6.7")
        with self.assertRaises(InstalledAddonSourceError) as caught:
            source.resources_lib_root()
        self.assertEqual(caught.exception.code, "INSTALLED_ADDON_VERSION_MISMATCH")


if __name__ == "__main__":
    unittest.main()
