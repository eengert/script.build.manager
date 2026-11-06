# A15 native content-conflict preservation procedure

This is a preparation contract, not native authorization. Obtain independent
review of the correction and a separate task naming the one allowed runtime
scenario. Do not run this procedure as part of the offline readiness task.

## Authoritative comparison and maintenance attribution (N6)

Keep three distinct observations; never replace the strict comparison result:

| Observation | Required evidence | Meaning |
| --- | --- | --- |
| Exact scoped semantic preservation | Successful fresh begin/finish and every supported projection plus separate public witnesses equal | `PRESERVED` within those scopes only; no complete-profile claim |
| Independently supported Kodi lifecycle maintenance | Evidence of the particular changed field/structure, the pinned writer and relevant caller, and independent evidence that this writer produced the particular change in the correlated interval | An explanatory attribution beside an unchanged strict `CHANGED_OR_MISSING`; never a preservation PASS |
| Unexplained or potentially BM-induced change | A strict difference without that complete causal evidence, including a maintenance-shaped difference or a matching control run alone | Attribution unresolved; do not waive, normalize, suppress, restore or retry |

The current bridge/driver deliberately return per-file equality results and
`maintenance_attribution=UNKNOWN`; they do not export field deltas or private
baseline values. There is no current automatic causal classifier. Do not infer
one from file names, numeric direction, timestamps, receipt validity, source
plausibility or a run without Build Manager. A same-shaped overwrite can
produce exactly the same projection as a legitimate lifecycle update.

Pinned Kodi 21.3, commit `a3a448d26b8d560a65655dab2cd122994dc4e146`, establishes
specific possible writers, not the writer of an actual observed delta:

- `xbmc/application/Application.cpp`, `CApplication::Stop`: adds integer
  `CTimeUtils::GetFrameTime()/60000` to stored uptime, then saves settings when
  the settings file exists. `SystemInfo.h` defines the setter; `SystemInfo.cpp`,
  `CSysInfo::Save`, writes `general/systemtotaluptime`. Do not equate host wall
  time with the frame-clock value or assume that the counter was unchanged
  before shutdown. A normal session lasting minutes can change this field.
- `xbmc/view/ViewStateSettings.cpp`, `Save`: serializes current viewstate,
  setting-level and event-log state. These can also represent user or product
  changes; their presence in this writer is not a harmlessness exemption.
- `xbmc/TextureDatabase.cpp`, `IncrementUseCount`: increments usecount and sets
  last-use time. Existence of this API does not prove it was invoked for a
  particular row by normal UI activity. Other texture changes remain compared.
- Display, media, skin and peripheral serializers can save current state.
  Serializing a field does not establish why its value changed.

Synthetic controls cover strict uptime/view/setting-level and texture-counter
changes, and indistinguishable lifecycle-shaped versus overwrite outcomes.
They prove detection and the attribution limit, not native writer causality.

For the single proposed test, use the existing strict result. Any difference
stays `CHANGED_OR_MISSING`; absent independently supported causality, overall
preservation qualification is INCONCLUSIVE. Even proven maintenance does not
turn this strict result into `PRESERVED` or authorize A15 acceptance. A future
policy accepting explained changes, or a separately reviewed way to compare
private field deltas in memory, needs its own explicit decision. Neither is
implemented here. No monitoring service or private baseline persistence is
needed or authorized by this contract.

## Audio root placement (N2)

The accepted grammar is correct. The pinned call chain is:

1. `Application.h`: `CApplication` inherits `CApplicationSettingsHandling`.
   `CApplication::Create` calls its `RegisterSettings` method.
2. `ApplicationSettingsHandling.cpp::RegisterSettings` registers `this` with
   `CSettings::RegisterSubSettings` (after the required player component exists).
   Its header declares the `ISubSettings` inheritance and `Save` override.
3. `CSettings::Save(file)` obtains the serialized settings document's root and
   calls `Save(root)`. That overload calls every registered subsetting's
   virtual `Save` with the same root, without an intermediate wrapper element.
4. The application handler's `Save(settings)` passes the same pointer to
   `CApplicationVolumeHandling::Save`. That method inserts `<audio>` directly
   under it and writes `mute` and `fvolumelevel` beneath `<audio>`.

This proves placement under the settings root, as well as shape. Keep the
existing grammar; no new audio permission or runtime claim is introduced.

## Preconditions for the separately authorized test

- Work only in `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`,
  branch `agent/codex`, at the exact independently reviewed full commit supplied
  in that authorization. Preserve the four known `.agent` histories.
