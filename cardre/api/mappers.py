"""Pure mapping functions: domain objects → API response models.

Every function in this module is a pure data transformation with no
side effects, no I/O, and no dependencies on FastAPI or the store.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cardre._version import __version__
from cardre.api.schemas import (
    ArtifactResponse,
    BranchResponse,
    ChampionAssignmentResponse,
    ComparisonResponse,
    DiagnosticResponse,
    EvidenceArtifactResponse,
    EvidenceEdgeResponse,
    ManualBinningReviewResponse,
    NodeTypeResponse,
    PlanResponse,
    PlanStepResponse,
    PlanVersionResponse,
    ProjectResponse,
    RunEvidenceEdgeResponse,
    RunResponse,
    RunStepResponse,
    StalenessExplanationResponse,
)
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
from cardre.domain.manual_binning import ManualBinningReview
from cardre.domain.plan import Plan, PlanVersion
from cardre.domain.project import Project
from cardre.domain.run import Run, RunStep
from cardre.domain.step import StepSpec

_DIAGNOSTIC_FIELDS = {"code", "message", "severity", "source", "created_at"}


def diagnostic_to_response(value: Mapping[str, Any]) -> DiagnosticResponse:
    return DiagnosticResponse(
        code=str(value.get("code", "UNKNOWN")),
        message=str(value.get("message", "")),
        severity=str(value.get("severity", "error")),
        source=value.get("source"),
        created_at=value.get("created_at"),
        context={k: v for k, v in value.items() if k not in _DIAGNOSTIC_FIELDS},
    )


def run_to_response(run: Run) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        plan_version_id=run.plan_version_id,
        status=str(run.status),
        started_at=run.started_at,
        finished_at=run.finished_at,
        branch_id=run.branch_id,
    )


def run_step_to_response(rs: RunStep) -> RunStepResponse:
    return RunStepResponse(
        run_step_id=rs.run_step_id,
        run_id=rs.run_id,
        step_id=rs.step_id,
        plan_version_id=rs.plan_version_id,
        status=rs.status.value,
        started_at=rs.started_at,
        finished_at=rs.finished_at,
        execution_fingerprint=rs.execution_fingerprint,
        warnings=[diagnostic_to_response(w) for w in rs.warnings],
        errors=[diagnostic_to_response(e) for e in rs.errors],
    )


def plan_to_response(plan: Plan) -> PlanResponse:
    return PlanResponse(
        plan_id=plan.plan_id,
        project_id=plan.project_id,
        name=plan.name,
        created_at=plan.created_at,
    )


def plan_version_to_response(pv: PlanVersion) -> PlanVersionResponse:
    return PlanVersionResponse(
        plan_version_id=pv.plan_version_id,
        plan_id=pv.plan_id,
        version_number=pv.version_number,
        is_committed=pv.is_committed,
        created_at=pv.created_at,
        description=pv.description,
    )


def step_spec_to_response(step: StepSpec) -> PlanStepResponse:
    return PlanStepResponse(
        step_id=step.step_id,
        plan_version_id="",
        node_type=step.node_type,
        node_version=step.node_version,
        category=step.category,
        params=dict(step.params),
        params_hash=step.params_hash,
        parent_step_ids=list(step.parent_step_ids),
        branch_label=step.branch_label,
        position=step.position,
        canonical_step_id=step.canonical_step_id,
        branch_id=step.branch_id,
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
    project: Any,
    *,
    cardre_version: str | None = None,
) -> ProjectResponse:
    if isinstance(project, dict):
        return ProjectResponse(
            project_id=project["project_id"],
            name=project["name"],
            created_at=project["created_at"],
            cardre_version=project.get("cardre_version", cardre_version or __version__),
        )
    if isinstance(project, Project):
        return ProjectResponse(
            project_id=project.project_id,
            name=project.name,
            created_at=project.created_at,
            cardre_version=project.cardre_version,
        )
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        created_at=project.created_at,
        cardre_version=getattr(project, "cardre_version", __version__),
    )


def champion_assignment_to_response(assignment: Mapping[str, Any]) -> ChampionAssignmentResponse:
    return ChampionAssignmentResponse(
        champion_assignment_id=assignment["champion_assignment_id"],
        project_id=assignment["project_id"],
        plan_id=assignment["plan_id"],
        champion_branch_id=assignment["champion_branch_id"],
        selected_plan_version_id=assignment["selected_plan_version_id"],
        assigned_at=assignment.get("assigned_at", ""),
        superseded_at=assignment.get("superseded_at"),
    )


def artifact_to_response(artifact: ArtifactRef) -> ArtifactResponse:
    return ArtifactResponse(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        role=artifact.role,
        path=artifact.path,
        physical_hash=artifact.physical_hash,
        logical_hash=artifact.logical_hash,
        media_type=artifact.media_type,
        created_at=artifact.created_at,
    )


def manual_binning_review_to_response(review: ManualBinningReview) -> ManualBinningReviewResponse:
    return ManualBinningReviewResponse(
        review_id=review.review_id,
        plan_version_id=review.plan_version_id,
        step_id=review.step_id,
        status=review.status,
        reviewer_notes=review.reviewer_notes,
        affected_downstream_step_ids=list(review.affected_downstream_step_ids),
        created_at=review.created_at,
        updated_at=review.updated_at,
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
    return EvidenceArtifactResponse(
        evidence_artifact_id=art.evidence_artifact_id,
        evidence_edge_id=evidence_edge_id,
        artifact_id=art.artifact_id,
        role=art.role,
        created_at=art.created_at,
    )


def evidence_edge_to_brief_response(edge: EvidenceEdge) -> EvidenceEdgeResponse:
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


def staleness_explanation_to_response(explanation: Any) -> StalenessExplanationResponse:
    return StalenessExplanationResponse(
        step_id=explanation.step_id,
        status=explanation.status,
        upstream_changes=dict(explanation.upstream_changes),
        missing_evidence=list(explanation.missing_evidence),
    )


__all__ = [
    "artifact_to_response",
    "branch_to_response",
    "champion_assignment_to_response",
    "comparison_to_response",
    "diagnostic_to_response",
    "evidence_artifact_to_response",
    "evidence_edge_to_brief_response",
    "evidence_edge_to_response",
    "manual_binning_review_to_response",
    "node_type_to_response",
    "plan_to_response",
    "plan_version_to_response",
    "project_to_response",
    "run_step_to_response",
    "run_to_response",
    "staleness_explanation_to_response",
    "step_spec_to_response",
]
