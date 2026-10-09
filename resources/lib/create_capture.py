"""Read-only, explicitly owned Create Build capture (BM-UI-003B).

Runtime dependencies are composed by trusted application code, never supplied
as paths in the UI request. Frozen capture may write ArtifactStore data;
resource adapters may use disposable scratch.
"""
from __future__ import annotations

import base64
import json
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Callable

from resources.lib.build_library import _validate_bundle, FILE_LIMIT, BUNDLE_LIMIT
from resources.lib.config import ConfigSettingType, ConfigTargetKind, ConfigAddonUnavailableError, validate_package_id
from resources.lib.frozen import capture_frozen_build, FrozenBuildManifest, CaptureStatus
from resources.lib.manifest import PrivateSettingDeclaration, SettingTargetKind, validate_manifest
from resources.lib.private_overlay import PrivateOverlay, PrivateOverlayEntry, validate_private_overlay
from resources.lib.private_resource import StructuredPrivateResourceDeclaration, PrivateResourceNotInitializedError
from resources.lib.resolver import resolve_manifest
from resources.lib.skin import canonical_skin_setting_key


class CreateRequestError(ValueError):
    """Safe request rejection, with no caller payload in its message."""


class CreateCaptureStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass(frozen=True)
class PublicSettingTarget:
    addon_id: str
    key: str
    setting_type: ConfigSettingType
    target_kind: SettingTargetKind = SettingTargetKind.ADDON


@dataclass(frozen=True)
class PublicCaptureSpecification:
    settings: tuple[PublicSettingTarget, ...] = ()
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreateBuildRequest:
    build_id: str
    build_version: str
    build_name: str
    platform_profile_id: str
    platform_label: str
    device_profile_id: str
    device_label: str
    root_addon_ids: tuple[str, ...]
    include_active_skin: bool
    public_capture: PublicCaptureSpecification
    config_package_id: str
    description: str = ""
    private_settings: tuple[PrivateSettingDeclaration, ...] = ()
    private_resources: tuple[StructuredPrivateResourceDeclaration, ...] = ()
    private_overlay_id: str = ""
    expected_active_skin: str = ""

    def __post_init__(self):
        try:
            _validate_request(self)
        except Exception:
            raise CreateRequestError("INVALID_CREATE_REQUEST") from None

    @property
    def captures_private(self):
        return bool(self.private_settings or self.private_resources)


@dataclass(frozen=True)
class CapturePreview:
    root_addon_ids: tuple[str, ...]
    include_active_skin: bool
    public_setting_count: int
    public_file_count: int
    private_requested: bool


def describe_capture(request: CreateBuildRequest) -> CapturePreview:
    return CapturePreview(request.root_addon_ids, request.include_active_skin,
                          len(request.public_capture.settings), len(request.public_capture.files),
                          request.captures_private)


@dataclass(frozen=True)
class PreparedPublicBundle:
    """Immutable canonical PUBLIC envelope; no private overlay reference.

    register() accepts files. registration_inputs() stages only public material
    in a new owned temporary directory and keeps it alive for that call.
    """
    canonical_json: str = field(repr=False)

    def __post_init__(self):
        try:
            bundle = json.loads(self.canonical_json)
            _validate_bundle(bundle)
            _validate_registration_sizes(bundle)
            object.__setattr__(self, "canonical_json", _canonical(bundle))
        except Exception:
            raise CreateRequestError("INVALID_PUBLIC_BUNDLE") from None

    def to_dict(self):
        return json.loads(self.canonical_json)

    @contextmanager
    def registration_inputs(self):
        with tempfile.TemporaryDirectory(prefix="bm-create-public-") as directory:
            root = Path(directory).resolve()
            bundle = self.to_dict()
            manifest = root / "manifest.json"
            frozen = root / "frozen.json"
            packages = root / "packages"
            packages.mkdir()
            manifest.write_text(_canonical(bundle["manifest"]), encoding="utf-8")
            frozen.write_text(_canonical(bundle["frozen"]), encoding="utf-8")
            for pid, material in bundle["packages"].items():
                package = packages / pid
                package.mkdir()
                (package / "package.json").write_text(_canonical(material["descriptor"]), encoding="utf-8")
                for name, encoded in material["sources"].items():
                    target = package / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(base64.b64decode(encoded, validate=True))
            yield str(manifest), str(frozen), str(packages)


