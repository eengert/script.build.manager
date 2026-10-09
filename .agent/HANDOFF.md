# Handoff — Trusted add-on root authority correction (pending independent re-review)

- State: product correction committed for independent re-review: `ace8b77` ("Pin trusted add-on root authority to the recorded directory object"), on top of `b8d7a06` and `b0835a2`. Neither prior commit was amended. **The bundled-capture defect is NOT claimed closed.** It remains pending independent re-review of `ace8b77`. Item 8 and restart/resume stay OPEN. Publication stays unauthorized.
- Start: `agent/claude` at `b0835a2`, worktree clean.
- Review finding addressed: trusted-root acquisition used a full-path open with O_NOFOLLOW, which protects only the final component. An ancestor replaced after construction with a symlink was followed. Reproduced on `b8d7a06`: the read returned the outside `addon.xml`, and the reviewed capture reached `COMPLETE` with the outside dependency edge.
- Fix: each configured root is canonicalized and opened component by component at construction (O_NOFOLLOW, relative to the previous descriptor). Its `(st_dev, st_ino)` is recorded, and the descriptor is held so the recorded inode cannot be recycled. Each read re-walks the canonical path from an anchored root, requires directories at every step, requires the final object to match the recorded identity, and only then opens the add-on directory and `addon.xml` relative to it. Replacement, root symlinks, same-path directories, and stale absolute paths fail closed as `addon.xml unavailable`, with no host path exposed. `close()` releases the descriptors.
- Tests: 10 new `TrustedRootAuthorityTests`. Six failed on `b8d7a06` for the reviewed reasons. All pass on `ace8b77`, on dev Python and on `/usr/bin/python3` 3.9.6. Child, addon.xml, identifier, identity, version, home, and bundled path tests are unchanged and pass.
- Focused modules (dev Python): test_frozen 37, test_create_capture 59, test_create_workflow 98, test_frozen_install 48, test_frozen_resolution 32, test_recorded_resolution_lifecycle 8, test_dependencies 148, test_status 102, all OK. Under Apple Python the same modules pass, except the pre-existing `assertNoLogs` error in test_create_workflow that the parent also has.
- Full suite (dev Python): candidate `Ran 3266, FAILED (failures=2, errors=4)`; parent `b0835a2` `Ran 3256, FAILED (failures=2, errors=4, skipped=5)`. Failing and erroring names are identical (4 keychain errors and 2 known import-policy failures). Candidate-only and parent-only sets are empty.
- Known residual limits (not blocking this correction):
  1. Anchored reads are verified with synthetic filesystem fixtures. They are not live-proven against Kodi's real path forms.
  2. The `KodiRuntimeDependencyBackend.read_addon_xml` fallback is unchanged, as requested. It fails closed.
  3. The downstream ZIP-versus-recorded-edge defense is not added, as requested.
- Not done: no Test.app staging or launch, no live Red Light database or private overlay access, no PIL sourcing, download, or import, no push, no release, no publication, no Agent Handoff.
- Smallest next step: independent re-review of `ace8b77`, then the exact `script.module.pil` 5.1.0 artifact decision for the Item 8 fixture. Do not source 1.1.7.

## Correction addenda (historical entries kept as written)

- The stopped Item 8 fixture record said `script.module.pil` was absent from Test.app. That was a stopped-state probe limitation. Test.app's application bundle ships `script.module.pil` 5.1.0 under `Contents/Resources/Kodi/addons/`, and Red Light 2.6.8 requires `>= 1.1.7`, which 5.1.0 satisfies.
- The earlier handoff said the bundled-capture defect was pending independent review of `b8d7a06`. That review returned NOT PASS on exactly one blocker: the ancestor replacement escape. `ace8b77` is the correction for that blocker, and it is pending re-review. Nothing is closed.
