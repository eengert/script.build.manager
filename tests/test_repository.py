"""
Unit tests for resources/lib/repository.py (BM-010).

All tests run without Kodi — no xbmc/xbmcvfs imports required.
Tests cover DETECTION, IDEMPOTENCY, DOWNLOAD, ZIP VALIDATION, INSTALL,
RESULT, and SECURITY categories from the BM-010 spec.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, List, Optional
from unittest.mock import MagicMock, patch

from resources.lib.manifest import Repository
from resources.lib.repository import (
    KodiRuntimeRepositoryBackend,
    RepositoryBackend,
    RepositoryError,
    RepositoryInstallError,
    RepositoryInstallResult,
    RepositoryManager,
    RepositoryStatus,
    RepositoryValidationError,
    _MAX_ARTIFACT_BYTES,
    _SafeRedirectHandler,
    _build_safe_opener,
    _download_artifact,
    _extract_zip_to_directory,
    _find_addon_xml,
    _validate_url_policy,
    _validate_zip_entries,
    validate_repository_zip,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_addon_xml(addon_id: str, has_repo_ext: bool = True) -> bytes:
    """Minimal addon.xml for a repository add-on."""
    ext = (
        '<extension point="xbmc.addon.repository" name="Test Repo"/>'
        if has_repo_ext
        else '<extension point="xbmc.addon.metadata"/>'
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<addon id="{addon_id}" name="Test" version="1.0.0" provider-name="Test">'
        f'{ext}'
        f'</addon>'
    ).encode("utf-8")


def _make_zip(
    files: dict,
) -> bytes:
    """Build a ZIP in memory from a dict of {name: bytes}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _make_repo_zip(
    addon_id: str,
    *,
    prefixed: bool = True,
    has_repo_ext: bool = True,
) -> bytes:
    """Build a valid repository ZIP (prefixed or flat)."""
    xml = _make_addon_xml(addon_id, has_repo_ext=has_repo_ext)
    if prefixed:
        return _make_zip({f"{addon_id}/addon.xml": xml})
    else:
        return _make_zip({"addon.xml": xml})


class FakeRepositoryBackend(RepositoryBackend):
    """Configurable fake backend for unit tests."""

    def __init__(
        self,
        installed: Optional[FrozenSet[str]] = None,
        download_data: Optional[bytes] = None,
        download_error: Optional[Exception] = None,
        install_error: Optional[Exception] = None,
        scan_error: Optional[Exception] = None,
        poll_result: bool = True,
        poll_error: Optional[Exception] = None,
        installed_after_install: Optional[FrozenSet[str]] = None,
    ):
        self._installed = frozenset(installed or set())
        self._download_data = download_data
        self._download_error = download_error
        self._install_error = install_error
        self._scan_error = scan_error
        self._poll_result = poll_result
        self._poll_error = poll_error
        self._installed_after_install = installed_after_install
        self.install_calls: List[str] = []
        self.scan_calls: int = 0
        self.poll_calls: List[str] = []

    def get_installed_addon_ids(self) -> FrozenSet[str]:
        return self._installed

    def download_artifact(self, url: str, *, max_bytes=_MAX_ARTIFACT_BYTES, timeout=30.0) -> bytes:
        if self._download_error:
            raise self._download_error
        return self._download_data or b""

    def install_zip_to_addons(self, addon_id: str, zip_bytes: bytes) -> None:
        if self._install_error:
            raise self._install_error
        self.install_calls.append(addon_id)
        if self._installed_after_install is not None:
            self._installed = self._installed_after_install

    def trigger_addon_scan(self) -> None:
        if self._scan_error:
            raise self._scan_error
        self.scan_calls += 1

    def poll_addon_installed(self, addon_id: str, *, timeout=60.0, interval=1.0) -> bool:
        self.poll_calls.append(addon_id)
        if self._poll_error:
            raise self._poll_error
        return self._poll_result


# ---------------------------------------------------------------------------
# DETECTION — RepositoryManager.is_installed
# ---------------------------------------------------------------------------

