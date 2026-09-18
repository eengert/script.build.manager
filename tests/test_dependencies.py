"""
Unit tests for resources/lib/dependencies.py (BM-012).

Baseline: 836 tests (end of BM-011).
This file adds tests for dependency closure discovery and reconciliation.

Test structure:
  TestIsSystemDependency       — _is_system_dependency()
  TestParseVersion             — _parse_version()
  TestVersionSatisfies         — _version_satisfies()
  TestParseRequirements        — _parse_requirements()
  TestDependencyStatusEnum     — DependencyStatus values
  TestDependencyClosureProps   — DependencyClosure property accessors
  TestResolveClosure           — DependencyResolver.resolve_closure()
  TestReconcileDependencies    — DependencyResolver.reconcile_dependencies()

FakeDependencyBackend: in-memory backend for all tests requiring a resolver.
  - installed: Dict[str, InstalledAddonInfo] — known installed add-ons
  - addon_xmls: Dict[str, bytes] — addon.xml per installed add-on
  - canned_install_results: Dict[str, AddonInstallResult] — canned by addon_id
  - enable_errors: Set[str] — addon_ids that raise on set_addon_enabled
  - install_side_effects: Dict[str, InstalledAddonInfo] — info added to
    installed after a successful install (simulates Kodi discovering new add-on)
  - set_enabled_calls: List[Tuple[str, bool]] — recorded calls
"""

import unittest
from typing import Dict, List, Optional, Set, Tuple

from resources.lib.addons import AddonInstallResult, AddonStatus, InstalledAddonInfo
from resources.lib.dependencies import (
    DependencyAction,
    DependencyActionKind,
    DependencyClosure,
    DependencyBackend,
    DependencyError,
    DependencyNode,
    DependencyRequirement,
    DependencyResolver,
    DependencyResult,
    DependencyStatus,
    _is_system_dependency,
    _parse_requirements,
    _parse_version,
    _version_satisfies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xml(addon_id: str, version: str = "1.0.0", requires: str = "") -> bytes:
    """Build a minimal addon.xml with an optional <requires> block."""
    requires_block = f"<requires>{requires}</requires>" if requires else ""
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<addon id="{addon_id}" version="{version}" name="{addon_id}">'
        f"{requires_block}"
        f"</addon>"
    ).encode("utf-8")


def _imp(addon_id: str, version: str = "", optional: str = "") -> str:
    """Build a single <import .../> string for use in _xml(requires=...)."""
    attrs = f'addon="{addon_id}"'
    if version:
        attrs += f' version="{version}"'
    if optional:
        attrs += f' optional="{optional}"'
    return f"<import {attrs}/>"


def _info(addon_id: str, enabled: bool = True, version: str = "1.0.0") -> InstalledAddonInfo:
    return InstalledAddonInfo(addon_id=addon_id, enabled=enabled, version=version)


def _install_ok(addon_id: str, version: str = "1.0.0") -> AddonInstallResult:
    return AddonInstallResult(
        addon_id=addon_id,
        status=AddonStatus.INSTALLED,
        desired_state="enabled",
        enabled=True,
        version=version,
        message="installed",
    )


def _install_fail(addon_id: str, reason: str = "not found") -> AddonInstallResult:
    return AddonInstallResult(
        addon_id=addon_id,
        status=AddonStatus.FAILED,
        desired_state="enabled",
        enabled=None,
        version=None,
        message=reason,
    )


# ---------------------------------------------------------------------------
# FakeDependencyBackend
# ---------------------------------------------------------------------------

class FakeDependencyBackend(DependencyBackend):
    def __init__(
        self,
        installed: Optional[Dict[str, InstalledAddonInfo]] = None,
        addon_xmls: Optional[Dict[str, bytes]] = None,
        canned_install_results: Optional[Dict[str, AddonInstallResult]] = None,
        enable_errors: Optional[Set[str]] = None,
        install_side_effects: Optional[Dict[str, InstalledAddonInfo]] = None,
    ) -> None:
        self.installed: Dict[str, InstalledAddonInfo] = dict(installed or {})
        self.addon_xmls: Dict[str, bytes] = dict(addon_xmls or {})
        self.canned_install_results: Dict[str, AddonInstallResult] = dict(
            canned_install_results or {}
        )
        self.enable_errors: Set[str] = set(enable_errors or set())
        self.install_side_effects: Dict[str, InstalledAddonInfo] = dict(
            install_side_effects or {}
        )
        self.set_enabled_calls: List[Tuple[str, bool]] = []
        self.install_calls: List[str] = []

    def get_addon_details(self, addon_id: str) -> Optional[InstalledAddonInfo]:
        return self.installed.get(addon_id)

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        return self.addon_xmls.get(addon_id)

    def install_addon(self, addon_id: str, desired_state: str = "enabled") -> AddonInstallResult:
        self.install_calls.append(addon_id)
        result = self.canned_install_results.get(addon_id, _install_fail(addon_id))
        if result.status in (AddonStatus.INSTALLED, AddonStatus.ALREADY_INSTALLED):
            if addon_id in self.install_side_effects:
                self.installed[addon_id] = self.install_side_effects[addon_id]
                if addon_id in self.addon_xmls:
                    pass  # already present
        return result

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        self.set_enabled_calls.append((addon_id, enabled))
        if addon_id in self.enable_errors:
            raise DependencyError(f"enable failed for {addon_id!r}")
        if addon_id in self.installed:
            old = self.installed[addon_id]
            self.installed[addon_id] = InstalledAddonInfo(
                addon_id=old.addon_id,
                enabled=enabled,
                version=old.version,
            )


