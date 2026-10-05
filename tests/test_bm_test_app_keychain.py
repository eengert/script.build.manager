"""Offline tests for tools/bm_test_app_keychain.py.

No test queries the real Keychain: every ``security`` interaction goes through an
injected fake runner, and a conspicuous sentinel stands in for the secret. The
filesystem tripwire from the helper tests stays armed, so nothing here can touch
the real Test.app, the normal Kodi application, or the normal Kodi profile.
"""

from __future__ import annotations

import ast
import base64
import contextlib
import dataclasses
import getpass
import inspect
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests import test_bm_test_app as helper_tests
from tools import bm_test_app as bm
from tools import bm_test_app_keychain as kc

PROJECT = Path(__file__).resolve().parents[1]
WRAPPER_PATH = PROJECT / "tools" / "bm_test_app_keychain.py"
WRAPPER_SOURCE = WRAPPER_PATH.read_text(encoding="utf-8")
WRAPPER_TREE = ast.parse(WRAPPER_SOURCE)

SENTINEL = "SENTINEL-KEYCHAIN-SECRET-DoNotLeak-5521"
STDERR_SENTINEL = "SENTINEL-SECURITY-STDERR-9917"
EXPECTED_ARGV = [
    "/usr/bin/security", "find-generic-password",
    "-a", "kodi", "-s", "ai-supervisor.test-app-kodi", "-w",
]


def item_bytes(text=SENTINEL, newline=True):
    return (text + ("\n" if newline else "")).encode("utf-8")


class FakeRunner:
    """subprocess.run stand-in that records every call and never spawns anything."""

    def __init__(self, *, returncode=0, stdout=b"", stderr=b"", raises=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr=self.stderr)


def failing_runners():
    """Every way the lookup can fail, each carrying the sentinel where it could."""
    argv = EXPECTED_ARGV
    leaky_timeout = subprocess.TimeoutExpired(argv, 15, output=item_bytes(), stderr=STDERR_SENTINEL.encode())
    return {
        "exit 44 (item not found)": (FakeRunner(returncode=44, stderr=STDERR_SENTINEL.encode()), "credential_missing"),
        "exit 1 with secret-looking stdout": (FakeRunner(returncode=1, stdout=item_bytes()), "credential_missing"),
        "exit 36 with stderr text": (FakeRunner(returncode=36, stderr=STDERR_SENTINEL.encode()), "credential_missing"),
        "empty output": (FakeRunner(stdout=b""), "credential_missing"),
        "newline only": (FakeRunner(stdout=b"\n"), "credential_missing"),
        "whitespace only": (FakeRunner(stdout=b"   \n"), "credential_missing"),
        "invalid utf-8": (FakeRunner(stdout=b"\xff\xfe" + SENTINEL.encode() + b"\n"), "credential_missing"),
        "embedded newline": (FakeRunner(stdout=b"first-line\n" + SENTINEL.encode() + b"\n"), "credential_missing"),
        "embedded carriage return": (FakeRunner(stdout=SENTINEL.encode() + b"\r\n"), "credential_missing"),
        "embedded NUL": (FakeRunner(stdout=SENTINEL.encode() + b"\x00x\n"), "credential_missing"),
        "unreasonably long text": (FakeRunner(stdout=b"A" * (kc.MAX_SECRET_CHARS + 1) + b"\n"), "credential_missing"),
        "unreasonably large output": (FakeRunner(stdout=b"A" * (kc.MAX_OUTPUT_BYTES + 1)), "credential_missing"),
        "non-bytes output": (FakeRunner(stdout=SENTINEL), "credential_missing"),
        "timeout": (FakeRunner(raises=leaky_timeout), "credential_prompt_unavailable"),
        "binary missing": (FakeRunner(raises=FileNotFoundError(2, SENTINEL)), "credential_prompt_unavailable"),
        "permission denied": (FakeRunner(raises=PermissionError(13, SENTINEL)), "credential_prompt_unavailable"),
        "generic OSError": (FakeRunner(raises=OSError(5, SENTINEL)), "credential_prompt_unavailable"),
        "generic SubprocessError": (FakeRunner(raises=subprocess.SubprocessError(SENTINEL)), "credential_prompt_unavailable"),
    }


def frames_below(exc):
    """Traceback frames deeper than the frame that caught the exception."""
    tb = exc.__traceback__
    tb = tb.tb_next if tb is not None else None
    while tb is not None:
        yield tb.tb_frame
        tb = tb.tb_next


def contains_sentinel(value):
    if isinstance(value, (bytes, bytearray)):
        return SENTINEL.encode() in bytes(value)
    return isinstance(value, str) and SENTINEL in value


