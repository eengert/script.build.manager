# AF3 qualification with the sealed Build Manager ZIP

The ZIP route shares the existing authenticated platform_check and AF3 native
health logic. The Git-stage af3-health command and its manifest pin retain
their original admission requirements.

## Candidate and independent review

The original Build Manager 0.1.0 ZIP is authenticated by its sealed archive hash
and final 88-member tree. The verifier checks the 89-member Git-stage manifest
separately. The new projection binds the packaged addon.xml bytes and excludes
the approved synthetic BM-022 fixture. Other packaged files are authenticated
against the original Git blobs and the sealed ZIP. The existing tree verifier
checks the full installed projection before and after diagnostic dispatch.

The candidate differs from the original five-file adapter in one generated
assignment in adapter_config.py. The AF3 graph pin and all other configuration
bytes are preserved. The four source files come from the authenticated Git
objects. The health route reverses the assignment in memory and requires the
original sealed config hash before accepting the new bytes. Preparation
verifies the original five-file adapter.

Run the offline preparation command below to write a mode-0600 candidate to a
new path outside Test.app in a protected evidence directory. The receipt reports
native health as unverified. Treat the artifact as machine-local.

    python3 -B tools/bm_test_app.py af3-prepare-zip --candidate-zip /absolute/protected/evidence/adapter-candidate.zip

Review the isolated candidate and the prior cache tool independently before
any Test.app change. Retain the existing adapter for separately authorized
stopped-state recovery.

## Native admission after acceptance

1. Obtain explicit authority to stage the exact reviewed adapter candidate to
   the stopped disposable Test.app. Use a reviewed isolated adapter staging
   procedure with rollback evidence. Keep the 88-member product and AF3
   packages intact. Verify the resulting five-file adapter identity and exact
   product inventory before launch with:

       python3 -B tools/bm_test_app.py af3-verify-zip
2. Follow the [AF3 cache qualification runbook](AF3_CACHE_QUALIFICATION.md) for
   fresh stopped admission, cache quarantine and the normal portable MCP launch.
3. Use the approved authenticated HTTP credential path for the fixed loopback
   listener at 8080. Invoke af3-health-zip before changing skins or entering
   Build Manager. Require current portable PID/listener ownership, a fresh
   platform_check with requirements_verified for the pinned AF3 graph, and all
   17 exact-version dependencies enabled and nonbroken. Verify embedded Kodi
   source loading separately.

    python3 -B tools/bm_test_app.py af3-health-zip --rpc-host 127.0.0.1 --rpc-port 8080 --rpc-user kodi --output /absolute/protected/evidence/af3-health-zip.json

Use the existing approved credential integration if the session calls for it.
Never place a password in a command argument. Complete the authorized scenario
through graceful quit and collision-safe cache restoration.
