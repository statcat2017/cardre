"""Evidence endpoints — staleness explanation and evidence edges."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.mappers import staleness_explanation_to_response
from cardre.api.schemas import StalenessExplanationResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["evidence"])


@router.get("/steps/{step_id}/evidence", response_model=StalenessExplanationResponse)
async def get_step_evidence_staleness(
    project_id: str,
    step_id: str,
    plan_version_id: str,
    branch_id: str | None = None,
    container=Depends(get_container),
):
    from cardre.application.evidence.explain_staleness import (
        ExplainStaleness,
        ExplainStalenessCommand,
    )

    def factory():
        return container.uow_factory.for_project(project_id)

    uc = ExplainStaleness(factory)
    result = uc(ExplainStalenessCommand(
        plan_version_id=plan_version_id,
        step_id=step_id,
        branch_id=branch_id,
        plan_id=None,
    ))
    return staleness_explanation_to_response(result)
