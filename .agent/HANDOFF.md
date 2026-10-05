# Test.app helper B1-B5 correction — 2026-10-04

Status: correction complete offline; independent correction-delta review pending.

## Identity and scope

- Worktree: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`.
- Branch: `agent/codex`; clean task-start HEAD: `5ce8f2b6accb013d2e9967e5180a86a28e29369e`.
- Original helper: `ef59605e2c8fe993efee600eda11be4412e01aa5`, unchanged at task start.
- Substantive correction: `53454069a033fcdfc52dc96aa38e050eb13a7ee7`; only `tools/bm_test_app.py`,
  `tests/test_bm_test_app.py`, `docs/BM_TEST_APP_HELPER.md`.
- Removes demonstrated helper safety blockers to macOS beta qualification (especially exit item 7).

## Corrections and proof

- B1: one pure lexical policy collapses leading slashes, rejects opaque `.vol`,
  `.nofollow`, `.resolve` components before traversal, and canonicalizes Data-volume
  aliases. CLI and all four paths in the six-value config receive the same protection;
  both identifier values retain strict non-path validation. Config symlinks are refused.
  Git discovery uses fixed system paths rather than inherited PATH. Independent tripwire
  normalization corrected. Entry-point tests refuse alias inputs before forbidden I/O.
- B2: workspace placement explicitly uses validated `/private/tmp` in production;
  injected roots pass the same path policy. Hostile TMPDIR cannot redirect export,
  driver, or config writes. Exclusive 0700 workspace is removed afterwards.
- B3: validate the full bundle/portable-data chain at identity, before stage mkdir,
  and immediately before swap. Resources and Resources/Kodi symlink decoys fail
  before staging or evidence creation, with unchanged decoy fingerprints.
- B4: proc_pidpath supplies actual executable identity; KERN_PROCARGS2 supplies
  NUL-delimited argv. Only argc argv entries are parsed; environment bytes are ignored.
  Recheck executable around argv acquisition; preserve sanctioned Data-volume aliases.
  Portable -p must precede unknown/value-taking options. Temporary compiled processes
  prove standalone -p accepted; absent/--portable/embedded text/option values and
  spoofed argv0/executable mismatch refused. Multiple/foreign checks still pass.
- B5: reverify backups and fingerprint actual moved-aside old trees before discard.
  Content or presence mismatch preserves .bm-stage/old and evidence and fails closed.
  Deterministic injected races cover both existing and newly appeared live trees;
  unexpected bytes survive and a later stage is refused by the retained area.

## Validation

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_bm_test_app`:
  310/310 on Python 3.10.9; same command with `/usr/bin/python3` (3.9.6) and
  `/usr/local/bin/python3.12` (3.12.4): 310/310 each, no skips.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_bm023a_adapter`: 110/110.
- `python3 -m py_compile tools/bm_test_app.py`; `git diff --check`: pass.
- Six narrow scratch-copy mutation probes detected B1, B2, B3, B4 argv,
  B4 executable, B5. Working helper remained byte-for-byte unchanged during probes.
- Final logs: `/private/tmp/bm-helper-final{39,310,312}.log`,
  `/private/tmp/bm-adapter.log`, `/private/tmp/bm-final-mutations.log`.
  Probe script: `/private/tmp/bm_mutation_probe.py` (PYTHONPATH must name this checkout).
- Initial sandbox process/loopback restrictions were resolved with permitted execution
  for disposable tests. Intermediate fixture/source-digest runs are superseded by final runs.

## Preserved boundaries and next step

- Accepted product `8789329054b77815c6f9548fd4ce9beacbe1d348` remains byte-identical
  for addon.xml/default.py/service.py/resources and the adapter builder/support/templates.
  No product version change; no repeated full product suite for unchanged product source.
- Normal Kodi/application profile, real Test.app, and household devices were NOT contacted.
  No live preflight/qualification, push, matrix integration, release, or history rewrite.
- No unrelated N1-N13 improvements; fixed Git discovery is necessary for B1 environment-path safety.
- Next: human relay to an independent reviewer of ONLY `5ce8f2b..53454069a033fcdfc52dc96aa38e050eb13a7ee7`.
  This correction is not self-approved; stop here. No additional implementation or live authority.
- Exact model tier and effort are not exposed by this session; system identity is GPT-6.
  Usage readings recorded as unavailable per current Codex guidance.
