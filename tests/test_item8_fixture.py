"""Offline qualification admission; real pinned public bytes, no Kodi runtime."""
import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import os
import sys
import unittest
from unittest.mock import patch
import uuid

from tools import bm_item8_fixture as q
from resources.lib.build_library import (BuildLibrary, LibraryInstallTarget, LibrarySource,
    isolated_library_install_authority)
from resources.lib.frozen_install import validate_frozen_install_plan
from resources.lib.plan import ReadOnlyArtifactStore
from resources.lib.private_overlay import PrivateOverlayStore
from resources.lib.private_resource import StructuredPrivateValue


@unittest.skipUnless(q.ARCHIVE.is_dir() and q.PIL_XML.is_file(), 'pinned local archive/bundled PIL required')
class Item8FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen, cls.blobs = q.validate_inputs(q.ARCHIVE, q.PIL_XML)

    def setUp(self):
        self.output = Path('/private/tmp') / ('bm-item8-test-' + uuid.uuid4().hex)

    def tearDown(self):
        if self.output.is_symlink():
            self.output.unlink()
        elif self.output.exists():
            shutil.rmtree(self.output)

    def prepare(self):
        return q.prepare(archive=q.ARCHIVE, pil_xml=q.PIL_XML, output=self.output)

    def test_real_public_closure_and_platform_semantics(self):
        self.assertEqual(len(self.blobs), 6)
        nodes = {n.addon_id: n for n in self.frozen.addons}
        for aid, data in self.blobs.items():
            self.assertEqual(hashlib.sha256(data).hexdigest(), q.PACKAGES[aid][1])
        self.assertEqual(set(nodes), set(q.PACKAGES) | {'script.module.pil', 'xbmc.python'})
        self.assertTrue(nodes['script.module.pil'].platform_provided)
        self.assertIsNone(nodes['script.module.pil'].artifact)
        record = self.prepare()
        plan = validate_frozen_install_plan(self.frozen, ReadOnlyArtifactStore(self.output/'artifacts-store'))
        self.assertEqual(len(plan.strict_plan.install_order), 7)  # Python is a system requirement.
        self.assertEqual(record['software_fingerprint'], self.frozen.fingerprint())

    def test_library_target_binding_and_no_runtime_records(self):
        record = self.prepare()
        library = BuildLibrary(str(self.output/'library'))
        target = LibraryInstallTarget(LibrarySource(library.root, record['entry_id']), q.PROFILE)
        with isolated_library_install_authority(library):
            target.load()
            for bad in [replace(target, device_profile_id='wrong'),
                        replace(target, source=replace(target.source, entry_id='0'*64))]:
                with self.assertRaises(Exception): bad.load()
        self.assertIsNone(library.current_applied_association())
        self.assertIsNone(library.pending_publication())
        names = {p.name for p in self.output.rglob('*')}
        self.assertFalse(any('transaction' in n or 'activation' in n or 'applied' in n for n in names))
        overlay = PrivateOverlayStore(self.output/'profile').load(q.OVERLAY)
        q.validate_authored_overlay(self.frozen, overlay)
        self.assertEqual(overlay.target_build_id, 'sha256:'+self.frozen.fingerprint())
        self.assertNotIn('empty_setting', (self.output/'provenance.json').read_text())

    def test_corrupt_or_substituted_package_rejected_before_output(self):
        original = q._read
        for replacement in [b'corrupt zip', self.blobs['script.module.requests']]:
            def read(path, limit):
                if path.name == q.PACKAGES['plugin.video.redlight'][1]+'.zip': return replacement
                return original(path, limit)
            with patch.object(q, '_read', side_effect=read):
                with self.assertRaises(Exception): self.prepare()
            self.assertFalse(self.output.exists())

    def test_wrong_platform_identity_version_type_or_dependency_refused(self):
        original = q._read
        xml = original(q.PIL_XML, 1024*1024)
        for bad in [xml.replace(b'5.1.0', b'1.0.0'), xml.replace(b'script.module.pil', b'script.module.other'),
                    xml.replace(b'xbmc.python.module', b'xbmc.python.script'), xml.replace(b'3.0.0', b'9.0.0')]:
            def read(path, limit): return bad if path == q.PIL_XML else original(path, limit)
            with patch.object(q, '_read', side_effect=read):
                with self.assertRaises(Exception): self.prepare()
            self.assertFalse(self.output.exists())

    def test_overlay_rejects_credentials_tokens_owner_schema_field_and_graph(self):
        _, overlay = q.material(self.frozen)
        resource = overlay.resources[0]
        bad_resources = [replace(resource, owner_addon_id='plugin.video.other'),
            replace(resource, schema_id='wrong'), replace(resource, addon_version='2.6.9'),
            replace(resource, values=(StructuredPrivateValue('pm.token','string','test-not-a-real-token'),)),
            replace(resource, values=(StructuredPrivateValue('pm.account_id','string','someone-private'),)),
            replace(resource, values=(StructuredPrivateValue('not.declared','string','value'),))]
        for bad in [replace(overlay, overlay_id='wrong'), replace(overlay, target_build_id='sha256:'+'0'*64),
                    *[replace(overlay, resources=(r,)) for r in bad_resources]]:
            with self.assertRaises(Exception): q.validate_authored_overlay(self.frozen, bad)
        changed = replace(self.frozen, addons=self.frozen.addons[:-1])
        with self.assertRaises(Exception): q.validate_authored_overlay(changed, overlay)

    def test_missing_or_incompatible_dependency_is_not_complete(self):
        self.prepare()
        store=ReadOnlyArtifactStore(self.output/'artifacts-store')
        root=next(n for n in self.frozen.addons if n.addon_id=='plugin.video.redlight')
        for dependency in ['script.module.pil','script.module.requests','xbmc.python']:
            with self.assertRaises(Exception):
                bad=replace(self.frozen,addons=tuple(n for n in self.frozen.addons if n.addon_id!=dependency))
                validate_frozen_install_plan(bad,store)
        edges=tuple(replace(e,min_version='99.0.0') if e.addon_id=='script.module.requests' else e
                    for e in root.dependency_edges)
        bad=replace(self.frozen,addons=tuple(replace(n,dependency_edges=edges) if n==root else n
                                            for n in self.frozen.addons))
        with self.assertRaises(Exception):q.validate_dependency_requirements(bad)

    def test_prepared_public_bundle_rejects_private_payload(self):
        from resources.lib.create_capture import PreparedPublicBundle
        bundle,_=q.material(self.frozen)
        bad=bundle.to_dict();bad['manifest']['private_overlay']['values']={'token':'not-a-real-token'}
        with self.assertRaises(Exception):PreparedPublicBundle(json.dumps(bad))
        bad=bundle.to_dict();bad['frozen']['source']['metadata']={'private':'not-a-real-secret'}
        with self.assertRaises(Exception):PreparedPublicBundle(json.dumps(bad))

    def test_production_plan_blocks_unverified_builtin_in_registered_legacy_fixture(self):
        from tests.test_plan import PlanHarness
        from resources.lib.frozen import InstalledMetadata, InstalledOrigin
        from resources.lib.frozen_install import InMemoryFrozenArtifactBackend, FrozenInstalledAddon
        record=self.prepare()
        h=PlanHarness(self,with_private=False,with_resource=False)
        bundle,_=q.material(self.frozen)
        h.desired=q.resolve_manifest(q.validate_manifest(bundle.to_dict()['manifest']),q.PROFILE)
        h.frozen=self.frozen
        backend=InMemoryFrozenArtifactBackend()
        for aid,version in [('script.module.pil','5.1.0'),('xbmc.python','3.0.0')]:
            backend.installed[aid]=FrozenInstalledAddon(aid,version,True)
            h.kodi.addons[aid]=(version,True)
            h.deps.installed[aid]=(version,True)
        backend.platform_metadata['script.module.pil']=InstalledMetadata(q.PIL_XML.read_bytes(),InstalledOrigin.APPLICATION)
        library=BuildLibrary(str(self.output/'library'))
        overlay_store=PrivateOverlayStore(self.output/'profile')
        owners=h.owners(overlay_loader=overlay_store.read_snapshot)
        from resources.lib.plan import BuildPlanService, PlanOwners
        service=BuildPlanService(PlanOwners(owners,ReadOnlyArtifactStore(self.output/'artifacts-store'),
                                           h.details,backend))
        plan=service.preview(library.plan_target(record['entry_id'],q.PROFILE))
        # Registration and exact artifacts do not establish native builtin
        # authority or the missing core closure of this historical fixture.
        self.assertTrue(plan.blockers)
        self.assertIsNone(plan.review,plan.to_safe_dict())

    def test_unsafe_and_profile_paths_rejected_before_any_read(self):
        for output in [Path('relative'), Path('/Applications/Kodi Build Manager Test.app/Contents/Resources/Kodi/portable_data'),
                       Path('/private/tmp/elsewhere'), Path('/private/tmp/bm-item8-x/../escape')]:
            with patch.object(q, 'validate_inputs', side_effect=AssertionError('must not read')):
                with self.assertRaises(Exception): q.prepare(archive=q.ARCHIVE, pil_xml=q.PIL_XML, output=output)
        with patch.object(q, '_read', side_effect=AssertionError('must not read')):
            for archive in [Path('/Applications/Kodi.app'),Path('/Applications/Kodi Build Manager Test.app/Contents/Resources/Kodi/portable_data.bm-original-f8e47c62a19b43d0b75609a26c1e8f34')]:
                with self.assertRaises(Exception):q.validate_inputs(archive, q.PIL_XML)

    def test_symlink_input_and_output_refused(self):
        with tempfile.TemporaryDirectory(prefix='bm-item8-links-',dir='/private/tmp') as d:
            p=Path(d); (p/'link').symlink_to(p/'target'); (p/'target').write_bytes(b'x')
            with self.assertRaises(Exception): q._read(p/'link', 50)
            (p/'ancestor').symlink_to(p,target_is_directory=True)
            with self.assertRaises(Exception):q._read(p/'ancestor'/'target',50)
            self.output.symlink_to(p,target_is_directory=True)
            with self.assertRaises(Exception):self.prepare()
            self.assertEqual((p/'target').read_bytes(),b'x')

    def test_repeat_preserves_library_and_evidence(self):
        self.prepare()
        before={str(p.relative_to(self.output)):p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        with self.assertRaises(FileExistsError): self.prepare()
        after={str(p.relative_to(self.output)):p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_interruption_retains_incomplete_unselected_output_and_refuses_retry(self):
        with patch.object(q.PrivateOverlayStore,'save',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):self.prepare()
        self.assertTrue(self.output.is_dir())
        library=BuildLibrary(str(self.output/'library'))
        self.assertEqual(len(library.list_builds()),1)
        self.assertFalse((self.output/'provenance.json').exists())
        self.assertFalse((self.output/'library/selection.json').exists())
        with self.assertRaises(FileExistsError): self.prepare()

    def test_no_capture_or_runtime_api_calls_in_preparer(self):
        tree=ast.parse(Path(q.__file__).read_text())
        calls={n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id
               for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,(ast.Attribute,ast.Name))}
        self.assertFalse(calls & {'capture','competing_operation','verify_restart','install_target',
                                'set_addon_enabled','record_applied','transition_expected'})

    def test_absolute_write_targets_are_only_owned_temporary_roots(self):
        # Initialize stdlib's temp-directory discovery before auditing this
        # operation; its one-time write/delete probe is not fixture output.
        scratch_prefix=str(Path(tempfile.gettempdir()).resolve()/'bm-create-public-')
        events=[]
        active=[True]
        def audit(event,args):
            if not active[0]:return
            if event=='open' and isinstance(args[0],str) and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT):
                events.append(args[0])
            elif event=='os.mkdir' and isinstance(args[0],str):events.append(args[0])
        sys.addaudithook(audit)
        try:self.prepare()
        finally:active[0]=False
        for name in events:
            if os.path.isabs(name):
                name=str(Path(name).resolve())
                self.assertTrue(name.startswith(str(self.output)+'/') or name==str(self.output)
                                or name.startswith(scratch_prefix),name)

    def test_package_auth_guard_rejects_the_selected_unauthenticated_sentinel(self):
        import io,zipfile
        with zipfile.ZipFile(io.BytesIO(self.blobs['plugin.video.redlight'])) as z:
            source=z.read('plugin.video.redlight/resources/lib/modules/settings.py').decode()
        module=ast.parse(source)
        node=next(n for n in module.body if isinstance(n,ast.FunctionDef)
                  and n.name=='authorized_debrid_check')
        # Execute only the audited three-line pure predicate, never the package
        # module, imports, service, initializer or any networking implementation.
        scope={'get_setting':lambda key:'empty_setting'}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<public auth predicate>','exec'),scope)
        self.assertFalse(scope['authorized_debrid_check']('pm'))


if __name__ == '__main__': unittest.main()
