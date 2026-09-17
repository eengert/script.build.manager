# Current Task

## BM-002 — Manifest Schema v1

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Not started — awaiting task prompt from supervisor

### Scope

Define the v1 build manifest schema. See `BUILD_MANAGER_PROJECT_PLAN.md` §38
(BM-002 in the initial development backlog) and §3 (design philosophy: desired-
state, declarative, idempotent) and §7 (build definition layers).

**Expected deliverables** (subject to task prompt):
- Schema definition for a build manifest (JSON/YAML format TBD)
- Validation rules
- At least one example manifest

**Out of scope** (BM-003+):
- Manifest parser/loader implementation
- Profile inheritance logic
- Kodi state inspection
- Any Kodi mutation

### Prerequisites

- BM-001 merged to `matrix` ✓ (`5442f13`, 2026-09-17)
- Per §49: do not begin Kodi mutation until planner layer (BM-007) is stable
