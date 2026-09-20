# Configuration Packages — v1 Reference

A **configuration package** supplies the desired *values* for the configuration
a Build Manager manifest declares. The manifest says **what** Build Manager
owns; packages say **what those things should be**.

Implementation: [`resources/lib/config.py`](../resources/lib/config.py) (BM-015)
Manifest declarations: [`docs/MANIFEST.md`](MANIFEST.md) §`config`

---

## Design principles

- **The manifest is the authority.** A package is data. A package can never
  grant itself permission to change anything the manifest has not declared.
- **Public only.** Packages never contain credentials, tokens, passwords, OAuth
  state, or any other secret.
- **Fail closed.** Anything malformed, unsafe, undeclared or unresolvable is
  rejected before a single value is written.
- **Verified.** Every applied value is read back and compared; a write that
  cannot be confirmed is a failure, not a success.
- **Idempotent.** Applying an already-correct configuration changes nothing.

---

## Directory layout

BM-015 supports **embedded/local packages only**. They ship inside the add-on:

```
resources/config/packages/<package-id>/
    package.json
    files/
        ...
```

`ConfigPackageLoader(default_packages_root())` resolves that directory relative
to the installed add-on, so it is correct wherever Kodi installed Build Manager.
A different root can be passed for tests.

Remote or versioned package delivery is deliberately out of scope and can be
added by a later task without changing this format.

### Package IDs

```
[a-z0-9][a-z0-9._-]*        maximum 64 characters
```

