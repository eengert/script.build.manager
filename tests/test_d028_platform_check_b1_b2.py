"""B1/B2 transport corrections: real import machinery, synthetic Kodi only."""
import builtins
from contextlib import nullcontext
import ctypes
import hashlib
import importlib.util
import json
import marshal
from pathlib import Path
import struct
import subprocess
import runpy
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from tests.test_d028_platform_check import Fixture, PROJECT, snapshot
from tools import bm_test_app as host

BASE = '8d1d0f05a7335fa153f79f49535fe2a9101d8e0e'


def original_driver(fixture):
    # Retain an executable reproduction tied to the rejected commit, never HEAD.
    for name, source in (('default.py','tools/bm023a_adapter/default.py.in'),
                         ('adapter_support.py','tools/bm023a_adapter_support.py')):
        (fixture.driver/name).write_bytes(subprocess.check_output(
            ['git','show',BASE+':'+source],cwd=PROJECT))
    binding=json.loads(fixture.binding)
    for name in binding['adapter']:
        binding['adapter'][name]=hashlib.sha256((fixture.driver/name).read_bytes()).hexdigest()
    fixture.binding=json.dumps(binding,sort_keys=True,separators=(',',':'))
    config=fixture.driver/'adapter_config.py'
    values=host._parse_adapter_config(config.read_bytes())
    values['PLATFORM_SOURCE_BINDING']=fixture.binding
    config.write_text(''.join(key+' = '+repr(value)+'\n' for key,value in values.items()))


def plant_pyc(path, substituted_source, *, adjacent=False):
    info=path.stat()
    code=compile(substituted_source,str(path),'exec')
    raw=importlib.util.MAGIC_NUMBER+struct.pack('<III',0,int(info.st_mtime),info.st_size)+marshal.dumps(code)
    cache=path.with_suffix('.pyc') if adjacent else Path(importlib.util.cache_from_source(str(path)))
    cache.parent.mkdir(exist_ok=True)
    cache.write_bytes(raw)
    return cache


def driver_tree(fixture):
    entries=[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size}
        for p in sorted(fixture.driver.iterdir()) if p.is_file()]
    return {'addon_id':host.DRIVER_ID,'files':entries,
        'tree_sha256':host.tree_digest((x['path'],x['sha256'],x['size']) for x in entries)}


def observe_support(fixture):
    seen=[];original=builtins.__import__
    def imported(name,*args,**kwargs):
        module=original(name,*args,**kwargs)
        if name=='adapter_support':seen.append(module.ADAPTER_VERSION)
        return module
    with patch.object(builtins,'__import__',side_effect=imported):result=fixture.entrypoint()
    return result,seen


class OriginalFailureReproductions(unittest.TestCase):
    def test_b1_matching_pyc_executes_while_source_and_tree_match_rejected_candidate(self):
        f=Fixture(self);original_driver(f)
        path=f.driver/'adapter_support.py';source=path.read_bytes();tree=driver_tree(f)
        self.assertTrue(host.verify_tree_dir(f.driver,tree,'sha1')['ok'])
        plant_pyc(path,source.replace(b'ADAPTER_VERSION = "0.0.16"',b'ADAPTER_VERSION = "9.9.99"'))
        self.assertTrue(host.verify_tree_dir(f.driver,tree,'sha1')['ok'])
        result,seen=observe_support(f)
        self.assertIn('9.9.99',seen);self.assertEqual(source,path.read_bytes())
        self.assertTrue(result['ok'],result)
        self.assertEqual(hashlib.sha256(f.binding.encode('ascii')).hexdigest(),
            result['platform_check']['source']['binding_sha256'])
        print('B1_ORIGINAL_REPRODUCED matching_pyc=9.9.99 source_and_tree_match=True requirements_verified=True',flush=True)

    def test_b2_malformed_prefix_reaches_legacy_writer_on_rejected_candidate(self):
        for token in ('platform_checkx','platform_check;install','?mode=platform_check&x=1'):
            f=Fixture(self);original_driver(f);f.data.rmdir()
            result=f.entrypoint(token)
            self.assertFalse(result['ok']);self.assertEqual('unselected',result['adapter_mode'])
            self.assertTrue(f.data.is_dir());self.assertTrue((f.data/'bm023a_live_result.json').is_file())
            print('B2_ORIGINAL_REPRODUCED '+token+' legacy_result_directory_created=True',flush=True)


