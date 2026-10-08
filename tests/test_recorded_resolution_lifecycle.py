"""End-to-end lifecycle coverage for prior accepted outcomes, offline.

Uses the real FrozenInstallCoordinator, binding, durable store and restart
lifecycle with injected fakes for Kodi, the installer and configuration. No
runtime, Test.app, profile or device is touched.

Two gaps from the recorded-resolution correction are closed here:
- a recorded SKIPPED outcome reused end to end, with unrelated drift repaired and
  a negative case where the skipped add-on is now installed;
- the real quiescence -> new session -> active_resume branch that compares the
  durable prior_resolution_fingerprint against the request.
"""
import json
from dataclasses import replace
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
from resources.lib.frozen_install import FrozenInstalledAddon, FrozenInstallTransaction, FrozenLifecycleStage
from resources.lib.frozen_resolution import InstallResolution, ResolutionChoice
from resources.lib.private_overlay import PrivateOverlayMetadata
from resources.lib.redlight_resource import redlight_declaration
from tests import test_library_install as library_install
from tests.test_frozen_install import SESSION_A, SESSION_B, _zip
from tests.test_library_install import forbidden
from tests.test_status import DEMO

OWNER = "plugin.video.redlight"
SESSION_C = "44444444-4444-4444-8444-444444444444"
SESSION_D = "55555555-5555-4555-8555-555555555555"


def held_fixture(f):
    """A library with a held pre-activation owner, using the library's own store.

    Mirrors LibraryInstallTests.held_library, but keeps f.store so the applied
    association stays visible to the publication path.
    """
    metadata = f.artifacts.import_zip(_zip(OWNER, "2.6.8"), expected_addon_id=OWNER, expected_version="2.6.8")
    f.fixture.frozen = replace(f.fixture.frozen, addons=f.fixture.frozen.addons + (
        AddonCaptureNode(OWNER, "2.6.8", "xbmc.python.pluginsource", True,
                         ProvenanceStatus.UNKNOWN, artifact=metadata),))
    f.fixture.raw["addons"].append({"addon_id": OWNER, "state": "enabled"})
    f.fixture.raw["private_overlay"] = {"type": "local_file", "overlay_id": "held", "required": True}
    f.fixture.raw["config"]["structured_private_resources"] = [redlight_declaration().safe_dict()]
    f.fixture.write_sources()
    f.backend.installed[OWNER] = FrozenInstalledAddon(OWNER, "2.6.8", True)
    target = f.target()
    meta = PrivateOverlayMetadata("held", "sha256:" + "3" * 64, True, True)
    provider = lambda profile, fingerprint: (meta.overlay_id, meta.fingerprint, meta.required)
    requests = []

    def runner(request, *, transaction_access=None):
        requests.append(request)
        private = SimpleNamespace(succeeded=True, resource_results=(SimpleNamespace(succeeded=True),))
        reconcile = SimpleNamespace(success=True, private_overlay=meta, action_results=(
            SimpleNamespace(owner_result=SimpleNamespace(private_result=private)),))
        return SimpleNamespace(outcome="complete", reconcile_result=reconcile)

    return target, provider, runner, requests


def coordinator(f, runner, provider, session=SESSION_A):
    return f.coordinator(session=session, runner=runner, private_overlay_metadata_provider=provider)


