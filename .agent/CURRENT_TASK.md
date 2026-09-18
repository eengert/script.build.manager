# Current Task

## BM-013 — Enable/Disable State Reconciliation

**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude`
**Status**: COMPLETE — commit b2a955f, 1040/1040 tests, 16/16 live

### Goal

Provide a production primitive that makes the enabled state of explicitly
managed installed add-ons match the desired state. Managed scope only;
never touch unmanaged add-ons.

### Deliverables

- `resources/lib/addon_state.py` — new module
- `tests/test_addon_state.py` — new test file
- `tools/kodi_test.py` — add validate-addon-state command
- `docs/TESTING.md` — update table and add validate-addon-state section

### Constraints

- Do NOT start BM-014
- Work only on agent/claude
- Do not touch matrix or agent/codex
