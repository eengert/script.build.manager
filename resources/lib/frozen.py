"""Frozen-build inventory and capture core (BM-021B).

This module creates immutable software snapshots; it does not install add-ons,
change Kodi settings, or read/write Kodi databases.  Acquisition is limited to
an existing artifact store, exact package-cache ZIPs, and an explicit optional
repository provider.  Installed-directory zipping is intentionally absent.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from resources.lib.artifacts import (
    ArtifactMetadata,
    ArtifactStore,
    ArtifactValidationError,
    validate_addon_zip,
)
from resources.lib.dependencies import _is_system_dependency


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


class ProvenanceStatus(str, Enum):
    VERIFIED_REPOSITORY = "verified_repository"
    REPOSITORY_EVIDENCE = "repository_evidence"
    MANUAL_OR_UNKNOWN = "manual_or_unknown"
    UNKNOWN = "unknown"


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

    @property
    def required_dependency_ids(self) -> Tuple[str, ...]:
        return tuple(edge.addon_id for edge in self.dependency_edges if not edge.optional)

    @property
    def optional_dependency_ids(self) -> Tuple[str, ...]:
        return tuple(edge.addon_id for edge in self.dependency_edges if edge.optional)

    def to_dict(self) -> dict:
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

    def software_graph(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "kodi_version": self.kodi_version,
            "platform": self.platform,
            "addons": [node.to_dict() for node in sorted(self.addons, key=lambda item: item.addon_id)],
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
            "addons": [node.to_dict() for node in sorted(self.addons, key=lambda item: item.addon_id)],
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
        if value["schema_version"] != 1:
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
        nodes = tuple(_node_from_dict(item) for item in addons)
        packages = value["configuration_packages"]
        if not isinstance(packages, list) or any(
            not isinstance(item, str) or not item for item in packages
        ):
            raise CaptureError("frozen manifest configuration packages are malformed")
        manifest = cls(
            schema_version=1,
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

    @property
    def complete(self) -> bool:
        return self.manifest.capture_status == CaptureStatus.COMPLETE


def _manifest_string(value: Mapping[str, object], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise CaptureError(f"frozen manifest {field} must be a non-empty string")
    return result


def _node_from_dict(value: object) -> AddonCaptureNode:
    if not isinstance(value, dict):
        raise CaptureError("frozen manifest add-on node must be an object")
    required = {
        "addon_id", "version", "addon_type", "desired_enabled", "provenance",
        "provenance_detail", "artifact_sha256", "artifact_size",
        "required_dependency_ids", "optional_dependency_ids", "dependency_edges",
        "system", "optional", "capture_status",
    }
    optional = {"artifact_filename", "error"}
    if set(value) - required - optional or not required.issubset(value):
        raise CaptureError("frozen manifest add-on node fields are not supported")
    addon_id = _manifest_string(value, "addon_id")
    version = _manifest_string(value, "version")
    addon_type = _manifest_string(value, "addon_type")
    if not isinstance(value["desired_enabled"], bool):
        raise CaptureError("frozen manifest desired_enabled must be boolean")
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
        status=CaptureStatus(value["capture_status"]),
        error=error,
    )


class InventoryBackend:
    """Read-only source interface for installed add-on capture."""

    def get_installed_addons(self) -> Sequence[Mapping[str, object]]:
        raise NotImplementedError

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        raise NotImplementedError

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
    ):
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

    def get_package_cache(self, addon_id: str, version: str) -> Sequence[Tuple[str, bytes]]:
        return self.package_cache.get((addon_id, version), ())

    def get_repository_artifact(self, addon_id: str, version: str) -> Optional[Tuple[str, bytes]]:
        return self.repository.get((addon_id, version))

    def get_provenance(self, addon_id: str) -> Tuple[ProvenanceStatus, Mapping[str, str]]:
        return self.provenance.get(addon_id, (ProvenanceStatus.UNKNOWN, {}))

    def get_source_metadata(self) -> Mapping[str, str]:
        return self.source_metadata


class KodiInventoryBackend(InventoryBackend):
    """Read-only Kodi JSON-RPC/filesystem adapter.

    ``rpc`` must return the JSON-RPC result object, as the project's disposable
    harness does.  Internal database origin evidence is accepted only through
    the optional read-only ``origin_reader`` callback.
    """

    def __init__(
        self,
        rpc: Callable[[str, dict], Mapping[str, object]],
        *,
        addons_dir: Path,
        package_cache_dir: Path,
        origin_reader: Optional[Callable[[str], Tuple[ProvenanceStatus, Mapping[str, str]]]] = None,
    ):
        self.rpc = rpc
        self.addons_dir = Path(addons_dir).resolve()
        self.package_cache_dir = Path(package_cache_dir).resolve()
        self.origin_reader = origin_reader

    def get_installed_addons(self) -> Sequence[Mapping[str, object]]:
        result = self.rpc(
            "Addons.GetAddons",
            {
                "installed": True,
                "properties": ["version", "path", "enabled", "installed", "broken", "dependencies"],
            },
        )
        addons = result.get("addons") if isinstance(result, Mapping) else None
        if not isinstance(addons, list):
            raise CaptureError("Kodi returned malformed installed add-on inventory")
        return tuple(item for item in addons if isinstance(item, Mapping))

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        details = next(
            (item for item in self.get_installed_addons() if item.get("addonid") == addon_id),
            None,
        )
        path_value = details.get("path") if details else None
        if isinstance(path_value, str) and path_value.startswith("special://home/addons/"):
            target = self.addons_dir / path_value.split("special://home/addons/", 1)[1] / "addon.xml"
        elif isinstance(path_value, str) and path_value:
            target = Path(path_value).resolve() / "addon.xml"
        else:
            target = self.addons_dir / addon_id / "addon.xml"
        try:
            target.relative_to(self.addons_dir)
            return target.read_bytes()
        except (OSError, ValueError):
            return None

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


def _combine_edges(edges: Iterable[DependencyEdge]) -> Tuple[DependencyEdge, ...]:
    grouped: Dict[Tuple[str, bool, str], set] = {}
    for edge in edges:
        grouped.setdefault((edge.addon_id, edge.optional, edge.min_version), set()).update(edge.required_by)
    return tuple(
        DependencyEdge(addon_id, min_version, optional, tuple(sorted(required_by)))
        for (addon_id, optional, min_version), required_by in sorted(grouped.items())
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
) -> FrozenBuildCaptureResult:
    """Capture exact installed software for selected roots and dependencies."""
    installed = {}
    for raw in backend.get_installed_addons():
        addon_id = raw.get("addonid")
        if isinstance(addon_id, str) and addon_id not in installed:
            installed[addon_id] = dict(raw)

    edges_by_id: Dict[str, List[DependencyEdge]] = {}
    optional_by_id: Dict[str, bool] = {}
    system_min_versions: Dict[str, str] = {}
    metadata_errors = set()
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
        xml_bytes = backend.read_addon_xml(addon_id)
        if xml_bytes is None:
            errors.append(f"{addon_id}: addon.xml unavailable")
        else:
            try:
                edges = _parse_dependency_edges(xml_bytes, addon_id)
                edges_by_id[addon_id] = list(edges)
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
        if status != CaptureStatus.COMPLETE and not node.optional:
            errors.append(f"{addon_id}: {status.value}: {acquisition.error}")

    blocking = [node for node in nodes if not node.system and not node.optional and node.status != CaptureStatus.COMPLETE]
    if blocking:
        overall = next(
            (node.status for node in blocking if node.status in set(CaptureStatus)),
            CaptureStatus.UNSUPPORTED,
        )
    else:
        overall = CaptureStatus.COMPLETE
    source = dict(backend.get_source_metadata())
    if not kodi_version:
        kodi_version = source.pop("kodi_version", "")
    manifest = FrozenBuildManifest(
        schema_version=1,
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
    return FrozenBuildCaptureResult(manifest, tuple(sorted(set(errors))))
