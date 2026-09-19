# Arctic Fuse 3 Portability Inventory

Status: BM-018C research specification. No AF3 configuration package is
created by this task.

This document defines the evidence-backed boundary for a future
`af3-common` package and identifies state that must remain in a platform or
device overlay, remain private, or remain unmanaged. It is a desired-state
specification, not a backup manifest. Current Eric-specific values are not
reproduced here.

## Decision summary

The minimal safe common subset is typed AF3 skin preferences only. It contains
no whole-file replacement and no menu/widget or viewtype payload in its first
version.

| State | BM-018C decision |
|---|---|
| `addon_data/skin.arctic.fuse.3/settings.xml` | Do not manage as a whole file. Use typed setting targets after BM-018D adds a skin-settings backend. |
| `addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/*.json` | Personal, non-secret source state. Exclude from `af3-common`; a later curated overlay may manage selected files after sanitization and lifecycle testing. |
| `addon_data/script.skinvariables/*-viewtypes.json` | `GENERATED_RUNTIME`; exclude. AF3 rebuild behavior recreates it. |
| `addon_data/script.skinvariables/logins/...` | `PRIVATE_OR_SECRET`; exclude. BM-017 owns authentication portability. |
| Generated `special://skin/.../script-*.xml` includes | `GENERATED_RUNTIME`; exclude. Rebuild them from source definitions. |
| Stable bool/enum-like skin preferences | Candidates for `PUBLIC_PORTABLE` in `af3-common`, subject to explicit value review. |
| Home/menu/widget labels, paths, targets, icons and queries | `PERSONAL_PORTABLE_NONSECRET`, `DEVICE_SPECIFIC`, or `UNKNOWN_NEEDS_TESTING`; never silently copied into common. |

The common package should be empty of files initially. Its first approved
payload should be a short allowlist of typed bool/string targets, with values
chosen as build policy rather than copied from the live profile.

## Evidence snapshot

### Installed add-ons

The current installed skin is:

- add-on ID: `skin.arctic.fuse.3`
- name: Arctic Fuse 3
- installed version: `3.2.19`
- required `script.skinvariables`: `2.2.2`
- required `script.texturemaker`: `0.2.9`
- required `plugin.video.themoviedb.helper`: `6.14.3` or newer; the current
  installed helper is `6.17.1`

The current installed profile contained:

```text
addon_data/skin.arctic.fuse.3/settings.xml
addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/
addon_data/script.skinvariables/skin.arctic.fuse.2-viewtypes.json
addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json
addon_data/script.skinvariables/skin.arctic.horizon.2-viewtypes.json
```

The observed AF3 settings file has 280 typed entries: 121 `bool` and 159
`string`. Six entries are build fingerprints with `script-skin...-hash` or
`script-skin...-checksum` suffixes. Those six are not user preferences.

The local AF3 checkout used for source tracing declares version `3.2.15` and
has pre-existing working-tree changes. The installed add-on at `3.2.19` is
the authoritative version observation for this inventory; the checkout is
source evidence only and was not modified.

### AF3 and helper ownership

AF3's `addon.xml` identifies `script.skinvariables` as a required helper. The
AF3 skin also calls the helper for shortcut/template generation and view
configuration. The installed `script.skinvariables` source identifies these
profile locations:

```text
special://profile/addon_data/script.skinvariables/nodes/
special://profile/addon_data/script.skinvariables/<skin>-viewtypes.json
special://profile/addon_data/script.skinvariables/logins/
```

The owner of those paths is `script.skinvariables`, not AF3. AF3 supplies the
packaged source templates under its own `shortcuts/` directory and consumes
the helper's generated output. Build Manager must preserve that ownership
boundary.

AF3 also integrates with optional or adjacent add-ons through fixed IDs and
plugin paths, including TMDb Helper, Up Next, Artist Slideshow, Arctic Mirage,
and platform settings services. A reference to an add-on ID is not an
authentication grant. The referenced add-on's own settings, cache, account,
and private state remain outside this package.

## Source and lifecycle findings

### Typed skin settings

