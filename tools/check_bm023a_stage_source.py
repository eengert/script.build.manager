"""Offline, read-only preflight for the BM-023A reviewed staging source.

Replicates the trusted stage adapter's checkpoint-pair selection: a bounded
first-parent walk from HEAD passes tracking checkpoints (and, additionally,
commits with no supervisor trailers that change only ``.agent/**``) until it
reaches the nearest ``AI-Supervisor-Part: substantive`` checkpoint, whose
immediate child must be a ``tracking`` checkpoint with the same
Review-Checkpoint, Source-Work and Snapshot trailers. Reports the commit and
tree that would be staged, its declared adapter version, and any non-``.agent``
product changes between that commit and HEAD. Uncommitted non-``.agent``
changes, untrailered product commits, merges, and malformed trailers fail
closed. Failures exit non-zero with a sanitized category only.

This tool only runs read-only git commands; it never stages, commits, or
touches the network, Test.app, or any device.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys
from typing import Dict, List, Optional


TRAILER_PREFIXES = {
    "review": "AI-Supervisor-Review-Checkpoint:",
    "source": "AI-Supervisor-Source-Work:",
    "snapshot": "AI-Supervisor-Snapshot:",
    "part": "AI-Supervisor-Part:",
}
PAIR_KEYS = ("review", "source", "snapshot")
SUPPORT_PATH = "tools/bm023a_adapter_support.py"
TRACKING_PREFIX = ".agent/"
# Bound the first-parent walks used to select (and, on failure, diagnose)
# the nearest substantive checkpoint.
MAX_ANCESTOR_WALK = 64


class StageSourceError(RuntimeError):
    """Failure carrying only a sanitized category."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StageSourceError("git_unavailable") from exc


def _rev(root: Path, spec: str) -> Optional[str]:
    try:
        return _git(root, "rev-parse", "--verify", "--quiet", spec + "^{commit}").strip() or None
    except StageSourceError:
        return None


def checkpoint_metadata(root: Path, commit: str) -> Dict[str, str]:
    """Parse supervisor trailers exactly as the trusted adapter does."""
    message = _git(root, "show", "-s", "--format=%B", commit)
    values: Dict[str, str] = {}
    for line in message.splitlines():
        stripped = line.strip()
        for key, prefix in TRAILER_PREFIXES.items():
            if stripped.startswith(prefix):
                values[key] = stripped[len(prefix):].strip()
    return values


def _complete(meta: Dict[str, str]) -> bool:
    return all(meta.get(key) for key in TRAILER_PREFIXES)


def declared_adapter_version(root: Path, commit: str) -> Optional[str]:
    """Read ADAPTER_VERSION literally from the commit without importing it."""
    try:
        source = _git(root, "show", f"{commit}:{SUPPORT_PATH}")
        tree = ast.parse(source, filename="<adapter-support>")
    except (StageSourceError, SyntaxError):
        return None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "ADAPTER_VERSION"
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            return value if isinstance(value, str) and value else None
    return None


def product_changes(root: Path, commit: str, head: str) -> List[str]:
    """Paths outside ``.agent/`` that differ between ``commit`` and HEAD."""
    output = _git(root, "diff", "--name-only", "--no-renames", commit, head)
    return sorted(
        path for path in output.splitlines()
        if path and not path.startswith(TRACKING_PREFIX)
    )


def _is_tracking_path(path: str) -> bool:
    return path == ".agent" or path.startswith(TRACKING_PREFIX)


def _reject_uncommitted_product_changes(root: Path) -> None:
    status = _git(
        root, "status", "--porcelain=v1", "--untracked-files=all",
        "--", ".", ":(exclude).agent/**",
    )
    if status.strip():
        raise StageSourceError("uncommitted_product_changes")


