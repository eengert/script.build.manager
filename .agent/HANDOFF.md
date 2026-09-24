# Current Handoff — BM-023A adapter bootstrap corrected offline (2026-09-24)

BM-017F remains complete and synchronized to matrix `66b0fd8`.

BM-023A's namespace-package TypeError is corrected offline. The authoritative
source is now the tracked `tools/build_bm023a_adapter.py` generator with
templates in `tools/bm023a_adapter/` and strict source-check/diagnostic helpers
in `tools/bm023a_adapter_support.py`. The prior one-off existed only under
`/private/tmp`; no project generator was found. The one-off was intentionally
outside Git because it embeds machine-specific portable paths and the
private-overlay source path. The tracked builder preserves those values only
in generated output and carries them forward only from six allowlisted string
assignments. Adapter version advanced from 0.0.1 to 0.0.2 to ensure Kodi sees
the corrected ZIP as an upgrade; packaging retains the built-in ZIP-installer
layout.

The fixed bootstrap imports `resources.lib`, resolves its concrete `__file__`,
and requires it to be exactly the package initializer inside the canonical
installed `script.build.manager` tree. The add-on root must be the direct
child of the canonical installed add-ons root. Host/project collisions,
wrong roots, and symlink/path escapes fail closed. The namespace package's
`resources.__file__` is never dereferenced. Failures expose only allowlisted
`adapter_stage`, `failing_callable`, `failure_category`, and `error_type`;
there is no raw exception text, traceback, or path in diagnostics. The
successful result also omits private overlay ID/fingerprint.

Offline validation: adapter/bootstrap tests **16/16**, BM harness tests
**124/124**, compileall, JSON parsing, and `git diff --check` pass. The corrected
0.0.2 ZIP was regenerated under `/private/tmp` from the tracked source. No
Kodi app/profile, normal profile, real device, or private-overlay file was
accessed; no live retry was run. macOS BM-023A is **READY_TO_RETRY**, not
passed; BM-017F remains complete; tvOS is not validated. The supervisor may
authorize the separate live retry.

## Prior handoff — BM-017F complete and synchronized (2026-09-24)

**Result**: `BM-017F COMPLETE`. The reviewed substantive endpoint diff was
reconstructed onto protected matrix as `4dfd97e180d14976adec8540d5c0c93893519249`;
neutral matrix tracking brings its pushed tip to
`66b0fd8a123ef778b23ba42703937b07eefc4e6f`. The worker was synchronized by a
normal merge. No worker history was rewritten, and no unrelated product
changes or disposable profile contents entered matrix. The only follow-up
correction during matrix validation reordered test mocks so the import spy
records add-on imports rather than its own `unittest.mock` target resolution.

The supervisor-provided final disposable validation passed all eight steps
and all twenty checks. Red Light structured private-resource lifecycle is
`LIVE-VALIDATED`. The evidence was restricted to `.kodi-test`; this
integration did not launch Kodi or access a normal Kodi profile, real device,
or private overlay values.

Matrix validation: focused lifecycle/resource/import/harness modules
**499/499**; full repository suite **1782/1782**; `compileall`; all **7
tracked JSON files** parsed, including the schema; `git diff --check` passed.

BM-023A macOS is `READY_TO_RETRY`; no retry was started. tvOS remains
`NOT VALIDATED`.

**Smallest next step**: wait for the next supervisor-authorized task, the
actual macOS BM-023A retry against `/Applications/Kodi Build Manager Test.app`,
launched exactly with `open "/Applications/Kodi Build Manager Test.app" --args -p`.

The historical BM-017F pending and blocker records below are retained for
audit context and are superseded by this completion handoff.

---

# Historical Handoff — BM-017F bounded service-start poll

Implemented the narrowly scoped disposable-harness fix. After unchanged
step-[3/8] completion checks (enabled, exact Red Light version, frozen
transaction absent), the harness polls only the current disposable
`.kodi-test/home/Library/Logs/kodi.log` for `Main Monitor Service Starting`,
using a monotonic 30-second deadline and 0.25-second intervals. A timeout has
a specific Red Light service-start diagnostic. Step [4/8] still checks all
five markers and its safety order; BM-020 classification remains required
presence-only. No production lifecycle code changed.

Added nine service-start-poll regressions. BM-017F poll/resume/order tests
passed 26/26; `tests.test_kodi_harness` passed 124/124; compileall and
`git diff --check` passed. No Kodi process or live BM-017F command was run.
The complete lifecycle remains `IMPLEMENTED_PENDING_FINAL_LIVE_VALIDATION`.
The supervisor still needs to run the full disposable live gate using the
manual command below. The earlier `Unknown addon id 'plugin.video.redlight'`
exception remains an observed diagnostic only, from before release while the
add-on was disabled; it did not prompt a production change. BM-023A remains
blocked; tvOS remains not validated; no new milestone started.

# Prior offline service-start marker diagnosis

Latest disposable-run evidence supports a harness service-start race, not a
proven Red Light startup failure. Step 3 breaks as soon as the owner is
enabled and the frozen transaction is absent. It does not wait for Red
Light's asynchronous `xbmc.service` entrypoint. Step 4 reads the log
immediately; if the marker is absent, its exception path runs the `finally`
block, which stops Kodi. The marker check is before the stop, not after it.

Current-run timeline: second session `Starting Kodi` 21:41:07.403; JSON-RPC
and webserver ready by 21:41:10.800; updater guard 21:41:11.237; held Red
Light registry state registered at 2.6.8/disabled 21:41:11.591; an
`Unknown addon id 'plugin.video.redlight'` exception 21:41:12.245; private
verification 21:41:12.972; activation release 21:41:12.976; BM-020C
`no_transaction` 21:41:13.002. The service-start marker is absent from both
logs for this run. No service-specific traceback, dependency failure, or
service-start attempt was found. Kodi's final Addons33 state is enabled for
Red Light, and both durable BM transaction files are absent. Current test
updater policy is AUTOMATIC; exact equality with the in-memory original
captured by the harness was not logged because step 4 failed before that
read-back.

The pre-release Unknown addon id exception is notable but does not evidence
service startup failure: it occurred while the add-on was recorded disabled,
and BM-022 subsequently logged private verification, activation release, and
transaction completion. Kodi shutdown time was not preserved; the stop is
inferred from the harness `finally` path and absent PID file. A prior run took
205 ms from release to service marker; this run reached the BM-020 marker 26
ms after release and then checked immediately, so stopping within a plausible
asynchronous service-scheduling window is consistent with the evidence.

At diagnosis time the state was `BLOCKED_BM017F_HARNESS_SERVICE_START_RACE`.
The requested bounded poll is now implemented; it does not itself prove live
service startup. Final disposable validation remains pending.

## Prior checkpoint: step-4 ordering correction

The harness-only ordering defect is corrected and the regression suite passes.
Step [4/8] continues to require every marker but now asserts the production
safety invariant `updater guard < private verification < activation release <
service start`. The BM-020 startup-classification marker remains required but
is treated as a post-resume diagnostic with no ordering constraint. No
production lifecycle behavior changed.

Nine focused ordering regressions cover the observed order, BM-020 before
private verification, invalid safety orders, missing markers, and rejection
of the old chained classification predicate. `python3 -m unittest
tests.test_kodi_harness` passed **115/115**; targeted compileall and
`git diff --check` passed. No Kodi launch or live lifecycle validation was
performed. BM-017F is `IMPLEMENTED_PENDING_FINAL_LIVE_VALIDATION`; the
supervisor must run the manual command below. BM-023A remains blocked and
tvOS remains not validated.

Unchanged remaining gates: [5] second BM-015 reconciliation succeeds with
zero changed/failed actions; [6] stopped-Kodi read-only DB checks verify exact
schema, WAL, fake private field, unrelated-row preservation, initialized
defaults, and fake-value absence from logs/transaction; [7] exact Red Light
artifact SHA and dependency artifacts; [8] completion while inspection stays
inside `.kodi-test`. Step [3] still requires enabled exact-version Red Light
and no durable transaction. Step [4] still checks complete marker presence,
safety order, fake-value log absence, and original updater-policy restoration.
These later gates were inspected, not executed.

## Result

The following timestamps and diagnosis are the pre-correction evidence that
motivated the harness fix above; the stale ordering predicate was corrected
without changing production behavior.

The latest supervisor-run disposable log contains every step-[4/8] marker
once, but not in the order the harness requires. Its expected sequence is
`guard < BM-020 startup classification < private verified < hold released <
service start`; actual local timestamps (2026-09-23, America/New_York) show:

- Updater guard reasserted: 21:02:46.407.
- Held Red Light registry state: 21:02:46.685, registered at 2.6.8 and disabled.
- Private resource verified: 21:02:48.057.
- Activation hold released: 21:02:48.062.
- BM-020 classification `no_transaction`: 21:02:48.094.
- Red Light service start: 21:02:48.267.

Thus the exact false term is `BM-020 startup classification < private
verified`. `service.py` emits that classification after
`run_frozen_install_startup()` returns, so the observed order
`guard < private verified < hold released < BM-020 classification < service
start` is expected. The live safety invariant
`private verification < activation release < service start` held, and the
updater guard was active before resumed registry/config work.

The stage-[3] poll reached step [4/8] only after reading the owner as enabled
and the frozen transaction as absent. The settings DB exists, passes
`integrity_check`, is WAL, and has the expected schema; no setting values were
read. The final policy read-back maps to `NEVER_CHECK`; source ordering plus
transaction clear shows restore to the captured original succeeded, though
the original enum is not separately retained. No restart transaction or
`needs_attention` state remains. A separate ERROR-level `unknown addon`
diagnostic at 21:02:47.286 is outside the step-[4/8] predicate and its
producer is not identified by retained evidence.

`reset()` deletes the disposable root before each run. Kodi rotated the first
session into `kodi.old.log` (startup 21:02:31.204); the second session began
in `kodi.log` at 21:02:44.910. Step [4/8] reads only the latter. Each required
marker appears once there; the BM-020 marker in the old log belongs to the
first session and is excluded. Current fixture/result file times follow the
reset, so stale artifacts did not affect the comparison.

## Classification and next step

- BM-017F: `IMPLEMENTED_PENDING_FINAL_LIVE_VALIDATION`.
- Red Light core safety ordering: **LIVE-PROVEN**; complete eight-step gate:
  **NOT YET LIVE-VALIDATED**. Step-[4/8] harness correction passed offline
  regression tests; supervisor manual live validation remains required.
- macOS BM-023A: `STILL BLOCKED`.
- tvOS: `NOT VALIDATED`.
- No normal Kodi profile, real device, or private overlay values were accessed.

The response-shape fix was exercised by the supervisor with the command below.
This harness-ordering correction did not run it. The supervisor should run the
command below to validate the corrected step [4/8] and continue gates [5/8]
through [8/8].

