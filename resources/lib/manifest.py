"""
Build Manager manifest loader and validator (BM-003).

Public API
----------
load_manifest_file(path: str) -> Manifest
    Load and validate a manifest from a filesystem path.

load_manifest_json(text: str) -> Manifest
    Load and validate a manifest from a JSON string.

validate_manifest(doc: dict) -> Manifest
    Validate a pre-parsed manifest dict and return the typed Manifest.

Errors
------
ManifestError           -- base class
ManifestParseError      -- I/O failure or JSON syntax error
ManifestValidationError -- schema or semantic constraint violation;
                           message identifies the offending field/path, e.g.:
                           "device_profiles.bonus-room.extends: unknown platform 'tvos2'"
                           "config.managed_files[0]: path traversal is not allowed"

URL policy
----------
bootstrap_url accepts 'https' (preferred) and 'http' (local/dev repositories only).
Credentials embedded in URLs are always rejected.

Stdlib only — no jsonschema runtime dependency.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ManifestError(Exception):
    """Base class for all manifest loading and validation errors."""


class ManifestParseError(ManifestError):
    """JSON syntax failure or I/O error reading a manifest file."""


class ManifestValidationError(ManifestError):
    """A manifest field or semantic constraint failed validation."""


# ---------------------------------------------------------------------------
# Typed representation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BuildInfo:
    id: str
    version: str
    name: str = ""
    description: str = ""


@dataclass(frozen=True)
class AddonEntry:
    addon_id: str
    state: str          # "enabled" | "disabled" | "absent"
    note: str = ""


@dataclass(frozen=True)
class Repository:
    addon_id: str
    bootstrap_url: str = ""
    required: bool = True


@dataclass(frozen=True)
class SkinEntry:
    addon_id: str
    config_packages: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ManagedSettingScope:
    addon_id: str
    keys: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigDeclarations:
    packages: Tuple[str, ...] = ()
    managed_settings: Tuple[ManagedSettingScope, ...] = ()
    managed_files: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileLayer:
    label: str = ""
    addons: Tuple[AddonEntry, ...] = ()
    config: Optional[ConfigDeclarations] = None
    skin: Optional[SkinEntry] = None
    include_optional: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DeviceProfile:
    extends: str
    label: str = ""
    addons: Tuple[AddonEntry, ...] = ()
    config: Optional[ConfigDeclarations] = None
    skin: Optional[SkinEntry] = None
    include_optional: Tuple[str, ...] = ()


@dataclass(frozen=True)
class OptionalGroup:
    id: str
    label: str = ""
    description: str = ""
    addons: Tuple[AddonEntry, ...] = ()
    config: Optional[ConfigDeclarations] = None


@dataclass(frozen=True)
class PrivateOverlayRef:
    type: str
    path_hint: str = ""
    description: str = ""


@dataclass(frozen=True)
class RestartPolicy:
    allow_skin_reload: bool = True
    allow_kodi_restart: bool = True


@dataclass
class Manifest:
    """Fully-parsed and validated Build Manager manifest.

    Collection fields are tuples (immutable). Profile maps are plain dicts for
    convenient lookup; callers should not mutate them or their contents.
    """
    schema_version: int
    build: BuildInfo
    engine_min_version: str = ""
    repositories: Tuple[Repository, ...] = ()
    addons: Tuple[AddonEntry, ...] = ()
    skin: Optional[SkinEntry] = None
    config: Optional[ConfigDeclarations] = None
    platform_profiles: Dict[str, ProfileLayer] = field(default_factory=dict)
    device_profiles: Dict[str, DeviceProfile] = field(default_factory=dict)
    optional: Tuple[OptionalGroup, ...] = ()
    private_overlay: Optional[PrivateOverlayRef] = None
    restart_policy: Optional[RestartPolicy] = None


# ---------------------------------------------------------------------------
# Constants (derived from schema-v1.json constraints)
# ---------------------------------------------------------------------------

_RE_BUILD_ID   = re.compile(r'^[a-z0-9][a-z0-9_-]*$')
_RE_VERSION    = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')
_RE_ADDON_ID   = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
_RE_REPO_ID    = re.compile(r'^repository\.[a-z0-9._-]+$')
_RE_SKIN_ID    = re.compile(r'^skin\.[a-z0-9._-]+$')
_RE_OPT_ID     = re.compile(r'^[a-z0-9][a-z0-9_-]*$')

_VALID_ADDON_STATES   = frozenset({"enabled", "disabled", "absent"})
_VALID_OVERLAY_TYPES  = frozenset({"local_file"})
_VALID_URL_SCHEMES    = frozenset({"https", "http"})

_TOP_LEVEL_KEYS = frozenset({
    "schema_version", "engine_min_version", "build", "repositories",
    "addons", "skin", "config", "platform_profiles", "device_profiles",
    "optional", "private_overlay", "restart_policy",
})
_BUILD_KEYS             = frozenset({"id", "version", "name", "description"})
_REPO_KEYS              = frozenset({"addon_id", "bootstrap_url", "required"})
_ADDON_KEYS             = frozenset({"addon_id", "state", "note"})
_SKIN_KEYS              = frozenset({"addon_id", "config_packages"})
_CONFIG_KEYS            = frozenset({"packages", "managed_settings", "managed_files"})
_MANAGED_SETTING_KEYS   = frozenset({"addon_id", "keys"})
_PROFILE_KEYS           = frozenset({"label", "addons", "config", "skin", "include_optional"})
_DEVICE_PROFILE_KEYS    = frozenset({"label", "extends", "addons", "config", "skin", "include_optional"})
_OPTIONAL_GROUP_KEYS    = frozenset({"id", "label", "description", "addons", "config"})
_OVERLAY_KEYS           = frozenset({"type", "path_hint", "description"})
_RESTART_POLICY_KEYS    = frozenset({"allow_skin_reload", "allow_kodi_restart"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_manifest_file(path: str) -> Manifest:
    """Load and validate a manifest from a filesystem path.

    Raises:
        ManifestParseError: if the file cannot be read or is not valid JSON.
        ManifestValidationError: if the manifest fails schema or semantic checks.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise ManifestParseError(f"Cannot read manifest file: {exc}") from exc
    return load_manifest_json(text, source=path)


