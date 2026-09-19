import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.chatgpt_local import core


class ChatGPTLocalBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # macOS exposes /var as a symlink to /private/var. Canonicalize the
        # temporary root so path-policy assertions compare like with like.
        self.root = Path(self.temp.name).resolve()
        (self.root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "sample.py").write_text("alpha\nbeta\nAlpha again\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"CHATGPT_LOCAL_WORKSPACE": str(self.root)}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_resolve_path_accepts_workspace_file(self):
        self.assertEqual(core.resolve_path("src/sample.py"), self.root / "src" / "sample.py")

    def test_resolve_path_rejects_escape_and_absolute(self):
        with self.assertRaises(core.BridgeError):
            core.resolve_path("../outside")
        with self.assertRaises(core.BridgeError):
            core.resolve_path("/tmp/outside")

    def test_direct_git_access_is_blocked(self):
        with self.assertRaises(core.BridgeError):
            core.resolve_path(".git/config")

    def test_secret_like_files_are_blocked(self):
        (self.root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
        with self.assertRaises(core.BridgeError):
            core.read_text_file(".env")

    def test_read_file_returns_hash_and_line_range(self):
        result = core.read_text_file("src/sample.py", 2, 3)
        self.assertEqual(result["content"], "beta\nAlpha again\n")
        expected = hashlib.sha256((self.root / "src" / "sample.py").read_bytes()).hexdigest()
        self.assertEqual(result["sha256"], expected)

    def test_search_text_is_case_insensitive_by_default(self):
        result = core.search_text("alpha", "src")
        self.assertEqual([x["line"] for x in result["results"]], [1, 3])

    def test_replacing_file_requires_matching_hash(self):
        path = self.root / "src" / "sample.py"
        current = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(core.BridgeError):
            core.write_text_file("src/sample.py", "new\n")
        with self.assertRaises(core.BridgeError):
            core.write_text_file("src/sample.py", "new\n", expected_sha256="bad")
        result = core.write_text_file("src/sample.py", "new\n", expected_sha256=current)
        self.assertEqual(path.read_text(encoding="utf-8"), "new\n")
        self.assertEqual(result["size"], 4)

    def test_new_file_can_create_parent_when_explicit(self):
        core.write_text_file("new/sub/file.txt", "ok\n", create_parents=True)
        self.assertEqual((self.root / "new" / "sub" / "file.txt").read_text(), "ok\n")

    def test_patch_paths_reject_deletion_and_escape(self):
        deletion = "--- a/src/sample.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-alpha\n"
        with self.assertRaises(core.BridgeError):
            core._patch_paths(deletion)
        escape = "--- /dev/null\n+++ b/../escape.txt\n@@ -0,0 +1 @@\n+x\n"
        with self.assertRaises(core.BridgeError):
            core._patch_paths(escape)

    def test_patch_paths_allow_creation(self):
        patch = "--- /dev/null\n+++ b/src/new.py\n@@ -0,0 +1 @@\n+print('ok')\n"
        self.assertEqual(core._patch_paths(patch), ["src/new.py"])

    def test_kodi_command_allowlist(self):
        self.assertIn("validate-config", core.KODI_COMMANDS)
        with self.assertRaises(core.BridgeError):
            core.run_kodi_harness("touch-real-profile")


if __name__ == "__main__":
    unittest.main()
