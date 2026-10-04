"""BM-017C fake structured-resource, Red Light schema, and secret-safety tests."""

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resources.lib.config import ConfigurationBackend, ConfigurationManager
from resources.lib.manifest import load_manifest_json
from resources.lib.private_overlay import (
    PrivateOverlay,
    PrivateOverlayManager,
    PrivateOverlayStore,
    PrivateOverlayValidationError,
)
from resources.lib.private_resource import (
    PrivateResourceCompatibilityError,
    PrivateResourceLifecycleError,
    PrivateResourceNotInitializedError,
    PrivateResourceValidationError,
    ResourceInitializationCause,
    ResourceInitializationStage,
    ResourceLifecycle,
    StructuredPrivateResourceManager,
    StructuredResourceInitializationError,
    StructuredPrivateResourceOverlay,
    StructuredPrivateValue,
    StructuredResourceFieldDeclaration,
    validate_resource_overlay,
)
from resources.lib.installed_addon_source import (
    InstalledAddonSourceResolver,
    ManagedAddonSourceIdentity,
    PrivateResourceOwnerContext,
)
from resources.lib.redlight_resource import (
    REDLIGHT_ADDON_ID,
    REDLIGHT_RESOURCE_ID,
    REDLIGHT_SCHEMA_ID,
    RedLightSettingsAdapter,
    redlight_declaration,
)
from resources.lib.verified_addon_imports import VerifiedAddonImportError


SECRET = "BM017C_FAKE_SECRET_NOT_FOR_OUTPUT"


class NullBackend(ConfigurationBackend):
    def get_setting(self, addon_id, key, setting_type):
        raise AssertionError("structured-only overlay must not use Kodi settings")

    def set_setting(self, addon_id, key, setting_type, value):
        raise AssertionError("structured-only overlay must not use Kodi settings")

    def read_file(self, destination):
        return None

    def write_file(self, destination, data):
        raise AssertionError("structured-only overlay must not use managed files")


def _profile(root: Path) -> Path:
    path = root / "addon_data" / REDLIGHT_ADDON_ID / "databases"
    path.mkdir(parents=True)
    database = path / "settings.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(
        "CREATE TABLE settings (setting_id text not null unique, setting_type text, setting_default text, setting_value text)"
    )
    connection.executemany(
        "INSERT INTO settings VALUES (?, ?, ?, ?)",
        (
            ("trakt.token", "string", "", "old-token"),
            ("pm.token", "string", "", "old-pm"),
            ("ordinary.preference", "string", "default", "keep-me"),
            ("generated.name", "name", "", "generated"),
            ("unknown.row", "string", "", "untouched"),
        ),
    )
    connection.commit()
    connection.close()
    return database


def _declaration(*fields):
    return redlight_declaration(fields=fields or (
        StructuredResourceFieldDeclaration("trakt.token", "string", True, "token"),
        StructuredResourceFieldDeclaration("pm.token", "string", False, "token"),
    ))


def _overlay(*values):
    return StructuredPrivateResourceOverlay(
        REDLIGHT_RESOURCE_ID,
        REDLIGHT_ADDON_ID,
        "2.6.8",
        REDLIGHT_SCHEMA_ID,
        tuple(values),
    )


