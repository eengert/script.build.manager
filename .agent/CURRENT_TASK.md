# Current Task

## BM-023A recovery adapter dispatch correction — 2026-09-24

**Status:** `OFFLINE_CORRECTION_COMPLETE; BLOCKED_PENDING_CORRECTED_RECOVERY_ADAPTER_INSTALL`.

Offline reconstruction of the prior request (`Addons.ExecuteAddon`, add-on
`script.build.manager.bm023a_driver`, `params` string `"recover"`) established
the dispatch bug: Kodi supplies the script path as `sys.argv[0]` and the first
add-on argument as `sys.argv[1]`, but adapter 0.0.3 sliced `sys.argv[2:]`.
That discarded `recover`, leaving an empty list that the old parser treated as
the mutating install default. The adapter now reads `sys.argv[1:]` and requires
exactly one explicit allowlisted `install` or `recover` token (also accepting
the fixed `?mode=...` form). Missing/invalid input fails before dispatch; every
result identifies `install`, `recover`, or the safe preselection value
`unselected`. Temporary adapter version is 0.0.4; product version unchanged.

Recovery still invokes only
`FrozenInstallCoordinator.abandon(acknowledge_restore_failure=False)` after
its existing preconditions. No production Build Manager code changed. Adapter
tests **35/35**; BM harness **124/124**; full offline suite **1843/1843**;
compileall, tracked JSON parsing, generated ZIP integrity/source checks, and
`git diff --check` passed. No Kodi was launched, corrected adapter installed or
invoked, transaction recovered, BM-023A retried, updater changed, real profile
or device accessed, or private value read.

- BM-017F: `COMPLETE`.
- macOS BM-023A: `BLOCKED_PENDING_CORRECTED_RECOVERY_ADAPTER_INSTALL`.
- tvOS: `NOT VALIDATED`.

**Smallest next step:** Eric may install corrected adapter 0.0.4 manually. Do
not invoke it or retry BM-023A without separate explicit authorization.

---

## Historical BM-023A offline skin activation diagnosis (pre-instrumentation)

**Status:** `BLOCKED_BM023A_SKIN_ACTIVATION_FAILURE_REASON_UNPERSISTED`.

The preserved portable result identifies the first failed reconciliation action
as `SET_SKIN` for `skin.arctic.fuse.3`. The portable profile's persisted
`lookandfeel.skin` remains `skin.estuary`. This is a skin activation failure;
no `CONFIGURE` action ran because reconciliation stops at the first failed
action.

The durable diagnostic does not include a nested skin failure code or message.
The portable Kodi log has two warnings about loading the target skin's
`Timers.xml`, which is absent from the installed skin directory, but the
preserved evidence does not prove those warnings caused the activation
failure. This is classified as a production diagnostic gap; do not infer or
apply a skin-package fix from the warnings alone.

The transaction remains `needs_attention`. No Kodi launch, adapter invocation,
retry, recovery, production edit, or test run occurred. Only portable test-app
evidence and repository sources were inspected. No normal profile, real device,
or private overlay values were accessed. No product commit was made.

- BM-017F: `COMPLETE`.
- macOS BM-023A: `BLOCKED_BM023A_SKIN_ACTIVATION_FAILURE_REASON_UNPERSISTED`.
- tvOS: `NOT VALIDATED`.

**Smallest recommendation:** add and persist an allowlisted static failure code
to `SkinResult` and pass it through frozen-configuration diagnostics without
storing raw exception or setting text. Keep the current transaction until a
reviewed correction and supervisor direction.

**Next step:** supervisor review of the diagnostic-gap classification and
correction recommendation. No live retry is authorized by this offline task.

---

## Historical prior task record (preserved; superseded for current status)

## BM-017F — Deferred Activation & Structured-Resource Lifecycle

**Status**: `COMPLETE` on `agent/codex`, synchronized with protected matrix
at `66b0fd8a123ef778b23ba42703937b07eefc4e6f`. The reviewed substantive
endpoint diff was reconstructed as matrix commit
`4dfd97e180d14976adec8540d5c0c93893519249`; worker history was not rewritten
and `.agent/**` history was not integrated as product work. BM-017F includes
the deferred-activation lifecycle, staged restart and dependency hold safety,
verified installed-source/import handling, Red Light resource initialization,
compatibility-alias ownership, safe diagnostics, the disposable validation
harness, and associated tests.

The supervisor-provided final disposable validation passed all eight steps
and all twenty checks. Red Light structured private-resource lifecycle is
`LIVE-VALIDATED`. The final live run stayed in the disposable `.kodi-test`
scope. This integration did not launch Kodi or access a normal profile, a
real device, or private overlay values.

- BM-017F: `COMPLETE`.
- macOS BM-023A: bootstrap blocker corrected offline; `READY_TO_RETRY`. No Kodi retry was run and BM-023A is not passed.
- tvOS: `NOT VALIDATED`.

On matrix, focused lifecycle/resource/import/harness modules passed **499/499**;
the full suite passed **1782/1782**; `compileall`, parsing of all **7 tracked
JSON files** including the schema, and `git diff --check` passed. A test-only
import-spy ordering correction ensures `unittest.mock` target resolution is
not counted as an add-on import under Python 3.14.

The authorized macOS BM-023A attempt and offline diagnosis are recorded below.
The dedicated test-app process was stopped. This task does not relaunch it or
resume the live retry; supervisor authorization remains required.

## BM-023A adapter bootstrap correction — 2026-09-24

The prior adapter source existed only as a one-off under `/private/tmp`; a
read-only search of this repository, sibling worktrees, and shared tools found
no tracked generator or staging source. The one-off kept portable-profile
paths and the private-overlay source path out of the public repository. To
make future retries reproducible without committing those machine-specific
values, added the authoritative project generator `tools/build_bm023a_adapter.py`,
templates under `tools/bm023a_adapter/`, and independently tested support code
at `tools/bm023a_adapter_support.py`. The generator can carry forward only six
literal configuration fields from the old adapter or accept them explicitly.
The adapter ZIP layout mirrors the prior Kodi built-in ZIP-installer format.

Adapter version is **0.0.2** (up from 0.0.1) so Kodi's add-on updater/install
path sees a newer package. The adapter now imports concrete `resources.lib`,
resolves its `__file__`, and verifies the canonical package path is exactly
inside the expected installed `script.build.manager/resources/lib` tree. It
also proves the canonical add-on root is a direct child of the installed
add-ons directory. Escapes, symlinks to outside sources, wrong roots, and
host/project module collisions fail closed. `resources.__file__` is never
dereferenced.

Failures serialize only allowlisted `adapter_stage`, `failing_callable`,
`failure_category`, and `error_type` labels; raw exception text, tracebacks,
paths, and private values are omitted. Successful transaction diagnostics no
longer include private overlay ID or fingerprint. Offline regressions passed
16/16, including the old namespace-package TypeError reproduction and the
corrected fixture, API signature binding, provenance/path escapes, diagnostic
redaction, and generated ZIP/version checks. The corrected 0.0.2 ZIP was
regenerated under `/private/tmp` from the tracked generator and previous
allowlisted adapter configuration. No Kodi executable, portable profile,
normal profile, device, or private-overlay file was accessed; no live retry
was run. macOS BM-023A is `READY_TO_RETRY`, not passed. BM-017F remains
`COMPLETE`; tvOS remains `NOT VALIDATED`.

## macOS BM-023A retry — 2026-09-24

The dedicated Kodi 21.3 test application was confirmed in portable mode and
launched with the required `-p` argument. Its only Kodi process remained the
test-app binary. The user confirmed `addons.unknownsources=true` for this test
profile. Kodi's built-in ZIP installer installed the repository Build Manager
package (0.1.0) and a temporary invocation adapter (0.0.1) into the app's
portable add-ons directory. The adapter was invoked once.

The adapter result is `ok=false`, `error_type=TypeError`; it saved no outcome,
code, transaction, or lifecycle stage, and the filtered test-app log contains
no traceback. No frozen transaction file or imported overlay file was present
in the portable profile. None of the 32 non-system add-ons in the retained
manifest had an installed add-on directory. The updater policy read-back was
0, matching its pre-run value. The live result did not record its stage; the
offline diagnosis below identifies the adapter failure before Build Manager
modules were imported. Activation holds, artifact installs, Red Light resource
initialization/private apply, restart/resume, and final validation have no
positive evidence.

No product code changed and no test suite was run. No normal Kodi profile or
real device was accessed. The exact test-app process was later stopped with a
graceful termination signal and verified exited. No second attempt occurred.

