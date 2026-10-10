import subprocess
import unittest

from tools import bm_test_app_launch as launch


class FakeOperations:
    bundle_id = "org.xbmc.kodi"

    def __init__(
        self, *, process_at=0.0, focus_at=0.5, other_at=None,
        target=True, foreground_candidate=True,
    ):
        self.now = 0.0
        self.previous = launch.ApplicationIdentity("ChatGPT", 101, "com.openai.codex")
        self.other = launch.ApplicationIdentity("Finder", 303, "com.apple.finder")
        self.target = launch.TestAppProcess(
            202, "/Applications/Kodi Build Manager Test.app/Contents/MacOS/Kodi"
        )
        self.process_at = process_at
        self.focus_at = focus_at
        self.other_at = other_at
        self.target_available = target
        self.foreground_candidate = foreground_candidate
        self.launch_count = 0
        self.hide_pids = []
        self.restore_pids = []
        self.hidden = False
        self.preflight_count = 0

    def preflight(self):
        self.preflight_count += 1

    def foreground(self):
        if (self.other_at is not None and self.now >= self.other_at
                and self.now < self.focus_at and not self.hidden):
            return self.other
        if self.now >= self.focus_at and self.foreground_candidate and not self.hidden:
            return launch.ApplicationIdentity("Kodi", self.target.pid, self.bundle_id)
        return self.previous

    def launch(self):
        self.launch_count += 1

    def find_test_process(self):
        return self.target if self.target_available and self.now >= self.process_at else None

    def verify_pid(self, pid):
        return self.target if self.target_available and pid == self.target.pid else None

    def hide_verified(self, process):
        self.assert_target(process)
        self.hide_pids.append(process.pid)
        self.hidden = True

    def assert_target(self, process):
        if process != self.target:
            raise AssertionError("unverified target was hidden")

    def restore_previous(self, previous, test_pid, *, safe):
        self.restore_pids.append((previous.pid, test_pid, safe))
        return safe

    def clock(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class BMTestAppLaunchTests(unittest.TestCase):
    def test_delayed_focus_steal_hides_verified_pid_and_restores_prior_app(self):
        operations = FakeOperations(process_at=0.25, focus_at=1.25)
        result = launch.launch_and_background(
            operations, monitor_seconds=2.0, poll_interval=0.25
        )

        self.assertEqual(operations.preflight_count, 1)
        self.assertEqual(operations.launch_count, 1)
        self.assertEqual(operations.hide_pids, [202])
        self.assertEqual(operations.restore_pids, [(101, 202, True)])
        self.assertTrue(result["background_verified"])
        self.assertEqual(result["test_app"]["pid"], 202)
        self.assertTrue(result["test_app"]["portable"])

    def test_other_foreground_change_prevents_focus_stealing_restore(self):
        operations = FakeOperations(process_at=0.0, focus_at=1.0, other_at=0.5)
        result = launch.launch_and_background(
            operations, monitor_seconds=2.0, poll_interval=0.25
        )

        self.assertTrue(result["background_verified"])
        self.assertEqual(operations.hide_pids, [202])
        self.assertEqual(operations.restore_pids, [(101, 202, False)])

    def test_wrong_executable_with_kodi_bundle_id_is_never_hidden(self):
        operations = FakeOperations(
            process_at=0.0, focus_at=0.25, target=False, foreground_candidate=True
        )
        with self.assertRaises(launch.LaunchError) as raised:
            launch.launch_and_background(
                operations, monitor_seconds=1.0, poll_interval=0.25
            )

        self.assertEqual(raised.exception.code, "test_app_not_running_portable")
        self.assertEqual(operations.hide_pids, [])
        self.assertEqual(operations.launch_count, 1)

    def test_launch_is_not_attempted_without_recorded_foreground_identity(self):
        class NoForeground(FakeOperations):
            def foreground(self):
                raise launch.LaunchError("foreground_identity_unavailable")

        operations = NoForeground()
        with self.assertRaises(launch.LaunchError):
            launch.launch_and_background(operations, monitor_seconds=1.0)
        self.assertEqual(operations.launch_count, 0)

    def test_open_uses_only_authorized_background_portable_arguments(self):
        calls = []

        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        operations = launch.LaunchOperations(runner=runner)
        operations.launch()

        self.assertEqual(calls[0][0], [
            "/usr/bin/open",
            "-g",
            "/Applications/Kodi Build Manager Test.app",
            "--args",
            "-p",
        ])
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(calls[0][1]["timeout"], launch.OPEN_TIMEOUT_SECONDS)

    def test_hide_control_targets_only_the_verified_pid(self):
        scripts = []

        def runner(args, **kwargs):
            scripts.append(args[-1])
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        control = launch.MacApplicationControl(runner=runner)
        control.hide_pid(202)

        self.assertIn("unix id is 202", scripts[0])
        self.assertIn("set visible to false", scripts[0])
        self.assertNotIn("keystroke", scripts[0])

    def test_restore_does_not_override_a_new_foreground_application(self):
        class Controls:
            def __init__(self):
                self.activated = []

            def foreground(self):
                return launch.ApplicationIdentity("Finder", 303, "com.apple.finder")

            def identity_for_pid(self, pid):
                return launch.ApplicationIdentity("ChatGPT", pid, "com.openai.codex")

            def activate_pid(self, pid):
                self.activated.append(pid)

        controls = Controls()
        operations = launch.LaunchOperations(app_control=controls)
        restored = operations.restore_previous(
            launch.ApplicationIdentity("ChatGPT", 101, "com.openai.codex"),
            202,
            safe=True,
        )

        self.assertFalse(restored)
        self.assertEqual(controls.activated, [])

    def test_process_verification_requires_exact_executable_and_portable_flag(self):
        expected = "/Applications/Kodi Build Manager Test.app/Contents/MacOS/Kodi"

        class Native:
            def executable(self, pid):
                return expected

        class ProcessLister:
            native = Native()

            def command_line(self, pid):
                return (expected, "-p")

        operations = launch.LaunchOperations(process_lister=ProcessLister())
        operations.executable_name = "Kodi"
        operations.executable_aliases = operations.target.exe_aliases("Kodi")
        self.assertEqual(
            operations.verify_pid(202), launch.TestAppProcess(202, expected)
        )

        ProcessLister.command_line = lambda self, pid: (expected, "--fullscreen")
        with self.assertRaises(launch.LaunchError) as raised:
            operations.verify_pid(202)
        self.assertEqual(raised.exception.code, "test_app_not_portable")


if __name__ == "__main__":
    unittest.main()
