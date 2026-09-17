# Handoff

## Latest — 2026-09-17 BM-002 complete; manifest schema v1 defined

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