### Offline TypeError diagnosis — 2026-09-24

**Classification:** `BLOCKED_BM023A_ADAPTER_NAMESPACE_PACKAGE_PATH_TYPEERROR`.

The temporary adapter entrypoint is `default.py` `main()`. After adding the
installed Build Manager directory to `sys.path`, it imports the top-level
`resources` directory and evaluates `Path(resources.__file__).resolve()` at
line 86. The installed add-on has no `resources/__init__.py`, so Python loads
`resources` as a namespace package with `__file__ is None`; constructing
`Path(None)` raises `TypeError: expected str, bytes or os.PathLike object,
not NoneType`. The offline reproduction used the installed portable add-on
source under Python 3.10.9 and Kodi API stubs; it reproduced this exact
expression failure without reading the private overlay input or writing to
the portable profile.

The adapter stops before importing `resources.lib`, `BuildManager`, or
`FrozenInstallCoordinator`. It therefore constructs no manifest/config
request, imports no private overlay, calls no BM production function, and
does not reach `FrozenInstallStore.create()` (`resources/lib/frozen_install.py`
line 1874). The later `ReconcileRequest` construction at line 2109 is also
unreached. This is adapter stage A: before the Build Manager production
entrypoint. The coordinator constructor and `install()` arguments do bind to
the current worker API when checked offline; there is no signature mismatch.

The installed Build Manager is version 0.1.0 and its 45 runtime files match
the current worker byte-for-byte. The installed adapter is version 0.0.1 and
matches its temporary source byte-for-byte. No source skew was found. The
portable result still contains only `ok=false` and `error_type=TypeError`;
the filtered portable log has no traceback. No transaction JSON or add-on
installation appeared. Zero-byte transaction lock files predate the adapter
result and are not transaction records.

The smallest correction is to make the temporary adapter verify an actual
regular package module such as `resources.lib.__file__`, or verify the
namespace package's `resources.__path__`; do not dereference
`resources.__file__`. For a future authorized run, add a stage label and
allowlisted failure category/callable fields while omitting tracebacks, raw
exception strings, and private data. No correction or live retry was made in
this diagnosis.

- BM-017F: `COMPLETE`.
- macOS BM-023A: `BLOCKED_BM023A_ADAPTER_NAMESPACE_PACKAGE_PATH_TYPEERROR`;
  supervisor direction is required before adapter correction or another live
  attempt.
- tvOS: `NOT VALIDATED`.

## Historical pre-final-validation implementation and diagnosis

The entries below preserve earlier BM-017F test and diagnosis checkpoints.
Their pending-live-validation and BM-023A-blocked statements are historical;
the final supervisor run and current classification above supersede them.

### Bounded service-start poll implementation (2026-09-24)

After the unchanged step-[3/8] exact-version, enabled, and absent-transaction
checks succeed, the disposable harness now polls only the current
`.kodi-test/home/Library/Logs/kodi.log` for `Main Monitor Service Starting`.
The poll uses a monotonic 30-second deadline and 0.25-second intervals, then
allows the existing step-[4/8] all-marker and safety-order checks to run.
Timeout reports `BM-017F Red Light service did not start after activation
release`. It does not inspect `kodi.old.log` or alter production lifecycle
code. The prior `Unknown addon id 'plugin.video.redlight'` exception remains
an observed diagnostic only; it is not treated as proof of service failure.

Added nine poll regressions for immediate/delayed/timeout behavior, bounded
intervals, current-log-only isolation, missing log handling, and preserving
step-[4/8] marker/order checks. Existing step-[3/8] completion and
`needs_attention` tests still pass. `python3 -m unittest
tests.test_kodi_harness` passed **124/124**; targeted BM-017F poll/resume/order
tests passed **26/26**; compileall and `git diff --check` passed. No Kodi
process or lifecycle validation command was run. The supervisor still needs
to run the full disposable live gate using the manual command below.

### Offline service-start marker diagnosis (2026-09-23)

Latest current-run evidence is only from `.kodi-test` and project files. The
second Kodi session began at 21:41:07.403; JSON-RPC/Webserver was initialized
by 21:41:10.800, before the guard marker at 21:41:11.237. The held-owner
checkpoint at 21:41:11.591 recorded Red Light 2.6.8 registered but disabled.
Kodi logged `EXCEPTION: Unknown addon id 'plugin.video.redlight'.` at
21:41:12.245, while the hold was still in force. Private-resource verification
followed at 21:41:12.972, activation release at 21:41:12.976, and BM-020C
`no_transaction` at 21:41:13.002. `Main Monitor Service Starting` is absent
from both logs for this run; there is no Red Light service traceback, service
dependency failure, or logged service-start attempt.

The current Addons33 `installed` row says Red Light is enabled; Kodi's install
log and disposable `addon.xml` identify version 2.6.8. Both BM-020
`restart_transaction.json` and BM-022 `frozen_install_transaction.json` are
absent; only lock files remain. There is no `needs_attention` or pending
restart state. Current test updater policy is `AUTOMATIC` (0); the harness
step-4 equality check against the original captured policy was never reached,
so exact equality is not independently recorded. BM-022 source restores the
captured policy before clearing the completed transaction; the absent
transaction and `no_transaction` classification support successful
finalization, but are not a saved policy read-back from this harness run.

Control flow confirms a harness race risk: once the step-3 poll finds
`enabled=true` and transaction absent, it breaks without sleeping. It checks
the exact version, prints completion, and proceeds immediately to step 4; no
Red Light service-start wait exists. Step 4 reads the log before any stop. On
missing `service_start`, it raises, and the `finally` block invokes `stop()`.
The exact stop time and Kodi shutdown marker were not retained; the PID file is
now absent and the log ends at the BM-020 marker. The Red Light manifest
declares an `xbmc.service` extension without a synchronous start contract;
the project audit records Kodi's service manager as asynchronously starting
it on the Enabled event. A prior successful run observed the marker 205 ms
after hold release; this run had only 26 ms from release to the BM-020 marker
and the harness checked immediately thereafter. This timing is compatible
with stopping inside a plausible scheduling window, though no recorded
step-4/stop timestamp proves the exact elapsed time.

One Kodi `EXCEPTION` naming the add-on occurred before release, while the
registry checkpoint showed it disabled; finalization subsequently verified
the private resource, released the hold, and cleared the transaction. It is
not evidence that the `xbmc.service` entrypoint attempted and failed. The
narrowest supported diagnosis was a harness service-start race, not a proven
production service-start failure. The separately authorized bounded
current-log poll is now implemented; final disposable live validation remains
pending.

### Offline harness correction (2026-09-23)

Corrected only the harness step-[4/8] marker-order predicate. Presence of all
five markers remains mandatory, including BM-020 startup classification; the
safety predicate now orders only updater guard `<` private-resource
verification `<` activation-hold release `<` Red Light service start. The
BM-020 classification is treated as a required post-resume diagnostic marker
with no relative-order constraint. Production lifecycle code was not changed.

Added nine focused regression tests covering observed order, BM-020 before
private verification, each unsafe safety-marker ordering, missing BM-020,
missing safety markers, and acceptance of the observed post-resume marker
placement. `python3 -m unittest tests.test_kodi_harness` passed **115/115**;
compileall for `tools/kodi_test.py` and `tests/test_kodi_harness.py`, and
`git diff --check` passed. No Kodi process or BM-017F lifecycle command was
run. BM-017F is now `IMPLEMENTED_PENDING_FINAL_LIVE_VALIDATION`, not live
complete. macOS BM-023A remains blocked; tvOS remains not validated.