- Only `/Applications/Kodi Build Manager Test.app`, portable `-p`, is eligible.
  Use unchanged automated admission. No repeated human closure confirmation is
  required. Any refusal stops target access; never query or terminate a foreign
  process, use another census, retry, or weaken policy.
- Authenticate installed product and adapter using the existing verified stage
  manifest, including installed-tree and Git binding. Distinguish the older
  staged commit from the reviewed host-tool commit. Verify product-byte
  equivalence. No staging or source substitution is part of this procedure.
- Admit current selected/applied association, saved library/artifacts, installed
  state, updater, terminal publication state and absence of conflicting frozen,
  restart, capture or hold ownership using existing supported witnesses.
  UNKNOWN is not absent. Preserve A11 marker and failed AF3 journal.
  The accepted driver's public admission also requires Estuary configured.
  If that prerequisite is not met, stop; do not switch or restore the skin.
- Revalidate the existing conflict fixture from the sealed
  `.qualification-evidence/item8-public-create-failure-20261016/REPORT.md`:
  exact existing build identity/version, and the previously qualified different
  public root. Do not replace a missing fixture or assume its current health.
  Require complete current capture eligibility and exact available artifact
  authority without uncontrolled downloads, skin/private capture or installation.
  Current readiness must be established then; this offline task reads no profile.
- Exclude known concurrent writers. Stopped state and two stable reads are
  bounded evidence, not a global exclusion lock or atomic snapshot.
- While stopped, establish only what is observable: supported MCP launch/UI
  controls, the persistent PTY control tools below, helper/wrapper source identity,
  approved expected HTTP loopback/port/user configuration and the fixed credential
  mechanism. Do not retrieve a credential as a "test" or claim successful HTTP
  authentication, listener ownership or a running PID before launch.
- The future native task must explicitly authorize and accept first use of the
  authenticated HTTP quit on this configuration, including the risk of leaving
  Test.app running if it fails. Prior authenticated status is not proof of quit.
  If that authority or the supported tools are missing, do not launch. No alternate
  GUI automation, transport, credential fallback or forced termination.
- Keep public evidence secret-blind: fixed results, operation counts, source
  identities and scoped comparison outcomes. Do not publish identifiable add-on
  inventories, settings IDs/values, database rows, private-value digests or raw
  baselines. The driver keeps separate public witnesses in memory; it does not
  need a new durable inventory dump. Retain only bounded, suitably protected UI
  evidence necessary to prove the actual conflict operation.

## Foreground FINISH channel (B1)

Use Codex's supported `exec_command`/`write_stdin` persistent PTY channel,
through `functions.exec`. This method was rehearsed with the non-Kodi fixture
in `tests/test_a15_finish_channel.py`, using the production driver's actual
`pending`, `announce` and `wait_signal`. No FIFO, holder, service or replacement
driver is introduced. If these tools are unavailable, STOP before begin/launch;
a terminal tool that cannot write to its running process is not equivalent.

Start the exact rendered driver command from step 1 using:

```javascript
const started = await tools.exec_command({
  cmd: renderedDriverCommand,
  workdir: "/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex",
  login: false, tty: true, yield_time_ms: 1000
});
```

`renderedDriverCommand` must contain the approved full SHA and the single
recorded absolute evidence path; do not rely on variables from another tool
shell. Keep the returned `session_id` in the external ledger. The command runs
in its original foreground PTY after the tool yields; the service keeps stdin
open. Yielding is not EOF. Poll only that session with `chars: ""` (no input):

```javascript
const observed = await tools.write_stdin({
  session_id: driverSessionId, chars: "", yield_time_ms: 1000
});
```

Observe actual stdout `READY`, verify durable ready.json and record the time
before native work. Check that the tool still reports the same running session.
Do not queue FINISH, inject a blank line, type shell commands into it, send Ctrl-D,
or close the session. Never start a second driver to obtain another baseline.
After step 5's original quit evidence, PID correlation and stopped verification,
send exactly one line to that same returned session:

```javascript
const completed = await tools.write_stdin({
  session_id: driverSessionId, chars: "FINISH\n", yield_time_ms: 1000
});
```

If it remains running, poll with empty `chars` until exit; do not resend FINISH.
Record original exit code, DONE and durable result.json. On cancellation send
`CANCEL\n` once instead, then poll. Cancellation discards the host baseline,
never quits Kodi and never produces a preservation comparison. After exit the
PTY is closed by the tool; retain the evidence, remove no historical artifacts.
There is no FIFO/holder to remove and no private baseline file to clean up.
EOF, controller loss or the 900-second driver timeout is INCONCLUSIVE, not a
recoverable baseline. Do not signal Kodi or fabricate FINISH. Any unresolved
native closure needs the separate authority described below.

