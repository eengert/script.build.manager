"""Tests for BM-019 typed restart-requirement aggregation."""

import json
import unittest

from resources.lib.config import (
    ConfigApplyResult,
    ConfigOperationKind,
    ConfigOperationResult,
    ConfigOperationStatus,
)
from resources.lib.addons import AddonInstallResult, AddonStatus
from resources.lib.skin import SkinResult, SkinStatus
from resources.lib.restart import (
    RestartAggregator,
    RestartObservation,
    RestartReport,
    RestartRequirement,
    aggregate_restart_reports,
    aggregate_restart_requirements,
)


def _observation(
    requirement=RestartRequirement.NONE,
    *,
    changed=False,
    succeeded=True,
):
    return RestartObservation(
        requirement=requirement,
        changed=changed,
        succeeded=succeeded,
        operation="test-operation",
    )


class TestRestartRequirement(unittest.TestCase):
    def test_typed_values_are_stable(self):
        self.assertEqual(RestartRequirement.NONE.value, "none")
        self.assertEqual(RestartRequirement.KODI_RESTART.value, "kodi_restart")

    def test_no_actions_report_none(self):
        report = aggregate_restart_requirements(())
        self.assertEqual(report, RestartReport())
        self.assertFalse(report.requires_restart)

    def test_successful_changed_action_requires_restart(self):
        report = aggregate_restart_requirements((
            _observation(
                RestartRequirement.KODI_RESTART,
                changed=True,
            ),
        ))
        self.assertEqual(report.requirement, RestartRequirement.KODI_RESTART)
        self.assertEqual(report.successful_changes, 1)

    def test_mixed_requirements_keep_strongest(self):
        report = aggregate_restart_requirements((
            _observation(RestartRequirement.NONE, changed=True),
            _observation(RestartRequirement.KODI_RESTART, changed=True),
        ))
        self.assertEqual(report.requirement, RestartRequirement.KODI_RESTART)
        self.assertEqual(report.successful_changes, 2)

    def test_later_none_cannot_downgrade_restart(self):
        aggregator = RestartAggregator()
        aggregator.record(_observation(
            RestartRequirement.KODI_RESTART,
            changed=True,
        ))
        aggregator.record(_observation(RestartRequirement.NONE, changed=True))
        self.assertEqual(
            aggregator.report().requirement,
            RestartRequirement.KODI_RESTART,
        )

    def test_idempotent_action_does_not_create_requirement(self):
        report = aggregate_restart_requirements((
            _observation(RestartRequirement.KODI_RESTART, changed=False),
        ))
        self.assertEqual(report.requirement, RestartRequirement.NONE)
        self.assertEqual(report.successful_changes, 0)

    def test_failure_after_success_preserves_requirement(self):
        report = aggregate_restart_requirements((
            _observation(RestartRequirement.KODI_RESTART, changed=True),
            _observation(
                RestartRequirement.KODI_RESTART,
                changed=True,
                succeeded=False,
            ),
        ))
        self.assertEqual(report.requirement, RestartRequirement.KODI_RESTART)
        self.assertEqual(report.successful_changes, 1)
        self.assertEqual(report.failed_operations, 1)

    def test_failed_uncommitted_action_does_not_add_requirement(self):
        report = aggregate_restart_requirements((
            _observation(
                RestartRequirement.KODI_RESTART,
                changed=True,
                succeeded=False,
            ),
        ))
        self.assertEqual(report.requirement, RestartRequirement.NONE)
        self.assertEqual(report.failed_operations, 1)

    def test_nested_reports_are_monotonic(self):
        report = aggregate_restart_reports((
            RestartReport(RestartRequirement.KODI_RESTART, 1, 0),
            RestartReport(RestartRequirement.NONE, 0, 1),
        ))
        self.assertEqual(report.requirement, RestartRequirement.KODI_RESTART)
        self.assertEqual(report.successful_changes, 1)
        self.assertEqual(report.failed_operations, 1)

    def test_serialization_preserves_typed_requirement(self):
        report = RestartReport(RestartRequirement.KODI_RESTART, 2, 1)
        encoded = json.dumps(report.to_dict(), sort_keys=True)
        self.assertIn('"requirement": "kodi_restart"', encoded)
        self.assertTrue(report.to_dict()["requires_restart"])

    def test_config_result_exposes_restart_report(self):
        operation = ConfigOperationResult(
            kind=ConfigOperationKind.SETTING,
            package_id="test",
            status=ConfigOperationStatus.UPDATED,
            expected_identity="sha256:expected",
            previous_identity="sha256:previous",
            detail="updated",
            addon_id="plugin.video.test",
            key="Setting",
            restart_requirement=RestartRequirement.KODI_RESTART,
        )
        result = ConfigApplyResult(results=(operation,))
        self.assertEqual(
            result.restart_requirement,
            RestartRequirement.KODI_RESTART,
        )
        self.assertEqual(result.restart_report.successful_changes, 1)

    def test_failed_config_result_does_not_add_restart_requirement(self):
        operation = ConfigOperationResult(
            kind=ConfigOperationKind.SETTING,
            package_id="test",
            status=ConfigOperationStatus.FAILED,
            expected_identity="sha256:expected",
            previous_identity="sha256:previous",
            detail="failed",
            addon_id="plugin.video.test",
            key="Setting",
            restart_requirement=RestartRequirement.KODI_RESTART,
        )
        result = ConfigApplyResult(results=(operation,))
        self.assertEqual(result.restart_requirement, RestartRequirement.NONE)
        self.assertEqual(result.restart_report.failed_operations, 1)

    def test_current_bm018_paths_do_not_request_restart(self):
        addon_result = AddonInstallResult(
            "skin.arctic.fuse.3",
            AddonStatus.INSTALLED,
            "enabled",
            True,
            "3.2.19",
            "installed",
        )
        skin_result = SkinResult(
            "skin.arctic.fuse.3",
            SkinStatus.ACTIVATED,
            "skin.arctic.fuse.3",
            "activated",
        )
        config_result = ConfigApplyResult()
        self.assertEqual(addon_result.restart_report.requirement, RestartRequirement.NONE)
        self.assertEqual(skin_result.restart_report.requirement, RestartRequirement.NONE)
        self.assertEqual(config_result.restart_requirement, RestartRequirement.NONE)


if __name__ == "__main__":
    unittest.main()
