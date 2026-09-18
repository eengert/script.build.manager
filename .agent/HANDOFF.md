# Agent Handoff — BM-014 Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude` @ `588f829`
**Status**: BM-014 complete. 1119/1119 tests. 19/19 live. BM-015 not started.

---

## What Was Done This Session

### BM-014 — Post-Operation State Validator

Implemented `resources/lib/validator.py` — a deterministic, read-only validator
that answers "does observable Kodi state match the resolved desired Build Manager
state?"

**Public API:**
```python
validate_build_state(
    desired: ResolvedBuild,
    actual: KodiState,
    dependency_closure: Optional[DependencyClosure] = None,
) -> ValidationReport
```

---

## Architecture

### Types

| Type | Role |
|------|------|
| `ValidationStatus` | `PASS`, `FAIL`, `WARNING`, `NOT_CHECKED` |
| `ValidationDomain` | `REPOSITORY`, `ADDON`, `DEPENDENCY`, `SKIN`, `CONFIGURATION` |
| `ValidationCheck` | Per-check result: domain, subject, status, expected, actual_state, reason |
| `ValidationReport` | Aggregate: checks tuple + is_valid, is_complete, passed, passes, failures, warnings, not_checked |
| `ValidationError` | Raised on malformed input (e.g. duplicate addon_ids in KodiState) |

### Validation domains (in output order)

**REPOSITORY** — `required=True` repos only:
- installed+enabled → PASS; missing → FAIL; disabled → FAIL
- `required=False` repos: no check emitted

**ADDON** — each `desired.addons` entry:
- `"enabled"`: installed+enabled=PASS, disabled or missing=FAIL
- `"disabled"`: installed+disabled=PASS, enabled or missing=FAIL
- `"absent"`: not installed=PASS, installed (any)=FAIL
- Unknown state → FAIL; unmanaged add-ons → silently ignored

**DEPENDENCY** — `DependencyClosure` nodes (lexical order):
- SATISFIED, SYSTEM → PASS; OPTIONAL → skipped (no check)
- MISSING, VERSION_INSUFFICIENT, METADATA_ERROR, INSTALLED_DISABLED → FAIL
- CYCLE → WARNING (reason includes cycle path)
- No closure + non-empty desired.addons → single NOT_CHECKED

**SKIN** — `desired.skin` if non-None:
- installed+active → PASS; installed but wrong active → FAIL; not installed → FAIL
- desired.skin=None → no check

**CONFIGURATION** — `desired.config` if non-None:
- Emits NOT_CHECKED (BM-015 deferred)
- desired.config=None → no check

### Aggregate semantics

```
is_valid    = no FAIL checks
is_complete = no NOT_CHECKED checks
passed      = is_valid AND is_complete
```

WARNING alone does not prevent `passed=True`.

### Read-only guarantee

The module has no xbmc imports, no filesystem writes, no network calls, no
shell execution, no mutation backend. Operates on immutable snapshots only.

### Determinism

Domain order: REPOSITORY → ADDON → DEPENDENCY → SKIN → CONFIGURATION.
Within each domain: lexical by subject/addon_id.

---

## Files

| File | Status | Notes |
|------|--------|-------|
| `resources/lib/validator.py` | new | main BM-014 module |
| `tests/test_validator.py` | new | 72 unit tests |
| `tools/kodi_test.py` | modified | BM-014 constants, ZIPs, addons.xml, _HttpKodiStateBackend, validate_post_operations() 19-step |
| `docs/TESTING.md` | modified | new test row + validate-post-operations section |
| `.agent/CURRENT_TASK.md` | modified | updated to BM-014 |
| `.agent/USAGE_HISTORY.md` | modified | BM-014 row appended |

All changes committed as `588f829` and pushed to `agent/claude`.

---

## Branch State

| Branch | SHA | Notes |
|--------|-----|-------|
| `matrix` | `984debe` | BM-013 merged; unchanged |
| `agent/claude` | `588f829` | BM-014 complete ✓ |
| `agent/codex` | `a970e83` | intentionally stale, unchanged |

---

## Test Results

- **Unit tests**: 1119/1119 pass (1047 pre-BM-014 + 72 new)
- **Live validation (BM-014)**: 19/19 passed (Kodi 21.1 macOS, disposable .kodi-test)

### Live sequence proven

| Step | Result |
|------|--------|
| 1. Reset + install + configure | ✓ |
| 2. Build ZIPs + start HTTP server | ✓ |
| 3. Launch + wait for ready | ✓ |
| 4. Pre-conditions (not installed) | ✓ |
| 5. Install test repo | ✓ |
| 6. Repo enabled=True verified | ✓ |
| 7. bm014-enabled installed+enabled | ✓ |
| 8. bm014-disabled installed then set disabled | ✓ |
| 9. KodiState inspected (33 addons, skin.estuary) | ✓ |
| 10. Dependency closure resolved (xbmc.python→SYSTEM) | ✓ |
| 11. ResolvedBuild constructed | ✓ |
| 12. validate_build_state → PASS (5 PASS, 0 FAIL) | ✓ |
| 13. Drift injected (bm014-disabled→enabled) | ✓ |
| 14. KodiState re-inspected (drift reflected) | ✓ |
| 15. validate_build_state → FAIL on bm014-disabled | ✓ |
| 16. Drift repaired (bm014-disabled→disabled) | ✓ |
| 17. KodiState re-inspected (repair reflected) | ✓ |
| 18. validate_build_state → PASS (repaired) | ✓ |
| 19. Stop + real profile untouched | ✓ |

---

## What Is NOT Done

- BM-015 not started

---

## Human Decision Required Before Next Step

None. Supervisor can proceed to BM-015 planning.

---

## Risks

None. BM-014 is purely read-only. No Kodi state is mutated by the validator.

---

## Out of Scope — Noticed

(Carried from prior handoffs)
- `_HttpAddonBackend._resolve_package_url()` does not sort `repo_ids`. Single-repo
  test is unaffected. Note for future harness work.
- `_HttpAddonStateBackend.get_addon_details()` raises `AddonStateError` for ALL
  `RuntimeError` from `jsonrpc()`, including -32602. Not an issue in validate_addon_state()
  or validate_post_operations() (only installed add-ons queried). Note for future harness work.

---

## Usage

Start: 5h 46% / wk 87% (claude-sonnet-4-6, max effort).
End: 5h 46% / wk 87%.
Delta: ~0% / 0%.
See USAGE_HISTORY.md for the appended row.