class TestDetection(unittest.TestCase):

    def test_returns_true_when_installed(self):
        backend = FakeRepositoryBackend(installed={"repo.test"})
        mgr = RepositoryManager(backend)
        self.assertTrue(mgr.is_installed("repo.test"))

    def test_returns_false_when_not_installed(self):
        backend = FakeRepositoryBackend(installed={"other.addon"})
        mgr = RepositoryManager(backend)
        self.assertFalse(mgr.is_installed("repo.test"))

    def test_returns_false_when_empty_installed_set(self):
        backend = FakeRepositoryBackend(installed=frozenset())
        mgr = RepositoryManager(backend)
        self.assertFalse(mgr.is_installed("repo.test"))

    def test_exact_string_match(self):
        backend = FakeRepositoryBackend(installed={"repository.test"})
        mgr = RepositoryManager(backend)
        self.assertFalse(mgr.is_installed("repo.test"))
        self.assertTrue(mgr.is_installed("repository.test"))


# ---------------------------------------------------------------------------
# IDEMPOTENCY — ALREADY_INSTALLED short-circuit, no mutation
# ---------------------------------------------------------------------------

class TestIdempotency(unittest.TestCase):

    def _repo(self, addon_id="repo.test", url="https://example.com/repo.zip"):
        return Repository(addon_id=addon_id, bootstrap_url=url)

    def test_already_installed_returns_correct_status(self):
        repo = self._repo("repo.test")
        backend = FakeRepositoryBackend(installed={"repo.test"})
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.ALREADY_INSTALLED)

    def test_already_installed_no_download(self):
        repo = self._repo("repo.test")
        backend = FakeRepositoryBackend(installed={"repo.test"})
        mgr = RepositoryManager(backend)
        mgr.install(repo)
        self.assertEqual(len(backend.install_calls), 0)

    def test_already_installed_no_scan(self):
        repo = self._repo("repo.test")
        backend = FakeRepositoryBackend(installed={"repo.test"})
        mgr = RepositoryManager(backend)
        mgr.install(repo)
        self.assertEqual(backend.scan_calls, 0)

    def test_already_installed_result_has_addon_id(self):
        repo = self._repo("repo.test")
        backend = FakeRepositoryBackend(installed={"repo.test"})
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.addon_id, "repo.test")

    def test_second_call_also_returns_already_installed(self):
        """After install succeeds, calling again is idempotent."""
        addon_id = "repository.build-manager-test"
        zip_bytes = _make_repo_zip(addon_id)
        backend = FakeRepositoryBackend(
            installed=frozenset(),
            download_data=zip_bytes,
            poll_result=True,
            installed_after_install=frozenset({addon_id}),
        )
        mgr = RepositoryManager(backend)
        repo = Repository(addon_id=addon_id, bootstrap_url="https://example.com/r.zip")
        result1 = mgr.install(repo)
        self.assertEqual(result1.status, RepositoryStatus.INSTALLED)
        result2 = mgr.install(repo)
        self.assertEqual(result2.status, RepositoryStatus.ALREADY_INSTALLED)


# ---------------------------------------------------------------------------
# URL validation — _validate_url_policy
# ---------------------------------------------------------------------------

class TestUrlValidation(unittest.TestCase):

    def test_https_allowed(self):
        _validate_url_policy("https://example.com/repo.zip")

    def test_http_allowed(self):
        _validate_url_policy("http://example.com/repo.zip")

    def test_file_scheme_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("file:///etc/passwd")

    def test_ftp_scheme_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("ftp://example.com/repo.zip")

    def test_no_scheme_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("example.com/repo.zip")

    def test_empty_host_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("https:///path/to/file.zip")

    def test_credentials_in_url_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("https://user:pass@example.com/repo.zip")

    def test_username_only_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("https://user@example.com/repo.zip")

    def test_context_string_in_error_message(self):
        with self.assertRaises(RepositoryValidationError) as ctx:
            _validate_url_policy("file:///etc/passwd", context="bootstrap_url")
        self.assertIn("bootstrap_url", str(ctx.exception))


