"""Offline Create-only quiescence coordinator. No runtime/startup composition.

Confirmed request declarations and their digest are durable in the same atomic
record as the hold. No captured values, results, overlays or diagnostics are
persisted. Lifecycle COMPLETE does not mean a build has been registered.
Injected operations are trusted lifecycle capabilities, not UI
inputs. The restart verifier must prove a complete process restart; a changed
window-property UUID alone is insufficient.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from resources.lib.create_capture import CreateBuildRequest
from resources.lib.readonly_io import read_regular_file


class CaptureLifecycleError(Exception):
    code = "CAPTURE_LIFECYCLE_BLOCKED"

    def __init__(self):
        super().__init__(self.code)


class CapturePhase(str, Enum):
    PREPARING = "preparing"
    AWAITING_RESTART = "awaiting_restart"
    CAPTURING = "capturing"
    RESTORING = "restoring"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"


TERMINAL = frozenset({CapturePhase.COMPLETE, CapturePhase.CANCELLED, CapturePhase.FAILED})
FILENAME = "create_capture_transaction.json"


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError()


def request_fingerprint(request: CreateBuildRequest) -> str:
    if not isinstance(request, CreateBuildRequest):
        raise CaptureLifecycleError()
    # Re-run the accepted request validator, even for a caller-forged dataclass.
    try:
        replace(request)
        raw = json.dumps(asdict(request), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    except Exception:
        raise CaptureLifecycleError() from None


def _canonical_request_metadata(request):
    value = asdict(request)
    value["private_resources"] = [p.resource_id for p in request.private_resources]
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _request_metadata(request):
    """Only declared request fields, never capture results or private values."""
    request_fingerprint(request)
    raw = _canonical_request_metadata(request)
    if len(raw.encode()) > 12 * 1024:
        raise CaptureLifecycleError()
    # Round-trip through trusted constructors before granting durable authority.
    if _request_from_metadata(raw) != request:
        raise CaptureLifecycleError()
    return raw


def _request_from_metadata(raw):
    from resources.lib.create_capture import PublicCaptureSpecification, PublicSettingTarget
    from resources.lib.config import ConfigSettingType
    from resources.lib.manifest import PrivateSettingDeclaration, SettingTargetKind
    from resources.lib.redlight_resource import redlight_declaration, REDLIGHT_ADDON_ID
    try:
        if not isinstance(raw, str) or len(raw.encode()) > 12 * 1024:
            raise ValueError()
        value = json.loads(raw)
        if set(value) != set(CreateBuildRequest.__dataclass_fields__):
            raise ValueError()
        # Resource definitions come from the trusted catalog, not disk constructors.
        trusted = redlight_declaration()
        if value['private_resources'] != [trusted.resource_id]:
            raise ValueError()
        value['private_resources'] = (trusted,)
        value['root_addon_ids'] = tuple(value['root_addon_ids'])
        if REDLIGHT_ADDON_ID not in value['root_addon_ids']:
            raise ValueError()
        public = value['public_capture']
        if set(public) != {'settings', 'files'}:
            raise ValueError()
        value['public_capture'] = PublicCaptureSpecification(tuple(
            PublicSettingTarget(**{**item, 'setting_type': ConfigSettingType(item['setting_type']),
                'target_kind': SettingTargetKind(item['target_kind'])}) for item in public['settings']),
            tuple(public['files']))
        value['private_settings'] = tuple(PrivateSettingDeclaration(**{
            **item, 'target_kind': SettingTargetKind(item['target_kind'])})
            for item in value['private_settings'])
        request = CreateBuildRequest(**value)
        if _canonical_request_metadata(request) != raw:
            raise ValueError()
        return request
    except Exception:
        raise CaptureLifecycleError() from None


@dataclass(frozen=True)
class CaptureTransaction:
    operation_id: str
    phase: CapturePhase
    request_fingerprint: str
    owner_id: str
    owner_version: str
    original_enabled: bool
    originating_session_id: str
    created_at: float
    expires_at: float
    capture_session_id: str = ""
    outcome: str = ""
    request_metadata: str = field(default="", repr=False)

    def __post_init__(self):
        try:
            if self.request_metadata and request_fingerprint(_request_from_metadata(self.request_metadata)) != self.request_fingerprint:
                raise ValueError()
            if not isinstance(self.request_metadata, str):
                raise ValueError()
            _uuid(self.operation_id)
            _uuid(self.originating_session_id)
            if self.capture_session_id:
                _uuid(self.capture_session_id)
                if self.capture_session_id == self.originating_session_id:
                    raise ValueError()
            if not isinstance(self.phase, CapturePhase):
                raise ValueError()
            if not isinstance(self.request_fingerprint, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.request_fingerprint):
                raise ValueError()
            # Stage 1 admits only the audited resource owner/version.
            from resources.lib.redlight_resource import REDLIGHT_ADDON_ID, REDLIGHT_VERSION
            if self.owner_id != REDLIGHT_ADDON_ID or self.owner_version != REDLIGHT_VERSION:
                raise ValueError()
            if (type(self.original_enabled) is not bool or type(self.expires_at) not in (float, int)
                    or type(self.created_at) not in (float, int)):
                raise ValueError()
            if not 0 < self.created_at < self.expires_at <= self.created_at + 86400 < float("inf"):
                raise ValueError()
            if self.phase is CapturePhase.CAPTURING and not self.capture_session_id:
                raise ValueError()
            if self.outcome not in ("", "complete", "cancelled", "failed"):
                raise ValueError()
            if self.phase is CapturePhase.RESTORING and not self.outcome:
                raise ValueError()
            if self.phase in TERMINAL and self.outcome != self.phase.value:
                raise ValueError()
            if self.phase is CapturePhase.COMPLETE and not self.capture_session_id:
                raise ValueError()
            if self.phase in {CapturePhase.PREPARING, CapturePhase.AWAITING_RESTART} and self.capture_session_id:
                raise ValueError()
            if self.phase not in TERMINAL | {CapturePhase.RESTORING} and self.outcome:
                raise ValueError()
        except Exception:
            raise CaptureLifecycleError() from None

    @property
    def held(self):
        # Hold ownership and phase are one atomic record, never independent flags.
        return self.phase not in TERMINAL

    def to_dict(self):
        result = asdict(self)
        result["phase"] = self.phase.value
        return {"schema_version": 1, "operation_kind": "create_capture", **result}

    def safe_dict(self):
        return {"operation_id": self.operation_id, "phase": self.phase.value,
                "held": self.held, "outcome": self.outcome}

    @classmethod
    def from_dict(cls, value):
        try:
            fields = set(cls.__dataclass_fields__)
            if isinstance(value, dict) and "request_metadata" not in value:
                value = {**value, "request_metadata": ""}
            if (not isinstance(value, dict) or set(value) != fields | {"schema_version", "operation_kind"}
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1
                    or value["operation_kind"] != "create_capture"):
                raise ValueError()
            return cls(**{key: CapturePhase(value[key]) if key == "phase" else value[key] for key in fields})
        except Exception:
            raise CaptureLifecycleError() from None


class CaptureStore:
    """Separate capture authority with existing OS-lock and atomic-write primitives."""
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def path(self):
        return self.root / FILENAME

    def read(self):
        try:
            # Open every directory component without following links, including
            # ancestors. Reconstruction must neither create nor lock anything.
            absolute = self.root.absolute()
            # macOS exposes trusted temporary roots through these OS aliases.
            # Canonicalize only the fixed alias, never caller-owned components.
            for alias, target in (("/var", "/private/var"), ("/tmp", "/private/tmp")):
                if str(absolute).startswith(alias + "/") and Path(alias).is_symlink():
                    if os.readlink(alias) not in (target, target.lstrip("/")):
                        raise CaptureLifecycleError()
                    absolute = Path(target) / absolute.relative_to(alias)
            fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for component in absolute.parts[1:]:
                    try:
                        next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except FileNotFoundError:
                        return None
                    os.close(fd)
                    fd = next_fd
                raw = read_regular_file(FILENAME, limit=16 * 1024, dir_fd=fd)
            finally:
                os.close(fd)
            return None if raw is None else CaptureTransaction.from_dict(json.loads(raw))
        except Exception:
            raise CaptureLifecycleError() from None

    def reconstruct_request(self, operation_id, fingerprint, *, now):
        """Expiry-bound reconstruction for normal preparation/retry/capture."""
        return self._reconstruct_request(operation_id, fingerprint, now=now, recovery=False)

    def reconstruct_request_for_recovery(self, operation_id, fingerprint, *, now):
        """Read-only request recovery after expiry; grants no lifecycle authority.

        The explicit recover() transition must still validate current owner,
        competing transactions and restoration authority under operation locks.
        """
        return self._reconstruct_request(operation_id, fingerprint, now=now, recovery=True)

    def _reconstruct_request(self, operation_id, fingerprint, *, now, recovery):
        """Creation-free read; terminal COMPLETE carries no saved-build authority.

        Metadata is co-owned by the transaction, so there is no independent
        orphan to delete. Missing/legacy metadata remains retained and blocked.
        """
        record = self.read()
        if (record is None or record.operation_id != operation_id
                or record.request_fingerprint != fingerprint
                or not record.created_at <= now < (float("inf") if recovery else record.expires_at)
                or not record.request_metadata):
            raise CaptureLifecycleError()
        request = _request_from_metadata(record.request_metadata)
        if self.read() != record:
            raise CaptureLifecycleError()
        return request

    def locked(self):
        from resources.lib.transaction import TransactionLock
        return TransactionLock(str(self.root / "create_capture_transaction.lock"))

    def save(self, expected, record):
        """CAS under the capture lock held by the coordinator."""
        if not isinstance(record, CaptureTransaction) or self.read() != expected:
            raise CaptureLifecycleError()
        from resources.lib.frozen_install import write_lifecycle_record, FrozenInstallStore
        try:
            if len(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")).encode()) + 1 > 16 * 1024:
                raise ValueError()
            write_lifecycle_record(self.path, record.to_dict(), self.read,
                lambda: FrozenInstallStore(self.root, create=False)._fsync_directory_strict())
            if self.read() != record:
                raise ValueError()
        except Exception:
            # A replacement may already be durable. Retain it and its hold.
            raise CaptureLifecycleError() from None
        return record


def require_no_capture(root: Path):
    record = CaptureStore(root).read()
    if record is not None and record.held:
        raise CaptureLifecycleError()


def capture_activation_holds(root: Path):
    record = CaptureStore(root).read()
    if record is None or not record.held:
        return frozenset()
    # A competing record is a lifecycle breach, not another source of authority.
    from resources.lib.frozen_install import FrozenInstallStore
    try:
        if (FrozenInstallStore.read_snapshot(root) is not None
                or read_regular_file(str(Path(root) / "restart_transaction.json"), limit=128 * 1024) is not None):
            raise CaptureLifecycleError()
    except Exception:
        raise CaptureLifecycleError() from None
    return frozenset({record.owner_id})


class CaptureLifecycleCoordinator:
    """No Install/Apply, initializer, private-setting writer, or restart executor.

    operations exposes session_id(), owner_version(owner), enabled(owner),
    set_enabled(owner, bool), competing_operation(), and
    verify_restart(operation_id, old_session, new_session). All verification
    results must be exact booleans. Only set_enabled may mutate anything.
    """
    def __init__(self, *, store: CaptureStore, restart_store, operations, clock=time.time):
        self.store, self.restart_store, self.operations, self.clock = store, restart_store, operations, clock
        if Path(restart_store.directory) != store.root:
            raise CaptureLifecycleError()

    @contextmanager
    def _exclusive(self):
        from resources.lib.frozen_install import FrozenInstallStore
        frozen = FrozenInstallStore(self.store.root, create=False)
        try:
            # Hold both existing operation locks through callbacks and persistence.
            with self.store.locked(), frozen.locked(), self.restart_store.locked_inspection() as pending:
                if (pending is not None or FrozenInstallStore.read_snapshot(self.store.root) is not None
                        or self.operations.competing_operation() is not False):
                    raise CaptureLifecycleError()
                yield
        except Exception:
            raise CaptureLifecycleError() from None

    def reconstruct_request(self, operation_id, fingerprint):
        """Read-only reconstruction; no operations callbacks or locks."""
        return self.store.reconstruct_request(operation_id, fingerprint, now=self.clock())

    def reconstruct_request_for_recovery(self, operation_id, fingerprint):
        """Read-only recovery-purpose reconstruction, including expired requests."""
        return self.store.reconstruct_request_for_recovery(operation_id, fingerprint, now=self.clock())

    def _checked(self, operation_id, request, *, recovery=False):
        from resources.lib.frozen_install import FrozenInstallStore
        record = self.store.read()
        if (record is None or record.operation_id != operation_id
                or not record.request_metadata
                or record.request_metadata != _request_metadata(request)
                or record.request_fingerprint != request_fingerprint(request)
                or not record.created_at <= self.clock() < (float("inf") if recovery else record.expires_at)
                or self.operations.competing_operation() is not False
                or self.restart_store.read_snapshot() is not None
                or FrozenInstallStore.read_snapshot(self.store.root) is not None
                or self.operations.owner_version(record.owner_id) != record.owner_version):
            raise CaptureLifecycleError()
        return record

    def _session(self):
        session = self.operations.session_id()
        try:
            _uuid(session)
        except Exception:
            raise CaptureLifecycleError() from None
        return session

    def begin(self, request, *, confirmed: bool, lifetime_seconds=86400):
        """Persist restoration intent and hold before disabling. Always await restart."""
        if confirmed is not True:
            # A declined confirmation is not preparation: create no lock/state.
            raise CaptureLifecycleError()
        with self._exclusive():
            previous = self.store.read()
            if type(lifetime_seconds) not in (float, int) or not 0 < lifetime_seconds <= 86400:
                raise CaptureLifecycleError()
            if previous is not None and previous.held:
                record = self._checked(previous.operation_id, request)
                if record.originating_session_id != self._session():
                    raise CaptureLifecycleError()
                if record.phase is CapturePhase.AWAITING_RESTART:
                    if self.operations.enabled(record.owner_id) is not False:
                        raise CaptureLifecycleError()
                    return record
                if record.phase is not CapturePhase.PREPARING:
                    raise CaptureLifecycleError()
                return self._disable(record, request)
            from resources.lib.redlight_resource import REDLIGHT_ADDON_ID, REDLIGHT_VERSION, redlight_declaration
            if (request.private_resources != (redlight_declaration(),)
                    or REDLIGHT_ADDON_ID not in request.root_addon_ids
                    or self.operations.owner_version(REDLIGHT_ADDON_ID) != REDLIGHT_VERSION):
                raise CaptureLifecycleError()
            enabled = self.operations.enabled(REDLIGHT_ADDON_ID)
            now = self.clock()
            record = CaptureTransaction(str(uuid.uuid4()), CapturePhase.PREPARING,
                request_fingerprint(request), REDLIGHT_ADDON_ID, REDLIGHT_VERSION,
                enabled, self._session(), now, now + lifetime_seconds,
                request_metadata=_request_metadata(request))
            self.store.save(previous, record)
            return self._disable(record, request)

    def _disable(self, record, request):
        if self._checked(record.operation_id, request) != record or self._session() != record.originating_session_id:
            raise CaptureLifecycleError()
        enabled = self.operations.enabled(record.owner_id)
        if type(enabled) is not bool or (enabled and not record.original_enabled):
            raise CaptureLifecycleError()
        if enabled:
            self.operations.set_enabled(record.owner_id, False)
        if self.operations.enabled(record.owner_id) is not False:
            raise CaptureLifecycleError()
        return self.store.save(record, replace(record, phase=CapturePhase.AWAITING_RESTART))

    def _eligible(self, record, request, session):
        current = self._checked(record.operation_id, request)
        if (current != record or not current.held or self._session() != session
                or session == record.originating_session_id
                or self.operations.enabled(record.owner_id) is not False
                or capture_activation_holds(self.store.root) != frozenset({record.owner_id})
                or self.operations.verify_restart(record.operation_id, record.originating_session_id, session) is not True):
            raise CaptureLifecycleError()

    def capture(self, operation_id, request, read_capture):
        """Run a trusted read-only callback; never retain its private result on disk."""
        with self._exclusive():
            record = self._checked(operation_id, request)
            if record.phase is not CapturePhase.AWAITING_RESTART:
                raise CaptureLifecycleError()
            session = self._session()
            self._eligible(record, request, session)
            record = self.store.save(record, replace(record, phase=CapturePhase.CAPTURING, capture_session_id=session))
            # The callback receives a revalidation capability, not Install authority.
            def verify():
                self._eligible(record, request, session)
            try:
                result = read_capture(verify)
                verify()
            except Exception:
                self._eligible(record, request, session)
                self._restore(record, request, "failed")
                raise CaptureLifecycleError() from None
            self._restore(record, request, "complete")
            return result

    def recover(self, operation_id, request, *, cancelled=True):
        """Explicit cancellation/failure recovery, including interrupted restoration."""
        with self._exclusive():
            if type(cancelled) is not bool:
                raise CaptureLifecycleError()
            record = self._checked(operation_id, request, recovery=True)
            if record.phase in TERMINAL:
                if self.operations.enabled(record.owner_id) is not record.original_enabled:
                    raise CaptureLifecycleError()
                return record
            return self._restore(record, request, "cancelled" if cancelled is True else "failed", recovery=True)

    def _restore(self, record, request, outcome, *, recovery=False):
        current = self._checked(record.operation_id, request, recovery=recovery)
        if current != record or not record.held:
            raise CaptureLifecycleError()
        enabled = self.operations.enabled(record.owner_id)
        if type(enabled) is not bool:
            raise CaptureLifecycleError()
        # PREPARING may have crashed before disable; RESTORING may have crashed
        # after the owned enable. Explicit recovery also admits a verified
        # original-enabled no-op; capture completion never gains this authority.
        if enabled and (not record.original_enabled or record.phase not in {
                CapturePhase.PREPARING, CapturePhase.RESTORING} and not recovery):
            raise CaptureLifecycleError()
        if record.phase is not CapturePhase.RESTORING:
            record = self.store.save(record, replace(record, phase=CapturePhase.RESTORING, outcome=outcome))
        if enabled != record.original_enabled:
            self.operations.set_enabled(record.owner_id, record.original_enabled)
        if (self.operations.enabled(record.owner_id) is not record.original_enabled
                or self.operations.owner_version(record.owner_id) != record.owner_version
                or self.store.read() != record):
            raise CaptureLifecycleError()
        return self.store.save(record, replace(record, phase=CapturePhase(record.outcome)))
