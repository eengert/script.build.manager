# Current Task

## BM-001 — Project Skeleton

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Complete — awaiting supervisor review and `matrix` merge

### Scope

Create the Kodi add-on skeleton for `script.build.manager` without implementing
provisioning logic. See `BUILD_MANAGER_PROJECT_PLAN.md` §38 (BM-001 in the
initial development backlog).

**Delivered**:
- `addon.xml`
- `default.py` (minimal safe entrypoint)
- `resources/lib/` (importable Python package)
- `resources/lib/build_manager.py` (stub class)
- `resources/lib/utils.py` (getString helper)
- `resources/settings.xml` (placeholder)
- `resources/language/resource.language.en_gb/strings.po` (initial strings)
- `tests/__init__.py`, `tests/test_imports.py` (3/3 passing)
- `changelog.md`, `LICENSE.txt`, `.gitignore`

**Out of scope** (BM-002+):
- Provisioning logic
- Manifest parsing
- Platform-specific adapters
- Network operations
- Skin management
- Merging to `matrix`

### Result

- Implementation commit: `799b836` on `agent/claude`
- `python3 -m unittest tests/test_imports.py`: **3/3 passed**
- `addon.xml` and `resources/settings.xml`: parse correctly
- No Kodi runtime imports in tested modules
- No secrets or machine-specific paths
- No real Kodi profiles or devices touched
