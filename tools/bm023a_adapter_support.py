"""Secret-safe bootstrap checks shared by the generated BM-023A adapter."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import ModuleType
from typing import Any, Dict


ADAPTER_VERSION = "0.0.15"
ADDON_ID = "script.build.manager"
DRIVER_ADDON_ID = "script.build.manager.bm023a_driver"
BUNDLED_FROZEN_INSTALL_NAME = "bundled_frozen_install.py"
HELD_RETRY_OWNER_ID = "plugin.video.redlight"
HELD_RETRY_FAILURE_CODE = "FROZEN_MANIFEST_INVALID"

ADAPTER_STAGES = frozenset({
    "LOCATE_BUILD_MANAGER",
    "IMPORT_RESOURCES",
    "VERIFY_BUILD_MANAGER_SOURCE",
    "IMPORT_PRODUCTION_MODULES",
    "LOAD_FROZEN_MANIFEST",
    "LOAD_CONFIGURATION",
    "LOAD_PRIVATE_OVERLAY",
    "STAGE_RETAINED_ARTIFACTS",
    "BUILD_COORDINATOR",
    "INVOKE_INSTALL",
    "CHECK_RECOVERY_PRECONDITIONS",
    "INVOKE_RECOVERY",
    "CHECK_RETRY_PRECONDITIONS",
    "INVOKE_RETRY",
    "READ_STATUS",
    "SERIALIZE_RESULT",
})
ADAPTER_CALLABLES = frozenset({
    "xbmcvfs.translatePath",
    "pathlib.Path",
    "importlib.import_module",
    "FrozenBuildManifest.from_json",
    "PrivateOverlayStore.import_file",
    "ArtifactStore.__init__",
    "ArtifactStore.read_bytes",
    "ArtifactStore.import_zip",
    "default_frozen_install_root",
    "BuildManager",
    "FrozenInstallCoordinator",
    "FrozenInstallCoordinator.install",
    "FrozenInstallCoordinator.retry_held_quiescence",
    "FrozenInstallStore",
    "FrozenInstallStore.inspect",
    "TransactionStore",
    "TransactionStore.inspect",
    "FrozenInstallCoordinator.abandon",
    "UpdatePolicyBackend.get_policy",
    "KodiRuntimeFrozenArtifactBackend.get_addon_details",
    "read_adapter_status",
    "result_serializer",
})
FAILURE_CATEGORIES = frozenset({
    "path_argument_is_none",
    "path_missing_or_unreadable",
    "addon_root_mismatch",
    "module_source_missing",
    "module_source_unreadable",
    "module_source_mismatch",
    "module_import_failed",
    "invalid_input",
    "operation_failed",
    "transaction_missing",
    "recovery_phase_mismatch",
    "transaction_identity_invalid",
    "original_policy_missing",
    "unsupported_recovery_state",
    "mode_missing",
    "mode_invalid",
    "artifact_stage_failed",
    "retry_snapshot_invalid",
    "retry_identity_mismatch",
    "recovery_identity_mismatch",
    "retry_api_unavailable",
    "retry_invocation_failed",
    "module_cache_preloaded",
    "bundled_source_mismatch",
    "source_target_invalid",
    "source_replace_failed",
    "source_reverify_failed",
    "retained_manifest_missing",
    "retained_manifest_unreadable",
    "retained_artifacts_missing",
})
SAFE_ERROR_TYPES = frozenset({
    "TypeError", "OSError", "ImportError", "ModuleNotFoundError",
    "ValueError", "RuntimeError", "Exception",
    "FileNotFoundError", "PermissionError",
})
RETAINED_INPUTS_KEYS = frozenset({
    "manifest_present",
    "manifest_readable",
    "artifact_store_present",
    "artifact_store_readable",
    "artifact_entry_count",
})


STATUS_KEYS = frozenset({
    "adapter_version",
    "frozen_transaction_state",
    "frozen_phase",
    "frozen_lifecycle_stage",
    "frozen_lifecycle_restart_count",
    "frozen_status_code",
    "activation_hold_count",
    "redlight_hold_present",
    "activation_hold_released",
    "updater_guard_required",
    "private_overlay_required",
    "original_update_policy",
    "resolution_record_count",
    "restart_transaction_state",
    "restart_phase",
    "restart_attempt_count",
    "restart_status_code",
    "restart_transaction_linked",
    "frozen_lock_file_present",
    "restart_lock_file_present",
})
STATUS_FROZEN_PHASES = frozenset({
    "preparing", "installing_software", "configuring", "awaiting_restart",
    "resuming", "validating", "needs_attention", "complete",
})
STATUS_LIFECYCLE_STAGES = frozenset({
    "none", "installing_software", "quiescence_awaiting_restart", "configuring",
    "configuration_awaiting_restart", "private_verified", "activation_released",
    "final_activation_awaiting_restart",
})
STATUS_RESTART_PHASES = frozenset({"awaiting_restart", "resuming", "needs_attention"})
STATUS_UPDATE_POLICIES = frozenset({"AUTOMATIC", "NOTIFY_ONLY", "NEVER_CHECK"})
# Public diagnostics emitted by frozen_install and resume. Durable records
# permit arbitrary bounded strings: a code-shaped string is not public data.
# Unknown codes (including dynamically formed exception codes) stay null.
STATUS_FROZEN_CODES = frozenset({
    "FROZEN_INSTALL_ERROR", "FROZEN_INSTALL_FAILED", "FROZEN_MANIFEST_INVALID",
    "FROZEN_TRANSACTION_PERSISTENCE_FAILED", "FROZEN_TRANSACTION_STATE_CONFLICT",
    "QUIESCENCE_RESTART_REQUIRED", "QUIESCENCE_VALIDATION_FAILED",
    "LIFECYCLE_RESTART_LIMIT", "FROZEN_RESUME_FAILED",
    "FROZEN_HELD_RETRY_CONTINUATION_FAILED", "FROZEN_TRANSACTION_CLEAR_FAILED",
    "FROZEN_ACTIVATION_HOLD_MISMATCH", "FROZEN_PRIVATE_OVERLAY_IDENTITY_MISMATCH",
    "FROZEN_ADDON_REGISTRY_CHECK_FAILED", "FROZEN_TRANSACTION_INSPECTION_FAILED",
    "FROZEN_LIFECYCLE_STAGE_INVALID", "FROZEN_UPDATER_NOT_QUARANTINED",
    "FROZEN_UPDATER_STATE_UNAVAILABLE", "FROZEN_ACTIVATION_HOLD_UNAVAILABLE",
    "FROZEN_HELD_RESOLUTION_MISSING", "PRIVATE_RESOURCE_RESUME_NOT_VERIFIED",
    "PRIVATE_OVERLAY_RESUME_MISMATCH", "FINAL_VALIDATION_FAILED",
    "PRIVATE_RESOURCE_NOT_VERIFIED", "INSTALL_RESOLUTION_MISSING",
    "RESOLVED_VERSION_VALIDATION_FAILED", "FINAL_STATE_VALIDATION_FAILED",
    "RESOLUTION_FINGERPRINT_MISMATCH", "RESOLUTION_PERSISTENCE_FAILED",
    "SKIPPED_ADDON_PRESENT", "UPDATE_POLICY_RESTORE_FAILED", "UPDATER_REASSERT_FAILED",
    "FROZEN_CONFIGURATION_FAILED",
    "FROZEN_CONFIGURATION_ACTION_FAILED", "FROZEN_CONFIGURATION_ACTION_EXECUTION_FAILED",
    "FROZEN_CONFIGURATION_INSPECTION_FAILED", "FROZEN_CONFIGURATION_INVALID_REQUEST",
    "FROZEN_CONFIGURATION_MANIFEST_LOAD_FAILED", "FROZEN_CONFIGURATION_PLANNING_FAILED",
    "FROZEN_CONFIGURATION_POST_VALIDATION_FAILED", "FROZEN_CONFIGURATION_PREFLIGHT_FAILED",
    "FROZEN_CONFIGURATION_PRIVATE_OVERLAY_SUPPORT_UNAVAILABLE",
    "FROZEN_CONFIGURATION_RESOLUTION_FAILED", "FROZEN_CONFIGURATION_UNKNOWN_ACTION_KIND",
    "FROZEN_CONFIGURATION_VALIDATION_FAILED",
})
STATUS_RESTART_CODES = frozenset({
    "SESSION_IDENTITY_UNAVAILABLE", "PREVIEW_FAILED", "FINGERPRINT_MISMATCH",
    "PRIVATE_OVERLAY_FINGERPRINT_MISMATCH", "PRE_RECONCILE_READINESS_FAILED",
    "RECONCILE_EXCEPTION", "RECONCILE_FAILED", "FINAL_FINGERPRINT_MISMATCH",
    "RESTART_REQUIRED_AFTER_RESUME", "UNSUPPORTED_RESTART_REQUIREMENT", "RESUME_FAILED",
    "ACTION_FAILED", "ACTION_EXECUTION_FAILED", "INSPECTION_FAILED", "INVALID_REQUEST",
    "MANIFEST_LOAD_FAILED", "PLANNING_FAILED", "POST_VALIDATION_FAILED", "PREFLIGHT_FAILED",
    "PRIVATE_OVERLAY_SUPPORT_UNAVAILABLE", "RESOLUTION_FAILED", "UNKNOWN_ACTION_KIND",
    "VALIDATION_FAILED",
    "FROZEN_TRANSACTION_INSPECTION_FAILED", "FROZEN_LIFECYCLE_STAGE_INVALID",
    "FROZEN_SAME_SESSION", "FROZEN_RESUME_IDENTITY_MISMATCH",
    "FROZEN_PRIVATE_OVERLAY_IDENTITY_MISMATCH", "FROZEN_RESUME_IDENTITY_INVALID",
    "FROZEN_UPDATER_NOT_QUARANTINED", "FROZEN_UPDATER_STATE_UNAVAILABLE",
    "FROZEN_ACTIVATION_HOLD_UNAVAILABLE", "FROZEN_ACTIVATION_HOLD_MISMATCH",
    "FROZEN_HELD_RESOLUTION_MISSING", "FROZEN_ADDON_REGISTRY_CHECK_FAILED",
})
_STATUS_MAX_COUNT = 10000
_STATUS_FROZEN_MAX_BYTES = 1024 * 1024
_STATUS_RESTART_MAX_BYTES = 128 * 1024


class AdapterBootstrapError(Exception):
    """A failure containing only allowlisted bootstrap diagnostic labels."""

    def __init__(
        self,
        stage: str,
        failing_callable: str,
        category: str,
        *,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ):
        self.stage = stage if stage in ADAPTER_STAGES else "LOCATE_BUILD_MANAGER"
        self.failing_callable = (
            failing_callable if failing_callable in ADAPTER_CALLABLES else "result_serializer"
        )
        self.failure_category = (
            category if category in FAILURE_CATEGORIES else "operation_failed"
        )
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256
        super().__init__(self.failure_category)


def _bootstrap_error(
    stage: str,
    callable_name: str,
    category: str,
    *,
    expected_sha256: str | None = None,
    observed_sha256: str | None = None,
) -> AdapterBootstrapError:
    return AdapterBootstrapError(
        stage,
        callable_name,
        category,
        expected_sha256=expected_sha256,
        observed_sha256=observed_sha256,
    )


def _is_sha256_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def parse_adapter_mode(arguments: list[str]) -> str:
    """Accept one explicit allowlisted token; never default to a mutating mode."""
    if not arguments or arguments == [""]:
        raise _bootstrap_error(
            "LOCATE_BUILD_MANAGER", "result_serializer", "mode_missing"
        )
    if len(arguments) == 1:
        token = arguments[0]
        if token in ("install", "recover", "retry", "status"):
            return token
        if token == "?mode=install":
            return "install"
        if token == "?mode=recover":
            return "recover"
        if token == "?mode=retry":
            return "retry"
        if token == "?mode=status":
            return "status"
    raise _bootstrap_error(
        "LOCATE_BUILD_MANAGER", "result_serializer", "mode_invalid"
    )


def identify_adapter_result(payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Tag every result with the selected mode or the safe preselection value."""
    safe_mode = (
        mode if mode in ("install", "recover", "retry", "status") else "unselected"
    )
    identified = dict(payload)
    identified["adapter_mode"] = safe_mode
    return identified


