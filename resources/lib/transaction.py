"""Durable BM-020B restart transaction storage and preparation.

This module owns only the durable handoff between a completed reconciliation
and a later Kodi process.  It deliberately does not restart Kodi, resume a
reconciliation, or serialize resolved/current Kodi state.
"""

from __future__ import annotations

import datetime as _datetime
import errno
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterator, Optional

from resources.lib.build_manager import ReconcileRequest, ReconcileResult
from resources.lib.frozen_resolution import InstallResolutionRecord, FrozenResolutionError
from resources.lib.restart import RestartRequirement


ADDON_ID = "script.build.manager"
SCHEMA_VERSION = 1
TRANSACTION_FILENAME = "restart_transaction.json"
LOCK_FILENAME = "restart_transaction.lock"
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_DIAGNOSTIC = 512
_MAX_STATUS_CODE = 96


class TransactionError(Exception):
    """Base class for fail-closed transaction errors."""

    code = "TRANSACTION_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TransactionLockBusy(TransactionError):
    code = "TRANSACTION_LOCK_BUSY"


class TransactionLockUnavailable(TransactionError):
    code = "TRANSACTION_LOCK_UNAVAILABLE"


class TransactionCorrupt(TransactionError):
    code = "TRANSACTION_CORRUPT"


class TransactionUnsupportedSchema(TransactionError):
    code = "TRANSACTION_UNSUPPORTED_SCHEMA"


class TransactionPersistenceError(TransactionError):
    code = "TRANSACTION_PERSISTENCE_FAILED"


class TransactionStateConflict(TransactionError):
    code = "TRANSACTION_STATE_CONFLICT"


class TransactionPhase(str, Enum):
    """Small durable state machine owned by BM-020B."""

    AWAITING_RESTART = "awaiting_restart"
    RESUMING = "resuming"
    NEEDS_ATTENTION = "needs_attention"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds")


def _valid_uuid(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc
    return value


def _valid_fingerprint(value: object) -> str:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value):
        raise ValueError("desired_state_fingerprint must be a sha256 fingerprint")
    return value


