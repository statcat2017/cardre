"""Plan endpoints — step status and staleness."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from sidecar.models import PlanResponse, StepStatusItem
from sidecar.routes.projects import _load_registry

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: str, project_id: str | None = None):
    registry = _load_registry()
    if project_id is None:
        for pid, entry in registry.items():
            store = _get_store(entry["path"])
            plan = store.get_plan(plan_id)
            if plan is not None:
                project_id = pid
                break
    if project_id is None or project_id not in registry:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": f"No plan with ID {plan_id}"})

    entry = registry[project_id]
    store = _get_store(entry["path"])
    plan = store.get_plan(plan_id)
    latest_pv_id = store.get_latest_plan_version_id(plan_id)
    if latest_pv_id is None:
        raise HTTPException(status_code=404, detail={"code": "NO_VERSION", "message": "Plan has no versions"})

    steps = store.get_plan_version_steps(latest_pv_id)

    executor = PlanExecutor(NodeRegistry.with_defaults())
    staleness = executor.compute_staleness(store, latest_pv_id)

    run_steps_map = {}
    run_id = store.get_latest_successful_run_id(latest_pv_id)
    if run_id is not None:
        for rs in store.get_run_steps(run_id):
            run_steps_map[rs.step_id] = rs

    step_items = []
    for s in steps:
        rs = run_steps_map.get(s.step_id)
        step_items.append(StepStatusItem(
            step_id=s.step_id,
            node_type=s.node_type,
            category=s.category,
            status=rs.status if rs else "not_run",
            is_stale=staleness.get(s.step_id, True),
            position=s.position,
        ))

    return PlanResponse(
        plan_id=plan_id,
        project_id=project_id,
        name=plan["name"],
        latest_version_id=latest_pv_id,
        steps=step_items,
    )


def _get_store(project_path: str):
    from cardre.store import ProjectStore
    return ProjectStore(Path(project_path))
