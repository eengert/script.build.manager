# BM-017F — Deferred Activation & Structured-Resource Lifecycle

## Latest continuation result — disposable Kodi JSON-RPC unavailable — 2026-09-23

Current classification: `BLOCKED_DISPOSABLE_KODI_JSONRPC_OPERATION_NOT_PERMITTED`.
The BM-022 quiescence-resume path now calls shared held-addon registry
readiness before configuration; BM-020 reuses that helper. It validates the
durable transaction and updater guard, confirms the full activation hold,
refreshes Kodi's local registry only when needed, and checks exact version and
disabled state through bounded supported-state polling. Unit and regression
tests cover the bypassed BM-020 hook, BM-020 `no_transaction` with a resumable
BM-022 transaction, ordering, hold persistence, and fail-closed results.

After the focused suites and full suite passed, the single newly authorized
command ran once through `tools/kodi_test.py` with the retained manifest and
ArtifactStore. Harness preflight verified disposable `HOME`
`/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.kodi-test/home`,
`KODI_HOME` unset, and configured executable
`/Applications/Kodi.app/Contents/MacOS/Kodi`. Kodi launched after disposable
fixture preparation, but its local JSON-RPC readiness request failed after 90
seconds with `<urlopen error [Errno 1] Operation not permitted>`. The harness
stopped Kodi and subsequent harness status confirmed no running process.

The failure preceded a BM-017F transaction and Red Light installation. No
quiescence restart, BM-020/BM-022 resume, registry query or refresh,
configuration, Red Light initialization, settings DB creation, private apply,
activation release, runtime start, or second reconciliation was reached. The
new production readiness path therefore remains unproven in live Kodi. The
single-run approval is exhausted; do not relaunch Kodi or rerun the harness.
Diagnostics are preserved at
`/private/tmp/bm017f-continuation-readiness-failure-2026-09-23.tar.gz`
(SHA-256
`588d2f858083cf611d8b97798c07160e9acea827acbf5675864f5865f9c1a827`).

No normal-profile path was accessed during this continuation. The prior
metadata-only normal-profile `test -e` and separate bare `Kodi -v` remain
historical safety deviations; they were not investigated further. No real
device, Kodi Build Manager Test.app, or real private value was accessed.
Current result: BM-017F blocked at the disposable JSON-RPC permission boundary;
Red Light clean-destination lifecycle **UNSUPPORTED**; macOS BM-023A
**STILL_BLOCKED**; tvOS **NOT VALIDATED**. Await supervisor direction and new
approval before any further live run or milestone.

## Historical lifecycle result — registry readiness bypassed — 2026-09-23

BM-017F is `BLOCKED_POST_RESTART_REGISTRY_READINESS_BYPASSED`. The exact
retained `plugin.video.redlight` 2.6.8 artifact was validated at SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`. The
implementation added generalized fail-closed registry readiness using Kodi's
`UpdateLocalAddons` discovery path and bounded JSON-RPC polling. Focused tests
and the complete suite passed before one directly authorized disposable run.

That run used `tools/kodi_test.py` with `HOME` at
`/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.kodi-test/home`;
`special://profile` resolved to its nested `Library/Application Support/Kodi/userdata`.
The exact Kodi binary launched by the harness was
`/Applications/Kodi.app/Contents/MacOS/Kodi`. Installation and the quiescence
restart completed. After restart, `run_startup()` logged BM-020
`no_transaction`, so its `ResumeCoordinator.before_reconcile` hook did not run.
BM-022 then entered its separate quiescence continuation through
`run_frozen_install_startup()` → `resume_after_restart()` → `install()` and
reached private-resource initialization without registry reconciliation.

Kodi logged `Unknown addon id 'plugin.video.redlight'` when Red Light's
package-owned initializer attempted `xbmcaddon.Addon("plugin.video.redlight")`.
No `UpdateLocalAddons` request or readiness markers were logged, so registry
state immediately before/after refresh is **unobserved** and refresh was **not
attempted**. The durable BM-022 transaction ended in
`needs_attention/configuring` with `FROZEN_CONFIGURATION_ACTION_FAILED`,
`failure=ACTION_FAILED`, one completed lifecycle restart, and the activation
hold unreleased. Private initialization was reached, but the initializer
failed before settings database creation or private-value writes. Activation
release, service start, and second-reconcile idempotence were not reached.
Red Light clean-destination lifecycle support remains **UNSUPPORTED**; BM-017F
is blocked and macOS BM-023A remains `STILL_BLOCKED`.

