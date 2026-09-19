# Agent Handoff — BM-018A runtime correctness correction

**Date**: 2026-09-19
**Agent**: Codex (Luna / Medium)
**Status**: Complete; pending supervisor review. BM-017 not started.

## Result

- Replaced the invalid `Skin.SetSkin(...)` builtin with strict
  `Settings.SetSettingValue` for `lookandfeel.skin`.
- Added strict `Settings.GetSettingValue` final verification and strict
  JSON-RPC response handling for setting mutation/read operations.
- Added bounded `Window.IsActive(yesnodialog)` polling; `SendClick(11)` is
  issued only after the dialog is observed, followed by bounded close polling.
- Added final verification of both persisted `lookandfeel.skin` and
  `xbmc.getSkinDir()`.
- Corrected `Addons.GetAddonDetails` handling so only Kodi's distinct
  not-found response is treated as absent; malformed/protocol errors fail.
- Added a pre-mutation `Window.IsActive(yesnodialog)` guard. A pre-existing
  dialog returns `FAILED` without changing `lookandfeel.skin` or clicking Yes.
- Expanded focused tests in `tests/test_skin.py`; prior BM-018A planner work
  remains unchanged.

## Validation and safety

- Focused tests: 106/106 passing.
- Full unit suite: 1398/1398 passing.
- No Kodi process, disposable profile, real profile, or Apple TV was used.
- Runtime behavior is unit-tested with an injected fake and mocked Kodi JSON-RPC.
- Live disposable validation was not run: the existing harness has no skin
  activation command, and the disposable Kodi installation has only
  `skin.estuary`; adding alternate-skin acquisition/UI harness work would be
  unrelated expansion.
- No shell execution, database manipulation, fallback skin, or destructive
  cleanup was added.
- `matrix`, `agent/claude`, and Backup Pro were untouched.

## Scope boundary / remaining unknowns

- Live confirmation timing and activation persistence on Kodi remain unproven
  for the precise blocker above.
- No AF3 configuration, private overlay, account/token portability, or BM-017
  code was created.

## Smallest next step

Supervisor review of this correction checkpoint, then integrate before
beginning separately scoped AF3 configuration work.

## Usage

Start/end/delta: unavailable. Codex has no reliable usage-introspection source
for this task.
