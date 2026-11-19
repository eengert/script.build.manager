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
reviewed in-memory comparator that is not implemented here. The strict result is
unchanged by that decision. No monitoring service or private baseline persistence
is needed or authorized by this contract.

## Practical beta preservation contract (D-032)

Approved by Eric on 2026-11-15 for personal beta readiness. This section defines
an additional practical verdict. It does not run, authorize or accept any native
task, does not change the N6 strict comparison, and does not add a comparison
subsystem.

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
  and `texture.lasthashcheck` values, plus cache row creation and eviction. Allowed
  only when the schema is exact and every pre-existing texture row that remains
  keeps identical `url`, `cachedurl` and `imagehash`. Row counts are reported.

Everything else is MEANINGFUL: all other leaves, view-state and event-log state
(user configuration), skin, peripheral and Addons33 changes within their witnessed
fields, every public-witness difference, and any change to a pre-existing texture
row's identity fields. A class is never extended by inference from names,
timestamps, a writer's presence in Kodi source, or a matching control run.

### Minimal verification mechanism (defined, not implemented)

The current driver exports per-file equality and `maintenance_attribution=UNKNOWN`,
and it cannot classify a difference without exporting field deltas, which N6
forbids. Until the mechanism below is implemented and independently reviewed, every
strict five-file difference is MEANINGFUL-unclassified, and the practical verdict
cannot be PASS.

- An in-memory comparator run only on the existing private before and after
  projections of the five files. For each file it returns `EXACT`,
  `MAINTENANCE_ONLY` with the class names and counts, or `MEANINGFUL` with a count.
  It returns no paths, values, row identifiers or value digests.
- Positive controls: an M1-only change; M2 `usecount`, `lastusetime` or
  `lasthashcheck` changes; M2 row creation and eviction with identities kept. Each
  must yield `MAINTENANCE_ONLY` with the correct class.
- Negative controls, each of which must yield `MEANINGFUL`: any other guisettings
  leaf; a structural change to the M1 element; an M1 change combined with another
  leaf change in the same file; a Textures13 schema change; a changed `url`,
  `cachedurl` or `imagehash` on a pre-existing row.
- Output tests: the comparator output must contain no paths, values or digests.
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

### Dated addenda (2026-11-17)

The text above this heading is the 2026-11-15 D-032 contract, restored byte for byte from commit `9f686dc`. Three later commits altered that wording in place: `a16c877` (the M2 sizes-row clarification), `a4509a5` (the offline wiring, which also reworded the mechanism section) and `6ee74a2` (the per-file class vocabulary). Those changes are recorded here as dated addenda instead. The earlier statement that all original D-032 text was unchanged was inaccurate for HEAD before this restoration.

Where an addendum adds to the historical text, the historical condition still applies unless the addendum states that it is met. No addendum authorizes native testing, a practical PASS, any change to the strict N6 comparison or qualification gates, publication, or integration to `matrix`.

#### A. M2 sizes-row lifecycle (approved 2026-11-17)

Eric approved the maintenance classes `M2_CACHE_SIZES_CREATE` and `M2_CACHE_SIZES_EVICT`, as recorded in the 2026-11-17 M2 clarification in `.orchestrator/DECISIONS.md`. A sizes row is maintenance only when its parent texture row is created or evicted in the same comparison. A sizes row added or removed beneath a retained texture row is MEANINGFUL. No other sizes lifecycle is accepted.

The closed M2 class list is now: `M2_SIZES_USECOUNT`, `M2_SIZES_LASTUSETIME`, `M2_TEXTURE_LASTHASHCHECK`, `M2_CACHE_ROW_CREATE`, `M2_CACHE_ROW_EVICT`, `M2_CACHE_SIZES_CREATE` and `M2_CACHE_SIZES_EVICT`.

Additional controls under this addendum:
- Positive: sizes rows created or evicted together with their parent texture row in the same comparison must each yield `MAINTENANCE_ONLY` with the correct class.
- Negative: a sizes row added or removed beneath a retained texture row must yield `MEANINGFUL`.
- Negative: a non-exact Textures13 schema in the baseline is rejected, never maintenance-only.

#### B. Offline comparator (implemented 2026-11-17; not reviewed for qualification)

The comparator exists as the pure, in-memory module `tools/bm_practical_preservation_comparator.py`, with synthetic tests in `tests/test_bm_practical_preservation_comparator.py`. The historical requirement for independent review before any native use still applies. Its output is a classification only, not a native practical verdict.

Additional properties implemented under this addendum:
- Inputs must use exact built-in `list` and `tuple` containers. Subclasses are rejected with the fixed code `unexpected_shape` (commit `28e33e3`).
- A caller Mapping that fails during iteration or lookup yields `ComparatorRejected` with a fixed code. `BaseException` is deliberately not caught.

#### C. Offline evidence wiring (retained 2026-11-17; commits `a4509a5` and `6ee74a2`)

Eric approved retaining the offline wiring, subject to the per-file class correction recorded in `.orchestrator/DECISIONS.md`. That approval supersedes only the restriction against comparator integration into a driver, stated in the 2026-11-17 M2 clarification. It does not authorize native execution, a practical PASS, any weakening of the strict N6 gates, publication, or integration to `matrix`.

The driver's strict export remains per-file equality with `maintenance_attribution=UNKNOWN`. It exports no field deltas, which N6 forbids.

Current implementation:
- The acquisition layer runs the comparator. The driver validates the block and never runs the comparator.
- `AcquisitionSession.finish()` classifies the same session's before and after projections of the five files with the comparator's `compare_file`. Each file is `EXACT`, `MAINTENANCE_ONLY` (class names and counts), `MEANINGFUL` (count) or `INCONCLUSIVE`. A comparator rejection, missing input or unexpected fault makes only that file `INCONCLUSIVE`. The output is the after result's `practical` block, with fixed file names, closed class names and integer counts. No private projection, path, value, row identity or digest is returned.
- The driver validates that block exactly: closed keys and names, counts, the aggregate, consistency with each strict per-file status, and the per-file class vocabulary. `M1_UPTIME` is valid on guisettings only. The approved M2 classes are valid on Textures13 only. No maintenance class is valid on Addons33, the Estuary settings or the keyboard settings. A valid block is written to `result.json` under `after.practical`, beside the unchanged strict fields.
- `tools/bm_practical_preservation_comparator.py` is in the driver's `HOST_PATHS`, so the host source binding covers it.
- The block's `verdict` is always `NOT_DECIDED`.

Correction to earlier wording. The earlier sentence "the strict gate never reads the practical block" was inaccurate. Three distinct facts apply:
1. Practical block validation is required for admission. The driver validates the block before it admits the acquisition result. A malformed block raises `finish_refused`, the run is recorded as `INCONCLUSIVE` with that reason, and the `after` block is not recorded.
2. The strict decision still uses only the original strict scope and public comparison. `scope_result` and the per-file statuses come from equality of the five projections, not from the practical classification. The strict state and reason remain `SCOPED_PRESERVED` / `scoped_comparison` only when the strict scope and public comparison both pass.
3. Practical classification never creates a PASS. The strict result constrains the classification: an unchanged projection may be `EXACT` or `INCONCLUSIVE`, and a changed projection is never `EXACT`. No classification produces a practical PASS, FAIL or INCONCLUSIVE verdict. The verdict remains `NOT_DECIDED`.

#### D. Strict and practical status are separate (2026-11-17)

`SCOPED_PRESERVED` and exit code 0 describe strict N6 scope preservation only. They are not a practical PASS. A strict `SCOPED_PRESERVED` may coexist with a practical `INCONCLUSIVE` classification, and the practical verdict remains `NOT_DECIDED`. Renaming a state or changing exit semantics is not authorized by this contract.

#### E. Current position of the practical verdict and native gates (2026-11-17)

- The practical verdict mechanism is not implemented. Operation and ledger correlation, the S7 after-stop condition, the S1, S2 and S5 public witness conditions, and the limitation reporting that a practical PASS requires are all absent.
- The historical conditional in "Minimal verification mechanism (defined, not implemented)" still applies. Until the mechanism is implemented and independently reviewed, strict differences remain MEANINGFUL-unclassified for the practical verdict, and practical PASS is unavailable. That condition is not met. The comparator's `MAINTENANCE_ONLY` results are classifications only and do not decide the practical verdict.
- Still unqualified:
  - independent review of the comparator and of the offline wiring;
  - the practical verdict mechanism, as listed above;
  - S1 to S9 preservation beyond the five projections, transaction closure and native acceptance;
  - a practical PASS for A15.
- Four statuses, which must not be merged:
  1. The comparator is implemented offline and is not reviewed for qualification. Its output is not a native practical verdict.
  2. The offline evidence wiring is implemented and retained for offline use only. It is not reviewed for qualification, and no native run has used it.
  3. The practical qualification verdict is not implemented. The block's verdict is always `NOT_DECIDED`.
  4. Native testing is not authorized or accepted.
- Native testing is not authorized or accepted by any addendum in this section.
- Dated clarification (2026-11-18). The 2026-11-17 status in this section is retained as historical. The offline precondition assessment (`tools/bm_practical_precondition.py`, commit `95b0d5d`) has since been added. It evaluates the available S1, S2, S5 and S7 evidence and five-file eligibility, and it lists its scope limitations explicitly (section F). The 2026-11-17 bullet that lists the S7 after-stop condition, the S1, S2 and S5 public witness conditions and the limitation reporting as absent is superseded for those offline checks only.
  - Completed offline: the prerequisite checks for S1, S2, S5, S7 and five-file eligibility, each `MET`, `NOT_MET` or `UNVERIFIED`, with unverified requirements and limitations listed.
  - Still missing: operation and ledger correlation; the expected-result check; scenario justifications for any exclusion of S4, S5 database coverage, S6, S8 or S9; and the final practical verdict logic.
  - The practical verdict remains `NOT_DECIDED`, and no practical PASS is available. The historical conditional still applies, because the practical verdict mechanism is not implemented. The offline review status of the comparator and wiring is recorded in section F; it does not change the independent-review requirement for native use.

#### F. Current status and practical precondition assessment (2026-11-17)

- Offline review status, by item. Provenance: these results were relayed through the manual Supervisor workflow. They are not repository-hosted review artifacts, and this repository does not contain the review reports.
  - Comparator: the D-032 B1 CORRECTION REVIEW returned PASS for candidate `28e33e3`, the exact list/tuple gate. That PASS covers the B1 correction only.
  - Offline evidence wiring (`a4509a5`, retained by `6ee74a2`): the earlier wiring reviews accepted the technical findings but returned NOT PASS for documentation. The D-032 HISTORICAL CONTRACT REVIEW returned PASS for candidate `13687f4`, and that resolved the documentation blocker. No separate wiring PASS report exists.
  - These are offline reviews only. They are not qualification reviews, they do not qualify any native behaviour, and they do not authorize a practical PASS, a native run, publication or integration to `matrix`. For offline review, this status supersedes the "independent review" item in section E; that item is unchanged for native use.
- Status record for the precondition assessment (`95b0d5d`):
  - Implemented offline in commit `95b0d5d`.
  - Under independent review. Its review, relayed through the same Supervisor workflow, returned NOT PASS on three documentation blockers only; the implementation was found technically sound. This correction addresses those blockers. No re-review verdict is recorded here.
  - Not accepted for native qualification.
  - Always `INCONCLUSIVE` / `NOT_DECIDED` in the current evidence flow.
