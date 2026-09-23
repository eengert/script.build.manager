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


class PrivateResourceError(Exception):
    """Base class for fail-closed structured resource errors."""

    code = "PRIVATE_RESOURCE_ERROR"


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


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PrivateResourceValidationError(f"{label} is not a safe identifier")
    return value


def _addon(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ADDON.fullmatch(value):
        raise PrivateResourceValidationError(f"{label} is not a safe add-on ID")
    return value


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
        self, declaration: StructuredPrivateResourceDeclaration
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
    ) -> tuple[StructuredResourceResult, ...]:
        results = []
        for declaration in declarations:
            if not declaration.configure_before_activation:
                continue
            result = self._adapter(declaration).initialize(declaration)
            if result is None or not result.succeeded:
                raise PrivateResourceNotInitializedError(
                    "structured resource initialization was not verified"
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
    ) -> tuple[StructuredResourceResult, ...]:
        declarations_by_id = {item.resource_id: item for item in declarations}
        if len(declarations_by_id) != len(declarations):
            raise PrivateResourceValidationError("duplicate resource ownership")
        overlays_by_id = {item.resource_id: item for item in overlays}
        if len(overlays_by_id) != len(overlays):
            raise PrivateResourceValidationError("duplicate resource overlays")
        self.initialize(declarations)
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
