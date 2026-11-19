"""D-033: controlled local capture as the last-resort acquisition step. Offline only.

The official repository is a FakeMirror and every installed tree lives in a temporary
directory. Nothing here reads a real Kodi profile, application bundle or artifact store.
"""

import hashlib
import io
import os
import shutil
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from resources.lib import frozen
from resources.lib.artifacts import ArtifactStore
from resources.lib.create_capture import (
    CreateBuildCaptureEngine, CreateBuildRequest, CreateCaptureStatus, PublicCaptureSpecification,
)
from resources.lib.create_workflow import CreateBuildWorkflow
from resources.lib.frozen import (
    ArtifactAcquirer, CaptureStatus, InMemoryInventoryBackend, capture_frozen_build,
)
from resources.lib.local_capture import (
    LOCAL_CAPTURE_SOURCE, LocalCaptureRefusal, build_local_capture_zip,
)
from resources.lib.official_repository import RepositoryArtifactRefusal, RepositoryArtifactUnlisted
from tests.test_frozen import _addon as frozen_addon, _xml as frozen_xml, _zip as frozen_zip
from tests.test_official_repository_artifacts import (
    ADDON, VERSION, FakeMirror, OfficialBackendFixture, _addon_xml, _addon_zip, _index, _md5,
    _standard_index, FILENAME, HOST, SIDECAR_PATH, ARCHIVE_PATH, INDEX_PATH, CHECKSUM_PATH,
)

OTHER_INDEX = _index([("script.module.unrelated", "1.0.0", None, None)])
TMDB = ("plugin.video.themoviedb.helper", "6.17.9")
TMDB_DEPENDENCIES = (("script.module.tmdb.dependency.one", "1.2.3"), ("script.module.tmdb.dependency.two", "4.5.6"))


class LocalCaptureFixture(OfficialBackendFixture):
    """The exact add-on is installed but absent from a checksum-verified official index."""

    def setUp(self):
        super().setUp()
        self.mirror = FakeMirror()
        self.mirror.publish(archive=self.archive, index_xml=OTHER_INDEX)

    def acquire_local(self, backend=None, allowed=((ADDON, VERSION),)):
        backend = backend or self.backend()
        return ArtifactAcquirer(self.store, backend, allowed).acquire(ADDON, VERSION)

    def refused_without_registration(self, result, fragment=""):
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertIn(fragment, result.error)
        self.assertNoRegistration()


class AcquisitionPolicyTests(LocalCaptureFixture):
    def test_unlisted_without_authorisation_is_offered_but_never_captured(self):
        result = ArtifactAcquirer(self.store, self.backend()).acquire(ADDON, VERSION)
        self.assertTrue(result.local_capture_eligible)
        self.refused_without_registration(result, "not listed")

    def test_authorised_unlisted_add_on_is_captured_and_recorded_as_local(self):
        result = self.acquire_local()
        self.assertEqual(CaptureStatus.COMPLETE, result.status)
        self.assertEqual(LOCAL_CAPTURE_SOURCE, result.source)
        self.assertEqual(LOCAL_CAPTURE_SOURCE, result.metadata.source)
        self.assertNotIn(result.metadata.source, ("repository", "package_cache"))
        stored = self.store.read_bytes(result.metadata.sha256)
        self.assertEqual(hashlib.sha256(stored).hexdigest(), result.metadata.sha256)
        self.assertEqual(LOCAL_CAPTURE_SOURCE, self.store.get_metadata(result.metadata.sha256).source)
        with zipfile.ZipFile(io.BytesIO(stored)) as archive:
            self.assertEqual([f"{ADDON}/addon.xml", f"{ADDON}/lib.py"], archive.namelist())

    def test_authorisation_is_per_exact_add_on_and_version(self):
        for allowed in ((("some.other.addon", VERSION),), ((ADDON, "0.0.1"),)):
            with self.subTest(allowed=allowed):
                result = self.acquire_local(allowed=allowed)
                self.assertTrue(result.local_capture_eligible)
                self.refused_without_registration(result)

    def test_capture_is_deterministic_and_idempotent(self):
        first = self.acquire_local()
        other_store = ArtifactStore(self.base / "second-store")
        second = ArtifactAcquirer(other_store, self.backend(), ((ADDON, VERSION),)).acquire(ADDON, VERSION)
        self.assertEqual(first.metadata.sha256, second.metadata.sha256)
        again = self.acquire_local()
        self.assertEqual("artifact_store", again.source)
        self.assertEqual(LOCAL_CAPTURE_SOURCE, again.metadata.source)

    def test_store_then_cache_then_official_still_precede_local_capture(self):
        spy = mock.Mock(side_effect=AssertionError("local capture must not run"))
        backend = self.backend()
        # 1. Existing store artifact.
        stored = self.store.import_zip(self.archive, expected_addon_id=ADDON, expected_version=VERSION,
                                       source="repository")
        with mock.patch.object(backend, "capture_installed_artifact", spy):
            self.assertEqual("artifact_store", self.acquire_local(backend).source)
        # 2. Exact package-cache ZIP.
        other = ArtifactStore(self.base / "cache-store")
        (self.packages / FILENAME).write_bytes(self.archive)
        with mock.patch.object(backend, "capture_installed_artifact", spy):
            result = ArtifactAcquirer(other, backend, ((ADDON, VERSION),)).acquire(ADDON, VERSION)
        self.assertEqual("package_cache", result.source)
        self.assertEqual(stored.sha256, result.metadata.sha256)
        # 3. Official repository when the version is listed.
        (self.packages / FILENAME).unlink()
        self.mirror.publish(archive=self.archive, index_xml=_standard_index(self.archive))
        third = ArtifactStore(self.base / "official-store")
        with mock.patch.object(backend, "capture_installed_artifact", spy):
            result = ArtifactAcquirer(third, backend, ((ADDON, VERSION),)).acquire(ADDON, VERSION)
        self.assertEqual("repository", result.source)


