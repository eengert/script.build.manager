from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Iterable


MAX_READ_BYTES = 1_000_000
MAX_WRITE_BYTES = 2_000_000
MAX_PATCH_BYTES = 2_000_000
MAX_PROCESS_OUTPUT = 250_000
MAX_SEARCH_RESULTS = 200

_SKIP_DIRS = {".git", ".kodi-test", ".venv", "__pycache__", "node_modules"}
_SECRET_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
_SECRET_GLOBS = ("*.pem", "*.key", "*.p12", "*.pfx")

KODI_COMMANDS = frozenset(
    {
        "reset",
        "install",
        "configure",
        "enable-webserver",
        "launch",
        "wait",
        "stop",
        "restart",
        "inspect",
        "status",
        "validate",
        "validate-repo",
        "validate-addon",
        "validate-dependencies",
        "validate-addon-state",
        "validate-post-operations",
        "validate-config",
    }
)


class BridgeError(RuntimeError):
    """Safe, user-facing bridge failure."""


def workspace_root() -> Path:
    raw = os.environ.get("CHATGPT_LOCAL_WORKSPACE")
    if not raw:
        raise BridgeError("CHATGPT_LOCAL_WORKSPACE is not set")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise BridgeError(f"workspace does not exist: {root}")
    if not (root / ".git").exists():
        # Worktrees have a .git file rather than a directory, so exists() is enough.
        raise BridgeError(f"workspace is not a git worktree: {root}")
    return root


def _is_secret_path(path: Path) -> bool:
    if os.environ.get("CHATGPT_LOCAL_ALLOW_SECRETS") == "1":
        return False
    name = path.name.lower()
    if name in _SECRET_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in _SECRET_GLOBS)


