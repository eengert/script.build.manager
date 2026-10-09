"""Read-only Build Status service (BM-UI-002B / G2).

``BuildStatusService.check()`` answers, from a fresh read of Kodi and Build
Manager state: is the managed software current, is the managed skin current,
is supported configuration current, are supported private settings verified,
is a restart pending, and does Build Manager need attention.

Observational only. This module imports no installer, add-on-state reconciler,
skin activator, updater-policy setter, or configuration/private-resource
applier, and it reaches Kodi and the disk only through read-only views:

* Kodi state via ``KodiStateInspector`` (JSON-RPC reads);
* settings and managed files via ``ConfigurationInspector`` over a
  ``ReadOnlyConfigurationBackend`` (no setter or writer is reachable);
* dependency metadata via a ``DependencyResolver`` whose backend refuses to
  install or enable anything and never reads repository metadata (which can
  download packages);
* structured private resources via ``StructuredPrivateResourceManager.inspect``;
* durable operation state via lock-free, creation-free ``read_snapshot``
  methods (no lock file, no directory, no window property is created).

Truthfulness rules: an area that could not be checked is ``UNAVAILABLE`` and
the result is never ``CURRENT`` while any applicable area is unchecked; a
failed inspection is reduced to a stable gap enum and never surfaces exception
text; the result type (`resources.lib.status_model`) has no field that can
carry a setting value, secret, path, fingerprint, or message.

Precedence of the overall result: NEEDS_ATTENTION, then RESTART_REQUIRED, then
CHANGES_NEEDED (drift was proven), then INCOMPLETE (something was not
checked), then CURRENT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from resources.lib.build_identity import (
    IdentityCode,
    IdentityMismatch,
    bind_resolutions,
    check_frozen_identity,
)
from resources.lib.config import (
    ConfigPackageLoader,
    ConfigSetting,
    ConfigurationInspector,
    KodiRuntimeConfigurationBackend,
    ReadOnlyConfigurationBackend,
    default_packages_root,
)
from resources.lib.dependencies import (
    DependencyBackend,
    DependencyResolver,
    DependencyStatus,
    KodiRuntimeDependencyBackend,
)
from resources.lib.frozen import CaptureStatus, FrozenBuildManifest
from resources.lib.frozen_install import (
    FrozenInstallPhase,
    FrozenInstallStateUnreadable,
    FrozenInstallStore,
)
from resources.lib.frozen_resolution import (
    FrozenInstallResolutionManifest,
    InstallResolution,
    InstallResolutionRecord,
)
from resources.lib.inspector import KodiRuntimeBackend, KodiState, KodiStateInspector
from resources.lib.manifest import load_manifest_file
from resources.lib.private_overlay import (
    PrivateOverlay,
    PrivateOverlayMissingError,
    PrivateOverlayStore,
    validate_private_overlay,
)
from resources.lib.private_resource import (
    ResourceCheckStatus,
    StructuredPrivateResourceManager,
)
from resources.lib.resolver import ResolvedBuild, resolve_manifest
from resources.lib.session import peek_current_kodi_session_id
from resources.lib.startup import StartupClassification, classify_startup_transaction
from resources.lib.status_model import (
    AreaLevel,
    BuildIdentity,
    BuildPresentation,
    build_display_name,
    BuildStatus,
    CheckGap,
    ConfigurationStatus,
    OperationCode,
    OperationKind,
    OperationStatus,
    OverallStatus,
    PrivateItem,
    PrivateItemKind,
    PrivateStatus,
    SkinStatus,
    SoftwareItem,
    SoftwareItemState,
    SoftwareStatus,
    StatusArea,
    is_plain_name,
)
from resources.lib.transaction import (
    RestartTransaction,
    TransactionPersistenceError,
    TransactionStore,
)
from resources.lib.validator import ValidationDomain, ValidationStatus, validate_build_state
from resources.lib.build_library import LibrarySource, AppliedBuildAssociation

_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_STATUS_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")

# Worst-first ordering used when two checks describe the same add-on.
_ITEM_SEVERITY = (
    SoftwareItemState.MISSING,
    SoftwareItemState.WRONG_VERSION,
    SoftwareItemState.WRONG_ENABLED_STATE,
    SoftwareItemState.UNCHECKABLE,
    SoftwareItemState.CURRENT,
)
_DRIFT_STATES = frozenset({
    SoftwareItemState.MISSING,
    SoftwareItemState.WRONG_VERSION,
    SoftwareItemState.WRONG_ENABLED_STATE,
})


@dataclass(frozen=True)
class StatusTarget:
    """The desired build to compare Kodi against. Paths never reach the result.

    ``configuration_manifest_path`` plus ``device_profile_id`` select the
    resolved build manifest (skin, settings, private data, managed add-on
    states). ``software_manifest_path`` is the optional frozen software graph
    carrying exact versions. ``install_resolution`` is the recorded outcome of
    an earlier install (an accepted skip or a repository fallback version); it
    refines what "current" means for those add-ons and decides nothing.

    The resolution is the installer's own ``FrozenInstallResolutionManifest``
    because only it carries the build ID and source software fingerprint that
    prove it belongs to this build. Individual records carry neither, so raw
    record tuples are not accepted. The service verifies the binding
    (``resources.lib.build_identity``) before trusting any of it.

    ``library_source`` reloads one verified owned manifest/frozen/package
    snapshot. For that source, legacy path fields are internal locators only;
    the service never passes them to independent filesystem/global loaders.
    """

    configuration_manifest_path: str
    device_profile_id: str
    software_manifest_path: str = ""
    install_resolution: Optional[FrozenInstallResolutionManifest] = None
    library_source: Optional[LibrarySource] = None
    applied_association: Optional[AppliedBuildAssociation] = None

    def __post_init__(self) -> None:
        if self.library_source is not None and not isinstance(self.library_source, LibrarySource):
            raise ValueError("library_source must be a LibrarySource")
        if self.applied_association is not None:
            if (not isinstance(self.applied_association, AppliedBuildAssociation)
                    or self.library_source is None
                    or self.applied_association.entry_id != self.library_source.entry_id
                    or self.applied_association.device_profile_id != self.device_profile_id):
                raise ValueError("applied association must match the target")
        if not isinstance(self.configuration_manifest_path, str) or not self.configuration_manifest_path:
            raise ValueError("configuration_manifest_path must be a non-empty string")
        if not isinstance(self.device_profile_id, str) or not self.device_profile_id:
            raise ValueError("device_profile_id must be a non-empty string")
        if not isinstance(self.software_manifest_path, str):
            raise ValueError("software_manifest_path must be a string")
        if self.install_resolution is not None and not isinstance(
            self.install_resolution, FrozenInstallResolutionManifest
        ):
            raise ValueError("install_resolution must be an install resolution manifest")


@dataclass(frozen=True)
class StatusOwners:
    """Injectable read-only collaborators. None of them can mutate Kodi or Build Manager."""

    inspector: object                       # .inspect() -> KodiState
    manifest_loader: Callable[[str], object]
    resolver: Callable[[object, str], ResolvedBuild]
    frozen_manifest_loader: Callable[[str], FrozenBuildManifest]
    config_loader: object                   # .resolve(ConfigDeclarations) -> EffectiveConfiguration
    configuration_inspector: ConfigurationInspector
    dependency_resolver: object             # .resolve_closure(roots, require_root_metadata=True)
    overlay_loader: Callable[[str], PrivateOverlay]
    resource_manager: Callable[[], StructuredPrivateResourceManager]
    restart_snapshot: Callable[[], Optional[RestartTransaction]]
    frozen_snapshot: Callable[[], Optional[object]]
    session_id: Callable[[], str]
    clock: Callable[[], str]
    log: Callable[[str], None]
    name_resolver: Optional[Callable[[str], str]] = None
    publication_snapshot: Optional[Callable[[], object]] = None


class _ReadOnlyDependencyBackend(DependencyBackend):
    """Installed-add-on metadata reads only.

    Installing or enabling is refused, and repository metadata is never
    consulted: ``read_available_addon_xml`` can download packages over the
    network and would let a repository copy stand in for an installed add-on's
    own unreadable metadata. Status describes what is installed, nothing else.
    """

    def __init__(self, backend: DependencyBackend) -> None:
        self._get_addon_details = backend.get_addon_details
        self._read_addon_xml = backend.read_addon_xml

    def get_addon_details(self, addon_id: str):
        return self._get_addon_details(addon_id)

    def read_addon_xml(self, addon_id: str):
        return self._read_addon_xml(addon_id)

    def read_available_addon_xml(self, addon_id: str):
        return None

    def install_addon(self, addon_id: str, desired_state: str = "enabled"):
        raise RuntimeError("status inspection is read-only")

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        raise RuntimeError("status inspection is read-only")


class _SnapshotStore:
    """Presents one already-read snapshot to ``classify_startup_transaction``."""

    def __init__(self, snapshot: Optional[RestartTransaction]) -> None:
        self._snapshot = snapshot

    def inspect(self) -> Optional[RestartTransaction]:
        return self._snapshot


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_frozen_manifest(path: str) -> FrozenBuildManifest:
    with open(path, "r", encoding="utf-8") as handle:
        return FrozenBuildManifest.from_json(handle.read())


def _safe_id(value: object) -> str:
    return value if isinstance(value, str) and _ADDON_ID.fullmatch(value) else ""


def _safe_status_code(value: object) -> str:
    return value if isinstance(value, str) and _STATUS_CODE.fullmatch(value) else ""


def _clean_name(value: object) -> str:
    """Plain, bounded text only; control, format and Kodi-markup characters become spaces."""
    if not isinstance(value, str):
        return ""
    cleaned = "".join(ch if is_plain_name(ch) else " " for ch in value).strip()[:64]
    return cleaned if is_plain_name(cleaned) else ""


def _worst(a: SoftwareItemState, b: SoftwareItemState) -> SoftwareItemState:
    return a if _ITEM_SEVERITY.index(a) <= _ITEM_SEVERITY.index(b) else b


def _project_resolutions(
    desired: ResolvedBuild, records: Tuple[InstallResolutionRecord, ...]
) -> Tuple[ResolvedBuild, frozenset]:
    """Drop add-ons the install recorded as an accepted skip from the managed set."""
    skipped = frozenset(
        record.addon_id for record in records if record.resolution is InstallResolution.SKIPPED
    )
    if not skipped:
        return desired, skipped
    return replace(desired, addons=tuple(
        addon for addon in desired.addons if addon.addon_id not in skipped
    )), skipped


project_resolutions = _project_resolutions
clean_name = _clean_name


def _unavailable_areas() -> Tuple[SoftwareStatus, SkinStatus, ConfigurationStatus, PrivateStatus]:
    return (
        SoftwareStatus(AreaLevel.UNAVAILABLE),
        SkinStatus(AreaLevel.UNAVAILABLE),
        ConfigurationStatus(AreaLevel.UNAVAILABLE),
        PrivateStatus(AreaLevel.UNAVAILABLE),
    )


def combine_overall(
    build_selected: bool, levels: Dict[StatusArea, AreaLevel], operation: OperationStatus
) -> OverallStatus:
    """The documented precedence; shared so tests pin it independently."""
    if operation.kind is OperationKind.NEEDS_ATTENTION:
        return OverallStatus.NEEDS_ATTENTION
    if operation.kind is OperationKind.RESTART_REQUIRED:
        return OverallStatus.RESTART_REQUIRED
    if any(level is AreaLevel.CHANGES_NEEDED for level in levels.values()):
        return OverallStatus.CHANGES_NEEDED
    if (
        not build_selected
        or operation.kind is OperationKind.UNAVAILABLE
        or any(level is AreaLevel.UNAVAILABLE for level in levels.values())
        or not any(level is AreaLevel.CURRENT for level in levels.values())
    ):
        return OverallStatus.INCOMPLETE      # includes a build that lists nothing to compare
    return OverallStatus.CURRENT


class BuildStatusService:
    """Performs one fresh, read-only check per ``check()`` call."""

    def __init__(self, owners: StatusOwners) -> None:
        self._o = owners

    # -- public ---------------------------------------------------------

    def check(self, target: Optional[StatusTarget] = None) -> BuildStatus:
        """Never raises and never mutates; failures become ``INCOMPLETE``."""
        try:
            return self._check(target)
        except Exception as exc:
            self._log_failure("check", exc)
            return self._failed_status()

    def _check(self, target: Optional[StatusTarget]) -> BuildStatus:
        checked_at = self._timestamp()
        gaps: List[CheckGap] = []
        try:
            operation = self._operation(gaps)
        except Exception as exc:
            self._log_failure("operation", exc)
            operation = OperationStatus(OperationKind.UNAVAILABLE,
                                        OperationCode.TRANSACTION_UNREADABLE)
            gaps.append(CheckGap.OPERATION_STATE_UNAVAILABLE)
        if target is None:
            software, skin, configuration, private = _unavailable_areas()
            gaps.append(CheckGap.NO_BUILD_SELECTED)
        else:
            try:
                software, skin, configuration, private = self._check_target(target, gaps)
            except Exception as exc:
                self._log_failure("target", exc)
                software, skin, configuration, private = _unavailable_areas()
                gaps.append(CheckGap.INSPECTION_FAILED)
        levels = {
            StatusArea.SOFTWARE: software.level,
            StatusArea.SKIN: skin.level,
            StatusArea.CONFIGURATION: configuration.level,
            StatusArea.PRIVATE: private.level,
        }
        if target is not None and all(l is AreaLevel.NOT_APPLICABLE for l in levels.values()):
            gaps.append(CheckGap.NOTHING_TO_COMPARE)    # a build that lists nothing proves nothing
        overall = combine_overall(target is not None, levels, operation)
        status = BuildStatus(
            overall=overall,
            checked_at=checked_at,
            build_selected=target is not None,
            software=software,
            skin=skin,
            configuration=configuration,
            private=private,
            operation=operation,
            gaps=tuple(dict.fromkeys(gaps)) if overall is not OverallStatus.CURRENT else (),
        )
        self._log("Build Status check: " + status.overall.value)
        return status

    def _failed_status(self) -> BuildStatus:
        software, skin, configuration, private = _unavailable_areas()
        return BuildStatus(
            overall=OverallStatus.INCOMPLETE, checked_at=self._timestamp(),
            build_selected=False, software=software, skin=skin, configuration=configuration,
            private=private,
            operation=OperationStatus(OperationKind.UNAVAILABLE, OperationCode.TRANSACTION_UNREADABLE),
            gaps=(CheckGap.INSPECTION_FAILED,),
        )

    def _timestamp(self) -> str:
        try:
            return self._o.clock()
        except Exception:
            return _utc_now()

    def _log(self, message: str) -> None:
        try:
            self._o.log(message)
        except Exception:
            pass

    # -- operation state --------------------------------------------------

    def _operation(self, gaps: List[CheckGap]) -> OperationStatus:
        if self._o.publication_snapshot is not None:
            try:
                if self._o.publication_snapshot() is not None:
                    return OperationStatus(OperationKind.NEEDS_ATTENTION,
                                           OperationCode.OPERATION_NOT_FINISHED,
                                           "APPLIED_PUBLICATION_PENDING",
                                           protection_active=self._frozen_operation()[1])
            except Exception:
                return OperationStatus(OperationKind.NEEDS_ATTENTION,
                                       OperationCode.TRANSACTION_INVALID,
                                       "APPLIED_PUBLICATION_INVALID",
                                       protection_active=self._frozen_operation()[1])
        restart = self._restart_operation()
        frozen = self._frozen_operation()
        protection = frozen[1]
        operations = (restart, frozen[0])
        for kind in (OperationKind.NEEDS_ATTENTION, OperationKind.RESTART_REQUIRED,
                     OperationKind.UNAVAILABLE):
            chosen = next((op for op in operations if op.kind is kind), None)
            if chosen is not None:
                if kind is OperationKind.UNAVAILABLE:
                    gaps.append(CheckGap.OPERATION_STATE_UNAVAILABLE)
                return replace(chosen, protection_active=protection)
        return OperationStatus(protection_active=protection)

    def _restart_operation(self) -> OperationStatus:
        try:
            snapshot = self._o.restart_snapshot()
        except TransactionPersistenceError:
            return OperationStatus(OperationKind.UNAVAILABLE, OperationCode.TRANSACTION_UNREADABLE)
        except Exception:
            return OperationStatus(OperationKind.NEEDS_ATTENTION, OperationCode.TRANSACTION_INVALID)
        if snapshot is None:
            return OperationStatus()
        # Without a session identity the restart cannot be proven to have
        # happened, so the durable owner is still waiting for one.
        session = self._o.session_id() or snapshot.originating_kodi_session_id
        status = classify_startup_transaction(session, store=_SnapshotStore(snapshot))
        code = _safe_status_code(status.code)
        classification = status.classification
        if classification is StartupClassification.SAME_SESSION_AWAITING_RESTART:
            return OperationStatus(OperationKind.RESTART_REQUIRED, OperationCode.AWAITING_RESTART, code)
        if classification is StartupClassification.READY_FOR_RESUME:
            return OperationStatus(OperationKind.NEEDS_ATTENTION, OperationCode.RESUME_PENDING, code)
        if classification is StartupClassification.NEEDS_ATTENTION:
            return OperationStatus(OperationKind.NEEDS_ATTENTION,
                                   OperationCode.OPERATION_NOT_FINISHED, code)
        return OperationStatus(OperationKind.NEEDS_ATTENTION, OperationCode.TRANSACTION_INVALID, code)

    def _frozen_operation(self) -> Tuple[OperationStatus, bool]:
        try:
            transaction = self._o.frozen_snapshot()
        except FrozenInstallStateUnreadable:
            return OperationStatus(OperationKind.UNAVAILABLE, OperationCode.TRANSACTION_UNREADABLE), False
        except Exception:
            return OperationStatus(OperationKind.NEEDS_ATTENTION, OperationCode.TRANSACTION_INVALID), False
        if transaction is None:
            return OperationStatus(), False
        protection = bool(transaction.activation_hold_ids) and not transaction.activation_hold_released
        code = _safe_status_code(transaction.status_code)
        if transaction.phase is FrozenInstallPhase.AWAITING_RESTART:
            session = self._o.session_id() or transaction.originating_kodi_session_id
            if transaction.originating_kodi_session_id == session:
                return OperationStatus(OperationKind.RESTART_REQUIRED,
                                       OperationCode.AWAITING_RESTART, code), protection
            return OperationStatus(OperationKind.NEEDS_ATTENTION,
                                   OperationCode.RESUME_PENDING, code), protection
        return OperationStatus(OperationKind.NEEDS_ATTENTION,
                               OperationCode.OPERATION_NOT_FINISHED, code), protection

    # -- selected build -----------------------------------------------------

    def _check_target(self, target: StatusTarget, gaps: List[CheckGap]):
        o = self._o
        try:
            config_loader = o.config_loader
            if target.library_source is not None:
                manifest, frozen, config_loader = target.library_source.load()
            else:
                manifest = o.manifest_loader(target.configuration_manifest_path)
                frozen = (
                    o.frozen_manifest_loader(target.software_manifest_path)
                    if target.software_manifest_path else None
                )
            desired = o.resolver(manifest, target.device_profile_id)
        except Exception as exc:
            self._log_failure("build", exc)
            gaps.append(CheckGap.BUILD_UNREADABLE)
            return _unavailable_areas()

        # The inputs must describe one build before any of them is used. A frozen
        # graph or install record that does not belong to the selected build makes
        # the whole comparison target invalid: nothing is verified against it.
        try:
            if frozen is not None:
                check_frozen_identity(desired.build.id, frozen)
            records = bind_resolutions(desired.build.id, frozen, target.install_resolution,
                                       policies=desired.frozen_install_policies)
            desired, skipped = _project_resolutions(desired, records)
        except IdentityMismatch as exc:
            self._log("Build Status check rejected the selected build's inputs (%s)" % exc.code.value)
            gaps.append(
                CheckGap.BUILD_IDENTITY_MISMATCH if exc.code is IdentityCode.FROZEN_BUILD_MISMATCH
                else CheckGap.RESOLUTION_IDENTITY_MISMATCH
            )
            return _unavailable_areas()
        except Exception as exc:
            self._log_failure("build", exc)
            gaps.append(CheckGap.BUILD_UNREADABLE)
            return _unavailable_areas()

        try:
            actual = o.inspector.inspect()
        except Exception as exc:
            self._log_failure("kodi", exc)
            actual = None
            gaps.append(CheckGap.KODI_STATE_UNAVAILABLE)

        if actual is None:
            software, skin, configuration = (
                SoftwareStatus(AreaLevel.UNAVAILABLE),
                SkinStatus(AreaLevel.UNAVAILABLE),
                ConfigurationStatus(AreaLevel.UNAVAILABLE),
            )
        else:
            software, skin, configuration = self._check_kodi_areas(
                records, desired, frozen, skipped, actual, gaps, config_loader
            )
        try:
            private = self._check_private(desired, frozen, gaps)
        except Exception as exc:
            self._log_failure("private", exc)
            gaps.append(CheckGap.PRIVATE_UNAVAILABLE)
            private = PrivateStatus(AreaLevel.UNAVAILABLE)
        return software, skin, configuration, private

    def _check_kodi_areas(self, records, desired, frozen, skipped, actual: KodiState, gaps, config_loader):
        o = self._o
        actual_map = {addon.addon_id: addon for addon in actual.addons}

        # Frozen software graph: exact version and enabled state per managed node.
        items: Dict[str, SoftwareItemState] = {}
        software_unchecked = False
        if frozen is not None:
            # An incomplete capture does not describe a whole build. The installer
            # accepts one only when recorded resolutions covered its gaps.
            if frozen.capture_status is not CaptureStatus.COMPLETE and not (
                frozen.capture_status is CaptureStatus.INCOMPLETE_ARTIFACT and records
            ):
                software_unchecked = True
            resolved = {record.addon_id: record for record in records}
            for node in frozen.addons:
                if node.system or node.is_absent_optional_dependency or node.addon_id in skipped:
                    continue
                record = resolved.get(node.addon_id)
                version = (record.resolved_version if record is not None else "") or node.version
                enabled = record.desired_enabled if record is not None else node.desired_enabled
                installed = actual_map.get(node.addon_id)
                if installed is None:
                    state = SoftwareItemState.MISSING
                elif (node.status is not CaptureStatus.COMPLETE and record is None) or not version \
                        or not installed.version:
                    state = SoftwareItemState.UNCHECKABLE
                elif installed.version != version:
                    state = SoftwareItemState.WRONG_VERSION
                elif installed.enabled is not enabled:
                    state = SoftwareItemState.WRONG_ENABLED_STATE
                else:
                    state = SoftwareItemState.CURRENT
                items[node.addon_id] = state

        # BM-014 validation of the resolved build manifest (add-ons, repositories,
        # dependencies, skin, configuration) over fresh, read-only evidence.
        closure = None
        roots = sorted(a.addon_id for a in desired.addons if a.state == "enabled")
        if roots:
            try:
                closure = o.dependency_resolver.resolve_closure(roots, require_root_metadata=True)
            except Exception as exc:
                self._log_failure("dependencies", exc)
        effective = None
        inspection = None
        if desired.config is not None:
            try:
                effective = config_loader.resolve(desired.config)
                inspection = o.configuration_inspector.inspect(effective)
            except Exception as exc:
                self._log_failure("configuration", exc)
                effective = inspection = None
        report = validate_build_state(
            desired, actual, closure,
            inspection.validation_state if inspection is not None else None,
            effective,
        )
        closure_nodes = {}
        for node in (closure.nodes if closure is not None else ()):
            # primary nodes precede cycle back-edge nodes; the primary state wins
            closure_nodes.setdefault(node.addon_id, node)
        for check in report.checks:
            if check.domain in (ValidationDomain.REPOSITORY, ValidationDomain.ADDON,
                                ValidationDomain.DEPENDENCY):
                if check.status is ValidationStatus.NOT_CHECKED:
                    software_unchecked = True
                    continue
                addon_id = _safe_id(check.subject)
                if not addon_id:
                    software_unchecked = True
                    continue
                if addon_id in skipped:
                    continue          # an accepted skip is not part of the managed set
                if check.status is ValidationStatus.FAIL:
                    state = self._failed_state(check.domain, addon_id, actual_map, closure_nodes)
                elif check.status is ValidationStatus.PASS:
                    state = SoftwareItemState.CURRENT
                else:
                    continue
                items[addon_id] = _worst(items[addon_id], state) if addon_id in items else state

        software = self._software_status(
            items, software_unchecked, bool(frozen is not None or desired.addons
                                            or any(r.required for r in desired.repositories))
        )
        skin = self._skin_status(desired, actual, report)
        configuration = self._configuration_status(desired, report, inspection, gaps)
        if software.level is AreaLevel.UNAVAILABLE:
            gaps.append(CheckGap.SOFTWARE_UNAVAILABLE)
        return software, skin, configuration

    @staticmethod
    def _failed_state(domain, addon_id, actual_map, closure_nodes) -> SoftwareItemState:
        installed = actual_map.get(addon_id)
        if domain is ValidationDomain.DEPENDENCY:
            node = closure_nodes.get(addon_id)
            status = node.status if node is not None else None
            if status is DependencyStatus.VERSION_INSUFFICIENT:
                return SoftwareItemState.WRONG_VERSION
            if status is DependencyStatus.INSTALLED_DISABLED:
                return SoftwareItemState.WRONG_ENABLED_STATE
            if status is DependencyStatus.MISSING or installed is None:
                return SoftwareItemState.MISSING
            return SoftwareItemState.UNCHECKABLE
        return SoftwareItemState.MISSING if installed is None else SoftwareItemState.WRONG_ENABLED_STATE

    def _software_status(self, items, unchecked: bool, applicable: bool) -> SoftwareStatus:
        resolve = self._o.name_resolver
        built = []
        for addon_id in sorted(items):
            name = ""
            if resolve is not None:
                try:
                    name = _clean_name(resolve(addon_id))
                except Exception:
                    name = ""
            built.append(SoftwareItem(addon_id, items[addon_id], name))
        if any(item.state in _DRIFT_STATES for item in built):
            level = AreaLevel.CHANGES_NEEDED
        elif unchecked or any(item.state is SoftwareItemState.UNCHECKABLE for item in built):
            level = AreaLevel.UNAVAILABLE
        elif built or applicable:
            level = AreaLevel.CURRENT
        else:
            level = AreaLevel.NOT_APPLICABLE
        return SoftwareStatus(level, tuple(built))

    @staticmethod
    def _skin_status(desired: ResolvedBuild, actual: KodiState, report) -> SkinStatus:
        current = _safe_id(actual.active_skin)
        if desired.skin is None:
            return SkinStatus(AreaLevel.NOT_APPLICABLE, "", current, None)
        expected = _safe_id(desired.skin.addon_id)
        checks = [c for c in report.checks if c.domain is ValidationDomain.SKIN]
        if any(c.status is ValidationStatus.FAIL for c in checks):
            skin_installed = any(a.addon_id == desired.skin.addon_id for a in actual.addons)
            if not current and skin_installed:
                # Kodi did not name the active skin, so "a different skin is
                # active" is not proven.
                return SkinStatus(AreaLevel.UNAVAILABLE, expected, current, None)
            return SkinStatus(AreaLevel.CHANGES_NEEDED, expected, current, False)
        if checks and all(c.status is ValidationStatus.PASS for c in checks):
            return SkinStatus(AreaLevel.CURRENT, expected, current, True)
        return SkinStatus(AreaLevel.UNAVAILABLE, expected, current, None)

    @staticmethod
    def _configuration_status(desired, report, inspection, gaps) -> ConfigurationStatus:
        if desired.config is None:
            return ConfigurationStatus(AreaLevel.NOT_APPLICABLE)
        checks = [c for c in report.checks if c.domain is ValidationDomain.CONFIGURATION]
        if inspection is None or any(c.status is ValidationStatus.NOT_CHECKED for c in checks):
            gaps.append(CheckGap.CONFIGURATION_UNAVAILABLE)
            return ConfigurationStatus(AreaLevel.UNAVAILABLE)
        counts = dict(total=inspection.total, differing=inspection.differing,
                      unreadable=inspection.unreadable)
        if inspection.differing:
            return ConfigurationStatus(AreaLevel.CHANGES_NEEDED, **counts)
        if inspection.unreadable:
            gaps.append(CheckGap.CONFIGURATION_UNAVAILABLE)
            return ConfigurationStatus(AreaLevel.UNAVAILABLE, **counts)
        if any(c.status is ValidationStatus.FAIL for c in checks):
            return ConfigurationStatus(AreaLevel.CHANGES_NEEDED, **counts)
        return ConfigurationStatus(AreaLevel.CURRENT, **counts)

    # -- private data ---------------------------------------------------------

    def _check_private(self, desired: ResolvedBuild, frozen, gaps: List[CheckGap]) -> PrivateStatus:
        return self._inspect_private(desired, frozen, gaps)[0]

    def inspect_private(
        self, desired: ResolvedBuild, frozen, gaps: List[CheckGap],
        pending_owners: frozenset = frozenset(),
    ) -> Tuple[PrivateStatus, str]:
        """Private-data status plus the overlay's secret-blind fingerprint (or "").

        ``pending_owners`` names add-ons that are not installed yet. Their
        private data cannot be inspected, and applying it is certain, so it
        counts as "changes needed" instead of "unavailable". Status itself never
        passes any: an owner that is missing there is a gap, not a plan.
        """
        return self._inspect_private(desired, frozen, gaps, pending_owners)

    def inspect_operation(self, gaps: List[CheckGap]) -> OperationStatus:
        """Durable restart / needs-attention state, read without locks or creation."""
        return self._operation(gaps)

    def _inspect_private(
        self, desired: ResolvedBuild, frozen, gaps: List[CheckGap],
        pending: frozenset = frozenset(),
    ) -> Tuple[PrivateStatus, str]:
        o = self._o
        config = desired.config
        setting_declarations = config.private_settings if config is not None else ()
        resource_declarations = config.structured_private_resources if config is not None else ()
        reference = desired.private_overlay
        any_required = (
            (reference is not None and reference.required)
            or any(item.required for item in setting_declarations)
            or any(item.required for item in resource_declarations)
        )
        if reference is None and not setting_declarations and not resource_declarations:
            return PrivateStatus(AreaLevel.NOT_APPLICABLE), ""
        if reference is None:
            return self._private_unavailable(CheckGap.PRIVATE_DATA_MISSING, gaps) if any_required \
                else (PrivateStatus(AreaLevel.NOT_APPLICABLE), "")
        if reference.type != "local_file" or not (setting_declarations or resource_declarations):
            # Same conditions under which applying the overlay refuses to start.
            return self._private_unavailable(CheckGap.PRIVATE_DATA_UNUSABLE, gaps)
        try:
            overlay = o.overlay_loader(reference.overlay_id)
        except PrivateOverlayMissingError:
            return self._private_unavailable(CheckGap.PRIVATE_DATA_MISSING, gaps) if any_required \
                else (PrivateStatus(AreaLevel.NOT_APPLICABLE), "")
        except Exception as exc:
            self._log_failure("private-load", exc)
            return self._private_unavailable(CheckGap.PRIVATE_DATA_UNUSABLE, gaps)
        try:
            source_fingerprint = frozen.fingerprint() if frozen is not None else ""
            validate_private_overlay(
                overlay, setting_declarations,
                expected_build_id=desired.build.id if not source_fingerprint else "",
                expected_source_software_fingerprint=source_fingerprint,
                expected_overlay_id=reference.overlay_id,
                resource_declarations=resource_declarations,
            )
        except Exception as exc:
            self._log_failure("private-validate", exc)
            return self._private_unavailable(CheckGap.PRIVATE_DATA_UNUSABLE, gaps)

        items: List[PrivateItem] = []
        if overlay.entries:
            live = tuple(entry for entry in overlay.entries if entry.addon_id not in pending)
            waiting = len(live) != len(overlay.entries)
            level = AreaLevel.CURRENT
            if live:
                settings = tuple(
                    ConfigSetting(
                        addon_id=entry.addon_id, key=entry.key, setting_type=entry.setting_type,
                        value=entry.value, package_id="private-overlay",
                        target_kind=entry.target_kind,
                    )
                    for entry in live
                )
                result = o.configuration_inspector.inspect_settings(
                    settings, effective_identity=overlay.fingerprint
                )
                level = (
                    AreaLevel.UNAVAILABLE if result.unreadable
                    else AreaLevel.CHANGES_NEEDED if result.differing else AreaLevel.CURRENT
                )
            if waiting and level is not AreaLevel.UNAVAILABLE:
                level = AreaLevel.CHANGES_NEEDED
            items.append(PrivateItem("private-settings", PrivateItemKind.SETTINGS, level))
        if resource_declarations:
            levels = {
                ResourceCheckStatus.CURRENT: AreaLevel.CURRENT,
                ResourceCheckStatus.CHANGES_NEEDED: AreaLevel.CHANGES_NEEDED,
                ResourceCheckStatus.UNAVAILABLE: AreaLevel.UNAVAILABLE,
            }
            live_declarations = tuple(
                item for item in resource_declarations if item.owner_addon_id not in pending
            )
            for item in resource_declarations:
                if item.owner_addon_id in pending:
                    items.append(PrivateItem(item.resource_id, PrivateItemKind.RESOURCE,
                                             AreaLevel.CHANGES_NEEDED))
            if live_declarations:
                for check in o.resource_manager().inspect(live_declarations, overlay.resources):
                    items.append(PrivateItem(
                        check.resource_id, PrivateItemKind.RESOURCE, levels[check.status]
                    ))
        if any(item.level is AreaLevel.UNAVAILABLE for item in items):
            gaps.append(CheckGap.PRIVATE_UNAVAILABLE)
            return PrivateStatus(AreaLevel.UNAVAILABLE, tuple(items)), overlay.fingerprint
        if any(item.level is AreaLevel.CHANGES_NEEDED for item in items):
            return PrivateStatus(AreaLevel.CHANGES_NEEDED, tuple(items)), overlay.fingerprint
        return (PrivateStatus(AreaLevel.CURRENT if items else AreaLevel.NOT_APPLICABLE, tuple(items)),
                overlay.fingerprint)

    @staticmethod
    def _private_unavailable(gap: CheckGap, gaps: List[CheckGap]) -> Tuple[PrivateStatus, str]:
        gaps.append(gap)
        return PrivateStatus(AreaLevel.UNAVAILABLE), ""

    # -- logging ----------------------------------------------------------------

    def _log_failure(self, phase: str, exc: BaseException) -> None:
        """Log the phase and exception class only; never message text or values."""
        self._log("Build Status check could not complete %s (%s)" % (
            phase, type(exc).__name__))


# ---------------------------------------------------------------------------
# Production wiring
# ---------------------------------------------------------------------------

def _runtime_profile_root() -> str:
    import xbmcvfs
    return xbmcvfs.translatePath("special://profile/")


def _resolve_installed_addon_name(addon_id: str) -> str:
    """Read an installed add-on's name, including when it is disabled.

    ``xbmcaddon.Addon(id)`` rejects disabled add-ons in the supported Kodi
    runtime. Addons.GetAddonDetails is a read-only JSON-RPC lookup that accepts
    installed disabled add-ons as well. Keep Kodi modules lazy so this owner is
    still constructible in offline tools and tests.
    """
    addon_id = _safe_id(addon_id)
    if not addon_id:
        return ""
    try:
        import json  # noqa: PLC0415
        import xbmc  # noqa: PLC0415

        request = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.GetAddonDetails",
            "params": {"addonid": addon_id, "properties": ["name"]},
            "id": 1,
        })
        response = json.loads(xbmc.executeJSONRPC(request))
    except Exception:
        return ""

    if not isinstance(response, dict):
        return ""
    result = response.get("result")
    addon = result.get("addon") if isinstance(result, dict) else None
    if not isinstance(addon, dict) or addon.get("addonid") != addon_id:
        return ""
    name = addon.get("name")
    return name if isinstance(name, str) else ""


def default_status_owners(*, log: Optional[Callable[[str], None]] = None) -> StatusOwners:
    """Production read-only collaborators, constructed without touching Kodi state."""
    # Imported here: the adapter module is only needed when a build declares it.
    def resource_manager() -> StructuredPrivateResourceManager:
        from resources.lib.redlight_resource import RedLightSettingsAdapter
        adapter = RedLightSettingsAdapter(_runtime_profile_root())
        return StructuredPrivateResourceManager({adapter.adapter_id: adapter})

    store: Dict[str, PrivateOverlayStore] = {}

    def load_overlay(overlay_id: str) -> PrivateOverlay:
        if "store" not in store:
            store["store"] = PrivateOverlayStore()
        return store["store"].read_snapshot(overlay_id)

    from resources.lib.build_library import default_build_library
    restart_store = TransactionStore()
    return StatusOwners(
        inspector=KodiStateInspector(KodiRuntimeBackend()),
        manifest_loader=load_manifest_file,
        resolver=resolve_manifest,
        frozen_manifest_loader=_load_frozen_manifest,
        config_loader=ConfigPackageLoader(default_packages_root()),
        configuration_inspector=ConfigurationInspector(
            ReadOnlyConfigurationBackend(KodiRuntimeConfigurationBackend())
        ),
        dependency_resolver=DependencyResolver(
            _ReadOnlyDependencyBackend(KodiRuntimeDependencyBackend())
        ),
        overlay_loader=load_overlay,
        resource_manager=resource_manager,
        restart_snapshot=restart_store.read_snapshot,
        frozen_snapshot=FrozenInstallStore.read_snapshot,
        session_id=peek_current_kodi_session_id,
        clock=_utc_now,
        log=log or (lambda message: None),
        name_resolver=_resolve_installed_addon_name,
        publication_snapshot=lambda: default_build_library().pending_publication(),
    )


def default_status_target() -> Optional[StatusTarget]:
    """The verified associated library build, or ``None``; no selection fallback."""
    from resources.lib.build_library import default_build_library
    try:
        return default_build_library().associated_status_target()
    except Exception:
        return None


def _presentation_identifiers(library, applied):
    """Stored values that must never appear inside a shown build name.

    Entry IDs, resolution fingerprints and publication transaction IDs are matched
    as substrings. Build IDs are matched only as a whole name. Every lookup is
    read-only, and a failed lookup contributes nothing.
    """
    identifiers, exact = set(), set()
    try:
        for entry in library.list_builds():
            identifiers.add(entry.entry_id)
            exact.add(entry.build_id)
    except Exception:
        pass
    if applied is not None:
        identifiers.add(applied.resolution_fingerprint)
    try:
        journal = library.publication_journal()
    except Exception:
        journal = None
    if journal is not None:
        identifiers.add(journal.transaction_id)
        for association in (journal.candidate, journal.previous):
            if association is not None:
                identifiers.update((association.entry_id, association.resolution_fingerprint))
    return frozenset(identifiers), frozenset(exact)


def _identity(entry, profile, identifiers, exact):
    """A valid build always yields an identity. Only its display name can fall back."""
    name = build_display_name(entry.display_name, identifiers=identifiers, exact=exact)
    return BuildIdentity(name, entry.build_version, profile)


def build_presentation(library, target: Optional[StatusTarget]) -> BuildPresentation:
    """Applied and saved-selection identities for display. Never a comparison input.

    ``target`` is the verified applied association, the same authority the health
    check uses; it alone decides what counts as applied. The saved selection is
    read separately, read-only, and shown only as context. A build that cannot be
    read is reported as unreadable, with no internal detail. A build that can be
    read but has an unsafe display name keeps its identity and shows the neutral
    name fallback.
    """
    applied = None
    applied_unreadable = False
    applied_key = None
    applied_association = None
    if target is not None:
        applied_association = target.applied_association
        if applied_association is None:
            raise ValueError("presentation needs the verified applied association")
        applied_key = (applied_association.entry_id, target.device_profile_id)
    identifiers, exact = _presentation_identifiers(library, applied_association)
    if target is not None:
        try:
            entry = library.get(applied_association.entry_id)
            applied = _identity(entry, target.device_profile_id, identifiers, exact)
        except Exception:
            applied_unreadable = True
    selected = None
    selection_unreadable = False
    state, saved = library.selection_state()
    if state == "invalid":
        selection_unreadable = True
    elif state == "selected" and (saved.entry_id, saved.device_profile_id) != applied_key:
        try:
            entry = library.get(saved.entry_id)
            if saved.device_profile_id not in entry.device_profiles:
                raise ValueError("selection profile is not in the build")
            selected = _identity(entry, saved.device_profile_id, identifiers, exact)
        except Exception:
            selection_unreadable = True
    return BuildPresentation(applied, applied_unreadable, selected, selection_unreadable)


def default_build_presentation(target: Optional[StatusTarget]) -> BuildPresentation:
    """Production presentation. If an applied build exists but cannot be named, say so.

    Without a verified applied association the page says nothing was applied,
    which is the status engine's own statement. A selection that cannot be read
    is never shown as selected.
    """
    from resources.lib.build_library import default_build_library
    try:
        return build_presentation(default_build_library(), target)
    except Exception:
        return BuildPresentation(applied_unreadable=target is not None)


def check_build_status(*, log: Optional[Callable[[str], None]] = None) -> BuildStatus:
    """One fresh read-only check of this device, for the Build Status route.

    Health is evaluated only against the verified applied association. The
    presentation adds the applied and saved-selection identities for display.
    """
    target = default_status_target()
    status = BuildStatusService(default_status_owners(log=log)).check(target)
    return replace(status, presentation=default_build_presentation(target))
