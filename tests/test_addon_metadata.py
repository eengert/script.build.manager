"""Package metadata checks: addon.xml describes the currently available workflows."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

# Early foundation-stage claims that are no longer true.
OBSOLETE_CLAIMS = ('not available yet', 'still being built', 'arrives with')
WORKFLOWS = ('Create Build', 'Install Build', 'Update / Repair')

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

if __name__ == '__main__':
    unittest.main()
