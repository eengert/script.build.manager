"""BM-022 frozen-build installation and transaction lifecycle.

The installer prefers exact BM-021B artifacts and immutable content-addressed
packages. An explicit per-add-on policy may offer a user-selected current
version from one captured, verified repository or an explicit skip. All other
missing artifacts remain blocking, and existing installations must match the
selected exact or resolved version.

The durable transaction owns the global updater quarantine from the first
mutation until explicit final release or recovery.  It is intentionally
separate from BM-020's restart transaction. The initial install is the only
place that writes the quarantine; after a process restart the startup
precondition only verifies that Kodi persisted ``NEVER_CHECK`` (a changing
write there can deadlock Kodi 21.3) and fails closed otherwise.
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
import stat
import sys
import plistlib
from contextlib import contextmanager
from dataclasses import dataclass, replace
from types import MappingProxyType
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from resources.lib.a15_observation import (
    observe_acknowledged_publication_completion, observe_publication_roots,
)
from resources.lib.addons import KodiRuntimeAddonBackend, RepositoryPackage
from resources.lib.artifacts import ArtifactStore, ArtifactValidationError, validate_addon_zip
from resources.lib.build_library import LibraryInstallTarget, LibraryError
from resources.lib.build_manager import ActionFailureDiagnostic, ReconcileRequest
from resources.lib.failure_diagnostics import emit
from resources.lib.skin import SkinFailureCode
from resources.lib.skin_approval_state import SkinApprovalState, AUTHORIZED as SKIN_AUTHORIZED, CANCELLED as SKIN_CANCELLED
from resources.lib.private_resource import ResourceInitializationStage
from resources.lib.readonly_io import ReadOnlyStateError, UnsafeStateFile, read_regular_file
from resources.lib.frozen import (
    AddonCaptureNode,
    CaptureError,
    CaptureStatus,
    DependencyEdge,
    FrozenBuildManifest,
    InstalledMetadata,
    InstalledOrigin,
    KodiInventoryBackend,
    _check_addon_xml_identity,
    _declared_extension_points,
    _parse_dependency_edges,
    _builtin_version_satisfies,
    _open_canonical_directory,
)
from resources.lib.dependencies import _is_system_dependency, _strict_version_satisfies
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
    completed_resolution_fingerprint,
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


class FrozenPriorResolutionError(FrozenInstallValidationError):
    """A prior accepted outcome cannot be reused for this exact operation."""

    code = "PRIOR_RESOLUTION_INVALID"


class FrozenInstallStateUnreadable(FrozenInstallPersistenceError):
    """The durable record could not be read at all (I/O), as opposed to being invalid."""


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
    PUBLICATION_PENDING = "publication_pending"


class FrozenLifecycleStage(str, Enum):
    NONE = "none"
    INSTALLING_SOFTWARE = "installing_software"
    QUIESCENCE_AWAITING_RESTART = "quiescence_awaiting_restart"
    CONFIGURING = "configuring"
    CONFIGURATION_AWAITING_RESTART = "configuration_awaiting_restart"
    PRIVATE_VERIFIED = "private_verified"
    ACTIVATION_RELEASED = "activation_released"
    FINAL_ACTIVATION_AWAITING_RESTART = "final_activation_awaiting_restart"


_TRANSACTION_SCHEMA = 4
_TRANSACTION_FILENAME = "frozen_install_transaction.json"
_LOCK_FILENAME = "frozen_install_transaction.lock"
_MAX_CODE = 96
_MAX_MESSAGE = 512
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SAFE_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_HELD_RETRY_OWNER_ID = "plugin.video.redlight"
_HELD_RETRY_FAILURE_CODE = "FROZEN_MANIFEST_INVALID"


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
    library_target: Optional[LibraryInstallTarget] = None
    # Resolution fingerprint of the prior accepted outcome this transaction was seeded
    # from. Empty means no prior outcome. Identity-bearing: a request or resume with a
    # different prior is a different operation.
    prior_resolution_fingerprint: str = ""
    skin_approval: Optional[SkinApprovalState] = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, FrozenInstallPhase):
            raise FrozenInstallValidationError("invalid frozen-install phase")
        if self.skin_approval is not None:
            if not isinstance(self.skin_approval, SkinApprovalState):
                raise FrozenInstallValidationError("invalid skin approval state")
            self.skin_approval.validate_transaction(self)
        _valid_uuid(self.transaction_id, "transaction_id")
        _valid_uuid(self.originating_kodi_session_id, "originating_kodi_session_id")
        if not isinstance(self.build_id, str) or not self.build_id:
            raise FrozenInstallValidationError("build_id must be non-empty")
        if self.library_target is not None:
            if (not isinstance(self.library_target, LibraryInstallTarget)
                    or self.library_target.device_profile_id != self.device_profile_id
                    or self.manifest_path != "" or self.configuration_manifest_path != ""):
                raise FrozenInstallValidationError("library transaction identity is invalid")
        if not isinstance(self.manifest_path, str) or (not self.manifest_path and self.library_target is None):
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
        if not isinstance(self.prior_resolution_fingerprint, str) or (
            self.prior_resolution_fingerprint
            and not _FINGERPRINT.fullmatch(self.prior_resolution_fingerprint)
        ):
            raise FrozenInstallValidationError("prior_resolution_fingerprint is invalid")
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
            # Legacy and in-flight decisions retain their records-only identity.
            # A new completion additionally binds every immutable manifest field.
            completed_resolution = ""
            if (self.install_plan_fingerprint and self.resolved_software_fingerprint
                    and all(r.state in (ResolutionState.INSTALLED, ResolutionState.SKIPPED)
                            for r in self.resolution_records)):
                completed_resolution = completed_resolution_fingerprint(
                    self.build_id, self.manifest_fingerprint, self.install_plan_fingerprint,
                    self.resolved_software_fingerprint, self.resolution_records)
            if self.resolution_fingerprint and self.resolution_fingerprint not in (
                    expected_resolution, completed_resolution):
                raise FrozenInstallValidationError("transaction resolution fingerprint does not match")

    def to_dict(self) -> dict:
        return {
            "schema_version": 5 if self.skin_approval is not None else _TRANSACTION_SCHEMA,
            **({"skin_approval": self.skin_approval.to_dict()} if self.skin_approval is not None else {}),
            "library_target": self.library_target.to_dict() if self.library_target is not None else None,
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
            "prior_resolution_fingerprint": self.prior_resolution_fingerprint,
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
            "skin_approval",
            "private_overlay_id", "private_overlay_fingerprint",
            "private_overlay_required",
            "install_plan_fingerprint", "policies", "resolution_records",
            "resolution_fingerprint", "resolved_software_fingerprint",
            "configuration_manifest_path", "lifecycle_stage", "activation_hold_ids",
            "activation_hold_released", "lifecycle_restart_count", "library_target",
            "prior_resolution_fingerprint",
        }
        if set(value) - required - optional or not required.issubset(value):
            raise FrozenInstallPersistenceError("frozen transaction fields are unsupported")
        if type(value["schema_version"]) is not int or value["schema_version"] not in (1, 2, 3, _TRANSACTION_SCHEMA, 5):
            raise FrozenInstallPersistenceError("unsupported frozen transaction schema")
        if value["schema_version"] in (2, 3, _TRANSACTION_SCHEMA, 5) and not {
            "install_plan_fingerprint", "policies", "resolution_records",
            "resolution_fingerprint", "resolved_software_fingerprint",
        }.issubset(value):
            raise FrozenInstallPersistenceError("frozen transaction is missing resolution metadata")
        if value["schema_version"] in (3, _TRANSACTION_SCHEMA, 5) and not {
            "configuration_manifest_path", "lifecycle_stage", "activation_hold_ids",
            "activation_hold_released", "lifecycle_restart_count",
        }.issubset(value):
            raise FrozenInstallPersistenceError("frozen transaction is missing lifecycle metadata")
        if value["schema_version"] in (_TRANSACTION_SCHEMA, 5) and "library_target" not in value:
            raise FrozenInstallPersistenceError("frozen transaction is missing source metadata")
        if value["schema_version"] not in (_TRANSACTION_SCHEMA, 5) and value.get("library_target") is not None:
            raise FrozenInstallPersistenceError("legacy transaction cannot declare a library source")
        if (value["schema_version"] == 5) != (value.get("skin_approval") is not None):
            raise FrozenInstallPersistenceError("skin approval schema mismatch")
        if value["schema_version"] != 5 and "skin_approval" in value:
            raise FrozenInstallPersistenceError("legacy skin approval field refused")
        try:
            library_target = (
                LibraryInstallTarget.from_dict(value["library_target"])
                if value.get("library_target") is not None else None
            )
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
                skin_approval=SkinApprovalState.from_dict(value["skin_approval"]) if value["schema_version"] == 5 else None,
                library_target=library_target,
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
                prior_resolution_fingerprint=value.get("prior_resolution_fingerprint", ""),
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
        except (KeyError, TypeError, ValueError, FrozenInstallError, FrozenResolutionError, LibraryError) as exc:
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


def _is_held_quiescence_retry_snapshot(
    transaction: object,
) -> bool:
    """Return whether a durable snapshot is the one supported held retry."""
    return bool(
        isinstance(transaction, FrozenInstallTransaction)
        and transaction.phase is FrozenInstallPhase.NEEDS_ATTENTION
        and transaction.status_code == _HELD_RETRY_FAILURE_CODE
        and transaction.lifecycle_stage
        is FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART
        and transaction.lifecycle_restart_count == 1
        and transaction.activation_hold_ids == (_HELD_RETRY_OWNER_ID,)
        and not transaction.activation_hold_released
        and transaction.updater_guard_required
        and transaction.original_update_policy is AddonUpdatePolicy.AUTOMATIC
        and bool(transaction.manifest_fingerprint)
        and bool(transaction.install_plan_fingerprint)
        and bool(transaction.resolution_fingerprint)
        and bool(transaction.configuration_manifest_path or transaction.library_target)
        and bool(transaction.private_overlay_id)
        and bool(transaction.private_overlay_fingerprint)
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

    def __init__(self, root: Optional[Path] = None, *, create: bool = True):
        self.root = Path(root) if root is not None else default_frozen_install_root()
        if create:
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

    def load_resolution_manifest(self, fingerprint: str, *, nofollow: bool = False) -> FrozenInstallResolutionManifest:
        path = self.resolution_path(fingerprint)
        try:
            from resources.lib.build_library import _read_path, FILE_LIMIT
            raw = json.loads(_read_path(str(path), FILE_LIMIT) if nofollow
                             else path.read_text(encoding="utf-8"))
        except Exception as exc:
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

    @contextmanager
    def locked_recovery_access(self):
        """One synchronous recovery owner; nested store operations share its lock."""
        import threading
        active = True
        owner = threading.get_ident()

        class RecoveryAccess(FrozenInstallStore):
            @contextmanager
            def locked(access):
                if not active or threading.get_ident() != owner:
                    raise FrozenInstallStateConflict("recovery access is no longer owned")
                yield

        with self.locked():
            try:
                yield RecoveryAccess(self.root, create=False)
            finally:
                active = False

    def inspect(self) -> Optional[FrozenInstallTransaction]:
        with self.locked():
            if not self.transaction_path.exists():
                return None
            try:
                data = json.loads(self.transaction_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FrozenInstallPersistenceError("could not read frozen transaction") from exc
            return FrozenInstallTransaction.from_dict(data)

    @staticmethod
    def read_snapshot(root: Optional[Path] = None) -> Optional[FrozenInstallTransaction]:
        """Read-only observation of the durable record for status callers.

        A static method on purpose: constructing a store creates its directory
        and ``inspect()`` creates the lock file. This takes no lock and creates
        nothing; writers replace the record atomically, so the snapshot is one
        complete record. Raises ``FrozenInstallStateUnreadable`` when the file
        cannot be read and ``FrozenInstallValidationError`` (or the record's own
        validation errors) when its content is not trustworthy, including a
        symlink, FIFO, directory or oversized file.
        """
        base = Path(root) if root is not None else default_frozen_install_root()
        try:
            raw = read_regular_file(str(base / _TRANSACTION_FILENAME), limit=4 * 1024 * 1024)
        except UnsafeStateFile as exc:
            raise FrozenInstallValidationError("frozen transaction file is not a safe regular file") from exc
        except ReadOnlyStateError as exc:
            raise FrozenInstallStateUnreadable("could not read frozen transaction") from exc
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrozenInstallValidationError("frozen transaction is malformed") from exc
        return FrozenInstallTransaction.from_dict(data)

    def create(self, transaction: FrozenInstallTransaction) -> FrozenInstallTransaction:
        with self.locked():
            from resources.lib.capture_lifecycle import require_no_capture
            require_no_capture(self.root)
            if transaction.skin_approval is not None and transaction.skin_approval.phase != SKIN_AUTHORIZED:
                raise FrozenInstallStateConflict("skin protocol must start at authorization")
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
            if current.skin_approval is not None:
                raise FrozenInstallStateConflict("skin approval requires dedicated state API")
            if current.phase is FrozenInstallPhase.PUBLICATION_PENDING:
                raise FrozenInstallStateConflict("publication fence cannot be transitioned")
            if new_phase is FrozenInstallPhase.PUBLICATION_PENDING and (
                    current.phase is not FrozenInstallPhase.COMPLETE
                    or current.library_target is None or not current.resolution_fingerprint):
                raise FrozenInstallStateConflict("publication fence requires completed library identity")
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

    def rearm_held_quiescence(
        self, expected: FrozenInstallTransaction
    ) -> FrozenInstallTransaction:
        """CAS the exact supported held failure back to normal resume.

        The complete immutable transaction snapshot is compared under the
        profile-local lock. Only phase, safe failure diagnostics, and update
        time change; transaction, manifest, plan, configuration, overlay, and
        activation-hold identities remain byte-for-byte equivalent.
        """
        if not _is_held_quiescence_retry_snapshot(expected):
            raise FrozenInstallStateConflict(
                "held retry snapshot does not match the supported predicate"
            )
        with self.locked():
            current = self._read_unlocked()
            if current != expected:
                raise FrozenInstallStateConflict(
                    "frozen transaction snapshot changed before held retry"
                )
            updated = replace(
                current,
                phase=FrozenInstallPhase.AWAITING_RESTART,
                status_code="",
                status_message="",
                updated_at=_utc_now(),
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
            if current.skin_approval is not None:
                raise FrozenInstallStateConflict("skin approval evidence cannot be cleared")
            if current.phase is FrozenInstallPhase.PUBLICATION_PENDING:
                raise FrozenInstallStateConflict("publication fence requires publication completion")
            try:
                self.transaction_path.unlink()
                self._fsync_directory()
            except OSError as exc:
                raise FrozenInstallPersistenceError("could not clear frozen transaction") from exc
            return True

    def _confirm_publication_owner(self, expected):
        """Positively establish an exact visible fence after write ambiguity."""
        with self.locked():
            current = self._read_unlocked()
            if current != expected or current.phase is not FrozenInstallPhase.PUBLICATION_PENDING:
                raise FrozenInstallStateConflict("publication fence owner changed")
            self._fsync_directory_strict()
            return current

    def _clear_publication_expected(self, *, transaction_id, publication):
        """Transfer fenced ownership only to independent durable exact journal.

        Read/fsync the journal while holding the frozen lock, never a library
        writer lock. Ordinary clear/transition APIs cannot discard the fence.
        """
        from resources.lib.build_library import BuildLibrary, _directory
        with self.locked():
            current = self._read_unlocked()
            if current is None:
                return False
            if (current.transaction_id != transaction_id
                    or current.phase is not FrozenInstallPhase.PUBLICATION_PENDING
                    or current.library_target is None
                    or publication.transaction_id != current.transaction_id
                    or publication.candidate.entry_id != current.library_target.source.entry_id
                    or publication.candidate.device_profile_id != current.device_profile_id
                    or publication.candidate.resolution_fingerprint != current.resolution_fingerprint):
                raise FrozenInstallStateConflict("publication fence identity changed")
            library = BuildLibrary(current.library_target.source.root)
            with _directory(library.root) as fd:
                journal = library._publication_at(fd)
                if (journal is None or not journal.same_identity(publication)
                        or journal.state != "acknowledged"
                        or library._applied_at(fd) != journal.candidate):
                    raise FrozenInstallStateConflict("independent publication evidence is absent")
                library._resolution(journal.candidate, self)
                os.fsync(fd)  # positive journal durability before ownership transfer
            self.transaction_path.unlink()
            self._fsync_directory()
            return True

    def clear(self) -> bool:
        with self.locked():
            current = self._read_unlocked()
            if current is not None and current.skin_approval is not None:
                raise FrozenInstallStateConflict("skin approval evidence cannot be cleared")
            if current is not None and current.phase is FrozenInstallPhase.PUBLICATION_PENDING:
                raise FrozenInstallStateConflict("publication fence requires publication completion")
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
        write_lifecycle_record(self.transaction_path, transaction.to_dict(),
                               self._read_unlocked, self._fsync_directory)

    def _fsync_directory_strict(self) -> None:
        """Positive publication authority barrier; no compatibility suppression."""
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise FrozenInstallPersistenceError(
                "could not confirm publication fence durability") from exc

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


def write_lifecycle_record(path: Path, record: dict, verify: Callable, sync: Callable) -> None:
    """Reuse atomic lifecycle storage without sharing Install/Apply authority."""
    data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    staged = None
    try:
        fd, name = tempfile.mkstemp(prefix=".frozen-install.", suffix=".tmp", dir=path.parent)
        staged = Path(name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
        staged = None
        sync()
        verify()
    except FrozenInstallError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise FrozenInstallPersistenceError("atomic lifecycle write failed") from exc
    finally:
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                pass


def default_frozen_install_root() -> Path:
    try:
        import xbmcvfs
        return Path(xbmcvfs.translatePath("special://profile/addon_data/script.build.manager"))
    except (ImportError, AttributeError, RuntimeError):
        return Path("/tmp/script.build.manager-frozen-install")


def active_activation_hold_ids(
    store: Optional[FrozenInstallStore] = None,
) -> frozenset[str]:
    """Return held add-ons from authoritative Install and Create transactions.

    A corrupt or unreadable transaction propagates as an error so callers can
    fail closed. NEEDS_ATTENTION does not release a hold; only the durable
    ``activation_hold_released`` transition does. Create retains its hold until
    a terminal capture phase proves original enabled-state restoration.
    """
    target = store or FrozenInstallStore()
    transaction = target.inspect()
    from resources.lib.capture_lifecycle import capture_activation_holds
    capture_holds = capture_activation_holds(target.root)
    if transaction is None or transaction.activation_hold_released:
        return capture_holds
    return frozenset(transaction.activation_hold_ids) | capture_holds


@dataclass(frozen=True)
class FrozenManifestPlan:
    manifest: FrozenBuildManifest
    nodes: Mapping[str, AddonCaptureNode]
    install_order: Tuple[AddonCaptureNode, ...]
    artifact_dependencies: Optional[Mapping[str, Tuple[DependencyEdge, ...]]] = None

    @property
    def executable_install_order(self) -> Tuple[AddonCaptureNode, ...]:
        """Install order without platform-provided nodes, which are verified and never installed (D-028)."""
        return tuple(node for node in self.install_order if not node.platform_provided)


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
    if manifest.schema_version not in (1, 2):
        raise FrozenInstallValidationError("unsupported frozen manifest schema")
    if manifest.capture_status is not CaptureStatus.COMPLETE and not (
        manifest.capture_status is CaptureStatus.INCOMPLETE_ARTIFACT
        and recoverable_gaps
    ):
        raise FrozenInstallValidationError("incomplete frozen capture is not installable")
    nodes: Dict[str, AddonCaptureNode] = {}
    artifact_dependencies = {}
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
        if node.platform_provided:
            # Verified target requirement, not an artifact: it stays a graph vertex for
            # edges, cycles and missing children, but needs no ZIP (D-028).
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
            from resources.lib.addon_zip import validated_root
            xml = validated_root(data, node.addon_id, node.version).xml_bytes
            actual_edges = _admission_dependency_edges(xml, node.addon_id)
            if _canonical_artifact_edges(actual_edges, node.addon_id) != _canonical_artifact_edges(
                node.dependency_edges, node.addon_id
            ):
                raise FrozenInstallValidationError(
                    f"artifact dependency declarations differ for {node.addon_id}"
                )
            artifact_dependencies[node.addon_id] = actual_edges
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

    visiting, done = set(), set()
    def visit(addon_id):
        if addon_id in visiting:
            raise FrozenInstallValidationError("frozen dependency graph contains a cycle")
        if addon_id in done:
            return
        visiting.add(addon_id)
        for edge in nodes[addon_id].dependency_edges:
            child = nodes.get(edge.addon_id)
            if child is None or child.is_absent_optional_dependency or edge.addon_id in skipped:
                if edge.optional:
                    continue
                raise FrozenInstallValidationError("required dependency is absent from frozen manifest")
            visit(edge.addon_id)
        visiting.remove(addon_id)
        done.add(addon_id)
    for addon_id, node in nodes.items():
        if not node.is_absent_optional_dependency and addon_id not in skipped:
            visit(addon_id)

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
    return FrozenManifestPlan(manifest, nodes, tuple(order), MappingProxyType(artifact_dependencies))


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

    @property
    def executable_install_order(self) -> Tuple[AddonCaptureNode, ...]:
        return self.strict_plan.executable_install_order


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
        if row is not None and row.recoverability is Recoverability.PLATFORM_PROVIDED:
            raise FrozenInstallValidationError(
                f"platform-provided add-on cannot be skipped: {addon_id}"
            )
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
        row.addon_id for row in summary.addons
        if not row.exact_artifact_available
        and row.recoverability is not Recoverability.PLATFORM_PROVIDED
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
        if row.recoverability is Recoverability.PLATFORM_PROVIDED:
            kind = FrozenPlanActionKind.PLATFORM_PROVIDED
        elif row.exact_artifact_available:
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
    platform_versions: Optional[Mapping[str, str]] = None,
) -> Tuple[str, ...]:
    """Require repository-current ZIP dependencies to fit the captured plan.

    A platform-provided dependency is checked against its verified target version,
    never its captured observation, and it fails closed when none was verified.
    """
    try:
        from resources.lib.addon_zip import validated_root
        xml_bytes = validated_root(package.zip_bytes, package.addon_id, package.version).xml_bytes
        from resources.lib.dependencies import _is_system_dependency, _dependency_version_satisfies
        requirements = _admission_dependency_edges(xml_bytes, package.addon_id)
    except Exception as exc:
        raise FrozenInstallValidationError(
            "repository package dependency metadata is invalid"
        ) from exc
    dependencies = []
    for requirement in requirements:
        if _is_system_dependency(requirement.addon_id):
            if requirement.optional:
                continue
            versions = getattr(platform_versions, "builtin_versions", {})
            abis = getattr(platform_versions, "builtin_abis", {})
            version, abi = versions.get(requirement.addon_id), abis.get(requirement.addon_id)
            if (not version or not abi or not _builtin_version_satisfies(version, abi)
                    or not _builtin_version_satisfies(version, requirement.min_version)
                    or (requirement.min_version and not _builtin_version_satisfies(requirement.min_version, abi))):
                raise FrozenInstallValidationError("repository package requires an unverified builtin minimum")
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
        if dependency.platform_provided:
            verified = (platform_versions or {}).get(requirement.addon_id)
            if verified is None:
                if requirement.optional:
                    continue
                raise FrozenInstallValidationError(
                    f"repository package requires unverified platform dependency {requirement.addon_id}"
                )
            if requirement.min_version and not _strict_version_satisfies(verified, requirement.min_version):
                if requirement.optional:
                    continue
                raise FrozenInstallValidationError(
                    f"repository package requires a newer platform dependency {requirement.addon_id}"
                )
            if not requirement.optional:
                dependencies.append(requirement.addon_id)
            continue
        record = records.get(requirement.addon_id)
        version = (
            record.resolved_version if record and record.resolved_version
            else dependency.version
        )
        if requirement.min_version and not _dependency_version_satisfies(version, requirement.min_version):
            if requirement.optional:
                continue
            raise FrozenInstallValidationError(
                f"repository package requires a newer captured dependency {requirement.addon_id}"
            )
        if not requirement.optional:
            dependencies.append(requirement.addon_id)
    return tuple(sorted(set(dependencies)))


def stored_repository_dependencies(
    store, record, plan, records, skipped, *, platform_versions=None,
) -> Tuple[str, ...]:
    """Read an exact saved repository package and reconstruct installer semantics.

    Deterministic read-only helper shared by restart restoration and plan preview.
    No fetching, persistence, locks, runtime state, or Kodi mutation.
    """
    data = store.read_bytes(record.artifact_sha256)
    metadata = store.get_metadata(record.artifact_sha256)
    if (
        metadata.addon_id != record.addon_id
        or metadata.version != record.resolved_version
        or metadata.sha256 != record.artifact_sha256
        or metadata.size != record.artifact_size
        or len(data) != record.artifact_size
    ):
        raise FrozenInstallValidationError("durable resolved artifact identity is invalid")
    package = RepositoryPackage(
        record.addon_id, record.repository_id, record.resolved_version, data
    )
    return _repository_package_required_dependencies(
        package, plan, records, skipped, platform_versions=platform_versions,
    )


def _check_terminal_record(addon_id, record, node, row, policies, *, allow_uninstalled=False):
    """Rules a terminal resolution record must satisfy before it is trusted.

    Shared by restart restoration and prior-outcome reuse so the two cannot drift.
    """
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
    elif record.resolution is InstallResolution.SKIPPED:
        policy = effective_policy(addon_id, {item.addon_id: item for item in policies})
        if not policy.skip_allowed or record.state is not ResolutionState.SKIPPED:
            raise FrozenInstallValidationError("durable skip resolution is inconsistent")


class FrozenPlatformRequirementError(FrozenInstallValidationError):
    """A platform-provided Kodi add-on cannot be verified for this build (D-028)."""

    code = "PLATFORM_REQUIREMENT_UNSATISFIED"


def _platform_unsatisfied(message: str) -> FrozenPlatformRequirementError:
    return FrozenPlatformRequirementError(message)


def _builtin_satisfies(installer, edge) -> bool:
    """Authoritative Kodi evidence for a builtin minimum; anything less fails closed."""
    try:
        verifier = getattr(installer, "verify_builtin_requirement", None)
        if callable(verifier):
            return verifier(edge) is True
    except Exception:
        return False
    return False


def _canonical_artifact_edges(edges, addon_id):
    """Legacy edges may omit attribution; supplied attribution must name the owner.

    Keep each declaration and minimum (including conflicting ABI imports), rather
    than consolidating them into a strongest-minimum resolver approximation.
    """
    return sorted((e.addon_id, e.min_version, e.optional,
                   tuple(sorted(set(e.required_by or (addon_id,))))) for e in edges)


def _admission_dependency_edges(xml_bytes, addon_id):
    """Keep every import, including ABI-conflicting lower incoming minima.

    The general resolver's strongest-minimum consolidation is insufficient for
    interfaces with a backwards-compatible lower ABI bound.
    """
    return _parse_dependency_edges(xml_bytes, addon_id)


# Passive registration evidence is deliberately limited to this reviewed macOS
# build. It is not independent functional usability proof and never covers Python.
# xbmc.metadata (D-032) is an extension-point interface: Kodi types it UNKNOWN and
# omits it from JSON-RPC by design. Its pin proves registration, identity, origin
# and descriptor only.
_PASSIVE_BUILD = "20251031-a3a448d26b"
_PASSIVE_PLIST_SHA256 = "9f37ef7b63021ef2ab01b98a44f2f62c8eb68c3f61c014510cc3b7166450bcac"
_PASSIVE_BUILTINS = MappingProxyType({
    "xbmc.core": ("0.1.0", "0.1", "e38ace50afe6e15b918fa51038504fc11888038671bdacac2521af931b538a6f"),
    "xbmc.gui": ("5.17.0", "5.17.0", "7d8602ff6510bbb5ae8098d60c563c4e82c5f0b682220aad297982c9e116e6bb"),
    "kodi.resource": ("1.0.0", "1.0", "dd54ff32f0920d4fe68bff14c1a51311ac8f31e639fbbe7123a16905901b06f3"),
    "xbmc.metadata": ("2.1.0", "1.0", "95082198599c695a91d2aefb072f0457e9ffd5eb3f2dc1587fa58159750db1b6"),
})


@dataclass(frozen=True)
class _PinnedPassiveMetadata(InstalledMetadata):
    """Nonserialized native grant, issued only after the complete pinned read."""
    addon_id: str
    build: str


def _builtin_metadata_edges(metadata, addon_id):
    # Only the native-bound exact core descriptor receives this interpretation.
    # Managed/repository/capture XML always uses the unchanged general parser.
    if (addon_id == "xbmc.core" and isinstance(metadata, _PinnedPassiveMetadata)
            and metadata.addon_id == addon_id and metadata.build == _PASSIVE_BUILD
            and metadata.origin is InstalledOrigin.APPLICATION
            and hashlib.sha256(metadata.xml_bytes).hexdigest() == _PASSIVE_BUILTINS[addon_id][2]):
        return ()
    return _admission_dependency_edges(metadata.xml_bytes, addon_id)


def _native_process_executable():
    """Kernel path of this process, never argv[0], sys.executable or a Kodi label."""
    if sys.platform != "darwin":
        raise ValueError("unsupported passive builtin platform")
    import ctypes
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    query = lib.proc_pidpath
    query.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    query.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(4096)
    count = query(os.getpid(), buffer, len(buffer))
    if count <= 0 or count >= len(buffer) or len(buffer.value) != count:
        raise ValueError("unverifiable native executable")
    return buffer.value.decode('utf-8', 'strict')


def _planned_versions(plan, records) -> Dict[str, str]:
    """Managed versions the build will leave installed, resolved where a record already knows them."""
    by_id = records if isinstance(records, Mapping) else {record.addon_id: record for record in records}
    versions: Dict[str, str] = {}
    for node in plan.manifest.addons:
        if node.system or node.platform_provided or node.is_absent_optional_dependency:
            continue
        record = by_id.get(node.addon_id)
        versions[node.addon_id] = (
            record.resolved_version if record is not None and record.resolved_version else node.version
        )
    return versions


def _repository_required_addon_ids(store, records=(), *, packages=()):
    """Mandatory package edges can promote optional source observations to requirements."""
    items = records.values() if isinstance(records, Mapping) else records
    payloads = [(package.addon_id, package.zip_bytes, package.version) for package in packages]
    payloads.extend((record.addon_id, store.read_bytes(record.artifact_sha256), record.resolved_version)
                    for record in items
                    if record.resolution is InstallResolution.REPOSITORY_CURRENT
                    and record.artifact_sha256)
    required = RepositoryRequirements()
    from resources.lib.addon_zip import validated_root
    for addon_id, data, version in payloads:
        xml = validated_root(data, addon_id, version).xml_bytes
        edges = tuple(edge for edge in _admission_dependency_edges(xml, addon_id) if not edge.optional)
        required.update(edge.addon_id for edge in edges)
        required.dependencies[addon_id] = edges
    return required


class RepositoryRequirements(set):
    """Required IDs plus the actual package edges; never discard replacement minima."""
    def __init__(self):
        super().__init__()
        self.dependencies = {}


class VerifiedPlatformVersions(dict):
    """Verified observations plus required target edges for execution ordering."""
    def __init__(self):
        super().__init__()
        self.dependencies = {}
        self.builtin_versions = {}
        self.builtin_abis = {}
        self.builtin_identity = []


def _verify_builtin_closure(plan, installer, required, verified, target_edges, skipped):
    """Prove every incoming interface interval and target-declared builtin child.

    A Boolean verifier alone cannot bind identity/ABI/closure/freshness. The
    backend must additionally return metadata from its same trusted native
    validation path. No installed-details fallback grants authority.
    """
    import xml.etree.ElementTree as ET
    pending = []
    graph = {}
    for aid in required:
        node = plan.nodes.get(aid)
        if node is None or node.is_absent_optional_dependency or aid in skipped:
            raise _platform_unsatisfied("required dependency is missing from the build")
        if node.system:
            if not _is_system_dependency(aid):
                raise _platform_unsatisfied("unrecognized system classification")
        edges = tuple(node.dependency_edges) + tuple(target_edges.get(aid, ()))
        graph[aid] = {e.addon_id for e in edges if not e.optional}
        pending.extend(e for e in edges if not e.optional and _is_system_dependency(e.addon_id))
    # A disconnected system requirement still needs proof, but do not invent an
    # extra unspecified import for providers that already have real minima.
    referenced = {edge.addon_id for edge in pending}
    pending.extend(DependencyEdge(aid) for aid in required
                   if plan.nodes[aid].system and aid not in referenced)
    observations = {}
    checked = set()
    while pending:
        edge = pending.pop()
        aid = edge.addon_id
        key = (aid, edge.min_version)
        if key in checked:
            continue
        node = plan.nodes.get(aid)
        if node is None or not node.system or aid in skipped:
            raise _platform_unsatisfied("required builtin is missing or misclassified: " + aid)
        try:
            reader = getattr(installer, "read_verified_builtin_metadata", None)
            if not callable(reader) or not _builtin_satisfies(installer, edge):
                raise ValueError("unverified native provider")
            metadata = reader(edge)
            if not isinstance(metadata, InstalledMetadata) or metadata.origin is not InstalledOrigin.APPLICATION:
                raise ValueError("untrusted builtin origin")
            root = ET.fromstring(metadata.xml_bytes)
            version = root.get("version", "")
            _check_addon_xml_identity(metadata.xml_bytes, aid, version)
            floors = root.findall("backwards-compatibility")
            if len(floors) != 1:
                raise ValueError("missing or ambiguous ABI floor")
            abi = floors[0].get("abi", "")
            if (not abi or not _builtin_version_satisfies(version, abi)
                    or not _builtin_version_satisfies(version, edge.min_version)
                    or (edge.min_version and not _builtin_version_satisfies(edge.min_version, abi))):
                raise ValueError("incompatible interface interval")
            children = _builtin_metadata_edges(metadata, aid)
            if aid in ("xbmc.python", "xbmc.gui", "kodi.resource", "xbmc.metadata") and not any(
                    child.addon_id == "xbmc.core" and not child.optional for child in children):
                raise ValueError("missing mandatory core interface requirement")
            identity = (version, abi, hashlib.sha256(metadata.xml_bytes).hexdigest())
            if aid in observations and observations[aid] != identity:
                raise ValueError("builtin observation changed during verification")
            observations[aid] = identity
        except Exception as exc:
            raise _platform_unsatisfied("builtin remains UNVERIFIED or incompatible: " + aid) from exc
        checked.add(key)
        verified.builtin_versions[aid] = version
        verified.builtin_abis[aid] = abi
        graph.setdefault(aid, set()).update(e.addon_id for e in children if not e.optional)
        # The source graph retains incoming requirements but is not target proof.
        for child in tuple(children) + tuple(node.dependency_edges):
            if child.optional:
                continue
            if not _is_system_dependency(child.addon_id):
                raise _platform_unsatisfied("unsupported builtin dependency classification")
            pending.append(child)
    visiting, done = set(), set()
    def visit(aid):
        if aid in visiting:
            raise _platform_unsatisfied("builtin dependency graph contains a cycle")
        if aid in done:
            return
        if aid not in plan.nodes or plan.nodes[aid].is_absent_optional_dependency or aid in skipped:
            raise _platform_unsatisfied("required dependency is missing from the build")
        visiting.add(aid)
        for child in graph.get(aid, ()):
            visit(child)
        visiting.remove(aid)
        done.add(aid)
    for aid in graph:
        visit(aid)
    verified.builtin_identity = [
        [aid, *observations[aid], sorted(minimum for name, minimum in checked if name == aid)]
        for aid in sorted(observations)]


def verify_platform_requirements(
    plan,
    installer,
    *,
    planned_versions: Mapping[str, str],
    skipped: frozenset = frozenset(),
    resolutions: Mapping[str, object] = {},
    required_addon_ids: Sequence[str] = (),
) -> Dict[str, str]:
    """Verify every platform-provided node on the target. Read-only and fail-closed (D-028).

    Each platform node must be present, trusted application-origin, enabled,
    unbroken, of the captured type, identity-consistent, and parseable at a version
    that meets every incoming minimum. Its own trusted metadata must then be
    representable by the frozen plan: managed children at a satisfying planned
    version, platform children at their verified version, builtins by authoritative
    Kodi evidence. Only inspection methods are called. Returns each verified target
    version. Any uncertainty raises FrozenPlatformRequirementError.
    """
    platform_nodes = [node for node in plan.manifest.addons if node.platform_provided]
    for node in platform_nodes:
        if node.addon_id in resolutions:
            raise FrozenInstallValidationError(
                "a platform-provided add-on cannot have a resolution record"
            )
    required = {n.addon_id for n in plan.nodes.values()
                if not n.optional and n.addon_id not in skipped}
    required.update(aid for aid in required_addon_ids if aid in plan.nodes)
    required.update(aid for aid in getattr(required_addon_ids, "dependencies", {}) if aid in plan.nodes)
    pending = list(required)
    while pending:
        parent = plan.nodes[pending.pop()]
        for edge in parent.dependency_edges:
            if not edge.optional and edge.addon_id in plan.nodes and edge.addon_id not in required:
                required.add(edge.addon_id)
                pending.append(edge.addon_id)
    verified = VerifiedPlatformVersions()
    platform_nodes = [node for node in platform_nodes if node.addon_id in required]

    def promote(addon_ids):
        # Target metadata can require an optional managed observation. Close over
        # its captured mandatory descendants too, discovering platform nodes for
        # this same verification pass. Repeated promotions reach a fixed point.
        pending = list(addon_ids)
        while pending:
            aid = pending.pop()
            child = plan.nodes.get(aid)
            if child is None or child.is_absent_optional_dependency or aid in skipped:
                raise _platform_unsatisfied(
                    f"target dependency closure requires {aid}, which this build does not install")
            if child.system or aid in required:
                continue
            required.add(aid)
            if child.platform_provided:
                platform_nodes.append(child)
            pending.extend(edge.addon_id for edge in child.dependency_edges if not edge.optional)

    metadata_by_id: Dict[str, InstalledMetadata] = {}
    target_requirements = dict(getattr(required_addon_ids, "dependencies", {}))
    # Bind exact archive truth alongside replacement-package truth. A plan made
    # without artifact validation is not sufficient authority for a managed row.
    bound = plan.artifact_dependencies
    for node in plan.manifest.addons:
        if node.system or node.platform_provided or node.is_absent_optional_dependency or node.addon_id in skipped:
            continue
        exact_edges = None if bound is None else bound.get(node.addon_id)
        if exact_edges is None:
            record = resolutions.get(node.addon_id)
            if (record is None or record.resolution is not InstallResolution.REPOSITORY_CURRENT
                    or node.addon_id not in target_requirements):
                raise _platform_unsatisfied("exact artifact requirements are unavailable: " + node.addon_id)
        else:
            target_requirements[node.addon_id] = tuple(target_requirements.get(node.addon_id, ())) + tuple(exact_edges)

    for node in platform_nodes:
        addon_id = node.addon_id
        try:
            details = installer.get_addon_details(addon_id)
        except Exception:
            details = None
        if details is None:
            raise _platform_unsatisfied(f"{addon_id} is not installed on the target")
        try:
            metadata = installer.read_installed_metadata(addon_id)
        except Exception:
            metadata = None
        if metadata is None:
            raise _platform_unsatisfied(f"{addon_id} has no readable trusted metadata on the target")
        if metadata.origin is not InstalledOrigin.APPLICATION:
            raise _platform_unsatisfied(f"{addon_id} on the target is not the trusted application add-on")
        if details.broken or details.enabled is not True:
            raise _platform_unsatisfied(f"{addon_id} on the target is broken or disabled")
        try:
            _check_addon_xml_identity(metadata.xml_bytes, addon_id, details.version)
            declared = _declared_extension_points(metadata.xml_bytes, addon_id)
        except CaptureError as exc:
            raise _platform_unsatisfied(f"{addon_id} metadata does not describe the target add-on") from exc
        if node.addon_type not in declared:
            raise _platform_unsatisfied(f"{addon_id} on the target does not declare the captured add-on type")
        if not _strict_version_satisfies(details.version, ""):
            raise _platform_unsatisfied(f"{addon_id} on the target has an unverifiable version")
        verified[addon_id] = details.version
        metadata_by_id[addon_id] = metadata
        try:
            target_edges = _admission_dependency_edges(metadata.xml_bytes, addon_id)
        except CaptureError as exc:
            raise _platform_unsatisfied(f"{addon_id} on the target has unreadable dependency metadata") from exc
        target_requirements[addon_id] = tuple(target_requirements.get(addon_id, ())) + tuple(target_edges)
        verified.dependencies[addon_id] = tuple(
            edge.addon_id for edge in target_edges
            if not edge.optional and not _is_system_dependency(edge.addon_id))
        promote(edge.addon_id for edge in target_edges
                if not edge.optional and not _is_system_dependency(edge.addon_id))

    _verify_builtin_closure(plan, installer, required, verified, target_requirements, skipped)

    # All promotions are now known. A newly required managed parent can impose
    # a stricter captured minimum on a platform node already inspected above.
    for parent in plan.nodes.values():
        if parent.system or parent.is_absent_optional_dependency or parent.addon_id not in required:
            continue
        for edge in parent.dependency_edges:
            if not edge.optional and edge.addon_id in verified:
                if not _strict_version_satisfies(verified[edge.addon_id], edge.min_version):
                    raise _platform_unsatisfied(
                        f"{edge.addon_id} on the target does not satisfy the build's minimum")

    for node in platform_nodes:
        addon_id = node.addon_id
        try:
            target_edges = _admission_dependency_edges(metadata_by_id[addon_id].xml_bytes, addon_id)
        except CaptureError as exc:
            raise _platform_unsatisfied(f"{addon_id} on the target has unreadable dependency metadata") from exc
        for edge in target_edges:
            if edge.optional:
                continue
            if _is_system_dependency(edge.addon_id):
                continue  # All captured, target and replacement minima were checked above.

            planned = plan.nodes.get(edge.addon_id)
            if planned is None or planned.is_absent_optional_dependency or edge.addon_id in skipped:
                raise _platform_unsatisfied(
                    f"{addon_id} on the target requires {edge.addon_id}, which this build does not install"
                )
            if planned.platform_provided:
                version = verified[edge.addon_id]
            else:
                if planned.desired_enabled is not True:
                    raise _platform_unsatisfied(
                        f"{addon_id} on the target requires enabled managed dependency {edge.addon_id}")
                version = planned_versions.get(edge.addon_id, planned.version)
            if not _strict_version_satisfies(version, edge.min_version):
                raise _platform_unsatisfied(
                    f"{addon_id} on the target requires {edge.addon_id} {edge.min_version}, which this build does not provide"
                )
    # Target metadata contributes real graph edges, including cycles through managed nodes.
    graph = {n.addon_id: set(n.required_dependency_ids) for n in plan.nodes.values()
             if not n.system and not n.is_absent_optional_dependency and n.addon_id not in skipped}
    for aid, children in verified.dependencies.items():
        graph[aid].update(children)
    visiting, done = set(), set()
    def visit(aid):
        if aid in visiting:
            raise _platform_unsatisfied("target dependency graph contains a cycle")
        if aid in done or aid not in graph:
            return
        visiting.add(aid)
        for child in graph[aid]:
            visit(child)
        visiting.remove(aid)
        done.add(aid)
    for aid in graph:
        visit(aid)
    return verified


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

    def read_installed_metadata(self, addon_id: str) -> Optional[InstalledMetadata]:
        """Read-only trusted metadata for platform verification. No evidence means no proof."""
        return None

    def verify_builtin_requirement(self, edge: DependencyEdge) -> bool:
        """Provider-specific native registration/usability proof; unavailable by default."""
        return False

    def read_verified_builtin_metadata(self, edge: DependencyEdge) -> Optional[InstalledMetadata]:
        """Return fresh metadata only after the same native identity/usability proof.

        Origin must come from pinned application authority and a no-shadow read.
        XML/version/ABI presence alone is insufficient. Unsupported providers
        return None. The caller validates every interval and recursive import.
        """
        return None

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
        platform_metadata: Optional[Mapping[str, InstalledMetadata]] = None,
    ):
        self.installed = dict(installed or {})
        self.repository_packages = dict(repository_packages or {})
        self.platform_metadata = dict(platform_metadata or {})
        self.install_calls = []
        self.enable_calls = []
        self.artifacts = {}
        self.repository_calls = []

    def get_addon_details(self, addon_id: str) -> Optional[FrozenInstalledAddon]:
        return self.installed.get(addon_id)

    def read_installed_metadata(self, addon_id: str) -> Optional[InstalledMetadata]:
        return self.platform_metadata.get(addon_id)

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
        self._inventory_backend = None

    def close(self):
        if getattr(self, "_inventory_backend", None) is not None:
            self._inventory_backend.close()

    def __del__(self):
        self.close()

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

    def _application_addons_dir(self) -> Path:
        try:
            import xbmcvfs
            return Path(xbmcvfs.translatePath("special://xbmc/addons"))
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise FrozenInstallError("Kodi VFS module is unavailable") from exc

    def _inventory(self) -> KodiInventoryBackend:
        def result_rpc(method: str, params: dict) -> dict:
            response = self._rpc(method, params)
            if response.get("error") is not None:
                raise FrozenInstallError("Kodi refused add-on inventory")
            return response.get("result", {})

        if self._inventory_backend is None:
            addons_dir = self._addons_dir()
            self._inventory_backend = KodiInventoryBackend(
                result_rpc, addons_dir=addons_dir,
                package_cache_dir=addons_dir / "packages",
                application_addons_dir=self._application_addons_dir(),
            )
        return self._inventory_backend

    def read_installed_metadata(self, addon_id: str) -> Optional[InstalledMetadata]:
        """Trusted addon.xml through the same root authority that capture uses (D-028)."""
        return self._inventory().read_installed_metadata(addon_id)

    def verify_builtin_requirement(self, edge: DependencyEdge) -> bool:
        return self.read_verified_builtin_metadata(edge) is not None

    @contextmanager
    def _passive_build_binding(self, inventory):
        """Bind current kernel executable, compiled build and pinned bundle bytes.

        Hold the original bundle/plist/executable objects through native reads;
        reject substitution of any pathname or ancestor before issuing evidence.
        """
        if sys.platform != "darwin":
            raise ValueError("unsupported passive builtin platform")
        executable = _native_process_executable()
        path = Path(executable)
        if (not path.is_absolute() or os.path.normpath(executable) != executable or
                path.parts[-3:] != ('Contents', 'MacOS', 'Kodi') or
                path.parents[2].suffix != '.app'):
            raise ValueError("native executable is not a Kodi bundle")
        bundle = path.parents[2]
        if inventory.application_addons_dir != bundle/'Contents/Resources/Kodi/addons':
            raise ValueError("runtime application root is not the executing bundle")
        fds = []
        def directory(parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            fds.append(fd)
            return fd
        def regular(parent, name, limit=None):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            fds.append(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (limit is not None and info.st_size > limit):
                raise ValueError("unsafe build identity file")
            return fd
        def identity(fd):
            s = os.fstat(fd)
            return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        def compiled():
            value = self._rpc('Application.GetProperties', {'properties': ['version']})
            if value.get('error') is not None:
                raise ValueError("unavailable compiled Kodi identity")
            value = value.get('result', {}).get('version', {})
            if (type(value.get('major')) is not int or value['major'] != 21 or
                    type(value.get('minor')) is not int or value['minor'] != 3 or
                    value.get('revision') != _PASSIVE_BUILD or value.get('tag') != 'stable'):
                raise ValueError("unsupported compiled Kodi build")
            return (value['major'], value['minor'], value['revision'], value['tag'])
        try:
            root = _open_canonical_directory(bundle)
            fds.append(root)
            contents = directory(root, 'Contents')
            macos = directory(contents, 'MacOS')
            binary = regular(macos, 'Kodi')
            if not os.fstat(binary).st_mode & 0o111:
                raise ValueError("nonexecutable Kodi image")
            plist = regular(contents, 'Info.plist', 1024 * 1024)
            raw = os.read(plist, 1024 * 1024 + 1)
            if hashlib.sha256(raw).hexdigest() != _PASSIVE_PLIST_SHA256:
                raise ValueError("unsupported bundle descriptor")
            info = plistlib.loads(raw)
            if any(info.get(k) != v for k, v in {
                    'CFBundleIdentifier': 'org.xbmc.kodi', 'CFBundleShortVersionString': '21.3.',
                    'CFBundleVersion': _PASSIVE_BUILD, 'CFBundleExecutable': 'Kodi',
                    'CFBundlePackageType': 'APPL'}.items()):
                raise ValueError("wrong Kodi bundle identity")
            observations = tuple(identity(fd) for fd in (root, contents, macos, binary, plist))
            native = compiled()
            # The caller runs this inside the metadata reader's held-object
            # validation callback, before its final descriptor freshness check.
            def native_fresh():
                return compiled() == native and _native_process_executable() == executable
            yield native_fresh
            fresh_root = _open_canonical_directory(bundle)
            fds.append(fresh_root)
            fresh_contents = directory(fresh_root, 'Contents')
            fresh_macos = directory(fresh_contents, 'MacOS')
            fresh_binary = regular(fresh_macos, 'Kodi')
            fresh_plist = regular(fresh_contents, 'Info.plist', 1024 * 1024)
            if (tuple(identity(fd) for fd in (fresh_root, fresh_contents, fresh_macos,
                                             fresh_binary, fresh_plist)) != observations or
                    tuple(identity(fd) for fd in (root, contents, macos, binary, plist)) != observations or
                    os.read(fresh_plist, 1024 * 1024 + 1) != raw):
                raise ValueError("Kodi runtime/bundle identity changed")
        finally:
            for fd in reversed(fds):
                os.close(fd)

    def _read_passive_builtin(self, edge):
        """Pinned registration compatibility only; no independent API usability claim."""
        try:
            inventory = self._inventory()  # establish root authority before native callbacks
            import xbmcaddon
            import xml.etree.ElementTree as ET
            xbmc = self._xbmc()
            def enabled():
                return (xbmc.getCondVisibility('System.HasAddon(' + edge.addon_id + ')') is True
                        and xbmc.getCondVisibility('System.AddonIsEnabled(' + edge.addon_id + ')') is True)
            if not enabled():
                return None
            with self._passive_build_binding(inventory) as native_fresh:
                fields = ('id', 'version', 'path', 'type')
                addon = xbmcaddon.Addon(edge.addon_id)
                info = tuple(addon.getAddonInfo(k) for k in fields)
                expected_version, expected_abi, digest = _PASSIVE_BUILTINS[edge.addon_id]
                if (info[0] != edge.addon_id or info[1] != expected_version or info[3] != 'unknown'
                        or not _builtin_version_satisfies(info[1], edge.min_version)):
                    return None
                def validate(metadata):
                    if (metadata.origin is not InstalledOrigin.APPLICATION or
                            hashlib.sha256(metadata.xml_bytes).hexdigest() != digest):
                        return False
                    root = ET.fromstring(metadata.xml_bytes)
                    floors = root.findall('backwards-compatibility')
                    if (root.tag != 'addon' or root.get('id') != edge.addon_id or
                            root.get('version') != expected_version or len(floors) != 1 or
                            floors[0].get('abi') != expected_abi or
                            not _builtin_version_satisfies(expected_version, expected_abi) or
                            (edge.min_version and not _builtin_version_satisfies(edge.min_version, expected_abi))):
                        return False
                    fresh = xbmcaddon.Addon(edge.addon_id)
                    return (enabled() and tuple(fresh.getAddonInfo(k) for k in fields) == info
                            and native_fresh())
                metadata = inventory.read_application_builtin_metadata(edge.addon_id, info[2], validate=validate)
                if metadata is None:
                    return None
            return _PinnedPassiveMetadata(metadata.xml_bytes, metadata.origin, edge.addon_id, _PASSIVE_BUILD)
        except Exception:
            return None

    def read_verified_builtin_metadata(self, edge: DependencyEdge) -> Optional[InstalledMetadata]:
        """Prove the Python builtin using Kodi's enabled API and pinned application XML.

        Kodi 21's GetAddonDetails excludes extension-point builtins (type UNKNOWN).
        xbmcaddon.Addon instead requires an enabled registered add-on and exposes
        its actual identity/version/path. Executing here proves the Python runtime
        is usable. The XML's ABI floor additionally excludes incompatible Python
        API requirements; a Kodi release number or a dependent's declaration is
        never target evidence. The four allowlisted passive interfaces instead
        use pinned registration compatibility; that proves no independent API
        functional usability. Every other interface remains unverified.
        """
        if edge.addon_id in _PASSIVE_BUILTINS:
            return self._read_passive_builtin(edge)
        if edge.addon_id != "xbmc.python":
            return None
        try:
            inventory = self._inventory()
            import sys
            import xml.etree.ElementTree as ET
            import xbmcaddon

            if sys.version_info.major != 3:
                return None
            xbmc = self._xbmc()

            def usable():
                return (xbmc.getCondVisibility("System.HasAddon(xbmc.python)") is True
                        and xbmc.getCondVisibility("System.AddonIsEnabled(xbmc.python)") is True)

            if not usable():
                return None
            addon = xbmcaddon.Addon("xbmc.python")
            fields = ("id", "version", "path", "type")
            info = tuple(addon.getAddonInfo(key) for key in fields)
            addon_id, version, path, addon_type = info
            if (addon_id != edge.addon_id or addon_type != "unknown"
                    or not isinstance(version, str) or not version.startswith("3.")
                    or not _builtin_version_satisfies(version, edge.min_version)):
                return None
            def validate(metadata):
                if metadata is None or metadata.origin is not InstalledOrigin.APPLICATION:
                    return None
                _check_addon_xml_identity(metadata.xml_bytes, addon_id, version)
                root = ET.fromstring(metadata.xml_bytes)
                backwards = root.findall("backwards-compatibility")
                scripts = [point for point in root.findall("extension-point") if point.get("id") == "script"]
                if (root.tag != "addon" or len(backwards) != 1 or len(scripts) != 1
                        or scripts[0].get("schema") != "script.xsd" or root.findall("extension")):
                    return None
                abi = backwards[0].get("abi")
                if (not isinstance(abi, str) or not abi.startswith("3.")
                        or not _builtin_version_satisfies(version, abi)
                        or not _builtin_version_satisfies(edge.min_version, abi)):
                    return None
                fresh = xbmcaddon.Addon("xbmc.python")
                return usable() and tuple(fresh.getAddonInfo(key) for key in fields) == info

            return inventory.read_application_builtin_metadata(
                addon_id, path, validate=validate,
            )

        except Exception:
            return None

    def assert_mutable_target(self, addon_id):
        from resources.lib.platform_policy import PlatformMutationError
        metadata = self.read_installed_metadata(addon_id)
        if metadata is not None and metadata.origin is InstalledOrigin.APPLICATION:
            raise PlatformMutationError("execution cannot target platform-provided software")
        if metadata is not None and metadata.origin is InstalledOrigin.HOME:
            return
        # Reported paths can deny mutation, never grant trusted application authority.
        for item in self._inventory_backend.get_installed_addons():
            if item.get("addonid") != addon_id:
                continue
            path = item.get("path", "")
            application = str(self._inventory_backend.application_addons_dir)
            if isinstance(path, str) and (path.startswith("special://xbmc/addons/")
                    or path.startswith(application + "/")):
                raise PlatformMutationError("execution cannot target platform-provided software")
            if metadata is None:
                raise PlatformMutationError("installed mutation target has unverifiable origin")

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
        self.assert_mutable_target(addon_id)
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
        from resources.lib.addon_zip import publish_package
        try:
            publish_package(zip_bytes, addon_id, target, version)
            self._xbmc().executebuiltin("UpdateLocalAddons")
        except Exception as exc:
            raise FrozenInstallError(f"exact artifact installation failed for {addon_id}") from exc
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
        self.assert_mutable_target(addon_id)
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
        return self.outcome in {"complete", "superseded"}

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


def load_transaction_manifest(transaction, manifest_loader=_default_manifest_loader):
    """Reopen an exact durable source; never interpret a library as a path."""
    if getattr(transaction, "library_target", None) is not None:
        try:
            manifest = transaction.library_target.load()[1]
        except LibraryError as exc:
            raise FrozenInstallValidationError("library transaction source unavailable") from exc
        if (manifest.build_id != transaction.build_id
                or manifest.fingerprint() != transaction.manifest_fingerprint):
            raise FrozenInstallValidationError("library transaction content identity changed")
        return manifest
    return manifest_loader(transaction.manifest_path)


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

    def _transaction_profile(self, transaction):
        if transaction.library_target is not None:
            from resources.lib.resolver import resolve_manifest
            try:
                manifest, _, _ = transaction.library_target.load()
            except LibraryError as exc:
                raise FrozenInstallValidationError("library transaction profile unavailable") from exc
            return resolve_manifest(manifest, transaction.device_profile_id)
        return self._configuration_profile(
            transaction.configuration_manifest_path, transaction.device_profile_id
        )

    def install_target(
        self, target: LibraryInstallTarget, *,
        resolution_choices: Optional[Mapping[str, ResolutionChoice]] = None,
        interactive: bool = False,
        transaction_access: Optional[object] = None,
        prepared_resolution=None,
        prior_resolution=None,
    ) -> FrozenInstallResult:
        """Product entry point for an exact library selection reviewed by Plan.

        Source paths/loaders cannot be supplied in library mode. Policies come
        from the verified library profile. Approved resolution_choices retain normal
        frozen-install semantics; omitted approved choices never prompt implicitly.
        """
        if not isinstance(target, LibraryInstallTarget):
            return FrozenInstallResult("failed", code="LIBRARY_TARGET_INVALID",
                                       message="library install target is invalid")
        return self.install(None, manifest_path="", device_profile_id=target.device_profile_id,
                            library_target=target,
                            resolution_choices=resolution_choices, interactive=interactive,
                            transaction_access=transaction_access,
                            prepared_resolution=prepared_resolution,
                            prior_resolution=prior_resolution)

    def install_prepared(self, target, review, *, plan_service=None):
        """Standalone continuation: present Plan preview, obtain fresh approval,
        then pass that exact target/review. Preparation alone is not approval.
        """
        from resources.lib.plan import PlanTarget
        if not isinstance(target, PlanTarget) or target.standalone_source is None:
            return FrozenInstallResult("failed", code="STANDALONE_TARGET_INVALID")
        return self.install(None, manifest_path=target.software_manifest_path,
            configuration_manifest_path=target.configuration_manifest_path,
            device_profile_id=target.device_profile_id,
            install_policies=target.standalone_source.policies,
            resolution_choices={a: ResolutionChoice(c.value) for a, c in target.choices},
            prepared_resolution=target.prepared_resolution, interactive=False,
            standalone_target=target, review=review, plan_service=plan_service)

    def _bind_prior_resolution(
        self, library, library_target, device_profile_id, manifest, policies, plan,
        resolution_choices, prepared_resolution, prior_resolution,
    ):
        """Bind a prior accepted terminal outcome to this exact applied library target.

        Returns ``(records, fingerprint)``. The prior outcome is evidence of what was
        accepted before. It is never permission to fetch a newer package: a recorded
        repository package is reused only as its exact saved bytes, and nothing here
        queries a repository. Every check runs before the first mutation.
        """
        from resources.lib.build_identity import IdentityMismatch, bind_resolutions
        if library_target is None or prepared_resolution is not None:
            raise FrozenPriorResolutionError("a prior resolution needs a library target and no preparation")
        if not isinstance(prior_resolution, FrozenInstallResolutionManifest):
            raise FrozenPriorResolutionError("prior resolution is not a resolution manifest")
        try:
            records = bind_resolutions(manifest.build_id, manifest, prior_resolution, policies=policies)
        except IdentityMismatch as exc:
            raise FrozenPriorResolutionError("prior resolution does not bind to this build") from exc
        fingerprint = prior_resolution.resolution_fingerprint
        applied = library.current_applied_association() if library is not None else None
        if (applied is None or applied.entry_id != library_target.source.entry_id
                or applied.device_profile_id != device_profile_id
                or applied.resolution_fingerprint != fingerprint):
            raise FrozenPriorResolutionError("prior resolution is no longer the applied association")
        if resolution_choices and set(resolution_choices) & {record.addon_id for record in records}:
            raise FrozenPriorResolutionError("a recorded outcome cannot also be answered")
        rows = {row.addon_id: row for row in plan.summary.addons}
        for record in records:
            row = rows.get(record.addon_id)
            if row is None or record.addon_id not in plan.nodes:
                raise FrozenPriorResolutionError("prior resolution names an add-on outside this build")
            node = plan.nodes[record.addon_id]
            _check_terminal_record(record.addon_id, record, node, row, policies)
            current = self.installer.get_addon_details(record.addon_id)
            if record.resolution is InstallResolution.SKIPPED:
                if current is not None:
                    raise FrozenPriorResolutionError("a recorded skip is now installed")
                continue
            # Replacing a different installed version or repairing a broken add-on is G6,
            # which stays blocked. A matching healthy add-on needs no software change.
            target_version = record.resolved_version or node.version
            if current is not None and (current.broken or current.version != target_version):
                raise FrozenPriorResolutionError("an installed managed add-on differs from the recorded outcome")
        return tuple(sorted(records, key=lambda item: item.addon_id)), fingerprint

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
        fingerprint = resolution_fingerprint(records)
        if all(record.state in (ResolutionState.INSTALLED, ResolutionState.SKIPPED) for record in records):
            resolved_fingerprint = resolved_software_fingerprint(manifest, records)
            fingerprint = self._make_resolution_manifest(manifest, transaction, records).resolution_fingerprint
        return self.store.transition_expected(
            transaction_id=transaction.transaction_id,
            expected_phase=transaction.phase,
            new_phase=transaction.phase,
            resolution_records=records,
            resolution_fingerprint_value=fingerprint,
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
        verified_platform = set()
        pending = list(repository_ids)
        while pending:
            addon_id = pending.pop()
            if addon_id in required:
                continue
            node = plan.nodes.get(addon_id)
            if node is None or node.system or node.is_absent_optional_dependency:
                raise FrozenInstallValidationError("captured repository prerequisite is unavailable")
            if node.platform_provided:
                # Verified against the target, never installed; its managed children still install first.
                if addon_id not in verified_platform:
                    verified_platform.add(addon_id)
                    for edge in node.dependency_edges:
                        if not edge.optional and edge.addon_id in plan.nodes and not plan.nodes[edge.addon_id].system:
                            pending.append(edge.addon_id)
                continue
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
        platform_ids = {node.addon_id for node in plan.install_order if node.platform_provided}
        if platform_ids.intersection(held):
            raise FrozenInstallValidationError(
                "a platform-provided add-on cannot be held or disabled"
            )
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
        transaction_access: Optional[object] = None,
        library_target: Optional[LibraryInstallTarget] = None,
        resolution_choices: Optional[Mapping[str, ResolutionChoice]] = None,
        prepared_resolution=None,
        prior_resolution=None,
        standalone_target=None,
        review=None,
        plan_service=None,
    ) -> FrozenInstallResult:
        configuration_runner = self.configuration_runner
        from resources.lib.capture_lifecycle import require_no_capture
        try:
            require_no_capture(self.store.root)
        except Exception:
            return FrozenInstallResult("failed", code="CAPTURE_LIFECYCLE_BLOCKED",
                                       message="capture lifecycle prevents frozen installation")
        try:
            from resources.lib.build_library import authoritative_build_library
            pending_approval = self.store.inspect()
            if pending_approval is not None and pending_approval.skin_approval is not None:
                return FrozenInstallResult("needs_attention", transaction=pending_approval,
                    code="SKIN_APPROVAL_PROTOCOL_PENDING",
                    message="skin approval protocol is not executable through ordinary install")
            try:
                library = authoritative_build_library()
            except Exception:
                if library_target is not None:
                    raise
                library = None  # standalone offline callers have no Kodi library
            if library is not None and library.pending_publication() is not None:
                return FrozenInstallResult("needs_attention", code="APPLIED_PUBLICATION_PENDING",
                                           message="completed association publication requires recovery")
            if library_target is not None:
                if (not isinstance(library_target, LibraryInstallTarget)
                        or device_profile_id != library_target.device_profile_id
                        or manifest_path or configuration_manifest_path):
                    raise FrozenInstallValidationError("library install identity is invalid")
                # Source conflicts can be rejected without opening the incoming
                # content, including a selector with an unauthoritative root.
                active_source = self._safe_inspect()
                if active_source is not None and (
                    active_source.library_target != library_target
                    or active_source.device_profile_id != device_profile_id
                ):
                    return FrozenInstallResult(
                        "failed", transaction=active_source,
                        code="ACTIVE_TRANSACTION_CONFLICT",
                        message="another frozen lifecycle transaction is active",
                    )
                from resources.lib.resolver import resolve_manifest
                public, loaded_frozen, library_loader = library_target.load()
                if manifest is not None and manifest.fingerprint() != loaded_frozen.fingerprint():
                    raise FrozenInstallValidationError("library install frozen manifest differs")
                manifest = loaded_frozen
                desired_profile = resolve_manifest(public, device_profile_id)
                if configuration_runner is None:
                    from resources.lib.restart_coordinator import RestartCoordinator
                    configuration_runner = RestartCoordinator().reconcile
            elif standalone_target is not None:
                from resources.lib.repository_preparation import _load_target
                from resources.lib.plan import BuildPlanService, default_plan_owners
                if (standalone_target.library_source is not None
                        or standalone_target.device_profile_id != device_profile_id
                        or standalone_target.software_manifest_path != manifest_path
                        or standalone_target.configuration_manifest_path != configuration_manifest_path):
                    raise FrozenInstallValidationError("standalone source differs")
                standalone_source, desired_profile, manifest, library_loader = _load_target(standalone_target)
                if (prepared_resolution != standalone_target.prepared_resolution
                        or resolution_choices != {a: ResolutionChoice(c.value)
                                                  for a, c in standalone_target.choices}
                        or tuple(install_policies or ()) != standalone_source.policies
                        or prior_resolution is not None):
                    raise FrozenInstallValidationError("standalone execution differs from the reviewed target")
                if standalone_source.configuration_manifest_path is None:
                    configuration_runner = None
                elif configuration_runner is None:
                    return FrozenInstallResult("failed", code="CONFIGURATION_RUNNER_REQUIRED",
                        message="standalone configuration requires its existing configuration/restart owner")
                if plan_service is None:
                    owners = default_plan_owners()
                    plan_service = BuildPlanService(replace(owners, artifact_store=self.artifact_store,
                                                           platform_backend=self.installer))
                if not isinstance(plan_service, BuildPlanService) or not plan_service.validate(standalone_target, review).is_current:
                    return FrozenInstallResult("failed", code="REVIEW_REQUIRED",
                        message="prepare and freshly review the actual package versions before Apply")
            else:
                desired_profile = self._configuration_profile(configuration_manifest_path, device_profile_id)
            if resolution_choices is not None:
                if (not isinstance(resolution_choices, Mapping)
                        or any(not isinstance(key, str) or not isinstance(choice, ResolutionChoice)
                               for key, choice in resolution_choices.items())
                        or set(resolution_choices) - {node.addon_id for node in manifest.addons}
                        or set(resolution_choices) & {
                            node.addon_id for node in manifest.addons if node.platform_provided
                        }):
                    raise FrozenInstallValidationError("approved resolution choices are invalid")
                resolution_choices = dict(resolution_choices)
            policies = tuple(
                install_policies if install_policies is not None and library_target is None
                else getattr(desired_profile, "frozen_install_policies", ())
            )
            from resources.lib.platform_policy import reject_platform_mutations
            if desired_profile is not None:
                reject_platform_mutations(desired_profile, {
                    node.addon_id for node in manifest.addons if node.platform_provided})
            plan = validate_frozen_install_plan(
                manifest, self.artifact_store, policies
            )
            prepared_records = ()
            if prepared_resolution is not None:
                if library_target is None and standalone_target is None:
                    return FrozenInstallResult("failed", code="REVIEW_REQUIRED",
                        message="use install_prepared with the exact standalone target and fresh review")
                from resources.lib.repository_preparation import bind_prepared
                prepared_records = bind_prepared(
                    prepared_resolution, library_target.source if library_target else standalone_source, device_profile_id,
                    desired_profile, manifest, library_loader, self.artifact_store)
                if (resolution_choices is None or any(
                    resolution_choices.get(r.addon_id) is not ResolutionChoice.INSTALL_CURRENT
                    for r in prepared_records
                )):
                    raise FrozenInstallValidationError("preparation differs from approved choices")
            prior_records, prior_fingerprint = (
                self._bind_prior_resolution(
                    library, library_target, device_profile_id, manifest, policies, plan,
                    resolution_choices, prepared_resolution, prior_resolution,
                ) if prior_resolution is not None else ((), "")
            )
            hold_ids = self._activation_hold_ids(plan, desired_profile)
            if hold_ids and (not (configuration_manifest_path or library_target) or configuration_runner is None):
                raise FrozenInstallValidationError(
                    "pre-activation resources require a durable configuration runner"
                )
            session_id = _valid_uuid(self.session_id_provider(), "current_session_id")
        except (FrozenInstallError, FrozenResolutionError, CaptureError, ValueError, LibraryError) as exc:
            return FrozenInstallResult(
                "failed",
                code=getattr(exc, "code", "FROZEN_MANIFEST_INVALID"),
                message=("could not read or persist the frozen transaction"
                         if isinstance(exc, FrozenInstallPersistenceError)
                         else "frozen install plan validation failed"),
            )
        active = self._safe_inspect()
        if active is not None and any(
            r.resolution is InstallResolution.REPOSITORY_CURRENT and r.state is ResolutionState.SELECTED
            for r in active.resolution_records
        ):
            return FrozenInstallResult("needs_attention", transaction=active,
                code="LEGACY_REPOSITORY_PREPARATION_INCOMPLETE",
                message="legacy unprepared repository resolution requires explicit recovery; evidence retained")
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
                and active.library_target == library_target
                and active.device_profile_id == device_profile_id
                and active.prior_resolution_fingerprint == prior_fingerprint
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
                    and active.library_target == library_target
                    and (library_target is None or active.device_profile_id == device_profile_id)
                    and active.prior_resolution_fingerprint == prior_fingerprint
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
            if active_resume else {r.addon_id: r for r in (*prepared_records, *prior_records)}
        )
        rows = {row.addon_id: row for row in plan.summary.addons}
        effective = {policy.addon_id: policy for policy in policies}
        for node in plan.executable_install_order:
            if active_resume:
                break
            row = rows[node.addon_id]
            if node.addon_id in records:
                continue
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
            if (resolution_choices is not None and node.addon_id not in resolution_choices) or (
                resolution_choices is None and not interactive
            ):
                return FrozenInstallResult(
                    "user_resolution_required",
                    code="USER_RESOLUTION_REQUIRED",
                    message="interactive install resolution is required before this build can continue",
                    recoverability=plan.summary,
                )
            try:
                if resolution_choices is not None:
                    choice = resolution_choices[node.addon_id]
                else:
                    choice = (self.resolution_decider(prompt) if self.resolution_decider is not None
                              else _kodi_resolution_choice(prompt))
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
                if not policy.repository_fallback_allowed or not row.fallback_eligible:
                    return FrozenInstallResult("failed", code="FROZEN_RESOLUTION_NOT_PERMITTED",
                        message="repository resolution is not permitted for this add-on",
                        recoverability=plan.summary)
                return FrozenInstallResult("preparation_required", code="PREPARATION_REQUIRED",
                    message="use RepositoryPreparationService.prepare(target), review the prepared Plan, then install_prepared(target, review)",
                    recoverability=plan.summary)
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
        def validate_execution_material(checked_manifest, checked_desired, checked_policies):
            if any(r.resolution is InstallResolution.REPOSITORY_CURRENT
                   and (r.state is ResolutionState.SELECTED or not r.resolved_version or not r.artifact_sha256)
                   for r in records.values()):
                raise FrozenInstallValidationError("unprepared repository records require attention")
            if checked_desired is not None:
                reject_platform_mutations(checked_desired, {
                    node.addon_id for node in checked_manifest.addons if node.platform_provided})
            resolved_plan = validate_frozen_install_plan(
                checked_manifest, self.artifact_store, checked_policies, skipped=tuple(skipped)
            )
            from resources.lib.platform_policy import reject_backend_platform_targets
            reject_backend_platform_targets(self.installer, {
                n.addon_id for n in resolved_plan.executable_install_order})
            # Platform-provided requirements are verified read-only, before any transaction,
            # policy, hold, install or configuration step (D-028).
            platform_versions = verify_platform_requirements(
                resolved_plan.strict_plan, self.installer,
                planned_versions=_planned_versions(resolved_plan.strict_plan, records),
                skipped=frozenset(skipped), resolutions=records,
                required_addon_ids=_repository_required_addon_ids(self.artifact_store, records),
            )
            extra_dependencies = {
                aid: stored_repository_dependencies(
                    self.artifact_store, record, resolved_plan, records, skipped,
                    platform_versions=platform_versions,
                )
                for aid, record in records.items()
                if record.resolution is InstallResolution.REPOSITORY_CURRENT and record.resolved_version
            }
            extra_dependencies.update(platform_versions.dependencies)
            if extra_dependencies:
                resolved_plan = validate_frozen_install_plan(
                    checked_manifest, self.artifact_store, checked_policies, skipped=tuple(skipped),
                    extra_dependencies=extra_dependencies)
            hold_ids = self._activation_hold_ids(resolved_plan, checked_desired)
            if hold_ids and any(
                record.resolution is InstallResolution.REPOSITORY_CURRENT
                for record in records.values()
            ):
                raise FrozenInstallValidationError(
                    "pre-activation lifecycle requires exact dependency metadata"
                )
            self._check_private_ownership_compatibility(checked_desired, tuple(records.values()))
            if hold_ids:
                private_overlay_id, private_overlay_fingerprint, private_overlay_required = (
                    self._private_overlay_metadata(
                        checked_desired, checked_manifest.fingerprint()
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
            return (resolved_plan, hold_ids, private_overlay_id,
                    private_overlay_fingerprint, private_overlay_required)

        try:
            (resolved_plan, hold_ids, private_overlay_id, private_overlay_fingerprint,
             private_overlay_required) = validate_execution_material(manifest, desired_profile, policies)
        except FrozenPlatformRequirementError as exc:
            return FrozenInstallResult(
                "failed", code=exc.code,
                message="a Kodi-provided add-on required by this build does not satisfy it; nothing was changed",
                recoverability=plan.summary,
            )
        except Exception as exc:
            return FrozenInstallResult(
                "failed", code=getattr(exc, "code", "FROZEN_RESOLUTION_INVALID"),
                message="selected install resolutions are incompatible with the build graph or owned configuration",
                recoverability=plan.summary,
            )

        try:
            if library_target is not None:
                boundary_public, boundary_frozen, boundary_loader = library_target.load()
                boundary_desired = resolve_manifest(boundary_public, device_profile_id)
                if prepared_resolution is not None:
                    bind_prepared(prepared_resolution, library_target.source, device_profile_id,
                                  boundary_desired, boundary_frozen, boundary_loader, self.artifact_store)
                boundary_policies = tuple(boundary_desired.frozen_install_policies)
                if (boundary_frozen.fingerprint() != manifest.fingerprint()
                        or boundary_desired != desired_profile or boundary_policies != policies):
                    raise FrozenInstallValidationError("library execution identity changed")
                boundary_material = validate_execution_material(
                    boundary_frozen, boundary_desired, boundary_policies)
                if boundary_material != (resolved_plan, hold_ids, private_overlay_id,
                                         private_overlay_fingerprint, private_overlay_required):
                    raise FrozenInstallValidationError("resolved execution material changed")
            if standalone_target is not None:
                _, fresh_desired, fresh_manifest, fresh_loader = _load_target(standalone_target)
                if fresh_manifest != manifest or fresh_desired != desired_profile:
                    raise FrozenInstallValidationError("standalone source changed")
                if prepared_resolution is not None:
                    bind_prepared(prepared_resolution, standalone_source, device_profile_id,
                                  fresh_desired, fresh_manifest, fresh_loader, self.artifact_store)
                validate_execution_material(fresh_manifest, fresh_desired, policies)
                if not plan_service.validate(standalone_target, review).is_current:
                    return FrozenInstallResult("failed", code="REVIEW_REQUIRED")
            if active_resume:
                transaction = active
                original = transaction.original_update_policy
            else:
                original = AddonUpdatePolicy(self.policy_backend.get_policy())
                transaction = FrozenInstallTransaction(
                    transaction_id=str(uuid.uuid4()),
                    library_target=library_target,
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
                    prior_resolution_fingerprint=prior_fingerprint,
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
                # Post-restart continuation: verify only, never write.
                guard.verify_quarantined()
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

            plan = resolved_plan
            # Install only the exact repository and its exact required
            # prerequisites before querying a current package from that repo.
            repository_ids = {
                record.repository_id for record in records.values()
                if record.resolution is InstallResolution.REPOSITORY_CURRENT and not record.resolved_version
            }
            prelude_ids = self._repository_prerequisites(
                plan.strict_plan, repository_ids, records, rows
            ) if repository_ids else set()
            installed_ids = set()
            record_map = dict(records)
            for node in plan.executable_install_order:
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
            for node in plan.executable_install_order:
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

            # Recheck against the state that exists now, before any further install (D-028).
            platform_versions = verify_platform_requirements(
                plan.strict_plan, self.installer,
                planned_versions=_planned_versions(plan.strict_plan, record_map),
                skipped=skipped, resolutions=record_map,
                required_addon_ids=_repository_required_addon_ids(self.artifact_store, record_map),
            )
            extra_dependencies = {
                aid: stored_repository_dependencies(
                    self.artifact_store, record, plan, record_map, skipped,
                    platform_versions=platform_versions,
                )
                for aid, record in record_map.items()
                if record.resolution is InstallResolution.REPOSITORY_CURRENT and record.resolved_version
            }
            extra_dependencies.update(platform_versions.dependencies)
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

            for node in resolved_plan.executable_install_order:
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
            if configuration_runner is not None:
                request_path = configuration_manifest_path or manifest_path
                request = ReconcileRequest(
                    request_path,
                    device_profile_id,
                    library_target=library_target,
                    install_resolutions=tuple(sorted(
                        record_map.values(), key=lambda record: record.addon_id
                    )),
                    source_software_fingerprint=manifest.fingerprint(),
                    frozen_transaction_id=(transaction.transaction_id if hold_ids else ""),
                )
                if transaction_access is None:
                    result = configuration_runner(request)
                else:
                    result = configuration_runner(
                        request, transaction_access=transaction_access
                    )
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
        if any(r.resolution is InstallResolution.REPOSITORY_CURRENT
               and (r.state is ResolutionState.SELECTED or not r.resolved_version or not r.artifact_sha256)
               for r in records):
            raise FrozenInstallValidationError("legacy unprepared repository resolution requires attention")
        if not records:
            # Compatibility with BM-022 schema-1 transactions created before
            # explicit resolution records existed: those transactions were
            # exact-only and have already installed all exact packages.
            strict_plan = validate_frozen_manifest(manifest, self.artifact_store)
            records = tuple(
                replace(default_exact_record(node), state=ResolutionState.INSTALLED)
                for node in strict_plan.executable_install_order
            )
            plan = RecoverableFrozenInstallPlan(
                strict_plan,
                (),
                summarize_frozen_recoverability(manifest, self.artifact_store),
                install_plan_fingerprint(manifest, ()),
                tuple(FrozenPlanAction(FrozenPlanActionKind.INSTALL_EXACT_ARTIFACT, node.addon_id)
                      for node in strict_plan.executable_install_order),
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
            # Platform-provided rows are verified requirements and never carry a durable record.
            managed_ids = {
                addon_id for addon_id, row in rows.items()
                if row.recoverability is not Recoverability.PLATFORM_PROVIDED
            }
            if set(record_map) != managed_ids:
                raise FrozenInstallValidationError("durable resolutions do not cover captured add-ons")
            platform_versions = verify_platform_requirements(
                plan.strict_plan, self.installer,
                planned_versions=_planned_versions(plan.strict_plan, record_map),
                skipped=frozenset(skipped), resolutions=record_map,
                required_addon_ids=_repository_required_addon_ids(self.artifact_store, record_map))
            extra_dependencies = dict(platform_versions.dependencies)
            for addon_id, record in record_map.items():
                node = plan.nodes[addon_id]
                row = rows[addon_id]
                _check_terminal_record(
                    addon_id, record, node, row, policies, allow_uninstalled=allow_uninstalled
                )
                if record.resolution is InstallResolution.REPOSITORY_CURRENT:
                    extra_dependencies[addon_id] = stored_repository_dependencies(
                        self.artifact_store, record, plan, record_map, frozenset(skipped),
                        platform_versions=platform_versions,
                    )
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
            if (resolution_fingerprint(records) != transaction.resolution_fingerprint
                    and self._make_resolution_manifest(manifest, transaction, records).resolution_fingerprint
                    != transaction.resolution_fingerprint):
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
        # Resume re-verifies the target before anything else mutates (D-028).
        verify_platform_requirements(
            plan.strict_plan, self.installer,
            planned_versions=_planned_versions(plan.strict_plan, records),
            skipped=frozenset(
                record.addon_id for record in records
                if record.resolution is InstallResolution.SKIPPED
            ),
            resolutions={record.addon_id: record for record in records},
            required_addon_ids=_repository_required_addon_ids(self.artifact_store, records),
        )
        from resources.lib.platform_policy import reject_platform_mutations, reject_backend_platform_targets
        platform_ids = {n.addon_id for n in manifest.addons if n.platform_provided}
        if platform_ids and hasattr(transaction, "configuration_manifest_path"):
            desired = self._transaction_profile(transaction)
            if desired is not None:
                reject_platform_mutations(desired, platform_ids)
        if platform_ids:
            reject_backend_platform_targets(self.installer, {n.addon_id for n in plan.executable_install_order})
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

    def retry_held_quiescence(
        self,
        *,
        expected_transaction: FrozenInstallTransaction,
        current_session_id: Optional[str] = None,
        artifact_source_store: Optional[ArtifactStore] = None,
        restart_store=None,
    ) -> FrozenInstallResult:
        """Re-arm only the reviewed held quiescence failure and resume once.

        The caller must supply the complete snapshot it reviewed. Exact ZIPs
        are re-imported through ArtifactStore's validation path, and a locked
        full-snapshot CAS clears only the prior failure diagnostic before the
        existing post-restart continuation runs.
        """
        try:
            current = self.store.inspect()
        except Exception:
            return FrozenInstallResult(
                "needs_attention",
                transaction=expected_transaction,
                code="FROZEN_TRANSACTION_INSPECTION_FAILED",
                message="held frozen transaction could not be reloaded for retry",
            )
        if current is None:
            return FrozenInstallResult(
                "needs_attention",
                code="FROZEN_TRANSACTION_MISSING",
                message="held frozen transaction is unavailable for retry",
            )
        if current != expected_transaction or not _is_held_quiescence_retry_snapshot(current):
            return FrozenInstallResult(
                "needs_attention",
                transaction=current,
                code="FROZEN_HELD_RETRY_NOT_ELIGIBLE",
                message="held frozen transaction does not match the reviewed retry state",
            )

        try:
            provider_session = _valid_uuid(
                self.session_id_provider(), "current_session_id"
            )
            session = _valid_uuid(
                provider_session if current_session_id is None else current_session_id,
                "current_session_id",
            )
        except Exception:
            return FrozenInstallResult(
                "needs_attention",
                transaction=current,
                code="FROZEN_HELD_RETRY_SESSION_INVALID",
                message="current Kodi session identity could not be validated",
            )
        if session != provider_session:
            return FrozenInstallResult(
                "needs_attention",
                transaction=current,
                code="FROZEN_HELD_RETRY_SESSION_MISMATCH",
                message="retry session does not match the current Kodi session",
            )
        if session == current.originating_kodi_session_id:
            return FrozenInstallResult(
                "needs_attention",
                transaction=current,
                code="FROZEN_SAME_SESSION",
                message="held frozen retry requires a new Kodi session",
            )

        try:
            if restart_store is None:
                from resources.lib.transaction import TransactionStore
                restart_store = TransactionStore()
            if (
                os.path.realpath(restart_store.directory)
                != os.path.realpath(str(self.store.root))
            ):
                return FrozenInstallResult(
                    "needs_attention",
                    transaction=current,
                    code="BM020_TRANSACTION_PROFILE_MISMATCH",
                    message="BM-020 and frozen transactions do not share a profile store",
                )
            if not callable(getattr(restart_store, "locked_access", None)):
                return FrozenInstallResult(
                    "needs_attention",
                    transaction=current,
                    code="BM020_TRANSACTION_SERIALIZATION_UNAVAILABLE",
                    message="BM-020 transactions cannot be serialized with held retry",
                )
        except Exception:
            return FrozenInstallResult(
                "needs_attention",
                transaction=current,
                code="BM020_TRANSACTION_PROFILE_UNAVAILABLE",
                message="the shared BM-020 and frozen transaction store is unavailable",
            )

        try:
            AddonUpdateGuard(self.policy_backend).verify_quarantined()
        except Exception as exc:
            # Verify only: the held snapshot is left exactly as reviewed.
            return FrozenInstallResult(
                "needs_attention",
                transaction=current,
                code=getattr(exc, "code", "") or "FROZEN_UPDATER_STATE_UNAVAILABLE",
                message="NEVER_CHECK updater quarantine was not verified for held retry",
            )

        try:
            manifest = load_transaction_manifest(current, self.manifest_loader)
            if (
                manifest.build_id != current.build_id
                or manifest.fingerprint() != current.manifest_fingerprint
            ):
                raise FrozenInstallValidationError(
                    "held retry manifest identity changed"
                )

            source_store = artifact_source_store or self.artifact_store
            skipped = frozenset(r.addon_id for r in current.resolution_records
                                if r.resolution is InstallResolution.SKIPPED)
            verification_plan = _validate_frozen_manifest_core(
                manifest, source_store, skipped=skipped,
                recoverable_gaps=frozenset(r.addon_id for r in current.resolution_records
                    if r.resolution in (InstallResolution.REPOSITORY_CURRENT, InstallResolution.SKIPPED)))
            verify_platform_requirements(
                verification_plan, self.installer,
                planned_versions=_planned_versions(verification_plan, current.resolution_records),
                skipped=frozenset(r.addon_id for r in current.resolution_records
                                  if r.resolution is InstallResolution.SKIPPED),
                resolutions={r.addon_id: r for r in current.resolution_records},
                required_addon_ids=_repository_required_addon_ids(source_store, current.resolution_records))

            source_store = artifact_source_store or self.artifact_store
            for node in manifest.addons:
                if node.system or node.is_absent_optional_dependency or node.artifact is None:
                    continue
                data = source_store.read_bytes(node.artifact.sha256)
                metadata = self.artifact_store.import_zip(
                    data,
                    expected_addon_id=node.addon_id,
                    expected_version=node.version,
                    source="held-quiescence-retry",
                )
                if (
                    metadata.sha256 != node.artifact.sha256
                    or metadata.size != node.artifact.size
                ):
                    raise FrozenInstallValidationError(
                        "held retry artifact identity changed"
                    )

            plan, records, _resolution_manifest = self._restore_resolution(
                manifest, current, allow_uninstalled=True
            )
            if (
                not (current.configuration_manifest_path or current.library_target)
                or plan.install_plan_fingerprint != current.install_plan_fingerprint
            ):
                raise FrozenInstallValidationError(
                    "held retry configuration or plan identity changed"
                )
            desired_profile = self._transaction_profile(current)
            if desired_profile is None:
                raise FrozenInstallValidationError(
                    "held retry configuration profile is unavailable"
                )
            self._check_private_ownership_compatibility(desired_profile, records)
            held_ids = self._activation_hold_ids(plan, desired_profile)
            readiness_ids = self._registry_readiness_ids(desired_profile)
            if (
                held_ids != (_HELD_RETRY_OWNER_ID,)
                or readiness_ids != (_HELD_RETRY_OWNER_ID,)
                or not set(readiness_ids).issubset(held_ids)
            ):
                raise FrozenInstallValidationError(
                    "held retry activation graph changed"
                )
            overlay_identity = self._private_overlay_metadata(
                desired_profile, manifest.fingerprint()
            )
            if overlay_identity != (
                current.private_overlay_id,
                current.private_overlay_fingerprint,
                current.private_overlay_required,
            ):
                raise FrozenInstallValidationError(
                    "held retry private overlay identity changed"
                )

            owner_node = plan.nodes.get(_HELD_RETRY_OWNER_ID)
            owner_record = next(
                (item for item in records if item.addon_id == _HELD_RETRY_OWNER_ID),
                None,
            )
            if (
                owner_node is None
                or owner_node.artifact is None
                or owner_record is None
                or owner_record.resolution is not InstallResolution.EXACT
                or owner_record.captured_version != owner_node.version
                or owner_record.resolved_version != owner_node.version
                or owner_record.artifact_sha256 != owner_node.artifact.sha256
                or owner_record.artifact_size != owner_node.artifact.size
            ):
                raise FrozenInstallValidationError(
                    "held retry owner is not backed by its exact captured artifact"
                )
            expected_owner_version = owner_node.version

            if restart_store.inspect() is not None:
                return FrozenInstallResult(
                    "needs_attention",
                    transaction=current,
                    code="BM020_TRANSACTION_PRESENT",
                    message="a BM-020 restart transaction conflicts with held retry",
                )
        except Exception:
            return FrozenInstallResult(
                "needs_attention",
                transaction=current,
                code="FROZEN_HELD_RETRY_VALIDATION_FAILED",
                message="held retry manifest, plan, artifacts, or overlay failed validation",
            )

        def owner_is_healthy_and_disabled() -> bool:
            try:
                owner = self.installer.get_addon_details(_HELD_RETRY_OWNER_ID)
            except Exception:
                return False
            return bool(
                owner is not None
                and owner.addon_id == _HELD_RETRY_OWNER_ID
                and owner.version == expected_owner_version
                and not owner.broken
                and not owner.enabled
            )

        try:
            latest = self.store.inspect()
        except Exception:
            latest = None
        if (
            latest != current
            or not _is_held_quiescence_retry_snapshot(latest)
            or not owner_is_healthy_and_disabled()
        ):
            return FrozenInstallResult(
                "needs_attention",
                transaction=latest or current,
                code="FROZEN_HELD_RETRY_STATE_CHANGED",
                message="held transaction or disabled owner changed before retry",
            )
        try:
            # Keep the BM-020 store lock from the decisive absence check
            # through the continuation. Every BM-020 writer acquires this same
            # profile-local OS lock, so a restart transaction cannot appear
            # after this check and race the held retry.
            if restart_store.inspect() is not None:
                return FrozenInstallResult(
                    "needs_attention",
                    transaction=current,
                    code="BM020_TRANSACTION_PRESENT",
                    message="a BM-020 restart transaction conflicts with held retry",
                )
            with restart_store.locked_access() as transaction_access:
                restart_transaction = transaction_access.inspect()
                if restart_transaction is not None:
                    return FrozenInstallResult(
                        "needs_attention",
                        transaction=current,
                        code="BM020_TRANSACTION_PRESENT",
                        message="a BM-020 restart transaction conflicts with held retry",
                    )

                try:
                    latest = self.store.inspect()
                except Exception:
                    latest = None
                if (
                    latest != current
                    or not _is_held_quiescence_retry_snapshot(latest)
                    or not owner_is_healthy_and_disabled()
                ):
                    return FrozenInstallResult(
                        "needs_attention",
                        transaction=latest or current,
                        code="FROZEN_HELD_RETRY_STATE_CHANGED",
                        message="held transaction or disabled owner changed before retry",
                    )

                try:
                    rearmed = self.store.rearm_held_quiescence(current)
                except Exception:
                    return FrozenInstallResult(
                        "needs_attention",
                        transaction=self._safe_inspect() or current,
                        code="FROZEN_HELD_RETRY_CAS_FAILED",
                        message="held frozen transaction changed before retry could be armed",
                    )

                # The normal continuation owns software/configuration work and
                # all final private verification, activation release, updater
                # restore, and clear ordering. If interrupted here, startup
                # sees AWAITING_RESTART. The BM-020 lock remains held until it
                # returns or records a safe failure.
                try:
                    return self.resume_after_restart(
                        current_session_id=session,
                        transaction_access=transaction_access,
                    )
                except Exception:
                    return self._attention(
                        rearmed,
                        "FROZEN_HELD_RETRY_CONTINUATION_FAILED",
                        "held frozen retry continuation failed and requires attention",
                    )
        except Exception as exc:
            busy = getattr(exc, "code", "") == "TRANSACTION_LOCK_BUSY"
            return FrozenInstallResult(
                "needs_attention",
                transaction=self._safe_inspect() or current,
                code=(
                    "BM020_TRANSACTION_LOCK_BUSY"
                    if busy else "BM020_TRANSACTION_INSPECTION_FAILED"
                ),
                message=(
                    "BM-020 restart state is being changed and held retry was not continued"
                    if busy else "BM-020 restart state could not be serialized with held retry"
                ),
            )

    def resume_after_restart(
        self,
        *,
        current_session_id: Optional[str] = None,
        bm020_result: object = None,
        transaction_access: Optional[object] = None,
    ) -> FrozenInstallResult:
        try:
            pending_approval = self.store.inspect()
        except Exception:
            return FrozenInstallResult("needs_attention", code="FROZEN_TRANSACTION_UNREADABLE",
                message="frozen transaction identity could not be established")
        if pending_approval is not None and pending_approval.skin_approval is not None:
            return FrozenInstallResult("needs_attention", transaction=pending_approval,
                code="SKIN_APPROVAL_PROTOCOL_PENDING", message="fresh explicit approval is required")
        publication = recover_applied_publication(store=self.store, policy_backend=self.policy_backend)
        if publication is not None:
            return publication
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
            # Post-restart: verify only, never write (see update_guard).
            guard.verify_quarantined()
            manifest = load_transaction_manifest(transaction, self.manifest_loader)
            if transaction.lifecycle_stage is FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART:
                plan, records, _resolution_manifest = self._restore_resolution(
                    manifest, transaction, allow_uninstalled=True
                )
                desired_profile = self._transaction_profile(transaction)
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
                    library_target=transaction.library_target,
                    device_profile_id=transaction.device_profile_id,
                    configuration_manifest_path=transaction.configuration_manifest_path,
                    install_policies=transaction.policies,
                    interactive=False,
                    transaction_access=transaction_access,
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
        if transaction.skin_approval is not None:
            return FrozenInstallResult("needs_attention", transaction=transaction,
                code="SKIN_APPROVAL_EXPLICIT_CANCELLATION_REQUIRED",
                message="skin approval protocol cannot use ordinary abandon")
        if transaction.phase is FrozenInstallPhase.PUBLICATION_PENDING:
            return FrozenInstallResult(
                "needs_attention", transaction=transaction,
                code="PUBLICATION_CANNOT_BE_ABANDONED",
                message="durable publication ownership requires publication recovery")
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

    def _platform_recheck(
        self, transaction, plan, records, *, recoverability, resolution_manifest,
    ) -> Optional[FrozenInstallResult]:
        """Read-only platform check before success. A lost requirement fails closed; nothing is repaired (D-028)."""
        try:
            verify_platform_requirements(
                plan, self.installer,
                planned_versions=_planned_versions(plan, records),
                skipped=frozenset(
                    record.addon_id for record in records
                    if record.resolution is InstallResolution.SKIPPED
                ),
                resolutions={record.addon_id: record for record in records},
                required_addon_ids=_repository_required_addon_ids(self.artifact_store, records),
            )
        except FrozenPlatformRequirementError as exc:
            return self._attention(
                transaction, exc.code,
                "a Kodi-provided add-on no longer satisfies this build; Build Manager did not change it",
                recoverability=recoverability, resolution_manifest=resolution_manifest,
            )
        return None

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
        attention = self._platform_recheck(
            transaction, plan, records,
            recoverability=recoverability, resolution_manifest=resolution_manifest,
        )
        if attention is not None:
            return attention
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
        for node in plan.executable_install_order:
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
        for node in plan.executable_install_order:
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
        attention = self._platform_recheck(
            transaction, plan, records,
            recoverability=recoverability, resolution_manifest=resolution_manifest,
        )
        if attention is not None:
            return attention
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
            if transaction.library_target is not None:
                _sync_publication_storage(self.store)
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
        if transaction.library_target is not None:
            try:
                from resources.lib.build_library import BuildLibrary
                target = transaction.library_target
                library = BuildLibrary(target.source.root)
                transaction = self.store.transition_expected(
                    transaction_id=transaction.transaction_id,
                    expected_phase=FrozenInstallPhase.COMPLETE,
                    new_phase=FrozenInstallPhase.PUBLICATION_PENDING)
                publication = library._create_applied_publication(
                    transaction, resolution_store=self.store)
            except Exception:
                # The fence (or COMPLETE if fencing lost ownership) stays
                # recoverable. Never regress publication ownership to attention.
                return FrozenInstallResult(
                    "needs_attention", transaction=transaction,
                    code="APPLIED_ASSOCIATION_PERSISTENCE_FAILED",
                    message="completed association publication requires recovery",
                    recoverability=recoverability, resolution_manifest=resolution_manifest)
            result = recover_applied_publication(store=self.store, library=library,
                                                 publication=publication)
            return replace(result, recoverability=recoverability,
                           resolution_manifest=resolution_manifest)
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


def _sync_publication_storage(store):
    """Strict durability barrier for completion evidence and lifecycle cleanup."""
    from resources.lib.build_library import _directory
    with _directory(str(store.resolutions_dir)) as fd:
        os.fsync(fd)
    with _directory(str(store.root)) as fd:
        os.fsync(fd)


def recover_applied_publication(*, store=None, library=None, policy_backend=None, publication=None,
                                startup_observation=False):
    """Existing frozen owner finishes publication; stale snapshots never create."""
    from resources.lib.build_library import authoritative_build_library, LibraryInstallTarget, LibrarySource
    target = store or FrozenInstallStore()
    transaction = None

    def resolved(disposition, resolution=None):
        return FrozenInstallResult(
            disposition, resolution_manifest=resolution,
            code="APPLIED_PUBLICATION_SUPERSEDED" if disposition == "superseded" else "",
            message=("publication was superseded by completed authority" if disposition == "superseded"
                     else "completed build association publication recovered"))

    try:
        if library is None:
            try:
                library = authoritative_build_library()
            except Exception:
                transaction = target.inspect()
                if transaction is not None and transaction.library_target is not None:
                    raise
                return None
        observed = publication if publication is not None else library.publication_journal()
        transaction = target.inspect()
        acknowledged_without_owner = None
        if startup_observation and publication is None:
            if observed is not None:
                emit("startup.evidence.journal_present")
                if (observe_publication_roots(target, library, journal_present=True)
                        and observed.state == "acknowledged" and transaction is None):
                    acknowledged_without_owner = observed
            elif transaction is None:
                observe_publication_roots(target, library)
                emit("startup.evidence.journal_and_frozen_owner_absent")
        if publication is None and (observed is None or (
                observed.state == "acknowledged" and transaction is not None
                and transaction.transaction_id != observed.transaction_id)):
            if (transaction is None or transaction.phase not in {
                    FrozenInstallPhase.COMPLETE, FrozenInstallPhase.PUBLICATION_PENDING}
                    or transaction.library_target is None):
                # A retained terminal journal must not intercept another frozen
                # Install's active/restart owner. It is read-only terminal state.
                return None
            if (policy_backend or _default_policy_backend()).get_policy() != transaction.original_update_policy:
                raise FrozenInstallStateConflict("completed updater restoration is unverified")
            if transaction.library_target.source.root != library.root:
                raise FrozenInstallStateConflict("completed library authority changed")
            if transaction.phase is FrozenInstallPhase.COMPLETE:
                transaction = target.transition_expected(
                    transaction_id=transaction.transaction_id,
                    expected_phase=FrozenInstallPhase.COMPLETE,
                    new_phase=FrozenInstallPhase.PUBLICATION_PENDING)
            observed = library._create_applied_publication(transaction, resolution_store=target)
        disposition, current = library._validate_applied_publication(observed, resolution_store=target)
        if disposition != "current":
            return resolved(disposition)
        observed = current
        selector = LibraryInstallTarget(LibrarySource(library.root, observed.candidate.entry_id),
                                        observed.candidate.device_profile_id)
        selector.load()
        resolution = library._resolution(observed.candidate, target)
        _sync_publication_storage(target)
        # Revalidation of observed authority has no create-if-absent semantics.
        disposition, current = library._validate_applied_publication(observed, resolution_store=target)
        if disposition != "current":
            return resolved(disposition)
        observed = current
        transaction = target.inspect()
        if transaction is not None:
            if transaction.transaction_id != observed.transaction_id:
                if observed.state == "acknowledged":
                    return resolved("superseded")
                raise FrozenInstallStateConflict("publication transaction identity changed")
            if transaction.phase is FrozenInstallPhase.COMPLETE:
                transaction = target.transition_expected(
                    transaction_id=transaction.transaction_id,
                    expected_phase=FrozenInstallPhase.COMPLETE,
                    new_phase=FrozenInstallPhase.PUBLICATION_PENDING)
            if (transaction.transaction_id != observed.transaction_id
                    or transaction.phase is not FrozenInstallPhase.PUBLICATION_PENDING
                    or transaction.library_target != selector
                    or transaction.resolution_fingerprint != resolution.resolution_fingerprint
                    or transaction.resolved_software_fingerprint != resolution.resulting_software_fingerprint
                    or transaction.manifest_fingerprint != resolution.source_software_fingerprint
                    or transaction.install_plan_fingerprint != resolution.install_plan_fingerprint
                    or tuple(sorted(transaction.resolution_records, key=lambda r: r.addon_id)) != resolution.records):
                raise FrozenInstallStateConflict("publication does not match completed transaction")
        _sync_publication_storage(target)
        disposition = library._record_applied_completion(observed, resolution_store=target)
        if disposition == "complete" and transaction is not None:
            try:
                target._clear_publication_expected(transaction_id=observed.transaction_id,
                                                   publication=observed)
            except Exception:
                if target.inspect() is not None:
                    raise
            if target.inspect() is not None:
                # Another owner may already have finished and started new work.
                disposition, _ = library._validate_applied_publication(observed, resolution_store=target)
                if disposition == "current":
                    raise FrozenInstallStateConflict("publication lifecycle cleanup is incomplete")
        _sync_publication_storage(target)
        if (acknowledged_without_owner is not None and observed == acknowledged_without_owner
                and transaction is None and disposition == "complete"):
            observe_acknowledged_publication_completion(target, library, observed)
        return resolved(disposition, resolution if disposition == "complete" else None)
    except Exception:
        return FrozenInstallResult("needs_attention", transaction=transaction,
                                   code="APPLIED_ASSOCIATION_PERSISTENCE_FAILED",
                                   message="completed association publication requires recovery")


def ensure_frozen_install_guard(
    *,
    store: Optional[FrozenInstallStore] = None,
    policy_backend: Optional[UpdatePolicyBackend] = None,
    startup_observation: bool = False,
) -> FrozenStartupPrecondition:
    """Verify the updater quarantine before any BM-020 startup/resume work.

    Read-only: after a process restart Kodi must already have persisted
    ``NEVER_CHECK``. Any other state fails closed with no settings write, and
    the frozen transaction keeps its identity, lifecycle stage and activation
    hold while moving to NEEDS_ATTENTION.
    """
    target = store or FrozenInstallStore()
    try:
        from resources.lib.build_library import authoritative_build_library
        try:
            library = authoritative_build_library()
        except Exception:
            library = None
        if library is not None and library.pending_publication() is not None:
            return FrozenStartupPrecondition(False, code="APPLIED_PUBLICATION_PENDING",
                                             message="completed association publication requires recovery")
        transaction = target.inspect()
    except Exception:
        return FrozenStartupPrecondition(False, code="FROZEN_TRANSACTION_INSPECTION_FAILED", message="active frozen transaction could not be inspected")
    if transaction is None:
        if startup_observation:
            emit("startup.evidence.guard_frozen_owner_absent")
        return FrozenStartupPrecondition(True)
    if transaction.phase in {FrozenInstallPhase.COMPLETE, FrozenInstallPhase.PUBLICATION_PENDING} and transaction.library_target is not None:
        return FrozenStartupPrecondition(False, transaction, "APPLIED_PUBLICATION_PENDING",
                                         "completed association publication requires recovery")
    backend = policy_backend or _default_policy_backend()
    try:
        AddonUpdateGuard(backend).verify_quarantined()
    except Exception as exc:
        code = getattr(exc, "code", "") or "FROZEN_UPDATER_STATE_UNAVAILABLE"
        message = "NEVER_CHECK updater quarantine was not verified before startup resume"
        updated = transaction
        # An already-failed transaction keeps its original diagnostic.
        if transaction.phase is not FrozenInstallPhase.NEEDS_ATTENTION:
            try:
                updated = target.transition_expected(
                    transaction_id=transaction.transaction_id,
                    expected_phase=transaction.phase,
                    new_phase=FrozenInstallPhase.NEEDS_ATTENTION,
                    status_code=code,
                    status_message=message,
                )
            except Exception:
                updated = transaction
        return FrozenStartupPrecondition(False, updated, code, message)
    try:
        import xbmc
        # Wording is kept for the legacy harness, which greps for this marker.
        xbmc.log(
            "Build Manager BM-022 updater guard reasserted before BM-020 startup",
            xbmc.LOGINFO,
        )
    except (ImportError, AttributeError, RuntimeError):
        pass
    if transaction.phase is FrozenInstallPhase.NEEDS_ATTENTION:
        return FrozenStartupPrecondition(False, transaction, "FROZEN_NEEDS_ATTENTION", "frozen installation requires explicit recovery")
    return FrozenStartupPrecondition(True, transaction, message="frozen updater quarantine verified")


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
    backend = policy_backend or _default_policy_backend()

    def blocked(code: str, message: str) -> FrozenResumeRegistryReadiness:
        return FrozenResumeRegistryReadiness(False, code, message)

    try:
        if (getattr(restart_transaction, "request", None) != request
                or source_fingerprint != transaction.manifest_fingerprint
                or getattr(request, "manifest_path", "") != transaction.configuration_manifest_path
                or getattr(request, "library_target", None) != transaction.library_target
                or getattr(request, "device_profile_id", "") != transaction.device_profile_id
                or not getattr(preview, "success", False)
                or transaction.originating_kodi_session_id == current_session_id):
            return blocked("FROZEN_RESUME_IDENTITY_MISMATCH", "linked frozen resume identity differs")
        manifest = load_transaction_manifest(transaction, manifest_loader)
        coordinator = (coordinator_factory or FrozenInstallCoordinator)(
            store=target, artifact_store=artifact_store or ArtifactStore(
                default_frozen_install_root() / "frozen-artifacts"),
            policy_backend=backend, installer=KodiRuntimeFrozenArtifactBackend(),
            manifest_loader=manifest_loader)
        plan, records, _ = coordinator._restore_resolution(manifest, transaction)
    except Exception:
        return blocked("FROZEN_RESUME_IDENTITY_INVALID",
                       "frozen packages, requirements or resume identity failed revalidation")
    if not transaction.activation_hold_ids or transaction.activation_hold_released:
        return FrozenResumeRegistryReadiness(True)

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
        or getattr(request, "library_target", None) != getattr(transaction, "library_target", None)
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
        desired_profile = (
            coordinator._transaction_profile(transaction)
            if getattr(transaction, "library_target", None) is not None
            else coordinator._configuration_profile(
                transaction.configuration_manifest_path, transaction.device_profile_id
            )
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
    try:
        pending_approval = target.inspect()
    except Exception:
        # Preserve the legacy recovery result for unreadable/unsupported records.
        # No retry or continuation may consume uncertain transaction evidence.
        return FrozenInstallResult("needs_attention",
            code="APPLIED_ASSOCIATION_PERSISTENCE_FAILED",
            message="completed association publication requires recovery")
    if pending_approval is not None and pending_approval.skin_approval is not None:
        # Dormant protocol: never invoke a configuration runner, restart resume,
        # publication recovery, or policy setter. Phase and evidence survive.
        backend = policy_backend or _default_policy_backend()
        try:
            if pending_approval.skin_approval.phase == SKIN_CANCELLED:
                observed_policy = backend.get_policy()
                if not isinstance(observed_policy, AddonUpdatePolicy) or observed_policy != pending_approval.original_update_policy:
                    raise FrozenInstallStateConflict("cancelled policy mismatch")
            else:
                precondition = ensure_frozen_install_guard(store=target, policy_backend=backend)
                if not precondition.allowed and precondition.code != "FROZEN_NEEDS_ATTENTION":
                    raise FrozenInstallStateConflict("pending approval protection unverified")
            code = "SKIN_APPROVAL_PROTOCOL_PENDING"
        except Exception:
            code = "SKIN_APPROVAL_PROTECTION_UNVERIFIED"
        return FrozenInstallResult("needs_attention", transaction=pending_approval,
            code=code, message="skin approval state retained; no automatic continuation")
    publication = recover_applied_publication(store=target, policy_backend=policy_backend,
                                               startup_observation=True)
    if publication is not None:
        return publication
    transaction = target.inspect()
    if transaction is None:
        emit("startup.evidence.frozen_owner_absent_at_return")
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
    if any(r.resolution is InstallResolution.REPOSITORY_CURRENT and r.state is ResolutionState.SELECTED
           for r in transaction.resolution_records):
        return FrozenInstallResult("needs_attention", transaction=transaction,
            code="LEGACY_REPOSITORY_PREPARATION_INCOMPLETE",
            message="legacy unprepared repository resolution requires explicit recovery; evidence retained")
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
