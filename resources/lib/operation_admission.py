"""Offline reservation for cooperating Build Manager operations, on local POSIX FS.

This is NOT a competing_operation provider, Kodi activity observer, or proof of
Kodi quiescence. Every participant must reserve BEFORE store locks/effects, pass
the same capability through nested calls, and retain it through verification.
Nonparticipants (including external Kodi and existing unwired BM code) are not
excluded. No store lock is acquired here; capability checks never reacquire flock.
Local thread contention also refuses immediately, avoiding a wait on a verifier
that might need a store lock already held by a nested caller.

Provision a NEW dedicated directory once with provision_new(). Retain its Pin in
trusted caller configuration and supply that exact identity on every open. Never
rediscover/re-pin an existing or damaged directory. Provisioning is an explicit
new-namespace declaration, not recovery or a check for existing work. Production
provisioning, pin persistence, integration and recovery are deliberately absent.

The permanent lock inode also holds an append-only, synchronized journal. Missing,
invalid, partial or unresolved evidence blocks admission. A failed write may leave
unresolved/corrupt evidence: it is never repaired here. close(), exceptions and
process exit release OS ownership WITHOUT completing the operation. No stale
owner heuristic, restart takeover, or recovery/clear API exists. The journal is
bounded; reaching the bound fails closed rather than compacting evidence.
A completion-write/flush/check/cleanup failure has a distinct uncertain outcome:
completion may have occurred; reconcile authoritative state and never retry the
operation's effects automatically. It is not evidence of unfinished work. Visible
completed records must pass fresh file and namespace synchronization before they
can authorize another operation. Failed barriers refuse before a new begin.

Assumptions: cooperating trusted Python callers, one shared externally retained
Pin, local filesystem with working flock/fsync, and no hostile writer with access
to the namespace. Identity checks detect persistent path replacement, symlinks and
split-lock attempts, but cannot police arbitrary same-user filesystem mutation
between a check and a caller effect, or authenticate a rewritten/rolled-back valid
journal. Capabilities are in-process API authority, not a Python security sandbox.
On macOS, journal and namespace metadata synchronization require F_FULLFSYNC,
which requests a drive-cache flush as well as the filesystem synchronization.
Missing support or failure refuses authority; there is no weaker fallback.
Other supported POSIX platforms use file/directory fsync and rely on that
platform/filesystem's documented persistence guarantee, not universal power-loss
protection. No software flush can overcome a device that violates its flush
contract. Disk-space exhaustion and actual I/O failures remain possible even
though admission reserves journal byte capacity for both begin and completion.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import threading
import uuid


_LOCK = "reservation.lock"
_LIMIT = 1024 * 1024
_OPERATION = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


class AdmissionError(Exception):
    """Sanitized refusal; never include caller paths or persisted data."""

    def __init__(self, code="BM_RESERVATION_EVIDENCE_INVALID"):
        self.code = code
        self.cleanup_reason = None
        super().__init__(code)


class CompletionUncertain(AdmissionError):
    """Completion may have occurred. Reconcile authoritative state; NEVER retry
    operation effects automatically. This is not proof of unfinished work.

    reason is a sanitized underlying code. durability_confirmed means that both
    descriptor barriers returned success, not that this call completed normally.
    In particular, a failed F_FULLFSYNC must never set durability_confirmed.
    """

    def __init__(self, reason, durability_confirmed=False):
        super().__init__("BM_RESERVATION_COMPLETION_UNCERTAIN")
        self.reason = reason
        self.durability_confirmed = durability_confirmed


def _close_descriptors(descriptors, primary=None):
    """Attempt each detached descriptor once. A failed close has unknown outcome.

    Never retry a descriptor number: it may already have been freed/reused.
    Preserve the original failure, annotating only a sanitized cleanup code.
    """
    failure = None
    for fd in descriptors:
        if fd is not None:
            try:
                os.close(fd)
            except BaseException as error:
                if failure is None or isinstance(failure, OSError):
                    failure = error
    if failure is not None:
        if primary is None:
            if not isinstance(failure, OSError):
                raise failure
            raise AdmissionError("BM_RESERVATION_CLOSE_FAILED") from None
        primary.cleanup_reason = "BM_RESERVATION_CLOSE_FAILED"


@dataclass
class _AppendProgress:
    attempted: bool = False
    journal_synced: bool = False


@dataclass(frozen=True)
class Pin:
    """Trusted namespace identity; persist externally, never reconstruct from disk."""

    path: str
    # Identity of / followed by each absolute path component (no symlinks).
    directories: tuple[tuple[int, int], ...]
    lock: tuple[int, int]
    namespace: str


@dataclass(frozen=True, eq=False)
class Capability:
    """Opaque, non-transferable ownership; only the issued object is accepted."""

    _reservation: object = field(repr=False)
    _pid: int = field(repr=False)
    _generation: int = field(repr=False)
    _token: str = field(repr=False)


def _identity(st):
    return st.st_dev, st.st_ino


def _path(path):
    value = os.fspath(path)
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        raise AdmissionError()
    parts = value.split("/")[1:]
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise AdmissionError()
    return value, parts


def _walk(path):
    """Open every component relative to its descriptor; never resolve symlinks."""
    _, parts = _path(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    ids = [_identity(os.fstat(fd))]
    try:
        for part in parts:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=fd)
            old, fd = fd, new
            _close_descriptors((old,))
            ids.append(_identity(os.fstat(fd)))
        return fd, tuple(ids)
    except BaseException as error:
        _close_descriptors((fd,), error)
        raise


def _regular(fd):
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise AdmissionError()
    return _identity(st)


def _encoded(row):
    return json.dumps(row, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def _sync(fd):
    """Required descriptor synchronization; macOS must never downgrade to fsync.

    Apple's fcntl(2) specifies F_FULLFSYNC as fsync plus a drive-cache flush
    request. Use it for both the journal and directory metadata descriptors.
    https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/fcntl.2.html
    """
    try:
        if sys.platform == "darwin":
            command = getattr(fcntl, "F_FULLFSYNC", None)
            if command is None:
                raise AdmissionError("BM_RESERVATION_DURABILITY_UNAVAILABLE")
            if fcntl.fcntl(fd, command) != 0:
                raise AdmissionError("BM_RESERVATION_DURABILITY_FAILED")
        else:
            os.fsync(fd)
    except OSError:
        pass
    else:
        return
    # Raise outside the handler so the internal filesystem error is not linked.
    raise AdmissionError("BM_RESERVATION_DURABILITY_FAILED") from None


def _completion(row, evidence):
    return dict(row, phase="completed", previous=hashlib.sha256(evidence).hexdigest())


def _append(fd, row, progress=None):
    data = _encoded(row)
    if os.fstat(fd).st_size + len(data) > _LIMIT:
        raise AdmissionError("BM_RESERVATION_JOURNAL_FULL")
    # O_APPEND writes only; a short write is ambiguous and intentionally blocks.
    if progress is not None:
        progress.attempted = True  # immediately before the potentially partial write
    if os.write(fd, data) != len(data):
        raise AdmissionError()
    _sync(fd)
    if progress is not None:
        progress.journal_synced = True


def _header(pin):
    return {"version": 1, "scope": "cooperating-bm-only", "namespace": pin.namespace,
            "root": list(pin.directories[-1]), "lock": list(pin.lock)}


def provision_new(path):
    """Create a fresh namespace and return its identity. Never repair/reinitialize.

    The parent must already exist with a symlink-free absolute path. A failure
    retains anything created, including the authoritative lock file. No unlink.
    """
    parent_fd = root_fd = lock_fd = None
    primary = None
    try:
        value, parts = _path(path)
        parent = "/" + "/".join(parts[:-1]) if len(parts) > 1 else "/"
        if parent == "/":
            parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            parents = (_identity(os.fstat(parent_fd)),)
        else:
            parent_fd, parents = _walk(parent)
        os.mkdir(parts[-1], mode=0o700, dir_fd=parent_fd)  # existing root refuses
        root_fd = os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=parent_fd)
        lock_fd = os.open(_LOCK, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL |
                          os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=root_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pin = Pin(value, parents + (_identity(os.fstat(root_fd)),),
                  _regular(lock_fd), uuid.uuid4().hex)
        _append(lock_fd, _header(pin))
        _sync(root_fd)
        _sync(parent_fd)
        # Check the complete path again before returning any trusted identity.
        check_fd, identities = _walk(value)
        check_error = None
        try:
            st = os.stat(_LOCK, dir_fd=check_fd, follow_symlinks=False)
            if identities != pin.directories or _identity(st) != pin.lock:
                raise AdmissionError()
        except BaseException as error:
            check_error = error
            raise
        finally:
            _close_descriptors((check_fd,), check_error)
        return pin
    except OSError as error:
        primary = AdmissionError("BM_RESERVATION_IO_FAILED")
        primary.cleanup_reason = getattr(error, "cleanup_reason", None)
    except BaseException as error:
        primary = error
        raise
    finally:
        _close_descriptors((lock_fd, root_fd, parent_fd), primary)
    raise primary from None


def _no_duplicates(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            raise AdmissionError()
        row[key] = value
    return row


class Reservation:
    """One operation owner. close() never claims completion, even after failure.

    Use try/finally or a with block to close deterministically. Completion runs a
    trusted caller verifier under the existing reservation and requires exactly
    True. The verifier must cover the full operation, including any mocked restart
    handoff; this foundation does not define or perform Kodi verification.
    """

    def __init__(self, pin: Pin):
        self._pin = pin
        self._pid = os.getpid()
        self._fd = self._root_fd = None
        self._capability = None
        self._evidence = None
        self._mutex = threading.RLock()
        self._verifying = False
        try:
            if type(pin) is not Pin:
                raise AdmissionError()
            self._root_fd, identities = _walk(pin.path)
            if identities != pin.directories:
                raise AdmissionError()
            self._fd = os.open(_LOCK, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW |
                               os.O_NONBLOCK, dir_fd=self._root_fd)
            self._check_identity()
        except OSError as failure:
            error = AdmissionError("BM_RESERVATION_IO_FAILED")
            error.cleanup_reason = getattr(failure, "cleanup_reason", None)
        except AdmissionError as error:
            self._release(error)
            raise
        else:
            return
        self._release(error)
        raise error from None

    @contextmanager
    def _guard(self):
        # Nested reuse must not wait behind a verifier that may need a store lock
        # held by the reusing thread. Local contention fails rather than waiting.
        if not self._mutex.acquire(blocking=False):
            raise AdmissionError("BM_RESERVATION_BUSY")
        try:
            yield
        finally:
            self._mutex.release()

    def _check_identity(self):
        if self._pid != os.getpid() or self._fd is None:
            raise AdmissionError("BM_RESERVATION_CAPABILITY_INVALID")
        fd, identities = _walk(self._pin.path)
        primary = None
        try:
            st = os.stat(_LOCK, dir_fd=fd, follow_symlinks=False)
            if (identities != self._pin.directories or
                    _identity(os.fstat(self._root_fd)) != identities[-1] or
                    not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
                    _identity(st) != self._pin.lock or
                    _regular(self._fd) != self._pin.lock):
                raise AdmissionError()
        except BaseException as error:
            primary = error
            raise
        finally:
            _close_descriptors((fd,), primary)

    def _read(self):
        self._check_identity()
        size = os.fstat(self._fd).st_size
        if not 0 < size <= _LIMIT:
            raise AdmissionError()
        data = os.pread(self._fd, size + 1, 0)
        self._check_identity()
        if len(data) != size or not data.endswith(b"\n"):
            raise AdmissionError()
        try:
            lines = data.splitlines(True)
            rows = [json.loads(line, object_pairs_hook=_no_duplicates) for line in lines]
            if rows[0] != _header(self._pin) or _encoded(rows[0]) != lines[0]:
                raise AdmissionError()
            last = None
            digest = hashlib.sha256(lines[0])
            for index, row in enumerate(rows[1:], 1):
                if type(row) is not dict or set(row) != {
                        "generation", "token", "pid", "operation", "phase", "previous"}:
                    raise AdmissionError()
                if (type(row["generation"]) is not int or type(row["pid"]) is not int or
                        row["pid"] <= 0 or type(row["operation"]) is not str or
                        not _OPERATION.fullmatch(row["operation"]) or
                        type(row["token"]) is not str or
                        not re.fullmatch(r"[0-9a-f]{32}", row["token"])):
                    raise AdmissionError()
                if row["previous"] != digest.hexdigest():
                    raise AdmissionError()
                if index % 2:
                    if row["phase"] != "unresolved" or row["generation"] != (index + 1) // 2:
                        raise AdmissionError()
                elif (row["phase"] != "completed" or
                      any(row[k] != last[k] for k in ("generation", "token", "pid", "operation"))):
                    raise AdmissionError()
                if _encoded(row) != lines[index]:
                    raise AdmissionError()
                digest.update(lines[index])
                last = row
            return data, last
        except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
            pass
        raise AdmissionError() from None

    def acquire(self, operation: str) -> Capability:
        """Nonblocking; valid completed BM evidence is required, then durable begin."""
        with self._guard():
            if type(operation) is not str or not _OPERATION.fullmatch(operation):
                raise AdmissionError()
            if self._capability is not None:
                raise AdmissionError("BM_RESERVATION_ALREADY_OWNED")
            try:
                self._check_identity()
                busy = False
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    busy = True
                if busy:
                    raise AdmissionError("BM_RESERVATION_BUSY") from None
                data, last = self._read()
                if last is not None and last["phase"] != "completed":
                    raise AdmissionError("BM_RESERVATION_UNRESOLVED")
                if last is not None:
                    # A visible completed row does not prove its prior barrier
                    # succeeded. Establish fresh durability BEFORE a new begin.
                    _sync(self._fd)
                    _sync(self._root_fd)
                    if self._read()[0] != data:
                        raise AdmissionError()
                generation = 1 if last is None else last["generation"] + 1
                token = uuid.uuid4().hex
                row = {"generation": generation, "token": token, "pid": self._pid,
                       "operation": operation, "phase": "unresolved",
                       "previous": hashlib.sha256(data).hexdigest()}
                # Reserve BOTH exact records before changing the valid journal.
                # This is byte capacity, not a guarantee against real I/O errors.
                beginning = _encoded(row)
                ending = _encoded(_completion(row, data + beginning))
                if len(data) + len(beginning) + len(ending) > _LIMIT:
                    raise AdmissionError("BM_RESERVATION_JOURNAL_FULL")
                _append(self._fd, row)
                _sync(self._root_fd)
                self._check_identity()
                self._evidence, written = self._read()
                if written != row:
                    raise AdmissionError()
                self._capability = Capability(self, self._pid, generation, token)
                return self._capability
            except OSError as failure:
                error = AdmissionError("BM_RESERVATION_IO_FAILED")
                error.cleanup_reason = getattr(failure, "cleanup_reason", None)
            except AdmissionError as error:
                self._release(error)
                raise
            self._release(error)
            raise error from None

    def require(self, capability: Capability):
        """Validate existing authority without flock or any store-lock acquisition."""
        with self._guard():
            try:
                if (capability is not self._capability or capability is None or
                        capability._reservation is not self or capability._pid != os.getpid()):
                    raise AdmissionError("BM_RESERVATION_CAPABILITY_INVALID")
                self._check_identity()
                data, last = self._read()
                if (data != self._evidence or last is None or last["phase"] != "unresolved" or
                        last["generation"] != capability._generation or
                        last["token"] != capability._token or last["pid"] != capability._pid):
                    raise AdmissionError()
            except OSError as failure:
                error = AdmissionError("BM_RESERVATION_IO_FAILED")
                error.cleanup_reason = getattr(failure, "cleanup_reason", None)
            else:
                return
            raise error from None

    def complete(self, capability: Capability, verify):
        """Verify while owned, then explicitly complete and expire authority.

        Verifier exceptions propagate unchanged. Pre-write refusals retain their
        typed code. Any failure after attempting the completion write (including
        close failure) raises CompletionUncertain: reconcile, never retry effects.
        A failed barrier is NOT a claim of durable completion. A later admission
        must establish fresh durability of valid completed evidence before begin.
        """
        with self._guard():
            self.require(capability)
            if self._verifying:
                raise AdmissionError("BM_RESERVATION_CAPABILITY_INVALID")
            self._verifying = True
            progress = _AppendProgress()
            durability_confirmed = False
            try:
                if verify() is not True:
                    raise AdmissionError("BM_RESERVATION_VERIFICATION_FAILED")
                try:
                    self.require(capability)
                    _, last = self._read()
                    row = _completion(last, self._evidence)
                    _append(self._fd, row, progress)
                    _sync(self._root_fd)
                    durability_confirmed = progress.journal_synced
                    self._check_identity()
                    _, written = self._read()
                    if written != row:
                        raise AdmissionError()
                    self.close()
                except BaseException as failure:
                    reason = (failure.code if isinstance(failure, AdmissionError) else
                              "BM_RESERVATION_IO_FAILED" if isinstance(failure, OSError) else
                              "BM_RESERVATION_INTERRUPTED")
                    error = (CompletionUncertain(reason, durability_confirmed)
                             if progress.attempted else
                             AdmissionError(reason) if isinstance(failure, OSError) else failure)
                    error.cleanup_reason = getattr(failure, "cleanup_reason", None)
                    self._release(error)
                else:
                    return
                raise error from None
            finally:
                self._verifying = False

    def _release(self, primary=None):
        # Detach ALL descriptors before attempting any close; never retry one
        # whose outcome is unknown. An unclosed OS handle may safely overblock.
        with self._guard():
            self._capability = None
            self._evidence = None
            descriptors = (self._fd, self._root_fd)
            self._fd = self._root_fd = None
            _close_descriptors(descriptors, primary)

    def close(self):
        """Revoke authority and attempt both closes once, with typed failure.

        Never append completion, unlink, or LOCK_UN a fork-shared description.
        Unknown close outcomes may retain an OS lock until natural process exit.
        """
        self._release()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, error, traceback):
        self._release(error)