AF3 writes skin settings through Kodi skin builtins such as
`Skin.SetBool(...)`, `Skin.SetString(...)`, `Skin.SetPath(...)`, and
`Skin.SetNumeric(...)`. Kodi persists all of the observed AF3 entries in the
skin settings map as `bool` or `string`; numeric-looking values such as OSD
timeouts are still stored as strings.

The source has no stable declarative defaults file equivalent to an add-on's
settings definition. Defaults are established by first-run and on-load rules
in the skin and by helper-generated actions. Therefore the current-vs-default
column below is intentionally `unknown` unless the state is demonstrably a
runtime marker. The current value itself is never printed in this document.

Build Manager's BM-015 package format already supports `string`, `bool`, `int`,
and `number` typed values and insists on read-back verification. Its current
runtime backend, however, opens Kodi add-on settings through
`xbmcaddon.Addon(...).getSettings()`. That API is not the AF3 skin-setting map.
BM-018D must add an explicit, typed skin-setting backend/target (or an equally
strict adapter) before an AF3 setting can be placed in a real package.

### Menus and widgets

The authoritative editable menu/widget source is the JSON under
`script.skinvariables`'s per-skin `nodes/` directory. The installed AF3
profile contains separate files for home submenu, home widgets, search
widgets, power menu, and numbered menu/widget groups. The JSON objects contain
stable-looking `guid`, `label`, `icon`, `path`, and `target` fields; widget
objects also contain widget style/autoscroll fields, while submenu objects can
contain nested submenu/widget arrays.

The current files use portable `special://` paths and `plugin://` targets in
some entries, and no HTTP URL, SMB/NFS URL, absolute path, or credential-like
field was observed in the inspected payloads. That is an observation of this
profile, not a safe general rule: the editor permits arbitrary paths, actions,
icons, targets, and plugin parameters. A future package validator must inspect
every string and reject credentials, absolute paths, private shares, and
unsupported schemes rather than assuming that all menu JSON is portable.

The menu/widget definitions are direct authored source for the helper, but
they are Eric-specific preferences in the current profile. Their ordering and
GUIDs are stable enough for source-level editing, not evidence that they are
appropriate for a public common package. A curated package must choose a
canonical menu definition and verify it against the exact AF3/helper versions
and installed add-on IDs.

### View configuration

`script.skinvariables` reads `special://skin/shortcuts/skinviewtypes.json` as
the AF3 source definition and writes the selected per-skin mapping to:

```text
special://profile/addon_data/script.skinvariables/<skin>-viewtypes.json
```

The helper then generates `script-skinviewtypes-includes.xml` in the active
skin's resolution folder. Its source code reads the JSON, merges default
content mappings, writes the JSON mapping, writes the generated include and
reloads the skin. The current AF3 mapping names installed plugin IDs including
TMDb Helper and other video add-ons, so it is not a neutral common default.

The historical Backup Pro investigation independently observed that the
`*-viewtypes.json` file is recreated during AF3 rebuild and excluded it from
the managed source set. That evidence is consistent with the helper source:
the mapping is input to a rebuild, while the generated XML and its hash/checksum
are runtime products. Build Manager should not own either the viewtype JSON or
the generated include in `af3-common`.

### Rebuild and reload behavior

The helper source proves the following lifecycle:

1. Read the AF3 packaged source templates and current helper data.
2. Generate XML include files into the active skin.
3. Write helper-owned profile JSON where a user selection is persisted.
4. Write hash/checksum markers into the skin settings map.
5. Reload the skin.

AF3 itself invokes helper routes for startup, shortcut template generation and
view construction. A future file-owning overlay must therefore stage and
validate source files while AF3 is inactive, activate AF3 through the existing
safe skin lifecycle, invoke the helper's public rebuild route, reload, and
verify live state. It must never treat generated includes, hashes, checksums,
or caches as desired state.

## Typed setting inventory

Each row is a candidate target, not an authorization to publish its current
value. `Present` means the key was observed in the current settings map; the
value is intentionally omitted. `Unknown` in the default column means that
the source establishes defaults through actions or conditional first-run
behavior rather than a safe declarative default.

### Public portable candidates

These keys are stable, non-secret, platform-independent UI behavior. They are
the only typed candidates currently suitable for consideration in
`af3-common`, and even these require a supervisor-approved value set.