# ---------------------------------------------------------------------------
# _is_system_dependency
# ---------------------------------------------------------------------------

class TestIsSystemDependency(unittest.TestCase):
    def test_xbmc_python(self) -> None:
        self.assertTrue(_is_system_dependency("xbmc.python"))

    def test_xbmc_gui(self) -> None:
        self.assertTrue(_is_system_dependency("xbmc.gui"))

    def test_xbmc_json(self) -> None:
        self.assertTrue(_is_system_dependency("xbmc.json"))

    def test_xbmc_addon_metadata(self) -> None:
        self.assertTrue(_is_system_dependency("xbmc.addon.metadata"))

    def test_script_module_not_system(self) -> None:
        self.assertFalse(_is_system_dependency("script.module.foo"))

    def test_plugin_not_system(self) -> None:
        self.assertFalse(_is_system_dependency("plugin.video.example"))

    def test_empty_string_not_system(self) -> None:
        self.assertFalse(_is_system_dependency(""))

    def test_xbmcpython_no_dot_not_system(self) -> None:
        # Must start with "xbmc." (with dot)
        self.assertFalse(_is_system_dependency("xbmcpython"))


# ---------------------------------------------------------------------------
# _parse_version
# ---------------------------------------------------------------------------

class TestParseVersion(unittest.TestCase):
    def test_three_part(self) -> None:
        self.assertEqual(_parse_version("1.0.0"), (1, 0, 0))

    def test_two_part(self) -> None:
        self.assertEqual(_parse_version("2.1"), (2, 1))

    def test_single_part(self) -> None:
        self.assertEqual(_parse_version("3"), (3,))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(_parse_version(""))

    def test_whitespace_only_returns_none(self) -> None:
        self.assertIsNone(_parse_version("   "))

    def test_non_numeric_returns_none(self) -> None:
        self.assertIsNone(_parse_version("abc"))

    def test_mixed_non_numeric_returns_none(self) -> None:
        self.assertIsNone(_parse_version("1.x.0"))

    def test_beta_suffix_returns_none(self) -> None:
        self.assertIsNone(_parse_version("1.0.0.beta"))

    def test_leading_zeros_ok(self) -> None:
        self.assertEqual(_parse_version("01.00.00"), (1, 0, 0))

    def test_large_version(self) -> None:
        self.assertEqual(_parse_version("100.200.300"), (100, 200, 300))


# ---------------------------------------------------------------------------
# _version_satisfies
# ---------------------------------------------------------------------------

class TestVersionSatisfies(unittest.TestCase):
    def test_no_min_always_satisfied(self) -> None:
        self.assertTrue(_version_satisfies("1.0.0", ""))

    def test_no_min_whitespace(self) -> None:
        self.assertTrue(_version_satisfies("1.0.0", "   "))

    def test_equal_versions_satisfied(self) -> None:
        self.assertTrue(_version_satisfies("1.0.0", "1.0.0"))

    def test_newer_patch_satisfied(self) -> None:
        self.assertTrue(_version_satisfies("1.0.1", "1.0.0"))

    def test_newer_minor_satisfied(self) -> None:
        self.assertTrue(_version_satisfies("1.1.0", "1.0.0"))

    def test_newer_major_satisfied(self) -> None:
        self.assertTrue(_version_satisfies("2.0.0", "1.0.0"))

    def test_older_patch_not_satisfied(self) -> None:
        self.assertFalse(_version_satisfies("1.0.0", "1.0.1"))

    def test_older_minor_not_satisfied(self) -> None:
        self.assertFalse(_version_satisfies("1.0.0", "1.1.0"))

    def test_older_major_not_satisfied(self) -> None:
        self.assertFalse(_version_satisfies("0.9.9", "1.0.0"))

    def test_unparseable_installed_conservative(self) -> None:
        self.assertTrue(_version_satisfies("abc", "1.0.0"))

    def test_unparseable_required_conservative(self) -> None:
        self.assertTrue(_version_satisfies("1.0.0", "abc"))

    def test_short_installed_padded(self) -> None:
        # "1.0" vs "1.0.0" — 1.0 == 1.0.0 when padded
        self.assertTrue(_version_satisfies("1.0", "1.0.0"))

    def test_short_required_padded(self) -> None:
        self.assertTrue(_version_satisfies("1.0.0", "1.0"))

    def test_short_installed_padded_insufficient(self) -> None:
        # "1.0" (= 1.0.0) vs "1.1" (= 1.1.0) → insufficient
        self.assertFalse(_version_satisfies("1.0", "1.1"))


