"""Comparison endpoints — governance-gated."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store, require_governance
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
    # Since ComparisonRepository doesn't have list_for_project, query directly
    comparisons: list[dict[str, Any]] = []
    if plan_id:
        rows = store.execute(
            "SELECT * FROM branch_comparisons WHERE project_id = ? AND plan_id = ? ORDER BY created_at",
            (project_id, plan_id),
        ).fetchall()
    else:
        rows = store.execute(
            "SELECT * FROM branch_comparisons WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
    comparisons = [dict(r) for r in rows]

    return ComparisonListResponse(
        comparisons=[
            ComparisonResponse(
                comparison_id=c["comparison_id"],
                project_id=c["project_id"],
                plan_id=c["plan_id"],
                baseline_branch_id=c["baseline_branch_id"],
                created_at=c.get("created_at", ""),
                latest_ready=c.get("latest_ready"),
            )
            for c in comparisons
        ]
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
    return ComparisonResponse(
        comparison_id=comparison["comparison_id"],
        project_id=comparison["project_id"],
        plan_id=comparison["plan_id"],
        baseline_branch_id=comparison["baseline_branch_id"],
        created_at=comparison.get("created_at", ""),
        latest_ready=comparison.get("latest_ready"),
    )
