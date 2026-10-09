# Handoff — Platform-provided bundled add-on core, Phase 1 (pending independent review)

- State: Phase-1 core semantics committed for independent review. **Not claimed CLOSED.** Acceptance criteria 1–20 self-verified; nothing pushed; `matrix` untouched. Item 8 and restart/resume remain OPEN. Publication stays unauthorized.
- Start: `agent/claude` at `20b5477`, worktree clean. Expected starting HEAD matched.
- Commits (local, unpushed):
  - `d1ebfa0` — D-028 guidance only (`.orchestrator/DECISIONS.md`).
  - `bddbe6f` — product plus tests (`resources/lib/{build_manager,create_capture,create_workflow,dependencies,frozen,frozen_install,frozen_resolution,plan,status}.py`; `tests/{test_build_manager,test_create_capture,test_create_workflow,test_dependencies,test_frozen,test_frozen_install,test_frozen_resolution,test_plan,test_status}.py`).
  - This bookkeeping commit — `.agent/**` only.
- Design implemented:
  - Capture classifies origin in the same trusted-root read that obtains addon.xml (`InstalledMetadata`: HOME or APPLICATION). Platform nodes are recorded without acquisition, install, enable or disable.
  - Frozen manifest schema 2 is emitted only when a platform node exists. Schema 1 bytes and fingerprints are unchanged (pinned in tests).
  - One read-only verifier runs before any mutation, and again on resume and before COMPLETE. It fails closed on absence, home shadow, broken, disabled, unreadable or unverifiable metadata, insufficient or unparseable versions, an undeclared type, and unrepresented dependencies. Builtin minima need Kodi evidence.
- Test results:
  - RED (before product changes, 20b5477 plus RED tests): 366 run, 39 failing. Detail in `.qualification-evidence/platform-provided-core-20261009/PRE-FIX-RESULTS.txt`.
  - Final focused, python3 3.10.9: 791 candidate vs 739 parent for the twelve modules, with only the baseline ImportPolicy failure.
  - Apple `/usr/bin/python3` 3.9.6, same twelve modules: 832 run, 1 failure and 1 error. Both reproduce identically on the parent (the baseline ImportPolicy test, and the pre-existing `assertNoLogs`, which Python 3.9 lacks).
  - Full suite: candidate 3318 vs parent 3266. Failure identities are identical (2 failures, 4 keychain errors). Zero candidate-only failures. The parent's 5 skips are environmental (scratch export lacks reviewed commit 8789329).
- Live-proven vs unit-only:
  - Unit-tested and synthetic only. No Kodi, no Test.app, no normal Kodi, no devices, no private overlay, no PIL artifact, no PIL sourcing.
  - Not live-proven: builtin `xbmc.python` verification via `Addons.GetAddonDetails`; trusted application origin on a real Kodi; `Addons.GetAddons` path for bundled add-ons.
- Risks and human decisions before the next step:
  1. Independent review of `bddbe6f` is required before any CLOSED claim.
  2. A bundled active skin (for example `skin.estuary`, if application-bundled) stays selectable but is refused by capture as a platform root. Decide whether bundled skins become platform requirements with settings capture (Phase 2).
  3. Live proof needed for `xbmc.python` builtin evidence and for the trusted origin/type read on a real Kodi (no Test.app work was authorized here).
  4. Judgment calls in the implementation, for review: platform nodes require non-empty trusted dependency edges (so dependency-free bundled add-ons are refused); observed disabled or broken platform nodes block capture; incoming minima from optional edges also apply; type proof uses the add-on's own addon.xml extension point rather than an unverified `GetAddonDetails` "type" property; `schema_version` booleans are rejected.
  5. Plan preview and repository preparation fail closed for repository-current packages that depend on a platform node (no verified target version there).
- Usage row: appended to `.agent/USAGE_HISTORY.md` (start unknown; end from `get_usage`).
- Out of scope — noticed:
  - `test_create_workflow.test_private_sentinels_absent_from_staging_logs_and_errors` uses `assertNoLogs` (absent on Python 3.9). Pre-existing; not changed.
  - `test_plan.ImportPolicy` and `test_ui_foundation.NativeFoundationTests` fail on the parent too. Not changed.
- Smallest next step: independent review of `bddbe6f` (with `d1ebfa0`), with focus on the verifier and the schema-2 invariants.
- Phase-2 follow-ups (deferred presentation and wording, not built here): Plan row wording and a "Provided by Kodi" presentation; Status verified platform rows (currently uncheckable); Help text; localization; repository-preparation preview for platform-dependent packages; the bundled-skin decision.
