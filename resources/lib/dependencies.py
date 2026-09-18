"""
Build Manager dependency closure discovery and reconciliation (BM-012).

Public API
----------
DependencyResolver(backend).resolve_closure(root_addon_ids) -> DependencyClosure
    Pure graph discovery: reads installed add-on addon.xml and computes the
    required transitive dependency closure. No installation or state mutation.
    Missing add-ons are recorded with status=MISSING; their transitive deps
    cannot be discovered until they are installed.

DependencyResolver(backend).reconcile_dependencies(root_addon_ids) -> DependencyResult
    Discovers the closure, installs missing required add-ons via BM-011,
    enables installed-but-disabled required add-ons, and iterates until
    stable (up to _MAX_RECONCILE_ROUNDS). Returns a structured result
    containing all actions taken and any unresolved dependencies.

KodiRuntimeDependencyBackend()
    Production backend. Uses xbmc/xbmcvfs for addon.xml reads and JSON-RPC
    for installed state. Delegates installation to AddonManager with
    KodiRuntimeAddonBackend. Lazy Kodi imports.

DependencyBackend
    Abstract backend interface. Subclass and override all methods to build
    a test fake. All abstract methods raise NotImplementedError by default.

Result types
------------
DependencyStatus
    SATISFIED | INSTALLED_DISABLED | VERSION_INSUFFICIENT
    | MISSING | SYSTEM | CYCLE | OPTIONAL

DependencyRequirement(addon_id, min_version, optional)
    One <import> element from a <requires> block.

DependencyNode(addon_id, required_by, status, installed_version,
               installed_enabled, min_version_required, optional, cycle_path)
    One discovered dependency in the transitive closure.

DependencyClosure(root_addon_ids, nodes)
    The full closure with per-status convenience properties.

DependencyActionKind
    INSTALLED | ENABLED | SKIPPED_SATISFIED | FAILED_INSTALL | FAILED_ENABLE
    | SKIPPED_VERSION_INSUFFICIENT

DependencyAction(addon_id, kind, reason, required_by)
    One action taken (or skipped) during reconciliation.

DependencyResult(closure, actions, all_required_satisfied, unresolved)
    Complete result of reconcile_dependencies().

Errors
------
DependencyError          -- base class for all dependency errors

Architecture (BM-012)
---------------------
Dependency metadata is read from installed add-on addon.xml files on the
filesystem via the backend. For missing add-ons, the status is MISSING and
transitive discovery continues after installation in subsequent rounds.

Required vs optional
--------------------
<import optional="true"> is never installed or enabled. It is recorded with
status=OPTIONAL and excluded from the required closure. <import> with no
optional attribute, or optional="false", is treated as required.

System/builtin dependencies
----------------------------
Add-on IDs beginning with "xbmc." are Kodi-provided builtins. They are
never installed by BM-012. They are recorded with status=SYSTEM and treated
as satisfied. Examples: xbmc.python, xbmc.gui, xbmc.json.

Version semantics
-----------------
<import version="x.y.z"> specifies the MINIMUM required version. Installed
version >= required minimum (tuple int comparison) → satisfied. Unparseable
versions are treated as satisfied (conservative). BM-012 never downgrades.
If installed version is below the minimum, the node is VERSION_INSUFFICIENT
and appears in unresolved; BM-012 does NOT upgrade (future work).

Circular dependency handling
-----------------------------
DFS uses visiting/visited sets. A node encountered while in the current DFS
path is recorded as CYCLE. Cycle detection does not halt the traversal;
other branches are still processed. Deterministic (deps sorted lexically).

Safety invariant
----------------
BM-012 never disables or removes any add-on (managed or unmanaged). It only
installs missing required add-ons and enables disabled required add-ons.

BM-013 boundary
---------------
BM-012 enables dependencies required by the root add-ons. BM-013 handles
drift reconciliation for the managed add-on set itself.

Stdlib only — no new runtime dependencies.
No shell commands, no direct database edits.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# Type alias used in docstrings — imported lazily at runtime
# InstalledAddonInfo and AddonInstallResult come from resources.lib.addons


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class DependencyError(Exception):
    """Base class for all dependency operation errors."""


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class DependencyStatus(str, Enum):
    """Status of one dependency node in the transitive closure."""
    SATISFIED = "satisfied"
    INSTALLED_DISABLED = "installed_disabled"
    VERSION_INSUFFICIENT = "version_insufficient"
    MISSING = "missing"
    SYSTEM = "system"
    CYCLE = "cycle"
    OPTIONAL = "optional"


# ---------------------------------------------------------------------------
# Action kinds
# ---------------------------------------------------------------------------

class DependencyActionKind(str, Enum):
    """The kind of action taken (or not taken) during reconciliation."""
    INSTALLED = "installed"
    ENABLED = "enabled"
    SKIPPED_SATISFIED = "skipped_satisfied"
    FAILED_INSTALL = "failed_install"
    FAILED_ENABLE = "failed_enable"
    SKIPPED_VERSION_INSUFFICIENT = "skipped_version_insufficient"


# ---------------------------------------------------------------------------
# Data types (frozen)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DependencyRequirement:
    """One <import> element from an add-on's <requires> section."""
    addon_id: str
    min_version: str      # "" = no minimum version specified
    optional: bool


