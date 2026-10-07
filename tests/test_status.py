"""BM-UI-002B: truthful, read-only, secret-blind Build Status (G2)."""

import ast
import contextlib
import hashlib
import json
import os
import socket
import sqlite3
import tempfile
import urllib.request
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib import (
    addon_registry, addon_state, addons, build_manager, config as config_module, dependencies,
    frozen_install, private_overlay, private_resource, redlight_resource, repository,
    restart_coordinator, resume, session, skin, startup, transaction, update_guard,
)
from resources.lib.build_identity import (
    IdentityCode, IdentityMismatch, bind_resolutions,
)
from resources.lib.config import (
    ConfigBackendError, ConfigFile, ConfigSetting, ConfigSettingType, ConfigTargetKind,
    ConfigurationBackend, ConfigurationInspector, EffectiveConfiguration,
    ReadOnlyConfigurationBackend,
)
from resources.lib.dependencies import DependencyBackend, DependencyResolver
from resources.lib.frozen import (
    AddonCaptureNode, CaptureStatus, FrozenBuildManifest, ProvenanceStatus,
)
from resources.lib.frozen_install import (
    FrozenInstallPhase, FrozenInstallStore, FrozenInstallTransaction,
)
from resources.lib import frozen_resolution
from resources.lib.frozen_resolution import (
    FrozenInstallResolutionManifest, InstallResolution, InstallResolutionRecord, ResolutionState,
)
from resources.lib.inspector import KodiBackend, KodiStateInspector
from resources.lib.manifest import (
    FrozenInstallPolicy, FrozenInstallPolicyMode,
    AddonEntry, BuildInfo, ConfigDeclarations, ManagedSettingScope,
    PrivateOverlayRef, PrivateSettingDeclaration, SkinEntry,
)
from resources.lib.private_overlay import (
    PrivateOverlay, PrivateOverlayEntry, PrivateOverlayStore,
)
from resources.lib.private_resource import (
    ResourceCheckStatus, StructuredPrivateResourceManager, StructuredPrivateResourceOverlay,
    StructuredPrivateValue, StructuredResourceFieldDeclaration,
)
from resources.lib.redlight_resource import (
    REDLIGHT_ADDON_ID, REDLIGHT_RESOURCE_ID, REDLIGHT_SCHEMA_ID, RedLightSettingsAdapter,
    redlight_declaration,
)
from resources.lib.resolver import ResolvedBuild
from resources.lib.restart import RestartRequirement
from resources.lib.session import peek_current_kodi_session_id
from resources.lib.status import (
    BuildStatusService, StatusOwners, StatusTarget, _ReadOnlyDependencyBackend,
    combine_overall, default_status_owners,
)
from resources.lib.status_model import (
    AreaLevel, BuildStatus, CheckGap, ConfigurationStatus, OperationCode, OperationKind,
    OperationStatus, OverallStatus, PrivateItem, PrivateItemKind, PrivateStatus, SkinStatus,
    SoftwareItem, SoftwareItemState, SoftwareStatus, StatusArea,
)
from resources.lib.transaction import (
    RestartTransaction, TransactionCorrupt, TransactionPhase, TransactionStore,
)

ROOT = Path(__file__).resolve().parents[1]
SECRET = "BM_UI_002B_SENTINEL_SECRET_VALUE"
DB_SECRET = "BM_UI_002B_SENTINEL_DB_ROW_VALUE"
SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"
FINGERPRINT = "sha256:" + "a" * 64
BUILD_ID = "status-fixture"
NOW = "2026-10-06T14:47:00Z"
DEMO, MODULE, SKIN = "plugin.video.demo", "script.module.demo", "skin.demo"


# -- fakes -------------------------------------------------------------------------

class FakeKodi(KodiBackend):
    def __init__(self, addons, skin=SKIN):
        self.addons = dict(addons)          # id -> (version, enabled)
        self.skin = skin
        self.calls = 0

    def get_platform_flags(self):
        return {"macos": True}

    def get_kodi_version(self):
        return "21.0"

    def get_active_skin(self):
        return self.skin

    def get_installed_addons(self):
        self.calls += 1
        return [{"addonid": i, "version": v, "enabled": e}
                for i, (v, e) in sorted(self.addons.items())]


class FakeConfigBackend(ConfigurationBackend):
    """Records reads; every mutator records itself and raises."""

    def __init__(self, settings=None, skin_settings=None, files=None, unreadable=()):
        self.settings = dict(settings or {})
        self.skin_settings = dict(skin_settings or {})
        self.files = dict(files or {})
        self.unreadable = set(unreadable)
        self.reads, self.mutations = [], []

    def _get(self, table, kind, addon_id, key):
        self.reads.append((kind, addon_id, key))
        if (addon_id, key) in self.unreadable or (addon_id, key) not in table:
            raise ConfigBackendError("SENTINEL_BACKEND_ERROR_TEXT " + SECRET)
        return table[(addon_id, key)]

    def get_setting(self, addon_id, key, setting_type):
        return self._get(self.settings, "addon", addon_id, key)

    def get_skin_setting(self, addon_id, key, setting_type):
        return self._get(self.skin_settings, "skin", addon_id, key)

    def read_file(self, destination):
        self.reads.append(("file", destination, ""))
        return self.files.get(destination)

    def set_setting(self, *args):
        self.mutations.append("set_setting")
        raise AssertionError("status wrote a setting")

    def set_skin_setting(self, *args):
        self.mutations.append("set_skin_setting")
        raise AssertionError("status wrote a skin setting")

    def write_file(self, *args):
        self.mutations.append("write_file")
        raise AssertionError("status wrote a managed file")


class FakeDeps(DependencyBackend):
    def __init__(self, installed):
        self.installed = installed          # id -> (version, enabled)
        self.mutations = []
        self.repository_reads = []          # status must never consult repositories
        self.broken_xml = set()             # installed add-ons whose own addon.xml is unreadable

    def get_addon_details(self, addon_id):
        if addon_id not in self.installed:
            return None
        version, enabled = self.installed[addon_id]
        return SimpleNamespace(version=version, enabled=enabled)

    def read_addon_xml(self, addon_id):
        if addon_id not in self.installed or addon_id in self.broken_xml:
            return None
        return ('<addon id="%s" version="%s"><requires/></addon>'
                % (addon_id, self.installed[addon_id][0])).encode()

    def read_available_addon_xml(self, addon_id):
        self.repository_reads.append(addon_id)     # would download from a repository
        return ('<addon id="%s" version="9.9"><requires/></addon>' % addon_id).encode()

    def install_addon(self, *args, **kwargs):
        self.mutations.append("install_addon")
        raise AssertionError("status installed an add-on")

    def set_addon_enabled(self, *args):
        self.mutations.append("set_addon_enabled")
        raise AssertionError("status toggled an add-on")


def _node(addon_id, version, enabled=True, **kwargs):
    return AddonCaptureNode(addon_id, version, "xbmc.python.pluginsource", enabled,
                            ProvenanceStatus.VERIFIED_REPOSITORY, **kwargs)


def frozen_manifest(extra=()):
    return FrozenBuildManifest(
        schema_version=1, build_id=BUILD_ID, name="Status fixture",
        created_at="2026-10-06T00:00:00Z", kodi_version="21.0", platform="macos",
        capture_status=CaptureStatus.COMPLETE,
        addons=(
            _node(DEMO, "1.0.0"), _node(MODULE, "2.0.0"),
            _node("xbmc.python", "3.0.1", system=True),
            AddonCaptureNode("script.module.optional", "", "", False, ProvenanceStatus.UNKNOWN,
                             optional=True, status=CaptureStatus.MISSING),
        ) + tuple(extra))


def redlight_resource_declaration():
    return redlight_declaration(fields=(
        StructuredResourceFieldDeclaration("trakt.token", "string", True, "token"),))


def build_db(profile, token=DB_SECRET):
    folder = Path(profile) / "addon_data" / REDLIGHT_ADDON_ID / "databases"
    folder.mkdir(parents=True)
    connection = sqlite3.connect(folder / "settings.db")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("CREATE TABLE settings (setting_id text not null unique, "
                       "setting_type text, setting_default text, setting_value text)")
    connection.execute("INSERT INTO settings VALUES ('trakt.token','string','',?)", (token,))
    connection.commit()
    connection.close()
    return folder / "settings.db"


