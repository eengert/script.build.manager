"""Secret-safe structured private-resource contracts (BM-017C).

This module is deliberately independent from Kodi and from SQLite.  Public
declarations describe a vetted resource adapter and field ownership; values
exist only in the private overlay object in memory or in the protected local
overlay store.  Adapters own all resource-specific paths, schema checks,
transactions, and lifecycle rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Mapping, Optional, Sequence

from resources.lib.installed_addon_source import PrivateResourceOwnerContext


class ResourceInitializationStage(str, Enum):
    """Safe, typed stages in an owner-specific structured-resource initializer."""

    VALIDATE_RESOURCE_DECLARATION = "VALIDATE_RESOURCE_DECLARATION"
    VALIDATE_EXISTING_RESOURCE = "VALIDATE_EXISTING_RESOURCE"
    SOURCE_REVALIDATION = "SOURCE_REVALIDATION"
    LOAD_INITIALIZER_DECLARATIONS = "LOAD_INITIALIZER_DECLARATIONS"
    LOAD_SCHEMA_DECLARATION = "LOAD_SCHEMA_DECLARATION"
    VALIDATE_RESOURCE_EMPTY = "VALIDATE_RESOURCE_EMPTY"
    CREATE_ADDON_DATA_DIRECTORY = "CREATE_ADDON_DATA_DIRECTORY"
    CREATE_DATABASE_DIRECTORY = "CREATE_DATABASE_DIRECTORY"
    OPEN_SETTINGS_DATABASE = "OPEN_SETTINGS_DATABASE"
    SET_WAL_MODE = "SET_WAL_MODE"
    CREATE_SCHEMA = "CREATE_SCHEMA"
    INSERT_DEFAULTS = "INSERT_DEFAULTS"
    FINAL_RESOURCE_VALIDATION = "FINAL_RESOURCE_VALIDATION"
    PUBLISH_SYNC_MARKER = "PUBLISH_SYNC_MARKER"


class ResourceInitializationCause(str, Enum):
    """Allowlisted causes for safe structured-resource initialization errors."""

    RESOURCE_DECLARATION_INVALID = "RESOURCE_DECLARATION_INVALID"
    EXISTING_RESOURCE_VALIDATION_FAILED = "EXISTING_RESOURCE_VALIDATION_FAILED"
    SOURCE_REVALIDATION_FAILED = "SOURCE_REVALIDATION_FAILED"
    INITIALIZER_IMPORT_FAILED = "INITIALIZER_IMPORT_FAILED"
    SCHEMA_DECLARATION_FAILED = "SCHEMA_DECLARATION_FAILED"
    RESOURCE_STATE_VALIDATION_FAILED = "RESOURCE_STATE_VALIDATION_FAILED"
    DIRECTORY_CREATION_FAILED = "DIRECTORY_CREATION_FAILED"
    DATABASE_OPEN_FAILED = "DATABASE_OPEN_FAILED"
    WAL_SETUP_FAILED = "WAL_SETUP_FAILED"
    SCHEMA_CREATION_FAILED = "SCHEMA_CREATION_FAILED"
    DEFAULT_INITIALIZATION_FAILED = "DEFAULT_INITIALIZATION_FAILED"
    FINAL_VALIDATION_FAILED = "FINAL_VALIDATION_FAILED"
    MARKER_PUBLICATION_FAILED = "MARKER_PUBLICATION_FAILED"
    INITIALIZATION_STAGE_FAILED = "INITIALIZATION_STAGE_FAILED"


class PrivateResourceError(Exception):
    """Base class for fail-closed structured resource errors."""

    code = "PRIVATE_RESOURCE_ERROR"

    def __init__(self, message: str = "") -> None:
        self.initialization_stage: Optional[ResourceInitializationStage] = None
        self.initialization_cause_code: Optional[ResourceInitializationCause] = None
        self.last_completed_stage: Optional[ResourceInitializationStage] = None
        self.import_failure_category = ""
        self.failing_module = ""
        self.expected_provider = ""
        self.actual_provider = ""
        super().__init__(message)


class PrivateResourceValidationError(PrivateResourceError):
    code = "PRIVATE_RESOURCE_INVALID"


class PrivateResourceCompatibilityError(PrivateResourceError):
    code = "PRIVATE_RESOURCE_UNSUPPORTED"


class PrivateResourceNotInitializedError(PrivateResourceError):
    code = "RESOURCE_NOT_INITIALIZED"


class PrivateResourceLifecycleError(PrivateResourceError):
    code = "PRIVATE_RESOURCE_UNSAFE_LIFECYCLE"


class PrivateResourceLockError(PrivateResourceError):
    code = "PRIVATE_RESOURCE_LOCKED"


class StructuredValueType(str, Enum):
    STRING = "string"
    BOOL = "bool"
    INT = "int"
    NUMBER = "number"


class ResourceLifecycle(str, Enum):
    INITIALIZED_IDLE = "initialized_idle"
    ACTIVE = "active"
    QUIESCED = "quiesced"
    RESTART_REQUIRED = "restart_required"


_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ADDON = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_SENSITIVITY = frozenset({"secret", "credential", "token", "private_identifier"})
_TYPES = frozenset(item.value for item in StructuredValueType)
_LIFECYCLES = frozenset(item.value for item in ResourceLifecycle)
_IMPORT_FAILURE_CATEGORY = re.compile(r"^[A-Z0-9_]{1,80}$")
_IMPORT_FAILURE_MODULE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,31}$"
)


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PrivateResourceValidationError(f"{label} is not a safe identifier")
    return value


def _addon(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ADDON.fullmatch(value):
        raise PrivateResourceValidationError(f"{label} is not a safe add-on ID")
    return value


class StructuredResourceInitializationError(PrivateResourceError):
    """Sanitized initialization failure with safe resource ownership metadata."""

    code = "PRIVATE_RESOURCE_INITIALIZATION_FAILED"

    def __init__(
        self,
        owner_addon_id: str,
        resource_id: str,
        cause_code: str | ResourceInitializationCause = "",
        *,
        initialization_stage: Optional[ResourceInitializationStage] = None,
        last_completed_stage: Optional[ResourceInitializationStage] = None,
        import_failure_category: str = "",
        failing_module: str = "",
        expected_provider: str = "",
        actual_provider: str = "",
    ):
        self.owner_addon_id = _addon(owner_addon_id, "resource failure owner")
        self.resource_id = _id(resource_id, "resource failure resource_id")
        super().__init__("structured private resource initialization failed")
        cause_value = (
            cause_code.value
            if isinstance(cause_code, ResourceInitializationCause)
            else cause_code
        )
        self.cause_code = (
            cause_value
            if isinstance(cause_value, str)
            and re.fullmatch(r"[A-Z0-9_]{1,80}", cause_value)
            else ""
        )
        self.initialization_cause_code = (
            cause_code if isinstance(cause_code, ResourceInitializationCause) else None
        )
        self.initialization_stage = (
            initialization_stage
            if isinstance(initialization_stage, ResourceInitializationStage)
            else None
        )
        self.last_completed_stage = (
            last_completed_stage
            if isinstance(last_completed_stage, ResourceInitializationStage)
            else None
        )
        self.import_failure_category = (
            import_failure_category
            if isinstance(import_failure_category, str)
            and _IMPORT_FAILURE_CATEGORY.fullmatch(import_failure_category)
            else ""
        )
        self.failing_module = (
            failing_module
            if isinstance(failing_module, str)
            and _IMPORT_FAILURE_MODULE.fullmatch(failing_module)
            else ""
        )
        self.expected_provider = (
            expected_provider
            if isinstance(expected_provider, str) and _ADDON.fullmatch(expected_provider)
            else ""
        )
        self.actual_provider = (
            actual_provider
            if isinstance(actual_provider, str) and _ADDON.fullmatch(actual_provider)
            else ""
        )


def validate_typed_value(value: object, value_type: StructuredValueType, label: str) -> object:
    valid = (
        isinstance(value, str)
        if value_type is StructuredValueType.STRING
        else isinstance(value, bool)
        if value_type is StructuredValueType.BOOL
        else isinstance(value, int) and not isinstance(value, bool)
        if value_type is StructuredValueType.INT
        else isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    if not valid:
        raise PrivateResourceValidationError(f"{label} has the wrong typed value")
    if value_type is StructuredValueType.NUMBER and not math.isfinite(float(value)):
        raise PrivateResourceValidationError(f"{label} has a non-finite number")
    return value


@dataclass(frozen=True)
class StructuredResourceFieldDeclaration:
    """Public, non-secret declaration for one owned field."""

    field_id: str
    value_type: str
    required: bool = False
    sensitivity: str = "private_identifier"

    def __post_init__(self) -> None:
        _id(self.field_id, "resource field_id")
        if self.value_type not in _TYPES:
            raise PrivateResourceValidationError("resource field type is unsupported")
        if not isinstance(self.required, bool):
            raise PrivateResourceValidationError("resource field required must be boolean")
        if self.sensitivity not in _SENSITIVITY:
            raise PrivateResourceValidationError("resource field sensitivity is unsupported")

    def safe_dict(self) -> dict:
        return {
            "field_id": self.field_id,
            "type": self.value_type,
            "required": self.required,
            "sensitivity": self.sensitivity,
        }


@dataclass(frozen=True)
class StructuredPrivateResourceDeclaration:
    """Public declaration for one vetted structured resource adapter."""

    resource_type: str
    owner_addon_id: str
    supported_versions: tuple[str, ...]
    schema_id: str
    resource_id: str
    fields: tuple[StructuredResourceFieldDeclaration, ...]
    adapter_id: str
    lifecycle: str = ResourceLifecycle.QUIESCED.value
    required: bool = True
    configure_before_activation: bool = False

    def __post_init__(self) -> None:
        _id(self.resource_type, "resource_type")
        _addon(self.owner_addon_id, "owner_addon_id")
        _id(self.schema_id, "schema_id")
        _id(self.resource_id, "resource_id")
        _id(self.adapter_id, "adapter_id")
        if not self.supported_versions or any(not isinstance(v, str) or not v for v in self.supported_versions):
            raise PrivateResourceValidationError("resource supported_versions must be non-empty")
        if len(set(self.supported_versions)) != len(self.supported_versions):
            raise PrivateResourceValidationError("resource supported_versions contains duplicates")
        if self.lifecycle not in _LIFECYCLES:
            raise PrivateResourceValidationError("resource lifecycle is unsupported")
        if not isinstance(self.required, bool):
            raise PrivateResourceValidationError("resource required must be boolean")
        if not isinstance(self.configure_before_activation, bool):
            raise PrivateResourceValidationError(
                "resource configure_before_activation must be boolean"
            )
        if not self.fields:
            raise PrivateResourceValidationError("resource must declare at least one field")
        seen = set()
        for field in self.fields:
            if field.field_id in seen:
                raise PrivateResourceValidationError("resource contains duplicate field ownership")
            seen.add(field.field_id)

    @property
    def field_map(self) -> Mapping[str, StructuredResourceFieldDeclaration]:
        return {field.field_id: field for field in self.fields}

    def safe_dict(self) -> dict:
        return {
            "resource_type": self.resource_type,
            "owner_addon_id": self.owner_addon_id,
            "supported_versions": list(self.supported_versions),
            "schema_id": self.schema_id,
            "resource_id": self.resource_id,
            "fields": [field.safe_dict() for field in self.fields],
            "adapter_id": self.adapter_id,
            "lifecycle": self.lifecycle,
            "required": self.required,
            "configure_before_activation": self.configure_before_activation,
        }


@dataclass(frozen=True, repr=False)
class StructuredPrivateValue:
    field_id: str
    value_type: str
    value: object

    def __post_init__(self) -> None:
        _id(self.field_id, "resource value field_id")
        try:
            value_type = StructuredValueType(self.value_type)
        except ValueError as exc:
            raise PrivateResourceValidationError("resource value type is unsupported") from exc
        validate_typed_value(self.value, value_type, "resource value")

    def safe_dict(self) -> dict:
        return {"field_id": self.field_id, "type": self.value_type}

    def to_dict(self) -> dict:
        return {"field_id": self.field_id, "type": self.value_type, "value": self.value}


@dataclass(frozen=True, repr=False)
class StructuredPrivateResourceOverlay:
    """One resource's values inside the protected private overlay."""

    resource_id: str
    owner_addon_id: str
    addon_version: str
    schema_id: str
    values: tuple[StructuredPrivateValue, ...]

    def __post_init__(self) -> None:
        _id(self.resource_id, "resource overlay resource_id")
        _addon(self.owner_addon_id, "resource overlay owner_addon_id")
        _id(self.schema_id, "resource overlay schema_id")
        if not isinstance(self.addon_version, str) or not self.addon_version:
            raise PrivateResourceValidationError("resource overlay addon_version is required")
        ids = [item.field_id for item in self.values]
        if len(ids) != len(set(ids)):
            raise PrivateResourceValidationError("resource overlay contains duplicate fields")

    def safe_dict(self) -> dict:
        return {
            "resource_id": self.resource_id,
            "owner_addon_id": self.owner_addon_id,
            "addon_version": self.addon_version,
            "schema_id": self.schema_id,
            "values": [item.safe_dict() for item in self.values],
        }

    def to_dict(self) -> dict:
        data = self.safe_dict()
        data["values"] = [item.to_dict() for item in self.values]
        return data

    @classmethod
    def from_dict(cls, raw: object) -> "StructuredPrivateResourceOverlay":
        if not isinstance(raw, dict) or set(raw) != {
            "resource_id", "owner_addon_id", "addon_version", "schema_id", "values"
        }:
            raise PrivateResourceValidationError("resource overlay fields are unsupported")
        values = raw["values"]
        if not isinstance(values, list):
            raise PrivateResourceValidationError("resource overlay values must be an array")
        parsed = []
        for item in values:
            if not isinstance(item, dict) or set(item) != {"field_id", "type", "value"}:
                raise PrivateResourceValidationError("resource overlay value is malformed")
            parsed.append(StructuredPrivateValue(item["field_id"], item["type"], item["value"]))
        return cls(raw["resource_id"], raw["owner_addon_id"], raw["addon_version"], raw["schema_id"], tuple(parsed))


