"""Offline dialog state, Kodi callback binding and XML contract checks."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from resources.lib.create_workflow import CreateComponent, CreateSession, CreateValidationError
from resources.lib.ui.create_dialogs import CreateDialogs, CreatePage, SettingsRow, create_window_type
from resources.lib.ui.native_dialogs import NativeDialogs
from tests.test_ui_foundation import _strings

ROOT = Path(__file__).resolve().parents[1]


class Addon:
    strings = _strings()
    def getLocalizedString(self, identifier): return self.strings[identifier]
    def getAddonInfo(self, key):
        assert key == 'path'
        return str(ROOT)


def session():
    return CreateSession((CreateComponent('script.keymap', 'Keymap Editor', '1.0.0'),
        CreateComponent('skin.arctic.fuse.3', 'Arctic Fuse 3', '1.0.0', True)),
        'macos', 'skin.arctic.fuse.3', name='BM-MANUAL-CREATE-01', device_label='Current device',
        selected=('script.keymap',), include_private=False)


class ScriptedShow:
    def __init__(self, *steps):
        self.steps = iter(steps)
        self.pages = []
        self.values = []
    def __call__(self, page):
        self.pages.append(page)
        self.values.append(tuple(r.value for r in page.rows))
        for control, position in next(self.steps):
            if isinstance(control, str):
                control = 201 + next(i for i, (key, _) in enumerate(page.actions) if key == control)
            page.focus, page.position = control, position
            if control == -1:
                return 'cancel'
            if page.activate(control, position):
                return page.result
        raise AssertionError('page script must end with an action')


class PageTests(unittest.TestCase):
    def test_field_labels_values_and_action_order(self):
        show = ScriptedShow([('cancel', 0)])
        ui = CreateDialogs(Addon(), show)
        self.assertEqual(ui.edit(session()), 'cancel')
        p = show.pages[0]
        self.assertEqual([r.label for r in p.rows],
            ['Build name', 'Version', 'Device profile', 'Add-ons', 'Include private settings'])
        self.assertEqual([r.value for r in p.rows],
            ['BM-MANUAL-CREATE-01', '1.0.0', 'Current device', '1 of 2 included', ''])
        self.assertIs(p.rows[4].toggle, False)
        self.assertTrue(all(r.toggle is None for r in p.rows[:4]))
        self.assertEqual(p.actions, (('apply', 'Apply'), ('cancel', 'Cancel'), ('help', 'Help')))

    def test_addon_labels_current_skin_and_button_order(self):
        show = ScriptedShow([(201, 0)])
        self.assertEqual(CreateDialogs(Addon(), show).addons(session()), [0])
        p = show.pages[0]
        self.assertEqual([r.label for r in p.rows], ['Keymap Editor', 'Arctic Fuse 3 — Current skin'])
        self.assertEqual(p.actions, (('ok', 'OK'), ('all', 'Select All'),
                                    ('none', 'Deselect All'), ('cancel', 'Cancel')))

    def test_individual_toggle_is_independent(self):
        show = ScriptedShow([(100, 1), (100, 0), (201, 0)])
        self.assertEqual(CreateDialogs(Addon(), show).addons(session()), [1])

    def test_select_all_includes_current_skin(self):
        show = ScriptedShow([(202, 0), (201, 0)])
        self.assertEqual(CreateDialogs(Addon(), show).addons(session()), [0, 1])

    def test_deselect_all_stays_empty_through_ok_and_reopen(self):
        s = session()
        show = ScriptedShow([(203, 0), (201, 0)], [(201, 0)])
        ui = CreateDialogs(Addon(), show)
        s.choose(ui.addons(s))
        self.assertEqual(s.selected, ())
        self.assertEqual(ui.addons(s), [])

    def test_toggle_after_bulk_clear_does_not_restore_other_rows(self):
        show = ScriptedShow([(203, 0), (100, 1), (201, 0)])
        self.assertEqual(CreateDialogs(Addon(), show).addons(session()), [1])

    def test_cancel_rolls_back_bulk_and_individual_changes(self):
        for action in (204, -1):
            s = session()
            show = ScriptedShow([(202, 0), (100, 0), (action, 0)], [(201, 0)])
            ui = CreateDialogs(Addon(), show)
            s.choose(ui.addons(s))
            self.assertEqual(s.selected, ('script.keymap',))
            self.assertEqual(ui.addons(s), [0])

    def test_edit_focus_and_position_survive_child_dialog(self):
        show = ScriptedShow([(100, 3)], [(203, 0)])
        ui = CreateDialogs(Addon(), show)
        self.assertEqual(ui.edit(session()), 3)
        ui.edit(session())
        self.assertEqual((show.pages[1].focus, show.pages[1].position), (203, 0))
        # Captured initial values need a separate observer, before script edits.
        observed = []
        def inspect(p): observed.append((p.focus, p.position)); return 'cancel'
        ui.show = inspect
        ui.edit_focus, ui.edit_position = 100, 3
        ui.edit(session())
        self.assertEqual(observed, [(100, 3)])

    def test_review_immediately_has_body_and_requested_buttons(self):
        show = ScriptedShow([(202, 0)])
        ui = CreateDialogs(Addon(), show)
        self.assertEqual(ui.review('complete details'), 'cancel')
        p = show.pages[0]
        self.assertEqual(p.body, 'complete details')
        self.assertEqual(p.rows, ())
        self.assertEqual(p.actions, (('create', 'Create'), ('cancel', 'Cancel'), ('help', 'Help')))

    def test_main_close_and_back_return_negative_selection(self):
        for control in (201, -1):
            show = ScriptedShow([(control, 0)])
            self.assertEqual(CreateDialogs(Addon(), show).main('Build Manager', ['Create Build'], 0), -1)
            self.assertEqual(show.pages[0].actions, (('cancel', 'Close'),))

    def test_main_row_still_routes_by_index(self):
        show = ScriptedShow([(100, 4)])
        self.assertEqual(CreateDialogs(Addon(), show).main('Build Manager', ['a'] * 6, 4), 4)

    def test_invalid_control_or_row_does_not_accept(self):
        p = CreatePage('title', [SettingsRow('field', 'value')], [('cancel', 'Cancel')])
        for control, index in ((0, 0), (204, 0), (100, -1), (100, 1)):
            self.assertFalse(p.activate(control, index))
        self.assertEqual(p.result, 'cancel')


class WorkflowDialogTests(unittest.TestCase):
    def setUp(self):
        self.session = session()
        self.workflow = Mock()
        self.workflow.open.return_value = self.session
        self.workflow.suggest_version.return_value = '1.0.1'
        req = SimpleNamespace(build_name=self.session.name, build_version='1.0.0',
            device_label='Current device', include_active_skin=False)
        self.preview = SimpleNamespace(request=req, counts=(1, 1, 3, 2, 0, 0),
            private_enabled=False, excluded_labels=('Arctic Fuse 3',))
        self.workflow.preview.return_value = self.preview
        self.workflow.execute.return_value = SimpleNamespace(string_id=32736, addon_count=2,
            skin_included=False, private_included=False)
        self.dialog = Mock()
        self.busy = []

    def run_ui(self, *steps):
        self.show = ScriptedShow(*steps)
        adapter = CreateDialogs(Addon(), self.show)
        ui = NativeDialogs(Addon(), self.dialog, lambda _: None,
            create_provider=lambda: self.workflow, busy=self.busy.append, create_dialogs=adapter)
        ui.create()
        return ui

    def test_apply_review_cancel_preserves_every_edit_without_execute(self):
        self.dialog.input.side_effect = ['New Build', '2.3.4', 'Bedroom']
        self.run_ui([(100, 0)], [(100, 1)], [(100, 2)], [(100, 3)],
                    [(202, 0), (201, 0)], [(100, 4)], [(201, 0)], [(202, 0)], [('cancel', 0)])
        s = self.session
        self.assertEqual((s.name, s.version, s.device_label), ('New Build', '2.3.4', 'Bedroom'))
        self.assertEqual(s.selected, ('script.keymap', 'skin.arctic.fuse.3'))
        self.assertTrue(s.include_private)
        self.assertEqual(self.show.values[-1], ('New Build', '2.3.4', 'Bedroom', '2 of 2 included', ''))
        self.assertIs(self.show.pages[-1].rows[4].toggle, True)
        self.workflow.preview.assert_called_once_with(s)
        self.workflow.execute.assert_not_called()
        self.dialog.yesno.assert_not_called()
        self.assertEqual(self.busy, [])

    def test_review_complete_details_without_intermediate_menu(self):
        self.run_ui([(201, 0)], [(202, 0)], [('cancel', 0)])
        body = self.show.pages[1].body
        for phrase in ('BM-MANUAL-CREATE-01', '1.0.0', 'Current device',
            '1 add-ons included; 1 excluded', 'Current skin excluded',
            '3 settings, 2 files', 'Private settings excluded',
            'Include private settings: Off', 'Excluded add-ons\nArctic Fuse 3'):
            self.assertIn(phrase, body)
        self.dialog.textviewer.assert_not_called()
        self.workflow.execute.assert_not_called()

    def test_full_excluded_list_is_not_truncated(self):
        self.preview.excluded_labels = tuple('Addon %s' % i for i in range(150))
        self.run_ui([(201, 0)], [(202, 0)], [('cancel', 0)])
        for label in self.preview.excluded_labels:
            self.assertIn(label, self.show.pages[1].body)

    def test_empty_excluded_list_has_localized_none(self):
        self.preview.excluded_labels = ()
        self.run_ui([(201, 0)], [(202, 0)], [('cancel', 0)])
        self.assertIn('Excluded add-ons\nNone', self.show.pages[1].body)

    def test_zero_selection_validation_does_not_reselect_or_execute(self):
        def preview(s):
            if not s.selected: raise CreateValidationError(32725)
            raise AssertionError('must remain empty')
        self.workflow.preview.side_effect = preview
        self.run_ui([(100, 3)], [(203, 0), (201, 0)], [(201, 0)], [('cancel', 0)])
        self.assertEqual(self.session.selected, ())
        self.dialog.ok.assert_called_once_with('Create Build', Addon.strings[32725])
        self.workflow.execute.assert_not_called()

    def test_final_confirmation_negative_never_executes(self):
        self.dialog.yesno.return_value = False
        self.run_ui([(201, 0)], [(201, 0)], [('cancel', 0)])
        self.dialog.yesno.assert_called_once()
        self.workflow.execute.assert_not_called()
        self.assertEqual(self.busy, [])

    def test_final_confirmation_executes_exact_preview_once(self):
        self.dialog.yesno.return_value = True
        self.run_ui([(201, 0)], [(201, 0)])
        self.workflow.execute.assert_called_once_with(self.preview)
        self.dialog.yesno.assert_called_once()
        self.assertEqual(self.busy, [True, False])
        self.assertIn('saved and selected', self.dialog.ok.call_args.args[1])
        # Long excluded details belong to the scrollable review, not yes/no.
        self.assertNotIn('Excluded add-ons', self.dialog.yesno.call_args.args[1])

    def test_help_retains_the_same_preview_and_review_body(self):
        self.dialog.yesno.return_value = True
        self.run_ui([('help', 0)], [(201, 0)], [('help', 0)], [(201, 0)])
        self.assertEqual(self.dialog.textviewer.call_count, 2)
        self.workflow.preview.assert_called_once()
        self.assertEqual(self.show.pages[2].body, self.show.pages[3].body)
        self.workflow.execute.assert_called_once_with(self.preview)

    def test_back_from_review_then_back_from_edit_never_executes(self):
        self.run_ui([(201, 0)], [(-1, 0)], [(-1, 0)])
        self.workflow.execute.assert_not_called()
        self.dialog.yesno.assert_not_called()

    def test_error_remains_redacted_and_busy_is_cleared(self):
        self.dialog.yesno.return_value = True
        self.workflow.execute.side_effect = RuntimeError('private-token')
        self.run_ui([(201, 0)], [(201, 0)], [('cancel', 0)])
        self.assertEqual(self.busy, [True, False])
        self.dialog.ok.assert_called_once_with('Create Build', Addon.strings[32732])


class Control:
    def __init__(self): self.items = []; self.position = 0
    def setLabel(self, label): self.label = label
    def setVisible(self, visible): self.visible = visible
    def setText(self, text): self.text = text
    def reset(self): self.items = []
    def addItems(self, items): self.items.extend(items)
    def selectItem(self, position): self.position = position
    def getSelectedPosition(self): return self.position
    def controlLeft(self, other): self.left = other
    def controlRight(self, other): self.right = other
    def controlUp(self, other): self.up = other
    def controlDown(self, other): self.down = other


class ListItem:
    def __init__(self, label, label2):
        self.label, self.label2 = label, label2
        self.properties, self.selected = {}, False
    def setProperty(self, key, value): self.properties[key] = value
    def setLabel2(self, label): self.label2 = label
    def select(self, selected): self.selected = selected


class WindowBase:
    def __new__(cls, *args, **kwargs):
        w = super().__new__(cls)
        w.arguments = args
        w.controls = {i: Control() for i in (10, 100, 110, 120, 121, 201, 202, 203, 204)}
        w.closed = 0
        w.properties = {}
        return w
    def getControl(self, ident):
        # Kodi 21.3 Window::GetControlById has no scrollbar wrapper.
        if ident in (120, 121):
            raise RuntimeError('Unknown control type for python')
        return self.controls[ident]
    def setProperty(self, key, value): self.properties[key] = value
    def setFocusId(self, ident): self.focus = ident
    def getFocusId(self): return self.focus
    def close(self): self.closed += 1


class KodiBindingTests(unittest.TestCase):
    def window(self, page):
        w = create_window_type(WindowBase, ListItem)(page=page, text=Addon().getLocalizedString)
        w.onInit()
        return w

    def toggle_page(self):
        return CreatePage('Add-ons', [SettingsRow('one', ''), SettingsRow('skin', '')],
            [('ok', 'OK'), ('all', 'Select All'), ('none', 'Deselect All'), ('cancel', 'Cancel')], selected={0})

    def test_kodi21_main_initializes_all_routes_and_only_close_without_scrollbar_wrappers(self):
        labels = [Addon.strings[i] for i in range(32100, 32106)]
        p = CreatePage('Build Manager', [SettingsRow(label, '') for label in labels],
                       [('cancel', 'Close')])
        w = self.window(p)
        self.assertEqual(w.getControl(10).label, 'Build Manager')
        self.assertEqual([item.label for item in w.getControl(100).items], labels)
        visible = [w.getControl(i) for i in range(201, 205) if w.getControl(i).visible]
        self.assertEqual([button.label for button in visible], ['Close'])
        self.assertEqual(w.getFocusId(), 100)
        w.onClick(201)
        self.assertEqual((p.result, w.closed), ('cancel', 1))

    def test_individual_and_bulk_actions_immediately_refresh_visible_items(self):
        w = self.window(self.toggle_page())
        def values(): return [(i.label2, i.selected) for i in w.items]
        self.assertEqual(values(), [('', True), ('', False)])
        w.getControl(100).selectItem(1)
        w.onClick(100)
        self.assertEqual(values(), [('', True), ('', True)])
        w.onClick(203)
        self.assertEqual(values(), [('', False), ('', False)])
        w.onClick(202)
        self.assertEqual(values(), [('', True), ('', True)])
        self.assertEqual(w.closed, 0)
        w.onClick(201)
        self.assertEqual(w.page.result, 'ok')
        self.assertEqual(w.closed, 1)

    def test_private_toggle_uses_visual_state_while_regular_values_stay_text(self):
        for selected in (False, True):
            page = CreatePage('Create', [SettingsRow('Name', 'Example'),
                SettingsRow('Private', '', toggle=selected)], [('cancel', 'Cancel')])
            w = self.window(page)
            self.assertEqual(w.items[0].properties['bm.toggle'], 'false')
            self.assertEqual(w.items[1].properties['bm.toggle'], 'true')
            self.assertEqual(w.items[1].selected, selected)
            self.assertEqual(w.items[1].label2, '')
            self.assertEqual(w.items[0].label2, 'Example')

    def test_bulk_clear_keeps_off_checkboxes_visible_and_cancel_discards_edits(self):
        p = self.toggle_page()
        original = set(p.selected)
        w = self.window(p)
        w.onClick(203)
        self.assertTrue(all(i.properties['bm.toggle'] == 'true' and not i.selected for i in w.items))
        w.onClick(204)
        self.assertEqual(p.result, 'cancel')
        self.assertEqual(original, {0})

    def test_native_action_icons_follow_semantics_after_button_reordering(self):
        p = CreatePage('Create', [], [('apply', 'Apply'), ('cancel', 'Cancel'), ('help', 'Help')])
        w = self.window(p)
        self.assertEqual([w.properties['bm.action.%s.icon' % i] for i in (201, 202, 203)],
            ['special://skin/extras/icons/circle-check.png', 'special://skin/extras/icons/circle-xmark.png',
             'special://skin/extras/icons/circle-question.png'])

    def test_review_scrollbar_click_does_not_require_list_items(self):
        p = CreatePage('Review', actions=[('create', 'Create'), ('cancel', 'Cancel'), ('help', 'Help')],
                       body='details', focus=121)
        w = self.window(p)
        w.onClick(121)
        self.assertEqual(w.closed, 0)
        self.assertEqual(p.result, 'cancel')

    def test_terminal_click_ignores_duplicate_and_queued_events(self):
        p = CreatePage('Review', actions=[('create', 'Create'), ('cancel', 'Cancel')], body='details', focus=201)
        w = self.window(p)
        w.onClick(201); w.onClick(201); w.onClick(202)
        w.onAction(SimpleNamespace(getId=lambda: 92))
        self.assertEqual((p.result, w.closed), ('create', 1))

    def test_back_escape_discard_unaccepted_selection(self):
        for action in (10, 92):
            w = self.window(self.toggle_page())
            w.onClick(203)
            w.onAction(SimpleNamespace(getId=lambda: action))
            self.assertEqual((w.page.result, w.closed), ('cancel', 1))

    def test_review_text_is_visible_with_wrapped_action_navigation(self):
        p = CreatePage('Review', actions=[('create', 'Create'), ('cancel', 'Cancel'), ('help', 'Help')], body='all details', focus=201)
        w = self.window(p)
        self.assertFalse(w.getControl(100).visible)
        self.assertTrue(w.getControl(110).visible)
        self.assertEqual(w.getControl(110).text, 'all details')
        self.assertFalse(w.getControl(204).visible)
        self.assertIs(w.getControl(201).up, w.getControl(203))
        self.assertIs(w.getControl(203).down, w.getControl(201))

    def test_settings_navigation_and_focus_restoration(self):
        p = CreatePage('Create', [SettingsRow('name', 'entered')], [('apply', 'Apply'), ('help', 'Help'), ('cancel', 'Cancel')], position=0)
        w = self.window(p)
        self.assertEqual(w.getFocusId(), 100)
        self.assertTrue(w.getControl(100).visible)
        self.assertFalse(w.getControl(110).visible)
        w.onClick(100)
        self.assertEqual((p.result, p.focus, p.position), (0, 100, 0))

    def test_review_can_restore_scrollbar_focus_without_a_python_wrapper(self):
        p = CreatePage('Review', actions=[('create', 'Create'), ('cancel', 'Cancel'), ('help', 'Help')],
                       body='details', focus=121)
        w = self.window(p)
        self.assertEqual(w.getFocusId(), 121)
        w.onAction(SimpleNamespace(getId=lambda: 92))
        self.assertEqual((p.result, p.focus, w.closed), ('cancel', 121, 1))

    def test_main_row_selection_and_back_with_kodi21_control_types(self):
        for back in (10, 92):
            p = CreatePage('Build Manager', [SettingsRow(str(i), '') for i in range(6)],
                           [('cancel', 'Close')], position=4)
            w = self.window(p)
            self.assertEqual(w.getControl(100).getSelectedPosition(), 4)
            w.onAction(SimpleNamespace(getId=lambda: back))
            self.assertEqual((p.result, w.closed), ('cancel', 1))
        p = CreatePage('Build Manager', [SettingsRow(str(i), '') for i in range(6)],
                       [('cancel', 'Close')])
        w = self.window(p)
        w.getControl(100).selectItem(5)
        w.onClick(100)
        self.assertEqual((p.result, w.closed), (5, 1))

    def test_default_main_close_exits_without_dispatching_a_workflow(self):
        windows = []
        class Base(WindowBase):
            def doModal(self):
                windows.append(self)
                self.onInit()
                self.onClick(201)
        provider = Mock(side_effect=AssertionError('must not dispatch'))
        gui = SimpleNamespace(WindowXMLDialog=Base, ListItem=ListItem)
        with patch.dict(sys.modules, xbmcgui=gui):
            NativeDialogs(Addon(), Mock(), lambda _: None, create_provider=provider,
                          install_provider=provider, repair_provider=provider).run()
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].getControl(201).label, 'Close')
        self.assertEqual([row.label for row in windows[0].page.rows],
            ['Create Build', 'Install Build', 'Update / Repair Build', 'Build Status',
             'Settings', 'Help / Information'])
        provider.assert_not_called()

    def test_lazy_kodi_construction_uses_supported_xml_fallback_and_resolution(self):
        captures = []
        class Base(WindowBase):
            def doModal(self):
                captures.append(self)
                self.onInit()
                self.onClick(201)
        gui = SimpleNamespace(WindowXMLDialog=Base, ListItem=ListItem)
        with patch.dict(sys.modules, xbmcgui=gui):
            self.assertEqual(CreateDialogs(Addon()).main('Build Manager', ['Create Build'], 0), -1)
        self.assertEqual(captures[0].arguments,
            ('script-build-manager-create.xml', str(ROOT), 'Default', '1080i'))
        self.assertEqual(captures[0].getControl(201).label, 'Close')


class XmlTests(unittest.TestCase):
    def resources(self):
        return sorted((ROOT / 'resources/skins').rglob('*.xml'))

    def contracts(self):
        import json
        return json.loads((ROOT / 'tests/fixtures/native_skin_contracts.json').read_text())

    def controls(self, path):
        """Declared IDs plus the pinned native include contracts (no GUI emulation)."""
        root = ET.parse(path)
        controls = {int(c.get('id')): c.get('type') for c in root.findall('.//control[@id]')}
        native = self.contracts().get(path.parent.parent.name, {}).get('includes', {})
        for call in root.findall('.//include'):
            name = call.get('content') or call.text
            self.assertIn(name, native, path)
            params = {p.get('name'): p.get('value', p.text) for p in call.findall('param')}
            for parameter, kind in native[name]['produces'].items():
                if parameter in params:
                    ident = int(params[parameter])
                    self.assertNotIn(ident, controls, path)
                    controls[ident] = kind
        return controls

    def test_skin_variants_and_required_kodi_controls(self):
        self.assertEqual({p.parent.parent.name for p in self.resources()},
                         {'Default', 'skin.estuary', 'skin.arctic.fuse.3'})
        required = {10: 'label', 100: 'list', 110: 'textbox', 120: 'scrollbar', 121: 'scrollbar',
                    201: 'button', 202: 'button', 203: 'button', 204: 'button'}
        for path in self.resources():
            self.assertEqual(path.parent.name, '1080i')
            controls = self.controls(path)
            self.assertEqual({i: controls[i] for i in required}, required)
            root = ET.parse(path)
            self.assertEqual(root.findtext('.//control[@id="100"]/pagecontrol'), '120')
            self.assertEqual(root.findtext('.//control[@id="110"]/pagecontrol'), '121')
            self.assertEqual(root.findtext('.//control[@id="110"]/autoscroll'), 'false')
            self.assertFalse(root.findall('.//onload'))

    def test_native_mappings_use_the_skin_definitions(self):
        contracts = self.contracts()
        af3 = ET.parse(ROOT / 'resources/skins/skin.arctic.fuse.3/1080i/script-build-manager-create.xml')
        names = {n.get('content') or n.text for n in af3.findall('.//include')}
        self.assertLessEqual({'Part_Background_Panel', 'Dimension_DialogHugeMenu', 'Part_List_Highlight',
            'Part_List_Checkmark', 'Button_Dialog', 'Part_Scrollbar_Max'}, names)
        self.assertEqual(contracts['skin.arctic.fuse.3']['revision'], '660a05c35546718e90a88be7798bb0a92632abce')
        for row in contracts.values():
            for contract in row['includes'].values():
                self.assertRegex(contract['source_sha256'], r'^[0-9a-f]{64}$')
        estuary = ET.parse(ROOT / 'resources/skins/skin.estuary/1080i/script-build-manager-create.xml')
        names = {n.get('content') or n.text for n in estuary.findall('.//include')}
        self.assertLessEqual({'DialogBackgroundCommons', 'DefaultDialogButton'}, names)
        self.assertEqual(contracts['skin.estuary']['revision'], '21.3-Omega')
        self.assertTrue(estuary.findall('.//texture[.="lists/focus.png"]'))
        self.assertTrue(estuary.findall('.//texture[.="buttons/radio-button-on.png"]'))
        self.assertTrue(estuary.findall('.//texture[.="buttons/radio-button-off.png"]'))

    def test_fields_and_toggle_labels_have_separate_space_and_scroll(self):
        for path in self.resources():
            root = ET.parse(path)
            layout = root.find('.//control[@id="100"]/focusedlayout')
            labels = layout.findall('./control[@type="label"]')
            self.assertEqual([n.findtext('label') for n in labels],
                ['$INFO[ListItem.Label]', '$INFO[ListItem.Label]', '$INFO[ListItem.Label2]'])
            self.assertEqual(labels[0].findtext('right'), '52%')
            self.assertEqual(labels[2].findtext('left'), '52%')
            self.assertEqual(labels[2].findtext('align'), 'right')
            self.assertTrue(all(n.findtext('scroll') == 'true' for n in labels))
            self.assertEqual(labels[1].findtext('visible'), 'String.IsEqual(ListItem.Property(bm.toggle),true)')
            self.assertEqual(labels[2].findtext('visible'), '!String.IsEqual(ListItem.Property(bm.toggle),true)')
            self.assertGreaterEqual(int(layout.get('width')), 840)

    def test_scrollbars_and_horizontal_navigation_stay_in_xml(self):
        for path in self.resources():
            root = ET.parse(path)
            if path.parent.parent.name == 'skin.arctic.fuse.3':
                bars = root.findall('.//include[@content="Part_Scrollbar_Max"]')
            else:
                bars = [root.find('.//control[@id="%s"]' % i) for i in (120, 121)]
            self.assertEqual([n.findtext('visible') for n in bars],
                             ['Control.IsVisible(100)', 'Control.IsVisible(110)'])
            self.assertEqual(bars[1].findtext('onleft'), '201')
            self.assertEqual(bars[1].findtext('onright'), '201')
            self.assertTrue(all(n.findtext('showonepage') == 'true' or
                n.findtext('param[@name="showonepage"]') == 'true' for n in bars))
            if path.parent.parent.name == 'skin.estuary':
                actions = [root.find('.//control[@id="9000"]')]
            elif path.parent.parent.name == 'skin.arctic.fuse.3':
                actions = root.findall('.//include[@content="Button_Dialog"]')
            else:
                actions = [root.find('.//control[@id="%s"]' % i) for i in range(201, 205)]
            for action in actions:
                for direction in ('onleft', 'onright'):
                    self.assertEqual([(n.get('condition'), n.text) for n in action.findall(direction)],
                        [('Control.IsVisible(110)', '121'), ('!Control.IsVisible(110)', '100')])

    def test_native_buttons_keep_declared_order_and_af3_dynamic_icon_bindings(self):
        for skin, include in (('skin.arctic.fuse.3', 'Button_Dialog'), ('skin.estuary', 'DefaultDialogButton')):
            root = ET.parse(ROOT / 'resources/skins' / skin / '1080i/script-build-manager-create.xml')
            buttons = root.findall('.//include[@content="%s"]' % include)
            self.assertEqual([n.findtext('param[@name="id"]') for n in buttons], ['201', '202', '203', '204'])
            if skin == 'skin.arctic.fuse.3':
                self.assertEqual([n.findtext('param[@name="icon"]') for n in buttons],
                    ['$INFO[Window.Property(bm.action.%s.icon)]' % i for i in range(201, 205)])

    def test_fallback_is_self_contained_and_toggle_states_are_distinct(self):
        import struct
        path = ROOT / 'resources/skins/Default/1080i/script-build-manager-create.xml'
        root = ET.parse(path)
        self.assertFalse(root.findall('.//include'))
        text = path.read_text()
        self.assertNotIn('$VAR[', text)
        self.assertNotIn('special://skin/', text)
        for node in root.findall('.//texture') + root.findall('.//texturefocus') + root.findall('.//texturenofocus'):
            asset = path.parent.parent / 'media' / node.text
            content = asset.read_bytes()
            self.assertTrue(content.startswith(b'\x89PNG\r\n\x1a\n'), asset)
            width, height = struct.unpack('>II', content[16:24])
            self.assertGreater(width, 0); self.assertGreater(height, 0)
        media = path.parent.parent / 'media'
        self.assertNotEqual((media/'bm-check-on.png').read_bytes(), (media/'bm-check-off.png').read_bytes())
        self.assertTrue(root.findall('.//texturesliderbarfocus'))
        self.assertTrue(root.findall('.//texturefocus'))

    def test_all_strings_remain_localized(self):
        for identifier in range(32740, 32749): self.assertIn(identifier, Addon.strings)
        self.assertEqual(Addon.strings[32441], 'Close')
