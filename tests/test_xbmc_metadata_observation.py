"""Offline focused tests for the fixed xbmc.metadata diagnostic (not production support).

Uses the exact-source platform fixture and synthetic native Kodi authorities.
Nothing here stages, launches or contacts Test.app, normal Kodi or a device.
"""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from resources.lib import frozen as fr, frozen_install as fi
from tools import bm023a_adapter_support as support, bm_test_app as host
from tests.test_d028_platform_check import Fixture, SECRET, snapshot

XBMC = 'xbmc.metadata'
DESCRIPTOR = (
    '<addon id="xbmc.metadata" version="1.0.0" name="Metadata fixture" provider-name="Test">'
    '<requires><import addon="xbmc.python" version="3.0.0"/>'
    '<import addon="xbmc.core" version="0.1.0" optional="true"/></requires>'
    '<backwards-compatibility abi="1.0.0"/>'
    '<extension point="xbmc.addon.metadata"><summary lang="en_GB">Fixture</summary></extension>'
    '</addon>').encode('utf-8')
MODE = 'xbmc_metadata_observe'


def make_fixture(case, *, xml=DESCRIPTOR, version='1.0.0', registered=True, enabled=True):
    """Exact-source adapter plus one synthetic application-bundled xbmc.metadata."""
    f = Fixture(case)
    descriptor = f.native.app / XBMC / 'addon.xml'
    descriptor.parent.mkdir()
    descriptor.write_bytes(xml)
    f.native.info[XBMC] = dict(id=XBMC, version=version, path=str(descriptor.parent), type='unknown')
    f.native.conditions['System.HasAddon(' + XBMC + ')'] = registered
    f.native.conditions['System.AddonIsEnabled(' + XBMC + ')'] = enabled
    return f


def observe(f):
    with f.imports():
        return support.read_xbmc_metadata_observation(f.addon, f.driver, f.binding)