def snapshot_tree(root):
    """Names, sizes, mtimes and digests of everything under root."""
    out = {}
    for path in sorted(Path(root).rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_dir():
            out[rel] = ("dir",)
        else:
            stat = path.stat()
            out[rel] = ("file", stat.st_size, stat.st_mtime_ns,
                        hashlib.sha256(path.read_bytes()).hexdigest())
    return out


MUTATORS = (
    (transaction.TransactionStore, ("create", "update_phase", "transition_expected", "clear",
                                    "clear_expected", "inspect", "locked", "locked_access",
                                    "locked_inspection", "acquire_lock")),
    (transaction.TransactionLock, ("acquire",)),
    (frozen_install.FrozenInstallStore, ("__init__", "create", "transition_expected",
                                         "rearm_held_quiescence", "clear_expected", "clear",
                                         "inspect", "locked", "save_resolution_manifest")),
    (frozen_install.FrozenInstallLock, ("acquire",)),
    (frozen_install.FrozenInstallCoordinator, ("install", "retry_held_quiescence",
                                               "resume_after_restart", "abandon")),
    (private_overlay.PrivateOverlayStore, ("save", "import_file")),
    (private_overlay.PrivateOverlayManager, ("prepare", "apply", "verify_configured_resources")),
    (config_module.ConfigurationManager, ("apply", "apply_settings")),
    (config_module.KodiRuntimeConfigurationBackend, ("set_setting", "set_skin_setting",
                                                     "write_file")),
    (private_resource.StructuredPrivateResourceManager, ("apply", "initialize", "capture")),
    (redlight_resource.RedLightSettingsAdapter, ("apply", "initialize", "capture")),
    (build_manager.BuildManager, ("reconcile", "preview")),
    (addon_state.AddonStateReconciler, ("reconcile",)),
    (addon_state.KodiRuntimeAddonStateBackend, ("set_addon_enabled",)),
    (skin.SkinActivator, ("activate",)),
    (skin.KodiRuntimeSkinSettingsBackend, ("set_setting",)),
    (addons.AddonManager, ("install",)),
    (addons.KodiRuntimeAddonBackend, ("invoke_install", "set_addon_enabled")),
    (repository.RepositoryManager, ("install",)),
    (dependencies.DependencyAwareInstaller, ("install",)),
    (dependencies.DependencyResolver, ("reconcile_dependencies",)),
    (dependencies.KodiRuntimeDependencyBackend, ("install_addon", "set_addon_enabled")),
    (update_guard.AddonUpdateGuard, ("engage", "engage_with_original", "reassert",
                                     "reassert_required", "restore", "restore_original")),
    (update_guard.KodiJsonRpcUpdatePolicyBackend, ("set_policy",)),
    (resume.ResumeCoordinator, ("resume",)),
    (restart_coordinator.RestartCoordinator, ("reconcile", "handle_result")),
    # module-level entry points that create state, restore policy, or run lifecycle work
    (frozen_install, ("ensure_frozen_install_guard", "ensure_frozen_transaction_registry_ready",
                      "ensure_frozen_resume_registry_ready", "run_frozen_install_startup",
                      "active_activation_hold_ids")),
    (addon_registry, ("ensure_staged_addons_registered_for_configuration",
                      "ensure_staged_addon_registered_for_configuration")),
    (startup, ("run_startup",)),
    (transaction, ("prepare_restart_transaction",)),
    (restart_coordinator, ("reconcile_with_restart",)),
)


class Harness:
    """A complete, current build whose parts each test can break."""

    def __init__(self, test, *, with_private=True, with_resource=True, with_frozen=True):
        self.test = test
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name) / "profile"
        self.profile.mkdir()
        self.frozen_root = self.profile / "addon_data" / "script.build.manager"
        self.logs, self.touched = [], []
        self.kodi = FakeKodi({
            DEMO: ("1.0.0", True), MODULE: ("2.0.0", True), SKIN: ("1.0.0", True),
            REDLIGHT_ADDON_ID: ("2.6.8", True),
            "plugin.video.unmanaged": ("0.1", False), "script.module.other": ("9.9", True),
        })
        self.settings = {(DEMO, "quality"): "high"}
        self.skin_settings = {(SKIN, "Menu.Style"): True}
        self.files = {"userdata/keymaps/demo.xml": b"<keymap/>"}
        self.config_backend = FakeConfigBackend(
            {**self.settings, (DEMO, "api_token"): SECRET}, self.skin_settings, self.files)
        self.deps = FakeDeps({k: v for k, v in self.kodi.addons.items()})
        self.with_private, self.with_resource, self.with_frozen = (
            with_private, with_resource, with_frozen)
        self.frozen = frozen_manifest()
        self.resolver_failure = None
        self.overlay_store = PrivateOverlayStore(self.profile)
        self.declaration = redlight_resource_declaration()
        self.db = build_db(self.profile) if with_resource else None
        self.records = ()
        self.rebuild()
        self.desired = replace(self.desired, frozen_install_policies=(
            FrozenInstallPolicy(MODULE, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP,
                                "repository.demo"),))

    # desired state -------------------------------------------------------------
    def rebuild(self, *, skin_id=SKIN):
        scopes = (ManagedSettingScope(DEMO, ("quality",)),
                  ManagedSettingScope(SKIN, ("Menu.Style",), ConfigTargetKind.SKIN))
        private = (PrivateSettingDeclaration(DEMO, "api_token", "string", True, "token"),) \
            if self.with_private else ()
        resources = (self.declaration,) if self.with_resource else ()
        self.desired = ResolvedBuild(
            build=BuildInfo(BUILD_ID, "1.0.0"), engine_min_version="",
            platform_profile_id="p", device_profile_id="d", repositories=(),
            addons=(AddonEntry(DEMO, "enabled"), AddonEntry(REDLIGHT_ADDON_ID, "enabled")),
            skin=SkinEntry(skin_id),
            config=ConfigDeclarations(
                packages=("pkg",), managed_settings=scopes,
                managed_files=("userdata/keymaps/demo.xml",),
                private_settings=private, structured_private_resources=resources),
            optional_groups_applied=(), restart_policy=None,
            private_overlay=PrivateOverlayRef("local_file", overlay_id="status-overlay",
                                              required=True) if private or resources else None)
        self.effective = EffectiveConfiguration(
            packages=("pkg",),
            settings=(
                ConfigSetting(DEMO, "quality", ConfigSettingType.STRING, "high", "pkg"),
                ConfigSetting(SKIN, "Menu.Style", ConfigSettingType.BOOL, True, "pkg",
                              ConfigTargetKind.SKIN)),
            files=(ConfigFile("userdata/keymaps/demo.xml", "demo.xml", b"<keymap/>", "pkg"),))

    def save_overlay(self, *, value=SECRET, resource_value=DB_SECRET):
        entries = (PrivateOverlayEntry(DEMO, "api_token", ConfigSettingType.STRING, value),) \
            if self.with_private else ()
        resources = (StructuredPrivateResourceOverlay(
            REDLIGHT_RESOURCE_ID, REDLIGHT_ADDON_ID, "2.6.8", REDLIGHT_SCHEMA_ID,
            (StructuredPrivateValue("trakt.token", "string", resource_value),)),) \
            if self.with_resource else ()
        target = ("sha256:" + self.frozen.fingerprint()) if self.with_frozen else BUILD_ID
        self.overlay_store.save(PrivateOverlay("status-overlay", target, entries,
                                               resources=resources))

    # service ---------------------------------------------------------------------
    def owners(self, **overrides):
        harness = self

        class Loader:
            def resolve(self, config):
                return harness.effective

        def resolver(manifest, profile):
            if harness.resolver_failure is not None:
                raise harness.resolver_failure
            return harness.desired

        values = dict(
            inspector=KodiStateInspector(self.kodi),
            manifest_loader=lambda path: path,
            resolver=resolver,
            frozen_manifest_loader=lambda path: harness.frozen,
            config_loader=Loader(),
            configuration_inspector=ConfigurationInspector(
                ReadOnlyConfigurationBackend(self.config_backend)),
            dependency_resolver=DependencyResolver(_ReadOnlyDependencyBackend(self.deps)),
            overlay_loader=self.overlay_store.read_snapshot,
            resource_manager=lambda: StructuredPrivateResourceManager(
                {RedLightSettingsAdapter.adapter_id: RedLightSettingsAdapter(self.profile)}),
            restart_snapshot=TransactionStore(str(self.profile)).read_snapshot,
            frozen_snapshot=lambda: FrozenInstallStore.read_snapshot(self.frozen_root),
            session_id=lambda: SESSION_A,
            clock=lambda: NOW,
            log=self.logs.append,
        )
        values.update(overrides)
        return StatusOwners(**values)

    def target(self, **kwargs):
        kwargs.setdefault("software_manifest_path", "/frozen.json" if self.with_frozen else "")
        return StatusTarget("/build.json", "d", **kwargs)

    def resolution(self, *records, **overrides):
        """A valid install-resolution manifest bound to this build and its frozen graph."""
        records = tuple(sorted(records, key=lambda record: record.addon_id))
        values = dict(
            build_id=self.desired.build.id,
            source_software_fingerprint=self.frozen.fingerprint(),
            install_plan_fingerprint=frozen_resolution.install_plan_fingerprint(
                self.frozen, self.desired.frozen_install_policies),
            records=records)
        if "resulting_software_fingerprint" not in overrides:
            values["resulting_software_fingerprint"] = (
                frozen_resolution._resolved_fingerprint_from_records(
                    self.frozen.fingerprint(), records))
        values.update(overrides)
        return FrozenInstallResolutionManifest(**values)

    def service(self, **overrides):
        return BuildStatusService(self.owners(**overrides))

    @contextlib.contextmanager
    def instrumented(self):
        """Any call to a mutating (or file-creating) owner method is recorded."""
        self.touched.clear()
        with contextlib.ExitStack() as stack:
            for cls, names in MUTATORS:
                for name in names:
                    def tripwire(*a, _label="%s.%s" % (cls.__name__, name), **k):
                        self.touched.append(_label)
                        raise AssertionError("status called " + _label)
                    stack.enter_context(patch.object(cls, name, tripwire))
            for module, name in ((urllib.request, "urlopen"), (socket, "create_connection"),
                                 (socket.socket, "connect")):
                stack.enter_context(patch.object(
                    module, name,
                    lambda *a, _label="network:%s" % name, **k: (
                        self.touched.append(_label), (_ for _ in ()).throw(AssertionError(_label)))))
            stack.enter_context(patch.object(
                session, "get_current_kodi_session_id",
                lambda *a, **k: self.touched.append("get_current_kodi_session_id")))
            yield

    def check(self, target=None, **kwargs):
        target = self.target(**kwargs) if target is None else target
        with self.instrumented():
            status = self.service().check(target)
        self.test.assertEqual(self.touched, [])
        self.test.assertEqual(self.config_backend.mutations, [])
        self.test.assertEqual(self.deps.mutations, [])
        self.test.assertEqual(self.deps.repository_reads, [])
        return status

    # durable operation state ---------------------------------------------------------
    def restart_transaction(self, phase=TransactionPhase.AWAITING_RESTART, session_id=SESSION_A,
                            status_code=""):
        TransactionStore(str(self.profile)).create(RestartTransaction(
            transaction_id="33333333-3333-4333-8333-333333333333", phase=phase,
            request=build_manager.ReconcileRequest("/safe/build.json", "d"),
            desired_state_fingerprint=FINGERPRINT,
            restart_requirement=RestartRequirement.KODI_RESTART,
            originating_kodi_session_id=session_id,
            created_at="2026-10-06T12:00:00+00:00", updated_at="2026-10-06T12:00:00+00:00",
            status_code=status_code))

    def frozen_transaction(self, phase, *, session_id=SESSION_A, hold=(), released=True,
                           status_code=""):
        FrozenInstallStore(self.frozen_root).create(FrozenInstallTransaction(
            transaction_id="44444444-4444-4444-8444-444444444444", build_id=BUILD_ID,
            manifest_path="/frozen.json", device_profile_id="d", manifest_fingerprint="a" * 64,
            phase=phase, originating_kodi_session_id=session_id,
            original_update_policy=update_guard.AddonUpdatePolicy.AUTOMATIC,
            created_at="2026-10-06T12:00:00Z", updated_at="2026-10-06T12:00:00Z",
            status_code=status_code, activation_hold_ids=hold, activation_hold_released=released))


def safe_text(status: BuildStatus) -> str:
    return repr(status) + json.dumps(status.to_safe_dict())


class StatusBase(unittest.TestCase):
    def current(self, **kwargs):
        harness = Harness(self, **kwargs)
        harness.save_overlay()
        return harness

    def assertSecretFree(self, *values):
        for value in values:
            for secret in (SECRET, DB_SECRET, "SENTINEL_BACKEND_ERROR_TEXT"):
                self.assertNotIn(secret, str(value))
                self.assertNotIn(secret, repr(value))


class ProductionAddonNameResolver(unittest.TestCase):
    def test_default_owners_supply_a_lazy_read_only_name_resolver(self):
        owners = default_status_owners()
        self.assertTrue(callable(owners.name_resolver))

    def test_disabled_installed_addon_name_is_returned_from_json_rpc(self):
        addon_id = "repository.eengert"
        installed = {addon_id: {"enabled": False, "name": "Eengert Repository"}}
        requests = []

        def execute_json_rpc(request):
            body = json.loads(request)
            requests.append(body)
            requested_id = body["params"]["addonid"]
            metadata = installed.get(requested_id)
            if metadata is None:
                return json.dumps({"error": {"code": -32602}})
            return json.dumps({"result": {"addon": {
                "addonid": requested_id, "name": metadata["name"]}}})

        with patch.dict("sys.modules", {"xbmc": SimpleNamespace(executeJSONRPC=execute_json_rpc)}):
            resolver = default_status_owners().name_resolver
            self.assertEqual(resolver(addon_id), "Eengert Repository")

        self.assertFalse(installed[addon_id]["enabled"])
        self.assertEqual(requests, [{
            "jsonrpc": "2.0", "method": "Addons.GetAddonDetails",
            "params": {"addonid": addon_id, "properties": ["name"]},
            "id": 1,
        }])

    def test_status_service_uses_the_production_resolver(self):
        h = Harness(self)
        h.save_overlay()
        names = {DEMO: "Demo Video", REDLIGHT_ADDON_ID: "Red Light"}

        def execute_json_rpc(request):
            body = json.loads(request)
            addon_id = body["params"]["addonid"]
            name = names.get(addon_id)
            if name is None:
                return json.dumps({"error": {"code": -32602}})
            return json.dumps({"result": {"addon": {"addonid": addon_id, "name": name}}})

        with patch.dict("sys.modules", {"xbmc": SimpleNamespace(executeJSONRPC=execute_json_rpc)}):
            owners = default_status_owners()
            with h.instrumented():
                status = h.service(name_resolver=owners.name_resolver).check(h.target())

        self.assertEqual(h.touched, [])
        self.assertEqual(h.config_backend.mutations, [])
        self.assertEqual(h.deps.mutations, [])
        self.assertEqual(h.deps.repository_reads, [])
        items = {item.addon_id: item for item in status.software.items}
        self.assertEqual(items[DEMO].display_name, "Demo Video")
        self.assertEqual(items[REDLIGHT_ADDON_ID].display_name, "Red Light")

    def test_lookup_fails_closed_for_unavailable_runtime_bad_response_and_exception(self):
        resolver = default_status_owners().name_resolver
        cases = (
            (None, ""),
            ({"error": {"code": -32602}}, ""),
            ({"result": {"addon": {"addonid": "plugin.video.demo"}}}, ""),
            ({"result": {"addon": {"addonid": "plugin.video.other", "name": "Other"}}}, ""),
            ({"result": {"addon": []}}, ""),
            ({"result": {"addon": {"addonid": "plugin.video.demo", "name": 17}}}, ""),
        )
        for response, expected in cases:
            with self.subTest(response=response):
                module = SimpleNamespace(executeJSONRPC=lambda _: json.dumps(response))
                with patch.dict("sys.modules", {"xbmc": module}):
                    self.assertEqual(resolver("plugin.video.demo"), expected)

        def broken(_request):
            raise RuntimeError("SENTINEL_RUNTIME_EXCEPTION_TEXT")

        with patch.dict("sys.modules", {"xbmc": SimpleNamespace(executeJSONRPC=broken)}):
            result = resolver("plugin.video.demo")
        self.assertEqual(result, "")
        self.assertNotIn("SENTINEL_RUNTIME_EXCEPTION_TEXT", result)

        with patch.dict("sys.modules", {"xbmc": None}):
            self.assertEqual(resolver("plugin.video.demo"), "")

    def test_invalid_addon_id_is_not_sent_to_kodi(self):
        calls = []
        module = SimpleNamespace(executeJSONRPC=lambda request: calls.append(request) or "{}")
        with patch.dict("sys.modules", {"xbmc": module}):
            resolver = default_status_owners().name_resolver
            self.assertEqual(resolver("../repository.eengert"), "")
        self.assertEqual(calls, [])


