"""Secret-safe bootstrap checks shared by the generated BM-023A adapter."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any, Dict


ADAPTER_VERSION = "0.0.4"
ADDON_ID = "script.build.manager"
DRIVER_ADDON_ID = "script.build.manager.bm023a_driver"

ADAPTER_STAGES = frozenset({
    "LOCATE_BUILD_MANAGER",
    "IMPORT_RESOURCES",
    "VERIFY_BUILD_MANAGER_SOURCE",
    "IMPORT_PRODUCTION_MODULES",
    "LOAD_FROZEN_MANIFEST",
    "LOAD_CONFIGURATION",
    "LOAD_PRIVATE_OVERLAY",
    "BUILD_COORDINATOR",
    "INVOKE_INSTALL",
    "CHECK_RECOVERY_PRECONDITIONS",
    "INVOKE_RECOVERY",
    "SERIALIZE_RESULT",
})
ADAPTER_CALLABLES = frozenset({
    "xbmcvfs.translatePath",
    "pathlib.Path",
    "importlib.import_module",
    "FrozenBuildManifest.from_json",
    "PrivateOverlayStore.import_file",
    "BuildManager",
    "FrozenInstallCoordinator",
    "FrozenInstallCoordinator.install",
    "FrozenInstallStore.inspect",
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
        if token in ("install", "recover"):
            return token
        if token == "?mode=install":
            return "install"
        if token == "?mode=recover":
            return "recover"
    raise _bootstrap_error(
        "LOCATE_BUILD_MANAGER", "result_serializer", "mode_invalid"
    )


def identify_adapter_result(payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Tag every result with the selected mode or the safe preselection value."""
    safe_mode = mode if mode in ("install", "recover") else "unselected"
    identified = dict(payload)
    identified["adapter_mode"] = safe_mode
    return identified


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