# ---------------------------------------------------------------------------
# Redirect safety — _SafeRedirectHandler
# ---------------------------------------------------------------------------

class TestSafeRedirectHandler(unittest.TestCase):

    def _make_redirect_env(self, newurl):
        """Build the arguments redirect_request receives."""
        req = urllib.request.Request("https://example.com/original")
        fp = None
        code = 302
        msg = "Found"
        headers = {}
        return req, fp, code, msg, headers, newurl

    def test_https_redirect_allowed(self):
        handler = _SafeRedirectHandler()
        handler.parent = MagicMock()
        # Should not raise
        args = self._make_redirect_env("https://example.com/other")
        handler.redirect_request(*args)

    def test_http_redirect_allowed(self):
        handler = _SafeRedirectHandler()
        handler.parent = MagicMock()
        args = self._make_redirect_env("http://example.com/other")
        handler.redirect_request(*args)

    def test_file_redirect_rejected(self):
        handler = _SafeRedirectHandler()
        args = self._make_redirect_env("file:///etc/passwd")
        with self.assertRaises(RepositoryInstallError):
            handler.redirect_request(*args)

    def test_ftp_redirect_rejected(self):
        handler = _SafeRedirectHandler()
        args = self._make_redirect_env("ftp://example.com/file")
        with self.assertRaises(RepositoryInstallError):
            handler.redirect_request(*args)

    def test_redirect_with_credentials_rejected(self):
        handler = _SafeRedirectHandler()
        args = self._make_redirect_env("https://user:pass@example.com/file")
        with self.assertRaises(RepositoryInstallError):
            handler.redirect_request(*args)

    def test_safe_opener_has_no_file_handler(self):
        opener = _build_safe_opener()
        for handler in opener.handlers:
            self.assertNotIsInstance(handler, urllib.request.FileHandler)


# ---------------------------------------------------------------------------
# DOWNLOAD — _download_artifact
# ---------------------------------------------------------------------------

class TestDownloadArtifact(unittest.TestCase):

    def _mock_response(self, data: bytes):
        response = MagicMock()
        chunks = [data[i:i+65536] for i in range(0, len(data), 65536)] + [b""]
        response.read.side_effect = chunks
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)
        return response

    def test_scheme_validation_before_download(self):
        with self.assertRaises(RepositoryValidationError):
            _download_artifact("file:///etc/passwd")

    def test_empty_response_raises_install_error(self):
        resp = self._mock_response(b"")
        with patch("resources.lib.repository._build_safe_opener") as mock_opener_fn:
            opener = MagicMock()
            opener.open.return_value = resp
            mock_opener_fn.return_value = opener
            with self.assertRaises(RepositoryInstallError):
                _download_artifact("https://example.com/repo.zip")

    def test_oversized_response_raises_install_error(self):
        chunk = b"x" * (65536 + 1)
        large_data = chunk * 900  # ~58 MB > 50 MB limit
        resp = self._mock_response(large_data)
        with patch("resources.lib.repository._build_safe_opener") as mock_opener_fn:
            opener = MagicMock()
            opener.open.return_value = resp
            mock_opener_fn.return_value = opener
            with self.assertRaises(RepositoryInstallError) as ctx:
                _download_artifact("https://example.com/repo.zip")
        self.assertIn("maximum size", str(ctx.exception))

    def test_network_error_raises_install_error(self):
        with patch("resources.lib.repository._build_safe_opener") as mock_opener_fn:
            opener = MagicMock()
            opener.open.side_effect = urllib.error.URLError("Connection refused")
            mock_opener_fn.return_value = opener
            with self.assertRaises(RepositoryInstallError) as ctx:
                _download_artifact("https://example.com/repo.zip")
        self.assertIn("Download failed", str(ctx.exception))

    def test_small_payload_returned_correctly(self):
        payload = b"x" * 100
        resp = self._mock_response(payload)
        with patch("resources.lib.repository._build_safe_opener") as mock_opener_fn:
            opener = MagicMock()
            opener.open.return_value = resp
            mock_opener_fn.return_value = opener
            result = _download_artifact("https://example.com/repo.zip")
        self.assertEqual(result, payload)

    def test_credentials_in_url_rejected_before_download(self):
        with self.assertRaises(RepositoryValidationError):
            _download_artifact("https://user:pass@example.com/repo.zip")