# -- the 17 required scenarios --------------------------------------------------------

class CurrentAndDrift(StatusBase):
    def test_01_fully_current_state_is_current(self):
        status = self.current().check()
        self.assertEqual(status.overall, OverallStatus.CURRENT)
        for area in StatusArea:
            self.assertEqual(status.area(area), AreaLevel.CURRENT, area)
        self.assertEqual(status.operation, OperationStatus())
        self.assertEqual(status.gaps, ())
        self.assertTrue(status.skin.matches)
        self.assertEqual({i.addon_id for i in status.software.items},
                         {DEMO, MODULE, REDLIGHT_ADDON_ID})
        self.assertEqual(status.checked_at, NOW)
        self.assertEqual(
            {(i.kind, i.level) for i in status.private.items},
            {(PrivateItemKind.SETTINGS, AreaLevel.CURRENT),
             (PrivateItemKind.RESOURCE, AreaLevel.CURRENT)})

    def test_02_missing_managed_addon_needs_changes(self):
        h = self.current()
        del h.kodi.addons[MODULE]
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CHANGES_NEEDED)
        self.assertEqual(status.software.level, AreaLevel.CHANGES_NEEDED)
        states = {i.addon_id: i.state for i in status.software.items}
        self.assertEqual(states[MODULE], SoftwareItemState.MISSING)
        self.assertEqual(states[DEMO], SoftwareItemState.CURRENT)

    def test_03_wrong_managed_version_needs_changes(self):
        h = self.current()
        h.kodi.addons[MODULE] = ("1.9.9", True)
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CHANGES_NEEDED)
        self.assertEqual({i.addon_id: i.state for i in status.software.items}[MODULE],
                         SoftwareItemState.WRONG_VERSION)

    def test_04_wrong_managed_enabled_state_needs_changes(self):
        h = self.current()
        h.kodi.addons[MODULE] = ("2.0.0", False)
        h.kodi.addons[DEMO] = ("1.0.0", False)
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CHANGES_NEEDED)
        states = {i.addon_id: i.state for i in status.software.items}
        self.assertEqual(states[MODULE], SoftwareItemState.WRONG_ENABLED_STATE)
        self.assertEqual(states[DEMO], SoftwareItemState.WRONG_ENABLED_STATE)

    def test_05_wrong_skin_needs_changes(self):
        h = self.current()
        h.kodi.skin = "skin.estuary"
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CHANGES_NEEDED)
        self.assertEqual(status.skin, SkinStatus(
            AreaLevel.CHANGES_NEEDED, SKIN, "skin.estuary", False))

    def test_06_configuration_drift_needs_changes(self):
        h = self.current()
        h.config_backend.settings[(DEMO, "quality")] = "low"
        h.config_backend.files["userdata/keymaps/demo.xml"] = b"<other/>"
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CHANGES_NEEDED)
        self.assertEqual(status.configuration,
                         ConfigurationStatus(AreaLevel.CHANGES_NEEDED, 3, 2, 0))
        self.assertEqual(status.software.level, AreaLevel.CURRENT)

    def test_07_configuration_unavailable_is_never_current(self):
        for how in ("unreadable", "package_failure"):
            with self.subTest(how=how):
                h = self.current()
                if how == "unreadable":
                    h.config_backend.unreadable.add((DEMO, "quality"))
                else:
                    class Broken:
                        def resolve(self, config):
                            raise RuntimeError("SENTINEL_BACKEND_ERROR_TEXT " + SECRET)
                    status = h.service(config_loader=Broken()).check(h.target())
                    self.assertEqual(status.configuration.level, AreaLevel.UNAVAILABLE)
                    self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
                    self.assertIn(CheckGap.CONFIGURATION_UNAVAILABLE, status.gaps)
                    self.assertSecretFree(safe_text(status), h.logs)
                    continue
                status = h.check()
                self.assertEqual(status.configuration.level, AreaLevel.UNAVAILABLE)
                self.assertEqual(status.configuration.unreadable, 1)
                self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
                self.assertIn(CheckGap.CONFIGURATION_UNAVAILABLE, status.gaps)
                self.assertNotEqual(status.overall, OverallStatus.CURRENT)

    def test_08_private_resource_current_returns_safe_current(self):
        h = self.current()
        spy = []
        real = RedLightSettingsAdapter.inspect

        def inspect(adapter, declaration, overlay):
            spy.append(overlay.values[0].value)       # the inspector really holds the secret
            return real(adapter, declaration, overlay)
        with patch.object(RedLightSettingsAdapter, "inspect", inspect):
            status = h.check()
        self.assertEqual(spy, [DB_SECRET])
        self.assertEqual(status.private.level, AreaLevel.CURRENT)
        self.assertSecretFree(safe_text(status), h.logs)

    def test_09_private_resource_drift_needs_changes_without_values(self):
        h = self.current()
        h.save_overlay(resource_value=DB_SECRET + "-different")
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CHANGES_NEEDED)
        self.assertEqual(status.private.level, AreaLevel.CHANGES_NEEDED)
        resource = [i for i in status.private.items if i.kind is PrivateItemKind.RESOURCE]
        self.assertEqual([i.level for i in resource], [AreaLevel.CHANGES_NEEDED])
        self.assertSecretFree(safe_text(status), h.logs)
        self.assertNotIn("different", safe_text(status))

    def test_09b_private_setting_drift_needs_changes_without_values(self):
        h = self.current()
        h.config_backend.settings[(DEMO, "api_token")] = "something-else"
        status = h.check()
        self.assertEqual(status.private.level, AreaLevel.CHANGES_NEEDED)
        self.assertEqual({(i.kind, i.level) for i in status.private.items},
                         {(PrivateItemKind.SETTINGS, AreaLevel.CHANGES_NEEDED),
                          (PrivateItemKind.RESOURCE, AreaLevel.CURRENT)})
        self.assertNotIn("something-else", safe_text(status))
        self.assertSecretFree(safe_text(status))

    def test_10_private_unavailable_is_never_current(self):
        cases = {}
        h = self.current(); h.overlay_store.path_for("status-overlay").unlink()
        cases["overlay missing"] = (h, CheckGap.PRIVATE_DATA_MISSING)
        h = self.current(); h.overlay_store.path_for("status-overlay").write_text("{not json")
        cases["overlay unreadable"] = (h, CheckGap.PRIVATE_DATA_UNUSABLE)
        h = self.current()
        h.save_overlay()
        h.overlay_store.save(PrivateOverlay("status-overlay", "another-build", (), resources=()))
        cases["overlay for another build"] = (h, CheckGap.PRIVATE_DATA_UNUSABLE)
        h = self.current(); h.db.unlink()
        cases["resource store absent"] = (h, None)
        for name, (harness, gap) in cases.items():
            with self.subTest(name):
                status = harness.check()
                self.assertNotEqual(status.overall, OverallStatus.CURRENT)
                self.assertNotEqual(status.private.level, AreaLevel.CURRENT)
                if gap is not None:
                    self.assertEqual(status.private.level, AreaLevel.UNAVAILABLE)
                    self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
                    self.assertIn(gap, status.gaps)
                self.assertSecretFree(safe_text(status), harness.logs)

    def test_10b_unsupported_resource_store_is_unavailable_not_drift(self):
        h = self.current()
        connection = sqlite3.connect(h.db)
        connection.execute("DROP TABLE settings")
        connection.execute("CREATE TABLE settings (only_column text)")
        connection.commit()
        connection.close()
        status = h.check()
        self.assertEqual(status.private.level, AreaLevel.UNAVAILABLE)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertIn(CheckGap.PRIVATE_UNAVAILABLE, status.gaps)

    def test_14_unmanaged_addons_do_not_affect_status(self):
        h = self.current()
        h.kodi.addons.update({
            "plugin.video.unmanaged": ("0.0.1", True), "script.module.other": ("0.0", False),
            "plugin.video.brand.new": ("5.0", True)})
        baseline = h.check()
        self.assertEqual(baseline.overall, OverallStatus.CURRENT)
        self.assertNotIn("plugin.video.unmanaged", {i.addon_id for i in baseline.software.items})
        self.assertNotIn("plugin.video.brand.new", safe_text(baseline))

    def test_skipped_addon_is_not_managed_and_fallback_version_is_current(self):
        h = self.current()
        del h.kodi.addons[MODULE]
        skip = InstallResolutionRecord(MODULE, "2.0.0", InstallResolution.SKIPPED,
                                       ResolutionState.SKIPPED)
        status = h.check(install_resolution=h.resolution(skip))
        self.assertNotIn(MODULE, {i.addon_id for i in status.software.items})
        self.assertEqual(status.overall, OverallStatus.CURRENT)
        h = self.current()
        h.kodi.addons[MODULE] = ("2.0.1", True)
        fallback = InstallResolutionRecord(
            MODULE, "2.0.0", InstallResolution.REPOSITORY_CURRENT, ResolutionState.INSTALLED,
            repository_id="repository.demo", resolved_version="2.0.1",
            artifact_sha256="b" * 64, artifact_size=10)
        self.assertEqual(h.check(install_resolution=h.resolution(fallback)).overall, OverallStatus.CURRENT)

    def test_incomplete_capture_node_is_uncheckable_not_current(self):
        h = self.current()
        h.frozen = frozen_manifest(extra=(
            _node("plugin.video.partial", "1.0", status=CaptureStatus.INCOMPLETE_ARTIFACT),))
        h.kodi.addons["plugin.video.partial"] = ("1.0", True)
        status = h.check()
        self.assertEqual({i.addon_id: i.state for i in status.software.items}[
            "plugin.video.partial"], SoftwareItemState.UNCHECKABLE)
        self.assertEqual(status.software.level, AreaLevel.UNAVAILABLE)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)

    def test_dependency_of_managed_addon_missing_is_reported(self):
        h = self.current()

        class Needs(FakeDeps):
            def read_addon_xml(self, addon_id):
                if addon_id == DEMO:
                    return (b'<addon id="plugin.video.demo" version="1.0.0"><requires>'
                            b'<import addon="script.module.needed" version="1.0"/>'
                            b'</requires></addon>')
                return super().read_addon_xml(addon_id)
        h.deps = Needs(dict(h.kodi.addons))
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CHANGES_NEEDED)
        self.assertEqual({i.addon_id: i.state for i in status.software.items}[
            "script.module.needed"], SoftwareItemState.MISSING)

    def test_build_without_private_data_or_skin_marks_areas_not_applicable(self):
        h = Harness(self, with_private=False, with_resource=False)
        h.rebuild()
        h.desired = replace(h.desired, skin=None)
        status = h.check()
        self.assertEqual(status.private.level, AreaLevel.NOT_APPLICABLE)
        self.assertEqual(status.skin.level, AreaLevel.NOT_APPLICABLE)
        self.assertEqual(status.overall, OverallStatus.CURRENT)

    def test_optional_absent_overlay_is_not_applicable_but_required_is_unavailable(self):
        h = Harness(self, with_resource=False)
        h.desired = replace(h.desired, private_overlay=PrivateOverlayRef(
            "local_file", overlay_id="status-overlay", required=False),
            config=replace(h.desired.config, private_settings=(
                PrivateSettingDeclaration(DEMO, "api_token", "string", False, "token"),)))
        self.assertEqual(h.check().private.level, AreaLevel.NOT_APPLICABLE)

    def test_without_frozen_manifest_overlay_binds_to_build_identity(self):
        h = self.current(with_frozen=False)
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CURRENT)


