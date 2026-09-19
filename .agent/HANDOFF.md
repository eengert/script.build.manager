# Agent Handoff — BM-018D typed skin configuration

## Status

Implementation and unit validation are complete in commit `0260ef8`:

`feat(BM-018D): add typed skin configuration support`

The disposable AF3 live gate is blocked by the local Kodi/AF3 activation
environment and is not represented as a pass.

## What changed

- `resources/lib/manifest.py` and `resources/builds/schema-v1.json`: explicit
  `target: addon|skin` for managed setting scopes; omitted target remains addon.
- `resources/lib/config.py`: target-kind identity, overlay, ownership,
  preflight, validation snapshots, dedicated skin backend dispatch, bool/string
  skin restriction, and the reviewed AF3 mutually-exclusive mode policy.
- `resources/lib/skin.py`: active-skin precondition and typed Kodi JSON-RPC
  `Settings.GetSkinSettingValue` / `Settings.SetSkinSettingValue` adapter;
  BM-018A confirmation handling now waits for loaded-skin/dialog lifecycle,
  supports both Kodi success result forms, and requires stable final state.
- `resources/lib/resolver.py` and `resources/lib/validator.py`: explicit
  target-aware merge and CONFIGURATION validation while accepting legacy addon
  snapshot pairs.
- `tools/kodi_test.py`: disposable `validate-skin-config` harness, synthetic
  AF3 bool/string package, in-Kodi production runner, idempotency/drift/
  ownership/wrong-skin/persistence checks, and real-profile mtime guard.
- `docs/AF3_PORTABILITY.md`, `docs/CONFIG_PACKAGES.md`, `docs/MANIFEST.md`,
  `docs/TESTING.md`: schema, runtime boundary, package specification, and
  harness documentation.
- Tests cover target parsing/backward compatibility, identity/overlay/
  ownership, dedicated skin reads/writes, validator snapshots, AF3 policy, and
  activation lifecycle.

## Validation

- Full unit suite: `1,436/1,436 passing`.
- Focused BM-018D/config/skin/validator suite: `722 passing`.
- `git diff --check`: passing.
- No real Kodi profile or Apple TV was mutated.

## Live evidence and blocker

The harness copied only installed AF3 `3.2.19` and available declared
dependencies into `.kodi-test`, seeded one synthetic disposable first-run
marker, launched Estuary, and invoked BM-018A through the production runner.
Kodi loaded AF3 transiently, but repeatedly reloaded it and ultimately fell
back to Estuary after the confirmation lifecycle. The final persisted/loaded
check correctly failed closed, so typed skin deployment was not falsely claimed.

The next smallest step is to resolve or reproduce that AF3/Kodi disposable
activation fallback, then rerun:

`python3 tools/kodi_test.py validate-skin-config`

No production `af3-common` package was created. BM-017, BM-018E, BM-019, and
BM-020 were not started. No worker branch other than `agent/codex` was changed.