# ---------------------------------------------------------------------------
# ZIP entry validation — _validate_zip_entries / _find_addon_xml
# ---------------------------------------------------------------------------

class TestZipEntryValidation(unittest.TestCase):

    def test_normal_entries_accepted(self):
        _validate_zip_entries(["addon.xml", "icon.png", "resources/strings.po"])

    def test_absolute_unix_path_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_zip_entries(["/etc/passwd"])

    def test_parent_traversal_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_zip_entries(["../../../etc/shadow"])

    def test_traversal_inside_path_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_zip_entries(["addon/../../../etc/shadow"])

    def test_null_byte_in_name_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_zip_entries(["addon\x00.xml"])

    def test_backslash_traversal_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_zip_entries(["..\\..\\windows\\system32\\bad.dll"])

    def test_directory_entries_accepted(self):
        _validate_zip_entries(["addon/", "addon/resources/"])

    def test_find_addon_xml_at_root(self):
        names = ["addon.xml", "icon.png"]
        self.assertEqual(_find_addon_xml(names), "addon.xml")

    def test_find_addon_xml_prefixed(self):
        names = ["repository.test/addon.xml", "repository.test/icon.png"]
        self.assertEqual(_find_addon_xml(names), "repository.test/addon.xml")

    def test_find_addon_xml_missing(self):
        names = ["icon.png", "resources/data.json"]
        self.assertIsNone(_find_addon_xml(names))

    def test_find_addon_xml_ignores_depth_3(self):
        names = ["a/b/addon.xml"]
        self.assertIsNone(_find_addon_xml(names))


# ---------------------------------------------------------------------------
# ZIP validation — validate_repository_zip
# ---------------------------------------------------------------------------

class TestValidateRepositoryZip(unittest.TestCase):

    def test_valid_prefixed_zip_passes(self):
        zip_bytes = _make_repo_zip("repository.test")
        validate_repository_zip(zip_bytes, "repository.test")

    def test_valid_flat_zip_passes(self):
        zip_bytes = _make_repo_zip("repository.test", prefixed=False)
        validate_repository_zip(zip_bytes, "repository.test")

    def test_empty_bytes_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            validate_repository_zip(b"", "repository.test")

    def test_not_a_zip_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            validate_repository_zip(b"this is not a zip file", "repository.test")

    def test_wrong_addon_id_rejected(self):
        zip_bytes = _make_repo_zip("repository.test")
        with self.assertRaises(RepositoryValidationError) as ctx:
            validate_repository_zip(zip_bytes, "repository.other")
        self.assertIn("expected", str(ctx.exception))

    def test_missing_addon_xml_rejected(self):
        zip_bytes = _make_zip({"icon.png": b"data"})
        with self.assertRaises(RepositoryValidationError) as ctx:
            validate_repository_zip(zip_bytes, "repository.test")
        self.assertIn("addon.xml", str(ctx.exception))

    def test_missing_repo_extension_rejected(self):
        zip_bytes = _make_repo_zip("repository.test", has_repo_ext=False)
        with self.assertRaises(RepositoryValidationError) as ctx:
            validate_repository_zip(zip_bytes, "repository.test")
        self.assertIn("xbmc.addon.repository", str(ctx.exception))

    def test_malformed_addon_xml_rejected(self):
        bad_xml = b"<not valid xml"
        zip_bytes = _make_zip({"repository.test/addon.xml": bad_xml})
        with self.assertRaises(RepositoryValidationError) as ctx:
            validate_repository_zip(zip_bytes, "repository.test")
        self.assertIn("valid XML", str(ctx.exception))

    def test_path_traversal_in_zip_rejected(self):
        xml = _make_addon_xml("repository.test")
        zip_bytes = _make_zip({
            "repository.test/addon.xml": xml,
            "../../../evil.sh": b"evil",
        })
        with self.assertRaises(RepositoryValidationError):
            validate_repository_zip(zip_bytes, "repository.test")


