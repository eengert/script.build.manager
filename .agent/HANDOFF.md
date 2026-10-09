# Handoff — Bundled add-on capture correction and frozen completeness

- State: product correction committed for independent review: `b8d7a06` ("Read bundled add-on metadata from a trusted root and keep capture truthful"), local on `agent/claude`, not pushed. **Not claimed closed.** Independent review is required before the bundled-capture and completeness defects are accepted as closed. Item 8 and restart/resume stay OPEN. Publication stays unauthorized.
- Start: `agent/claude` at `e93b593`, worktree clean. Product source since the quiet-WAL correction was empty before this task.
- Accepted earlier: the Red Light quiet-WAL correction `e5a18a5` ("Read Red Light settings through a stable private copy") **passed independent review** and is CLOSED IN SOURCE. It is not reopened here.
- Defects corrected (see `.qualification-evidence/bundled-addon-capture-correction-20261009/`):
  - A. Installed `addon.xml` was read only from the home add-ons directory. Application-bundled add-ons such as `script.module.pil` 5.1.0 were reported unavailable, so their dependency edges were dropped and ordinary Create failed SOFTWARE_INCOMPLETE for a legitimate build.
  - B. `FrozenBuildCaptureResult.complete` checked only the manifest status. Capture errors could coexist with `COMPLETE`, so an unreadable `addon.xml` could yield a complete-looking graph with missing edges.
- Fix: `KodiInventoryBackend` takes an explicit `application_addons_dir` (`special://xbmc/addons`), configured by `runtime_create_workflow` and failing closed without an absolute root. Reported paths are trusted only when they name the requested add-on's own directory directly inside a configured root. Identifiers must be a single safe component. `addon.xml` is read anchored to the root with no link followed, from a regular file only. Captured installed `addon.xml` must match the inventory id and version. Unavailable metadata blocks like malformed metadata, and any capture error makes the manifest non-COMPLETE and `complete` False. Edges are never inferred from inventory RPC dependencies.
- Tests: 22 new (18 frozen capture and trusted-root, 2 ordinary Create, 2 runtime composition). Pre-fix reproduction failed on the starting source. The post-fix synthetic probe is correct on the affected Apple runtime.
- Focused modules pass on dev Python: test_frozen 27, test_create_capture 59, test_create_workflow 98. They also pass under Apple Python 3.9.6, except the pre-existing `assertNoLogs` error that the parent also has there.
- Full suite on dev Python: candidate `Ran 3256, FAILED (failures=2, errors=4)`; parent `e93b593` `Ran 3234, FAILED (failures=2, errors=4, skipped=5)`. Failing and erroring names are identical: 2 known import-policy failures and 4 known keychain errors.
- Not done: no Test.app staging or launch, no live Red Light database or private overlay access, no PIL sourcing or download or import, no push, no release, no publication, no Agent Handoff. The `KodiRuntimeDependencyBackend.read_addon_xml` fallback is unchanged. It fails closed and was out of scope.
- Known residual items (not blocking this task):
  1. Downstream ZIP-versus-recorded-edge defense is not added. It is a separate hardening layer.
  2. Identifier and trust checks are validated with synthetic fixtures only. Production behavior against real Kodi JSON-RPC path forms is not live-proven.
- Smallest next step: independent review of `b8d7a06`. Then the exact `script.module.pil` 5.1.0 artifact decision for the Item 8 fixture. Do not source 1.1.7, since the correct artifact is 5.1.0.

## Correction addenda (historical entries kept as written)

- The stopped Item 8 fixture record (`e-public-graph-summary.json`, `RUN-SUMMARY.md` in `item8-restart-resume-redlight-20261009`, and the earlier handoff) said `script.module.pil` was absent from Test.app. **That was a stopped-state probe limitation, not a true runtime fact.** The probe enumerated only the portable add-ons directory. Test.app's application bundle ships `script.module.pil` 5.1.0 under `Contents/Resources/Kodi/addons/`, and Red Light 2.6.8 requires `>= 1.1.7`, which 5.1.0 satisfies.
- The exact artifact still unavailable and pending is `script.module.pil` 5.1.0, not 1.1.7. It is to be sourced only after review of `b8d7a06` and under an explicit decision.