Steps [5/8]-[8/8] remain unchanged: [5] a second production BM-015
reconciliation must succeed with zero changed and zero failed actions; [6]
Kodi is stopped and the isolated Red Light DB is read-only checked for exact
four-column schema, WAL mode, fake private-field match, preservation of the
unrelated `auto_start_redlight=false` row, at least 100 initialized defaults,
and absence of the fake value from Kodi logs/durable BM-022 state; [7] the
Red Light root artifact must retain exact SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927` and the
fixture's exact dependency artifacts are reported; [8] records successful
completion with all inspection inside `.kodi-test`. Step [3] still requires
the resumed add-on enabled at the exact version and the durable transaction
absent; step [4] still requires all lifecycle markers, the safety ordering,
fake-value log exclusion, and restoration of the original updater policy.
No later lifecycle step was weakened.

### Latest offline step-4 ordering diagnosis (2026-09-23)

Step [4/8] reads only the current disposable `kodi.log`. It calls `find()` for
five literal markers, then requires these first textual positions to satisfy
`guard < BM-020 startup < private verified < hold released < service start`.
It does not parse timestamps, reject duplicates, or select markers by Kodi
session ID. If any marker is absent it raises
`BM-017F lifecycle markers were incomplete in disposable Kodi log`; the
reported ordering error occurs only after all five markers were found and the
strict chained comparison returned false. `find()` selects the first duplicate.
Step [4/8] then checks that the fake marker is absent from the log and that the
current updater policy equals the original policy captured before installation.

The current log contains each required marker once, in this order:

| Marker | Source | Timestamp |
|---|---|---|
| Updater guard reasserted | `ensure_frozen_install_guard` after setting and verifying quarantine | 21:02:46.407 |
| Private resource verified | BM-022 after successful structured-resource results are durably recorded | 21:02:48.057 |
| Activation hold released | BM-022 after final-validator success and durable release transition | 21:02:48.062 |
| BM-020 startup classification (`no_transaction`) | `service.py`, after `run_frozen_install_startup()` returns | 21:02:48.094 |
| Red Light service start | Red Light service emits `Main Monitor Service Starting` | 21:02:48.267 |

The actual order is `guard < private verified < hold released < BM-020 startup
classification < service start`. Thus all markers are present, the core
production invariant holds, and the exact failed comparison is
`BM-020 startup < private verified` (false). The BM-020 line is a completion
classification emitted after BM-022 resume/finalization, not a resume-start
marker. There is no separate BM-022 resume-start timestamp; the first progress
checkpoint is registry readiness at 21:02:46.685 (`before_refresh`), with the
owner registered at 2.6.8 and `enabled=false`. No resource-initialization-start,
Kodi Enabled-transition, or `Addons.SetAddonEnabled` event was logged. The
stage-[3] poll completed with final enabled state true and no transaction file;
Addons33's installed-state row also reports enabled.

BM-022 source order is: private verification; final software/config validator;
activation release; enable and final-state/version checks; COMPLETE transition
and resolution persistence; restore original updater policy; clear transaction.
`service.py` writes the BM-020 classification only after that call returns.
There is no timestamped restore or clear marker, but the absent frozen
transaction, successful stage-[3] poll, and lack of a BM-022 failure outcome
place successful finalization by 21:02:48.094, before service start. The
disposable settings database exists, passes integrity, is in WAL mode, and has
the expected `settings` schema. No setting values were read. The current
updater-policy read-back maps to `NEVER_CHECK`; transaction clearing follows a
successful restore to the captured original policy. The original scalar is not
separately retained in the preserved state after clear. No frozen/restart
transaction JSON or pending restart remains; lock sidecar files remain. No
`needs_attention` state is recorded.

Log provenance is current-run only: `reset()` removes the disposable root,
including prior logs and result files. Kodi rotated the first session into
`kodi.old.log` (startup 21:02:31.204) and the second session began in
`kodi.log` at 21:02:44.910. Step [4/8] reads only `kodi.log`. The old log has
one BM-020 classification from the first session but no private, release, or
service marker; each required marker appears once in the current log. Current
fixture and BM-015 job/result file modification times follow this run's reset,
so no stale result file contaminated the predicate. One separate ERROR-level
`unknown addon` diagnostic naming Red Light appears at 21:02:47.286; step [4/8]
does not read it, and the retained evidence does not identify its producer.

**Root cause**: `BLOCKED_BM017F_HARNESS_ORDERING_MARKER_DEFECT`, not a failure
of the observed private-verification/activation/service ordering. Smallest
recommendation only: keep marker-presence checks, but order the safety markers
as `guard < private verified < hold released < service start`; treat the
BM-020 startup classification as a post-resume diagnostic rather than placing
it before private verification. No implementation or lifecycle rerun was
performed in this diagnosis.

### Earlier staged-resume diagnosis (2026-09-23; prior run)

The preserved `.kodi-test` evidence shows the transaction's quiescence
checkpoint at `phase=awaiting_restart`,
`lifecycle_stage=quiescence_awaiting_restart`,
`lifecycle_restart_count=1`, and the Red Light activation hold unreleased.
After the full process boundary, the logs show updater-guard reassertion,
private-resource verification, activation-hold release, BM-020 startup
classification `no_transaction`, and Red Light service start. The current
disposable state has Red Light enabled, no frozen-install or BM-020 restart
transaction JSON, and `general.addonupdates=AUTOMATIC`, matching the saved
original policy. `settings.db` passes integrity, is in WAL mode, has the
`settings` table, and contains 592 rows.

There are no explicit per-stage success records. The initializer stages
through source revalidation, declaration loading, database creation/default
insertion, final validation, and marker publication passed by inference from
the later successful private-resource-verification event, which requires all
structured-resource results to succeed. This proves the Requests alias
ownership check passed during this live run, although no module-level marker
was logged. Since the held add-on was enabled, the updater policy restored,
and the transaction cleared after activation release, no second restart stage
was left pending. The final phase is inferred to have been `complete` before
the transaction file was cleared; terminal transaction history is not
preserved.

The diagnosis found that the inline 180-second poll in `tools/kodi_test.py`
requires both `owner_details.enabled is True` and no frozen transaction file. The shared
`jsonrpc()` helper returns `body["result"]`; the poll then incorrectly looks
for `detail_response["result"]["addon"]`, making `owner_details` empty. The
generic harness error therefore reflects a harness response-shape mismatch,
not a transaction-stall marker. This offline diagnosis led to the correction
recorded below; it did not trigger a Kodi launch or a second lifecycle run.

### Harness response-shape correction (2026-09-23)

`_bm017f_resume_poll_status` reads the top-level `addon` object returned by
`jsonrpc()`, preserves immediate `needs_attention` failure, and reports
completion only when the add-on is enabled and the durable transaction is
absent. Eight regression tests cover raw JSON-RPC unwrapping, enabled and
disabled states, missing details, pending transaction, `needs_attention`, a
double-wrapped negative, and the existing HTTP add-on-state consumer.

Validation: `tests.test_kodi_harness` **106 passed**, including the BM-017F
poll cases **8 passed**; compileall for the touched Python files and
`git diff --check` passed. No Kodi process, lifecycle harness command, normal
profile, real device, or private overlay values were accessed in this
correction. A later supervisor-run command reached step [4/8] but failed the
ordering predicate documented above.

Review confirmed the remaining harness success gates are unchanged: lifecycle
marker ordering and updater-policy restoration, a zero-change/zero-failure
second reconciliation, isolated settings database read-back, and exact root
artifact hash plus dependency count.

Command executed later by the supervisor (not during the response-shape fix):

```sh
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

### Verified package import context

Red Light's package-owned initialization imports now use the canonical
`<verified plugin.video.redlight>/resources/lib` root derived from the exact
installed source descriptor. The add-on root is not used as the Python root.
The declared module path is checked against `addon.xml`; traversal, symlinks,
missing roots, wrong owner identity, and wrong version fail closed.

The owner context derives Python dependency roots from the transaction's
fingerprinted frozen manifest and exact installed resolution records. The
audited import chain requires `script.module.requests` (2.31.0), with its
frozen transitive module dependencies `script.module.urllib3` (2.2.3),
`script.module.certifi` (2023.5.7), `script.module.chardet` (5.1.0), and
`script.module.idna` (3.10.0). Registry versions and enabled state must match
the exact frozen records. `script.module.pil` and other Red Light dependencies
are not added to the import path because the audited initializer does not
require them.

`verified_addon_import_context` routes known packages only to those verified
roots and blocks host-package fallback. It validates ordinary module origins
and namespace `__path__` locations for `caches` and `modules`, rejects external
collisions, restores `sys.path` and preexisting modules, and removes newly
created owner modules and namespace roots on success or failure. Red Light
continues to load its schema/default declarations and marker setter from the
installed package while the owner remains held disabled; no service, provider,
authentication, or network entrypoint is called.

Module ownership is derived from canonical source paths, not module names.
Ordinary modules use `__file__` or spec origin; namespace packages use every
`__path__` entry. Each path must resolve inside exactly one verified provider
root. Requests compatibility names are limited to its audited 2.31.0 aliases
for `urllib3`, `idna`, and `chardet`. An alias must be backed by the matching
provider in the current frozen dependency closure, sit under the verified
Requests package, and be the same module object as its canonical provider
entry. Host/system packages, missing providers, ambiguous roots, and path or
symlink escapes fail closed. Context-created aliases and controlled modules are
removed on success or failure; preexisting module objects and dictionaries,
`sys.path`, and `sys.meta_path` are restored. A failed ownership check followed
by a same-process retry passes offline.

