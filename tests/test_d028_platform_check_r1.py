"""Execution-window identity controls, using deterministic synthetic invocations."""
import ast
import builtins
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import bm_test_app as host
from tests import test_d028_platform_check as platform_tests
from tests.test_d028_platform_check_b1_b2 import execute, rebind_driver, snapshot

Fixture = platform_tests.Fixture
PROJECT = platform_tests.PROJECT
BASE = 'b4c6bf34bc912815f3d0f1e63456c01c0f1d7268'


def baseline_runner():
    source=subprocess.check_output(['git','show',BASE+':tools/bm_test_app.py'],cwd=PROJECT,text=True)
    function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='run_adapter')
    namespace=dict(host.__dict__)
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<rejected R1 host baseline>','exec'),namespace)
    return namespace['run_adapter']


def change_driver(world,kind):
    folder=world.target.addon_dir(host.DRIVER_ID)
    if kind in ('config','entry','support','addon','bundled','mode','mtime','atomic-new','atomic-original'):
        name={'config':'adapter_config.py','support':'adapter_support.py','addon':'addon.xml',
              'bundled':'bundled_frozen_install.py'}.get(kind,'default.py')
        path=folder/name
        original=path.read_bytes();before=path.stat()
        if kind=='mode':
            path.chmod(0o600);path.chmod(before.st_mode & 0o777)
        elif kind=='atomic-original':
            backup=folder/'.retained-source';path.rename(backup)
            path.write_bytes(original+b'\n# transient replacement\n');path.unlink();backup.rename(path)
        elif kind=='atomic-new':
            temporary=folder/'.replacement';temporary.write_bytes(original+b'\n# transient replacement\n')
            os.replace(temporary,path);path.write_bytes(original)
        else:
            path.write_bytes(original+b'\n# transient source\n');path.write_bytes(original)
        os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        assert path.read_bytes()==original and path.stat().st_mtime_ns==before.st_mtime_ns
        assert path.stat().st_ctime_ns!=before.st_ctime_ns
    elif kind=='injected-module':
        path=folder/'tempfile.py';path.write_text('IMPORTED_TRANSIENT_SOURCE = True\n')
        spec=importlib.util.spec_from_file_location('_synthetic_transient_driver_module',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        assert module.IMPORTED_TRANSIENT_SOURCE is True
        path.unlink()
    elif kind in ('driver-directory','parent-directory','ancestor-directory'):
        directory=folder if kind=='driver-directory' else folder.parent if kind=='parent-directory' else world.target.portable_data
        before=directory.stat();retained=directory.with_name(directory.name+'-retained')
        directory.rename(retained);retained.rename(directory)
        assert directory.stat().st_ino==before.st_ino and directory.stat().st_ctime_ns!=before.st_ctime_ns
    elif kind=='new-parent-inode':
        parent=folder.parent;retained=parent.with_name(parent.name+'-retained')
        parent.rename(retained);shutil.copytree(retained,parent)
    else:raise AssertionError(kind)


class R1World(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform_tests.PlatformHostTests.setUpClass();cls.world=platform_tests.PlatformHostTests.world

    @classmethod
    def tearDownClass(cls):platform_tests.PlatformHostTests.tearDownClass()

    setup_world=platform_tests.PlatformHostTests.setup_world

    def invoke(self,kind=None,*,runner=None,hook=None):
        world,result=self.setup_world();original=world.transport.execute_hook
        def during(params):
            original(params)
            if kind:change_driver(world,kind)
            if hook:hook(world)
        world.transport.execute_hook=during
        world.produce_on_sleep(result)
        report=(runner or host.run_adapter)(world.services,mode='platform_check',manifest=world.manifest,
            manifest_sha256='f'*64,rpc={'port':8080},git_repo=self.world.FIXTURE.repo,timeout=10)
        return world,report


class OriginalR1Reproductions(R1World):
    def test_rejected_host_accepts_transient_modifications_with_matching_restored_bytes(self):
        for kind in ('config','entry','injected-module','atomic-original'):
            world,report=self.invoke(kind,runner=baseline_runner())
            self.assertTrue(report['ok'],report)
            self.assertEqual('requirements_verified',report['result']['platform_check']['overall'])
            self.assertTrue(report['post_run_verification']['installed_equals_manifest'])
            print('R1_ORIGINAL_REPRODUCED '+kind+' host_ok=True restored_content=True matching_identity=True',flush=True)


class InvocationWitnessTests(R1World):
    def test_unchanged_driver_with_valid_result_succeeds(self):
        _,report=self.invoke();self.assertTrue(report['ok'],report)

    def test_all_transient_file_and_directory_changes_prevent_host_success(self):
        for kind in ('config','entry','support','addon','bundled','mode','injected-module','atomic-new','atomic-original','mtime',
                     'driver-directory','parent-directory','ancestor-directory','new-parent-inode'):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(host.HelperError,'platform_source_'):self.invoke(kind)

    def test_unavailable_identity_refuses_before_execution_and_after_fresh_result(self):
        original_snapshot=host._platform_invocation_snapshot
        original_fstat=os.fstat
        fields=('st_dev','st_ino','st_mode','st_size','st_ctime_ns','st_mtime_ns')
        for phase in ('before','after'):
            for field,value in (('st_ctime_ns',None),('st_ctime_ns',1_000_000_000),
                                ('st_mtime_ns',None),('st_ino',0)):
                calls=[];executed=[]
                def unavailable(fd):
                    info=original_fstat(fd)
                    values={name:getattr(info,name) for name in fields}
                    if value is None:values.pop(field)
                    else:values[field]=value
                    return SimpleNamespace(**values)
                def observe(target,manifest):
                    calls.append(True)
                    if len(calls)==(1 if phase=='before' else 2):
                        with patch.object(host.os,'fstat',unavailable):
                            return original_snapshot(target,manifest)
                    return original_snapshot(target,manifest)
                with self.subTest(phase=phase,field=field,value=value), \
                        patch.object(host,'_platform_invocation_snapshot',observe):
                    with self.assertRaisesRegex(host.HelperError,'platform_source_unverifiable'):
                        self.invoke(hook=lambda world:executed.append(True))
                    self.assertEqual([] if phase=='before' else [True],executed)

    def test_witness_is_read_only_and_includes_all_five_files(self):
        world,_=self.setup_world();before=snapshot(world.target.root)
        witness=host._platform_invocation_snapshot(world.target,world.manifest)
        self.assertEqual(before,snapshot(world.target.root))
        self.assertEqual(sorted(host.DRIVER_FILES),[name for name,_ in witness[1]])
        self.assertEqual(witness,host._platform_invocation_snapshot(world.target,world.manifest))


class DriverIsolationTests(unittest.TestCase):
    def test_driver_tempfile_and_aliases_cannot_supply_unscoped_imports(self):
        for alias in ('direct','relative','symlink','descendant','symlink-descendant','symlink-parent','cwd'):
            f=Fixture(self);folder=f.driver
            if alias=='symlink':
                folder=f.native.root/'driver-alias';folder.symlink_to(f.driver,target_is_directory=True)
            elif alias in ('descendant','symlink-descendant'):
                folder=f.driver/'unscoped';folder.mkdir()
                if alias=='symlink-descendant':
                    link=f.native.root/'descendant-alias';link.symlink_to(folder,target_is_directory=True);folder=link
            path=folder/'tempfile.py';path.write_text('import builtins\nbuiltins._r1_imports.append("driver-tempfile")\n')
            previous=sys.modules.pop('tempfile',None)
            previous_cwd=os.getcwd()
            try:
                with patch.object(builtins,'_r1_imports',[],create=True) as imported:
                    prefix=os.path.relpath(folder) if alias=='relative' else str(folder)
                    if alias=='symlink-parent':
                        side=f.driver.parent/'side';side.mkdir()
                        link=f.native.root/'redirect';link.symlink_to(side,target_is_directory=True)
                        (f.native.root/f.driver.name).mkdir()  # lexical normalization decoy
                        prefix=str(link)+'/../'+f.driver.name
                    if alias=='cwd':os.chdir(folder);prefix=''
                    result=execute(f,search_prefix=prefix)
                    self.assertEqual([],imported)
                self.assertTrue(result['ok'],result)
            finally:
                os.chdir(previous_cwd)
                sys.modules.pop('tempfile',None)
                if previous is not None:sys.modules['tempfile']=previous

    def test_missing_bootstrap_authority_refuses_and_restores_interpreter(self):
        f=Fixture(self);before=snapshot(f.native.root)
        code=compile((f.driver/'default.py').read_bytes(),str(f.driver/'default.py'),'exec')
        def direct_entry(path,**kwargs):exec(code,{'__file__':path,'__name__':'__main__'})
        # runpy itself needs os before executing the entrypoint. Compile first
        # and execute those same bytes to exercise the entrypoint's own refusal.
        with patch.dict(sys.modules,{'os':None}), \
                patch('tests.test_d028_platform_check_b1_b2.runpy.run_path',direct_entry):
            with self.assertRaisesRegex(ImportError,'import isolation unavailable'):execute(f)
        self.assertEqual(before,snapshot(f.native.root))


class R1MutationTests(unittest.TestCase):
    def assert_detection(self,case,label):
        result=unittest.TestResult();case.run(result)
        self.assertEqual([],result.errors,str(result.errors))
        self.assertEqual([],result.skipped)
        self.assertGreater(len(result.failures),0,'removed R1 control escaped behavioral assertions')
        print('PLATFORM_R1_MUTATION_ASSERTION_PASS '+label,flush=True)

    def test_removing_host_witness_admits_transient_sources_and_is_detected(self):
        # A constant witness models removal of all independent ctime/identity
        # authority. The real RPC/result/Git/tree path still runs.
        case=InvocationWitnessTests('test_all_transient_file_and_directory_changes_prevent_host_success')
        type(case).setUpClass()
        try:
            with patch.object(host,'_platform_invocation_snapshot',return_value=()):
                self.assert_detection(case,'host_invocation_identity')
        finally:type(case).tearDownClass()

    def test_restoring_driver_import_precedence_executes_marker_and_is_detected(self):
        original=Fixture.__init__
        def mutated(f,owner,*args,**kwargs):
            original(f,owner,*args,**kwargs)
            path=f.driver/'default.py';source=path.read_text()
            before='sys.path[:] = [entry for entry in sys.path if _platform_import_path_allowed(entry)]'
            self.assertEqual(1,source.count(before))
            path.write_text(source.replace(before,'sys.path[:] = _PREVIOUS_SYS_PATH'));rebind_driver(f)
        with patch.object(Fixture,'__init__',mutated):
            self.assert_detection(DriverIsolationTests('test_driver_tempfile_and_aliases_cannot_supply_unscoped_imports'),
                'driver_unscoped_import_isolation')


class OriginalImportReproduction(unittest.TestCase):
    def test_rejected_entrypoint_imports_driver_local_tempfile(self):
        f=Fixture(self)
        (f.driver/'default.py').write_bytes(subprocess.check_output(['git','show',BASE+':tools/bm023a_adapter/default.py.in'],cwd=PROJECT))
        rebind_driver(f)
        (f.driver/'tempfile.py').write_text('import builtins\nbuiltins._r1_imports.append("driver-tempfile")\n')
        previous=sys.modules.pop('tempfile',None)
        try:
            with patch.object(builtins,'_r1_imports',[],create=True) as imported:
                result=execute(f);self.assertEqual(['driver-tempfile'],imported)
            self.assertTrue(result['ok'],result)
            print('R1_ORIGINAL_IMPORT_REPRODUCED driver_tempfile_executed=True diagnostic_ok=True',flush=True)
        finally:
            sys.modules.pop('tempfile',None)
            if previous is not None:sys.modules['tempfile']=previous
