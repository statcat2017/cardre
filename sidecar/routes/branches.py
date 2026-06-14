"""Branch endpoints — branch list, detail, creation, and baseline migration."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.services import migrate_project_to_branch_model
from cardre.services.branch_service import BranchService
from sidecar.models import (
    BranchListResponse,
    BranchListItem,
    BranchResponse,
    BranchStepItem,
    CreateBranchRequest,
    CreateBranchResponse,
    MigrateRequest,
    MigrateResponse,
)
from cardre.services.project_registry import load_registry

router = APIRouter(tags=["branches"])


def _get_store(project_path: str):
    from cardre.store import ProjectStore
    return ProjectStore(Path(project_path))


@router.get("/projects/{project_id}/branches", response_model=BranchListResponse)
def list_branches(
    project_id: str,
    plan_id: str | None = None,
    branch_type: str | None = None,
    status: str | None = None,
):
    registry = load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})

    store = _get_store(entry["path"])
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found in SQLite"})

    raw_branches = store.list_branches(project_id, plan_id=plan_id, branch_type=branch_type, status=status)
    items = []
    for b in raw_branches:
        items.append(BranchListItem(
            branch_id=b["branch_id"],
            plan_id=b["plan_id"],
            name=b["name"],
            branch_type=b["branch_type"],
            status=b.get("status", "active"),
            base_branch_id=b.get("base_branch_id"),
            base_plan_version_id=b["base_plan_version_id"],
            head_plan_version_id=b["head_plan_version_id"],
            branch_point_step_id=b.get("branch_point_step_id"),
            branch_point_canonical_step_id=b.get("branch_point_canonical_step_id"),
        ))

    return BranchListResponse(project_id=project_id, branches=items)


@router.get("/branches/{branch_id}", response_model=BranchResponse)
def get_branch(branch_id: str, project_id: str | None = None):
    if project_id is not None:
        registry = load_registry()
        entry = registry.get(project_id)
        if entry is None:
            raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})
        store = _get_store(entry["path"])
        branch = store.get_branch(branch_id)
        if branch is None:
            raise HTTPException(status_code=404, detail={"code": "BRANCH_NOT_FOUND", "message": f"No branch with ID {branch_id}"})
    else:
        registry = load_registry()
        branch = None
        store = None
        for pid, entry in registry.items():
            s = _get_store(entry["path"])
            b = s.get_branch(branch_id)
            if b is not None:
                branch = b
                store = s
                break
        if branch is None:
            raise HTTPException(status_code=404, detail={"code": "BRANCH_NOT_FOUND", "message": f"No branch with ID {branch_id}"})

    step_map = store.get_branch_step_map(branch_id, branch["head_plan_version_id"])
    steps = [
        BranchStepItem(
            step_id=row["step_id"],
            canonical_step_id=row["canonical_step_id"],
            branch_id=row.get("branch_id"),
            is_shared_upstream=bool(row["is_shared_upstream"]),
            is_branch_owned=bool(row["is_branch_owned"]),
        )
        for row in step_map
    ]
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
        steps=steps,
    )


@router.post("/plans/{plan_id}/branches", response_model=CreateBranchResponse, status_code=201)
def create_branch(plan_id: str, req: CreateBranchRequest):
    registry = load_registry()
    entry = registry.get(req.project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {req.project_id}"})

    store = _get_store(entry["path"])
    service = BranchService(store)
    result = service.create_branch(
        project_id=req.project_id,
        plan_id=plan_id,
        name=req.name,
        branch_type=req.branch_type,
        branch_point_step_id=req.branch_point_step_id,
        base_branch_id=req.base_branch_id,
        base_plan_version_id=req.base_plan_version_id,
        created_reason=req.created_reason,
        description=req.description,
        segment_filter_spec=req.segment_filter_spec,
    )
    return CreateBranchResponse(
        branch_id=result["branch_id"],
        plan_id=plan_id,
        new_plan_version_id=result["new_plan_version_id"],
        name=result["name"],
        branch_type=result["branch_type"],
        branch_point_step_id=result["branch_point_step_id"],
        branch_point_canonical_step_id=result["branch_point_canonical_step_id"],
        created_step_ids=result["created_step_ids"],
        shared_upstream_step_ids=result["shared_upstream_step_ids"],
        status=result["status"],
        warnings=result["warnings"],
    )


@router.post("/migrations/baseline", response_model=MigrateResponse)
def migrate_baseline(req: MigrateRequest):
    registry = load_registry()
    entry = registry.get(req.project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {req.project_id}"})

    store = _get_store(entry["path"])
    result = migrate_project_to_branch_model(store, req.project_id)

    return MigrateResponse(
        project_id=result["project_id"],
        branches_created=result["branches_created"],
        plan_versions_mapped=result["plan_versions_mapped"],
        steps_mapped=result["steps_mapped"],
    )
