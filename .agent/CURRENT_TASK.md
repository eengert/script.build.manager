# Current Task

## BM-017F — Deferred Activation & Structured-Resource Lifecycle

**Status**: `COMPLETE` on protected `matrix`. The reviewed substantive worker
endpoint diff was reconstructed as matrix commit
`4dfd97e180d14976adec8540d5c0c93893519249`; `.agent/**` worker history was not
cherry-picked and worker history was not rewritten. The 33-file integration
contains the BM-017F production lifecycle, schema, resource/import handling,
tests, disposable validation harness, and sanitized audit. No unrelated
product changes or disposable profile contents entered matrix.

The supervisor-provided final disposable run passed all eight steps and all
twenty listed checks. It proved the activation hold survived restart, private
resource initialization and verification completed before release, Red Light
started after release, the exact artifact/dependency inputs were retained,
and idempotency, database shape, WAL, unrelated-state preservation, and fake
value redaction checks passed.

- BM-017F: `COMPLETE`.
- Red Light structured private-resource lifecycle: `LIVE-VALIDATED`.
- macOS BM-023A: `READY_TO_RETRY`; the retry was not started.
- tvOS: `NOT VALIDATED`.

Matrix automated validation passed: focused BM-017F/lifecycle/resource/import/
harness modules **499/499**; full repository suite **1782/1782**;
`compileall`; parsing of all **7 tracked JSON files**, including the schema;
and `git diff --check`. During validation, one import-spy assertion was made
order-safe after Python 3.14 `unittest.mock` target resolution was counted as
two incidental `builtins` imports. This was a test-only correction; production
behavior did not change.

This integration did not launch Kodi or access a normal Kodi profile, a real
device, or private overlay values. The final live-validation evidence was
supervisor-provided and restricted to the disposable `.kodi-test` scope.

**Smallest next step**: normally merge the pushed `matrix` update into
`agent/codex`, then wait for the separately supervisor-authorized macOS
BM-023A retry against `/Applications/Kodi Build Manager Test.app`, launched
with `open "/Applications/Kodi Build Manager Test.app" --args -p`. Do not run
that retry as part of this integration.

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
