"""Tests for BM-021B inventory, closure, acquisition, and manifest core."""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from resources.lib.artifacts import ArtifactStore
from resources.lib.frozen import (
    CaptureStatus,
    InMemoryInventoryBackend,
    ProvenanceStatus,
    capture_frozen_build,
)


def _xml(addon_id, version="1.0.0", imports=()):
    import_parts = []
    for target, minimum, optional in imports:
        optional_attr = ' optional="true"' if optional else ""
        import_parts.append(
            f'<import addon="{target}" version="{minimum}"{optional_attr}/>'
        )
    imports_xml = "".join(import_parts)
    requires = f"<requires>{imports_xml}</requires>" if imports_xml else ""
    return f'<addon id="{addon_id}" version="{version}" name="{addon_id}">{requires}</addon>'.encode()


def _zip(addon_id, version="1.0.0"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(f"{addon_id}/addon.xml", _xml(addon_id, version))
    return output.getvalue()


def _addon(addon_id, version="1.0.0", enabled=True, addon_type="xbmc.python.module"):
    return {"addonid": addon_id, "version": version, "enabled": enabled, "type": addon_type}


class TestFrozenCapture(unittest.TestCase):
    def test_transitive_required_and_optional_closure_is_deterministic(self):
        addons = [_addon("plugin.root", addon_type="xbmc.python.plugin.video"),
                  _addon("script.required"), _addon("script.optional", enabled=False)]
        xml = {
            "plugin.root": _xml("plugin.root", imports=(("script.required", "1.0.0", False), ("script.optional", "1.0.0", True))),
            "script.required": _xml("script.required"),
            "script.optional": _xml("script.optional"),
        }
        packages = {
            (item, "1.0.0"): [(f"{item}-1.0.0.zip", _zip(item))]
            for item in ("plugin.root", "script.required", "script.optional")
        }
        with tempfile.TemporaryDirectory() as directory:
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend(addons, xml, package_cache=packages),
                store=ArtifactStore(Path(directory)), root_addon_ids=["plugin.root"],
                build_id="build-a", name="Example", created_at="2026-01-01T00:00:00Z",
            )
        self.assertTrue(result.complete)
        self.assertEqual(["plugin.root", "script.optional", "script.required"], [node.addon_id for node in result.manifest.addons])
        root = result.manifest.addons[0]
        self.assertEqual(("script.required",), root.required_dependency_ids)
        self.assertEqual(("script.optional",), root.optional_dependency_ids)
        self.assertEqual(result.manifest.fingerprint(), result.manifest.fingerprint())

    def test_system_dependency_is_recorded_without_artifact(self):
        addons = [_addon("plugin.root", addon_type="xbmc.python.plugin.video")]
        xml = {"plugin.root": _xml("plugin.root", imports=(("xbmc.python", "3.0.0", False),))}
        package = {("plugin.root", "1.0.0"): [("plugin.root.zip", _zip("plugin.root"))]}
        with tempfile.TemporaryDirectory() as directory:
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend(addons, xml, package_cache=package),
                store=ArtifactStore(Path(directory)), root_addon_ids=["plugin.root"],
                build_id="build-a", name="Example", created_at="now",
            )
        system = next(node for node in result.manifest.addons if node.addon_id == "xbmc.python")
        self.assertEqual(CaptureStatus.SYSTEM, system.status)
        self.assertIsNone(system.artifact)
        self.assertTrue(result.complete)

    def test_missing_exact_artifact_is_incomplete_and_not_latest_substituted(self):
        addons = [_addon("plugin.root")]
        xml = {"plugin.root": _xml("plugin.root")}
        wrong_version = {("plugin.root", "1.0.0"): [("plugin.root-2.0.0.zip", _zip("plugin.root", "2.0.0"))]}
        with tempfile.TemporaryDirectory() as directory:
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend(addons, xml, package_cache=wrong_version),
                store=ArtifactStore(Path(directory)), root_addon_ids=["plugin.root"],
                build_id="build-a", name="Example", created_at="now",
            )
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.manifest.capture_status)
        self.assertFalse(result.complete)
        self.assertIn("exact artifact unavailable", result.errors[0])

    def test_missing_root_is_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend([], {}),
                store=ArtifactStore(Path(directory)), root_addon_ids=["plugin.missing"],
                build_id="build-a", name="Example", created_at="now",
            )
        self.assertEqual(CaptureStatus.MISSING, result.manifest.capture_status)
        self.assertFalse(result.complete)

    def test_malformed_installed_metadata_fails_closed(self):
        addons = [_addon("plugin.root")]
        with tempfile.TemporaryDirectory() as directory:
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend(addons, {"plugin.root": b"<addon"}),
                store=ArtifactStore(Path(directory)), root_addon_ids=["plugin.root"],
                build_id="build-a", name="Example", created_at="now",
            )
        self.assertEqual(CaptureStatus.UNSUPPORTED, result.manifest.capture_status)
        self.assertFalse(result.complete)

    def test_unknown_provenance_is_honest_and_not_fabricated(self):
        addons = [_addon("plugin.root")]
        xml = {"plugin.root": _xml("plugin.root")}
        package = {("plugin.root", "1.0.0"): [("plugin.root.zip", _zip("plugin.root"))]}
        with tempfile.TemporaryDirectory() as directory:
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend(addons, xml, package_cache=package),
                store=ArtifactStore(Path(directory)), root_addon_ids=["plugin.root"],
                build_id="build-a", name="Example", created_at="now",
            )
        node = result.manifest.addons[0]
        self.assertEqual(ProvenanceStatus.UNKNOWN, node.provenance)
        self.assertTrue(result.complete)
        self.assertNotIn("repository", node.provenance_detail)

    def test_manifest_json_is_stable_for_same_source_graph(self):
        addons = [_addon("plugin.root")]
        xml = {"plugin.root": _xml("plugin.root")}
        package = {("plugin.root", "1.0.0"): [("plugin.root.zip", _zip("plugin.root"))]}
        manifests = []
        for build_id in ("build-a", "build-b"):
            with tempfile.TemporaryDirectory() as directory:
                result = capture_frozen_build(
                    backend=InMemoryInventoryBackend(addons, xml, package_cache=package),
                    store=ArtifactStore(Path(directory)), root_addon_ids=["plugin.root"],
                    build_id=build_id, name="Example", created_at="different",
                )
                manifests.append(result.manifest)
        self.assertEqual(manifests[0].fingerprint(), manifests[1].fingerprint())
        self.assertNotEqual(manifests[0].to_dict()["build_id"], manifests[1].to_dict()["build_id"])
