"""Pinned passive compatibility, using only synthetic registries and disposable roots.

Descriptor fixtures are exact Kodi 21.3 bundled bytes (see fixtures/d028_passive/README.md).
Synthetic Info.plist has a test-only
anchor: production's supplied real-bundle SHA is separately checked and must
reject that synthetic plist. No test calls native proc_pidpath or a Kodi runtime.
"""
from dataclasses import replace
import hashlib
import inspect
import json
import plistlib
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib import frozen as fr, frozen_install as fi
from resources.lib import repository_preparation as prep
from resources.lib.addons import RepositoryPackage
from resources.lib.artifacts import ArtifactStore
from tests import test_d028_admission as admission, test_d028_b1 as b1
from tests import test_d028_preparation as standalone, test_frozen as capture
from tests import test_frozen_install as old
from tests.test_status import DEMO

PINS = {
    'xbmc.core': ('0.1.0', '0.1', 'e38ace50afe6e15b918fa51038504fc11888038671bdacac2521af931b538a6f'),
    'xbmc.gui': ('5.17.0', '5.17.0', '7d8602ff6510bbb5ae8098d60c563c4e82c5f0b682220aad297982c9e116e6bb'),
    'kodi.resource': ('1.0.0', '1.0', 'dd54ff32f0920d4fe68bff14c1a51311ac8f31e639fbbe7123a16905901b06f3'),
    'xbmc.metadata': ('2.1.0', '1.0', '95082198599c695a91d2aefb072f0457e9ffd5eb3f2dc1587fa58159750db1b6'),
}
NATIVE_EXECUTABLE_QUERY = fi._native_process_executable
PLIST_PIN = '9f37ef7b63021ef2ab01b98a44f2f62c8eb68c3f61c014510cc3b7166450bcac'


class PassiveFixture:
    def __init__(self, case):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.bundle = self.root / 'Synthetic.app'
        self.app = self.bundle / 'Contents/Resources/Kodi/addons'
        self.home = self.root / 'home/addons'
        self.app.mkdir(parents=True)
        self.home.mkdir(parents=True)
        self.exe = self.bundle / 'Contents/MacOS/Kodi'
        self.exe.parent.mkdir()
        self.exe.write_bytes(b'synthetic executable identity, never executed')
        self.exe.chmod(0o755)
        self.plist = self.bundle / 'Contents/Info.plist'
        self.plist.write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'org.xbmc.kodi', 'CFBundleShortVersionString': '21.3.',
            'CFBundleVersion': '20251031-a3a448d26b', 'CFBundleExecutable': 'Kodi',
            'CFBundlePackageType': 'APPL'}))
        self.info = {}
        self.conditions = {}
        for aid, (version, _, digest) in PINS.items():
            data = (Path(__file__).parent / 'fixtures/d028_passive' / (aid + '.xml')).read_bytes()
            case.assertEqual(digest, hashlib.sha256(data).hexdigest())
            descriptor = self.app / aid / 'addon.xml'
            descriptor.parent.mkdir()
            descriptor.write_bytes(data)
            self.info[aid] = dict(id=aid, version=version, path=str(descriptor.parent), type='unknown')
            self.conditions['System.HasAddon(' + aid + ')'] = True
            self.conditions['System.AddonIsEnabled(' + aid + ')'] = True
        self.version = dict(major=21, minor=3, revision='20251031-a3a448d26b', tag='stable')
        self.backend = fi.KodiRuntimeFrozenArtifactBackend()
        case.addCleanup(self.backend.close)
        self.backend._addons_dir = lambda: self.home
        self.backend._application_addons_dir = lambda: self.app
        self.backend._xbmc = lambda: SimpleNamespace(getCondVisibility=self.conditions.__getitem__)
        self.backend._rpc = lambda method, params: {'result': {'version': self.version.copy()}}
        self.api = SimpleNamespace(Addon=lambda aid: SimpleNamespace(getAddonInfo=self.info[aid].__getitem__))
        for p in (patch.dict('sys.modules', {'xbmcaddon': self.api}),
                  patch.object(fi.sys, 'platform', 'darwin'),
                  patch.object(fi, '_native_process_executable', return_value=str(self.exe)),
                  patch.object(fi, '_PASSIVE_PLIST_SHA256', hashlib.sha256(self.plist.read_bytes()).hexdigest())):
            p.start()
            case.addCleanup(p.stop)

    def read(self, aid='xbmc.gui', minimum=None):
        return self.backend.read_verified_builtin_metadata(fr.DependencyEdge(aid,
            PINS[aid][0] if minimum is None else minimum))

    def descriptor(self, aid='xbmc.gui'):
        return self.app / aid / 'addon.xml'