def load_manifest_json(text: str, *, source: str = "<string>") -> Manifest:
    """Load and validate a manifest from a JSON string.

    Raises:
        ManifestParseError: if the text is not valid JSON or the root is not an object.
        ManifestValidationError: if the manifest fails schema or semantic checks.
    """
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestParseError(
            f"Invalid JSON in manifest ({source}): {exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise ManifestParseError(
            f"Manifest root must be a JSON object, got {type(doc).__name__} ({source})"
        )
    return validate_manifest(doc, source=source)


def validate_manifest(doc: object, *, source: str = "<dict>") -> Manifest:
    """Validate a pre-parsed manifest dict and return a typed Manifest.

    Raises:
        ManifestValidationError: on any schema or semantic constraint failure.
    """
    if not isinstance(doc, dict):
        raise ManifestValidationError(
            f"Manifest must be a JSON object, got {type(doc).__name__}"
        )
    _check_top_level(doc)

    schema_version = doc["schema_version"]
    build = _parse_build(doc["build"])
    engine_min_version = _parse_engine_min_version(doc)
    repositories = _parse_repositories(doc.get("repositories", []))
    addons = _parse_addons(doc.get("addons", []), label="addons")
    skin = _parse_skin(doc["skin"], label="skin") if "skin" in doc else None
    config = _parse_config(doc["config"], label="config") if "config" in doc else None
    platform_profiles = _parse_platform_profiles(doc.get("platform_profiles", {}))
    device_profiles = _parse_device_profiles(doc.get("device_profiles", {}))
    optional = _parse_optional(doc.get("optional", []))
    private_overlay = _parse_private_overlay(doc["private_overlay"]) if "private_overlay" in doc else None
    restart_policy = _parse_restart_policy(doc["restart_policy"]) if "restart_policy" in doc else None

    _validate_semantic(
        platform_profiles=platform_profiles,
        device_profiles=device_profiles,
        optional=optional,
    )

    return Manifest(
        schema_version=schema_version,
        build=build,
        engine_min_version=engine_min_version,
        repositories=repositories,
        addons=addons,
        skin=skin,
        config=config,
        platform_profiles=platform_profiles,
        device_profiles=device_profiles,
        optional=optional,
        private_overlay=private_overlay,
        restart_policy=restart_policy,
    )


