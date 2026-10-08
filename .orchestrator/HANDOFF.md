# Current Handoff — Build Manager Manual Mode (refreshed 2026-10-08)

## Operating mode

- **Manual relay** (D-025): ChatGPT plans and reviews, Eric relays one bounded prompt at a time, and Claude or Codex executes exactly that prompt and reports back. No agent selects the next project task.
- ai-supervisor is retired cold storage. Do not start, resume, reinstall, or depend on it.
- Working lane: **Claude**, `agent/claude`, worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude` (Agent Handoff endpoints, D-026). This refresh did not run the live Agent Handoff status command. Check live ownership before relying on the lane.
- No push, release, or `matrix` integration by default. All `agent/claude` commits after `origin/agent/claude` are local and unpushed.

## Current milestone

**Build Manager macOS Beta Qualification.** The finish line is the eight-item Beta exit checklist in `BUILD_MANAGER_PROJECT_PLAN.md`.

- Items 1-7: accepted backend qualification evidence remains intact.
- Item 8 (complete user-facing workflow through the Kodi UI, including Estuary, restart/resume, error states, and second-run presentation, tied to an exact candidate): **OPEN**.
- Beta Candidate phase exit (repository-distributed package, custom icon, install/update through the Eengert Repository, repository-distributed qualification): **NOT COMPLETE**.
- Do not describe beta qualification as complete.

## Product state

Package version in `addon.xml`: **0.1.0**. The "BM 0.0.15 candidate" wording in earlier handoffs is historical.

- **Create Build:** implemented; previously qualified.
- **Install Build:** implemented; previously qualified.
- **Update / Repair:** implemented and independently reviewed. Live portable Test.app PASS:
  - verified no-op: Current / Healthy, no changes, no durable mutation;
  - supported enablement repair: `repository.eengert` disabled deliberately, enable-only review, re-enabled without reinstalling, second check Current / Healthy;
  - missing exact managed add-on restoration: `repository.eengert` 1.0.0 uninstalled deliberately, exact frozen artifact `5a0ee9bf94e900ed4c7f09a2eff82b2f36c7854fd45796a4c6bb2e564569ea86` restored, no Repository Current fallback, second check Current / Healthy.
  - Evidence: `.qualification-evidence/update-repair-noop-20261008T203627Z`, `.qualification-evidence/update-repair-enable-drift-20261008T205800Z`, `.qualification-evidence/update-repair-missing-exact-addon-20261008T211207Z`.
- **Build Status, Settings, Help / Information:** native Kodi UI exists. Help H01-H10 was rewritten in plain language (BM-UI-002A). Not recorded here as fully item-8 qualified.

Offline Update / Repair chain: `866080ef9d687879fdcb02efa480e34ae34dff99`, `326e52d5b2d4e24f870d3ab11aadd61fc9b2c496`, `53f221986b6c76d5d13652421ac62f999c0c6aab`. NB-1 terminal-record coverage: `723c254b737446975e8c77e12b0ce7a62951ddbf`.

## Installed runtime candidate versus newer unstaged metadata

- The installed Test.app runtime candidate for every live qualification above is **`53f221986b6c76d5d13652421ac62f999c0c6aab`**.
- Product source (`resources/`, `tools/`, `default.py`, `service.py`) is identical between `53f2219` and current HEAD. Verified by path diff.
- Commits after `53f2219` touch only tests, docs, `.orchestrator/**`, `.agent/**`, and `addon.xml`:
  - `6105282b5340ba15f0ca4b231ce1e27c42d3cb81` package metadata refresh (news, en_US/en_GB descriptions, focused metadata test);
  - `5f0dd67045079fbeff9651f782a4ff14f27cef33` package summary correction to `Capture and apply a managed Kodi setup.` in both English locales.
- **Metadata at `6105282` and `5f0dd67` is NOT staged or live-proven in Test.app.** The installed Test.app still carries the old stale package text ("not available yet" news and "Save and restore" summary). The new metadata is covered by unit tests and XML validation only.

## Remaining beta/package blockers

1. **Item 8, complete-workflow qualification: OPEN.** Durable Estuary, restart/resume, error-state, and second-run evidence for the complete frontend, tied to one exact candidate, is still needed. The Update / Repair scenarios above are recorded. Create, Install, Status, Help, and Settings are not recorded here as complete across that full set.
2. **Custom icon: OPEN (hard package-exit check, `CUSTOM_ICON_ASSET_REQUIRED`).** `resources/images/icon.png` on `agent/claude` is still the generic skeleton icon. `matrix` carries a much larger `resources/images/icon.png` (last changed in `a33a3f8`, "chore: add Build Manager addon icon"). Whether it is Eric's approved artwork has not been verified. Decide and verify before packaging.
3. **Eengert Repository publication and install/update through it in portable Test.app: not recorded as done.**
4. **Live staging of the metadata commits (`6105282`, `5f0dd67`) in Test.app: not done.**
5. **Integration of this lane into `matrix`: not done.** It needs a separate, explicit decision.

## Safety boundaries

- Authorized runtime target: **`/Applications/Kodi Build Manager Test.app` in portable `-p` mode only.**
- Default launch: `open -g "/Applications/Kodi Build Manager Test.app" --args -p`. `-p` is mandatory. Use foreground activation only when a specific validation task requires it.
- Standalone Test.app MCP interaction is qualified and supported. Use it only inside a named task.
- Forbidden for BM validation: normal `/Applications/Kodi.app`, and `/Users/eengert/Library/Application Support/Kodi`, including read or probe access.
- Household Kodi devices (Apple TV, Shield, Fire TV): mutation needs Eric's explicit authority naming the device and the action. Completing portable Test.app work does not authorize normal Kodi or device validation.
- No push, release, force-push, or history rewrite without explicit authorization. The only standing exception is the agent-switch push in D-026.
- Do not expose credentials, tokens, private overlay values, or secrets.

## Next step

No implementation task is pre-selected. ChatGPT chooses the next bounded task and names its blocker. Open decisions for Eric and ChatGPT:

- whether to stage `agent/claude` HEAD in portable Test.app for live metadata proof (needs a named task);
- which icon artwork is authoritative (`matrix` versus this branch);
- when and how to integrate into `matrix`.

Do not restart Status, G1-G6, Create, Install, or Update / Repair implementation. These are implemented and recorded above. Reopening any of them needs a new bounded task that names a specific blocker.

## Stable references

- `BUILD_MANAGER_PROJECT_PLAN.md`: eight-item exit checklist and Beta Candidate phase exit.
- `.orchestrator/PROJECT.md`, `.orchestrator/WORKFLOW.md`, `.orchestrator/DECISIONS.md` (D-025 manual relay, D-026 Agent Handoff endpoints).
- `AGENTS.md`, `CLAUDE.md`.
- Approved backend baseline: `4a02b833178f5cb29e2b596985f1a8641ed3fa25`.

Ai-supervisor archives, `BUILD_MANAGER_SUPERVISOR_HANDOFF.md`, and old `.agent/**` records are historical evidence only. They do not override current Git or this file.
