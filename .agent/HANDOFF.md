# BM-011 Handoff — 2026-09-18

## Branch and HEAD
- Branch: `agent/claude`
- HEAD after commit: see `AGENT_STATUS.json` `last_commit`

## Task
BM-011: General add-on detection and installation from configured Kodi repositories.

---

## What Is Complete (unit-tested, committed)

### Production module: `resources/lib/addons.py` (NEW)
- `AddonError`, `AddonValidationError`, `AddonInstallError`
- `AddonStatus(str, Enum)`: ALREADY_INSTALLED | INSTALLED | FAILED
- `InstalledAddonInfo(addon_id, enabled, version)` — frozen dataclass
- `AddonInstallResult(addon_id, status, desired_state, enabled, version, message)` — frozen dataclass
- `_validate_addon_id(addon_id)` — regex `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$`
- `AddonBackend` abstract base (3 abstract methods)
- `AddonManager(backend)` with `is_installed()` and `install()`
- `KodiRuntimeAddonBackend` — lazy xbmc import; `invoke_install` uses `xbmc.executebuiltin(f"InstallAddon({addon_id})")`
- Bug guard: `get_addon_details` has `isinstance(result_val, dict)` check for `result: null` responses

### Unit tests: `tests/test_addon_manager.py` (NEW)
- 113 tests, all passing
- `FakeAddonBackend` with configurable installed/error/poll states
- TestAddonIdValidation, TestIsInstalled, TestInstallAlreadyInstalled, TestInstallHappyPath,
  TestInstallInvalidId, TestInstallInvocationFailure, TestInstallPollTimeout, TestInstallPollError,
  TestResultFields, TestDesiredState, TestAddonStatusEnum, TestKodiRuntimeBackend,
  TestAddonBackendInterface, TestAddonErrorHierarchy

### Harness infrastructure: `tools/kodi_test.py` (MODIFIED)
- `_ADDON_SERVER_PORT = 8922`
- `_BM011_TEST_ADDON_ID = "script.module.build-manager-test"`
- `_HARNESS_TRIGGER_ADDON_ID = "script.build-manager-harness-trigger"`
- `_make_bm011_test_addon_zip()`, `_make_bm011_addons_xml()`, `_make_bm011_repo_zip(port)`
- `_install_harness_trigger_script()` — writes trigger script to disposable addons dir
  - Supports two commands via `sys.argv[2]`:
    - `"update_repos"` → `xbmc.executebuiltin("UpdateAddonRepos")`
    - `"<addon_id>"` → `xbmc.executebuiltin("InstallAddon(<addon_id>)")`
- `_MultiFileHandler` — serves repo ZIP, addons.xml, addons.xml.md5, test addon ZIP
- `_HttpAddonBackend` — live validation backend (get_addon_details, invoke_install, poll)
- `_wait_for_addon_in_repo_index()` — polls `Addons.GetAddons(installed=False)`
- `validate_addon()` — 17-step live validation sequence
- CLI: `validate-addon` sub-command

### Harness tests: `tests/test_kodi_harness.py` (MODIFIED)
- 19 new tests: TestConstants (3), TestBm011ContentBuilders (12), TestMultiFileHandler (3),
  TestValidateAddonCliRoute (1)

### Total test count: 758/758 passing (was 626 before BM-011)

---

## What Is Partially Complete

### Live validation: `validate_addon()` — FAILS at step 10

Steps completed in runs:
- [1/17] reset ✓
- [2/17] install BM + trigger ✓
- [3/17] configure ✓
- [4/17] HTTP server on port 8922 serving 4 paths ✓
- [5/17] launch + ready ✓
- [6/17] test addon NOT installed ✓
- [7/17] repo installed via BM-010 path ✓
  - `enable_addon('repository.build-manager-test')` ✓
  - `SetAddonEnabled(harness-trigger)` → enabled ✓
  - `Addons.ExecuteAddon(trigger, "update_repos")` → triggered UpdateAddonRepos ✓
- [8/17] WARNING: `script.module.build-manager-test` NOT in repo index after 90s
- [9/17] test addon still NOT installed ✓
- [10/17] FAIL: `AddonManager.install()` returns FAILED with poll timeout after 120s
  - `Addons.ExecuteAddon(trigger, addon_id)` itself succeeds (no error)
  - `InstallAddon(addon_id)` is called inside Kodi but the addon never appears in DB

Steps NOT yet validated: 11–17

---

## Root Cause Analysis of Step 10 Failure

**Kodi 21's `SyncInstalled()` registers newly-discovered addons as `enabled=0` (disabled).**
This was diagnosed and fixed for step 7 (trigger script). The trigger script is now enabled.