- The comparator, the offline evidence wiring and the precondition assessment have separate review statuses. Do not merge them.
- Precondition assessment. `tools/bm_practical_precondition.py` implements an offline, fail-closed assessment. It reads only values the driver has already validated: the two public witnesses, the validated begin and after projections, and two driver facts. The driver records its result under `practical_precondition` in `result.json`, beside the unchanged strict result and `after.practical`. A run that does not reach the finish records `not_reached`.
- Scope-specific comparisons:
  - S1 compares the library census (root, registry and selection facts), the selection, and the `build-library` tree.
  - S2 compares the `frozen-artifacts` and `install_resolutions` trees and the applied association.
  - S5 compares Addons33 add-on identity, taken from the `addon.xml` census, and enabled state, taken from the `addons_db` source. It requires the Addons33 classification to be `EXACT`. The comparator's `EXACT` classification covers the approved Addons33 identity/enabled projection only; all other Addons33 content remains `UNVERIFIED`.
  - S7 requires a verified quit, source binding at both boundaries, owner absence and pending-publication absence at both boundaries, and an unchanged bundle identity.
  - Five-file eligibility accepts `EXACT`, and the approved `MAINTENANCE_ONLY` classes on their own files. `MEANINGFUL` prevents eligibility. `INCONCLUSIVE` leaves the requirement unverified.
- Each prerequisite is `MET`, `NOT_MET` or `UNVERIFIED`. A missing witness is `UNVERIFIED` and is never inferred. Malformed input yields `input_invalid`, and no prerequisite is treated as met.
- Unverified requirements are listed explicitly and are never assumed untouched: the operation's expected result, fresh operation and ledger correlation, and the limitations for S4, S5 database coverage, S6, S8 and S9. Any future exclusion needs a scenario that justifies it.
- The assessment is `INCONCLUSIVE` in every case in this implementation. It never emits a practical PASS or FAIL. Its `verdict` remains `NOT_DECIDED`, and its `qualification` remains `not_qualified`.
- Exception-context limitation. The comparator cannot clear exception context that a caller already holds in its own frames. Its rejections carry no caller text and are raised outside exception handlers, so the comparator adds no chained context. A caller's existing `__context__` or traceback remains outside this module's control.
- Four statuses, which must not be merged:
  1. The comparator is implemented offline and has the offline review status described above. It is not a qualification review, and its output is not a native practical verdict.
  2. The offline evidence wiring is retained for offline use and has the offline review status described above. No native run has used it.
  3. The practical verdict is not implemented. The precondition assessment is `INCONCLUSIVE`, and the `verdict` is always `NOT_DECIDED`.
  4. Native testing is not authorized or accepted.
- Still unqualified: the practical verdict mechanism itself (its decision logic, operation and ledger correlation, the expected-result check, and the witnesses or justified exclusions for S4, S5 database coverage, S6, S8 and S9); S1 to S9 beyond these checks; transaction closure; native acceptance; and a practical PASS for A15.

#### G. Addons33 byte-identity witness (approved 2026-11-19; offline implementation)

Authority and status. Eric approved this scenario-specific clarification on 2026-11-19, recorded in `.orchestrator/DECISIONS.md`. It is additive: the 2026-11-15 contract text and addenda A to F are unchanged. It is implemented offline only, has not had an independent review, and authorizes no native run, no practical PASS, no qualification and no beta acceptance.

Scope. The Create-conflict scenario of the 2026-11-18 addendum only: Create name `BM-ITEM8-INSTALL-20261015`, version `1.0.0`, root `metadata.generic.albums` `1.0.20`, private capture off, expected terminal `32733`. Any other scenario needs its own approval.

Mechanism. The existing acquisition session fingerprints the Addons33 main-file bytes it has already admitted at each boundary. `_capture` is unchanged in its admission, identity, sidecar-refusal, read-stability and source checks. It takes SHA-256 and byte length from the first of its two stable reads, and only after the second read matched. The session holds that fingerprint privately between `begin()` and `finish()`. It keeps no raw copy of the database and builds no new SQLite parser. The fingerprint is cleared on `close()`, on every failure path, on interruption, and when `finish()` consumes it. A lost or consumed fingerprint is never rebuilt, and nothing retries.

Supplemental containment (correction of 2026-11-19 after review). The fingerprint and its comparison are supplemental and cannot change strict N6. An ordinary exception (`Exception`, including `MemoryError`) raised only inside fingerprint generation or the byte comparison is contained: that fingerprint is treated as unavailable, or the block is built directly as `UNVERIFIED` without calling the failing helper again, and the admitted acquisition, the strict per-file statuses and the practical classification are reported exactly as without the fault. No exception text, digest or length is exported. `KeyboardInterrupt` and `SystemExit` are not suppressed. Nothing else is contained: a real snapshot instability, a sidecar or WAL header, a malformed or missing input, an admission failure, a source-binding failure or any other fault in the capture still fails closed through its original path.

Exported source. `result.json` `after.addons33_bytes` is a sibling of `after.practical`, with the closed shape `{schema: bm-a15-addons33-bytes/1, scope: addons33_file_bytes, status}`. `status` is exactly one of `BYTES_IDENTICAL`, `BYTES_DIFFERENT` or `UNVERIFIED`. No digest, length, path or database content is exported. The driver validates the block exactly and refuses the finish on a missing or extra key, on a `schema`, `scope` or `status` that is not an exact `str` (a `str` subclass or an object that merely compares equal is refused), on a wrong schema or scope, or on a status outside the vocabulary. The precondition assessment applies the same exact-`str` rule. `BYTES_IDENTICAL` must agree with the strict Addons33 status (`PRESERVED`) and with the Addons33 practical row (`EXACT` or `INCONCLUSIVE`), because identical bytes give an identical projection. `BYTES_DIFFERENT` may coexist with an unchanged projection and is not a contradiction.

Meaning.
- `BYTES_IDENTICAL`: the Addons33.db main-file bytes admitted at the begin and after boundaries had equal SHA-256 digests and equal lengths. This is strong evidence of byte identity at those two boundaries, and so of identical schema, rows and pragmas at them. Each boundary was read with Test.app not running, no `-wal`, `-shm` or `-journal` file present at either read, a legacy (non-WAL) header, and a byte-stable double read.
- `BYTES_DIFFERENT`: the bytes differ. This establishes nothing about meaning, cause, loss or harm. It is not FAIL, not a maintenance class and not MEANINGFUL, and it is not retried. S5 other-Addons33 content then stays unresolved.
- `UNVERIFIED`: a fingerprint was unavailable at either boundary (including an Addons33 main file that is absent at the after boundary, which the strict result reports as `CHANGED_OR_MISSING`), or an ordinary fault occurred only in the optional fingerprint or comparison. This status appears only in a successfully admitted `after` result, beside valid strict and practical evidence. It never replaces a refusal.
- Refused boundary: when a boundary itself is refused (a missing Addons33 main file at the begin boundary, an unstable or malformed snapshot, a sidecar or WAL header, a failed admission or source-binding check), no successful `after` block is exported, so there is no `after.addons33_bytes` and no byte status at all. The refusal reason is the evidence, and the result is INCONCLUSIVE, never FAIL.

Limits. The witness makes no assumption about writes between the two boundaries and does not exclude writers or attribute any change. It is not an atomic snapshot. It says nothing about S4, S6, S8 or S9, nor about files other than the Addons33 main file. Legitimate Kodi activity may produce `BYTES_DIFFERENT`. The retained 2026-10-08 tree censuses record an Addons33.db mtime change in one of two no-op Kodi sessions and none in the other, with unknown content. There is no Addons33 maintenance class, and adding one needs a separate approval. The strict N6 comparison is unchanged: `witness.SCOPES` still reads "installed.addonID,enabled ONLY", and the per-file statuses, `state`, `reason`, exit codes, the practical block schema and the `NOT_DECIDED` verdict are unchanged.

Precondition assessment and the scope gate. `tools/bm_practical_precondition.py` validates the block with the same grammar. A block that is missing, malformed, or contradicts the strict result makes the whole assessment `input_invalid`, and nothing is promoted. A valid block refines only the reason of the `S5_DATABASE` limitation entry, and that entry stays `UNVERIFIED` for every status: `addons33_bytes_identical_scenario_unauthenticated`, `addons33_bytes_differ` or `addons33_bytes_unverified`. The default reason `other_addons33_content_unverified` remains for a run that never reached the finish. A byte difference is never `NOT_MET`. The assessment has no authenticated scenario context: the driver neither receives nor verifies a scenario identity, and the caller-supplied `correlation` string is not authentication (section 4 of the 2026-11-18 addendum). The assessment therefore cannot promote `S5_DATABASE` to `MET`, and this change invents no flag to do so. Remaining gate: promotion inside the assessment needs a reviewed, authenticated scenario input, which does not exist. The overall assessment stays `INCONCLUSIVE` and `NOT_DECIDED`.

Adjudication use. For the approved scenario only, the independent adjudication of the 2026-11-18 addendum may treat `after.addons33_bytes.status` of `BYTES_IDENTICAL`, with its raw-record provenance under section 1.2 and the scenario identity in ledger entry L1, as the adequate witness for the S5 other-Addons33 disposition in section 2 and P8. `BYTES_DIFFERENT` or `UNVERIFIED` leaves that disposition unresolved, PASS unavailable and the result INCONCLUSIVE, never FAIL. This adds to the exported-fact table in section 1.6 a row: Addons33 main-file byte identity, `result.json` `after.addons33_bytes`.

Unchanged and open. S4 justification, S6, S8 and S9 dispositions, operation and ledger correlation, the expected-result check, reviews of the comparator, driver validator and precondition for the exact candidate, and every item under "Conditions still required before a native A15 run" remain open. `tools/bm_addons33_content.py` and its tests (commits `551da1f` and `1a06320`) are a superseded, unwired, unreviewed experiment, outside `HOST_PATHS`. The logical witness never received a PASS, and it is preserved as history.

### Dated addendum (2026-11-18): external practical adjudication, Create conflict only

Status. Documentation only. It authorizes no native test, Test.app launch or staging, profile access, practical PASS, qualification or acceptance. It records the direction of an independent Codex design review of the exact candidate, which returned PARTIALLY CONFIRMED. That review was relayed through the manual workflow and is not repository-hosted. Codex's adjudication review of commit `731b29b` returned NOT PASS on four blockers (execution provenance, ledger order and exports, S5 and S6 exclusion, and artifact-bearing dependencies). This revision corrects them, and it is subject to a narrow re-review. The driver's practical block stays `verdict = NOT_DECIDED`, and `tools/bm_practical_precondition.py` stays `INCONCLUSIVE`. This procedure is applied by an independent reviewer to retained evidence. It is not a ledger service, a signing or attestation service, a machine verdict engine or a driver change.

This follows D-032's requirement (2026-11-15, "Independent review and native evidence") for a separate authorized scenario, sealed native evidence and independent review of that evidence.

Scope. One scenario only: Create name `BM-ITEM8-INSTALL-20261015`, version `1.0.0`, root `metadata.generic.albums` `1.0.20`, expected terminal `32733`. Any other scenario needs its own addendum.

#### Source facts for this scenario

Checked against candidate `bbfbb7e` on 2026-11-18. Line numbers refer to that commit.

