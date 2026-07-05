"""Champion endpoints — governance-gated."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store, require_governance
from cardre.api.routes._project_scope import plan_belongs_to_project
from cardre.api.schemas import ChampionAssignmentResponse, ChampionResponse
from cardre.store.branch_repo import BranchRepository
from cardre.store.db import ProjectStore

router = APIRouter(prefix="/projects/{project_id}", tags=["champion"],
                   dependencies=[Depends(require_governance)])


@router.get("/champion", response_model=ChampionResponse)
async def get_champion(
    project_id: str,
    plan_id: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> ChampionResponse:
    """Get the current champion assignment for a project or plan."""
    repo = BranchRepository(store)
    if plan_id:
        if not plan_belongs_to_project(store, project_id, plan_id):
            from cardre.api.errors import PLAN_NOT_FOUND, CardreApiError
            raise CardreApiError(
                code=PLAN_NOT_FOUND,
                message=f"Plan {plan_id!r} not found in project {project_id!r}.",
                status_code=404,
            )
        assignment = repo.get_champion_assignment(plan_id)
    else:
        assignment = repo.get_champion_assignment_for_project(project_id)

    if assignment is None:
        return ChampionResponse(assignment=None)

    return ChampionResponse(
        assignment=ChampionAssignmentResponse(
            champion_assignment_id=assignment["champion_assignment_id"],
            project_id=assignment["project_id"],
            plan_id=assignment["plan_id"],
            champion_branch_id=assignment["champion_branch_id"],
            selected_plan_version_id=assignment["selected_plan_version_id"],
            assigned_at=assignment.get("assigned_at", ""),
            superseded_at=assignment.get("superseded_at"),
        )
    )
