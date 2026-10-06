"""Plain-language Build Status presentation. Secret-blind by construction.

Consumes only the stdlib-only ``status_model`` contract and produces localized
string identifiers plus integer counts and validated add-on names. Nothing
here imports an engine, backend, or private-data owner, and a ``Text`` can
only reference an allowlisted string identifier.
"""
from dataclasses import dataclass
from resources.lib.status_model import (
    AreaLevel, BuildStatus, CheckGap, OperationCode, OperationKind, OverallStatus,
    PrivateItemKind, SoftwareItemState,
)
from resources.lib.ui.models import Semantic

# -- localized string identifiers (resource.language.en_gb/strings.po) -----------
S_OVERALL, S_ADDONS, S_SKIN, S_SETTINGS, S_PRIVATE = 32401, 32402, 32403, 32404, 32405
S_ROW = 32406                                           # "%s: %s"
S_CHECK_AGAIN, S_CLOSE = 32440, 32441
S_ADDONS_PLURAL, S_ADDONS_ONE = 32424, 32425            # "%d need attention" / "1 needs attention"
S_BULLET_ADDONS_PLURAL, S_BULLET_ADDONS_ONE = 32461, 32462
S_MORE_ITEMS, S_ITEM_LINE = 32494, 32495                # "…and %d more" / "• %s — %s"
S_ALL_ADDONS_MATCH, S_ADDONS_NOT_USED = 32496, 32497
S_SKIN_BUILD, S_SKIN_ACTIVE, S_SKIN_NONE = 32500, 32501, 32502
S_CFG_TOTAL, S_CFG_DIFFERING, S_CFG_UNREADABLE, S_CFG_NONE = 32510, 32511, 32512, 32513
S_PRIVATE_LINE, S_PRIVATE_NONE = 32525, 32526           # "• %s: %s"
S_PROTECTION, S_CHECKED_AT = 32534, 32540

OVERALL_LABEL = {
    OverallStatus.CURRENT: 32430, OverallStatus.CHANGES_NEEDED: 32431,
    OverallStatus.RESTART_REQUIRED: 32432, OverallStatus.NEEDS_ATTENTION: 32433,
    OverallStatus.INCOMPLETE: 32434,
}
OVERALL_SENTENCE = {
    OverallStatus.CURRENT: 32450, OverallStatus.CHANGES_NEEDED: 32451,
    OverallStatus.RESTART_REQUIRED: 32452, OverallStatus.NEEDS_ATTENTION: 32453,
    OverallStatus.INCOMPLETE: 32454,
}
OVERALL_SEMANTIC = {
    OverallStatus.CURRENT: Semantic.VERIFIED, OverallStatus.CHANGES_NEEDED: Semantic.WARNING,
    OverallStatus.RESTART_REQUIRED: Semantic.WARNING,
    OverallStatus.NEEDS_ATTENTION: Semantic.NEEDS_ATTENTION,
    OverallStatus.INCOMPLETE: Semantic.INCOMPLETE,
}
AREA_STATE = {
    AreaLevel.CURRENT: 32420, AreaLevel.CHANGES_NEEDED: 32421,
    AreaLevel.UNAVAILABLE: 32422, AreaLevel.NOT_APPLICABLE: 32423,
}
BULLET = {                                              # area -> {level: id}
    'addons': {AreaLevel.CURRENT: 32460, AreaLevel.UNAVAILABLE: 32463},
    'skin': {AreaLevel.CURRENT: 32465, AreaLevel.CHANGES_NEEDED: 32466,
             AreaLevel.UNAVAILABLE: 32467},
    'settings': {AreaLevel.CURRENT: 32468, AreaLevel.CHANGES_NEEDED: 32469,
                 AreaLevel.UNAVAILABLE: 32470},
    'private': {AreaLevel.CURRENT: 32471, AreaLevel.CHANGES_NEEDED: 32472,
                AreaLevel.UNAVAILABLE: 32473},
}
GAP_TEXT = {
    CheckGap.NO_BUILD_SELECTED: 32480, CheckGap.BUILD_UNREADABLE: 32481,
    CheckGap.KODI_STATE_UNAVAILABLE: 32482, CheckGap.CONFIGURATION_UNAVAILABLE: 32483,
    CheckGap.PRIVATE_DATA_MISSING: 32484, CheckGap.PRIVATE_DATA_UNUSABLE: 32485,
    CheckGap.PRIVATE_UNAVAILABLE: 32486, CheckGap.OPERATION_STATE_UNAVAILABLE: 32487,
    CheckGap.INSPECTION_FAILED: 32488, CheckGap.SOFTWARE_UNAVAILABLE: 32489,
    CheckGap.NOTHING_TO_COMPARE: 32498, CheckGap.BUILD_IDENTITY_MISMATCH: 32541,
    CheckGap.RESOLUTION_IDENTITY_MISMATCH: 32542,
}
ITEM_STATE = {
    SoftwareItemState.MISSING: 32490, SoftwareItemState.WRONG_VERSION: 32491,
    SoftwareItemState.WRONG_ENABLED_STATE: 32492, SoftwareItemState.UNCHECKABLE: 32493,
}
PRIVATE_KIND = {PrivateItemKind.SETTINGS: 32520, PrivateItemKind.RESOURCE: 32521}
OPERATION_TEXT = {     # TRANSACTION_UNREADABLE is explained by its check gap instead
    OperationCode.RESUME_PENDING: 32530, OperationCode.OPERATION_NOT_FINISHED: 32531,
    OperationCode.TRANSACTION_INVALID: 32532,
}