def validate_resource_overlay(
    overlay: StructuredPrivateResourceOverlay,
    declaration: StructuredPrivateResourceDeclaration,
) -> StructuredPrivateResourceOverlay:
    if overlay.resource_id != declaration.resource_id:
        raise PrivateResourceValidationError("resource overlay identity is not declared")
    if overlay.owner_addon_id != declaration.owner_addon_id:
        raise PrivateResourceValidationError("resource overlay owner is not declared")
    if overlay.schema_id != declaration.schema_id:
        raise PrivateResourceCompatibilityError("resource schema is unsupported")
    if overlay.addon_version not in declaration.supported_versions:
        raise PrivateResourceCompatibilityError("resource add-on version is unsupported")
    fields = declaration.field_map
    seen = set()
    for value in overlay.values:
        field = fields.get(value.field_id)
        if field is None:
            raise PrivateResourceValidationError("resource overlay contains an undeclared field")
        if value.value_type != field.value_type:
            raise PrivateResourceValidationError("resource overlay field type is incorrect")
        validate_typed_value(value.value, StructuredValueType(value.value_type), "resource overlay field")
        seen.add(value.field_id)
    missing = [field.field_id for field in declaration.fields if field.required and field.field_id not in seen]
    if missing:
        raise PrivateResourceValidationError("a required resource field is missing")
    return overlay


