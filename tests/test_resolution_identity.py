"""Distinct immutable completion contexts, with read-only legacy compatibility."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from resources.lib.build_library import AppliedBuildAssociation, LibraryInstallTarget
from resources.lib.build_identity import IdentityMismatch
from resources.lib.frozen_install import (
    FrozenInstallResolutionManifest, FrozenInstallPersistenceError,
    FrozenInstallTransaction, FrozenInstallValidationError, FrozenInstallStore,
)
from resources.lib.frozen_resolution import resolution_fingerprint, FrozenResolutionError
from tests import test_library_install as install_fixture


class ResolutionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.x = install_fixture.LibraryInstallTests()
        self.x.setUp()
        self.addCleanup(self.x.doCleanups)
        self.library = self.x.fixture.library

    def target(self, build_id):
        self.x.fixture.raw['build']['id'] = build_id
        self.x.fixture.frozen = replace(self.x.fixture.frozen, build_id=build_id)
        self.x.fixture.write_sources()
        entry = self.x.fixture.register()
        return LibraryInstallTarget.from_plan_target(self.library.plan_target(entry.entry_id, 'desk'))

    def install(self, target):
        with self.x.isolated():
            return self.x.coordinator().install_target(target, interactive=False)

    def test_two_builds_same_rows_persist_and_publish_independently(self):
        first = self.target('identity-one')
        a = self.install(first)
        self.assertEqual('complete', a.outcome, a)
        old_path = self.x.store.resolution_path(a.resolution_manifest.resolution_fingerprint)
        old_bytes = old_path.read_bytes()
        second = self.target('identity-two')
        b = self.install(second)
        self.assertEqual('complete', b.outcome, b)
        self.assertEqual(a.resolution_manifest.records, b.resolution_manifest.records)
        self.assertNotEqual(a.resolution_manifest.resolution_fingerprint, b.resolution_manifest.resolution_fingerprint)
        for target, result in ((first, a), (second, b)):
            fp = result.resolution_manifest.resolution_fingerprint
            loaded = self.x.store.load_resolution_manifest(fp, nofollow=True)
            self.assertEqual(result.resolution_manifest, loaded)
            association = AppliedBuildAssociation(target.source.entry_id, 'desk', fp)
            self.assertEqual(loaded, self.library._resolution(association))
        self.assertEqual(old_bytes, old_path.read_bytes())
        applied = self.library.current_applied_association()
        self.assertEqual(second.source.entry_id, applied.entry_id)
        self.assertEqual(b.resolution_manifest.resolution_fingerprint, applied.resolution_fingerprint)
        wrong = replace(applied, resolution_fingerprint=a.resolution_manifest.resolution_fingerprint)
        with self.assertRaises(IdentityMismatch):
            self.library._resolution(wrong)
        self.assertIsNone(self.x.store.inspect())

    def test_schema_one_record_and_association_survive_new_completion(self):
        first = self.target('legacy-one')
        # Construct the same immutable schema-1 bytes produced before correction.
        _, result = self.x.fixture.completed_resolution(self.x.fixture.library.get(first.source.entry_id))
        raw = result.to_dict()
        raw['schema_version'] = 1
        raw['resolution_fingerprint'] = resolution_fingerprint(result.records)
        raw['resolution_id'] = 'sha256:' + raw['resolution_fingerprint']
        legacy = FrozenInstallResolutionManifest.from_dict(raw)
        path = self.x.store.save_resolution_manifest(legacy)
        legacy_bytes = path.read_bytes()
        association = AppliedBuildAssociation(first.source.entry_id, 'desk', legacy.resolution_fingerprint)
        (self.x.fixture.root / 'applied.json').write_text(json.dumps(association.to_dict()))
        self.assertEqual(association, self.library.current_applied_association())
        self.assertEqual(legacy, self.library._resolution(association))
        self.assertEqual(raw, legacy.to_dict())
        second = self.target('legacy-two')
        new = self.install(second)
        self.assertEqual('complete', new.outcome, new)
        self.assertEqual(legacy.records, new.resolution_manifest.records)
        self.assertNotEqual(legacy.resolution_fingerprint, new.resolution_manifest.resolution_fingerprint)
        self.assertEqual(legacy_bytes, path.read_bytes())
        self.assertEqual(legacy, self.x.store.load_resolution_manifest(legacy.resolution_fingerprint, nofollow=True))
        self.assertEqual(legacy, self.library._resolution(association))

    def test_completion_transaction_roundtrip_binds_context_and_reads_legacy(self):
        target = self.target('transaction-context')
        with patch.object(FrozenInstallStore, 'save_resolution_manifest', side_effect=OSError('synthetic write failure')):
            result = self.install(target)
        self.assertEqual('RESOLUTION_PERSISTENCE_FAILED', result.code)
        tx = self.x.store.inspect()
        self.assertEqual(result.resolution_manifest.resolution_fingerprint, tx.resolution_fingerprint)
        self.assertEqual(tx, FrozenInstallTransaction.from_dict(tx.to_dict()))
        for field in ('build_id', 'manifest_fingerprint', 'install_plan_fingerprint', 'resolved_software_fingerprint'):
            with self.subTest(field=field):
                value = 'another-build' if field == 'build_id' else 'a' * 64
                with self.assertRaises(FrozenInstallValidationError):
                    replace(tx, **{field: value})
        legacy = replace(tx, resolution_fingerprint=resolution_fingerprint(tx.resolution_records))
        self.assertEqual(legacy, FrozenInstallTransaction.from_dict(legacy.to_dict()))

    def test_new_identity_binds_context_and_refuses_conflicting_storage(self):
        result = self.install(self.target('bound-context'))
        self.assertEqual('complete', result.outcome, result)
        manifest = result.resolution_manifest
        fp = manifest.resolution_fingerprint
        path = self.x.store.resolution_path(fp)
        original = path.read_bytes()
        for field in ('build_id', 'source_software_fingerprint', 'install_plan_fingerprint', 'resulting_software_fingerprint'):
            with self.subTest(field=field):
                value = 'different-build' if field == 'build_id' else 'a' * 64
                changed = replace(manifest, **{field: value})
                self.assertNotEqual(fp, changed.resolution_fingerprint)
                raw = manifest.to_dict()
                raw[field] = value  # retain original ID: substitution must refuse
                with self.assertRaises(FrozenResolutionError):
                    FrozenInstallResolutionManifest.from_dict(raw)
        # Existing different bytes are never overwritten even at a valid key.
        path.write_bytes(b'conflicting synthetic bytes')
        with self.assertRaises(FrozenInstallPersistenceError):
            self.x.store.save_resolution_manifest(manifest)
        self.assertEqual(b'conflicting synthetic bytes', path.read_bytes())
        path.write_bytes(original)
        self.assertEqual(manifest, self.x.store.load_resolution_manifest(fp))
