"""Explicit pre-Apply repository acquisition; no Kodi or lifecycle mutation.

PreparedRepositoryResolution is an internal, serializable input, never a completed
install outcome or an approval token. Consumers reread source, policy and packages.
Only content addressed ArtifactStore objects are persisted during preparation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import io
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from resources.lib.artifacts import validate_addon_zip
from resources.lib.build_identity import check_frozen_identity
from resources.lib.build_library import LibraryInstallTarget
from resources.lib.build_manager import fingerprint_resolved_build
from resources.lib.frozen_resolution import (
    InstallResolution, InstallResolutionRecord, ResolutionState,
    _canonical_digest, _trusted_repository_id, effective_policy, install_plan_fingerprint,
)
from resources.lib.repository import validate_repository_zip, _download_artifact, _validate_url_policy
from resources.lib.resolver import resolve_manifest

_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~:-]{0,63}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
INDEX_LIMIT = 10 * 1024 * 1024
PACKAGE_LIMIT = 100 * 1024 * 1024


class PreparationCode(str, Enum):
    READY = "ready"
    TARGET_INVALID = "target_invalid"
    REPOSITORY_UNAVAILABLE = "repository_unavailable"
    METADATA_UNSUPPORTED = "metadata_unsupported"
    NETWORK_FAILED = "network_failed"
    INDEX_INVALID = "index_invalid"
    ADDON_UNAVAILABLE = "addon_unavailable"
    VERSION_INVALID = "version_invalid"
    PACKAGE_INVALID = "package_invalid"
    INCOMPATIBLE = "incompatible"
    IMPORT_FAILED = "import_failed"


class PreparationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, repr=False)
class PreparedRepositoryResolution:
    source_identity: str
    device_profile_id: str
    build_id: str
    source_software_fingerprint: str
    install_plan_fingerprint: str
    build_fingerprint: str
    records: tuple[InstallResolutionRecord, ...]

    def __post_init__(self):
        for value in (self.source_identity, self.source_software_fingerprint,
                      self.install_plan_fingerprint, self.build_fingerprint):
            if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                raise PreparationError(PreparationCode.TARGET_INVALID)
        for value in (self.device_profile_id, self.build_id):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value):
                raise PreparationError(PreparationCode.TARGET_INVALID)
        if (not isinstance(self.records, tuple) or not self.records
                or len(self.records) > 4096
                or any(not isinstance(r, InstallResolutionRecord)
                       or r.resolution is not InstallResolution.REPOSITORY_CURRENT
                       or r.state is not ResolutionState.RESOLVED
                       or not _VERSION.fullmatch(r.resolved_version)
                       or not _VERSION.fullmatch(r.captured_version)
                       or len(r.repository_id) > 100 for r in self.records)
                or len({r.addon_id for r in self.records}) != len(self.records)):
            raise PreparationError(PreparationCode.TARGET_INVALID)

    def __repr__(self):
        return "PreparedRepositoryResolution(<bound packages>)"

    def to_dict(self):
        return {"schema_version": 1, "source_identity": self.source_identity,
                "device_profile_id": self.device_profile_id, "build_id": self.build_id,
                "source_software_fingerprint": self.source_software_fingerprint,
                "install_plan_fingerprint": self.install_plan_fingerprint,
                "build_fingerprint": self.build_fingerprint,
                "records": [r.to_dict() for r in self.records]}

    @classmethod
    def from_dict(cls, value):
        fields = {"source_identity", "device_profile_id", "build_id", "source_software_fingerprint",
                  "install_plan_fingerprint", "build_fingerprint", "records"}
        try:
            if (not isinstance(value, dict) or set(value) != fields | {"schema_version"}
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1
                    or not isinstance(value["records"], list)):
                raise ValueError
            return cls(**{k: value[k] for k in fields - {"records"}},
                       records=tuple(InstallResolutionRecord.from_dict(r) for r in value["records"]))
        except Exception as exc:
            raise PreparationError(PreparationCode.TARGET_INVALID) from exc


@dataclass(frozen=True)
class PreparationResult:
    code: PreparationCode
    prepared: PreparedRepositoryResolution | None = None

    def __post_init__(self):
        if (not isinstance(self.code, PreparationCode)
                or (self.code is PreparationCode.READY) != isinstance(self.prepared, PreparedRepositoryResolution)):
            raise ValueError("invalid preparation result")

    def to_safe_dict(self):
        return {"code": self.code.value, "prepared": self.prepared is not None}


def _binding(source, profile, desired, frozen, loader):
    check_frozen_identity(desired.build.id, frozen)
    effective = loader.resolve(desired.config) if desired.config is not None else None
    return dict(source_identity=_canonical_digest({"root": source.root, "entry_id": source.entry_id}),
                device_profile_id=profile, build_id=desired.build.id,
                source_software_fingerprint=frozen.fingerprint(),
                install_plan_fingerprint=install_plan_fingerprint(frozen, desired.frozen_install_policies),
                build_fingerprint=_canonical_digest(fingerprint_resolved_build(desired, effective)))


def bind_prepared(prepared, source, profile, desired, frozen, loader, store):
    """Exact identity/artifact binding, read only. Dependencies are reread by Plan/install."""
    try:
        checked = PreparedRepositoryResolution.from_dict(prepared.to_dict())
        expected = _binding(source, profile, desired, frozen, loader)
        if any(getattr(checked, k) != v for k, v in expected.items()):
            raise ValueError
        nodes = {n.addon_id: n for n in frozen.addons}
        policies = {p.addon_id: p for p in desired.frozen_install_policies}
        for record in checked.records:
            node = nodes[record.addon_id]
            policy = effective_policy(record.addon_id, policies)
            if (node.system or node.is_absent_optional_dependency
                    or node.version != record.captured_version
                    or node.desired_enabled is not record.desired_enabled
                    or not policy.repository_fallback_allowed
                    or record.repository_id != policy.repository_id
                    or _trusted_repository_id(policy, nodes, store) != record.repository_id):
                raise ValueError
            metadata = store.get_metadata(record.artifact_sha256)
            data = store.read_bytes(record.artifact_sha256)
            if (metadata.addon_id != record.addon_id or metadata.version != record.resolved_version
                    or metadata.sha256 != record.artifact_sha256 or metadata.size != record.artifact_size
                    or len(data) != record.artifact_size):
                raise ValueError
            validate_addon_zip(data, expected_addon_id=record.addon_id, expected_version=record.resolved_version)
        return checked.records
    except Exception as exc:
        raise PreparationError(PreparationCode.TARGET_INVALID) from exc


def _xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError
    return ET.fromstring(data)


def _fetch_package(repository_data, repository_id, addon_id, download):
    """Single captured repository authority; unsupported/ambiguous layouts fail closed."""
    try:
        validate_repository_zip(repository_data, expected_addon_id=repository_id)
        with zipfile.ZipFile(io.BytesIO(repository_data)) as archive:
            root = _xml(archive.read(repository_id + "/addon.xml"))
        dirs = root.findall("./extension[@point='xbmc.addon.repository']/dir")
        if len(dirs) != 1 or dirs[0].attrib:
            raise ValueError
        info = dirs[0].findall("info")
        datadir = dirs[0].findall("datadir")
        if (len(info) != 1 or len(datadir) != 1 or info[0].attrib
                or datadir[0].attrib != {"zip": "true"}):
            raise ValueError
        info_url = (info[0].text or "").strip()
        data_url = (datadir[0].text or "").strip()
        for url in (info_url, data_url):
            _validate_url_policy(url)
            if urllib.parse.urlsplit(url).fragment:
                raise ValueError
        if urllib.parse.urlsplit(data_url).query:
            raise ValueError
    except Exception as exc:
        raise PreparationError(PreparationCode.METADATA_UNSUPPORTED) from exc
    try:
        index = download(info_url, max_bytes=INDEX_LIMIT, timeout=30.0)
        if not isinstance(index, bytes) or len(index) > INDEX_LIMIT:
            raise ValueError
    except Exception as exc:
        raise PreparationError(PreparationCode.NETWORK_FAILED) from exc
    try:
        index_root = _xml(index)
        if index_root.tag != "addons":
            raise ValueError
        matches = [a for a in index_root.findall("addon") if a.get("id") == addon_id]
    except Exception as exc:
        raise PreparationError(PreparationCode.INDEX_INVALID) from exc
    if not matches:
        raise PreparationError(PreparationCode.ADDON_UNAVAILABLE)
    if len(matches) != 1:
        raise PreparationError(PreparationCode.INDEX_INVALID)
    version = matches[0].get("version", "")
    if not _VERSION.fullmatch(version):
        raise PreparationError(PreparationCode.VERSION_INVALID)
    # Quote components so a version can never change the path/URL authority.
    version_path = urllib.parse.quote(version, safe="")
    package_url = data_url.rstrip("/") + f"/{addon_id}/{version_path}/{addon_id}-{version_path}.zip"
    try:
        _validate_url_policy(package_url)
        data = download(package_url, max_bytes=PACKAGE_LIMIT, timeout=30.0)
        if not isinstance(data, bytes) or len(data) > PACKAGE_LIMIT:
            raise ValueError
    except Exception as exc:
        raise PreparationError(PreparationCode.NETWORK_FAILED) from exc
    try:
        metadata = validate_addon_zip(data, expected_addon_id=addon_id, expected_version=version)
        return data, metadata
    except Exception as exc:
        raise PreparationError(PreparationCode.PACKAGE_INVALID) from exc


class RepositoryPreparationService:
    """Backend seam: prepare(target) -> result; attach result to a NEW PlanTarget.

    The injected downloader must obey the bounded/redirect-safe download contract.
    Production uses the established repository downloader. No runtime owner is used.
    """
    def __init__(self, artifact_store, *, download=_download_artifact):
        self.store = artifact_store
        self.download = download

    def prepare(self, target):
        from resources.lib.plan_model import DecisionChoice
        from resources.lib.frozen_install import (
            validate_frozen_install_plan, _repository_package_required_dependencies,
            FrozenInstallCoordinator,
        )
        from resources.lib.addons import RepositoryPackage
        try:
            install_target = LibraryInstallTarget.from_plan_target(target)
            public, frozen, loader = install_target.load()
            desired = resolve_manifest(public, target.device_profile_id)
            binding = _binding(target.library_source, target.device_profile_id, desired, frozen, loader)
            if target.install_resolution is not None or target.prepared_resolution is not None:
                raise ValueError
            choices = dict(target.choices)
            requested = sorted(a for a, c in choices.items() if c is DecisionChoice.INSTALL_CURRENT)
            skipped = frozenset(a for a, c in choices.items() if c is DecisionChoice.SKIP)
            if not requested or any(c is DecisionChoice.CANCEL for c in choices.values()):
                raise ValueError
            plan = validate_frozen_install_plan(frozen, self.store, desired.frozen_install_policies,
                                               skipped=tuple(skipped))
            rows = {r.addon_id: r for r in plan.summary.addons}
            if set(choices) - set(rows):
                raise ValueError
            nodes = {n.addon_id: n for n in frozen.addons}
            policies = {p.addon_id: p for p in desired.frozen_install_policies}
        except Exception:
            return PreparationResult(PreparationCode.TARGET_INVALID)
        try:
            records, packages = {}, {}
            for aid in requested:
                row = rows[aid]
                policy = effective_policy(aid, policies)
                repository_id = _trusted_repository_id(policy, nodes, self.store)
                if not row.fallback_eligible or row.exact_artifact_available or not repository_id:
                    raise PreparationError(PreparationCode.REPOSITORY_UNAVAILABLE)
                repository_data = self.store.read_bytes(nodes[repository_id].artifact.sha256)
                data, metadata = _fetch_package(repository_data, repository_id, aid, self.download)
                records[aid] = InstallResolutionRecord(
                    aid, nodes[aid].version, InstallResolution.REPOSITORY_CURRENT, ResolutionState.RESOLVED,
                    nodes[aid].desired_enabled, repository_id, metadata.version, metadata.sha256, metadata.size)
                packages[aid] = RepositoryPackage(aid, repository_id, metadata.version, data)
            try:
                extra = {a: _repository_package_required_dependencies(p, plan, records, skipped)
                         for a, p in packages.items()}
                resolved_plan = validate_frozen_install_plan(
                    frozen, self.store, desired.frozen_install_policies,
                    skipped=tuple(skipped), extra_dependencies=extra)
                if FrozenInstallCoordinator._activation_hold_ids(resolved_plan, desired):
                    raise ValueError
                config = desired.config
                if config is not None:
                    from resources.lib.private_overlay import validate_private_overlay_resolution_compatibility
                    validate_private_overlay_resolution_compatibility(
                        {a: r.resolved_version for a, r in records.items()},
                        config.private_settings, config.structured_private_resources)
            except Exception as exc:
                raise PreparationError(PreparationCode.INCOMPATIBLE) from exc
            try:
                for aid, package in packages.items():
                    self.store.import_zip(package.zip_bytes, expected_addon_id=aid,
                                          expected_version=package.version,
                                          source="repository:" + package.repository_id)
            except Exception as exc:
                raise PreparationError(PreparationCode.IMPORT_FAILED) from exc
            prepared = PreparedRepositoryResolution(**binding, records=tuple(records[a] for a in requested))
            # Source and policy must still match after network I/O/import.
            public, frozen, loader = install_target.load()
            desired = resolve_manifest(public, target.device_profile_id)
            bind_prepared(prepared, target.library_source, target.device_profile_id,
                          desired, frozen, loader, self.store)
            return PreparationResult(PreparationCode.READY, prepared)
        except PreparationError as exc:
            return PreparationResult(exc.code)
        except Exception:
            return PreparationResult(PreparationCode.TARGET_INVALID)
