"""Comparison endpoints — governance-gated."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store, require_governance
from cardre.api.routes._run_mappings import comparison_to_response
from cardre.api.schemas import ComparisonListResponse, ComparisonResponse
from cardre.store.comparison_repo import ComparisonRepository
from cardre.store.db import ProjectStore

router = APIRouter(prefix="/projects/{project_id}", tags=["comparisons"],
                   dependencies=[Depends(require_governance)])


@router.get("/comparisons", response_model=ComparisonListResponse)
async def list_comparisons(
    project_id: str,
    plan_id: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> ComparisonListResponse:
    """List all comparisons for a project."""
    repo = ComparisonRepository(store)
    comparisons = repo.list_for_project(project_id, plan_id=plan_id)

    return ComparisonListResponse(
        comparisons=[comparison_to_response(c) for c in comparisons]
    )


@router.get("/comparisons/{comparison_id}", response_model=ComparisonResponse)
async def get_comparison(
    project_id: str,
    comparison_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ComparisonResponse:
    """Get a single comparison by ID."""
    repo = ComparisonRepository(store)
    comparison = repo.get_comparison(comparison_id)
    if comparison is None:
        from cardre.api.errors import COMPARISON_NOT_FOUND, CardreApiError
        raise CardreApiError(
            code=COMPARISON_NOT_FOUND,
            message=f"Comparison {comparison_id!r} not found.",
            status_code=404,
        )
    if comparison.get("project_id") != project_id:
        from cardre.api.errors import COMPARISON_NOT_FOUND, CardreApiError
        raise CardreApiError(
            code=COMPARISON_NOT_FOUND,
            message=f"Comparison {comparison_id!r} not found.",
            status_code=404,
        )
    return comparison_to_response(comparison)
