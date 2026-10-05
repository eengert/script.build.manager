#!/usr/bin/env python3
"""Host-side qualification helper for the portable Build Manager Test.app.

Subcommands (every one prints deterministic, sanitized JSON on stdout):

  identify   read-only bundle and process identity of the authorized Test.app
  stage      install an exact, Git-pinned candidate into the portable add-ons
             directory while the Test.app is NOT running
  verify     read-only proof that the installed trees equal the stage manifest
  run MODE   trigger the BM-023A adapter (install|retry|recover|status) over
             loopback JSON-RPC and report its fresh, allowlisted result
  snapshot   read-only, secret-blind qualification census

The only runtime target is ``/Applications/Kodi Build Manager Test.app`` and its
portable ``-p`` data. The path is a constant: there is no command-line or
environment override. Internals take an injected target so the unit tests can
use temporary fake bundles and never touch /Applications. Nothing here reads or
stats the normal Kodi application or its normal profile.

Candidate bytes come from Git objects of an explicit commit, never from
working-tree files. Credentials are entered through a controlling-terminal
prompt only: never argv, environment, files, logs, or output.

This module performs no live operation at import time.
"""

from __future__ import annotations

import argparse
import ast
import base64
import ctypes
import errno
import getpass
import hashlib
import http.client
import io
import ipaddress
import json
import os
import plistlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from typing import (
    Any, Callable, Dict, Iterable, List, Mapping, NoReturn, Optional, Sequence, Set, Tuple,
)

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

# Only the allowlists and the sanctioned secret-blind status reader are shared
# with the in-Kodi adapter; no candidate bytes are ever taken from this import.
from tools import bm023a_adapter_support as _adapter  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HELPER_NAME = "bm_test_app"
OUTPUT_SCHEMA = "bm-test-app-output/1"
MANIFEST_SCHEMA = "bm-test-app-stage-manifest/1"
CONFIG_SCHEMA = "bm-test-app-config/1"

AUTHORIZED_TEST_APP = "/Applications/Kodi Build Manager Test.app"
# Forbidden surfaces: matched lexically only. These paths are never stat'ed,
# listed, opened or resolved by this module.
_NORMAL_KODI_APP = "/Applications/Kodi.app"
_NORMAL_KODI_PROFILE_LITERAL = "/Users/eengert/Library/Application Support/Kodi"
_DATA_VOLUME_ALIAS = "/System/Volumes/Data"

BUILD_MANAGER_ID = _adapter.ADDON_ID
DRIVER_ID = _adapter.DRIVER_ADDON_ID
ADAPTER_MODES = ("install", "retry", "recover", "status")
RESULT_FILENAME = "bm023a_live_result.json"
STAGE_AREA_NAME = ".bm-stage"

# The one auxiliary executable a normal portable launch starts beside the main
# Kodi executable. It is recognized only by its full kernel executable path.
AUXILIARY_NAME = "XBMCHelper"
AUXILIARY_RELATIVE_PARTS = ("Resources", "Kodi", "tools", "darwin", "runtime", AUXILIARY_NAME)

ADAPTER_CONFIG_KEYS = (
    "MANIFEST_PATH",
    "ARTIFACT_ROOT",
    "CONFIGURATION_PATH",
    "OVERLAY_SOURCE",
    "DEVICE_PROFILE_ID",
    "EXPECTED_OVERLAY_ID",
)
ADAPTER_PATH_KEYS = ("MANIFEST_PATH", "ARTIFACT_ROOT", "CONFIGURATION_PATH", "OVERLAY_SOURCE")

# The staged product set: exactly the runtime content of the add-on.
PRODUCT_ROOT_FILES = ("addon.xml", "default.py", "service.py")
PRODUCT_TREE_DIRS = ("resources",)
PRODUCT_REQUIRED = (
    "addon.xml",
    "default.py",
    "service.py",
    "resources/lib/__init__.py",
    "resources/lib/frozen_install.py",
)
# What the candidate's own driver builder needs (read from the same commit).
BUILDER_TREE_DIR = "tools"
BUILDER_REQUIRED = (
    "tools/__init__.py",
    "tools/build_bm023a_adapter.py",
    "tools/bm023a_adapter_support.py",
    "tools/bm023a_adapter/addon.xml.in",
    "tools/bm023a_adapter/default.py.in",
)
DRIVER_FILES = (
    "addon.xml",
    "default.py",
    "adapter_config.py",
    "adapter_support.py",
    "bundled_frozen_install.py",
)
# Driver files that are byte copies of candidate blobs (adapter_config.py is
# generated from machine-local configuration and is bound by hash only).
DRIVER_SOURCE_PATHS = {
    "default.py": "tools/bm023a_adapter/default.py.in",
    "addon.xml": "tools/bm023a_adapter/addon.xml.in",
    "adapter_support.py": "tools/bm023a_adapter_support.py",
    "bundled_frozen_install.py": "resources/lib/frozen_install.py",
}

MAX_BLOB_BYTES = 8 * 1024 * 1024
MAX_CANDIDATE_BYTES = 64 * 1024 * 1024
MAX_CANDIDATE_FILES = 2000
MAX_GIT_OUTPUT = 128 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TREE_ENTRIES = 20000
MAX_TREE_DEPTH = 24
MAX_PLIST_BYTES = 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_CONFIG_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_RPC_BYTES = 1024 * 1024
LIST_CAP = 50

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_ADAPTER_FAILED = 4
EXIT_INTERRUPTED = 130

_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ADDON_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}")
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+~\-]{0,63}")
_SAFE_TEXT_RE = re.compile(r"[A-Za-z0-9._:/+@=~ \-]*")
_PYC_NAME_RE = re.compile(r"[A-Za-z0-9_.\-]{1,200}\.pyc")
_UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


# ---------------------------------------------------------------------------
# Error vocabulary: only these fixed codes ever leave the helper
# ---------------------------------------------------------------------------

ERROR_CODES = frozenset({
    # arguments / configuration
    "argument_invalid", "argument_path_invalid", "argument_path_forbidden",
    "argument_path_inside_test_app", "argument_path_symlink", "argument_path_not_found",
    "config_unreadable", "config_unsafe_permissions", "config_invalid",
    "config_credential_field", "config_missing_section", "output_exists",
    "output_write_failed", "evidence_dir_invalid",
    # target / identity
    "target_path_not_authorized", "target_path_forbidden", "bundle_missing",
    "bundle_path_symlink", "info_plist_invalid", "bundle_executable_invalid",
    "layout_missing", "process_listing_failed", "foreign_kodi_process_present",
    "multiple_test_app_processes", "test_app_process_mismatch",
    "test_app_process_ambiguous", "test_app_not_portable", "test_app_running",
    "test_app_not_running",
    # candidate / git
    "candidate_id_invalid", "candidate_commit_missing", "candidate_not_a_commit",
    "candidate_id_mismatch", "candidate_git_failed", "candidate_git_unavailable",
    "candidate_git_output_too_large", "candidate_tree_malformed",
    "candidate_unsafe_entry", "candidate_path_collision", "candidate_incomplete",
    "candidate_too_large", "candidate_blob_missing", "candidate_blob_too_large",
    "candidate_blob_mismatch", "candidate_blob_stream_malformed",
    "candidate_object_format_invalid", "candidate_addon_xml_invalid",
    "candidate_export_failed",
    # driver build
    "driver_build_failed", "driver_output_unexpected", "driver_source_mismatch",
    "driver_config_mismatch", "driver_version_mismatch",
    # manifest / verify
    "manifest_unreadable", "manifest_invalid", "manifest_too_large",
    "installed_tree_mismatch",
    # stage
    "stage_area_exists", "stage_area_invalid", "stage_write_failed",
    "stage_new_tree_mismatch", "stage_backup_failed", "stage_swap_failed",
    "stage_post_verify_failed", "rollback_failed", "evidence_exists",
    # rpc / run
    "rpc_config_invalid", "rpc_host_not_loopback", "rpc_port_invalid",
    "listener_lookup_failed", "listener_not_found", "listener_pid_mismatch",
    "credential_prompt_unavailable", "credential_missing", "rpc_transport_failed",
    "rpc_auth_failed", "rpc_http_error", "rpc_response_invalid",
    "rpc_response_too_large", "rpc_error", "rpc_execute_rejected",
    "addon_not_visible_to_kodi", "addon_view_mismatch",
    "result_path_unsafe", "result_not_produced", "result_stale",
    "result_malformed", "result_from_future", "adapter_mode_mismatch",
    "kodi_exited_before_result",
    # snapshot / privacy
    "private_path_denied", "read_not_allowlisted", "output_blocked_secret_detected",
    # generic
    "interrupted", "unexpected_error", "internal_error",
})


class HelperError(Exception):
    """A fail-closed error carrying only a fixed code and sanitized scalar detail."""

    def __init__(self, code: str, /, **detail: Any) -> None:
        super().__init__(code)
        self.code = code if code in ERROR_CODES else "internal_error"
        self.detail = {key: _scalar(value) for key, value in sorted(detail.items())}


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, (list, tuple)):
        return [_scalar(item) for item in list(value)[:LIST_CAP]]
    return "<unsupported>"


def safe_text(value: str, limit: int = 200) -> str:
    """Return value if it is short printable ASCII, else a short digest marker."""
    if len(value) <= limit and _SAFE_TEXT_RE.fullmatch(value):
        return value
    digest = hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()[:12]
    return f"<unsafe:{digest}>"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_object_id(kind: bytes, data: bytes, algo: str) -> str:
    """Git object id of ``data`` (used to re-verify every blob read from Git)."""
    digest = hashlib.new(algo)
    digest.update(kind + b" " + str(len(data)).encode("ascii") + b"\0")
    digest.update(data)
    return digest.hexdigest()


def canonical_json(payload: Any) -> str:
    """Deterministic JSON text: sorted keys, ASCII only, no NaN, trailing newline."""
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_utc_from_ns(nanoseconds: int) -> str:
    return iso_utc(datetime.fromtimestamp(nanoseconds / 1e9, timezone.utc))


def capped(items: Iterable[str], cap: int = LIST_CAP) -> Tuple[List[str], bool]:
    """Sorted, sanitized, bounded list of names plus a truncation flag."""
    ordered = sorted(items)
    return [safe_text(item) for item in ordered[:cap]], len(ordered) > cap


class SecretRegistry:
    """Values that must never appear in any emitted output."""

    def __init__(self) -> None:
        self._values: List[str] = []

    def register(self, value: Optional[str], *, minimum: int = 1) -> None:
        if isinstance(value, str) and len(value) >= minimum:
            # Output is JSON, so a secret must also be caught in its escaped form.
            for spelling in (value, json.dumps(value)[1:-1]):
                if spelling not in self._values:
                    self._values.append(spelling)

    def leaks(self, text: str) -> bool:
        return any(value in text for value in self._values)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

class SystemClock:
    def time_ns(self) -> int:
        return time.time_ns()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def utcnow(self) -> datetime:
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Filesystem primitives (no symlink following, bounded, fail closed)
# ---------------------------------------------------------------------------