```sh
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

---

# Previous Handoff — BM-017F Requests alias correction ready for live validation

## Result

Committed the verified Requests compatibility-alias correction and regression
coverage as `81e8b2c` on `agent/codex`. The provider resolver determines
ownership from canonical module source locations (`__file__`, spec origin, and
namespace `__path__`) and accepts only one matching frozen provider. Requests
2.31.0 aliases are limited to `urllib3`, `idna`, and `chardet`; each alias must
come from its matching provider in the verified dependency closure, remain
anchored under the verified Requests package, and be the identical object in
the canonical provider entry in `sys.modules`. Host packages and unrelated
cross-provider aliases fail closed.

Cleanup snapshots controlled preexisting modules and their dictionaries,
removes every newly created Requests, dependency, owner, namespace, and alias
entry under the temporary import roots on success or failure, and restores
`sys.path` and `sys.meta_path`. The regression covers ownership-check failure
followed by a successful same-process retry; legitimate preexisting Requests
and urllib3 modules and an unrelated shared module remain intact.

Ownership failures carry a safe category and validated module/provider IDs
through Red Light initialization, Build Manager action results, and the frozen
CONFIGURE transaction status. Paths, exception text, and private values are
excluded.

## Validation and limits

- Requested focused regression set: **456 passed**.
- Full repository `unittest` suite: **1,756 passed**.
- Manifest/schema suite: **50 passed**.
- `compileall` passed; all **7 tracked JSON files** parsed; `git diff --check`
  passed.
- No Kodi executable or BM-017F lifecycle harness command was run. No normal
  Kodi profile, real device, or private overlay values were accessed.

Classification: `IMPLEMENTED_PENDING_ALIAS_LIVE_VALIDATION`. The historical
`BLOCKED_RED_LIGHT_REQUESTS_ALIAS_SOURCE_MISMATCH` is corrected offline and
awaits supervisor live proof. Red Light's lifecycle remains **NOT YET
LIVE-VALIDATED**; macOS BM-023A remains **STILL BLOCKED**; tvOS remains **NOT
VALIDATED**.

## Smallest next step

The supervisor runs the following disposable lifecycle command manually from
normal Terminal. Codex did not run it:

```text
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

Required human input: supervisor review of the live stage/result before any
further BM-017F work. Do not claim completion from offline tests alone.

---

# Previous Handoff — BM-017F import-path correction implemented

## Result

Implemented the correction for `BLOCKED_RED_LIGHT_IMPORT_PATH_CONTEXT` in
`93be55a3e3a900de488d388c88fbf39aca885869` on `agent/codex`. Red Light's
temporary owner import root is derived from its verified installed
`addon.xml` module declaration and resolves to the canonical
`plugin.video.redlight/resources/lib` directory.

The import context adds only the frozen transaction's verified Python-module
dependency closure required by the audited initializer: requests 2.31.0,
urllib3 2.2.3, certifi 2023.5.7, chardet 5.1.0, and idna 3.10.0. The exact
versions and enabled registry state must match the frozen records. It rejects
unverified or colliding top-level modules, checks namespace `__path__` as well
as ordinary `__file__`, restores `sys.path` and legitimate prior modules, and
cleans up imported owner namespace modules on success and failure.

Red Light remains held disabled. Its installed package still supplies the
schema/default declarations, value converter, marker constants, and property
setter. Offline source review found no database, provider network,
authentication, service-start, or background-worker side effects in the
audited initializer import chain. No `xbmcaddon.Addon("plugin.video.redlight")`
source lookup was reintroduced.

## Validation and limits

- Focused source/import/resource/private-overlay/build/dependency/frozen
  transaction and resume suites: **354 passed**.
- Full repository suite: **1,742 passed**; manifest/schema suite: **50 passed**.
- `compileall` passed; all **7 tracked JSON files** parsed; `git diff --check`
  passed.
- BM-017F was not live-validated in this task. Kodi and the lifecycle harness
  were not run. No normal Kodi profile, real device, or private overlay values
  were accessed.

Classification: `IMPLEMENTED_PENDING_IMPORT_LIVE_VALIDATION`. The historical
`BLOCKED_RED_LIGHT_IMPORT_PATH_CONTEXT` correction awaits live proof. Red Light
clean-destination lifecycle remains **NOT YET LIVE-VALIDATED**; macOS BM-023A
remains **STILL BLOCKED**; tvOS remains **NOT VALIDATED**.

## Smallest next step

The supervisor runs the following disposable lifecycle command manually from
normal Terminal. Codex did not run it:

```text
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

Required human input: supervisor review of the live stage/result before any
further BM-017F work. Do not claim completion from offline tests alone.

---

# Previous Handoff — BM-017F stage diagnostics ready for live validation

## Work completed

Committed narrowly scoped Red Light initializer stage diagnostics and
regression coverage as deae656 on agent/codex. The current changes preserve
BM-017F lifecycle ordering and the activation hold. The prior uncommitted
offline-diagnosis tracking changes were preserved and updated below this source
commit.

The actual RedLightSettingsAdapter.initialize() sequence is covered at these
boundaries in resources/lib/redlight_resource.py:

1. Resource declaration/version validation and existing-resource inspection.
2. Quiescence, hold, and frozen installed-source context validation, including
   the immediate pre-import source revalidation.
3. Package helper imports and schema declaration loading.
4. Add-on-data directory and database-directory creation.
5. SQLite open, WAL setup, and schema execution/commit.
6. Package defaults preparation and row insertion.
7. Persisted-row, WAL, and schema validation.
8. Publication of the two existing sync markers.

## Diagnostic propagation

ResourceInitializationStage and ResourceInitializationCause provide
allowlisted typed codes. Failures preserve the high-level
PRIVATE_RESOURCE_INITIALIZATION_FAILED code and safe owner/resource identity,
plus initialization_stage, last_completed_stage, and a typed cause. The
fields pass through StructuredPrivateResourceManager, the private-overlay
boundary, Build Manager CONFIGURE result, and
FrozenInstallCoordinator._handle_configuration_result into the durable
transaction status_message.

The transaction stores only fixed stage/cause codes and validated owner,
resource, and action identifiers. Raw exception text, filesystem paths, row
contents, fake secrets, and private overlay values are excluded. New optional
action-result fields are omitted for legacy diagnostics, preserving their
serialized shape.

## Tests and checks

- Focused Red Light resource, private overlay, CONFIGURE diagnostic,
  Build Manager, and frozen transaction/readiness suites: 93/93.
- Full repository unittest suite: 1,722/1,722.
- compileall for resources, tests, and tools: passed.
- All 7 tracked JSON files parsed; git diff --check passed.
- Test harness dispatch cases are mocked. Codex did not launch Kodi or run
  validate-bm017f-lifecycle.

## Classification and next action

IMPLEMENTED_PENDING_DIAGNOSTIC_LIVE_VALIDATION. Red Light clean-destination
lifecycle remains NOT YET LIVE-VALIDATED. macOS BM-023A retry remains
STILL BLOCKED; tvOS is NOT VALIDATED. Wait for the supervisor to run the
manual disposable lifecycle command and inspect its persisted safe stage/cause.
Do not automatically rerun after a failure.

Exact next manual command, when directed by the supervisor:

```text
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

No normal Kodi profile, real device, or real private overlay values were
accessed. Preserved disposable runtime evidence was left unchanged.

---

# Previous Handoff — BM-017F Codex JSON-RPC block (superseded by Terminal evidence)

## Follow-up transport investigation — loopback blocked

With Kodi stopped, a no-Kodi Python HTTP server bind to `127.0.0.1` on an
ephemeral port failed with `PermissionError`, errno 1 (`EPERM`). No port was
selected and no HTTP listener started, so urllib, direct socket-client, and
curl requests were not attempted. This meets the environment-block condition;
no alternate host, port, or transport was tried. Classification:
`VALIDATION_ENVIRONMENT_LOOPBACK_BLOCKED`.

Historical project handoffs record that the disposable BM-022
`validate-frozen-install` gate and BM-020C `validate-build-manager-resume`
gate succeeded and exercised `JSONRPC.Ping`. The successful BM-022 source at
`27f4215` and the current harness both target
`http://127.0.0.1:8920/jsonrpc` through `urllib.request.urlopen()`. Both write
the enabled webserver setting and port 8920 to disposable `guisettings.xml`
before launch. Git history shows no request, webserver, launch command, or
launch-environment change since BM-022; the current harness's functional
changes are the BM-017F command/fixture and lexical profile-isolation check.
The old records do not state whether those successes used the same Codex
execution sandbox or record proxy variables.

During this investigation all uppercase and lowercase HTTP_PROXY, HTTPS_PROXY,
ALL_PROXY, NO_PROXY, and no_proxy variables were unset. `urllib`'s loopback
proxy-bypass checks returned false; because explicit proxy variables were
absent, no environment-proxy route was indicated. The bypass result alone does
not establish whether a system-level proxy is configured; no proxy URL/value
was printed or further inspected. A proxy cannot explain the failed server
bind; the current execution surface denies loopback listener creation. No code
was changed.

## Work completed

The preserved BM-017F implementation now places held-addon registry readiness
in BM-022's own post-restart continuation, before configuration, so it does not
depend on BM-020 having a transaction. BM-020 reuses the same readiness helper.
The helper reloads durable ownership, checks updater quarantine and the full
activation hold before and during refresh, derives exact expected versions,
uses supported `UpdateLocalAddons`, and verifies registered-disabled state with
bounded polling. Regression coverage includes BM-020 `no_transaction` with a
resumable BM-022 transaction, ordering, failure modes, exact-version state, and
hold persistence.

The retained Red Light 2.6.8 ArtifactStore object is validated at SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`. The
harness isolation check was also changed to avoid resolving or probing the
normal-profile path; it verifies only lexical disposable paths and disposable
symlink components. The implementation, regression tests, and sanitized
handoff are committed on `agent/codex` as `beff4f1`.

## Validation

- Registry/readiness/frozen-install focused suites: **48/48**.
- Full repository suite: **1,690/1,690**.
- `compileall`, schema/status JSON parsing, and `git diff --check`: passed.
- The new full-hold regression first failed with a mutable mock that changed
  the same in-memory transaction. The fixture was corrected to model durable
  transaction replacement; targeted tests and the full suite then passed.

## One authorized live run

The exact authorized `tools/kodi_test.py validate-bm017f-lifecycle` command was
run once with retained manifest
`/private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json` and
ArtifactStore `/private/tmp/bm022v-familyroom.ygB0t5/artifact-store`. Isolation
preflight verified HOME
`/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.kodi-test/home`,
`KODI_HOME` unset, configured binary
`/Applications/Kodi.app/Contents/MacOS/Kodi`, and a stopped starting state.

Kodi launched through the harness (PID 79755). Reset, fixture preparation,
Build Manager runner setup, and webserver configuration completed. Kodi did
not answer the harness JSON-RPC readiness request within 90 seconds; the last
error was `<urlopen error [Errno 1] Operation not permitted>`. The harness
stopped Kodi, and its status command confirmed `running: False`, `pid: None`.
The failure occurred before a BM-017F transaction or Red Light installation.
No restart, BM-020/BM-022 resume, registry query/refresh, resource
initialization, settings DB creation, private apply, activation release,
runtime start, or idempotence was reached. The production readiness fix was
not exercised live. Do not rerun under this approval.

Diagnostics: `/private/tmp/bm017f-continuation-readiness-failure-2026-09-23.tar.gz`,
SHA-256 `588d2f858083cf611d8b97798c07160e9acea827acbf5675864f5865f9c1a827`.

## Safety and next step

This continuation used Kodi only through `tools/kodi_test.py` and did not
access the normal Kodi profile, any real device, Kodi Build Manager Test.app,
or real private values. The earlier normal-profile metadata-only `test -e`
and separate bare `Kodi -v` invocation remain documented historical safety
deviations; do not investigate them or access that profile. No BM-023A retry
or tvOS validation was started.

Current classification: `BLOCKED_DISPOSABLE_KODI_JSONRPC_OPERATION_NOT_PERMITTED`;
Red Light clean-destination lifecycle **UNSUPPORTED**; macOS BM-023A
**STILL_BLOCKED**; tvOS **NOT VALIDATED**. The smallest next step is
supervisor direction on the disposable harness's local JSON-RPC permission,
followed by new explicit approval before another live run. Preserve all current
worker changes; do not start another milestone.

---

---

# Historical Handoff — BM-017F resumed after qualified matrix integration

BM-017F first attempt is complete as an investigation/implementation attempt.
Its historical result is `BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE`,
but that result requires revalidation: BM-023A-R1 reported Red Light 2.6.8
among 30 exact artifact-backed installed managed add-ons, with YouTube as the
single exact-artifact gap. The pinned Red Light SHA-256 is
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`.