- Identity. `build_id` is `identity(name)`: a slug plus the first 12 hex digits of the SHA-256 of the stripped label (`resources/lib/create_workflow.py:27-34`). The name alone fixes the build identity.
- Conflict key. `BuildLibrary.register` raises `LibraryConflict("build_library_conflict")` only when an existing entry has the same `(build_id, build_version)` (`resources/lib/build_library.py:612-616`). The root add-on is not part of that key. The root does enter the captured bundle: its node, its dependencies and their artifacts form the frozen manifest. The root therefore changes the bundle content, the capture and the acquisition, but not the name-derived identity or the conflict key.
- Terminal mapping. `LibraryConflict` maps to `CreateTerminal(32733)` (`create_workflow.py:292-293`). With private capture off, `execute()` calls `register()` directly (`create_workflow.py:270-271`), so 32733 can then come only from the library conflict.
- Order. Frozen capture runs first (`create_workflow.py:218`; a second pass runs only after an explicit local-capture approval, line 224). Registration follows at line 271. An incomplete capture returns its category at line 232, before registration (for example 32730 for SOFTWARE_INCOMPLETE). So 32733 is reachable only after a COMPLETE capture of the root and every dependency.
- Node kinds in capture. Each closure node is one of three kinds, and only one kind needs a ZIP:
  - System nodes: add-ons whose IDs start with `xbmc.`, and `kodi.resource` (`resources/lib/dependencies.py:344`). They are never acquired. Each must pass the trusted builtin read (`read_verified_builtin_metadata`, `resources/lib/frozen.py:1662`). For the passive builtins that read requires the exact pinned descriptor (`resources/lib/frozen_install.py:1561-1565`, including `xbmc.metadata` 2.1.0).
  - Platform-provided nodes: installed add-ons whose metadata origin is the application directory (`resources/lib/frozen.py:1708-1711`). They are never acquired and must pass the platform checks.
  - Artifact-bearing nodes: every other installed add-on in the closure. They require a verified ZIP through `ArtifactAcquirer.acquire` (`resources/lib/frozen.py:1350`): the store first, then the package cache, the official repository or an approved local capture. The root `metadata.generic.albums` 1.0.20 is installed in the portable user add-on directory, not the application directory, so it is artifact-bearing.
- Builtin pins are admission data, not closure verdicts. The candidate's pin for `xbmc.metadata` 2.1.0 (`frozen_install.py:1565`) does not by itself admit the node. Admission depends on the installed descriptor passing the verified read during capture. The offline diagnosis of 2026-11-18 traced the earlier 32730 builtin-closure refusal to the missing pin. It did not establish that the current installed descriptor passes that read.
- Version suggestion. `suggest_version` pre-fills the next version when an entry with the same identity exists (`create_workflow.py:172-182`). This is why runbook gate B-2 re-enters `1.0.0` after every name edit.
- Identical bundle. If the bundle key equals an existing entry, `register` returns that entry without conflict (`build_library.py:612-614`). The frozen manifest carries `created_at` (`frozen.py:250`), so a fresh Create normally produces a new key. A success where 32733 is expected is therefore a wrong result (see F1).
- Selection. `select()` runs only after a successful register (`create_workflow.py:297`). A conflict never reaches it.

#### Rejection does not establish that nothing was written

The conflict is detected after capture and acquisition. With private capture off, these are the writes that can occur before the 32733 result:

| Write site | When it happens | Scope |
| --- | --- | --- |
| `ArtifactStore` creates `artifacts/` (`artifacts.py:141`) under `addon_data/script.build.manager/frozen-artifacts` (`create_workflow.py:356`) | Only if that `artifacts/` directory is missing | S2 |
| `ArtifactStore.import_zip` (`artifacts.py:152`; called at `frozen.py:1364`, `1396`, `1432`) | Only for an artifact-bearing node whose exact `(addon_id, version)` is not already a verified store artifact and whose bytes come from the package cache, the official repository or an approved local capture | S2 |
| `BuildLibrary` lock file and root (`build_library.py:546-551`) | Created only if missing; no content change | None |
| `builds/<key>.json` and `registry.json` (`build_library.py:618-632`) | Only after the conflict check, which is not passed | S1 (not reached) |
| Registration inputs (`create_capture.py:121-139`) | System temporary directory | None (outside the profile) |

