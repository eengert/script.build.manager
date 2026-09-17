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

**BM-001 — Project skeleton: complete, awaiting supervisor review**

- Bootstrap: `a970e83` on `matrix` (2026-09-17)
- BM-001 implementation: `799b836` on `agent/claude` (2026-09-17)
- Agent-state correction commit follows on `agent/claude`
- Canonical project plan installed: `BUILD_MANAGER_PROJECT_PLAN.md`
- Not yet merged to `matrix`

**BM-001 deliverables** (all committed at `799b836`):
- `addon.xml` — v0.1.0, MIT, `xbmc.python 3.0`, all platforms
- `default.py` — safe placeholder entrypoint
- `resources/lib/__init__.py`, `build_manager.py` stub, `utils.py`
- `resources/settings.xml` — placeholder section
- `resources/language/resource.language.en_gb/strings.po` — strings 32000/32001/32010
- `tests/__init__.py`, `tests/test_imports.py` — 3/3 passing
- `changelog.md`, `LICENSE.txt`, `.gitignore`

**Known gap**: `resources/images/icon.png` is referenced in `addon.xml` but the
binary asset does not exist. Kodi shows no icon rather than erroring.

## Test Status

`python3 -m unittest tests/test_imports.py` — **3/3 passing** (outside Kodi runtime)

## Next Recommended Tasks

After supervisor review and merge of BM-001 to `matrix`:

1. **BM-002** — Create manifest schema v1 (§38; see §3.2 for declarative format example, §7 for layering model)
2. **BM-003** — Implement manifest validation/parser
3. **BM-004** — Implement profile inheritance/overrides
4. **BM-005** — Implement Kodi/platform state inspector

Claude is the active development agent. Codex rejoins when available; before
beginning new work, Codex should fast-forward `agent/codex` to the `matrix`
commit that includes BM-001.

Per §49: do not begin Kodi mutation until the planning layer (BM-007) is stable.

## Worktree Paths

| Branch | Worktree |
|---|---|
| `agent/codex` | `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex` |
| `agent/claude` | `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude` |

## Agent Workflow

See §22–31 of `BUILD_MANAGER_PROJECT_PLAN.md` for full workflow guidance,
task prompt template, handoff format, cross-agent review criteria, model/effort
recommendations, parallel-work rules, and source control conventions.

Normal implementation work happens on `agent/codex` or `agent/claude`.
Supervisor reviews and merges to `matrix`.

## History

| Date | Milestone |
|---|---|
| 2026-09-17 | Repository initialized; bootstrap committed to `matrix` (`a970e83`) |
| 2026-09-17 | BM-001 skeleton complete on `agent/claude` (`799b836`); awaiting review |
| 2026-09-17 | Canonical project plan installed; agent state corrected |
