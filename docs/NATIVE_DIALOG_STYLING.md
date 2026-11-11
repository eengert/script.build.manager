# Native dialog styling

Build Manager's main menu, Help topics, Build Status, Create fields, add-on selections and Create review use one small WindowXMLDialog presenter. Kodi selects the matching add-on resource directory using the active skin ID. The common filename is `script-build-manager-create.xml` at 1080i resolution:

| Active skin | Resource directory | Styling |
|---|---|---|
| Arctic Fuse 3 | `resources/skins/skin.arctic.fuse.3/1080i` | Active AF3 dialog includes, textures, fonts, constants and theme variables |
| Estuary | `resources/skins/skin.estuary/1080i` | Active Estuary dialog includes and native row/toggle resources |
| Other skins | `resources/skins/Default/1080i` | Self-contained neutral fallback; no claim of native styling for every skin |

Kodi 21.3 first checks the active skin's own XML, then the add-on's directory named after the skin ID, then the specified Default resource. Its window loader resolves includes through the active skin. The presenter therefore needs no custom skin detector, file loader, theme parser or installed-skin modification. It passes the supported add-on path / Default / 1080i constructor arguments.

## Arctic Fuse 3

The AF3 resource composes the actual settings-dialog parts rather than drawing a similar black panel:

- `Dimension_DialogHugeMenu`, `Size_Dialog_Pad`, `Size_LeftGroup_Main`, `Size_Group_Head`, `Size_Group_Body` and `Size_Grouplist_Pad` provide native frame geometry and spacing.
- `Part_Dim_Overlay`, `Part_Background_Panel`, `Part_Panel` and `Part_Line` provide AF3's texture-backed background, borders, corners, transparency and action-column treatment. Background/theme expressions and variables are evaluated by AF3 itself.
- `Part_HeadText`, `font_main`, `font_main_plot` and the dialog foreground colors provide native typography. Action labels use the skin's `Button_Control` definition and `font_mini_bold`.
- `Part_List_Highlight` provides AF3's actual focused-row appearance, including its configured focus style. Focused text and checkbox colors use the skin's corresponding selected-color variables.
- `Part_List_Checkmark` provides AF3's circular checked/unchecked resources. `Part_Scrollbar_Max` supplies the native scrollbar.

AF3's `Button_Dialog` text-only path still calls `Button_Label`, whose inner label area has a fixed left inset and literal left alignment. There is no forwarded alignment parameter at that level. Build Manager instead calls the same native `Button_Control` directly, supplying nested `align=center`, `aligny=center`, zero text offsets and `font_mini_bold`. AF3 places these nested elements before its defaults; Kodi 21.3 reads the first alignment/font/offset elements. The native background/dimensions and button focus handling remain intact. Native dialog foreground and selected-theme colors are explicit. Python fills the one real button label; there is no overlay label, second renderer or action icon. No installed skin is changed.

The include/asset contracts were inspected at AF3 **v3.3.12**, commit `660a05c35546718e90a88be7798bb0a92632abce`, matching the retained qualification target. The current upstream v3.4.20 definitions were also inspected for the directly used names, but do not replace the pinned 3.3.12 evidence. No current installed-skin version was probed in this offline task. These are skin-specific resource contracts, not a guarantee that every future AF3 release preserves the same include names.

## Estuary

Estuary has an explicit variant so the other-skin fallback never needs to borrow Estuary resources. `DialogBackgroundCommons`, `DefaultDialogButton` and the native popup animations supply the same background/header/window chrome and action-button treatment used by Kodi 21.3's Estuary dialogs. The list uses `lists/focus.png`, and toggles use `buttons/radio-button-on.png` / `buttons/radio-button-off.png`. Fonts, theme colors and scrollbar defaults belong to Estuary.

The standard Estuary header close affordance closes the dialog with its default cancellation result. The right-side action column still contains only the page's declared actions. Horizontal navigation is on the native action grouplist because DefaultDialogButton does not accept nested navigation elements. AF3's Button_Control forwards nested alignment/style elements. Estuary's DefaultDialogButton supplies horizontal centering; the pinned skin's Defaults.xml supplies vertical centering. Default declares both alignments explicitly.

