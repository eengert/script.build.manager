# Handoff

## Latest — 2026-09-17 BM-005 merged to matrix; project idle, BM-006 next

**matrix before**: `2ad253f`
**matrix after**: `6d41279` (fast-forward — no squash, no rebase)
**Merge type**: Fast-forward via `git push origin 6d41279:refs/heads/matrix`

**Tests on matrix**: 358/358 passing (`python3 -m unittest discover tests`)

**Codex**: untouched at `a970e83`

**BM-006**: not started

**Usage (merge task)**: start 5h 67% / wk 46%, end 5h 67% / wk 46%,
delta ~0% / 0%. Model: claude-sonnet-4-6, effort: max.

**Smallest next step**: Supervisor assigns BM-006 task prompt. Claude implements
desired-vs-actual diff / planner consuming `ResolvedBuild` (BM-004) and
`KodiState` (BM-005).

---

## Previous — 2026-09-17 BM-005 complete; awaiting supervisor review

**Files created**:
- `resources/lib/inspector.py` — NEW. Kodi state inspector.
  Public API: `KodiStateInspector(backend=None).inspect() -> KodiState` and
  `inspect_kodi_state() -> KodiState`.
  Error: `KodiInspectionError`.
  Types: `KodiState` (frozen dataclass), `InstalledAddon` (frozen dataclass).
  Backend: `KodiBackend` (injectable base), `KodiRuntimeBackend` (lazy xbmc).
  JSON-RPC helpers (testable without xbmc): `_parse_addon_response`,
  `_parse_version_response`. Add-on normalizer: `_parse_addon_list`.
  Stdlib only — no new runtime dependencies.
- `tests/test_kodi_inspector.py` — NEW. 58 BM-005 tests (all passing).

**Tests**: 349/349 passing (`python3 -m unittest discover tests`)
- 291 prior (BM-001 through BM-004)
- 58 new BM-005 inspector tests

**What was live-proven**: All 349 tests passing with fake backend. No Kodi
runtime required; no real Kodi profiles touched.

**Platform mapping** (Kodi condition → BM platform ID):
- `system.platform.tvos`    → `tvos`
- `system.platform.android` → `android` (includes Fire TV)
- `system.platform.osx`     → `macos`
- `system.platform.ios`     → `ios`
- `system.platform.windows` → `windows`
- `system.platform.linux`   → `linux`
- (none matched)            → `unknown`
Precedence: tvos > android > macos > ios > windows > linux > unknown.

**JSON-RPC methods used (read-only)**:
- `Addons.GetAddons` with `installed:true` and properties `[enabled, version]`
- `Application.GetProperties` with properties `[version]`
- `xbmc.getSkinDir()` — active skin directory (==addon_id by Kodi convention)
- `xbmc.getCondVisibility()` — platform condition flags

**No mutating JSON-RPC methods called**. No Kodi state written.

**Add-on ordering**: sorted by addon_id; malformed entries silently skipped.

**Skin detection**: `xbmc.getSkinDir()` returns folder name matching addon_id
for all standard Kodi skins. Returns "" if result doesn't start with "skin.".

**What was NOT live-proven outside tests**: `KodiRuntimeBackend` methods
require a live Kodi process. The JSON-RPC parsing helpers are fully tested;
the xbmc API call paths are not testable outside Kodi.

**Runtime dependencies added**: None.

**BM-006**: not started.

**Usage (this task)**: start 5h 56% / wk 44%, end 5h 63% / wk 45%,
delta +7% / +1%. Model: claude-sonnet-4-6, effort: max.

**Smallest next step**: Supervisor reviews BM-005 on `agent/claude`. Merges to
`matrix`. Claude continues with BM-006 (desired-vs-actual diff / planner).

---

## Previous — 2026-09-17 BM-004 merged to matrix; project idle, BM-005 next

**matrix before**: `a5d263e`
**matrix after**: `2ad253f` (fast-forward — no squash, no rebase)
**Merge type**: Fast-forward via `git push origin 2ad253f:refs/heads/matrix`

**Tests on matrix**: 291/291 passing (`python3 -m unittest discover tests`)

**Codex**: untouched at `a970e83`

**BM-005**: not started

**Usage (merge task)**: start 5h 52% / wk 44%, end 5h 52% / wk 44%,
delta ~0% / 0%. Model: claude-sonnet-4-6, effort: max.

**Smallest next step**: Supervisor assigns BM-005 task prompt. Claude implements
Kodi/platform state inspector per §38 of the canonical plan.

---

## Previous — 2026-09-17 BM-004 complete; profile resolver committed

