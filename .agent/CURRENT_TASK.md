# Current Task

## BM-011-C — Production Direct Package Install Correction

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: COMPLETE — 17/17 live validation steps pass. Awaiting supervisor merge to matrix.

### Problem Corrected

The prior BM-011 implementation used `xbmc.executebuiltin("InstallAddon(id)")` as
the production install mechanism. Kodi 21 always shows a confirmation dialog for
this builtin — it cannot complete unattended. The harness workaround (direct
extraction) caused TEST != PRODUCTION mismatch.

### Solution: Option A — Constrained Package-Install Fallback

Both production and harness now use the same algorithm:
1. Resolve ZIP URL from installed+enabled repository metadata
2. Download ZIP (`_fetch_bytes`)
3. Validate ZIP (`_validate_addon_zip`)
4. Staged extract → atomic rename (`_staged_install`)
5. Trigger Kodi discovery (production: `UpdateLocalAddons`; harness: Kodi restart)
6. Enable if desired_state="enabled" (`enable_addon` via `SetAddonEnabled`)

### Deliverables

- `resources/lib/addons.py` — full rewrite of `KodiRuntimeAddonBackend`
  - `invoke_install`: Option A algorithm (resolve → download → validate → stage → UpdateLocalAddons)
  - `enable_addon`: `Addons.SetAddonEnabled` via JSON-RPC
  - New shared helpers: `_validate_url`, `_fetch_bytes`, `_validate_addon_zip`, `_staged_install`
  - `AddonManager.install`: now acts on `desired_state` (enable_addon after poll)
  - Updated module docstring

- `tests/test_addon_manager.py` — 51 new tests; updated FakeAddonBackend + 3 runtime tests
  - `TestValidateUrl`, `TestValidateAddonZip`, `TestStagedInstall`
  - `TestDesiredStateEnable`, `TestDesiredStateDisable`, `TestEnableAddonFails`
  - `TestRepoResolution`, updated `TestKodiRuntimeBackend`

- `tools/kodi_test.py` — `_HttpAddonBackend` rewritten to mirror production algorithm

### Test Totals

811/811 passing (760 pre-BM-011-C + 51 new)

### Live Validation Status

**COMPLETE**: 17/17 steps pass on Kodi 21.1 macOS (disposable .kodi-test only).

HTTP server logs prove Build Manager's algorithm fetched `addons.xml` and the
addon ZIP from the repository. `[resolve]` log lines prove metadata resolution ran.

### Commit

- `0eb8133` — BM-011-C: production direct package install (17/17 live-proven)

### Prerequisites Met

- BM-010 merged to `matrix` ✓ (`031e405`)
- BM-011-C fully corrects the supervisor-identified TEST != PRODUCTION mismatch