STATUS_TEXT_IDS = frozenset(
    [S_OVERALL, S_ADDONS, S_SKIN, S_SETTINGS, S_PRIVATE, S_ROW, S_CHECK_AGAIN, S_CLOSE,
     S_ADDONS_PLURAL, S_ADDONS_ONE, S_BULLET_ADDONS_PLURAL, S_BULLET_ADDONS_ONE, S_MORE_ITEMS,
     S_ITEM_LINE, S_ALL_ADDONS_MATCH, S_ADDONS_NOT_USED, S_SKIN_BUILD, S_SKIN_ACTIVE,
     S_SKIN_NONE, S_CFG_TOTAL, S_CFG_DIFFERING, S_CFG_UNREADABLE, S_CFG_NONE, S_PRIVATE_LINE,
     S_PRIVATE_NONE, S_PROTECTION, S_CHECKED_AT, 32103, 32112]
    + list(OVERALL_LABEL.values()) + list(OVERALL_SENTENCE.values())
    + list(AREA_STATE.values()) + list(GAP_TEXT.values()) + list(ITEM_STATE.values())
    + list(PRIVATE_KIND.values()) + list(OPERATION_TEXT.values())
    + [i for table in BULLET.values() for i in table.values()])

MAX_LISTED_ADDONS = 15


@dataclass(frozen=True)
class Text:
    """A localized string reference with optional, constrained arguments.

    Placeholders are filled in this order: ``name`` (a validated add-on or skin
    identifier, or a bounded display name), then each ``refs`` entry (itself an
    allowlisted string identifier, rendered localized), then ``count``.
    """
    string_id: int
    count: int = -1
    name: str = ''
    refs: tuple = ()

    def __post_init__(self):
        if type(self.string_id) is not int or self.string_id not in STATUS_TEXT_IDS:
            raise ValueError('unsupported status text')
        if type(self.count) is not int or not -1 <= self.count <= 100000:
            raise ValueError('unsupported status count')
        if not isinstance(self.name, str) or len(self.name) > 100:
            raise ValueError('unsupported status name')
        if not isinstance(self.refs, tuple) or len(self.refs) > 2 or any(
                type(r) is not int or r not in STATUS_TEXT_IDS for r in self.refs):
            raise ValueError('unsupported status text')


@dataclass(frozen=True)
class StatusRow:
    """One selectable line (``label: state``) and the lines of its detail page."""
    label: Text
    state: Text
    detail: tuple


@dataclass(frozen=True)
class StatusViewModel:
    overall: OverallStatus
    semantic: Semantic
    rows: tuple          # Overall, Add-ons, Skin, Settings, Private settings
    check_time: str      # local HH:MM, or ''

    @classmethod
    def unavailable(cls):
        """Shown when a check could not even start; no exception text is kept."""
        overall = OverallStatus.INCOMPLETE
        state = Text(AREA_STATE[AreaLevel.UNAVAILABLE])
        rows = (StatusRow(Text(S_OVERALL), Text(OVERALL_LABEL[overall]),
                          (Text(OVERALL_SENTENCE[overall]),
                           Text(GAP_TEXT[CheckGap.INSPECTION_FAILED]))),)
        for label, area in ((S_ADDONS, 'addons'), (S_SKIN, 'skin'),
                            (S_SETTINGS, 'settings'), (S_PRIVATE, 'private')):
            rows += (StatusRow(Text(label), state,
                               (_bullet(area, AreaLevel.UNAVAILABLE),)),)
        return cls(overall, OVERALL_SEMANTIC[overall], rows, '')

    @classmethod
    def from_status(cls, status):
        if not isinstance(status, BuildStatus):
            raise ValueError('unsupported status')
        overall = StatusRow(Text(S_OVERALL), Text(OVERALL_LABEL[status.overall]),
                            _overall_detail(status))
        return cls(status.overall, OVERALL_SEMANTIC[status.overall],
                   (overall, _addons_row(status), _skin_row(status),
                    _settings_row(status), _private_row(status)),
                   status.checked_time_label())


