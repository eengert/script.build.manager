#!/usr/bin/env python3
"""Keychain-backed credential bridge for the Test.app qualification helper.

Host-side qualification tooling only: it is never staged into Kodi and it is not
part of the Build Manager product. It behaves exactly like ``bm_test_app.py``
(same arguments, same JSON output, same exit codes) except for one thing: when
the Kodi web interface demands a password, the password is read from one fixed
macOS Keychain item inside this local process instead of a hidden terminal
prompt. Nothing else about the reviewed helper is changed or bypassed: exact
Test.app identity, portable ``-p``, exact listener PID, loopback validation, Git
binding, installed-tree verification, result freshness, the secret registry and
the output leak guard all stay inside ``bm_test_app``.

The Keychain item is a constant of this file. It cannot come from the command
line, the environment, a config file or stdin, and there is deliberately no
fallback to the interactive prompt: if the item cannot be read the command fails
closed with a fixed helper error code. Run ``tools/bm_test_app.py`` directly for
the manual hidden prompt.
"""

from __future__ import annotations

import dataclasses
import os
import pwd
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from tools import bm_test_app as bm  # noqa: E402

# The trusted wrapper identity. Deliberately not configurable from anywhere.
SECURITY_BIN = "/usr/bin/security"
KEYCHAIN_SERVICE = "ai-supervisor.test-app-kodi"
KEYCHAIN_ACCOUNT = "kodi"
LOOKUP_ARGV = (
    SECURITY_BIN,
    "find-generic-password",
    "-a", KEYCHAIN_ACCOUNT,
    "-s", KEYCHAIN_SERVICE,
    "-w",
)
KEYCHAIN_TIMEOUT_SECONDS = 15
MAX_OUTPUT_BYTES = 4096
MAX_SECRET_CHARS = 1024


def _lookup_environment() -> Dict[str, str]:
    """A fixed, minimal environment; nothing is inherited from the caller.

    HOME comes from the password database, not from the caller's environment.
    """
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError):
        home = None
    if not isinstance(home, str) or not os.path.isabs(home):
        raise bm.HelperError("credential_prompt_unavailable")
    return {"PATH": "/usr/bin:/bin", "HOME": home}


def _validated_secret(raw: Any) -> Optional[str]:
    """The Keychain item's text, or None. Never raises and never says why.

    Exactly one trailing newline (what ``security -w`` appends) is removed;
    nothing else is trimmed, so a password may legitimately contain spaces.
    """
    if not isinstance(raw, (bytes, bytearray)) or not raw or len(raw) > MAX_OUTPUT_BYTES:
        return None
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        return None
    if text.endswith("\n"):
        text = text[:-1]
    if not text.strip() or len(text) > MAX_SECRET_CHARS:
        return None
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
        return None
    return text


def fetch_keychain_password(runner: Callable[..., Any] = subprocess.run) -> str:
    """Read the fixed Keychain item; fail closed on anything unexpected.

    Failures are raised outside every ``except`` block and only after the
    process output has been dropped, so no exception chain or traceback frame
    can retain the secret or any ``security`` output.
    """
    environment = _lookup_environment()
    try:
        completed = runner(
            list(LOOKUP_ARGV),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):  # includes TimeoutExpired
        completed = None
    if completed is None:
        raise bm.HelperError("credential_prompt_unavailable")
    returncode = getattr(completed, "returncode", None)
    raw = getattr(completed, "stdout", None)
    completed = None
    secret = _validated_secret(raw) if returncode == 0 else None
    raw = None
    if secret is None:
        raise bm.HelperError("credential_missing")
    return secret


def make_keychain_password_prompt(
    runner: Callable[..., Any] = subprocess.run,
) -> Callable[[str], str]:
    """The one replacement for ``Services.password_prompt``."""

    def keychain_password_prompt(_prompt: str) -> str:
        return fetch_keychain_password(runner)

    return keychain_password_prompt


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    """Run the reviewed helper unchanged except for its password source."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    production = bm.Services.production()
    services = dataclasses.replace(
        production, password_prompt=make_keychain_password_prompt(runner)
    )
    return bm.main(arguments, services=services)


if __name__ == "__main__":
    raise SystemExit(main())
