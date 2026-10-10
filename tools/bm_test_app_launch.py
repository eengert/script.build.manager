#!/usr/bin/env python3
"""Launch the authorized portable Test.app and keep it out of foreground."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

if __package__:  # Package import for tests; script import below for CLI use.
    from .bm_test_app import (
        AUTHORIZED_TEST_APP,
        HelperError,
        ProcessVanished,
        PsProcessLister,
        Services,
        TestAppTarget,
        identify,
    )
else:
    from bm_test_app import (
        AUTHORIZED_TEST_APP,
        HelperError,
        ProcessVanished,
        PsProcessLister,
        Services,
        TestAppTarget,
        identify,
    )


OPEN = "/usr/bin/open"
OPEN_ARGS = ("-g", AUTHORIZED_TEST_APP, "--args", "-p")
OPEN_TIMEOUT_SECONDS = 10.0
CONTROL_TIMEOUT_SECONDS = 2.0
STARTUP_MONITOR_SECONDS = 15.0
DISCOVERY_INTERVAL_SECONDS = 0.75
POLL_INTERVAL_SECONDS = 0.25
MAX_HIDE_ATTEMPTS = 3
RESTORE_VERIFY_SECONDS = 1.0
_BUNDLE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}\Z")
_PORTABLE_PREFIX_FLAGS = frozenset({"--debug", "-fs", "--fullscreen", "--standalone", "-q", "--quiet"})


class LaunchError(Exception):
    """Fixed-code failure; raw AppleScript or process output never escapes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ApplicationIdentity:
    name: str
    pid: int
    bundle_id: str


@dataclass(frozen=True)
class TestAppProcess:
    pid: int
    executable: str


def _positive_pid(text: str) -> int:
    try:
        pid = int(text.strip())
    except (TypeError, ValueError):
        raise LaunchError("application_identity_unavailable") from None
    if pid <= 0:
        raise LaunchError("application_identity_unavailable")
    return pid


