# Agent Handoff — BM-015 Complete (Pending Supervisor Review)

**Date**: 2026-09-18 (corrections applied)
**Agent**: Claude (claude-opus-5, effort xhigh)
**Status**: BM-015 complete on `agent/claude`. NOT merged to `matrix`. BM-016 not started.

---

## Result

BM-015 (prototype configuration deployment) is implemented, unit-tested,
live-validated and documented.

- **Unit tests**: 1378/1378 pass (was 1129; +249)
- **Live validation**: 24/24 `validate-config` (Kodi 21.1, macOS, disposable
  `.kodi-test` profile only)
- **Branch**: `agent/claude`
- **Merge**: not performed — supervisor review gate

## Commits

| SHA | Message |
|-----|---------|
| `69d5984` | feat(BM-015): configuration package deployment prototype |
| `52a08b9` | fix(BM-015): write settings through the persisting typed Addon setters |
| `762b36b` | docs(BM-015): configuration package format reference |
| `b640b5e` | chore: record BM-015 complete (1346/1346 tests, 24/24 live) |

## Files created / modified

**Created**
- `resources/lib/config.py` — the BM-015 module
- `resources/config/packages/README.md` — embedded package root
- `tests/test_config.py` — 226 tests
- `docs/CONFIG_PACKAGES.md` — package format reference

**Modified**
- `resources/lib/validator.py` — optional `configuration_state` parameter
- `tests/test_validator.py` — +23 tests (105 total)
- `tools/kodi_test.py` — `validate-config` live sequence + disposable runner
- `docs/MANIFEST.md` — "Config package format" open question resolved
- `docs/TESTING.md` — `validate-config` documentation
- `.agent/USAGE_HISTORY.md`, `.agent/CURRENT_TASK.md`, `.agent/AGENT_STATUS.json`

---

## Kodi Addon-lifetime discovery (corrected)

**Correction**: an earlier BM-015 handoff claimed Kodi 21's `Settings`-wrapper
setters do not persist because `Settings.cpp` never calls `Save()`. That was
wrong. It came from reading only the `SetSettingValue<>` template and stopping
before the setter methods themselves. In Omega:

```cpp
void Settings::setString(const char* id, const String& value)
{
  if (!SetSettingValue<CSettingString>(settings, id, value))
    throw XBMCAddon::WrongTypeException(...);
  settings->Save();
}
```

Equivalent `Save()` calls exist for `setBool` / `setInt` / `setNumber`, and
`CAddonSettings::Save()` reaches the owning add-on's `SaveSettings()`. The
Settings API persists correctly.

**Actual root cause — Addon object lifetime.** The original backend helper was:

```python
def _settings_for(addon_id):          # WRONG
    addon = xbmcaddon.Addon(addon_id)
    return addon.getSettings()        # addon released on return
```

Kodi's `CAddonSettings` holds a **weak** reference to its owning add-on. With
the `Addon` released, the wrapper remained usable for in-memory access while
`Save()` could no longer reach its owner. That explains every observed symptom:
the setter did not raise, in-memory state changed, no `settings.xml` appeared, a
fresh handle did not see the value, and a restart lost it.

**Production API now used** — the Kodi 20+ typed `Settings` wrapper for BOTH
directions, with the owning `Addon` kept alive:

```python
addon = xbmcaddon.Addon(addon_id)      # stays bound in this frame
settings = addon.getSettings()
settings.getString(key)                # read
settings.setString(key, value)         # write
```

`_open_addon()` returns the **Addon**, never a Settings wrapper, so the helper
shape that caused the bug cannot recur. The deprecated
`Addon.setSettingString/setSettingBool/setSettingInt/setSettingNumber`
(deprecated since Kodi 20) are no longer used anywhere.

Post-write verification is unchanged and still mandatory: the value is re-read
through a **fresh** `Addon`/`Settings` pair.

Unaffected and still verified: `CSettingNumber::ToString()` uses default
`std::ostringstream` double formatting — 6 significant digits. BM-015 rejects
package `number` values that do not survive that round trip and compares numbers
at exactly that precision.

---

## Path-safety corrections

**Secure staging file.** The predictable `<dest>.bm-config-tmp` staging name is
gone. Writes now stage through `tempfile.mkstemp(dir=parent, ...)`
(`O_CREAT|O_EXCL`, mode 0600, unpredictable name), then `os.replace()`. A
pre-existing symlink at the old predictable path can no longer capture the
write. The staging file is removed on every failure path.

**Destinations never traverse a symlink.** Containment is lexical against the
realpath'ed profile root plus an explicit refusal of any existing symlink
component — parent directories and the destination itself, checked with lstat
semantics. This rejects an in-profile symlink pointing at a different in-profile
file, not just escapes: a managed path names that exact file, never an alias.
Reads obey the same rule.

**Descriptor containment.** `package.json`'s real path must remain inside the
selected package directory, matching the rule already applied to package source
assets.

---

## Architecture summary

**Public API** (`resources/lib/config.py`)

```python
loader = ConfigPackageLoader(default_packages_root())
effective = loader.resolve(desired.config)        # full preflight, pure
manager = ConfigurationManager(KodiRuntimeConfigurationBackend())
result = manager.apply(effective)                 # verified deployment
```

- **Pure layer**: descriptor parsing, type validation, path containment,
  package overlay, ownership + completeness validation.
- **Runtime layer** (`ConfigurationBackend`): typed setting access, managed-file
  read/atomic write.

**Package format**: `resources/config/packages/<package-id>/package.json` plus
optional `files/`. Package IDs match `[a-z0-9][a-z0-9._-]*` (≤64 chars) and are
never treated as paths. Setting types: `string`, `bool`, `int`, `number`, with
exact JSON value typing (a bool is never an int or a number).

