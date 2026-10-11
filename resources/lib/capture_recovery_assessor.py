"""Offline, creation-free Create recovery advice; never lifecycle authority.

Only accepted typed state reads and injected read-only inspections are used.
Matching version strings do not establish package provenance. Future actions
must obtain explicit consent and independently revalidate under operation locks.
No UI, startup, restart, capture, registration or recovery composition belongs here.
The sanitized store error cannot reliably distinguish corruption from read/path
failure. Missing state means only that no record was observed, not no history.
"""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from resources.lib.capture_lifecycle import CaptureStore


class RecoveryReason(str, Enum):
    NO_RECORD_OBSERVED = "NO_RECORD_OBSERVED"
    ORDINARY_RECOVERY_POTENTIAL = "ORDINARY_RECOVERY_POTENTIAL"
    TERMINAL_NO_CAPTURE_HOLD = "TERMINAL_NO_CAPTURE_HOLD"
    OWNER_IDENTITY_UNVERIFIED = "OWNER_IDENTITY_UNVERIFIED"
    UNEXPECTED_ENABLEMENT = "UNEXPECTED_ENABLEMENT"
    STATE_UNVERIFIABLE = "STATE_UNVERIFIABLE"
    LEGACY_REQUEST_UNAVAILABLE = "LEGACY_REQUEST_UNAVAILABLE"
    PATH_UNVERIFIABLE = "PATH_UNVERIFIABLE"
    OBSERVATIONS_UNVERIFIABLE = "OBSERVATIONS_UNVERIFIABLE"


class RecoveryNextStep(str, Enum):
    NO_RECOVERY_PROPOSED = "NO_RECOVERY_PROPOSED"
    REVIEW_EXPLICIT_RECOVERY = "REVIEW_EXPLICIT_RECOVERY"
    OPERATOR_IDENTITY_REVIEW = "OPERATOR_IDENTITY_REVIEW"
    OPERATOR_ENABLEMENT_REVIEW = "OPERATOR_ENABLEMENT_REVIEW"
    OPERATOR_EVIDENCE_REVIEW = "OPERATOR_EVIDENCE_REVIEW"
    OPERATOR_FILESYSTEM_REVIEW = "OPERATOR_FILESYSTEM_REVIEW"
    RECHECK_READ_ONLY = "RECHECK_READ_ONLY"


_NEXT = {
    RecoveryReason.NO_RECORD_OBSERVED: RecoveryNextStep.NO_RECOVERY_PROPOSED,
    RecoveryReason.ORDINARY_RECOVERY_POTENTIAL: RecoveryNextStep.REVIEW_EXPLICIT_RECOVERY,
    RecoveryReason.TERMINAL_NO_CAPTURE_HOLD: RecoveryNextStep.NO_RECOVERY_PROPOSED,
    RecoveryReason.OWNER_IDENTITY_UNVERIFIED: RecoveryNextStep.OPERATOR_IDENTITY_REVIEW,
    RecoveryReason.UNEXPECTED_ENABLEMENT: RecoveryNextStep.OPERATOR_ENABLEMENT_REVIEW,
    RecoveryReason.STATE_UNVERIFIABLE: RecoveryNextStep.OPERATOR_EVIDENCE_REVIEW,
    RecoveryReason.LEGACY_REQUEST_UNAVAILABLE: RecoveryNextStep.OPERATOR_EVIDENCE_REVIEW,
    RecoveryReason.PATH_UNVERIFIABLE: RecoveryNextStep.OPERATOR_FILESYSTEM_REVIEW,
    RecoveryReason.OBSERVATIONS_UNVERIFIABLE: RecoveryNextStep.RECHECK_READ_ONLY,
}


@dataclass(frozen=True)
class CaptureRecoveryAssessment:
    reason: RecoveryReason

    def __post_init__(self):
        if type(self.reason) is not RecoveryReason:
            raise ValueError("invalid recovery reason")

    def safe_dict(self):
        return {"reason": self.reason.value, "next_step": _NEXT[self.reason].value,
                "advisory_only": True}


def assess_capture_recovery(root: Path, operations) -> CaptureRecoveryAssessment:
    """Observe one advisory snapshot without creating directories or locks.

    Trusted operations supply only owner_version(owner), enabled(owner), and
    competing_operation(). An absent owner, unavailable identity or any nonempty
    nonmatching version is D1; no exception payload or inspection value escapes.
    Repeated observations detect disagreement, not every possible external race.
    Expiry, clock, restart proof and future-action eligibility are not authorized
    or certified by ORDINARY_RECOVERY_POTENTIAL.
    UNEXPECTED_ENABLEMENT also covers a verified terminal restoration-postcondition
    mismatch in either direction. A terminal mismatch is not an active hold or
    unfinished Create recovery.
    """
    def result(reason):
        return CaptureRecoveryAssessment(reason)

    try:
        store = CaptureStore(root)
    except Exception:
        # Construction validates only the path, not transaction content.
        return result(RecoveryReason.PATH_UNVERIFIABLE)
    try:
        record = store.read()
        if record is None:
            if store.read() is not None:
                return result(RecoveryReason.OBSERVATIONS_UNVERIFIABLE)
            return result(RecoveryReason.NO_RECORD_OBSERVED)
        competing = store.competing_records_present()
        versions, enabled, external = [], [], []
        for _ in range(2):
            # Identity trouble takes priority over an enablement action.
            try:
                versions.append(operations.owner_version(record.owner_id))
            except Exception:
                versions.append(None)
            try:
                enabled.append(operations.enabled(record.owner_id))
            except Exception:
                enabled.append(None)
            try:
                external.append(operations.competing_operation())
            except Exception:
                external.append(None)
        if store.read() != record or store.competing_records_present() != competing:
            return result(RecoveryReason.OBSERVATIONS_UNVERIFIABLE)
    except Exception:
        return result(RecoveryReason.STATE_UNVERIFIABLE)

    # Any unverifiable/competing state prevents a proposed restoration step.
    if (competing or any(type(v) is not bool for v in external)
            or external != [False, False]):
        return result(RecoveryReason.OBSERVATIONS_UNVERIFIABLE)
    if any(type(v) is not str or v != record.owner_version for v in versions):
        return result(RecoveryReason.OWNER_IDENTITY_UNVERIFIED)
    if any(type(v) is not bool for v in enabled) or enabled[0] != enabled[1]:
        return result(RecoveryReason.OBSERVATIONS_UNVERIFIABLE)
    if not record.request_metadata:
        return result(RecoveryReason.LEGACY_REQUEST_UNAVAILABLE)
    if not record.held:
        if enabled[0] != record.original_enabled:
            return result(RecoveryReason.UNEXPECTED_ENABLEMENT)
        return result(RecoveryReason.TERMINAL_NO_CAPTURE_HOLD)
    if not record.original_enabled and enabled[0]:
        return result(RecoveryReason.UNEXPECTED_ENABLEMENT)
    return result(RecoveryReason.ORDINARY_RECOVERY_POTENTIAL)
