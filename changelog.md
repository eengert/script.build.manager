# Changelog

All notable changes to Build Manager will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] — 2026-09-17

### Added
- Initial add-on skeleton: `addon.xml`, `default.py`, `resources/lib/`,
  `resources/settings.xml`, `resources/language/`, `tests/`.
- `BuildManager` stub class (`resources/lib/build_manager.py`).
- Placeholder entrypoint that launches safely and shows a "not yet configured"
  dialog.
- Basic import test suite (`tests/test_imports.py`).

### Notes
- No provisioning logic implemented. Skeleton only.
- Provisioning features are planned for BM-002 and later phases.
