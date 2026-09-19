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


class AF3PolicyError(ValueError):
    """An AF3-specific configuration relationship is invalid."""


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
