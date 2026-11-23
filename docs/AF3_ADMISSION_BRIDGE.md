# AF3 native admission bridge

This procedure is for one separately authorized portable Test.app session.
Independently accept the bridge before use. Keep other launchers and writers
idle throughout the stopped phases.

## Stopped preparation

1. Recheck the Item 4 stopped admission against the accepted receipt, including
   the product and original adapter, public state, sealed 235-file inventory
   and backup, and 17/17 ArtifactStore availability. Use the exact artifacts.
2. Run the following commands from the Codex worktree. Use a fresh protected
   evidence directory outside Test.app for the new receipt.

       python3 -B -m tools.bm_af3_adapter_stage stage
       python3 -B tools/bm_test_app.py af3-verify-zip
       python3 -B -m tools.bm_af3_cache quarantine
       python3 -B -m tools.bm_af3_origin prepare --output /absolute/evidence/af3-before-launch.json

   Require staged, stopped ZIP verification, quarantined, and prepared,
   respectively. Retain the prepare output and its baseline SHA-256. The
   observation baseline requires every AF3 package tree to be free of
   executable caches and checks the pinned service descriptor, entry point,
   monitor source and window-property helper. It records the no-follow source
   identities, add-ons directory identity, ZIP projection and clock boundary.
   These establish only the stopped baseline.

The stage command accepts no target or candidate path override. It pins the
fixed bundle and executable, the sealed archive, both config digests, the
other four adapter members, and the 88-member product. It publishes a durable
owner-only transaction record and staged slot beside the add-ons directory,
then uses Darwin's same-volume atomic exchange to swap the exact config and
slot. The original inode and metadata are retained in the slot. The exchange
moves both files together. The journal records their hashes, inode and stable
metadata, so a stopped retry after an interrupted exchange can verify either
arrangement. The command refuses partial slots, unexpected changes, wrong
target or identity, and mismatches. Preserve the transaction directory on
refusal. Never bypass a mismatch by copying a config over the destination.

## Running admission, before changing skins

3. Launch once via the existing portable MCP launch. Verify the supported
   local control endpoints and expected PID. Run the existing
   af3-health-zip workflow against authenticated loopback HTTP 8080. Require
   requirements_verified, the D-028/PIL authority and all 17 exact dependency
   versions enabled and nonbroken. Preserve that result and use its PID below.
4. With Estuary still active and before launching any add-on manually, run:

       python3 -B -m tools.bm_af3_origin observe --baseline /absolute/evidence/af3-before-launch.json --baseline-sha256 BASELINE_SHA256 --expected-pid HEALTH_PID

   The existing helper prompts for the HTTP password on the controlling
   terminal. Keep credentials out of arguments, logs and evidence.
   Retain the sanitized JSON output. Require status observed, the same PID,
   authenticated true, 17 portable_home registrations, startup_marker true and
   the fresh monitor cache digest. A missing, substituted or unrecognized
   observation stops admission. Use authenticated graceful quit and the
   stopped preservation/rollback steps below without activating AF3.

### What the runtime observations establish

- The build-pinned Kodi JSON-RPC Addon.Fields schema supports path. An
  authenticated PID/listener-bound Addons.GetAddonDetails call requires exact
  id, version, enabled and nonbroken state and a registered path equal to the
  verified portable-home path, its Data-volume spelling or the exact
  special://home/addons alias. The alias relies on the admitted fixed portable
  launch. The host opens only the fixed local directory without following
  symlinks. This is registration origin, with no execution implication.
- The pinned TMDb Helper service descriptor starts resources/service.py.
  That entry imports the monitor and invokes ServiceMonitor.run. The reviewed
  monitor publishes TMDbHelper.ServiceStarted=True after its initialization
  calls. The admitted observer requires this in the new Kodi process and the
  exact newly created CPython 3.11 opt-1 monitor cache whose timestamp header
  agrees with the pinned source. Those are independent signals of initialized
  service code and fresh source compilation in the controlled cache-free
  session. The observer hashes the cache without unmarshalling or executing it.
  The receipt is scoped to that startup chain. It does not identify every
  runtime import or turn content-only registrations into Python evidence.
- The cache header is a consistency witness, not a cryptographic binding of
  marshalled payload to source. Evidence assumes the pinned packages, a single
  clean launch, the verified cache-free baseline and no other writers.
  Host mock receipts and APFS tests establish the observer's predicates only.
  If Kodi does not return the marker or produces no matching fresh cache, do
  not substitute package hashes, log start messages or status for that witness.

Primary Kodi sources:
[JSON-RPC add-on schema](https://github.com/xbmc/xbmc/blob/a3a448d26b/xbmc/interfaces/json-rpc/schema/types.json#L4123-L4172)
and [info label RPC](https://github.com/xbmc/xbmc/blob/a3a448d26b/xbmc/interfaces/json-rpc/XBMCOperations.cpp#L16-L40).

## Active AF3 and stopped closure

5. Follow the accepted Item 4 run card. Verify Estuary fallback once, perform
   manual Keep, and observe sustained native AF3 activation and the 15 typed
   supported settings. Claim only behaviors actually observed. Capture the
   declared public build with private capture off and zero files. Confirm
   Slide=false, change only Slide to true, review the exact one-setting plan,
   confirm once, verify typed false and saved/applied association, then verify
   no further correction. Stop on ambiguity without repeating a mutation.
6. Exit the UI and gracefully quit the admitted PID. Require zero Test.app
   processes. Run af3-verify-zip while the candidate remains staged; compare
   installed product, AF3 packages, public state, generated includes and new
   caches against the recorded baseline and authorized changes.
7. Run the accepted cache restore. Retain both versions if a new cache occupies
   an original name. Record the collision, without overwriting or deleting
   either version. With stopped identity and the original rollback slot
   verified, run:

       python3 -B -m tools.bm_af3_adapter_stage restore

   Require restored and the original five-file adapter tree
   da73b03e894a49e89a0f38448c92f158c76fe59ec64bff3b1e57e3d2c56f40e4.
   Verify stopped identity and the final public state. Retain the protected
   journal, candidate slot and receipts with checksums.