| Key | Kodi type | Purpose | Classification | Current differs from default | Platform/device dependent |
|---|---|---|---|---|---|
| `HomeSwitcher.Vertical` | bool | Main menu orientation | `PUBLIC_PORTABLE` | Present; unknown | No evidence |
| `HomeSwitcher.EnableIcons` | bool | Main menu icon mode | `PUBLIC_PORTABLE` | Present; unknown | No |
| `HomeSwitcher.EnableIconText` | bool | Main menu icon + text mode | `PUBLIC_PORTABLE` | Present; unknown | No |
| `HomeSwitcher.DisableHeader` | bool | Hide the home header | `PUBLIC_PORTABLE` | Present; unknown | No |
| `HomeSwitcher.DisableDate` | bool | Hide the home date | `PUBLIC_PORTABLE` | Present; unknown | No |
| `HomeSwitcher.DisableSearch` | bool | Hide search from the main menu | `PUBLIC_PORTABLE` | Present; unknown | No |
| `HomeSwitcher.DisableFirstWidgetFocus` | bool | Do not focus the first widget at startup | `PUBLIC_PORTABLE` | Present; unknown | No |
| `HomeSwitcher.LoopBack` | bool | Loop menu navigation | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Spotlight.EnableSlide` | bool | Enable spotlight sliding | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Spotlight.UseMenuButton` | bool | Spotlight button behavior | `PUBLIC_PORTABLE` | Present; unknown | No |
| `View.UseDetailedListLabels` | bool | Use detailed list labels | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Widgets.EnableShowMore` | bool | Show widget “more” entries | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Widgets.DisableNoResultsItem` | bool | Suppress empty-widget entries | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Navigation.OnBack` | string | Back-navigation policy; enum-like values | `PUBLIC_PORTABLE` | Present; unknown | No |
| `OSD.AutoOnPause` | string | OSD behavior on pause; enum-like values | `PUBLIC_PORTABLE` | Present; unknown | No |
| `OSD.AutoOnPause.Delay` | string | OSD pause delay; enum-like values | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Seekbar.TimeDisplay` | string | Seekbar time display mode | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Plotline.Movie` | string | Movie plotline mode | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Plotline.TVShow` | string | TV plotline mode | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Mouse.PointerSize` | string | Pointer-size enum | `PUBLIC_PORTABLE` | Present; unknown | No |
| `SeasonalTheme.PropsDensity` | string | Seasonal props density enum | `PUBLIC_PORTABLE` | Present; unknown | No |
| `Skin.FlixArt.Size` | string | FlixArt size enum | `PUBLIC_PORTABLE` | Present; unknown | No |

`HomeSwitcher.EnableIcons` and `HomeSwitcher.EnableIconText` are mutually
exclusive modes in the AF3 UI. A package must not set contradictory values;
BM-018D should validate the mode relationship before mutation.

### Personal but technically portable candidates

These are non-secret and can be copied between compatible AF3 installations,
but they encode Eric's content choices or menu design. They must not enter the
public common package without an explicit review of the exact values.

| Key/family | Kodi type | Purpose | Classification | Current differs from default | Platform/device dependent |
|---|---|---|---|---|---|
| `HomeSwitcher.<window>.Name` | string | Personalized menu labels | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | No, but personal |
| `HomeSwitcher.<window>.Mode` | string | Per-menu layout mode | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | Usually no |
| `HomeSwitcher.<window>.Icon` | string | Menu icon choice | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | If custom path, yes |
| `HomeSwitcher.<window>.Spotlight.Label` | string | Personalized spotlight label | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | No, but personal |
| `HomeSwitcher.<window>.Spotlight.SortMethod` | string | Spotlight sort choice | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | No |
| `CustomRating.Movies.Item01..06` | string | Rating-provider ordering | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | Depends on installed providers |
| `CustomRating.TVShows.Item01..06` | string | Rating-provider ordering | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | Depends on installed providers |
| `DialogInfo.Movies.Item01..03` | string | Movie info-provider ordering | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | Depends on installed providers |
| `DialogInfo.TVShows/others.Item01..03` | string | Other info-provider ordering | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | Depends on installed providers |
| `OptionsTiles.<01..04>.Include` | string | Settings/options tile selection | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | No, but personal |
| `OptionsTiles.<01..04>.Label` | string | Custom tile labels | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | No, but personal |
| `OptionsTiles.Layout` | string | Options tile layout | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | No |
| `Background.DialogImage` | string | Dialog background preset or path | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | Custom paths may be device-specific |
| `Focuscolor.name` and `watchedprogresscolor.name` | string | Custom UI colors | `PERSONAL_PORTABLE_NONSECRET` | Present; unknown | No |

The same family may move to `DEVICE_SPECIFIC` when its value is a local path
or an action that names a device-local resource.

### Device-specific candidates

These keys may be useful in a future device overlay but must not be placed in
`af3-common`:

| Key/family | Kodi type | Reason |
|---|---|---|
| `Startup.ImageFolder` | string | User-selected image directory can be local, removable, SMB, or device-specific. |
| `Startup.VideoPath` | string | User-selected startup video path is inherently location-dependent. |
| `Background.Image` / `Background.MultiImage` | string | Built-in `special://skin` values are portable, but the same fields accept custom paths. |
| `HomeSwitcher.<window>.Shortcut.Path` | string | May be a local file, playlist, source, or device-specific action. |
| `HomeSwitcher.<window>.Spotlight.Path` | string | May reference a local playlist or source. |
| `OptionsTiles.<01..04>.Path` | string | May reference local files, sources, or playlists. |
| Menu/widget JSON `path`, `target`, `icon` and action fields | JSON strings | Exact values can embed device-local locations or installed-add-on assumptions. |

