# Agent Handoff — BM-011-C-final Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude`
**Status**: BM-011-C-final corrections complete. Awaiting supervisor review + merge to matrix.

---

## What Was Done

Two supervisor-mandated corrections applied to BM-011-C:

### Commit

- `500217f` — BM-011-C-final: redirect security + desired_state validation/enforcement

### Previous commits (still valid)

- `0eb8133` — BM-011-C: production direct package install (Option A)
- `c991dc4` — chore: record BM-011-C completion

---

## Issue 1 — Redirect Security (FIXED)

`_fetch_bytes()` previously used bare `urllib.request.urlopen()` which follows
redirects without validation. Fixed:

- Added `_SafeRedirectHandler(urllib.request.HTTPRedirectHandler)` to `addons.py`
  mirroring the BM-010 pattern exactly; raises `AddonInstallError` on:
  - non-http/https scheme (file://, ftp://, etc.)
  - embedded credentials (user:pass@host)
  - missing/invalid host
- Added `_build_safe_opener()` removing `FileHandler` (prevents file:// even on redirect)
- `_fetch_bytes` now uses `opener.open()` with `except AddonInstallError: raise`
  before `except Exception` to prevent re-wrapping
- urllib imports moved to top level

---

## Issue 2 — desired_state Validation and Enforcement (FIXED)

### Validation
`AddonManager.install()` now validates `desired_state in {"enabled", "disabled"}`
at the very top of the method, before addon_id validation or any backend call.
Any other value returns FAILED immediately with `desired_state` preserved in the result.

### Symmetric enforcement
Replaced asymmetric `if desired_state == "enabled" and not info.enabled: enable_addon()`
with symmetric: `if info.enabled != desired_enabled: set_addon_enabled(addon_id, desired_enabled)`.

All four cases handled correctly:
- desired enabled + discovered disabled → `set_addon_enabled(True)` → verify
- desired enabled + discovered enabled → no call
- desired disabled + discovered disabled → no call
- desired disabled + discovered enabled → `set_addon_enabled(False)` → verify

### API rename
`enable_addon(addon_id)` → `set_addon_enabled(addon_id, enabled: bool)` throughout:
- `AddonBackend` abstract base (addons.py)
- `KodiRuntimeAddonBackend` (addons.py)
- `FakeAddonBackend` (tests) — `enable_calls` → `set_enabled_calls: List[tuple]`,
  `enable_error` → `set_enabled_error`
- `_HttpAddonBackend` (kodi_test.py) — AddonBackend side only

**NOT renamed**: `_HttpRepositoryBackend.enable_addon` and
`KodiRuntimeRepositoryBackend.enable_addon` in kodi_test.py/repository.py —
those implement `RepositoryBackend` (BM-010) which is a separate interface.

---

## BM-013 Boundary (documented)

BM-011 is responsible only for finalizing the enabled state of an add-on it
just installed. BM-013 handles drift reconciliation for already-installed
add-ons. The docstring in `install()` now makes this explicit.

---

## Files Modified

| File | Change |
|------|--------|
| `resources/lib/addons.py` | Redirect handler + safe opener; desired_state validation; symmetric set_addon_enabled |
| `tests/test_addon_manager.py` | 24 new tests; FakeAddonBackend renamed; existing tests updated |
| `tools/kodi_test.py` | _HttpAddonBackend.set_addon_enabled; addon B; 19-step validation |

---

## Test Results

- **Unit tests**: 835/835 pass
  - New tests: TestSafeRedirectHandler (6), TestDesiredStateValidation (7),
    TestStateFinalizationSymmetry (8), TestSetAddonEnabledFails (5),
    updated TestKodiRuntimeBackend (+1), updated TestAddonBackendInterface
  - Baseline: 811/811 (BM-011-C) + 24 new = 835
- **Live validation**: 19/19 pass

---

## Live Validation Summary

| Step | Description | Status |
|------|-------------|--------|
| 1 | Reset disposable profile | ✓ |
| 2 | Install Build Manager + trigger script | ✓ |
| 3 | Configure web server | ✓ |
| 4 | Create test content + start HTTP server | ✓ |
| 5 | Launch Kodi + wait for ready | ✓ |
| 6 | Verify addon A NOT installed before action | ✓ |
| 7 | Install test repo via BM-010 | ✓ |
| 8 | Wait for Kodi to index test repo | ✓ |
| 9 | Verify addon A still NOT installed | ✓ |
| 10 | Install addon A desired_state='enabled' → INSTALLED | ✓ |
| 11 | Verify result.status == INSTALLED | ✓ |
| 12 | Verify GetAddonDetails: addon A enabled=True, version=1.0.0 | ✓ |
| **13** | **Install addon B desired_state='disabled' → INSTALLED** | **✓** |
| **14** | **Verify GetAddonDetails: addon B enabled=False** | **✓** |
| 15 | Restart Kodi | ✓ |
| 16 | Verify addon A enabled=True + addon B enabled=False after restart | ✓ |
| 17 | Install both again → ALREADY_INSTALLED (idempotency) | ✓ |
| 18 | Stop Kodi + HTTP server | ✓ |
| 19 | Confirm real Kodi profile untouched | ✓ |

### HTTP server log evidence (step 10 and 13):

```
[http:8922] "GET /addons.xml HTTP/1.1" 200 -
[http:8922] "GET /script.module.build-manager-test/1.0.0/script.module.build-manager-test-1.0.0.zip HTTP/1.1" 200 -
[http:8922] "GET /addons.xml HTTP/1.1" 200 -
[http:8922] "GET /script.module.build-manager-test-b/1.0.0/script.module.build-manager-test-b-1.0.0.zip HTTP/1.1" 200 -
```

Both addon A (enabled path) and addon B (disabled path) fetched from local server.
Step 13 proves `set_addon_enabled(False)` was called when Kodi discovered the addon
as enabled (Kodi 21 SyncInstalled default).

---

## What Is NOT Done

- BM-012 not started (dependency closure — explicitly out of scope)
- No merge to `matrix` (supervisor gate)

---

## Risks / Human Decisions Before Next Step

1. **Supervisor merge review**: Three files changed. Redirect handler and
   desired_state logic are the two targeted corrections from the supervisor brief.
2. **RepositoryBackend.enable_addon unchanged**: The BM-010 interface uses
   `enable_addon(addon_id)` (no `enabled` parameter). That interface was NOT
   renamed — it is correct as-is. The rename applies only to `AddonBackend`.

---

## Out of Scope — Noticed

- None.

---

## Usage

Start: 5h 52% / wk 72% (claude-sonnet-4-6, max effort).
End: 5h 52% / wk 72% (plan window did not advance measurably).
Delta: ~0% / ~0% (very low-cost session — well-scoped correction).
See USAGE_HISTORY.md for the appended row.
