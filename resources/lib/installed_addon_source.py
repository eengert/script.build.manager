"""Verified source paths for add-ons installed by a frozen Build Manager run.

The resolver accepts installation identity only. It always derives the source
path from Kodi's active ``special://home/addons`` root and a validated add-on
ID; public manifest data never supplies an executable path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Callable, Optional
import xml.etree.ElementTree as ET


_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
_MAX_ADDON_XML_BYTES = 1024 * 1024
_SOURCE_VERIFICATION_TOKEN = object()


class InstalledAddonSourceError(ValueError):
    """Safe, bounded failure to resolve one managed installed source."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ManagedAddonSourceIdentity:
    """Identity copied from a validated frozen resolution record."""

    addon_id: str
    version: str
    artifact_sha256: str
    artifact_size: int
    frozen_transaction_id: str
    manifest_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.addon_id, str) or not _ADDON_ID.fullmatch(self.addon_id):
            raise ValueError("managed source add-on ID is invalid")
        if not isinstance(self.version, str) or not self.version or len(self.version) > 128:
            raise ValueError("managed source version is invalid")
        if not isinstance(self.artifact_sha256, str) or not _SHA256.fullmatch(self.artifact_sha256):
            raise ValueError("managed source artifact digest is invalid")
        if isinstance(self.artifact_size, bool) or not isinstance(self.artifact_size, int) or self.artifact_size <= 0:
            raise ValueError("managed source artifact size is invalid")
        if not isinstance(self.frozen_transaction_id, str) or not _UUID.fullmatch(self.frozen_transaction_id):
            raise ValueError("managed source transaction identity is invalid")
        if not isinstance(self.manifest_fingerprint, str) or not _FINGERPRINT.fullmatch(self.manifest_fingerprint):
            raise ValueError("managed source manifest identity is invalid")


@dataclass(frozen=True, repr=False)
class VerifiedInstalledAddonSource:
    """Canonical Kodi add-on source tied to a frozen artifact record.

    ``artifact_sha256`` identifies the exact archive recorded by BM-022. It is
    deliberately not described as a hash of the installed directory.
    """

    addon_id: str
    version: str
    installed_root: Path
    addons_root: Path
    artifact_sha256: str
    artifact_size: int
    frozen_transaction_id: str
    manifest_fingerprint: str
    _verification_token: object = field(default=None, repr=False, compare=False)

    @property
    def verified(self) -> bool:
        return self._verification_token is _SOURCE_VERIFICATION_TOKEN

    def safe_dict(self) -> dict:
        return {
            "addon_id": self.addon_id,
            "version": self.version,
            "artifact_sha256": self.artifact_sha256,
            "artifact_size": self.artifact_size,
            "frozen_transaction_id": self.frozen_transaction_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "verified": self.verified,
        }

    def revalidate(self) -> "VerifiedInstalledAddonSource":
        """Repeat path and add-on metadata checks immediately before import."""
        if not self.verified:
            raise InstalledAddonSourceError(
                "INSTALLED_SOURCE_UNVERIFIED", "installed add-on source is not verified"
            )
        identity = ManagedAddonSourceIdentity(
            self.addon_id,
            self.version,
            self.artifact_sha256,
            self.artifact_size,
            self.frozen_transaction_id,
            self.manifest_fingerprint,
        )
        return _resolve_under_root(identity, self.addons_root)


