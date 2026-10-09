"""Frozen-build inventory and capture core (BM-021B).

This module creates immutable software snapshots; it does not install add-ons,
change Kodi settings, or read/write Kodi databases.  Acquisition is limited to
an existing artifact store, exact package-cache ZIPs, and an explicit optional
repository provider.  Installed-directory zipping is intentionally absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from resources.lib.artifacts import (
    ArtifactMetadata,
    ArtifactStore,
    ArtifactValidationError,
    validate_addon_zip,
)
from resources.lib.dependencies import _is_system_dependency, _strict_version_satisfies
from resources.lib.readonly_io import read_regular_file

if TYPE_CHECKING:
    from resources.lib.frozen_resolution import FrozenBuildRecoverabilitySummary
    from resources.lib.manifest import FrozenInstallPolicy


class CaptureError(Exception):
    """Base class for inventory and capture errors."""


class CaptureStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE_ARTIFACT = "incomplete_artifact"
    INCOMPLETE_PROVENANCE = "incomplete_provenance"
    INVALID_PACKAGE = "invalid_package"
    UNSUPPORTED = "unsupported"
    MISSING = "missing"
    SYSTEM = "system"
    PLATFORM_PROVIDED = "platform_provided"


class ProvenanceStatus(str, Enum):
    VERIFIED_REPOSITORY = "verified_repository"
    REPOSITORY_EVIDENCE = "repository_evidence"
    MANUAL_OR_UNKNOWN = "manual_or_unknown"
    UNKNOWN = "unknown"


class InstalledOrigin(str, Enum):
    """Which trusted root an installed add-on's metadata was read from."""

    HOME = "home"
    APPLICATION = "application"


@dataclass(frozen=True)
class InstalledMetadata:
    """Installed addon.xml bytes together with the trusted origin that proved them.

    The origin is assigned only after the trusted root, identity and safe read
    have all succeeded in the same operation. It is never serialized.
    """

    xml_bytes: bytes
    origin: InstalledOrigin


@dataclass(frozen=True)
class DependencyEdge:
    addon_id: str
    min_version: str = ""
    optional: bool = False
    required_by: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "addon_id": self.addon_id,
            "min_version": self.min_version,
            "optional": self.optional,
            "required_by": list(self.required_by),
        }


@dataclass(frozen=True)
class ArtifactAcquisition:
    status: CaptureStatus
    metadata: Optional[ArtifactMetadata] = None
    source: str = ""
    error: str = ""


@dataclass(frozen=True)
class AddonCaptureNode:
    addon_id: str
    version: str
    addon_type: str
    desired_enabled: bool
    provenance: ProvenanceStatus
    provenance_detail: Mapping[str, str] = field(default_factory=dict)
    artifact: Optional[ArtifactMetadata] = None
    dependency_edges: Tuple[DependencyEdge, ...] = ()
    system: bool = False
    optional: bool = False
    status: CaptureStatus = CaptureStatus.COMPLETE
    error: str = ""
    platform_provided: bool = False

    def __post_init__(self) -> None:
        """Reject contradictory combinations at construction, so no path can carry one."""
        if not self.platform_provided:
            if self.status is CaptureStatus.PLATFORM_PROVIDED:
                raise CaptureError("platform-provided status requires the platform marker")
            return
        if self.status is not CaptureStatus.PLATFORM_PROVIDED:
            raise CaptureError("platform-provided add-on must have platform-provided status")
        if self.system:
            raise CaptureError("platform-provided add-on cannot be a system dependency")
        if self.artifact is not None:
            raise CaptureError("platform-provided add-on cannot carry an artifact")
        if not self.addon_id or not self.version or not self.addon_type:
            raise CaptureError("platform-provided add-on requires identity, version and type")
        if not self.dependency_edges:
            raise CaptureError("platform-provided add-on requires trusted dependency edges")

    @property
    def required_dependency_ids(self) -> Tuple[str, ...]:
        return tuple(edge.addon_id for edge in self.dependency_edges if not edge.optional)

    @property
    def optional_dependency_ids(self) -> Tuple[str, ...]:
        return tuple(edge.addon_id for edge in self.dependency_edges if edge.optional)

    @property
    def is_absent_optional_dependency(self) -> bool:
        """Whether this node records an optional dependency absent at capture."""
        return (
            not self.system
            and self.optional
            and self.status is CaptureStatus.MISSING
            and not self.desired_enabled
            and self.artifact is None
        )

    def to_dict(self, schema_version: int = 1) -> dict:
        result = {
            "addon_id": self.addon_id,
            "version": self.version,
            "addon_type": self.addon_type,
            "desired_enabled": self.desired_enabled,
            "provenance": self.provenance.value,
            "provenance_detail": dict(sorted(self.provenance_detail.items())),
            "artifact_sha256": self.artifact.sha256 if self.artifact else None,
            "artifact_size": self.artifact.size if self.artifact else None,
            "required_dependency_ids": list(self.required_dependency_ids),
            "optional_dependency_ids": list(self.optional_dependency_ids),
            "dependency_edges": [edge.to_dict() for edge in self.dependency_edges],
            "system": self.system,
            "optional": self.optional,
            "capture_status": self.status.value,
        }
        if schema_version >= 2:
            # Schema v1 has no platform marker; its serialized bytes must not change.
            result["platform_provided"] = self.platform_provided
        if self.artifact is not None:
            result["artifact_filename"] = self.artifact.filename
        if self.error:
            result["error"] = self.error
        return result


