"""D-028 builtin authority regressions using disposable pinned roots and Kodi API fakes."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import replace

from resources.lib.frozen import (AddonCaptureNode, CaptureStatus, DependencyEdge,
    FrozenBuildManifest, ProvenanceStatus)
from resources.lib.frozen_install import (KodiRuntimeFrozenArtifactBackend,
    FrozenPlatformRequirementError, _builtin_satisfies, verify_platform_requirements)

BUILTIN = '''<addon id="xbmc.python" version="3.0.1"><backwards-compatibility abi="3.0.0"/>
<requires><import addon="xbmc.core" version="0.1.0"/></requires>
<extension-point id="script" schema="script.xsd"/></addon>'''
PIL = '''<addon id="script.module.pil" version="5.1.0"><requires>
<import addon="xbmc.python" version="3.0.0"/></requires>
<extension point="xbmc.python.module" library="lib"/></addon>'''


class BuiltinAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root/'home/addons'
        self.app = self.root/'application/addons'
        self.home.mkdir(parents=True)
        self.app.mkdir(parents=True)
        self.file = self.app/'xbmc.python/addon.xml'
        self.file.parent.mkdir()
        self.file.write_text(BUILTIN)
        pil = self.app/'script.module.pil/addon.xml'
        pil.parent.mkdir()
        pil.write_text(PIL)
        self.info = {'id':'xbmc.python', 'version':'3.0.1',
                     'path':str(self.file.parent)+'/', 'type':'unknown'}
        self.conditions = {'System.HasAddon(xbmc.python)':True,
                           'System.AddonIsEnabled(xbmc.python)':True}
        self.api = SimpleNamespace(Addon=lambda aid:SimpleNamespace(getAddonInfo=self.info.__getitem__))
        self.addCleanup(patch.stopall)
        patch.dict('sys.modules', {'xbmcaddon':self.api}).start()
        self.backend = KodiRuntimeFrozenArtifactBackend()
        self.addCleanup(self.backend.close)
        self.backend._addons_dir = lambda:self.home
        self.backend._application_addons_dir = lambda:self.app
        self.xbmc = SimpleNamespace(getCondVisibility=self.conditions.__getitem__)
        self.backend._xbmc = lambda:self.xbmc
        self.calls = []
        def rpc(method, params):
            self.calls.append((method,params))
            if method=='Addons.GetAddons':
                return {'result':{'addons':[{'addonid':'script.module.pil',
                    'path':str(pil.parent), 'enabled':True,'broken':False,'version':'5.1.0'}]}}
            if params.get('addonid')=='script.module.pil':
                return {'result':{'addon':{'addonid':'script.module.pil',
                    'enabled':True,'broken':False,'version':'5.1.0'}}}
            return {'error':{'code':-32602,'message':'Invalid params.'}}
        self.backend._rpc = rpc
        self.edge = DependencyEdge('xbmc.python','3.0.0')

    def satisfies(self, version=None):
        edge=self.edge if version is None else replace(self.edge,min_version=version)
        return _builtin_satisfies(self.backend,edge)

    def test_supported_api_and_pinned_xml_verify_builtin_despite_jsonrpc_invalid_params(self):
        self.assertTrue(self.satisfies())
        self.assertTrue(self.satisfies('3.0.1'))
        self.assertFalse(any(p.get('addonid')=='xbmc.python' for _,p in self.calls))

    def test_production_platform_verifier_uses_builtin_authority_and_rechecks_enabled(self):
        node=AddonCaptureNode('script.module.pil','5.1.0','xbmc.python.module',True,
            ProvenanceStatus.UNKNOWN, dependency_edges=(self.edge,),
            status=CaptureStatus.PLATFORM_PROVIDED,platform_provided=True)
        manifest=FrozenBuildManifest(2,'probe','probe','2026-10-09T00:00:00Z','21.3','macos',
            CaptureStatus.COMPLETE,(node,))
        plan=SimpleNamespace(manifest=manifest,nodes={node.addon_id:node})
        # Python's native proof does not prove its mandatory core provider.
        # This formerly passed without a captured builtin closure.
        with self.assertRaises(FrozenPlatformRequirementError):
            verify_platform_requirements(plan,self.backend,planned_versions={})
        self.conditions['System.AddonIsEnabled(xbmc.python)']=False
        with self.assertRaises(FrozenPlatformRequirementError):
            verify_platform_requirements(plan,self.backend,planned_versions={})

    def test_api_identity_version_type_and_origin_must_match(self):
        for key,value in [('id','xbmc.gui'),('version','3.0.0'),('version','bad'),
            ('type','xbmc.python.module'),('path',str(self.home/'xbmc.python')),
            ('path','special://home/addons/xbmc.python'),('path','relative/path'),
            ('path',str(self.app/'xbmc.python-evil')),('path',None)]:
            with self.subTest(key=key,value=value):
                old=self.info[key];self.info[key]=value
                self.assertFalse(self.satisfies());self.info[key]=old

    def test_missing_disabled_or_non_boolean_availability_is_unverifiable(self):
        for key in self.conditions:
            for value in (False,None,1,'true'):
                with self.subTest(key=key,value=value):
                    self.conditions[key]=value;self.assertFalse(self.satisfies())
            self.conditions[key]=True

    def test_api_unavailable_or_error_fails_closed(self):
        def fail(aid):raise RuntimeError('unsupported')
        self.api.Addon=fail
        self.assertFalse(self.satisfies())

    def test_first_addon_construction_cannot_replace_unpinned_application_root(self):
        self.assertIsNone(self.backend._inventory_backend)
        replaced = False

        def construct(aid):
            nonlocal replaced
            if not replaced:
                replaced = True
                self.app.rename(self.app.with_name('retained-application'))
                replacement = self.app/'xbmc.python/addon.xml'
                replacement.parent.mkdir(parents=True)
                replacement.write_text(BUILTIN)
            return SimpleNamespace(getAddonInfo=self.info.__getitem__)

        self.api.Addon = construct
        self.assertFalse(self.satisfies())
        self.assertTrue(replaced)

    def test_missing_or_unreadable_xml_blocks_despite_api_proof(self):
        self.file.unlink();self.assertFalse(self.satisfies())
        self.file.write_text(BUILTIN)
        # OS-independent read denial, including runners with elevated privileges.
        with patch('resources.lib.frozen.read_regular_file',side_effect=PermissionError):
            self.assertFalse(self.satisfies())

    def test_malformed_identity_abi_and_extension_metadata_fail_closed(self):
        cases=['<addon',BUILTIN.replace('id="xbmc.python"','id="xbmc.gui"'),
            BUILTIN.replace('version="3.0.1"','version="3.0.0"',1),
            BUILTIN.replace('abi="3.0.0"','abi="unknown"'),
            BUILTIN.replace('abi="3.0.0"','abi="4.0.0"'),
            BUILTIN.replace('<backwards-compatibility abi="3.0.0"/>',''),
            BUILTIN.replace('<backwards-compatibility abi="3.0.0"/>',
                '<backwards-compatibility abi="3.0.0"/>'*2),
            BUILTIN.replace('id="script"','id="plugin"'),
            BUILTIN.replace('schema="script.xsd"','schema="other.xsd"'),
            BUILTIN.replace('</addon>','<extension point="xbmc.addon.metadata"><broken>broken</broken></extension></addon>')]
        for text in cases:
            with self.subTest(text=text):
                self.file.write_text(text);self.assertFalse(self.satisfies())

    def test_incompatible_unknown_or_unspecified_requirement_is_not_admitted(self):
        for value in ('2.26.0','3.0.2','4.0.0','bad','', ' '):
            with self.subTest(value=value):self.assertFalse(self.satisfies(value))

    def test_declared_python2_api_is_not_usable_on_python3(self):
        self.info['version']='2.26.0'
        self.file.write_text(BUILTIN.replace('3.0.1','2.26.0').replace('3.0.0','2.0.0'))
        self.assertFalse(self.satisfies('2.26.0'))

    def test_home_shadow_of_any_kind_blocks_application_builtin(self):
        shadow=self.home/'xbmc.python'
        for kind in ('directory','file','symlink','dangling'):
            with self.subTest(kind=kind):
                if kind=='directory':shadow.mkdir()
                elif kind=='file':shadow.write_text('shadow')
                else:shadow.symlink_to(self.file.parent if kind=='symlink' else self.root/'missing')
                self.assertFalse(self.satisfies())
                if kind=='directory':shadow.rmdir()
                else:shadow.unlink()

    def test_symlink_xml_or_builtin_directory_is_rejected(self):
        outside=self.root/'outside.xml';outside.write_text(BUILTIN)
        self.file.unlink();self.file.symlink_to(outside)
        self.assertFalse(self.satisfies())
        self.file.unlink();self.file.write_text(BUILTIN)
        moved=self.root/'moved-builtin';self.file.parent.rename(moved)
        self.file.parent.symlink_to(moved,target_is_directory=True)
        self.assertFalse(self.satisfies())

    def test_missing_application_or_home_root_fails_closed(self):
        self.backend._application_addons_dir=lambda:self.root/'missing-app'
        self.assertFalse(self.satisfies())

    def test_missing_home_root_cannot_prove_absence_of_shadow(self):
        self.backend._addons_dir=lambda:self.root/'missing-home'
        self.assertFalse(self.satisfies())

    def test_shadow_introduced_during_metadata_read_is_rejected(self):
        from resources.lib.frozen import read_regular_file
        def read_then_shadow(*args, **kwargs):
            data=read_regular_file(*args, **kwargs)
            (self.home/'xbmc.python').mkdir()
            return data
        with patch('resources.lib.frozen.read_regular_file',side_effect=read_then_shadow):
            self.assertFalse(self.satisfies())

    def test_runtime_identity_change_during_proof_fails_closed(self):
        from resources.lib.frozen import read_regular_file
        def read_then_change(*args, **kwargs):
            data=read_regular_file(*args, **kwargs)
            self.info['version']='3.0.2'
            return data
        with patch('resources.lib.frozen.read_regular_file',side_effect=read_then_change):
            self.assertFalse(self.satisfies())

    def test_abi_floor_above_requested_version_is_incompatible(self):
        self.file.write_text(BUILTIN.replace('abi="3.0.0"','abi="3.0.1"'))
        self.assertFalse(self.satisfies('3.0.0'))
        self.assertTrue(self.satisfies('3.0.1'))

    def test_untrusted_root_cannot_be_created_later_to_grant_authority(self):
        missing=self.root/'later-app'
        self.backend._application_addons_dir=lambda:missing
        self.assertFalse(self.satisfies())
        p=missing/'xbmc.python/addon.xml';p.parent.mkdir(parents=True);p.write_text(BUILTIN)
        self.info['path']=str(p.parent)
        self.assertFalse(self.satisfies())

    def test_nonregular_or_oversized_metadata_is_unverifiable(self):
        from resources.lib.frozen import _ADDON_XML_LIMIT
        self.file.write_bytes(b' ' * (_ADDON_XML_LIMIT+1))
        self.assertFalse(self.satisfies())
        self.file.unlink();os.mkfifo(self.file)
        self.assertFalse(self.satisfies())

    def test_application_root_replacement_after_proof_is_rejected(self):
        self.assertTrue(self.satisfies())
        moved=self.app.with_name('old');self.app.rename(moved);self.app.mkdir()
        p=self.app/'xbmc.python/addon.xml';p.parent.mkdir();p.write_text(BUILTIN)
        self.assertFalse(self.satisfies())

    def test_ancestor_symlink_substitution_after_proof_is_rejected(self):
        self.assertTrue(self.satisfies())
        ancestor=self.app.parent;moved=ancestor.with_name('old-app');ancestor.rename(moved)
        ancestor.symlink_to(moved,target_is_directory=True)
        self.assertFalse(self.satisfies())

    def test_home_root_substitution_after_proof_is_rejected(self):
        self.assertTrue(self.satisfies())
        moved=self.home.with_name('old');self.home.rename(moved);self.home.mkdir()
        self.assertFalse(self.satisfies())

    def test_closed_pinned_authority_cannot_be_reestablished(self):
        self.assertTrue(self.satisfies());self.backend.close()
        self.assertFalse(self.satisfies())

    def test_other_unproven_builtin_does_not_use_dependency_declarations(self):
        self.assertFalse(_builtin_satisfies(self.backend,DependencyEdge('xbmc.core','0.1.0')))

    def test_runtime_python_major_must_match_builtin_api(self):
        with patch('sys.version_info',SimpleNamespace(major=2)):
            self.assertFalse(self.satisfies())

    def _platform_probe(self):
        node = AddonCaptureNode('script.module.pil', '5.1.0', 'xbmc.python.module', True,
            ProvenanceStatus.UNKNOWN, dependency_edges=(self.edge,),
            status=CaptureStatus.PLATFORM_PROVIDED, platform_provided=True)
        manifest = FrozenBuildManifest(2, 'probe', 'probe', '2026-10-09T00:00:00Z',
            '21.3', 'macos', CaptureStatus.COMPLETE, (node,))
        return verify_platform_requirements(SimpleNamespace(manifest=manifest,
            nodes={node.addon_id: node}), self.backend, planned_versions={})

    def _during_read(self, change):
        from resources.lib.frozen import read_regular_file
        changed = False
        def read_then_change(*args, **kwargs):
            nonlocal changed
            data = read_regular_file(*args, **kwargs)
            if not changed and os.stat(args[0], dir_fd=kwargs["dir_fd"]).st_ino == self.file.stat().st_ino:
                changed = True
                change()
            return data
        return patch('resources.lib.frozen.read_regular_file', side_effect=read_then_change)

    def test_same_attempt_application_root_replacement(self):
        def change():
            self.app.rename(self.app.with_name('retained'))
            self.file.parent.mkdir(parents=True)
            self.file.write_text(BUILTIN)
        with self._during_read(change):
            self.assertFalse(self.satisfies())

    def test_same_attempt_application_root_symlink_substitution(self):
        def change():
            retained = self.app.with_name('retained')
            self.app.rename(retained)
            self.app.symlink_to(retained, target_is_directory=True)
        with self._during_read(change):
            self.assertFalse(self.satisfies())

    def test_same_attempt_atomic_xml_substitution(self):
        def change():
            replacement = self.file.with_name('replacement.xml')
            replacement.write_text(BUILTIN.replace('abi="3.0.0"', 'abi="4.0.0"'))
            replacement.replace(self.file)
        with self._during_read(change):
            self.assertFalse(self.satisfies())

    def test_same_attempt_equal_bytes_xml_replacement(self):
        def change():
            replacement = self.file.with_name('replacement.xml')
            replacement.write_text(BUILTIN)
            replacement.replace(self.file)
        with self._during_read(change):
            self.assertFalse(self.satisfies())

    def _snapshot_registry(self):
        def construct(aid):
            snapshot = dict(self.info)
            return SimpleNamespace(getAddonInfo=snapshot.__getitem__)
        self.api.Addon = construct

    def test_same_attempt_snapshot_handle_registry_version_change(self):
        self._snapshot_registry()
        with self._during_read(lambda: self.info.update(version='3.0.2')):
            self.assertFalse(self.satisfies())

    def test_production_caller_rejects_snapshot_registry_substitution(self):
        self._snapshot_registry()
        with self._during_read(lambda: self.info.update(version='3.0.2')):
            with self.assertRaises(FrozenPlatformRequirementError):
                self._platform_probe()

    def test_fresh_registry_fields_and_enabled_state_are_required(self):
        self._snapshot_registry()
        for key, value in [('id', 'xbmc.gui'), ('type', 'xbmc.python.module'),
                           ('path', str(self.home/'xbmc.python'))]:
            with self.subTest(key=key):
                original = self.info[key]
                with self._during_read(lambda: self.info.update({key: value})):
                    self.assertFalse(self.satisfies())
                self.info[key] = original
        with self._during_read(lambda: self.conditions.update(
                {'System.AddonIsEnabled(xbmc.python)': False})):
            self.assertFalse(self.satisfies())

    def test_fresh_registry_authority_unavailable_fails_closed(self):
        self._snapshot_registry()
        def unavailable(aid):
            raise RuntimeError('registry unavailable')
        with self._during_read(lambda: setattr(self.api, 'Addon', unavailable)):
            self.assertFalse(self.satisfies())

    def test_filesystem_substitution_during_fresh_registry_check_is_rejected(self):
        constructions = 0
        def construct(aid):
            nonlocal constructions
            constructions += 1
            snapshot = dict(self.info)
            if constructions == 2:
                replacement = self.file.with_name('replacement.xml')
                replacement.write_text(BUILTIN.replace('abi="3.0.0"', 'abi="4.0.0"'))
                replacement.replace(self.file)
            return SimpleNamespace(getAddonInfo=snapshot.__getitem__)
        self.api.Addon = construct
        self.assertFalse(self.satisfies())
        self.assertEqual(constructions, 2)