def _resolve_under_root(
    identity: ManagedAddonSourceIdentity,
    addons_root: Path,
) -> VerifiedInstalledAddonSource:
    try:
        root_text = str(addons_root)
        if not root_text or "://" in root_text:
            raise ValueError("Kodi add-ons root must be a local path")
        root = Path(root_text).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise InstalledAddonSourceError(
            "KODI_ADDONS_ROOT_UNAVAILABLE", "Kodi add-ons root is unavailable"
        ) from exc
    if not root.is_dir():
        raise InstalledAddonSourceError(
            "KODI_ADDONS_ROOT_UNAVAILABLE", "Kodi add-ons root is unavailable"
        )

    expected_root = root / identity.addon_id
    try:
        installed_root = expected_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InstalledAddonSourceError(
            "INSTALLED_ADDON_SOURCE_MISSING", "managed installed add-on source is missing"
        ) from exc
    if (
        not expected_root.is_dir()
        or expected_root.is_symlink()
        or installed_root != expected_root
        or installed_root.parent != root
    ):
        raise InstalledAddonSourceError(
            "INSTALLED_ADDON_SOURCE_OUTSIDE_ROOT",
            "managed installed add-on source is outside Kodi's add-ons root",
        )

    addon_xml = installed_root / "addon.xml"
    try:
        if addon_xml.is_symlink() or addon_xml.resolve(strict=True).parent != installed_root:
            raise InstalledAddonSourceError(
                "INSTALLED_ADDON_XML_OUTSIDE_ROOT",
                "managed add-on metadata is outside its installed root",
            )
        if not addon_xml.is_file():
            raise InstalledAddonSourceError(
                "INSTALLED_ADDON_XML_INVALID", "managed add-on metadata is unavailable"
            )
        raw_xml = addon_xml.read_bytes()
        if len(raw_xml) > _MAX_ADDON_XML_BYTES:
            raise InstalledAddonSourceError(
                "INSTALLED_ADDON_XML_INVALID", "managed add-on metadata is too large"
            )
        metadata = ET.fromstring(raw_xml)
    except InstalledAddonSourceError:
        raise
    except (OSError, RuntimeError, ET.ParseError, ValueError) as exc:
        raise InstalledAddonSourceError(
            "INSTALLED_ADDON_XML_INVALID", "managed add-on metadata is invalid"
        ) from exc
    if metadata.tag != "addon" or metadata.get("id") != identity.addon_id:
        raise InstalledAddonSourceError(
            "INSTALLED_ADDON_ID_MISMATCH", "installed add-on ID does not match the frozen record"
        )
    if metadata.get("version") != identity.version:
        raise InstalledAddonSourceError(
            "INSTALLED_ADDON_VERSION_MISMATCH",
            "installed add-on version does not match the frozen record",
        )
    return VerifiedInstalledAddonSource(
        identity.addon_id,
        identity.version,
        installed_root,
        root,
        identity.artifact_sha256,
        identity.artifact_size,
        identity.frozen_transaction_id,
        identity.manifest_fingerprint,
        _SOURCE_VERIFICATION_TOKEN,
    )


class InstalledAddonSourceResolver:
    """Resolve a frozen identity below the active Kodi add-ons directory."""

    def __init__(self, addons_root_provider: Callable[[], str | Path]):
        self._addons_root_provider = addons_root_provider

    def resolve(
        self, identity: ManagedAddonSourceIdentity
    ) -> VerifiedInstalledAddonSource:
        if not isinstance(identity, ManagedAddonSourceIdentity):
            raise InstalledAddonSourceError(
                "INSTALLED_SOURCE_IDENTITY_INVALID", "managed source identity is invalid"
            )
        try:
            root = self._addons_root_provider()
        except Exception as exc:
            raise InstalledAddonSourceError(
                "KODI_ADDONS_ROOT_UNAVAILABLE", "Kodi add-ons root is unavailable"
            ) from exc
        return _resolve_under_root(identity, root)


class KodiInstalledAddonSourceResolver(InstalledAddonSourceResolver):
    """Runtime resolver deriving its root from Kodi VFS, never the manifest."""

    def __init__(self, path_translator: Optional[Callable[[str], str]] = None):
        def _addons_root() -> str:
            translate = path_translator
            if translate is None:
                import xbmcvfs
                translate = xbmcvfs.translatePath
            return translate("special://home/addons")

        super().__init__(_addons_root)


@dataclass(frozen=True, repr=False)
class PrivateResourceOwnerContext:
    """In-memory proof supplied by Build Manager to a lifecycle resource."""

    owner_addon_id: str
    expected_version: str
    registry_version: str
    owner_enabled: bool
    activation_held: bool
    installed_source: VerifiedInstalledAddonSource

    def matches(self, addon_id: str, version: str) -> bool:
        source = self.installed_source
        return bool(
            isinstance(source, VerifiedInstalledAddonSource)
            and source.verified
            and self.owner_addon_id == addon_id
            and self.expected_version == version
            and self.registry_version == version
            and self.owner_enabled is False
            and self.activation_held is True
            and source.addon_id == addon_id
            and source.version == version
        )
