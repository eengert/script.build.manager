"""The AF3 fixture is authored from exact retained inputs, never native state."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import bm_item8_af3_fixture as fixture
from resources.lib.frozen import FrozenBuildManifest, CaptureError
from resources.lib.frozen_install import validate_frozen_manifest, validate_frozen_install_plan


class AuthoredAF3FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.store = fixture.prepare()

    def test_exact_graph_classification_and_original_archive_identity(self):
        m = self.manifest
        self.assertEqual((22, 45), (len(m.addons), sum(len(n.dependency_edges) for n in m.addons)))
        self.assertEqual(fixture.SYSTEM_IDS, {n.addon_id for n in m.addons if n.system})
        self.assertEqual(["script.module.pil"], [n.addon_id for n in m.addons if n.platform_provided])
        managed = [n for n in m.addons if n.artifact]
        self.assertEqual(17, len(managed))
        for n in managed:
            data = self.store.read_bytes(n.artifact.sha256)
            self.assertEqual((n.artifact.sha256, n.artifact.size),
                             (hashlib.sha256(data).hexdigest(), len(data)))
        font = next(n for n in managed if n.addon_id == "resource.font.robotocjksc")
        self.assertEqual("58c3e32cafbbf0984896c4ab317c820e555f3deacae977598e4a03a0f8139743", font.artifact.sha256)
        self.assertTrue(all(n.artifact is None for n in m.addons if n.system or n.platform_provided))

    def test_production_roundtrip_fingerprint_and_both_strict_plans(self):
        m = self.manifest
        self.assertEqual(m.to_dict(), FrozenBuildManifest.from_json(m.to_json()).to_dict())
        strict = validate_frozen_manifest(m, self.store)
        plan = validate_frozen_install_plan(m, self.store)
        self.assertEqual((18, 17), (len(strict.install_order), len(plan.executable_install_order)))
        self.assertEqual("0399a872129059607efed0281c83a9e1f87699648ada55f9fa876a8b8324f545", m.fingerprint())
        forged = m.to_dict()
        forged["software_fingerprint"] = "0" * 64
        with self.assertRaises(CaptureError):
            FrozenBuildManifest.from_dict(forged)

    def test_authorship_and_source_limitations_are_explicit(self):
        m = self.manifest
        self.assertEqual(fixture.LABEL, m.name)
        self.assertEqual("NONE", m.source_metadata["runtime_observations"])
        self.assertEqual("UNOBSERVED", m.kodi_version)
        core = next(n for n in m.addons if n.addon_id == "xbmc.core")
        self.assertIn("Raw core XML not retained", core.provenance_detail["limitation"])
        for aid in ("xbmc.gui", "xbmc.python", "kodi.resource"):
            node = next(n for n in m.addons if n.addon_id == aid)
            self.assertEqual(("xbmc.core",), node.required_dependency_ids)

    def test_altered_sealed_metadata_blocks_before_archive_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in fixture.PINS:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("{}")
            with self.assertRaisesRegex(fixture.FixtureInputError, "checksum mismatch"):
                fixture.prepare(root)

    def test_missing_archive_blocks_construction(self):
        real = fixture._read
        def missing(root, name, digest=None):
            if name.endswith(".zip"):
                raise fixture.FixtureInputError("approved archive missing")
            return real(root, name, digest)
        with patch.object(fixture, "_read", missing):
            with self.assertRaisesRegex(fixture.FixtureInputError, "archive missing"):
                fixture.prepare()

    def test_changed_graph_or_classification_cannot_be_resealed_implicitly(self):
        real = fixture._read
        for field, value in (("version", "999.0.0"), ("id", "wrong.id"),
                             ("sha256", "0" * 64), ("bytes", 0)):
            with self.subTest(field=field):
                def altered(root, name, digest=None):
                    data = real(root, name, digest)
                    if name == next(iter(fixture.PINS)):
                        d = json.loads(data)
                        d["nodes"][0][field] = value
                        return json.dumps(d).encode()
                    return data
                # Even bypassing the outer metadata pin cannot bypass archive identity.
                with patch.object(fixture, "_read", altered), self.assertRaises(Exception):
                    fixture.prepare()

    def test_invalid_zip_and_wrong_dependency_xml_block(self):
        real = fixture._read
        for replacement in (b"not a zip", b"PK\x03\x04"):
            with self.subTest(replacement=replacement):
                def corrupt(root, name, digest=None):
                    if name.endswith(".zip"):
                        return replacement
                    return real(root, name, digest)
                with patch.object(fixture, "_read", corrupt), self.assertRaises(Exception):
                    fixture.prepare()

    def test_dependency_declaration_disagreement_blocks(self):
        real = fixture._read
        def changed(root, name, digest=None):
            data = real(root, name, digest)
            if name == next(iter(fixture.PINS)):
                d = json.loads(data)
                d["edges"][0]["minimum"] = "999.0.0"
                return json.dumps(d).encode()
            return data
        with patch.object(fixture, "_read", changed), self.assertRaisesRegex(
                fixture.FixtureInputError, "dependency/root evidence mismatch"):
            fixture.prepare()

    def test_incomplete_closure_blocks(self):
        real = fixture._read
        def incomplete(root, name, digest=None):
            data = real(root, name, digest)
            if name == next(iter(fixture.PINS)):
                d = json.loads(data)
                d["edges"].pop()
                return json.dumps(d).encode()
            return data
        with patch.object(fixture, "_read", incomplete), self.assertRaises(fixture.FixtureInputError):
            fixture.prepare()