class OperationState(StatusBase):
    def test_11_restart_pending_requires_restart(self):
        for how in ("restart", "frozen"):
            with self.subTest(how):
                h = self.current()
                if how == "restart":
                    h.restart_transaction()
                else:
                    h.frozen_transaction(FrozenInstallPhase.AWAITING_RESTART,
                                         hold=(REDLIGHT_ADDON_ID,), released=False)
                status = h.check()
                self.assertEqual(status.overall, OverallStatus.RESTART_REQUIRED)
                self.assertEqual(status.operation.kind, OperationKind.RESTART_REQUIRED)
                self.assertEqual(status.operation.code, OperationCode.AWAITING_RESTART)
                self.assertEqual(status.operation.protection_active, how == "frozen")

    def test_12_needs_attention_is_reported_and_outranks_restart(self):
        h = self.current()
        h.restart_transaction(TransactionPhase.NEEDS_ATTENTION, status_code="SOME_PRODUCT_CODE")
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.NEEDS_ATTENTION)
        self.assertEqual(status.operation.code, OperationCode.OPERATION_NOT_FINISHED)
        self.assertEqual(status.operation.status_code, "SOME_PRODUCT_CODE")
        h = self.current()
        h.restart_transaction()
        h.frozen_transaction(FrozenInstallPhase.NEEDS_ATTENTION)
        self.assertEqual(h.check().overall, OverallStatus.NEEDS_ATTENTION)

    def test_interrupted_and_post_restart_states_need_attention(self):
        for phase in (FrozenInstallPhase.INSTALLING_SOFTWARE, FrozenInstallPhase.CONFIGURING,
                      FrozenInstallPhase.RESUMING, FrozenInstallPhase.VALIDATING):
            with self.subTest(phase):
                h = self.current()
                h.frozen_transaction(phase)
                status = h.check()
                self.assertEqual(status.overall, OverallStatus.NEEDS_ATTENTION)
                self.assertEqual(status.operation.code, OperationCode.OPERATION_NOT_FINISHED)
        h = self.current()
        h.restart_transaction(session_id=SESSION_B)      # Kodi restarted; resume not finished
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.NEEDS_ATTENTION)
        self.assertEqual(status.operation.code, OperationCode.RESUME_PENDING)

    def test_malformed_state_is_needs_attention_and_io_failure_is_not_fully_checked(self):
        h = self.current()
        path = Path(TransactionStore(str(h.profile)).transaction_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        for invalid in (b'{"truncated": ', b"\x00\xff not utf8", b"[1, 2]"):
            path.write_bytes(invalid)
            status = h.check()
            self.assertEqual(status.overall, OverallStatus.NEEDS_ATTENTION, invalid)
            self.assertEqual(status.operation.code, OperationCode.TRANSACTION_INVALID)
        path.unlink()
        path.mkdir()                                    # a directory is not a state file
        self.assertEqual(h.check().operation.code, OperationCode.TRANSACTION_INVALID)
        path.rmdir()
        path.write_text("{}")
        os.chmod(path, 0)                               # present but cannot be read
        try:
            if os.geteuid() == 0:
                self.skipTest("root can read a mode-000 file")
            status = h.check()
        finally:
            os.chmod(path, 0o600)
        self.assertEqual(status.operation.kind, OperationKind.UNAVAILABLE)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertIn(CheckGap.OPERATION_STATE_UNAVAILABLE, status.gaps)

    def test_unknown_session_still_reports_the_pending_restart(self):
        h = self.current()
        h.restart_transaction(session_id=SESSION_B)
        status = h.service(session_id=lambda: "").check(h.target())
        self.assertEqual(status.overall, OverallStatus.RESTART_REQUIRED)

    def test_hostile_status_code_is_dropped(self):
        h = self.current()
        h.restart_transaction(TransactionPhase.NEEDS_ATTENTION,
                              status_code="lowercase path /Users/x secret")
        self.assertEqual(h.check().operation.status_code, "")

    def test_no_transaction_leaves_no_operation_state(self):
        status = self.current().check()
        self.assertEqual((status.operation.kind, status.operation.protection_active),
                         (OperationKind.NONE, False))


class FailureSemantics(StatusBase):
    def test_13_inspection_exception_is_sanitized_and_not_current(self):
        h = self.current()

        class Boom:
            def inspect(self):
                raise RuntimeError("SENTINEL_BACKEND_ERROR_TEXT " + SECRET)
        status = h.service(inspector=Boom()).check(h.target())
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertEqual(status.software.level, AreaLevel.UNAVAILABLE)
        self.assertEqual(status.skin.level, AreaLevel.UNAVAILABLE)
        self.assertEqual(status.configuration.level, AreaLevel.UNAVAILABLE)
        self.assertIn(CheckGap.KODI_STATE_UNAVAILABLE, status.gaps)
        self.assertSecretFree(safe_text(status), h.logs)
        self.assertTrue(any("RuntimeError" in line for line in h.logs))

    def test_every_phase_failure_is_contained(self):
        h = self.current()
        for name in ("manifest_loader", "resolver", "frozen_manifest_loader", "overlay_loader",
                     "restart_snapshot", "frozen_snapshot"):
            def boom(*a, **k):
                raise RuntimeError("SENTINEL_BACKEND_ERROR_TEXT " + SECRET)
            with self.subTest(name):
                status = h.service(**{name: boom}).check(h.target())
                self.assertNotEqual(status.overall, OverallStatus.CURRENT)
                self.assertSecretFree(safe_text(status), h.logs)

    def test_unreadable_build_files_are_not_fully_checked(self):
        h = self.current()
        h.resolver_failure = ValueError("/Users/eric/private.json " + SECRET)
        status = h.service().check(h.target())
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertIn(CheckGap.BUILD_UNREADABLE, status.gaps)
        self.assertSecretFree(safe_text(status), h.logs)
        self.assertNotIn("/Users", safe_text(status))

    def test_no_selected_build_is_never_healthy(self):
        h = self.current()
        status = h.service().check(None)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertFalse(status.build_selected)
        self.assertEqual(status.gaps, (CheckGap.NO_BUILD_SELECTED,))
        self.assertTrue(all(status.area(a) is AreaLevel.UNAVAILABLE for a in StatusArea))
        # but a pending restart is still reported without a build
        h.restart_transaction()
        self.assertEqual(h.service().check(None).overall, OverallStatus.RESTART_REQUIRED)

    def test_check_never_raises(self):
        class Hostile:
            def __getattr__(self, name):
                raise RuntimeError("SENTINEL_BACKEND_ERROR_TEXT")
        h = self.current()
        status = h.service(inspector=Hostile(), config_loader=Hostile(),
                           configuration_inspector=Hostile(), dependency_resolver=Hostile()
                           ).check(h.target())
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)

    def test_a_check_is_always_a_fresh_read(self):
        h = self.current()
        service = h.service()
        service.check(h.target())
        self.assertEqual(h.kodi.calls, 1)
        h.kodi.addons[MODULE] = ("0.0", True)
        self.assertEqual(service.check(h.target()).overall, OverallStatus.CHANGES_NEEDED)
        self.assertEqual(h.kodi.calls, 2)
        h.kodi.addons[MODULE] = ("2.0.0", True)
        self.assertEqual(service.check(h.target()).overall, OverallStatus.CURRENT)
        self.assertEqual(h.kodi.calls, 3)


class Precedence(unittest.TestCase):
    def levels(self, **given):
        base = {a: AreaLevel.CURRENT for a in StatusArea}
        base.update({StatusArea[k.upper()]: v for k, v in given.items()})
        return base

    def test_documented_precedence(self):
        none = OperationStatus()
        attention = OperationStatus(OperationKind.NEEDS_ATTENTION, OperationCode.OPERATION_NOT_FINISHED)
        restart = OperationStatus(OperationKind.RESTART_REQUIRED, OperationCode.AWAITING_RESTART)
        unavailable = OperationStatus(OperationKind.UNAVAILABLE, OperationCode.TRANSACTION_UNREADABLE)
        changes = self.levels(software=AreaLevel.CHANGES_NEEDED)
        unchecked = self.levels(private=AreaLevel.UNAVAILABLE)
        table = [
            ((True, self.levels(), none), OverallStatus.CURRENT),
            ((True, self.levels(skin=AreaLevel.NOT_APPLICABLE), none), OverallStatus.CURRENT),
            ((True, unchecked, none), OverallStatus.INCOMPLETE),
            ((True, self.levels(), unavailable), OverallStatus.INCOMPLETE),
            ((False, self.levels(), none), OverallStatus.INCOMPLETE),
            ((True, changes, none), OverallStatus.CHANGES_NEEDED),
            ((True, {**changes, StatusArea.PRIVATE: AreaLevel.UNAVAILABLE}, none),
             OverallStatus.CHANGES_NEEDED),                 # proven drift beats "not checked"
            ((True, changes, unavailable), OverallStatus.CHANGES_NEEDED),
            ((True, changes, restart), OverallStatus.RESTART_REQUIRED),
            ((True, unchecked, restart), OverallStatus.RESTART_REQUIRED),
            ((True, changes, attention), OverallStatus.NEEDS_ATTENTION),
            ((True, self.levels(), attention), OverallStatus.NEEDS_ATTENTION),
        ]
        for args, expected in table:
            self.assertEqual(combine_overall(*args), expected, args)


# -- zero mutation ----------------------------------------------------------------------

