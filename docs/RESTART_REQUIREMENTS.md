# Restart Requirements — BM-019

BM-019 establishes the typed handoff between reconciliation operations and the
future restart/resume executor. It detects and reports a required lifecycle
action; it does not restart Kodi, persist a transaction, or resume a partial
build. Those behaviors belong to BM-020.

## Contract

`resources.lib.restart.RestartRequirement` is the machine-readable contract:

| Value | Meaning |
|---|---|
| `NONE` | The successful reconciliation requires no Kodi restart. |
| `KODI_RESTART` | A successful changed operation requires Kodi restart handling. |

The enum is intentionally limited to lifecycle actions currently needed by the
implementation. A new level must be justified by a real operation before it is
added.

Each operation result carries a local `restart_requirement` declaration. The
existing result types expose the typed declaration through a `restart_report`:

- repository installation;
- add-on installation;
- dependency reconciliation;
- skin activation; and
- configuration deployment.

The planner remains non-mutating and does not predict a final restart from an
action kind. The operation that owns the behavior reports what actually
happened, and orchestration aggregates those reports with
`RestartAggregator`/`aggregate_restart_reports()`.

## Aggregation and idempotency

Aggregation is monotonic: `NONE + KODI_RESTART` is `KODI_RESTART`, and later
`NONE` results cannot downgrade an earlier requirement. Only a successful
operation that reports an actual change contributes its declared requirement.
An already-correct or otherwise no-change operation contributes neither a
change nor a restart requirement.

`RestartReport.to_dict()` preserves the typed enum value as `none` or
`kodi_restart` and also reports successful-change and failed-operation counts.
Human-readable text is derived from that typed value rather than serving as the
primary API.

## Failure semantics

A failed operation is counted in the report but does not establish a restart
requirement. This matches the current result contracts: failed operations are
not committed reconciliation results, and no existing manager exposes a
rollback-committed marker. If an implementation has made an unverified partial
write, the reconciliation is incomplete and must be repaired or retried before
BM-020 acts on restart metadata.

An earlier successful changed operation is never erased by a later failure, so
the final report remains actionable while still exposing the failure count.

## Current milestone boundary

BM-018D/BM-018E typed AF3 setting deployment, AF3 activation, and the JSON-RPC
persistence compatibility path currently report `NONE`; the compatibility
fix does not require a restart. No current operation legitimately emits
`KODI_RESTART`, so BM-019 validates the framework with unit/integration tests
and does not invent a live restart scenario. BM-020 owns persistence of
transaction progress, Kodi restart execution, and deterministic continuation.