@dataclass(frozen=True)
class CreateBuildResult:
    status: CreateCaptureStatus
    build_name: str
    build_version: str
    managed_root_count: int
    addon_count: int
    skin_included: bool
    public_setting_count: int
    public_file_count: int
    private_setting_count: int
    private_resource_count: int
    exact_artifact_count: int = 0
    missing_artifact_count: int = 0
    gaps: tuple[str, ...] = ()
    artifact_gaps: tuple[tuple[str, str], ...] = ()
    public_bundle: PreparedPublicBundle | None = field(default=None, repr=False)
    private_overlay: PrivateOverlay | None = field(default=None, repr=False)

    def safe_dict(self):
        return {key: (value.value if isinstance(value, Enum) else value)
                for key, value in vars(self).items()
                if key not in {"public_bundle", "private_overlay"}}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate_registration_sizes(bundle):
    # Mirror the accepted registration transport limits; do not weaken them.
    for name in ("manifest", "frozen"):
        if len(_canonical(bundle[name]).encode("utf-8")) > FILE_LIMIT:
            raise ValueError()
    total = 0
    for material in bundle["packages"].values():
        size = len(_canonical(material["descriptor"]).encode("utf-8"))
        if size > FILE_LIMIT:
            raise ValueError()
        total += size
        for encoded in material["sources"].values():
            size = len(base64.b64decode(encoded, validate=True))
            if size > FILE_LIMIT:
                raise ValueError()
            total += size
    if total > BUNDLE_LIMIT // 2 or len(_canonical(bundle).encode("utf-8")) > BUNDLE_LIMIT:
        raise ValueError()


def _setting(target, value):
    return {"addon_id": target.addon_id, "key": target.key,
            "target": target.target_kind.value,
            "type": (target.setting_type.value if isinstance(target.setting_type, ConfigSettingType)
                     else target.setting_type), "value": value}


def _manifest(request, roots, skin=""):
    scopes = {}
    for target in request.public_capture.settings:
        scopes.setdefault((target.target_kind.value, target.addon_id), []).append(target.key)
    config = {
        "packages": [request.config_package_id],
        "managed_settings": [{"target": kind, "addon_id": owner, "keys": sorted(keys)}
                             for (kind, owner), keys in sorted(scopes.items())],
        "managed_files": sorted(request.public_capture.files),
        "private_settings": [{**{k: v for k, v in _setting(p, None).items() if k != "value"},
                              "required": p.required, "sensitivity": p.sensitivity}
                             for p in sorted(request.private_settings, key=lambda p: (p.target_kind.value, p.addon_id, p.key))],
        "structured_private_resources": [p.safe_dict() for p in sorted(request.private_resources, key=lambda p: p.resource_id)],
    }
    doc = {"schema_version": 1,
           "build": {"id": request.build_id, "version": request.build_version,
                     "name": request.build_name, "description": request.description},
           "addons": roots, "config": config,
           "platform_profiles": {request.platform_profile_id: {"label": request.platform_label}},
           "device_profiles": {request.device_profile_id: {"extends": request.platform_profile_id,
                                                          "label": request.device_label}}}
    if skin:
        doc["skin"] = {"addon_id": skin}
    if request.captures_private:
        doc["private_overlay"] = {"type": "local_file", "overlay_id": request.private_overlay_id,
                                  "required": any(p.required for p in (*request.private_settings, *request.private_resources))}
    return doc


