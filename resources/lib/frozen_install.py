"""BM-022 frozen-build installation and transaction lifecycle.

The installer prefers exact BM-021B artifacts and immutable content-addressed
packages. An explicit per-add-on policy may offer a user-selected current
version from one captured, verified repository or an explicit skip. All other
missing artifacts remain blocking, and existing installations must match the
selected exact or resolved version.

The durable transaction owns the global updater quarantine from the first
mutation until explicit final release or recovery.  It is intentionally
separate from BM-020's restart transaction; the startup precondition lets the
frozen transaction reassert ``NEVER_CHECK`` before BM-020 may resume.
"""

from __future__ import annotations

import datetime as _datetime
import errno
import fcntl
import hashlib
import io
import json
import os
import re
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from resources.lib.artifacts import ArtifactStore, ArtifactValidationError, validate_addon_zip
from resources.lib.addons import KodiRuntimeAddonBackend, RepositoryPackage
from resources.lib.build_manager import ActionFailureDiagnostic, ReconcileRequest
from resources.lib.skin import SkinFailureCode
from resources.lib.private_resource import ResourceInitializationStage
from resources.lib.frozen import (
    AddonCaptureNode,
    CaptureError,
    CaptureStatus,
    FrozenBuildManifest,
)
from resources.lib.frozen_resolution import (
    FrozenBuildRecoverabilitySummary,
    FrozenInstallResolutionManifest,
    FrozenPlanAction,
    FrozenPlanActionKind,
    FrozenResolutionError,
    InstallResolution,
    InstallResolutionRecord,
    Recoverability,
    ResolutionChoice,
    ResolutionPrompt,
    ResolutionState,
    default_exact_record,
    effective_policy,
    install_plan_fingerprint,
    resolution_fingerprint,
    resolved_software_fingerprint,
    summarize_frozen_recoverability,
)
from resources.lib.manifest import (
    FrozenInstallPolicy,
    FrozenInstallPolicyMode,
)
from resources.lib.repository import _extract_zip_to_directory
from resources.lib.update_guard import (
    AddonUpdatePolicy,
    AddonUpdateGuard,
    KodiJsonRpcUpdatePolicyBackend,
    UpdateGuardError,
    UpdatePolicyBackend,
)


class FrozenInstallError(Exception):
    """Base class for safe frozen-install failures."""

    code = "FROZEN_INSTALL_ERROR"


class FrozenConfigurationFailure(FrozenInstallError):
    """Safe CONFIGURE failure with validated transaction metadata updates."""

    def __init__(self, message: str, *, transaction_updates=None):
        super().__init__(message)
        self.transaction_updates = transaction_updates or {}


class FrozenInstallValidationError(FrozenInstallError):
    code = "FROZEN_MANIFEST_INVALID"


class FrozenInstallPersistenceError(FrozenInstallError):
    code = "FROZEN_TRANSACTION_PERSISTENCE_FAILED"


class FrozenInstallStateConflict(FrozenInstallError):
    code = "FROZEN_TRANSACTION_STATE_CONFLICT"


class FrozenInstallPhase(str, Enum):
    PREPARING = "preparing"
    INSTALLING_SOFTWARE = "installing_software"
    CONFIGURING = "configuring"
    AWAITING_RESTART = "awaiting_restart"
    RESUMING = "resuming"
    VALIDATING = "validating"
    NEEDS_ATTENTION = "needs_attention"
    COMPLETE = "complete"


class FrozenLifecycleStage(str, Enum):
    NONE = "none"
    INSTALLING_SOFTWARE = "installing_software"
    QUIESCENCE_AWAITING_RESTART = "quiescence_awaiting_restart"
    CONFIGURING = "configuring"
    CONFIGURATION_AWAITING_RESTART = "configuration_awaiting_restart"
    PRIVATE_VERIFIED = "private_verified"
    ACTIVATION_RELEASED = "activation_released"
    FINAL_ACTIVATION_AWAITING_RESTART = "final_activation_awaiting_restart"


_TRANSACTION_SCHEMA = 3
_TRANSACTION_FILENAME = "frozen_install_transaction.json"
_LOCK_FILENAME = "frozen_install_transaction.lock"
_MAX_CODE = 96
_MAX_MESSAGE = 512
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SAFE_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds")


def _log_lifecycle_event(message: str) -> None:
    """Log a fixed, value-free lifecycle milestone when running inside Kodi."""
    try:
        import xbmc
        xbmc.log(message, xbmc.LOGINFO)
    except (ImportError, AttributeError, RuntimeError):
        pass


def _safe_exception_location(exc: BaseException) -> str:
    """Return code coordinates without exception text or runtime values."""
    tb = exc.__traceback__
    if tb is None:
        return "unknown"
    while tb.tb_next is not None:
        tb = tb.tb_next
    filename = Path(tb.tb_frame.f_code.co_filename).name
    function = tb.tb_frame.f_code.co_name
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", filename):
        filename = "unknown"
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", function):
        function = "unknown"
    return f"{filename}:{tb.tb_lineno}:{function}"


def _bounded(value: object, limit: int, default: str) -> str:
    text = str(value).strip()
    return (text or default)[:limit]


def _valid_uuid(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise FrozenInstallValidationError(f"{field} must be a UUID")
    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise FrozenInstallValidationError(f"{field} must be a UUID") from exc
    return value


def _valid_fingerprint(value: object) -> str:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value):
        raise FrozenInstallValidationError("manifest fingerprint is invalid")
    return value


@dataclass(frozen=True)
class FrozenInstallTransaction:
    """Secret-safe durable state for one frozen installation."""

    transaction_id: str
    build_id: str
    manifest_path: str
    device_profile_id: str
    manifest_fingerprint: str
    phase: FrozenInstallPhase
    originating_kodi_session_id: str
    original_update_policy: AddonUpdatePolicy
    updater_guard_required: bool = True
    restart_transaction_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    status_code: str = ""
    status_message: str = ""
    private_overlay_id: str = ""
    private_overlay_fingerprint: str = ""
    private_overlay_required: bool = False
    install_plan_fingerprint: str = ""
    policies: Tuple[FrozenInstallPolicy, ...] = ()
    resolution_records: Tuple[InstallResolutionRecord, ...] = ()
    resolution_fingerprint: str = ""
    resolved_software_fingerprint: str = ""
    configuration_manifest_path: str = ""
    lifecycle_stage: FrozenLifecycleStage = FrozenLifecycleStage.NONE
    activation_hold_ids: Tuple[str, ...] = ()
    activation_hold_released: bool = True
    lifecycle_restart_count: int = 0

    def __post_init__(self) -> None:
        _valid_uuid(self.transaction_id, "transaction_id")
        _valid_uuid(self.originating_kodi_session_id, "originating_kodi_session_id")
        if not isinstance(self.build_id, str) or not self.build_id:
            raise FrozenInstallValidationError("build_id must be non-empty")
        if not isinstance(self.manifest_path, str) or not self.manifest_path:
            raise FrozenInstallValidationError("manifest_path must be non-empty")
        if not isinstance(self.device_profile_id, str) or not self.device_profile_id:
            raise FrozenInstallValidationError("device_profile_id must be non-empty")
        _valid_fingerprint(self.manifest_fingerprint)
        if not isinstance(self.phase, FrozenInstallPhase):
            raise FrozenInstallValidationError("invalid frozen-install phase")
        if not isinstance(self.lifecycle_stage, FrozenLifecycleStage):
            raise FrozenInstallValidationError("invalid frozen lifecycle stage")
        if not isinstance(self.original_update_policy, AddonUpdatePolicy):
            raise FrozenInstallValidationError("invalid original updater policy")
        if not isinstance(self.updater_guard_required, bool):
            raise FrozenInstallValidationError("updater_guard_required must be boolean")
        if self.restart_transaction_id:
            _valid_uuid(self.restart_transaction_id, "restart_transaction_id")
        for field in ("created_at", "updated_at"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or len(value) > 64:
                raise FrozenInstallValidationError(f"{field} is invalid")
        if not isinstance(self.status_code, str) or len(self.status_code) > _MAX_CODE:
            raise FrozenInstallValidationError("status_code is invalid")
        if not isinstance(self.status_message, str) or len(self.status_message) > _MAX_MESSAGE:
            raise FrozenInstallValidationError("status_message is invalid")
        if not isinstance(self.private_overlay_id, str) or len(self.private_overlay_id) > 64:
            raise FrozenInstallValidationError("private_overlay_id is invalid")
        if self.private_overlay_fingerprint and not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.private_overlay_fingerprint
        ):
            raise FrozenInstallValidationError("private_overlay_fingerprint is invalid")
        if not isinstance(self.private_overlay_required, bool):
            raise FrozenInstallValidationError("private_overlay_required is invalid")
        for field in (
            "install_plan_fingerprint",
            "resolution_fingerprint",
            "resolved_software_fingerprint",
        ):
            value = getattr(self, field)
            if value and not _FINGERPRINT.fullmatch(value):
                raise FrozenInstallValidationError(f"{field} is invalid")
        if len({policy.addon_id for policy in self.policies}) != len(self.policies):
            raise FrozenInstallValidationError("transaction policies contain duplicates")
        if len({record.addon_id for record in self.resolution_records}) != len(self.resolution_records):
            raise FrozenInstallValidationError("transaction resolutions contain duplicates")
        if not isinstance(self.configuration_manifest_path, str):
            raise FrozenInstallValidationError("configuration_manifest_path is invalid")
        if any(
            not isinstance(addon_id, str) or not _ADDON_ID.fullmatch(addon_id)
            for addon_id in self.activation_hold_ids
        ) or len(set(self.activation_hold_ids)) != len(self.activation_hold_ids):
            raise FrozenInstallValidationError("activation hold IDs are invalid")
        if not isinstance(self.activation_hold_released, bool):
            raise FrozenInstallValidationError("activation_hold_released must be boolean")
        if (
            not isinstance(self.lifecycle_restart_count, int)
            or isinstance(self.lifecycle_restart_count, bool)
            or not 0 <= self.lifecycle_restart_count <= 3
        ):
            raise FrozenInstallValidationError("lifecycle_restart_count is invalid")
        if self.resolution_records:
            expected_resolution = resolution_fingerprint(self.resolution_records)
            if self.resolution_fingerprint and self.resolution_fingerprint != expected_resolution:
                raise FrozenInstallValidationError("transaction resolution fingerprint does not match")

    def to_dict(self) -> dict:
        return {
            "schema_version": _TRANSACTION_SCHEMA,
            "transaction_id": self.transaction_id,
            "build_id": self.build_id,
            "manifest_path": self.manifest_path,
            "device_profile_id": self.device_profile_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "phase": self.phase.value,
            "originating_kodi_session_id": self.originating_kodi_session_id,
            "original_update_policy": int(self.original_update_policy),
            "updater_guard_required": self.updater_guard_required,
            "restart_transaction_id": self.restart_transaction_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status_code": self.status_code,
            "status_message": self.status_message,
            "private_overlay_id": self.private_overlay_id,
            "private_overlay_fingerprint": self.private_overlay_fingerprint,
            "private_overlay_required": self.private_overlay_required,
            "install_plan_fingerprint": self.install_plan_fingerprint,
            "policies": [policy.to_dict() for policy in self.policies],
            "resolution_records": [record.to_dict() for record in self.resolution_records],
            "resolution_fingerprint": self.resolution_fingerprint,
            "resolved_software_fingerprint": self.resolved_software_fingerprint,
            "configuration_manifest_path": self.configuration_manifest_path,
            "lifecycle_stage": self.lifecycle_stage.value,
            "activation_hold_ids": list(self.activation_hold_ids),
            "activation_hold_released": self.activation_hold_released,
            "lifecycle_restart_count": self.lifecycle_restart_count,
        }

    @classmethod
    def from_dict(cls, value: object) -> "FrozenInstallTransaction":
        if not isinstance(value, dict):
            raise FrozenInstallPersistenceError("frozen transaction root is not an object")
        required = {
            "schema_version", "transaction_id", "build_id", "manifest_path",
            "device_profile_id", "manifest_fingerprint", "phase",
            "originating_kodi_session_id", "original_update_policy",
            "updater_guard_required", "restart_transaction_id", "created_at",
            "updated_at", "status_code", "status_message",
        }
        optional = {
            "private_overlay_id", "private_overlay_fingerprint",
            "private_overlay_required",
            "install_plan_fingerprint", "policies", "resolution_records",
            "resolution_fingerprint", "resolved_software_fingerprint",
            "configuration_manifest_path", "lifecycle_stage", "activation_hold_ids",
            "activation_hold_released", "lifecycle_restart_count",
        }
        if set(value) - required - optional or not required.issubset(value):
            raise FrozenInstallPersistenceError("frozen transaction fields are unsupported")
        if value["schema_version"] not in (1, 2, _TRANSACTION_SCHEMA):
            raise FrozenInstallPersistenceError("unsupported frozen transaction schema")
        if value["schema_version"] in (2, _TRANSACTION_SCHEMA) and not {
            "install_plan_fingerprint", "policies", "resolution_records",
            "resolution_fingerprint", "resolved_software_fingerprint",
        }.issubset(value):
            raise FrozenInstallPersistenceError("frozen transaction is missing resolution metadata")
        if value["schema_version"] == _TRANSACTION_SCHEMA and not {
            "configuration_manifest_path", "lifecycle_stage", "activation_hold_ids",
            "activation_hold_released", "lifecycle_restart_count",
        }.issubset(value):
            raise FrozenInstallPersistenceError("frozen transaction is missing lifecycle metadata")
        try:
            policies = tuple(
                FrozenInstallPolicy(
                    addon_id=item["addon_id"],
                    mode=FrozenInstallPolicyMode(item["policy"]),
                    repository_id=item.get("repository_id", ""),
                )
                for item in value.get("policies", [])
            )
            resolutions = tuple(
                InstallResolutionRecord.from_dict(item)
                for item in value.get("resolution_records", [])
            )
            return cls(
                transaction_id=value["transaction_id"],
                build_id=value["build_id"],
                manifest_path=value["manifest_path"],
                device_profile_id=value["device_profile_id"],
                manifest_fingerprint=value["manifest_fingerprint"],
                phase=FrozenInstallPhase(value["phase"]),
                originating_kodi_session_id=value["originating_kodi_session_id"],
                original_update_policy=AddonUpdatePolicy(value["original_update_policy"]),
                updater_guard_required=value["updater_guard_required"],
                restart_transaction_id=value["restart_transaction_id"],
                created_at=value["created_at"],
                updated_at=value["updated_at"],
                status_code=value["status_code"],
                status_message=value["status_message"],
                private_overlay_id=value.get("private_overlay_id", ""),
                private_overlay_fingerprint=value.get("private_overlay_fingerprint", ""),
                private_overlay_required=value.get("private_overlay_required", False),
                install_plan_fingerprint=value.get("install_plan_fingerprint", ""),
                policies=policies,
                resolution_records=resolutions,
                resolution_fingerprint=value.get("resolution_fingerprint", ""),
                resolved_software_fingerprint=value.get("resolved_software_fingerprint", ""),
                configuration_manifest_path=value.get("configuration_manifest_path", ""),
                lifecycle_stage=FrozenLifecycleStage(
                    value.get("lifecycle_stage", FrozenLifecycleStage.NONE.value)
                ),
                activation_hold_ids=tuple(value.get("activation_hold_ids", ())),
                activation_hold_released=value.get(
                    "activation_hold_released",
                    not bool(value.get("activation_hold_ids", ())),
                ),
                lifecycle_restart_count=value.get("lifecycle_restart_count", 0),
            )
        except (KeyError, TypeError, ValueError, FrozenInstallError, FrozenResolutionError) as exc:
            if isinstance(exc, FrozenInstallError):
                raise
            raise FrozenInstallPersistenceError("frozen transaction contains invalid fields") from exc

    def with_phase(
        self,
        phase: FrozenInstallPhase,
        *,
        originating_kodi_session_id: Optional[str] = None,
        status_code: str = "",
        status_message: str = "",
        restart_transaction_id: Optional[str] = None,
        private_overlay_id: Optional[str] = None,
        private_overlay_fingerprint: Optional[str] = None,
        private_overlay_required: Optional[bool] = None,
        resolution_records: Optional[Tuple[InstallResolutionRecord, ...]] = None,
        resolution_fingerprint_value: Optional[str] = None,
        resolved_software_fingerprint_value: Optional[str] = None,
        configuration_manifest_path: Optional[str] = None,
        lifecycle_stage: Optional[FrozenLifecycleStage] = None,
        activation_hold_ids: Optional[Tuple[str, ...]] = None,
        activation_hold_released: Optional[bool] = None,
        lifecycle_restart_count: Optional[int] = None,
    ) -> "FrozenInstallTransaction":
        return replace(
            self,
            phase=phase,
            originating_kodi_session_id=(
                self.originating_kodi_session_id
                if originating_kodi_session_id is None
                else _valid_uuid(originating_kodi_session_id, "originating_kodi_session_id")
            ),
            status_code=_bounded(status_code, _MAX_CODE, "") if status_code else "",
            status_message=_bounded(status_message, _MAX_MESSAGE, "") if status_message else "",
            restart_transaction_id=(
                self.restart_transaction_id
                if restart_transaction_id is None else restart_transaction_id
            ),
            private_overlay_id=(
                self.private_overlay_id
                if private_overlay_id is None else private_overlay_id
            ),
            private_overlay_fingerprint=(
                self.private_overlay_fingerprint
                if private_overlay_fingerprint is None else private_overlay_fingerprint
            ),
            private_overlay_required=(
                self.private_overlay_required
                if private_overlay_required is None else private_overlay_required
            ),
            resolution_records=(
                self.resolution_records
                if resolution_records is None else resolution_records
            ),
            resolution_fingerprint=(
                self.resolution_fingerprint
                if resolution_fingerprint_value is None else resolution_fingerprint_value
            ),
            resolved_software_fingerprint=(
                self.resolved_software_fingerprint
                if resolved_software_fingerprint_value is None
                else resolved_software_fingerprint_value
            ),
            configuration_manifest_path=(
                self.configuration_manifest_path
                if configuration_manifest_path is None else configuration_manifest_path
            ),
            lifecycle_stage=(
                self.lifecycle_stage if lifecycle_stage is None else lifecycle_stage
            ),
            activation_hold_ids=(
                self.activation_hold_ids
                if activation_hold_ids is None else activation_hold_ids
            ),
            activation_hold_released=(
                self.activation_hold_released
                if activation_hold_released is None else activation_hold_released
            ),
            lifecycle_restart_count=(
                self.lifecycle_restart_count
                if lifecycle_restart_count is None else lifecycle_restart_count
            ),
            updated_at=_utc_now(),
        )


class FrozenInstallLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self._handle = self.path.open("a+")
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.release()
            raise FrozenInstallStateConflict("frozen install transaction is busy") from exc
        except OSError as exc:
            self.release()
            raise FrozenInstallPersistenceError("could not acquire frozen transaction lock") from exc

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self._handle.close()
        finally:
            self._handle = None

    def __enter__(self) -> "FrozenInstallLock":
        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()


class FrozenInstallStore:
    """Atomic, profile-local persistence for frozen-install state."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else default_frozen_install_root()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @property
    def transaction_path(self) -> Path:
        return self.root / _TRANSACTION_FILENAME

    @property
    def lock_path(self) -> Path:
        return self.root / _LOCK_FILENAME

    @property
    def resolutions_dir(self) -> Path:
        return self.root / "install_resolutions"

    def resolution_path(self, fingerprint: str) -> Path:
        if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
            raise FrozenInstallPersistenceError("resolution fingerprint is invalid")
        return self.resolutions_dir / f"{fingerprint}.json"

    def save_resolution_manifest(
        self, manifest: FrozenInstallResolutionManifest
    ) -> Path:
        """Persist an immutable, safe derivative install-resolution record."""
        if not isinstance(manifest, FrozenInstallResolutionManifest):
            raise FrozenInstallPersistenceError("install resolution record is invalid")
        data = (json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode()
        destination = self.resolution_path(manifest.resolution_fingerprint)
        staged: Optional[Path] = None
        try:
            self.resolutions_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            if destination.exists():
                if destination.read_bytes() != data:
                    raise FrozenInstallPersistenceError("resolution identity already has different content")
                return destination
            fd, name = tempfile.mkstemp(prefix=".resolution.", suffix=".tmp", dir=self.resolutions_dir)
            staged = Path(name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staged, destination)
            except FileExistsError:
                if destination.read_bytes() != data:
                    raise FrozenInstallPersistenceError("resolution identity already has different content")
            staged.unlink()
            staged = None
            self._fsync_directory_path(self.resolutions_dir)
            self.load_resolution_manifest(manifest.resolution_fingerprint)
            return destination
        except FrozenInstallError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise FrozenInstallPersistenceError("install resolution could not be persisted") from exc
        finally:
            if staged is not None:
                try:
                    staged.unlink()
                except OSError:
                    pass

    def load_resolution_manifest(self, fingerprint: str) -> FrozenInstallResolutionManifest:
        path = self.resolution_path(fingerprint)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FrozenInstallPersistenceError("install resolution could not be read") from exc
        try:
            record = FrozenInstallResolutionManifest.from_dict(raw)
        except FrozenResolutionError as exc:
            raise FrozenInstallPersistenceError("install resolution is invalid") from exc
        if record.resolution_fingerprint != fingerprint:
            raise FrozenInstallPersistenceError("install resolution identity changed")
        return record

    @staticmethod
    def _fsync_directory_path(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def locked(self) -> FrozenInstallLock:
        return FrozenInstallLock(self.lock_path)

    def inspect(self) -> Optional[FrozenInstallTransaction]:
        with self.locked():
            if not self.transaction_path.exists():
                return None
            try:
                data = json.loads(self.transaction_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FrozenInstallPersistenceError("could not read frozen transaction") from exc
            return FrozenInstallTransaction.from_dict(data)

    def create(self, transaction: FrozenInstallTransaction) -> FrozenInstallTransaction:
        with self.locked():
            if self.transaction_path.exists():
                raise FrozenInstallStateConflict("a frozen install transaction is already active")
            self._write_unlocked(transaction)
            return transaction

    def transition_expected(
        self,
        *,
        transaction_id: str,
        expected_phase: FrozenInstallPhase,
        new_phase: FrozenInstallPhase,
        status_code: str = "",
        status_message: str = "",
        originating_kodi_session_id: Optional[str] = None,
        restart_transaction_id: Optional[str] = None,
        private_overlay_id: Optional[str] = None,
        private_overlay_fingerprint: Optional[str] = None,
        private_overlay_required: Optional[bool] = None,
        resolution_records: Optional[Tuple[InstallResolutionRecord, ...]] = None,
        resolution_fingerprint_value: Optional[str] = None,
        resolved_software_fingerprint_value: Optional[str] = None,
        configuration_manifest_path: Optional[str] = None,
        lifecycle_stage: Optional[FrozenLifecycleStage] = None,
        activation_hold_ids: Optional[Tuple[str, ...]] = None,
        activation_hold_released: Optional[bool] = None,
        lifecycle_restart_count: Optional[int] = None,
    ) -> FrozenInstallTransaction:
        with self.locked():
            current = self._read_unlocked()
            if current is None or current.transaction_id != transaction_id:
                raise FrozenInstallStateConflict("frozen transaction identity changed")
            if current.phase is not expected_phase:
                raise FrozenInstallStateConflict("frozen transaction phase changed")
            updated = current.with_phase(
                new_phase,
                originating_kodi_session_id=originating_kodi_session_id,
                status_code=status_code,
                status_message=status_message,
                restart_transaction_id=restart_transaction_id,
                private_overlay_id=private_overlay_id,
                private_overlay_fingerprint=private_overlay_fingerprint,
                private_overlay_required=private_overlay_required,
                resolution_records=resolution_records,
                resolution_fingerprint_value=resolution_fingerprint_value,
                resolved_software_fingerprint_value=resolved_software_fingerprint_value,
                configuration_manifest_path=configuration_manifest_path,
                lifecycle_stage=lifecycle_stage,
                activation_hold_ids=activation_hold_ids,
                activation_hold_released=activation_hold_released,
                lifecycle_restart_count=lifecycle_restart_count,
            )
            self._write_unlocked(updated)
            return updated

    def clear_expected(
        self, *, transaction_id: str, expected_phase: FrozenInstallPhase
    ) -> bool:
        with self.locked():
            current = self._read_unlocked()
            if current is None:
                return False
            if current.transaction_id != transaction_id or current.phase is not expected_phase:
                raise FrozenInstallStateConflict("frozen transaction changed before clear")
            try:
                self.transaction_path.unlink()
                self._fsync_directory()
            except OSError as exc:
                raise FrozenInstallPersistenceError("could not clear frozen transaction") from exc
            return True

    def clear(self) -> bool:
        with self.locked():
            try:
                self.transaction_path.unlink()
                self._fsync_directory()
                return True
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise FrozenInstallPersistenceError("could not clear frozen transaction") from exc

    def _read_unlocked(self) -> Optional[FrozenInstallTransaction]:
        if not self.transaction_path.exists():
            return None
        try:
            return FrozenInstallTransaction.from_dict(
                json.loads(self.transaction_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrozenInstallPersistenceError("could not read frozen transaction") from exc

    def _write_unlocked(self, transaction: FrozenInstallTransaction) -> None:
        data = (json.dumps(transaction.to_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode()
        staged: Optional[Path] = None
        try:
            fd, name = tempfile.mkstemp(prefix=".frozen-install.", suffix=".tmp", dir=self.root)
            staged = Path(name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, self.transaction_path)
            staged = None
            self._fsync_directory()
            self._read_unlocked()
        except FrozenInstallError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise FrozenInstallPersistenceError("atomic frozen transaction write failed") from exc
        finally:
            if staged is not None:
                try:
                    staged.unlink()
                except OSError:
                    pass

    def _fsync_directory(self) -> None:
        try:
            fd = os.open(self.root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
        finally:
            os.close(fd)


def default_frozen_install_root() -> Path:
    try:
        import xbmcvfs
        return Path(xbmcvfs.translatePath("special://profile/addon_data/script.build.manager"))
    except (ImportError, AttributeError, RuntimeError):
        return Path("/tmp/script.build.manager-frozen-install")


def active_activation_hold_ids(
    store: Optional[FrozenInstallStore] = None,
) -> frozenset[str]:
    """Return held add-ons from the authoritative frozen transaction.

    A corrupt or unreadable transaction propagates as an error so callers can
    fail closed. NEEDS_ATTENTION does not release a hold; only the durable
    ``activation_hold_released`` transition does.
    """
    transaction = (store or FrozenInstallStore()).inspect()
    if transaction is None or transaction.activation_hold_released:
        return frozenset()
    return frozenset(transaction.activation_hold_ids)


@dataclass(frozen=True)
class FrozenManifestPlan:
    manifest: FrozenBuildManifest
    nodes: Mapping[str, AddonCaptureNode]
    install_order: Tuple[AddonCaptureNode, ...]


def validate_frozen_manifest(
    manifest: FrozenBuildManifest, store: ArtifactStore
) -> FrozenManifestPlan:
    """Strictly validate an exact-frozen manifest and deterministic order."""
    return _validate_frozen_manifest_core(manifest, store)


def _validate_frozen_manifest_core(
    manifest: FrozenBuildManifest,
    store: ArtifactStore,
    *,
    recoverable_gaps: frozenset = frozenset(),
    skipped: frozenset = frozenset(),
    repository_dependencies: Optional[Mapping[str, Tuple[str, ...]]] = None,
) -> FrozenManifestPlan:
    """Validate graph/artifacts, allowing only caller-proven install gaps."""
    if not isinstance(manifest, FrozenBuildManifest):
        raise FrozenInstallValidationError("frozen installation requires a typed manifest")
    if manifest.schema_version != 1:
        raise FrozenInstallValidationError("unsupported frozen manifest schema")
    if manifest.capture_status is not CaptureStatus.COMPLETE and not (
        manifest.capture_status is CaptureStatus.INCOMPLETE_ARTIFACT
        and recoverable_gaps
    ):
        raise FrozenInstallValidationError("incomplete frozen capture is not installable")
    nodes: Dict[str, AddonCaptureNode] = {}
    for node in manifest.addons:
        if node.addon_id in nodes:
            raise FrozenInstallValidationError("frozen manifest contains duplicate add-on IDs")
        nodes[node.addon_id] = node
        if node.system:
            if node.artifact is not None:
                raise FrozenInstallValidationError("system dependency has an artifact")
            continue
        if node.is_absent_optional_dependency:
            continue
        if (
            node.addon_id in recoverable_gaps
            and node.status in (
                CaptureStatus.COMPLETE,
                CaptureStatus.INCOMPLETE_ARTIFACT,
                CaptureStatus.INCOMPLETE_PROVENANCE,
                CaptureStatus.INVALID_PACKAGE,
            )
            and node.version
            and node.addon_type
        ):
            if node.artifact is None or (
                not store.artifact_path(node.artifact.sha256).exists()
                or not store.metadata_path(node.artifact.sha256).exists()
            ):
                continue
        if node.status is not CaptureStatus.COMPLETE or node.artifact is None:
            raise FrozenInstallValidationError(
                f"installed add-on artifact is incomplete for {node.addon_id} {node.version}"
            )
        try:
            metadata = store.get_metadata(node.artifact.sha256)
            data = store.read_bytes(node.artifact.sha256)
            if (
                metadata.sha256 != node.artifact.sha256
                or metadata.addon_id != node.addon_id
                or metadata.version != node.version
                or metadata.size != node.artifact.size
                or len(data) != node.artifact.size
                or hashlib.sha256(data).hexdigest() != node.artifact.sha256
            ):
                raise FrozenInstallValidationError(
                    f"artifact identity mismatch for {node.addon_id} {node.version}"
                )
            validate_addon_zip(
                data,
                expected_addon_id=node.addon_id,
                expected_version=node.version,
            )
        except (ArtifactValidationError, FrozenInstallError) as exc:
            if isinstance(exc, FrozenInstallError):
                raise
            raise FrozenInstallValidationError(
                f"artifact validation failed for {node.addon_id} {node.version}"
            ) from exc
        except Exception as exc:
            raise FrozenInstallValidationError(
                f"artifact unavailable for {node.addon_id} {node.version}"
            ) from exc

    install_nodes = {
        addon_id: node
        for addon_id, node in nodes.items()
        if not node.system and not node.is_absent_optional_dependency and addon_id not in skipped
    }
    edges: Dict[str, set] = {addon_id: set() for addon_id in install_nodes}
    reverse: Dict[str, set] = {addon_id: set() for addon_id in edges}
    for node in install_nodes.values():
        for edge in node.dependency_edges:
            if edge.addon_id not in nodes:
                if edge.optional:
                    continue
                raise FrozenInstallValidationError(
                    f"required dependency {edge.addon_id} is absent from frozen manifest"
                )
            if nodes[edge.addon_id].system:
                continue
            if nodes[edge.addon_id].is_absent_optional_dependency:
                if edge.optional:
                    continue
                raise FrozenInstallValidationError(
                    f"required dependency {edge.addon_id} is absent from frozen manifest"
                )
            if edge.addon_id in skipped:
                if edge.optional:
                    continue
                raise FrozenInstallValidationError(
                    f"required dependency {edge.addon_id} is intentionally skipped"
                )
            edges[node.addon_id].add(edge.addon_id)
            reverse[edge.addon_id].add(node.addon_id)

    for addon_id, repository_ids in (repository_dependencies or {}).items():
        if addon_id not in install_nodes:
            continue
        for repository_id in repository_ids:
            if repository_id not in install_nodes or repository_id in skipped:
                raise FrozenInstallValidationError(
                    f"trusted repository {repository_id} is not installable"
                )
            edges[addon_id].add(repository_id)
            reverse[repository_id].add(addon_id)

    ready = sorted(addon_id for addon_id, deps in edges.items() if not deps)
    order = []
    while ready:
        addon_id = ready.pop(0)
        order.append(nodes[addon_id])
        for dependent in sorted(reverse[addon_id]):
            edges[dependent].discard(addon_id)
            if not edges[dependent]:
                ready.append(dependent)
                ready.sort()
    if len(order) != len(edges):
        raise FrozenInstallValidationError("frozen dependency graph contains a cycle")
    return FrozenManifestPlan(manifest, nodes, tuple(order))


@dataclass(frozen=True)
class RecoverableFrozenInstallPlan:
    strict_plan: FrozenManifestPlan
    policies: Tuple[FrozenInstallPolicy, ...]
    summary: FrozenBuildRecoverabilitySummary
    install_plan_fingerprint: str
    actions: Tuple[FrozenPlanAction, ...]

    @property
    def manifest(self) -> FrozenBuildManifest:
        return self.strict_plan.manifest

    @property
    def nodes(self) -> Mapping[str, AddonCaptureNode]:
        return self.strict_plan.nodes

    @property
    def install_order(self) -> Tuple[AddonCaptureNode, ...]:
        return self.strict_plan.install_order


def validate_frozen_install_plan(
    manifest: FrozenBuildManifest,
    store: ArtifactStore,
    policies: Sequence[FrozenInstallPolicy] = (),
    *,
    skipped: Sequence[str] = (),
    extra_dependencies: Optional[Mapping[str, Tuple[str, ...]]] = None,
) -> RecoverableFrozenInstallPlan:
    """Validate exact artifacts plus explicit, safe install-time recoveries.

    ``validate_frozen_manifest`` remains exact-only. This planner accepts only
    missing artifacts that have an explicit repository/skip policy and a
    coherent dependency graph.
    """
    summary = summarize_frozen_recoverability(manifest, store, policies)
    rows = {row.addon_id: row for row in summary.addons}
    effective = {policy.addon_id: policy for policy in policies}
    for addon_id in skipped:
        row = rows.get(addon_id)
        policy = effective_policy(addon_id, effective)
        if (
            row is None
            or row.exact_artifact_available
            or not policy.skip_allowed
            or not row.skip_eligible
        ):
            raise FrozenInstallValidationError(
                f"skip resolution is not permitted for {addon_id}"
            )
    blocking = [
        row.addon_id for row in summary.addons
        if row.recoverability is Recoverability.BLOCKING_UNRECOVERABLE
    ]
    if blocking:
        raise FrozenInstallValidationError(
            "missing exact artifacts are blocking for " + ", ".join(sorted(blocking))
        )
    allowed_gaps = frozenset(
        row.addon_id for row in summary.addons if not row.exact_artifact_available
    )
    trusted_repo_dependencies: Dict[str, Tuple[str, ...]] = {}
    for addon_id in allowed_gaps:
        row = rows[addon_id]
        policy = effective_policy(addon_id, effective)
        if row.repository_known and policy.repository_fallback_allowed:
            trusted_repo_dependencies[addon_id] = (row.repository_id,)
    for addon_id, dependency_ids in (extra_dependencies or {}).items():
        trusted_repo_dependencies[addon_id] = tuple(sorted(set(
            trusted_repo_dependencies.get(addon_id, ()) + tuple(dependency_ids)
        )))
    strict_plan = _validate_frozen_manifest_core(
        manifest,
        store,
        recoverable_gaps=allowed_gaps,
        skipped=frozenset(skipped),
        repository_dependencies=trusted_repo_dependencies,
    )
    actions = []
    for node in strict_plan.install_order:
        row = rows[node.addon_id]
        if row.exact_artifact_available:
            kind = FrozenPlanActionKind.INSTALL_EXACT_ARTIFACT
        elif row.repository_known and row.fallback_eligible:
            kind = (
                FrozenPlanActionKind.PROMPT_REPOSITORY_OR_SKIP
                if row.skip_eligible else FrozenPlanActionKind.PROMPT_REPOSITORY_OR_CANCEL
            )
        elif row.skip_eligible:
            kind = FrozenPlanActionKind.PROMPT_SKIP_OR_CANCEL
        else:
            kind = FrozenPlanActionKind.BLOCKING_UNRECOVERABLE
        actions.append(FrozenPlanAction(kind, node.addon_id))
    for addon_id in sorted(set(skipped)):
        actions.append(FrozenPlanAction(FrozenPlanActionKind.SKIPPED, addon_id))
    normalized_policies = tuple(
        sorted(policies, key=lambda policy: policy.addon_id)
    )
    return RecoverableFrozenInstallPlan(
        strict_plan,
        normalized_policies,
        summary,
        install_plan_fingerprint(manifest, normalized_policies),
        tuple(actions),
    )


def _repository_package_required_dependencies(
    package: RepositoryPackage,
    manifest_plan: RecoverableFrozenInstallPlan,
    records: Mapping[str, InstallResolutionRecord],
    skipped: frozenset,
) -> Tuple[str, ...]:
    """Require repository-current ZIP dependencies to fit the captured plan."""
    try:
        with zipfile.ZipFile(io.BytesIO(package.zip_bytes), "r") as archive:
            xml_bytes = archive.read(f"{package.addon_id}/addon.xml")
        from resources.lib.dependencies import _is_system_dependency, _parse_requirements_strict, _version_satisfies
        requirements = _parse_requirements_strict(xml_bytes)
    except Exception as exc:
        raise FrozenInstallValidationError(
            "repository package dependency metadata is invalid"
        ) from exc
    dependencies = []
    for requirement in requirements:
        if _is_system_dependency(requirement.addon_id):
            continue
        dependency = manifest_plan.nodes.get(requirement.addon_id)
        if dependency is None or dependency.is_absent_optional_dependency:
            if requirement.optional:
                continue
            raise FrozenInstallValidationError(
                f"repository package requires uncaptured dependency {requirement.addon_id}"
            )
        if requirement.addon_id in skipped:
            if requirement.optional:
                continue
            raise FrozenInstallValidationError(
                f"repository package requires skipped dependency {requirement.addon_id}"
            )
        record = records.get(requirement.addon_id)
        version = (
            record.resolved_version if record and record.resolved_version
            else dependency.version
        )
        if requirement.min_version and not _version_satisfies(version, requirement.min_version):
            if requirement.optional:
                continue
            raise FrozenInstallValidationError(
                f"repository package requires a newer captured dependency {requirement.addon_id}"
            )
        if not requirement.optional:
            dependencies.append(requirement.addon_id)
    return tuple(sorted(set(dependencies)))


@dataclass(frozen=True)
class FrozenInstalledAddon:
    addon_id: str
    version: str
    enabled: bool
    broken: bool = False


class FrozenArtifactBackend:
    """Exact-artifact install and state interface."""

    def get_addon_details(self, addon_id: str) -> Optional[FrozenInstalledAddon]:
        raise NotImplementedError

    def install_exact(self, addon_id: str, version: str, zip_bytes: bytes) -> FrozenInstalledAddon:
        raise NotImplementedError

    def resolve_repository_current(
        self, addon_id: str, repository_id: str
    ) -> RepositoryPackage:
        raise NotImplementedError

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> FrozenInstalledAddon:
        raise NotImplementedError


class InMemoryFrozenArtifactBackend(FrozenArtifactBackend):
    """Deterministic backend for transaction tests and fixture design."""

    def __init__(
        self,
        installed: Optional[Mapping[str, FrozenInstalledAddon]] = None,
        repository_packages: Optional[Mapping[Tuple[str, str], Tuple[str, bytes]]] = None,
    ):
        self.installed = dict(installed or {})
        self.repository_packages = dict(repository_packages or {})
        self.install_calls = []
        self.enable_calls = []
        self.artifacts = {}
        self.repository_calls = []

    def get_addon_details(self, addon_id: str) -> Optional[FrozenInstalledAddon]:
        return self.installed.get(addon_id)

    def install_exact(self, addon_id: str, version: str, zip_bytes: bytes) -> FrozenInstalledAddon:
        current = self.installed.get(addon_id)
        if current is not None:
            if current.version != version:
                raise FrozenInstallError(
                    f"exact replacement/downgrade is unsupported for {addon_id}"
                )
            if current.broken:
                raise FrozenInstallError(f"existing exact add-on is broken: {addon_id}")
            return current
        self.install_calls.append(addon_id)
        self.artifacts[addon_id] = bytes(zip_bytes)
        result = FrozenInstalledAddon(addon_id, version, False, False)
        self.installed[addon_id] = result
        return result

    def resolve_repository_current(
        self, addon_id: str, repository_id: str
    ) -> RepositoryPackage:
        self.repository_calls.append((addon_id, repository_id))
        package = self.repository_packages.get((repository_id, addon_id))
        if package is None:
            raise FrozenInstallError("captured repository did not provide the requested add-on")
        version, zip_bytes = package
        return RepositoryPackage(addon_id, repository_id, version, bytes(zip_bytes))

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> FrozenInstalledAddon:
        current = self.installed.get(addon_id)
        if current is None:
            raise FrozenInstallError(f"cannot set state for missing add-on {addon_id}")
        self.enable_calls.append((addon_id, enabled))
        result = FrozenInstalledAddon(addon_id, current.version, enabled, current.broken)
        self.installed[addon_id] = result
        return result


class KodiRuntimeFrozenArtifactBackend(FrozenArtifactBackend):
    """Kodi runtime adapter using the established validated staged install path."""

    _WAIT_TIMEOUT = 60.0
    _WAIT_INTERVAL = 0.5

    def __init__(self):
        self.install_order = []

    def _xbmc(self):
        try:
            import xbmc
            return xbmc
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise FrozenInstallError("Kodi runtime module is unavailable") from exc

    def _addons_dir(self) -> Path:
        try:
            import xbmcvfs
            return Path(xbmcvfs.translatePath("special://home/addons"))
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise FrozenInstallError("Kodi VFS module is unavailable") from exc

    def _rpc(self, method: str, params: dict) -> dict:
        response = json.loads(self._xbmc().executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params, "id": 1,
        })))
        if not isinstance(response, dict):
            raise FrozenInstallError(f"{method} returned malformed JSON-RPC data")
        return response

    def get_addon_details(self, addon_id: str) -> Optional[FrozenInstalledAddon]:
        response = self._rpc(
            "Addons.GetAddonDetails",
            {"addonid": addon_id, "properties": ["enabled", "version", "broken"]},
        )
        error = response.get("error")
        if isinstance(error, dict) and error.get("code") == -32602:
            return None
        if error is not None:
            raise FrozenInstallError("Kodi refused add-on inspection")
        addon = response.get("result", {}).get("addon", {})
        if not isinstance(addon, dict) or addon.get("addonid") != addon_id:
            return None
        if not isinstance(addon.get("enabled"), bool) or not isinstance(addon.get("version"), str):
            raise FrozenInstallError("Kodi returned malformed add-on state")
        return FrozenInstalledAddon(
            addon_id=addon_id,
            version=addon["version"],
            enabled=addon["enabled"],
            broken=addon.get("broken") is True,
        )

    def install_exact(self, addon_id: str, version: str, zip_bytes: bytes) -> FrozenInstalledAddon:
        self.install_order.append(addon_id)
        current = self.get_addon_details(addon_id)
        if current is not None:
            if current.version != version:
                raise FrozenInstallError(
                    f"exact replacement/downgrade is unsupported for {addon_id}"
                )
            if current.broken:
                raise FrozenInstallError(f"existing exact add-on is broken: {addon_id}")
            return current
        addons_dir = self._addons_dir()
        target = addons_dir / addon_id
        if target.exists():
            raise FrozenInstallError(
                f"unregistered add-on directory already exists for {addon_id}; refusing overwrite"
            )
        staging = Path(tempfile.mkdtemp(prefix=".bm022-", dir=addons_dir))
        try:
            _extract_zip_to_directory(zip_bytes, addon_id, staging)
            if not any(path.is_file() for path in staging.rglob("*")):
                raise FrozenInstallError(f"exact artifact extracted no usable files for {addon_id}")
            os.rename(staging, target)
            staging = None  # type: ignore[assignment]
            self._xbmc().executebuiltin("UpdateLocalAddons")
        except FrozenInstallError:
            raise
        except Exception as exc:
            raise FrozenInstallError(f"exact artifact installation failed for {addon_id}") from exc
        finally:
            if staging is not None and staging.exists():
                import shutil
                shutil.rmtree(staging, ignore_errors=True)
        return self._wait_for_exact(addon_id, version)

    def resolve_repository_current(
        self, addon_id: str, repository_id: str
    ) -> RepositoryPackage:
        """Use BM-011's constrained fresh-index/package validation path."""
        try:
            return KodiRuntimeAddonBackend().fetch_current_from_repository(
                addon_id, repository_id
            )
        except Exception as exc:
            raise FrozenInstallError(
                f"captured repository could not resolve {addon_id}"
            ) from exc

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> FrozenInstalledAddon:
        if enabled:
            try:
                from resources.lib.activation import reject_held_activation
                reject_held_activation(addon_id)
            except Exception as exc:
                raise FrozenInstallError(
                    "add-on activation is held or activation-hold state is unavailable"
                ) from exc
        response = self._rpc(
            "Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": bool(enabled)}
        )
        result = response.get("result")
        if (
            response.get("error") is not None
            or result is False
            or (isinstance(result, dict) and result.get("success") is False)
        ):
            raise FrozenInstallError(f"Kodi refused enabled-state change for {addon_id}")
        current = self._wait_for_details(addon_id)
        if current.enabled is not enabled:
            raise FrozenInstallError(f"enabled-state verification failed for {addon_id}")
        return current

    def _wait_for_details(self, addon_id: str) -> FrozenInstalledAddon:
        deadline = time.monotonic() + self._WAIT_TIMEOUT
        while time.monotonic() < deadline:
            current = self.get_addon_details(addon_id)
            if current is not None:
                return current
            time.sleep(self._WAIT_INTERVAL)
        raise FrozenInstallError(f"Kodi did not register exact add-on {addon_id}")

    def _wait_for_exact(self, addon_id: str, version: str) -> FrozenInstalledAddon:
        current = self._wait_for_details(addon_id)
        if current.version != version or current.broken:
            raise FrozenInstallError(f"Kodi registered the wrong or broken version for {addon_id}")
        return current


