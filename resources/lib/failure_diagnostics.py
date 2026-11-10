"""Best-effort fixed workflow phases; never retain payloads or exception text."""
import re

PHASES = frozenset({
    'status.provider', 'status.presentation', 'status.view_model',
    'install.workflow', 'install.operation_gate', 'install.library',
    'install.build_selection', 'install.profile_selection', 'install.target',
    'install.preview', 'install.plan_conversion', 'install.resolution_required',
    'install.decision', 'install.preparation', 'install.confirmation',
    'install.validation', 'install.execution_target', 'install.execution_wrapper',
    'install.coordinator_factory', 'install.coordinator_invoke',
    'install.coordinator_result', 'install.result_presentation',
})


def emit(phase, exception=None, log=None):
    try:
        if phase not in PHASES:
            return
        message = '[script.build.manager] diagnostic phase=' + phase
        if exception is not None:
            name = type(exception).__name__
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name):
                name = 'Exception'
            message += ' exception=' + name
        if log is None:
            import xbmc
            xbmc.log(message, xbmc.LOGINFO)
        else:
            log(message)
    except Exception:
        # Diagnostics must never affect the observed operation or its fallback.
        pass


def call(phase, operation, *, log=None):
    emit(phase, log=log)
    try:
        return operation()
    except Exception as exc:
        emit(phase, exc, log=log)
        raise
