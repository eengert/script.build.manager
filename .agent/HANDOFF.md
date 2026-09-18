# Agent Handoff — BM-014 Merged

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Status**: BM-014 + BM-014-correction merged to matrix. Project idle. BM-015 not started.

---

## What Was Done This Session

### BM-014-merge — Fast-forward matrix to bc0be68

Merged BM-014 (post-operation state validator) into `matrix` via fast-forward
push: `984debe → bc0be68`.

**Commits merged (5):**
| SHA | Message |
|-----|---------|
| `98272a9` | chore: record BM-013-merge complete |
| `588f829` | feat(BM-014): post-operation state validator |
| `fb1bc17` | chore: record BM-014 complete (1119/1119 tests, 19/19 live) |
| `903e78a` | fix(BM-014): closure root-scope check in dependency validator |
| `bc0be68` | chore: record BM-014-correction complete (1129/1129 tests, 19/19 live) |

---

## Architecture (BM-014)

### Public API

```python
validate_build_state(
    desired: ResolvedBuild,
    actual: KodiState,
    dependency_closure: Optional[DependencyClosure] = None,
) -> ValidationReport
```

### Validation domains (REPOSITORY → ADDON → DEPENDENCY → SKIN → CONFIGURATION)

**REPOSITORY** — `required=True` repos only  
**ADDON** — `enabled` / `disabled` / `absent` desired states  
**DEPENDENCY** — BM-012 DependencyClosure nodes  
**SKIN** — desired skin installed and active  
**CONFIGURATION** — NOT_CHECKED until BM-015  

### Dependency-root scope rule

`expected_roots` = addon_ids from `desired.addons` where `state == "enabled"`.

| Case | Condition | Result |
|------|-----------|--------|
| 1 | no expected roots | dep validation not applicable; return [] |
| 2 | expected roots + closure=None | NOT_CHECKED |
| 3 | closure root set exactly matches expected roots | validate nodes |
| 4 | empty/partial/unrelated closure | NOT_CHECKED (scope mismatch) |

Root ordering is irrelevant (set equality). Empty node list is valid when
`root_addon_ids` correctly covers expected roots.

### Dependency status mapping

- SATISFIED, SYSTEM → PASS
- OPTIONAL → skipped (no check)
- INSTALLED_DISABLED, MISSING, VERSION_INSUFFICIENT, METADATA_ERROR → FAIL
- CYCLE → WARNING

### Aggregate semantics

```
is_valid    = no FAIL
is_complete = no NOT_CHECKED
passed      = is_valid AND is_complete
```

WARNING alone does not prevent `passed=True`.

### Read-only guarantee

No xbmc/xbmcvfs imports, no mutation backend, no SetAddonEnabled, no
install/remove calls, no filesystem writes, no network access, no shell.

---

## Branch State

| Branch | SHA | Notes |
|--------|-----|-------|
| `matrix` | `bc0be68` | BM-014 merged ✓ |
| `agent/claude` | `bc0be68` | same as matrix |
| `agent/codex` | `a970e83` | intentionally stale, unchanged |

---

## Test Results

- **Unit tests**: 1129/1129 pass (run on agent/claude before merge)
- **Live validation (BM-014)**: 19/19 passed (Kodi 21.1 macOS, prior session)

---

## What Is NOT Done

- BM-015 not started

---

## Human Decision Required Before Next Step

None. Supervisor may plan and assign BM-015.

---

## Usage

Start: 5h 57% / wk 88% (claude-sonnet-4-6, max effort).
End: 5h 57% / wk 88%.
Delta: ~0% / 0%.
See USAGE_HISTORY.md for the appended row.
