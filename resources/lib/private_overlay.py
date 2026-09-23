"""BM-017A private/auth configuration overlay foundation.

The public manifest declares private targets and their typed ownership.  A
separate profile-local JSON overlay supplies values for those declarations.
This module deliberately uses the existing BM-015 typed configuration backend
for application and verification; it is not a second settings engine.

The initial storage backend is restrictive plaintext JSON.  It is outside the
repository, public build, and artifact store, and is written atomically with
0600 file permissions and a 0700 directory where the platform permits it.
There is no encryption-at-rest claim and no custom cryptography.  A stronger
keychain-backed backend can replace this storage abstraction later.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from resources.lib.config import (
    ConfigApplyResult,
    ConfigSetting,
    ConfigSettingType,
    ConfigTargetKind,
    ConfigurationManager,
)
from resources.lib.manifest import (
    ConfigDeclarations,
    PrivateOverlayRef,
    PrivateSettingDeclaration,
    SettingTargetKind,
)
from resources.lib.private_resource import (
    PrivateResourceValidationError,
    StructuredPrivateResourceDeclaration,
    StructuredPrivateResourceOverlay,
    StructuredPrivateResourceManager,
    validate_resource_overlay,
)


SCHEMA_VERSION = 1
ADDON_ID = "script.build.manager"
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_ADDON_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENTRY_KEYS = frozenset({"target", "addon_id", "key", "type", "value"})
_OVERLAY_KEYS = frozenset({
    "schema_version", "overlay_id", "target_build_id", "entries", "resources",
})
_SETTING_TYPES = frozenset(item.value for item in ConfigSettingType)
_SENSITIVITIES = frozenset({
    "secret", "credential", "token", "private_identifier",
})


class PrivateOverlayError(Exception):
    """Base class for fail-closed private overlay errors."""

    code = "PRIVATE_OVERLAY_ERROR"


class PrivateOverlayValidationError(PrivateOverlayError):
    code = "PRIVATE_OVERLAY_INVALID"


class PrivateOverlayMissingError(PrivateOverlayError):
    code = "PRIVATE_OVERLAY_REQUIRED"


class PrivateOverlayPersistenceError(PrivateOverlayError):
    code = "PRIVATE_OVERLAY_STORAGE_FAILED"


class PrivateOverlayFingerprintError(PrivateOverlayError):
    code = "PRIVATE_OVERLAY_FINGERPRINT_MISMATCH"


class PrivateOverlayOutcome(str, Enum):
    ABSENT_OPTIONAL = "absent_optional"
    APPLIED = "applied"
    FAILED = "failed"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise PrivateOverlayValidationError(f"{label} is not a safe identifier")
    return value


def _safe_addon_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ADDON_ID.fullmatch(value):
        raise PrivateOverlayValidationError(f"{label} is not a safe add-on ID")
    return value


def _safe_key(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_KEY.fullmatch(value):
        raise PrivateOverlayValidationError(f"{label} is not a safe setting key")
    return value


def _setting_type(value: object, label: str) -> ConfigSettingType:
    if not isinstance(value, str) or value not in _SETTING_TYPES:
        raise PrivateOverlayValidationError(f"{label} has an unsupported setting type")
    return ConfigSettingType(value)


def _typed_value(value: object, setting_type: ConfigSettingType, label: str) -> object:
    valid = (
        isinstance(value, str)
        if setting_type is ConfigSettingType.STRING
        else isinstance(value, bool)
        if setting_type is ConfigSettingType.BOOL
        else isinstance(value, int) and not isinstance(value, bool)
        if setting_type is ConfigSettingType.INT
        else isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    if not valid:
        raise PrivateOverlayValidationError(f"{label} has the wrong typed value")
    if setting_type is ConfigSettingType.NUMBER and not (-float("inf") < float(value) < float("inf")):
        raise PrivateOverlayValidationError(f"{label} has a non-finite number")
    return value


def _translate_profile_root(profile_root: str | Path) -> Path:
    if isinstance(profile_root, Path):
        root = str(profile_root)
    else:
        root = profile_root
    if not isinstance(root, str) or not root:
        raise PrivateOverlayPersistenceError("private overlay profile root is unavailable")
    if root.startswith("special://"):
        try:
            import xbmcvfs
            root = xbmcvfs.translatePath(root)
        except (ImportError, AttributeError, OSError, RuntimeError) as exc:
            raise PrivateOverlayPersistenceError(
                "Kodi profile path translation is unavailable"
            ) from exc
    if "://" in root:
        raise PrivateOverlayPersistenceError("private overlay storage is not local")
    return Path(os.path.realpath(root))


@dataclass(frozen=True, repr=False)
class PrivateOverlayEntry:
    """One private value; ``repr`` intentionally omits the value."""

    addon_id: str
    key: str
    setting_type: ConfigSettingType
    value: object = field(repr=False)
    target_kind: ConfigTargetKind = ConfigTargetKind.ADDON

    @property
    def target(self) -> tuple[str, str, str]:
        return (self.target_kind.value, self.addon_id, self.key)

    def to_dict(self) -> dict:
        return {
            "target": self.target_kind.value,
            "addon_id": self.addon_id,
            "key": self.key,
            "type": self.setting_type.value,
            "value": self.value,
        }

    def safe_dict(self) -> dict:
        return {
            "target": self.target_kind.value,
            "addon_id": self.addon_id,
            "key": self.key,
            "type": self.setting_type.value,
        }


@dataclass(frozen=True, repr=False)
class PrivateOverlay:
    """Validated private overlay content, including values only in memory."""

    overlay_id: str
    target_build_id: str
    entries: Tuple[PrivateOverlayEntry, ...]
    schema_version: int = SCHEMA_VERSION
    resources: Tuple[StructuredPrivateResourceOverlay, ...] = ()

    def to_dict(self) -> dict:
        result = {
            "schema_version": self.schema_version,
            "overlay_id": self.overlay_id,
            "target_build_id": self.target_build_id,
            "entries": [entry.to_dict() for entry in self.entries],
        }
        if self.resources:
            result["resources"] = [resource.to_dict() for resource in self.resources]
        return result

    def safe_dict(self) -> dict:
        result = {
            "schema_version": self.schema_version,
            "overlay_id": self.overlay_id,
            "target_build_id": self.target_build_id,
            "entries": [entry.safe_dict() for entry in self.entries],
        }
        if self.resources:
            result["resources"] = [resource.safe_dict() for resource in self.resources]
        return result

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    @classmethod
    def from_dict(cls, value: object) -> "PrivateOverlay":
        if not isinstance(value, dict) or not _OVERLAY_KEYS.issuperset(value):
            raise PrivateOverlayValidationError("private overlay fields are unsupported")
        if set(value) not in (_OVERLAY_KEYS - {"resources"}, _OVERLAY_KEYS):
            raise PrivateOverlayValidationError("private overlay fields are unsupported")
        if value.get("schema_version") != SCHEMA_VERSION:
            raise PrivateOverlayValidationError("unsupported private overlay schema")
        overlay_id = _safe_id(value.get("overlay_id"), "overlay_id")
        target_build_id = value.get("target_build_id", "")
        if not isinstance(target_build_id, str) or len(target_build_id) > 128:
            raise PrivateOverlayValidationError("target_build_id is invalid")
        raw_entries = value.get("entries")
        if not isinstance(raw_entries, list):
            raise PrivateOverlayValidationError("private overlay entries must be an array")
        entries = []
        seen = set()
        for index, raw in enumerate(raw_entries):
            label = f"private overlay entry {index}"
            if not isinstance(raw, dict) or set(raw) != _ENTRY_KEYS:
                raise PrivateOverlayValidationError(f"{label} is malformed")
            target = raw.get("target", "addon")
            try:
                target_kind = ConfigTargetKind(target)
            except ValueError as exc:
                raise PrivateOverlayValidationError(f"{label} has an invalid target") from exc
            addon_id = _safe_addon_id(raw.get("addon_id"), f"{label} add-on")
            key = _safe_key(raw.get("key"), f"{label} key")
            setting_type = _setting_type(raw.get("type"), f"{label} type")
            typed_value = _typed_value(raw.get("value"), setting_type, label)
            identity = (target_kind, addon_id, key)
            if identity in seen:
                raise PrivateOverlayValidationError("private overlay contains duplicate targets")
            seen.add(identity)
            entries.append(PrivateOverlayEntry(
                addon_id=addon_id,
                key=key,
                setting_type=setting_type,
                value=typed_value,
                target_kind=target_kind,
            ))
        resources = []
        if "resources" in value:
            raw_resources = value["resources"]
            if not isinstance(raw_resources, list):
                raise PrivateOverlayValidationError("private resource overlays must be an array")
            try:
                resources = [StructuredPrivateResourceOverlay.from_dict(item) for item in raw_resources]
            except PrivateResourceValidationError as exc:
                raise PrivateOverlayValidationError("private resource overlay is malformed") from exc
        return cls(
            overlay_id=overlay_id,
            target_build_id=target_build_id,
            entries=tuple(entries),
            schema_version=SCHEMA_VERSION,
            resources=tuple(resources),
        )


@dataclass(frozen=True)
class PrivateOverlayMetadata:
    """Safe identity carried in results and durable transactions."""

    overlay_id: str
    fingerprint: str
    required: bool
    present: bool

    def __post_init__(self) -> None:
        _safe_id(self.overlay_id, "overlay_id")
        if not _FINGERPRINT.fullmatch(self.fingerprint):
            raise PrivateOverlayValidationError("private overlay fingerprint is invalid")
        if not isinstance(self.required, bool) or not isinstance(self.present, bool):
            raise PrivateOverlayValidationError("private overlay metadata flags are invalid")

    def to_dict(self) -> dict:
        return {
            "overlay_id": self.overlay_id,
            "fingerprint": self.fingerprint,
            "required": self.required,
            "present": self.present,
        }


@dataclass(frozen=True)
class PreparedPrivateOverlay:
    overlay: Optional[PrivateOverlay]
    metadata: Optional[PrivateOverlayMetadata]
    declarations: Tuple[PrivateSettingDeclaration, ...] = ()
    resource_declarations: Tuple[StructuredPrivateResourceDeclaration, ...] = ()


@dataclass(frozen=True)
class PrivateSettingResult:
    addon_id: str
    key: str
    status: str
    verified: bool
    changed: bool
    detail: str
    target_kind: ConfigTargetKind = ConfigTargetKind.ADDON

    def to_dict(self) -> dict:
        return {
            "target": self.target_kind.value,
            "addon_id": self.addon_id,
            "key": self.key,
            "status": self.status,
            "verified": self.verified,
            "changed": self.changed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PrivateOverlayApplyResult:
    outcome: PrivateOverlayOutcome
    metadata: Optional[PrivateOverlayMetadata]
    results: Tuple[PrivateSettingResult, ...] = ()
    resource_results: tuple = ()

    @property
    def succeeded(self) -> bool:
        return self.outcome is not PrivateOverlayOutcome.FAILED and all(
            result.succeeded for result in self.resource_results
        )

    @property
    def changed(self) -> bool:
        return any(item.changed for item in self.results) or any(
            result.changed for result in self.resource_results
        )

    @property
    def message(self) -> str:
        if self.outcome is PrivateOverlayOutcome.ABSENT_OPTIONAL:
            return "optional private overlay is absent"
        if self.outcome is PrivateOverlayOutcome.APPLIED:
            return "private overlay settings were verified"
        return "private overlay application failed closed"

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "results": [item.to_dict() for item in self.results],
            "resource_results": [item.to_dict() for item in self.resource_results],
        }


@dataclass(frozen=True)
class ConfigurationApplyBundle:
    """Public result plus private result from the same BM-015 backend."""

    public_result: ConfigApplyResult
    private_result: Optional[PrivateOverlayApplyResult] = None

    @property
    def succeeded(self) -> bool:
        return self.public_result.all_applied and (
            self.private_result is None or self.private_result.succeeded
        )

    @property
    def changed(self) -> bool:
        return bool(self.public_result.changed) or bool(
            self.private_result and self.private_result.changed
        )

    @property
    def message(self) -> str:
        if not self.public_result.all_applied:
            return "public configuration application failed"
        if self.private_result and not self.private_result.succeeded:
            return self.private_result.message
        return "public and private configuration were verified"

    @property
    def restart_report(self):
        return self.public_result.restart_report


class PrivateOverlayStore:
    """Atomic profile-local active overlay store."""

    def __init__(self, profile_root: str | Path = "special://profile/", *, addon_id: str = ADDON_ID):
        self._root = _translate_profile_root(profile_root)
        self._addon_id = _safe_id(addon_id, "addon_id")

    @property
    def directory(self) -> Path:
        return self._root / "addon_data" / self._addon_id / "private_overlays"

    def path_for(self, overlay_id: str) -> Path:
        return self.directory / f"{_safe_id(overlay_id, 'overlay_id')}.json"

    def load(self, overlay_id: str) -> PrivateOverlay:
        path = self.path_for(overlay_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PrivateOverlayMissingError("required private overlay is absent") from exc
        except (OSError, UnicodeError) as exc:
            raise PrivateOverlayPersistenceError("private overlay could not be read") from exc
        try:
            overlay = PrivateOverlay.from_dict(json.loads(raw))
        except (UnicodeError, json.JSONDecodeError, PrivateOverlayError) as exc:
            if isinstance(exc, PrivateOverlayError):
                raise
            raise PrivateOverlayValidationError("private overlay JSON is malformed") from exc
        if overlay.overlay_id != overlay_id:
            raise PrivateOverlayValidationError("private overlay identity does not match its path")
        return overlay

    def save(self, overlay: PrivateOverlay) -> Path:
        if not isinstance(overlay, PrivateOverlay):
            raise PrivateOverlayValidationError("private overlay has an invalid type")
        target = self.path_for(overlay.overlay_id)
        staged = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(self.directory, 0o700)
            except OSError:
                pass
            fd, name = tempfile.mkstemp(prefix=".private-overlay.", suffix=".tmp", dir=self.directory)
            staged = Path(name)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_canonical_json(overlay.to_dict()) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, target)
            staged = None
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            self._fsync_directory()
            return target
        except (OSError, ValueError) as exc:
            raise PrivateOverlayPersistenceError("private overlay could not be stored") from exc
        finally:
            if staged is not None:
                try:
                    staged.unlink()
                except OSError:
                    pass

    def import_file(self, source: str | Path) -> PrivateOverlay:
        """Validate an explicitly supplied import artifact into active storage."""
        try:
            raw = Path(source).read_text(encoding="utf-8")
            overlay = PrivateOverlay.from_dict(json.loads(raw))
        except (OSError, UnicodeError, json.JSONDecodeError, PrivateOverlayError) as exc:
            if isinstance(exc, PrivateOverlayError):
                raise
            raise PrivateOverlayValidationError("private overlay import is invalid") from exc
        self.save(overlay)
        return overlay

    def _fsync_directory(self) -> None:
        try:
            fd = os.open(self.directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)


def _declaration_map(
    declarations: Iterable[PrivateSettingDeclaration],
) -> Mapping[tuple[SettingTargetKind, str, str], PrivateSettingDeclaration]:
    result = {}
    for declaration in declarations:
        if declaration.sensitivity not in _SENSITIVITIES:
            raise PrivateOverlayValidationError("private declaration has an invalid sensitivity class")
        if declaration.setting_type not in _SETTING_TYPES:
            raise PrivateOverlayValidationError("private declaration has an invalid setting type")
        identity = (declaration.target_kind, declaration.addon_id, declaration.key)
        if identity in result:
            raise PrivateOverlayValidationError("private declarations contain duplicate targets")
        result[identity] = declaration
    return result


def validate_private_overlay(
    overlay: PrivateOverlay,
    declarations: Sequence[PrivateSettingDeclaration],
    *,
    expected_build_id: str = "",
    expected_overlay_id: str = "",
    resource_declarations: Sequence[StructuredPrivateResourceDeclaration] = (),
) -> PrivateOverlay:
    """Validate explicit ownership, type, completeness, and target identity."""
    if not isinstance(overlay, PrivateOverlay):
        raise PrivateOverlayValidationError("private overlay has an invalid type")
    declaration_map = _declaration_map(declarations)
    if expected_overlay_id and overlay.overlay_id != expected_overlay_id:
        raise PrivateOverlayValidationError("private overlay identity does not match the manifest")
    if expected_build_id and overlay.target_build_id not in ("", expected_build_id):
        raise PrivateOverlayValidationError("private overlay target build does not match")
    entries = {entry.target: entry for entry in overlay.entries}
    for entry in overlay.entries:
        declaration = declaration_map.get(entry.target)
        if declaration is None:
            raise PrivateOverlayValidationError(
                f"private setting {entry.addon_id}/{entry.key} is not declared"
            )
        if entry.setting_type.value != declaration.setting_type:
            raise PrivateOverlayValidationError(
                f"private setting {entry.addon_id}/{entry.key} has the wrong type"
            )
        _typed_value(entry.value, entry.setting_type, "private setting")
    missing = [
        declaration for identity, declaration in declaration_map.items()
        if declaration.required and identity not in entries
    ]
    if missing:
        raise PrivateOverlayValidationError("a required private setting is missing")
    resource_map = {declaration.resource_id: declaration for declaration in resource_declarations}
    if len(resource_map) != len(resource_declarations):
        raise PrivateOverlayValidationError("private resource declarations contain duplicates")
    overlay_resource_map = {resource.resource_id: resource for resource in overlay.resources}
    if len(overlay_resource_map) != len(overlay.resources):
        raise PrivateOverlayValidationError("private overlay contains duplicate resources")
    for resource in overlay.resources:
        declaration = resource_map.get(resource.resource_id)
        if declaration is None:
            raise PrivateOverlayValidationError("private overlay contains an undeclared resource")
        try:
            validate_resource_overlay(resource, declaration)
        except PrivateResourceValidationError as exc:
            raise PrivateOverlayValidationError(str(exc)) from exc
    missing_resources = [
        declaration.resource_id for declaration in resource_declarations
        if declaration.required and declaration.resource_id not in overlay_resource_map
    ]
    if missing_resources:
        raise PrivateOverlayValidationError("a required private resource is missing")
    return overlay


def validate_private_overlay_resolution_compatibility(
    resolutions: Mapping[str, Optional[str]],
    declarations: Sequence[PrivateSettingDeclaration],
    resource_declarations: Sequence[StructuredPrivateResourceDeclaration] = (),
) -> bool:
    """Check resolution changes against declared overlay ownership only.

    ``None`` means an add-on is intentionally skipped; a string is its
    resolved version. This function accepts public declarations only and
    never loads or inspects private overlay values.
    """
    setting_owners = {item.addon_id for item in declarations}
    resource_owners: Dict[str, list] = {}
    for item in resource_declarations:
        resource_owners.setdefault(item.owner_addon_id, []).append(item)
    for addon_id, version in resolutions.items():
        if addon_id in setting_owners:
            raise PrivateOverlayValidationError(
                "install resolution changes an add-on that owns declared private settings"
            )
        resources = resource_owners.get(addon_id, ())
        if not resources:
            continue
        if version is None:
            raise PrivateOverlayValidationError(
                "install resolution skips a declared private-resource owner"
            )
        if any(version not in resource.supported_versions for resource in resources):
            raise PrivateOverlayValidationError(
                "resolved private-resource owner version is not declared as compatible"
            )
    return True


class PrivateOverlayManager:
    """Prepare and apply private settings through the BM-015 backend."""

    def __init__(
        self,
        configuration_manager: ConfigurationManager,
        *,
        store: Optional[PrivateOverlayStore] = None,
        structured_resource_manager: Optional[StructuredPrivateResourceManager] = None,
    ):
        self._configuration_manager = configuration_manager
        # Do not translate special://profile while merely importing or
        # constructing BuildManager outside Kodi.  The store is needed only
        # when a manifest actually references a private overlay.
        self._store = store
        self._structured_resource_manager = structured_resource_manager

    @property
    def _active_store(self) -> PrivateOverlayStore:
        if self._store is None:
            self._store = PrivateOverlayStore()
        return self._store

    @property
    def _active_resource_manager(self) -> StructuredPrivateResourceManager:
        if self._structured_resource_manager is None:
            try:
                from resources.lib.redlight_resource import RedLightSettingsAdapter
                self._structured_resource_manager = StructuredPrivateResourceManager({
                    RedLightSettingsAdapter.adapter_id: RedLightSettingsAdapter(
                        _translate_profile_root("special://profile"),
                    ),
                })
            except Exception:
                # Outside Kodi, or without a translated profile, retain a
                # registry that fails closed rather than inventing a path.
                self._structured_resource_manager = StructuredPrivateResourceManager()
        return self._structured_resource_manager

    def prepare(
        self,
        reference: Optional[PrivateOverlayRef],
        declarations: Sequence[PrivateSettingDeclaration],
        *,
        build_id: str = "",
        resource_declarations: Sequence[StructuredPrivateResourceDeclaration] = (),
    ) -> PreparedPrivateOverlay:
        if reference is None:
            return PreparedPrivateOverlay(None, None, tuple(declarations))
        if reference.type != "local_file":
            raise PrivateOverlayValidationError("unsupported private overlay storage type")
        if not declarations and not resource_declarations:
            raise PrivateOverlayValidationError("private overlay has no public declarations")
        try:
            overlay = self._active_store.load(reference.overlay_id)
        except PrivateOverlayMissingError:
            if reference.required:
                raise
            return PreparedPrivateOverlay(None, None, tuple(declarations), tuple(resource_declarations))
        validated = validate_private_overlay(
            overlay,
            declarations,
            expected_build_id=build_id,
            expected_overlay_id=reference.overlay_id,
            resource_declarations=resource_declarations,
        )
        metadata = PrivateOverlayMetadata(
            validated.overlay_id,
            validated.fingerprint,
            reference.required,
            True,
        )
        return PreparedPrivateOverlay(
            validated, metadata, tuple(declarations), tuple(resource_declarations)
        )

    def apply(self, prepared: PreparedPrivateOverlay) -> PrivateOverlayApplyResult:
        if prepared.overlay is None:
            return PrivateOverlayApplyResult(
                PrivateOverlayOutcome.ABSENT_OPTIONAL,
                prepared.metadata,
            )
        settings = tuple(
            ConfigSetting(
                addon_id=entry.addon_id,
                key=entry.key,
                setting_type=entry.setting_type,
                value=entry.value,
                package_id=f"private-overlay:{prepared.overlay.overlay_id}",
                target_kind=entry.target_kind,
            )
            for entry in prepared.overlay.entries
        )
        applied = self._configuration_manager.apply_settings(
            settings, effective_identity=prepared.overlay.fingerprint,
        )
        results = tuple(
            PrivateSettingResult(
                addon_id=result.addon_id,
                key=result.key,
                status=result.status.value,
                verified=result.status.value != "failed",
                changed=result.status.value in {"updated", "created"},
                detail=(
                    "private setting was verified"
                    if result.status.value != "failed"
                    else "private setting verification failed"
                ),
                target_kind=result.target_kind,
            )
            for result in applied.settings
        )
        resource_results = ()
        if prepared.overlay.resources:
            try:
                resource_results = self._active_resource_manager.apply(
                    prepared.resource_declarations, prepared.overlay.resources,
                )
            except Exception:
                return PrivateOverlayApplyResult(PrivateOverlayOutcome.FAILED, prepared.metadata, results)
        return PrivateOverlayApplyResult(
            PrivateOverlayOutcome.APPLIED if applied.all_applied else PrivateOverlayOutcome.FAILED,
            prepared.metadata,
            results,
            resource_results,
        )