# ---------------------------------------------------------------------------
# Top-level structure
# ---------------------------------------------------------------------------

def _check_top_level(doc: dict) -> None:
    unknown = set(doc.keys()) - _TOP_LEVEL_KEYS
    if unknown:
        raise ManifestValidationError(
            f"Unknown top-level field(s): {', '.join(sorted(unknown))}"
        )
    if "schema_version" not in doc:
        raise ManifestValidationError("schema_version: required field is missing")
    sv = doc["schema_version"]
    if isinstance(sv, bool) or not isinstance(sv, int):
        raise ManifestValidationError(
            f"schema_version: must be integer 1, got {type(sv).__name__} {sv!r}"
        )
    if sv != 1:
        raise ManifestValidationError(
            f"schema_version: unsupported version {sv!r}; this engine supports version 1 only"
        )
    if "build" not in doc:
        raise ManifestValidationError("build: required field is missing")
    if not isinstance(doc["build"], dict):
        raise ManifestValidationError(
            f"build: must be an object, got {type(doc['build']).__name__}"
        )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _parse_build(raw: dict) -> BuildInfo:
    label = "build"
    _reject_unknown(raw, _BUILD_KEYS, label)

    id_ = _require_str(raw, "id", label)
    if not _RE_BUILD_ID.match(id_):
        raise ManifestValidationError(
            f"build.id: invalid identifier {id_!r} "
            f"(must match ^[a-z0-9][a-z0-9_-]*$)"
        )

    version = _require_str(raw, "version", label)
    if not _RE_VERSION.match(version):
        raise ManifestValidationError(
            f"build.version: invalid semver {version!r} (must be MAJOR.MINOR.PATCH)"
        )

    name = ""
    if "name" in raw:
        name_val = raw["name"]
        if not isinstance(name_val, str):
            raise ManifestValidationError(
                f"build.name: must be a string if present, got {type(name_val).__name__}"
            )
        name = name_val

    description = ""
    if "description" in raw:
        desc_val = raw["description"]
        if not isinstance(desc_val, str):
            raise ManifestValidationError(
                f"build.description: must be a string if present, got {type(desc_val).__name__}"
            )
        description = desc_val

    return BuildInfo(
        id=id_,
        version=version,
        name=name,
        description=description,
    )


def _parse_engine_min_version(doc: dict) -> str:
    if "engine_min_version" not in doc:
        return ""
    val = doc["engine_min_version"]
    if not isinstance(val, str):
        raise ManifestValidationError(
            f"engine_min_version: must be a string, got {type(val).__name__}"
        )
    if not _RE_VERSION.match(val):
        raise ManifestValidationError(
            f"engine_min_version: invalid semver {val!r} (must be MAJOR.MINOR.PATCH)"
        )
    return val


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------

