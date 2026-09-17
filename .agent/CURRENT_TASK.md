# Current Task

## Idle — awaiting BM-006 assignment

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Idle — BM-005 complete and merged to `matrix` (`6d41279`)

### Deliverables (BM-005)

- `resources/lib/inspector.py` — Kodi state inspector
  - Public API: `KodiStateInspector(backend=None).inspect() -> KodiState`
  - Convenience: `inspect_kodi_state() -> KodiState`
  - Error: `KodiInspectionError`
  - Types: `KodiState` (frozen), `InstalledAddon` (frozen)
  - Backend: `KodiBackend` (injectable), `KodiRuntimeBackend` (lazy xbmc)
  - Fail-closed: all add-on entry fields validated; duplicates rejected
  - No new runtime dependencies (stdlib only)
- `tests/test_kodi_inspector.py` — 67 BM-005 tests (58 original + 9 correction)

### Last Completed: BM-005 — Kodi/Platform State Inspector

Merged to `matrix` at `6d41279`. Tests: 358/358 passing.

### Next: BM-006 — Desired-vs-Actual Diff / Planner

Not started. Feeds from `ResolvedBuild` (BM-004) + `KodiState` (BM-005).

### Prerequisites

- BM-001 merged to `matrix` ✓ (`5442f13`)
- BM-002 merged to `matrix` ✓ (`89039d6`)
- BM-003 merged to `matrix` ✓ (`a5d263e`)
- BM-004 merged to `matrix` ✓ (`2ad253f`)
- BM-005 merged to `matrix` ✓ (`6d41279`)
