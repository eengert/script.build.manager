# Handoff — Package metadata refresh

- State: COMPLETE; product commit `6105282b5340ba15f0ca4b231ce1e27c42d3cb81` on `agent/claude`, local only, not pushed.
- Start: `agent/claude` at `2eefb452e6deee4ec123b403670784aaa281b6f4`, clean. Recent commits touched only `.agent/**`, `.orchestrator/**`, and docs.
- Changed: `addon.xml` (`<news>`, `en_US` and `en_GB` `<description>`; summary and version unchanged at 0.1.0) and new `tests/test_addon_metadata.py` (3 tests: XML parses with metadata and both locales; obsolete claims "not available yet", "still being built", "arrives with" absent; Create Build, Install Build, Update / Repair named as available in news and both descriptions).
- Tests: focused metadata test 3/3 pass; the new test fails 2 checks on the pre-fix addon.xml, as intended. Related `tests.test_ui_foundation`, `tests.test_installed_addon_source`, `tests.test_imports`: 56 run, 1 failure, `test_ui_foundation.NativeFoundationTests.test_no_engine_imports` (flags `resources/lib/ui/plan_view.py`). That failure reproduces on a clean `git archive` of `2eefb45`, so it predates this change and is out of scope.
- Live-proven: nothing. This is text and a unit test only. Kodi did not parse or display the new metadata.
- Not done: no Kodi, Test.app, profile, device, MCP, or push activity; no full-suite run (not needed for a text-only change that no code path consumes beyond id/version parsing).
- Out of scope — noticed:
  - `test_no_engine_imports` failure above (pre-existing).
  - `.orchestrator/HANDOFF.md` says BM-UI-002A replaced stale skeleton addon.xml wording, but the `agent/claude` addon.xml was still stale until this commit. Worth checking on `matrix`.
  - `resources/images/icon.png` is still the generic icon (`CUSTOM_ICON_ASSET_REQUIRED`), unchanged here.
- Human decisions:
  1. Summary `Save and restore your Kodi setup.` was kept per the instruction to keep the summary unless false. "Restore" can read as general backup/restore, which `AGENTS.md` says Build Manager is not. Decide whether to reword it.
  2. Whether the store copy should carry a beta/qualification note. None was added, and no completion claim was made.
- Smallest next step: decide item 1, then integrate or continue per the manual relay.