def rebind_driver(f):
    binding=json.loads(f.binding)
    for name in binding['adapter']:
        binding['adapter'][name]=hashlib.sha256((f.driver/name).read_bytes()).hexdigest()
    f.binding=json.dumps(binding,sort_keys=True,separators=(',',':'))
    path=f.driver/'adapter_config.py';values=host._parse_adapter_config(path.read_bytes())
    values['PLATFORM_SOURCE_BINDING']=f.binding
    path.write_text(''.join(key+' = '+repr(value)+'\n' for key,value in values.items()))


def scoped(name):
    return name in ('adapter_support','adapter_config','resources') or name.startswith('resources.')


def execute(f, arguments=('platform_check',), *, real_resources=False, preloaded=None, bytecode=False, search_prefix=None):
    """Use the real entrypoint/import machinery; assert restoration before cleanup."""
    saved={name:sys.modules.pop(name) for name in list(sys.modules) if scoped(name)}
    original_path=list(sys.path);original_argv=sys.argv
    xbmc=ModuleType('xbmc');calls=[]
    def rpc(raw):
        request=json.loads(raw);calls.append(request['method'])
        return json.dumps({'result':{}})
    xbmc.executeJSONRPC=rpc
    vfs=ModuleType('xbmcvfs')
    paths={'special://profile/':f.profile,'special://home/addons':f.native.home,
        'special://home/addons/script.build.manager':f.addon,'special://xbmc/addons':f.native.app}
    vfs.translatePath=lambda name:str(paths[name])
    try:
        sys.path.insert(0,str(f.driver));sys.argv=[str(f.driver/'default.py'),*arguments]
        if search_prefix is not None:sys.path.insert(0,search_prefix)
        with patch.dict(sys.modules,{'xbmc':xbmc,'xbmcvfs':vfs,**(preloaded or {})}), \
                patch.object(sys,'dont_write_bytecode',bytecode), \
                patch.object(ctypes,'CDLL',side_effect=AssertionError('no native process query')):
            path_before=list(sys.path);meta_before=list(sys.meta_path);prefix_before=sys.pycache_prefix
            modules_before={name:mod for name,mod in sys.modules.items() if scoped(name)}
            with nullcontext() if real_resources else f.imports(cache=True):
                try:
                    runpy.run_path(str(f.driver/'default.py'),run_name='__main__')
                finally:
                    f.case.assertEqual(bytecode,sys.dont_write_bytecode)
                    f.case.assertEqual(path_before,sys.path)
                    f.case.assertEqual(meta_before,sys.meta_path)
                    f.case.assertEqual(prefix_before,sys.pycache_prefix)
                    f.case.assertEqual(modules_before,{name:mod for name,mod in sys.modules.items() if scoped(name)})
                    f.case.assertLessEqual(set(calls),{'Application.GetProperties','Addons.GetAddons','Addons.GetAddonDetails'})
    finally:
        sys.path[:]=original_path;sys.argv=original_argv
        for name in list(sys.modules):
            if scoped(name):sys.modules.pop(name,None)
        sys.modules.update(saved)
    return json.loads((f.data/'bm023a_live_result.json').read_text())


