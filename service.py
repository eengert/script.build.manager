"""Thin BM-020B Kodi startup entrypoint."""


def main() -> None:
    try:
        import xbmc
    except (ImportError, AttributeError, RuntimeError):
        return
    try:
        from resources.lib.startup import (
            STARTUP_CLASSIFICATION_PROPERTY,
            run_startup,
        )
        status = run_startup()
    except Exception:  # Kodi must retain a bounded, fail-closed service.
        xbmc.log("[script.build.manager] BM-020B startup foundation unavailable", xbmc.LOGERROR)
        return
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty(
            STARTUP_CLASSIFICATION_PROPERTY,
            status.classification.value,
        )
        level = xbmc.LOGINFO
        xbmc.log(
            f"Build Manager BM-020B startup: {status.classification.value}",
            level,
        )
    except (ImportError, AttributeError, RuntimeError):
        # Logging is diagnostic only; startup classification has already run.
        pass


# Kodi loads service libraries as modules rather than relying on the normal
# Python script ``__main__`` convention.  Keep this one call as the complete
# service entrypoint; all behavior remains in resources.lib.startup.
main()
