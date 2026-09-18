"""
Build Manager post-operation state validator (BM-014).

Public API
----------
validate_build_state(
    desired: ResolvedBuild,
    actual: KodiState,
    dependency_closure: Optional[DependencyClosure] = None,
    configuration_state: Optional[ConfigurationValidationState] = None,
) -> ValidationReport

    Read-only validator. Evaluates whether the observable Kodi state matches
    the resolved desired Build Manager state after provisioning/reconciliation
    operations. Reports discrepancies. Never mutates Kodi state.

    desired:              Fully resolved desired configuration (BM-004 output).
    actual:               Immutable snapshot of current Kodi state (BM-005 output).
    dependency_closure:   Optional BM-012 DependencyClosure for the managed
                          root add-ons. If None and dependency validation is
                          applicable, a NOT_CHECKED result is emitted.
    configuration_state:  Optional BM-015 ConfigurationValidationState snapshot.
                          If None and desired.config is present, a NOT_CHECKED
                          result is emitted.

ValidationReport
    report.checks         — all ValidationCheck results, deterministic order
    report.failures       — FAIL checks
    report.warnings       — WARNING checks
    report.not_checked    — NOT_CHECKED checks
    report.passes         — PASS checks
    report.is_valid       — True when no FAIL checks
    report.is_complete    — True when no NOT_CHECKED checks
    report.passed         — True when is_valid AND is_complete

ValidationCheck(domain, subject, status, expected, actual_state, reason)
    Per-check result. All fields are strings or enums; callers must not scrape
    the formatted reason string to determine status — use the status field.

ValidationStatus
    PASS | FAIL | WARNING | NOT_CHECKED

ValidationDomain
    REPOSITORY | ADDON | DEPENDENCY | SKIN | CONFIGURATION

Errors
------
ValidationError
    Raised for malformed or internally inconsistent validator inputs, such as
    duplicate addon_ids in KodiState, which make deterministic validation
    impossible. This is not a validation FAIL — it is a precondition violation
    by the caller. Fix the input, then retry.

Validation domains
------------------
1. REPOSITORY   — every required repository is installed+enabled
2. ADDON        — every explicitly managed add-on is in its desired state
3. DEPENDENCY   — every required dependency node has a satisfying status
4. SKIN         — desired skin (if any) is installed and active
5. CONFIGURATION — managed setting/file targets, against a BM-015 snapshot

Read-only guarantee
-------------------
This module contains:
  - no xbmc imports
  - no xbmcvfs imports
  - no filesystem writes
  - no network calls
  - no shell execution
  - no mutation backend

The validator is pure Python operating on immutable snapshots supplied by the
caller. Kodi state mutation is never performed here.

Domain ordering
---------------
All checks are returned in deterministic domain + lexical subject order:
  REPOSITORY → ADDON → DEPENDENCY → SKIN → CONFIGURATION
  Within each domain, subjects are sorted lexically by addon_id / subject key.
  The CONFIGURATION domain emits its managed-setting checks (sorted by
  addon_id then key) before its managed-file checks (sorted by destination).

Aggregate semantics
-------------------
is_valid:    no FAIL checks are present
is_complete: no NOT_CHECKED checks are present
passed:      is_valid AND is_complete

A build with zero detected failures but an unvalidated configuration domain
is NOT represented as fully validated (is_complete=False → passed=False).
WARNING checks alone do not prevent is_valid or passed from being True.

Dependency cycle treatment
--------------------------
BM-012 records detected dependency cycles with status=CYCLE without automatically
failing the closure (a cycle may be benign if all cycle members are SATISFIED via
other paths). BM-014 maps CYCLE to WARNING unless the same node is also MISSING
or VERSION_INSUFFICIENT. One failure does not suppress the other.

Repository validation scope
---------------------------
Only repositories with required=True are validated. Missing optional repositories
(required=False) do not generate checks. Do not attempt to identify repository type
from KodiState — validate observable state: ID + installed/enabled.

Addon validation scope
----------------------
Only add-ons explicitly listed in desired.addons are validated. Unmanaged
installed add-ons (present in KodiState but absent from desired.addons) are
silently ignored; they never produce FAIL results.

BM-015 integration (Option A)
-----------------------------
BM-014 remains read-only and never inspects live configuration itself. BM-015
produces an immutable ConfigurationValidationState snapshot describing exactly
which managed targets it resolved and which of them it verified after applying
them. Passing that snapshot lets BM-014 report the CONFIGURATION domain:

  desired.config is None                      → no CONFIGURATION checks
  desired.config present, snapshot None       → NOT_CHECKED (unchanged)
  snapshot scope == declared managed scope    → PASS/FAIL per declared target
  snapshot empty / partial / unrelated        → NOT_CHECKED (scope mismatch)

Scope comparison is by set equality over declared (addon_id, key) setting
targets and declared managed file destinations, mirroring the dependency-root
scope discipline above. A successful BM-015 apply() never by itself makes
BM-014 claim configuration is validated: the snapshot must cover exactly the
resolved managed scope, and every target in it must have been verified.

Stdlib only — no new runtime dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from resources.lib.config import ConfigurationValidationState
from resources.lib.dependencies import DependencyClosure, DependencyStatus
from resources.lib.inspector import InstalledAddon, KodiState
from resources.lib.resolver import ResolvedBuild


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Invalid validator input that makes deterministic validation impossible.

    Example: duplicate addon_ids in KodiState.addons.
    Fix the input before retrying.
    """