def _status_enum_value(value: Any, allowed: frozenset) -> Any:
    candidate = getattr(value, "value", value)
    return candidate if isinstance(candidate, str) and candidate in allowed else None


def _status_code(value: Any, allowed: frozenset) -> Any:
    return value if isinstance(value, str) and value in allowed else None


def _status_count(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= _STATUS_MAX_COUNT else None


def _status_bool(value: Any) -> Any:
    return value if isinstance(value, bool) else None


def _status_file_present(path: Any) -> bool:
    try:
        os.lstat(path)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _status_load(path: Any, limit: int, loader: Any) -> tuple[str, Any]:
    """Read a bounded regular record without locks or blocking FIFO opens."""
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return "absent", None
    except (OSError, TypeError, ValueError):
        return "unreadable", None
    if not stat.S_ISREG(before.st_mode):
        return "unreadable", None
    # Never fall back to a blocking or symlink-following open on a platform
    # lacking these flags. fstat checks the opened object, not a raced path.
    if not hasattr(os, "O_NONBLOCK") or not hasattr(os, "O_NOFOLLOW"):
        return "unreadable", None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev, opened.st_ino
            ) != (before.st_dev, before.st_ino):
                return "unreadable", None
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(limit + 1)
            after = os.lstat(path)
            if not stat.S_ISREG(after.st_mode) or (
                after.st_dev, after.st_ino
            ) != (opened.st_dev, opened.st_ino):
                return "unreadable", None
        finally:
            os.close(fd)
    except (OSError, TypeError, ValueError):
        return "unreadable", None
    if len(raw) > limit:
        return "invalid", None
    try:
        return "present", loader(json.loads(raw.decode("utf-8")))
    except Exception:
        return "invalid", None