def resolve_path(relative: str, *, must_exist: bool = False) -> Path:
    if not relative or relative == ".":
        return workspace_root()
    candidate = Path(relative)
    if candidate.is_absolute():
        raise BridgeError("absolute paths are not allowed")
    root = workspace_root()
    target = (root / candidate).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise BridgeError("path escapes the configured workspace") from exc
    if ".git" in target.relative_to(root).parts:
        raise BridgeError("direct .git access is not allowed; use git tools")
    if _is_secret_path(target):
        raise BridgeError("secret-like file is blocked by bridge policy")
    if must_exist and not target.exists():
        raise BridgeError(f"path does not exist: {relative}")
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _truncate(text: str, limit: int = MAX_PROCESS_OUTPUT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n...[output truncated by ChatGPT local bridge]", True


def _run(
    argv: list[str],
    *,
    timeout: float = 120,
    input_text: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    root = workspace_root()
    workdir = cwd or root
    try:
        workdir.resolve().relative_to(root)
    except ValueError as exc:
        raise BridgeError("process cwd escapes the configured workspace") from exc

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(workdir),
            env=env,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError(f"process timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise BridgeError(f"could not start process: {exc}") from exc

    stdout, out_truncated = _truncate(completed.stdout)
    stderr, err_truncated = _truncate(completed.stderr)
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": out_truncated or err_truncated,
    }


def list_directory(path: str = ".") -> dict[str, Any]:
    target = resolve_path(path, must_exist=True)
    if not target.is_dir():
        raise BridgeError(f"not a directory: {path}")
    root = workspace_root()
    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name == ".git" or _is_secret_path(child):
            continue
        item: dict[str, Any] = {
            "path": str(child.relative_to(root)),
            "kind": "directory" if child.is_dir() else "file",
        }
        if child.is_file():
            item["size"] = child.stat().st_size
        entries.append(item)
    return {"path": str(target.relative_to(root)) or ".", "entries": entries}


def read_text_file(path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
    target = resolve_path(path, must_exist=True)
    if not target.is_file():
        raise BridgeError(f"not a file: {path}")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise BridgeError(f"file exceeds {MAX_READ_BYTES} byte read limit")
    if start_line < 1 or (end_line is not None and end_line < start_line):
        raise BridgeError("invalid line range")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BridgeError("file is not UTF-8 text") from exc
    lines = text.splitlines(keepends=True)
    selected = lines[start_line - 1 : end_line]
    return {
        "path": path,
        "sha256": sha256_file(target),
        "size": size,
        "line_count": len(lines),
        "start_line": start_line,
        "end_line": min(end_line or len(lines), len(lines)),
        "content": "".join(selected),
    }


def search_text(
    query: str,
    path: str = ".",
    *,
    case_sensitive: bool = False,
    max_results: int = 100,
) -> dict[str, Any]:
    if not query:
        raise BridgeError("query must not be empty")
    if max_results < 1 or max_results > MAX_SEARCH_RESULTS:
        raise BridgeError(f"max_results must be 1..{MAX_SEARCH_RESULTS}")
    base = resolve_path(path, must_exist=True)
    root = workspace_root()
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)

    files: Iterable[Path]
    if base.is_file():
        files = (base,)
    else:
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            folder = Path(dirpath)
            for filename in filenames:
                candidate = folder / filename
                if _is_secret_path(candidate):
                    continue
                try:
                    if candidate.stat().st_size <= MAX_READ_BYTES:
                        found.append(candidate)
                except OSError:
                    continue
        files = found

    results: list[dict[str, Any]] = []
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                results.append(
                    {
                        "path": str(file_path.relative_to(root)),
                        "line": number,
                        "text": line[:1000],
                    }
                )
                if len(results) >= max_results:
                    return {"query": query, "results": results, "truncated": True}
    return {"query": query, "results": results, "truncated": False}


def write_text_file(
    path: str,
    content: str,
    *,
    expected_sha256: str | None = None,
    create_parents: bool = False,
) -> dict[str, Any]:
    raw = content.encode("utf-8")
    if len(raw) > MAX_WRITE_BYTES:
        raise BridgeError(f"content exceeds {MAX_WRITE_BYTES} byte write limit")
    target = resolve_path(path)
    root = workspace_root()
    if target.exists():
        if not target.is_file():
            raise BridgeError(f"not a file: {path}")
        current_sha = sha256_file(target)
        if expected_sha256 is None:
            raise BridgeError("expected_sha256 is required when replacing an existing file")
        if current_sha != expected_sha256:
            raise BridgeError("file changed since it was read; sha256 mismatch")
    elif expected_sha256 is not None:
        raise BridgeError("expected_sha256 supplied for a file that does not exist")

    parent = target.parent
    if not parent.exists():
        if not create_parents:
            raise BridgeError("parent directory does not exist")
        parent.mkdir(parents=True, exist_ok=True)
        parent.resolve().relative_to(root)

    fd, temp_name = tempfile.mkstemp(prefix=".chatgpt-write-", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return {"path": path, "sha256": sha256_file(target), "size": len(raw)}


def _patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    old_path: str | None = None
    for line in patch.splitlines():
        if line.startswith("--- "):
            old_path = line[4:].split("\t", 1)[0]
            continue
        if not line.startswith("+++ "):
            continue
        new_path = line[4:].split("\t", 1)[0]
        if new_path == "/dev/null":
            raise BridgeError("patch deletion is blocked; delete files manually outside the bridge")
        for candidate in (old_path, new_path):
            if not candidate or candidate == "/dev/null":
                continue
            relative = candidate[2:] if candidate.startswith(("a/", "b/")) else candidate
            resolve_path(relative)
            paths.append(relative)
    if not paths:
        raise BridgeError("patch contains no file paths")
    return sorted(set(paths))


def apply_patch(patch: str) -> dict[str, Any]:
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise BridgeError(f"patch exceeds {MAX_PATCH_BYTES} byte limit")
    paths = _patch_paths(patch)
    check = _run(["git", "apply", "--check", "--whitespace=nowarn", "-"], input_text=patch)
    if check["returncode"] != 0:
        raise BridgeError(f"git apply --check failed:\n{check['stderr'] or check['stdout']}")
    applied = _run(["git", "apply", "--whitespace=nowarn", "-"], input_text=patch)
    if applied["returncode"] != 0:
        raise BridgeError(f"git apply failed:\n{applied['stderr'] or applied['stdout']}")
    stat = _run(["git", "diff", "--stat", "--", *paths])
    return {"paths": paths, "diff_stat": stat["stdout"], "returncode": applied["returncode"]}


def git_status() -> dict[str, Any]:
    return _run(["git", "status", "--short", "--branch"])


def git_diff(path: str | None = None, *, staged: bool = False) -> dict[str, Any]:
    argv = ["git", "diff"]
    if staged:
        argv.append("--staged")
    if path:
        target = resolve_path(path, must_exist=False)
        rel = str(target.relative_to(workspace_root()))
        argv.extend(["--", rel])
    return _run(argv)


def git_log(limit: int = 12) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        raise BridgeError("limit must be 1..100")
    return _run(["git", "log", f"-{limit}", "--oneline", "--decorate"])


def git_stage(paths: list[str]) -> dict[str, Any]:
    if not paths:
        raise BridgeError("at least one path is required")
    rels: list[str] = []
    for path in paths:
        target = resolve_path(path, must_exist=False)
        rels.append(str(target.relative_to(workspace_root())))
    result = _run(["git", "add", "--", *rels])
    if result["returncode"] != 0:
        raise BridgeError(result["stderr"] or result["stdout"] or "git add failed")
    return git_status()


def git_commit(message: str) -> dict[str, Any]:
    message = message.strip()
    if not message or len(message) > 200 or "\n" in message:
        raise BridgeError("commit message must be one non-empty line up to 200 characters")
    result = _run(["git", "commit", "-m", message], timeout=120)
    if result["returncode"] != 0:
        raise BridgeError(result["stderr"] or result["stdout"] or "git commit failed")
    head = _run(["git", "rev-parse", "HEAD"])
    result["head"] = head["stdout"].strip()
    return result


def run_tests(target: str | None = None, timeout: int = 600) -> dict[str, Any]:
    if timeout < 1 or timeout > 1800:
        raise BridgeError("timeout must be 1..1800 seconds")
    if target:
        if not re.fullmatch(r"[A-Za-z0-9_\.]+", target):
            raise BridgeError("test target must be a Python unittest dotted name")
        argv = ["python3", "-m", "unittest", target]
    else:
        argv = ["python3", "-m", "unittest", "discover", "tests"]
    return _run(argv, timeout=timeout)


def run_kodi_harness(command: str, timeout: int = 900) -> dict[str, Any]:
    if command not in KODI_COMMANDS:
        raise BridgeError(f"unsupported Kodi harness command: {command}")
    if timeout < 1 or timeout > 1800:
        raise BridgeError("timeout must be 1..1800 seconds")
    harness = resolve_path("tools/kodi_test.py", must_exist=True)
    return _run(["python3", str(harness), command], timeout=timeout)