class ZeroMutation(StatusBase):
    def test_15_status_calls_no_mutating_owner_in_any_state(self):
        scenarios = {
            "current": lambda h: None,
            "drift": lambda h: h.kodi.addons.pop(MODULE),
            "restart": lambda h: h.restart_transaction(),
            "frozen hold": lambda h: h.frozen_transaction(
                FrozenInstallPhase.AWAITING_RESTART, hold=(REDLIGHT_ADDON_ID,), released=False),
            "attention": lambda h: h.frozen_transaction(FrozenInstallPhase.NEEDS_ATTENTION),
        }
        for name, arrange in scenarios.items():
            with self.subTest(name):
                h = self.current()
                arrange(h)
                h.check()                      # Harness.check asserts every tripwire is untouched
                self.assertTrue(h.config_backend.reads)
                self.assertEqual(h.touched, [])

    def test_the_instrumentation_is_live(self):
        h = self.current()
        with h.instrumented():
            for call in (lambda: TransactionStore(str(h.profile)).inspect(),
                         lambda: FrozenInstallStore(h.frozen_root),
                         lambda: config_module.ConfigurationManager(h.config_backend).apply(
                             h.effective),
                         lambda: private_overlay.PrivateOverlayStore(h.profile).save(None),
                         lambda: RedLightSettingsAdapter(h.profile).apply(None, None)):
                with self.assertRaises(AssertionError):
                    call()
        self.assertEqual(len(h.touched), 5)
        self.assertEqual(h.touched[0], "TransactionStore.inspect")

    def test_state_and_files_are_identical_before_and_after(self):
        h = self.current()
        h.restart_transaction()
        h.frozen_transaction(FrozenInstallPhase.AWAITING_RESTART, hold=(REDLIGHT_ADDON_ID,),
                             released=False)
        before = snapshot_tree(h.profile)
        kodi_before = dict(h.kodi.addons)
        settings_before = (dict(h.config_backend.settings), dict(h.config_backend.files))
        for _ in range(2):
            h.check()
        self.assertEqual(snapshot_tree(h.profile), before)
        self.assertEqual(h.kodi.addons, kodi_before)
        self.assertEqual((h.config_backend.settings, h.config_backend.files), settings_before)

    def test_no_lock_file_or_directory_is_created(self):
        h = Harness(self, with_private=False, with_resource=False)
        before = snapshot_tree(h.profile)
        h.check(h.target(software_manifest_path=""))
        self.assertEqual(snapshot_tree(h.profile), before)
        self.assertFalse((h.frozen_root).exists())
        self.assertEqual(list(h.profile.rglob("*.lock")), [])

    def test_status_does_not_wait_on_a_held_operation_lock(self):
        import fcntl
        h = self.current()
        h.restart_transaction()
        lock = open(TransactionStore(str(h.profile)).lock_path, "a+")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(h.check().overall, OverallStatus.RESTART_REQUIRED)
        finally:
            lock.close()

    def test_status_never_sets_the_kodi_session_property(self):
        window = SimpleNamespace(props={}, getProperty=lambda k: "", setProperty=lambda k, v: (
            _ for _ in ()).throw(AssertionError("session property written")))
        self.assertEqual(peek_current_kodi_session_id(window=window), "")
        window.getProperty = lambda k: SESSION_A
        self.assertEqual(peek_current_kodi_session_id(window=window), SESSION_A)
        window.getProperty = lambda k: "not-a-uuid"
        self.assertEqual(peek_current_kodi_session_id(window=window), "")

    def test_service_module_never_reaches_a_mutating_owner(self):
        tree = ast.parse((ROOT / "resources/lib/status.py").read_text())
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("build_manager", "addons", "repository", "addon_state", "skin",
                       "restart_coordinator", "resume", "update_guard", "artifacts",
                       "installed_addon_source", "verified_addon_imports"):
            self.assertNotIn("resources.lib." + banned, modules)
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        for banned in ("BuildManager", "ConfigurationManager", "PrivateOverlayManager",
                       "AddonManager", "RepositoryManager", "SkinActivator", "AddonStateReconciler",
                       "FrozenInstallCoordinator", "ResumeCoordinator", "RestartCoordinator",
                       "AddonUpdateGuard", "DependencyAwareInstaller",
                       "get_current_kodi_session_id", "active_activation_hold_ids"):
            self.assertNotIn(banned, names)
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("install", "uninstall", "apply", "apply_settings", "activate", "reconcile",
                     "enable", "disable", "set_setting", "set_skin_setting", "write_file",
                     "set_addon_enabled", "set_policy", "create", "clear", "clear_expected",
                     "save", "transition_expected", "rearm_held_quiescence", "acquire",
                     "release", "retry_held_quiescence", "resume", "abandon", "initialize",
                     "capture", "inspect_locked", "locked", "mkdir", "makedirs", "unlink",
                     "write", "write_text", "write_bytes", "rename", "replace", "remove"):
            self.assertNotIn(verb, called)

    def test_read_only_views_cannot_reach_a_writer(self):
        backend = FakeConfigBackend()
        view = ReadOnlyConfigurationBackend(backend)
        for name in ("set_setting", "set_skin_setting", "write_file", "_backend"):
            self.assertFalse(hasattr(view, name), name)
        with self.assertRaises(AttributeError):
            view.set_setting = lambda *a: None
        with self.assertRaises(TypeError):
            ConfigurationInspector(backend)
        deps = _ReadOnlyDependencyBackend(FakeDeps({}))
        with self.assertRaises(RuntimeError):
            deps.install_addon("x")
        with self.assertRaises(RuntimeError):
            deps.set_addon_enabled("x", True)

    def test_configuration_inspector_reports_status_only(self):
        backend = FakeConfigBackend({(DEMO, "quality"): "high", (DEMO, "n"): 2.0},
                                    files={"a.xml": b"x"}, unreadable={(DEMO, "gone")})
        inspector = ConfigurationInspector(ReadOnlyConfigurationBackend(backend))
        effective = EffectiveConfiguration(
            packages=("p",),
            settings=(ConfigSetting(DEMO, "quality", ConfigSettingType.STRING, "high", "p"),
                      ConfigSetting(DEMO, "n", ConfigSettingType.NUMBER, 3.0, "p"),
                      ConfigSetting(DEMO, "gone", ConfigSettingType.STRING, SECRET, "p")),
            files=(ConfigFile("a.xml", "a", b"x", "p"), ConfigFile("b.xml", "b", b"y", "p")))
        result = inspector.inspect(effective)
        self.assertEqual((result.total, result.matching, result.differing, result.unreadable),
                         (5, 2, 2, 1))
        self.assertEqual(backend.mutations, [])
        self.assertNotIn(SECRET, repr(result))
        self.assertEqual(result.validation_state.verified_files, ("a.xml",))


# -- privacy --------------------------------------------------------------------------------

class Privacy(StatusBase):
    def test_secrets_never_enter_result_logs_or_serialized_evidence(self):
        for mutate in (lambda h: None,
                       lambda h: h.save_overlay(resource_value=DB_SECRET + "x"),
                       lambda h: h.config_backend.settings.update({(DEMO, "api_token"): "z"})):
            h = self.current()
            mutate(h)
            status = h.check()
            blob = safe_text(status) + "\n".join(h.logs) + json.dumps(status.to_safe_dict())
            self.assertSecretFree(blob)
            self.assertIn("Build Status check", "\n".join(h.logs))

    def test_status_types_have_no_field_that_can_carry_free_text(self):
        for kwargs in (
            dict(addon_id="plugin x; rm -rf", state=SoftwareItemState.CURRENT),
            dict(addon_id=SECRET + "/..", state=SoftwareItemState.CURRENT),
            dict(addon_id=DEMO, state="current"),
            dict(addon_id=DEMO, state=SoftwareItemState.CURRENT, display_name="a\nb"),
            dict(addon_id=DEMO, state=SoftwareItemState.CURRENT, display_name="x" * 65),
        ):
            with self.assertRaises(ValueError, msg=kwargs):
                SoftwareItem(**kwargs)
        for bad in ("../x", "has space", "A" * 200, 7):
            with self.assertRaises(ValueError):
                SkinStatus(AreaLevel.CURRENT, bad)
        for bad in ({"token": SECRET}, SECRET, True, -1, 10 ** 9):
            with self.assertRaises(ValueError):
                ConfigurationStatus(AreaLevel.CURRENT, bad)
        with self.assertRaises(ValueError):
            PrivateItem("redlight.settings", PrivateItemKind.RESOURCE, "current")
        with self.assertRaises(ValueError):
            PrivateItem(SECRET.upper(), PrivateItemKind.RESOURCE, AreaLevel.CURRENT)
        with self.assertRaises(ValueError):
            OperationStatus(OperationKind.NONE, OperationCode.AWAITING_RESTART)
        with self.assertRaises(ValueError):
            OperationStatus(OperationKind.NEEDS_ATTENTION, OperationCode.RESUME_PENDING,
                            status_code="a secret value")

    def test_a_status_with_unchecked_or_changed_areas_cannot_claim_to_be_current(self):
        good = dict(checked_at=NOW, build_selected=True, software=SoftwareStatus(AreaLevel.CURRENT),
                    skin=SkinStatus(AreaLevel.CURRENT), configuration=ConfigurationStatus(AreaLevel.CURRENT),
                    private=PrivateStatus(AreaLevel.CURRENT), operation=OperationStatus())
        BuildStatus(overall=OverallStatus.CURRENT, **good)
        for area, value in (("software", SoftwareStatus(AreaLevel.UNAVAILABLE)),
                            ("skin", SkinStatus(AreaLevel.CHANGES_NEEDED)),
                            ("configuration", ConfigurationStatus(AreaLevel.UNAVAILABLE)),
                            ("private", PrivateStatus(AreaLevel.UNAVAILABLE)),
                            ("operation", OperationStatus(OperationKind.RESTART_REQUIRED,
                                                          OperationCode.AWAITING_RESTART))):
            with self.assertRaises(ValueError, msg=area):
                BuildStatus(overall=OverallStatus.CURRENT, **{**good, area: value})
        with self.assertRaises(ValueError):
            BuildStatus(overall=OverallStatus.CURRENT, gaps=(CheckGap.NO_BUILD_SELECTED,), **good)
        with self.assertRaises(ValueError):
            BuildStatus(overall=OverallStatus.CURRENT, **{**good, "checked_at": "yesterday"})

    def test_display_names_are_sanitized_and_optional(self):
        h = self.current()
        names = {DEMO: "Demo \x1b[31mAddon\x00\n" + "x" * 80, MODULE: None}
        status = h.service(name_resolver=lambda addon_id: names.get(addon_id)).check(h.target())
        item = {i.addon_id: i for i in status.software.items}
        self.assertNotIn("\x1b", item[DEMO].display_name)
        self.assertLessEqual(len(item[DEMO].display_name), 64)
        self.assertEqual(item[MODULE].label, MODULE)
        self.assertEqual(status.overall, OverallStatus.CURRENT)

        def boom(addon_id):
            raise RuntimeError(SECRET)
        status = h.service(name_resolver=boom).check(h.target())
        self.assertEqual(status.overall, OverallStatus.CURRENT)
        self.assertSecretFree(safe_text(status))

    def test_real_overlay_secret_sits_in_the_overlay_file_but_not_in_any_output(self):
        h = self.current()
        self.assertIn(SECRET, h.overlay_store.path_for("status-overlay").read_text())
        status = h.check()
        self.assertSecretFree(safe_text(status), h.logs, status.to_safe_dict())


# -- read-only owner additions ------------------------------------------------------------------

