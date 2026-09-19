from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import core


mcp = MCPServer(
    "Kodi Local Developer",
    instructions=(
        "Scoped local coding tools for the configured git worktree. "
        "Stay inside CHATGPT_LOCAL_WORKSPACE. Read before replacing files. "
        "Use disposable Kodi harness commands only; never touch real Kodi profiles. "
        "Git push, merge, reset, clean, force operations, arbitrary shell execution, "
        "direct .git access, secret-like files, and file deletion are intentionally unavailable."
    ),
)


@mcp.tool()
def workspace_info() -> dict:
    """Return the configured worktree root and current Git status."""
    root = core.workspace_root()
    return {"workspace": str(root), "git": core.git_status()}


@mcp.tool()
def list_directory(path: str = ".") -> dict:
    """List files and directories inside the configured worktree."""
    return core.list_directory(path)


@mcp.tool()
def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> dict:
    """Read a UTF-8 repository file and return its SHA-256 for guarded replacement."""
    return core.read_text_file(path, start_line, end_line)


@mcp.tool()
def search_text(query: str, path: str = ".", case_sensitive: bool = False, max_results: int = 100) -> dict:
    """Search repository text without invoking a shell."""
    return core.search_text(query, path, case_sensitive=case_sensitive, max_results=max_results)


@mcp.tool()
def write_file(
    path: str,
    content: str,
    expected_sha256: str | None = None,
    create_parents: bool = False,
) -> dict:
    """Create or atomically replace a UTF-8 file. Existing files require the SHA returned by read_file."""
    return core.write_text_file(
        path,
        content,
        expected_sha256=expected_sha256,
        create_parents=create_parents,
    )


@mcp.tool()
def apply_patch(patch: str) -> dict:
    """Validate and apply a unified Git patch inside the worktree. File deletion is blocked."""
    return core.apply_patch(patch)


@mcp.tool()
def git_status() -> dict:
    """Return short Git status for the ChatGPT worktree."""
    return core.git_status()


@mcp.tool()
def git_diff(path: str | None = None, staged: bool = False) -> dict:
    """Return the worktree or staged diff, optionally restricted to one repository path."""
    return core.git_diff(path, staged=staged)


@mcp.tool()
def git_log(limit: int = 12) -> dict:
    """Return recent local commits."""
    return core.git_log(limit)


@mcp.tool()
def git_stage(paths: list[str]) -> dict:
    """Stage explicit repository paths. This does not commit or push."""
    return core.git_stage(paths)


@mcp.tool()
def git_commit(message: str) -> dict:
    """Commit already-staged changes locally. Push, merge, reset, clean, and force operations are not exposed."""
    return core.git_commit(message)


@mcp.tool()
def run_tests(target: str | None = None, timeout: int = 600) -> dict:
    """Run the full unittest suite, or one dotted unittest target, inside the worktree."""
    return core.run_tests(target, timeout)


@mcp.tool()
def kodi_harness(command: str, timeout: int = 900) -> dict:
    """Run an approved tools/kodi_test.py command against the disposable Kodi profile only."""
    return core.run_kodi_harness(command, timeout)


if __name__ == "__main__":
    mcp.run()