def read_adapter_status(
    frozen_transaction_path: Any,
    frozen_lock_path: Any,
    restart_transaction_path: Any,
    restart_lock_path: Any,
    load_frozen: Any,
    load_restart: Any,
) -> Dict[str, Any]:
    """Return the fixed sanitized status record from read-only file reads.

    No lock is taken (so no other process is ever blocked), nothing is
    created, and only enumerated values, bounded counts and booleans leave.
    """
    status: Dict[str, Any] = {key: None for key in STATUS_KEYS}
    status["adapter_version"] = ADAPTER_VERSION
    status["frozen_lock_file_present"] = _status_file_present(frozen_lock_path)
    status["restart_lock_file_present"] = _status_file_present(restart_lock_path)

    frozen_state, frozen = _status_load(
        frozen_transaction_path, _STATUS_FROZEN_MAX_BYTES, load_frozen
    )
    restart_state, restart = _status_load(
        restart_transaction_path, _STATUS_RESTART_MAX_BYTES, load_restart
    )
    status["frozen_transaction_state"] = frozen_state
    status["restart_transaction_state"] = restart_state

    if frozen is not None:
        hold_ids = getattr(frozen, "activation_hold_ids", None)
        hold_ids = tuple(hold_ids) if isinstance(hold_ids, (tuple, list)) else ()
        policy = getattr(frozen, "original_update_policy", None)
        records = getattr(frozen, "resolution_records", None)
        status.update({
            "frozen_phase": _status_enum_value(
                getattr(frozen, "phase", None), STATUS_FROZEN_PHASES
            ),
            "frozen_lifecycle_stage": _status_enum_value(
                getattr(frozen, "lifecycle_stage", None), STATUS_LIFECYCLE_STAGES
            ),
            "frozen_lifecycle_restart_count": _status_count(
                getattr(frozen, "lifecycle_restart_count", None)
            ),
            "frozen_status_code": _status_code(
                getattr(frozen, "status_code", None), STATUS_FROZEN_CODES
            ),
            "activation_hold_count": _status_count(len(hold_ids)),
            "redlight_hold_present": HELD_RETRY_OWNER_ID in hold_ids,
            "activation_hold_released": _status_bool(
                getattr(frozen, "activation_hold_released", None)
            ),
            "updater_guard_required": _status_bool(
                getattr(frozen, "updater_guard_required", None)
            ),
            "private_overlay_required": _status_bool(
                getattr(frozen, "private_overlay_required", None)
            ),
            "original_update_policy": (
                getattr(policy, "name", None)
                if getattr(policy, "name", None) in STATUS_UPDATE_POLICIES
                else None
            ),
            "resolution_record_count": _status_count(
                len(records) if isinstance(records, (tuple, list)) else None
            ),
        })
    if restart is not None:
        status.update({
            "restart_phase": _status_enum_value(
                getattr(restart, "phase", None), STATUS_RESTART_PHASES
            ),
            "restart_attempt_count": _status_count(
                getattr(restart, "restart_attempt_count", None)
            ),
            "restart_status_code": _status_code(
                getattr(restart, "status_code", None), STATUS_RESTART_CODES
            ),
        })
    if frozen is not None and restart is not None:
        linked = getattr(frozen, "restart_transaction_id", None)
        status["restart_transaction_linked"] = bool(linked) and linked == getattr(
            restart, "transaction_id", None
        )
    return status


