# Agent Handoff — BM-020A Codex worker

## Status

Codex remains the active worker on `agent/codex`, based on protected matrix
`e2458d4f977e09769b01d8e8a82635497b913546`. BM-020A is complete on the worker
and has not been integrated to matrix. The external Agent Handoff pointer was
not changed.

BM-020A adds the stable `BuildManager.reconcile()` orchestration boundary and
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

Focused executor tests passed 5/5 and the full suite passed 1467/1467;
`git diff --check` passed. The disposable harness exposes no BM-020A executor
live-validation command, so no live gate was claimed. The real Kodi profile,
Apple TV, and all devices remained untouched. BM-020B/C and BM-017 were not
started. Next step: supervisor review; do not integrate to matrix.
