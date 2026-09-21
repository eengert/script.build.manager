"""Tests for BM-021B immutable exact add-on artifacts."""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from resources.lib.artifacts import (
    ArtifactStore,
    ArtifactStoreError,
    ArtifactValidationError,
    validate_addon_zip,
)


def _xml(addon_id="plugin.example", version="1.2.3"):
    return f'<addon id="{addon_id}" version="{version}" name="Example" />'.encode()


def _zip(entries, *, compression=zipfile.ZIP_DEFLATED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return output.getvalue()


class TestAddonZipValidation(unittest.TestCase):
    def test_valid_exact_zip_returns_sha_and_size(self):
        data = _zip({"plugin.example/addon.xml": _xml()})
        metadata = validate_addon_zip(
            data, expected_addon_id="plugin.example", expected_version="1.2.3"
        )
        self.assertEqual(len(data), metadata.size)
        self.assertEqual(64, len(metadata.sha256))

    def test_wrong_id_and_version_rejected(self):
        data = _zip({"plugin.example/addon.xml": _xml()})
        with self.assertRaises(ArtifactValidationError):
            validate_addon_zip(data, expected_addon_id="plugin.other", expected_version="1.2.3")
        with self.assertRaises(ArtifactValidationError):
            validate_addon_zip(data, expected_addon_id="plugin.example", expected_version="9.9.9")

    def test_malformed_zip_rejected(self):
        with self.assertRaises(ArtifactValidationError):
            validate_addon_zip(b"not a zip", expected_addon_id="plugin.example", expected_version="1.2.3")

    def test_unsafe_paths_and_multiple_roots_rejected(self):
        with self.assertRaises(ArtifactValidationError):
            validate_addon_zip(
                _zip({"plugin.example/addon.xml": _xml(), "../escape": b"x"}),
                expected_addon_id="plugin.example", expected_version="1.2.3",
            )
        with self.assertRaises(ArtifactValidationError):
            validate_addon_zip(
                _zip({"plugin.example/addon.xml": _xml(), "other/file": b"x"}),
                expected_addon_id="plugin.example", expected_version="1.2.3",
            )

    def test_no_installed_directory_fallback_is_possible(self):
        with self.assertRaises(ArtifactValidationError):
            validate_addon_zip(
                _zip({"plugin.example/readme.txt": b"no addon xml"}),
                expected_addon_id="plugin.example", expected_version="1.2.3",
            )


class TestArtifactStore(unittest.TestCase):
    def test_import_is_atomic_readable_and_deduplicates(self):
        data = _zip({"plugin.example/addon.xml": _xml()})
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            first = store.import_zip(
                data, expected_addon_id="plugin.example", expected_version="1.2.3", source="cache"
            )
            second = store.import_zip(
                data, expected_addon_id="plugin.example", expected_version="1.2.3", source="repository"
            )
            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(data, store.read_bytes(first.sha256))
            self.assertEqual(first, store.get_metadata(first.sha256))
            self.assertEqual(1, len(list((Path(directory) / "artifacts").glob("*.zip"))))

    def test_existing_digest_path_is_not_overwritten(self):
        data = _zip({"plugin.example/addon.xml": _xml()})
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            metadata = store.import_zip(
                data, expected_addon_id="plugin.example", expected_version="1.2.3"
            )
            path = store.artifact_path(metadata.sha256)
            path.write_bytes(b"tampered")
            with self.assertRaises(ArtifactStoreError):
                store.import_zip(
                    data, expected_addon_id="plugin.example", expected_version="1.2.3"
                )

    def test_failed_import_publishes_no_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            with self.assertRaises(ArtifactValidationError):
                store.import_zip(
                    b"bad", expected_addon_id="plugin.example", expected_version="1.2.3"
                )
            self.assertEqual([], list((Path(directory) / "artifacts").glob("*.zip")))
