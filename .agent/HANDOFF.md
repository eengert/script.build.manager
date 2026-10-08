# Handoff — Test.app background launch guidance

- State: COMPLETE; docs-only change.
- Start: `agent/claude` at `ce17a39`, clean. Since the expected `cc0911d` baseline, only `.agent/**` bookkeeping had advanced.
- Done: updated `.orchestrator/PROJECT.md`, `.orchestrator/WORKFLOW.md`, D-007 in `.orchestrator/DECISIONS.md`, and current launch/relaunch instructions in `docs/BM_TEST_APP_HELPER.md` and `docs/FROZEN_BUILD_INSTALL.md`.
- Durable default: `open -g "/Applications/Kodi Build Manager Test.app" --args -p`. Portable `-p` remains mandatory; a specific validation task may require foreground activation.
- Commit: `a9af2bb1dbbb580f93620ceb336d89bfa2132f0e` (`Use background launch for Test.app validation`).
- Validation: `git diff --check` passed. No product tests were run or needed. Historical qualification evidence was not edited.
- Not done: no Test.app/Kodi/profile/device interaction, MCP extension changes, push, merge, or Agent Handoff operation. `.agent/AGENT_STATUS.json` remains untouched.
- Next step: none for this task. Any integration needs a separate decision.
- Human input: none required to complete this task.
