"""Presentation-safe read-only plan contract (BM-UI-002C / G3).

The public vocabulary of the frozen-build review: what would change, what would
stay, what needs a decision, what is blocked, and whether an earlier review is
still valid. It imports only the standard library and the stdlib-only status
vocabulary, so the native UI can depend on it without importing an engine,
backend, or private-data owner.

Every field is an enum, a bool, a bounded integer, a validated identifier or
version, or a UTC timestamp. The one free-text field is ``display_name``:
bounded plain text with no control, format, or Kodi-markup characters. A plan
cannot carry a setting value, credential, overlay payload, exception message,
path, or fingerprint, and constructing one that tries to is a ``ValueError``.

Truthfulness is structural: a plan that is blocked, undecided, or not fully
checked cannot be built as ``CHANGES_READY``, and only a ``CHANGES_READY`` plan
can carry a review identity. The identity is an opaque stale-plan guard, not a
credential: its digest never appears in ``repr`` or ``to_safe_dict``.

Plan-state precedence (first match wins): ``BLOCKED`` (a proven reason the work
cannot proceed), ``INCOMPLETE`` (something required could not be checked),
``DECISION_REQUIRED`` (the user must choose before anything is proposed),
``CHANGES_READY``, ``NO_CHANGES``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional, Tuple

from resources.lib.status_model import CheckGap, is_plain_name

_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~:-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

MAX_SOFTWARE_ROWS = 4096
MAX_BLOCKERS = 256
MAX_COUNT = 100000


class PlanState(str, Enum):
    NO_CHANGES = "no_changes"
    CHANGES_READY = "changes_ready"
    DECISION_REQUIRED = "decision_required"
    RESOLUTION_REQUIRED = "resolution_required"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"


class DecisionChoice(str, Enum):
    """What the user may choose for an add-on whose saved package is missing."""

    INSTALL_CURRENT = "install_current"
    SKIP = "skip"
    CANCEL = "cancel"


class SoftwareAction(str, Enum):
    """One managed add-on's row. There is deliberately no remove/uninstall action."""

    CURRENT = "current"
    INSTALL_EXACT = "install_exact"              # the saved version
    INSTALL_REPOSITORY = "install_repository"    # a current repository version the user chose
    ENABLE = "enable"
    DISABLE = "disable"
    ACCEPTED_SKIP = "accepted_skip"
    DECISION = "decision"                        # saved package missing; the user chooses
    DIFFERENT_VERSION = "different_version"      # blocked: replacing a version is not supported yet
    BROKEN = "broken"                            # blocked: repairing a broken install is not supported yet
    PACKAGE_MISSING = "package_missing"          # blocked: no way to obtain this add-on
    NOT_SAVED = "not_saved"                      # blocked: the build manages it but did not save it
    BLOCKED = "blocked"                          # blocked for another reason (see blockers)
    UNAVAILABLE = "unavailable"                  # this add-on's state could not be determined


CHANGE_ACTIONS = frozenset({
    SoftwareAction.INSTALL_EXACT, SoftwareAction.INSTALL_REPOSITORY,
    SoftwareAction.ENABLE, SoftwareAction.DISABLE,
})
BLOCKING_ACTIONS = frozenset({
    SoftwareAction.DIFFERENT_VERSION, SoftwareAction.BROKEN, SoftwareAction.PACKAGE_MISSING,
    SoftwareAction.NOT_SAVED, SoftwareAction.BLOCKED,
})


class BlockerCode(str, Enum):
    DIFFERENT_VERSION_INSTALLED = "different_version_installed"
    INSTALLED_ADDON_BROKEN = "installed_addon_broken"
    PACKAGE_MISSING = "package_missing"
    ADDON_NOT_IN_SAVED_SOFTWARE = "addon_not_in_saved_software"
    SKIPPED_ADDON_PRESENT = "skipped_addon_present"
    CHOICE_NOT_PERMITTED = "choice_not_permitted"
    CHOICE_CONFLICTS_WITH_BUILD = "choice_conflicts_with_build"
    USER_CANCELLED = "user_cancelled"
    SOFTWARE_PLAN_INVALID = "software_plan_invalid"
    BUILD_DEFINITION_INVALID = "build_definition_invalid"
    PRIVATE_DATA_MISSING = "private_data_missing"
    PRIVATE_DATA_UNUSABLE = "private_data_unusable"
    OPERATION_PENDING = "operation_pending"
    OPERATION_NEEDS_ATTENTION = "operation_needs_attention"


