"""Evidence endpoints — staleness explanation keyed by step, not run."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.errors import CardreApiError, PLAN_VERSION_NOT_FOUND, STEP_NOT_FOUND
from cardre.api.routes._project_scope import plan_version_belongs_to_project
from cardre.api.schemas import EvidenceEdgeResponse, StalenessExplanationResponse
from cardre.services.staleness_service import StalenessService
from cardre.store.db import ProjectStore
from cardre.store.evidence_repo import EvidenceRepository
from cardre.store.step_repo import StepRepository

router = APIRouter(prefix="/projects/{project_id}", tags=["evidence"])


@router.get("/steps/{step_id}/evidence", response_model=StalenessExplanationResponse)
async def get_step_evidence_staleness(
    project_id: str,
    step_id: str,
    plan_version_id: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> StalenessExplanationResponse:
    """Get staleness explanation for a step.

    Requires ``plan_version_id`` query parameter.  Keyed by step, not run.
    """
    if plan_version_id is None:
        raise CardreApiError(
            code="MISSING_PARAMETER",
            message="plan_version_id query parameter is required.",
            status_code=400,
        )

    if not plan_version_belongs_to_project(store, project_id, plan_version_id):
        raise CardreApiError(
            code=PLAN_VERSION_NOT_FOUND,
            message=f"Plan version {plan_version_id!r} not found.",
            status_code=404,
        )
    step_repo = StepRepository(store)
    if not any(step.step_id == step_id for step in step_repo.get_steps(plan_version_id)):
        raise CardreApiError(
            code=STEP_NOT_FOUND,
            message=f"Step {step_id!r} not found in plan version {plan_version_id!r}.",
            status_code=404,
        )
    staleness_svc = StalenessService(store)
    explanation = staleness_svc.explain_step(plan_version_id, step_id)

    return StalenessExplanationResponse(
        step_id=explanation.step_id,
        status=explanation.status,
        upstream_changes=explanation.upstream_changes,
        missing_evidence=explanation.missing_evidence,
    )


@router.get("/steps/{step_id}/evidence/edges", response_model=list[EvidenceEdgeResponse])
async def get_step_evidence_edges(
    project_id: str,
    step_id: str,
    plan_version_id: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> list[EvidenceEdgeResponse]:
    """List evidence edges for a step across plan versions."""
    if plan_version_id is None:
        raise CardreApiError(
            code="MISSING_PARAMETER",
            message="plan_version_id query parameter is required.",
            status_code=400,
        )

    if not plan_version_belongs_to_project(store, project_id, plan_version_id):
        raise CardreApiError(
            code=PLAN_VERSION_NOT_FOUND,
            message=f"Plan version {plan_version_id!r} not found.",
            status_code=404,
        )
    step_repo = StepRepository(store)
    if not any(step.step_id == step_id for step in step_repo.get_steps(plan_version_id)):
        raise CardreApiError(
            code=STEP_NOT_FOUND,
            message=f"Step {step_id!r} not found in plan version {plan_version_id!r}.",
            status_code=404,
        )

    evidence_repo = EvidenceRepository(store)
    edges = evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)

    return [
        EvidenceEdgeResponse(
            evidence_edge_id=e.evidence_edge_id,
            run_id=e.run_id,
            run_step_id=e.run_step_id,
            plan_version_id=e.plan_version_id,
            step_id=e.step_id,
            parent_step_id=e.parent_step_id,
            source_run_id=e.source_run_id,
            source_run_step_id=e.source_run_step_id,
            policy=e.policy,
            source_label=e.source_label,
            is_reused=e.is_reused,
            is_stale=e.is_stale,
            stale_reason=e.stale_reason,
            created_at=e.created_at,
        )
        for e in edges
    ]
