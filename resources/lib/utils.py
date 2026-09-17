import xbmcaddon

_ADDON = xbmcaddon.Addon()


def getString(string_id):
    """Return a localized string by its numeric ID."""
    return _ADDON.getLocalizedString(string_id)
