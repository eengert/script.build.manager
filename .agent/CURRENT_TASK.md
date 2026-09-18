# Current Task

## BM-011 — General Add-on Detection and Installation

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: In progress — unit tests complete, live validation blocked at step 10.

### Deliverables (BM-011)

- `resources/lib/addons.py` — NEW production module
  - `AddonManager(backend)` with `is_installed()` and `install()`
  - `KodiRuntimeAddonBackend` — uses `InstallAddon` builtin (not ZIP download)
  - `AddonBackend` abstract base (injectable for tests)
  - Strict addon_id validation: `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$`
  - Result types: `AddonStatus`, `InstalledAddonInfo`, `AddonInstallResult`
  - Errors: `AddonError`, `AddonValidationError`, `AddonInstallError`

- `tests/test_addon_manager.py` — 113 unit tests, all passing

- `tools/kodi_test.py` — BM-011 harness infrastructure
  - Multi-file HTTP server on port 8922 (repo ZIP, addons.xml, addon ZIP)
  - Harness trigger script (enabled via `SetAddonEnabled` after restart)
  - `validate_addon()` — 17-step live validation (partial: steps 1–9 pass, 10 blocks)
  - `validate-addon` CLI sub-command

- `tests/test_kodi_harness.py` — 19 new harness tests

### Test Totals

758/758 passing (626 pre-BM-011 + 113 addon_manager + 19 harness)

### Live Validation Status

**BLOCKED at step 10**: `InstallAddon` poll timeout after 120s.
- Steps 1–9 all pass
- Trigger script enable fix landed ✓
- `UpdateAddonRepos` triggered after repo enable ✓
- HTTP server may not be receiving requests from Kodi (unconfirmed)
- See `.agent/HANDOFF.md` for full root cause analysis and next steps

### Immediate Next Step

Add HTTP logging to `_MultiFileHandler.log_message` to confirm if Kodi hits port 8922.
Also try changing `<datadir zip="false">` to `<datadir zip="true">` in `_make_bm011_repo_zip()`.

### Prerequisites Met

- BM-010 merged to `matrix` ✓ (`031e405`)
