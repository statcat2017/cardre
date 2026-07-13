"""Branch endpoints — governance-gated."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store, require_governance
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.api.routes._project_scope import (
    branch_belongs_to_project,
    plan_belongs_to_project,
    plan_version_belongs_to_project,
)
from cardre.api.routes._run_mappings import branch_to_response
from cardre.api.schemas import BranchCreateRequest, BranchListResponse, BranchResponse
from cardre.store.branch_repo import BranchRepository
from cardre.store.db import ProjectStore

router = APIRouter(prefix="/projects/{project_id}", tags=["branches"],
                   dependencies=[Depends(require_governance)])


@router.get("/branches", response_model=BranchListResponse)
async def list_branches(
    project_id: str,
    plan_id: str | None = None,
    branch_type: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> BranchListResponse:
    """List all branches for a project, optionally filtered."""
    repo = BranchRepository(store)
    branches = repo.list(
        project_id=project_id,
        plan_id=plan_id,
        branch_type=branch_type,
    )
    return BranchListResponse(
        branches=[branch_to_response(b) for b in branches]
    )


@router.get("/branches/{branch_id}", response_model=BranchResponse)
async def get_branch(
    project_id: str,
    branch_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> BranchResponse:
    """Get a single branch by ID."""
    if not branch_belongs_to_project(store, project_id, branch_id):
        raise CardreApiError(
            code=ErrorCode.BRANCH_NOT_FOUND,
            message=f"Branch {branch_id!r} not found.",
            status_code=404,
        )
    repo = BranchRepository(store)
    branch = repo.get_branch(branch_id)
    if branch is None:
        raise CardreApiError(
            code=ErrorCode.BRANCH_NOT_FOUND,
            message=f"Branch {branch_id!r} not found.",
            status_code=404,
        )
    return branch_to_response(branch)


@router.post("/branches", response_model=BranchResponse, status_code=201)
async def create_branch(
    project_id: str,
    body: BranchCreateRequest,
    store: ProjectStore = Depends(get_project_store),
) -> BranchResponse:
    """Create a new branch for challenger analysis."""
    if not plan_belongs_to_project(store, project_id, body.plan_id):
        raise CardreApiError(
            code=ErrorCode.PLAN_NOT_FOUND,
            message=f"Plan {body.plan_id!r} not found.",
            status_code=404,
        )
    if not plan_version_belongs_to_project(store, project_id, body.base_plan_version_id):
        raise CardreApiError(
            code=ErrorCode.PLAN_VERSION_NOT_FOUND,
            message=f"Plan version {body.base_plan_version_id!r} not found.",
            status_code=404,
        )
    if not plan_version_belongs_to_project(store, project_id, body.head_plan_version_id):
        raise CardreApiError(
            code=ErrorCode.PLAN_VERSION_NOT_FOUND,
            message=f"Plan version {body.head_plan_version_id!r} not found.",
            status_code=404,
        )
    repo = BranchRepository(store)
    branch_id = repo.create_branch(
        project_id=project_id,
        plan_id=body.plan_id,
        name=body.name,
        branch_type=body.branch_type,
        base_plan_version_id=body.base_plan_version_id,
        head_plan_version_id=body.head_plan_version_id,
        created_reason=body.created_reason,
        description=body.description,
        base_branch_id=body.base_branch_id,
        branch_point_step_id=body.branch_point_step_id,
    )
    branch = repo.get_branch(branch_id)
    assert branch is not None
    return branch_to_response(branch)
