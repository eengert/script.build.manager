"""Best-effort fixed workflow phases; never retain payloads or exception text."""
import re

PHASES = frozenset({
    'create.capture.incomplete',
    'create.capture.dependency_cycle',
    'create.capture.builtin_closure_unavailable',
    'create.capture.metadata_unavailable',
    'create.capture.metadata_invalid',
    'create.capture.application_root_refused',
    'create.capture.builtin_requirement_incompatible',
    'create.capture.platform_requirement_unsatisfied',
    'create.capture.capture_errors',
    'create.capture.incomplete_artifact',
    'create.capture.incomplete_provenance',
    'create.capture.invalid_package',
    'create.capture.unsupported',
    'create.capture.missing',
    'create.evidence.staging_confined_before',
    'create.evidence.staging_confined_cold_before',
    'create.evidence.staging_confined_first_candidate_before',
    'create.evidence.staging_cleaned',
    'create.evidence.staging_unverified',
    'create.evidence.roots_confined',
    'create.evidence.roots_unverified',
    'create.evidence.acquisition_store_only',
    'create.evidence.acquisition_unverified',
    'startup.evidence.restart_root_confined',
    'startup.evidence.restart_root_unverified',
    'startup.evidence.guard_frozen_owner_absent',
    'startup.evidence.publication_roots_confined',
    'startup.evidence.publication_roots_unverified',
    'startup.evidence.journal_present',
    'startup.evidence.journal_and_frozen_owner_absent',
    'startup.evidence.frozen_owner_absent_at_return',
    'status.provider', 'status.presentation', 'status.view_model',
    'status.view_model.overall_detail', 'status.view_model.build_rows',
    'status.view_model.addons_row', 'status.view_model.skin_row',
    'status.view_model.settings_row', 'status.view_model.private_row',
    'status.view_model.overall_timestamp', 'status.view_model.timestamp',
    'install.workflow', 'install.operation_gate', 'install.library',
    'install.build_selection', 'install.profile_selection', 'install.target',
    'install.preview', 'install.plan_conversion', 'install.resolution_required',
    'install.plan_conversion.repository_current', 'install.plan_conversion.entry',
    'install.plan_conversion.sections', 'install.plan_conversion.decisions',
    'install.plan_conversion.timestamp', 'install.plan_conversion.confirmation_summary',
    'install.plan_conversion.model',
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
