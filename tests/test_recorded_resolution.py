"""Prior accepted outcomes for Update / Repair, offline.

A prior terminal resolution is reused as exactly what was accepted: exact outcomes
keep their exact artifacts, and recorded repository packages are reused as their
saved bytes. The engine binds it again before any mutation, never queries a
repository, and carries its identity through the durable transaction. The
plan-level tests pin the applied-target decision invariant.
"""
from dataclasses import replace
import unittest
from unittest.mock import patch

from resources.lib import frozen_install
from resources.lib import repository_preparation as prep
from resources.lib.artifacts import ArtifactStore
from resources.lib.build_library import LibraryInstallTarget
from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
from resources.lib.frozen_install import FrozenInstalledAddon, FrozenInstallTransaction
from resources.lib.frozen_resolution import (
    AddonRecoverability, FrozenInstallResolutionManifest, InstallResolution, InstallResolutionRecord,
    Recoverability, ResolutionChoice, ResolutionState, default_exact_record, resolved_software_fingerprint,
)
from resources.lib.manifest import FrozenInstallPolicyMode
from resources.lib.plan import PlanTarget
from resources.lib.plan_model import BlockerCode, DecisionChoice, PlanState, SoftwareAction
from resources.lib.restart_coordinator import RestartCapabilityResolver, RestartCoordinator
from tests import test_library_install as library_install
from tests.test_frozen_install import SESSION_A, SESSION_B, _zip
from tests.test_library_install import forbidden
from tests.test_plan import LATE_DEPENDENCY, PlanBase, PlanHarness, REPOSITORY, make_zip
from tests.test_status import DEMO, MODULE

PRIOR_ERROR = 'PRIOR_RESOLUTION_INVALID'
INDEX_URL = 'http://127.0.0.1:9999/addons.xml'


class StaleAssociation:
    """The library authority, except that its applied association names another revision."""

    def __init__(self, library):
        self._library = library

    def __getattr__(self, name):
        return getattr(self._library, name)

    def current_applied_association(self, **kwargs):
        return replace(self._library.current_applied_association(**kwargs), entry_id="f" * 64)


class TamperedAssociation(StaleAssociation):
    """The library authority, except that its applied association names a tampered outcome."""

    def __init__(self, library, resolution_fingerprint):
        super().__init__(library)
        self._resolution_fingerprint = resolution_fingerprint

    def current_applied_association(self, **kwargs):
        return replace(self._library.current_applied_association(**kwargs),
                       resolution_fingerprint=self._resolution_fingerprint)


def installable_records(frozen, record_for):
    """Records for every installable add-on: the set a published outcome always covers."""
    return [record_for(node) for node in frozen.addons
            if not node.system and not node.is_absent_optional_dependency]


