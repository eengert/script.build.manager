"""Plain-language Review Changes presentation. Secret-blind by construction.

Consumes only the stdlib-only ``plan_model`` contract and produces localized
string identifiers plus validated add-on names, versions and counts. Nothing
here imports an engine, backend, or private-data owner, and a ``Text`` can only
reference an allowlisted string identifier. The page is review-only: nothing
here can offer, start or imply an operation.
"""
from dataclasses import dataclass

from resources.lib.plan_model import (
    BlockerCode, BuildPlan, DecisionChoice, PlanState, PrivatePlanKind, RestartExpectation,
    SettingsPlanKind, SkinPlanKind, SoftwareAction,
)
from resources.lib.status_model import CheckGap
from resources.lib.ui.models import Semantic
from resources.lib.ui.status_view import GAP_TEXT, S_CHECKED_AT, S_CLOSE, S_MORE_ITEMS

# -- localized string identifiers (resource.language.en_gb/strings.po) -----------------------
TITLE = {
    PlanState.CHANGES_READY: 32600, PlanState.BLOCKED: 32601, PlanState.NO_CHANGES: 32602,
    PlanState.DECISION_REQUIRED: 32603, PlanState.INCOMPLETE: 32604, PlanState.RESOLUTION_REQUIRED: 32605,
}
SEMANTIC = {
    PlanState.CHANGES_READY: Semantic.WARNING, PlanState.BLOCKED: Semantic.BLOCKED,
    PlanState.NO_CHANGES: Semantic.VERIFIED, PlanState.DECISION_REQUIRED: Semantic.WARNING,
    PlanState.INCOMPLETE: Semantic.INCOMPLETE,
    PlanState.RESOLUTION_REQUIRED: Semantic.INCOMPLETE,
}
S_ADDONS, S_SKIN, S_SETTINGS, S_PRIVATE, S_RESTART = 32610, 32611, 32612, 32613, 32614
SOFTWARE_LINE = {
    SoftwareAction.INSTALL_EXACT: 32620, SoftwareAction.INSTALL_REPOSITORY: 32621,
    SoftwareAction.ENABLE: 32622, SoftwareAction.DISABLE: 32623, SoftwareAction.ACCEPTED_SKIP: 32624,
    SoftwareAction.DECISION: 32625,
}
S_CURRENT_MANY, S_CURRENT_ONE, S_UNCHECKED_ADDON, S_ALL_MATCH = 32626, 32627, 32628, 32629
SKIN_LINE = {SkinPlanKind.SWITCH: 32630, SkinPlanKind.CURRENT: 32631, SkinPlanKind.UNAVAILABLE: 32632}
S_SETTINGS_MANY, S_SETTINGS_ONE = 32640, 32641
SETTINGS_LINE = {SettingsPlanKind.CURRENT: 32642, SettingsPlanKind.UNAVAILABLE: 32643}
PRIVATE_LINE = {
    PrivatePlanKind.CHANGES_NEEDED: 32650, PrivatePlanKind.CURRENT: 32651,
    PrivatePlanKind.UNAVAILABLE: 32652,
}
S_RESTART_EXPECTED = 32660
BLOCKER_LINE = {            # one line per blocker; an add-on name fills the %s where there is one
    BlockerCode.DIFFERENT_VERSION_INSTALLED: 32670, BlockerCode.INSTALLED_ADDON_BROKEN: 32671,
    BlockerCode.PACKAGE_MISSING: 32672, BlockerCode.ADDON_NOT_IN_SAVED_SOFTWARE: 32673,
    BlockerCode.SKIPPED_ADDON_PRESENT: 32674, BlockerCode.CHOICE_NOT_PERMITTED: 32675,
    BlockerCode.CHOICE_CONFLICTS_WITH_BUILD: 32676, BlockerCode.USER_CANCELLED: 32677,
    BlockerCode.SOFTWARE_PLAN_INVALID: 32678, BlockerCode.BUILD_DEFINITION_INVALID: 32679,
    BlockerCode.PRIVATE_DATA_MISSING: 32680, BlockerCode.PRIVATE_DATA_UNUSABLE: 32681,
    BlockerCode.OPERATION_PENDING: 32682, BlockerCode.OPERATION_NEEDS_ATTENTION: 32683,
}
NAMED_BLOCKERS = frozenset({
    BlockerCode.DIFFERENT_VERSION_INSTALLED, BlockerCode.INSTALLED_ADDON_BROKEN,
    BlockerCode.PACKAGE_MISSING, BlockerCode.ADDON_NOT_IN_SAVED_SOFTWARE,
    BlockerCode.SKIPPED_ADDON_PRESENT, BlockerCode.CHOICE_NOT_PERMITTED,
    BlockerCode.CHOICE_CONFLICTS_WITH_BUILD, BlockerCode.USER_CANCELLED,
})
S_BLOCKER_GENERIC = 32684
S_DECISION_HEADING = 32690
CHOICE_LABEL = {
    DecisionChoice.INSTALL_CURRENT: 32691, DecisionChoice.SKIP: 32692, DecisionChoice.CANCEL: 32693,
}