The source audit of the exact retained Requests 2.31.0 `requests/packages.py`
confirmed its structural alias rule and the three provider names. The frozen
Red Light import fixture reaches `requests.adapters.Retry` from frozen
`urllib3.util.retry` and then passes post-import ownership validation.

### Latest offline alias diagnosis and correction

After the import-root correction, the offline Red Light import reached
`requests.adapters.Retry`; the first ownership rejection was
`requests.packages.urllib3.exceptions`, whose actual source belonged to the
verified `script.module.urllib3` provider. The old prefix-only check required
every `requests.*` entry to originate in Requests. That also left newly created
Requests aliases in `sys.modules` after failure, causing a same-process retry to
fail during preflight.

Commit `81e8b2c` now validates physical provider ownership and canonical object
identity for the three audited aliases, enforces Requests 2.31.0 and verified
dependency-closure membership, and restores the temporary module state. Safe
diagnostics retain `import_failure_category`, `failing_module`, and verified
provider IDs through CONFIGURE transaction status without paths, exception
text, or private values. This remains offline implementation evidence only.

### Resolved pre-correction import diagnosis

The latest supervisor-run disposable result completed `SOURCE_REVALIDATION`,
then failed at `LOAD_INITIALIZER_DECLARATIONS` with
`INITIALIZER_IMPORT_FAILED`; `last_completed_stage` was
`SOURCE_REVALIDATION`. The installed disposable source identifies as
`plugin.video.redlight` 2.6.8; BM-017F's validated artifact digest is
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`.

`RedLightSettingsAdapter._redlight_initializers()` inserts the installed
add-on root into `sys.path`, then first calls
`importlib.import_module("caches.base_cache")`. In the exact installed layout,
`caches/base_cache.py` is under `resources/lib/caches`, and the add-on root has
no `caches` directory. A side-effect-free isolated import probe using the same
root-only path reproduced `ModuleNotFoundError` for `caches`; source inspection
also confirmed that `resources/lib` is the package import root. The latest
persisted Kodi diagnostic contains only the stage/cause, not the exception or
frame, so the source-path reproduction identifies the first failing operation
but does not independently recover a live traceback. The same safe cause can
also be set by the pre-import namespace-collision guard; the live transaction
does not persist enough information to distinguish those branches. A static
scan found no Build Manager source imports of top-level `caches` or `modules`.

The remaining import chain, if that path is supplied, reaches
`modules.kodi_utils` (Kodi API imports), then `caches.settings_cache`, which
imports `modules.http_defaults` and `requests.adapters.Retry`. Red Light
declares `script.module.requests`, whose installed module code is under its
`lib` directory; Build Manager itself declares only `xbmc.python`, so dependency
visibility is a follow-on import-context check. Module-scope inspection found
no database, network, service/thread, migration, or Kodi-property operation
before the failed first import. The `caches` and `modules` directories have no
`__init__.py`; their namespace package objects have no `__file__`, which is why
the pre-correction collision and cleanup logic missed those package roots. The
current context checks their `__path__` locations and cleans them up. No
narrower existing defaults module was found; `resources/settings.xml` has no
setting declarations.

Historical classification for that pre-correction run:
`BLOCKED_RED_LIGHT_IMPORT_PATH_CONTEXT` (architecture verdict A). The
implementation above corrects the missing package root and adds verified,
isolated dependency resolution plus namespace collision handling. This task
did not run Kodi or the lifecycle harness; live confirmation remains pending.
No normal Kodi profile, real device, or private overlay values were accessed.
macOS BM-023A remains **STILL BLOCKED**; tvOS remains **NOT VALIDATED**.

### Historical BM-017F blocker progression

- `BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE` is resolved. The
  retained archive is SHA-256
  `64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`, size
  1,261,957 bytes.
- `BLOCKED_POST_RESTART_REGISTRY_READINESS_BYPASSED` is resolved. BM-022's own
  restart continuation now proves held-disabled registry readiness before
  configuration.
- `BLOCKED_RED_LIGHT_XBMCADDON_LOOKUP_WHILE_HELD_DISABLED` was addressed by
  deriving and revalidating the installed source from the frozen transaction.
- The most recent supervisor-run disposable attempt passed readiness and source
  validation, entered `redlight.settings` initialization, and stopped before
  private apply or activation release. Its latest preserved diagnostic names
  `LOAD_INITIALIZER_DECLARATIONS` and `INITIALIZER_IMPORT_FAILED`; the offline
  source/layout probe narrows the first operation to the missing `resources/lib`
  import root, subject to the live traceback limitation above.
- A later offline probe against the verified installed package roots established
  that the import chain reaches `requests.adapters.Retry`, then fails post-import
  ownership validation on the Requests compatibility alias backed by frozen
  `script.module.urllib3`. Commit `81e8b2c` corrects that provider mismatch and
  alias cleanup. No live rerun was performed.

### Actual initializer map

`RedLightSettingsAdapter.initialize()` in
`resources/lib/redlight_resource.py` now names the actual operations in order:

1. Validate the declared owner/resource/version.
2. Inspect any existing database and verify an already-populated resource.
3. Verify quiescence and activation hold; revalidate the frozen installed-source
   context, then revalidate the source again immediately before helper imports.
4. Import the package-owned schema/default helpers and marker setter.
5. Check the existing resource is empty. For a missing database, load the
   package schema declaration, create `addon_data`, create the database
   directory, open SQLite, set WAL mode, and execute/commit the schema.
6. Recheck the empty-state predicate, build package defaults, and insert rows.
7. Confirm rows persisted and validate the final database/WAL/schema.
8. Publish Red Light's two existing sync markers through its window-property
   helper, then return the same successful result.

Each operation uses a project enum stage. The split directory checks name the
existing recursive path creation boundaries; successful paths still create the
same directories and database content.

### Diagnostic propagation and safety

`ResourceInitializationStage` and `ResourceInitializationCause` in
`resources/lib/private_resource.py` provide allowlisted typed codes. A failure
retains the current `initialization_stage`, deepest
`last_completed_stage`, and typed safe cause while preserving the high-level
`PRIVATE_RESOURCE_INITIALIZATION_FAILED` code and safe owner/resource IDs.

The structured-resource manager carries these fields into the existing action
failure diagnostic. Import ownership errors additionally carry a validated
failure category, Python module ID, and verified provider IDs. The frozen
CONFIGURE handler persists only allowlisted
`action`, `resource_failure`, `owner`, `resource`, `cause`,
`initialization_stage`, `last_completed_stage`, and optional import ownership
tokens in the transaction status message. New optional action-result fields
are omitted for legacy errors, preserving their serialized shape. Exception
text, paths, settings rows, fake secrets, and private overlay values are never
copied into the diagnostic.

### Validation and live boundary

- Focused verified-source, import-context, Red Light resource, private overlay,
  add-on registry, Build Manager, dependency, frozen install/readiness,
  transaction, resume, CONFIGURE diagnostics, and manifest/schema suites:
  **456 passed**.
- Full repository `unittest` suite: **1,756 passed**.
- Project manifest/schema tests: **50 passed**.
- `compileall` over `resources`, `tests`, and `tools`: passed.
- All **7 tracked JSON files** parsed; `git diff --check` passed.
- No Kodi executable or BM-017F lifecycle harness command was run. No normal
  Kodi profile, real device, or real private overlay values were accessed.

Current classification is `IMPLEMENTED_PENDING_ALIAS_LIVE_VALIDATION`.
Both the historical import-path correction and the current Requests alias
correction are implemented and await live proof. Red Light clean-destination
lifecycle remains **NOT YET LIVE-VALIDATED**; macOS BM-023A remains **STILL
BLOCKED**; tvOS remains **NOT VALIDATED**. The supervisor will run the next
disposable validation from normal Terminal.

### Next manual command — supervisor only

Do not run this command from Codex:

```text
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

## BM-023A-H — Historical Exact Artifact Recovery

**Status**: Complete with result
`EXACT_YOUTUBE_7.4.4_UNOFFICIAL_2_NOT_RECOVERED`. Public exact-version metadata
was searched before considering packages. No candidate ZIP was downloaded,
imported, substituted, or repackaged.

### Public search and provenance

