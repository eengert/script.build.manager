"""AF3-specific configuration policy (BM-018D).

The generic configuration loader owns target parsing, typed values, overlays,
and ownership. AF3's UI relationship rules belong here so the generic skin
setting backend remains reusable for other Kodi skins.
"""

from __future__ import annotations

from typing import Mapping


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


def capture_package(version):
    """Select the approved exact-version scope; legacy policy stays unchanged."""
    return AF3_3312_PACKAGE if version == AF3_3312_VERSION else "af3-common"


def validate_configuration_version(configuration, versions):
    """Read-only target-version preflight. Never migrate or alias stored targets.

    A named 3.3.12 package requires exact target-version evidence. Other packages
    (including captured public packages) cannot write unsupported AF3 keys when
    their target is 3.3.12. Unversioned legacy configurations retain their prior
    semantics outside that exact version.
    """
    if configuration is None:
        return
    version = versions.get(AF3_SKIN_ID)
    if AF3_3312_PACKAGE in configuration.packages and version != AF3_3312_VERSION:
        raise AF3PolicyError("AF3 3.3.12 catalog requires exact target version 3.3.12")
    if version == AF3_3312_VERSION and any(
        setting.target_kind.value == "skin" and setting.addon_id == AF3_SKIN_ID
        and setting.key not in AF3_3312_KEYS for setting in configuration.settings
    ):
        raise AF3PolicyError("AF3 3.3.12 configuration is incompatible with the supported 15-key scope")


def validate_skin_settings(settings_map: Mapping[tuple, object]) -> None:
    """Reject contradictory AF3 HomeSwitcher mode settings."""
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
