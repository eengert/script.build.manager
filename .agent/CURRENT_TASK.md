# Current Task

## BM-017E — Structured Private Resource Initialization & Quiescence

**Status**: Complete as a static investigation. Result:
`BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`. The sanitized audit
was integrated from worker commit `e94046d84145ce570e3a49fa25706ae03351997a`
as matrix commit `7075d59`; worker `.agent/*` was excluded.

The audited Red Light 2.6.8 package SHA-256 is
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`.
Red Light's `ensure_database_tables('settings_db')` owns settings-table DDL;
`connect_database()` establishes WAL; and `sync_settings()` seeds defaults but
also performs migrations and other settings behavior. Normal enabled startup
performs broader database maintenance and starts background workers. The
observed pause/disabled signal does not prove worker quiescence. BM-022 applies
final enabled state before private configuration, while BM-020/BM-022 resume
cannot preserve a structured-resource lifecycle stage across another restart.
The current production path therefore cannot prove Red Light remains safely
quiesced through initialization and private apply.

No add-on code was run. BM-023A-R1 remains historically
`BLOCKED_RESOURCE_NOT_INITIALIZED`; its Mac retry remains blocked and was not
resumed. tvOS remains NOT VALIDATED. Matrix integration validated the audit
tracking fields and `git diff --check`; no product tests were run for this
documentation-only change.

**Smallest next step**: synchronize Codex with matrix, then begin the separately
authorized BM-017F deferred-activation/lifecycle work. Do not resume BM-023A.

---
## BM-023B — Frozen Artifact Fallback & Install Recoverability

**Status**: Complete on protected `matrix`. Reviewed substantive worker commit
`1d60ed39b36a1b25ac4c0d912712a55fe9a17e8f` was cherry-picked as
`5648c6781b4567d3b2f0931fc4ed838142ed22f1`. Worker `.agent/*` files were not
integrated; matrix tracking is neutral (`active_agent: none`). Starting matrix
was `b82885ab01fdb3c2486fff0c3e42bf33262b110e`.

Exact captured artifacts remain preferred and strictly validated. Repository
fallback and Skip require explicit policy and user choice; fallback requires a
concrete trusted repository represented by an exact captured package. Skip is
checked against dependency closure and remains absent from installed state.
Source capture, install plan, resolution, and resolved-software identities
remain distinct. Restart-safe metadata preserves resolution without rewriting
the source manifest.

Family Room captured desired state remains COMPLETE, with 30 / 31 exact
artifact-backed installed managed add-ons. The source fingerprint remains
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
YouTube `7.4.4+unofficial.2` exact artifact is unavailable; trusted repository
provenance is not established. Its explicit policy permits Skip or Cancel Build
and retains the manual-install warning. Absent optional `script.module.pysocks`
remains absent.

Matrix validation passed: relevant focused module suites **581/581**, full
repository suite **1643/1643**, `compileall`, schema/example JSON parsing, and
`git diff --check`. These were automated fixture tests; Kodi, Family Room, any
device, the portable profile, and private overlay values were not accessed.

BM-023A remains historically `BLOCKED_MISSING_FROZEN_ARTIFACTS`; BM-023A-R and
BM-023A-H remain complete. BM-023A-R1 is architecturally unblocked but
**NOT YET EXECUTED**. tvOS validation remains **NOT VALIDATED**.

**Smallest next step**: normally merge the new `origin/matrix` into
`agent/codex`, preserve worker history while semantically resolving `.agent`,
push only `agent/codex`, then begin the separately authorized BM-023A-R1
macOS test-app validation.

---

# Previous Task Records

## BM-023A-H — Historical Exact Artifact Recovery

**Status**: Complete with result
`EXACT_YOUTUBE_7.4.4_UNOFFICIAL_2_NOT_RECOVERED`. Public exact-version
metadata and repository provenance searches located no exact `.2` package,
package URL, provider checksum, archived entry, or `.2`-specific source
commit. The generic source-build path did not identify the `.2` build. No ZIP
was downloaded, imported, substituted, or repackaged.

The retained manifest and artifact store are unchanged. Production
`validate_frozen_manifest` rejects the installed managed YouTube
`7.4.4+unofficial.2` artifact; absent optional `script.module.pysocks` remains
artifactless and excluded from installation. The original manifest fingerprint
is unchanged at
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
Focused frozen tests passed **25/25**. The integrated BM-023A-R matrix suite
passed frozen **25/25**, dependency regressions **147/147**, full suite
**1607/1607**, and `git diff --check`.

No Family Room/device, Kodi, portable profile, or private overlay was accessed
or modified. BM-023A remains historically `BLOCKED_MISSING_FROZEN_ARTIFACTS`;
installation was not resumed.

**Smallest next step**: begin the separately authorized BM-023B worker task
for explicit exact-artifact fallback and installation recoverability. Keep the
captured manifest immutable and do not resume BM-023A installation.

## BM-023A-R — Frozen input completeness reconciliation

**Status**: Complete on protected matrix with result
`MANIFEST_SEMANTICS_CORRECTED_BUT_ARTIFACT_GAP_REMAINS`. Reviewed worker
implementation `a8d4b71` was integrated as matrix commit `ff5c000` from the
supplied base `5a3598f565ad5b0c0164215eeefdf39b54a1d682`. Matrix remains
neutral with `active_agent: none`.

The generalized completeness rules are:

- Every installed non-system node in frozen desired state requires its exact
  artifact, including nodes reached only through optional edges.
- `script.module.pysocks` was absent on the source, appears only through
  YouTube optional dependency metadata, needs no artifact, and is excluded from
  the install schedule.
- Installed, enabled `plugin.video.youtube` `7.4.4+unofficial.2` remains part
  of managed frozen desired state through an optional edge and still requires
  its exact artifact.
- System/runtime nodes remain artifactless declarations.
- A manifest marked complete is accepted only when production
  `validate_frozen_manifest` agrees.

BM-023A remains historically complete as a validation task with result
`BLOCKED_MISSING_FROZEN_ARTIFACTS`. The exact remaining gap is
`plugin.video.youtube` `7.4.4+unofficial.2`.

Validation from the integrated matrix tree: frozen capture/manifest/install
**25/25**; dependency regressions **147/147**; full suite **1607/1607**;
`git diff --check` clean. These were automated tests only. No Kodi instance
was launched, the portable test profile was not modified, Family Room or any
device was not accessed, and no private overlay values were read.

**Smallest next step**: synchronize the Codex worker with protected matrix,
then continue the separately authorized BM-023A-H public historical artifact
recovery. Do not resume BM-023A installation until the exact frozen input
passes production validation.
