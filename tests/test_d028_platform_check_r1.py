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


# Conventional-only coverage: execute trusted template snippets with fake OS/sys
# objects, never import a planted module or alter source during an invocation.
from contextlib import nullcontext
import hashlib
import importlib.machinery
import json

CONVENTIONAL_BASE = 'ce488ac743c65bbe3ce1e97f0e7f45549fcf5b42'
# The historical comparison below remains rooted at ce488ac. Later additions
# have explicit structural shapes in a test fixture, not a broad qualification
# or independent-review claim for a5a4a23 or any other whole-main snapshot.


# Literal current argument contract (eight exact diagnostic forms). This guards
# only no-write invocation admission; it is not native qualification evidence.
B2_REQUEST_PREDICATE = "_PLATFORM_REQUESTED = bool(sys.argv[1:]) and (sys.argv[1].startswith('platform_check') or sys.argv[1].startswith('?mode=platform_check') or sys.argv[1].startswith('auto_keep') or sys.argv[1].startswith('?mode=auto_keep') or sys.argv[1].startswith('af3_fixture') or sys.argv[1].startswith('?mode=af3_fixture'))"
B2_ARGUMENT_GATE = "if sys.argv[1:] not in (['platform_check'], ['?mode=platform_check'], ['af3_fixture'], ['?mode=af3_fixture'], ['af3_fixture_verify'], ['?mode=af3_fixture_verify'], ['auto_keep'], ['?mode=auto_keep']):\n    raise SystemExit('platform_check arguments refused')"

def legacy_main_projection(tree):
    """Preserve the old platform-only normalization, then check named additions.

    Every later shape must match exactly once before projection. The final AST
    must equal ce488ac, so unrelated legacy statements cannot be discarded.
    Shapes document bounded additions; they do not qualify their native behavior.
    """
    main = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == 'main')
    for node in ast.walk(main):
        if isinstance(node, ast.Try):
            node.body = [child.body[0] if isinstance(child, ast.If)
                         and ast.unparse(child.test) == "mode != 'platform_check'" else child for child in node.body]
        if isinstance(node, ast.If) and ast.unparse(node.test) == "mode == 'platform_check'":
            node.body = [child for child in node.body if not
                (isinstance(child, ast.Assign) and any(isinstance(target, ast.Name)
                 and target.id == '_platform_product_stat' for target in child.targets)) and not
                (isinstance(child, ast.Expr) and isinstance(child.value, ast.Call)
                 and ast.unparse(child.value.func) == '_platform_isolated_roots.add') and not
                (isinstance(child, ast.Assign) and any(isinstance(target, ast.Subscript)
                 and ast.unparse(target.value) == 'sys.path' for target in child.targets))]
    text = ast.unparse(main) + '\n'
    document = json.loads((PROJECT / 'tests/fixtures/d028_legacy_main_additions.json').read_text())
    additions = document['additions']
    if len(additions) != 10 or len({item['label'] for item in additions}) != 10:
        raise AssertionError('legacy addition inventory changed')
    for item in additions:
        if text.count(item['addition']) != 1:
            raise AssertionError('legacy addition shape changed: ' + item['label'])
        text = text.replace(item['addition'], item['historical'], 1)
    return ast.parse(text).body[0]


def conventional_template():
    return ast.parse((PROJECT / 'tools/bm023a_adapter/default.py.in').read_text())


def conventional_branch(tree):
    outer = next(node for node in tree.body if isinstance(node, ast.Try))
    branch = next(node for node in outer.body if isinstance(node, ast.If)
                  and isinstance(node.test, ast.Name) and node.test.id == '_PLATFORM_REQUESTED')
    return outer, branch


def conventional_exec(nodes, namespace):
    # These nodes come solely from the checked-in trusted template, not from a
    # generated module, injected source, or changed production implementation.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<trusted template unit>', 'exec'), namespace)


def conventional_metadata(info, **changes):
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_ctime_ns', 'st_mtime_ns')
    values = {name: getattr(info, name) for name in fields}
    values.update(changes)
    return SimpleNamespace(**values)


