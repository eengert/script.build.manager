"""Production Build Manager reconciliation orchestration (BM-020A).

This module is deliberately a coordinator. Manifest parsing, profile
resolution, inspection, planning, dependency reconciliation, configuration
deployment, skin activation, and add-on state changes remain owned by their
existing modules. BM-020A supplies the stable request/result boundary and
executes the planner's ordered actions through those owners.

The executor does not restart Kodi, persist transactions, resume after a
restart, or acquire a process-wide lock. Those are later BM-020 work.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

from resources.lib.addon_state import AddonStateReconciler
from resources.lib.addons import AddonManager, KodiRuntimeAddonBackend
from resources.lib.config import (
    ConfigApplyResult,
    ConfigPackageLoader,
    ConfigurationManager,
    EffectiveConfiguration,
    KodiRuntimeConfigurationBackend,
    default_packages_root,
)
from resources.lib.private_overlay import (
    ConfigurationApplyBundle,
    PrivateOverlayManager,
    PrivateOverlayMetadata,
    PreparedPrivateOverlay,
)
from resources.lib.private_resource import ResourceInitializationStage
from resources.lib.installed_addon_source import (
    KodiInstalledAddonSourceResolver,
    ManagedAddonSourceIdentity,
    PrivateResourceOwnerContext,
)
from resources.lib.frozen import CaptureStatus, FrozenBuildManifest
from resources.lib.dependencies import (
    _is_system_dependency,
    DependencyAwareInstaller,
    DependencyResolver,
    DependencyStatus,
    KodiRuntimeDependencyBackend,
)
from resources.lib.inspector import KodiRuntimeBackend, KodiState, KodiStateInspector
from resources.lib.manifest import load_manifest_file
from resources.lib.planner import (
    CONFIGURE,
    DISABLE_ADDON,
    ENABLE_ADDON,
    INSTALL_ADDON,
    INSTALL_REPOSITORY,
    PlanAction,
    SET_SKIN,
    plan_changes,
)
from resources.lib.repository import (
    KodiRuntimeRepositoryBackend,
    RepositoryInstallResult,
    RepositoryManager,
    RepositoryStatus,
)
from resources.lib.resolver import ResolvedBuild, resolve_manifest
from resources.lib.frozen_resolution import (
    InstallResolution,
    InstallResolutionRecord,
    ResolutionState,
)
from resources.lib.restart import RestartReport, aggregate_restart_reports
from resources.lib.skin import KodiRuntimeSkinBackend, SkinActivator
from resources.lib.validator import ValidationReport, validate_build_state


class ReconcilePhase(str, Enum):
    """Phase in which a reconciliation failure occurred."""

    REQUEST = "request"
    LOAD = "load"
    INSPECT = "inspect"
    RESOLVE = "resolve"
    PREFLIGHT = "preflight"
    PLAN = "plan"
    EXECUTE = "execute"
    VALIDATE = "validate"


@dataclass(frozen=True)
class ReconcileRequest:
    """Safe, serializable selectors for one reconciliation request."""

    manifest_path: str
    device_profile_id: str
    install_resolutions: Tuple[InstallResolutionRecord, ...] = ()
    source_software_fingerprint: str = ""
    frozen_transaction_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.manifest_path, str) or not self.manifest_path:
            raise ValueError("manifest_path must be a non-empty string")
        if not isinstance(self.device_profile_id, str) or not self.device_profile_id:
            raise ValueError("device_profile_id must be a non-empty string")
        if not isinstance(self.install_resolutions, tuple) or any(
            not isinstance(record, InstallResolutionRecord)
            for record in self.install_resolutions
        ):
            raise ValueError("install_resolutions must be a tuple of frozen resolution records")
        addon_ids = [record.addon_id for record in self.install_resolutions]
        if len(addon_ids) != len(set(addon_ids)):
            raise ValueError("install_resolutions must not contain duplicate add-on IDs")
        if any(
            record.state not in (ResolutionState.INSTALLED, ResolutionState.SKIPPED)
            for record in self.install_resolutions
        ):
            raise ValueError("install_resolutions must contain only terminal resolutions")
        if not isinstance(self.source_software_fingerprint, str):
            raise ValueError("source_software_fingerprint must be a string")
        if self.source_software_fingerprint and not re.fullmatch(
            r"[0-9a-f]{64}", self.source_software_fingerprint
        ):
            raise ValueError("source_software_fingerprint must be a SHA-256 digest")
        if not isinstance(self.frozen_transaction_id, str):
            raise ValueError("frozen_transaction_id must be a string")
        if self.frozen_transaction_id and not re.fullmatch(
            r"[0-9a-fA-F-]{36}", self.frozen_transaction_id
        ):
            raise ValueError("frozen_transaction_id must be a UUID")

    def to_dict(self) -> dict:
        payload = {
            "manifest_path": self.manifest_path,
            "device_profile_id": self.device_profile_id,
        }
        if self.install_resolutions:
            payload["install_resolutions"] = [
                record.to_dict()
                for record in sorted(self.install_resolutions, key=lambda item: item.addon_id)
            ]
        if self.source_software_fingerprint:
            payload["source_software_fingerprint"] = self.source_software_fingerprint
        if self.frozen_transaction_id:
            payload["frozen_transaction_id"] = self.frozen_transaction_id
        return payload

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True)
class ReconcileFailure:
    """Machine-readable phase failure with a bounded diagnostic message."""

    phase: ReconcilePhase
    code: str
    message: str

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class ActionExecutionResult:
    """One planner action's outcome, including its nested owner result."""

    action: PlanAction
    succeeded: bool
    changed: bool
    message: str
    owner_result: Optional[object] = None
    restart_report: RestartReport = RestartReport()


