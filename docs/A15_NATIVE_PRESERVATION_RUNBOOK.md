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

For the strict comparison, any difference stays `CHANGED_OR_MISSING`, and proven
maintenance never turns it into `PRESERVED`. D-032 (2026-11-15) adds a separate
practical verdict, defined in "Practical beta preservation contract (D-032)" below.
It may classify only the closed maintenance classes M1 and M2, and only through a
reviewed in-memory comparator. An offline comparator (`tools/bm_practical_preservation_comparator.py`)
is implemented, but it is not integrated into any driver and has not passed independent
qualification review. The strict result is
unchanged by that decision. No monitoring service or private baseline persistence
is needed or authorized by this contract.

## Practical beta preservation contract (D-032)

Approved by Eric on 2026-11-15 for personal beta readiness. This section defines
an additional practical verdict. It does not run, authorize or accept any native
task, does not change the N6 strict comparison, does not integrate the offline
comparator into any driver, and adds no native comparison subsystem.

### Relationship to the strict comparison

- The N6 strict results (`PRESERVED`, `CHANGED_OR_MISSING`, the five projections,
  the public witnesses and the driver's `state` and `reason`) are always reported
  exactly as produced. They are never rewritten, normalized or relabelled.
- Practical beta acceptance is judged by the practical verdict below. Byte-for-byte
  equality of an entire Kodi session is not required for that verdict. Every
  strict difference must still be classified. None may be ignored or waived.

### Protected scopes and current witnesses

| Scope | Protected meaningful content | Current witness | Stated limitation |
| --- | --- | --- | --- |
| S1 Saved builds and library | Build Library registry, saved entries, selection | Public snapshot equality (library root, registry, selection) and the `build-library` tree digest | Digest equality only; no semantic read of build contents |
| S2 Artifacts and associations | Frozen artifacts, applied association, install resolutions | `frozen-artifacts` and `install_resolutions` tree digests; applied association equality | Digest equality only |
| S3 Configuration and meaningful settings | `guisettings.xml` leaves outside M1, keyboard peripheral strings, Estuary settings, active skin, updater policy | The five projections (texture rows are S5) and the public `settings` fields | Only the five listed files are compared |
| S4 Supported add-on resources and private settings | Managed add-on data and structured private resources | None in the A15 driver | UNVERIFIED unless the scenario can touch it; must be stated |
| S5 Relevant databases | Addons33 installed identity and enabled state; Textures13 (cache, see M2) | Addons33 `installed.addonID,enabled` only; Textures13 exact schema and typed rows | Other Addons33 content is UNVERIFIED; Textures13 is cache, not user data |
| S6 Unmanaged add-ons and unrelated configuration | Unmanaged add-on directories and their settings; unrelated files | Addons33 identity and enabled state only | No unmanaged directory census and no unrelated-file witness; an open gap |
| S7 Transaction and recovery safety | No BM frozen-install, restart, capture or hold record; no pending publication; verified quit and stopped state | Owner-absence checks, `pending_publication`, quit receipt, fresh stopped and source verification | Does not prove the absence of unrelated external writers |
| S8 Source installation during capture | Kodi application add-ons and BM product trees | Stage verification (`installed_equals_candidate`, Git binding) before and after | No separate native source-tree census in the A15 driver |
| S9 Receiving installation during application | Receiving-profile data in S1 to S6 during an install, update or repair attempt | The same witnesses before and after the attempt | Scenario-specific; a rejected conflict is expected to change nothing |

A scope with a stated limitation is reported in the verdict. It may be left out of
the PASS basis only when the authorized operation cannot touch it by design, and the
ledger records that reasoning. Otherwise it is INCONCLUSIVE until witnessed.

### Ordinary maintenance classes (closed list)

- **M1, uptime counter:** `general/systemtotaluptime` in `guisettings.xml`. Shutdown
  adds frame-clock minutes (`CApplication::Stop`), and `CSysInfo::Save` writes the
  value (N6). Only the value of this leaf may differ. A structural change to that
  element is MEANINGFUL.
- **M2, texture cache metadata:** `Textures13` `sizes.usecount`, `sizes.lastusetime`
  and `texture.lasthashcheck` values, plus cache row creation and eviction. The
  classes are `M2_SIZES_USECOUNT`, `M2_SIZES_LASTUSETIME`, `M2_TEXTURE_LASTHASHCHECK`,
  `M2_CACHE_ROW_CREATE`, `M2_CACHE_ROW_EVICT`, `M2_CACHE_SIZES_CREATE` and
  `M2_CACHE_SIZES_EVICT`. A sizes row is maintenance only when its parent texture row
  is created or evicted in the same comparison (D-032 clarification, 2026-11-17).
  Allowed only when the schema is exact and every pre-existing texture row that
  remains keeps identical `url`, `cachedurl` and `imagehash`. Row counts are reported.

Everything else is MEANINGFUL: all other leaves, view-state and event-log state
(user configuration), skin, peripheral and Addons33 changes within their witnessed
fields, every public-witness difference, any change to a pre-existing texture
row's identity fields, and any sizes row added or removed beneath a retained texture
row. A class is never extended by inference from names,
timestamps, a writer's presence in Kodi source, or a matching control run.

### Offline comparator and practical qualification mechanism

The current driver exports per-file equality and `maintenance_attribution=UNKNOWN`,
and it cannot classify a difference without exporting field deltas, which N6
forbids. The two parts of the mechanism below have different status:

- **Implemented offline, not reviewed for qualification:** the pure comparator in
  `tools/bm_practical_preservation_comparator.py`, with its synthetic tests. It is
  not integrated into the A15 driver or any native task, and its output is not a
  native practical verdict.
- **Not integrated and not reviewed:** the practical qualification mechanism that
  would feed comparator results into the PASS, FAIL and INCONCLUSIVE verdict and
  the native ledger.

Until the practical qualification mechanism is integrated and independently
reviewed, every strict five-file difference is MEANINGFUL-unclassified for the
practical verdict, and the practical verdict cannot be PASS.

Required properties of the comparator:

- An in-memory comparator run only on the existing private before and after
  projections of the five files. For each file it returns `EXACT`,
  `MAINTENANCE_ONLY` with the class names and counts, or `MEANINGFUL` with a count.
  It returns no paths, values, row identifiers or value digests.
- Positive controls: an M1-only change; M2 `usecount`, `lastusetime` or
  `lasthashcheck` changes; M2 texture row creation and eviction with identities
  kept; sizes rows created or evicted together with their parent texture in the same
  comparison. Each must yield `MAINTENANCE_ONLY` with the correct class.
- Negative controls, each of which must yield `MEANINGFUL`: any other guisettings
  leaf; a structural change to the M1 element; an M1 change combined with another
  leaf change in the same file; a Textures13 schema change; a changed `url`,
  `cachedurl` or `imagehash` on a pre-existing row; a sizes row added or removed
  beneath a retained texture row. A non-exact Textures13 schema in the baseline is
  rejected, never maintenance-only.
- Output tests: the comparator output must contain no paths, values or digests.
- Rejection: a caller's Mapping that fails during iteration or lookup yields
  `ComparatorRejected` with a fixed reason code and no caller text. `BaseException`
  is deliberately not caught. This does not clear exception context a caller holds.
- Independent review of the comparator and its tests before any native use.

### Practical verdict

**PASS (practical)** requires all of the following:

1. The authorized operation's expected result and its fresh ledger correlation are
   verified, as in the N6 narrow-scenario PASS.
2. S7 holds after stop: no BM transaction, hold, restart or capture record, no
   pending publication, and no residual unsafe state.
3. S1, S2 and the S5 Addons33 identity and enabled state match exactly under the
   public witnesses. Each of the five projections is `EXACT` or `MAINTENANCE_ONLY`
   from the reviewed comparator, and none is `MEANINGFUL`.
4. Each stated limitation for S4, S5, S6 and S8 is reported. The PASS basis explains
   why an unwitnessed scope cannot be touched by the authorized operation.

**FAIL (practical)** requires independently established evidence, correlated to the
operation, of any of the following: a wrong operation result (for example an
overwrite or a success where rejection is expected); BM-caused loss, overwrite,
truncation or deletion of meaningful content in S1 to S6; BM-caused unsafe
transaction, hold or publication residue; an unrelated mutation, including of an
unmanaged add-on; or exposure of secret or private values. A strict difference alone
is never FAIL. Preserve the evidence and do not retry.

**INCONCLUSIVE (practical)** is the result when any of the following holds: a
MEANINGFUL or unclassified difference; a scope the operation could touch has no
witness; acquisition is unstable or unsupported; correlation is missing or broken;
the process was lost, timed out or cleaned up incompletely; or the comparator is not
yet reviewed. A matching control run is not causal proof and cannot upgrade or
downgrade a result.

### Limits and acceptance

This contract does not establish whole-profile preservation, global writer
exclusion, complete Addons33 or unmanaged add-on verification, the D-030 deferred
lifecycles, publication, public-product qualification or macOS beta acceptance. A
practical PASS for A15 requires the reviewed comparator, a separate task naming the
one scenario, sealed native evidence, and independent review of that evidence. Until
then A15 is not accepted.

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

### Prepare input and timing before READY

Have the exact public conflict inputs ready before starting the driver:
`BM-ITEM8-INSTALL-20261015`, version `1.0.0`, and the reviewed distinct public
root `metadata.generic.albums` at `1.0.20`. Reuse the accepted fixture admission;
these strings do not replace current source/artifact/fixture checks. Do not
rename the build or change its version to make entry faster: that would avoid
the intended same-identity conflict. Preserve the reviewed excluded skin/private
scope and zero public configuration scope.

The supported MCP navigation interface offers only Back, directional movement
and Select, one action per call; each navigation call includes a 1.2-second
settle and an image. It has no text-entry, paste or arbitrary RPC interface.
For the next separately authorized native attempt, prefer an explicitly scoped
operator-assisted input step: the operator types the exact public name and version
into the ordinary Kodi input dialogs using the physical keyboard. Physical entry
is proposed and not yet natively verified; operator participation requires explicit
authorization in a future task. Arrange operator availability before READY; do not
wait indefinitely during acquisition. No shell typing, clipboard injection,
credential path or new automation is implied.

**Verified keyboard-focus gate (B-1), for each input dialog:** the controller must
show the operator a fresh exact-target MCP observation of the intended Kodi input
dialog. The operator must confirm at OS level, without clicking inside Kodi's
content area, that the foreground application is the authorized disposable
`/Applications/Kodi Build Manager Test.app`. Explicitly confirm that the driver
terminal or PTY, normal Kodi and all other applications are not focused. MCP
launch does not establish foreground focus: it returns focus to the prior app.
Only after both observation and operator confirmation may physical entry begin.
No MCP navigation is permitted while the operator is typing; use one actor at a
time. The operator must never type into the foreground driver terminal or PTY:
after READY, stray input can refuse the driver with `protocol_invalid` and dispose
its baseline. The operator must acknowledge completion, then the controller must
obtain a fresh exact-target observation of the entered field before further action.
Record both confirmations and bounded UI evidence references in the external
ledger. If any focus requirement is unavailable or ambiguous, do not type; use
the abandonment path below.

**Unconditional name/version gate (B-2):** enter the name
`BM-ITEM8-INSTALL-20261015` first. Every name edit calls `suggest_version`, which
replaces the version and can reset this fixture to `1.0.1`. Open the version
dialog afterward, clear the prefilled version completely, and enter exactly
`1.0.0`, applying the keyboard-focus gate to that dialog too. Verify both exact
name and version in a fresh exact-target observation of the returned Create menu
before review. Repeat this verification after EVERY subsequent name or version
edit; a subsequent name edit requires opening, clearing and setting the version
again before verification. Never confirm Create without verified exact name and
version and the full intended review. Incorrect input takes the abandonment path;
do not improvise corrective edits during this attempt.

Record host UTC start/end and monotonic elapsed/remaining time for READY,
launch/identity, each navigation/observation or operator-input interval, completed
name/version, component selection, final review, rejection, UI exit, prequit,
quit and FINISH/CANCEL. Keep actual durations separate from estimated remaining
work. A screenshot clock, call count or predicted overrun is not a measured
deadline expiry. Use measured progress to decide whether the remaining review,
verified UI exit and complete shutdown sequence fit the existing reserve; if
they do not, take the abandonment path below. Retain the 900-second
deadline and existing 150-second no-new-confirmation cutoff. No extension is
justified by the prior attempt, which reached no submitted name or confirmation.

### Incomplete-scenario abandonment (B-3)

If keyboard assistance is unavailable or ineffective, focus verification fails,
input is incorrect, or remaining time is insufficient, stop entering text and
performing Create actions. Do not confirm Create or switch to the remote
keyboard-grid route or any alternative input mechanism. Apply the accepted K1
back-out procedure even when no rejection was observed: one supported
`test_app_navigate({"direction":"back"})` action, then
`test_app_observe({})`, inspecting each exact-target image. Continue only along
an understood, non-mutating path until an outside-Build-Manager add-on list or
home screen is positively verified. Record `UI_EXIT_VERIFIED`, UTC/elapsed time
and bounded evidence references; sending Back does not establish exit.

Dispose of the original driver baseline with exactly one CANCEL if the session
still responds; otherwise its existing bounded timeout applies. Never send FINISH
for an incomplete scenario. Preserve evidence and report INCONCLUSIVE regardless
of whether subsequent authorized shutdown succeeds. CANCEL never quits Kodi.

Only after verified UI exit, and only if the future native task explicitly
authorizes shutdown on abandonment and enough time remains, apply step 4's
unchanged prequit identity and authenticated, PID-bound shutdown rules, including
launch-PID correlation and final stopped/source checks. Then stop; do not proceed
to step 5 or reuse the disposed baseline. This is no fallback authority and grants
no quit after a refused admission. If safe UI exit, current identity, sufficient
shutdown time or authorized shutdown cannot be established, stop the normal
sequence and require separately authorized recovery. An unexpected dialog,
confirmation, ambiguous screen or unsupported control stops back-out immediately.
Tell the operator: **Test.app may still be running; no automated shutdown has
been established. Leave Test.app and Kodi untouched until Supervisor disposition.**
Do not retry, switch quit transports, or infer shutdown from CANCEL.

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

   In particular, `esrch_confirmation / pending_pid_present` means a failed
   kernel executable lookup reported ESRCH but its PID appeared in the one fresh
   confirmation census. It is not proof of a harmless exit, a known background
   process or PID continuity. Preserve the refusal; do not repeat admission,
   independently enumerate, or use a second name/path lookup to force success.
   No independently authenticated fallback closure is established by this runbook.
   Immediately tell the operator: **the test stopped; Test.app may still be
   running; CANCEL only disposes the baseline; do not wait for automated quit.
   Leave Test.app and Kodi untouched until Supervisor disposition.**
   Request separately authorized manual closure of this exact Test.app through
   its normal GUI after Supervisor disposition, without repair, signals or other
   Kodi access. Record an eventual operator closure report as such, not as an
   authenticated stopped-state result. A future task needs its own fresh admission;
   manual closure cannot rescue this cancelled run or authorize FINISH.
5. Correlate the original quit invocation/receipt, PID and UTC times with READY,
   launch, UI review/confirmation/rejection and the still-live driver session.
   Require the stop/source observations to belong to this interval. Send exactly
   one `FINISH` newline to that same foreground process. It validates receipt,
   rechecks host source, stopped/public state, invokes `finish()` at most once,
   compares all five projections and separate public witnesses, and disposes
   the session. Record exit status and durable result.json, not just DONE.
6. After the session is disposed, perform only the separately authorized bounded
   capture-marker assessment below; never reopen a session or retry Create for
   missing diagnostics. Seal ready/result/quit artifacts, external run ledger, bounded native UI
   evidence, source authority and the sanitized assessment together. A copied
   receipt with refreshed mtime or zero-native-activity window can satisfy the
   driver's structural checks, so receipt syntax/mtime alone cannot establish
   launch, UI execution or graceful exit. External trusted correlation remains
   mandatory; do not claim nonce-bound or machine-authenticated UI provenance.

## Capture-refusal log observability (staging prerequisite)

This procedure is for a separately authorized native run, not permission to read
logs during documentation review or staging. The native task must explicitly
include the bounded prelaunch/post-run log reads below. Staging may proceed after
review of this procedure and the diagnostic candidate; actual native emission
remains **UNVERIFIED** until observed in that future run.

**Select only the portable log.** For the admitted fixed target the source is:

```text
/Applications/Kodi Build Manager Test.app/Contents/Resources/Kodi/portable_data/temp/kodi.log
```

`docs/BM023A_MACOS_TEST_RUNTIME.md` distinguishes the original portable
`temp/kodi.log` from the replacement isolated-HOME runtime's
`<HOME>/Library/Logs/kodi.log`; `docs/TESTING.md` describes the latter harness
mapping too. Those HOME-based harness paths are not this portable `-p` target.
Do not search other log directories, use normal Kodi logs, or fall back to
`kodi.old.log` or an archived log when this source cannot be proved.

Use the existing `tools.bm_test_app` Python interfaces with the unchanged approved
configuration: `Services.production().target`, `target.portable_data / "temp" /
"kodi.log"`, `target.require_chain(path)`, then
`read_regular_file(path, 64 * 1024 * 1024)`. Require the constructed path to equal
the fixed source above, and check the chain again after reading. The reader is
bounded, read-only, final-component no-follow and verifies file identity, size
and modification-time stability. Refuse symlinks, non-regular files, oversized,
unreadable or changing inputs; do not truncate or retry a refused read. This is
an explicitly scoped log read, not a new five-file bridge projection or an
expansion/bypass of `ReadGuard`'s public-state allowlist. Never feed logs to the
preservation comparator.

**Bind source and freshness to the run.** After successful stopped/source
admission and before READY/launch, take one bounded read using those interfaces.
Keep raw bytes only in memory. Record file identity/size/mtime internally and
retain only the fixed marker/timestamp pairs needed to reject historical entries;
discard the raw bytes immediately. If the initial read is unavailable, refuse
this diagnostic run before launch rather than guessing the baseline. Correlate
with the external ledger's exact installed diagnostic commit, manifest, fixed
bundle, independently identified portable `-p` launch PID, confirmation and
shutdown interval. Path location alone is not proof of an authenticated writer.

After the native sequence has stopped Test.app, verified source and disposed the
original driver session with its prescribed FINISH or CANCEL, perform one bounded
read of the same fixed log. Do not delay quit/FINISH or consume the 900-second
budget to inspect logs. If shutdown or admission failed, do not read while the
target remains uncertain; use the existing recovery stop rule. Rotation,
replacement or truncation must not be treated as appended bytes: accept fresh
markers only if their full dated log timestamps unambiguously fall between this
run's recorded Create confirmation and shutdown, using the recorded host timezone
and UTC ledger, and were absent from the prelaunch marker set. Reject ambiguous
dates, clock discontinuities, historical matches or uncertain rotation as
INCONCLUSIVE; never substitute modification time alone for event freshness.

**Filter in memory; never print log lines.** Accept only a complete diagnostic
message of the form `[script.build.manager] diagnostic phase=create.capture.X`
after the ordinary Kodi timestamp/thread/log-level envelope, with no extra
message suffix. Match X against this exact allowlist, also checked against the
staged candidate's `failure_diagnostics.PHASES`:

```text
incomplete
capture_errors
incomplete_artifact
incomplete_provenance
invalid_package
unsupported
missing
dependency_cycle
builtin_closure_unavailable
metadata_unavailable
metadata_invalid
application_root_refused
builtin_requirement_incompatible
platform_requirement_unsatisfied
```

Discard all other messages and surrounding content without output. Retain only
the distinct allowlisted phase names, fixed source/freshness verification outcomes
and their correlation to the external run ledger. Do not retain raw bytes, raw
lines, headers, thread identifiers, private-value hashes or unrelated content.
The future run confirms emission only when it actually observes fresh allowlisted
markers; successful staging, offline tests or a missing marker cannot prove it.

**Outcome limits (32730 versus 32732).** The diagnostic covers incomplete capture
mapped to 32730. Preserve that user-facing result and the safe abandonment/CANCEL
flow if the intended 32733 conflict was not reached; diagnostic evidence cannot
rescue A15 qualification. Exceptions/FAILED outcomes mapped to 32732 may produce
no `create.capture.*` markers, including failures before the incomplete-result
boundary. A 32732 outcome, absent/inaccessible markers, or uncertain source or
freshness is INCONCLUSIVE for the intended capture diagnosis and requires separate
investigation, not a retry. Markers identify fixed categories, not necessarily a
particular node or builtin subcheck. Never infer a missing artifact, zero capture
side effects or successful preservation from either UI outcome or from markers.

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
UI evidence and omit unrelated inventories/private values. Retain bounded evidence
references for significant UI observations, including input dialogs, verified
name/version, full review, rejection or abandonment, and outside-BM exit. Include
operator OS-focus confirmations and completion acknowledgements in order.
Correlate the actual
observations in order; a successful form/mtime check is not native attribution.

## Predetermined outcome and stop rules

These bullets define the strict results only. The practical verdict is defined in
the D-032 section above and is reported separately. A strict difference does not by
itself decide the practical verdict; any part left unclassified is INCONCLUSIVE, and
a practical PASS never rewrites a strict result.

- **Strict PASS (narrow A15 scenario):** complete correlated native conflict evidence,
  expected rejection, verified UI exit before quit, fresh stopped/source
  verification, all five strict scopes
  and separate public witnesses PRESERVED, no unsafe transaction/hold/publication
  or unrelated mutation. Report the Addons33 and full-profile limitations.
- **Strict FAIL (native behavior):** a demonstrably wrong conflict result (for example
  unexpected success/overwrite), or independently established harmful/unexpected
  mutation caused by the operation. Preserve evidence; no corrective retry.
- **Strict difference mapping:** the unchanged driver reports `state=INCONCLUSIVE`,
  `reason=changed`, nonzero exit when either semantic/public equality differs.
  The underlying `CHANGED_OR_MISSING` stays authoritative, but is not by itself
  a native-behavior FAIL or proof of BM-caused damage. Do not report it as PASS.
- **Strict INCONCLUSIVE:** any unsupported/unstable acquisition, missing correlation,
  process/source uncertainty, process loss, timeout, incomplete cleanup or any
  semantic/public difference whose qualification/causal meaning is unresolved.
  Known or plausible maintenance remains a strict difference and cannot satisfy
  this procedure's exact-preservation PASS. A prelaunch refusal means no native
  scenario occurred; report the reached gate without guessing.

Normal Kodi shutdown can increase uptime, and UI work may change texture or view
state. Under the strict comparison, such differences remain differences. Under the
practical contract, only M1 and M2 may be classified as ordinary maintenance, and
view-state or other settings changes remain MEANINGFUL. Do not shorten, repeat,
alter settings or omit fields merely to obtain equality. The procedure may advance
failure-path evidence without closing A15.

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