- The official v7.4.4 upstream release is commit `922cc0d` and publishes the
  normal `7.4.4` package plus `7.4.4+unofficial.1`; it does not publish `.2`:
  <https://github.com/anxdpanic/plugin.video.youtube/releases/tag/v7.4.4>.
- The upstream installation guide lists the normal and `.unofficial.1` ZIP
  variants and names `repository.yt.unofficial` and
  `repository.yt.testing_unofficial`:
  <https://github.com/anxdpanic/plugin.video.youtube/wiki/Installation>.
- The upstream release workflow checks out `master` for official packages and
  `nexus-unofficial` for unofficial packages, runs the repository generator,
  and mirrors generated ZIPs and XML indexes to OSMC stable/testing paths:
  <https://github.com/anxdpanic/plugin.video.youtube/blob/master/.github/workflows/release-development-repository.yml>.
  This identifies a generic packaging path, but not a `.2` source commit or
  build output.
- Current upstream `nexus-unofficial/addon.xml` declares version `7.4.4`, not
  `.2`:
  <https://raw.githubusercontent.com/anxdpanic/plugin.video.youtube/nexus-unofficial/addon.xml>.
- The checked OSMC unofficial-testing package index lists `7.4.4+beta.1` through
  `beta.4` and bare `7.4.4`, with no `.unofficial.2` asset:
  <https://ftp.fau.de/osmc/osmc/download/dev/anxdpanic/kodi/youtube/unofficial_testing/zips/plugin.video.youtube/>.
  The OSMC repository download index exposes repository ZIPs but no historical
  plugin package index:
  <https://ftp.fau.de/osmc/osmc/download/dev/anxdpanic/repositories/>.
- Exact-version and exact-filename searches across public GitHub, OSMC, and
  Panicked references produced no `.2` metadata result. The Panicked repository
  endpoints and Wayback CDX query were inaccessible through the available
  research surface. No exact `addons.xml` entry, package URL, provider checksum,
  public fork/cached package, or `.2`-specific source commit was located.

Therefore no exact artifact could be validated or imported, and no comparison
against upstream `.unofficial.1` was performed. The known retained local ZIP is
still the inexact bare `7.4.4` artifact and was not changed.

### Frozen input validation

The retained manifest and artifact store were left unchanged. The graph reports
37 nodes: 31 installed managed non-system nodes, 1 absent optional node, and 5
system/runtime nodes. The earlier 32 non-system total consisted of 31 installed
nodes plus absent optional `pysocks`; corrected semantics does not change the 37
node graph but no longer treats `pysocks` as an installed artifact requirement.
The manifest contains 30 artifact references, all 30 present in the store;
required and optional edges are 67 and 3. Exactly one installed managed node
lacks its artifact: `plugin.video.youtube` `7.4.4+unofficial.2`.

`script.module.pysocks` remains absent on the source, optional, missing,
disabled, artifactless, and excluded from installation order. YouTube remains
installed, enabled, managed desired software, reached from Umbrella through an
optional edge, and still requires its exact artifact.

The retained manifest still declares `capture_status=complete`, but production
`validate_frozen_manifest` rejects it with
`installed add-on artifact is incomplete for plugin.video.youtube
7.4.4+unofficial.2`. It is not a valid installable complete input. Its
canonical fingerprint remains
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`,
matching the previously recorded private-overlay target fingerprint. The
private overlay itself was not read or changed.

Focused frozen tests passed **25/25**. Matrix BM-023A-R validation passed
frozen capture/manifest/install **25/25**, dependency regressions **147/147**,
full suite **1607/1607**, and `git diff --check`. No production code changed.
Family Room and devices were not accessed; Kodi was not launched; the portable
test profile and private overlay were not touched.

**Smallest next step**: supervisor chooses whether to pursue another archival
source, accept an altered build, explicitly remove YouTube from managed desired
state, or arrange a separately authorized recapture. Keep BM-023A's historical
result `BLOCKED_MISSING_FROZEN_ARTIFACTS`; do not resume installation here.

## BM-023A-R — Frozen input completeness reconciliation

**Status**: Complete with result
`MANIFEST_SEMANTICS_CORRECTED_BUT_ARTIFACT_GAP_REMAINS`. The worker began on
`agent/codex` at `093757bc3ebacbf4c554aea50b5810498d90f7d5`; protected
`origin/matrix` was at the supplied starting SHA
`5a3598f565ad5b0c0164215eeefdf39b54a1d682`. The implementation is committed
as `a8d4b71`, integrated on matrix as `ff5c000`, and recorded by neutral matrix
tracking commit `a51a84d`. Codex is synchronized by a normal merge that
preserves worker history. Claude and Antigravity branches were not changed.

### Completeness semantics

- Every installed non-system node in the frozen desired software graph needs
  an exact artifact, including a node reached only through optional edges.
- An optional dependency absent at capture remains `capture_status: missing`,
  disabled, and artifactless; it does not block completeness and is excluded
  from installation order. System nodes remain artifactless declarations.
- Capture and `validate_frozen_manifest` now enforce the same rule. The parser
  accepts the capture-native empty version/type representation for missing
  nodes and the retained `not-installed` marker; neither becomes package
  identity.
- Schema v1 has no implicit unmanaged/excluded state for an installed node.

### Retained evidence and classifications

The existing candidate at
`/private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json` has 37
nodes and 32 non-system nodes. `script.module.pysocks` is a missing optional
node, disabled and without an artifact. Its only parent is
`plugin.video.youtube`, through an optional edge. The graph contains it because
capture traverses declared optional imports and records dependencies absent
from installed inventory. It needs no artifact and is no longer scheduled.
Before this correction, validation rejected it under the blanket
non-system-artifact rule; the old order builder also included every
non-system node, but no schedule was returned because validation failed first.

`plugin.video.youtube` is installed at `7.4.4+unofficial.2`, desired enabled,
and reached from `plugin.video.umbrella` through an optional edge. It is part
of the managed frozen software state because there is no explicit exclusion
state. The candidate declares no configuration packages; the protected
captured private overlay targets Red Light only. No captured public/private
configuration dependency on YouTube was found. Excluding it would change the
captured enabled software state and remove the add-on from the destination;
specific runtime feature effects were not device-tested. Provenance is
`repository_evidence`; `installed_origin` is only the placeholder `recorded`,
so an exact provider ID is unavailable.

Search stayed within retained local capture evidence and the named protected
Build Manager storage location. The capture directory's `artifact-store`,
`packages`, and `repository-candidates` were checked, along with matching
filenames in the retained `source` and `evidence` directories. No exact
YouTube `7.4.4+unofficial.2` artifact exists in the store or candidates. The
only YouTube ZIP is `packages/plugin.video.youtube.zip`: production ZIP
validation confirms ID `plugin.video.youtube`, embedded version `7.4.4`, SHA-256
`d744e5ba2d2b50924a9fa5624f4d209c2be95b97ef1ad1682cafbed160fb428f`, size
1,093,649 bytes. Validation rejects it for `7.4.4+unofficial.2`. It was not
imported, normalized, or substituted. No public-network lookup or Family Room
recapture was performed.

Production changes are in `resources/lib/frozen.py` and
`resources/lib/frozen_install.py`; regression tests and sanitized contracts
were updated in `tests/test_frozen.py`, `tests/test_frozen_install.py`,
`docs/FROZEN_BUILD_CAPTURE.md`, and `docs/FROZEN_BUILD_INSTALL.md`.

Focused frozen capture/install tests passed **25/25**. The full suite passed
**1607/1607**. `git diff --check` passed. No Kodi instance was launched, the
portable test profile was not modified, and Family Room was not accessed.

**Checkpoint next step**: BM-023A-H is recorded above as
`EXACT_YOUTUBE_7.4.4_UNOFFICIAL_2_NOT_RECOVERED`. The production validator still
rejects the retained input; do not resume frozen installation.

## BM-023A — Isolated macOS frozen-install validation preflight blocked (historical)

BM-023A remains historically complete as a validation task with result
`BLOCKED_MISSING_FROZEN_ARTIFACTS`; BM-023A-R corrects its interpretation of
optional installed versus absent nodes without changing that historical
result.

### BM-023A preflight evidence (historical)

**Status**: Complete as a validation task with result
`BLOCKED_MISSING_FROZEN_ARTIFACTS`. BM-017D tracking was integrated on
protected `matrix` at `5a3598f`, and Codex was synchronized by normal merge
at `bcd0fe5`. Kodi was not launched and the authorized disposable profile was
not mutated.

Read-only validation of the exact candidate manifest at
`/private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json` and
its paired artifact store found software fingerprint
`8ce7d2daf131f6c1bbcdf152c02c15745f9c52eac34480ee43e9f7af093e035`, 37 graph
nodes, and `capture_status=complete`; however, two of 32 non-system nodes are
not installable: `plugin.video.youtube` `7.4.4+unofficial.2` and
`script.module.pysocks` `not-installed`. Only 30 artifacts are present.
`validate_frozen_manifest` therefore fails closed with an incomplete-required-
artifact error. This exact artifact set does not satisfy BM-023A's frozen
install gate. Do not recapture from Family Room or substitute newer packages.

The protected `family-room-redlight-2.6.8` overlay was read via
`PrivateOverlayStore`; typed overlay/resource validation passed, all ten
declared field identifiers were present, and its target fingerprint matches
the frozen software fingerprint. Private values were not displayed. The
existing bundled portable profile contains prior Kodi data, but no cleanup,
wipe, launch, install, reconciliation, or other test-profile mutation was
performed. No ordinary Kodi process enumeration was needed after the frozen
artifact gate failed.

No BM-023A live gate or tests were run. Smallest next step: recover the exact
approved missing frozen artifacts/evidence from existing retained capture
outputs, then rerun read-only manifest validation. If those exact artifacts
are unavailable, stop for supervisor direction. No Family Room recapture,
newer-package substitution, Apple TV access, or next milestone is authorized.

## BM-017D — Real Family Room structured private-resource capture complete

**Status**: Complete and recorded for protected `matrix`; matrix remains
neutral with `active_agent: none`. The captured overlay remains outside Git
in protected local Build Manager storage.

Matrix tracking integration commit: `5a3598f`. Codex was synchronized to that
tip by normal merge before BM-023A preflight began.

Using the explicitly authorized read-only Xcode `devicectl` connection to
`AppleTV - Family Room (4)` and bundle `com.eengert.koditvosnew`, the only
received resource was
`Library/Caches/Kodi/userdata/addon_data/plugin.video.redlight/databases/settings.db`.
The names-only directory check found no `settings.db-wal` or `settings.db-shm`
sidecars, so the authorized main-database snapshot was sufficient. Unrelated
cache database sidecars were not retrieved.

The BM-017C Red Light adapter validated owner/path contract
`plugin.video.redlight`, version contract `2.6.8`, resource
`redlight.settings`, schema `redlight-settings-v1`, exact four-column text
schema, WAL mode, and SQLite integrity. The ten reviewed field-level
allowlist entries were all optional private/auth candidates and were captured
and verified: `mdblist.refresh`, `mdblist.token`, `mdblist.user`,
`pm.account_id`, `pm.token`, `tb.token`, `trakt.expires`, `trakt.refresh`,
`trakt.token`, and `trakt.user`. No required fields were declared or missing;
all 10 optional fields were present. Derived/generated, ordinary preference,
cache, and unrelated rows remained intentionally unmanaged.

The protected overlay is `family-room-redlight-2.6.8` at
`/Users/eengert/Library/Application Support/Build Manager/addon_data/script.build.manager/private_overlays/family-room-redlight-2.6.8.json`,
with fingerprint
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`.
It is protected plaintext with `0600` file permissions; encryption at rest is
not claimed. The overlay is bound to frozen software fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.

