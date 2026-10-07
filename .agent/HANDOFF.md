# Handoff — Library bridge NB-1 through NB-5

## Outcome

Narrow correction candidate complete offline; STOP per task. No independent
re-review, frontend work, or runtime qualification was performed.

Starting state: `agent/codex`, clean, `bf2d86c56d690f58fb104a682b1453cf0a5c7af8`.
Verified parent: accepted product `32d915e0ea4f97748b505ca131d0f16df08832f0`,
based on `72970ba9c07aa6d2d60c4bdc626c41a32d1a3b86`; starting HEAD was `.agent/**` only.
Product correction: `dc7f25683b6f26367fc59abd0c352d8f6f9b8827`. Task records are committed separately.
Admission: protects the durable API needed by beta checklist item 8 and restart/recovery item 2.

## Changes

- NB-1: durable selector deserialization and every target load authenticate the
  root against `default_build_library()`. Explicit scoped
  `isolated_library_install_authority(BuildLibrary(root))` supplies offline
  isolation authority; persisted selectors cannot establish authority. Schema 4
  and serialized shape are unchanged; unauthorized roots fail before content use.
- NB-2: removed `install_target` policy override. Library-mode `install` also
  derives policies from the verified resolved profile. Standalone overrides remain.
- NB-3: translate LibraryError only at durable manifest/profile load boundaries
  into FrozenInstallValidationError / FROZEN_MANIFEST_INVALID. Held outage test
  crosses restart, retains hold/quarantine/state, refuses abandon, restores exact
  envelope bytes, then succeeds through supported retry, activation and cleanup.
- NB-4: equivalent-active reuse requires exact library target and profile, plus
  existing fingerprints. Conflicting library sources are rejected before their
  content is opened. Standalone equivalent-active profile behavior is unchanged.
- NB-5: 10 new bridge regression methods and extended real BuildManager held-stage
  preparation coverage. Pins held manifest/profile reload and source retry predicate;
  BM-020 versus frozen selector; held-stage selector and fingerprint; active-resume
  entry/profile; empty legacy paths; library-owned frozen dependency graph;
  BM-020 schema/source tie. Global loaders fail if reached in the library graph test.

Changed product/test/docs files: resources/lib/build_library.py,
resources/lib/frozen_install.py, tests/test_library_install.py,
tests/test_build_manager.py, docs/LIBRARY_INSTALL_TARGET.md.

## Validation

- `python3 -m unittest tests.test_library_install tests.test_build_manager -q`:
  45 tests PASS before final active-source precheck; final broader run includes both.
- `python3 -m unittest tests.test_library_install tests.test_build_library tests.test_plan tests.test_frozen_install tests.test_resume tests.test_restart_coordinator tests.test_build_manager tests.test_config tests.test_transaction -q`:
  final 564 tests PASS (19.331s).
- `python3 -m unittest discover -s tests -t . -q`:
  final 2970 tests PASS (141.279s), with permitted disposable process inspection
  and loopback fixtures. Initial sandbox run completed 2970 tests but had 8 failure
  and 11 error reports from denied ps/socket fixtures; no tests were weakened.
  A prior permitted run passed 2970 (149.684s); final full run supersedes it because
  the NB-4 early source-conflict check changed during that prior run.
- `git diff --check`: PASS.

Evidence is offline: real library/artifact/transaction loaders and supported retry;
public configuration uses real BuildManager/ConfigurationManager; private-resource
execution outcomes and Kodi session identities are injected fixture owners.
No live runtime acceptance is claimed.

## Preserved / not done

Accepted registry/content-ID/profile/Plan bindings, owned package loading,
resolution fingerprints, selection independence, schema shapes/legacy readability,
hold/quarantine semantics and standalone lifecycle remain intact. No Create UI,
Install UI, Update/Repair, G5/G6, Red Light URI, packaging or storage redesign.
NB-6..NB-12 remain non-blocking observations: from_plan_target(None) exception type;
standalone schema-4 emission; root diagnostics; test-double compatibility shims;
future frontend review adapter; performance; platform symlink behavior.
No Test.app launch, normal Kodi/profile/device access, ai-supervisor work,
protected-branch integration, push, release or publication.

## Smallest next step / human input

Stop. A separately assigned independent review may inspect only this correction
candidate. No pending implementation blocker; further work requires a new bounded
assignment. Do not start frontend implementation or runtime qualification from this handoff.
