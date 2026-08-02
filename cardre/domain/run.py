"""Run and RunStep domain types — run state machine.

Run state machine::

    submitted → running → succeeded
                          → failed
                          → cancelled
                          → interrupted

``RunStep`` does **not** own ``input_artifact_ids`` or
``output_artifact_ids`` — those are derived via
``RunStepEvidenceView`` from ``evidence_artifacts`` +
``artifact_lineage``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cardre.domain.diagnostics import JsonDict, utc_now_iso

if TYPE_CHECKING:
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.evidence import EvidenceEdge


class RunStepStatus(enum.Enum):
    """Status values for individual run steps."""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunStatus(enum.StrEnum):
    """Status values for runs — the run-level state machine."""
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"

    @classmethod
    def terminal(cls) -> set[RunStatus]:
        return {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.INTERRUPTED, RunStatus.CANCELLED}


class RunScope(enum.StrEnum):
    """Execution scope discriminator for a run."""
    FULL_PLAN = "full_plan"
    BRANCH = "branch"


_VALID_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.SUBMITTED: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.RUNNING: {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
    RunStatus.INTERRUPTED: set(),
}


def _check_transition(current: RunStatus, target: RunStatus) -> None:
    allowed = _VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Invalid run state transition: {current!r} -> {target!r}. "
            f"Allowed transitions from {current!r}: {sorted(allowed)}"
        )


@dataclass(frozen=True)
class Run:
    """A single execution run of a plan version."""
    run_id: str
    plan_version_id: str
    status: str  # one of the state machine values above
    started_at: str
    finished_at: str | None = None
    branch_id: str | None = None
    force: bool = False
    run_scope: str = "full_plan"
    heartbeat_at: str | None = None
    cancel_requested: bool = False
    worker_generation: int = 0
    metadata: JsonDict = field(default_factory=dict)

    def transition_to(self, new_status: str) -> Run:
        """Return a new ``Run`` with the given status, or raise."""
        _check_transition(RunStatus(self.status), RunStatus(new_status))
        import copy

        terminal_statuses = {s.value for s in RunStatus.terminal()}
        return Run(
            run_id=self.run_id,
            plan_version_id=self.plan_version_id,
            status=new_status,
            started_at=self.started_at,
            finished_at=utc_now_iso() if new_status in terminal_statuses else None,
            branch_id=self.branch_id,
            force=self.force,
            run_scope=self.run_scope,
            heartbeat_at=self.heartbeat_at,
            cancel_requested=self.cancel_requested,
            worker_generation=self.worker_generation,
            metadata=copy.deepcopy(self.metadata),
        )

    def is_stale(self, *, stale_heartbeat_seconds: int, now_ts: float | None = None) -> bool:
        """A run is stale only if it is running AND its persisted heartbeat is
        older than the staleness threshold (or absent/malformed).

        A healthy running run with a recent heartbeat is fresh; a running run
        with no heartbeat is stale; a non-running run is never stale.

        ``now_ts`` is injectable for deterministic tests; defaults to now.
        """
        if self.status != RunStatus.RUNNING.value:
            return False
        hb = self.heartbeat_at
        if hb is None:
            return True
        if now_ts is None:
            now_ts = datetime.now(UTC).timestamp()
        try:
            hb_ts = datetime.fromisoformat(hb).replace(tzinfo=UTC).timestamp()
        except (ValueError, TypeError):
            return True
        return (now_ts - hb_ts) > stale_heartbeat_seconds


@dataclass(frozen=True)
class RunStep:
    """A single step execution record within a run.

    Does **not** carry ``input_artifact_ids`` or ``output_artifact_ids``.
    Those are derived from ``evidence_edges`` + ``evidence_artifacts`` +
    ``artifact_lineage`` at query time (see ``RunStepEvidenceView``).
    """
    run_step_id: str
    run_id: str
    step_id: str
    plan_version_id: str
    status: RunStepStatus
    started_at: str
    finished_at: str | None = None
    execution_fingerprint: JsonDict = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionFingerprint:
    params_hash: str
    node_type: str
    node_version: str


@dataclass(frozen=True)
class RunStepEvidenceView:
    """Aggregate view of a run step with derived artifact references."""
    run_step: RunStep
    input_artifacts: list[ArtifactRef] = field(default_factory=list)
    output_artifacts: list[ArtifactRef] = field(default_factory=list)
    evidence_edges: list[EvidenceEdge] = field(default_factory=list)


__all__ = [
    "ExecutionFingerprint",
    "Run",
    "RunScope",
    "RunStatus",
    "RunStep",
    "RunStepEvidenceView",
    "RunStepStatus",
]
