# Agent Handoff — BM-020A Codex worker

## Status

Codex remains the active worker on `agent/codex`, based on protected matrix
`e2458d4f977e09769b01d8e8a82635497b913546`. BM-020A implementation is complete
on the worker, but its required disposable production-executor gate is blocked
in preflight and has not been integrated to matrix. The external Agent Handoff
pointer was not changed.

BM-020A implementation commits are `1e29c23` and `213c9c0`. BM-020A adds the stable
`BuildManager.reconcile()` orchestration boundary and
typed `ReconcileRequest`, `ReconcileResult`, phase failures, ordered action
results, deterministic desired-state fingerprints, and aggregated BM-019
restart reports. It delegates to the existing manifest loader/resolver,
inspector, planner, dependency-aware installer, repository manager,
addon-state reconciler, skin activator, configuration manager, and BM-014
validator. The executor does not restart Kodi, persist transactions, resume
after restart, manage session identity, or acquire a process-wide lock.

BM-020A1 contracts remain intact: only `enabled`/`disabled` are managed,
omission is unmanaged, `absent`/`ENSURE_ABSENT` are rejected, dependency
ownership remains per install operation, explicit disabled required-dependency
conflicts fail before mutation, and nested BM-019 restart results propagate.

Added `validate-build-manager`, which invokes the real production
`BuildManager.reconcile()` inside disposable Kodi with the exact installed
`eric-main.example.json` / `family-room` request. The gate reached the
executor and returned structured `PREFLIGHT_FAILED` before planning or
mutation because `redlight-common` is absent from the installed package tree.
That package is intentionally unavailable under the deferred BM-016 Red Light
portability boundary; no fake package or reduced manifest was introduced.
Harness/relevant focused tests passed 1173/1173 and the full suite passed
1468/1468; `git diff --check` passed. The real Kodi profile was not accessed,
Apple TV and all devices remained untouched. BM-020B/C and BM-017 were not
started. Next step: supervisor decision on the package boundary; do not
integrate to matrix.
