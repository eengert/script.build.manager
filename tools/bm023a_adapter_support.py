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


ADAPTER_VERSION = "0.0.16"
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
    "AF3_FIXTURE",
    "PLATFORM_CHECK",
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
    "read_platform_check",
    "run_af3_fixture",
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
    "resuming", "validating", "needs_attention", "complete", "publication_pending",
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
        if token in ("install", "recover", "retry", "status", "platform_check", "af3_fixture", "af3_fixture_verify"):
            return token
        if token == "?mode=install":
            return "install"
        if token == "?mode=recover":
            return "recover"
        if token == "?mode=retry":
            return "retry"
        if token == "?mode=status":
            return "status"
        if token in ("?mode=af3_fixture", "?mode=af3_fixture_verify"):
            return token.removeprefix("?mode=")
        if token == "?mode=platform_check":
            return "platform_check"
    raise _bootstrap_error(
        "LOCATE_BUILD_MANAGER", "result_serializer", "mode_invalid"
    )


def identify_adapter_result(payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Tag every result with the selected mode or the safe preselection value."""
    safe_mode = (
        mode if mode in ("install", "recover", "retry", "status", "platform_check", "af3_fixture", "af3_fixture_verify") else "unselected"
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


def project_recovery_identity(value):
    """Closed public nine-field request; never expose paths or arbitrary text."""
    import re
    from uuid import UUID

    keys = {"schema", "transaction_id", "build_id", "entry_id", "device_profile_id",
            "manifest_fingerprint", "phase", "status_code", "original_update_policy"}
    try:
        valid = (isinstance(value, dict) and set(value) == keys
            and value["schema"] == "bm-library-recovery/1"
            and isinstance(value["transaction_id"], str)
            and str(UUID(value["transaction_id"])) == value["transaction_id"]
            and all(isinstance(value[key], str)
                    and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value[key])
                    for key in ("build_id", "device_profile_id"))
            and all(_is_sha256_digest(value[key]) for key in ("entry_id", "manifest_fingerprint"))
            and value["phase"] == "needs_attention"
            and value["status_code"] == "RESOLUTION_PERSISTENCE_FAILED"
            and type(value["original_update_policy"]) is int
            and value["original_update_policy"] in (0, 1, 2))
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("invalid recovery identity")
    return {key: value[key] for key in sorted(keys)}


def read_native_recovery_identity(frozen_root, restart_transaction_path):
    """Point-in-time runtime authority, without locks, writes or recovery calls.

    Omit identity on any unavailable proof. Recovery must separately revalidate
    these pins under its own lock; this observation grants no mutation authority.
    """
    def restart_absent():
        parent = _platform_directory(Path(restart_transaction_path).parent)
        try:
            try:
                os.stat(Path(restart_transaction_path).name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return True
            return False
        finally:
            os.close(parent)

    try:
        from resources.lib.build_library import default_build_library, LibraryInstallTarget
        from resources.lib.frozen_install import FrozenInstallStore, FrozenInstallTransaction, FrozenInstallPhase
        from resources.lib.update_guard import AddonUpdatePolicy

        path = Path(frozen_root) / "frozen_install_transaction.json"
        raw = _platform_read(path, _STATUS_FROZEN_MAX_BYTES)
        transaction = FrozenInstallStore.read_snapshot(root=frozen_root)
        if (not isinstance(transaction, FrozenInstallTransaction)
                or transaction != FrozenInstallTransaction.from_dict(json.loads(raw))
                or transaction.phase is not FrozenInstallPhase.NEEDS_ATTENTION
                or transaction.status_code != "RESOLUTION_PERSISTENCE_FAILED"
                or not isinstance(transaction.original_update_policy, AddonUpdatePolicy)
                or transaction.private_overlay_required or transaction.private_overlay_id
                or transaction.private_overlay_fingerprint
                or transaction.activation_hold_ids and not transaction.activation_hold_released
                or transaction.restart_transaction_id):
            return None
        # A directory, symlink, unreadable owner or missing parent also refuses.
        if not restart_absent():
            return None
        library = default_build_library()
        if Path(frozen_root) != Path(library.root).parent or transaction.library_target is None:
            return None
        target = LibraryInstallTarget.from_plan_target(library.plan_target(
            transaction.library_target.source.entry_id, transaction.device_profile_id))
        if transaction.library_target != target or library.pending_publication() is not None:
            return None
        _, manifest, _ = target.load()
        _require_transaction_identity(transaction, manifest,
            stage="READ_STATUS", category="recovery_identity_mismatch", manifest_path="",
            configuration_manifest_path="", device_profile_id=target.device_profile_id,
            expected_overlay_id="")
        identity = project_recovery_identity({
            "schema": "bm-library-recovery/1", "transaction_id": transaction.transaction_id,
            "build_id": manifest.build_id, "entry_id": target.source.entry_id,
            "device_profile_id": target.device_profile_id,
            "manifest_fingerprint": manifest.fingerprint(), "phase": transaction.phase.value,
            "status_code": transaction.status_code,
            "original_update_policy": int(transaction.original_update_policy)})
        if (_platform_read(path, _STATUS_FROZEN_MAX_BYTES) != raw
                or target.load()[1].fingerprint() != identity["manifest_fingerprint"]
                or library.pending_publication() is not None or not restart_absent()):
            return None
        return identity
    except Exception:
        return None


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


def recover_library_frozen_install(request, *, store, policy_backend, installer,
                                   restart_transaction_path):
    """Explicit native-library recovery; no caller-selected library or source path."""
    from uuid import UUID
    from resources.lib.build_library import default_build_library, LibraryInstallTarget
    from resources.lib.frozen_install import FrozenInstallCoordinator, FrozenInstallPhase
    from resources.lib.update_guard import AddonUpdatePolicy

    stage = "CHECK_RECOVERY_PRECONDITIONS"
    def refuse():
        return _bootstrap_error(stage, "FrozenInstallStore.inspect", "recovery_identity_mismatch")

    keys = {"schema", "transaction_id", "build_id", "entry_id", "device_profile_id",
            "manifest_fingerprint", "phase", "status_code", "original_update_policy"}
    try:
        if (not isinstance(request, dict) or set(request) != keys
                or request["schema"] != "bm-library-recovery/1"
                or str(UUID(request["transaction_id"])) != request["transaction_id"]
                or not _is_sha256_digest(request["entry_id"])
                or not _is_sha256_digest(request["manifest_fingerprint"])
                or request["phase"] != "needs_attention"
                or request["status_code"] != "RESOLUTION_PERSISTENCE_FAILED"
                or type(request["original_update_policy"]) is not int):
            raise ValueError()
        expected_policy = AddonUpdatePolicy(request["original_update_policy"])
        library = default_build_library()
        if store.root != Path(library.root).parent:
            raise ValueError()
        target = LibraryInstallTarget.from_plan_target(
            library.plan_target(request["entry_id"], request["device_profile_id"]))
        _, manifest, _ = target.load()
        if manifest.build_id != request["build_id"] or manifest.fingerprint() != request["manifest_fingerprint"]:
            raise ValueError()
    except Exception:
        raise refuse() from None

    with store.locked_recovery_access() as access:
        transaction = access.inspect()
        if (transaction is None or transaction.transaction_id != request["transaction_id"]
                or transaction.library_target != target
                or transaction.phase is not FrozenInstallPhase.NEEDS_ATTENTION
                or transaction.status_code != request["status_code"]
                or transaction.original_update_policy is not expected_policy
                or transaction.private_overlay_required or transaction.private_overlay_id
                or transaction.private_overlay_fingerprint
                or transaction.activation_hold_ids and not transaction.activation_hold_released
                or restart_transaction_path.exists()):
            raise refuse()
        # Existing identity validation also binds empty standalone paths, build,
        # profile and the authoritative library manifest before any mutation.
        before = (library.current_applied_association(), library.publication_journal(),
                  library.current_selection())
        if library.pending_publication() is not None:
            raise refuse()
        coordinator = FrozenInstallCoordinator(store=access, artifact_store=None,
            policy_backend=policy_backend, installer=installer)
        result = recover_frozen_install(coordinator, access, policy_backend, installer,
            restart_transaction_path, manifest=manifest, manifest_path="",
            configuration_manifest_path="", device_profile_id=request["device_profile_id"],
            expected_overlay_id="", needs_attention_phase=FrozenInstallPhase.NEEDS_ATTENTION,
            update_policy_type=AddonUpdatePolicy)
        if before != (library.current_applied_association(), library.publication_journal(),
                      library.current_selection()):
            raise _bootstrap_error("INVOKE_RECOVERY", "FrozenInstallCoordinator.abandon", "operation_failed")
        return result


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


# This diagnostic transports the reviewed verifier; it grants no Apply authority.
PLATFORM_IDS = ('xbmc.core', 'xbmc.gui', 'kodi.resource', 'xbmc.python')
PLATFORM_BUILD = '20251031-a3a448d26b'
PLATFORM_FAILURES = frozenset({
    'source_binding_invalid', 'source_changed', 'runtime_or_build_unverified',
    'manifest_binding_missing', 'manifest_unavailable', 'manifest_changed',
    'manifest_invalid', 'artifact_evidence_unavailable', 'platform_requirements_refused',
    'incoming_requirement_unavailable', 'provider_unverified', 'metadata_invalid',
    'provider_changed', 'fixed_provider_closure_missing', 'diagnostic_unavailable',
})
_PLATFORM_ADAPTER_FILES = frozenset({'default.py', 'adapter_support.py',
    'addon.xml', BUNDLED_FROZEN_INSTALL_NAME})
_PLATFORM_PRODUCT_REQUIRED = frozenset({'addon.xml', 'default.py', 'service.py',
    'resources/lib/frozen.py', 'resources/lib/frozen_install.py', 'resources/lib/artifacts.py'})


def _platform_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def _platform_directory(path):
    """Read-only canonical descriptor chain; no resolve/follow fallback."""
    path = Path(path)
    text = str(path)
    aliases = text.removeprefix('/System/Volumes/Data') if text.startswith('/System/Volumes/Data/') else text
    if (not path.is_absolute() or os.path.normpath(text) != text or
            any(aliases == prefix or aliases.startswith(prefix + '/') for prefix in (
                '/Applications/Kodi.app', '/Users/eengert/Library/Application Support/Kodi'))):
        raise ValueError('unsafe diagnostic path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        return fd
    except BaseException:
        os.close(fd)
        raise


def _platform_read(path, limit):
    path = Path(path)
    parent = _platform_directory(path.parent)
    fd = None
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        def identity(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        original = os.fstat(fd)
        if not stat.S_ISREG(original.st_mode) or original.st_size > limit:
            raise ValueError('unsafe diagnostic input')
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk: break
            data.extend(chunk)
        if (len(data) > limit or identity(os.fstat(fd)) != identity(original) or
                identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != identity(original)):
            raise ValueError('diagnostic input changed')
        return bytes(data)
    finally:
        if fd is not None: os.close(fd)
        os.close(parent)


def platform_source_binding(product, adapter, candidate_commit, manifest_sha256=''):
    """Canonical generated binding; the host independently checks these maps."""
    return json.dumps({'schema': 1, 'candidate_commit': candidate_commit,
        'product': product, 'adapter': adapter, 'manifest_sha256': manifest_sha256},
        sort_keys=True, separators=(',', ':'))


def _platform_sources(raw, addon_root, driver_root):
    if not isinstance(raw, str) or len(raw) > 300000:
        raise ValueError('source binding invalid')
    binding = json.loads(raw)
    if (not isinstance(binding, dict) or set(binding) != {
            'schema', 'candidate_commit', 'product', 'adapter', 'manifest_sha256'} or
            type(binding['schema']) is not int or binding['schema'] != 1):
        raise ValueError('source binding invalid')
    commit = binding['candidate_commit']
    if (not isinstance(commit, str) or len(commit) not in (40, 64) or
            any(c not in '0123456789abcdef' for c in commit) or
            (binding['manifest_sha256'] != '' and not _is_sha256_digest(binding['manifest_sha256']))):
        raise ValueError('source identity unavailable')
    total = 0
    for group, root in (('product', Path(addon_root)), ('adapter', Path(driver_root))):
        entries = binding[group]
        if not isinstance(entries, dict) or not 1 <= len(entries) <= 2000:
            raise ValueError('source binding invalid')
        if group == 'adapter' and set(entries) != _PLATFORM_ADAPTER_FILES:
            raise ValueError('adapter binding invalid')
        if group == 'product' and not _PLATFORM_PRODUCT_REQUIRED <= set(entries):
            raise ValueError('product binding incomplete')
        for name, expected in entries.items():
            relative = Path(name)
            if (not isinstance(name, str) or relative.is_absolute() or
                    any(p in ('..', '.') for p in relative.parts) or str(relative) != name or
                    (group == 'product' and name not in ('addon.xml', 'default.py', 'service.py')
                     and not name.startswith('resources/')) or not _is_sha256_digest(expected)):
                raise ValueError('source path invalid')
            data = _platform_read(root / relative, 64 * 1024 * 1024)
            total += len(data)
            if total > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('source changed')
    return binding, {'candidate_commit': commit, 'product_sha256': _platform_digest(binding['product']),
        'adapter_sha256': _platform_digest(binding['adapter']),
        'binding_sha256': hashlib.sha256(raw.encode('ascii')).hexdigest()}


class _PlatformArtifacts:
    """Read-only duck type for strict manifest validation; no mkdir/import/find API."""
    def __init__(self, root, metadata_type):
        self.root = Path(root) / 'artifacts'
        self.metadata_type = metadata_type
        fd = _platform_directory(self.root)
        os.close(fd)

    def _read(self, digest, suffix, limit):
        if not _is_sha256_digest(digest): raise ValueError('invalid digest')
        return _platform_read(self.root / (digest + suffix), limit)

    def get_metadata(self, digest):
        return self.metadata_type.from_dict(json.loads(self._read(digest, '.json', 128 * 1024)))

    def read_bytes(self, digest):
        data = self._read(digest, '.zip', 64 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != digest: raise ValueError('artifact changed')
        return data


class _PlatformBackend:
    """Only inspection capabilities cross into complete platform verification."""
    def __init__(self, backend): self.backend = backend
    def read_verified_builtin_metadata(self, edge):
        if edge.addon_id not in PLATFORM_IDS: return None
        return self.backend.read_verified_builtin_metadata(edge)
    def verify_builtin_requirement(self, edge):
        return self.read_verified_builtin_metadata(edge) is not None
    def get_addon_details(self, aid): return self.backend.get_addon_details(aid)
    def read_installed_metadata(self, aid): return self.backend.read_installed_metadata(aid)


def read_platform_check(addon_root, driver_root, raw_binding, manifest_path, artifact_root):
    """Fixed provider reads and optional strict public-plan proof. Never Apply."""
    import importlib
    import xml.etree.ElementTree as ET
    diagnostic = {'schema': 1, 'source': None,
        'build': {'status': 'unverified', 'major': None, 'minor': None, 'revision': None},
        'manifest_sha256': None, 'manifest_fingerprint': None,
        'graph': {'status': 'unavailable', 'failure_category': 'diagnostic_unavailable'},
        'providers': {aid: {'status': 'unavailable', 'version': None, 'abi': None,
            'descriptor_sha256': None, 'trusted_origin': False, 'closure_status': 'unverified',
            'failure_category': 'incoming_requirement_unavailable'} for aid in PLATFORM_IDS},
        'overall': 'unverified', 'qualification': 'not_qualified'}
    backend = None
    try:
        try:
            binding, diagnostic['source'] = _platform_sources(raw_binding, addon_root, driver_root)
        except Exception:
            diagnostic['graph']['failure_category'] = 'source_binding_invalid'
            return {'ok': False, 'platform_check': diagnostic}
        fi = importlib.import_module('resources.lib.frozen_install')
        fr = importlib.import_module('resources.lib.frozen')
        artifacts = importlib.import_module('resources.lib.artifacts')
        verify_production_module_sources(addon_root, {
            'resources.lib.frozen_install': fi, 'resources.lib.frozen': fr,
            'resources.lib.artifacts': artifacts})
        backend = fi.KodiRuntimeFrozenArtifactBackend()
        try:
            # Reuse the reviewed current-process / pinned-bundle authority,
            # independently of whether any provider can be constructed.
            with backend._passive_build_binding(backend._inventory()) as fresh:
                if fresh() is not True: raise ValueError('runtime changed')
            diagnostic['build'] = {'status': 'verified', 'major': 21, 'minor': 3, 'revision': PLATFORM_BUILD}
        except Exception:
            diagnostic['graph']['failure_category'] = 'runtime_or_build_unverified'
            return {'ok': False, 'platform_check': diagnostic}
        plan = None
        manifest_bytes = None
        if not binding['manifest_sha256']:
            diagnostic['graph']['failure_category'] = 'manifest_binding_missing'
        else:
            diagnostic['manifest_sha256'] = binding['manifest_sha256']
            try:
                manifest_bytes = _platform_read(manifest_path, 1024 * 1024)
            except Exception:
                diagnostic['graph']['failure_category'] = 'manifest_unavailable'
            else:
                if hashlib.sha256(manifest_bytes).hexdigest() != binding['manifest_sha256']:
                    diagnostic['graph']['failure_category'] = 'manifest_changed'
                else:
                    try:
                        manifest = fr.FrozenBuildManifest.from_json(manifest_bytes.decode('utf-8'))
                        if (len(manifest.addons) > 500 or
                                sum(len(n.dependency_edges) for n in manifest.addons) > 2000):
                            raise ValueError('diagnostic graph too large')
                        store = _PlatformArtifacts(artifact_root, artifacts.ArtifactMetadata)
                    except Exception:
                        diagnostic['graph']['failure_category'] = 'manifest_invalid'
                    else:
                        try:
                            plan = fi.validate_frozen_manifest(manifest, store)
                            if len(plan.nodes) > 500 or sum(len(n.dependency_edges) for n in plan.nodes.values()) > 2000:
                                raise ValueError('diagnostic graph too large')
                            diagnostic['manifest_fingerprint'] = manifest.fingerprint()
                        except Exception:
                            plan = None
                            diagnostic['graph']['failure_category'] = 'artifact_evidence_unavailable'
        observations = {}
        for aid in PLATFORM_IDS:
            incoming = [] if plan is None else [edge for node in plan.nodes.values()
                for edge in node.dependency_edges if edge.addon_id == aid and not edge.optional]
            # Empty means a metadata observation only, never a fabricated minimum.
            requirements = incoming or [fr.DependencyEdge(aid)]
            row = diagnostic['providers'][aid]
            try:
                for edge in requirements:
                    metadata = backend.read_verified_builtin_metadata(edge)
                    if metadata is None:
                        row['status'] = 'refused' if incoming else 'unavailable'
                        row['failure_category'] = 'provider_unverified' if incoming else 'incoming_requirement_unavailable'
                        break
                    if not isinstance(metadata, fr.InstalledMetadata) or metadata.origin is not fr.InstalledOrigin.APPLICATION:
                        raise ValueError('metadata authority missing')
                    root = ET.fromstring(metadata.xml_bytes)
                    floors = root.findall('backwards-compatibility')
                    version = root.get('version', '')
                    abi = floors[0].get('abi', '') if len(floors) == 1 else ''
                    if (root.tag != 'addon' or root.get('id') != aid or
                            not fr._builtin_version_satisfies(version, abi) or not abi):
                        raise ValueError('metadata interval invalid')
                    fi._builtin_metadata_edges(metadata, aid)
                    identity = (version, abi, hashlib.sha256(metadata.xml_bytes).hexdigest())
                    if aid in observations and observations[aid] != identity:
                        raise ValueError('provider changed')
                    observations[aid] = identity
                else:
                    version, abi, digest = observations[aid]
                    row.update(status='verified', version=version, abi=abi, descriptor_sha256=digest,
                        trusted_origin=True, failure_category=None)
            except Exception:
                row.update(status='refused', failure_category='metadata_invalid')
        if plan is not None:
            try:
                verified = fi.verify_platform_requirements(plan, _PlatformBackend(backend),
                    planned_versions=fi._planned_versions(plan, ()))
                identities = {entry[0]: tuple(entry[1:4]) for entry in verified.builtin_identity}
                if (not all(row["status"] == "verified" for row in diagnostic["providers"].values()) or
                        not set(PLATFORM_IDS) <= set(identities) or
                        any(identities[aid] != observations.get(aid) for aid in PLATFORM_IDS)):
                    raise ValueError('complete provider closure absent or changed')
                diagnostic['graph'] = {'status': 'verified', 'failure_category': None}
                for row in diagnostic['providers'].values(): row['closure_status'] = 'verified'
            except Exception:
                diagnostic['graph'] = {'status': 'refused', 'failure_category': 'platform_requirements_refused'}
        try:
            _platform_sources(raw_binding, addon_root, driver_root)
            if manifest_bytes is not None and _platform_read(manifest_path, 1024 * 1024) != manifest_bytes:
                raise ValueError('manifest changed')
        except Exception:
            diagnostic['graph'] = {'status': 'refused', 'failure_category': 'source_changed'}
            for row in diagnostic['providers'].values(): row['closure_status'] = 'unverified'
        complete = (diagnostic['graph']['status'] == 'verified' and
            all(row['status'] == 'verified' for row in diagnostic['providers'].values()))
        diagnostic['overall'] = 'requirements_verified' if complete else 'unverified'
        return {'ok': complete, 'platform_check': diagnostic}
    except Exception:
        diagnostic['graph'] = {'status': 'unavailable', 'failure_category': 'diagnostic_unavailable'}
        return {'ok': False, 'platform_check': diagnostic}
    finally:
        if backend is not None: backend.close()


def write_platform_result(path, payload):
    """Only persistent diagnostic output: replace the fixed result, no mkdir."""
    import secrets
    path = Path(path)
    if path.name != 'bm023a_live_result.json': raise ValueError('invalid result destination')
    data = json.dumps(payload, sort_keys=True).encode('ascii')
    if len(data) > 65536: raise ValueError('diagnostic result too large')
    parent = _platform_directory(path.parent)
    temporary = '.platform-result-' + secrets.token_hex(16)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        fresh = _platform_directory(path.parent)
        try:
            if (os.fstat(parent).st_dev, os.fstat(parent).st_ino) != (os.fstat(fresh).st_dev, os.fstat(fresh).st_ino):
                raise ValueError('result directory changed')
            os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally: os.close(fresh)
    finally:
        try: os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError: pass
        os.close(parent)


def project_platform_check(value):
    """Strict bounded public record; malformed or contradictory success refuses."""
    import re
    def keys(record, expected):
        if not isinstance(record, dict) or set(record) != set(expected): raise ValueError('diagnostic keys')
    def digest(value, nullable=False):
        if nullable and value is None: return
        if not _is_sha256_digest(value): raise ValueError('diagnostic digest')
    def version(value):
        if (not isinstance(value, str) or len(value) > 100 or
                not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', value) or
                any(int(p) > 2147483647 for p in value.split('.'))): raise ValueError('diagnostic version')
    keys(value, ('schema','source','build','manifest_sha256','manifest_fingerprint','graph','providers','overall','qualification'))
    if type(value['schema']) is not int or value['schema'] != 1 or value['qualification'] != 'not_qualified':
        raise ValueError('diagnostic schema')
    if value['source'] is not None:
        keys(value['source'], ('candidate_commit','product_sha256','adapter_sha256','binding_sha256'))
        commit = value['source']['candidate_commit']
        if not isinstance(commit, str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit):
            raise ValueError('diagnostic commit')
        for key in ('product_sha256','adapter_sha256','binding_sha256'): digest(value['source'][key])
    build = value['build']
    keys(build, ('status','major','minor','revision'))
    if build['status'] == 'verified':
        if type(build['major']) is not int or type(build['minor']) is not int or (
                build['major'],build['minor'],build['revision']) != (21,3,PLATFORM_BUILD): raise ValueError('diagnostic build')
    elif build != {'status':'unverified','major':None,'minor':None,'revision':None}:
        raise ValueError('diagnostic build')
    digest(value['manifest_sha256'], True); digest(value['manifest_fingerprint'], True)
    graph = value['graph'];keys(graph, ('status','failure_category'))
    if graph['status'] not in ('verified','refused','unavailable'): raise ValueError('diagnostic graph')
    def failure(category):
        if category is not None and (not isinstance(category, str) or category not in PLATFORM_FAILURES): raise ValueError('diagnostic category')
    failure(graph['failure_category'])
    if (graph['status'] == 'verified') != (graph['failure_category'] is None): raise ValueError('diagnostic graph')
    keys(value['providers'], PLATFORM_IDS)
    for aid in PLATFORM_IDS:
        row=value['providers'][aid]
        keys(row, ('status','version','abi','descriptor_sha256','trusted_origin','closure_status','failure_category'))
        if type(row['trusted_origin']) is not bool: raise ValueError('diagnostic origin')
        if row['status'] == 'verified':
            version(row['version']); version(row['abi']); digest(row['descriptor_sha256'])
            if row['trusted_origin'] is not True or row['failure_category'] is not None: raise ValueError('diagnostic authority')
        elif row['status'] in ('refused','unavailable'):
            if any(row[k] is not None for k in ('version','abi','descriptor_sha256')) or row['trusted_origin'] is not False:
                raise ValueError('diagnostic refusal')
            if row['failure_category'] is None: raise ValueError('diagnostic refusal')
        else: raise ValueError('diagnostic status')
        failure(row['failure_category'])
        if row['closure_status'] not in ('verified','unverified'): raise ValueError('diagnostic closure')
        if row['closure_status'] == 'verified' and (row['status'] != 'verified' or graph['status'] != 'verified'):
            raise ValueError('diagnostic closure')
    complete = (graph['status'] == 'verified' and value['source'] is not None and build['status'] == 'verified'
        and value['manifest_sha256'] is not None and value['manifest_fingerprint'] is not None
        and all(row['status'] == row['closure_status'] == 'verified' for row in value['providers'].values()))
    if value['overall'] != ('requirements_verified' if complete else 'unverified'): raise ValueError('diagnostic overall')
    if graph['status'] == 'verified' and not complete: raise ValueError('diagnostic partial graph')
    # Round-trip closes off custom objects and returns no unvalidated fields.
    return json.loads(json.dumps(value, sort_keys=True))


# Qualification-only AF3 fixture. No repository/source override or resume.
AF3_FIXTURE_MODES = ("af3_fixture", "af3_fixture_verify")
_AF3_HOME = Path("/Applications/Kodi Build Manager Test.app/Contents/Resources/Kodi/portable_data")
_AF3_STORE = Path("/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/item8-d028-public-artifact-store-20261022")
_AF3_MANIFEST = _AF3_STORE.parent / "item8-d028-trusted-admission-20261020/authored-af3-manifest.json"
_AF3_MANIFEST_SHA = "30bd44d3f6897b0e17b40afdd44881dcf24acca906cdad8827dad7c095101420"
_AF3_PACKAGES = {'plugin.video.themoviedb.helper': ('6.17.9',
                                    'b1023f7fc82b2d3c037758384fcd32ea6b906f2551be674859c0e1deb37f7989',
                                    4322239),
 'resource.font.robotocjksc': ('0.0.3',
                               '58c3e32cafbbf0984896c4ab317c820e555f3deacae977598e4a03a0f8139743',
                               51599422),
 'resource.images.studios.coloured': ('0.0.24',
                                      'de985b7c671e1f171f8ac8a71a9f24f035ffabebaeee3c3a173e570d8b3c50d6',
                                      60584821),
 'resource.images.weathericons.white': ('0.0.6',
                                        '89466f3c5d1e269e68f9caf3a3b732bc85875f62ab3dd5536730eae19e4d5a2c',
                                        71550),
 'script.module.addon.signals': ('0.0.6+matrix.1',
                                 'a41629f328429d08d79ef3c8b59c93d6f4c06b1a6e76806babd44f2457a9a1fb',
                                 19835),
 'script.module.certifi': ('2023.5.7',
                           'c16d4cd2efe6e57dbb5e8d71a9beb3af213b1e3d717e8b0b24f0cbdc4c645070',
                           162689),
 'script.module.chardet': ('5.1.0',
                           'd5010fc55a9523d86a306ae9e6a8dea0e3248fe079b9ed37280fe86110cd766a',
                           204491),
 'script.module.idna': ('3.10.0', 'c4ff34dbfab2736e9214a374d331bd6f558d8b3fea8eb7902e210749509242b3', 73349),
 'script.module.infotagger': ('0.0.9',
                              '5fb83664bb732bca773d420f9f5b1383be594ed88836f59178032f36bc668336',
                              23148),
 'script.module.jurialmunkey': ('0.2.35',
                                '80302314cdbc5a75611b0c2866eb1c7b4e93ccadaf20208ef7eb79b79c1fb749',
                                55792),
 'script.module.qrcode': ('6.1.0+matrix.3',
                          'e5c01d0ff83bdb7687c3150dcda5a01896a2281c28ffe9813f6e4763ea44f132',
                          32990),
 'script.module.requests': ('2.31.0',
                            'a5704f0fd7afb4154e1beea9b5f05a002bcd75fa581a1e5fd15ece39bf2bd38a',
                            67576),
 'script.module.six': ('1.16.0+matrix.1',
                       '4197f7773f75ab9f16b3c920195acbb8b8b151b4b3c8c3e14fc4876e764e3860',
                       16999),
 'script.module.urllib3': ('2.2.3',
                           '740b2d63bb50eee9fb35f01c567ec8d3588c5bbd548e2b8d280932be30d82f53',
                           130842),
 'script.skinvariables': ('2.2.9',
                          '7bbac52948ff0934fd29ccbf0657d4d625da22514a9afe4818bc4070d08d50b2',
                          236686),
 'script.texturemaker': ('0.2.11',
                         '051bca651c467901b12fcae56ca430402427149d801fa7a7cfd1254d386a738b',
                         171850),
 'skin.arctic.fuse.3': ('3.3.12',
                        'baa7f38da51379f4a65f9aee421e27b369ce799103d58fdef9087920b9041492',
                        58482102)}


def _af3_inputs(manifest_path, artifact_root):
    """Read all original bytes before mutation; retain immutable byte objects."""
    from resources.lib.artifacts import ArtifactMetadata
    from resources.lib.addon_zip import validated_root
    from resources.lib.frozen import FrozenBuildManifest
    from resources.lib.frozen_install import validate_frozen_manifest
    if Path(manifest_path) != _AF3_MANIFEST or Path(artifact_root) != _AF3_STORE:
        raise ValueError('fixture input path refused')
    raw = _platform_read(_AF3_MANIFEST, 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != _AF3_MANIFEST_SHA:
        raise ValueError('fixture manifest identity')
    manifest = FrozenBuildManifest.from_json(raw.decode('utf-8'))
    nodes = {n.addon_id: n for n in manifest.addons if n.artifact is not None}
    if set(nodes) != set(_AF3_PACKAGES): raise ValueError('fixture package set')
    store = _PlatformArtifacts(_AF3_STORE, ArtifactMetadata)
    plan = validate_frozen_manifest(manifest, store)
    if len(plan.nodes) != 22 or sum(len(n.dependency_edges) for n in plan.nodes.values()) != 45:
        raise ValueError('fixture graph identity')
    packages = {}
    for aid, (version, digest, size) in _AF3_PACKAGES.items():
        node = nodes[aid]
        if (node.version, node.artifact.sha256, node.artifact.size) != (version, digest, size):
            raise ValueError('fixture node identity')
        data = store.read_bytes(digest)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('fixture package identity')
        package = validated_root(data, aid, version)
        packages[aid] = (data, package.xml_bytes)
    return plan, packages


def _af3_public_tree(path, limit=16 * 1024 * 1024):
    """Creation-free hash of public library/resolutions only, no private roots."""
    path = Path(path)
    try:
        fd = _platform_directory(path)
    except FileNotFoundError:
        return None
    try:
        original = os.fstat(fd)
        result = {}
        for name in sorted(os.listdir(fd)):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            child = path / name
            if stat.S_ISDIR(info.st_mode):
                result[name] = _af3_public_tree(child, limit)
            elif stat.S_ISREG(info.st_mode):
                result[name] = hashlib.sha256(_platform_read(child, limit)).hexdigest()
            else:
                raise ValueError('fixture public state type')
        fresh = _platform_directory(path)
        try:
            current, linked = os.fstat(fd), os.fstat(fresh)
            fields = ('st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns')
            if (tuple(getattr(original, k) for k in fields) != tuple(getattr(current, k) for k in fields)
                    or (original.st_dev, original.st_ino) != (linked.st_dev, linked.st_ino)):
                raise ValueError('fixture public state changed')
        finally: os.close(fresh)
        return result
    finally:
        os.close(fd)


def _af3_expected_tree(data, aid, version):
    """Original member hashes only; this never extracts or executes a package."""
    import io
    import zipfile
    from resources.lib.addon_zip import validated_root
    validated_root(data, aid, version)
    expected = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            parts = member.filename.rstrip('/').split('/')[1:]
            if not parts: continue
            tree = expected
            for part in parts[:-1]: tree = tree.setdefault(part, {})
            if member.is_dir(): tree.setdefault(parts[-1], {})
            else: tree[parts[-1]] = hashlib.sha256(archive.read(member)).hexdigest()
    return expected


def _af3_runtime_state(backend):
    """Native authority, not caller-supplied claims or a captured manifest."""
    import xbmcvfs
    from resources.lib import frozen_install as fi
    from resources.lib.transaction import TransactionStore
    from resources.lib.capture_lifecycle import CaptureStore
    from resources.lib.activation import current_activation_holds
    from resources.lib.build_library import default_build_library
    profile = _AF3_HOME / 'userdata'
    bm_root = profile / 'addon_data/script.build.manager'
    if (Path(xbmcvfs.translatePath('special://home/')) != _AF3_HOME or
            Path(xbmcvfs.translatePath('special://profile/')) != profile or
            Path(xbmcvfs.translatePath('special://home/addons')) != _AF3_HOME / 'addons' or
            fi.default_frozen_install_root() != bm_root):
        raise ValueError('fixture runtime profile')
    for path in (_AF3_HOME, profile, bm_root):
        fd = _platform_directory(path); os.close(fd)
    if (fi.FrozenInstallStore(bm_root).inspect() is not None or
            TransactionStore().inspect() is not None or
            CaptureStore(bm_root).read() is not None or current_activation_holds()):
        raise ValueError('fixture transaction or hold')
    library = default_build_library()
    if library.pending_publication() is not None: raise ValueError('fixture publication')
    # Typed association read authenticates the existing applied resolution.
    association = library.current_applied_association()
    selection_state, selection = library.selection_state()
    if (association is None or selection_state != 'selected' or selection is None
            or association.entry_id != selection.entry_id
            or association.device_profile_id != selection.device_profile_id):
        raise ValueError('fixture library identity')
    settings = {}
    for key in ('general.addonupdates', 'lookandfeel.skin'):
        row = backend._rpc('Settings.GetSettingValue', {'setting': key}).get('result')
        if not isinstance(row, dict) or 'value' not in row: raise ValueError('fixture setting unavailable')
        settings[key] = row['value']
    if settings['lookandfeel.skin'] != 'skin.estuary': raise ValueError('fixture skin')
    if type(settings['general.addonupdates']) is not int or settings['general.addonupdates'] not in (0, 1, 2):
        raise ValueError('fixture updater observation')
    rows = backend._rpc('Addons.GetAddons', {'installed': True,
        'properties': ['version', 'enabled', 'broken']}).get('result')
    if not isinstance(rows, dict) or not isinstance(rows.get('addons'), list):
        raise ValueError('fixture native inventory')
    inventory = {}
    for row in rows['addons']:
        if (not isinstance(row, dict) or not isinstance(row.get('addonid'), str) or
                not isinstance(row.get('version'), str) or type(row.get('enabled')) is not bool or
                type(row.get('broken')) is not bool or row['addonid'] in inventory):
            raise ValueError('fixture native inventory entry')
        inventory[row['addonid']] = (row['version'], row['enabled'], row['broken'])
    if 'script.keymap' not in inventory or inventory['script.keymap'][0] != '1.4.0' or inventory['script.keymap'][2]:
        raise ValueError('fixture Keymap identity')
    return (settings, {k: v for k, v in inventory.items() if k not in _AF3_PACKAGES},
            repr(association), _af3_public_tree(bm_root / 'build-library'),
            _af3_public_tree(bm_root / 'install_resolutions'))


def run_af3_fixture(addon_root, driver_root, binding, manifest_path, artifact_root, *, verify=False):
    """One admitted fixture attempt. Journal existence always fences provision.

    Native use must go through Git-bound HTTP run; never invoke this as an
    arbitrary script. Only the existing exclusive package publisher mutates
    packages. No coordinator, updater setter, configuration or publication call.
    """
    addon_root, driver_root = Path(addon_root), Path(driver_root)
    if (addon_root != _AF3_HOME / 'addons/script.build.manager' or
            driver_root != _AF3_HOME / 'addons/script.build.manager.bm023a_driver'):
        raise ValueError('fixture target refused')
    from resources.lib.frozen_install import KodiRuntimeFrozenArtifactBackend
    from resources.lib.addon_zip import publish_package
    from resources.lib.frozen import InstalledMetadata, InstalledOrigin
    _platform_sources(binding, addon_root, driver_root)
    plan, packages = _af3_inputs(manifest_path, artifact_root)
    # This reuses current runtime registration, pinned application origin,
    # ABI/dependency closure and PIL admission. Static evidence is insufficient.
    check = read_platform_check(addon_root, driver_root, binding, manifest_path, artifact_root)
    if check.get('ok') is not True: raise ValueError('fixture native platform requirements')
    diagnostic = check['platform_check']
    home_fd = addons_fd = profile_fd = journal_fd = backend = None
    journal = 'bm-af3-fixture-v1.jsonl'
    def fresh():
        for path, pinned in ((_AF3_HOME, home_fd), (_AF3_HOME / 'addons', addons_fd),
                             (_AF3_HOME / 'userdata', profile_fd)):
            fd = _platform_directory(path)
            try:
                if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (os.fstat(pinned).st_dev, os.fstat(pinned).st_ino):
                    raise ValueError('fixture ancestor changed')
            finally: os.close(fd)
        _platform_sources(binding, addon_root, driver_root)
        with backend._passive_build_binding(backend._inventory()) as native_fresh:
            if native_fresh() is not True: raise ValueError('fixture native identity changed')
        if hashlib.sha256(_platform_read(manifest_path, 1024 * 1024)).hexdigest() != _AF3_MANIFEST_SHA:
            raise ValueError('fixture manifest changed')
    def row(stage, aid=None):
        return {'stage': stage, 'addon_id': aid, 'manifest_sha256': _AF3_MANIFEST_SHA,
                'source_sha256': _platform_digest(diagnostic['source']),
                'baseline_sha256': _platform_digest(before)}
    def record(stage, aid=None):
        raw = json.dumps(row(stage, aid),
                         sort_keys=True).encode('ascii') + b'\n'
        with os.fdopen(os.dup(journal_fd), 'ab', closefd=True) as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
    try:
        home_fd = _platform_directory(_AF3_HOME)
        addons_fd = _platform_directory(_AF3_HOME / 'addons')
        profile_fd = _platform_directory(_AF3_HOME / 'userdata')
        backend = KodiRuntimeFrozenArtifactBackend()
        before = _af3_runtime_state(backend)
        if verify:
            raw = _platform_read(_AF3_HOME / 'userdata' / journal, 16384)
            records = [json.loads(line) for line in raw.splitlines()]
            expected = [row('started')]
            for node in plan.install_order:
                if node.addon_id in packages:
                    expected.extend((row('installing', node.addon_id), row('installed', node.addon_id)))
            expected.append(row('complete'))
            if records != expected:
                raise ValueError('fixture completion evidence absent')
        else:
            # Validate every target before journal/package mutation. Exact prior
            # versions also refuse: no adoption of preexisting/partial installs.
            for aid in packages:
                if backend.get_addon_details(aid) is not None:
                    raise ValueError('fixture registered collision')
                try: os.stat(aid, dir_fd=addons_fd, follow_symlinks=False)
                except FileNotFoundError: pass
                else: raise ValueError('fixture directory collision')
            fresh()
            journal_fd = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=profile_fd)
            record('started'); os.fsync(profile_fd)
            for node in plan.install_order:
                aid = node.addon_id
                if aid not in packages: continue
                fresh()
                if _af3_runtime_state(backend) != before: raise ValueError('fixture unrelated state changed')
                record('installing', aid)
                if backend.get_addon_details(aid) is not None:
                    raise ValueError('fixture late registered collision')
                # Direct exclusive publisher, not install_exact's adopt-existing
                # shortcut: a race may never turn into trusting another install.
                publish_package(packages[aid][0], aid, _AF3_HOME / 'addons' / aid, node.version)
                backend._xbmc().executebuiltin('UpdateLocalAddons')
                detail = backend._wait_for_exact(aid, node.version)
                if detail.version != node.version or detail.broken: raise ValueError('fixture registration')
                if not detail.enabled: backend.set_addon_enabled(aid, True)
                record('installed', aid)
        for aid, (version, digest, size) in _AF3_PACKAGES.items():
            detail = backend.get_addon_details(aid)
            if detail is None or detail.version != version or detail.enabled is not True or detail.broken is not False:
                raise ValueError('fixture native health')
            metadata = backend.read_installed_metadata(aid)
            if (not isinstance(metadata, InstalledMetadata) or metadata.origin is not InstalledOrigin.HOME
                    or metadata.xml_bytes != packages[aid][1]):
                raise ValueError('fixture installed origin')
            if _af3_public_tree(_AF3_HOME / 'addons' / aid, 128 * 1024 * 1024) != _af3_expected_tree(packages[aid][0], aid, version):
                raise ValueError('fixture installed package bytes')
        final_platform = read_platform_check(addon_root, driver_root, binding, manifest_path, artifact_root)
        if final_platform.get('ok') is not True: raise ValueError('fixture final platform requirements')
        fresh()
        if _af3_runtime_state(backend) != before: raise ValueError('fixture preservation mismatch')
        if not verify: record('complete')
        return {'ok': True, 'platform_check': diagnostic, 'af3_fixture': {
            'schema': 1, 'status': 'verified' if verify else 'complete',
            'package_count': 17, 'manifest_sha256': _AF3_MANIFEST_SHA,
            'preservation_checked': True, 'native_health_checked': True}}
    finally:
        if journal_fd is not None: os.close(journal_fd)
        if backend is not None: backend.close()
        for fd in (profile_fd, addons_fd, home_fd):
            if fd is not None: os.close(fd)


def project_af3_fixture(value):
    if (not isinstance(value, dict) or set(value) != {'schema','status','package_count',
            'manifest_sha256','preservation_checked','native_health_checked'} or
            type(value['schema']) is not int or value['schema'] != 1 or
            value['status'] not in ('complete','verified') or
            type(value['package_count']) is not int or value['package_count'] != 17 or
            value['manifest_sha256'] != _AF3_MANIFEST_SHA or
            value['preservation_checked'] is not True or value['native_health_checked'] is not True):
        raise ValueError('fixture result invalid')
    return dict(value)