# ---------------------------------------------------------------------------
# Status and domain enums
# ---------------------------------------------------------------------------

class ValidationStatus(str, Enum):
    """Per-check outcome from validate_build_state()."""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    NOT_CHECKED = "not_checked"


class ValidationDomain(str, Enum):
    """Validation category a check belongs to."""
    REPOSITORY = "repository"
    ADDON = "addon"
    DEPENDENCY = "dependency"
    SKIN = "skin"
    CONFIGURATION = "configuration"


# ---------------------------------------------------------------------------
# Per-check result (frozen)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationCheck:
    """Result of one validation point.

    Callers must use the `status` field to determine outcome — never scrape
    the `reason` string. All string fields are human-readable diagnostic text.

    subject:      addon_id or a domain-level descriptor (e.g. "dependency_domain")
    expected:     human-readable description of the expected state
    actual_state: human-readable description of the observed state
    reason:       one-sentence diagnosis suitable for a log or report
    """
    domain: ValidationDomain
    subject: str
    status: ValidationStatus
    expected: str
    actual_state: str
    reason: str


# ---------------------------------------------------------------------------
# Aggregate report (frozen)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationReport:
    """Aggregate result from validate_build_state().

    checks: all ValidationCheck results in deterministic domain+lexical order.

    Convenience properties filter by status:
      passes, failures, warnings, not_checked

    Aggregate boolean properties:
      is_valid     — no FAIL checks
      is_complete  — no NOT_CHECKED checks
      passed       — is_valid AND is_complete

    WARNING checks alone do not prevent is_valid or passed from being True.
    """
    checks: Tuple[ValidationCheck, ...]

    @property
    def passes(self) -> Tuple[ValidationCheck, ...]:
        return tuple(c for c in self.checks if c.status == ValidationStatus.PASS)

    @property
    def failures(self) -> Tuple[ValidationCheck, ...]:
        return tuple(c for c in self.checks if c.status == ValidationStatus.FAIL)

    @property
    def warnings(self) -> Tuple[ValidationCheck, ...]:
        return tuple(c for c in self.checks if c.status == ValidationStatus.WARNING)

    @property
    def not_checked(self) -> Tuple[ValidationCheck, ...]:
        return tuple(c for c in self.checks if c.status == ValidationStatus.NOT_CHECKED)

    @property
    def is_valid(self) -> bool:
        """True when no FAIL checks are present."""
        return not any(c.status == ValidationStatus.FAIL for c in self.checks)

    @property
    def is_complete(self) -> bool:
        """True when no NOT_CHECKED checks are present."""
        return not any(c.status == ValidationStatus.NOT_CHECKED for c in self.checks)

    @property
    def passed(self) -> bool:
        """True when is_valid AND is_complete (no failures, no unvalidated domains)."""
        return self.is_valid and self.is_complete


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_build_state(
    desired: ResolvedBuild,
    actual: KodiState,
    dependency_closure: Optional[DependencyClosure] = None,
    configuration_state: Optional[ConfigurationValidationState] = None,
) -> ValidationReport:
    """Validate observable Kodi state against a resolved desired Build Manager state.

    Read-only. Never mutates Kodi state or touches any backend.

    Args:
        desired:            Fully resolved desired configuration (BM-004 output).
        actual:             Immutable Kodi state snapshot (BM-005 output).
        dependency_closure: Optional BM-012 DependencyClosure. If None and
                            dependency validation is applicable, a NOT_CHECKED
                            result is emitted.

    Returns:
        ValidationReport in deterministic domain+lexical order.

    Raises:
        ValidationError: if actual.addons contains duplicate addon_ids, or
                         any other input makes deterministic validation impossible.
    """
    actual_map = _build_actual_map(actual)

    checks: list = []
    checks.extend(_validate_repositories(desired, actual_map))
    checks.extend(_validate_addons(desired, actual_map))
    checks.extend(_validate_dependencies(desired, dependency_closure))
    checks.extend(_validate_skin(desired, actual, actual_map))
    checks.extend(_validate_configuration(desired, configuration_state))

    return ValidationReport(checks=tuple(checks))


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _build_actual_map(actual: KodiState) -> Dict[str, InstalledAddon]:
    """Build and return {addon_id → InstalledAddon} from actual.addons.

    Raises ValidationError if any addon_id appears more than once.
    """
    seen: Dict[str, InstalledAddon] = {}
    for addon in actual.addons:
        if addon.addon_id in seen:
            raise ValidationError(
                f"KodiState contains duplicate addon_id: {addon.addon_id!r}. "
                f"Cannot validate deterministically. Fix the KodiState input."
            )
        seen[addon.addon_id] = addon
    return seen


