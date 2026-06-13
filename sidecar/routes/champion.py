"""Champion endpoints — assign and query champion branches."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cardre.services.champion_service import assign_champion, get_champion as _get_champion
from sidecar.models import AssignChampionRequest, ChampionResponse
from sidecar.routes.projects import _load_registry, _get_store_for_project

router = APIRouter(tags=["champion"])


@router.post("/plans/{plan_id}/champion", response_model=ChampionResponse, status_code=201)
def assign_plan_champion(plan_id: str, req: AssignChampionRequest):
    store = _get_store_for_project(req.project_id)
    try:
        result = assign_champion(
            store=store,
            project_id=req.project_id,
            plan_id=plan_id,
            branch_id=req.branch_id,
            comparison_id=req.comparison_id,
            comparison_snapshot_id=req.comparison_snapshot_id,
            scope_type=req.scope_type,
            scope_key=req.scope_key,
            assigned_reason=req.assigned_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "CHAMPION_FAILED", "message": str(exc)})

    return ChampionResponse(
        champion_assignment_id=result["champion_assignment_id"],
        plan_id=result["plan_id"],
        champion_branch_id=result["champion_branch_id"],
        previous_champion_branch_id=result.get("previous_champion_branch_id"),
        scope_type=result["scope_type"],
        scope_key=result["scope_key"],
        assigned_at=result["assigned_at"],
        assigned_reason=result["assigned_reason"],
    )


@router.get("/plans/{plan_id}/champion", response_model=ChampionResponse)
def get_plan_champion(plan_id: str, project_id: str, scope_type: str = "project", scope_key: str = "default"):
    store = _get_store_for_project(project_id)
    result = _get_champion(store, plan_id, scope_type=scope_type, scope_key=scope_key)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "NO_CHAMPION", "message": f"No active champion for plan {plan_id}"})

    return ChampionResponse(
        champion_assignment_id=result["champion_assignment_id"],
        plan_id=result["plan_id"],
        champion_branch_id=result["champion_branch_id"],
        scope_type=result["scope_type"],
        scope_key=result["scope_key"],
        assigned_at=result["assigned_at"],
        assigned_reason=result["assigned_reason"],
    )
