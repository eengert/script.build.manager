"""Identity binding for the inputs that describe one selected build (BM-UI-002C).

A selected build is described by up to three independently loaded inputs: the
resolved configuration manifest (``desired``), an optional frozen software
manifest, and an optional install-resolution manifest. None of them is
trustworthy on its own. A frozen graph for a different build, or a record of
some other install's outcomes, would silently change what "current" means.

This module is the single place that proves the inputs belong together.
Read-only status and the read-only plan both call it before using any frozen
or recorded-resolution data. It reuses ``FrozenInstallResolutionManifest``, the
installer's own resolution identity, instead of defining a weaker format.

A trusted resolution set proves, at minimum, that:

* the resolution manifest's build ID is the resolved build's ID;
* its source software fingerprint is the frozen manifest's fingerprint;
* its canonical install-plan fingerprint matches the current effective policies;
* each record is eligible under that policy (including the selected repository);
* it is internally valid (fingerprint formats, unique add-ons, terminal
  states, and a resulting software fingerprint that matches its records);
* every record refers to a managed node of that frozen manifest and agrees with
  the node's captured version and desired enabled state.

Failures raise ``IdentityMismatch`` carrying only a stable enum code: never a
path, fingerprint, or message from the rejected input.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Sequence, Tuple

from resources.lib.frozen import FrozenBuildManifest
from resources.lib.manifest import FrozenInstallPolicy
from resources.lib.frozen_resolution import (
    FrozenInstallResolutionManifest,
    InstallResolutionRecord,
    InstallResolution,
    effective_policy,
    install_plan_fingerprint,
    resolved_software_fingerprint,
)


class IdentityCode(str, Enum):
    FROZEN_BUILD_MISMATCH = "frozen_build_mismatch"
    RESOLUTION_WITHOUT_SOFTWARE = "resolution_without_software"
    RESOLUTION_BUILD_MISMATCH = "resolution_build_mismatch"
    RESOLUTION_SOURCE_MISMATCH = "resolution_source_mismatch"
    RESOLUTION_PLAN_MISMATCH = "resolution_plan_mismatch"
    RESOLUTION_RECORD_MISMATCH = "resolution_record_mismatch"
    RESOLUTION_INVALID = "resolution_invalid"


class IdentityMismatch(Exception):
    """The inputs do not describe one build. ``code`` is the only detail."""

    def __init__(self, code: IdentityCode) -> None:
        super().__init__(code.value)
        self.code = code


def check_frozen_identity(build_id: str, frozen: FrozenBuildManifest) -> None:
    """The frozen graph must be the selected build's own graph."""
    if (
        not isinstance(frozen, FrozenBuildManifest)
        or not isinstance(build_id, str)
        or not build_id
        or frozen.build_id != build_id
    ):
        raise IdentityMismatch(IdentityCode.FROZEN_BUILD_MISMATCH)


def bind_resolutions(
    build_id: str,
    frozen: Optional[FrozenBuildManifest],
    resolution: object,
    *,
    policies: Sequence[FrozenInstallPolicy],
) -> Tuple[InstallResolutionRecord, ...]:
    """Return the records of a resolution manifest proven to belong here.

    ``None`` means no prior resolution and yields no records. Anything that is
    not a ``FrozenInstallResolutionManifest`` bound to exactly this build and
    this frozen manifest and the required current policies is rejected. Raw
    record tuples are never accepted.
    """
    if resolution is None:
        return ()
    if not isinstance(resolution, FrozenInstallResolutionManifest):
        raise IdentityMismatch(IdentityCode.RESOLUTION_INVALID)
    if frozen is None:
        raise IdentityMismatch(IdentityCode.RESOLUTION_WITHOUT_SOFTWARE)
    check_frozen_identity(build_id, frozen)
    if resolution.build_id != build_id:
        raise IdentityMismatch(IdentityCode.RESOLUTION_BUILD_MISMATCH)
    if resolution.source_software_fingerprint != frozen.fingerprint():
        raise IdentityMismatch(IdentityCode.RESOLUTION_SOURCE_MISMATCH)
    try:
        # A directly constructed manifest is not validated; the installer's own
        # parser is. Round-trip through it so every internal invariant is checked.
        checked = FrozenInstallResolutionManifest.from_dict(resolution.to_dict())
    except Exception as exc:
        raise IdentityMismatch(IdentityCode.RESOLUTION_INVALID) from exc
    try:
        expected = install_plan_fingerprint(frozen, policies)
    except Exception as exc:
        raise IdentityMismatch(IdentityCode.RESOLUTION_INVALID) from exc
    if checked.install_plan_fingerprint != expected:
        raise IdentityMismatch(IdentityCode.RESOLUTION_PLAN_MISMATCH)
    selected = {policy.addon_id: policy for policy in policies}
    nodes = {node.addon_id: node for node in frozen.addons}
    for record in checked.records:
        node = nodes.get(record.addon_id)
        if (
            node is None
            or node.system
            or node.is_absent_optional_dependency
            or record.captured_version != node.version
            or record.desired_enabled is not node.desired_enabled
        ):
            raise IdentityMismatch(IdentityCode.RESOLUTION_RECORD_MISMATCH)
        policy = effective_policy(record.addon_id, selected)
        if (
            record.resolution is InstallResolution.REPOSITORY_CURRENT
            and (not policy.repository_fallback_allowed or record.repository_id != policy.repository_id)
        ) or (record.resolution is InstallResolution.SKIPPED and not policy.skip_allowed):
            raise IdentityMismatch(IdentityCode.RESOLUTION_RECORD_MISMATCH)
    try:
        if resolved_software_fingerprint(frozen, checked.records) != checked.resulting_software_fingerprint:
            raise IdentityMismatch(IdentityCode.RESOLUTION_INVALID)
    except IdentityMismatch:
        raise
    except Exception as exc:
        raise IdentityMismatch(IdentityCode.RESOLUTION_RECORD_MISMATCH) from exc
    return tuple(sorted(checked.records, key=lambda record: record.addon_id))


__all__ = ["IdentityCode", "IdentityMismatch", "bind_resolutions", "check_frozen_identity"]
