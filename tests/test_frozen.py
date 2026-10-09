"""Tests for BM-021B inventory, closure, acquisition, and manifest core."""

import io
import os
import signal
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from resources.lib.artifacts import ArtifactStore
from resources.lib.frozen import (
    CaptureStatus,
    FrozenBuildManifest,
    InMemoryInventoryBackend,
    KodiInventoryBackend,
    ProvenanceStatus,
    capture_frozen_build,
)
from resources.lib.frozen_install import (
    FrozenInstallValidationError,
    validate_frozen_manifest,
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
            store = ArtifactStore(Path(directory))
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend(addons, xml, package_cache=package),
                store=store, root_addon_ids=["plugin.root"],
                build_id="build-a", name="Example", created_at="now",
            )
            plan = validate_frozen_manifest(result.manifest, store)
        system = next(node for node in result.manifest.addons if node.addon_id == "xbmc.python")
        self.assertEqual(CaptureStatus.SYSTEM, system.status)
        self.assertIsNone(system.artifact)
        self.assertTrue(result.complete)
        self.assertNotIn("xbmc.python", [node.addon_id for node in plan.install_order])

    def test_complete_capture_validates_and_skips_only_absent_optional_dependency(self):
        addons = [
            _addon("plugin.root", addon_type="xbmc.python.plugin.video"),
            _addon("script.optional.installed"),
        ]
        xml = {
            "plugin.root": _xml(
                "plugin.root",
                imports=(("script.optional.installed", "1.0.0", True),),
            ),
            "script.optional.installed": _xml(
                "script.optional.installed",
                imports=(("script.optional.absent", "1.0.0", True),),
            ),
        }
        packages = {
            (addon_id, "1.0.0"): [(f"{addon_id}.zip", _zip(addon_id))]
            for addon_id in ("plugin.root", "script.optional.installed")
        }
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend(addons, xml, package_cache=packages),
                store=store,
                root_addon_ids=["plugin.root"],
                build_id="build-optional-absent",
                name="Optional dependency fixture",
                created_at="now",
                kodi_version="21.1",
                platform="macos",
            )
            decoded = type(result.manifest).from_json(result.manifest.to_json())
            plan = validate_frozen_manifest(decoded, store)

        absent = next(
            node for node in result.manifest.addons
            if node.addon_id == "script.optional.absent"
        )
        self.assertTrue(result.complete)
        self.assertEqual(CaptureStatus.MISSING, absent.status)
        self.assertEqual("", absent.version)
        self.assertTrue(absent.optional)
        self.assertFalse(absent.desired_enabled)
        self.assertIsNone(absent.artifact)
        self.assertEqual(
            ["script.optional.installed", "plugin.root"],
            [node.addon_id for node in plan.install_order],
        )

    def test_installed_optional_dependency_without_artifact_is_incomplete(self):
        addons = [
            _addon("plugin.root", addon_type="xbmc.python.plugin.video"),
            _addon("script.optional.installed"),
        ]
        xml = {
            "plugin.root": _xml(
                "plugin.root",
                imports=(("script.optional.installed", "1.0.0", True),),
            ),
            "script.optional.installed": _xml("script.optional.installed"),
        }
        packages = {("plugin.root", "1.0.0"): [("plugin.root.zip", _zip("plugin.root"))]}
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            result = capture_frozen_build(
                backend=InMemoryInventoryBackend(addons, xml, package_cache=packages),
                store=store,
                root_addon_ids=["plugin.root"],
                build_id="build-optional-installed-missing-artifact",
                name="Optional installed fixture",
                created_at="now",
            )
            self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.manifest.capture_status)
            with self.assertRaises(FrozenInstallValidationError):
                validate_frozen_manifest(result.manifest, store)

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


def _write_addon(root, addon_id, *, version="1.0.0", imports=()):
    directory = root / addon_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "addon.xml").write_bytes(_xml(addon_id, version=version, imports=imports))
    return directory


def _kodi_entry(addon_id, path, version="1.0.0", addon_type="xbmc.python.module"):
    return {"addonid": addon_id, "version": version, "type": addon_type, "enabled": True,
            "installed": True, "broken": False, "path": path, "dependencies": []}


def _kodi_rpc(entries):
    def rpc(method, params):
        if method == "Addons.GetAddons":
            return {"addons": [dict(entry) for entry in entries]}
        if method == "Application.GetProperties":
            return {"version": {"major": 21, "minor": 3}}
        raise AssertionError(method)
    return rpc