@dataclass(frozen=True)
class FrozenBuildManifest:
    """Versioned, serializable frozen software graph."""

    schema_version: int
    build_id: str
    name: str
    created_at: str
    kodi_version: str
    platform: str
    capture_status: CaptureStatus
    addons: Tuple[AddonCaptureNode, ...]
    configuration_packages: Tuple[str, ...] = ()
    source_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Schema v2 exists only to carry platform-provided meaning (D-028)."""
        if self.schema_version not in (1, 2) or isinstance(self.schema_version, bool):
            raise CaptureError("unsupported frozen manifest schema")
        platform = any(node.platform_provided for node in self.addons)
        if self.schema_version == 1 and platform:
            raise CaptureError("frozen manifest schema 1 cannot carry platform-provided add-ons")
        if self.schema_version == 2 and not platform:
            raise CaptureError("frozen manifest schema 2 requires a platform-provided add-on")

    def software_graph(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "kodi_version": self.kodi_version,
            "platform": self.platform,
            "addons": [
                node.to_dict(self.schema_version)
                for node in sorted(self.addons, key=lambda item: item.addon_id)
            ],
            "configuration_packages": sorted(self.configuration_packages),
        }

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.software_graph(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "build_id": self.build_id,
            "name": self.name,
            "created_at": self.created_at,
            "source": {
                "kodi_version": self.kodi_version,
                "platform": self.platform,
                "metadata": dict(sorted(self.source_metadata.items())),
            },
            "software_fingerprint": self.fingerprint(),
            "capture_status": self.capture_status.value,
            "addons": [
                node.to_dict(self.schema_version)
                for node in sorted(self.addons, key=lambda item: item.addon_id)
            ],
            "configuration_packages": sorted(self.configuration_packages),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: object) -> "FrozenBuildManifest":
        """Parse the exact manifest-v1 representation emitted by ``to_dict``.

        The installer accepts only the typed, versioned representation.  It
        does not interpret arbitrary runtime state or silently fill in missing
        artifact identity fields.
        """
        if not isinstance(value, dict):
            raise CaptureError("frozen manifest must be an object")
        required = {
            "schema_version", "build_id", "name", "created_at", "source",
            "software_fingerprint", "capture_status", "addons",
            "configuration_packages",
        }
        if set(value) != required:
            raise CaptureError("frozen manifest fields are not exactly supported")
        schema_version = value["schema_version"]
        if schema_version not in (1, 2) or isinstance(schema_version, bool):
            raise CaptureError("unsupported frozen manifest schema")
        source = value["source"]
        if not isinstance(source, dict) or set(source) != {
            "kodi_version", "platform", "metadata"
        }:
            raise CaptureError("frozen manifest source is malformed")
        metadata = source["metadata"]
        if not isinstance(metadata, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in metadata.items()
        ):
            raise CaptureError("frozen manifest source metadata is malformed")
        addons = value["addons"]
        if not isinstance(addons, list):
            raise CaptureError("frozen manifest addons must be a list")
        nodes = tuple(_node_from_dict(item, schema_version) for item in addons)
        packages = value["configuration_packages"]
        if not isinstance(packages, list) or any(
            not isinstance(item, str) or not item for item in packages
        ):
            raise CaptureError("frozen manifest configuration packages are malformed")
        manifest = cls(
            schema_version=schema_version,
            build_id=_manifest_string(value, "build_id"),
            name=_manifest_string(value, "name"),
            created_at=_manifest_string(value, "created_at"),
            kodi_version=_manifest_string(source, "kodi_version"),
            platform=_manifest_string(source, "platform"),
            capture_status=CaptureStatus(value["capture_status"]),
            addons=nodes,
            configuration_packages=tuple(packages),
            source_metadata=dict(metadata),
        )
        if value["software_fingerprint"] != manifest.fingerprint():
            raise CaptureError("frozen manifest fingerprint does not match content")
        return manifest

    @classmethod
    def from_json(cls, text: str) -> "FrozenBuildManifest":
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CaptureError("frozen manifest JSON is invalid") from exc
        return cls.from_dict(value)


@dataclass(frozen=True)
class FrozenBuildCaptureResult:
    manifest: FrozenBuildManifest
    errors: Tuple[str, ...] = ()
    recoverability: Optional["FrozenBuildRecoverabilitySummary"] = None

    @property
    def complete(self) -> bool:
        # Any capture error is blocking, so it can never coexist with a complete graph.
        return self.manifest.capture_status == CaptureStatus.COMPLETE and not self.errors

    @property
    def exact_frozen_coverage(self) -> Optional[str]:
        return self.recoverability.exact_frozen_coverage if self.recoverability else None

    def to_dict(self) -> dict:
        return {
            "build_id": self.manifest.build_id,
            "capture_complete": self.complete,
            "captured_desired_state": (
                self.recoverability.captured_desired_state if self.recoverability else "unknown"
            ),
            "exact_frozen_coverage": self.exact_frozen_coverage,
            "install_recoverability": (
                self.recoverability.install_recoverability if self.recoverability else "unknown"
            ),
            "recoverability": (
                self.recoverability.to_dict() if self.recoverability else None
            ),
            "errors": list(self.errors),
        }


def _manifest_string(value: Mapping[str, object], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise CaptureError(f"frozen manifest {field} must be a non-empty string")
    return result


def _node_from_dict(value: object, schema_version: int = 1) -> AddonCaptureNode:
    if not isinstance(value, dict):
        raise CaptureError("frozen manifest add-on node must be an object")
    required = {
        "addon_id", "version", "addon_type", "desired_enabled", "provenance",
        "provenance_detail", "artifact_sha256", "artifact_size",
        "required_dependency_ids", "optional_dependency_ids", "dependency_edges",
        "system", "optional", "capture_status",
    }
    if schema_version == 2:
        required = required | {"platform_provided"}
    optional = {"artifact_filename", "error"}
    if set(value) - required - optional or not required.issubset(value):
        raise CaptureError("frozen manifest add-on node fields are not supported")
    addon_id = _manifest_string(value, "addon_id")
    try:
        status = CaptureStatus(value["capture_status"])
    except (TypeError, ValueError) as exc:
        raise CaptureError("frozen manifest add-on capture status is invalid") from exc
    version = value["version"]
    addon_type = value["addon_type"]
    if not isinstance(version, str):
        raise CaptureError("frozen manifest add-on version is malformed")
    if status is CaptureStatus.MISSING:
        if version not in ("", "not-installed"):
            raise CaptureError("missing frozen manifest add-on has a version")
    elif not version:
        raise CaptureError("frozen manifest add-on version is malformed")
    if not isinstance(addon_type, str) or (not addon_type and status is not CaptureStatus.MISSING):
        raise CaptureError("frozen manifest add-on type is malformed")
    if not isinstance(value["desired_enabled"], bool):
        raise CaptureError("frozen manifest desired_enabled must be boolean")
    if status is CaptureStatus.MISSING and value["desired_enabled"]:
        raise CaptureError("missing frozen manifest add-on cannot be enabled")
    detail = value["provenance_detail"]
    if not isinstance(detail, dict) or any(
        not isinstance(k, str) or not isinstance(v, str)
        for k, v in detail.items()
    ):
        raise CaptureError("frozen manifest provenance_detail is malformed")
    required_ids = value["required_dependency_ids"]
    optional_ids = value["optional_dependency_ids"]
    if (
        not isinstance(required_ids, list)
        or not isinstance(optional_ids, list)
        or any(not isinstance(item, str) or not item for item in required_ids + optional_ids)
    ):
        raise CaptureError("frozen manifest dependency IDs are malformed")
    raw_edges = value["dependency_edges"]
    if not isinstance(raw_edges, list):
        raise CaptureError("frozen manifest dependency edges must be a list")
    edges = []
    for raw in raw_edges:
        if not isinstance(raw, dict) or set(raw) != {
            "addon_id", "min_version", "optional", "required_by"
        }:
            raise CaptureError("frozen manifest dependency edge is malformed")
        required_by = raw["required_by"]
        if (
            not isinstance(raw["addon_id"], str) or not raw["addon_id"]
            or not isinstance(raw["min_version"], str)
            or not isinstance(raw["optional"], bool)
            or not isinstance(required_by, list)
            or any(not isinstance(item, str) or not item for item in required_by)
        ):
            raise CaptureError("frozen manifest dependency edge has invalid fields")
        edges.append(DependencyEdge(
            addon_id=raw["addon_id"],
            min_version=raw["min_version"],
            optional=raw["optional"],
            required_by=tuple(required_by),
        ))
    artifact = None
    if value["artifact_sha256"] is not None or value["artifact_size"] is not None:
        if (
            not isinstance(value["artifact_sha256"], str)
            or not isinstance(value["artifact_size"], int)
            or isinstance(value["artifact_size"], bool)
            or value["artifact_size"] < 0
            or not isinstance(value.get("artifact_filename"), str)
            or not value["artifact_filename"]
        ):
            raise CaptureError("frozen manifest artifact metadata is malformed")
        artifact = ArtifactMetadata(
            sha256=value["artifact_sha256"],
            size=value["artifact_size"],
            addon_id=addon_id,
            version=version,
            filename=value["artifact_filename"],
            source=str(detail.get("artifact_source", "")),
        )
    elif "artifact_filename" in value:
        raise CaptureError("frozen manifest artifact filename has no artifact")
    if value["system"] and artifact is not None:
        raise CaptureError("system dependency cannot have a frozen artifact")
    if not isinstance(value["system"], bool) or not isinstance(value["optional"], bool):
        raise CaptureError("frozen manifest system/optional fields must be boolean")
    error = value.get("error", "")
    if not isinstance(error, str):
        raise CaptureError("frozen manifest node error must be a string")
    platform_provided = value.get("platform_provided", False)
    if not isinstance(platform_provided, bool):
        raise CaptureError("frozen manifest platform marker must be boolean")
    return AddonCaptureNode(
        addon_id=addon_id,
        version=version,
        addon_type=addon_type,
        desired_enabled=value["desired_enabled"],
        provenance=ProvenanceStatus(value["provenance"]),
        provenance_detail=dict(detail),
        artifact=artifact,
        dependency_edges=tuple(edges),
        system=value["system"],
        optional=value["optional"],
        status=status,
        error=error,
        platform_provided=platform_provided,
    )


class InventoryBackend:
    """Read-only source interface for installed add-on capture."""

    def get_installed_addons(self) -> Sequence[Mapping[str, object]]:
        raise NotImplementedError

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        raise NotImplementedError

    def read_installed_metadata(
        self, addon_id: str, *, installed: Optional[Sequence[Mapping[str, object]]] = None,
    ) -> Optional[InstalledMetadata]:
        """Installed addon.xml with its trusted origin. A backend without roots is HOME-only."""
        xml_bytes = self.read_addon_xml(addon_id)
        return None if xml_bytes is None else InstalledMetadata(xml_bytes, InstalledOrigin.HOME)

    def get_package_cache(self, addon_id: str, version: str) -> Sequence[Tuple[str, bytes]]:
        return ()

    def get_repository_artifact(self, addon_id: str, version: str) -> Optional[Tuple[str, bytes]]:
        return None

    def get_provenance(self, addon_id: str) -> Tuple[ProvenanceStatus, Mapping[str, str]]:
        return ProvenanceStatus.UNKNOWN, {}

    def get_source_metadata(self) -> Mapping[str, str]:
        return {}


class InMemoryInventoryBackend(InventoryBackend):
    """Small deterministic backend for tests and disposable harness fixtures."""

    def __init__(
        self,
        addons: Sequence[Mapping[str, object]],
        addon_xml: Mapping[str, bytes],
        package_cache: Optional[Mapping[Tuple[str, str], Sequence[Tuple[str, bytes]]]] = None,
        repository: Optional[Mapping[Tuple[str, str], Tuple[str, bytes]]] = None,
        provenance: Optional[Mapping[str, Tuple[ProvenanceStatus, Mapping[str, str]]]] = None,
        source_metadata: Optional[Mapping[str, str]] = None,
        application_addon_ids: Sequence[str] = (),
    ):
        self.application_addon_ids = frozenset(application_addon_ids)
        self.addons = tuple(dict(item) for item in addons)
        self.addon_xml = dict(addon_xml)
        self.package_cache = dict(package_cache or {})
        self.repository = dict(repository or {})
        self.provenance = dict(provenance or {})
        self.source_metadata = dict(source_metadata or {})

    def get_installed_addons(self) -> Sequence[Mapping[str, object]]:
        return self.addons

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        return self.addon_xml.get(addon_id)

    def read_installed_metadata(
        self, addon_id: str, *, installed: Optional[Sequence[Mapping[str, object]]] = None,
    ) -> Optional[InstalledMetadata]:
        xml_bytes = self.addon_xml.get(addon_id)
        if xml_bytes is None:
            return None
        origin = (
            InstalledOrigin.APPLICATION if addon_id in self.application_addon_ids else InstalledOrigin.HOME
        )
        return InstalledMetadata(xml_bytes, origin)

    def get_package_cache(self, addon_id: str, version: str) -> Sequence[Tuple[str, bytes]]:
        return self.package_cache.get((addon_id, version), ())

    def get_repository_artifact(self, addon_id: str, version: str) -> Optional[Tuple[str, bytes]]:
        return self.repository.get((addon_id, version))

    def get_provenance(self, addon_id: str) -> Tuple[ProvenanceStatus, Mapping[str, str]]:
        return self.provenance.get(addon_id, (ProvenanceStatus.UNKNOWN, {}))

    def get_source_metadata(self) -> Mapping[str, str]:
        return self.source_metadata


_ADDON_XML_LIMIT = 1024 * 1024
_SAFE_ADDON_COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,159}")
_HOME_ADDONS_PREFIX = "special://home/addons/"
_APPLICATION_ADDONS_PREFIX = "special://xbmc/addons/"


def _open_canonical_directory(canonical: Path) -> int:
    """Open an absolute canonical directory one component at a time, never following a link.

    Each component is opened relative to the previous descriptor with O_NOFOLLOW,
    so the walk never re-resolves a pathname from the top and cannot be redirected
    by a symlink that appears in an ancestor during the walk.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in canonical.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