class PassiveNativeTests(unittest.TestCase):
    def setUp(self):
        self.f = PassiveFixture(self)

    def test_all_pins_and_original_bytes_are_accepted(self):
        self.assertEqual(PINS, dict(fi._PASSIVE_BUILTINS))
        for aid in PINS:
            with self.subTest(aid=aid):
                metadata = self.f.read(aid)
                self.assertIsInstance(metadata, fi._PinnedPassiveMetadata)
                self.assertEqual(self.f.descriptor(aid).read_bytes(), metadata.xml_bytes)
                self.assertEqual(fr.InstalledOrigin.APPLICATION, metadata.origin)

    def test_production_plist_anchor_refuses_synthetic_bytes(self):
        self.assertIn(PLIST_PIN, inspect.getsource(fi))
        with patch.object(fi, '_PASSIVE_PLIST_SHA256', PLIST_PIN):
            self.assertIsNone(self.f.read())

    def test_unknown_platform_and_unavailable_kernel_identity_refuse(self):
        with patch.object(fi.sys, 'platform', 'linux'):
            self.assertIsNone(self.f.read())
        with patch.object(fi, '_native_process_executable', side_effect=OSError):
            self.assertIsNone(self.f.read())
        for path in ('relative', str(self.f.exe) + '-evil', str(self.f.root / 'other.app/Contents/MacOS/Kodi')):
            with patch.object(fi, '_native_process_executable', return_value=path):
                self.assertIsNone(self.f.read())

    def test_kernel_query_uses_current_pid_and_refuses_invalid_results(self):
        import ctypes
        import os
        calls = []
        def query(pid, buffer, size):
            calls.append((pid, size))
            buffer.value = str(self.f.exe).encode()
            return len(buffer.value)
        # Fake libproc only: never load or execute a native process query.
        with patch.object(ctypes, 'CDLL', return_value=SimpleNamespace(proc_pidpath=query)):
            self.assertEqual(str(self.f.exe), NATIVE_EXECUTABLE_QUERY())
        self.assertEqual([(os.getpid(), 4096)], calls)
        for count in (-1, 0, 4096, 1):
            def invalid(pid, buffer, size):
                buffer.value = b'longer-than-count'
                return count
            with patch.object(ctypes, 'CDLL', return_value=SimpleNamespace(proc_pidpath=invalid)):
                with self.assertRaises(ValueError): NATIVE_EXECUTABLE_QUERY()

    def test_wrong_application_root_and_bundle_ancestor_symlink_refuse(self):
        other = self.f.root / 'unrelated/addons'
        other.mkdir(parents=True)
        self.f.backend._application_addons_dir = lambda: other
        self.assertIsNone(self.f.read())
        self.f.backend.close()
        self.f.backend._inventory_backend = None
        self.f.backend._application_addons_dir = lambda: self.f.app
        retained = self.f.root / 'retained.app'
        self.f.bundle.rename(retained)
        self.f.bundle.symlink_to(retained, target_is_directory=True)
        self.assertIsNone(self.f.read())

    def test_last_compiled_observation_cannot_replace_descriptor_after_freshness_check(self):
        calls = []
        def rpc(method, params):
            calls.append(method)
            if len(calls) == 2:
                self.f.descriptor().write_bytes(self.f.descriptor().read_bytes() + b' ')
            return {'result': {'version': self.f.version.copy()}}
        self.f.backend._rpc = rpc
        self.assertIsNone(self.f.read())
        self.assertEqual(2, len(calls))

    def test_wrong_build_version_and_unknown_compiled_identity_refuse(self):
        for key, value in (('major', 22), ('major', True), ('minor', 2), ('revision', 'a3a448d26b'),
                           ('revision', '20251031-other'), ('tag', 'alpha'), ('revision', None)):
            with self.subTest(key=key, value=value):
                old_value = self.f.version[key]
                self.f.version[key] = value
                self.assertIsNone(self.f.read())
                self.f.version[key] = old_value
        self.f.backend._rpc = lambda *args: {'error': {'code': -1}}
        self.assertIsNone(self.f.read())

    def test_bundle_metadata_and_executable_substitution_refuse(self):
        self.f.plist.write_bytes(self.f.plist.read_bytes() + b' ')
        self.assertIsNone(self.f.read())
        self.f.exe.unlink()
        self.f.exe.symlink_to(self.f.plist)
        self.assertIsNone(self.f.read())

    def test_wrong_plist_fields_refuse_even_with_test_anchor(self):
        for key, value in (('CFBundleVersion', 'other'), ('CFBundleIdentifier', 'other'),
                           ('CFBundleExecutable', 'Other'), ('CFBundleShortVersionString', '21.2.')):
            original = self.f.plist.read_bytes()
            info = plistlib.loads(original)
            info[key] = value
            self.f.plist.write_bytes(plistlib.dumps(info))
            with patch.object(fi, '_PASSIVE_PLIST_SHA256', hashlib.sha256(self.f.plist.read_bytes()).hexdigest()):
                self.assertIsNone(self.f.read())
            self.f.plist.write_bytes(original)

    def test_registration_enabled_and_constructor_are_mandatory(self):
        for key in self.f.conditions:
            if '(xbmc.gui)' not in key:
                continue
            for value in (False, None, 1, 'true'):
                self.f.conditions[key] = value
                self.assertIsNone(self.f.read())
            self.f.conditions[key] = True
        self.f.api.Addon = lambda aid: (_ for _ in ()).throw(RuntimeError('unavailable'))
        self.assertIsNone(self.f.read())

    def test_native_id_type_version_path_and_prefix_tricks_refuse(self):
        info = self.f.info['xbmc.gui']
        for key, value in (('id', 'xbmc.core'), ('type', 'xbmc.python.module'), ('type', None),
                           ('version', '5.17'), ('path', str(self.f.home / 'xbmc.gui')),
                           ('path', str(self.f.app / 'xbmc.gui-evil')), ('path', 'relative'), ('path', None)):
            original = info[key]
            info[key] = value
            self.assertIsNone(self.f.read())
            info[key] = original

    def test_home_shadow_all_forms_refuse(self):
        shadow = self.f.home / 'xbmc.gui'
        for kind in ('equal', 'higher', 'file', 'symlink', 'dangling'):
            with self.subTest(kind=kind):
                if kind in ('equal', 'higher'):
                    shadow.mkdir()
                    (shadow / 'addon.xml').write_bytes(self.f.descriptor().read_bytes().replace(
                        b'5.17.0', b'999.0.0') if kind == 'higher' else self.f.descriptor().read_bytes())
                elif kind == 'file': shadow.write_bytes(b'shadow')
                else: shadow.symlink_to(self.f.descriptor().parent if kind == 'symlink' else self.f.root / 'missing')
                try:
                    self.assertIsNone(self.f.read())
                finally:
                    if kind in ('equal', 'higher'):
                        (shadow / 'addon.xml').unlink()
                        shadow.rmdir()
                    else: shadow.unlink()

    def test_single_byte_and_additional_imports_or_metadata_refuse(self):
        for aid in PINS:
            descriptor = self.f.descriptor(aid)
            original = descriptor.read_bytes()
            for data in (original + b' ', original.replace(b'</addon>',
                    b'<requires><import addon="xbmc.fake"/></requires></addon>'),
                    original.replace(b'</addon>', b'<extension point="xbmc.addon.metadata"/></addon>'),
                    original.replace(b'c-pluff version="0.1"', b'c-pluff version="0.2"')):
                if data == original: continue
                descriptor.write_bytes(data)
                self.assertIsNone(self.f.read(aid))
            descriptor.write_bytes(original)

    def test_missing_core_import_modified_core_and_additional_child_refuse(self):
        gui = self.f.descriptor()
        gui.write_bytes(gui.read_bytes().replace(b'<import addon="xbmc.core" version="0.1.0"/>', b''))
        self.assertIsNone(self.f.read())
        core = self.f.descriptor('xbmc.core')
        core.write_bytes(core.read_bytes().replace(b'</requires>', b'<extra/></requires>'))
        self.assertIsNone(self.f.read('xbmc.core'))

    def test_symlink_descriptor_directory_or_ancestor_refuse(self):
        file = self.f.descriptor()
        moved = self.f.root / 'retained.xml'
        file.rename(moved)
        file.symlink_to(moved)
        self.assertIsNone(self.f.read())
        file.unlink()
        moved.rename(file)
        directory = file.parent
        moved_dir = self.f.root / 'retained-addon'
        directory.rename(moved_dir)
        directory.symlink_to(moved_dir, target_is_directory=True)
        self.assertIsNone(self.f.read())

    def test_repeated_native_identity_and_enabled_drift_refuse(self):
        for key, value in (('id', 'xbmc.core'), ('version', '5.18.0'), ('path', str(self.f.home)),
                           ('type', 'changed'), ('enabled', False)):
            calls = []
            original = self.f.info['xbmc.gui'].copy()
            def construct(aid):
                calls.append(aid)
                snapshot = self.f.info[aid].copy()
                if len(calls) == 2:
                    if key == 'enabled': self.f.conditions['System.AddonIsEnabled(xbmc.gui)'] = False
                    else: snapshot[key] = value
                return SimpleNamespace(getAddonInfo=snapshot.__getitem__)
            self.f.api.Addon = construct
            self.assertIsNone(self.f.read())
            self.f.info['xbmc.gui'] = original
            self.f.conditions['System.AddonIsEnabled(xbmc.gui)'] = True

    def test_descriptor_and_build_changes_during_observation_refuse(self):
        original_construct = self.f.api.Addon
        for change in ('descriptor', 'plist', 'executable', 'compiled', 'shadow'):
            calls = []
            def construct(aid):
                calls.append(aid)
                if len(calls) == 2:
                    if change == 'descriptor': self.f.descriptor().write_bytes(self.f.descriptor().read_bytes() + b' ')
                    if change == 'plist': self.f.plist.write_bytes(self.f.plist.read_bytes() + b' ')
                    if change == 'executable': self.f.exe.write_bytes(b'replacement')
                    if change == 'compiled': self.f.version['revision'] = 'changed'
                    if change == 'shadow': (self.f.home / 'xbmc.gui').mkdir()
                return original_construct(aid)
            # Independent roots, since an earlier refusal must not grant new authority.
            if change != 'descriptor': self.f = PassiveFixture(self)
            original_construct = self.f.api.Addon
            self.f.api.Addon = construct
            self.assertIsNone(self.f.read())

    def test_abi_and_independent_minima_use_kodi_ordering(self):
        for minimum in ('5.17', '5.16.9', '999.0.0', '5.17.0+matrix', 'bad', '5..17'):
            self.assertIsNone(self.f.read(minimum=minimum))
        self.assertIsNotNone(self.f.read(minimum='5.17.0'))
        self.assertIsNotNone(self.f.read('xbmc.core', '0.1'))
        self.assertIsNone(self.f.backend.read_verified_builtin_metadata(fr.DependencyEdge('xbmc.unknown', '1.0')))

    def test_full_admission_closes_core_and_preserves_each_minimum(self):
        a = admission.BuiltinAdmissionTests()
        a.setUp()
        self.addCleanup(a.doCleanups)
        a.backend = self.f.backend
        verified = a.verify()
        self.assertEqual({'xbmc.gui', 'xbmc.core'}, set(verified.builtin_versions))
        for key in ('System.HasAddon(xbmc.core)', 'System.AddonIsEnabled(xbmc.core)'):
            self.f.conditions[key] = False
            with self.assertRaises(fi.FrozenPlatformRequirementError): a.verify()
            self.f.conditions[key] = True
        with self.assertRaises(fi.FrozenPlatformRequirementError): a.verify(a.manifest('999.0.0'))
        with self.assertRaises(fi.FrozenPlatformRequirementError): a.verify(a.manifest('5.17'))

    def test_core_exception_requires_native_grant_and_exact_hash(self):
        raw = self.f.descriptor('xbmc.core').read_bytes()
        native = self.f.read('xbmc.core')
        self.assertEqual((), fi._builtin_metadata_edges(native, 'xbmc.core'))
        for metadata in (fr.InstalledMetadata(raw, fr.InstalledOrigin.APPLICATION),
                         replace(native, origin=fr.InstalledOrigin.HOME),
                         replace(native, build='other'), replace(native, addon_id='xbmc.gui'),
                         replace(native, xml_bytes=raw + b' ')):
            with self.assertRaises(fr.CaptureError): fi._builtin_metadata_edges(metadata, 'xbmc.core')
        for parser in (fr._parse_dependency_edges, fi._admission_dependency_edges):
            with self.assertRaises(fr.CaptureError): parser(raw, 'xbmc.core')


