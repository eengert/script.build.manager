"""Trusted Create composition. Only execute() crosses the confirmed write boundary."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import re
import unicodedata
from pathlib import Path

from resources.lib.build_library import LibraryConflict
from resources.lib.config import ConfigPackageLoader
from resources.lib.create_capture import (CreateBuildRequest, CreateCaptureStatus,
    PublicCaptureSpecification, PublicSettingTarget)
from resources.lib.dependencies import _is_system_dependency
from resources.lib.manifest import SettingTargetKind
from resources.lib.private_overlay import PrivateOverlayConflict
from resources.lib.redlight_resource import redlight_declaration


class CreateValidationError(ValueError):
    def __init__(self, string_id=32720):
        self.string_id = string_id
        super().__init__('CREATE_VALIDATION_FAILED')


def identity(label):
    if not isinstance(label, str) or not label.strip() or len(label) > 160 or any(ord(c) < 32 for c in label):
        raise CreateValidationError()
    clean = label.strip()
    ascii_name = unicodedata.normalize('NFKD', clean).encode('ascii', 'ignore').decode().lower()
    slug = re.sub('[^a-z0-9]+', '-', ascii_name).strip('-')[:32] or 'build'
    # A digest of the original label prevents punctuation, truncation and Unicode collisions.
    return slug + '-' + hashlib.sha256(clean.encode()).hexdigest()[:12]


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value) or len(value) > 24:
        raise CreateValidationError(32721)
    return tuple(map(int, value.split('.')))


@dataclass(frozen=True)
class CreateComponent:
    addon_id: str
    label: str
    version: str
    current_skin: bool = False


@dataclass
class CreateSession:
    components: tuple[CreateComponent, ...]
    platform: str
    active_skin: str
    name: str = ''
    version: str = '1.0.0'
    device_label: str = ''
    selected: tuple[str, ...] = ()
    include_private: bool = True

    def choose(self, indices):
        if indices is not None:
            if any(type(i) is not int or not 0 <= i < len(self.components) for i in indices):
                raise CreateValidationError()
            self.selected = tuple(self.components[i].addon_id for i in sorted(set(indices)))


@dataclass(frozen=True)
class CreatePreview:
    request: CreateBuildRequest = field(repr=False)
    excluded_labels: tuple[str, ...]
    private_enabled: bool

    @property
    def counts(self):
        r = self.request
        return (len(r.root_addon_ids), len(self.excluded_labels), len(r.public_capture.settings),
                len(r.public_capture.files), len(r.private_settings), len(r.private_resources))

    def safe_dict(self):
        r = self.request
        return {'build_name': r.build_name, 'version': r.build_version,
                'device_label': r.device_label, 'counts': self.counts,
                'skin_included': r.include_active_skin,
                'private_enabled': self.private_enabled,
                'excluded_labels': self.excluded_labels}


@dataclass(frozen=True)
class CreateTerminal:
    string_id: int
    addon_count: int = 0
    skin_included: bool = False
    private_included: bool = False
    def safe_dict(self):
        return dict(vars(self))


class TrustedCaptureCatalog:
    def __init__(self, loader=None):
        self.loader = loader or ConfigPackageLoader(str(Path(__file__).parents[1] / 'config' / 'packages'))

    def compose(self, selected, skin, private, versions):
        settings, files = [], []
        if skin == 'skin.arctic.fuse.3' and skin in selected:
            package = self.loader.load_package('af3-common')
            for target in package.settings:
                if target.addon_id != skin or target.target_kind.value != 'skin':
                    raise CreateValidationError()
                settings.append(PublicSettingTarget(target.addon_id, target.key, target.setting_type,
                                                    SettingTargetKind(target.target_kind.value)))
            files.extend(f.destination for f in package.files)
        resources = ()
        declaration = redlight_declaration()
        if private and declaration.owner_addon_id in selected and versions.get(declaration.owner_addon_id) in declaration.supported_versions:
            resources = (declaration,)
        return PublicCaptureSpecification(tuple(settings), tuple(files)), (), resources


class CreateBuildWorkflow:
    def __init__(self, *, inventory, inspect_state, library, engine_factory, private_store_factory,
                 catalog=None, clock=None):
        self.inventory, self.inspect_state, self.library = inventory, inspect_state, library
        self.engine_factory, self.private_store_factory = engine_factory, private_store_factory
        self.catalog = catalog or TrustedCaptureCatalog()
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def open(self, device_label):
        state = self.inspect_state()
        if state.platform not in {'macos', 'tvos', 'ios', 'android', 'linux', 'windows'}:
            raise CreateValidationError(32722)
        inventory = self.inventory.get_installed_addons()
        items = {}
        for raw in inventory:
            aid = raw.get('addonid', '')
            kind = raw.get('type', '')
            if not isinstance(aid, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*', aid):
                raise CreateValidationError()
            if aid == 'script.build.manager' or _is_system_dependency(aid):
                continue
            if aid != state.active_skin and (aid.startswith('script.module.') or kind in {
                    'xbmc.python.module', 'kodi.gameclient', 'kodi.inputstream', 'kodi.vfs',
                    'kodi.audiodecoder', 'kodi.audioencoder', 'kodi.binary.instance', 'xbmc.metadata.scraper',
                    'xbmc.addon.metadata', 'kodi.resource'} or aid.startswith('resource.')):
                continue
            label = raw.get('name')
            if not isinstance(label, str) or not label.strip() or len(label) > 160 or any(ord(c) < 32 for c in label):
                label = aid
            # Kodi markup must not be interpreted as UI instructions.
            label = re.sub(r'\[[^\]]*\]', '', label).strip() or aid
            if aid in items:
                raise CreateValidationError()
            items[aid] = CreateComponent(aid, label, raw.get('version', ''), aid == state.active_skin)
        if not isinstance(state.active_skin, str) or not state.active_skin.startswith('skin.') or state.active_skin not in items:
            raise CreateValidationError(32723)
        components = tuple(sorted(items.values(), key=lambda c: (c.label.casefold(), c.addon_id)))
        return CreateSession(components, state.platform, state.active_skin, device_label=device_label,
                             selected=tuple(c.addon_id for c in components))

    def suggest_version(self, name):
        bid = identity(name)
        entries = [e for e in self.library.list_builds() if e.build_id == bid]
        if any(e.display_name != name.strip() for e in entries):
            raise CreateValidationError(32724)
        versions = [version_tuple(e.build_version) for e in entries]
        if not versions:
            return '1.0.0'
        major, minor, patch = max(versions)
        return f'{major}.{minor}.{patch + 1}'

    def preview(self, session):
        bid, did = identity(session.name), identity(session.device_label)
        version_tuple(session.version)
        if not session.selected or len(set(session.selected)) != len(session.selected) or not set(session.selected) <= {c.addon_id for c in session.components}:
            raise CreateValidationError(32725)
        # Also detect an existing identity/name conflict before capture.
        self.suggest_version(session.name)
        skin = session.active_skin if session.active_skin in session.selected else ''
        spec, private, resources = self.catalog.compose(session.selected, skin, session.include_private,
                                                       {c.addon_id: c.version for c in session.components})
        overlay_id = ''
        if private or resources:
            overlay_id = 'private-' + hashlib.sha256((bid + ':' + session.version).encode()).hexdigest()[:48]
        request = CreateBuildRequest(bid, session.version, session.name.strip(), session.platform,
            session.platform, did, session.device_label.strip(), tuple(sorted(session.selected)), bool(skin),
            spec, 'captured-public', expected_active_skin=skin, private_settings=private, private_resources=resources,
            private_overlay_id=overlay_id)
        return CreatePreview(request, tuple(c.label for c in session.components if c.addon_id not in session.selected), session.include_private)

    def execute(self, preview):
        """Called only after native confirmation; preserve the one previewed request.

        Private lock spans register/rollback so another Create cannot adopt a new
        overlay before an ordinary failed registration removes it. A crash may
        leave an unregistered private orphan; it never publishes the wrong data.
        """
        request = preview.request
        try:
            result = self.engine_factory().capture(request, created_at=self.clock())
        except Exception:
            return CreateTerminal(32732)
        if result.status is not CreateCaptureStatus.COMPLETE:
            gaps = set(result.gaps)
            category = 32723 if 'ACTIVE_SKIN_UNAVAILABLE' in gaps else 32730 if 'SOFTWARE_INCOMPLETE' in gaps else 32731 if gaps & {
                'PUBLIC_SETTING_UNREADABLE', 'PUBLIC_FILE_UNREADABLE', 'PRIVATE_SETTING_UNREADABLE',
                'PRIVATE_RESOURCE_UNREADABLE'} else 32732
            return CreateTerminal(category)
        if result.public_bundle is None or bool(result.private_overlay) != request.captures_private:
            return CreateTerminal(32732)
        def register():
            with result.public_bundle.registration_inputs() as inputs:
                return self.library.register(*inputs)
        try:
            if result.private_overlay is None:
                entry = register()
            else:
                overlay = result.private_overlay
                if overlay.overlay_id != request.private_overlay_id:
                    return CreateTerminal(32732)
                with self.private_store_factory().create_commit() as commit:
                    created = commit.ensure_exact(overlay)
                    try:
                        entry = register()
                    except Exception:
                        # register may raise after its registry publication (e.g.
                        # directory fsync or final read). Never remove private data
                        # until authoritative readable state proves no such build.
                        recovered = self.library.registered_bundle(result.public_bundle.to_dict())
                        if recovered is not None:
                            entry = recovered
                        else:
                            if created:
                                commit.remove_if_exact(overlay.overlay_id, overlay.fingerprint)
                            raise
        except (LibraryConflict, PrivateOverlayConflict):
            return CreateTerminal(32733)
        except Exception:
            return CreateTerminal(32734)
        try:
            self.library.select(entry.entry_id, request.device_profile_id)
        except Exception:
            return CreateTerminal(32735, result.addon_count, result.skin_included, bool(result.private_overlay))
        return CreateTerminal(32736, result.addon_count, result.skin_included, bool(result.private_overlay))


def runtime_create_workflow():
    """Lazy runtime composition; no host fallback, no ArtifactStore before confirmation."""
    import json
    import xbmc
    import xbmcvfs
    from resources.lib.inspector import KodiStateInspector
    from resources.lib.frozen import KodiInventoryBackend
    from resources.lib.build_library import default_build_library
    from resources.lib.artifacts import ArtifactStore
    from resources.lib.config import KodiRuntimeConfigurationBackend
    from resources.lib.create_capture import CreateBuildCaptureEngine
    from resources.lib.private_overlay import PrivateOverlayStore
    from resources.lib.private_resource import StructuredPrivateResourceManager
    from resources.lib.redlight_resource import RedLightSettingsAdapter
    def rpc(method, params):
        response = json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
        if 'error' in response:
            raise CreateValidationError()
        return response['result']
    def profile():
        import os
        path = xbmcvfs.translatePath('special://profile/')
        if not isinstance(path, str) or not os.path.isabs(path):
            raise CreateValidationError()
        return Path(path)
    inventory = KodiInventoryBackend(rpc, addons_dir=Path(xbmcvfs.translatePath('special://home/addons')),
        package_cache_dir=Path(xbmcvfs.translatePath('special://home/addons/packages')))
    inspector = KodiStateInspector()
    def engine():
        resources = StructuredPrivateResourceManager()
        resources.register(RedLightSettingsAdapter(profile()))
        return CreateBuildCaptureEngine(inventory=inventory,
            artifact_store=ArtifactStore(profile() / 'addon_data' / 'script.build.manager' / 'frozen-artifacts'),
            configuration=KodiRuntimeConfigurationBackend(), inspect_state=inspector.inspect, private_resources=resources)
    return CreateBuildWorkflow(inventory=inventory, inspect_state=inspector.inspect,
        library=default_build_library(), engine_factory=engine, private_store_factory=lambda: PrivateOverlayStore(profile()))