class _TrustedRoot:
    """A canonical add-ons root whose authority is pinned by one held descriptor.

    The held descriptor keeps the inode allocated, so the recorded (st_dev, st_ino)
    cannot be recycled into a different directory while this object lives. The
    descriptor is released by close() or when the object is garbage collected.
    """

    def __init__(self, canonical: Path, anchor_fd: int, identity: Tuple[int, int]):
        self.canonical = canonical
        self.identity = identity
        self._finalizer = weakref.finalize(self, os.close, anchor_fd)

    @classmethod
    def establish(cls, path: Path) -> Optional["_TrustedRoot"]:
        """Record authority over the object the canonical root names right now, or None."""
        canonical = Path(path).resolve()
        try:
            fd = _open_canonical_directory(canonical)
        except OSError:
            return None
        try:
            info = os.fstat(fd)
        except OSError:
            os.close(fd)
            return None
        return cls(canonical, fd, (info.st_dev, info.st_ino))

    def reacquire(self) -> Optional[int]:
        """A fresh root descriptor, only if the canonical path still names the recorded object."""
        if not self._finalizer.alive:
            return None
        try:
            fd = _open_canonical_directory(self.canonical)
        except OSError:
            return None
        try:
            info = os.fstat(fd)
        except OSError:
            os.close(fd)
            return None
        if (info.st_dev, info.st_ino) != self.identity:
            os.close(fd)
            return None
        return fd

    def close(self) -> None:
        self._finalizer()