class FsProblem(Exception):
    """A low-level filesystem condition; callers map it to a HelperError code."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class FileRead:
    data: bytes
    st_dev: int
    st_ino: int
    st_size: int
    st_mtime_ns: int
    st_mode: int
    st_uid: int


def _read_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise FsProblem("unreadable")
    return os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def read_regular_file(path: Any, max_bytes: int) -> FileRead:
    """Read one regular file without following a final symlink or blocking.

    The path is lstat'ed, opened with O_NOFOLLOW|O_NONBLOCK, fstat'ed to prove
    it is the same regular file, read with a hard bound, and lstat'ed again.
    """
    flags = _read_flags()
    text = os.fspath(path)
    try:
        before = os.lstat(text)
    except (FileNotFoundError, NotADirectoryError):
        raise FsProblem("absent") from None
    except OSError:
        raise FsProblem("unreadable") from None
    if not stat.S_ISREG(before.st_mode):
        raise FsProblem("not_regular")
    try:
        fd = os.open(text, flags)
    except OSError:
        raise FsProblem("unreadable") from None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev, before.st_ino
        ):
            raise FsProblem("changed")
        chunks: List[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1 << 20, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise FsProblem("too_large")
        after = os.lstat(text)
        if (
            not stat.S_ISREG(after.st_mode)
            or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
            or after.st_size != total
            or after.st_mtime_ns != opened.st_mtime_ns
        ):
            raise FsProblem("changed")
    except OSError:
        raise FsProblem("unreadable") from None
    finally:
        os.close(fd)
    return FileRead(
        data=b"".join(chunks),
        st_dev=opened.st_dev,
        st_ino=opened.st_ino,
        st_size=total,
        st_mtime_ns=opened.st_mtime_ns,
        st_mode=opened.st_mode,
        st_uid=opened.st_uid,
    )


def lstat_real_dir(path: Any) -> os.stat_result:
    """lstat a path that must be a real directory (never a symlink)."""
    try:
        info = os.lstat(os.fspath(path))
    except (FileNotFoundError, NotADirectoryError):
        raise FsProblem("absent") from None
    except OSError:
        raise FsProblem("unreadable") from None
    if stat.S_ISLNK(info.st_mode):
        raise FsProblem("symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise FsProblem("not_directory")
    return info


def reject_symlink_components(path: Any) -> None:
    """Reject any existing symlink component; targets are never dereferenced."""
    normalized = os.fspath(normalize_path(path))
    parts = Path(normalized).parts
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            info = os.lstat(str(current))
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError:
            raise FsProblem("unreadable") from None
        if stat.S_ISLNK(info.st_mode):
            raise FsProblem("symlink")


@dataclass(frozen=True)
class TreeEntry:
    rel: str
    kind: str  # "file" | "dir" | "symlink" | "other"
    size: int


def walk_tree(
    root: Any, *, max_entries: int = MAX_TREE_ENTRIES, max_depth: int = MAX_TREE_DEPTH
) -> List[TreeEntry]:
    """Deterministic, bounded, non-following inventory of everything below root."""
    base = os.fspath(root)
    entries: List[TreeEntry] = []
    stack: List[Tuple[str, int]] = [("", 0)]
    while stack:
        rel_dir, depth = stack.pop()
        directory = os.path.join(base, rel_dir) if rel_dir else base
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda entry: entry.name)
        except OSError:
            raise FsProblem("unreadable") from None
        for child in children:
            rel = f"{rel_dir}/{child.name}" if rel_dir else child.name
            try:
                info = child.stat(follow_symlinks=False)
            except OSError:
                raise FsProblem("unreadable") from None
            if stat.S_ISLNK(info.st_mode):
                kind = "symlink"
            elif stat.S_ISDIR(info.st_mode):
                kind = "dir"
            elif stat.S_ISREG(info.st_mode):
                kind = "file"
            else:
                kind = "other"
            entries.append(TreeEntry(rel, kind, info.st_size))
            if len(entries) > max_entries:
                raise FsProblem("too_many_entries")
            if kind == "dir":
                if depth + 1 > max_depth:
                    raise FsProblem("too_deep")
                stack.append((rel, depth + 1))
    entries.sort(key=lambda entry: entry.rel)
    return entries


def tree_digest(files: Iterable[Tuple[str, str, int]]) -> str:
    """SHA-256 over sorted ``path NUL sha256 NUL size`` lines."""
    lines = [
        f"{path}\0{digest}\0{size}\n".encode("utf-8", "surrogateescape")
        for path, digest, size in sorted(files)
    ]
    return sha256_hex(b"".join(lines))


def write_new_file(path: Any, data: bytes, mode: int = 0o644) -> None:
    """Create a new file (never overwriting, never following a symlink)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(os.fspath(path), flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(os.fspath(path), mode)


def fsync_directory(path: Any) -> None:
    try:
        fd = os.open(os.fspath(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_new_file_atomic(path: Any, data: bytes, mode: int = 0o644) -> None:
    """Publish a new file atomically; refuse to replace an existing one."""
    final = os.fspath(path)
    parent = os.path.dirname(final)
    temporary = os.path.join(parent, f".{os.path.basename(final)}.{os.getpid()}.{token_hex(4)}.tmp")
    write_new_file(temporary, data, mode)
    try:
        try:
            os.link(temporary, final)
        except FileExistsError:
            raise HelperError("output_exists") from None
        except OSError:
            raise HelperError("output_write_failed") from None
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
    fsync_directory(parent)


# ---------------------------------------------------------------------------
# Forbidden surfaces and path hygiene (lexical; never touches the filesystem)
# ---------------------------------------------------------------------------

def _lexical_path(path: Any) -> str:
    """Canonical macOS spelling without any filesystem lookup.

    Opaque namespaces are refused before normpath can erase their components.
    Data-volume spellings are mapped to the ordinary namespace for both policy
    comparisons and subsequent I/O. No realpath/stat is used here.
    """
    text = os.fsdecode(path)
    if not text or "\x00" in text:
        raise HelperError("argument_path_invalid")
    absolute = text if os.path.isabs(text) else os.path.join(os.getcwd(), text)
    parts = unicodedata.normalize("NFD", absolute).casefold().split("/")
    if any(part in (".vol", ".nofollow", ".resolve") for part in parts):
        raise HelperError("argument_path_forbidden")
    canonical = os.path.normpath("/" + absolute.lstrip("/"))
    alias = _DATA_VOLUME_ALIAS.casefold()
    folded = canonical.casefold()
    if folded == alias or folded.startswith(alias + "/"):
        canonical = canonical[len(_DATA_VOLUME_ALIAS):] or "/"
    return canonical


def _folded_abspath(path: Any) -> str:
    return unicodedata.normalize("NFD", _lexical_path(path)).casefold()


def _forbidden_prefixes() -> Tuple[str, ...]:
    bases = [_NORMAL_KODI_APP, _NORMAL_KODI_PROFILE_LITERAL]
    home = os.path.expanduser("~")
    if home and home != "~" and os.path.isabs(home):
        bases.append(os.path.join(home, "Library", "Application Support", "Kodi"))
    return tuple(_folded_abspath(base) for base in bases)


def is_forbidden_path(path: Any) -> bool:
    """True for forbidden nodes or opaque macOS namespace spellings."""
    try:
        candidate = _folded_abspath(path)
    except HelperError:
        return True
    return any(candidate == prefix or candidate.startswith(prefix + "/")
               for prefix in _forbidden_prefixes())


def is_inside(path: Any, root: Any) -> bool:
    candidate = _folded_abspath(path)
    anchor = _folded_abspath(root)
    return candidate == anchor or candidate.startswith(anchor + "/")


def normalize_path(raw: Any) -> Path:
    path = Path(_lexical_path(raw))
    if is_forbidden_path(path):
        raise HelperError("argument_path_forbidden")
    return path


# ---------------------------------------------------------------------------
# The authorized target
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TestAppTarget:
    """Layout of one Test.app bundle and its portable data."""

    __test__ = False  # not a unittest case

    root: Path
    production: bool = False

    def __post_init__(self) -> None:
        text = os.fspath(self.root)
        if (
            not os.path.isabs(text)
            or os.path.normpath(text) != text
            or "\x00" in text
            or text == os.sep
        ):
            raise HelperError("target_path_not_authorized")
        if is_forbidden_path(text):
            raise HelperError("target_path_forbidden")
        if self.production and text != AUTHORIZED_TEST_APP:
            raise HelperError("target_path_not_authorized")

    @classmethod
    def authorized(cls) -> "TestAppTarget":
        """The one production target. Performs no filesystem access."""
        return cls(Path(AUTHORIZED_TEST_APP), production=True)

    @classmethod
    def for_tests(cls, root: Any) -> "TestAppTarget":
        """A fake bundle in a temporary directory (used only by the unit tests)."""
        return cls(Path(os.fspath(root)), production=False)

    @property
    def contents_dir(self) -> Path:
        return self.root / "Contents"

    @property
    def info_plist(self) -> Path:
        return self.contents_dir / "Info.plist"

    @property
    def macos_dir(self) -> Path:
        return self.contents_dir / "MacOS"

    @property
    def portable_data(self) -> Path:
        return self.contents_dir / "Resources" / "Kodi" / "portable_data"

    @property
    def addons_dir(self) -> Path:
        return self.portable_data / "addons"

    @property
    def userdata_dir(self) -> Path:
        return self.portable_data / "userdata"

    @property
    def addon_data_dir(self) -> Path:
        return self.userdata_dir / "addon_data"

    @property
    def bm_data_dir(self) -> Path:
        return self.addon_data_dir / BUILD_MANAGER_ID

    @property
    def result_path(self) -> Path:
        return self.bm_data_dir / RESULT_FILENAME

    @property
    def stage_area(self) -> Path:
        return self.portable_data / STAGE_AREA_NAME

    def addon_dir(self, addon_id: str) -> Path:
        if not _ADDON_ID_RE.fullmatch(addon_id):
            raise HelperError("argument_invalid")
        return self.addons_dir / addon_id

    def contains(self, path: Any) -> bool:
        return is_inside(path, self.root)

    def exe_aliases(self, executable: str) -> Tuple[str, ...]:
        """Lexical spellings under which the main executable may be reported."""
        main = os.fspath(self.macos_dir / executable)
        return (main, _DATA_VOLUME_ALIAS + main)

    @property
    def auxiliary_executable(self) -> Path:
        """The exact sanctioned auxiliary executable (a path, never a pattern)."""
        return self.contents_dir.joinpath(*AUXILIARY_RELATIVE_PARTS)

    def auxiliary_aliases(self) -> Tuple[str, ...]:
        """Lexical spellings under which the sanctioned auxiliary may be reported."""
        auxiliary = os.fspath(self.auxiliary_executable)
        return (auxiliary, _DATA_VOLUME_ALIAS + auxiliary)

    def require_chain(self, path: Path) -> None:
        """Every component from / down to path must be a real, non-symlink node."""
        if not self.contains(path):
            raise HelperError("target_path_not_authorized")
        try:
            reject_symlink_components(path)
        except FsProblem:
            raise HelperError("bundle_path_symlink") from None


# ---------------------------------------------------------------------------
# Identity: bundle (Info.plist) and process state
# ---------------------------------------------------------------------------

_BUNDLE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,154}")
_EXEC_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ \-]{0,127}")
_KODI_NAME_PREFIXES = ("kodi", "xbmc")


@dataclass(frozen=True)
class BundleInfo:
    identifier: str
    executable: str
    package_type: str
    short_version: Optional[str]
    build_version: Optional[str]
    info_plist_sha256: str
    portable_data_present: bool
    addons_dir_present: bool
    userdata_dir_present: bool


def _plist_text(info: Mapping[str, Any], key: str, pattern: "re.Pattern[str]") -> Optional[str]:
    value = info.get(key)
    if isinstance(value, str) and pattern.fullmatch(value):
        return value
    return None


def _optional_dir(path: Path) -> bool:
    """True if a real directory, False if absent; a symlink is refused."""
    try:
        lstat_real_dir(path)
    except FsProblem as exc:
        if exc.kind == "absent":
            return False
        if exc.kind == "symlink":
            raise HelperError("bundle_path_symlink") from None
        raise HelperError("layout_missing") from None
    return True


def inspect_bundle(target: TestAppTarget) -> BundleInfo:
    """Read-only identity of the bundle from its Info.plist and layout."""
    target.require_chain(target.root)
    target.require_chain(target.macos_dir)
    for directory in (target.root, target.contents_dir, target.macos_dir):
        try:
            lstat_real_dir(directory)
        except FsProblem as exc:
            raise HelperError(
                "bundle_path_symlink" if exc.kind == "symlink" else "bundle_missing"
            ) from None
    try:
        raw = read_regular_file(target.info_plist, MAX_PLIST_BYTES)
    except FsProblem:
        raise HelperError("info_plist_invalid") from None
    try:
        info = plistlib.loads(raw.data)
    except Exception:
        raise HelperError("info_plist_invalid") from None
    if not isinstance(info, dict):
        raise HelperError("info_plist_invalid")
    identifier = _plist_text(info, "CFBundleIdentifier", _BUNDLE_ID_RE)
    executable = _plist_text(info, "CFBundleExecutable", _EXEC_NAME_RE)
    package_type = info.get("CFBundlePackageType")
    if identifier is None or executable is None or package_type != "APPL":
        raise HelperError("info_plist_invalid")
    if executable in (".", "..") or "/" in executable:
        raise HelperError("bundle_executable_invalid")
    try:
        executable_info = os.lstat(os.fspath(target.macos_dir / executable))
    except OSError:
        raise HelperError("bundle_executable_invalid") from None
    if not stat.S_ISREG(executable_info.st_mode) or not executable_info.st_mode & 0o111:
        raise HelperError("bundle_executable_invalid")
    target.require_chain(target.portable_data)
    portable = _optional_dir(target.portable_data)
    target.require_chain(target.addons_dir)
    target.require_chain(target.userdata_dir)
    addons = portable and _optional_dir(target.addons_dir)
    userdata = portable and _optional_dir(target.userdata_dir)
    return BundleInfo(
        identifier=identifier,
        executable=executable,
        package_type="APPL",
        short_version=_plist_text(info, "CFBundleShortVersionString", _VERSION_RE),
        build_version=_plist_text(info, "CFBundleVersion", _VERSION_RE),
        info_plist_sha256=sha256_hex(raw.data),
        portable_data_present=portable,
        addons_dir_present=addons,
        userdata_dir_present=userdata,
    )


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    exe: str


class ProcessVanished(Exception):
    """The kernel reported ESRCH for a pid: it exited after the ps snapshot.

    Internal marker only. It carries no text, is never part of helper output,
    and every caller either skips the stale pid or fails closed.
    """


def parse_ps_listing(text: str) -> List[ProcessInfo]:
    """Parse ``ps -o pid=,comm=`` output; the path may contain spaces."""
    found: List[ProcessInfo] = []
    for line in text.splitlines():
        match = re.match(r"\s*(\d+)\s+(.+?)\s*$", line)
        if match:
            found.append(ProcessInfo(int(match.group(1)), match.group(2)))
    return found


class MacProcessReader:
    """Kernel executable path and NUL-delimited argv, never ps command text.

    proc_pidpath identifies the executable vnode independently of argv[0].
    KERN_PROCARGS2 supplies argc, an exec path, padding, then argc argv strings.
    Environment bytes returned by sysctl are never parsed or emitted.
    """

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise HelperError("process_listing_failed")
        self.lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        self.lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        self.lib.proc_pidpath.restype = ctypes.c_int
        self.lib.sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
                                   ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                                   ctypes.c_void_p, ctypes.c_size_t]
        self.lib.sysctl.restype = ctypes.c_int

    def executable(self, pid: int) -> Optional[str]:
        """Kernel executable path, None if unreadable, ProcessVanished on ESRCH.

        Only a failed proc_pidpath call whose own errno is exactly ESRCH proves
        the pid exited. errno is cleared first and read straight after (ctypes
        keeps a private copy because the library is opened with use_errno), so
        a stale value can never pass for ESRCH. Every other failure, including
        an errno of zero, an unexpected errno or a malformed length, stays an
        unreadable identity.
        """
        buffer = ctypes.create_string_buffer(4096)  # PROC_PIDPATHINFO_MAXSIZE
        ctypes.set_errno(0)
        count = self.lib.proc_pidpath(pid, buffer, len(buffer))
        if count == 0 and ctypes.get_errno() == errno.ESRCH:
            raise ProcessVanished()
        if count <= 0 or count >= len(buffer):
            return None
        return os.fsdecode(buffer.value)

    def argv(self, pid: int) -> Optional[Tuple[str, ...]]:
        mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
        buffer = ctypes.create_string_buffer(262144)
        size = ctypes.c_size_t(len(buffer))
        if self.lib.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
            return None
        return self.parse_argv(buffer.raw[:size.value])

    @staticmethod
    def parse_argv(raw: bytes) -> Optional[Tuple[str, ...]]:
        if len(raw) < 5:
            return None
        argc = int.from_bytes(raw[:4], byteorder=sys.byteorder, signed=True)
        if not 1 <= argc <= 20000:
            return None
        offset = raw.find(b"\0", 4)  # skip exec path, not argv[0]
        if offset < 0:
            return None
        while offset < len(raw) and raw[offset] == 0:
            offset += 1
        arguments = []
        for _ in range(argc):
            end = raw.find(b"\0", offset)
            if end < 0:
                return None
            arguments.append(os.fsdecode(raw[offset:end]))
            offset = end + 1
        return tuple(arguments)


class PsProcessLister:
    """ps enumerates PIDs; kernel paths classify them; argv is target-only."""

    PS = "/bin/ps"

    def __init__(self, runner: Callable[..., Any] = subprocess.run,
                 native: Optional[Any] = None) -> None:
        self._run = runner
        self._native = native

    @property
    def native(self) -> Any:
        if self._native is None:
            self._native = MacProcessReader()
        return self._native

    def kernel_processes(self, listed: Iterable[ProcessInfo]) -> List[ProcessInfo]:
        found = []
        for process in listed:
            try:
                exe = self.native.executable(process.pid)
            except ProcessVanished:
                continue  # exited after the ps snapshot; the kernel said so
            if not exe:
                raise HelperError("process_listing_failed")
            found.append(ProcessInfo(process.pid, exe))
        return found

    def _ps(self, arguments: Sequence[str]) -> Tuple[int, str]:
        try:
            proc = self._run(
                [self.PS, *arguments],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                timeout=30,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise HelperError("process_listing_failed") from None
        return proc.returncode, proc.stdout.decode("utf-8", "replace")

    def list_all(self) -> List[ProcessInfo]:
        code, text = self._ps(["-axww", "-o", "pid=,comm="])
        if code != 0:
            raise HelperError("process_listing_failed")
        return self.kernel_processes(parse_ps_listing(text))

    def command_line(self, pid: int) -> Optional[Tuple[str, ...]]:
        try:
            before = self.native.executable(pid)
            argv = self.native.argv(pid)
            after = self.native.executable(pid)
        except ProcessVanished:
            return None  # the target exited mid-read: no identity, as before
        if not before or before != after or not argv:
            return None
        # Preserve the two sanctioned Data-volume spellings without accepting
        # an unrelated argv[0] as evidence of executable identity.
        if (argv[0] != before and argv[0] != _DATA_VOLUME_ALIAS + before
                and before != _DATA_VOLUME_ALIAS + argv[0]):
            return None
        return argv


def lsof_listener_pids(port: int, runner: Callable[..., Any] = subprocess.run) -> Set[int]:
    """PIDs with a TCP LISTEN socket on port, at any local address."""
    command = ["/usr/sbin/lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-Fp"]
    try:
        proc = runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/sbin:/usr/bin:/bin", "LC_ALL": "C"},
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise HelperError("listener_lookup_failed") from None
    text = proc.stdout.decode("utf-8", "replace")
    if proc.returncode == 1 and not text.strip():
        return set()  # lsof exits 1 when nothing matches
    if proc.returncode != 0:
        raise HelperError("listener_lookup_failed")
    return {int(line[1:]) for line in text.splitlines() if line.startswith("p") and line[1:].isdigit()}


def _kodi_like(exe: str) -> bool:
    """String-only test: never touches the filesystem for a foreign process."""
    parts = [part.casefold() for part in exe.split("/") if part]
    if not parts:
        return False
    if parts[-1].startswith(_KODI_NAME_PREFIXES):
        return True
    return any(
        part.endswith(".app") and part.startswith(_KODI_NAME_PREFIXES) for part in parts
    )


@dataclass(frozen=True)
class ProcessView:
    test_app: Tuple[ProcessInfo, ...]
    inside_bundle_other: Tuple[ProcessInfo, ...]
    foreign: Tuple[ProcessInfo, ...]
    # Exact sanctioned auxiliary executables only (see AUXILIARY_RELATIVE_PARTS).
    auxiliary: Tuple[ProcessInfo, ...] = ()


def classify_processes(
    processes: Iterable[ProcessInfo], target: TestAppTarget, executable: str
) -> ProcessView:
    aliases = set(target.exe_aliases(executable))
    auxiliary_aliases = set(target.auxiliary_aliases())
    root = os.fspath(target.root)
    inside_prefixes = (root + "/", _DATA_VOLUME_ALIAS + root + "/")
    main: List[ProcessInfo] = []
    auxiliary: List[ProcessInfo] = []
    other: List[ProcessInfo] = []
    foreign: List[ProcessInfo] = []
    for process in processes:
        if process.exe in aliases:
            main.append(process)
        elif process.exe in auxiliary_aliases:
            # Exact kernel-path equality only: never a basename, suffix, prefix,
            # name, argv or parent-pid match. Anything else inside the bundle
            # falls through to ``other`` and is refused.
            auxiliary.append(process)
        elif process.exe.startswith(inside_prefixes):
            other.append(process)
        elif _kodi_like(process.exe):
            foreign.append(process)
    return ProcessView(tuple(main), tuple(other), tuple(foreign), tuple(auxiliary))


@dataclass(frozen=True)
class Identity:
    bundle: BundleInfo
    state: str  # "not_running" | "running_portable"
    pid: Optional[int]
    test_app_process_count: int
    auxiliary_process_count: int = 0

    def report(self) -> Dict[str, Any]:
        bundle = self.bundle
        process: Dict[str, Any] = {
            "pid": self.pid,
            "portable_flag": True if self.state == "running_portable" else None,
            "state": self.state,
            "test_app_process_count": self.test_app_process_count,
        }
        if self.auxiliary_process_count:
            # Audit trail only: a fixed name and a bounded count, never a path.
            process["auxiliary"] = AUXILIARY_NAME
            process["auxiliary_process_count"] = self.auxiliary_process_count
        return {
            "bundle": {
                "build_version": bundle.build_version,
                "executable": bundle.executable,
                "identifier": bundle.identifier,
                "info_plist_sha256": bundle.info_plist_sha256,
                "package_type": bundle.package_type,
                "short_version": bundle.short_version,
            },
            "layout": {
                "addons_dir_present": bundle.addons_dir_present,
                "portable_data_present": bundle.portable_data_present,
                "userdata_dir_present": bundle.userdata_dir_present,
            },
            "process": process,
        }


def identify(services: "Services", require: Optional[str] = None) -> Identity:
    """Prove which Test.app this is and whether exactly one portable instance runs.

    require="not_running" or "running" additionally enforces that process state;
    "not_running" holds only when no main process, no sanctioned auxiliary and
    no other in-bundle process exists. Any ambiguity fails closed.
    """
    bundle = inspect_bundle(services.target)
    try:
        processes = services.process_lister.list_all()
    except HelperError:
        raise
    except Exception:
        raise HelperError("process_listing_failed") from None
    view = classify_processes(processes, services.target, bundle.executable)
    if view.foreign:
        raise HelperError("foreign_kodi_process_present", foreign_kodi_process_count=len(view.foreign))
    if view.inside_bundle_other:
        raise HelperError("test_app_process_mismatch", process_count=len(view.inside_bundle_other))
    if len(view.test_app) > 1:
        raise HelperError("multiple_test_app_processes", process_count=len(view.test_app))
    # The sanctioned auxiliary is accepted only beside exactly one main process
    # that passes every check below. Several are ambiguous, and one on its own
    # is a detached helper that outlived Kodi: the bundle is not quiescent, so
    # it must never read as "not_running" (staging relies on that proof).
    if len(view.auxiliary) > 1 or (view.auxiliary and not view.test_app):
        raise HelperError(
            "test_app_process_mismatch",
            process_count=len(view.auxiliary),
            auxiliary_process_count=len(view.auxiliary),
            test_app_process_count=len(view.test_app),
        )
    if not view.test_app:
        identity = Identity(bundle, "not_running", None, 0)
    else:
        process = view.test_app[0]
        try:
            command = services.process_lister.command_line(process.pid)
        except HelperError:
            raise
        except Exception:
            raise HelperError("test_app_process_ambiguous") from None
        if (not isinstance(command, tuple) or not command
                or command[0] not in services.target.exe_aliases(bundle.executable)):
            raise HelperError("test_app_process_ambiguous", pid=process.pid)
        # -p must be an option, not the value of an unknown/data-path option.
        # Refuse ambiguous prefixes; the documented launch starts with -p.
        portable = False
        for argument in command[1:]:
            if argument == "-p":
                portable = True
                break
            if argument not in ("--debug", "-fs", "--fullscreen", "--standalone",
                                "-q", "--quiet"):
                break
        if not portable:
            raise HelperError("test_app_not_portable", pid=process.pid)
        identity = Identity(bundle, "running_portable", process.pid, 1, len(view.auxiliary))
    if require == "not_running" and identity.state != "not_running":
        raise HelperError("test_app_running", pid=identity.pid)
    if require == "running" and identity.state == "not_running":
        raise HelperError("test_app_not_running")
    return identity


# ---------------------------------------------------------------------------
# Exact candidate source: Git objects of an explicit commit
# ---------------------------------------------------------------------------

_GIT_SAFE_PATH = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
_PATH_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f\\]")
_ALLOWED_GIT_MODES = frozenset({"100644", "100755"})


