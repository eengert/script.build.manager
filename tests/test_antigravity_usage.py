"""Tests for tools/antigravity-usage.

All codexbar interaction is mocked. No live CodexBar calls, no real quota
consumed, and no network or credentials accessed.
"""

import importlib.util
import json
import os
import subprocess
import unittest
from importlib.machinery import SourceFileLoader
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(REPO_ROOT, "tools", "antigravity-usage")

_loader = SourceFileLoader("antigravity_usage", SCRIPT_PATH)
_spec = importlib.util.spec_from_loader("antigravity_usage", _loader)
antigravity_usage = importlib.util.module_from_spec(_spec)
_loader.exec_module(antigravity_usage)


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=antigravity_usage.CODEXBAR_CMD,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


SAMPLE_ANTIGRAVITY_OUTPUT = [
    {
        "account": "user@example.com",
        "provider": "antigravity",
        "source": "app",
        "usage": {
            "accountEmail": "user@example.com",
            "loginMethod": "Antigravity Starter Quota",
            "extraRateWindows": [
                {
                    "id": "antigravity-quota-summary-gemini-weekly",
                    "title": "Gemini weekly",
                    "window": {
                        "resetDescription": "Reset in 6 days",
                        "resetsAt": "2026-09-26T16:30:07Z",
                        "usedPercent": 32.5332,
                        "windowMinutes": 10080,
                    },
                },
                {
                    "id": "antigravity-quota-summary-3p-weekly",
                    "title": "Claude/GPT weekly",
                    "window": {
                        "resetDescription": "Reset in 6 days 23 hours",
                        "resetsAt": "2026-09-27T01:26:13Z",
                        "usedPercent": 25.4204,
                        "windowMinutes": 10080,
                    },
                },
            ],
            "identity": {
                "accountEmail": "user@example.com",
                "loginMethod": "Antigravity Starter Quota",
                "providerID": "antigravity",
            },
            "primary": {
                "resetDescription": "Reset in 6 days",
                "resetsAt": "2026-09-26T16:30:07Z",
                "usedPercent": 32.5332,
                "windowMinutes": 10080,
            },
            "secondary": {
                "resetDescription": "Reset in 6 days 23 hours",
                "resetsAt": "2026-09-27T01:26:13Z",
                "usedPercent": 25.4204,
                "windowMinutes": 10080,
            },
            "updatedAt": "2026-09-20T01:38:21Z",
        },
    }
]


class AntigravityUsageTests(unittest.TestCase):

    def _run_with(self, data_json):
        with mock.patch.object(
            antigravity_usage.subprocess,
            "run",
            return_value=_completed(stdout=data_json),
        ):
            return antigravity_usage.get_normalized_usage()

    def test_successful_parsing_with_named_pools(self):
        result = self._run_with(json.dumps(SAMPLE_ANTIGRAVITY_OUTPUT))
        self.assertTrue(result["available"])
        self.assertEqual(result["provider"], "antigravity")
        self.assertEqual(result["source"], "app")
        self.assertEqual(result["account"], "user@example.com")
        self.assertEqual(result["login_method"], "Antigravity Starter Quota")
        self.assertEqual(len(result["windows"]), 2)

    def test_gemini_and_claude_pools_remain_separate(self):
        result = self._run_with(json.dumps(SAMPLE_ANTIGRAVITY_OUTPUT))
        self.assertIn("Gemini weekly", result["pools"])
        self.assertIn("Claude/GPT weekly", result["pools"])

        gemini = result["pools"]["Gemini weekly"]
        claude = result["pools"]["Claude/GPT weekly"]

        self.assertEqual(gemini["used_percent"], 32.5332)
        self.assertEqual(claude["used_percent"], 25.4204)
        self.assertNotEqual(gemini["used_percent"], claude["used_percent"])

    def test_remaining_percentage_calculation(self):
        result = self._run_with(json.dumps(SAMPLE_ANTIGRAVITY_OUTPUT))
        gemini = result["pools"]["Gemini weekly"]
        claude = result["pools"]["Claude/GPT weekly"]

        self.assertEqual(gemini["remaining_percent"], round(100.0 - 32.5332, 4))
        self.assertEqual(claude["remaining_percent"], round(100.0 - 25.4204, 4))

    def test_fallback_to_primary_secondary_if_extra_windows_missing(self):
        data = [
            {
                "provider": "antigravity",
                "source": "cli",
                "usage": {
                    "primary": {
                        "usedPercent": 50.0,
                        "windowMinutes": 10080,
                        "resetsAt": "2026-09-26T00:00:00Z",
                    },
                    "secondary": {
                        "usedPercent": 10.0,
                        "windowMinutes": 10080,
                        "resetsAt": "2026-09-27T00:00:00Z",
                    },
                },
            }
        ]
        result = self._run_with(json.dumps(data))
        self.assertTrue(result["available"])
        self.assertEqual(len(result["windows"]), 2)
        self.assertIn("primary", result["pools"])
        self.assertIn("secondary", result["pools"])
        self.assertEqual(result["pools"]["primary"]["remaining_percent"], 50.0)
        self.assertEqual(result["pools"]["secondary"]["remaining_percent"], 90.0)

    def test_malformed_json_returns_unavailable(self):
        result = self._run_with("Not JSON {broken")
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "codexbar returned malformed JSON")

    def test_command_exit_failure_returns_sanitized_reason(self):
        with mock.patch.object(
            antigravity_usage.subprocess,
            "run",
            return_value=_completed(stderr="secret token leak 12345", returncode=1),
        ):
            result = antigravity_usage.get_normalized_usage()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "codexbar exited with status 1")
        # Ensure stderr is not leaked in the reason
        self.assertNotIn("secret", result["reason"])

    def test_command_not_found_returns_sanitized_reason(self):
        with mock.patch.object(
            antigravity_usage.subprocess,
            "run",
            side_effect=FileNotFoundError("binary missing"),
        ):
            result = antigravity_usage.get_normalized_usage()
        self.assertFalse(result["available"])
        self.assertIn("not found", result["reason"])

    def test_command_timeout_returns_unavailable(self):
        with mock.patch.object(
            antigravity_usage.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="codexbar", timeout=15),
        ):
            result = antigravity_usage.get_normalized_usage()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "codexbar timed out")

    def test_missing_antigravity_record(self):
        other_provider = [{"provider": "codex", "usage": {}}]
        result = self._run_with(json.dumps(other_provider))
        self.assertFalse(result["available"])
        self.assertEqual(
            result["reason"], "no antigravity provider record in codexbar output"
        )

    def test_missing_usage_section(self):
        record = [{"provider": "antigravity"}]
        result = self._run_with(json.dumps(record))
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "codexbar record missing usage section")

    def test_human_format_output(self):
        result = antigravity_usage._normalize(json.dumps(SAMPLE_ANTIGRAVITY_OUTPUT))
        formatted = antigravity_usage._format_human(result)
        self.assertIn("Antigravity usage (CodexBar)", formatted)
        self.assertIn("Gemini weekly: 32.5332% used / 67.4668% remaining", formatted)
        self.assertIn("Claude/GPT weekly: 25.4204% used / 74.5796% remaining", formatted)
        self.assertIn("Source: app", formatted)


if __name__ == "__main__":
    unittest.main()
