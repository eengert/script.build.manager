"""D-032 pinned passive compatibility for xbmc.metadata 2.1.0 (offline, synthetic authority).

The descriptor is the exact Kodi 21.3 bundled addon.xml recorded in
fixtures/d028_passive/README.md. Kernel, bundle and Kodi runtime calls are replaced
by PassiveFixture's disposable doubles, so no Kodi process, Test.app, profile or
device is touched. Passive registration proves registration, identity, origin,
build and descriptor only. It proves no functional usability of the scraper
extension points.
"""
import hashlib
import unittest
from types import MappingProxyType
from unittest.mock import patch

from resources.lib import frozen as fr, frozen_install as fi
from tests.test_d028_passive import PINS, PassiveFixture

XBMC = 'xbmc.metadata'
PIN = ('2.1.0', '1.0', '95082198599c695a91d2aefb072f0457e9ffd5eb3f2dc1587fa58159750db1b6')
BUILD = '20251031-a3a448d26b'


def replacement_pins(**changes):
    """A test-only replacement pin table; the production mapping is never edited."""
    return patch.object(fi, '_PASSIVE_BUILTINS', MappingProxyType({**fi._PASSIVE_BUILTINS, **changes}))


class XbmcMetadataPinTests(unittest.TestCase):
    def setUp(self):
        self.f = PassiveFixture(self)

    def test_pin_is_exact_native_identity_and_bundled_bytes(self):
        self.assertEqual(PIN, PINS[XBMC])
        self.assertEqual(PIN, fi._PASSIVE_BUILTINS[XBMC])
        self.assertEqual(PIN[2], hashlib.sha256(self.f.descriptor(XBMC).read_bytes()).hexdigest())
        self.assertEqual(BUILD, fi._PASSIVE_BUILD)

    def test_positive_read_returns_pinned_application_metadata(self):
        metadata = self.f.read(XBMC)
        self.assertIsInstance(metadata, fi._PinnedPassiveMetadata)
        self.assertEqual(fr.InstalledOrigin.APPLICATION, metadata.origin)
        self.assertEqual(self.f.descriptor(XBMC).read_bytes(), metadata.xml_bytes)
        self.assertEqual((XBMC, BUILD), (metadata.addon_id, metadata.build))
        for minimum in ('', '1.0', '2.0', '2.1', '2.1.0'):
            with self.subTest(minimum=minimum):
                self.assertIsNotNone(self.f.read(XBMC, minimum=minimum))

    def test_only_mandatory_core_edge_is_derived_and_core_grant_does_not_extend(self):
        edges = fi._builtin_metadata_edges(self.f.read(XBMC), XBMC)
        self.assertEqual([('xbmc.core', '0.1.0', False)],
                         [(e.addon_id, e.min_version, e.optional) for e in edges])
        self.assertEqual((XBMC,), edges[0].required_by)
        # The empty-edge exception is granted to the exact xbmc.core descriptor alone.
        self.assertEqual((), fi._builtin_metadata_edges(self.f.read('xbmc.core'), 'xbmc.core'))

    def test_descriptor_mismatch_refuses(self):
        descriptor = self.f.descriptor(XBMC)
        original = descriptor.read_bytes()
        mutations = (
            original + b'\n',
            original.replace(b'version="2.1.0"', b'version="2.1.1"', 1),
            original.replace(b'abi="1.0"', b'abi="1.1"', 1),
            original.replace(b'version="0.1.0"', b'version="0.1.1"', 1),
            original.replace(b'addon="xbmc.core"', b'addon="xbmc.gui"', 1),
            original.replace(b'</requires>', b'<import addon="xbmc.python" version="3.0.0"/></requires>', 1),
            original.replace(b'</addon>', b'<extension point="xbmc.addon.metadata"/></addon>', 1),
            original.replace(b'scraper.tvshows', b'scraper.tv', 1),
        )
        for index, data in enumerate(mutations):
            with self.subTest(mutation=index):
                self.assertNotEqual(original, data)
                descriptor.write_bytes(data)
                self.assertIsNone(self.f.read(XBMC))
        descriptor.write_bytes(original)
        self.assertIsNotNone(self.f.read(XBMC))

    def test_installed_version_mismatch_refuses(self):
        info = self.f.info[XBMC]
        for version in ('2.0.0', '2.1.1', '2.1', '', None, 'bad'):
            with self.subTest(installed_version=version):
                original = info['version']
                info['version'] = version
                self.assertIsNone(self.f.read(XBMC))
                info['version'] = original
        self.assertIsNotNone(self.f.read(XBMC))

    def test_pin_version_and_abi_mismatch_refuses_exact_bytes(self):
        digest = PIN[2]
        for pin in (('2.2.0', '1.0', digest), ('2.1.0', '2.0', digest), ('2.1.0', '1.1', digest)):
            with self.subTest(pin=pin), replacement_pins(**{XBMC: pin}):
                self.assertIsNone(self.f.read(XBMC))

    def test_unsupported_or_malformed_minimum_refuses(self):
        for minimum in ('2.1.1', '2.2.0', '999.0.0', '0.9', '0.9.9', '1', '2..1', 'bad', '2.1.0+x',
                        '2147483648.0'):
            with self.subTest(minimum=minimum):
                self.assertIsNone(self.f.read(XBMC, minimum=minimum))

    def test_incorrect_type_identity_or_path_refuses(self):
        info = self.f.info[XBMC]
        for key, value in (('type', 'xbmc.metadata'), ('type', 'kodi.metadata'),
                           ('type', 'xbmc.python.script'), ('type', None), ('type', ''),
                           ('type', 'UNKNOWN'), ('id', 'xbmc.core'), ('id', 'xbmc.metadata.scraper'),
                           ('path', str(self.f.home / XBMC)), ('path', str(self.f.app / 'xbmc.metadata-evil')),
                           ('path', 'relative'), ('path', None)):
            with self.subTest(key=key, value=value):
                original = info[key]
                info[key] = value
                self.assertIsNone(self.f.read(XBMC))
                info[key] = original
        self.assertIsNotNone(self.f.read(XBMC))

    def test_wrong_application_root_refuses(self):
        other = self.f.root / 'unrelated/addons'
        other.mkdir(parents=True)
        self.f.backend._application_addons_dir = lambda: other
        self.assertIsNone(self.f.read(XBMC))

    def test_disabled_unregistered_or_unconstructible_refuses(self):
        for key in ('System.HasAddon(xbmc.metadata)', 'System.AddonIsEnabled(xbmc.metadata)'):
            for value in (False, None, 1, 'true'):
                with self.subTest(condition=key, value=value):
                    self.f.conditions[key] = value
                    self.assertIsNone(self.f.read(XBMC))
            self.f.conditions[key] = True
        self.assertIsNotNone(self.f.read(XBMC))
        self.f.api.Addon = lambda aid: (_ for _ in ()).throw(RuntimeError('unavailable'))
        self.assertIsNone(self.f.read(XBMC))

    def test_home_shadow_forms_refuse(self):
        shadow = self.f.home / XBMC
        original = self.f.descriptor(XBMC).read_bytes()
        for kind in ('equal', 'higher', 'file', 'symlink', 'dangling'):
            with self.subTest(kind=kind):
                if kind in ('equal', 'higher'):
                    shadow.mkdir()
                    data = original if kind == 'equal' else original.replace(b'version="2.1.0"', b'version="9.0.0"', 1)
                    (shadow / 'addon.xml').write_bytes(data)
                elif kind == 'file':
                    shadow.write_bytes(b'shadow')
                elif kind == 'symlink':
                    shadow.symlink_to(self.f.descriptor(XBMC).parent, target_is_directory=True)
                else:
                    shadow.symlink_to(self.f.root / 'missing')
                try:
                    self.assertIsNone(self.f.read(XBMC))
                finally:
                    if shadow.is_symlink() or shadow.is_file():
                        shadow.unlink()
                    else:
                        (shadow / 'addon.xml').unlink()
                        shadow.rmdir()
        self.assertIsNotNone(self.f.read(XBMC))

    def test_wrong_kodi_build_refuses(self):
        for key, value in (('revision', '20251031-other'), ('revision', None), ('major', 22),
                           ('minor', 2), ('tag', 'alpha')):
            with self.subTest(key=key, value=value):
                original = self.f.version[key]
                self.f.version[key] = value
                self.assertIsNone(self.f.read(XBMC))
                self.f.version[key] = original
        with patch.object(fi, '_PASSIVE_BUILD', '20251031-other'):
            self.assertIsNone(self.f.read(XBMC))
        self.assertIsNotNone(self.f.read(XBMC))

    def test_descriptor_change_during_observation_refuses(self):
        original_construct = self.f.api.Addon
        calls = []

        def construct(aid):
            calls.append(aid)
            if len(calls) == 2:
                self.f.descriptor(XBMC).write_bytes(self.f.descriptor(XBMC).read_bytes() + b' ')
            return original_construct(aid)

        self.f.api.Addon = construct
        self.assertIsNone(self.f.read(XBMC))
