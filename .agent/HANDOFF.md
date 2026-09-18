# Agent Handoff — BM-013 Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude` @ `b2a955f`
**Status**: BM-013 complete. 1040/1040 tests. 16/16 live. BM-014 not started.

---

## What Was Done This Session

### BM-013 — Enable/Disable State Reconciliation

Implemented `AddonStateReconciler(backend).reconcile(desired_states,
protected_dependency_ids)` — the production primitive that makes the enabled
state of explicitly managed installed add-ons match desired state.

**Files created/modified** (commit `b2a955f`):

| File | Status | Description |
|------|--------|-------------|
| `resources/lib/addon_state.py` | **new** | Main module: AddonStateReconciler, AddonStateBackend, KodiRuntimeAddonStateBackend, all types/errors |
| `tests/test_addon_state.py` | **new** | 66 unit tests (11 classes) |
| `tools/kodi_test.py` | modified | _HttpAddonStateBackend, 3 test ZIP helpers, validate_addon_state() 16-step, validate-addon-state command |
| `docs/TESTING.md` | modified | New row, port table, validate-addon-state section |

---

## Architecture

`AddonStateReconciler` is the pure-logic core; all Kodi communication is
injected via `AddonStateBackend`. Production uses `KodiRuntimeAddonStateBackend`
(lazy xbmc import); tests use `FakeAddonStateBackend`.

**Per-addon reconcile logic (lexical order; one failure ≠ stop)**:
1. Validate addon_id (regex `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$`) → FAILED
2. Validate desired_state ∈ {"enabled","disabled"} → FAILED
3. `addon_id.startswith("xbmc.")` → BLOCKED_SYSTEM, no backend call
4. `not desired_enabled AND addon_id in protected` → BLOCKED_REQUIRED_DEPENDENCY
   (checked BEFORE current-state read; fires even when already disabled — conflict report)
5. `get_addon_details()` → FAILED on AddonStateError, MISSING if None
6. `current.enabled == desired_enabled` → ALREADY_CORRECT, no mutation
7. `set_addon_enabled()` → FAILED on AddonStateError
8. `get_addon_details()` (verify) → FAILED on error/None/mismatch
9. Return ENABLED or DISABLED

**`all_correct`**: True only when all results ∈ {ALREADY_CORRECT, ENABLED, DISABLED}.

---

## Test Results

- **Unit tests**: 1040/1040 pass (`python3 -m unittest discover tests`)
  - Baseline: 974; BM-013 added: 66 (11 test classes)
- **Live validation**: 16/16 passed

### Live validation outcomes proven

| Step | Outcome | Proof |
|------|---------|-------|
| 10 | DISABLED | enabled→disabled mutation; Kodi API enabled=False ✓ |
| 11 | ALREADY_CORRECT | Second reconcile; no SetAddonEnabled call ✓ |
| 12-13 | BLOCKED_REQUIRED_DEPENDENCY | protected dep desired disabled; blocked ✓ |
| 14 | persistence | disabled state survives Kodi restart ✓ |
| 15 | ENABLED | disabled→enabled re-enable; all_correct=True ✓ |
| 16 | isolation | real profile mtime unchanged ✓ |

---

## Branch State

| Branch | SHA | Notes |
|--------|-----|-------|
| `agent/claude` | `b2a955f` | BM-013 complete ✓ |
| `matrix` | `3683b9a` | BM-012 merged; BM-013 not yet merged |
| `agent/codex` | `a970e83` | intentionally stale, unchanged |

---

## What Is NOT Done

- BM-013 merge to `matrix` — pending supervisor approval
- BM-014 not started (explicitly out of scope for this task)

---

## Human Decision Required Before Next Step

**Supervisor review required** before merging BM-013 to `matrix`.

Merge prerequisites (same as prior tasks):
1. Supervisor reviews commit `b2a955f` on `agent/claude`
2. Supervisor confirms no additional corrections required
3. Human-gated merge task (BM-013-merge) authorized

---

## Risks

None. All changes are isolated to new files plus additive extensions to
`kodi_test.py` and `docs/TESTING.md`. No existing production modules modified.
Backend interface is injectable; production `xbmc` import is lazy (no Kodi
required for unit tests or import).

---

## Out of Scope — Noticed

- `_HttpAddonStateBackend.get_addon_details()` in `tools/kodi_test.py` raises
  `AddonStateError` for ALL `RuntimeError` from `jsonrpc()`, including JSON-RPC
  -32602 (not-installed). The production backend returns `None` for -32602.
  This is a known harness simplification: the harness only queries installed
  add-ons in `validate_addon_state()`, so the distinction doesn't matter for
  the live tests. The MISSING path is tested exclusively via unit tests with
  FakeAddonStateBackend. Note for future harness work if needed.

---

## Usage

Start: 5h 28% / wk 84% (claude-sonnet-4-6, max effort).
End: 5h 28% / wk 84%.
Delta: ~0% / 0% (validation is runtime-only; no AI calls during live run).
See USAGE_HISTORY.md for the appended row.
