"""
Build Manager profile resolver (BM-004).

Public API
----------
resolve_manifest(manifest, device_profile_id) -> ResolvedBuild
    Merge all manifest layers for a given device profile and return the
    resolved desired configuration.

Errors
------
ManifestResolutionError -- a named device or platform profile is missing,
                           or a referenced optional group is not defined.

Merge semantics — see docs/MANIFEST.md §Merge semantics.

Layer application order
-----------------------
base → platform profile → device profile → optional groups (in resolved order)

Optional-group de-duplication
------------------------------
Groups are collected from platform.include_optional (in listed order) then
device.include_optional (in listed order). Duplicate IDs are dropped by first
occurrence. Each group is applied at most once.

Stdlib only — no new runtime dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from resources.lib.manifest import (
    AddonEntry,
    BuildInfo,
    ConfigDeclarations,
    DeviceProfile,
    ManifestError,
    ManagedSettingScope,
    Manifest,
    OptionalGroup,
    PrivateOverlayRef,
    ProfileLayer,
    Repository,
    RestartPolicy,
    SkinEntry,
)


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class ManifestResolutionError(ManifestError):
    """Failed to resolve manifest layers.

    Raised when the requested device profile is unknown, its platform profile
    cannot be found, or a referenced optional group is not defined.
    """


# ---------------------------------------------------------------------------
# Resolved output type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedBuild:
    """Fully resolved desired configuration for one device profile.

    Produced by resolve_manifest(). All collection fields are tuples; nested
    objects are the same frozen dataclass instances as in the source Manifest.
    Callers should not mutate any field.
    """
    build: BuildInfo
    engine_min_version: str
    platform_profile_id: str
    device_profile_id: str
    repositories: Tuple[Repository, ...]
    addons: Tuple[AddonEntry, ...]
    skin: Optional[SkinEntry]
    config: Optional[ConfigDeclarations]
    optional_groups_applied: Tuple[str, ...]
    restart_policy: Optional[RestartPolicy]
    private_overlay: Optional[PrivateOverlayRef]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_manifest(manifest: Manifest, device_profile_id: str) -> ResolvedBuild:
    """Resolve all manifest layers for device_profile_id.

    Layer order: base → platform profile → device profile → optional groups.

    Raises:
        ManifestResolutionError: if device_profile_id is not in
            manifest.device_profiles, the device's extends platform is not in
            manifest.platform_profiles, or a requested optional group is not
            found in manifest.optional.
    """
    # 1. Locate device profile
    if device_profile_id not in manifest.device_profiles:
        raise ManifestResolutionError(
            f"device_profiles.{device_profile_id}: unknown device profile"
        )
    device = manifest.device_profiles[device_profile_id]

    # 2. Locate platform profile via device.extends
    platform_id = device.extends
    if platform_id not in manifest.platform_profiles:
        raise ManifestResolutionError(
            f"device_profiles.{device_profile_id}.extends: "
            f"platform profile {platform_id!r} not found"
        )
    platform = manifest.platform_profiles[platform_id]

    # 3. Determine optional groups in application order (deduplicated)
    opt_map: Dict[str, OptionalGroup] = {g.id: g for g in manifest.optional}
    applied_ids = _resolve_optional_ids(platform, device, opt_map)
    opt_groups = [opt_map[gid] for gid in applied_ids]

    # 4. Merge add-ons: base → platform → device → optional groups
    addons = _merge_addons(
        base=manifest.addons,
        layers=[platform.addons, device.addons] + [g.addons for g in opt_groups],
    )

    # 5. Resolve skin: deepest explicit layer wins
    skin = _resolve_skin([manifest.skin, platform.skin, device.skin])

    # 6. Merge config: base → platform → device → optional groups
    config = _merge_config(
        [manifest.config, platform.config, device.config]
        + [g.config for g in opt_groups]
    )

    return ResolvedBuild(
        build=manifest.build,
        engine_min_version=manifest.engine_min_version,
        platform_profile_id=platform_id,
        device_profile_id=device_profile_id,
        repositories=manifest.repositories,
        addons=addons,
        skin=skin,
        config=config,
        optional_groups_applied=tuple(applied_ids),
        restart_policy=manifest.restart_policy,
        private_overlay=manifest.private_overlay,
    )


# ---------------------------------------------------------------------------
# Optional-group ID resolution
# ---------------------------------------------------------------------------

def _resolve_optional_ids(
    platform: ProfileLayer,
    device: DeviceProfile,
    opt_map: Dict[str, OptionalGroup],
) -> List[str]:
    """Return ordered, deduplicated optional group IDs.

    Collects from platform.include_optional then device.include_optional,
    both in listed order. Drops duplicate IDs by first occurrence.
    Each group is applied at most once.
    """
    seen: set = set()
    result: List[str] = []
    for gid in list(platform.include_optional) + list(device.include_optional):
        if gid in seen:
            continue
        if gid not in opt_map:
            raise ManifestResolutionError(
                f"optional group {gid!r} not found in manifest"
            )
        seen.add(gid)
        result.append(gid)
    return result


# ---------------------------------------------------------------------------
# Add-on merge
# ---------------------------------------------------------------------------

def _merge_addons(
    base: Tuple[AddonEntry, ...],
    layers: List[Tuple[AddonEntry, ...]],
) -> Tuple[AddonEntry, ...]:
    """Merge add-on layers, preserving deterministic ordering.

    - An overriding entry retains the position of the entry it replaces.
    - New add-ons are appended in first-seen order.
    - The full entry (state + note) from the overriding layer replaces
      the previous entry for that addon_id.
    """
    order: List[str] = []
    current: Dict[str, AddonEntry] = {}

    for entry in base:
        order.append(entry.addon_id)
        current[entry.addon_id] = entry

    for layer in layers:
        for entry in layer:
            if entry.addon_id not in current:
                order.append(entry.addon_id)
            current[entry.addon_id] = entry

    return tuple(current[aid] for aid in order)


# ---------------------------------------------------------------------------
# Skin resolution
# ---------------------------------------------------------------------------

def _resolve_skin(layers: List[Optional[SkinEntry]]) -> Optional[SkinEntry]:
    """Return the deepest non-None skin across the given layers."""
    result: Optional[SkinEntry] = None
    for layer_skin in layers:
        if layer_skin is not None:
            result = layer_skin
    return result


# ---------------------------------------------------------------------------
# Config merge
# ---------------------------------------------------------------------------

def _merge_config(
    layers: List[Optional[ConfigDeclarations]],
) -> Optional[ConfigDeclarations]:
    """Merge config declarations using union semantics.

    - packages: union in first-seen order, no duplicates
    - managed_settings: per addon_id, keys unioned in first-seen order,
      addon_id order is first-seen
    - managed_files: union in first-seen order, no duplicates

    Returns None when every supplied layer has no config.
    """
    pkg_seen: set = set()
    packages: List[str] = []

    ms_order: List[str] = []
    ms_keys: Dict[str, List[str]] = {}
    ms_keys_seen: Dict[str, set] = {}

    file_seen: set = set()
    files: List[str] = []

    any_config = False
    for cfg in layers:
        if cfg is None:
            continue
        any_config = True

        for pkg in cfg.packages:
            if pkg not in pkg_seen:
                pkg_seen.add(pkg)
                packages.append(pkg)

        for scope in cfg.managed_settings:
            if scope.addon_id not in ms_keys:
                ms_order.append(scope.addon_id)
                ms_keys[scope.addon_id] = []
                ms_keys_seen[scope.addon_id] = set()
            for key in scope.keys:
                if key not in ms_keys_seen[scope.addon_id]:
                    ms_keys_seen[scope.addon_id].add(key)
                    ms_keys[scope.addon_id].append(key)

        for path in cfg.managed_files:
            if path not in file_seen:
                file_seen.add(path)
                files.append(path)

    if not any_config:
        return None

    return ConfigDeclarations(
        packages=tuple(packages),
        managed_settings=tuple(
            ManagedSettingScope(addon_id=aid, keys=tuple(ms_keys[aid]))
            for aid in ms_order
        ),
        managed_files=tuple(files),
    )
