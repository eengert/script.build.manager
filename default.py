"""Open Build Manager's native Kodi menu and compose confirmed workflows lazily."""

def status_provider(xbmc):
    """Read-only Build Status check; imported lazily so a failure stays on the page."""
    def provide():
        from resources.lib.status import check_build_status
        return check_build_status(
            log=lambda message: xbmc.log("[script.build.manager] " + message, xbmc.LOGINFO))
    return provide


def background_busy(xbmcgui, heading):
    """Own one modeless progress handle; never close another caller's dialog."""
    progress = None

    def busy(active):
        nonlocal progress
        if active:
            if progress is None:
                progress = xbmcgui.DialogProgressBG()
                progress.create(heading)
        elif progress is not None:
            progress.close()
            progress = None
    return busy


def main():
    import xbmc
    import xbmcaddon
    import xbmcgui
    addon = xbmcaddon.Addon("script.build.manager")
    try:
        from resources.lib.ui.native_dialogs import NativeDialogs
        from resources.lib.create_workflow import runtime_create_workflow
        def install_provider():
            from resources.lib.install_workflow import runtime_install_workflow
            return runtime_install_workflow()
        def repair_provider():
            from resources.lib.update_repair_workflow import runtime_update_repair_workflow
            return runtime_update_repair_workflow()
        busy = background_busy(xbmcgui, addon.getLocalizedString(32101))
        NativeDialogs(addon, xbmcgui.Dialog(), xbmc.sleep, status_provider(xbmc),
                      create_provider=runtime_create_workflow, busy=busy, install_provider=install_provider,
                      repair_provider=repair_provider).run()
    except Exception:
        # Never expose runtime exceptions or private settings in fallback text.
        xbmcgui.Dialog().ok(addon.getLocalizedString(32126),
                            addon.getLocalizedString(32127))

if __name__ == '__main__':
    main()
