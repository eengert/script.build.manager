# Current Task

## Synchronized worker state

**Status**: BM-019 is complete, supervisor-approved, and integrated on
`matrix`. Codex is synchronized, idle, and ready for the next supervisor
assignment. BM-020 has not started and no new milestone has begun.

Current matrix: `3b87bd394e7733636b74231c83853f577c596a71`.

BM-019 established typed `RestartRequirement` aggregation with `NONE` and
`KODI_RESTART`, monotonic aggregation of successful changed operations, and
JSON-safe reporting. Idempotent/no-change and failed/uncommitted operations do
not establish a requirement; later failures do not erase an earlier success.
The planner remains non-mutating and does not infer restart requirements from
action kinds. BM-020 owns restart execution, transaction persistence, and
resume/re-entry.

BM-018D and BM-018E remain complete and integrated, including the approved
16-setting `af3-common` package and typed skin persistence compatibility.

Focused BM-019 tests passed 813/813; the full suite passed 1476/1476. The real
Kodi profile and devices remained untouched. No BM-020 or other milestone work
has started.
