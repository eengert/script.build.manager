# Agent Handoff — BM-012 Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude` (ahead of matrix; not yet merged)
**Status**: BM-012 implementation complete. Unit tests pass. Live validation ready to run.

---

## What Was Done This Session

### BM-012 — Dependency closure discovery and reconciliation

**Files created:**
- `resources/lib/dependencies.py` — production module
- `tests/test_dependencies.py` — 96 unit tests

**Files modified:**
- `tools/kodi_test.py` — BM-012 add-on ZIP makers, `_HttpDependencyBackend`, `validate_dependencies()` (18-step live sequence), `validate-dependencies` CLI command
- `docs/TESTING.md` — test table updated (BM-011 + BM-012 rows), `validate-addon` and `validate-dependencies` sections added
- `.agent/AGENT_STATUS.json` — BM-012 in_progress → complete
- `.agent/HANDOFF.md` — this file
- `.agent/USAGE_HISTORY.md` — BM-012 usage row appended

---

## Architecture Summary

### `resources/lib/dependencies.py`

**Public API:**
- `DependencyResolver(backend).resolve_closure(root_addon_ids)` → `DependencyClosure` — pure graph; reads addon.xml, classifies deps, no mutation
- `DependencyResolver(backend).reconcile_dependencies(root_addon_ids)` → `DependencyResult` — pure graph + iterative install/enable loop (up to `_MAX_RECONCILE_ROUNDS=10`)
- `KodiRuntimeDependencyBackend()` — production backend (lazy Kodi imports; delegates to `AddonManager(KodiRuntimeAddonBackend())` for install)
- `DependencyBackend` — abstract base for test fakes

**Key design decisions:**

**System deps**: `xbmc.*` → `SYSTEM`, never installed.

**Optional deps**: `<import optional="true">` → `OPTIONAL`, recorded but never installed or traversed. Traverse only required deps.

**Cycle detection**: DFS with `visiting` list (current path) + `visited` dict (fully processed). Cycle check precedes visited check so back-edges in a cycle are correctly detected even when the first occurrence is already in `visited`. Cycle nodes recorded with `cycle_path`; DFS continues other branches.

**Version semantics**: `installed >= required_min` (tuple int comparison); unparseable → conservative `True`; `VERSION_INSUFFICIENT` nodes are surfaced as unresolved, never upgraded.

**Iterative reconcile**: Each round calls `resolve_closure` + applies installs + enables. `acted_on` set prevents retrying failed add-ons. Stable when no new missing/disabled nodes remain (or max rounds exhausted).

**Additive-only**: `reconcile_dependencies()` never disables or removes any add-on. `set_addon_enabled()` is only called with `enabled=True`.

**Determinism**: roots sorted lexically; sub-deps sorted lexically by addon_id within each add-on; installs within a round sorted lexically.

### Live validation (`validate_dependencies()`, 18 steps)

Dependency graph:
```
plugin.video.bm012-root
  ├── script.module.bm012-a   (required, MISSING pre-reconcile)
  │     └── script.module.bm012-b   (required, discovered round 2)
  └── script.module.bm012-optional (optional="true" — never installed)
```

Reconcile rounds expected:
- Round 1: A is MISSING → install A (triggers Kodi restart)
- Round 2: A installed → B is MISSING → install B (triggers Kodi restart)
- Round 3: all satisfied → stable

Each installation uses `AddonManager(_HttpAddonBackend())` — same constrained package-install fallback as BM-011 production. Read_addon_xml reads from KODI_ADDONS_DIR filesystem (not via xbmcvfs). HTTP server on port 8922.

**Live validation not yet run** — requires running Kodi 21 with the disposable harness. Command:
```
python3 tools/kodi_test.py validate-dependencies
```

---

## Branch State

| Branch | SHA | Notes |
|--------|-----|-------|
| `matrix` | `5bc6325` | BM-011 merged (BM-012 not yet merged) |
| `agent/claude` | `<BM-012 commit>` | BM-012 complete |
| `agent/codex` | `a970e83` | intentionally stale, unchanged |

---

## Test Results

- 932/932 unit tests pass (836 baseline + 96 new BM-012 tests)
- Live validation: **not yet run** (requires disposable Kodi 21 environment)

---

## What Is NOT Done

- Live validation not run (BM-012 is unit-tested but needs live disposable Kodi confirmation)
- BM-012 not yet merged to `matrix`
- BM-013 not started

---

## Human Decision Required Before Next Step

None. The supervisor can either:
1. Run live validation (`python3 tools/kodi_test.py validate-dependencies`) and merge if it passes
2. Proceed to BM-013 if live validation is deferred

---

## Risks

- **Live validation has two Kodi restarts** during reconciliation (one per required dep installed). Total live validation time ~5-10 minutes.
- `_HttpDependencyBackend.install_addon()` creates a new `AddonManager(_HttpAddonBackend())` per call. Each call to `invoke_install()` triggers a Kodi restart. This is expected behavior in the harness (same as BM-011).

---

## Out of Scope — Noticed

- `_HttpAddonBackend._resolve_package_url()` in `tools/kodi_test.py` does not sort `repo_ids` (the BM-011 cleanup sorted this in production `addons.py` but not in the harness copy). Single-repo test isn't affected. Note for BM-013 or future harness work.

---

## Usage

Start: 5h 59% / wk 74% (claude-sonnet-4-6, max effort).
End: 5h 81% / wk 77%.
Delta: +22% / +3%.
See USAGE_HISTORY.md for the appended row.