class KodiInventoryBackend(InventoryBackend):
    """Read-only Kodi JSON-RPC/filesystem adapter.

    ``rpc`` must return the JSON-RPC result object, as the project's disposable
    harness does.  Internal database origin evidence is accepted only through
    the optional read-only ``origin_reader`` callback.

    Installed ``addon.xml`` is read only from an explicit trusted root: the home
    add-ons directory, and optionally the Kodi application add-ons directory
    (``special://xbmc/addons``) for bundled add-ons. Kodi's reported path is
    never authority by itself. Authority over each root is recorded at
    construction and re-verified on every read, so replacing a root, an ancestor,
    or the root path fails closed.
    """

    def __init__(
        self,
        rpc: Callable[[str, dict], Mapping[str, object]],
        *,
        addons_dir: Path,
        package_cache_dir: Path,
        origin_reader: Optional[Callable[[str], Tuple[ProvenanceStatus, Mapping[str, str]]]] = None,
        application_addons_dir: Optional[Path] = None,
    ):
        self.rpc = rpc
        self.addons_dir = Path(addons_dir).resolve()
        self.package_cache_dir = Path(package_cache_dir).resolve()
        self.origin_reader = origin_reader
        if application_addons_dir is not None and not os.path.isabs(str(application_addons_dir)):
            raise ValueError("application add-ons root must be an absolute path")
        self.application_addons_dir = (
            Path(application_addons_dir).resolve() if application_addons_dir is not None else None
        )
        # Authority over each configured root is recorded once, here; reads re-verify it.
        self._home = _TrustedRoot.establish(self.addons_dir)
        self._application = (
            _TrustedRoot.establish(self.application_addons_dir)
            if self.application_addons_dir is not None else None
        )

    def get_installed_addons(self) -> Sequence[Mapping[str, object]]:
        result = self.rpc(
            "Addons.GetAddons",
            {
                "installed": True,
                "properties": ["name", "version", "path", "enabled", "installed", "broken", "dependencies"],
            },
        )
        addons = result.get("addons") if isinstance(result, Mapping) else None
        if not isinstance(addons, list):
            raise CaptureError("Kodi returned malformed installed add-on inventory")
        return tuple(item for item in addons if isinstance(item, Mapping))

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        metadata = self.read_installed_metadata(addon_id)
        return None if metadata is None else metadata.xml_bytes

    def read_installed_metadata(
        self, addon_id: str, *, installed: Optional[Sequence[Mapping[str, object]]] = None,
    ) -> Optional[InstalledMetadata]:
        """Read addon.xml from its trusted root and report which root proved it.

        The origin is assigned only after the trusted root, identity and safe read
        have all succeeded in this one operation. Kodi's reported path is still
        never authority by itself. ``installed`` may carry a listing already read
        from Kodi, so callers that classify many add-ons make one inventory call.
        """
        # An identifier must be exactly one safe directory name, so it can never
        # traverse out of a trusted root.
        if not isinstance(addon_id, str) or not _SAFE_ADDON_COMPONENT.fullmatch(addon_id):
            return None
        listing = self.get_installed_addons() if installed is None else installed
        details = next((item for item in listing if item.get("addonid") == addon_id), None)
        path_value = details.get("path") if details else None
        root = self._trusted_root(addon_id, path_value)
        if root is None:
            return None
        xml_bytes = self._read_addon_xml_in(root, addon_id)
        if xml_bytes is None:
            return None
        origin = InstalledOrigin.APPLICATION if root is self._application else InstalledOrigin.HOME
        return InstalledMetadata(xml_bytes, origin)

    def _trusted_roots(self):
        roots = [(_HOME_ADDONS_PREFIX, self._home)]
        if self.application_addons_dir is not None:
            roots.append((_APPLICATION_ADDONS_PREFIX, self._application))
        return tuple(roots)

    def _trusted_root(self, addon_id: str, path_value) -> Optional["_TrustedRoot"]:
        """Return the explicit trusted root that directly holds this add-on, or None.

        A Kodi-reported special path must name exactly the requested add-on's
        directory under a configured root. An absolute path must resolve, after
        symlinks and ``..`` are removed, to ``<trusted root>/<addon_id>``. Any other
        value, including traversal, sibling and prefix-confusion paths, is rejected.
        """
        if path_value is None or path_value == "":
            return self._home
        if not isinstance(path_value, str):
            return None
        for prefix, root in self._trusted_roots():
            if path_value.startswith(prefix):
                name = path_value[len(prefix):]
                if name.endswith("/"):
                    name = name[:-1]
                return root if root is not None and name == addon_id else None
        if not os.path.isabs(path_value):
            return None
        try:
            resolved = Path(path_value).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        for _, root in self._trusted_roots():
            if root is not None and resolved.parent == root.canonical and resolved.name == addon_id:
                return root
        return None

    def _read_addon_xml_in(self, trusted: "_TrustedRoot", addon_id: str) -> Optional[bytes]:
        """Read ``<trusted root>/<addon_id>/addon.xml`` from a freshly verified root descriptor.

        The root is re-walked from its canonical path and must still be the recorded
        object. Only then is the add-on directory opened relative to that descriptor,
        and addon.xml relative to the directory. No link is followed at any step.
        """
        root_fd = trusted.reacquire()
        if root_fd is None:
            return None
        try:
            try:
                directory_fd = os.open(
                    addon_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd,
                )
            except OSError:
                return None
            try:
                return read_regular_file("addon.xml", limit=_ADDON_XML_LIMIT, dir_fd=directory_fd)
            except Exception:
                return None
            finally:
                os.close(directory_fd)
        finally:
            os.close(root_fd)

    def close(self) -> None:
        """Release the pinned root descriptors. Metadata reads after close fail closed."""
        for root in (self._home, self._application):
            if root is not None:
                root.close()

    def get_package_cache(self, addon_id: str, version: str) -> Sequence[Tuple[str, bytes]]:
        if not self.package_cache_dir.is_dir():
            return ()
        result = []
        for path in sorted(self.package_cache_dir.glob("*.zip")):
            try:
                result.append((path.name, path.read_bytes()))
            except OSError:
                continue
        return tuple(result)

    def get_provenance(self, addon_id: str) -> Tuple[ProvenanceStatus, Mapping[str, str]]:
        if self.origin_reader is None:
            return ProvenanceStatus.UNKNOWN, {}
        return self.origin_reader(addon_id)

    def get_source_metadata(self) -> Mapping[str, str]:
        result = self.rpc("Application.GetProperties", {"properties": ["version"]})
        version = result.get("version") if isinstance(result, Mapping) else None
        if isinstance(version, Mapping):
            major = version.get("major")
            minor = version.get("minor")
            if isinstance(major, int) and isinstance(minor, int):
                return {"kodi_version": f"{major}.{minor}"}
        return {}


