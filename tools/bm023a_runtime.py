#!/usr/bin/env python3
"""Isolated macOS Kodi runtime support for the BM-023A diagnostic.

The test HOME and staged Kodi bundle live in the project-local,
git-ignored ``.bm023a-test-runtime`` directory. This module never uses Kodi's
portable ``-p`` mode. It prepares a deterministic migration plan from a
portable_data tree, can clone only persistent profile state, and launches a
staged, signed Kodi 21.3 bundle with HOME redirected to the isolated test HOME.

This tooling has no default app path and performs no live operation at import
time. A real launch is an explicit CLI subcommand.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / ".bm023a-test-runtime"
RUNTIME_HOME = RUNTIME_ROOT / "home"
RUNTIME_MARKER = RUNTIME_ROOT / "BM023A_TEST_STATE.txt"
RUNTIME_MARKER_TEXT = "BM-023A isolated test state. Never use the normal Kodi profile.\n"
STAGED_KODI_APP = RUNTIME_ROOT / "distribution" / "Kodi.app"
KODI_PROFILE_SUFFIX = Path("Library") / "Application Support" / "Kodi"
KODI_LOG_SUFFIX = Path("Library") / "Logs" / "kodi.log"
MIGRATED_ROOTS: Tuple[str, ...] = ("addons", "media", "userdata")
OMITTED_PORTABLE_ROOTS: Tuple[str, ...] = ("system", "temp")
REDIRECT_ENV_KEYS: Tuple[str, ...] = (
    "KODI_HOME",
    "KODI_PROFILE",
    "XBMC_HOME",
    "XBMC_PROFILE",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONPYCACHEPREFIX",
)


class RuntimeSafetyError(RuntimeError):
    """Raised when a runtime path or launch input fails a safety gate."""


class BundleMutationError(RuntimeError):
    """Raised when a Kodi run changes the staged application bundle."""


@dataclass(frozen=True)
class RuntimePaths:
    runtime_root: Path
    home: Path
    kodi_home: Path
    userdata: Path
    addons: Path
    addon_packages: Path
    log_file: Path
    temp_dir: Path


@dataclass(frozen=True)
class MigrationEntry:
    source: Path
    destination: Path


def _absolute(path: Path) -> Path:
    """Normalize a path lexically without resolving symlinks."""
    return Path(os.path.normpath(os.path.abspath(os.fspath(path))))


def _inside(child: Path, parent: Path) -> bool:
    try:
        child_abs = _absolute(child)
        parent_abs = _absolute(parent)
        return os.path.commonpath((str(child_abs), str(parent_abs))) == str(parent_abs)
    except (OSError, ValueError):
        return False


def _overlaps(first: Path, second: Path) -> bool:
    return _inside(first, second) or _inside(second, first)


def _reject_symlink_components(path: Path) -> None:
    """Reject an existing symlink component without resolving its target."""
    path = _absolute(path)
    parts = path.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        if current.is_symlink():
            raise RuntimeSafetyError("symlink in an authorized runtime path")


def _normal_home(inherited_home: Optional[Path] = None) -> Path:
    raw = inherited_home if inherited_home is not None else os.environ.get("HOME")
    if raw is None or not os.fspath(raw):
        raise RuntimeSafetyError("the inherited HOME is unavailable")
    return _absolute(Path(raw))


def paths_for_home(home: Path) -> RuntimePaths:
    home = _absolute(home)
    kodi_home = home / KODI_PROFILE_SUFFIX
    return RuntimePaths(
        runtime_root=RUNTIME_ROOT,
        home=home,
        kodi_home=kodi_home,
        userdata=kodi_home / "userdata",
        addons=kodi_home / "addons",
        addon_packages=kodi_home / "addons" / "packages",
        log_file=home / KODI_LOG_SUFFIX,
        temp_dir=RUNTIME_ROOT / "tmp",
    )


def verify_runtime_layout(
    home: Path,
    *,
    inherited_home: Optional[Path] = None,
    app_bundle: Optional[Path] = None,
    require_marker: bool = True,
) -> RuntimePaths:
    """Validate the fixed project-local HOME without probing normal Kodi data.

    The normal profile path is derived lexically from the inherited HOME. No
    stat, resolve, or file read is performed against that path.
    """
    paths = paths_for_home(home)
    expected_root = _absolute(PROJECT_ROOT / ".bm023a-test-runtime")
    expected_home = expected_root / "home"
    if _absolute(paths.runtime_root) != expected_root:
        raise RuntimeSafetyError("runtime root is not the project BM-023A test root")
    if _overlaps(expected_root, PROJECT_ROOT / ".kodi-test"):
        raise RuntimeSafetyError("BM-023A runtime must remain separate from .kodi-test")
    if paths.home != expected_home:
        raise RuntimeSafetyError("HOME is not the project BM-023A isolated HOME")
    if paths.home == _normal_home(inherited_home):
        raise RuntimeSafetyError("the inherited normal HOME cannot be used as test HOME")

    normal_profile = _normal_home(inherited_home) / KODI_PROFILE_SUFFIX
    if _overlaps(paths.home, normal_profile) or _overlaps(paths.kodi_home, normal_profile):
        raise RuntimeSafetyError("test HOME overlaps the normal Kodi profile")
    if _overlaps(expected_root, normal_profile):
        raise RuntimeSafetyError("BM-023A runtime root overlaps the normal Kodi profile")

    ignore_file = PROJECT_ROOT / ".gitignore"
    try:
        ignored = ".bm023a-test-runtime/" in ignore_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeSafetyError("could not verify the runtime ignore rule") from exc
    if not ignored:
        raise RuntimeSafetyError("BM-023A runtime directory is not excluded from Git")

    if app_bundle is not None:
        app = _absolute(app_bundle)
        if app != _absolute(STAGED_KODI_APP):
            raise RuntimeSafetyError("Kodi app must be staged at the dedicated runtime path")
        if _overlaps(app, paths.home) or _overlaps(app, normal_profile):
            raise RuntimeSafetyError("Kodi app overlaps an authorized profile path")

    for path in (
        expected_root,
        paths.home,
        paths.home / "Library",
        paths.home / "Library" / "Application Support",
        paths.kodi_home,
        paths.userdata,
        paths.addons,
        paths.log_file.parent,
        paths.temp_dir,
    ):
        _reject_symlink_components(path)

    if require_marker:
        _reject_symlink_components(RUNTIME_MARKER)
        try:
            marker_text = RUNTIME_MARKER.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeSafetyError("BM-023A runtime marker is missing or unreadable") from exc
        if marker_text != RUNTIME_MARKER_TEXT:
            raise RuntimeSafetyError("BM-023A runtime marker does not match")
    return paths


def initialize_runtime() -> RuntimePaths:
    """Create the persistent marked HOME skeleton; do not create Kodi state."""
    root = _absolute(RUNTIME_ROOT)
    if root == Path("/") or not _inside(root, PROJECT_ROOT):
        raise RuntimeSafetyError("unsafe BM-023A runtime root")
    _reject_symlink_components(root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / RUNTIME_MARKER.name
    _reject_symlink_components(marker)
    if marker.exists():
        if marker.read_text(encoding="utf-8") != RUNTIME_MARKER_TEXT:
            raise RuntimeSafetyError("existing BM-023A runtime marker does not match")
    else:
        marker.write_text(RUNTIME_MARKER_TEXT, encoding="utf-8")
    home = root / "home"
    _reject_symlink_components(home)
    home.mkdir(parents=True, exist_ok=True)
    (root / "tmp").mkdir(exist_ok=True)
    return verify_runtime_layout(home)


def migration_plan(source_portable_data: Path, home: Path) -> Tuple[MigrationEntry, ...]:
    """Map persistent Kodi state roots, preserving their relative paths."""
    paths = verify_runtime_layout(home)
    source = _absolute(source_portable_data)
    _reject_symlink_components(source)
    if not source.is_dir():
        raise RuntimeSafetyError("portable_data source is not a directory")
    if _overlaps(source, paths.kodi_home):
        raise RuntimeSafetyError("portable_data source overlaps the destination profile")
    entries: List[MigrationEntry] = []
    for name in MIGRATED_ROOTS:
        source_root = source / name
        _reject_symlink_components(source_root)
        if not source_root.is_dir():
            raise RuntimeSafetyError("portable_data is missing a required state directory")
        entries.append(MigrationEntry(source_root, paths.kodi_home / name))
    return tuple(entries)


def _tree_manifest(root: Path) -> Tuple[Tuple[str, str, int, int, str], ...]:
    """Hash a tree without following symlinks; contents are never returned."""
    root = _absolute(root)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeSafetyError("tree root must be a plain directory")
    rows: List[Tuple[str, str, int, int, str]] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise RuntimeSafetyError("could not inventory state tree") from exc
        for entry in entries:
            path = Path(entry.path)
            rel = path.relative_to(root).as_posix()
            st = entry.stat(follow_symlinks=False)
            mode = st.st_mode & 0o7777
            if stat.S_ISLNK(st.st_mode):
                raise RuntimeSafetyError("symlink in state tree")
            if stat.S_ISDIR(st.st_mode):
                rows.append((rel, "dir", mode, 0, ""))
                stack.append(path)
            elif stat.S_ISREG(st.st_mode):
                digest = hashlib.sha256()
                try:
                    with path.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                except OSError as exc:
                    raise RuntimeSafetyError("could not hash state file") from exc
                rows.append((rel, "file", mode, st.st_size, digest.hexdigest()))
            else:
                raise RuntimeSafetyError("unsupported filesystem node in state tree")
    return tuple(sorted(rows))


def migrate_portable_state(source_portable_data: Path, home: Path) -> RuntimePaths:
    """Clone addons and userdata into a fresh isolated Kodi profile.

    ``media``, ``system``, and ``temp`` are retained in the forensic portable
    backup but are runtime resources or transient state, not migrated profile
    data. The source is hashed before and after the copy and is never written.
    """
    paths = verify_runtime_layout(home)
    plan = migration_plan(source_portable_data, home)
    source = _absolute(source_portable_data)
    for entry in plan:
        # Reject any nested links/special nodes before copying.
        _tree_manifest(entry.source)
    source_before = {name: _tree_manifest(source / name) for name in MIGRATED_ROOTS}

    if paths.kodi_home.exists():
        raise RuntimeSafetyError("destination Kodi profile already exists")
    parent = paths.kodi_home.parent
    _reject_symlink_components(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / ".Kodi.bm023a-migration-staging"
    if stage.exists() or stage.is_symlink():
        raise RuntimeSafetyError("migration staging path already exists")
    stage.mkdir()
    try:
        for name in MIGRATED_ROOTS:
            shutil.copytree(source / name, stage / name, copy_function=shutil.copy2)
        staged = {name: _tree_manifest(stage / name) for name in MIGRATED_ROOTS}
        source_after = {name: _tree_manifest(source / name) for name in MIGRATED_ROOTS}
        if source_before != source_after:
            raise RuntimeSafetyError("portable_data source changed during migration")
        if source_before != staged:
            raise RuntimeSafetyError("migrated profile failed byte and structure verification")
        stage.rename(paths.kodi_home)
    except Exception:
        # Preserve a failed staging tree for diagnosis; never alter the source.
        raise
    return paths


def build_child_environment(
    home: Path,
    *,
    inherited: Optional[Mapping[str, str]] = None,
    suppress_python_bytecode: bool = False,
) -> Dict[str, str]:
    """Build a controlled child environment rooted under the isolated HOME."""
    env = dict(os.environ if inherited is None else inherited)
    for key in REDIRECT_ENV_KEYS:
        env.pop(key, None)
    env["HOME"] = str(_absolute(home))
    env["XDG_CONFIG_HOME"] = str(_absolute(home) / ".config")
    env["XDG_DATA_HOME"] = str(_absolute(home) / ".local" / "share")
    env["XDG_CACHE_HOME"] = str(_absolute(home) / ".cache")
    env["PYTHONPYCACHEPREFIX"] = str(_absolute(home) / ".cache" / "python-bytecode")
    env["TMPDIR"] = str(_absolute(RUNTIME_ROOT / "tmp"))
    if suppress_python_bytecode:
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    else:
        env.pop("PYTHONDONTWRITEBYTECODE", None)
    return env


def capture_bundle_manifest(app_bundle: Path) -> Dict[str, object]:
    """Capture a deterministic structural/hash manifest without following links."""
    bundle = _absolute(app_bundle)
    _reject_symlink_components(bundle)
    if not bundle.is_dir():
        raise RuntimeSafetyError("Kodi app bundle is not a directory")
    rows: List[Dict[str, object]] = []
    root_stat = bundle.lstat()
    rows.append({
        "path": ".",
        "type": "directory",
        "mode": root_stat.st_mode & 0o7777,
        "mtime_ns": root_stat.st_mtime_ns,
        "xattrs": _xattr_manifest(bundle),
    })
    stack = [bundle]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
        for entry in entries:
            path = Path(entry.path)
            rel = path.relative_to(bundle).as_posix()
            st = entry.stat(follow_symlinks=False)
            row: Dict[str, object] = {
                "path": rel,
                "mode": st.st_mode & 0o7777,
                "mtime_ns": st.st_mtime_ns,
                "xattrs": _xattr_manifest(path),
            }
            if stat.S_ISLNK(st.st_mode):
                row["type"] = "symlink"
                row["target"] = os.readlink(path)
            elif stat.S_ISDIR(st.st_mode):
                row["type"] = "directory"
                stack.append(path)
            elif stat.S_ISREG(st.st_mode):
                row["type"] = "file"
                row["size"] = st.st_size
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                row["sha256"] = digest.hexdigest()
            else:
                raise RuntimeSafetyError("unsupported filesystem node in Kodi bundle")
            rows.append(row)
    rows.sort(key=lambda row: str(row["path"]))
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": 1,
        "xattrs_supported": hasattr(os, "listxattr") and hasattr(os, "getxattr"),
        "entries": rows,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _xattr_manifest(path: Path) -> List[Tuple[str, int, str]]:
    """Hash extended attributes without returning their potentially private bytes."""
    listxattr = getattr(os, "listxattr", None)
    getxattr = getattr(os, "getxattr", None)
    if listxattr is None or getxattr is None:
        return []
    try:
        names = sorted(listxattr(path, follow_symlinks=False))
        result: List[Tuple[str, int, str]] = []
        for name in names:
            value = getxattr(path, name, follow_symlinks=False)
            result.append((name, len(value), hashlib.sha256(value).hexdigest()))
        return result
    except OSError as exc:
        # Filesystems may report that extended attributes are unsupported.
        unsupported = {errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
        if getattr(exc, "errno", None) in unsupported:
            return []
        raise RuntimeSafetyError("could not inventory bundle extended attributes") from exc


def compare_bundle_manifests(
    before: Mapping[str, object], after: Mapping[str, object]
) -> Dict[str, List[str]]:
    """Return added, removed, and changed bundle-relative paths."""
    before_rows = {str(row["path"]): row for row in before.get("entries", [])}  # type: ignore[index]
    after_rows = {str(row["path"]): row for row in after.get("entries", [])}  # type: ignore[index]
    before_paths = set(before_rows)
    after_paths = set(after_rows)
    return {
        "added": sorted(after_paths - before_paths),
        "removed": sorted(before_paths - after_paths),
        "changed": sorted(
            path for path in before_paths & after_paths
            if before_rows[path] != after_rows[path]
        ),
    }


def verify_kodi_app(
    app_bundle: Path,
    *,
    expected_version: str = "21.3",
    expected_arch: str = "x86_64",
) -> Tuple[Path, Dict[str, str]]:
    """Verify staged Kodi identity, architecture, and strict code signature."""
    app = _absolute(app_bundle)
    if app != _absolute(STAGED_KODI_APP):
        raise RuntimeSafetyError("Kodi app must be staged at the dedicated runtime path")
    _reject_symlink_components(app)
    plist = app / "Contents" / "Info.plist"
    _reject_symlink_components(plist)
    if not app.is_dir() or not plist.is_file():
        raise RuntimeSafetyError("staged Kodi bundle or Info.plist is missing")
    try:
        with plist.open("rb") as stream:
            info = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RuntimeSafetyError("could not read staged Kodi bundle identity") from exc
    version = str(info.get("CFBundleShortVersionString", ""))
    bundle_id = str(info.get("CFBundleIdentifier", ""))
    executable_name = str(info.get("CFBundleExecutable", ""))
    if version != expected_version or not bundle_id or not executable_name:
        raise RuntimeSafetyError("staged Kodi version or bundle identity is unexpected")
    if Path(executable_name).name != executable_name:
        raise RuntimeSafetyError("Kodi executable name is unsafe")
    executable = app / "Contents" / "MacOS" / executable_name
    _reject_symlink_components(executable)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeSafetyError("staged Kodi executable is missing or not executable")
    try:
        file_result = subprocess.run(
            ["/usr/bin/file", "-b", str(executable)],
            check=True,
            capture_output=True,
            text=True,
        )
        architecture = file_result.stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeSafetyError("could not verify Kodi executable architecture") from exc
    if re.search(r"\b" + re.escape(expected_arch) + r"\b", architecture) is None:
        raise RuntimeSafetyError("staged Kodi executable architecture is unexpected")
    try:
        verify = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
            check=True,
            capture_output=True,
            text=True,
        )
        details = subprocess.run(
            ["/usr/bin/codesign", "-dv", "--verbose=4", str(app)],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeSafetyError("strict Kodi code-signature verification failed") from exc
    signature_text = details.stdout + details.stderr
    authority = next(
        (line.partition("=")[2] for line in signature_text.splitlines() if line.startswith("Authority=")),
        "",
    )
    team_id = next(
        (line.partition("=")[2] for line in signature_text.splitlines() if line.startswith("TeamIdentifier=")),
        "",
    )
    if verify.returncode != 0 or not authority or not team_id or team_id == "not set":
        raise RuntimeSafetyError("Kodi bundle is not validly signed by a Developer ID")
    return executable, {
        "version": version,
        "bundle_id": bundle_id,
        "architecture": architecture,
        "authority": authority,
        "team_id": team_id,
    }


def _save_manifest(path: Path, manifest: Mapping[str, object], bundle: Path) -> None:
    path = _absolute(path)
    if _overlaps(path, bundle):
        raise RuntimeSafetyError("bundle manifests must be outside the app bundle")
    _reject_symlink_components(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def launch_kodi(
    app_bundle: Path,
    home: Path,
    *,
    suppress_python_bytecode: bool = False,
    inherited_env: Optional[Mapping[str, str]] = None,
) -> int:
    """Run staged Kodi with HOME isolation and enforce before/after bundle hashes."""
    paths = verify_runtime_layout(home, app_bundle=app_bundle)
    if not paths.kodi_home.is_dir() or not paths.userdata.is_dir() or not paths.addons.is_dir():
        raise RuntimeSafetyError("isolated Kodi profile is not fully prepared")
    if paths.kodi_home.is_symlink() or paths.userdata.is_symlink() or paths.addons.is_symlink():
        raise RuntimeSafetyError("isolated Kodi profile contains a symlink")
    executable, _identity = verify_kodi_app(app_bundle)
    baseline = capture_bundle_manifest(app_bundle)
    manifest_dir = paths.runtime_root / "bundle-manifests"
    run_id = str(time.time_ns())
    before_path = manifest_dir / f"{run_id}-before.json"
    after_path = manifest_dir / f"{run_id}-after.json"
    _save_manifest(before_path, baseline, app_bundle)
    for directory in (
        paths.temp_dir,
        paths.log_file.parent,
        paths.home / ".config",
        paths.home / ".local" / "share",
        paths.home / ".cache",
    ):
        _reject_symlink_components(directory)
        directory.mkdir(parents=True, exist_ok=True)
    env = build_child_environment(
        paths.home,
        inherited=inherited_env,
        suppress_python_bytecode=suppress_python_bytecode,
    )
    process = subprocess.Popen([str(executable)], cwd=str(paths.runtime_root), env=env)
    return_code = process.wait()
    after = capture_bundle_manifest(app_bundle)
    _save_manifest(after_path, after, app_bundle)
    differences = compare_bundle_manifests(baseline, after)
    if any(differences.values()):
        raise BundleMutationError(
            "Kodi changed its staged application bundle; inspect the saved manifests"
        )
    return return_code


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="create or validate the marked isolated HOME skeleton")
    plan_parser = subparsers.add_parser("plan-migration", help="show the portable profile mapping")
    plan_parser.add_argument("--source-portable-data", type=Path, required=True)
    plan_parser.add_argument("--home", type=Path, required=True)
    migrate_parser = subparsers.add_parser("migrate-state", help="clone addons and userdata once")
    migrate_parser.add_argument("--source-portable-data", type=Path, required=True)
    migrate_parser.add_argument("--home", type=Path, required=True)
    launch_parser = subparsers.add_parser("launch", help="launch staged Kodi with bundle mutation checks")
    launch_parser.add_argument("--app", type=Path, required=True)
    launch_parser.add_argument("--home", type=Path, required=True)
    launch_parser.add_argument("--suppress-python-bytecode", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "init":
            paths = initialize_runtime()
            print("isolated HOME initialized")
            print(f"Kodi profile: {paths.kodi_home}")
            print(f"Kodi log: {paths.log_file}")
            return 0
        if args.command == "plan-migration":
            entries = migration_plan(args.source_portable_data, args.home)
            paths = verify_runtime_layout(args.home)
            for entry in entries:
                print(f"{entry.source} -> {entry.destination}")
            print(f"old portable temp/log cache retained only in forensic backup: {paths.log_file}")
            return 0
        if args.command == "migrate-state":
            paths = migrate_portable_state(args.source_portable_data, args.home)
            print(f"Kodi profile cloned: {paths.kodi_home}")
            return 0
        if args.command == "launch":
            code = launch_kodi(
                args.app,
                args.home,
                suppress_python_bytecode=args.suppress_python_bytecode,
            )
            print(f"Kodi exited with status {code}; application bundle unchanged")
            return code
    except (RuntimeSafetyError, BundleMutationError, OSError) as exc:
        print(f"BM-023A runtime stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
