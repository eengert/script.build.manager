"""Offline, read-only preflight for the BM-023A reviewed staging source.

Replicates the trusted stage adapter's checkpoint-pair selection: worker HEAD
must be an ``AI-Supervisor-Part: tracking`` checkpoint whose first parent is
the matching ``substantive`` checkpoint (same Review-Checkpoint, Source-Work
and Snapshot trailers). Reports the commit that would be staged, its declared
adapter version, and any non-``.agent`` product changes between that commit
and HEAD. Failures exit non-zero with a sanitized category only.

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
# Bound the diagnostic first-parent walk used to locate the nearest
# substantive checkpoint when the HEAD/HEAD^ pair is invalid.
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


def select_stage_source(root: Path) -> str:
    """Return the substantive commit the trusted adapter would stage."""
    head = _rev(root, "HEAD")
    if head is None:
        raise StageSourceError("head_unavailable")
    head_meta = checkpoint_metadata(root, head)
    if not _complete(head_meta):
        raise StageSourceError("head_metadata_incomplete")
    if head_meta["part"] != "tracking":
        raise StageSourceError("head_not_tracking")
    parent = _rev(root, head + "^")
    if parent is None:
        raise StageSourceError("parent_unavailable")
    parent_meta = checkpoint_metadata(root, parent)
    if not _complete(parent_meta):
        raise StageSourceError("parent_metadata_incomplete")
    if parent_meta["part"] != "substantive":
        raise StageSourceError("parent_not_substantive")
    for key in PAIR_KEYS:
        if parent_meta[key] != head_meta[key]:
            raise StageSourceError("pair_metadata_mismatch")
    return parent


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
        "adapter_version": declared_adapter_version(root, commit),
        "product_changes_to_head": product_changes(root, commit, head),
    }


def check(root: Path) -> Dict[str, object]:
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
    args = parser.parse_args(argv)
    try:
        report = check(args.root)
    except StageSourceError as exc:
        report = {"ok": False, "category": exc.category}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