**The remaining failure**: `InstallAddon(script.module.build-manager-test)` succeeds
but the addon never appears in Kodi's database after 120s polling. This means either:

1. **The test repository hasn't been indexed** — `UpdateAddonRepos` was triggered
   but Kodi didn't successfully fetch `addons.xml` from `http://127.0.0.1:8922/addons.xml`.
   If the repo index is empty, `InstallAddon` silently does nothing.

2. **The addons.xml format is wrong** — Kodi can't parse the file and skips the repo.

3. **`Addons.GetAddons(installed=False)` doesn't expose repo-indexed addons** in Kodi 21
   (step 8 WARNING is a symptom; this API may only show local addons).

4. **The `<datadir>` URL format in repo addon.xml** — the datadir is `http://127.0.0.1:8922/`
   with `zip="false"`. Kodi might construct the addon download URL differently than expected.

---

## Known Unknowns / Design Questions

**Q1: Does Kodi actually hit the HTTP server?**
The `_MultiFileHandler.log_message` is suppressed. There is no evidence Kodi requested
`/addons.xml` or the addon ZIP from port 8922. Add HTTP server logging to confirm.

**Q2: Is `<datadir zip="false">` the correct attribute?**
Real repos (kodi.tv) use `zip="true"`. With `zip="false"`, Kodi may expect addon
files directly (not ZIPs) at `{datadir}/{addon_id}/`. Try changing to `zip="true"`.

**Q3: Does `Addons.GetAddons(installed=False)` work in Kodi 21?**
Step 8 never finds the test addon. This API may return nothing useful. It is not
critical — if `InstallAddon` works, step 10 will succeed regardless.

**Q4: Does `UpdateAddonRepos` complete before step 10 calls `InstallAddon`?**
`UpdateAddonRepos` is async. We proceed immediately after triggering it. The 120s
poll may be entirely spent waiting for the repo scan to complete, then `InstallAddon`
runs too early (before the repo index is populated).

---

## Suggested Next Steps (in order)

### Step A: Enable HTTP server logging
In `_MultiFileHandler.log_message`, temporarily print to stderr to see if Kodi
is hitting the server. This costs ~1 line of change and diagnoses Q1 definitively:

```python
def log_message(self, fmt, *args) -> None:
    import sys
    print(f"  [http] {fmt % args}", file=sys.stderr)
```

### Step B: Try `zip="true"` in repo addon.xml
In `_make_bm011_repo_zip()`, change:
```python
f'<datadir zip="false">{base_url}/</datadir>'
```
to:
```python
f'<datadir zip="true">{base_url}/</datadir>'
```
(This is more consistent with kodi.tv repos.)

### Step C: Wait after UpdateAddonRepos before InstallAddon
After triggering `update_repos` in step 7, wait 30s before calling `InstallAddon`
in step 10. This gives the repo scan time to complete. Add `time.sleep(30)` between
steps 8 and 9, or make step 8 wait for the HTTP server to have received at least
one request to `/addons.xml`.

### Step D: Verify HTTP server path match
The addon ZIP is served at:
`/{addon_id}/{version}/{addon_id}-{version}.zip`
e.g. `/script.module.build-manager-test/1.0.0/script.module.build-manager-test-1.0.0.zip`

Check that Kodi constructs this exact URL. With `zip="false"`, Kodi might use a
flat path like `/{addon_id}-{version}.zip` instead.

---

## What Remains Unimplemented

- Live validation steps 11–17 (not reached yet)
- `BUILD_MANAGER_SUPERVISOR_HANDOFF.md` update
- `docs/TESTING.md` update

---

## Tests Run and Results

```
Ran 758 tests in 0.562s
OK
```

All unit tests pass. No live validation test has passed (step 10 blocks).

---

## Real Kodi / Device Safety

No real Kodi profile was touched. No Apple TV was touched. All mutation occurred
in `.kodi-test` (disposable profile). No Kodi process is running at handoff.

---

## Model and Effort

- Model: `claude-sonnet-4-6`
- Effort: `max`

## Usage at Handoff

- 5-hour window: **95% used** (resets ~2026-09-18T04:20 UTC, in ~3h 2m)
- Weekly (all models): 65% used

## Next Command for Fresh Session

```
python tools/kodi_test.py validate-addon
```

Then investigate HTTP server hits (Step A above). Most likely fix is either
enabling server logging to see if Kodi hits port 8922, or changing `zip="false"`
to `zip="true"` in `_make_bm011_repo_zip()`.
