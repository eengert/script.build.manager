"""Read-only frozen-build plan and review service (BM-UI-002C / G3).

``BuildPlanService.preview()`` answers, from a fresh read of Kodi and Build
Manager state: what would an install of this exact frozen build change, what
would stay as it is, what needs the user's decision, and what is blocked.
``validate()`` answers whether a plan the user already reviewed is still the
plan: it re-reads everything the plan depends on and compares the result with
the reviewed identity. Neither applies, installs, enables, repairs, downloads,
or writes anything.

The plan is derived from existing owners; it makes no installer decision of its
own beyond mirroring, before any mutation, the conditions under which the
installer would refuse or fail:

* artifact availability, recovery policy and the missing-package choices come
  from ``summarize_frozen_recoverability`` / ``validate_frozen_install_plan``;
* what happens after software is staged (skin, add-ons the build manages but
  did not freeze) comes from the pure BM-006 ``plan_changes`` over the state the
  software stage would leave behind;
* settings, private data, and pending-operation state come from the same
  read-only views Build Status uses;
* the exact installer cannot replace a different installed version or repair a
  broken installation (G6 is not built), so those cases are reported as
  ``BLOCKED`` here instead of failing after the updater guard is engaged.

Read-only is structural: this module imports no installer, reconciler, skin
activator, updater-policy setter, or configuration/private-resource applier,
reaches the saved-package store only through a subclass that creates nothing,
and reads Kodi only through the status owners and one add-on-details accessor.

An unresolved repository-current choice produces RESOLUTION_REQUIRED with no
review identity. A later authorized resolution stage must save the exact
package before a new preview and review. Bound saved repository packages use
the installer's read-only dependency reconstruction; preview never downloads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from resources.lib.artifacts import ArtifactStore, validate_addon_zip
from resources.lib.build_identity import (
    IdentityCode,
    IdentityMismatch,
    bind_resolutions,
    check_frozen_identity,
)
from resources.lib.build_manager import fingerprint_resolved_build
from resources.lib.build_library import LibrarySource
from resources.lib.config import ConfigTargetCheck
from resources.lib.frozen import FrozenBuildManifest
from resources.lib.frozen_install import (
    FrozenInstalledAddon,
    KodiRuntimeFrozenArtifactBackend,
    default_frozen_install_root,
    validate_frozen_install_plan,
    stored_repository_dependencies,
)
from resources.lib.frozen_resolution import (
    FrozenInstallResolutionManifest,
    InstallResolution,
    InstallResolutionRecord,
    ResolutionState,
    install_plan_fingerprint,
    policy_fingerprint,
    summarize_frozen_recoverability,
)
from resources.lib.inspector import InstalledAddon, KodiState
from resources.lib.plan_model import (
    BLOCKING_ACTIONS,
    CHANGE_ACTIONS,
    BlockerCode,
    BuildPlan,
    DecisionChoice,
    IdentityComponent,
    PlanBlocker,
    PlanState,
    PrivatePlan,
    PrivatePlanKind,
    RestartExpectation,
    RestartPlan,
    ReviewCheck,
    ReviewFreshness,
    ReviewIdentity,
    SettingsPlan,
    SettingsPlanKind,
    SkinPlan,
    SkinPlanKind,
    SoftwareAction,
    SoftwareRow,
)
from resources.lib.planner import (
    DISABLE_ADDON,
    ENABLE_ADDON,
    INSTALL_ADDON,
    INSTALL_REPOSITORY,
    PlanningError,
    plan_changes,
)
from resources.lib.private_overlay import validate_private_overlay_resolution_compatibility
from resources.lib.resolver import ResolvedBuild
from resources.lib.status import (
    BuildStatusService,
    StatusOwners,
    clean_name,
    default_status_owners,
    project_resolutions,
)
from resources.lib.status_model import (
    AreaLevel,
    CheckGap,
    OperationCode,
    OperationKind,
    OperationStatus,
)

_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~:-]{0,63}$")
_PRIVATE_GAPS = {
    CheckGap.PRIVATE_DATA_MISSING: BlockerCode.PRIVATE_DATA_MISSING,
    CheckGap.PRIVATE_DATA_UNUSABLE: BlockerCode.PRIVATE_DATA_UNUSABLE,
}
_PRIVATE_KIND = {
    AreaLevel.CURRENT: PrivatePlanKind.CURRENT,
    AreaLevel.CHANGES_NEEDED: PrivatePlanKind.CHANGES_NEEDED,
    AreaLevel.UNAVAILABLE: PrivatePlanKind.UNAVAILABLE,
    AreaLevel.NOT_APPLICABLE: PrivatePlanKind.NOT_USED,
}


# ---------------------------------------------------------------------------
# Target and owners
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanTarget:
    """Everything the user selected. Paths never reach the result.

    ``install_resolution`` is a prior accepted install outcome, trusted only
    when it is bound to this exact build and frozen manifest. ``choices`` are the
    user's answers to missing-package decisions; they are part of the plan's
    identity, so changing one makes an earlier review stale.

    ``library_source`` supplies one revalidated library-owned snapshot including
    configuration packages. Its effective content still participates in the
    accepted build/review fingerprint; no path substitutes for build identity.
    """

    configuration_manifest_path: str
    device_profile_id: str
    software_manifest_path: str
    install_resolution: Optional[FrozenInstallResolutionManifest] = None
    choices: Tuple[Tuple[str, DecisionChoice], ...] = ()
    library_source: Optional[LibrarySource] = None

    def __post_init__(self) -> None:
        if self.library_source is not None and not isinstance(self.library_source, LibrarySource):
            raise ValueError("library_source must be a LibrarySource")
        for name in ("configuration_manifest_path", "device_profile_id", "software_manifest_path"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError("%s must be a non-empty string" % name)
        if self.install_resolution is not None and not isinstance(
            self.install_resolution, FrozenInstallResolutionManifest
        ):
            raise ValueError("install_resolution must be an install resolution manifest")
        if not isinstance(self.choices, tuple) or any(
            not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)
                 and _ADDON_ID.fullmatch(item[0]) and isinstance(item[1], DecisionChoice))
            for item in self.choices
        ):
            raise ValueError("choices must be (add-on ID, DecisionChoice) pairs")
        if len({addon_id for addon_id, _ in self.choices}) != len(self.choices):
            raise ValueError("choices must not repeat an add-on")
        object.__setattr__(self, "choices", tuple(sorted(self.choices, key=lambda item: item[0])))

    def with_choice(self, addon_id: str, choice: DecisionChoice) -> "PlanTarget":
        kept = tuple(item for item in self.choices if item[0] != addon_id)
        return replace(self, choices=kept + ((addon_id, choice),))


class ReadOnlyArtifactStore(ArtifactStore):
    """Saved packages, read only. Unlike ``ArtifactStore`` it creates nothing."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.artifacts_dir = self.root / "artifacts"

    def import_zip(self, *args, **kwargs):
        raise RuntimeError("plan inspection is read-only")

    def _publish_metadata(self, *args, **kwargs):
        raise RuntimeError("plan inspection is read-only")


