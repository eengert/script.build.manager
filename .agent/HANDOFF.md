# BM updater-policy malformed verification correction — 2026-10-05

Status: correction complete offline; narrow independent review pending. Do not
self-approve.

## Identity and scope

- Worktree: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`.
- Branch: `agent/codex`; task-start HEAD `f27270039d668d727cc2c54869bbc0bfd4c584c5` (clean).
- Reviewed candidate before correction: `8ad6aaeb878b0cefc8198c6124107b93e9865c88`.
- Correction commit: `4a02b833178f5cb29e2b596985f1a8641ed3fa25` (`resources/lib/update_guard.py`, `tests/test_update_guard.py`, `tests/test_frozen_install.py`, and `tests/test_resume.py`).
- Scope: reject malformed updater-policy representations before they can authorize post-restart continuation.

## Reproduction and correction

- Before the fix, the actual `KodiJsonRpcUpdatePolicyBackend` plus `AddonUpdateGuard.verify_quarantined()` accepted `2.9`, `2.01`, `2.0`, `"2"`, and `b"2"` as `NEVER_CHECK`. The `run_startup` regression showed `2.9` invoking BM-020 resume and returning `RESUME_COMPLETE`.
- `_coerce_policy` now accepts only the existing `AddonUpdatePolicy` enum object or an exact built-in integer, then validates the enum value. Other representations raise updater-state-unavailable through verification. No setter path was added or changed.
- Coverage includes exact integers 0/1/2; fractional values, numeric string/bytes, booleans, `None`, NaN/infinities, containers, and arbitrary objects; no malformed API response calls the setter. Startup tests verify `2.9` blocks resume, marks the frozen transaction for attention while preserving its activation hold, leaves BM-020 untouched, and makes zero setter calls. Exact integer `2` still permits the verify-only startup continuation.
- The pre-fix regressions failed as expected. An in-memory mutation restoring `int(value)` caused the new JSON-RPC and startup regressions to fail again.

## Validation

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_update_guard tests.test_frozen_install tests.test_resume`: 84/84 passed.
- Initial full-suite run under the restricted sandbox had 8 failures and 11 errors from blocked process listing and loopback binds in unrelated helper tests. The same unchanged offline suite was rerun with permitted process/loopback access: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -q`, 2405/2405 passed.
- `python3 -m py_compile resources/lib/update_guard.py tests/test_update_guard.py tests/test_frozen_install.py tests/test_resume.py`: passed.
- `git diff --check`: passed. Product correction commit contains only the four scoped source/test files.

## Boundaries and next step

- No Test.app, Kodi runtime, normal profile, or device was accessed or mutated. No updater setting was changed. No adapter/version, helper, graceful-quit, terminal restore, or recovery behavior was changed. No push, release, or integration was performed.
- Next: independent review of only `f27270039d668d727cc2c54869bbc0bfd4c584c5..4a02b833178f5cb29e2b596985f1a8641ed3fa25`. Eric should relay that review before further work. No human input is needed before that review.