Offline replay commands (harmless fixtures only) use the unchanged guard:
`tools/offline_test_suite.py --verbose tests.test_a15_finish_channel.rehearse_finish`
(or `.rehearse_cancel`, `.rehearse_eof`, `.rehearse_timeout`), with the pinned
interpreter and DEVELOPER_DIR. Use the same PTY tools; send FINISH/CANCEL only
after READY. EOF is a test-only Ctrl-D; the timeout fixture uses an injected
0.3-second stub deadline. Production WAIT_SECONDS remains 900. These fixtures
hold only an object in memory, exercise no acquisition/native API and do not
qualify real state preservation.

## One executable sequence, with an external ledger

Use two coordinated execution surfaces: one foreground trusted host process,
kept alive throughout, and the existing supported Test.app control. No daemon,
saved private baseline, extra driver, or new trust mechanism is needed.

1. Record the approved full host commit, old stage manifest path/hash, trusted
   helper/wrapper hashes, command, environment, external controller/foreground
   session handle and UTC start. Verify Git/index/source and all preconditions.
   Set `A15_REVIEWED_SHA` to the explicitly approved full SHA, and `A15_RUN` to
   one new unused absolute direct child of this worktree's qualification folder.
   Neither is a target override. From the exact worktree run:

   ```sh
   DEVELOPER_DIR=/Library/Developer/CommandLineTools \
   /Users/eengert/.pyenv/versions/3.10.9/bin/python3 -B \
     -m tools.bm_preservation_driver \
     --host-commit "$A15_REVIEWED_SHA" \
     --manifest /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/item8-a11-auto-keep-staging-20261104/stage-20261104T211724Z-a5a4a23b026e/stage_manifest.json \
     --evidence-dir "$A15_RUN"
   ```

   Use a trusted interpreter, startup/import environment and host bytecode;
   `-B` prevents cache writes, not reads. Keep stdin open and empty; do not pipe
   prequeued FINISH. The driver does stopped/source/public admission and its
   fresh single-process `begin()`. Observe stdout READY and durable ready.json,
   verify its host/manifest/staged identities and record observation time.
   READY is not permission to execute; the separate native task supplies that.
2. Only after observed READY, invoke supported `test_app_launch` once. Record
   its timestamped call/result, then immediately obtain the authoritative PID
   through the existing read-only helper before any UI action:

   ```sh
   DEVELOPER_DIR=/Library/Developer/CommandLineTools \
   /Users/eengert/.pyenv/versions/3.10.9/bin/python3 -B \
     tools/bm_test_app.py identify --output "$A15_RUN/launch-identity.json"
   ```

   Require exact bundle, `running_portable`, `portable_flag=true`, one target
   process, and no foreign-process refusal. Record the returned PID as the launch
   PID; the MCP tool name or an assumed PID is not evidence. This does not verify
   HTTP authentication/listener ownership. No independent census or relaunch.

   Keep the original driver session alive. Its 900-second wait deadline starts
   at READY/wait_signal, not at launch or when convenient. Record a controller
   host `time.monotonic()` reading immediately before the initial exec_command;
   use that earlier instant as the conservative budget origin (including admission
   time), since the exact internal wait start is not exported. Reading monotonic
   time with the pinned interpreter needs no Kodi/process probe. A late READY
   observation or empty-input poll must never grant another 900 seconds. Plan
   navigation in advance from the retained fixture observations. A budget is 90 s
   for launch/identity, 540 s for UI/review/rejection, and 150 s for quit/correlation,
   leaving 120 s reserve. These are planning limits, not assurances or a sub-minute
   preservation target. At each checkpoint record elapsed/remaining time. With
   less than 150 s remaining, do not begin another UI confirmation; close only
   under retained safe authority and cancel rather than racing the deadline.
   After FINISH, the comparison has its existing bounded reads; do not claim
   that the 900-second signal deadline bounds all later filesystem work.