class ConventionalImportPathTests(unittest.TestCase):
    driver = '/synthetic/addons/' + host.DRIVER_ID
    product = '/synthetic/addons/' + host.BUILD_MANAGER_ID

    def environment(self, *, paths=None, product_mode=0o40755, missing=None, cwd='/synthetic'):
        identities = {}
        for index, path in enumerate(('/synthetic', '/synthetic/addons', self.driver,
                                      self.product, self.product + '/sub', '/stdlib', '/alias'), 1):
            identities[path] = SimpleNamespace(st_dev=1, st_ino=index, st_mode=0o40755)
        identities[self.product].st_mode = product_mode
        identities['/alias'].st_mode = 0o120777
        def metadata(path, **kwargs):
            path = str(path)
            if path == missing or path not in identities:
                raise FileNotFoundError('synthetic path unavailable')
            return identities[path]
        fake_os = SimpleNamespace(path=os.path, stat=metadata, lstat=metadata,
                                  readlink=lambda path: self.product + '/sub', getcwd=lambda: cwd)
        fake_sys = SimpleNamespace(path=list(paths or ['/stdlib', self.driver]),
                                   argv=[self.driver + '/default.py', 'platform_check'],
                                   modules={'os': fake_os}, dont_write_bytecode=False, meta_path=['previous'])
        namespace = dict(sys=fake_sys, __file__=self.driver + '/default.py',
                         _PREVIOUS_PLATFORM_MODULES={})
        return namespace, fake_sys, identities

    def bootstrap(self, namespace):
        _, branch = conventional_branch(conventional_template())
        nodes = branch.body[:next(i for i, node in enumerate(branch.body) if isinstance(node, ast.Import))]
        conventional_exec(nodes, namespace)

    def later(self, namespace):
        tree = conventional_template()
        main = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'main')
        branch = next(node for node in ast.walk(main) if isinstance(node, ast.If)
                      and isinstance(node.test, ast.Compare)
                      and ast.unparse(node.test) == "mode == 'platform_check'"
                      and any(isinstance(child, ast.Assign) and any(isinstance(t, ast.Attribute)
                          and t.attr == 'product_root' for t in child.targets) for child in node.body))
        namespace.update(addon_root=Path(self.product), os=namespace['_platform_os'],
                         _PLATFORM_FINDER=SimpleNamespace(product_root=None))
        conventional_exec(branch.body[:4], namespace)

    def test_product_and_driver_direct_relative_and_symlink_paths_are_excluded(self):
        paths = ['/stdlib', self.driver, self.product, self.product + '/sub',
                 'addons/' + host.BUILD_MANAGER_ID, '/alias', '/alias/..', '/missing']
        namespace, fake_sys, _ = self.environment(paths=paths)
        self.bootstrap(namespace)
        self.assertEqual(['/stdlib'], fake_sys.path)

    def test_current_directory_alias_is_excluded(self):
        namespace, fake_sys, _ = self.environment(paths=['', '.', '/stdlib'], cwd=self.product)
        self.bootstrap(namespace)
        self.assertEqual(['/stdlib'], fake_sys.path)

    def test_later_filter_preserves_restrictions_and_binds_fixed_product_root(self):
        namespace, fake_sys, _ = self.environment()
        self.bootstrap(namespace)
        fake_sys.path[:] = ['/stdlib', self.product, self.product + '/sub', '/alias', self.driver]
        self.later(namespace)
        self.assertEqual(['/stdlib'], fake_sys.path)
        self.assertEqual(self.product, namespace['_PLATFORM_FINDER'].product_root)

    def test_missing_required_and_invalid_directory_identity_refuse(self):
        for mode in (0o100644, 0o120777):
            namespace, _, _ = self.environment(product_mode=mode)
            with self.subTest(mode=mode), self.assertRaisesRegex(ImportError, 'product isolation unavailable'):
                self.bootstrap(namespace)
        namespace, _, _ = self.environment(missing=self.driver)
        with self.assertRaises(FileNotFoundError):
            self.bootstrap(namespace)
        namespace, _, _ = self.environment(missing=self.product)
        self.bootstrap(namespace)  # Sibling lookup is preliminary; VFS lookup below is required.
        with self.assertRaises(FileNotFoundError):
            self.later(namespace)
        namespace, fake_sys, _ = self.environment()
        fake_sys.modules.clear()
        with self.assertRaisesRegex(ImportError, 'import isolation unavailable'):
            self.bootstrap(namespace)
        namespace, fake_sys, _ = self.environment()
        namespace['_PREVIOUS_PLATFORM_MODULES'] = {'resources.lib': object()}
        before = list(fake_sys.path)
        with self.assertRaisesRegex(ImportError, 'preloaded module refused'):
            self.bootstrap(namespace)
        self.assertEqual(before, fake_sys.path)

    def test_exact_requests_and_malformed_prefix_refusal_precede_path_changes(self):
        for argument in ('platform_check', '?mode=platform_check'):
            namespace, fake_sys, _ = self.environment()
            fake_sys.argv[1:] = [argument]
            self.bootstrap(namespace)
            self.assertEqual(['/stdlib'], fake_sys.path)
        for arguments in (['platform_checkx'], ['platform_check;install'],
                          ['?mode=platform_check&x=1'], ['platform_check', 'install']):
            namespace, fake_sys, _ = self.environment()
            fake_sys.argv[1:] = arguments
            before = list(fake_sys.path)
            with self.assertRaises(SystemExit):
                self.bootstrap(namespace)
            self.assertEqual(before, fake_sys.path)
            self.assertFalse(fake_sys.dont_write_bytecode)

    def test_outer_cleanup_restores_search_state_on_success_and_refusal(self):
        for invalid in (False, True):
            namespace, fake_sys, _ = self.environment(product_mode=0o100644 if invalid else 0o40755)
            before = list(fake_sys.path)
            namespace.update(_PREVIOUS_BYTECODE_FLAG=False, _PREVIOUS_SYS_PATH=before,
                             _PREVIOUS_META_PATH=list(fake_sys.meta_path), _PLATFORM_REQUESTED=True)
            tree = conventional_template()
            conventional_exec([next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                                    and node.name == '_platform_module')], namespace)
            try:
                if invalid:
                    with self.assertRaises(ImportError):
                        self.bootstrap(namespace)
                else:
                    self.bootstrap(namespace)
                    self.later(namespace)
                    self.assertEqual(['/stdlib'], fake_sys.path)
            finally:
                fake_sys.modules['resources.unit'] = object()
                fake_sys.meta_path.append('temporary finder')
                outer, _ = conventional_branch(tree)
                conventional_exec(outer.finalbody, namespace)
            self.assertEqual(before, fake_sys.path)
            self.assertEqual(['previous'], fake_sys.meta_path)
            self.assertFalse(fake_sys.dont_write_bytecode)
            self.assertNotIn('resources.unit', fake_sys.modules)

    def test_product_is_not_prepended_and_legacy_path_insertion_is_unchanged(self):
        main = next(node for node in ast.walk(conventional_template())
                    if isinstance(node, ast.FunctionDef) and node.name == 'main')
        guards = [node for node in ast.walk(main) if isinstance(node, ast.If)
                  and ast.unparse(node.test) == "mode != 'platform_check'"]
        self.assertEqual(1, len(guards))
        self.assertEqual(1, len([node for node in ast.walk(main) if isinstance(node, ast.Call)
                                and ast.unparse(node.func) == 'sys.path.insert']))
        for mode in ('platform_check', 'install', 'recover', 'retry', 'status'):
            fake_sys = SimpleNamespace(path=['/stdlib'])
            conventional_exec(guards, dict(sys=fake_sys, mode=mode, addon_root=Path(self.product)))
            self.assertEqual(['/stdlib'] if mode == 'platform_check' else [self.product, '/stdlib'], fake_sys.path)

    def test_fixed_product_specs_and_source_hash_before_compilation_remain_supported(self):
        _, branch = conventional_branch(conventional_template())
        names = ('_PlatformSourceLoader', '_PlatformSourceFinder')
        classes = [node for node in branch.body if isinstance(node, ast.ClassDef) and node.name in names]
        data = b'known conventional fixture bytes\n'
        digest = hashlib.sha256(data).hexdigest()
        product = {'resources/lib/' + name + '.py': digest for name in ('frozen_install', 'frozen', 'artifacts')}
        module = SimpleNamespace(PLATFORM_SOURCE_BINDING=json.dumps({'product': product, 'adapter': {}}))
        namespace = dict(sys=SimpleNamespace(modules={'adapter_config': module}), __file__=self.driver + '/default.py',
                         _platform_os=os, _platform_json=json, _platform_hashlib=hashlib,
                         _platform_machinery=importlib.machinery, _platform_util=importlib.util,
                         _platform_module=lambda name: name == 'resources' or name.startswith('resources.'))
        conventional_exec(classes, namespace)
        finder = namespace['_PlatformSourceFinder']()
        finder.product_root = self.product
        for name in ('frozen_install', 'frozen', 'artifacts'):
            spec = finder.find_spec('resources.lib.' + name)
            self.assertEqual(self.product + '/resources/lib/' + name + '.py', spec.origin)
            self.assertEqual(digest, spec.loader.expected)
            compiled = object()
            with patch.object(spec.loader, 'get_data', return_value=data), \
                    patch.object(spec.loader, 'source_to_code', return_value=compiled) as compiler:
                self.assertIs(compiled, spec.loader.get_code(spec.name))
                compiler.assert_called_once_with(data, spec.origin)
            spec.loader.expected = '0' * 64
            with patch.object(spec.loader, 'get_data', return_value=data), \
                    patch.object(spec.loader, 'source_to_code') as compiler:
                with self.assertRaisesRegex(ImportError, 'source identity refused'):
                    spec.loader.get_code(spec.name)
                compiler.assert_not_called()

    def assert_b2_argument_gate(self, tree):
        predicate = next(node for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == '_PLATFORM_REQUESTED' for t in node.targets))
        self.assertEqual(ast.dump(ast.parse(B2_REQUEST_PREDICATE).body[0]), ast.dump(predicate))
        _, branch = conventional_branch(tree)
        self.assertEqual(ast.dump(ast.parse(B2_ARGUMENT_GATE).body[0]), ast.dump(branch.body[0]))

    def test_module_level_b2_argument_gate_matches_exact_current_contract(self):
        self.assert_b2_argument_gate(conventional_template())

    def test_module_level_b2_guard_rejects_unauthorized_allowlist_expansion(self):
        tree = conventional_template()
        _, branch = conventional_branch(tree)
        branch.body[0].test.comparators[0].elts.append(
            ast.List(elts=[ast.Constant('platform_checkx')], ctx=ast.Load()))
        with self.assertRaises(AssertionError):
            self.assert_b2_argument_gate(tree)

    def assert_legacy_main(self, tree):
        baseline = ast.parse(subprocess.check_output(
            ['git', 'show', CONVENTIONAL_BASE + ':tools/bm023a_adapter/default.py.in'],
            cwd=PROJECT, text=True))
        main = next(node for node in ast.walk(baseline)
                    if isinstance(node, ast.FunctionDef) and node.name == 'main')
        self.assertEqual(ast.dump(main), ast.dump(legacy_main_projection(tree)))

    def test_legacy_main_ast_is_identical_after_removing_only_platform_changes(self):
        """Compare legacy behavior to ce488ac, with explicit checked additions.

        This is a structural compatibility guard, not qualification of additions.
        Original finder/loader assertions also retain their ce488ac reference.
        """
        self.assert_legacy_main(conventional_template())
        baseline = ast.parse(subprocess.check_output(
            ['git', 'show', CONVENTIONAL_BASE + ':tools/bm023a_adapter/default.py.in'],
            cwd=PROJECT, text=True))
        _, before = conventional_branch(baseline)
        _, after = conventional_branch(conventional_template())
        for name in ('_PlatformSourceFinder', '_PlatformSourceLoader'):
            old = next(node for node in before.body if isinstance(node, ast.ClassDef) and node.name == name)
            new = next(node for node in after.body if isinstance(node, ast.ClassDef) and node.name == name)
            self.assertEqual(ast.dump(old), ast.dump(new))

    def test_legacy_projection_rejects_unauthorized_behavior_mutations(self):
        for mutation in ('fixture_modes', 'result_identity', 'execution', 'verification'):
            with self.subTest(mutation=mutation):
                tree = conventional_template()
                main = next(node for node in ast.walk(tree)
                            if isinstance(node, ast.FunctionDef) and node.name == 'main')
                if mutation == 'fixture_modes':
                    assignment = next(node for node in ast.walk(main) if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'fixture_mode' for t in node.targets)
                        and isinstance(node.value, ast.IfExp))
                    assignment.value.test.comparators[0].elts.append(ast.Constant('install'))
                else:
                    expected = {'result_identity': 'identify_adapter_result',
                                'execution': 'coordinator.install',
                                'verification': 'verify_production_module_sources'}[mutation]
                    call = next(node for node in ast.walk(main)
                                if isinstance(node, ast.Call) and ast.unparse(node.func) == expected)
                    call.func = ast.Name(id='unauthorized_call', ctx=ast.Load())
                with self.assertRaises(AssertionError):
                    self.assert_legacy_main(tree)