class PassiveParsingTests(unittest.TestCase):
    def test_numeric_ordering_supported_subset_and_malformed_refusal(self):
        for version, minimum, result in (('5.17', '5.17.0', False), ('5.17.0', '5.17', True),
                ('5.17.0', '5.17.0', True), ('5.10', '5.9', True), ('0.1.0', '0.1', True),
                ('01.002', '1.2', True), ('1.0.0.0', '1.0.0', True)):
            self.assertEqual(result, fr._builtin_version_satisfies(version, minimum))
        for value in ('', ' 1', '1 ', '1a', '1.0+matrix', '1..0', '1.', '-1', '1:2', '١', '2147483648'):
            self.assertFalse(fr._builtin_version_satisfies(value, '1'))
            if value: self.assertFalse(fr._builtin_version_satisfies('1', value))

    def test_builtin_minversion_refuses_capture_and_admission_even_optional(self):
        for aid in ('xbmc.gui', 'xbmc.core', 'kodi.resource', 'xbmc.python'):
            for attribute in ('minversion="999.0.0"', 'minversion=""', 'minversion="0.0.1"',
                              'x:minversion="1" xmlns:x="urn:x"'):
                for optional in ('true', 'false'):
                    payload = b1.xml('plugin.test', '1.0.0', '<requires><import addon="' + aid +
                        '" version="1.0.0" optional="' + optional + '" ' + attribute + '/></requires>')
                    for parser in (fr._parse_dependency_edges, fi._admission_dependency_edges):
                        with self.assertRaises(fr.CaptureError): parser(payload, 'plugin.test')
        payload = b1.xml('plugin.test', '1.0.0', '<requires><import addon="script.managed" minversion="1"/></requires>')
        self.assertEqual('script.managed', fr._parse_dependency_edges(payload, 'plugin.test')[0].addon_id)

    def test_real_capture_refuses_builtin_minversion(self):
        payload = b1.xml('plugin.test', '1.0.0', '<requires><import addon="xbmc.gui" minversion="999.0.0"/></requires>')
        with tempfile.TemporaryDirectory() as tmp:
            backend = fr.InMemoryInventoryBackend([capture._addon('plugin.test')], {'plugin.test': payload})
            result = fr.capture_frozen_build(backend=backend, store=ArtifactStore(Path(tmp)),
                root_addon_ids=['plugin.test'], build_id='passive', name='Passive', created_at='now')
            self.assertFalse(result.complete)
            self.assertTrue(result.errors)

    def test_ordinary_zip_and_repository_cpluff_cannot_use_native_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp))
            aid = 'plugin.test'
            raw = b1.xml(aid, '1.0.0', '<requires><c-pluff version="0.1"/></requires>')
            artifact = store.import_zip(capture._zip(aid, xml_bytes=raw), expected_addon_id=aid, expected_version='1.0.0')
            node = fr.AddonCaptureNode(aid, '1.0.0', 'xbmc.python.pluginsource', True,
                fr.ProvenanceStatus.UNKNOWN, artifact=artifact)
            m = fr.FrozenBuildManifest(1, 'passive', 'Passive', 'now', '21.3', 'macos', fr.CaptureStatus.COMPLETE, (node,))
            with self.assertRaises(fi.FrozenInstallValidationError): fi.validate_frozen_manifest(m, store)
            package = RepositoryPackage(aid, 'repository.test', '1.0.0', capture._zip(aid, xml_bytes=raw))
            with self.assertRaises(fr.CaptureError): fi._repository_required_addon_ids(None, packages=(package,))

    def test_repository_current_abi_floor_does_not_zero_pad(self):
        a = admission.BuiltinAdmissionTests()
        a.setUp()
        self.addCleanup(a.doCleanups)
        m = a.manifest()
        plan = fi.validate_frozen_manifest(m, a.artifacts)
        verified = a.verify(m)
        aid = m.addons[0].addon_id
        for minimum in ('5.17', '999.0.0'):
            package = RepositoryPackage(aid, 'repository.test', '2.0.0',
                old._zip(aid, '2.0.0', requires=(('xbmc.gui', minimum),)))
            with self.assertRaises(fi.FrozenInstallValidationError):
                fi._repository_package_required_dependencies(package, plan, {}, frozenset(), platform_versions=verified)


