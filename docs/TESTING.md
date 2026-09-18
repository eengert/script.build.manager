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
| `test_addon_manager.py` | General add-on installation (BM-011) | 132 |
| `test_dependencies.py` | Dependency closure discovery/reconciliation (BM-012) | 96 |
| `test_addon_state.py` | Enable/disable state reconciliation (BM-013) | 66 |

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
| validate-addon / validate-dependencies / validate-addon-state HTTP server (127.0.0.1 only) | 8922 | n/a |

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

### validate-addon command (BM-011)

`validate-addon` runs a 19-step live sequence to prove general add-on
detection and installation work end-to-end:

```
python3 tools/kodi_test.py validate-addon
```

Tests the constrained package-install fallback: resolve ZIP URL from repo
metadata → download → validate → staged extract → restart → enable. Proves
both `desired_state='enabled'` and `desired_state='disabled'` paths, restart
persistence, and ALREADY_INSTALLED idempotency.

Ports: Kodi 8920, HTTP server 8922.

### validate-dependencies command (BM-012)

`validate-dependencies` runs an 18-step live sequence to prove dependency
closure discovery and reconciliation work end-to-end:

```
python3 tools/kodi_test.py validate-dependencies
```

Dependency graph used in the test:

```
plugin.video.bm012-root
  ├── script.module.bm012-a   (required, MISSING pre-reconcile)
  │     └── script.module.bm012-b   (required, discovered in round 2)
  └── script.module.bm012-optional (optional="true" — never installed)
```

Proves:
1. `resolve_closure()` correctly classifies bm012-a as MISSING and
   bm012-optional as OPTIONAL before any installation.
2. `reconcile_dependencies()` installs bm012-a (round 1) and then bm012-b
   (round 2, discovered by reading bm012-a's addon.xml after install).
3. Optional deps are never installed regardless of availability.
4. `result.all_required_satisfied = True` after reconciliation.
5. Kodi API confirms bm012-a and bm012-b are installed + enabled.
6. bm012-optional is never installed even though its ZIP is served.

Each required dep installation triggers a Kodi restart (stop → launch →
wait_for_ready) — the harness substitute for `UpdateLocalAddons`.
Additive-only: no add-on is disabled or removed during reconciliation.

Ports: Kodi 8920, HTTP server 8922.

### validate-addon-state command (BM-013)

`validate-addon-state` runs a 16-step live sequence to prove enable/disable
state reconciliation works end-to-end against a real Kodi instance:

```
python3 tools/kodi_test.py validate-addon-state
```

Three test add-ons are installed from the test repository:

| Add-on | Role |
|--------|------|
| `plugin.video.bm013-enabled` | Stays enabled; proves ALREADY_CORRECT |
| `plugin.video.bm013-disabled` | Starts enabled; reconcile sets it disabled |
| `script.module.bm013-protected` | Protected dependency; desired=disabled is BLOCKED |

Proves:
1. `reconcile({disabled:"disabled"})` → DISABLED; Kodi API confirms enabled=False.
2. Second reconcile → ALREADY_CORRECT (idempotency: no redundant SetAddonEnabled call).
3. `reconcile({enabled:"enabled", protected:"disabled"}, protected={protected})`
   → enabled=ALREADY_CORRECT, protected=BLOCKED_REQUIRED_DEPENDENCY; all_correct=False.
4. Disabled state persists across Kodi restart (restart → verify enabled=False).
5. Re-enable: `reconcile({enabled:"enabled", disabled:"enabled"})` → enabled=ALREADY_CORRECT,
   disabled=ENABLED; all_correct=True.

Managed scope: only add-ons explicitly passed to `reconcile()` are touched.
Unmanaged installed add-ons are never queried or mutated.

Ports: Kodi 8920, HTTP server 8922.

### Out of scope for BM-009 / BM-010 / BM-011 / BM-012 / BM-013

- Add-on provisioning from the full planner action plan (BM-014+)
- Add-on provisioning from the full planner action plan
- tvOS, Android, Fire TV, Shield testing (require device harnesses)
- Windows or Linux harnesses