@dataclass(frozen=True)
class PlanOwners:
    """Injectable read-only collaborators."""

    status: StatusOwners                       # Kodi state, build files, configuration, private data
    artifact_store: object                     # artifact_path / metadata_path / get_metadata / read_bytes
    addon_details: Callable[[str], Optional[FrozenInstalledAddon]]   # installed add-on incl. ``broken``


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hold_ids(nodes, desired: ResolvedBuild) -> Tuple[str, ...]:
    """Add-ons the installer holds disabled until pre-activation resources are configured."""
    config = desired.config
    declarations = tuple(
        item for item in (config.structured_private_resources if config is not None else ())
        if item.configure_before_activation
    )
    if not declarations:
        return ()
    install_ids = {node.addon_id for node in nodes}
    held = {item.owner_addon_id for item in declarations}
    if not held.issubset(install_ids):
        raise ValueError("pre-activation resource owner is not in the frozen software graph")
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if node.addon_id not in held and any(edge.addon_id in held for edge in node.dependency_edges):
                held.add(node.addon_id)
                changed = True
    return tuple(sorted(held))


class _Software:
    """Mutable accumulator for the software stage of one evaluation."""

    def __init__(self) -> None:
        self.rows: Dict[str, SoftwareRow] = {}
        self.skipped: Dict[str, InstallResolutionRecord] = {}
        self.target_version: Dict[str, str] = {}
        self.pending: set = set()               # decisions awaiting the user
        self.repository: set = set()            # add-ons the user chose to install from a repository
        self.install_order: Tuple = ()
        self.hold_ids: Tuple[str, ...] = ()
        self.valid = True


