# BM-UI-003A — Canonical Build Library: PASS offline; STOP

## Identity and admission
- Worktree: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex
- Branch: agent/codex; clean required start ddeec17fbb010fd21f4c1de04002a02c79a2bae8.
- Product commit: f660332d4701bbf8493037f956ea62d8a539e023.
- Advances beta exit item 8: owned build data and persisted selection for native workflows. G2/G3 remain accepted.
- Live Agent Handoff status confirmed Codex active before implementation. No agent switch.

## Completed
- Canonical active-special-profile Build Library: build-library/{registry.json, selection.json, library.lock, builds/<sha256>.json}.
- Immutable content-bound entries own existing public/frozen manifest formats and all required package descriptors/assets; deterministic usable listing and strict ID/version conflicts.
- Reused package validation through an optional source-byte reader and existing bounded regular-file reads through optional dir_fd.
- One optional typed LibrarySource in StatusTarget/PlanTarget supplies a revalidated coherent owned snapshot; default_status_target and default_plan_target use persisted selection. Legacy path targets preserve their previous behavior.
- Exact ZIPs remain in existing ArtifactStore; private payloads remain in PrivateOverlayStore; prior completed install resolutions remain separate and association is deferred (None).
- No-follow ancestor/leaf traversal, bounded reads, regular-file checks, writer lock, atomic fsynced publication, ignored/unselectable interrupted stages/orphans, corruption and registry/content disagreement fail closed.
- Private declarations/Red Light/credential targets and diagnostic payloads rejected; unrelated private files are not imported. Public models/logs contain no private test sentinels/internal paths.

## Files
resources/lib/build_library.py; resources/lib/config.py; resources/lib/readonly_io.py;
resources/lib/status.py; resources/lib/plan.py; tests/test_build_library.py;
docs/BUILD_LIBRARY.md. Endpoint bookkeeping additionally updates HANDOFF.md,
CURRENT_TASK.md, AGENT_STATUS.json and append-only USAGE_HISTORY.md.

## Validation
- 43 new library regressions PASS, including scoped Status/Plan behavior for two same-package-ID builds, deleted/changed sources, source/library symlinks/FIFOs, ancestor swap, interrupted registration/selection, stale targets, privacy and mutation/network tripwires.
- Final focused: 843 tests PASS (8.586 s).
  python3 -m unittest tests.test_build_library tests.test_status tests.test_plan tests.test_config tests.test_manifest_loader tests.test_manifest_resolver tests.test_manifest_schema tests.test_frozen tests.test_artifacts tests.test_frozen_resolution -q
- One full suite: 2739 tests PASS (133.031 s).
  python3 -m unittest discover -s tests -q
  Permitted execution used for existing disposable loopback/process fixtures. No source changed afterward.
- git diff --check PASS. Seven product/test/document files match pre-full-suite SHA-256 digests.
- Logs: /private/tmp/bm-ui-003a-focused.log; /private/tmp/bm-ui-003a-full.log.
- Automated/disposable evidence only; no independent review or live runtime claim.

## Not done / boundaries
No Create UI/capture, Install/Repair Apply, G6, acquisition/network, transfer folder,
installed-resolution association, removal/repair API, version/icon/repository work,
push/publication/matrix integration, Test.app launch, live Kodi/profile/device
access or mutation. Full-suite helper output comes from existing disposable/mock
fixtures; it is not live Kodi qualification.

Prepared inputs must already be public under the existing package contract.
Known private targets/diagnostic channels are blocked; there is no universal
classifier for secrets disguised as arbitrary public text. Prepared frozen
bundles must omit node errors/arbitrary provenance maps; only matching typed
kodi_version source metadata is accepted. macOS beta uses POSIX dir_fd/flock;
unsupported runtime/profile translation fails closed. Corrupt indexed entries
are retained/unavailable pending explicit repair; unindexed valid content can be
recovered by exact registration retry.

## Smallest next step / human input
Exact next task: native Create Build capture/registration workflow.
No further work is authorized by this task. Eric/ChatGPT supplies its bounded
prompt and any separate review direction. No implementation human input remains.