The sanitized audit was integrated on protected `matrix` as `ad48ff4` and
qualified in `ed92808`; neutral tracking is `fedefae98aa01253e6b34ecbac1b292b80c21b6a`.
Only the audit and neutral BM-017F tracking were integrated. Worker metadata
and the worker usage row remain on `agent/codex`. The worker now synchronizes
by normal merge from this matrix tip; there is no reset, rebase, or force-push.

The audit recorded these Kodi 21.1/Omega findings: ordinary newly discovered
add-ons defaulted disabled; `UpdateLocalAddons` did not start the fake service;
the fake service started only after enable. Kodi native install/reload and
Build Manager dependency reconciliation remain activation paths that require
lifecycle coordination. The full managed-graph activation barrier is
unresolved. The prior focused suite passed **703/703**, the full suite passed
**1647/1647**, compileall and seven JSON parses passed, and `git diff --check`
passed. No production code changed in that first attempt.

A safety deviation remains recorded: `/Applications/Kodi.app/Contents/MacOS/Kodi -v`
was invoked without disposable `HOME`. A later check found no Kodi process, but
transient normal-profile access could not be ruled out. The normal Kodi profile
was not inspected and must not be inspected to investigate that deviation.

The resumed BM-017F run is now revalidating the retained frozen-manifest
reference and ArtifactStore object through production APIs. No result is claimed
yet. No Family Room/device access or real private values were used. BM-023A
retry was not started; tvOS remains NOT VALIDATED.

**Smallest next step**: finish the retained manifest and ArtifactStore lookup.
If the exact object exists, validate its pinned bytes and resume BM-017F. If it
is absent or inconsistent, record the precise retained-state blocker and stop.
Do not resume BM-023A.

---

# Agent Handoff — BM-017E audit integrated on matrix

BM-017E is complete as a static investigation with result
`BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`. Only the sanitized
`docs/BM017E_RESOURCE_LIFECYCLE_AUDIT.md` from worker commit `e94046d` was
integrated as matrix commit `7075d59`; worker `.agent/*` was excluded. Matrix
tracking remains neutral with `active_agent: none`.

The audit records the exact public Red Light 2.6.8 package hash, its own DDL and
WAL paths, the broader effects of settings synchronization and normal service
startup, and why current BM-020/BM-022 ordering cannot maintain quiescence and
resume private configuration across another restart. No Red Light code or
Kodi runtime was executed for this documentation-only integration. The audit
tracking assertions and `git diff --check` passed; no product tests were run.

BM-023A-R1 remains historically `BLOCKED_RESOURCE_NOT_INITIALIZED`; do not
resume the Mac installation. tvOS remains NOT VALIDATED.

**Smallest next step**: synchronize Codex normally, then begin the separately
authorized BM-017F lifecycle work.

---

# Agent Handoff — BM-017E investigation complete; BM-023A-R1 synchronized

## BM-017E disposition

**Complete as a static investigation** with result
`BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`.

