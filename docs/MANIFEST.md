# Build Manager Manifest Format — v1 Reference

A Build Manager manifest is a JSON file that declares the **desired state** of a
Kodi installation. The engine reads the manifest, inspects the actual Kodi
installation, computes the difference, and provisions the device to match.

Machine-readable schema: [`resources/builds/schema-v1.json`](../resources/builds/schema-v1.json)
(JSON Schema Draft 7)

Examples:
- Minimal: [`resources/builds/examples/minimal.json`](../resources/builds/examples/minimal.json)
- Realistic: [`resources/builds/examples/eric-main.example.json`](../resources/builds/examples/eric-main.example.json)

---

## Design principles

- **Desired state, not captured state.** The manifest says what a device *should
  look like*, not what it looked like when it was last backed up.
- **Declarative.** Configuration is expressed as data, not as instructions.
- **Idempotent.** Running Build Manager on an already-correct device produces
  no changes.
- **Fail closed.** A malformed manifest must be rejected before any Kodi
  mutation occurs.
- **No secrets.** The public manifest never contains passwords, tokens, API keys,
  or any private authentication state.
- **Format-independent core.** The schema is JSON for v1 because JSON is built
  into Python and requires no added dependency. The engine architecture must not
  couple core logic to JSON syntax so that the format can be extended later.

---

## Layering model

A manifest is composed of **layers** that are merged to produce the desired
state for a specific device:

```
Base Build
   +
Platform Profile          (e.g. tvos, android, macos)
   +
Device Profile            (e.g. bonus-room, shield)
   +
Optional Groups           (e.g. shield-extras)
   +
Private Overlay           (referenced, never embedded)
   =
Desired Device State
```

Each layer can override or extend the layer beneath it. A field absent from a
layer means **inherit from the parent** — not "use a default value" and not
"disable it".

---

## Merge semantics

These semantics are defined here for BM-004 (profile inheritance) to implement
against. BM-002 defines the data contract only; no merge logic is implemented.

### Add-on merge (across all layers)

1. Start with the base `addons` list as the working set.
2. For each profile layer in order (platform → device → optional groups):
   - For each entry in the layer's `addons` list:
     - If the `addon_id` is already in the working set, **replace** its `state`.
     - If the `addon_id` is not in the working set, **add** it.
3. Add-ons not mentioned in a layer are **unchanged** (not disabled, not removed).

### Config merge (across all layers)

- `packages`: union of all package names across all layers. Duplicates are
  ignored.
- `managed_settings`: union per `(target, addon_id)`. If the same explicit
  target and `addon_id` appears in multiple layers, the `keys` lists are
  unioned. The optional `target` defaults to `addon` for backward
  compatibility; use `skin` only for Kodi skin settings.
- `managed_files`: union of all paths across all layers. Duplicates are ignored.

### Skin merge (across all layers)

The **deepest layer** that explicitly declares a `skin` wins completely. Absent
`skin` in a layer means inherit from the parent.

### Optional groups

Optional groups are applied **after** the device profile has been fully resolved.
Each optional group's `addons` and `config` are merged using the same rules as
other layers. Optional groups themselves do not have an `extends` field.

**Application order and de-duplication (resolved in BM-004):**

1. Collect group IDs from `platform_profile.include_optional` in listed order.
2. Then collect group IDs from `device_profile.include_optional` in listed order.
3. De-duplicate by first occurrence — each group ID appears at most once.
4. Apply the resulting ordered list after the device layer.

