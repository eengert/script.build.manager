"""Isolated workflow fixtures and fault injection. Never execute a live builder."""
import copy
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib
from xml.etree import ElementTree as ET

from tools import bm_release_workflow as w
from tools import bm_release_source as s

PRIVATE = 'synthetic-private-exception-928'


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Public pinned Git inputs, read only. Every adversarial mutation below
        # affects only independent scratch fixtures or test-local return values.
        cls.data, cls.manifest = s.admit(w.REPOSITORY, w.MANIFEST)
        cls.auth = w.authenticate()

    def setUp(self):
        self.roots = []
        self.addCleanup(self.clean_roots)
        self.patch_export = mock.patch.object(s, 'export', side_effect=self.fixture_export)
        self.patch_verify = mock.patch.object(s, 'verify_export', side_effect=self.fixture_verify)
        self.patch_export.start(); self.addCleanup(self.patch_export.stop)
        self.patch_verify.start(); self.addCleanup(self.patch_verify.stop)

    def clean_roots(self):
        for work in self.roots:
            if work['root'].exists(): w.cleanup(work)

    def fixture_export(self, repository, manifest, output):
        output.mkdir(mode=0o700)
        with s.directory(output) as fd:
            for name, body in s.expected_export(self.data, self.manifest)[0].items(): s.put(fd, name, body)
        return self.fixture_verify(repository, manifest, output)

    def fixture_verify(self, repository, manifest, output):
        expected, dirs = s.expected_export(self.data, self.manifest)
        with s.directory(output) as fd: files, actual_dirs = s.scan(fd)
        s.need(set(files) == set(expected) and dirs == actual_dirs, 'test_export_members')
        s.need(all(files[n][0] == b for n, b in expected.items()), 'test_export_bytes')
        return {'ok': True, 'publication_authorized': False}

    def workspace(self):
        work = w.allocate(); self.roots.append(work)
        w.create_workspace(work, *self.auth)
        return work

    def refused(self, function):
        with self.assertRaises((s.Refusal, OSError, ValueError, zipfile.BadZipFile, zlib.error)):
            function()

    @staticmethod
    def zip_bytes(mapping, mode=stat.S_IFREG | 0o644, duplicate=False):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(mapping.items()):
                item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); item.create_system = 3
                item.compress_type = zipfile.ZIP_DEFLATED; item.external_attr = mode << 16
                archive.writestr(item, raw)
            if duplicate:
                # Duplicate warning intentionally captured, not a skipped test.
                import warnings
                with warnings.catch_warnings(record=True): archive.writestr(item, raw)
        return out.getvalue()

    def outputs(self, work):
        expected, _, _, fixture = self.auth
        xml = ET.fromstring(expected['addon.xml']); xml.set('version', w.VERSION)
        addon = w.xml_bytes(xml)
        package = self.zip_bytes({w.PRODUCT+'/'+n: addon if n=='addon.xml' else b for n,b in expected.items()})
        self.assertEqual(w.digest(package), w.ZIP_SHA256); self.assertEqual(len(package), w.ZIP_SIZE)
        repo_zip = self.zip_bytes({w.REPO+'/addon.xml': fixture})
        index = ET.Element('addons'); index.append(ET.fromstring(fixture)); index.append(ET.fromstring(addon)); raw_index=w.xml_bytes(index)
        import hashlib
        files = {w.REPO+'/addon.xml': fixture,
                 'omega/zips/'+w.PRODUCT+'/'+w.PRODUCT+'-0.1.0.zip': package,
                 'omega/zips/'+w.PRODUCT+'/addon.xml': addon,
                 'omega/zips/'+w.PRODUCT+'/resources/images/icon.png': expected['resources/images/icon.png'],
                 'omega/zips/'+w.REPO+'/'+w.REPO+'-1.0.0.zip': repo_zip,
                 'omega/zips/'+w.REPO+'/addon.xml': fixture,
                 w.REPO+'-1.0.0.zip': repo_zip, 'omega/zips/addons.xml': raw_index,
                 'omega/zips/addons.xml.md5': hashlib.md5(raw_index).hexdigest().encode()}
        for name, body in files.items():
            p=work['repo']/name;p.parent.mkdir(parents=True,exist_ok=True)
            if p.exists(): p.write_bytes(body)
            else: w.write(p,body)
        return work['repo']/('omega/zips/'+w.PRODUCT+'/'+w.PRODUCT+'-0.1.0.zip')

    def test_fixed_CLI_has_no_source_version_or_publication_overrides(self):
        for args in ([],['rehearse','--source','/private/tmp/source'],['rehearse','--version','9.0.0'],['publish']):
            captured=[]
            with mock.patch.object(w,'rehearse') as op, mock.patch.object(w.os,'write',side_effect=lambda fd,b:captured.append(b) or len(b)):
                self.assertEqual(w.main(args),2);op.assert_not_called()
            self.assertFalse(json.loads(b''.join(captured))['publication_authorized'])

    def test_source_builder_fixture_and_release_pins_fail_closed(self):
        # Independent trusted bytes retained from the real public pin, not export.
        def git(repo,*args):
            if args[0]=='rev-parse': return (w.BUILDER_BLOB+'\n').encode()
            return self.auth[2] if args[0]=='cat-file' else self.auth[3]
        for pin in ('PRODUCT_TREE','SOURCE_MANIFEST','RELEASE_MANIFEST','BUILDER_SHA256','FIXTURE_SHA256','ICON_SHA256'):
            with self.subTest(pin=pin), mock.patch.object(s,'admit',return_value=(self.data,self.manifest)), \
                 mock.patch.object(s,'git',side_effect=git), mock.patch.object(w,'read',return_value=(self.auth[2],())), \
                 mock.patch.object(w,pin,'0'*64):
                self.refused(w.authenticate)

    def test_builder_blob_and_live_builder_substitution_refused(self):
        def git(repo,*args):
            if args[0]=='rev-parse': return (w.BUILDER_BLOB+'\n').encode()
            return self.auth[2] if args[0]=='cat-file' else self.auth[3]
        with mock.patch.object(s,'admit',return_value=(self.data,self.manifest)), mock.patch.object(s,'git',side_effect=git):
            with mock.patch.object(w,'BUILDER_BLOB','0'*40): self.refused(w.authenticate)
            with mock.patch.object(w,'read',return_value=(b'changed',())): self.refused(w.authenticate)

    def test_builder_repository_symlink_refused_before_Git_access(self):
        work=self.workspace();link=work['root']/'repository-link';link.symlink_to(work['repo'],target_is_directory=True)
        try:
            with mock.patch.object(w,'BUILDER_REPOSITORY',link), \
                 mock.patch.object(s,'admit',return_value=(self.data,self.manifest)),mock.patch.object(s,'git') as git:
                self.refused(w.authenticate);git.assert_not_called()
        finally:link.unlink()

    def test_changed_extra_missing_authenticated_source_refused(self):
        for mode in ('changed','extra','missing'):
            data=dict(self.data)
            if mode=='changed':data['default.py']=PRIVATE.encode()
            elif mode=='extra':data['.credentials']=PRIVATE.encode()
            else:data.pop('default.py')
            with self.subTest(mode=mode), mock.patch.object(s,'admit',return_value=(data,self.manifest)):
                self.refused(w.authenticate)

    def test_export_mutation_before_execution_refused(self):
        for mode in ('change','extra','missing'):
            work=self.workspace();target=work['product']/'default.py'
            if mode=='change':target.write_text(PRIVATE)
            elif mode=='extra':(work['product']/'.credentials').write_text(PRIVATE)
            else:target.unlink()
            self.refused(lambda:w.check_inputs(work,self.auth[0],self.manifest))

    def test_development_checkout_substitution_refused(self):
        work=self.workspace();fake=work['root']/'development';fake.mkdir();(fake/'.git').mkdir();(fake/'default.py').write_text(PRIVATE)
        work['product']=fake;self.refused(lambda:w.check_inputs(work,self.auth[0],self.manifest))

    def test_builder_policy_fixture_mutation_refused(self):
        for kind in ('builder','policy','fixture'):
            work=self.workspace();p=work['repo']/w.REPO/'addon.xml' if kind=='fixture' else work[kind]
            p.write_text(PRIVATE);self.refused(lambda:w.check_inputs(work,self.auth[0],self.manifest))

    def test_builder_same_byte_identity_replacement_refused(self):
        work=self.workspace();p=work['builder'];raw=p.read_bytes();p.unlink();w.write(p,raw,0o700)
        self.refused(lambda:w.check_inputs(work,self.auth[0],self.manifest))

    def test_symlink_hardlink_and_existing_output_refused(self):
        work=self.workspace();p=work['product']/'default.py';raw=p.read_bytes();p.unlink();p.symlink_to(work['builder'])
        try:self.refused(lambda:w.check_inputs(work,self.auth[0],self.manifest))
        finally:p.unlink();p.write_bytes(raw);p.chmod(0o644)
        other=work['root']/'hardlink';os.link(p,other)
        try:self.refused(lambda:w.check_inputs(work,self.auth[0],self.manifest))
        finally:other.unlink()
        (work['repo']/'omega').mkdir();self.refused(lambda:w.check_inputs(work,self.auth[0],self.manifest))

    def test_workspace_boundary_substitution_and_cleanup_refusal(self):
        work=self.workspace();original=work['identity'];work['identity']=(0,0)
        try:self.refused(lambda:w.cleanup(work))
        finally:work['identity']=original
        other=work['root']/'link';other.symlink_to('/private/tmp')
        try:self.refused(lambda:w.cleanup(work))
        finally:other.unlink()
        self.assertTrue(work['root'].exists())

    def test_actual_policy_only_allows_repository_writes_and_denies_network(self):
        work=self.workspace();text=work['policy'].read_text()
        self.assertIn('(deny network*)',text);self.assertIn('(deny file-write*)',text)
        self.assertEqual(text.count('(allow file-write*'),1)
        self.assertIn(json.dumps(str(work['repo'])),text)
        self.assertNotIn('(allow file-write* (subpath '+json.dumps(str(work['root'])),text)
        self.assertEqual(w.environment(work['tmp'])['TMPDIR'],str(work['repo']/'tmp'))
        self.assertNotIn('PYTHONPATH',w.environment(work['tmp']))

    def test_ineffective_or_unavailable_sandbox_refused(self):
        work=self.workspace()
        with mock.patch.object(w,'run',return_value=(1,b'',b'unavailable')):self.refused(lambda:w.confinement(work))
        for label in ('outside','source','builder','network','allowed'):
            for role in ('parent','inherited'):
                checks=dict(outside=True,source=True,builder=True,network=True,allowed=True)
                proof=dict(checks,inherited=dict(checks))
                (proof if role=='parent' else proof['inherited'])[label]=False
                with self.subTest(label=label,role=role),mock.patch.object(w,'run',return_value=(0,json.dumps(proof).encode(),b'')):
                    self.refused(lambda:w.confinement(work))

    def test_successful_preflight_requires_parent_and_inherited_checks(self):
        work=self.workspace();checks=dict(outside=True,source=True,builder=True,network=True,allowed=True)
        with mock.patch.object(w,'run',return_value=(0,json.dumps(dict(checks,inherited=checks)).encode(),b'')):
            proof=w.confinement(work)
        self.assertEqual(proof['kernel_checks']['inherited'],checks)
        self.assertFalse(proof['protected_paths_probed'])

    def test_archive_extras_missing_duplicates_modes_and_wrong_bytes(self):
        expected={'script.build.manager/default.py':b'expected'}
        for raw in (self.zip_bytes(dict(expected,extra=b'x')),self.zip_bytes({}),
                    self.zip_bytes(expected,duplicate=True),self.zip_bytes(expected,mode=stat.S_IFLNK|0o777),
                    self.zip_bytes(expected,mode=stat.S_IFREG|0o777),self.zip_bytes({'../escape':b'expected'}),
                    self.zip_bytes({'script.build.manager/default.py':b'changed'})):
            self.refused(lambda:w.archive(raw,expected))

    def test_CRC_corruption_refused(self):
        expected={'script.build.manager/default.py':b'expected'*80};raw=bytearray(self.zip_bytes(expected))
        with zipfile.ZipFile(io.BytesIO(raw)) as z:i=z.infolist()[0]
        offset=i.header_offset+30+len(i.filename.encode())+len(i.extra);raw[offset]^=255
        self.refused(lambda:w.archive(bytes(raw),expected))

    def test_independent_full_output_verification(self):
        work=self.workspace();self.outputs(work);result=w.verify_outputs(work,self.auth[0],self.auth[3])
        self.assertEqual(result['package_sha256'],w.ZIP_SHA256);self.assertEqual(result['package_members'],75)
        self.assertEqual(len(result['output_inventory']),9)

    def test_wrong_XML_assets_index_checksum_and_repository_copy_refused(self):
        for name in ('omega/zips/script.build.manager/addon.xml',
                     'omega/zips/script.build.manager/resources/images/icon.png','omega/zips/addons.xml',
                     'omega/zips/addons.xml.md5','repository.eengert-1.0.0.zip'):
            work=self.workspace();self.outputs(work);(work['repo']/name).write_bytes(b'wrong')
            self.refused(lambda:w.verify_outputs(work,self.auth[0],self.auth[3]))

    def test_partial_extra_outputs_and_wrong_pin_refused(self):
        work=self.workspace();self.refused(lambda:w.verify_outputs(work,self.auth[0],self.auth[3]))
        self.outputs(work);(work['repo']/'extra').write_text(PRIVATE)
        self.refused(lambda:w.verify_outputs(work,self.auth[0],self.auth[3]));(work['repo']/'extra').unlink()
        with mock.patch.object(w,'ZIP_SHA256','0'*64):self.refused(lambda:w.verify_outputs(work,self.auth[0],self.auth[3]))
        (work['repo']/'empty-unexpected-directory').mkdir()
        self.refused(lambda:w.verify_outputs(work,self.auth[0],self.auth[3]))

    def test_wrong_XML_inside_archive_is_not_hidden_by_new_hash(self):
        work=self.workspace();p=self.outputs(work)
        with zipfile.ZipFile(p) as archive:files={n:archive.read(n) for n in archive.namelist()}
        files[w.PRODUCT+'/addon.xml']=b'<addon id="wrong" version="0.1.0"/>'
        raw=self.zip_bytes(files);p.write_bytes(raw)
        with mock.patch.object(w,'ZIP_SHA256',w.digest(raw)),mock.patch.object(w,'ZIP_SIZE',len(raw)):
            self.refused(lambda:w.verify_outputs(work,self.auth[0],self.auth[3]))

    def test_output_identity_race_is_refused(self):
        work=self.workspace();self.outputs(work);original=w.tree;calls=0
        def race(path):
            nonlocal calls
            value=original(path);calls+=1
            if calls==1:
                p=work['repo']/'omega/zips/addons.xml';raw=p.read_bytes();p.unlink();p.write_bytes(raw)
            return value
        with mock.patch.object(w,'tree',side_effect=race):self.refused(lambda:w.verify_outputs(work,self.auth[0],self.auth[3]))

    def pipeline(self, fail=None):
        work=self.workspace();events=[];original_cleanup=w.cleanup
        def check(*a):
            events.append('check')
            if fail=='mutation' and len(events)>2:raise s.Refusal('mutation')
        def preflight(*a):
            events.append('confinement')
            if fail=='confinement':raise s.Refusal('confinement')
            return {'synthetic_unit_proof':True}
        def execute(*a):
            events.append('builder')
            if fail=='timeout':raise s.Refusal('child_timeout')
            return (2 if fail=='nonzero' else 0),b'',b''
        def finalize(*a):
            events.append('cleanup')
            if fail=='cleanup':raise OSError(PRIVATE)
            original_cleanup(work)
            if fail=='cleanup_after':raise OSError(PRIVATE)
        with mock.patch.object(w,'authenticate',return_value=self.auth),mock.patch.object(w,'allocate',return_value=work), \
             mock.patch.object(w,'create_workspace'),mock.patch.object(w,'check_inputs',side_effect=check), \
             mock.patch.object(w,'confinement',side_effect=preflight),mock.patch.object(w,'run',side_effect=execute), \
             mock.patch.object(w,'verify_outputs',return_value={'verified':True}),mock.patch.object(w,'cleanup',side_effect=finalize):
            # Capture original cleanup before the mock to avoid recursion.
            result=w.rehearse()
        return result,events

    def test_no_builder_before_successful_confinement(self):
        result,events=self.pipeline('confinement');self.assertFalse(result['ok']);self.assertNotIn('builder',events)
        self.assertFalse(result['publication_authorized']);self.assertNotIn(PRIVATE,json.dumps(result))

    def test_success_record_only_after_verification_and_cleanup(self):
        result,events=self.pipeline()
        self.assertTrue(result['ok']);self.assertFalse(result['publication_authorized'])
        self.assertEqual(result['phase'],'complete');self.assertEqual(result['cleanup'],'complete')
        self.assertLess(events.index('confinement'),events.index('builder'))
        self.assertEqual(events[-1],'cleanup')

    def test_mutation_timeout_nonzero_and_finalization_never_emit_success(self):
        for fault in ('mutation','timeout','nonzero','cleanup','cleanup_after'):
            with self.subTest(fault=fault):
                result,events=self.pipeline(fault);self.assertFalse(result['ok']);self.assertFalse(result['publication_authorized'])
                self.assertNotIn(PRIVATE,json.dumps(result))
                self.assertEqual(result['partial_state'],'unverified')

    def test_managed_child_timeout(self):
        # Task-owned toy child only, never a builder or native process probe.
        with self.assertRaisesRegex(s.Refusal,'^child_timeout$'):
            w.run([w.PYTHON,'-B','-c','import time;time.sleep(20)'],Path('/private/tmp'),w.environment('/private/tmp'),0.1)