class NoFallbackOnIntegrityFailureTests(LocalCaptureFixture):
    """Only a checksum-verified 'not listed' proves unavailability. Nothing else falls back."""

    def assert_no_fallback(self, fragment=""):
        spy = mock.Mock(side_effect=AssertionError("local capture must not run"))
        backend = self.backend()
        with mock.patch.object(backend, "capture_installed_artifact", spy):
            result = self.acquire_local(backend)
        self.assertFalse(result.local_capture_eligible)
        self.refused_without_registration(result, fragment)
        spy.assert_not_called()

    def publish_listed(self, **kwargs):
        self.mirror = FakeMirror()
        self.mirror.publish(archive=self.archive, index_xml=_standard_index(self.archive), **kwargs)

    def test_sidecar_checksum_mismatch(self):
        self.publish_listed(sidecar=f"{'0' * 32}  {FILENAME}\n".encode())
        self.assert_no_fallback("checksum")

    def test_declared_size_mismatch(self):
        self.mirror = FakeMirror()
        self.mirror.publish(archive=self.archive, index_xml=_standard_index(self.archive, size=1))
        self.assert_no_fallback("size")

    def test_index_checksum_mismatch(self):
        self.publish_listed(checksum=f"{'1' * 32}  addons.xml\n".encode())
        self.assert_no_fallback("index")

    def test_listed_archive_that_cannot_be_fetched(self):
        self.publish_listed()
        self.mirror.route(HOST, ARCHIVE_PATH, status=404)
        self.assert_no_fallback()

    def test_tls_or_network_failure(self):
        self.mirror.connect_errors[HOST] = ConnectionRefusedError("refused")
        self.assert_no_fallback()

    def test_unsuitable_destination_address(self):
        self.mirror.dns[HOST] = ["10.0.0.5"]
        self.assert_no_fallback()

    def test_malformed_index(self):
        self.mirror.publish(archive=self.archive, index_xml=b"<addons><oops")
        self.assert_no_fallback()

    def test_ambiguous_index_listing(self):
        self.mirror.publish(archive=self.archive, index_xml=_index([
            (ADDON, VERSION, f"{ADDON}/{FILENAME}", 1), (ADDON, VERSION, f"{ADDON}/{FILENAME}", 2)]))
        self.assert_no_fallback()

    def test_listed_version_whose_installed_content_differs(self):
        self.publish_listed()
        (self.home / ADDON / "lib.py").write_bytes(b"VALUE = 2\n")
        self.assert_no_fallback("differs")

    def test_unsafe_installed_tree_is_a_plain_refusal(self):
        os.symlink("/etc/hosts", self.home / ADDON / "link.txt")
        self.assert_no_fallback()

    def test_trusted_application_configuration_missing(self):
        shutil.rmtree(self.application / "repository.xbmc.org")
        self.assert_no_fallback()

    def test_only_the_unlisted_subclass_is_a_proof_of_absence(self):
        self.assertTrue(issubclass(RepositoryArtifactUnlisted, RepositoryArtifactRefusal))
        for exc in (RepositoryArtifactRefusal("x"), LocalCaptureRefusal("x")):
            self.assertNotIsInstance(exc, RepositoryArtifactUnlisted)


