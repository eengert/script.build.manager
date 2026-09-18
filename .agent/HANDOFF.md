# Agent Handoff — BM-014-correction Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude`
**Status**: BM-014-correction complete. 1129/1129 tests. 19/19 live. BM-015 not started.

---

## What Was Done This Session

### BM-014-correction — Closure Root-Scope Check

Applied a narrow correctness fix to `_validate_dependencies()` in
`resources/lib/validator.py`.

**Problem**: The previous implementation accepted any non-None
`DependencyClosure` as complete, even when its `root_addon_ids` was empty or
covered unrelated add-ons. Three tests worked around this with
`DependencyClosure(root_addon_ids=(), nodes=())`, which was incorrect.

**Fix**:

1. Compute `expected_roots = frozenset(entry.addon_id for entry in desired.addons
   if entry.state == "enabled")`.
2. If `expected_roots` is empty → return [] (CASE 1: dep validation not applicable).
3. If `closure is None` → emit one `NOT_CHECKED` (CASE 2).
4. If `set(closure.root_addon_ids) != expected_roots` → emit one `NOT_CHECKED`
   describing the scope mismatch (CASE 4: wrong/empty roots).
5. Otherwise → validate nodes normally (CASE 3).
6. Removed "Configuration-management validation deferred." from the dep
   `NOT_CHECKED` reason string (that sentence belongs only in CONFIGURATION domain).

---

## Files Modified

| File | Change |
|------|--------|
| `resources/lib/validator.py` | `_validate_dependencies` rewritten with root-scope check |
| `tests/test_validator.py` | 11 node tests updated (added enabled addon + matching closure); 3 empty-closure workarounds replaced; 10 new tests in `TestDependencyClosureRootScope` (82 validator tests total) |
| `docs/TESTING.md` | test_validator.py count updated 72 → 82 |
| `.agent/USAGE_HISTORY.md` | BM-014-correction row appended |

---

## Test Results

- **Unit tests**: 1129/1129 pass (1047 pre-BM-014 + 82 validator tests)
- **Live validation (BM-014)**: 19/19 passed (Kodi 21.1 macOS, disposable .kodi-test)

Live sequence unchanged — the live closure is rooted at `plugin.video.bm014-enabled`
which is exactly the one enabled managed add-on in desired, so CASE 3 (roots match)
applies and all 5 checks remain PASS.

---

## Branch State

| Branch | SHA | Notes |
|--------|-----|-------|
| `matrix` | `984debe` | unchanged |
| `agent/claude` | `903e78a` | BM-014-correction ✓ |
| `agent/codex` | `a970e83` | intentionally stale, unchanged |

---

## What Is NOT Done

- BM-015 not started

---

## Human Decision Required Before Next Step

None. Supervisor may proceed to merge BM-014 + BM-014-correction to matrix,
then plan BM-015.

---

## Risks

None. Correction is narrowly scoped to `_validate_dependencies`. All other
domains unaffected. Read-only guarantee unchanged.

---

## Out of Scope — Noticed

(Carried from BM-014 handoff)
- `_HttpAddonBackend._resolve_package_url()` does not sort `repo_ids`.
- `_HttpAddonStateBackend.get_addon_details()` raises `AddonStateError` for
  all `RuntimeError` from `jsonrpc()`, including -32602.

---

## Usage

Start: 5h 55% / wk 88% (claude-sonnet-4-6, max effort).
End: 5h 55% / wk 88%.
Delta: ~0% / 0%.
See USAGE_HISTORY.md for the appended row.
