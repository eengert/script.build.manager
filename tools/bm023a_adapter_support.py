"""Secret-safe bootstrap checks shared by the generated BM-023A adapter."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any, Dict


ADAPTER_VERSION = "0.0.8"
ADDON_ID = "script.build.manager"
DRIVER_ADDON_ID = "script.build.manager.bm023a_driver"
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
    "result_serializer",
})
FAILURE_CATEGORIES = frozenset({
    "path_argument_is_none",
    "path_missing_or_unreadable",
    "addon_root_mismatch",
    "module_source_missing",
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
})
SAFE_ERROR_TYPES = frozenset({
    "TypeError", "OSError", "ImportError", "ModuleNotFoundError",
    "ValueError", "RuntimeError", "Exception",
})


class AdapterBootstrapError(Exception):
    """A failure containing only allowlisted bootstrap diagnostic labels."""

    def __init__(self, stage: str, failing_callable: str, category: str):
        self.stage = stage if stage in ADAPTER_STAGES else "LOCATE_BUILD_MANAGER"
        self.failing_callable = (
            failing_callable if failing_callable in ADAPTER_CALLABLES else "result_serializer"
        )
        self.failure_category = (
            category if category in FAILURE_CATEGORIES else "operation_failed"
        )
        super().__init__(self.failure_category)


def _bootstrap_error(stage: str, callable_name: str, category: str) -> AdapterBootstrapError:
    return AdapterBootstrapError(stage, callable_name, category)


def parse_adapter_mode(arguments: list[str]) -> str:
    """Accept one explicit allowlisted token; never default to a mutating mode."""
    if not arguments or arguments == [""]:
        raise _bootstrap_error(
            "LOCATE_BUILD_MANAGER", "result_serializer", "mode_missing"
        )
    if len(arguments) == 1:
        token = arguments[0]
        if token in ("install", "recover", "retry"):
            return token
        if token == "?mode=install":
            return "install"
        if token == "?mode=recover":
            return "recover"
        if token == "?mode=retry":
            return "retry"
    raise _bootstrap_error(
        "LOCATE_BUILD_MANAGER", "result_serializer", "mode_invalid"
    )


def identify_adapter_result(payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Tag every result with the selected mode or the safe preselection value."""
    safe_mode = mode if mode in ("install", "recover", "retry") else "unselected"
    identified = dict(payload)
    identified["adapter_mode"] = safe_mode
    return identified


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


def recover_frozen_install(
    coordinator: Any,
    store: Any,
    policy_backend: Any,
    installer: Any,
    restart_transaction_path: Any,
    *,
    needs_attention_phase: Any,
    update_policy_type: Any,
    af3_addon_id: str = "skin.arctic.fuse.3",
) -> Dict[str, Any]:
    """Run only the fixed, supported BM-023A abandon operation and summarize safely."""
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

    if not (
        transaction.manifest_path == manifest_path
        and transaction.build_id == manifest.build_id
        and transaction.manifest_fingerprint == manifest.fingerprint()
        and transaction.configuration_manifest_path == configuration_manifest_path
        and transaction.device_profile_id == device_profile_id
        and transaction.private_overlay_id == expected_overlay_id
    ):
        raise _bootstrap_error(
            "CHECK_RETRY_PRECONDITIONS", "FrozenInstallStore.inspect", "retry_identity_mismatch"
        )

    if not Path(configuration_manifest_path).is_file():
        raise _bootstrap_error(
            "CHECK_RETRY_PRECONDITIONS", "pathlib.Path", "path_missing_or_unreadable"
        )

    try:
        result = coordinator.retry_held_quiescence(
            expected_transaction=transaction,
            artifact_source_store=artifact_source_store,
            restart_store=restart_store,
        )
    except Exception:
        raise _bootstrap_error(
            "INVOKE_RETRY",
            "FrozenInstallCoordinator.retry_held_quiescence",
            "operation_failed",
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
    return concrete_file


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
    return {
        "ok": False,
        "error_type": error_name,
        "adapter_stage": safe_stage,
        "failing_callable": safe_callable,
        "failure_category": safe_category,
    }
