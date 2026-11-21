"""Exact release and adapter evidence projected onto a disposable add-ons tree."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from tests import test_bm_test_app as support
from tools import bm_test_app as host

CANDIDATE = host.PROJECT / ".qualification-evidence/af3-zip-binding-20261121/adapter-candidate.zip"
CANDIDATE_SHA = "76ce64952561dd79df53f76c0efae28a28ad9074b1254e00852f99b0954acceb"
RPC = {"host": "127.0.0.1", "port": 8080, "username": "kodi"}


class ExactZipBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(path.is_file() for path in (CANDIDATE, host._AF3_ZIP_PATH, host._AF3_ZIP_STAGE)):
            raise unittest.SkipTest("sealed AF3 release and private adapter candidate required")
        cls.stage = json.loads(host._AF3_ZIP_STAGE.read_bytes())
        release = host._AF3_ZIP_PATH.read_bytes()
        candidate = CANDIDATE.read_bytes()
        assert host.sha256_hex(release) == host._AF3_ZIP_SHA
        assert host.sha256_hex(candidate) == CANDIDATE_SHA
        cls.archives = (release, candidate)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        self.target = support.make_fake_app(Path(temporary.name))
        self.services = support.make_services(self.target)
        self.product = self.target.addon_dir(host.BUILD_MANAGER_ID)
        self.driver = self.target.addon_dir(host.DRIVER_ID)
        for raw in self.archives:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for member in archive.infolist():
                    path = self.target.addons_dir / member.filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(archive.read(member))
        self.source, self.config = self.load()

    def load(self, *, prepare=False):
        return host.load_af3_zip_source(self.services, host.PROJECT, prepare=prepare)

    def test_exact_release_and_candidate_verify(self):
        self.assertTrue(self.source.verify(self.services)["installed_equals_manifest"])
        self.assertEqual(self.source.receipt()["adapter_tree_sha256"],
                         "61772ae0f3838e258f0e1bc7fc8a4df90e5810e7e8770e0a78e271034bc12db6")
        binding = host._parse_adapter_config(self.config)["PLATFORM_SOURCE_BINDING"]
        parsed, _ = host._adapter._platform_sources(binding, self.product, self.driver)
        self.assertEqual(len(parsed["product"]), 88)
        self.assertEqual(parsed["manifest_sha256"], host._adapter._AF3_MANIFEST_SHA)
        self.assertNotIn("platform_check", self.source.receipt())
        code, receipt, _ = support.run_cli(self.services, "af3-verify-zip")
        self.assertEqual(code, host.EXIT_OK)
        self.assertEqual(receipt["identity"]["process"]["state"], "not_running")
        self.assertEqual(receipt["native_health"], "unverified")
        self.assertEqual(self.services.transport.requests, [])

    def test_modified_adapter_or_config_refuses(self):
        addon = self.driver / "addon.xml"
        original = addon.read_bytes()
        addon.write_bytes(original + b"\n")
        with self.assertRaisesRegex(host.HelperError, "installed_tree_mismatch"):
            self.load()
        addon.write_bytes(original)
        config = self.driver / "adapter_config.py"
        config.write_bytes(b"\n" + self.config)
        with self.assertRaisesRegex(host.HelperError, "driver_config_mismatch"):
            self.load()

    def test_changed_missing_and_added_product_are_refused(self):
        descriptor = self.product / "addon.xml"
        original = descriptor.read_bytes()
        cases = (
            ("changed descriptor", lambda: descriptor.write_bytes(original + b"\n")),
            ("missing member", descriptor.unlink),
            ("unexpected member", lambda: (self.product / "unknown.py").write_bytes(b"pass\n")),
        )
        for label, edit in cases:
            with self.subTest(case=label):
                edit()
                with self.assertRaisesRegex(host.HelperError, "installed_tree_mismatch"):
                    self.source.verify(self.services)
                descriptor.write_bytes(original)
        (self.product / "unknown.py").unlink()
        member = self.product / "service.py"
        member.write_bytes((self.product / "default.py").read_bytes())
        with self.assertRaisesRegex(host.HelperError, "installed_tree_mismatch"):
            self.source.verify(self.services)

    def test_git_projection_passes_only_with_git_bound_adapter(self):
        self.assertFalse(host.verify_installed(self.services, self.stage, git_repo=host.PROJECT)
                         ["installed_equals_candidate"])
        original_product = {e["path"]: e for e in self.stage["build_manager"]["files"]}
        git = host.GitSource(host.PROJECT, self.services.git_exe, self.services.git_runner)
        identity = git.resolve_commit(self.stage["candidate"]["commit"])
        for name in ("addon.xml", host._AF3_ZIP_EXCLUDED):
            blob = original_product[name]["git_blob"]
            path = self.product / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(git.read_blobs(identity, [blob])[blob])
        # Reconstruct the original generated bytes and prove them against the sealed stage.
        new_binding = host._parse_adapter_config(self.config)["PLATFORM_SOURCE_BINDING"]
        old_binding = host._adapter.platform_source_binding(
            {name: row["sha256"] for name, row in original_product.items()},
            json.loads(new_binding)["adapter"], host._AF3_ZIP_COMMIT, host._adapter._AF3_MANIFEST_SHA)
        (self.driver / "adapter_config.py").write_bytes(
            self.config.replace(repr(new_binding).encode("ascii"), repr(old_binding).encode("ascii")))
        legacy = host.verify_installed(self.services, self.stage, git_repo=host.PROJECT)
        self.assertTrue(legacy["installed_equals_candidate"])
        with self.assertRaisesRegex(host.HelperError, "driver_config_mismatch"):
            self.load()
        first, _ = self.load(prepare=True)
        self.assertEqual(first.receipt(), self.source.receipt())
        output = self.target.root.parent / "regenerated-adapter.zip"
        receipt = host.prepare_af3_zip(self.services, host.PROJECT, output)
        self.assertEqual(receipt["native_health"], "unverified")
        self.assertEqual(receipt["adapter_zip_sha256"], CANDIDATE_SHA)
        self.assertEqual(output.read_bytes(), self.archives[1])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(host.HelperError, "output_exists"):
            host.prepare_af3_zip(self.services, host.PROJECT, output)

    def test_modified_archive_refuses_before_installed_source(self):
        altered = self.target.root.parent / "altered.zip"
        altered.write_bytes(self.archives[0] + b"extra")
        with patch.object(host, "_AF3_ZIP_PATH", altered):
            with self.assertRaisesRegex(host.HelperError, "af3_health_refused"):
                self.load()

    def test_wrong_route_and_changed_pid_refuse_before_rpc(self):
        options = dict(mode="platform_check", manifest=self.source.manifest,
                       manifest_sha256=self.source.manifest_sha256, rpc=RPC, timeout=1)
        with self.assertRaisesRegex(host.HelperError, "argument_invalid"):
            host.run_adapter(self.services, git_repo=None, **options)
        with self.assertRaisesRegex(host.HelperError, "argument_invalid"):
            host.run_adapter(self.services, git_repo=host.PROJECT, _zip_source=self.source,
                             _expected_pid=9, require_authenticated=True, **options)
        with patch.object(host, "identify", return_value=SimpleNamespace(pid=10)):
            with self.assertRaisesRegex(host.HelperError, "listener_pid_mismatch"):
                host.run_adapter(self.services, git_repo=None, _zip_source=self.source,
                                 _expected_pid=9, require_authenticated=True, **options)
        self.assertEqual(self.services.transport.requests, [])
