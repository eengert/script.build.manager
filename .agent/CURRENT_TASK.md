# Current Task

## BM-020A1 — supported action contract and dependency ownership

**Status**: Complete on `agent/codex`; supervisor review is the next gate.
BM-020A, BM-020B, BM-020C, BM-017, and all later milestones have not started.

Implemented the approved prerequisite scope:

- managed add-on states are only `enabled` and `disabled`; omitted add-ons are
  unmanaged, and `absent` is rejected before planning or mutation with an
  explanation that unattended removal is unsupported by Kodi's public API;
- removed the planner's `ENSURE_ABSENT` contract and updated schema, validator,
  manifest docs, planner tests, and project architecture notes;
- added `DependencyAwareInstaller`, which owns required dependency preflight,
  conflict detection, reconciliation, target installation, and one nested
  result; optional dependencies remain optional;
- required dependencies explicitly declared `disabled` fail before any
  dependency or target mutation; and nested add-on install restart requirements
  propagate through dependency actions/results and the enclosing result.

Validation: focused manifest/planner/dependency/add-on/restart tests passed
711/711; full suite passed 1462/1462; `git diff --check` passed. No disposable
Kodi or real-profile mutation was needed for this prerequisite; the real Kodi
profile and all devices remained untouched.

Smallest next step: supervisor review and, if approved, normal integration of
BM-020A1. Do not begin the BM-020A production executor in this task.
