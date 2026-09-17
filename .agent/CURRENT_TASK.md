# Current Task

## BM-004 — Profile Merge / Inheritance

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Complete — awaiting supervisor review and merge to `matrix`

### Deliverables

- `resources/lib/resolver.py` — profile resolver
  - Public API: `resolve_manifest(manifest, device_profile_id) -> ResolvedBuild`
  - Error: `ManifestResolutionError`
  - Output type: `ResolvedBuild` (frozen dataclass)
  - Merge order: base → platform → device → optional groups
  - No new runtime dependencies (stdlib only)
- `tests/test_manifest_resolver.py` — 78 BM-004 tests (all passing)
- `docs/MANIFEST.md` — optional-group deduplication rule documented, open question #5 closed

### Out of scope (BM-005+)

- Platform / device auto-detection
- Kodi state inspection
- Diff / planner
- Private overlay loading
- Add-on installation, config deployment, skin activation

### Prerequisites

- BM-001 merged to `matrix` ✓ (`5442f13`)
- BM-002 merged to `matrix` ✓ (`89039d6`)
- BM-003 merged to `matrix` ✓ (`a5d263e`)