def _parse_repositories(raw: object) -> Tuple[Repository, ...]:
    label = "repositories"
    if not isinstance(raw, list):
        raise ManifestValidationError(f"{label}: must be an array")
    seen_ids: set = set()
    out = []
    for i, entry in enumerate(raw):
        lbl = f"{label}[{i}]"
        if not isinstance(entry, dict):
            raise ManifestValidationError(f"{lbl}: must be an object")
        _reject_unknown(entry, _REPO_KEYS, lbl)

        addon_id = _require_str(entry, "addon_id", lbl)
        if not _RE_REPO_ID.match(addon_id):
            raise ManifestValidationError(
                f"{lbl}.addon_id: repository ID must match repository.<name>, "
                f"got {addon_id!r}"
            )
        if addon_id in seen_ids:
            raise ManifestValidationError(
                f"{lbl}.addon_id: duplicate repository ID {addon_id!r}"
            )
        seen_ids.add(addon_id)

        bootstrap_url = ""
        if "bootstrap_url" in entry:
            url = entry["bootstrap_url"]
            if not isinstance(url, str):
                raise ManifestValidationError(
                    f"{lbl}.bootstrap_url: must be a string"
                )
            _validate_url(url, label=f"{lbl}.bootstrap_url")
            bootstrap_url = url

        required = True
        if "required" in entry:
            req = entry["required"]
            if not isinstance(req, bool):
                raise ManifestValidationError(f"{lbl}.required: must be a boolean")
            required = req

        out.append(Repository(
            addon_id=addon_id,
            bootstrap_url=bootstrap_url,
            required=required,
        ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------

def _parse_addons(raw: object, *, label: str) -> Tuple[AddonEntry, ...]:
    """Parse an add-on list, rejecting duplicate addon_ids within the same layer."""
    if not isinstance(raw, list):
        raise ManifestValidationError(f"{label}: must be an array")
    seen: set = set()
    out = []
    for i, entry in enumerate(raw):
        lbl = f"{label}[{i}]"
        parsed = _parse_addon_entry(entry, label=lbl)
        if parsed.addon_id in seen:
            raise ManifestValidationError(
                f"{lbl}.addon_id: duplicate add-on ID {parsed.addon_id!r}"
            )
        seen.add(parsed.addon_id)
        out.append(parsed)
    return tuple(out)


def _parse_addon_entry(raw: object, *, label: str) -> AddonEntry:
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"{label}: must be an object")
    _reject_unknown(raw, _ADDON_KEYS, label)

    addon_id = _require_str(raw, "addon_id", label)
    if not _RE_ADDON_ID.match(addon_id):
        raise ManifestValidationError(
            f"{label}.addon_id: invalid add-on ID {addon_id!r} "
            f"(must match ^[a-z0-9][a-z0-9._-]*$)"
        )

    state = _require_str(raw, "state", label)
    if state not in _VALID_ADDON_STATES:
        raise ManifestValidationError(
            f"{label}.state: expected enabled|disabled|absent, got {state!r}"
        )

    note = ""
    if "note" in raw:
        note_val = raw["note"]
        if not isinstance(note_val, str):
            raise ManifestValidationError(
                f"{label}.note: must be a string if present, got {type(note_val).__name__}"
            )
        note = note_val

    return AddonEntry(addon_id=addon_id, state=state, note=note)


# ---------------------------------------------------------------------------
# Skin
# ---------------------------------------------------------------------------

def _parse_skin(raw: object, *, label: str) -> Optional[SkinEntry]:
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"{label}: must be an object")
    _reject_unknown(raw, _SKIN_KEYS, label)

    addon_id = _require_str(raw, "addon_id", label)
    if not _RE_SKIN_ID.match(addon_id):
        raise ManifestValidationError(
            f"{label}.addon_id: skin ID must start with 'skin.', got {addon_id!r}"
        )

    config_packages: Tuple[str, ...] = ()
    if "config_packages" in raw:
        cp = raw["config_packages"]
        if not isinstance(cp, list):
            raise ManifestValidationError(f"{label}.config_packages: must be an array")
        for j, pkg in enumerate(cp):
            if not isinstance(pkg, str):
                raise ManifestValidationError(
                    f"{label}.config_packages[{j}]: must be a string"
                )
        config_packages = tuple(cp)

    return SkinEntry(addon_id=addon_id, config_packages=config_packages)


# ---------------------------------------------------------------------------
# Config declarations
# ---------------------------------------------------------------------------

