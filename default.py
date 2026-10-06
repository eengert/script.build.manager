"""Open Build Manager's native Kodi menu without starting operations."""

def main():
    import xbmc
    import xbmcaddon
    import xbmcgui
    addon = xbmcaddon.Addon("script.build.manager")
    try:
        from resources.lib.ui.native_dialogs import NativeDialogs
        NativeDialogs(addon, xbmcgui.Dialog(), xbmc.sleep).run()
    except Exception:
        # Never expose runtime exceptions or private settings in fallback text.
        xbmcgui.Dialog().ok(addon.getLocalizedString(32126),
                            addon.getLocalizedString(32127))

if __name__ == '__main__':
    main()
