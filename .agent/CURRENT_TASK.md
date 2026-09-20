# Current Task

## BM-018D — typed skin-setting configuration synchronized

**Agent**: Codex (Luna / High)
**Branch**: `agent/codex`
**Worktree**: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`
**Status**: Complete and supervisor-approved; worker synchronized with
current `origin/matrix` and ready for an outgoing handoff.

Current protected matrix: `0e38797d90bb64cd19ca5e7608c41a741afb2e07`.
Substantive BM-018D work is already integrated on matrix as `28a6fd4` and
`5a3cc9a`; this synchronization changes history/metadata only and does not
alter implementation contents.

BM-018D conclusions remain authoritative:

- generic typed skin-setting support is complete;
- disposable AF3 live gate: 17/17 passing;
- full suite: 1438/1438 passing;
- the complete AF3 dependency closure must be installed, enabled, and not
  broken in the disposable environment;
- AF3 first-run generated-state initialization caused the original transient
  fallback; the harness bootstraps that state only inside `.kodi-test` before
  validating the actual BM-018A Estuary -> AF3 path;
- completely pristine first-ever AF3 provisioning is not overstated as proven;
- AF3 key normalization and non-boolean string-setter return handling are
  handled by the backend/runtime adaptation;
- AF3-specific mutual-exclusion policy remains isolated from the generic
  backend.

No production `af3-common` package was created. BM-018E, BM-017, BM-019, and
BM-020 were not started. No Apple TV or real Kodi profile was accessed for
mutation.