@dataclass(frozen=True)
class ActionFailureDiagnostic:
    """Sanitized action error metadata; exception text is never retained."""

    code: str
    owner_addon_id: str = ""
    resource_id: str = ""
    cause_code: str = ""
    initialization_stage: str = ""
    last_completed_stage: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not re.fullmatch(
            r"[A-Z0-9_]{1,80}", self.code
        ):
            raise ValueError("action failure code is not safe")
        if self.owner_addon_id and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", self.owner_addon_id
        ):
            raise ValueError("action failure owner is not safe")
        if self.resource_id and not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{0,127}", self.resource_id
        ):
            raise ValueError("action failure resource is not safe")
        if self.cause_code and not re.fullmatch(
            r"[A-Z0-9_]{1,80}", self.cause_code
        ):
            raise ValueError("action failure cause code is not safe")
        stage_values = {item.value for item in ResourceInitializationStage}
        if self.initialization_stage and self.initialization_stage not in stage_values:
            raise ValueError("action failure initialization stage is unsupported")
        if self.last_completed_stage and self.last_completed_stage not in stage_values:
            raise ValueError("action failure completed stage is unsupported")

    def to_dict(self) -> dict:
        result = {
            "code": self.code,
            "owner_addon_id": self.owner_addon_id,
            "resource_id": self.resource_id,
            "cause_code": self.cause_code,
        }
        if self.initialization_stage:
            result["initialization_stage"] = self.initialization_stage
        if self.last_completed_stage:
            result["last_completed_stage"] = self.last_completed_stage
        return result


@dataclass(frozen=True)
class ReconcileResult:
    """Stable aggregate returned to callers of :class:`BuildManager`."""

    success: bool
    request: Optional[ReconcileRequest]
    desired_fingerprint: Optional[str]
    planned_actions: tuple = ()
    action_results: tuple = ()
    restart_report: RestartReport = RestartReport()
    failure: Optional[ReconcileFailure] = None
    validation_report: Optional[ValidationReport] = None
    private_overlay: Optional[PrivateOverlayMetadata] = None

    @property
    def changed(self) -> bool:
        return any(result.changed for result in self.action_results)

    def to_dict(self) -> dict:
        """Serialize safe aggregate metadata without owner-specific payloads."""
        return {
            "success": self.success,
            "request": self.request.to_dict() if self.request else None,
            "desired_fingerprint": self.desired_fingerprint,
            "planned_actions": [_action_dict(a) for a in self.planned_actions],
            "action_results": [
                {
                    "action": _action_dict(result.action),
                    "succeeded": result.succeeded,
                    "changed": result.changed,
                    "message": result.message,
                    "failure": (
                        result.owner_result.to_dict()
                        if isinstance(result.owner_result, ActionFailureDiagnostic)
                        else None
                    ),
                    "restart_report": result.restart_report.to_dict(),
                }
                for result in self.action_results
            ],
            "restart_report": self.restart_report.to_dict(),
            "failure": self.failure.to_dict() if self.failure else None,
            "validation_passed": (
                self.validation_report.passed
                if self.validation_report is not None else None
            ),
            "private_overlay": (
                self.private_overlay.to_dict() if self.private_overlay else None
            ),
        }


@dataclass(frozen=True)
class BuildManagerOwners:
    """Injectable subsystem owners used by the executor and its tests."""

    inspector: object
    manifest_loader: object
    resolver: object
    dependency_resolver: object
    repository_manager: object
    dependency_installer: object
    addon_state_reconciler: object
    skin_activator: object
    config_loader: object
    config_manager: object
    private_overlay_manager: object = None
    installed_addon_source_resolver: object = None
    frozen_manifest_loader: object = None


def _runtime_addon_state_backend():
    from resources.lib.addon_state import KodiRuntimeAddonStateBackend
    return KodiRuntimeAddonStateBackend()


def _default_owners() -> BuildManagerOwners:
    """Construct production owners lazily, outside Kodi or test imports."""
    dependency_resolver = DependencyResolver(KodiRuntimeDependencyBackend())
    config_manager = ConfigurationManager(KodiRuntimeConfigurationBackend())
    return BuildManagerOwners(
        inspector=KodiStateInspector(KodiRuntimeBackend()),
        manifest_loader=load_manifest_file,
        resolver=resolve_manifest,
        dependency_resolver=dependency_resolver,
        repository_manager=RepositoryManager(KodiRuntimeRepositoryBackend()),
        dependency_installer=DependencyAwareInstaller(
            dependency_resolver,
            AddonManager(KodiRuntimeAddonBackend()),
        ),
        addon_state_reconciler=AddonStateReconciler(_runtime_addon_state_backend()),
        skin_activator=SkinActivator(KodiRuntimeSkinBackend()),
        config_loader=ConfigPackageLoader(default_packages_root()),
        config_manager=config_manager,
        private_overlay_manager=PrivateOverlayManager(config_manager),
        installed_addon_source_resolver=KodiInstalledAddonSourceResolver(),
        frozen_manifest_loader=_load_frozen_manifest_file,
    )


def _load_frozen_manifest_file(path: str) -> FrozenBuildManifest:
    """Read frozen graph metadata from the transaction's fingerprinted file."""
    return FrozenBuildManifest.from_json(Path(path).read_text(encoding="utf-8"))


