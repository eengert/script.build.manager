"""BM-017C fake structured-resource, Red Light schema, and secret-safety tests."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

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
    ResourceLifecycle,
    StructuredPrivateResourceManager,
    StructuredPrivateResourceOverlay,
    StructuredPrivateValue,
    StructuredResourceFieldDeclaration,
    validate_resource_overlay,
)
from resources.lib.redlight_resource import (
    REDLIGHT_ADDON_ID,
    REDLIGHT_RESOURCE_ID,
    REDLIGHT_SCHEMA_ID,
    RedLightSettingsAdapter,
    redlight_declaration,
)


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

    def test_fresh_initialization_uses_only_bounded_package_default_helpers(self):
        from unittest.mock import patch

        database_path = self.adapter.database_path
        database_path.unlink()
        calls = []

        def ensure_database_tables(database_name):
            calls.append(("ensure", database_name))
            database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(database_path)
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE settings (setting_id text not null unique, setting_type text, setting_default text, setting_value text)"
            )
            connection.commit()
            connection.close()

        class SettingsCache:
            def is_empty_strict(inner):
                if not database_path.exists():
                    return True
                connection = sqlite3.connect(database_path)
                try:
                    return connection.execute("SELECT 1 FROM settings LIMIT 1").fetchone() is None
                finally:
                    connection.close()

            def set_many(inner, rows, *, load_properties=True):
                calls.append(("set_many", tuple(rows), load_properties))
                connection = sqlite3.connect(database_path)
                connection.executemany(
                    "INSERT OR REPLACE INTO settings VALUES (?, ?, ?, ?)", rows
                )
                connection.commit()
                connection.close()

            def clear_db_cache(inner):
                calls.append(("clear_db_cache",))

        defaults = (
            {"setting_id": "trakt.token", "setting_type": "string", "setting_default": ""},
            {
                "setting_id": "example.action",
                "setting_type": "action",
                "setting_default": "one",
                "settings_options": {"one": "One", "two": "Two"},
            },
        )

        def default_settings():
            calls.append(("default_settings",))
            return defaults

        def new_setting_value(setting_id, setting_default, current, had_existing, *, fresh_install):
            calls.append(("new_value", setting_id, dict(current), had_existing, fresh_install))
            return setting_default

        def mark_defaults_initialized():
            calls.append(("mark_defaults_initialized",))

        settings_cache = SettingsCache()
        helpers = (
            ensure_database_tables,
            default_settings,
            new_setting_value,
            settings_cache,
            lambda: str(self.root / "addon_data" / REDLIGHT_ADDON_ID),
            mark_defaults_initialized,
        )
        with patch.object(self.adapter, "_redlight_initializers", return_value=helpers):
            result = self.adapter.initialize(self.declaration)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.outcome, "initialized")
        self.assertEqual(calls[0], ("ensure", "settings_db"))
        self.assertIn(("default_settings",), calls)
        self.assertIn(
            ("new_value", "trakt.token", {}, False, True),
            calls,
        )
        set_call = next(call for call in calls if call[0] == "set_many")
        self.assertFalse(set_call[2])
        self.assertIn(("trakt.token", "string", "", ""), set_call[1])
        self.assertIn(("example.action_name", "name", "One", "One"), set_call[1])
        self.assertIn(("example.action", "action", "one", "one"), set_call[1])
        self.assertFalse(any(call[0] == "sync" for call in calls))
        self.assertIn(("mark_defaults_initialized",), calls)
        verified = self.adapter.apply(
            self.declaration,
            _overlay(StructuredPrivateValue("trakt.token", "string", SECRET)),
        )
        self.assertTrue(verified.succeeded)
        self.assertFalse(verified.restart_required)
        connection = sqlite3.connect(database_path)
        rows = dict(connection.execute("SELECT setting_id, setting_value FROM settings"))
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        connection.close()
        self.assertEqual(rows["trakt.token"], SECRET)
        self.assertEqual(journal_mode.lower(), "wal")

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
