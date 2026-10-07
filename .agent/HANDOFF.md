# Handoff

## Task / outcome
WF-native-ui-capability-blocker-policy: complete. Added durable guidance to prevent inferring a required tool from a behavioral UI requirement and to require evidence before reporting a missing-tool blocker.

## Identity / changes
Worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`, branch `agent/codex`. Starting HEAD `a8fd230dc21fbd53813513843358f543eb9ccc97`, clean and 20 commits ahead of `origin/agent/codex`. Focused guidance commit `bf49ded770a9c548ac725ff226111f2616c55dd3` changes only `.orchestrator/WORKFLOW.md`; current branch is 21 commits ahead. This handoff and its task records are endpoint-specific bookkeeping.

The new policy treats native UI control and capture as behavioral requirements, names the exact authorized/proven shell-mediated Test.app mechanism (PID/window identity, foreground-PID check, guarded input, window-only capture), and requires checking accepted alternatives and reconciling contradictory recent evidence before broad tooling investigation. It keeps CUA/Remote Desktop incidents separate unless Build Manager depends on them.

## Validation
Reviewed the focused diff against current Test.app safety rules; `git diff --check` passed. No tests were run because the change is documentation-only. No product, helper, test, runtime, Test.app, Kodi, device, or external-application state changed. Nothing was pushed.

## Scope boundary / next step
No Test.app qualification was attempted under this guidance-only task. The existing `BM-UI-003C-HELPER-STABLE-BASELINE-CORRECTION` still requires independent correction-delta review; resume its Test.app qualification only after PASS. Manual relay is needed to arrange that separate review. The new guidance remains local to this endpoint; no matrix integration, endpoint synchronization, or publication was authorized.