def choose_missing_artifact_resolution(prompt: Any, resolution_choice: Any) -> Any:
    """Keep the adapter's existing YouTube skip and all-other cancel policy."""
    if prompt.addon_id == "plugin.video.youtube" and prompt.skip_allowed:
        return resolution_choice.SKIP
    return resolution_choice.CANCEL


def stage_manifest_artifacts(manifest: Any, source_store: Any, durable_store: Any) -> None:
    """Copy exact captured ZIPs into the profile-local frozen artifact store."""
    for node in manifest.addons:
        if node.system or node.artifact is None:
            continue
        artifact = node.artifact
        try:
            zip_bytes = source_store.read_bytes(artifact.sha256)
        except Exception:
            raise _bootstrap_error(
                "STAGE_RETAINED_ARTIFACTS",
                "ArtifactStore.read_bytes",
                "artifact_stage_failed",
            ) from None
        try:
            imported = durable_store.import_zip(
                zip_bytes,
                expected_addon_id=node.addon_id,
                expected_version=node.version,
                source="bm023a-retained-artifact",
            )
        except Exception:
            raise _bootstrap_error(
                "STAGE_RETAINED_ARTIFACTS",
                "ArtifactStore.import_zip",
                "artifact_stage_failed",
            ) from None
        if (
            getattr(imported, "sha256", None) != artifact.sha256
            or getattr(imported, "size", None) != artifact.size
        ):
            raise _bootstrap_error(
                "STAGE_RETAINED_ARTIFACTS",
                "ArtifactStore.import_zip",
                "artifact_stage_failed",
            )


def _require_transaction_identity(
    transaction: Any,
    manifest: Any,
    *,
    stage: str,
    category: str,
    manifest_path: str,
    configuration_manifest_path: str,
    device_profile_id: str,
    expected_overlay_id: str,
) -> None:
    """Bind a durable transaction to the reviewed manifest and adapter constants."""
    try:
        matches = (
            transaction.manifest_path == manifest_path
            and transaction.build_id == manifest.build_id
            and transaction.manifest_fingerprint == manifest.fingerprint()
            and transaction.configuration_manifest_path == configuration_manifest_path
            and transaction.device_profile_id == device_profile_id
            and transaction.private_overlay_id == expected_overlay_id
        )
    except Exception:
        matches = False
    if not matches:
        raise _bootstrap_error(stage, "FrozenInstallStore.inspect", category)


def recover_frozen_install(
    coordinator: Any,
    store: Any,
    policy_backend: Any,
    installer: Any,
    restart_transaction_path: Any,
    *,
    manifest: Any,
    manifest_path: str,
    configuration_manifest_path: str,
    device_profile_id: str,
    expected_overlay_id: str,
    needs_attention_phase: Any,
    update_policy_type: Any,
    af3_addon_id: str = "skin.arctic.fuse.3",
) -> Dict[str, Any]:
    """Abandon only the transaction bound to the reviewed manifest identity, then summarize safely."""
    from uuid import UUID

    if not store.root.is_dir():
        raise _bootstrap_error(
            "CHECK_RECOVERY_PRECONDITIONS", "pathlib.Path", "path_missing_or_unreadable"
        )
    transaction = store.inspect()
    if transaction is None:
        raise _bootstrap_error(
            "CHECK_RECOVERY_PRECONDITIONS", "FrozenInstallStore.inspect", "transaction_missing"
        )
    try:
        UUID(transaction.transaction_id)
    except (AttributeError, TypeError, ValueError):
        raise _bootstrap_error(
            "CHECK_RECOVERY_PRECONDITIONS", "FrozenInstallStore.inspect", "transaction_identity_invalid"
        ) from None
    if transaction.phase != needs_attention_phase:
        raise _bootstrap_error(
            "CHECK_RECOVERY_PRECONDITIONS", "FrozenInstallStore.inspect", "recovery_phase_mismatch"
        )
    _require_transaction_identity(
        transaction,
        manifest,
        stage="CHECK_RECOVERY_PRECONDITIONS",
        category="recovery_identity_mismatch",
        manifest_path=manifest_path,
        configuration_manifest_path=configuration_manifest_path,
        device_profile_id=device_profile_id,
        expected_overlay_id=expected_overlay_id,
    )
    original_policy = transaction.original_update_policy
    if not isinstance(original_policy, update_policy_type):
        raise _bootstrap_error(
            "CHECK_RECOVERY_PRECONDITIONS", "FrozenInstallStore.inspect", "original_policy_missing"
        )
    if transaction.activation_hold_ids and not transaction.activation_hold_released:
        raise _bootstrap_error(
            "CHECK_RECOVERY_PRECONDITIONS", "FrozenInstallStore.inspect", "unsupported_recovery_state"
        )

    # Observe only add-ons named by the validated transaction; abandon must not
    # uninstall or otherwise mutate those add-ons.
    observed_ids = []
    for record in transaction.resolution_records:
        if installer.get_addon_details(record.addon_id) is not None:
            observed_ids.append(record.addon_id)
    restart_present_before = bool(restart_transaction_path.exists())

    # This is the sole recovery call; no transaction files, locks, add-ons,
    # updater settings, or restart records are manually edited here.
    try:
        result = coordinator.abandon(acknowledge_restore_failure=False)
    except Exception:
        raise _bootstrap_error(
            "INVOKE_RECOVERY", "FrozenInstallCoordinator.abandon", "operation_failed"
        ) from None
    outcome = getattr(getattr(result, "outcome", None), "value", getattr(result, "outcome", None))
    if outcome != "complete":
        raise _bootstrap_error(
            "INVOKE_RECOVERY", "FrozenInstallCoordinator.abandon", "operation_failed"
        )

    try:
        transaction_cleared = store.inspect() is None
    except Exception:
        raise _bootstrap_error(
            "INVOKE_RECOVERY", "FrozenInstallStore.inspect", "operation_failed"
        ) from None
    try:
        policy_after = update_policy_type(policy_backend.get_policy())
    except Exception:
        raise _bootstrap_error(
            "INVOKE_RECOVERY", "UpdatePolicyBackend.get_policy", "operation_failed"
        ) from None
    restart_present_after = bool(restart_transaction_path.exists())
    try:
        af3_installed = installer.get_addon_details(af3_addon_id) is not None
        addons_retained = all(
            installer.get_addon_details(addon_id) is not None for addon_id in observed_ids
        )
    except Exception:
        raise _bootstrap_error(
            "INVOKE_RECOVERY", "KodiRuntimeFrozenArtifactBackend.get_addon_details",
            "operation_failed",
        ) from None
    if not (
        transaction_cleared
        and policy_after == original_policy
        and restart_present_after == restart_present_before
        and addons_retained
    ):
        raise _bootstrap_error(
            "INVOKE_RECOVERY", "FrozenInstallCoordinator.abandon", "operation_failed"
        )
    return {
        "ok": True,
        "adapter_mode": "recover",
        "transaction_cleared": transaction_cleared,
        "original_update_policy": int(original_policy),
        "update_policy_after": int(policy_after),
        "updater_policy_restored": policy_after == original_policy,
        "restart_transaction_present": restart_present_after,
        "af3_installed": af3_installed,
        "frozen_addons_retained": addons_retained,
    }


