"""Presentation-safe Build Status contract (BM-UI-002B / G2).

This module is the public, read-only vocabulary shared by the status service
(`resources.lib.status`) and the native Kodi presentation. It imports only the
standard library so the UI can depend on it without importing any engine,
backend, or private-data owner.

Every field is an enum, a bool, a bounded integer, a validated identifier, or
a UTC timestamp. The one exception is ``SoftwareItem.display_name``: bounded
plain text with no control, format, or Kodi-markup characters. A status object
cannot carry a setting value, credential, overlay payload, exception message,
path, or fingerprint, and constructing one that tries to is a ``ValueError``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, Tuple

_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_STATUS_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

MAX_SOFTWARE_ITEMS = 4096
MAX_PRIVATE_ITEMS = 64
MAX_COUNT = 100000


class OverallStatus(str, Enum):
    """The one-line answer. ``INCOMPLETE`` means not fully checked."""

    CURRENT = "current"
    CHANGES_NEEDED = "changes_needed"
    RESTART_REQUIRED = "restart_required"
    NEEDS_ATTENTION = "needs_attention"
    INCOMPLETE = "incomplete"


class AreaLevel(str, Enum):
    CURRENT = "current"
    CHANGES_NEEDED = "changes_needed"
    UNAVAILABLE = "unavailable"          # the check could not truthfully complete
    NOT_APPLICABLE = "not_applicable"    # the selected build does not use this area


class StatusArea(str, Enum):
    SOFTWARE = "software"
    SKIN = "skin"
    CONFIGURATION = "configuration"
    PRIVATE = "private"


class SoftwareItemState(str, Enum):
    CURRENT = "current"
    MISSING = "missing"
    WRONG_VERSION = "wrong_version"
    WRONG_ENABLED_STATE = "wrong_enabled_state"
    UNCHECKABLE = "uncheckable"


class PrivateItemKind(str, Enum):
    SETTINGS = "settings"
    RESOURCE = "resource"


class OperationKind(str, Enum):
    NONE = "none"
    RESTART_REQUIRED = "restart_required"
    NEEDS_ATTENTION = "needs_attention"
    UNAVAILABLE = "unavailable"


class OperationCode(str, Enum):
    """Stable, UI-mappable reason for a non-NONE operation state."""

    NONE = "none"
    AWAITING_RESTART = "awaiting_restart"
    RESUME_PENDING = "resume_pending"
    OPERATION_NOT_FINISHED = "operation_not_finished"
    TRANSACTION_INVALID = "transaction_invalid"
    TRANSACTION_UNREADABLE = "transaction_unreadable"


class CheckGap(str, Enum):
    """Why part of the check could not complete (stable enums, never text)."""

    NO_BUILD_SELECTED = "no_build_selected"
    NOTHING_TO_COMPARE = "nothing_to_compare"
    BUILD_UNREADABLE = "build_unreadable"
    KODI_STATE_UNAVAILABLE = "kodi_state_unavailable"
    SOFTWARE_UNAVAILABLE = "software_unavailable"
    CONFIGURATION_UNAVAILABLE = "configuration_unavailable"
    PRIVATE_DATA_MISSING = "private_data_missing"
    PRIVATE_DATA_UNUSABLE = "private_data_unusable"
    PRIVATE_UNAVAILABLE = "private_unavailable"
    OPERATION_STATE_UNAVAILABLE = "operation_state_unavailable"
    INSPECTION_FAILED = "inspection_failed"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def is_plain_name(value: object) -> bool:
    """Bounded text a Kodi dialog cannot interpret: no control or format
    characters (including bidirectional overrides and line separators) and none
    of the characters Kodi treats as markup or info-label syntax."""
    return (
        isinstance(value, str) and len(value) <= 64
        and not any(ch in "[]$" or unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn")
                    for ch in value)
    )


def _is_int(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_COUNT


def _addon_id(value: object, label: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    _require(isinstance(value, str) and _ADDON_ID.fullmatch(value) is not None,
             "unsupported %s" % label)
    return value


@dataclass(frozen=True)
class SoftwareItem:
    """One managed add-on's state. ``display_name`` is optional, bounded text."""

    addon_id: str
    state: SoftwareItemState
    display_name: str = ""

    def __post_init__(self) -> None:
        _addon_id(self.addon_id, "software item id")
        _require(isinstance(self.state, SoftwareItemState), "unsupported software state")
        _require(is_plain_name(self.display_name), "unsupported software item name")

    @property
    def label(self) -> str:
        """Human-readable name when known, otherwise the validated add-on ID."""
        return self.display_name or self.addon_id