No write site was found on this path for: configuration (the configuration backend's writers have no Create call site; capture uses only `read_file` and the getters); skin activation (`skin.py:235` is not on the path); the capture lifecycle (`CaptureLifecycleCoordinator` has no production call site, and `create_capture_transaction.json` is only read); private overlays (private path only); add-on enable, disable or install; or the product or application add-on trees.

Consequence. The S2 frozen-artifacts witness can change before the conflict in two ways: by creating the missing `artifacts/` directory, or by importing an artifact. The driver's witness is a recursive tree digest of `addon_data/script.build.manager/frozen-artifacts` (`tools/bm_preservation_driver.py:95-141`, `tools/bm023a_adapter_support.py:2169-2185`), and each subdirectory contributes its own entry. Creating an empty `artifacts/` therefore changes the digest even if no file is added. D-032 has no maintenance class for either change, so either change is MEANINGFUL-unclassified and blocks PASS. An unchanged post-run S2 witness shows that neither occurred. The 32733 outcome does not show it.

Kodi's own runtime writes during the UI session (texture cache, uptime and settings saved at exit, view state) are not Create writes. They are classified only by the five-file comparator (S3) and by the S5, S6 and S8 dispositions below.

#### 1. Execution provenance and external ledger

**1.1 Fact classes.** Four classes, never merged:

- **T, original tool-observed fact.** A value stated in a tool's own output or raw response: the `identify`, `verify` and `quit` output files; the driver's `ready.json` and `result.json`; the READY and DONE lines and exit status in the raw session transcript; and MCP image and text responses. A T fact names its producing tool. It is independently verified only when the adjudicator matches it to its original invocation record under §1.2.
- **C, controller-recorded observation.** What the controller records about its own actions and clocks: call times, the chosen navigation, budget readings, and the session identifier as returned to it. A C entry supports timing or ordering only where T records corroborate it.
- **A, operator attestation.** A human statement: focus confirmed, text typed, step acknowledged. It counts only where a later T image or record is consistent with it.
- **R, independent review or adjudication conclusion.** The judgment belongs in the independent review or adjudication record. A tool can establish the existence and identity of a retained record. The judgment it contains is R.

**1.2 Provenance rules.** Every material execution or ordering claim (launch, name and version entry, review, confirm, rejection, UI exit, prequit identity, quit, final verification, FINISH and DONE) must satisfy all of the following. Otherwise it is UNVERIFIED.

- P-a. The original records are retained unedited: the raw transcript of the driver session (each `exec_command` and `write_stdin` call with its returned output and session identifier); the raw MCP tool-call responses; and each helper output written by `--output` into the sealed evidence directory, together with the raw call that named its output path.
- P-b. Each claim cites its original record by call sequence number and session identifier. The adjudicator inspects the raw record, not the controller's copy or summary.
- P-c. Producer identity. Every helper output's `tool.sha256` must equal the SHA-256 of the reviewed candidate's `tools/bm_test_app.py`, recorded in L1. For `bbfbb7e` that value is `eabee188c999d2e21738e70fa10e98bf082eec7931ebb5cbeb2bb1614797311a` (`git show bbfbb7e:tools/bm_test_app.py`). The driver's `ready.json` `host_commit` must equal the reviewed commit, because the driver verifies host source against that commit before READY.
- P-d. Order comes from raw sequence numbers. Clock readings corroborate only. Monotonic readings are controller-recorded (C).
- P-e. A file hash binds a retained file to the bytes named by its original record. It proves that the bytes are unchanged. It does not prove that the bytes were produced by that execution. A copied or re-created file with a matching hash fails P-b unless its original record shows that it was produced by that invocation.
- P-f. If producer identity, session identifier, timing or ordering cannot be verified from the original records, the claim is UNVERIFIED, and every conclusion that depends on it is INCONCLUSIVE. This procedure introduces no signing, attestation or ledger service. The raw transcripts and helper outputs are the authority.

**1.3 Template, contemporaneous entries and sealing.**

- Before READY, the controller creates an empty ledger template with slots for L1 to L16 and, for the D1 scenario, L2A as described in the 2026-11-19 S6 addendum. The template contains no outcomes and no values. Its SHA-256 is printed in a raw tool output produced before the driver session starts.
- Entries are appended contemporaneously, each immediately after its event and citing the raw record sequence number. An entry that describes an event before its raw record exists is invalid.
- After execution the append-only ledger is sealed. Its final SHA-256, the template hash, and an index of raw records (sequence numbers with file hashes) are recorded in the adjudication record. Corrections are appended as new entries, never edited in place.

**1.4 Permitted and prohibited choices.** The ordinary Create component selection in the review is permitted. It must stay within the reviewed content: the existing name and version, legitimate different public software content, skin and private scope excluded, and no unintended configuration or package action (runbook step 3). Every selection and toggle is recorded in L7 with its image.

Prohibited. Each of these makes the run INCONCLUSIVE at least: any artifact-decision or recovery choice for a missing saved copy (Install the current version, Skip, Repository Current, or any alternative offered for it); version substitution; D-033 local-capture consent or any approval of a local capture; a scope change outside the reviewed exclusions (skin, private, configuration or package action); a second Create; and Apply, Install, Repair or any recovery.

**1.5 Required entries, in order.** Fact classes appear in brackets. The order follows the runbook's executable sequence (steps 1 to 5, including the K1 UI-exit gate).

- **L1 Authority and identity [A, T].** Task identifier and authorization reference. Scenario: name, version, root `metadata.generic.albums` 1.0.20, expected 32733. Reviewed candidate `bbfbb7e440b7093eb3ccff7576b23888930d4021`, tree `06adffc5e41f8965daaceab8353b96ddfe559c3f`. Stage manifest from the authoritative run card, `.qualification-evidence/a15-pinned-stage-provenance-20261119/stage-20261118T182302Z-bbfbb7e440b7/stage_manifest.json`, SHA-256 `19dc2e927976176e3b9b9a4b1e5fb60579b9088d8593d32737c3df34abbecde6`. Product tree `98af76306ac113ca29be45beef11771029105d8b12fb5f53399e0b531528cedd` (88 files). Helper SHA-256 (P-c). Driver host commit and manifest SHA. The adapter version that Eric accepted; the open 0.0.17 decision must be settled before this entry is sealed. Target `/Applications/Kodi Build Manager Test.app`, portable `-p` only.
- **L2 Pre-run source and identity [T].** The pre-run `verify --output` result (installed equals manifest and candidate; Git binding checked and ok) and the pre-run `identify --output` result (not running; zero processes), each with its raw call sequence. The optional closure and store determination in §5 is recorded here as a T output if it was run. Otherwise it is recorded as UNVERIFIED.
- **L3 Driver session and READY [T, C].** The session identifier as returned to the controller (C) and as it appears in the raw transcript (T). The READY line in the raw transcript (T). The `ready.json` SHA-256 (T), with its `host_commit`, `manifest_sha256`, `staged_candidate`, `public_baseline_acquired`, `begin` block and `native_operation_authorized: false`. The `native_operation_authorized: false` value records that the driver does not authorize the operation. READY time (C).
- **L4 Launch [T].** The raw `test_app_launch` call (sequence and response), and the `identify --output launch-identity.json` result (T): `process.pid`, bundle, `portable_flag`, and `test_app_process_count` 1. The launch PID is taken from this file, not from the MCP response.
- **L5 Ordered navigation and observation [T, C].** Each `test_app_observe` and `test_app_navigate` call: raw sequence number, direction, response time (C), and the image SHA-256 from the raw response (T). The controller's one-line description of each screen is C.
- **L6 Input [A, T].** For each input dialog: the B-1 focus observation (T image), the operator's OS-focus confirmation (A), the completion acknowledgement (A), and the exact-field observation that follows (T). Name is entered first, then version, with B-2 verification after every edit. The recorded value is the value shown in the T image.
- **L7 Review, component selection and single confirmation [T, A, C].** The full review image before confirm (T). Each ordinary component selection or toggle, with its image (T), under §1.4. The single confirm action: raw sequence number and count, which must be 1 (T). The controller's time for it is C.
- **L8 Terminal outcome [T].** The raw response image and text after confirm (expected localized 32733), the acknowledgement call, and the absence of any prohibited choice in §1.4, as shown by the raw sequence. Any other outcome is recorded exactly as observed.
- **L9 UI exit [T, C].** Each raw Back and observe call with its image (T), and the observed outside-BM state. The controller's `UI_EXIT_VERIFIED` marker (C) is valid only with the image it cites.
- **L10 Prequit identity [T].** The `identify --output prequit-identity.json` result with its raw call sequence: the same PID as L4, the same bundle, portable state, and a single process.
- **L11 Authenticated quit [T].** The raw invocation of `tools/bm_test_app_keychain.py quit` with `--output <run>/quit.json`: its sequence, command, start and end times as the raw record shows, and exit code. The raw record binds the `quit.json` SHA-256 (P-e). The `quit.json` fields are `schema`, `command`, `ok`, `graceful`, `identity_before`, `identity_after`, `invocation`, `shutdown` and `tool`. Required values: `ok` and `graceful` true; `invocation.authenticated` and `invocation.listener_pid_verified` true; `invocation.test_app_pid` equal to the L4 PID; `shutdown.accepted` and `shutdown.exited` true; `shutdown.forced_termination` false; `identity_after` not running, with zero processes; and `tool.sha256` equal to P-c.
- **L12 Final identity and source verification, before FINISH [T].** `final-identity.json` (not running; zero processes) and `final-source.json` (installed equals manifest and candidate; Git binding checked and ok), each with its raw call sequence. Both must succeed before L13. On failure the runbook's stop rules apply, and no FINISH is sent.
- **L13 FINISH [T, C].** Exactly one raw `write_stdin` call with `FINISH\n` to the original session identifier (T), with the controller's time (C). The count must be 1. No CANCEL and no other input to that session.
- **L14 Driver result and exit [T].** The session's raw transcript: its DONE line and exit status. The `result.json` SHA-256, and these fields: `state`, `reason`, `public_comparison`, `after.files[].status` (the five strict statuses), `after.practical` (per-file classifications and maintenance classes), `practical_precondition` (prerequisite IDs, statuses and reasons), and `receipt_form_and_file_time_validated` when present. The driver's post-FINISH checks (quit receipt form, source and public admission) appear only through `state` and `reason`. They are not independent verification.
- **L15 Sealing and index [C, T].** The template hash, the sealed ledger hash, the raw-record index with SHA-256 and sequence numbers, and the UI image hashes. No private values and no raw logs.
- **L16 Limitations and UNKNOWN [C].** Explicit entries for anything that was not recorded.

**1.6 Required machine facts and their exported sources.** The driver keeps the raw public states in memory. It writes only the fields below, so the adjudication uses only these fields. Any fact not listed is not assumed to be exported.

| Required fact | Exported field or supported original result |
| --- | --- |
| Begin acquired, and the begin file statuses | `ready.json` `begin.acquisition` (`ACQUIRED`) and `begin.files[].status` (`UNVERIFIED`, the before boundary) |
| Begin public-state fingerprint | Not exported and not required. The begin boundary is witnessed by the pre-run `verify` (L2) |
| Public comparison before and after | `result.json` `public_comparison` (`PRESERVED` or `CHANGED_OR_MISSING`) |
| After public-state contents | Not exported |
| S1 and S2 equality, with reason | `result.json` `practical_precondition` prerequisites `S1` and `S2` (status and reason) |
| S5 installed add-on identity and enabled state, and EXACT Addons33 projection | `practical_precondition` prerequisite `S5` (status `MET`, reason `addons33_exact_and_identity_match`), which combines `identity_and_enabled_match` (installed identity and enabled equality) and `addons33_exact` (Addons33 projection classified `EXACT`) |
| Five strict file statuses | `result.json` `after.files[].status` |
| Five-file practical classes and maintenance classes | `result.json` `after.practical.files` |
| S7 owners, pending publication, quit and source binding | `practical_precondition` prerequisite `S7` (reason `owner_pending_quit_and_source_verified` when met), with L10 to L12 |
| Quit facts | `quit.json` fields in L11 |
| Stage and Git binding before and after | `verify --output` results (L2 and L12) |
| Not running, process count and launch PID | `identify --output` results (L2, L4, L10 and L12) |
| READY, DONE and exit status | Lines and exit status in the raw session transcript |
| Native screens | Raw MCP responses (images and text) |

A reviewer confirms each row against the retained file before relying on it. A row whose field is absent from the retained files is UNVERIFIED.

#### 2. S1-S9 disposition table

Each scope needs an adequate witness, or a reviewed, scenario-specific proof that the authorized operation cannot touch it by design, including its reachable lifecycle paths. A rejected Create is not a witness. A limitation statement clears nothing.

| Scope | Witness and exported source | Create-conflict argument | Required for PASS | Status now |
| --- | --- | --- | --- | --- |
| S1 Saved builds and library | `practical_precondition` S1 (library, selection and build-library tree) and `public_comparison` | The conflict path writes nothing under `build-library`. The lock and root are created only if missing | S1 MET (reason `library_selection_and_tree_match`) | Post-run witness needed |
| S2 Artifacts and associations | `practical_precondition` S2 (frozen-artifacts and install-resolution trees, and association) and `public_comparison` | Writes occur only through creation of `artifacts/` and `import_zip`, both before the conflict (write-site table) | S2 MET (reason `artifacts_and_association_match`). This is the decisive post-run witness: it shows that no artifact-bearing node needed an import and that `artifacts/` already existed. No universal pre-run store-hit condition is required (see §5) | Decisive witness exported; feasibility depends on store state |
| S3 Configuration and meaningful settings | Five-file comparator (`after.practical`) and `after.files` | Create writes no settings. Kodi may write the M1 and M2 classes. View-state or other leaves are MEANINGFUL | Each file EXACT, or MAINTENANCE_ONLY on its own file | Comparator not qualification-reviewed |
| S4 Supported add-on resources and private settings | None in the driver | The pinned private-off Create path skips configuration capture and private persistence. The separate software-acquisition and lifecycle paths need the bounds below | Independent acceptance of the scenario-specific source argument and its binding to authenticated run evidence below | Unresolved |
| S5 Addons33 | Identity and enabled state: `practical_precondition` S5. Other Addons33 content: no witness | The Create path makes no enable, disable or install call (none found). Other reachable Addons33 writers during the interval (Kodi startup and shutdown, UI navigation, add-on list access) are not analysed here | Identity and enabled MET. Other Addons33 content needs an adequate witness, OR reviewed scenario-specific proof of no reachable write by design. Without either, PASS is unavailable. The limitation stays reported | Identity witnessed; other content unresolved |
| S6 Unmanaged add-ons and unrelated configuration | None | BM write sites on the path stay in BM-owned roots (write-site table). Import failures remove their temporary files (`artifacts.py:194-225`), and capture failures return before registration. Kodi's reachable writes to unmanaged add-on directories and to unrelated configuration are not analysed here | The complete BM write-set (above) AND either an adequate witness or reviewed proof covering Kodi's reachable writes, citing pinned Kodi source. Without either, PASS is unavailable. [For the Create-conflict scenario only, narrowly overridden by the 2026-11-19 S6 addendum; this original wording is retained as history.] | Not justified. Unresolved, not presumed safe. Stays unresolved until the 2026-11-19 addendum's L2A entry is independently reviewed |
| S7 Transaction, hold and publication | `practical_precondition` S7 (reason `owner_pending_quit_and_source_verified`), with L10 to L12 | No transaction, hold or publication record is created on the path | S7 MET at both boundaries | Must be met by the run |
| S8 Source installation | Boundary witnesses: the `verify` results in L2 and L12 | Create reads application add-ons through `KodiInventoryBackend(..., application_addons_dir=special://xbmc/addons)` (`create_workflow.py:345-350`). No write call on the path targets the product tree or the application add-on tree (write-site table) | Boundary witnesses, plus the bounded source argument above. The limitation (no source-tree census during the interval) is reported | Source argument recorded; boundary witnesses must come from the run |
| S9 Receiving installation | The S1 to S6 witnesses | Not applicable. The conflict performs no install, update or repair, and `select()` is never reached (`create_workflow.py:297`) | Stated as not applicable. Remains unqualified for receiving operations | Not applicable to this scenario |

##### S4 source justification for the Create conflict

Scope and status. This is a conditional source argument for `BM-ITEM8-INSTALL-20261015` 1.0.0 with only `metadata.generic.albums` 1.0.20 selected, current skin excluded, private capture off, and expected terminal 32733. Product citations refer to the L1 candidate `bbfbb7e440b7093eb3ccff7576b23888930d4021`. The `resources` tree is `3678e8ee47b1ceb21330ff2a039e3c8be03dfc7d`, and the candidate and documentation base `735b847` match in `resources`, `addon.xml`, `default.py` and `service.py`. S4 remains unresolved pending independent review and authenticated run evidence.

**What the source establishes**

1. `default.py:51-62` wires the native Create provider. The editor renders `session.include_private` (default on), and choice 4 toggles it (`ui/create_dialogs.py:77-97`, `create_workflow.py:51-66`, `ui/native_dialogs.py:203-212`). The runtime uses the default `TrustedCaptureCatalog`. Preview sets an empty skin when it is unselected. The catalog adds public settings/files only for the selected active Arctic Fuse 3 skin, always returns an empty private-settings tuple, and adds the structured declaration only when private capture is on and the owner and version qualify. Constructing the catalog declaration uses static metadata. Preview passes the actual tuples into the frozen request and leaves the overlay ID empty when both private tuples are empty. `captures_private` tests those tuples and request validation checks its agreement with the overlay ID (`create_workflow.py:101-128`, `183-200`, `348-359`, `redlight_resource.py:61-92`, `create_capture.py:54-81`, `231-257`).
2. The review shows counts from the request for public settings and files. With private capture off it shows “Private settings excluded” rather than private declaration counts. Separate confirmation executes the same previewed request. Back or cancellation skips execution (`create_workflow.py:69-79`, `215-224`, `ui/native_dialogs.py:211-244`, `ui/create_dialogs.py:121-126`). Engine setup resolves the profile root for the Red Light adapter and registers the adapter in memory, and the configuration backend constructor stores its arguments. These steps open no private resource. Capture revalidates the request, acquires software, iterates the empty public setting/file lists, and skips the private setting/resource reads and overlay construction. A validation or capture error returns a failed or incomplete result without a private fallback (`redlight_resource.py:100-122`, `private_resource.py:522-543`, `config.py:1833-1837`, `create_capture.py:298-355`, `359-440`). A second software capture requires explicit D-033 approval, which this scenario prohibits.
3. Execution returns before registration on an incomplete result, missing public bundle, overlay-presence mismatch or failed validation. It checks the resolved public manifest's private declarations against the request. With no overlay it stages only public registration inputs in a temporary directory and calls the library. The lazy store factory, store lookup or persistence, and rollback via `remove_if_exact` are all on the overlay-present branch. Version suggestion reads the public library. Registration reads staged public materials and library records, and the different-content same-version conflict raises before writing an envelope or registry. Temporary staging is cleaned up on exit, and 32733 returns before `select()` (`create_workflow.py:172-181`, `225-297`, `359`, `create_capture.py:121-139`, `build_library.py:480-491`, `526-539`, `546-637`). The shared 32733 handler also covers private overlay conflict in other scenarios. The terminal alone cannot identify the branch.

**What must be established for the actual run**

- Bind the source and runtime composition to L1–L4 and L12. Use the original L6–L8 records to identify the exact inputs, selected root, skin exclusion, private toggle off, the full review showing zero public settings and files, and the separate confirmation followed by the visible 32733 rejection. Corroborate the root ID and version through authenticated public inventory or fixture evidence tied to the run because the chooser shows labels. The accepted source mapping from that review to the same executed request is the basis for both empty private tuples and the empty overlay ID. Record that inference in adjudication. The screen does not export the tuples. Record any differing selection, prohibited choice, substituted candidate or ambiguous sequence as unresolved under the existing rules.
- Account for the actual software-acquisition reads as well as Create's write and cleanup targets. Inventory reads installed descriptors. Store hits return before cache or repository lookup. The cache path reads matching `*.zip` paths before exact archive validation. Repository fallback hashes all regular files under the installed add-on before archive comparison, so private-off alone cannot rule out a protected read there (`frozen.py:1009-1033`, `1174-1198`, `1220-1253`, `1296-1305`, `774-820`, `855-886`, `1350-1437`, `1804-1819`). Establish stable verified store hits for the actual artifact-bearing closure, or bound the reached cache/repository reads to public software using original records. The advisory §5 determination, a root-only store hit, S2 boundary equality, and 32733 each leave gaps on their own. Establish confinement through use for metadata and archive reads, library and temporary staging, artifact writes and cleanup, and admitted startup paths. A redirected or aliased source or target can invalidate the proof (`artifacts.py:167-225`, `233-258`, `288-314`). Use public identities and path-safety evidence without collecting private values.
- Bound startup or other lifecycle work admitted by the actual run and any reasonably traceable effects of the reached Kodi API calls on S4. Build Manager reaches the inventory and builtin queries, native dialogs and logging cited in the write-site table. The service also calls ordinary restart startup and frozen-install startup at launch (`service.py:17-20`, `startup.py:117-142`, `frozen_install.py:5296-5328`). Source inspection leaves Kodi implementation side effects, startup state continuity, runtime path identity and ambient changes unverified. The S6 addendum's U1–U4 evidence may be relevant where it covers the same paths and effects. D1's ambient limitation applies to S6 only. Any unresolved path capable of touching S4 prevents this justification from clearing S4. The driver still reports `S4` as `UNVERIFIED` (host source at `735b847`, `tools/bm_practical_precondition.py:477`).

#### 3. Independent adjudication rules

**Precondition for any PASS.** The comparator and the driver's practical validator must have independent qualification-review records for the exact candidate. Without them the result is INCONCLUSIVE. No such records exist yet.

**Narrow practical PASS (external, Create conflict only).** Every condition must hold. Each must cite an original record under §1.2 or a field listed in §1.6.

- P1 Identity and provenance: L1 matches the reviewed candidate, manifest, helper and driver identities. Every T fact relied on passes §1.2. There is exactly one confirmation.
- P2 Expected result: the 32733 outcome is visible in a verified T image after that single confirmation, with its acknowledgement. No prohibited choice in §1.4 occurred.
- P3 Ordering and correlation: the raw sequence shows READY, launch, review, confirm, rejection, UI exit, prequit identity, authenticated quit, final identity, final source verification, the single FINISH, and then the driver's result and DONE, in that order. The PID is the same in L4, L10 and the quit invocation. The session identifier is the same from READY to DONE.
- P4 Driver record: `result.json` agrees with the raw transcript and with its own validated `after.practical` block.
- P5 Public witnesses: `public_comparison` is PRESERVED, and the exported S1 and S2 prerequisites are MET.
- P6 Five files: each file is EXACT, or MAINTENANCE_ONLY with an approved class on its own file (M1 on guisettings; M2 on Textures13). None is MEANINGFUL or INCONCLUSIVE.
- P7 S7: exported S7 MET, with L10 to L12.
- P8 Dispositions: S4 is justified by its call path. S5 other Addons33 content and S6 each have an adequate witness, or reviewed scenario-specific proof, under §2. S8 has its boundary witnesses and bounded source argument. S9 is recorded as not applicable. Any unresolved disposition makes PASS unavailable. [For the Create-conflict scenario only, narrowly overridden by the 2026-11-19 S6 addendum; this original P8 wording is retained as history.]
- P9 Attestations: each A entry is followed by a T image or record that is consistent with it.

Under P5 and P6 together, the strict five-file statuses may still read CHANGED_OR_MISSING when the only difference is an approved M1 or M2 class. The strict result stays as produced. Practical classification never rewrites it, and a practical PASS never makes the strict state PRESERVED.

**FAIL.** Requires independently established evidence, correlated through the ledger and §1.2 to the operation, of at least one of:

- F1 Wrong operation result: success where 32733 was expected, including a byte-identical bundle success, or any increase in registry entries for the same identity and version.
- F2 BM-caused loss, overwrite, truncation or deletion of meaningful content in S1 to S6, such as the fixture entry or its build file, the selection, the association, or a store artifact. The store is write-once, so this needs direct evidence.
- F3 BM-caused unsafe transaction, hold or publication residue attributable to the operation (S7 NOT_MET from an operation-created record).
- F4 Unrelated mutation attributable to the operation, including of an unmanaged add-on.
- F5 Exposure of secret or private values in retained evidence.

A claim that fails §1.2 cannot ground FAIL. It yields INCONCLUSIVE.

Not FAIL by themselves: a strict difference; an additive artifact import; creation of `artifacts/`; an approved M1 or M2 change; an incomplete terminal such as 32730 or 32732; a timeout or CANCEL.

**INCONCLUSIVE** is the default for: any unverified T fact (§1.2); a prohibited choice (§1.4); an unexpected dialog or ambiguous screen; an S2 change (import or directory creation) with no D-032 class; any MEANINGFUL or unclassified classification; any reachable S4, S5, S6, S8 or S9 scope without its required disposition; any missing, contradictory or unsealed ledger entry; any unverified attestation; broken or uncertain session, PID or receipt correlation; a terminal other than 32733 that is not a success (the conflict gate was not reached); process loss, timeout, EOF, CANCEL or interruption; incomplete cleanup; an absent `result.json`; and a comparator or validator without review.

The N6 strict state, reason and per-file statuses are copied from `result.json` unchanged. The adjudication may cite them. It never rewrites them and never derives a strict result from them.

#### 4. Negative evidence cases

Each case below prevents PASS, alone or in combination.

- **Caller-supplied VERIFIED alone.** `tools/bm_practical_precondition.py` accepts the string `correlation='VERIFIED'` (lines 292-293), and no producer exists. The driver passes `None` (`tools/bm_preservation_driver.py:396`). A string or flag is not evidence. This procedure never uses that field.
- **Copied receipt with refreshed mtime.** `quit_receipt` checks shape, owner, mode, link count and an mtime inside the READY-to-read window (`tools/bm_preservation_driver.py:172-207`). A copied file touched into that window passes those checks. Its mtime is not provenance. PASS needs the raw invocation of the authenticated quit, whose record names the output path and binds the `quit.json` SHA-256 (L11, P-a, P-e), a receipt PID equal to the launch PID, and the final identity (L12). A receipt without that binding is UNVERIFIED.
- **Controller-authored summary without an original record.** A statement such as "launch succeeded" or "32733 observed" that has no raw record is a C claim. It yields INCONCLUSIVE for the fact it asserts.
- **No native activity despite a structurally valid driver.** READY, FINISH and `result.json` establish only the acquisition and comparison boundaries. Without T entries for the review and the confirm, the scenario did not occur: INCONCLUSIVE (not reached).
- **Missing terminal result observation.** Without a fresh T image of the 32733 outcome after the single confirmation, the expected result is unverified. A selection screen, a receipt, a comparison or a driver success does not show it (runbook step 3).
- **Stale or broken process or session correlation.** Different session identifiers at READY and FINISH; a second driver; a launch PID that differs from the receipt PID; more than one Test.app process; a process still running after quit; FINISH sent twice or to another session; `ready.json` changed after READY. Each is INCONCLUSIVE.
- **CANCEL, timeout or interrupted acquisition.** CANCEL discards the host baseline and produces no comparison. A 900-second timeout, EOF, controller loss or interruption is INCONCLUSIVE. No comparison may be rebuilt from hashes or persisted private data (runbook B1 and the stop rules).
- **Meaningful or unclassified changes.** Any MEANINGFUL or INCONCLUSIVE classification, any public-witness difference, and any leaf outside the M1 and M2 classes block PASS. A class counts only on its own file.
- **Unwitnessed protected scopes without proof.** S5 other Addons33 content and S6 are unwitnessed. A limitation statement does not clear them. Without an adequate witness or reviewed proof they block PASS. [For the Create-conflict scenario only, narrowly overridden by the 2026-11-19 S6 addendum; this S6 part of this bullet is retained as history.] The 32733 outcome cannot exclude S2 writes, because an import or the creation of `artifacts/` happens before the conflict is detected.
- **Pre-run store probe alone.** A read-only store probe shows the presence of artifacts. It is not the post-run S2 witness, and it does not establish builtin admission.
- **Source pin alone.** A pin in source (for example `xbmc.metadata` 2.1.0 at `frozen_install.py:1565`) does not establish that the installed descriptor passes the verified builtin read. It does not make a system node artifact-bearing or artifact-free.

#### 5. Pre-run determination (advisory; not a PASS input)

- The decisive witness is the exported post-run S2 result (§2). The pre-run determination only predicts whether capture will import an artifact or create `artifacts/`. It is recorded in L2 as UNVERIFIED if it was not performed.
- Node kinds. Using the classification in the source facts, the determination places each closure node in one of three kinds: system (`xbmc.` and `kodi.resource`), platform-provided (application-origin), or artifact-bearing. For a system node it must establish that the verified builtin read succeeds for the installed descriptor. A source pin is not enough. For a platform-provided node it must establish the platform admission. Neither kind receives or needs a ZIP, and no ZIP is manufactured for either.
- Store probe for artifact-bearing nodes only. The method is `ReadOnlyArtifactStore` over `addon_data/script.build.manager/frozen-artifacts`, followed by `find(addon_id, version)` and `read_bytes(sha256)` with its digest check. `ReadOnlyArtifactStore` creates nothing and refuses `import_zip` (`resources/lib/plan.py:197-208`). The capture's own `ArtifactStore` must not be constructed for this step, because its constructor creates `artifacts/` (`artifacts.py:141`).
- Closure source. This review found no existing read-only entry point that returns the complete classified closure separately from acquisition. The closure walk and the acquisition are one function, `capture_frozen_build`. A composition of the same installed-descriptor edge parser and node predicates with the read-only store probe is not an existing supported method until a reviewer accepts it from source. If it is not accepted, the determination is UNVERIFIED and reported as such.
- Never: call `capture_frozen_build` or `CreateBuildCaptureEngine.capture` for the determination; use the package cache, the official repository or local capture in it; manufacture a ZIP for a system or platform node; or infer eligibility from a pin or from the mere presence of a directory.
- Each determination output is a T record under §1.2, with its raw invocation retained.

#### 6. Acceptance boundary

- A PASS under this procedure is independently adjudicated external evidence for the Create conflict scenario only, and it must be labelled that way. It is not a PASS from the existing driver, and the driver's verdict stays `NOT_DECIDED`.
- It does not establish S9 receiving-installation preservation, install, update or repair preservation, the D-030 deferred lifecycles, whole-profile preservation, complete Addons33 or unmanaged add-on verification, publication, public-product qualification, or macOS beta acceptance.
- It does not replace an accepted native run. A native run needs its own authorization naming the scenario, target, permitted actions and operator steps.
- It does not replace independent qualification reviews of the comparator, the driver validator, the precondition assessment or the evidence itself.

#### Illustrative outcomes (hypothetical; not observations)

These examples show how the rules apply. They describe no run, make no finding, and must not be cited as evidence.

- **H1, hypothetical narrow PASS.** The ledger is complete, and its raw records are verified. `public_comparison` is PRESERVED, and exported S1 and S2 are MET. guisettings is MAINTENANCE_ONLY with `M1_UPTIME` count 1, and the other four files are EXACT. S4 is justified by a hypothetical reviewed call path. S5 other content and S6 are covered by a hypothetical reviewed proof, which is an assumption of this example. The `result.json` strict state is INCONCLUSIVE, reason `changed`, because guisettings differs. Adjudication: narrow external practical PASS, with the strict result reported unchanged.
- **H2, hypothetical FAIL (F1).** The confirm produced a success screen instead of 32733, and the exported S1 is NOT_MET because the registry gained a second entry for the same identity and version. Adjudication: FAIL for wrong operation result, cited to the verified T image and the S1 field.
- **H3, hypothetical INCONCLUSIVE.** 32733 is observed and all other entries are clean, but the exported S2 is NOT_MET because one dependency was imported before the conflict. No D-032 class covers artifact addition. Adjudication: INCONCLUSIVE. Preserve the evidence and make no retry. It is not FAIL, because the import is additive and not shown to be harmful.

#### Feasibility of this scenario

- Feasible in principle. The 32733 gate is reached only after a COMPLETE capture. System and platform nodes are admitted without ZIPs, and artifact-bearing nodes need verified ZIPs.
- A narrow PASS needs the exported post-run S2 to show no import and no creation of `artifacts/`. That holds when every artifact-bearing node already had a verified store artifact and `artifacts/` already existed. The conflict key needs only identity and version, so the reviewed content can be chosen to match existing store artifacts. Otherwise expect INCONCLUSIVE by design.
- Root content changes the bundle, the captured nodes and their artifacts, but not the conflict key.
- Maintenance from UI use (M1, M2) is classifiable. View-state or other settings changes are not.

#### Conditions still required before a native A15 run

This November 18 checklist is historical. The authoritative run card below supersedes its status and executable inputs.

1. Qualification reviews of the comparator, the driver practical validator and the precondition assessment for the exact candidate (none recorded yet).
2. A narrow independent Codex re-review of this corrected addendum.
3. Eric's authorization of a separate native task naming the scenario, target, permitted actions and operator role, and his decision on the adapter 0.0.17 driver.
4. A B1 PTY channel in the executing session, with raw transcript retention under §1.2 P-a. This Claude session has none.
5. A disposition for S5 other Addons33 content and for S6: an adequate witness, or reviewed proof citing pinned Kodi source. Neither exists yet. [For S6 only, narrowed by the 2026-11-19 S6 addendum, which is pending independent review; the S5 part is unchanged.]
6. A reviewed decision on the closure composition in §5, if the advisory determination is wanted.
7. The ledger template prepared and hashed before READY (§1.3), using the bbfbb7e stage manifest rather than the stale path in runbook step 1.
8. The fixture entry `BM-ITEM8-INSTALL-20261015` 1.0.0 present and unchanged before READY, and `artifacts/` already present under `frozen-artifacts`, so that no directory creation is expected.
9. Operator availability for B-1 focus confirmation and physical entry, arranged before READY.

#### Consistency findings

- Consistent: the 32733 mapping; the 32730 path ends before registration; the B-2 re-entry rule matches `suggest_version`; the absence of a D-032 class for artifact addition is consistent with the S2 digest rule.
- Clarified here: the root changes the captured bundle but not the conflict key, which is identity and version only.
- Open, not changed by this addendum: S2 has no class for additive imports or directory creation, so a scenario PASS depends on store state; runbook step 1 still names the stale manifest path; the precondition module still accepts a caller correlation string; the driver's quit receipt check is mtime-bounded only.

### Dated addendum (2026-11-19): S6 BM-attributable disposition, Create conflict only

Status. Documentation only. Eric approved option D1 on 2026-11-19, recorded in `.orchestrator/DECISIONS.md` (D-032 clarification of 2026-11-19, S6). This addendum is additive and narrowly overrides the Kodi-inclusive S6 wording of the 2026-11-18 addendum for one scenario. S6 remains unresolved. Applying the disposition requires an accepted independent source review and adjudication of the future run's sealed evidence, including L2A. It authorizes no native test, Test.app launch or staging, profile access, practical PASS, qualification or acceptance. No product code, test, witness, schema or maintenance class changed.

Scope. The Create-conflict scenario only: Create name `BM-ITEM8-INSTALL-20261015`, version `1.0.0`, root `metadata.generic.albums` `1.0.20`, private capture off, expected terminal `32733`. Install, Update, Repair and every other scenario keep the Kodi-inclusive requirement and need their own approval.

#### Reconciliation with earlier text

The earlier wording stays in place as history. For this scenario only, the standard below replaces it as follows.

| Earlier text | Status for this scenario |
| --- | --- |
| Section 2, S6 row, "Required for PASS": the complete BM write set AND an adequate witness or reviewed proof covering Kodi's reachable writes, citing pinned Kodi source | Narrowed. The Kodi-inclusive proof is not required for this scenario. The reviewed BM write-set proof below, with the L2A ledger entry, is required instead |
| P8 (S5 other content and S6 each need a witness or reviewed scenario-specific proof) | S5 is unchanged (see addendum G). S6 is satisfied by the BM-attributable disposition below, once accepted |
| Adjudication bullet "Unwitnessed protected scopes without proof" | S6 is no longer unwitnessed-without-proof for this scenario once accepted. It stays a stated limitation. Ambient activity remains unwitnessed |
| Condition 5 for a native run (a disposition for S5 other content and for S6) | S6 requires independent review of this procedure before a native run and independent adjudication of the actual run evidence afterward. S5 part unchanged |
| Protected scopes table, S6 row (no unmanaged directory census, no unrelated-file witness) | Still true. No witness was added |

Unchanged: S1 to S5, S7 to S9, strict N6, the five-file comparator, the closed maintenance classes M1 and M2 and the practical FAIL and INCONCLUSIVE rules. A strict or practical difference never becomes FAIL by this addendum.

#### The approved standard

- S6 for this scenario concerns changes attributable to the authorized Build Manager operation, including reasonably traceable direct and indirect effects.
- Reviewed evidence must establish that the reachable operation cannot modify unmanaged add-on directories, their data or settings, or unrelated configuration.
- Ambient Kodi and third-party add-on activity is not verified for preservation and is outside this S6 claim. A PASS that relies on this disposition must say so, and must not say that S6 content was preserved.
- An established BM-caused unrelated mutation, including of an unmanaged add-on, is FAIL under the existing rules. Ambiguous attribution that could conceal a BM-caused modification is INCONCLUSIVE.
- The 32733 outcome does not prove preservation. A missing direct write call does not prove it either. The proof below is about what the code can reach, and it carries named assumptions.

#### Reachable BM write sites and Kodi API calls (source inspection)

Source identity. Line numbers refer to repository commit `6bf489b36856fe0ebddca26ce142e56ebb0ef3b5`. Its product tree is identical to the staged candidate `bbfbb7e440b7093eb3ccff7576b23888930d4021` named in L1: `git rev-parse <commit>:resources` returns `3678e8ee47b1ceb21330ff2a039e3c8be03dfc7d` for both, and `git diff bbfbb7e 6bf489b -- resources addon.xml default.py service.py` is empty. A different candidate needs its own review. Everything below was read from repository source. Kodi source was not used, because no verifiable pinned copy is available locally.

| Reachable activity | Site | Writes and where |
| --- | --- | --- |
| Menu and Create entry | `default.py:45-62`; `native_dialogs.py:49-56`, `169-180`, `484-498`; `create_workflow.py:137-151` | Create entry reads inventory through JSON-RPC and installed metadata through read-only descriptors. The menu also invokes Kodi's modal UI (see below and U1) |
| Native Create presentation | `native_dialogs.py:180-262`; `create_dialogs.py:69-107`, `121-138`; `default.py:20-41`, `59-62` | The path opens BM pages using Kodi's `WindowXMLDialog.doModal()` for the menu, editor, add-on selection, review and separate confirmation. Name and version use `Dialog.input()`. The confirmed execution creates and closes `DialogProgressBG`, and the conflict presents localized 32733 through `Dialog.ok()`. These are verified BM call sites. Kodi-side effects are open under U1 |
| Capture, before conflict | `create_workflow.py:218` (`engine.capture`); `create_capture.py:298` (`capture`); `frozen.py:1602` (`capture_frozen_build`) | Reads installed add-on files and metadata through `O_RDONLY`, `O_NOFOLLOW` descriptors (for example `frozen.py:605-615`, `1090-1100`). A search of `frozen.py`, `create_capture.py` (outside the temporary directory below), `inspector.py`, `official_repository.py` and `installed_addon_source.py` for file-write primitives (write-mode `open`, `write_text`, `write_bytes`, `os.replace`, rename, `mkdir`, `unlink`, `rmtree`, `shutil`, `tempfile`, `O_CREAT`, `O_WRONLY`) finds none, apart from the temporary directory below. `local_capture.py` writes only into an in-memory ZIP. `dependencies.py` and `frozen_install.py` contain mutating methods that this path does not call (see the absence paragraph) |
| Package cache and repository | `frozen.py:1296-1305` (`get_package_cache`); `frozen.py:1350-1409` (`ArtifactAcquirer.acquire`); `official_repository.py` | Reads cached ZIPs from `special://home/addons/packages` (no delete or write). The repository fetch is in memory and has no file-write primitive. Nothing in this path writes to the package cache |
| Artifact store creation and import | `create_workflow.py:356` (store root `special://profile/addon_data/script.build.manager/frozen-artifacts`); `artifacts.py:141` (`mkdir` of `artifacts/`); `artifacts.py:152-225` (`import_zip`, temporary file at `178-179`, cleanup at `194-225`); `artifacts.py:265-280` (metadata temporary file); `artifacts.py:316-322` (directory sync); callers `frozen.py:1364`, `1396`, `1432` | Creates `artifacts/` if missing, and imports a verified ZIP only when the store has no verified artifact for that `(add-on, version)`. The constructed paths are under the configured `frozen-artifacts` root. U3 covers the actual destinations. This happens before the conflict is detected, so S2 is the witness for it (see "Rejection does not establish that nothing was written"). Line 1432 is local capture, which §1.4 prohibits |
| Build Library lock and registration | `build_library.py:559` (`register`); `546-556` (`_writer`); `92-116` (`_directory` with `create=True`); `549` (lock open with `O_CREAT`); `610-616` (conflict check); `618-632` (`builds/` and `registry.json`, not reached on conflict) | `_writer` creates `library.lock`, and `_directory` creates any missing component of the path from `/` down to the library root with `os.mkdir`. The conflict check at `616` raises before `builds/` or any envelope is written. The root is `special://profile/addon_data/script.build.manager/build-library` (`build_library.py:1008-1018`). S1 witnesses the `build-library` tree |
| System temporary capture work | `create_capture.py:121-139` | `tempfile.TemporaryDirectory(prefix="bm-create-public-")` holds registration inputs. It is removed on exit. Its location is the Python temporary directory, and that location is not verified for Test.app (see U2) |
| BM startup and transaction paths | `service.py:17-20`; `startup.py:55-75`, `101-142`; `transaction.py:298-312`, `353-396`; `frozen_install.py:595-604`, `632-646`, `728-729`, `751-759`, `4899-4925`, `5296-5328` | Transaction inspection can create parent directories and the restart and frozen-install lock files. Frozen startup calls publication recovery before its no-transaction return. With no relevant journal and no transaction or hold, the no-recovery path makes no publication or policy write. U3 and U4 require evidence for the actual paths and startup state. Window properties set by `session.py:67` and `service.py:42-68` are Kodi API calls covered by U1 |
| Startup publication recovery | `build_library.py:718-754`, `860-923`; `frozen_install.py:4791-4797`, `4813-4882` | `pending_publication()` can return `None` with an acknowledged journal when the parsed applied record matches its candidate and the resolution validates. Recovery reads `publication_journal()` and can process that retained journal with no transaction. The current-authority path takes the Build Library writer lock, syncs the library and the frozen store and its `install_resolutions` directory, and can atomically replace `build-library/applied.json` if its raw bytes differ from the canonical candidate encoding. The rewrite uses a temporary file under the library directory (`build_library.py:145-162`). See U4 for the evidence required to exclude or bound startup recovery |
| Read-only inventory and JSON-RPC | `create_workflow.py:333-337` (`rpc`); `frozen.py:993-994`, `1313`; `inspector.py:335`, `353`; `frozen_install.py:2128` | Methods used on this path: `Addons.GetAddons`, `Application.GetProperties`. The builtin check at `frozen.py:1034-1042` calls `KodiRuntimeFrozenArtifactBackend.read_verified_builtin_metadata` (`frozen_install.py:2177-2218`, `2219-2283`), which uses `System.HasAddon`, `System.AddonIsEnabled`, `xbmcaddon.Addon(...)` and descriptor reads (`frozen_install.py:2113-2123`). The same object has install and enable methods, but only the read method is called here |
| Diagnostics | `failure_diagnostics.py:40-56`; `service.py` | Writes log lines through `xbmc.log` only |

Absence of enabled-state mutation. `Addons.SetAddonEnabled` is issued only at `frozen_install.py:2375`, `repository.py:691`, `dependencies.py:1525`, `addons.py:941` and `addon_state.py:638`. The Create path imports only pure helpers from those modules (`dependencies._is_system_dependency` and `_strict_version_satisfies`), and no call to any of those five sites was found on the path from `create_workflow.py` and `create_capture.py` through `frozen.py`. `artifacts.py:119` imports only `validated_root`. The add-on directory writers `addon_zip.publish_package` and `extract_package` are called only from `addons.py:317`, `repository.py:414` and `645`, and `frozen_install.py:2343`, which are Install, Update and Repair paths. `operation_admission.py` has no caller. So the path neither enables, disables, installs, updates nor removes any add-on, and it does not trigger an add-on service start or stop.

Not inferred. This table does not claim that capture made no writes: `artifacts/` creation and artifact import can occur before the conflict, and S2 continues to witness them. It does not claim that Kodi or an add-on cannot write elsewhere.

#### Effects considered

- The table identifies direct BM write sites, the destinations constructed by source and the branches that may reach them. The runtime confinement and startup evidence in U2 to U4 still need to be established. Artifact-store creation or import can precede the conflict and remains subject to S2.
- The reviewed Create path initiates no add-on lifecycle change. Its calls into Kodi include native UI, inventory queries, window properties and logging. The source establishes the BM calls and arguments, with Kodi-side behavior evaluated under U1. The retained 2026-10-08 no-op census records `__pycache__` activity in the BM product tree, which S8 covers.
- The retained 2026-10-08 Update / Repair censuses are metadata records. In each of four pairs, two database files of an unmanaged third-party add-on showed changed mtimes at unchanged size. In two of those sessions the Build Manager UI was never opened. The records establish metadata activity. Content equality and attribution are unknown, and the records do not establish whether an exact-content witness is feasible. The approved D1 policy defines the scope of the ambient-activity limitation.

#### Unresolved attribution items

- **U1, Kodi API effects.** The cited BM call paths establish the reached API calls. Review their reasonably traceable effects on S6, including native input (`Dialog.input()`), progress (`DialogProgressBG.create()` and `close()`), modals (`WindowXMLDialog.doModal()`), conflict result (`Dialog.ok()`), inventory and builtin queries (`Addons.GetAddons`, `Application.GetProperties`, `System.HasAddon`, `System.AddonIsEnabled`, `xbmcaddon.Addon`, `getAddonInfo`), window properties and `xbmc.log`. BM source inspection alone leaves Kodi's implementation effects unverified. Require reviewable evidence that bounds any effects reasonably traceable to these calls that could alter S6.
- **U2, system temporary location.** Establish the effective Python temporary directory used by `TemporaryDirectory` in the actual portable Test.app runtime and establish that its capture paths stay outside the profile and unmanaged add-on locations. A host shell's environment or temporary directory cannot establish the runtime location.
- **U3, runtime path confinement.** Establish the actual translated or resolved runtime destinations and real directory chains from the authorized portable profile to the BM-owned roots. Cover ArtifactStore (`frozen-artifacts/artifacts`, including staged imports and metadata), BuildLibrary (`build-library`, including locks and publication files), FrozenInstallStore (including its lock, transaction and `install_resolutions` paths), and the restart transaction and lock paths. Include any ancestor creation and the creation, open, replacement and cleanup targets of admitted branches. Show that existing components and leaf targets are safe and that confinement holds from preflight through use, including against symlink or other path redirection and component replacement. Directory existence or a nominal `special://` path alone is insufficient. BuildLibrary uses descriptor-relative traversal with `O_NOFOLLOW` (`build_library.py:92-116`, `546-556`). That check does not establish confinement for the separate pathname-based ArtifactStore, frozen-install lock or restart lock operations (`artifacts.py:135-141`, `frozen_install.py:600-604`, `transaction.py:306-312`). S1 and S2 cover their own trees.
- **U4, startup recovery.** Establish that no relevant publication journal, including an acknowledged one, is present at startup, with continuity from preflight and evidence that no transaction or hold can introduce another recovery path. Alternatively, bound the effects and actual destinations of every startup recovery branch admitted by the evidenced state, including lock creation, durability operations and any journal, transaction or applied-record writes. Neither alternative is established. The driver checks owner absence and `pending_publication() is None` in its before and after public snapshots (`tools/bm_preservation_driver.py:117-137`, `399-421`). The S7 assessment uses those flags along with quit, source and bundle checks (`tools/bm_practical_precondition.py:425-447`). S7 remains independently required at both boundaries. Those checks do not establish journal absence or continuity into startup, even if both snapshots show no pending publication.

Any unresolved reasonably traceable BM effect capable of changing S6 leaves the result INCONCLUSIVE. An established BM-caused unrelated mutation remains FAIL under the existing rules.

#### Evidence an independent reviewer must accept before applying this disposition

1. Match the reviewed source commit and `resources` tree to the L1 staged candidate, or review the candidate delta. Reconfirm the cited sites at that commit and retain the original source records and the scope of the call-path review.
2. Resolve U1 to U4 for the evidenced run. Account for direct writes, their actual destinations and confinement, the startup branch evidence, and reasonably traceable indirect effects. State the basis for each disposition and any remaining uncertainty.
3. Reconcile L2A with L1, L2, L3, L7 and the original run records, including the entered identity, private capture off, the single confirmation and the observed terminal. Check S1, S2, S7 and the S5 exports, including the byte-witness adjudication in addendum G, under their own criteria.
4. State the ambient-activity limitation verbatim in the adjudication. The claim covers BM attribution in this scenario only. Terminal 32733 is an outcome, and additional evidence is required for preservation.

#### Ledger entry L2A

Add the `L2A` slot between L2 and L3 in the empty template. Hash the template before READY and retain the original tool output from before the driver session starts, as required by §1.3. After L2, append the pre-run L2A entry before READY using the supporting records that already exist. Record unavailable or unresolved conditions explicitly. Append later observations as cross-referenced L2A updates in execution order once their original records exist, including any evidence available only at startup or in the live runtime. Do not backdate entries or fill gaps with assumptions. The template position identifies the slot. Raw sequence numbers establish when evidence was acquired and recorded.

- **Scenario and candidate.** Bind the build name and version, root and version, private capture off, and expected terminal 32733 to L1. Distinguish authorized scenario terms, operator attestations [A], and original tool observations [T]. Reconcile controller observations [C] against original records. After the relevant events, link the actual inputs, component choice, private toggle state, single confirmation and terminal to L6 through L8 and their original records.
- **Source evidence.** Record the reviewed commit and `resources` tree, the L1 candidate commit and tree, and the original Git and source records [T] for equality or the reviewed delta and the cited call sites. Record the controller's summary [C] with references to those records. The write-set completeness and attribution judgments belong to the independent reviewer [R].
- **Pre-run state and later evidence.** Cite L2 and the original records [T] supporting the preflight path and startup state and any other available U1 to U4 evidence. Link the READY candidate binding in L3 and later runtime or startup observations to this same session and launch identity. The controller records each open condition and its supporting references [C]. Any claim that a gate is resolved is an independent conclusion [R].
- **Independent review reference.** Bind the retained review record to the reviewed candidate and scope, with reviewer identity, date and a record reference or hash. The original tool observation of a record's existence and identity may be cited as [T]. Its acceptance, rejection or unresolved findings are [R] in the review record. A controller's transcription or summary is [C]. A missing or unbound review leaves the review prerequisite unverified.
- **Ambient limitation [C].** Include the sentence: "S6 content was not witnessed. Ambient Kodi and third-party add-on activity during the session is not verified for preservation and is outside this S6 claim."

After execution, seal the append-only ledger, including L2A and its cross-references, under §1.3 and L15. Independent adjudication follows sealing. The adjudication record includes the template hash, final ledger hash and original-record index. The adjudicator verifies provenance, reconciles L2A with L1, L7 and the actual run records, and records findings [R] against the sealed evidence. Incomplete provenance, missing independent acceptance or unresolved evidence that could conceal a BM-caused S6 change leaves S6 unresolved and the result INCONCLUSIVE under the existing rules. A complete L2A supports only the scenario-specific BM-attributable disposition, subject to independent acceptance and every other PASS requirement.

#### Boundary

- This addendum does not mark S6 MET, add an S6 maintenance class, exclusion, witness or schema, or change a verdict mechanism. It does not apply to any other scenario or to a changed candidate without review.
- It does not change the remaining gates: the qualification reviews of the comparator, driver validator and precondition; the S4 justification; S8 and S9 dispositions; operation and ledger correlation; the expected-result check; the PTY channel and operator arrangements; and Eric's authorization of a separate native task. Condition 5 now reads: S5 other content per addendum G and the adjudication, and S6 per this addendum after its independent review.
- A native run still needs its own authorization, and a PASS stays external adjudicated evidence for this scenario only (§6).

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

## Authoritative run card for the A15 Create conflict

**Status: BLOCKED.** This card supersedes the historical checklist and former step 1 command that used the `a5a4a23` manifest. Do not begin the driver, inspect the target or launch until the offline evidence routes are reviewed and Eric separately authorizes the exact operation. The sole scenario is `BM-ITEM8-INSTALL-20261015` 1.0.0, only `metadata.generic.albums` 1.0.20 selected, current skin excluded, private capture off, zero public configuration settings and files, expected 32733.

### Source and historical stage provenance

- Worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`, branch `agent/codex`. Reviewed host-tool reference `457e26935b2bf09da45fdbf65fee013ad3aac4ac`. Bind the later authorized full host SHA to the reviewed tool bytes before rendering the command. The three code reviews compared the relevant sources against this reference.
- Pinned product `bbfbb7e440b7093eb3ccff7576b23888930d4021`, Git tree `06adffc5e41f8965daaceab8353b96ddfe559c3f`, product tree SHA-256 `98af76306ac113ca29be45beef11771029105d8b12fb5f53399e0b531528cedd` (88 files), helper SHA-256 `eabee188c999d2e21738e70fa10e98bf082eec7931ebb5cbeb2bb1614797311a`. The manifest binds adapter `0.0.17`, tree SHA-256 `11265c6f2cfc76551c553b8f64f139a712a2bfcefce3d50eb2f4d17b487f7582` (5 files). Eric's approval to use this adapter in the A15 native run is pending. D-031 authorizes a narrower diagnostic exception.
- `A15_MANIFEST` is `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/a15-pinned-stage-provenance-20261119/stage-20261118T182302Z-bbfbb7e440b7/stage_manifest.json`. Use this exact path and hash for pre-run verify, the driver, READY correlation and final verify. The `d2a7897` and `a5a4a23` stage records cannot bind this candidate.
- Original records remain under `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude/.qualification-evidence/bm-claude-final-candidate-stage-20261118`. The same relative paths identify the byte-for-byte copies under `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/a15-pinned-stage-provenance-20261119`.

| Path relative to each evidence root | SHA-256 |
| --- | --- |
| `stage-20261118T182302Z-bbfbb7e440b7/stage_manifest.json` | `19dc2e927976176e3b9b9a4b1e5fb60579b9088d8593d32737c3df34abbecde6` |
| `stage-20261118T182302Z-bbfbb7e440b7/stage_result.json` | `9fa8800f14ae166809281ad12ef4919c8073e7532dd1a8601dc4f0985005e3d3` |
| `stage-durable-bbfbb7e.json` | `d64d5a6ffb5381972dab3353710ac2e76662e14eab39d7533c37ff58f2fa4969` |
| `verify-after-stage-bbfbb7e.json` | `b4a540025d7ffc48ea4f9c014081abd79146537d37b29be33a605c7a3326672d` |
| `stage-dry-run-bbfbb7e.json` | `14cd51a0095449871cc1561e5c2fb4fc28c15a7f31703847bb9171c312cec289` |

The durable stage outputs bind the same manifest and original paths. Their embedded check compared installed bytes to the manifest with Git binding unchecked. The separate November 18 verification has both installed-equality flags and checked/ok Git binding for this manifest and candidate. That is historical evidence only. The dry run has its own manifest hash and establishes no installation. Current installed identity requires separately authorized stopped preflight.

### Independent review references

The [Supervisor - Build Manager](https://chatgpt.com/c/6af886d5-1964-83e9-8cbc-0201bf682eb1) chat retains full relayed Claude report bodies for the first four rows. The identifiers below identify relay items. Original Claude-session records for these reviews were not located. Review conclusions are R under §1.1. A retrieval can establish a relay item's identity as T.

| Review | Retained reference and status |
| --- | --- |
| Five-file comparator | Full relayed PASS, item `3e06ecf0-669b-47e6-890d-c4fcabd41770`, bound to `457e269` with comparator blob `d11bff10…` |
| Driver practical-result validator | Full relayed PASS, item `c19eae93-9692-4f00-8270-dcd20650f18a`, bound to `457e269` with driver blob `72b43c23…` |
| Practical-precondition assessment | Full relayed PASS, item `7421c788-c1ae-4538-b4e4-09557541154f`, bound to `457e269` with precondition blob `64c19e9d…` |
| Conditional S4 source justification | Full relayed PASS, item `e523f6fa-f9c4-4542-b7cf-f85079a5270e`, covers `735b847..457e269` and requires authenticated run evidence |
| S5 byte-witness source work | Prior acceptance reported. Addendum G and `29c45a8` / `6bf489b` identify policy and source. Full review body and original reviewer record were not located |
| S6 D1 documentation correction | Prior PASS reported. `735b847` identifies the correction. Full report body and original reviewer record were not located. Resolve the retained report reference for L2A |
| External-practical-adjudication re-review | Historical condition 2 requests a narrow re-review. No retained disposition was located. Reconcile whether it was satisfied or superseded before authorizing execution |

Bind existing reports and decisions by exact references. Retrieve missing report references or reconcile the outstanding requirements in the supervisor record. Do not reconstruct a reviewer report from a summary or repeat accepted reviews for bookkeeping.

### Evidence routes to resolve before launch

Review and accept the collection routes before starting the driver. Collect the actual observations at the stated boundaries during the separately authorized run.

| Gate | Collection and decision |
| --- | --- |
| S4 acquisition | Bind the L6–L8 evidence under §2. Record the current public fixture/root and artifact authority during stopped admission. For the actual artifact-bearing closure, bind stable verified store hits or bound any reached cache/repository reads to public software. Include staging, write and cleanup paths through use. The optional §5 advisory probe is insufficient on its own |
| U1 Kodi API effects | Use the source call table and an accepted review of the pinned Kodi API behavior or equivalent bounded evidence covering traceable S4 and S6 effects. Record references and unknowns in L2A. Screen and build identities bind the called path. No complete evidence route for Kodi implementation effects is recorded here |
| U2 Python temp directory | **Blocked.** Capture calls `TemporaryDirectory` without an explicit directory (`resources/lib/create_capture.py:121-139`). MCP window, input and lifecycle controls, helper identity/verify/snapshot, capture markers and adapter `xbmc_metadata_observe` do not report the effective Python temp directory of that Create interpreter (`tools/bm_test_app.py:100`, `4822-4881`, `tools/bm023a_adapter_support.py:1828-1978`, `resources/lib/failure_diagnostics.py:5-18`). Host `TMPDIR`, the Kodi log path and a different interpreter cannot establish it |
| U3 path confinement | Begin with authorized stopped public path and identity admission. Bind actual translated paths, real directory and leaf identities and their stability through use for ArtifactStore, BuildLibrary, FrozenInstallStore and restart paths. Include read, lock, creation, replacement and cleanup targets and rule out path redirection. Current exports do not cover the required runtime confinement |
| U4 startup and independent S7 | A future authorized creation-free observation of `BuildLibrary.publication_journal()` at the confined library root could supply the preflight fact, including acknowledged journals. Pair it with continuity into startup and owner/hold exclusion, or bound every admitted recovery branch and destination. Record U4 independently of S7 MET at both boundaries. The driver's pending check and current exports do not establish U4 |

**Minimum separate U2 evidence change.** Review and explicitly authorize a fixed observation at the existing registration-staging call site in the same Create interpreter. Observe the effective Python temp parent used at `TemporaryDirectory` and bind the actual staging directory to it before the staged writes. Retain an allowlisted record with source identity, launch PID/session, call phase and confinement result, with path evidence protected for verification. Establish a real directory chain, stability through creation and cleanup, and confinement outside the profile and unmanaged add-on locations. Any required source delta needs its own identity binding and review. This mechanism remains unimplemented and unauthorized.

### Stopped admission and authority for a later run

Eric's later authorization must name the full reviewed host and staged
product identities, manifest and adapter 0.0.17, the fixed portable Test.app
target, the exact scenario, and the operator. It must cover the stopped
admission, approved evidence collection, one launch, scoped observation and UI
navigation, physical B-1 input, one confirmation, verified UI exit, one
authenticated PID-bound quit and final stopped verification. It must also
specify the stop and recovery boundaries below. No prelaunch verification or
native operation is authorized by the offline repair.

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
  Establish the stopped public fixture/root and exact artifact authority that
  permitted checks can observe. Assess native-only builtin and platform
  eligibility in the unchanged authorized Create capture. The stopped check
  cannot supply that authority. Missing static admission stops before launch.
  Unsupported or incomplete native capture stops the scenario, with no
  uncontrolled acquisition, local capture, installation or substitution.
  See `.qualification-evidence/a15-eligibility-method-review-20261113/REPORT.md`.
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

### Single execution sequence and external ledger

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

### Execution steps

1. Only after the offline gates and separate authorization are satisfied,
   record the approved full host commit, the card's single `A15_MANIFEST`
   path and verified hash, trusted helper/wrapper hashes, command, environment,
   controller/foreground session handle and UTC start. Complete stopped L2
   admission with that manifest. Create an empty L1–L16 template with L2A and
   retain its hash tool output before starting the driver. Append L1, L2 and
   pre-run L2A in order after supporting records exist. Record open conditions.
   Set `A15_REVIEWED_SHA` to the authorized full host SHA, `A15_MANIFEST` to
   the exact absolute path in the card and `A15_RUN` to one new unused absolute
   direct child of this worktree's qualification folder. Retain L2 and the
   external ledger separately so the driver can create that unused directory.
   Render the values into the first PTY command from the exact worktree:

   ```sh
   DEVELOPER_DIR=/Library/Developer/CommandLineTools \
   /Users/eengert/.pyenv/versions/3.10.9/bin/python3 -B \
     -m tools.bm_preservation_driver \
     --host-commit "$A15_REVIEWED_SHA" \
     --manifest "$A15_MANIFEST" \
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

### Adjudication and stop conditions

Bind the public root ID/version, private off, skin excluded, zero public scope, one separate confirmation and visible 32733 to the same launch and foreground session. Stop on prohibited choices, unexpected or ambiguous UI, wrong terminal, source/PID/session mismatch, failed admission or loss of raw provenance. Below 150 seconds remaining, do not begin confirmation. Follow K1 and B-3 for safe exit. Unverified UI exit prevents quit and FINISH. Failed authenticated quit or final admission prevents FINISH. Any recovery requires separate authorization. CANCEL disposes only the driver baseline. Do not start another Create or driver.

After the single FINISH, reconcile the original result.json, DONE and exit with the sealed ledger. S5 requires identity/enabled and EXACT projection checks. The authenticated scenario may use BYTES_IDENTICAL from after.addons33_bytes.status to adjudicate other Addons33 content. BYTES_DIFFERENT, UNVERIFIED or a refused boundary leaves that disposition open. S8 uses L2 and L12 installed equality and Git binding with the existing bounded source argument. S9 is inapplicable when the correlated rejected Create sequence confirms no receiving operation. Preserve S1–S3 and S7 checks, strict N6, and the existing practical FAIL and INCONCLUSIVE rules. D1's ambient limitation applies only to the narrow S6 claim.

Append later L2A entries only after their raw supporting records exist, in original order. Seal after execution and retain template and ledger hashes and the raw-record index. Independent adjudication follows sealing under §1–§3 and L2A, including actual S4 and U1–U4 dispositions. Missing evidence and unresolved traceable S4/S6 effects keep those dispositions open.

### Minimal external run ledger

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
