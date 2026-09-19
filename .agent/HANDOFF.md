# Agent Handoff — BM-018C AF3 portability inventory

**Agent**: Codex
**Branch**: `agent/codex`
**Status**: In progress. BM-017 remains deferred.

## Synchronization

- Refreshed `origin/matrix` at `91752ab`.
- Verified endpoint trees differ only in the four `.agent/*` metadata files.
- Verified `git diff --quiet origin/matrix HEAD -- . ':(exclude).agent/**'`
  exited successfully.
- Normal merge is in progress; metadata conflicts are being resolved as
  worker-specific state.

## Integrated behavior

- Resolver appends the winning skin's `config_packages` after ordinary
  resolved configuration packages.
- Package IDs use the existing deterministic first-seen de-duplication.
- Skin-only packages create `ResolvedBuild.config` with empty ownership scopes.
- Deepest-wins skin resolution means superseded skin package lists are not
  accumulated; inherited skins retain their package list.
- Planner emits the existing `CONFIGURE` action after `SET_SKIN`.
- BM-015 package format, loader, deployer, and bidirectional ownership checks
  remain unchanged. Validator package identity behavior remains unchanged and
  now naturally includes the merged selection.
- Documentation updated in `docs/MANIFEST.md` and
  `docs/CONFIG_PACKAGES.md`; the BM-015 module boundary text was corrected.

## Validation and boundaries

- Focused resolver/planner/config/validator tests: 510/510 passing.
- Full suite: 1412/1412 passing.
- No live Kodi mutation occurred.
- No production AF3 package was created and no AF3 configuration was copied.
- BM-017, BM-019, and BM-020 were not started.

## BM-018C scope

Research/classification only. Inspect installed AF3 read-only, AF3 source,
and Backup Pro history; then write `docs/AF3_PORTABILITY.md`. Classify typed
settings and candidate files as public portable, personal non-secret,
device-specific, generated runtime, private/secret, or unknown. Define the
minimal safe future `af3-common` package and overlay candidates. Do not start
BM-018D.
