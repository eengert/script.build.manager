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
| `test_validator.py` | Post-operation state validation (BM-014) | 105 |
| `test_config.py` | Configuration package deployment (BM-015) | 226 |

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

# BM-015 live validation: configuration package deployment
python3 tools/kodi_test.py validate-config

# BM-018D live validation: typed AF3 skin configuration
python3 tools/kodi_test.py validate-skin-config

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
| validate-addon / validate-dependencies / validate-addon-state / validate-post-operations / validate-config HTTP server (127.0.0.1 only) | 8922 | n/a |

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

### validate-post-operations command (BM-014)

`validate-post-operations` runs a 19-step live sequence to prove the
post-operation state validator works end-to-end, including deliberate drift
detection and repair:

```
python3 tools/kodi_test.py validate-post-operations
```

Two test add-ons are installed from the test repository:

| Add-on | Desired state | Role |
|--------|---------------|------|
| `plugin.video.bm014-enabled` | `"enabled"` | Installed enabled; validator reports PASS |
| `plugin.video.bm014-disabled` | `"disabled"` | Installed enabled, then set disabled; validator reports PASS |

Dependency closure is resolved via `DependencyResolver.resolve_closure()` for
the enabled add-on. `xbmc.python` is discovered as a SYSTEM node and maps to
PASS in the DEPENDENCY domain.

Proves:
1. `validate_build_state()` returns `passed=True` when Kodi state matches
   desired state (all domains: REPOSITORY, ADDON, DEPENDENCY, SKIN).
2. Deliberate drift (re-enabling `bm014-disabled` outside the validator) causes
   `is_valid=False` with a FAIL on `bm014-disabled` in the ADDON domain.
3. Repairing the drift (disabling again outside the validator) restores
   `passed=True` on the next call.
4. The validator makes zero Kodi mutations throughout — it is strictly read-only.
5. The real Kodi profile is untouched.

The validator itself never calls `Addons.SetAddonEnabled` or any other mutating
JSON-RPC method. Drift injection and repair both use the harness's
`_HttpAddonStateBackend.set_addon_enabled()`, which is external to the validator.

Ports: Kodi 8920, HTTP server 8922.

### validate-config command (BM-015)

`validate-config` runs a 24-step live sequence proving configuration package
deployment end-to-end, including layered package override, drift repair,
idempotency and restart persistence:

```bash
python3 tools/kodi_test.py validate-config
```

#### Why this test runs code inside Kodi

Kodi's typed add-on settings APIs (`xbmcaddon.Addon(id).getSettings()` and the
typed `Addon` setters) are **in-process APIs with no JSON-RPC equivalent**. The
other live validations drive production algorithms over HTTP JSON-RPC; that is
impossible here, and an HTTP simulation would prove nothing about the real
`xbmcaddon` path.

So `validate-config` writes a tiny **harness-only runner script add-on**
(`script.build-manager-harness-config`) directly into `.kodi-test` and invokes
it via `Addons.ExecuteAddon`. The runner contains no configuration logic: it
reads a job file, calls the real production API, and serializes the real
production result back out.

```python
loader = ConfigPackageLoader(default_packages_root())
effective = loader.resolve(declarations)
manager = ConfigurationManager(KodiRuntimeConfigurationBackend())
result = manager.apply(effective)
```

Nothing is simulated. The runner is generated by the harness at run time, lives
only in the disposable profile, and is never part of the shipped add-on — the
production add-on carries no test execution hook of any kind.

The test packages are written into the **installed** copy of Build Manager at
the production embedded location (`resources/config/packages/`), so the run
exercises `default_packages_root()` exactly as production will. The project
working tree is never modified.

#### Fixture

`plugin.video.bm015-config` is installed from the test repository with real Kodi
setting definitions covering every supported type, plus one deliberately
unmanaged control setting:

| Setting | Type | Default | Managed? |
|---------|------|---------|----------|
| `bm015.text` | string | `initial-text` | yes |
| `bm015.bool` | boolean | `false` | yes |
| `bm015.int` | integer | `1` | yes |
| `bm015.number` | number | `0.5` | yes |
| `bm015.unmanaged` | string | `unmanaged-initial` | **no** |

Two layered packages prove override precedence live:

| Package | Supplies |
|---------|----------|
| `bm015-common` | all four managed settings + the managed file |
| `bm015-device` | overrides `text` / `int` / `number` + the managed file |

`bm015.bool` therefore stays owned by the common layer while everything else is
won by the device layer.

Managed file: `addon_data/plugin.video.bm015-config/bm015-managed.txt`
Unmanaged sibling: `addon_data/plugin.video.bm015-config/bm015-unmanaged.txt`

All values are synthetic. No real credentials and no real add-on configuration
are used anywhere in this fixture.

#### Proves

1. Typed values are read through the real `xbmcaddon` Settings wrapper — the
   baseline step observes each add-on default correctly.
2. The production loader resolves `default_packages_root()` to the installed
   add-on's embedded package directory.
3. Package overlay precedence is correct live: each target reports the expected
   winning `package_id`.
4. All four typed settings and the managed file are deployed and verified.
5. No raw setting value appears anywhere in an operation result.
6. The unmanaged setting and the unmanaged sibling file are untouched.
7. Re-applying an identical configuration performs **zero mutations**
   (5/5 `ALREADY_CORRECT`).