The previous failed-run evidence was archived before the harness reset, and
this failed-run evidence was archived after the attempt; both archives are
outside the disposable harness and contain only `.kodi-test` data and fake
private inputs. No further Kodi launch or runtime mutation occurred. One later
shell `test -e` checked only existence of a constructed settings-database path
under the normal profile; it did not read or modify profile contents. This
unintended metadata-only access is a recorded safety deviation. The earlier
bare `Kodi -v` is a separate historical deviation. No real device, Kodi Build
Manager Test.app, or real private value was used.

The single live-run approval is exhausted. The next code step requires
supervisor direction: invoke registry readiness from the BM-022 quiescence
continuation before configuration, and add a regression for the BM-020
`no_transaction` startup path. Obtain new explicit approval before any further
live lifecycle run. Do not resume BM-023A.

## Prior implementation context and accepted safety review — 2026-09-23

The exact Red Light 2.6.8 object was recovered from the retained local
ArtifactStore through the frozen manifest and validated through production
artifact/package validators. Its identity is
`plugin.video.redlight` 2.6.8, SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`. The
historical `BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE` result is
therefore invalidated. No artifact bytes were modified or added to Git.

The supervisor accepted the safety audit: purposeful BM-017F Kodi runs used
the disposable harness `HOME`
`/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.kodi-test/home`,
and Kodi startup logs mapped `special://profile` to the matching disposable
`userdata` path. Purposeful runs did not use the normal Kodi profile. The
shared `/Applications/Kodi.app/Contents/MacOS/Kodi` executable is the harness
binary; the profile is selected by its isolated `HOME`. The earlier bare
`/Applications/Kodi.app/Contents/MacOS/Kodi -v` invocation remains a separate
historical safety deviation: no process remained afterward, but transient
normal-profile access could not be ruled out. The normal profile was not
inspected or modified. No direct Kodi.app launch occurred after supervisor
clearance, and Kodi Build Manager Test.app was not used.

The resumed worker contains implementation changes for generic
`configure_before_activation`, durable activation holds, required and optional
dependent protection, staged restart/re-entry, updater quarantine, a bounded
Red Light-owned settings initializer, private apply/verification, and the
disposable runtime harness. The last completed purposeful lifecycle run before
the safety pause reached the quiescence boundary but failed during restart
resume with `FROZEN_INSTALL_ERROR` in `_handle_configuration_result`. Safe
failure-code diagnostics were added but have not been exercised. Review also
closed a gap where an unheld enabled add-on could reference the held owner via
an optional dependency.

Current non-runtime checks: focused suites **250/250**, full repository suite
**1659/1659**, `compileall`, schema JSON parsing, and `git diff --check` passed.
After the supervisor cleared the safety stop, automatic review rejected a new
`tools/kodi_test.py validate-bm017f-lifecycle` invocation because it did not
accept the attached clearance as a direct override for the previous runtime
stop. No retry or indirect workaround was attempted. BM-017F remains in
progress and its implementation is uncommitted pending direct approval for
that single disposable run. Do not resume BM-023A.

Current classifications: BM-017F **IN PROGRESS**; Red Light clean-destination
lifecycle **NOT YET SUPPORTED**; macOS BM-023A retry **STILL BLOCKED**; tvOS
**NOT VALIDATED**.

Status: **complete as an investigation/implementation attempt**. Result:
`BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE`.

This is the historical result of the first BM-017F attempt. It requires local
revalidation before it can be accepted: BM-023A-R1 reported 30 exact
artifact-backed installed managed add-ons, with Red Light 2.6.8 among them and
YouTube 7.4.4+unofficial.2 as the single exact-artifact gap. The retained frozen
manifest and ArtifactStore must be checked through the production model before
concluding that the Red Light object is unavailable.

