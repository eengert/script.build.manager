# Handoff — Item 8 Red Light restart/resume qualification (STOP, NOT PASS)

- State: stopped at the fixture gate. Verdict: **NOT PASS**. Nothing was registered, applied, launched, restarted, or changed in durable state. Item 8 stays OPEN. Restart/resume stays OPEN. Publication stays unauthorized.
- Start: `agent/claude` at `16b87d873339229287dbd830ed7860aafa90a4e3`, worktree clean. Agent Handoff read-only status: claude at `16b87d8`, clean. Test.app `not_running`.
- Done:
  - Standalone Git-bound verify of candidate `7b625cc3aa58fcc4d50660172a4a67ada326fb4c` against the existing stage manifest: `installed_equals_manifest` true, `installed_equals_candidate` true, `git_binding` checked and ok, `problems` `[]`. No restage.
  - Preflight durable baseline (product read-only APIs and `snapshot --library-baseline`): A applied; publication acknowledged and tied to A; B selected; transactions absent; updater `AUTOMATIC`; Red Light 2.6.8 installed and enabled; registry A/A2/B/C/D.
  - Fixture E public graph built in scratch and checked with production capture (in memory). Not registered.
  - No-seeding gate run value-blind (counts and metadata only).
- Blockers, both independent:
  1. **Fixture E is not a complete graph.** Red Light 2.6.8 has a required `<import>` of `script.module.pil` 1.1.7. pil is not installed in Test.app, not in the public ArtifactStore, and not in the local repository listing. Production capture reports `MISSING`.
  2. **Red Light readiness fails closed.** The existing `settings.db` is non-empty (diagnostic, count only). The product's own non-empty check uses a `mode=ro` SQLite open. That open fails on a cleanly closed WAL database with no `-wal`/`-shm` sidecars (reproduced in scratch; `immutable=1` reads it). Production cannot verify readiness, so the gate fails closed. No seeding or initialization was attempted.
- Not done: private compatibility gate (overlay not opened); E registration; Apply; Test.app launch, navigation, restart, resume; second-run proof; final proof.
- Live-proven in this task: nothing new. No Test.app launch.
- Tests: none run. The task changed no product source.
- Risks and human decisions:
  1. **pil.** Choose: (a) authorize one exact `script.module.pil` 1.1.7 artifact (name the source and SHA-256) to be imported to the public ArtifactStore and installed in Test.app as part of E; or (b) choose a fixture that does not depend on pil.
  2. **Red Light readiness.** Choose: (a) authorize a bounded product change so the read-only settings check verifies a cleanly closed WAL database, then a separate run; or (b) authorize a different verification path. Check whether a live Kodi profile is affected too. That was not tested.
  3. The Red Light overlay was not opened. Its binding to E is still unchecked. It depends on E's final fingerprint, so it has to be checked after decision 1.
- Usage: start 5-hour 16%, weekly 56%. End 5-hour 19%, weekly 56%. Session reported `claude-haiku-5-5` at effort `xhigh`.
- Cleanup: scratch scripts and temporary reproduction databases removed. Evidence kept under `.qualification-evidence/item8-restart-resume-redlight-20261009/` (gitignored).
- Smallest next step: decide 1 and 2 above, then one bounded task for the chosen path.