class PassiveProductPathTests(unittest.TestCase):
    def exercise(self, body, *, before_apply=None, wrong_build=False):
        native = PassiveFixture(self)
        if wrong_build: native.version['revision'] = 'unsupported'
        graph = standalone.StandalonePreparationTests.builtin_graph
        def pinned_graph(owner):
            backend = graph(owner)  # faithful captured GUI/core graph, synthetic managed installer
            backend.verify_builtin_requirement = native.backend.verify_builtin_requirement
            backend.read_verified_builtin_metadata = native.backend.read_verified_builtin_metadata
            return backend
        original = fi.FrozenInstallCoordinator.install_prepared
        def apply(owner, *args, **kwargs):
            if before_apply: before_apply(native)
            return original(owner, *args, **kwargs)
        helper = b1.B1PreparedApplyTests()
        self.addCleanup(helper.doCleanups)
        with patch.object(standalone.StandalonePreparationTests, 'builtin_graph', pinned_graph), \
                patch.object(fi.FrozenInstallCoordinator, 'install_prepared', apply):
            return helper.exercise(body)

    def assert_no_mutation(self, observed, backend):
        self.assertNotEqual('complete', observed['apply_outcome'], observed)
        for key in ('frozen_transaction_creates', 'config_transaction_creates', 'updater_mutations',
                    'installs', 'configuration_mutations'):
            self.assertEqual(0, observed[key], observed)
        self.assertFalse(observed['transaction_present'])
        self.assertEqual([], backend.enable_calls)

    def test_pinned_prepare_review_configured_apply_succeeds(self):
        _, _, observed = self.exercise('<requires><import addon="xbmc.gui" version="5.17.0"/></requires>')
        self.assertEqual('ready', observed['preparation'], observed)
        self.assertEqual('changes_ready', observed['preview'], observed)
        self.assertEqual('complete', observed['apply_outcome'], observed)
        self.assertGreater(observed['configuration_mutations'], 0)

    def test_wrong_build_refuses_before_all_mutation(self):
        _, backend, observed = self.exercise('<requires><import addon="xbmc.gui" version="5.17.0"/></requires>', wrong_build=True)
        self.assert_no_mutation(observed, backend)

    def test_changed_native_evidence_after_review_refuses_before_transaction(self):
        _, backend, observed = self.exercise('<requires><import addon="xbmc.gui" version="5.17.0"/></requires>',
            before_apply=lambda native: native.conditions.update({'System.AddonIsEnabled(xbmc.core)': False}))
        self.assertEqual('ready', observed['preparation'], observed)
        self.assertEqual('changes_ready', observed['preview'], observed)
        self.assert_no_mutation(observed, backend)

    def test_changed_descriptor_after_review_refuses_before_transaction(self):
        _, backend, observed = self.exercise('<requires><import addon="xbmc.gui" version="5.17.0"/></requires>',
            before_apply=lambda native: native.descriptor().write_bytes(native.descriptor().read_bytes() + b' '))
        self.assertEqual('ready', observed['preparation'], observed)
        self.assert_no_mutation(observed, backend)

    def test_malicious_builtin_minversion_refuses_before_all_mutation(self):
        _, backend, observed = self.exercise('<requires><import addon="xbmc.gui" version="5.17.0" minversion="999.0.0" optional="true"/></requires>')
        self.assert_no_mutation(observed, backend)
        self.assertNotEqual('ready', observed['preparation'], observed)