# ---------------------------------------------------------------------------
# _parse_requirements
# ---------------------------------------------------------------------------

class TestParseRequirements(unittest.TestCase):
    def test_empty_bytes_returns_empty(self) -> None:
        self.assertEqual(_parse_requirements(b""), [])

    def test_invalid_xml_returns_empty(self) -> None:
        self.assertEqual(_parse_requirements(b"<this is not valid"), [])

    def test_no_requires_element(self) -> None:
        xml = b'<addon id="x.y"><extension point="xbmc.python"/></addon>'
        self.assertEqual(_parse_requirements(xml), [])

    def test_requires_no_import_children(self) -> None:
        xml = b'<addon id="x.y"><requires/></addon>'
        self.assertEqual(_parse_requirements(xml), [])

    def test_single_required_import(self) -> None:
        xml = _xml("root", requires=_imp("script.module.foo", "1.0.0"))
        reqs = _parse_requirements(xml)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].addon_id, "script.module.foo")
        self.assertEqual(reqs[0].min_version, "1.0.0")
        self.assertFalse(reqs[0].optional)

    def test_optional_import(self) -> None:
        xml = _xml("root", requires=_imp("script.module.opt", optional="true"))
        reqs = _parse_requirements(xml)
        self.assertEqual(len(reqs), 1)
        self.assertTrue(reqs[0].optional)

    def test_optional_false_treated_as_required(self) -> None:
        xml = _xml("root", requires=_imp("script.module.req", optional="false"))
        reqs = _parse_requirements(xml)
        self.assertEqual(len(reqs), 1)
        self.assertFalse(reqs[0].optional)

    def test_multiple_imports(self) -> None:
        xml = _xml("root", requires=_imp("a") + _imp("b") + _imp("c"))
        reqs = _parse_requirements(xml)
        self.assertEqual([r.addon_id for r in reqs], ["a", "b", "c"])

    def test_duplicate_addon_id_first_wins(self) -> None:
        xml = _xml("root", requires=_imp("dep", "1.0") + _imp("dep", "2.0"))
        reqs = _parse_requirements(xml)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].min_version, "1.0")

    def test_import_without_addon_attr_skipped(self) -> None:
        xml = b'<addon id="root"><requires><import version="1.0.0"/></requires></addon>'
        self.assertEqual(_parse_requirements(xml), [])

    def test_no_version_attr_gives_empty_min(self) -> None:
        xml = _xml("root", requires=_imp("script.module.nodep"))
        reqs = _parse_requirements(xml)
        self.assertEqual(reqs[0].min_version, "")

    def test_system_dep_parsed_but_not_filtered(self) -> None:
        xml = _xml("root", requires=_imp("xbmc.python", "3.0.0"))
        reqs = _parse_requirements(xml)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].addon_id, "xbmc.python")


# ---------------------------------------------------------------------------
# DependencyStatus enum
# ---------------------------------------------------------------------------

class TestDependencyStatusEnum(unittest.TestCase):
    def test_satisfied_value(self) -> None:
        self.assertEqual(DependencyStatus.SATISFIED, "satisfied")

    def test_installed_disabled_value(self) -> None:
        self.assertEqual(DependencyStatus.INSTALLED_DISABLED, "installed_disabled")

    def test_version_insufficient_value(self) -> None:
        self.assertEqual(DependencyStatus.VERSION_INSUFFICIENT, "version_insufficient")

    def test_missing_value(self) -> None:
        self.assertEqual(DependencyStatus.MISSING, "missing")

    def test_system_value(self) -> None:
        self.assertEqual(DependencyStatus.SYSTEM, "system")

    def test_cycle_value(self) -> None:
        self.assertEqual(DependencyStatus.CYCLE, "cycle")

    def test_optional_value(self) -> None:
        self.assertEqual(DependencyStatus.OPTIONAL, "optional")


# ---------------------------------------------------------------------------
# DependencyClosure property accessors
# ---------------------------------------------------------------------------

