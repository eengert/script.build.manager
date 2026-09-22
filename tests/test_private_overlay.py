"""BM-017A disposable private-overlay and secret-safety tests."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from resources.lib.config import (
    EffectiveConfiguration,
    ConfigBackendError,
    ConfigSettingType,
    ConfigurationBackend,
    ConfigurationManager,
)
from resources.lib.manifest import (
    ConfigDeclarations,
    BuildInfo,
    Manifest,
    PrivateOverlayRef,
    PrivateSettingDeclaration,
)
from resources.lib.private_overlay import (
    PrivateOverlay,
    PrivateOverlayApplyResult,
    PrivateOverlayEntry,
    PrivateOverlayManager,
    PrivateOverlayMissingError,
    PrivateOverlayOutcome,
    PrivateOverlayStore,
    PrivateOverlayValidationError,
    validate_private_overlay,
)
from resources.lib.restart import RestartReport, RestartRequirement
from resources.lib.transaction import (
    RestartTransaction,
    TransactionPhase,
    prepare_restart_transaction,
    TransactionStore,
)
from resources.lib.build_manager import ReconcileRequest, ReconcileResult


SECRET = "BM017_TEST_SECRET_DO_NOT_LOG"
BUILD_ID = "bm017-disposable"


def _declarations():
    return (
        PrivateSettingDeclaration(
            "plugin.video.fixture", "api_token", "string", True, "token"
        ),
        PrivateSettingDeclaration(
            "plugin.video.fixture", "account_id", "string", True, "private_identifier"
        ),
        PrivateSettingDeclaration(
            "plugin.video.fixture", "nickname", "string", False, "private_identifier"
        ),
    )


def _overlay(*, include_required=True, include_optional=True, token=SECRET):
    entries = []
    if include_required:
        entries.extend([
            PrivateOverlayEntry(
                "plugin.video.fixture", "api_token", ConfigSettingType.STRING, token
            ),
            PrivateOverlayEntry(
                "plugin.video.fixture", "account_id", ConfigSettingType.STRING, "fake-account-017"
            ),
        ])
    if include_optional:
        entries.append(
            PrivateOverlayEntry(
                "plugin.video.fixture", "nickname", ConfigSettingType.STRING, "disposable"
            )
        )
    return PrivateOverlay("fixture-overlay", BUILD_ID, tuple(entries))


class FakeBackend(ConfigurationBackend):
    def __init__(self, settings=None):
        self.settings = dict(settings or {})
        self.writes = []
        self.fail = None

    def get_setting(self, addon_id, key, setting_type):
        if (addon_id, key) not in self.settings:
            raise ConfigBackendError("unknown disposable setting")
        return self.settings[(addon_id, key)]

    def set_setting(self, addon_id, key, setting_type, value):
        if self.fail:
            raise ConfigBackendError(self.fail)
        self.writes.append((addon_id, key))
        self.settings[(addon_id, key)] = value

    def read_file(self, destination):
        return None

    def write_file(self, destination, data):
        raise ConfigBackendError("files are not part of this fixture")


class PrivateOverlayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = PrivateOverlayStore(self.root / "profile")
        self.backend = FakeBackend({
            ("plugin.video.fixture", "api_token"): "old-token",
            ("plugin.video.fixture", "account_id"): "old-account",
            ("plugin.video.fixture", "nickname"): "old-name",
        })
        self.manager = PrivateOverlayManager(
            ConfigurationManager(self.backend), store=self.store
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_overlay_round_trips_and_is_stored_outside_public_paths(self):
        overlay = _overlay()
        path = self.store.save(overlay)
        self.assertEqual(self.store.load(overlay.overlay_id), overlay)
        self.assertTrue(str(path).startswith(str((self.root / "profile").resolve())))
        self.assertNotIn("public-build", str(path))
        if os.name == "posix":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)

    def test_atomic_import_and_malformed_storage_fail_closed(self):
        source = self.root / "import.json"
        source.write_text(json.dumps(_overlay().to_dict()), encoding="utf-8")
        imported = self.store.import_file(source)
        self.assertEqual(imported, _overlay())
        self.store.path_for(imported.overlay_id).write_text("{bad", encoding="utf-8")
        with self.assertRaises(PrivateOverlayValidationError):
            self.store.load(imported.overlay_id)

    def test_unknown_schema_and_duplicate_entries_fail_closed(self):
        with self.assertRaises(PrivateOverlayValidationError):
            PrivateOverlay.from_dict({"schema_version": 99})
        duplicate = _overlay().to_dict()
        duplicate["entries"].append(duplicate["entries"][0])
        with self.assertRaises(PrivateOverlayValidationError):
            PrivateOverlay.from_dict(duplicate)

    def test_fingerprint_is_deterministic_and_changes_with_private_content(self):
        self.assertEqual(_overlay().fingerprint, _overlay().fingerprint)
        self.assertNotEqual(
            _overlay().fingerprint,
            _overlay(token="BM017_TEST_SECRET_CHANGED").fingerprint,
        )

    def test_declaration_validation_rejects_undeclared_wrong_and_missing_values(self):
        with self.assertRaises(PrivateOverlayValidationError):
            validate_private_overlay(
                PrivateOverlay(
                    "fixture-overlay", BUILD_ID,
                    (PrivateOverlayEntry("plugin.video.other", "token", ConfigSettingType.STRING, "x"),),
                ),
                _declarations(), expected_build_id=BUILD_ID,
                expected_overlay_id="fixture-overlay",
            )
        wrong_type = PrivateOverlay(
            "fixture-overlay", BUILD_ID,
            (PrivateOverlayEntry("plugin.video.fixture", "api_token", ConfigSettingType.BOOL, True),),
        )
        with self.assertRaises(PrivateOverlayValidationError):
            validate_private_overlay(wrong_type, _declarations())
        with self.assertRaises(PrivateOverlayValidationError):
            validate_private_overlay(
                _overlay(include_required=False), _declarations()
            )

    def test_optional_private_value_may_be_absent(self):
        declarations = _declarations()
        self.assertIsNotNone(validate_private_overlay(
            _overlay(include_optional=False), declarations,
            expected_build_id=BUILD_ID, expected_overlay_id="fixture-overlay",
        ))

    def test_required_missing_overlay_fails_before_application(self):
        with self.assertRaises(PrivateOverlayMissingError):
            self.manager.prepare(
                PrivateOverlayRef("local_file", overlay_id="fixture-overlay", required=True),
                _declarations(), build_id=BUILD_ID,
            )
        self.assertEqual(self.backend.writes, [])

    def test_optional_missing_overlay_is_a_safe_noop(self):
        prepared = self.manager.prepare(
            PrivateOverlayRef("local_file", overlay_id="fixture-overlay", required=False),
            _declarations(), build_id=BUILD_ID,
        )
        result = self.manager.apply(prepared)
        self.assertEqual(result.outcome, PrivateOverlayOutcome.ABSENT_OPTIONAL)
        self.assertEqual(self.backend.writes, [])

    def test_public_then_private_uses_same_typed_backend_and_verifies_readback(self):
        overlay = _overlay()
        self.store.save(overlay)
        prepared = self.manager.prepare(
            PrivateOverlayRef("local_file", overlay_id=overlay.overlay_id, required=True),
            _declarations(), build_id=BUILD_ID,
        )
        result = self.manager.apply(prepared)
        self.assertEqual(result.outcome, PrivateOverlayOutcome.APPLIED)
        self.assertEqual(len(result.results), 3)
        self.assertTrue(all(item.verified for item in result.results))
        self.assertEqual(self.backend.settings[("plugin.video.fixture", "api_token")], SECRET)

    def test_application_failure_is_sanitized(self):
        overlay = _overlay()
        self.store.save(overlay)
        self.backend.fail = SECRET
        prepared = self.manager.prepare(
            PrivateOverlayRef("local_file", overlay_id=overlay.overlay_id, required=True),
            _declarations(), build_id=BUILD_ID,
        )
        result = self.manager.apply(prepared)
        raw = json.dumps(result.to_dict())
        self.assertEqual(result.outcome, PrivateOverlayOutcome.FAILED)
        self.assertNotIn(SECRET, raw)
        self.assertNotIn(SECRET, result.message)

    def test_safe_serialization_excludes_values(self):
        overlay = _overlay()
        self.assertNotIn(SECRET, json.dumps(overlay.safe_dict()))
        metadata = self.manager.prepare(
            PrivateOverlayRef("local_file", overlay_id=overlay.overlay_id, required=True),
            _declarations(), build_id=BUILD_ID,
        ) if self.store.save(overlay) else None
        self.assertNotIn(SECRET, json.dumps(metadata.metadata.to_dict()))

    def test_restart_transaction_contains_only_overlay_identity(self):
        overlay = _overlay()
        self.store.save(overlay)
        prepared = self.manager.prepare(
            PrivateOverlayRef("local_file", overlay_id=overlay.overlay_id, required=True),
            _declarations(), build_id=BUILD_ID,
        )
        result = self.manager.apply(prepared)
        reconcile = ReconcileResult(
            success=True,
            request=ReconcileRequest("public.json", "disposable"),
            desired_fingerprint="sha256:" + "a" * 64,
            restart_report=RestartReport(RestartRequirement.KODI_RESTART, 1, 0),
            private_overlay=prepared.metadata,
        )
        store = TransactionStore(str(self.root / "transactions"))
        prepared_tx = prepare_restart_transaction(
            reconcile.request, reconcile,
            "11111111-1111-4111-8111-111111111111", store=store,
        )
        raw = Path(store.transaction_path).read_text(encoding="utf-8")
        self.assertEqual(prepared_tx.transaction.private_overlay_id, overlay.overlay_id)
        self.assertEqual(prepared_tx.transaction.private_overlay_fingerprint, overlay.fingerprint)
        self.assertNotIn(SECRET, raw)
        self.assertNotIn("value", raw)

    def test_manifest_public_declaration_contains_no_private_value(self):
        from resources.lib.manifest import load_manifest_json
        document = {
            "schema_version": 1,
            "build": {"id": BUILD_ID, "version": "1.0.0"},
            "config": {"private_settings": [{
                "addon_id": "plugin.video.fixture",
                "key": "api_token",
                "type": "string",
                "sensitivity": "token",
            }]},
            "private_overlay": {
                "type": "local_file",
                "overlay_id": "fixture-overlay",
                "required": True,
            },
        }
        manifest = load_manifest_json(json.dumps(document))
        self.assertEqual(manifest.config.private_settings[0].key, "api_token")
        self.assertNotIn(SECRET, json.dumps(document))

    def test_build_manager_preflight_requires_overlay_before_mutation(self):
        from resources.lib.build_manager import BuildManager, BuildManagerOwners
        from resources.lib.dependencies import DependencyClosure
        from resources.lib.inspector import KodiState
        from resources.lib.resolver import ResolvedBuild

        desired = ResolvedBuild(
            build=BuildInfo(BUILD_ID, "1.0.0"), engine_min_version="",
            platform_profile_id="disposable", device_profile_id="fixture",
            repositories=(), addons=(), skin=None,
            config=ConfigDeclarations(private_settings=_declarations()),
            optional_groups_applied=(), restart_policy=None,
            private_overlay=PrivateOverlayRef(
                "local_file", overlay_id="missing", required=True
            ),
        )

        class EmptyInspector:
            def inspect(self):
                return KodiState("macos", "21.0", "", ())

        class EmptyDeps:
            def resolve_closure(self, roots, **kwargs):
                return DependencyClosure(root_addon_ids=(), nodes=())

        class Noop:
            def install(self, *args, **kwargs):
                return type("Result", (), {"succeeded": True, "changed": False, "restart_report": RestartReport()})()

            def activate(self, *args, **kwargs):
                return self.install()

            def reconcile(self, *args, **kwargs):
                return type("Result", (), {"all_correct": True, "changed": (), "failed": (), "results": ()})()

        owners = BuildManagerOwners(
            inspector=EmptyInspector(),
            manifest_loader=lambda _path: Manifest(1, desired.build),
            resolver=lambda _manifest, _device: desired,
            dependency_resolver=EmptyDeps(),
            repository_manager=Noop(),
            dependency_installer=Noop(),
            addon_state_reconciler=Noop(),
            skin_activator=Noop(),
            config_loader=type("Loader", (), {"resolve": lambda _self, _config: EffectiveConfiguration()})(),
            config_manager=ConfigurationManager(self.backend),
            private_overlay_manager=self.manager,
        )
        result = BuildManager(owners).reconcile(ReconcileRequest("public.json", "fixture"))
        self.assertFalse(result.success)
        self.assertEqual(result.failure.code, "PREFLIGHT_FAILED")
        self.assertEqual(self.backend.writes, [])


if __name__ == "__main__":
    unittest.main()
