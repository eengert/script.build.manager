# Test.app helper B3 cleanup correction — 2026-10-04

Status: correction complete offline; independent review pending. Do not self-approve.

## Identity and scope

- Worktree: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`.
- Branch: `agent/codex`; task-start HEAD: `a420a17ca7e7245a2558c9a5b27589b52ee926a6` (clean).
- Prior B1-B5 correction: `53454069a033fcdfc52dc96aa38e050eb13a7ee7`.
- Substantive B3 correction: `f47dc15cf9e43dd2e4612f38bbb97cacdb4d0323` (`tools/bm_test_app.py`, `tests/test_bm_test_app.py` only).
- Scope: preserve relocated staging state when pre-swap validation rejects an ancestor symlink. No Test.app preflight.

## Root cause and correction

- `_swap_in` rejected a replaced `Contents/Resources` ancestor with `bundle_path_symlink`, but `_remove_stage_area` checked only `.bm-stage` with `lstat_real_dir`. `rmtree` followed the ancestor symlink and deleted the relocated stage area.
- Cleanup now validates the full path chain before inspection and rechecks it immediately before `rmtree`. Unsafe or ambiguous chains return `False`; no symlink resolution is used, and the original stage error propagates.

## Reproduction and validation

- The disposable fake-bundle regression reproduced the old defect: immediately before swap, `Resources` was moved to a decoy, replaced with a symlink, and a sentinel was placed inside the relocated `.bm-stage`. The pre-swap rejection followed by legacy cleanup deleted the sentinel. The same test passes with the correction.
- After repairing the fake bundle path, a subsequent stage is blocked by retained `.bm-stage` with `stage_area_exists`; the sentinel remains intact.
- B3 regression: 1/1 pass. A targeted in-memory mutation restoring the old final-node-only cleanup caused the regression to fail on the deleted sentinel, as expected.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_bm_test_app`: 311/311 pass in permitted offline execution. The initial sandbox run could not bind disposable loopback servers or inspect test processes; no test isolation changes were made.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_bm023a_adapter`: 110/110 pass.
- `python3 -m py_compile tools/bm_test_app.py` and `git diff --check`: pass.
- Existing B1/B2/B4/B5 coverage passed in the helper suite. Accepted product files (`addon.xml`, `default.py`, `service.py`, `resources/`) match `8789329054b77815c6f9548fd4ce9beacbe1d348`.

## Boundaries and next step

- No real `/Applications/Kodi Build Manager Test.app`, normal Kodi, normal profile, or household device was accessed. No push, matrix integration, release, rebase, or reset.
- Next: independent review of only commit `f47dc15cf9e43dd2e4612f38bbb97cacdb4d0323` against task-start HEAD `a420a17ca7e7245a2558c9a5b27589b52ee926a6`. Eric must relay that review; no further implementation or live action is authorized by this task.
- No additional human input is needed before the independent review.