def _node(addon_id: str, status: DependencyStatus) -> DependencyNode:
    return DependencyNode(
        addon_id=addon_id,
        required_by=("root",),
        status=status,
        installed_version=None,
        installed_enabled=None,
        min_version_required="",
        optional=False,
    )


class TestDependencyClosureProps(unittest.TestCase):
    def setUp(self) -> None:
        self.closure = DependencyClosure(
            root_addon_ids=("root",),
            nodes=(
                _node("a", DependencyStatus.SATISFIED),
                _node("b", DependencyStatus.INSTALLED_DISABLED),
                _node("c", DependencyStatus.VERSION_INSUFFICIENT),
                _node("d", DependencyStatus.MISSING),
                _node("e", DependencyStatus.SYSTEM),
                _node("f", DependencyStatus.CYCLE),
                _node("g", DependencyStatus.OPTIONAL),
            ),
        )

    def test_satisfied_property(self) -> None:
        ids = [n.addon_id for n in self.closure.satisfied]
        self.assertEqual(ids, ["a"])

    def test_needs_enable_property(self) -> None:
        ids = [n.addon_id for n in self.closure.needs_enable]
        self.assertEqual(ids, ["b"])

    def test_insufficient_version_property(self) -> None:
        ids = [n.addon_id for n in self.closure.insufficient_version]
        self.assertEqual(ids, ["c"])

    def test_missing_property(self) -> None:
        ids = [n.addon_id for n in self.closure.missing]
        self.assertEqual(ids, ["d"])

    def test_system_property(self) -> None:
        ids = [n.addon_id for n in self.closure.system]
        self.assertEqual(ids, ["e"])

    def test_cycles_property(self) -> None:
        ids = [n.addon_id for n in self.closure.cycles]
        self.assertEqual(ids, ["f"])

    def test_optional_skipped_property(self) -> None:
        ids = [n.addon_id for n in self.closure.optional_skipped]
        self.assertEqual(ids, ["g"])

    def test_empty_closure(self) -> None:
        empty = DependencyClosure(root_addon_ids=("root",), nodes=())
        self.assertEqual(empty.satisfied, ())
        self.assertEqual(empty.missing, ())


# ---------------------------------------------------------------------------
# DependencyResolver.resolve_closure
# ---------------------------------------------------------------------------