class PlatformProvidedTests(LocalCaptureFixture):
    def test_application_bundled_add_on_is_never_packaged(self):
        self.install(ADDON, {"addon.xml": _addon_xml()}, root=self.application)
        backend = self.backend(listing=[self.listing_entry(ADDON, path=f"special://xbmc/addons/{ADDON}/")])
        with self.assertRaisesRegex(LocalCaptureRefusal, "platform-provided"):
            backend.capture_installed_artifact(ADDON, VERSION)
        result = self.acquire_local(backend)
        self.refused_without_registration(result)

    def test_capture_flow_never_reaches_local_capture_for_platform_nodes(self):
        spy = mock.Mock(side_effect=AssertionError("must not run"))
        backend = self.backend()
        with mock.patch.object(backend, "capture_installed_artifact", spy):
            ArtifactAcquirer(self.store, backend, ((ADDON, VERSION),))  # construction alone never packages
        spy.assert_not_called()

    def test_version_must_be_the_exact_installed_version(self):
        backend = self.backend()
        with self.assertRaisesRegex(LocalCaptureRefusal, "exact requested version"):
            backend.capture_installed_artifact(ADDON, "9.9.9")
        with self.assertRaisesRegex(LocalCaptureRefusal, "exact add-on identity"):
            backend.capture_installed_artifact(ADDON, "../1")
        with self.assertRaisesRegex(LocalCaptureRefusal, "exact requested version"):
            backend.capture_installed_artifact("not.installed", VERSION)


