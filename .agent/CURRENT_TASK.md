# Current Task

- Task: BUILD MANAGER UPDATE / REPAIR SUPPORTED WORKFLOW (bounded offline product implementation; no assigned ID).
- State: STOPPED candidate. Product commit 866080e (local, not pushed). Stop for a product decision on repository-current packages before independent review.
- Start: clean agent/claude at 6b5f43c97c4531425b451a2c5d2447fe2411ea91. Accepted product ancestor 62a3f9062df8b41c1a64df6012b476b7f8626482; 6b5f43c..HEAD delta was .agent-only.
- Product: 866080e (10 files: Update / Repair workflow, UI wiring, strings, tests, docs).
- Result: REPAIR routes to the real workflow from the verified applied association. Check for Changes, reviewed Apply, G6 blockers, and session-only different revisions are implemented. Two repository-current limits are refused before Apply (see HANDOFF.md).
- Validation: 29 new offline tests pass. Full suite 3132 run: 2 import-policy failures and 4 keychain errors, identical to the git-backed starting HEAD (3103 run, same six).
- Preserved: applied association and publication path, Install behavior, Status, Help, main-menu order.
- Boundaries: no push, no matrix, no Agent Handoff operation, no Test.app/Kodi/profile/device/MCP access.
- Next: product decision on repository-current packages on applied builds; then independent review of 866080e.
- Usage: see the last row of .agent/USAGE_HISTORY.md.
