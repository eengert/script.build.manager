# Current Task

- Task: Correct the two confirmed Install final-confirmation Gate-2 defects (offline; no assigned task ID).
- State: COMPLETE; stop before runtime qualification.
- Starting state: clean `agent/codex` at `170715505fd9c75912d1fd7bf202c7ded61dc391`; staged runtime candidate `439ab4f8884d59b3c02a096eb1c515e5e661950e` was not accessed.
- Kodi contract: Kodi 21.3/Omega `Dialog.yesno()` defaults `defaultbutton` to `CONTROL_NO_BUTTON`; `DLG_YESNO_NO_BTN` maps to that control. [Kodi 21.3 Dialog.h](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/interfaces/legacy/Dialog.h)
- Correction: omitted `defaultbutton` from the Install final confirmation; changed English string `#32815` to `Temporary protection and a full Kodi restart may be required.` Friendly-name Gate 1 implementation was not changed. Product commit `bb6dd9f62c943b08258b9090ef23f76e6aac3c8a`.
- Validation: `python3 -m unittest tests.test_install_workflow tests.test_plan_ui -q` — 45 tests PASS. `git diff --check` — PASS. Final product diff contained only the requested three files.
- Not done: no Test.app, Kodi/profile, or device access; no Apply/runtime qualification, push, merge, release, or publication.
- Next: stop. Any Gate-2 runtime qualification requires a separate task.
- Human input: none for this offline correction; separate task required before runtime qualification.
- Usage/model/effort: start, end, and delta unavailable; exact Codex model tier and effort unavailable.
