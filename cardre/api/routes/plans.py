"""Plan and plan-version endpoints.

Plans and plan-versions are distinct route concepts.
- ``/projects/{project_id}/plans`` and ``/plans/{plan_id}`` — plans
- ``/plans/{plan_id}/versions`` — list versions
- ``/projects/{project_id}/plan-versions/{plan_version_id}`` — GET, PATCH, POST commit
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.errors import CardreApiError, PLAN_NOT_FOUND, PLAN_VERSION_IMMUTABLE, PLAN_VERSION_NOT_FOUND
from cardre.api.schemas import (
    PlanCreateRequest,
    PlanListResponse,
    PlanResponse,
    PlanVersionListResponse,
    PlanVersionResponse,
    PlanVersionUpdate,
)
from cardre.services.plan_service import PlanService, PlanServiceError
from cardre.store.db import ProjectStore
from cardre.store.plan_repo import PlanRepository

router = APIRouter(prefix="/projects/{project_id}", tags=["plans"])


# ------------------------------------------------------------------
# Plans
# ------------------------------------------------------------------


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> PlanListResponse:
    """List all plans for a project."""
    service = PlanService(store)
    plans = service.list_plans(project_id)
    return PlanListResponse(
        plans=[
            PlanResponse(
                plan_id=p.plan_id,
                project_id=p.project_id,
                name=p.name,
                created_at=p.created_at,
            )
            for p in plans
        ]
    )


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(
    project_id: str,
    plan_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> PlanResponse:
    """Get a single plan by ID."""
    service = PlanService(store)
    plan = service.get_plan(plan_id)
    if plan is None:
        raise CardreApiError(
            code=PLAN_NOT_FOUND,
            message=f"Plan {plan_id!r} not found.",
            status_code=404,
        )
    return PlanResponse(
        plan_id=plan.plan_id,
        project_id=plan.project_id,
        name=plan.name,
        created_at=plan.created_at,
    )


@router.post("/plans", response_model=PlanResponse, status_code=201)
async def create_plan(
    project_id: str,
    body: PlanCreateRequest,
    store: ProjectStore = Depends(get_project_store),
) -> PlanResponse:
    """Create a new plan for a project."""
    repo = PlanRepository(store)
    plan_id = repo.create_plan(project_id=project_id, name=body.name)
    plan = repo.get_plan(plan_id)
    assert plan is not None
    return PlanResponse(
        plan_id=plan["plan_id"],
        project_id=plan["project_id"],
        name=plan["name"],
        created_at=plan["created_at"],
    )


# ------------------------------------------------------------------
# Plan versions (list under plan)
# ------------------------------------------------------------------


@router.get("/plans/{plan_id}/versions", response_model=PlanVersionListResponse)
async def list_plan_versions(
    project_id: str,
    plan_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> PlanVersionListResponse:
    """List all versions of a plan."""
    repo = PlanRepository(store)
    versions = repo.list_versions(plan_id)
    return PlanVersionListResponse(
        versions=[
            PlanVersionResponse(
                plan_version_id=v["plan_version_id"],
                plan_id=v["plan_id"],
                version_number=v["version_number"],
                is_committed=bool(v.get("is_committed", False)),
                created_at=v["created_at"],
                description=v.get("description", ""),
            )
            for v in versions
        ]
    )


# ------------------------------------------------------------------
# Plan versions (direct access under project)
# ------------------------------------------------------------------


@router.get("/plan-versions/{plan_version_id}", response_model=PlanVersionResponse)
async def get_plan_version(
    project_id: str,
    plan_version_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> PlanVersionResponse:
    """Get a single plan version by ID."""
    service = PlanService(store)
    pv = service.get_plan_version(plan_version_id)
    if pv is None:
        raise CardreApiError(
            code=PLAN_VERSION_NOT_FOUND,
            message=f"Plan version {plan_version_id!r} not found.",
            status_code=404,
        )
    return PlanVersionResponse(
        plan_version_id=pv.plan_version_id,
        plan_id=pv.plan_id,
        version_number=pv.version_number,
        is_committed=pv.is_committed,
        created_at=pv.created_at,
        description=pv.description,
    )


@router.patch("/plan-versions/{plan_version_id}", response_model=PlanVersionResponse)
async def update_plan_version(
    project_id: str,
    plan_version_id: str,
    body: PlanVersionUpdate,
    store: ProjectStore = Depends(get_project_store),
) -> PlanVersionResponse:
    """Update a draft plan version's metadata (description).

    Raises ``PLAN_VERSION_IMMUTABLE`` (409) if the version is already committed.
    """
    service = PlanService(store)
    pv = service.get_plan_version(plan_version_id)
    if pv is None:
        raise CardreApiError(
            code=PLAN_VERSION_NOT_FOUND,
            message=f"Plan version {plan_version_id!r} not found.",
            status_code=404,
        )
    if pv.is_committed:
        raise CardreApiError(
            code=PLAN_VERSION_IMMUTABLE,
            message=f"Plan version {plan_version_id!r} is already committed and cannot be modified.",
            status_code=409,
        )

    if body.description is not None:
        store.execute(
            "UPDATE plan_versions SET description = ? WHERE plan_version_id = ?",
            (body.description, plan_version_id),
        )

    updated = service.get_plan_version(plan_version_id)
    assert updated is not None
    return PlanVersionResponse(
        plan_version_id=updated.plan_version_id,
        plan_id=updated.plan_id,
        version_number=updated.version_number,
        is_committed=updated.is_committed,
        created_at=updated.created_at,
        description=updated.description,
    )


@router.post("/plan-versions/{plan_version_id}/commit", response_model=PlanVersionResponse)
async def commit_plan_version(
    project_id: str,
    plan_version_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> PlanVersionResponse:
    """Commit a draft plan version, making it read-only.

    Raises ``PLAN_VERSION_IMMUTABLE`` (409) if already committed.
    """
    service = PlanService(store)
    try:
        result = service.commit_plan_version(plan_version_id)
    except PlanServiceError as exc:
        raise CardreApiError(
            code=PLAN_VERSION_IMMUTABLE,
            message=str(exc),
            status_code=409,
        )

    return PlanVersionResponse(
        plan_version_id=result.plan_version_id,
        plan_id=result.plan_id,
        version_number=result.version_number,
        is_committed=result.is_committed,
        created_at=result.created_at,
        description=result.description,
    )