def _safe_held_retry_result(result: Any) -> Dict[str, Any]:
    """Summarize only fixed labels and booleans from a held retry result."""
    allowed_outcomes = {"complete", "failed", "needs_attention", "awaiting_restart"}
    raw_outcome = getattr(result, "outcome", None)
    outcome = getattr(raw_outcome, "value", raw_outcome)
    if not isinstance(outcome, str) or outcome not in allowed_outcomes:
        outcome = "unknown"

    transaction = getattr(result, "transaction", None)
    transaction_summary = None
    if transaction is not None:
        allowed_phases = {
            "preparing", "installing_software", "configuring",
            "awaiting_restart", "resuming", "validating", "needs_attention",
            "complete",
        }
        allowed_lifecycle = {
            "none", "installing_software", "quiescence_awaiting_restart",
            "configuring", "configuration_awaiting_restart", "private_verified",
            "activation_released", "final_activation_awaiting_restart",
        }
        raw_phase = getattr(transaction, "phase", None)
        phase = getattr(raw_phase, "value", raw_phase)
        if not isinstance(phase, str) or phase not in allowed_phases:
            phase = "unknown"
        raw_lifecycle = getattr(transaction, "lifecycle_stage", None)
        lifecycle = getattr(raw_lifecycle, "value", raw_lifecycle)
        if not isinstance(lifecycle, str) or lifecycle not in allowed_lifecycle:
            lifecycle = "unknown"
        hold_ids = getattr(transaction, "activation_hold_ids", ())
        try:
            is_held_owner = tuple(hold_ids) == (HELD_RETRY_OWNER_ID,)
        except TypeError:
            is_held_owner = False
        if is_held_owner:
            safe_hold_ids = [HELD_RETRY_OWNER_ID]
        else:
            safe_hold_ids = []
        restart_count = getattr(transaction, "lifecycle_restart_count", None)
        if (
            not isinstance(restart_count, int)
            or isinstance(restart_count, bool)
            or not 0 <= restart_count <= 3
        ):
            restart_count = None
        hold_released = getattr(transaction, "activation_hold_released", None)
        guard_required = getattr(transaction, "updater_guard_required", None)
        transaction_summary = {
            "phase": phase,
            "lifecycle_stage": lifecycle,
            "lifecycle_restart_count": restart_count,
            "activation_hold_ids": safe_hold_ids,
            "activation_hold_released": (
                hold_released if isinstance(hold_released, bool) else None
            ),
            "updater_guard_required": (
                guard_required if isinstance(guard_required, bool) else None
            ),
        }

    return {
        "ok": outcome == "complete",
        "adapter_mode": "retry",
        "retry_invoked": True,
        "outcome": outcome,
        "transaction": transaction_summary,
    }


