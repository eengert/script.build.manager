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


@dataclass(frozen=True)
class StartupStatus:
    classification: StartupClassification
    transaction: Optional[RestartTransaction] = None
    code: str = ""
    message: str = ""

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
            code="TRANSACTION_PHASE_REQUIRES_ATTENTION",
            message=f"transaction is in phase {transaction.phase.value}",
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


def run_startup(*, store: Optional[TransactionStore] = None) -> StartupStatus:
    """Obtain session identity and classify once; never reconcile or restart."""
    try:
        current_session_id = get_current_kodi_session_id()
    except SessionIdentityError as exc:
        return StartupStatus(
            StartupClassification.INSPECTION_FAILED,
            code="SESSION_IDENTITY_UNAVAILABLE",
            message=str(exc),
        )
    return classify_startup_transaction(current_session_id, store=store)
