"""Skin-aware UI pages; no capture, storage or workflow authority.

The small page model is also the offline interaction seam. Kodi loads the
matching skin resource; Default supplies self-contained styling for other skins.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SettingsRow:
    label: str
    value: str
    toggle: Optional[bool] = None


class CreatePage:
    def __init__(self, title, rows=(), actions=(), body=None, selected=None, focus=100, position=0):
        self.title, self.rows, self.actions, self.body = title, tuple(rows), tuple(actions), body
        keys = tuple(key for key, _ in self.actions)
        if len(keys) > 4 or len(set(keys)) != len(keys):
            raise ValueError('Action panes require at most four distinct actions')
        if 'help' in keys and keys[-1] != 'help':
            raise ValueError('Help must be the last action')
        if 'cancel' in keys and any(key != 'help' for key in keys[keys.index('cancel') + 1:]):
            raise ValueError('Primary actions must precede navigation')
        if 'confirm' in keys and (keys != ('confirm', 'cancel') or focus != 202):
            raise ValueError('Final confirmation requires Back focus and cancellation')
        # None means ordinary settings; a set (including empty) means toggles.
        self.selected = None if selected is None else set(selected)
        self.focus, self.position = focus, position
        self.result = 'cancel'

    def activate(self, control_id, position=0):
        """Return True only for a terminal page action. Bulk edits stay open."""
        if control_id == 100:
            if not 0 <= position < len(self.rows):
                return False
            if self.selected is None:
                self.result = position
                return True
            if position in self.selected:
                self.selected.remove(position)
            else:
                self.selected.add(position)
            return False
        index = control_id - 201
        if not 0 <= index < len(self.actions):
            return False
        action = self.actions[index][0]
        if action == 'all':
            self.selected = set(range(len(self.rows)))
        elif action == 'none':
            self.selected.clear()
        else:
            self.result = action
            return True
        return False


class CreateDialogs:
    def __init__(self, addon, show=None):
        self.addon = addon
        self.text = addon.getLocalizedString
        self.show = show or self._show
        self.edit_focus, self.edit_position = 100, 0
        self.review_focus = 201

    def main(self, title, labels, preselect):
        # Dialog.select cannot relabel its Cancel button in Kodi 21.3.
        # Keep exactly the existing routes, using the same small XML presenter.
        page = CreatePage(title, [SettingsRow(label, '') for label in labels],
                          (('cancel', self.text(32441)),), position=preselect)
        result = self.show(page)
        return result if type(result) is int else -1

    def edit(self, session):
        t = self.text
        page = CreatePage(t(32100), (
            SettingsRow(t(32700), session.name),
            SettingsRow(t(32701), session.version),
            SettingsRow(t(32702), session.device_label),
            SettingsRow(t(32740), t(32741) % (len(session.selected), len(session.components))),
            SettingsRow(t(32705), '', toggle=session.include_private),
        ), (('apply', t(32742)), ('cancel', t(32743)), ('help', t(32112))),
            focus=self.edit_focus, position=self.edit_position)
        result = self.show(page)
        self.edit_focus, self.edit_position = page.focus, page.position
        return result

    def addons(self, session):
        t = self.text
        page = CreatePage(t(32740), tuple(SettingsRow(
            c.label + (' — ' + t(32709) if c.current_skin else ''), '') for c in session.components),
            (('ok', t(32744)), ('all', t(32745)), ('none', t(32746)), ('cancel', t(32743))),
            selected={i for i, c in enumerate(session.components) if c.addon_id in session.selected})
        return sorted(page.selected) if self.show(page) == 'ok' else None

    def review(self, body):
        t = self.text
        page = CreatePage(t(32708), actions=(('create', t(32747)),
            ('cancel', t(32743)), ('help', t(32112))), body=body, focus=self.review_focus)
        result = self.show(page)
        # Only a visible action button is remembered; text or scrollbar focus resets to Create.
        action_ids = range(201, 201 + len(page.actions))
        self.review_focus = page.focus if page.focus in action_ids else 201
        return result

    def status(self, body):
        page = CreatePage(self.text(32103), actions=(('check_again', self.text(32440)),
                          ('cancel', self.text(32113))),
                          body=body, focus=201)
        return self.show(page)

    def information(self, title, body, actions, focus=201):
        """Read-only text with explicit actions; return focus for Help round trips."""
        page = CreatePage(title, body=body, actions=actions, focus=focus)
        result = self.show(page)
        return result, page.focus

    def confirmation(self, body, title_id=32805, affirmative_id=32807):
        # A new modal page and distinct result: review's 'apply' is never approval.
        page = CreatePage(self.text(title_id), body=body,
            actions=(('confirm', self.text(affirmative_id)), ('cancel', self.text(32113))),
            focus=202)
        return self.show(page) == 'confirm'

    def _show(self, page):
        # Lazy import keeps both the page model and other UI routes Kodi-free.
        from xbmcgui import WindowXMLDialog, ListItem
        window_type = create_window_type(WindowXMLDialog, ListItem)
        window = window_type('script-build-manager-create.xml',
            self.addon.getAddonInfo('path'), 'Default', '1080i', page=page, text=self.text)
        try:
            window.doModal()
            return page.result
        finally:
            del window


def create_window_type(base, list_item):
    """Bind Kodi's supported callbacks; injected types allow offline tests."""
    class CreateWindow(base):
        def __init__(self, *args, page, text, **kwargs):
            self.page, self.text = page, text
            self.finished = False

        def onInit(self):
            p = self.page
            self.getControl(10).setLabel(p.title)
            review = p.body is not None
            self.getControl(100).setVisible(not review)
            self.getControl(110).setVisible(review)
            # Kodi 21.3 has no Python wrapper for XML scrollbars. Their
            # visibility and horizontal navigation stay in the skin XML.
            if review:
                self.getControl(110).setText(p.body)
            else:
                self.getControl(100).reset()
                self.items = [list_item(label=r.label, label2=r.value) for r in p.rows]
                self.getControl(100).addItems(self.items)
                self.refresh_toggles()
                self.getControl(100).selectItem(p.position)
            for i in range(4):
                button = self.getControl(201 + i)
                button.setVisible(i < len(p.actions))
                if i < len(p.actions):
                    button.setLabel(p.actions[i][1])
                    button.controlUp(self.getControl(201 + (i - 1) % len(p.actions)))
                    button.controlDown(self.getControl(201 + (i + 1) % len(p.actions)))
            self.setFocusId(p.focus)

        def refresh_toggles(self):
            if self.page.body is not None:
                return
            for i, item in enumerate(self.items):
                selected = i in self.page.selected if self.page.selected is not None else self.page.rows[i].toggle
                item.setProperty('bm.toggle', 'true' if selected is not None else 'false')
                if selected is not None:
                    item.select(selected)

        def remember_focus(self):
            self.page.focus = self.getFocusId()
            if self.page.body is None:
                self.page.position = self.getControl(100).getSelectedPosition()

        def onClick(self, control_id):
            if self.finished:
                return
            self.remember_focus()
            if self.page.activate(control_id, self.page.position):
                self.finished = True
                self.close()
            else:
                self.refresh_toggles()

        def onAction(self, action):
            # Kodi ACTION_PREVIOUS_MENU / NAV_BACK: includes remote Back,
            # keyboard Escape and mapped mouse back. Never accepts toggle edits.
            if action.getId() in (10, 92) and not self.finished:
                self.remember_focus()
                self.page.result = 'cancel'
                self.finished = True
                self.close()

    return CreateWindow
