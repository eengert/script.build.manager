"""BM-020B startup inspection and same/new-session classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from resources.lib.session import SessionIdentityError, get_current_kodi_session_id
from resources.lib.transaction import (
    RestartTransaction,
    TransactionCorrupt,
    TransactionError,
    TransactionPhase,
    TransactionStore,
    TransactionUnsupportedSchema,
)


class StartupClassification(str, Enum):
    NO_TRANSACTION = "no_transaction"
    SAME_SESSION_AWAITING_RESTART = "same_session_awaiting_restart"
    READY_FOR_RESUME = "ready_for_resume"
    NEEDS_ATTENTION = "needs_attention"
    INVALID_TRANSACTION = "invalid_transaction"
    INSPECTION_FAILED = "inspection_failed"


STARTUP_CLASSIFICATION_PROPERTY = "script.build.manager.startup_classification"
RESUME_OUTCOME_PROPERTY = "script.build.manager.resume_outcome"
RESUME_FINGERPRINT_PROPERTY = "script.build.manager.resume_fingerprint"
RESUME_REQUIREMENT_PROPERTY = "script.build.manager.resume_requirement"


@dataclass(frozen=True)
class StartupStatus:
    classification: StartupClassification
    transaction: Optional[RestartTransaction] = None
    code: str = ""
    message: str = ""
    resume_result: Optional[object] = None

    @property
    def eligible_for_resume(self) -> bool:
        return self.classification is StartupClassification.READY_FOR_RESUME


def inspect_pending_transaction(
    *, store: Optional[TransactionStore] = None
) -> Optional[RestartTransaction]:
    """Inspect the durable record under the profile-local transaction lock."""
    return (store or TransactionStore()).inspect()


def classify_startup_transaction(
    current_session_id: str, *, store: Optional[TransactionStore] = None
) -> StartupStatus:
    """Classify a pending transaction without claiming or resuming it."""
    target = store or TransactionStore()
    try:
        transaction = target.inspect()
    except TransactionUnsupportedSchema as exc:
        return StartupStatus(
            StartupClassification.INVALID_TRANSACTION,
            code=exc.code,
            message=str(exc),
        )
    except (TransactionCorrupt, TransactionError) as exc:
        return StartupStatus(
            StartupClassification.INVALID_TRANSACTION,
            code=getattr(exc, "code", "TRANSACTION_INSPECTION_FAILED"),
            message=str(exc),
        )
    if transaction is None:
        return StartupStatus(StartupClassification.NO_TRANSACTION)
    if transaction.phase is not TransactionPhase.AWAITING_RESTART:
        return StartupStatus(
            StartupClassification.NEEDS_ATTENTION,
            transaction=transaction,
            code=(transaction.status_code or "TRANSACTION_PHASE_REQUIRES_ATTENTION"),
            message=(
                transaction.status_message
                or f"transaction is in phase {transaction.phase.value}"
            ),
        )
    if transaction.originating_kodi_session_id == current_session_id:
        return StartupStatus(
            StartupClassification.SAME_SESSION_AWAITING_RESTART,
            transaction=transaction,
            code="SAME_SESSION",
            message="restart transaction belongs to the current Kodi session",
        )
    return StartupStatus(
        StartupClassification.READY_FOR_RESUME,
        transaction=transaction,
        code="NEW_SESSION",
        message="restart transaction belongs to a prior Kodi session",
    )


def run_startup(
    *,
    store: Optional[TransactionStore] = None,
    resume_coordinator=None,
) -> StartupStatus:
    """Classify once and invoke resume only for a new-session handoff."""
    try:
        current_session_id = get_current_kodi_session_id()
    except SessionIdentityError as exc:
        return StartupStatus(
            StartupClassification.INSPECTION_FAILED,
            code="SESSION_IDENTITY_UNAVAILABLE",
            message=str(exc),
        )
    target = store or TransactionStore()
    status = classify_startup_transaction(current_session_id, store=target)
    if not status.eligible_for_resume or status.transaction is None:
        return status

    try:
        if resume_coordinator is None:
            from resources.lib.resume import ResumeCoordinator
            resume_coordinator = ResumeCoordinator(store=target)
        result = resume_coordinator.resume(
            status.transaction, current_session_id=current_session_id
        )
    except Exception:
        return StartupStatus(
            StartupClassification.NEEDS_ATTENTION,
            transaction=status.transaction,
            code="RESUME_COORDINATOR_FAILED",
            message="resume coordinator failed closed",
        )
    if result.succeeded:
        return StartupStatus(
            StartupClassification.NO_TRANSACTION,
            code="RESUME_COMPLETE",
            message="resume reconciliation completed and transaction was cleared",
            resume_result=result,
        )

    try:
        current = target.inspect()
    except TransactionError:
        current = None
    if current is not None and current.phase is TransactionPhase.NEEDS_ATTENTION:
        return StartupStatus(
            StartupClassification.NEEDS_ATTENTION,
            transaction=current,
            code=(current.status_code or "RESUME_NEEDS_ATTENTION"),
            message=(current.status_message or "resume requires explicit recovery"),
            resume_result=result,
        )
    failure = result.failure
    return StartupStatus(
        StartupClassification.READY_FOR_RESUME,
        transaction=current or status.transaction,
        code=(failure.code if failure else "RESUME_FAILED"),
        message=(failure.message if failure else "resume did not complete"),
        resume_result=result,
    )
