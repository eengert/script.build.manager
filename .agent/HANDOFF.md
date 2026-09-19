# Agent Handoff — BM-018C AF3 portability inventory

**Agent**: Codex
**Branch**: `agent/codex`
**Status**: Complete. BM-017 remains deferred.

## Synchronization

- Refreshed `origin/matrix` at `91752ab`.
- Verified endpoint trees differ only in the four `.agent/*` metadata files.
- Verified `git diff --quiet origin/matrix HEAD -- . ':(exclude).agent/**'`
  exited successfully.
- Normal synchronization merge completed as `0366a90`, with parents
  `4ad00f1` and `91752ab`. It was pushed to `origin/agent/codex`.

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

## BM-018C result

Research/classification completed in `docs/AF3_PORTABILITY.md` (commit
`db58403`). The specification records:

- installed AF3 identity/version (`skin.arctic.fuse.3` `3.2.19`), helper
  ownership, typed settings, profile-relative file layout and lifecycle;
- the minimal safe common subset: reviewed typed bool/string preferences only,
  with no whole-file state;
- menu/widget source classification, path/add-on/credential checks and
  personal-overlay boundary;
- generated viewtype/include/hash/checksum exclusions;
- private login/authentication exclusions owned by BM-017;
- platform/device overlay criteria and BM-018D typed skin-setting backend and
  disposable-profile validation requirements.

Validation: full unit suite `1412/1412` passing. No live Kodi mutation, no
Apple TV access, and no production AF3 package was created.

## Smallest next step

Supervisor review of `docs/AF3_PORTABILITY.md`; then decide whether BM-018D
should implement the typed AF3 skin-settings backend. Do not start BM-018D
automatically.
