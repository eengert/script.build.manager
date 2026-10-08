"""BM-UI-003A owned library, selection, adversarial persistence and G2/G3 bridge."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from resources.lib import build_library as lib
from resources.lib.build_library import BuildLibrary, LibraryConflict, LibraryError
from resources.lib.frozen import FrozenBuildManifest, CaptureStatus
from resources.lib.resolver import resolve_manifest
from resources.lib.status import (BuildStatusService, StatusTarget, build_presentation,
    check_build_status, default_build_presentation, default_status_target)
from resources.lib.plan import BuildPlanService, PlanTarget, default_plan_target
from resources.lib.plan_model import DecisionChoice
from resources.lib.status_model import BuildIdentity, BuildPresentation, CheckGap
from tests.test_plan import PlanHarness
from tests.test_status import DEMO, SECRET, DB_SECRET, snapshot_tree


class LibraryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # macOS /var and /tmp aliases are test setup only; library rejects links.
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "bm" / "build-library"
        self.library = BuildLibrary(self.root)
        self.source = self.base / "source"
        self.source.mkdir()
        self.packages = self.source / "packages"
        package = self.packages / "shared"
        package.mkdir(parents=True)
        self.manifest_path = self.source / "manifest.json"
        self.frozen_path = self.source / "frozen.json"
        self.raw = {
            "schema_version": 1, "build": {"id": "demo", "version": "1.0.0", "name": "Demo"},
            "addons": [{"addon_id": DEMO, "state": "enabled"}],
            "config": {"packages": ["shared"],
                       "managed_settings": [{"addon_id": DEMO, "keys": ["quality"]}],
                       "managed_files": ["userdata/keymaps/demo.xml"]},
            "platform_profiles": {"macos": {}},
            "device_profiles": {"desk": {"extends": "macos"}, "other": {"extends": "macos"}},
            "private_overlay": {"type": "local_file", "overlay_id": "safe-overlay", "required": False},
        }
        self.frozen = FrozenBuildManifest(1, "demo", "Demo", "2026-10-06T00:00:00Z",
                                          "21.0", "macos", CaptureStatus.COMPLETE, (), ("shared",))
        self.descriptor = {"schema_version": 1, "id": "shared",
                           "settings": [{"addon_id": DEMO, "key": "quality", "type": "string", "value": "high"}],
                           "files": [{"source": "keys.xml", "destination": "userdata/keymaps/demo.xml"}]}
        self.asset = b"<keymap/>"
        self.write_sources()

    def write_sources(self):
        self.manifest_path.write_text(json.dumps(self.raw))
        self.frozen_path.write_text(self.frozen.to_json())
        (self.packages / "shared" / "package.json").write_text(json.dumps(self.descriptor))
        (self.packages / "shared" / "keys.xml").write_bytes(self.asset)

    def register(self):
        return self.library.register(str(self.manifest_path), str(self.frozen_path), str(self.packages))

    def effective(self, key, profile="desk"):
        manifest, frozen, loader = self.library._load(key)
        return loader.resolve(resolve_manifest(manifest, profile).config)

    def envelope(self, key):
        return self.root / "builds" / (key + ".json")

    def registered_fixture(self):
        entry = self.register()
        return entry, json.loads(self.envelope(entry.entry_id).read_text())

    def completed_resolution(self, entry, profile="desk", *, store=None):
        from resources.lib.frozen_install import FrozenInstallStore
        from resources.lib.frozen_resolution import (FrozenInstallResolutionManifest,
            InstallResolutionRecord, InstallResolution, ResolutionState,
            install_plan_fingerprint, resolved_software_fingerprint)
        store = store or FrozenInstallStore(self.root.parent)
        public, frozen, _ = self.library._load(entry.entry_id)
        desired = resolve_manifest(public, profile)
        records = tuple(sorted((InstallResolutionRecord(
            n.addon_id, n.version, InstallResolution.EXACT, ResolutionState.INSTALLED,
            resolved_version=n.version, artifact_sha256=n.artifact.sha256,
            desired_enabled=n.desired_enabled, artifact_size=n.artifact.size) for n in frozen.addons if n.artifact),
            key=lambda r: r.addon_id))
        resolution = FrozenInstallResolutionManifest(
            build_id=desired.build.id, source_software_fingerprint=frozen.fingerprint(),
            install_plan_fingerprint=install_plan_fingerprint(frozen, desired.frozen_install_policies),
            resulting_software_fingerprint=resolved_software_fingerprint(frozen, records), records=records)
        store.save_resolution_manifest(resolution)
        return store, resolution

    def record_applied(self, entry, profile="desk"):
        import uuid
        target = lib.LibraryInstallTarget(lib.LibrarySource(str(self.root), entry.entry_id), profile)
        with lib.isolated_library_install_authority(self.library):
            target.load()
            store, resolution = self.completed_resolution(entry, profile)
            from resources.lib.frozen_install import FrozenInstallTransaction, FrozenInstallPhase
            from resources.lib.update_guard import AddonUpdatePolicy
            desired = resolve_manifest(target.load()[0], profile)
            transaction = FrozenInstallTransaction(
                transaction_id=str(uuid.uuid4()), build_id=resolution.build_id,
                manifest_path="", device_profile_id=profile,
                manifest_fingerprint=resolution.source_software_fingerprint,
                phase=FrozenInstallPhase.COMPLETE,
                originating_kodi_session_id=str(uuid.uuid4()),
                original_update_policy=AddonUpdatePolicy.NOTIFY_ONLY,
                created_at="2026-10-08T00:00:00+00:00", updated_at="2026-10-08T00:00:00+00:00",
                install_plan_fingerprint=resolution.install_plan_fingerprint,
                policies=desired.frozen_install_policies, resolution_records=resolution.records,
                resolution_fingerprint=resolution.resolution_fingerprint,
                resolved_software_fingerprint=resolution.resulting_software_fingerprint,
                library_target=target)
            store.create(transaction)
            transaction = store.transition_expected(transaction_id=transaction.transaction_id,
                expected_phase=FrozenInstallPhase.COMPLETE,
                new_phase=FrozenInstallPhase.PUBLICATION_PENDING)
            pending = self.library._create_applied_publication(transaction, resolution_store=store)
            self.library._record_applied_completion(pending, resolution_store=store)
            store._clear_publication_expected(transaction_id=transaction.transaction_id,
                                              publication=pending)
        return self.library.current_applied_association()

    def test_applied_durable_distinct_selection_and_bridges(self):
        self.assertIsNone(self.library.current_applied_association())
        self.assertFalse(self.root.exists())
        a = self.register()
        self.library.select(a.entry_id, "desk")
        self.assertIsNone(self.library.current_applied_association())
        applied = self.record_applied(a)
        self.assertEqual(BuildLibrary(self.root).current_applied_association(), applied)
        self.raw["build"]["version"] = "2.0.0"
        self.write_sources(); b = self.register()
        self.library.select(b.entry_id, "other")
        self.assertEqual(self.library.current_applied_association(), applied)
        self.assertEqual(self.library.associated_status_target().applied_association, applied)
        self.assertEqual(self.library.associated_plan_target().library_source.entry_id, a.entry_id)
        self.assertEqual(self.library.selected_status_target().library_source.entry_id, b.entry_id)
        self.assertIsNone(self.library.selected_status_target().applied_association)
        with patch('resources.lib.build_library.default_build_library', return_value=self.library):
            self.assertEqual(default_status_target().applied_association, applied)
        self.library.clear_selection()
        self.assertEqual(self.library.current_applied_association(), applied)
        final = self.record_applied(b, "other")
        raw = json.loads((self.root / "applied.json").read_text())
        self.assertEqual(raw, final.to_dict())

    def test_applied_malformed_bounded_and_no_fallback(self):
        entry = self.register(); self.library.select(entry.entry_id, "other")
        path = self.root / "applied.json"
        valid = {"schema_version": 1, "entry_id": entry.entry_id, "device_profile_id": "desk"}
        cases = [b"{", b"null", b"[]", b"x" * (lib.STATE_LIMIT + 1),
                 b'{"schema_version":1,"schema_version":1}',
                 json.dumps({**valid, "schema_version": True}).encode(),
                 json.dumps({**valid, "schema_version": 2}).encode(),
                 json.dumps({**valid, "entry_id": "../escape"}).encode(),
                 json.dumps({**valid, "entry_id": "a" * 64}).encode(),
                 json.dumps({**valid, "device_profile_id": []}).encode(),
                 json.dumps({**valid, "device_profile_id": "removed"}).encode(),
                 json.dumps({**valid, "private": SECRET}).encode()]
        for data in cases:
            with self.subTest(data_length=len(data)):
                path.write_bytes(data)
                self.assertIsNone(self.library.current_applied_association())
                self.assertIsNone(self.library.associated_status_target())
                with patch('resources.lib.build_library.default_build_library', return_value=self.library):
                    self.assertIsNone(default_status_target())
                self.assertIsNone(self.library.associated_plan_target())
                self.assertEqual(self.library.current_selection().device_profile_id, "other")
        path.unlink()
        self.assertIsNone(self.library.current_applied_association())

    def test_applied_safe_files_and_ancestors(self):
        entry = self.register(); self.record_applied(entry)
        path = self.root / "applied.json"; data = path.read_bytes(); path.unlink()
        external = self.base / "external"; external.write_bytes(data)
        for kind in ("link", "directory", "fifo", "socket"):
            with self.subTest(kind=kind):
                sock = None
                if kind == "link": path.symlink_to(external)
                elif kind == "directory": path.mkdir()
                elif kind == "fifo": os.mkfifo(path)
                else:
                    sock = socket.socket(socket.AF_UNIX); sock.bind(str(path))
                try:
                    self.assertIsNone(self.library.current_applied_association())
                    self.assertEqual(external.read_bytes(), data)
                finally:
                    if sock: sock.close()
                    if kind == "directory": path.rmdir()
                    else: path.unlink()
        path.write_bytes(data)
        moved = self.base / "moved"; self.root.rename(moved); self.root.symlink_to(moved, target_is_directory=True)
        self.assertIsNone(self.library.current_applied_association())
        with self.assertRaises(LibraryError): self.record_applied(entry)
        self.assertEqual((moved / "applied.json").read_bytes(), data)

    def test_applied_atomic_replace_failure_retains_prior_and_removes_stage(self):
        entry = self.register(); self.record_applied(entry)
        before = (self.root / "applied.json").read_bytes()
        original = lib.os.replace
        def fail_applied(source, destination, **kwargs):
            if destination == "applied.json": raise OSError("replace failed")
            return original(source, destination, **kwargs)
        with patch.object(lib.os, "replace", side_effect=fail_applied):
            with self.assertRaises(LibraryError): self.record_applied(entry, "other")
        self.assertEqual((self.root / "applied.json").read_bytes(), before)
        self.assertEqual(list(self.root.glob(".stage-*")), [])

    def test_applied_entry_changes_and_removed_profile_invalidate(self):
        entry = self.register(); self.record_applied(entry)
        path = self.envelope(entry.entry_id); saved = path.read_bytes()
        for mode in ("deleted", "changed", "profile_removed", "unregistered"):
            with self.subTest(mode=mode):
                path.write_bytes(saved)
                if mode == "deleted": path.unlink()
                elif mode in ("changed", "profile_removed"):
                    raw = json.loads(saved)
                    if mode == "changed": raw["manifest"]["build"]["name"] = "Changed"
                    else: del raw["manifest"]["device_profiles"]["desk"]
                    path.write_text(json.dumps(raw))
                else:
                    (self.root / "registry.json").write_text('{"schema_version":1,"entries":{}}')
                self.assertIsNone(self.library.current_applied_association())

    def test_applied_writer_revalidates_and_preserves_on_rejection(self):
        entry = self.register(); self.record_applied(entry)
        before = (self.root / "applied.json").read_bytes()
        with self.assertRaises(LibraryError): self.record_applied(entry, "unknown")
        self.assertEqual((self.root / "applied.json").read_bytes(), before)
        target = lib.LibraryInstallTarget(lib.LibrarySource(str(self.root), entry.entry_id), "desk")
        with patch('resources.lib.build_library.default_build_library', side_effect=RuntimeError):
            with self.assertRaises(LibraryError): self.library._record_applied_completion(target, resolution_store=None)
        self.assertEqual((self.root / "applied.json").read_bytes(), before)

    def test_registered_missing_entire_root_proves_absence(self):
        _, bundle = self.registered_fixture()
        shutil.rmtree(self.root)
        self.assertIsNone(self.library.registered_bundle(bundle))

    def test_registered_readable_registry_key_absent(self):
        _, bundle = self.registered_fixture()
        (self.root / 'registry.json').write_text(json.dumps({'schema_version': 1, 'entries': {}}))
        self.assertIsNone(self.library.registered_bundle(bundle))

    def test_registered_valid_indexed_entry(self):
        entry, bundle = self.registered_fixture()
        self.assertEqual(self.library.registered_bundle(bundle), entry)

    def test_registered_missing_registry_is_ambiguous(self):
        _, bundle = self.registered_fixture()
        (self.root / 'registry.json').unlink()
        with self.assertRaises(LibraryError): self.library.registered_bundle(bundle)

    def test_registered_indexed_missing_builds_is_error(self):
        _, bundle = self.registered_fixture()
        shutil.rmtree(self.root / 'builds')
        with self.assertRaises(LibraryError): self.library.registered_bundle(bundle)

    def test_registered_indexed_missing_envelope_is_error(self):
        entry, bundle = self.registered_fixture()
        self.envelope(entry.entry_id).unlink()
        with self.assertRaises(LibraryError): self.library.registered_bundle(bundle)

    def test_registered_indexed_corrupt_envelope_is_error(self):
        entry, bundle = self.registered_fixture()
        self.envelope(entry.entry_id).write_text('{')
        with self.assertRaises(LibraryError): self.library.registered_bundle(bundle)

    def test_registered_indexed_digest_disagreement_is_error(self):
        entry, bundle = self.registered_fixture()
        changed = json.loads(json.dumps(bundle)); changed['manifest']['build']['name'] = 'Changed'
        self.envelope(entry.entry_id).write_text(json.dumps(changed))
        with self.assertRaises(LibraryError): self.library.registered_bundle(bundle)

    def test_registered_indexed_metadata_disagreement_is_error(self):
        entry, bundle = self.registered_fixture()
        registry = json.loads((self.root / 'registry.json').read_text())
        registry['entries'][entry.entry_id]['display_name'] = 'Changed'
        (self.root / 'registry.json').write_text(json.dumps(registry))
        with self.assertRaises(LibraryError): self.library.registered_bundle(bundle)

    def test_registered_indexed_unreadable_content_is_error(self):
        _, bundle = self.registered_fixture()
        original = lib._read_at
        def deny(fd, name, limit):
            if name.startswith('builds/'):
                raise PermissionError(SECRET)
            return original(fd, name, limit)
        with patch.object(lib, '_read_at', side_effect=deny):
            with self.assertRaises(LibraryError) as error: self.library.registered_bundle(bundle)
        self.assertNotIn(SECRET, str(error.exception))

    def test_empty_is_creation_free_and_not_auto_selected(self):
        self.assertEqual(self.library.list_builds(), ())
        self.assertIsNone(self.library.current_selection())
        self.assertIsNone(self.library.selected_status_target())
        self.assertIsNone(self.library.selected_plan_target())
        self.assertFalse(self.root.exists())
        self.register()
        self.assertIsNone(self.library.current_selection())

    def test_registration_reload_safe_public_model_and_idempotence(self):
        entry = self.register()
        self.assertEqual(entry, BuildLibrary(self.root).get(entry.entry_id))
        self.assertEqual(entry.device_profiles, ("desk", "other"))
        self.assertTrue(entry.usable)
        self.assertNotIn(str(self.root), repr(entry))
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self.register(), entry)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        # Canonical JSON means formatting/key order do not alter the identity.
        self.manifest_path.write_text(json.dumps(self.raw, indent=4, sort_keys=True))
        self.assertEqual(self.register(), entry)

    def test_deterministic_listing(self):
        first = self.register()
        self.raw["build"] = {"id": "alpha", "version": "1.0.0", "name": "Alpha"}
        self.frozen = replace(self.frozen, build_id="alpha", name="Alpha")
        self.write_sources()
        second = self.register()
        self.assertEqual(self.library.list_builds(), (second, first))

    def test_same_id_version_different_package_content_conflicts(self):
        first = self.register()
        self.descriptor["settings"][0]["value"] = "low"
        self.write_sources()
        with self.assertRaises(LibraryConflict):
            self.register()
        self.assertEqual(self.effective(first.entry_id).settings[0].value, "high")
        self.assertEqual(len(self.library.list_builds()), 1)

    def test_two_builds_isolate_same_package_id(self):
        first = self.register()
        self.raw["build"]["version"] = "2.0.0"
        self.descriptor["settings"][0]["value"] = "low"
        self.asset = b"<keymap>second</keymap>"
        self.write_sources()
        second = self.register()
        self.assertNotEqual(first.entry_id, second.entry_id)
        self.assertEqual(self.effective(first.entry_id).settings[0].value, "high")
        self.assertEqual(self.effective(second.entry_id).settings[0].value, "low")
        self.assertEqual(self.effective(first.entry_id).files[0].content, b"<keymap/>")
        self.assertEqual(self.effective(second.entry_id).files[0].content, self.asset)

    def test_source_changes_and_deletion_do_not_change_owned_content(self):
        entry = self.register()
        self.raw["build"]["id"] = "changed"
        self.descriptor["settings"][0]["value"] = "changed"
        self.asset = b"changed"
        self.write_sources()
        self.assertEqual(self.library.get(entry.entry_id), entry)
        self.assertEqual(self.effective(entry.entry_id).settings[0].value, "high")
        shutil.rmtree(self.source)
        self.assertEqual(self.library.get(entry.entry_id), entry)
        self.assertEqual(self.effective(entry.entry_id).files[0].content, b"<keymap/>")

    def test_frozen_build_id_mismatch_rejected(self):
        self.frozen = replace(self.frozen, build_id="different")
        self.write_sources()
        self.assert_registration_rejected()

    def assert_registration_rejected(self):
        with self.assertRaises(LibraryError) as cm:
            self.register()
        self.assertEqual(str(cm.exception), "build_library_invalid")
        self.assertEqual(self.library.list_builds(), ())

    def test_malformed_frozen_fingerprint_rejected(self):
        data = self.frozen.to_dict()
        data["software_fingerprint"] = "a" * 64
        self.frozen_path.write_text(json.dumps(data))
        self.assert_registration_rejected()

    def test_missing_configuration_descriptor_or_asset_rejected(self):
        for name in ("package.json", "keys.xml"):
            with self.subTest(name=name):
                self.write_sources()
                (self.packages / "shared" / name).unlink()
                self.assert_registration_rejected()

    def test_invalid_profile_structure_rejected(self):
        self.raw["device_profiles"]["desk"]["extends"] = "unknown"
        self.write_sources()
        self.assert_registration_rejected()

    def test_traversal_inputs_rejected(self):
        for location in ("../keys.xml", "/keys.xml", "sub/../../keys.xml", "sub\\keys.xml"):
            with self.subTest(location=location):
                self.descriptor["files"][0]["source"] = location
                self.write_sources()
                self.assert_registration_rejected()
        with self.assertRaises(LibraryError):
            BuildLibrary(str(self.root) + "/../outside")
        with self.assertRaises(LibraryError):
            self.library.get("../../outside")

    def test_source_ancestor_and_leaf_symlinks_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        for name in ("manifest.json", "frozen.json", "keys.xml", "package.json"):
            with self.subTest(name=name):
                self.write_sources()
                original = self.source / name if name in ("manifest.json", "frozen.json") else self.packages / "shared" / name
                saved = original.read_bytes()
                target = outside / name
                target.write_bytes(saved)
                original.unlink()
                original.symlink_to(target)
                self.assert_registration_rejected()
                original.unlink()
        # Package directory escape.
        shutil.rmtree(self.packages / "shared")
        (self.packages / "shared").symlink_to(outside, target_is_directory=True)
        self.assert_registration_rejected()

    def test_source_path_with_linked_ancestor_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(LibraryError):
            self.library.register(str(alias / "manifest.json"), str(self.frozen_path), str(self.packages))

    def test_library_ancestor_symlink_preserves_outside(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.root.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(LibraryError):
            self.register()
        self.assertEqual(list(outside.iterdir()), [])
        with self.assertRaises(LibraryError):
            self.library.list_builds()
        self.assertIsNone(self.library.current_selection())

    def test_nonregular_source_reads_do_not_block(self):
        for kind in ("directory", "fifo"):
            with self.subTest(kind=kind):
                self.manifest_path.unlink()
                if kind == "directory":
                    self.manifest_path.mkdir()
                else:
                    os.mkfifo(self.manifest_path)
                self.assert_registration_rejected()
                if kind == "directory":
                    self.manifest_path.rmdir()
                else:
                    self.manifest_path.unlink()
                self.write_sources()

    def test_bounded_sources_and_library_state(self):
        with patch.object(lib, "FILE_LIMIT", 10):
            self.assert_registration_rejected()
        entry = self.register()
        self.library.select(entry.entry_id, "desk")
        with patch.object(lib, "BUNDLE_LIMIT", 10):
            self.assertEqual(self.library.list_builds(), ())
            self.assertIsNone(self.library.current_selection())
        with patch.object(lib, "STATE_LIMIT", 10):
            with self.assertRaises(LibraryError):
                self.library.list_builds()
            self.assertIsNone(self.library.current_selection())

    def test_interrupted_unindexed_envelope_not_selectable_and_retry_recovers(self):
        atomic = lib._atomic
        def interrupted(fd, name, data):
            if name == "registry.json":
                raise OSError("interruption")
            return atomic(fd, name, data)
        with patch.object(lib, "_atomic", side_effect=interrupted):
            with self.assertRaises(LibraryError):
                self.register()
        self.assertEqual(self.library.list_builds(), ())
        key = next((self.root / "builds").glob("*.json")).stem
        with self.assertRaises(LibraryError):
            self.library.select(key, "desk")
        (self.root / ".stage-interrupted").write_text(SECRET)
        entry = self.register()
        self.assertEqual(entry.entry_id, key)
        self.assertEqual(self.library.list_builds(), (entry,))

    def test_corrupt_entry_does_not_hide_other_entries(self):
        first = self.register()
        self.raw["build"]["version"] = "2.0.0"
        self.write_sources()
        second = self.register()
        self.envelope(first.entry_id).write_text("{broken")
        self.assertEqual(self.library.list_builds(), (second,))
        with self.assertRaises(LibraryError):
            self.library.get(first.entry_id)

    def test_registry_content_disagreement_and_content_tampering_fail_closed(self):
        entry = self.register()
        registry = self.root / "registry.json"
        data = json.loads(registry.read_text())
        data["entries"][entry.entry_id]["display_name"] = "Wrong"
        registry.write_text(json.dumps(data))
        self.assertEqual(self.library.list_builds(), ())
        with self.assertRaises(LibraryError):
            self.library.select(entry.entry_id, "desk")
        data["entries"][entry.entry_id]["display_name"] = "Demo"
        registry.write_text(json.dumps(data))
        bundle = json.loads(self.envelope(entry.entry_id).read_text())
        bundle["packages"]["shared"]["descriptor"]["settings"][0]["value"] = "tampered"
        self.envelope(entry.entry_id).write_text(json.dumps(bundle))
        self.assertEqual(self.library.list_builds(), ())

    def test_malformed_and_traversal_registry_rejected(self):
        self.register()
        for data in ({"schema_version": 1, "entries": {"../../outside": {}}},
                     {"schema_version": True, "entries": {}}, [], {"arbitrary_path": SECRET}):
            with self.subTest(data=data):
                (self.root / "registry.json").write_text(json.dumps(data))
                with self.assertRaises(LibraryError) as cm:
                    self.library.list_builds()
                self.assertNotIn(SECRET, str(cm.exception))
                self.assertIsNone(self.library.current_selection())

    def test_duplicate_json_fields_rejected(self):
        self.manifest_path.write_text('{"schema_version":1,"schema_version":1}')
        self.assert_registration_rejected()

    def test_valid_selection_is_durable_and_clearable(self):
        entry = self.register()
        selected = self.library.select(entry.entry_id, "desk")
        self.assertEqual(BuildLibrary(self.root).current_selection(), selected)
        selection = json.loads((self.root / "selection.json").read_text())
        self.assertEqual(set(selection), {"schema_version", "entry_id", "device_profile_id"})
        self.library.clear_selection()
        self.assertIsNone(self.library.current_selection())

    def test_unknown_entry_and_invalid_profile_selection_rejected(self):
        entry = self.register()
        for key, profile in (("a" * 64, "desk"), (entry.entry_id, "missing"), ("../../escape", "desk")):
            with self.subTest(key=key, profile=profile):
                with self.assertRaises(LibraryError):
                    self.library.select(key, profile)
        self.assertIsNone(self.library.current_selection())

    def test_corrupt_deleted_or_unindexed_selection_never_redirects(self):
        entry = self.register()
        self.library.select(entry.entry_id, "desk")
        self.envelope(entry.entry_id).unlink()
        self.assertIsNone(self.library.current_selection())
        self.assertIsNone(self.library.selected_status_target())
        self.assertIsNone(self.library.selected_plan_target())
        # Re-registration can recover the identical, now missing envelope only
        # through explicit repair; normal duplicate registration fails closed.
        with self.assertRaises(LibraryError):
            self.register()

    def test_invalid_or_changed_selected_profile_and_identity_unavailable(self):
        entry = self.register()
        self.library.select(entry.entry_id, "desk")
        selected_path = self.root / "selection.json"
        raw = json.loads(selected_path.read_text())
        for changes in ({"device_profile_id": "missing"}, {"entry_id": "b" * 64}, {"entry_id": "../escape"}):
            with self.subTest(changes=changes):
                selected_path.write_text(json.dumps({**raw, **changes}))
                self.assertIsNone(self.library.current_selection())
        selected_path.write_text("invalid")
        self.assertIsNone(self.library.current_selection())

    def test_envelope_registry_selection_links_and_fifos_fail_closed(self):
        entry = self.register()
        self.library.select(entry.entry_id, "desk")
        for path in (self.envelope(entry.entry_id), self.root / "registry.json", self.root / "selection.json"):
            saved = path.read_bytes()
            outside = self.base / "external-record"
            outside.write_bytes(saved)
            for kind in ("link", "fifo", "directory"):
                with self.subTest(path=path.name, kind=kind):
                    path.unlink()
                    if kind == "link":
                        path.symlink_to(outside)
                    elif kind == "fifo":
                        os.mkfifo(path)
                    else:
                        path.mkdir()
                    self.assertIsNone(self.library.current_selection())
                    if kind == "directory":
                        path.rmdir()
                    else:
                        path.unlink()
                    path.write_bytes(saved)
            self.assertEqual(outside.read_bytes(), saved)

    def test_builds_directory_symlink_rejected(self):
        entry = self.register()
        builds = self.root / "builds"
        moved = self.base / "moved"
        builds.rename(moved)
        builds.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.library.list_builds(), ())
        with self.assertRaises(LibraryError):
            self.library.select(entry.entry_id, "desk")

    def test_interrupted_selection_retains_previous_record(self):
        entry = self.register()
        selected = self.library.select(entry.entry_id, "desk")
        with patch.object(lib.os, "replace", side_effect=OSError("interrupted")):
            with self.assertRaises(LibraryError):
                self.library.select(entry.entry_id, "other")
        self.assertEqual(self.library.current_selection(), selected)
        self.assertFalse(list(self.root.glob(".stage-*")))

    def test_writer_lock_refuses_concurrent_publication(self):
        entry = self.register()
        with self.library._writer():
            with self.assertRaises(LibraryError):
                self.library.select(entry.entry_id, "desk")
        self.assertIsNone(self.library.current_selection())

    def test_private_payload_rejected_and_unused_private_files_not_imported(self):
        # Public declarations/IDs can reference existing private storage; values
        # never enter the registration API or envelope.
        self.raw["config"]["private_settings"] = [{"addon_id": DEMO, "key": "account", "type": "string", "required": False, "sensitivity": "credential"}]
        self.write_sources()
        (self.source / "private-overlay.json").write_text(SECRET + DB_SECRET)
        (self.packages / "shared" / "unused-private.txt").write_text(SECRET)
        entry = self.register()
        persisted = b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file()).decode()
        for sentinel in (SECRET, DB_SECRET):
            self.assertNotIn(sentinel, persisted)
            self.assertNotIn(sentinel, repr(entry))
        # A value for a declared private target is forbidden even if also
        # dishonestly declared as managed public configuration.
        self.raw["build"]["version"] = "2.0.0"
        self.raw["config"]["managed_settings"][0]["keys"].append("account")
        self.descriptor["settings"].append({"addon_id": DEMO, "key": "account", "type": "string", "value": SECRET})
        self.write_sources()
        with self.assertRaises(LibraryError) as cm:
            self.register()
        self.assertNotIn(SECRET, str(cm.exception))
        persisted = b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file()).decode()
        self.assertNotIn(SECRET, persisted)
        self.assertEqual(self.library.list_builds(), (entry,))

    def test_reject_private_overlay_values_frozen_diagnostics_and_redlight(self):
        for modification in ("overlay", "frozen", "redlight", "credential"):
            with self.subTest(modification=modification):
                if modification == "overlay":
                    self.raw["private_overlay"]["values"] = SECRET
                elif modification == "frozen":
                    self.frozen = replace(self.frozen, source_metadata={"token": SECRET})
                elif modification == "redlight":
                    self.raw["addons"].append({"addon_id": "plugin.video.redlight", "state": "enabled"})
                    self.raw["config"]["managed_settings"] = [{"addon_id": "plugin.video.redlight", "keys": ["quality"]}]
                    self.descriptor["settings"][0]["addon_id"] = "plugin.video.redlight"
                    self.descriptor["settings"][0]["value"] = DB_SECRET
                else:
                    self.raw["config"]["managed_settings"][0]["keys"] = ["api_token"]
                    self.descriptor["settings"][0]["key"] = "api_token"
                    self.descriptor["settings"][0]["value"] = SECRET
                self.write_sources()
                self.assert_registration_rejected()
                self.raw["private_overlay"].pop("values", None)
                self.frozen = replace(self.frozen, source_metadata={})
                self.raw["config"]["managed_settings"] = [{"addon_id": DEMO, "keys": ["quality"]}]
                self.descriptor["settings"][0] = {"addon_id": DEMO, "key": "quality", "type": "string", "value": "high"}

    def test_structurally_invalid_exact_artifact_rejected(self):
        from resources.lib.artifacts import ArtifactMetadata
        from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
        node = AddonCaptureNode(DEMO, "1.0.0", "xbmc.python.pluginsource", True,
                                ProvenanceStatus.UNKNOWN,
                                artifact=ArtifactMetadata("bad", 10, DEMO, "1.0.0", "demo.zip"))
        self.frozen = replace(self.frozen, addons=(node,))
        self.write_sources()
        self.assert_registration_rejected()

    def test_registration_selection_listing_perform_no_network_or_kodi_mutation(self):
        harness = PlanHarness(self, with_private=False, with_resource=False)
        with harness.instrumented(), patch.object(socket, "socket", side_effect=AssertionError("network")):
            entry = self.register()
            self.library.list_builds()
            self.library.select(entry.entry_id, "desk")
            self.library.selected_status_target()
            self.library.selected_plan_target()
            self.library.clear_selection()
        harness.assert_untouched()

    def test_selected_targets_production_wiring_and_scoped_configuration(self):
        entry = self.register()
        self.library.select(entry.entry_id, "desk")
        harness = PlanHarness(self, with_private=False, with_resource=False)
        # Real resolver and library-owned config; arbitrary path/global package
        # loaders must never be reached by these production selected targets.
        def forbidden(*args):
            raise AssertionError("external path/global packages")
        status_owners = harness.owners(resolver=resolve_manifest, manifest_loader=forbidden,
                                       frozen_manifest_loader=forbidden,
                                       config_loader=SimpleNamespace(resolve=forbidden))
        plan_owners = replace(harness.plan_service()._o, status=status_owners)
        status_target = self.library.selected_status_target()
        plan_target = self.library.selected_plan_target()
        self.assertIsInstance(status_target, StatusTarget)
        self.assertIsInstance(plan_target, PlanTarget)
        self.assertIsNone(status_target.install_resolution)
        self.assertIsNone(plan_target.install_resolution)
        with harness.instrumented():
            status = BuildStatusService(status_owners).check(status_target)
            plan = BuildPlanService(plan_owners).preview(plan_target)
        self.assertNotIn(CheckGap.BUILD_UNREADABLE, status.gaps)
        self.assertNotIn(CheckGap.BUILD_UNREADABLE, plan.gaps)
        self.assertTrue(status.build_selected)
        self.assertEqual(status_target.library_source.load()[0].build.id, "demo")
        self.assertEqual(plan_target.library_source.load()[0].build.id, "demo")
        self.assertEqual(status.configuration.differing, 0)
        self.assertFalse(any("external path" in message for message in harness.logs))
        # Production translation uses only the active special://profile root.
        translations = []
        vfs = SimpleNamespace(translatePath=lambda path: translations.append(path) or str(self.root.parent))
        with patch.dict("sys.modules", {"xbmcvfs": vfs}):
            self.assertIsNone(default_status_target())  # selection is not applied
            self.record_applied(entry)
            self.assertEqual(default_status_target(), self.library.associated_status_target())
            self.assertEqual(lib.selected_plan_target(), plan_target)
            self.assertEqual(default_plan_target(), plan_target)
        self.assertEqual(set(translations), {"special://profile/addon_data/script.build.manager"})
        self.assertEqual(plan_target.with_choice(DEMO, DecisionChoice.SKIP).library_source, plan_target.library_source)
        for sentinel in (SECRET, DB_SECRET, str(self.root), str(self.source)):
            self.assertNotIn(sentinel, repr(status.to_safe_dict()))
            self.assertNotIn(sentinel, repr(plan.to_safe_dict()))
            self.assertNotIn(sentinel, "\n".join(harness.logs))
        harness.assert_untouched()

    def test_target_revalidates_after_selection_and_never_trusts_stale_paths(self):
        entry = self.register()
        self.library.select(entry.entry_id, "desk")
        status_target = self.library.selected_status_target()
        plan_target = self.library.selected_plan_target()
        self.envelope(entry.entry_id).write_text("invalid")
        harness = PlanHarness(self, with_private=False, with_resource=False)
        status = BuildStatusService(harness.owners(resolver=resolve_manifest)).check(status_target)
        plan = harness.plan_service().preview(plan_target)
        self.assertIn(CheckGap.BUILD_UNREADABLE, status.gaps)
        self.assertIn(CheckGap.BUILD_UNREADABLE, plan.gaps)

    def test_no_selection_preserves_truthful_status_and_translation_failure(self):
        vfs = SimpleNamespace(translatePath=lambda path: str(self.root.parent))
        with patch.dict("sys.modules", {"xbmcvfs": vfs}):
            self.assertIsNone(default_status_target())
            self.assertIsNone(lib.selected_plan_target())
            self.register()
            self.assertIsNone(default_status_target())
        harness = PlanHarness(self, with_private=False, with_resource=False)
        status = BuildStatusService(harness.owners()).check(None)
        self.assertIn(CheckGap.NO_BUILD_SELECTED, status.gaps)
        with patch.dict("sys.modules", {"xbmcvfs": None}):
            self.assertIsNone(default_status_target())
            self.assertIsNone(lib.selected_plan_target())
        self.assertFalse((self.base / "bm" / "selection.json").exists())

    def test_typed_source_validation(self):
        for target in (StatusTarget, PlanTarget):
            with self.assertRaises(ValueError):
                target("/manifest", "desk", "/frozen", library_source="arbitrary")

    def test_scoped_packages_change_status_and_plan_without_global_contamination(self):
        first = self.register()
        self.raw["build"]["version"] = "2.0.0"
        self.descriptor["settings"][0]["value"] = "low"
        self.write_sources()
        second = self.register()
        harness = PlanHarness(self, with_private=False, with_resource=False)
        owners = harness.owners(resolver=resolve_manifest)
        plan_service = BuildPlanService(harness.plan_owners(status=owners))
        counts = []
        plans = []
        for entry in (first, second, first):
            self.library.select(entry.entry_id, "desk")
            with harness.instrumented():
                status = BuildStatusService(owners).check(self.library.selected_status_target())
                plan = plan_service.preview(self.library.selected_plan_target())
            counts.append(status.configuration.differing)
            plans.append(plan)
        self.assertEqual(counts, [0, 1, 0])
        self.assertEqual(plans[0].settings, plans[2].settings)
        self.assertNotEqual(plans[0].settings, plans[1].settings)
        harness.assert_untouched()

    def test_exact_artifacts_remain_in_existing_store_without_duplication(self):
        from resources.lib.artifacts import ArtifactStore
        from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
        from tests.test_plan import make_zip
        store = ArtifactStore(self.base / "bm" / "frozen-artifacts")
        metadata = store.import_zip(make_zip(DEMO, "1.0.0"), expected_addon_id=DEMO,
                                    expected_version="1.0.0")
        self.frozen = replace(self.frozen, addons=(AddonCaptureNode(DEMO, "1.0.0", "xbmc.python.pluginsource",
                                                                  True, ProvenanceStatus.UNKNOWN, artifact=metadata),))
        self.write_sources()
        before = {p.relative_to(store.root): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
        entry = self.register()
        loaded = self.library._load(entry.entry_id)[1]
        self.assertEqual(loaded.fingerprint(), self.frozen.fingerprint())
        self.assertEqual(loaded.addons[0].artifact.sha256, metadata.sha256)
        self.assertFalse(list(self.root.rglob("*.zip")))
        self.assertEqual(before, {p.relative_to(store.root): p.read_bytes() for p in store.root.rglob("*") if p.is_file()})

    def test_package_and_aggregate_limits_reject_before_publication(self):
        with patch.object(lib, "PACKAGE_LIMIT", 0):
            self.assert_registration_rejected()
        with patch.object(lib, "BUNDLE_LIMIT", 128):
            self.assert_registration_rejected()

    def test_invalid_profile_type_and_unsafe_translation_unavailable(self):
        entry = self.register()
        with self.assertRaises(LibraryError):
            self.library.select(entry.entry_id, ["desk"])
        for translated in ("special://profile/", "relative", str(self.base) + "/../escape"):
            vfs = SimpleNamespace(translatePath=lambda path: translated)
            with patch.dict("sys.modules", {"xbmcvfs": vfs}):
                self.assertIsNone(default_status_target())
                self.assertIsNone(default_plan_target())

    def test_directory_swap_cannot_redirect_writes_to_outside(self):
        entry = self.register()
        outside = self.base / "outside"
        outside.mkdir()
        sentinel = outside / "selection.json"
        sentinel.write_text(SECRET)
        held = self.base / "held-library"
        atomic = lib._atomic
        def swap(fd, name, data):
            self.root.rename(held)
            self.root.symlink_to(outside, target_is_directory=True)
            return atomic(fd, name, data)
        with patch.object(lib, "_atomic", side_effect=swap):
            # Publication remains anchored to the originally opened directory.
            self.library.select(entry.entry_id, "desk")
        self.assertEqual(sentinel.read_text(), SECRET)
        self.assertEqual(BuildLibrary(held).current_selection().entry_id, entry.entry_id)
        self.assertIsNone(self.library.current_selection())

    def test_nonregular_lock_rejected_without_selecting(self):
        entry = self.register()
        lock = self.root / "library.lock"
        lock.unlink()
        os.mkfifo(lock)
        with self.assertRaises(LibraryError):
            self.library.select(entry.entry_id, "desk")
        self.assertIsNone(self.library.current_selection())

    # -- Build Status presentation: applied build and saved selection (Item 8) ----------

    def record_second_build(self):
        """A second, distinct build (version 2.0.0). The applied association is untouched."""
        self.raw["build"]["version"] = "2.0.0"
        self.write_sources()
        return self.register()

    def test_selection_state_classifies_none_selected_and_invalid_read_only(self):
        self.assertEqual(self.library.selection_state(), ("none", None))
        self.assertFalse(self.root.exists())                    # never creates the library
        entry = self.register()
        self.assertEqual(self.library.selection_state(), ("none", None))
        selected = self.library.select(entry.entry_id, "desk")
        path = self.root / "selection.json"
        before = path.read_bytes()
        self.assertEqual(self.library.selection_state(), ("selected", selected))
        self.assertEqual(self.library.current_selection(), selected)
        self.assertEqual(path.read_bytes(), before)              # read-only
        self.library.clear_selection()
        self.assertEqual(self.library.selection_state(), ("none", None))
        valid = {"schema_version": 1, "entry_id": entry.entry_id, "device_profile_id": "desk"}
        for changes in ({"device_profile_id": "missing"}, {"entry_id": "b" * 64},
                        {"entry_id": "../escape"}, {"schema_version": 2}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps({**valid, **changes}))
                self.assertEqual(self.library.selection_state(), ("invalid", None))
                self.assertIsNone(self.library.current_selection())
        path.write_text("invalid")
        self.assertEqual(self.library.selection_state(), ("invalid", None))
        path.write_text(json.dumps(valid))
        self.assertEqual(self.library.selection_state()[0], "selected")
        self.envelope(entry.entry_id).unlink()                   # selected build became unreadable
        self.assertEqual(self.library.selection_state(), ("invalid", None))
        self.assertIsNone(self.library.current_selection())

    def test_presentation_applied_only_names_the_applied_build_and_no_selection(self):
        entry = self.register()
        self.record_applied(entry)
        presentation = build_presentation(self.library, self.library.associated_status_target())
        self.assertEqual(presentation, BuildPresentation(applied=BuildIdentity("Demo", "1.0.0", "desk")))

    def test_presentation_selection_of_the_applied_build_is_not_duplicated(self):
        entry = self.register()
        self.record_applied(entry)
        self.library.select(entry.entry_id, "desk")
        presentation = build_presentation(self.library, self.library.associated_status_target())
        self.assertEqual(presentation, BuildPresentation(applied=BuildIdentity("Demo", "1.0.0", "desk")))

    def test_presentation_applied_a_and_selected_b_are_distinct_and_health_stays_on_a(self):
        a = self.register()
        self.record_applied(a)
        b = self.record_second_build()
        self.library.select(b.entry_id, "other")
        target = self.library.associated_status_target()
        presentation = build_presentation(self.library, target)
        self.assertEqual(presentation, BuildPresentation(
            applied=BuildIdentity("Demo", "1.0.0", "desk"),
            selected=BuildIdentity("Demo", "2.0.0", "other")))
        self.assertEqual((target.library_source.entry_id, target.device_profile_id), (a.entry_id, "desk"))

    def test_presentation_selection_without_applied_is_context_only(self):
        b = self.register()
        self.library.select(b.entry_id, "desk")
        self.assertIsNone(self.library.associated_status_target())
        presentation = build_presentation(self.library, None)
        self.assertEqual(presentation, BuildPresentation(selected=BuildIdentity("Demo", "1.0.0", "desk")))
        with patch('resources.lib.build_library.default_build_library', return_value=self.library):
            self.assertIsNone(default_status_target())          # no selection fallback

    def test_presentation_nothing_applied_or_selected_is_empty_and_truthful(self):
        self.assertEqual(build_presentation(self.library, None), BuildPresentation())

    def test_presentation_invalid_or_stale_selection_fails_closed_and_leaves_applied_alone(self):
        a = self.register()
        self.record_applied(a)
        self.library.select(a.entry_id, "other")
        target = self.library.associated_status_target()
        selection = self.root / "selection.json"
        for data in (b"{",
                     json.dumps({"schema_version": 1, "entry_id": a.entry_id, "device_profile_id": "removed"}).encode(),
                     json.dumps({"schema_version": 1, "entry_id": "c" * 64, "device_profile_id": "desk"}).encode()):
            with self.subTest(data=data[:24]):
                selection.write_bytes(data)
                self.assertEqual(build_presentation(self.library, target),
                                 BuildPresentation(applied=BuildIdentity("Demo", "1.0.0", "desk"),
                                                   selection_unreadable=True))
                self.assertEqual(self.library.associated_status_target(), target)

    def test_presentation_pending_publication_never_presents_the_candidate_as_applied(self):
        import uuid
        a = self.register()
        applied = self.record_applied(a)
        b = self.record_second_build()
        self.library.select(b.entry_id, "other")
        candidate = lib.AppliedBuildAssociation(b.entry_id, "other", "c" * 64)
        journal = lib.AppliedPublication(str(uuid.uuid4()), candidate, applied, "pending")
        (self.root / "applied-publication.json").write_bytes(lib._encode(journal.to_dict()))
        presentation = build_presentation(self.library, self.library.associated_status_target())
        self.assertEqual(presentation, BuildPresentation(
            applied=BuildIdentity("Demo", "1.0.0", "desk"),
            selected=BuildIdentity("Demo", "2.0.0", "other")))
        # With no previous association, the pending candidate is only a selection.
        journal = lib.AppliedPublication(str(uuid.uuid4()), candidate, None, "pending")
        (self.root / "applied-publication.json").write_bytes(lib._encode(journal.to_dict()))
        self.assertIsNone(self.library.associated_status_target())
        self.assertEqual(build_presentation(self.library, None),
                         BuildPresentation(selected=BuildIdentity("Demo", "2.0.0", "other")))

    def test_presentation_unreadable_names_are_reported_without_internal_detail(self):
        a = self.register()
        self.record_applied(a)
        self.library.select(a.entry_id, "other")
        target = self.library.associated_status_target()

        class Unreadable:
            def get(self, key):
                raise LibraryError("internal detail /private/path")
            def selection_state(self):
                return ("invalid", None)

        self.assertEqual(build_presentation(Unreadable(), target),
                         BuildPresentation(applied_unreadable=True, selection_unreadable=True))

        b = self.record_second_build()
        applied_entry, selected_entry, library = a.entry_id, b.entry_id, self.library

        class SelectedUnreadable:
            def get(self, key):
                if key == applied_entry:
                    return library.get(key)
                raise LibraryError("selected build unreadable")
            def selection_state(self):
                return ("selected", lib.SelectedBuild(selected_entry, "other"))

        self.assertEqual(build_presentation(SelectedUnreadable(), target),
                         BuildPresentation(applied=BuildIdentity("Demo", "1.0.0", "desk"),
                                           selection_unreadable=True))

    def test_presentation_requires_the_verified_applied_association(self):
        b = self.register()
        self.library.select(b.entry_id, "desk")
        with self.assertRaises(ValueError):
            build_presentation(self.library, self.library.selected_status_target())

    def test_presentation_is_read_only_and_never_writes_or_uses_the_network(self):
        a = self.register()
        self.record_applied(a)
        b = self.record_second_build()
        self.library.select(b.entry_id, "other")
        before = snapshot_tree(self.base / "bm")
        with patch.object(BuildLibrary, "select", side_effect=AssertionError("select")), \
                patch.object(BuildLibrary, "clear_selection", side_effect=AssertionError("clear")), \
                patch.object(BuildLibrary, "register", side_effect=AssertionError("register")), \
                patch.object(socket, "socket", side_effect=AssertionError("network")):
            presentation = build_presentation(self.library, self.library.associated_status_target())
            with patch('resources.lib.build_library.default_build_library', return_value=self.library):
                production = default_build_presentation(self.library.associated_status_target())
        self.assertEqual(presentation, production)
        self.assertEqual(snapshot_tree(self.base / "bm"), before)

    def test_presentation_exposes_only_names_versions_and_profile_labels(self):
        a = self.register()
        applied = self.record_applied(a)
        self.library.select(a.entry_id, "other")
        presentation = build_presentation(self.library, self.library.associated_status_target())
        text = repr(presentation)
        for hidden in (a.entry_id, applied.resolution_fingerprint, str(self.root), str(self.base),
                       "safe-overlay", "transaction", SECRET, DB_SECRET):
            self.assertNotIn(hidden, text)

    def test_selection_never_changes_applied_health_or_becomes_its_target(self):
        a = self.register()
        self.record_applied(a)
        harness = PlanHarness(self, with_private=False, with_resource=False)
        owners = harness.owners(resolver=resolve_manifest)
        target = self.library.associated_status_target()

        def health(status):
            return (status.overall, status.gaps, status.build_selected, status.software,
                    status.skin, status.configuration, status.private)

        applied_only = health(BuildStatusService(owners).check(target))
        b = self.record_second_build()
        self.library.select(b.entry_id, "other")
        self.assertEqual(health(BuildStatusService(owners).check(self.library.associated_status_target())),
                         applied_only)
        (self.root / "selection.json").write_text("invalid")
        self.assertEqual(health(BuildStatusService(owners).check(self.library.associated_status_target())),
                         applied_only)
        self.assertEqual(self.library.associated_status_target(), target)

    def test_production_presentation_fallbacks_never_claim_a_selection_or_hide_an_applied_build(self):
        a = self.register()
        self.record_applied(a)
        self.library.select(a.entry_id, "other")
        target = self.library.associated_status_target()
        with patch('resources.lib.build_library.default_build_library', side_effect=LibraryError("gone")):
            self.assertEqual(default_build_presentation(target), BuildPresentation(applied_unreadable=True))
            self.assertEqual(default_build_presentation(None), BuildPresentation())

    def test_check_build_status_attaches_presentation_and_keeps_applied_health(self):
        from resources.lib import status as status_module
        a = self.register()
        self.record_applied(a)
        b = self.record_second_build()
        self.library.select(b.entry_id, "other")
        harness = PlanHarness(self, with_private=False, with_resource=False)
        owners = harness.owners(resolver=resolve_manifest)
        with patch('resources.lib.build_library.default_build_library', return_value=self.library), \
                patch.object(status_module, "default_status_owners", return_value=owners):
            status = check_build_status()
        expected = BuildStatusService(owners).check(self.library.associated_status_target())
        self.assertEqual((status.overall, status.gaps, status.build_selected),
                         (expected.overall, expected.gaps, expected.build_selected))
        self.assertEqual(status.presentation, BuildPresentation(
            applied=BuildIdentity("Demo", "1.0.0", "desk"),
            selected=BuildIdentity("Demo", "2.0.0", "other")))