class UnsafeTreeTests(LocalCaptureFixture):
    def assert_refused(self, fragment=""):
        self.refused_without_registration(self.acquire_local(), fragment)

    def test_symbolic_link(self):
        os.symlink("lib.py", self.home / ADDON / "alias.py")
        self.assert_refused()

    def test_symbolic_link_directory_to_outside(self):
        os.symlink(self.base, self.home / ADDON / "escape")
        self.assert_refused()

    def test_special_file(self):
        os.mkfifo(self.home / ADDON / "pipe")
        self.assert_refused()

    def test_unsafe_names(self):
        for name in ("back\\slash.py", "nul\x00name.py"):
            with self.subTest(name=name):
                try:
                    (self.home / ADDON / name).write_bytes(b"x")
                except (OSError, ValueError):
                    continue
                self.assert_refused()
                (self.home / ADDON / name).unlink()

    def test_ambiguous_case_folded_names(self):
        (self.home / ADDON / "Lib.py").write_bytes(b"x")
        if len({p.name for p in (self.home / ADDON).iterdir()}) == 3:  # case-sensitive file system
            self.assert_refused()

    def test_too_deeply_nested_content(self):
        deep = self.home / ADDON
        for index in range(40):
            deep = deep / f"d{index}"
        deep.mkdir(parents=True)
        (deep / "x.py").write_bytes(b"x")
        self.assert_refused()

    def test_file_changed_between_scans(self):
        real = frozen._digest_bounded
        state = {"calls": 0}

        def mutating(file_fd, info, totals, *rest):
            state["calls"] += 1
            result = real(file_fd, info, totals, *rest)
            if state["calls"] == 4:  # last file of the collecting scan (calls 1-2 are the official provider's scan)
                (self.home / ADDON / "lib.py").write_bytes(b"VALUE = 2\n")
            return result

        with mock.patch.object(frozen, "_digest_bounded", mutating):
            result = self.acquire_local()
        self.refused_without_registration(result, "changed during")

    def test_restored_bytes_do_not_hide_a_write(self):
        real = frozen._digest_bounded
        state = {"calls": 0}

        def rewriting(file_fd, info, totals, *rest):
            state["calls"] += 1
            result = real(file_fd, info, totals, *rest)
            if state["calls"] == 4:
                original = (self.home / ADDON / "lib.py").read_bytes()
                (self.home / ADDON / "lib.py").write_bytes(b"temporary")
                (self.home / ADDON / "lib.py").write_bytes(original)
            return result

        with mock.patch.object(frozen, "_digest_bounded", rewriting):
            result = self.acquire_local()
        self.refused_without_registration(result, "changed during")

    def test_root_replaced_after_the_scan_is_refused(self):
        real = frozen._digest_bounded
        state = {"calls": 0, "swapped": False}

        def swapping(file_fd, info, totals, *rest):
            state["calls"] += 1
            if state["calls"] == 5 and not state["swapped"]:  # first read of the verifying scan
                os.rename(self.home, self.base / "home" / "addons.old")
                shutil.copytree(self.base / "home" / "addons.old", self.home)
                state["swapped"] = True
            return real(file_fd, info, totals, *rest)

        with mock.patch.object(frozen, "_digest_bounded", swapping):
            result = self.acquire_local()
        self.assertTrue(state["swapped"])
        self.refused_without_registration(result, "location changed")

    def test_add_on_directory_replaced_during_the_scan(self):
        real = frozen._digest_bounded
        state = {"calls": 0, "swapped": False}

        def swapping(file_fd, info, totals, *rest):
            state["calls"] += 1
            if state["calls"] == 5 and not state["swapped"]:
                os.rename(self.home / ADDON, self.base / "moved")
                shutil.copytree(self.base / "moved", self.home / ADDON)
                state["swapped"] = True
            return real(file_fd, info, totals, *rest)

        with mock.patch.object(frozen, "_digest_bounded", swapping):
            result = self.acquire_local()
        self.assertTrue(state["swapped"])
        self.refused_without_registration(result, "changed during")

    def test_oversized_content_is_refused(self):
        with mock.patch.object(frozen, "LOCAL_CAPTURE_MAX_BYTES", 4):
            self.refused_without_registration(self.acquire_local(), "size limit")

    def test_addon_xml_that_disagrees_with_the_listing_is_refused(self):
        (self.home / ADDON / "addon.xml").write_bytes(_addon_xml(version="0.0.1"))
        self.assert_refused("does not match")