class ArtifactAcquirer:
    """Acquire exact artifacts in the BM-021A priority order."""

    def __init__(self, store: ArtifactStore, backend: InventoryBackend):
        self.store = store
        self.backend = backend

    def acquire(self, addon_id: str, version: str) -> ArtifactAcquisition:
        existing = self.store.find(addon_id, version)
        if existing is not None:
            try:
                self.store.read_bytes(existing.sha256)
            except Exception as exc:
                return ArtifactAcquisition(CaptureStatus.INVALID_PACKAGE, error=str(exc))
            return ArtifactAcquisition(CaptureStatus.COMPLETE, existing, "artifact_store")

        for filename, data in self.backend.get_package_cache(addon_id, version):
            try:
                metadata = validate_addon_zip(
                    data, expected_addon_id=addon_id, expected_version=version, source="package_cache"
                )
                metadata = self.store.import_zip(
                    data, expected_addon_id=addon_id, expected_version=version, source="package_cache"
                )
                return ArtifactAcquisition(CaptureStatus.COMPLETE, metadata, "package_cache")
            except ArtifactValidationError:
                continue
            except Exception as exc:
                return ArtifactAcquisition(CaptureStatus.INVALID_PACKAGE, error=f"{filename}: {exc}")

        repository_candidate = self.backend.get_repository_artifact(addon_id, version)
        if repository_candidate is not None:
            filename, data = repository_candidate
            try:
                validate_addon_zip(
                    data, expected_addon_id=addon_id, expected_version=version, source="repository"
                )
                metadata = self.store.import_zip(
                    data, expected_addon_id=addon_id, expected_version=version, source="repository"
                )
                return ArtifactAcquisition(CaptureStatus.COMPLETE, metadata, "repository")
            except ArtifactValidationError as exc:
                return ArtifactAcquisition(CaptureStatus.INVALID_PACKAGE, error=f"{filename}: {exc}")
            except Exception as exc:
                return ArtifactAcquisition(CaptureStatus.INVALID_PACKAGE, error=f"{filename}: {exc}")

        return ArtifactAcquisition(
            CaptureStatus.INCOMPLETE_ARTIFACT,
            error=f"exact artifact unavailable for {addon_id} {version}",
        )


