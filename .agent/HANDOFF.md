# Handoff

## Latest — 2026-09-17 BM-001 complete; awaiting supervisor review

BM-001 project skeleton is complete and committed to `agent/claude` (`799b836`).
Codex was unavailable during this task; Claude acted as primary agent.

**What was done**:
- `BUILD_MANAGER_PROJECT_PLAN.md` replaced with full phased plan (9 phases,
  desired-state architecture, platform list, implementation rules)
- `addon.xml` — v0.1.0, MIT, `xbmc.python 3.0`, all platforms, en_US/en_GB
  summary and description
- `default.py` — minimal entrypoint, shows "not yet configured" dialog via
  `utils.getString`; launches safely without Kodi runtime errors
- `resources/lib/__init__.py` — empty package marker for test importability
- `resources/lib/build_manager.py` — `BuildManager` stub class (no Kodi
  imports; importable outside runtime)
- `resources/lib/utils.py` — `getString()` helper wrapping `xbmcaddon.Addon`
- `resources/settings.xml` — placeholder settings section (no settings yet)
- `resources/language/resource.language.en_gb/strings.po` — strings 32000
  (Build Manager), 32001 (General), 32010 (placeholder UI message)
- `tests/__init__.py`, `tests/test_imports.py` — 3 tests; all pass outside
  Kodi: `BuildManager` importable, instantiates, `resources.lib` is a package
- `changelog.md` — Keep a Changelog format, v0.1.0 entry
- `LICENSE.txt` — MIT, 2026 Eric Engert
- `.gitignore` — `__pycache__/`, `*.pyc`, `.DS_Store`, `dist/`

**Test results**: 3/3 passing (`python3 -m unittest tests/test_imports.py`)

**Validation**:
- `addon.xml` parses correctly (`xml.etree.ElementTree`)
- `resources/settings.xml` parses correctly
- No Kodi runtime imports in tested modules
- No secrets or machine-specific paths
- No real Kodi profiles or devices touched

**What was not done**:
- Provisioning logic (BM-002+)
- Service/background process (not needed at this phase)
- Packaging tools (BM-009)
- Icon image (binary asset; noted in handoff — Kodi won't error without it,
  will just show no icon)
- Merge to `matrix` (supervisor decision)

**Smallest next step**: Supervisor review of `agent/claude` → `799b836`,
then merge to `matrix`. Codex can fast-forward `agent/codex` to the merged
`matrix` commit and begin BM-002 (build specification format).

**No human input required** for the skeleton itself. Merge to `matrix` is
a supervisor decision.

## Previous — 2026-09-17 BM-001 in progress; Claude is primary agent

*(see git log for full context)*

## Previous — 2026-09-17 Bootstrap complete

*(see git log for full context)*