No structured-resource apply path was called. No Red Light/Kodi setting,
database, add-on state, repository, device, or source profile was modified.
The raw database snapshot and locally generated SQLite sidecars were deleted
and verified absent. The secret-blind worktree scan reported
`leak_detected=false`.

Focused validation passed structured-resource/private-overlay tests **27/27**
and the focused BM-017A/BM-017C/manifest/build-manager/BM-020/BM-022 group
**386/386**. No production or test code changed, so the full suite was not
rerun. The worker and matrix integration diff checks passed.

Frozen Family Room software is **COMPLETE**; Family Room private overlay is
**COMPLETE**; captured desired state is **COMPLETE**; real-device frozen
installation remains **NOT VALIDATED**. No next milestone was started.

## BM-017C — Structured private resource foundation integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`.

The reviewed substantive matrix commit is `dce8276`, reconstructed from worker
implementation commit `8ba7bdc`; worker tracking and all worker `.agent/*`
metadata were excluded. BM-017C provides generic structured private-resource
declarations, typed protected-overlay values, explicit field ownership,
secret-safe results, and manifest/schema/resolver/build-manager integration.
The Red Light 2.6.8 adapter is exact-version and exact-schema, requires an
existing WAL database and quiesced runtime, updates only declared string rows
inside a bounded `BEGIN IMMEDIATE` transaction, verifies each row before
commit, preserves unrelated rows, and reports an explicit restart/reload
requirement. It never replaces the mixed database, creates missing state, or
accepts arbitrary SQL, paths, or wildcard fields.

Validation rerun on the integrated tree passed structured-resource tests
**27/27**, the focused BM-017A/BM-017C/manifest/build-manager/BM-020/BM-022
regression group **386/386**, the full suite **1604/1604**, and
`git diff --check`. Tests use fake Red Light SQLite fixtures only; no real
Family Room private database, credentials, Kodi profile, Apple TV, or other
device was accessed or mutated. BM-017B remains complete with historical
result **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**; frozen Family Room software
is **COMPLETE**, captured desired state is **INCOMPLETE**, and real-device
frozen installation is **NOT VALIDATED**. BM-017D has not started.

No next milestone was started. The smallest next step is supervisor direction
and separate authorization for BM-017D's real private-state capture work.

## BM-017B — Private overlay capture blocker integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`.

BM-017B result: **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**. Red Light `2.6.8`
requires private/auth state in a mixed `databases/settings.db` resource outside
the BM-017A typed Kodi-setting boundary. The sanitized read-only evidence is
recorded in `docs/BM017B_PRIVATE_CAPTURE.md`; no private values were captured,
no raw database was retained, no arbitrary private-file copier was added, and
the Family Room source remained read-only. Frozen Family Room software remains
**COMPLETE**, captured desired state remains **INCOMPLETE**, and real-device
frozen installation remains **NOT VALIDATED**.

BM-017C is complete and integrated above. BM-017D is complete; its sanitized
capture state is recorded at the top of this file. BM-023A is now in preflight.

## BM-017A — Private/auth overlay foundation integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`.

The reviewed substantive matrix commit is `321fee8`, reconstructed by
cherry-picking worker implementation commit `ebd4c61`. The worker tracking
commit and all worker `.agent/*` metadata were excluded. BM-020, BM-021A/B,
BM-022, and BM-022V/BM-022V-R remain complete. Required Family Room frozen
software capture is **COMPLETE**; ready-to-use configuration remains
**PENDING REAL PRIVATE OVERLAY CAPTURE / IMPORT**; real-device frozen
installation remains **NOT VALIDATED**.

BM-017A provides explicit public private-setting declarations with target
namespace, setting ID, type, required/optional status, sensitivity class, and
deterministic ownership. Version-1 overlays contain typed entries, build and
overlay identity, duplicate/undeclared/type/completeness checks, and a
canonical SHA-256 fingerprint. Active storage is
`special://profile/addon_data/script.build.manager/private_overlays/`, with
atomic writes and restrictive `0700`/`0600` permissions where supported.
The current backend is protected local plaintext: encryption at rest is not
claimed and no custom cryptography is used.

BM-015 remains the sole typed settings backend. Public configuration is
applied first, then validated private values through the same typed
write/read-back/verification path. Private values stay outside public
manifests, packages, frozen artifacts, logs, `.agent/*`, and BM-020/BM-022
durable state; those transactions persist only overlay ID, fingerprint, and
required flag. Missing required overlays and fingerprint drift fail closed;
optional absence is a safe no-op.

Integrated validation passed private-overlay tests **14/14**, the
BM-015/BM-020/BM-022 regression group **588/588**, the full suite
**1591/1591**, and `git diff --check`. No implementation or test accessed
real Family Room private data, credentials, a real Kodi profile, Apple TV,
or another device. BM-017B real private capture/import has not started.

No next milestone was started. The smallest next step is supervisor direction
and explicit authorization for any future private-state capture/import work.

## BM-022V / BM-022V-R — Frozen Family Room software capture integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The clean
matrix-side substantive commit is `31b8f9d`, reconstructed from the approved
worker endpoint `784ea8f`; worker `.agent/*` metadata was excluded.