# ---------------------------------------------------------------------------
# ZIP extraction — _extract_zip_to_directory
# ---------------------------------------------------------------------------

class TestExtractZipToDirectory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_prefixed_zip_extracts_contents(self):
        addon_id = "repository.test"
        xml = _make_addon_xml(addon_id)
        zip_bytes = _make_zip({f"{addon_id}/addon.xml": xml, f"{addon_id}/icon.png": b"img"})
        target = Path(self.tmpdir) / addon_id
        _extract_zip_to_directory(zip_bytes, addon_id, target)
        self.assertTrue((target / "addon.xml").exists())
        self.assertTrue((target / "icon.png").exists())

    def test_flat_zip_extracts_contents(self):
        addon_id = "repository.test"
        xml = _make_addon_xml(addon_id)
        zip_bytes = _make_zip({"addon.xml": xml, "icon.png": b"img"})
        target = Path(self.tmpdir) / addon_id
        _extract_zip_to_directory(zip_bytes, addon_id, target)
        self.assertTrue((target / "addon.xml").exists())

    def test_does_not_extract_other_prefix(self):
        """ZIP with mixed prefix — only the correct addon_id prefix extracted."""
        addon_id = "repository.test"
        xml = _make_addon_xml(addon_id)
        zip_bytes = _make_zip({
            f"{addon_id}/addon.xml": xml,
            "other.addon/addon.xml": b"<addon/>",
        })
        target = Path(self.tmpdir) / addon_id
        _extract_zip_to_directory(zip_bytes, addon_id, target)
        self.assertTrue((target / "addon.xml").exists())
        # other.addon should not appear under target
        self.assertFalse((target / "other.addon").exists())

    def test_directory_entries_skipped(self):
        addon_id = "repository.test"
        xml = _make_addon_xml(addon_id)
        zip_bytes = _make_zip({f"{addon_id}/": b"", f"{addon_id}/addon.xml": xml})
        target = Path(self.tmpdir) / addon_id
        _extract_zip_to_directory(zip_bytes, addon_id, target)
        self.assertTrue((target / "addon.xml").exists())

    def test_nested_resources_extracted(self):
        addon_id = "repository.test"
        xml = _make_addon_xml(addon_id)
        zip_bytes = _make_zip({
            f"{addon_id}/addon.xml": xml,
            f"{addon_id}/resources/data.xml": b"<data/>",
        })
        target = Path(self.tmpdir) / addon_id
        _extract_zip_to_directory(zip_bytes, addon_id, target)
        self.assertTrue((target / "resources" / "data.xml").exists())


# ---------------------------------------------------------------------------
# INSTALL flow — RepositoryManager.install (happy path)
# ---------------------------------------------------------------------------

class TestInstallHappyPath(unittest.TestCase):

    def _install(
        self, addon_id="repository.test", *, url="https://example.com/repo.zip", prefixed=True
    ):
        zip_bytes = _make_repo_zip(addon_id, prefixed=prefixed)
        backend = FakeRepositoryBackend(
            installed=frozenset(),
            download_data=zip_bytes,
            poll_result=True,
        )
        mgr = RepositoryManager(backend)
        repo = Repository(addon_id=addon_id, bootstrap_url=url)
        return mgr.install(repo), backend

    def test_install_returns_installed_status(self):
        result, _ = self._install()
        self.assertEqual(result.status, RepositoryStatus.INSTALLED)

    def test_install_addon_id_in_result(self):
        result, _ = self._install("repository.test")
        self.assertEqual(result.addon_id, "repository.test")

    def test_install_triggers_scan(self):
        _, backend = self._install()
        self.assertEqual(backend.scan_calls, 1)

    def test_install_calls_install_zip(self):
        _, backend = self._install()
        self.assertEqual(backend.install_calls, ["repository.test"])

    def test_install_calls_poll(self):
        _, backend = self._install()
        self.assertEqual(backend.poll_calls, ["repository.test"])

    def test_install_flat_zip(self):
        result, _ = self._install(prefixed=False)
        self.assertEqual(result.status, RepositoryStatus.INSTALLED)


