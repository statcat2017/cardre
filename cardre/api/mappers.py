"""Pure mapping functions: domain objects → API response models.

Every function in this module is a pure data transformation with no
side effects, no I/O, and no dependencies on FastAPI or the store.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from cardre._version import __version__
from cardre.api.schemas import (
    ArtifactResponse,
    DiagnosticResponse,
    EvidenceArtifactResponse,
    EvidenceEdgeResponse,
    ExportResponse,
    ManualBinningReviewResponse,
    MethodOptionResponse,
    NodeParameterSchemaResponse,
    NodeTypeResponse,
    ParameterConstraintResponse,
    ParameterDefinitionResponse,
    PlanResponse,
    PlanStepResponse,
    PlanVersionResponse,
    ProjectResponse,
    ReportResponse,
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


# ---------------------------------------------------------------------------
# Structural types for node parameter schema objects.
#
# These mirror the dataclass-shaped objects produced by ``cardre.nodes`` but
# are defined locally so the API layer never imports ``cardre.nodes``.  The
# mapper only needs attribute access; ``Any`` is used for JSON values.
# ---------------------------------------------------------------------------


class _ConstraintLike(Protocol):
    enum_values: list[Any] | None
    min_value: float | None
    max_value: float | None
    exclusive_min: float | None
    exclusive_max: float | None
    min_items: int | None
    max_items: int | None
    pattern: str | None


class _ParameterDefinitionLike(Protocol):
    name: str
    label: str
    kind: str
    default: Any
    required: bool
    help_text: str
    constraint: _ConstraintLike | None


class _MethodOptionLike(Protocol):
    id: str
    label: str
    status: str
    description: str
    params: list[_ParameterDefinitionLike]


class _NodeParameterSchemaLike(Protocol):
    node_type: str
    node_version: str
    title: str
    default_method: str
    methods: list[_MethodOptionLike]


def diagnostic_to_response(value: Mapping[str, Any]) -> DiagnosticResponse:
    return DiagnosticResponse(
        code=str(value.get("code", "UNKNOWN")),
        message=str(value.get("message", "")),
        severity=str(value.get("severity", "error")),
        source=value.get("source"),
        created_at=value.get("created_at"),
        context={k: v for k, v in value.items() if k not in _DIAGNOSTIC_FIELDS},
    )


def run_to_response(
    run: Run,
    *,
    step_count: int = 0,
    executed_step_ids: list[str] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    stale_heartbeat_seconds: int,
) -> RunResponse:
    diag_responses = [diagnostic_to_response(d) for d in (diagnostics or [])]
    latest_error = next(
        (d for d in reversed(diag_responses) if d.severity == "error"),
        None,
    )
    return RunResponse(
        run_id=run.run_id,
        plan_version_id=run.plan_version_id,
        status=str(run.status),
        run_scope=run.run_scope,
        force=run.force,
        started_at=run.started_at,
        finished_at=run.finished_at,
        step_count=step_count,
        executed_step_ids=list(executed_step_ids or []),
        diagnostics=diag_responses,
        latest_error=latest_error,
        heartbeat_at=run.heartbeat_at,
        is_stale=run.is_stale(stale_heartbeat_seconds=stale_heartbeat_seconds),
        cancel_requested=run.cancel_requested,
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


def step_spec_to_response(step: StepSpec, *, plan_version_id: str = "") -> PlanStepResponse:
    return PlanStepResponse(
        step_id=step.step_id,
        plan_version_id=plan_version_id,
        node_type=step.node_type,
        node_version=step.node_version,
        category=step.category,
        params=dict(step.params),
        params_hash=step.params_hash,
        parent_step_ids=list(step.parent_step_ids),
        position=step.position,
        canonical_step_id=step.canonical_step_id,
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


def node_parameter_schema_to_response(
    schema: _NodeParameterSchemaLike,
) -> NodeParameterSchemaResponse:
    """Serialize a node parameter schema into its API DTO."""
    return NodeParameterSchemaResponse(
        node_type=schema.node_type,
        node_version=schema.node_version,
        title=schema.title,
        default_method=schema.default_method,
        methods=[_method_option_to_response(m) for m in schema.methods],
    )


def _method_option_to_response(method: _MethodOptionLike) -> MethodOptionResponse:
    return MethodOptionResponse(
        id=method.id,
        label=method.label,
        status=method.status,
        description=method.description,
        params=[_parameter_definition_to_response(p) for p in method.params],
    )


def _parameter_definition_to_response(
    param: _ParameterDefinitionLike,
) -> ParameterDefinitionResponse:
    return ParameterDefinitionResponse(
        name=param.name,
        label=param.label,
        kind=param.kind,
        default=param.default,
        required=param.required,
        help_text=param.help_text,
        constraint=_parameter_constraint_to_response(param.constraint),
    )


def _parameter_constraint_to_response(
    constraint: _ConstraintLike | None,
) -> ParameterConstraintResponse | None:
    if constraint is None:
        return None
    return ParameterConstraintResponse(
        enum_values=list(constraint.enum_values) if constraint.enum_values is not None else None,
        min_value=constraint.min_value,
        max_value=constraint.max_value,
        exclusive_min=constraint.exclusive_min,
        exclusive_max=constraint.exclusive_max,
        min_items=constraint.min_items,
        max_items=constraint.max_items,
        pattern=constraint.pattern,
    )


def node_type_to_response(
    node_type: str,
    *,
    category: str = "",
    description: str = "",
    has_params: bool = True,
    parameter_schema: NodeParameterSchemaResponse | None = None,
) -> NodeTypeResponse:
    return NodeTypeResponse(
        node_type=node_type,
        display_name=node_type.split(".")[-1] if "." in node_type else node_type,
        description=description,
        category=category,
        has_params=has_params,
        parameter_schema=parameter_schema,
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


def report_to_response(item: Any) -> ReportResponse:
    return ReportResponse(
        report_id=item.report_id,
        run_id=item.run_id,
        report_type=item.report_type,
        path=item.path,
        created_at=item.created_at,
    )


def export_to_response(item: Any) -> ExportResponse:
    return ExportResponse(
        export_id=item.export_id,
        run_id=item.run_id,
        export_type=item.export_type,
        path=item.path,
        created_at=item.created_at,
        size_bytes=getattr(item, "size_bytes", 0),
    )


__all__ = [
    "artifact_to_response",
    "diagnostic_to_response",
    "evidence_artifact_to_response",
    "evidence_edge_to_brief_response",
    "evidence_edge_to_response",
    "manual_binning_review_to_response",
    "node_parameter_schema_to_response",
    "node_type_to_response",
    "plan_to_response",
    "plan_version_to_response",
    "project_to_response",
    "run_step_to_response",
    "run_to_response",
    "staleness_explanation_to_response",
    "step_spec_to_response",
]
