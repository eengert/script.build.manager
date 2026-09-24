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
    _module_provider,
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

    def _requests_compatibility_sources(self):
        specs = (
            ("script.module.urllib3", "2.2.3", "urllib3", "d"),
            ("script.module.idna", "3.10.0", "idna", "f"),
            ("script.module.chardet", "5.1.0", "chardet", "1"),
        )
        sources = []
        for index, (addon_id, version, module_name, digit) in enumerate(specs):
            source = self._install_addon(
                addon_id, version, "lib", digit * 64, 4000 + index
            )
            package = source.installed_root / "lib" / module_name
            package.mkdir()
            if module_name == "urllib3":
                (package / "__init__.py").write_text(
                    "__version__ = '2.2.3'\nfrom . import exceptions, util\n",
                    encoding="utf-8",
                )
                (package / "exceptions.py").write_text(
                    "class DependencyWarning(Warning): pass\n",
                    encoding="utf-8",
                )
                (package / "util").mkdir()
                (package / "util" / "__init__.py").write_text(
                    "from . import retry\n", encoding="utf-8"
                )
                (package / "util" / "retry.py").write_text(
                    "class Retry: pass\n", encoding="utf-8"
                )
            elif module_name == "idna":
                (package / "__init__.py").write_text(
                    "from . import codec\n", encoding="utf-8"
                )
                (package / "codec.py").write_text("value = True\n", encoding="utf-8")
            else:
                (package / "__init__.py").write_text(
                    "__version__ = '5.1.0'\n", encoding="utf-8"
                )
            sources.append(source)

        requests_package = self.requests_root / "requests"
        (requests_package / "__init__.py").write_text(
            "from . import packages\n", encoding="utf-8"
        )
        (requests_package / "packages.py").write_text(
            "import sys\n"
            "try:\n"
            "    import chardet\n"
            "except ImportError:\n"
            "    import warnings\n"
            "    import charset_normalizer as chardet\n"
            "    warnings.filterwarnings('ignore', 'Trying to detect', "
            "module='charset_normalizer')\n"
            "for package in ('urllib3', 'idna'):\n"
            "    locals()[package] = __import__(package)\n"
            "    for mod in list(sys.modules):\n"
            "        if mod == package or mod.startswith(f'{package}.'):\n"
            "            sys.modules[f'requests.packages.{mod}'] = sys.modules[mod]\n"
            "target = chardet.__name__\n"
            "for mod in list(sys.modules):\n"
            "    if mod == target or mod.startswith(f'{target}.'):\n"
            "        target = target.replace(target, 'chardet')\n"
            "        sys.modules[f'requests.packages.{target}'] = sys.modules[mod]\n",
            encoding="utf-8",
        )
        (requests_package / "adapters.py").write_text(
            "from urllib3.util.retry import Retry\n", encoding="utf-8"
        )
        return tuple([self.requests, *sources])

    @staticmethod
    def _module(name, source, package_path=None):
        module = ModuleType(name)
        module.__file__ = str(source)
        if package_path is not None:
            module.__path__ = [str(package_path)]
        return module

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

    def test_requests_231_compatibility_aliases_use_verified_canonical_objects(self):
        dependencies = self._requests_compatibility_sources()
        original_path = list(sys.path)
        original_meta_path = list(sys.meta_path)
        with self._context(dependencies=dependencies) as import_module:
            requests_module = import_module("requests")
            urllib3 = import_module("urllib3")
            urllib3_exceptions = import_module("urllib3.exceptions")
            idna = import_module("idna")
            chardet = import_module("chardet")
            retry_module = import_module("requests.adapters")
            self.assertEqual(
                Path(requests_module.__file__).resolve().parent,
                (self.requests_root / "requests").resolve(),
            )
            self.assertEqual(urllib3.__version__, "2.2.3")
            self.assertEqual(retry_module.Retry.__module__, "urllib3.util.retry")
            for alias, canonical in (
                ("requests.packages.urllib3", "urllib3"),
                ("requests.packages.urllib3.exceptions", "urllib3.exceptions"),
                ("requests.packages.urllib3.util.retry", "urllib3.util.retry"),
                ("requests.packages.idna", "idna"),
                ("requests.packages.idna.codec", "idna.codec"),
                ("requests.packages.chardet", "chardet"),
            ):
                self.assertIs(sys.modules[alias], sys.modules[canonical], alias)
            self.assertIs(sys.modules["requests.packages.urllib3"], urllib3)
            self.assertIs(
                sys.modules["requests.packages.urllib3.exceptions"],
                urllib3_exceptions,
            )
            self.assertIs(sys.modules["requests.packages.idna"], idna)
            self.assertIs(sys.modules["requests.packages.chardet"], chardet)
        self.assertEqual(sys.path, original_path)
        self.assertEqual(sys.meta_path, original_meta_path)
        for name in tuple(sys.modules):
            self.assertFalse(name == "requests" or name.startswith("requests."), name)
            self.assertFalse(name == "urllib3" or name.startswith("urllib3."), name)
            self.assertFalse(name == "idna" or name.startswith("idna."), name)
            self.assertFalse(name == "chardet" or name.startswith("chardet."), name)

    def test_requests_alias_from_unrelated_verified_provider_is_rejected(self):
        dependencies = self._requests_compatibility_sources()
        unrelated = self._install_addon(
            "script.module.pil", "1.1.7", "lib", "2" * 64, 6000
        )
        unrelated_file = unrelated.installed_root / "lib" / "pil.py"
        unrelated_file.write_text("value = True\n", encoding="utf-8")
        with self.assertRaises(VerifiedAddonImportError) as caught:
            with self._context(dependencies=(*dependencies, unrelated)) as import_module:
                import_module("requests")
                sys.modules["requests.packages.urllib3.exceptions"] = self._module(
                    "requests.packages.urllib3.exceptions", unrelated_file
                )
        self.assertEqual(caught.exception.import_failure_category, "MODULE_SOURCE_MISMATCH")
        self.assertEqual(
            caught.exception.failing_module,
            "requests.packages.urllib3.exceptions",
        )
        self.assertEqual(caught.exception.expected_provider, "script.module.urllib3")
        self.assertEqual(caught.exception.actual_provider, "script.module.pil")
        self.assertNotIn("requests.packages.urllib3.exceptions", sys.modules)

    def test_requests_alias_from_requests_root_is_rejected(self):
        dependencies = self._requests_compatibility_sources()
        with self.assertRaises(VerifiedAddonImportError) as caught:
            with self._context(dependencies=dependencies) as import_module:
                import_module("requests")
                sys.modules["requests.packages.urllib3.exceptions"] = self._module(
                    "requests.packages.urllib3.exceptions",
                    self.requests_root / "requests" / "adapters.py",
                )
        self.assertEqual(caught.exception.import_failure_category, "MODULE_SOURCE_MISMATCH")
        self.assertEqual(caught.exception.expected_provider, "script.module.urllib3")
        self.assertEqual(caught.exception.actual_provider, "script.module.requests")

    def test_forged_requests_alias_with_distinct_module_object_is_rejected(self):
        dependencies = self._requests_compatibility_sources()
        with self.assertRaises(VerifiedAddonImportError) as caught:
            with self._context(dependencies=dependencies) as import_module:
                import_module("requests")
                canonical = sys.modules["urllib3.exceptions"]
                sys.modules["requests.packages.urllib3.exceptions"] = self._module(
                    "requests.packages.urllib3.exceptions", canonical.__file__
                )
        self.assertEqual(
            caught.exception.import_failure_category,
            "MODULE_ALIAS_IDENTITY_MISMATCH",
        )
        self.assertEqual(caught.exception.actual_provider, "script.module.urllib3")
        self.assertNotIn("requests.packages.urllib3.exceptions", sys.modules)

    def test_alias_provider_absent_from_dependency_closure_is_rejected(self):
        urllib3 = self._install_addon(
            "script.module.urllib3", "2.2.3", "lib", "3" * 64, 7000
        )
        canonical_file = urllib3.installed_root / "lib" / "urllib3" / "exceptions.py"
        canonical_file.parent.mkdir()
        canonical_file.write_text("value = True\n", encoding="utf-8")
        requests_root = self.requests_root / "requests"
        (requests_root / "packages.py").write_text(
            "# verified Requests compatibility package fixture\n",
            encoding="utf-8",
        )
        requests_module = self._module(
            "requests", requests_root / "__init__.py", requests_root
        )
        packages_module = self._module(
            "requests.packages", requests_root / "packages.py"
        )
        canonical = self._module("urllib3.exceptions", canonical_file)
        entries = {
            "requests": requests_module,
            "requests.packages": packages_module,
            "urllib3.exceptions": canonical,
            "requests.packages.urllib3.exceptions": canonical,
        }
        with patch.dict(sys.modules, entries):
            with self.assertRaises(VerifiedAddonImportError) as caught:
                with self._context(dependencies=(self.requests,)):
                    self.fail("alias provider absent from closure must be rejected")
        self.assertEqual(
            caught.exception.import_failure_category,
            "MODULE_PROVIDER_NOT_IN_CLOSURE",
        )
        self.assertEqual(
            caught.exception.failing_module,
            "requests.packages.urllib3.exceptions",
        )
        self.assertEqual(caught.exception.expected_provider, "script.module.urllib3")

    def test_alias_from_host_urllib3_is_rejected_before_context_body(self):
        dependencies = self._requests_compatibility_sources()
        host = self.root / "host"
        host.mkdir()
        host_file = host / "exceptions.py"
        host_file.write_text("value = 'host'\n", encoding="utf-8")
        requests_root = self.requests_root / "requests"
        host_module = self._module("urllib3.exceptions", host_file)
        entries = {
            "requests": self._module(
                "requests", requests_root / "__init__.py", requests_root
            ),
            "requests.packages": self._module(
                "requests.packages", requests_root / "packages.py"
            ),
            "urllib3.exceptions": host_module,
            "requests.packages.urllib3.exceptions": host_module,
        }
        with patch.dict(sys.modules, entries):
            with self.assertRaises(VerifiedAddonImportError) as caught:
                with self._context(dependencies=dependencies):
                    self.fail("host module must not satisfy frozen urllib3")
        self.assertEqual(caught.exception.import_failure_category, "MODULE_SOURCE_MISMATCH")
        self.assertEqual(caught.exception.expected_provider, "script.module.urllib3")
        self.assertEqual(caught.exception.actual_provider, "")

    def test_host_top_level_dependencies_never_masquerade_as_verified(self):
        dependencies = self._requests_compatibility_sources()
        host = self.root / "host"
        host.mkdir()
        module_files = {}
        for name in ("requests", "urllib3", "idna", "chardet"):
            source = host / f"{name}.py"
            source.write_text("value = 'host'\n", encoding="utf-8")
            module_files[name] = source
        for name in module_files:
            with self.subTest(name=name):
                with patch.dict(
                    sys.modules,
                    {name: self._module(name, module_files[name])},
                ):
                    with self.assertRaises(VerifiedAddonImportError) as caught:
                        with self._context(dependencies=dependencies):
                            self.fail("host package must not satisfy frozen provider")
                self.assertEqual(
                    caught.exception.import_failure_category,
                    "MODULE_SOURCE_MISMATCH",
                )
                self.assertEqual(caught.exception.failing_module, name)

    def test_module_provider_resolution_rejects_ambiguous_roots_and_symlink_escape(self):
        source_file = self.requests_root / "requests" / "adapters.py"
        source_module = self._module("requests.adapters", source_file)
        with self.assertRaises(VerifiedAddonImportError) as ambiguous:
            _module_provider(
                "requests.adapters",
                source_module,
                {
                    "script.module.requests": (self.requests_root,),
                    "script.module.other": (self.requests_root,),
                },
                expected_provider="script.module.requests",
            )
        self.assertEqual(
            ambiguous.exception.import_failure_category,
            "MODULE_PROVIDER_AMBIGUOUS",
        )

        outside = self.root / "outside.py"
        outside.write_text("value = True\n", encoding="utf-8")
        escape = self.requests_root / "requests" / "escaped.py"
        escape.symlink_to(outside)
        with self.assertRaises(VerifiedAddonImportError) as escaped:
            _module_provider(
                "requests.escaped",
                self._module("requests.escaped", escape),
                {"script.module.requests": (self.requests_root,)},
                expected_provider="script.module.requests",
            )
        self.assertEqual(
            escaped.exception.import_failure_category,
            "MODULE_SOURCE_MISMATCH",
        )
        self.assertNotIn(str(outside), str(escaped.exception))

    def test_compatibility_aliases_are_removed_after_failure_and_retry_is_clean(self):
        dependencies = self._requests_compatibility_sources()
        original_path = list(sys.path)
        original_meta_path = list(sys.meta_path)
        unrelated = ModuleType("bm017f_unrelated_shared_module")
        unrelated.value = object()
        sys.modules[unrelated.__name__] = unrelated
        try:
            with self.assertRaises(VerifiedAddonImportError) as failed:
                with self._context(dependencies=dependencies) as import_module:
                    import_module("requests")
                    sys.modules["requests.packages.urllib3.exceptions"] = self._module(
                        "requests.packages.urllib3.exceptions",
                        self.requests_root / "requests" / "adapters.py",
                    )
            self.assertEqual(
                failed.exception.import_failure_category,
                "MODULE_SOURCE_MISMATCH",
            )
            self.assertEqual(sys.path, original_path)
            self.assertEqual(sys.meta_path, original_meta_path)
            self.assertIs(sys.modules[unrelated.__name__], unrelated)
            self.assertFalse(any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in ("requests", "urllib3", "idna", "chardet")
                for name in sys.modules
            ))
            with self._context(dependencies=dependencies) as import_module:
                import_module("requests")
                self.assertIs(
                    sys.modules["requests.packages.urllib3.exceptions"],
                    sys.modules["urllib3.exceptions"],
                )
            self.assertEqual(sys.path, original_path)
            self.assertEqual(sys.meta_path, original_meta_path)
            self.assertFalse(any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in ("requests", "urllib3", "idna", "chardet")
                for name in sys.modules
            ))
        finally:
            sys.modules.pop(unrelated.__name__, None)

    def test_new_compatibility_aliases_are_removed_after_success(self):
        dependencies = self._requests_compatibility_sources()
        with self._context(dependencies=dependencies) as import_module:
            import_module("requests")
            self.assertIn("requests.packages.idna.codec", sys.modules)
            self.assertIn("requests.packages.chardet", sys.modules)
        for name in (
            "requests",
            "requests.packages",
            "requests.packages.urllib3.exceptions",
            "requests.packages.idna.codec",
            "requests.packages.chardet",
            "urllib3",
            "urllib3.exceptions",
            "idna",
            "chardet",
        ):
            self.assertNotIn(name, sys.modules)

    def test_preexisting_verified_urllib3_modules_survive_alias_cleanup(self):
        dependencies = self._requests_compatibility_sources()
        urllib3_root = dependencies[1].installed_root / "lib" / "urllib3"
        urllib3 = self._module("urllib3", urllib3_root / "__init__.py", urllib3_root)
        exceptions = self._module("urllib3.exceptions", urllib3_root / "exceptions.py")
        urllib3.exceptions = exceptions
        before = dict(urllib3.__dict__)
        exception_before = dict(exceptions.__dict__)
        with patch.dict(sys.modules, {"urllib3": urllib3, "urllib3.exceptions": exceptions}):
            with self._context(dependencies=dependencies) as import_module:
                import_module("requests")
                self.assertIs(sys.modules["requests.packages.urllib3.exceptions"], exceptions)
            self.assertIs(sys.modules["urllib3"], urllib3)
            self.assertIs(sys.modules["urllib3.exceptions"], exceptions)
            self.assertEqual(urllib3.__dict__, before)
            self.assertEqual(exceptions.__dict__, exception_before)
            self.assertNotIn("requests.packages.urllib3.exceptions", sys.modules)

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
            with self.assertRaisesRegex(VerifiedAddonImportError, "outside verified providers"):
                with self._context(required=False):
                    self.fail("outside caches namespace must be rejected")

    def test_preexisting_modules_namespace_outside_verified_roots_is_rejected(self):
        outside = self.root / "outside-modules"
        outside.mkdir()
        namespace = ModuleType("modules")
        namespace.__path__ = [str(outside)]
        with patch.dict(sys.modules, {"modules": namespace}):
            with self.assertRaisesRegex(VerifiedAddonImportError, "outside verified providers"):
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
