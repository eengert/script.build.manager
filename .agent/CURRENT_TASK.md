# Current Task

## Idle — awaiting BM-007 assignment

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Idle — BM-006 merged to `matrix` (`70504e0`)

### Deliverables (BM-006)

- `resources/lib/planner.py` — desired-vs-actual planner
  - Public API: `plan_changes(desired: ResolvedBuild, actual: KodiState) -> Plan`
  - Errors: `PlanningError`
  - Types: `Plan` (frozen), `PlanAction` (frozen)
  - Action kinds: `INSTALL_REPOSITORY`, `INSTALL_ADDON`, `ENABLE_ADDON`,
    `DISABLE_ADDON`, `ENSURE_ABSENT`, `SET_SKIN`, `CONFIGURE`
  - Deterministic ordering: repos→installs→enable/disable→absent→skin→config,
    lexical by addon_id within each category
  - Skin dedup: tracks `planned_install_ids` to prevent duplicate INSTALL_ADDON
  - Unmanaged add-ons: never emits ENSURE_ABSENT for unmentioned add-ons
  - Config: always `current_state="unchecked"` (BM-005 does not inspect config)
  - Stdlib only — no Kodi imports, no filesystem/network access
- `tests/test_planner.py` — 70 BM-006 tests

### Last Completed: BM-006 — Desired-vs-Actual Diff / Planner

Merged to `matrix` at `70504e0` (fast-forward from `6d41279`).
Tests: 444/444 passing (358 pre-BM-006 + 70 BM-006 + 16 correction).

### Next: BM-007

Not started. Scope to be assigned by supervisor.

### Prerequisites

- BM-001 merged to `matrix` ✓ (`5442f13`)
- BM-002 merged to `matrix` ✓ (`89039d6`)
- BM-003 merged to `matrix` ✓ (`a5d263e`)
- BM-004 merged to `matrix` ✓ (`2ad253f`)
- BM-005 merged to `matrix` ✓ (`6d41279`)
- BM-006 merged to `matrix` ✓ (`70504e0`)