The exact public Red Light 2.6.8 package (SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`) contains
an internal `ensure_database_tables('settings_db')` helper and a fresh-settings
sync path. The helper is called from directory-listing routing, not a standalone
initializer API. The ordinary enabled-addon service performs broad
integrity/rebuild maintenance, syncs settings, bootstraps properties, and starts
multiple background workers. Its pause flag does not stop all workers, and its
disabled notification has no worker-join/quiescence acknowledgement.

Build Manager's current frozen-install flow enforces the add-on's requested
enabled state before its configuration runner. BM-022 restart resume has a
separate updater-policy transaction and finalizes software without rerunning
configuration; BM-020 stores no resource stage and its resume path does not
accept a further restart requirement. The present ordering cannot prove that
the owner remains disabled while the internal initializer and private apply
run, and that it is re-enabled only afterward while updater quarantine remains
active. No safe production lifecycle could be established from the current
architecture, so no production code or tests were added and no Red Light code
was executed. Full static findings and the exact next step are in
[`docs/BM017E_RESOURCE_LIFECYCLE_AUDIT.md`](../docs/BM017E_RESOURCE_LIFECYCLE_AUDIT.md).

No Family Room database, protected overlay values, Kodi device, or portable Mac
test profile was accessed. BM-023A remains blocked; do not start its Mac retry
from BM-017E. tvOS remains NOT VALIDATED.

## BM-023A-R1 integration

The reviewed R1 correction was integrated onto protected matrix as substantive
commit `9f05ea748d9c15131982d6eee2cb1e9aa41a3f8e`; neutral tracking is
`9abc4724fede1a2a936be37db501d1ab24c6d5f1`. Matrix focused validation passed
**288/288** and the full suite passed **1647/1647**. Compileall, JSON parsing,
and `git diff --check` passed. The Codex worker synchronized by normal merge
`7b8fe386447fd345c3029d7c8a13f0a96cf300ce`; only the authorized branches were
pushed. BM-023A-R1 remains complete as validation with result
`BLOCKED_RESOURCE_NOT_INITIALIZED`.

The requested Luna-6 / Max setting was not observable. Runtime label was GPT-6;
effort and usage telemetry were unavailable.

**Smallest next step**: review the BM-017E audit and design a single durable
BM-020/BM-022 stage for disabling Red Light through initialization and private
application, then re-enabling it before a future BM-023A retry.

---

# Agent Handoff — BM-023A-R1 validation complete

**Result**: `BLOCKED_RESOURCE_NOT_INITIALIZED`. BM-023A-R1 is complete as a
validation task. Do not begin another milestone.

## Integration and synchronization

Starting refs matched the supplied SHAs: `origin/matrix` at
`b82885ab01fdb3c2486fff0c3e42bf33262b110e` and `origin/agent/codex` at
`68f0da5613b4d5606ba2e334d4330fbaf6889d9f`. Only substantive BM-023B commit
`1d60ed39b36a1b25ac4c0d912712a55fe9a17e8f` was cherry-picked to matrix as
`5648c6781b4567d3b2f0931fc4ed838142ed22f1`; worker `.agent/*` was excluded.
Neutral matrix tracking is `d867b8029ae35d4187ecbcecb0f3f39016673517`. The
normal worker merge is `9b16e8a5a0585a11552233071f20073af151c0b4`. Matrix and
worker substantive endpoint trees matched after integration. Matrix was pushed
only to `origin/matrix`; synchronization pushed only to `origin/agent/codex`.

Integrated BM-023B validation: focused **581/581**, full suite **1643/1643**,
compileall, JSON parsing, and `git diff --check` passed.

## Isolated macOS retry

Only `/Applications/Kodi Build Manager Test.app` was launched, using exactly
`open "/Applications/Kodi Build Manager Test.app" --args -p`. Kodi 21.3/Omega
mapped `special://home`, `special://profile`, userdata, addon_data, databases,
and packages under the app's `Contents/Resources/Kodi/portable_data` tree.
Process/open-file checks found no use of the normal Kodi profile. The portable
profile held the fresh stock baseline; it was not reset or mutated. The exact
Red Light `settings.db` path under portable userdata was absent.

The retained capture matched source fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`:
37 graph nodes, 31 installed managed non-system nodes, one absent optional
`script.module.pysocks`, five system/runtime nodes, 67 required edges, and
three optional edges. All 30 retained exact artifacts passed byte/hash,
size, ID/version, and ZIP checks. YouTube `7.4.4+unofficial.2` remains exact
unavailable and no trusted repository is established; policy permits Skip or
Cancel, with a manual-install warning.

Protected overlay safe metadata validation passed for ID
`family-room-redlight-2.6.8`, expected fingerprint
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`,
source binding, and the public Red Light declaration. YouTube Skip was
compatible according to public ownership/resource declarations. No private
values were emitted or used for the compatibility decision.

Production inspection found `PrivateOverlayManager` constructs
`RedLightSettingsAdapter` with `lifecycle=ACTIVE` and `initialized=False`.
The adapter requires an existing database and a quiesced owner; it does not
create the database, and no supported deterministic initialization/quiesce
path is wired into the production flow. The clean destination lacks the
database. The hard gate therefore stopped with
`RESOURCE_NOT_INITIALIZED` before bootstrap, prompt, updater-policy change,
frozen install, reconciliation, or profile mutation. YouTube UI choice,
restart/resume, private application, final validation, updater restoration,
and idempotence remain untested.

BM-023A-R1 generalized correction: carry the immutable source software
fingerprint through frozen reconciliation and restart-safe request metadata;
validate overlay source binding against it; declare the public Red Light
resource and overlay ID in the Family Room example. No lifecycle bypass was
added. The correction and regression tests are committed on `agent/codex` as
`a2ad39a`. Focused production regressions **288/288**, full suite **1647/1647**,
compileall, JSON parsing, and diff check passed. Runtime label was GPT-6;
requested Luna-6/Max and Codex quota data were unavailable.

No Family Room profile/device or other Kodi device was accessed. tvOS remains
NOT VALIDATED. Secret values do not appear in the source changes or tracking;
the secret-blind scan result is recorded as `leak_detected=false` after the
final scan. The exact authorized test app remains at its pristine portable
baseline and is still available to the user.

**Smallest next step**: complete the separately authorized BM-017E source audit
and lifecycle work. Keep BM-023A-R1 blocked and do not resume the Mac
installation during BM-017E.

---

# Agent Handoff — BM-023B complete

**Result**: explicit exact-first frozen install recovery is implemented and
pushed as `1d60ed39b36a1b25ac4c0d912712a55fe9a17e8f` on `agent/codex`. BM-023A-H
tracking remains on protected `matrix` at `b82885ab01fdb3c2486fff0c3e42bf33262b110e`;
the normal worker synchronization merge is `08c0fdfc9601e770c88edab5100751c04b16166d`.

**Architecture**: exact artifacts retain strict digest/size/ZIP/ID/version
validation and install first. Explicit per-addon policy selects exact-only,
exact-first repository fallback, or exact-first fallback/skip. Fallback uses
only a named repository represented by an exact captured enabled repository
package. Unknown repository provenance never triggers guessing. Skip is
explicit, cannot satisfy required dependencies, is carried into ordinary
BuildManager reconciliation, and survives BM-020 restart transaction
serialization. Unattended choice returns `USER_RESOLUTION_REQUIRED`. Source,
install-plan, resolution, and resulting-software fingerprints are separate;
the source manifest is unchanged. Private-overlay compatibility uses only
public owner/resource declarations and reads no overlay values.

**Family Room classification**: captured desired state COMPLETE; exact frozen
coverage 30/31; YouTube `7.4.4+unofficial.2` exact artifact unavailable;
trusted repository identity unknown. Current actions are Skip or Cancel Build,
with a manual-install warning. If a trusted repository is established later,
the explicit Install Current Version choice is available under policy.

**Validation**: focused group 120/120; full suite 1643/1643; `compileall`, JSON
parsing, and `git diff --check` passed. Disposable temporary artifacts and
fake backends were used. Kodi was not launched; no real profile, device, or
private-overlay value was accessed. macOS BM-023A retry is architecturally
unblocked through explicit resolution but was not resumed; tvOS is not
validated.

**Smallest next step**: stop after BM-023B. Do not perform the separate macOS
install retry without a new task authorization.

---

# Agent Handoff — BM-023A-H exact historical artifact recovery

**Result**: `EXACT_YOUTUBE_7.4.4_UNOFFICIAL_2_NOT_RECOVERED`.
**Tracking synchronization**: sanitized worker completion commit `49791ea` is recorded on protected matrix at `b82885a` and is being merged normally into `agent/codex`; the worker H record remains intact.

The matrix integration is at `a51a84d`; Codex was synchronized by normal merge
`e08fe24`. Worker history and the single existing BM-023A-R usage entry were
preserved. BM-023A-H changed only sanitized tracking.

Public exact-version searches covered the upstream v7.4.4 release and install
guide, the upstream repository-generation workflow and `nexus-unofficial`
metadata, OSMC unofficial-testing package listings and repository indexes,
public GitHub search, Panicked references, and a Wayback CDX query. The official
release assets show bare `7.4.4` and `7.4.4+unofficial.1`; checked current OSMC
testing metadata shows betas and bare `7.4.4`; the current stable unofficial
package index was also checked and has no `.2` entry:
<https://ftp.fau.de/osmc/osmc/download/dev/anxdpanic/kodi/youtube/unofficial/zips/plugin.video.youtube/>.
No public exact `.2` metadata, package URL, provider checksum, archived entry,
forked package, or `.2`-specific source commit was located. The generic source-build process is known, but it
does not identify the `.2` build. No package ZIP was downloaded; the known bare
`7.4.4` candidate was not changed or substituted.

Production validation of the unchanged retained manifest/store pair fails
exactly for the installed managed YouTube `7.4.4+unofficial.2` artifact. Graph:
37 total nodes; 31 installed managed non-system; 1 absent optional; 5 system or
runtime; 30 artifact references, all present; 67 required edges; 3 optional
edges; 1 missing managed artifact. `pysocks` remains absent/optional/artifactless
and unscheduled. Canonical fingerprint is unchanged at
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`, the
recorded private-overlay target. No overlay value was read or changed.

Focused frozen tests: **25/25**. BM-023A-R matrix validation: **25/25** frozen,
**147/147** dependency, **1607/1607** full suite, clean diff check. Family Room,
all devices, Kodi, the portable profile, and private overlay remained untouched.

**Smallest next step**: await supervisor direction on archival recovery versus
an explicitly altered desired build or later authorized recapture. BM-023A
remains historically `BLOCKED_MISSING_FROZEN_ARTIFACTS`; do not resume install.

---

# Agent Handoff — BM-023A-R matrix integration and Codex synchronization

The protected matrix started at `5a3598f565ad5b0c0164215eeefdf39b54a1d682`.
Reviewed substantive worker commit `a8d4b71` was cherry-picked as matrix
`ff5c000`; neutral tracking was committed as `a51a84d` and pushed to
`origin/matrix`. Worker implementation and tracking history were preserved by a
normal merge. Only `.agent/AGENT_STATUS.json`, `.agent/CURRENT_TASK.md`, and
`.agent/HANDOFF.md` needed semantic conflict resolution; production changes
merged without conflict. The existing BM-023A-R usage row is preserved once.

Matrix validation: frozen capture/manifest/install **25/25**, dependency
regressions **147/147**, full suite **1607/1607**, and `git diff --check` clean.
No Kodi launch, portable-profile mutation, Family Room/device access, or private
overlay access occurred.

**Checkpoint next step**: the normal worker push at `e08fe24` and BM-023A-H
recovery result are recorded above. Await supervisor direction; do not resume
BM-023A installation.

---

## Existing worker handoff — synchronized Codex worker

## BM-023A-R — Frozen input completeness reconciliation

**Result**: `MANIFEST_SEMANTICS_CORRECTED_BUT_ARTIFACT_GAP_REMAINS`.
Implementation commit: `a8d4b71` on `agent/codex`. `origin/matrix` remains
`5a3598f565ad5b0c0164215eeefdf39b54a1d682`. No protected or other worker
branch was changed.

Capture and install validation now share these rules: every installed
non-system node needs an exact artifact even if its incoming dependency edge
is optional; an absent optional dependency is recorded as `missing` with
disabled desired state and no artifact and is omitted from install order; and
system nodes remain declarations without artifacts. The installer validates
these rules independently. Schema v1 does not imply exclusion/unmanaged state
for installed optional nodes.

The retained `script.module.pysocks` graph node is absent, disabled, and
optional, reached only from YouTube through an optional edge. It exists because
capture records traversed optional imports even when absent from installed
inventory. It requires no artifact and is no longer scheduled. The previous
installer rejected it under its blanket artifact rule before returning a
schedule.

YouTube is installed as `7.4.4+unofficial.2`, desired enabled, and is an
optional dependency of `plugin.video.umbrella`. With no explicit exclusion
model, it is managed frozen software. The manifest has no configuration
packages; the protected private overlay targets Red Light only. No captured
configuration dependency on YouTube was found. Excluding it changes the
captured enabled software state. The `repository_evidence` provenance has only
the `installed_origin` placeholder `recorded`; an exact provider ID is not
present in retained evidence.

Only the retained candidate directory
`/private/tmp/bm022v-familyroom.ygB0t5` and named protected Build Manager
artifact storage were searched. No exact `plugin.video.youtube`
`7.4.4+unofficial.2` artifact was found. The retained package
`packages/plugin.video.youtube.zip` validates as `7.4.4` (SHA-256
`d744e5ba2d2b50924a9fa5624f4d209c2be95b97ef1ad1682cafbed160fb428f`,
1,093,649 bytes); production validation rejects it for the installed version.
No import, version normalization/substitution, network lookup, or recapture
occurred.

Focused frozen tests passed **25/25**, full suite **1607/1607**, and
`git diff --check` passed. No Kodi launch, portable-profile mutation, or
Family Room access occurred. BM-023A remains historically complete as a
validation task with result `BLOCKED_MISSING_FROZEN_ARTIFACTS`.

### Smallest next step

Supervisor decides whether to authorize a separate exact historical-provider
recovery step or explicitly exclude YouTube from the managed frozen state.
Do not resume frozen installation or start another milestone before that
decision.

### BM-023A preflight details (historical)

BM-017D tracking is integrated on protected matrix at `5a3598f`; Codex is
synchronized by normal merge at `bcd0fe5`. BM-023A stopped before Kodi launch
or disposable-profile mutation because the exact retained Family Room frozen
manifest/artifact-store pair is incomplete despite its top-level complete
status: 37 graph nodes, 32 non-system nodes, but only 30 artifacts. The
required `plugin.video.youtube` `7.4.4+unofficial.2` node and
`script.module.pysocks` `not-installed` node are incomplete, and
`validate_frozen_manifest` rejected the candidate.

Read-only typed validation of the protected Red Light overlay passed; its
target fingerprint matches the frozen graph and its ten field identifiers
were present. Values were not displayed. No test app launch, wipe, install,
settings/add-on mutation, reconciliation, restart, or other Kodi action was
performed. The bundled disposable profile already contains Kodi data and was
left untouched. The exact frozen artifacts must be recovered from existing
retained capture outputs; do not recapture Family Room or substitute newer
packages. If unavailable, request supervisor direction. No BM-017E or other
milestone was started.

### Smallest next step

Recover and validate the exact two missing frozen artifact nodes from the
approved capture, without accessing Family Room; otherwise stop for direction.

## BM-017D — Real Family Room structured private-resource capture complete

BM-017D is complete on `agent/codex`. Matrix remains unchanged at `2374ee5`;
the real private overlay is stored only outside Git in protected local Build
Manager storage. No other worker branch was modified.

The explicitly authorized read-only Xcode `devicectl` receive targeted only
`AppleTV - Family Room (4)`, bundle `com.eengert.koditvosnew`, and
`Library/Caches/Kodi/userdata/addon_data/plugin.video.redlight/databases/settings.db`.
The names-only directory check found no `settings.db-wal` or `settings.db-shm`
sidecars. No unrelated cache sidecars were received.

The BM-017C adapter validated the Red Light 2.6.8 contract, exact
`settings(setting_id, setting_type, setting_default, setting_value)` text
schema, WAL mode, and SQLite integrity. All ten optional reviewed fields were
captured and verified: `mdblist.refresh`, `mdblist.token`, `mdblist.user`,
`pm.account_id`, `pm.token`, `tb.token`, `trakt.expires`, `trakt.refresh`,
`trakt.token`, and `trakt.user`. No required fields were missing. Ordinary,
generated, cache, and unrelated rows were not captured.

Overlay ID: `family-room-redlight-2.6.8`. Protected storage:
`/Users/eengert/Library/Application Support/Build Manager/addon_data/script.build.manager/private_overlays/family-room-redlight-2.6.8.json`.
Overlay fingerprint:
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`.
Frozen software fingerprint:
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.

The source remained read-only: no apply operation, Red Light/Kodi setting
write, database mutation, restart/stop, add-on operation, repository refresh,
Build Manager reconciliation, Backup Pro operation, or device installation
was performed. The temporary raw database and locally generated sidecars were
deleted and verified absent. The secret-blind worktree scan reported
`leak_detected=false`.

Validation passed focused tests **27/27** and **386/386**; no production/test
code changed, so the full suite was not rerun. `git diff --check` must pass
before the tracking commit.

Frozen software is **COMPLETE**, the private overlay is **COMPLETE**, captured
desired state is **COMPLETE**, and real-device frozen installation remains
**NOT VALIDATED**.

### Smallest next step

Supervisor review of the sanitized BM-017D capture result. Do not apply the
overlay to Family Room or any destination device, and do not start another
milestone.

## BM-017C — structured private-resource foundation integrated and synchronized

Codex is synchronized with protected `matrix` through `2374ee5` by a normal
merge; matrix remains neutral, the worker identity remains `codex`, and no
other worker branch was modified. BM-017C is complete and supervisor-approved
on matrix. Its clean matrix-side substantive commit is `dce8276`, reconstructed
from worker implementation commit `8ba7bdc`; worker tracking metadata was
excluded from that substantive integration.

BM-017C provides a generic structured-private-resource protocol, exact Red
Light schema/version declarations, a quiesced row-scoped WAL adapter,
protected-overlay coexistence, restart-safe metadata, fake SQLite fixtures, and
sanitized documentation. It did not retrieve the real Family Room `settings.db`,
capture private values, create the real overlay, write to Family Room, install
on a real device, or start BM-017D/retention/scheduling.

Validation on the integrated matrix tree: structured-resource **27/27**,
focused regression group **386/386**, full suite **1604/1604**, and
`git diff --check` passed.

### Smallest next step

Stop after synchronization. Any real Red Light private capture is a separate
BM-017D authorization and must not be inferred from this foundation.

## BM-017B — Private overlay capture blocked by opaque Red Light state

BM-017B performed the authorized narrow read-only Family Room inventory using
paired-device `devicectl` against the Kodi app-data container. Device listing,
names-only relevant-directory inspection, and specifically justified metadata
and source receives succeeded. No source-profile write, Kodi control, add-on
state change, restart, repository operation, database write, Backup Pro
operation, reconciliation, installation, or unrelated profile scrape occurred.

The installed Red Light `2.6.8` source exposes a custom settings layer and its
`databases/settings.db` table is the owner of the observed private provider
state. Secret-blind schema/presence/default comparison found non-default
private-state fields in the `mdblist`, `pm`, `tb`, and `trakt` categories,
including refresh/token/account/user/expiry field IDs. Red Light's Kodi
`settings.xml` exposes only informational/action entries, so these values
cannot be represented by BM-017A's typed Kodi-setting backend. The database
also mixes ordinary preferences and generated/runtime state; copying or
replacing the whole file is explicitly unsafe.

MyAccounts `2.1.2` source exposes provider-auth setting operations for several
providers, but its Family Room addon_data directory was empty and no separate
user-state file was identified. POV and Umbrella source also contain provider
integrations, but no duplicate owner was inferred from the file evidence.

Result: frozen software capture remains **COMPLETE** with software fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
Private overlay capture is **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**; no typed
declarations, required/optional overlay entries, overlay file, or overlay
fingerprint were created. Captured desired state is **INCOMPLETE** and
real-device frozen installation remains **NOT VALIDATED**.

The final targeted secret-blind leak scan returned `leak_detected=false` for
repository files. All raw received database/source/metadata evidence was
deleted from the disposable directory and its absence was verified. No real
private value appears in tracking, documentation, logs, results, or Git.

### Smallest next step

Design and review a dedicated structured private-resource boundary for Red
Light's mixed settings database, including field-level ownership and safe
lifecycle/application semantics. Do not add an arbitrary file copier, capture
real private state again, or begin destination installation without that
review.

## BM-017A — Private/auth overlay foundation complete

BM-017A is complete on `agent/codex`. The worker first synchronized current
`origin/matrix` by normal merge (`a1ceab1`); the protected matrix and other
worker branches were not modified.

The implementation adds explicit public `config.private_settings`
declarations and a version-1 local private overlay with typed values,
required/optional ownership, sensitivity classification, build/overlay
identity, canonical JSON fingerprinting, and duplicate/undeclared/type/
completeness validation. Storage is profile-local, atomically written, and
permission-restricted (`0700` directory / `0600` file where supported). It is
intentionally restrictive plaintext: there is no encryption-at-rest claim,
custom cryptography, cloud sync, or secret-bearing public artifact.

The existing BM-015 `ConfigurationManager` remains the sole typed settings
backend. Build Manager applies public settings first and validated private
settings second, with typed authoritative read-back. Private values are not
returned in results, errors, logs, manifests, packages, `.agent/*`, or
BM-020/BM-022 durable transactions. Only overlay ID, fingerprint, and
required flag cross restart/frozen-install boundaries. Required absence and
identity drift fail closed; optional absence is a safe no-op.

Tests passed: private-overlay **14/14**, combined BM-015/BM-020/BM-022
regressions **588/588**, full suite **1591/1591**, and `git diff --check`.
Disposable fixtures used temporary storage only. No real Family Room private
files, credentials, Kodi profile, Apple TV, or other device were accessed.
The software foundation is ready for a separately authorized capture/import
workflow; real private capture and real-device frozen installation were not
performed. BM-017A is complete, BM-017 remains scoped to future authorized
capture/application work, and no next milestone was started.

### Smallest next step

Supervisor review the BM-017A foundation and explicitly authorize any future
private-state capture/import task. Do not access the real Family Room profile
or begin another milestone from this handoff.

## BM-022V-R — Family Room exact-artifact blocker resolution complete

BM-022V-R is complete on `agent/codex`. The BM-022V checkpoint was published
first as `f5a4415` to `origin/agent/codex`. No BM-017 or other milestone was
started, and the Family Room remained read-only.

### Resolution

Kodi Omega source supports a package with one safe top-level folder whose
`addon.xml` declares the requested add-on ID, even when the folder name differs
from that ID. Kodi stages the extracted contents under the requested ID. The
previous Build Manager root-equality check was unnecessarily strict.

The generalized correction is limited to `resources/lib/artifacts.py` and the
shared staged extraction helper in `resources/lib/repository.py`. It accepts
one safe root and keeps exact `addon.xml` ID/version authority while preserving
rejection of multiple roots, traversal, symlinks, missing/malformed XML, ID
mismatch, and version mismatch. No package bytes are rewritten, and there is
no add-on-specific exception.

The exact official Kodi Omega Dropbox package was recovered and imported:

- ID/version: `script.module.dropbox` `10.3.1+matrix.1`
- SHA-256: `5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6`
- Size: 667,538 bytes
- Source: recorded official Kodi Omega mirror URL

The exact cached Robotocjksc ZIP now validates unchanged as
`resource.font.robotocjksc` `0.0.3`; its alternate safe root is normalized only
during staged extraction. A temporary proof confirmed the final target has
the original `addon.xml` and payload bytes.

### Final capture state

- Required frozen software capture: **COMPLETE**.
- Candidate manifest: 37 nodes; 67 required edges; 3 optional edges; zero
  required missing artifacts.
- Exact artifact-backed nodes: 30; captured artifact bytes: 194,254,227.
- Candidate fingerprint:
  `sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
- Optional YouTube remains incomplete because installed
  `7.4.4+unofficial.2` differs from cached `7.4.4`; it does not block required
  capture completion.
- BM-023A-R later established that optional incoming edges do not waive the
  artifact requirement for this installed, enabled node. The non-blocking
  classification above is preserved as historical BM-022V/R tracking and is
  superseded by the current completeness invariant.
- Ready-to-use configuration: **BLOCKED_BY_BM017 / INCOMPLETE**. Private/auth
  state was not captured.

Focused tests passed **331/331**; full suite passed **1577/1577**; and
`git diff --check` passed. No Family Room installation, update, enable/disable,
repository refresh, restart, settings write, database write, or reconciliation
was performed. Codex usage values remain unavailable.

### Smallest next step

Supervisor review the BM-022V-R correction and, separately, authorize any
future BM-017 private-state work. Do not install the candidate build or begin
another milestone from this handoff.

## BM-022V — Real Family Room frozen-capture validation complete (initial checkpoint)

BM-022V is complete on `agent/codex` as read-only evidence validation. No
production code or documentation was added; no source Kodi profile, database,
settings, package cache, or device state was mutated; and no next milestone
was started.

The authorized `Addons33.db` was received into temporary evidence storage and
parsed with a read-only SQLite connection. The requested `guisettings.xml`
could not be received because no file with that name exists at the authorized
path or elsewhere in the Kodi app-data Library; no alternate file was used.
The raw database was deleted after parsing. The candidate FrozenManifest v1
was generated only in disposable temporary storage with fingerprint
`sha256:8807efedc3814b3c460761b8dc44466ae4e6d6f5dbe099f1a3cfb0a1a192660b`.

Evidence summary:

- Graph: 37 observed nodes; 70 edges; 67 required and 3 optional.
- ArtifactStore: 28 exact validated artifacts, 28 unique identities,
  141,987,267 unique bytes, disposable only.
- Software capture: **INCOMPLETE**, blocked by two required exact artifacts:
  `script.module.dropbox` `10.3.1+matrix.1` and
  `resource.font.robotocjksc` `0.0.3`.
- The Robotocjksc cached ZIP is malformed (`resource.font.robotcjksc` top-level
  directory) and was not repaired, renamed, or repackaged.
- Optional YouTube artifact evidence is incomplete; optional metadata remains
  unresolved for `script.module.inputstreamhelper` and
  `script.module.pysocks`.
- The database showed captured add-ons enabled except
  `service.skinsettings.backup` (disabled reason `1`). No explicit broken
  state is represented in the inspected database schema, so none is claimed.
- `general.addonupdates` is **UNAVAILABLE** because the authorized settings
  file was absent.
- Ready-to-use configuration is **INCOMPLETE / BLOCKED_BY_BM017** because
  private/authenticated configuration was not captured.

Validation: relevant BM-021B artifact/frozen/frozen-install tests **30/30**;
`git diff --check` passed. Codex usage values are unavailable under the
project's documented rules. BM-017, retention, pinning, scheduling, freshness
UI, and real frozen installation were not started.

### Smallest next step

Supervisor review the BM-022V evidence report and separately authorize any
future exact-artifact recovery or BM-017 private-state work. Do not install the
candidate build or begin another milestone from this handoff.

## BM-022 — Frozen Build Installation and Transaction Lifecycle complete

BM-022 is complete on `agent/codex` in substantive commit `27f4215`. It is
not integrated to `matrix`; protected matrix remains `7ab49f1`. No worker
branch other than `agent/codex` was touched, and no next milestone was
started.

### What was done

- Added strict schema-v1 frozen-manifest loading and validation, including
  complete-capture status, exact artifact-store SHA-256/size/ZIP identity,
  system-dependency boundaries, edge validation, and deterministic
  topological installation order.
- Added a durable profile-local frozen transaction with atomic writes and
  locking; phases cover preparation, exact software installation,
  configuration, restart handoff, resume, validation, completion, and
  `needs_attention` recovery.
- Extended the existing updater guard so the original global policy is
  durably captured before mutation, `NEVER_CHECK` can be reasserted after a
  process restart, and the original policy can be restored from durable state.
- Reused the reviewed BM-011 staged-package boundary: validated ZIP content
  is atomically staged, registered with `UpdateLocalAddons`, and verified at
  the exact requested version; wrong-version replacement/downgrade is rejected.
- Added BM-020 startup precondition/resume integration and a read-only VFS
  fallback for installed dependency metadata when Kodi cannot open a freshly
  discovered disabled add-on handle.
- Added the BM-022 design document, a real ZIP/ArtifactStore disposable
  fixture, focused tests, and the `validate-frozen-install` command.

### Live and test evidence

The disposable BM-022 gate passed completely in `.kodi-test`: exact artifact
hash selection; repository → dependency → ordinary add-on ordering; durable
BM-020 handoff; restart-time updater reassertion before BM-020 startup;
existing Build Manager configuration; exact final state; original updater
policy restoration; clearing of BM-022 and BM-020 transactions; and real Kodi
profile immutability. The proof uses generated disposable runtime state only;
pristine first-ever provisioning of arbitrary add-ons is not claimed.

Focused regressions passed **639/639**. The full suite passed **1573/1573**.
`git diff --check` passed. Codex usage start/end/delta are `unavailable` per
the project rule; no telemetry was fabricated.

### What was not done

BM-022 has not been integrated to protected `matrix`. BM-017 remains deferred.
No retention, pinning, scheduling, freshness enforcement, garbage collection,
Apple TV action, real-profile mutation, or next milestone was started.

### Smallest next step

Supervisor review the BM-022 substantive commit and, if approved, perform the
normal clean integration onto protected `matrix` without copying worker
metadata wholesale.

## BM-021B capture core complete

BM-021B is complete and integrated on protected `matrix`; this worker is
synchronized, idle, and ready for BM-022. BM-021A is complete and its findings remain in
`docs/FROZEN_BUILD_CAPTURE.md`.

Implementation commit: `89525bd`. The implementation is limited to exact artifact capture, dependency-aware
inventory, manifest v1, deterministic incomplete results, and the independent
global updater guard. It does not install frozen builds or implement retention,
pinning, scheduling, freshness UI, garbage collection, BM-017, or device work.

Verified: Kodi 21.1 public add-on metadata exposes identity, version, type,
path, enabled/installed/broken state, and declared dependency edges, but not
provenance or per-addon update policy. The disposable profile's internal
database showed origin, package-cache, repository, and update-rule evidence;
the cache was bounded and did not contain every installed third-party package,
and some cached versions differed from installed versions. AF3 3.2.19's
closure was 21 nodes (18 third-party, 3 Kodi/system), with BM-020A dependency
health **18/18**. BM-011 repository/add-on validation passed **19/19**.

Decision: exact version recovery is feasible only from a verified immutable
artifact, an exact cache hit, or a still-available repository package. A ZIP
made from an installed directory is rejected as a reproducible artifact
fallback. The BM-021B manifest carries SHA-256 identity, exact ID/version,
dependency edges, enabled state, provenance confidence, and capture status;
system dependencies are constraints rather than frozen artifacts. Kodi's
global updater setting was proven through the supported Settings API; the
`NEVER_CHECK` value did not persist across restart, but deterministic guard
reassertion succeeded before capture mutation and no scheduled updater activity
appeared while guarded.

The representative disposable capture correctly returned `incomplete_artifact`
because no exact package-cache ZIP was available after reset; no installed
directory was zipped and no COMPLETE result was claimed. Evidence: BM-021B
focused tests **21/21**; combined focused tests **370/370**; full suite
**1557/1557**; updater-guard disposable proof passed. `NEVER_CHECK` did not
persist across restart, but deterministic reassertion succeeded before capture
mutation and original-policy restoration survived restart. BM-022 and BM-017
have not started. The real Kodi profile, Apple TV, devices, and other workers
remain untouched.

## BM-020C — post-restart resume orchestration complete

BM-020C is complete, supervisor-approved, and integrated on protected `matrix`.
The worker is synchronized to the integrated state; its substantive matrix
commits are `81ba44b` and `091cfe9`.

The implementation adds the read-only `BuildManager.preview()` seam,
`resources/lib/resume.py`, expected-state transaction transitions and bounded
status diagnostics, automatic `service.py` delegation for `READY_FOR_RESUME`,
focused resume tests, and the disposable `validate-build-manager-resume` gate.

The coordinator re-reads the persisted record, verifies a new session,
previews the desired state before mutation, requires an exact fingerprint
match, atomically claims `RESUMING`, and runs the normal BuildManager
reconciliation from the beginning. It clears only an unchanged `RESUMING`
record after success + matching final fingerprint + `NONE`. Failures,
fingerprint drift, repeated restart requirements, claim conflicts, and clear
conflicts fail closed into preserved `NEEDS_ATTENTION` state. Existing
`RESUMING` and `NEEDS_ATTENTION` records are not retried automatically.

Evidence: focused tests **465/465**, disposable BM-020C gate **8/8** with AF3
closure **18/18**, full suite **1536/1536**, and `git diff --check` clean. The
live gate proved automatic service-driven resume after a harness-only Kodi
restart, normal reconciliation with matching fingerprint and
`RestartRequirement.NONE`, automatic transaction clear, all 16 managed AF3
settings, no second handoff, and later `NO_TRANSACTION`. The unmanaged AF3
probe is covered by the BM-020A gate because this runtime normalizes that
schema entry across process restart. The real Kodi profile, Apple TV, and all
devices remained untouched.

BM-020C and BM-020 overall are complete. Current supported platforms still
require a manual full-Kodi restart; Build Manager does not automatically
relaunch Kodi. BM-017 and family-room distribution/source work remain
deferred. The next step is the BM-021A audit documented above.

## BM-020C1 — typed capability model and manual restart handoff complete

BM-020C1 is complete and integrated on protected `matrix`; its substantive
implementation commit is `bcaf2ca` (worker implementation `a6bf902`). The implementation adds
`resources/lib/restart_coordinator.py`, focused coverage in
`tests/test_restart_coordinator.py`, the disposable
`validate-build-manager-manual-restart` gate, and the BM-020B/C1 transaction
documentation.

The capability resolver maps macOS, Android/Shield, Fire OS, Apple TV/tvOS,
and unknown platforms to `MANUAL_APP_RESTART_REQUIRED`. A successful typed
`KODI_RESTART` result creates and read-backs `AWAITING_RESTART` with attempt
count `0`, returns `MANUAL_RESTART_REQUIRED`, and leaves Kodi running. Failed
reconciliation and `NONE` are fail-closed/no-transaction paths. A matching
same-session call reuses the durable record without a second reconciliation;
a changed session is `READY_FOR_RESUME` with count `0`, while BM-020C resume is
not implemented. Automatic capability selection fails closed because no
approved automatic adapter exists.

Evidence: focused BM-020C1/BM-020B/BM-020A/BM-019 tests **63/63**,
disposable manual gate **8/8**, full suite **1517/1517**, and
`git diff --check` clean. The gate used the real BM-020A fixture and
fingerprint, with only the restart requirement synthesized to exercise this
contract. It used only `.kodi-test`; the real Kodi profile, Apple TV, and all
devices remained untouched. The gate also proved AF3's disposable dependency
closure, same-process manual behavior, new-session classification, no resume,
and explicit clear.

Remaining BM-020C work is pre-resume fingerprint validation, `RESUMING`,
resumed reconciliation, success clear, restart-loop prevention, and recovery
after resume failure. Do not begin that work, BM-017, or device work as part
of this handoff. The smallest next step is supervisor direction on the later
resume contract.

## BM-020C audit stop — production restart primitive not established

BM-020C was started on Codex and stopped at its mandatory read-only restart
mechanism audit before the later BM-020C1 capability/manual-handoff work.
That audit remains historical context; the integrated BM-020C1 endpoint does
not claim that resume/re-entry is complete.

Kodi Omega's official built-in reference lists `RestartApp` as implemented
only under Windows and Linux. `Quit` is an application exit, not an automatic
relaunch. JSON-RPC provides quit/restart notifications, not a supported
add-on/Python operation that guarantees a new Kodi process. Kodi's Android
source contains internal restart-exit handling, but that does not establish a
public add-on/Python restart contract; no equivalent supported primitive was
established for macOS, Fire OS, Shield, or Apple TV/tvOS.

The required BM-020C lifecycle cannot safely claim a new session without a
genuine new Kodi process. Host shell/process management, GUI automation,
`System.Exec`, or a `Quit` plus assumed external relaunch would violate the
task boundary. The disposable harness may control Kodi externally, but that
cannot substitute for the missing production mechanism.

Recommended smallest next step: supervisor approval of an explicit platform
capability model and relaunch authority. Until then, do not add a restart
coordinator, alter BM-020A/B, or run the BM-020C process-level gate.

BM-020C and BM-020 overall remain incomplete. BM-017, the remaining resume
implementation, and all device/family-room work remain deferred. The real Kodi
profile and devices remain untouched.

## BM-020B complete and synchronized on Codex

BM-020B is complete and integrated on protected `matrix`; the substantive
commit is `f3ccf2a`. The implementation stores only a versioned safe
`ReconcileRequest`, desired fingerprint, typed restart requirement, originating
Kodi session UUID, phase, and bounded diagnostics under the Kodi profile.
Writes are validated and atomic; locking uses OS-backed `fcntl.flock` and fails
closed if unavailable. Kodi's global home-window property supplies a process
session identity, and `service.py` performs one startup classification pass.

The service fast path reports no transaction without reconciliation. Same-
session `AWAITING_RESTART` remains intact and ineligible for resume. A
different Kodi process is classified `READY_FOR_RESUME` while the transaction
remains durable for BM-020C. Corruption, unsupported versions, invalid fields,
and persistence/lock failures fail closed; clear is explicit only.

Disposable BM-020B validation passed 9/9 across an external Kodi stop/relaunch;
the service ran automatically in both processes, distinguished session IDs,
and never restarted Kodi or invoked `BuildManager.reconcile()`. Focused
transaction/session/service tests passed 32/32, the full suite passed
1504/1504, and `git diff --check` passed. Codex is synchronized/idle/ready
for BM-020C; BM-020C, BM-017, and family-room distribution/source work remain
outside scope.

## BM-017D — Real Family Room structured private-resource capture integrated

BM-017D is complete and its sanitized tracking is integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. Only tracking from
worker commit `d585fd8` was integrated. The protected overlay remains outside
Git in local Build Manager storage.

The matrix tracking commit is `5a3598f`; Codex was synchronized to that tip
with a normal merge before beginning BM-023A preflight.

The authorized read-only receive targeted the Family Room Kodi app-data
container and only Red Light `databases/settings.db`. Names-only inspection
found no matching settings database WAL/SHM sidecars. Exact Red Light 2.6.8
owner/version/schema, WAL mode, and integrity checks passed. The ten declared
optional provider/auth fields were captured and verified through BM-017C;
ordinary preferences, generated state, caches, and unrelated rows were not
captured. No values or overlay contents are recorded here.

Sanitized overlay identity: `family-room-redlight-2.6.8`, fingerprint
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`,
bound to frozen software fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
Frozen Family Room software, private overlay, and captured desired state are
**COMPLETE**. Real-device frozen installation remains **NOT VALIDATED**.
BM-017B retains its historical result **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**.

The source remained read-only; no apply or device installation occurred. The
temporary raw database and local SQLite sidecars were deleted and verified
absent. The secret-blind scan reported `leak_detected=false`. Focused tests
passed **27/27** and **386/386**; no production/test code changed.

### Smallest next step

Supervisor review. Do not start real-device installation without its separate
authorization.

## BM-017C integration complete

BM-017C is complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The clean
matrix-side substantive commit is `dce8276`, reconstructed from worker
implementation commit `8ba7bdc`; worker tracking metadata was excluded.

The structured private-resource foundation owns only explicitly declared typed
fields inside a vetted resource. Public manifests contain safe adapter,
version, schema, lifecycle, and field metadata; private values remain in the
protected overlay and are omitted from results, logs, and durable restart
metadata. The Red Light 2.6.8 adapter requires an existing exact-schema WAL
database and quiesced runtime, performs bounded row-scoped transaction writes
with per-field read-back, preserves unrelated rows, and requires explicit
restart/reload. It does not replace the mixed settings database or support
arbitrary paths, SQL, or wildcard ownership.

Integrated validation passed structured-resource **27/27**, focused
regressions **386/386**, full suite **1604/1604**, and `git diff --check`.
Tests use fake fixtures only. No real Family Room private database, credential,
Kodi profile, Apple TV, or other device was accessed or mutated.

BM-017B remains complete with result
**BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**; frozen Family Room software is
**COMPLETE**, captured desired state is **INCOMPLETE**, and real-device frozen
installation is **NOT VALIDATED**. BM-017D has not started.

### Smallest next step

Supervisor direction and separate authorization are required before any
BM-017D real private-state capture/import work. Do not access the real Family
Room private database or begin another milestone from this handoff.

## BM-017B integration complete

BM-017B is complete and supervisor-approved, with result
**BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**. The reviewed sanitized evidence is
`docs/BM017B_PRIVATE_CAPTURE.md`; it records that Red Light `2.6.8` stores
required private/auth state in a mixed `databases/settings.db` resource outside
the BM-017A typed Kodi-setting boundary. No private values were captured, no
raw database was retained, no arbitrary private-file copier was added, and the
Family Room source remained read-only.

Frozen Family Room software remains **COMPLETE**; captured desired state is
**INCOMPLETE**; real-device frozen installation is **NOT VALIDATED**. Matrix
remains neutral with `active_agent: none`. BM-017C is complete and integrated
above; BM-017D remains separately authorized and not started.

## BM-017A integration complete

BM-017A is complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The clean
matrix-side substantive commit is `321fee8`, reconstructed from worker
implementation commit `ebd4c61`. Worker tracking metadata was excluded.

The integrated foundation defines explicit public private-setting ownership,
typed version-1 overlay entries, build/overlay identity, canonical SHA-256
fingerprinting, duplicate/undeclared/type/completeness rejection, and
fail-closed missing-required behavior. Active storage is profile-local under
`addon_data/script.build.manager/private_overlays`, written atomically with
restrictive permissions where supported. It is protected local plaintext;
encryption at rest is not provided or claimed, and no custom cryptography is
used.

The existing BM-015 typed configuration backend remains the only settings
engine. Public configuration is applied first and validated private settings
second through the same typed write/read-back path. Private values are not
included in public artifacts, logs, results, `.agent/*`, or durable BM-020 /
BM-022 state. Durable state carries only overlay ID, fingerprint, and required
flag. Optional absence is a safe no-op; required absence and fingerprint drift
fail closed.

Integrated validation passed private-overlay **14/14**, BM-015/BM-020/BM-022
regressions **588/588**, full suite **1591/1591**, and `git diff --check`.
The real Family Room private profile, credentials, Kodi profile, Apple TV,
and other devices were not accessed or mutated. Required Family Room frozen
software capture remains complete, but ready-to-use configuration still
requires a separately authorized real private overlay capture/import, and
real-device frozen installation is not validated. BM-017B has not started.

### Smallest next step

Supervisor review and explicit authorization of any future BM-017B private
capture/import work. Do not access real private Family Room state or begin
another milestone from this handoff.

## BM-022V / BM-022V-R integration complete

BM-022V and BM-022V-R are complete, supervisor-approved, and integrated on
protected `matrix`. The clean matrix-side substantive commit is `31b8f9d`,
reconstructed from approved worker commit `784ea8f`; worker-only `.agent/*`
metadata was not copied. Matrix remains neutral with `active_agent: none`.

The read-only Family Room software capture is complete for required software:
37 nodes; 67 required and 3 optional edges; zero required missing artifacts;
30 exact artifact-backed nodes; 194,254,227 captured bytes; and fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
The exact Dropbox `10.3.1+matrix.1` artifact is present with SHA-256
`5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6` and
size 667,538 bytes. The cached Robotocjksc ZIP remains byte-for-byte
unchanged; its single safe alternate root is accepted by the generalized
validator and normalized during staged extraction. Optional YouTube remains
non-blockingly incomplete because the installed and cached versions differ.

Ready-to-use configuration is **INCOMPLETE / BLOCKED_BY_BM017** because
private/authenticated state was not captured. Real-device frozen installation
is **NOT YET VALIDATED**. The Family Room profile/evidence remained read-only;
no installation, update, enable/disable, repository refresh, restart,
settings/database write, or reconciliation occurred. BM-017 remains deferred
and no next milestone was started.

Validation from the integrated tree passed focused tests **331/331**, the
full suite **1577/1577**, and `git diff --check`. The smallest next step is
supervisor direction on the separate BM-017/private-state boundary; do not
install the candidate build or begin another milestone from this record.

## BM-022 integration complete

BM-022 is complete, supervisor-approved, and integrated on protected `matrix`.
The clean matrix-side substantive commit is `56ea26a`, a cherry-pick of
worker commit `27f4215`. The worker tracking commit and all worker `.agent/*`
metadata were excluded. Matrix remains neutral with `active_agent: none`.

The integrated lifecycle consumes only complete BM-021B manifests and exact
immutable artifacts, validates artifact identity and ZIP structure, installs
the required third-party graph deterministically, and excludes Kodi/system
dependencies from artifact installation. It reuses the reviewed BM-011
staged-package boundary and does not create a second unrestricted installer.
Wrong-version replacement, downgrade, broken state, missing metadata, and
orphaned target directories fail closed.

The durable frozen transaction captures build/manifest identity, phase,
original updater policy, guard ownership, restart linkage, and bounded status.
The updater guard is persisted before the first mutation, `NEVER_CHECK` is
verified before installation and reasserted before BM-020 startup/resume, and
release restores and verifies the original policy before clearing the frozen
transaction. Failures remain diagnosable in `NEEDS_ATTENTION`; there is no
silent completion or automatic software rollback. Explicit abandon is
available and does not claim rollback.

BM-022 composes with the existing Build Manager configuration and BM-020
restart/resume lifecycle. The new read-only dependency metadata fallback only
reads the known installed VFS path when Kodi cannot expose a freshly
discovered disabled add-on handle; it does not mutate Kodi state or fabricate
metadata.

Rerun evidence: focused regressions **639/639**, disposable
`validate-frozen-install` passed, full suite **1573/1573**, and
`git diff --check` passed. The proof used only `.kodi-test`; complete real
Family Room capture/install and real-device validation remain pending.

BM-020, BM-021A, BM-021B, and BM-022 are complete. BM-017 remains deferred.
No next milestone was started. The smallest next step is supervisor direction
on the remaining real Family Room/device validation boundary.

## BM-021B integration complete

BM-021B is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`. The reviewed
substantive endpoint was reconstructed as `2ee040c` (`feat(BM-021B): add
frozen artifact capture core`); worker-specific `.agent/*` files were not
copied.

The capture core provides a SHA-256 content-addressed, atomic write-once
artifact store with immutable sidecar metadata and read-back verification;
exact ZIP/package validation without execution or installed-directory
synthesis; typed installed inventory, transitive dependency closure, exact
system boundary, honest provenance, deterministic manifest/fingerprint, and
fail-closed incomplete states; plus exact store/cache/repository acquisition
ordering. The updater guard uses supported Settings JSON-RPC, captures and
restores the global policy explicitly, and must reassert/read-back
`NEVER_CHECK` before each resumed mutation because that setting does not
persist across restart.

The disposable gate proved 18/18 AF3 third-party closure entries healthy plus
the system boundary, exact installed versions and edges, and an honest
`incomplete_artifact` result when exact package-cache ZIPs were unavailable.
It did not claim a complete build, installed-directory provenance, frozen
installation, retention, pinning, scheduling, freshness enforcement, or
garbage collection. The updater proof passed read/set/read-back, restart
reassertion, no observed scheduled updater activity while guarded, explicit
restoration, and second-restart restoration. Focused validation passed
372/372 tests and the full suite passed 1557/1557; `git diff --check` is
clean. The live proof used only the disposable `.kodi-test` profile; no real
Kodi profile or Apple TV was accessed.

BM-020 and BM-021A/B are complete. BM-022 has not started, BM-017 remains
deferred, and family-room source/distribution concerns remain pending. The
smallest next step is supervisor direction on those separate concerns; no
next milestone was started.

## BM-021A integration complete

BM-021A is complete, supervisor-approved, and integrated on protected `matrix`.
The substantive audit commit is `b32369e`; no worker-specific metadata was
copied. `docs/FROZEN_BUILD_CAPTURE.md` records the exact artifact/provenance,
dependency-closure, updater-policy, immutable-store, and freshness conclusions
for future BM-021B/BM-022 work. It explicitly rejects installed-directory
zipping and undocumented per-addon auto-update assumptions.

BM-021B and BM-022 remain unstarted. BM-020 remains complete, BM-017 remains
deferred, and family-room source/distribution concerns are not independently
marked solved. Matrix remains neutral with `active_agent: none`.

## BM-020C integration complete

BM-020C is complete, supervisor-approved, and integrated on protected
`matrix`; matrix is neutral with `active_agent: none`. The matrix-side
substantive commits are `81ba44b` and `091cfe9`. Codex worker metadata was not
copied.

The guarded resume coordinator now re-reads the durable request after a new
Kodi session, previews the exact request and fingerprint before mutation,
claims `AWAITING_RESTART` atomically as `RESUMING`, runs normal
`BuildManager.reconcile()`, verifies the final fingerprint and `NONE`, and
clears the expected transaction atomically. Preview/fingerprint/reconcile
failures, claim/clear conflicts, exceptions, repeated restart requirements,
and later `RESUMING` or `NEEDS_ATTENTION` states fail closed. The service does
not restart Kodi or a host process; current supported platforms require a
manual full Kodi restart, after which resume is automatic.

Integrated validation passed focused tests **465/465**, disposable BM-020C
resume gate **8/8** with AF3 dependency closure **18/18**, full suite
**1536/1536**, and `git diff --check`. The gate proved service automatic
resume, authoritative read-back, fingerprint equality, `NONE`, no duplicate
handoff, later no transaction, and real Kodi profile immutability. AF3
generated first-run runtime state was bootstrapped only in `.kodi-test`; the
AF3 unmanaged probe is intentionally owned by BM-020A because AF3 normalizes
that entry across restart. Pristine first-ever AF3 provisioning is not claimed.

BM-020 overall is complete. BM-017 and family-room distribution/source work
remain deferred. The smallest next step is supervisor direction on those
separate concerns; no next milestone was started.

## BM-020C1 integration complete

BM-020C1 is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive commit is `bcaf2ca`. Codex worker metadata was not
copied.

The integration adds the typed capability resolver and manual restart
coordinator, with current and unknown platforms conservatively mapped to
`MANUAL_APP_RESTART_REQUIRED`. Successful `KODI_RESTART` handoff preparation
persists and read-backs `AWAITING_RESTART` with attempt count `0`, never
restarts or quits Kodi, and returns structured manual guidance. Failed runs
create no transaction, `NONE` completes without one, same-session requests do
not re-run reconciliation, and a new session with count `0` is ready for the
later resume phase. No automatic adapter or resumed reconciliation is
claimed.

Matrix validation passed focused tests **63/63**, disposable manual gate
**8/8** with AF3 closure **18/18**, full suite **1517/1517**, and
`git diff --check`. The gate used only `.kodi-test`; the real Kodi profile,
Apple TV, and all devices remained untouched.

BM-020C resume work remains incomplete: fingerprint revalidation, `RESUMING`,
resumed reconciliation, success clear, loop prevention, and failure/recovery
semantics. Do not begin that work, BM-017, or family-room distribution/source
work as part of this integration record.

## BM-020B integration complete

BM-020B is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive integration commit is `f3ccf2a`. Worker-specific
Codex metadata was not copied.

The durable foundation is profile-local and schema-versioned. It records only
the safe request, desired fingerprint, restart requirement, originating Kodi
session UUID, and transaction phase. Writes are staged in the same directory,
flushed and fsynced, atomically replaced, read back, and rejected if corrupt
or unsupported. An explicit clear removes the record safely. A profile-local
sidecar uses nonblocking `fcntl.flock`; lock ownership is released by the OS
when the process exits. The current Kodi session UUID is held in the home
window property `script.build.manager.kodi_session_id`.

`service.py` is a thin `xbmc.service` startup entrypoint. It classifies the
record and publishes the bounded result without restarting Kodi, reconciling,
resuming, or claiming a transaction. BM-020C owns actual resume/re-entry
execution.

The integrated disposable gate passed **9/9**: service fast path, session
identity, production preparation without restart, same-session protection,
external process boundary, automatic ready-for-resume classification, clear,
returned fast path, and real-profile immutability. Transaction tests passed
**32/32**, the full suite passed **1504/1504**, and `git diff --check` passed.
The first gate invocation observed only a startup-readiness race and was not
used as evidence of a code failure; the unchanged retry passed all 9 checks.
The real Kodi profile, Apple TV, and all devices remained untouched.

BM-020C and BM-017 remain unstarted. No next milestone was started. The
smallest next step is supervisor direction on BM-020C's resume/re-entry
policy; no worker handoff is implied by this matrix record.

## Prior integrated state

## BM-020A integration complete

BM-020A is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive commits are `eeafc1c`, `0ed2c35`, `821e69e`,
`0fb0bd5`, and `1ad0fdb`. Worker-specific Codex metadata was not copied.

The callable contract now available to BM-020B is
`BuildManager.reconcile(ReconcileRequest) -> ReconcileResult`. It owns the
load/inspect/resolve/preflight/plan/ordered execution/post-validation flow,
returns the safe request, deterministic desired fingerprint, ordered action
results, structured failure, validation report, and aggregated BM-019
`RestartReport`. It does not restart Kodi, persist transactions, resume after
restart, lock, or handle restart loops.

The integrated disposable `validate-build-manager` gate passed using the
self-contained AF3 fixture and production `af3-common` package: 18/18 AF3
closure entries healthy, `SET_SKIN` → `SkinActivator`, `CONFIGURE` →
`ConfigurationManager`, all 16 settings read back, `files=[]`, and
`RestartRequirement.NONE`. The second identical request retained the same
fingerprint and made no mutations. Managed `Navigation.OnBack` drift was
repaired; unmanaged `TMDbHelper.Corner.Radius` was preserved; invalid selector
failed closed before mutation. The `kodi.resource` system-dependency fix was
minimal and regression-tested.

Codex worker synchronization completed by normal merge from protected matrix;
the worker remains idle/ready for BM-020C and the external active-worker
pointer remains `build-manager -> codex`.

Focused integrated validation passed 1458/1458; full suite passed 1472/1472;
`git diff --check` passed. The family-room production source/distribution gap
remains a separate pending concern and is not claimed by BM-020A. The real
Kodi profile, Apple TV, and all devices remained untouched. BM-020B/C and
BM-017 were not started.

- Normal composition reached manifest/profile resolution, production package
  resolution, planner, `SET_SKIN` through BM-018A, `CONFIGURE` through
  ConfigurationManager, and post-validation through BM-014.
- The real `af3-common` descriptor applied and read back all 16 typed settings;
  its effective file target list was empty. First pass required no restart.
- Exact second request kept the same fingerprint and made zero mutations.
- A deliberate managed `Navigation.OnBack` drift was repaired, while the
  unmanaged `TMDbHelper.Corner.Radius` probe remained unchanged.
- Invalid device selector failed closed during resolve without state change.
- The disposable AF3 closure was healthy; `kodi.resource` is now correctly
  treated as a Kodi system dependency, with focused regression coverage.

Focused tests passed 1391/1391 and the full suite passed 1472/1472.
`git diff --check` passed. BM-020B/C and BM-017 remain unstarted. The real
Kodi profile, Apple TV, and all devices remained untouched. Family-room
distribution/source work remains separate and was not started.

## BM-023A macOS retry — 2026-09-24

**Status:** `BLOCKED_BM023A_ADAPTER_NAMESPACE_PACKAGE_PATH_TYPEERROR` after one authorized live attempt and offline diagnosis.

**What was done:** Confirmed the dedicated Kodi 21.3 app remained in portable
mode and was the only Kodi process. Installed Build Manager 0.1.0 and the
temporary BM-023A invocation adapter through Kodi's built-in ZIP installer in
the test app's portable profile. Invoked the adapter once. It returned
`ok=false`, `error_type=TypeError` without an outcome, code, transaction, or
lifecycle stage. Offline reproduction located it at the temporary adapter's
`Path(resources.__file__)` source check: `resources` is a namespace package
and `__file__` is `None`. The filtered target log has no traceback. The
updater policy read-back remained 0, equal to the pre-run value.

**What was not done:** No frozen transaction or imported overlay file appeared
in the portable profile, and none of the 32 non-system manifest add-ons had an
installed add-on directory. Red Light resource initialization, private apply,
activation release, restart/resume, and final validation have no positive
evidence. No product code change or test suite run. No normal Kodi profile or
real device was accessed. The exact test-app process was subsequently stopped
and verified exited; no second attempt occurred.

**Smallest next step:** Supervisor review of the adapter guard correction
recommendation. The adapter can validate `resources.lib.__file__` or
`resources.__path__`; any live retry requires separate supervisor direction.

**Human input:** Supervisor direction before changing the adapter or resuming
macOS BM-023A. tvOS remains unvalidated.

## BM-023B — protected matrix integration and Codex synchronization

The reviewed substantive implementation commit `1d60ed3` was cherry-picked to
protected `matrix` as `5648c678`; sanitized neutral tracking is `d867b80`. The
Codex worker branch was synchronized through this normal merge, preserving its
BM-023A/B history and Codex identity. Worker `.agent/*` files were not copied
onto matrix. The worker BM-023B usage row and neutral matrix integration row
are each preserved exactly once.

Matrix validation passed focused relevant modules **581/581**, full suite
**1643/1643**, `compileall`, schema/example JSON parsing, and
`git diff --check`. The synchronized substantive endpoint matches matrix when
`.agent/**` is excluded. No Kodi app, Family Room, device, portable profile,
or private-overlay value was accessed during integration.

BM-023A-R1 is separately authorized and architecturally unblocked; it had not
started at this synchronization checkpoint. The next action is the isolated
macOS destination preflight using only `/Applications/Kodi Build Manager Test.app`.
tvOS remains NOT VALIDATED.

## macOS BM-023A offline skin activation diagnosis — 2026-09-24

**Classification:** `BLOCKED_BM023A_SKIN_ACTIVATION_FAILURE_REASON_UNPERSISTED`.

The worker was clean on `agent/codex` before this task. Only the dedicated
portable test-app profile and repository files were inspected. No Kodi launch,
adapter invocation, retry, recovery, production edit, or test run occurred. No
normal Kodi profile, real device, or private overlay values were accessed; no
product commit was made.

The preserved adapter 0.0.2 result is `ok=true`, `outcome=needs_attention`,
`code=FROZEN_CONFIGURATION_ACTION_FAILED`. The durable transaction is still
present at phase `needs_attention`; its safe status detail is
`outcome=failed; phase=execute; failure=ACTION_FAILED; action=SET_SKIN;
addon=skin.arctic.fuse.3`. The transaction is at configuration execution,
`lifecycle_stage=none`, restart count 0, with no activation-hold IDs and
`activation_hold_released=true`. The updater guard is required: current policy
2 (`NEVER_CHECK`), original policy 0 (`AUTOMATIC`).

`skin.arctic.fuse.3` is installed, enabled, unbroken at 3.3.1. The portable
`lookandfeel.skin` value remains `skin.estuary`. Red Light 2.6.8 is installed,
enabled, and unbroken. YouTube is recorded as skipped and absent, consistent
with policy. The adapter imported the overlay, but the failed `SET_SKIN` action
preceded any `CONFIGURE` action; private application, structured-resource
initialization, private verification, activation release, and final validation
were not reached. The durable `private_overlay_required=false` was not updated
with result overlay metadata because `_handle_configuration_result` raises on
failure before its later persistence transition; do not treat it as evidence
that the overlay was not imported or required.

The planner orders `SET_SKIN` before `CONFIGURE`, and `BuildManager.reconcile`
returns on the first failed action. Therefore no public/private CONFIGURE
action failed here; the failure is specifically skin activation through
`BuildManager._dispatch_action` and `SkinActivator.activate`, wrapped by
`FrozenInstallCoordinator._handle_configuration_result` as
`FROZEN_CONFIGURATION_ACTION_FAILED`. The resulting `SkinResult` has status
`FAILED`, but neither its message nor a typed failure code is persisted. The
final portable setting shows the target skin was not persisted. The exact
inner branch (dialog timeout, JSON-RPC error, read-back mismatch, or another
skin activation failure) cannot be determined from the preserved result.

In the current portable Kodi log, two warnings at approximately 10:20:12.589
and 10:20:13.350 report a failed `Timers.xml` load while the target skin is
referenced; the installed target skin directory contains no `Timers.xml`. A
generic error follows at approximately 10:20:13.714. No safe log marker
identifies the SkinResult failure branch, and no JSON-RPC error, Python
traceback/TypeError, database error, private verification, or activation
release marker was found in the correlated interval. The XML warnings are a
correlated clue, not proven root cause.

No restart was requested because reconciliation stopped during action
execution before RestartCoordinator could handle a successful reconciliation.
The zero restart count is expected at this failure point. The no-hold state
also means the BM-022 private-verification/release stages did not apply.

**Smallest correction recommendation:** add an allowlisted static failure code
to each `SkinResult` failure path and preserve that code in frozen diagnostics;
do not persist the raw result/exception message. Review whether the missing
`Timers.xml` warning is causal before considering any skin package correction.
Do not clear the `needs_attention` transaction. This task made no correction.

- BM-017F: `COMPLETE`.
- macOS BM-023A: `BLOCKED_BM023A_SKIN_ACTIVATION_FAILURE_REASON_UNPERSISTED`.
- tvOS: `NOT VALIDATED`.

**Human input:** supervisor review of this classification and correction
recommendation before any production change or live retry.

## BM-023A offline skin failure instrumentation — 2026-09-24

**Classification:** `BLOCKED_PENDING_DIAGNOSTIC_RETRY`. This is an
observability correction only; the AF3 activation failure itself is not fixed.

Added `SkinFailureCode` and optional `SkinResult.failure_code`. Successful and
already-active results retain `None`; existing positional `SkinResult`
construction remains compatible. Failure codes are static enum values and
never incorporate Kodi text, values, paths, or exceptions. The activation
algorithm retains its previous command order, Home preparation, `SendClick(11)`
path, timeout durations, post-confirmation persisted/active read-back order,
stability check, and implicit keep/revert behavior. The code has no explicit
rollback/revert operation.

Audited failure paths and assignments:

- Invalid add-on ID: existing `SkinValidationError` is raised before backend
  access; no `SkinResult` or mutation.
- Initial active-skin read error → `INITIAL_SKIN_STATE_READ_FAILED`; already
  active remains successful with no failure code.
- Target state read error → `TARGET_SKIN_STATE_READ_FAILED`; absent and
  disabled targets → `TARGET_SKIN_NOT_AVAILABLE` and `TARGET_SKIN_DISABLED`.
- Pre-existing confirmation dialog → `PREEXISTING_CONFIRMATION_DIALOG`;
  failure reading the initial dialog state →
  `CONFIRMATION_STATE_READ_FAILED`.
- Home/preparation failure → `SKIN_CHANGE_PREPARATION_FAILED`; failure to set
  the skin → `SET_SKIN_COMMAND_FAILED`, unless a typed Kodi JSON-RPC failure
  gives `JSONRPC_FAILURE`.
- Confirmation polling expires without a state-read error →
  `CONFIRMATION_NOT_OBSERVED`; terminal active/dialog read errors are separately
  `ACTIVE_SKIN_READ_FAILED` or `CONFIRMATION_STATE_READ_FAILED`.
- Yes/click failure → `CONFIRMATION_ACTION_FAILED`; close polling expires with
  the dialog still visible → `CONFIRMATION_NOT_CLOSED`; terminal visibility
  read error → `CONFIRMATION_STATE_READ_FAILED`.
- Persisted setting read failure → `PERSISTED_SKIN_READ_FAILED`; a completed
  read-back with a different skin → `TARGET_SKIN_NOT_PERSISTED`.
- Loaded-skin read failure → `ACTIVE_SKIN_READ_FAILED`; completed read-back
  with a different skin → `TARGET_SKIN_NOT_ACTIVE`.
- Stability polling timeout → `SKIN_DID_NOT_REMAIN_STABLE`; terminal setting or
  active-skin read error is identified as `PERSISTED_SKIN_READ_FAILED` or
  `ACTIVE_SKIN_READ_FAILED`. The final fallback is
  `UNKNOWN_SAFE_FAILURE`.

Frozen `needs_attention` diagnostics retain the existing top-level
`FROZEN_CONFIGURATION_ACTION_FAILED` and add `skin_failure_code=<allowlisted
enum>` only for failed `SET_SKIN`. Existing `action=SET_SKIN` and
`addon=skin.arctic.fuse.3` identify the action/owner. `SkinResult.message` is
not copied. Regression coverage proved fake exception text, a private-looking
path, and secret text are absent from the durable transaction; existing
CONFIGURE diagnostics remain unchanged.

**Read-only AF3 package audit:** retained package metadata identifies
`skin.arctic.fuse.3` 3.3.1, SHA-256
`4d10cb10b9358a12a79519a813e82864b513370c627b85406e2840357b07729c`; ZIP
integrity passed. Neither that ZIP nor the portable installed 3.3.1 directory
contains exact `Timers.xml`, and a scan of package XML found no exact
`Timers.xml` reference in `addon.xml` or other AF3 XML. AF3 references to
`MyPVRTimers.xml` point to that distinct file, which is present. The installed
directory and retained ZIP have the same 3,700-file path set but three content
mismatches: `1080i/Includes_Home.xml`, `1080i/Includes_Labels.xml`, and
`1080i/Includes_SkinSettings.xml` (HomeSwitcher changes). Thus version matches,
but the retained ZIP is not byte-identical to the installed directory. The
warning is **correlated warning only**, not a demonstrated packaging defect or
cause of SET_SKIN failure. No source evidence established Kodi's precise
caller for the `Timers.xml` lookup.

The current portable failed transaction was not read for additional values,
modified, cleared, or recovered during this instrumentation task. No Kodi
application was launched; no adapter was invoked; no normal Kodi profile, real
device, or private overlay value was accessed. No skin behavior, AF3 package,
planner order, frozen lifecycle, transaction, or current portable policy was
changed.

Validation: skin activation tests **44/44**; skin frozen-diagnostic integration
and existing CONFIGURE diagnostics **9/9**; full suite **1810/1810**;
`compileall`, `.agent/AGENT_STATUS.json` and schema JSON parsing, and
`git diff --check` passed. Codex usage figures were unavailable; recorded as
unavailable rather than estimated. Requested Luna-6/High was not independently
observable in the runtime label.

**Implementation/test commit:**
`20bb8f09c8804c4bb1ea1405f1a1b2c7845974b9`. The sanitized tracking commit is
separate. Matrix remains
`66b0fd8a123ef778b23ba42703937b07eefc4e6f`; this work is only on
`agent/codex`.

- BM-017F: `COMPLETE`.
- macOS BM-023A: `BLOCKED_PENDING_DIAGNOSTIC_RETRY`.
- tvOS: `NOT VALIDATED`.

**Next step:** supervisor reviews this safe diagnostic change and authorizes a
separate live retry/recovery plan. Do not launch, rerun, or clear the current
transaction without that authorization.