def _parse_config(raw: object, *, label: str) -> Optional[ConfigDeclarations]:
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"{label}: must be an object")
    _reject_unknown(raw, _CONFIG_KEYS, label)

    packages: Tuple[str, ...] = ()
    if "packages" in raw:
        pkgs = raw["packages"]
        if not isinstance(pkgs, list):
            raise ManifestValidationError(f"{label}.packages: must be an array")
        for j, pkg in enumerate(pkgs):
            if not isinstance(pkg, str):
                raise ManifestValidationError(f"{label}.packages[{j}]: must be a string")
        packages = tuple(pkgs)

    managed_settings: Tuple[ManagedSettingScope, ...] = ()
    if "managed_settings" in raw:
        ms_raw = raw["managed_settings"]
        if not isinstance(ms_raw, list):
            raise ManifestValidationError(f"{label}.managed_settings: must be an array")
        seen_addon_ids: set = set()
        ms_list = []
        for j, scope in enumerate(ms_raw):
            slbl = f"{label}.managed_settings[{j}]"
            parsed = _parse_managed_setting_scope(scope, label=slbl)
            if parsed.addon_id in seen_addon_ids:
                raise ManifestValidationError(
                    f"{slbl}.addon_id: duplicate managed_settings scope for "
                    f"{parsed.addon_id!r}"
                )
            seen_addon_ids.add(parsed.addon_id)
            ms_list.append(parsed)
        managed_settings = tuple(ms_list)

    managed_files: Tuple[str, ...] = ()
    if "managed_files" in raw:
        mf_raw = raw["managed_files"]
        if not isinstance(mf_raw, list):
            raise ManifestValidationError(f"{label}.managed_files: must be an array")
        seen_paths: set = set()
        mf_list = []
        for j, path_val in enumerate(mf_raw):
            flbl = f"{label}.managed_files[{j}]"
            normalized = _validate_managed_path(path_val, label=flbl)
            if normalized in seen_paths:
                raise ManifestValidationError(
                    f"{flbl}: duplicate managed file path {normalized!r}"
                )
            seen_paths.add(normalized)
            mf_list.append(normalized)
        managed_files = tuple(mf_list)

    return ConfigDeclarations(
        packages=packages,
        managed_settings=managed_settings,
        managed_files=managed_files,
    )


def _parse_managed_setting_scope(raw: object, *, label: str) -> ManagedSettingScope:
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"{label}: must be an object")
    _reject_unknown(raw, _MANAGED_SETTING_KEYS, label)

    addon_id = _require_str(raw, "addon_id", label)
    if not _RE_ADDON_ID.match(addon_id):
        raise ManifestValidationError(
            f"{label}.addon_id: invalid add-on ID {addon_id!r}"
        )

    if "keys" not in raw:
        raise ManifestValidationError(f"{label}.keys: required field is missing")
    keys_raw = raw["keys"]
    if not isinstance(keys_raw, list) or not keys_raw:
        raise ManifestValidationError(f"{label}.keys: must be a non-empty array")
    for j, k in enumerate(keys_raw):
        if not isinstance(k, str):
            raise ManifestValidationError(f"{label}.keys[{j}]: must be a string")

    return ManagedSettingScope(addon_id=addon_id, keys=tuple(keys_raw))


# ---------------------------------------------------------------------------
# Platform profiles
# ---------------------------------------------------------------------------

def _parse_platform_profiles(raw: object) -> Dict[str, ProfileLayer]:
    label = "platform_profiles"
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"{label}: must be an object")
    out = {}
    for key, layer in raw.items():
        out[key] = _parse_profile_layer(layer, label=f"{label}.{key}")
    return out