## Shared behavior and compatibility

A settings row carries an optional boolean toggle state. Native XML displays a visual checkbox when ListItem.Property(bm.toggle) is true and uses ListItem.IsSelected for its checked state. Other rows retain separate text label/value areas. Add-on choices remain dialog-local until OK; Select All, Deselect All, individual changes and Cancel/Back rollback use the existing page model. An empty selection remains empty and existing workflow validation prevents Create.

The private-settings row uses the same visual state without displaying an On/Off value. Choosing that row still returns its existing field index, and NativeDialogs changes the session boolean as before. The review continues to report private status as informational text. Create, Review, Add-ons and Main actions retain their behavior; Create's order is now Apply / Cancel / Help. Review is Create / Cancel / Help. Add-ons and Main keep their existing requested ordering.

**Kodi 21.3 scrollbar restriction:** no Python getControl call may target XML scrollbars 120 or 121. Visibility and horizontal navigation remain XML-owned. Native include contracts produce the same supported label/list/textbox/button IDs used by Python; the strict offline stub rejects scrollbar lookups. Focus restoration uses setFocusId with an integer ID.

Build Status uses the existing read-only textbox and XML-owned scrollbar, with Check Again / Back actions. All safe summaries and diagnostic lines from the status view model appear inline; no status list items are created. Each refresh requests one new status model. Back/Escape and window close return without another check. AF3 uses its native Part_CloseButton in the header for this page; Estuary retains its native header close control. Default provides a conditional header Close button with the same fallback assets. These header controls leave the default cancellation result and are separate from the declared action column.

Help topics use the same ordinary navigation rows as Main, with toggle indicators disabled. Topic content remains in the native text viewer; returning restores the topic position. Boolean settings and add-on selection keep their existing visual checkboxes.

Actionable Install review uses the read-only textbox and Apply Build / Back / Help buttons. Back is initially focused and Help restores its button without another preview. Review Apply opens a separate Build Manager confirmation page with exactly Apply Build / Back and Back initially focused. Only its distinct `confirm` result returns approval; review's `apply` result, arbitrary dismissal and missing/failed confirmation cannot approve. Both pages use the same skin-aware presenter, with input-release settling between modals and duplicate-terminal-event fencing. The conditional overwrite warning remains bold above build/profile, calculated change summary and restart/protection notice. Fresh validation and coordinator safeguards remain in the unchanged workflow after approval.

Install NO_CHANGES uses the same textbox with only Back, preserving the complete existing explanation and optional checked timestamp. Other non-actionable states retain their existing native read-only viewer. No refresh or execution is attached to the Back-only page.

The final Install confirmation now uses the existing two-pane frame rather than the short Kodi-owned prompt. At pinned AF3 3.3.12 / 1080i, Dimension_DialogHugeMenu resolves to 1280 x 880 (100px top/bottom); the old Dimension_DialogConfirm is 1280 x 600. The existing left textbox resolves to 800 x 618 after dialog/header/text padding. Normal warning/details have ample vertical room; font_main_plot remains the native 28px font with 1.16 spacing. Long content still wraps in the textbox and scrolls through XML-owned control 121. No unrelated frame is enlarged. Native rendering under the actual chosen font set still requires visual inspection; offline geometry is not a screenshot or pixel-render proof.

Update / Repair retains its complete applied/desired information and actions, with shortened localized labels: Check Changes / Choose Revision / Back / Help. Labels remain single-line and share the centered native button styling. Revision decisions, plan calculations and execution are unchanged.

Update / Repair review now shows the complete cached proposed changes beside Apply Changes / Back / Help, initially focused on Back. Help opens the existing contextual content and returns to the same rendered review and Help focus without another preview. Review Apply Changes still opens the existing separate final confirmation with its unchanged body, labels and safe default. Only an affirmative final result returns approval to the unchanged fresh-validation/execution workflow. Healthy/no-change, blocked, incomplete and other read-only check results use the same wrapping/scrolling textbox with only Back; they never offer Apply. Existing extra limit notes and optional checked timestamps remain inline.

