"""Offline acceptance for the explicit Create capture boundary."""
import base64
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from resources.lib.artifacts import ArtifactStore
from resources.lib.build_library import BuildLibrary, _validate_bundle
from resources.lib.config import ConfigurationBackend, ConfigSettingType as T, ConfigBackendError
from resources.lib.create_capture import (CreateBuildRequest, CreateBuildCaptureEngine, CreateCaptureStatus as S,
    PublicCaptureSpecification as Spec, PublicSettingTarget as Target, CreateRequestError, describe_capture)
from resources.lib.frozen import InMemoryInventoryBackend, FrozenBuildManifest
from resources.lib.manifest import PrivateSettingDeclaration, SettingTargetKind as K
from resources.lib.private_resource import StructuredPrivateResourceManager
from resources.lib.redlight_resource import RedLightSettingsAdapter
from resources.lib.resolver import resolve_manifest
from tests.test_frozen import _addon, _xml, _zip

SECRET = 'PRIVATE_SENTINEL_NEVER_PUBLIC_792'
ROOT = 'plugin.demo'
DEP = 'script.module.demo'
SKIN = 'skin.demo'


class Configuration(ConfigurationBackend):
    def __init__(self):
        self.values = {(ROOT, 'quality'): 'high', (SKIN, 'background'): 'blue', (ROOT, 'privateid'): SECRET}
        self.files = {'userdata/keymaps/demo.xml': b'\x00<keymap/>\xff'}
        self.reads = []
        self.mutations = []

    def get_setting(self, owner, key, setting_type):
        self.reads.append(('addon', owner, key, setting_type))
        return self.values[(owner, key)]

    def get_skin_setting(self, owner, key, setting_type):
        self.reads.append(('skin', owner, key, setting_type))
        return self.values[(owner, key)]

    def read_file(self, destination):
        self.reads.append(('file', destination))
        return self.files.get(destination)

    def set_setting(self, *args):
        self.mutations.append('set_setting')
        raise AssertionError('mutation')

    def set_skin_setting(self, *args):
        self.mutations.append('set_skin_setting')
        raise AssertionError('mutation')

    def write_file(self, *args):
        self.mutations.append('write_file')
        raise AssertionError('mutation')


class CreateCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.store = ArtifactStore(self.base / 'artifacts')
        self.config = Configuration()
        self.inventory = InMemoryInventoryBackend(
            [_addon(ROOT), _addon(DEP), _addon(SKIN, addon_type='xbmc.gui.skin')],
            {ROOT: _xml(ROOT, imports=((DEP, '1.0.0', False),)), DEP: _xml(DEP), SKIN: _xml(SKIN)},
            package_cache={(a, '1.0.0'): ((a + '.zip', _zip(a)),) for a in (ROOT, DEP, SKIN)})
        self.state = SimpleNamespace(platform='macos', kodi_version='21.0', active_skin=SKIN)
        self.resources = StructuredPrivateResourceManager()
        self.engine = CreateBuildCaptureEngine(inventory=self.inventory, artifact_store=self.store,
            configuration=self.config, inspect_state=lambda: self.state, private_resources=self.resources)
        self.request = CreateBuildRequest('demo', '1.0.0', 'Demo', 'macos', 'Mac', 'desk', 'Desk',
                                         (ROOT,), False, Spec(), 'captured')

    def capture(self, **changes):
        return self.engine.capture(replace(self.request, **changes), created_at='2026-10-06T00:00:00Z')

    def bundle(self, result):
        self.assertEqual(result.status, S.COMPLETE, result)
        return result.public_bundle.to_dict()

    def test_minimal_exact_complete_and_preview(self):
        result = self.capture()
        raw = self.bundle(result)
        self.assertEqual(result.exact_artifact_count, 2)
        self.assertEqual(result.missing_artifact_count, 0)
        self.assertEqual(raw['manifest']['addons'], [{'addon_id': ROOT, 'state': 'enabled'}])
        self.assertEqual(describe_capture(self.request).root_addon_ids, (ROOT,))
        self.assertEqual(self.config.reads, [])

    def test_multiple_roots_dependency_not_promoted(self):
        raw = self.bundle(self.capture(root_addon_ids=(ROOT, SKIN)))
        self.assertEqual({n['addon_id'] for n in raw['frozen']['addons']}, {ROOT, DEP, SKIN})
        self.assertEqual({n['addon_id'] for n in raw['manifest']['addons']}, {ROOT, SKIN})

    def test_disabled_state_preserved(self):
        self.inventory.addons = tuple({**a, 'enabled': False} if a['addonid'] == ROOT else a for a in self.inventory.addons)
        raw = self.bundle(self.capture())
        self.assertEqual(raw['manifest']['addons'][0]['state'], 'disabled')
        self.assertFalse(next(n for n in raw['frozen']['addons'] if n['addon_id'] == ROOT)['desired_enabled'])

    def test_active_skin_included_and_resolved(self):
        result = self.capture(include_active_skin=True)
        raw = self.bundle(result)
        self.assertEqual(raw['manifest']['skin'], {'addon_id': SKIN})
        self.assertTrue(result.skin_included)
        manifest, frozen, _ = _validate_bundle(raw)
        self.assertEqual(resolve_manifest(manifest, 'desk').skin.addon_id, SKIN)
        self.assertIn(SKIN, [n.addon_id for n in frozen.addons])

    def test_skin_only_capture(self):
        self.bundle(self.capture(include_active_skin=True, root_addon_ids=()))

    def test_unavailable_active_skin(self):
        self.state.active_skin = ''
        result = self.capture(include_active_skin=True)
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertEqual(result.gaps, ('ACTIVE_SKIN_UNAVAILABLE',))
        self.assertIsNone(result.public_bundle)

    def test_skin_missing_inventory(self):
        self.state.active_skin = 'skin.missing'
        self.assertEqual(self.capture(include_active_skin=True).status, S.INCOMPLETE)

    def test_public_typed_addon_and_skin_settings(self):
        spec = Spec((Target(ROOT, 'quality', T.STRING), Target(SKIN, 'background', T.STRING, K.SKIN)))
        raw = self.bundle(self.capture(include_active_skin=True, public_capture=spec))
        manifest, _, loader = _validate_bundle(raw)
        settings = loader.resolve(resolve_manifest(manifest, 'desk').config).settings
        self.assertEqual({(s.addon_id, s.key, s.setting_type, s.value) for s in settings},
                         {(ROOT, 'quality', T.STRING, 'high'), (SKIN, 'background', T.STRING, 'blue')})
        self.assertEqual(len(self.config.reads), 2)

    def test_all_addon_value_types(self):
        for kind, value in ((T.STRING, 'high'), (T.BOOL, False), (T.INT, 23), (T.NUMBER, 1.25)):
            with self.subTest(kind=kind):
                self.config.values[(ROOT, 'quality')] = value
                raw = self.bundle(self.capture(public_capture=Spec((Target(ROOT, 'quality', kind),))))
                self.assertEqual(raw['packages']['captured']['descriptor']['settings'][0]['value'], value)

    def test_file_exact_and_package_ownership(self):
        spec = Spec((Target(ROOT, 'quality', T.STRING),), ('userdata/keymaps/demo.xml',))
        raw = self.bundle(self.capture(public_capture=spec))
        manifest, _, loader = _validate_bundle(raw)
        effective = loader.resolve(resolve_manifest(manifest, 'desk').config)
        self.assertEqual(effective.files[0].content, self.config.files[spec.files[0]])
        self.assertEqual(manifest.config.managed_files, spec.files)
        self.assertEqual(manifest.config.managed_settings[0].keys, ('quality',))
        self.assertEqual(self.config.reads, [('addon', ROOT, 'quality', T.STRING), ('file', spec.files[0])])

    def test_two_captures_do_not_contaminate(self):
        spec = Spec(files=('userdata/keymaps/demo.xml',))
        first = self.capture(public_capture=spec)
        self.config.files[spec.files[0]] = b'changed'
        second = self.capture(public_capture=spec)
        self.assertNotEqual(first.public_bundle.canonical_json, second.public_bundle.canonical_json)
        self.assertEqual(base64.b64decode(first.public_bundle.to_dict()['packages']['captured']['sources']['assets/0.bin']), b'\x00<keymap/>\xff')

    def test_unreadable_public_setting(self):
        self.config.values.clear()
        result = self.capture(public_capture=Spec((Target(ROOT, 'quality', T.STRING),)))
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertEqual(result.gaps, ('PUBLIC_SETTING_UNREADABLE',))

    def test_unreadable_public_file(self):
        result = self.capture(public_capture=Spec(files=('userdata/keymaps/missing.xml',)))
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertEqual(result.gaps, ('PUBLIC_FILE_UNREADABLE',))

    def test_private_value_separate_and_library_envelope_clean(self):
        private = (PrivateSettingDeclaration(ROOT, 'privateid', 'string'),)
        result = self.capture(private_settings=private, private_overlay_id='private-demo')
        raw = self.bundle(result)
        self.assertEqual(result.private_overlay.entries[0].value, SECRET)
        frozen = FrozenBuildManifest.from_dict(raw['frozen'])
        self.assertEqual(result.private_overlay.target_build_id, 'sha256:' + frozen.fingerprint())
        for public in (repr(result), str(result.safe_dict()), result.public_bundle.canonical_json,
                       repr(result.private_overlay), json.dumps(raw['manifest']), json.dumps(raw['frozen']), json.dumps(raw['packages'])):
            self.assertNotIn(SECRET, public)
        library = BuildLibrary(self.base / 'library')
        with result.public_bundle.registration_inputs() as inputs:
            entry = library.register(*inputs)
            self.assertTrue(all(Path(p).exists() for p in inputs))
        self.assertFalse(Path(inputs[0]).exists())
        self.assertIsNone(library.current_selection())
        self.assertNotIn(SECRET, (self.base / 'library' / 'builds' / (entry.entry_id + '.json')).read_text())

    def test_required_private_failure_with_no_partial_overlay(self):
        self.config.values.clear()
        result = self.capture(private_settings=(PrivateSettingDeclaration(ROOT, 'privateid', 'string'),), private_overlay_id='private-demo')
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertIsNone(result.private_overlay)
        self.assertIsNone(result.public_bundle)

    def test_optional_absent_private_setting(self):
        self.config.values[(ROOT, 'privateid')] = None
        result = self.capture(private_settings=(PrivateSettingDeclaration(ROOT, 'privateid', 'string', required=False),), private_overlay_id='private-demo')
        self.bundle(result)
        self.assertEqual(result.private_overlay.entries, ())

    def test_bad_private_type_fails_safely(self):
        self.config.values[(ROOT, 'privateid')] = object()
        result = self.capture(private_settings=(PrivateSettingDeclaration(ROOT, 'privateid', 'string'),), private_overlay_id='private-demo')
        self.assertEqual(result.status, S.FAILED)
        self.assertIsNone(result.private_overlay)

    def test_build_frozen_config_identity(self):
        raw = self.bundle(self.capture())
        manifest, frozen, _ = _validate_bundle(raw)
        self.assertEqual(manifest.build.id, frozen.build_id)
        self.assertEqual(tuple(raw['packages']), frozen.configuration_packages)
        self.assertEqual(manifest.config.packages, frozen.configuration_packages)
        self.assertEqual(resolve_manifest(manifest, 'desk').device_profile_id, 'desk')

    def test_missing_artifact_incomplete_no_substitute(self):
        self.inventory.package_cache = {}
        result = self.capture()
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertEqual(result.missing_artifact_count, 2)
        self.assertEqual({a for a, _ in result.artifact_gaps}, {ROOT, DEP})
        self.assertIsNone(result.public_bundle)
        self.assertEqual(list((self.base / 'artifacts').rglob('*.zip')), [])

    def test_diagnostic_provenance_is_removed_and_fingerprint_valid(self):
        from resources.lib.frozen import ProvenanceStatus
        self.inventory.provenance[ROOT] = (ProvenanceStatus.UNKNOWN, {'path': '/private/profile/' + SECRET})
        self.inventory.source_metadata = {'path': '/private/profile/' + SECRET}
        raw = self.bundle(self.capture())
        FrozenBuildManifest.from_dict(raw['frozen'])
        self.assertNotIn(SECRET, json.dumps(raw))
        self.assertEqual(raw['frozen']['source']['metadata'], {})

    def test_request_invalid_ids_and_duplicates(self):
        changes = ({'build_id': '../bad'}, {'build_version': 'bad'}, {'config_package_id': '../bad'},
                   {'platform_profile_id': '/bad'}, {'device_profile_id': '..'},
                   {'root_addon_ids': (ROOT, ROOT)}, {'root_addon_ids': ('../bad',)},
                   {'public_capture': Spec((Target(ROOT, 'quality', T.STRING),) * 2)},
                   {'public_capture': Spec(files=('userdata/keymaps/demo.xml',) * 2)},
                   {'public_capture': Spec(files=('../private',))},
                   {'private_settings': (PrivateSettingDeclaration(ROOT, 'privateid', 'string'),), 'private_overlay_id': '../bad'})
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(CreateRequestError, '^INVALID_CREATE_REQUEST$'):
                replace(self.request, **change)

    def test_public_private_overlap_rejected_before_reads(self):
        with self.assertRaises(CreateRequestError):
            replace(self.request, public_capture=Spec((Target(ROOT, 'privateid', T.STRING),)),
                    private_settings=(PrivateSettingDeclaration(ROOT, 'privateid', 'string'),), private_overlay_id='private-demo')
        self.assertEqual(self.config.reads, [])

    def test_skin_alias_collisions_rejected_before_all_reads(self):
        for first, second in (("CustomID", "customid"), ("customid", "CUSTOMID"),
                              ("HomeSwitcher.Foo", "homeswitcher.foo")):
            for group in ("overlap", "public", "private"):
                with self.subTest(first=first, second=second, group=group):
                    public = tuple(Target(SKIN, key, T.STRING, K.SKIN) for key in
                                   ((first, second) if group == "public" else (first,) if group == "overlap" else ()))
                    private = tuple(PrivateSettingDeclaration(SKIN, key, "string", target_kind=K.SKIN) for key in
                                    ((first, second) if group == "private" else (second,) if group == "overlap" else ()))
                    with patch.object(self.config, "get_skin_setting") as skin_get, \
                         patch.object(self.config, "get_setting") as addon_get, \
                         patch.object(self.engine, "inspect_state") as inspect, \
                         self.assertRaisesRegex(CreateRequestError, "^INVALID_CREATE_REQUEST$"):
                        replace(self.request, include_active_skin=True, public_capture=Spec(public),
                                private_settings=private, private_overlay_id="private-demo" if private else "")
                    skin_get.assert_not_called()
                    addon_get.assert_not_called()
                    inspect.assert_not_called()

    def test_skin_alias_identity_uses_effective_target_kind(self):
        from resources.lib.config import ConfigTargetKind
        # These enums share the runtime target value. Validation must use that
        # value too rather than enum object identity.
        with self.assertRaises(CreateRequestError):
            self.capture(include_active_skin=True,
                public_capture=Spec((Target(SKIN, "CustomID", T.STRING, ConfigTargetKind.SKIN),)),
                private_settings=(PrivateSettingDeclaration(SKIN, "customid", "string", target_kind=K.SKIN),),
                private_overlay_id="private-demo")
        self.assertEqual(self.config.reads, [])

    def test_addon_case_distinct_public_and_private_groups(self):
        self.config.values.update({(ROOT, "CustomID"): "one", (ROOT, "customid"): "two"})
        public = self.capture(public_capture=Spec(tuple(Target(ROOT, key, T.STRING) for key in ("CustomID", "customid"))))
        self.bundle(public)
        private = self.capture(private_settings=tuple(PrivateSettingDeclaration(ROOT, key, "string") for key in
                                                     ("CustomID", "customid")), private_overlay_id="private-demo")
        self.bundle(private)
        self.assertEqual(len(private.private_overlay.entries), 2)

    def test_skin_unrelated_and_addon_case_distinct_semantics(self):
        self.config.values.update({(SKIN, "CustomID"): "public", (SKIN, "otherid"): SECRET,
                                   (ROOT, "CustomID"): "public", (ROOT, "customid"): SECRET})
        for owner, kind, public_key, private_key in ((SKIN, K.SKIN, "CustomID", "otherid"),
                                                   (ROOT, K.ADDON, "CustomID", "customid")):
            result = self.capture(include_active_skin=True,
                public_capture=Spec((Target(owner, public_key, T.STRING, kind),)),
                private_settings=(PrivateSettingDeclaration(owner, private_key, "string", target_kind=kind),),
                private_overlay_id="private-demo")
            self.assert_public_surfaces_clean(result)
            self.assertEqual(result.private_overlay.entries[0].value, SECRET)

    def assert_public_surfaces_clean(self, result):
        raw = self.bundle(result)
        surfaces = [result.public_bundle.canonical_json, json.dumps(raw["packages"]),
                    json.dumps(raw["manifest"]), json.dumps(raw["frozen"]), repr(result),
                    str(result.safe_dict()), repr(result.private_overlay)]
        library_root = self.base / ("privacy-library-" + str(len(list(self.base.glob("privacy-library-*")))))
        library = BuildLibrary(library_root)
        with result.public_bundle.registration_inputs() as inputs:
            surfaces.extend(p.read_text() for path in inputs for p in
                            ([Path(path)] if Path(path).is_file() else Path(path).rglob("*")) if p.is_file())
            entry = library.register(*inputs)
        surfaces.append((library_root / "builds" / (entry.entry_id + ".json")).read_text())
        for surface in surfaces:
            self.assertNotIn(SECRET, surface)

    def test_real_skin_runtime_fallback_and_capture_alias_privacy(self):
        from resources.lib.skin import KodiRuntimeSkinSettingsBackend
        backend = KodiRuntimeSkinSettingsBackend()
        xbmc = Mock()
        xbmc.getSkinDir.return_value = SKIN
        def rpc(payload):
            key = json.loads(payload)["params"]["setting"]
            return json.dumps({"error": {"code": -32602}} if key == "CustomID" else
                              {"result": {"value": SECRET}})
        xbmc.executeJSONRPC.side_effect = rpc
        self.config.get_skin_setting = backend.get_setting
        with patch.dict("sys.modules", {"xbmc": xbmc}), patch("logging.Logger._log") as log:
            self.assertEqual(backend.get_setting(SKIN, "CustomID", T.STRING), SECRET)
            self.assertEqual([json.loads(c.args[0])["params"]["setting"] for c in
                              xbmc.executeJSONRPC.call_args_list], ["CustomID", "customid"])
            xbmc.reset_mock()
            with patch("resources.lib.create_capture.PreparedPublicBundle") as prepared, \
                 patch("resources.lib.build_library.BuildLibrary.register") as register:
                with self.assertRaises(CreateRequestError) as error:
                    self.capture(include_active_skin=True,
                        public_capture=Spec((Target(SKIN, "CustomID", T.STRING, K.SKIN),)),
                        private_settings=(PrivateSettingDeclaration(SKIN, "customid", "string", target_kind=K.SKIN),),
                        private_overlay_id="private-demo")
                prepared.assert_not_called()
                register.assert_not_called()
                self.assertNotIn(SECRET, repr(error.exception))
            xbmc.executeJSONRPC.assert_not_called()
            log.assert_not_called()
            result = self.capture(include_active_skin=True,
                private_settings=(PrivateSettingDeclaration(SKIN, "customid", "string", target_kind=K.SKIN),),
                private_overlay_id="private-demo")
            self.assert_public_surfaces_clean(result)
            self.assertEqual(result.private_overlay.entries[0].value, SECRET)
            log.assert_not_called()

    def test_sensitive_public_surface_rejected(self):
        for spec in (Spec((Target(ROOT, 'password', T.STRING),)), Spec(files=('userdata/addon_data/plugin.video.redlight/settings.db',))):
            with self.assertRaises(CreateRequestError):
                replace(self.request, public_capture=spec)
        self.assertEqual(self.config.reads, [])

    def test_unmanaged_owner_not_read(self):
        result = self.capture(public_capture=Spec((Target('plugin.unmanaged', 'quality', T.STRING),)))
        self.assertEqual(result.status, S.FAILED)
        self.assertEqual(self.config.reads, [])

    def test_skin_target_requires_included_active_skin(self):
        result = self.capture(root_addon_ids=(ROOT, SKIN), public_capture=Spec((Target(SKIN, 'background', T.STRING, K.SKIN),)))
        self.assertEqual(result.status, S.FAILED)
        self.assertEqual(self.config.reads, [])

    def test_exception_payload_and_logs_not_exposed(self):
        with patch.object(self.config, 'get_setting', side_effect=RuntimeError('/private/profile/' + SECRET)), \
             patch('logging.Logger._log') as log:
            result = self.capture(public_capture=Spec((Target(ROOT, 'quality', T.STRING),)))
        self.assertNotIn(SECRET, repr(result))
        self.assertNotIn('/private/profile', str(result.safe_dict()))
        self.assertFalse(log.called)

    def test_runtime_failure_safe(self):
        self.engine.inspect_state = Mock(side_effect=RuntimeError(SECRET))
        result = self.capture()
        self.assertEqual(result.gaps, ('RUNTIME_IDENTITY_UNAVAILABLE',))
        self.assertNotIn(SECRET, repr(result))

    def test_no_mutation_and_no_library_side_effect(self):
        with patch('resources.lib.config.ConfigurationManager.apply', side_effect=AssertionError('mutation')), \
             patch('resources.lib.private_overlay.PrivateOverlayManager.apply', side_effect=AssertionError('mutation')), \
             patch('resources.lib.private_resource.StructuredPrivateResourceManager.apply', side_effect=AssertionError('mutation')), \
             patch('resources.lib.build_library.BuildLibrary.register', side_effect=AssertionError('registration')):
            self.bundle(self.capture(public_capture=Spec((Target(ROOT, 'quality', T.STRING),), ('userdata/keymaps/demo.xml',))))
        self.assertEqual(self.config.mutations, [])
        self.assertFalse((self.base / 'library').exists())

    def test_canonical_determinism_and_immutable_output(self):
        first = self.capture(root_addon_ids=(ROOT, SKIN))
        second = self.capture(root_addon_ids=(SKIN, ROOT))
        self.assertEqual(first.public_bundle.canonical_json, second.public_bundle.canonical_json)
        copy = first.public_bundle.to_dict()
        copy['manifest']['build']['id'] = 'changed'
        self.assertEqual(first.public_bundle.to_dict()['manifest']['build']['id'], 'demo')
        with self.assertRaises(AttributeError):
            first.status = S.FAILED

    def test_malformed_caller_returns_safe_typed_failure(self):
        result = self.engine.capture({'path': SECRET}, created_at='today')
        self.assertEqual(result.status, S.FAILED)
        self.assertNotIn(SECRET, repr(result))

    def redlight(self, *, required=True, present=True):
        import sqlite3
        from resources.lib.redlight_resource import redlight_declaration, REDLIGHT_ADDON_ID as owner
        from resources.lib.private_resource import ResourceLifecycle, StructuredResourceFieldDeclaration
        declaration = replace(redlight_declaration((StructuredResourceFieldDeclaration('trakt.token', 'string', True, 'token'),)), required=required)
        self.inventory.addons += (_addon(owner, '2.6.8', enabled=False),)
        self.inventory.addon_xml[owner] = _xml(owner, '2.6.8')
        self.inventory.package_cache[(owner, '2.6.8')] = ((owner + '.zip', _zip(owner, '2.6.8')),)
        profile = self.base / 'isolated-profile'
        adapter = RedLightSettingsAdapter(profile, lifecycle=ResourceLifecycle.QUIESCED, initialized=present,
                    activation_hold_provider=lambda _: True, enabled_state_provider=lambda _: False)
        if present:
            adapter.database_path.parent.mkdir(parents=True)
            with sqlite3.connect(adapter.database_path) as db:
                db.execute('CREATE TABLE settings (setting_id text not null unique, setting_type text, setting_default text, setting_value text)')
                db.execute('INSERT INTO settings VALUES (?, ?, ?, ?)', ('trakt.token', 'string', '', SECRET))
        self.resources.register(adapter)
        self.request = replace(self.request, root_addon_ids=(ROOT, owner), private_resources=(declaration,), private_overlay_id='private-demo')
        return adapter

    def test_structured_capture_uses_real_adapter_readonly(self):
        adapter = self.redlight()
        before = adapter.database_path.read_bytes()
        with patch.object(adapter, 'capture', wraps=adapter.capture) as capture, \
             patch.object(adapter, 'apply', side_effect=AssertionError('mutation')), \
             patch.object(adapter, 'initialize', side_effect=AssertionError('mutation')), \
             patch('logging.Logger._log') as log:
            result = self.capture()
        self.bundle(result)
        self.assertEqual(capture.call_count, 1)
        self.assertEqual(result.private_overlay.resources[0].values[0].value, SECRET)
        self.assertNotIn(SECRET, result.public_bundle.canonical_json)
        self.assertNotIn(SECRET, repr(result))
        self.assertFalse(log.called)
        self.assertEqual(adapter.database_path.read_bytes(), before)

    def wal_fixture(self, *, shm=True):
        import sqlite3
        adapter = self.redlight()
        db = sqlite3.connect(adapter.database_path)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("UPDATE settings SET setting_value=?", ("checkpointed-disposable-value",))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("UPDATE settings SET setting_value=?", (SECRET,))
        db.commit()
        self.addCleanup(db.close)
        self.assertGreater(Path(str(adapter.database_path) + "-wal").stat().st_size, 0)
        if not shm:
            Path(str(adapter.database_path) + "-shm").unlink()
        return adapter

    @staticmethod
    def live_database_state(adapter):
        return tuple(p.read_bytes() if p.exists() else None for p in
                     (Path(str(adapter.database_path) + suffix) for suffix in ("", "-wal", "-shm")))

    def test_wal_current_capture_preserves_all_live_files_and_cleans_scratch(self):
        for shm in (True, False):
            with self.subTest(shm=shm):
                # Separate fixtures to avoid two registered owners or library version conflicts.
                case = CreateCaptureTests()
                case.setUp()
                try:
                    adapter = case.wal_fixture(shm=shm)
                    before = case.live_database_state(adapter)
                    scratch = []
                    original = tempfile.TemporaryDirectory
                    def temporary(**kwargs):
                        directory = original(**kwargs)
                        scratch.append(Path(directory.name))
                        return directory
                    with patch("resources.lib.redlight_resource.tempfile.TemporaryDirectory", side_effect=temporary), \
                         patch.object(adapter, "_open_read_only", side_effect=AssertionError("live SQLite")), \
                         patch("logging.Logger._log") as log:
                        result = case.capture()
                    case.assertEqual(case.live_database_state(adapter), before)
                    case.assertEqual(result.private_overlay.resources[0].values[0].value, SECRET)
                    case.assert_public_surfaces_clean(result)
                    case.assertTrue(scratch)
                    case.assertTrue(all(not p.exists() for p in scratch))
                    log.assert_not_called()
                    # Status still fails closed on uncheckpointed WAL and touches nothing.
                    from resources.lib.private_resource import PrivateResourceCompatibilityError
                    with case.assertRaises(PrivateResourceCompatibilityError):
                        adapter.inspect(case.request.private_resources[0], result.private_overlay.resources[0])
                    case.assertEqual(case.live_database_state(adapter), before)
                finally:
                    case.doCleanups()

    def test_unstable_snapshot_fails_incomplete_without_outputs(self):
        adapter = self.wal_fixture()
        original = adapter._read_snapshot_files
        for mutation in ("content", "replacement", "wal_disappears", "ancestor"):
            with self.subTest(mutation=mutation):
                # Mutation of the disposable source emulates an external actor.
                calls = []
                restore = []
                def read(directory):
                    data = original(directory)
                    calls.append(True)
                    if len(calls) == 1:
                        if mutation == "content":
                            p = adapter.database_path
                            data_mutated = bytearray(p.read_bytes()); data_mutated[-1] ^= 1
                            restore.append((p, p.read_bytes()))
                            p.write_bytes(data_mutated)
                        elif mutation == "replacement":
                            p = adapter.database_path
                            other = p.with_name("replacement.db")
                            other.write_bytes(p.read_bytes()); other.replace(p)
                        elif mutation == "wal_disappears":
                            p = Path(str(adapter.database_path) + "-wal")
                            restore.append((p, p.read_bytes())); p.unlink()
                        else:
                            parent = adapter.database_path.parent
                            moved = parent.with_name("moved-databases")
                            parent.rename(moved); parent.mkdir()
                            self.addCleanup(lambda: parent.rmdir())
                            restore.append((parent, moved))
                    return data
                try:
                    with patch.object(adapter, "_read_snapshot_files", side_effect=read), \
                         patch("logging.Logger._log") as log:
                        result = self.capture()
                    self.assertEqual(result.status, S.INCOMPLETE)
                    self.assertEqual(result.gaps, ("PRIVATE_RESOURCE_UNREADABLE",))
                    self.assertIsNone(result.public_bundle)
                    self.assertIsNone(result.private_overlay)
                    self.assertNotIn(SECRET, repr(result))
                    log.assert_not_called()
                finally:
                    for path, content in restore:
                        if isinstance(content, Path):
                            path.rmdir(); content.rename(path)
                            self._cleanups.pop()
                        else:
                            path.write_bytes(content)

    def test_source_change_during_temporary_query_fails_and_cleans(self):
        adapter = self.redlight()
        original = adapter._validate_schema
        scratch = []
        original_temporary = tempfile.TemporaryDirectory
        def temporary(**kwargs):
            directory = original_temporary(**kwargs); scratch.append(Path(directory.name)); return directory
        def validate(connection):
            original(connection)
            adapter.database_path.touch()
        with patch.object(adapter, "_validate_schema", side_effect=validate), \
             patch("resources.lib.redlight_resource.tempfile.TemporaryDirectory", side_effect=temporary):
            result = self.capture()
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertIsNone(result.public_bundle)
        self.assertIsNone(result.private_overlay)
        self.assertTrue(all(not p.exists() for p in scratch))

    def test_snapshot_rejects_ancestor_symlink(self):
        adapter = self.redlight()
        parent = adapter.database_path.parent
        moved = parent.with_name("moved-databases")
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
        before = (moved / "settings.db").read_bytes()
        try:
            self.assertEqual(self.capture().status, S.INCOMPLETE)
            self.assertEqual((moved / "settings.db").read_bytes(), before)
        finally:
            parent.unlink(); moved.rename(parent)

    def test_snapshot_rejects_symlinks_special_files_and_oversize(self):
        adapter = self.redlight()
        for suffix in ("", "-wal"):
            with self.subTest(suffix=suffix):
                path = Path(str(adapter.database_path) + suffix)
                saved = path.read_bytes() if path.exists() else None
                target = self.base / "untouched.db"
                target.write_bytes(b"untouched")
                if path.exists(): path.unlink()
                try:
                    path.symlink_to(target)
                    result = self.capture()
                    self.assertEqual(result.status, S.INCOMPLETE)
                    self.assertEqual(target.read_bytes(), b"untouched")
                    path.unlink()
                    import os
                    os.mkfifo(path)
                    self.assertEqual(self.capture().status, S.INCOMPLETE)
                    path.unlink()
                    with path.open("wb") as handle:
                        handle.truncate(64 * 1024 * 1024 + 1)
                    self.assertEqual(self.capture().status, S.INCOMPLETE)
                finally:
                    path.unlink()
                    if saved is not None: path.write_bytes(saved)

    def test_snapshot_sqlite_failure_cleans_scratch_and_redacts(self):
        adapter = self.redlight()
        before = self.live_database_state(adapter)
        adapter.database_path.write_bytes(b"invalid database")
        scratch = []
        original = tempfile.TemporaryDirectory
        def temporary(**kwargs):
            directory = original(**kwargs); scratch.append(Path(directory.name)); return directory
        with patch("resources.lib.redlight_resource.tempfile.TemporaryDirectory", side_effect=temporary):
            result = self.capture()
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertIsNone(result.public_bundle)
        self.assertTrue(scratch)
        self.assertTrue(all(not p.exists() for p in scratch))
        self.assertNotIn(SECRET, repr(result))
        self.assertEqual(self.live_database_state(adapter), (b"invalid database", before[1], before[2]))

    def test_required_resource_absent_incomplete(self):
        self.redlight(present=False)
        result = self.capture()
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertIsNone(result.private_overlay)
        self.assertIsNone(result.public_bundle)

    def test_optional_resource_absent_complete(self):
        self.redlight(required=False, present=False)
        result = self.capture()
        self.bundle(result)
        self.assertEqual(result.private_overlay.resources, ())

    def test_resource_unquiesced_is_safe_incomplete(self):
        from resources.lib.private_resource import ResourceLifecycle
        adapter = self.redlight()
        adapter._lifecycle = ResourceLifecycle.ACTIVE
        result = self.capture()
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertEqual(result.gaps, ('PRIVATE_RESOURCE_UNREADABLE',))

    def test_optional_absent_addon_setting(self):
        from resources.lib.config import ConfigAddonUnavailableError
        with patch.object(self.config, 'get_setting', side_effect=ConfigAddonUnavailableError('absent')):
            result = self.capture(private_settings=(PrivateSettingDeclaration(ROOT, 'privateid', 'string', required=False),), private_overlay_id='private-demo')
        self.bundle(result)
        self.assertEqual(result.private_overlay.entries, ())

    def test_optional_backend_error_is_not_absence(self):
        with patch.object(self.config, 'get_setting', side_effect=ConfigBackendError(SECRET)):
            result = self.capture(private_settings=(PrivateSettingDeclaration(ROOT, 'privateid', 'string', required=False),), private_overlay_id='private-demo')
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertIsNone(result.private_overlay)

    def test_no_extra_setting_or_file_reads(self):
        self.config.values[(ROOT, 'undeclared')] = SECRET
        self.config.files['userdata/keymaps/undeclared.xml'] = SECRET.encode()
        self.bundle(self.capture(public_capture=Spec((Target(ROOT, 'quality', T.STRING),), ('userdata/keymaps/demo.xml',))))
        self.assertEqual(self.config.reads, [('addon', ROOT, 'quality', T.STRING), ('file', 'userdata/keymaps/demo.xml')])

    def test_optional_missing_dependency_keeps_truth(self):
        self.inventory.addon_xml[ROOT] = _xml(ROOT, imports=(('script.module.absent', '1.0.0', True),))
        raw = self.bundle(self.capture())
        missing = next(n for n in raw['frozen']['addons'] if n['addon_id'] == 'script.module.absent')
        self.assertEqual(missing['capture_status'], 'missing')
        self.assertIsNone(missing['artifact_sha256'])

    def test_file_alias_rejected_before_read(self):
        for name in ('userdata/./keymaps/demo.xml', 'userdata\\keymaps\\demo.xml'):
            with self.assertRaises(CreateRequestError):
                replace(self.request, public_capture=Spec(files=(name,)))
        self.assertEqual(self.config.reads, [])

    def test_registration_transport_limit_fails_before_complete(self):
        self.config.values[(ROOT, 'quality')] = 'x' * (4 * 1024 * 1024 + 1)
        result = self.capture(public_capture=Spec((Target(ROOT, 'quality', T.STRING),)))
        self.assertEqual(result.status, S.FAILED)
        self.assertIsNone(result.public_bundle)

    def test_resource_version_must_match_frozen_owner(self):
        adapter = self.redlight()
        declaration = self.request.private_resources[0]
        self.request = replace(self.request, private_resources=(replace(declaration, supported_versions=('2.6.8', '2.6.9')),))
        resource, outcome = adapter.capture(declaration)
        with patch.object(adapter, 'capture', return_value=(replace(resource, addon_version='2.6.9'), outcome)):
            result = self.capture()
        self.assertEqual(result.status, S.INCOMPLETE)
        self.assertIsNone(result.private_overlay)

    def test_all_mutating_subsystems_are_unreached(self):
        from contextlib import ExitStack
        paths = ('resources.lib.addons.AddonManager.install',
                 'resources.lib.addon_state.AddonStateReconciler.reconcile',
                 'resources.lib.addon_state.KodiRuntimeAddonStateBackend.set_addon_enabled',
                 'resources.lib.skin.SkinActivator.activate',
                 'resources.lib.update_guard.UpdatePolicyBackend.set_policy',
                 'resources.lib.update_guard.KodiJsonRpcUpdatePolicyBackend.set_policy',
                 'resources.lib.restart_coordinator.RestartCoordinator.reconcile',
                 'resources.lib.restart_coordinator.RestartCoordinator.handle_result',
                 'resources.lib.frozen_install.FrozenInstallCoordinator.install',
                 'resources.lib.frozen_install.FrozenInstallCoordinator.retry_held_quiescence',
                 'resources.lib.frozen_install.FrozenInstallCoordinator.resume_after_restart',
                 'resources.lib.transaction.TransactionStore.create',
                 'resources.lib.private_overlay.PrivateOverlayStore.save')
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(path, side_effect=AssertionError('mutation'))) for path in paths]
            result = self.capture(include_active_skin=True, public_capture=Spec((Target(ROOT, 'quality', T.STRING),)),
                        private_settings=(PrivateSettingDeclaration(ROOT, 'privateid', 'string'),), private_overlay_id='private-demo')
            self.bundle(result)
            self.assertFalse(any(mock.called for mock in mocks))

    def test_frozen_engine_is_used_with_roots_only(self):
        from resources.lib.frozen import capture_frozen_build
        with patch('resources.lib.create_capture.capture_frozen_build', wraps=capture_frozen_build) as capture:
            self.bundle(self.capture())
        self.assertEqual(capture.call_count, 1)
        self.assertEqual(capture.call_args.kwargs['root_addon_ids'], (ROOT,))
        self.assertEqual(capture.call_args.kwargs['configuration_packages'], ('captured',))

    def test_optional_private_owner_absent_in_frozen_graph(self):
        owner = 'script.module.absent'
        self.inventory.addon_xml[ROOT] = _xml(ROOT, imports=((owner, '1.0.0', True),))
        result = self.capture(private_settings=(PrivateSettingDeclaration(owner, 'privateid', 'string', required=False),),
                              private_overlay_id='private-demo')
        self.bundle(result)
        self.assertEqual(result.private_overlay.entries, ())
        self.assertEqual(self.config.reads, [])

    def test_invalid_public_value_cannot_complete(self):
        self.config.values[(ROOT, 'quality')] = SECRET
        result = self.capture(public_capture=Spec((Target(ROOT, 'quality', T.INT),)))
        self.assertEqual(result.status, S.FAILED)
        self.assertNotIn(SECRET, str(result.safe_dict()))
        self.assertIsNone(result.public_bundle)

    def test_capture_identity_corruption_cannot_complete(self):
        from resources.lib.frozen import capture_frozen_build
        def corrupted(**kwargs):
            captured = capture_frozen_build(**kwargs)
            return replace(captured, manifest=replace(captured.manifest, build_id='wrong'))
        with patch('resources.lib.create_capture.capture_frozen_build', side_effect=corrupted):
            result = self.capture()
        self.assertEqual(result.status, S.FAILED)
        self.assertIsNone(result.public_bundle)