PLAN_TEXT_IDS = frozenset(
    [32606, S_CLOSE, S_MORE_ITEMS, S_CHECKED_AT, S_ADDONS, S_SKIN, S_SETTINGS, S_PRIVATE, S_RESTART,
     S_CURRENT_MANY, S_CURRENT_ONE, S_UNCHECKED_ADDON, S_ALL_MATCH, S_SETTINGS_MANY,
     S_SETTINGS_ONE, S_RESTART_EXPECTED, S_BLOCKER_GENERIC, S_DECISION_HEADING]
    + list(TITLE.values()) + list(SOFTWARE_LINE.values()) + list(SKIN_LINE.values())
    + list(SETTINGS_LINE.values()) + list(PRIVATE_LINE.values()) + list(BLOCKER_LINE.values())
    + list(CHOICE_LABEL.values()) + list(GAP_TEXT.values()))

MAX_LISTED = 15


@dataclass(frozen=True)
class Text:
    """A localized string reference with optional, constrained arguments.

    Placeholders are filled in this order: ``name`` (a validated add-on or skin
    name, optionally followed by a validated version), then each ``refs`` entry
    (an allowlisted string identifier, rendered localized), then ``count``.
    """
    string_id: int
    count: int = -1
    name: str = ''
    refs: tuple = ()

    def __post_init__(self):
        if type(self.string_id) is not int or self.string_id not in PLAN_TEXT_IDS:
            raise ValueError('unsupported plan text')
        if type(self.count) is not int or not -1 <= self.count <= 100000:
            raise ValueError('unsupported plan count')
        if not isinstance(self.name, str) or len(self.name) > 140:
            raise ValueError('unsupported plan name')
        if not isinstance(self.refs, tuple) or len(self.refs) > 2 or any(
                type(r) is not int or r not in PLAN_TEXT_IDS for r in self.refs):
            raise ValueError('unsupported plan text')


@dataclass(frozen=True)
class ReviewSection:
    heading: object         # a Text, or None when the page title already says it
    lines: tuple


@dataclass(frozen=True)
class DecisionPrompt:
    """One add-on the user must decide about before the review can be shown."""
    addon_id: str
    heading: Text
    choices: tuple          # DecisionChoice values, in the order offered


@dataclass(frozen=True)
class ReviewViewModel:
    state: PlanState
    semantic: Semantic
    title: Text
    sections: tuple
    decisions: tuple
    check_time: str

    @classmethod
    def unavailable(cls):
        """Shown when a plan could not even start; no exception text is kept."""
        state = PlanState.INCOMPLETE
        return cls(state, SEMANTIC[state], Text(TITLE[state]),
                   (ReviewSection(None, (Text(GAP_TEXT[CheckGap.INSPECTION_FAILED]),)),),
                   (), '')

    @classmethod
    def from_plan(cls, plan):
        if not isinstance(plan, BuildPlan):
            raise ValueError('unsupported plan')
        sections, decisions = _sections(plan), ()
        if plan.state is PlanState.DECISION_REQUIRED:
            decisions = tuple(
                DecisionPrompt(row.addon_id, Text(S_DECISION_HEADING, name=row.label), row.choices)
                for row in plan.decisions)
        return cls(plan.state, SEMANTIC[plan.state], Text(TITLE[plan.state]), sections, decisions,
                   plan.checked_time_label())


