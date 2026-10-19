"""AF3-specific configuration policy (BM-018D).

The generic configuration loader owns target parsing, typed values, overlays,
and ownership. AF3's UI relationship rules belong here so the generic skin
setting backend remains reusable for other Kodi skins.
"""

from __future__ import annotations

from typing import Mapping
import re


AF3_SKIN_ID = "skin.arctic.fuse.3"
AF3_ENABLE_ICONS_KEY = "HomeSwitcher.EnableIcons"
AF3_ENABLE_ICON_TEXT_KEY = "HomeSwitcher.EnableIconText"
AF3_3312_VERSION = "3.3.12"
AF3_3312_PACKAGE = "af3-3.3.12"
AF3_3312_KEYS = frozenset((
    "HomeSwitcher.Vertical", "HomeSwitcher.EnableIcons",
    "HomeSwitcher.DisableHeader", "HomeSwitcher.DisableDate",
    "HomeSwitcher.DisableSearch", "HomeSwitcher.DisableFirstWidgetFocus",
    "HomeSwitcher.LoopBack", "Spotlight.EnableSlide", "Spotlight.UseMenuButton",
    "View.UseDetailedListLabels", "Widgets.EnableShowMore",
    "Widgets.DisableNoResultsItem", "Navigation.OnBack", "Seekbar.TimeDisplay",
    "Skin.FlixArt.Size",
))


class AF3PolicyError(ValueError):
    """An AF3-specific configuration relationship is invalid."""

    code = "AF3_CONFIGURATION_INCOMPATIBLE"


class AF3TargetVersionError(AF3PolicyError):
    code = "AF3_TARGET_VERSION_UNVERIFIED"


class AF3ActualVersionError(AF3PolicyError):
    code = "AF3_ACTUAL_VERSION_MISMATCH"


class AF3RestartRequiredError(AF3PolicyError):
    code = "AF3_CONFIGURATION_RESTART_REQUIRED"


def is_af3_identity(addon_id):
    """Recognize potential AF3 ASCII spellings for policy admission only.

    This is not an execution/storage alias or a global Kodi identity rule.
    """
    return isinstance(addon_id, str) and addon_id.isascii() and addon_id.strip(" \t\r\n\v\f").lower() == AF3_SKIN_ID


def validate_identities(settings):
    for setting in settings:
        if is_af3_identity(setting.addon_id) and setting.addon_id != AF3_SKIN_ID:
            raise AF3PolicyError("AF3 configuration requires the canonical add-on ID")


def has_configuration(configuration, private_settings=()):
    return (configuration is not None and (
        AF3_3312_PACKAGE in configuration.packages or any(
            is_af3_identity(setting.addon_id) for setting in configuration.settings))) or any(
                is_af3_identity(setting.addon_id) for setting in private_settings)


def capture_package(version):
    """Select the approved exact-version scope; legacy policy stays unchanged."""
    return AF3_3312_PACKAGE if version == AF3_3312_VERSION else "af3-common"


def validate_configuration_version(configuration, versions, private_settings=()):
    """Read-only target-version preflight. Never migrate or alias stored targets.

    A named 3.3.12 package requires exact target-version evidence. Other packages
    (including captured public packages) cannot write unsupported AF3 keys when
    their target is 3.3.12. Unversioned legacy configurations retain their prior
    semantics outside that exact version. Private AF3 settings require verified
    legacy-version evidence and are never admitted for 3.3.12.
    """
    public = configuration.settings if configuration is not None else ()
    packages = configuration.packages if configuration is not None else ()
    # Validate the complete ownership set before setting relationships or values.
    validate_identities((*public, *private_settings))
    version = versions.get(AF3_SKIN_ID)
    if has_configuration(configuration, private_settings) and (
        not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version)
    ):
        raise AF3TargetVersionError("AF3 exact target version could not be verified")
    if AF3_3312_PACKAGE in packages and version != AF3_3312_VERSION:
        raise AF3PolicyError("AF3 3.3.12 catalog requires exact target version 3.3.12")
    if version == AF3_3312_VERSION and any(
        is_af3_identity(setting.addon_id) for setting in private_settings
    ):
        raise AF3PolicyError("AF3 3.3.12 private setting declarations are not admitted")
    if version == AF3_3312_VERSION and any(
        setting.addon_id == AF3_SKIN_ID
        and setting.key not in AF3_3312_KEYS for setting in public
    ):
        raise AF3PolicyError("AF3 3.3.12 configuration is incompatible with the supported 15-key scope")


def validate_skin_settings(settings_map: Mapping[tuple, object]) -> None:
    """Reject contradictory AF3 HomeSwitcher mode settings."""
    validate_identities(settings_map.values())
    icons = settings_map.get(("skin", AF3_SKIN_ID, AF3_ENABLE_ICONS_KEY))
    icon_text = settings_map.get(("skin", AF3_SKIN_ID, AF3_ENABLE_ICON_TEXT_KEY))
    if (
        icons is not None
        and icon_text is not None
        and getattr(icons, "value", object()) is True
        and getattr(icon_text, "value", object()) is True
    ):
        raise AF3PolicyError(
            "AF3 skin settings HomeSwitcher.EnableIcons and "
            "HomeSwitcher.EnableIconText are mutually exclusive; both "
            "cannot be true"
        )


def private_policy_targets(declarations=(), prepared=None):
    """Metadata only: include entries even for programmatically prepared overlays."""
    targets = tuple(declarations)
    if prepared is not None:
        targets += tuple(getattr(prepared, "declarations", ()))
        overlay = getattr(prepared, "overlay", None)
        if overlay is not None:
            targets += tuple(getattr(overlay, "entries", ()))
    return targets
