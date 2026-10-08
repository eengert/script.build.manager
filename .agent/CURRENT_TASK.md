# Current Task

- Task: BUILD MANAGER TEST.APP DEFAULT BACKGROUND LAUNCH GUIDANCE (no assigned ID).
- State: COMPLETE. Updated the durable launch default and current manual launch/relaunch examples.
- Start: `agent/claude` at `ce17a39`, worktree clean. The task's expected `cc0911d` baseline had advanced only through `.agent/CURRENT_TASK.md`, `.agent/HANDOFF.md`, and `.agent/USAGE_HISTORY.md` bookkeeping.
- Files: `.orchestrator/PROJECT.md`, `.orchestrator/WORKFLOW.md`, `.orchestrator/DECISIONS.md` (D-007), `docs/BM_TEST_APP_HELPER.md`, `docs/FROZEN_BUILD_INSTALL.md`.
- Durable command: `open -g "/Applications/Kodi Build Manager Test.app" --args -p`; `-p` remains mandatory. Foreground activation is allowed only when a specific validation task requires it.
- Commit: `a9af2bb1dbbb580f93620ceb336d89bfa2132f0e` (`Use background launch for Test.app validation`).
- Validation: `git diff --check` passed; current tracked guidance has no remaining recommended foreground command. No product tests or app launch were needed for this docs-only task.
- Boundaries: no product/runtime source, tests, Test.app, Kodi/profile/device, MCP extension, push, merge, or Agent Handoff activity. `.agent/AGENT_STATUS.json` was not changed.
- Next: no further action for this task; any integration or additional validation requires a separate decision.
- Usage: see the appended row in `.agent/USAGE_HISTORY.md`.