@dataclass(frozen=True)
class FrozenInstallResult:
    outcome: str
    transaction: Optional[FrozenInstallTransaction] = None
    message: str = ""
    code: str = ""
    recoverability: Optional[FrozenBuildRecoverabilitySummary] = None
    resolution_manifest: Optional[FrozenInstallResolutionManifest] = None

    @property
    def succeeded(self) -> bool:
        return self.outcome == "complete"

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "code": self.code,
            "message": self.message,
            "recoverability": self.recoverability.to_dict() if self.recoverability else None,
            "resolution": self.resolution_manifest.to_dict() if self.resolution_manifest else None,
        }


def _kodi_resolution_choice(prompt: ResolutionPrompt) -> Optional[ResolutionChoice]:
    """Show safe metadata and clear actions; return None when no UI exists."""
    try:
        import xbmcgui
    except (ImportError, AttributeError, RuntimeError):
        return None
    heading = (
        f"{prompt.addon_id}\n"
        f"Captured version: {prompt.captured_version}\n"
        "Exact captured package: unavailable\n"
    )
    if prompt.repository_known:
        heading += (
            "Build Manager can install the current version available from:\n"
            f"{prompt.repository_id}\n"
            "The installed version may differ from the captured source."
        )
        choices = [ResolutionChoice.INSTALL_CURRENT]
        labels = ["Install Current Version"]
        if prompt.skip_allowed:
            choices.append(ResolutionChoice.SKIP)
            labels.append("Skip")
        choices.append(ResolutionChoice.CANCEL)
        labels.append("Cancel Build")
    else:
        heading += (
            "Build Manager does not know a trusted repository from which this "
            "add-on can be installed automatically. You may need to install it "
            "manually later."
        )
        if not prompt.skip_allowed:
            return None
        choices = [ResolutionChoice.SKIP, ResolutionChoice.CANCEL]
        labels = ["Skip", "Cancel Build"]
    selected = xbmcgui.Dialog().select(heading, labels)
    if not isinstance(selected, int) or selected < 0 or selected >= len(choices):
        return ResolutionChoice.CANCEL
    return choices[selected]


