"""Offline Create-only quiescence coordinator. No runtime/startup composition.

Confirmed request declarations and their digest are durable in the same atomic
record as the hold. No captured values, results, overlay contents or diagnostics are
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
import stat
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
    commit_pending: bool = False

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
            if type(self.commit_pending) is not bool or (self.commit_pending and self.phase not in TERMINAL):
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
        # Phase and commitment own the hold together in the same atomic record.
        return self.phase not in TERMINAL or self.commit_pending

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
            if isinstance(value, dict) and "commit_pending" not in value:
                value = {**value, "commit_pending": False}
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
        try:
            # Match TransactionStore's trusted profile translation, while keeping
            # the final state directory and every state file no-follow.
            self._source = Path(root).absolute()
            # A missing state suffix is normal; a dangling profile alias is not.
            for ancestor in self._source.parents:
                if ancestor.is_symlink():
                    ancestor.resolve(strict=True)
            self.root = self._source.parent.resolve() / self._source.name
            self._identities = {}
            self._held_locks = {}
            self._transition_fd = None
            with self._directory():
                pass
        except Exception:
            raise CaptureLifecycleError() from None

    @property
    def path(self):
        return self.root / FILENAME

    @contextmanager
    def _directory(self, *, create=False):
        """Pin canonical components; all IO is relative to the opened root.

        Existing components cannot disappear or change identity. Only a mutating
        transition may create missing directories; observation never creates.
        A trusted symlink spelling is resolved once, then checked for drift.
        """
        fd = None
        try:
            if self._source.parent.resolve() / self._source.name != self.root:
                raise CaptureLifecycleError()
            fd = os.open(self.root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for index, component in enumerate(self.root.parts[1:]):
                try:
                    next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    if index in self._identities:
                        raise CaptureLifecycleError()
                    if not create:
                        yield None
                        return
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                    next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                info = os.fstat(next_fd)
                identity = (info.st_dev, info.st_ino)
                previous = self._identities.setdefault(index, identity)
                if identity != previous:
                    os.close(next_fd)
                    raise CaptureLifecycleError()
                os.close(fd)
                fd = next_fd
            yield fd
        except Exception:
            raise CaptureLifecycleError() from None
        finally:
            if fd is not None:
                os.close(fd)

    def _validate_directory(self, fd):
        with self._directory() as current:
            if current is None or self._identity(os.fstat(current)) != self._identity(os.fstat(fd)):
                raise CaptureLifecycleError()
            for name, identity in self._held_locks.items():
                info = os.stat(name, dir_fd=current, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or self._identity(info) != identity:
                    raise CaptureLifecycleError()

    @staticmethod
    def _identity(info):
        return info.st_dev, info.st_ino

    def read(self):
        try:
            with self._directory() as fd:
                if fd is None:
                    return None
                raw = read_regular_file(FILENAME, limit=16 * 1024, dir_fd=fd)
                self._validate_directory(fd)
            return None if raw is None else CaptureTransaction.from_dict(json.loads(raw))
        except Exception:
            raise CaptureLifecycleError() from None

    def competing_records_present(self):
        """Validated no-follow reads; reuse the locked transition's root pin.

        No shared store construction, callbacks or lock acquisition occurs here.
        An observer pins the directory only for this read and creates nothing.
        Directory timestamps bound both reads against transient entry movement.
        Composition is single-threaded; the transition pin is not thread-local.
        """
        from resources.lib.frozen_install import FrozenInstallTransaction, _TRANSACTION_FILENAME
        from resources.lib.transaction import RestartTransaction, TRANSACTION_FILENAME

        def read(fd):
            if type(fd) is not int or fd < 0:
                raise CaptureLifecycleError()
            before = os.fstat(fd)
            if not stat.S_ISDIR(before.st_mode):
                raise CaptureLifecycleError()
            present = False
            for name, limit, record_type in (
                    (TRANSACTION_FILENAME, 128 * 1024, RestartTransaction),
                    (_TRANSACTION_FILENAME, 4 * 1024 * 1024, FrozenInstallTransaction)):
                raw = read_regular_file(name, limit=limit, dir_fd=fd)
                if raw is not None:
                    record_type.from_dict(json.loads(raw.decode("utf-8")))
                    present = True
            after = os.fstat(fd)
            if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
                raise CaptureLifecycleError()
            self._validate_directory(fd)
            return present

        try:
            transition_fd = self._transition_fd
            if transition_fd is not None:
                return read(transition_fd)
            with self._directory() as fd:
                return False if fd is None else read(fd)
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

    @contextmanager
    def _lock(self, fd, filename):
        # Same OS flock and filenames as the existing stores, but opening via
        # the pinned root prevents a path swap from redirecting the lock.
        import fcntl
        handle = os.open(filename, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o600, dir_fd=fd)
        try:
            if not stat.S_ISREG(os.fstat(handle).st_mode):
                raise CaptureLifecycleError()
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if filename in self._held_locks:
                raise CaptureLifecycleError()
            self._held_locks[filename] = self._identity(os.fstat(handle))
            try:
                self._validate_directory(fd)
                yield
            finally:
                del self._held_locks[filename]
        finally:
            os.close(handle)

    @contextmanager
    def locked(self):
        with self._directory(create=True) as fd:
            with self._lock(fd, "create_capture_transaction.lock"):
                yield

    def _sync_directory(self, fd):
        os.fsync(fd)

    def save(self, expected, record):
        """CAS under the capture lock held by the coordinator; pinned-root IO."""
        if not isinstance(record, CaptureTransaction) or self.read() != expected:
            raise CaptureLifecycleError()
        staged = None
        try:
            data = (json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode()
            if len(data) > 16 * 1024:
                raise ValueError()
            with self._directory() as fd:
                if fd is None:
                    raise CaptureLifecycleError()
                name = ".frozen-install." + str(uuid.uuid4()) + ".tmp"
                try:
                    handle = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                     0o600, dir_fd=fd)
                    staged = name
                    with os.fdopen(handle, "wb") as output:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    self._validate_directory(fd)
                    if self.read() != expected:
                        raise CaptureLifecycleError()
                    os.replace(staged, FILENAME, src_dir_fd=fd, dst_dir_fd=fd)
                    staged = None
                    self._sync_directory(fd)
                    self._validate_directory(fd)
                finally:
                    if staged is not None:
                        os.unlink(staged, dir_fd=fd)
            if self.read() != record:
                raise ValueError()
        except Exception:
            # Retain published evidence. Pending terminals still hold; release
            # publication can fail its barrier after the outcome was committed.
            raise CaptureLifecycleError() from None
        return record


def require_no_capture(root: Path):
    record = CaptureStore(root).read()
    if record is not None and record.held:
        raise CaptureLifecycleError()


def capture_activation_holds(root: Path):
    store = CaptureStore(root)
    record = store.read()
    if record is None or not record.held:
        return frozenset()
    # A competing record is a lifecycle breach, not another source of authority.
    try:
        if (store.competing_records_present()
                or store.read() != record):
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
        if Path(restart_store.directory).resolve() != store.root:
            raise CaptureLifecycleError()

    @contextmanager
    def _exclusive(self):
        from resources.lib.frozen_install import FrozenInstallStore
        frozen = FrozenInstallStore(self.store.root, create=False)
        try:
            # All three stores use the same canonical directory and OS locks.
            # Descriptor-relative lock opens cannot escape that directory.
            from resources.lib.transaction import LOCK_FILENAME
            with self.store._directory(create=True) as fd:
                with self.store._lock(fd, "create_capture_transaction.lock"), \
                        self.store._lock(fd, frozen.lock_path.name), \
                        self.store._lock(fd, LOCK_FILENAME):
                    if self.store._transition_fd is not None:
                        raise CaptureLifecycleError()
                    self.store._transition_fd = fd
                    try:
                        if (self.store.competing_records_present()
                                or self.operations.competing_operation() is not False):
                            raise CaptureLifecycleError()
                        self._validate_root()
                        self.store._validate_directory(fd)
                        yield
                        self.store._validate_directory(fd)
                    finally:
                        self.store._transition_fd = None
        except Exception:
            raise CaptureLifecycleError() from None

    def reconstruct_request(self, operation_id, fingerprint):
        """Read-only reconstruction; no operations callbacks or locks."""
        return self.store.reconstruct_request(operation_id, fingerprint, now=self.clock())

    def reconstruct_request_for_recovery(self, operation_id, fingerprint):
        """Read-only recovery-purpose reconstruction, including expired requests."""
        return self.store.reconstruct_request_for_recovery(operation_id, fingerprint, now=self.clock())

    def _validate_root(self):
        if Path(self.restart_store.directory).resolve() != self.store.root:
            raise CaptureLifecycleError()
        with self.store._directory() as fd:
            if fd is None:
                raise CaptureLifecycleError()
            self.store._validate_directory(fd)

    def _checked(self, operation_id, request, *, recovery=False):
        self._validate_root()
        record = self.store.read()
        if (record is None or record.operation_id != operation_id
                or not record.request_metadata
                or record.request_metadata != _request_metadata(request)
                or record.request_fingerprint != request_fingerprint(request)
                or not record.created_at <= self.clock() < (float("inf") if recovery else record.expires_at)
                or self.operations.competing_operation() is not False
                or self.store.competing_records_present()
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
            self._validate_root()
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
                if record.commit_pending:
                    # A prior first barrier may have failed. Fresh publication
                    # and a successful barrier establish commitment on this retry.
                    self._terminal_checked(record, request, recovery=True)
                    record = self.store.save(record, record)
                    return self._release_terminal(record, request, recovery=True)
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
            self._validate_root()
            self.operations.set_enabled(record.owner_id, record.original_enabled)
        if (self.operations.enabled(record.owner_id) is not record.original_enabled
                or self.operations.owner_version(record.owner_id) != record.owner_version
                or self.store.read() != record):
            raise CaptureLifecycleError()
        self._terminal_checked(record, request, recovery=recovery)
        pending = self.store.save(record, replace(record, phase=CapturePhase(record.outcome), commit_pending=True))
        return self._release_terminal(pending, request, recovery=recovery)

    def _terminal_checked(self, record, request, *, recovery):
        if (self._checked(record.operation_id, request, recovery=recovery) != record
                or self.operations.enabled(record.owner_id) is not record.original_enabled):
            raise CaptureLifecycleError()

    def _release_terminal(self, record, request, *, recovery):
        """Only after a successful pending publication/barrier; never a setter."""
        if record.phase not in TERMINAL or not record.commit_pending:
            raise CaptureLifecycleError()
        self._terminal_checked(record, request, recovery=recovery)
        return self.store.save(record, replace(record, commit_pending=False))
