"""Isolation and cleanup tests for temporary verified add-on imports."""

import tempfile
import unittest
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch

from resources.lib.installed_addon_source import (
    InstalledAddonSourceResolver,
    ManagedAddonSourceIdentity,
)
from resources.lib.verified_addon_imports import (
    VerifiedAddonImportError,
    verified_addon_import_context,
)


OWNER_ID = "plugin.video.redlight"
OWNER_VERSION = "2.6.8"
TRANSACTION_ID = "22222222-2222-4222-8222-222222222222"
MANIFEST_FINGERPRINT = "e" * 64


class VerifiedAddonImportContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addons_root = self.root / "home" / "addons"
        self.addons_root.mkdir(parents=True)
        self.resolver = InstalledAddonSourceResolver(lambda: self.addons_root)
        self.owner = self._install_addon(
            OWNER_ID, OWNER_VERSION, "resources/lib", "a" * 64, 1000
        )
        self.owner_root = self.owner.installed_root / "resources" / "lib"
        (self.owner_root / "caches").mkdir()
        (self.owner_root / "modules").mkdir()
        (self.owner_root / "caches" / "base_cache.py").write_text(
            "value = 'base'\n", encoding="utf-8"
        )
        (self.owner_root / "modules" / "kodi_utils.py").write_text(
            "value = 'kodi'\n", encoding="utf-8"
        )
        self.requests = self._install_addon(
            "script.module.requests", "2.31.0", "lib", "b" * 64, 2000
        )
        self.requests_root = self.requests.installed_root / "lib"
        (self.requests_root / "requests").mkdir()
        (self.requests_root / "requests" / "__init__.py").write_text(
            "from requests.adapters import Retry\n", encoding="utf-8"
        )
        (self.requests_root / "requests" / "adapters.py").write_text(
            "class Retry: pass\n", encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _install_addon(self, addon_id, version, library, digest, size):
        installed = self.addons_root / addon_id
        module_root = installed / library
        module_root.mkdir(parents=True)
        (installed / "addon.xml").write_text(
            f'<addon id="{addon_id}" version="{version}">'
            f'<extension point="xbmc.python.module" library="{library}"/>'
            '</addon>',
            encoding="utf-8",
        )
        return self.resolver.resolve(ManagedAddonSourceIdentity(
            addon_id,
            version,
            digest,
            size,
            TRANSACTION_ID,
            MANIFEST_FINGERPRINT,
        ))

    def _context(self, owner=None, dependencies=(), required=True):
        return verified_addon_import_context(
            owner or self.owner,
            dependencies,
            required_module_providers=(
                {"requests": "script.module.requests"} if required else {}
            ),
        )

    def test_verified_requests_dependency_root_provides_requests_package(self):
        with self._context(dependencies=(self.requests,)) as import_module:
            requests_module = import_module("requests")
            self.assertEqual(
                Path(requests_module.__file__).resolve().parent,
                (self.requests_root / "requests").resolve(),
            )
            self.assertEqual(import_module("requests.adapters").Retry.__module__, "requests.adapters")
        self.assertNotIn("requests", sys.modules)
        self.assertNotIn("requests.adapters", sys.modules)

    def test_preexisting_verified_dependency_modules_are_preserved_exactly(self):
        package_path = self.requests_root / "requests"
        requests_module = ModuleType("requests")
        requests_module.__file__ = str(package_path / "__init__.py")
        requests_module.__path__ = [str(package_path)]
        adapters_module = ModuleType("requests.adapters")
        adapters_module.__file__ = str(package_path / "adapters.py")
        adapters_module.Retry = type("Retry", (), {})
        requests_module.adapters = adapters_module
        requests_before = dict(requests_module.__dict__)
        adapters_before = dict(adapters_module.__dict__)
        with patch.dict(sys.modules, {
            "requests": requests_module,
            "requests.adapters": adapters_module,
        }):
            with self._context(dependencies=(self.requests,)) as import_module:
                self.assertIs(import_module("requests"), requests_module)
                self.assertIs(import_module("requests.adapters"), adapters_module)
            self.assertIs(sys.modules["requests"], requests_module)
            self.assertIs(sys.modules["requests.adapters"], adapters_module)
            self.assertEqual(requests_module.__dict__, requests_before)
            self.assertEqual(adapters_module.__dict__, adapters_before)

    def test_addon_root_is_not_a_fallback_for_nested_caches_layout(self):
        self.assertFalse((self.owner.installed_root / "caches").exists())
        self.assertTrue((self.owner_root / "caches" / "base_cache.py").is_file())
        with self._context(required=False) as import_module:
            base_cache = import_module("caches.base_cache")
            kodi_utils = import_module("modules.kodi_utils")
            self.assertEqual(base_cache.value, "base")
            self.assertEqual(kodi_utils.value, "kodi")

    def test_missing_required_managed_dependency_does_not_fall_back_to_host(self):
        host_root = self.root / "host"
        host_root.mkdir()
        (host_root / "requests.py").write_text("host = True\n", encoding="utf-8")
        original_path = list(sys.path)
        previous_requests = sys.modules.get("requests")
        sys.path.insert(0, str(host_root))
        try:
            with self.assertRaisesRegex(
                VerifiedAddonImportError, "required managed Python dependency"
            ):
                with self._context(required=True):
                    self.fail("context must fail before importing a host requests module")
            self.assertIs(sys.modules.get("requests"), previous_requests)
        finally:
            sys.path[:] = original_path

    def test_unrelated_dependency_roots_are_not_implicitly_added(self):
        pil = self._install_addon(
            "script.module.pil", "1.1.7", "lib", "c" * 64, 3000
        )
        pil_root = str(pil.installed_root / "lib")
        original_path = list(sys.path)
        with self._context(dependencies=(self.requests,)):
            self.assertIn(str(self.requests_root), sys.path)
            self.assertNotIn(pil_root, sys.path)
        self.assertEqual(sys.path, original_path)

    def test_sys_path_is_restored_exactly_with_preexisting_dependency_entry(self):
        original_path = list(sys.path)
        sys.path.insert(1, str(self.requests_root))
        before_context = list(sys.path)
        try:
            with self._context(dependencies=(self.requests,)):
                self.assertEqual(sys.path[0], str(self.requests_root))
                self.assertEqual(sys.path.count(str(self.requests_root)), 1)
            self.assertEqual(sys.path, before_context)
        finally:
            sys.path[:] = original_path

    def test_expected_namespace_packages_are_accepted_and_restored(self):
        caches = ModuleType("caches")
        caches.__path__ = [str(self.owner_root / "caches")]
        modules = ModuleType("modules")
        modules.__path__ = [str(self.owner_root / "modules")]
        caches_before = dict(caches.__dict__)
        modules_before = dict(modules.__dict__)
        with patch.dict(sys.modules, {"caches": caches, "modules": modules}):
            with self._context(required=False) as import_module:
                self.assertEqual(import_module("caches.base_cache").value, "base")
                self.assertEqual(import_module("modules.kodi_utils").value, "kodi")
            self.assertIs(sys.modules["caches"], caches)
            self.assertIs(sys.modules["modules"], modules)
            self.assertEqual(caches.__dict__, caches_before)
            self.assertEqual(modules.__dict__, modules_before)
            self.assertNotIn("caches.base_cache", sys.modules)
            self.assertNotIn("modules.kodi_utils", sys.modules)

    def test_preexisting_legitimate_owner_module_is_restored_exactly(self):
        package = ModuleType("modules")
        package.__path__ = [str(self.owner_root / "modules")]
        module = ModuleType("modules.kodi_utils")
        module.__file__ = str(self.owner_root / "modules" / "kodi_utils.py")
        module.value = "preexisting"
        package.kodi_utils = module
        package_before = dict(package.__dict__)
        module_before = dict(module.__dict__)
        with patch.dict(sys.modules, {"modules": package, "modules.kodi_utils": module}):
            with self._context(required=False) as import_module:
                self.assertIs(import_module("modules.kodi_utils"), module)
            self.assertIs(sys.modules["modules"], package)
            self.assertIs(sys.modules["modules.kodi_utils"], module)
            self.assertEqual(package.__dict__, package_before)
            self.assertEqual(module.__dict__, module_before)

    def test_preexisting_caches_namespace_outside_verified_roots_is_rejected(self):
        outside = self.root / "outside-caches"
        outside.mkdir()
        namespace = ModuleType("caches")
        namespace.__path__ = [str(outside)]
        with patch.dict(sys.modules, {"caches": namespace}):
            with self.assertRaisesRegex(VerifiedAddonImportError, "outside verified roots"):
                with self._context(required=False):
                    self.fail("outside caches namespace must be rejected")

    def test_preexisting_modules_namespace_outside_verified_roots_is_rejected(self):
        outside = self.root / "outside-modules"
        outside.mkdir()
        namespace = ModuleType("modules")
        namespace.__path__ = [str(outside)]
        with patch.dict(sys.modules, {"modules": namespace}):
            with self.assertRaisesRegex(VerifiedAddonImportError, "outside verified roots"):
                with self._context(required=False):
                    self.fail("outside modules namespace must be rejected")

    def test_new_namespace_roots_and_owner_modules_are_removed_after_context(self):
        self.assertNotIn("caches", sys.modules)
        self.assertNotIn("modules", sys.modules)
        original_path = list(sys.path)
        with self._context(dependencies=(self.requests,)) as import_module:
            import_module("caches.base_cache")
            import_module("modules.kodi_utils")
            self.assertIn("caches", sys.modules)
            self.assertIn("modules", sys.modules)
        self.assertEqual(sys.path, original_path)
        for name in ("caches", "caches.base_cache", "modules", "modules.kodi_utils"):
            self.assertNotIn(name, sys.modules)

    def test_failed_import_uses_the_same_owner_cleanup(self):
        (self.owner_root / "modules" / "fails.py").write_text(
            "raise RuntimeError('fixture failure')\n", encoding="utf-8"
        )
        original_path = list(sys.path)
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            with self._context(required=False) as import_module:
                import_module("caches.base_cache")
                import_module("modules.fails")
        self.assertEqual(sys.path, original_path)
        for name in ("caches", "caches.base_cache", "modules", "modules.fails"):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
