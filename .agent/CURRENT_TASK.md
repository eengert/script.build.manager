# Current Task

## BM-020A production reconciliation executor

**Status**: BM-020A remains blocked from matrix integration. The executable
example correction is complete, but the disposable gate now reaches the real
repository owner and fails downloading the example's intentional
`https://example.invalid/repository.eengert-1.0.0.zip` bootstrap URL. No
production bypass or placeholder package was added.

Current matrix: `e2458d4f977e09769b01d8e8a82635497b913546`.

Correction commit: `0b05cdb` removes `redlight-common` and unsupported Red
Light managed-setting ownership from `eric-main.example.json`, keeps
`af3-common`, updates the example documentation, and adds general shipped
example package-existence coverage. Red Light portability remains deferred
under BM-016; `redlight-common` is not created.

Gate evidence:

- First rerun: the original Red Light preflight failure was eliminated.
- Second rerun: real planner emitted production owners for repository,
  dependency-aware add-on installation, skin activation, and configuration;
  execution stopped at `INSTALL_REPOSITORY` because `example.invalid` does not
  resolve. No successful action or AF3 application occurred.
- Focused tests: 384/384. Full suite: 1469/1469. `git diff --check` passed.

BM-019, BM-018D, and BM-018E remain complete and integrated. BM-020B/C and
BM-017 have not started. The real Kodi profile, Apple TV, and all devices
remained untouched. Next step requires a separately approved resolution for
the executable repository bootstrap; do not integrate to matrix yet.