BM-022V read-only validation and BM-022V-R exact-artifact recovery establish
that Frozen Family Room software capture is **COMPLETE** for required
software: 37 graph nodes, 67 required edges, 3 optional edges, zero required
missing artifacts, 30 exact artifact-backed nodes, 194,254,227 captured
artifact bytes, and candidate fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
The optional YouTube artifact remains incomplete (`7.4.4+unofficial.2`
installed versus cached `7.4.4`) but is non-blocking. The exact Dropbox
`script.module.dropbox` `10.3.1+matrix.1` artifact is captured with SHA-256
`5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6` and
size 667,538 bytes. The unchanged Robotocjksc ZIP is accepted through the
generalized one-safe-root validator and normalized only during staged
extraction; package bytes were not rewritten.

BM-023A-R later established that optional incoming edges do not waive the
artifact requirement for this installed, enabled node. The non-blocking
classification above is preserved as historical BM-022V/R tracking and is
superseded by the current completeness invariant.

Ready-to-use configuration remains **INCOMPLETE / BLOCKED_BY_BM017** because
private/authenticated state was not captured. Real-device frozen installation
is **NOT YET VALIDATED**. Family Room evidence and software capture remained
read-only: no install/update, enable/disable, repository refresh, restart,
settings/database write, or reconciliation occurred. BM-017 remains deferred
and no next milestone was started.

Integrated validation passed focused artifact/repository/add-on/frozen tests
**331/331**, the full Build Manager suite **1577/1577**, and
`git diff --check`.

## BM-022 — Frozen Build Installation and Transaction Lifecycle integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The reviewed
substantive integration commit is `56ea26a`, reconstructed from worker
commit `27f4215`. Worker `.agent/*` metadata was excluded.

BM-022 installs only complete BM-021B manifests backed by immutable exact
artifacts. It validates SHA-256, size, ZIP identity, exact add-on ID/version,
dependency edges, system boundaries, and deterministic topological order. It
reuses the reviewed BM-011 staged-package boundary with atomic staging,
`UpdateLocalAddons`, exact-version verification, and fail-closed
replacement/downgrade behavior.

The durable frozen-install transaction captures the original global updater
policy before mutation, owns `NEVER_CHECK` through installation,
configuration, restart/resume, and final validation, reasserts and verifies
the guard before BM-020 startup mutation, restores the original policy only
after successful final validation, and preserves diagnosable
`NEEDS_ATTENTION` state on failure. Existing Build Manager configuration and
BM-020 restart/resume remain the owners of those operations. Explicit abandon
restores policy and clears the transaction without claiming software rollback.

Integrated validation was rerun: focused BM-022/BM-021B/BM-020/dependency/
repository regressions **639/639**; disposable `validate-frozen-install`
passed; full suite **1573/1573**; and `git diff --check` passed. The live
proof used only `.kodi-test` and did not claim complete real Family Room
capture/install or real-device validation.

BM-020, BM-021A, BM-021B, and BM-022 are complete. BM-017 remains deferred;
no next milestone was started.

## BM-021B — Frozen artifact capture core integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`.

The reviewed BM-021B substantive commit was reconstructed from the approved
worker endpoint as `2ee040c` (`feat(BM-021B): add frozen artifact capture
core`). It adds the SHA-256 content-addressed, atomic write-once artifact
store; exact ZIP validation and read-back; typed installed inventory with
direct/transitive dependency edges and the `xbmc.gui`, `xbmc.python`, and
`kodi.resource` system boundary; honest provenance and incomplete-capture
manifest states; exact cache/repository acquisition ordering; and the
supported Settings JSON-RPC updater guard. It does not add frozen installation,
retention, pinning, scheduling, freshness enforcement, or garbage collection.

The disposable proof recorded the AF3 3.2.19 closure as 18 healthy
third-party add-ons plus the system boundary, exact versions and dependency
edges, and an honest `incomplete_artifact` result after the reset had no exact
package-cache ZIPs. No installed directory was zipped, no false `COMPLETE`
claim was made, and no real Kodi profile or Apple TV was accessed. The updater
proof verified read/set/read-back, restart reassertion because `NEVER_CHECK`
does not persist across restart, no observed scheduled updater activity while
guarded, explicit restoration, and restoration after a second restart. A
resumed transaction must reassert and verify the guard before every mutation.

BM-020, BM-021A, and BM-021B are complete. BM-022 has not started; BM-017
remains deferred; family-room source/distribution concerns remain pending.
No next milestone was started.

## BM-021A — Frozen Build Capture audit integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`.

Substantive commit: `b32369e` (`docs(BM-021A): record frozen build capture
audit`). The audit establishes exact reproducible artifact requirements,
verified artifact acquisition priority, bounded/non-authoritative Kodi cache
semantics, rejection of installed-directory zipping, frozen third-party
dependency closure, repository artifact/provenance handling, Kodi's global
three-state updater policy, the absence of a solved per-addon auto-update API,
and a SHA-256 content-addressed immutable artifact-store model. Freshness
checks warn without substituting newer package versions. Updater inhibition
restart/race behavior remains for BM-021B.

BM-021B and BM-022 have not started. BM-020 remains complete and BM-017
remains deferred. Family-room source/distribution concerns are being absorbed
by BM-021/BM-022 and are not independently marked solved.

## BM-020C — guarded post-restart resume integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`.

Substantive integration commits: `81ba44b` (`feat(BM-020C): add guarded
post-restart resume`) and `091cfe9` (`docs(BM-020C): document service readiness
boundary`). Codex worker metadata was excluded.

BM-020C completes the guarded post-restart resume path. Startup accepts only a
new-session `READY_FOR_RESUME` transaction, re-reads and previews the original
request, verifies the desired fingerprint, atomically claims `AWAITING` as
`RESUMING`, runs the normal `BuildManager.reconcile()` path, verifies the final
fingerprint and `RestartRequirement.NONE`, then atomically clears the expected
transaction. Preview, fingerprint, reconciliation, claim/clear conflicts,
exceptions, repeated `KODI_RESTART`, and later `RESUMING` or
`NEEDS_ATTENTION` states fail closed with bounded diagnostics. The service
remains thin: it does not restart Kodi or a host process, and current supported
platforms still require a manual full Kodi restart before automatic resume.

Integrated validation passed focused BM-020C/BM-020B/BM-020C1/BM-020A/BM-019
tests **465/465**, the disposable BM-020C gate **8/8** with AF3 dependency
closure **18/18**, the full suite **1536/1536**, and `git diff --check`.
The gate proved a new session, service-driven automatic resume, authoritative
read-back, final fingerprint equality, `NONE`, no second handoff, later no
transaction, and real Kodi profile immutability. AF3 generated first-run state
was bootstrapped only inside `.kodi-test`; the selected AF3 unmanaged probe is
owned by the BM-020A gate because AF3 normalizes that entry across restart.

BM-020 overall is complete. BM-017 and family-room distribution/source work
remain deferred. No next milestone was started.

## BM-020C1 — typed restart capability model and manual-restart handoff integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`.

Substantive integration commit: `bcaf2ca` (`feat(BM-020C1): add manual restart
capability handoff`). Worker-specific Codex metadata was excluded.

BM-020C1 establishes a typed restart capability seam and conservative platform
policy. macOS, Android/Shield, Fire OS, Apple TV/tvOS, and unknown platforms
resolve to `MANUAL_APP_RESTART_REQUIRED`. A successful typed `KODI_RESTART`
result persists and verifies `AWAITING_RESTART` with
`restart_attempt_count = 0`, returns structured manual guidance, and does not
restart or quit Kodi. Failed reconciliation creates no transaction; `NONE`
completes without one; same-session calls reuse the handoff without a second
reconciliation; and a new session with count `0` is `READY_FOR_RESUME`.
Explicit automatic capability selection fails closed because no approved
production adapter exists.

Integrated validation passed: focused BM-020C1/BM-020B/BM-020A/BM-019 tests
**63/63**; disposable manual handoff gate **8/8**, including AF3 dependency
closure **18/18**; full suite **1517/1517**; and `git diff --check` clean.
The disposable gate used only `.kodi-test`, proved the harness-controlled
process boundary, and confirmed the real Kodi profile remained unchanged.

BM-020 overall remains incomplete. Remaining work is read-only fingerprint
revalidation, `RESUMING` claim, normal BuildManager resumed reconciliation,
success clearing, repeated-restart loop prevention, and resume-failure/
recovery semantics. BM-017 and family-room distribution/source work remain
deferred. No next milestone was started.

## BM-020B — durable restart transaction and startup re-entry foundation integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`. `active_agent` is `none`; matrix remains neutral.

