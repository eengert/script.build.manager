"""Package metadata checks: addon.xml describes the currently available workflows."""
from pathlib import Path
import hashlib
import struct
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

# Early foundation-stage claims that are no longer true.
OBSOLETE_CLAIMS = ('not available yet', 'still being built', 'arrives with')
WORKFLOWS = ('Create Build', 'Install Build', 'Update / Repair')

# Exact approved artwork (matrix a33a3f8); the SHA pin is intentional.
ICON_PATH = 'resources/images/icon.png'
ICON_SHA256 = '207c44a0474e7e370cf6d210c7646ce243c704a0694ef422c12bd51401628d23'

class AddonMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / 'addon.xml').read_text(encoding='utf-8')
        cls.root = ET.fromstring(cls.raw)
        cls.metadata = cls.root.find('./extension[@point="xbmc.addon.metadata"]')
        cls.news = cls.metadata.findtext('news') or ''
        cls.descriptions = {d.get('lang'): d.text or '' for d in cls.metadata.findall('description')}
        cls.summaries = {s.get('lang'): s.text or '' for s in cls.metadata.findall('summary')}

    def test_addon_xml_parses_with_metadata_and_locales(self):
        self.assertEqual(self.root.get('id'), 'script.build.manager')
        self.assertTrue(self.news.strip())
        self.assertEqual(set(self.descriptions), {'en_US', 'en_GB'})
        self.assertEqual(set(self.summaries), {'en_US', 'en_GB'})

    def test_summaries_describe_capture_and_apply_not_backup(self):
        for lang, summary in self.summaries.items():
            with self.subTest(lang=lang):
                self.assertEqual(summary, 'Capture and apply a managed Kodi setup.')
                self.assertNotIn('restore', summary.lower())
                self.assertNotIn('backup', summary.lower())

    def test_obsolete_claims_removed(self):
        lowered = self.raw.lower()
        for claim in OBSOLETE_CLAIMS:
            self.assertNotIn(claim, lowered)

    def test_workflows_described_as_available(self):
        self.assertTrue(all(name in self.news for name in WORKFLOWS))
        for text in self.descriptions.values():
            self.assertTrue(all(name in text for name in WORKFLOWS))

    def test_packaged_icon_is_approved_512_png(self):
        self.assertEqual(self.metadata.findtext('assets/icon'), ICON_PATH)
        data = (ROOT / ICON_PATH).read_bytes()
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(data[12:16], b'IHDR')
        self.assertEqual(struct.unpack('>II', data[16:24]), (512, 512))
        self.assertEqual(hashlib.sha256(data).hexdigest(), ICON_SHA256)

if __name__ == '__main__':
    unittest.main()
