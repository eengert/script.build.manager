# Handoff — Install Final-Confirmation Compact Presentation

- State: COMPLETE offline; stop before runtime qualification.
- Starting state: clean `agent/codex` at `dd952d4d088a8809639df55b57bd92be617cc88a`. The existing staged runtime candidate `bb6dd9f62c943b08258b9090ef23f76e6aac3c8a` was not accessed or changed.
- Blocker: Kodi 21.3 Estuary's native confirmation textbox initially shows only a short viewport. The full `review_body(model)` exceeded that viewport, leaving the change and safety summary below its delayed autoscroll.
- Done: the typed `ReviewViewModel.confirmation_summary` uses a friendly localized line for one change, or bounded localized change/accepted-Skip counts otherwise. The final Yes/No body has four nonblank lines: build/version, profile, compact summary, and the exact protection/restart line. The Install menu's Review Changes action still renders the full `review_body(model)`; Gate-1 content, button labels, omitted `defaultbutton`, and decline behavior remain intact.
- Files: `resources/lib/ui/native_dialogs.py`, `resources/lib/ui/plan_view.py`, `resources/language/resource.language.en_gb/strings.po`, `tests/test_install_workflow.py`, `tests/test_plan_ui.py`.
- Validation: `python3 -m unittest tests.test_install_workflow tests.test_plan_ui -q` — 49 PASS. `git diff --check` — PASS. The first iteration exposed that the menu's Review Changes action shared the compact body; the full review body was restored there before final validation.
- Product commit: `37258ad825f574fe97e0f7cffab00413d7e8d482` (`fix: compact Install confirmation summary`). Bookkeeping is committed separately.
- Not done: no Test.app staging/runtime, Kodi/profile/device access, Apply, push, merge, release, or publication. The staged runtime and its preserved state remain untouched.
- Smallest next step: a separately authorized runtime qualification of the new product candidate, with the existing staged candidate left intact until that task explicitly stages the new commit.
- Human input: no input needed for this offline correction; a separate bounded task is required before any Test.app runtime work.
- Usage/model/effort: Codex usage source unavailable; exact model tier and effort unavailable. Start/end/delta recorded as unavailable; no values inferred.