# ---------------------------------------------------------------------------
# Domain validators
# ---------------------------------------------------------------------------

def _validate_repositories(
    desired: ResolvedBuild,
    actual_map: Dict[str, InstalledAddon],
) -> list:
    """Validate required repositories (required=True only)."""
    checks = []
    required_repos = sorted(
        (r for r in desired.repositories if r.required),
        key=lambda r: r.addon_id,
    )
    for repo in required_repos:
        addon = actual_map.get(repo.addon_id)
        if addon is None:
            checks.append(ValidationCheck(
                domain=ValidationDomain.REPOSITORY,
                subject=repo.addon_id,
                status=ValidationStatus.FAIL,
                expected="installed and enabled",
                actual_state="not installed",
                reason=f"Required repository {repo.addon_id!r} is not installed",
            ))
        elif not addon.enabled:
            checks.append(ValidationCheck(
                domain=ValidationDomain.REPOSITORY,
                subject=repo.addon_id,
                status=ValidationStatus.FAIL,
                expected="installed and enabled",
                actual_state="installed but disabled",
                reason=(
                    f"Required repository {repo.addon_id!r} is installed "
                    f"but disabled"
                ),
            ))
        else:
            checks.append(ValidationCheck(
                domain=ValidationDomain.REPOSITORY,
                subject=repo.addon_id,
                status=ValidationStatus.PASS,
                expected="installed and enabled",
                actual_state="installed and enabled",
                reason=f"Required repository {repo.addon_id!r} is installed and enabled",
            ))
    return checks


