# BM-UI-003B capture correction — PASS offline; STOP

## Identity / admission
- Branch/worktree: agent/codex, /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex.
- Clean starting HEAD: 843794d2b5cd4342de99975486c4c7c4e9408ebf.
- Corrected product: f08b3fda497da74ba3a6a4afaff672ee9b9ba05d.
- Correction product commit: 2a7791cc7cf227fe15620207852d6c11ca6fae2d; separate endpoint tracking commit follows.
- Live Agent Handoff confirmed Codex active, clean expected start. Removes two demonstrated blockers to beta exit item 8 / G1 capture; accepted architecture and other PASS areas preserved.

## Reproduced before source edits
- Real skin runtime adapter, mocked JSON-RPC: public CustomID failed lookup and fell back to private customid; COMPLETE; three RPCs; disposable private sentinel entered canonical public bundle and registered disposable library envelope.
- Real Red Light adapter, held/disabled/initialized disposable WAL DB: COMPLETE and newest committed value captured; DB/WAL identical but existing live SHM changed.
- Reproducer: /private/tmp/bm003b_reproduce.py (synthetic fixture values only).

## Correction / files
- resources/lib/skin.py: shared canonical_skin_setting_key() uses runtime lowercase alias identity; first requested RPC spelling and fallback behavior unchanged.
- resources/lib/create_capture.py: public/public, private/private, public/private skin alias collisions rejected before getters. Effective target-kind value governs identity; ordinary add-on keys remain case-sensitive. No Red Light logic added here.
- resources/lib/private_resource.py: explicit generic capture contract forbids managed-file/sidecar mutation; disposable internal scratch allowed.
- resources/lib/redlight_resource.py: capture validates lifecycle before reading; opens ancestors/files no-follow; bounded main/WAL reads twice, compares bytes and device/inode/size/mtime/ctime before/between/after; verifies fresh ancestor identities; brackets temporary SQLite query with source/lifecycle rechecks; schema and quick_check validated on copy only. Live SHM never opened/copied. Temporary DB/WAL/SQLite sidecars cleaned on success/failure.
- tests/test_create_capture.py: 11 additional regression methods (57 total), alias combinations/inverse case, effective enum target, unrelated skin and case-distinct add-on settings, real runtime fallback/privacy across all public and library surfaces, WAL-current values with SHM present/absent, unstable file/ancestor changes, symlink/FIFO/size rejection, query-time changes, scratch cleanup and safe failures.
- tests/test_skin.py: shared alias helper/runtime fallback regression (one additional method).
- docs/CREATE_CAPTURE.md and docs/BM017C_PRIVATE_RESOURCES.md: alias collision, generic non-mutating capture, coherent private WAL snapshot, scratch cleanup/privacy semantics. Existing pre-0.2.0 SQLite # URI finding retained verbatim; apply/verify and Status probe code unchanged.

## Evidence
- 809 focused tests PASS (3.921 s): python3 -m unittest tests.test_create_capture tests.test_skin tests.test_private_overlay tests.test_private_resource tests.test_build_library tests.test_config tests.test_status tests.test_frozen tests.test_manifest_loader tests.test_manifest_resolver tests.test_artifacts -q
- One full suite PASS: 2797 tests, 129.800 s; python3 -m unittest discover -s tests -q. Permitted execution for existing disposable process/loopback fixtures.
- All eight product/test/document hashes match pre-full-suite candidate; no source/test/document edits after full PASS. git diff --cached --check PASS.
- Focused/full logs: /private/tmp/bm003b-focused.log, /private/tmp/bm003b-full.log. Candidate hashes: /private/tmp/bm003b-candidate-hashes.json.
- WAL regression uses checkpointed older value plus newer committed WAL value: captured newer value, DB/WAL/SHM existence+bytes unchanged; absent SHM remains absent. Snapshot paths cleaned before returning.
- Source content change/replacement/WAL disappearance/ancestor replacement or symlink/query-time change yields INCOMPLETE with no public bundle/private overlay. No sensitive logging/error payloads.
- Status still rejects non-empty WAL without changing live files; related Status tests PASS.
- Rejected aliases reach neither PreparedPublicBundle nor registration. Valid private-only/unrelated captures keep synthetic private values outside canonical bundle, package descriptors/assets, Manifest, FrozenBuildManifest, staged registration inputs, library envelope, repr/safe output/logs.
- Existing undeclared-read, wrong-type, ownership, skin include/exclude, exact artifact, required failure and all mutation tripwires pass.
- Practical mutations: replacing canonical normalization with raw identity fails privacy regression; restoring old live SQLite path reproduces changed SHM with COMPLETE.

## Scope / limits
- Offline/disposable evidence only; no live-runtime or independent acceptance claimed.
- One deterministic snapshot attempt; 64 MiB maximum per main/WAL file. Requires existing verified held/disabled/initialized lifecycle; changing/unsafe/oversized sources fail closed. No universal snapshot guarantee against malicious writers violating that contract.
- Normal read-only file reads may update filesystem access metadata; byte/existence invariants are DB/WAL/SHM content and no SQLite live sidecar writes.
- Exact model tier/effort unavailable; observed session identity GPT-6. Fresh desktop usage tool available despite stale CLI-only guidance: start remaining 5h 18%, weekly 54%; end 5h 13%, weekly 53%; account-wide observed burn 5/1 percentage points, no task attribution or estimation.
- No push, matrix merge, publication, repository.eengert changes, Test.app launch/access, normal Kodi/profile/device access, real build registration/selection, real overlay persistence, native Create UI, Install/Repair Apply, G6, or unrelated hardening.

## Smallest next step / human input
- STOP: independent correction-delta review of 843794d2b5cd4342de99975486c4c7c4e9408ebf..2a7791cc7cf227fe15620207852d6c11ca6fae2d, excluding endpoint tracking.
- Eric/ChatGPT relays exact candidate to the independent reviewer. No additional implementation or live operation authorized by this completion.