_RESOURCE_REQUIRED_PYTHON_MODULES = {
    # Red Light 2.6.8's audited initializer import chain reaches
    # requests.adapters.Retry through modules.http_defaults.
    "redlight.sqlite.settings.v1": {"requests": "script.module.requests"},
}


def _verified_python_dependency_sources(
    *,
    frozen_manifest: FrozenBuildManifest,
    transaction: object,
    owner_addon_id: str,
    required_module_providers: dict[str, str],
    records_by_id: dict[str, InstallResolutionRecord],
    actual_by_id: dict[str, object],
    source_resolver: object,
) -> tuple:
    """Resolve only the required Python-module subtree of a frozen owner."""
    if not isinstance(frozen_manifest, FrozenBuildManifest):
        raise ValueError("frozen dependency graph is unavailable")
    if frozen_manifest.fingerprint() != transaction.manifest_fingerprint:
        raise ValueError("frozen dependency graph does not match the active transaction")
    nodes = tuple(frozen_manifest.addons)
    nodes_by_id = {node.addon_id: node for node in nodes}
    if len(nodes_by_id) != len(nodes):
        raise ValueError("frozen dependency graph contains duplicate add-ons")
    owner = nodes_by_id.get(owner_addon_id)
    owner_record = records_by_id.get(owner_addon_id)
    owner_registered = actual_by_id.get(owner_addon_id)
    if (
        owner is None
        or owner.system
        or owner.status is not CaptureStatus.COMPLETE
        or owner.artifact is None
        or owner_record is None
        or owner_record.resolution is not InstallResolution.EXACT
        or owner_record.state is not ResolutionState.INSTALLED
        or owner_record.captured_version != owner.version
        or owner_record.resolved_version != owner.version
        or owner_record.artifact_sha256 != owner.artifact.sha256
        or owner_record.artifact_size != owner.artifact.size
        or owner_record.desired_enabled is not owner.desired_enabled
        or owner_registered is None
        or owner_registered.version != owner_record.resolved_version
    ):
        raise ValueError("frozen resource owner is missing from the dependency graph")

    requested_roots = tuple(sorted(set(required_module_providers.values())))
    for dependency_id in requested_roots:
        if not any(
            edge.addon_id == dependency_id and not edge.optional
            for edge in owner.dependency_edges
        ):
            raise ValueError("required Python module is not a required owner dependency")

    visited = set()
    dependency_ids = set()
    pending = list(reversed(requested_roots))
    while pending:
        addon_id = pending.pop()
        if addon_id in visited:
            continue
        visited.add(addon_id)
        node = nodes_by_id.get(addon_id)
        if node is None and _is_system_dependency(addon_id):
            continue
        if node is None:
            raise ValueError("frozen Python dependency is absent from the dependency graph")
        if node.system:
            continue
        if (
            node.status is not CaptureStatus.COMPLETE
            or node.artifact is None
            or not node.artifact.sha256
            or node.artifact.size <= 0
        ):
            raise ValueError("frozen Python dependency has no complete exact artifact")
        record = records_by_id.get(addon_id)
        registered = actual_by_id.get(addon_id)
        if (
            record is None
            or record.resolution is not InstallResolution.EXACT
            or record.state is not ResolutionState.INSTALLED
            or record.captured_version != node.version
            or record.resolved_version != node.version
            or record.artifact_sha256 != node.artifact.sha256
            or record.artifact_size != node.artifact.size
            or record.desired_enabled is not node.desired_enabled
            or registered is None
            or registered.version != record.resolved_version
            or registered.enabled is not record.desired_enabled
        ):
            raise ValueError(
                "installed Python dependency state differs from the exact frozen graph"
            )
        dependency_ids.add(addon_id)
        for edge in reversed(node.dependency_edges):
            if not edge.optional:
                pending.append(edge.addon_id)

    resolved = []
    for addon_id in sorted(dependency_ids):
        record = records_by_id[addon_id]
        identity = ManagedAddonSourceIdentity(
            addon_id=addon_id,
            version=record.resolved_version,
            artifact_sha256=record.artifact_sha256,
            artifact_size=record.artifact_size,
            frozen_transaction_id=transaction.transaction_id,
            manifest_fingerprint=transaction.manifest_fingerprint,
        )
        source = source_resolver.resolve(identity)
        # A required root must expose its provider from the verified Kodi
        # module extension. Other exact graph nodes are included only when
        # their installed metadata declares Python modules.
        try:
            roots = source.python_module_roots()
        except Exception as exc:
            if addon_id in requested_roots:
                raise ValueError("required Python dependency root is unavailable") from exc
            if getattr(exc, "code", "") == "PYTHON_MODULE_ROOT_MISSING":
                continue
            raise
        if not roots:
            if addon_id in requested_roots:
                raise ValueError("required Python dependency root is unavailable")
            continue
        resolved.append(source)

    resolved_ids = {source.addon_id for source in resolved}
    if not set(requested_roots).issubset(resolved_ids):
        raise ValueError("required Python dependency source is unavailable")
    return tuple(resolved)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _action_dict(action: PlanAction) -> dict:
    return {
        "kind": action.kind,
        "addon_id": action.addon_id,
        "desired_state": action.desired_state,
        "current_state": action.current_state,
        "reason": action.reason,
    }


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def fingerprint_resolved_build(
    desired: ResolvedBuild,
    effective: Optional[EffectiveConfiguration] = None,
) -> str:
    """Fingerprint portable desired state, excluding current/private values."""
    payload = {
        "build": {
            "id": desired.build.id,
            "version": desired.build.version,
            "name": desired.build.name,
            "description": desired.build.description,
        },
        "engine_min_version": desired.engine_min_version,
        "platform_profile_id": desired.platform_profile_id,
        "device_profile_id": desired.device_profile_id,
        "repositories": [
            {
                "addon_id": repo.addon_id,
                "bootstrap_url": repo.bootstrap_url,
                "required": repo.required,
            }
            for repo in sorted(desired.repositories, key=lambda item: item.addon_id)
        ],
        "frozen_install_policies": [
            {
                "addon_id": policy.addon_id,
                "policy": policy.mode.value,
                "repository_id": policy.repository_id,
            }
            for policy in desired.frozen_install_policies
        ],
        "addons": [
            {
                "addon_id": addon.addon_id,
                "state": addon.state,
                "note": addon.note,
            }
            for addon in sorted(desired.addons, key=lambda item: item.addon_id)
        ],
        "skin": (
            {
                "addon_id": desired.skin.addon_id,
                "config_packages": list(desired.skin.config_packages),
            }
            if desired.skin is not None else None
        ),
        "config": _config_declarations_payload(desired),
        "effective_configuration": effective.identity if effective is not None else None,
        "optional_groups_applied": sorted(desired.optional_groups_applied),
        "restart_policy": (
            {
                "allow_skin_reload": desired.restart_policy.allow_skin_reload,
                "allow_kodi_restart": desired.restart_policy.allow_kodi_restart,
            }
            if desired.restart_policy is not None else None
        ),
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _config_declarations_payload(desired: ResolvedBuild) -> Optional[dict]:
    config = desired.config
    if config is None:
        return None
    return {
        "packages": list(config.packages),
        "managed_settings": [
            {
                "target_kind": _enum_value(scope.target_kind),
                "addon_id": scope.addon_id,
                "keys": list(scope.keys),
            }
            for scope in config.managed_settings
        ],
        "managed_files": list(config.managed_files),
        "private_settings": [
            {
                "target_kind": _enum_value(declaration.target_kind),
                "addon_id": declaration.addon_id,
                "key": declaration.key,
                "type": declaration.setting_type,
                "required": declaration.required,
                "sensitivity": declaration.sensitivity,
            }
            for declaration in config.private_settings
        ],
        "structured_private_resources": [
            declaration.safe_dict()
            for declaration in config.structured_private_resources
        ],
    }


@dataclass(frozen=True)
class _PreparedReconciliation:
    desired: ResolvedBuild
    execution_desired: ResolvedBuild
    effective: Optional[EffectiveConfiguration]
    fingerprint: str
    protected_dependency_ids: frozenset
    plan: object
    private_prepared: Optional[PreparedPrivateOverlay] = None
    skipped_addon_ids: Tuple[str, ...] = ()
    owner_contexts: object = None


class BuildManager:
    """Stable production entrypoint for one complete reconciliation run."""

    ACTION_KINDS = frozenset({
        INSTALL_REPOSITORY,
        INSTALL_ADDON,
        ENABLE_ADDON,
        DISABLE_ADDON,
        SET_SKIN,
        CONFIGURE,
    })

    def __init__(self, owners: Optional[BuildManagerOwners] = None) -> None:
        self._owners = owners or _default_owners()

    @property
    def owners(self) -> BuildManagerOwners:
        return self._owners

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        """Run load → inspect → resolve → preflight → plan → execute → validate."""
        prepared, failure = self._prepare(request)
        if failure is not None:
            return failure
        assert prepared is not None
        desired = prepared.desired
        execution_desired = prepared.execution_desired
        effective = prepared.effective
        fingerprint = prepared.fingerprint
        protected = prepared.protected_dependency_ids
        skipped_addon_ids = prepared.skipped_addon_ids
        plan = prepared.plan
        private_metadata = (
            prepared.private_prepared.metadata
            if prepared.private_prepared is not None else None
        )

        action_results = []
        reports = []
        for action in plan.actions:
            if action.kind not in self.ACTION_KINDS:
                failure = ReconcileFailure(
                    ReconcilePhase.EXECUTE, "UNKNOWN_ACTION_KIND",
                    f"unsupported planner action kind {action.kind!r}",
                )
                return ReconcileResult(
                    success=False, request=request,
                    desired_fingerprint=fingerprint,
                    planned_actions=plan.actions,
                    action_results=tuple(action_results),
                    restart_report=aggregate_restart_reports(reports),
                    failure=failure,
                    private_overlay=private_metadata,
                )

            try:
                result = self._dispatch_action(
                    action, execution_desired, effective, protected,
                    prepared.private_prepared, prepared.owner_contexts,
                )
            except Exception as exc:
                diagnostic = _action_failure_diagnostic(exc)
                result = ActionExecutionResult(
                    action=action,
                    succeeded=False,
                    changed=False,
                    message=f"action failed safely ({diagnostic.code})",
                    owner_result=diagnostic,
                )
            action_results.append(result)
            reports.append(result.restart_report)
            if not result.succeeded:
                return ReconcileResult(
                    success=False, request=request,
                    desired_fingerprint=fingerprint,
                    planned_actions=plan.actions,
                    action_results=tuple(action_results),
                    restart_report=aggregate_restart_reports(reports),
                    failure=ReconcileFailure(
                        ReconcilePhase.EXECUTE, "ACTION_FAILED", result.message,
                    ),
                    private_overlay=private_metadata,
                )

        try:
            final_actual = self._owners.inspector.inspect()
            final_closure = self._final_dependency_closure(execution_desired)
            if final_closure is not None and skipped_addon_ids:
                skipped_required_dependencies = {
                    node.addon_id
                    for node in final_closure.nodes
                    if node.addon_id in skipped_addon_ids and not node.optional
                }
                if skipped_required_dependencies:
                    raise ValueError(
                        "frozen skipped add-on is required by the final configuration dependency closure"
                    )
            config_state = self._config_validation_state(action_results)
            validation = validate_build_state(
                execution_desired, final_actual,
                dependency_closure=final_closure,
                configuration_state=config_state,
                effective_configuration=effective,
            )
        except Exception as exc:
            return ReconcileResult(
                success=False, request=request,
                desired_fingerprint=fingerprint,
                planned_actions=plan.actions,
                action_results=tuple(action_results),
                restart_report=aggregate_restart_reports(reports),
                failure=ReconcileFailure(
                    ReconcilePhase.VALIDATE, "VALIDATION_FAILED", _message(exc),
                ),
                private_overlay=private_metadata,
            )

        if not validation.passed:
            return ReconcileResult(
                success=False, request=request,
                desired_fingerprint=fingerprint,
                planned_actions=plan.actions,
                action_results=tuple(action_results),
                restart_report=aggregate_restart_reports(reports),
                failure=ReconcileFailure(
                    ReconcilePhase.VALIDATE, "POST_VALIDATION_FAILED",
                    "resolved desired state did not pass complete validation",
                ),
                validation_report=validation,
                private_overlay=private_metadata,
            )

        return ReconcileResult(
            success=True, request=request,
            desired_fingerprint=fingerprint,
            planned_actions=plan.actions,
            action_results=tuple(action_results),
            restart_report=aggregate_restart_reports(reports),
            validation_report=validation,
            private_overlay=private_metadata,
        )

    def preview(self, request: ReconcileRequest) -> ReconcileResult:
        """Resolve and plan desired state without invoking any mutating owner."""
        prepared, failure = self._prepare(request)
        if failure is not None:
            return failure
        assert prepared is not None
        return ReconcileResult(
            success=True,
            request=request,
            desired_fingerprint=prepared.fingerprint,
            planned_actions=prepared.plan.actions,
            private_overlay=(
                prepared.private_prepared.metadata
                if prepared.private_prepared is not None else None
            ),
        )

    def _prepare(self, request: ReconcileRequest):
        """Build the shared read-only reconciliation preparation."""
        if not isinstance(request, ReconcileRequest):
            return None, self._failed(
                None, ReconcilePhase.REQUEST, "INVALID_REQUEST",
                "request must be a ReconcileRequest",
            )

        try:
            manifest = self._owners.manifest_loader(request.manifest_path)
        except Exception as exc:
            return None, self._failed(request, ReconcilePhase.LOAD, "MANIFEST_LOAD_FAILED", exc)

        try:
            actual = self._owners.inspector.inspect()
        except Exception as exc:
            return None, self._failed(request, ReconcilePhase.INSPECT, "INSPECTION_FAILED", exc)

        try:
            desired = self._owners.resolver(manifest, request.device_profile_id)
            desired, skipped_addon_ids = self._apply_install_resolutions(
                desired, request.install_resolutions
            )
        except Exception as exc:
            return None, self._failed(request, ReconcilePhase.RESOLVE, "RESOLUTION_FAILED", exc)

        try:
            effective = self._owners.config_loader.resolve(desired.config)
            private_prepared = None
            if desired.private_overlay is not None:
                manager = self._owners.private_overlay_manager
                if manager is None:
                    raise ValueError("private overlay support is unavailable")
                private_prepared = manager.prepare(
                    desired.private_overlay,
                    desired.config.private_settings if desired.config is not None else (),
                    build_id=desired.build.id,
                    resource_declarations=(
                        desired.config.structured_private_resources
                        if desired.config is not None else ()
                    ),
                    source_software_fingerprint=request.source_software_fingerprint,
                )
            fingerprint = fingerprint_resolved_build(desired, effective)
            if skipped_addon_ids:
                installed_ids = {addon.addon_id for addon in actual.addons}
                unresolved_managed_addons = {
                    addon.addon_id for addon in desired.addons
                    if addon.addon_id not in installed_ids
                }
                if unresolved_managed_addons:
                    raise ValueError(
                        "cannot prove frozen skip compatibility while managed add-ons are not installed"
                    )

            # BM-022 is the sole lifecycle owner. While a durable activation
            # hold exists, accept only its exact configuration request and
            # project every held owner/dependent to disabled for planning and
            # validation. A normal second reconciliation is read-only with
            # respect to configured lifecycle resources.
            from resources.lib.frozen_install import (
                FrozenInstallPhase,
                FrozenInstallStore,
                FrozenLifecycleStage,
                active_activation_hold_ids,
            )
            transaction = FrozenInstallStore().inspect()
            held_ids = active_activation_hold_ids()
            execution_desired = desired
            owner_contexts = {}
            lifecycle_resources = tuple(
                item for item in (
                    desired.config.structured_private_resources
                    if desired.config is not None else ()
                )
                if item.configure_before_activation
            )
            if held_ids:
                if transaction is None or transaction.activation_hold_released:
                    raise ValueError("activation hold has no authoritative frozen transaction")
                stage_owns_configuration = (
                    transaction.phase is FrozenInstallPhase.CONFIGURING
                    and transaction.lifecycle_stage is FrozenLifecycleStage.CONFIGURING
                ) or (
                    transaction.phase is FrozenInstallPhase.AWAITING_RESTART
                    and transaction.lifecycle_stage
                    is FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART
                )
                if (
                    request.frozen_transaction_id != transaction.transaction_id
                    or request.manifest_path != transaction.configuration_manifest_path
                    or request.device_profile_id != transaction.device_profile_id
                    or request.source_software_fingerprint != transaction.manifest_fingerprint
                    or tuple(request.install_resolutions) != tuple(transaction.resolution_records)
                    or not stage_owns_configuration
                ):
                    raise ValueError("active activation hold belongs to another coordinator stage")
                if not lifecycle_resources or not {
                    item.owner_addon_id for item in lifecycle_resources
                }.issubset(held_ids):
                    raise ValueError("configuration resources are not covered by the activation hold")
                if transaction.private_overlay_id:
                    metadata = private_prepared.metadata if private_prepared else None
                    if (
                        metadata is None
                        or metadata.overlay_id != transaction.private_overlay_id
                        or metadata.fingerprint != transaction.private_overlay_fingerprint
                        or metadata.required != transaction.private_overlay_required
                    ):
                        raise ValueError("private overlay identity differs from the lifecycle transaction")
                actual_map = {item.addon_id: item for item in actual.addons}
                if any(
                    addon_id not in actual_map or actual_map[addon_id].enabled
                    for addon_id in held_ids
                ):
                    raise ValueError("held add-ons are not all installed and disabled")
                managed_ids = {item.addon_id for item in desired.addons}
                if not held_ids.issubset(managed_ids):
                    raise ValueError("activation hold includes an unmanaged desired add-on")
                source_resolver = getattr(
                    self._owners, "installed_addon_source_resolver", None
                )
                if source_resolver is None:
                    raise ValueError("verified installed add-on source resolver is unavailable")
                records_by_id = {
                    item.addon_id: item for item in transaction.resolution_records
                }
                for declaration in lifecycle_resources:
                    owner_id = declaration.owner_addon_id
                    if owner_id in owner_contexts:
                        continue
                    record = records_by_id.get(owner_id)
                    registered = actual_map.get(owner_id)
                    if (
                        record is None
                        or record.state is not ResolutionState.INSTALLED
                        or record.resolution is InstallResolution.SKIPPED
                        or not record.resolved_version
                        or not record.artifact_sha256
                        or record.artifact_size is None
                        or registered is None
                        or registered.enabled is not False
                        or registered.version != record.resolved_version
                        or record.resolved_version not in declaration.supported_versions
                    ):
                        raise ValueError(
                            "held resource owner registry state differs from its frozen resolution"
                        )
                    identity = ManagedAddonSourceIdentity(
                        addon_id=record.addon_id,
                        version=record.resolved_version,
                        artifact_sha256=record.artifact_sha256,
                        artifact_size=record.artifact_size,
                        frozen_transaction_id=transaction.transaction_id,
                        manifest_fingerprint=transaction.manifest_fingerprint,
                    )
                    source = source_resolver.resolve(identity)
                    required_module_providers = _RESOURCE_REQUIRED_PYTHON_MODULES.get(
                        declaration.adapter_id, {}
                    )
                    dependency_sources = ()
                    if required_module_providers:
                        frozen_manifest_loader = getattr(
                            self._owners, "frozen_manifest_loader", None
                        )
                        if not callable(frozen_manifest_loader):
                            raise ValueError("frozen dependency graph loader is unavailable")
                        frozen_manifest = frozen_manifest_loader(transaction.manifest_path)
                        dependency_sources = _verified_python_dependency_sources(
                            frozen_manifest=frozen_manifest,
                            transaction=transaction,
                            owner_addon_id=owner_id,
                            required_module_providers=required_module_providers,
                            records_by_id=records_by_id,
                            actual_by_id=actual_map,
                            source_resolver=source_resolver,
                        )
                    owner_contexts[owner_id] = PrivateResourceOwnerContext(
                        owner_addon_id=owner_id,
                        expected_version=record.resolved_version,
                        registry_version=registered.version,
                        owner_enabled=registered.enabled,
                        activation_held=owner_id in held_ids,
                        installed_source=source,
                        python_dependency_sources=dependency_sources,
                    )
            else:
                if request.frozen_transaction_id:
                    raise ValueError("frozen lifecycle request has no active activation hold")
                if lifecycle_resources:
                    if private_prepared is None:
                        raise ValueError("pre-activation resources have no validated overlay")
                    manager = self._owners.private_overlay_manager
                    if manager is None or not manager.verify_configured_resources(private_prepared):
                        raise ValueError(
                            "pre-activation resource state requires its frozen lifecycle hold"
                        )

            dependency_closure = self._preflight_dependencies(
                desired, actual, include_disabled=bool(skipped_addon_ids)
            )
            if held_ids:
                enabled_roots = {
                    item.addon_id for item in desired.addons
                    if item.state == "enabled" and item.addon_id not in held_ids
                }
                for node in dependency_closure.nodes:
                    if node.addon_id in held_ids:
                        if enabled_roots.intersection(node.required_by):
                            raise ValueError(
                                "an unheld desired add-on references a held dependency"
                            )
                if desired.skin is not None and desired.skin.addon_id in held_ids:
                    raise ValueError("a held add-on cannot be activated as the desired skin")
                execution_desired = replace(
                    desired,
                    addons=tuple(
                        replace(addon, state="disabled")
                        if addon.addon_id in held_ids else addon
                        for addon in desired.addons
                    ),
                )
            protected = frozenset(
                node.addon_id
                for node in dependency_closure.nodes
                if node.status in (
                    DependencyStatus.SATISFIED,
                    DependencyStatus.INSTALLED_DISABLED,
                )
            )
            required_dependency_ids = {
                node.addon_id
                for node in dependency_closure.nodes
                if not node.optional
            }
            blocked_skips = sorted(set(skipped_addon_ids) & required_dependency_ids)
            if blocked_skips:
                raise ValueError(
                    "frozen skipped add-on is required by the configuration dependency closure"
                )
        except Exception as exc:
            return None, self._failed(request, ReconcilePhase.PREFLIGHT, "PREFLIGHT_FAILED", exc)

        try:
            plan = plan_changes(execution_desired, actual)
        except Exception as exc:
            return None, self._failed(
                request, ReconcilePhase.PLAN, "PLANNING_FAILED", exc,
                desired_fingerprint=fingerprint,
            )

        for action in plan.actions:
            if action.kind not in self.ACTION_KINDS:
                return None, self._failed(
                    request, ReconcilePhase.PLAN, "UNKNOWN_ACTION_KIND",
                    f"unsupported planner action kind {action.kind!r}",
                    desired_fingerprint=fingerprint,
                )
        return _PreparedReconciliation(
            desired=desired,
            execution_desired=execution_desired,
            effective=effective,
            fingerprint=fingerprint,
            protected_dependency_ids=protected,
            plan=plan,
            private_prepared=private_prepared,
            skipped_addon_ids=skipped_addon_ids,
            owner_contexts=owner_contexts,
        ), None

    @staticmethod
    def _apply_install_resolutions(
        desired: ResolvedBuild,
        records: Tuple[InstallResolutionRecord, ...],
    ) -> Tuple[ResolvedBuild, Tuple[str, ...]]:
        """Project explicit frozen-install outcomes onto reconciliation state."""
        if not records:
            return desired, ()
        skipped = {
            record.addon_id for record in records
            if record.resolution is InstallResolution.SKIPPED
        }
        if not skipped:
            return desired, ()
        if desired.skin is not None and desired.skin.addon_id in skipped:
            raise ValueError("a frozen skipped add-on cannot be the desired skin")
        if any(repository.addon_id in skipped and repository.required for repository in desired.repositories):
            raise ValueError("a required repository cannot be skipped")
        return replace(desired, addons=tuple(
            addon for addon in desired.addons if addon.addon_id not in skipped
        )), tuple(sorted(skipped))

    def _preflight_dependencies(
        self,
        desired: ResolvedBuild,
        actual: KodiState,
        *,
        include_disabled: bool = False,
    ):
        installed_ids = {addon.addon_id for addon in actual.addons}
        roots = sorted(
            {
                addon.addon_id
                for addon in desired.addons
                if (include_disabled or addon.state == "enabled")
                and addon.addon_id in installed_ids
            }
            | (
                {desired.skin.addon_id}
                if desired.skin is not None and desired.skin.addon_id in installed_ids
                else set()
            )
        )
        if not roots:
            from resources.lib.dependencies import DependencyClosure
            return DependencyClosure(root_addon_ids=(), nodes=())
        closure = self._owners.dependency_resolver.resolve_closure(
            roots, require_root_metadata=True,
        )
        if closure.metadata_errors or closure.insufficient_version:
            raise ValueError("installed dependency metadata is not safely resolvable")
        return closure

    def _final_dependency_closure(self, desired: ResolvedBuild):
        roots = [addon.addon_id for addon in desired.addons if addon.state == "enabled"]
        if not roots:
            return None
        return self._owners.dependency_resolver.resolve_closure(
            sorted(roots), require_root_metadata=True,
        )

    def _config_validation_state(self, results):
        for result in results:
            if isinstance(result.owner_result, ConfigApplyResult):
                return result.owner_result.validation_state
            if isinstance(result.owner_result, ConfigurationApplyBundle):
                return result.owner_result.public_result.validation_state
        return None

    def _dispatch_action(
        self, action, desired, effective, protected_dependency_ids,
        private_prepared: Optional[PreparedPrivateOverlay] = None,
        owner_contexts=None,
    ):
        if action.kind == INSTALL_REPOSITORY:
            repository = next(
                (item for item in desired.repositories if item.addon_id == action.addon_id),
                None,
            )
            if repository is None:
                return _failed_action(action, "planned repository is absent from desired state")
            repo_result = self._owners.repository_manager.install(repository)
            if action.desired_state == "disabled":
                state_result = self._owners.addon_state_reconciler.reconcile(
                    {action.addon_id: "disabled"},
                    protected_dependency_ids=protected_dependency_ids,
                )
                succeeded = _state_succeeded(state_result)
                changed = _result_changed(repo_result) or bool(state_result.changed)
                return ActionExecutionResult(
                    action=action,
                    succeeded=succeeded and _result_succeeded(repo_result),
                    changed=changed if succeeded else False,
                    message=(
                        "repository installed and disabled"
                        if succeeded else "repository state reconciliation failed"
                    ),
                    owner_result=(repo_result, state_result),
                    restart_report=_result_restart(repo_result),
                )
            return _action_from_owner(action, repo_result)

        if action.kind == INSTALL_ADDON:
            explicit = {item.addon_id: item.state for item in desired.addons}
            owner_result = self._owners.dependency_installer.install(
                action.addon_id,
                desired_state=action.desired_state,
                explicit_desired_states=explicit,
            )
            return _action_from_owner(action, owner_result)

        if action.kind in (ENABLE_ADDON, DISABLE_ADDON):
            owner_result = self._owners.addon_state_reconciler.reconcile(
                {action.addon_id: action.desired_state},
                protected_dependency_ids=protected_dependency_ids,
            )
            return ActionExecutionResult(
                action=action,
                succeeded=_state_succeeded(owner_result),
                changed=bool(owner_result.changed) if _state_succeeded(owner_result) else False,
                message=_state_message(owner_result),
                owner_result=owner_result,
            )

        if action.kind == SET_SKIN:
            return _action_from_owner(
                action, self._owners.skin_activator.activate(action.addon_id),
            )

        if action.kind == CONFIGURE:
            public_result = self._owners.config_manager.apply(effective)
            if not public_result.all_applied:
                return _action_from_owner(action, public_result)
            private_result = None
            if private_prepared is not None:
                manager = self._owners.private_overlay_manager
                if manager is None:
                    return _failed_action(action, "private overlay support is unavailable")
                has_pre_activation_resources = any(
                    item.configure_before_activation
                    for item in private_prepared.resource_declarations
                )
                if not (
                    has_pre_activation_resources
                    and public_result.restart_report.requires_restart
                ):
                    if owner_contexts:
                        private_result = manager.apply(
                            private_prepared, owner_contexts=owner_contexts
                        )
                    else:
                        private_result = manager.apply(private_prepared)
            return _action_from_owner(
                action,
                ConfigurationApplyBundle(public_result, private_result),
            )

        return _failed_action(action, f"unsupported planner action kind {action.kind!r}")

    @staticmethod
    def _failed(request, phase, code, exc, *, desired_fingerprint=None):
        return ReconcileResult(
            success=False, request=request,
            desired_fingerprint=desired_fingerprint,
            failure=ReconcileFailure(phase, code, _message(exc)),
        )


def _message(exc: object) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:500]


