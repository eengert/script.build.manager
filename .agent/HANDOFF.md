# Handoff

## Task / outcome
BM-UI-003C-HELPER-STABLE-BASELINE-CORRECTION: PASS offline. Removes stable-absence blocker to beta exit item 8; STOP for independent correction-delta review. Live-use clearance PENDING.

## Identity / changes
Branch agent/codex; start 16c6124b9c1188b95979fee78e0b35bf69b2e19b (clean; live Agent Handoff current agent codex). Substantive commit 24e0332c15eb27942f0901d405d7138af966d2c7; helper blob 35bf742047bbc7656634ab508cfef0ae61a4a096.
Changed only tools/bm_test_app.py, tests/test_bm_test_app.py, docs/BM_TEST_APP_HELPER.md, plus separate .agent bookkeeping.
Ordinary snapshot omits library and never calls census_build_library. --library-baseline enforces full not_running identity before reads, two independently opened/closed matching samples, then full not_running identity immediately before success. Fixed mismatch error build_library_state_changed. Reviewed projection/schema/read guard unchanged.

## Evidence
Before source edits, standalone disposable probes used supported BuildLibrary.register/select APIs: root absent, registry absent, selection absent each returned stale absent ok:true after writer ran before return. Present registry/selection changes also reproduced.
After correction, all five supported-writer transitions injected after first sample fail with build_library_state_changed; no successful stale projection. Separate probes reject process launches after sample 1 and sample 2; running baseline refuses before library opens; ordinary running snapshot performs zero library opens. Present empty registry/null selection opens exactly two registry/selection pairs. Envelope/private-overlay/Red Light addon-data/library-lock sentinels unread and absent from output. Fixture file path/byte sets unchanged. Scripts retained at /private/tmp/bm_baseline_probe.py and /private/tmp/bm_baseline_read_probe.py (disposable, not repository dependencies).
15 focused library tests PASS (4 added methods; all 11 existing tests preserved with explicit opt-in). Stable absent/empty/populated/no-selection/selected states match reviewed census, deterministic across repeated commands; bytes/mtime unchanged and no root/lock creation.
Full requested helper suite: 452 tests PASS in 89.945s with permitted escalation. Initial sandbox run: 452 tests, 8 failures / 11 errors due solely to denied ps / loopback binds; unchanged rerun passed, no tests weakened.
git diff --check PASS. Documentation states stopped/writer-free controller contract, limits against arbitrary host writers, and BM-UI-003C pre-staging/Preview-Cancel/post-Create stop-baseline sequences.

## Scope / next step
No product/shared-runtime changes, subagents, live Test.app staging/launch/snapshot/RPC/quit, real credentials/keychain/defaults, portable_data, normal Kodi/profile, devices, push/release/publication/matrix integration/history rewrite.
Not live-proven. Independent review of this correction; only after PASS restart BM-UI-003C Test.app qualification. Human relay required to obtain independent review; runtime qualification not restarted.