class PlanInvariantTests(PlanBase):
    """A published applied outcome records every installable add-on, so Check for Changes
    never asks for a new decision on the applied revision. A partial bound outcome is not
    something publication produces, and it is the only input that reaches a decision."""

    def harness(self):
        h = PlanHarness(self, with_private=False, with_resource=False)
        h.set_graph(policies=[h.policy(MODULE, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY)])
        return h

    def repository_module(self, h):
        """MODULE was captured exact; the applied outcome reached it through the repository at 2.0.1."""
        resolved = ArtifactStore(h.store_root).import_zip(
            make_zip(MODULE, "2.0.1"), expected_addon_id=MODULE, expected_version="2.0.1")
        h.forget_package(MODULE)
        return resolved, InstallResolutionRecord(
            MODULE, "2.0.0", InstallResolution.REPOSITORY_CURRENT, ResolutionState.INSTALLED,
            repository_id=REPOSITORY, resolved_version="2.0.1",
            artifact_sha256=resolved.sha256, artifact_size=resolved.size)

    def complete(self, h, module_record):
        def record_for(node):
            if node.addon_id == MODULE:
                return module_record
            return replace(default_exact_record(node), state=ResolutionState.INSTALLED)
        return h.resolution(*installable_records(h.frozen, record_for))

    def test_a_complete_applied_outcome_never_asks_for_a_new_decision(self):
        h = self.harness()
        _, module = self.repository_module(h)
        resolution = self.complete(h, module)
        h.kodi.addons[MODULE] = ("2.0.1", True)
        plan = h.plan(install_resolution=resolution)
        self.assertNotIn(plan.state, (PlanState.DECISION_REQUIRED, PlanState.RESOLUTION_REQUIRED),
                         plan.to_safe_dict())
        self.assertFalse(any(row.action in (SoftwareAction.DECISION, SoftwareAction.INSTALL_REPOSITORY)
                             for row in plan.software))
        self.assertEqual(self.row(plan, MODULE).version, "2.0.1")

    def test_a_recorded_package_that_is_gone_blocks_instead_of_asking_again(self):
        h = self.harness()
        resolved, module = self.repository_module(h)
        resolution = self.complete(h, module)
        del h.kodi.addons[MODULE]
        (h.store_root / "artifacts" / ("%s.zip" % resolved.sha256)).unlink()
        plan = h.plan(install_resolution=resolution)
        self.assertEqual(plan.state, PlanState.BLOCKED, plan.to_safe_dict())
        self.assertIn((BlockerCode.PACKAGE_MISSING, MODULE), self.codes(plan))
        self.assertFalse(any(row.action is SoftwareAction.DECISION for row in plan.software))

    def test_an_installed_recorded_package_that_is_gone_blocks_before_any_change(self):
        """Execution needs the saved bytes even for a healthy installed add-on, so the plan must too."""
        h = self.harness()
        resolved, module = self.repository_module(h)
        resolution = self.complete(h, module)
        h.kodi.addons[MODULE] = ("2.0.1", True)
        (h.store_root / "artifacts" / ("%s.zip" % resolved.sha256)).unlink()
        plan = h.plan(install_resolution=resolution)
        self.assertEqual(plan.state, PlanState.BLOCKED, plan.to_safe_dict())
        self.assertIn((BlockerCode.PACKAGE_MISSING, MODULE), self.codes(plan))

    def test_a_partial_bound_outcome_is_the_only_input_that_reaches_a_decision(self):
        """Documents the boundary. Publication never produces an outcome like this."""
        h = self.harness()
        h.forget_package(MODULE)
        del h.kodi.addons[MODULE]
        plan = h.plan(install_resolution=h.resolution())
        self.assertEqual(plan.state, PlanState.DECISION_REQUIRED, plan.to_safe_dict())
        self.assertEqual(self.row(plan, MODULE).action, SoftwareAction.DECISION)