def _action_failure_diagnostic(exc: object) -> ActionFailureDiagnostic:
    """Extract only validated codes and identifiers from an action error."""
    code = getattr(exc, "code", "")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9_]{1,80}", code):
        code = "ACTION_EXECUTION_FAILED"
    owner = getattr(exc, "owner_addon_id", "")
    if not isinstance(owner, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", owner
    ):
        owner = ""
    resource = getattr(exc, "resource_id", "")
    if not isinstance(resource, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{0,127}", resource
    ):
        resource = ""
    cause = getattr(exc, "cause_code", "")
    if not isinstance(cause, str) or not re.fullmatch(r"[A-Z0-9_]{1,80}", cause):
        cause = ""
    initialization_stage = getattr(exc, "initialization_stage", "")
    initialization_stage = getattr(
        initialization_stage, "value", initialization_stage
    )
    last_completed_stage = getattr(exc, "last_completed_stage", "")
    last_completed_stage = getattr(last_completed_stage, "value", last_completed_stage)
    if initialization_stage not in {item.value for item in ResourceInitializationStage}:
        initialization_stage = ""
    if last_completed_stage not in {item.value for item in ResourceInitializationStage}:
        last_completed_stage = ""
    return ActionFailureDiagnostic(
        code, owner, resource, cause, initialization_stage, last_completed_stage
    )