class RecordedSkipEndToEndTests(unittest.TestCase):
    """An applied outcome with an accepted skip, reused by a later Update / Repair run."""

    def setUp(self):
        self.f = library_install.LibraryInstallTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.missing = self.f.with_missing_addon()
        self.target = self.f.target()

    def applied_with_skip(self):
        first = self.f.coordinator(resolution_decider=forbidden).install_target(
            self.target, interactive=False, resolution_choices={self.missing: ResolutionChoice.SKIP})
        self.assertEqual(first.outcome, "complete", (first.code, first.message))
        self.f.assert_associated(self.target)
        skipped = [record.resolution for record in first.resolution_manifest.records
                   if record.addon_id == self.missing]
        self.assertEqual(skipped, [InstallResolution.SKIPPED])
        return first.resolution_manifest

    def test_recorded_skip_is_reused_while_unrelated_drift_is_repaired(self):
        prior = self.applied_with_skip()
        self.f.backend.installed.pop(DEMO)  # unrelated, supported drift: a managed add-on is missing
        with patch.object(self.f.backend, "install_exact", wraps=self.f.backend.install_exact) as install, \
                patch.object(self.f.backend, "resolve_repository_current", side_effect=forbidden):
            result = self.f.coordinator(resolution_decider=forbidden).install_target(
                self.target, interactive=False, prior_resolution=prior)
        self.assertEqual(result.outcome, "complete", (result.code, result.message))
        self.assertEqual([call.args[0] for call in install.call_args_list], [DEMO])
        self.assertEqual(self.f.backend.installed[DEMO].version, "1.0.0")
        self.assertNotIn(self.missing, self.f.backend.installed)
        self.assertEqual(result.resolution_manifest.records, prior.records)
        self.assertEqual(result.resolution_manifest.resolution_fingerprint, prior.resolution_fingerprint)
        applied = self.f.fixture.library.current_applied_association()
        self.assertEqual(applied.resolution_fingerprint, prior.resolution_fingerprint)
        self.assertIsNone(self.f.store.inspect())

    def test_a_recorded_skip_whose_add_on_is_now_installed_is_refused_before_any_mutation(self):
        prior = self.applied_with_skip()
        self.f.backend.installed.pop(DEMO)
        intruder = FrozenInstalledAddon(self.missing, "1.0.0", True, False)
        self.f.backend.installed[self.missing] = intruder
        with patch.object(self.f.backend, "install_exact", side_effect=forbidden), \
                patch.object(self.f.backend, "set_addon_enabled", side_effect=forbidden), \
                patch.object(self.f.backend, "resolve_repository_current", side_effect=forbidden):
            result = self.f.coordinator(resolution_decider=forbidden).install_target(
                self.target, interactive=False, prior_resolution=prior)
        self.assertEqual((result.outcome, result.code), ("failed", "PRIOR_RESOLUTION_INVALID"),
                         (result.code, result.message))
        self.assertIsNone(self.f.store.inspect())
        self.assertEqual(self.f.backend.installed[self.missing], intruder)  # not removed, not changed
        self.assertNotIn(DEMO, self.f.backend.installed)                     # nothing was installed