class SourceBoundaryTests(unittest.TestCase):
    def test_matching_driver_cache_cannot_substitute_executed_support(self):
        f=Fixture(self);path=f.driver/'adapter_support.py';source=path.read_bytes();tree=driver_tree(f)
        plant_pyc(path,source.replace(b'ADAPTER_VERSION = "0.0.16"',b'ADAPTER_VERSION = "9.9.99"'))
        before=snapshot(f.native.root)
        self.assertTrue(host.verify_tree_dir(f.driver,tree,'sha1')['ok'])
        result,seen=observe_support(f)
        self.assertTrue(seen);self.assertEqual({'0.0.16'},set(seen))
        self.assertTrue(result['ok'],result)
        self.assertEqual(hashlib.sha256(f.binding.encode('ascii')).hexdigest(),
            result['platform_check']['source']['binding_sha256'])
        after=snapshot(f.native.root)
        after.pop(str((f.data/'bm023a_live_result.json').relative_to(f.native.root)))
        self.assertEqual(before,after)

    def test_adapter_config_cache_is_ignored(self):
        f=Fixture(self);path=f.driver/'adapter_config.py'
        code=path.read_bytes()+b'\nimport builtins\nbuiltins._d028_cache_executions.append("config")\n'
        plant_pyc(path,code)
        with patch.object(builtins,'_d028_cache_executions',[],create=True) as executed:
            result=execute(f);self.assertEqual([],executed)
        self.assertTrue(result['ok'],result)

    def test_real_production_imports_ignore_matching_cache_for_all_product_python(self):
        f=Fixture(self);binding=json.loads(f.binding);planted=[]
        for relative in binding['product']:
            if not relative.startswith('resources/') or not relative.endswith('.py'):continue
            path=f.addon/relative
            code=path.read_bytes()+b'\nimport builtins\nbuiltins._d028_cache_executions.append("production")\n'
            planted.append(plant_pyc(path,code))
        self.assertGreater(len(planted),10)
        before={str(p):p.read_bytes() for p in planted}
        loaded={};original=importlib.import_module
        def observed(name,*args,**kwargs):
            module=original(name,*args,**kwargs)
            if name.startswith('resources.'):
                loaded[name]=type(module.__loader__).__name__
            return module
        with patch.object(builtins,'_d028_cache_executions',[],create=True) as executed:
            with patch.object(importlib,'import_module',side_effect=observed):
                result=execute(f,real_resources=True)
            self.assertEqual([],executed)
        for name in ('resources.lib','resources.lib.frozen_install','resources.lib.frozen','resources.lib.artifacts'):
            self.assertEqual('_PlatformSourceLoader',loaded[name])
        self.assertFalse(result['ok'])  # Synthetic native API deliberately has no runtime authority.
        self.assertIsNotNone(result['platform_check']['source'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in planted})

    def test_sourceless_driver_and_production_cache_cannot_supply_code(self):
        for target in ('adapter_config.py','adapter_support.py','resources/lib/__init__.py'):
            f=Fixture(self)
            path=f.addon/target if target.startswith('resources/') else f.driver/target
            plant_pyc(path,b'import builtins\nbuiltins._d028_cache_executions.append("sourceless")\n',adjacent=True)
            path.unlink()
            with patch.object(builtins,'_d028_cache_executions',[],create=True) as executed:
                if target.startswith('resources/'):
                    result=execute(f,real_resources=True);self.assertFalse(result['ok'])
                else:
                    with self.assertRaises((FileNotFoundError,ImportError)):execute(f)
                self.assertEqual([],executed)

    def test_alternate_sourceless_search_path_does_not_override_fixed_sources(self):
        f=Fixture(self);folder=f.native.root/'untrusted-bytecode';folder.mkdir()
        path=folder/'adapter_support.py';path.write_text('unused source')
        plant_pyc(path,b'import builtins\nbuiltins._d028_cache_executions.append("alternate")\n',adjacent=True)
        path.unlink()
        with patch.object(builtins,'_d028_cache_executions',[],create=True) as executed, \
                patch.object(sys,'path',[str(folder),*sys.path]):
            result=execute(f,search_prefix=str(folder));self.assertEqual([],executed)
        self.assertTrue(result['ok'],result)

    def test_preloaded_driver_package_and_transitive_modules_refuse_and_are_preserved(self):
        for name in ('adapter_support','adapter_config','resources','resources.lib',
                     'resources.lib.frozen_install','resources.lib.frozen','resources.lib.dependencies'):
            f=Fixture(self);module=ModuleType(name);before=snapshot(f.native.root)
            with self.assertRaisesRegex(ImportError,'preloaded module refused'):
                execute(f,preloaded={name:module})
            self.assertEqual(before,snapshot(f.native.root))

    def test_benign_cache_and_exact_forms_succeed_without_cache_writes(self):
        for token in ('platform_check','?mode=platform_check'):
            f=Fixture(self)
            for path in (f.driver/'adapter_support.py',f.driver/'adapter_config.py'):
                plant_pyc(path,path.read_bytes())
            before=snapshot(f.native.root)
            result=execute(f,(token,),bytecode=True)
            self.assertTrue(result['ok'],result)
            self.assertEqual('not_qualified',result['platform_check']['qualification'])
            self.assertEqual('requirements_verified',result['platform_check']['overall'])
            after=snapshot(f.native.root)
            after.pop(str((f.data/'bm023a_live_result.json').relative_to(f.native.root)))
            self.assertEqual(before,after)

    def test_changed_source_is_refused_before_execution_and_state_restores(self):
        f=Fixture(self);path=f.driver/'adapter_support.py'
        path.write_bytes(path.read_bytes()+b'\nimport builtins\nbuiltins._d028_cache_executions.append("changed-source")\n')
        with patch.object(builtins,'_d028_cache_executions',[],create=True) as executed:
            with self.assertRaisesRegex(ImportError,'source identity refused'):execute(f)
            self.assertEqual([],executed)
        self.assertFalse((f.data/'bm023a_live_result.json').exists())

    def test_failed_product_import_restores_state_without_native_or_cache_execution(self):
        f=Fixture(self);(f.addon/'resources/lib/__init__.py').unlink()
        result=execute(f,real_resources=True)
        self.assertFalse(result['ok']);self.assertNotIn('platform_check',result)

    def test_failed_result_write_restores_state_and_preserves_missing_directory(self):
        f=Fixture(self);f.data.rmdir();before=snapshot(f.native.root)
        with self.assertRaises(FileNotFoundError):execute(f)
        self.assertFalse(f.data.exists());self.assertEqual(before,snapshot(f.native.root))