def _capped(lines):
    lines = list(lines)
    if len(lines) > MAX_LISTED:
        lines = lines[:MAX_LISTED] + [Text(S_MORE_ITEMS, len(lines) - MAX_LISTED)]
    return tuple(lines)


def _sections(plan):
    if plan.state is PlanState.RESOLUTION_REQUIRED:
        return (ReviewSection(None, (Text(32606),)),)
    if plan.state is PlanState.NO_CHANGES:
        kept = [Text(SOFTWARE_LINE[r.action], name=r.label) for r in plan.software
                if r.action is SoftwareAction.ACCEPTED_SKIP]
        return (ReviewSection(Text(S_ADDONS), _capped([Text(S_ALL_MATCH)] + kept)),)
    if plan.state is PlanState.BLOCKED:
        return (ReviewSection(None, _capped(_blocker_text(b) for b in plan.blockers)),)
    if plan.state is PlanState.INCOMPLETE:
        lines = [Text(S_UNCHECKED_ADDON, name=r.label) for r in plan.software
                 if r.action is SoftwareAction.UNAVAILABLE]
        if plan.skin.kind is SkinPlanKind.UNAVAILABLE:
            lines.append(Text(SKIN_LINE[SkinPlanKind.UNAVAILABLE]))
        if plan.settings.kind is SettingsPlanKind.UNAVAILABLE:
            lines.append(Text(SETTINGS_LINE[SettingsPlanKind.UNAVAILABLE]))
        if plan.private.kind is PrivatePlanKind.UNAVAILABLE:
            lines.append(Text(PRIVATE_LINE[PrivatePlanKind.UNAVAILABLE]))
        lines += [Text(GAP_TEXT[g]) for g in plan.gaps if g in GAP_TEXT]
        if not lines:
            lines.append(Text(GAP_TEXT[CheckGap.INSPECTION_FAILED]))
        return (ReviewSection(None, _capped(lines)),)
    sections = []
    listed = [Text(SOFTWARE_LINE[r.action], name=_row_name(r)) for r in plan.software
              if r.action in SOFTWARE_LINE]
    current = len([r for r in plan.software if r.action is SoftwareAction.CURRENT])
    if current:
        listed.append(Text(S_CURRENT_ONE) if current == 1 else Text(S_CURRENT_MANY, current))
    if listed:
        sections.append(ReviewSection(Text(S_ADDONS), _capped(listed)))
    skin = plan.skin
    if skin.kind in SKIN_LINE:
        sections.append(ReviewSection(Text(S_SKIN), (Text(
            SKIN_LINE[skin.kind], name=skin.label if skin.kind is not SkinPlanKind.UNAVAILABLE else ''),)))
    settings = plan.settings
    if settings.kind is SettingsPlanKind.CHANGES:
        line = Text(S_SETTINGS_ONE) if settings.changing == 1 else Text(S_SETTINGS_MANY, settings.changing)
        sections.append(ReviewSection(Text(S_SETTINGS), (line,)))
    elif settings.kind in SETTINGS_LINE:
        sections.append(ReviewSection(Text(S_SETTINGS), (Text(SETTINGS_LINE[settings.kind]),)))
    if plan.private.kind in PRIVATE_LINE:
        sections.append(ReviewSection(Text(S_PRIVATE), (Text(PRIVATE_LINE[plan.private.kind]),)))
    if plan.restart.expectation is RestartExpectation.EXPECTED:
        sections.append(ReviewSection(Text(S_RESTART), (Text(S_RESTART_EXPECTED),)))
    return tuple(sections)


def _row_name(row):
    """Name, then the saved version when the line installs one: ``Red Light 2.6.8``."""
    if row.action is SoftwareAction.INSTALL_EXACT and row.version:
        return (row.label + ' ' + row.version)[:140]
    return row.label


def _blocker_text(blocker):
    if blocker.code in NAMED_BLOCKERS:
        if blocker.label:
            return Text(BLOCKER_LINE[blocker.code], name=blocker.label)
        return Text(S_BLOCKER_GENERIC)
    return Text(BLOCKER_LINE[blocker.code])