class PackagingRuleTests(unittest.TestCase):
    XML = _addon_xml()

    def files(self, **extra):
        files = {("addon.xml",): self.XML, ("lib.py",): b"VALUE = 1\n"}
        files.update({tuple(key.split("/")): value for key, value in extra.items()})
        return files

    def names(self, files):
        data, dropped = build_local_capture_zip(ADDON, files)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return [n[len(ADDON) + 1:] for n in archive.namelist()], dropped

    def test_executable_source_is_kept_and_generated_cache_is_dropped(self):
        names, dropped = self.names(self.files(**{
            "__pycache__/lib.cpython-311.pyc": b"c", "__pycache__/lib.cpython-311.opt-1.pyc": b"c",
            "sub/__pycache__/m.cpython-311.pyc": b"c", "sub/m.py": b"x = 1\n", ".DS_Store": b"d", "run.log": b"l"}))
        self.assertEqual(["addon.xml", "lib.py", "sub/m.py"], names)
        self.assertEqual(5, dropped)

    def test_bytecode_without_shipped_source_is_refused_not_dropped(self):
        for key in ("__pycache__/orphan.cpython-311.pyc", "loose.pyc", "legacy.pyo",
                    "__pycache__/lib.weird-name", "__pycache__/lib.cpython-311.pyc.bak"):
            with self.subTest(key=key), self.assertRaisesRegex(LocalCaptureRefusal, "bytecode"):
                build_local_capture_zip(ADDON, self.files(**{key: b"c"}))

    def test_bytecode_whose_source_is_in_another_directory_is_refused(self):
        with self.assertRaises(LocalCaptureRefusal):
            build_local_capture_zip(ADDON, self.files(**{"sub/__pycache__/lib.cpython-311.pyc": b"c"}))

    def test_private_and_local_state_content_is_refused(self):
        for key in ("settings.xml", "addon_data/x.xml", "userdata/x", ".git/config", "data/store.db",
                    "cache.sqlite3", "id_rsa", "client.key", "credentials.json", "resources/api_key.txt",
                    "auth/Password.dat", "cookies.json", ".env"):
            with self.subTest(key=key), self.assertRaisesRegex(LocalCaptureRefusal, "private"):
                build_local_capture_zip(ADDON, self.files(**{key: b"v"}))

    def test_shipped_settings_definition_is_ordinary_content(self):
        names, _ = self.names(self.files(**{"resources/settings.xml": b"<settings/>", "tokenizer.py": b"x"}))
        self.assertIn("resources/settings.xml", names)
        self.assertIn("tokenizer.py", names)

    def test_native_content_is_refused(self):
        for key, data in (("lib/x.so", b"x"), ("x.dll", b"x"), ("x.dylib", b"x"), ("tool", b"\x7fELF\x02"),
                          ("tool2", b"\xcf\xfa\xed\xfe..."), ("w.bin", b"MZ" + b"\0" * 58 + b"\x40\0\0\0" + b"PE\0\0")):
            with self.subTest(key=key), self.assertRaisesRegex(LocalCaptureRefusal, "platform-specific"):
                build_local_capture_zip(ADDON, self.files(**{key: data}))

    def test_platform_declarations_are_checked(self):
        def xml(extension):
            return (f'<addon id="{ADDON}" version="{VERSION}" name="n">{extension}</addon>').encode()
        accepted = (
            '<extension point="xbmc.python.module" library="lib.py"/>',
            '<extension point="xbmc.addon.metadata"><platform>all</platform></extension>',
            '<extension point="xbmc.addon.metadata"><summary>x</summary></extension>',
        )
        for extension in accepted:
            with self.subTest(extension=extension):
                build_local_capture_zip(ADDON, {("addon.xml",): xml(extension), ("lib.py",): b"x"})
        refused = (
            '<extension point="xbmc.addon.metadata"><platform>windows</platform></extension>',
            '<extension point="xbmc.addon.metadata"><platform>osx linux</platform></extension>',
            '<extension point="kodi.pvrclient" library_linux="x.so"/>',
        )
        for extension in refused:
            with self.subTest(extension=extension), self.assertRaises(LocalCaptureRefusal):
                build_local_capture_zip(ADDON, {("addon.xml",): xml(extension), ("lib.py",): b"x"})

    def test_missing_or_malformed_addon_xml_is_refused(self):
        with self.assertRaises(LocalCaptureRefusal):
            build_local_capture_zip(ADDON, {("lib.py",): b"x"})
        with self.assertRaises(LocalCaptureRefusal):
            build_local_capture_zip(ADDON, {("addon.xml",): b"<addon"})

    def test_size_limit(self):
        with mock.patch("resources.lib.local_capture.LOCAL_CAPTURE_MAX_BYTES", 8):
            with self.assertRaisesRegex(LocalCaptureRefusal, "size limit"):
                build_local_capture_zip(ADDON, self.files())

    def test_zip_is_deterministic_and_has_safe_names_only(self):
        first, _ = build_local_capture_zip(ADDON, self.files(**{"b/z.py": b"1", "a/y.py": b"2"}))
        second, _ = build_local_capture_zip(ADDON, dict(reversed(list(self.files(**{"b/z.py": b"1", "a/y.py": b"2"}).items()))))
        self.assertEqual(first, second)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            for info in archive.infolist():
                self.assertTrue(info.filename.startswith(ADDON + "/"))
                self.assertEqual((1980, 1, 1, 0, 0, 0), info.date_time)
                self.assertNotIn("..", info.filename.split("/"))


class PrivateDataStaysOutOfTheSoftwareZipTests(LocalCaptureFixture):
    def test_private_state_inside_the_install_is_refused_whole(self):
        (self.home / ADDON / "settings.xml").write_bytes(b"<settings><setting id='token'>SECRET-VALUE</setting></settings>")
        result = self.acquire_local()
        self.refused_without_registration(result, "private")
        self.assertNotIn("SECRET-VALUE", result.error)

    def test_userdata_directories_are_never_read(self):
        userdata = self.base / "userdata" / "addon_data" / ADDON
        userdata.mkdir(parents=True)
        (userdata / "settings.xml").write_bytes(b"SECRET-VALUE")
        stored = self.store.read_bytes(self.acquire_local().metadata.sha256)
        self.assertNotIn(b"SECRET-VALUE", stored)


