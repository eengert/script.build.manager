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
    | MISSING | SYSTEM | CYCLE | OPTIONAL | METADATA_ERROR

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

Multi-path requirement consolidation
--------------------------------------
A dependency may be required from multiple paths (e.g. root A requires X>=1.0
and root B requires X>=2.0). The effective requirement is the STRICTEST
(highest minimum version) across all required paths. If the installed version
does not satisfy the effective requirement, the node is VERSION_INSUFFICIENT
regardless of which path is traversed first. Traversal order does not affect
classification.

Version semantics
-----------------
<import version="x.y.z"> specifies the MINIMUM required version. Installed
version >= required minimum (tuple int comparison) → satisfied. Unparseable
version strings are treated as satisfied (conservative). BM-012 never downgrades.
If installed version is below the minimum, the node is VERSION_INSUFFICIENT
and appears in unresolved; BM-012 does NOT upgrade (future work).

Note: unparseable version STRINGS (e.g. "1.0.beta") in <import version="...">
are treated conservatively (satisfied). This is distinct from METADATA_ERROR,
which applies to unreadable or malformed addon.xml files.

Malformed metadata handling
----------------------------
An installed dependency whose addon.xml cannot be read or parsed is classified
as METADATA_ERROR. This prevents all_required_satisfied=True when the
closure cannot be fully verified. Malformed metadata at the root level is also
recorded as METADATA_ERROR. Other independent dependencies are still evaluated.

Backend contract
-----------------
get_addon_details():
  - Returns None when the add-on is genuinely absent from Kodi's database.
  - Raises DependencyError on infrastructure failure (JSON-RPC error, malformed
    response, Kodi unreachable). Infrastructure failure must not be treated as
    "add-on not installed" — doing so would cause an unnecessary install attempt.

read_addon_xml():
  - Returns bytes when addon.xml is readable (may still be malformed XML).
  - Returns None when the file is absent or the add-on is not installed.
  - Should not raise; callers treat exceptions as metadata errors.

Circular dependency handling
-----------------------------
DFS uses visiting (current path) and visited (fully processed) sets. A node
encountered while in the current DFS path is recorded as CYCLE. The cycle
check precedes the visited check so that back-edges through previously
classified nodes are correctly detected. Cycle detection does not halt the
traversal; other branches are still processed. Deterministic (deps sorted
lexically).

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
from typing import Dict, List, Optional, Set, Tuple

# Type alias used in docstrings — imported lazily at runtime
# InstalledAddonInfo and AddonInstallResult come from resources.lib.addons


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class DependencyError(Exception):
    """Base class for all dependency operation errors."""


class _MetadataParseError(Exception):
    """Internal: raised when addon.xml bytes are non-empty but cannot be parsed."""


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
    METADATA_ERROR = "metadata_error"


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
    min_version_required: the effective (strictest across all paths) minimum
    required version for this dependency.
    cycle_path: only set for CYCLE nodes; the detected cycle as a tuple.
    """
    addon_id: str
    required_by: Tuple[str, ...]
    status: DependencyStatus
    installed_version: Optional[str]
    installed_enabled: Optional[bool]
    min_version_required: str     # effective minimum across all required paths
    optional: bool
    cycle_path: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class DependencyClosure:
    """Full transitive dependency closure for a set of root add-ons.

    The root add-ons themselves are not included in nodes unless they have
    a METADATA_ERROR (unreadable/malformed addon.xml at the root level).
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

    @property
    def metadata_errors(self) -> Tuple[DependencyNode, ...]:
        return tuple(n for n in self.nodes if n.status == DependencyStatus.METADATA_ERROR)


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
    unresolved: Tuple[DependencyNode, ...]  # MISSING, VERSION_INSUFFICIENT, METADATA_ERROR, failed


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