@dataclass(frozen=True)
class SoftwareStatus:
    level: AreaLevel
    items: Tuple[SoftwareItem, ...] = ()

    def __post_init__(self) -> None:
        _require(isinstance(self.level, AreaLevel), "unsupported software level")
        _require(isinstance(self.items, tuple) and len(self.items) <= MAX_SOFTWARE_ITEMS
                 and all(isinstance(item, SoftwareItem) for item in self.items),
                 "unsupported software items")
        _require(len({item.addon_id for item in self.items}) == len(self.items),
                 "duplicate software item")

    @property
    def needs_attention(self) -> Tuple[SoftwareItem, ...]:
        return tuple(item for item in self.items
                     if item.state is not SoftwareItemState.CURRENT)


@dataclass(frozen=True)
class SkinStatus:
    level: AreaLevel
    expected_skin: str = ""
    current_skin: str = ""
    matches: Optional[bool] = None

    def __post_init__(self) -> None:
        _require(isinstance(self.level, AreaLevel), "unsupported skin level")
        _addon_id(self.expected_skin, "expected skin", allow_empty=True)
        _addon_id(self.current_skin, "current skin", allow_empty=True)
        _require(self.matches is None or type(self.matches) is bool, "unsupported skin match")


@dataclass(frozen=True)
class ConfigurationStatus:
    """Counts only: managed setting/file targets that match, differ, or could not be read."""

    level: AreaLevel
    total: int = 0
    differing: int = 0
    unreadable: int = 0

    def __post_init__(self) -> None:
        _require(isinstance(self.level, AreaLevel), "unsupported configuration level")
        _require(all(_is_int(v) for v in (self.total, self.differing, self.unreadable)),
                 "unsupported configuration count")
        _require(self.differing + self.unreadable <= self.total, "inconsistent configuration counts")


@dataclass(frozen=True)
class PrivateItem:
    """Status of one private-data group. Never carries a field name or value."""

    item_id: str
    kind: PrivateItemKind
    level: AreaLevel

    def __post_init__(self) -> None:
        _require(isinstance(self.item_id, str) and _ITEM_ID.fullmatch(self.item_id) is not None,
                 "unsupported private item id")
        _require(isinstance(self.kind, PrivateItemKind), "unsupported private item kind")
        _require(isinstance(self.level, AreaLevel) and self.level is not AreaLevel.NOT_APPLICABLE,
                 "unsupported private item level")


@dataclass(frozen=True)
class PrivateStatus:
    level: AreaLevel
    items: Tuple[PrivateItem, ...] = ()

    def __post_init__(self) -> None:
        _require(isinstance(self.level, AreaLevel), "unsupported private level")
        _require(isinstance(self.items, tuple) and len(self.items) <= MAX_PRIVATE_ITEMS
                 and all(isinstance(item, PrivateItem) for item in self.items),
                 "unsupported private items")


@dataclass(frozen=True)
class OperationStatus:
    kind: OperationKind = OperationKind.NONE
    code: OperationCode = OperationCode.NONE
    status_code: str = ""            # sanitized product status code, or ""
    protection_active: bool = False  # an activation hold is still in force

    def __post_init__(self) -> None:
        _require(isinstance(self.kind, OperationKind), "unsupported operation kind")
        _require(isinstance(self.code, OperationCode), "unsupported operation code")
        _require(isinstance(self.status_code, str)
                 and (self.status_code == "" or _STATUS_CODE.fullmatch(self.status_code) is not None),
                 "unsupported operation status code")
        _require(type(self.protection_active) is bool, "unsupported protection flag")
        _require((self.kind is OperationKind.NONE) == (self.code is OperationCode.NONE),
                 "operation kind and code disagree")


