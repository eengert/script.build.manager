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

**BM-002 — Manifest schema v1: complete, awaiting supervisor review**

| Task | Status | matrix SHA |
|---|---|---|
| BM-001 Project skeleton | Merged | `5442f13` |
| BM-002 Manifest schema v1 | Complete on `agent/claude`, pending review | — |

**BM-002 deliverables** (committed on `agent/claude`, not yet merged):
- `docs/MANIFEST.md` — schema reference (layering, merge semantics, field docs)
- `resources/builds/schema-v1.json` — JSON Schema Draft 7
- `resources/builds/examples/minimal.json` — minimal valid manifest
- `resources/builds/examples/eric-main.example.json` — realistic example (no secrets)
- `tests/test_manifest_schema.py` — 47 new structural validation tests

## Test Status

`python3 -m unittest discover tests` — **50/50 passing** (outside Kodi runtime)

- 3 BM-001 import tests
- 8 schema-file structure tests
- 5 minimal-example tests
- 18 eric-main example tests
- 16 invalid-case tests
- 2 BM-001 regression tests

## Schema Summary (for review)

Format: JSON, JSON Schema Draft 7 (`resources/builds/schema-v1.json`).

Top-level structure:
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
  "optional": [ { "id": "...", "addons": [...], "config": {...} } ],
  "private_overlay": { "type": "local_file", "path_hint": "..." },
  "restart_policy": { "allow_skin_reload": true, "allow_kodi_restart": true }
}
```

Key semantic decisions:
- `enabled` / `disabled` / `absent` — explicit states; omitted field = inherit
- `additionalProperties: false` everywhere — malformed manifests rejected
- Layering: base → platform → device → optional groups → private overlay
- `private_overlay` is a reference only; no credentials in public manifest
- Full JSON Schema validation deferred to BM-003 (no `jsonschema` dependency yet)

## Next Recommended Tasks

After supervisor review and merge of BM-002 to `matrix`:

1. **BM-003** — Implement manifest validation/parser (load JSON, validate against
   schema, expose typed Python objects; may add `jsonschema` dependency)
2. **BM-004** — Implement profile inheritance/overrides (merge semantics defined
   in `docs/MANIFEST.md` §Merge semantics)
3. **BM-005** — Implement Kodi/platform state inspector
4. **BM-006** — Create desired-state model

Claude is the active development agent. Per §49: do not begin Kodi mutation
until the planning layer (BM-007) is stable.

## Open Questions (from BM-002)

1. Private overlay schema — format not yet defined; needed before auth work
2. Config package format — package names defined; resolution not yet specified
3. `bootstrap_url` validation — checksum/signature strategy TBD
4. `firetv` vs `android` platform split — defer until cross-platform testing
5. Optional group deduplication — BM-004 must deduplicate `include_optional`
   when a platform and device both activate the same group

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
| 2026-09-17 | BM-002 manifest schema v1 complete on `agent/claude`; awaiting review |