# ---------------------------------------------------------------------------
# RESULT — error paths return RepositoryStatus.FAILED
# ---------------------------------------------------------------------------

class TestInstallFailurePaths(unittest.TestCase):

    def _repo(self, addon_id="repository.test", url="https://example.com/r.zip"):
        return Repository(addon_id=addon_id, bootstrap_url=url)

    def test_no_bootstrap_url_returns_failed(self):
        repo = Repository(addon_id="repository.test", bootstrap_url="")
        backend = FakeRepositoryBackend(installed=frozenset())
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.FAILED)
        self.assertIn("bootstrap_url", result.message)

    def test_download_error_returns_failed(self):
        repo = self._repo()
        backend = FakeRepositoryBackend(
            installed=frozenset(),
            download_error=RepositoryInstallError("Connection refused"),
        )
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.FAILED)
        self.assertIn("Download failed", result.message)

    def test_invalid_zip_returns_failed(self):
        repo = self._repo()
        backend = FakeRepositoryBackend(installed=frozenset(), download_data=b"not a zip")
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.FAILED)
        self.assertIn("Artifact rejected", result.message)

    def test_wrong_addon_id_in_zip_returns_failed(self):
        repo = self._repo("repository.test")
        zip_bytes = _make_repo_zip("repository.other")
        backend = FakeRepositoryBackend(installed=frozenset(), download_data=zip_bytes)
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.FAILED)

    def test_install_zip_error_returns_failed(self):
        repo = self._repo()
        zip_bytes = _make_repo_zip("repository.test")
        backend = FakeRepositoryBackend(
            installed=frozenset(),
            download_data=zip_bytes,
            install_error=RepositoryInstallError("Filesystem error"),
        )
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.FAILED)
        self.assertIn("Installation failed", result.message)

    def test_scan_error_returns_failed(self):
        repo = self._repo()
        zip_bytes = _make_repo_zip("repository.test")
        backend = FakeRepositoryBackend(
            installed=frozenset(),
            download_data=zip_bytes,
            scan_error=RepositoryInstallError("Kodi not responding"),
        )
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.FAILED)
        self.assertIn("scan failed", result.message)

    def test_poll_returns_false_means_failed(self):
        repo = self._repo()
        zip_bytes = _make_repo_zip("repository.test")
        backend = FakeRepositoryBackend(
            installed=frozenset(),
            download_data=zip_bytes,
            poll_result=False,
        )
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.FAILED)
        self.assertIn("verification timeout", result.message)

    def test_poll_error_returns_failed(self):
        repo = self._repo()
        zip_bytes = _make_repo_zip("repository.test")
        backend = FakeRepositoryBackend(
            installed=frozenset(),
            download_data=zip_bytes,
            poll_error=RepositoryInstallError("Timeout"),
        )
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.status, RepositoryStatus.FAILED)
        self.assertIn("Verification failed", result.message)

    def test_result_is_immutable(self):
        result = RepositoryInstallResult(
            addon_id="repository.test",
            status=RepositoryStatus.INSTALLED,
            message="ok",
        )
        with self.assertRaises((AttributeError, TypeError)):
            result.addon_id = "changed"  # type: ignore[misc]

    def test_failed_result_contains_addon_id(self):
        repo = Repository(addon_id="repository.test", bootstrap_url="")
        backend = FakeRepositoryBackend(installed=frozenset())
        mgr = RepositoryManager(backend)
        result = mgr.install(repo)
        self.assertEqual(result.addon_id, "repository.test")


# ---------------------------------------------------------------------------
# RESULT type correctness
# ---------------------------------------------------------------------------

