# Build Manager — Supervisor Handoff

Living project-state document. Keep current truth; remove obsolete trails.
See §32–33 of `BUILD_MANAGER_PROJECT_PLAN.md` for maintenance discipline.

---

## Project Identity

| Field | Value |
|---|---|
| Name | Build Manager |
| Addon ID | `script.build.manager` |
| Repository | `eengert/script.build.manager` |
| Integration branch | `matrix` (protected) |
| Agent branches | `agent/codex`, `agent/claude` |
| Active agent | Claude (Codex temporarily unavailable) |

## Target Platforms

- Apple TV / tvOS
- Nvidia Shield Pro / Android TV
- Fire TV / Fire OS
- macOS

## Canonical Project Plan

**`BUILD_MANAGER_PROJECT_PLAN.md`** — supervisor-approved, 51 sections.

Key sections for quick reference:

| § | Topic |
|---|---|
| 2 | Project goal (fresh-install and reconciliation flows) |
| 3 | Design philosophy (desired-state, idempotency, reconciliation) |
| 4 | MVP scope |
| 5 | Proposed architecture |
| 6 | Repository structure |
| 7 | Build definition layers (base → platform → device → secrets) |
| 8–14 | Add-ons, dependencies, skin, managed config, auth, security, workflow |
| 15 | Reconciliation / repair mode |
| 17–19 | Testing strategy, golden scenarios, volatile state |
| 20 | Restart orchestration |
| 21 | Backup Pro relationship |
| 22–31 | Supervisor/agent workflow, model guidance, parallel rules, source control |
| 37 | Phase plan (0: research → 9: 1.0 release) |
| 38 | Initial development backlog (BM-001 through BM-020) |
| 45–47 | Definition of done, MVP criteria, scope-control rule |
| 49 | Recommended first milestone (planner output before mutation) |

Do not treat any shorter summary as a substitute for the canonical plan.

## Current State

**Idle — BM-003 merged, awaiting BM-004 assignment**

| Task | Status | matrix SHA |
|---|---|---|
| BM-001 Project skeleton | Merged | `5442f13` |
| BM-002 Manifest schema v1 | Merged | `89039d6` |
| BM-003 Manifest parser/validator | Merged | `a5d263e` |
| BM-004 Profile merge/inheritance | Not started | — |

**matrix HEAD**: `a5d263e` (fast-forward from `a983df8`)

## Completed Deliverables

### BM-001 (merged `5442f13`)
- `addon.xml`, `default.py`, `resources/lib/`, `resources/settings.xml`,
  `resources/language/resource.language.en_gb/strings.po`
- `tests/test_imports.py` — 3/3 passing

### BM-002 (merged `89039d6`)
- `docs/MANIFEST.md` — schema reference (layering, merge semantics, field docs)
- `resources/builds/schema-v1.json` — JSON Schema Draft 7
- `resources/builds/examples/minimal.json`
- `resources/builds/examples/eric-main.example.json`
- `tests/test_manifest_schema.py` — 48 structural validation tests

### BM-003 (merged `a5d263e`)
- `resources/lib/manifest.py` — loader, validator, typed representation.
  Public API: `load_manifest_file`, `load_manifest_json`, `validate_manifest`.
  Errors: `ManifestError`, `ManifestParseError`, `ManifestValidationError`.
  Stdlib only — no `jsonschema` runtime dependency.
- `tests/test_manifest_loader.py` — 162 BM-003 tests (127 original + 35 null-rejection)
- `docs/MANIFEST.md` — updated runtime-validation note (stdlib, not jsonschema)
- Null-vs-omission correction included: explicit JSON `null` rejected for all
  non-nullable fields; omission still returns documented defaults.

## Test Status

`python3 -m unittest discover tests` — **213/213 passing** (outside Kodi runtime)

## Schema Summary

Format: JSON, JSON Schema Draft 7. Top-level structure:

```json
{
  "schema_version": 1,
  "engine_min_version": "0.1.0",
  "build": { "id": "...", "version": "...", "name": "...", "description": "..." },
  "repositories": [...],
  "addons": [...],
  "skin": { "addon_id": "skin.*", "config_packages": [...] },
  "config": { "packages": [...], "managed_settings": [...], "managed_files": [...] },
  "platform_profiles": { "<platform-id>": { ... } },
  "device_profiles": { "<device-id>": { "extends": "<platform-id>", ... } },
  "optional": [ { "id": "...", "addons": [...] } ],
  "private_overlay": { "type": "local_file", "path_hint": "..." },
  "restart_policy": { "allow_skin_reload": true, "allow_kodi_restart": true }
}
```

Key constraints:
- `device_profile.extends` is **required** — every device profile must extend a platform profile
- `additionalProperties: false` everywhere — malformed manifests rejected
- Add-on states: `enabled` | `disabled` | `absent`; omitted = inherit (not disabled)
- No credentials in public manifest; `private_overlay` is reference only
- Full JSON Schema validation deferred to BM-003 (no `jsonschema` dependency yet)

## Next Recommended Tasks

1. **BM-004** — Profile merge/inheritance logic (merge semantics fully
   documented in `docs/MANIFEST.md` §Merge semantics; no implementation yet):
   - Add-on merge: base → platform → device → optional groups
   - Config merge: union of packages, managed_settings (per addon_id), managed_files
   - Skin merge: deepest layer that declares skin wins
   - Optional group deduplication (when both platform and device include same group)
   - Return fully-resolved `ResolvedBuild` or equivalent typed result

2. **BM-005** — Kodi/platform state inspector

3. **BM-005** — Kodi/platform state inspector

## Open Questions (from BM-002)

1. Private overlay schema — format not yet defined; needed before auth work
2. Config package resolution — package names defined; format TBD
3. `bootstrap_url` validation — checksum/signature strategy TBD
4. `firetv` vs `android` platform split — defer to cross-platform testing
5. Optional group deduplication — BM-004 must deduplicate when platform + device both include same group

## Agent/Model Usage Policy

Usage tracking is **enabled where reliable data is available**.

- Model/effort recommendations should be driven by **empirically observed burn
  and task success**, not by assuming a lower model or lower reasoning setting
  is cheaper. The target is lowest total cost to a correct result (§28).
- **Raw usage history lives in `.agent/USAGE_HISTORY.md`**, not here and not in
  `BUILD_MANAGER_PROJECT_PLAN.md`. This file carries only short summarized
  observations.
- **Never fabricate usage data.** Missing readings are recorded as `unknown` or
  `unavailable`. An absent measurement is acceptable; an invented one is not.
- Available sources, as of 2026-09-17:
  - **Claude** — Claude Code reports plan limit windows (5-hour, weekly) and
    the session's model/effort. Documented in `CLAUDE.md`.
  - **Codex** — no usage/quota source exists. Codex rows record
    `unavailable` for start/end/delta. Documented in `AGENTS.md`.
- Claude and Codex model/effort terminology are separate namespaces and are
  never translated into each other. Claude: Sonnet/Opus with Claude Code's
  `effort` value. Codex: Luna/Sol/Astra with Codex effort names.

### Observations

*(none yet — WF-001 recorded a partial reading only; no comparable-task
baseline exists)*

## Worktree Paths

| Branch | Worktree |
|---|---|
| `agent/codex` | `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex` |
| `agent/claude` | `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude` |

## Agent Workflow

See §22–31 of `BUILD_MANAGER_PROJECT_PLAN.md` for full workflow guidance.

Normal implementation work happens on `agent/codex` or `agent/claude`.
Supervisor reviews and merges to `matrix`.

## History

| Date | Milestone |
|---|---|
| 2026-09-17 | Repository initialized; bootstrap committed to `matrix` (`a970e83`) |
| 2026-09-17 | BM-001 skeleton complete and merged to `matrix` (`5442f13`) |
| 2026-09-17 | BM-002 manifest schema v1 complete and merged to `matrix` (`89039d6`) |
| 2026-09-17 | WF-001 usage-tracking docs merged to `matrix` (`a983df8`); project idle |
| 2026-09-17 | BM-003 manifest parser/validator merged to `matrix` (`a5d263e`); project idle |
