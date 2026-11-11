# Native dialog styling

Build Manager's main menu, Help topics, Build Status, Create fields, add-on selections and Create review use one small WindowXMLDialog presenter. Kodi selects the matching add-on resource directory using the active skin ID. The common filename is `script-build-manager-create.xml` at 1080i resolution:

| Active skin | Resource directory | Styling |
|---|---|---|
| Arctic Fuse 3 | `resources/skins/skin.arctic.fuse.3/1080i` | Active AF3 dialog includes, textures, fonts, constants and theme variables |
| Estuary | `resources/skins/skin.estuary/1080i` | Active Estuary dialog includes and native row/toggle resources |
| Other skins | `resources/skins/Default/1080i` | Self-contained neutral fallback; no claim of native styling for every skin |

Kodi 21.3 first checks the active skin's own XML, then the add-on's directory named after the skin ID, then the specified Default resource. Its window loader resolves includes through the active skin. The presenter therefore needs no custom skin detector, file loader, theme parser or installed-skin modification. It passes the supported add-on path / Default / 1080i constructor arguments.

## Mandatory action and confirmation contract

Future UI work MUST follow this contract and the matching rules in AGENTS.md. Reuse CreatePage / CreateDialogs and the existing three skin resources; do not add a second button renderer or use Kodi Dialog.yesno for a Build Manager final confirmation.

- Center action labels horizontally and vertically, without leading icons or padding spaces. Labels are single-line and rendered once. Keep shared dimensions, spacing, typography, colors and focus/navigation treatment; meaningful checkboxes and status indicators remain.
- Order primary actions first, navigation/cancellation next, Help last when present. Do not add unnecessary Help. CreatePage rejects duplicate/over-capacity actions, misplaced Help/navigation and unsafe final-confirmation shape/focus.
- No Build Manager-owned window may add a header Close/X, including through a skin include. The main screen retains its single action-pane Close; subpages retain their ordered Back/Cancel/Close actions. Escape and remote Back dismiss safely.
- Mutation approval requires review followed by a separate final modal. Back is initially focused; default result is cancellation. Only a new final pane's explicit confirm result can approve. Back/Escape/remote Back/dismissal and display failure must not execute work.
- Retain input-release settling and duplicate/queued-event fencing between pages. Preserve warning text and complete details, with wrapping/scrolling. Preserve fresh validation, stale-plan/coordinator/transaction protections and privacy.
- Add regression coverage for the shared presentation, action order, initial focus and two-step approval/cancellation safety. Check AF3, Estuary and Default contracts. Offline tests do not replace native visual inspection.

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

Estuary has an explicit variant so the other-skin fallback never needs to borrow Estuary resources. The frame preserves the pinned `DialogBackgroundCommons` background, title, outside-click dismissal and inside-click shield, while omitting its two implicit header Close controls. That include has no Close-disable parameter in Kodi 21.3, so the retained frame controls are composed directly using the same native textures, theme colors and typography. `DefaultDialogButton` and the native popup animations retain Estuary's action-button and animation treatment. The list uses `lists/focus.png`, and toggles use `buttons/radio-button-on.png` / `buttons/radio-button-off.png`. Fonts, theme colors and scrollbar defaults belong to Estuary.

There is no header Close control in either touch or non-touch mode. The right-side action column still contains only the page's declared actions. Horizontal navigation is on the native action grouplist because DefaultDialogButton does not accept nested navigation elements. AF3's Button_Control forwards nested alignment/style elements. Estuary's DefaultDialogButton supplies horizontal centering; the pinned skin's Defaults.xml supplies vertical centering. Default declares both alignments explicitly.

## Shared behavior and compatibility

A settings row carries an optional boolean toggle state. Native XML displays a visual checkbox when ListItem.Property(bm.toggle) is true and uses ListItem.IsSelected for its checked state. Other rows retain separate text label/value areas. Add-on choices remain dialog-local until OK; Select All, Deselect All, individual changes and Cancel/Back rollback use the existing page model. An empty selection remains empty and existing workflow validation prevents Create.