class PriorExactOutcomeTests(unittest.TestCase):
    """Library installs with exact artifacts only, through the real lifecycle."""

    def setUp(self):
        self.f = library_install.LibraryInstallTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def installed_prior(self):
        target = self.f.target()
        first = self.f.coordinator().install_target(target, interactive=False)
        self.assertEqual(first.outcome, 'complete', (first.code, first.message))
        return target, first.resolution_manifest

    def assert_refused_before_mutation(self, result):
        self.assertEqual((result.outcome, result.code), ('failed', PRIOR_ERROR), (result.code, result.message))
        self.assertIsNone(self.f.store.inspect())

    def test_a_healthy_outcome_is_reused_without_reinstalling_anything(self):
        target, prior = self.installed_prior()
        with patch.object(self.f.backend, 'install_exact', side_effect=forbidden):
            result = self.f.coordinator().install_target(target, interactive=False, prior_resolution=prior)
        self.assertEqual(result.outcome, 'complete', (result.code, result.message))
        self.assertEqual(result.resolution_manifest.resolution_fingerprint, prior.resolution_fingerprint)

    def test_a_missing_exact_outcome_reinstalls_only_its_exact_saved_bytes(self):
        target, prior = self.installed_prior()
        record = next(r for r in prior.records if r.addon_id == DEMO)
        saved = self.f.artifacts.read_bytes(record.artifact_sha256)
        del self.f.backend.installed[DEMO]
        with patch.object(self.f.backend, 'install_exact', wraps=self.f.backend.install_exact) as install:
            result = self.f.coordinator().install_target(target, interactive=False, prior_resolution=prior)
        self.assertEqual(result.outcome, 'complete', (result.code, result.message))
        install.assert_called_once_with(DEMO, record.resolved_version, saved)

    def test_a_prior_that_does_not_bind_is_refused_before_mutation(self):
        target, prior = self.installed_prior()
        del self.f.backend.installed[DEMO]
        tampered = replace(prior, resulting_software_fingerprint="0" * 64)
        self.assert_refused_before_mutation(
            self.f.coordinator().install_target(target, interactive=False, prior_resolution=tampered))
        self.assertNotIn(DEMO, self.f.backend.installed)

    def test_a_prior_that_is_no_longer_the_applied_association_is_refused_before_mutation(self):
        target, prior = self.installed_prior()
        del self.f.backend.installed[DEMO]
        with patch('resources.lib.build_library.authoritative_build_library',
                   return_value=StaleAssociation(self.f.fixture.library)):
            result = self.f.coordinator().install_target(target, interactive=False, prior_resolution=prior)
        self.assert_refused_before_mutation(result)
        self.assertNotIn(DEMO, self.f.backend.installed)

    def test_a_different_installed_version_stays_blocked_before_mutation(self):
        target, prior = self.installed_prior()
        self.f.backend.installed[DEMO] = FrozenInstalledAddon(DEMO, "9.9.9", True, False)
        self.assert_refused_before_mutation(
            self.f.coordinator().install_target(target, interactive=False, prior_resolution=prior))
        self.assertEqual(self.f.backend.installed[DEMO].version, "9.9.9")

    def test_a_broken_installed_add_on_stays_blocked_before_mutation(self):
        target, prior = self.installed_prior()
        self.f.backend.installed[DEMO] = FrozenInstalledAddon(DEMO, "1.0.0", True, True)
        self.assert_refused_before_mutation(
            self.f.coordinator().install_target(target, interactive=False, prior_resolution=prior))

    def test_a_recorded_outcome_cannot_also_be_answered(self):
        target, prior = self.installed_prior()
        del self.f.backend.installed[DEMO]
        self.assert_refused_before_mutation(self.f.coordinator().install_target(
            target, interactive=False, prior_resolution=prior,
            resolution_choices={DEMO: ResolutionChoice.SKIP}))

    def tampered_exact_prior(self, prior):
        """A prior whose exact record names another saved build of the same add-on and version.

        The manifest stays internally coherent: its resulting-software fingerprint is
        recomputed, and the resolution fingerprint follows from the records. Only the
        terminal-record rule can see that the record's artifact is not the captured one.
        """
        record = next(r for r in prior.records if r.addon_id == DEMO)
        # Same add-on and version, different bytes: the requirement only makes the build distinct.
        other = self.f.artifacts.import_zip(
            _zip(DEMO, record.resolved_version, requires=((LATE_DEPENDENCY, '3.0.0'),)),
            expected_addon_id=DEMO, expected_version=record.resolved_version)
        captured = next(node for node in self.f.fixture.frozen.addons if node.addon_id == DEMO).artifact
        self.assertNotEqual(other.sha256, captured.sha256)
        records = tuple(
            replace(r, artifact_sha256=other.sha256, artifact_size=other.size) if r.addon_id == DEMO else r
            for r in prior.records)
        return FrozenInstallResolutionManifest(
            build_id=prior.build_id,
            source_software_fingerprint=prior.source_software_fingerprint,
            install_plan_fingerprint=prior.install_plan_fingerprint,
            resulting_software_fingerprint=resolved_software_fingerprint(self.f.fixture.frozen, records),
            records=records)

    def test_a_prior_exact_outcome_naming_another_artifact_is_refused_before_mutation(self):
        """Binds to this build and to the applied association, so only the terminal rule can refuse it."""
        target, prior = self.installed_prior()
        tampered = self.tampered_exact_prior(prior)
        del self.f.backend.installed[DEMO]
        with patch('resources.lib.build_library.authoritative_build_library',
                   return_value=TamperedAssociation(self.f.fixture.library, tampered.resolution_fingerprint)), \
                patch.object(self.f.backend, 'install_exact', side_effect=forbidden), \
                patch.object(self.f.backend, 'resolve_repository_current', side_effect=forbidden), \
                patch('resources.lib.frozen_install._check_terminal_record',
                      wraps=frozen_install._check_terminal_record) as terminal_rule:
            result = self.f.coordinator().install_target(target, interactive=False, prior_resolution=tampered)
        self.assertEqual(result.outcome, 'failed', (result.code, result.message))
        self.assertIn(DEMO, [call.args[0] for call in terminal_rule.call_args_list])
        self.assertIsNone(self.f.store.inspect())
        self.assertNotIn(DEMO, self.f.backend.installed)


