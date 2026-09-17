# Current Task

## BM-002 — Manifest Schema v1

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Complete — awaiting supervisor review

### Scope

Define the v1 build manifest format (data contract only). No parser, loader,
or validation Python in production code. No Kodi mutation. No new runtime
dependencies.

**Delivered**:
- `docs/MANIFEST.md` — full schema reference (layering model, merge semantics,
  field-by-field docs, security notes, open questions for BM-003/BM-004)
- `resources/builds/schema-v1.json` — JSON Schema Draft 7
- `resources/builds/examples/minimal.json` — minimal valid manifest (2 required fields)
- `resources/builds/examples/eric-main.example.json` — realistic example (AF3,
  Red Light, TMDb Helper, POV, Umbrella; tvos/android platform profiles;
  bonus-room/family-room/shield device profiles; optional groups; private
  overlay reference; no secrets)
- `tests/test_manifest_schema.py` — 47 new tests (schema file, minimal example,
  eric-main example, 16 invalid-case tests, BM-001 regression)

**Total tests**: 50/50 passing (3 BM-001 + 47 BM-002)

**Out of scope** (BM-003+):
- Production manifest loader/parser
- Profile merge/inheritance logic (`docs/MANIFEST.md` defines the semantics)
- Platform detection
- Any Kodi mutation