@dataclass(frozen=True)
class ResourceFieldResult:
    field_id: str
    status: str
    verified: bool
    changed: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "field_id": self.field_id,
            "status": self.status,
            "verified": self.verified,
            "changed": self.changed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class StructuredResourceResult:
    resource_id: str
    outcome: str
    restart_required: bool
    fields: tuple[ResourceFieldResult, ...] = ()
    detail: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome in {"applied", "initialized", "already_initialized"}

    @property
    def changed(self) -> bool:
        return any(item.changed for item in self.fields)

    def to_dict(self) -> dict:
        return {
            "resource_id": self.resource_id,
            "outcome": self.outcome,
            "restart_required": self.restart_required,
            "fields": [item.to_dict() for item in self.fields],
            "detail": self.detail,
        }


class StructuredPrivateResourceAdapter:
    """Adapter interface; implementations must keep values out of results."""

    adapter_id = ""

    def initialize(
        self,
        declaration: StructuredPrivateResourceDeclaration,
        context: Optional[PrivateResourceOwnerContext] = None,
    ) -> Optional[StructuredResourceResult]:
        """Initialize an absent resource through its owner-specific safe API.

        Adapters that do not declare ``configure_before_activation`` may keep
        the default no-op. Lifecycle adapters must override this method and
        return a sanitized result without exposing resource values.
        """
        if declaration.configure_before_activation:
            raise PrivateResourceNotInitializedError(
                "resource adapter has no safe initializer"
            )
        return None

    def verify(
        self,
        declaration: StructuredPrivateResourceDeclaration,
        overlay: StructuredPrivateResourceOverlay,
    ) -> StructuredResourceResult:
        """Read-only verification used after activation has been released."""
        if declaration.configure_before_activation:
            raise PrivateResourceNotInitializedError(
                "resource adapter cannot verify its configured state"
            )
        raise NotImplementedError

    def capture(self, declaration: StructuredPrivateResourceDeclaration) -> tuple[StructuredPrivateResourceOverlay, StructuredResourceResult]:
        raise NotImplementedError

    def apply(self, declaration: StructuredPrivateResourceDeclaration, overlay: StructuredPrivateResourceOverlay) -> StructuredResourceResult:
        raise NotImplementedError