def _default_manifest_loader(path: str) -> FrozenBuildManifest:
    raw_path = path
    try:
        import xbmcvfs
        if raw_path.startswith("special://"):
            raw_path = xbmcvfs.translatePath(raw_path)
    except (ImportError, AttributeError, RuntimeError):
        pass
    try:
        return FrozenBuildManifest.from_json(Path(raw_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, CaptureError) as exc:
        raise FrozenInstallValidationError("could not load frozen manifest") from exc


def _configuration_failure_parts(owner_result: object) -> list[str]:
    """Return only safe, typed diagnostics for a failed CONFIGURE action."""
    from resources.lib.config import ConfigApplyResult
    from resources.lib.private_overlay import (
        ConfigurationApplyBundle,
        PrivateOverlayApplyResult,
    )

    def token(value: object, pattern: str) -> str:
        value = getattr(value, "value", value)
        if isinstance(value, str) and re.fullmatch(pattern, value):
            return value
        return ""

    def public_parts(result: ConfigApplyResult) -> list[str]:
        failed = result.failed
        if not failed:
            return []
        parts = [
            "configuration_scope=public",
            "cause=PUBLIC_CONFIGURATION_OPERATION_FAILED",
        ]
        owner = token(getattr(failed[0], "addon_id", ""), _ADDON_ID.pattern)
        if owner:
            parts.append(f"owner={owner}")
        return parts

    def private_parts(result: PrivateOverlayApplyResult) -> list[str]:
        if result.succeeded:
            return []
        failed_resources = tuple(
            item for item in result.resource_results
            if not getattr(item, "succeeded", False)
        )
        failed_settings = tuple(
            item for item in result.results
            if token(getattr(item, "status", ""), r"[a-z_]{1,40}") == "failed"
            or getattr(item, "verified", True) is False
        )
        if failed_resources:
            cause = "PRIVATE_RESOURCE_APPLICATION_FAILED"
        elif failed_settings:
            cause = "PRIVATE_SETTING_APPLICATION_FAILED"
        else:
            cause = "PRIVATE_OVERLAY_APPLICATION_FAILED"
        parts = ["configuration_scope=private", f"cause={cause}"]
        if failed_resources:
            resource = token(
                getattr(failed_resources[0], "resource_id", ""),
                r"[a-z0-9][a-z0-9._-]{0,127}",
            )
            owner = token(
                getattr(failed_resources[0], "owner_addon_id", ""),
                _ADDON_ID.pattern,
            )
            if owner:
                parts.append(f"owner={owner}")
            if resource:
                parts.append(f"resource={resource}")
        elif failed_settings:
            owner = token(
                getattr(failed_settings[0], "addon_id", ""),
                _ADDON_ID.pattern,
            )
            if owner:
                parts.append(f"owner={owner}")
        return parts

    if isinstance(owner_result, ActionFailureDiagnostic):
        scope = owner_result.configuration_scope
        if not scope and (
            owner_result.owner_addon_id
            or owner_result.resource_id
            or owner_result.cause_code
            or owner_result.code.startswith(("PRIVATE_", "STRUCTURED_RESOURCE_"))
        ):
            scope = "private"
        return [f"configuration_scope={scope}"] if scope in {"public", "private"} else []

    # The dispatcher returns a direct ConfigApplyResult when public apply fails;
    # private apply is never reached in that case.
    if isinstance(owner_result, ConfigApplyResult):
        return public_parts(owner_result)

    if isinstance(owner_result, ConfigurationApplyBundle):
        public_result = owner_result.public_result
        if isinstance(public_result, ConfigApplyResult) and not public_result.all_applied:
            return public_parts(public_result)
        private_result = owner_result.private_result
        if isinstance(private_result, PrivateOverlayApplyResult):
            return private_parts(private_result)
        return []

    if isinstance(owner_result, PrivateOverlayApplyResult):
        return private_parts(owner_result)

    return []


def _overlay_failure_transaction_updates(overlay: object) -> dict:
    """Return transaction fields only for validated, present overlay metadata."""
    from resources.lib.private_overlay import PrivateOverlayMetadata

    if not isinstance(overlay, PrivateOverlayMetadata) or not overlay.present:
        return {}
    return {
        "private_overlay_id": overlay.overlay_id,
        "private_overlay_fingerprint": overlay.fingerprint,
        "private_overlay_required": overlay.required,
    }


class FrozenInstallCoordinator:
    """Coordinate exact software, existing configuration, restart, and release."""

    def __init__(
        self,
        *,
        store: FrozenInstallStore,
        artifact_store: ArtifactStore,
        policy_backend: UpdatePolicyBackend,
        installer: FrozenArtifactBackend,
        manifest_loader: Callable[[str], FrozenBuildManifest] = _default_manifest_loader,
        session_id_provider: Optional[Callable[[], str]] = None,
        configuration_runner: Optional[Callable[[ReconcileRequest], object]] = None,
        final_validator: Optional[Callable[[FrozenManifestPlan], bool]] = None,
        resolution_decider: Optional[Callable[[ResolutionPrompt], ResolutionChoice]] = None,
        private_overlay_metadata_provider: Optional[Callable[[object, str], tuple]] = None,
        registry_backend=None,
    ):
        self.store = store
        self.artifact_store = artifact_store
        self.policy_backend = policy_backend
        self.installer = installer
        self.manifest_loader = manifest_loader
        self.session_id_provider = session_id_provider or _default_session_id
        self.configuration_runner = configuration_runner
        self.final_validator = final_validator
        self.resolution_decider = resolution_decider
        self.private_overlay_metadata_provider = private_overlay_metadata_provider
        self.registry_backend = registry_backend

    @staticmethod
    def _configuration_profile(configuration_manifest_path: str, device_profile_id: str):
        if not configuration_manifest_path:
            return None
        from resources.lib.manifest import load_manifest_file
        from resources.lib.resolver import resolve_manifest
        manifest = load_manifest_file(configuration_manifest_path)
        return resolve_manifest(manifest, device_profile_id)

    def _check_private_ownership_compatibility(self, desired, records):
        if desired is None:
            return
        config = getattr(desired, "config", None)
        if config is None:
            return
        changes = {
            record.addon_id: (
                None if record.resolution is InstallResolution.SKIPPED
                else record.resolved_version or record.captured_version
            )
            for record in records
            if record.resolution is InstallResolution.SKIPPED
            or record.resolution is InstallResolution.REPOSITORY_CURRENT
            or record.resolved_version != record.captured_version
        }
        if not changes:
            return
        from resources.lib.private_overlay import validate_private_overlay_resolution_compatibility
        validate_private_overlay_resolution_compatibility(
            changes,
            config.private_settings,
            config.structured_private_resources,
        )

    def _private_overlay_metadata(self, desired_profile, source_fingerprint):
        reference = getattr(desired_profile, "private_overlay", None)
        if reference is None:
            return "", "", False
        if self.private_overlay_metadata_provider is not None:
            return self.private_overlay_metadata_provider(
                desired_profile, source_fingerprint
            )
        from resources.lib.private_overlay import (
            PrivateOverlayMissingError,
            PrivateOverlayStore,
            validate_private_overlay,
        )
        try:
            overlay = PrivateOverlayStore().load(reference.overlay_id)
        except PrivateOverlayMissingError:
            if reference.required:
                raise FrozenInstallValidationError(
                    "required private overlay is absent before lifecycle staging"
                )
            return "", "", False
        config = getattr(desired_profile, "config", None)
        validated = validate_private_overlay(
            overlay,
            getattr(config, "private_settings", ()) if config is not None else (),
            expected_build_id=(
                getattr(getattr(desired_profile, "build", None), "id", "")
                if not source_fingerprint else ""
            ),
            expected_source_software_fingerprint=source_fingerprint,
            expected_overlay_id=reference.overlay_id,
            resource_declarations=(
                getattr(config, "structured_private_resources", ())
                if config is not None else ()
            ),
        )
        return validated.overlay_id, validated.fingerprint, reference.required

    def _persist_resolutions(self, transaction, manifest, records):
        records = tuple(sorted(records, key=lambda record: record.addon_id))
        resolved_fingerprint = ""
        if all(record.state in (ResolutionState.INSTALLED, ResolutionState.SKIPPED) for record in records):
            resolved_fingerprint = resolved_software_fingerprint(manifest, records)
        return self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=transaction.phase,
            new_phase=transaction.phase,
            resolution_records=records,
            resolution_fingerprint_value=resolution_fingerprint(records),
            resolved_software_fingerprint_value=resolved_fingerprint,
        )

    def _await_quiescence_restart(self, transaction, session_id, recoverability, message):
        if transaction.lifecycle_restart_count >= 3:
            return self._attention(
                transaction,
                "LIFECYCLE_RESTART_LIMIT",
                "activation lifecycle exceeded its bounded restart progression",
                recoverability=recoverability,
            )
        updated = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=transaction.phase,
            new_phase=FrozenInstallPhase.AWAITING_RESTART,
            originating_kodi_session_id=session_id,
            lifecycle_stage=FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            lifecycle_restart_count=transaction.lifecycle_restart_count + 1,
            status_code="QUIESCENCE_RESTART_REQUIRED",
            status_message=message,
        )
        return FrozenInstallResult(
            "awaiting_restart",
            transaction=updated,
            code="QUIESCENCE_RESTART_REQUIRED",
            message=message,
            recoverability=recoverability,
        )

    @staticmethod
    def _make_resolution_manifest(manifest, transaction, records):
        return FrozenInstallResolutionManifest(
            build_id=manifest.build_id,
            source_software_fingerprint=manifest.fingerprint(),
            install_plan_fingerprint=(
                transaction.install_plan_fingerprint
                or install_plan_fingerprint(manifest, transaction.policies)
            ),
            resulting_software_fingerprint=resolved_software_fingerprint(manifest, records),
            records=tuple(sorted(records, key=lambda record: record.addon_id)),
        )

    @staticmethod
    def _repository_prerequisites(plan, repository_ids, records, recoverability_rows):
        required = set()
        pending = list(repository_ids)
        while pending:
            addon_id = pending.pop()
            if addon_id in required:
                continue
            node = plan.nodes.get(addon_id)
            if node is None or node.system or node.is_absent_optional_dependency:
                raise FrozenInstallValidationError("captured repository prerequisite is unavailable")
            record = records.get(addon_id)
            row = recoverability_rows.get(addon_id)
            if (
                record is None
                or record.resolution is not InstallResolution.EXACT
                or row is None
                or not row.exact_artifact_available
            ):
                raise FrozenInstallValidationError(
                    "captured repository and its prerequisites must have exact artifacts"
                )
            required.add(addon_id)
            for edge in node.dependency_edges:
                if not edge.optional and edge.addon_id in plan.nodes and not plan.nodes[edge.addon_id].system:
                    pending.append(edge.addon_id)
        return required

    @staticmethod
    def _activation_hold_ids(plan, desired_profile) -> Tuple[str, ...]:
        """Hold each pre-activation resource owner and its managed dependents."""
        config = getattr(desired_profile, "config", None)
        declarations = tuple(
            item for item in (
                getattr(config, "structured_private_resources", ())
                if config is not None else ()
            )
            if item.configure_before_activation
        )
        if not declarations:
            return ()
        install_ids = {node.addon_id for node in plan.install_order}
        held = {item.owner_addon_id for item in declarations}
        if not held.issubset(install_ids):
            raise FrozenInstallValidationError(
                "pre-activation resource owner is not in the frozen software graph"
            )
        changed = True
        while changed:
            changed = False
            for node in plan.install_order:
                if node.addon_id in held:
                    continue
                if any(
                    edge.addon_id in held
                    for edge in node.dependency_edges
                ):
                    held.add(node.addon_id)
                    changed = True
        return tuple(sorted(held))

    @staticmethod
    def _registry_readiness_ids(desired_profile) -> Tuple[str, ...]:
        """Return resource owners that must be registered before initialization."""
        config = getattr(desired_profile, "config", None)
        return tuple(sorted({
            item.owner_addon_id
            for item in (
                getattr(config, "structured_private_resources", ())
                if config is not None else ()
            )
            if item.configure_before_activation
        }))

    def install(
        self,
        manifest: FrozenBuildManifest,
        *,
        manifest_path: str,
        device_profile_id: str,
        configuration_manifest_path: str = "",
        install_policies: Optional[Sequence[FrozenInstallPolicy]] = None,
        interactive: bool = True,
    ) -> FrozenInstallResult:
        try:
            desired_profile = self._configuration_profile(
                configuration_manifest_path, device_profile_id
            )
            policies = tuple(
                install_policies if install_policies is not None
                else getattr(desired_profile, "frozen_install_policies", ())
            )
            plan = validate_frozen_install_plan(
                manifest, self.artifact_store, policies
            )
            hold_ids = self._activation_hold_ids(plan, desired_profile)
            if hold_ids and (not configuration_manifest_path or self.configuration_runner is None):
                raise FrozenInstallValidationError(
                    "pre-activation resources require a durable configuration runner"
                )
            session_id = _valid_uuid(self.session_id_provider(), "current_session_id")
        except (FrozenInstallError, FrozenResolutionError, CaptureError, ValueError) as exc:
            return FrozenInstallResult(
                "failed",
                code=getattr(exc, "code", "FROZEN_MANIFEST_INVALID"),
                message="frozen install plan validation failed",
            )
        active = self._safe_inspect()
        active_resume = False
        if active is not None and active.lifecycle_stage is FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART:
            skipped_active = tuple(
                record.addon_id for record in active.resolution_records
                if record.resolution is InstallResolution.SKIPPED
            )
            if (
                active.manifest_fingerprint == manifest.fingerprint()
                and active.install_plan_fingerprint == install_plan_fingerprint(manifest, policies)
                and active.configuration_manifest_path == (configuration_manifest_path or manifest_path)
            ):
                if session_id == active.originating_kodi_session_id:
                    return FrozenInstallResult(
                        "awaiting_restart", transaction=active, code="SAME_SESSION",
                        message="Red Light remains held; restart Kodi completely to prove quiescence",
                        recoverability=active and plan.summary,
                    )
                active_resume = True
                try:
                    plan = validate_frozen_install_plan(
                        manifest, self.artifact_store, policies, skipped=skipped_active
                    )
                    hold_ids = self._activation_hold_ids(plan, desired_profile)
                    if hold_ids != active.activation_hold_ids:
                        raise FrozenInstallValidationError(
                            "activation hold graph changed across the restart boundary"
                        )
                    if any(
                        (current := self.installer.get_addon_details(addon_id)) is None
                        or current.enabled
                        for addon_id in active.activation_hold_ids
                    ):
                        raise FrozenInstallValidationError(
                            "an activation-held add-on became enabled across restart"
                        )
                except Exception:
                    return self._attention(
                        active, "QUIESCENCE_VALIDATION_FAILED",
                        "held add-on state could not be verified after restart",
                        recoverability=plan.summary,
                    )
            else:
                return FrozenInstallResult(
                    "failed", transaction=active, code="ACTIVE_TRANSACTION_CONFLICT",
                    message="another frozen lifecycle transaction is active",
                )
        if active is not None:
            if active_resume:
                pass
            else:
                if (
                    active.manifest_fingerprint == plan.manifest.fingerprint()
                    and active.install_plan_fingerprint == plan.install_plan_fingerprint
                ):
                    return FrozenInstallResult(
                        "needs_attention" if active.phase is FrozenInstallPhase.NEEDS_ATTENTION else "active",
                        transaction=active,
                        code=active.status_code or "FROZEN_INSTALL_ACTIVE",
                        message="an equivalent frozen install transaction already has recorded resolutions",
                        recoverability=plan.summary,
                    )
                return FrozenInstallResult("failed", transaction=active, code="ACTIVE_TRANSACTION_CONFLICT", message="another frozen install transaction is active")

        records: Dict[str, InstallResolutionRecord] = (
            {record.addon_id: record for record in active.resolution_records}
            if active_resume else {}
        )
        rows = {row.addon_id: row for row in plan.summary.addons}
        effective = {policy.addon_id: policy for policy in policies}
        for node in plan.install_order:
            if active_resume:
                break
            row = rows[node.addon_id]
            if row.exact_artifact_available:
                records[node.addon_id] = default_exact_record(node)
                continue
            policy = effective_policy(node.addon_id, effective)
            prompt = ResolutionPrompt(
                addon_id=node.addon_id,
                captured_version=node.version,
                repository_id=row.repository_id if row.fallback_eligible else "",
                skip_allowed=row.skip_eligible,
            )
            if not interactive:
                return FrozenInstallResult(
                    "user_resolution_required",
                    code="USER_RESOLUTION_REQUIRED",
                    message="interactive install resolution is required before this build can continue",
                    recoverability=plan.summary,
                )
            try:
                choice = (
                    self.resolution_decider(prompt)
                    if self.resolution_decider is not None
                    else _kodi_resolution_choice(prompt)
                )
                if choice is not None and not isinstance(choice, ResolutionChoice):
                    choice = ResolutionChoice(choice)
            except Exception:
                choice = None
            if choice is None:
                return FrozenInstallResult(
                    "user_resolution_required",
                    code="USER_RESOLUTION_REQUIRED",
                    message="interactive install resolution is required before this build can continue",
                    recoverability=plan.summary,
                )
            if choice is ResolutionChoice.CANCEL:
                return FrozenInstallResult(
                    "cancelled",
                    code="BUILD_CANCELLED",
                    message="build cancelled before frozen installation began",
                    recoverability=plan.summary,
                )
            if choice is ResolutionChoice.INSTALL_CURRENT:
                if not policy.repository_fallback_allowed or not row.repository_known:
                    return FrozenInstallResult(
                        "failed", code="FROZEN_RESOLUTION_NOT_PERMITTED",
                        message="repository resolution is not permitted for this add-on",
                        recoverability=plan.summary,
                    )
                records[node.addon_id] = InstallResolutionRecord(
                    addon_id=node.addon_id,
                    captured_version=node.version,
                    resolution=InstallResolution.REPOSITORY_CURRENT,
                    state=ResolutionState.SELECTED,
                    desired_enabled=node.desired_enabled,
                    repository_id=row.repository_id,
                )
            elif choice is ResolutionChoice.SKIP:
                if not policy.skip_allowed or not row.skip_eligible:
                    return FrozenInstallResult(
                        "failed", code="FROZEN_SKIP_NOT_PERMITTED",
                        message="skip is not permitted for this add-on or its required dependents",
                        recoverability=plan.summary,
                    )
                if self.installer.get_addon_details(node.addon_id) is not None:
                    return FrozenInstallResult(
                        "failed", code="SKIP_TARGET_ALREADY_INSTALLED",
                        message="the target already has this add-on and Build Manager cannot remove it safely",
                        recoverability=plan.summary,
                    )
                records[node.addon_id] = InstallResolutionRecord(
                    addon_id=node.addon_id,
                    captured_version=node.version,
                    resolution=InstallResolution.SKIPPED,
                    state=ResolutionState.SKIPPED,
                    desired_enabled=node.desired_enabled,
                )
            else:
                return FrozenInstallResult(
                    "failed", code="FROZEN_RESOLUTION_INVALID",
                    message="install resolution choice is unsupported",
                    recoverability=plan.summary,
                )

        skipped = frozenset(
            addon_id for addon_id, record in records.items()
            if record.resolution is InstallResolution.SKIPPED
        )
        try:
            resolved_plan = validate_frozen_install_plan(
                manifest, self.artifact_store, policies, skipped=tuple(skipped)
            )
            hold_ids = self._activation_hold_ids(resolved_plan, desired_profile)
            if hold_ids and any(
                record.resolution is InstallResolution.REPOSITORY_CURRENT
                for record in records.values()
            ):
                raise FrozenInstallValidationError(
                    "pre-activation lifecycle requires exact dependency metadata"
                )
            self._check_private_ownership_compatibility(desired_profile, tuple(records.values()))
            if hold_ids:
                private_overlay_id, private_overlay_fingerprint, private_overlay_required = (
                    self._private_overlay_metadata(
                        desired_profile, manifest.fingerprint()
                    )
                )
                if not private_overlay_id or not private_overlay_fingerprint:
                    raise FrozenInstallValidationError(
                        "pre-activation resources require a persisted private overlay identity"
                    )
                if active_resume and (
                    private_overlay_id != active.private_overlay_id
                    or private_overlay_fingerprint != active.private_overlay_fingerprint
                    or private_overlay_required != active.private_overlay_required
                ):
                    raise FrozenInstallValidationError(
                        "private overlay identity changed across the quiescence restart"
                    )
            else:
                private_overlay_id, private_overlay_fingerprint, private_overlay_required = "", "", False
        except Exception as exc:
            return FrozenInstallResult(
                "failed", code=getattr(exc, "code", "FROZEN_RESOLUTION_INVALID"),
                message="selected install resolutions are incompatible with the build graph or owned configuration",
                recoverability=plan.summary,
            )

        try:
            if active_resume:
                transaction = active
                original = transaction.original_update_policy
            else:
                original = AddonUpdatePolicy(self.policy_backend.get_policy())
                transaction = FrozenInstallTransaction(
                    transaction_id=str(uuid.uuid4()),
                    build_id=manifest.build_id,
                    manifest_path=manifest_path,
                    device_profile_id=device_profile_id,
                    manifest_fingerprint=manifest.fingerprint(),
                    phase=FrozenInstallPhase.PREPARING,
                    originating_kodi_session_id=session_id,
                    original_update_policy=original,
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                    install_plan_fingerprint=plan.install_plan_fingerprint,
                    policies=tuple(sorted(policies, key=lambda item: item.addon_id)),
                    resolution_records=tuple(sorted(records.values(), key=lambda item: item.addon_id)),
                    resolution_fingerprint=resolution_fingerprint(tuple(records.values())),
                    configuration_manifest_path=configuration_manifest_path or manifest_path,
                    private_overlay_id=private_overlay_id,
                    private_overlay_fingerprint=private_overlay_fingerprint,
                    private_overlay_required=private_overlay_required,
                    lifecycle_stage=(
                        FrozenLifecycleStage.INSTALLING_SOFTWARE
                        if hold_ids else FrozenLifecycleStage.NONE
                    ),
                    activation_hold_ids=hold_ids,
                    activation_hold_released=not bool(hold_ids),
                )
                self.store.create(transaction)
        except Exception as exc:
            return FrozenInstallResult(
                "failed",
                code=getattr(exc, "code", "FROZEN_TRANSACTION_CREATE_FAILED"),
                message=_bounded(
                    "frozen install transaction could not be created "
                    f"({type(exc).__name__})",
                    _MAX_MESSAGE,
                    "transaction creation failed",
                ),
            )
        resolution_manifest = None
        guard = AddonUpdateGuard(self.policy_backend)
        try:
            if active_resume:
                guard.reassert_required()
                transaction = self.store.transition_expected(
                    transaction_id=transaction.transaction_id,
                    expected_phase=FrozenInstallPhase.AWAITING_RESTART,
                    new_phase=FrozenInstallPhase.RESUMING,
                    originating_kodi_session_id=session_id,
                    lifecycle_stage=FrozenLifecycleStage.INSTALLING_SOFTWARE,
                )
                transaction = self.store.transition_expected(
                    transaction_id=transaction.transaction_id,
                    expected_phase=FrozenInstallPhase.RESUMING,
                    new_phase=FrozenInstallPhase.INSTALLING_SOFTWARE,
                )
            else:
                guard.engage_with_original(original)
                transaction = self.store.transition_expected(
                    transaction_id=transaction.transaction_id,
                    expected_phase=FrozenInstallPhase.PREPARING,
                    new_phase=FrozenInstallPhase.INSTALLING_SOFTWARE,
                    lifecycle_stage=(
                        FrozenLifecycleStage.INSTALLING_SOFTWARE
                        if hold_ids else FrozenLifecycleStage.NONE
                    ),
                )

                existing_held = tuple(
                    addon_id for addon_id in hold_ids
                    if self.installer.get_addon_details(addon_id) is not None
                )
                if existing_held:
                    for addon_id in existing_held:
                        current = self.installer.get_addon_details(addon_id)
                        if current is not None and current.enabled:
                            self.installer.set_addon_enabled(addon_id, False)
                        current = self.installer.get_addon_details(addon_id)
                        if current is None or current.enabled:
                            raise FrozenInstallValidationError(
                                "pre-existing activation-held add-on could not be disabled"
                            )
                    return self._await_quiescence_restart(
                        transaction, session_id, plan.summary,
                        "pre-existing resource owner was disabled; restart Kodi before configuration",
                    )

            # Install only the exact repository and its exact required
            # prerequisites before querying a current package from that repo.
            repository_ids = {
                record.repository_id for record in records.values()
                if record.resolution is InstallResolution.REPOSITORY_CURRENT
            }
            prelude_ids = self._repository_prerequisites(
                plan.strict_plan, repository_ids, records, rows
            ) if repository_ids else set()
            installed_ids = set()
            record_map = dict(records)
            for node in plan.install_order:
                current = self.installer.get_addon_details(node.addon_id)
                target_version = record_map[node.addon_id].resolved_version or node.version
                if current is not None and current.version == target_version and not current.broken:
                    if node.addon_id in hold_ids and current.enabled:
                        self.installer.set_addon_enabled(node.addon_id, False)
                        current = self.installer.get_addon_details(node.addon_id)
                        if current is None or current.enabled:
                            raise FrozenInstallValidationError(
                                "existing activation-held add-on could not be disabled"
                            )
                        return self._await_quiescence_restart(
                            transaction, session_id, plan.summary,
                            "held add-on became enabled; restart Kodi before configuration",
                        )
                    if record_map[node.addon_id].resolution is not InstallResolution.SKIPPED:
                        record_map[node.addon_id] = replace(
                            record_map[node.addon_id], state=ResolutionState.INSTALLED
                        )
                    installed_ids.add(node.addon_id)
            for node in plan.install_order:
                if node.addon_id not in prelude_ids:
                    continue
                if node.addon_id in installed_ids:
                    continue
                record = record_map[node.addon_id]
                data = self.artifact_store.read_bytes(record.artifact_sha256)
                current = self.installer.install_exact(node.addon_id, node.version, data)
                if current.version != node.version or current.broken:
                    raise FrozenInstallValidationError("captured repository prerequisite failed exact verification")
                install_enabled = False if node.addon_id in hold_ids else node.desired_enabled
                if node.addon_id in hold_ids and current.enabled:
                    self.installer.set_addon_enabled(node.addon_id, False)
                    record_map[node.addon_id] = replace(record, state=ResolutionState.INSTALLED)
                    transaction = self._persist_resolutions(
                        transaction, manifest, tuple(record_map.values())
                    )
                    return self._await_quiescence_restart(
                        transaction, session_id, plan.summary,
                        "held add-on was discovered enabled; restart Kodi before configuration",
                    )
                if current.enabled is not install_enabled:
                    current = self.installer.set_addon_enabled(node.addon_id, install_enabled)
                if current.enabled is not install_enabled:
                    raise FrozenInstallValidationError("captured repository prerequisite enabled state is invalid")
                record_map[node.addon_id] = replace(record, state=ResolutionState.INSTALLED)
                installed_ids.add(node.addon_id)
                transaction = self._persist_resolutions(transaction, manifest, tuple(record_map.values()))

            packages = {}
            for addon_id in sorted(repository_ids):
                repository = self.installer.get_addon_details(addon_id)
                if repository is None or not repository.enabled or repository.broken:
                    raise FrozenInstallValidationError("captured repository is not installed and enabled")
            for addon_id, record in tuple(record_map.items()):
                if record.resolution is not InstallResolution.REPOSITORY_CURRENT:
                    continue
                package = self.installer.resolve_repository_current(
                    addon_id, record.repository_id
                )
                if (
                    package.addon_id != addon_id
                    or package.repository_id != record.repository_id
                    or not package.version
                ):
                    raise FrozenInstallValidationError("repository returned a mismatched package identity")
                validate_addon_zip(
                    package.zip_bytes,
                    expected_addon_id=addon_id,
                    expected_version=package.version,
                )
                metadata = self.artifact_store.import_zip(
                    package.zip_bytes,
                    expected_addon_id=addon_id,
                    expected_version=package.version,
                    source=f"repository:{record.repository_id}",
                )
                packages[addon_id] = package
                record_map[addon_id] = replace(
                    record,
                    state=ResolutionState.RESOLVED,
                    resolved_version=package.version,
                    artifact_sha256=metadata.sha256,
                    artifact_size=metadata.size,
                )
                transaction = self._persist_resolutions(transaction, manifest, tuple(record_map.values()))

            extra_dependencies = {}
            for addon_id, package in packages.items():
                extra_dependencies[addon_id] = _repository_package_required_dependencies(
                    package, plan, record_map, skipped
                )
            resolved_plan = validate_frozen_install_plan(
                manifest,
                self.artifact_store,
                policies,
                skipped=tuple(skipped),
                extra_dependencies=extra_dependencies,
            )
            self._check_private_ownership_compatibility(
                desired_profile, tuple(record_map.values())
            )

            for node in resolved_plan.install_order:
                if node.addon_id in installed_ids:
                    continue
                record = record_map[node.addon_id]
                if record.resolution is InstallResolution.SKIPPED:
                    continue
                if record.resolution is InstallResolution.REPOSITORY_CURRENT and not record.resolved_version:
                    raise FrozenInstallValidationError("repository resolution metadata is incomplete")
                version = record.resolved_version or node.version
                data = self.artifact_store.read_bytes(record.artifact_sha256)
                current = self.installer.install_exact(node.addon_id, version, data)
                if current.addon_id != node.addon_id or current.version != version or current.broken:
                    raise FrozenInstallValidationError("installed add-on did not match resolved package identity")
                install_enabled = False if node.addon_id in hold_ids else node.desired_enabled
                if node.addon_id in hold_ids and current.enabled:
                    self.installer.set_addon_enabled(node.addon_id, False)
                    record_map[node.addon_id] = replace(record, state=ResolutionState.INSTALLED)
                    transaction = self._persist_resolutions(
                        transaction, manifest, tuple(record_map.values())
                    )
                    return self._await_quiescence_restart(
                        transaction, session_id, plan.summary,
                        "held add-on was discovered enabled; restart Kodi before configuration",
                    )
                if current.enabled is not install_enabled:
                    current = self.installer.set_addon_enabled(node.addon_id, install_enabled)
                if current.enabled is not install_enabled:
                    raise FrozenInstallValidationError("resolved add-on enabled state is invalid")
                record_map[node.addon_id] = replace(record, state=ResolutionState.INSTALLED)
                transaction = self._persist_resolutions(transaction, manifest, tuple(record_map.values()))

            if any(record.state not in (ResolutionState.INSTALLED, ResolutionState.SKIPPED) for record in record_map.values()):
                raise FrozenInstallValidationError("install resolution did not reach a terminal state")
            transaction = self._persist_resolutions(transaction, manifest, tuple(record_map.values()))
            # Native Kodi discovery/reload is an activation boundary. Keep
            # every held add-on disabled and cross one complete Kodi session
            # boundary before calling any structured-resource initializer.
            # This also covers installers that report disabled after a reload
            # but may have started an extension transiently during discovery.
            if hold_ids and not active_resume:
                return self._await_quiescence_restart(
                    transaction,
                    session_id,
                    plan.summary,
                    "exact software is staged with held add-ons disabled; restart Kodi before configuration",
                )
            resolution_manifest = self._make_resolution_manifest(
                manifest, transaction, tuple(record_map.values())
            )
            transaction = self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.INSTALLING_SOFTWARE,
                new_phase=FrozenInstallPhase.CONFIGURING,
                lifecycle_stage=(
                    FrozenLifecycleStage.CONFIGURING
                    if hold_ids else transaction.lifecycle_stage
                ),
                configuration_manifest_path=configuration_manifest_path or manifest_path,
            )
            if self.configuration_runner is not None:
                request_path = configuration_manifest_path or manifest_path
                result = self.configuration_runner(ReconcileRequest(
                    request_path,
                    device_profile_id,
                    install_resolutions=tuple(sorted(
                        record_map.values(), key=lambda record: record.addon_id
                    )),
                    source_software_fingerprint=manifest.fingerprint(),
                    frozen_transaction_id=(transaction.transaction_id if hold_ids else ""),
                ))
                transaction, awaiting = self._handle_configuration_result(transaction, result)
                if awaiting is not None:
                    return replace(awaiting, recoverability=plan.summary, resolution_manifest=resolution_manifest)
            return self._finalize(
                transaction, resolved_plan.strict_plan, guard,
                manifest=manifest, records=tuple(record_map.values()),
                resolution_manifest=resolution_manifest,
                recoverability=plan.summary,
            )
        except Exception as exc:
            failure_code = getattr(exc, "code", "") or (
                f"FROZEN_INSTALL_{type(exc).__name__.upper()}"
            )
            safe_detail = getattr(exc, "safe_detail", "")
            safe_detail_valid = (
                isinstance(safe_detail, str)
                and len(safe_detail) <= 480
                and re.fullmatch(r"[A-Za-z0-9_=; .:/-]+", safe_detail)
            )
            if safe_detail_valid and len(safe_detail) > 350:
                message = f"configuration failure: {safe_detail}"
            else:
                message = (
                    "frozen installation failed at "
                    f"{_safe_exception_location(exc)} and requires explicit recovery"
                    + (f" ({safe_detail})" if safe_detail_valid else "")
                )
            return self._attention(
                transaction,
                failure_code,
                message,
                recoverability=plan.summary,
                resolution_manifest=resolution_manifest,
                transaction_updates=(
                    exc.transaction_updates
                    if isinstance(exc, FrozenConfigurationFailure) else None
                ),
            )

    def _restore_resolution(self, manifest, transaction, *, allow_uninstalled=False):
        policies = transaction.policies
        records = tuple(transaction.resolution_records)
        if not records:
            # Compatibility with BM-022 schema-1 transactions created before
            # explicit resolution records existed: those transactions were
            # exact-only and have already installed all exact packages.
            strict_plan = validate_frozen_manifest(manifest, self.artifact_store)
            records = tuple(
                replace(default_exact_record(node), state=ResolutionState.INSTALLED)
                for node in strict_plan.install_order
            )
            plan = RecoverableFrozenInstallPlan(
                strict_plan,
                (),
                summarize_frozen_recoverability(manifest, self.artifact_store),
                install_plan_fingerprint(manifest, ()),
                tuple(FrozenPlanAction(FrozenPlanActionKind.INSTALL_EXACT_ARTIFACT, node.addon_id)
                      for node in strict_plan.install_order),
            )
        else:
            skipped = tuple(
                record.addon_id for record in records
                if record.resolution is InstallResolution.SKIPPED
            )
            plan = validate_frozen_install_plan(
                manifest, self.artifact_store, policies, skipped=skipped
            )
            if plan.install_plan_fingerprint != transaction.install_plan_fingerprint:
                raise FrozenInstallValidationError("install policy changed before restart resume")
            rows = {row.addon_id: row for row in plan.summary.addons}
            record_map = {record.addon_id: record for record in records}
            if set(record_map) != set(rows):
                raise FrozenInstallValidationError("durable resolutions do not cover captured add-ons")
            extra_dependencies = {}
            for addon_id, record in record_map.items():
                node = plan.nodes[addon_id]
                row = rows[addon_id]
                if record.captured_version != node.version:
                    raise FrozenInstallValidationError("durable resolution changed captured version")
                if record.resolution is InstallResolution.EXACT:
                    if (
                        not row.exact_artifact_available
                        or node.artifact is None
                        or record.resolved_version != node.version
                        or record.artifact_sha256 != node.artifact.sha256
                        or record.artifact_size != node.artifact.size
                        or record.state not in (
                            (
                                ResolutionState.INSTALLED,
                                ResolutionState.RESOLVED,
                                ResolutionState.SELECTED,
                            )
                            if allow_uninstalled else (ResolutionState.INSTALLED,)
                        )
                    ):
                        raise FrozenInstallValidationError("durable exact resolution is inconsistent")
                elif record.resolution is InstallResolution.REPOSITORY_CURRENT:
                    policy = effective_policy(addon_id, {item.addon_id: item for item in policies})
                    if (
                        not policy.repository_fallback_allowed
                        or record.repository_id != row.repository_id
                        or not record.resolved_version
                        or not record.artifact_sha256
                        or record.state is not ResolutionState.INSTALLED
                    ):
                        raise FrozenInstallValidationError("durable repository resolution is inconsistent")
                    data = self.artifact_store.read_bytes(record.artifact_sha256)
                    metadata = self.artifact_store.get_metadata(record.artifact_sha256)
                    if (
                        metadata.addon_id != addon_id
                        or metadata.version != record.resolved_version
                        or metadata.sha256 != record.artifact_sha256
                        or metadata.size != record.artifact_size
                        or len(data) != record.artifact_size
                    ):
                        raise FrozenInstallValidationError("durable resolved artifact identity is invalid")
                    package = RepositoryPackage(
                        addon_id, record.repository_id, record.resolved_version, data
                    )
                    extra_dependencies[addon_id] = _repository_package_required_dependencies(
                        package, plan, record_map, frozenset(skipped)
                    )
                elif record.resolution is InstallResolution.SKIPPED:
                    policy = effective_policy(addon_id, {item.addon_id: item for item in policies})
                    if not policy.skip_allowed or record.state is not ResolutionState.SKIPPED:
                        raise FrozenInstallValidationError("durable skip resolution is inconsistent")
            plan = validate_frozen_install_plan(
                manifest,
                self.artifact_store,
                policies,
                skipped=skipped,
                extra_dependencies=extra_dependencies,
            )
        if manifest.fingerprint() != transaction.manifest_fingerprint:
            raise FrozenInstallValidationError("frozen manifest changed before resume")
        if transaction.resolution_records:
            if resolution_fingerprint(records) != transaction.resolution_fingerprint:
                raise FrozenInstallValidationError("durable resolution fingerprint changed")
            resulting = resolved_software_fingerprint(manifest, records)
            if transaction.resolved_software_fingerprint != resulting and not (
                allow_uninstalled
                and not transaction.resolved_software_fingerprint
                and any(
                    record.state in {
                        ResolutionState.RESOLVED,
                        ResolutionState.SELECTED,
                    }
                    for record in records
                )
            ):
                raise FrozenInstallValidationError("resolved software fingerprint changed")
        resolution_manifest = self._make_resolution_manifest(manifest, transaction, records)
        return plan, records, resolution_manifest

    @staticmethod
    def _private_resource_results_verified(result: object) -> bool:
        reconcile_result = getattr(result, "reconcile_result", None) or result
        if hasattr(reconcile_result, "success") and not reconcile_result.success:
            return False
        collected = []
        for action_result in getattr(reconcile_result, "action_results", ()):
            owner = getattr(action_result, "owner_result", None)
            private_result = getattr(owner, "private_result", None)
            if private_result is None:
                continue
            if not getattr(private_result, "succeeded", False):
                return False
            collected.extend(getattr(private_result, "resource_results", ()))
        return bool(collected) and all(
            getattr(item, "succeeded", False) for item in collected
        )

    def resume_after_restart(
        self,
        *,
        current_session_id: Optional[str] = None,
        bm020_result: object = None,
    ) -> FrozenInstallResult:
        transaction = self._safe_inspect()
        if transaction is None:
            return FrozenInstallResult("failed", code="FROZEN_TRANSACTION_MISSING", message="no frozen install transaction is active")
        if transaction.phase is not FrozenInstallPhase.AWAITING_RESTART:
            return FrozenInstallResult("needs_attention", transaction=transaction, code="FROZEN_TRANSACTION_NOT_AWAITING", message="frozen transaction is not awaiting restart")
        recoverability = None
        resolution_manifest = None
        try:
            session = _valid_uuid(current_session_id or self.session_id_provider(), "current_session_id")
            if session == transaction.originating_kodi_session_id:
                return FrozenInstallResult("awaiting_restart", transaction=transaction, code="SAME_SESSION", message="Kodi has not crossed the restart boundary")
            guard = AddonUpdateGuard(self.policy_backend)
            guard.reassert_required()
            manifest = self.manifest_loader(transaction.manifest_path)
            if transaction.lifecycle_stage is FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART:
                plan, records, _resolution_manifest = self._restore_resolution(
                    manifest, transaction, allow_uninstalled=True
                )
                desired_profile = self._configuration_profile(
                    transaction.configuration_manifest_path,
                    transaction.device_profile_id,
                )
                held_ids = self._activation_hold_ids(plan, desired_profile)
                readiness_ids = self._registry_readiness_ids(desired_profile)
                if (
                    not held_ids
                    or not readiness_ids
                    or not set(readiness_ids).issubset(held_ids)
                    or held_ids != transaction.activation_hold_ids
                    or transaction.activation_hold_released
                ):
                    return self._attention(
                        transaction,
                        "FROZEN_ACTIVATION_HOLD_MISMATCH",
                        "quiescence resume activation hold does not match the validated resource graph",
                    )
                overlay_identity = self._private_overlay_metadata(
                    desired_profile, manifest.fingerprint()
                )
                if overlay_identity != (
                    transaction.private_overlay_id,
                    transaction.private_overlay_fingerprint,
                    transaction.private_overlay_required,
                ):
                    return self._attention(
                        transaction,
                        "FROZEN_PRIVATE_OVERLAY_IDENTITY_MISMATCH",
                        "private overlay identity changed before held-resource configuration",
                    )
                readiness = ensure_frozen_transaction_registry_ready(
                    transaction,
                    held_ids,
                    readiness_ids,
                    records,
                    current_session_id=session,
                    store=self.store,
                    policy_backend=self.policy_backend,
                    registry_backend=self.registry_backend,
                )
                if not readiness.allowed:
                    return self._attention(
                        transaction,
                        readiness.code or "FROZEN_ADDON_REGISTRY_CHECK_FAILED",
                        readiness.message or "held add-on registry readiness failed",
                    )
                return self.install(
                    manifest,
                    manifest_path=transaction.manifest_path,
                    device_profile_id=transaction.device_profile_id,
                    configuration_manifest_path=transaction.configuration_manifest_path,
                    install_policies=transaction.policies,
                    interactive=False,
                )
            if transaction.lifecycle_stage is FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART:
                if not self._private_resource_results_verified(bm020_result):
                    return self._attention(
                        transaction,
                        "PRIVATE_RESOURCE_RESUME_NOT_VERIFIED",
                        "successful BM-020 resume did not verify the held private resource",
                    )
                resumed_result = getattr(bm020_result, "reconcile_result", None)
                overlay = getattr(resumed_result, "private_overlay", None)
                if (
                    overlay is None
                    or overlay.overlay_id != transaction.private_overlay_id
                    or overlay.fingerprint != transaction.private_overlay_fingerprint
                ):
                    return self._attention(
                        transaction,
                        "PRIVATE_OVERLAY_RESUME_MISMATCH",
                        "resumed private overlay identity changed",
                    )
                plan, records, resolution_manifest = self._restore_resolution(
                    manifest, transaction
                )
                transaction = self.store.transition_expected(
                    transaction_id=transaction.transaction_id,
                    expected_phase=FrozenInstallPhase.AWAITING_RESTART,
                    new_phase=FrozenInstallPhase.RESUMING,
                    originating_kodi_session_id=session,
                    lifecycle_stage=FrozenLifecycleStage.PRIVATE_VERIFIED,
                )
                return self._finalize(
                    transaction, plan.strict_plan, guard,
                    manifest=manifest,
                    records=records,
                    resolution_manifest=resolution_manifest,
                    recoverability=plan.summary,
                )
            plan, records, resolution_manifest = self._restore_resolution(manifest, transaction)
            transaction = self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.AWAITING_RESTART,
                new_phase=FrozenInstallPhase.RESUMING,
            )
            return self._finalize(
                transaction, plan.strict_plan, guard,
                manifest=manifest,
                records=records,
                resolution_manifest=resolution_manifest,
                recoverability=plan.summary,
            )
        except Exception as exc:
            return self._attention(
                transaction,
                getattr(exc, "code", "FROZEN_RESUME_FAILED"),
                "frozen installation resume failed at "
                f"{_safe_exception_location(exc)} and requires explicit recovery",
                recoverability=recoverability,
                resolution_manifest=resolution_manifest,
            )

    def abandon(self, *, acknowledge_restore_failure: bool = False) -> FrozenInstallResult:
        transaction = self._safe_inspect()
        if transaction is None:
            return FrozenInstallResult("complete", message="no frozen transaction is active")
        if transaction.activation_hold_ids and not transaction.activation_hold_released:
            return FrozenInstallResult(
                "needs_attention",
                transaction=transaction,
                code="HELD_LIFECYCLE_CANNOT_BE_ABANDONED",
                message="the activation hold remains authoritative until private verification and final activation",
            )
        guard = AddonUpdateGuard(self.policy_backend)
        try:
            guard.restore_original(transaction.original_update_policy)
        except Exception:
            if not acknowledge_restore_failure:
                return self._attention(transaction, "UPDATE_POLICY_RESTORE_FAILED", "explicit abandon could not restore updater policy")
        try:
            self.store.clear_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=transaction.phase,
            )
        except Exception:
            return self._attention(transaction, "FROZEN_TRANSACTION_CLEAR_FAILED", "explicit abandon could not clear transaction")
        return FrozenInstallResult("complete", message="frozen installation explicitly abandoned; software was not rolled back")

    def _handle_configuration_result(self, transaction, result):
        from resources.lib.private_overlay import PrivateOverlayMetadata

        outcome = getattr(getattr(result, "outcome", None), "value", getattr(result, "outcome", ""))
        reconcile_result = getattr(result, "reconcile_result", None) or result
        overlay = getattr(result, "private_overlay", None)
        if overlay is None:
            overlay = getattr(reconcile_result, "private_overlay", None)
        overlay_kwargs = {
            "private_overlay_id": "",
            "private_overlay_fingerprint": "",
            "private_overlay_required": False,
        }
        if isinstance(overlay, PrivateOverlayMetadata):
            overlay_kwargs.update({
                "private_overlay_id": overlay.overlay_id,
                "private_overlay_fingerprint": overlay.fingerprint,
                "private_overlay_required": overlay.required,
            })
        if outcome in ("manual_restart_required", "awaiting_restart"):
            if (
                transaction.activation_hold_ids
                and transaction.lifecycle_restart_count >= 3
            ):
                raise FrozenInstallError(
                    "pre-activation lifecycle exceeded its bounded restart progression"
                )
            restart_tx = getattr(result, "transaction", None)
            restart_id = getattr(restart_tx, "transaction_id", "")
            updated = self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.CONFIGURING,
                new_phase=FrozenInstallPhase.AWAITING_RESTART,
                restart_transaction_id=restart_id,
                lifecycle_stage=(
                    FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART
                    if transaction.activation_hold_ids
                    else transaction.lifecycle_stage
                ),
                lifecycle_restart_count=(
                    transaction.lifecycle_restart_count + 1
                    if transaction.activation_hold_ids
                    else transaction.lifecycle_restart_count
                ),
                **overlay_kwargs,
            )
            return updated, FrozenInstallResult("awaiting_restart", transaction=updated, code="AWAITING_RESTART", message="restart Kodi completely to continue frozen installation")
        if outcome in ("failed", "needs_attention"):
            failure = getattr(result, "failure", None)
            if failure is None:
                failure = getattr(reconcile_result, "failure", None)
            phase = getattr(getattr(failure, "phase", None), "value", "")
            failure_code = getattr(failure, "code", "")
            diagnostic_parts = []
            if isinstance(outcome, str) and re.fullmatch(r"[a-z_]{1,40}", outcome):
                diagnostic_parts.append(f"outcome={outcome}")
            if isinstance(phase, str) and re.fullmatch(r"[a-z_]{1,40}", phase):
                diagnostic_parts.append(f"phase={phase}")
            if isinstance(failure_code, str) and re.fullmatch(
                r"[A-Z0-9_]{1,80}", failure_code
            ):
                diagnostic_parts.append(f"failure={failure_code}")
            for action_result in getattr(reconcile_result, "action_results", ()):
                if getattr(action_result, "succeeded", True):
                    continue
                action = getattr(action_result, "action", None)
                kind = getattr(action, "kind", "")
                kind = getattr(kind, "value", kind)
                if isinstance(kind, str):
                    kind = kind.strip().upper()
                addon_id = getattr(action, "addon_id", "")
                if isinstance(kind, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,39}", kind):
                    diagnostic_parts.append(f"action={kind}")
                if isinstance(addon_id, str) and _ADDON_ID.fullmatch(addon_id):
                    diagnostic_parts.append(f"addon={addon_id}")
                owner_result = getattr(action_result, "owner_result", None)
                if kind == "CONFIGURE":
                    diagnostic_parts.extend(
                        _configuration_failure_parts(owner_result)
                    )
                if kind == "SET_SKIN":
                    skin_failure_code = getattr(owner_result, "failure_code", None)
                    skin_failure_code = getattr(
                        skin_failure_code, "value", skin_failure_code
                    )
                    if skin_failure_code in {
                        item.value for item in SkinFailureCode
                    }:
                        diagnostic_parts.append(
                            f"skin_failure_code={skin_failure_code}"
                        )
                owner_code = getattr(owner_result, "code", "")
                if isinstance(owner_code, str) and re.fullmatch(
                    r"[A-Z0-9_]{1,80}", owner_code
                ):
                    diagnostic_parts.append(f"resource_failure={owner_code}")
                owner_id = getattr(owner_result, "owner_addon_id", "")
                if isinstance(owner_id, str) and _ADDON_ID.fullmatch(owner_id):
                    diagnostic_parts.append(f"owner={owner_id}")
                resource_id = getattr(owner_result, "resource_id", "")
                if isinstance(resource_id, str) and re.fullmatch(
                    r"[a-z0-9][a-z0-9._-]{0,127}", resource_id
                ):
                    diagnostic_parts.append(f"resource={resource_id}")
                cause_code = getattr(owner_result, "cause_code", "")
                if isinstance(cause_code, str) and re.fullmatch(
                    r"[A-Z0-9_]{1,80}", cause_code
                ):
                    diagnostic_parts.append(f"cause={cause_code}")
                stage_values = {item.value for item in ResourceInitializationStage}
                initialization_stage = getattr(
                    owner_result, "initialization_stage", ""
                )
                initialization_stage = getattr(
                    initialization_stage, "value", initialization_stage
                )
                if initialization_stage in stage_values:
                    diagnostic_parts.append(
                        f"initialization_stage={initialization_stage}"
                    )
                last_completed_stage = getattr(
                    owner_result, "last_completed_stage", ""
                )
                last_completed_stage = getattr(
                    last_completed_stage, "value", last_completed_stage
                )
                if last_completed_stage in stage_values:
                    diagnostic_parts.append(
                        f"last_completed_stage={last_completed_stage}"
                    )
                import_failure_category = getattr(
                    owner_result, "import_failure_category", ""
                )
                if isinstance(import_failure_category, str) and re.fullmatch(
                    r"[A-Z0-9_]{1,80}", import_failure_category
                ):
                    diagnostic_parts.append(
                        f"import_failure_category={import_failure_category}"
                    )
                failing_module = getattr(owner_result, "failing_module", "")
                if isinstance(failing_module, str) and re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,31}",
                    failing_module,
                ):
                    diagnostic_parts.append(f"failing_module={failing_module}")
                expected_provider = getattr(owner_result, "expected_provider", "")
                if isinstance(expected_provider, str) and _SAFE_PROVIDER_ID.fullmatch(
                    expected_provider
                ):
                    diagnostic_parts.append(
                        f"expected_provider={expected_provider}"
                    )
                actual_provider = getattr(owner_result, "actual_provider", "")
                if isinstance(actual_provider, str) and _SAFE_PROVIDER_ID.fullmatch(
                    actual_provider
                ):
                    diagnostic_parts.append(f"actual_provider={actual_provider}")
                break
            if any(
                part.startswith("import_failure_category=")
                for part in diagnostic_parts
            ):
                diagnostic_parts = [
                    part for part in diagnostic_parts
                    if not part.startswith(("outcome=", "phase=", "failure="))
                ]
            error = FrozenConfigurationFailure(
                "configuration/restart handoff failed",
                transaction_updates=_overlay_failure_transaction_updates(overlay),
            )
            error.code = (
                f"FROZEN_CONFIGURATION_{failure_code}"
                if isinstance(failure_code, str)
                and re.fullmatch(r"[A-Z0-9_]{1,80}", failure_code)
                else "FROZEN_CONFIGURATION_FAILED"
            )
            error.safe_detail = "; ".join(diagnostic_parts)
            raise error
        if hasattr(reconcile_result, "success") and not reconcile_result.success:
            raise FrozenInstallError("configuration reconciliation failed")
        if transaction.activation_hold_ids:
            action_results = getattr(reconcile_result, "action_results", ())
            resource_results = []
            for action_result in action_results:
                owner = getattr(action_result, "owner_result", None)
                private_result = getattr(owner, "private_result", None)
                resource_results.extend(
                    getattr(private_result, "resource_results", ())
                )
                if private_result is not None and not private_result.succeeded:
                    raise FrozenInstallError("structured private-resource application failed")
            if not resource_results or not all(
                getattr(item, "succeeded", False) for item in resource_results
            ):
                raise FrozenInstallError(
                    "pre-activation private-resource verification is missing"
                )
            if overlay is None:
                raise FrozenInstallError("private overlay identity was not recorded")
        updated = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=FrozenInstallPhase.CONFIGURING,
            new_phase=FrozenInstallPhase.CONFIGURING,
            lifecycle_stage=(
                FrozenLifecycleStage.PRIVATE_VERIFIED
                if transaction.activation_hold_ids
                else transaction.lifecycle_stage
            ),
            **overlay_kwargs,
        )
        if transaction.activation_hold_ids:
            _log_lifecycle_event(
                "Build Manager BM-022 private resource verified; activation remains held"
            )
        return updated, None

    def _finalize(
        self,
        transaction,
        plan,
        guard,
        *,
        manifest,
        records,
        resolution_manifest,
        recoverability,
    ) -> FrozenInstallResult:
        transaction = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=transaction.phase,
            new_phase=FrozenInstallPhase.VALIDATING,
        )
        if self.final_validator is not None and not self.final_validator(plan):
            return self._attention(
                transaction, "FINAL_VALIDATION_FAILED",
                "frozen software/configuration validation failed",
                recoverability=recoverability, resolution_manifest=resolution_manifest,
            )
        if transaction.activation_hold_ids and not transaction.activation_hold_released:
            if transaction.lifecycle_stage is not FrozenLifecycleStage.PRIVATE_VERIFIED:
                return self._attention(
                    transaction, "PRIVATE_RESOURCE_NOT_VERIFIED",
                    "activation hold cannot be released before private verification",
                    recoverability=recoverability,
                    resolution_manifest=resolution_manifest,
                )
            transaction = self.store.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.VALIDATING,
                new_phase=FrozenInstallPhase.VALIDATING,
                lifecycle_stage=FrozenLifecycleStage.ACTIVATION_RELEASED,
                activation_hold_released=True,
            )
            _log_lifecycle_event(
                "Build Manager BM-022 activation hold released after private verification"
            )
        record_map = {record.addon_id: record for record in records}
        for record in records:
            if record.resolution is InstallResolution.SKIPPED:
                current = self.installer.get_addon_details(record.addon_id)
                if current is not None:
                    return self._attention(
                        transaction,
                        "SKIPPED_ADDON_PRESENT",
                        f"skipped add-on {record.addon_id} is present on the target",
                        recoverability=recoverability, resolution_manifest=resolution_manifest,
                    )
        for node in plan.install_order:
            record = record_map.get(node.addon_id)
            if record is None or record.resolution is InstallResolution.SKIPPED:
                return self._attention(
                    transaction, "INSTALL_RESOLUTION_MISSING",
                    "install resolution does not cover the final plan",
                    recoverability=recoverability, resolution_manifest=resolution_manifest,
                )
            resolved_version = record.resolved_version or node.version
            current = self.installer.get_addon_details(node.addon_id)
            if current is None or current.version != resolved_version or current.broken:
                return self._attention(
                    transaction, "RESOLVED_VERSION_VALIDATION_FAILED",
                    f"resolved version validation failed for {node.addon_id}",
                    recoverability=recoverability, resolution_manifest=resolution_manifest,
                )
            if current.enabled is not node.desired_enabled:
                self.installer.set_addon_enabled(node.addon_id, node.desired_enabled)
        for node in plan.install_order:
            record = record_map[node.addon_id]
            resolved_version = record.resolved_version or node.version
            current = self.installer.get_addon_details(node.addon_id)
            if current is None or current.version != resolved_version or current.enabled is not node.desired_enabled or current.broken:
                return self._attention(
                    transaction, "FINAL_STATE_VALIDATION_FAILED",
                    f"final frozen state validation failed for {node.addon_id}",
                    recoverability=recoverability, resolution_manifest=resolution_manifest,
                )
        computed_resolution_manifest = self._make_resolution_manifest(
            manifest, transaction, tuple(records)
        )
        if (
            computed_resolution_manifest.resolution_fingerprint
            != resolution_manifest.resolution_fingerprint
            or computed_resolution_manifest.resulting_software_fingerprint
            != resolution_manifest.resulting_software_fingerprint
        ):
            return self._attention(
                transaction, "RESOLUTION_FINGERPRINT_MISMATCH",
                "install resolution identity changed before completion",
                recoverability=recoverability, resolution_manifest=resolution_manifest,
            )
        transaction = self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=FrozenInstallPhase.VALIDATING,
            new_phase=FrozenInstallPhase.COMPLETE,
            resolution_records=tuple(records),
            resolution_fingerprint_value=resolution_manifest.resolution_fingerprint,
            resolved_software_fingerprint_value=resolution_manifest.resulting_software_fingerprint,
        )
        try:
            self.store.save_resolution_manifest(resolution_manifest)
        except Exception:
            return self._attention(
                transaction, "RESOLUTION_PERSISTENCE_FAILED",
                "completed install resolution could not be recorded",
                recoverability=recoverability, resolution_manifest=resolution_manifest,
            )
        try:
            guard.restore_original(transaction.original_update_policy)
        except Exception:
            return self._attention(
                transaction, "UPDATE_POLICY_RESTORE_FAILED",
                "original updater policy could not be restored",
                recoverability=recoverability, resolution_manifest=resolution_manifest,
            )
        try:
            self.store.clear_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.COMPLETE,
            )
        except Exception:
            return self._attention(
                transaction, "FROZEN_TRANSACTION_CLEAR_FAILED",
                "completed frozen transaction could not be cleared",
                recoverability=recoverability, resolution_manifest=resolution_manifest,
            )
        return FrozenInstallResult(
            "complete",
            message="frozen installation completed and updater policy restored",
            recoverability=recoverability,
            resolution_manifest=resolution_manifest,
        )

    def _attention(
        self, transaction, code: str, message: str, *,
        recoverability=None, resolution_manifest=None, transaction_updates=None,
    ) -> FrozenInstallResult:
        try:
            current = self.store.inspect() or transaction
            if current.phase is not FrozenInstallPhase.NEEDS_ATTENTION:
                updates = {}
                if isinstance(transaction_updates, dict) and set(transaction_updates) == {
                    "private_overlay_id",
                    "private_overlay_fingerprint",
                    "private_overlay_required",
                }:
                    overlay_id = transaction_updates.get("private_overlay_id")
                    fingerprint = transaction_updates.get(
                        "private_overlay_fingerprint"
                    )
                    required = transaction_updates.get("private_overlay_required")
                    if (
                        isinstance(overlay_id, str)
                        and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", overlay_id)
                        and isinstance(fingerprint, str)
                        and re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)
                        and isinstance(required, bool)
                    ):
                        updates = dict(transaction_updates)
                current = self.store.transition_expected(
                    transaction_id=current.transaction_id,
                    expected_phase=current.phase,
                    new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
                    status_code=_bounded(code, _MAX_CODE, "FROZEN_INSTALL_FAILED"),
                    status_message=_bounded(message, _MAX_MESSAGE, "frozen install requires attention"),
                    **updates,
                )
        except Exception:
            current = transaction
        return FrozenInstallResult(
            "needs_attention", transaction=current, code=code, message=message,
            recoverability=recoverability, resolution_manifest=resolution_manifest,
        )

    def _safe_inspect(self) -> Optional[FrozenInstallTransaction]:
        try:
            return self.store.inspect()
        except Exception:
            return None


