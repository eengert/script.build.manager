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
from resources.lib.status import BuildStatusService, default_status_target, StatusTarget
from resources.lib.plan import BuildPlanService, PlanTarget, default_plan_target
from resources.lib.plan_model import DecisionChoice
from resources.lib.status_model import CheckGap
from tests.test_plan import PlanHarness
from tests.test_status import DEMO, SECRET, DB_SECRET


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
            self.assertEqual(default_status_target(), status_target)
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
