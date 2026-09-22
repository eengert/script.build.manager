# Current Task

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