class BuildPlanService:
    """Performs one fresh, read-only plan per ``preview()`` call."""

    def __init__(self, owners: PlanOwners) -> None:
        self._o = owners
        self._status = BuildStatusService(owners.status)

    # -- public ---------------------------------------------------------

    def preview(self, target: PlanTarget) -> BuildPlan:
        """Never raises and never mutates; failures become ``INCOMPLETE``."""
        try:
            plan, material = self._evaluate(target)
            if plan.state is PlanState.CHANGES_READY:
                plan = replace(plan, review=ReviewIdentity.from_material(material))
            self._log("Build plan: " + plan.state.value)
            return plan
        except Exception as exc:
            self._log_failure("preview", exc)
            return self._failed_plan()

    def validate(self, target: PlanTarget, review: ReviewIdentity) -> ReviewCheck:
        """Is ``review`` still what would happen? Re-reads everything the plan depends on.

        Anything but an exact match requires a new preview and a new review.
        """
        try:
            if not isinstance(review, ReviewIdentity):
                return ReviewCheck(ReviewFreshness.UNVERIFIABLE)
            plan, material = self._evaluate(target)
            if plan.state is PlanState.INCOMPLETE:
                return ReviewCheck(ReviewFreshness.UNVERIFIABLE)
            changed = ReviewIdentity.from_material(material).changed_since(review)
            if changed:
                return ReviewCheck(ReviewFreshness.STALE, changed)
            if plan.state is not PlanState.CHANGES_READY:
                return ReviewCheck(ReviewFreshness.STALE, (IdentityComponent.ACTIONS,))
            return ReviewCheck(ReviewFreshness.CURRENT)
        except Exception as exc:
            self._log_failure("validate", exc)
            return ReviewCheck(ReviewFreshness.UNVERIFIABLE)

    # -- plumbing ----------------------------------------------------------

    def _timestamp(self) -> str:
        try:
            return self._o.status.clock()
        except Exception:
            return _utc_now()

    def _log(self, message: str) -> None:
        try:
            self._o.status.log(message)
        except Exception:
            pass

    def _log_failure(self, phase: str, exc: BaseException) -> None:
        """Phase and exception class only; never message text or values."""
        self._log("Build plan could not complete %s (%s)" % (phase, type(exc).__name__))

    def _name(self, addon_id: str) -> str:
        resolve = self._o.status.name_resolver
        if resolve is None or not addon_id:
            return ""
        try:
            return clean_name(resolve(addon_id))
        except Exception:
            return ""

    @staticmethod
    def _unchecked(now: str, gaps, blockers) -> BuildPlan:
        return BuildPlan(
            state=PlanState.BLOCKED if blockers else PlanState.INCOMPLETE,
            checked_at=now, software=(),
            skin=SkinPlan(SkinPlanKind.UNAVAILABLE),
            settings=SettingsPlan(SettingsPlanKind.UNAVAILABLE),
            private=PrivatePlan(PrivatePlanKind.UNAVAILABLE),
            restart=RestartPlan(),
            blockers=tuple(blockers), gaps=tuple(dict.fromkeys(gaps)),
        )

    def _failed_plan(self) -> BuildPlan:
        return self._unchecked(self._timestamp(), (CheckGap.INSPECTION_FAILED,), ())

    # -- evaluation ---------------------------------------------------------

    def _evaluate(self, target: PlanTarget):
        """One fresh read -> (plan without a review, identity material per component)."""
        o = self._o
        status = o.status
        now = self._timestamp()
        gaps: List[CheckGap] = []
        blockers: List[PlanBlocker] = []
        material: Dict[IdentityComponent, object] = {c: None for c in IdentityComponent}
        material[IdentityComponent.DEVICE] = {"requested": target.device_profile_id}

        try:
            operation = self._status.inspect_operation(gaps)
        except Exception as exc:
            self._log_failure("operation", exc)
            operation = OperationStatus(OperationKind.UNAVAILABLE, OperationCode.TRANSACTION_UNREADABLE)
            gaps.append(CheckGap.OPERATION_STATE_UNAVAILABLE)
        material[IdentityComponent.OPERATION] = [
            operation.kind.value, operation.code.value, operation.protection_active]
        if operation.kind is OperationKind.NEEDS_ATTENTION:
            blockers.append(PlanBlocker(BlockerCode.OPERATION_NEEDS_ATTENTION))
        elif operation.kind is OperationKind.RESTART_REQUIRED:
            blockers.append(PlanBlocker(BlockerCode.OPERATION_PENDING))

        try:
            config_loader = status.config_loader
            if target.library_source is not None:
                manifest, frozen, config_loader = target.library_source.load()
            else:
                manifest = status.manifest_loader(target.configuration_manifest_path)
                frozen = status.frozen_manifest_loader(target.software_manifest_path)
            desired = status.resolver(manifest, target.device_profile_id)
        except Exception as exc:
            self._log_failure("build", exc)
            gaps.append(CheckGap.BUILD_UNREADABLE)
            return self._unchecked(now, gaps, blockers), material

        # The inputs must describe one build before any of them is used.
        try:
            check_frozen_identity(desired.build.id, frozen)
            records = bind_resolutions(desired.build.id, frozen, target.install_resolution,
                                       policies=desired.frozen_install_policies)
        except IdentityMismatch as exc:
            self._log("Build plan rejected the selected build's inputs (%s)" % exc.code.value)
            gaps.append(
                CheckGap.BUILD_IDENTITY_MISMATCH if exc.code is IdentityCode.FROZEN_BUILD_MISMATCH
                else CheckGap.RESOLUTION_IDENTITY_MISMATCH
            )
            return self._unchecked(now, gaps, blockers), material
        except Exception as exc:
            self._log_failure("build", exc)
            gaps.append(CheckGap.BUILD_UNREADABLE)
            return self._unchecked(now, gaps, blockers), material

        effective = None
        if desired.config is not None:
            try:
                effective = config_loader.resolve(desired.config)
            except Exception as exc:
                self._log_failure("configuration", exc)
        try:
            material[IdentityComponent.BUILD] = fingerprint_resolved_build(desired, effective)
            if target.library_source is not None:
                # Entry/root are part of approval even when two sources resolve
                # identically for this profile. Only their digest is public.
                material[IdentityComponent.BUILD] = {
                    "resolved": material[IdentityComponent.BUILD],
                    "library": {"root": target.library_source.root,
                                "entry_id": target.library_source.entry_id},
                }
        except Exception as exc:
            self._log_failure("build-identity", exc)
            gaps.append(CheckGap.BUILD_UNREADABLE)
            return self._unchecked(now, gaps, blockers), material
        material[IdentityComponent.DEVICE] = {
            "requested": target.device_profile_id, "resolved": desired.device_profile_id,
            "platform": desired.platform_profile_id}
        material[IdentityComponent.FROZEN] = {
            "build_id": frozen.build_id, "software": frozen.fingerprint(),
            "capture": frozen.capture_status.value}

        try:
            actual = status.inspector.inspect()
        except Exception as exc:
            self._log_failure("kodi", exc)
            gaps.append(CheckGap.KODI_STATE_UNAVAILABLE)
            return self._unchecked(now, gaps, blockers), material
        actual_map = {addon.addon_id: addon for addon in actual.addons}

        software = self._software(target, desired, frozen, records, actual, actual_map,
                                  gaps, blockers, material)
        skipped_records = tuple(software.skipped.values())
        try:
            projected_desired, _ = project_resolutions(desired, skipped_records)
        except Exception as exc:
            self._log_failure("projection", exc)
            projected_desired = desired
        final_map = self._final_state(frozen, software, actual_map)
        self._stage_two(projected_desired, actual, final_map, frozen, software, gaps, blockers)
        skin = self._skin(desired, actual, software, gaps, blockers, material)
        settings = self._settings(projected_desired, effective, actual_map, final_map, gaps, material)
        private = self._private(projected_desired, frozen, actual_map, gaps, blockers, material)

        order = {addon_id: index for index, addon_id in enumerate(software.install_order)}
        rows = tuple(sorted(software.rows.values(),
                            key=lambda row: (order.get(row.addon_id, 10 ** 6), row.addon_id)))
        has_changes = (
            any(row.action in CHANGE_ACTIONS for row in rows)
            or skin.kind is SkinPlanKind.SWITCH
            or settings.kind is SettingsPlanKind.CHANGES
            or private.kind is PrivatePlanKind.CHANGES_NEEDED
        )
        has_decision = any(row.action is SoftwareAction.DECISION for row in rows)
        compared = (
            any(row.action is not SoftwareAction.ACCEPTED_SKIP for row in rows)
            or skin.kind not in (SkinPlanKind.NOT_APPLICABLE, SkinPlanKind.UNAVAILABLE)
            or settings.kind not in (SettingsPlanKind.NOT_APPLICABLE, SettingsPlanKind.UNAVAILABLE)
            or private.kind not in (PrivatePlanKind.NOT_USED, PrivatePlanKind.UNAVAILABLE)
        )
        if not compared and not blockers:
            gaps.append(CheckGap.NOTHING_TO_COMPARE)
        unavailable = (
            skin.kind is SkinPlanKind.UNAVAILABLE or settings.kind is SettingsPlanKind.UNAVAILABLE
            or private.kind is PrivatePlanKind.UNAVAILABLE
            or any(row.action is SoftwareAction.UNAVAILABLE for row in rows)
        )
        gaps = list(dict.fromkeys(gaps))
        if blockers:
            state = PlanState.BLOCKED
        elif gaps or unavailable:
            state = PlanState.INCOMPLETE
        elif has_decision:
            state = PlanState.DECISION_REQUIRED
        elif software.repository:
            state = PlanState.RESOLUTION_REQUIRED
        elif has_changes:
            state = PlanState.CHANGES_READY
        else:
            state = PlanState.NO_CHANGES
        restart = RestartPlan(
            RestartExpectation.EXPECTED if software.hold_ids and (has_changes or has_decision)
            else RestartExpectation.NOT_EXPECTED)
        plan = BuildPlan(
            state=state, checked_at=now, software=rows, skin=skin, settings=settings,
            private=private, restart=restart,
            blockers=tuple(self._unique_blockers(blockers)), gaps=tuple(gaps),
        )
        material[IdentityComponent.ACTIONS] = plan.identity_material()
        return plan, material

    @staticmethod
    def _unique_blockers(blockers) -> List[PlanBlocker]:
        seen, result = set(), []
        for blocker in blockers:
            key = (blocker.code, blocker.addon_id)
            if key not in seen:
                seen.add(key)
                result.append(blocker)
        return result

    # -- software stage -----------------------------------------------------

    def _software(self, target, desired, frozen, records, actual, actual_map,
                  gaps, blockers, material) -> _Software:
        o = self._o
        sw = _Software()
        policies = tuple(desired.frozen_install_policies)
        installable = tuple(sorted(
            (n for n in frozen.addons if not n.system and not n.is_absent_optional_dependency),
            key=lambda n: n.addon_id))
        prior = {record.addon_id: record for record in records}
        choices = dict(target.choices)
        artifacts: List[object] = []
        outcomes: List[object] = []
        broken: Dict[str, object] = {}          # add-on -> its ``broken`` flag, when it was read

        try:
            summary = summarize_frozen_recoverability(frozen, o.artifact_store, policies)
            policy_digest = policy_fingerprint(frozen, policies)
            plan_digest = install_plan_fingerprint(frozen, policies)
        except Exception as exc:
            self._log_failure("software", exc)
            blockers.append(PlanBlocker(BlockerCode.SOFTWARE_PLAN_INVALID))
            sw.valid = False
            material[IdentityComponent.POLICY] = [
                sorted([a, c.value] for a, c in choices.items())]
            return sw
        recover = {row.addon_id: row for row in summary.addons}

        def put(addon_id, action, version="", offered=()):
            sw.rows[addon_id] = SoftwareRow(addon_id, action, self._name(addon_id), version, offered)

        def block(addon_id, action, code):
            blockers.append(PlanBlocker(code, addon_id, self._name(addon_id)))
            put(addon_id, action)

        for node in installable:
            aid = node.addon_id
            row = recover[aid]
            record = prior.get(aid)
            installed = actual_map.get(aid)
            artifacts.append([aid, node.version, row.exact_artifact_available,
                              node.artifact.sha256 if row.exact_artifact_available else "",
                              row.repository_id, row.fallback_eligible, row.skip_eligible])

            # 1. which outcome does the plan assume for this add-on?
            kind, version = "", node.version
            if record is not None and record.resolution is InstallResolution.SKIPPED:
                kind = "skip_recorded"
            elif record is not None:
                kind, version = "recorded", record.resolved_version or node.version
                recorded_ok = self._recorded_package(record) if installed is None else None
                artifacts.append(["recorded", aid, record.artifact_sha256, recorded_ok])
            elif row.exact_artifact_available:
                kind = "exact"
            else:
                offered: List[DecisionChoice] = []
                if installed is None:      # an installed add-on can be neither skipped nor fetched
                    if row.repository_known and row.fallback_eligible:
                        offered.append(DecisionChoice.INSTALL_CURRENT)
                    if row.skip_eligible:
                        offered.append(DecisionChoice.SKIP)
                choice = choices.get(aid)
                if not offered:
                    outcomes.append([aid, "package_missing"])
                    block(aid, SoftwareAction.PACKAGE_MISSING, BlockerCode.PACKAGE_MISSING)
                    continue
                offered.append(DecisionChoice.CANCEL)
                if choice is None:
                    outcomes.append([aid, "decision"])
                    sw.pending.add(aid)
                    put(aid, SoftwareAction.DECISION, node.version, tuple(offered))
                    continue
                if choice is DecisionChoice.CANCEL:
                    outcomes.append([aid, "cancelled"])
                    block(aid, SoftwareAction.BLOCKED, BlockerCode.USER_CANCELLED)
                    continue
                if choice not in offered:
                    outcomes.append([aid, "choice_not_permitted"])
                    block(aid, SoftwareAction.BLOCKED, BlockerCode.CHOICE_NOT_PERMITTED)
                    continue
                kind = "skip_chosen" if choice is DecisionChoice.SKIP else "repository_chosen"
            outcomes.append([aid, kind])

            # 2. skipped add-ons: accepted, and never touched
            if kind.startswith("skip"):
                sw.skipped[aid] = record if kind == "skip_recorded" else InstallResolutionRecord(
                    aid, node.version, InstallResolution.SKIPPED, ResolutionState.SKIPPED,
                    desired_enabled=node.desired_enabled)
                if installed is not None:
                    block(aid, SoftwareAction.BLOCKED, BlockerCode.SKIPPED_ADDON_PRESENT)
                else:
                    put(aid, SoftwareAction.ACCEPTED_SKIP, node.version)
                continue

            # 3. everything else must end at the exact version, enabled as the build says
            sw.target_version[aid] = version
            if installed is None:
                if kind == "repository_chosen":
                    sw.repository.add(aid)
                    put(aid, SoftwareAction.INSTALL_REPOSITORY)
                elif kind == "recorded" and not recorded_ok:
                    block(aid, SoftwareAction.PACKAGE_MISSING, BlockerCode.PACKAGE_MISSING)
                else:
                    put(aid, SoftwareAction.INSTALL_EXACT, version)
                continue
            try:
                detail = o.addon_details(aid)
            except Exception as exc:
                self._log_failure("details", exc)
                detail = None
            broken[aid] = None if detail is None else bool(detail.broken)
            if detail is None or not installed.version:
                gaps.append(CheckGap.SOFTWARE_UNAVAILABLE)
                put(aid, SoftwareAction.UNAVAILABLE)
            elif detail.broken:
                block(aid, SoftwareAction.BROKEN, BlockerCode.INSTALLED_ADDON_BROKEN)
            elif installed.version != version:
                block(aid, SoftwareAction.DIFFERENT_VERSION, BlockerCode.DIFFERENT_VERSION_INSTALLED)
            elif installed.enabled is not node.desired_enabled:
                put(aid, SoftwareAction.ENABLE if node.desired_enabled else SoftwareAction.DISABLE,
                    version)
            else:
                put(aid, SoftwareAction.CURRENT, version)

        material[IdentityComponent.ARTIFACTS] = artifacts
        resolution = target.install_resolution
        material[IdentityComponent.POLICY] = {
            "install_plan": plan_digest, "policy": policy_digest,
            "resolution": None if resolution is None else [
                resolution.resolution_fingerprint, resolution.resulting_software_fingerprint],
            "choices": sorted([a, c.value] for a, c in choices.items()),
            "outcomes": sorted(outcomes),
        }
        managed = {n.addon_id for n in installable}
        managed.update(item.addon_id for item in desired.addons)
        managed.update(item.addon_id for item in desired.repositories if item.required)
        if desired.skin is not None:
            managed.add(desired.skin.addon_id)
        # Declared managed nodes and the managed skin may be outside the saved graph.
        # Their installed health affects stage-two actions and must bind the review too.
        for aid in sorted(managed - {n.addon_id for n in installable}):
            if aid not in actual_map:
                continue
            try:
                detail = o.addon_details(aid)
            except Exception as exc:
                self._log_failure("details", exc)
                detail = None
            broken[aid] = None if detail is None else bool(detail.broken)
            if detail is None:
                gaps.append(CheckGap.SOFTWARE_UNAVAILABLE)
                put(aid, SoftwareAction.UNAVAILABLE)
            elif detail.broken:
                block(aid, SoftwareAction.BROKEN, BlockerCode.INSTALLED_ADDON_BROKEN)
        material[IdentityComponent.SOFTWARE_STATE] = sorted(
            [aid, aid in actual_map,
             actual_map[aid].version if aid in actual_map else "",
             actual_map[aid].enabled if aid in actual_map else False,
             broken.get(aid)]
            for aid in managed)

        # 4. choices that cannot be honoured, found now rather than after the guard is engaged
        self._check_choices(desired, frozen, sw, blockers)
        if not blockers or all(b.code in (BlockerCode.OPERATION_PENDING,
                                          BlockerCode.OPERATION_NEEDS_ATTENTION) for b in blockers):
            self._validate_graph(desired, frozen, policies, sw, blockers, prior)
        return sw

    def _recorded_package(self, record: InstallResolutionRecord) -> bool:
        """The saved package a recorded resolution installed, still exact and intact."""
        store = self._o.artifact_store
        try:
            metadata = store.get_metadata(record.artifact_sha256)
            data = store.read_bytes(record.artifact_sha256)
            if (metadata.sha256 != record.artifact_sha256 or metadata.addon_id != record.addon_id
                    or metadata.version != record.resolved_version
                    or metadata.size != record.artifact_size or len(data) != record.artifact_size):
                return False
            validate_addon_zip(data, expected_addon_id=record.addon_id,
                               expected_version=record.resolved_version)
            return True
        except Exception:
            return False

    def _check_choices(self, desired, frozen, sw: _Software, blockers) -> None:
        """The conflicts the installer and reconciler would raise only after mutation began."""
        if desired.skin is not None and desired.skin.addon_id in sw.skipped:
            blockers.append(PlanBlocker(BlockerCode.CHOICE_CONFLICTS_WITH_BUILD, desired.skin.addon_id,
                                        self._name(desired.skin.addon_id)))
        for repository in desired.repositories:
            if repository.required and repository.addon_id in sw.skipped:
                blockers.append(PlanBlocker(BlockerCode.CHOICE_CONFLICTS_WITH_BUILD,
                                            repository.addon_id, self._name(repository.addon_id)))
        config = desired.config
        if config is None:
            return
        changes = {aid: None for aid in sw.skipped}
        changes.update({aid: sw.target_version.get(aid) for aid in sw.repository})
        for aid, version in sorted(changes.items()):
            try:
                validate_private_overlay_resolution_compatibility(
                    {aid: version}, config.private_settings, config.structured_private_resources)
            except Exception:
                blockers.append(PlanBlocker(BlockerCode.CHOICE_CONFLICTS_WITH_BUILD, aid, self._name(aid)))

    def _validate_graph(self, desired, frozen, policies, sw: _Software, blockers, records) -> None:
        """Dependency graph, skip permissions and activation holds, exactly as the installer checks."""
        try:
            plan = validate_frozen_install_plan(
                frozen, self._o.artifact_store, policies, skipped=tuple(sorted(sw.skipped)))
            skipped = frozenset(sw.skipped)
            extra_dependencies = {
                aid: stored_repository_dependencies(
                    self._o.artifact_store, record, plan, records, skipped)
                for aid, record in sorted(records.items())
                if record.resolution is InstallResolution.REPOSITORY_CURRENT
            }
            if extra_dependencies:
                plan = validate_frozen_install_plan(
                    frozen, self._o.artifact_store, policies, skipped=tuple(sorted(skipped)),
                    extra_dependencies=extra_dependencies)
            sw.install_order = tuple(node.addon_id for node in plan.install_order)
            sw.hold_ids = _hold_ids(plan.install_order, desired)
        except Exception as exc:
            self._log_failure("graph", exc)
            sw.valid = False
            blockers.append(PlanBlocker(BlockerCode.SOFTWARE_PLAN_INVALID))
            return
        if sw.hold_ids:
            for aid in sorted(sw.repository):      # "pre-activation lifecycle requires exact dependency metadata"
                blockers.append(PlanBlocker(BlockerCode.CHOICE_CONFLICTS_WITH_BUILD, aid, self._name(aid)))

    @staticmethod
    def _final_state(frozen, sw: _Software, actual_map) -> Dict[str, InstalledAddon]:
        """Kodi after the software stage: each saved add-on at its exact version, as the build says."""
        final = dict(actual_map)
        for node in frozen.addons:
            if node.system or node.is_absent_optional_dependency or node.addon_id in sw.skipped:
                continue
            if node.addon_id in sw.target_version or node.addon_id in sw.pending:
                installed = actual_map.get(node.addon_id)
                final[node.addon_id] = InstalledAddon(
                    node.addon_id, node.desired_enabled,
                    installed.version if installed is not None else sw.target_version.get(
                        node.addon_id, node.version))
        return final

    def _stage_two(self, desired, actual, final_map, frozen, sw: _Software, gaps, blockers) -> None:
        """What the BM-006 planner would still do once the saved software is in place."""
        projected = KodiState(actual.platform, actual.kodi_version, actual.active_skin,
                              tuple(sorted(final_map.values(), key=lambda a: a.addon_id)))
        try:
            stage = plan_changes(desired, projected)
        except PlanningError as exc:
            self._log_failure("planner", exc)
            blockers.append(PlanBlocker(BlockerCode.BUILD_DEFINITION_INVALID))
            return
        saved = {n.addon_id for n in frozen.addons}
        for action in stage.actions:
            if action.addon_id in saved or not _ADDON_ID.fullmatch(action.addon_id or ""):
                continue                      # saved add-ons were judged above; CONFIGURE/SET_SKIN below
            if action.kind in (INSTALL_ADDON, INSTALL_REPOSITORY):
                if action.addon_id not in sw.rows:
                    blockers.append(PlanBlocker(BlockerCode.ADDON_NOT_IN_SAVED_SOFTWARE,
                                                action.addon_id, self._name(action.addon_id)))
                    sw.rows[action.addon_id] = SoftwareRow(
                        action.addon_id, SoftwareAction.NOT_SAVED, self._name(action.addon_id))
            elif action.kind in (ENABLE_ADDON, DISABLE_ADDON) and action.addon_id not in sw.rows:
                sw.rows[action.addon_id] = SoftwareRow(
                    action.addon_id,
                    SoftwareAction.ENABLE if action.kind == ENABLE_ADDON else SoftwareAction.DISABLE,
                    self._name(action.addon_id))

    # -- skin, settings, private ----------------------------------------------

    def _skin(self, desired, actual, sw: _Software, gaps, blockers, material) -> SkinPlan:
        material[IdentityComponent.SKIN_STATE] = [
            desired.skin.addon_id if desired.skin is not None else "", actual.active_skin]
        if desired.skin is None:
            return SkinPlan(SkinPlanKind.NOT_APPLICABLE)
        skin_id = desired.skin.addon_id
        name = self._name(skin_id)
        current = actual.active_skin if _ADDON_ID.fullmatch(actual.active_skin or "") else ""
        if not current:        # Kodi did not name the active skin: a switch is not proven
            return SkinPlan(SkinPlanKind.UNAVAILABLE, skin_id, "", name)
        kind = SkinPlanKind.CURRENT if current == skin_id else SkinPlanKind.SWITCH
        return SkinPlan(kind, skin_id, current, name)

    def _settings(self, desired, effective, actual_map, final_map, gaps, material) -> SettingsPlan:
        if desired.config is None:
            return SettingsPlan(SettingsPlanKind.NOT_APPLICABLE)
        try:
            inspection = self._o.status.configuration_inspector.inspect(effective)
        except Exception as exc:
            self._log_failure("configuration", exc)
            inspection = None
        if inspection is None:
            gaps.append(CheckGap.CONFIGURATION_UNAVAILABLE)
            material[IdentityComponent.CONFIGURATION] = ["unavailable"]
            return SettingsPlan(SettingsPlanKind.UNAVAILABLE)
        differing = waiting = unreadable = 0
        for (_kind, owner, _key), check in inspection.setting_checks:
            if check is ConfigTargetCheck.DIFFERS:
                differing += 1
            elif check is ConfigTargetCheck.UNREADABLE:
                if owner not in actual_map and owner in final_map:
                    waiting += 1            # its owner is installed first, then the setting is written
                else:
                    unreadable += 1
        for _destination, check in inspection.file_checks:
            if check is ConfigTargetCheck.DIFFERS:
                differing += 1
            elif check is ConfigTargetCheck.UNREADABLE:
                unreadable += 1
        material[IdentityComponent.CONFIGURATION] = {
            "effective": effective.identity,
            "settings": sorted([list(t), c.value] for t, c in inspection.setting_checks),
            "files": sorted([d, c.value] for d, c in inspection.file_checks),
            "waiting": waiting,
        }
        if unreadable:
            gaps.append(CheckGap.CONFIGURATION_UNAVAILABLE)
            return SettingsPlan(SettingsPlanKind.UNAVAILABLE)
        if differing + waiting:
            return SettingsPlan(SettingsPlanKind.CHANGES, differing + waiting)
        return SettingsPlan(SettingsPlanKind.CURRENT)

    def _private(self, desired, frozen, actual_map, gaps, blockers, material) -> PrivatePlan:
        config = desired.config
        owners = set()
        if config is not None:
            owners.update(item.addon_id for item in config.private_settings)
            owners.update(item.owner_addon_id for item in config.structured_private_resources)
        pending = frozenset(owner for owner in owners if owner not in actual_map)
        private_gaps: List[CheckGap] = []
        try:
            status, fingerprint = self._status.inspect_private(desired, frozen, private_gaps, pending)
        except Exception as exc:
            self._log_failure("private", exc)
            gaps.append(CheckGap.PRIVATE_UNAVAILABLE)
            material[IdentityComponent.PRIVATE] = ["unavailable"]
            return PrivatePlan(PrivatePlanKind.UNAVAILABLE)
        for gap in private_gaps:
            code = _PRIVATE_GAPS.get(gap)
            if code is not None:
                blockers.append(PlanBlocker(code))
            else:
                gaps.append(gap)
        material[IdentityComponent.PRIVATE] = {
            "levels": sorted([i.item_id, i.kind.value, i.level.value] for i in status.items),
            "level": status.level.value, "overlay": fingerprint, "waiting": sorted(pending)}
        return PrivatePlan(_PRIVATE_KIND[status.level])


