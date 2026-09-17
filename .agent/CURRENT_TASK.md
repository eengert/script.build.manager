# Current Task

## Idle — awaiting BM-005 assignment

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Idle — BM-004 complete and merged to `matrix` (`2ad253f`)

### Deliverables

- `resources/lib/resolver.py` — profile resolver
  - Public API: `resolve_manifest(manifest, device_profile_id) -> ResolvedBuild`
  - Error: `ManifestResolutionError`
  - Output type: `ResolvedBuild` (frozen dataclass)
  - Merge order: base → platform → device → optional groups
  - No new runtime dependencies (stdlib only)
- `tests/test_manifest_resolver.py` — 78 BM-004 tests (all passing)
- `docs/MANIFEST.md` — optional-group deduplication rule documented, open question #5 closed

### Last Completed: BM-004 — Profile Merge / Inheritance

Merged to `matrix` at `2ad253f`. Tests: 291/291 passing.

### Next: BM-005 — Kodi/Platform State Inspector

Not started.

### Prerequisites

- BM-001 merged to `matrix` ✓ (`5442f13`)
- BM-002 merged to `matrix` ✓ (`89039d6`)
- BM-003 merged to `matrix` ✓ (`a5d263e`)
- BM-004 merged to `matrix` ✓ (`2ad253f`)
