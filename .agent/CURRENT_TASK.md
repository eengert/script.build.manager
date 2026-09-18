# Current Task

## BM-014 — Post-Operation State Validation

**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude`
**Status**: IN PROGRESS — implementation complete; live validation pending

### Goal

Implement a deterministic, read-only post-operation validator that answers:
"Does observable Kodi state match the resolved desired state?"

The validator MUST NOT repair, install, enable, disable, remove, download,
configure, restart, or edit any Kodi state. Read-only only.

### Deliverables

- `resources/lib/validator.py` — ValidationStatus, ValidationDomain,
  ValidationCheck, ValidationReport, validate_build_state(), ValidationError
- `tests/test_validator.py` — comprehensive unit tests (72 tests)
- `tools/kodi_test.py` — add validate-post-operations command (19-step)
- `docs/TESTING.md` — update table, add validate-post-operations section

### Constraints

- Do NOT start BM-015
- Work only on agent/claude
- Do not touch matrix or agent/codex
- BM-014 validator is STRICTLY READ-ONLY: no xbmc imports, no filesystem writes,
  no network calls, no shell, no mutation backend
