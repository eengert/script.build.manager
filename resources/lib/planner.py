"""
Build Manager desired-vs-actual planner (BM-006).

Public API
----------
plan_changes(desired: ResolvedBuild, actual: KodiState) -> Plan
    Compare a fully resolved desired build against actual Kodi runtime state
    and return an ordered, deterministic, non-mutating plan of required actions.

Errors
------
PlanningError -- raised for inconsistent or invalid input (e.g. duplicate
                 addon_ids in the KodiState tuple).

Plan representation
-------------------
Plan(actions: Tuple[PlanAction, ...])
    Immutable ordered sequence of PlanAction objects.
    plan.is_noop -- True when actions is empty.
    plan.action_count -- number of actions.

PlanAction(kind, addon_id, desired_state, current_state, reason)
    Immutable description of one required change.

Action kinds
------------
INSTALL_REPOSITORY -- install a missing required repository add-on.
INSTALL_ADDON      -- install an add-on not currently present; desired_state
                      carries the intended post-install state ("enabled" or
                      "disabled"). Kodi installs add-ons enabled by default;
                      the executor must handle the disabled case explicitly.
ENABLE_ADDON       -- enable an installed but currently disabled add-on.
DISABLE_ADDON      -- disable an installed but currently enabled add-on.
ENSURE_ABSENT      -- remove an installed add-on whose desired state is "absent".
SET_SKIN           -- activate a skin add-on.
CONFIGURE          -- placeholder: managed configuration reconciliation is
                      required. BM-005 does not inspect config state, so the
                      actual state is always "unchecked" at this planning stage.

Add-on transition matrix (desired → action when actual is …)
-------------------------------------------------------------
desired \ actual  | missing          | disabled     | enabled
------------------+------------------+--------------+-------------------
enabled           | INSTALL_ADDON*   | ENABLE_ADDON | (no action)
disabled          | INSTALL_ADDON**  | (no action)  | DISABLE_ADDON
absent            | (no action)      | ENSURE_ABSENT| ENSURE_ABSENT

*  desired_state="enabled"
** desired_state="disabled"; executor must install then disable.

Unmanaged add-ons
-----------------
Add-ons present in KodiState but not mentioned in ResolvedBuild.addons are
left untouched. The planner never emits ENSURE_ABSENT for an add-on that is
not explicitly listed with state="absent" in the desired build.

Repository planning
-------------------
Only repositories with required=True (the default) are planned. A missing
optional (required=False) repository is left unplanned; deferring to a future
task that understands which add-ons require which repositories.

Skin planning
-------------
If desired skin is already the active skin: no action.
If desired skin differs from active skin: SET_SKIN action emitted.
If desired skin add-on is not currently installed and no INSTALL_ADDON action
for that skin_id is already being generated from the desired add-ons list,
an additional INSTALL_ADDON action is prepended (category 2).

Config planning
---------------
If desired.config is None: no CONFIGURE action.
If desired.config is non-None: exactly one CONFIGURE action with
current_state="unchecked" (actual config state is not inspected by BM-005).

Duplicate-action prevention
---------------------------
A skin add-on present in desired.addons (state != absent) already generates
an INSTALL_ADDON. The planner tracks install targets and skips the separate
skin INSTALL_ADDON to avoid duplication.

Deterministic ordering policy
------------------------------
Actions are sorted by category first, then lexically by addon_id within each
category. Category order:
  1. INSTALL_REPOSITORY
  2. INSTALL_ADDON
  3. ENABLE_ADDON, DISABLE_ADDON   (lexical by addon_id)
  4. ENSURE_ABSENT
  5. SET_SKIN
  6. CONFIGURE
This ordering is stable and independent of Python dict/set iteration order or
the order add-ons appear in the manifest or KodiState.

Platform compatibility
----------------------
ResolvedBuild.platform_profile_id is the profile key selected at resolution
time (e.g. "tvos"). KodiState.platform is the runtime platform detected by
BM-005 (e.g. "macos"). These are different namespaces — the planner does not
compare them. Platform mismatch detection is deferred to a future task when
the mapping between profile IDs and runtime platform IDs is formally specified.

Stdlib only — no new runtime dependencies.
No Kodi imports — pure Python, no filesystem or network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from resources.lib.inspector import InstalledAddon, KodiState
from resources.lib.resolver import ResolvedBuild


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class PlanningError(Exception):
    """Raised when plan_changes() receives an inconsistent or invalid input."""


# ---------------------------------------------------------------------------
# Action kind constants
# ---------------------------------------------------------------------------

INSTALL_REPOSITORY: str = "INSTALL_REPOSITORY"
INSTALL_ADDON: str = "INSTALL_ADDON"
ENABLE_ADDON: str = "ENABLE_ADDON"
DISABLE_ADDON: str = "DISABLE_ADDON"
ENSURE_ABSENT: str = "ENSURE_ABSENT"
SET_SKIN: str = "SET_SKIN"
CONFIGURE: str = "CONFIGURE"

_CATEGORY_ORDER: Dict[str, int] = {
    INSTALL_REPOSITORY: 0,
    INSTALL_ADDON:      1,
    ENABLE_ADDON:       2,
    DISABLE_ADDON:      2,
    ENSURE_ABSENT:      3,
    SET_SKIN:           4,
    CONFIGURE:          5,
}


# ---------------------------------------------------------------------------
# Typed output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanAction:
    """One required change in the desired-vs-actual plan.

    Fields
    ------
    kind         -- one of the action kind constants (INSTALL_ADDON, etc.)
    addon_id     -- the add-on or skin being acted on; empty string for CONFIGURE
    desired_state -- intended end state:
                    "enabled" | "disabled" | "absent" | "installed" |
                    "active" | "configured"
    current_state -- observed actual state:
                    "missing" | "enabled" | "disabled" | skin_addon_id |
                    "unchecked" (config) | ""
    reason       -- human-readable explanation of why this action is required
    """
    kind: str
    addon_id: str
    desired_state: str
    current_state: str
    reason: str


@dataclass(frozen=True)
class Plan:
    """Immutable, ordered sequence of PlanAction objects.

    Produced by plan_changes(). Does not mutate any Kodi state.
    """
    actions: Tuple[PlanAction, ...]

    @property
    def is_noop(self) -> bool:
        """True when no actions are required."""
        return len(self.actions) == 0

    @property
    def action_count(self) -> int:
        """Number of actions in the plan."""
        return len(self.actions)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_changes(desired: ResolvedBuild, actual: KodiState) -> Plan:
    """Compare desired build state against actual Kodi state.

    Returns an ordered Plan describing all required changes. The plan is
    deterministic: identical inputs always produce identical output regardless
    of Python dict/set iteration order. The plan is non-mutating: calling this
    function does not change any Kodi state.

    Raises:
        PlanningError: if KodiState contains duplicate addon_ids, or if the
            desired build contains contradictory declarations (e.g. skin also
            declared absent, or required repository also declared absent).
    """
    _validate_no_contradictions(desired)
    actual_map = _build_actual_map(actual)

    # Phase 1 — repositories (category 0).
    # Returns the set of addon_ids being installed as repositories so later
    # phases can skip duplicate INSTALL_ADDON actions for those IDs.
    repo_actions, repo_install_ids = _plan_repositories(desired, actual_map)

    # Phase 2 — add-on installs (category 1).
    # repo_install_ids prevents INSTALL_ADDON for IDs already covered by
    # INSTALL_REPOSITORY (cross-category dedup).
    install_actions, addon_install_ids = _plan_addon_installs(
        desired, actual_map, repo_install_ids
    )

    # planned_install_ids = union of all installation actions so far.
    # Used by the skin phase to prevent any duplicate INSTALL_ADDON.
    planned_install_ids: Set[str] = repo_install_ids | addon_install_ids

    # Phase 3 — skin install prerequisite (category 1, interspersed lexically)
    skin_install = _plan_skin_install(desired, actual_map, planned_install_ids)
    if skin_install is not None:
        install_actions.append(skin_install)
        planned_install_ids.add(skin_install.addon_id)

    # Sort all installs lexically within category 1
    install_actions.sort(key=lambda a: a.addon_id)

    # Phase 4 — enable/disable transitions (category 2)
    enable_disable_actions = _plan_enable_disable(desired, actual_map)

    # Phase 5 — ensure-absent (category 3)
    absent_actions = _plan_ensure_absent(desired, actual_map)

    # Phase 6 — skin activation (category 4)
    skin_actions = _plan_skin_activate(desired, actual)

    # Phase 7 — configuration reconciliation (category 5)
    config_actions = _plan_config(desired)

    all_actions: List[PlanAction] = (
        repo_actions
        + install_actions
        + enable_disable_actions
        + absent_actions
        + skin_actions
        + config_actions
    )

    return Plan(actions=tuple(all_actions))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_no_contradictions(desired: ResolvedBuild) -> None:
    """Raise PlanningError for cross-declaration contradictions in desired state.

    Two contradictions are detected:

    1. Desired skin also declared absent in desired.addons.
       These are mutually exclusive: the planner cannot install+activate a skin
       that is simultaneously required to be absent.

    2. A required repository also declared absent in desired.addons.
       These are mutually exclusive: the planner cannot install a required
       repository that is simultaneously required to be absent.
    """
    absent_ids: Set[str] = {e.addon_id for e in desired.addons if e.state == "absent"}

    if desired.skin is not None and desired.skin.addon_id in absent_ids:
        raise PlanningError(
            f"Desired skin {desired.skin.addon_id!r} is also declared absent "
            f"in desired add-ons"
        )

    required_repo_ids: Set[str] = {
        r.addon_id for r in desired.repositories if r.required
    }
    conflicting = sorted(required_repo_ids & absent_ids)
    if conflicting:
        raise PlanningError(
            f"Required repository {conflicting[0]!r} is also declared absent "
            f"in desired add-ons"
        )


def _build_actual_map(actual: KodiState) -> Dict[str, InstalledAddon]:
    """Index actual.addons by addon_id. Raise PlanningError on duplicates."""
    result: Dict[str, InstalledAddon] = {}
    for addon in actual.addons:
        if addon.addon_id in result:
            raise PlanningError(
                f"KodiState contains duplicate addon_id: {addon.addon_id!r}"
            )
        result[addon.addon_id] = addon
    return result


def _plan_repositories(
    desired: ResolvedBuild,
    actual_map: Dict[str, InstalledAddon],
) -> Tuple[List[PlanAction], Set[str]]:
    """Plan INSTALL_REPOSITORY actions for missing required repositories.

    Returns (actions, install_ids) where install_ids is the set of addon_ids
    being installed as repositories.  Callers must exclude these IDs from
    INSTALL_ADDON planning to prevent duplicate installation actions.

    Cross-category desired_state hint:
    When the same addon_id also appears in desired.addons with state="disabled",
    the INSTALL_REPOSITORY action carries desired_state="disabled" so that the
    executor knows to disable the add-on after repository installation.  For all
    other overlapping desired add-on states ("enabled" or absent from the list),
    desired_state="installed" is used (implying enabled, Kodi's default).
    """
    desired_addon_states: Dict[str, str] = {
        e.addon_id: e.state for e in desired.addons
    }
    actions: List[PlanAction] = []
    install_ids: Set[str] = set()

    for repo in sorted(desired.repositories, key=lambda r: r.addon_id):
        if not repo.required:
            continue
        if repo.addon_id in actual_map:
            continue
        overlapping_state = desired_addon_states.get(repo.addon_id)
        desired_state = "disabled" if overlapping_state == "disabled" else "installed"
        reason = "Required repository not installed"
        if repo.bootstrap_url:
            reason += f"; bootstrap_url={repo.bootstrap_url!r}"
        if overlapping_state == "disabled":
            reason += "; overlapping desired add-on state: disabled"
        install_ids.add(repo.addon_id)
        actions.append(PlanAction(
            kind=INSTALL_REPOSITORY,
            addon_id=repo.addon_id,
            desired_state=desired_state,
            current_state="missing",
            reason=reason,
        ))
    return actions, install_ids


def _plan_addon_installs(
    desired: ResolvedBuild,
    actual_map: Dict[str, InstalledAddon],
    repo_install_ids: Set[str],
) -> Tuple[List[PlanAction], Set[str]]:
    """Plan INSTALL_ADDON actions for add-ons not currently present.

    repo_install_ids: addon_ids already covered by INSTALL_REPOSITORY actions.
    Any addon_id in this set is skipped here to prevent duplicate installation
    actions for the same logical target.

    Returns (actions, addon_install_ids) where addon_install_ids is the set of
    addon_ids for which INSTALL_ADDON was emitted.  The caller merges this with
    repo_install_ids before skin-install dedup.
    """
    actions: List[PlanAction] = []
    addon_ids: Set[str] = set()

    for entry in sorted(desired.addons, key=lambda e: e.addon_id):
        if entry.state == "absent":
            continue
        if entry.addon_id in actual_map:
            continue
        if entry.addon_id in repo_install_ids:
            # Installation already covered by INSTALL_REPOSITORY; skip to
            # prevent a duplicate installation action for the same target.
            continue
        addon_ids.add(entry.addon_id)
        actions.append(PlanAction(
            kind=INSTALL_ADDON,
            addon_id=entry.addon_id,
            desired_state=entry.state,
            current_state="missing",
            reason=f"Add-on not installed; desired state after install: {entry.state!r}",
        ))

    return actions, addon_ids


def _plan_skin_install(
    desired: ResolvedBuild,
    actual_map: Dict[str, InstalledAddon],
    planned_install_ids: Set[str],
) -> Optional[PlanAction]:
    """Return an INSTALL_ADDON for the desired skin if it needs installation.

    planned_install_ids must be the union of repo_install_ids and
    addon_install_ids so that both INSTALL_REPOSITORY and INSTALL_ADDON coverage
    prevent a redundant skin install.

    Returns None when:
    - no desired skin
    - skin already installed in actual state
    - skin already covered by any planned installation action (no duplicate)
    """
    if desired.skin is None:
        return None
    skin_id = desired.skin.addon_id
    if skin_id in actual_map:
        return None
    if skin_id in planned_install_ids:
        return None
    return PlanAction(
        kind=INSTALL_ADDON,
        addon_id=skin_id,
        desired_state="enabled",
        current_state="missing",
        reason="Desired skin add-on not installed; required before SET_SKIN",
    )


def _plan_enable_disable(
    desired: ResolvedBuild,
    actual_map: Dict[str, InstalledAddon],
) -> List[PlanAction]:
    """Plan ENABLE_ADDON and DISABLE_ADDON for installed add-ons in wrong state."""
    actions: List[PlanAction] = []

    for entry in sorted(desired.addons, key=lambda e: e.addon_id):
        if entry.state == "absent":
            continue
        actual_addon = actual_map.get(entry.addon_id)
        if actual_addon is None:
            # Not installed; covered by INSTALL_ADDON
            continue

        if entry.state == "enabled" and not actual_addon.enabled:
            actions.append(PlanAction(
                kind=ENABLE_ADDON,
                addon_id=entry.addon_id,
                desired_state="enabled",
                current_state="disabled",
                reason="Add-on is installed and disabled; desired state: enabled",
            ))
        elif entry.state == "disabled" and actual_addon.enabled:
            actions.append(PlanAction(
                kind=DISABLE_ADDON,
                addon_id=entry.addon_id,
                desired_state="disabled",
                current_state="enabled",
                reason="Add-on is installed and enabled; desired state: disabled",
            ))

    return actions


def _plan_ensure_absent(
    desired: ResolvedBuild,
    actual_map: Dict[str, InstalledAddon],
) -> List[PlanAction]:
    """Plan ENSURE_ABSENT actions for add-ons whose desired state is 'absent'."""
    actions: List[PlanAction] = []

    for entry in sorted(desired.addons, key=lambda e: e.addon_id):
        if entry.state != "absent":
            continue
        actual_addon = actual_map.get(entry.addon_id)
        if actual_addon is None:
            continue
        current = "enabled" if actual_addon.enabled else "disabled"
        actions.append(PlanAction(
            kind=ENSURE_ABSENT,
            addon_id=entry.addon_id,
            desired_state="absent",
            current_state=current,
            reason="Add-on is installed; desired state: absent",
        ))

    return actions


def _plan_skin_activate(
    desired: ResolvedBuild,
    actual: KodiState,
) -> List[PlanAction]:
    """Plan a SET_SKIN action if the desired skin differs from the active skin."""
    if desired.skin is None:
        return []
    skin_id = desired.skin.addon_id
    if skin_id == actual.active_skin:
        return []
    current = actual.active_skin if actual.active_skin else "none"
    return [PlanAction(
        kind=SET_SKIN,
        addon_id=skin_id,
        desired_state="active",
        current_state=current,
        reason=f"Active skin is {actual.active_skin!r}; desired skin is {skin_id!r}",
    )]


def _plan_config(desired: ResolvedBuild) -> List[PlanAction]:
    """Plan a CONFIGURE action if desired config is declared.

    BM-005 does not inspect managed settings or files, so the actual config
    state is always 'unchecked' at this planning stage. One CONFIGURE action
    per plan is the extent of config planning in BM-006.
    """
    if desired.config is None:
        return []
    return [PlanAction(
        kind=CONFIGURE,
        addon_id="",
        desired_state="configured",
        current_state="unchecked",
        reason=(
            "Managed configuration declared; actual config state not yet "
            "inspected (BM-005 does not read managed settings or files)"
        ),
    )]
