# Handoff — Test.app package metadata and custom icon smoke

- State: **PASS** (12-point standard). `a2b1ffc` staged into portable Test.app and checked in the Kodi UI. Test.app is stopped. Build Manager durable state is unchanged. Local only: no push, no release, no matrix, no Agent Handoff operation.
- Start: `agent/claude` at `ba11e48`, clean, ahead of origin. Live Agent Handoff: current agent `claude`; `agent/codex` `67c0a9e` clean, ahead; `agent/claude` `ba11e48` clean, ahead; Antigravity unavailable. Test.app not running. Installed runtime before the run: `53f2219`, Git-bound verified.
- Staged: `a2b1ffcf77123d269d0e21452a316186950eec1a`. One supported dry run, then one real stage with `tools/bm_test_app.py` (sha256 `7688234891be...305fb8b`). Config: `/private/tmp/bm-ui-install-37258ad-current-device.json`, not printed. Its configuration fingerprint equals the one in the accepted `53f2219` manifest. Stage manifest: `stage-20261008T225724Z-a2b1ffcf7712/stage_manifest.json`, sha256 `48b5a2014c1b7580c8c39dba947c6cb86842650301640cae776b9c3c442db5ed`.
- Git-bound verify, post-stage and post-run: `ok`; `installed_equals_manifest` and `installed_equals_candidate` both true; `script.build.manager` 66/66 files and `.bm023a_driver` 5/5 files match.
- Installed package: `addon.xml` is byte-identical to `a2b1ffc`, version `0.1.0`. Summary en_US and en_GB: "Capture and apply a managed Kodi setup." None of "not available yet", "still being built", "Save and restore your Kodi setup" is present. Icon: valid 512x512 PNG, all chunk CRCs ok, SHA-256 `207c44a0…628d23`, byte-identical to the candidate.
- Live, through `test_app_*` MCP tools only:
  - Custom icon visible in the Program add-ons row and in the My add-ons "All" list.
  - Info view shows the corrected summary as its heading, then the refreshed description (Create Build / Install Build / Update / Repair / Build Status).
  - Native menu opened twice (once from the tile, once from Run) and showed six items in order: Create Build, Install Build, Update / Repair Build, Build Status, Settings, Help / Information. No item was entered.
  - Exit: backed out to the All list with no Build Manager dialog open, then one graceful quit (`stopped`) and one observe (`stopped`).
  - `kodi.log`: only the benign "failed to stop script.build.manager (may have ended)" line. No kill line and no "didn't stop".
- Durable state, pre vs post: zero differences in the applied-state inspection (association, publication journal, library registry and selection, applied resolution manifest, transaction locks), the frozen-artifacts census (61 entries), and the helper snapshot (updater policy `AUTOMATIC`; frozen and restart transactions `absent`). The comparator was self-tested to detect changes.
- Allowed ephemera: `.pyc` files in the installed `script.build.manager` tree: 43 now, 50 in the replaced `53f2219` tree. Both are `__pycache__` only.
- Live-proven: `a2b1ffc` staging into Test.app; installed files; custom icon; corrected summary and description in the Kodi info view; six-item menu; clean exit.
- Unit-tested only: nothing new. No product code changed and no test suite was run in this task.
- Not done: no workflow entered or mutated (Create, Install, Update / Repair, Status, Settings, Help). No normal Kodi, Application Support/Kodi, device, direct JSON-RPC, Computer Control, push, release, or Agent Handoff action.
- Deviations, recorded for review:
  1. Two `verify` invocations failed before the valid one. The first used a wrong manifest path (glob width). The second returned `output_exists` because the first had written its error file. Both error files are kept as `p3-verify-attempt1-*` and `p3-verify-attempt2-*`. Verify is read-only, so the Test.app state was not affected.
  2. The stage's internal `post_stage_verify` reports `installed_equals_candidate: false`. It runs without Git binding, so that is expected. The standalone Git-bound verify is the proof.
  3. The first package-proof run reported `pass: false`. That was a bug in my own IEND offset check. The first output is kept as `p4-installed-package-proof-run1-iend-offset-bug.json`. The corrected run uses a full PNG chunk and CRC walk and is authoritative.
  4. Selecting the Program add-ons tile runs Build Manager and opens its native menu. It does not open the info view. The info view was reached through My add-ons → All → Build Manager → Select.
- Out of scope, noticed, not fixed:
  - Third-party toasts appeared during the run: Red Light "authorisation failed", and an Umbrella update notice.
  - `kodi.log` shows `Unknown addon id 'repository.umbrella'`, and TMDb Helper `GetDirectory` errors at shutdown.
- Risks and human decisions:
  1. Test.app's installed runtime is now `a2b1ffc`, not `53f2219`. Earlier Update / Repair evidence still refers to `53f2219` and stays valid as history. Verify the installed candidate before any future live run.
  2. `.orchestrator/HANDOFF.md` still states that the installed candidate is `53f2219` and that the metadata and icon are unstaged. That is now stale. It was not edited here because this task limits bookkeeping to `.agent/`. ChatGPT should refresh it.
  3. CLAUDE.md lists Sonnet and Opus as the Claude models. This session reported `claude-haiku-5-5` at effort `xhigh`. The usage row records what was reported.
- Evidence: `.qualification-evidence/bm-testapp-package-icon-smoke-20261008T225641Z/` (git-excluded, not committed). Checksums are in `EVIDENCE_SHA256.txt` there.
- Human decision needed before the next step: whether to integrate `agent/claude` into `matrix`, and which bounded live step follows open item 4 in `.orchestrator/HANDOFF.md`. No next task is pre-selected.