MALFORMED = ('platform_checkx','platform_check;install','?mode=platform_check&x=1',
    'platform_check/../install','platform_check?install','platform_check\ninstall',
    '?mode=platform_check;install','?mode=platform_checkx','platform_check!',
    ['platform_check','install'],['?mode=platform_check','install'])


class MalformedBoundaryTests(unittest.TestCase):
    def test_malformed_prefix_preserves_existing_result_and_never_enters_writer(self):
        for token in MALFORMED:
            with self.subTest(token=token):
                f=Fixture(self);result=f.data/'bm023a_live_result.json'
                original=b'{"existing_result": "preserve byte for byte"}\n';result.write_bytes(original)
                before=snapshot(f.native.root);stamp=result.stat().st_mtime_ns
                arguments=[token] if isinstance(token,str) else token
                with patch.object(Path,'mkdir',side_effect=AssertionError('legacy writer reached')):
                    with self.assertRaises(SystemExit):execute(f,arguments)
                self.assertEqual(original,result.read_bytes());self.assertEqual(stamp,result.stat().st_mtime_ns)
                self.assertEqual(before,snapshot(f.native.root));self.assertEqual(0,f.factory_calls)

    def test_malformed_prefix_preserves_missing_result_parent_and_no_imports(self):
        for token in MALFORMED:
            f=Fixture(self);f.data.rmdir();before=snapshot(f.native.root)
            arguments=[token] if isinstance(token,str) else token
            with patch.object(Path,'mkdir',side_effect=AssertionError('legacy writer reached')):
                with self.assertRaises(SystemExit):execute(f,arguments)
            self.assertFalse(f.data.exists());self.assertEqual(before,snapshot(f.native.root))
            self.assertEqual(0,f.factory_calls)


