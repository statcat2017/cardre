"""Evidence endpoints — staleness explanation and evidence edges."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.mappers import staleness_explanation_to_response
from cardre.api.schemas import StalenessExplanationResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["evidence"])


@router.get("/steps/{step_id}/evidence", response_model=StalenessExplanationResponse)
def get_step_evidence_staleness(
    project_id: str,
    step_id: str,
    plan_version_id: str,
    container=Depends(get_container),
):
    from cardre.application.evidence.explain_staleness import (
        ExplainStaleness,
        ExplainStalenessCommand,
    )

    def factory():
        return container.uow_factory.read_only(project_id)

    uc = ExplainStaleness(factory)
    result = uc(ExplainStalenessCommand(
        plan_version_id=plan_version_id,
        step_id=step_id,
        plan_id=None,
    ))
    return staleness_explanation_to_response(result)
