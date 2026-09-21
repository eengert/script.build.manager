"""BM-020C1 restart capability selection and manual handoff coordination.

This module prepares the durable BM-020B handoff when a successful
reconciliation requires a Kodi restart.  Current supported platforms use the
manual handoff capability: the coordinator never exits or restarts Kodi.
Resume reconciliation remains a later BM-020C responsibility.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping, Optional

from resources.lib.build_manager import BuildManager, ReconcileRequest, ReconcileResult
from resources.lib.restart import RestartReport, RestartRequirement
from resources.lib.session import get_current_kodi_session_id
from resources.lib.transaction import (
    RestartTransaction,
    TransactionError,
    TransactionPhase,
    TransactionStore,
    prepare_restart_transaction,
)


class RestartCapability(str, Enum):
    """Whether Build Manager may request a new Kodi application process."""

    AUTOMATIC_APP_RESTART = "automatic_app_restart"
    MANUAL_APP_RESTART_REQUIRED = "manual_app_restart_required"


class RestartOutcome(str, Enum):
    """Safe caller-facing outcome for one reconciliation request."""

    COMPLETE = "complete"
    FAILED = "failed"
    MANUAL_RESTART_REQUIRED = "manual_restart_required"
    AUTOMATIC_RESTART_INITIATED = "automatic_restart_initiated"


_PLATFORM_ALIASES = {
    "darwin": "macos",
    "mac": "macos",
    "osx": "macos",
    "fireos": "fire_os",
    "fire-os": "fire_os",
    "nvidia_shield": "shield",
    "nvidia-shield": "shield",
    "apple_tv": "tvos",
    "apple-tv": "tvos",
}

# No current project platform has an approved production automatic-restart
# adapter.  Keeping this policy in one resolver makes a future approved
# adapter an explicit change rather than scattered platform conditionals.
DEFAULT_PLATFORM_CAPABILITIES = {
    "macos": RestartCapability.MANUAL_APP_RESTART_REQUIRED,
    "android": RestartCapability.MANUAL_APP_RESTART_REQUIRED,
    "shield": RestartCapability.MANUAL_APP_RESTART_REQUIRED,
    "fire_os": RestartCapability.MANUAL_APP_RESTART_REQUIRED,
    "tvos": RestartCapability.MANUAL_APP_RESTART_REQUIRED,
    "ios": RestartCapability.MANUAL_APP_RESTART_REQUIRED,
}


def _normalize_platform(platform_id: object) -> str:
    if not isinstance(platform_id, str) or not platform_id.strip():
        return "unknown"
    normalized = platform_id.strip().lower().replace(" ", "_")
    return _PLATFORM_ALIASES.get(normalized, normalized)


def default_platform_id() -> str:
    """Return the host identity available to the Python runtime."""
    return _normalize_platform(sys.platform)


class RestartCapabilityResolver:
    """Injectable, conservative platform-to-capability policy."""

    def __init__(
        self,
        platform_id: Optional[str] = None,
        capabilities: Optional[Mapping[str, RestartCapability]] = None,
    ) -> None:
        self.platform_id = platform_id
        self._capabilities = dict(capabilities or DEFAULT_PLATFORM_CAPABILITIES)

    def resolve(self, platform_id: Optional[str] = None) -> RestartCapability:
        key = _normalize_platform(platform_id or self.platform_id or default_platform_id())
        capability = self._capabilities.get(
            key, RestartCapability.MANUAL_APP_RESTART_REQUIRED
        )
        if not isinstance(capability, RestartCapability):
            raise TypeError("restart capability policy returned an invalid capability")
        return capability


@dataclass(frozen=True)
class RestartCoordinatorFailure:
    """Bounded, structured failure safe for callers and logs."""

    code: str
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class RestartCoordinatorResult:
    """Result of reconciliation plus restart handoff preparation."""

    outcome: RestartOutcome
    request: ReconcileRequest
    reconcile_result: ReconcileResult
    capability: Optional[RestartCapability] = None
    transaction: Optional[RestartTransaction] = None
    failure: Optional[RestartCoordinatorFailure] = None
    message: str = ""

    @property
    def manual_restart_required(self) -> bool:
        return self.outcome is RestartOutcome.MANUAL_RESTART_REQUIRED

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "request": self.request.to_dict(),
            "capability": self.capability.value if self.capability else None,
            "transaction": self.transaction.to_dict() if self.transaction else None,
            "reconcile_result": self.reconcile_result.to_dict(),
            "failure": self.failure.to_dict() if self.failure else None,
            "message": self.message,
        }


def _bounded_message(value: object) -> str:
    text = str(value).strip() or value.__class__.__name__
    return text[:500]


class RestartCoordinator:
    """Coordinate a normal reconciliation with the BM-020B handoff."""

    def __init__(
        self,
        build_manager: Optional[BuildManager] = None,
        *,
        capability_resolver: Optional[object] = None,
        session_id_provider: Optional[Callable[[], str]] = None,
        store: Optional[TransactionStore] = None,
    ) -> None:
        self._build_manager = build_manager or BuildManager()
        self._capability_resolver = capability_resolver or RestartCapabilityResolver()
        self._session_id_provider = session_id_provider or get_current_kodi_session_id
        self._store = store or TransactionStore()

    def reconcile(self, request: ReconcileRequest) -> RestartCoordinatorResult:
        """Run normal reconciliation, then apply the restart handoff contract."""
        pending = self._pending_before_reconcile(request)
        if pending is not None:
            return pending
        result = self._build_manager.reconcile(request)
        return self.handle_result(request, result)

    def _pending_before_reconcile(
        self, request: ReconcileRequest
    ) -> Optional[RestartCoordinatorResult]:
        """Keep an active handoff from re-entering normal reconciliation."""
        if not isinstance(request, ReconcileRequest):
            return None
        try:
            transaction = self._store.inspect()
        except TransactionError as exc:
            return self._failed(
                request,
                ReconcileResult(False, request, None),
                getattr(exc, "code", "TRANSACTION_INSPECTION_FAILED"),
                exc,
            )
        if transaction is None:
            return None
        if transaction.phase is not TransactionPhase.AWAITING_RESTART:
            return self._failed(
                request,
                ReconcileResult(False, request, None),
                "ACTIVE_TRANSACTION_CONFLICT",
                "an active restart transaction requires explicit recovery",
            )
        if transaction.request != request:
            return self._failed(
                request,
                ReconcileResult(False, request, None),
                "ACTIVE_TRANSACTION_CONFLICT",
                "an incompatible restart transaction is already active",
            )
        try:
            capability = self._resolve_capability()
            current_session = self._session_id_provider()
        except Exception as exc:
            return self._failed(
                request,
                ReconcileResult(False, request, None),
                "PENDING_TRANSACTION_INSPECTION_FAILED",
                exc,
                capability=None,
            )
        pending_result = ReconcileResult(
            success=True,
            request=request,
            desired_fingerprint=transaction.desired_state_fingerprint,
            restart_report=RestartReport(RestartRequirement.KODI_RESTART),
        )
        if current_session == transaction.originating_kodi_session_id:
            if capability is RestartCapability.AUTOMATIC_APP_RESTART:
                return self.handle_result(request, pending_result)
            return self._prepare_manual(request, pending_result, capability)
        return self._failed(
            request,
            pending_result,
            "RESUME_PENDING",
            "a new Kodi session is ready for BM-020C resume orchestration",
            capability=capability,
        )

    def handle_result(
        self, request: ReconcileRequest, reconcile_result: ReconcileResult
    ) -> RestartCoordinatorResult:
        """Handle a typed result without duplicating Build Manager execution."""
        if not isinstance(request, ReconcileRequest):
            return self._failed(
                request,
                reconcile_result,
                "INVALID_REQUEST",
                "request must be a ReconcileRequest",
            )
        if not isinstance(reconcile_result, ReconcileResult):
            return self._failed(
                request,
                ReconcileResult(False, request, None),
                "INVALID_RECONCILE_RESULT",
                "reconcile_result must be a ReconcileResult",
            )

        # A failed run never authorizes a restart, even if an earlier action
        # contributed KODI_RESTART to the aggregate report.
        if not reconcile_result.success:
            return RestartCoordinatorResult(
                RestartOutcome.FAILED,
                request,
                reconcile_result,
                message="reconciliation failed; restart handoff was not prepared",
            )
        if reconcile_result.request != request:
            return self._failed(
                request,
                reconcile_result,
                "REQUEST_MISMATCH",
                "reconcile result request does not match the request",
            )
        requirement = reconcile_result.restart_report.requirement
        if requirement is RestartRequirement.NONE:
            return RestartCoordinatorResult(
                RestartOutcome.COMPLETE,
                request,
                reconcile_result,
                message="reconciliation completed without a Kodi restart",
            )
        if requirement is not RestartRequirement.KODI_RESTART:
            return self._failed(
                request,
                reconcile_result,
                "UNSUPPORTED_RESTART_REQUIREMENT",
                "reconciliation returned an unsupported restart requirement",
            )

        try:
            capability = self._resolve_capability()
        except Exception as exc:
            return self._failed(
                request,
                reconcile_result,
                "CAPABILITY_RESOLUTION_FAILED",
                exc,
            )
        if capability is RestartCapability.AUTOMATIC_APP_RESTART:
            # BM-020C1 defines the future seam but deliberately ships no
            # automatic adapter.  Failing closed avoids pretending that a
            # platform-specific internal or external mechanism is approved.
            return RestartCoordinatorResult(
                RestartOutcome.FAILED,
                request,
                reconcile_result,
                capability=capability,
                failure=RestartCoordinatorFailure(
                    "AUTOMATIC_RESTART_ADAPTER_UNAVAILABLE",
                    "automatic Kodi restart has no approved production adapter",
                ),
                message="automatic restart capability is not implemented",
            )

        return self._prepare_manual(request, reconcile_result, capability)

    def _resolve_capability(self) -> RestartCapability:
        resolver = self._capability_resolver
        if hasattr(resolver, "resolve"):
            capability = resolver.resolve()
        elif callable(resolver):
            capability = resolver()
        else:
            raise TypeError("capability resolver is not callable")
        if not isinstance(capability, RestartCapability):
            raise TypeError("capability resolver returned an invalid capability")
        return capability

    def _prepare_manual(
        self,
        request: ReconcileRequest,
        reconcile_result: ReconcileResult,
        capability: RestartCapability,
    ) -> RestartCoordinatorResult:
        try:
            session_id = self._session_id_provider()
            existing = self._store.inspect()
            if existing is not None:
                if (
                    existing.phase is TransactionPhase.AWAITING_RESTART
                    and existing.request == request
                    and existing.desired_state_fingerprint
                    == reconcile_result.desired_fingerprint
                    and existing.restart_attempt_count == 0
                ):
                    transaction = existing
                else:
                    return self._failed(
                        request,
                        reconcile_result,
                        "ACTIVE_TRANSACTION_CONFLICT",
                        "an incompatible restart transaction is already active",
                        capability=capability,
                    )
            else:
                prepared = prepare_restart_transaction(
                    request,
                    reconcile_result,
                    session_id,
                    store=self._store,
                )
                if not prepared.succeeded or prepared.transaction is None:
                    failure = prepared.failure
                    return self._failed(
                        request,
                        reconcile_result,
                        failure.code if failure else "TRANSACTION_PREPARE_FAILED",
                        failure.message if failure else "restart transaction was not prepared",
                        capability=capability,
                    )
                transaction = prepared.transaction

            # Explicit read-back makes the manual caller contract independent
            # of the preparation helper's implementation details.
            read_back = self._store.inspect()
            if (
                read_back is None
                or read_back.transaction_id != transaction.transaction_id
                or read_back.phase is not TransactionPhase.AWAITING_RESTART
                or read_back.restart_attempt_count != 0
            ):
                return self._failed(
                    request,
                    reconcile_result,
                    "TRANSACTION_READBACK_FAILED",
                    "manual restart transaction read-back did not match",
                    capability=capability,
                )
            return RestartCoordinatorResult(
                RestartOutcome.MANUAL_RESTART_REQUIRED,
                request,
                reconcile_result,
                capability=capability,
                transaction=read_back,
                message="Restart Kodi completely to continue.",
            )
        except (TransactionError, TypeError, ValueError) as exc:
            return self._failed(
                request,
                reconcile_result,
                getattr(exc, "code", "TRANSACTION_PREPARE_FAILED"),
                exc,
                capability=capability,
            )

    @staticmethod
    def _failed(
        request: ReconcileRequest,
        reconcile_result: ReconcileResult,
        code: str,
        message: object,
        *,
        capability: Optional[RestartCapability] = None,
    ) -> RestartCoordinatorResult:
        return RestartCoordinatorResult(
            RestartOutcome.FAILED,
            request,
            reconcile_result,
            capability=capability,
            failure=RestartCoordinatorFailure(code, _bounded_message(message)),
            message="restart handoff failed",
        )


def reconcile_with_restart(
    request: ReconcileRequest,
    *,
    build_manager: Optional[BuildManager] = None,
    capability_resolver: Optional[object] = None,
    session_id_provider: Optional[Callable[[], str]] = None,
    store: Optional[TransactionStore] = None,
) -> RestartCoordinatorResult:
    """Public callable for future UI callers; manual restart is non-mutating."""
    return RestartCoordinator(
        build_manager,
        capability_resolver=capability_resolver,
        session_id_provider=session_id_provider,
        store=store,
    ).reconcile(request)