Substantive integration commit: `f3ccf2a` (`feat(BM-020B): add durable restart
transaction foundation`). Worker-only `.agent/*` metadata was not copied.

BM-020B adds a profile-local schema-v1 restart transaction record containing
only the safe request, desired fingerprint, restart requirement, originating
Kodi session UUID, and explicit transaction phase. It uses atomic staged
writes with flush/fsync/replace, read-after-write validation, fail-closed
corrupt or unsupported records, explicit clear, and a nonblocking POSIX
`fcntl.flock` sidecar lock with automatic release. The session UUID is stored
in the Kodi home-window property
`script.build.manager.kodi_session_id`.

The thin `xbmc.service` entrypoint classifies startup only: no transaction,
same-session awaiting restart, ready for resume, needs attention, invalid
transaction, or inspection failure. It does not restart Kodi, reconcile, or
resume work; BM-020C owns those actions.

Validation from this integrated tree: BM-020B transaction tests **32/32**;
the disposable process-boundary gate **9/9**; full suite **1504/1504**; and
`git diff --check` clean. The disposable gate proved service startup on
normal launch, same-session protection, durable state across an external Kodi
restart, ready-for-resume classification, explicit clear, and the returned
no-transaction path. The first gate attempt exposed only a timing race
between JSON-RPC readiness and automatic service execution; the unchanged
retry passed. The real Kodi profile remained read-only and no device or
Apple TV was accessed.

BM-020C and BM-017 remain deferred. Cross-device lock behavior is an
architecture selection for supported POSIX-like Kodi targets, not a live
claim beyond the disposable macOS validation. No next milestone was started.

## BM-020A — production reconciliation executor integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`. `active_agent` is `none`; matrix remains neutral.

Substantive integration commits: `eeafc1c`, `0ed2c35`, `821e69e`, `0fb0bd5`,
and `1ad0fdb`.

BM-020A establishes the callable `BuildManager.reconcile()` contract: typed
serializable request/result models; load → inspect → resolve → preflight → plan
→ execute → validate orchestration; planner-authoritative owner dispatch;
deterministic desired-state fingerprints; ordered fail-closed execution; and
BM-019 `RestartReport` aggregation. No restart execution, transaction
persistence, resume, locking, or restart-loop behavior was added.

The disposable `validate-build-manager` gate passed from this integrated tree.
It used the self-contained `bm020a-executor.example.json` / `bm020a-disposable`
fixture and the checked-in production `af3-common` package. The real AF3
dependency closure was healthy at 18/18; the first pass exercised `SET_SKIN`
through `SkinActivator` and `CONFIGURE` through `ConfigurationManager`, read
back all 16 typed settings with `files=[]`, and reported
`RestartRequirement.NONE`. The identical second pass retained fingerprint
`sha256:05f278188815d3900760d7b3d4d82c31e6e50324128a3e45031cca9ee8606d86`
and made no mutations. Managed `Navigation.OnBack` drift was repaired while
unmanaged `TMDbHelper.Corner.Radius` remained unchanged. An invalid device
selector failed in resolve with disposable state unchanged.

The narrow `kodi.resource` system-dependency classification correction is
included and covered by focused tests. The real family-room distribution and
source coverage gap remains separate: BM-020A does not claim fresh-installable
coverage for POV, Red Light, Umbrella, MyAccounts, AF3, or the production
repository bootstrap/source binding.

Focused integrated validation passed 1458/1458; the full suite passed
1472/1472; and `git diff --check` passed. The real Kodi profile, Apple TV, and
all devices remained untouched. BM-020B/C and BM-017 remain unstarted.

## BM-020A1 — action-ownership prerequisites integrated

BM-020A1 remains complete and is included in the BM-020A integration history.

## BM-019 — restart-requirement aggregation integrated

**Status**: Complete, supervisor-approved, and integrated on `matrix`.
`active_agent` is `none`; matrix remains neutral.

Substantive integration commit: `202f41d`.

Established the typed `RestartRequirement` contract with the current levels
`NONE` and `KODI_RESTART`. Individual operation results declare their local
requirement, while orchestration aggregates successful changed results
centrally and monotonically. The planner remains non-mutating and does not
infer restart requirements from action kinds. Idempotent/no-change operations
report `NONE`; failed/uncommitted operations do not establish a requirement;
later failures preserve earlier successful requirements.

The contract and JSON-safe `RestartReport` are documented in
`docs/RESTART_REQUIREMENTS.md`. BM-018D/BM-018E paths remain `NONE`; their
typed AF3 persistence compatibility behavior does not spuriously request a
restart. BM-020 owns actual restart execution, transaction persistence, and
resume/re-entry and has not started.

Focused BM-019/planner/config/add-on/dependency/repository/skin tests passed
813/813. Full suite passed 1476/1476. `git diff --check` passed. No current
production operation legitimately requires restart, so no synthetic live
restart scenario was added. Real Kodi profile and devices remained untouched.

## Prior integrated state

## BM-018D compatibility extension + BM-018E — integrated

**Status**: Complete, supervisor-approved, and integrated on `matrix`.
`active_agent` is `none`; matrix remains neutral and awaits the next
assignment.

Substantive integration commit: `1c024e9`.

The integrated work preserves the approved 16-setting `af3-common` package
with `files: []`, explicit skin ownership, and the AF3-specific mutual-
exclusion policy outside the generic backend. The generic skin backend now
handles canonical/lowercase typed lookup, double-`-32602` fallback, safe
`Skin.SetBool`/`Skin.SetString`/`Skin.Reset` persistence, strict effective
read-back, and bounded persisted-state verification. XML is used only for
fallback key/type eligibility and persistence verification, never as the
effective state backend.

BM-018D disposable validation passed 17/17. BM-018E's production AF3 gate
passed 14/14 for all 16 settings, including authoritative read-back,
idempotency, drift repair, ownership failure before mutation, restart
persistence, and wrong-skin rejection. AF3's complete disposable dependency
closure was 18/18 installed, enabled, and not broken. The first-run AF3
generated-runtime bootstrap remains disposable-only; pristine first-ever AF3
provisioning is not overstated as proven.

Focused tests passed 461/461; the full suite passed 1463/1463; and
`git diff --check` passed. The real Kodi profile remained read-only, with no
Apple TV or other device access. BM-017, BM-019, BM-020, and any next
milestone were not started. BM-019/BM-020 retain ownership of future
restart aggregation/resume work.

Next task awaits supervisor assignment.

## Prior integrated task

### WF-002 — Antigravity usage reporting via CodexBar integrated

**Status**: Complete, supervisor-approved, and integrated on `matrix`;
`matrix` remains neutral and awaits the next assignment.

Integrated workflow commit: `fcc7caa` (cherry-picked with provenance).

WF-002 adds the read-only `tools/antigravity-usage` helper, focused tests, and
the Antigravity CodexBar usage guidance in `AGENTS.md`. The helper preserves
distinct named Gemini and Claude/GPT pools, account/source/login metadata when
available, and sanitized bounded failure results.

Focused tests: 11/11 passing. The live helper smoke test was attempted
read-only; the current CodexBar invocation timed out and the helper returned
the sanitized unavailable result without exposing stderr or private data.

Integrated substantive commits:

- `28a6fd4` — `feat(BM-018D): add typed skin configuration support`
- `5a3cc9a` — `fix(BM-018D): resolve AF3 disposable live gate`

BM-018D generic typed skin-setting support is complete. The disposable AF3
live gate passed 17/17 and the full suite passed 1438/1438. The disposable
environment must install, enable, and verify the complete AF3 dependency
closure, with no dependency broken. AF3's first-run generated-state
initialization caused the original transient fallback; the harness performs
that generated-runtime bootstrap only inside `.kodi-test`, then validates the
actual BM-018A Estuary -> AF3 confirmation/activation path. Completely
pristine first-ever AF3 provisioning is not overstated as proven.

AF3 key normalization and non-boolean string-setter return handling are
implemented in the skin backend/runtime adaptation. AF3-specific mutual
exclusion policy remains isolated from the generic backend.

- Focused BM-018D tests: 765/765 passing.
- Full suite: 1438/1438 passing.
- `git diff --check`: passing.
- Real Kodi profile remained read-only; no Apple TV access occurred.
- At that earlier WF-002 checkpoint, no production `af3-common` package had
  yet been created.
- At that checkpoint BM-018E, BM-017, BM-019, and BM-020 were not started.

Next task awaits supervisor assignment.
