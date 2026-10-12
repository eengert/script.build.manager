"""Pure advisory Create presentation. No buttons, callbacks or recovery authority.

The caller supplies trusted typed snapshots. They do not prove action eligibility,
restart, provenance, or history. No private metadata enters the presentation.
"""
from dataclasses import dataclass

from enum import Enum


class RecoveryPresentationReason(str, Enum):
    NO_RECORD_OBSERVED = 'NO_RECORD_OBSERVED'
    ORDINARY_RECOVERY_POTENTIAL = 'ORDINARY_RECOVERY_POTENTIAL'
    TERMINAL_NO_CAPTURE_HOLD = 'TERMINAL_NO_CAPTURE_HOLD'
    TERMINAL_FINALIZATION_PENDING = 'TERMINAL_FINALIZATION_PENDING'
    OWNER_IDENTITY_UNVERIFIED = 'OWNER_IDENTITY_UNVERIFIED'
    UNEXPECTED_ENABLEMENT = 'UNEXPECTED_ENABLEMENT'
    STATE_UNVERIFIABLE = 'STATE_UNVERIFIABLE'
    LEGACY_REQUEST_UNAVAILABLE = 'LEGACY_REQUEST_UNAVAILABLE'
    PATH_UNVERIFIABLE = 'PATH_UNVERIFIABLE'
    OBSERVATIONS_UNVERIFIABLE = 'OBSERVATIONS_UNVERIFIABLE'


R = RecoveryPresentationReason


@dataclass(frozen=True)
class RecoveryPresentationInput:
    reason: RecoveryPresentationReason
    supported_owner_verified: bool = False
    enabled: bool | None = None
    original_enabled: bool | None = None

    def __post_init__(self):
        if (type(self.reason) is not R or type(self.supported_owner_verified) is not bool
                or any(v is not None and type(v) is not bool for v in (self.enabled, self.original_enabled))):
            raise ValueError('invalid Create presentation input')


@dataclass(frozen=True)
class CreateRecoveryView:
    title_id: int
    body_id: int

    def __post_init__(self):
        if type(self.title_id) is not int or self.title_id != 33000 or type(self.body_id) is not int or self.body_id not in range(33001, 33008):
            raise ValueError('invalid Create presentation')


_BODY = {
    R.NO_RECORD_OBSERVED: 33001,
    R.ORDINARY_RECOVERY_POTENTIAL: 33002,
    R.TERMINAL_FINALIZATION_PENDING: 33003,
    R.TERMINAL_NO_CAPTURE_HOLD: 33004,
}


def present_create_recovery(observation: RecoveryPresentationInput) -> CreateRecoveryView:
    """Map advisory evidence only; supported_owner_verified must come from trusted
    exact owner/version observation. UNKNOWN must never produce manual disable
    guidance. This Boolean is a presentation condition, never operation authority.
    """
    body = 33007
    if type(observation) is RecoveryPresentationInput:
        body = _BODY.get(observation.reason, 33007)
        if observation.reason is R.UNEXPECTED_ENABLEMENT:
            body = 33006
            if (observation.supported_owner_verified is True
                    and observation.enabled is True and observation.original_enabled is False):
                body = 33005
    return CreateRecoveryView(33000, body)
