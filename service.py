"""Thin BM-020C Kodi startup and post-restart resume entrypoint."""


def main() -> None:
    try:
        import xbmc
    except (ImportError, AttributeError, RuntimeError):
        return
    try:
        from resources.lib.startup import (
            RESUME_FINGERPRINT_PROPERTY,
            RESUME_OUTCOME_PROPERTY,
            RESUME_REQUIREMENT_PROPERTY,
            STARTUP_CLASSIFICATION_PROPERTY,
            run_startup,
        )
        status = run_startup()
        try:
            from resources.lib.frozen_install import run_frozen_install_startup
            frozen_result = run_frozen_install_startup(bm020_status=status)
            if frozen_result is not None and not frozen_result.succeeded:
                xbmc.log(
                    f"Build Manager BM-022 startup: {frozen_result.outcome}",
                    xbmc.LOGERROR,
                )
        except Exception:
            xbmc.log(
                "[script.build.manager] BM-022 startup/resume unavailable",
                xbmc.LOGERROR,
            )
    except Exception:  # Kodi must retain a bounded, fail-closed service.
        xbmc.log("[script.build.manager] BM-020C startup/resume unavailable", xbmc.LOGERROR)
        return
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty(
            STARTUP_CLASSIFICATION_PROPERTY,
            status.classification.value,
        )
        resume_result = status.resume_result
        xbmcgui.Window(10000).setProperty(
            RESUME_OUTCOME_PROPERTY,
            resume_result.outcome.value if resume_result is not None else "",
        )
        reconcile_result = (
            resume_result.reconcile_result if resume_result is not None else None
        )
        xbmcgui.Window(10000).setProperty(
            RESUME_FINGERPRINT_PROPERTY,
            (
                reconcile_result.desired_fingerprint
                if reconcile_result is not None
                and reconcile_result.desired_fingerprint is not None
                else ""
            ),
        )
        xbmcgui.Window(10000).setProperty(
            RESUME_REQUIREMENT_PROPERTY,
            (
                reconcile_result.restart_report.requirement.value
                if reconcile_result is not None else ""
            ),
        )
        level = xbmc.LOGINFO
        xbmc.log(
            f"Build Manager BM-020C startup: {status.classification.value}",
            level,
        )
    except (ImportError, AttributeError, RuntimeError):
        # Logging is diagnostic only; startup classification has already run.
        pass


# Kodi loads service libraries as modules rather than relying on the normal
# Python script ``__main__`` convention.  Keep this one call as the complete
# service entrypoint; all behavior remains in resources.lib.startup.
main()
