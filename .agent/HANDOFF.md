# D-028 final B1 pin-order correction — STOP for independent correction-delta re-review

Worktree: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`
Branch: `agent/codex`; starting HEAD `7fae62e349ddce25fa04c9420d798c5e705cf3cd`.
Product correction commit: `6147562f08d86f141772ee0156408b1cd02bb85d`.

## Correction

- `verify_builtin_requirement()` now initializes and retains `self._inventory()` before Kodi availability checks or any `xbmcaddon.Addon()` construction. The later application metadata proof uses that same initialized backend.
- Added one regression with a fresh backend and no prior inventory access. The first Addon construction replaces the application root with valid same-path metadata.
- Before the source correction, the regression failed as expected: verification returned `True`. Afterward, it returns `False`. Normal positive admission still succeeds.

## Validation

- Regression before correction: 1 test failed (`True is not false`), reproducing B1.
- Positive admission + B1 regression after correction: 2/2 PASS.
- D-028 builtin authority module: 34/34 PASS.
- Established seven-module D-028 focused set: 288/288 PASS.
- `git diff --check`: PASS.
- Full suite not run; no unexpected behavior was observed.

## Boundaries and next step

Only `resources/lib/frozen_install.py` and `tests/test_d028_builtin_authority.py` changed in the product commit. No Test.app, normal Kodi, device, integration, push, release, or history rewrite was performed. Next step: independent correction-delta re-review of this B1 fix. No additional human input is required before that review.

## Cleanup

The regression's temporary roots were removed by its test fixture cleanup. No new evidence files, screenshots, logs, or scratch trees remain. Existing qualification evidence was left untouched.