class XbmcMetadataObservationTests(unittest.TestCase):
    def test_observed_success_reports_facts_without_pin_usability_or_allowlist_grant(self):
        f = make_fixture(self)
        before = snapshot(f.native.root)
        result = observe(f)
        self.assertTrue(result['ok'], result)
        obs = result['xbmc_metadata_observation']
        self.assertEqual('observed', obs['status'])
        self.assertIsNone(obs['failure_category'])
        self.assertEqual('not_established', obs['functional_usability'])
        self.assertEqual('not_qualified', obs['qualification'])
        self.assertEqual({'status': 'enabled', 'has_addon': True, 'enabled': True,
            'json_rpc_listed': False}, obs['registration'])
        self.assertEqual({'addon_id': XBMC, 'version': '1.0.0', 'reported_type': 'unknown'}, obs['identity'])
        self.assertEqual({'status': 'application'}, obs['origin'])
        self.assertEqual(hashlib.sha256(DESCRIPTOR).hexdigest(), obs['descriptor']['sha256'])
        self.assertEqual('observed_unpinned', obs['descriptor']['trust'])
        self.assertEqual(('1.0.0', '1.0.0'), (obs['descriptor']['version'], obs['descriptor']['abi']))
        self.assertEqual([
            {'addon_id': 'xbmc.python', 'minimum_version': '3.0.0', 'optional': False},
            {'addon_id': 'xbmc.core', 'minimum_version': '0.1.0', 'optional': True},
        ], obs['descriptor']['requirements'])
        self.assertEqual(['xbmc.addon.metadata'], obs['descriptor']['extension_points'])
        self.assertEqual({'status': 'verified', 'major': 21, 'minor': 3,
            'revision': support.PLATFORM_BUILD}, obs['build'])
        self.assertEqual(obs, support.project_xbmc_metadata_observation(obs))
        self.assertEqual(before, snapshot(f.native.root))
        self.assertEqual([], f.calls)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(str(f.native.root), json.dumps(result))

    def test_xbmc_metadata_is_not_a_platform_or_passive_trust_identity(self):
        self.assertNotIn(XBMC, support.PLATFORM_IDS)
        self.assertNotIn(XBMC, fi._PASSIVE_BUILTINS)
        self.assertEqual(('xbmc.core', 'xbmc.gui', 'kodi.resource'), tuple(fi._PASSIVE_BUILTINS))

    def test_missing_provider_refuses_without_reading_descriptor(self):
        f = make_fixture(self, registered=False, enabled=False)
        result = observe(f)
        self.assertFalse(result['ok'])
        obs = result['xbmc_metadata_observation']
        self.assertEqual(('refused', 'registration_unverified'), (obs['status'], obs['failure_category']))
        self.assertEqual({'status': 'absent', 'has_addon': False, 'enabled': False,
            'json_rpc_listed': False}, obs['registration'])
        self.assertIsNone(obs['identity'])
        self.assertEqual({'status': 'unverified'}, obs['origin'])
        self.assertIsNone(obs['descriptor']['sha256'])
        self.assertEqual(obs, support.project_xbmc_metadata_observation(obs))

    def test_registered_but_disabled_provider_refuses(self):
        f = make_fixture(self, enabled=False)
        obs = observe(f)['xbmc_metadata_observation']
        self.assertEqual(('refused', 'registration_unverified'), (obs['status'], obs['failure_category']))
        self.assertEqual('disabled', obs['registration']['status'])
        self.assertIsNone(obs['descriptor']['sha256'])

    def test_build_mismatch_refuses_before_any_descriptor_fact(self):
        f = make_fixture(self)
        wrong = {'result': {'version': dict(major=21, minor=3, revision='20990101-deadbeef', tag='stable')}}
        with patch.object(f.native.backend, '_rpc', lambda method, params: wrong):
            result = observe(f)
        self.assertFalse(result['ok'])
        obs = result['xbmc_metadata_observation']
        self.assertEqual(('refused', 'runtime_or_build_unverified'), (obs['status'], obs['failure_category']))
        self.assertEqual({'status': 'unverified', 'major': None, 'minor': None, 'revision': None}, obs['build'])
        self.assertIsNone(obs['descriptor']['sha256'])
        self.assertEqual(obs, support.project_xbmc_metadata_observation(obs))

    def test_home_shadow_blocks_application_origin(self):
        f = make_fixture(self)
        (f.native.home / XBMC).mkdir()
        obs = observe(f)['xbmc_metadata_observation']
        self.assertEqual(('refused', 'origin_unverified'), (obs['status'], obs['failure_category']))
        self.assertEqual({'status': 'unverified'}, obs['origin'])
        self.assertIsNone(obs['descriptor']['sha256'])

    def test_path_outside_the_application_root_refuses(self):
        f = make_fixture(self)
        elsewhere = f.native.home / 'elsewhere' / XBMC
        elsewhere.mkdir(parents=True)
        (elsewhere / 'addon.xml').write_bytes(DESCRIPTOR)
        f.native.info[XBMC]['path'] = str(elsewhere)
        obs = observe(f)['xbmc_metadata_observation']
        self.assertEqual(('refused', 'origin_unverified'), (obs['status'], obs['failure_category']))
        self.assertIsNone(obs['descriptor']['sha256'])

    def test_identity_mismatch_between_runtime_and_descriptor_refuses(self):
        f = make_fixture(self, version='2.0.0')
        obs = observe(f)['xbmc_metadata_observation']
        self.assertEqual(('refused', 'metadata_invalid'), (obs['status'], obs['failure_category']))
        self.assertIsNone(obs['descriptor']['sha256'])

    def test_malformed_descriptor_shapes_refuse_as_metadata_invalid(self):
        broken = {
            'missing_abi': DESCRIPTOR.replace(b'<backwards-compatibility abi="1.0.0"/>', b''),
            'two_requires': DESCRIPTOR.replace(b'</requires>', b'</requires><requires/>'),
            'bad_optional': DESCRIPTOR.replace(b'optional="true"', b'optional="maybe"'),
            'wrong_id': DESCRIPTOR.replace(b'id="xbmc.metadata"', b'id="xbmc.other"'),
        }
        for name, xml in broken.items():
            with self.subTest(name):
                f = make_fixture(self, xml=xml)
                obs = observe(f)['xbmc_metadata_observation']
                self.assertEqual(('refused', 'metadata_invalid'), (obs['status'], obs['failure_category']))
                self.assertIsNone(obs['descriptor']['sha256'])

    def test_source_change_refuses_before_runtime_reads(self):
        f = make_fixture(self)
        (f.addon / 'service.py').write_bytes(b'# changed after binding\n')
        obs = observe(f)['xbmc_metadata_observation']
        self.assertEqual(('refused', 'source_binding_invalid'), (obs['status'], obs['failure_category']))
        self.assertIsNone(obs['source'])
        self.assertIsNone(obs['identity'])

    def test_projection_rejects_unpinned_usable_or_contradictory_claims(self):
        obs = observe(make_fixture(self))['xbmc_metadata_observation']
        cases = {
            'usable_claim': lambda o: o.update(functional_usability='usable'),
            'pinned_trust': lambda o: o['descriptor'].update(trust='pinned'),
            'observed_with_failure': lambda o: o.update(failure_category='metadata_invalid'),
            'extra_path_field': lambda o: o.update(path='/unsafe/path'),
            'wrong_identity': lambda o: o['identity'].update(addon_id='xbmc.python'),
            'absent_but_enabled': lambda o: o['registration'].update(status='absent'),
            'unknown_failure_text': lambda o: o.update(status='refused', failure_category='exception text'),
            'unavailable_mismatch': lambda o: o.update(status='unavailable'),
            'bad_digest': lambda o: o['descriptor'].update(sha256='x'),
            'unbounded_requirement': lambda o: o['descriptor'].update(requirements=[
                {'addon_id': 'a.b', 'minimum_version': '1', 'optional': False, 'extra': 1}]),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                copy = json.loads(json.dumps(obs))
                mutate(copy)
                with self.assertRaises(ValueError):
                    support.project_xbmc_metadata_observation(copy)

    def test_mode_tokens_are_exact_and_fixed(self):
        for token in (MODE, '?mode=' + MODE):
            self.assertEqual(MODE, support.parse_adapter_mode([token]))
        for args in ([MODE, 'install'], ['xbmc.metadata'], ['?mode=' + MODE + '&method=install'],
                     [MODE + ';install']):
            with self.subTest(args=args):
                with self.assertRaises(support.AdapterBootstrapError):
                    support.parse_adapter_mode(args)
        self.assertEqual(MODE, support.identify_adapter_result({}, MODE)['adapter_mode'])

    def test_entrypoint_writes_only_the_fixed_sanitized_result(self):
        f = make_fixture(self)
        before = snapshot(f.native.root)
        result = f.entrypoint(MODE)
        self.assertTrue(result['ok'], result)
        self.assertEqual(MODE, result['adapter_mode'])
        after = snapshot(f.native.root)
        self.assertEqual({str((f.data / 'bm023a_live_result.json').relative_to(f.native.root))},
            {key for key in set(before) | set(after) if before.get(key) != after.get(key)})
        self.assertEqual(result['xbmc_metadata_observation'],
            support.project_xbmc_metadata_observation(result['xbmc_metadata_observation']))
        self.assertNotIn(str(f.native.root), json.dumps(result))


MALFORMED_TOKENS = (
    '', ' ' + MODE, MODE + ' ', MODE + '\n', MODE + 'x', MODE + '/', MODE + ';install',
    '?' + MODE, '?mode=', '?mode=' + MODE + ' ', '?mode=' + MODE + '&method=install',
    'XBMC_METADATA_OBSERVE', 'xbmc_metadata', 'xbmc.metadata', 'xbmc.python',
    '?mode=xbmc.metadata', '?mode=xbmc.python',
)
GATED_MALFORMED_ARGS = (
    [MODE, 'install'], [MODE + ';install'], ['?mode=' + MODE + '&method=install'],
    [MODE + 'x'], [MODE + ' '], ['?mode=' + MODE + '?'], [MODE, 'xbmc.metadata'],
    ['?mode=' + MODE, 'xbmc.python'],
)


class XbmcMetadataArgumentNegativeTests(unittest.TestCase):
    def test_malformed_and_unauthorized_tokens_never_parse_as_the_mode(self):
        for token in MALFORMED_TOKENS:
            with self.subTest(token=token):
                with self.assertRaises(support.AdapterBootstrapError):
                    support.parse_adapter_mode([token])
        for args in ([MODE, MODE], [MODE, 'install'], [MODE, 'xbmc.metadata'], []):
            with self.subTest(args=args):
                with self.assertRaises(support.AdapterBootstrapError):
                    support.parse_adapter_mode(args)

    def test_expanded_or_malformed_gated_arguments_refuse_before_any_import_or_write(self):
        for args in GATED_MALFORMED_ARGS:
            with self.subTest(args=args):
                f = make_fixture(self)
                before = snapshot(f.native.root)
                with self.assertRaises(SystemExit):
                    f.entrypoint(args)
                self.assertEqual(0, f.factory_calls)
                self.assertEqual(before, snapshot(f.native.root))

    def test_reader_never_substitutes_another_provider_when_xbmc_metadata_is_absent(self):
        f = make_fixture(self, registered=False, enabled=False)
        f.native.conditions['System.HasAddon(xbmc.python)'] = True
        f.native.conditions['System.AddonIsEnabled(xbmc.python)'] = True
        obs = observe(f)['xbmc_metadata_observation']
        self.assertEqual(('refused', 'registration_unverified'), (obs['status'], obs['failure_category']))
        self.assertIsNone(obs['identity'])
        self.assertIsNone(obs['descriptor']['sha256'])

    def test_production_builtin_reader_still_refuses_xbmc_metadata(self):
        f = make_fixture(self)
        # Call the class method directly; the fixture wraps the instance attribute.
        self.assertIsNone(fi.KodiRuntimeFrozenArtifactBackend.read_verified_builtin_metadata(
            f.native.backend, fr.DependencyEdge(XBMC, '1.0.0')))


class XbmcMetadataOriginNegativeTests(unittest.TestCase):
    def test_unsafe_application_root_and_home_variants_fail_closed(self):
        import os
        import shutil

        def dangling_home_shadow(f):
            os.symlink(f.native.root / 'missing-target', f.native.home / XBMC)

        def symlinked_application_directory(f):
            outside = f.native.root / 'outside' / XBMC
            outside.mkdir(parents=True)
            (outside / 'addon.xml').write_bytes(DESCRIPTOR)
            shutil.rmtree(f.native.app / XBMC)
            os.symlink(outside, f.native.app / XBMC)

        def symlinked_descriptor(f):
            outside = f.native.root / 'outside-addon.xml'
            outside.write_bytes(DESCRIPTOR)
            (f.native.app / XBMC / 'addon.xml').unlink()
            os.symlink(outside, f.native.app / XBMC / 'addon.xml')

        def oversized_descriptor(f):
            (f.native.app / XBMC / 'addon.xml').write_bytes(
                DESCRIPTOR + b'<!-- ' + b'x' * (2 * 1024 * 1024) + b' -->')

        for name, mutate in (('dangling_home_shadow', dangling_home_shadow),
                             ('symlinked_application_directory', symlinked_application_directory),
                             ('symlinked_descriptor', symlinked_descriptor),
                             ('oversized_descriptor', oversized_descriptor)):
            with self.subTest(name):
                f = make_fixture(self)
                mutate(f)
                obs = observe(f)['xbmc_metadata_observation']
                self.assertEqual(('refused', 'origin_unverified'), (obs['status'], obs['failure_category']))
                self.assertEqual({'status': 'unverified'}, obs['origin'])
                self.assertIsNone(obs['descriptor']['sha256'])


class XbmcMetadataHostTests(unittest.TestCase):
    def test_host_registers_the_mode_and_projects_only_consistent_results(self):
        self.assertIn(MODE, host.ADAPTER_MODES)
        self.assertIn(MODE, host.DEFAULT_TIMEOUTS)
        observed = observe(make_fixture(self))
        raw = dict(observed, adapter_mode=MODE)
        projected, _ = host.project_adapter_result(MODE, raw)
        self.assertTrue(projected['ok'])
        self.assertEqual('observed', projected['xbmc_metadata_observation']['status'])
        with self.assertRaises(host.HelperError):
            host.project_adapter_result(MODE, dict(raw, ok=False))
        with self.assertRaises(host.HelperError):
            host.project_adapter_result(MODE, {'ok': True, 'adapter_mode': MODE})
        failure, _ = host.project_adapter_result(MODE, {
            'ok': False, 'adapter_mode': MODE, 'error_type': 'ValueError',
            'adapter_stage': 'XBMC_METADATA_OBSERVE', 'failing_callable': 'read_xbmc_metadata_observation',
            'failure_category': 'invalid_input'})
        self.assertFalse(failure['ok'])

    def test_host_refuses_the_mode_without_source_identity_or_over_tcp(self):
        for kwargs in ({'git_repo': None, 'rpc_transport': 'http'},
                       {'git_repo': Path('.'), 'rpc_transport': 'tcp'}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(host.HelperError):
                    host.run_adapter(None, mode=MODE, manifest={}, manifest_sha256='', rpc={},
                        timeout=1, **kwargs)


if __name__ == '__main__':
    unittest.main()
