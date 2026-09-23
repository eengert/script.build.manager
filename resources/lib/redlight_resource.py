"""Red Light 2.6.8 structured private-resource adapter (BM-017C).

The public Red Light settings import path replaces whole mixed databases and
is UI-driven, so it is not a Build Manager application API. This adapter
accepts only the audited settings table, only declared string fields, and only
when the owner is held disabled. For a fresh destination it creates the
settings table from Red Light's exact package schema/default declarations,
then applies only owned rows; it does not run service, provider, or auth setup.
"""

from __future__ import annotations

import sqlite3
import importlib
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

from resources.lib.private_resource import (
    PrivateResourceCompatibilityError,
    PrivateResourceError,
    PrivateResourceLifecycleError,
    PrivateResourceLockError,
    PrivateResourceNotInitializedError,
    PrivateResourceValidationError,
    ResourceFieldResult,
    ResourceInitializationCause,
    ResourceInitializationStage,
    ResourceLifecycle,
    StructuredPrivateResourceAdapter,
    StructuredPrivateResourceDeclaration,
    StructuredPrivateResourceOverlay,
    StructuredPrivateValue,
    StructuredResourceFieldDeclaration,
    StructuredResourceResult,
    validate_resource_overlay,
)
from resources.lib.installed_addon_source import (
    PrivateResourceOwnerContext,
    VerifiedInstalledAddonSource,
)


REDLIGHT_ADDON_ID = "plugin.video.redlight"
REDLIGHT_VERSION = "2.6.8"
REDLIGHT_RESOURCE_ID = "redlight.settings"
REDLIGHT_SCHEMA_ID = "redlight-settings-v1"
REDLIGHT_RESOURCE_TYPE = "sqlite.settings"
REDLIGHT_ADAPTER_ID = "redlight.sqlite.settings.v1"
REDLIGHT_SETTINGS_RELATIVE_PATH = "databases/settings.db"
REDLIGHT_SETTINGS_COLUMNS = ("setting_id", "setting_type", "setting_default", "setting_value")
_REDLIGHT_INITIALIZER_LOCK = threading.RLock()


def redlight_declaration(
    fields: Sequence[StructuredResourceFieldDeclaration] | None = None,
) -> StructuredPrivateResourceDeclaration:
    """Return the exact-version public declaration for audited auth fields."""
    if fields is None:
        fields = tuple(
            StructuredResourceFieldDeclaration(field_id, "string", False, sensitivity)
            for field_id, sensitivity in (
                ("mdblist.refresh", "token"),
                ("mdblist.token", "token"),
                ("mdblist.user", "private_identifier"),
                ("pm.account_id", "private_identifier"),
                ("pm.token", "token"),
                ("tb.token", "token"),
                ("trakt.expires", "private_identifier"),
                ("trakt.refresh", "token"),
                ("trakt.token", "token"),
                ("trakt.user", "private_identifier"),
            )
        )
    return StructuredPrivateResourceDeclaration(
        resource_type=REDLIGHT_RESOURCE_TYPE,
        owner_addon_id=REDLIGHT_ADDON_ID,
        supported_versions=(REDLIGHT_VERSION,),
        schema_id=REDLIGHT_SCHEMA_ID,
        resource_id=REDLIGHT_RESOURCE_ID,
        fields=tuple(fields),
        adapter_id=REDLIGHT_ADAPTER_ID,
        lifecycle=ResourceLifecycle.QUIESCED.value,
        required=True,
        configure_before_activation=True,
    )