**Files created/changed**:
- `resources/lib/resolver.py` — NEW. Profile resolver.
  Public API: `resolve_manifest(manifest, device_profile_id) -> ResolvedBuild`.
  Error: `ManifestResolutionError` (subclass of `ManifestError`).
  Output: `ResolvedBuild` (frozen dataclass).
  Stdlib only — no new runtime dependencies.
- `tests/test_manifest_resolver.py` — NEW. 78 BM-004 tests (all passing).
- `docs/MANIFEST.md` — Optional-group deduplication rule added to §Optional groups;
  open question #5 closed.
- `.agent/` state files updated.

**Tests**: 291/291 passing (`python3 -m unittest discover tests`)
- 213 prior (BM-001/BM-002/BM-003)
- 78 new BM-004 resolver tests

**Layer application order**: base → platform → device → optional groups

**Optional-group de-duplication**: platform.include_optional (listed order), then
device.include_optional (listed order); duplicate IDs dropped by first occurrence;
each group applied at most once. Resolves BM-002 open question #5.

**Add-on ordering**: overridden entry retains original position; new entries appended
in first-seen order.

**Config merge**: packages / managed_files: union, first-seen order, no duplicates.
Managed settings: per addon_id, keys unioned in first-seen order, addon order is
first-seen.

**Skin resolution**: deepest explicit layer wins (base → platform → device).

**What was live-proven**: All 291 tests passing. `resolve_manifest` exercised
against both minimal manifests (via dict) and `eric-main.example.json` (loaded
from disk). Three device profiles resolved: bonus-room, family-room, shield.

**No Kodi runtime involved**. No real Kodi profiles touched.

**Runtime dependencies added**: None.

**BM-005 status**: Not started.

**Usage (this task)**: start 5h 44% / wk 42%, end 5h 50% / wk 43%,
delta +6% / +1%. Model: claude-sonnet-4-6, effort: max.

**Smallest next step**: Supervisor reviews BM-004 on `agent/claude`. Merges to
`matrix`. Claude continues with BM-005 (Kodi/platform state inspector).

---

## Previous — 2026-09-17 BM-003 merged to matrix; project idle, BM-004 next

**matrix before**: `a983df8`
**matrix after**: `a5d263e` (fast-forward — no squash, no rebase)
**Merge type**: Fast-forward via `git push origin a5d263e:refs/heads/matrix`

**Tests on matrix**: 213/213 passing (`python3 -m unittest discover tests`)

**Codex**: untouched at `a970e83`

**BM-004**: not started

**Usage (merge task)**: start 5h 41% / wk 42%, end 5h 42% / wk 42%,
delta +1% / 0%. Model: claude-sonnet-4-6, effort: max.

**Smallest next step**: Supervisor assigns BM-004 task prompt. Claude implements
profile merge/inheritance logic per merge semantics documented in
`docs/MANIFEST.md` §Merge semantics.

---

## Previous — 2026-09-17 BM-003 complete; manifest loader/validator committed

**Files created/changed**:
- `resources/lib/manifest.py` — NEW. Production manifest loader and validator.
  Public API: `load_manifest_file`, `load_manifest_json`, `validate_manifest`.
  Errors: `ManifestError`, `ManifestParseError`, `ManifestValidationError`.
  Typed dataclasses: `Manifest`, `BuildInfo`, `AddonEntry`, `Repository`,
  `SkinEntry`, `ManagedSettingScope`, `ConfigDeclarations`, `ProfileLayer`,
  `DeviceProfile`, `OptionalGroup`, `PrivateOverlayRef`, `RestartPolicy`.
  No new runtime dependencies (stdlib only: `json`, `re`, `posixpath`,
  `urllib.parse`, `dataclasses`).
- `tests/test_manifest_loader.py` — NEW. 127 BM-003 tests (all passing).
- `docs/MANIFEST.md` — Updated runtime-validation note to reflect stdlib-only
  implementation (removed jsonschema recommendation).
- `.agent/` state files updated.

**Tests**: 181/181 passing (`python3 -m unittest discover tests`)
- 3 BM-001 import tests
- 51 BM-002 schema structural tests
- 127 BM-003 loader/validator tests

**What was live-proven**: All 181 tests passing. `load_manifest_file` used
against `minimal.json` and `eric-main.example.json` within tests.

**No Kodi runtime involved**. No real Kodi profiles touched.

**Runtime dependencies added**: None.

**BM-003 implementation decisions**:
- Stdlib-only: no `jsonschema` dependency (per supervisor instruction)
- Semantic cross-references validated: device_profile.extends must reference
  existing platform, include_optional references must exist, duplicate IDs
  rejected at all layers
