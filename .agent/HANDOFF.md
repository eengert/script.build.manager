# Handoff — D-028 builtin authority correction

## Done
Reconciled 8480a25 to guidance-only 3ad2ffc; accepted product 9a77068 unchanged before work.
Preserved four dirty .agent records. Actual portable Test.app probe established enabled
xbmcaddon API id/version/path/type and pinned xbmc.python XML: 3.0.1, ABI 3.0.0.
JSON-RPC rejects UNKNOWN-type builtins; dependency declarations are not target authority.
Product correction 233bf87a245010de7830395789117bc81478c1ac: pinned unshadowed application metadata plus enabled
runtime API, Python-major/type/identity/version/ABI checks; other unproven builtins block.
Files: resources/lib/frozen.py, resources/lib/frozen_install.py,
tests/test_d028_builtin_authority.py. 24 new PASS (dev/Apple Python), 235 subsystem PASS.
Full candidate 3430 vs baseline 3406: same two unchanged UI import-policy failures,
no errors; candidate no skips; five baseline archive-history supplement tests PASS.
Two in-memory security mutations detected. Whitespace checks PASS.

## Not done / next
STOP for independent correction-delta review of 3ad2ffc..233bf87.
No restaging/live candidate acceptance; accepted 9a77068 remains staged, Test.app stopped.
No fixture E, Install/Repair, Apply, restart transaction, private data, normal Kodi/device,
Agent Handoff operation, integration, push or publication. Item 8 remains open.
After independent acceptance, separately authorize exact-candidate staging/runtime admission.
Evidence: .qualification-evidence/d028-builtin-authority/RUN-SUMMARY.md and SHA256SUMS.txt.

## Cleanup
Removed task baseline archive/test scratch and one launch-created runtime cache directory.
Retained checksummed public XML/API evidence, tests/logs, reproducible probes and original
four .agent file snapshots. Prior fixture/selection/settings/transactions/evidence preserved.

---

# Preserved earlier task records

# Handoff — Test.app launch/background focus correction

## Done
Updated `AGENTS.md` and `.orchestrator/WORKFLOW.md` with the standing
Test.app launch/relaunch focus policy: capture foreground app/PID, use the
exact portable `open -g ... --args -p` command, verify executable path/PID and
portable arguments, keep Test.app out of foreground except for required UI,
and restore focus through identity-checked process targeting. Guidance-only
commit: `3ad2ffc`. `git diff --check` passed; no tests were needed.

## Not done / limits
No Test.app launch or interaction, product-code change, device access, matrix
or Claude worktree access, push, or publication. The prior D-028 runtime
handoff and qualification evidence are preserved below.

## Next step / input
No further action is needed for this guidance task. D-028 runtime admission
still requires separately authorized builtin-authority investigation and
correction before another runtime attempt.

## Cleanup
No task-created scratch artifacts. Pre-existing D-028 qualification evidence
remains preserved as described in its prior handoff below.

---

# Previous Handoff — D-028 Test.app runtime verification

## Done
Clean start agent/codex at 8480a25f9556c9a55c4ae663fedbe250faa51b3a;
accepted 9a77068455f9800bb381040458c0fbdcdc316f59 ancestry/runtime-byte equality proven.
Staged exact accepted Git objects into portable Test.app using proven helper;
67 product / five driver files verified. Live PID 71808 portable identity proven.
Trusted application-root PIL 5.1.0 enabled/unbroken, xbmc.python >=3.0.0 dependency,
PLATFORM_PROVIDED/no ZIP/fallback/Skip proven. Build Manager menu and Estuary Home accessible.

## Result / not done
**NOT PASS runtime admission:** production verifier rejects xbmc.python builtin authority:
Addons.GetAddonDetails(xbmc.python, enabled/version/broken) returns -32602 Invalid params,
backend returns None, frozen_install.py:1581 fails closed. No product correction.
PIL-only in-memory capture intentionally rejected as managed root; no complete build claimed.
No fixture E, Install/Repair, Apply, restart transaction, private value, normal Kodi,
device, Agent Handoff, integration, push or publication. No new commit/full suite.

## Evidence / next step
.qualification-evidence/d028-runtime-9a77068/RUN-SUMMARY.md and SHA256SUMS.txt.
Authorize bounded builtin-authority investigation/correction with regressions and independent
review, then rerun runtime admission before fixture E/restart qualification. Item 8 remains open.
Final Test.app stopped, accepted candidate staged; five fixtures/selection, add-on states,
settings and absent transactions unchanged in secret-blind pre/post census.

## Cleanup
Removed staging input, Swift executable/cache, probe scratch stores, and two newly staged
runtime cache directories. Retained checksummed report/JSON, reproducible probe sources,
two Test.app screenshots, exact stage manifest and replaced trees. Earlier data/evidence preserved.
