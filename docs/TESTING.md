# Testing — Build Manager

## Unit tests

All tests live in `tests/` and run with the stdlib test runner:

```
python3 -m unittest discover tests
```

No real Kodi, no network access, and no external dependencies are required.

The test suite covers:

| File | Area | Count |
|------|------|-------|
| `test_imports.py` | Import smoke tests (BM-001) | 3 |
| `test_manifest_schema.py` | JSON Schema structure (BM-002) | 48 |
| `test_manifest_loader.py` | Manifest parser/validator (BM-003) | 162 |
| `test_manifest_resolver.py` | Profile resolver (BM-004) | 78 |
| `test_kodi_inspector.py` | Kodi state inspector (BM-005) | 67 |
| `test_planner.py` | Desired-vs-actual planner (BM-006) | 86 |
| `test_kodi_harness.py` | Disposable Kodi harness (BM-009) | 74 |
| `test_repository.py` | Repository detection/install (BM-010) | 87 |

## Disposable Kodi harness

`tools/kodi_test.py` provides a self-contained, isolated Kodi environment for
live integration testing on macOS.

### Isolation model

Kodi on macOS resolves its profile from the process `HOME` environment
variable:

```
$HOME/Library/Application Support/Kodi
```

The harness overrides `HOME` to a project-local `.kodi-test/home/` directory
before launching Kodi. The real Kodi profile is never read, written, or
modified.

Path layout:

```
<project>/.kodi-test/
  home/
    Library/
      Application Support/
        Kodi/
          addons/        ← installed test add-ons (script.build.manager)
          userdata/
            guisettings.xml  ← web server config written by configure
      Logs/
        kodi.log
  kodi.pid               ← PID of the running disposable Kodi process
```

### Safety invariants

`verify_isolation()` is called before every mutating operation and raises
`RuntimeError` if any invariant is violated:

- `ROOT` is not `/`
- `ROOT` is inside `PROJECT`
- `HOME` is inside `ROOT`
- `KODI_APPDATA_DIR` is inside `HOME`
- `KODI_APPDATA_DIR` does not overlap the real Kodi profile
  (`~/Library/Application Support/Kodi`)

`reset()` performs an additional check before `shutil.rmtree(ROOT)`:
the path must still be inside `PROJECT` after resolving symlinks.

`stop()` checks that the target PID belongs to the Kodi binary before sending
`SIGTERM`. It refuses to stop an unrelated process.

Credentials (webserver username and password) are never logged or committed.

### Usage

Commands are run from the project root:

```bash
# Full validation sequence (recommended for CI or first-run verification)
python3 tools/kodi_test.py validate

# BM-010 live validation: repository detection and installation
python3 tools/kodi_test.py validate-repo

# Step by step
python3 tools/kodi_test.py reset
python3 tools/kodi_test.py install
python3 tools/kodi_test.py configure
python3 tools/kodi_test.py launch
python3 tools/kodi_test.py wait --timeout 90
python3 tools/kodi_test.py inspect
python3 tools/kodi_test.py stop

# Current state
python3 tools/kodi_test.py status
```

### Requirements

- macOS with `/Applications/Kodi.app` installed (Kodi 21.x recommended)
- No other process using port 8920 (Kodi JSON-RPC) or port 8921 (validate-repo HTTP server)

The harness is not required for the standard unit test suite — `validate` is
a manual or CI step run after a full `reset → install → configure` sequence.

### Webserver port

The harness uses port **8920** for the disposable Kodi JSON-RPC web server.
This differs from Backup Pro's port (8899) to allow both test harnesses to
run simultaneously without collision.

| Harness | Port | Username |
|---------|------|----------|
| Build Manager (`tools/kodi_test.py`) | 8920 | `bm-test` |
| Backup Pro (`tools/kodi_test.py`) | 8899 | `kodi-test` |
| validate-repo HTTP server (127.0.0.1 only) | 8921 | n/a |

### Add-on install

`install` copies only the add-on distribution files from the project root:

- `addon.xml`
- `default.py`
- `resources/`

Tests, tools, and documentation are excluded from the disposable profile.

### INSPECT command

`inspect` queries the disposable Kodi instance via HTTP JSON-RPC and returns:

- `platform` — detected platform (e.g. `"macos"`)
- `kodi_version` — major.minor (e.g. `"21.1"`)
- `active_skin` — active skin add-on ID (e.g. `"skin.estuary"`)
- `addon_count` — number of installed add-ons
- `addons` — raw list from `Addons.GetAddons`

All calls are read-only. No Kodi state is mutated.

### validate-repo command (BM-010)

`validate-repo` runs a 12-step live sequence to prove repository detection and
installation work end-to-end against a real Kodi instance:

1. Reset the disposable harness
2. Install Build Manager
3. Configure web server
4. Launch Kodi
5. Wait for JSON-RPC ready
6. Create a minimal test repository ZIP (`repository.build-manager-test`)
7. Start a localhost-only HTTP server (127.0.0.1:8921) to serve the ZIP
8. Verify the repository is NOT yet installed
9. Call `RepositoryManager.install()` via `_HttpRepositoryBackend`
10. Verify result status = INSTALLED
11. Verify `is_installed()` returns True (via JSON-RPC)
12. Stop Kodi and shut down the HTTP server

The backend (`_HttpRepositoryBackend`) uses HTTP JSON-RPC for detection and
polling, direct filesystem writes for ZIP extraction, and a Kodi restart
(stop → launch → wait) to trigger the add-on scanner — since
`UpdateLocalAddons` is a Kodi GUI builtin not accessible via HTTP JSON-RPC.

All mutation occurs only in the `.kodi-test` disposable environment. The real
Kodi profile is never touched.

### Out of scope for BM-009 / BM-010

- General add-on installation (BM-011+)
- Add-on provisioning from the full planner action plan (BM-011+)
- tvOS, Android, Fire TV, Shield testing (require device harnesses)
- Windows or Linux harnesses