def _parse_profile_layer(raw: object, *, label: str) -> ProfileLayer:
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"{label}: must be an object")
    _reject_unknown(raw, _PROFILE_KEYS, label)

    addons: Tuple[AddonEntry, ...] = ()
    if "addons" in raw:
        addons = _parse_addons(raw["addons"], label=f"{label}.addons")

    config = _parse_config(raw["config"], label=f"{label}.config") if "config" in raw else None
    skin = _parse_skin(raw["skin"], label=f"{label}.skin") if "skin" in raw else None

    include_optional: Tuple[str, ...] = ()
    if "include_optional" in raw:
        io = raw["include_optional"]
        if not isinstance(io, list):
            raise ManifestValidationError(
                f"{label}.include_optional: must be an array"
            )
        for j, ref in enumerate(io):
            if not isinstance(ref, str):
                raise ManifestValidationError(
                    f"{label}.include_optional[{j}]: must be a string"
                )
        include_optional = tuple(io)

    profile_label = ""
    if "label" in raw:
        lv = raw["label"]
        if not isinstance(lv, str):
            raise ManifestValidationError(
                f"{label}.label: must be a string if present, got {type(lv).__name__}"
            )
        profile_label = lv

    return ProfileLayer(
        label=profile_label,
        addons=addons,
        config=config,
        skin=skin,
        include_optional=include_optional,
    )


# ---------------------------------------------------------------------------
# Device profiles
# ---------------------------------------------------------------------------

def _parse_device_profiles(raw: object) -> Dict[str, DeviceProfile]:
    label = "device_profiles"
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"{label}: must be an object")
    out = {}
    for key, profile in raw.items():
        out[key] = _parse_device_profile(profile, label=f"{label}.{key}")
    return out


def _parse_device_profile(raw: object, *, label: str) -> DeviceProfile:
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"{label}: must be an object")
    _reject_unknown(raw, _DEVICE_PROFILE_KEYS, label)

    if "extends" not in raw:
        raise ManifestValidationError(f"{label}.extends: required field is missing")
    extends = raw["extends"]
    if not isinstance(extends, str) or not extends:
        raise ManifestValidationError(
            f"{label}.extends: must be a non-empty string"
        )

    addons: Tuple[AddonEntry, ...] = ()
    if "addons" in raw:
        addons = _parse_addons(raw["addons"], label=f"{label}.addons")

    config = _parse_config(raw["config"], label=f"{label}.config") if "config" in raw else None
    skin = _parse_skin(raw["skin"], label=f"{label}.skin") if "skin" in raw else None

    include_optional: Tuple[str, ...] = ()
    if "include_optional" in raw:
        io = raw["include_optional"]
        if not isinstance(io, list):
            raise ManifestValidationError(
                f"{label}.include_optional: must be an array"
            )
        for j, ref in enumerate(io):
            if not isinstance(ref, str):
                raise ManifestValidationError(
                    f"{label}.include_optional[{j}]: must be a string"
                )
        include_optional = tuple(io)

    profile_label = ""
    if "label" in raw:
        lv = raw["label"]
        if not isinstance(lv, str):
            raise ManifestValidationError(
                f"{label}.label: must be a string if present, got {type(lv).__name__}"
            )
        profile_label = lv

    return DeviceProfile(
        extends=extends,
        label=profile_label,
        addons=addons,
        config=config,
        skin=skin,
        include_optional=include_optional,
    )


# ---------------------------------------------------------------------------
# Optional groups
# ---------------------------------------------------------------------------