def _validate_request(request):
    if not isinstance(request.public_capture, PublicCaptureSpecification):
        raise ValueError()
    if any(not isinstance(p, PrivateSettingDeclaration) for p in request.private_settings):
        raise ValueError()
    if any(not isinstance(p, StructuredPrivateResourceDeclaration)
           or not isinstance(p.fields, tuple) or not isinstance(p.supported_versions, tuple)
           for p in request.private_resources):
        raise ValueError()
    for value in (request.root_addon_ids, request.private_settings, request.private_resources,
                  request.public_capture.settings, request.public_capture.files):
        if not isinstance(value, tuple):
            raise ValueError()
    if request.expected_active_skin and (not request.include_active_skin or
            request.expected_active_skin not in request.root_addon_ids or
            not request.expected_active_skin.startswith('skin.')):
        raise ValueError()
    if type(request.include_active_skin) is not bool or not request.build_name:
        raise ValueError()
    for pid in (request.config_package_id, request.platform_profile_id, request.device_profile_id):
        validate_package_id(pid)
    if len(set(request.root_addon_ids)) != len(request.root_addon_ids):
        raise ValueError()
    if not request.root_addon_ids and not request.include_active_skin:
        raise ValueError()
    if request.captures_private != bool(request.private_overlay_id):
        raise ValueError()
    identities = [(t.target_kind.value, t.addon_id,
                   canonical_skin_setting_key(t.key) if t.target_kind.value == "skin" else t.key)
                  for t in (*request.public_capture.settings, *request.private_settings)]
    if len(set(identities)) != len(identities):
        raise ValueError()
    for t in request.public_capture.settings:
        if not isinstance(t, PublicSettingTarget) or not isinstance(t.setting_type, ConfigSettingType):
            raise ValueError()
    doc = _manifest(request, [{"addon_id": r, "state": "enabled"} for r in request.root_addon_ids])
    validated = validate_manifest(doc)
    if validated.config.managed_files != tuple(sorted(request.public_capture.files)):
        raise ValueError()
    # Validate public ownership and privacy restrictions BEFORE reading values.
    placeholders = {"string": "", "bool": False, "int": 0, "number": 0}
    descriptor = {"schema_version": 1, "id": request.config_package_id,
                  "settings": [_setting(t, placeholders[t.setting_type.value]) for t in request.public_capture.settings],
                  "files": [{"destination": p, "source": f"assets/{i}.bin"}
                            for i, p in enumerate(sorted(request.public_capture.files))]}
    frozen = FrozenBuildManifest(1, request.build_id, request.build_name, "preflight", "unknown", "unknown",
                                 CaptureStatus.COMPLETE, (), (request.config_package_id,))
    _validate_bundle({"schema_version": 1, "manifest": doc, "frozen": frozen.to_dict(),
                      "packages": {request.config_package_id: {"descriptor": descriptor,
                                  "sources": {f["source"]: "" for f in descriptor["files"]}}}})