class MacApplicationControl:
    """PID-targeted System Events controls; no keyboard synthesis."""

    def __init__(self, runner: Callable[..., Any] = subprocess.run) -> None:
        self._run = runner

    def _script(self, source: str) -> str:
        try:
            completed = self._run(
                ["/usr/bin/osascript", "-e", source],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=CONTROL_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise LaunchError("application_control_failed") from None
        if completed.returncode != 0:
            raise LaunchError("application_control_failed")
        return completed.stdout.strip()

    def foreground(self) -> ApplicationIdentity:
        source = (
            'tell application "System Events" to tell '
            '(first application process whose frontmost is true) to return '
            'name & tab & (unix id as text) & tab & bundle identifier'
        )
        fields = self._script(source).split("\t")
        if len(fields) != 3:
            raise LaunchError("foreground_identity_unavailable")
        name, pid_text, bundle_id = (field.strip() for field in fields)
        pid = _positive_pid(pid_text)
        if not name or not _BUNDLE_ID_RE.fullmatch(bundle_id):
            raise LaunchError("foreground_identity_unavailable")
        return ApplicationIdentity(name, pid, bundle_id)

    def pids_for_bundle(self, bundle_id: str) -> Tuple[int, ...]:
        if not _BUNDLE_ID_RE.fullmatch(bundle_id):
            raise LaunchError("bundle_identity_invalid")
        source = (
            'tell application "System Events" to return '
            f'(unix id of every application process whose bundle identifier is "{bundle_id}") as text'
        )
        output = self._script(source)
        if not output:
            return ()
        if not re.fullmatch(r"\s*\d+(?:\s*,\s*\d+)*\s*", output):
            raise LaunchError("application_process_list_invalid")
        return tuple(_positive_pid(value) for value in re.findall(r"\d+", output))

    def identity_for_pid(self, pid: int) -> ApplicationIdentity:
        source = (
            'tell application "System Events" to tell '
            f'(first application process whose unix id is {int(pid)}) to return '
            'name & tab & (unix id as text) & tab & bundle identifier'
        )
        fields = self._script(source).split("\t")
        if len(fields) != 3:
            raise LaunchError("application_identity_changed")
        name, pid_text, bundle_id = (field.strip() for field in fields)
        actual_pid = _positive_pid(pid_text)
        if actual_pid != pid or not name or not _BUNDLE_ID_RE.fullmatch(bundle_id):
            raise LaunchError("application_identity_changed")
        return ApplicationIdentity(name, actual_pid, bundle_id)

    def hide_pid(self, pid: int) -> None:
        source = (
            'tell application "System Events" to tell '
            f'(first application process whose unix id is {int(pid)}) to set visible to false'
        )
        self._script(source)

    def activate_pid(self, pid: int) -> None:
        source = (
            'tell application "System Events" to tell '
            f'(first application process whose unix id is {int(pid)}) to set frontmost to true'
        )
        self._script(source)


class LaunchOperations:
    """Operating-system calls are isolated here for offline behavioral tests."""

    def __init__(
        self,
        *,
        process_lister: Optional[PsProcessLister] = None,
        app_control: Optional[MacApplicationControl] = None,
        runner: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.target = TestAppTarget.authorized()
        self.process_lister = process_lister or PsProcessLister()
        self.app_control = app_control or MacApplicationControl()
        self._run = runner
        self.clock = clock
        self.sleep = sleep
        self.bundle_id: Optional[str] = None
        self.executable_name: Optional[str] = None
        self.executable_aliases: Tuple[str, ...] = ()

    def preflight(self) -> None:
        try:
            identity = identify(Services.production(), require="not_running")
        except HelperError as exc:
            raise LaunchError("test_app_preflight_failed") from exc
        self.bundle_id = identity.bundle.identifier
        self.executable_name = identity.bundle.executable
        self.executable_aliases = self.target.exe_aliases(identity.bundle.executable)

    def foreground(self) -> ApplicationIdentity:
        return self.app_control.foreground()

    def launch(self) -> None:
        try:
            completed = self._run(
                [OPEN, *OPEN_ARGS],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=OPEN_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            # open may already have dispatched the Launch Services request.
            # Do not invoke it a second time; continue bounded process discovery.
            return
        except OSError:
            raise LaunchError("open_failed") from None
        if completed.returncode != 0:
            raise LaunchError("open_failed")

    def verify_pid(self, pid: int) -> Optional[TestAppProcess]:
        if self.executable_name is None:
            raise LaunchError("helper_not_initialized")
        try:
            executable = self.process_lister.native.executable(pid)
        except (HelperError, ProcessVanished):
            return None
        if executable not in self.executable_aliases:
            return None
        try:
            argv = self.process_lister.command_line(pid)
        except HelperError:
            return None
        if not argv or argv[0] not in self.executable_aliases:
            return None
        if not self._has_portable_flag(argv):
            raise LaunchError("test_app_not_portable")
        # command_line rechecks the executable around argv acquisition.
        return TestAppProcess(pid=pid, executable=executable)

    @staticmethod
    def _has_portable_flag(argv: Sequence[str]) -> bool:
        for argument in argv[1:]:
            if argument == "-p":
                return True
            if argument not in _PORTABLE_PREFIX_FLAGS:
                return False
        return False

    def find_test_process(self) -> Optional[TestAppProcess]:
        if self.bundle_id is None:
            raise LaunchError("helper_not_initialized")
        matches = []
        for pid in self.app_control.pids_for_bundle(self.bundle_id):
            process = self.verify_pid(pid)
            if process is not None:
                matches.append(process)
        if len(matches) > 1:
            raise LaunchError("multiple_test_app_processes")
        return matches[0] if matches else None

    def hide_verified(self, process: TestAppProcess) -> None:
        current = self.verify_pid(process.pid)
        if current != process:
            raise LaunchError("test_app_identity_changed_before_hide")
        self.app_control.hide_pid(process.pid)

    def restore_previous(
        self,
        previous: ApplicationIdentity,
        test_pid: int,
        *,
        safe: bool,
    ) -> bool:
        if not safe:
            return False
        try:
            current = self.foreground()
            if current == previous:
                return True
            if current.pid != test_pid:
                # The user (or another process) took focus after the last
                # monitor sample; restoring now would steal it back.
                return False
            if self.app_control.identity_for_pid(previous.pid) != previous:
                return False
            self.app_control.activate_pid(previous.pid)
        except LaunchError:
            return False
        deadline = self.clock() + RESTORE_VERIFY_SECONDS
        while self.clock() < deadline:
            try:
                current = self.foreground()
            except LaunchError:
                return False
            if current.pid == previous.pid and current.bundle_id == previous.bundle_id:
                return True
            if current.pid == test_pid:
                self.sleep(min(POLL_INTERVAL_SECONDS, max(0.0, deadline - self.clock())))
                continue
            if current.pid not in (previous.pid, test_pid):
                return False
            self.sleep(min(POLL_INTERVAL_SECONDS, max(0.0, deadline - self.clock())))
        return False


def launch_and_background(
    operations: LaunchOperations,
    *,
    monitor_seconds: float = STARTUP_MONITOR_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> Dict[str, Any]:
    if monitor_seconds <= 0 or monitor_seconds > STARTUP_MONITOR_SECONDS:
        raise LaunchError("monitor_bound_invalid")
    operations.preflight()
    previous = operations.foreground()
    if previous.pid <= 0 or not previous.bundle_id:
        raise LaunchError("foreground_identity_unavailable")
    operations.launch()

    start = operations.clock()
    deadline = start + monitor_seconds
    next_discovery = start
    test_process: Optional[TestAppProcess] = None
    hide_count = 0
    unrelated_focus_seen = False
    previous_restored = False

    while operations.clock() < deadline:
        now = operations.clock()
        if test_process is None or now >= next_discovery:
            test_process = operations.find_test_process()
            next_discovery = now + DISCOVERY_INTERVAL_SECONDS

        foreground = operations.foreground()
        if test_process is None and foreground.bundle_id == operations.bundle_id:
            test_process = operations.verify_pid(foreground.pid)

        if (
            foreground.pid != previous.pid
            and foreground.bundle_id != operations.bundle_id
            and (test_process is None or foreground.pid != test_process.pid)
        ):
            unrelated_focus_seen = True

        if test_process is not None:
            verified = operations.verify_pid(test_process.pid)
            if verified is None:
                test_process = None
            else:
                test_process = verified
                if foreground.pid == test_process.pid:
                    if hide_count >= MAX_HIDE_ATTEMPTS:
                        raise LaunchError("foreground_reactivated_repeatedly")
                    operations.hide_verified(test_process)
                    hide_count += 1
                    previous_restored = operations.restore_previous(
                        previous, test_process.pid, safe=not unrelated_focus_seen
                    ) or previous_restored

        remaining = deadline - operations.clock()
        if remaining > 0:
            operations.sleep(min(poll_interval, remaining))

    test_process = operations.find_test_process()
    if test_process is None:
        raise LaunchError("test_app_not_running_portable")
    verified = operations.verify_pid(test_process.pid)
    if verified is None:
        raise LaunchError("test_app_identity_unverified")
    final_foreground = operations.foreground()
    previous_restored = previous_restored or (
        final_foreground == previous
    )
    if final_foreground.pid == verified.pid:
        # One last identity-checked hide is bounded by the same retry limit.
        if hide_count >= MAX_HIDE_ATTEMPTS:
            raise LaunchError("foreground_reactivated_repeatedly")
        operations.hide_verified(verified)
        hide_count += 1
        previous_restored = operations.restore_previous(
            previous, verified.pid, safe=not unrelated_focus_seen
        ) or previous_restored
        final_foreground = operations.foreground()
    if final_foreground.pid == verified.pid:
        raise LaunchError("test_app_foreground_after_hide")

    return {
        "background_verified": True,
        "command": "launch-and-background",
        "foreground_after": asdict(final_foreground),
        "hide_count": hide_count,
        "launch_command": 'open -g "/Applications/Kodi Build Manager Test.app" --args -p',
        "monitor_seconds": round(operations.clock() - start, 2),
        "previous_foreground": asdict(previous),
        "previous_restored": previous_restored,
        "test_app": {
            "executable": verified.executable,
            "pid": verified.pid,
            "portable": True,
            "running": True,
        },
        "ok": True,
    }


def main() -> int:
    try:
        result = launch_and_background(LaunchOperations())
        code = 0
    except LaunchError as exc:
        result = {"command": "launch-and-background", "error": exc.code, "ok": False}
        code = 1
    except KeyboardInterrupt:
        result = {"command": "launch-and-background", "error": "interrupted", "ok": False}
        code = 130
    except Exception:
        result = {"command": "launch-and-background", "error": "unexpected_error", "ok": False}
        code = 1
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
