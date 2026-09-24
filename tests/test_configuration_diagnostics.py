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
from resources.lib.config import (
    ConfigApplyResult,
    ConfigOperationKind,
    ConfigOperationResult,
    ConfigOperationStatus,
)
from resources.lib.frozen_install import FrozenInstallCoordinator, FrozenInstallError
from resources.lib.planner import CONFIGURE, SET_SKIN, PlanAction
from resources.lib.private_overlay import (
    ConfigurationApplyBundle,
    PrivateOverlayApplyResult,
    PrivateOverlayOutcome,
    PrivateSettingResult,
)
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
        import_failure_category="",
        failing_module="",
        expected_provider="",
        actual_provider="",
    ):
        diagnostic = ActionFailureDiagnostic(
            "PRIVATE_RESOURCE_INITIALIZATION_FAILED",
            "plugin.video.redlight",
            "redlight.settings",
            cause_code,
            initialization_stage,
            last_completed_stage,
            import_failure_category,
            failing_module,
            expected_provider,
            actual_provider,
        )
        return self._frozen_error(diagnostic, action_kind=action_kind)

    def _frozen_error(self, owner_result, *, action_kind=CONFIGURE):
        action_result = SimpleNamespace(
            action=SimpleNamespace(kind=action_kind, addon_id=""),
            succeeded=False,
            owner_result=owner_result,
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

    def test_public_configuration_result_is_classified_without_private_claim(self):
        raw_private_text = "/private/fake/profile/PRIVATE_TOKEN_PUBLIC_CASE"
        public_result = ConfigApplyResult(results=(ConfigOperationResult(
            ConfigOperationKind.SETTING,
            "public-package",
            ConfigOperationStatus.FAILED,
            raw_private_text,
            raw_private_text,
            raw_private_text,
            addon_id="plugin.video.publicfixture",
            key="private.token",
        ),))
        error = self._frozen_error(public_result)

        self.assertIn("action=CONFIGURE", error.safe_detail)
        self.assertIn("configuration_scope=public", error.safe_detail)
        self.assertIn(
            "cause=PUBLIC_CONFIGURATION_OPERATION_FAILED", error.safe_detail
        )
        self.assertIn("owner=plugin.video.publicfixture", error.safe_detail)
        self.assertNotIn("addon=", error.safe_detail)
        self.assertNotIn("configuration_scope=private", error.safe_detail)
        self.assertNotIn(raw_private_text, error.safe_detail)
        self.assertNotIn("private.token", error.safe_detail)

    def test_private_bundle_failure_is_unwrapped_using_safe_fields_only(self):
        raw_private_text = "/private/fake/profile/PRIVATE_TOKEN_BUNDLE_CASE"
        private_result = PrivateOverlayApplyResult(
            PrivateOverlayOutcome.FAILED,
            metadata=None,
            results=(PrivateSettingResult(
                "plugin.video.redlight",
                "private.token",
                "failed",
                False,
                False,
                raw_private_text,
            ),),
        )
        bundle = ConfigurationApplyBundle(ConfigApplyResult(), private_result)
        error = self._frozen_error(bundle)

        self.assertIn("action=CONFIGURE", error.safe_detail)
        self.assertIn("configuration_scope=private", error.safe_detail)
        self.assertIn("cause=PRIVATE_SETTING_APPLICATION_FAILED", error.safe_detail)
        self.assertIn("owner=plugin.video.redlight", error.safe_detail)
        self.assertNotIn("addon=", error.safe_detail)
        self.assertNotIn(raw_private_text, error.safe_detail)
        self.assertNotIn("private.token", error.safe_detail)

    def test_non_configure_action_diagnostics_keep_existing_fields_without_scope(self):
        error = self._frozen_failure(SET_SKIN)

        self.assertIn("action=SET_SKIN", error.safe_detail)
        self.assertIn("owner=plugin.video.redlight", error.safe_detail)
        self.assertIn("resource=redlight.settings", error.safe_detail)
        self.assertNotIn("configuration_scope=", error.safe_detail)

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
        self.assertIn("configuration_scope=private", error.safe_detail)
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

    def test_import_ownership_fields_survive_configure_diagnostic_safely(self):
        error = self._frozen_failure(
            "configure",
            cause_code=ResourceInitializationCause.INITIALIZER_IMPORT_FAILED.value,
            initialization_stage=ResourceInitializationStage.LOAD_INITIALIZER_DECLARATIONS.value,
            last_completed_stage=ResourceInitializationStage.SOURCE_REVALIDATION.value,
            import_failure_category="MODULE_SOURCE_MISMATCH",
            failing_module="requests.packages.urllib3.exceptions",
            expected_provider="script.module.urllib3",
            actual_provider="script.module.requests",
        )
        self.assertIn("import_failure_category=MODULE_SOURCE_MISMATCH", error.safe_detail)
        self.assertIn(
            "failing_module=requests.packages.urllib3.exceptions", error.safe_detail
        )
        self.assertIn("expected_provider=script.module.urllib3", error.safe_detail)
        self.assertIn("actual_provider=script.module.requests", error.safe_detail)
        self.assertNotIn(FAKE_SECRET, error.safe_detail)
        self.assertNotIn("/private/", error.safe_detail)

    def test_action_import_diagnostics_reject_paths_and_unbounded_text(self):
        diagnostic = _action_failure_diagnostic(SimpleNamespace(
            code="PRIVATE_RESOURCE_INITIALIZATION_FAILED",
            import_failure_category="MODULE_SOURCE_MISMATCH",
            failing_module="/private/profile/secret.py",
            expected_provider="script.module.requests",
            actual_provider=FAKE_SECRET,
        ))
        self.assertEqual(diagnostic.import_failure_category, "MODULE_SOURCE_MISMATCH")
        self.assertEqual(diagnostic.failing_module, "")
        self.assertEqual(diagnostic.expected_provider, "script.module.requests")
        self.assertEqual(diagnostic.actual_provider, "")
        self.assertNotIn("/private/", json.dumps(diagnostic.to_dict()))
        self.assertNotIn(FAKE_SECRET, json.dumps(diagnostic.to_dict()))

    def test_configuration_scope_is_explicit_and_allowlisted(self):
        diagnostic = _action_failure_diagnostic(
            RuntimeError(FAKE_SECRET), configuration_scope="private"
        )

        self.assertEqual(diagnostic.to_dict()["configuration_scope"], "private")
        self.assertNotIn(FAKE_SECRET, json.dumps(diagnostic.to_dict()))
        with self.assertRaises(ValueError):
            ActionFailureDiagnostic("ACTION_EXECUTION_FAILED", configuration_scope="unknown")

    def test_action_diagnostic_extracts_typed_stage_metadata(self):
        error = StructuredResourceInitializationError(
            "plugin.video.redlight",
            "redlight.settings",
            ResourceInitializationCause.WAL_SETUP_FAILED,
            initialization_stage=ResourceInitializationStage.SET_WAL_MODE,
            last_completed_stage=ResourceInitializationStage.OPEN_SETTINGS_DATABASE,
        )
        diagnostic = _action_failure_diagnostic(
            error, configuration_scope="private"
        )
        self.assertEqual(
            diagnostic.initialization_stage,
            ResourceInitializationStage.SET_WAL_MODE.value,
        )
        self.assertEqual(
            diagnostic.last_completed_stage,
            ResourceInitializationStage.OPEN_SETTINGS_DATABASE.value,
        )
        self.assertEqual(diagnostic.cause_code, "WAL_SETUP_FAILED")
        self.assertEqual(diagnostic.configuration_scope, "private")
        self.assertEqual(
            set(diagnostic.to_dict()),
            {
                "code", "owner_addon_id", "resource_id", "cause_code",
                "initialization_stage", "last_completed_stage",
                "configuration_scope",
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
