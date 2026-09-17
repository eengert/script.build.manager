# Current Task

## BM-001 — Project Skeleton

**Agent**: Claude (Codex temporarily unavailable; Claude is primary until Codex rejoins)
**Branch**: `agent/claude`
**Status**: In progress

### Scope

Create the Kodi add-on skeleton for `script.build.manager` without implementing
provisioning logic. See `BUILD_MANAGER_PROJECT_PLAN.md` → "Phase 1".

**In scope**:
- `addon.xml`
- `default.py` (minimal safe entrypoint)
- `resources/lib/` (importable Python package)
- `resources/lib/build_manager.py` (stub class)
- `resources/settings.xml` (placeholder)
- `resources/language/resource.language.en_gb/strings.po` (initial strings)
- `tests/__init__.py`, `tests/test_imports.py`
- `changelog.md`
- `LICENSE.txt`

**Out of scope**:
- Provisioning logic
- Manifest parsing
- Platform-specific adapters
- Network operations
- Skin management
- Merging to `matrix`

### Acceptance Criteria

- `addon.xml` is syntactically valid XML
- `resources/lib/build_manager.py` imports cleanly outside Kodi
- `tests/test_imports.py` passes with `python3 -m unittest`
- No secrets or machine-specific paths
- No modification to real Kodi profiles or devices
