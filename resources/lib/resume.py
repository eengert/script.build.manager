"""BM-020C post-restart resume orchestration.

Resume is deliberately a separate coordinator from startup inspection.  It
revalidates desired state before mutation, claims the durable transaction for
one process, runs the ordinary idempotent BuildManager entrypoint, and clears
only an unchanged transaction after a matching successful no-restart result.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from resources.lib.build_manager import BuildManager, ReconcileResult
from resources.lib.restart import RestartRequirement
from resources.lib.session import get_current_kodi_session_id
from resources.lib.transaction import (
    RestartTransaction,
    TransactionError,
    TransactionPhase,
    TransactionStateConflict,
    TransactionStore,
)


class ResumeOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"


@dataclass(frozen=True)
class ResumeFailure:
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ResumeResult:
    outcome: ResumeOutcome
    transaction: Optional[RestartTransaction] = None
    reconcile_result: Optional[ReconcileResult] = None
    failure: Optional[ResumeFailure] = None
    message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome is ResumeOutcome.COMPLETED

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "transaction": self.transaction.to_dict() if self.transaction else None,
            "reconcile_result": (
                self.reconcile_result.to_dict()
                if self.reconcile_result is not None else None
            ),
            "failure": self.failure.to_dict() if self.failure else None,
            "message": self.message,
        }


def _safe_code(value: object, default: str) -> str:
    text = str(value).strip()
    return text[:96] if text else default


class ResumeCoordinator:
    """Perform exactly one guarded, normal reconciliation after restart."""

    def __init__(
        self,
        build_manager: Optional[BuildManager] = None,
        *,
        store: Optional[TransactionStore] = None,
        session_id_provider: Optional[Callable[[], str]] = None,
        before_reconcile: Optional[Callable[[RestartTransaction, ReconcileResult, str], object]] = None,
    ) -> None:
        self._build_manager = build_manager or BuildManager()
        self._store = store or TransactionStore()
        self._session_id_provider = session_id_provider or get_current_kodi_session_id
        self._before_reconcile = before_reconcile

    def resume(
        self,
        expected: RestartTransaction,
        *,
        current_session_id: Optional[str] = None,
    ) -> ResumeResult:
        """Resume one READY_FOR_RESUME transaction, failing closed on drift."""
        if not isinstance(expected, RestartTransaction):
            return self._failed("INVALID_TRANSACTION", "resume requires a valid transaction")

        try:
            current = self._store.inspect()
        except TransactionError as exc:
            return self._failed(getattr(exc, "code", "TRANSACTION_INSPECTION_FAILED"),
                                "could not inspect the restart transaction")
        if current is None:
            return self._failed("TRANSACTION_MISSING", "restart transaction is no longer present")
        if current.transaction_id != expected.transaction_id:
            return self._failed("TRANSACTION_ID_MISMATCH", "restart transaction identity changed",
                                transaction=current)
        if current.phase is not TransactionPhase.AWAITING_RESTART:
            return self._failed("TRANSACTION_NOT_AWAITING", "restart transaction is not awaiting resume",
                                transaction=current)

        try:
            session_id = current_session_id or self._session_id_provider()
        except Exception:
            return self._needs_attention(
                current, "SESSION_IDENTITY_UNAVAILABLE",
                "resume session boundary could not be verified",
            )
        if session_id == current.originating_kodi_session_id:
            return self._failed(
                "SAME_SESSION",
                "restart transaction belongs to the current Kodi session",
                transaction=current,
            )

        try:
            preview = self._build_manager.preview(current.request)
        except Exception:
            preview = None
        if (
            not isinstance(preview, ReconcileResult)
            or not preview.success
            or preview.request != current.request
        ):
            return self._needs_attention(
                current,
                "PREVIEW_FAILED",
                "read-only desired-state preview failed",
            )
        if preview.desired_fingerprint != current.desired_state_fingerprint:
            return self._needs_attention(
                current,
                "FINGERPRINT_MISMATCH",
                "desired-state fingerprint changed before resume",
            )
        preview_overlay = preview.private_overlay
        if (
            (preview_overlay is None) != (not current.private_overlay_id)
            or (
                preview_overlay is not None
                and (
                    preview_overlay.overlay_id != current.private_overlay_id
                    or preview_overlay.fingerprint != current.private_overlay_fingerprint
                    or preview_overlay.required != current.private_overlay_required
                )
            )
        ):
            return self._needs_attention(
                current,
                "PRIVATE_OVERLAY_FINGERPRINT_MISMATCH",
                "private overlay identity changed before resume",
            )

        if self._before_reconcile is not None:
            try:
                readiness = self._before_reconcile(current, preview, session_id)
            except Exception:
                return self._needs_attention(
                    current,
                    "PRE_RECONCILE_READINESS_FAILED",
                    "pre-configuration resume readiness could not be verified",
                )
            if readiness is not None and not getattr(readiness, "allowed", False):
                code = _safe_code(
                    getattr(readiness, "code", "PRE_RECONCILE_READINESS_FAILED"),
                    "PRE_RECONCILE_READINESS_FAILED",
                )
                message = getattr(
                    readiness,
                    "message",
                    "pre-configuration resume readiness failed",
                )
                if not isinstance(message, str):
                    message = "pre-configuration resume readiness failed"
                return self._needs_attention(
                    current, code, message[:512],
                )

        try:
            claimed = self._store.transition_expected(
                transaction_id=current.transaction_id,
                expected_phase=TransactionPhase.AWAITING_RESTART,
                new_phase=TransactionPhase.RESUMING,
            )
        except TransactionStateConflict:
            return self._failed(
                "RESUME_CLAIM_CONFLICT",
                "restart transaction changed before resume claim",
                transaction=self._safe_inspect(),
            )
        except TransactionError:
            return self._failed(
                "RESUME_CLAIM_FAILED",
                "restart transaction could not be claimed",
                transaction=self._safe_inspect(),
            )

        try:
            result = self._build_manager.reconcile(claimed.request)
        except Exception:
            return self._needs_attention(
                claimed,
                "RECONCILE_EXCEPTION",
                "resumed reconciliation raised an unexpected failure",
            )
        if not isinstance(result, ReconcileResult) or not result.success:
            code = _safe_code(
                result.failure.code if result.failure is not None else "RECONCILE_FAILED",
                "RECONCILE_FAILED",
            ) if isinstance(result, ReconcileResult) else "RECONCILE_FAILED"
            return self._needs_attention(
                claimed,
                code,
                f"resumed reconciliation failed ({code})",
                reconcile_result=result if isinstance(result, ReconcileResult) else None,
            )
        if result.desired_fingerprint != current.desired_state_fingerprint:
            return self._needs_attention(
                claimed,
                "FINAL_FINGERPRINT_MISMATCH",
                "desired-state fingerprint changed during resume",
                reconcile_result=result,
            )
        result_overlay = result.private_overlay
        if (
            (result_overlay is None) != (not current.private_overlay_id)
            or (
                result_overlay is not None
                and (
                    result_overlay.overlay_id != current.private_overlay_id
                    or result_overlay.fingerprint != current.private_overlay_fingerprint
                    or result_overlay.required != current.private_overlay_required
                )
            )
        ):
            return self._needs_attention(
                claimed,
                "PRIVATE_OVERLAY_FINGERPRINT_MISMATCH",
                "private overlay identity changed during resume",
                reconcile_result=result,
            )
        if result.restart_report.requirement is RestartRequirement.KODI_RESTART:
            return self._needs_attention(
                claimed,
                "RESTART_REQUIRED_AFTER_RESUME",
                "restart requirement persisted after completed restart boundary",
                reconcile_result=result,
            )
        if result.restart_report.requirement is not RestartRequirement.NONE:
            return self._needs_attention(
                claimed,
                "UNSUPPORTED_RESTART_REQUIREMENT",
                "resumed reconciliation returned an unsupported restart requirement",
                reconcile_result=result,
            )

        try:
            self._store.clear_expected(
                transaction_id=claimed.transaction_id,
                expected_phase=TransactionPhase.RESUMING,
            )
        except TransactionStateConflict:
            return self._failed(
                "RESUME_CLEAR_CONFLICT",
                "restart transaction changed before successful clear",
                transaction=self._safe_inspect(),
                reconcile_result=result,
            )
        except TransactionError:
            return self._failed(
                "RESUME_CLEAR_FAILED",
                "completed restart transaction could not be cleared",
                transaction=self._safe_inspect(),
                reconcile_result=result,
            )
        return ResumeResult(
            ResumeOutcome.COMPLETED,
            reconcile_result=result,
            message="resume reconciliation completed and transaction cleared",
        )

    def _needs_attention(
        self,
        transaction: RestartTransaction,
        code: str,
        message: str,
        *,
        reconcile_result: Optional[ReconcileResult] = None,
    ) -> ResumeResult:
        bounded_code = _safe_code(code, "RESUME_FAILED")
        try:
            updated = self._store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=transaction.phase,
                new_phase=TransactionPhase.NEEDS_ATTENTION,
                status_code=bounded_code,
                status_message=message[:512],
            )
        except TransactionError:
            updated = self._safe_inspect() or transaction
            return self._failed(
                "RESUME_STATE_UPDATE_FAILED",
                "resume failure state could not be persisted",
                transaction=updated,
                reconcile_result=reconcile_result,
            )
        return ResumeResult(
            ResumeOutcome.NEEDS_ATTENTION,
            transaction=updated,
            reconcile_result=reconcile_result,
            failure=ResumeFailure(bounded_code, message[:512]),
            message="resume requires explicit recovery",
        )

    def _safe_inspect(self) -> Optional[RestartTransaction]:
        try:
            return self._store.inspect()
        except TransactionError:
            return None

    @staticmethod
    def _failed(
        code: str,
        message: str,
        *,
        transaction: Optional[RestartTransaction] = None,
        reconcile_result: Optional[ReconcileResult] = None,
    ) -> ResumeResult:
        return ResumeResult(
            ResumeOutcome.FAILED,
            transaction=transaction,
            reconcile_result=reconcile_result,
            failure=ResumeFailure(_safe_code(code, "RESUME_FAILED"), message[:512]),
            message="resume did not run to completion",
        )