def _result_succeeded(result: object) -> bool:
    if hasattr(result, "succeeded"):
        return bool(result.succeeded)
    if isinstance(result, ConfigApplyResult):
        return result.all_applied
    if isinstance(result, RepositoryInstallResult):
        return result.status is not RepositoryStatus.FAILED
    status = getattr(result, "status", None)
    return _enum_value(status) not in ("failed", "missing")


def _result_changed(result: object) -> bool:
    if hasattr(result, "changed"):
        value = result.changed
        return bool(value) if isinstance(value, bool) else bool(tuple(value))
    if isinstance(result, RepositoryInstallResult):
        return result.status is RepositoryStatus.INSTALLED
    status = _enum_value(getattr(result, "status", None))
    return status in ("installed", "activated", "updated", "created", "enabled", "disabled")


def _result_restart(result: object) -> RestartReport:
    report = getattr(result, "restart_report", None)
    return report if isinstance(report, RestartReport) else RestartReport()


def _action_from_owner(action: PlanAction, owner_result: object) -> ActionExecutionResult:
    succeeded = _result_succeeded(owner_result)
    return ActionExecutionResult(
        action=action,
        succeeded=succeeded,
        changed=_result_changed(owner_result) if succeeded else False,
        message=_message(getattr(owner_result, "message", "action completed")),
        owner_result=owner_result,
        restart_report=_result_restart(owner_result),
    )


def _state_succeeded(result: object) -> bool:
    return bool(getattr(result, "all_correct", False))


def _state_message(result: object) -> str:
    failed = getattr(result, "failed", ())
    if failed:
        return _message(getattr(failed[0], "message", "add-on state reconciliation failed"))
    results = getattr(result, "results", ())
    return _message(getattr(results[0], "message", "add-on state reconciled")) if results else "add-on state reconciled"


def _failed_action(action: PlanAction, message: str) -> ActionExecutionResult:
    return ActionExecutionResult(
        action=action,
        succeeded=False,
        changed=False,
        message=message,
    )