@dataclass(frozen=True)
class RestartTransaction:
    """Versioned, secret-safe durable transaction record."""

    transaction_id: str
    phase: TransactionPhase
    request: ReconcileRequest
    desired_state_fingerprint: str
    restart_requirement: RestartRequirement
    originating_kodi_session_id: str
    restart_attempt_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    status_code: str = ""
    status_message: str = ""
    private_overlay_id: str = ""
    private_overlay_fingerprint: str = ""
    private_overlay_required: bool = False

    schema_version = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _valid_uuid(self.transaction_id, "transaction_id")
        if not isinstance(self.phase, TransactionPhase):
            raise ValueError("phase must be a TransactionPhase")
        if not isinstance(self.request, ReconcileRequest):
            raise ValueError("request must be a ReconcileRequest")
        _valid_fingerprint(self.desired_state_fingerprint)
        if self.restart_requirement is not RestartRequirement.KODI_RESTART:
            raise ValueError("transaction restart_requirement must be kodi_restart")
        _valid_uuid(self.originating_kodi_session_id, "originating_kodi_session_id")
        if (
            not isinstance(self.restart_attempt_count, int)
            or isinstance(self.restart_attempt_count, bool)
            or self.restart_attempt_count < 0
        ):
            raise ValueError("restart_attempt_count must be a non-negative integer")
        for field in ("created_at", "updated_at"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or len(value) > 64:
                raise ValueError(f"{field} must be a bounded non-empty string")
        if (
            not isinstance(self.status_code, str)
            or len(self.status_code) > _MAX_STATUS_CODE
        ):
            raise ValueError("status_code must be a bounded string")
        if (
            not isinstance(self.status_message, str)
            or len(self.status_message) > _MAX_DIAGNOSTIC
        ):
            raise ValueError("status_message must be a bounded string")
        if not isinstance(self.private_overlay_id, str) or len(self.private_overlay_id) > 64:
            raise ValueError("private_overlay_id must be a bounded string")
        if self.private_overlay_fingerprint:
            _valid_fingerprint(self.private_overlay_fingerprint)
        if not isinstance(self.private_overlay_required, bool):
            raise ValueError("private_overlay_required must be boolean")

    def to_dict(self) -> dict:
        """Return only stable selectors and typed transaction metadata."""
        return {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": self.transaction_id,
            "phase": self.phase.value,
            "request": self.request.to_dict(),
            "desired_state_fingerprint": self.desired_state_fingerprint,
            "restart_requirement": self.restart_requirement.value,
            "originating_kodi_session_id": self.originating_kodi_session_id,
            "restart_attempt_count": self.restart_attempt_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status_code": self.status_code,
            "status_message": self.status_message,
            "private_overlay_id": self.private_overlay_id,
            "private_overlay_fingerprint": self.private_overlay_fingerprint,
            "private_overlay_required": self.private_overlay_required,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "RestartTransaction":
        if not isinstance(value, dict):
            raise TransactionCorrupt("transaction root must be an object")
        required = {
            "schema_version", "transaction_id", "phase", "request",
            "desired_state_fingerprint", "restart_requirement",
            "originating_kodi_session_id", "restart_attempt_count",
            "created_at", "updated_at",
        }
        optional = {
            "status_code", "status_message", "private_overlay_id",
            "private_overlay_fingerprint", "private_overlay_required",
        }
        if set(value) - required - optional:
            raise TransactionCorrupt("transaction fields are not exactly supported")
        if not required.issubset(value):
            raise TransactionCorrupt("transaction is missing required fields")
        if value["schema_version"] != SCHEMA_VERSION:
            raise TransactionUnsupportedSchema(
                f"unsupported transaction schema {value['schema_version']!r}"
            )
        request_value = value["request"]
        request_fields = {"manifest_path", "device_profile_id"}
        if (
            not isinstance(request_value, dict)
            or not request_fields.issubset(request_value)
            or set(request_value) - request_fields - {
                "install_resolutions", "source_software_fingerprint",
                "frozen_transaction_id"
            }
        ):
            raise TransactionCorrupt("transaction request is not a safe selector object")
        try:
            raw_resolutions = request_value.get("install_resolutions", [])
            if not isinstance(raw_resolutions, list):
                raise TransactionCorrupt("transaction install resolutions must be an array")
            install_resolutions = tuple(
                InstallResolutionRecord.from_dict(item) for item in raw_resolutions
            )
            request = ReconcileRequest(
                manifest_path=request_value["manifest_path"],
                device_profile_id=request_value["device_profile_id"],
                install_resolutions=install_resolutions,
                source_software_fingerprint=request_value.get(
                    "source_software_fingerprint", ""
                ),
                frozen_transaction_id=request_value.get("frozen_transaction_id", ""),
            )
            phase = TransactionPhase(value["phase"])
            requirement = RestartRequirement(value["restart_requirement"])
            return cls(
                transaction_id=value["transaction_id"],
                phase=phase,
                request=request,
                desired_state_fingerprint=value["desired_state_fingerprint"],
                restart_requirement=requirement,
                originating_kodi_session_id=value["originating_kodi_session_id"],
                restart_attempt_count=value["restart_attempt_count"],
                created_at=value["created_at"],
                updated_at=value["updated_at"],
                status_code=value.get("status_code", ""),
                status_message=value.get("status_message", ""),
                private_overlay_id=value.get("private_overlay_id", ""),
                private_overlay_fingerprint=value.get("private_overlay_fingerprint", ""),
                private_overlay_required=value.get("private_overlay_required", False),
            )
        except TransactionError:
            raise
        except (KeyError, TypeError, ValueError, FrozenResolutionError) as exc:
            raise TransactionCorrupt("transaction contains an invalid field") from exc

    def with_phase(self, phase: TransactionPhase) -> "RestartTransaction":
        return replace(self, phase=phase, updated_at=_utc_now())

    def with_status(
        self,
        *,
        phase: Optional[TransactionPhase] = None,
        status_code: str = "",
        status_message: str = "",
    ) -> "RestartTransaction":
        return replace(
            self,
            phase=phase or self.phase,
            status_code=status_code,
            status_message=status_message,
            updated_at=_utc_now(),
        )


class TransactionLock:
    """Profile-local OS-backed lock whose ownership disappears on process exit."""

    def __init__(self, path: str):
        self.path = path
        self._handle = None
        self._fcntl = None

    def acquire(self) -> None:
        try:
            import fcntl  # POSIX; all supported Kodi targets are POSIX-based.
        except ImportError as exc:
            raise TransactionLockUnavailable(
                "portable OS-backed transaction locking is unavailable"
            ) from exc
        self._fcntl = fcntl
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            self._handle = os.fdopen(fd, "a+")
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._close_handle()
            raise TransactionLockBusy("another transaction operation is active") from exc
        except OSError as exc:
            self._close_handle()
            raise TransactionLockUnavailable(
                "could not acquire the transaction lock"
            ) from exc

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._fcntl.flock(self._handle.fileno(), self._fcntl.LOCK_UN)
        finally:
            self._close_handle()

    def _close_handle(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            finally:
                self._handle = None

    def __enter__(self) -> "TransactionLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()


class TransactionStore:
    """Validated, atomic store under special://profile/addon_data/..."""

    def __init__(self, profile_root: str = "special://profile/", addon_id: str = ADDON_ID):
        self._profile_root = profile_root
        self._addon_id = addon_id
        self._translated_root: Optional[str] = None

    @property
    def profile_directory(self) -> str:
        if self._translated_root is not None:
            root = self._translated_root
        elif "://" in self._profile_root:
            try:
                import xbmcvfs
                root = xbmcvfs.translatePath(self._profile_root)
            except (ImportError, AttributeError, OSError) as exc:
                raise TransactionPersistenceError(
                    "Kodi profile path translation is unavailable"
                ) from exc
        else:
            root = self._profile_root
        if not isinstance(root, str) or not root or "://" in root:
            raise TransactionPersistenceError("Kodi profile path is not local")
        self._translated_root = os.path.realpath(root)
        return self._translated_root

    @property
    def directory(self) -> str:
        return os.path.join(self.profile_directory, "addon_data", self._addon_id)

    @property
    def transaction_path(self) -> str:
        return os.path.join(self.directory, TRANSACTION_FILENAME)

    @property
    def lock_path(self) -> str:
        return os.path.join(self.directory, LOCK_FILENAME)

    def acquire_lock(self) -> TransactionLock:
        return TransactionLock(self.lock_path)

    @contextmanager
    def locked(self) -> Iterator[TransactionLock]:
        lock = self.acquire_lock()
        with lock:
            yield lock

    def inspect(self) -> Optional[RestartTransaction]:
        with self.locked():
            return self._read_unlocked()

    def create(self, transaction: RestartTransaction) -> RestartTransaction:
        if not isinstance(transaction, RestartTransaction):
            raise TransactionPersistenceError("transaction has an invalid type")
        with self.locked():
            if os.path.exists(self.transaction_path):
                raise TransactionPersistenceError(
                    "an active transaction already exists"
                )
            self._write_unlocked(transaction, previous_bytes=None)
            return transaction

    def update_phase(self, phase: TransactionPhase) -> RestartTransaction:
        if not isinstance(phase, TransactionPhase):
            raise TransactionPersistenceError("phase has an invalid type")
        with self.locked():
            current = self._read_unlocked()
            if current is None:
                raise TransactionPersistenceError("no active transaction exists")
            updated = current.with_phase(phase)
            self._write_unlocked(updated, previous_bytes=self._read_bytes())
            return updated

    def transition_expected(
        self,
        *,
        transaction_id: str,
        expected_phase: TransactionPhase,
        new_phase: TransactionPhase,
        status_code: str = "",
        status_message: str = "",
    ) -> RestartTransaction:
        """Atomically transition only the expected durable transaction state."""
        if not isinstance(expected_phase, TransactionPhase):
            raise TransactionPersistenceError("expected phase has an invalid type")
        if not isinstance(new_phase, TransactionPhase):
            raise TransactionPersistenceError("new phase has an invalid type")
        with self.locked():
            current = self._read_unlocked()
            if current is None:
                raise TransactionStateConflict("no active transaction exists")
            if (
                current.transaction_id != transaction_id
                or current.phase is not expected_phase
            ):
                raise TransactionStateConflict(
                    "transaction identity or phase changed before transition"
                )
            updated = current.with_status(
                phase=new_phase,
                status_code=status_code,
                status_message=status_message,
            )
            self._write_unlocked(updated, previous_bytes=self._read_bytes())
            return updated

    def clear_expected(
        self, *, transaction_id: str, expected_phase: TransactionPhase
    ) -> bool:
        """Clear only an unchanged transaction identity and phase."""
        if not isinstance(expected_phase, TransactionPhase):
            raise TransactionPersistenceError("expected phase has an invalid type")
        with self.locked():
            current = self._read_unlocked()
            if current is None:
                raise TransactionStateConflict("no active transaction exists")
            if (
                current.transaction_id != transaction_id
                or current.phase is not expected_phase
            ):
                raise TransactionStateConflict(
                    "transaction identity or phase changed before clear"
                )
            try:
                os.remove(self.transaction_path)
                self._fsync_directory(self.directory)
                return True
            except OSError as exc:
                raise TransactionPersistenceError(
                    "could not clear the completed transaction"
                ) from exc

    def clear(self) -> bool:
        """Explicitly abandon the record; never called by startup inspection."""
        with self.locked():
            try:
                os.remove(self.transaction_path)
                return True
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise TransactionPersistenceError(
                    "could not explicitly clear the transaction"
                ) from exc

    def _read_bytes(self) -> bytes:
        try:
            with open(self.transaction_path, "rb") as handle:
                return handle.read()
        except OSError as exc:
            raise TransactionPersistenceError(
                "could not preserve the existing transaction"
            ) from exc

    def _read_unlocked(self) -> Optional[RestartTransaction]:
        try:
            with open(self.transaction_path, "rb") as handle:
                raw = handle.read(128 * 1024)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise TransactionPersistenceError(
                "could not read the transaction"
            ) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransactionCorrupt("transaction JSON is malformed") from exc
        return RestartTransaction.from_dict(value)

    def _write_unlocked(
        self, transaction: RestartTransaction, *, previous_bytes: Optional[bytes]
    ) -> None:
        parent = self.directory
        try:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        except OSError as exc:
            raise TransactionPersistenceError(
                "could not create the transaction directory"
            ) from exc
        data = (transaction.to_json() + "\n").encode("utf-8")
        staged: Optional[str] = None
        replaced = False
        try:
            fd, staged = tempfile.mkstemp(
                dir=parent, prefix=".restart_transaction.", suffix=".tmp"
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # Validate the complete staged representation before replacement.
            with open(staged, "rb") as handle:
                RestartTransaction.from_dict(json.loads(handle.read().decode("utf-8")))
            os.replace(staged, self.transaction_path)
            staged = None
            replaced = True
            self._read_unlocked()
            self._fsync_directory(parent)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TransactionError) as exc:
            if replaced:
                self._restore_previous(previous_bytes)
            if isinstance(exc, TransactionError):
                raise
            raise TransactionPersistenceError(
                "atomic transaction persistence failed"
            ) from exc
        finally:
            if staged is not None:
                try:
                    os.remove(staged)
                except OSError:
                    pass

    @staticmethod
    def _fsync_directory(parent: str) -> None:
        try:
            fd = os.open(parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
        finally:
            os.close(fd)

    def _restore_previous(self, previous_bytes: Optional[bytes]) -> None:
        if previous_bytes is None:
            try:
                os.remove(self.transaction_path)
            except OSError:
                pass
            return
        fd, staged = tempfile.mkstemp(
            dir=self.directory, prefix=".restart_transaction.restore.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(previous_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, self.transaction_path)
            staged = None
        finally:
            if staged is not None:
                try:
                    os.remove(staged)
                except OSError:
                    pass


@dataclass(frozen=True)
class TransactionFailure:
    code: str
    message: str


@dataclass(frozen=True)
class PrepareTransactionResult:
    created: bool
    transaction: Optional[RestartTransaction] = None
    failure: Optional[TransactionFailure] = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None


def prepare_restart_transaction(
    request: ReconcileRequest,
    reconcile_result: ReconcileResult,
    current_session_id: str,
    *,
    store: Optional[TransactionStore] = None,
) -> PrepareTransactionResult:
    """Prepare durable state only after a successful restart-requiring run."""
    try:
        if not isinstance(request, ReconcileRequest):
            raise ValueError("request must be a ReconcileRequest")
        if not isinstance(reconcile_result, ReconcileResult):
            raise ValueError("reconcile_result must be a ReconcileResult")
        if not reconcile_result.success:
            raise ValueError("failed reconciliation cannot prepare a restart")
        if reconcile_result.request != request:
            raise ValueError("reconcile result request does not match the request")
        if reconcile_result.restart_report.requirement is RestartRequirement.NONE:
            return PrepareTransactionResult(created=False)
        if reconcile_result.restart_report.requirement is not RestartRequirement.KODI_RESTART:
            raise ValueError("reconcile result has an unsupported restart requirement")
        fingerprint = _valid_fingerprint(reconcile_result.desired_fingerprint)
        session_id = _valid_uuid(current_session_id, "current_session_id")
        transaction = RestartTransaction(
            transaction_id=str(uuid.uuid4()),
            phase=TransactionPhase.AWAITING_RESTART,
            request=request,
            desired_state_fingerprint=fingerprint,
            restart_requirement=RestartRequirement.KODI_RESTART,
            originating_kodi_session_id=session_id,
            created_at=_utc_now(),
            updated_at=_utc_now(),
            private_overlay_id=(
                reconcile_result.private_overlay.overlay_id
                if reconcile_result.private_overlay else ""
            ),
            private_overlay_fingerprint=(
                reconcile_result.private_overlay.fingerprint
                if reconcile_result.private_overlay else ""
            ),
            private_overlay_required=(
                reconcile_result.private_overlay.required
                if reconcile_result.private_overlay else False
            ),
        )
        (store or TransactionStore()).create(transaction)
        return PrepareTransactionResult(created=True, transaction=transaction)
    except (TransactionError, TypeError, ValueError) as exc:
        code = getattr(exc, "code", "INVALID_RESTART_TRANSACTION")
        return PrepareTransactionResult(
            created=False,
            failure=TransactionFailure(code=code, message=str(exc)),
        )