The private-settings row uses the same visual state without displaying an On/Off value. Choosing that row still returns its existing field index, and NativeDialogs changes the session boolean as before. The review continues to report private status as informational text. Create, Review, Add-ons and Main actions retain their behavior; Create's order is now Apply / Cancel / Help. Review is Create / Cancel / Help. Add-ons and Main keep their existing requested ordering.

**Kodi 21.3 scrollbar restriction:** no Python getControl call may target XML scrollbars 120 or 121. Visibility and horizontal navigation remain XML-owned. Native include contracts produce the same supported label/list/textbox/button IDs used by Python; the strict offline stub rejects scrollbar lookups. Focus restoration uses setFocusId with an integer ID.

Build Status uses the existing read-only textbox and XML-owned scrollbar, with Check Again / Back actions. All safe summaries and diagnostic lines from the status view model appear inline; no status list items are created. Each refresh requests one new status model. Back/Escape and window close return without another check. All three skins omit header Close controls. The presenter has no bm.native_close property or header-control click route; cancellation remains in the action pane and Back/Escape callbacks.

Help topics use the same ordinary navigation rows as Main, with toggle indicators disabled. Topic content remains in the native text viewer; returning restores the topic position. Boolean settings and add-on selection keep their existing visual checkboxes.

Actionable Install review uses the read-only textbox and Apply Build / Back / Help buttons. Back is initially focused and Help restores its button without another preview. Review Apply opens a separate Build Manager confirmation page with exactly Apply Build / Back and Back initially focused. Only its distinct `confirm` result returns approval; review's `apply` result, arbitrary dismissal and missing/failed confirmation cannot approve. Both pages use the same skin-aware presenter, with input-release settling between modals and duplicate-terminal-event fencing. The conditional overwrite warning remains bold above build/profile, calculated change summary and restart/protection notice. Fresh validation and coordinator safeguards remain in the unchanged workflow after approval.

Install NO_CHANGES uses the same textbox with only Back, preserving the complete existing explanation and optional checked timestamp. Other non-actionable states retain their existing native read-only viewer. No refresh or execution is attached to the Back-only page.

The final Install confirmation now uses the existing two-pane frame rather than the short Kodi-owned prompt. At pinned AF3 3.3.12 / 1080i, Dimension_DialogHugeMenu resolves to 1280 x 880 (100px top/bottom); the old Dimension_DialogConfirm is 1280 x 600. The existing left textbox resolves to 800 x 618 after dialog/header/text padding. Normal warning/details have ample vertical room; font_main_plot remains the native 28px font with 1.16 spacing. Long content still wraps in the textbox and scrolls through XML-owned control 121. No unrelated frame is enlarged. Native rendering under the actual chosen font set still requires visual inspection; offline geometry is not a screenshot or pixel-render proof.

Update / Repair retains its complete applied/desired information and actions, with shortened localized labels: Check Changes / Choose Revision / Back / Help. Labels remain single-line and share the centered native button styling. Revision decisions, plan calculations and execution are unchanged.

Update / Repair review now shows the complete cached proposed changes beside Apply Changes / Back / Help, initially focused on Back. Help opens the existing contextual content and returns to the same rendered review and Help focus without another preview. Review Apply Changes opens the shared separate final confirmation with its unchanged body, labels and safe default. Only an affirmative final result returns approval to the unchanged fresh-validation/execution workflow. Healthy/no-change, blocked, incomplete and other read-only check results use the same wrapping/scrolling textbox with only Back; they never offer Apply. Existing extra limit notes and optional checked timestamps remain inline.

Help is last in every owned action pane that already offers it: primary actions first, then Back/Cancel/Close, then Help. Update / Repair main is Check Changes / Choose Revision / Back / Help; its initial Check focus is unchanged. Create fields/review and Install review already follow this order. No Help action is added to confirmation, Status or read-only result panes.

Create, Install and Update / Repair final approvals now call the same confirmation presenter. Its localized heading and affirmative label are parameters; the body is the existing workflow-specific warning/summary, passed unchanged. All use exactly an affirmative action followed by Back, initial Back focus and the same tall wrapping/scrolling frame. Create's review Create action and Repair's review Apply Changes action only open this separate modal; neither is execution approval. Native Dialog.yesno is prohibited for these product confirmations. No installed skin/core changes or global native-dialog override are used.

