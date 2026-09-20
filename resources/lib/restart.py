"""Typed restart-requirement aggregation for Build Manager (BM-019).

BM-019 records whether a reconciliation actually changed state in a way that
requires a later Kodi restart.  It does not restart Kodi and it does not own
resume/re-entry behavior; those responsibilities belong to BM-020.

Operations declare a :class:`RestartRequirement` on their typed result.  The
orchestration layer records those results through :class:`RestartAggregator`.
Only a successful operation that actually changed state contributes a
requirement.  This makes idempotent reconciliation report ``NONE`` and keeps a
previously established requirement visible when a later independent operation
fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class RestartRequirement(str, Enum):
    """The lifecycle action required after a successful changed operation."""

    NONE = "none"
    KODI_RESTART = "kodi_restart"

    @classmethod
    def combine(cls, *requirements: "RestartRequirement") -> "RestartRequirement":
        """Return the strongest requirement in deterministic precedence order."""
        for requirement in requirements:
            if not isinstance(requirement, cls):
                raise TypeError(
                    "restart requirements must be RestartRequirement values"
                )
        if cls.KODI_RESTART in requirements:
            return cls.KODI_RESTART
        return cls.NONE

    @property
    def human_label(self) -> str:
        """A stable human-readable label derived from the typed value."""
        if self is RestartRequirement.KODI_RESTART:
            return "Kodi restart"
        return "No restart"


@dataclass(frozen=True)
class RestartObservation:
    """One operation outcome presented to the restart aggregator.

    ``changed`` means the operation reports a real state mutation.  A failed
    operation is not considered committed by this contract, even if an
    implementation may have made an unverified partial write; its failed
    reconciliation must be repaired or retried before BM-020 acts on a restart
    requirement.
    """

    requirement: RestartRequirement = RestartRequirement.NONE
    changed: bool = False
    succeeded: bool = True
    operation: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, RestartRequirement):
            raise TypeError("requirement must be a RestartRequirement")
        if not isinstance(self.changed, bool):
            raise TypeError("changed must be bool")
        if not isinstance(self.succeeded, bool):
            raise TypeError("succeeded must be bool")
        if not isinstance(self.operation, str):
            raise TypeError("operation must be str")


@dataclass(frozen=True)
class RestartReport:
    """Immutable aggregate result consumed by a future restart executor."""

    requirement: RestartRequirement = RestartRequirement.NONE
    successful_changes: int = 0
    failed_operations: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, RestartRequirement):
            raise TypeError("requirement must be a RestartRequirement")
        if self.successful_changes < 0 or self.failed_operations < 0:
            raise ValueError("restart report counts cannot be negative")

    @property
    def requires_restart(self) -> bool:
        """Whether BM-020 would need to schedule a Kodi restart."""
        return self.requirement is RestartRequirement.KODI_RESTART

    def to_dict(self) -> dict:
        """Serialize the typed contract without replacing it with free text."""
        return {
            "requirement": self.requirement.value,
            "successful_changes": self.successful_changes,
            "failed_operations": self.failed_operations,
            "requires_restart": self.requires_restart,
        }

    def human_summary(self) -> str:
        """Return concise reporting text derived from the typed requirement."""
        return (
            f"{self.requirement.human_label}; "
            f"{self.successful_changes} successful change(s); "
            f"{self.failed_operations} failed operation(s)"
        )


class RestartAggregator:
    """Monotonic accumulator for operation outcomes and nested reports."""

    def __init__(self) -> None:
        self._requirement = RestartRequirement.NONE
        self._successful_changes = 0
        self._failed_operations = 0

    def record(self, observation: RestartObservation) -> None:
        """Record one typed operation outcome.

        A successful changed operation contributes its declared requirement.
        A no-change or failed operation cannot create a restart requirement.
        """
        if not isinstance(observation, RestartObservation):
            raise TypeError("observation must be a RestartObservation")
        if not observation.succeeded:
            self._failed_operations += 1
            return
        if not observation.changed:
            return
        self._successful_changes += 1
        self._requirement = RestartRequirement.combine(
            self._requirement, observation.requirement
        )

    def record_report(self, report: RestartReport) -> None:
        """Merge a result from a nested subsystem without losing strength."""
        if not isinstance(report, RestartReport):
            raise TypeError("report must be a RestartReport")
        self._successful_changes += report.successful_changes
        self._failed_operations += report.failed_operations
        self._requirement = RestartRequirement.combine(
            self._requirement, report.requirement
        )

    def report(self) -> RestartReport:
        """Return the immutable aggregate snapshot."""
        return RestartReport(
            requirement=self._requirement,
            successful_changes=self._successful_changes,
            failed_operations=self._failed_operations,
        )


def aggregate_restart_requirements(
    observations: Iterable[RestartObservation],
) -> RestartReport:
    """Aggregate operation observations in their supplied execution order."""
    aggregator = RestartAggregator()
    for observation in observations:
        aggregator.record(observation)
    return aggregator.report()


def aggregate_restart_reports(reports: Iterable[RestartReport]) -> RestartReport:
    """Aggregate already-computed subsystem reports for orchestration."""
    aggregator = RestartAggregator()
    for report in reports:
        aggregator.record_report(report)
    return aggregator.report()


def restart_report_for_outcome(
    requirement: RestartRequirement,
    *,
    changed: bool,
    succeeded: bool,
    operation: str = "",
) -> RestartReport:
    """Build a one-operation report for a typed subsystem result."""
    return aggregate_restart_requirements((RestartObservation(
        requirement=requirement,
        changed=changed,
        succeeded=succeeded,
        operation=operation,
    ),))