- Path safety: rejects absolute, UNC, Windows drive, `..` traversal, null bytes
- URL policy: `https` (preferred) + `http` (local/dev), embedded credentials rejected
- Frozen dataclasses for all types except `Manifest` (which contains dict fields)

**Usage (this task)**: start 5h 19% / wk 39%, end 5h 31% / wk 41%,
delta +12% / +2%. Model: claude-sonnet-4-6, effort: max.

**Smallest next step**: Supervisor reviews and merges BM-003 to `matrix`.
Claude continues with BM-004 (profile merge/inheritance logic, semantics
documented in `docs/MANIFEST.md`).

---

## Previous — 2026-09-17 WF-001 usage-tracking docs merged to matrix

Integration only. No implementation changes. No BM-003 work started.

**What happened**:
- `agent/claude` fast-forwarded `matrix` from `89039d6` → `a983df8`
- Includes `a4c999f` (post-BM-002 merge state) and `a983df8` (WF-001: usage-tracking)
- `matrix` pushed to origin
- `agent/claude` agent-state updated: status=idle, last_commit=a983df8
- `agent/codex` not touched
- 51/51 tests passing

**Usage (this task)**: start 5h 96% / wk 35%, end 5h 96% / wk 35%, delta ~0%.
Model: claude-sonnet-4-6, effort: max.

**Smallest next step**: Supervisor assigns BM-003 task prompt. Claude implements
manifest loader/parser on `agent/claude` per §38 and `docs/MANIFEST.md`.

---

## Previous — 2026-09-17 BM-002 merged to matrix; ready for BM-003

Integration only. No implementation changes.

**What happened**:
- `agent/claude` fast-forwarded `matrix` from `5442f13` → `89039d6`
- Includes BM-002 commits: `7bfda71`, `98e93db`, `4ac58c6`, `89039d6`
- `matrix` pushed to origin
- `agent/claude` agent-state updated: status=idle, next task=BM-003
- `agent/codex` not touched (Codex still temporarily unavailable)
- 51/51 tests passing on `matrix`

**matrix now contains** (key commits):
- `5442f13` — BM-001 complete (§30 branch-workflow correction)
- `7bfda71` — BM-002: manifest schema v1
- `89039d6` — BM-002: require extends on every device profile

**Smallest next step**: Supervisor assigns BM-003 task prompt. Claude implements
manifest loader/parser on `agent/claude` per §38 and `docs/MANIFEST.md`.

---

## Previous — 2026-09-17 BM-002 complete; manifest schema v1 defined

Data contract only. No production parser code. No Kodi mutation. No new
runtime dependencies. BM-001 implementation files unchanged from `799b836`.

**Files created**:
- `docs/MANIFEST.md` — human-readable schema reference (layering model, merge
  semantics for BM-004, field-by-field docs, security notes, open questions)
- `resources/builds/schema-v1.json` — JSON Schema Draft 7
- `resources/builds/examples/minimal.json` — minimal valid manifest
- `resources/builds/examples/eric-main.example.json` — realistic example
- `tests/test_manifest_schema.py` — 47 new structural validation tests

**Tests**: 50/50 passing (`python3 -m unittest discover tests`)
- 3 BM-001 import tests
- 8 schema-file structure tests
- 5 minimal-example tests
- 18 eric-main example tests
- 16 invalid-case tests (missing fields, bad states, unknown keys, etc.)
- 2 BM-001 regression tests

**Key schema decisions**:
- JSON format, JSON Schema Draft 7 (no added runtime dependency)
- `schema_version: 1` (integer constant) — format versioning independent of build version
- Layering: base → platform profile → device profile → optional groups → private overlay
- Explicit states: `enabled` | `disabled` | `absent`; omitted = inherit (not disabled)
- `additionalProperties: false` at top level and on all named object types (fail-closed)
- `private_overlay` is a reference only; no credentials in public manifest

**What was live-proven**: All 50 tests passing with `python3 -m unittest`.
No Kodi runtime required; no real Kodi profiles touched.

**Smallest next step**: Supervisor review → BM-003 (manifest parser/validator
in Python, using the schema and merge semantics defined here).

---

## Previous — 2026-09-17 BM-001 merged to matrix; ready for BM-002

Integration only. No implementation changes.

**What happened**:
- `agent/claude` fast-forwarded `matrix` from `a970e83` → `5442f13`
- `matrix` pushed to origin; all BM-001 work and documentation corrections are
  now on the integration branch
