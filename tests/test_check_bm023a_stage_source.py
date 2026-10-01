"""Offline tests for the BM-023A reviewed staging-source preflight."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.check_bm023a_stage_source import check, main


def _trailers(part, review="rc-1", source="work-1", snapshot="snap-1"):
    return (
        f"AI-Supervisor-Review-Checkpoint: {review}\n"
        f"AI-Supervisor-Source-Work: {source}\n"
        f"AI-Supervisor-Snapshot: {snapshot}\n"
        f"AI-Supervisor-Part: {part}\n"
    )


class TestCheckBm023aStageSource(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="Test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
        )
        self.git("init", "-q")
        self.write("README.md", "base\n")
        self.commit("base")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True, env=self.env,
        ).strip()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, subject, body=""):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", subject + "\n\n" + body)
        return self.git("rev-parse", "HEAD")

    def substantive(self, version="0.0.10", **ids):
        self.write(
            "tools/bm023a_adapter_support.py",
            f'ADAPTER_VERSION = "{version}"\n',
        )
        return self.commit("checkpoint: substantive", _trailers("substantive", **ids))

    def tracking(self, note="tracked\n", **ids):
        self.write(".agent/HANDOFF.md", note)
        return self.commit("docs: tracking", _trailers("tracking", **ids))

    def test_valid_pair_reports_stage_source(self):
        source = self.substantive()
        head = self.tracking()
        report = check(self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["head"], head)
        self.assertEqual(report["stage_source"], {
            "commit": source,
            "tree": self.git("rev-parse", source + "^{tree}"),
            "adapter_version": "0.0.10",
            "product_changes_to_head": [],
        })
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--root", str(self.root)]), 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])

    def untrailered_agent(self, note="plain\n"):
        self.write(".agent/HANDOFF.md", note)
        return self.commit("docs: no trailers")

    def test_stacked_tracking_and_untrailered_agent_commits_are_tolerated(self):
        source = self.substantive()
        self.tracking()
        self.tracking(note="second\n", review="rc-2", source="w2", snapshot="s2")
        self.untrailered_agent()
        self.tracking(note="third\n", review="rc-3", source="w3", snapshot="s3")
        head = self.untrailered_agent(note="latest\n")
        self.write(".agent/HANDOFF.md", "uncommitted\n")
        report = check(self.root, expected_version="0.0.10")
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["head"], head)
        self.assertEqual(report["stage_source"], {
            "commit": source,
            "tree": self.git("rev-parse", source + "^{tree}"),
            "adapter_version": "0.0.10",
            "product_changes_to_head": [],
        })

    def test_tracking_over_tracking_with_product_change_is_drift(self):
        source = self.substantive(version="0.0.10")
        self.tracking()
        self.write("resources/lib/extra.py", "x = 1\n")
        self.commit("docs: second", _trailers("tracking", review="rc-2", source="w2", snapshot="s2"))
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "product_changes_after_source")
        self.assertEqual(report["stage_source"]["commit"], source)
        self.assertEqual(
            report["stage_source"]["product_changes_to_head"],
            ["resources/lib/extra.py"],
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--root", str(self.root)]), 1)

    def reconcile(self, note="reconciled\n", files=None, body=None):
        self.write(".agent/HANDOFF.md", note)
        for rel, text in (files or {}).items():
            self.write(rel, text)
        return self.commit(
            "checkpoint: reconcile .agent tracking state",
            body or "AI-Supervisor-Part: tracking\nAI-Supervisor-Tracking-Reconcile: v1\n",
        )

    def test_reconcile_commits_are_tolerated_to_substantive(self):
        source = self.substantive(version="0.0.14")
        self.tracking()
        self.reconcile("a\n")
        head = self.reconcile("b\n")
        report = check(self.root, expected_version="0.0.14")
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["head"], head)
        self.assertEqual(report["stage_source"]["commit"], source)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(["--root", str(self.root), "--expected-version", "0.0.14"]), 0,
            )

    def test_reconcile_commit_does_not_form_a_pair(self):
        self.substantive()
        self.reconcile()
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "tracking_pair_missing")

    def test_reconcile_with_product_change_fails_closed(self):
        source = self.substantive()
        self.tracking()
        self.reconcile(files={"resources/lib/extra.py": "x = 1\n"})
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "reconcile_product_commit")
        self.assertEqual(report["nearest_substantive"]["commit"], source)

    def test_product_commit_after_source_still_fails_past_reconcile(self):
        source = self.substantive()
        self.tracking()
        self.reconcile("a\n")
        self.write("resources/lib/late.py", "y = 2\n")
        self.commit("feat: no trailers")
        self.reconcile("b\n")
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "untrailered_product_commit")
        self.assertEqual(
            report["nearest_substantive"]["product_changes_to_head"],
            ["resources/lib/late.py"],
        )
        self.assertEqual(report["nearest_substantive"]["commit"], source)

    def test_malformed_reconcile_trailers_fail(self):
        bodies = {
            "wrong_version": "AI-Supervisor-Part: tracking\nAI-Supervisor-Tracking-Reconcile: v2\n",
            "reconcile_only": "AI-Supervisor-Tracking-Reconcile: v1\n",
            "wrong_part": "AI-Supervisor-Part: substantive\nAI-Supervisor-Tracking-Reconcile: v1\n",
            "extra_pair_id": "AI-Supervisor-Part: tracking\nAI-Supervisor-Tracking-Reconcile: v1\nAI-Supervisor-Source-Work: w\n",
        }
        for name, body in bodies.items():
            with self.subTest(name=name):
                self.substantive()
                self.tracking(note=name + "\n")
                self.reconcile(note=name + " r\n", body=body)
                report = check(self.root)
                self.assertFalse(report["ok"], report)
                self.assertEqual(report["category"], "checkpoint_metadata_incomplete")

    def test_substantive_lacking_full_trailers_is_not_a_source(self):
        self.write("tools/bm023a_adapter_support.py", 'ADAPTER_VERSION = "0.0.14"\n')
        self.commit(
            "checkpoint: substantive",
            "AI-Supervisor-Source-Work: w\nAI-Supervisor-Part: substantive\n"
            "AI-Supervisor-Tracking-Reconcile: v1\n",
        )
        self.tracking()
        self.reconcile()
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "checkpoint_metadata_incomplete")

    def test_untrailered_product_commit_fails_and_reports_nearest(self):
        source = self.substantive()
        self.tracking()
        self.write("resources/lib/extra.py", "x = 1\n")
        self.write(".agent/HANDOFF.md", "mixed\n")
        self.commit("feat: no trailers")
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "untrailered_product_commit")
        self.assertNotIn("stage_source", report)
        self.assertEqual(report["nearest_substantive"]["commit"], source)
        self.assertEqual(
            report["nearest_substantive"]["product_changes_to_head"],
            ["resources/lib/extra.py"],
        )

    def test_untrailered_agent_commit_is_not_a_tracking_pair(self):
        self.substantive()
        self.untrailered_agent()
        self.tracking(note="later\n")
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "tracking_pair_missing")

    def test_untrailered_commit_tolerance_rejects_non_agent_only_changes(self):
        cases = {
            "mixed_agent_and_product": {
                ".agent/HANDOFF.md": "mixed\n",
                "resources/lib/extra.py": "x = 1\n",
            },
            "product_only": {"resources/lib/extra.py": "x = 1\n"},
            "agent_lookalike_sibling": {".agentx/notes.md": "n\n"},
            "nested_agent_directory": {"docs/.agent/notes.md": "n\n"},
        }
        for name, files in cases.items():
            with self.subTest(name=name):
                source = self.substantive()
                self.tracking(note=name + "\n")
                for rel, text in files.items():
                    self.write(rel, text)
                self.commit("feat: no trailers")
                self.tracking(note=name + " later\n", review="rc-2", source="w2", snapshot="s2")
                report = check(self.root)
                self.assertFalse(report["ok"], report)
                self.assertEqual(report["category"], "untrailered_product_commit")
                self.assertNotIn("stage_source", report)
                self.assertEqual(report["nearest_substantive"]["commit"], source)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--root", str(self.root)]), 1)
                self.git("reset", "-q", "--hard", "HEAD~4")
                self.git("clean", "-q", "-f", "-d")

    def test_untrailered_empty_commit_is_rejected(self):
        source = self.substantive()
        self.tracking()
        self.commit("chore: empty, no trailers")
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"), "")
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "untrailered_product_commit")
        self.assertEqual(report["nearest_substantive"]["commit"], source)

    def test_uncommitted_product_changes_fail(self):
        for rel in ("resources/lib/new.py", "tools/bm023a_adapter_support.py"):
            with self.subTest(rel=rel):
                self.substantive()
                self.tracking(note=rel + "\n")
                self.write(rel, "dirty\n")
                report = check(self.root)
                self.assertFalse(report["ok"])
                self.assertEqual(report["category"], "uncommitted_product_changes")
                self.git("checkout", "-q", "--", ".")
                self.git("clean", "-q", "-f", "--", "resources")

    def test_adapter_version_mismatch_fails(self):
        self.substantive(version="0.0.9")
        self.tracking()
        report = check(self.root, expected_version="0.0.10")
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "adapter_version_mismatch")
        self.assertEqual(report["stage_source"]["adapter_version"], "0.0.9")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(["--root", str(self.root), "--expected-version", "0.0.10"]), 1,
            )

    def test_partial_trailers_fail(self):
        self.substantive()
        self.tracking()
        self.write(".agent/HANDOFF.md", "partial\n")
        self.commit("docs: partial", "AI-Supervisor-Part: tracking\n")
        report = check(self.root)
        self.assertEqual(report["category"], "checkpoint_metadata_incomplete")

    def test_merge_in_lineage_fails(self):
        self.substantive()
        self.tracking()
        self.git("checkout", "-q", "-b", "side")
        self.tracking(note="side\n", review="rc-2", source="w2", snapshot="s2")
        self.git("checkout", "-q", "-")
        self.git(
            "merge", "-q", "--no-ff", "-s", "ours", "side",
            "-m", "merge\n\n" + _trailers("tracking", review="rc-3", source="w3", snapshot="s3"),
        )
        report = check(self.root)
        self.assertEqual(report["category"], "lineage_ambiguous")

    def test_mismatched_trailers_fail(self):
        for key in ("review", "source", "snapshot"):
            with self.subTest(key=key):
                self.substantive()
                self.tracking(note=key + "\n", **{key: "other"})
                report = check(self.root)
                self.assertFalse(report["ok"])
                self.assertEqual(report["category"], "pair_metadata_mismatch")

    def test_untrailered_head_over_substantive_has_no_pair(self):
        self.substantive()
        self.untrailered_agent()
        report = check(self.root)
        self.assertEqual(report["category"], "tracking_pair_missing")
        self.assertFalse(report["ok"])

    def test_missing_parent_trailers_fail(self):
        self.write("tools/bm023a_adapter_support.py", 'ADAPTER_VERSION = "0.0.9"\n')
        self.commit("plain product commit")
        self.tracking()
        report = check(self.root)
        self.assertEqual(report["category"], "untrailered_product_commit")
        self.assertNotIn("nearest_substantive", report)

    def test_head_substantive_is_not_tracking(self):
        self.substantive()
        report = check(self.root)
        self.assertEqual(report["category"], "head_not_tracking")

    def test_tracking_commit_with_product_changes_is_drift(self):
        source = self.substantive()
        self.write("resources/lib/late.py", "y = 2\n")
        self.tracking()
        report = check(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["category"], "product_changes_after_source")
        self.assertEqual(report["stage_source"]["commit"], source)
        self.assertEqual(
            report["stage_source"]["product_changes_to_head"],
            ["resources/lib/late.py"],
        )

    def test_missing_adapter_version_fails(self):
        self.git("rm", "-q", "--cached", "--ignore-unmatch", "tools/bm023a_adapter_support.py")
        self.commit("checkpoint: substantive", _trailers("substantive"))
        self.tracking()
        report = check(self.root)
        self.assertEqual(report["category"], "adapter_version_unavailable")
        self.assertIsNone(report["stage_source"]["adapter_version"])

    def test_non_repository_is_sanitized(self):
        with tempfile.TemporaryDirectory() as parent:
            other = str(Path(parent).resolve() / "not-a-repo")
            os.mkdir(other)
            ceiling = {"GIT_CEILING_DIRECTORIES": str(Path(parent).resolve())}
            with mock.patch.dict(os.environ, ceiling), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["--root", other]), 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["category"], "head_unavailable")
        self.assertNotIn(other, out.getvalue())


    # -- one canonical trailer per semantic field --------------------------------

    def _reviewed_with_reconcile_body(self, body, **kwargs):
        source = self.substantive()
        self.tracking()
        head = self.reconcile(body=body, **kwargs)
        return source, head

    def test_duplicate_or_conflicting_reconcile_trailers_fail_closed(self):
        canonical = "AI-Supervisor-Part: tracking\nAI-Supervisor-Tracking-Reconcile: v1\n"
        bodies = {
            "identical_reconcile": canonical + "AI-Supervisor-Tracking-Reconcile: v1\n",
            "conflicting_v1_then_v2": canonical + "AI-Supervisor-Tracking-Reconcile: v2\n",
            "conflicting_v2_then_v1": (
                "AI-Supervisor-Part: tracking\nAI-Supervisor-Tracking-Reconcile: v2\n"
                "AI-Supervisor-Tracking-Reconcile: v1\n"
            ),
            "identical_part": canonical + "AI-Supervisor-Part: tracking\n",
            "conflicting_part_tracking_last": (
                "AI-Supervisor-Part: substantive\nAI-Supervisor-Part: tracking\n"
                "AI-Supervisor-Tracking-Reconcile: v1\n"
            ),
            "conflicting_part_tracking_first": (
                "AI-Supervisor-Part: tracking\nAI-Supervisor-Part: substantive\n"
                "AI-Supervisor-Tracking-Reconcile: v1\n"
            ),
        }
        for name, body in bodies.items():
            with self.subTest(name=name):
                source, head = self._reviewed_with_reconcile_body(body)
                report = check(self.root)
                self.assertFalse(report["ok"], report)
                self.assertEqual(report["category"], "checkpoint_metadata_ambiguous")
                self.assertEqual(report["head"], head)
                self.assertNotIn("stage_source", report)
                self.assertEqual(report["nearest_substantive"]["commit"], source)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--root", str(self.root)]), 1)

    def test_duplicate_pair_trailers_fail_closed_instead_of_last_wins(self):
        other = "work-other"
        cases = {
            "tracking_source_identical": ("tracking", "AI-Supervisor-Source-Work: work-1\n"),
            "tracking_source_conflicting": ("tracking", f"AI-Supervisor-Source-Work: {other}\n"),
            "tracking_snapshot_conflicting": ("tracking", "AI-Supervisor-Snapshot: snap-other\n"),
            "substantive_review_conflicting": (
                "substantive", "AI-Supervisor-Review-Checkpoint: rc-other\n"
            ),
            "substantive_part_conflicting": ("substantive", "AI-Supervisor-Part: tracking\n"),
        }
        for name, (part, duplicate) in cases.items():
            with self.subTest(name=name):
                if part == "substantive":
                    self.write("tools/bm023a_adapter_support.py", 'ADAPTER_VERSION = "0.0.10"\n')
                    self.commit("checkpoint: substantive", _trailers("substantive") + duplicate)
                    self.tracking()
                else:
                    self.substantive()
                    self.write(".agent/HANDOFF.md", name + "\n")
                    self.commit("docs: tracking", _trailers("tracking") + duplicate)
                report = check(self.root)
                self.assertFalse(report["ok"], report)
                self.assertEqual(report["category"], "checkpoint_metadata_ambiguous")

    def test_pair_trailers_combined_with_reconcile_marker_are_ambiguous(self):
        self.substantive()
        self.tracking()
        self.write(".agent/HANDOFF.md", "hybrid\n")
        self.commit(
            "docs: hybrid",
            _trailers("tracking") + "AI-Supervisor-Tracking-Reconcile: v1\n",
        )
        report = check(self.root)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["category"], "checkpoint_metadata_ambiguous")

    def test_unrecognized_supervisor_trailer_is_not_an_untrailered_commit(self):
        source = self.substantive()
        self.tracking()
        self.write(".agent/HANDOFF.md", "unknown\n")
        self.commit("docs: unknown family trailer", "AI-Supervisor-Unknown: x\n")
        report = check(self.root)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["category"], "checkpoint_metadata_incomplete")
        self.assertEqual(report["nearest_substantive"]["commit"], source)

    def test_ambiguous_commit_deep_in_lineage_does_not_break_diagnostics(self):
        # nearest_substantive() scans every commit; one ambiguous message must be
        # skipped there, not escape as an unreported error.
        good = self.substantive()
        self.tracking()
        self.write(".agent/HANDOFF.md", "dup\n")
        self.commit("docs: dup", _trailers("tracking") + "AI-Supervisor-Part: tracking\n")
        self.reconcile("tip\n")
        report = check(self.root)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["category"], "checkpoint_metadata_ambiguous")
        self.assertEqual(report["nearest_substantive"]["commit"], good)

    def test_valid_single_trailers_and_extra_prose_remain_accepted(self):
        source = self.substantive()
        self.write(".agent/HANDOFF.md", "tracked\n")
        self.commit(
            "docs: tracking\n\nbody text",
            _trailers("tracking") + "Co-Authored-By: Someone <noreply@example.invalid>\n",
        )
        self.reconcile(
            body="AI-Supervisor-Part: tracking\nAI-Supervisor-Tracking-Reconcile: v1\n"
            "\nCo-Authored-By: Someone <noreply@example.invalid>\n",
        )
        report = check(self.root, expected_version="0.0.10")
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["stage_source"]["commit"], source)

    def test_report_is_deterministic_and_the_check_is_read_only(self):
        self.substantive()
        self.tracking()
        self.reconcile("a\n")
        head = self.reconcile("b\n")
        refs = self.git("for-each-ref")
        first = check(self.root, expected_version="0.0.10")
        second = check(self.root, expected_version="0.0.10")
        self.assertTrue(first["ok"], first)
        self.assertEqual(first, second)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("for-each-ref"), refs)
        self.assertEqual(self.git("status", "--porcelain=v1"), "")

    def test_replace_ref_cannot_hide_a_product_commit(self):
        for shape in ("untrailered", "reconcile"):
            with self.subTest(shape=shape):
                make = self.untrailered_agent if shape == "untrailered" else self.reconcile
                self.substantive()
                self.tracking(note=shape + "\n")
                first = make("a\n")
                self.write("resources/lib/late.py", "y = 2\n")
                self.commit("feat: late untrailered change")
                head = make("b\n")
                message = self.git("log", "-1", "--format=%B", head)
                tree = self.git("rev-parse", head + "^{tree}")
                forged = self.git("commit-tree", tree, "-p", first, "-m", message)
                self.git("replace", head, forged)
                report = check(self.root)
                self.assertFalse(report["ok"], report)
                self.assertEqual(report["category"], "untrailered_product_commit")
                self.git("replace", "-d", head)
                self.git("reset", "-q", "--hard", "HEAD~5")


if __name__ == "__main__":
    unittest.main()
