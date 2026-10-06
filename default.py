"""Open Build Manager's native Kodi menu and compose confirmed workflows lazily."""

def status_provider(xbmc):
    """Read-only Build Status check; imported lazily so a failure stays on the page."""
    def provide():
        from resources.lib.status import check_build_status
        return check_build_status(
            log=lambda message: xbmc.log("[script.build.manager] " + message, xbmc.LOGINFO))
    return provide


def main():
    import xbmc
    import xbmcaddon
    import xbmcgui
    addon = xbmcaddon.Addon("script.build.manager")
    try:
        from resources.lib.ui.native_dialogs import NativeDialogs
        from resources.lib.create_workflow import runtime_create_workflow
        def busy(active):
            xbmc.executebuiltin('ActivateWindow(busydialognocancel)' if active else 'Dialog.Close(busydialognocancel)')
        NativeDialogs(addon, xbmcgui.Dialog(), xbmc.sleep, status_provider(xbmc),
                      create_provider=runtime_create_workflow, busy=busy).run()
    except Exception:
        # Never expose runtime exceptions or private settings in fallback text.
        xbmcgui.Dialog().ok(addon.getLocalizedString(32126),
                            addon.getLocalizedString(32127))

if __name__ == '__main__':
    main()
