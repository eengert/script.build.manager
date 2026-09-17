# Current Task

## Idle — awaiting BM-010 assignment

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: BM-009 complete on `agent/claude`; pending supervisor review and merge to `matrix`

### Deliverables (BM-009)

- `tools/__init__.py` — empty; makes tools/ importable for tests
- `tools/kodi_test.py` — standalone disposable Kodi test harness
  - Commands: reset, install, configure, enable-webserver, launch, wait, stop,
    restart, inspect, status, validate
  - Isolation: HOME override → `.kodi-test/home/`; never touches real Kodi profile
  - Path safety: `verify_isolation()` before every mutating operation;
    `_inside()`, `_overlaps()` helpers; reset double-checks before rmtree
  - Process safety: `stop()` verifies PID belongs to Kodi before SIGTERM;
    zombie-aware wait via `_process.wait()` when we own the child
  - Install: copies only ADDON_INCLUDE subset (addon.xml, default.py, resources/)
  - Inspect: HTTP JSON-RPC queries (platform, version, skin, addons) — read-only
  - Validate: full 11-step live sequence (reset→install→configure→launch→wait→
    verify ping→verify addon visible→inspect→stop→confirm exit→confirm real
    profile untouched)
  - Webserver port: 8920 (distinct from Backup Pro's 8899)
  - Stdlib only — no runtime dependencies outside Python stdlib
- `tests/test_kodi_harness.py` — 74 unit tests (no real Kodi required)
  - PATH SAFETY: _inside, _overlaps, verify_isolation (7 isolation cases)
  - RESET: path safety guards
  - INSTALL: source validation, copy filtering, overwrite
  - PROCESS STATE: PID file, status, stop guards
  - COMMAND DISPATCH: 13 routing tests + error handling
  - READINESS: wait_for_ready (success, transient failure, timeout)
  - WEBSERVER: configure writes file, refuses if exists
  - CONSTANTS: sanity checks
- `docs/TESTING.md` — harness documentation
- `.gitignore` — added `.kodi-test/`

### Live Validation (BM-009)

All 11 steps passed against Kodi 21.1 on macOS (2026-09-17):
- platform=macos, kodi_version=21.1, active_skin=skin.estuary, addon_count=30
- script.build.manager visible (enabled=False — expected for freshly installed add-on)
- Real profile (`~/Library/Application Support/Kodi`) untouched ✓

### BM-007 / BM-008 Absorption

Both tasks are fully covered by earlier work:
- BM-007 desired-state model = BM-004 `ResolvedBuild`
- BM-007 operation planner = BM-006 `plan_changes()`
- BM-008 reconciliation loop tests = BM-006 test suite
No separate BM-007 or BM-008 implementation is needed.

### Test Totals

518/518 passing (444 pre-BM-009 + 74 new harness tests)

### Last Completed: BM-009 — Disposable Kodi Harness

On `agent/claude`; pending supervisor merge to `matrix`.

### Next: BM-010

Not started. Scope to be assigned by supervisor.

### Prerequisites

- BM-001 through BM-006 merged to `matrix` ✓
- BM-007, BM-008 absorbed by BM-006 ✓
- BM-009 on `agent/claude` ✓ (pending merge)
