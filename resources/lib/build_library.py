"""Canonical profile-owned public builds and a separate selected-build record.

The envelope contains existing manifest/package formats, not a new build format.
Only registry-published content hashes are selectable. Reads are creation-free;
all directory traversal is anchored with no-follow directory descriptors.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from resources.lib.config import ConfigPackageLoader, _parse_descriptor, validate_package_id
from resources.lib.frozen import FrozenBuildManifest
from resources.lib.build_identity import check_frozen_identity
from resources.lib.manifest import validate_manifest
from resources.lib.readonly_io import read_regular_file
from resources.lib.resolver import resolve_manifest

FILE_LIMIT = 4 * 1024 * 1024
BUNDLE_LIMIT = 32 * 1024 * 1024
STATE_LIMIT = 1024 * 1024
PACKAGE_LIMIT = 256
_KEY = re.compile(r"^[0-9a-f]{64}$")
_ADDON = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_PRIVATE_KEY = re.compile(r"password|passwd|token|secret|credential|oauth|api[._-]?key|username", re.I)


class LibraryError(Exception):
    """Stable, presentation-safe failure; never includes rejected input values."""


class LibraryConflict(LibraryError):
    pass


def _error():
    return LibraryError("build_library_invalid")


def _safe_publication_write(method):
    def write(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except LibraryError:
            raise
        except Exception:
            raise _error() from None
    return write


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _error()
            result[key] = value
        return result
    def constant(_):
        raise _error()
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def _parts(path):
    if not isinstance(path, str) or not path or "\\" in path:
        raise _error()
    parts = path.split("/")
    if any(p in ("", ".", "..") or "\x00" in p for p in parts):
        raise _error()
    return parts


@contextmanager
def _directory(path, *, create=False):
    """Open every ancestor without following links; retain descriptors for I/O.

    Never realpath a rejected source or library root. Directory swaps cannot
    redirect traversal into a symlink target, including during publication.
    """
    path = os.fspath(path)
    if not os.path.isabs(path):
        raise _error()
    parts = _parts(path[1:]) if path != "/" else []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            new = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


def _read_at(fd, relative, limit):
    parts = _parts(relative)
    current = os.dup(fd)
    try:
        for part in parts[:-1]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = new
        return read_regular_file(parts[-1], limit=limit, dir_fd=current)
    finally:
        os.close(current)


def _read_path(path, limit):
    path = os.fspath(path)
    # Do not normalize traversal away before validating it.
    if not os.path.isabs(path):
        raise _error()
    _parts(path[1:])
    with _directory(os.path.dirname(path)) as fd:
        data = _read_at(fd, os.path.basename(path), limit)
    if data is None:
        raise _error()
    return data


def _atomic(fd, name, data):
    if len(data) > BUNDLE_LIMIT:
        raise _error()
    temporary = ".stage-" + uuid.uuid4().hex
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class LibraryEntry:
    entry_id: str
    build_id: str
    build_version: str
    display_name: str
    device_profiles: tuple[str, ...]
    usable: bool = True


@dataclass(frozen=True)
class SelectedBuild:
    entry_id: str
    device_profile_id: str


@dataclass(frozen=True)
class AppliedBuildAssociation:
    """Verified terminal identity, distinct from a user selection."""
    entry_id: str
    device_profile_id: str
    resolution_fingerprint: str

    def to_dict(self):
        return {"schema_version": 2, "entry_id": self.entry_id,
                "device_profile_id": self.device_profile_id,
                "resolution_fingerprint": self.resolution_fingerprint}

    @classmethod
    def from_dict(cls, raw):
        if (not isinstance(raw, dict)
                or set(raw) != {"schema_version", "entry_id", "device_profile_id", "resolution_fingerprint"}
                or type(raw["schema_version"]) is not int or raw["schema_version"] != 2
                or not isinstance(raw["entry_id"], str) or not _KEY.fullmatch(raw["entry_id"])
                or not isinstance(raw["resolution_fingerprint"], str)
                or not _KEY.fullmatch(raw["resolution_fingerprint"])
                or not isinstance(raw["device_profile_id"], str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", raw["device_profile_id"])):
            raise _error()
        return cls(raw["entry_id"], raw["device_profile_id"], raw["resolution_fingerprint"])


@dataclass(frozen=True)
class AppliedPublication:
    transaction_id: str
    candidate: AppliedBuildAssociation
    previous: AppliedBuildAssociation | None
    state: str = "pending"

    def same_identity(self, other):
        return (isinstance(other, AppliedPublication)
                and replace(self, state="pending") == replace(other, state="pending"))

    def to_dict(self):
        return {"schema_version": 2, "transaction_id": self.transaction_id,
                "candidate": self.candidate.to_dict(), "state": self.state,
                "previous": self.previous.to_dict() if self.previous else None}

    @classmethod
    def from_dict(cls, raw):
        if (not isinstance(raw, dict)
                or type(raw.get("schema_version")) is not int
                or raw["schema_version"] not in (1, 2)
                or set(raw) != ({"schema_version", "transaction_id", "candidate", "previous"}
                               | ({"state"} if raw["schema_version"] == 2 else set()))
                or raw.get("state", "pending") not in ("pending", "acknowledged")
                or not isinstance(raw["transaction_id"], str)
                or str(uuid.UUID(raw["transaction_id"])) != raw["transaction_id"]):
            raise _error()
        return cls(raw["transaction_id"], AppliedBuildAssociation.from_dict(raw["candidate"]),
                   None if raw["previous"] is None else AppliedBuildAssociation.from_dict(raw["previous"]),
                   raw.get("state", "pending"))


class _OwnedPackages(ConfigPackageLoader):
    """Reuse the production preflight on verified in-memory package material."""

    def __init__(self, packages):
        self._packages = packages

    def load_package(self, package_id):
        pid = validate_package_id(package_id)
        package = self._packages[pid]
        sources = package["sources"]
        return _parse_descriptor(package["descriptor"], package_id=pid, package_dir="",
                                 source_reader=lambda name: base64.b64decode(sources[name], validate=True))


@dataclass(frozen=True)
class LibrarySource:
    """Internal target input. Reload and verify before use; never a public model."""
    root: str
    entry_id: str

    def load(self):
        return BuildLibrary(self.root)._load(self.entry_id)


_isolated_install_root = ContextVar("isolated_library_install_root", default=None)


@contextmanager
def isolated_library_install_authority(library):
    """Explicit scoped authority for offline tests/disposable profile isolation.

    Durable records never establish authority themselves. Production callers
    omit this scope and use the active Kodi profile's default_build_library().
    """
    if not isinstance(library, BuildLibrary):
        raise _error()
    token = _isolated_install_root.set(library.root)
    try:
        yield
    finally:
        _isolated_install_root.reset(token)


def _authenticate_install_root(root):
    authority = _isolated_install_root.get()
    if authority is None:
        try:
            authority = default_build_library().root
        except Exception as exc:
            raise _error() from exc
    if root != authority:
        raise _error()


@dataclass(frozen=True)
class LibraryInstallTarget:
    """Durable exact entry/profile selector; never follows current selection.

    Only identity is persisted. Every load goes through registry/envelope
    authority and returns all three content owners from one verified snapshot.
    Paths are internal selectors, not presentation data or configuration values.
    """
    source: LibrarySource
    device_profile_id: str

    def __post_init__(self):
        if not isinstance(self.source, LibrarySource) or not isinstance(self.source.root, str):
            raise _error()
        BuildLibrary(self.source.root)
        if not isinstance(self.source.entry_id, str) or not _KEY.fullmatch(self.source.entry_id):
            raise _error()
        if not isinstance(self.device_profile_id, str) or not self.device_profile_id:
            raise _error()

    def load(self):
        _authenticate_install_root(self.source.root)
        loaded = self.source.load()
        if self.device_profile_id not in loaded[0].device_profiles:
            raise _error()
        return loaded

    def to_dict(self):
        return {"mode": "library", "root": self.source.root,
                "entry_id": self.source.entry_id, "device_profile_id": self.device_profile_id}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict)
                or set(value) != {"mode", "root", "entry_id", "device_profile_id"}
                or value["mode"] != "library"):
            raise _error()
        result = cls(LibrarySource(value["root"], value["entry_id"]), value["device_profile_id"])
        _authenticate_install_root(result.source.root)
        return result

    @classmethod
    def from_plan_target(cls, target):
        """Bind the exact source reviewed by Plan, without rereading selection."""
        result = cls(target.library_source, target.device_profile_id)
        result.load()
        return result


def _validate_bundle(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"schema_version", "manifest", "frozen", "packages"}:
        raise _error()
    if type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1:
        raise _error()
    manifest = validate_manifest(bundle["manifest"])
    frozen = FrozenBuildManifest.from_dict(bundle["frozen"])
    check_frozen_identity(manifest.build.id, frozen)
    if type(bundle["frozen"]["schema_version"]) is not int or len(set(frozen.configuration_packages)) != len(frozen.configuration_packages):
        raise _error()
    if not manifest.device_profiles or len({n.addon_id for n in frozen.addons}) != len(frozen.addons):
        raise _error()
    # Diagnostic maps can contain host paths/private runtime data. Prepared
    # public bundles may carry only this typed, known-safe source metadata.
    if set(frozen.source_metadata) - {"kodi_version"}:
        raise _error()
    if "kodi_version" in frozen.source_metadata and frozen.source_metadata["kodi_version"] != frozen.kodi_version:
        raise _error()
    for node in frozen.addons:
        if not _ADDON.fullmatch(node.addon_id) or node.error or node.provenance_detail:
            raise _error()
        if any(not _ADDON.fullmatch(edge.addon_id) or any(not _ADDON.fullmatch(parent) for parent in edge.required_by)
               for edge in node.dependency_edges):
            raise _error()
        if node.artifact is not None and (
            not _KEY.fullmatch(node.artifact.sha256) or node.artifact.size <= 0
            or len(_parts(node.artifact.filename)) != 1
        ):
            raise _error()
    packages = bundle["packages"]
    if not isinstance(packages, dict) or len(packages) > PACKAGE_LIMIT:
        raise _error()
    loader = _OwnedPackages(packages)
    required = set(frozen.configuration_packages)
    builds = [resolve_manifest(manifest, profile) for profile in sorted(manifest.device_profiles)]
    # Private declarations from any layer are forbidden in every public package.
    layers = [manifest, *manifest.platform_profiles.values(), *manifest.device_profiles.values(), *manifest.optional]
    private = {(p.target_kind.value, p.addon_id, p.key) for layer in layers
               if layer.config for p in layer.config.private_settings}
    for desired in builds:
        if desired.config:
            required.update(desired.config.packages)
        effective = loader.resolve(desired.config)
        for setting in effective.settings:
            if (setting.target in private or setting.addon_id == "plugin.video.redlight"
                    or _PRIVATE_KEY.search(setting.key)):
                raise _error()
        for item in effective.files:
            if "plugin.video.redlight" in item.destination.lower() or _PRIVATE_KEY.search(item.destination):
                raise _error()
    if set(packages) != required:
        raise _error()
    for pid, package in packages.items():
        validate_package_id(pid)
        if not isinstance(package, dict) or set(package) != {"descriptor", "sources"}:
            raise _error()
        if not isinstance(package["sources"], dict):
            raise _error()
        parsed = loader.load_package(pid)
        if set(package["sources"]) != {item.source for item in parsed.files}:
            raise _error()
        if any(len(item.content) > FILE_LIMIT for item in parsed.files):
            raise _error()
        # Check unused-by-profile frozen packages too; no shadow private values.
        for setting in parsed.settings:
            if setting.target in private or setting.addon_id == "plugin.video.redlight" or _PRIVATE_KEY.search(setting.key):
                raise _error()
        for item in parsed.files:
            if "plugin.video.redlight" in item.destination.lower() or _PRIVATE_KEY.search(item.destination):
                raise _error()
    overlay = bundle["manifest"].get("private_overlay")
    if overlay and (overlay.get("path_hint") or overlay.get("description")):
        raise _error()
    return manifest, frozen, loader


class BuildLibrary:
    """Production data API. Explicit roots are for isolated callers/tests only."""

    def __init__(self, root):
        self.root = os.fspath(root)
        if not os.path.isabs(self.root):
            raise _error()
        _parts(self.root[1:])

    def _registry(self, fd, *, required=False):
        data = _read_at(fd, "registry.json", STATE_LIMIT)
        if data is None:
            if required:
                raise _error()
            return {}
        raw = _json(data)
        if not isinstance(raw, dict) or set(raw) != {"schema_version", "entries"} or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            raise _error()
        entries = raw["entries"]
        if not isinstance(entries, dict) or any(not _KEY.fullmatch(key) for key in entries):
            raise _error()
        for key, metadata in entries.items():
            if not isinstance(metadata, dict) or set(metadata) != {"build_id", "build_version", "display_name", "device_profiles"}:
                raise _error()
            if any(not isinstance(metadata[k], str) for k in ("build_id", "build_version", "display_name")) or not isinstance(metadata["device_profiles"], list) or any(not isinstance(p, str) for p in metadata["device_profiles"]):
                raise _error()
        return entries

    def _metadata(self, manifest):
        return {"build_id": manifest.build.id, "build_version": manifest.build.version,
                "display_name": manifest.build.name, "device_profiles": sorted(manifest.device_profiles)}

    def _load_at(self, fd, key, entries):
        if not isinstance(key, str) or not _KEY.fullmatch(key) or key not in entries:
            raise _error()
        data = _read_at(fd, "builds/" + key + ".json", BUNDLE_LIMIT)
        if data is None:
            raise _error()
        bundle = _json(data)
        if hashlib.sha256(_encode(bundle)).hexdigest() != key:
            raise _error()
        loaded = _validate_bundle(bundle)
        if self._metadata(loaded[0]) != entries[key]:
            raise _error()
        return loaded

    def _load(self, key):
        try:
            with _directory(self.root) as fd:
                return self._load_at(fd, key, self._registry(fd))
        except Exception:
            raise _error() from None

    def get(self, key):
        manifest, _, _ = self._load(key)
        return LibraryEntry(key, manifest.build.id, manifest.build.version, manifest.build.name,
                            tuple(sorted(manifest.device_profiles)))

    def list_builds(self):
        try:
            with _directory(self.root) as fd:
                entries = self._registry(fd)
                result = []
                for key in sorted(entries):
                    try:
                        manifest, _, _ = self._load_at(fd, key, entries)
                        result.append(LibraryEntry(key, manifest.build.id, manifest.build.version,
                                                   manifest.build.name, tuple(sorted(manifest.device_profiles))))
                    except Exception:
                        # Corrupt entries are omitted, never advertised as usable.
                        continue
                return tuple(sorted(result, key=lambda e: (e.display_name.casefold(), e.build_id, e.build_version, e.entry_id)))
        except FileNotFoundError:
            return ()
        except Exception:
            raise _error() from None

    @contextmanager
    def _writer(self):
        import fcntl
        with _directory(self.root, create=True) as fd:
            lock = os.open("library.lock", os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=fd)
            try:
                if not stat.S_ISREG(os.fstat(lock).st_mode):
                    raise _error()
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield fd
            finally:
                os.close(lock)

    def register(self, manifest_path, frozen_path, packages_root):
        """Register already prepared PUBLIC material. No capture or acquisition.

        Copy only referenced package descriptors/assets, never a source tree or
        overlay payload. Validate a stable byte snapshot before publishing it.
        """
        try:
            raw = _json(_read_path(manifest_path, FILE_LIMIT))
            frozen_raw = _json(_read_path(frozen_path, FILE_LIMIT))
            manifest = validate_manifest(raw)
            frozen = FrozenBuildManifest.from_dict(frozen_raw)
            required = set(frozen.configuration_packages)
            for profile in manifest.device_profiles:
                desired = resolve_manifest(manifest, profile)
                if desired.config:
                    required.update(desired.config.packages)
            packages = {}
            if len(required) > PACKAGE_LIMIT:
                raise _error()
            total = 0
            if required:
                with _directory(packages_root) as source_fd:
                    for pid in sorted(required):
                        validate_package_id(pid)
                        descriptor = _read_at(source_fd, pid + "/package.json", FILE_LIMIT)
                        if descriptor is None:
                            raise _error()
                        total += len(descriptor)
                        if total > BUNDLE_LIMIT // 2:
                            raise _error()
                        descriptor = _json(descriptor)
                        sources = {}
                        def read_source(name):
                            nonlocal total
                            data = _read_at(source_fd, pid + "/" + name, FILE_LIMIT)
                            if data is None:
                                raise _error()
                            total += len(data)
                            if total > BUNDLE_LIMIT // 2:
                                raise _error()
                            sources[name] = base64.b64encode(data).decode("ascii")
                            return data
                        _parse_descriptor(descriptor, package_id=pid, package_dir="", source_reader=read_source)
                        packages[pid] = {"descriptor": descriptor, "sources": sources}
            bundle = {"schema_version": 1, "manifest": raw, "frozen": frozen_raw, "packages": packages}
            checked, _, _ = _validate_bundle(bundle)
            data = _encode(bundle)
            if len(data) > BUNDLE_LIMIT:
                raise _error()
            key = hashlib.sha256(data).hexdigest()
            metadata = self._metadata(checked)
            with self._writer() as fd:
                entries = self._registry(fd)
                if key in entries:
                    self._load_at(fd, key, entries)
                    return self.get(key)
                if any((m["build_id"], m["build_version"]) == (metadata["build_id"], metadata["build_version"]) for m in entries.values()):
                    raise LibraryConflict("build_library_conflict")
                try:
                    os.mkdir("builds", 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                builds_fd = os.open("builds", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    # An unindexed complete envelope left by an interrupted write
                    # may be replaced by identical, freshly validated content.
                    _atomic(builds_fd, key + ".json", data)
                finally:
                    os.close(builds_fd)
                entries[key] = metadata
                registry = _encode({"schema_version": 1, "entries": entries})
                if len(registry) > STATE_LIMIT:
                    raise _error()
                _atomic(fd, "registry.json", registry)
            return self.get(key)
        except LibraryConflict:
            raise
        except Exception:
            raise _error() from None

    def registered_bundle(self, bundle):
        """Resolve an ambiguous register failure against authoritative state.

        Returns None only for a genuinely absent root or readable valid registry
        lacking the exact key. Indexed-content failures propagate so callers
        retain required private data instead of guessing.
        """
        _validate_bundle(bundle)
        key = hashlib.sha256(_encode(bundle)).hexdigest()
        try:
            with ExitStack() as stack:
                try:
                    fd = stack.enter_context(_directory(self.root))
                except FileNotFoundError:
                    return None
                entries = self._registry(fd, required=True)
                if key not in entries:
                    return None
                manifest, _, _ = self._load_at(fd, key, entries)
                return LibraryEntry(key, manifest.build.id, manifest.build.version,
                                    manifest.build.name, tuple(sorted(manifest.device_profiles)))
        except Exception:
            raise _error() from None

    def select(self, entry_id, device_profile_id):
        try:
            with self._writer() as fd:
                manifest, _, _ = self._load_at(fd, entry_id, self._registry(fd))
                if device_profile_id not in manifest.device_profiles:
                    raise _error()
                _atomic(fd, "selection.json", _encode({"schema_version": 1, "entry_id": entry_id,
                                                        "device_profile_id": device_profile_id}))
            return SelectedBuild(entry_id, device_profile_id)
        except Exception:
            raise _error() from None

    def _selection_at(self, fd):
        """Read-only classification of the saved selection: ``none``, ``selected`` or ``invalid``.

        A cleared selection (``null``) and a missing file are both ``none``. Anything
        that does not validate against the registry and profile is ``invalid``.
        """
        data = _read_at(fd, "selection.json", STATE_LIMIT)
        if data is None:
            return "none", None
        try:
            raw = _json(data)
        except Exception:
            return "invalid", None
        if raw is None:
            return "none", None
        if not isinstance(raw, dict) or set(raw) != {"schema_version", "entry_id", "device_profile_id"} or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            return "invalid", None
        try:
            manifest, _, _ = self._load_at(fd, raw["entry_id"], self._registry(fd))
        except Exception:
            return "invalid", None
        if raw["device_profile_id"] not in manifest.device_profiles:
            return "invalid", None
        return "selected", SelectedBuild(raw["entry_id"], raw["device_profile_id"])

    def selection_state(self):
        """``(state, selection)`` for presentation only; never a status or plan target.

        Read-only: it never creates the library, never writes, and never repairs.
        """
        try:
            with _directory(self.root) as fd:
                return self._selection_at(fd)
        except FileNotFoundError:
            return "none", None
        except Exception:
            return "invalid", None

    def current_selection(self):
        state, selected = self.selection_state()
        return selected if state == "selected" else None

    def publication_journal(self) -> AppliedPublication | None:
        """Creation-free journal observation, including terminal evidence."""
        try:
            with _directory(self.root) as fd:
                return self._publication_at(fd)
        except FileNotFoundError:
            return None
        except Exception:
            raise _error() from None

    def pending_publication(self) -> AppliedPublication | None:
        """Only PENDING blocks Install; contradictory terminal state fails closed."""
        journal = self.publication_journal()
        if journal is None or journal.state == "pending":
            return journal
        try:
            with _directory(self.root) as fd:
                current = self._publication_at(fd)
                if current is None or current.state == "pending":
                    return current
                applied = self._applied_at(fd)
                if applied != current.candidate:
                    if applied != current.previous:
                        raise _error()
                    return current  # visible ACK is unresolved until materialized
            self._resolution(current.candidate)
            return None
        except Exception:
            raise _error() from None

    @staticmethod
    def _publication_at(fd):
        data = _read_at(fd, "applied-publication.json", STATE_LIMIT)
        return None if data is None else AppliedPublication.from_dict(_json(data))

    def _resolution(self, applied, resolution_store=None):
        from resources.lib.frozen_install import FrozenInstallStore
        from resources.lib.build_identity import bind_resolutions
        # The library and frozen store share the active profile's addon-data
        # parent. Reads do not create a directory or scan for a resolution.
        store = resolution_store or FrozenInstallStore(Path(self.root).parent, create=False)
        resolution = store.load_resolution_manifest(applied.resolution_fingerprint, nofollow=True)
        if resolution.resolution_fingerprint != applied.resolution_fingerprint:
            raise _error()
        public, frozen, _ = self._load(applied.entry_id)
        desired = resolve_manifest(public, applied.device_profile_id)
        bind_resolutions(desired.build.id, frozen, resolution,
                         policies=desired.frozen_install_policies)
        return resolution

    @staticmethod
    def _applied_at(fd):
        data = _read_at(fd, "applied.json", STATE_LIMIT)
        return None if data is None else AppliedBuildAssociation.from_dict(_json(data))

    def current_applied_association(self, *, resolution_store=None) -> AppliedBuildAssociation | None:
        """PENDING masks candidate; ACKNOWLEDGED remains terminal across restart."""
        try:
            with _directory(self.root) as fd:
                journal = self._publication_at(fd)
                if journal is not None and journal.state == "pending":
                    applied = journal.previous
                else:
                    applied = self._applied_at(fd)
                    # Recheck publication authority if it changed during the
                    # applied read; inspection never acknowledges or cleans it.
                    journal = self._publication_at(fd)
                    if journal is not None:
                        if journal.state == "pending":
                            applied = journal.previous
                        elif applied != journal.candidate:
                            if applied != journal.previous:
                                raise _error()
                            applied = journal.previous
            if applied is not None:
                self._resolution(applied, resolution_store)
            return applied
        except Exception:
            return None

    def _completed_publication_identity(self, transaction, store):
        from resources.lib.frozen_install import FrozenInstallTransaction, FrozenInstallPhase
        if (not isinstance(transaction, FrozenInstallTransaction)
                or transaction.phase is not FrozenInstallPhase.PUBLICATION_PENDING
                or transaction.library_target is None
                or transaction.library_target.source.root != self.root
                or store.read_snapshot(store.root) != transaction):
            raise LibraryConflict("completed_publication_owner_changed")
        candidate = AppliedBuildAssociation.from_dict({
            "schema_version": 2, "entry_id": transaction.library_target.source.entry_id,
            "device_profile_id": transaction.device_profile_id,
            "resolution_fingerprint": transaction.resolution_fingerprint})
        resolution = self._resolution(candidate, store)
        if (transaction.build_id != resolution.build_id
                or transaction.manifest_fingerprint != resolution.source_software_fingerprint
                or transaction.install_plan_fingerprint != resolution.install_plan_fingerprint
                or transaction.resolved_software_fingerprint != resolution.resulting_software_fingerprint
                or tuple(sorted(transaction.resolution_records, key=lambda r: r.addon_id)) != resolution.records):
            raise LibraryConflict("completed_publication_identity_changed")
        return candidate

    @_safe_publication_write
    def _create_applied_publication(self, transaction, *, resolution_store):
        """Create only from a durable frozen publication fence.

        The fence cannot be abandoned or normally cleared/transitioned. Frozen
        lock-free checks inside the library lock reject obsolete observations;
        the fence, rather than compensating snapshot checks, preserves ownership
        through journal write/crash ambiguity. Never nest persistence locks.
        """
        _authenticate_install_root(self.root)
        try:
            resolution_store._confirm_publication_owner(transaction)
        except Exception:
            raise LibraryConflict("completed_publication_owner_changed") from None
        candidate = self._completed_publication_identity(transaction, resolution_store)
        with self._writer() as fd:
            candidate = self._completed_publication_identity(transaction, resolution_store)
            current = self._publication_at(fd)
            if current is not None and current.state == "pending":
                if current.transaction_id != transaction.transaction_id or current.candidate != candidate:
                    raise LibraryConflict("applied_publication_pending")
                os.fsync(fd)
                return current
            if current is not None:
                if self._applied_at(fd) != current.candidate:
                    raise _error()
                self._resolution(current.candidate, resolution_store)
                os.fsync(fd)  # confirm preceding terminal state before advancing
                if current.transaction_id == transaction.transaction_id:
                    if current.candidate != candidate:
                        raise _error()
                    return current
            previous = self.current_applied_association(resolution_store=resolution_store)
            journal = AppliedPublication.from_dict(AppliedPublication(
                transaction.transaction_id, candidate, previous).to_dict())
            # A final lock-free owner check covers work done loading the prior
            # association. Other publication owners require this writer lock to
            # validate an intent before clearing its frozen transaction.
            self._completed_publication_identity(transaction, resolution_store)
            _atomic(fd, "applied-publication.json", _encode(journal.to_dict()))
            return journal

    def _publication_authority_at(self, fd, observed, resolution_store):
        current = self._publication_at(fd)
        if current is not None and current.same_identity(observed):
            self._resolution(current.candidate, resolution_store)
            if current.state == "acknowledged":
                applied = self._applied_at(fd)
                if applied not in (current.candidate, current.previous):
                    raise _error()
            os.fsync(fd)  # positive barrier for a visible, previously ambiguous write
            return "current", current
        if current is not None and current.state == "pending":
            raise LibraryConflict("applied_publication_changed")
        applied = self._applied_at(fd)
        if applied is None or (current is not None and applied != current.candidate):
            raise _error()
        self._resolution(applied, resolution_store)
        if applied == observed.candidate:
            os.fsync(fd)
            return "complete", None
        # A newer completed authority supersedes this observed publication.
        # In particular, never recreate an absent old intent or touch applied.
        return "superseded", None

    @_safe_publication_write
    def _validate_applied_publication(self, observed, *, resolution_store):
        """Validate/re-fsync existing authority only. Never create or replace it."""
        _authenticate_install_root(self.root)
        with self._writer() as fd:
            return self._publication_authority_at(fd, observed, resolution_store)

    @_safe_publication_write
    def _record_applied_completion(self, observed, *, resolution_store):
        """Serialized exact publication, with a positive terminal ACK barrier."""
        _authenticate_install_root(self.root)
        with self._writer() as fd:
            disposition, current = self._publication_authority_at(fd, observed, resolution_store)
            if disposition != "current":
                return disposition
            # ACK is the durable commit evidence; applied is its materialization.
            # Never publish candidate bytes until a positive ACK barrier succeeds.
            if current.state == "pending":
                # Older write ordering could leave candidate bytes masked by
                # PENDING. Restore the materialized previous state before ACK
                # so an ambiguous ACK replacement cannot look terminal.
                if self._applied_at(fd) == current.candidate and current.previous != current.candidate:
                    if current.previous is None:
                        os.unlink("applied.json", dir_fd=fd)
                        os.fsync(fd)
                    else:
                        _atomic(fd, "applied.json", _encode(current.previous.to_dict()))
                self._acknowledge_publication(fd, current)
            data = _encode(current.candidate.to_dict())
            if _read_at(fd, "applied.json", STATE_LIMIT) != data:
                _atomic(fd, "applied.json", data)
            os.fsync(fd)
            self._resolution(current.candidate, resolution_store)
            if _read_at(fd, "applied.json", STATE_LIMIT) != data:
                raise _error()
            return "complete"

    @staticmethod
    def _acknowledge_publication(fd, journal):
        acknowledged = replace(journal, state="acknowledged")
        _atomic(fd, "applied-publication.json", _encode(acknowledged.to_dict()))

    @_safe_publication_write
    def _cleanup_acknowledged_publication(self, observed, *, resolution_store):
        """Optional terminal GC; removal is never the proof of completion."""
        _authenticate_install_root(self.root)
        with self._writer() as fd:
            current = self._publication_at(fd)
            if current is None or not current.same_identity(observed):
                return False
            if current.state != "acknowledged":
                raise LibraryConflict("applied_publication_not_acknowledged")
            self._publication_authority_at(fd, current, resolution_store)
            if self._applied_at(fd) != current.candidate:
                return False  # unresolved ACK still owns materialization
            os.fsync(fd)  # applied must be independently durable before ACK removal
            # ACK was positively durable before unlink. A reappearing ACK after
            # cleanup ambiguity remains terminal and cannot expose previous.
            try:
                os.unlink("applied-publication.json", dir_fd=fd)
                os.fsync(fd)
            except OSError:
                return False
            return True

    def associated_status_target(self, *, resolution_store=None):
        from resources.lib.status import StatusTarget
        applied = self.current_applied_association(resolution_store=resolution_store)
        if applied is None:
            return None
        try:
            resolution = self._resolution(applied, resolution_store)
            path = str(Path(self.root) / "builds" / (applied.entry_id + ".json"))
            return StatusTarget(path, applied.device_profile_id, path,
                                library_source=LibrarySource(self.root, applied.entry_id),
                                applied_association=applied, install_resolution=resolution)
        except Exception:
            return None

    def associated_plan_target(self, *, resolution_store=None):
        target = self.associated_status_target(resolution_store=resolution_store)
        if target is None:
            return None
        from resources.lib.plan import PlanTarget
        return PlanTarget(target.configuration_manifest_path, target.device_profile_id,
                          target.software_manifest_path, library_source=target.library_source,
                          install_resolution=target.install_resolution)

    def clear_selection(self):
        try:
            with self._writer() as fd:
                _atomic(fd, "selection.json", b"null")
        except Exception:
            raise _error() from None

    def selected_status_target(self):
        from resources.lib.status import StatusTarget
        selected = self.current_selection()
        if selected is None:
            return None
        # Existing path fields remain for compatible callers; production library
        # targets consume the revalidated typed source instead of path loaders.
        path = str(Path(self.root) / "builds" / (selected.entry_id + ".json"))
        return StatusTarget(path, selected.device_profile_id, path,
                            library_source=LibrarySource(self.root, selected.entry_id))

    def plan_target(self, entry_id, device_profile_id):
        """Read-only target for an explicit session selection, independent of saved selection."""
        from resources.lib.plan import PlanTarget
        entry = self.get(entry_id)
        if device_profile_id not in entry.device_profiles:
            raise _error()
        path = str(Path(self.root) / "builds" / (entry.entry_id + ".json"))
        return PlanTarget(path, device_profile_id, path,
                          library_source=LibrarySource(self.root, entry.entry_id))

    def selected_plan_target(self):
        from resources.lib.plan import PlanTarget
        target = self.selected_status_target()
        if target is None:
            return None
        return PlanTarget(target.configuration_manifest_path, target.device_profile_id,
                          target.software_manifest_path, library_source=target.library_source)


def default_build_library():
    """Use only the active Kodi profile abstraction, never probe a host profile.

    Same parent as default_frozen_install_root(), without its host-test fallback.
    A missing runtime/profile translation makes production selection unavailable.
    """
    import xbmcvfs
    root = xbmcvfs.translatePath("special://profile/addon_data/script.build.manager")
    if not isinstance(root, str) or not os.path.isabs(root):
        raise _error()
    return BuildLibrary(os.path.join(root, "build-library"))


def selected_plan_target():
    try:
        return default_build_library().selected_plan_target()
    except Exception:
        return None


def authoritative_build_library():
    """Existing profile authority, with the explicit isolated test scope."""
    root = _isolated_install_root.get()
    return BuildLibrary(root) if root is not None else default_build_library()