class ThreeMissingOriginalsTests(unittest.TestCase):
    """TMDb Helper 6.17.9 and two dependencies: absent from the Omega index, installed locally."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "home" / "addons"
        self.application = self.base / "app" / "addons"
        self.home.mkdir(parents=True)
        self.application.mkdir(parents=True)
        self.store = ArtifactStore(self.base / "store")
        self.mirror = FakeMirror()
        from tests.test_official_repository_artifacts import _config_xml
        (self.application / "repository.xbmc.org").mkdir()
        (self.application / "repository.xbmc.org" / "addon.xml").write_bytes(_config_xml())
        self.mirror.publish(archive=b"x", index_xml=OTHER_INDEX)
        imports = "".join(f'<import addon="{d}" version="{v}"/>' for d, v in TMDB_DEPENDENCIES)
        self.entries = []
        for (addon_id, version), requires in (
            (TMDB, imports), (TMDB_DEPENDENCIES[0], ""), (TMDB_DEPENDENCIES[1], ""),
        ):
            directory = self.home / addon_id
            directory.mkdir()
            xml = (f'<addon id="{addon_id}" name="{addon_id}" version="{version}">'
                   f'<requires>{requires}</requires><extension point="xbmc.python.script" library="main.py"/></addon>')
            (directory / "addon.xml").write_text(xml)
            (directory / "main.py").write_text("print('x')\n")
            (directory / "__pycache__").mkdir()
            (directory / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"\0cache")
            self.entries.append({"addonid": addon_id, "version": version, "enabled": True, "installed": True,
                                 "broken": False, "type": "xbmc.python.script",
                                 "path": f"special://home/addons/{addon_id}/", "dependencies": []})

    def backend(self):
        def rpc(method, params):
            if method == "Addons.GetAddons":
                return {"addons": [dict(e) for e in self.entries]}
            if method == "Application.GetProperties":
                return {"version": {"major": 21, "minor": 3}}
            raise AssertionError(method)
        return frozen.KodiInventoryBackend(
            rpc, addons_dir=self.home, package_cache_dir=self.base / "packages",
            application_addons_dir=self.application,
            https_connect=self.mirror.connect, https_resolve=self.mirror.resolve)

    def capture(self, allowed=()):
        return capture_frozen_build(
            backend=self.backend(), store=self.store, root_addon_ids=[TMDB[0]], build_id="b", name="n",
            created_at="2026-11-16T00:00:00Z", kodi_version="21.3", platform="macos",
            local_capture_approvals=allowed)

    def test_without_authorisation_all_three_are_offered_and_nothing_is_stored(self):
        result = self.capture()
        self.assertFalse(result.complete)
        self.assertEqual(sorted((TMDB,) + TMDB_DEPENDENCIES), list(result.local_capture_candidates))
        self.assertEqual([], list((self.base / "store" / "artifacts").iterdir()))

    def test_with_per_add_on_authorisation_all_three_are_captured_locally(self):
        result = self.capture(allowed=(TMDB,) + TMDB_DEPENDENCIES)
        self.assertTrue(result.complete, result.errors)
        sources = {n.addon_id: n.artifact.source for n in result.manifest.addons}
        self.assertEqual({LOCAL_CAPTURE_SOURCE}, set(sources.values()))
        self.assertEqual(3, len(sources))
        for node in result.manifest.addons:
            data = self.store.read_bytes(node.artifact.sha256)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual({f"{node.addon_id}/addon.xml", f"{node.addon_id}/main.py"}, set(archive.namelist()))
        self.assertEqual((), result.local_capture_candidates)

    def test_partial_authorisation_leaves_the_build_incomplete(self):
        result = self.capture(allowed=[TMDB])
        self.assertFalse(result.complete)
        self.assertEqual(sorted(TMDB_DEPENDENCIES), list(result.local_capture_candidates))


class LocalBackend(InMemoryInventoryBackend):
    """Create fixtures: the root add-on's original is demonstrably unavailable."""

    ROOT = "plugin.demo"

    def get_repository_artifact(self, addon_id, version):
        if addon_id == self.ROOT:
            raise RepositoryArtifactUnlisted("exact version is not listed in the official index")
        return None

    def capture_installed_artifact(self, addon_id, version):
        data, _ = build_local_capture_zip(addon_id, {("addon.xml",): frozen_xml(addon_id, version), ("main.py",): b"x = 1\n"})
        return f"{addon_id}-{version}.zip", data


class CreateIntegrationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_create_workflow import WorkflowTests
        # Reuse the accepted Create fixture, then swap in a backend whose root original is absent.
        base = WorkflowTests("test_all_eligible_selected_and_private_on")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        rows = list(base.inventory.addons)
        xml = dict(base.inventory.addon_xml)
        cache = {(a, "1.0.0"): ((a + ".zip", frozen_zip(a)),) for a in ("script.module.demo", "skin.demo")}
        base.inventory = LocalBackend(rows, xml, package_cache=cache)
        base.engine = CreateBuildCaptureEngine(
            inventory=base.inventory, artifact_store=base.artifacts, configuration=base.config,
            inspect_state=lambda: base.state)
        base.factory.return_value = base.engine
        base.workflow = CreateBuildWorkflow(
            inventory=base.inventory, inspect_state=lambda: base.state, library=base.library,
            engine_factory=base.factory, private_store_factory=base.private_factory,
            catalog=base.workflow.catalog, clock=base.clock)
        base.session = base.workflow.open("Current device")
        base.session.name = "My Build"
        base.session.include_private = False

    def test_without_consent_nothing_is_saved_and_nothing_is_captured_locally(self):
        terminal = self.base.workflow.execute(self.base.workflow.preview(self.base.session))
        self.assertIsNone(self.base.workflow.confirm_local_capture)
        self.assertEqual(32730, terminal.string_id)
        self.assertEqual([], list(self.base.entries()))

    def test_declined_consent_saves_nothing(self):
        asked = []
        self.base.workflow.confirm_local_capture = lambda c: asked.append(c) or ()
        terminal = self.base.workflow.execute(self.base.workflow.preview(self.base.session))
        self.assertEqual([(("plugin.demo", "1.0.0"),)], asked)
        self.assertEqual(32730, terminal.string_id)
        self.assertEqual([], list(self.base.entries()))

    def test_approval_saves_the_build_and_discloses_the_local_copy(self):
        self.base.workflow.confirm_local_capture = lambda c: tuple(c)
        terminal = self.base.workflow.execute(self.base.workflow.preview(self.base.session))
        self.assertEqual(32736, terminal.string_id)
        self.assertEqual(1, terminal.local_copy_count)
        self.assertEqual(1, len(self.base.entries()))
        stored = self.base.artifacts.find("plugin.demo", "1.0.0")
        self.assertEqual(LOCAL_CAPTURE_SOURCE, stored.source)

    def test_approval_for_an_unoffered_add_on_is_rejected(self):
        self.base.workflow.confirm_local_capture = lambda c: (("script.module.demo", "1.0.0"),)
        terminal = self.base.workflow.execute(self.base.workflow.preview(self.base.session))
        self.assertEqual(32730, terminal.string_id)

    def test_ui_asks_once_per_add_on_and_returns_only_approved_pairs(self):
        from resources.lib.ui.native_dialogs import NativeDialogs
        from tests.test_create_workflow import CreateAddon

        class Strings(CreateAddon):
            def getLocalizedString(self, identifier):
                return "ask %s %s" if identifier == 32749 else super().getLocalizedString(identifier)

        answers = iter([True, False])
        dialogs = SimpleNamespace(confirmation=mock.Mock(side_effect=lambda *a, **k: next(answers)))
        ui = NativeDialogs(Strings(), mock.Mock(), lambda ms: None, create_dialogs=dialogs)
        approved = ui.confirm_local_capture((("a.one", "1.0"), ("b.two", "2.0")))
        self.assertEqual((("a.one", "1.0"),), approved)
        self.assertEqual(2, dialogs.confirmation.call_count)
        self.assertEqual(32750, dialogs.confirmation.call_args.kwargs["affirmative_id"])


if __name__ == "__main__":
    unittest.main()
