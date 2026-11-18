"""Capture-to-admission builtin closure; synthetic authority only, no native calls."""
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch

from resources.lib.artifacts import ArtifactStore
from resources.lib.frozen import (
    CaptureStatus, InstalledMetadata, InstalledOrigin, InMemoryInventoryBackend, KodiInventoryBackend,
    capture_frozen_build,
)
from resources.lib.frozen_install import (
    FrozenPlatformRequirementError, validate_frozen_manifest, verify_platform_requirements,
)
from tests.builtin_evidence import SyntheticBuiltinBackend
from tests.test_frozen import _addon, _xml, _zip


class CaptureBuiltinClosureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ArtifactStore(Path(temp.name))
        self.native = SyntheticBuiltinBackend()
        xml = _xml('plugin.capture', imports=(('xbmc.python', '3.0.0', False),))
        self.inventory = InMemoryInventoryBackend(
            [_addon('plugin.capture')], {'plugin.capture': xml},
            package_cache={('plugin.capture', '1.0.0'): [('capture.zip', _zip('plugin.capture', xml_bytes=xml))]},
        )
        self.inventory.read_verified_builtin_metadata = self.native.read_verified_builtin_metadata

    def capture(self):
        return capture_frozen_build(backend=self.inventory, store=self.store,
            root_addon_ids=('plugin.capture',), build_id='closure', name='Closure', created_at='now')

    def admit(self, manifest):
        plan = validate_frozen_manifest(manifest, self.store)
        verified = verify_platform_requirements(plan, self.native,
            planned_versions={'plugin.capture': '1.0.0'})
        return plan, verified

    def test_capture_records_python_core_closure_and_existing_admission_passes(self):
        result = self.capture()
        self.assertTrue(result.complete, result.errors)
        nodes = {n.addon_id: n for n in result.manifest.addons}
        self.assertIn('xbmc.core', nodes)
        self.assertEqual('3.0.1', nodes['xbmc.python'].version)
        self.assertEqual('0.1.0', nodes['xbmc.core'].version)
        edge, = nodes['xbmc.python'].dependency_edges
        self.assertEqual(('xbmc.core', '0.1.0', False), (edge.addon_id, edge.min_version, edge.optional))
        for aid in ('xbmc.python', 'xbmc.core'):
            self.assertTrue(nodes[aid].system)
            self.assertEqual(CaptureStatus.SYSTEM, nodes[aid].status)
            self.assertIsNone(nodes[aid].artifact)
        plan, verified = self.admit(result.manifest)
        self.assertEqual({'xbmc.python', 'xbmc.core'}, set(verified.builtin_versions))
        self.assertEqual(['plugin.capture'], [n.addon_id for n in plan.install_order])
        self.assertEqual([], self.native.install_calls)
        self.assertEqual([], self.native.enable_calls)
        # Existing target closure enforcement still rejects the historical shape.
        incomplete = replace(result.manifest, addons=tuple(
            replace(n, dependency_edges=()) if n.addon_id == 'xbmc.python' else n
            for n in result.manifest.addons if n.addon_id != 'xbmc.core'))
        with self.assertRaises(FrozenPlatformRequirementError):
            self.admit(incomplete)

    def test_missing_or_untrusted_required_metadata_never_completes(self):
        reader = self.native.read_verified_builtin_metadata
        for aid in ('xbmc.python', 'xbmc.core'):
            for mode in ('missing', 'home', 'raises'):
                with self.subTest(aid=aid, mode=mode):
                    def read(edge):
                        metadata = reader(edge)
                        if edge.addon_id != aid:
                            return metadata
                        if mode == 'raises':
                            raise RuntimeError('synthetic refusal')
                        if mode == 'missing':
                            return None
                        return InstalledMetadata(metadata.xml_bytes, InstalledOrigin.HOME)
                    self.inventory.read_verified_builtin_metadata = read
                    result = self.capture()
                    self.assertFalse(result.complete)
                    self.assertNotEqual(CaptureStatus.COMPLETE, result.manifest.capture_status)
                    self.assertTrue(result.errors)

    def test_inventory_xml_is_not_builtin_authority(self):
        del self.inventory.read_verified_builtin_metadata
        self.inventory.addon_xml['xbmc.python'] = b'<addon id="xbmc.python" version="3.0.1"/>'
        self.assertFalse(self.capture().complete)

    def test_malformed_incompatible_and_cyclic_builtin_metadata_refuse(self):
        reader = self.native.read_verified_builtin_metadata
        for mode in ('malformed', 'identity', 'abi', 'minimum', 'core_missing', 'cycle'):
            with self.subTest(mode=mode):
                def read(edge):
                    metadata = reader(edge)
                    if edge.addon_id == 'xbmc.python':
                        raw = metadata.xml_bytes
                        if mode == 'malformed':
                            raw = b'<addon'
                        elif mode == 'identity':
                            raw = raw.replace(b'id="xbmc.python"', b'id="xbmc.other"')
                        elif mode == 'abi':
                            raw = raw.replace(b'abi="3.0.0"', b'abi="4.0.0"')
                        elif mode == 'minimum':
                            raw = raw.replace(b'addon="xbmc.core" version="0.1.0"',
                                              b'addon="xbmc.core" version="999.0.0"')
                        elif mode == 'core_missing':
                            raw = raw.replace(b'<import addon="xbmc.core" version="0.1.0"/>', b'')
                        metadata = InstalledMetadata(raw, metadata.origin)
                    elif mode == 'cycle':
                        metadata = InstalledMetadata(metadata.xml_bytes.replace(b'</addon>',
                            b'<requires><import addon="xbmc.python" version="3.0.0"/></requires></addon>'), metadata.origin)
                    return metadata
                self.inventory.read_verified_builtin_metadata = read
                self.assertFalse(self.capture().complete)

    def test_kodi_capture_reuses_native_proof_and_pinned_core_parser(self):
        from resources.lib import frozen_install as fi
        from tests.test_d028_passive import PassiveFixture
        from tests.test_d028_builtin_authority import BUILTIN
        from tests.test_frozen import _kodi_entry, _kodi_rpc
        fixture = PassiveFixture(self)
        python = fixture.app / 'xbmc.python' / 'addon.xml'
        python.parent.mkdir()
        python.write_text(BUILTIN)
        fixture.info['xbmc.python'] = dict(id='xbmc.python', version='3.0.1',
                                          path=str(python.parent), type='unknown')
        for condition in ('System.HasAddon(xbmc.python)', 'System.AddonIsEnabled(xbmc.python)'):
            fixture.conditions[condition] = True
        aid = 'plugin.capture'
        xml = self.inventory.addon_xml[aid]
        target = fixture.home / aid
        target.mkdir()
        (target / 'addon.xml').write_bytes(xml)
        cache = fixture.home / 'packages'
        cache.mkdir()
        (cache / 'capture.zip').write_bytes(_zip(aid, xml_bytes=xml))
        inventory = KodiInventoryBackend(_kodi_rpc([_kodi_entry(aid, str(target))]),
            addons_dir=fixture.home, package_cache_dir=cache, application_addons_dir=fixture.app)
        self.addCleanup(inventory.close)
        original = fi.KodiRuntimeFrozenArtifactBackend
        def native():
            backend = original()
            backend._addons_dir = lambda: fixture.home
            backend._application_addons_dir = lambda: fixture.app
            backend._xbmc = fixture.backend._xbmc
            backend._rpc = fixture.backend._rpc
            return backend
        self.inventory = inventory
        with patch.object(fi, 'KodiRuntimeFrozenArtifactBackend', side_effect=native):
            result = self.capture()
            self.assertTrue(result.complete, result.errors)
            plan, verified = self.admit(result.manifest)
            self.assertEqual({'xbmc.core', 'xbmc.python'}, set(verified.builtin_versions))
            self.assertEqual(['plugin.capture'], [n.addon_id for n in plan.install_order])
            # A native home shadow withdraws authority; ordinary XML cannot fix it.
            (fixture.home / 'xbmc.core').mkdir()
            self.assertFalse(self.capture().complete)