class ReadOnlySnapshots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = TransactionStore(self.tmp.name)

    def test_absent_record_creates_nothing(self):
        self.assertIsNone(self.store.read_snapshot())
        self.assertEqual(list(Path(self.tmp.name).rglob("*")), [])
        self.assertIsNone(FrozenInstallStore.read_snapshot(Path(self.tmp.name) / "none"))
        self.assertFalse((Path(self.tmp.name) / "none").exists())

    def test_snapshot_matches_the_locked_inspection(self):
        h = Harness.__new__(Harness)
        Harness.__init__(h, self, with_private=False, with_resource=False)
        h.restart_transaction()
        store = TransactionStore(str(h.profile))
        self.assertEqual(store.read_snapshot(), store.inspect())

    def test_unsafe_record_shapes_are_invalid_state_not_followed(self):
        path = Path(self.store.transaction_path)
        path.parent.mkdir(parents=True)
        os.mkfifo(path)                                  # would block a naive open() forever
        with self.assertRaises(TransactionCorrupt):
            self.store.read_snapshot()
        path.unlink()
        target = path.parent / "elsewhere"
        target.write_text("{}")
        path.symlink_to(target)
        with self.assertRaises(TransactionCorrupt):
            self.store.read_snapshot()
        path.unlink()
        path.write_bytes(b"{" + b" " * (200 * 1024) + b"}")
        with self.assertRaises(TransactionCorrupt):
            self.store.read_snapshot()
        path.write_text("[1, 2]")
        with self.assertRaises(transaction.TransactionError):
            self.store.read_snapshot()
        path.write_text("{ nope")
        with self.assertRaises(TransactionCorrupt):
            self.store.read_snapshot()

    def test_a_present_but_unreadable_record_is_an_io_failure(self):
        if os.geteuid() == 0:
            self.skipTest("root can read a mode-000 file")
        path = Path(self.store.transaction_path)
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        with self.assertRaises(transaction.TransactionPersistenceError):
            self.store.read_snapshot()

    def test_frozen_snapshot_distinguishes_unreadable_from_invalid(self):
        root = Path(self.tmp.name) / "frozen"
        root.mkdir()
        record = root / "frozen_install_transaction.json"
        record.write_text("{ nope")
        with self.assertRaises(frozen_install.FrozenInstallValidationError):
            FrozenInstallStore.read_snapshot(root)
        record.unlink()
        record.mkdir()                                   # a directory is invalid state
        with self.assertRaises(frozen_install.FrozenInstallValidationError):
            FrozenInstallStore.read_snapshot(root)
        record.rmdir()
        if os.geteuid() != 0:
            record.write_text("{}")
            os.chmod(record, 0)
            self.addCleanup(os.chmod, record, 0o600)
            with self.assertRaises(frozen_install.FrozenInstallStateUnreadable):
                FrozenInstallStore.read_snapshot(root)

    def test_resource_manager_inspect_returns_status_only(self):
        profile = Path(self.tmp.name) / "p"
        db = build_db(profile)
        manager = StructuredPrivateResourceManager(
            {RedLightSettingsAdapter.adapter_id: RedLightSettingsAdapter(profile)})
        declaration = redlight_resource_declaration()

        def overlay(value):
            return StructuredPrivateResourceOverlay(
                REDLIGHT_RESOURCE_ID, REDLIGHT_ADDON_ID, "2.6.8", REDLIGHT_SCHEMA_ID,
                (StructuredPrivateValue("trakt.token", "string", value),))
        (current,) = manager.inspect((declaration,), (overlay(DB_SECRET),))
        (drift,) = manager.inspect((declaration,), (overlay("different-" + SECRET),))
        (absent,) = manager.inspect((declaration,), ())
        self.assertEqual((current.status, drift.status, absent.status),
                         (ResourceCheckStatus.CURRENT, ResourceCheckStatus.CHANGES_NEEDED,
                          ResourceCheckStatus.UNAVAILABLE))        # required overlay is missing
        self.assertEqual(current.resource_id, REDLIGHT_RESOURCE_ID)
        for check in (current, drift, absent):
            self.assertNotIn(SECRET, repr(check))
            self.assertNotIn(DB_SECRET, repr(check))
        self.assertEqual(StructuredPrivateResourceManager().inspect(
            (declaration,), (overlay(DB_SECRET),))[0].status, ResourceCheckStatus.UNAVAILABLE)
        db.unlink()
        self.assertEqual(manager.inspect((declaration,), (overlay(DB_SECRET),))[0].status,
                         ResourceCheckStatus.CHANGES_NEEDED)

    def test_inspect_never_writes_resource_sidecars(self):
        profile = Path(self.tmp.name) / "p"
        build_db(profile)
        before = snapshot_tree(profile)
        manager = StructuredPrivateResourceManager(
            {RedLightSettingsAdapter.adapter_id: RedLightSettingsAdapter(profile)})
        overlay = StructuredPrivateResourceOverlay(
            REDLIGHT_RESOURCE_ID, REDLIGHT_ADDON_ID, "2.6.8", REDLIGHT_SCHEMA_ID,
            (StructuredPrivateValue("trakt.token", "string", DB_SECRET),))
        manager.inspect((redlight_resource_declaration(),), (overlay,))
        self.assertEqual(snapshot_tree(profile), before)


class IndependentReviewRegressions(StatusBase):
    """Each test reproduces a defect an independent review confirmed."""

    def test_status_never_consults_repositories_or_the_network(self):
        h = self.current()
        del h.kodi.addons[MODULE]
        del h.deps.installed[MODULE]
        status = h.check()                       # check() asserts no repository read, no network
        self.assertEqual({i.addon_id: i.state for i in status.software.items}[MODULE],
                         SoftwareItemState.MISSING)
        self.assertEqual(h.deps.repository_reads, [])

    def test_an_installed_addons_unreadable_metadata_is_not_papered_over_by_a_repository(self):
        h = self.current()
        h.deps.broken_xml.add(DEMO)
        status = h.check()
        self.assertEqual(h.deps.repository_reads, [])
        self.assertEqual({i.addon_id: i.state for i in status.software.items}[DEMO],
                         SoftwareItemState.UNCHECKABLE)
        self.assertEqual(status.software.level, AreaLevel.UNAVAILABLE)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)

    def test_a_selected_build_that_lists_nothing_is_not_healthy(self):
        h = Harness(self, with_private=False, with_resource=False)
        h.desired = replace(h.desired, addons=(), skin=None, config=None, private_overlay=None)
        status = h.service().check(h.target(software_manifest_path=""))
        self.assertTrue(all(status.area(a) is AreaLevel.NOT_APPLICABLE for a in StatusArea))
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertEqual(status.gaps, (CheckGap.NOTHING_TO_COMPARE,))

    def test_an_incomplete_frozen_capture_is_not_a_whole_build(self):
        gap = "plugin.video.gap"
        for capture, skipped, expected in (
                (CaptureStatus.INCOMPLETE_PROVENANCE, False, AreaLevel.UNAVAILABLE),
                (CaptureStatus.INCOMPLETE_ARTIFACT, False, AreaLevel.UNAVAILABLE),
                (CaptureStatus.INCOMPLETE_PROVENANCE, True, AreaLevel.UNAVAILABLE),
                (CaptureStatus.INCOMPLETE_ARTIFACT, True, AreaLevel.CURRENT)):
            with self.subTest(capture=capture, skipped=skipped):
                h = Harness(self)
                h.frozen = replace(frozen_manifest(extra=(
                    _node(gap, "1.0", status=CaptureStatus.INCOMPLETE_ARTIFACT),)),
                    capture_status=capture)
                h.kodi.addons[gap] = ("1.0", True)
                h.save_overlay()
                extra = {}
                if skipped:
                    h.desired = replace(h.desired, frozen_install_policies=(
                        FrozenInstallPolicy(gap, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP),))
                    extra["install_resolution"] = h.resolution(InstallResolutionRecord(
                        gap, "1.0", InstallResolution.SKIPPED, ResolutionState.SKIPPED))
                status = h.check(**extra)
                self.assertEqual(status.software.level, expected)
                if expected is AreaLevel.UNAVAILABLE:
                    self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
                    self.assertIn(CheckGap.SOFTWARE_UNAVAILABLE, status.gaps)

    def test_a_dependency_cycle_does_not_turn_drift_into_not_checked(self):
        h = self.current()

        class Cycle(FakeDeps):
            def read_addon_xml(self, addon_id):
                other = {DEMO: REDLIGHT_ADDON_ID, REDLIGHT_ADDON_ID: DEMO}.get(addon_id)
                if other is None:
                    return super().read_addon_xml(addon_id)
                return ('<addon id="%s" version="1"><requires><import addon="%s" version="1"/>'
                        '</requires></addon>' % (addon_id, other)).encode()
        h.kodi.addons[DEMO] = ("1.0.0", False)
        h.deps = Cycle(dict(h.kodi.addons))
        status = h.check()
        self.assertEqual({i.addon_id: i.state for i in status.software.items}[DEMO],
                         SoftwareItemState.WRONG_ENABLED_STATE)
        self.assertEqual(status.overall, OverallStatus.CHANGES_NEEDED)

    def test_a_large_healthy_build_is_reported_not_rejected(self):
        h = Harness(self)
        extra = tuple(_node("plugin.video.bulk%04d" % i, "1.0") for i in range(1000))
        h.frozen = frozen_manifest(extra=extra)
        h.save_overlay()                       # the overlay is bound to this exact software graph
        for node in extra:
            h.kodi.addons[node.addon_id] = ("1.0", True)
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CURRENT)
        self.assertGreater(len(status.software.items), 1000)

    def test_private_data_saved_for_a_different_software_graph_is_not_trusted(self):
        h = self.current()
        h.frozen = frozen_manifest(extra=(_node("plugin.video.other", "1.0"),))
        h.kodi.addons["plugin.video.other"] = ("1.0", True)
        status = h.check()
        self.assertEqual(status.private.level, AreaLevel.UNAVAILABLE)
        self.assertIn(CheckGap.PRIVATE_DATA_UNUSABLE, status.gaps)

    def test_an_accepted_skip_that_others_depend_on_is_not_reported_missing(self):
        h = self.current()

        class NeedsModule(FakeDeps):
            def read_addon_xml(self, addon_id):
                if addon_id == DEMO:
                    return (b'<addon id="plugin.video.demo" version="1.0.0"><requires>'
                            b'<import addon="script.module.demo" version="1.0"/></requires></addon>')
                return super().read_addon_xml(addon_id)
        del h.kodi.addons[MODULE]
        h.deps = NeedsModule(dict(h.kodi.addons))
        skip = InstallResolutionRecord(MODULE, "2.0.0", InstallResolution.SKIPPED,
                                       ResolutionState.SKIPPED)
        status = h.check(install_resolution=h.resolution(skip))
        self.assertNotIn(MODULE, {i.addon_id for i in status.software.items})
        self.assertEqual(status.overall, OverallStatus.CURRENT)

    def test_an_unnamed_active_skin_is_not_reported_as_a_different_skin(self):
        h = self.current()
        h.kodi.skin = ""
        status = h.check()
        self.assertEqual(status.skin.level, AreaLevel.UNAVAILABLE)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        del h.kodi.addons[SKIN]                 # not installed at all is proven drift
        self.assertEqual(h.check().skin.level, AreaLevel.CHANGES_NEEDED)

    def test_overlay_that_is_a_fifo_or_symlink_cannot_hang_or_be_followed(self):
        import threading
        h = self.current()
        path = h.overlay_store.path_for("status-overlay")
        copy = path.read_bytes()
        path.unlink()
        os.mkfifo(path)
        done = []
        thread = threading.Thread(target=lambda: done.append(h.service().check(h.target())))
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive(), "status hung on a FIFO overlay")
        self.assertEqual(done[0].private.level, AreaLevel.UNAVAILABLE)
        self.assertIn(CheckGap.PRIVATE_DATA_UNUSABLE, done[0].gaps)
        path.unlink()
        elsewhere = path.parent / "elsewhere.json"
        elsewhere.write_bytes(copy)
        path.symlink_to(elsewhere)
        self.assertEqual(h.service().check(h.target()).private.level, AreaLevel.UNAVAILABLE)

    def test_overlay_snapshot_matches_load(self):
        h = self.current()
        self.assertEqual(h.overlay_store.read_snapshot("status-overlay").fingerprint,
                         h.overlay_store.load("status-overlay").fingerprint)
        with self.assertRaises(private_overlay.PrivateOverlayMissingError):
            h.overlay_store.read_snapshot("nothing-here")
        h.overlay_store.path_for("status-overlay").write_text('{"overlay_id": 7}')
        with self.assertRaises(private_overlay.PrivateOverlayError):
            h.overlay_store.read_snapshot("status-overlay")

    def test_overlay_reference_the_applier_would_refuse_is_not_verified(self):
        h = self.current()
        h.desired = replace(h.desired, private_overlay=PrivateOverlayRef(
            "cloud_bucket", overlay_id="status-overlay", required=True))
        status = h.check()
        self.assertEqual(status.private.level, AreaLevel.UNAVAILABLE)
        self.assertIn(CheckGap.PRIVATE_DATA_UNUSABLE, status.gaps)
        h = self.current()
        h.desired = replace(h.desired, config=replace(
            h.desired.config, private_settings=(), structured_private_resources=()))
        self.assertEqual(h.check().private.level, AreaLevel.UNAVAILABLE)

    def test_markup_and_format_characters_cannot_reach_a_dialog_through_a_name(self):
        h = self.current()
        hostile = {
            DEMO: "[COLOR red]Demo[/COLOR][CR]\u2022 Skin \u2014 Current",
            MODULE: "$INFO[Window.Property(x)] \u202eevil\u2028name",
        }
        status = h.service(name_resolver=hostile.get).check(h.target())
        for item in status.software.items:
            for bad in "[]$\u202e\u2028":
                self.assertNotIn(bad, item.display_name)
        for bad in ("[COLOR]", "$INFO[x]", "a\u202eb", "a\u2028b", "a\x00b", "\ud800"):
            with self.assertRaises(ValueError):
                SoftwareItem(DEMO, SoftwareItemState.CURRENT, bad)
        SoftwareItem(DEMO, SoftwareItemState.CURRENT, "Demo 100% Videos (HD)")

    def test_the_current_invariant_covers_items_and_selection(self):
        good = dict(checked_at=NOW, build_selected=True, software=SoftwareStatus(AreaLevel.CURRENT),
                    skin=SkinStatus(AreaLevel.CURRENT), configuration=ConfigurationStatus(AreaLevel.CURRENT),
                    private=PrivateStatus(AreaLevel.CURRENT), operation=OperationStatus())
        for override in (
            {"build_selected": False},
            {"software": SoftwareStatus(AreaLevel.CURRENT,
                                        (SoftwareItem(DEMO, SoftwareItemState.MISSING),))},
            {"private": PrivateStatus(AreaLevel.CURRENT, (
                PrivateItem("redlight.settings", PrivateItemKind.RESOURCE, AreaLevel.UNAVAILABLE),))},
            {"software": SoftwareStatus(AreaLevel.NOT_APPLICABLE), "skin": SkinStatus(AreaLevel.NOT_APPLICABLE),
             "configuration": ConfigurationStatus(AreaLevel.NOT_APPLICABLE),
             "private": PrivateStatus(AreaLevel.NOT_APPLICABLE)},
        ):
            with self.assertRaises(ValueError, msg=sorted(override)):
                BuildStatus(overall=OverallStatus.CURRENT, **{**good, **override})

    def test_check_never_raises_even_when_the_clock_or_log_sink_does(self):
        h = self.current()

        def boom(*args):
            raise RuntimeError(SECRET)
        status = h.service(log=boom, clock=boom).check(h.target())
        self.assertEqual(status.overall, OverallStatus.CURRENT)
        self.assertRegex(status.checked_at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        status = h.service(log=boom).check(None)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)