Help is last in every owned action pane that already offers it: primary actions first, then Back/Cancel/Close, then Help. Update / Repair main is Check Changes / Choose Revision / Back / Help; its initial Check focus is unchanged. Create fields/review and Install review already follow this order. No Help action is added to confirmation, Status or read-only result panes.

Other Kodi-owned prompts (for example Create and Repair confirmations) retain their existing active-skin presentation. The final Install confirmation is now owned by Build Manager and has centered icon-free buttons; no global native-dialog override was introduced.

Other Build Manager screens use standard Dialog.select, input, textviewer, yesno, ok, progress dialogs, or the standard add-on Settings window. They already belong to the active skin and are not replaced. No workflow, capture, library, lifecycle or backend styling dependency is introduced.

## Other-skin fallback

Default provides explicit text colors, button/focus textures, checkbox images and scrollbar textures, using four small owned PNG primitives in its media directory. It does not reference AF3/Estuary includes, colors, constants, variables or skin asset paths. It uses the common Kodi font13 alias and a neutral readable layout. This is functional fallback styling, not universal native inheritance. Font availability and the actual rendered result still require manual verification on any additional skin to be supported.

## Maintenance and validation

`tests/fixtures/native_skin_contracts.json` records the upstream repositories/revisions, include names, producing control parameters and source-file SHA-256 values checked for this implementation. It contains metadata only, not vendored skin definitions. Tests validate resource routing, these include contracts, required IDs, visual toggle state, action order, XML-owned navigation, fallback assets and the prior initialization-crash restriction. No test emulates Kodi's complete XML renderer or proves native appearance.

When adding support for another skin, add a matching resource directory using that skin's documented XML facilities and actual resources; retain the independent Default fallback. When upgrading the target AF3 or Kodi version, recheck the small set of native include/asset contracts and manually inspect the result.

Native checks after independent review and separately authorized staging: AF3 first, including its configured background/focus theme; circular toggles in both private settings and add-on rows; text-only native action labels; long labels/values and scrolling; keyboard/remote/mouse focus; bulk selection/Cancel rollback; Help return and final confirmation. Then inspect Estuary's native header/buttons/toggles and an additional skin's fallback. Offline checks do not supply a rendered-appearance PASS.

Source references:

- [Kodi 21.3 WindowXML resource selection](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/interfaces/legacy/WindowXML.cpp)
- [Kodi 21.3 active-skin include resolution](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/guilib/GUIWindow.cpp)
- [Kodi 21.3 include parameters and nested forwarding](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/guilib/GUIIncludes.cpp)
- [AF3 3.3.12 settings layout](https://github.com/jurialmunkey/skin.arctic.fuse.3/blob/660a05c35546718e90a88be7798bb0a92632abce/1080i/Dialog_DialogSettings.xml), [dialog parts](https://github.com/jurialmunkey/skin.arctic.fuse.3/blob/660a05c35546718e90a88be7798bb0a92632abce/1080i/Dialog_Parts.xml), [buttons](https://github.com/jurialmunkey/skin.arctic.fuse.3/blob/660a05c35546718e90a88be7798bb0a92632abce/1080i/Includes_Buttons.xml)
- [Estuary settings layout](https://github.com/xbmc/xbmc/blob/21.3-Omega/addons/skin.estuary/xml/DialogSettings.xml), [dialog background](https://github.com/xbmc/xbmc/blob/21.3-Omega/addons/skin.estuary/xml/Includes.xml), [dialog buttons](https://github.com/xbmc/xbmc/blob/21.3-Omega/addons/skin.estuary/xml/Includes_Buttons.xml)

The fallback header label uses Kodi [add-on label parsing](https://kodi.wiki/view/Label_Parsing).