class TestKeychainLookup(helper_tests.TripwireTestCase):
    def prompt(self, runner):
        return kc.make_keychain_password_prompt(runner)

    def only_call(self, runner):
        self.assertEqual(len(runner.calls), 1)
        return runner.calls[0]

    # -- required properties 1-5 ------------------------------------------------

    def test_1_exact_security_executable_and_exact_argv(self):
        runner = FakeRunner(stdout=item_bytes())
        self.prompt(runner)("ignored prompt")
        argv, _ = self.only_call(runner)
        self.assertIsInstance(argv, list)
        self.assertEqual(argv, EXPECTED_ARGV)
        self.assertTrue(all(isinstance(item, str) for item in argv))
        self.assertEqual((kc.SECURITY_BIN, kc.KEYCHAIN_SERVICE, kc.KEYCHAIN_ACCOUNT),
                         ("/usr/bin/security", "ai-supervisor.test-app-kodi", "kodi"))
        for banned in ("-g", "dump-keychain", "find-internet-password", "list-keychains", "-D", "-j"):
            self.assertNotIn(banned, argv)

    def test_2_shell_is_false(self):
        runner = FakeRunner(stdout=item_bytes())
        self.prompt(runner)("p")
        _, kwargs = self.only_call(runner)
        self.assertIs(kwargs["shell"], False)

    def test_3_stdin_is_not_inherited_and_the_call_is_bounded(self):
        runner = FakeRunner(stdout=item_bytes())
        self.prompt(runner)("p")
        _, kwargs = self.only_call(runner)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)  # never captured, never echoed
        self.assertIs(kwargs["check"], False)
        self.assertTrue(0 < kwargs["timeout"] <= 30)
        for forbidden in ("input", "text", "universal_newlines", "capture_output", "cwd", "preexec_fn"):
            self.assertNotIn(forbidden, kwargs)

    def test_environment_is_fixed_and_minimal_not_inherited(self):
        runner = FakeRunner(stdout=item_bytes())
        with mock.patch.dict(os.environ, {"BM_LEAK_CANARY": "canary", "KEYCHAIN_SERVICE": "evil", "PATH": "/evil/bin"}):
            self.prompt(runner)("p")
        _, kwargs = self.only_call(runner)
        self.assertEqual(set(kwargs["env"]), {"PATH", "HOME"})
        self.assertEqual(kwargs["env"]["PATH"], "/usr/bin:/bin")
        self.assertTrue(os.path.isabs(kwargs["env"]["HOME"]))
        self.assertNotIn("canary", json.dumps(kwargs["env"]))

    def test_4_successful_lookup_supplies_the_secret_only_through_the_callback(self):
        runner = FakeRunner(stdout=item_bytes())
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            value = self.prompt(runner)("a prompt that must be ignored")
        self.assertEqual(value, SENTINEL)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertEqual(len(runner.calls), 1)
        self.assertNotIn(SENTINEL, repr(runner.calls))  # call arguments carry no secret
        self.assertFalse([k for k, v in vars(kc).items() if contains_sentinel(v)])  # no module-level cache

    def test_only_one_trailing_newline_is_removed_and_nothing_else_is_trimmed(self):
        for stdout, expected in (
            (b"  pass word  \n", "  pass word  "),
            (b"no-newline-at-all", "no-newline-at-all"),
            (b"trailing-space \n", "trailing-space "),
            ("pässwörd-€\n".encode("utf-8"), "pässwörd-€"),
        ):
            with self.subTest(stdout=stdout[:6]):
                self.assertEqual(self.prompt(FakeRunner(stdout=stdout))("p"), expected)

    def test_5_service_and_account_are_fixed_constants_not_caller_controlled(self):
        for function in (kc.fetch_keychain_password, kc.make_keychain_password_prompt):
            self.assertEqual(list(inspect.signature(function).parameters), ["runner"])
        self.assertEqual(list(inspect.signature(kc.main).parameters), ["argv", "runner"])
        self.assertEqual(kc.LOOKUP_ARGV, tuple(EXPECTED_ARGV))
        hostile = {
            "KEYCHAIN_SERVICE": "evil.service", "KEYCHAIN_ACCOUNT": "evil", "BM_KEYCHAIN_SERVICE": "evil",
            "SECURITY_BIN": "/tmp/evil-security", "SERVICE": "evil", "ACCOUNT": "evil",
        }
        runner = FakeRunner(stdout=item_bytes())
        with mock.patch.dict(os.environ, hostile), mock.patch.object(sys, "argv", ["wrapper", "--service", "evil"]):
            self.prompt(runner)("service=evil account=evil -s evil -a evil")
        self.assertEqual(self.only_call(runner)[0], EXPECTED_ARGV)

    # -- required properties 6-10 (every failure is closed, fixed and silent) -----

    def test_6_to_10_every_failure_is_closed_with_a_fixed_code_and_leaks_nothing(self):
        for label, (runner, expected_code) in failing_runners().items():
            with self.subTest(label=label):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    with self.assertRaises(bm.HelperError) as raised:
                        self.prompt(runner)("p")
                error = raised.exception
                self.assertEqual(error.code, expected_code)
                self.assertEqual(error.detail, {})
                self.assertEqual(len(runner.calls), 1)
                self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
                payload = bm.canonical_json(bm._error_payload("run", error))
                for text in (payload, str(error), repr(error), repr(error.args), repr(error.detail)):
                    self.assertNotIn(SENTINEL, text)
                    self.assertNotIn(STDERR_SENTINEL, text)
                # nothing chained: neither the process output nor a TimeoutExpired is reachable
                self.assertIsNone(error.__cause__)
                self.assertIsNone(error.__context__)
                for frame in frames_below(error):
                    self.assertFalse([n for n, v in frame.f_locals.items() if contains_sentinel(v)], label)

    def test_a_missing_passwd_entry_fails_closed_before_any_lookup(self):
        runner = FakeRunner(stdout=item_bytes())
        with mock.patch.object(kc.pwd, "getpwuid", side_effect=KeyError("uid")):
            with self.assertRaises(bm.HelperError) as raised:
                self.prompt(runner)("p")
        self.assertEqual(raised.exception.code, "credential_prompt_unavailable")
        self.assertEqual(runner.calls, [])

    # -- required property 14: no interactive fallback -----------------------------

    def test_14_no_automatic_interactive_fallback(self):
        class ExplodingStdin:
            def __getattr__(self, name):
                raise AssertionError("stdin must never be touched")

        with mock.patch.object(bm, "interactive_password_prompt", side_effect=AssertionError("tty fallback")) as tty, \
                mock.patch.object(getpass, "getpass", side_effect=AssertionError("getpass fallback")), \
                mock.patch("builtins.input", side_effect=AssertionError("input fallback")), \
                mock.patch.object(sys, "stdin", ExplodingStdin()):
            for label, (runner, expected_code) in failing_runners().items():
                with self.subTest(label=label), self.assertRaises(bm.HelperError) as raised:
                    self.prompt(runner)("p")
                self.assertEqual(raised.exception.code, expected_code)
        tty.assert_not_called()
        services = dataclasses.replace(bm.Services.production(), password_prompt=self.prompt(FakeRunner(returncode=44)))
        self.assertIsNot(services.password_prompt, bm.interactive_password_prompt)