- `agent/claude` agent-state updated: status=idle, next task=BM-002
- `agent/codex` not touched (Codex still temporarily unavailable)

**matrix now contains**:
- Bootstrap (`a970e83`)
- BM-001 skeleton (`799b836`)
- Agent-state correction + canonical plan (`1789386`)
- §30 branch-workflow correction (`5442f13`)

**BM-001 implementation files on matrix**: `addon.xml`, `default.py`,
`resources/lib/`, `resources/settings.xml`, `resources/language/`, `tests/`,
`changelog.md`, `LICENSE.txt`, `.gitignore`

**Smallest next step**: Supervisor assigns BM-002 task prompt. Claude implements
manifest schema v1 on `agent/claude` per §38 and §7 of the canonical plan.

---

## Previous — 2026-09-17 Project plan §30 corrected (branch workflow)

Documentation correction only. No BM-001 implementation files changed.

**What changed**:
- `BUILD_MANAGER_PROJECT_PLAN.md` §30: replaced incorrect `main`-only branch
  recommendation with the actual established workflow (`matrix` as protected
  integration branch; `agent/codex` and `agent/claude` as worktree branches;
  short-lived task branches optional). No other sections touched.

**BM-001 implementation unchanged**: `git diff 799b836 -- addon.xml default.py
resources/ tests/ changelog.md LICENSE.txt` produced no output.

---

## Previous — 2026-09-17 Agent-state correction; canonical plan confirmed installed

Documentation correction only. No BM-001 implementation files changed.

**What changed in this commit**:
- `AGENT_STATUS.json`: `next_agent` corrected from `codex` to `claude` (Codex
  temporarily unavailable; Claude continues development after supervisor review)
- `BUILD_MANAGER_SUPERVISOR_HANDOFF.md`: rewritten to accurately reference the
  canonical 51-section `BUILD_MANAGER_PROJECT_PLAN.md`; removed inaccurate
  reference to a shorter 9-phase plan
- `HANDOFF.md` (this file): corrected prior entry's claim about the project plan

**BM-001 implementation unchanged**: `addon.xml`, `default.py`, `resources/`,
`tests/`, `changelog.md`, `LICENSE.txt` are identical to commit `799b836`.
`git diff 799b836 -- addon.xml default.py resources/ tests/ changelog.md LICENSE.txt`
produced no output.

**Canonical plan**: `BUILD_MANAGER_PROJECT_PLAN.md` — 51-section
supervisor-approved document covering project goals, design philosophy, MVP
scope, architecture, phase plan (§37), initial backlog BM-001–BM-020 (§38),
and all workflow/agent conventions. It was supplied directly by the supervisor
and must not be summarized or replaced.

## Previous — 2026-09-17 BM-001 complete; awaiting supervisor review

BM-001 project skeleton committed to `agent/claude` (`799b836`). Codex was
unavailable during this task; Claude acted as primary agent.

**What was done**:
- `addon.xml` — v0.1.0, MIT, `xbmc.python 3.0`, all platforms, en_US/en_GB
- `default.py` — minimal entrypoint, shows "not yet configured" dialog via
  `utils.getString`; launches safely without Kodi runtime errors
- `resources/lib/__init__.py` — empty package marker for test importability
- `resources/lib/build_manager.py` — `BuildManager` stub class (no Kodi
  imports; importable outside runtime)
- `resources/lib/utils.py` — `getString()` helper wrapping `xbmcaddon.Addon`
- `resources/settings.xml` — placeholder settings section
- `resources/language/resource.language.en_gb/strings.po` — strings 32000
  (Build Manager), 32001 (General), 32010 (placeholder UI message)
- `tests/__init__.py`, `tests/test_imports.py` — 3/3 passing
- `changelog.md`, `LICENSE.txt`, `.gitignore`

**Test results**: 3/3 passing (`python3 -m unittest tests/test_imports.py`)

**Validation**:
- `addon.xml` and `resources/settings.xml` parse correctly
- No Kodi runtime imports in tested modules
- No secrets or machine-specific paths
- No real Kodi profiles or devices touched

**What was not done**:
- Provisioning logic (BM-002+)
- `resources/images/icon.png` (binary asset pending; Kodi shows no icon rather
  than erroring)
- Merge to `matrix` (supervisor decision)

**Smallest next step**: Supervisor review of `agent/claude` → `799b836`, then
merge to `matrix`. Claude continues with BM-002 (manifest schema v1, §38 of
the canonical plan) after supervisor review.

## Previous — 2026-09-17 Bootstrap complete

*(see git log — bootstrap commit `a970e83` on `matrix`)*
