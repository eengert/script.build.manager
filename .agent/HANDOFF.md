# Agent Handoff — BM-020A1

## Status

BM-020A1 is complete on `agent/codex` and awaits supervisor review. The worker
identity remains Codex; no Codex-to-Antigravity handoff has occurred. BM-020A
production executor work, BM-020B/C, BM-017, and later milestones were not
started.

## What changed

- The supported manifest contract is `enabled` / `disabled`; omitted add-ons
  are unmanaged. `absent` now fails manifest validation with an actionable
  public-Kodi-API limitation message, and `ENSURE_ABSENT` was removed from the
  planner and dead tests/docs.
- `DependencyAwareInstaller` owns the target install's required dependency
  preflight and reconciliation. It detects explicitly disabled required
  dependencies before mutation, stops before target installation on any
  dependency failure, preserves optional dependency semantics, and returns a
  nested aggregate result.
- `AddonInstallResult.restart_requirement` now propagates through
  `DependencyAction`, `DependencyResult`, and the enclosing install result via
  BM-019's existing typed restart aggregation.

## Validation and boundaries

Focused tests: 711/711. Full suite: 1462/1462. `git diff --check`: passed.
No live disposable dependency gate was required by this prerequisite, and no
real Kodi profile, Apple TV, matrix branch, or other worker branch was touched.

## Next step

Supervisor review. If approved, integrate this worker change normally to
`matrix`; do not start BM-020A until separately authorized.
