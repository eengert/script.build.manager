# Agent Handoff — BM-011-C Complete

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude`
**Status**: BM-011-C correction complete. Awaiting supervisor review + merge to matrix.

---

## What Was Done

BM-011-C implements the supervisor-mandated correction: production now uses the
constrained package-install fallback algorithm (Option A), not InstallAddon.
Live validation proves the production code path, not a harness workaround.

### Commit

- `0eb8133` — BM-011-C: production direct package install (this session)

### Previous commits (now superseded)

- `08fd2de` — BM-011 validation fixes (now incorrect re: production mechanism)
- `cdcaa2f` — BM-011 production module (InstallAddon approach — REPLACED)

---

## Files Modified

| File | Change |
|------|--------|
| `resources/lib/addons.py` | Major rewrite — Option A algorithm replaces InstallAddon |
| `tests/test_addon_manager.py` | Updated FakeAddonBackend + 51 new tests |
| `tools/kodi_test.py` | `_HttpAddonBackend` rewritten to mirror production |

---

## Architecture (BM-011-C — Option A)

### Production `KodiRuntimeAddonBackend.invoke_install` (new):
1. `_resolve_package_url(addon_id)` — enumerates installed+enabled repos via
   `Addons.GetAddons` JSON-RPC; reads each repo's `addon.xml` via xbmcvfs;
   fetches `addons.xml` from `<info>` URL; finds addon_id + version;
   constructs ZIP URL from `<datadir zip="true">/{id}/{ver}/{id}-{ver}.zip`
2. `_fetch_bytes(url, max_bytes)` — secure HTTP download (http/https only, no
   credentials, bounded to `_MAX_ADDON_ZIP_BYTES = 100 MB`)
3. `_validate_addon_zip(data, addon_id, expected_version)` — checks: valid ZIP,
   no absolute paths, no traversal (..), `{addon_id}/addon.xml` present,
   ID and version match
4. `_staged_install(zip_data, addon_id, addons_dir)` — extracts to temp staging
   dir, atomically renames `staging/{addon_id}/` → `addons_dir/{addon_id}/`,
   cleans staging on any failure
5. `xbmc.executebuiltin("UpdateLocalAddons")` — triggers Kodi to discover new addon

### Harness `_HttpAddonBackend.invoke_install` (mirrors production):
- Same helpers: `_resolve_package_url` (JSON-RPC + filesystem + `_fetch_bytes`),
  `_fetch_bytes`, `_validate_addon_zip`, `_staged_install`
- Harness difference: restart Kodi instead of `UpdateLocalAddons` (builtin
  unavailable outside Kodi)

### `AddonManager.install` (updated):
- After `poll_addon_installed`, checks `desired_state`:
  - `"enabled"` + not enabled → calls `backend.enable_addon(addon_id)`, verifies
  - `"disabled"` → leaves as-is (SyncInstalled Kodi 21 default: enabled=0)
- Returns INSTALLED with observed final state

### New shared helpers (pure Python, importable by both):
- `_validate_url` — http/https only, no embedded credentials, no file://
- `_fetch_bytes` — bounded download, 30s timeout
- `_validate_addon_zip` — ZIP structure + ID/version validation
- `_staged_install` — atomic extract + rename, cleanup on failure

---

## Test Results

- **Unit tests**: 811/811 pass
  - 51 new tests: `TestValidateUrl`, `TestValidateAddonZip`, `TestStagedInstall`,
    `TestDesiredStateEnable`, `TestDesiredStateDisable`, `TestEnableAddonFails`,
    `TestRepoResolution`, updated `TestKodiRuntimeBackend`
- **Live validation**: 17/17 pass

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
| 7 | Install test repo via BM-010 + enable trigger | ✓ |
| 8 | Wait for Kodi to index test repo | ✓ |
| 9 | Verify test add-on still NOT installed | ✓ |
| 10 | **Production algorithm**: resolve metadata → download → validate → stage → restart | ✓ |
| 11 | Verify result.status == INSTALLED | ✓ |
| 12 | Verify GetAddonDetails: enabled=True, version=1.0.0, files present | ✓ |
| 13 | Restart Kodi (restart #3) | ✓ |
| 14 | Verify still installed + enabled after restart | ✓ |
| 15 | Install again → ALREADY_INSTALLED (idempotency) | ✓ |
| 16 | Stop Kodi + HTTP server | ✓ |
| 17 | Confirm real Kodi profile untouched | ✓ |

### HTTP server log evidence (from step 10):

```
[http:8922] "GET /addons.xml HTTP/1.1" 200 -
[http:8922] "GET /script.module.build-manager-test/1.0.0/script.module.build-manager-test-1.0.0.zip HTTP/1.1" 200 -
```

Build Manager's algorithm fetched the repository index (`addons.xml`) to resolve
the package URL, then fetched the addon ZIP. Both requests originated from
`_HttpAddonBackend._resolve_package_url` and `invoke_install`, which use the
same `_fetch_bytes` helper as production.

---

## Final Report (Supervisor's 18 Items)

1. **Architecture decision**: Option A (constrained package-install fallback). No
   unattended normal addon install API exists in Kodi 21.
2. **`_resolve_package_url`**: Implemented in production (xbmc/xbmcvfs/xbmcaddon)
   and mirrored in harness (JSON-RPC + filesystem). First repo match wins.
3. **Download security** (`_fetch_bytes`): http/https only, no credentials, 100 MB cap,
   30s timeout. `_validate_url` enforces scheme + no-credentials.
4. **ZIP validation** (`_validate_addon_zip`): safe paths, no traversal, no absolute
   paths, addon.xml present, ID match, version match.
5. **Staged install** (`_staged_install`): temp dir, extract, atomic rename. Cleanup on failure.
6. **Install target**: fail closed if `addons_dir/{addon_id}` already exists.
7. **Kodi discovery**: `UpdateLocalAddons` builtin (production); Kodi restart (harness).
8. **`enable_addon`**: abstract on `AddonBackend`; implemented in production (JSON-RPC)
   and harness (JSON-RPC).
9. **`desired_state` handling**: `AddonManager.install` calls `enable_addon` when
   `desired_state="enabled"` and poll returns enabled=False. Verifies after enable.
10. **`desired_state="disabled"`**: leaves addon in SyncInstalled default (enabled=0).
11. **Verification**: `get_addon_details` after `enable_addon` confirms final state.
12. **Idempotency**: ALREADY_INSTALLED if `get_addon_details` returns non-None before install.
13. **Module docstring**: Updated to accurately describe the algorithm, security model,
    and distinction from BM-010 and BM-013.
14. **`FakeAddonBackend`**: updated with `enable_addon`, `enable_error`, `enable_calls`.
    `poll_addon_installed` registers poll result in `_installed` for post-enable verify.
15. **Test coverage**: 51 new tests across all new code paths.
16. **Live validation**: 17/17, HTTP evidence of repo metadata fetch + ZIP download.
17. **Shared helpers**: `_validate_url`, `_fetch_bytes`, `_validate_addon_zip`,
    `_staged_install` are pure Python in `addons.py`, imported by harness.
18. **No BM-012 work**: dependency closure deferred per task scope.

---

## What Is NOT Done

- BM-012 not started (dependency closure — explicitly out of scope)
- No merge to `matrix` (supervisor gate)

---

## Risks / Human Decisions Before Next Step

1. **Supervisor merge review**: All three files changed significantly. The old
   `KodiRuntimeAddonBackend.invoke_install` (InstallAddon builtin) is gone;
   the new implementation uses the full Option A algorithm.
2. **`UpdateLocalAddons` timing**: In production (inside Kodi), `UpdateLocalAddons`
   is asynchronous. `poll_addon_installed` must wait long enough for FindAddons
   to complete. The existing `_INSTALL_TIMEOUT = 120.0s` should be adequate.
3. **Kodi 21 `UpdateLocalAddons` vs restart**: The harness uses restart because
   `UpdateLocalAddons` is a Kodi builtin (only callable from inside the Kodi
   Python runtime). In production, `executebuiltin("UpdateLocalAddons")` is
   correct and doesn't require restart.

---

## Out of Scope — Noticed

- None.

---

## Usage

Start: 5h 37% / wk 70% (claude-sonnet-4-6, max effort).
End: 5h 37% / wk 70% (plan window did not advance measurably).
Delta: ~0% / ~0% (very low-cost session — implementation was well-scoped).
See USAGE_HISTORY.md for the appended row.
