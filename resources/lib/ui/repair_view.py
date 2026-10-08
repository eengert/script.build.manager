"""Update / Repair presentation vocabulary: string identifiers and a bounded summary.

Stdlib-only and secret-blind like the other ui modules. A summary carries only
validated friendly names, versions and a device-profile label. It never holds a
library entry identifier, path, fingerprint or transaction detail.
"""
from dataclasses import dataclass

from resources.lib.plan_model import BlockerCode
from resources.lib.status_model import is_plain_name

# Localized identifiers (resource.language.en_gb/strings.po). Wording that already
# fits Update / Repair is reused from the shared Install and Review identifiers.
S_TITLE = 32102                   # Update / Repair Build
S_NO_VERIFIED_BUILD = 32900       # no verified applied build yet; Install Build first
S_APPLIED_ROW = 32901             # Applied: <name> <version> for <profile>
S_DESIRED_ROW = 32902             # Desired: <name> <version>
S_CHECK_FOR_CHANGES = 32903
S_CHOOSE_REVISION = 32904         # Choose Different Revision...
S_APPLY_CHANGES = 32905
S_CONFIRM_APPLY = 32906
S_NO_OTHER_REVISION = 32907
S_REVISION_HEADING = 32908
S_APPLIED_MARK = 32909            # marks the applied revision in the chooser
S_HEALTHY_TITLE = 32910           # Current / Healthy
S_HEALTHY_BODY = 32911
S_NOTE_DIFFERENT_VERSION = 32912  # G6: a different installed version cannot be replaced yet
S_NOTE_BROKEN = 32913             # G6: a broken installed add-on cannot be repaired yet
S_APPLIED_DETAIL = 32915          # applied build details (help-style viewer)
S_DESIRED_DETAIL = 32916          # desired revision details (help-style viewer)

# Shared identifiers reused by Update / Repair.
S_PREPARE = 32803                 # getting the current repository version; no change to Kodi
S_STALE = 32808                  # reviewed plan changed; check and confirm again
S_NOT_APPLIED = 32814             # could not be applied safely; check Build Status
S_CONFIRM_RESTART = 32815         # temporary protection and a full restart may be required
S_COMPLETE_WITH_EXCEPTIONS = 32816  # verified, with accepted skips or reviewed exceptions
S_BACK = 32113
S_HELP = 32112

# Each supported-scope limit that stops a reviewed plan from being applied.
NOTE_FOR_BLOCKER = {
    BlockerCode.DIFFERENT_VERSION_INSTALLED: S_NOTE_DIFFERENT_VERSION,
    BlockerCode.INSTALLED_ADDON_BROKEN: S_NOTE_BROKEN,
}


def friendly(value):
    """Bounded plain text for display; anything else becomes a neutral dash."""
    return value if isinstance(value, str) and value and is_plain_name(value) else '-'


@dataclass(frozen=True)
class RepairSummary:
    """What Update / Repair shows about the applied and the desired revision."""
    applied_name: str
    applied_version: str
    profile: str
    desired_name: str
    desired_version: str
    changed: bool
