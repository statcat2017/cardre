"""Pure mapping functions: domain objects → API response models.

Every function in this module is a pure data transformation with no
side effects, no I/O, and no dependencies on FastAPI or the store.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cardre._version import __version__
from cardre.api.schemas import (
    BranchResponse,
    ComparisonResponse,
    EvidenceArtifactResponse,
    EvidenceEdgeResponse,
    NodeTypeResponse,
    PlanResponse,
    PlanVersionResponse,
    ProjectResponse,
    RunEvidenceEdgeResponse,
    RunResponse,
    RunStepResponse,
)
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
from cardre.domain.plan import Plan, PlanVersion
from cardre.domain.run import RunStep
from cardre.services.run_coordinator import RunSummary


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


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


def plan_to_response(plan: Plan | Mapping[str, Any]) -> PlanResponse:
    return PlanResponse(
        plan_id=_value(plan, "plan_id"),
        project_id=_value(plan, "project_id"),
        name=_value(plan, "name"),
        created_at=_value(plan, "created_at"),
    )


def plan_version_to_response(plan_version: PlanVersion | Mapping[str, Any]) -> PlanVersionResponse:
    return PlanVersionResponse(
        plan_version_id=_value(plan_version, "plan_version_id"),
        plan_id=_value(plan_version, "plan_id"),
        version_number=_value(plan_version, "version_number"),
        is_committed=bool(_value(plan_version, "is_committed", False)),
        created_at=_value(plan_version, "created_at"),
        description=_value(plan_version, "description", ""),
    )


def branch_to_response(branch: Mapping[str, Any]) -> BranchResponse:
    return BranchResponse(
        branch_id=branch["branch_id"],
        project_id=branch["project_id"],
        plan_id=branch["plan_id"],
        name=branch["name"],
        description=branch.get("description"),
        branch_type=branch["branch_type"],
        status=branch.get("status", "active"),
        base_branch_id=branch.get("base_branch_id"),
        base_plan_version_id=branch["base_plan_version_id"],
        head_plan_version_id=branch["head_plan_version_id"],
        branch_point_step_id=branch.get("branch_point_step_id"),
        branch_point_canonical_step_id=branch.get("branch_point_canonical_step_id"),
        created_reason=branch.get("created_reason", ""),
        created_at=branch.get("created_at", ""),
        updated_at=branch.get("updated_at", ""),
    )


def comparison_to_response(comparison: Mapping[str, Any]) -> ComparisonResponse:
    return ComparisonResponse(
        comparison_id=comparison["comparison_id"],
        project_id=comparison["project_id"],
        plan_id=comparison["plan_id"],
        baseline_branch_id=comparison["baseline_branch_id"],
        created_at=comparison.get("created_at", ""),
        latest_ready=comparison.get("latest_ready"),
    )


def project_to_response(
    project: Mapping[str, Any],
    *,
    cardre_version: str | None = None,
) -> ProjectResponse:
    return ProjectResponse(
        project_id=project["project_id"],
        name=project["name"],
        created_at=project["created_at"],
        cardre_version=project.get("cardre_version", cardre_version or __version__),
    )


def node_type_to_response(
    node_type: str,
    *,
    category: str = "",
    description: str = "",
    tier: str = "launch",
    has_params: bool = True,
) -> NodeTypeResponse:
    return NodeTypeResponse(
        node_type=node_type,
        display_name=node_type.split(".")[-1] if "." in node_type else node_type,
        description=description,
        category=category,
        tier=tier,
        has_params=has_params,
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
