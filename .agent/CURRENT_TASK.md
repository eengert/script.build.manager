# Current Task

## BM-020A production reconciliation executor

**Status**: BM-020A is complete on `agent/codex` and is not integrated on
`matrix`. BM-020B and BM-020C have not started; no new milestone has begun.

Current matrix: `e2458d4f977e09769b01d8e8a82635497b913546`.

BM-020A adds `resources/lib/build_manager.py` as the callable production
orchestration entrypoint. It accepts only a serializable manifest/device
request; loads, inspects, resolves, preflights, plans, executes through the
existing owners, validates read-only afterward, and returns ordered typed
action results plus a BM-019 `RestartReport`. Desired-state fingerprints are
canonical and exclude current state, private overlays, and raw configuration
values. Unknown actions and phase/action failures fail closed; execution stops
after the first failed action while preserving earlier results.

BM-019, BM-018D, and BM-018E remain complete and integrated. BM-020A owns the
the production executor; BM-020B/C remain deferred. The existing BM-020A1
enabled/disabled ownership and dependency-conflict contracts remain intact.

Focused executor tests passed 5/5; the full suite passed 1467/1467. The
disposable harness has no BM-020A executor validation command, so no live
executor gate was claimed. The real Kodi profile, Apple TV, and all devices
remained untouched. Next step: supervisor review; do not integrate to matrix.
