# Current Task

## BM-018B — skin configuration package wiring

**Agent**: Codex
**Branch**: `agent/codex`
**Status**: complete; pending supervisor review

Resolved `SkinEntry.config_packages` into the existing generic BM-015
configuration pipeline. Ordinary packages remain first; winning-skin packages
are appended with deterministic first-seen de-duplication. Skin-only packages
create `ResolvedBuild.config` with empty ownership scopes, so existing BM-015
ownership checks remain fail-closed.

- Focused tests: 510/510 passing.
- Full suite: 1412/1412 passing.
- No live Kodi mutation; no AF3 package created.
- BM-017 not started.

Next action: supervisor review.