_IMPORT_RE = re.compile(r"^import$")


def _check_addon_xml_identity(xml_bytes: bytes, addon_id: str, installed_version) -> None:
    """Refuse metadata that does not describe the inventory add-on it was read for."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CaptureError(f"{addon_id}: malformed addon.xml") from exc
    if root.tag.rsplit("}", 1)[-1] != "addon" or root.get("id") != addon_id:
        raise CaptureError(f"{addon_id}: addon.xml identity does not match the installed add-on")
    if isinstance(installed_version, str) and installed_version and root.get("version") != installed_version:
        raise CaptureError(f"{addon_id}: addon.xml version does not match the installed add-on")


def _parse_dependency_edges(xml_bytes: bytes, addon_id: str) -> Tuple[DependencyEdge, ...]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CaptureError(f"{addon_id}: malformed addon.xml") from exc
    requires = next((child for child in root if child.tag.rsplit("}", 1)[-1] == "requires"), None)
    if requires is None:
        return ()
    edges = []
    for child in requires:
        if child.tag.rsplit("}", 1)[-1] != "import":
            continue
        target = child.attrib.get("addon", "")
        if not target:
            raise CaptureError(f"{addon_id}: dependency is missing addon ID")
        optional = child.attrib.get("optional", "false").lower() == "true"
        edges.append(
            DependencyEdge(target, child.attrib.get("version", ""), optional, (addon_id,))
        )
    return tuple(sorted(edges, key=lambda edge: (edge.addon_id, edge.optional, edge.min_version)))


def _declared_extension_points(xml_bytes: bytes, addon_id: str) -> Tuple[str, ...]:
    """Extension points an addon.xml declares. Kodi derives an add-on's type from them (D-028)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CaptureError(f"{addon_id}: malformed addon.xml") from exc
    return tuple(
        child.attrib.get("point", "")
        for child in root
        if child.tag.rsplit("}", 1)[-1] == "extension"
    )


def _combine_edges(edges: Iterable[DependencyEdge]) -> Tuple[DependencyEdge, ...]:
    grouped: Dict[Tuple[str, bool, str], set] = {}
    for edge in edges:
        grouped.setdefault((edge.addon_id, edge.optional, edge.min_version), set()).update(edge.required_by)
    return tuple(
        DependencyEdge(addon_id, min_version, optional, tuple(sorted(required_by)))
        for (addon_id, optional, min_version), required_by in sorted(grouped.items())
    )