class PriorRepositoryOutcomeTests(unittest.TestCase):
    """A recorded repository-current outcome, reused as its saved bytes with the network forbidden."""

    def setUp(self):
        self.f = library_install.LibraryInstallTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.store = self.f.artifacts
        self.raw = self.f.fixture.raw
        self.raw['device_profiles']['desk']['frozen_install_policies'] = [
            {'addon_id': DEMO, 'policy': 'exact_first_with_repository_fallback_or_skip', 'repository_id': REPOSITORY}]
        self.nodes = list(self.f.fixture.frozen.addons)
        self.store.artifact_path(self.nodes[0].artifact.sha256).unlink()
        repo = self.store.import_zip(_zip(REPOSITORY, '1.0.0', repository=True),
                                     expected_addon_id=REPOSITORY, expected_version='1.0.0')
        self.nodes.append(AddonCaptureNode(REPOSITORY, '1.0.0', 'xbmc.addon.repository', True,
                                           ProvenanceStatus.VERIFIED_REPOSITORY, artifact=repo))
        late = self.store.import_zip(_zip(LATE_DEPENDENCY, '3.0.0'),
                                     expected_addon_id=LATE_DEPENDENCY, expected_version='3.0.0')
        self.nodes.append(AddonCaptureNode(LATE_DEPENDENCY, '3.0.0', 'xbmc.python.module', True,
                                           ProvenanceStatus.UNKNOWN, artifact=late))
        self.package = _zip(DEMO, '2.0.0', requires=((LATE_DEPENDENCY, '3.0.0'),))
        self.index = f'<addons><addon id="{DEMO}" version="2.0.0"/></addons>'.encode()
        self.downloads = []

    def download(self, url, *, max_bytes, timeout):
        self.downloads.append((url, max_bytes, timeout))
        if url == INDEX_URL:
            return self.index
        return self.package

    def prepared_target(self):
        self.f.fixture.frozen = replace(self.f.fixture.frozen, addons=tuple(self.nodes))
        self.f.fixture.write_sources()
        self.install_target = self.f.target()
        plain = PlanTarget('/unused-build', 'desk', '/unused-frozen',
                           library_source=self.install_target.source,
                           choices=((DEMO, DecisionChoice.INSTALL_CURRENT),))
        result = prep.RepositoryPreparationService(self.store, download=self.download).prepare(plain)
        self.assertEqual(result.code, prep.PreparationCode.READY, result)
        return replace(plain, prepared_resolution=result.prepared)

    def first_apply(self):
        target = self.prepared = self.prepared_target()
        with self.f.isolated(), patch.object(self.f.backend, 'resolve_repository_current', side_effect=forbidden):
            first = self.f.coordinator().install_target(
                LibraryInstallTarget.from_plan_target(target), prepared_resolution=target.prepared_resolution,
                resolution_choices={DEMO: ResolutionChoice.INSTALL_CURRENT}, interactive=False)
        self.assertEqual(first.outcome, 'complete', (first.code, first.message))
        self.assertEqual(self.f.backend.installed[DEMO].version, '2.0.0')
        return first.resolution_manifest

    def reuse(self, prior, **kwargs):
        with self.f.isolated(), patch.object(self.f.backend, 'resolve_repository_current', side_effect=forbidden):
            return self.f.coordinator(**kwargs).install_target(self.install_target, interactive=False,
                                                               prior_resolution=prior)

    @staticmethod
    def record_for(prior):
        return next(r for r in prior.records if r.addon_id == DEMO)

    def test_a_healthy_recorded_outcome_is_reused_without_network_or_reinstall(self):
        prior = self.first_apply()
        downloads = list(self.downloads)
        with patch.object(self.f.backend, 'install_exact', side_effect=forbidden):
            result = self.reuse(prior)
        self.assertEqual(result.outcome, 'complete', (result.code, result.message))
        self.assertEqual(self.downloads, downloads)
        self.assertEqual(result.resolution_manifest.resolution_fingerprint, prior.resolution_fingerprint)

    def test_a_missing_recorded_add_on_installs_only_its_saved_package(self):
        prior = self.first_apply()
        saved = self.store.read_bytes(self.record_for(prior).artifact_sha256)
        downloads = list(self.downloads)
        del self.f.backend.installed[DEMO]
        with patch.object(self.f.backend, 'install_exact', wraps=self.f.backend.install_exact) as install:
            result = self.reuse(prior)
        self.assertEqual(result.outcome, 'complete', (result.code, result.message))
        self.assertEqual(self.downloads, downloads)
        install.assert_any_call(DEMO, '2.0.0', saved)

    def test_a_missing_saved_package_fails_closed_before_any_mutation(self):
        prior = self.first_apply()
        self.store.artifact_path(self.record_for(prior).artifact_sha256).unlink()
        del self.f.backend.installed[DEMO]
        downloads = list(self.downloads)
        result = self.reuse(prior)
        self.assertEqual(result.outcome, 'failed', (result.code, result.message))
        self.assertNotIn(DEMO, self.f.backend.installed)
        self.assertIsNone(self.f.store.inspect())
        self.assertEqual(self.downloads, downloads)

    def test_a_truncated_saved_package_fails_closed_before_any_mutation(self):
        prior = self.first_apply()
        path = self.store.artifact_path(self.record_for(prior).artifact_sha256)
        path.write_bytes(path.read_bytes()[:-1])
        del self.f.backend.installed[DEMO]
        downloads = list(self.downloads)
        result = self.reuse(prior)
        self.assertEqual(result.outcome, 'failed', (result.code, result.message))
        self.assertNotIn(DEMO, self.f.backend.installed)
        self.assertEqual(self.downloads, downloads)

    def test_an_interrupted_reuse_is_equivalent_only_to_the_same_prior_identity(self):
        """Durable identity: an interrupted reuse keeps the prior outcome it was seeded from."""
        prior = self.first_apply()                 # a completed, published prior outcome
        del self.f.backend.installed[DEMO]

        def interrupted(*args, **kwargs):
            raise RuntimeError("interrupted before the saved package was installed")

        with patch.object(self.f.backend, 'install_exact', side_effect=interrupted):
            stopped = self.reuse(prior)
        self.assertNotEqual(stopped.outcome, 'complete', (stopped.code, stopped.message))
        persisted = self.f.store.inspect()
        self.assertIsNotNone(persisted, (stopped.code, stopped.message))
        self.assertEqual(persisted.prior_resolution_fingerprint, prior.resolution_fingerprint)
        roundtrip = FrozenInstallTransaction.from_dict(persisted.to_dict())
        self.assertEqual(roundtrip.prior_resolution_fingerprint, prior.resolution_fingerprint)
        # The same operation without the prior outcome is a different operation.
        with self.f.isolated():
            other = self.f.coordinator(session=SESSION_B).install_target(self.install_target, interactive=False)
        self.assertEqual((other.outcome, other.code), ('failed', 'ACTIVE_TRANSACTION_CONFLICT'),
                         (other.code, other.message))
        # The same prior identity is equivalent to the active transaction.
        same = self.reuse(prior)
        self.assertIn(same.outcome, ('active', 'needs_attention'), (same.code, same.message))

        legacy = persisted.to_dict()
        legacy.pop('prior_resolution_fingerprint')
        self.assertEqual(FrozenInstallTransaction.from_dict(legacy).prior_resolution_fingerprint, '')