class RestartPriorResolutionTests(unittest.TestCase):
    """The real quiescence boundary: a prior-seeded transaction, a new session, active_resume."""

    def setUp(self):
        self.f = library_install.LibraryInstallTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.target, self.provider, self.runner, self.requests = held_fixture(self.f)

    def completed_prior(self):
        first = coordinator(self.f, self.runner, self.provider).install_target(self.target)
        self.assertEqual((first.outcome, first.code), ("awaiting_restart", "QUIESCENCE_RESTART_REQUIRED"),
                         (first.code, first.message))
        self.assertEqual(first.transaction.lifecycle_stage, FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART)
        done = coordinator(self.f, self.runner, self.provider, SESSION_B).resume_after_restart()
        self.assertEqual(done.outcome, "complete", (done.code, done.message))
        self.f.assert_associated(self.target)
        return done.resolution_manifest

    def quiescent_with_prior(self):
        """A reconciliation seeded from the completed prior, stopped at quiescence."""
        prior = self.completed_prior()
        stopped = coordinator(self.f, self.runner, self.provider, SESSION_C).install_target(
            self.target, interactive=False, prior_resolution=prior)
        self.assertEqual((stopped.outcome, stopped.code), ("awaiting_restart", "QUIESCENCE_RESTART_REQUIRED"),
                         (stopped.code, stopped.message))
        durable = self.f.store.inspect()
        self.assertEqual(durable.lifecycle_stage, FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART)
        self.assertEqual(durable.prior_resolution_fingerprint, prior.resolution_fingerprint)
        self.assertEqual(durable.lifecycle_restart_count, 1)
        return prior

    def rewrite_transaction(self, mutate):
        raw = json.loads(self.f.store.transaction_path.read_text())
        mutate(raw)
        self.f.store.transaction_path.write_text(json.dumps(raw))

    def snapshot(self):
        return (self.f.store.transaction_path.read_bytes(), dict(self.f.backend.installed),
                len(self.requests), list(self.f.policy.calls), list(self.f.config.mutations))

    def test_the_durable_prior_identity_survives_a_real_round_trip(self):
        prior = self.quiescent_with_prior()
        raw = json.loads(self.f.store.transaction_path.read_text())
        self.assertEqual(raw["prior_resolution_fingerprint"], prior.resolution_fingerprint)
        self.assertEqual(FrozenInstallTransaction.from_dict(raw), self.f.store.inspect())

    def test_the_same_prior_in_the_same_session_is_not_a_resume(self):
        prior = self.quiescent_with_prior()
        before = len(self.requests)
        same = coordinator(self.f, self.runner, self.provider, SESSION_C).install_target(
            self.target, interactive=False, prior_resolution=prior)
        self.assertEqual((same.outcome, same.code), ("awaiting_restart", "SAME_SESSION"), (same.code, same.message))
        self.assertEqual(len(self.requests), before)

    def test_the_same_prior_in_a_new_session_resumes_past_quiescence(self):
        prior = self.quiescent_with_prior()
        before = len(self.requests)
        resumed = coordinator(self.f, self.runner, self.provider, SESSION_D).install_target(
            self.target, interactive=False, prior_resolution=prior)
        self.assertEqual(resumed.outcome, "complete", (resumed.code, resumed.message))
        # Configuration ran only after the active_resume gate accepted the same identity.
        self.assertEqual(len(self.requests), before + 1)
        self.assertEqual(resumed.resolution_manifest.resolution_fingerprint, prior.resolution_fingerprint)
        self.assertTrue(self.f.backend.installed[OWNER].enabled)
        self.f.assert_associated(self.target)
        self.assertIsNone(self.f.store.inspect())

    def test_an_omitted_prior_in_a_new_session_conflicts_without_mutation(self):
        self.quiescent_with_prior()
        before = self.snapshot()
        omitted = coordinator(self.f, self.runner, self.provider, SESSION_D).install_target(
            self.target, interactive=False)
        self.assertEqual((omitted.outcome, omitted.code), ("failed", "ACTIVE_TRANSACTION_CONFLICT"),
                         (omitted.code, omitted.message))
        self.assertEqual(self.snapshot(), before)

    def test_a_different_prior_identity_in_a_new_session_conflicts_without_mutation(self):
        prior = self.quiescent_with_prior()
        self.rewrite_transaction(lambda raw: raw.__setitem__("prior_resolution_fingerprint", "b" * 64))
        before = self.snapshot()
        other = coordinator(self.f, self.runner, self.provider, SESSION_D).install_target(
            self.target, interactive=False, prior_resolution=prior)
        self.assertEqual((other.outcome, other.code), ("failed", "ACTIVE_TRANSACTION_CONFLICT"),
                         (other.code, other.message))
        self.assertEqual(self.snapshot(), before)

    def test_a_legacy_empty_prior_is_not_silently_equivalent_to_a_request_with_a_prior(self):
        prior = self.quiescent_with_prior()
        self.rewrite_transaction(lambda raw: raw.pop("prior_resolution_fingerprint"))  # written before the field
        self.assertEqual(self.f.store.inspect().prior_resolution_fingerprint, "")
        before = self.snapshot()
        legacy = coordinator(self.f, self.runner, self.provider, SESSION_D).install_target(
            self.target, interactive=False, prior_resolution=prior)
        self.assertEqual((legacy.outcome, legacy.code), ("failed", "ACTIVE_TRANSACTION_CONFLICT"),
                         (legacy.code, legacy.message))
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
