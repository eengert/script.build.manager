# Agent Handoff — BM-012-C Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude` @ `ef8f570` (ahead of matrix; not yet merged)
**Status**: BM-012-C complete. 958/958 tests. 18/18 live validation.

---

## What Was Done This Session

### BM-012-C — Three correctness corrections to dependency closure

**Files modified:**
- `resources/lib/dependencies.py` — three bug fixes + new types/helpers
- `tests/test_dependencies.py` — 26 new unit tests for all three issues

---

## Three Issues Fixed

### Issue 1 — Multi-path strongest minimum version consolidation

**Bug**: `_dfs` used `visited: Dict[str, DependencyNode]`. Once addon X was
processed via one required path (e.g., root A requires X>=1.0 → SATISFIED),
a later required path with a stronger requirement (root B requires X>=2.0)
was silently skipped. X stayed SATISFIED even though X=1.5 < 2.0.

**Fix**:
- `visited` changed from `Dict[str, DependencyNode]` to `Set[str]` (fully-traversed addon_ids)
- `result_map: Dict[str, DependencyNode]` replaces the flat `results` list; allows O(1) update
- `effective_min: Dict[str, str]` tracks the strictest min-version seen for each dep across all required paths
- When a dep already in `visited` is encountered from a second required path with a stronger requirement, `result_map[dep_id]` is updated in place from SATISFIED/INSTALLED_DISABLED → VERSION_INSUFFICIENT
- `_max_version_requirement(a, b)` helper: returns the stricter (higher minimum) of two version strings, parseable-beats-unparseable, commutative result
- `cycle_nodes: List[DependencyNode]` is separate; final nodes = sorted(result_map.values()) + cycle_nodes
- Classification is now traversal-order-independent

### Issue 2 — Malformed metadata fails closed

**Bug**: `_parse_requirements()` returned `[]` on `ET.ParseError`, indistinguishable from "valid addon with no deps". A root or installed dep whose addon.xml was malformed would silently appear to have no dependencies, allowing `all_required_satisfied=True` for an incomplete closure.

**Fix**:
- New `DependencyStatus.METADATA_ERROR = "metadata_error"` enum value
- New `_MetadataParseError` internal exception
- New `_parse_requirements_strict(xml_bytes)`: raises `_MetadataParseError` on malformed XML (vs empty bytes or no `<requires>` → returns `[]`)
- `_parse_requirements()` unchanged (backward compat; still returns `[]` on error)
- `_dfs` uses `_parse_requirements_strict` for installed dep sub-dep discovery; parse failure → reclassify dep as METADATA_ERROR
- `read_addon_xml` returning `None` for an installed dep → METADATA_ERROR (cannot determine sub-deps)
- Root's malformed xml → METADATA_ERROR node with `required_by=()` added to result_map
- `DependencyClosure.metadata_errors` property returns METADATA_ERROR nodes
- `all_required_satisfied=False` when any METADATA_ERROR nodes exist
- METADATA_ERROR nodes appear in `unresolved`

### Issue 3 — Backend infrastructure failure → METADATA_ERROR not MISSING

**Bug**: `_dfs` caught all `Exception` from `get_addon_details()` and converted to `None`, then recorded MISSING and attempted install. Infrastructure failure was indistinguishable from "addon not installed".

**Fix**:
- `DependencyBackend.get_addon_details()` contract updated: return `None` ONLY for "genuinely absent from Kodi's database"; raise `DependencyError` for infrastructure failure (JSON-RPC error, malformed response, Kodi unreachable)
- `_dfs` catches `DependencyError` specifically → METADATA_ERROR (no install attempt); catches any other `Exception` → METADATA_ERROR (fail closed)
- `KodiRuntimeDependencyBackend.get_addon_details()` updated: raises `DependencyError` on JSON decode error, infrastructure failure, malformed response; returns `None` only on JSONRPC "Not Found" / "error" key
- `FakeDependencyBackend` extended with `get_details_errors: Dict[str, Exception]`; when an addon_id is in the dict, `get_addon_details` raises it (simulates infrastructure failure in tests)

---

## Architecture Summary

Key structural change to traversal state in `resolve_closure` / `_dfs`:

**Before**: `visited: Dict[str, DependencyNode]`, `results: List[DependencyNode]`
**After**: `visited: Set[str]`, `result_map: Dict[str, DependencyNode]`, `effective_min: Dict[str, str]`, `cycle_nodes: List[DependencyNode]`

The `result_map` allows re-classification of already-visited nodes when a
stronger requirement arrives from a second traversal path. `effective_min`
accumulates the strictest required version across all required edges to the
same dep. `cycle_nodes` holds back-edge records separately (a dep may appear
in both `result_map` as SATISFIED and `cycle_nodes` as CYCLE, which is the
correct behavior for shared-node cycles).

---

## Branch State

| Branch | SHA | Notes |
|--------|-----|-------|
| `matrix` | `5bc6325` | BM-012 not yet merged |
| `agent/claude` | `ef8f570` | BM-012 + BM-012-C complete |
| `agent/codex` | `a970e83` | intentionally stale, unchanged |

---

## Test Results

- **Unit tests**: 958/958 pass (932 baseline + 96 BM-012 + 26 BM-012-C = 958 total... wait, the baseline 932 already included BM-012's 96. Total: 836 + 96 + 26 = 958)
- **Live validation**: 18/18 passed (Kodi 21.1 macOS, disposable .kodi-test)

---

## What Is NOT Done

- BM-012 / BM-012-C not yet merged to `matrix`
- BM-013 not started

---

## Human Decision Required Before Next Step

None outstanding. The supervisor can:
1. Merge `agent/claude` → `matrix` (BM-012 + BM-012-C together)
2. Proceed to BM-013 planning

---

## Risks

None new. BM-012-C is additive: no previously passing tests broken; three bugs closed; live proof obtained.

---

## Out of Scope — Noticed

(Carried from BM-012 handoff)
- `_HttpAddonBackend._resolve_package_url()` in `tools/kodi_test.py` does not sort `repo_ids`. Single-repo test isn't affected. Note for future harness work.

---

## Usage

Start: 5h 83% / wk 77% (claude-sonnet-4-6, max effort).
End: 5h 96% / wk 79%.
Delta: +13% / +2%.
See USAGE_HISTORY.md for the appended row.
