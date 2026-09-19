# Current Task

## BM-018A — verified Kodi skin activation merged

**Status**: Complete and merged on matrix; awaiting next supervisor assignment.

Integration commit: `9d7dbdd`.

BM-018A implements verified Kodi skin activation using
`Settings.SetSettingValue("lookandfeel.skin", ...)`, installed/enabled
prerequisites, a pre-existing Yes/No-dialog safety guard, bounded
confirmation-dialog detection, and `SendClick(11)` only after the newly
created dialog is observed. It verifies both the persisted setting and loaded
skin, and the planner enables a disabled desired skin before activation.

- Full suite before integration: 1398/1398 passing.
- Live alternate-skin activation remains deferred because the disposable
  profile contains only Estuary.
- BM-017 not started.
- Remaining BM-018 work not started.

Next step: supervisor assignment.