class RedLightStatusProbe(unittest.TestCase):
    """The status read of a Red Light database leaves nothing behind."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name)
        self.db = build_db(self.profile)
        self.adapter = RedLightSettingsAdapter(self.profile)
        self.declaration = redlight_resource_declaration()

    def overlay(self, value=DB_SECRET):
        return StructuredPrivateResourceOverlay(
            REDLIGHT_RESOURCE_ID, REDLIGHT_ADDON_ID, "2.6.8", REDLIGHT_SCHEMA_ID,
            (StructuredPrivateValue("trakt.token", "string", value),))

    def status(self, value=DB_SECRET):
        manager = StructuredPrivateResourceManager({self.adapter.adapter_id: self.adapter})
        return manager.inspect((self.declaration,), (self.overlay(value),))[0].status

    def sidecars(self):
        for suffix in ("-shm", "-wal"):
            Path(str(self.db) + suffix).unlink(missing_ok=True)

    def test_quiet_database_is_read_without_touching_any_file(self):
        for label, drop in (("sidecars left behind", False), ("no sidecars", True)):
            with self.subTest(label):
                if drop:
                    self.sidecars()
                before = snapshot_tree(self.profile)
                self.assertEqual(self.status(), ResourceCheckStatus.CURRENT)
                self.assertEqual(self.status("other"), ResourceCheckStatus.CHANGES_NEEDED)
                self.assertEqual(snapshot_tree(self.profile), before)

    def test_a_wal_with_frames_is_not_inspected_and_nothing_is_touched(self):
        writer = sqlite3.connect(self.db)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("UPDATE settings SET setting_value = 'from-the-wal'")
        writer.commit()
        self.assertGreater(os.stat(str(self.db) + "-wal").st_size, 0)
        before = snapshot_tree(self.profile)
        for value in ("from-the-wal", DB_SECRET):
            self.assertEqual(self.status(value), ResourceCheckStatus.UNAVAILABLE)
        self.assertEqual(snapshot_tree(self.profile), before)    # -shm and -wal included
        writer.close()                                            # checkpoint on close
        writer = sqlite3.connect(self.db)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.close()
        self.assertEqual(self.status("from-the-wal"), ResourceCheckStatus.CURRENT)

    def test_a_crash_leftover_wal_without_shm_creates_nothing(self):
        writer = sqlite3.connect(self.db)
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("UPDATE settings SET setting_value = 'from-the-wal'")
        writer.commit()
        wal = Path(str(self.db) + "-wal")
        copy = Path(self.tmp.name) / "hot-copy"
        copy.mkdir()
        (copy / "settings.db").write_bytes(self.db.read_bytes())
        (copy / "settings.db-wal").write_bytes(wal.read_bytes())
        writer.close()
        profile = Path(self.tmp.name) / "crashed"
        target = profile / "addon_data" / REDLIGHT_ADDON_ID / "databases"
        target.mkdir(parents=True)
        for entry in copy.iterdir():
            (target / entry.name).write_bytes(entry.read_bytes())
        before = snapshot_tree(profile)
        adapter = RedLightSettingsAdapter(profile)
        manager = StructuredPrivateResourceManager({adapter.adapter_id: adapter})
        (check,) = manager.inspect((self.declaration,), (self.overlay("from-the-wal"),))
        self.assertEqual(check.status, ResourceCheckStatus.UNAVAILABLE)
        self.assertEqual(snapshot_tree(profile), before)
        self.assertFalse((target / "settings.db-shm").exists())

    def test_special_characters_in_the_profile_path_cannot_create_stray_files(self):
        for name in ("Media #2", "what?", "100%41", "a&b c"):
            with self.subTest(name):
                profile = Path(self.tmp.name) / name
                build_db(profile)
                adapter = RedLightSettingsAdapter(profile)
                manager = StructuredPrivateResourceManager({adapter.adapter_id: adapter})
                before = snapshot_tree(Path(self.tmp.name))
                (check,) = manager.inspect((self.declaration,), (self.overlay(),))
                self.assertEqual(check.status, ResourceCheckStatus.CURRENT)
                self.assertEqual(snapshot_tree(Path(self.tmp.name)), before)

    def test_non_wal_or_unsupported_database_is_unavailable_not_current(self):
        connection = sqlite3.connect(self.db)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.close()
        self.sidecars()
        before = snapshot_tree(self.profile)
        self.assertEqual(self.status(), ResourceCheckStatus.UNAVAILABLE)
        self.assertEqual(snapshot_tree(self.profile), before)

    def test_corrupt_database_is_unavailable(self):
        self.sidecars()
        self.db.write_bytes(b"not a database" * 100)
        self.assertEqual(self.status(), ResourceCheckStatus.UNAVAILABLE)

    def test_verify_keeps_its_original_behavior(self):
        result = self.adapter.verify(self.declaration, self.overlay())
        self.assertTrue(result.succeeded)
        self.assertFalse(self.adapter.verify(self.declaration, self.overlay("x")).succeeded)


if __name__ == "__main__":
    unittest.main()


# -- BM-UI-002C correction 1: the frozen graph must belong to the selected build ----------

class FrozenBuildIdentity(StatusBase):
    def other_build(self, h):
        """Build B's frozen manifest (same graph, so the saved private data still fits it)."""
        h.frozen = replace(h.frozen, build_id="another-build")

    def test_16_frozen_manifest_for_another_build_is_never_current(self):
        h = self.current()
        self.other_build(h)
        status = h.check()
        self.assertNotEqual(status.overall, OverallStatus.CURRENT)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertIn(CheckGap.BUILD_IDENTITY_MISMATCH, status.gaps)
        self.assertTrue(status.build_selected)

    def test_the_mismatched_graph_is_not_used_for_software_or_private_verification(self):
        h = self.current()
        # Build B's graph describes an extra add-on that is genuinely missing, and
        # the saved overlay is bound to that very graph: using either would report
        # drift or verify private data against the wrong build.
        h.frozen = replace(frozen_manifest(extra=(_node("plugin.video.other", "1.0"),)),
                           build_id="another-build")
        h.save_overlay()
        loaded = []
        with h.instrumented():
            service = h.service(overlay_loader=lambda overlay_id: loaded.append(overlay_id))
            status = service.check(h.target())
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertEqual(status.software.level, AreaLevel.UNAVAILABLE)
        self.assertEqual(status.software.items, ())
        self.assertEqual(status.private.level, AreaLevel.UNAVAILABLE)
        self.assertEqual(status.private.items, ())
        self.assertEqual(loaded, [])
        for area in StatusArea:
            self.assertEqual(status.area(area), AreaLevel.UNAVAILABLE, area)

    def test_the_mismatch_result_and_log_carry_only_a_stable_code(self):
        h = self.current()
        self.other_build(h)
        status = h.check()
        text = safe_text(status) + "\n".join(h.logs)
        self.assertNotIn("another-build", text)
        self.assertNotIn(BUILD_ID, text)
        self.assertNotIn(h.frozen.fingerprint(), text)
        self.assertNotIn("/frozen.json", text)
        self.assertIn("frozen_build_mismatch", "\n".join(h.logs))
        self.assertEqual(status.gaps, (CheckGap.BUILD_IDENTITY_MISMATCH,))

    def test_matching_build_ids_keep_the_normal_result(self):
        h = self.current()
        self.assertEqual(h.frozen.build_id, h.desired.build.id)
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.CURRENT)
        self.assertEqual(status.gaps, ())
        del h.kodi.addons[MODULE]
        self.assertEqual(h.check().overall, OverallStatus.CHANGES_NEEDED)

    def test_a_mismatch_is_reported_even_when_the_state_has_drift(self):
        h = self.current()
        self.other_build(h)
        del h.kodi.addons[MODULE]
        status = h.check()
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertEqual(status.software.items, ())


# -- BM-UI-002C correction 2: recorded install outcomes must be bound to this build ---------