def _validate_addons(
    desired: ResolvedBuild,
    actual_map: Dict[str, InstalledAddon],
) -> list:
    """Validate each explicitly managed add-on entry."""
    checks = []
    managed = sorted(desired.addons, key=lambda a: a.addon_id)
    for entry in managed:
        addon_id = entry.addon_id
        desired_state = entry.state
        actual_addon = actual_map.get(addon_id)

        if desired_state == "enabled":
            if actual_addon is None:
                checks.append(ValidationCheck(
                    domain=ValidationDomain.ADDON,
                    subject=addon_id,
                    status=ValidationStatus.FAIL,
                    expected="installed and enabled",
                    actual_state="not installed",
                    reason=f"{addon_id!r} desired enabled but is not installed",
                ))
            elif not actual_addon.enabled:
                checks.append(ValidationCheck(
                    domain=ValidationDomain.ADDON,
                    subject=addon_id,
                    status=ValidationStatus.FAIL,
                    expected="enabled",
                    actual_state="installed but disabled",
                    reason=f"{addon_id!r} desired enabled but is installed disabled",
                ))
            else:
                checks.append(ValidationCheck(
                    domain=ValidationDomain.ADDON,
                    subject=addon_id,
                    status=ValidationStatus.PASS,
                    expected="enabled",
                    actual_state="enabled",
                    reason=f"{addon_id!r} is enabled as desired",
                ))

        elif desired_state == "disabled":
            if actual_addon is None:
                checks.append(ValidationCheck(
                    domain=ValidationDomain.ADDON,
                    subject=addon_id,
                    status=ValidationStatus.FAIL,
                    expected="installed and disabled",
                    actual_state="not installed",
                    reason=f"{addon_id!r} desired disabled but is not installed",
                ))
            elif actual_addon.enabled:
                checks.append(ValidationCheck(
                    domain=ValidationDomain.ADDON,
                    subject=addon_id,
                    status=ValidationStatus.FAIL,
                    expected="disabled",
                    actual_state="installed and enabled",
                    reason=f"{addon_id!r} desired disabled but is installed enabled",
                ))
            else:
                checks.append(ValidationCheck(
                    domain=ValidationDomain.ADDON,
                    subject=addon_id,
                    status=ValidationStatus.PASS,
                    expected="disabled",
                    actual_state="disabled",
                    reason=f"{addon_id!r} is disabled as desired",
                ))

        elif desired_state == "absent":
            if actual_addon is None:
                checks.append(ValidationCheck(
                    domain=ValidationDomain.ADDON,
                    subject=addon_id,
                    status=ValidationStatus.PASS,
                    expected="absent",
                    actual_state="not installed",
                    reason=f"{addon_id!r} is absent as desired",
                ))
            else:
                state_desc = "installed and enabled" if actual_addon.enabled else "installed but disabled"
                checks.append(ValidationCheck(
                    domain=ValidationDomain.ADDON,
                    subject=addon_id,
                    status=ValidationStatus.FAIL,
                    expected="absent",
                    actual_state=state_desc,
                    reason=f"{addon_id!r} desired absent but is {state_desc}",
                ))

        else:
            checks.append(ValidationCheck(
                domain=ValidationDomain.ADDON,
                subject=addon_id,
                status=ValidationStatus.FAIL,
                expected="enabled | disabled | absent",
                actual_state="unknown",
                reason=(
                    f"{addon_id!r} has unrecognised desired state "
                    f"{desired_state!r}"
                ),
            ))
    return checks


