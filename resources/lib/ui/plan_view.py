"""Plain-language Review Changes presentation. Secret-blind by construction.

Consumes only the stdlib-only ``plan_model`` contract and produces localized
string identifiers plus validated add-on names, versions and counts. Nothing
here imports an engine, backend, or private-data owner, and a ``Text`` can only
reference an allowlisted string identifier. The page is review-only: nothing
here can offer, start or imply an operation.
"""
from dataclasses import dataclass
from typing import Optional

from resources.lib.plan_model import (
    BlockerCode, BuildPlan, CHANGE_ACTIONS, DecisionChoice, MAX_COUNT, MAX_SOFTWARE_ROWS,
    PlanState, PrivatePlanKind, RestartExpectation, SettingsPlanKind, SkinPlanKind, SoftwareAction,
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
S_CONFIRMATION_SUMMARY = 32694
CHOICE_LABEL = {
    DecisionChoice.INSTALL_CURRENT: 32691, DecisionChoice.SKIP: 32692, DecisionChoice.CANCEL: 32693,
}

PLAN_TEXT_IDS = frozenset(
    [32606, S_CLOSE, S_MORE_ITEMS, S_CHECKED_AT, S_ADDONS, S_SKIN, S_SETTINGS, S_PRIVATE, S_RESTART,
     S_CURRENT_MANY, S_CURRENT_ONE, S_UNCHECKED_ADDON, S_ALL_MATCH, S_SETTINGS_MANY,
     S_SETTINGS_ONE, S_RESTART_EXPECTED, S_BLOCKER_GENERIC, S_DECISION_HEADING,
     S_CONFIRMATION_SUMMARY]
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
class ConfirmationSummary:
    """Safe compact summary for the initial viewport of the final confirmation."""
    single_change: Optional[Text]
    change_count: int
    accepted_skip_count: int

    def __post_init__(self):
        max_changes = MAX_COUNT + MAX_SOFTWARE_ROWS + 2
        if (self.single_change is not None and not isinstance(self.single_change, Text)):
            raise ValueError('unsupported confirmation change')
        if type(self.change_count) is not int or not 0 <= self.change_count <= max_changes:
            raise ValueError('unsupported confirmation change count')
        if (type(self.accepted_skip_count) is not int
                or not 0 <= self.accepted_skip_count <= MAX_SOFTWARE_ROWS):
            raise ValueError('unsupported confirmation exception count')
        if self.single_change is not None and (self.change_count != 1 or self.accepted_skip_count):
            raise ValueError('a direct confirmation change must be the only reviewed item')


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
    confirmation_summary: ConfirmationSummary

    @classmethod
    def unavailable(cls):
        """Shown when a plan could not even start; no exception text is kept."""
        state = PlanState.INCOMPLETE
        return cls(state, SEMANTIC[state], Text(TITLE[state]),
                   (ReviewSection(None, (Text(GAP_TEXT[CheckGap.INSPECTION_FAILED]),)),),
                   (), '', ConfirmationSummary(None, 0, 0))

    @classmethod
    def from_plan(cls, plan, repository_current=(), fully_listed=False):
        if not isinstance(plan, BuildPlan):
            raise ValueError('unsupported plan')
        sections, decisions = _sections(plan, repository_current, fully_listed), ()
        if plan.state is PlanState.DECISION_REQUIRED:
            decisions = tuple(
                DecisionPrompt(row.addon_id, Text(S_DECISION_HEADING, name=row.label), row.choices)
                for row in plan.decisions)
        return cls(plan.state, SEMANTIC[plan.state], Text(TITLE[plan.state]), sections, decisions,
                   plan.checked_time_label(), _confirmation_summary(plan, repository_current))


def _confirmation_summary(plan, repository_current=()):
    changes = []
    change_count = 0
    accepted_skip_count = 0
    for row in plan.software:
        if row.action in CHANGE_ACTIONS:
            string_id = (32621 if row.action is SoftwareAction.INSTALL_EXACT
                         and row.addon_id in repository_current else SOFTWARE_LINE[row.action])
            changes.append(Text(string_id, name=_row_name(row)))
            change_count += 1
        elif row.action is SoftwareAction.ACCEPTED_SKIP:
            accepted_skip_count += 1
    if plan.skin.kind is SkinPlanKind.SWITCH:
        changes.append(Text(SKIN_LINE[SkinPlanKind.SWITCH], name=plan.skin.label))
        change_count += 1
    if plan.settings.kind is SettingsPlanKind.CHANGES:
        changes.append(Text(S_SETTINGS_ONE) if plan.settings.changing == 1
                       else Text(S_SETTINGS_MANY, plan.settings.changing))
        change_count += plan.settings.changing
    if plan.private.kind is PrivatePlanKind.CHANGES_NEEDED:
        changes.append(Text(PRIVATE_LINE[PrivatePlanKind.CHANGES_NEEDED]))
        change_count += 1
    single_change = changes[0] if change_count == 1 and accepted_skip_count == 0 else None
    return ConfirmationSummary(single_change, change_count, accepted_skip_count)


def _capped(lines):
    lines = list(lines)
    if len(lines) > MAX_LISTED:
        lines = lines[:MAX_LISTED] + [Text(S_MORE_ITEMS, len(lines) - MAX_LISTED)]
    return tuple(lines)


def _sections(plan, repository_current=(), fully_listed=False):
    def listed_lines(lines):
        return tuple(lines) if fully_listed else _capped(lines)
    if plan.state is PlanState.RESOLUTION_REQUIRED:
        return (ReviewSection(None, (Text(32606),)),)
    if plan.state is PlanState.NO_CHANGES:
        kept = [Text(SOFTWARE_LINE[r.action], name=r.label) for r in plan.software
                if r.action is SoftwareAction.ACCEPTED_SKIP]
        return (ReviewSection(Text(S_ADDONS), listed_lines([Text(S_ALL_MATCH)] + kept)),)
    if plan.state is PlanState.BLOCKED:
        return (ReviewSection(None, listed_lines(_blocker_text(b) for b in plan.blockers)),)
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
        return (ReviewSection(None, listed_lines(lines)),)
    sections = []
    listed = [Text(32621 if r.addon_id in repository_current and r.action is SoftwareAction.INSTALL_EXACT
                   else SOFTWARE_LINE[r.action], name=_row_name(r)) for r in plan.software
              if r.action in SOFTWARE_LINE]
    current = len([r for r in plan.software if r.action is SoftwareAction.CURRENT])
    if current:
        listed.append(Text(S_CURRENT_ONE) if current == 1 else Text(S_CURRENT_MANY, current))
    if listed:
        sections.append(ReviewSection(Text(S_ADDONS), listed_lines(listed)))
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
    if row.action in (SoftwareAction.INSTALL_EXACT, SoftwareAction.INSTALL_REPOSITORY) and row.version:
        return (row.label + ' ' + row.version)[:140]
    return row.label


def _blocker_text(blocker):
    if blocker.code in NAMED_BLOCKERS:
        if blocker.label:
            return Text(BLOCKER_LINE[blocker.code], name=blocker.label)
        return Text(S_BLOCKER_GENERIC)
    return Text(BLOCKER_LINE[blocker.code])