class PassiveMutationTests(unittest.TestCase):
    def mutate(self, module, owner, method, changes, test_class, test_name):
        source = textwrap.dedent(inspect.getsource(getattr(owner, method)))
        for before, after in changes:
            self.assertIn(before, source)
            source = source.replace(before, after)
        namespace = dict(module.__dict__)
        exec(compile(source, '<isolated pinned passive guard mutation>', 'exec'), namespace)
        with patch.object(owner, method, namespace[method]):
            result = unittest.TestResult()
            test_class(test_name).run(result)
        self.assertEqual([], result.errors, str(result.errors))
        self.assertEqual([], result.skipped)
        self.assertGreater(len(result.failures), 0, 'guard removal escaped security assertions')
        print('PASSIVE_MUTATION_ASSERTION_PASS ' + method + ':' + test_name, flush=True)

    def test_descriptor_sha_guard_is_detected(self):
        self.mutate(fi, fi.KodiRuntimeFrozenArtifactBackend, '_read_passive_builtin',
            [('hashlib.sha256(metadata.xml_bytes).hexdigest() != digest', 'False')],
            PassiveNativeTests, 'test_single_byte_and_additional_imports_or_metadata_refuse')

    def test_home_shadow_guard_is_detected(self):
        self.mutate(fr, fr.KodiInventoryBackend, 'read_application_builtin_metadata',
            [('if not unshadowed():', 'if False:'), ('or not unshadowed()', 'or False')],
            PassiveNativeTests, 'test_home_shadow_all_forms_refuse')

    def test_nonpadding_order_is_detected(self):
        # Existing zero-padding general comparator models the exact rejected behavior.
        with patch.object(fi, '_builtin_version_satisfies', fi._strict_version_satisfies):
            result = unittest.TestResult()
            PassiveNativeTests('test_abi_and_independent_minima_use_kodi_ordering').run(result)
        self.assertEqual([], result.errors, str(result.errors))
        self.assertTrue(result.failures)
        self.assertEqual([], result.skipped)
        print('PASSIVE_MUTATION_ASSERTION_PASS zero_padding:abi_minimum', flush=True)

    def test_minversion_guard_is_detected(self):
        source = inspect.getsource(fr._parse_dependency_edges)
        before = 'if target.startswith(("xbmc.", "kodi.")) and any('
        self.assertIn(before, source)
        namespace = dict(fr.__dict__)
        exec(compile(source.replace(before, 'if False and any('), '<isolated minversion mutation>', 'exec'), namespace)
        with patch.object(fr, '_parse_dependency_edges', namespace['_parse_dependency_edges']), \
                patch.object(fi, '_parse_dependency_edges', namespace['_parse_dependency_edges']):
            result = unittest.TestResult()
            PassiveProductPathTests('test_malicious_builtin_minversion_refuses_before_all_mutation').run(result)
        self.assertEqual([], result.errors, str(result.errors))
        self.assertTrue(result.failures)
        self.assertEqual([], result.skipped)
        print('PASSIVE_MUTATION_ASSERTION_PASS minversion:configured_apply', flush=True)

    def test_core_native_grant_boundary_is_detected(self):
        self.mutate(fi, fi, '_builtin_metadata_edges',
            [('isinstance(metadata, _PinnedPassiveMetadata)', 'True'),
             ('metadata.addon_id == addon_id and metadata.build == _PASSIVE_BUILD', 'True')],
            PassiveNativeTests, 'test_core_exception_requires_native_grant_and_exact_hash')