If both the platform profile and the device profile name the same optional group,
it is applied once (at the platform's position).

---

## Important distinctions

### `schema_version` vs `build.version` vs `engine_min_version`

| Field | What it versions |
|---|---|
| `schema_version` | The manifest **format** (this document). Parsed first. |
| `build.version` | The **build definition** — what Kodi should look like. |
| `engine_min_version` | The minimum Build Manager **add-on** version required. |

A build definition can change (new add-ons, config updates) without changing the
manifest format (`schema_version` stays `1`) and without requiring a new Build
Manager release.

### `enabled` vs `disabled` vs omitted

| Value | Meaning |
|---|---|
| `"enabled"` | Install the add-on if missing; ensure it is enabled. |
| `"disabled"` | Install the add-on if missing; ensure it is disabled. |
| *(omitted from a profile)* | Inherit the state from the parent layer. At the top level, the add-on is unmanaged. **Not** equivalent to `"disabled"`. |

Build Manager does not uninstall add-ons. The former `"absent"` state is
rejected because Kodi does not expose a supported unattended removal API with
the lifecycle and data-preservation guarantees required here. Omit an add-on
to leave it unmanaged; do not translate removal into `"disabled"`.

### Repository vs add-on

A `repository` entry describes a **Kodi repository add-on** (id starts with
`repository.`). The repository must be present before the engine can install
other add-ons from it. Repositories are not subject to profile layering; the
base `repositories` list applies globally.

An `addons` entry describes any other installable Kodi add-on (plugin, script,
service, skin, etc.).

### Platform profile vs device profile

A **platform profile** describes behavior common to all devices running a
particular operating system (tvOS, Android, macOS). A **device profile**
describes a specific physical device (bonus-room Apple TV, Shield Pro). Every
device profile must declare exactly one platform profile via `extends`. Direct
layering on the base build (without an intervening platform profile) is not
permitted in v1.

### Public config declarations vs private overlay

The `config` block (and `config` blocks within profiles) declares **which**
settings and files are managed by Build Manager. It contains no values. Setting
values are stored in configuration packages (separate files, resolved by the
engine).

The `private_overlay` field references an optional private file that may contain
portable authentication state and personal credentials. The private file is never
part of the public manifest and is never committed to the public repository.

### Managed vs unmanaged configuration

Build Manager only modifies the settings and files explicitly declared in
`config.managed_settings` and `config.managed_files`. All other Kodi state is
left untouched unless explicitly managed. This prevents accidental overwrites of
device-local state.

The relationship is enforced in both directions (BM-015): a configuration
package may not target anything outside these declarations, and every declared
target must be supplied by some selected package. Either violation fails
preflight before any Kodi state is changed.

### Add-on settings versus skin settings

The setting target namespace is explicit and is part of the target identity:

```text
(target, addon_id, key)
```

An omitted package `target` means `addon`, preserving existing package
behavior. A package entry with `target: skin` must match a manifest
`managed_settings` scope with `target: skin` and is applied through Kodi's
skin-setting API only after that exact skin is active. The `skin.` prefix is
not used as a heuristic; an explicit target is required. BM-018D initially
supports only typed `bool` and `string` skin entries. Skin `settings.xml` is
never managed as a whole file.

---

## Top-level fields

### `schema_version` *(required)*

```json
"schema_version": 1
```

Integer. Must be `1`. Allows the parser to immediately reject or route manifests
written for a different format version.

### `engine_min_version` *(optional)*

```json
"engine_min_version": "0.2.0"
```

Semver string. Minimum Build Manager add-on version that can process this
manifest. Absent means no minimum is declared.

### `build` *(required)*

```json
"build": {
  "id": "eric-main",
  "version": "1.3.0",
  "name": "Eric Main Build",
  "description": "Optional human-readable description."
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | Stable machine identifier. Set once, never changed. Used for version tracking and repair detection. Pattern: `[a-z0-9][a-z0-9_-]*`. |
| `version` | Yes | Semver. Increment when the desired state changes. |
| `name` | No | Display name in UI. |
| `description` | No | Human-readable description. |

### `repositories` *(optional)*

```json
"repositories": [
  {
    "addon_id": "repository.eengert",
    "bootstrap_url": "https://example.com/repo.zip",
    "required": true
  }
]
```

Ordered list of Kodi repositories that must be present before add-on resolution.
If a repository is already installed, `bootstrap_url` is not used.

| Field | Required | Notes |
|---|---|---|
| `addon_id` | Yes | Must start with `repository.`. |
| `bootstrap_url` | No | URL to the repo ZIP for initial bootstrap only. |
| `required` | No | Default `true`. If `true`, provisioning fails if the repo cannot be installed. |

### `addons` *(optional)*

```json
"addons": [
  {"addon_id": "plugin.video.redlight",  "state": "enabled"},
  {"addon_id": "plugin.video.pov",        "state": "enabled"},
  {"addon_id": "plugin.video.deprecated", "state": "disabled"}
]
```

The base desired add-on set. Applies to all profiles unless overridden. Add-on
IDs follow standard Kodi conventions.

### `skin` *(optional)*

```json
"skin": {
  "addon_id": "skin.arctic.fuse.3",
  "config_packages": ["af3-common"]
}
```

The desired active skin. `config_packages` names configuration packages to apply
after activation. During profile resolution, packages from the winning skin
are appended after ordinary resolved `config.packages`; duplicates are removed
by deterministic first-seen order. The deepest explicitly declared skin wins
completely, including its package list, so superseded skins do not contribute
packages. Package targets still require ownership declarations in
`config.managed_settings` and `config.managed_files`. Absent means Build
Manager does not manage skin selection.

### `config` *(optional)*

```json
"config": {
  "packages": ["af3-common"],
  "managed_settings": [
    {
      "target": "skin",
      "addon_id": "skin.arctic.fuse.3",
      "keys": ["HomeSwitcher.EnableIcons"]
    }
  ],
  "managed_files": [
    "addon_data/skin.arctic.fuse.3/settings.xml"
  ]
}
```

Declares which configuration is owned by this build. Contains no values.

| Sub-field | Notes |
|---|---|
| `packages` | Named config packages the engine must apply, in resolved order; later packages override earlier ones. See [`docs/CONFIG_PACKAGES.md`](CONFIG_PACKAGES.md). |
| `managed_settings` | Which explicit add-on (`target: addon`, or omitted) or active-skin (`target: skin`) setting keys Build Manager owns. Only listed targets are written. |
| `managed_files` | Kodi userdata-relative paths Build Manager may overwrite. |

### `platform_profiles` *(optional)*

```json
"platform_profiles": {
  "tvos": {
    "label": "Apple TV / tvOS",
    "addons": [...],
    "config": {...},
    "skin": {...},
    "include_optional": [...]
  }
}
```

Keys are stable platform IDs (`tvos`, `android`, `macos`, etc.). Each value is a
profile layer. All fields are optional; absent means inherit from base.

Recommended platform IDs:

| ID | Platform |
|---|---|
| `tvos` | Apple TV / tvOS |
| `android` | Android TV (Shield, Fire TV) |
| `macos` | macOS |
| `firetv` | Fire TV / Fire OS (if different enough from `android` to warrant its own profile) |

### `device_profiles` *(optional)*

```json
"device_profiles": {
  "bonus-room": {
    "label": "Bonus Room Apple TV",
    "extends": "tvos",
    "addons": [...],
    "config": {...},
    "skin": {...},
    "include_optional": [...]
  }
}
```

Keys are stable device IDs. Every device profile **must** declare `extends`
naming exactly one platform profile ID. Direct inheritance from the base build
(without an intervening platform profile) is not permitted in v1.

### `optional` *(optional)*

```json
"optional": [
  {
    "id": "shield-extras",
    "label": "Shield-specific add-ons",
    "addons": [...],
    "config": {...}
  }
]
```

Named optional component groups. Activated by platform or device profiles via
`include_optional`. Applied after the device profile is fully resolved.

### `private_overlay` *(optional)*

```json
"private_overlay": {
  "type": "local_file",
  "path_hint": "~/.config/kodi-private/eric-main-private.json",
  "description": "Portable auth state for Real-Debrid, Trakt, EasyNews."
}
```

A reference to a private overlay file. The engine locates this file at runtime
on the target device. If absent or missing, the engine continues without it.

**The private overlay must never be committed to the public repository.**

`type` must be `"local_file"` in v1. Future versions may support other types.

### `restart_policy` *(optional)*

```json
"restart_policy": {
  "allow_skin_reload": true,
  "allow_kodi_restart": true
}
```

Governs which restart actions Build Manager may perform. Both default to `true`.

---

## Schema validation

The schema file (`resources/builds/schema-v1.json`) follows **JSON Schema Draft
7** (`http://json-schema.org/draft-07/schema#`).

**Runtime validation**: BM-003 implements validation using Python standard
library only — no `jsonschema` runtime dependency. The schema file
(`resources/builds/schema-v1.json`) serves as the formal machine-readable
contract and documentation artifact; the runtime validator in
`resources/lib/manifest.py` enforces the same constraints in Python.

**Unknown properties**: The schema uses `"additionalProperties": false` at the
top level and on all named object types. Manifests with unknown top-level keys
must be rejected.

**Unknown properties**: The schema uses `"additionalProperties": false` at the
top level and on all named object types. Manifests with unknown top-level keys
must be rejected.

---

## Security notes

- Manifests must not embed shell commands, arbitrary executable code, or
  unrestricted filesystem directives.
- `managed_files` paths must be validated against path-traversal sequences
  (`..`, absolute paths) before use. This validation is in the parser (BM-003),
  not enforced by the schema.
- `bootstrap_url` values are used only for initial repository bootstrap. The
  engine must validate downloaded artifacts before installation.
- The `private_overlay` field contains only a reference. Credential values live
  in the private overlay file, which is never parsed by this schema.

---

## Unresolved questions for BM-005+

1. **Private overlay schema**: The format of the private overlay file is not
   defined in v1. A dedicated task should define it before authentication work
   begins.

2. ~~**Config package format**~~ — **Resolved by BM-015.** A package is a
   directory under `resources/config/packages/<package-id>/` containing a
   `package.json` descriptor and an optional `files/` tree. See
   [`docs/CONFIG_PACKAGES.md`](CONFIG_PACKAGES.md) for the descriptor schema,
   supported setting types, override semantics, ownership rules and the file
   safety model. Packages may only affect targets declared in
   `managed_settings` / `managed_files`, and every declared target must be
   supplied by some selected package.

3. **`bootstrap_url` security**: The engine must decide how to validate
   downloaded repository ZIPs (checksum, signature, or trust-on-first-use).

4. **`firetv` vs `android` platform split**: Fire TV may diverge enough from
   Shield to warrant a separate platform profile. Defer until cross-platform
   testing begins.

5. ~~**Optional group ordering**~~ — **Resolved by BM-004.** See §Optional groups
   above. De-duplication is by first occurrence, platform-first then device.