def _platform_node(
    addon_id: str,
    raw: Mapping[str, object],
    optional: bool,
    edges: Sequence[DependencyEdge],
    incoming_minima: Sequence[str],
    declared_points: Sequence[str],
) -> AddonCaptureNode:
    """Record a trusted application add-on as a verified platform requirement (D-028).

    Capture records the observed identity and dependency closure only. It never
    acquires, installs, enables or disables anything. Any defect makes the node
    UNSUPPORTED, so the capture cannot complete with it.
    """
    version = raw.get("version")
    addon_type = raw.get("type", "")
    enabled = raw.get("enabled", False)
    broken = raw.get("broken", False)

    def unsupported(reason: str) -> AddonCaptureNode:
        return AddonCaptureNode(
            addon_id=addon_id,
            version=str(version or ""),
            addon_type=str(addon_type or ""),
            desired_enabled=bool(enabled),
            provenance=ProvenanceStatus.UNKNOWN,
            optional=optional,
            status=CaptureStatus.UNSUPPORTED,
            error=reason,
        )

    if (
        not isinstance(version, str) or not version
        or not isinstance(addon_type, str) or not addon_type
        or not isinstance(enabled, bool) or not isinstance(broken, bool)
    ):
        return unsupported("installed metadata is malformed")
    if broken:
        return unsupported("platform-provided add-on is broken")
    if not enabled:
        return unsupported("platform-provided add-on is disabled")
    if not edges:
        return unsupported("platform-provided add-on has no trusted dependency metadata")
    if addon_type not in declared_points:
        return unsupported("platform-provided add-on type is not declared by its trusted metadata")
    # The observed version is evidence, so it must be parseable and must already
    # meet every minimum that the build's incoming edges declare.
    if not _strict_version_satisfies(version, ""):
        return unsupported("platform-provided add-on version is unverifiable")
    if any(not _strict_version_satisfies(version, minimum) for minimum in incoming_minima):
        return unsupported("platform-provided add-on does not satisfy a required minimum")
    return AddonCaptureNode(
        addon_id=addon_id,
        version=version,
        addon_type=addon_type,
        desired_enabled=True,
        provenance=ProvenanceStatus.UNKNOWN,
        dependency_edges=_combine_edges(edges),
        optional=optional,
        status=CaptureStatus.PLATFORM_PROVIDED,
        platform_provided=True,
    )