class TerminalExactStateTests(unittest.TestCase):
    """The shared terminal-record rule for an EXACT record that is not yet INSTALLED.

    Prior reuse cannot present such a record: the manifest parser refuses unfinished
    records before binding. The rule is tested where it is enforced, shared with the
    restart path, so it stays observable if the parser ever stops refusing them.
    """

    def setUp(self):
        self.f = library_install.LibraryInstallTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.node = next(node for node in self.f.fixture.frozen.addons if node.addon_id == DEMO)
        self.row = AddonRecoverability(DEMO, self.node.version, Recoverability.EXACT_FROZEN, True)
        self.selected = default_exact_record(self.node)

    def test_a_completed_exact_record_that_is_not_installed_is_rejected(self):
        with self.assertRaises(frozen_install.FrozenInstallValidationError):
            frozen_install._check_terminal_record(DEMO, self.selected, self.node, self.row, ())
        installed = replace(self.selected, state=ResolutionState.INSTALLED)
        frozen_install._check_terminal_record(DEMO, installed, self.node, self.row, ())

    def test_the_restart_path_accepts_an_uninstalled_exact_record(self):
        frozen_install._check_terminal_record(DEMO, self.selected, self.node, self.row, (), allow_uninstalled=True)


if __name__ == '__main__':
    unittest.main()
