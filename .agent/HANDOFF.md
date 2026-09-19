# Agent Handoff — BM-018D typed skin configuration

## Status

BM-018D is complete on `agent/codex` at `39bd26c`:

`fix(BM-018D): resolve AF3 disposable live gate`

The branch remains separate from `matrix`; no history was rewritten and no
worker branch other than `agent/codex` was changed.

## What was done

- Moved the AF3 `HomeSwitcher.EnableIcons` / `HomeSwitcher.EnableIconText`
  mutual-exclusion rule into `resources/lib/af3.py`; generic skin-setting
  backend code has no AF3 hard-coded policy.
- Verified AF3 3.2.19's complete 18-node transitive closure in disposable
  Kodi. All nodes are installed, enabled, and not broken, with versions
  recorded before activation.
- Diagnosed the original fallback: AF3 was transiently loaded and the Yes
  confirmation was sent; `script.skinvariables` first-run generation then
  reloaded the skin during Kodi's keep/revert transaction, and Kodi returned
  to Estuary. The persisted setting also reverted to Estuary. The issue was
  not an unaccepted confirmation and not a missing dependency after closure
  enablement.
- Updated the disposable harness to initialize AF3's generated runtime state
  in `.kodi-test` only, then prove the actual BM-018A activation from Estuary.
- Corrected live Kodi typed skin-setting handling for lowercase AF3 IDs and
  Kodi's string-setter return value.

## Validation

- BM-018D disposable live gate: `17/17 passing`.
  - AF3 persisted and `xbmc.getSkinDir()` remained AF3.
  - typed bool/string deployment and authoritative read-back passed;
    identical reapply was idempotent; drift was repaired.
  - unmanaged setting preservation, BM-014 configuration validation, restart
    persistence, ownership preflight, and wrong-skin zero-mutation behavior
    passed.
- Focused skin/configuration tests: `264/264 passing`.
- Full unit suite: `1,438/1,438 passing`.
- `git diff --check`: passing.
- Real Kodi profile mtime unchanged; no real profile settings or generated
  state were copied; no Apple TV was accessed.

## Not done

- No production `af3-common` package was created.
- BM-017, BM-018E, BM-019, and BM-020 were not started.
- `matrix` was not integrated or modified. The current matrix SHA is
  `bd78cc29a8aa572cc43f393d94a470e4912f3d32`.

## Smallest next step

Supervisor-directed integration review of `agent/codex` commit `39bd26c`.
Do not start another Build Manager task from this handoff.

## Usage

No reliable Codex usage source was available. The existing BM-018D Luna/High
usage row remains exactly once in `.agent/USAGE_HISTORY.md`; no figures were
fabricated and no duplicate row was added.