def _commit_paths(root: Path, commit: str) -> List[str]:
    """Paths changed by a single-parent commit; merges and roots fail closed."""
    parents = _git(root, "show", "-s", "--format=%P", commit).split()
    if len(parents) != 1:
        raise StageSourceError("lineage_ambiguous")
    output = _git(
        root, "diff-tree", "--no-commit-id", "--name-only", "--no-renames",
        "-r", parents[0], commit,
    )
    return [path for path in output.splitlines() if path]


def select_stage_source(root: Path) -> str:
    """Return the substantive commit the trusted adapter would stage."""
    head = _rev(root, "HEAD")
    if head is None:
        raise StageSourceError("head_unavailable")
    _reject_uncommitted_product_changes(root)
    lineage = _git(
        root, "rev-list", "--first-parent", f"--max-count={MAX_ANCESTOR_WALK}", head,
    ).split()
    child_tracking: Optional[Dict[str, str]] = None
    for commit in lineage:
        meta = checkpoint_metadata(root, commit)
        paths = _commit_paths(root, commit)
        if not meta:
            # Untrailered commits are tolerated only for ``.agent/**`` edits,
            # and never count as the tracking half of a reviewed pair.
            if not paths or not all(_is_tracking_path(path) for path in paths):
                raise StageSourceError("untrailered_product_commit")
            child_tracking = None
            continue
        if not _complete(meta):
            raise StageSourceError("checkpoint_metadata_incomplete")
        if meta["part"] == "tracking":
            child_tracking = meta
            continue
        if meta["part"] != "substantive":
            raise StageSourceError("checkpoint_part_invalid")
        if child_tracking is None:
            raise StageSourceError(
                "head_not_tracking" if commit == head else "tracking_pair_missing"
            )
        for key in PAIR_KEYS:
            if meta[key] != child_tracking[key]:
                raise StageSourceError("pair_metadata_mismatch")
        return commit
    raise StageSourceError("substantive_unavailable")


def nearest_substantive(root: Path, head: str) -> Optional[str]:
    """Bounded first-parent walk for the nearest substantive checkpoint."""
    output = _git(
        root, "rev-list", "--first-parent", f"--max-count={MAX_ANCESTOR_WALK}", head,
    )
    for commit in output.split():
        meta = checkpoint_metadata(root, commit)
        if _complete(meta) and meta["part"] == "substantive":
            return commit
    return None


def _describe(root: Path, commit: str, head: str) -> Dict[str, object]:
    return {
        "commit": commit,
        "tree": _git(root, "rev-parse", commit + "^{tree}").strip(),
        "adapter_version": declared_adapter_version(root, commit),
        "product_changes_to_head": product_changes(root, commit, head),
    }


def check(root: Path, expected_version: Optional[str] = None) -> Dict[str, object]:
    """Build the report; ``ok`` is false when staging would fail or drift."""
    head = _rev(root, "HEAD")
    report: Dict[str, object] = {"ok": False, "head": head}
    try:
        source = select_stage_source(root)
    except StageSourceError as exc:
        report["category"] = exc.category
        if head is not None:
            candidate = nearest_substantive(root, head)
            if candidate is not None:
                report["nearest_substantive"] = _describe(root, candidate, head)
        return report
    assert head is not None
    staged = _describe(root, source, head)
    report["stage_source"] = staged
    if staged["adapter_version"] is None:
        report["category"] = "adapter_version_unavailable"
    elif expected_version is not None and staged["adapter_version"] != expected_version:
        report["category"] = "adapter_version_mismatch"
    elif staged["product_changes_to_head"]:
        report["category"] = "product_changes_after_source"
    else:
        report["ok"] = True
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="product git worktree to inspect (default: this checkout)",
    )
    parser.add_argument(
        "--expected-version",
        help="fail unless the staged ADAPTER_VERSION equals this value",
    )
    args = parser.parse_args(argv)
    try:
        report = check(args.root, args.expected_version)
    except StageSourceError as exc:
        report = {"ok": False, "category": exc.category}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
