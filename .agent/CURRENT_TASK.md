# Current Task

## BM-003 — Manifest Validation / Parser

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Complete — awaiting supervisor review and merge to `matrix`

### Deliverables

- `resources/lib/manifest.py` — loader, validator, typed representation
  - Public API: `load_manifest_file`, `load_manifest_json`, `validate_manifest`
  - Errors: `ManifestError`, `ManifestParseError`, `ManifestValidationError`
  - Dataclasses: `Manifest`, `BuildInfo`, `AddonEntry`, `Repository`, `SkinEntry`,
    `ManagedSettingScope`, `ConfigDeclarations`, `ProfileLayer`, `DeviceProfile`,
    `OptionalGroup`, `PrivateOverlayRef`, `RestartPolicy`
  - No runtime dependencies added (stdlib only)
- `tests/test_manifest_loader.py` — 127 BM-003 tests (all passing)
- `docs/MANIFEST.md` — updated runtime-validation note (stdlib, not jsonschema)

### Out of scope (BM-004+)

- Profile merge/inheritance logic
- Platform detection
- Any Kodi mutation

### Prerequisites

- BM-001 merged to `matrix` ✓ (`5442f13`)
- BM-002 merged to `matrix` ✓ (`89039d6`)