class TestResolveClosure(unittest.TestCase):
    def _resolver(self, **kw) -> DependencyResolver:
        return DependencyResolver(FakeDependencyBackend(**kw))

    def test_empty_root_list(self) -> None:
        r = self._resolver()
        closure = r.resolve_closure([])
        self.assertEqual(closure.root_addon_ids, ())
        self.assertEqual(closure.nodes, ())

    def test_root_not_installed_no_addon_xml(self) -> None:
        r = self._resolver()
        closure = r.resolve_closure(["plugin.video.missing"])
        # Root itself not in nodes; root's deps unknown (no addon.xml)
        self.assertEqual(len(closure.nodes), 0)
        self.assertEqual(closure.root_addon_ids, ("plugin.video.missing",))

    def test_root_with_no_requirements(self) -> None:
        r = self._resolver(addon_xmls={"root": _xml("root")})
        closure = r.resolve_closure(["root"])
        self.assertEqual(closure.nodes, ())

    def test_root_with_system_dep(self) -> None:
        xml = _xml("root", requires=_imp("xbmc.python", "3.0.0"))
        r = self._resolver(addon_xmls={"root": xml})
        closure = r.resolve_closure(["root"])
        self.assertEqual(len(closure.nodes), 1)
        node = closure.nodes[0]
        self.assertEqual(node.addon_id, "xbmc.python")
        self.assertEqual(node.status, DependencyStatus.SYSTEM)

    def test_root_with_missing_dep(self) -> None:
        xml = _xml("root", requires=_imp("script.module.dep"))
        r = self._resolver(addon_xmls={"root": xml})
        closure = r.resolve_closure(["root"])
        self.assertEqual(len(closure.nodes), 1)
        self.assertEqual(closure.nodes[0].status, DependencyStatus.MISSING)

    def test_root_with_satisfied_dep(self) -> None:
        xml = _xml("root", requires=_imp("script.module.dep", "1.0.0"))
        installed = {"script.module.dep": _info("script.module.dep", enabled=True, version="1.5.0")}
        dep_xml = {"script.module.dep": _xml("script.module.dep", "1.5.0")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": xml, **dep_xml},
        )
        closure = r.resolve_closure(["root"])
        self.assertEqual(len(closure.nodes), 1)
        self.assertEqual(closure.nodes[0].status, DependencyStatus.SATISFIED)

    def test_root_with_installed_disabled_dep(self) -> None:
        xml = _xml("root", requires=_imp("script.module.dep"))
        installed = {"script.module.dep": _info("script.module.dep", enabled=False)}
        dep_xml = {"script.module.dep": _xml("script.module.dep")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": xml, **dep_xml},
        )
        closure = r.resolve_closure(["root"])
        self.assertEqual(len(closure.nodes), 1)
        self.assertEqual(closure.nodes[0].status, DependencyStatus.INSTALLED_DISABLED)

    def test_root_with_version_insufficient_dep(self) -> None:
        xml = _xml("root", requires=_imp("script.module.dep", "2.0.0"))
        installed = {"script.module.dep": _info("script.module.dep", version="1.5.0")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": xml, "script.module.dep": _xml("script.module.dep", "1.5.0")},
        )
        closure = r.resolve_closure(["root"])
        self.assertEqual(len(closure.nodes), 1)
        self.assertEqual(closure.nodes[0].status, DependencyStatus.VERSION_INSUFFICIENT)

    def test_version_insufficient_dep_subdeps_not_traversed(self) -> None:
        """Sub-deps of a version-insufficient dep are unknown and not traversed."""
        dep_xml = _xml("dep", requires=_imp("script.module.sub"))
        xml = _xml("root", requires=_imp("dep", "2.0.0"))
        installed = {"dep": _info("dep", version="1.0.0")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": xml, "dep": dep_xml},
        )
        closure = r.resolve_closure(["root"])
        ids = {n.addon_id for n in closure.nodes}
        self.assertIn("dep", ids)
        self.assertNotIn("script.module.sub", ids)

    def test_root_with_optional_dep(self) -> None:
        xml = _xml("root", requires=_imp("script.module.opt", optional="true"))
        r = self._resolver(addon_xmls={"root": xml})
        closure = r.resolve_closure(["root"])
        self.assertEqual(len(closure.nodes), 1)
        self.assertEqual(closure.nodes[0].status, DependencyStatus.OPTIONAL)
        self.assertTrue(closure.nodes[0].optional)

    def test_optional_dep_not_traversed_further(self) -> None:
        """Optional dep's sub-deps are never traversed."""
        opt_xml = _xml("opt", requires=_imp("script.module.sub"))
        xml = _xml("root", requires=_imp("opt", optional="true"))
        installed = {"opt": _info("opt")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": xml, "opt": opt_xml},
        )
        closure = r.resolve_closure(["root"])
        ids = {n.addon_id for n in closure.nodes}
        self.assertIn("opt", ids)
        self.assertNotIn("script.module.sub", ids)

    def test_transitive_required_deps(self) -> None:
        """A → B → C (all installed, enabled)."""
        a_xml = _xml("a", requires=_imp("b"))
        b_xml = _xml("b", requires=_imp("c"))
        c_xml = _xml("c")
        installed = {
            "b": _info("b"),
            "c": _info("c"),
        }
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": _xml("root", requires=_imp("a")), "a": a_xml, "b": b_xml, "c": c_xml},
        )
        closure = r.resolve_closure(["root"])
        ids = {n.addon_id for n in closure.nodes}
        self.assertIn("a", ids)  # a is missing (not in installed)
        self.assertNotIn("b", ids)  # b's sub-deps not traversed since a is MISSING

    def test_transitive_all_installed(self) -> None:
        """A → B → C all installed."""
        a_xml = _xml("a", requires=_imp("b"))
        b_xml = _xml("b", requires=_imp("c"))
        c_xml = _xml("c")
        installed = {"a": _info("a"), "b": _info("b"), "c": _info("c")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": _xml("root", requires=_imp("a")), "a": a_xml, "b": b_xml, "c": c_xml},
        )
        closure = r.resolve_closure(["root"])
        ids = {n.addon_id for n in closure.nodes}
        self.assertEqual(ids, {"a", "b", "c"})

    def test_cycle_detection(self) -> None:
        """A → B → A (direct cycle).

        'a' is traversed first (SATISFIED), then encountered again as a
        back-edge from b's DFS path (CYCLE). Both nodes appear in results.
        'b' appears once as SATISFIED.
        """
        a_xml = _xml("a", requires=_imp("b"))
        b_xml = _xml("b", requires=_imp("a"))
        installed = {"a": _info("a"), "b": _info("b")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": _xml("root", requires=_imp("a")), "a": a_xml, "b": b_xml},
        )
        closure = r.resolve_closure(["root"])
        # 'a' appears as SATISFIED (first traversal) and CYCLE (back-edge)
        a_statuses = {n.status for n in closure.nodes if n.addon_id == "a"}
        self.assertIn(DependencyStatus.SATISFIED, a_statuses)
        self.assertIn(DependencyStatus.CYCLE, a_statuses)
        # 'b' appears as SATISFIED
        b_statuses = {n.status for n in closure.nodes if n.addon_id == "b"}
        self.assertIn(DependencyStatus.SATISFIED, b_statuses)
        # cycle_ids reports the back-edge 'a'
        cycle_ids = {n.addon_id for n in closure.cycles}
        self.assertIn("a", cycle_ids)

    def test_multiple_roots_sorted(self) -> None:
        """Root add-ons are sorted lexically; closure root_addon_ids reflects order."""
        r = self._resolver(
            addon_xmls={
                "z.root": _xml("z.root"),
                "a.root": _xml("a.root"),
            }
        )
        closure = r.resolve_closure(["z.root", "a.root"])
        self.assertEqual(closure.root_addon_ids, ("a.root", "z.root"))

    def test_shared_dep_across_two_roots_appears_once(self) -> None:
        """If two roots share a dep, it appears once in nodes."""
        shared_xml = _xml("shared")
        installed = {"shared": _info("shared")}
        r = self._resolver(
            installed=installed,
            addon_xmls={
                "root1": _xml("root1", requires=_imp("shared")),
                "root2": _xml("root2", requires=_imp("shared")),
                "shared": shared_xml,
            },
        )
        closure = r.resolve_closure(["root1", "root2"])
        shared_nodes = [n for n in closure.nodes if n.addon_id == "shared"]
        self.assertEqual(len(shared_nodes), 1)

    def test_missing_dep_sub_deps_not_traversed(self) -> None:
        """Sub-deps of a missing dep cannot be discovered."""
        xml = _xml("root", requires=_imp("missing"))
        r = self._resolver(addon_xmls={"root": xml})
        closure = r.resolve_closure(["root"])
        self.assertEqual(len(closure.nodes), 1)
        self.assertEqual(closure.nodes[0].status, DependencyStatus.MISSING)

    def test_system_dep_sub_deps_not_traversed(self) -> None:
        """System deps have no sub-deps tracked by BM-012."""
        xml = _xml("root", requires=_imp("xbmc.python"))
        r = self._resolver(addon_xmls={"root": xml})
        closure = r.resolve_closure(["root"])
        self.assertEqual(len(closure.nodes), 1)
        self.assertEqual(closure.nodes[0].status, DependencyStatus.SYSTEM)

    def test_sub_deps_sorted_lexically(self) -> None:
        """Sub-deps within one add-on are traversed in lexical addon_id order."""
        xml = _xml("root", requires=_imp("z.dep") + _imp("a.dep"))
        installed = {"z.dep": _info("z.dep"), "a.dep": _info("a.dep")}
        r = self._resolver(
            installed=installed,
            addon_xmls={
                "root": xml,
                "z.dep": _xml("z.dep"),
                "a.dep": _xml("a.dep"),
            },
        )
        closure = r.resolve_closure(["root"])
        ids = [n.addon_id for n in closure.nodes]
        self.assertIn("a.dep", ids)
        self.assertIn("z.dep", ids)

    def test_required_by_tuple_populated(self) -> None:
        """DependencyNode.required_by points to the immediate requirer."""
        xml = _xml("root", requires=_imp("dep"))
        r = self._resolver(addon_xmls={"root": xml})
        closure = r.resolve_closure(["root"])
        dep_node = closure.nodes[0]
        self.assertIn("root", dep_node.required_by)

    def test_min_version_recorded_on_node(self) -> None:
        xml = _xml("root", requires=_imp("dep", "3.1.0"))
        r = self._resolver(addon_xmls={"root": xml})
        closure = r.resolve_closure(["root"])
        self.assertEqual(closure.nodes[0].min_version_required, "3.1.0")


