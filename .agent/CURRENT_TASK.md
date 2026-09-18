# Current Task

## BM-011 — General Add-on Detection and Installation

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: COMPLETE — 17/17 live validation steps pass. Awaiting supervisor merge to matrix.

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
  - Harness trigger script (used for UpdateAddonRepos only)
  - `validate_addon()` — 17-step live validation, all pass
  - `validate-addon` CLI sub-command

- `tests/test_kodi_harness.py` — 21 new harness tests (19 + 2 Kodi 21 schema tests)

### Test Totals

760/760 passing (626 pre-BM-011 + 113 addon_manager + 21 harness)

### Live Validation Status

**COMPLETE**: 17/17 steps pass on Kodi 21.1 macOS (disposable .kodi-test only).

Key discoveries during validation:
- Kodi 21 dropped flat `<info>/<datadir>/<checksum>` repo schema; requires `<dir>` wrapper
- `InstallAddon` builtin always shows interactive dialog in Kodi 21; cannot be headless
- `_HttpAddonBackend.invoke_install` uses direct ZIP extraction + Kodi restart + SetAddonEnabled

### Commits

- `cdcaa2f` — production module + initial harness
- `08fd2de` — live validation fixes (Kodi 21 repo schema, headless install approach)

### Prerequisites Met

- BM-010 merged to `matrix` ✓ (`031e405`)
