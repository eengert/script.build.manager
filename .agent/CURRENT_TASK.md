# Current Task

## BM-018E — production AF3 common typed-settings package

**Agent**: Codex
**Branch**: `agent/codex`
**Status**: Implementation complete; production-package live gate blocked by
Kodi 21.1 runtime API behavior. The task is not ready for matrix integration.

Created `resources/config/packages/af3-common/package.json` with the approved
16 typed `skin.arctic.fuse.3` settings, no file overlays, and explicit
manifest ownership. The six reviewed candidates intentionally remain
unmanaged. BM-018D's typed skin backend, normalization, idempotency, drift
repair, and fail-closed ownership checks remain authoritative.

Prior validation: focused package/resolver/schema tests 61/61; BM-018D
synthetic typed-runtime gate 17/17; full unit suite 1453/1453.

BM-018E continuation validation loaded the installed disposable production
manifest/profile and installed `af3-common` package, copied AF3 3.2.19 and
its complete 18-add-on closure, proved planner `SET_SKIN -> CONFIGURE`
ordering, bootstrapped AF3 generated state only in `.kodi-test`, and proved
BM-018A activation. The actual package applied 12/16 targets, but Kodi 21.1
returned `-32602 Invalid params` for both canonical and lowercase forms of
`Navigation.OnBack`, `View.UseDetailedListLabels`,
`Widgets.DisableNoResultsItem`, and `Widgets.EnableShowMore`. The live gate
stopped before claiming idempotency, drift, ownership, or restart completion.

The real Kodi profile and all devices remained untouched. BM-017, BM-019, and
BM-020 were not started. The smallest next step is a separately reviewed
resolution of the Kodi runtime/API incompatibility; do not weaken the approved
16-setting package or reopen BM-018D.