# Exact current gate condition; a missing/changed anchor is a setup error.
B2_CONDITION = 'sys.argv[1:] not in (["platform_check"], ["?mode=platform_check"], ["af3_fixture"],\n                                  ["?mode=af3_fixture"], ["af3_fixture_verify"], ["?mode=af3_fixture_verify"], ["auto_keep"], ["?mode=auto_keep"])'


class CorrectionMutationTests(unittest.TestCase):
    def detected(self,before,after,case,label,expected_failure):
        original=Fixture.__init__
        # Check outside case.run(): an anchor assertion must not masquerade as
        # the behavioral failure that this detector is intended to observe.
        probe=Fixture(self)
        if (probe.driver/'default.py').read_text().count(before)!=1:
            raise ValueError('mutation anchor missing or ambiguous')
        applied=[]
        def mutated(f,owner,*args,**kwargs):
            original(f,owner,*args,**kwargs)
            path=f.driver/'default.py';source=path.read_text()
            if source.count(before)!=1:
                raise ValueError('mutation anchor missing or ambiguous')
            path.write_text(source.replace(before,after,1));rebind_driver(f)
            applied.append(True)
        with patch.object(Fixture,'__init__',mutated):
            result=unittest.TestResult();case.run(result)
        self.assertTrue(applied,'mutation was never applied')
        self.assertEqual(1,result.testsRun)
        self.assertEqual([],result.errors,str(result.errors));self.assertEqual([],result.skipped)
        self.assertGreater(len(result.failures),0,'removed correction escaped behavioral assertions')
        self.assertTrue(all(expected_failure in failure for _,failure in result.failures),
                        'intended behavioral security assertion did not detect mutation')
        print('PLATFORM_B1_B2_MUTATION_ASSERTION_PASS '+label,flush=True)

    def test_bytecode_cache_fallback_removal_of_source_boundary_is_detected(self):
        self.detected('return self.source_to_code(data, self.path)',
            'return super().get_code(fullname)',
            SourceBoundaryTests('test_matching_driver_cache_cannot_substitute_executed_support'),'B1_source_only_loader',
            "self.assertTrue(seen);self.assertEqual({'0.0.16'},set(seen))")

    def test_early_argument_refusal_removal_is_detected(self):
        self.detected(B2_CONDITION,'False',
            MalformedBoundaryTests('test_malformed_prefix_preserves_existing_result_and_never_enters_writer'),
            'B2_no_write_argument_boundary','AssertionError: SystemExit not raised')

    def test_missing_anchor_is_setup_failure_not_detection(self):
        case=unittest.FunctionTestCase(lambda: self.fail('behavior must not run'))
        with patch.object(case,'run',wraps=case.run) as run:
            with self.assertRaisesRegex(ValueError,'mutation anchor'):
                self.detected('OBSOLETE_MISSING_ANCHOR','False',case,'missing','legacy writer reached')
            run.assert_not_called()

    def test_unrelated_assertion_is_not_behavioral_detection(self):
        def unrelated():
            Fixture(self)
            self.fail('unrelated assertion')
        with self.assertRaisesRegex(AssertionError,'intended behavioral'):
            self.detected(B2_CONDITION,'False',unittest.FunctionTestCase(unrelated),
                          'unrelated','AssertionError: SystemExit not raised')

    def test_noop_mutation_is_not_behavioral_detection(self):
        with self.assertRaisesRegex(AssertionError,'removed correction escaped'):
            self.detected(B2_CONDITION,B2_CONDITION,
                MalformedBoundaryTests('test_malformed_prefix_preserves_existing_result_and_never_enters_writer'),
                'unchanged','AssertionError: SystemExit not raised')
