# Current Task

## BM-003 — Manifest Validation / Parser

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Not started — awaiting task prompt from supervisor

### Scope (anticipated — subject to task prompt)

Implement the manifest loader and validator in Python. See
`BUILD_MANAGER_PROJECT_PLAN.md` §38 (BM-003) and `docs/MANIFEST.md` for the
schema reference and merge semantics.

**Expected deliverables** (subject to task prompt):
- Python manifest loader (load JSON from file or string)
- Structural validation against `resources/builds/schema-v1.json`
- Typed Python objects (dataclasses or similar) for engine consumption
- Path-traversal safety check on `managed_files` values
- Unit tests against `minimal.json`, `eric-main.example.json`, and invalid cases

**Dependencies**:
- `jsonschema` PyPI package — may be added as a runtime dependency in BM-003
  if supervisor approves; document in `addon.xml` if added

**Out of scope** (BM-004+):
- Profile merge/inheritance logic (semantics defined in `docs/MANIFEST.md`)
- Platform detection
- Any Kodi mutation

### Prerequisites

- BM-001 merged to `matrix` ✓ (`5442f13`)
- BM-002 merged to `matrix` ✓ (`89039d6`)
- Per §49: do not begin Kodi mutation until planner layer (BM-007) is stable
