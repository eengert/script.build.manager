# Handoff — Custom icon adoption

- State: COMPLETE in source; local commits only, not pushed; not staged in Test.app.
- Start: `agent/claude` at `f97ca32`, clean. Live Agent Handoff (checked by the task prompt): claude current; codex `67c0a9e` clean, ahead; claude clean, ahead.
- Done:
  - `resources/images/icon.png` replaced with the exact blob from `matrix:resources/images/icon.png` (added by `a33a3f8`), by writing the blob bytes directly. Nothing else was copied, merged, or re-encoded (`a2b1ffc`).
  - `tests/test_addon_metadata.py` pins addon.xml's icon path, the PNG signature and 512x512 dimensions, and the exact SHA-256 (standard library only).
  - `.orchestrator/HANDOFF.md` records the blocker as closed in source and restores the live status command (`ed0bf60`).
- Tests: `tests.test_addon_metadata` 5/5 pass. The icon test fails on the old icon (SHA `b908af84...`). XML parse and `xmllint` pass. `tests.test_repository` and `tests.test_ui_foundation` pass except the pre-existing `test_no_engine_imports` failure. `git diff --check` clean.
- Live-proven: nothing new. The icon, the summary, and the metadata are not staged or run in Test.app.
- Not done: no Test.app, Kodi, profile, device, push, release, Agent Handoff, or matrix activity; no full product suite (asset-only change).
- Out of scope, still open: the pre-existing `test_ui_foundation.NativeFoundationTests.test_no_engine_imports` failure (flags `resources/lib/ui/plan_view.py`).
- Human input: none needed for this step. The next live-proof and matrix-integration decisions are listed in `.orchestrator/HANDOFF.md`.
- Smallest next step: ChatGPT selects a bounded task for live staging of the package, if wanted.