@dataclass(frozen=True)
class DependencyNode:
    """One discovered dependency in the transitive closure.

    required_by: tuple of addon_ids that led to this node, immediate requirer
    first. Example: if root → A → B, then B.required_by = ("A", "root").
    cycle_path: only set for CYCLE nodes; the detected cycle as a tuple.
    """
    addon_id: str
    required_by: Tuple[str, ...]
    status: DependencyStatus
    installed_version: Optional[str]
    installed_enabled: Optional[bool]
    min_version_required: str     # "" = no minimum declared for this edge
    optional: bool
    cycle_path: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class DependencyClosure:
    """Full transitive dependency closure for a set of root add-ons.

    The root add-ons themselves are not included in nodes — only their deps.
    """
    root_addon_ids: Tuple[str, ...]
    nodes: Tuple[DependencyNode, ...]

    @property
    def satisfied(self) -> Tuple[DependencyNode, ...]:
        return tuple(n for n in self.nodes if n.status == DependencyStatus.SATISFIED)

    @property
    def needs_enable(self) -> Tuple[DependencyNode, ...]:
        return tuple(n for n in self.nodes if n.status == DependencyStatus.INSTALLED_DISABLED)

    @property
    def insufficient_version(self) -> Tuple[DependencyNode, ...]:
        return tuple(n for n in self.nodes if n.status == DependencyStatus.VERSION_INSUFFICIENT)

    @property
    def missing(self) -> Tuple[DependencyNode, ...]:
        return tuple(n for n in self.nodes if n.status == DependencyStatus.MISSING)

    @property
    def system(self) -> Tuple[DependencyNode, ...]:
        return tuple(n for n in self.nodes if n.status == DependencyStatus.SYSTEM)

    @property
    def cycles(self) -> Tuple[DependencyNode, ...]:
        return tuple(n for n in self.nodes if n.status == DependencyStatus.CYCLE)

    @property
    def optional_skipped(self) -> Tuple[DependencyNode, ...]:
        return tuple(n for n in self.nodes if n.status == DependencyStatus.OPTIONAL)


@dataclass(frozen=True)
class DependencyAction:
    """One action taken (or skipped) during reconcile_dependencies()."""
    addon_id: str
    kind: DependencyActionKind
    reason: str
    required_by: Tuple[str, ...]


@dataclass(frozen=True)
class DependencyResult:
    """Complete result of a reconcile_dependencies() call."""
    closure: DependencyClosure
    actions: Tuple[DependencyAction, ...]
    all_required_satisfied: bool
    unresolved: Tuple[DependencyNode, ...]  # MISSING+failed, VERSION_INSUFFICIENT


# ---------------------------------------------------------------------------
# System dependency detection
# ---------------------------------------------------------------------------

def _is_system_dependency(addon_id: str) -> bool:
    """True if addon_id is a Kodi-provided builtin that should never be installed.

    Kodi provides add-ons whose IDs start with "xbmc." as part of the runtime.
    Examples: xbmc.python, xbmc.gui, xbmc.json, xbmc.addon.metadata.
    These are treated as always-satisfied and never passed to install_addon().
    """
    return addon_id.startswith("xbmc.")


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

def _parse_version(version: str) -> Optional[Tuple[int, ...]]:
    """Parse a dotted version string into a tuple of ints.

    Returns None if the string is empty or cannot be parsed.
    Examples: "1.0.0" → (1, 0, 0); "2.1" → (2, 1); "abc" → None.
    """
    if not version or not version.strip():
        return None
    parts = version.strip().split(".")
    try:
        return tuple(int(p) for p in parts)
    except (ValueError, TypeError):
        return None


