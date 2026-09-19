# Current Task

## BM-018D — typed skin-setting configuration support

**Agent**: Codex (Luna / High)
**Branch**: `agent/codex`
**Worktree**: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`
**Status**: Implementation complete; live AF3 gate blocked by the disposable
Kodi/AF3 activation environment.

Implemented in `0260ef8` (`feat(BM-018D): add typed skin configuration support`):

- explicit `addon` / `skin` target namespaces in manifest and package schemas;
- backward-compatible omitted target defaulting to `addon`;
- target-kind-aware identity, overlay, ownership, resolver, validator, and
  validation snapshots;
- dedicated active-skin bool/string backend using Kodi skin-setting JSON-RPC;
- AF3 mutually-exclusive `EnableIcons` / `EnableIconText` policy;
- focused tests and disposable `validate-skin-config` harness;
- BM-018C portability and testing documentation updates.

Validation:

- focused BM-018D/skin/configuration tests: 722 passing;
- full suite: 1,436/1,436 passing;
- `git diff --check`: passing;
- real Kodi profile: read-only and unchanged.

Live boundary:

- The disposable harness copied installed AF3 `3.2.19` plus available declared
  dependencies and reached BM-018A confirmation handling.
- AF3 loaded transiently, then Kodi repeatedly reloaded it and fell back to
  Estuary; the harness therefore stopped before typed deployment and does not
  claim a live BM-018D pass.
- No production `af3-common` package was created; BM-017, BM-018E, BM-019, and
  BM-020 were not started.