class ResolutionIdentity(StatusBase):
    def skip(self, addon_id=MODULE, version="2.0.0", **kwargs):
        return InstallResolutionRecord(addon_id, version, InstallResolution.SKIPPED,
                                       ResolutionState.SKIPPED, **kwargs)

    def missing_module(self):
        h = self.current()
        del h.kodi.addons[MODULE]               # a genuinely missing managed add-on
        return h

    def code(self, h, resolution):
        with self.assertRaises(IdentityMismatch) as caught:
            bind_resolutions(BUILD_ID, h.frozen, resolution, policies=h.desired.frozen_install_policies)
        return caught.exception.code

    def assertRejected(self, h, resolution, code):
        self.assertEqual(self.code(h, resolution), code)
        status = h.check(install_resolution=resolution)
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertEqual(status.gaps, (CheckGap.RESOLUTION_IDENTITY_MISMATCH,))
        for area in StatusArea:
            self.assertEqual(status.area(area), AreaLevel.UNAVAILABLE, area)
        self.assertEqual(status.software.items, ())
        self.assertIn(code.value, "\n".join(h.logs))

    def test_policy_change_rejects_repository_version_and_skip(self):
        for skipped in (False, True):
            with self.subTest(skipped=skipped):
                h = self.current()
                if skipped:
                    del h.kodi.addons[MODULE]
                    record = self.skip()
                else:
                    h.kodi.addons[MODULE] = ("2.0.1", True)
                    record = InstallResolutionRecord(
                        MODULE, "2.0.0", InstallResolution.REPOSITORY_CURRENT, ResolutionState.INSTALLED,
                        repository_id="repository.demo", resolved_version="2.0.1",
                        artifact_sha256="b" * 64, artifact_size=10)
                original = h.desired
                resolution = h.resolution(record)
                self.assertEqual(h.check(install_resolution=resolution).overall, OverallStatus.CURRENT)
                h.desired = replace(original, frozen_install_policies=())
                before = snapshot_tree(h.profile)
                with h.instrumented():
                    self.assertRejected(h, resolution, IdentityCode.RESOLUTION_PLAN_MISMATCH)
                self.assertEqual(before, snapshot_tree(h.profile))
                self.assertEqual(h.touched, [])
                self.assertEqual(h.check().overall, OverallStatus.CHANGES_NEEDED)
                self.assertIn(MODULE, {item.addon_id for item in h.check().software.items})
                h.desired = original
                self.assertEqual(h.check(install_resolution=resolution).overall, OverallStatus.CURRENT)

    def test_03_unbound_raw_records_cannot_be_trusted(self):
        h = self.missing_module()
        for raw in ((self.skip(),), [self.skip()], self.skip(), {MODULE: self.skip()}):
            with self.assertRaises(ValueError):
                StatusTarget("/b.json", "d", install_resolution=raw)
        with self.assertRaises(TypeError):
            StatusTarget("/b.json", "d", install_resolutions=(self.skip(),))
        self.assertEqual(self.code(h, (self.skip(),)), IdentityCode.RESOLUTION_INVALID)
        self.assertFalse(hasattr(StatusTarget("/b.json", "d"), "install_resolutions"))
        # the record is real, but nothing binds it to this build
        self.assertEqual(h.check().overall, OverallStatus.CHANGES_NEEDED)

    def test_04_resolution_for_another_build_is_rejected(self):
        h = self.missing_module()
        self.assertRejected(h, h.resolution(self.skip(), build_id="another-build"),
                            IdentityCode.RESOLUTION_BUILD_MISMATCH)

    def test_05_resolution_for_another_software_graph_is_rejected(self):
        h = self.missing_module()
        other = "d" * 64
        resolution = h.resolution(
            self.skip(), source_software_fingerprint=other,
            resulting_software_fingerprint=frozen_resolution._resolved_fingerprint_from_records(
                other, (self.skip(),)))
        self.assertRejected(h, resolution, IdentityCode.RESOLUTION_SOURCE_MISMATCH)

    def test_06_resolution_record_with_another_captured_version_is_rejected(self):
        h = self.missing_module()
        self.assertRejected(h, h.resolution(self.skip(version="9.9.9")),
                            IdentityCode.RESOLUTION_RECORD_MISMATCH)

    def test_07_resolution_record_with_another_enabled_state_is_rejected(self):
        h = self.missing_module()
        self.assertRejected(h, h.resolution(self.skip(desired_enabled=False)),
                            IdentityCode.RESOLUTION_RECORD_MISMATCH)

    def test_07b_resolution_record_for_an_unmanaged_node_is_rejected(self):
        h = self.missing_module()
        for addon_id, version in (("plugin.video.not-in-graph", "1.0"),
                                  ("xbmc.python", "3.0.1"),                # system dependency
                                  ("script.module.optional", "1.0")):      # absent optional
            with self.subTest(addon_id):
                self.assertRejected(h, h.resolution(self.skip(addon_id, version)),
                                    IdentityCode.RESOLUTION_RECORD_MISMATCH)

    def test_07c_internally_inconsistent_resolution_is_rejected(self):
        h = self.missing_module()
        tampered = h.resolution(self.skip(), resulting_software_fingerprint="e" * 64)
        self.assertRejected(h, tampered, IdentityCode.RESOLUTION_INVALID)
        duplicate = h.resolution(self.skip(), self.skip())
        self.assertRejected(h, duplicate, IdentityCode.RESOLUTION_INVALID)
        unfinished = InstallResolutionRecord(
            MODULE, "2.0.0", InstallResolution.REPOSITORY_CURRENT, ResolutionState.SELECTED,
            repository_id="repository.demo")
        self.assertRejected(
            h, h.resolution(unfinished, resulting_software_fingerprint="f" * 64),
            IdentityCode.RESOLUTION_INVALID)
        self.assertRejected(h, h.resolution(self.skip(), install_plan_fingerprint="not-a-digest"),
                            IdentityCode.RESOLUTION_INVALID)

    def test_07d_resolution_without_a_frozen_manifest_cannot_be_bound(self):
        h = self.missing_module()
        resolution = h.resolution(self.skip())
        with self.assertRaises(IdentityMismatch) as caught:
            bind_resolutions(BUILD_ID, None, resolution, policies=h.desired.frozen_install_policies)
        self.assertEqual(caught.exception.code, IdentityCode.RESOLUTION_WITHOUT_SOFTWARE)
        status = h.check(h.target(software_manifest_path="", install_resolution=resolution))
        self.assertEqual(status.overall, OverallStatus.INCOMPLETE)
        self.assertEqual(status.gaps, (CheckGap.RESOLUTION_IDENTITY_MISMATCH,))

    def test_08_valid_matching_resolution_manifest_works(self):
        h = self.missing_module()
        resolution = h.resolution(self.skip())
        records = bind_resolutions(BUILD_ID, h.frozen, resolution, policies=h.desired.frozen_install_policies)
        self.assertEqual([r.addon_id for r in records], [MODULE])
        status = h.check(install_resolution=resolution)
        self.assertEqual(status.overall, OverallStatus.CURRENT)
        self.assertNotIn(MODULE, {i.addon_id for i in status.software.items})
        h = self.current()
        h.kodi.addons[MODULE] = ("2.0.1", True)
        fallback = InstallResolutionRecord(
            MODULE, "2.0.0", InstallResolution.REPOSITORY_CURRENT, ResolutionState.INSTALLED,
            repository_id="repository.demo", resolved_version="2.0.1",
            artifact_sha256="b" * 64, artifact_size=10)
        self.assertEqual(h.check(install_resolution=h.resolution(fallback)).overall,
                         OverallStatus.CURRENT)
        self.assertEqual(h.check().overall, OverallStatus.CHANGES_NEEDED)   # no record: wrong version

    def test_09_an_accepted_skip_only_counts_when_the_binding_is_valid(self):
        h = self.missing_module()
        self.assertEqual(h.check().overall, OverallStatus.CHANGES_NEEDED)
        valid = h.check(install_resolution=h.resolution(self.skip()))
        foreign = h.check(install_resolution=h.resolution(self.skip(), build_id="another-build"))
        self.assertEqual(valid.overall, OverallStatus.CURRENT)
        self.assertEqual(foreign.overall, OverallStatus.INCOMPLETE)
        self.assertNotEqual(foreign.overall, OverallStatus.CURRENT)

    def test_a_valid_resolution_still_does_not_hide_a_mismatched_frozen_build(self):
        h = self.missing_module()
        resolution = h.resolution(self.skip())
        h.frozen = replace(h.frozen, build_id="another-build")
        status = h.check(install_resolution=resolution)
        self.assertEqual(status.gaps, (CheckGap.BUILD_IDENTITY_MISMATCH,))

    def test_rejection_output_has_no_identity_material(self):
        h = self.missing_module()
        resolution = h.resolution(self.skip(), build_id="another-build")
        status = h.check(install_resolution=resolution)
        text = safe_text(status) + "\n".join(h.logs)
        for forbidden in ("another-build", resolution.resolution_fingerprint,
                          resolution.source_software_fingerprint, resolution.install_plan_fingerprint,
                          resolution.resulting_software_fingerprint):
            self.assertNotIn(forbidden, text)


class PrivateUnreadabilityPrecedence(StatusBase):
    def two_settings(self):
        h = self.current(with_resource=False)
        h.desired = replace(h.desired, config=replace(h.desired.config,
            private_settings=h.desired.config.private_settings + (
                PrivateSettingDeclaration(DEMO, 'second_token', 'string', True, 'token'),)))
        overlay = h.overlay_store.load('status-overlay')
        h.overlay_store.save(replace(overlay, entries=overlay.entries + (
            PrivateOverlayEntry(DEMO, 'second_token', ConfigSettingType.STRING, SECRET),)))
        h.config_backend.settings[(DEMO, 'second_token')] = SECRET
        return h

    def test_real_setting_results_current_drift_and_unavailable(self):
        h = self.two_settings()
        self.assertEqual(h.check().private.level, AreaLevel.CURRENT)
        h.config_backend.settings[(DEMO, 'api_token')] = 'different'
        self.assertEqual(h.check().private.level, AreaLevel.CHANGES_NEEDED)
        h.config_backend.settings[(DEMO, 'second_token')] = 'also different'
        self.assertEqual(h.check().private.level, AreaLevel.CHANGES_NEEDED)
        h.config_backend.unreadable.add((DEMO, 'second_token'))
        result = h.check()
        self.assertEqual(result.private.level, AreaLevel.UNAVAILABLE)
        self.assertIn(CheckGap.PRIVATE_UNAVAILABLE, result.gaps)
        self.assertSecretFree(safe_text(result), h.logs)

    def mixed_resources(self):
        h = self.current()
        second = replace(h.declaration, resource_id='private.second', adapter_id='unavailable.adapter')
        h.desired = replace(h.desired, config=replace(h.desired.config,
            structured_private_resources=(h.declaration, second)))
        overlay = h.overlay_store.load('status-overlay')
        first = replace(overlay.resources[0], values=(
            StructuredPrivateValue('trakt.token', 'string', 'different'),))
        h.overlay_store.save(replace(overlay, resources=(first, replace(first, resource_id='private.second'))))
        return h

    def test_real_resource_manager_mixed_results_preserve_items(self):
        h = self.mixed_resources()
        result = h.check()
        self.assertEqual(result.private.level, AreaLevel.UNAVAILABLE)
        items = {item.item_id: item.level for item in result.private.items}
        self.assertEqual(items[REDLIGHT_RESOURCE_ID], AreaLevel.CHANGES_NEEDED)
        self.assertEqual(items['private.second'], AreaLevel.UNAVAILABLE)
        self.assertIn(CheckGap.PRIVATE_UNAVAILABLE, result.gaps)
        self.assertSecretFree(safe_text(result), h.logs)

    def test_real_resource_unreadability_outranks_setting_drift(self):
        h = self.current()
        h.config_backend.settings[(DEMO, 'api_token')] = 'different'
        h.db.write_bytes(b'unreadable database')
        result = h.check()
        self.assertEqual(result.private.level, AreaLevel.UNAVAILABLE)
        self.assertEqual({item.kind: item.level for item in result.private.items}, {
            PrivateItemKind.SETTINGS: AreaLevel.CHANGES_NEEDED,
            PrivateItemKind.RESOURCE: AreaLevel.UNAVAILABLE})