The package format currently rejects URI-style file destinations and has no
path-aware value policy for string settings. BM-018D must add an explicit
allowlist/validator before any device-specific string is authorized.

### Generated runtime settings

These entries are observed or source-proven helper/runtime state. They must
never be declared as desired configuration:

| Key/family | Kodi type | Producer/evidence |
|---|---|---|
| `DefaultConfig.InitDone` | bool | AF3 startup first-run guard writes it after default initialization. |
| `Home.FirstRun` | bool | AF3 home on-load guard writes it after first-run actions. |
| `Shortcuts.RebuildDateTime` | string | AF3 shortcut/settings screens update it to trigger rebuild work. |
| `SkinConstant.Numeric.00..19` | string | AF3 startup fills internal numeric slots for generated expressions. |
| `script-skinvariables-*-hash` | string | `script.skinvariables` build fingerprints. |
| `script-skinviewtypes-hash` | string | Viewtype generator fingerprint. |
| `script-skinviewtypes-checksum` | string | Generated viewtype include checksum. |
| Generated `script-skinvariables-*.xml` | file | Helper output written into the active skin. |
| Generated `script-skinviewtypes-includes.xml` | file | Helper output rebuilt from viewtype source/mapping. |

Backup Pro live evidence found that the viewtype hash and checksum can appear
in the live settings map after AF3 reactivation/rebuild even though they are
not real user changes. This is a direct reason to exclude the fingerprint
family rather than attempting to stabilize it in a package.

### Private or secret state

| State | Classification | Boundary |
|---|---|---|
| `addon_data/script.skinvariables/logins/<skin>/...` | `PRIVATE_OR_SECRET` | Skin Variables supports login/profile data and pin-code protection. Exclude; BM-017 owns authentication portability. |
| `addon_data/script.skinvariables/nodes/<skin>-user-<slug>/...` when tied to a protected skin profile | `PRIVATE_OR_SECRET` or `PERSONAL_PORTABLE_NONSECRET` | Do not infer from the filename alone. Require explicit profile review; never publish login-bearing data. |
| TMDb Helper, Trakt, MDBList, provider and resolver account state | `PRIVATE_OR_SECRET` | Owned by those add-ons and outside AF3. Do not copy through an AF3 package. |
| Authenticated URLs or query parameters in menu/widget JSON | `PRIVATE_OR_SECRET` | Reject during validation and redact from all reports. |

No raw credential or authenticated value was printed during this inventory.
The current installed profile did not expose a `logins/` directory, but the
helper source and Backup Pro contract prove that the path is a supported state
family and must remain excluded.

## Whole-file inventory