class BlockerCategory(str, Enum):
    SOFTWARE = "software"
    CHOICE = "choice"
    BUILD = "build"
    PRIVATE_DATA = "private_data"
    OPERATION = "operation"


BLOCKER_CATEGORY = {
    BlockerCode.DIFFERENT_VERSION_INSTALLED: BlockerCategory.SOFTWARE,
    BlockerCode.INSTALLED_ADDON_BROKEN: BlockerCategory.SOFTWARE,
    BlockerCode.PACKAGE_MISSING: BlockerCategory.SOFTWARE,
    BlockerCode.ADDON_NOT_IN_SAVED_SOFTWARE: BlockerCategory.SOFTWARE,
    BlockerCode.SKIPPED_ADDON_PRESENT: BlockerCategory.SOFTWARE,
    BlockerCode.CHOICE_NOT_PERMITTED: BlockerCategory.CHOICE,
    BlockerCode.CHOICE_CONFLICTS_WITH_BUILD: BlockerCategory.CHOICE,
    BlockerCode.USER_CANCELLED: BlockerCategory.CHOICE,
    BlockerCode.SOFTWARE_PLAN_INVALID: BlockerCategory.BUILD,
    BlockerCode.BUILD_DEFINITION_INVALID: BlockerCategory.BUILD,
    BlockerCode.PRIVATE_DATA_MISSING: BlockerCategory.PRIVATE_DATA,
    BlockerCode.PRIVATE_DATA_UNUSABLE: BlockerCategory.PRIVATE_DATA,
    BlockerCode.OPERATION_PENDING: BlockerCategory.OPERATION,
    BlockerCode.OPERATION_NEEDS_ATTENTION: BlockerCategory.OPERATION,
}
# Blockers that always concern one add-on.
ADDON_BLOCKERS = frozenset({
    BlockerCode.DIFFERENT_VERSION_INSTALLED, BlockerCode.INSTALLED_ADDON_BROKEN,
    BlockerCode.PACKAGE_MISSING, BlockerCode.ADDON_NOT_IN_SAVED_SOFTWARE,
    BlockerCode.SKIPPED_ADDON_PRESENT, BlockerCode.CHOICE_NOT_PERMITTED,
    BlockerCode.USER_CANCELLED,
})
_ACTION_BLOCKER = {
    SoftwareAction.DIFFERENT_VERSION: BlockerCode.DIFFERENT_VERSION_INSTALLED,
    SoftwareAction.BROKEN: BlockerCode.INSTALLED_ADDON_BROKEN,
    SoftwareAction.PACKAGE_MISSING: BlockerCode.PACKAGE_MISSING,
    SoftwareAction.NOT_SAVED: BlockerCode.ADDON_NOT_IN_SAVED_SOFTWARE,
}


class SkinPlanKind(str, Enum):
    CURRENT = "current"
    SWITCH = "switch"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class SettingsPlanKind(str, Enum):
    CURRENT = "current"
    CHANGES = "changes"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class PrivatePlanKind(str, Enum):
    CURRENT = "current"
    CHANGES_NEEDED = "changes_needed"
    UNAVAILABLE = "unavailable"
    NOT_USED = "not_used"


class RestartExpectation(str, Enum):
    NOT_EXPECTED = "not_expected"
    EXPECTED = "expected"


class IdentityComponent(str, Enum):
    """The state a review is bound to. Each is hashed separately so a stale
    review can say *what* changed without saying what the values were."""

    BUILD = "build"                      # resolved build: manifest content, effective configuration
    DEVICE = "device"                    # selected device profile
    FROZEN = "frozen"                    # frozen build ID and software fingerprint
    POLICY = "policy"                    # install policy, recorded resolution, chosen resolutions
    ARTIFACTS = "artifacts"              # exact saved-package availability and identity
    SOFTWARE_STATE = "software_state"    # managed add-on state in Kodi
    SKIN_STATE = "skin_state"            # active skin
    CONFIGURATION = "configuration"      # verification state of managed settings and files
    PRIVATE = "private"                  # secret-blind private verification state
    OPERATION = "operation"              # pending restart / needs-attention state
    ACTIONS = "actions"                  # the resulting ordered plan