3. Through supported `test_app_observe` and `test_app_navigate`, perform the
   ordinary Create UI sequence from the retained conflict contract. Record its
   full review: existing name/version, legitimate different public software
   content, skin/private scope excluded and no unintended configuration or
   package action. Confirm Create exactly once only if the entire review fits.
   Record the actual visible content-conflict rejection (localized string 32733)
   and acknowledgement. A chooser, receipt or comparison alone is insufficient.
   Do not perform a second Create, Apply, Install, Repair or recovery.

   **Required UI-exit gate (K1), before step 4:** after the rejection has been
   observed and acknowledged, call `test_app_observe({})`. Back out of Build
   Manager's remaining dialogs, results, menus and overview with
   `test_app_navigate({"direction":"back"})`, one action per call. After each
   Back, call `test_app_observe({})` and inspect the exact-target image/state.
   Continue only along an understood, non-mutating back-out path until the Kodi
   add-on list or home screen is visibly displayed, with no Build Manager dialog,
   result, menu or overview remaining open. Sending Back alone is not evidence
   of exit; record `UI_EXIT_VERIFIED` only from that observed outside-BM state.
   No additional Create confirmation, settings change, installation or Build
   Manager operation is allowed. Do not invent a Home/close control or send blind
   batches of navigation. Keep all navigation and observations within the original
   900-second budget; UI exit does not reset it or extend the quit reserve.

   Record the ordered Back/observe calls, their UTC start/end times, the observed
   outside-BM screen and its evidence reference, launch-PID correlation, and
   elapsed/remaining budget in the external run ledger. If an unexpected dialog,
   confirmation, ambiguous screen, unsupported control, unavailable image or
   unresponsive Back prevents safe verified exit, stop the normal sequence,
   preserve evidence and report INCONCLUSIVE. Do not proceed to prequit identity,
   authenticated quit or FINISH while UI exit remains unverified. Send CANCEL once
   only if the original driver still responds, solely to dispose its baseline;
   otherwise its bounded timeout applies. Any unresolved running Test.app process
   requires separately authorized recovery; this branch grants no fallback quit.
4. Only after `UI_EXIT_VERIFIED`, immediately before quit, use the same supported
   read-only `identify` command
   with a fresh `prequit-identity.json` output and require the same launch PID,
   bundle and running portable state. Any ambiguity stops further action.
   Then gracefully quit through the existing trusted helper's authenticated,
   PID-bound HTTP path, retaining its original fresh `quit.json` in the same
   protected evidence folder. The accepted Keychain wrapper command form is:

   ```sh
   DEVELOPER_DIR=/Library/Developer/CommandLineTools \
   /Users/eengert/.pyenv/versions/3.10.9/bin/python3 -B \
     tools/bm_test_app_keychain.py quit \
     --rpc-host 127.0.0.1 --rpc-port 8080 --rpc-user kodi \
     --timeout 60 --output "$A15_RUN/quit.json"
   ```

   This is the single authorized HTTP quit invocation, not a prelaunch probe.
   Authentication and listener PID ownership are first proved here, after launch,
   by the unchanged helper. `--timeout 60` bounds its post-acknowledgement shutdown
   wait; existing HTTP/process operations have their own bounds, so reserve time
   for the complete command and receipt checks. Never silently raise the timeout.
   Require exit 0, ok=true, graceful=true, authenticated=true, verified listener
   ownership, exact bundle and identity_before/invocation PIDs equal to the recorded
   launch PID, accepted/exited shutdown, no forced termination and identity_after
   not_running/count=0. Successful HTTP shutdown and `graceful=true` do not prove
   the add-on script was never force-stopped internally by Kodi. The verified
   UI-exit gate is separate evidence; it does not turn the receipt into a script-
   lifecycle attestation. The prequit check is not atomic with the helper; the helper
   independently binds/rechecks its actual PID for RPC and receipt correlation
   still must match. Never invent an unsupported expected-PID CLI option.

   After a successful quit, independently use the read-only helper commands
   below before FINISH. These do not enumerate an add-on inventory or settings:

   ```sh
   DEVELOPER_DIR=/Library/Developer/CommandLineTools \
   /Users/eengert/.pyenv/versions/3.10.9/bin/python3 -B \
     tools/bm_test_app.py identify --output "$A15_RUN/final-identity.json"
   DEVELOPER_DIR=/Library/Developer/CommandLineTools \
   /Users/eengert/.pyenv/versions/3.10.9/bin/python3 -B \
     tools/bm_test_app.py verify --manifest "$A15_MANIFEST" \
     --repo /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex \
     --output "$A15_RUN/final-source.json"
   ```

   `A15_MANIFEST` is the exact same absolute manifest path recorded at READY;
   render all variables consistently in each new tool command. Require exit 0,
   not_running/count=0 and installed-equals-manifest/candidate plus checked/ok Git
   binding. Neither command is a retry after a failed admission: on either
   refusal stop immediately. The driver separately repeats stopped/public/source
   admission after FINISH. Receipt syntax alone does not prove this interval.

   On authentication, listener/PID binding, quit rejection, timeout, nonzero exit,
   uncertain output or final admission failure: stop native/UI/RPC actions, record
   the precise sanitized stage and whether running state is known or UNKNOWN,
   and preserve the original result/exit. Do NOT send FINISH. If the original
   driver session still responds, send CANCEL once solely to dispose its private
   baseline; otherwise allow its bounded timeout and report loss. Do not retry
   quit, use another transport/MCP quit as a workaround, send a signal, manually
   repair state or claim shutdown. Test.app may remain running. Closure/recovery
   requires separately authorized target-specific action after Supervisor review;
   no emergency or fallback closure authority is implied by this procedure.