def _version_satisfies(installed: str, required_min: str) -> bool:
    """True if installed version satisfies the required minimum.

    Returns True (conservative) when required_min is empty/blank (no minimum).
    Returns True (conservative) when either version string cannot be parsed.
    Pads shorter tuples with zeros for comparison (e.g. "1.0" vs "1.0.1").
    Never returns False based solely on a parsing failure.
    """
    if not required_min or not required_min.strip():
        return True
    inst = _parse_version(installed)
    req = _parse_version(required_min)
    if inst is None or req is None:
        return True  # conservative
    max_len = max(len(inst), len(req))
    inst_padded = inst + (0,) * (max_len - len(inst))
    req_padded = req + (0,) * (max_len - len(req))
    return inst_padded >= req_padded


# ---------------------------------------------------------------------------
# Addon.xml dependency parsing
# ---------------------------------------------------------------------------

def _parse_requirements(xml_bytes: bytes) -> List[DependencyRequirement]:
    """Parse <requires><import .../> elements from addon.xml bytes.

    Returns an empty list when:
    - xml_bytes is empty
    - XML cannot be parsed
    - There is no <requires> element
    - <requires> has no <import> children

    Deduplicates import entries by addon_id (first occurrence wins).
    Does not raise on malformed input — returns what can be parsed.
    """
    if not xml_bytes:
        return []
    try:
        root_el = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    requires_el = root_el.find("requires")
    if requires_el is None:
        return []

    reqs: List[DependencyRequirement] = []
    seen_ids: Set[str] = set()

    for import_el in requires_el.findall("import"):
        dep_id = (import_el.get("addon") or "").strip()
        if not dep_id:
            continue
        if dep_id in seen_ids:
            continue
        seen_ids.add(dep_id)

        min_version = (import_el.get("version") or "").strip()
        optional_str = (import_el.get("optional") or "false").lower().strip()
        optional = optional_str == "true"

        reqs.append(DependencyRequirement(
            addon_id=dep_id,
            min_version=min_version,
            optional=optional,
        ))

    return reqs


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class DependencyBackend:
    """Injectable backend for Kodi runtime calls in BM-012.

    Override all methods in a concrete subclass. Defaults raise
    NotImplementedError so incomplete fakes surface missing stubs immediately.
    """

    def get_addon_details(self, addon_id: str):
        """Return InstalledAddonInfo for an installed add-on, or None if absent.

        Must return None (not raise) when the add-on is not installed.
        May raise DependencyError on genuine infrastructure failure.
        """
        raise NotImplementedError

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        """Read addon.xml bytes for an installed add-on.

        Returns None if the add-on is not installed, addon.xml does not exist,
        or the file cannot be read. Never raises on missing file.
        """
        raise NotImplementedError

    def install_addon(self, addon_id: str, desired_state: str = "enabled"):
        """Install addon_id using BM-011 AddonManager.install().

        Returns an AddonInstallResult. The caller inspects result.status.
        """
        raise NotImplementedError

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        """Enable or disable an installed add-on.

        Raises DependencyError on failure (e.g. JSON-RPC error, add-on absent).
        BM-012 only ever calls this with enabled=True (enabling disabled deps).
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# DFS graph traversal (pure — no side effects)
# ---------------------------------------------------------------------------

def _dfs(
    dep_id: str,
    req: DependencyRequirement,
    requirer_path: Tuple[str, ...],
    backend: DependencyBackend,
    visited: Dict[str, DependencyNode],
    visiting: List[str],
    results: List[DependencyNode],
) -> None:
    """Depth-first traversal to collect all required transitive dependencies.

    dep_id: the dependency to process now
    req: the DependencyRequirement edge that caused this traversal
    requirer_path: tuple of addon_ids that led here (immediate requirer first)
    backend: read-only backend calls only
    visited: addon_ids fully processed → their final DependencyNode
    visiting: addon_ids currently in the DFS stack (cycle detection)
    results: accumulates DependencyNode entries
    """
    # System dependency: always satisfied, never install, short-circuit
    if _is_system_dependency(dep_id):
        if dep_id not in visited:
            sys_node = DependencyNode(
                addon_id=dep_id,
                required_by=requirer_path,
                status=DependencyStatus.SYSTEM,
                installed_version=None,
                installed_enabled=None,
                min_version_required=req.min_version,
                optional=False,
            )
            results.append(sys_node)
            visited[dep_id] = sys_node
        return

    # Cycle detection must precede the visited check: a node can be in both
    # visited (processed on an earlier branch) and visiting (in the current
    # DFS path) when the graph has a cycle that loops through a shared node.
    # Checking visiting first ensures cycles are detected correctly.
    if dep_id in visiting:
        cycle_path = tuple(visiting[visiting.index(dep_id):]) + (dep_id,)
        cycle_node = DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.CYCLE,
            installed_version=None,
            installed_enabled=None,
            min_version_required=req.min_version,
            optional=False,
            cycle_path=cycle_path,
        )
        results.append(cycle_node)
        # Do NOT add to visited — a cycle node is not fully processed
        return

    # Already fully processed — skip
    if dep_id in visited:
        return

    # Query installed state
    try:
        details = backend.get_addon_details(dep_id)
    except Exception:
        details = None

    if details is None:
        node = DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.MISSING,
            installed_version=None,
            installed_enabled=None,
            min_version_required=req.min_version,
            optional=False,
        )
        results.append(node)
        visited[dep_id] = node
        # Cannot read addon.xml for a missing dep; transitive deps unknown
        return

    # Installed — classify
    inst_version = details.version or ""
    if req.min_version and not _version_satisfies(inst_version, req.min_version):
        status = DependencyStatus.VERSION_INSUFFICIENT
    elif not details.enabled:
        status = DependencyStatus.INSTALLED_DISABLED
    else:
        status = DependencyStatus.SATISFIED

    node = DependencyNode(
        addon_id=dep_id,
        required_by=requirer_path,
        status=status,
        installed_version=inst_version,
        installed_enabled=details.enabled,
        min_version_required=req.min_version,
        optional=False,
    )
    results.append(node)
    visited[dep_id] = node

    if status == DependencyStatus.VERSION_INSUFFICIENT:
        # Cannot safely traverse a version-insufficient dep's sub-deps
        return

    # Read addon.xml and traverse sub-dependencies
    try:
        xml_bytes = backend.read_addon_xml(dep_id)
    except Exception:
        xml_bytes = None

    if not xml_bytes:
        return

    sub_reqs = _parse_requirements(xml_bytes)
    # Sort lexically by addon_id for deterministic traversal
    sub_reqs.sort(key=lambda r: r.addon_id)

    visiting.append(dep_id)
    for sub_req in sub_reqs:
        if sub_req.optional:
            # Record optional deps but do not traverse or require
            if sub_req.addon_id not in visited and sub_req.addon_id not in visiting:
                opt_already = any(
                    n.addon_id == sub_req.addon_id and n.status == DependencyStatus.OPTIONAL
                    for n in results
                )
                if not opt_already:
                    opt_node = DependencyNode(
                        addon_id=sub_req.addon_id,
                        required_by=(dep_id,) + requirer_path,
                        status=DependencyStatus.OPTIONAL,
                        installed_version=None,
                        installed_enabled=None,
                        min_version_required=sub_req.min_version,
                        optional=True,
                    )
                    results.append(opt_node)
        else:
            _dfs(
                sub_req.addon_id,
                sub_req,
                (dep_id,) + requirer_path,
                backend,
                visited,
                visiting,
                results,
            )
    visiting.remove(dep_id)


# ---------------------------------------------------------------------------
# Reconcile-round constant
# ---------------------------------------------------------------------------

_MAX_RECONCILE_ROUNDS: int = 10


# ---------------------------------------------------------------------------
# DependencyResolver
# ---------------------------------------------------------------------------

class DependencyResolver:
    """Dependency closure discovery and reconciliation.

    Usage (pure discovery, no mutation):
        backend = KodiRuntimeDependencyBackend()
        resolver = DependencyResolver(backend)
        closure = resolver.resolve_closure(["plugin.video.example"])

    Usage (full reconciliation with install + enable):
        result = resolver.reconcile_dependencies(["plugin.video.example"])

    For testing:
        backend = FakeDependencyBackend(...)
        resolver = DependencyResolver(backend)
    """

    def __init__(self, backend: DependencyBackend) -> None:
        self._backend = backend

    def resolve_closure(self, root_addon_ids: List[str]) -> DependencyClosure:
        """Compute the transitive required dependency closure. Pure: no mutation.

        Reads addon.xml for each installed root add-on and traverses required
        (non-optional) dependencies recursively. Missing deps are recorded with
        status=MISSING; their transitive deps cannot be known until installed.

        root_addon_ids are the starting points. They are not included in the
        returned nodes — only their dependencies are.

        Result is deterministic: roots are sorted lexically; sub-dependencies
        within each add-on are sorted lexically by addon_id.
        """
        sorted_roots = sorted(set(root_addon_ids))
        visited: Dict[str, DependencyNode] = {}
        results: List[DependencyNode] = []

        for root_id in sorted_roots:
            # Read root's dependencies from its installed addon.xml
            try:
                xml_bytes = self._backend.read_addon_xml(root_id)
            except Exception:
                xml_bytes = None

            if not xml_bytes:
                continue

            reqs = _parse_requirements(xml_bytes)
            reqs.sort(key=lambda r: r.addon_id)

            visiting: List[str] = [root_id]
            for req in reqs:
                if req.optional:
                    opt_already = any(
                        n.addon_id == req.addon_id and n.status == DependencyStatus.OPTIONAL
                        for n in results
                    )
                    if req.addon_id not in visited and not opt_already:
                        opt_node = DependencyNode(
                            addon_id=req.addon_id,
                            required_by=(root_id,),
                            status=DependencyStatus.OPTIONAL,
                            installed_version=None,
                            installed_enabled=None,
                            min_version_required=req.min_version,
                            optional=True,
                        )
                        results.append(opt_node)
                else:
                    _dfs(
                        req.addon_id,
                        req,
                        (root_id,),
                        self._backend,
                        visited,
                        visiting,
                        results,
                    )

        return DependencyClosure(
            root_addon_ids=tuple(sorted_roots),
            nodes=tuple(results),
        )

    def reconcile_dependencies(self, root_addon_ids: List[str]) -> DependencyResult:
        """Discover the required closure, install missing deps, enable disabled deps.

        Iterates resolve_closure + apply actions until stable (no new required
        actions) or _MAX_RECONCILE_ROUNDS is reached. Installation uses BM-011
        AddonManager via backend.install_addon(). Enabling uses backend.
        set_addon_enabled().

        Safety: never disables or removes any add-on.

        Returns DependencyResult with all actions taken and any unresolved deps.
        """
        all_actions: List[DependencyAction] = []
        acted_on: Set[str] = set()  # addon_ids acted on in any prior round
        final_closure: Optional[DependencyClosure] = None

        for _round in range(_MAX_RECONCILE_ROUNDS):
            closure = self.resolve_closure(root_addon_ids)
            final_closure = closure

            # Collect actionable nodes in this round (missing or needs_enable)
            # Skip add-ons already acted on (prevents loops on install failure)
            to_install = [
                n for n in closure.missing
                if n.addon_id not in acted_on
            ]
            to_enable = [
                n for n in closure.needs_enable
                if n.addon_id not in acted_on
            ]

            if not to_install and not to_enable:
                break  # stable

            # Apply installs first (may expose more deps after)
            for node in sorted(to_install, key=lambda n: n.addon_id):
                acted_on.add(node.addon_id)
                try:
                    result = self._backend.install_addon(
                        node.addon_id, desired_state="enabled"
                    )
                except Exception as exc:
                    all_actions.append(DependencyAction(
                        addon_id=node.addon_id,
                        kind=DependencyActionKind.FAILED_INSTALL,
                        reason=f"install_addon raised: {exc}",
                        required_by=node.required_by,
                    ))
                    continue

                # Check AddonStatus enum from addons module (string comparison)
                status_val = getattr(result.status, "value", str(result.status))
                if status_val in ("installed", "already_installed"):
                    all_actions.append(DependencyAction(
                        addon_id=node.addon_id,
                        kind=DependencyActionKind.INSTALLED,
                        reason=result.message,
                        required_by=node.required_by,
                    ))
                else:
                    all_actions.append(DependencyAction(
                        addon_id=node.addon_id,
                        kind=DependencyActionKind.FAILED_INSTALL,
                        reason=result.message,
                        required_by=node.required_by,
                    ))

            # Apply enables
            for node in sorted(to_enable, key=lambda n: n.addon_id):
                acted_on.add(node.addon_id)
                try:
                    self._backend.set_addon_enabled(node.addon_id, True)
                    all_actions.append(DependencyAction(
                        addon_id=node.addon_id,
                        kind=DependencyActionKind.ENABLED,
                        reason=f"{node.addon_id!r} was installed-disabled; enabled for required closure",
                        required_by=node.required_by,
                    ))
                except Exception as exc:
                    all_actions.append(DependencyAction(
                        addon_id=node.addon_id,
                        kind=DependencyActionKind.FAILED_ENABLE,
                        reason=f"set_addon_enabled raised: {exc}",
                        required_by=node.required_by,
                    ))

        # Final closure after all rounds
        assert final_closure is not None

        # Compute unresolved: missing + version_insufficient
        failed_install_ids = {
            a.addon_id for a in all_actions
            if a.kind == DependencyActionKind.FAILED_INSTALL
        }
        failed_enable_ids = {
            a.addon_id for a in all_actions
            if a.kind == DependencyActionKind.FAILED_ENABLE
        }

        unresolved = tuple(
            n for n in final_closure.nodes
            if n.status in (
                DependencyStatus.MISSING,
                DependencyStatus.VERSION_INSUFFICIENT,
            ) or n.addon_id in failed_install_ids or n.addon_id in failed_enable_ids
        )

        all_required_satisfied = (
            len(final_closure.missing) == 0
            and len(final_closure.insufficient_version) == 0
            and not failed_install_ids
            and not failed_enable_ids
        )

        return DependencyResult(
            closure=final_closure,
            actions=tuple(all_actions),
            all_required_satisfied=all_required_satisfied,
            unresolved=unresolved,
        )


# ---------------------------------------------------------------------------
# Production backend — Kodi runtime (xbmc / xbmcvfs)
# ---------------------------------------------------------------------------

class KodiRuntimeDependencyBackend(DependencyBackend):
    """Production backend. Reads addon.xml via xbmcvfs; state via JSON-RPC.

    Delegates installation to AddonManager(KodiRuntimeAddonBackend()).
    All Kodi modules imported lazily inside each method.
    """

    def _xbmc(self):
        try:
            import xbmc  # noqa: PLC0415
            return xbmc
        except ImportError as exc:
            raise DependencyError(f"Kodi runtime (xbmc) not available: {exc}") from exc

    def get_addon_details(self, addon_id: str):
        """Query Addons.GetAddonDetails. Returns None if not installed."""
        import json  # noqa: PLC0415
        xbmc = self._xbmc()
        req = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.GetAddonDetails",
            "params": {"addonid": addon_id, "properties": ["enabled", "version"]},
            "id": 1,
        })
        try:
            resp = json.loads(xbmc.executeJSONRPC(req))
        except Exception:
            return None
        if "error" in resp:
            return None
        result_val = resp.get("result", {})
        if not isinstance(result_val, dict):
            return None
        addon = result_val.get("addon", {})
        if not isinstance(addon, dict) or addon.get("addonid") != addon_id:
            return None
        from resources.lib.addons import InstalledAddonInfo  # noqa: PLC0415
        enabled = addon.get("enabled")
        version = addon.get("version", "")
        return InstalledAddonInfo(
            addon_id=addon_id,
            enabled=bool(enabled) if isinstance(enabled, bool) else False,
            version=str(version) if version else "",
        )

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        """Read addon.xml from special://home/addons/{addon_id}/ via xbmcvfs."""
        try:
            import xbmcaddon  # noqa: PLC0415
            import xbmcvfs    # noqa: PLC0415
        except ImportError:
            return None
        try:
            path = xbmcaddon.Addon(addon_id).getAddonInfo("path")
        except Exception:
            return None
        if not path:
            return None
        addon_xml_path = path.rstrip("/") + "/addon.xml"
        try:
            f = xbmcvfs.File(addon_xml_path)
            raw = f.read()
            f.close()
        except Exception:
            return None
        if isinstance(raw, str):
            return raw.encode("utf-8")
        return raw if raw else None

    def install_addon(self, addon_id: str, desired_state: str = "enabled"):
        """Install via BM-011 AddonManager(KodiRuntimeAddonBackend())."""
        from resources.lib.addons import AddonManager, KodiRuntimeAddonBackend  # noqa: PLC0415
        mgr = AddonManager(KodiRuntimeAddonBackend())
        return mgr.install(addon_id, desired_state=desired_state)

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        """Set enabled state via Addons.SetAddonEnabled JSON-RPC."""
        import json  # noqa: PLC0415
        xbmc = self._xbmc()
        req = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.SetAddonEnabled",
            "params": {"addonid": addon_id, "enabled": enabled},
            "id": 1,
        })
        try:
            resp = json.loads(xbmc.executeJSONRPC(req))
        except Exception as exc:
            raise DependencyError(
                f"Addons.SetAddonEnabled({addon_id!r}, {enabled}) failed: {exc}"
            ) from exc
        if "error" in resp:
            raise DependencyError(
                f"Addons.SetAddonEnabled({addon_id!r}, {enabled}) error: {resp['error']}"
            )
