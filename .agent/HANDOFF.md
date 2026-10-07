# Handoff — Install Final-Confirmation Gate-2 Correction

- State: COMPLETE offline; stop before runtime qualification.
- Starting state: clean `agent/codex` at `170715505fd9c75912d1fd7bf202c7ded61dc391`; staged candidate `439ab4f8884d59b3c02a096eb1c515e5e661950e` was not accessed.
- Kodi contract: Kodi 21.3/Omega documents `Dialog.yesno(defaultbutton=DLG_YESNO_NO_BTN)` and maps that constant to `CONTROL_NO_BUTTON`. [Kodi 21.3 Dialog.h](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/interfaces/legacy/Dialog.h)
- Done: removed the explicit `defaultbutton=0`; preserved Back/Apply Build labels. Changed string `#32815` to `Temporary protection and a full Kodi restart may be required.` Preserved the full Review Changes body and did not change friendly-name resolution. Product commit: `bb6dd9f62c943b08258b9090ef23f76e6aac3c8a`.
- Tests: `python3 -m unittest tests.test_install_workflow tests.test_plan_ui -q` — 45 PASS. `git diff --check` — clean. The focused confirmation test checks default omission, labels, friendly build/profile/review content, exact summary text, internal-ID exclusion, and `False` on decline; existing workflow decline coverage verifies no execution.
- Not done: no Test.app/Kodi/profile/device access or runtime Apply; no push, merge, release, or publication.
- Smallest next step: stop. A separate task is required for runtime Gate-2 qualification.
- Human input: none for this offline correction; explicit task authority is required before Test.app runtime work.
- Usage/model/effort: Codex usage source unavailable; exact model tier and effort unavailable. No values inferred.
