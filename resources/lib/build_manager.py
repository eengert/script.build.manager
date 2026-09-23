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
from dataclasses import dataclass, replace
from enum import Enum
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
from resources.lib.dependencies import (
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
    )


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
    effective: Optional[EffectiveConfiguration]
    fingerprint: str
    protected_dependency_ids: frozenset
    plan: object
    private_prepared: Optional[PreparedPrivateOverlay] = None
    skipped_addon_ids: Tuple[str, ...] = ()


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
                    action, desired, effective, protected, prepared.private_prepared
                )
            except Exception as exc:
                result = ActionExecutionResult(
                    action=action,
                    succeeded=False,
                    changed=False,
                    message=f"action owner raised: {_message(exc)}",
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
            final_closure = self._final_dependency_closure(desired)
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
                desired, final_actual,
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
            dependency_closure = self._preflight_dependencies(
                desired, actual, include_disabled=bool(skipped_addon_ids)
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
            plan = plan_changes(desired, actual)
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
            effective=effective,
            fingerprint=fingerprint,
            protected_dependency_ids=protected,
            plan=plan,
            private_prepared=private_prepared,
            skipped_addon_ids=skipped_addon_ids,
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