def _validate_dependencies(
    desired: ResolvedBuild,
    closure: Optional[DependencyClosure],
) -> list:
    """Validate the dependency closure if provided; emit NOT_CHECKED if not."""
    # Expected roots: only desired managed add-ons with state "enabled".
    # Disabled, absent, and unmanaged add-ons are excluded.
    expected_roots = frozenset(
        entry.addon_id for entry in desired.addons if entry.state == "enabled"
    )

    if not expected_roots:
        # No enabled managed add-ons → dependency validation is not applicable.
        return []

    if closure is None:
        return [ValidationCheck(
            domain=ValidationDomain.DEPENDENCY,
            subject="dependency_domain",
            status=ValidationStatus.NOT_CHECKED,
            expected=f"closure roots: {sorted(expected_roots)}",
            actual_state="no closure supplied",
            reason=(
                "Dependency closure was not supplied; dependency validation "
                "requires a BM-012 DependencyClosure rooted at: "
                f"{sorted(expected_roots)}"
            ),
        )]

    # Closure supplied: verify root scope matches exactly.
    supplied_roots = frozenset(closure.root_addon_ids)
    if supplied_roots != expected_roots:
        return [ValidationCheck(
            domain=ValidationDomain.DEPENDENCY,
            subject="dependency_domain",
            status=ValidationStatus.NOT_CHECKED,
            expected=f"closure roots: {sorted(expected_roots)}",
            actual_state=f"closure roots: {sorted(supplied_roots)}",
            reason=(
                "Dependency closure root_addon_ids do not match expected enabled "
                f"managed add-ons; expected: {sorted(expected_roots)}, "
                f"supplied: {sorted(supplied_roots)}"
            ),
        )]

    checks = []
    # Process nodes in lexical addon_id order.
    _failing = (
        DependencyStatus.MISSING,
        DependencyStatus.VERSION_INSUFFICIENT,
        DependencyStatus.METADATA_ERROR,
    )
    nodes = sorted(closure.nodes, key=lambda n: n.addon_id)
    for node in nodes:
        status = node.status

        if status == DependencyStatus.OPTIONAL:
            # Optional-only dependencies are not required; skip without a check.
            continue

        if status in (DependencyStatus.SATISFIED, DependencyStatus.SYSTEM):
            checks.append(ValidationCheck(
                domain=ValidationDomain.DEPENDENCY,
                subject=node.addon_id,
                status=ValidationStatus.PASS,
                expected="satisfied",
                actual_state=status.value,
                reason=f"Dependency {node.addon_id!r} is {status.value}",
            ))

        elif status == DependencyStatus.CYCLE:
            # BM-012 allows benign cycles. Report as WARNING; the caller can
            # treat it as a failure if the surrounding closure also has concrete
            # unresolved deps (reported separately as FAIL via those nodes).
            checks.append(ValidationCheck(
                domain=ValidationDomain.DEPENDENCY,
                subject=node.addon_id,
                status=ValidationStatus.WARNING,
                expected="acyclic dependency graph",
                actual_state="cycle detected",
                reason=(
                    f"Dependency cycle detected involving {node.addon_id!r}; "
                    f"cycle path: {' → '.join(node.cycle_path) if node.cycle_path else 'unknown'}"
                ),
            ))

        elif status == DependencyStatus.INSTALLED_DISABLED:
            # Required dep is installed but disabled — treat as a failure.
            checks.append(ValidationCheck(
                domain=ValidationDomain.DEPENDENCY,
                subject=node.addon_id,
                status=ValidationStatus.FAIL,
                expected="installed and enabled",
                actual_state="installed but disabled",
                reason=(
                    f"Required dependency {node.addon_id!r} is installed but disabled; "
                    f"required by: {', '.join(sorted(node.required_by))}"
                ),
            ))

        elif status in _failing:
            reason_parts = [f"Required dependency {node.addon_id!r} status={status.value}"]
            if node.required_by:
                reason_parts.append(f"required by: {', '.join(sorted(node.required_by))}")
            if (
                status == DependencyStatus.VERSION_INSUFFICIENT
                and node.min_version_required
                and node.installed_version is not None
            ):
                reason_parts.append(
                    f"installed={node.installed_version!r} "
                    f"required>={node.min_version_required!r}"
                )
            checks.append(ValidationCheck(
                domain=ValidationDomain.DEPENDENCY,
                subject=node.addon_id,
                status=ValidationStatus.FAIL,
                expected=(
                    f"installed and enabled"
                    + (
                        f" (>={node.min_version_required})"
                        if node.min_version_required
                        else ""
                    )
                ),
                actual_state=status.value,
                reason="; ".join(reason_parts),
            ))

    return checks


def _validate_skin(
    desired: ResolvedBuild,
    actual: KodiState,
    actual_map: Dict[str, InstalledAddon],
) -> list:
    """Validate desired skin state if a skin is specified."""
    if desired.skin is None:
        return []

    skin_id = desired.skin.addon_id
    skin_addon = actual_map.get(skin_id)

    if skin_addon is None:
        return [ValidationCheck(
            domain=ValidationDomain.SKIN,
            subject=skin_id,
            status=ValidationStatus.FAIL,
            expected="installed and active",
            actual_state="not installed",
            reason=f"Desired skin {skin_id!r} is not installed",
        )]

    active = actual.active_skin
    if active != skin_id:
        return [ValidationCheck(
            domain=ValidationDomain.SKIN,
            subject=skin_id,
            status=ValidationStatus.FAIL,
            expected=f"active skin = {skin_id!r}",
            actual_state=f"active skin = {active!r}",
            reason=(
                f"Desired skin {skin_id!r} is installed but not active; "
                f"active skin is {active!r}"
            ),
        )]

    return [ValidationCheck(
        domain=ValidationDomain.SKIN,
        subject=skin_id,
        status=ValidationStatus.PASS,
        expected="installed and active",
        actual_state="installed and active",
        reason=f"Desired skin {skin_id!r} is installed and active",
    )]