class ConventionalProductWitnessTests(unittest.TestCase):
    def setup_world(self):
        # Ordinary inert stage data. No exported builder, generated entrypoint,
        # configuration module or product module file is executed/imported.
        fixture = Fixture(self)
        target = host.TestAppTarget.for_tests(fixture.native.bundle)
        driver = target.addon_dir(host.DRIVER_ID)
        shutil.copytree(fixture.driver, driver)
        binding = json.loads(fixture.binding)
        manifest = {
            'candidate': {'commit': binding['candidate_commit']},
            'driver': {'files': [dict(path=path.name, size=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted(driver.iterdir())]},
            'build_manager': {'files': [dict(path=name, sha256=digest,
                size=(fixture.addon / name).stat().st_size) for name, digest in binding['product'].items()]},
        }
        return SimpleNamespace(target=target, manifest=manifest, fixture=fixture), fixture.run()

    def invoke(self):
        world, result = self.setup_world()
        path = world.target.bm_data_dir / host.RESULT_FILENAME
        # A normal result fixture; no source or directory identity is changed
        # between the two production witness calls.
        path.write_text(json.dumps(dict(result, adapter_mode='platform_check')))
        observation = host.observe_result(world.target)
        timestamp = observation.read.st_mtime_ns
        times = iter((timestamp - 1, timestamp + 1))
        services = SimpleNamespace(target=world.target,
            clock=SimpleNamespace(time_ns=lambda: next(times), monotonic=lambda: 0))
        identity = SimpleNamespace(pid=4242, report=lambda: {'process': {}})
        client = SimpleNamespace(authenticated=False, requests_sent=2,
            call=lambda method, params: 'pong' if method == 'JSONRPC.Ping' else 'OK')
        verification = dict(installed_equals_manifest=True, installed_equals_candidate=True, trees={})
        absent = SimpleNamespace(state='absent', identity=lambda: None)
        # Mock the already-tested upstream process/RPC/Git boundaries. Keep the
        # actual invocation witness, source/result binding and projection logic.
        with patch.object(host, 'identify', return_value=identity), \
                patch.object(host, 'verify_installed', return_value=verification), \
                patch.object(host, 'RpcClient', return_value=client), \
                patch.object(host, '_kodi_addon_view', return_value={}), \
                patch.object(host, 'observe_result', side_effect=[absent, absent, observation]):
            report = host.run_adapter(services, mode='platform_check', manifest=world.manifest,
                manifest_sha256='f' * 64, rpc={'port': 8080}, git_repo=PROJECT, timeout=10)
        return world, report

    def product(self, world):
        return world.target.addon_dir(host.BUILD_MANAGER_ID)

    def test_stable_witness_includes_product_identity_and_sorted_top_level_inventory(self):
        world, _ = self.setup_world()
        before = snapshot(world.target.root)
        first = host._platform_invocation_snapshot(world.target, world.manifest)
        second = host._platform_invocation_snapshot(world.target, world.manifest)
        self.assertEqual(first, second)
        root = self.product(world).stat()
        self.assertIn((root.st_dev, root.st_ino, root.st_mode, root.st_size, root.st_ctime_ns, root.st_mtime_ns), first[0])
        expected = sorted({entry['path'].split('/')[0] for entry in world.manifest['build_manager']['files']})
        self.assertEqual(expected, [name for name, _ in first[2]])
        self.assertEqual(sorted(host.DRIVER_FILES), [name for name, _ in first[1]])
        self.assertEqual(before, snapshot(world.target.root))

    def test_mocked_unexpected_or_missing_manifest_inventory_refuses(self):
        world, _ = self.setup_world()
        product_inode = self.product(world).stat().st_ino
        original_scandir, original_fstat = os.scandir, os.fstat
        original_names = sorted(path.name for path in self.product(world).iterdir())
        for names in (original_names + ['unexpected.txt'], original_names[1:]):
            def listing(fd):
                if isinstance(fd, int) and original_fstat(fd).st_ino == product_inode:
                    return nullcontext(iter(SimpleNamespace(name=name) for name in names))
                return original_scandir(fd)
            with self.subTest(names=names), patch.object(host.os, 'scandir', listing):
                with self.assertRaisesRegex(host.HelperError, 'platform_source_unverifiable'):
                    host._platform_invocation_snapshot(world.target, world.manifest)

    def test_mocked_manifest_size_and_bounded_inventory_are_enforced(self):
        world, _ = self.setup_world()
        product_inode = self.product(world).stat().st_ino
        original_stat, original_fstat = os.stat, os.fstat
        def different_size(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            fd = kwargs.get('dir_fd')
            if path == 'default.py' and fd is not None and original_fstat(fd).st_ino == product_inode:
                return conventional_metadata(info, st_size=info.st_size + 1)
            return info
        with patch.object(host.os, 'stat', different_size):
            with self.assertRaisesRegex(host.HelperError, 'platform_source_unverifiable'):
                host._platform_invocation_snapshot(world.target, world.manifest)
        count = len(world.manifest['build_manager']['files'])
        original_scandir = os.scandir
        def oversized_listing(fd):
            if isinstance(fd, int) and original_fstat(fd).st_ino == product_inode:
                return nullcontext(iter(SimpleNamespace(name='entry-' + str(i)) for i in range(count + 2)))
            return original_scandir(fd)
        with patch.object(host, 'MAX_CANDIDATE_FILES', count), patch.object(host.os, 'scandir', oversized_listing):
            with self.assertRaisesRegex(host.HelperError, 'platform_source_unverifiable'):
                host._platform_invocation_snapshot(world.target, world.manifest)
        with patch.object(host, 'MAX_CANDIDATE_BYTES', 0):
            with self.assertRaisesRegex(host.HelperError, 'platform_source_unverifiable'):
                host._platform_invocation_snapshot(world.target, world.manifest)

    def test_inconsistent_directory_identity_refuses_without_writes(self):
        world, _ = self.setup_world()
        inode = self.product(world).stat().st_ino
        original_fstat = os.fstat
        before = snapshot(world.target.root)
        def inconsistent(fd):
            info = original_fstat(fd)
            return conventional_metadata(info, st_ino=info.st_ino + 1) if info.st_ino == inode else info
        with patch.object(host.os, 'fstat', inconsistent):
            with self.assertRaisesRegex(host.HelperError, 'platform_source_unverifiable'):
                host._platform_invocation_snapshot(world.target, world.manifest)
        self.assertEqual(before, snapshot(world.target.root))

    def test_missing_coarse_and_invalid_product_metadata_fail_closed(self):
        world, _ = self.setup_world()
        inode = self.product(world).stat().st_ino
        original_fstat = os.fstat
        for changes in ({'st_ctime_ns': None}, {'st_ctime_ns': 1_000_000_000},
                        {'st_ino': 0}, {'st_mode': 0o120777}):
            def metadata(fd):
                info = original_fstat(fd)
                if info.st_ino != inode:
                    return info
                altered = conventional_metadata(info, **changes)
                if changes.get('st_ctime_ns', 1) is None:
                    del altered.st_ctime_ns
                return altered
            with self.subTest(changes=changes), patch.object(host.os, 'fstat', metadata):
                with self.assertRaisesRegex(host.HelperError, 'platform_source_unverifiable'):
                    host._platform_invocation_snapshot(world.target, world.manifest)

    def test_missing_product_root_or_unavailable_directory_open_refuses(self):
        world, _ = self.setup_world()
        original_open = os.open
        for error in (FileNotFoundError, PermissionError):
            def unavailable(path, *args, **kwargs):
                if path == host.BUILD_MANAGER_ID and kwargs.get('dir_fd') is not None:
                    raise error('synthetic unavailable product')
                return original_open(path, *args, **kwargs)
            with self.subTest(error=error), patch.object(host.os, 'open', unavailable):
                with self.assertRaisesRegex(host.HelperError, 'platform_source_unverifiable'):
                    host._platform_invocation_snapshot(world.target, world.manifest)

    def test_top_level_entry_identity_is_no_follow_and_never_reads_product_contents(self):
        world, _ = self.setup_world()
        product = self.product(world)
        inode = product.stat().st_ino
        file_inodes = {path.stat().st_ino for path in product.iterdir() if path.is_file()}
        original_read, original_stat, original_fstat = os.read, os.stat, os.fstat
        entry_calls = []
        def observe_stat(path, *args, **kwargs):
            if kwargs.get('dir_fd') is not None and original_fstat(kwargs['dir_fd']).st_ino == inode:
                self.assertIs(False, kwargs.get('follow_symlinks'))
                entry_calls.append(path)
            return original_stat(path, *args, **kwargs)
        def observe_read(fd, size):
            self.assertNotIn(original_fstat(fd).st_ino, file_inodes)
            return original_read(fd, size)
        with patch.object(host.os, 'stat', observe_stat), patch.object(host.os, 'read', observe_read):
            host._platform_invocation_snapshot(world.target, world.manifest)
        self.assertEqual(2 * len(list(product.iterdir())), len(entry_calls))

    def test_product_witness_difference_prevents_host_success(self):
        original_snapshot = host._platform_invocation_snapshot
        original_fstat, original_stat = os.fstat, os.stat
        calls = []
        def observe(target, manifest):
            calls.append(True)
            if len(calls) == 1:
                return original_snapshot(target, manifest)
            inode = target.addon_dir(host.BUILD_MANAGER_ID).stat().st_ino
            def altered(info):
                return conventional_metadata(info, st_ctime_ns=info.st_ctime_ns + 1) if info.st_ino == inode else info
            with patch.object(host.os, 'fstat', lambda fd: altered(original_fstat(fd))), \
                    patch.object(host.os, 'stat', lambda *args, **kwargs: altered(original_stat(*args, **kwargs))):
                return original_snapshot(target, manifest)
        with patch.object(host, '_platform_invocation_snapshot', observe):
            with self.assertRaisesRegex(host.HelperError, 'platform_source_changed'):
                self.invoke()
        self.assertEqual(2, len(calls))

    def test_unchanged_host_result_retains_requirements_verified_and_not_qualified(self):
        _, report = self.invoke()
        self.assertTrue(report['ok'])
        self.assertEqual('requirements_verified', report['result']['platform_check']['overall'])
        self.assertEqual('not_qualified', report['result']['platform_check']['qualification'])