class ReviewFreshness(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    UNVERIFIABLE = "unverifiable"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_count(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_COUNT


def _addon_id(value: object, label: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    _require(isinstance(value, str) and _ADDON_ID.fullmatch(value) is not None,
             "unsupported %s" % label)
    return value


def _digest(material: object) -> str:
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# -- review identity -----------------------------------------------------------------------

@dataclass(frozen=True, repr=False)
class ReviewIdentity:
    """Opaque binding of a reviewed plan to the state that produced it.

    A stale-plan guard, not a security credential. ``digest`` exists so a future
    apply step can carry the identity; nothing here ever renders it.
    """

    parts: Tuple[Tuple[IdentityComponent, str], ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.parts, tuple)
                 and len(self.parts) == len(IdentityComponent)
                 and all(isinstance(p, tuple) and len(p) == 2
                         and isinstance(p[0], IdentityComponent) for p in self.parts)
                 and tuple(c for c, _ in self.parts)
                 == tuple(IdentityComponent)
                 and all(isinstance(d, str) and _SHA256.fullmatch(d) for _, d in self.parts),
                 "unsupported review identity")

    @classmethod
    def from_material(cls, material: Mapping[IdentityComponent, object]) -> "ReviewIdentity":
        """Hash each component's canonical-JSON material. Pure and deterministic."""
        _require(set(material) == set(IdentityComponent), "unsupported review identity material")
        return cls(tuple((c, _digest(material[c])) for c in IdentityComponent))

    @property
    def digest(self) -> str:
        return _digest([[c.value, d] for c, d in self.parts])

    def changed_since(self, other: "ReviewIdentity") -> Tuple[IdentityComponent, ...]:
        mine, theirs = dict(self.parts), dict(other.parts)
        return tuple(c for c in IdentityComponent if mine[c] != theirs[c])

    def __repr__(self) -> str:
        return "ReviewIdentity(<opaque>)"


@dataclass(frozen=True)
class ReviewCheck:
    """Whether an earlier review still describes what would happen now."""

    freshness: ReviewFreshness
    changed: Tuple[IdentityComponent, ...] = ()

    def __post_init__(self) -> None:
        _require(isinstance(self.freshness, ReviewFreshness), "unsupported review freshness")
        _require(isinstance(self.changed, tuple)
                 and all(isinstance(c, IdentityComponent) for c in self.changed)
                 and len(set(self.changed)) == len(self.changed),
                 "unsupported changed components")
        _require((self.freshness is ReviewFreshness.CURRENT) == (not self.changed)
                 or self.freshness is ReviewFreshness.UNVERIFIABLE,
                 "review freshness and changed components disagree")

    @property
    def is_current(self) -> bool:
        return self.freshness is ReviewFreshness.CURRENT

    @property
    def requires_new_review(self) -> bool:
        return self.freshness is not ReviewFreshness.CURRENT


# -- plan parts ------------------------------------------------------------------------------

@dataclass(frozen=True)
class SoftwareRow:
    """One managed add-on. ``version`` is the saved version an install would use."""

    addon_id: str
    action: SoftwareAction
    display_name: str = ""
    version: str = ""
    choices: Tuple[DecisionChoice, ...] = ()

    def __post_init__(self) -> None:
        _addon_id(self.addon_id, "software row id")
        _require(isinstance(self.action, SoftwareAction), "unsupported software action")
        _require(is_plain_name(self.display_name), "unsupported software row name")
        _require(self.version == "" or (isinstance(self.version, str)
                                        and _VERSION.fullmatch(self.version) is not None),
                 "unsupported software row version")
        _require(isinstance(self.choices, tuple)
                 and all(isinstance(c, DecisionChoice) for c in self.choices)
                 and len(set(self.choices)) == len(self.choices),
                 "unsupported software row choices")
        if self.action is SoftwareAction.DECISION:
            _require(DecisionChoice.CANCEL in self.choices and len(self.choices) >= 2,
                     "a decision must offer a way forward and a way to cancel")
        else:
            _require(not self.choices, "only a decision row offers choices")
        _require(self.action is not SoftwareAction.INSTALL_EXACT or self.version != "",
                 "an exact install names its version")

    @property
    def label(self) -> str:
        return self.display_name or self.addon_id


@dataclass(frozen=True)
class PlanBlocker:
    code: BlockerCode
    addon_id: str = ""
    display_name: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.code, BlockerCode), "unsupported blocker code")
        _addon_id(self.addon_id, "blocker add-on", allow_empty=True)
        _require(is_plain_name(self.display_name), "unsupported blocker name")
        _require(self.code not in ADDON_BLOCKERS or bool(self.addon_id),
                 "this blocker names the add-on it concerns")

    @property
    def category(self) -> BlockerCategory:
        return BLOCKER_CATEGORY[self.code]

    @property
    def label(self) -> str:
        return self.display_name or self.addon_id