class CreateBuildCaptureEngine:
    """Trusted composition of existing read-only adapters and ArtifactStore.

    inspect_state is KodiStateInspector.inspect (or an offline equivalent).
    InventoryBackend and ConfigurationBackend remain the existing contracts.
    No UI-supplied paths, registration, reconciliation, or mutation methods.
    """
    def __init__(self, *, inventory, artifact_store, configuration,
                 inspect_state: Callable, private_resources=None):
        self.inventory = inventory
        self.artifact_store = artifact_store
        self.configuration = configuration
        self.inspect_state = inspect_state
        self.private_resources = private_resources

    def capture(self, request: CreateBuildRequest, *, created_at: str) -> CreateBuildResult:
        if not isinstance(request, CreateBuildRequest):
            return CreateBuildResult(CreateCaptureStatus.FAILED, "", "", 0, 0, False, 0, 0, 0, 0,
                                     gaps=("INVALID_CREATE_REQUEST",))
        result = CreateBuildResult(CreateCaptureStatus.FAILED, request.build_name, request.build_version,
                                  len(request.root_addon_ids), 0, False, len(request.public_capture.settings),
                                  len(request.public_capture.files), len(request.private_settings), len(request.private_resources))
        stage = "INVALID_CREATE_REQUEST"
        try:
            _validate_request(request)
            stage = "RUNTIME_IDENTITY_UNAVAILABLE"
            state = self.inspect_state()
            if state.platform not in {"macos", "tvos", "android", "ios", "windows", "linux"} or not state.kodi_version:
                raise ValueError()
            skin = ""
            if request.include_active_skin:
                stage = "ACTIVE_SKIN_UNAVAILABLE"
                skin = state.active_skin
                if request.expected_active_skin and skin != request.expected_active_skin:
                    raise ValueError()
                if not isinstance(skin, str) or not skin.startswith("skin."):
                    raise ValueError()
                validate_manifest({"schema_version": 1, "build": {"id": request.build_id, "version": request.build_version},
                                   "skin": {"addon_id": skin}})
            roots = tuple(sorted(set(request.root_addon_ids) | ({skin} if skin else set())))
            result = replace(result, managed_root_count=len(roots), skin_included=bool(skin))
            stage = "SOFTWARE_CAPTURE_FAILED"
            captured = capture_frozen_build(backend=self.inventory, store=self.artifact_store,
                                           root_addon_ids=roots, build_id=request.build_id, name=request.build_name,
                                           created_at=created_at, kodi_version=state.kodi_version, platform=state.platform,
                                           configuration_packages=(request.config_package_id,))
            raw = captured.manifest
            exact = sum(n.artifact is not None for n in raw.addons)
            # A platform-provided requirement is verified on the target, so it is never a missing artifact.
            gaps = tuple((n.addon_id, n.status.value) for n in raw.addons
                         if not n.system and not n.platform_provided
                         and n.status is not CaptureStatus.COMPLETE and not n.is_absent_optional_dependency)
            # Only safe validated IDs may cross the result boundary.
            for node in raw.addons:
                validate_manifest({"schema_version": 1, "build": {"id": request.build_id, "version": request.build_version},
                                   "addons": [{"addon_id": node.addon_id, "state": "enabled"}]})
            result = replace(result, addon_count=len(raw.addons), exact_artifact_count=exact,
                             missing_artifact_count=len(gaps))
            if not captured.complete or captured.errors:
                return replace(result, status=CreateCaptureStatus.INCOMPLETE, gaps=("SOFTWARE_INCOMPLETE",), artifact_gaps=gaps)
            # Strip diagnostic maps, not software/acquisition truth; recompute canonical identity.
            frozen = replace(raw, source_metadata={}, addons=tuple(replace(n, provenance_detail={}, error="") for n in raw.addons))
            nodes = {n.addon_id: n for n in frozen.addons}
            stage = "CAPTURE_OWNER_UNAVAILABLE"
            for t in (*request.public_capture.settings, *request.private_settings):
                if t.addon_id not in nodes or nodes[t.addon_id].system or nodes[t.addon_id].platform_provided:
                    raise ValueError()
                if nodes[t.addon_id].is_absent_optional_dependency and (
                        isinstance(t, PublicSettingTarget) or t.required):
                    raise ValueError()
                if t.target_kind.value == "skin" and t.addon_id != skin:
                    raise ValueError()
            for declaration in request.private_resources:
                owner = nodes.get(declaration.owner_addon_id)
                if owner is not None and owner.is_absent_optional_dependency and not declaration.required:
                    continue
                if owner is None or owner.platform_provided or owner.version not in declaration.supported_versions:
                    raise ValueError()
            doc = _manifest(request, [{"addon_id": r, "state": "enabled" if nodes[r].desired_enabled else "disabled"} for r in roots], skin)
            stage = "PUBLIC_SETTING_UNREADABLE"
            settings = [_setting(t, self._read_setting(t)) for t in sorted(request.public_capture.settings,
                        key=lambda t: (t.target_kind.value, t.addon_id, t.key))]
            stage = "PUBLIC_FILE_UNREADABLE"
            files, sources = [], {}
            for index, destination in enumerate(sorted(request.public_capture.files)):
                data = self.configuration.read_file(destination)
                if type(data) is not bytes:
                    raise ValueError()
                source = f"assets/{index}.bin"
                files.append({"source": source, "destination": destination})
                sources[source] = base64.b64encode(data).decode("ascii")
            descriptor = {"schema_version": 1, "id": request.config_package_id, "settings": settings, "files": files}
            stage = "PUBLIC_BUNDLE_INVALID"
            bundle = {"schema_version": 1, "manifest": doc, "frozen": frozen.to_dict(),
                      "packages": {request.config_package_id: {"descriptor": descriptor, "sources": sources}}}
            manifest, checked_frozen, _ = _validate_bundle(bundle)
            resolve_manifest(manifest, request.device_profile_id)
            if checked_frozen.configuration_packages != (request.config_package_id,):
                raise ValueError()
            overlay = None
            if request.captures_private:
                stage = "PRIVATE_SETTING_UNREADABLE"
                entries = []
                for t in request.private_settings:
                    if nodes[t.addon_id].is_absent_optional_dependency and not t.required:
                        continue
                    try:
                        value = self._read_setting(t)
                    except ConfigAddonUnavailableError:
                        if t.required:
                            raise
                        continue
                    if value is None and not t.required:
                        continue
                    entries.append(PrivateOverlayEntry(t.addon_id, t.key, ConfigSettingType(t.setting_type), value,
                                                       ConfigTargetKind(t.target_kind.value)))
                stage = "PRIVATE_RESOURCE_UNREADABLE"
                resources = []
                for declaration in request.private_resources:
                    if nodes[declaration.owner_addon_id].is_absent_optional_dependency and not declaration.required:
                        continue
                    try:
                        resource, outcome = self.private_resources.capture(declaration)
                    except PrivateResourceNotInitializedError:
                        if declaration.required:
                            raise
                        continue
                    if outcome.outcome != "captured" or any(not item.verified for item in outcome.fields):
                        raise ValueError()
                    if resource.addon_version != nodes[declaration.owner_addon_id].version:
                        raise ValueError()
                    resources.append(resource)
                stage = "PRIVATE_OVERLAY_INVALID"
                overlay = PrivateOverlay(request.private_overlay_id, "sha256:" + frozen.fingerprint(), tuple(entries), resources=tuple(resources))
                overlay = PrivateOverlay.from_dict(overlay.to_dict())
                validate_private_overlay(overlay, request.private_settings,
                                         expected_source_software_fingerprint=frozen.fingerprint(),
                                         expected_overlay_id=request.private_overlay_id, resource_declarations=request.private_resources)
            return replace(result, status=CreateCaptureStatus.COMPLETE,
                           public_bundle=PreparedPublicBundle(_canonical(bundle)), private_overlay=overlay)
        except Exception:
            incomplete = stage in {"ACTIVE_SKIN_UNAVAILABLE", "PUBLIC_SETTING_UNREADABLE", "PUBLIC_FILE_UNREADABLE",
                                   "PRIVATE_SETTING_UNREADABLE", "PRIVATE_RESOURCE_UNREADABLE"}
            return replace(result, status=CreateCaptureStatus.INCOMPLETE if incomplete else CreateCaptureStatus.FAILED,
                           gaps=(stage,))

    def _read_setting(self, target):
        method = self.configuration.get_skin_setting if target.target_kind.value == "skin" else self.configuration.get_setting
        return method(target.addon_id, target.key, ConfigSettingType(target.setting_type))