def retry_held_frozen_install(
    coordinator: Any,
    store: Any,
    artifact_source_store: Any,
    restart_store: Any,
    *,
    manifest: Any,
    manifest_path: str,
    configuration_manifest_path: str,
    device_profile_id: str,
    expected_overlay_id: str,
    transaction_type: type,
    needs_attention_phase: Any,
    quiescence_awaiting_restart_stage: Any,
    automatic_update_policy: Any,
) -> Dict[str, Any]:
    """Validate the reviewed held snapshot, then call the production retry once."""
    from uuid import UUID

    try:
        if not store.root.is_dir():
            raise _bootstrap_error(
                "CHECK_RETRY_PRECONDITIONS", "pathlib.Path", "path_missing_or_unreadable"
            )
        transaction = store.inspect()
    except AdapterBootstrapError:
        raise
    except Exception:
        raise _bootstrap_error(
            "CHECK_RETRY_PRECONDITIONS", "FrozenInstallStore.inspect", "operation_failed"
        ) from None
    if transaction is None:
        raise _bootstrap_error(
            "CHECK_RETRY_PRECONDITIONS", "FrozenInstallStore.inspect", "transaction_missing"
        )
    if not isinstance(transaction, transaction_type):
        raise _bootstrap_error(
            "CHECK_RETRY_PRECONDITIONS", "FrozenInstallStore.inspect", "retry_snapshot_invalid"
        )
    try:
        UUID(transaction.transaction_id)
    except (AttributeError, TypeError, ValueError):
        raise _bootstrap_error(
            "CHECK_RETRY_PRECONDITIONS", "FrozenInstallStore.inspect", "transaction_identity_invalid"
        ) from None

    if not (
        transaction.phase is needs_attention_phase
        and transaction.status_code == HELD_RETRY_FAILURE_CODE
        and transaction.lifecycle_stage is quiescence_awaiting_restart_stage
        and transaction.lifecycle_restart_count == 1
        and transaction.activation_hold_ids == (HELD_RETRY_OWNER_ID,)
        and transaction.activation_hold_released is False
        and transaction.updater_guard_required is True
        and transaction.original_update_policy is automatic_update_policy
        and bool(transaction.manifest_fingerprint)
        and bool(transaction.install_plan_fingerprint)
        and bool(transaction.resolution_fingerprint)
        and bool(transaction.private_overlay_fingerprint)
    ):
        raise _bootstrap_error(
            "CHECK_RETRY_PRECONDITIONS", "FrozenInstallStore.inspect", "retry_snapshot_invalid"
        )

    _require_transaction_identity(
        transaction,
        manifest,
        stage="CHECK_RETRY_PRECONDITIONS",
        category="retry_identity_mismatch",
        manifest_path=manifest_path,
        configuration_manifest_path=configuration_manifest_path,
        device_profile_id=device_profile_id,
        expected_overlay_id=expected_overlay_id,
    )

    if not Path(configuration_manifest_path).is_file():
        raise _bootstrap_error(
            "CHECK_RETRY_PRECONDITIONS", "pathlib.Path", "path_missing_or_unreadable"
        )

    retry_callable = getattr(coordinator, "retry_held_quiescence", None)
    if not callable(retry_callable):
        raise _bootstrap_error(
            "INVOKE_RETRY",
            "FrozenInstallCoordinator.retry_held_quiescence",
            "retry_api_unavailable",
        )

    try:
        result = retry_callable(
            expected_transaction=transaction,
            artifact_source_store=artifact_source_store,
            restart_store=restart_store,
        )
    except Exception:
        raise _bootstrap_error(
            "INVOKE_RETRY",
            "FrozenInstallCoordinator.retry_held_quiescence",
            "retry_invocation_failed",
        ) from None
    return _safe_held_retry_result(result)


def verify_build_manager_source(
    addons_root: Any,
    addon_root: Any,
    resources_lib: ModuleType,
) -> Path:
    """Prove resources.lib is the concrete package beneath this installed add-on.

    `resources` itself is intentionally not inspected: without
    `resources/__init__.py` it is a namespace package and has no `__file__`.
    Canonical paths are checked after resolution to reject symlink escapes.
    """
    try:
        expected_addons = Path(addons_root).resolve(strict=True)
        expected_addon = Path(addon_root).resolve(strict=True)
    except TypeError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "path_argument_is_none"
        ) from None
    except OSError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "path_missing_or_unreadable"
        ) from None

    if (
        not expected_addons.is_dir()
        or not expected_addon.is_dir()
        or expected_addon.name != ADDON_ID
        or expected_addon.parent != expected_addons
    ):
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "addon_root_mismatch"
        )

    module_file = getattr(resources_lib, "__file__", None)
    if not isinstance(module_file, (str, bytes)) or not module_file:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "path_argument_is_none"
        )
    try:
        concrete_file = Path(module_file).resolve(strict=True)
        expected_package = (expected_addon / "resources" / "lib").resolve(strict=True)
    except TypeError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "path_argument_is_none"
        ) from None
    except OSError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "path_missing_or_unreadable"
        ) from None

    try:
        expected_package.relative_to(expected_addon)
        concrete_file.relative_to(expected_package)
    except ValueError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_mismatch"
        ) from None
    if (
        not expected_package.is_dir()
        or not concrete_file.is_file()
        or concrete_file != expected_package / "__init__.py"
    ):
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_mismatch"
        )
    package_locations = getattr(resources_lib, "__path__", None)
    try:
        concrete_locations = [Path(location).resolve(strict=True) for location in package_locations]
    except (TypeError, OSError):
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_mismatch"
        ) from None
    if concrete_locations != [expected_package]:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_mismatch"
        )
    return concrete_file


def reject_cached_production_modules(module_names: Any, module_cache: Any = None) -> None:
    """Fail closed when a production child module predates this invocation.

    Kodi can keep imported modules in ``sys.modules`` after their source files
    change on disk.  The package path check alone cannot establish which code
    object a cached child module contains, so production modules needed by the
    adapter must be imported fresh for this invocation.
    """
    cache = sys.modules if module_cache is None else module_cache
    if any(name in cache for name in module_names):
        raise _bootstrap_error(
            "IMPORT_PRODUCTION_MODULES",
            "importlib.import_module",
            "module_cache_preloaded",
        )