@dataclass(frozen=True)
class SkinPlan:
    kind: SkinPlanKind
    skin_id: str = ""
    current_skin_id: str = ""
    display_name: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.kind, SkinPlanKind), "unsupported skin plan")
        _addon_id(self.skin_id, "skin", allow_empty=True)
        _addon_id(self.current_skin_id, "current skin", allow_empty=True)
        _require(is_plain_name(self.display_name), "unsupported skin name")

    @property
    def label(self) -> str:
        return self.display_name or self.skin_id


@dataclass(frozen=True)
class SettingsPlan:
    """A count only: how many managed settings and files would be written."""

    kind: SettingsPlanKind
    changing: int = 0

    def __post_init__(self) -> None:
        _require(isinstance(self.kind, SettingsPlanKind), "unsupported settings plan")
        _require(_is_count(self.changing), "unsupported settings count")
        _require((self.kind is SettingsPlanKind.CHANGES) == (self.changing > 0),
                 "settings plan and count disagree")


@dataclass(frozen=True)
class PrivatePlan:
    """Status only. Never a field name, value, or fingerprint."""

    kind: PrivatePlanKind

    def __post_init__(self) -> None:
        _require(isinstance(self.kind, PrivatePlanKind), "unsupported private plan")


@dataclass(frozen=True)
class RestartPlan:
    expectation: RestartExpectation = RestartExpectation.NOT_EXPECTED

    def __post_init__(self) -> None:
        _require(isinstance(self.expectation, RestartExpectation), "unsupported restart plan")


