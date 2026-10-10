# D-028 target closure correction — offline candidate

- Worktree/branch: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`, `agent/codex`.
- Verified clean start: `220a4da7d7c73ecb6dc98dc5723a1907e8b67e55`.
- Previous correction: `06bde801502395b6d0738e8757cf2b2c331b5314`.
- Narrow source correction: `9a77068455f9800bb381040458c0fbdcdc316f59`; bookkeeping committed separately.
- Advances demonstrated blockers to beta items 2, 3, 5, 6 and truthful user-facing Repair. No live or beta acceptance claimed.

## Reproduction and change

Before source edits, disposable R/P/C/Q fixtures reproduced successful installation
with Q missing, Plan `NO_CHANGES` and Healthy Repair. Final 18 regression tests
against the exact baseline archive produce 20 failed assertions, no errors.

Only `resources/lib/frozen_install.py` product code changed. Trusted target mandatory
edges now promote managed nodes and recursively traverse their captured mandatory
edges. Newly discovered platform nodes join the same verification pass; their own
trusted target edges continue promotion until the closure stops growing. Captured
incoming minima are checked after promotion, including minima imposed on platform
nodes inspected earlier. Optional edges are excluded from promotion.

The existing complete platform checks, graph cycle/order validation, preflight,
restart/resume and final completion callers use that same verifier. No schema,
fingerprint, artifact acquisition or configuration authority changed. D-003 and
previous trusted-root/platform mutation protections are preserved.

## Validation

- `tests.test_d028_target_closure`: 18 PASS; missing Q before any mutation; Plan
  blockers and no Healthy Repair; compatible closure/order; multiple alternating
  target/captured promotion levels; optional-only branches (including optional
  descendants of newly required managed nodes); nine platform health/authority/
  version/builtin faults; minima on previously verified nodes; target cycles;
  missing captured/target children; restart/resume and final-state loss.
- New plus existing `tests.test_d028_corrections`: 88 PASS.
- Exact baseline full: 3388 tests, 177.137s, 2 failures, 0 errors, 5 skips caused by
  absent Git history in the disposable archive. Those five historical-candidate
  tests all PASS in a baseline supplement using the archived helper and read-only
  history of the named worktree.
- Candidate full: 3406 tests, 178.212s, 2 failures, 0 errors, 0 skips.
- Failure identities AND causes match exact `220a4da` and retained `bddbe6f` evidence:
  `tests.test_plan.ImportPolicy.test_the_presentation_modules_import_no_engine` and
  `tests.test_ui_foundation.NativeFoundationTests.test_no_engine_imports`.
  Both concern unchanged `resources/lib/ui/plan_view.py` import assertions.
- Staged/source whitespace checks pass. No additional product failure observed.

## Evidence, limits and cleanup

Minimum compressed logs, baseline adapters, run summary and verified checksum
manifest retained at `.qualification-evidence/d028-target-closure-9a77068/`.
The previous `.qualification-evidence/d028-review-corrections-20261009-06bde80/`
is untouched. Unit/disposable fixture evidence only; independent re-review pending.
No Test.app, normal Kodi/devices, private data, platform artifact manufacture,
agent switch, matrix integration, push, release or history rewrite.

Cleanup: task-owned temporary source archive, adapters and disposable logs removed
from `/private/tmp`; retained evidence is the minimum supporting the unaccepted
correction. Pre-existing caches and evidence preserved; tests used
`PYTHONDONTWRITEBYTECODE=1`. STOP for independent correction-delta review.