def _max_version_requirement(a: str, b: str) -> str:
    """Return the stricter (higher minimum required) of two version strings.

    Used to consolidate requirements from multiple required paths to the same
    dependency. 'Stricter' means the installed version must be at least that
    high — a higher minimum is harder to satisfy.

    If either is empty (no minimum), returns the other.
    If either is unparseable, returns the parseable one (conservative: prefer
    the structured requirement so it can be enforced).
    If both are unparseable, returns 'a' arbitrarily.
    If both are parseable, returns the lexically-larger minimum requirement.
    """
    if not a:
        return b
    if not b:
        return a
    pa = _parse_version(a)
    pb = _parse_version(b)
    if pa is None and pb is None:
        return a  # both unparseable — arbitrary, return first
    if pa is None:
        return b  # a unparseable, b has structure → use b
    if pb is None:
        return a  # b unparseable, a has structure → use a
    # Both parseable — return the larger (stricter minimum)
    max_len = max(len(pa), len(pb))
    pa_padded = pa + (0,) * (max_len - len(pa))
    pb_padded = pb + (0,) * (max_len - len(pb))
    return b if pb_padded >= pa_padded else a


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

    Deduplicates import entries by addon_id: strongest min_version wins;
    required beats optional. See _extract_requirements for full rules.

    Does not raise on malformed input — returns what can be parsed.
    For a strict variant that raises on malformed XML, use _parse_requirements_strict.
    """
    if not xml_bytes:
        return []
    try:
        root_el = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    return _extract_requirements(root_el)


def _parse_requirements_strict(xml_bytes: bytes) -> List[DependencyRequirement]:
    """Parse <requires><import .../> elements from addon.xml bytes.

    Unlike _parse_requirements, raises _MetadataParseError if xml_bytes is
    non-empty but contains malformed XML. This distinguishes:
      - Empty bytes / no <requires> element  → [] (valid: no deps declared)
      - Non-empty but unparseable XML        → _MetadataParseError (metadata broken)

    Deduplicates by addon_id: strongest min_version wins; required beats optional.
    """
    if not xml_bytes:
        return []
    try:
        root_el = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise _MetadataParseError(f"addon.xml parse error: {exc}") from exc
    return _extract_requirements(root_el)


def _extract_requirements(root_el: ET.Element) -> List[DependencyRequirement]:
    """Extract DependencyRequirement list from a parsed addon.xml Element.

    Deduplication rules when the same addon_id appears more than once:
    - Required beats optional: if any occurrence is required, the result is required.
    - Strongest min_version wins: effective min = max across all occurrences,
      using _max_version_requirement() (order-independent).
    - Order of entries in the output matches first-seen addon_id order.
    """
    requires_el = root_el.find("requires")
    if requires_el is None:
        return []

    entries: Dict[str, DependencyRequirement] = {}

    for import_el in requires_el.findall("import"):
        dep_id = (import_el.get("addon") or "").strip()
        if not dep_id:
            continue

        min_version = (import_el.get("version") or "").strip()
        optional_str = (import_el.get("optional") or "false").lower().strip()
        optional = optional_str == "true"

        if dep_id not in entries:
            entries[dep_id] = DependencyRequirement(
                addon_id=dep_id,
                min_version=min_version,
                optional=optional,
            )
        else:
            existing = entries[dep_id]
            # Required beats optional: only optional if every occurrence is optional
            new_optional = existing.optional and optional
            # Strongest minimum version wins (order-independent)
            new_min = _max_version_requirement(existing.min_version, min_version)
            entries[dep_id] = DependencyRequirement(
                addon_id=dep_id,
                min_version=new_min,
                optional=new_optional,
            )

    return list(entries.values())


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

        MUST return None only when the add-on is genuinely absent from Kodi's
        database ("not installed"). MUST raise DependencyError on infrastructure
        failure (JSON-RPC error, malformed response, Kodi unreachable). This
        distinction prevents infrastructure failure from being misclassified as
        MISSING and triggering an unnecessary installation attempt.
        """
        raise NotImplementedError

    def read_addon_xml(self, addon_id: str) -> Optional[bytes]:
        """Read addon.xml bytes for an installed add-on.

        Returns bytes (possibly malformed) when the file is accessible.
        Returns None if the add-on is not installed or addon.xml is absent.
        Should not raise; callers treat unhandled exceptions as metadata errors.
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
    result_map: Dict[str, DependencyNode],
    effective_min: Dict[str, str],
    cycle_nodes: List[DependencyNode],
    visited: Set[str],
    visiting: List[str],
) -> None:
    """Depth-first traversal to collect all required transitive dependencies.

    dep_id: the dependency to process now
    req: the DependencyRequirement edge that caused this traversal
    requirer_path: tuple of addon_ids that led here (immediate requirer first)
    backend: read-only backend calls only
    result_map: addon_id → primary DependencyNode; updated in place; allows
        re-classification when a stronger requirement is discovered later
    effective_min: addon_id → strictest min_version required across all paths
    cycle_nodes: back-edge CYCLE records (separate from result_map)
    visited: addon_ids that have been fully processed (prevents re-traversal)
    visiting: addon_ids in the current DFS path (cycle detection)
    """
    # System dependency: always satisfied, never installed, short-circuit
    if _is_system_dependency(dep_id):
        if dep_id not in result_map:
            result_map[dep_id] = DependencyNode(
                addon_id=dep_id,
                required_by=requirer_path,
                status=DependencyStatus.SYSTEM,
                installed_version=None,
                installed_enabled=None,
                min_version_required=req.min_version,
                optional=False,
            )
        return

    # Cycle detection must precede the visited check: a node can be in both
    # visited (processed on an earlier branch) and visiting (in the current
    # DFS path) when the graph has a cycle that loops through a shared node.
    if dep_id in visiting:
        cycle_path = tuple(visiting[visiting.index(dep_id):]) + (dep_id,)
        cycle_nodes.append(DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.CYCLE,
            installed_version=None,
            installed_enabled=None,
            min_version_required=req.min_version,
            optional=False,
            cycle_path=cycle_path,
        ))
        return

    # Update effective minimum version for this dependency across all paths
    prev_effective = effective_min.get(dep_id, "")
    new_effective = _max_version_requirement(prev_effective, req.min_version)
    effective_min[dep_id] = new_effective

    # Already fully processed: re-classify if a stronger requirement was discovered
    if dep_id in visited:
        if new_effective != prev_effective and dep_id in result_map:
            existing = result_map[dep_id]
            if existing.status in (
                DependencyStatus.SATISFIED,
                DependencyStatus.INSTALLED_DISABLED,
            ):
                inst_version = existing.installed_version or ""
                if new_effective and not _version_satisfies(inst_version, new_effective):
                    result_map[dep_id] = DependencyNode(
                        addon_id=existing.addon_id,
                        required_by=existing.required_by,
                        status=DependencyStatus.VERSION_INSUFFICIENT,
                        installed_version=existing.installed_version,
                        installed_enabled=existing.installed_enabled,
                        min_version_required=new_effective,
                        optional=False,
                    )
        return

    # Mark as visited (prevents infinite recursion and double-traversal)
    visited.add(dep_id)

    # Query installed state; distinguish infrastructure failure from "not installed"
    try:
        details = backend.get_addon_details(dep_id)
    except DependencyError:
        result_map[dep_id] = DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.METADATA_ERROR,
            installed_version=None,
            installed_enabled=None,
            min_version_required=new_effective,
            optional=False,
        )
        return
    except Exception:
        result_map[dep_id] = DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.METADATA_ERROR,
            installed_version=None,
            installed_enabled=None,
            min_version_required=new_effective,
            optional=False,
        )
        return

    # Genuinely not installed
    if details is None:
        result_map[dep_id] = DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.MISSING,
            installed_version=None,
            installed_enabled=None,
            min_version_required=new_effective,
            optional=False,
        )
        return

    # Installed — classify based on effective minimum version across all paths
    inst_version = details.version or ""
    if new_effective and not _version_satisfies(inst_version, new_effective):
        status = DependencyStatus.VERSION_INSUFFICIENT
    elif not details.enabled:
        status = DependencyStatus.INSTALLED_DISABLED
    else:
        status = DependencyStatus.SATISFIED

    result_map[dep_id] = DependencyNode(
        addon_id=dep_id,
        required_by=requirer_path,
        status=status,
        installed_version=inst_version,
        installed_enabled=details.enabled,
        min_version_required=new_effective,
        optional=False,
    )

    if status == DependencyStatus.VERSION_INSUFFICIENT:
        return

    # Read addon.xml to discover sub-dependencies
    try:
        xml_bytes = backend.read_addon_xml(dep_id)
    except Exception:
        result_map[dep_id] = DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.METADATA_ERROR,
            installed_version=inst_version,
            installed_enabled=details.enabled,
            min_version_required=new_effective,
            optional=False,
        )
        return

    if xml_bytes is None:
        # Installed but addon.xml is absent or unreadable: metadata error —
        # cannot determine sub-dependencies, so closure is incomplete.
        result_map[dep_id] = DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.METADATA_ERROR,
            installed_version=inst_version,
            installed_enabled=details.enabled,
            min_version_required=new_effective,
            optional=False,
        )
        return

    # Parse sub-dependencies; malformed XML is a metadata error
    try:
        sub_reqs = _parse_requirements_strict(xml_bytes)
    except _MetadataParseError:
        result_map[dep_id] = DependencyNode(
            addon_id=dep_id,
            required_by=requirer_path,
            status=DependencyStatus.METADATA_ERROR,
            installed_version=inst_version,
            installed_enabled=details.enabled,
            min_version_required=new_effective,
            optional=False,
        )
        return

    # Sort lexically by addon_id for deterministic traversal
    sub_reqs.sort(key=lambda r: r.addon_id)

    visiting.append(dep_id)
    for sub_req in sub_reqs:
        if sub_req.optional:
            # Record optional deps but do not traverse or require
            if sub_req.addon_id not in visited and sub_req.addon_id not in result_map:
                result_map[sub_req.addon_id] = DependencyNode(
                    addon_id=sub_req.addon_id,
                    required_by=(dep_id,) + requirer_path,
                    status=DependencyStatus.OPTIONAL,
                    installed_version=None,
                    installed_enabled=None,
                    min_version_required=sub_req.min_version,
                    optional=True,
                )
        else:
            _dfs(
                sub_req.addon_id,
                sub_req,
                (dep_id,) + requirer_path,
                backend,
                result_map,
                effective_min,
                cycle_nodes,
                visited,
                visiting,
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

        Multi-path consolidation: when the same dependency is required from
        multiple paths with different minimum versions, the effective requirement
        is the strictest (highest minimum) across all paths. Classification is
        independent of traversal order.

        Malformed metadata: if a root or installed dependency's addon.xml is
        unreadable or unparseable, a METADATA_ERROR node is recorded. This
        prevents all_required_satisfied=True when the closure cannot be fully
        verified. Root add-ons with METADATA_ERROR appear in nodes even though
        roots are normally excluded.

        Result is deterministic: roots are sorted lexically; sub-dependencies
        within each add-on are sorted lexically by addon_id; the final nodes
        tuple is sorted by addon_id (cycle back-edge nodes appended after).
        """
        sorted_roots = sorted(set(root_addon_ids))
        result_map: Dict[str, DependencyNode] = {}
        effective_min: Dict[str, str] = {}
        cycle_nodes: List[DependencyNode] = []
        visited: Set[str] = set()

        for root_id in sorted_roots:
            try:
                xml_bytes = self._backend.read_addon_xml(root_id)
            except Exception:
                xml_bytes = None

            if xml_bytes is None:
                # Cannot read addon.xml. Determine why before deciding what to do:
                # - root genuinely not installed → skip (no METADATA_ERROR)
                # - root IS installed but xml unreadable → METADATA_ERROR
                # - infrastructure failure querying root state → METADATA_ERROR
                try:
                    root_details = self._backend.get_addon_details(root_id)
                except Exception:
                    result_map[root_id] = DependencyNode(
                        addon_id=root_id,
                        required_by=(),
                        status=DependencyStatus.METADATA_ERROR,
                        installed_version=None,
                        installed_enabled=None,
                        min_version_required="",
                        optional=False,
                    )
                    continue
                if root_details is not None:
                    # Root is installed but its addon.xml is absent or unreadable
                    result_map[root_id] = DependencyNode(
                        addon_id=root_id,
                        required_by=(),
                        status=DependencyStatus.METADATA_ERROR,
                        installed_version=root_details.version or "",
                        installed_enabled=root_details.enabled,
                        min_version_required="",
                        optional=False,
                    )
                # else: root is genuinely not installed → skip
                continue

            try:
                reqs = _parse_requirements_strict(xml_bytes)
            except _MetadataParseError:
                # Root's addon.xml is malformed — record as METADATA_ERROR
                result_map[root_id] = DependencyNode(
                    addon_id=root_id,
                    required_by=(),
                    status=DependencyStatus.METADATA_ERROR,
                    installed_version=None,
                    installed_enabled=None,
                    min_version_required="",
                    optional=False,
                )
                continue

            reqs.sort(key=lambda r: r.addon_id)
            visiting: List[str] = [root_id]

            for req in reqs:
                if req.optional:
                    # Record optional direct deps; don't overwrite a required classification
                    if req.addon_id not in visited and req.addon_id not in result_map:
                        result_map[req.addon_id] = DependencyNode(
                            addon_id=req.addon_id,
                            required_by=(root_id,),
                            status=DependencyStatus.OPTIONAL,
                            installed_version=None,
                            installed_enabled=None,
                            min_version_required=req.min_version,
                            optional=True,
                        )
                else:
                    _dfs(
                        req.addon_id,
                        req,
                        (root_id,),
                        self._backend,
                        result_map,
                        effective_min,
                        cycle_nodes,
                        visited,
                        visiting,
                    )

        # Build final nodes: primary nodes sorted by addon_id, then cycle back-edges
        primary_nodes = sorted(result_map.values(), key=lambda n: n.addon_id)
        return DependencyClosure(
            root_addon_ids=tuple(sorted_roots),
            nodes=tuple(primary_nodes) + tuple(cycle_nodes),
        )

    def reconcile_dependencies(self, root_addon_ids: List[str]) -> DependencyResult:
        """Discover the required closure, install missing deps, enable disabled deps.

        Iterates resolve_closure + apply actions until stable (no new required
        actions) or _MAX_RECONCILE_ROUNDS is reached. Installation uses BM-011
        AddonManager via backend.install_addon(). Enabling uses backend.
        set_addon_enabled().

        Safety: never disables or removes any add-on.

        all_required_satisfied is False when any of the following are present
        after the final round: MISSING nodes, VERSION_INSUFFICIENT nodes,
        METADATA_ERROR nodes, failed install or enable actions.

        Returns DependencyResult with all actions taken and any unresolved deps.
        """
        all_actions: List[DependencyAction] = []
        acted_on: Set[str] = set()  # addon_ids acted on in any prior round
        final_closure: Optional[DependencyClosure] = None

        for _round in range(_MAX_RECONCILE_ROUNDS):
            closure = self.resolve_closure(root_addon_ids)
            final_closure = closure

            # Collect actionable nodes (missing or needs_enable) not yet acted on
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

            # Apply installs first (may expose more deps after install + restart)
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
                DependencyStatus.METADATA_ERROR,
            ) or n.addon_id in failed_install_ids or n.addon_id in failed_enable_ids
        )

        all_required_satisfied = (
            len(final_closure.missing) == 0
            and len(final_closure.insufficient_version) == 0
            and len(final_closure.metadata_errors) == 0
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
        """Query Addons.GetAddonDetails.

        Returns None ONLY when Kodi responds with JSON-RPC error code -32602
        (Invalid params), which is the exact response Kodi 21 generates for an
        add-on that is not installed. All other error responses raise
        DependencyError so infrastructure failures are not misclassified as
        "addon not installed".

        Raises DependencyError on JSON decode failure, Kodi unreachable,
        malformed response, or any JSON-RPC error other than -32602.
        """
        import json  # noqa: PLC0415
        xbmc = self._xbmc()
        req = json.dumps({
            "jsonrpc": "2.0",
            "method": "Addons.GetAddonDetails",
            "params": {"addonid": addon_id, "properties": ["enabled", "version"]},
            "id": 1,
        })
        try:
            raw = xbmc.executeJSONRPC(req)
            resp = json.loads(raw)
        except Exception as exc:
            raise DependencyError(
                f"Addons.GetAddonDetails({addon_id!r}) infrastructure failure: {exc}"
            ) from exc

        if "error" in resp:
            error_obj = resp["error"]
            if not isinstance(error_obj, dict):
                raise DependencyError(
                    f"Addons.GetAddonDetails({addon_id!r}) malformed error in response: {resp!r}"
                )
            error_code = error_obj.get("code")
            if error_code == -32602:
                # Kodi 21: Invalid params (-32602) is the exact response when the
                # add-on is not installed. Return None to signal "genuinely absent".
                return None
            raise DependencyError(
                f"Addons.GetAddonDetails({addon_id!r}) JSON-RPC error {error_code}: "
                f"{error_obj.get('message', '(no message)')}"
            )

        result_val = resp.get("result")
        if not isinstance(result_val, dict):
            raise DependencyError(
                f"Addons.GetAddonDetails({addon_id!r}) malformed response: {resp!r}"
            )

        addon = result_val.get("addon")
        if addon is None:
            # Kodi returned a result but no addon field — absent
            return None
        if not isinstance(addon, dict):
            raise DependencyError(
                f"Addons.GetAddonDetails({addon_id!r}) addon field not a dict: {addon!r}"
            )
        if addon.get("addonid") != addon_id:
            raise DependencyError(
                f"Addons.GetAddonDetails({addon_id!r}) returned wrong addon id: "
                f"{addon.get('addonid')!r}"
            )

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