class KodiInventoryAddonXmlTests(unittest.TestCase):
    """Installed addon.xml may come only from an explicit trusted Kodi root."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "home" / "addons"
        self.application = self.base / "application" / "addons"
        self.outside = self.base / "outside"
        self.cache = self.base / "packages"
        for root in (self.home, self.application, self.outside):
            root.mkdir(parents=True)

    def backend(self, entries, *, application=True):
        kwargs = {"application_addons_dir": self.application} if application else {}
        return KodiInventoryBackend(
            _kodi_rpc(entries), addons_dir=self.home, package_cache_dir=self.cache, **kwargs,
        )

    def test_home_addons_path_remains_readable(self):
        _write_addon(self.home, "plugin.demo")
        backend = self.backend(
            [_kodi_entry("plugin.demo", "special://home/addons/plugin.demo/", addon_type="xbmc.python.plugin.video")],
            application=False,
        )
        self.assertEqual(
            (self.home / "plugin.demo" / "addon.xml").read_bytes(),
            backend.read_addon_xml("plugin.demo"),
        )

    def test_bundled_special_path_reads_from_trusted_application_root(self):
        _write_addon(self.application, "script.module.pil", version="5.1.0",
                     imports=(("xbmc.python", "3.0.0", False),))
        backend = self.backend([_kodi_entry("script.module.pil", "special://xbmc/addons/script.module.pil/", "5.1.0")])
        self.assertEqual(
            (self.application / "script.module.pil" / "addon.xml").read_bytes(),
            backend.read_addon_xml("script.module.pil"),
        )

    def test_bundled_absolute_translated_path_reads_from_trusted_application_root(self):
        _write_addon(self.application, "script.module.pil", version="5.1.0",
                     imports=(("xbmc.python", "3.0.0", False),))
        path = str(self.application / "script.module.pil") + "/"
        backend = self.backend([_kodi_entry("script.module.pil", path, "5.1.0")])
        self.assertEqual(
            (self.application / "script.module.pil" / "addon.xml").read_bytes(),
            backend.read_addon_xml("script.module.pil"),
        )

    def test_arbitrary_absolute_path_outside_trusted_roots_is_rejected(self):
        _write_addon(self.outside, "script.module.pil", version="5.1.0")
        path = str(self.outside / "script.module.pil") + "/"
        backend = self.backend([_kodi_entry("script.module.pil", path, "5.1.0")])
        self.assertIsNone(backend.read_addon_xml("script.module.pil"))

    def test_traversal_and_escaping_paths_are_rejected(self):
        _write_addon(self.outside, "script.module.pil", version="5.1.0")
        escapes = (
            "special://home/addons/../../outside/script.module.pil/",
            "special://xbmc/addons/../../outside/script.module.pil/",
            str(self.home / ".." / ".." / "outside" / "script.module.pil") + "/",
        )
        for path in escapes:
            with self.subTest(path=path):
                backend = self.backend([_kodi_entry("script.module.pil", path, "5.1.0")])
                self.assertIsNone(backend.read_addon_xml("script.module.pil"))

    def test_prefix_confusion_and_sibling_directories_are_rejected(self):
        _write_addon(self.base / "home" / "addons-evil", "script.module.pil", version="5.1.0")
        _write_addon(self.base / "home" / "other", "script.module.pil", version="5.1.0")
        paths = (
            str(self.base / "home" / "addons-evil" / "script.module.pil") + "/",
            str(self.base / "home" / "other" / "script.module.pil") + "/",
            "special://home/addons-evil/script.module.pil/",
        )
        for path in paths:
            with self.subTest(path=path):
                backend = self.backend([_kodi_entry("script.module.pil", path, "5.1.0")])
                self.assertIsNone(backend.read_addon_xml("script.module.pil"))

    def test_symlinked_add_on_directory_cannot_escape_its_root(self):
        _write_addon(self.outside, "script.module.pil", version="5.1.0")
        _write_addon(self.outside, "plugin.demo")
        (self.application / "script.module.pil").symlink_to(
            self.outside / "script.module.pil", target_is_directory=True)
        (self.home / "plugin.demo").symlink_to(self.outside / "plugin.demo", target_is_directory=True)
        bundled = self.backend([_kodi_entry("script.module.pil", "special://xbmc/addons/script.module.pil/", "5.1.0")])
        self.assertIsNone(bundled.read_addon_xml("script.module.pil"))
        home = self.backend(
            [_kodi_entry("plugin.demo", "special://home/addons/plugin.demo/")], application=False,
        )
        self.assertIsNone(home.read_addon_xml("plugin.demo"))

    def test_symlinked_addon_xml_cannot_redirect_the_read(self):
        _write_addon(self.outside, "script.module.pil", version="5.1.0")
        directory = _write_addon(self.application, "script.module.pil", version="5.1.0")
        (directory / "addon.xml").unlink()
        (directory / "addon.xml").symlink_to(self.outside / "script.module.pil" / "addon.xml")
        backend = self.backend([_kodi_entry("script.module.pil", "special://xbmc/addons/script.module.pil/", "5.1.0")])
        self.assertIsNone(backend.read_addon_xml("script.module.pil"))

    def test_non_regular_addon_xml_is_rejected_without_blocking(self):
        directory = _write_addon(self.application, "script.module.pil", version="5.1.0")
        (directory / "addon.xml").unlink()
        os.mkfifo(directory / "addon.xml")
        backend = self.backend([_kodi_entry("script.module.pil", "special://xbmc/addons/script.module.pil/", "5.1.0")])

        def interrupted(signum, frame):
            raise TimeoutError("addon.xml read blocked on a special file")

        previous = signal.signal(signal.SIGALRM, interrupted)
        signal.alarm(5)
        try:
            result = backend.read_addon_xml("script.module.pil")
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        self.assertIsNone(result)

    def test_wrong_add_on_directory_is_rejected(self):
        _write_addon(self.application, "other.addon", version="5.1.0")
        _write_addon(self.home, "other.addon", version="5.1.0")
        bundled = self.backend([_kodi_entry("script.module.pil", "special://xbmc/addons/other.addon/", "5.1.0")])
        self.assertIsNone(bundled.read_addon_xml("script.module.pil"))
        home = self.backend(
            [_kodi_entry("script.module.pil", "special://home/addons/other.addon/", "5.1.0")], application=False,
        )
        self.assertIsNone(home.read_addon_xml("script.module.pil"))

    def test_add_on_identifiers_are_never_path_traversal(self):
        (self.base / "home" / "addon.xml").write_bytes(_xml("..", version="1.0.0"))
        (self.outside / "addon.xml").write_bytes(_xml("../outside", version="1.0.0"))
        for hostile in ("..", "../outside", "a/../..", "/absolute"):
            with self.subTest(addon_id=hostile):
                backend = self.backend([_kodi_entry(hostile, "")], application=False)
                self.assertIsNone(backend.read_addon_xml(hostile))
        escaping = self.backend([_kodi_entry("../outside", "special://home/addons/../outside/")], application=False)
        self.assertIsNone(escaping.read_addon_xml("../outside"))

    def test_entry_without_path_uses_only_the_home_addons_directory(self):
        _write_addon(self.home, "plugin.demo")
        backend = self.backend([_kodi_entry("plugin.demo", "")], application=False)
        self.assertEqual(
            (self.home / "plugin.demo" / "addon.xml").read_bytes(),
            backend.read_addon_xml("plugin.demo"),
        )


class FrozenCaptureTruthTests(unittest.TestCase):
    """Blocking metadata and closure errors can never leave a COMPLETE graph behind."""

    ROOT = "plugin.root"
    DEP = "script.required"

    def capture(self, backend, store_dir, roots):
        return capture_frozen_build(
            backend=backend, store=ArtifactStore(store_dir), root_addon_ids=roots,
            build_id="truth", name="Truth", created_at="now", kodi_version="21.3", platform="macos",
        )

    def test_missing_addon_xml_blocks_node_manifest_and_result(self):
        addons = [_addon(self.ROOT, addon_type="xbmc.python.plugin.video"), _addon(self.DEP)]
        addons[0]["dependencies"] = [{"addonid": self.DEP, "version": "1.0.0", "optional": False}]
        xml = {self.DEP: _xml(self.DEP)}
        packages = {
            (self.ROOT, "1.0.0"): [(self.ROOT + ".zip", _zip(self.ROOT))],
            (self.DEP, "1.0.0"): [(self.DEP + ".zip", _zip(self.DEP))],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self.capture(InMemoryInventoryBackend(addons, xml, package_cache=packages),
                                  Path(directory), [self.ROOT])
            store = ArtifactStore(Path(directory))
            root_node = next(node for node in result.manifest.addons if node.addon_id == self.ROOT)
            self.assertEqual(CaptureStatus.UNSUPPORTED, root_node.status)
            self.assertEqual((), root_node.dependency_edges)
            self.assertIn(f"{self.ROOT}: addon.xml unavailable", result.errors)
            self.assertNotEqual(CaptureStatus.COMPLETE, result.manifest.capture_status)
            self.assertFalse(result.complete)
            decoded = FrozenBuildManifest.from_json(result.manifest.to_json())
            self.assertNotEqual(CaptureStatus.COMPLETE, decoded.capture_status)
            with self.assertRaises(FrozenInstallValidationError):
                validate_frozen_manifest(result.manifest, store)

    def test_identity_mismatch_is_a_blocking_metadata_failure(self):
        addons = [_addon(self.ROOT, addon_type="xbmc.python.plugin.video")]
        xml = {self.ROOT: _xml("plugin.other")}
        packages = {(self.ROOT, "1.0.0"): [(self.ROOT + ".zip", _zip(self.ROOT))]}
        with tempfile.TemporaryDirectory() as directory:
            result = self.capture(InMemoryInventoryBackend(addons, xml, package_cache=packages),
                                  Path(directory), [self.ROOT])
        root_node = next(node for node in result.manifest.addons if node.addon_id == self.ROOT)
        self.assertEqual(CaptureStatus.UNSUPPORTED, root_node.status)
        self.assertEqual((), root_node.dependency_edges)
        self.assertNotEqual(CaptureStatus.COMPLETE, result.manifest.capture_status)
        self.assertFalse(result.complete)

    def test_installed_version_mismatch_is_a_blocking_metadata_failure(self):
        addons = [_addon(self.ROOT, version="1.0.0", addon_type="xbmc.python.plugin.video")]
        xml = {self.ROOT: _xml(self.ROOT, version="2.0.0")}
        packages = {(self.ROOT, "1.0.0"): [(self.ROOT + ".zip", _zip(self.ROOT))]}
        with tempfile.TemporaryDirectory() as directory:
            result = self.capture(InMemoryInventoryBackend(addons, xml, package_cache=packages),
                                  Path(directory), [self.ROOT])
        self.assertNotEqual(CaptureStatus.COMPLETE, result.manifest.capture_status)
        self.assertFalse(result.complete)

    def test_rpc_dependencies_are_not_substituted_for_unreadable_addon_xml(self):
        addons = [_addon(self.ROOT, addon_type="xbmc.python.plugin.video"), _addon(self.DEP)]
        addons[0]["dependencies"] = [{"addonid": self.DEP, "version": "1.0.0", "optional": False}]
        packages = {(self.ROOT, "1.0.0"): [(self.ROOT + ".zip", _zip(self.ROOT))]}
        with tempfile.TemporaryDirectory() as directory:
            result = self.capture(InMemoryInventoryBackend(addons, {self.DEP: _xml(self.DEP)},
                                                           package_cache=packages),
                                  Path(directory), [self.ROOT])
        root_node = next(node for node in result.manifest.addons if node.addon_id == self.ROOT)
        self.assertNotIn(self.DEP, [edge.addon_id for edge in root_node.dependency_edges])
        self.assertFalse(result.complete)

    def test_dependency_cycle_blocks_manifest_and_result(self):
        first, second = "script.cycle.a", "script.cycle.b"
        addons = [_addon(first), _addon(second)]
        xml = {
            first: _xml(first, imports=((second, "1.0.0", False),)),
            second: _xml(second, imports=((first, "1.0.0", False),)),
        }
        packages = {
            (first, "1.0.0"): [(first + ".zip", _zip(first))],
            (second, "1.0.0"): [(second + ".zip", _zip(second))],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self.capture(InMemoryInventoryBackend(addons, xml, package_cache=packages),
                                  Path(directory), [first])
        self.assertTrue(any("dependency cycle" in error for error in result.errors))
        self.assertNotEqual(CaptureStatus.COMPLETE, result.manifest.capture_status)
        self.assertFalse(result.complete)

    def test_bundled_pil_shaped_addon_captures_its_system_edge_and_exact_artifact(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        home, application, cache = base / "home", base / "application" / "addons", base / "packages"
        home.mkdir()
        application.mkdir(parents=True)
        cache.mkdir()
        _write_addon(application, "script.module.pil", version="5.1.0",
                     imports=(("xbmc.python", "3.0.0", False),))
        (cache / "script.module.pil-5.1.0.zip").write_bytes(_zip("script.module.pil", "5.1.0"))
        backend = KodiInventoryBackend(
            _kodi_rpc([_kodi_entry("script.module.pil", "special://xbmc/addons/script.module.pil/", "5.1.0")]),
            addons_dir=home, package_cache_dir=cache, application_addons_dir=application,
        )
        store_dir = base / "artifacts"
        result = capture_frozen_build(
            backend=backend, store=ArtifactStore(store_dir), root_addon_ids=["script.module.pil"],
            build_id="pil", name="PIL", created_at="now",
        )
        nodes = {node.addon_id: node for node in result.manifest.addons}
        pil = nodes["script.module.pil"]
        self.assertFalse(pil.system)
        self.assertEqual("5.1.0", pil.version)
        self.assertEqual("xbmc.python.module", pil.addon_type)
        self.assertEqual(CaptureStatus.COMPLETE, pil.status)
        self.assertIsNotNone(pil.artifact)
        self.assertEqual([("xbmc.python", "3.0.0", False)],
                         [(edge.addon_id, edge.min_version, edge.optional) for edge in pil.dependency_edges])
        self.assertTrue(nodes["xbmc.python"].system)
        self.assertTrue(result.complete)
        validate_frozen_manifest(result.manifest, ArtifactStore(store_dir))


class TrustedRootAuthorityTests(unittest.TestCase):
    """Authority is bound to the trusted root object established at construction.

    Replacing that root, any ancestor, or the root path itself must not redirect
    metadata reads into a different filesystem object.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.trusted = self.base / "trusted" / "addons"
        self.outside = self.base / "outside"
        self.home = self.base / "home" / "addons"
        self.cache = self.base / "packages"
        self.cache.mkdir()
        self.home.mkdir(parents=True)
        self.trusted.mkdir(parents=True)
        self.outside.mkdir()
        _write_addon(self.trusted, "script.demo", version="1.0.0")
        _write_addon(self.outside / "addons", "script.demo", version="1.0.0",
                     imports=(("script.outside.dep", "1.0.0", False),))
        _write_addon(self.home, "script.outside.dep", version="1.0.0")
        (self.cache / "script.demo-1.0.0.zip").write_bytes(_zip("script.demo"))
        (self.cache / "script.outside.dep-1.0.0.zip").write_bytes(_zip("script.outside.dep"))

    def backend(self, *, application=None):
        entries = [
            _kodi_entry("script.demo", "special://xbmc/addons/script.demo/", "1.0.0"),
            _kodi_entry("script.outside.dep", "special://home/addons/script.outside.dep/", "1.0.0"),
        ]
        return KodiInventoryBackend(
            _kodi_rpc(entries), addons_dir=self.home, package_cache_dir=self.cache,
            application_addons_dir=self.trusted if application is None else application,
        )

    def capture(self, backend):
        return capture_frozen_build(
            backend=backend, store=ArtifactStore(self.base / "artifacts"),
            root_addon_ids=["script.demo"], build_id="authority", name="Authority",
            created_at="now", kodi_version="21.3", platform="macos",
        )

    def assertFailsClosed(self, backend, *, reason):
        self.assertIsNone(backend.read_addon_xml("script.demo"), reason)
        result = self.capture(backend)
        self.assertNotEqual(CaptureStatus.COMPLETE, result.manifest.capture_status, reason)
        self.assertFalse(result.complete, reason)
        node = next(n for n in result.manifest.addons if n.addon_id == "script.demo")
        self.assertNotIn("script.outside.dep", [edge.addon_id for edge in node.dependency_edges], reason)

    def test_ancestor_replacement_cannot_redirect_a_special_path_read(self):
        backend = self.backend()
        (self.base / "trusted").rename(self.base / "trusted-original")
        (self.base / "trusted").symlink_to(self.outside)
        self.assertFailsClosed(backend, reason="ancestor symlink must not redirect the read")

    def test_same_path_root_replacement_does_not_inherit_old_authority(self):
        backend = self.backend()
        self.trusted.rename(self.base / "trusted" / "addons-original")
        _write_addon(self.trusted, "script.demo", version="1.0.0",
                     imports=(("script.outside.dep", "1.0.0", False),))
        self.assertFailsClosed(backend, reason="a new directory at the same path has a different identity")

    def test_root_replaced_by_symlink_fails_closed(self):
        backend = self.backend()
        self.trusted.rename(self.base / "trusted" / "addons-original")
        self.trusted.symlink_to(self.outside / "addons", target_is_directory=True)
        self.assertFailsClosed(backend, reason="a symlinked root must not be followed")

    def test_absolute_path_cannot_regain_authority_over_a_replacement_tree(self):
        absolute = str(self.trusted / "script.demo") + "/"
        entries = [_kodi_entry("script.demo", absolute, "1.0.0")]
        backend = KodiInventoryBackend(
            _kodi_rpc(entries), addons_dir=self.home, package_cache_dir=self.cache,
            application_addons_dir=self.trusted,
        )
        self.trusted.rename(self.base / "trusted" / "addons-original")
        _write_addon(self.trusted, "script.demo", version="1.0.0")
        self.assertIsNone(backend.read_addon_xml("script.demo"))

    def test_absolute_path_after_ancestor_symlink_fails_closed(self):
        absolute = str(self.trusted / "script.demo") + "/"
        entries = [_kodi_entry("script.demo", absolute, "1.0.0")]
        backend = KodiInventoryBackend(
            _kodi_rpc(entries), addons_dir=self.home, package_cache_dir=self.cache,
            application_addons_dir=self.trusted,
        )
        (self.base / "trusted").rename(self.base / "trusted-original")
        (self.base / "trusted").symlink_to(self.outside)
        self.assertIsNone(backend.read_addon_xml("script.demo"))

    def test_ancestor_swapped_during_acquisition_is_refused_not_followed(self):
        backend = self.backend()
        real_open = os.open
        swapped = []

        def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
            if dir_fd is not None and path == "trusted" and not swapped:
                swapped.append(path)
                (self.base / "trusted").rename(self.base / "trusted-original")
                (self.base / "trusted").symlink_to(self.outside)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with patch("os.open", new=swapping_open):
            result = backend.read_addon_xml("script.demo")
        self.assertEqual(["trusted"], swapped)
        self.assertIsNone(result)

    def test_home_root_same_path_replacement_fails_closed(self):
        _write_addon(self.home, "plugin.demo", version="1.0.0")
        entries = [_kodi_entry("plugin.demo", "special://home/addons/plugin.demo/", "1.0.0")]
        backend = KodiInventoryBackend(
            _kodi_rpc(entries), addons_dir=self.home, package_cache_dir=self.cache,
        )
        self.assertIsNotNone(backend.read_addon_xml("plugin.demo"))
        self.home.rename(self.base / "home" / "addons-original")
        _write_addon(self.home, "plugin.demo", version="1.0.0")
        self.assertIsNone(backend.read_addon_xml("plugin.demo"))

    def test_closed_backend_fails_closed_and_releases_its_authority(self):
        backend = self.backend()
        self.assertIsNotNone(backend.read_addon_xml("script.demo"))
        backend.close()
        self.assertIsNone(backend.read_addon_xml("script.demo"))
        backend.close()

    def test_configured_alias_root_is_canonicalized_and_readable(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name) / "addons"
        _write_addon(target, "script.demo", version="1.0.0")
        backend = KodiInventoryBackend(
            _kodi_rpc([_kodi_entry("script.demo", "special://xbmc/addons/script.demo/", "1.0.0")]),
            addons_dir=self.home, package_cache_dir=self.cache, application_addons_dir=target,
        )
        self.assertIsNotNone(backend.read_addon_xml("script.demo"))

    def test_unchanged_home_and_bundled_roots_keep_their_authority(self):
        _write_addon(self.home, "plugin.demo", version="1.0.0")
        entries = [
            _kodi_entry("plugin.demo", "special://home/addons/plugin.demo/", "1.0.0"),
            _kodi_entry("script.demo", "special://xbmc/addons/script.demo/", "1.0.0"),
        ]
        backend = KodiInventoryBackend(
            _kodi_rpc(entries), addons_dir=self.home, package_cache_dir=self.cache,
            application_addons_dir=self.trusted,
        )
        self.assertIsNotNone(backend.read_addon_xml("plugin.demo"))
        self.assertIsNotNone(backend.read_addon_xml("script.demo"))
