"""D-033 correction: local capture consent is bound to exact (addon_id, version) pairs.

Offline only. The fixtures come from tests.test_local_capture_fallback: a FakeMirror, temporary
directories and in-memory inventories. No Kodi profile, application bundle or real artifact store
is read or written outside those temporary directories.
"""

import unittest

from resources.lib.create_capture import CreateBuildCaptureEngine, CreateCaptureStatus
from resources.lib.create_workflow import CreateBuildWorkflow
from resources.lib.frozen import ArtifactAcquirer, CaptureStatus, capture_frozen_build
from resources.lib.local_capture import LOCAL_CAPTURE_SOURCE
from tests import test_local_capture_fallback as fallback
from tests.test_frozen import _xml as frozen_xml, _zip as frozen_zip

DEMO_ID = "plugin.demo"
DEMO_OLD = (DEMO_ID, "1.0.0")
DEMO_NEW = (DEMO_ID, "1.0.1")
TMDB = fallback.TMDB
TMDB_ID = fallback.TMDB[0]
TMDB_NEW = (TMDB_ID, "6.17.10")
DEPENDENCIES = tuple(fallback.TMDB_DEPENDENCIES)


class CreateVersionConsentTests(unittest.TestCase):
    """The offer, the user's answer and the second capture pass must agree on the exact pair."""

    def setUp(self):
        from tests.test_create_workflow import WorkflowTests
        base = WorkflowTests("test_all_eligible_selected_and_private_on")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        rows = list(base.inventory.addons)
        xml = dict(base.inventory.addon_xml)
        cache = {(a, "1.0.0"): ((a + ".zip", frozen_zip(a)),) for a in ("script.module.demo", "skin.demo")}
        base.inventory = fallback.LocalBackend(rows, xml, package_cache=cache)
        base.engine = CreateBuildCaptureEngine(
            inventory=base.inventory, artifact_store=base.artifacts, configuration=base.config,
            inspect_state=lambda: base.state)
        base.factory.return_value = base.engine
        base.workflow = CreateBuildWorkflow(
            inventory=base.inventory, inspect_state=lambda: base.state, library=base.library,
            engine_factory=base.factory, private_store_factory=base.private_factory,
            catalog=base.workflow.catalog, clock=base.clock)
        base.session = base.workflow.open("Current device")
        base.session.name = "My Build"
        base.session.include_private = False
        # Record every capture pass so each test can prove whether a second pass ran at all.
        self.passes = []
        capture = base.engine.capture

        def record(*args, **kwargs):
            result = capture(*args, **kwargs)
            self.passes.append(result)
            return result

        base.engine.capture = record

    def execute(self):
        return self.base.workflow.execute(self.base.workflow.preview(self.base.session))

    def installed_version_becomes(self, version):
        """The user changes the installed version between the offer and the second pass."""
        inventory = self.base.inventory
        inventory.addons = tuple(dict(row, version=version) if row.get("addonid") == DEMO_ID else dict(row)
                                 for row in inventory.addons)
        inventory.addon_xml[DEMO_ID] = frozen_xml(DEMO_ID, version)

    def store_files(self):
        root = self.base.base / "artifacts"
        return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()) if root.exists() else []

    def assert_rejected(self, answer):
        self.base.workflow.confirm_local_capture = answer
        self.execute()
        self.assertEqual(1, len(self.passes), "the second capture pass must never run")
        self.assertEqual([], list(self.base.entries()))
        self.assertIsNone(self.base.artifacts.find(*DEMO_OLD))
        self.assertIsNone(self.base.artifacts.find(*DEMO_NEW))

    def test_unchanged_approved_pair_is_captured_and_saved(self):
        self.base.workflow.confirm_local_capture = lambda offered: tuple(offered)
        terminal = self.execute()
        self.assertEqual(32736, terminal.string_id)
        self.assertEqual(2, len(self.passes))
        self.assertEqual(CreateCaptureStatus.COMPLETE, self.passes[1].status)
        self.assertEqual(1, len(self.base.entries()))
        self.assertEqual(LOCAL_CAPTURE_SOURCE, self.base.artifacts.find(*DEMO_OLD).source)

    def test_version_change_between_passes_is_refused_and_registers_nothing(self):
        offered = []

        def approve_then_change_the_installed_version(candidates):
            offered.append(tuple(candidates))
            self.store_snapshot = self.store_files()
            self.installed_version_becomes(DEMO_NEW[1])
            return tuple(candidates)

        self.base.workflow.confirm_local_capture = approve_then_change_the_installed_version
        terminal = self.execute()
        self.assertEqual([(DEMO_OLD,)], offered)
        self.assertEqual(2, len(self.passes))
        self.assertEqual(CreateCaptureStatus.INCOMPLETE, self.passes[1].status)
        self.assertEqual((DEMO_NEW,), tuple(self.passes[1].local_capture_candidates))
        self.assertEqual(32730, terminal.string_id)
        self.assertEqual([], list(self.base.entries()))
        self.assertEqual(self.store_snapshot, self.store_files())
        self.assertIsNone(self.base.artifacts.find(*DEMO_NEW))
        self.assertIsNone(self.base.artifacts.find(*DEMO_OLD))

    def test_declined_consent_remains_declined(self):
        asked = []
        self.base.workflow.confirm_local_capture = lambda offered: asked.append(tuple(offered)) or ()
        terminal = self.execute()
        self.assertEqual([(DEMO_OLD,)], asked)
        self.assertEqual(1, len(self.passes))
        self.assertEqual(32730, terminal.string_id)
        self.assertEqual([], list(self.base.entries()))
        self.assertIsNone(self.base.artifacts.find(*DEMO_OLD))

    def test_approval_for_the_same_add_on_with_another_version_is_rejected(self):
        self.assert_rejected(lambda offered: (DEMO_NEW,))

    def test_approval_for_an_unoffered_add_on_is_rejected(self):
        self.assert_rejected(lambda offered: (("script.module.demo", "1.0.0"),))

    def test_mixed_answer_with_one_unoffered_pair_is_rejected_entirely(self):
        self.assert_rejected(lambda offered: (DEMO_OLD, ("script.module.demo", "1.0.0")))

    def test_malformed_answer_is_rejected(self):
        self.assert_rejected(lambda offered: (DEMO_ID,))