def _validate_configuration(
    desired: ResolvedBuild,
    configuration_state: Optional[ConfigurationValidationState],
) -> list:
    """Validate the configuration domain against an optional BM-015 snapshot.

    Four cases, mirroring the dependency-root scope discipline:

    1. desired.config is None
       Configuration validation is not applicable; no checks are emitted.
    2. desired.config present, configuration_state is None
       NOT_CHECKED — nothing inspected configuration state.
    3. desired.config present, snapshot scope exactly matches the declared
       managed scope
       One PASS/FAIL check per declared target (or a single domain PASS when
       the manifest declares no managed targets).
    4. desired.config present, snapshot scope is empty, partial or unrelated
       NOT_CHECKED — a snapshot from a different resolution can never be
       reported as a complete configuration validation.

    Scope comparison is by set equality, so ordering is irrelevant. This
    function never mutates anything; it reads an immutable snapshot the caller
    obtained from BM-015.
    """
    config = desired.config
    if config is None:
        return []

    if configuration_state is None:
        return [ValidationCheck(
            domain=ValidationDomain.CONFIGURATION,
            subject="configuration_domain",
            status=ValidationStatus.NOT_CHECKED,
            expected="managed configuration matches deployed state",
            actual_state="not inspected",
            reason=(
                "No configuration validation state was supplied. Run BM-015 "
                "configuration deployment and pass its validation_state to "
                "validate_build_state() to validate this domain."
            ),
        )]

    declared_settings = {
        (scope.addon_id, key)
        for scope in config.managed_settings
        for key in scope.keys
    }
    declared_files = set(config.managed_files)

    snapshot_settings = set(configuration_state.setting_targets)
    snapshot_files = set(configuration_state.file_targets)

    if snapshot_settings != declared_settings or snapshot_files != declared_files:
        return [ValidationCheck(
            domain=ValidationDomain.CONFIGURATION,
            subject="configuration_domain",
            status=ValidationStatus.NOT_CHECKED,
            expected=(
                f"snapshot covering {len(declared_settings)} managed setting(s) "
                f"and {len(declared_files)} managed file(s)"
            ),
            actual_state=(
                f"snapshot covering {len(snapshot_settings)} setting(s) "
                f"and {len(snapshot_files)} file(s)"
            ),
            reason=(
                "Configuration validation state does not cover exactly the "
                "manifest-declared managed scope. A partial or unrelated "
                "snapshot is never reported as a complete configuration "
                "validation."
            ),
        )]

    if not declared_settings and not declared_files:
        return [ValidationCheck(
            domain=ValidationDomain.CONFIGURATION,
            subject="configuration_domain",
            status=ValidationStatus.PASS,
            expected="no managed configuration targets",
            actual_state="no managed configuration targets",
            reason=(
                "The manifest declares managed configuration but names no "
                "setting or file targets; there is nothing to reconcile."
            ),
        )]

    verified_settings = set(configuration_state.verified_settings)
    verified_files = set(configuration_state.verified_files)

    checks = []
    for addon_id, key in sorted(declared_settings):
        subject = f"{addon_id}/{key}"
        if (addon_id, key) in verified_settings:
            checks.append(ValidationCheck(
                domain=ValidationDomain.CONFIGURATION,
                subject=subject,
                status=ValidationStatus.PASS,
                expected="managed setting matches the desired value",
                actual_state="verified after deployment",
                reason=(
                    f"Managed setting {subject} was verified against its "
                    f"desired value"
                ),
            ))
        else:
            checks.append(ValidationCheck(
                domain=ValidationDomain.CONFIGURATION,
                subject=subject,
                status=ValidationStatus.FAIL,
                expected="managed setting matches the desired value",
                actual_state="not verified",
                reason=(
                    f"Managed setting {subject} was not verified against its "
                    f"desired value"
                ),
            ))

    for destination in sorted(declared_files):
        if destination in verified_files:
            checks.append(ValidationCheck(
                domain=ValidationDomain.CONFIGURATION,
                subject=destination,
                status=ValidationStatus.PASS,
                expected="managed file matches the desired content",
                actual_state="verified after deployment",
                reason=(
                    f"Managed file {destination!r} was verified against its "
                    f"desired content"
                ),
            ))
        else:
            checks.append(ValidationCheck(
                domain=ValidationDomain.CONFIGURATION,
                subject=destination,
                status=ValidationStatus.FAIL,
                expected="managed file matches the desired content",
                actual_state="not verified",
                reason=(
                    f"Managed file {destination!r} was not verified against its "
                    f"desired content"
                ),
            ))

    return checks