@dataclass(frozen=True)
class BuildStatus:
    """Result of one fresh, read-only check."""

    overall: OverallStatus
    checked_at: str
    build_selected: bool
    software: SoftwareStatus
    skin: SkinStatus
    configuration: ConfigurationStatus
    private: PrivateStatus
    operation: OperationStatus
    gaps: Tuple[CheckGap, ...] = ()

    def __post_init__(self) -> None:
        _require(isinstance(self.overall, OverallStatus), "unsupported overall status")
        _require(isinstance(self.checked_at, str) and _TIMESTAMP.fullmatch(self.checked_at) is not None,
                 "unsupported check time")
        _require(type(self.build_selected) is bool, "unsupported build selection flag")
        for value, kind in ((self.software, SoftwareStatus), (self.skin, SkinStatus),
                            (self.configuration, ConfigurationStatus),
                            (self.private, PrivateStatus), (self.operation, OperationStatus)):
            _require(isinstance(value, kind), "unsupported status section")
        _require(isinstance(self.gaps, tuple) and len(self.gaps) <= len(CheckGap)
                 and all(isinstance(gap, CheckGap) for gap in self.gaps)
                 and len(set(self.gaps)) == len(self.gaps), "unsupported check gaps")
        if self.overall is OverallStatus.CURRENT:
            levels = [area_level(self, a) for a in StatusArea]
            _require(
                self.build_selected and not self.gaps
                and self.operation.kind is OperationKind.NONE
                and not any(l in (AreaLevel.CHANGES_NEEDED, AreaLevel.UNAVAILABLE) for l in levels)
                and AreaLevel.CURRENT in levels
                and all(i.state is SoftwareItemState.CURRENT for i in self.software.items)
                and all(i.level is AreaLevel.CURRENT for i in self.private.items),
                "a status with unchecked or changed areas cannot be current")

    def area(self, area: StatusArea) -> AreaLevel:
        return area_level(self, area)

    def checked_time_label(self) -> str:
        """Local ``HH:MM`` of the check, for display; ``""`` if it cannot be converted."""
        try:
            moment = datetime.strptime(self.checked_at, "%Y-%m-%dT%H:%M:%SZ")
            return moment.replace(tzinfo=timezone.utc).astimezone().strftime("%H:%M")
        except (ValueError, OverflowError, OSError):
            return ""

    def to_safe_dict(self) -> dict:
        """Serializable evidence form: enum values, booleans, counts, validated IDs."""
        return {
            "overall": self.overall.value,
            "checked_at": self.checked_at,
            "build_selected": self.build_selected,
            "software": {
                "level": self.software.level.value,
                "items": [{"addon_id": i.addon_id, "state": i.state.value,
                           "display_name": i.display_name} for i in self.software.items],
            },
            "skin": {
                "level": self.skin.level.value,
                "expected_skin": self.skin.expected_skin,
                "current_skin": self.skin.current_skin,
                "matches": self.skin.matches,
            },
            "configuration": {
                "level": self.configuration.level.value,
                "total": self.configuration.total,
                "differing": self.configuration.differing,
                "unreadable": self.configuration.unreadable,
            },
            "private": {
                "level": self.private.level.value,
                "items": [{"item_id": i.item_id, "kind": i.kind.value, "level": i.level.value}
                          for i in self.private.items],
            },
            "operation": {
                "kind": self.operation.kind.value,
                "code": self.operation.code.value,
                "status_code": self.operation.status_code,
                "protection_active": self.operation.protection_active,
            },
            "gaps": [gap.value for gap in self.gaps],
        }


def area_level(status: BuildStatus, area: StatusArea) -> AreaLevel:
    sections: Dict[StatusArea, object] = {
        StatusArea.SOFTWARE: status.software,
        StatusArea.SKIN: status.skin,
        StatusArea.CONFIGURATION: status.configuration,
        StatusArea.PRIVATE: status.private,
    }
    return sections[area].level
