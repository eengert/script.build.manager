# Current Task

## Idle — awaiting BM-011 assignment

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: BM-010 merged to `matrix` (`031e405`). Bootstrap fallback architecture approved. Project idle.

### Deliverables (BM-010-R corrected)

- `resources/lib/repository.py` — repository detection and installation (corrected)
  - Corrected install mechanism: temp dir → atomic os.rename → UpdateLocalAddons → Addons.SetAddonEnabled
  - Fail closed if target directory exists (no blind rmtree)
  - Temp dir cleaned up on extraction failure
  - `enable_addon()` new abstract backend method; calls Addons.SetAddonEnabled JSON-RPC
  - `poll_addon_installed()` now verifies enabled=True via Addons.GetAddonDetails
  - `_ENABLE_WAIT_TIMEOUT = 30.0` constant for UpdateLocalAddons registration wait
  - RepositoryBackend now has 6 abstract methods (was 5)
  - All other security/idempotency/download properties from BM-010 unchanged

- `tests/test_repository.py` — 108 BM-010-R unit tests (no real Kodi required)
  - All original BM-010 tests retained and updated
  - New: STAGING (temp+rename, existing target fail-closed, cleanup on failure)
  - New: enable_addon invocation order (after scan, before poll)
  - New: ALREADY_INSTALLED has no enable call, no scan, no install
  - New: enable failure → FAILED; poll not called if enable fails
  - New: poll verifies enabled=True (not just presence)
  - New: KodiRuntime tests verify SetAddonEnabled called, GetAddonDetails used

- `tools/kodi_test.py` — corrected backend + 13-step validate_repo()
  - `_HttpRepositoryBackend.install_zip_to_addons()`: temp+rename, fail closed on existing target
  - `_HttpRepositoryBackend.enable_addon()`: polls until registered, then SetAddonEnabled
  - `_HttpRepositoryBackend.poll_addon_installed()`: Addons.GetAddonDetails + enabled=True
  - `validate_repo()`: 13 steps (was 12) — added restart persistence (9-10), idempotency (11), real-profile confirmation (13)

### Live Validation (BM-010-R)

**PASSED — 13/13 steps** against Kodi 21.1 macOS, disposable .kodi-test only (2026-09-18).

Key proofs:
- Step 8: `Addons.GetAddonDetails` → `enabled=true`, `type=xbmc.addon.repository` before restart
- Step 10: `Addons.GetAddonDetails` → `enabled=true`, `type=xbmc.addon.repository` after restart
- Step 11: second `mgr.install()` → `ALREADY_INSTALLED`; no download, extraction, scan, or enable
- Step 13: real profile (`~/Library/Application Support/Kodi`) untouched
- Repository recognized by `Addons.GetAddons(type=xbmc.addon.repository)` — Kodi sees it as a repository, not a generic add-on
- No staging/temp artifacts remain in addons directory

### Test Totals

626/626 passing (518 pre-BM-010 + 87 original BM-010 + 21 BM-010-R additions)

### Last Completed: BM-010 — Repository Bootstrap (merged `031e405`)

- Architecture approved: constrained bootstrap fallback (validated ZIP → staged extraction → Kodi scan → API enable → API verify)
- 626/626 tests on `matrix`
- Live validation 13/13 passed
- Restart persistence proven; idempotency proven

### Next: BM-011

Not started. Scope to be assigned by supervisor.
BM-011: General add-on detection/installation (distinct from repository bootstrap).

### Prerequisites

- BM-001 through BM-006 merged to `matrix` ✓
- BM-007, BM-008 absorbed by BM-006 ✓
- BM-009 merged to `matrix` ✓ (fast-forwarded with BM-010)
- BM-010 merged to `matrix` ✓ (`031e405`)