BM-017F did not modify product code or begin a later milestone. The exact
Red Light 2.6.8 package is required to re-inspect its source before choosing an
initializer and to prove the complete clean-destination lifecycle. The
maintainer's published Omega metadata URL
(`https://repo.redwizard.xyz/redwizardrepo/21omega/addons.xml`) and the derived
exact package URL
(`https://repo.redwizard.xyz/redwizardrepo/21omega/plugin.video.redlight/plugin.video.redlight-2.6.8.zip`)
redirected to generic Google HTML in this run. The returned content was not a
ZIP and had SHA-256
`8cc849b78b499dd61b1cdc010f7e6446fe307c1bae069de7e53956eade4d3593`, which does
not match the previously verified package SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`. It was
rejected. No substitute, repack, or unverified archive was used.

## Current production ordering

The existing BM-022 install path stages and atomically renames the exact ZIP,
then calls Kodi's `UpdateLocalAddons` and polls for registration
(`KodiRuntimeFrozenArtifactBackend.install_exact()` in
`resources/lib/frozen_install.py`). Kodi discovery reports a newly added
non-system/non-optional add-on disabled. The coordinator then enforces each
manifest node's final `desired_enabled` state in the install loop. Only after
all resolved packages reach their terminal state does it enter `CONFIGURING`
and call the ordinary reconciliation runner (`FrozenInstallCoordinator.install()`).
For a desired-enabled service this remains:

```text
install -> register -> final enable -> configure/public config/private apply
```

The ordinary BM-020 planner also orders `ENABLE_ADDON` and `DISABLE_ADDON`
before `CONFIGURE`. `BuildManager` applies public configuration and then the
prepared private overlay, including structured private resources, within that
configuration action. Kodi's service manager starts an enabled service
extension on the `Enabled` event and runs its Python entrypoint asynchronously.
Thus applying a final enabled state before private configuration may start the
owner too early.

Restart ownership is split today:

1. `service.py` calls `run_startup()` before BM-022 finalization.
2. `run_startup()` calls `ensure_frozen_install_guard()` before it invokes
   BM-020 resume. The guard is reasserted before resumed reconciliation, and
   fails closed if it cannot be restored. `run_frozen_install_startup()` repeats
   this check defensively after BM-020.
3. BM-020 `ResumeCoordinator` validates the desired-state and overlay identity,
   runs ordinary reconciliation once, and moves to `NEEDS_ATTENTION` if that
   reconciliation still requests another restart.
4. BM-022 `resume_after_restart()` verifies a different Kodi session, reasserts
   updater quarantine, reloads and validates frozen resolution identities, and
   finalizes the frozen install. It does not rerun the configuration runner.

The updater guard therefore is reasserted before BM-020 startup work in the
current service path. However, neither transaction stores a structured-resource
lifecycle stage or activation-hold identity. BM-020 owns reconciliation and its
restart transaction; BM-022 owns frozen software, resolution, and updater
quarantine. There is no single durable owner for the sequence “hold, prove
quiescence, initialize, apply and verify private fields, release, then validate
runtime.” BM-020's one-restart contract also cannot advance through repeated
resource stages. A safe generalized coordinator design was not selected or
implemented without the exact resource package.

## Kodi 21.1 Omega activation findings

The disposable harness runtime reported Kodi 21.1. Source review used the
matching `21.1-Omega` tag:

- `CAddonDatabase::SyncInstalled()` inserts new IDs with `enabled=0`, except
  system and optional-system add-ons. `CAddonMgr::FindAddons()` scans the addon
  directories, synchronizes the installed registry, and refreshes caches.
- The `UpdateLocalAddons` builtin calls `FindAddons()` directly. This discovery
  path does not enable the new add-on or publish the enabled event that starts a
  service. Kodi's service manager starts enabled service extensions on startup
  and on the `Enabled` event; disabling emits a stop event.
- Kodi's separate native installer path calls `CAddonMgr::LoadAddon()` after
  copying a package. `LoadAddon()` enables the add-on if it is disabled. That
  path is not Build Manager's staged extraction plus local scan and must not be
  used for a deferred-activation install.
- For the staged local-scan path on Kodi 21.1, a new ordinary add-on is
  discoverable as installed while disabled. An existing ID with an extant
  disabled database record remains subject to that stored state; Build Manager
  does not edit Kodi's Addons database. No direct database manipulation was
  used.

Primary source links: [AddonDatabase.cpp](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonDatabase.cpp#L354-L415), [AddonManager.cpp: discovery](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonManager.cpp#L652-L684), [AddonBuiltins.cpp](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/interfaces/builtins/AddonBuiltins.cpp#L358-L366), [Service.cpp](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/Service.cpp#L34-L90), [native installer reload](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonInstaller.cpp#L729-L750), and [AddonManager.cpp: load/enable](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonManager.cpp#L711-L747).

## Disposable service proof

A synthetic helper and fake service were created only under `.kodi-test`, then
removed by resetting that harness. Kodi was launched with the harness's
disposable `HOME`; no Kodi Build Manager Test app, device, Red Light package,
provider, or private value was used. A separate version-check command mistake
without that `HOME` is disclosed in the worker handoff; a later process check
found no running Kodi process, but no normal profile was inspected and
transient startup or profile access cannot be ruled out.

| Check | Observation |
|---|---|
| Staged folder followed by `UpdateLocalAddons` | `scan_registered=true` |
| State after registration | `enabled_after_scan=false` |
| Explicit disabled hold via Kodi JSON-RPC | `hold_rpc_no_error=true`; `enabled_after_hold=false` |
| Fake service before and after hold | Startup marker absent |
| Same disabled state after a full harness restart | Disabled; marker absent |
| Enable after creating a fake readiness sentinel | Service marker appeared and recorded readiness true |

This proves the synthetic Kodi 21.1 registration/activation path. It does not
prove Red Light initialization, Red Light's background behavior, dependency
startup interactions, or end-to-end lifecycle safety. The disposable harness is
currently stopped and reset.

For a newly staged standalone ordinary add-on under this Kodi version, the
evidence supports a no-race registration hold. It does not prove safety against
another coordinator enabling that add-on as a dependency. An already-enabled
owner that may have executed earlier in the same process still requires a
process restart while disabled before structured private mutation can claim
quiescence. Native Kodi installer reinstallation is not an acceptable
substitute because its load path may enable the owner immediately.

## Dependency and activation safety

Kodi distinguishes installed presence from enabled state. Its dependency
resolver looks up dependencies including disabled add-ons, so a held add-on
remains present for package dependency resolution. However, `CAddonMgr::EnableAddon()`
walks required dependencies, then enables the dependency closure; each transition
publishes `Enabled`, which can start service extensions. A separately enabled
dependent can therefore undo an add-on's temporary disabled state.

Build Manager makes the same distinction: BM-012 reports an installed-disabled
dependency separately from a missing package, but
`DependencyResolver.reconcile_dependencies()` enables required disabled
dependencies before `DependencyAwareInstaller` installs the requested root.
BM-020 preflights required closures of desired-enabled roots; that closure
currently protects dependencies from inappropriate disable actions, but does
not implement a deferred-activation barrier. This is not permission to disable
unrelated add-ons.

Because the exact package and its dependency metadata could not be re-inspected,
and no package-specific enabled-root graph was validated in this disposable
probe, this run does not prove that no other managed startup add-on can enable
or invoke Red Light before private configuration. A future generic lifecycle
coordinator must account for the affected required dependency/dependent closure
and either propagate a narrow activation barrier or fail closed when it cannot
prove safe ordering. That graph behavior remains unimplemented and untested.

Source: [AddonManager.cpp: dependency lookup and enable](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonManager.cpp#L771-L876).

## Red Light initialization and validation disposition

BM-017E's previously verified source audit remains historical evidence for the
exact package SHA above. It identified `base_cache.ensure_database_tables()` as
the add-on-owned DDL helper and `settings_cache.sync_settings()` as the default
seed/migration path. The latter performs broader settings work than a narrow
initializer contract. BM-017F could not repeat this audit against the exact ZIP,
prove import-time or call-time side effects, inspect the package's current schema
and WAL contract, or test initialization without provider/network/UI/service
activity. No initializer was called and no generic SQL or file-copy substitute
was introduced.

Accordingly, BM-017F did not attempt resource initialization, fake private
field application, restart continuation, activation release, second-run
idempotence, or package-specific runtime verification. The existing
`resources/lib/redlight_resource.py` continues to fail closed for an absent
resource and an uninitialized lifecycle. No success or retry readiness is
claimed.

## Exact next step and historical classification

Revalidate the retained Family Room frozen manifest's Red Light artifact
reference and resolve that reference through the production ArtifactStore API.
If the exact object exists, check the pinned SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`, size,
ZIP integrity, package root, traversal/symlink safety, and addon ID/version
before opening its source. If it is missing or the manifest reference is
inconsistent, report that precise retained-state result. Do not use a
substitute.

- BM-017E historical result:
  `BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`.
- BM-017F first attempt: complete as investigation/implementation attempt;
  historical result `BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE`,
  pending retained-manifest and ArtifactStore revalidation.
- Red Light clean-destination lifecycle: **UNSUPPORTED**.
- macOS BM-023A retry: **STILL_BLOCKED**; not started.
- tvOS: **NOT VALIDATED**.
- Product implementation: **none**.

## Validation

- Focused BM-017A/C, BM-020, BM-022, BM-023B, planner, dependency, and manifest
  regressions: **703/703**.
- Full repository suite: **1647/1647**.
- `compileall`: passed.
- JSON parsing: **7 files** parsed successfully.
- `git diff --check`: passed.
- Disposable fake-service probe: registration remained disabled across the
  tested scan/hold/restart path; it started only after the fake readiness
  sentinel was present and Kodi enabled the service.