class TestRepositoryInstallResult(unittest.TestCase):

    def test_status_enum_values(self):
        self.assertEqual(RepositoryStatus.ALREADY_INSTALLED.value, "already_installed")
        self.assertEqual(RepositoryStatus.INSTALLED.value, "installed")
        self.assertEqual(RepositoryStatus.FAILED.value, "failed")

    def test_result_fields_accessible(self):
        r = RepositoryInstallResult(
            addon_id="repo.test",
            status=RepositoryStatus.INSTALLED,
            message="done",
        )
        self.assertEqual(r.addon_id, "repo.test")
        self.assertEqual(r.status, RepositoryStatus.INSTALLED)
        self.assertEqual(r.message, "done")

    def test_result_is_hashable(self):
        r = RepositoryInstallResult("x", RepositoryStatus.FAILED, "msg")
        hash(r)  # frozen dataclass must be hashable


# ---------------------------------------------------------------------------
# SECURITY — further URL/download policy checks
# ---------------------------------------------------------------------------

class TestSecurityPolicy(unittest.TestCase):

    def test_max_artifact_bytes_is_50mb(self):
        self.assertEqual(_MAX_ARTIFACT_BYTES, 50 * 1024 * 1024)

    def test_data_url_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("data:text/html,<h1>hi</h1>")

    def test_javascript_url_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("javascript:alert(1)")

    def test_empty_url_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            _validate_url_policy("")

    def test_validation_error_hierarchy(self):
        self.assertTrue(issubclass(RepositoryValidationError, RepositoryError))

    def test_install_error_hierarchy(self):
        self.assertTrue(issubclass(RepositoryInstallError, RepositoryError))

    def test_backend_abstract_methods_raise(self):
        backend = RepositoryBackend()
        with self.assertRaises(NotImplementedError):
            backend.get_installed_addon_ids()
        with self.assertRaises(NotImplementedError):
            backend.download_artifact("https://x.com/")
        with self.assertRaises(NotImplementedError):
            backend.install_zip_to_addons("x", b"")
        with self.assertRaises(NotImplementedError):
            backend.trigger_addon_scan()
        with self.assertRaises(NotImplementedError):
            backend.poll_addon_installed("x")


# ---------------------------------------------------------------------------
# KodiRuntimeRepositoryBackend — without Kodi (import errors)
# ---------------------------------------------------------------------------

class TestKodiRuntimeBackend(unittest.TestCase):

    def test_raises_install_error_without_xbmc(self):
        backend = KodiRuntimeRepositoryBackend()
        with self.assertRaises(RepositoryInstallError) as ctx:
            backend.get_installed_addon_ids()
        self.assertIn("xbmc", str(ctx.exception).lower())

    def test_trigger_addon_scan_raises_without_xbmc(self):
        backend = KodiRuntimeRepositoryBackend()
        with self.assertRaises(RepositoryInstallError):
            backend.trigger_addon_scan()

    def test_install_zip_raises_without_xbmcvfs(self):
        backend = KodiRuntimeRepositoryBackend()
        with self.assertRaises(RepositoryInstallError):
            backend.install_zip_to_addons("repo.test", b"data")

    def test_download_artifact_works_without_kodi(self):
        """download_artifact must be callable without Kodi (uses stdlib only)."""
        backend = KodiRuntimeRepositoryBackend()
        # Just verify that it dispatches to _download_artifact correctly —
        # a bad URL should raise a policy error, not an ImportError.
        with self.assertRaises(RepositoryValidationError):
            backend.download_artifact("file:///etc/passwd")


# ---------------------------------------------------------------------------
# Backend interface completeness
# ---------------------------------------------------------------------------

class TestBackendInterface(unittest.TestCase):

    def test_fake_backend_satisfies_interface(self):
        """FakeRepositoryBackend implements all RepositoryBackend methods."""
        backend = FakeRepositoryBackend(installed=frozenset(), download_data=b"x")
        addon_ids = backend.get_installed_addon_ids()
        self.assertIsInstance(addon_ids, frozenset)

    def test_manager_requires_backend_argument(self):
        with self.assertRaises(TypeError):
            RepositoryManager()  # type: ignore[call-arg]


if __name__ == "__main__":
    unittest.main()