class StructuredPrivateResourceManager:
    """Registry and fail-closed coordinator for vetted resource adapters."""

    def __init__(self, adapters: Optional[Mapping[str, StructuredPrivateResourceAdapter]] = None):
        self._adapters = dict(adapters or {})

    def register(self, adapter: StructuredPrivateResourceAdapter) -> None:
        if not adapter.adapter_id:
            raise PrivateResourceValidationError("resource adapter ID is required")
        if adapter.adapter_id in self._adapters:
            raise PrivateResourceValidationError("duplicate resource adapter ID")
        self._adapters[adapter.adapter_id] = adapter

    def _adapter(self, declaration: StructuredPrivateResourceDeclaration) -> StructuredPrivateResourceAdapter:
        adapter = self._adapters.get(declaration.adapter_id)
        if adapter is None:
            raise PrivateResourceCompatibilityError("resource adapter is unavailable")
        return adapter

    def capture(self, declaration: StructuredPrivateResourceDeclaration):
        return self._adapter(declaration).capture(declaration)

    def initialize(
        self,
        declarations: Sequence[StructuredPrivateResourceDeclaration],
        *,
        owner_contexts: Optional[Mapping[str, PrivateResourceOwnerContext]] = None,
    ) -> tuple[StructuredResourceResult, ...]:
        results = []
        for declaration in declarations:
            if not declaration.configure_before_activation:
                continue
            context = (owner_contexts or {}).get(declaration.owner_addon_id)
            adapter = self._adapter(declaration)
            try:
                result = adapter.initialize(declaration, context)
            except StructuredResourceInitializationError:
                raise
            except Exception as exc:
                cause_code = getattr(exc, "initialization_cause_code", None)
                if not isinstance(cause_code, ResourceInitializationCause):
                    cause_code = getattr(exc, "code", "")
                raise StructuredResourceInitializationError(
                    declaration.owner_addon_id,
                    declaration.resource_id,
                    cause_code,
                    initialization_stage=getattr(exc, "initialization_stage", None),
                    last_completed_stage=getattr(exc, "last_completed_stage", None),
                    import_failure_category=getattr(
                        exc, "import_failure_category", ""
                    ),
                    failing_module=getattr(exc, "failing_module", ""),
                    expected_provider=getattr(exc, "expected_provider", ""),
                    actual_provider=getattr(exc, "actual_provider", ""),
                ) from exc
            if result is None or not result.succeeded:
                raise StructuredResourceInitializationError(
                    declaration.owner_addon_id,
                    declaration.resource_id,
                    "RESOURCE_NOT_INITIALIZED",
                )
            results.append(result)
        return tuple(results)

    def verify(
        self,
        declarations: Sequence[StructuredPrivateResourceDeclaration],
        overlays: Sequence[StructuredPrivateResourceOverlay],
    ) -> tuple[StructuredResourceResult, ...]:
        declarations_by_id = {item.resource_id: item for item in declarations}
        if len(declarations_by_id) != len(declarations):
            raise PrivateResourceValidationError("duplicate resource ownership")
        overlays_by_id = {item.resource_id: item for item in overlays}
        if len(overlays_by_id) != len(overlays):
            raise PrivateResourceValidationError("duplicate resource overlays")
        results = []
        for declaration in declarations:
            overlay = overlays_by_id.get(declaration.resource_id)
            if overlay is None:
                if declaration.required:
                    raise PrivateResourceValidationError("required resource overlay is missing")
                continue
            result = self._adapter(declaration).verify(declaration, overlay)
            if not result.succeeded:
                raise PrivateResourceNotInitializedError(
                    "structured resource values are not verified"
                )
            results.append(result)
        return tuple(results)

    def apply(
        self,
        declarations: Sequence[StructuredPrivateResourceDeclaration],
        overlays: Sequence[StructuredPrivateResourceOverlay],
        *,
        owner_contexts: Optional[Mapping[str, PrivateResourceOwnerContext]] = None,
    ) -> tuple[StructuredResourceResult, ...]:
        declarations_by_id = {item.resource_id: item for item in declarations}
        if len(declarations_by_id) != len(declarations):
            raise PrivateResourceValidationError("duplicate resource ownership")
        overlays_by_id = {item.resource_id: item for item in overlays}
        if len(overlays_by_id) != len(overlays):
            raise PrivateResourceValidationError("duplicate resource overlays")
        self.initialize(declarations, owner_contexts=owner_contexts)
        results = []
        for declaration in declarations:
            overlay = overlays_by_id.get(declaration.resource_id)
            if overlay is None:
                if declaration.required:
                    raise PrivateResourceValidationError("required resource overlay is missing")
                continue
            validate_resource_overlay(overlay, declaration)
            results.append(self._adapter(declaration).apply(declaration, overlay))
        for resource_id in overlays_by_id:
            if resource_id not in declarations_by_id:
                raise PrivateResourceValidationError("resource overlay is not declared")
        return tuple(results)
