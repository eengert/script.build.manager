"""Behavioral checks for native foundation navigation and private-data boundaries."""
import ast
from pathlib import Path
import unittest
from resources.lib.ui.native_dialogs import NativeDialogs
from resources.lib.ui.controller import ROUTES, Route, CONTEXT_HELP, TITLE_IDS
from resources.lib.ui.help_content import SECTIONS, section_index
from resources.lib.ui.models import PageModel, Semantic, SEMANTIC_LABELS

ROOT = Path(__file__).resolve().parents[1]

class Addon:
    def __init__(self): self.opened = 0
    def getLocalizedString(self, identifier): return str(identifier)
    def openSettings(self): self.opened += 1
    def getSetting(self, *args): raise AssertionError('private settings read')

class Dialog:
    def __init__(self, choices): self.choices = iter(choices); self.calls = []; self.details = []
    def select(self, heading, labels, preselect=0):
        self.calls.append((heading, labels, preselect)); return next(self.choices)
    def textviewer(self, heading, text): self.details.append((heading, text))

class NativeFoundationTests(unittest.TestCase):
    def flow(self, choices):
        a=Addon(); d=Dialog(choices); ui=NativeDialogs(a,d,lambda milliseconds: None); ui.run(); return a,d,ui
    def test_native_boundaries_settle_input(self):
        a=Addon(); d=Dialog([0,0,1,-1,-1]); waits=[]
        NativeDialogs(a,d,waits.append).run()
        self.assertEqual(waits,[200]*7)

    def test_main_menu_order(self):
        _,d,_=self.flow([-1]); self.assertEqual(d.calls[0],('32000',list(map(str,TITLE_IDS)),0))
    def test_cancel_main_exits(self):
        a,d,_=self.flow([-1]); self.assertEqual(len(d.calls),1); self.assertFalse(a.opened)
    def test_every_foundation_route_explains_unavailability(self):
        for i in range(3):  # Create, Install, Update/Repair; Build Status has its own page
            with self.subTest(route=i):
                a,d,_=self.flow([i,0,-1,-1]); self.assertEqual(d.details,[(str(32100+i),str(32120+i))]); self.assertFalse(a.opened)
                self.assertIn('32138',d.calls[1][0])
    def test_every_foundation_context_help(self):
        for i in range(3):  # Build Status Help is covered in test_status_ui
            with self.subTest(route=i):
                _,d,_=self.flow([i,1,-1,-1]); self.assertEqual(d.details,[(str(32201+i),str(32301+i))])
    def test_foundation_back_restores_main_selection(self):
        for i in range(3):
            _,d,_=self.flow([i,2,-1]); self.assertEqual(d.calls[-1][2],i)
    def test_context_help_returns_to_invoking_choice(self):
        _,d,_=self.flow([0,1,-1,-1]); self.assertEqual(d.calls[2][2],1)
    def test_unavailable_detail_returns_to_choice(self):
        _,d,_=self.flow([0,0,-1,-1]); self.assertEqual(d.calls[2][2],0)
    def test_all_ten_help_sections(self):
        for i in range(10):
            _,d,_=self.flow([5,i,-1,-1]); self.assertEqual(d.details,[(str(32200+i),str(32300+i))])
    def test_help_selection_restored(self):
        _,d,_=self.flow([5,9,-1,-1]); self.assertEqual(d.calls[2][2],9)
    def test_help_cancel_restores_main_selection(self):
        _,d,_=self.flow([5,-1,-1]); self.assertEqual(d.calls[-1][2],5)
    def test_settings_opens_native_settings_directly(self):
        a,d,_=self.flow([4,-1]); self.assertEqual(a.opened,1)
        self.assertEqual(len(d.calls),2)
        self.assertEqual(d.calls[1],('32000',list(map(str,TITLE_IDS)),4))
    def test_settings_has_no_intermediate_menu(self):
        a,d,_=self.flow([4,-1]); self.assertTrue(all(c[0]=='32000' for c in d.calls))
        self.assertFalse(d.details)
    def test_settings_return_restores_main_selection(self):
        _,d,_=self.flow([4,-1]); self.assertEqual(d.calls[-1][2],4)
    def test_settings_cancel_does_not_write_preferences(self):
        a,d,_=self.flow([4,-1]); self.assertEqual(vars(a),{'opened':1})
    def test_entry_binds_explicit_addon_id(self):
        self.assertIn('xbmcaddon.Addon("script.build.manager")',(ROOT/'default.py').read_text())
    def test_entry_failure_redacts_exception(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        import default
        calls=[]; a=Addon()
        gui=SimpleNamespace(Dialog=lambda: SimpleNamespace(ok=lambda *args:calls.append(args)))
        modules={'xbmc':SimpleNamespace(sleep=lambda ms:None),
                 'xbmcaddon':SimpleNamespace(Addon=lambda name:a), 'xbmcgui':gui}
        with patch.dict(sys.modules,modules), patch(
                'resources.lib.ui.native_dialogs.NativeDialogs',
                side_effect=RuntimeError('private-token-sensitive-path')):
            default.main()
        self.assertEqual(calls,[('32126','32127')])

    def test_no_engine_imports(self):
        for p in (ROOT/'resources/lib/ui').glob('*.py'):
            tree=ast.parse(p.read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom): self.assertTrue((n.module or '').startswith(('dataclasses','enum','resources.lib.ui','resources.lib.status_model','resources.lib.plan_model')),p)
                if isinstance(n,ast.Import): self.fail('unexpected import '+str(p))
    def test_status_model_is_standard_library_only(self):
        tree=ast.parse((ROOT/'resources/lib/status_model.py').read_text())
        allowed={'__future__','re','dataclasses','datetime','enum','typing','unicodedata'}
        for n in ast.walk(tree):
            if isinstance(n,ast.ImportFrom): self.assertIn((n.module or '').split('.')[0],allowed)
            if isinstance(n,ast.Import): self.assertTrue(all(a.name.split('.')[0] in allowed for a in n.names))
    def test_no_custom_shell_or_palette(self):
        self.assertFalse((ROOT/'resources/skins').exists())
        self.assertFalse((ROOT/'resources/lib/ui/main_window.py').exists())
        self.assertNotIn('WindowXML',(ROOT/'default.py').read_text())
        self.assertFalse(any('color' in vars(v) for v in SEMANTIC_LABELS.values() if hasattr(v,'__dict__')))
    def test_all_semantics_distinct(self): self.assertEqual(len(set(SEMANTIC_LABELS.values())),9)
    def test_unknown_semantics_rejected(self):
        with self.assertRaises(ValueError): PageModel(32000,32120,'private value')
    def test_raw_title_rejected(self):
        with self.assertRaises(ValueError): PageModel('secret',32120)
    def test_raw_body_rejected(self):
        with self.assertRaises(ValueError): PageModel(32000,{'token':'secret'})
    def test_bool_identifier_rejected(self):
        with self.assertRaises(ValueError): PageModel(True,32120)
    def test_unknown_identifier_rejected(self):
        with self.assertRaises(ValueError): PageModel(99999,32120)
    def test_section_ids_complete(self): self.assertEqual([s.section_id for s in SECTIONS],['H%02d'%i for i in range(1,11)])
    def test_invalid_section_safe(self):
        with self.assertRaisesRegex(ValueError,'unsupported help section'):section_index('private')
    def test_settings_schema(self):
        import xml.etree.ElementTree as ET
        settings=ET.parse(ROOT/'resources/settings.xml').findall('.//setting')
        self.assertEqual([s.attrib['id'] for s in settings],['build_transfer_folder','notify_operation_finished'])
        self.assertEqual(settings[1].findtext('default'),'true')
    def test_resources_complete(self):
        s=(ROOT/'resources/language/resource.language.en_gb/strings.po').read_text()
        for i in (*TITLE_IDS,*range(32200,32210),*range(32300,32310),32150):self.assertIn('msgctxt "#%d"'%i,s)
    def test_invalid_main_result_closes_safely(self):
        _,d,_=self.flow([100]); self.assertEqual(len(d.calls),1)
    def test_invalid_help_result_returns(self):
        _,d,_=self.flow([5,100,-1]); self.assertFalse(d.details)

def _strings():
    import re
    text=(ROOT/'resources/language/resource.language.en_gb/strings.po').read_text(encoding='utf-8')
    out={}
    for m in re.finditer(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"',text):
        out[int(m.group(1))]=m.group(2).replace('\\n','\n').replace('\\"','"')
    return out

# Internal vocabulary that must not return to user-facing Help copy.
BANNED_HELP_TERMS=('reconcil','lifecycle','transaction','adapter','schema','manifest',
    'fingerprint','artifact','activation hold','quarantine','durable','private-resource',
    'validation report','exact-version','desired state','owner')
RAW_FIELDS=('traceback','exception','sha256','password','token','secret','api_key','/users/')

class HelpCopyTests(unittest.TestCase):
    def setUp(self): self.s=_strings()
    def bodies(self): return {i:self.s[32300+i] for i in range(10)}
    def test_titles_are_the_approved_ten(self):
        self.assertEqual([self.s[32200+i] for i in range(10)],[
            'What is Build Manager?','Create Build','Install Build','Update / Repair',
            'Build Status','Builds & Device Profiles','Safety \u2014 What Can BM Change?',
            'Restarts & Resume','Problems & Recovery','About'])
    def test_no_internal_vocabulary(self):
        for i,b in self.bodies().items():
            for t in BANNED_HELP_TERMS: self.assertNotIn(t,b.lower(),(i,t))
    def test_no_raw_diagnostics_or_private_values(self):
        for i,b in self.bodies().items():
            for t in RAW_FIELDS: self.assertNotIn(t,b.lower(),(i,t))
    def test_old_technical_copy_removed(self):
        for i,b in self.bodies().items():
            for old in ('Exact packages matter','reconciles','Advanced Details','Missing Artifact'):
                self.assertNotIn(old,b,i)
    def test_pages_are_scannable(self):
        for i,b in self.bodies().items():
            self.assertIn('\n\n',b,i)
            self.assertIn('\u2022 ',b,i)
            self.assertLess(len(b),900 if i==8 else 650,i)
            for para in b.split('\n\n'):
                self.assertLessEqual(len(para.split('. ')),3,(i,para))
    def test_safety_facts(self):
        self.assertIn('Your Kodi is not changed',self.s[32301])
        self.assertIn('never shown',self.s[32301])
        self.assertIn('before anything happens',self.s[32302])
        self.assertIn('fully closed and reopened',self.s[32302])
        self.assertIn('Does not reinstall everything',self.s[32303].replace('does not','Does not'))
        self.assertIn('older result is not the same as a fresh check',self.s[32304])
        safety=self.s[32306]
        for phrase in ('Uninstall your other add-ons','Install add-ons','Turn those add-ons on or off',
                       'Change your skin','Restore supported settings','Closing a window does not undo'):
            self.assertIn(phrase,safety)
    def test_restart_is_manual(self):
        r=self.s[32307]
        self.assertIn('Fully close Kodi',r); self.assertIn('does not reopen Kodi for you',r)


class AddonMetadataTests(unittest.TestCase):
    def test_metadata_is_current_and_parses(self):
        import xml.etree.ElementTree as ET
        root=ET.parse(ROOT/'addon.xml').getroot()
        self.assertEqual(root.attrib['id'],'script.build.manager')
        text=(ROOT/'addon.xml').read_text()
        self.assertNotIn('skeleton',text.lower())
        self.assertNotIn('not yet implemented',text.lower())
        self.assertEqual(root.findtext('.//assets/icon'),'resources/images/icon.png')


if __name__ == '__main__': unittest.main()
