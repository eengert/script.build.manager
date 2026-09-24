"""Secret-safe bootstrap checks shared by the generated BM-023A adapter."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any, Dict


ADAPTER_VERSION = "0.0.2"
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