def _verified_source_context(root: Path, *, version="2.6.8"):
    addons_root = root / "verified-kodi-home" / "addons"
    installed_root = addons_root / REDLIGHT_ADDON_ID
    (installed_root / "resources" / "lib").mkdir(parents=True, exist_ok=True)
    (installed_root / "addon.xml").write_text(
        f'<addon id="{REDLIGHT_ADDON_ID}" version="{version}">'
        '<extension point="xbmc.python.module" library="resources/lib/"/>'
        '</addon>',
        encoding="utf-8",
    )
    transaction_id = "11111111-1111-4111-8111-111111111111"
    manifest_fingerprint = "b" * 64
    identity = ManagedAddonSourceIdentity(
        REDLIGHT_ADDON_ID,
        version,
        "a" * 64,
        1234,
        transaction_id,
        manifest_fingerprint,
    )
    resolver = InstalledAddonSourceResolver(lambda: addons_root)
    source = resolver.resolve(identity)
    dependency_specs = (
        ("script.module.requests", "2.31.0", "requests"),
        ("script.module.urllib3", "2.2.3", "urllib3"),
        ("script.module.certifi", "2023.5.7", "certifi"),
        ("script.module.chardet", "5.1.0", "chardet"),
        ("script.module.idna", "3.10.0", "idna"),
    )
    dependency_sources = []
    for index, (addon_id, addon_version, _module) in enumerate(dependency_specs):
        dependency_root = addons_root / addon_id
        (dependency_root / "lib").mkdir(parents=True)
        (dependency_root / "addon.xml").write_text(
            f'<addon id="{addon_id}" version="{addon_version}">'
            '<extension point="xbmc.python.module" library="lib"/>'
            '</addon>',
            encoding="utf-8",
        )
        dependency_identity = ManagedAddonSourceIdentity(
            addon_id,
            addon_version,
            format(index + 1, "x") * 64,
            200 + index,
            transaction_id,
            manifest_fingerprint,
        )
        dependency_sources.append(resolver.resolve(dependency_identity))
    return PrivateResourceOwnerContext(
        REDLIGHT_ADDON_ID,
        version,
        version,
        False,
        True,
        source,
        tuple(dependency_sources),
    )


