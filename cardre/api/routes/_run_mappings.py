"""Pure mapping functions: domain objects → API response models.

Every function in this module is a pure data transformation with no
side effects, no I/O, and no dependencies on FastAPI or the store.
"""

from __future__ import annotations

from cardre.api.schemas import (
    EvidenceArtifactResponse,
    EvidenceEdgeResponse,
    RunEvidenceEdgeResponse,
    RunResponse,
    RunStepResponse,
)
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
from cardre.domain.run import RunStep
from cardre.services.run_coordinator import RunSummary


def run_summary_to_response(summary: RunSummary) -> RunResponse:
    """Map a ``RunSummary`` dataclass to a ``RunResponse`` model."""
    return RunResponse(
        run_id=summary.run_id,
        plan_version_id=summary.plan_version_id,
        status=summary.status,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        step_count=summary.step_count,
        branch_id=summary.branch_id,
        executed_step_ids=summary.executed_step_ids or [],
        diagnostics=summary.diagnostics or [],
        latest_error=summary.latest_error,
        heartbeat_at=summary.heartbeat_at,
        is_stale=summary.is_stale,
    )


def run_step_to_response(rs: RunStep) -> RunStepResponse:
    """Map a ``RunStep`` domain object to a ``RunStepResponse`` model."""
    return RunStepResponse(
        run_step_id=rs.run_step_id,
        run_id=rs.run_id,
        step_id=rs.step_id,
        plan_version_id=rs.plan_version_id,
        status=rs.status.value,
        started_at=rs.started_at,
        finished_at=rs.finished_at,
        execution_fingerprint=rs.execution_fingerprint,
        warnings=rs.warnings,
        errors=rs.errors,
    )


def evidence_edge_to_response(
    edge: EvidenceEdge,
    artifacts: list[EvidenceArtifact],
) -> RunEvidenceEdgeResponse:
    """Map an ``EvidenceEdge`` + its artifacts to a ``RunEvidenceEdgeResponse``."""
    return RunEvidenceEdgeResponse(
        evidence_edge_id=edge.evidence_edge_id,
        run_id=edge.run_id,
        run_step_id=edge.run_step_id,
        plan_version_id=edge.plan_version_id,
        step_id=edge.step_id,
        parent_step_id=edge.parent_step_id,
        source_run_id=edge.source_run_id,
        source_run_step_id=edge.source_run_step_id,
        policy=edge.policy,
        source_label=edge.source_label,
        is_reused=edge.is_reused,
        is_stale=edge.is_stale,
        stale_reason=edge.stale_reason,
        created_at=edge.created_at,
        artifacts=[evidence_artifact_to_response(a, edge.evidence_edge_id) for a in artifacts],
    )


def evidence_artifact_to_response(
    art: EvidenceArtifact,
    evidence_edge_id: str,
) -> EvidenceArtifactResponse:
    """Map an ``EvidenceArtifact`` domain object to an ``EvidenceArtifactResponse``."""
    return EvidenceArtifactResponse(
        evidence_artifact_id=art.evidence_artifact_id,
        evidence_edge_id=evidence_edge_id,
        artifact_id=art.artifact_id,
        role=art.role,
        created_at=art.created_at,
    )


def evidence_edge_to_brief_response(edge: EvidenceEdge) -> EvidenceEdgeResponse:
    """Map an ``EvidenceEdge`` to an ``EvidenceEdgeResponse`` (without nested artifacts).

    This is a subset of ``evidence_edge_to_response`` used by the standalone
    evidence endpoints that return ``EvidenceEdgeResponse``.
    """
    return EvidenceEdgeResponse(
        evidence_edge_id=edge.evidence_edge_id,
        run_id=edge.run_id,
        run_step_id=edge.run_step_id,
        plan_version_id=edge.plan_version_id,
        step_id=edge.step_id,
        parent_step_id=edge.parent_step_id,
        source_run_id=edge.source_run_id,
        source_run_step_id=edge.source_run_step_id,
        policy=edge.policy,
        source_label=edge.source_label,
        is_reused=edge.is_reused,
        is_stale=edge.is_stale,
        stale_reason=edge.stale_reason,
        created_at=edge.created_at,
    )