class RedLightSettingsAdapter(StructuredPrivateResourceAdapter):
    """Row-scoped adapter for a quiesced Red Light settings database."""

    adapter_id = REDLIGHT_ADAPTER_ID

    def __init__(
        self,
        profile_root: str | Path,
        *,
        addon_version: str = REDLIGHT_VERSION,
        lifecycle: ResourceLifecycle = ResourceLifecycle.ACTIVE,
        initialized: bool = False,
        activation_hold_provider: Optional[Callable[[str], bool]] = None,
        enabled_state_provider: Optional[Callable[[str], Optional[bool]]] = None,
    ) -> None:
        self._profile_root = Path(profile_root).resolve()
        self._addon_version = addon_version
        self._lifecycle = lifecycle
        self._initialized = initialized
        self._activation_hold_provider = activation_hold_provider
        self._enabled_state_provider = enabled_state_provider

    @property
    def database_path(self) -> Path:
        return (
            self._profile_root / "addon_data" / REDLIGHT_ADDON_ID
            / REDLIGHT_SETTINGS_RELATIVE_PATH
        )

    def _validate_declaration(self, declaration: StructuredPrivateResourceDeclaration) -> None:
        if declaration.resource_id != REDLIGHT_RESOURCE_ID:
            raise PrivateResourceCompatibilityError("unsupported Red Light resource")
        if declaration.owner_addon_id != REDLIGHT_ADDON_ID:
            raise PrivateResourceCompatibilityError("unsupported Red Light owner")
        if declaration.schema_id != REDLIGHT_SCHEMA_ID:
            raise PrivateResourceCompatibilityError("unsupported Red Light schema")
        if self._addon_version not in declaration.supported_versions:
            raise PrivateResourceCompatibilityError("unsupported Red Light version")
        if declaration.lifecycle != ResourceLifecycle.QUIESCED.value:
            raise PrivateResourceLifecycleError("Red Light resource must require quiesced lifecycle")
        if any(field.value_type != "string" for field in declaration.fields):
            raise PrivateResourceCompatibilityError("Red Light settings schema supports string fields only")

    def _validate_quiescence(self) -> None:
        if self._lifecycle is not ResourceLifecycle.QUIESCED:
            raise PrivateResourceLifecycleError(
                "Red Light must be quiesced; active runtime cache invalidation is not implicit"
            )
        if self._activation_hold_provider is None or self._enabled_state_provider is None:
            raise PrivateResourceLifecycleError(
                "Red Light activation hold and disabled state are required"
            )
        try:
            held = self._activation_hold_provider(REDLIGHT_ADDON_ID)
            enabled = self._enabled_state_provider(REDLIGHT_ADDON_ID)
        except Exception as exc:
            raise PrivateResourceLifecycleError(
                "Red Light activation hold could not be verified"
            ) from exc
        if held is not True:
            raise PrivateResourceLifecycleError(
                "Red Light activation hold is not active"
            )
        if enabled is not False:
            raise PrivateResourceLifecycleError(
                "Red Light owner must remain disabled during resource mutation"
            )

    def _validate_lifecycle(self) -> None:
        self._validate_quiescence()
        if not self._initialized or not self.database_path.is_file():
            raise PrivateResourceNotInitializedError("Red Light settings resource is not initialized")

    def initialize(
        self,
        declaration: StructuredPrivateResourceDeclaration,
        context: Optional[PrivateResourceOwnerContext] = None,
    ) -> StructuredResourceResult:
        """Create a fresh Red Light settings resource from verified package code.

        Existing non-empty databases are only verified. An absent or strictly
        empty database is seeded with the exact package's static defaults and
        pure fresh-install value normalizer. Any partial, incompatible, or
        uncertain resource fails closed without deletion or migration repair.
        """
        last_completed_stage = None

        def run_stage(
            stage,
            cause,
            operation,
            *,
            expected_exceptions=(),
        ):
            nonlocal last_completed_stage
            try:
                result = operation()
            except Exception as exc:
                known_failure = (
                    isinstance(exc, PrivateResourceError)
                    or bool(expected_exceptions and isinstance(exc, expected_exceptions))
                )
                failure_cause = (
                    cause
                    if known_failure
                    else ResourceInitializationCause.INITIALIZATION_STAGE_FAILED
                )
                safe_message = "Red Light resource initialization failed safely"
                if isinstance(exc, PrivateResourceError):
                    try:
                        failure = type(exc)(safe_message)
                    except Exception:
                        failure = PrivateResourceNotInitializedError(safe_message)
                else:
                    failure = PrivateResourceNotInitializedError(safe_message)
                failure.initialization_stage = stage
                failure.initialization_cause_code = failure_cause
                failure.last_completed_stage = last_completed_stage
                raise failure from None
            last_completed_stage = stage
            return result

        def validate_declaration():
            self._validate_declaration(declaration)
            if self._addon_version != REDLIGHT_VERSION:
                raise PrivateResourceCompatibilityError(
                    "Red Light initializer version is unsupported"
                )

        run_stage(
            ResourceInitializationStage.VALIDATE_RESOURCE_DECLARATION,
            ResourceInitializationCause.RESOURCE_DECLARATION_INVALID,
            validate_declaration,
        )
        with _REDLIGHT_INITIALIZER_LOCK:
            def inspect_existing_resource():
                path_existed = self.database_path.exists()
                has_rows = False
                if path_existed:
                    self._verify_database()
                    has_rows = self._has_settings_rows()
                return path_existed, has_rows

            path_existed, has_rows = run_stage(
                ResourceInitializationStage.VALIDATE_EXISTING_RESOURCE,
                ResourceInitializationCause.EXISTING_RESOURCE_VALIDATION_FAILED,
                inspect_existing_resource,
                expected_exceptions=(OSError, sqlite3.Error),
            )
            if path_existed and has_rows:
                self._initialized = True
                return StructuredResourceResult(
                    REDLIGHT_RESOURCE_ID,
                    "already_initialized",
                    False,
                    (),
                    "Red Light settings resource initialized and verified",
                )

            def revalidate_source():
                self._validate_quiescence()
                return self._verified_source_context(declaration, context)

            installed_source = run_stage(
                ResourceInitializationStage.SOURCE_REVALIDATION,
                ResourceInitializationCause.SOURCE_REVALIDATION_FAILED,
                revalidate_source,
            )
            (
                settings_table_creators,
                default_settings,
                new_setting_value,
                set_property,
                settings_db_synced_property,
                settings_sync_fingerprint_property,
            ) = self._redlight_initializers(installed_source, run_stage)
            def validate_empty_before_initialization():
                if not self._settings_database_is_empty():
                    raise PrivateResourceCompatibilityError(
                        "Red Light settings cache disagrees with the empty database"
                    )

            run_stage(
                ResourceInitializationStage.VALIDATE_RESOURCE_EMPTY,
                ResourceInitializationCause.RESOURCE_STATE_VALIDATION_FAILED,
                validate_empty_before_initialization,
                expected_exceptions=(OSError, sqlite3.Error),
            )
            if not path_existed:
                self._ensure_settings_database(settings_table_creators, run_stage)

            def validate_empty_before_defaults():
                if not self._settings_database_is_empty():
                    raise PrivateResourceCompatibilityError(
                        "Red Light settings changed before default initialization"
                    )

            run_stage(
                ResourceInitializationStage.VALIDATE_RESOURCE_EMPTY,
                ResourceInitializationCause.RESOURCE_STATE_VALIDATION_FAILED,
                validate_empty_before_defaults,
                expected_exceptions=(OSError, sqlite3.Error),
            )

            def initialize_defaults():
                rows = self._fresh_default_rows(default_settings, new_setting_value)
                if not rows:
                    raise PrivateResourceNotInitializedError(
                        "Red Light package supplied no fresh default settings"
                    )
                self._write_default_rows(rows)
                return rows

            run_stage(
                ResourceInitializationStage.INSERT_DEFAULTS,
                ResourceInitializationCause.DEFAULT_INITIALIZATION_FAILED,
                initialize_defaults,
                expected_exceptions=(sqlite3.Error,),
            )

            def verify_initialized_resource():
                if self._settings_database_is_empty():
                    raise PrivateResourceNotInitializedError(
                        "Red Light default settings were not persisted"
                    )
                self._verify_database()
            run_stage(
                ResourceInitializationStage.FINAL_RESOURCE_VALIDATION,
                ResourceInitializationCause.FINAL_VALIDATION_FAILED,
                verify_initialized_resource,
                expected_exceptions=(OSError, sqlite3.Error),
            )

            # Keep the exact fresh-install boot markers used by Red Light's
            # service, without calling its Addon(id)-based version/profile
            # helpers or running its broader sync/bootstrap path.
            def publish_markers():
                try:
                    set_property(settings_db_synced_property, "true")
                    set_property(
                        settings_sync_fingerprint_property,
                        f"{installed_source.version}:{len(default_settings())}",
                    )
                except Exception:
                    raise PrivateResourceNotInitializedError(
                        "Red Light initialization markers could not be published"
                    ) from None

            run_stage(
                ResourceInitializationStage.PUBLISH_SYNC_MARKER,
                ResourceInitializationCause.MARKER_PUBLICATION_FAILED,
                publish_markers,
            )
            self._initialized = True
            return StructuredResourceResult(
                REDLIGHT_RESOURCE_ID,
                "initialized",
                False,
                (),
                "Red Light settings resource initialized and verified",
            )

    def _has_settings_rows(self) -> bool:
        """Read only whether the owner settings table has at least one row."""
        connection = None
        try:
            uri = f"file:{self.database_path}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=0.5)
            self._validate_schema(connection)
            return connection.execute(
                "SELECT 1 FROM settings LIMIT 1"
            ).fetchone() is not None
        except sqlite3.Error:
            raise PrivateResourceCompatibilityError(
                "Red Light settings rows cannot be verified safely"
            ) from None
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _fresh_default_rows(default_settings, new_setting_value):
        """Build only exact package defaults for a genuinely empty database."""
        settings = default_settings()
        if not isinstance(settings, (tuple, list)) or not settings:
            raise PrivateResourceNotInitializedError(
                "Red Light package defaults are unavailable"
            )
        rows = []
        seen = set()
        for item in settings:
            if not isinstance(item, dict):
                raise PrivateResourceCompatibilityError(
                    "Red Light package default declaration is malformed"
                )
            setting_id = item.get("setting_id")
            setting_type = item.get("setting_type")
            setting_default = item.get("setting_default")
            if (
                not isinstance(setting_id, str) or not setting_id
                or setting_id in seen
                or not isinstance(setting_type, str) or not setting_type
                or not isinstance(setting_default, str)
            ):
                raise PrivateResourceCompatibilityError(
                    "Red Light package default identity is unsupported"
                )
            seen.add(setting_id)
            value = new_setting_value(
                setting_id,
                setting_default,
                {},
                False,
                fresh_install=True,
            )
            if not isinstance(value, str):
                raise PrivateResourceCompatibilityError(
                    "Red Light package default value is not a string"
                )
            options = item.get("settings_options")
            if setting_type == "action" and options is not None:
                if not isinstance(options, dict) or setting_default not in options:
                    raise PrivateResourceCompatibilityError(
                        "Red Light action default options are malformed"
                    )
                name_default = options[setting_default]
                name_value = options.get(value, name_default)
                rows.append((f"{setting_id}_name", "name", name_default, name_value))
            rows.append((setting_id, setting_type, setting_default, value))
        return tuple(rows)

    def _verified_source_context(
        self,
        declaration: StructuredPrivateResourceDeclaration,
        context: Optional[PrivateResourceOwnerContext],
    ) -> VerifiedInstalledAddonSource:
        if (
            context is None
            or not context.matches(REDLIGHT_ADDON_ID, self._addon_version)
            or context.expected_version not in declaration.supported_versions
        ):
            raise PrivateResourceNotInitializedError(
                "verified held Red Light source context is unavailable"
            )
        try:
            source = context.installed_source.revalidate()
        except Exception:
            raise PrivateResourceNotInitializedError(
                "verified Red Light installed source changed before initialization"
            ) from None
        if (
            source.addon_id != declaration.owner_addon_id
            or source.version != self._addon_version
            or source.installed_root.name != REDLIGHT_ADDON_ID
        ):
            raise PrivateResourceCompatibilityError(
                "verified Red Light source identity does not match the resource owner"
            )
        return source

    def _settings_database_is_empty(self) -> bool:
        if not self.database_path.exists():
            return True
        return not self._has_settings_rows()

    def _ensure_settings_database(self, table_creators, run_stage) -> None:
        def load_schema_declaration():
            statements = table_creators().get("settings_db")
            if not isinstance(statements, tuple) or not statements or any(
                not isinstance(statement, str) or not statement.strip()
                for statement in statements
            ):
                raise PrivateResourceCompatibilityError(
                    "Red Light settings schema declaration is unavailable"
                )
            return statements

        statements = run_stage(
            ResourceInitializationStage.LOAD_SCHEMA_DECLARATION,
            ResourceInitializationCause.SCHEMA_DECLARATION_FAILED,
            load_schema_declaration,
            expected_exceptions=(AttributeError, TypeError),
        )
        run_stage(
            ResourceInitializationStage.CREATE_ADDON_DATA_DIRECTORY,
            ResourceInitializationCause.DIRECTORY_CREATION_FAILED,
            lambda: (self._profile_root / "addon_data").mkdir(
                parents=True, exist_ok=True
            ),
            expected_exceptions=(OSError,),
        )
        run_stage(
            ResourceInitializationStage.CREATE_DATABASE_DIRECTORY,
            ResourceInitializationCause.DIRECTORY_CREATION_FAILED,
            lambda: self.database_path.parent.mkdir(
                parents=True, exist_ok=True
            ),
            expected_exceptions=(OSError,),
        )
        connection = run_stage(
            ResourceInitializationStage.OPEN_SETTINGS_DATABASE,
            ResourceInitializationCause.DATABASE_OPEN_FAILED,
            lambda: sqlite3.connect(self.database_path, timeout=0.5),
            expected_exceptions=(sqlite3.Error,),
        )
        try:
            def set_wal_mode():
                row = connection.execute(
                    "PRAGMA journal_mode = WAL"
                ).fetchone()
                if not row or str(row[0]).lower() != "wal":
                    raise PrivateResourceCompatibilityError(
                        "Red Light settings database could not enter audited WAL mode"
                    )

            run_stage(
                ResourceInitializationStage.SET_WAL_MODE,
                ResourceInitializationCause.WAL_SETUP_FAILED,
                set_wal_mode,
                expected_exceptions=(sqlite3.Error,),
            )

            def create_schema():
                try:
                    for statement in statements:
                        connection.execute(statement)
                    connection.commit()
                finally:
                    connection.close()

            run_stage(
                ResourceInitializationStage.CREATE_SCHEMA,
                ResourceInitializationCause.SCHEMA_CREATION_FAILED,
                create_schema,
                expected_exceptions=(sqlite3.Error,),
            )
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            raise

    def _write_default_rows(self, rows) -> None:
        connection = None
        try:
            connection = sqlite3.connect(self.database_path, timeout=0.5)
            connection.executemany(
                "INSERT OR REPLACE INTO settings VALUES (?, ?, ?, ?)", rows
            )
            connection.commit()
        except sqlite3.Error as exc:
            if connection is not None:
                connection.rollback()
            raise PrivateResourceNotInitializedError(
                "Red Light package defaults could not be persisted"
            ) from None
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _redlight_initializers(
        installed_source: VerifiedInstalledAddonSource,
        run_stage,
    ):
        """Import the audited package defaults from a revalidated installed root.

        Only static package defaults, their pure fresh-install value helper,
        and the package-owned settings-table declaration are used. The package
        profile helper, settings sync, provider setup, and service entry points
        are intentionally never called here.
        """
        verified = run_stage(
            ResourceInitializationStage.SOURCE_REVALIDATION,
            ResourceInitializationCause.SOURCE_REVALIDATION_FAILED,
            installed_source.revalidate,
            expected_exceptions=(OSError, ValueError),
        )
        addon_path = verified.installed_root

        def load_helpers():
            for top_level in ("caches", "modules"):
                loaded = sys.modules.get(top_level)
                origin = getattr(loaded, "__file__", None) if loaded else None
                if origin is not None:
                    try:
                        Path(origin).resolve().relative_to(addon_path)
                    except ValueError:
                        raise PrivateResourceCompatibilityError(
                            "Red Light helper namespace is already occupied"
                        ) from None

            inserted = str(addon_path) not in sys.path
            if inserted:
                sys.path.insert(0, str(addon_path))
            try:
                base_cache = importlib.import_module("caches.base_cache")
                settings_cache_module = importlib.import_module("caches.settings_cache")
                kodi_utils = importlib.import_module("modules.kodi_utils")
                table_creators = getattr(base_cache, "table_creators")
                default_settings = getattr(settings_cache_module, "default_settings")
                new_setting_value = getattr(settings_cache_module, "_new_setting_value")
                settings_db_synced_property = getattr(
                    settings_cache_module, "_SETTINGS_DB_SYNCED"
                )
                settings_sync_fingerprint_property = getattr(
                    settings_cache_module, "_SETTINGS_SYNC_FINGERPRINT"
                )
                set_property = getattr(kodi_utils, "set_property")

                return (
                    table_creators,
                    default_settings,
                    new_setting_value,
                    set_property,
                    settings_db_synced_property,
                    settings_sync_fingerprint_property,
                )
            finally:
                if inserted:
                    try:
                        sys.path.remove(str(addon_path))
                    except ValueError:
                        pass
                # Kodi gives each add-on invoker its own Python interpreter.
                # Clear this bounded import set so later Build Manager calls
                # cannot reuse the package-level cache accidentally.
                for name, module in tuple(sys.modules.items()):
                    if name.split(".", 1)[0] not in {"caches", "modules"}:
                        continue
                    origin = getattr(module, "__file__", None)
                    if origin is None:
                        continue
                    try:
                        Path(origin).resolve().relative_to(addon_path)
                    except ValueError:
                        continue
                    sys.modules.pop(name, None)

        return run_stage(
            ResourceInitializationStage.LOAD_INITIALIZER_DECLARATIONS,
            ResourceInitializationCause.INITIALIZER_IMPORT_FAILED,
            load_helpers,
            expected_exceptions=(ImportError, AttributeError),
        )

    def _verify_database(self) -> None:
        if not self.database_path.is_file():
            raise PrivateResourceNotInitializedError(
                "Red Light settings database is absent"
            )
        connection = None
        try:
            uri = f"file:{self.database_path}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=0.5)
            journal_mode = str(
                connection.execute("PRAGMA journal_mode").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise PrivateResourceCompatibilityError(
                    "Red Light settings database is not using audited WAL mode"
                )
            self._validate_schema(connection)
        except PrivateResourceCompatibilityError:
            raise
        except sqlite3.Error as exc:
            raise PrivateResourceCompatibilityError(
                "Red Light settings database cannot be verified safely"
            ) from None
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(settings)"))
        if columns != REDLIGHT_SETTINGS_COLUMNS:
            raise PrivateResourceCompatibilityError("Red Light settings schema is unsupported")
        declared_types = tuple(str(row[2]).lower() for row in connection.execute("PRAGMA table_info(settings)"))
        if declared_types != ("text", "text", "text", "text"):
            raise PrivateResourceCompatibilityError("Red Light settings column types are unsupported")

    def _open_read_only(self) -> sqlite3.Connection:
        self._validate_lifecycle()
        uri = f"file:{self.database_path}?mode=ro"
        connection = None
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=0.5)
            self._validate_schema(connection)
            return connection
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise PrivateResourceCompatibilityError("Red Light settings database cannot be read safely") from exc

    def _verify_overlay_values(
        self,
        declaration: StructuredPrivateResourceDeclaration,
        overlay: StructuredPrivateResourceOverlay,
    ) -> StructuredResourceResult:
        self._verify_database()
        connection = None
        results = []
        matched = True
        try:
            uri = f"file:{self.database_path}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=0.5)
            self._validate_schema(connection)
            for value in overlay.values:
                row = connection.execute(
                    "SELECT setting_type, setting_value FROM settings WHERE setting_id = ?",
                    (value.field_id,),
                ).fetchone()
                if row is None:
                    matched = False
                    results.append(ResourceFieldResult(
                        value.field_id, "missing", False, False,
                        "declared field is not initialized",
                    ))
                    continue
                if str(row[0]).lower() != "string":
                    raise PrivateResourceCompatibilityError(
                        "Red Light field type is unsupported"
                    )
                same = row[1] == value.value
                matched = matched and same
                results.append(ResourceFieldResult(
                    value.field_id,
                    "unchanged" if same else "mismatch",
                    same,
                    False,
                    "field was verified" if same else "declared field needs configuration",
                ))
        except sqlite3.Error as exc:
            raise PrivateResourceCompatibilityError(
                "Red Light settings values cannot be verified safely"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        return StructuredResourceResult(
            REDLIGHT_RESOURCE_ID,
            "applied" if matched else "not_applied",
            False,
            tuple(results),
            "declared Red Light fields were verified" if matched
            else "declared Red Light fields need configuration",
        )

    def verify(
        self,
        declaration: StructuredPrivateResourceDeclaration,
        overlay: StructuredPrivateResourceOverlay,
    ) -> StructuredResourceResult:
        self._validate_declaration(declaration)
        validate_resource_overlay(overlay, declaration)
        return self._verify_overlay_values(declaration, overlay)

    def capture(self, declaration: StructuredPrivateResourceDeclaration):
        self._validate_declaration(declaration)
        connection = self._open_read_only()
        try:
            values = []
            results = []
            field_map = declaration.field_map
            for field in declaration.fields:
                row = connection.execute(
                    "SELECT setting_type, setting_value FROM settings WHERE setting_id = ?",
                    (field.field_id,),
                ).fetchone()
                if row is None:
                    if field.required:
                        raise PrivateResourceNotInitializedError("required Red Light field is absent")
                    results.append(ResourceFieldResult(field.field_id, "absent", True, False, "optional field absent"))
                    continue
                if str(row[0]).lower() != "string":
                    raise PrivateResourceCompatibilityError("Red Light field type is unsupported")
                values.append(StructuredPrivateValue(field.field_id, field.value_type, row[1]))
                results.append(ResourceFieldResult(field.field_id, "captured", True, False, "field captured"))
            overlay = StructuredPrivateResourceOverlay(
                REDLIGHT_RESOURCE_ID, REDLIGHT_ADDON_ID, self._addon_version,
                REDLIGHT_SCHEMA_ID, tuple(values),
            )
            return overlay, StructuredResourceResult(
                REDLIGHT_RESOURCE_ID, "captured", True, tuple(results),
                "captured in memory; runtime reload remains explicit",
            )
        finally:
            connection.close()

    def apply(self, declaration: StructuredPrivateResourceDeclaration, overlay: StructuredPrivateResourceOverlay):
        self._validate_declaration(declaration)
        try:
            validate_resource_overlay(overlay, declaration)
        except PrivateResourceValidationError:
            raise
        verification = self._verify_overlay_values(declaration, overlay)
        if verification.succeeded:
            return verification
        self._validate_lifecycle()
        connection = None
        try:
            connection = sqlite3.connect(str(self.database_path), timeout=0.5, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 500")
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if journal_mode != "wal":
                raise PrivateResourceCompatibilityError("Red Light settings database is not using audited WAL mode")
            self._validate_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            results = []
            for value in overlay.values:
                row = connection.execute(
                    "SELECT setting_type, setting_value FROM settings WHERE setting_id = ?",
                    (value.field_id,),
                ).fetchone()
                if row is None:
                    raise PrivateResourceNotInitializedError("declared Red Light field is absent")
                if str(row[0]).lower() != "string":
                    raise PrivateResourceCompatibilityError("Red Light field type is unsupported")
                before = row[1]
                connection.execute(
                    "UPDATE settings SET setting_value = ? WHERE setting_id = ?",
                    (value.value, value.field_id),
                )
                after = connection.execute(
                    "SELECT setting_value FROM settings WHERE setting_id = ?",
                    (value.field_id,),
                ).fetchone()
                if after is None or after[0] != value.value:
                    raise PrivateResourceCompatibilityError("Red Light row read-back failed")
                results.append(ResourceFieldResult(
                    value.field_id, "updated" if before != value.value else "unchanged",
                    True, before != value.value, "field was verified",
                ))
            connection.commit()
            return StructuredResourceResult(
                REDLIGHT_RESOURCE_ID, "applied", False, tuple(results),
                "rows committed and verified before Red Light activation",
            )
        except sqlite3.OperationalError as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise PrivateResourceLockError("Red Light settings database is locked") from exc
            raise PrivateResourceCompatibilityError("Red Light settings application failed safely") from exc
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise
        finally:
            if connection is not None:
                connection.close()