**Overlay**: packages apply in resolved order (base → platform → device →
optional groups); later packages win per target. Duplicate targets *inside* one
package are rejected outright.

**Ownership**: effective targets must exactly equal manifest-declared
`managed_settings` / `managed_files` — undeclared targets and unsupplied
declared targets both fail preflight.

**Preflight guarantee**: all parsing, validation, path checks and source-file
reads complete before the first mutation. A malformed later package leaves Kodi
untouched. This is preflight, *not* rollback — once `apply()` starts, earlier
successful operations are not undone if a later one fails.

**Files**: destinations resolve against `special://profile/` via
`xbmcvfs.translatePath`; securely created sibling temp file
(`tempfile.mkstemp`) + `os.replace()` (atomic on POSIX and Windows, never
cross-filesystem). No symlink is ever traversed. `xbmcvfs.rename()` is
deliberately avoided — Kodi documents it as unable to move across filesystems on all
platforms and `CFile::Rename` has no overwrite guarantee or fallback. Fails
closed if the profile root does not translate to a local path.

**Secrets**: `private_overlay` is never read. Results carry SHA-256 content
identities, never raw setting values or file bytes. No heuristic secret
detection — BM-017 owns credential portability.

**Skin**: `SkinEntry.config_packages` is NOT deployed. Only
`desired.config.packages` is applied. BM-018 can reuse the loader/deployer.

---

## BM-014 integration — Option A (identity-bound)

`ConfigApplyResult.validation_state` returns an immutable
`ConfigurationValidationState` carrying the applied scope, the verified subset,
and the `effective_identity` it was produced from.
`validate_build_state()` now takes both `configuration_state` and
`effective_configuration`.

**Why identity is required**: scope alone false-passes. A package whose desired
value changes from `720p` to `4k` keeps an identical managed scope, so a stale
snapshot would otherwise validate the new configuration.
`EffectiveConfiguration.identity` is a deterministic SHA-256 over the ordered
package selection and, per target, the setting type plus the desired value
digest (or file content digest) plus the winning package ID. No raw values are
included.

Four gates, all NOT_CHECKED on failure (never FAIL — a stale artifact is not
evidence of drift):

| # | Gate |
|---|---|
| 1 | effective package selection corresponds to `desired.config.packages` |
| 2 | effective target scope equals the declared managed scope |
| 3 | snapshot scope equals the effective scope |
| 4 | snapshot `effective_identity` equals `EffectiveConfiguration.identity` |

`desired.config is None` still emits no checks. BM-014 remains strictly
read-only and never resolves or reads package files — it receives the already
resolved `EffectiveConfiguration` as an immutable expected snapshot.

---

## Live validation — 24/24

`python3 tools/kodi_test.py validate-config`

Kodi's typed settings APIs are in-process only, so the live test writes a
**harness-only runner script add-on** into `.kodi-test` and invokes it via
`Addons.ExecuteAddon`. The runner holds no configuration logic — it calls the
real `ConfigPackageLoader`, `ConfigurationManager` and
`KodiRuntimeConfigurationBackend`. Nothing is simulated. **The production add-on
contains no test execution hook.**

Test packages are written into the *installed* copy of Build Manager at the
production embedded location, so `default_packages_root()` is exercised exactly
as production will use it. The project working tree is not modified.

Proven live: typed reads of all four types; overlay precedence (`bm015.bool`
stays owned by the common layer, everything else by the device layer);
deployment + verification of four settings and one managed file; no raw value in
any result; unmanaged setting and unmanaged sibling file untouched; idempotency
(5/5 `ALREADY_CORRECT`, zero mutations); BM-014 CONFIGURATION 5/5 PASS with
snapshot, NOT_CHECKED without and with a partial snapshot; **external** drift
repair (settings.xml rewritten with Kodi stopped; managed file overwritten
externally) repairing exactly the two drifted targets; ownership violation
failing preflight with zero mutations (injected drift survives); restart
persistence with a zero-mutation post-restart apply; real Kodi profile untouched.

BM-014 artifact binding proven live (step 18): no artifacts → NOT_CHECKED;
state only → NOT_CHECKED; effective only → NOT_CHECKED; matching pair → 5/5
PASS with `report.passed=True`; partial state → NOT_CHECKED; **stale state with
an identical managed scope but different desired content → NOT_CHECKED**. The
identity computed inside Kodi is also cross-checked against the identity the
harness computes out of process.

---

## What is NOT done

- **Not merged to `matrix`** (`matrix` remains `bc0be68`)
- BM-016 **not started**
- No production configuration packages exist yet —
  `resources/config/packages/` contains only `README.md`
- BM-015 is embedded/local packages only; no remote/versioned delivery
- Only macOS/Kodi 21.1 live-validated

## Out of scope — noticed

- `README.md` still says "implementation has not begun" and its repository
  layout section predates `docs/`, `tests/` and `tools/`. Stale since before
  BM-015; deliberately not touched.

## Human decision required before next step

Supervisor review and merge of `agent/claude` → `matrix`, then assignment of
BM-016.

---

## Usage

**BM-015 (initial)** — start 5h 59% / wk 88%, end 5h 94% / wk 94%,
delta +35% / +6% (claude-opus-5, effort xhigh).

**BM-015-corrections** — start 5h 8% / wk 95%, end 5h 19% / wk 97%,
delta +11% / +2% (claude-opus-5, effort xhigh).

Most of the initial delta went to investigating the failed live setting writes.
That investigation reached the wrong conclusion — the Settings API was blamed
after reading only the `SetSettingValue<>` template and stopping before the
setter methods. The supervisor's independent source inspection identified the
real cause (discarded `Addon`, weak-referenced `CAddonSettings`), which this
correction round implements and documents.

See `.agent/USAGE_HISTORY.md` for the appended rows.
