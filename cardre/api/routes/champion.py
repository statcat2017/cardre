"""Champion endpoints — governance-gated."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store, require_governance
from cardre.api.schemas import ChampionAssignmentResponse, ChampionResponse
from cardre.store.db import ProjectStore
from cardre.store.branch_repo import BranchRepository

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
        assignment = repo.get_champion_assignment(plan_id)
    else:
        # Look for any champion assignment in this project
        rows = store.execute(
            "SELECT * FROM champion_assignments "
            "WHERE project_id = ? AND superseded_at IS NULL "
            "ORDER BY assigned_at DESC LIMIT 1",
            (project_id,),
        ).fetchall()
        assignment = dict(rows[0]) if rows else None

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