A package ID is an identifier, never a path. Rejected: empty values, non-strings,
uppercase, leading dots, whitespace (leading, trailing, internal, or only),
null bytes, `/`, `\`, absolute paths, `..` anywhere in the value, and anything
longer than 64 characters. The loader additionally confirms that the resolved
package directory is still inside the package root.

---

## Descriptor — `package.json`

```json
{
  "schema_version": 1,
  "id": "example-common",

  "settings": [
    {
      "target": "addon",
      "addon_id": "plugin.video.example",
      "key": "quality",
      "type": "string",
      "value": "1080p"
    },
    {
      "target": "skin",
      "addon_id": "skin.arctic.fuse.3",
      "key": "HomeSwitcher.EnableIcons",
      "type": "bool",
      "value": true
    },
    {
      "addon_id": "plugin.video.example",
      "key": "enabled_feature",
      "type": "bool",
      "value": true
    },
    {
      "addon_id": "plugin.video.example",
      "key": "limit",
      "type": "int",
      "value": 20
    },
    {
      "addon_id": "plugin.video.example",
      "key": "ratio",
      "type": "number",
      "value": 1.5
    }
  ],

  "files": [
    {
      "source": "files/example.json",
      "destination": "addon_data/plugin.video.example/example.json"
    }
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | Must be the integer `1`. Booleans are rejected. |
| `id` | yes | Must be a valid package ID **and** equal the directory name. |
| `settings` | no | Defaults to `[]`. |
| `files` | no | Defaults to `[]`. |

Unknown fields are rejected — at the top level, in a settings entry, and in a
files entry. This keeps a package from smuggling in directives (hooks, modes,
secret references) that the engine would silently ignore.

### Settings entry

| Field | Notes |
|---|---|
| `target` | Optional explicit namespace: `addon` (default, backward compatible) or `skin`. Skin entries use Kodi's active-skin API and must match a manifest scope with the same target. |
| `addon_id` | Must match `[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}`. |
| `key` | Must match `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. |
| `type` | One of `string`, `bool`, `int`, `number`. |
| `value` | Must be the exact JSON type for `type` (see below). |

### Files entry

| Field | Notes |
|---|---|
| `source` | Package-root-relative path to a regular file inside the package. |
| `destination` | Kodi profile-relative path, declared in `config.managed_files`. |

---

## Supported setting types

BM-015 supports exactly four types, mapped to Kodi's typed setting APIs:

| `type` | Required JSON value | Kodi read | Kodi write |
|---|---|---|---|
| `string` | string | `Settings.getString` | `Settings.setString` |
| `bool` | boolean | `Settings.getBool` | `Settings.setBool` |
| `int` | integer (never boolean) | `Settings.getInt` | `Settings.setInt` |
| `number` | number (never boolean) | `Settings.getNumber` | `Settings.setNumber` |

Type validation is exact and fails closed:

- `type: "string"` rejects numbers, booleans, `null`, arrays and objects.
- `type: "bool"` rejects `1`, `0`, `"true"` — only real JSON booleans.
- `type: "int"` rejects booleans (a boolean is not an integer here) and floats.
- `type: "number"` rejects booleans and accepts a JSON integer as a float.
- `NaN`, `Infinity` and `-Infinity` are rejected at JSON parse time.

Deliberately **not** supported: lists, arbitrary JSON object settings, binary
blobs, secret/reference values, expressions or templates, environment-variable
substitution, and shell expansion. These can be added when a real use requires
them — not before.

### The Settings wrapper, and why Addon lifetime matters

Build Manager uses the Kodi 20+ typed `Settings` wrapper — the current
recommended API — for **both** reads and writes:

```python
addon = xbmcaddon.Addon(addon_id)
settings = addon.getSettings()
settings.setString("quality", "1080p")      # addon still referenced here
```

The deprecated `Addon.setSettingString` / `setSettingBool` / `setSettingInt` /
`setSettingNumber` (deprecated since Kodi 20) are **not** used.

**The owning `Addon` object must stay referenced for as long as the `Settings`
wrapper derived from it is used.** Kodi's `CAddonSettings` reaches its owning
add-on through a *weak* reference. Once the `Addon` is released, the wrapper can
still serve in-memory reads and accept writes, but `Save()` can no longer reach
its owner. The failure is silent: the setter does not raise, in-memory state
changes, no `settings.xml` appears, a fresh handle does not see the value, and a
restart loses it.

This shape is the bug:

```python
def _settings_for(addon_id):          # WRONG
    addon = xbmcaddon.Addon(addon_id)
    return addon.getSettings()        # addon is released on return
```

An early BM-015 revision used exactly that helper, and live validation failed
every setting verification with no `settings.xml` written at all. The `Settings`
wrapper is not at fault: `Settings::setBool` / `setInt` / `setNumber` /
`setString` in `xbmc/interfaces/legacy/Settings.cpp` **do** call
`settings->Save()`, and `CAddonSettings::Save()` reaches the owning add-on's
`SaveSettings()`. The defect was the discarded `Addon`.

The backend therefore never returns a `Settings` wrapper from a helper: it
returns the `Addon`, and each accessor keeps it bound in its own frame across
the wrapper call.

Post-write verification remains mandatory regardless — the value is re-read
through a **fresh** `Addon`/`Settings` pair, so a persistence failure is caught
even when the setter returns normally.

Build Manager never edits a generated per-add-on `settings.xml` directly. It
owns selected keys, not the whole file.

### Number precision

Kodi serializes a number setting with the default `std::ostringstream` double
formatting — **6 significant digits** (`CSettingNumber::ToString`). So:

- a package `number` value that does not survive a 6-significant-digit round
  trip is **rejected at parse time** (a package can never request a value Kodi
  cannot store); and
- number settings are compared at exactly that precision.

`3.14159` is accepted; `3.1415926535` is rejected. This is a narrow comparison
tied to Kodi's own serialization, not a general floating-point tolerance.

---

## Package ordering and override semantics

Selected packages come from `config.packages`, which the profile resolver
(BM-004) has already merged into deterministic first-seen order:

```
base → platform → device → optional groups
```

Packages are applied in that order. For a target named by more than one
selected package — a `(target, addon_id, key)` setting or a file `destination` — the
**last package wins**:

```
common → tvos → bonus-room
```

`bonus-room` overrides `tvos`, which overrides `common`. Targets a later package
does not mention keep the earlier package's value. This supports per-platform
and per-device layering without any manifest schema change.

Duplicate package IDs in `config.packages` collapse to their first occurrence,
matching the resolver's union semantics.

**Inside a single package** there is no override semantics at all: duplicate
`(target, addon_id, key)` setting targets and duplicate file destinations are
rejected. An `addon` target and a `skin` target with the same `addon_id` and
`key` are distinct identities, but neither can satisfy the other's manifest
ownership declaration.
Neither first-wins nor last-wins — a package that contradicts itself is a bug.

### Determinism

The same packages in the same order always produce an identical effective
configuration. Output is sorted (settings by `(target, addon_id, key)`, files
by destination) because that ordering carries no meaning; package order is
preserved only where it decides precedence. No result depends on dict or set
iteration order.

---

## Ownership model

Build Manager's authority comes from `ResolvedBuild.config`, never from a
package.

**Declared setting targets** are every `(target, addon_id, key)` triple in
`config.managed_settings`. **Declared file targets** are the normalized paths in
`config.managed_files`.

After overlay resolution, the effective target set must **exactly equal** the
declared target set:

| Condition | Result |
|---|---|
| A package targets a setting the manifest does not declare | preflight fails |
| A package targets a file the manifest does not declare | preflight fails |
| The manifest declares a setting no package supplies | preflight fails — *unresolved managed configuration* |
| The manifest declares a file no package supplies | preflight fails — *unresolved managed configuration* |
| The two sets match | valid |

Requiring completeness in both directions avoids claiming ownership of a value
Build Manager cannot actually reconcile.

Anything not declared — other settings of the same add-on, sibling files in the
same directory, any other add-on — is never read and never written.

### Skin-setting runtime boundary

Entries with `target: skin` are handled by a dedicated adapter using Kodi's
`Settings.GetSkinSettingValue` and `Settings.SetSkinSettingValue` JSON-RPC
methods. The adapter verifies `xbmc.getSkinDir()` equals the declared
`addon_id` before reading or writing. It supports only explicit `bool` and
`string` targets, performs one-key writes, and the normal BM-015 manager reads
the value again through the adapter after every write. It never calls
`xbmcaddon.Addon(...).getSettings()` for a skin target and never edits the
skin's generated `settings.xml` directly.

---

## Preflight guarantee

`ConfigPackageLoader.resolve()` completes **all** of the following before
`ConfigurationManager.apply()` is ever called:

1. validate every package ID
2. load every selected package
3. validate every descriptor (schema version, id match, unknown fields)
4. validate every setting: add-on ID, key, type, exact value type
5. validate every source path and every destination path
6. read every source file (existence, regular-file check, containment)
7. resolve package overlays
8. validate manifest ownership
9. validate managed-target completeness

Only then may mutation begin. A malformed *later* package therefore cannot
leave an *earlier* package already applied — the run fails with zero mutations.

This is a **preflight guarantee, not transactional rollback**. Once `apply()`
begins, an individual operation can still fail (Kodi unavailable, read-only
filesystem); earlier successful operations are not undone. Each operation is
independently verified and reported, so the failure is always visible.

---

## File safety model

### Source paths

A package `source` must:

- be relative to the package root
- contain no `..` component, no null byte, no URI scheme, no UNC prefix, and no
  Windows drive letter
- stay inside the package root after normalization **and after symlink
  resolution**
- resolve to a regular file that exists and can be read

A symlink inside `files/` pointing outside the package is rejected, not
followed.

`package.json` itself obeys the same trust boundary: its real path must remain
inside the selected package directory, so a descriptor symlink cannot pull in a
document from elsewhere.

### Destination paths

A `destination` must:

- be a normalized relative path with no traversal
- carry no URI scheme — a package can never supply `special://`, `smb://`,
  `http://` or any other scheme
- never be an absolute OS path or a UNC path
- exactly match a normalized path in `config.managed_files`
- stay inside the translated Kodi profile root
- traverse **no symlink at all** (see below)

Destinations are **profile-relative**. They are resolved at runtime against
`special://profile/` using `xbmcvfs.translatePath` — never a hard-coded OS path.
`special://profile/addon_data/<addon-id>/...` is the current profile's add-on
data area. Kodi application and system directories are not valid destinations.

### Symlinks are never followed

A managed destination names that **exact filesystem path**, never an alias to
another file. If any existing path component beneath the profile root is a
symlink — a parent directory or the destination itself — the operation fails
closed. This holds whether the link points outside the profile or at a different
file inside it, and whether or not it is broken.

Following an in-profile symlink would let an explicitly declared managed path
redirect writes to an undeclared file, which breaks the ownership model just as
surely as escaping the profile would. Reads obey the same rule.

### Whole-file ownership

A path in `config.managed_files` means Build Manager owns the **entire file**,
so exact replacement is allowed for that path.

- Unknown sibling files in the same directory are never touched.
- Directories are never replaced recursively.
- Only explicitly declared paths are written.

### Atomic replacement

Desired bytes are written to a **securely created** temporary file in the
destination's own directory via `tempfile.mkstemp()`, which creates the file
with `O_CREAT|O_EXCL` and mode `0600`. The staging name is unique and
unpredictable, so a pre-existing symlink cannot capture the write before the
swap — a deterministic staging name such as `<dest>.bm-config-tmp` would be
exactly that hazard. The file is written, flushed, `fsync`ed and closed, then
moved into place with `os.replace()`, which overwrites atomically on both POSIX
and Windows. Because the staging file is always a sibling of the destination, no
cross-filesystem move occurs. The staging file is removed on every failure path,
and the original file is never deleted ahead of its replacement.

`xbmcvfs.rename()` is deliberately not used for the swap: Kodi documents it as
unable to move between filesystems on all platforms, and `CFile::Rename`
delegates straight to the platform handler with neither guaranteed overwrite
semantics nor a copy+delete fallback.

**Documented limitation:** this requires `special://profile/` to translate to a
local filesystem path. If translation yields a VFS URL, the backend fails closed
rather than falling back to a weaker mechanism. Every write is verified by
re-reading the destination either way.

---

## Deployment behaviour

### Settings

```
read current typed value
    ├─ equal to desired  → ALREADY_CORRECT (no write)
    └─ different         → write typed value
                           → read it back
                              ├─ exact match → UPDATED
                              └─ mismatch    → FAILED
```

- If the target add-on is not installed or cannot be opened, the operation
  fails clearly. BM-015 never installs an add-on — BM-011 owns installation.
- A Kodi API error is never converted into a default or empty value. Read
  failures, write failures and verification mismatches all produce `FAILED`.

### Managed files

```
read current bytes
    ├─ identical to desired → ALREADY_CORRECT (no write)
    ├─ different            → atomic replace → verify → UPDATED
    └─ absent               → create parents → atomic write → verify → CREATED
```

Verification requires **exact byte equality**. This does not conflict with the
project's rule against checksum-validating volatile or generated state: exact
content verification applies only to files Build Manager has explicitly declared
whole-file managed. Partially managed or Kodi-generated files — including
per-add-on `settings.xml` — are never verified this way.

### Idempotency

Applying the same configuration twice performs zero mutations the second time;
every operation reports `ALREADY_CORRECT`. Drift in either direction is repaired
on the next apply, and only the drifted targets are written.

---

## Results

`apply()` returns one `ConfigOperationResult` per effective target:

| Field | Meaning |
|---|---|
| `kind` | `SETTING` or `FILE` |
| `addon_id` / `key` | target, for settings |
| `destination` | target, for files |
| `package_id` | the package responsible for the final desired value |
| `status` | `ALREADY_CORRECT`, `UPDATED`, `CREATED`, `FAILED` |
| `expected_identity` | type-tagged digest of the desired value/content |
| `previous_identity` | digest of the previous state, or `None` when absent |
| `detail` | one-line diagnosis |

Aggregates: `all_applied`, `changed`, `unchanged`, `failed`, plus `settings`
and `files` views.

**Raw setting values and file contents never appear in a result.** Identities
are SHA-256 digests, so two runs can be compared without echoing what was
deployed. `addon_id`, `key` and `package_id` are normally enough to diagnose a
problem.

Digests are identities, not a confidentiality mechanism — a digest of a short
value is trivially reversible. They are not a substitute for the rule below.

---

## Secrets boundary

**Public configuration packages must never contain credentials.** Not tokens,
passwords, API keys, OAuth state, debrid credentials, Trakt credentials, or
EasyNews credentials.

BM-015 does not read `private_overlay` and has no notion of a secret value.
Portable authentication state is the subject of BM-017, which will define it
architecturally. There is deliberately **no heuristic secret detection** here —
a scanner would be a poor substitute for keeping secrets out of the public
package format in the first place.

Test fixtures use obviously synthetic, non-secret values.

---

## Skin boundary

`SkinEntry.config_packages` is resolved into the end of
`ResolvedBuild.config.packages` by BM-018B. BM-015 then applies the merged
selection through this same generic package/ownership/deployer pipeline. The
deepest winning skin supplies its package list; duplicate IDs are collapsed by
first-seen order. Skin-selected packages do not gain authority to modify
undeclared targets: `config.managed_settings` and `config.managed_files`
remain the ownership boundary. There is no separate skin package format.

The production `af3-common` package is a typed skin-target package for
`skin.arctic.fuse.3`. It contains the supervisor-approved common AF3 bool and
string policy only and has `files: []`; the exact key/value contract and the
six intentionally unmanaged reviewed candidates are recorded in
[`docs/AF3_PORTABILITY.md`](AF3_PORTABILITY.md). A manifest using it must
declare each exact skin target with `target: "skin"`. No package can claim
ownership merely by appearing in `skin.config_packages`.

---

## API

```python
from resources.lib.config import (
    ConfigPackageLoader,
    ConfigurationManager,
    KodiRuntimeConfigurationBackend,
    default_packages_root,
)

loader = ConfigPackageLoader(default_packages_root())
effective = loader.resolve(desired.config)          # full preflight

manager = ConfigurationManager(KodiRuntimeConfigurationBackend())
result = manager.apply(effective)                    # verified deployment

if not result.all_applied:
    for failure in result.failed:
        log(f"{failure.target}: {failure.detail}")
```

`desired.config is None` resolves to a clean empty no-op; a config that declares
nothing and selects no packages does too. `apply()` of an empty configuration
makes no backend calls at all.

### Errors

| Exception | Raised when |
|---|---|
| `ConfigPackageError` | a package is missing, malformed, or unsafe |
| `ConfigOwnershipError` | ownership or completeness is violated |
| `ConfigBackendError` | a Kodi runtime or filesystem operation failed |
| `ConfigAddonUnavailableError` | a targeted add-on is not installed / cannot be opened |

The first two are preflight failures raised by `resolve()` — zero mutations. The
last two surface as `FAILED` operations inside `apply()`.

### Effective configuration identity

`EffectiveConfiguration.identity` is a deterministic SHA-256 fingerprint of the
desired configuration. It covers:

- the ordered selected package IDs
- per setting target: `addon_id`, `key`, setting type, the desired value's
  type-tagged digest, and the winning package ID
- per file target: destination, desired content digest, and the winning package ID

Raw values never appear — settings contribute their digest, files theirs.

Scope alone is not an identity. A package whose desired value changes from
`720p` to `4k` keeps exactly the same managed scope, so the fingerprint is what
distinguishes one resolution from another. Changing a desired value, a setting
type, file content, the package order, or which package wins a target all change
the identity.

### Validation state for BM-014

`result.validation_state` is an immutable `ConfigurationValidationState` naming
the full managed scope that was applied, the subset verified correct, and the
`effective_identity` it was produced from.

BM-014 needs **both** artifacts:

```python
validate_build_state(
    desired, actual, dependency_closure,
    configuration_state=result.validation_state,
    effective_configuration=effective,
)
```

BM-014 stays read-only and never resolves packages itself — it receives the
already-resolved `EffectiveConfiguration` as an immutable expected snapshot.
Four gates must pass before any PASS/FAIL is emitted:

| # | Gate |
|---|---|
| 1 | effective package selection corresponds to `desired.config.packages` |
| 2 | effective target scope equals the declared managed scope |
| 3 | snapshot scope equals the effective scope |
| 4 | snapshot `effective_identity` equals `EffectiveConfiguration.identity` |

Any gate failure — including a missing artifact — yields **NOT_CHECKED, never
FAIL**. A stale or unrelated artifact is not evidence of current Kodi drift.
Gate 4 is what scope comparison alone cannot do: without it, a snapshot from a
prior resolution with the same scope would produce a false PASS.

---

## Example: layering common → platform → device

Manifest:

```json
"config": {
  "packages": ["af3-common"],
  "managed_settings": [
    {"addon_id": "plugin.video.example", "keys": ["quality", "limit"]}
  ],
  "managed_files": ["addon_data/plugin.video.example/menu.json"]
},
"platform_profiles": {
  "tvos": {"config": {"packages": ["af3-tvos"]}}
},
"device_profiles": {
  "bonus-room": {"extends": "tvos", "config": {"packages": ["af3-bonus-room"]}}
}
```

Resolved package order for `bonus-room`:

```
af3-common → af3-tvos → af3-bonus-room
```

| Target | `af3-common` | `af3-tvos` | `af3-bonus-room` | Effective |
|---|---|---|---|---|
| `quality` | `720p` | `1080p` | — | `1080p` (af3-tvos) |
| `limit` | `20` | — | `50` | `50` (af3-bonus-room) |
| `menu.json` | base | — | device menu | device menu |

All three declared targets are supplied, so preflight succeeds. Had
`af3-bonus-room` also set `plugin.video.example/api_host`, preflight would fail:
that key is not in `managed_settings`.
