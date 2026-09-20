# Current Task

## Synchronized worker state

**Status**: BM-020A1 is complete, supervisor-approved, and integrated on
`matrix`. Codex is synchronized, idle, and ready for the next supervisor
assignment. BM-020A, BM-020B, and BM-020C have not started; no new milestone
has begun.

Current matrix: `e2458d4f977e09769b01d8e8a82635497b913546`.

BM-020A1 established the supported add-on contract (`enabled`/`disabled`, with
omission unmanaged and `absent` rejected), removed `ENSURE_ABSENT`, and made
each target install operation own required dependency preflight and
reconciliation. Explicitly disabled required dependencies fail closed before
mutation, optional dependencies remain optional, and nested install results
propagate BM-019 restart requirements.

BM-019, BM-018D, and BM-018E remain complete and integrated. BM-020A owns the
future production executor; BM-020B/C remain deferred.

Focused integrated tests passed 988/988; the full suite passed 1462/1462. The
real Kodi profile, Apple TV, and all devices remained untouched.
