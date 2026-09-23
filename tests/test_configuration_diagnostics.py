"""Secret-safe action diagnostics for frozen CONFIGURE failures."""

import json
import unittest
from enum import Enum
from types import SimpleNamespace

from resources.lib.build_manager import (
    ActionExecutionResult,
    ActionFailureDiagnostic,
    ReconcileFailure,
    ReconcilePhase,
    ReconcileResult,
    _action_failure_diagnostic,
)
from resources.lib.frozen_install import FrozenInstallCoordinator, FrozenInstallError
from resources.lib.planner import CONFIGURE, PlanAction
from resources.lib.private_resource import (
    ResourceInitializationCause,
    ResourceInitializationStage,
    StructuredResourceInitializationError,
)
from resources.lib.restart import RestartReport


FAKE_SECRET = "BM017F_FAKE_EXCEPTION_SECRET_8342"


class _EnumActionKind(Enum):
    CONFIGURE = "configure"


class ConfigurationDiagnosticsTest(unittest.TestCase):
    def _frozen_failure(
        self,
        action_kind,
        *,
        cause_code="RESOURCE_NOT_INITIALIZED",
        initialization_stage="",
        last_completed_stage="",
    ):
        diagnostic = ActionFailureDiagnostic(
            "PRIVATE_RESOURCE_INITIALIZATION_FAILED",
            "plugin.video.redlight",
            "redlight.settings",
            cause_code,
            initialization_stage,
            last_completed_stage,
        )
        action_result = SimpleNamespace(
            action=SimpleNamespace(kind=action_kind, addon_id=""),
            succeeded=False,
            owner_result=diagnostic,
        )
        reconcile = SimpleNamespace(
            failure=ReconcileFailure(
                ReconcilePhase.EXECUTE, "ACTION_FAILED", FAKE_SECRET
            ),
            action_results=(action_result,),
        )
        result = SimpleNamespace(
            outcome="failed",
            failure=None,
            reconcile_result=reconcile,
            private_overlay=None,
        )
        coordinator = object.__new__(FrozenInstallCoordinator)
        transaction = SimpleNamespace(
            activation_hold_ids=("plugin.video.redlight",),
            lifecycle_restart_count=0,
        )
        with self.assertRaises(FrozenInstallError) as caught:
            coordinator._handle_configuration_result(transaction, result)
        return caught.exception

    def test_uppercase_configure_and_enum_values_are_normalized(self):
        for kind in (CONFIGURE, "configure", _EnumActionKind.CONFIGURE):
            with self.subTest(kind=kind):
                error = self._frozen_failure(kind)
                self.assertIn("action=CONFIGURE", error.safe_detail)

    def test_owner_resource_and_typed_failure_are_retained_without_exception_text(self):
        error = self._frozen_failure("configure")
        self.assertEqual(error.code, "FROZEN_CONFIGURATION_ACTION_FAILED")
        self.assertIn("owner=plugin.video.redlight", error.safe_detail)
        self.assertIn("resource=redlight.settings", error.safe_detail)
        self.assertIn(
            "resource_failure=PRIVATE_RESOURCE_INITIALIZATION_FAILED",
            error.safe_detail,
        )
        self.assertIn("cause=RESOURCE_NOT_INITIALIZED", error.safe_detail)
        self.assertNotIn(FAKE_SECRET, error.safe_detail)

    def test_stage_and_typed_cause_survive_configure_diagnostic(self):
        error = self._frozen_failure(
            "configure",
            cause_code=ResourceInitializationCause.DATABASE_OPEN_FAILED.value,
            initialization_stage=ResourceInitializationStage.OPEN_SETTINGS_DATABASE.value,
            last_completed_stage=ResourceInitializationStage.CREATE_DATABASE_DIRECTORY.value,
        )
        self.assertIn(
            "resource_failure=PRIVATE_RESOURCE_INITIALIZATION_FAILED",
            error.safe_detail,
        )
        self.assertIn("action=CONFIGURE", error.safe_detail)
        self.assertIn("owner=plugin.video.redlight", error.safe_detail)
        self.assertIn("resource=redlight.settings", error.safe_detail)
        self.assertIn("cause=DATABASE_OPEN_FAILED", error.safe_detail)
        self.assertIn(
            "initialization_stage=OPEN_SETTINGS_DATABASE", error.safe_detail
        )
        self.assertIn(
            "last_completed_stage=CREATE_DATABASE_DIRECTORY", error.safe_detail
        )
        self.assertNotIn(FAKE_SECRET, error.safe_detail)

    def test_action_diagnostic_extracts_typed_stage_metadata(self):
        error = StructuredResourceInitializationError(
            "plugin.video.redlight",
            "redlight.settings",
            ResourceInitializationCause.WAL_SETUP_FAILED,
            initialization_stage=ResourceInitializationStage.SET_WAL_MODE,
            last_completed_stage=ResourceInitializationStage.OPEN_SETTINGS_DATABASE,
        )
        diagnostic = _action_failure_diagnostic(error)
        self.assertEqual(
            diagnostic.initialization_stage,
            ResourceInitializationStage.SET_WAL_MODE.value,
        )
        self.assertEqual(
            diagnostic.last_completed_stage,
            ResourceInitializationStage.OPEN_SETTINGS_DATABASE.value,
        )
        self.assertEqual(diagnostic.cause_code, "WAL_SETUP_FAILED")
        self.assertEqual(
            set(diagnostic.to_dict()),
            {
                "code", "owner_addon_id", "resource_id", "cause_code",
                "initialization_stage", "last_completed_stage",
            },
        )

    def test_action_diagnostic_serialization_excludes_exception_and_private_values(self):
        diagnostic = _action_failure_diagnostic(RuntimeError(FAKE_SECRET))
        action = PlanAction(CONFIGURE, "", "", "", "configuration required")
        result = ReconcileResult(
            success=False,
            request=None,
            desired_fingerprint=None,
            action_results=(ActionExecutionResult(
                action,
                False,
                False,
                f"action failed safely ({diagnostic.code})",
                diagnostic,
                RestartReport(),
            ),),
            failure=ReconcileFailure(
                ReconcilePhase.EXECUTE, "ACTION_FAILED", "action execution failed safely"
            ),
        )
        encoded = json.dumps(result.to_dict(), sort_keys=True)
        self.assertIn('"kind": "CONFIGURE"', encoded)
        self.assertNotIn("PRIVATE_RESOURCE_INITIALIZATION_FAILED", encoded)
        self.assertIn("ACTION_EXECUTION_FAILED", encoded)
        self.assertNotIn(FAKE_SECRET, encoded)
        failure_fields = result.to_dict()["action_results"][0]["failure"]
        self.assertNotIn("initialization_stage", failure_fields)
        self.assertNotIn("last_completed_stage", failure_fields)


if __name__ == "__main__":
    unittest.main()