def find_git() -> Optional[str]:
    return shutil.which("git", path="/usr/bin:/bin")


def _git_environment(git_exe: str) -> Dict[str, str]:
    return {
        "PATH": os.path.dirname(git_exe) + os.pathsep + _GIT_SAFE_PATH,
        "LC_ALL": "C",
        "LANG": "C",
        # Replace refs and user/system config must not influence the bytes.
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


@dataclass(frozen=True)
class CommitIdentity:
    commit: str
    tree: str
    object_format: str  # "sha1" | "sha256"


@dataclass(frozen=True)
class GitTreeEntry:
    mode: str
    oid: str
    path: str


class GitSource:
    """Read-only Git plumbing against one repository (object data only)."""

    def __init__(
        self,
        repo: Path,
        git_exe: Optional[str],
        runner: Callable[..., Any] = subprocess.run,
        timeout: float = 60.0,
    ) -> None:
        if not git_exe:
            raise HelperError("candidate_git_unavailable")
        self.repo = repo
        self.git_exe = git_exe
        self._runner = runner
        self._timeout = timeout

    def _run(
        self, arguments: Sequence[str], *, stdin: Optional[bytes] = None,
        failure: str = "candidate_git_failed",
    ) -> bytes:
        command = [self.git_exe, "--no-pager", "-C", os.fspath(self.repo), *arguments]
        try:
            proc = self._runner(
                command,
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_git_environment(self.git_exe),
                timeout=self._timeout,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise HelperError(failure) from None
        if proc.returncode != 0:
            raise HelperError(failure, returncode=proc.returncode)
        if len(proc.stdout) > MAX_GIT_OUTPUT:
            raise HelperError("candidate_git_output_too_large")
        return proc.stdout

    def resolve_commit(self, commit: str) -> CommitIdentity:
        """Accept only a full object id that names a commit; no refs, no tags."""
        if not (_HEX40.fullmatch(commit) or _HEX64.fullmatch(commit)):
            raise HelperError("candidate_id_invalid")
        kind = self._run(["cat-file", "-t", commit], failure="candidate_commit_missing").strip()
        if kind != b"commit":
            raise HelperError("candidate_not_a_commit")
        verified = self._run(
            ["rev-parse", "--verify", "--quiet", commit + "^{commit}"],
            failure="candidate_commit_missing",
        ).strip().decode("ascii", "replace")
        if verified != commit:
            raise HelperError("candidate_id_mismatch")
        tree = self._run(["rev-parse", "--verify", commit + "^{tree}"]).strip().decode("ascii", "replace")
        object_format = self._run(["rev-parse", "--show-object-format"]).strip().decode("ascii", "replace")
        expected_length = {"sha1": 40, "sha256": 64}.get(object_format)
        if (
            expected_length is None
            or len(commit) != expected_length
            or not re.fullmatch(r"[0-9a-f]{%d}" % expected_length, tree)
        ):
            raise HelperError("candidate_object_format_invalid")
        return CommitIdentity(commit, tree, object_format)

    def subtree_oid(self, identity: CommitIdentity, path: str) -> str:
        oid = self._run(
            ["rev-parse", "--verify", f"{identity.commit}:{path}"]
        ).strip().decode("ascii", "replace")
        if not re.fullmatch(r"[0-9a-f]{%d}" % len(identity.commit), oid):
            raise HelperError("candidate_tree_malformed")
        return oid

    def list_tree(self, identity: CommitIdentity, pathspecs: Sequence[str]) -> List[GitTreeEntry]:
        output = self._run(
            ["ls-tree", "-r", "-z", "--full-tree", identity.commit, "--", *pathspecs]
        )
        entries: List[GitTreeEntry] = []
        for record in output.split(b"\0"):
            if not record:
                continue
            meta, separator, raw_path = record.partition(b"\t")
            fields = meta.split(b" ")
            if not separator or len(fields) != 3:
                raise HelperError("candidate_tree_malformed")
            try:
                mode, kind, oid = (field_.decode("ascii") for field_ in fields)
                path = raw_path.decode("utf-8")
            except UnicodeDecodeError:
                raise HelperError("candidate_unsafe_entry") from None
            if kind != "blob" or mode not in _ALLOWED_GIT_MODES:
                # Symlinks (120000), submodules (160000) and anything else.
                raise HelperError("candidate_unsafe_entry", mode=mode)
            if not re.fullmatch(r"[0-9a-f]{%d}" % len(identity.commit), oid):
                raise HelperError("candidate_tree_malformed")
            validate_repo_path(path)
            entries.append(GitTreeEntry(mode, oid, path))
        return sorted(entries, key=lambda entry: entry.path)

    def read_blobs(self, identity: CommitIdentity, oids: Sequence[str]) -> Dict[str, bytes]:
        """Blob bytes by oid; every blob is re-hashed so objects cannot be swapped."""
        unique = list(dict.fromkeys(oids))
        if not unique:
            return {}
        output = self._run(["cat-file", "--batch"], stdin=("\n".join(unique) + "\n").encode("ascii"))
        position = 0
        blobs: Dict[str, bytes] = {}
        for expected in unique:
            newline = output.find(b"\n", position)
            if newline < 0:
                raise HelperError("candidate_blob_stream_malformed")
            header = output[position:newline].decode("ascii", "replace").split(" ")
            position = newline + 1
            if len(header) != 3 or header[0] != expected or header[1] != "blob":
                raise HelperError("candidate_blob_missing")
            if not header[2].isdigit():
                raise HelperError("candidate_blob_stream_malformed")
            size = int(header[2])
            if size > MAX_BLOB_BYTES:
                raise HelperError("candidate_blob_too_large")
            data = output[position:position + size]
            if len(data) != size or output[position + size:position + size + 1] != b"\n":
                raise HelperError("candidate_blob_stream_malformed")
            position += size + 1
            if git_object_id(b"blob", data, identity.object_format) != expected:
                raise HelperError("candidate_blob_mismatch")
            blobs[expected] = data
        return blobs


def validate_repo_path(path: str) -> None:
    """A repository path must be a plain relative path with safe components."""
    if not path or len(path) > 240 or path.startswith("/") or path.endswith("/"):
        raise HelperError("candidate_unsafe_entry")
    for component in path.split("/"):
        if (
            component in ("", ".", "..")
            or _PATH_BAD_CHARS.search(component)
            or component.casefold() == ".git"
        ):
            raise HelperError("candidate_unsafe_entry")


def _collision_key(path: str) -> str:
    # APFS preserves case and normalization but compares insensitively.
    return unicodedata.normalize("NFD", path).casefold()


@dataclass(frozen=True)
class CandidateFile:
    path: str
    mode: str
    blob: str
    data: bytes

    @property
    def sha256(self) -> str:
        return sha256_hex(self.data)

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class Candidate:
    identity: CommitIdentity
    resources_tree: str
    product: Tuple[CandidateFile, ...]
    tools: Tuple[CandidateFile, ...]
    addon_version: str
    adapter_version: str

    def product_file(self, path: str) -> CandidateFile:
        for item in self.product:
            if item.path == path:
                return item
        raise HelperError("candidate_incomplete")

    def source_file(self, path: str) -> CandidateFile:
        for item in (*self.product, *self.tools):
            if item.path == path:
                return item
        raise HelperError("candidate_incomplete")


def parse_addon_xml(data: bytes) -> Tuple[str, str]:
    """(id, version) of an addon.xml; DTDs and entities are refused outright."""
    if len(data) > MAX_XML_BYTES or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("unsafe xml")
    root = ET.fromstring(data)
    if root.tag != "addon":
        raise ValueError("not an addon")
    addon_id = root.get("id", "")
    version = root.get("version", "")
    if not _ADDON_ID_RE.fullmatch(addon_id) or not _VERSION_RE.fullmatch(version):
        raise ValueError("bad id or version")
    return addon_id, version


def declared_adapter_version(source: bytes) -> Optional[str]:
    """ADAPTER_VERSION read as a literal; the candidate module is never imported."""
    try:
        tree = ast.parse(source, filename="<adapter-support>")
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "ADAPTER_VERSION"
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            return value if isinstance(value, str) and _VERSION_RE.fullmatch(value) else None
    return None


def load_candidate(source: GitSource, commit: str) -> Candidate:
    """Read the product set and the builder inputs of one commit from Git objects."""
    identity = source.resolve_commit(commit)
    product_entries = source.list_tree(identity, [*PRODUCT_ROOT_FILES, *PRODUCT_TREE_DIRS])
    tools_entries = source.list_tree(identity, [BUILDER_TREE_DIR])
    for entry in product_entries:
        if entry.path not in PRODUCT_ROOT_FILES and not any(
            entry.path.startswith(prefix + "/") for prefix in PRODUCT_TREE_DIRS
        ):
            raise HelperError("candidate_unsafe_entry")
    for entry in tools_entries:
        if not entry.path.startswith(BUILDER_TREE_DIR + "/"):
            raise HelperError("candidate_unsafe_entry")
    everything = [*product_entries, *tools_entries]
    if len(everything) > MAX_CANDIDATE_FILES:
        raise HelperError("candidate_too_large")
    keys: Set[str] = set()
    for entry in everything:
        key = _collision_key(entry.path)
        if key in keys:
            raise HelperError("candidate_path_collision")
        keys.add(key)
    for entry in everything:
        # A file may not collide with another entry's parent directory either.
        if any(_collision_key(parent) in keys for parent in _parents(entry.path)):
            raise HelperError("candidate_path_collision")
    product_paths = {entry.path for entry in product_entries}
    tools_paths = {entry.path for entry in tools_entries}
    missing = [path for path in PRODUCT_REQUIRED if path not in product_paths] + [
        path for path in BUILDER_REQUIRED if path not in tools_paths
    ]
    if missing:
        raise HelperError("candidate_incomplete", missing_count=len(missing))
    blobs = source.read_blobs(identity, [entry.oid for entry in everything])
    if sum(len(data) for data in blobs.values()) > MAX_CANDIDATE_BYTES:
        raise HelperError("candidate_too_large")
    product = tuple(CandidateFile(e.path, e.mode, e.oid, blobs[e.oid]) for e in product_entries)
    tools = tuple(CandidateFile(e.path, e.mode, e.oid, blobs[e.oid]) for e in tools_entries)
    candidate_addon = next(item for item in product if item.path == "addon.xml")
    try:
        addon_id, addon_version = parse_addon_xml(candidate_addon.data)
    except (ET.ParseError, ValueError):
        raise HelperError("candidate_addon_xml_invalid") from None
    if addon_id != BUILD_MANAGER_ID:
        raise HelperError("candidate_addon_xml_invalid")
    support = next(item for item in tools if item.path == "tools/bm023a_adapter_support.py")
    adapter_version = declared_adapter_version(support.data)
    if adapter_version is None:
        raise HelperError("candidate_incomplete", reason="adapter_version")
    return Candidate(
        identity=identity,
        resources_tree=source.subtree_oid(identity, "resources"),
        product=product,
        tools=tools,
        addon_version=addon_version,
        adapter_version=adapter_version,
    )


def _parents(path: str) -> List[str]:
    parts = path.split("/")
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


# ---------------------------------------------------------------------------
# Machine-local configuration (schema validated, never holds credentials)
# ---------------------------------------------------------------------------

_CONFIG_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,127}")
_USERNAME_RE = re.compile(r"[A-Za-z0-9._\-@]{1,64}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CREDENTIAL_KEY_RE = re.compile(r"pass|secret|token|credential|auth|cookie|api_?key", re.IGNORECASE)
DEFAULT_RPC_HOST = "127.0.0.1"
DEFAULT_RPC_USERNAME = "kodi"


def _no_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_json_strict(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)


def validate_loopback_host(host: Any) -> str:
    """Loopback IP literals only; hostnames are never resolved."""
    if not isinstance(host, str):
        raise HelperError("rpc_host_not_loopback")
    if host == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise HelperError("rpc_host_not_loopback") from None
    # Only plain 127.0.0.0/8 and ::1. IPv4-mapped IPv6 literals and zone ids are
    # refused outright: how ipaddress classifies them differs between Python versions.
    if "%" in host or (isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None):
        raise HelperError("rpc_host_not_loopback")
    if not address.is_loopback:
        raise HelperError("rpc_host_not_loopback")
    return str(address)


def validate_port(port: Any) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise HelperError("rpc_port_invalid")
    return port


def _scan_credential_keys(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and _CREDENTIAL_KEY_RE.search(key):
                raise HelperError("config_credential_field")
            _scan_credential_keys(value)
    elif isinstance(node, list):
        for item in node:
            _scan_credential_keys(item)


def check_cli_path(raw: Any, services: "Services", *, allow_inside_app: bool = False) -> Path:
    """Normalize a user-supplied path and refuse forbidden/symlinked locations."""
    path = normalize_path(raw)
    if is_forbidden_path(path):
        raise HelperError("argument_path_forbidden")
    if not allow_inside_app and services.target.contains(path):
        raise HelperError("argument_path_inside_test_app")
    try:
        reject_symlink_components(path)
    except FsProblem:
        raise HelperError("argument_path_symlink") from None
    return path


def load_config(path: Path, services: "Services") -> Dict[str, Any]:
    """Validate the machine-local config; returns {"adapter": ..., "rpc": ...}."""
    path = check_cli_path(path, services)
    try:
        raw = read_regular_file(path, MAX_CONFIG_BYTES)
    except FsProblem as exc:
        raise HelperError(
            "argument_path_not_found" if exc.kind == "absent" else "config_unreadable"
        ) from None
    if raw.st_mode & 0o022 or raw.st_uid != os.getuid():
        raise HelperError("config_unsafe_permissions")
    try:
        document = parse_json_strict(raw.data)
    except (ValueError, UnicodeDecodeError):
        raise HelperError("config_invalid", reason="json") from None
    if not isinstance(document, dict):
        raise HelperError("config_invalid", reason="root")
    _scan_credential_keys(document)
    if not set(document) <= {"schema", "adapter", "rpc"} or document.get("schema") != CONFIG_SCHEMA:
        raise HelperError("config_invalid", reason="keys")
    adapter_values: Optional[Dict[str, str]] = None
    if "adapter" in document:
        adapter_values = _validate_adapter_values(document["adapter"], services)
    rpc = _validate_rpc_section(document.get("rpc", {}))
    # The machine-local paths must never be echoed by any output.
    for key in ADAPTER_PATH_KEYS:
        if adapter_values is not None:
            services.secrets.register(adapter_values[key], minimum=8)
    return {"adapter": adapter_values, "rpc": rpc}


def _validate_adapter_values(section: Any, services: Optional["Services"] = None) -> Dict[str, str]:
    if not isinstance(section, dict) or set(section) != set(ADAPTER_CONFIG_KEYS):
        raise HelperError("config_invalid", reason="adapter_keys")
    values: Dict[str, str] = {}
    for key in ADAPTER_CONFIG_KEYS:
        value = section[key]
        if not isinstance(value, str) or not value or len(value) > 4096 or _CONTROL_RE.search(value):
            raise HelperError("config_invalid", reason="adapter_value", key=key)
        if key in ADAPTER_PATH_KEYS:
            if not os.path.isabs(value) or os.path.normpath(value) != value:
                raise HelperError("config_invalid", reason="adapter_path", key=key)
            path = normalize_path(value)
            if services is not None and services.target.contains(path):
                raise HelperError("argument_path_inside_test_app")
            try:
                reject_symlink_components(path)
            except FsProblem:
                raise HelperError("argument_path_symlink") from None
            value = os.fspath(path)
        elif not _CONFIG_ID_RE.fullmatch(value):
            raise HelperError("config_invalid", reason="adapter_id", key=key)
        values[key] = value
    return values


def _validate_rpc_section(section: Any) -> Dict[str, Any]:
    if not isinstance(section, dict) or not set(section) <= {"host", "port", "username"}:
        raise HelperError("config_invalid", reason="rpc_keys")
    rpc: Dict[str, Any] = {}
    if "host" in section:
        rpc["host"] = validate_loopback_host(section["host"])
    if "port" in section:
        rpc["port"] = validate_port(section["port"])
    if "username" in section:
        if not isinstance(section["username"], str) or not _USERNAME_RE.fullmatch(section["username"]):
            raise HelperError("config_invalid", reason="rpc_username")
        rpc["username"] = section["username"]
    return rpc


def config_fingerprint(values: Mapping[str, str]) -> str:
    """Fingerprint of the six adapter values; the values themselves never leave."""
    canonical = json.dumps({key: values[key] for key in ADAPTER_CONFIG_KEYS}, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256_hex(b"bm-test-app-config-fingerprint/1\n" + canonical.encode("utf-8"))


# ---------------------------------------------------------------------------
# Driver build: run the CANDIDATE's own builder on a temp export of the commit
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DriverBuild:
    files: Tuple[Tuple[str, bytes], ...]
    addon_version: str
    adapter_version: str
    frozen_install_sha256: str

    def data(self, name: str) -> bytes:
        return dict(self.files)[name]


def export_candidate(workspace: Path, candidate: Candidate) -> Path:
    """Write the product and builder files of the commit into workspace/export."""
    export_root = workspace / "export"
    try:
        os.mkdir(export_root, 0o700)
        for item in (*candidate.product, *candidate.tools):
            destination = export_root / item.path
            if not is_inside(destination, export_root):
                raise HelperError("candidate_export_failed")
            os.makedirs(destination.parent, mode=0o700, exist_ok=True)
            write_new_file(destination, item.data, 0o755 if item.mode == "100755" else 0o644)
    except OSError:
        raise HelperError("candidate_export_failed") from None
    return export_root


def _parse_adapter_config(source: bytes) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for node in ast.parse(source, filename="<adapter-config>").body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            raise ValueError("unexpected statement")
        key = node.targets[0].id
        value = ast.literal_eval(node.value)
        if not isinstance(value, str) or key in values:
            raise ValueError("bad assignment")
        values[key] = value
    return values


def build_driver(
    candidate: Candidate,
    adapter_values: Mapping[str, str],
    workspace: Path,
    python_exe: str,
    runner: Callable[..., Any] = subprocess.run,
) -> DriverBuild:
    export_root = export_candidate(workspace, candidate)
    config_dir = workspace / "cfg"
    output_dir = workspace / "driver-out"
    try:
        os.mkdir(config_dir, 0o700)
        os.mkdir(output_dir, 0o700)
        # The six machine-local values reach the builder through a private file
        # (its existing --reuse-config-from input), never through argv.
        config_text = "".join(f"{key} = {adapter_values[key]!r}\n" for key in ADAPTER_CONFIG_KEYS)
        config_file = config_dir / "adapter_config_input.py"
        write_new_file(config_file, config_text.encode("utf-8"), 0o600)
    except OSError:
        raise HelperError("driver_build_failed", reason="workspace") from None
    command = [
        python_exe, "-I", "-B",
        os.fspath(export_root / "tools" / "build_bm023a_adapter.py"),
        "--output-dir", os.fspath(output_dir),
        "--reuse-config-from", os.fspath(config_file),
    ]
    try:
        proc = runner(
            command,
            cwd=os.fspath(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=120,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise HelperError("driver_build_failed", reason="launch") from None
    if proc.returncode != 0:
        raise HelperError("driver_build_failed", returncode=proc.returncode)
    driver_dir = output_dir / DRIVER_ID
    try:
        listing = walk_tree(driver_dir)
        if any(entry.kind != "file" for entry in listing) or sorted(
            entry.rel for entry in listing
        ) != sorted(DRIVER_FILES):
            raise HelperError("driver_output_unexpected")
        files = {name: read_regular_file(driver_dir / name, MAX_BLOB_BYTES).data for name in DRIVER_FILES}
    except FsProblem:
        raise HelperError("driver_output_unexpected") from None
    for name, source_path in DRIVER_SOURCE_PATHS.items():
        if files[name] != candidate.source_file(source_path).data:
            raise HelperError("driver_source_mismatch", file=name)
    frozen_digest = candidate.source_file("resources/lib/frozen_install.py").sha256
    try:
        generated = _parse_adapter_config(files["adapter_config.py"])
    except (SyntaxError, ValueError):
        raise HelperError("driver_config_mismatch") from None
    expected_keys = set(ADAPTER_CONFIG_KEYS) | {"EXPECTED_FROZEN_INSTALL_SHA256"}
    if set(generated) != expected_keys or any(
        generated[key] != adapter_values[key] for key in ADAPTER_CONFIG_KEYS
    ) or generated["EXPECTED_FROZEN_INSTALL_SHA256"] != frozen_digest:
        raise HelperError("driver_config_mismatch")
    try:
        driver_id, driver_version = parse_addon_xml(files["addon.xml"])
    except (ET.ParseError, ValueError):
        raise HelperError("driver_version_mismatch") from None
    if driver_id != DRIVER_ID or driver_version != candidate.adapter_version:
        raise HelperError("driver_version_mismatch")
    return DriverBuild(
        files=tuple(sorted(files.items())),
        addon_version=driver_version,
        adapter_version=candidate.adapter_version,
        frozen_install_sha256=frozen_digest,
    )


# ---------------------------------------------------------------------------
# Stage manifest: binds the exact staged bytes
# ---------------------------------------------------------------------------

def tool_identity() -> Dict[str, str]:
    try:
        digest = sha256_hex(Path(__file__).resolve().read_bytes())
    except OSError:
        digest = "0" * 64
    return {"name": HELPER_NAME, "schema": OUTPUT_SCHEMA, "sha256": digest}


def build_manifest(
    candidate: Candidate,
    driver: DriverBuild,
    fingerprint: str,
    created_utc: str,
) -> Dict[str, Any]:
    product = sorted(candidate.product, key=lambda item: item.path)
    build_manager_files = [
        {
            "git_blob": item.blob,
            "git_mode": item.mode,
            "path": item.path,
            "sha256": item.sha256,
            "size": item.size,
        }
        for item in product
    ]
    driver_files = []
    for name, data in driver.files:
        source_path = DRIVER_SOURCE_PATHS.get(name)
        driver_files.append({
            "generated": source_path is None,
            "path": name,
            "sha256": sha256_hex(data),
            "size": len(data),
            "source_git_blob": candidate.source_file(source_path).blob if source_path else None,
            "source_git_path": source_path,
        })
    tool = tool_identity()
    return {
        "build_manager": {
            "addon_id": BUILD_MANAGER_ID,
            "addon_version": candidate.addon_version,
            "file_count": len(build_manager_files),
            "files": build_manager_files,
            "install_dir": BUILD_MANAGER_ID,
            "total_bytes": sum(entry["size"] for entry in build_manager_files),
            "tree_sha256": tree_digest(
                (entry["path"], entry["sha256"], entry["size"]) for entry in build_manager_files
            ),
        },
        "candidate": {
            "commit": candidate.identity.commit,
            "object_format": candidate.identity.object_format,
            "resources_tree": candidate.resources_tree,
            "tree": candidate.identity.tree,
        },
        "configuration_fingerprint": fingerprint,
        "created_utc": created_utc,
        "driver": {
            "addon_id": DRIVER_ID,
            "addon_version": driver.addon_version,
            "adapter_version": driver.adapter_version,
            "default_py_sha256": sha256_hex(driver.data("default.py")),
            "file_count": len(driver_files),
            "files": driver_files,
            "frozen_install_sha256": driver.frozen_install_sha256,
            "install_dir": DRIVER_ID,
            "total_bytes": sum(entry["size"] for entry in driver_files),
            "tree_sha256": tree_digest(
                (entry["path"], entry["sha256"], entry["size"]) for entry in driver_files
            ),
        },
        "ignored_runtime_artifacts": ["__pycache__"],
        "schema": MANIFEST_SCHEMA,
        "tool": {"name": tool["name"], "sha256": tool["sha256"]},
    }


def manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return canonical_json(manifest).encode("ascii")


def _need(condition: bool, name: str) -> None:
    if not condition:
        raise HelperError("manifest_invalid", field=name)


def _is_hex(value: Any, length: int = 64) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _manifest_path_ok(path: Any) -> bool:
    if not isinstance(path, str) or not path or len(path) > 240 or path.startswith("/"):
        return False
    return all(
        part not in ("", ".", "..") and not _PATH_BAD_CHARS.search(part) and part.casefold() != ".git"
        for part in path.split("/")
    )


def _validate_tree_files(files: Any, key_set: frozenset, name: str) -> None:
    _need(isinstance(files, list) and 0 < len(files) <= MAX_CANDIDATE_FILES, name)
    seen: Set[str] = set()
    previous = ""
    for entry in files:
        _need(isinstance(entry, dict) and set(entry) == key_set, name)
        path = entry["path"]
        _need(_manifest_path_ok(path) and path > previous, name + ".path")
        previous = path
        collision = _collision_key(path)
        _need(collision not in seen, name + ".collision")
        seen.add(collision)
        _need(_is_hex(entry["sha256"]) and _is_count(entry["size"]), name + ".hash")
    for entry in files:
        for parent in _parents(entry["path"]):
            _need(_collision_key(parent) not in seen, name + ".collision")


_BM_FILE_KEYS = frozenset({"git_blob", "git_mode", "path", "sha256", "size"})
_DRIVER_FILE_KEYS = frozenset({"generated", "path", "sha256", "size", "source_git_blob", "source_git_path"})
_TREE_KEYS = frozenset({
    "addon_id", "addon_version", "file_count", "files", "install_dir", "total_bytes", "tree_sha256",
})


def validate_manifest(document: Any) -> Dict[str, Any]:
    """Strict, closed-schema validation; unknown keys and bad shapes are refused."""
    _need(isinstance(document, dict), "root")
    _need(
        set(document) == {
            "build_manager", "candidate", "configuration_fingerprint", "created_utc", "driver",
            "ignored_runtime_artifacts", "schema", "tool",
        },
        "keys",
    )
    _need(document["schema"] == MANIFEST_SCHEMA, "schema")
    _need(isinstance(document["created_utc"], str) and _UTC_RE.fullmatch(document["created_utc"]), "created_utc")
    _need(document["ignored_runtime_artifacts"] == ["__pycache__"], "ignored_runtime_artifacts")
    fingerprint = document["configuration_fingerprint"]
    _need(isinstance(fingerprint, str) and fingerprint.startswith("sha256:") and _is_hex(fingerprint[7:]), "configuration_fingerprint")
    tool = document["tool"]
    _need(isinstance(tool, dict) and set(tool) == {"name", "sha256"} and tool["name"] == HELPER_NAME and _is_hex(tool["sha256"]), "tool")
    candidate = document["candidate"]
    _need(isinstance(candidate, dict) and set(candidate) == {"commit", "object_format", "resources_tree", "tree"}, "candidate")
    length = {"sha1": 40, "sha256": 64}.get(candidate["object_format"])
    _need(length is not None, "candidate.object_format")
    for key in ("commit", "resources_tree", "tree"):
        _need(_is_hex(candidate[key], length), "candidate." + key)

    build_manager = document["build_manager"]
    _need(isinstance(build_manager, dict) and set(build_manager) == _TREE_KEYS, "build_manager")
    _need(build_manager["addon_id"] == BUILD_MANAGER_ID and build_manager["install_dir"] == BUILD_MANAGER_ID, "build_manager.addon_id")
    _need(isinstance(build_manager["addon_version"], str) and _VERSION_RE.fullmatch(build_manager["addon_version"]), "build_manager.addon_version")
    _validate_tree_files(build_manager["files"], _BM_FILE_KEYS, "build_manager.files")
    for entry in build_manager["files"]:
        _need(entry["git_mode"] in _ALLOWED_GIT_MODES and _is_hex(entry["git_blob"], length), "build_manager.files.git")
    _check_tree_totals(build_manager, "build_manager")

    driver = document["driver"]
    _need(isinstance(driver, dict) and set(driver) == _TREE_KEYS | {"adapter_version", "default_py_sha256", "frozen_install_sha256"}, "driver")
    _need(driver["addon_id"] == DRIVER_ID and driver["install_dir"] == DRIVER_ID, "driver.addon_id")
    for key in ("addon_version", "adapter_version"):
        _need(isinstance(driver[key], str) and _VERSION_RE.fullmatch(driver[key]), "driver." + key)
    _need(_is_hex(driver["default_py_sha256"]) and _is_hex(driver["frozen_install_sha256"]), "driver.hashes")
    _validate_tree_files(driver["files"], _DRIVER_FILE_KEYS, "driver.files")
    _need([entry["path"] for entry in driver["files"]] == sorted(DRIVER_FILES), "driver.files.set")
    for entry in driver["files"]:
        expected_source = DRIVER_SOURCE_PATHS.get(entry["path"])
        _need(
            entry["generated"] is (expected_source is None)
            and entry["source_git_path"] == expected_source
            and (entry["source_git_blob"] is None if expected_source is None else _is_hex(entry["source_git_blob"], length)),
            "driver.files.source",
        )
    _check_tree_totals(driver, "driver")
    return document


def _check_tree_totals(tree: Mapping[str, Any], name: str) -> None:
    files = tree["files"]
    _need(tree["file_count"] == len(files), name + ".file_count")
    _need(tree["total_bytes"] == sum(entry["size"] for entry in files), name + ".total_bytes")
    _need(
        tree["tree_sha256"] == tree_digest((entry["path"], entry["sha256"], entry["size"]) for entry in files),
        name + ".tree_sha256",
    )


def load_manifest(path: Any, services: "Services") -> Tuple[Dict[str, Any], str]:
    """(validated manifest, sha256 of the exact file bytes)."""
    checked = check_cli_path(path, services)
    try:
        raw = read_regular_file(checked, MAX_MANIFEST_BYTES)
    except FsProblem as exc:
        if exc.kind == "too_large":
            raise HelperError("manifest_too_large") from None
        raise HelperError(
            "argument_path_not_found" if exc.kind == "absent" else "manifest_unreadable"
        ) from None
    try:
        document = parse_json_strict(raw.data)
    except (ValueError, UnicodeDecodeError):
        raise HelperError("manifest_invalid", field="json") from None
    return validate_manifest(document), sha256_hex(raw.data)


# ---------------------------------------------------------------------------
# verify: installed trees against the stage manifest
# ---------------------------------------------------------------------------

def verify_tree_dir(directory: Path, tree: Mapping[str, Any], object_format: str) -> Dict[str, Any]:
    """Compare one directory with a manifest tree. Reports booleans, counts, names."""
    expected = {entry["path"]: entry for entry in tree["files"]}
    expected_dirs = {parent for path in expected for parent in _parents(path)}
    problems: List[str] = []
    missing: List[str] = []
    unexpected: List[str] = []
    unexpected_dirs: List[str] = []
    modified: List[str] = []
    symlinks: List[str] = []
    special: List[str] = []
    unreadable: List[str] = []
    blob_mismatch: List[str] = []
    found: Dict[str, Tuple[str, int]] = {}
    pycache_dirs = 0
    pyc_files = 0
    try:
        lstat_real_dir(directory)
        listing = walk_tree(directory)
    except FsProblem as exc:
        listing = []
        problems.append({
            "absent": "addon_dir_missing",
            "symlink": "addon_dir_is_symlink",
            "not_directory": "addon_dir_not_directory",
        }.get(exc.kind, "addon_dir_unreadable" if exc.kind == "unreadable" else "tree_too_large"))
    for entry in listing:
        parts = entry.rel.split("/")
        if entry.kind == "symlink":
            symlinks.append(entry.rel)
            continue
        if entry.kind == "other":
            special.append(entry.rel)
            continue
        if "__pycache__" in parts:
            index = parts.index("__pycache__")
            if index == len(parts) - 1 and entry.kind == "dir":
                pycache_dirs += 1
                continue
            if index == len(parts) - 2 and entry.kind == "file" and _PYC_NAME_RE.fullmatch(parts[-1]):
                pyc_files += 1
                continue
            unexpected.append(entry.rel)
            continue
        if entry.kind == "dir":
            if entry.rel in expected:
                modified.append(entry.rel)
            elif entry.rel not in expected_dirs:
                unexpected_dirs.append(entry.rel)
            continue
        try:
            content = read_regular_file(directory / entry.rel, MAX_BLOB_BYTES)
        except FsProblem:
            unreadable.append(entry.rel)
            continue
        digest = sha256_hex(content.data)
        found[entry.rel] = (digest, len(content.data))
        wanted = expected.get(entry.rel)
        if wanted is None:
            unexpected.append(entry.rel)
        elif digest != wanted["sha256"] or len(content.data) != wanted["size"]:
            modified.append(entry.rel)
        else:
            blob = wanted.get("git_blob", wanted.get("source_git_blob"))
            if blob is not None and git_object_id(b"blob", content.data, object_format) != blob:
                blob_mismatch.append(entry.rel)
    missing = [path for path in expected if path not in found and path not in modified and path not in unreadable]
    for name, items in (
        ("missing_files", missing), ("unexpected_files", unexpected),
        ("unexpected_directories", unexpected_dirs), ("modified_files", modified),
        ("symlinks_present", symlinks), ("special_files_present", special),
        ("unreadable_files", unreadable), ("git_blob_mismatch", blob_mismatch),
    ):
        if items:
            problems.append(name)
    shown: Dict[str, Any] = {}
    truncated = False
    for key, items in (
        ("missing", missing), ("unexpected", unexpected), ("unexpected_directories", unexpected_dirs),
        ("modified", modified), ("symlinks", symlinks), ("special", special),
        ("unreadable", unreadable), ("git_blob_mismatch", blob_mismatch),
    ):
        names, cut = capped(items)
        shown[key] = names
        shown[key + "_count"] = len(items)
        truncated = truncated or cut
    report: Dict[str, Any] = {
        "addon_id": tree["addon_id"],
        "expected_file_count": len(expected),
        "found_file_count": len(found),
        "ignored_pycache_dirs": pycache_dirs,
        "ignored_pyc_files": pyc_files,
        "lists_truncated": truncated,
        "ok": not problems,
        "problems": problems,
        "tree_sha256_actual": tree_digest((path, digest, size) for path, (digest, size) in found.items()),
        "tree_sha256_expected": tree["tree_sha256"],
    }
    report.update(shown)
    return report


def verify_git_binding(
    services: "Services", manifest: Mapping[str, Any], repo: Path
) -> Dict[str, Any]:
    """Prove the manifest's blob ids are exactly what the candidate commit holds."""
    problems: List[str] = []
    try:
        source = GitSource(repo, services.git_exe, services.git_runner)
        identity = source.resolve_commit(manifest["candidate"]["commit"])
        if identity.tree != manifest["candidate"]["tree"]:
            problems.append("tree_mismatch")
        if identity.object_format != manifest["candidate"]["object_format"]:
            problems.append("object_format_mismatch")
        if source.subtree_oid(identity, "resources") != manifest["candidate"]["resources_tree"]:
            problems.append("resources_tree_mismatch")
        product = {e.path: e for e in source.list_tree(identity, [*PRODUCT_ROOT_FILES, *PRODUCT_TREE_DIRS])}
        tool_paths = sorted({
            entry["source_git_path"] for entry in manifest["driver"]["files"]
            if entry["source_git_path"] and entry["source_git_path"].startswith(BUILDER_TREE_DIR + "/")
        })
        tools = {e.path: e for e in source.list_tree(identity, tool_paths)} if tool_paths else {}
    except HelperError as exc:
        return {"checked": True, "ok": False, "problems": [exc.code]}
    wanted = {entry["path"]: entry for entry in manifest["build_manager"]["files"]}
    if set(product) != set(wanted):
        problems.append("product_set_mismatch")
    if any(
        path not in product or product[path].oid != entry["git_blob"] or product[path].mode != entry["git_mode"]
        for path, entry in wanted.items()
    ):
        problems.append("product_blob_mismatch")
    for entry in manifest["driver"]["files"]:
        source_path = entry["source_git_path"]
        if source_path is None:
            continue
        found = product.get(source_path) or tools.get(source_path)
        if found is None or found.oid != entry["source_git_blob"]:
            problems.append("driver_source_blob_mismatch")
            break
    return {
        "candidate_tree": identity.tree,
        "checked": True,
        "ok": not problems,
        "problems": sorted(set(problems)),
    }


def verify_installed(
    services: "Services", manifest: Mapping[str, Any], *, git_repo: Optional[Path]
) -> Dict[str, Any]:
    """Read-only comparison of both installed trees with the manifest."""
    target = services.target
    object_format = manifest["candidate"]["object_format"]
    trees: Dict[str, Any] = {}
    for key in ("build_manager", "driver"):
        tree = manifest[key]
        directory = target.addon_dir(tree["install_dir"])
        try:
            target.require_chain(directory)
        except HelperError:
            trees[tree["addon_id"]] = {
                "addon_id": tree["addon_id"], "ok": False, "problems": ["addon_dir_path_symlink"],
            }
            continue
        trees[tree["addon_id"]] = verify_tree_dir(directory, tree, object_format)
    equals_manifest = all(report["ok"] for report in trees.values())
    binding: Dict[str, Any] = {"checked": False}
    if git_repo is not None:
        binding = verify_git_binding(services, manifest, git_repo)
    return {
        "git_binding": binding,
        "installed_equals_candidate": bool(equals_manifest and binding.get("ok") is True),
        "installed_equals_manifest": equals_manifest,
        "trees": trees,
    }


# ---------------------------------------------------------------------------
# stage: exact candidate -> portable add-ons directory, with rollback
# ---------------------------------------------------------------------------

def _make_dir(path: Path, mode: int = 0o755) -> None:
    os.mkdir(os.fspath(path), mode)
    os.chmod(os.fspath(path), mode)


def write_tree(root: Path, files: Sequence[Tuple[str, bytes, int]]) -> None:
    """Create root (which must not exist) holding exactly these files."""
    _make_dir(root)
    made: Set[str] = {""}
    for relative, data, mode in files:
        current = ""
        for part in relative.split("/")[:-1]:
            current = f"{current}/{part}" if current else part
            if current not in made:
                _make_dir(root / current)
                made.add(current)
        write_new_file(root / relative, data, mode)


def fingerprint_tree(root: Path) -> Dict[str, Any]:
    """Content fingerprint of a live tree: files by hash, symlinks by target."""
    rows: List[str] = []
    counts: Dict[str, Any] = {"bytes": 0, "directories": 0, "files": 0, "special": 0, "symlinks": 0}
    for entry in walk_tree(root):
        full = root / entry.rel
        if entry.kind == "file":
            content = read_regular_file(full, MAX_FILE_BYTES)
            fields = ("f", entry.rel, sha256_hex(content.data), str(len(content.data)))
            counts["files"] += 1
            counts["bytes"] += len(content.data)
        elif entry.kind == "symlink":
            link_text = os.readlink(full).encode("utf-8", "surrogateescape")
            fields = ("l", entry.rel, sha256_hex(link_text), "0")
            counts["symlinks"] += 1
        elif entry.kind == "dir":
            fields = ("d", entry.rel, "", "0")
            counts["directories"] += 1
        else:
            fields = ("o", entry.rel, "", "0")
            counts["special"] += 1
        rows.append("\0".join(fields))
    counts["digest"] = sha256_hex("\n".join(rows).encode("utf-8", "surrogateescape"))
    return counts


def copy_tree_exact(source: Path, destination: Path) -> None:
    """Byte-faithful copy that never follows symlinks (destination must not exist)."""
    listing = walk_tree(source)
    _make_dir(destination, 0o700)
    for entry in listing:
        origin = source / entry.rel
        target = destination / entry.rel
        if entry.kind == "dir":
            _make_dir(target, 0o700)
        elif entry.kind == "file":
            content = read_regular_file(origin, MAX_FILE_BYTES)
            write_new_file(target, content.data, stat.S_IMODE(content.st_mode) or 0o600)
            os.utime(os.fspath(target), ns=(content.st_mtime_ns, content.st_mtime_ns))
        elif entry.kind == "symlink":
            os.symlink(os.readlink(origin), os.fspath(target))
        # Special files cannot be copied; fingerprint_tree counts them so the
        # backup comparison fails closed instead of silently dropping them.


def _live_state(path: Path) -> str:
    """"absent" or "dir"; anything else (symlink, file) is refused."""
    try:
        lstat_real_dir(path)
    except FsProblem as exc:
        if exc.kind == "absent":
            return "absent"
        raise HelperError(
            "bundle_path_symlink" if exc.kind == "symlink" else "layout_missing"
        ) from None
    return "dir"


def _exists(path: Path) -> bool:
    try:
        os.lstat(os.fspath(path))
    except FileNotFoundError:
        return False
    return True


def _same_device(first: Path, second: Path) -> bool:
    """Renames between the two are atomic only on one filesystem."""
    try:
        return os.lstat(os.fspath(first)).st_dev == os.lstat(os.fspath(second)).st_dev
    except OSError:
        return False


def _has_entries(path: Path) -> bool:
    with os.scandir(os.fspath(path)) as iterator:
        return any(True for _ in iterator)


def _remove_stage_area(target: TestAppTarget, *, discard_old: bool) -> bool:
    """Remove the helper-owned staging area only while its full path is safe.

    Unless discard_old is set (only after every replaced tree has a verified
    evidence copy), an area whose old/ directory still holds anything is kept.
    Validate the complete bundle-to-area chain before cleanup: lstat of only
    the final node does not detect an ancestor symlink and rmtree would then
    follow it to a relocated stage area.
    """
    area = target.stage_area
    try:
        target.require_chain(area)
        lstat_real_dir(area)
        if not discard_old and _exists(area / "old") and _has_entries(area / "old"):
            return False
        # Recheck immediately before the destructive traversal in case the
        # chain changed while the retained-old check was running.
        target.require_chain(area)
        lstat_real_dir(area)
        shutil.rmtree(area)
    except (FsProblem, HelperError, OSError):
        return False
    return True


def _swap_in(target: TestAppTarget, area: Path, addon_ids: Sequence[str]) -> List[Tuple[str, str]]:
    """Rename live -> old and new -> live for each add-on, all-or-nothing.

    Each step is recorded BEFORE its rename so an interruption in between is
    still rolled back (rollback skips steps that never took place).
    """
    target.require_chain(target.addons_dir)
    target.require_chain(area)
    done: List[Tuple[str, str]] = []
    try:
        for addon_id in addon_ids:
            live = target.addon_dir(addon_id)
            if _live_state(live) == "dir":
                done.append(("old", addon_id))
                os.rename(os.fspath(live), os.fspath(area / "old" / addon_id))
            done.append(("new", addon_id))
            os.rename(os.fspath(area / "new" / addon_id), os.fspath(live))
    except BaseException:
        _rollback(target, area, done)
        raise
    return done


def _rollback(target: TestAppTarget, area: Path, done: Sequence[Tuple[str, str]]) -> None:
    """Undo recorded steps newest-first; never deletes, only renames back/aside."""
    failures = 0
    for action, addon_id in reversed(done):
        live = target.addon_dir(addon_id)
        try:
            if action == "new":
                if _exists(area / "new" / addon_id):
                    continue  # the new tree never left the staging area
                os.rename(os.fspath(live), os.fspath(area / "failed" / addon_id))
            else:
                if not _exists(area / "old" / addon_id):
                    continue  # the live tree never moved aside
                os.rename(os.fspath(area / "old" / addon_id), os.fspath(live))
        except OSError:
            failures += 1
    if failures:
        raise HelperError("rollback_failed", failed_steps=failures)


def run_stage(
    services: "Services",
    *,
    candidate_id: str,
    config: Mapping[str, Any],
    repo: Path,
    evidence_dir: Optional[Path],
    dry_run: bool,
) -> Dict[str, Any]:
    target = services.target
    repo = check_cli_path(repo, services)
    if evidence_dir is not None:
        evidence_dir = check_cli_path(evidence_dir, services)
    adapter_values = config.get("adapter")
    if adapter_values is None:
        raise HelperError("config_missing_section", section="adapter")
    adapter_values = _validate_adapter_values(adapter_values, services)
    identity_before = identify(services, require="not_running")
    if not (identity_before.bundle.portable_data_present and identity_before.bundle.addons_dir_present):
        raise HelperError("layout_missing")
    source = GitSource(repo, services.git_exe, services.git_runner)
    candidate = load_candidate(source, candidate_id)
    fingerprint = config_fingerprint(adapter_values)
    # Explicit placement: never let tempfile consult inherited TMPDIR.
    workspace_root = check_cli_path(services.tmp_root or Path("/private/tmp"), services)
    try:
        lstat_real_dir(workspace_root)
    except FsProblem:
        raise HelperError("argument_path_invalid") from None
    workspace = Path(tempfile.mkdtemp(prefix="bm-test-app-", dir=workspace_root))
    try:
        driver = build_driver(candidate, adapter_values, workspace, services.python_exe, services.build_runner)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    created = iso_utc(services.clock.utcnow())
    manifest = build_manifest(candidate, driver, fingerprint, created)
    manifest_data = manifest_bytes(manifest)
    manifest_sha = sha256_hex(manifest_data)
    addon_ids = (BUILD_MANAGER_ID, DRIVER_ID)
    payload: Dict[str, Any] = {
        "candidate": manifest["candidate"],
        "command": "stage",
        "dry_run": dry_run,
        "identity_before": identity_before.report(),
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "ok": True,
    }
    if dry_run:
        payload["would_replace"] = {
            addon_id: _live_state(target.addon_dir(addon_id)) == "dir" for addon_id in addon_ids
        }
        return payload
    if evidence_dir is None:
        raise HelperError("evidence_dir_invalid")
    try:
        lstat_real_dir(evidence_dir)
    except FsProblem:
        raise HelperError("evidence_dir_invalid") from None
    if services.secrets.leaks(os.fspath(evidence_dir)):
        # Output naming this directory would be blocked by the leak guard.
        raise HelperError("evidence_dir_invalid", reason="overlaps_config_value")
    stamp = created.replace("-", "").replace(":", "")
    run_dir = evidence_dir / f"stage-{stamp}-{candidate.identity.commit[:12]}"
    try:
        os.mkdir(os.fspath(run_dir), 0o700)
    except FileExistsError:
        raise HelperError("evidence_exists") from None
    except OSError:
        raise HelperError("evidence_dir_invalid") from None
    manifest_path = run_dir / "stage_manifest.json"
    write_new_file_atomic(manifest_path, manifest_data, 0o600)
    new_files = {
        BUILD_MANAGER_ID: [
            (item.path, item.data, 0o755 if item.mode == "100755" else 0o644)
            for item in sorted(candidate.product, key=lambda item: item.path)
        ],
        DRIVER_ID: [(name, data, 0o644) for name, data in driver.files],
    }
    try:
        outcome = _apply_stage(services, manifest, new_files, run_dir, addon_ids)
    except BaseException as exc:
        _record_stage_failure(run_dir, payload, exc)
        raise
    payload.update({
        "evidence": {
            "manifest_path": os.fspath(manifest_path),
            "result_path": os.fspath(run_dir / "stage_result.json"),
            "run_dir": os.fspath(run_dir),
        },
        "installed_dirs": list(addon_ids),
    })
    payload.update(outcome)
    write_new_file_atomic(run_dir / "stage_result.json", canonical_json(payload).encode("ascii"), 0o600)
    return payload


def _record_stage_failure(run_dir: Path, payload: Mapping[str, Any], error: BaseException) -> None:
    """Best-effort evidence that a stage did not complete (never raises)."""
    if isinstance(error, HelperError):
        code, detail = error.code, error.detail
    else:
        code = "interrupted" if isinstance(error, KeyboardInterrupt) else "unexpected_error"
        detail = {}
    record = {
        "candidate": payload["candidate"],
        "command": "stage",
        "error": {"code": code, "detail": detail},
        "manifest_sha256": payload["manifest_sha256"],
        "ok": False,
        "schema": OUTPUT_SCHEMA,
    }
    try:
        write_new_file_atomic(run_dir / "stage_result.json", canonical_json(record).encode("ascii"), 0o600)
    except Exception:
        pass


def _backup_live_trees(
    target: TestAppTarget, run_dir: Path, addon_ids: Sequence[str]
) -> Dict[str, Any]:
    """Copy every live tree that will be replaced into the evidence directory."""
    replaced: Dict[str, Any] = {}
    try:
        for addon_id in addon_ids:
            live = target.addon_dir(addon_id)
            if _live_state(live) == "absent":
                replaced[addon_id] = {"backed_up": False, "existed": False}
                continue
            before = fingerprint_tree(live)
            backup = run_dir / "replaced" / addon_id
            os.makedirs(os.fspath(backup.parent), mode=0o700, exist_ok=True)
            copy_tree_exact(live, backup)
            after = fingerprint_tree(backup)
            if after != before:
                raise HelperError("stage_backup_failed", addon_id=addon_id)
            replaced[addon_id] = {
                "backed_up": True,
                "backup_dir": os.fspath(backup),
                "backup_file_count": after["files"],
                "backup_tree_digest": after["digest"],
                "existed": True,
            }
    except (OSError, FsProblem):
        raise HelperError("stage_backup_failed") from None
    return replaced


def _recheck_backups(replaced: Mapping[str, Any]) -> None:
    for addon_id, info in replaced.items():
        if not info["backed_up"]:
            continue
        try:
            current = fingerprint_tree(Path(info["backup_dir"]))["digest"]
        except (OSError, FsProblem):
            current = None
        if current != info["backup_tree_digest"]:
            raise HelperError("stage_backup_failed", addon_id=addon_id)


def _check_moved_old(target: TestAppTarget, replaced: Mapping[str, Any],
                     addon_ids: Sequence[str]) -> None:
    """No moved-aside live bytes may be discarded without matching evidence."""
    for addon_id in addon_ids:
        old = target.stage_area / "old" / addon_id
        info = replaced[addon_id]
        try:
            present = _live_state(old) == "dir"
            if present != info["existed"]:
                raise HelperError("stage_backup_failed", addon_id=addon_id)
            if present and fingerprint_tree(old)["digest"] != info["backup_tree_digest"]:
                raise HelperError("stage_backup_failed", addon_id=addon_id)
        except (FsProblem, OSError):
            raise HelperError("stage_backup_failed", addon_id=addon_id) from None


def _apply_stage(
    services: "Services",
    manifest: Mapping[str, Any],
    new_files: Mapping[str, Sequence[Tuple[str, bytes, int]]],
    run_dir: Path,
    addon_ids: Sequence[str],
) -> Dict[str, Any]:
    """Mutate the portable add-ons directory; roll back on any failure."""
    target = services.target
    area = target.stage_area
    target.require_chain(target.portable_data)
    target.require_chain(target.addons_dir)
    try:
        os.mkdir(os.fspath(area), 0o700)  # exclusive: doubles as the stage lock
    except FileExistsError:
        raise HelperError("stage_area_exists") from None
    except OSError:
        raise HelperError("stage_area_invalid") from None
    try:
        if not _same_device(area, target.addons_dir):
            raise HelperError("stage_area_invalid", reason="cross_device")
        for name in ("new", "old", "failed"):
            _make_dir(area / name, 0o700)
        try:
            for addon_id in addon_ids:
                write_tree(area / "new" / addon_id, new_files[addon_id])
        except OSError:
            raise HelperError("stage_write_failed") from None
        object_format = manifest["candidate"]["object_format"]
        for key in ("build_manager", "driver"):
            tree = manifest[key]
            if not verify_tree_dir(area / "new" / tree["addon_id"], tree, object_format)["ok"]:
                raise HelperError("stage_new_tree_mismatch", addon_id=tree["addon_id"])
        # A verified evidence copy of everything replaced exists before any rename.
        replaced = _backup_live_trees(target, run_dir, addon_ids)
        identify(services, require="not_running")  # nothing may have launched meanwhile
        try:
            done = _swap_in(target, area, addon_ids)
        except OSError:
            raise HelperError("stage_swap_failed") from None  # already rolled back
        verification = verify_installed(services, manifest, git_repo=None)
        if not verification["installed_equals_manifest"]:
            _rollback(target, area, done)
            raise HelperError("stage_post_verify_failed")
        _recheck_backups(replaced)
        _check_moved_old(target, replaced, addon_ids)
    except BaseException:
        # Keeps the area whenever old/ may still be the only copy of anything.
        _remove_stage_area(target, discard_old=False)
        raise
    return {
        "post_stage_verify": verification,
        "replaced": replaced,
        "stage_area_removed": _remove_stage_area(target, discard_old=True),
    }


# ---------------------------------------------------------------------------
# Adapter result: allowlisted projection and freshness
# ---------------------------------------------------------------------------

def _opt(validator: Callable[[Any], Any]) -> Callable[[Any], Any]:
    def check(value: Any) -> Any:
        return None if value is None else validator(value)
    return check


def _v_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError("bool")


def _v_enum(allowed: Iterable[str]) -> Callable[[Any], str]:
    options = frozenset(allowed)

    def check(value: Any) -> str:
        if isinstance(value, str) and value in options:
            return value
        raise ValueError("enum")
    return check


def _v_int(low: int, high: int) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
            return value
        raise ValueError("int")
    return check


def _v_match(pattern: "re.Pattern[str]") -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if isinstance(value, str) and pattern.fullmatch(value):
            return value
        raise ValueError("pattern")
    return check


def _v_list(item: Callable[[Any], Any], limit: int) -> Callable[[Any], List[Any]]:
    def check(value: Any) -> List[Any]:
        if not isinstance(value, list) or len(value) > limit:
            raise ValueError("list")
        return [item(element) for element in value]
    return check


def _lenient_enum(allowed: Iterable[str]) -> Callable[[Any], Optional[str]]:
    """Like the adapter itself: a code outside the public allowlist becomes null."""
    options = frozenset(allowed)

    def check(value: Any) -> Optional[str]:
        return value if isinstance(value, str) and value in options else None
    return check


def _v_record(spec: Mapping[str, Callable[[Any], Any]]) -> Callable[[Any], Dict[str, Any]]:
    """Closed record: unknown keys are dropped; one invalid value withholds it all."""
    def check(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("record")
        return {key: validator(value[key]) for key, validator in spec.items() if key in value}
    return check


def _v_installed(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or len(value) > 500:
        raise ValueError("installed")
    entry = _opt(_v_record({
        "broken": _opt(_v_bool), "enabled": _opt(_v_bool), "version": _opt(_v_match(_VERSION_RE)),
    }))
    result: Dict[str, Any] = {}
    for key in sorted(value):
        if not isinstance(key, str) or not _ADDON_ID_RE.fullmatch(key):
            raise ValueError("installed key")
        result[key] = entry(value[key])
    return result


_TOKEN_RE = re.compile(r"[a-z][a-z_]{0,31}")
_FINGERPRINT_RE = re.compile(r"(sha256:)?[0-9a-f]{64}")
_PHASES = _adapter.STATUS_FROZEN_PHASES
_LIFECYCLES = _adapter.STATUS_LIFECYCLE_STAGES
_FROZEN_CODES = _adapter.STATUS_FROZEN_CODES | frozenset({""})
_RESTART_CODES = _adapter.STATUS_RESTART_CODES
_POLICY_NAMES = _adapter.STATUS_UPDATE_POLICIES
_ADDON_ID_V = _v_match(_ADDON_ID_RE)

_INSTALL_TRANSACTION = _opt(_v_record({
    "activation_hold_ids": _v_list(_ADDON_ID_V, 64),
    "activation_hold_released": _opt(_v_bool),
    "lifecycle_restart_count": _opt(_v_int(0, 3)),
    "lifecycle_stage": _opt(_v_enum(_LIFECYCLES)),
    "original_update_policy": _opt(_v_int(0, 2)),
    "phase": _opt(_v_enum(_PHASES)),
    "private_overlay_required": _opt(_v_bool),
    "resolution_records": _v_list(_v_record({
        "addon_id": _ADDON_ID_V,
        "desired_enabled": _opt(_v_bool),
        "repository_id": _opt(_ADDON_ID_V),
        "resolution": _opt(_v_match(_TOKEN_RE)),
        "resolved_version": _opt(_v_match(_VERSION_RE)),
        "state": _opt(_v_match(_TOKEN_RE)),
    }), 500),
    "status_code": _lenient_enum(_FROZEN_CODES),
    "updater_guard_required": _opt(_v_bool),
}))
_RETRY_TRANSACTION = _opt(_v_record({
    "activation_hold_ids": _v_list(_ADDON_ID_V, 1),
    "activation_hold_released": _opt(_v_bool),
    "lifecycle_restart_count": _opt(_v_int(0, 3)),
    "lifecycle_stage": _opt(_v_enum(_LIFECYCLES | {"unknown"})),
    "phase": _opt(_v_enum(_PHASES | {"unknown"})),
    "updater_guard_required": _opt(_v_bool),
}))
_STATUS_RECORD = _v_record({
    "activation_hold_count": _opt(_v_int(0, 10000)),
    "activation_hold_released": _opt(_v_bool),
    "adapter_version": _opt(_v_match(_VERSION_RE)),
    "frozen_lifecycle_restart_count": _opt(_v_int(0, 10000)),
    "frozen_lifecycle_stage": _opt(_v_enum(_LIFECYCLES)),
    "frozen_lock_file_present": _opt(_v_bool),
    "frozen_phase": _opt(_v_enum(_PHASES)),
    "frozen_status_code": _lenient_enum(_FROZEN_CODES),
    "frozen_transaction_state": _opt(_v_enum(("absent", "present", "unreadable", "invalid"))),
    "original_update_policy": _opt(_v_enum(_POLICY_NAMES)),
    "private_overlay_required": _opt(_v_bool),
    "redlight_hold_present": _opt(_v_bool),
    "resolution_record_count": _opt(_v_int(0, 10000)),
    "restart_attempt_count": _opt(_v_int(0, 10000)),
    "restart_lock_file_present": _opt(_v_bool),
    "restart_phase": _opt(_v_enum(_adapter.STATUS_RESTART_PHASES)),
    "restart_status_code": _lenient_enum(_RESTART_CODES),
    "restart_transaction_linked": _opt(_v_bool),
    "restart_transaction_state": _opt(_v_enum(("absent", "present", "unreadable", "invalid"))),
    "updater_guard_required": _opt(_v_bool),
})
_OUTCOME = _v_enum(("complete", "failed", "needs_attention", "awaiting_restart", "unknown"))

_COMMON_FIELDS: Dict[str, Callable[[Any], Any]] = {
    "adapter_stage": _v_enum(_adapter.ADAPTER_STAGES),
    "error_type": _v_enum(_adapter.SAFE_ERROR_TYPES | {"not_started"}),
    "expected_sha256": _v_match(_HEX64),
    "failing_callable": _v_enum(_adapter.ADAPTER_CALLABLES),
    "failure_category": _v_enum(_adapter.FAILURE_CATEGORIES),
    "frozen_install_source": _v_record({
        "replaced": _opt(_v_bool),
        "sha256_after": _opt(_v_match(_HEX64)),
        "sha256_before": _opt(_v_match(_HEX64)),
    }),
    "observed_sha256": _v_match(_HEX64),
    "retained_inputs": _v_record({
        "artifact_entry_count": _opt(_v_int(0, 10 ** 7)),
        "artifact_store_present": _opt(_v_bool),
        "artifact_store_readable": _opt(_v_bool),
        "manifest_present": _opt(_v_bool),
        "manifest_readable": _opt(_v_bool),
    }),
}
_MODE_FIELDS: Dict[str, Dict[str, Callable[[Any], Any]]] = {
    "install": {
        "code": _lenient_enum(_FROZEN_CODES | _RESTART_CODES),
        "frozen_manifest_fingerprint": _v_match(_FINGERPRINT_RE),
        "installation_order": _v_list(_ADDON_ID_V, 500),
        "installed": _v_installed,
        "outcome": _v_match(_TOKEN_RE),
        "overlay_imported": _v_bool,
        "transaction": _INSTALL_TRANSACTION,
        "updater_policy": _opt(_v_int(0, 2)),
    },
    "recover": {
        "af3_installed": _v_bool,
        "frozen_addons_retained": _v_bool,
        "original_update_policy": _v_int(0, 2),
        "restart_transaction_present": _v_bool,
        "transaction_cleared": _v_bool,
        "update_policy_after": _v_int(0, 2),
        "updater_policy_restored": _v_bool,
    },
    "retry": {
        "outcome": _OUTCOME,
        "retry_invoked": _v_bool,
        "transaction": _RETRY_TRANSACTION,
    },
    "status": {"status": _STATUS_RECORD},
}


def project_adapter_result(mode: str, raw: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Reduce an adapter result file to its allowlisted, validated fields.

    Unknown keys and invalid values are withheld (counted, never echoed).
    """
    if not isinstance(raw, dict):
        raise HelperError("result_malformed", reason="root")
    ok = raw.get("ok")
    if not isinstance(ok, bool):
        raise HelperError("result_malformed", reason="ok")
    observed = raw.get("adapter_mode")
    if observed != mode:
        shown = observed if isinstance(observed, str) and observed in (*ADAPTER_MODES, "unselected") else "invalid"
        raise HelperError("adapter_mode_mismatch", expected_mode=mode, observed_mode=shown)
    spec = {**_COMMON_FIELDS, **_MODE_FIELDS[mode]}
    projected: Dict[str, Any] = {"adapter_mode": mode, "ok": ok}
    invalid: List[str] = []
    for key in sorted(spec):
        if key not in raw:
            continue
        try:
            projected[key] = spec[key](raw[key])
        except ValueError:
            invalid.append(key)
    unknown = sorted(key for key in raw if key not in spec and key not in ("ok", "adapter_mode"))
    withheld = {
        "invalid_known_keys": invalid,
        "unknown_key_count": len(unknown),
        "unknown_key_names": [key for key in unknown if re.fullmatch(r"[a-z][a-z0-9_]{0,39}", str(key))][:20],
    }
    return projected, withheld


_PAST_SLACK_NS = 1_000_000_000
_FUTURE_SLACK_NS = 5_000_000_000


@dataclass(frozen=True)
class ResultObservation:
    state: str  # "absent" | "unreadable" | "ok"
    read: Optional[FileRead] = None
    sha256: Optional[str] = None

    def identity(self) -> Optional[Tuple[int, int, int, int, str]]:
        if self.read is None or self.sha256 is None:
            return None
        return (self.read.st_dev, self.read.st_ino, self.read.st_size, self.read.st_mtime_ns, self.sha256)


def observe_result(target: TestAppTarget) -> ResultObservation:
    """Hardened, read-only look at the adapter result file."""
    try:
        target.require_chain(target.result_path.parent)
    except HelperError:
        raise HelperError("result_path_unsafe") from None
    try:
        read = read_regular_file(target.result_path, MAX_RESULT_BYTES)
    except FsProblem as exc:
        if exc.kind == "absent":
            return ResultObservation("absent")
        if exc.kind == "not_regular":
            raise HelperError("result_path_unsafe") from None
        if exc.kind == "too_large":
            raise HelperError("result_malformed", reason="size") from None
        return ResultObservation("unreadable")
    return ResultObservation("ok", read, sha256_hex(read.data))


def judge_freshness(
    observation: ResultObservation,
    before: Optional[Tuple[int, int, int, int, str]],
    invoked_ns: int,
    now_ns: int,
) -> str:
    """"fresh" only for a file written by this invocation; fail closed otherwise."""
    if observation.state == "absent":
        return "absent"
    if observation.state != "ok" or observation.read is None:
        return "unreadable"
    if observation.read.st_mtime_ns > now_ns + _FUTURE_SLACK_NS:
        return "future"
    if before is not None and _same_file_and_content(observation, before):
        return "stale"  # same inode and same bytes: at most touched, never rewritten
    if observation.read.st_mtime_ns < invoked_ns - _PAST_SLACK_NS:
        return "stale"
    return "fresh"


def _same_file_and_content(
    observation: ResultObservation, before: Tuple[int, int, int, int, str]
) -> bool:
    current = observation.identity()
    return current is not None and (current[0], current[1], current[4]) == (before[0], before[1], before[4])


# ---------------------------------------------------------------------------
# Loopback JSON-RPC (credentials: terminal prompt only, memory only)
# ---------------------------------------------------------------------------

class HttpTransport:
    """Direct http.client connection: no proxies, no redirects, loopback IP only."""

    def post(
        self, host: str, port: int, path: str, body: bytes, headers: Mapping[str, str], timeout: float
    ) -> Tuple[int, bytes]:
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            connection.request("POST", path, body=body, headers=dict(headers))
            response = connection.getresponse()
            payload = response.read(MAX_RPC_BYTES + 1)
            if len(payload) > MAX_RPC_BYTES:
                raise HelperError("rpc_response_too_large")
            return response.status, payload
        finally:
            connection.close()


def interactive_password_prompt(prompt: str) -> str:
    """Prompt on the controlling terminal; never falls back to stdin."""
    try:
        descriptor = os.open("/dev/tty", os.O_RDWR | getattr(os, "O_NOCTTY", 0))
    except OSError:
        raise HelperError("credential_prompt_unavailable") from None
    os.close(descriptor)
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, OSError):
            raise HelperError("credential_prompt_unavailable") from None
        except EOFError:
            raise HelperError("credential_missing") from None


class RpcClient:
    """JSON-RPC over HTTP to the one verified Test.app listener on loopback."""

    def __init__(self, services: "Services", pid: int, host: str, port: int, username: str) -> None:
        self._services = services
        self._pid = pid
        self._host = host
        self._port = port
        self._username = username
        self._auth: Optional[str] = None
        self.requests_sent = 0

    @property
    def authenticated(self) -> bool:
        return self._auth is not None

    def _guard_listener(self) -> None:
        """The listener on the port must be exactly the authorized Test.app pid."""
        pids = self._services.listener_lookup(self._port)
        if not pids:
            raise HelperError("listener_not_found", port=self._port)
        if pids != {self._pid}:
            raise HelperError("listener_pid_mismatch", port=self._port, listener_count=len(pids))

    def _authenticate(self) -> None:
        prompt = f"Kodi web interface password for '{self._username}' (input hidden): "
        password = self._services.password_prompt(prompt)
        if not isinstance(password, str) or not password:
            raise HelperError("credential_missing")
        token = base64.b64encode(f"{self._username}:{password}".encode("utf-8")).decode("ascii")
        self._auth = "Basic " + token
        self._services.secrets.register(password, minimum=8)
        self._services.secrets.register(token)
        self._services.secrets.register(self._auth)
        del password

    def call(self, method: str, params: Mapping[str, Any]) -> Any:
        body = json.dumps(
            {"id": 1, "jsonrpc": "2.0", "method": method, "params": dict(params)}, sort_keys=True
        ).encode("utf-8")
        for attempt in (1, 2):
            self._guard_listener()
            headers = {"Accept": "application/json", "Connection": "close", "Content-Type": "application/json"}
            if self._auth is not None:
                headers["Authorization"] = self._auth
            try:
                status, payload = self._services.transport.post(
                    self._host, self._port, "/jsonrpc", body, headers, 15.0
                )
            except HelperError:
                raise
            except Exception:
                raise HelperError("rpc_transport_failed") from None
            self.requests_sent += 1
            if status == 401:
                if self._auth is not None or attempt == 2:
                    raise HelperError("rpc_auth_failed")
                self._authenticate()
                continue
            if status != 200:
                raise HelperError("rpc_http_error", status=status)
            return self._parse(payload)
        raise HelperError("rpc_auth_failed")

    @staticmethod
    def _parse(payload: bytes) -> Any:
        if len(payload) > MAX_RPC_BYTES:
            raise HelperError("rpc_response_too_large")
        try:
            document = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HelperError("rpc_response_invalid") from None
        if not isinstance(document, dict) or document.get("jsonrpc") != "2.0" or document.get("id") != 1:
            raise HelperError("rpc_response_invalid")
        if "error" in document:
            error = document["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise HelperError("rpc_error", rpc_code=code if isinstance(code, int) else None)
        if "result" not in document:
            raise HelperError("rpc_response_invalid")
        return document["result"]


DEFAULT_TIMEOUTS = {"install": 1800, "retry": 900, "recover": 300, "status": 120}
POLL_INTERVAL_SECONDS = 1.0
LIVENESS_EVERY_POLLS = 5


def _kodi_addon_view(client: RpcClient, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Kodi's own view of the two add-ons must match the staged versions."""
    view: Dict[str, Any] = {}
    expectations = (
        (DRIVER_ID, manifest["driver"]["addon_version"]),
        (BUILD_MANAGER_ID, manifest["build_manager"]["addon_version"]),
    )
    for addon_id, expected_version in expectations:
        try:
            result = client.call(
                "Addons.GetAddonDetails", {"addonid": addon_id, "properties": ["enabled", "version"]}
            )
        except HelperError as exc:
            if exc.code == "rpc_error":
                raise HelperError("addon_not_visible_to_kodi", addon_id=addon_id) from None
            raise
        addon = result.get("addon") if isinstance(result, dict) else None
        if not isinstance(addon, dict):
            raise HelperError("addon_not_visible_to_kodi", addon_id=addon_id)
        enabled, version = addon.get("enabled"), addon.get("version")
        if not isinstance(enabled, bool) or not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise HelperError("addon_view_mismatch", addon_id=addon_id)
        view[addon_id] = {"enabled": enabled, "version": version}
        if not enabled or version != expected_version:
            raise HelperError("addon_view_mismatch", addon_id=addon_id)
    return view


def run_adapter(
    services: "Services",
    *,
    mode: str,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    rpc: Mapping[str, Any],
    git_repo: Optional[Path],
    timeout: float,
) -> Dict[str, Any]:
    """Invoke one BM-023A adapter mode and report its fresh, allowlisted result."""
    target = services.target
    identity = identify(services, require="running")
    verification = verify_installed(services, manifest, git_repo=git_repo)
    if not verification["installed_equals_manifest"] or (
        git_repo is not None and not verification["installed_equals_candidate"]
    ):
        raise HelperError("installed_tree_mismatch")
    host = validate_loopback_host(rpc.get("host", DEFAULT_RPC_HOST))
    if "port" not in rpc:
        raise HelperError("rpc_port_invalid")
    port = validate_port(rpc["port"])
    username = rpc.get("username", DEFAULT_RPC_USERNAME)
    if identity.pid is None:
        raise HelperError("test_app_not_running")
    observe_result(target)  # an unsafe result path fails closed before any RPC
    client = RpcClient(services, identity.pid, host, port, username)
    if client.call("JSONRPC.Ping", {}) != "pong":
        raise HelperError("rpc_response_invalid")
    addon_view = _kodi_addon_view(client, manifest)
    before = observe_result(target)
    invoked_ns = services.clock.time_ns()
    invoked_utc = iso_utc_from_ns(invoked_ns)
    accepted = client.call("Addons.ExecuteAddon", {"addonid": DRIVER_ID, "params": mode, "wait": False})
    if accepted != "OK":
        raise HelperError("rpc_execute_rejected")
    deadline = services.clock.monotonic() + timeout
    polls = 0
    last_verdict = "absent"
    while True:
        observation = observe_result(target)
        last_verdict = judge_freshness(
            observation, before.identity(), invoked_ns, services.clock.time_ns()
        )
        if last_verdict == "future":
            raise HelperError("result_from_future")
        if last_verdict == "fresh":
            break
        if services.clock.monotonic() >= deadline:
            raise HelperError(
                "result_stale" if last_verdict == "stale" else "result_not_produced",
                last_observation=last_verdict,
            )
        polls += 1
        if polls % LIVENESS_EVERY_POLLS == 0 and not services.pid_alive(identity.pid):
            raise HelperError("kodi_exited_before_result", last_observation=last_verdict)
        services.clock.sleep(POLL_INTERVAL_SECONDS)
    if observation.read is None:  # unreachable: "fresh" implies a readable file
        raise HelperError("result_not_produced")
    try:
        raw = json.loads(observation.read.data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HelperError("result_malformed", reason="json") from None
    projected, withheld = project_adapter_result(mode, raw)
    try:
        after = identify(services).report()["process"]
    except HelperError as exc:
        after = {"error": exc.code}
    # The run (or Kodi's updater) must not have altered the staged candidate.
    final = verify_installed(services, manifest, git_repo=git_repo)
    post_run = {
        "installed_equals_manifest": final["installed_equals_manifest"],
        "problems": {
            addon_id: report.get("problems", []) for addon_id, report in sorted(final["trees"].items())
        },
    }
    return {
        "adapter_ok": projected["ok"],
        "command": "run",
        "freshness": {
            "changed_since_before": before.identity() != observation.identity(),
            "preexisting_result": before.state == "ok",
            "result_mtime_utc": iso_utc_from_ns(observation.read.st_mtime_ns),
            "result_sha256": observation.sha256,
            "result_size": observation.read.st_size,
            "verdict": last_verdict,
        },
        "identity": identity.report(),
        "invocation": {
            "authenticated": client.authenticated,
            "invoked_utc": invoked_utc,
            "listener_pid_verified": True,
            "mode": mode,
            "rpc_host": host,
            "rpc_port": port,
            "rpc_requests": client.requests_sent,
            "test_app_pid": identity.pid,
        },
        "kodi_addon_view": addon_view,
        "manifest_sha256": manifest_sha256,
        "ok": True,
        "post_run_verification": post_run,
        "process_after": after,
        "result": projected,
        "result_withheld": withheld,
        "stage_verification": verification,
    }


# ---------------------------------------------------------------------------
# snapshot: read-only, secret-blind census of the portable data
# ---------------------------------------------------------------------------

# Explicit denylist of private raw data. Matching is lexical and case-insensitive
# because APFS is; nothing under these locations is ever opened or stat'ed.
DENIED_ADDON_DATA_IDS = frozenset({"plugin.video.redlight"})
DENIED_BM_SUBDIRS = frozenset({"private_overlays"})
BM_DATA_READ_FILES = frozenset({
    "frozen_install_transaction.json",
    "frozen_install_transaction.lock",
    "restart_transaction.json",
    "restart_transaction.lock",
    RESULT_FILENAME,
})
_ADDONS_DB_RE = re.compile(r"Addons[0-9]{1,4}\.db")
_SKIN_RE = re.compile(r"[A-Za-z0-9_.\-]{1,100}")
_POLICY_BY_VALUE = {"0": "AUTOMATIC", "1": "NOTIFY_ONLY", "2": "NEVER_CHECK"}


class ReadGuard:
    """Every snapshot read passes through here: denylist first, then allowlist."""

    def __init__(self, target: TestAppTarget) -> None:
        self._target = target
        self.refused = 0

    def _denied(self, path: Path) -> bool:
        folded = _folded_abspath(path)
        base = _folded_abspath(self._target.addon_data_dir) + os.sep
        if not folded.startswith(base):
            return False
        parts = folded[len(base):].split(os.sep)
        if parts[0] in {item.casefold() for item in DENIED_ADDON_DATA_IDS}:
            return True
        return (
            parts[0] == BUILD_MANAGER_ID.casefold()
            and len(parts) > 1
            and parts[1] in {item.casefold() for item in DENIED_BM_SUBDIRS}
        )

    def _allowed(self, path: Path) -> bool:
        target = self._target
        normalized = Path(os.path.normpath(os.path.abspath(os.fspath(path))))
        parent, name = normalized.parent, normalized.name
        if parent.parent == target.addons_dir and name == "addon.xml":
            return _ADDON_ID_RE.fullmatch(parent.name) is not None
        if normalized == target.userdata_dir / "guisettings.xml":
            return True
        if parent == target.userdata_dir / "Database":
            return _ADDONS_DB_RE.fullmatch(name) is not None
        return parent == target.bm_data_dir and name in BM_DATA_READ_FILES

    def require(self, path: Path) -> Path:
        if self._denied(path):
            self.refused += 1
            raise HelperError("private_path_denied")
        if not self._allowed(path):
            self.refused += 1
            raise HelperError("read_not_allowlisted")
        try:
            self._target.require_chain(Path(os.path.abspath(os.fspath(path))).parent)
        except HelperError:
            self.refused += 1
            raise
        return path


def extract_settings(data: bytes, wanted: Iterable[str]) -> Dict[str, Optional[str]]:
    """Return only the wanted ``<setting id=...>`` values from guisettings.xml.

    The document is parsed in a streaming fashion and every other setting
    (which may include credentials) is discarded unread; DTDs are refused.
    """
    if len(data) > MAX_XML_BYTES or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("unsafe xml")
    wanted_ids = set(wanted)
    counts: Dict[str, int] = {}
    values: Dict[str, Optional[str]] = {}
    for _event, element in ET.iterparse(io.BytesIO(data), events=("end",)):
        if element.tag == "setting":
            setting_id = element.get("id")
            if setting_id in wanted_ids:
                counts[setting_id] = counts.get(setting_id, 0) + 1
                values[setting_id] = (element.text or "").strip()
        element.clear()
    return {key: (values.get(key) if counts.get(key) == 1 else None) for key in wanted_ids}


def read_guisettings(target: TestAppTarget, guard: ReadGuard) -> Dict[str, Any]:
    path = guard.require(target.userdata_dir / "guisettings.xml")
    report: Dict[str, Any] = {
        "active_skin": None, "present": False, "readable": False,
        "source": "guisettings.xml", "updater_policy": None,
    }
    try:
        raw = read_regular_file(path, MAX_XML_BYTES)
    except FsProblem as exc:
        report["present"] = exc.kind != "absent"
        return report
    report["present"] = True
    try:
        values = extract_settings(raw.data, ("general.addonupdates", "lookandfeel.skin"))
    except (ET.ParseError, ValueError):
        return report
    report["readable"] = True
    report["updater_policy"] = _POLICY_BY_VALUE.get(values.get("general.addonupdates") or "")
    skin = values.get("lookandfeel.skin")
    report["active_skin"] = skin if skin is not None and _SKIN_RE.fullmatch(skin) else None
    return report


def read_enabled_map(target: TestAppTarget, guard: ReadGuard) -> Optional[Dict[str, bool]]:
    """Enabled flags from Kodi's add-on database, opened read-only/immutable."""
    database_dir = target.userdata_dir / "Database"
    try:
        lstat_real_dir(database_dir)
        names = [entry.name for entry in os.scandir(database_dir) if _ADDONS_DB_RE.fullmatch(entry.name)]
    except (FsProblem, OSError):
        return None
    if not names:
        return None
    newest = max(names, key=lambda name: int(name[6:-3]))
    path = guard.require(database_dir / newest)
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        uri = "file:" + urllib.parse.quote(os.fspath(path)) + "?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            connection.execute("PRAGMA query_only = 1")
            rows = connection.execute("SELECT addonID, enabled FROM installed LIMIT 10000").fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return None
    return {str(addon_id): bool(enabled) for addon_id, enabled in rows if isinstance(addon_id, str)}


def census_addons(target: TestAppTarget, guard: ReadGuard) -> Dict[str, Any]:
    """Installed add-on ids and versions (public metadata from addon.xml only)."""
    entries: List[Dict[str, Any]] = []
    skipped_names = skipped_nondir = unreadable = id_mismatch = 0
    try:
        listing = sorted(os.scandir(target.addons_dir), key=lambda entry: entry.name)
    except OSError:
        raise HelperError("layout_missing") from None
    enabled_map = read_enabled_map(target, guard)
    for entry in listing:
        if entry.name in ("packages", "temp") or entry.name.startswith("."):
            continue
        if not _ADDON_ID_RE.fullmatch(entry.name):
            skipped_names += 1
            continue
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            unreadable += 1
            continue
        if not stat.S_ISDIR(info.st_mode):
            skipped_nondir += 1
            continue
        try:
            raw = read_regular_file(guard.require(target.addons_dir / entry.name / "addon.xml"), MAX_XML_BYTES)
            addon_id, version = parse_addon_xml(raw.data)
        except (FsProblem, ET.ParseError, ValueError):
            unreadable += 1
            continue
        if addon_id != entry.name:
            id_mismatch += 1
            continue
        entries.append({
            "enabled": None if enabled_map is None else enabled_map.get(addon_id),
            "id": addon_id,
            "version": version,
        })
    return {
        "count": len(entries),
        "enabled_state_source": "addons_db" if enabled_map is not None else "unavailable",
        "entries": entries,
        "id_mismatch": id_mismatch,
        "skipped_invalid_names": skipped_names,
        "skipped_non_directories": skipped_nondir,
        "unreadable_addon_xml": unreadable,
    }


def _load_frozen_record(value: Any) -> SimpleNamespace:
    if not isinstance(value, dict):
        raise ValueError("record")
    policy = value.get("original_update_policy")
    holds = value.get("activation_hold_ids")
    records = value.get("resolution_records")
    return SimpleNamespace(
        phase=value.get("phase"),
        lifecycle_stage=value.get("lifecycle_stage"),
        lifecycle_restart_count=value.get("lifecycle_restart_count"),
        status_code=value.get("status_code"),
        activation_hold_ids=tuple(holds) if isinstance(holds, list) else (),
        activation_hold_released=value.get("activation_hold_released"),
        updater_guard_required=value.get("updater_guard_required"),
        private_overlay_required=value.get("private_overlay_required"),
        original_update_policy=SimpleNamespace(
            name=_POLICY_BY_VALUE.get(str(policy)) if isinstance(policy, int) and not isinstance(policy, bool) else None
        ),
        resolution_records=tuple(records) if isinstance(records, list) else None,
        restart_transaction_id=value.get("restart_transaction_id"),
    )


def _load_restart_record(value: Any) -> SimpleNamespace:
    if not isinstance(value, dict):
        raise ValueError("record")
    return SimpleNamespace(
        phase=value.get("phase"),
        restart_attempt_count=value.get("restart_attempt_count"),
        status_code=value.get("status_code"),
        transaction_id=value.get("transaction_id"),
    )


def _file_size(path: Path) -> Optional[int]:
    try:
        info = os.lstat(os.fspath(path))
    except OSError:
        return None
    return info.st_size if stat.S_ISREG(info.st_mode) else None


def census_transactions(target: TestAppTarget, guard: ReadGuard) -> Dict[str, Any]:
    """Frozen/restart transaction state via the product's bounded status reader."""
    directory = target.bm_data_dir
    paths = {name: guard.require(directory / name) for name in sorted(BM_DATA_READ_FILES - {RESULT_FILENAME})}
    status = _adapter.read_adapter_status(
        paths["frozen_install_transaction.json"],
        paths["frozen_install_transaction.lock"],
        paths["restart_transaction.json"],
        paths["restart_transaction.lock"],
        _load_frozen_record,
        _load_restart_record,
    )
    status.pop("adapter_version", None)  # describes this helper's checkout, not the install
    status["sizes"] = {
        "frozen_lock_file": _file_size(paths["frozen_install_transaction.lock"]),
        "frozen_transaction_file": _file_size(paths["frozen_install_transaction.json"]),
        "restart_lock_file": _file_size(paths["restart_transaction.lock"]),
        "restart_transaction_file": _file_size(paths["restart_transaction.json"]),
    }
    return status


def census_result_file(target: TestAppTarget, guard: ReadGuard) -> Dict[str, Any]:
    guard.require(target.result_path)
    observation = observe_result(target)
    if observation.state != "ok" or observation.read is None:
        return {"present": observation.state == "unreadable"}
    report: Dict[str, Any] = {
        "mtime_utc": iso_utc_from_ns(observation.read.st_mtime_ns),
        "present": True,
        "sha256": observation.sha256,
        "size": observation.read.st_size,
    }
    try:
        raw = json.loads(observation.read.data.decode("utf-8"))
        mode = raw.get("adapter_mode") if isinstance(raw, dict) else None
        if mode not in ADAPTER_MODES:
            raise HelperError("result_malformed", reason="mode")
        projected, withheld = project_adapter_result(mode, raw)
        report["projection"] = projected
        report["withheld"] = withheld
    except (ValueError, UnicodeDecodeError):
        report["projection_error"] = "result_malformed"
    except HelperError as exc:
        report["projection_error"] = exc.code
    return report


def run_snapshot(
    services: "Services",
    *,
    manifest: Optional[Mapping[str, Any]],
    manifest_sha256: Optional[str],
    git_repo: Optional[Path],
) -> Dict[str, Any]:
    """One sanitized census; touches only allowlisted portable-data locations."""
    target = services.target
    identity = identify(services)
    if not (identity.bundle.portable_data_present and identity.bundle.addons_dir_present
            and identity.bundle.userdata_dir_present):
        raise HelperError("layout_missing")
    guard = ReadGuard(target)
    addons = census_addons(target, guard)
    versions = {entry["id"]: entry["version"] for entry in addons["entries"]}
    payload: Dict[str, Any] = {
        "adapter_result_file": census_result_file(target, guard),
        "build_manager": {
            "installed": BUILD_MANAGER_ID in versions, "version": versions.get(BUILD_MANAGER_ID),
        },
        "command": "snapshot",
        "driver": {"installed": DRIVER_ID in versions, "version": versions.get(DRIVER_ID)},
        "identity": identity.report(),
        "installed_addons": addons,
        "ok": True,
        "private_data": {
            "denied_addon_data_ids": sorted(DENIED_ADDON_DATA_IDS),
            "denylist_enforced": True,
        },
        "settings": read_guisettings(target, guard),
        "stage_manifest": None,
        "transactions": census_transactions(target, guard),
    }
    if manifest is not None:
        payload["stage_manifest"] = {
            "build_manager_version": manifest["build_manager"]["addon_version"],
            "candidate_commit": manifest["candidate"]["commit"],
            "configuration_fingerprint": manifest["configuration_fingerprint"],
            "created_utc": manifest["created_utc"],
            "driver_adapter_version": manifest["driver"]["adapter_version"],
            "driver_tree_sha256": manifest["driver"]["tree_sha256"],
            "manifest_sha256": manifest_sha256,
        }
        payload["stage_verification"] = verify_installed(services, manifest, git_repo=git_repo)
    return payload


# ---------------------------------------------------------------------------
# Services (injectable for tests) and the command line
# ---------------------------------------------------------------------------

def default_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass
class Services:
    """Everything with side effects, so the unit tests can substitute fakes."""

    target: TestAppTarget
    process_lister: Any
    listener_lookup: Callable[[int], Set[int]]
    pid_alive: Callable[[int], bool]
    clock: Any
    password_prompt: Callable[[str], str]
    transport: Any
    git_exe: Optional[str]
    git_runner: Callable[..., Any]
    build_runner: Callable[..., Any]
    python_exe: str
    tmp_root: Optional[Path]
    repo_default: Path
    stdout: Any
    secrets: SecretRegistry

    @classmethod
    def production(cls) -> "Services":
        """The only production wiring: the hard-coded authorized target."""
        return cls(
            target=TestAppTarget.authorized(),
            process_lister=PsProcessLister(),
            listener_lookup=lsof_listener_pids,
            pid_alive=default_pid_alive,
            clock=SystemClock(),
            password_prompt=interactive_password_prompt,
            transport=HttpTransport(),
            git_exe=find_git(),
            git_runner=subprocess.run,
            build_runner=subprocess.run,
            python_exe=sys.executable,
            tmp_root=Path("/private/tmp"),
            repo_default=PROJECT,
            stdout=sys.stdout,
            secrets=SecretRegistry(),
        )


class _Parser(argparse.ArgumentParser):
    """Never echoes user input; usage errors become a fixed error code."""

    def error(self, message: str) -> NoReturn:
        raise HelperError("argument_invalid")


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", help="also write the JSON here (never overwrites)")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog=HELPER_NAME, description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    identify_parser = commands.add_parser("identify", help="read-only Test.app identity")
    _add_output(identify_parser)

    stage_parser = commands.add_parser("stage", help="install an exact Git-pinned candidate")
    stage_parser.add_argument("--candidate", required=True, help="full commit id (40 or 64 hex)")
    stage_parser.add_argument("--config", required=True, help="machine-local JSON config")
    stage_parser.add_argument("--evidence-dir", help="existing directory for the manifest and backups")
    stage_parser.add_argument("--repo", help="repository holding the candidate (default: this checkout)")
    stage_parser.add_argument("--dry-run", action="store_true", help="build and report; change nothing")
    _add_output(stage_parser)

    verify_parser = commands.add_parser("verify", help="prove installed trees equal the manifest")
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.add_argument("--repo")
    verify_parser.add_argument("--no-git-binding", action="store_true", help="weaker: skip the Git check")
    _add_output(verify_parser)

    run_parser = commands.add_parser("run", help="trigger the BM-023A adapter over loopback RPC")
    run_parser.add_argument("mode", choices=ADAPTER_MODES)
    run_parser.add_argument("--manifest", required=True)
    run_parser.add_argument("--config", help="machine-local JSON config (rpc section)")
    run_parser.add_argument("--rpc-host", help="loopback IP literal (default 127.0.0.1)")
    run_parser.add_argument("--rpc-port", type=int)
    run_parser.add_argument("--rpc-user", help="web interface user name (never the password)")
    run_parser.add_argument("--timeout", type=float, help="seconds to wait for the fresh result")
    run_parser.add_argument("--repo")
    run_parser.add_argument("--no-git-binding", action="store_true", help="weaker: skip the Git check")
    _add_output(run_parser)

    snapshot_parser = commands.add_parser("snapshot", help="read-only secret-blind census")
    snapshot_parser.add_argument("--manifest")
    snapshot_parser.add_argument("--repo")
    snapshot_parser.add_argument("--no-git-binding", action="store_true", help="weaker: skip the Git check")
    _add_output(snapshot_parser)
    return parser


_USAGE_CODES = frozenset({
    "argument_invalid", "argument_path_invalid", "argument_path_forbidden",
    "argument_path_inside_test_app", "argument_path_symlink", "argument_path_not_found",
    "config_unreadable", "config_unsafe_permissions", "config_invalid",
    "config_credential_field", "config_missing_section", "output_exists",
    "evidence_dir_invalid", "rpc_config_invalid", "rpc_host_not_loopback", "rpc_port_invalid",
})


def _error_payload(command: Optional[str], error: HelperError) -> Dict[str, Any]:
    return {
        "command": command,
        "error": {"code": error.code, "detail": error.detail},
        "ok": False,
    }


def _finalize(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload["schema"] = OUTPUT_SCHEMA
    payload["tool"] = tool_identity()
    return payload


def _validated_output(args: argparse.Namespace, services: Services) -> Optional[Path]:
    raw = getattr(args, "output", None)
    if raw is None:
        return None
    path = check_cli_path(raw, services)
    try:
        lstat_real_dir(path.parent)
    except FsProblem:
        raise HelperError("argument_path_not_found") from None
    try:
        os.lstat(os.fspath(path))
    except FileNotFoundError:
        return path
    except OSError:
        raise HelperError("output_exists") from None
    raise HelperError("output_exists")


def _git_repo(args: argparse.Namespace, services: Services) -> Optional[Path]:
    if getattr(args, "no_git_binding", False):
        return None
    return check_cli_path(args.repo or services.repo_default, services)


def _merge_rpc(config_rpc: Mapping[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    rpc = dict(config_rpc)
    if args.rpc_host is not None:
        rpc["host"] = validate_loopback_host(args.rpc_host)
    if args.rpc_port is not None:
        rpc["port"] = validate_port(args.rpc_port)
    if args.rpc_user is not None:
        if not _USERNAME_RE.fullmatch(args.rpc_user):
            raise HelperError("rpc_config_invalid")
        rpc["username"] = args.rpc_user
    return rpc


def _dispatch(args: argparse.Namespace, services: Services) -> Tuple[Dict[str, Any], int]:
    command = args.command
    if command == "identify":
        identity = identify(services)
        return {"command": "identify", "ok": True, **identity.report()}, EXIT_OK
    if command == "stage":
        config = load_config(Path(args.config), services)
        repo = check_cli_path(args.repo or services.repo_default, services)
        evidence = check_cli_path(args.evidence_dir, services) if args.evidence_dir else None
        payload = run_stage(
            services,
            candidate_id=args.candidate,
            config=config,
            repo=repo,
            evidence_dir=evidence,
            dry_run=args.dry_run,
        )
        return payload, EXIT_OK
    if command == "verify":
        manifest, manifest_sha = load_manifest(args.manifest, services)
        git_repo = _git_repo(args, services)
        identity = identify(services)
        verification = verify_installed(services, manifest, git_repo=git_repo)
        ok = verification["installed_equals_manifest"] and (
            git_repo is None or verification["installed_equals_candidate"]
        )
        payload = {
            "candidate_commit": manifest["candidate"]["commit"],
            "command": "verify",
            "identity": identity.report(),
            "manifest_sha256": manifest_sha,
            "ok": ok,
            **verification,
        }
        return payload, EXIT_OK if ok else EXIT_FAILED
    if command == "run":
        manifest, manifest_sha = load_manifest(args.manifest, services)
        config_rpc: Dict[str, Any] = {}
        if args.config:
            config_rpc = load_config(Path(args.config), services)["rpc"]
        rpc = _merge_rpc(config_rpc, args)
        timeout = args.timeout if args.timeout is not None else DEFAULT_TIMEOUTS[args.mode]
        if not 1 <= timeout <= 7200:
            raise HelperError("argument_invalid")
        payload = run_adapter(
            services,
            mode=args.mode,
            manifest=manifest,
            manifest_sha256=manifest_sha,
            rpc=rpc,
            git_repo=_git_repo(args, services),
            timeout=timeout,
        )
        return payload, EXIT_OK if payload["adapter_ok"] else EXIT_ADAPTER_FAILED
    if command == "snapshot":
        manifest = manifest_sha = None
        if args.manifest:
            manifest, manifest_sha = load_manifest(args.manifest, services)
        payload = run_snapshot(
            services,
            manifest=manifest,
            manifest_sha256=manifest_sha,
            git_repo=_git_repo(args, services) if manifest is not None else None,
        )
        return payload, EXIT_OK
    raise HelperError("argument_invalid")


def main(argv: Optional[Sequence[str]] = None, *, services: Optional[Services] = None) -> int:
    """Run one command; always prints one JSON document and returns an exit code."""
    active = services
    output_path: Optional[Path] = None
    command: Optional[str] = None
    try:
        args = build_parser().parse_args(argv)
        command = args.command
        if active is None:
            active = Services.production()
        output_path = _validated_output(args, active)
        payload, code = _dispatch(args, active)
    except HelperError as exc:
        payload = _error_payload(command, exc)
        code = EXIT_USAGE if exc.code in _USAGE_CODES else EXIT_FAILED
    except KeyboardInterrupt:
        payload, code = _error_payload(command, HelperError("interrupted")), EXIT_INTERRUPTED
    except Exception as exc:  # never leak exception text
        payload = _error_payload(command, HelperError("unexpected_error", exception_type=type(exc).__name__))
        code = EXIT_FAILED
    payload = _finalize(payload)
    text = canonical_json(payload)
    if active is not None and active.secrets.leaks(text):
        payload = _finalize(_error_payload(command, HelperError("output_blocked_secret_detected")))
        text, code, output_path = canonical_json(payload), EXIT_FAILED, None
    if output_path is not None:
        try:
            write_new_file_atomic(output_path, text.encode("ascii"), 0o600)
        except HelperError as exc:
            payload["output_write_error"] = exc.code
            text, code = canonical_json(payload), EXIT_FAILED
    stream = active.stdout if active is not None else sys.stdout
    stream.write(text)
    stream.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