def verify_frozen_install_source(addon_root: Any, expected_sha256: str) -> None:
    """Require the installed coordinator source used to build this adapter."""
    if not _is_sha256_digest(expected_sha256):
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "invalid_input"
        )
    try:
        expected_addon = Path(addon_root).resolve(strict=True)
        expected_package = (expected_addon / "resources" / "lib").resolve(strict=True)
        source_file = (expected_package / "frozen_install.py").resolve(strict=True)
        source_file.relative_to(expected_package)
    except (FileNotFoundError, NotADirectoryError):
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_missing"
        ) from None
    except ValueError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_mismatch"
        ) from None
    except TypeError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "path_argument_is_none"
        ) from None
    except OSError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_unreadable"
        ) from None
    try:
        digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
    except (FileNotFoundError, NotADirectoryError):
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_missing"
        ) from None
    except OSError:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path", "module_source_unreadable"
        ) from None
    if digest != expected_sha256:
        raise _bootstrap_error(
            "VERIFY_BUILD_MANAGER_SOURCE",
            "pathlib.Path",
            "module_source_mismatch",
            expected_sha256=expected_sha256,
            observed_sha256=digest,
        )


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_file_durably(path: Path, data: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_file_atomically(target: Path, data: bytes) -> None:
    mode = stat.S_IMODE(target.stat().st_mode)
    fd, temporary = tempfile.mkstemp(
        prefix=".frozen_install.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def repair_frozen_install_source(
    addon_root: Any,
    expected_sha256: str,
    backup_dir: Any,
    bundled_path: Any = None,
) -> Dict[str, Any]:
    """Replace only the installed frozen_install.py with the pinned bundled copy.

    Does nothing when the installed file already matches the pin.  Otherwise the
    bundled copy must match the pin, the target must be exactly the regular file
    ``<addon_root>/resources/lib/frozen_install.py`` with no symlink or
    traversal, and the original is backed up under ``backup_dir`` before an
    atomic single-file replacement that is re-verified.  Returns sanitized
    hashes only.
    """
    stage, callable_name = "VERIFY_BUILD_MANAGER_SOURCE", "pathlib.Path"
    if not _is_sha256_digest(expected_sha256):
        raise _bootstrap_error(stage, callable_name, "invalid_input")
    try:
        supplied_addon = Path(addon_root)
        resolved_addon = supplied_addon.resolve(strict=True)
    except TypeError:
        raise _bootstrap_error(stage, callable_name, "path_argument_is_none") from None
    except OSError:
        raise _bootstrap_error(stage, callable_name, "path_missing_or_unreadable") from None
    target = resolved_addon / "resources" / "lib" / "frozen_install.py"
    try:
        before = _sha256_of_file(target)
    except (FileNotFoundError, NotADirectoryError):
        raise _bootstrap_error(stage, callable_name, "module_source_missing") from None
    except OSError:
        raise _bootstrap_error(stage, callable_name, "module_source_unreadable") from None
    if before == expected_sha256:
        return {"sha256_before": before, "sha256_after": before, "replaced": False}

    if bundled_path is None:
        bundled_path = Path(__file__).resolve().parent / BUNDLED_FROZEN_INSTALL_NAME
    try:
        bundled = Path(bundled_path)
        if bundled.is_symlink() or not bundled.is_file():
            raise OSError
        bundled_bytes = bundled.read_bytes()
    except (TypeError, OSError):
        raise _bootstrap_error(stage, callable_name, "bundled_source_mismatch") from None
    if hashlib.sha256(bundled_bytes).hexdigest() != expected_sha256:
        raise _bootstrap_error(stage, callable_name, "bundled_source_mismatch")

    try:
        target_valid = (
            supplied_addon.is_absolute()
            and ".." not in supplied_addon.parts
            and supplied_addon == resolved_addon
            and resolved_addon.name == ADDON_ID
            and not target.is_symlink()
            and target.is_file()
            and target.resolve(strict=True) == target
        )
    except OSError:
        target_valid = False
    if not target_valid:
        raise _bootstrap_error(stage, callable_name, "source_target_invalid")

    try:
        original_bytes = target.read_bytes()
        if hashlib.sha256(original_bytes).hexdigest() != before:
            raise OSError
        backup_root = Path(backup_dir)
        if backup_root.is_symlink():
            raise OSError
        backup_root.mkdir(parents=True, exist_ok=True)
        _write_file_durably(backup_root / f"frozen_install.{before[:16]}.py.bak", original_bytes)
    except (TypeError, OSError):
        raise _bootstrap_error(stage, callable_name, "source_replace_failed") from None

    try:
        _replace_file_atomically(target, bundled_bytes)
    except OSError:
        raise _bootstrap_error(stage, callable_name, "source_replace_failed") from None

    try:
        after = _sha256_of_file(target)
    except OSError:
        after = None
    if after != expected_sha256:
        try:
            _replace_file_atomically(target, original_bytes)
        except OSError:
            pass
        raise _bootstrap_error(stage, callable_name, "source_reverify_failed")
    return {"sha256_before": before, "sha256_after": after, "replaced": True}


def inspect_retained_inputs(manifest_path: Any, artifact_root: Any) -> Dict[str, Any]:
    """Report only booleans and a count about the retained manifest and artifacts."""
    manifest_present = manifest_readable = False
    try:
        manifest = Path(manifest_path)
        manifest_present = manifest.is_file()
        if manifest_present:
            with open(manifest, "rb") as handle:
                handle.read(1)
            manifest_readable = True
    except (TypeError, ValueError, OSError):
        pass

    store_present = store_readable = False
    entry_count = 0
    try:
        artifacts_dir = Path(artifact_root) / "artifacts"
        store_present = artifacts_dir.is_dir()
        if store_present:
            with os.scandir(artifacts_dir) as entries:
                entry_count = sum(1 for _ in entries)
            store_readable = True
    except (TypeError, ValueError, OSError):
        entry_count = 0
    return {
        "manifest_present": manifest_present,
        "manifest_readable": manifest_readable,
        "artifact_store_present": store_present,
        "artifact_store_readable": store_readable,
        "artifact_entry_count": entry_count,
    }


def require_retained_inputs(
    record: Dict[str, Any], *, require_artifacts: bool = True
) -> None:
    """Fail with one distinct sanitized category before the manifest is read."""
    if not record["manifest_present"]:
        category = "retained_manifest_missing"
    elif not record["manifest_readable"]:
        category = "retained_manifest_unreadable"
    elif require_artifacts and (
        not record["artifact_store_present"] or record["artifact_entry_count"] < 1
    ):
        category = "retained_artifacts_missing"
    else:
        return
    raise _bootstrap_error("LOAD_FROZEN_MANIFEST", "pathlib.Path", category)


def verify_production_module_sources(addon_root: Any, modules: Dict[str, ModuleType]) -> None:
    """Bind imported production modules to exact files under this add-on."""
    try:
        expected_addon = Path(addon_root).resolve(strict=True)
        expected_package = (expected_addon / "resources" / "lib").resolve(strict=True)
    except TypeError:
        raise _bootstrap_error(
            "IMPORT_PRODUCTION_MODULES", "pathlib.Path", "path_argument_is_none"
        ) from None
    except OSError:
        raise _bootstrap_error(
            "IMPORT_PRODUCTION_MODULES", "pathlib.Path", "module_source_missing"
        ) from None

    for module_name, module in modules.items():
        if not module_name.startswith("resources.lib."):
            raise _bootstrap_error(
                "IMPORT_PRODUCTION_MODULES",
                "importlib.import_module",
                "module_source_mismatch",
            )
        relative_name = module_name[len("resources.lib."):]
        expected_file = expected_package.joinpath(*relative_name.split(".")).with_suffix(".py")
        module_file = getattr(module, "__file__", None)
        module_spec = getattr(module, "__spec__", None)
        module_origin = getattr(module_spec, "origin", None)
        if not isinstance(module_file, (str, bytes)) or not module_file:
            raise _bootstrap_error(
                "IMPORT_PRODUCTION_MODULES",
                "pathlib.Path",
                "module_source_missing",
            )
        if not isinstance(module_origin, (str, bytes)) or not module_origin:
            raise _bootstrap_error(
                "IMPORT_PRODUCTION_MODULES",
                "pathlib.Path",
                "module_source_missing",
            )
        try:
            expected = expected_file.resolve(strict=True)
            concrete_file = Path(module_file).resolve(strict=True)
            concrete_origin = Path(module_origin).resolve(strict=True)
        except (TypeError, OSError):
            raise _bootstrap_error(
                "IMPORT_PRODUCTION_MODULES",
                "pathlib.Path",
                "module_source_missing",
            ) from None
        try:
            expected.relative_to(expected_package)
        except ValueError:
            raise _bootstrap_error(
                "IMPORT_PRODUCTION_MODULES",
                "importlib.import_module",
                "module_source_mismatch",
            ) from None
        if not expected.is_file() or concrete_file != expected or concrete_origin != expected:
            raise _bootstrap_error(
                "IMPORT_PRODUCTION_MODULES",
                "importlib.import_module",
                "module_source_mismatch",
            )


def safe_failure_payload(
    stage: str,
    failing_callable: str,
    error: BaseException,
    category: str | None = None,
) -> Dict[str, Any]:
    """Return fixed, allowlisted failure metadata and never exception text."""
    if isinstance(error, AdapterBootstrapError):
        stage = error.stage
        failing_callable = error.failing_callable
        category = error.failure_category
    elif category is None:
        if isinstance(error, TypeError):
            category = "path_argument_is_none" if stage == "VERIFY_BUILD_MANAGER_SOURCE" else "invalid_input"
        elif isinstance(error, (ImportError, ModuleNotFoundError)):
            category = "module_import_failed"
        elif isinstance(error, (FileNotFoundError, PermissionError, OSError)):
            category = "path_missing_or_unreadable"
        elif isinstance(error, ValueError):
            category = "invalid_input"
        else:
            category = "operation_failed"

    safe_stage = stage if stage in ADAPTER_STAGES else "LOCATE_BUILD_MANAGER"
    safe_callable = (
        failing_callable if failing_callable in ADAPTER_CALLABLES else "result_serializer"
    )
    safe_category = category if category in FAILURE_CATEGORIES else "operation_failed"
    error_name = type(error).__name__
    if error_name not in SAFE_ERROR_TYPES:
        error_name = "Exception"
    payload = {
        "ok": False,
        "error_type": error_name,
        "adapter_stage": safe_stage,
        "failing_callable": safe_callable,
        "failure_category": safe_category,
    }
    if (
        isinstance(error, AdapterBootstrapError)
        and safe_stage == "VERIFY_BUILD_MANAGER_SOURCE"
        and safe_category == "module_source_mismatch"
    ):
        expected_sha256 = error.expected_sha256
        observed_sha256 = error.observed_sha256
        if (
            _is_sha256_digest(expected_sha256)
            and _is_sha256_digest(observed_sha256)
            and expected_sha256 != observed_sha256
        ):
            payload["expected_sha256"] = expected_sha256
            payload["observed_sha256"] = observed_sha256
    return payload
