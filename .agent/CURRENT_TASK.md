# Current Task

- Task: BUILD MANAGER UPDATE / REPAIR RECORDED RESOLUTION CORRECTION (bounded offline product correction; no assigned ID).
- State: READY FOR REVIEW. Correction commit 326e52d (local; not pushed). Bookkeeping in the commit after it.
- Start: clean agent/claude at 91d9dc39c1559840b0f2a1b97aea33d23cb8254f; parent 866080ef9d687879fdcb02efa480e34ae34dff99.
- Result: applied outcomes that record repository-current packages are reused as their exact accepted resolution. The engine binds them before mutation and never queries a repository. The recorded-repository refusal is gone. The decision invariant is proven by tests and documented.
- Validation: 16 new offline tests and 29 workflow tests pass. Focused engine run 373 pass. Full suite 3148 run with only the six pre-existing failures and errors (two plan_view import-policy, four keychain fixture).
- Preserved: applied-association publication, Install behaviour, G6 blocks, RepositoryPreparationService rejection of applied targets, restart and resume behaviour, the schema-4 transaction format (new field optional).
- Boundaries: no push, no matrix, no Agent Handoff operation, no Test.app, no normal Kodi, profile, device or MCP access.
- Next: independent review of 326e52d; runtime validation needs a separately authorized task.
- Usage: see the last row of .agent/USAGE_HISTORY.md.