def _parse_optional(raw: object) -> Tuple[OptionalGroup, ...]:
    label = "optional"
    if not isinstance(raw, list):
        raise ManifestValidationError(f"{label}: must be an array")
    seen_ids: set = set()
    out = []
    for i, group in enumerate(raw):
        lbl = f"{label}[{i}]"
        if not isinstance(group, dict):
            raise ManifestValidationError(f"{lbl}: must be an object")
        _reject_unknown(group, _OPTIONAL_GROUP_KEYS, lbl)

        if "id" not in group:
            raise ManifestValidationError(f"{lbl}.id: required field is missing")
        group_id = group["id"]
        if not isinstance(group_id, str) or not group_id:
            raise ManifestValidationError(f"{lbl}.id: must be a non-empty string")
        if not _RE_OPT_ID.match(group_id):
            raise ManifestValidationError(
                f"{lbl}.id: invalid optional group ID {group_id!r} "
                f"(must match ^[a-z0-9][a-z0-9_-]*$)"
            )
        if group_id in seen_ids:
            raise ManifestValidationError(
                f"{lbl}.id: duplicate optional group ID {group_id!r}"
            )
        seen_ids.add(group_id)

        addons: Tuple[AddonEntry, ...] = ()
        if "addons" in group:
            addons = _parse_addons(group["addons"], label=f"{lbl}.addons")

        config = _parse_config(group["config"], label=f"{lbl}.config") if "config" in group else None

        group_label = ""
        if "label" in group:
            lv = group["label"]
            if not isinstance(lv, str):
                raise ManifestValidationError(
                    f"{lbl}.label: must be a string if present, got {type(lv).__name__}"
                )
            group_label = lv

        group_desc = ""
        if "description" in group:
            dv = group["description"]
            if not isinstance(dv, str):
                raise ManifestValidationError(
                    f"{lbl}.description: must be a string if present, got {type(dv).__name__}"
                )
            group_desc = dv

        out.append(OptionalGroup(
            id=group_id,
            label=group_label,
            description=group_desc,
            addons=addons,
            config=config,
        ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Private overlay reference
# ---------------------------------------------------------------------------

def _parse_private_overlay(raw: object) -> Optional[PrivateOverlayRef]:
    if not isinstance(raw, dict):
        raise ManifestValidationError("private_overlay: must be an object")
    _reject_unknown(raw, _OVERLAY_KEYS, "private_overlay")

    if "type" not in raw:
        raise ManifestValidationError("private_overlay.type: required field is missing")
    ov_type = raw["type"]
    if not isinstance(ov_type, str):
        raise ManifestValidationError("private_overlay.type: must be a string")
    if ov_type not in _VALID_OVERLAY_TYPES:
        raise ManifestValidationError(
            f"private_overlay.type: unsupported type {ov_type!r}; "
            f"expected one of: {sorted(_VALID_OVERLAY_TYPES)}"
        )

    path_hint = ""
    if "path_hint" in raw:
        ph = raw["path_hint"]
        if not isinstance(ph, str):
            raise ManifestValidationError(
                f"private_overlay.path_hint: must be a string if present, got {type(ph).__name__}"
            )
        path_hint = ph

    overlay_desc = ""
    if "description" in raw:
        dv = raw["description"]
        if not isinstance(dv, str):
            raise ManifestValidationError(
                f"private_overlay.description: must be a string if present, got {type(dv).__name__}"
            )
        overlay_desc = dv

    return PrivateOverlayRef(type=ov_type, path_hint=path_hint, description=overlay_desc)


# ---------------------------------------------------------------------------
# Restart policy
# ---------------------------------------------------------------------------

def _parse_restart_policy(raw: object) -> Optional[RestartPolicy]:
    if not isinstance(raw, dict):
        raise ManifestValidationError("restart_policy: must be an object")
    _reject_unknown(raw, _RESTART_POLICY_KEYS, "restart_policy")

    allow_skin_reload = True
    if "allow_skin_reload" in raw:
        val = raw["allow_skin_reload"]
        if not isinstance(val, bool):
            raise ManifestValidationError(
                f"restart_policy.allow_skin_reload: must be a boolean, got {type(val).__name__}"
            )
        allow_skin_reload = val

    allow_kodi_restart = True
    if "allow_kodi_restart" in raw:
        val = raw["allow_kodi_restart"]
        if not isinstance(val, bool):
            raise ManifestValidationError(
                f"restart_policy.allow_kodi_restart: must be a boolean, got {type(val).__name__}"
            )
        allow_kodi_restart = val

    return RestartPolicy(
        allow_skin_reload=allow_skin_reload,
        allow_kodi_restart=allow_kodi_restart,
    )


# ---------------------------------------------------------------------------
# Semantic validation (cross-reference checks)
# ---------------------------------------------------------------------------

def _validate_semantic(
    *,
    platform_profiles: Dict[str, ProfileLayer],
    device_profiles: Dict[str, DeviceProfile],
    optional: Tuple[OptionalGroup, ...],
) -> None:
    opt_ids = {g.id for g in optional}

    for device_id, profile in device_profiles.items():
        if profile.extends not in platform_profiles:
            raise ManifestValidationError(
                f"device_profiles.{device_id}.extends: "
                f"unknown platform profile {profile.extends!r}"
            )

    for platform_id, layer in platform_profiles.items():
        for ref in layer.include_optional:
            if ref not in opt_ids:
                raise ManifestValidationError(
                    f"platform_profiles.{platform_id}.include_optional: "
                    f"unknown optional group {ref!r}"
                )

    for device_id, profile in device_profiles.items():
        for ref in profile.include_optional:
            if ref not in opt_ids:
                raise ManifestValidationError(
                    f"device_profiles.{device_id}.include_optional: "
                    f"unknown optional group {ref!r}"
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_str(raw: dict, key: str, label: str) -> str:
    if key not in raw:
        raise ManifestValidationError(f"{label}.{key}: required field is missing")
    val = raw[key]
    if not isinstance(val, str):
        raise ManifestValidationError(
            f"{label}.{key}: must be a string, got {type(val).__name__}"
        )
    if not val:
        raise ManifestValidationError(f"{label}.{key}: must not be empty")
    return val


def _reject_unknown(raw: dict, allowed: frozenset, label: str) -> None:
    unknown = set(raw.keys()) - allowed
    if unknown:
        raise ManifestValidationError(
            f"{label}: unknown field(s): {', '.join(sorted(unknown))}"
        )


def _validate_url(url: str, *, label: str) -> None:
    """Validate a bootstrap URL. Accepts https (preferred) and http (local/dev)."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise ManifestValidationError(f"{label}: malformed URL: {exc}") from exc

    if not parsed.scheme:
        raise ManifestValidationError(
            f"{label}: URL must be absolute (missing scheme): {url!r}"
        )
    if parsed.scheme not in _VALID_URL_SCHEMES:
        raise ManifestValidationError(
            f"{label}: URL scheme must be 'https' or 'http', got {parsed.scheme!r}"
        )
    if not parsed.netloc:
        raise ManifestValidationError(
            f"{label}: URL must be absolute (missing host): {url!r}"
        )
    if parsed.username or parsed.password:
        raise ManifestValidationError(
            f"{label}: URL must not contain embedded credentials"
        )


def _validate_managed_path(raw: object, *, label: str) -> str:
    """Validate a Kodi userdata-relative managed file path. Returns the normalized path."""
    if not isinstance(raw, str):
        raise ManifestValidationError(f"{label}: path must be a string")
    if not raw:
        raise ManifestValidationError(f"{label}: path must not be empty")
    if "\x00" in raw:
        raise ManifestValidationError(f"{label}: path must not contain null bytes")
    if raw.startswith("\\\\"):
        raise ManifestValidationError(f"{label}: UNC paths are not allowed")
    if raw.startswith("//"):
        raise ManifestValidationError(f"{label}: UNC-style paths are not allowed")
    if raw.startswith("/"):
        raise ManifestValidationError(f"{label}: absolute paths are not allowed")
    if len(raw) >= 2 and raw[1] == ":":
        raise ManifestValidationError(f"{label}: Windows drive paths are not allowed")

    normalized = raw.replace("\\", "/")
    for comp in normalized.split("/"):
        if comp == "..":
            raise ManifestValidationError(f"{label}: path traversal ('..') is not allowed")

    normed = posixpath.normpath(normalized)
    if normed.startswith("/"):
        raise ManifestValidationError(f"{label}: path normalizes outside allowed root")
    if normed == "..":
        raise ManifestValidationError(f"{label}: path traversal is not allowed")

    return normed