class VersionlessBuiltinTests(unittest.TestCase):
    def payload(self, aid='xbmc.gui', version=None, optional=None):
        attributes = '' if version is None else ' version="' + version + '"'
        if optional is not None: attributes += ' optional="' + optional + '"'
        return b1.xml('plugin.test', '1.0.0',
            '<requires><import addon="' + aid + '"' + attributes + '/></requires>')

    def test_missing_mandatory_gui_version_refuses_both_parsers(self):
        for parser in (fr._parse_dependency_edges, fi._admission_dependency_edges):
            with self.subTest(parser=parser.__name__):
                with self.assertRaises(fr.CaptureError): parser(self.payload(), 'plugin.test')

    def test_all_mandatory_builtin_spellings_require_nonblank_version(self):
        for aid in ('xbmc.gui', 'xbmc.core', 'kodi.resource', 'xbmc.python'):
            for version in (None, '', ' ', '  \t\n '):
                for optional in (None, 'false', 'False', 'FALSE'):
                    for parser in (fr._parse_dependency_edges, fi._admission_dependency_edges):
                        with self.subTest(aid=aid, version=version, optional=optional, parser=parser.__name__):
                            with self.assertRaises(fr.CaptureError):
                                parser(self.payload(aid, version, optional), 'plugin.test')

    def test_capture_and_exact_artifact_admission_refuse_missing_empty_and_blank(self):
        for aid in ('xbmc.gui', 'xbmc.core', 'kodi.resource', 'xbmc.python'):
            for version in (None, '', ' \t '):
                with self.subTest(aid=aid, version=version), tempfile.TemporaryDirectory() as tmp:
                    payload = self.payload(aid, version)
                    store = ArtifactStore(Path(tmp))
                    archive = capture._zip('plugin.test', xml_bytes=payload)
                    backend = fr.InMemoryInventoryBackend([capture._addon('plugin.test')],
                        {'plugin.test': payload}, package_cache={('plugin.test', '1.0.0'): [('test.zip', archive)]})
                    result = fr.capture_frozen_build(backend=backend, store=store,
                        root_addon_ids=['plugin.test'], build_id='versionless', name='Versionless', created_at='now')
                    self.assertFalse(result.complete)
                    self.assertTrue(result.errors)
                    artifact = store.import_zip(archive, expected_addon_id='plugin.test', expected_version='1.0.0')
                    node = fr.AddonCaptureNode('plugin.test', '1.0.0', 'xbmc.python.pluginsource', True,
                        fr.ProvenanceStatus.UNKNOWN, artifact=artifact,
                        dependency_edges=(fr.DependencyEdge(aid, '' if version is None else version),))
                    builtin = fr.AddonCaptureNode(aid, '1.0.0', 'system', True,
                        fr.ProvenanceStatus.UNKNOWN, system=True, status=fr.CaptureStatus.SYSTEM)
                    manifest = fr.FrozenBuildManifest(1, 'versionless', 'Versionless', 'now',
                        '21.3', 'macos', fr.CaptureStatus.COMPLETE, (node, builtin))
                    with self.assertRaisesRegex(fi.FrozenInstallValidationError, 'artifact unavailable') as refusal:
                        fi.validate_frozen_manifest(manifest, store)
                    self.assertIsInstance(refusal.exception.__cause__, fr.CaptureError)
                    self.assertIn('mandatory builtin dependency requires a version',
                        str(refusal.exception.__cause__))

    def test_repository_current_admission_refuses_all_versionless_builtins(self):
        a = admission.BuiltinAdmissionTests()
        a.setUp()
        self.addCleanup(a.doCleanups)
        manifest = a.manifest()
        plan = fi.validate_frozen_manifest(manifest, a.artifacts)
        verified = a.verify(manifest)
        for aid in ('xbmc.gui', 'xbmc.core', 'kodi.resource', 'xbmc.python'):
            for version in (None, '', '  '):
                payload = self.payload(aid, version)
                package = RepositoryPackage('plugin.test', 'repository.test', '1.0.0',
                    capture._zip('plugin.test', xml_bytes=payload))
                with self.subTest(aid=aid, version=version):
                    with self.assertRaises(fr.CaptureError):
                        fi._repository_required_addon_ids(None, packages=(package,))
                    with self.assertRaisesRegex(fi.FrozenInstallValidationError, 'dependency metadata'):
                        fi._repository_package_required_dependencies(package, plan, {}, frozenset(),
                            platform_versions=verified)

    def product(self, body):
        helper = PassiveProductPathTests()
        self.addCleanup(helper.doCleanups)
        return helper, helper.exercise(body)

    def test_versionless_mandatory_refuses_before_mutation(self):
        helper, (_, backend, observed) = self.product('<requires><import addon="xbmc.gui"/></requires>')
        helper.assert_no_mutation(observed, backend)
        self.assertNotEqual('ready', observed['preparation'], observed)
        self.assertNotEqual('changes_ready', observed['preview'], observed)

    def test_valid_version_and_versionless_optional_complete_configured_apply(self):
        for attributes in ('version="5.17.0"', 'optional="true"', 'optional="True"', 'optional="TRUE"'):
            with self.subTest(attributes=attributes):
                _, (_, _, observed) = self.product('<requires><import addon="xbmc.gui" ' + attributes + '/></requires>')
                self.assertEqual('ready', observed['preparation'], observed)
                self.assertEqual('changes_ready', observed['preview'], observed)
                self.assertEqual('complete', observed['apply_outcome'], observed)
                self.assertGreater(observed['configuration_mutations'], 0)

    def test_optional_and_managed_versionless_edges_and_valid_boolean_forms_preserved(self):
        for aid in ('xbmc.gui', 'xbmc.core', 'kodi.resource', 'xbmc.python'):
            for optional in ('true', 'True', 'TRUE'):
                for parser in (fr._parse_dependency_edges, fi._admission_dependency_edges):
                    edge, = parser(self.payload(aid, optional=optional), 'plugin.test')
                    self.assertTrue(edge.optional)
                    self.assertEqual('', edge.min_version)
            for optional in (None, 'false', 'False', 'FALSE'):
                for parser in (fr._parse_dependency_edges, fi._admission_dependency_edges):
                    edge, = parser(self.payload(aid, '1.0.0', optional), 'plugin.test')
                    self.assertFalse(edge.optional)
                    self.assertEqual('1.0.0', edge.min_version)
        for parser in (fr._parse_dependency_edges, fi._admission_dependency_edges):
            edge, = parser(self.payload('script.managed'), 'plugin.test')
            self.assertFalse(edge.optional)
            self.assertEqual('', edge.min_version)

    def test_new_guard_removal_is_detected_by_configured_apply_assertions(self):
        source = inspect.getsource(fr._parse_dependency_edges)
        before = 'if not optional and target.startswith(("xbmc.", "kodi.")) and not child.get("version", "").strip():'
        self.assertIn(before, source)
        namespace = dict(fr.__dict__)
        exec(compile(source.replace(before, 'if False:'), '<isolated mandatory builtin version mutation>', 'exec'), namespace)
        with patch.object(fr, '_parse_dependency_edges', namespace['_parse_dependency_edges']), \
                patch.object(fi, '_parse_dependency_edges', namespace['_parse_dependency_edges']):
            result = unittest.TestResult()
            VersionlessBuiltinTests('test_versionless_mandatory_refuses_before_mutation').run(result)
        self.assertEqual([], result.errors, str(result.errors))
        self.assertEqual([], result.skipped)
        self.assertGreater(len(result.failures), 0, 'mandatory version guard removal escaped assertions')
        print('VERSIONLESS_MUTATION_ASSERTION_PASS mandatory_builtin_version:configured_apply', flush=True)
