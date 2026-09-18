# Agent Handoff — BM-011 Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude`
**Status**: BM-011 complete. Awaiting supervisor review + merge to matrix.

---

## What Was Done

BM-011 is fully complete: production module, unit tests, and live validation all pass.

### Commits (this session)

- `08fd2de` — live validation fixes: Kodi 21 repo schema + headless install approach

### Previous commit

- `cdcaa2f` — production module `resources/lib/addons.py` + initial harness (from prior session)

---

## Files Created or Modified

| File | Change |
|------|--------|
| `resources/lib/addons.py` | NEW — production addon detection/install module |
| `tests/test_addon_manager.py` | NEW — 113 unit tests |
| `tools/kodi_test.py` | MODIFIED — BM-011 harness: HTTP server, trigger script, validate_addon(), schema fix, direct-extraction invoke_install |
| `tests/test_kodi_harness.py` | MODIFIED — 21 new harness tests |

---

## Test Results

- **Unit tests**: 760/760 pass
- **Live validation**: 17/17 steps pass (Kodi 21.1 macOS, disposable .kodi-test only)

---

## Key Technical Discoveries (for supervisor awareness)

### 1. Kodi 21 repository addon.xml schema change
The flat `<info>/<datadir>/<checksum>` format directly under `<extension point="xbmc.addon.repository">` was removed in Kodi 21. Elements MUST be wrapped in `<dir>`. Kodi logs:
> "Repository add-on … uses old schema definition … This is no longer supported, please update your addon to use `<dir>` definitions."

`_make_bm011_repo_zip()` now uses the `<dir>` schema with `zip="true"`.

### 2. Kodi 21's InstallAddon builtin requires interactive dialog
`InstallAddon(addon_id)` always shows a GUI confirmation dialog in Kodi 21. It cannot be driven headlessly:
- No `CAddonInstaller` log entry ever appears
- HTTP server never receives a ZIP download request
- Kodi logs multiple warnings: "uses plain HTTP for add-on downloads … if enabled!" (the "if enabled" refers to the HTTP download security gate, which is disabled by default)

**Production `KodiRuntimeAddonBackend` is correct**: it calls `InstallAddon` which shows the dialog to the real user in interactive Kodi use. The unit tests verify the method calls `executebuiltin('InstallAddon(...)')` correctly.

**Harness `_HttpAddonBackend.invoke_install`** uses direct extraction instead:
1. Download addon ZIP via `urllib.request` from port 8922
2. Extract to `KODI_ADDONS_DIR / addon_id`
3. Restart Kodi (`stop()` + `launch()` + `wait_for_ready()`)
4. Wait for addon in Kodi DB (FindAddons at startup)
5. `Addons.SetAddonEnabled(addon_id, True)` (SyncInstalled registers new addons as disabled=0)

### 3. Kodi 21 SyncInstalled registers new addons as disabled=0
Any addon newly discovered by FindAddons (on startup) is registered with `enabled=0`. Explicit `SetAddonEnabled(..., True)` is required for harness trigger script AND for test addon installation.

---

## Live Validation Summary

| Step | Description | Status |
|------|-------------|--------|
| 1 | Reset disposable profile | ✓ |
| 2 | Install Build Manager + trigger script | ✓ |
| 3 | Configure web server | ✓ |
| 4 | Create test content + start HTTP server | ✓ |
| 5 | Launch Kodi + wait for ready | ✓ |
| 6 | Verify test add-on NOT installed before action | ✓ |
| 7 | Install test repo via BM-010 (restart #1) + enable trigger + UpdateAddonRepos | ✓ |
| 8 | Wait for Kodi to index test repo | ✓ |
| 9 | Verify test add-on still NOT installed | ✓ |
| 10 | Install test add-on via AddonManager.install (restart #2) | ✓ |
| 11 | Verify result.status == INSTALLED | ✓ |
| 12 | Verify GetAddonDetails: enabled=True, version=1.0.0, files present | ✓ |
| 13 | Restart Kodi (restart #3) | ✓ |
| 14 | Verify add-on still installed + enabled after restart | ✓ |
| 15 | Install again → ALREADY_INSTALLED (idempotency) | ✓ |
| 16 | Stop Kodi + HTTP server | ✓ |
| 17 | Confirm real Kodi profile untouched | ✓ |

---

## What Is NOT Done

- BM-012 not started (explicitly out of scope)
- No merge to `matrix` (supervisor gate)

---

## Out of Scope — Noticed

- None.

---

## Risks / Human Decisions Before Next Step

1. **BM-011 merge review**: Supervisor should note that `_HttpAddonBackend.invoke_install` does NOT use `InstallAddon` (it can't headlessly). The production `KodiRuntimeAddonBackend` is correct; the harness approximates the install to enable end-to-end API testing.

2. **Future consideration**: If a future task requires validating that `KodiRuntimeAddonBackend.invoke_install` triggers a Kodi download, that would require an interactive test environment or a Kodi feature flag to disable the confirmation dialog. Not a blocker for BM-011.

---

## Usage

End: 5h 18% / wk 67% (claude-sonnet-4-6, max effort).
Start (this session): unknown (context continuation from prior session).
See USAGE_HISTORY.md for the appended row.
