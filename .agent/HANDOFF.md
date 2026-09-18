# Agent Handoff — BM-015 Complete (Pending Supervisor Review)

**Date**: 2026-09-18
**Agent**: Claude (claude-opus-5, effort xhigh)
**Status**: BM-015 complete on `agent/claude`. NOT merged to `matrix`. BM-016 not started.

---

## Result

BM-015 (prototype configuration deployment) is implemented, unit-tested,
live-validated and documented.

- **Unit tests**: 1346/1346 pass (was 1129; +217)
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
| `3d61f5e` | chore: record BM-015 complete (1346/1346 tests, 24/24 live) |

## Files created / modified

**Created**
- `resources/lib/config.py` — the BM-015 module
- `resources/config/packages/README.md` — embedded package root
- `tests/test_config.py` — 202 tests
- `docs/CONFIG_PACKAGES.md` — package format reference

**Modified**
- `resources/lib/validator.py` — optional `configuration_state` parameter
- `tests/test_validator.py` — +15 tests (97 total)
- `tools/kodi_test.py` — `validate-config` live sequence + disposable runner
- `docs/MANIFEST.md` — "Config package format" open question resolved
- `docs/TESTING.md` — `validate-config` documentation
- `.agent/USAGE_HISTORY.md`, `.agent/CURRENT_TASK.md`, `.agent/AGENT_STATUS.json`

---

## Kodi Settings API persistence discovery

**This is the most important finding of the task and should survive into any
future settings work.**

The first live run failed **every** setting verification and produced no
`settings.xml` at all, while the managed-file operation succeeded.

**Finding**: in Kodi 21 (Omega), the Kodi 20+ typed `Settings` wrapper obtained
from `xbmcaddon.Addon(id).getSettings()` **does not persist writes**.
`SetSettingValue()` in `xbmc/interfaces/legacy/Settings.cpp` calls
`setting->SetValue(value)` and returns — there is **no `Save()` call**. Values
written through `setString` / `setBool` / `setInt` / `setNumber` mutate only the
in-memory `CSetting`, are not written to the add-on's `settings.xml`, and are not
observable from a fresh `Addon` handle or after a restart. The setters do not
raise and (in this build) give no failure signal.

**Mechanism used instead**: the typed `Addon` setters —
`setSettingString` / `setSettingBool` / `setSettingInt` / `setSettingNumber` in
`xbmc/interfaces/legacy/Addon.cpp` — which call `addon->SaveSettings()` after
updating the value and do persist.

**Production backend (`KodiRuntimeConfigurationBackend`) therefore**:

| Direction | API |
|---|---|
| read | `xbmcaddon.Addon(id).getSettings().getString/getBool/getInt/getNumber` |
| write | `xbmcaddon.Addon(id).setSettingString/setSettingBool/setSettingInt/setSettingNumber` |

Both are typed APIs; only one stores a value. No generated per-add-on
`settings.xml` is ever edited directly. `tests/test_config.py` pins this with a
stubbed `xbmcaddon` whose wrapper setters fail the test if ever called.

Related verified detail: `CSettingNumber::ToString()` uses default
`std::ostringstream` double formatting — **6 significant digits**. BM-015 rejects
package `number` values that do not survive that round trip and compares numbers
at exactly that precision.

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
`xbmcvfs.translatePath`; staged sibling temp file + `os.replace()` (atomic on
POSIX and Windows, never cross-filesystem). `xbmcvfs.rename()` is deliberately
avoided — Kodi documents it as unable to move across filesystems on all
platforms and `CFile::Rename` has no overwrite guarantee or fallback. Fails
closed if the profile root does not translate to a local path.

**Secrets**: `private_overlay` is never read. Results carry SHA-256 content
identities, never raw setting values or file bytes. No heuristic secret
detection — BM-017 owns credential portability.

**Skin**: `SkinEntry.config_packages` is NOT deployed. Only
`desired.config.packages` is applied. BM-018 can reuse the loader/deployer.

---

## BM-014 integration — Option A

`ConfigApplyResult.validation_state` returns an immutable
`ConfigurationValidationState` (full applied scope + the verified subset).
`validate_build_state()` gained an optional `configuration_state` parameter.

| Case | Result |
|---|---|
| `desired.config is None` | no CONFIGURATION checks |
| config present, snapshot `None` | NOT_CHECKED (unchanged behaviour) |
| snapshot scope == declared managed scope | PASS/FAIL per declared target |
| snapshot empty / partial / unrelated | NOT_CHECKED (scope mismatch) |

Scope comparison is set equality, mirroring BM-014's dependency-root discipline.
BM-014 remains strictly read-only and never claims configuration is validated
merely because `apply()` succeeded. All three behaviours are proven live.

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

Start: 5h 59% / wk 88% (claude-opus-5, effort xhigh — observed, matches the
requested Opus preference).
End: 5h 94% / wk 94%.
Delta: +35% / +6%.

Most of the delta went to the Kodi Settings API investigation: the first live
run failed every setting verification, which required reading the Kodi source to
establish that the documented modern wrapper does not persist.

See `.agent/USAGE_HISTORY.md` for the appended row.