@dataclass(frozen=True)
class FrozenStartupPrecondition:
    allowed: bool
    transaction: Optional[FrozenInstallTransaction] = None
    code: str = ""
    message: str = ""


def ensure_frozen_install_guard(
    *,
    store: Optional[FrozenInstallStore] = None,
    policy_backend: Optional[UpdatePolicyBackend] = None,
) -> FrozenStartupPrecondition:
    """Reassert quarantine before any BM-020 startup/resume work."""
    target = store or FrozenInstallStore()
    try:
        transaction = target.inspect()
    except Exception:
        return FrozenStartupPrecondition(False, code="FROZEN_TRANSACTION_INSPECTION_FAILED", message="active frozen transaction could not be inspected")
    if transaction is None:
        return FrozenStartupPrecondition(True)
    backend = policy_backend or _default_policy_backend()
    try:
        AddonUpdateGuard(backend).reassert_required()
    except Exception:
        try:
            updated = target.transition_expected(
                transaction_id=transaction.transaction_id,
                expected_phase=transaction.phase,
                new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
                status_code="UPDATER_REASSERT_FAILED",
                status_message="NEVER_CHECK could not be reasserted before startup resume",
            )
        except Exception:
            updated = transaction
        return FrozenStartupPrecondition(False, updated, "UPDATER_REASSERT_FAILED", "NEVER_CHECK could not be reasserted before startup resume")
    try:
        import xbmc
        xbmc.log(
            "Build Manager BM-022 updater guard reasserted before BM-020 startup",
            xbmc.LOGINFO,
        )
    except (ImportError, AttributeError, RuntimeError):
        pass
    if transaction.phase is FrozenInstallPhase.NEEDS_ATTENTION:
        return FrozenStartupPrecondition(False, transaction, "FROZEN_NEEDS_ATTENTION", "frozen installation requires explicit recovery")
    return FrozenStartupPrecondition(True, transaction, message="frozen updater guard reasserted")


