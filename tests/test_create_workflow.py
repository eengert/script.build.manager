"""Offline native Create, real capture/library/private commit acceptance."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from resources.lib.create_workflow import (CreateBuildWorkflow, CreateValidationError,
    TrustedCaptureCatalog, identity, version_tuple)
from resources.lib.create_capture import CreateBuildCaptureEngine, CreateCaptureStatus, PublicCaptureSpecification, PublicSettingTarget
from resources.lib.build_library import BuildLibrary, LibraryConflict
from resources.lib.private_overlay import (PrivateOverlayStore, PrivateOverlay, PrivateOverlayEntry,
    PrivateOverlayConflict)
from resources.lib.config import ConfigSettingType
from resources.lib.manifest import PrivateSettingDeclaration
from resources.lib.frozen import InMemoryInventoryBackend
from resources.lib.artifacts import ArtifactStore
from resources.lib.ui.native_dialogs import NativeDialogs
from tests.test_create_capture import Configuration, SECRET
from tests.test_frozen import _addon, _xml, _zip
from tests.test_ui_foundation import Addon

ROOT = 'plugin.demo'
DEP = 'script.module.demo'
SKIN = 'skin.demo'
RED = 'plugin.video.redlight'
AF3 = 'skin.arctic.fuse.3'
STAMP = '2026-10-06T21:00:00Z'


class Catalog(TrustedCaptureCatalog):
    def compose(self, selected, skin, private, versions):
        public = PublicCaptureSpecification((PublicSettingTarget(ROOT, 'quality', ConfigSettingType.STRING),)) if ROOT in selected else PublicCaptureSpecification()
        settings = (PrivateSettingDeclaration(ROOT, 'privateid', 'string', True, 'private_identifier'),) if private and ROOT in selected else ()
        return public, settings, ()


class CreateAddon(Addon):
    def getLocalizedString(self, identifier):
        counts = {32704:2,32711:2,32714:2,32715:2,32737:1}
        return str(identifier) + (': ' + ' '.join(['%s'] * counts[identifier]) if identifier in counts else '')


class NativeDialog:
    def __init__(self, choices, inputs=(), multiselects=(), confirms=()):
        self.choices, self.inputs = iter(choices), iter(inputs)
        self.multiselects, self.confirms = iter(multiselects), iter(confirms)
        self.calls, self.multi_calls, self.details, self.results, self.questions = [], [], [], [], []
    def select(self, heading, labels, preselect=0):
        self.calls.append((heading, labels, preselect)); return next(self.choices)
    def input(self, heading, defaultt=''):
        return next(self.inputs)
    def multiselect(self, heading, labels, preselect):
        self.multi_calls.append((heading, labels, preselect)); return next(self.multiselects)
    def textviewer(self, *args): self.details.append(args)
    def yesno(self, *args, **kwargs): self.questions.append((args, kwargs)); return next(self.confirms)
    def ok(self, *args): self.results.append(args)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.config = Configuration()
        rows = [{**_addon(ROOT, addon_type='xbmc.python.pluginsource'), 'name': 'Demo'}, _addon(DEP),
                {**_addon(SKIN, addon_type='xbmc.gui.skin'), 'name': 'Demo Skin'},
                _addon('script.build.manager'), _addon('xbmc.python'),
                _addon('resource.language.demo'), _addon('runtime.hidden', addon_type='xbmc.python.module')]
        self.inventory = InMemoryInventoryBackend(rows,
            {ROOT: _xml(ROOT, imports=((DEP,'1.0.0',False),)), DEP:_xml(DEP), SKIN:_xml(SKIN)},
            package_cache={(a,'1.0.0'):((a+'.zip',_zip(a)),) for a in (ROOT,DEP,SKIN)})
        self.state = SimpleNamespace(platform='macos', kodi_version='21.0', active_skin=SKIN)
        self.library = BuildLibrary(self.base/'library')
        self.private_store = PrivateOverlayStore(self.base)
        self.artifacts = ArtifactStore(self.base/'artifacts')
        self.engine = CreateBuildCaptureEngine(inventory=self.inventory, artifact_store=self.artifacts,
            configuration=self.config, inspect_state=lambda:self.state)
        self.factory = Mock(return_value=self.engine)
        self.private_factory = Mock(return_value=self.private_store)
        self.clock = Mock(return_value=STAMP)
        self.workflow = CreateBuildWorkflow(inventory=self.inventory, inspect_state=lambda:self.state,
            library=self.library, engine_factory=self.factory, private_store_factory=self.private_factory,
            catalog=Catalog(), clock=self.clock)
        self.session = self.workflow.open('Current device'); self.session.name = 'My Build'

    def preview(self): return self.workflow.preview(self.session)
    def execute(self): return self.workflow.execute(self.preview())
    def entries(self): return self.library.list_builds()
    def overlay(self, value=SECRET, overlay_id='test-private'):
        return PrivateOverlay(overlay_id, 'sha256:'+'a'*64,
            (PrivateOverlayEntry(ROOT,'privateid',ConfigSettingType.STRING,value),))
    def ui(self, dialog):
        busy=[]
        ui=NativeDialogs(CreateAddon(), dialog, lambda ms:None, create_provider=lambda:self.workflow, busy=busy.append)
        ui.create(); return ui,busy

    def test_all_eligible_selected_and_private_on(self):
        self.assertEqual(set(self.session.selected),{ROOT,SKIN}); self.assertTrue(self.session.include_private)
    def test_manager_system_module_resource_excluded(self):
        self.assertEqual({c.addon_id for c in self.session.components},{ROOT,SKIN})
    def test_skin_default_marked(self):
        self.assertTrue(next(c for c in self.session.components if c.addon_id==SKIN).current_skin)
        self.assertTrue(self.preview().request.include_active_skin)
    def test_exclude_one(self):
        self.session.choose([1]); self.assertEqual(self.session.selected,(SKIN,))
    def test_exclude_many_zero_rejected(self):
        self.session.choose([])
        with self.assertRaises(CreateValidationError): self.preview()
        self.factory.assert_not_called()
    def test_cancel_selection_unchanged(self):
        self.session.choose([0]); old=self.session.selected; self.session.choose(None)
        self.assertEqual(self.session.selected,old)
    def test_bad_indices_rejected(self):
        for indices in ([-1],[9],[True]):
            with self.assertRaises(CreateValidationError): self.session.choose(indices)
    def test_current_skin_exclusion(self):
        self.session.choose([0]); r=self.preview().request
        self.assertFalse(r.include_active_skin); self.assertFalse(r.expected_active_skin)
    def test_missing_skin_fails_closed(self):
        self.state.active_skin='skin.absent'
        with self.assertRaises(CreateValidationError) as error:self.workflow.open('Device')
        self.assertEqual(error.exception.string_id,32723)
    def test_skin_change_after_preview_blocks(self):
        preview=self.preview(); self.state.active_skin='skin.changed'
        self.assertEqual(self.workflow.execute(preview).string_id,32723)
        self.assertEqual(self.entries(),()); self.private_factory.assert_not_called()
    def test_private_off_no_declarations_ref_or_store(self):
        self.session.include_private=False; r=self.preview().request
        self.assertEqual((r.private_settings,r.private_resources,r.private_overlay_id),((),(),''))
        self.assertEqual(self.execute().string_id,32736); self.private_factory.assert_not_called()
        bundle=self.library.get(self.entries()[0].entry_id)
        self.assertNotIn('private_overlay',bundle.manifest.to_dict() if hasattr(bundle,'manifest') else {})
    def test_private_owner_excluded(self):
        self.session.choose([1]); r=self.preview().request
        self.assertFalse(r.captures_private)
    def test_catalog_redlight_vetted_and_exclusion(self):
        c=TrustedCaptureCatalog(); spec,settings,resources=c.compose((RED,), '',True,{RED:'2.6.8'})
        from resources.lib.redlight_resource import redlight_declaration
        self.assertEqual(resources,(redlight_declaration(),));self.assertFalse(settings)
        for selected,on,version in (((),True,'2.6.8'),((RED,),False,'2.6.8'),((RED,),True,'9.0.0')):
            self.assertEqual(c.compose(selected,'',on,{RED:version})[2],())
    def test_catalog_af3_exact_production_schema(self):
        c=TrustedCaptureCatalog(); package=c.loader.load_package('af3-common')
        spec,private,resources=c.compose((AF3,),AF3,True,{AF3:'1.0.0'})
        self.assertEqual([(s.addon_id,s.key,s.setting_type) for s in spec.settings],
            [(s.addon_id,s.key,s.setting_type) for s in package.settings])
        self.assertEqual(spec.files,tuple(f.destination for f in package.files))
        self.assertFalse(private or resources)
    def test_af3_real_capture_reads_current_values(self):
        catalog=TrustedCaptureCatalog();package=catalog.loader.load_package('af3-common')
        self.inventory.addons=(*self.inventory.addons,_addon(AF3,addon_type='xbmc.gui.skin'))
        self.inventory.addon_xml[AF3]=_xml(AF3)
        self.inventory.package_cache[(AF3,'1.0.0')]=((AF3+'.zip',_zip(AF3)),)
        self.state.active_skin=AF3;self.workflow.catalog=catalog
        self.session=self.workflow.open('Device');self.session.name='AF3 Build'
        current={}
        for target in package.settings:
            value=not target.value if target.setting_type is ConfigSettingType.BOOL else target.value
            self.config.values[(AF3,target.key)]=value;current[target.key]=value
        result=self.engine.capture(self.preview().request,created_at=STAMP)
        self.assertEqual(result.status,CreateCaptureStatus.COMPLETE)
        captured=result.public_bundle.to_dict()['packages']['captured-public']['descriptor']['settings']
        self.assertEqual({s['key']:s['value'] for s in captured},current)
        self.assertNotEqual(current[package.settings[0].key],package.settings[0].value)

    def test_unrecognized_software_only(self):
        spec,private,resources=TrustedCaptureCatalog().compose((ROOT,), '',True,{ROOT:'1.0.0'})
        self.assertEqual(spec,PublicCaptureSpecification()); self.assertFalse(private or resources)
    def test_preview_cannot_invent_arbitrary_owners(self):
        self.session.selected=(ROOT,'arbitrary.owner')
        with self.assertRaises(CreateValidationError):self.preview()
    def test_slug_stable_safe_and_collision_resistant(self):
        import re
        for label in ('My Build','!!!','你好','A'*160):
            self.assertEqual(identity(label),identity(label)); self.assertTrue(re.fullmatch('[a-z0-9][a-z0-9._-]{0,63}',identity(label)))
        self.assertNotEqual(identity('My Build'),identity('My-Build'))
        self.assertNotEqual(identity('A'*150+'x'),identity('A'*150+'y'))
    def test_bad_names(self):
        for name in ('','  ','x\nsecret','x'*161,None):
            with self.assertRaises(CreateValidationError):identity(name)
    def test_version_new(self):self.assertEqual(self.workflow.suggest_version('Other'),'1.0.0')
    def test_version_highest_patch(self):
        self.library.list_builds=Mock(return_value=[SimpleNamespace(build_id=identity('My Build'),display_name='My Build',build_version=v) for v in ('1.9.9','2.0.3','2.0.10')])
        self.assertEqual(self.workflow.suggest_version('My Build'),'2.0.11')
    def test_name_conflict_surfaced(self):
        self.library.list_builds=Mock(return_value=[SimpleNamespace(build_id=identity('My Build'),display_name='Different',build_version='1.0.0')])
        with self.assertRaises(CreateValidationError):self.preview()
    def test_invalid_semver_before_capture(self):
        for value in ('1','1.0','01.0.0','1.0.0-beta','1.0.0\n','a.b.c'):
            self.session.version=value
            with self.assertRaises(CreateValidationError):self.preview()
        self.factory.assert_not_called()
    def test_profile_ids_safe(self):
        self.session.device_label='Living Room'; r=self.preview().request
        self.assertEqual(r.device_profile_id,identity('Living Room'));self.assertEqual(r.platform_profile_id,'macos')
    def test_preview_counts_and_no_writes(self):
        preview=self.preview();self.assertEqual(preview.counts,(2,0,1,0,1,0))
        self.factory.assert_not_called(); self.private_factory.assert_not_called()
        self.assertFalse((self.base/'library').exists());self.assertEqual(self.config.reads,[])
    def test_preview_excluded_truthful(self):
        self.session.choose([0]); p=self.preview()
        self.assertEqual(p.excluded_labels,('Demo Skin',));self.assertEqual(p.counts[:2],(1,1))
    def test_exact_preview_request_and_one_timestamp(self):
        engine=Mock();engine.capture.return_value=SimpleNamespace(status=CreateCaptureStatus.FAILED,gaps=())
        self.factory.return_value=engine;p=self.preview();self.workflow.execute(p)
        engine.capture.assert_called_once_with(p.request,created_at=STAMP);self.clock.assert_called_once()
    def test_incomplete_no_commit(self):
        self.engine.capture=Mock(return_value=SimpleNamespace(status=CreateCaptureStatus.INCOMPLETE,gaps=('SOFTWARE_INCOMPLETE',)))
        self.assertEqual(self.execute().string_id,32730);self.private_factory.assert_not_called();self.assertEqual(self.entries(),())
    def test_failed_no_commit(self):
        self.engine.capture=Mock(return_value=SimpleNamespace(status=CreateCaptureStatus.FAILED,gaps=()))
        self.assertEqual(self.execute().string_id,32732);self.private_factory.assert_not_called();self.assertEqual(self.entries(),())
    def test_complete_private_register_select(self):
        terminal=self.execute();self.assertEqual(terminal.string_id,32736)
        entry=self.entries()[0];self.assertEqual(self.library.current_selection().entry_id,entry.entry_id)
        self.assertEqual(self.private_store.load(self.preview().request.private_overlay_id).entries[0].value,SECRET)
    def test_identical_repeat_idempotent(self):
        self.assertEqual(self.execute().string_id,32736); self.assertEqual(self.execute().string_id,32736)
        self.assertEqual(len(self.entries()),1)
    def test_changed_private_conflict_no_overwrite(self):
        self.execute();p=self.preview();old=self.private_store.load(p.request.private_overlay_id).fingerprint
        self.config.values[(ROOT,'privateid')]='changed-secret'
        self.assertEqual(self.execute().string_id,32733)
        self.assertEqual(self.private_store.load(p.request.private_overlay_id).fingerprint,old)
    def test_changed_public_conflict_rolls_back_new_overlay(self):
        self.execute();p=self.preview();old=self.private_store.load(p.request.private_overlay_id)
        with self.private_store.create_commit() as commit:commit.remove_if_exact(old.overlay_id,old.fingerprint)
        self.config.values[(ROOT,'quality')]='changed'
        self.assertEqual(self.execute().string_id,32733)
        self.assertFalse(self.private_store.path_for(old.overlay_id).exists());self.assertEqual(len(self.entries()),1)
    def test_registration_failure_new_overlay_cleanup(self):
        p=self.preview();self.library.register=Mock(side_effect=OSError(SECRET))
        self.assertEqual(self.workflow.execute(p).string_id,32734)
        self.assertFalse(self.private_store.path_for(p.request.private_overlay_id).exists())
    def test_registration_failure_existing_overlay_preserved(self):
        p=self.preview();result=self.engine.capture(p.request,created_at=STAMP)
        with self.private_store.create_commit() as commit:commit.ensure_exact(result.private_overlay)
        self.library.register=Mock(side_effect=OSError(SECRET))
        self.assertEqual(self.workflow.execute(p).string_id,32734)
        self.assertEqual(self.private_store.load(p.request.private_overlay_id).fingerprint,result.private_overlay.fingerprint)
    def test_registration_raises_after_publication_preserves_valid_overlay(self):
        original = self.library.register
        def publish_then_raise(*inputs):
            original(*inputs)
            raise OSError(SECRET)
        self.library.register = publish_then_raise
        p = self.preview()
        self.assertEqual(self.workflow.execute(p).string_id,32736)
        self.assertEqual(len(self.entries()),1)
        self.assertTrue(self.private_store.path_for(p.request.private_overlay_id).exists())

    def test_ambiguous_registry_failure_retains_private_fail_closed(self):
        self.library.register=Mock(side_effect=OSError(SECRET))
        self.library.registered_bundle=Mock(side_effect=[None, OSError(SECRET)])
        p=self.preview()
        self.assertEqual(self.workflow.execute(p).string_id,32734)
        self.assertTrue(self.private_store.path_for(p.request.private_overlay_id).exists())
        self.assertEqual(self.entries(),())

    def test_exact_public_missing_private_never_recreated(self):
        p = self.preview()
        self.assertEqual(self.workflow.execute(p).string_id, 32736)
        path = self.private_store.path_for(p.request.private_overlay_id)
        path.unlink()
        self.config.values[(ROOT, 'privateid')] = 'changed-disposable-private'
        self.library.register = Mock(side_effect=AssertionError('must reuse entry'))
        self.assertEqual(self.workflow.execute(p).string_id, 32733)
        self.assertFalse(path.exists())
        self.library.register.assert_not_called()
        self.assertEqual(len(self.entries()), 1)

    def test_exact_public_matching_private_reuses_entry_without_writes(self):
        p = self.preview()
        self.assertEqual(self.workflow.execute(p).string_id, 32736)
        path = self.private_store.path_for(p.request.private_overlay_id)
        before = path.stat()
        self.library.register = Mock(side_effect=AssertionError('must reuse entry'))
        self.assertEqual(self.workflow.execute(p).string_id, 32736)
        self.library.register.assert_not_called()
        self.assertEqual(path.stat().st_ino, before.st_ino)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_exact_public_malformed_private_preserved(self):
        p = self.preview(); self.workflow.execute(p)
        path = self.private_store.path_for(p.request.private_overlay_id)
        path.write_text('{')
        self.assertEqual(self.workflow.execute(p).string_id, 32734)
        self.assertEqual(path.read_text(), '{')
        self.assertEqual(len(self.entries()), 1)

    def test_exact_public_nonregular_private_fails_closed(self):
        import os
        p = self.preview(); self.workflow.execute(p)
        path = self.private_store.path_for(p.request.private_overlay_id)
        path.unlink(); os.mkfifo(path)
        self.assertEqual(self.workflow.execute(p).string_id, 32734)
        self.assertTrue(path.exists())

    def test_exact_public_unreadable_private_fails_closed(self):
        p = self.preview(); self.workflow.execute(p)
        path = self.private_store.path_for(p.request.private_overlay_id)
        before = path.read_bytes()
        from resources.lib.build_library import _read_at
        def deny(fd, name, limit):
            if name == path.name:
                raise PermissionError(SECRET)
            return _read_at(fd, name, limit)
        with patch('resources.lib.build_library._read_at', side_effect=deny):
            terminal = self.workflow.execute(p)
        self.assertEqual(terminal.string_id, 32734)
        self.assertNotIn(SECRET, repr(terminal))
        self.assertEqual(path.read_bytes(), before)

    def test_orphan_matching_continues_and_differing_conflicts(self):
        p = self.preview(); result = self.engine.capture(p.request, created_at=STAMP)
        with self.private_store.create_commit() as commit:
            commit.ensure_exact(result.private_overlay)
        self.config.values[(ROOT, 'privateid')] = 'changed-disposable-private'
        self.assertEqual(self.workflow.execute(p).string_id, 32733)
        self.assertEqual(self.entries(), ())
        self.config.values[(ROOT, 'privateid')] = SECRET
        self.assertEqual(self.workflow.execute(p).string_id, 32736)

    def test_indexed_missing_builds_recovery_preserves_private(self):
        import shutil
        original = self.library.register
        def publish_then_lose_content(*inputs):
            original(*inputs)
            shutil.rmtree(Path(self.library.root) / 'builds')
            raise OSError(SECRET)
        self.library.register = publish_then_lose_content
        p = self.preview()
        terminal = self.workflow.execute(p)
        self.assertEqual(terminal.string_id, 32734)
        self.assertTrue(self.private_store.path_for(p.request.private_overlay_id).exists())
        self.assertNotIn(SECRET, repr(terminal))

    def test_authority_check_is_inside_private_commit_lock(self):
        original = self.library.registered_bundle
        def inspect(bundle):
            with self.assertRaises(OSError):
                with self.private_store.create_commit():
                    pass
            return original(bundle)
        self.library.registered_bundle = inspect
        self.assertEqual(self.execute().string_id, 32736)
        self.assertEqual(self.execute().string_id, 32736)

    def reject_complete_overlay(self, transform):
        p = self.preview(); result = self.engine.capture(p.request, created_at=STAMP)
        result = replace(result, private_overlay=transform(result.private_overlay))
        self.engine.capture = Mock(return_value=result)
        self.library.register = Mock(side_effect=AssertionError('must not register'))
        self.library.select = Mock(side_effect=AssertionError('must not select'))
        from resources.lib.create_capture import PreparedPublicBundle
        with patch.object(PreparedPublicBundle, 'registration_inputs', side_effect=AssertionError('must not stage')) as stage:
            terminal = self.workflow.execute(p)
        self.assertEqual(terminal.string_id, 32732)
        self.assertNotIn(SECRET, repr(terminal))
        self.assertNotIn(SECRET, str(terminal.safe_dict()))
        self.private_factory.assert_not_called()
        self.library.register.assert_not_called(); self.library.select.assert_not_called()
        stage.assert_not_called()
        self.assertFalse(Path(self.library.root).exists())
        self.assertFalse(self.private_store.directory.exists())
        self.assertEqual(self.config.mutations, [])

    def test_complete_undeclared_private_setting_zero_persistence(self):
        self.reject_complete_overlay(lambda overlay: replace(overlay, entries=overlay.entries +
            (PrivateOverlayEntry(ROOT, 'undeclared', ConfigSettingType.STRING, SECRET),)))

    def test_complete_undeclared_private_resource_zero_persistence(self):
        from resources.lib.private_resource import StructuredPrivateResourceOverlay, StructuredPrivateValue
        resource = StructuredPrivateResourceOverlay('redlight.settings', RED, '2.6.8',
            'redlight-settings-v1', (StructuredPrivateValue('trakt.token', 'string', SECRET),))
        self.reject_complete_overlay(lambda overlay: replace(overlay, resources=(resource,)))

    def test_complete_missing_required_private_zero_persistence(self):
        self.reject_complete_overlay(lambda overlay: replace(overlay, entries=()))

    def test_complete_wrong_overlay_id_zero_persistence(self):
        self.reject_complete_overlay(lambda overlay: replace(overlay, overlay_id='wrong-overlay'))

    def test_complete_wrong_source_fingerprint_zero_persistence(self):
        self.reject_complete_overlay(lambda overlay: replace(overlay, target_build_id='sha256:' + 'a'*64))

    def test_complete_wrong_setting_type_zero_persistence(self):
        self.reject_complete_overlay(lambda overlay: replace(overlay, entries=
            (PrivateOverlayEntry(ROOT, 'privateid', ConfigSettingType.BOOL, True),)))

    def test_complete_other_valid_public_frozen_identity_zero_persistence(self):
        from resources.lib.create_capture import PreparedPublicBundle
        p = self.preview(); result = self.engine.capture(p.request, created_at=STAMP)
        raw = result.public_bundle.to_dict()
        from resources.lib.frozen import FrozenBuildManifest
        frozen = FrozenBuildManifest.from_dict(raw['frozen'])
        raw['frozen'] = replace(frozen, kodi_version='22.0', source_metadata={'kodi_version': '22.0'}).to_dict()
        result = replace(result, public_bundle=PreparedPublicBundle(json.dumps(raw)))
        self.engine.capture = Mock(return_value=result)
        self.assertEqual(self.workflow.execute(p).string_id, 32732)
        self.private_factory.assert_not_called(); self.assertEqual(self.entries(), ())

    def reject_public_binding(self, transform):
        from resources.lib.create_capture import PreparedPublicBundle
        p = self.preview(); result = self.engine.capture(p.request, created_at=STAMP)
        raw = result.public_bundle.to_dict(); transform(raw)
        result = replace(result, public_bundle=PreparedPublicBundle(json.dumps(raw)))
        self.engine.capture = Mock(return_value=result)
        self.assertEqual(self.workflow.execute(p).string_id, 32732)
        self.private_factory.assert_not_called(); self.assertEqual(self.entries(), ())

    def test_complete_public_overlay_reference_mismatch_zero_persistence(self):
        self.reject_public_binding(lambda raw: raw['manifest']['private_overlay'].update(overlay_id='wrong'))

    def test_complete_public_private_declarations_mismatch_zero_persistence(self):
        self.reject_public_binding(lambda raw: raw['manifest']['config'].update(private_settings=[]))

    def test_complete_public_build_version_mismatch_zero_persistence(self):
        self.reject_public_binding(lambda raw: raw['manifest']['build'].update(version='2.0.0'))

    def test_complete_missing_required_resource_zero_persistence(self):
        from resources.lib.create_capture import PreparedPublicBundle
        from resources.lib.redlight_resource import redlight_declaration
        declaration = redlight_declaration()
        self.assertTrue(declaration.required)
        p = self.preview(); result = self.engine.capture(p.request, created_at=STAMP)
        p = replace(p, request=replace(p.request, private_resources=(declaration,)))
        raw = result.public_bundle.to_dict()
        raw['manifest']['config']['structured_private_resources'] = [declaration.safe_dict()]
        result = replace(result, public_bundle=PreparedPublicBundle(json.dumps(raw)))
        self.engine.capture = Mock(return_value=result)
        self.assertEqual(self.workflow.execute(p).string_id, 32732)
        self.private_factory.assert_not_called(); self.assertEqual(self.entries(), ())

    def test_require_exact_missing_never_writes(self):
        with self.private_store.create_commit() as commit:
            with self.assertRaises(PrivateOverlayConflict):
                commit.require_exact(self.overlay())
            self.assertFalse(self.private_store.path_for('test-private').exists())
            commit.ensure_exact(self.overlay())
            commit.require_exact(self.overlay())
            with self.assertRaises(PrivateOverlayConflict):
                commit.require_exact(self.overlay('different'))

    def test_rollback_unlink_failure_retains_private(self):
        import os
        original = os.unlink
        p = self.preview()
        def deny(name, *args, **kwargs):
            if name == self.private_store.path_for(p.request.private_overlay_id).name:
                raise OSError(SECRET)
            return original(name, *args, **kwargs)
        self.library.register = Mock(side_effect=OSError(SECRET))
        with patch('resources.lib.private_overlay.os.unlink', side_effect=deny):
            self.assertEqual(self.workflow.execute(p).string_id, 32734)
        self.assertTrue(self.private_store.path_for(p.request.private_overlay_id).exists())

    def test_rollback_fsync_failure_safe_terminal(self):
        import os
        original = os.fsync
        count = 0
        def fail_rollback(fd):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError(SECRET)
            return original(fd)
        p = self.preview(); captured = self.engine.capture(p.request, created_at=STAMP)
        self.engine.capture = Mock(return_value=captured)
        self.library.register = Mock(side_effect=OSError(SECRET))
        with patch('resources.lib.private_overlay.os.fsync', side_effect=fail_rollback):
            terminal = self.execute()
        self.assertEqual(terminal.string_id, 32734)
        self.assertEqual(self.entries(), ())
        self.assertNotIn(SECRET, repr(terminal))

    def test_private_file_fsync_failure_no_publication(self):
        p = self.preview(); captured = self.engine.capture(p.request, created_at=STAMP)
        self.engine.capture = Mock(return_value=captured)
        with patch('resources.lib.private_overlay.os.fsync', side_effect=OSError(SECRET)):
            terminal = self.execute()
        self.assertEqual(terminal.string_id, 32734)
        self.assertEqual(self.entries(), ())
        self.assertFalse(self.private_store.path_for(self.preview().request.private_overlay_id).exists())

    def test_concurrent_same_overlay_creates_safe_and_retry_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        p = self.preview(); original = self.library.register
        entered, release = Event(), Event()
        def slow_register(*inputs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('disposable test timeout')
            return original(*inputs)
        self.library.register = slow_register
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.workflow.execute, p)
            self.assertTrue(entered.wait(5))
            try:
                second = pool.submit(self.workflow.execute, p).result(timeout=5)
                self.assertEqual(second.string_id, 32734)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5).string_id, 32736)
        self.assertEqual(self.workflow.execute(p).string_id, 32736)
        self.assertEqual(len(self.entries()), 1)

    def test_library_entry_publication_failure_rolls_back_proven_absence(self):
        from resources.lib import build_library as lib
        root = Path(self.library.root); root.mkdir(parents=True)
        (root / 'registry.json').write_text(json.dumps({'schema_version': 1, 'entries': {}}))
        original = lib._atomic
        def fail_envelope(fd, name, data):
            if name not in ('registry.json', 'selection.json'):
                raise OSError(SECRET)
            return original(fd, name, data)
        with patch.object(lib, '_atomic', side_effect=fail_envelope):
            terminal = self.execute()
        self.assertEqual(terminal.string_id, 32734)
        self.assertEqual(self.entries(), ())
        self.assertFalse(self.private_store.path_for(self.preview().request.private_overlay_id).exists())

    def test_missing_registry_after_publication_preserves_private(self):
        original = self.library.register
        def lose_registry(*inputs):
            original(*inputs)
            (Path(self.library.root) / 'registry.json').unlink()
            raise OSError(SECRET)
        self.library.register = lose_registry
        self.assertEqual(self.execute().string_id, 32734)
        self.assertTrue(self.private_store.path_for(self.preview().request.private_overlay_id).exists())

    def test_private_sentinels_absent_from_staging_logs_and_errors(self):
        p = self.preview(); result = self.engine.capture(p.request, created_at=STAMP)
        self.assertNotIn(SECRET, repr(result.private_overlay))
        original = self.library.register
        def inspect_staging(*inputs):
            for name in inputs:
                path = Path(name)
                paths = path.rglob('*') if path.is_dir() else (path,)
                for item in paths:
                    if item.is_file():
                        self.assertNotIn(SECRET.encode(), item.read_bytes())
            return original(*inputs)
        self.library.register = inspect_staging
        with self.assertNoLogs(level='DEBUG'):
            terminal = self.workflow.execute(p)
            self.config.values[(ROOT, 'privateid')] = SECRET + '-different'
            conflict = self.workflow.execute(p)
        self.assertEqual(terminal.string_id, 32736)
        self.assertEqual(conflict.string_id, 32733)
        for value in (repr(terminal), str(terminal.safe_dict()), repr(conflict), str(conflict.safe_dict())):
            self.assertNotIn(SECRET, value)
        self.assertEqual(self.config.mutations, [])

    def test_storage_wording_allows_next_version(self):
        po = (Path(__file__).parents[1] / 'resources/language/resource.language.en_gb/strings.po').read_text()
        text = po.split('msgctxt "#32734"', 1)[1].split('msgstr', 1)[0]
        self.assertNotIn('same version', text)
        self.assertIn('choose the next version', text)

    def test_selection_failure_keeps_saved_private_and_build(self):
        self.library.select=Mock(side_effect=OSError(SECRET));p=self.preview()
        self.assertEqual(self.workflow.execute(p).string_id,32735);self.assertEqual(len(self.entries()),1)
        self.assertTrue(self.private_store.path_for(p.request.private_overlay_id).exists())
    def test_malformed_existing_private_fails_closed(self):
        p=self.preview();path=self.private_store.path_for(p.request.private_overlay_id);path.parent.mkdir(parents=True)
        path.write_text('{')
        self.assertEqual(self.workflow.execute(p).string_id,32734);self.assertEqual(path.read_text(),'{');self.assertEqual(self.entries(),())
    def test_store_exact_create_idempotent_conflict(self):
        overlay=self.overlay()
        with self.private_store.create_commit() as commit:
            self.assertTrue(commit.ensure_exact(overlay));self.assertFalse(commit.ensure_exact(overlay))
            with self.assertRaises(PrivateOverlayConflict):commit.ensure_exact(self.overlay('different'))
        self.assertEqual(self.private_store.load(overlay.overlay_id).fingerprint,overlay.fingerprint)
    def test_exact_cleanup_checks_fingerprint(self):
        overlay=self.overlay()
        with self.private_store.create_commit() as commit:
            commit.ensure_exact(overlay)
            self.assertFalse(commit.remove_if_exact(overlay.overlay_id,'sha256:'+'b'*64))
            self.assertTrue(commit.remove_if_exact(overlay.overlay_id,overlay.fingerprint))
            self.assertFalse(commit.remove_if_exact(overlay.overlay_id,overlay.fingerprint))
    def test_store_symlink_target_rejected(self):
        self.private_store.directory.mkdir(parents=True);target=self.base/'unrelated';target.write_text('keep')
        self.private_store.path_for('test-private').symlink_to(target)
        with self.assertRaises(Exception):
            with self.private_store.create_commit() as commit:commit.ensure_exact(self.overlay())
        self.assertEqual(target.read_text(),'keep')
    def test_store_symlink_ancestor_rejected(self):
        other=self.base/'other';other.mkdir();(self.base/'addon_data').symlink_to(other)
        with self.assertRaises(Exception):
            with self.private_store.create_commit() as commit:commit.ensure_exact(self.overlay())
        self.assertEqual(list(other.iterdir()),[])
    def test_private_permissions_and_lock_serialization(self):
        overlay=self.overlay()
        with self.private_store.create_commit() as commit:
            commit.ensure_exact(overlay)
            with self.assertRaises(OSError):
                with self.private_store.create_commit():pass
            with self.assertRaises(OSError):self.private_store.save(self.overlay('replacement'))
        self.assertEqual(self.private_store.path_for(overlay.overlay_id).stat().st_mode & 0o777,0o600)
    def test_dependency_stays_dependency(self):
        self.session.choose([0]);self.session.include_private=False
        result=self.engine.capture(self.preview().request,created_at=STAMP);bundle=result.public_bundle.to_dict()
        self.assertIn(DEP,{n['addon_id'] for n in bundle['frozen']['addons']})
        self.assertEqual([n['addon_id'] for n in bundle['manifest']['addons']],[ROOT])
    def test_current_values_not_schema_defaults(self):
        p=self.preview();result=self.engine.capture(p.request,created_at=STAMP)
        self.assertEqual(result.public_bundle.to_dict()['packages']['captured-public']['descriptor']['settings'][0]['value'],'high')
    def test_privacy_all_public_models_and_real_library(self):
        p=self.preview();result=self.engine.capture(p.request,created_at=STAMP)
        for value in (repr(self.session),repr(p),str(p.safe_dict()),repr(result),str(result.safe_dict()),str(result.public_bundle.to_dict())):
            self.assertNotIn(SECRET,value)
        terminal=self.workflow.execute(p)
        self.assertNotIn(SECRET,repr(terminal));self.assertNotIn(SECRET,str(terminal.safe_dict()))
        for path in (self.base/'library').rglob('*'):
            if path.is_file():self.assertNotIn(SECRET.encode(),path.read_bytes())
        self.assertEqual(self.config.mutations,[])
    def test_native_multiselect_reopen_cancel_preserves_choices(self):
        d=NativeDialog([3,3,3,7],multiselects=[[0],None,[0]])
        self.ui(d)
        self.assertEqual([c[2] for c in d.multi_calls],[[0,1],[0],[0]])
        self.factory.assert_not_called();self.assertIn('32709',d.multi_calls[0][1][1])
    def test_native_back_before_preview_no_capture(self):
        d=NativeDialog([7]);self.ui(d);self.factory.assert_not_called()
    def test_native_preview_back_no_capture(self):
        d=NativeDialog([0,5,3,7],inputs=['My Build']);self.ui(d)
        self.factory.assert_not_called();self.private_factory.assert_not_called()
    def test_native_final_no_confirmation_no_capture(self):
        d=NativeDialog([0,5,0,7],inputs=['My Build'],confirms=[False]);self.ui(d)
        self.factory.assert_not_called();self.assertEqual(len(d.questions),1)
    def test_native_success_persistent_and_busy(self):
        d=NativeDialog([0,5,1,0],inputs=['My Build'],confirms=[True]);_,busy=self.ui(d)
        self.assertEqual(busy,[True,False]);self.assertEqual(len(d.results),1)
        self.assertIn('32736',d.results[0][1]);self.assertNotIn(SECRET,str(vars(d)))
        self.assertNotIn(str(self.base),str(vars(d)));self.assertEqual(self.config.mutations,[])
    def test_native_private_toggle_off(self):
        d=NativeDialog([0,4,5,0],inputs=['My Build'],confirms=[True]);self.ui(d)
        self.private_factory.assert_not_called();self.assertEqual(len(self.entries()),1)
    def test_native_failure_persistent(self):
        self.factory.side_effect=RuntimeError(SECRET)
        d=NativeDialog([0,5,0],inputs=['My Build'],confirms=[True]);_,busy=self.ui(d)
        self.assertEqual(busy,[True,False]);self.assertIn('32732',d.results[0][1]);self.assertNotIn(SECRET,str(vars(d)))
    def test_native_focus_return(self):
        d=NativeDialog([3,7],multiselects=[None]);self.ui(d)
        self.assertEqual(d.calls[1][2],3)
    def test_deterministic_order_and_name_fallback(self):
        self.inventory.addons=tuple(reversed(self.inventory.addons))
        other=self.workflow.open('Device')
        self.assertEqual(other.components,self.session.components)
        self.inventory.addons=tuple({**a,'name':None} if a['addonid']==ROOT else a for a in self.inventory.addons)
        other=self.workflow.open('Device')
        self.assertEqual(next(c.label for c in other.components if c.addon_id==ROOT),ROOT)

    def test_normal_user_addon_categories_remain_roots(self):
        rows = [_addon(a,addon_type=t) for a,t in (
            ('plugin.audio.demo','xbmc.python.pluginsource'),
            ('script.demo','xbmc.python.script'),('service.demo','xbmc.service'),
            ('repository.demo','xbmc.addon.repository'))]
        self.inventory.addons=(*self.inventory.addons,*rows)
        session=self.workflow.open('Device')
        self.assertTrue({a['addonid'] for a in rows} <= set(session.selected))

    def test_excluded_skin_can_remain_dependency_without_desired_skin(self):
        self.inventory.addon_xml[ROOT]=_xml(ROOT,imports=((SKIN,'1.0.0',False),))
        self.session.choose([0]);self.session.include_private=False
        result=self.engine.capture(self.preview().request,created_at=STAMP)
        raw=result.public_bundle.to_dict()
        self.assertIn(SKIN,{n['addon_id'] for n in raw['frozen']['addons']})
        self.assertNotIn('skin',raw['manifest'])
        self.assertEqual([a['addon_id'] for a in raw['manifest']['addons']],[ROOT])

    def test_public_only_conflict_preserves_existing_build_and_selection(self):
        self.session.include_private=False;self.execute()
        prior=self.library.current_selection()
        self.config.values[(ROOT,'quality')]='new'
        self.assertEqual(self.execute().string_id,32733)
        self.assertEqual(len(self.entries()),1);self.assertEqual(self.library.current_selection(),prior)

    def test_configuration_gap_persistent_category_and_no_store(self):
        self.config.values.pop((ROOT,'quality'))
        self.assertEqual(self.execute().string_id,32731)
        self.assertEqual(self.entries(),());self.private_factory.assert_not_called()

    def test_fsync_failure_after_private_publication_rolls_back_exact(self):
        overlay=self.overlay()
        import os
        actual=os.fsync
        with self.private_store.create_commit() as commit:
            def fail_directory(fd):
                if fd==commit.fd:raise OSError('directory sync failed')
                return actual(fd)
            with patch('resources.lib.private_overlay.os.fsync',side_effect=fail_directory):
                with self.assertRaises(OSError):commit.ensure_exact(overlay)
        self.assertFalse(self.private_store.path_for(overlay.overlay_id).exists())

    def test_native_main_create_route_and_help(self):
        d=NativeDialog([0,6,7,-1])
        ui=NativeDialogs(CreateAddon(),d,lambda ms:None,create_provider=lambda:self.workflow)
        ui.run()
        self.assertEqual(d.details,[('32201','32301')])
        self.assertEqual(d.calls[-1][2],0);self.factory.assert_not_called()

    def test_preview_safe_dictionary_hides_request(self):
        p=self.preview()
        self.assertNotIn('request',p.safe_dict())
        self.assertNotIn(SECRET,str(p.safe_dict()))

    def test_localization_identifiers_unique(self):
        import re
        po=(Path(__file__).parents[1]/'resources/language/resource.language.en_gb/strings.po').read_text()
        ids=re.findall(r'msgctxt "#([0-9]+)"',po)
        self.assertEqual(len(ids),len(set(ids)))

    def test_duplicate_json_private_state_rejected_without_overwrite(self):
        overlay=self.overlay();path=self.private_store.path_for(overlay.overlay_id)
        path.parent.mkdir(parents=True)
        raw=json.dumps(overlay.to_dict())
        raw=raw[:-1]+',"overlay_id":"test-private"}'
        path.write_text(raw)
        with self.assertRaises(Exception):
            with self.private_store.create_commit() as commit:commit.ensure_exact(overlay)
        self.assertEqual(path.read_text(),raw)

    def test_fifo_private_state_fails_without_blocking(self):
        import os
        path=self.private_store.path_for('test-private');path.parent.mkdir(parents=True);os.mkfifo(path)
        with self.assertRaises(Exception):
            with self.private_store.create_commit() as commit:commit.ensure_exact(self.overlay())
        self.assertTrue(path.exists())

    def test_runtime_composition_defers_artifact_and_private_stores(self):
        import sys
        from resources.lib.create_workflow import runtime_create_workflow
        calls=[]
        def rpc(raw):
            request=json.loads(raw);calls.append(request)
            self.assertEqual(request['method'],'Addons.GetAddons')
            return json.dumps({'result':{'addons':list(self.inventory.addons)}})
        modules={'xbmc':SimpleNamespace(executeJSONRPC=rpc),
                 'xbmcvfs':SimpleNamespace(translatePath=lambda uri:str(self.base / uri.replace('special://','').replace('/','-')))}
        with patch.dict(sys.modules,modules), patch('resources.lib.inspector.KodiStateInspector') as inspector, patch('resources.lib.artifacts.ArtifactStore') as artifacts, patch('resources.lib.private_overlay.PrivateOverlayStore') as private:
            inspector.return_value.inspect.return_value=self.state
            workflow=runtime_create_workflow();session=workflow.open('Device');session.name='Runtime Build'
            preview=workflow.preview(session)
            artifacts.assert_not_called();private.assert_not_called()
            self.assertEqual(preview.request.root_addon_ids,(ROOT,SKIN))
            self.assertIn('name',calls[0]['params']['properties'])
            workflow.engine_factory();artifacts.assert_called_once();private.assert_not_called()

    def test_runtime_composition_passes_trusted_application_addons_root(self):
        import sys
        from resources.lib.create_workflow import runtime_create_workflow
        bundled = self.base / 'xbmc-addons'
        def translate(uri):
            if uri == 'special://xbmc/addons':
                return str(bundled)
            return str(self.base / uri.replace('special://', '').replace('/', '-'))
        modules = {'xbmc': SimpleNamespace(executeJSONRPC=lambda raw: json.dumps({'result': {}})),
                   'xbmcvfs': SimpleNamespace(translatePath=translate)}
        with patch.dict(sys.modules, modules), patch('resources.lib.frozen.KodiInventoryBackend') as backend, \
             patch('resources.lib.inspector.KodiStateInspector'), patch('resources.lib.artifacts.ArtifactStore'), \
             patch('resources.lib.private_overlay.PrivateOverlayStore'):
            runtime_create_workflow()
        self.assertEqual(backend.call_args.kwargs['application_addons_dir'], bundled)

    def test_runtime_composition_fails_closed_without_absolute_application_root(self):
        import sys
        from resources.lib.create_workflow import CreateValidationError, runtime_create_workflow
        def translate(uri):
            if uri == 'special://xbmc/addons':
                return 'relative/xbmc-addons'
            return str(self.base / uri.replace('special://', '').replace('/', '-'))
        modules = {'xbmc': SimpleNamespace(executeJSONRPC=lambda raw: json.dumps({'result': {}})),
                   'xbmcvfs': SimpleNamespace(translatePath=translate)}
        with patch.dict(sys.modules, modules), patch('resources.lib.frozen.KodiInventoryBackend') as backend, \
             patch('resources.lib.inspector.KodiStateInspector'), patch('resources.lib.artifacts.ArtifactStore'), \
             patch('resources.lib.private_overlay.PrivateOverlayStore'):
            with self.assertRaises(CreateValidationError):
                runtime_create_workflow()
        backend.assert_not_called()

    def test_localization_required(self):
        po=(Path(__file__).parents[1]/'resources/language/resource.language.en_gb/strings.po').read_text()
        for identifier in (*range(32700,32726),*range(32730,32740)):
            self.assertIn('msgctxt "#%d"'%identifier,po)
        self.assertNotIn(SECRET,po)

if __name__=='__main__':unittest.main()
