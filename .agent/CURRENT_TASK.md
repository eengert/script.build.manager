# Current Task

## BM-018D — typed skin-setting configuration support

**Agent**: Codex (Luna / High)
**Branch**: `agent/codex`
**Worktree**: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`
**Status**: Complete on `agent/codex`; not integrated to `matrix`.

Implemented across `0260ef8` and `39bd26c`:

- explicit `addon` / `skin` target namespaces in manifest and package schemas;
- backward-compatible omitted target defaulting to `addon`;
- target-kind-aware identity, overlay, ownership, resolver, validator, and
  validation snapshots;
- dedicated active-skin bool/string backend using Kodi skin-setting JSON-RPC;
- AF3 mutually-exclusive `EnableIcons` / `EnableIconText` policy in the
  AF3-specific validation layer;
- focused tests and disposable `validate-skin-config` harness with complete
  transitive dependency enablement and runtime warm-up;
- BM-018C portability and testing documentation updates.

Validation:

- focused skin/configuration tests: 264/264 passing;
- full suite: 1,438/1,438 passing;
- disposable BM-018D live gate: 17/17 passing;
- `git diff --check`: passing;
- real Kodi profile: read-only and unchanged.

Root causes resolved:

- A fresh disposable profile had AF3 and 17 transitive dependencies installed
  but disabled. The harness now verifies and enables all 18 closure nodes and
  confirms installed/enabled/not-broken/version state.
- AF3's first-run `script.skinvariables` generated-state reload raced Kodi's
  keep/revert transaction after an accepted Yes. The disposable harness warms
  that generated runtime state, then runs the actual BM-018A gate from Estuary.
- Kodi returns mixed-case and lowercase skin-setting IDs inconsistently and
  returns the written string for string setters. The runtime adapter now
  handles both observed contracts without weakening typed validation.

No production `af3-common` package was created; BM-017, BM-018E, BM-019, and
BM-020 were not started. No Apple TV or real Kodi profile was accessed for
mutation.