8. BM-015's `validation_state` drives BM-014's CONFIGURATION domain to 5/5 PASS
   and `report.passed=True`; without a snapshot the domain is `NOT_CHECKED`, and
   a partial snapshot is `NOT_CHECKED` (scope mismatch).
9. **External** drift is repaired: a managed setting is rewritten directly in
   `settings.xml` with Kodi stopped, and the managed file is overwritten outside
   Build Manager; the next apply repairs exactly those two targets and leaves
   the other three `ALREADY_CORRECT`.
10. An ownership-violating job fails preflight with `ConfigOwnershipError` and
    performs **zero mutations** — the injected drift survives untouched.
11. Settings and managed file content persist across a Kodi restart, and a
    post-restart apply performs zero mutations.
12. The real Kodi profile is untouched.

#### Kodi Addon-lifetime finding

The first live run failed every setting verification and produced no
`settings.xml` at all. The cause was **not** the `Settings` API —
`Settings::setBool` / `setInt` / `setNumber` / `setString` in
`xbmc/interfaces/legacy/Settings.cpp` do call `settings->Save()`, and
`CAddonSettings::Save()` reaches the owning add-on's `SaveSettings()`.

The cause was **Addon object lifetime**. The backend used a helper of the shape:

```python
def _settings_for(addon_id):          # WRONG
    addon = xbmcaddon.Addon(addon_id)
    return addon.getSettings()        # addon is released on return
```

Kodi's `CAddonSettings` reaches its owning add-on through a *weak* reference, so
once the `Addon` was released the wrapper still accepted writes and served
in-memory reads while `Save()` could no longer reach its owner. That explains
every symptom: the setter did not raise, in-memory state changed, no
`settings.xml` appeared, a fresh handle did not see the value, and a restart
lost it.

The production backend uses the Kodi 20+ `Settings` wrapper for **both** reads
and writes, and keeps the owning `Addon` bound in the same frame across the
call. The deprecated `Addon.setSettingString/Bool/Int/Number` are not used.
`tests/test_config.py` pins this with a stubbed `xbmcaddon` whose `Settings`
stub holds only a **weakref** to its `Addon` — exactly mirroring Kodi — so a
write from a released handle silently fails to persist, and a dedicated test
reproduces the original defect to document it.

#### BM-014 artifact binding

Step 18 supplies BM-014 with **both** BM-015 artifacts and proves the gate
behaviour live:

| Artifacts supplied | CONFIGURATION domain |
|---|---|
| none | NOT_CHECKED |
| `configuration_state` only | NOT_CHECKED |
| `effective_configuration` only | NOT_CHECKED |
| matching pair | 5/5 PASS, `report.passed=True` |
| partial state | NOT_CHECKED |
| stale state (same scope, different desired content) | NOT_CHECKED |

The stale case resolves a second `EffectiveConfiguration` from `bm015-common`
alone. Its managed scope is **identical** to the real one — only the desired
values differ — so scope comparison alone would false-pass. The differing
`EffectiveConfiguration.identity` is what makes it NOT_CHECKED.

The step also cross-checks that the identity computed inside Kodi matches the
identity the harness computes by resolving the same packages out of process,
confirming the fingerprint is deterministic.

Ports: Kodi 8920, HTTP server 8922.

### validate-skin-config command (BM-018D)

`validate-skin-config` is a disposable macOS integration harness for the typed
skin-target path. It copies the installed AF3 add-on and its available declared
dependencies into `.kodi-test`; it never copies Eric's real profile, skin
settings, generated state, or authentication data. The only profile seed is a
synthetic AF3 first-run marker required to keep AF3's own first-run reload from
confounding the activation test.

The runner executes the production modules inside Kodi because Kodi's typed
skin-setting API is not exposed as an external JSON-RPC deployment API. The
sequence proves, when the local AF3/Kodi combination keeps the skin active:

1. Estuary starts in the disposable profile.
2. BM-018A activates AF3 through the confirmation-dialog lifecycle and checks
   the persisted skin setting plus `xbmc.getSkinDir()`.
3. A synthetic package applies one AF3 bool and one AF3 string through the
   explicit `target: "skin"` backend.
4. Read-back, zero-mutation reapply, one-setting drift repair, unmanaged-key
   preservation, restart persistence, BM-014 CONFIGURATION validation, and
   ownership preflight zero-mutation behavior are checked.
5. A wrong-active-skin attempt is rejected before any skin-setting mutation.
6. Kodi is stopped and the real profile's mtime is checked unchanged.

The command requires `/Applications/Kodi.app`, uses Kodi JSON-RPC port 8920,
and can require local-process/network permission in a sandboxed environment.
It does not create `af3-common`; the package is synthetic harness data only.

### Out of scope for BM-009 through BM-018D

- Add-on provisioning from the full planner action plan
- Production AF3 provisioning package (`af3-common`) and whole-file skin state
- Authentication and credential portability (BM-017)
- Remote or versioned configuration package delivery
- tvOS, Android, Fire TV, Shield testing (require device harnesses)
- Windows or Linux harnesses