def _fake_redlight_package(root: Path):
    """Small fixture for the audited defaults/schema import contract."""
    context = _verified_source_context(root)
    addon_root = context.installed_source.installed_root
    import_root = addon_root / "resources" / "lib"
    (import_root / "caches").mkdir()
    (import_root / "modules").mkdir()
    (import_root / "caches" / "base_cache.py").write_text(
        "def table_creators():\n"
        "    return {'settings_db': (\"CREATE TABLE IF NOT EXISTS settings "
        "(setting_id text not null unique, setting_type text, "
        "setting_default text, setting_value text)\",)}\n",
        encoding="utf-8",
    )
    (import_root / "modules" / "kodi_utils.py").write_text(
        "properties = {}\n"
        "def addon_fanart():\n"
        "    return 'special://home/addons/plugin.video.redlight/resources/media/fanart.jpg'\n"
        "def addon_profile():\n"
        "    raise AssertionError('owner profile API must not be used')\n"
        "def set_property(key, value):\n"
        "    properties[key] = value\n",
        encoding="utf-8",
    )
    (import_root / "caches" / "settings_cache.py").write_text(
        "from modules import kodi_utils, http_defaults\n"
        "_SETTINGS_DB_SYNCED = 'redlight.settings_db_synced'\n"
        "_SETTINGS_SYNC_FINGERPRINT = 'redlight.settings_sync_fingerprint'\n"
        "def default_settings():\n"
        "    return [\n"
        "      {'setting_id': 'trakt.token', 'setting_type': 'string', 'setting_default': 'empty_setting'},\n"
        "      {'setting_id': 'aiostreams.instance', 'setting_type': 'action', 'setting_default': '0', 'settings_options': {'0': 'Default'}},\n"
        "      {'setting_id': 'default_addon_fanart', 'setting_type': 'path', 'setting_default': kodi_utils.addon_fanart()},\n"
        "    ]\n"
        "def _new_setting_value(setting_id, setting_default, current, had_existing, fresh_install=False):\n"
        "    return setting_default\n",
        encoding="utf-8",
    )
    (import_root / "modules" / "http_defaults.py").write_text(
        "from requests.adapters import Retry\n"
        "def scoped_token(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    for source in context.python_dependency_sources:
        dependency_root = source.installed_root / "lib"
        module_name = {
            "script.module.requests": "requests",
            "script.module.urllib3": "urllib3",
            "script.module.certifi": "certifi",
            "script.module.chardet": "chardet",
            "script.module.idna": "idna",
        }[source.addon_id]
        package = dependency_root / module_name
        package.mkdir(parents=True)
        if source.addon_id == "script.module.requests":
            (package / "__init__.py").write_text(
                "from . import packages\n", encoding="utf-8"
            )
            (package / "packages.py").write_text(
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
            (package / "adapters.py").write_text(
                "from urllib3.util.retry import Retry\n",
                encoding="utf-8",
            )
        elif source.addon_id == "script.module.urllib3":
            (package / "__init__.py").write_text(
                "__version__ = '2.2.3'\nfrom . import exceptions, util\n",
                encoding="utf-8",
            )
            (package / "exceptions.py").write_text(
                "class DependencyWarning(Warning): pass\n",
                encoding="utf-8",
            )
            util = package / "util"
            util.mkdir()
            (util / "__init__.py").write_text(
                "from . import retry\n", encoding="utf-8"
            )
            (util / "retry.py").write_text("class Retry: pass\n", encoding="utf-8")
        elif source.addon_id == "script.module.idna":
            (package / "__init__.py").write_text(
                "from . import codec\n", encoding="utf-8"
            )
            (package / "codec.py").write_text("value = True\n", encoding="utf-8")
        elif source.addon_id == "script.module.chardet":
            (package / "__init__.py").write_text(
                "__version__ = '5.1.0'\n", encoding="utf-8"
            )
    return context


class StructuredResourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _profile(self.root)
        self.declaration = _declaration()
        self.adapter = RedLightSettingsAdapter(
            self.root,
            lifecycle=ResourceLifecycle.QUIESCED,
            initialized=True,
            activation_hold_provider=lambda _addon_id: True,
            enabled_state_provider=lambda _addon_id: False,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _prepare_fresh_initialization(self):
        database_path = self.adapter.database_path
        for path in (
            database_path,
            Path(str(database_path) + "-wal"),
            Path(str(database_path) + "-shm"),
        ):
            path.unlink(missing_ok=True)
        return _fake_redlight_package(self.root)

    def _assert_initialization_stage(self, context, stage, cause, last_stage=None):
        manager = StructuredPrivateResourceManager(
            {self.adapter.adapter_id: self.adapter}
        )
        with self.assertRaises(StructuredResourceInitializationError) as caught:
            manager.initialize(
                (self.declaration,),
                owner_contexts={REDLIGHT_ADDON_ID: context},
            )
        error = caught.exception
        self.assertEqual(error.code, "PRIVATE_RESOURCE_INITIALIZATION_FAILED")
        self.assertEqual(error.owner_addon_id, REDLIGHT_ADDON_ID)
        self.assertEqual(error.resource_id, REDLIGHT_RESOURCE_ID)
        self.assertEqual(error.initialization_stage, stage)
        self.assertEqual(error.last_completed_stage, last_stage)
        self.assertEqual(error.cause_code, cause.value)
        self.assertNotIn(SECRET, str(error))
        self.assertNotIn(SECRET, repr(error))
        return error

    def test_public_declaration_contains_only_safe_metadata(self):
        safe = self.declaration.safe_dict()
        self.assertNotIn("value", json.dumps(safe))
        self.assertEqual(safe["resource_id"], REDLIGHT_RESOURCE_ID)
        self.assertEqual(safe["supported_versions"], ["2.6.8"])

    def test_duplicate_field_ownership_rejected(self):
        with self.assertRaises(PrivateResourceValidationError):
            _declaration(
                StructuredResourceFieldDeclaration("trakt.token", "string"),
                StructuredResourceFieldDeclaration("trakt.token", "string"),
            )

    def test_unknown_adapter_and_unsupported_version_fail_closed(self):
        manager = StructuredPrivateResourceManager()
        with self.assertRaises(PrivateResourceCompatibilityError):
            manager.apply((self.declaration,), (_overlay(StructuredPrivateValue("trakt.token", "string", SECRET)),))
        wrong = StructuredPrivateResourceOverlay(
            REDLIGHT_RESOURCE_ID, REDLIGHT_ADDON_ID, "2.6.7", REDLIGHT_SCHEMA_ID,
            (StructuredPrivateValue("trakt.token", "string", SECRET),),
        )
        with self.assertRaises(PrivateResourceCompatibilityError):
            validate_resource_overlay(wrong, self.declaration)

    def test_capture_reads_declared_fields_only_and_sanitizes_result(self):
        overlay, result = self.adapter.capture(self.declaration)
        self.assertEqual([value.field_id for value in overlay.values], ["trakt.token", "pm.token"])
        self.assertNotIn("old-token", json.dumps(result.to_dict()))
        self.assertNotIn("keep-me", json.dumps(result.to_dict()))
        self.assertEqual(result.fields[0].status, "captured")

    def test_required_missing_field_fails_and_optional_missing_is_allowed(self):
        connection = sqlite3.connect(self.adapter.database_path)
        connection.execute("DELETE FROM settings WHERE setting_id = 'trakt.token'")
        connection.commit()
        connection.close()
        with self.assertRaises(PrivateResourceNotInitializedError):
            self.adapter.capture(self.declaration)
        optional = _declaration(StructuredResourceFieldDeclaration("missing.optional", "string", False, "token"))
        overlay, result = self.adapter.capture(optional)
        self.assertEqual(overlay.values, ())
        self.assertEqual(result.fields[0].status, "absent")

    def test_active_runtime_is_rejected_for_application(self):
        adapter = RedLightSettingsAdapter(self.root, lifecycle=ResourceLifecycle.ACTIVE, initialized=True)
        with self.assertRaises(PrivateResourceLifecycleError):
            adapter.apply(self.declaration, _overlay(StructuredPrivateValue("trakt.token", "string", SECRET)))

    def test_drift_repair_requires_durable_hold_and_disabled_owner(self):
        overlay = _overlay(StructuredPrivateValue("trakt.token", "string", SECRET))
        for adapter in (
            RedLightSettingsAdapter(self.root, lifecycle=ResourceLifecycle.QUIESCED, initialized=True),
            RedLightSettingsAdapter(
                self.root, lifecycle=ResourceLifecycle.QUIESCED, initialized=True,
                activation_hold_provider=lambda _addon_id: True,
                enabled_state_provider=lambda _addon_id: True,
            ),
        ):
            with self.assertRaises(PrivateResourceLifecycleError):
                adapter.apply(self.declaration, overlay)

    def test_exact_values_are_read_only_after_activation_release(self):
        overlay = _overlay(StructuredPrivateValue("trakt.token", "string", SECRET))
        self.adapter.apply(self.declaration, overlay)
        released = RedLightSettingsAdapter(
            self.root,
            lifecycle=ResourceLifecycle.QUIESCED,
            initialized=False,
            activation_hold_provider=lambda _addon_id: False,
            enabled_state_provider=lambda _addon_id: True,
        )
        result = released.apply(self.declaration, overlay)
        self.assertTrue(result.succeeded)
        self.assertFalse(result.changed)
        self.assertFalse(result.restart_required)
        self.assertNotIn(SECRET, json.dumps(result.to_dict()))

    def test_existing_populated_resource_initializes_without_activation_hold(self):
        adapter = RedLightSettingsAdapter(self.root, lifecycle=ResourceLifecycle.QUIESCED)
        result = adapter.initialize(self.declaration)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.outcome, "already_initialized")

    def test_verified_source_initializes_red_light_while_disabled_without_addon_lookup(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        database_path = self.adapter.database_path
        database_path.unlink()
        for suffix in ("-wal", "-shm"):
            Path(str(database_path) + suffix).unlink(missing_ok=True)
        source_context = _fake_redlight_package(self.root)
        calls = []
        lifecycle_checks = []
        loaded_modules = {}
        request_alias_checks = []
        self.adapter._activation_hold_provider = lambda addon_id: (
            lifecycle_checks.append((addon_id, "held", True)) or True
        )
        self.adapter._enabled_state_provider = lambda addon_id: (
            lifecycle_checks.append((addon_id, "enabled", False)) or False
        )
        forbidden_addon = unittest.mock.Mock(
            side_effect=AssertionError("xbmcaddon.Addon must not be called")
        )
        original_import_module = __import__("importlib").import_module
        original_import = __import__("builtins").__import__

        def track_import(name, package=None):
            calls.append(name)
            module = original_import_module(name, package)
            loaded_modules[name] = module
            if name == "caches.settings_cache":
                request_alias_checks.extend((
                    getattr(module.http_defaults.Retry, "__module__", ""),
                    sys.modules.get("requests.packages.urllib3.exceptions")
                    is sys.modules.get("urllib3.exceptions"),
                    sys.modules.get("requests.packages.idna.codec")
                    is sys.modules.get("idna.codec"),
                    sys.modules.get("requests.packages.chardet")
                    is sys.modules.get("chardet"),
                ))
            return module

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.split(".", 1)[0] in {"apis", "service"}:
                raise AssertionError("provider or service import must not run")
            return original_import(name, globals, locals, fromlist, level)

        with (
            patch.dict("sys.modules", {"xbmcaddon": SimpleNamespace(Addon=forbidden_addon)}),
            patch("builtins.__import__", side_effect=guarded_import),
            patch("resources.lib.verified_addon_imports.importlib.import_module", side_effect=track_import),
        ):
            result = self.adapter.initialize(self.declaration, source_context)
            self.assertTrue(result.succeeded)
            self.assertEqual(result.outcome, "initialized")
            self.assertEqual(
                calls,
                ["caches.base_cache", "caches.settings_cache", "modules.kodi_utils"],
            )
            forbidden_addon.assert_not_called()
        self.assertEqual(
            request_alias_checks,
            [
                "urllib3.util.retry",
                True,
                True,
                True,
            ],
        )
        self.assertEqual(
            loaded_modules["modules.kodi_utils"].properties,
            {
                "redlight.settings_db_synced": "true",
                "redlight.settings_sync_fingerprint": "2.6.8:3",
            },
        )
        self.assertTrue(lifecycle_checks)
        self.assertTrue(all(
            addon_id == REDLIGHT_ADDON_ID and state_value in (True, False)
            for addon_id, _state_name, state_value in lifecycle_checks
        ))
        self.assertTrue(all(
            (state_name != "held" or state_value is True)
            and (state_name != "enabled" or state_value is False)
            for _addon_id, state_name, state_value in lifecycle_checks
        ))
        self.assertEqual(result.resource_id, REDLIGHT_RESOURCE_ID)
        self.assertFalse(result.restart_required)

        connection = sqlite3.connect(database_path)
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(settings)"))
        rows = dict(connection.execute("SELECT setting_id, setting_value FROM settings"))
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        connection.execute(
            "INSERT INTO settings VALUES (?, ?, ?, ?)",
            ("ordinary.preference", "string", "keep", "keep-me"),
        )
        connection.execute(
            "INSERT INTO settings VALUES (?, ?, ?, ?)",
            ("unrelated.name", "name", "", "preserve-me"),
        )
        connection.commit()
        connection.close()
        self.assertEqual(columns, ("setting_id", "setting_type", "setting_default", "setting_value"))
        self.assertEqual(rows["trakt.token"], "empty_setting")
        self.assertEqual(rows["aiostreams.instance_name"], "Default")
        self.assertEqual(journal_mode.lower(), "wal")

        # A repeat is read-only and idempotent; private application remains
        # row-scoped and preserves unrelated package state.
        repeated = self.adapter.initialize(self.declaration, source_context)
        self.assertEqual(repeated.outcome, "already_initialized")
        applied = self.adapter.apply(
            self.declaration,
            _overlay(StructuredPrivateValue("trakt.token", "string", SECRET)),
        )
        self.assertTrue(applied.succeeded)
        self.assertNotIn(SECRET, json.dumps(applied.to_dict()))
        connection = sqlite3.connect(database_path)
        rows = dict(connection.execute("SELECT setting_id, setting_value FROM settings"))
        connection.close()
        self.assertEqual(rows["trakt.token"], SECRET)
        self.assertEqual(rows["ordinary.preference"], "keep-me")
        self.assertEqual(rows["unrelated.name"], "preserve-me")

    def test_fresh_initialization_requires_verified_held_disabled_source(self):
        self.adapter.database_path.unlink()
        context = _fake_redlight_package(self.root)
        with self.assertRaises(PrivateResourceNotInitializedError):
            self.adapter.initialize(self.declaration)
        self.assertFalse(self.adapter.database_path.exists())

    def test_source_revalidation_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()
        with patch.object(
            type(context.installed_source),
            "revalidate",
            side_effect=RuntimeError(SECRET),
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.SOURCE_REVALIDATION,
                ResourceInitializationCause.SOURCE_REVALIDATION_FAILED,
                ResourceInitializationStage.VALIDATE_EXISTING_RESOURCE,
            )

    def test_initializer_import_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()
        import_module = __import__("importlib").import_module

        def fail_settings_import(name, package=None):
            if name == "caches.settings_cache":
                raise ImportError(SECRET)
            return import_module(name, package)

        with patch(
            "resources.lib.verified_addon_imports.importlib.import_module",
            side_effect=fail_settings_import,
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.LOAD_INITIALIZER_DECLARATIONS,
                ResourceInitializationCause.INITIALIZER_IMPORT_FAILED,
                ResourceInitializationStage.SOURCE_REVALIDATION,
            )

    def test_import_ownership_diagnostic_fields_are_sanitized_and_retained(self):
        context = self._prepare_fresh_initialization()
        import_module = __import__("importlib").import_module

        def fail_alias_import(name, package=None):
            if name == "caches.settings_cache":
                raise VerifiedAddonImportError(
                    f"source=/private/untrusted/path {SECRET}",
                    import_failure_category="MODULE_SOURCE_MISMATCH",
                    failing_module="requests.packages.urllib3.exceptions",
                    expected_provider="script.module.urllib3",
                    actual_provider="script.module.requests",
                )
            return import_module(name, package)

        with patch(
            "resources.lib.verified_addon_imports.importlib.import_module",
            side_effect=fail_alias_import,
        ):
            error = self._assert_initialization_stage(
                context,
                ResourceInitializationStage.LOAD_INITIALIZER_DECLARATIONS,
                ResourceInitializationCause.INITIALIZER_IMPORT_FAILED,
                ResourceInitializationStage.SOURCE_REVALIDATION,
            )
        self.assertEqual(error.import_failure_category, "MODULE_SOURCE_MISMATCH")
        self.assertEqual(
            error.failing_module,
            "requests.packages.urllib3.exceptions",
        )
        self.assertEqual(error.expected_provider, "script.module.urllib3")
        self.assertEqual(error.actual_provider, "script.module.requests")
        encoded = json.dumps({
            "category": error.import_failure_category,
            "module": error.failing_module,
            "expected": error.expected_provider,
            "actual": error.actual_provider,
            "message": str(error),
        })
        self.assertNotIn("/private/", encoded)
        self.assertNotIn(SECRET, encoded)

    def test_addon_data_directory_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()
        shutil.rmtree(self.root / "addon_data")
        addon_data_path = self.adapter._profile_root / "addon_data"
        original_mkdir = Path.mkdir

        def fail_addon_data(path, *args, **kwargs):
            if path == addon_data_path:
                raise OSError(SECRET)
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", new=fail_addon_data):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.CREATE_ADDON_DATA_DIRECTORY,
                ResourceInitializationCause.DIRECTORY_CREATION_FAILED,
                ResourceInitializationStage.LOAD_SCHEMA_DECLARATION,
            )

    def test_database_directory_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()
        shutil.rmtree(self.root / "addon_data")
        database_directory = self.adapter.database_path.parent
        original_mkdir = Path.mkdir

        def fail_database_directory(path, *args, **kwargs):
            if path == database_directory:
                raise OSError(SECRET)
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", new=fail_database_directory):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.CREATE_DATABASE_DIRECTORY,
                ResourceInitializationCause.DIRECTORY_CREATION_FAILED,
                ResourceInitializationStage.CREATE_ADDON_DATA_DIRECTORY,
            )

    def test_sqlite_open_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()
        with patch(
            "resources.lib.redlight_resource.sqlite3.connect",
            side_effect=sqlite3.OperationalError(SECRET),
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.OPEN_SETTINGS_DATABASE,
                ResourceInitializationCause.DATABASE_OPEN_FAILED,
                ResourceInitializationStage.CREATE_DATABASE_DIRECTORY,
            )

    def test_wal_setup_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()

        class FailingWalConnection:
            def execute(self, _statement):
                raise sqlite3.OperationalError(SECRET)

            def close(self):
                pass

        with patch(
            "resources.lib.redlight_resource.sqlite3.connect",
            return_value=FailingWalConnection(),
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.SET_WAL_MODE,
                ResourceInitializationCause.WAL_SETUP_FAILED,
                ResourceInitializationStage.OPEN_SETTINGS_DATABASE,
            )

    def test_schema_creation_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()

        class FailingSchemaConnection:
            def execute(self, statement):
                if statement == "PRAGMA journal_mode = WAL":
                    return type("Cursor", (), {"fetchone": lambda _self: ("wal",)})()
                raise sqlite3.OperationalError(SECRET)

            def commit(self):
                pass

            def close(self):
                pass

        with patch(
            "resources.lib.redlight_resource.sqlite3.connect",
            return_value=FailingSchemaConnection(),
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.CREATE_SCHEMA,
                ResourceInitializationCause.SCHEMA_CREATION_FAILED,
                ResourceInitializationStage.SET_WAL_MODE,
            )

    def test_defaults_insertion_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()
        with patch.object(
            self.adapter,
            "_write_default_rows",
            side_effect=sqlite3.OperationalError(SECRET),
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.INSERT_DEFAULTS,
                ResourceInitializationCause.DEFAULT_INITIALIZATION_FAILED,
                ResourceInitializationStage.VALIDATE_RESOURCE_EMPTY,
            )

    def test_final_validation_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()
        with patch.object(
            self.adapter,
            "_verify_database",
            side_effect=PrivateResourceCompatibilityError(SECRET),
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.FINAL_RESOURCE_VALIDATION,
                ResourceInitializationCause.FINAL_VALIDATION_FAILED,
                ResourceInitializationStage.INSERT_DEFAULTS,
            )

    def test_marker_publication_failure_reports_stage_and_cause(self):
        context = self._prepare_fresh_initialization()
        original_initializers = self.adapter._redlight_initializers

        def with_failing_setter(installed_source, run_stage, dependency_sources=()):
            values = list(original_initializers(
                installed_source,
                run_stage,
                dependency_sources=dependency_sources,
            ))

            def fail_set_property(_key, _value):
                raise RuntimeError(SECRET)

            values[3] = fail_set_property
            return tuple(values)

        with patch.object(
            self.adapter,
            "_redlight_initializers",
            side_effect=with_failing_setter,
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.PUBLISH_SYNC_MARKER,
                ResourceInitializationCause.MARKER_PUBLICATION_FAILED,
                ResourceInitializationStage.FINAL_RESOURCE_VALIDATION,
            )

    def test_unexpected_exception_reports_safe_generic_cause(self):
        context = self._prepare_fresh_initialization()
        with patch.object(
            self.adapter,
            "_settings_database_is_empty",
            side_effect=RuntimeError(SECRET),
        ):
            self._assert_initialization_stage(
                context,
                ResourceInitializationStage.VALIDATE_RESOURCE_EMPTY,
                ResourceInitializationCause.INITIALIZATION_STAGE_FAILED,
                ResourceInitializationStage.LOAD_INITIALIZER_DECLARATIONS,
            )

    def test_initialization_failure_keeps_typed_owner_resource_context_safely(self):
        from resources.lib.private_resource import StructuredPrivateResourceManager

        self.adapter.database_path.unlink()
        manager = StructuredPrivateResourceManager(
            {self.adapter.adapter_id: self.adapter}
        )
        with self.assertRaises(StructuredResourceInitializationError) as caught:
            manager.initialize((self.declaration,))
        self.assertEqual(caught.exception.code, "PRIVATE_RESOURCE_INITIALIZATION_FAILED")
        self.assertEqual(caught.exception.owner_addon_id, REDLIGHT_ADDON_ID)
        self.assertEqual(caught.exception.resource_id, REDLIGHT_RESOURCE_ID)
        self.assertEqual(
            caught.exception.initialization_stage,
            ResourceInitializationStage.SOURCE_REVALIDATION,
        )
        self.assertEqual(
            caught.exception.cause_code,
            ResourceInitializationCause.SOURCE_REVALIDATION_FAILED.value,
        )
        self.assertNotIn(SECRET, str(caught.exception))

    def test_ordinary_resources_do_not_require_installed_owner_context(self):
        from dataclasses import replace

        ordinary = replace(self.declaration, configure_before_activation=False)
        manager = StructuredPrivateResourceManager(
            {self.adapter.adapter_id: self.adapter}
        )
        self.assertEqual(manager.initialize((ordinary,)), ())

    def test_missing_database_is_not_synthesized(self):
        adapter = RedLightSettingsAdapter(
            self.root,
            lifecycle=ResourceLifecycle.QUIESCED,
            initialized=True,
            activation_hold_provider=lambda _addon_id: True,
            enabled_state_provider=lambda _addon_id: False,
        )
        self.adapter.database_path.unlink()
        with self.assertRaises(PrivateResourceNotInitializedError):
            adapter.capture(self.declaration)
        self.assertFalse(self.adapter.database_path.exists())

    def test_schema_mismatch_fails_closed(self):
        connection = sqlite3.connect(self.adapter.database_path)
        connection.execute("ALTER TABLE settings RENAME TO wrong_table")
        connection.execute("CREATE TABLE settings (setting_id text, setting_value text)")
        connection.commit()
        connection.close()
        with self.assertRaises(PrivateResourceCompatibilityError):
            self.adapter.capture(self.declaration)

    def test_application_changes_only_owned_rows_and_requires_reload(self):
        result = self.adapter.apply(
            self.declaration,
            _overlay(
                StructuredPrivateValue("trakt.token", "string", SECRET),
                StructuredPrivateValue("pm.token", "string", "fake-pm-token"),
            ),
        )
        self.assertTrue(result.succeeded)
        self.assertFalse(result.restart_required)
        self.assertNotIn(SECRET, json.dumps(result.to_dict()))
        connection = sqlite3.connect(self.adapter.database_path)
        rows = dict(connection.execute("SELECT setting_id, setting_value FROM settings"))
        connection.close()
        self.assertEqual(rows["trakt.token"], SECRET)
        self.assertEqual(rows["pm.token"], "fake-pm-token")
        self.assertEqual(rows["ordinary.preference"], "keep-me")
        self.assertEqual(rows["generated.name"], "generated")
        self.assertEqual(rows["unknown.row"], "untouched")

    def test_undeclared_and_wrong_typed_values_fail_before_mutation(self):
        with self.assertRaises(PrivateResourceValidationError):
            validate_resource_overlay(_overlay(StructuredPrivateValue("unknown.row", "string", SECRET)), self.declaration)
        with self.assertRaises(PrivateResourceValidationError):
            validate_resource_overlay(_overlay(StructuredPrivateValue("trakt.token", "bool", True)), self.declaration)
        with self.assertRaises(PrivateResourceValidationError):
            validate_resource_overlay(_overlay(), self.declaration)

    def test_overlay_serialization_and_store_are_secret_blind_except_protected_values(self):
        overlay = PrivateOverlay("resource-overlay", "bm017c", (), resources=(_overlay(StructuredPrivateValue("trakt.token", "string", SECRET)),))
        self.assertNotIn(SECRET, json.dumps(overlay.safe_dict()))
        self.assertIn(SECRET, json.dumps(overlay.to_dict()))
        store = PrivateOverlayStore(self.root / "profile")
        store.save(overlay)
        loaded = store.load("resource-overlay")
        self.assertEqual(loaded.resources, overlay.resources)

    def test_private_overlay_manager_applies_structured_resource_without_normal_settings(self):
        overlay = PrivateOverlay("resource-overlay", "bm017c", (), resources=(_overlay(StructuredPrivateValue("trakt.token", "string", SECRET)),))
        store = PrivateOverlayStore(self.root / "manager-profile")
        store.save(overlay)
        manager = PrivateOverlayManager(
            ConfigurationManager(NullBackend()),
            store=store,
            structured_resource_manager=StructuredPrivateResourceManager({self.adapter.adapter_id: self.adapter}),
        )
        prepared = manager.prepare(
            type("Ref", (), {"type": "local_file", "overlay_id": "resource-overlay", "required": True})(),
            (), build_id="bm017c", resource_declarations=(self.declaration,),
        )
        result = manager.apply(prepared)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.resource_results[0].resource_id, REDLIGHT_RESOURCE_ID)

    def test_manifest_accepts_resource_metadata_without_values_or_paths(self):
        document = {
            "schema_version": 1,
            "build": {"id": "bm017c", "version": "1.0.0"},
            "config": {"structured_private_resources": [{
                "resource_type": "sqlite.settings",
                "owner_addon_id": REDLIGHT_ADDON_ID,
                "supported_versions": ["2.6.8"],
                "schema_id": REDLIGHT_SCHEMA_ID,
                "resource_id": REDLIGHT_RESOURCE_ID,
                "adapter_id": "redlight.sqlite.settings.v1",
                "fields": [{"field_id": "trakt.token", "type": "string", "sensitivity": "token"}],
            }]},
        }
        manifest = load_manifest_json(json.dumps(document))
        self.assertEqual(manifest.config.structured_private_resources[0].resource_id, REDLIGHT_RESOURCE_ID)
        self.assertNotIn(SECRET, json.dumps(document))


if __name__ == "__main__":
    unittest.main()