def capture_frozen_build(
    *,
    backend: InventoryBackend,
    store: ArtifactStore,
    root_addon_ids: Sequence[str],
    build_id: str,
    name: str,
    created_at: str,
    kodi_version: str = "",
    platform: str = "",
    configuration_packages: Sequence[str] = (),
    install_policies: Sequence["FrozenInstallPolicy"] = (),
) -> FrozenBuildCaptureResult:
    """Capture exact installed software for selected roots and dependencies."""
    listing = tuple(backend.get_installed_addons())
    installed = {}
    for raw in listing:
        addon_id = raw.get("addonid")
        if isinstance(addon_id, str) and addon_id not in installed:
            installed[addon_id] = dict(raw)

    edges_by_id: Dict[str, List[DependencyEdge]] = {}
    optional_by_id: Dict[str, bool] = {}
    system_min_versions: Dict[str, str] = {}
    metadata_errors = set()
    platform_ids = set()
    declared_points_by_id: Dict[str, Tuple[str, ...]] = {}
    visiting = set()
    visited = set()
    errors: List[str] = []

    def walk(addon_id: str, optional: bool = False) -> None:
        optional_by_id[addon_id] = optional_by_id.get(addon_id, True) and optional
        if addon_id in visiting:
            errors.append(f"dependency cycle at {addon_id}")
            return
        if addon_id in visited:
            return
        visited.add(addon_id)
        if _is_system_dependency(addon_id):
            return
        raw = installed.get(addon_id)
        if raw is None:
            return
        visiting.add(addon_id)
        metadata = backend.read_installed_metadata(addon_id, installed=listing)
        xml_bytes = None if metadata is None else metadata.xml_bytes
        if xml_bytes is None:
            # Required metadata absence blocks exactly like malformed metadata.
            # Dependency edges are never inferred from inventory RPC data.
            errors.append(f"{addon_id}: addon.xml unavailable")
            metadata_errors.add(addon_id)
        else:
            try:
                _check_addon_xml_identity(xml_bytes, addon_id, raw.get("version"))
                edges = _parse_dependency_edges(xml_bytes, addon_id)
                edges_by_id[addon_id] = list(edges)
                if metadata.origin is InstalledOrigin.APPLICATION:
                    declared_points_by_id[addon_id] = _declared_extension_points(xml_bytes, addon_id)
                    platform_ids.add(addon_id)
                for edge in edges:
                    if _is_system_dependency(edge.addon_id):
                        current = system_min_versions.get(edge.addon_id, "")
                        if not current or edge.min_version > current:
                            system_min_versions[edge.addon_id] = edge.min_version
                    walk(edge.addon_id, edge.optional)
            except CaptureError as exc:
                errors.append(str(exc))
                metadata_errors.add(addon_id)
        visiting.remove(addon_id)

    for root in sorted(set(root_addon_ids)):
        walk(root, False)
    for root in sorted(set(root_addon_ids)):
        if root in platform_ids:
            # Trusted application add-ons are dependencies, never ordinary managed roots (D-028).
            errors.append(f"{root}: platform-provided add-on cannot be an ordinary managed root")

    incoming_minima: Dict[str, List[str]] = {}
    for parent_edges in edges_by_id.values():
        for edge in parent_edges:
            if edge.min_version:
                incoming_minima.setdefault(edge.addon_id, []).append(edge.min_version)

    nodes: List[AddonCaptureNode] = []
    for addon_id in sorted(visited):
        if _is_system_dependency(addon_id):
            raw = installed.get(addon_id, {})
            nodes.append(
                AddonCaptureNode(
                    addon_id=addon_id,
                    version=str(raw.get("version", "")) or system_min_versions.get(addon_id, ""),
                    addon_type=str(raw.get("type", "system")),
                    desired_enabled=True,
                    provenance=ProvenanceStatus.UNKNOWN,
                    system=True,
                    optional=optional_by_id.get(addon_id, False),
                    status=CaptureStatus.SYSTEM,
                )
            )
            continue
        raw = installed.get(addon_id)
        if raw is None:
            nodes.append(
                AddonCaptureNode(
                    addon_id=addon_id,
                    version="",
                    addon_type="",
                    desired_enabled=False,
                    provenance=ProvenanceStatus.UNKNOWN,
                    optional=optional_by_id.get(addon_id, False),
                    status=CaptureStatus.MISSING,
                    error="add-on is not installed",
                )
            )
            continue
        if addon_id in platform_ids and addon_id not in metadata_errors:
            # Platform-provided: no acquisition, provenance lookup, install or enablement.
            platform_node = _platform_node(
                addon_id, raw, optional_by_id.get(addon_id, False),
                edges_by_id.get(addon_id, ()), incoming_minima.get(addon_id, ()),
                declared_points_by_id.get(addon_id, ()),
            )
            nodes.append(platform_node)
            if platform_node.status is not CaptureStatus.PLATFORM_PROVIDED:
                errors.append(f"{addon_id}: {platform_node.error}")
            continue
        if addon_id in metadata_errors:
            nodes.append(
                AddonCaptureNode(
                    addon_id=addon_id,
                    version=str(raw.get("version", "")),
                    addon_type=str(raw.get("type", "")),
                    desired_enabled=bool(raw.get("enabled", False)),
                    provenance=ProvenanceStatus.UNKNOWN,
                    optional=optional_by_id.get(addon_id, False),
                    status=CaptureStatus.UNSUPPORTED,
                    error="addon.xml is unavailable or malformed",
                )
            )
            continue
        version = raw.get("version")
        addon_type = raw.get("type", "")
        enabled = raw.get("enabled", False)
        if not isinstance(version, str) or not version or not isinstance(enabled, bool):
            nodes.append(
                AddonCaptureNode(
                    addon_id, str(version or ""), str(addon_type or ""), bool(enabled),
                    ProvenanceStatus.UNKNOWN, optional=optional_by_id.get(addon_id, False),
                    status=CaptureStatus.UNSUPPORTED, error="installed metadata is malformed",
                )
            )
            continue
        provenance, detail = backend.get_provenance(addon_id)
        acquisition = ArtifactAcquirer(store, backend).acquire(addon_id, version)
        status = acquisition.status
        if status == CaptureStatus.COMPLETE:
            status = CaptureStatus.COMPLETE
        node = AddonCaptureNode(
            addon_id=addon_id,
            version=version,
            addon_type=str(addon_type),
            desired_enabled=enabled,
            provenance=provenance,
            provenance_detail=dict(detail),
            artifact=acquisition.metadata,
            dependency_edges=_combine_edges(edges_by_id.get(addon_id, ())),
            optional=optional_by_id.get(addon_id, False),
            status=status,
            error=acquisition.error,
        )
        nodes.append(node)
        if status != CaptureStatus.COMPLETE:
            errors.append(f"{addon_id}: {status.value}: {acquisition.error}")

    blocking = [
        node
        for node in nodes
        if not node.system
        and node.status not in (CaptureStatus.COMPLETE, CaptureStatus.PLATFORM_PROVIDED)
        and not node.is_absent_optional_dependency
    ]
    if blocking:
        overall = next(
            (node.status for node in blocking if node.status in set(CaptureStatus)),
            CaptureStatus.UNSUPPORTED,
        )
    elif errors:
        # Every capture error is blocking: metadata, identity, and closure
        # failures make the recorded graph unreproducible, so the manifest
        # itself must say so. Nothing downstream may launder it into COMPLETE.
        overall = CaptureStatus.UNSUPPORTED
    else:
        overall = CaptureStatus.COMPLETE
    source = dict(backend.get_source_metadata())
    if not kodi_version:
        kodi_version = source.pop("kodi_version", "")
    manifest = FrozenBuildManifest(
        # Schema 2 is emitted only for platform-provided meaning, so every
        # managed-only capture keeps its schema 1 bytes and fingerprint.
        schema_version=2 if any(node.platform_provided for node in nodes) else 1,
        build_id=build_id,
        name=name,
        created_at=created_at,
        kodi_version=kodi_version,
        platform=platform,
        capture_status=overall,
        addons=tuple(nodes),
        configuration_packages=tuple(sorted(set(configuration_packages))),
        source_metadata=source,
    )
    from resources.lib.frozen_resolution import summarize_frozen_recoverability

    recoverability = summarize_frozen_recoverability(manifest, store, install_policies)
    return FrozenBuildCaptureResult(
        manifest,
        tuple(sorted(set(errors))),
        recoverability,
    )