def _drift_count(status):
    return len([i for i in status.software.items
                if i.state not in (SoftwareItemState.CURRENT, SoftwareItemState.UNCHECKABLE)])


def _bullet(area, level, count=0):
    if area == 'addons' and level is AreaLevel.CHANGES_NEEDED:
        return Text(S_BULLET_ADDONS_ONE) if count == 1 else Text(S_BULLET_ADDONS_PLURAL, count)
    return Text(BULLET[area][level])


def _addons_row(status):
    software = status.software
    count = _drift_count(status)
    if software.level is AreaLevel.CHANGES_NEEDED:
        state = Text(S_ADDONS_ONE) if count == 1 else Text(S_ADDONS_PLURAL, count)
    else:
        state = Text(AREA_STATE[software.level])
    if software.level is AreaLevel.NOT_APPLICABLE:
        return StatusRow(Text(S_ADDONS), state, (Text(S_ADDONS_NOT_USED),))
    attention = software.needs_attention
    lines = [Text(S_ITEM_LINE, name=item.label, refs=(ITEM_STATE[item.state],))
             for item in attention[:MAX_LISTED_ADDONS]]
    if len(attention) > MAX_LISTED_ADDONS:
        lines.append(Text(S_MORE_ITEMS, len(attention) - MAX_LISTED_ADDONS))
    if not lines:
        lines.append(Text(S_ALL_ADDONS_MATCH) if software.level is AreaLevel.CURRENT
                     else _bullet('addons', AreaLevel.UNAVAILABLE))
    return StatusRow(Text(S_ADDONS), state, tuple(lines))


def _skin_row(status):
    skin = status.skin
    state = Text(AREA_STATE[skin.level])
    if skin.level is AreaLevel.NOT_APPLICABLE:
        return StatusRow(Text(S_SKIN), state, (Text(S_SKIN_NONE),))
    lines = []
    if skin.expected_skin:
        lines.append(Text(S_SKIN_BUILD, name=skin.expected_skin))
    if skin.current_skin:
        lines.append(Text(S_SKIN_ACTIVE, name=skin.current_skin))
    if not lines:
        lines.append(_bullet('skin', AreaLevel.UNAVAILABLE))
    return StatusRow(Text(S_SKIN), state, tuple(lines))


def _settings_row(status):
    config = status.configuration
    state = Text(AREA_STATE[config.level])
    if config.level is AreaLevel.NOT_APPLICABLE:
        return StatusRow(Text(S_SETTINGS), state, (Text(S_CFG_NONE),))
    if config.level is AreaLevel.UNAVAILABLE and not config.total:
        return StatusRow(Text(S_SETTINGS), state, (_bullet('settings', AreaLevel.UNAVAILABLE),))
    lines = [Text(S_CFG_TOTAL, config.total)]
    if config.differing:
        lines.append(Text(S_CFG_DIFFERING, config.differing))
    if config.unreadable:
        lines.append(Text(S_CFG_UNREADABLE, config.unreadable))
    return StatusRow(Text(S_SETTINGS), state, tuple(lines))


def _private_row(status):
    private = status.private
    state = Text(AREA_STATE[private.level])
    if private.level is AreaLevel.NOT_APPLICABLE:
        return StatusRow(Text(S_PRIVATE), state, (Text(S_PRIVATE_NONE),))
    lines = [Text(S_PRIVATE_LINE, refs=(PRIVATE_KIND[item.kind], AREA_STATE[item.level]))
             for item in private.items]
    if not lines:
        lines.append(_bullet('private', AreaLevel.UNAVAILABLE))
    return StatusRow(Text(S_PRIVATE), state, tuple(lines))


def _overall_detail(status):
    lines = [Text(OVERALL_SENTENCE[status.overall])]
    operation = status.operation
    if operation.kind is not OperationKind.NONE and operation.code in OPERATION_TEXT:
        lines.append(Text(OPERATION_TEXT[operation.code]))
    if operation.protection_active:
        lines.append(Text(S_PROTECTION))
    if status.build_selected:
        drift = _drift_count(status)
        for area, level in (('addons', status.software.level), ('skin', status.skin.level),
                            ('settings', status.configuration.level),
                            ('private', status.private.level)):
            if level is not AreaLevel.NOT_APPLICABLE:
                lines.append(_bullet(area, level, drift))
    lines.extend(Text(GAP_TEXT[gap]) for gap in status.gaps)
    checked = status.checked_time_label()
    if checked:
        lines.append(Text(S_CHECKED_AT, name=checked))
    return tuple(lines)
