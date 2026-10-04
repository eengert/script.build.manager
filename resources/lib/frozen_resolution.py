"""Explicit recovery policy and identity for frozen-install plans.

Captured manifests remain immutable source evidence. This module classifies
artifact recoverability and represents operator-selected installation outcomes
without weakening exact-artifact validation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping, Optional, Sequence, Tuple

from resources.lib.artifacts import (
    ArtifactStore,
    ArtifactStoreError,
    ArtifactValidationError,
    validate_addon_zip,
)
from resources.lib.frozen import AddonCaptureNode, CaptureStatus, FrozenBuildManifest
from resources.lib.manifest import FrozenInstallPolicy, FrozenInstallPolicyMode
from resources.lib.repository import validate_repository_zip


class FrozenResolutionError(Exception):
    """A recovery policy or resolution record is invalid."""


class Recoverability(str, Enum):
    EXACT_FROZEN = "exact_frozen"
    REPOSITORY_RECOVERABLE = "repository_recoverable"
    MANUAL_OR_SKIP = "manual_or_skip"
    BLOCKING_UNRECOVERABLE = "blocking_unrecoverable"


class InstallResolution(str, Enum):
    EXACT = "exact"
    REPOSITORY_CURRENT = "repository_current"
    SKIPPED = "skipped"


class ResolutionState(str, Enum):
    SELECTED = "selected"
    RESOLVED = "resolved"
    INSTALLED = "installed"
    SKIPPED = "skipped"


class ResolutionChoice(str, Enum):
    INSTALL_CURRENT = "install_current"
    SKIP = "skip"
    CANCEL = "cancel"


class FrozenPlanActionKind(str, Enum):
    INSTALL_EXACT_ARTIFACT = "install_exact_artifact"
    PROMPT_REPOSITORY_OR_SKIP = "prompt_repository_or_skip"
    PROMPT_REPOSITORY_OR_CANCEL = "prompt_repository_or_cancel"
    PROMPT_SKIP_OR_CANCEL = "prompt_skip_or_cancel"
    BLOCKING_UNRECOVERABLE = "blocking_unrecoverable"
    SKIPPED = "skipped"


_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_REPOSITORY_ID = re.compile(r"^repository\.[a-z0-9._-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _policy_map(
    manifest: FrozenBuildManifest,
    policies: Sequence[FrozenInstallPolicy] = (),
) -> Dict[str, FrozenInstallPolicy]:
    node_ids = {node.addon_id for node in manifest.addons}
    result: Dict[str, FrozenInstallPolicy] = {}
    for policy in policies:
        if not isinstance(policy, FrozenInstallPolicy):
            raise FrozenResolutionError("frozen install policy has an invalid type")
        if not _ADDON_ID.fullmatch(policy.addon_id):
            raise FrozenResolutionError("frozen install policy add-on ID is invalid")
        if policy.addon_id not in node_ids:
            raise FrozenResolutionError("frozen install policy targets an add-on absent from capture")
        if policy.addon_id in result:
            raise FrozenResolutionError("frozen install policies contain duplicate add-on IDs")
        if policy.repository_id and not _REPOSITORY_ID.fullmatch(policy.repository_id):
            raise FrozenResolutionError("frozen install policy repository ID is invalid")
        if policy.repository_id and not policy.repository_fallback_allowed:
            raise FrozenResolutionError("exact-only policy cannot declare a repository")
        result[policy.addon_id] = policy
    return result


def effective_policy(
    addon_id: str, policies: Mapping[str, FrozenInstallPolicy]
) -> FrozenInstallPolicy:
    return policies.get(
        addon_id,
        FrozenInstallPolicy(addon_id, FrozenInstallPolicyMode.EXACT_REQUIRED),
    )


def _installed_managed_nodes(manifest: FrozenBuildManifest) -> Tuple[AddonCaptureNode, ...]:
    return tuple(
        node for node in manifest.addons
        if not node.system and not node.is_absent_optional_dependency
    )


def _exact_artifact(node: AddonCaptureNode, store: ArtifactStore) -> bool:
    if node.artifact is None:
        return False
    if node.status is not CaptureStatus.COMPLETE:
        raise FrozenResolutionError("captured artifact has an inconsistent node status")
    try:
        metadata = store.get_metadata(node.artifact.sha256)
        data = store.read_bytes(node.artifact.sha256)
        if (
            metadata.sha256 != node.artifact.sha256
            or metadata.addon_id != node.addon_id
            or metadata.version != node.version
            or metadata.size != node.artifact.size
            or len(data) != node.artifact.size
            or hashlib.sha256(data).hexdigest() != node.artifact.sha256
        ):
            raise FrozenResolutionError(f"exact artifact identity mismatch for {node.addon_id}")
        validate_addon_zip(data, expected_addon_id=node.addon_id, expected_version=node.version)
    except ArtifactStoreError as exc:
        if (
            not store.artifact_path(node.artifact.sha256).exists()
            or not store.metadata_path(node.artifact.sha256).exists()
        ):
            return False
        raise FrozenResolutionError(
            f"exact artifact store integrity failed for {node.addon_id}"
        ) from exc
    except FrozenResolutionError:
        raise
    except Exception as exc:
        raise FrozenResolutionError(f"exact artifact validation failed for {node.addon_id}") from exc
    return True


def _trusted_repository_id(
    policy: FrozenInstallPolicy,
    nodes: Mapping[str, AddonCaptureNode],
    store: ArtifactStore,
) -> str:
    repository_id = policy.repository_id
    if not repository_id:
        return ""
    node = nodes.get(repository_id)
    if (
        node is None
        or node.system
        or node.is_absent_optional_dependency
        or node.addon_type != "xbmc.addon.repository"
        or not node.desired_enabled
        or node.artifact is None
        or node.status is not CaptureStatus.COMPLETE
    ):
        return ""
    try:
        metadata = store.get_metadata(node.artifact.sha256)
        data = store.read_bytes(node.artifact.sha256)
        if (
            metadata.sha256 != node.artifact.sha256
            or metadata.addon_id != repository_id
            or metadata.version != node.version
            or metadata.size != node.artifact.size
            or len(data) != node.artifact.size
            or hashlib.sha256(data).hexdigest() != node.artifact.sha256
        ):
            return ""
        validate_repository_zip(data, expected_addon_id=repository_id)
    except Exception:
        return ""
    return repository_id


def _required_dependents(manifest: FrozenBuildManifest, addon_id: str) -> Tuple[str, ...]:
    return tuple(sorted({
        node.addon_id
        for node in _installed_managed_nodes(manifest)
        if node.addon_id != addon_id
        and any(edge.addon_id == addon_id and not edge.optional for edge in node.dependency_edges)
    }))


@dataclass(frozen=True)
class AddonRecoverability:
    addon_id: str
    captured_version: str
    recoverability: Recoverability
    exact_artifact_available: bool
    installed_on_source: bool = True
    repository_id: str = ""
    repository_known: bool = False
    repository_fallback_permitted: bool = False
    fallback_eligible: bool = False
    skip_eligible: bool = False
    manual_action_possible: bool = False
    dependency_skip_blockers: Tuple[str, ...] = ()

    @property
    def likely_installation_behavior(self) -> str:
        if self.exact_artifact_available:
            return "install exact captured version"
        if self.repository_known and self.fallback_eligible:
            return "ask before installing current repository version"
        if self.skip_eligible:
            return "ask to skip; manual installation may be needed later"
        return "blocks installation"

    def to_dict(self) -> dict:
        return {
            "addon_id": self.addon_id,
            "captured_version": self.captured_version,
            "installed_on_source": self.installed_on_source,
            "recoverability": self.recoverability.value,
            "exact_artifact": "available" if self.exact_artifact_available else "unavailable",
            "repository_id": self.repository_id or None,
            "repository_known": self.repository_known,
            "repository_fallback_permitted": self.repository_fallback_permitted,
            "fallback_eligible": self.fallback_eligible,
            "skip_eligible": self.skip_eligible,
            "likely_installation_behavior": self.likely_installation_behavior,
            "manual_action_possible": self.manual_action_possible,
            "dependency_skip_blockers": list(self.dependency_skip_blockers),
        }


@dataclass(frozen=True)
class FrozenBuildRecoverabilitySummary:
    captured_desired_state: str
    exact_frozen_available: int
    installed_managed_addons: int
    install_recoverability: str
    addons: Tuple[AddonRecoverability, ...]

    @property
    def exact_frozen_coverage(self) -> str:
        return f"{self.exact_frozen_available} / {self.installed_managed_addons}"

    def to_dict(self) -> dict:
        return {
            "captured_desired_state": self.captured_desired_state,
            "exact_frozen_coverage": self.exact_frozen_coverage,
            "install_recoverability": self.install_recoverability,
            "addons": [row.to_dict() for row in self.addons],
        }


def summarize_frozen_recoverability(
    manifest: FrozenBuildManifest,
    store: ArtifactStore,
    policies: Sequence[FrozenInstallPolicy] = (),
) -> FrozenBuildRecoverabilitySummary:
    """Report source state, exact coverage, and separately declared recovery."""
    if not isinstance(manifest, FrozenBuildManifest):
        raise FrozenResolutionError("recoverability requires a typed frozen manifest")
    effective = _policy_map(manifest, policies)
    nodes = {node.addon_id: node for node in manifest.addons}
    rows = []
    for node in _installed_managed_nodes(manifest):
        exact = _exact_artifact(node, store)
        policy = effective_policy(node.addon_id, effective)
        repository_id = _trusted_repository_id(policy, nodes, store)
        blockers = _required_dependents(manifest, node.addon_id)
        gap_recoverable = (
            node.status in (
                CaptureStatus.COMPLETE,
                CaptureStatus.INCOMPLETE_ARTIFACT,
                CaptureStatus.INCOMPLETE_PROVENANCE,
                CaptureStatus.INVALID_PACKAGE,
            )
            and bool(node.version)
            and bool(node.addon_type)
        )
        skip_eligible = policy.skip_allowed and gap_recoverable and not blockers
        if exact:
            state = Recoverability.EXACT_FROZEN
        elif policy.repository_fallback_allowed and repository_id and gap_recoverable:
            state = Recoverability.REPOSITORY_RECOVERABLE
        elif skip_eligible:
            state = Recoverability.MANUAL_OR_SKIP
        else:
            state = Recoverability.BLOCKING_UNRECOVERABLE
        rows.append(AddonRecoverability(
            addon_id=node.addon_id,
            captured_version=node.version,
            recoverability=state,
            exact_artifact_available=exact,
            installed_on_source=node.status is not CaptureStatus.MISSING,
            repository_id=repository_id,
            repository_known=bool(repository_id),
            repository_fallback_permitted=policy.repository_fallback_allowed,
            fallback_eligible=(
                policy.repository_fallback_allowed and bool(repository_id) and gap_recoverable
            ),
            skip_eligible=skip_eligible,
            manual_action_possible=skip_eligible,
            dependency_skip_blockers=blockers,
        ))

    inventory_statuses = {
        CaptureStatus.COMPLETE,
        CaptureStatus.INCOMPLETE_ARTIFACT,
        CaptureStatus.INCOMPLETE_PROVENANCE,
        CaptureStatus.INVALID_PACKAGE,
    }
    desired_state_complete = all(
        node.is_absent_optional_dependency
        or node.system
        or (
            node.status in inventory_statuses
            and bool(node.version)
            and bool(node.addon_type)
        )
        for node in manifest.addons
    )
    if any(row.recoverability is Recoverability.BLOCKING_UNRECOVERABLE for row in rows):
        overall = "blocking_unrecoverable"
    elif any(row.recoverability is Recoverability.MANUAL_OR_SKIP for row in rows):
        overall = "manual_or_skip_action_required"
    elif any(row.recoverability is Recoverability.REPOSITORY_RECOVERABLE for row in rows):
        overall = "interactive_fallback_available"
    else:
        overall = "fully_automatic"
    return FrozenBuildRecoverabilitySummary(
        "complete" if desired_state_complete else "incomplete",
        sum(1 for row in rows if row.installed_on_source and row.exact_artifact_available),
        sum(1 for row in rows if row.installed_on_source),
        overall,
        tuple(rows),
    )


@dataclass(frozen=True)
class FrozenPlanAction:
    kind: FrozenPlanActionKind
    addon_id: str


@dataclass(frozen=True)
class ResolutionPrompt:
    addon_id: str
    captured_version: str
    repository_id: str = ""
    skip_allowed: bool = False

    @property
    def repository_known(self) -> bool:
        return bool(self.repository_id)


@dataclass(frozen=True)
class InstallResolutionRecord:
    addon_id: str
    captured_version: str
    resolution: InstallResolution
    state: ResolutionState
    desired_enabled: bool = True
    repository_id: str = ""
    resolved_version: str = ""
    artifact_sha256: str = ""
    artifact_size: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.addon_id, str) or not _ADDON_ID.fullmatch(self.addon_id):
            raise FrozenResolutionError("resolution add-on ID is invalid")
        if not isinstance(self.captured_version, str) or not self.captured_version:
            raise FrozenResolutionError("resolution captured version is invalid")
        if not isinstance(self.resolution, InstallResolution):
            raise FrozenResolutionError("resolution kind is invalid")
        if not isinstance(self.state, ResolutionState):
            raise FrozenResolutionError("resolution state is invalid")
        if not isinstance(self.desired_enabled, bool):
            raise FrozenResolutionError("resolution desired enabled state is invalid")
        if not isinstance(self.repository_id, str) or not isinstance(self.resolved_version, str):
            raise FrozenResolutionError("resolution version or repository identity is invalid")
        if not isinstance(self.artifact_sha256, str):
            raise FrozenResolutionError("resolution artifact digest is invalid")
        if self.repository_id and not _REPOSITORY_ID.fullmatch(self.repository_id):
            raise FrozenResolutionError("resolution repository ID is invalid")
        if self.resolution is InstallResolution.EXACT:
            if self.state not in (ResolutionState.SELECTED, ResolutionState.INSTALLED):
                raise FrozenResolutionError("exact resolution state is inconsistent")
            if self.repository_id or self.resolved_version != self.captured_version:
                raise FrozenResolutionError("exact resolution identity is inconsistent")
            if not _SHA256.fullmatch(self.artifact_sha256) or self.artifact_size is None:
                raise FrozenResolutionError("exact resolution artifact identity is incomplete")
        elif self.resolution is InstallResolution.REPOSITORY_CURRENT:
            if not self.repository_id:
                raise FrozenResolutionError("repository resolution has no repository identity")
            if self.state is ResolutionState.SELECTED and (
                self.resolved_version or self.artifact_sha256 or self.artifact_size is not None
            ):
                raise FrozenResolutionError("selected repository resolution has package data")
            if self.state in (ResolutionState.RESOLVED, ResolutionState.INSTALLED) and (
                not self.resolved_version
                or not _SHA256.fullmatch(self.artifact_sha256)
                or self.artifact_size is None
            ):
                raise FrozenResolutionError("repository resolution artifact identity is incomplete")
            if self.state is ResolutionState.SKIPPED:
                raise FrozenResolutionError("repository resolution cannot be skipped")
        elif self.resolution is InstallResolution.SKIPPED:
            if self.repository_id or self.resolved_version or self.artifact_sha256 or self.artifact_size is not None:
                raise FrozenResolutionError("skipped resolution carries install artifact data")
            if self.state is not ResolutionState.SKIPPED:
                raise FrozenResolutionError("skipped resolution state is inconsistent")
        if self.artifact_size is not None and (
            isinstance(self.artifact_size, bool)
            or not isinstance(self.artifact_size, int)
            or self.artifact_size < 0
        ):
            raise FrozenResolutionError("resolution artifact size is invalid")

    def semantic_dict(self) -> dict:
        return {
            "addon_id": self.addon_id,
            "captured_version": self.captured_version,
            "resolution": self.resolution.value,
            "desired_enabled": self.desired_enabled,
            "repository_id": self.repository_id or None,
            "resolved_version": self.resolved_version or None,
            "artifact_sha256": self.artifact_sha256 or None,
            "artifact_size": self.artifact_size,
        }

    def to_dict(self) -> dict:
        value = self.semantic_dict()
        value["state"] = self.state.value
        return value

    @classmethod
    def from_dict(cls, value: object) -> "InstallResolutionRecord":
        expected = {
            "addon_id", "captured_version", "resolution", "state", "repository_id",
            "resolved_version", "artifact_sha256", "artifact_size", "desired_enabled",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise FrozenResolutionError("resolution record fields are unsupported")
        try:
            return cls(
                addon_id=value["addon_id"],
                captured_version=value["captured_version"],
                resolution=InstallResolution(value["resolution"]),
                state=ResolutionState(value["state"]),
                desired_enabled=value["desired_enabled"],
                repository_id=value["repository_id"] or "",
                resolved_version=value["resolved_version"] or "",
                artifact_sha256=value["artifact_sha256"] or "",
                artifact_size=value["artifact_size"],
            )
        except (TypeError, ValueError) as exc:
            raise FrozenResolutionError("resolution record contains invalid values") from exc


def policy_fingerprint(
    manifest: FrozenBuildManifest,
    policies: Sequence[FrozenInstallPolicy],
) -> str:
    selected = _policy_map(manifest, policies)
    rows = [effective_policy(node.addon_id, selected).to_dict() for node in _installed_managed_nodes(manifest)]
    return _canonical_digest(rows)


def install_plan_fingerprint(
    manifest: FrozenBuildManifest,
    policies: Sequence[FrozenInstallPolicy],
) -> str:
    return _canonical_digest({
        "source_software_fingerprint": manifest.fingerprint(),
        "policy_fingerprint": policy_fingerprint(manifest, policies),
    })


def resolution_fingerprint(records: Sequence[InstallResolutionRecord]) -> str:
    return _canonical_digest([
        record.semantic_dict() for record in sorted(records, key=lambda row: row.addon_id)
    ])


def resolved_software_fingerprint(
    manifest: FrozenBuildManifest,
    records: Sequence[InstallResolutionRecord],
) -> str:
    nodes = {node.addon_id: node for node in manifest.addons}
    rows = []
    for record in sorted(records, key=lambda item: item.addon_id):
        node = nodes.get(record.addon_id)
        if node is None or node.version != record.captured_version:
            raise FrozenResolutionError("resolution record does not match captured software")
        if record.resolution is InstallResolution.SKIPPED:
            if record.desired_enabled is not node.desired_enabled:
                raise FrozenResolutionError("resolution changed captured desired enabled state")
            rows.append({"addon_id": record.addon_id, "state": "intentionally_skipped"})
        else:
            if not record.resolved_version or not record.artifact_sha256:
                raise FrozenResolutionError("resolved software identity is incomplete")
            if record.desired_enabled is not node.desired_enabled:
                raise FrozenResolutionError("resolution changed captured desired enabled state")
            rows.append({
                "addon_id": record.addon_id,
                "state": "installed",
                "version": record.resolved_version,
                "enabled": record.desired_enabled,
                "artifact_sha256": record.artifact_sha256,
            })
    return _canonical_digest({
        "source_software_fingerprint": manifest.fingerprint(),
        "addons": rows,
    })


def _resolved_fingerprint_from_records(
    source_fingerprint: str,
    records: Sequence[InstallResolutionRecord],
) -> str:
    rows = []
    for record in sorted(records, key=lambda item: item.addon_id):
        if record.resolution is InstallResolution.SKIPPED:
            rows.append({"addon_id": record.addon_id, "state": "intentionally_skipped"})
            continue
        if not record.resolved_version or not record.artifact_sha256:
            raise FrozenResolutionError("resolved software identity is incomplete")
        rows.append({
            "addon_id": record.addon_id,
            "state": "installed",
            "version": record.resolved_version,
            "enabled": record.desired_enabled,
            "artifact_sha256": record.artifact_sha256,
        })
    return _canonical_digest({"source_software_fingerprint": source_fingerprint, "addons": rows})


@dataclass(frozen=True)
class FrozenInstallResolutionManifest:
    build_id: str
    source_software_fingerprint: str
    install_plan_fingerprint: str
    resulting_software_fingerprint: str
    records: Tuple[InstallResolutionRecord, ...]

    @property
    def resolution_fingerprint(self) -> str:
        return resolution_fingerprint(self.records)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "resolution_id": f"sha256:{self.resolution_fingerprint}",
            "build_id": self.build_id,
            "source_software_fingerprint": self.source_software_fingerprint,
            "install_plan_fingerprint": self.install_plan_fingerprint,
            "resolution_fingerprint": self.resolution_fingerprint,
            "resulting_software_fingerprint": self.resulting_software_fingerprint,
            "records": [record.to_dict() for record in sorted(self.records, key=lambda item: item.addon_id)],
        }

    @classmethod
    def from_dict(cls, value: object) -> "FrozenInstallResolutionManifest":
        required = {
            "schema_version", "resolution_id", "build_id", "source_software_fingerprint",
            "install_plan_fingerprint", "resolution_fingerprint",
            "resulting_software_fingerprint", "records",
        }
        if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1:
            raise FrozenResolutionError("install resolution manifest fields are unsupported")
        raw_records = value["records"]
        if not isinstance(raw_records, list):
            raise FrozenResolutionError("install resolution records must be an array")
        try:
            manifest = cls(
                build_id=value["build_id"],
                source_software_fingerprint=value["source_software_fingerprint"],
                install_plan_fingerprint=value["install_plan_fingerprint"],
                resulting_software_fingerprint=value["resulting_software_fingerprint"],
                records=tuple(InstallResolutionRecord.from_dict(item) for item in raw_records),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FrozenResolutionError("install resolution manifest contains invalid values") from exc
        for fingerprint in (
            manifest.source_software_fingerprint,
            manifest.install_plan_fingerprint,
            manifest.resulting_software_fingerprint,
        ):
            if not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint):
                raise FrozenResolutionError("install resolution fingerprint is invalid")
        if value["resolution_fingerprint"] != manifest.resolution_fingerprint:
            raise FrozenResolutionError("install resolution fingerprint does not match records")
        if value["resolution_id"] != f"sha256:{manifest.resolution_fingerprint}":
            raise FrozenResolutionError("install resolution ID does not match records")
        if len({record.addon_id for record in manifest.records}) != len(manifest.records):
            raise FrozenResolutionError("install resolution contains duplicate add-on IDs")
        if any(record.state not in (ResolutionState.INSTALLED, ResolutionState.SKIPPED) for record in manifest.records):
            raise FrozenResolutionError("completed install resolution contains unfinished records")
        if manifest.resulting_software_fingerprint != _resolved_fingerprint_from_records(
            manifest.source_software_fingerprint, manifest.records
        ):
            raise FrozenResolutionError("resulting software fingerprint does not match records")
        return manifest


def default_exact_record(node: AddonCaptureNode) -> InstallResolutionRecord:
    if node.artifact is None:
        raise FrozenResolutionError("exact record requires captured artifact metadata")
    return InstallResolutionRecord(
        node.addon_id,
        node.version,
        InstallResolution.EXACT,
        ResolutionState.SELECTED,
        resolved_version=node.version,
        artifact_sha256=node.artifact.sha256,
        artifact_size=node.artifact.size,
        desired_enabled=node.desired_enabled,
    )


__all__ = [
    "AddonRecoverability", "FrozenBuildRecoverabilitySummary", "FrozenInstallResolutionManifest",
    "FrozenPlanAction", "FrozenPlanActionKind", "FrozenResolutionError", "InstallResolution",
    "InstallResolutionRecord", "Recoverability", "ResolutionChoice", "ResolutionPrompt",
    "ResolutionState", "default_exact_record", "effective_policy", "install_plan_fingerprint",
    "policy_fingerprint", "resolution_fingerprint", "resolved_software_fingerprint",
    "summarize_frozen_recoverability",
]
