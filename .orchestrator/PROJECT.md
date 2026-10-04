# Build Manager Project Context

## Identity

- Name: Build Manager
- Kodi add-on ID: `script.build.manager`
- Repository: `/Users/eengert/Documents/Kodi/script.build.manager`
- Protected integration branch: `matrix`
- Canonical project plan: `BUILD_MANAGER_PROJECT_PLAN.md`
- Shared worker guidance: `AGENTS.md`

## Purpose

Build Manager provides declarative desired-state provisioning/reconciliation for Kodi.

Target platforms:

- tvOS / Apple TV
- Android / Nvidia Shield / Fire TV
- macOS

Desired-state layering:

`Base Build + Platform Profile + Device Profile + Optional Components + Personal Configuration + Optional Secrets`

Public builds never contain private tokens/secrets.

Build Manager is not Backup Pro. It manages declarative software/configuration/private fields, not arbitrary filesystem snapshot backup/restore.

## Current outcome

The active milestone is **Build Manager macOS Beta Qualification**. Its authoritative seven-item exit checklist and critical-path admission rule are in `BUILD_MANAGER_PROJECT_PLAN.md` under “Current Outcome: Build Manager macOS Beta Qualification.” Every task in this milestone maps to one checklist item or a demonstrated blocker to it; broader 1.0 and cross-platform scope remains governed by the longer-range plan after this milestone.

## Manual worktrees

Build Manager uses a manual ChatGPT -> Codex/Claude workflow. The retained Agent Handoff tool (`/Users/eengert/Documents/Kodi/agent-handoff`, installed as `Agent Handoff.app`) maintains exactly two manual endpoints for this project:

- Codex: worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`, branch `agent/codex`
- Claude: worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude`, branch `agent/claude`

These are manual Agent Handoff endpoints, not autonomous supervisor workers: nothing runs in them unless Eric launches Codex or Claude with a bounded prompt. Their product trees outside `.agent/**` are meant to stay identical, and Agent Handoff records one active worker. Current status (active worker, candidate state) is in `.orchestrator/HANDOFF.md`; live Git and a read-only Agent Handoff status check win over any snapshot. Antigravity is retired from the Build Manager Agent Handoff configuration and must not be recreated.

Having two endpoints does not remove the per-task rule: every manual task prompt must name the exact worktree/branch it is allowed to use, and an agent works only in that one.

`/Users/eengert/Documents/Kodi/worktrees/script.build.manager-beta-recovery` (branch `agent/beta-recovery`) is retained as a historical/safety reference for the candidate the endpoints were restored from. It is not a normal working endpoint. Old `script.build.manager-supervised-*`, `script.build.manager-supervisor`, and other historical agent worktrees are retired or inactive; their branches and archived evidence may still exist in Git metadata and under `/Users/eengert/Documents/Kodi/archives/`, but they are not active merely because they exist.

Do not disturb or delete an old worktree if it contains uncommitted/review evidence unless its state has first been reconciled and intentionally archived.

## Protected branch policy

`matrix` is protected.

Normal implementation happens in the exact manual task branch/worktree named by ChatGPT, not directly on `matrix`.

Do not:

- reset/rebase shared worker history
- force-push
- discard worker commits
- use destructive `git reset --hard` / `git clean`
- push unless Eric explicitly authorizes it

Worker and matrix histories may legitimately diverge after reviewed integration.

Worker `.agent/**` tracking is not substantive product code and should not be mechanically copied to matrix.

## Kodi safety boundaries

### Authorized macOS validation target

Only this application is authorized for current BM-023A macOS live validation:

`/Applications/Kodi Build Manager Test.app`

Launch exactly with:

`open "/Applications/Kodi Build Manager Test.app" --args -p`

The `-p` flag is mandatory.

Eric has granted standing authorization for ongoing staging, testing, installation, configuration, restart/quit/relaunch, JSON-RPC interaction, temporary validation adapters, and other Build Manager validation work against this portable Test.app. Routine Test.app interaction is not a new human authorization gate, but in manual mode each agent receives the exact operation/scope in its bounded task prompt rather than continuing autonomously.

This standing authorization is scoped only to `/Applications/Kodi Build Manager Test.app` and its portable data. Never use `/Applications/Kodi.app` for this validation.

Never access in any way:

`/Users/eengert/Library/Application Support/Kodi`

That prohibition includes read, write, `ls`, `stat`, `test -e`, grep, and metadata probes.

### Real devices

Family Room Apple TV is historical source-of-truth for the captured desired state and must remain read-only unless a new explicit work item authorizes a specific mutation through an appropriate safe capability.

The retired ai-supervisor framework used these Kodi device aliases (they no longer exist as callable aliases; the names remain useful only as device identifiers):

- `family-room-kodi`
- `bonus-room-kodi`
- `shield-pro-kodi`

Naming a device is not authorization. A work item must explicitly grant the target.

## Frozen software model

ArtifactStore semantics are settled:

- immutable
- content-addressed by SHA-256
- exact ZIP artifacts
- validator enforces safe ZIP/root/addon.xml/ID/version/traversal/symlink/identity

Acquisition order:

1. verified Build Manager artifact
2. exact Kodi cache ZIP
3. exact still-available trusted provider/repository artifact
4. otherwise incomplete / explicit resolution required

Never manufacture a frozen artifact by ZIPing an installed add-on directory.

The Family Room historical graph has one intentional exact-artifact gap: YouTube `7.4.4+unofficial.2`. Do not silently substitute a different version. BM-023B fallback semantics govern explicit Skip/Cancel/resolution behavior.

## Red Light structured private resource

Owner: `plugin.video.redlight`

Resource: `redlight.settings`

Frozen validated version: `2.6.8`

Exact SHA-256:

`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`

Private overlay ID:

`family-room-redlight-2.6.8`

Historical sanitized overlay fingerprint:

`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`

Historical source software fingerprint:

`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`

Private overlay values must never be logged, pasted into chat, committed, emitted in public manifests, or exposed in diagnostics.

The overlay reference's `required=false` means the overlay reference is optional; it does not mean no overlay was imported/present. Preserve this distinction.

## BM-017F status

BM-017F configure-before-activation / structured private-resource lifecycle is complete and live-validated in a disposable profile.

Do not reopen it without new contradictory evidence.

The validated lifecycle is:

`exact install -> activation hold -> restart if required -> resource initialization -> config/private apply -> verification -> hold release -> final activation`