Other Build Manager screens use standard Dialog.select, input, textviewer, ok, progress dialogs, or the standard add-on Settings window. They already belong to the active skin and are not replaced. No workflow, capture, library, lifecycle or backend styling dependency is introduced.

## Other-skin fallback

Default provides explicit text colors, button/focus textures, checkbox images and scrollbar textures, using four small owned PNG primitives in its media directory. It does not reference AF3/Estuary includes, colors, constants, variables or skin asset paths. It uses the common Kodi font13 alias and a neutral readable layout. This is functional fallback styling, not universal native inheritance. Font availability and the actual rendered result still require manual verification on any additional skin to be supported.

## Maintenance and validation

`tests/fixtures/native_skin_contracts.json` records the upstream repositories/revisions, include names, producing control parameters and source-file SHA-256 values checked for this implementation. It contains metadata only, not vendored skin definitions. Tests validate resource routing, these include contracts, required IDs, visual toggle state, action order, XML-owned navigation, fallback assets and the prior initialization-crash restriction. No test emulates Kodi's complete XML renderer or proves native appearance.

When adding support for another skin, add a matching resource directory using that skin's documented XML facilities and actual resources; retain the independent Default fallback. When upgrading the target AF3 or Kodi version, recheck the small set of native include/asset contracts and manually inspect the result.

Native checks after independent review and separately authorized staging: AF3 first, including its configured background/focus theme; circular toggles in both private settings and add-on rows; text-only native action labels; long labels/values and scrolling; keyboard/remote/mouse focus; bulk selection/Cancel rollback; Help return and final confirmation. Verify no header Close/X on any owned page, the main action-pane Close, subpage Back/Cancel, and final-confirmation cancellation. Then inspect Estuary's native title/buttons/toggles and an additional skin's fallback. Offline checks do not supply a rendered-appearance PASS.

Source references:

- [Kodi 21.3 WindowXML resource selection](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/interfaces/legacy/WindowXML.cpp)
- [Kodi 21.3 active-skin include resolution](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/guilib/GUIWindow.cpp)
- [Kodi 21.3 include parameters and nested forwarding](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/guilib/GUIIncludes.cpp)
- [AF3 3.3.12 settings layout](https://github.com/jurialmunkey/skin.arctic.fuse.3/blob/660a05c35546718e90a88be7798bb0a92632abce/1080i/Dialog_DialogSettings.xml), [dialog parts](https://github.com/jurialmunkey/skin.arctic.fuse.3/blob/660a05c35546718e90a88be7798bb0a92632abce/1080i/Dialog_Parts.xml), [buttons](https://github.com/jurialmunkey/skin.arctic.fuse.3/blob/660a05c35546718e90a88be7798bb0a92632abce/1080i/Includes_Buttons.xml)
- [Estuary settings layout](https://github.com/xbmc/xbmc/blob/21.3-Omega/addons/skin.estuary/xml/DialogSettings.xml), [dialog background](https://github.com/xbmc/xbmc/blob/21.3-Omega/addons/skin.estuary/xml/Includes.xml), [dialog buttons](https://github.com/xbmc/xbmc/blob/21.3-Omega/addons/skin.estuary/xml/Includes_Buttons.xml)

The fallback header label uses Kodi [add-on label parsing](https://kodi.wiki/view/Label_Parsing).

## Scoped audit of remaining native surfaces

The unavailable-route fallback still uses a native selection action menu; its View Details / Back / Help order is corrected, but conversion of that dormant fallback to an owned pane is outside this confirmation task. Build/profile/revision and missing-package choosers remain native data selections, including the authoritative frozen-install chooser; their decisions and engine code are untouched. Input, information/error/progress dialogs and Kodi's add-on Settings window retain their native purpose. These are not additional final-approval implementations. Any future task modifying a legacy action menu must apply the mandatory shared contract rather than introducing another native product confirmation.
