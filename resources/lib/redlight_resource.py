"""Red Light 2.6.8 structured private-resource adapter (BM-017C).

The public Red Light settings import path replaces whole mixed databases and
is UI-driven, so it is not a Build Manager application API.  This adapter is a
deliberately narrow fallback: it accepts only the audited settings table,
only declared string fields, and only when the owner has quiesced Red Light.
It never creates a database, changes journal mode, writes undeclared rows, or
claims that an active runtime cache has been refreshed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

from resources.lib.private_resource import (
    PrivateResourceCompatibilityError,
    PrivateResourceLifecycleError,
    PrivateResourceLockError,
    PrivateResourceNotInitializedError,
    PrivateResourceValidationError,
    ResourceFieldResult,
    ResourceLifecycle,
    StructuredPrivateResourceAdapter,
    StructuredPrivateResourceDeclaration,
    StructuredPrivateResourceOverlay,
    StructuredPrivateValue,
    StructuredResourceFieldDeclaration,
    StructuredResourceResult,
    validate_resource_overlay,
)


REDLIGHT_ADDON_ID = "plugin.video.redlight"
REDLIGHT_VERSION = "2.6.8"
REDLIGHT_RESOURCE_ID = "redlight.settings"
REDLIGHT_SCHEMA_ID = "redlight-settings-v1"
REDLIGHT_RESOURCE_TYPE = "sqlite.settings"
REDLIGHT_ADAPTER_ID = "redlight.sqlite.settings.v1"
REDLIGHT_SETTINGS_RELATIVE_PATH = "databases/settings.db"
REDLIGHT_SETTINGS_COLUMNS = ("setting_id", "setting_type", "setting_default", "setting_value")


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
    ) -> None:
        self._profile_root = Path(profile_root).resolve()
        self._addon_version = addon_version
        self._lifecycle = lifecycle
        self._initialized = initialized

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

    def _validate_lifecycle(self) -> None:
        if not self._initialized or not self.database_path.is_file():
            raise PrivateResourceNotInitializedError("Red Light settings resource is not initialized")
        if self._lifecycle is not ResourceLifecycle.QUIESCED:
            raise PrivateResourceLifecycleError(
                "Red Light must be quiesced; active runtime cache invalidation is not implicit"
            )

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
        self._validate_lifecycle()
        try:
            validate_resource_overlay(overlay, declaration)
        except PrivateResourceValidationError:
            raise
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
                REDLIGHT_RESOURCE_ID, "applied", True, tuple(results),
                "rows committed; Red Light restart/reload is required before live use",
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
