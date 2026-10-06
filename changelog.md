# Changelog

All notable changes to Build Manager will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Read-only Build Status: a fresh check of managed add-ons, skin, supported
  settings and private settings, plus pending-restart and needs-attention
  state, shown in a plain-language native page with Check Again and Help.
  The check changes nothing in Kodi or Build Manager and never shows a
  private value. Without an applied build it reports what it cannot compare.

### Changed
- Build Status now trusts a saved software list or a recorded install outcome
  only when it belongs to the selected build; otherwise it says it could not
  check, instead of reporting a healthy result.

### Added (not yet reachable from the menu)
- Read-only Review Changes model: what would change for a saved build, what
  needs a choice, what is blocked, and whether an earlier review is still
  valid. It changes nothing and offers no Apply action.

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