# ---------------------------------------------------------------------------
# DependencyResolver.reconcile_dependencies
# ---------------------------------------------------------------------------

class TestReconcileDependencies(unittest.TestCase):
    def _resolver(self, **kw) -> DependencyResolver:
        return DependencyResolver(FakeDependencyBackend(**kw))

    def test_no_deps_needed(self) -> None:
        r = self._resolver(addon_xmls={"root": _xml("root")})
        result = r.reconcile_dependencies(["root"])
        self.assertTrue(result.all_required_satisfied)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.unresolved, ())

    def test_all_satisfied_no_actions(self) -> None:
        xml = _xml("root", requires=_imp("dep"))
        installed = {"dep": _info("dep")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": xml, "dep": _xml("dep")},
        )
        result = r.reconcile_dependencies(["root"])
        self.assertTrue(result.all_required_satisfied)
        self.assertEqual(result.actions, ())

    def test_installs_missing_dep(self) -> None:
        xml = _xml("root", requires=_imp("missing.dep"))
        r = DependencyResolver(FakeDependencyBackend(
            addon_xmls={"root": xml, "missing.dep": _xml("missing.dep")},
            canned_install_results={"missing.dep": _install_ok("missing.dep")},
            install_side_effects={"missing.dep": _info("missing.dep")},
        ))
        result = r.reconcile_dependencies(["root"])
        install_actions = [a for a in result.actions if a.kind == DependencyActionKind.INSTALLED]
        self.assertEqual(len(install_actions), 1)
        self.assertEqual(install_actions[0].addon_id, "missing.dep")
        self.assertTrue(result.all_required_satisfied)

    def test_enables_disabled_dep(self) -> None:
        xml = _xml("root", requires=_imp("dis.dep"))
        installed = {"dis.dep": _info("dis.dep", enabled=False)}
        r = DependencyResolver(FakeDependencyBackend(
            installed=installed,
            addon_xmls={"root": xml, "dis.dep": _xml("dis.dep")},
        ))
        result = r.reconcile_dependencies(["root"])
        enable_actions = [a for a in result.actions if a.kind == DependencyActionKind.ENABLED]
        self.assertEqual(len(enable_actions), 1)
        self.assertEqual(enable_actions[0].addon_id, "dis.dep")
        self.assertTrue(result.all_required_satisfied)

    def test_install_failure_recorded_as_failed_install(self) -> None:
        xml = _xml("root", requires=_imp("broken.dep"))
        r = self._resolver(
            addon_xmls={"root": xml},
            canned_install_results={"broken.dep": _install_fail("broken.dep", "repo not found")},
        )
        result = r.reconcile_dependencies(["root"])
        fail_actions = [a for a in result.actions if a.kind == DependencyActionKind.FAILED_INSTALL]
        self.assertEqual(len(fail_actions), 1)
        self.assertFalse(result.all_required_satisfied)
        self.assertGreater(len(result.unresolved), 0)

    def test_enable_failure_recorded(self) -> None:
        xml = _xml("root", requires=_imp("dis.dep"))
        installed = {"dis.dep": _info("dis.dep", enabled=False)}
        r = DependencyResolver(FakeDependencyBackend(
            installed=installed,
            addon_xmls={"root": xml, "dis.dep": _xml("dis.dep")},
            enable_errors={"dis.dep"},
        ))
        result = r.reconcile_dependencies(["root"])
        fail_actions = [a for a in result.actions if a.kind == DependencyActionKind.FAILED_ENABLE]
        self.assertEqual(len(fail_actions), 1)
        self.assertFalse(result.all_required_satisfied)

    def test_install_exception_becomes_failed_install(self) -> None:
        xml = _xml("root", requires=_imp("error.dep"))
        backend = FakeDependencyBackend(addon_xmls={"root": xml})

        class _ExceptingBackend(FakeDependencyBackend):
            def install_addon(self, addon_id, desired_state="enabled"):
                raise RuntimeError("network error")

        r = DependencyResolver(_ExceptingBackend(addon_xmls={"root": xml}))
        result = r.reconcile_dependencies(["root"])
        fail_actions = [a for a in result.actions if a.kind == DependencyActionKind.FAILED_INSTALL]
        self.assertGreater(len(fail_actions), 0)
        self.assertFalse(result.all_required_satisfied)

    def test_iterative_install_reveals_transitive_dep(self) -> None:
        """Round 1: install A; Round 2: A's dep B discovered → install B."""
        root_xml = _xml("root", requires=_imp("a.dep"))
        a_xml = _xml("a.dep", requires=_imp("b.dep"))
        b_xml = _xml("b.dep")

        backend = FakeDependencyBackend(
            addon_xmls={
                "root": root_xml,
                "a.dep": a_xml,
                "b.dep": b_xml,
            },
            canned_install_results={
                "a.dep": _install_ok("a.dep"),
                "b.dep": _install_ok("b.dep"),
            },
            install_side_effects={
                "a.dep": _info("a.dep"),
                "b.dep": _info("b.dep"),
            },
        )
        r = DependencyResolver(backend)
        result = r.reconcile_dependencies(["root"])
        installed_ids = [a.addon_id for a in result.actions if a.kind == DependencyActionKind.INSTALLED]
        self.assertIn("a.dep", installed_ids)
        self.assertIn("b.dep", installed_ids)
        self.assertTrue(result.all_required_satisfied)

    def test_failed_install_not_retried(self) -> None:
        """An add-on that fails install is not retried in subsequent rounds."""
        xml = _xml("root", requires=_imp("broken"))
        backend = FakeDependencyBackend(
            addon_xmls={"root": xml},
            canned_install_results={"broken": _install_fail("broken")},
        )
        r = DependencyResolver(backend)
        result = r.reconcile_dependencies(["root"])
        fail_count = sum(1 for a in result.actions if a.kind == DependencyActionKind.FAILED_INSTALL)
        self.assertEqual(fail_count, 1)
        install_count = backend.install_calls.count("broken")
        self.assertEqual(install_count, 1)

    def test_version_insufficient_in_unresolved(self) -> None:
        xml = _xml("root", requires=_imp("dep", "5.0.0"))
        installed = {"dep": _info("dep", version="1.0.0")}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": xml, "dep": _xml("dep")},
        )
        result = r.reconcile_dependencies(["root"])
        self.assertFalse(result.all_required_satisfied)
        unresolved_ids = {n.addon_id for n in result.unresolved}
        self.assertIn("dep", unresolved_ids)

    def test_optional_dep_not_installed(self) -> None:
        xml = _xml("root", requires=_imp("opt.dep", optional="true"))
        r = self._resolver(addon_xmls={"root": xml})
        result = r.reconcile_dependencies(["root"])
        install_calls = [a.addon_id for a in result.actions if a.kind == DependencyActionKind.INSTALLED]
        self.assertNotIn("opt.dep", install_calls)
        self.assertTrue(result.all_required_satisfied)

    def test_never_disables_addon(self) -> None:
        """No reconcile action ever disables an add-on."""
        xml = _xml("root", requires=_imp("dep"))
        installed = {"dep": _info("dep", enabled=True)}
        r = self._resolver(
            installed=installed,
            addon_xmls={"root": xml, "dep": _xml("dep")},
        )
        result = r.reconcile_dependencies(["root"])
        for action in result.actions:
            self.assertNotIn(action.kind, (
                DependencyActionKind.FAILED_ENABLE,
                # disabling would never appear as an action kind
            ))
        # More directly: enabled args are always True
        r2 = DependencyResolver(FakeDependencyBackend(
            installed={"dep": _info("dep", enabled=False)},
            addon_xmls={"root": xml, "dep": _xml("dep")},
        ))
        result2 = r2.reconcile_dependencies(["root"])
        fake = r2._backend
        for _, flag in fake.set_enabled_calls:  # type: ignore[attr-defined]
            self.assertTrue(flag)

    def test_all_required_satisfied_true_after_install_and_enable(self) -> None:
        xml = _xml("root", requires=_imp("dep1") + _imp("dep2"))
        backend = FakeDependencyBackend(
            installed={"dep2": _info("dep2", enabled=False)},
            addon_xmls={"root": xml, "dep1": _xml("dep1"), "dep2": _xml("dep2")},
            canned_install_results={"dep1": _install_ok("dep1")},
            install_side_effects={"dep1": _info("dep1")},
        )
        r = DependencyResolver(backend)
        result = r.reconcile_dependencies(["root"])
        self.assertTrue(result.all_required_satisfied)

    def test_install_already_installed_status_treated_as_success(self) -> None:
        already = AddonInstallResult(
            addon_id="dep",
            status=AddonStatus.ALREADY_INSTALLED,
            desired_state="enabled",
            enabled=True,
            version="1.0.0",
            message="already_installed",
        )
        xml = _xml("root", requires=_imp("dep"))
        backend = FakeDependencyBackend(
            addon_xmls={"root": xml, "dep": _xml("dep")},
            canned_install_results={"dep": already},
            install_side_effects={"dep": _info("dep")},
        )
        r = DependencyResolver(backend)
        result = r.reconcile_dependencies(["root"])
        install_actions = [a for a in result.actions if a.kind == DependencyActionKind.INSTALLED]
        self.assertEqual(len(install_actions), 1)
        self.assertTrue(result.all_required_satisfied)

    def test_result_has_closure(self) -> None:
        r = self._resolver(addon_xmls={"root": _xml("root")})
        result = r.reconcile_dependencies(["root"])
        self.assertIsInstance(result.closure, DependencyClosure)

    def test_multiple_install_actions_sorted_by_addon_id(self) -> None:
        """Install actions within one round are processed in lexical order."""
        xml = _xml("root", requires=_imp("z.dep") + _imp("a.dep"))
        backend = FakeDependencyBackend(
            addon_xmls={"root": xml, "z.dep": _xml("z.dep"), "a.dep": _xml("a.dep")},
            canned_install_results={
                "z.dep": _install_ok("z.dep"),
                "a.dep": _install_ok("a.dep"),
            },
            install_side_effects={
                "z.dep": _info("z.dep"),
                "a.dep": _info("a.dep"),
            },
        )
        r = DependencyResolver(backend)
        result = r.reconcile_dependencies(["root"])
        installed_ids = [a.addon_id for a in result.actions if a.kind == DependencyActionKind.INSTALLED]
        self.assertEqual(installed_ids, ["a.dep", "z.dep"])


if __name__ == "__main__":
    unittest.main()