5. Correlate the original quit invocation/receipt, PID and UTC times with READY,
   launch, UI review/confirmation/rejection and the still-live driver session.
   Require the stop/source observations to belong to this interval. Send exactly
   one `FINISH` newline to that same foreground process. It validates receipt,
   rechecks host source, stopped/public state, invokes `finish()` at most once,
   compares all five projections and separate public witnesses, and disposes
   the session. Record exit status and durable result.json, not just DONE.
6. Seal ready/result/quit artifacts, external run ledger, bounded native UI
   evidence, source authority and the sanitized assessment together. A copied
   receipt with refreshed mtime or zero-native-activity window can satisfy the
   driver's structural checks, so receipt syntax/mtime alone cannot establish
   launch, UI execution or graceful exit. External trusted correlation remains
   mandatory; do not claim nonce-bound or machine-authenticated UI provenance.

## Minimal external run ledger

Retain a protected, sanitized ordered ledger with the exact host/source/manifest
identities; rendered commands and environment; original driver PTY session ID;
observed READY time and ready.json identity; each timestamped MCP action/result
needed to establish the review, one confirmation and rejection; launch identify
PID/bundle/portable-state result; observed `UI_EXIT_VERIFIED`, its outside-BM
screen/evidence and Back/observe UTC timing; prequit identity/PID result; the actual
original
quit command, start/end/exit and its authenticated PID/listener/shutdown facts;
final stopped/source result; the single FINISH or CANCEL send time and exact
session ID; and driver DONE/exit/result. Include elapsed/remaining 900-second
budget at native checkpoints. Record UNKNOWN instead of filling gaps. Protect
UI evidence and omit unrelated inventories/private values. Correlate the actual
observations in order; a successful form/mtime check is not native attribution.

## Predetermined outcome and stop rules

- **PASS (narrow A15 scenario):** complete correlated native conflict evidence,
  expected rejection, verified UI exit before quit, fresh stopped/source
  verification, all five strict scopes
  and separate public witnesses PRESERVED, no unsafe transaction/hold/publication
  or unrelated mutation. Report the Addons33 and full-profile limitations.
- **FAIL (native behavior):** a demonstrably wrong conflict result (for example
  unexpected success/overwrite), or independently established harmful/unexpected
  mutation caused by the operation. Preserve evidence; no corrective retry.
- **Strict difference mapping:** the unchanged driver reports `state=INCONCLUSIVE`,
  `reason=changed`, nonzero exit when either semantic/public equality differs.
  The underlying `CHANGED_OR_MISSING` stays authoritative, but is not by itself
  a native-behavior FAIL or proof of BM-caused damage. Do not report it as PASS.
- **INCONCLUSIVE:** any unsupported/unstable acquisition, missing correlation,
  process/source uncertainty, process loss, timeout, incomplete cleanup or any
  semantic/public difference whose qualification/causal meaning is unresolved.
  Known or plausible maintenance remains a strict difference and cannot satisfy
  this procedure's exact-preservation PASS. A prelaunch refusal means no native
  scenario occurred; report the reached gate without guessing.

Normal Kodi shutdown can increase uptime; UI work may also change texture or
view state. Thus a useful honest result may be INCONCLUSIVE. Do not shorten,
repeat, alter settings or omit fields merely to obtain equality. The procedure
may advance failure-path evidence without closing A15.

CANCEL/EOF/timeout/host-process loss consumes or loses the private session and
never controls Kodi or authorizes retry. An unverified UI exit remains subject
to step 3's K1 stop rule: no authenticated quit or FINISH, and any unresolved
running target needs separately authorized recovery. Otherwise, before any failed
quit/admission, the separate native task may still authorize its one graceful
quit with retained
exact target/control authority; a lost comparison cannot become PASS. After a
quit or trusted admission failure, step 4's no-retry/separate-recovery-authority
rule controls. Do not force termination or improvise recovery. On a Create or
state error stop actions and preserve evidence. No baseline may be reconstructed
from hashes or persisted private data.

This procedure does not qualify A11, whole-profile preservation, global writer
exclusion, deferred D-030 lifecycles, publication or macOS beta acceptance.
