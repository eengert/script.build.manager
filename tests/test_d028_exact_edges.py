"""Exact archive requirements remain authoritative after manifest resealing."""
from dataclasses import replace
import unittest
from resources.lib import frozen_install as fi
from resources.lib.frozen import FrozenBuildManifest, DependencyEdge, CaptureError
from tools.bm_item8_af3_fixture import prepare
from tests.builtin_evidence import SyntheticBuiltinBackend


class ExactArtifactEdgesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.store = prepare()

    def altered(self, transform, drop_gui=False):
        nodes = tuple(replace(n, dependency_edges=transform(n)) if n.addon_id == 'skin.arctic.fuse.3'
                      else n for n in self.manifest.addons if not (drop_gui and n.addon_id == 'xbmc.gui'))
        return FrozenBuildManifest.from_json(replace(self.manifest, addons=nodes).to_json())

    def assert_invalid(self, manifest):
        for validator in (fi.validate_frozen_manifest, fi.validate_frozen_install_plan):
            with self.subTest(validator=validator.__name__):
                with self.assertRaisesRegex(fi.FrozenInstallValidationError, 'artifact dependenc'):
                    validator(manifest, self.store)

    def test_v2_resealed_manifest_drops_gui_edge_and_node(self):
        m = self.altered(lambda n: tuple(e for e in n.dependency_edges if e.addon_id != 'xbmc.gui'), True)
        self.assert_invalid(m)

    def test_dropped_builtin_edge(self):
        self.assert_invalid(self.altered(lambda n: tuple(e for e in n.dependency_edges if e.addon_id != 'xbmc.gui')))

    def test_dropped_system_node(self):
        m = replace(self.manifest, addons=tuple(n for n in self.manifest.addons if n.addon_id != 'xbmc.gui'))
        with self.assertRaises(fi.FrozenInstallValidationError):
            fi.validate_frozen_manifest(m, self.store)

    def test_changed_minimum_optionality_managed_edge_and_attribution(self):
        for target, change in [('xbmc.gui', {'min_version': '1.0.0'}),
                               ('xbmc.gui', {'optional': True}),
                               ('script.skinvariables', {'min_version': '999.0.0'}),
                               ('xbmc.gui', {'required_by': ('forged.parent',)})]:
            with self.subTest(target=target, change=change):
                self.assert_invalid(self.altered(lambda n: tuple(replace(e, **change) if e.addon_id == target else e
                                                                for e in n.dependency_edges)))

    def test_extra_edge(self):
        self.assert_invalid(self.altered(lambda n: n.dependency_edges + (DependencyEdge('xbmc.fake'),)))

    def test_forged_fingerprint(self):
        raw = self.manifest.to_dict()
        raw['software_fingerprint'] = '0' * 64
        with self.assertRaises(CaptureError):
            FrozenBuildManifest.from_dict(raw)

    def test_faithful_fixture_and_v1_no_gui_proof(self):
        plan = fi.validate_frozen_manifest(self.manifest, self.store)
        self.assertEqual((22, 45), (len(plan.nodes), sum(len(n.dependency_edges) for n in plan.nodes.values())))
        for requirements in ((), fi._repository_required_addon_ids(self.store, packages=())):
            with self.assertRaises(fi.FrozenPlatformRequirementError):
                fi.verify_platform_requirements(plan, SyntheticBuiltinBackend(),
                    planned_versions=fi._planned_versions(plan, ()), required_addon_ids=requirements)

    def test_bound_artifact_requirements_survive_manifest_edge_removal_at_admission(self):
        from tests.test_d028_admission import BuiltinAdmissionTests
        fixture = BuiltinAdmissionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        m = fixture.manifest()
        plan = fi.validate_frozen_manifest(m, fixture.artifacts)
        changed_nodes = tuple(replace(n, dependency_edges=()) if n.artifact else n
                              for n in m.addons if n.addon_id != 'xbmc.gui')
        changed = replace(plan, manifest=replace(m, addons=changed_nodes),
                          nodes={n.addon_id: n for n in changed_nodes})
        fixture.backend.builtin_state.pop('xbmc.gui')
        with self.assertRaises(fi.FrozenPlatformRequirementError):
            fi.verify_platform_requirements(changed, fixture.backend,
                planned_versions=fi._planned_versions(changed, ()))

    def test_unbound_managed_plan_is_not_admission_authority(self):
        from tests.test_d028_admission import BuiltinAdmissionTests
        fixture = BuiltinAdmissionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        m = fixture.manifest()
        plan = fi.FrozenManifestPlan(m, {n.addon_id: n for n in m.addons}, ())
        with self.assertRaises(fi.FrozenPlatformRequirementError):
            fi.verify_platform_requirements(plan, fixture.backend,
                planned_versions=fi._planned_versions(plan, ()))

    def test_v3_resealed_source_cannot_hide_actual_zip_derived_stronger_requirement(self):
        from tests.test_d028_admission import BuiltinAdmissionTests
        from resources.lib.addons import RepositoryPackage
        fixture = BuiltinAdmissionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        manifest = fixture.manifest('999.0.0')
        plan = fi.validate_frozen_manifest(manifest, fixture.artifacts)
        root = manifest.addons[0]
        # Independent actual byte-derived requirements, with the source resealed
        # to lie about its minimum. Both exact validation and final admission refuse.
        altered = replace(manifest, addons=(replace(root, dependency_edges=(DependencyEdge('xbmc.gui', '5.17.0'),)),)
                          + manifest.addons[1:])
        with self.assertRaises(fi.FrozenInstallValidationError):
            fi.validate_frozen_manifest(altered, fixture.artifacts)
        requirements = fi._repository_required_addon_ids(None, packages=(RepositoryPackage(
            root.addon_id, 'repository.fixture', root.version, fixture.artifacts.read_bytes(root.artifact.sha256)),))
        checked = replace(plan, manifest=altered, nodes={n.addon_id: n for n in altered.addons})
        with self.assertRaises(fi.FrozenPlatformRequirementError):
            fi.verify_platform_requirements(checked, fixture.backend,
                planned_versions=fi._planned_versions(checked, ()), required_addon_ids=requirements)