class XbmcMetadataClosureTests(unittest.TestCase):
    """Representative metadata.generic.albums closure through the pinned native path (D-032)."""
    ROOT = 'metadata.generic.albums'
    XBMC = 'xbmc.metadata'

    def setUp(self):
        from resources.lib import frozen_install as fi
        from tests.test_d028_passive import PassiveFixture
        self.fi = fi
        self.f = PassiveFixture(self)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ArtifactStore(Path(temp.name))
        self.backends = []
        original = fi.KodiRuntimeFrozenArtifactBackend

        def native():
            backend = original()
            self.backends.append(backend)
            backend._addons_dir = lambda: self.f.home
            backend._application_addons_dir = lambda: self.f.app
            backend._xbmc = self.f.backend._xbmc
            backend._rpc = self.f.backend._rpc
            return backend

        patcher = patch.object(fi, 'KodiRuntimeFrozenArtifactBackend', side_effect=native)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: [backend.close() for backend in self.backends])

    def root_xml(self, metadata='2.1.0', core='0.1.0'):
        """Representative managed root: only its builtin closure is under test."""
        return _xml(self.ROOT, version='1.0.20', imports=(
            (self.XBMC, metadata, False), ('xbmc.core', core, False)))

    def install_root(self, xml):
        from tests.test_frozen import _kodi_entry, _kodi_rpc
        target = self.f.home / self.ROOT
        target.mkdir(parents=True, exist_ok=True)
        (target / 'addon.xml').write_bytes(xml)
        cache = self.f.home / 'packages'
        cache.mkdir(exist_ok=True)
        (cache / 'metadata-albums.zip').write_bytes(_zip(self.ROOT, xml_bytes=xml))
        inventory = KodiInventoryBackend(
            _kodi_rpc([_kodi_entry(self.ROOT, str(target), version='1.0.20')]),
            addons_dir=self.f.home, package_cache_dir=cache, application_addons_dir=self.f.app)
        self.addCleanup(inventory.close)
        return inventory

    def capture(self, xml=None):
        return capture_frozen_build(
            backend=self.install_root(self.root_xml() if xml is None else xml),
            store=self.store, root_addon_ids=(self.ROOT,), build_id='metadata-closure',
            name='Metadata closure', created_at='now')

    def admit(self, manifest):
        plan = validate_frozen_manifest(manifest, self.store)
        verified = verify_platform_requirements(plan, self.fi.KodiRuntimeFrozenArtifactBackend(),
            planned_versions={self.ROOT: '1.0.20'})
        return plan, verified

    def test_metadata_generic_albums_closure_uses_pinned_xbmc_metadata_and_core(self):
        result = self.capture()
        self.assertTrue(result.complete, result.errors)
        nodes = {n.addon_id: n for n in result.manifest.addons}
        self.assertTrue(nodes[self.XBMC].system and nodes['xbmc.core'].system)
        self.assertEqual(('2.1.0', '0.1.0'), (nodes[self.XBMC].version, nodes['xbmc.core'].version))
        edge, = nodes[self.XBMC].dependency_edges
        self.assertEqual(('xbmc.core', '0.1.0', False), (edge.addon_id, edge.min_version, edge.optional))
        plan, verified = self.admit(result.manifest)
        self.assertEqual({self.XBMC: '2.1.0', 'xbmc.core': '0.1.0'}, dict(verified.builtin_versions))
        self.assertEqual({self.XBMC: '1.0', 'xbmc.core': '0.1'}, dict(verified.builtin_abis))
        self.assertEqual([self.ROOT], [n.addon_id for n in plan.install_order])

    def test_incompatible_metadata_minimum_never_completes(self):
        for minimum in ('2.1.1', '2.2.0', '0.9'):
            with self.subTest(minimum=minimum):
                result = self.capture(self.root_xml(metadata=minimum))
                self.assertFalse(result.complete)
                self.assertNotEqual(CaptureStatus.COMPLETE, result.manifest.capture_status)
                self.assertTrue(result.errors)

    def test_disabled_absent_or_shadowed_closure_members_never_complete(self):
        for condition in ('System.AddonIsEnabled(xbmc.metadata)', 'System.HasAddon(xbmc.core)',
                          'System.AddonIsEnabled(xbmc.core)'):
            with self.subTest(condition=condition):
                self.f.conditions[condition] = False
                self.assertFalse(self.capture().complete)
                self.f.conditions[condition] = True
        self.assertTrue(self.capture().complete)
        shadow = self.f.home / self.XBMC
        shadow.mkdir()
        (shadow / 'addon.xml').write_bytes(self.f.descriptor(self.XBMC).read_bytes())
        try:
            self.assertFalse(self.capture().complete)
        finally:
            (shadow / 'addon.xml').unlink()
            shadow.rmdir()

    def test_missing_mandatory_core_import_refuses_at_capture_and_admission(self):
        good = self.f.descriptor(self.XBMC).read_bytes()
        bad = good.replace(b'<import addon="xbmc.core" version="0.1.0"/>', b'')
        self.assertNotEqual(good, bad)
        result = self.capture()
        self.assertTrue(result.complete, result.errors)
        manifest = result.manifest
        pin = ('2.1.0', '1.0', hashlib.sha256(bad).hexdigest())
        self.f.descriptor(self.XBMC).write_bytes(bad)
        try:
            with patch.object(self.fi, '_PASSIVE_BUILTINS',
                              MappingProxyType({**self.fi._PASSIVE_BUILTINS, self.XBMC: pin})):
                self.assertFalse(self.capture().complete)
                with self.assertRaises(self.fi.FrozenPlatformRequirementError):
                    self.admit(manifest)
        finally:
            self.f.descriptor(self.XBMC).write_bytes(good)
        self.assertTrue(self.capture().complete)
