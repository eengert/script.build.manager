# Current Task

## Idle — awaiting BM-011 assignment

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: BM-010 complete on `agent/claude`; pending supervisor review and merge to `matrix`

### Deliverables (BM-010)

- `resources/lib/repository.py` — repository detection and installation
  - Public API: `RepositoryManager(backend).is_installed(addon_id)` and
    `RepositoryManager(backend).install(repository) -> RepositoryInstallResult`
  - Result types: `RepositoryStatus` (ALREADY_INSTALLED | INSTALLED | FAILED),
    `RepositoryInstallResult(addon_id, status, message)` frozen dataclass
  - Error hierarchy: `RepositoryError` → `RepositoryValidationError`,
    `RepositoryInstallError`
  - Security helpers: `_validate_url_policy()`, `_SafeRedirectHandler`,
    `_build_safe_opener()`, `_download_artifact()` (50 MB limit, 30s timeout)
  - ZIP validation: `validate_repository_zip()` — path traversal rejection,
    addon.xml presence, ID match, `xbmc.addon.repository` extension required
  - ZIP extraction: `_extract_zip_to_directory()` — handles prefixed and flat ZIPs,
    path containment check before every write
  - Backend interface: `RepositoryBackend` abstract base (5 methods)
  - Production backend: `KodiRuntimeRepositoryBackend` — lazy xbmc/xbmcvfs import,
    uses `xbmc.executeJSONRPC()` for detection and `xbmc.executebuiltin('UpdateLocalAddons')`
    for scan trigger
  - Idempotent: ALREADY_INSTALLED returned if add-on already present; no mutation
  - Stdlib only — no new runtime dependencies
  - No dependency on tools/kodi_test.py

- `tests/test_repository.py` — 87 BM-010 unit tests (no real Kodi required)
  - DETECTION: is_installed() — 4 tests
  - IDEMPOTENCY: already-installed short-circuit, no mutation — 5 tests
  - URL VALIDATION: allowed/rejected schemes, credentials — 9 tests
  - REDIRECT SAFETY: _SafeRedirectHandler — 6 tests
  - DOWNLOAD: size limit, network error, empty response — 6 tests
  - ZIP ENTRY VALIDATION: traversal, absolute paths, null bytes — 11 tests
  - ZIP VALIDATION: valid/invalid artifacts — 9 tests
  - ZIP EXTRACTION: prefixed/flat/nested — 5 tests
  - INSTALL HAPPY PATH: full flow — 6 tests
  - INSTALL FAILURE PATHS: all error branches — 10 tests
  - RESULT TYPES: status enum, dataclass fields, immutability — 3 tests
  - SECURITY: policy constants, URL edge cases, error hierarchy — 7 tests
  - KODI RUNTIME BACKEND: import failure behavior — 4 tests
  - BACKEND INTERFACE: completeness — 2 tests

- `tools/kodi_test.py` — added `validate-repo` command
  - `_make_test_repo_zip()`: builds minimal `repository.build-manager-test` ZIP
  - `_HttpRepositoryBackend`: harness backend using HTTP JSON-RPC + filesystem;
    `trigger_addon_scan()` restarts Kodi (stop → launch → wait) since
    `UpdateLocalAddons` is not accessible via HTTP JSON-RPC
  - `_SingleFileHandler`: localhost-only HTTP server (127.0.0.1:8921) for serving
    the test repo ZIP
  - `validate_repo()`: 12-step live validation sequence
  - Port 8921 used (distinct from 8920 Kodi JSON-RPC port)

- `docs/TESTING.md` — updated for BM-010
  - Added `test_repository.py` row (87 tests)
  - Added `validate-repo` to usage examples
  - Added port 8921 to port table
  - Added `validate-repo` command documentation section

### Live Validation (BM-010)

All 12 steps passed against Kodi 21.1 on macOS (2026-09-17):
- repository.build-manager-test (392-byte ZIP) installed successfully
- Detection before install: is_installed() = False ✓
- Install: result.status = INSTALLED ✓
- Detection after install: is_installed() = True ✓
- Kodi restarted once during trigger_addon_scan() to run UpdateLocalAddons ✓
- Real profile (`~/Library/Application Support/Kodi`) untouched ✓

### Test Totals

605/605 passing (518 pre-BM-010 + 87 new repository tests)

### Last Completed: BM-010 — Repository Detection and Installation

On `agent/claude`; pending supervisor merge to `matrix`.

### Next: BM-011

Not started. Scope to be assigned by supervisor.
BM-011: General add-on detection/installation (distinct from repository bootstrap).

### Prerequisites

- BM-001 through BM-006 merged to `matrix` ✓
- BM-007, BM-008 absorbed by BM-006 ✓
- BM-009 on `agent/claude` ✓ (pending merge)
- BM-010 on `agent/claude` ✓ (pending merge)
