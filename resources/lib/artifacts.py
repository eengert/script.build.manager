"""Immutable, content-addressed Kodi add-on artifacts (BM-021B).

This module validates package bytes without executing them and stores validated
ZIPs under ``<root>/artifacts/<sha256>.zip``.  The digest is the identity;
filenames, repository URLs, and provenance are metadata only.

The store deliberately has no garbage collection or installation behavior.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


class ArtifactError(Exception):
    """Base class for artifact validation and storage errors."""


class ArtifactValidationError(ArtifactError):
    """The supplied bytes are not a safe, exact Kodi add-on package."""


class ArtifactStoreError(ArtifactError):
    """The artifact store could not publish or validate an artifact."""


_ADDON_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ArtifactMetadata:
    """Immutable identity and validation metadata for one ZIP artifact."""

    sha256: str
    size: int
    addon_id: str
    version: str
    filename: str
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "sha256": self.sha256,
            "size": self.size,
            "addon_id": self.addon_id,
            "version": self.version,
            "filename": self.filename,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ArtifactMetadata":
        if not isinstance(value, dict):
            raise ArtifactStoreError("artifact metadata must be an object")
        required = ("sha256", "size", "addon_id", "version", "filename")
        if any(key not in value for key in required):
            raise ArtifactStoreError("artifact metadata is missing required fields")
        sha256 = value["sha256"]
        size = value["size"]
        addon_id = value["addon_id"]
        version = value["version"]
        filename = value["filename"]
        source = value.get("source", "")
        if (
            not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256)
            or not isinstance(size, int) or isinstance(size, bool) or size < 0
            or not isinstance(addon_id, str) or not _ADDON_ID_RE.fullmatch(addon_id)
            or not isinstance(version, str) or not version
            or not isinstance(filename, str) or not filename
            or not isinstance(source, str)
        ):
            raise ArtifactStoreError("artifact metadata has invalid field types")
        return cls(sha256, size, addon_id, version, filename, source)


def _safe_member_name(name: str) -> Tuple[str, ...]:
    """Return normalized ZIP path components or raise on unsafe input."""
    if not name or "\\" in name:
        raise ArtifactValidationError("ZIP contains an invalid path")
    if name.startswith("/") or name.startswith("\\"):
        raise ArtifactValidationError("ZIP contains an absolute path")
    parts = tuple(part for part in name.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise ArtifactValidationError("ZIP contains path traversal")
    return parts


def validate_addon_zip(
    zip_bytes: bytes,
    *,
    expected_addon_id: str,
    expected_version: str,
    source: str = "",
) -> ArtifactMetadata:
    """Validate an exact Kodi add-on ZIP and return its computed metadata.

    Validation reads package members and parses ``addon.xml`` only.  Package
    contents are never imported or executed.
    """
    if not isinstance(zip_bytes, bytes) or not zip_bytes:
        raise ArtifactValidationError("artifact must be non-empty bytes")
    if not isinstance(expected_addon_id, str) or not _ADDON_ID_RE.fullmatch(expected_addon_id):
        raise ArtifactValidationError("expected add-on ID is invalid")
    if not isinstance(expected_version, str) or not expected_version:
        raise ArtifactValidationError("expected add-on version is required")

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArtifactValidationError("artifact is not a readable ZIP") from exc

    with archive:
        infos = archive.infolist()
        if not infos:
            raise ArtifactValidationError("artifact ZIP is empty")
        roots = set()
        normalized_names = set()
        for info in infos:
            parts = _safe_member_name(info.filename)
            roots.add(parts[0])
            normalized = "/".join(parts)
            if normalized in normalized_names:
                raise ArtifactValidationError("artifact contains duplicate paths")
            normalized_names.add(normalized)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                raise ArtifactValidationError("artifact contains a symbolic link")
        if len(roots) != 1:
            raise ArtifactValidationError(
                "artifact must contain exactly one top-level add-on directory"
            )
        addon_root = next(iter(roots))
        xml_name = f"{addon_root}/addon.xml"
        if xml_name not in normalized_names:
            raise ArtifactValidationError("artifact is missing addon.xml")
        try:
            xml_bytes = archive.read(xml_name)
            root = ET.fromstring(xml_bytes)
        except (KeyError, ET.ParseError, OSError) as exc:
            raise ArtifactValidationError("artifact addon.xml is invalid") from exc
        if root.tag.rsplit("}", 1)[-1] != "addon":
            raise ArtifactValidationError("artifact addon.xml has the wrong root")
        actual_id = root.attrib.get("id")
        actual_version = root.attrib.get("version")
        if actual_id != expected_addon_id:
            raise ArtifactValidationError("artifact addon.xml ID does not match")
        if actual_version != expected_version:
            raise ArtifactValidationError("artifact addon.xml version does not match")

    return ArtifactMetadata(
        sha256=hashlib.sha256(zip_bytes).hexdigest(),
        size=len(zip_bytes),
        addon_id=expected_addon_id,
        version=expected_version,
        filename=f"{expected_addon_id}-{expected_version}.zip",
        source=source,
    )


class ArtifactStore:
    """Write-once content-addressed storage for validated add-on ZIPs."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.artifacts_dir = self.root / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def artifact_path(self, sha256: str) -> Path:
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise ArtifactStoreError("invalid artifact SHA-256")
        return self.artifacts_dir / f"{sha256}.zip"

    def metadata_path(self, sha256: str) -> Path:
        self.artifact_path(sha256)
        return self.artifacts_dir / f"{sha256}.json"

    def import_zip(
        self,
        zip_bytes: bytes,
        *,
        expected_addon_id: str,
        expected_version: str,
        source: str = "",
    ) -> ArtifactMetadata:
        metadata = validate_addon_zip(
            zip_bytes,
            expected_addon_id=expected_addon_id,
            expected_version=expected_version,
            source=source,
        )
        destination = self.artifact_path(metadata.sha256)
        metadata_file = self.metadata_path(metadata.sha256)
        if destination.exists():
            try:
                existing = destination.read_bytes()
            except OSError as exc:
                raise ArtifactStoreError("cannot read existing artifact") from exc
            if existing != zip_bytes:
                raise ArtifactStoreError("existing artifact bytes do not match digest")
            self._verify_metadata_identity(metadata_file, metadata)
            return self._read_metadata(metadata_file)

        fd, temp_name = tempfile.mkstemp(
            prefix=f".{metadata.sha256}.", suffix=".tmp", dir=self.artifacts_dir
        )
        temp_path = Path(temp_name)
        published_by_us = False
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(zip_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_path, destination)
                published_by_us = True
            except FileExistsError:
                if destination.read_bytes() != zip_bytes:
                    raise ArtifactStoreError("existing artifact bytes do not match digest")
            os.unlink(temp_path)
            self._publish_metadata(metadata_file, metadata)
            self._fsync_directory()
            self._verify_readback(destination, metadata)
            return metadata
        except ArtifactError:
            if published_by_us:
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
                try:
                    metadata_file.unlink()
                except FileNotFoundError:
                    pass
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise
        except (OSError, ValueError) as exc:
            if published_by_us:
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
                try:
                    metadata_file.unlink()
                except FileNotFoundError:
                    pass
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise ArtifactStoreError("artifact publication failed") from exc

    def get_metadata(self, sha256: str) -> ArtifactMetadata:
        return self._read_metadata(self.metadata_path(sha256))

    def find(self, addon_id: str, version: str) -> Optional[ArtifactMetadata]:
        """Find a validated stored artifact for an exact ID/version pair."""
        for metadata_path in sorted(self.artifacts_dir.glob("*.json")):
            try:
                metadata = self._read_metadata(metadata_path)
            except ArtifactStoreError:
                continue
            if metadata.addon_id != addon_id or metadata.version != version:
                continue
            artifact_path = self.artifact_path(metadata.sha256)
            try:
                self._verify_readback(artifact_path, metadata)
            except (OSError, ArtifactStoreError):
                continue
            return metadata
        return None

    def read_bytes(self, sha256: str) -> bytes:
        path = self.artifact_path(sha256)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ArtifactStoreError("artifact is unavailable") from exc
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ArtifactStoreError("artifact read-back digest mismatch")
        return data

    def _publish_metadata(self, path: Path, metadata: ArtifactMetadata) -> None:
        encoded = json.dumps(metadata.to_dict(), sort_keys=True, separators=(",", ":"))
        if path.exists():
            self._verify_metadata_identity(path, metadata)
            return
        fd, temp_name = tempfile.mkstemp(prefix=f".{metadata.sha256}.", suffix=".json.tmp", dir=self.artifacts_dir)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_path, path)
            except FileExistsError:
                self._verify_metadata_identity(path, metadata)
            os.unlink(temp_path)
        except (OSError, ArtifactError) as exc:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactStoreError("artifact metadata publication failed") from exc

    @staticmethod
    def _read_metadata(path: Path) -> ArtifactMetadata:
        try:
            return ArtifactMetadata.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ArtifactStoreError) as exc:
            raise ArtifactStoreError("artifact metadata is unavailable or invalid") from exc

    def _verify_metadata(self, path: Path, expected: ArtifactMetadata) -> None:
        actual = self._read_metadata(path)
        if actual != expected:
            raise ArtifactStoreError("existing artifact metadata does not match")

    def _verify_metadata_identity(self, path: Path, expected: ArtifactMetadata) -> None:
        actual = self._read_metadata(path)
        if (
            actual.sha256 != expected.sha256
            or actual.size != expected.size
            or actual.addon_id != expected.addon_id
            or actual.version != expected.version
            or actual.filename != expected.filename
        ):
            raise ArtifactStoreError("existing artifact metadata does not match")

    @staticmethod
    def _verify_readback(path: Path, expected: ArtifactMetadata) -> None:
        data = path.read_bytes()
        if len(data) != expected.size or hashlib.sha256(data).hexdigest() != expected.sha256:
            raise ArtifactStoreError("artifact read-back verification failed")

    def _fsync_directory(self) -> None:
        try:
            fd = os.open(self.artifacts_dir, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
