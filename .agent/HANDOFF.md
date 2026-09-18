# Agent Handoff — BM-013-merge Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude` @ `984debe`
**Status**: BM-013-merge complete. `matrix` fast-forwarded to `984debe`. 1047/1047 tests.

---

## What Was Done This Session

### BM-013-merge — Fast-forward `matrix` through approved BM-013 history

**Method**: `git push origin agent/claude:matrix` (worktree-safe; `matrix` is
checked out in the main worktree at `/Users/eengert/Documents/Kodi/script.build.manager`
and cannot be switched in this worktree).

**Merge type**: fast-forward only. No squash, no rebase, no history rewrite.

**Commits merged** (5, all from `agent/claude`):
1. `b2a955f` feat(BM-013): enable/disable state reconciliation for managed add-ons
2. `6089b19` chore: record BM-013 complete (1040/1040 tests, 16/16 live)
3. `cbd3f4a` fix(BM-013): fail-closed enabled-field validation in KodiRuntimeAddonStateBackend
4. `984debe` chore: record BM-013-correction complete (1047/1047 tests)

(Note: `be1ed65` was the BM-012-merge tracking commit already on matrix from the prior task; the 4 listed above are the net new BM-013 commits.)

---

## Branch State

| Branch | SHA | Notes |
|--------|-----|-------|
| `matrix` | `984debe` | BM-013 merged ✓ |
| `agent/claude` | `984debe` | same tip |
| `agent/codex` | `a970e83` | intentionally stale, unchanged |

---

## BM-013 Summary (on matrix)

- `resources/lib/addon_state.py` — AddonStateReconciler, AddonStateBackend,
  KodiRuntimeAddonStateBackend, all status/result/info types
- `tests/test_addon_state.py` — 73 unit tests (66 original + 7 correction)
- `tools/kodi_test.py` — _HttpAddonStateBackend, validate_addon_state() 16-step,
  validate-addon-state command
- `docs/TESTING.md` — updated table, port table, validate-addon-state section

**Architecture invariants**:
- Managed scope only — unmanaged installed add-ons never queried/mutated
- `enabled` field must be an actual Python `bool`; malformed → AddonStateError
- Protected required dependencies cannot be disabled
- `xbmc.*` system add-ons unconditionally blocked
- Post-mutation verification re-reads Kodi state; mismatch → FAILED
- Idempotency: current == desired → ALREADY_CORRECT, no backend call
- Missing add-ons → MISSING; no installation attempted

---

## Test Results

- **Unit tests**: 1047/1047 pass
- **Live validation (BM-013)**: 16/16 passed (Kodi 21.1 macOS, disposable .kodi-test)

---

## What Is NOT Done

- BM-014 not started

---

## Human Decision Required Before Next Step

None. Supervisor can proceed to BM-014 planning.

---

## Risks

None. Merge was fast-forward; no history was altered. All prior tests still pass.

---

## Out of Scope — Noticed

(Carried from prior handoffs)
- `_HttpAddonBackend._resolve_package_url()` in `tools/kodi_test.py` does not
  sort `repo_ids`. Single-repo test isn't affected. Note for future harness work.
- `_HttpAddonStateBackend.get_addon_details()` raises `AddonStateError` for ALL
  `RuntimeError` from `jsonrpc()`, including -32602. In the harness this doesn't
  matter (only installed add-ons are queried in validate_addon_state()). Note for
  future harness work if needed.

---

## Usage

Start: 5h 31% / wk 84% (claude-sonnet-4-6, max effort).
End: 5h 31% / wk 84%.
Delta: ~0% / 0%.
See USAGE_HISTORY.md for the appended row.