@dataclass(frozen=True)
class FrozenResumeRegistryReadiness:
    allowed: bool
    code: str = ""
    message: str = ""
    registry_result: Optional[object] = None


def ensure_frozen_transaction_registry_ready(
    transaction: FrozenInstallTransaction,
    held_ids: Sequence[str],
    readiness_ids: Sequence[str],
    records: Sequence[InstallResolutionRecord],
    *,
    current_session_id: str,
    store: Optional[FrozenInstallStore] = None,
    policy_backend: Optional[UpdatePolicyBackend] = None,
    registry_backend=None,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> FrozenResumeRegistryReadiness:
    """Run the shared fail-closed registry gate for a validated BM-022 resume.

    The caller validates the frozen manifest, install plan, resolution
    records, overlay identity, and activation-hold graph. This final gate
    reloads durable ownership and updater state before using the same Kodi
    registry helper shared with BM-020 resume.
    """
    target = store or FrozenInstallStore()
    try:
        durable = target.inspect()
    except Exception:
        return FrozenResumeRegistryReadiness(
            False,
            "FROZEN_TRANSACTION_INSPECTION_FAILED",
            "frozen transaction could not be reloaded before registry readiness",
        )
    if (
        durable is None
        or durable != transaction
        or durable.phase is not FrozenInstallPhase.AWAITING_RESTART
        or durable.lifecycle_stage not in {
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART,
        }
        or durable.activation_hold_released
        or not durable.updater_guard_required
        or durable.originating_kodi_session_id == current_session_id
        or tuple(sorted(set(held_ids))) != tuple(sorted(durable.activation_hold_ids))
        or not readiness_ids
        or not set(readiness_ids).issubset(durable.activation_hold_ids)
    ):
        return FrozenResumeRegistryReadiness(
            False,
            "FROZEN_LIFECYCLE_STAGE_INVALID",
            "held add-on registry readiness was requested outside the verified quiescence continuation",
        )

    backend = policy_backend or _default_policy_backend()
    try:
        if AddonUpdatePolicy(backend.get_policy()) is not AddonUpdatePolicy.NEVER_CHECK:
            return FrozenResumeRegistryReadiness(
                False,
                "FROZEN_UPDATER_NOT_QUARANTINED",
                "updater quarantine was not active before held add-on registry refresh",
            )
    except Exception:
        return FrozenResumeRegistryReadiness(
            False,
            "FROZEN_UPDATER_STATE_UNAVAILABLE",
            "updater quarantine could not be verified before held add-on registry refresh",
        )

    try:
        from resources.lib.activation import current_activation_holds
        active_holds = current_activation_holds(
            lambda: active_activation_hold_ids(target)
        )
    except Exception:
        return FrozenResumeRegistryReadiness(
            False,
            "FROZEN_ACTIVATION_HOLD_UNAVAILABLE",
            "activation hold could not be reloaded before registry readiness",
        )
    if active_holds != frozenset(durable.activation_hold_ids):
        return FrozenResumeRegistryReadiness(
            False,
            "FROZEN_ACTIVATION_HOLD_MISMATCH",
            "durable activation hold does not match the frozen transaction",
        )

    expected_activation_holds = frozenset(durable.activation_hold_ids)

    def verified_activation_holds():
        current = active_activation_hold_ids(target)
        if current != expected_activation_holds:
            raise FrozenInstallValidationError(
                "durable activation hold changed during registry readiness"
            )
        return current

    records_by_id = {record.addon_id: record for record in records}
    expectations = []
    try:
        from resources.lib.addon_registry import (
            StagedAddonExpectation,
            ensure_staged_addons_registered_for_configuration,
        )
        for addon_id in sorted(readiness_ids):
            record = records_by_id.get(addon_id)
            if (
                record is None
                or record.state not in {
                    ResolutionState.INSTALLED,
                    ResolutionState.RESOLVED,
                    ResolutionState.SELECTED,
                }
                or not record.resolved_version
            ):
                return FrozenResumeRegistryReadiness(
                    False,
                    "FROZEN_HELD_RESOLUTION_MISSING",
                    "a configure-before-activation owner has no validated package version",
                )
            expectations.append(
                StagedAddonExpectation(addon_id, record.resolved_version)
            )
        registry_result = ensure_staged_addons_registered_for_configuration(
            tuple(expectations),
            backend=registry_backend,
            activation_hold_provider=verified_activation_holds,
            timeout=timeout,
            poll_interval=poll_interval,
            monotonic=monotonic,
            sleeper=sleeper,
        )
    except Exception:
        return FrozenResumeRegistryReadiness(
            False,
            "FROZEN_ADDON_REGISTRY_CHECK_FAILED",
            "held add-on registry readiness could not be verified",
        )
    if not registry_result.ready:
        return FrozenResumeRegistryReadiness(
            False,
            f"FROZEN_ADDON_REGISTRY_{registry_result.code.value.upper()}",
            registry_result.message,
            registry_result,
        )
    return FrozenResumeRegistryReadiness(
        True,
        registry_result.code.value.upper(),
        registry_result.message,
        registry_result,
    )


def ensure_frozen_resume_registry_ready(
    restart_transaction: object,
    preview: object,
    current_session_id: str,
    *,
    store: Optional[FrozenInstallStore] = None,
    artifact_store: Optional[ArtifactStore] = None,
    policy_backend: Optional[UpdatePolicyBackend] = None,
    registry_backend=None,
    manifest_loader: Callable[[str], FrozenBuildManifest] = _default_manifest_loader,
    coordinator_factory=None,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> FrozenResumeRegistryReadiness:
    """Validate the held BM-022 transaction and refresh Kodi's local registry.

    This pre-reconcile hook is called after BM-020 has validated its new
    session, request, desired fingerprint, and overlay identity, but before
    ``BuildManager.reconcile`` can enter public or private configuration.
    """
    request = getattr(preview, "request", None)
    source_fingerprint = getattr(request, "source_software_fingerprint", "")
    if not source_fingerprint:
        return FrozenResumeRegistryReadiness(True)

    target = store or FrozenInstallStore()
    try:
        transaction = target.inspect()
    except Exception:
        return FrozenResumeRegistryReadiness(
            False,
            "FROZEN_TRANSACTION_INSPECTION_FAILED",
            "frozen transaction could not be reloaded before registry readiness",
        )
    if transaction is None:
        return FrozenResumeRegistryReadiness(True)
    if not transaction.activation_hold_ids or transaction.activation_hold_released:
        return FrozenResumeRegistryReadiness(True)

    backend = policy_backend or _default_policy_backend()

    def blocked(code: str, message: str) -> FrozenResumeRegistryReadiness:
        return FrozenResumeRegistryReadiness(False, code, message)

    if (
        transaction.phase is not FrozenInstallPhase.AWAITING_RESTART
        or transaction.lifecycle_stage not in {
            FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART,
        }
        or transaction.activation_hold_released
        or not transaction.updater_guard_required
    ):
        return blocked(
            "FROZEN_LIFECYCLE_STAGE_INVALID",
            "held add-on registry readiness was requested outside an awaiting-restart lifecycle stage",
        )
    if transaction.originating_kodi_session_id == current_session_id:
        return blocked(
            "FROZEN_SAME_SESSION",
            "held add-on registry readiness requires a verified Kodi session boundary",
        )
    if (
        getattr(restart_transaction, "request", None) != request
        or getattr(request, "manifest_path", "") != transaction.configuration_manifest_path
        or getattr(request, "device_profile_id", "") != transaction.device_profile_id
        or source_fingerprint != transaction.manifest_fingerprint
        or not getattr(preview, "success", False)
    ):
        return blocked(
            "FROZEN_RESUME_IDENTITY_MISMATCH",
            "BM-020 resume identity does not match the held frozen transaction",
        )

    preview_overlay = getattr(preview, "private_overlay", None)
    if (
        preview_overlay is None
        or preview_overlay.overlay_id != transaction.private_overlay_id
        or preview_overlay.fingerprint != transaction.private_overlay_fingerprint
        or preview_overlay.required != transaction.private_overlay_required
    ):
        return blocked(
            "FROZEN_PRIVATE_OVERLAY_IDENTITY_MISMATCH",
            "BM-020 preview private overlay does not match the held frozen transaction",
        )

    try:
        manifest = manifest_loader(transaction.manifest_path)
        active_artifact_store = artifact_store or ArtifactStore(
            default_frozen_install_root() / "frozen-artifacts"
        )
        active_policy_backend = backend
        factory = coordinator_factory or FrozenInstallCoordinator
        coordinator = factory(
            store=target,
            artifact_store=active_artifact_store,
            policy_backend=active_policy_backend,
            installer=KodiRuntimeFrozenArtifactBackend(),
            manifest_loader=manifest_loader,
        )
        plan, records, _resolution_manifest = coordinator._restore_resolution(
            manifest, transaction
        )
        desired_profile = coordinator._configuration_profile(
            transaction.configuration_manifest_path,
            transaction.device_profile_id,
        )
        held_ids = coordinator._activation_hold_ids(plan, desired_profile)
        overlay_identity = coordinator._private_overlay_metadata(
            desired_profile, manifest.fingerprint()
        )
    except Exception:
        return blocked(
            "FROZEN_RESUME_IDENTITY_INVALID",
            "source manifest, install plan, resolution, or resource identity failed revalidation",
        )

    if (
        manifest.fingerprint() != transaction.manifest_fingerprint
        or held_ids != transaction.activation_hold_ids
        or overlay_identity != (
            transaction.private_overlay_id,
            transaction.private_overlay_fingerprint,
            transaction.private_overlay_required,
        )
    ):
        return blocked(
            "FROZEN_RESUME_IDENTITY_MISMATCH",
            "reloaded manifest, held resource, or private overlay identity changed",
        )

    return ensure_frozen_transaction_registry_ready(
        transaction,
        held_ids,
        coordinator._registry_readiness_ids(desired_profile),
        records,
        current_session_id=current_session_id,
        store=target,
        policy_backend=backend,
        registry_backend=registry_backend,
        timeout=timeout,
        poll_interval=poll_interval,
        monotonic=monotonic,
        sleeper=sleeper,
    )


def run_frozen_install_startup(
    *,
    bm020_status: object,
    store: Optional[FrozenInstallStore] = None,
    artifact_store: Optional[ArtifactStore] = None,
    policy_backend: Optional[UpdatePolicyBackend] = None,
    installer: Optional[FrozenArtifactBackend] = None,
    registry_backend=None,
    manifest_loader: Callable[[str], FrozenBuildManifest] = _default_manifest_loader,
    session_id_provider: Optional[Callable[[], str]] = None,
    configuration_runner: Optional[Callable[[ReconcileRequest], object]] = None,
) -> Optional[FrozenInstallResult]:
    """Continue the BM-022 lifecycle after ordinary BM-020 startup handling.

    The service calls this only after ``run_startup``. The updater precondition
    is repeated defensively. For a quiescence lifecycle restart, BM-022 owns the
    continuation even when BM-020 correctly reports ``no_transaction``.
    """
    target = store or FrozenInstallStore()
    transaction = target.inspect()
    if transaction is None:
        return None
    precondition = ensure_frozen_install_guard(
        store=target, policy_backend=policy_backend
    )
    if not precondition.allowed:
        return FrozenInstallResult(
            "needs_attention",
            transaction=precondition.transaction or transaction,
            code=precondition.code,
            message=precondition.message,
        )
    resume_result = getattr(bm020_status, "resume_result", None)
    if transaction.phase is not FrozenInstallPhase.AWAITING_RESTART:
        return FrozenInstallResult(
            "needs_attention" if transaction.phase is FrozenInstallPhase.NEEDS_ATTENTION else "awaiting_restart",
            transaction=transaction,
            code=transaction.status_code or "FROZEN_STARTUP_WAITING",
            message=transaction.status_message or "frozen installation is not ready for finalization",
        )
    if resume_result is None or not getattr(resume_result, "succeeded", False):
        if (
            transaction.lifecycle_stage is FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART
            and getattr(getattr(bm020_status, "classification", None), "value", "")
            == "no_transaction"
        ):
            pass
        else:
            return FrozenInstallResult(
                "awaiting_restart",
                transaction=transaction,
                code="BM020_RESUME_PENDING",
                message="frozen installation is waiting for successful BM-020 resume",
            )
    if (
        transaction.lifecycle_stage is FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART
        and (resume_result is None or not getattr(resume_result, "succeeded", False))
    ):
        return FrozenInstallResult(
            "awaiting_restart",
            transaction=transaction,
            code="BM020_RESUME_PENDING",
            message="frozen installation is waiting for successful BM-020 resume",
        )
    root = default_frozen_install_root()
    from resources.lib.restart_coordinator import RestartCoordinator
    coordinator = FrozenInstallCoordinator(
        store=target,
        artifact_store=artifact_store or ArtifactStore(root / "frozen-artifacts"),
        policy_backend=policy_backend or _default_policy_backend(),
        installer=installer or KodiRuntimeFrozenArtifactBackend(),
        manifest_loader=manifest_loader,
        session_id_provider=session_id_provider,
        configuration_runner=configuration_runner or RestartCoordinator().reconcile,
        registry_backend=registry_backend,
    )
    return coordinator.resume_after_restart(bm020_result=resume_result)


def _default_policy_backend() -> UpdatePolicyBackend:
    try:
        import xbmc

        def _rpc(method, params):
            response = json.loads(
                xbmc.executeJSONRPC(json.dumps({
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": 1,
                }))
            )
            return response.get("result", response)

        return KodiJsonRpcUpdatePolicyBackend(
            _rpc
        )
    except (ImportError, AttributeError, RuntimeError) as exc:
        raise FrozenInstallError("Kodi JSON-RPC runtime is unavailable") from exc


def _default_session_id() -> str:
    from resources.lib.session import get_current_kodi_session_id
    return get_current_kodi_session_id()
