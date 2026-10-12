"""Injected read-only Red Light snapshot; no lifecycle or runtime composition.

Uses FrozenArtifactBackend.get_addon_details semantics. Version strings are
observations, never package provenance or enablement history. Unsupported version
syntax is unknown rather than exported as arbitrary backend text.
"""
from dataclasses import dataclass
import re

from resources.lib.redlight_resource import REDLIGHT_ADDON_ID


@dataclass(frozen=True)
class OwnerObservation:
    version: str | None = None
    enabled: bool | None = None

    def __post_init__(self):
        if self.version is None and self.enabled is None:
            return
        if (type(self.version) is not str or len(self.version) > 32
                or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', self.version)
                or type(self.enabled) is not bool):
            raise ValueError('invalid owner observation')

    @property
    def known(self):
        return self.version is not None


def observe_redlight_owner(backend) -> OwnerObservation:
    """One snapshot, exact ID, numeric version, strict enabled; errors are unknown.

    The caller supplies a trusted backend. No default backend is constructed;
    only get_addon_details is invoked, for the fixed audited owner. Non-numeric
    versions remain unknown. There is no claim about intervening changes.
    """
    try:
        row = backend.get_addon_details(REDLIGHT_ADDON_ID)
        if row is None or type(row.addon_id) is not str or row.addon_id != REDLIGHT_ADDON_ID:
            return OwnerObservation()
        return OwnerObservation(row.version, row.enabled)
    except Exception:
        return OwnerObservation()
