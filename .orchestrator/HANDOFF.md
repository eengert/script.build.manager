# Current Handoff — Build Manager Manual Mode (refreshed 2026-10-08)

## Operating mode

- **Manual relay** (D-025): ChatGPT plans and reviews, Eric relays one bounded prompt at a time, and Claude or Codex executes exactly that prompt and reports back. No agent selects the next project task.
- ai-supervisor is retired cold storage. Do not start, resume, reinstall, or depend on it.
- Working lane: **Claude**, `agent/claude`, worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude` (Agent Handoff endpoints, D-026). Confirm live ownership with the status command below before relying on the lane.
- No push, release, or `matrix` integration by default. All `agent/claude` commits after `origin/agent/claude` are local and unpushed.

## Live Agent Handoff status (read first)

Read the live status before relying on lane ownership or issuing a mutation prompt:

```bash
AGENT_HANDOFF_PROJECT=build-manager /Users/eengert/Documents/Kodi/agent-handoff/src/agent_handoff_controller.sh status
```

- The command is read-only apart from a bounded fetch of `origin/matrix`. Do not run `continue`, `set-active-agent`, or any other Agent Handoff operation without Eric's explicit request (D-026).
- `AGENT_HANDOFF_PROJECT=build-manager` is required. Without it the controller falls back to a saved project state or to the `backup-pro` project.
- **Live output overrides this snapshot.** Last recorded check, reported in the 2026-10-08 icon task prompt: current agent `claude`; `agent/codex` at `67c0a9e`, clean, ahead; `agent/claude` at `f97ca32`, clean, ahead; Antigravity unavailable.

## Current milestone

**Build Manager macOS Beta Qualification.** The finish line is the eight-item Beta exit checklist in `BUILD_MANAGER_PROJECT_PLAN.md`.

- Items 1-7: accepted backend qualification evidence remains intact.
- Item 8 (complete user-facing workflow through the Kodi UI, including Estuary, restart/resume, error states, and second-run presentation, tied to an exact candidate): **OPEN**. Not accepted. It remains open pending ChatGPT review of the 2026-10-08 evidence consolidation (`.qualification-evidence/item8-evidence-consolidation-20261008T232026Z/`), which reports a remaining live gap. That report is evidence and does not accept or close Item 8.
- Status applied-versus-selected presentation gap: **CLOSED IN SOURCE** (product commit `5d2bf55`, with the independent-review label correction in `65ef014` the private-identifier boundary correction in `bc6d596`, and its per-build scope correction in `ca41133`). Live Test.app proof is **still pending**. Restart/resume, error-state, artifact-decision and multi-build UI gaps **remain**, so Item 8 stays **OPEN**.
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

- The installed Test.app runtime candidate is now **`a2b1ffcf77123d269d0e21452a316186950eec1a`** ("Add approved Build Manager icon"). It was staged from exact Git objects and is Git-bound verified (`installed_equals_candidate` true).
- **a2b1ffc package/icon live smoke: PASS** (2026-10-08, portable Test.app, `.qualification-evidence/bm-testapp-package-icon-smoke-20261008T225641Z/`). It showed the corrected `addon.xml` metadata, the approved 512x512 custom icon in Kodi, the corrected summary, the native six-item menu, a clean exit, and no Build Manager durable-state mutation.
- Earlier live qualifications (Create, Install, applied association, Update / Repair) ran on earlier candidates. Their transfer to `a2b1ffc` is assessed in the consolidation evidence and is not assumed here.

## Remaining beta/package blockers

1. **Item 8, complete-workflow qualification: OPEN.** Durable Estuary, restart/resume, error-state, and second-run evidence for the complete frontend, tied to one exact candidate, is still needed. The Update / Repair scenarios above are recorded. Create, Install, Status, Help, and Settings are not recorded here as complete across that full set.
2. **Custom icon: CLOSED** (`CUSTOM_ICON_ASSET_REQUIRED`). `resources/images/icon.png` is the approved custom Build Manager icon (512x512 PNG, SHA-256 `207c44a0474e7e370cf6d210c7646ce243c704a0694ef422c12bd51401628d23`), byte-identical to `matrix:resources/images/icon.png` (blob `65c70420507d3d218d570c65d773ec6fc07db5cd`). The live Test.app smoke on `a2b1ffc` showed it in Kodi. The former generic skeleton icon (SHA-256 `b908af8490f1ea6f16a2d9c2cc551c678c640c04df81a341dc79ec6d37817b8c`) no longer ships.
3. **Live package qualification of metadata and icon: CLOSED** on the exact candidate `a2b1ffc` (PASS; see the installed-runtime section).
4. **Eengert Repository publication and install/update qualification through it: OPEN and unauthorized.** Nothing in the 2026-10-08 consolidation task authorizes publication. It is blocked until Item 8 is accepted (`BUILD_MANAGER_PROJECT_PLAN.md`, Beta Candidate phase exit).
5. **Integration of this lane into `matrix`: not done.** It needs a separate, explicit decision. `matrix` already carries the same icon blob.

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

- Item 8 acceptance, pending ChatGPT review of the consolidation evidence (`item8-evidence-consolidation-20261008T232026Z`);
- when and how to integrate into `matrix`.

Do not restart Status, G1-G6, Create, Install, or Update / Repair implementation. These are implemented and recorded above. Reopening any of them needs a new bounded task that names a specific blocker.

## Stable references

- `BUILD_MANAGER_PROJECT_PLAN.md`: eight-item exit checklist and Beta Candidate phase exit.
- `.orchestrator/PROJECT.md`, `.orchestrator/WORKFLOW.md`, `.orchestrator/DECISIONS.md` (D-025 manual relay, D-026 Agent Handoff endpoints).
- `AGENTS.md`, `CLAUDE.md`.
- Approved backend baseline: `4a02b833178f5cb29e2b596985f1a8641ed3fa25`.

Ai-supervisor archives, `BUILD_MANAGER_SUPERVISOR_HANDOFF.md`, and old `.agent/**` records are historical evidence only. They do not override current Git or this file.
