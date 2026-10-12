"""Synthetic owner backend contract; never invokes live Kodi APIs."""
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from resources.lib.create_owner_observation import OwnerObservation, observe_redlight_owner
from resources.lib.frozen_install import FrozenInstalledAddon, KodiRuntimeFrozenArtifactBackend
from resources.lib.redlight_resource import REDLIGHT_ADDON_ID


class OwnerObservationTests(unittest.TestCase):
    def test_exact_backend_contract_and_disabled_is_known(self):
        for version in ('2.6.8', '2.6.9'):
            for enabled in (True, False):
                backend = Mock(spec_set=['get_addon_details'])
                backend.get_addon_details.return_value = FrozenInstalledAddon(REDLIGHT_ADDON_ID, version, enabled)
                result = observe_redlight_owner(backend)
                self.assertTrue(result.known)
                self.assertEqual((result.version, result.enabled), (version, enabled))
                backend.get_addon_details.assert_called_once_with(REDLIGHT_ADDON_ID)

    def test_missing_wrong_owner_and_malformed_fields_are_unknown(self):
        valid = FrozenInstalledAddon(REDLIGHT_ADDON_ID, '2.6.8', False)
        rows = [None, object(), replace(valid, addon_id='plugin.other')]
        rows += [replace(valid, enabled=x) for x in (None, 0, 1, '', 'false', [], {})]
        rows += [replace(valid, version=x) for x in (None, '', 268, 'SECRET/private', '2.6.8\n', '1.' + '0'*40)]
        for row in rows:
            with self.subTest(row_type=type(row).__name__):
                backend = Mock(spec_set=['get_addon_details'])
                backend.get_addon_details.return_value = row
                self.assertEqual(observe_redlight_owner(backend), OwnerObservation())

    def test_exception_payload_does_not_escape(self):
        backend = Mock(spec_set=['get_addon_details'])
        backend.get_addon_details.side_effect = RuntimeError('SECRET/private/profile')
        self.assertEqual(repr(observe_redlight_owner(backend)), 'OwnerObservation(version=None, enabled=None)')

    def test_constructor_refuses_partial_and_coerced_evidence(self):
        for version, enabled in (('2.6.8', None), (None, False), ('2.6.8', 0), ('SECRET', True)):
            with self.assertRaisesRegex(ValueError, '^invalid owner observation$'):
                OwnerObservation(version, enabled)

    def test_existing_kodi_backend_with_injected_rpc_only(self):
        backend = KodiRuntimeFrozenArtifactBackend()
        with patch.object(backend, '_rpc', return_value={'result': {'addon': {
                'addonid': REDLIGHT_ADDON_ID, 'version': '2.6.8', 'enabled': False}}}) as rpc, \
                patch.object(backend, '_xbmc', side_effect=AssertionError('live API')), \
                patch('os.mkdir', side_effect=AssertionError('creation')):
            self.assertEqual(observe_redlight_owner(backend), OwnerObservation('2.6.8', False))
        rpc.assert_called_once_with('Addons.GetAddonDetails', {
            'addonid': REDLIGHT_ADDON_ID, 'properties': ['enabled', 'version', 'broken']})

    def test_each_call_is_fresh_and_no_mutator_is_accessible(self):
        backend = Mock(spec_set=['get_addon_details'])
        backend.get_addon_details.side_effect = [FrozenInstalledAddon(REDLIGHT_ADDON_ID, '2.6.8', True), None]
        self.assertTrue(observe_redlight_owner(backend).enabled)
        self.assertIsNone(observe_redlight_owner(backend).enabled)
        self.assertEqual(len(backend.mock_calls), 2)