# -- the plan ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class BuildPlan:
    """Result of one fresh, read-only plan."""

    state: PlanState
    checked_at: str
    software: Tuple[SoftwareRow, ...]
    skin: SkinPlan
    settings: SettingsPlan
    private: PrivatePlan
    restart: RestartPlan
    blockers: Tuple[PlanBlocker, ...] = ()
    gaps: Tuple[CheckGap, ...] = ()
    review: Optional[ReviewIdentity] = None

    def __post_init__(self) -> None:
        _require(isinstance(self.state, PlanState), "unsupported plan state")
        _require(isinstance(self.checked_at, str) and _TIMESTAMP.fullmatch(self.checked_at) is not None,
                 "unsupported plan time")
        _require(isinstance(self.software, tuple) and len(self.software) <= MAX_SOFTWARE_ROWS
                 and all(isinstance(r, SoftwareRow) for r in self.software), "unsupported software rows")
        _require(len({r.addon_id for r in self.software}) == len(self.software), "duplicate software row")
        for value, kind in ((self.skin, SkinPlan), (self.settings, SettingsPlan),
                            (self.private, PrivatePlan), (self.restart, RestartPlan)):
            _require(isinstance(value, kind), "unsupported plan section")
        _require(isinstance(self.blockers, tuple) and len(self.blockers) <= MAX_BLOCKERS
                 and all(isinstance(b, PlanBlocker) for b in self.blockers), "unsupported blockers")
        _require(isinstance(self.gaps, tuple) and len(self.gaps) <= len(CheckGap)
                 and all(isinstance(g, CheckGap) for g in self.gaps)
                 and len(set(self.gaps)) == len(self.gaps), "unsupported plan gaps")
        _require(self.review is None or isinstance(self.review, ReviewIdentity), "unsupported review")
        for row in self.software:      # a blocked row needs its matching blocker
            code = _ACTION_BLOCKER.get(row.action)
            if code is not None:
                _require(any(b.code is code and b.addon_id == row.addon_id for b in self.blockers),
                         "a blocked software row needs its blocker")
            elif row.action is SoftwareAction.BLOCKED:
                _require(any(b.addon_id == row.addon_id for b in self.blockers),
                         "a blocked software row needs its blocker")
        _require(self.review is None or self.state is PlanState.CHANGES_READY,
                 "only a plan that is ready for approval carries a review identity")
        unavailable = (
            self.skin.kind is SkinPlanKind.UNAVAILABLE
            or self.settings.kind is SettingsPlanKind.UNAVAILABLE
            or self.private.kind is PrivatePlanKind.UNAVAILABLE
            or any(r.action is SoftwareAction.UNAVAILABLE for r in self.software)
        )
        if self.state is PlanState.BLOCKED:
            _require(bool(self.blockers), "a blocked plan names its blockers")
        else:
            _require(not self.blockers and not any(r.action in BLOCKING_ACTIONS for r in self.software),
                     "only a blocked plan carries blockers")
        if self.state is PlanState.INCOMPLETE:
            _require(bool(self.gaps) or unavailable, "an incomplete plan says what was not checked")
        if self.state in (PlanState.DECISION_REQUIRED, PlanState.RESOLUTION_REQUIRED,
                          PlanState.CHANGES_READY, PlanState.NO_CHANGES):
            _require(not self.gaps and not unavailable,
                     "a plan with unchecked areas cannot be ready")
        has_decision = any(r.action is SoftwareAction.DECISION for r in self.software)
        _require(has_decision == (self.state is PlanState.DECISION_REQUIRED)
                 or self.state in (PlanState.BLOCKED, PlanState.INCOMPLETE),
                 "decisions and plan state disagree")
        unresolved = any(r.action is SoftwareAction.INSTALL_REPOSITORY for r in self.software)
        _require(unresolved == (self.state is PlanState.RESOLUTION_REQUIRED)
                 or self.state in (PlanState.BLOCKED, PlanState.INCOMPLETE, PlanState.DECISION_REQUIRED),
                 "unresolved packages and plan state disagree")
        if self.state in (PlanState.CHANGES_READY, PlanState.NO_CHANGES):
            _require(self.has_changes == (self.state is PlanState.CHANGES_READY),
                     "changes and plan state disagree")
            _require(self.compared, "a plan that compared nothing proves nothing")

    # -- derived views -----------------------------------------------------------------------

    @property
    def has_changes(self) -> bool:
        return (
            any(r.action in CHANGE_ACTIONS for r in self.software)
            or self.skin.kind is SkinPlanKind.SWITCH
            or self.settings.kind is SettingsPlanKind.CHANGES
            or self.private.kind is PrivatePlanKind.CHANGES_NEEDED
        )

    @property
    def compared(self) -> bool:
        """Something real was compared (a plan of only not-applicable areas proves nothing)."""
        return (
            any(r.action is not SoftwareAction.ACCEPTED_SKIP for r in self.software)
            or self.skin.kind not in (SkinPlanKind.NOT_APPLICABLE, SkinPlanKind.UNAVAILABLE)
            or self.settings.kind not in (SettingsPlanKind.NOT_APPLICABLE, SettingsPlanKind.UNAVAILABLE)
            or self.private.kind not in (PrivatePlanKind.NOT_USED, PrivatePlanKind.UNAVAILABLE)
        )

    @property
    def decisions(self) -> Tuple[SoftwareRow, ...]:
        return tuple(r for r in self.software if r.action is SoftwareAction.DECISION)

    @property
    def can_proceed(self) -> bool:
        """True only for a reviewed, fully-checked plan with work to do and nothing in the way."""
        return self.state is PlanState.CHANGES_READY and self.review is not None

    def checked_time_label(self) -> str:
        """Local ``HH:MM`` of the check, for display; ``""`` if it cannot be converted."""
        try:
            moment = datetime.strptime(self.checked_at, "%Y-%m-%dT%H:%M:%SZ")
            return moment.replace(tzinfo=timezone.utc).astimezone().strftime("%H:%M")
        except (ValueError, OverflowError, OSError):
            return ""

    def identity_material(self) -> dict:
        """Everything that defines what would happen, excluding the check time."""
        return {
            "state": self.state.value,
            "software": [[r.addon_id, r.action.value, r.version, [c.value for c in r.choices]]
                         for r in self.software],
            "skin": [self.skin.kind.value, self.skin.skin_id, self.skin.current_skin_id],
            "settings": [self.settings.kind.value, self.settings.changing],
            "private": self.private.kind.value,
            "restart": self.restart.expectation.value,
            "blockers": [[b.code.value, b.addon_id] for b in self.blockers],
            "gaps": [g.value for g in self.gaps],
        }

    def to_safe_dict(self) -> dict:
        """Serializable evidence form: enum values, counts, validated identifiers."""
        return {
            "state": self.state.value,
            "checked_at": self.checked_at,
            "software": [{"addon_id": r.addon_id, "action": r.action.value,
                          "display_name": r.display_name, "version": r.version,
                          "choices": [c.value for c in r.choices]} for r in self.software],
            "skin": {"kind": self.skin.kind.value, "skin_id": self.skin.skin_id,
                     "current_skin_id": self.skin.current_skin_id,
                     "display_name": self.skin.display_name},
            "settings": {"kind": self.settings.kind.value, "changing": self.settings.changing},
            "private": {"kind": self.private.kind.value},
            "restart": {"expectation": self.restart.expectation.value},
            "blockers": [{"code": b.code.value, "category": b.category.value,
                          "addon_id": b.addon_id, "display_name": b.display_name}
                         for b in self.blockers],
            "gaps": [g.value for g in self.gaps],
            "reviewed": self.review is not None,
        }
