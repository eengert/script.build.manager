# Handoff — Package summary correction and canonical handoff refresh

- State: COMPLETE; local commits only, not pushed.
- Start: `agent/claude` at `988509c`, clean, matching the expected state.
- Done:
  - summaries (en_US and en_GB) changed from "Save and restore your Kodi setup." to "Capture and apply a managed Kodi setup." (`5f0dd67`);
  - `tests/test_addon_metadata.py` extended with a summary test asserting exact wording and rejecting "restore" and "backup"; the new test fails on both locales against the prior summary (checked in a scratch copy);
  - `.orchestrator/HANDOFF.md` rewritten as a current checkpoint (`6c57cc5`).
- Tests: `tests.test_addon_metadata` 4/4 pass. XML parse and `xmllint` pass. `git diff --check` clean. No full suite (text and metadata only).
- Live-proven: nothing new. The metadata commits (`6105282`, `5f0dd67`) are not staged in Test.app. The installed candidate is still `53f2219`.
- Not done: no Test.app, Kodi, profile, device, MCP, push, or Agent Handoff activity; no `matrix` change; version unchanged.
- Out of scope, still open: the pre-existing `test_ui_foundation.NativeFoundationTests.test_no_engine_imports` failure (flags `resources/lib/ui/plan_view.py`), reproduced on a clean HEAD export earlier.
- Human input required: see "Remaining beta/package blockers" and "Next step" in `.orchestrator/HANDOFF.md`. In short: icon artwork authority, whether to stage the metadata in Test.app (needs a named task), and when to integrate into `matrix`.
- Smallest next step: ChatGPT selects the next bounded task.