class TestWrapperMain(helper_tests.TripwireTestCase):
    def test_11_helper_argv_passes_through_unchanged(self):
        argv = ["run", "status", "--manifest", "/x/stage_manifest.json", "--rpc-port", "8080", "--output", "/x/out.json"]
        with mock.patch.object(kc.bm, "main", return_value=0) as helper_main:
            kc.main(list(argv))
        (passed,), kwargs = helper_main.call_args
        self.assertEqual(list(passed), argv)
        self.assertEqual(set(kwargs), {"services"})
        with mock.patch.object(kc.bm, "main", return_value=0) as helper_main, \
                mock.patch.object(sys, "argv", ["wrapper", "snapshot", "--no-git-binding"]):
            kc.main()
        self.assertEqual(list(helper_main.call_args.args[0]), ["snapshot", "--no-git-binding"])

    def test_12_helper_exit_code_is_preserved(self):
        for code in (bm.EXIT_OK, bm.EXIT_FAILED, bm.EXIT_USAGE, bm.EXIT_ADAPTER_FAILED, bm.EXIT_INTERRUPTED):
            with self.subTest(code=code), mock.patch.object(kc.bm, "main", return_value=code):
                self.assertEqual(kc.main(["identify"]), code)

    def test_13_only_services_password_prompt_is_replaced(self):
        original = helper_tests.make_services(helper_tests.make_fake_app(self.tmp))
        with mock.patch.object(kc.bm.Services, "production", return_value=original), \
                mock.patch.object(kc.bm, "main", return_value=0) as helper_main:
            kc.main(["identify"], runner=FakeRunner(stdout=item_bytes()))
        passed = helper_main.call_args.kwargs["services"]
        self.assertIs(type(passed), bm.Services)
        for field in dataclasses.fields(bm.Services):
            if field.name == "password_prompt":
                self.assertIsNot(passed.password_prompt, original.password_prompt)
            else:
                self.assertIs(getattr(passed, field.name), getattr(original, field.name), field.name)
        self.assertEqual(passed.password_prompt("p"), SENTINEL)

    def test_the_real_production_services_get_only_a_new_prompt(self):
        with mock.patch.object(kc.bm, "main", return_value=0) as helper_main:
            kc.main(["identify"])
        passed = helper_main.call_args.kwargs["services"]
        reference = bm.Services.production()
        self.assertIsNot(passed.password_prompt, reference.password_prompt)
        self.assertIs(reference.password_prompt, bm.interactive_password_prompt)
        for field in dataclasses.fields(bm.Services):
            if field.name not in ("password_prompt",):
                self.assertIs(type(getattr(passed, field.name)), type(getattr(reference, field.name)), field.name)
        self.assertEqual(passed.target, reference.target)

    def test_an_unknown_option_cannot_redirect_the_keychain_item(self):
        runner = FakeRunner(stdout=item_bytes())
        services = helper_tests.make_services(helper_tests.make_fake_app(self.tmp))
        with mock.patch.object(kc.bm.Services, "production", return_value=services):
            code = kc.main(["identify", "--service", "evil", "--account", "evil"], runner=runner)
        payload = json.loads(services.stdout.getvalue())
        self.assertEqual(code, bm.EXIT_USAGE)
        self.assertEqual(payload["error"]["code"], "argument_invalid")
        self.assertEqual(runner.calls, [])

    def test_the_script_entry_point_propagates_the_helper_exit_code(self):
        # An argument error exits inside the reviewed helper before any Keychain or
        # Kodi contact, so this is a true end-to-end run of the script itself.
        proc = subprocess.run(
            [sys.executable, "-B", str(WRAPPER_PATH), "identify", "--no-such-option"],
            capture_output=True, cwd=self.tmp, timeout=60, check=False,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(proc.returncode, bm.EXIT_USAGE)
        self.assertEqual(proc.stderr, b"")
        payload = json.loads(proc.stdout)
        self.assertEqual((payload["ok"], payload["error"]["code"]), (False, "argument_invalid"))


class TestKeychainThroughTheReviewedRpcClient(helper_tests.TripwireTestCase):
    """The secret reaches only the reviewed client; the reviewed protections still apply."""

    def setUp(self):
        super().setUp()
        self.transport = helper_tests.FakeTransport()
        self.transport.password = SENTINEL
        self.runner = FakeRunner(stdout=item_bytes())
        self.services = helper_tests.make_services(
            helper_tests.make_fake_app(self.tmp),
            transport=self.transport,
            listener_lookup=lambda port: {4242},
            password_prompt=kc.make_keychain_password_prompt(self.runner),
        )

    def client(self):
        return bm.RpcClient(self.services, 4242, "127.0.0.1", 8080, "kodi")

    def test_correct_password_authenticates_and_is_registered_with_the_leak_guard(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            client = self.client()
            self.assertEqual(client.call("JSONRPC.Ping", {}), "pong")
        self.assertTrue(client.authenticated)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        sent = self.transport.requests[-1]["headers"]["Authorization"]
        self.assertEqual(base64.b64decode(sent.split()[1]).decode(), f"kodi:{SENTINEL}")
        self.assertTrue(self.services.secrets.leaks("prefix " + SENTINEL))
        self.assertTrue(self.services.secrets.leaks(sent))
        for request in self.transport.requests:
            self.assertNotIn(SENTINEL, json.dumps(request["body"]))

    def test_a_stale_keychain_password_still_surfaces_as_rpc_auth_failed(self):
        self.transport.password = "a-different-current-kodi-password"
        with self.assertRaises(bm.HelperError) as raised:
            self.client().call("JSONRPC.Ping", {})
        self.assertEqual(raised.exception.code, "rpc_auth_failed")  # the distinction is not masked
        self.assertNotIn(SENTINEL, bm.canonical_json(bm._error_payload("run", raised.exception)))

    def test_a_failed_lookup_surfaces_a_credential_code_and_never_prompts(self):
        for label, (runner, expected_code) in failing_runners().items():
            with self.subTest(label=label):
                services = dataclasses.replace(self.services, password_prompt=kc.make_keychain_password_prompt(runner))
                with mock.patch.object(bm, "interactive_password_prompt", side_effect=AssertionError("fallback")):
                    with self.assertRaises(bm.HelperError) as raised:
                        bm.RpcClient(services, 4242, "127.0.0.1", 8080, "kodi").call("JSONRPC.Ping", {})
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn(SENTINEL, bm.canonical_json(bm._error_payload("run", raised.exception)))

    def test_16_the_sentinel_never_appears_in_any_captured_output(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.client().call("JSONRPC.Ping", {})
            for runner, _ in failing_runners().values():
                with contextlib.suppress(bm.HelperError):
                    kc.make_keychain_password_prompt(runner)("p")
        self.assertNotIn(SENTINEL, out.getvalue() + err.getvalue())
        self.assertNotIn(STDERR_SENTINEL, out.getvalue() + err.getvalue())


class TestWrapperStaticSafety(unittest.TestCase):
    @staticmethod
    def dotted(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    def test_15_no_environment_cli_stdin_or_prompt_password_mechanism(self):
        banned_attributes = {
            "os.environ", "os.getenv", "os.putenv", "os.system", "os.popen", "os.execv", "os.spawnv",
            "getpass.getpass", "sys.stdin", "sys.stdin.read", "sys.stdin.readline",
        }
        banned_names = {"input", "eval", "exec", "compile", "__import__", "breakpoint", "getpass", "argparse", "environ"}
        for node in ast.walk(WRAPPER_TREE):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(self.dotted(node), banned_attributes)
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, banned_names)
        imported = set()
        for node in ast.walk(WRAPPER_TREE):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported - {"__future__", "dataclasses", "os", "pwd", "subprocess", "sys", "pathlib", "typing", "tools"}, set())
        for text in ("/dev/tty", "interactive_password_prompt", "dump-keychain", "shell=True", "--password", "--keychain",
                     "add-generic-password", "delete-generic-password", "find-internet-password", "list-keychains"):
            self.assertNotIn(text, WRAPPER_SOURCE)
        self.assertNotIn("-g", kc.LOOKUP_ARGV)

    def test_constants_are_exact_literals_defined_once(self):
        self.assertEqual(WRAPPER_SOURCE.count('"/usr/bin/security"'), 1)
        self.assertEqual(WRAPPER_SOURCE.count('"ai-supervisor.test-app-kodi"'), 1)
        self.assertEqual(WRAPPER_SOURCE.count('KEYCHAIN_ACCOUNT = "kodi"'), 1)
        self.assertEqual(WRAPPER_SOURCE.count('"find-generic-password"'), 1)

    def test_the_only_process_invocation_is_the_bounded_runner_call(self):
        calls = [n for n in ast.walk(WRAPPER_TREE) if isinstance(n, ast.Call) and self.dotted(n.func) == "runner"]
        self.assertEqual(len(calls), 1)
        keywords = {kw.arg: kw.value for kw in calls[0].keywords}
        self.assertEqual(set(keywords), {"stdin", "stdout", "stderr", "env", "timeout", "check", "shell"})
        self.assertIs(keywords["shell"].value, False)
        self.assertIs(keywords["check"].value, False)
        self.assertEqual(self.dotted(keywords["stdin"]), "subprocess.DEVNULL")
        self.assertEqual(self.dotted(keywords["stderr"]), "subprocess.DEVNULL")
        self.assertEqual(self.dotted(keywords["stdout"]), "subprocess.PIPE")
        for node in ast.walk(WRAPPER_TREE):
            if isinstance(node, ast.Call) and self.dotted(node.func).startswith("subprocess."):
                self.fail("subprocess must only be reached through the injected runner")

    def test_module_has_no_import_time_side_effects(self):
        allowed = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign, ast.If)
        for node in WRAPPER_TREE.body:
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)  # the docstring only
                continue
            self.assertIsInstance(node, allowed, ast.dump(node)[:60])
            if isinstance(node, ast.If):
                self.assertIn(ast.unparse(node.test), ("str(PROJECT) not in sys.path", "__name__ == '__main__'"))

    def test_the_wrapper_is_host_side_tooling_never_staged_into_kodi(self):
        relative = WRAPPER_PATH.relative_to(PROJECT).as_posix()
        self.assertEqual(relative, "tools/bm_test_app_keychain.py")
        self.assertNotIn(relative, bm.BUILDER_REQUIRED)
        self.assertNotIn(relative, bm.DRIVER_SOURCE_PATHS.values())
        self.assertFalse(relative.startswith(tuple(bm.PRODUCT_TREE_DIRS)))
        self.assertNotIn(WRAPPER_PATH.name, bm.PRODUCT_ROOT_FILES)


# --- END OF TESTS ---

if __name__ == "__main__":
    unittest.main()