Build Manager should own a whole file only when exact replacement is the
semantic source-of-truth and the lifecycle can safely rebuild consumers.

| Profile-relative path | Owner/producer | Source-of-truth or output | Exact whole-file ownership | Classification | Decision/evidence |
|---|---|---|---|---|---|
| `addon_data/skin.arctic.fuse.3/settings.xml` | Kodi skin settings store | Persisted representation of skin settings, but not a safe live authority | No | `UNKNOWN_NEEDS_TESTING` as a file candidate | Use typed live settings; Backup Pro deliberately reads Kodi's live typed map instead of trusting this file. |
| `addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/*.json` | `script.skinvariables` | Authored menu/widget source | Only for a future curated overlay | `PERSONAL_PORTABLE_NONSECRET` / `UNKNOWN_NEEDS_TESTING` | Helper reads/writes these files directly; current payload is personalized and values require scheme/add-on/path validation. |
| `addon_data/script.skinvariables/nodes/skin.arctic.fuse.3-user-<slug>/*.json` | `script.skinvariables` | Per-skin-user menu/widget source | Not in common; possible reviewed private/personal overlay | `UNKNOWN_NEEDS_TESTING` | User profile slug and content need explicit review; protected profiles may be private. |
| `addon_data/script.skinvariables/<skin>-viewtypes.json` | `script.skinvariables` | Rebuild input/mapping cache | No | `GENERATED_RUNTIME` | Backup Pro observed recreation during rebuild and excluded it from the durable managed set. |
| `addon_data/script.skinvariables/logins/<skin>/*.json` | `script.skinvariables` | Login/profile state | No | `PRIVATE_OR_SECRET` | Authentication boundary; BM-017. |
| `special://skin/shortcuts/*.json` | AF3 add-on package | Packaged source templates | No profile ownership | `PUBLIC_PORTABLE` as add-on content, not config | Installed with the exact skin version. Do not duplicate into a config package. |
| `special://skin/1080i/script-skinvariables-*.xml` | `script.skinvariables` | Generated include output | No | `GENERATED_RUNTIME` | Rebuilt from AF3/helper source; hashes track it. |
| `special://skin/1080i/script-skinviewtypes-includes.xml` | `script.skinvariables` | Generated viewtype output | No | `GENERATED_RUNTIME` | Source code writes it from `skinviewtypes.json` and mapping data, then reloads. |
| `addon_data/script.skinvariables/log_request/*` | `script.skinvariables` | Diagnostic request log/cache | No | `GENERATED_RUNTIME` | Not a desired AF3 setting; may contain request metadata. |
| `addon_data/service.skinsettings.backup/*` | Skin Settings Backup | Locks, staging, rollback and operation state | No | `GENERATED_RUNTIME` | Belongs to the backup service, not Build Manager or AF3. |

## Menus/widgets and view portability rules

Before a future helper-source overlay is accepted, every JSON string must pass
these checks:

- reject credentials, tokens, password-like keys, authenticated URLs and
  private service state;
- reject absolute paths, `smb://`, `nfs://`, local mounts and unknown URI
  schemes unless a device overlay explicitly owns the value;
- allow `plugin://` only when the referenced add-on ID is declared and enabled
  by the desired build;
- allow `special://skin/...` only for assets shipped by the exact AF3 version;
- preserve GUIDs and ordering within a curated file, then verify after helper
  rebuild that the live menu/widget source is unchanged;
- never include generated XML, hashes, checksums, Kodi window properties or
  helper caches in the package;
- verify the helper version and AF3 version before applying the source.

Viewtype mappings are especially sensitive to installed add-on IDs. The
current profile contains mappings for TMDb Helper and other provider add-ons;
that is not evidence that every AF3 installation should receive those
mappings. A standard build may choose a curated mapping only after its add-on
dependencies are declared and the generated output is verified.

## Future package specification

### `af3-common`

BM-018D should create `af3-common` only after a supervisor-approved value set
exists. Its v1 contract is:

```text
settings:
  target family: skin.arctic.fuse.3 typed skin settings
  allowed types: bool, string
  allowed keys: the PUBLIC_PORTABLE table above, minus any key rejected by
                value-specific or cross-setting validation
files: []
```

The package must not contain:

- the live `settings.xml` file;
- any current-value dump copied from Eric's profile;
- home/menu/widget JSON;
- viewtype JSON;
- generated XML, hashes, checksums, caches, log-request output or rollback
  state;
- provider, TMDb, Trakt, MDBList or other authentication state;
- paths, URLs, actions or labels that were not explicitly reviewed.

The manifest declaration should use `skin.config_packages: ["af3-common"]`
as already supported by BM-018B, plus `config.managed_settings` entries for
every exact `(skin.arctic.fuse.3, key)` target supplied by the package. No
undeclared setting may be silently accepted. The package values should be
written as normal BM-015 typed values once BM-018D supplies the skin-settings
backend and post-write verification.

### Future personal, platform and device overlays

Use the existing package layering order:

```text
af3-common -> af3-<platform> -> af3-<device>
```

The current evidence does not justify a non-empty platform package. Create one
only when a setting is proven to vary by operating system or rendering
environment, such as a verified screen/layout choice. Do not infer platform
specificity from the Mac profile.

A device package may eventually own reviewed local paths, custom background
locations, or a device-specific menu/widget source. It must declare those
files/keys separately and never broaden `af3-common`. A device package still
cannot contain secrets; private authentication remains a separate BM-017
boundary.

## BM-018D implementation and validation requirements

BM-018D should not start from whole-file copying. It should implement and test:

1. A typed AF3 skin-setting backend that reads the active skin's bool/string
   map, validates the requested skin ID, writes one owned key at a time, and
   reads each value back through a fresh handle or equivalent authoritative
   route.
2. Ownership declarations that distinguish an AF3 skin-setting target from a
   normal add-on setting while preserving BM-015's fail-closed package and
   manifest checks.
3. Cross-setting validation for mutually exclusive menu modes and enum/value
   allowlists for the common table.
4. A file overlay transaction for any future helper source: validate all JSON,
   stage while AF3 is inactive, preserve rollback state, activate/reload,
   rebuild through the helper's supported route, and verify live source and
   generated fingerprints without managing the generated products.
5. Disposable Kodi-profile tests for a clean profile, AF3 active, AF3
   inactive, missing helper, missing referenced add-on, stale generated output,
   malformed JSON, path/URI rejection, private-looking values, and rebuild
   persistence. Do not use Family Rm, Bonus Rm, or Apple TV profiles.

The BM-018C research itself performed no Kodi writes, no helper rebuild, no
skin switch, and no Apple TV access. Those remain validation work for the
future implementation task.

## Evidence index

Primary installed evidence:

- AF3 `addon.xml`: installed ID/version and dependencies.
- AF3 `1080i/Includes_SkinSettings.xml`, `Home.xml`, `Includes_Actions.xml`,
  `Includes.xml`, and `shortcuts/skinvariables-*.json`: setting writers,
  menu/widget source, helper routes, generated include names and lifecycle.
- `addon_data/skin.arctic.fuse.3/settings.xml`: typed key/type inventory only;
  current values were not copied into this document.
- `addon_data/script.skinvariables/nodes/` and `*-viewtypes.json`: observed
  helper-owned profile layout and sanitized structural counts.

Helper source evidence:

- `script.skinvariables/resources/lib/skinvariables.py`: generated include
  construction, hash comparison, write and `ReloadSkin()` behavior.
- `script.skinvariables/resources/lib/viewtypes.py`: per-skin viewtype JSON,
  generated include, checksum/hash and reload behavior.
- `script.skinvariables/resources/lib/shortcuts/node.py` and `futils.py`:
  authored node JSON ownership, GUID assignment, write and reload behavior.

Backup Pro evidence:

- `resources/lib/skin_adapter.py`: live typed settings authority, helper
  allowlist, generated fingerprint exclusion, path validation and managed
  source roots.
- `WORK_LOG.md` Phase 5–7B: AF3 source-file scope, helper rebuild, transient
  state and lifecycle findings.
- `docs/DESIGN.md`: explicit distinction between source JSON and generated
  output, plus inactive-skin staging and post-rebuild verification.
- `tests/test_skin_adapter.py`: regression evidence for excluding
  `*-viewtypes.json`-related generated state and generated XML from managed
  source paths.