# ---------------------------------------------------------------------------
# Production wiring
# ---------------------------------------------------------------------------

def default_plan_target() -> Optional[PlanTarget]:
    """The current validated library selection, without acquiring/applying it."""
    from resources.lib.build_library import selected_plan_target
    return selected_plan_target()


def default_plan_owners(*, log: Optional[Callable[[str], None]] = None) -> PlanOwners:
    """Production read-only collaborators, constructed without touching Kodi state."""
    return PlanOwners(
        status=default_status_owners(log=log),
        artifact_store=ReadOnlyArtifactStore(default_frozen_install_root() / "frozen-artifacts"),
        addon_details=KodiRuntimeFrozenArtifactBackend().get_addon_details,
    )


def preview_build_plan(target: PlanTarget, *, log: Optional[Callable[[str], None]] = None) -> BuildPlan:
    """One fresh read-only plan for an explicit target (future Create / Library wiring)."""
    return BuildPlanService(default_plan_owners(log=log)).preview(target)


def validate_reviewed_plan(
    target: PlanTarget, review: ReviewIdentity, *, log: Optional[Callable[[str], None]] = None
) -> ReviewCheck:
    """Read-only freshness check, to be called immediately before any mutation."""
    return BuildPlanService(default_plan_owners(log=log)).validate(target, review)


def plan_provider(
    target: PlanTarget, *, log: Optional[Callable[[str], None]] = None
) -> Callable[[Dict[str, DecisionChoice]], BuildPlan]:
    """The read-only callable the native Review Changes page uses.

    It carries the explicit target; each call applies the user's choices so far
    and returns a fresh plan. Nothing here selects a build or starts work.
    """
    def provide(choices: Optional[Dict[str, DecisionChoice]] = None) -> BuildPlan:
        chosen = target
        for addon_id, choice in sorted((choices or {}).items()):
            chosen = chosen.with_choice(addon_id, choice)
        return preview_build_plan(chosen, log=log)
    return provide