class PairBoundFrozenCaptureTests(unittest.TestCase):
    """Frozen acquisition packages a local copy only for the exact approved (addon_id, version)."""

    def setUp(self):
        self.fixture = fallback.ThreeMissingOriginalsTests(
            "test_without_authorisation_all_three_are_offered_and_nothing_is_stored")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def capture(self, approvals, backend):
        return capture_frozen_build(
            backend=backend, store=self.fixture.store, root_addon_ids=[TMDB_ID], build_id="b", name="n",
            created_at="2026-11-16T00:00:00Z", kodi_version="21.3", platform="macos",
            local_capture_approvals=approvals)

    def record_packaging(self, backend):
        """Every attempt to create a local package, whether it succeeds or is refused."""
        attempts = []
        packaged = backend.capture_installed_artifact

        def record(addon_id, version):
            attempts.append((addon_id, version))
            return packaged(addon_id, version)

        backend.capture_installed_artifact = record
        return attempts

    def stored_files(self):
        root = self.fixture.base / "store" / "artifacts"
        return sorted(path.name for path in root.iterdir()) if root.exists() else []

    def install_version(self, addon_id, version):
        """The installed version changes in the listing and on disk, as it would between passes."""
        entry = next(item for item in self.fixture.entries if item["addonid"] == addon_id)
        previous = entry["version"]
        entry["version"] = version
        path = self.fixture.home / addon_id / "addon.xml"
        path.write_text(path.read_text().replace(f'version="{previous}"', f'version="{version}"', 1))

    def test_exact_approved_pair_is_packaged_and_nothing_else_is_authorised(self):
        backend = self.fixture.backend()
        attempts = self.record_packaging(backend)
        result = self.capture((TMDB,), backend)
        self.assertEqual([TMDB], attempts)
        node = next(item for item in result.manifest.addons if item.addon_id == TMDB_ID)
        self.assertEqual(CaptureStatus.COMPLETE, node.status)
        self.assertEqual(LOCAL_CAPTURE_SOURCE, node.artifact.source)
        self.assertFalse(result.complete)
        self.assertEqual(sorted(DEPENDENCIES), list(result.local_capture_candidates))

    def test_installed_version_change_voids_local_capture_for_the_whole_pass(self):
        self.install_version(TMDB_ID, TMDB_NEW[1])
        backend = self.fixture.backend()
        attempts = self.record_packaging(backend)
        result = self.capture((TMDB,) + DEPENDENCIES, backend)
        self.assertFalse(result.complete)
        self.assertEqual([], attempts)  # no package is created, not even for the unchanged pairs
        self.assertEqual([], self.stored_files())  # and nothing is imported
        self.assertEqual(sorted([TMDB_NEW] + list(DEPENDENCIES)), list(result.local_capture_candidates))
        self.assertIn("local_capture_snapshot_changed", result.diagnostic_categories)

    def test_an_approved_version_does_not_authorise_a_different_installed_version(self):
        self.install_version(TMDB_ID, TMDB_NEW[1])
        backend = self.fixture.backend()
        attempts = self.record_packaging(backend)
        result = ArtifactAcquirer(self.fixture.store, backend, (TMDB,)).acquire(TMDB_ID, TMDB_NEW[1])
        self.assertEqual(CaptureStatus.INCOMPLETE_ARTIFACT, result.status)
        self.assertTrue(result.local_capture_eligible)
        self.assertEqual([], attempts)
        self.assertEqual([], self.stored_files())

    def test_an_approved_pair_does_not_authorise_another_add_on(self):
        backend = self.fixture.backend()
        attempts = self.record_packaging(backend)
        result = ArtifactAcquirer(self.fixture.store, backend, (TMDB,)).acquire(*DEPENDENCIES[0])
        self.assertTrue(result.local_capture_eligible)
        self.assertEqual([], attempts)

    def test_declined_consent_never_packages(self):
        backend = self.fixture.backend()
        attempts = self.record_packaging(backend)
        result = self.capture((), backend)
        self.assertFalse(result.complete)
        self.assertEqual([], attempts)
        self.assertEqual([], self.stored_files())
        self.assertEqual(sorted((TMDB,) + DEPENDENCIES), list(result.local_capture_candidates))

    def test_bare_add_on_ids_are_refused_as_approvals(self):
        with self.assertRaises(ValueError):
            self.capture([TMDB_ID], self.fixture.backend())
        with self.assertRaises(ValueError):
            ArtifactAcquirer(self.fixture.store, self.fixture.backend(), [TMDB_ID])


if __name__ == "__main__":
    unittest.main()
