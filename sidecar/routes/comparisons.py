"""Comparison endpoints — intent, refresh, and snapshot read."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cardre.services.comparison_service import create_comparison, refresh_comparison
from sidecar.models import (
    ComparisonResponse,
    ComparisonSnapshotResponse,
    CreateComparisonRequest,
    RefreshComparisonResponse,
    MissingStaleEvidence,
)
from sidecar.routes.projects import _load_registry, _get_store_for_project

router = APIRouter(tags=["comparisons"])


@router.post("/branch-comparisons", response_model=ComparisonResponse, status_code=201)
def create_branch_comparison(req: CreateComparisonRequest):
    store = _get_store_for_project(req.project_id)
    try:
        result = create_comparison(
            store=store,
            project_id=req.project_id,
            plan_id=req.plan_id,
            baseline_branch_id=req.baseline_branch_id,
            challenger_branch_ids=req.challenger_branch_ids,
            comparison_spec=dict(req.comparison_spec),
            created_reason=req.created_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "COMPARISON_FAILED", "message": str(exc)})

    return ComparisonResponse(
        comparison_id=result["comparison_id"],
        project_id=result["project_id"],
        plan_id=result["plan_id"],
        baseline_branch_id=result["baseline_branch_id"],
        challenger_branch_ids=result["challenger_branch_ids"],
        latest_snapshot_id=result.get("latest_snapshot_id"),
        latest_ready=result.get("latest_ready"),
        blocked_reason=result.get("blocked_reason"),
        missing_or_stale=[MissingStaleEvidence(**m) for m in result.get("missing_or_stale", [])],
        warnings=result.get("warnings", []),
    )


@router.get("/branch-comparisons/{comparison_id}", response_model=ComparisonResponse)
def get_branch_comparison(comparison_id: str):
    registry = _load_registry()
    for pid, entry in registry.items():
        store = _get_store_for_project(pid)
        row = store._connect().execute(
            "SELECT * FROM branch_comparisons WHERE comparison_id = ?",
            (comparison_id,),
        ).fetchone()
        if row is not None:
            import json
            comp = dict(row)
            return ComparisonResponse(
                comparison_id=comp["comparison_id"],
                project_id=comp["project_id"],
                plan_id=comp["plan_id"],
                baseline_branch_id=comp["baseline_branch_id"],
                challenger_branch_ids=json.loads(comp["challenger_branch_ids_json"]),
                latest_snapshot_id=comp.get("latest_snapshot_id"),
                latest_ready=bool(comp["latest_ready"]) if comp.get("latest_ready") else None,
            )
    raise HTTPException(status_code=404, detail={"code": "COMPARISON_NOT_FOUND", "message": f"No comparison with ID {comparison_id}"})


@router.post("/branch-comparisons/{comparison_id}/refresh", response_model=RefreshComparisonResponse)
def refresh_branch_comparison(comparison_id: str):
    registry = _load_registry()
    for pid, entry in registry.items():
        store = _get_store_for_project(pid)
        row = store._connect().execute(
            "SELECT project_id FROM branch_comparisons WHERE comparison_id = ?",
            (comparison_id,),
        ).fetchone()
        if row is not None:
            try:
                result = refresh_comparison(store, comparison_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"code": "REFRESH_FAILED", "message": str(exc)})

            return RefreshComparisonResponse(
                comparison_id=result["comparison_id"],
                comparison_snapshot_id=result.get("comparison_snapshot_id"),
                ready=result.get("ready", False),
                comparison_artifact_id=result.get("comparison_artifact_id"),
                refreshed_at=result.get("refreshed_at", ""),
                blocked_reason=result.get("blocked_reason"),
                missing_or_stale=[MissingStaleEvidence(**m) for m in result.get("missing_or_stale", [])],
                warnings=result.get("warnings", []),
            )
    raise HTTPException(status_code=404, detail={"code": "COMPARISON_NOT_FOUND", "message": f"No comparison with ID {comparison_id}"})


@router.get("/branch-comparison-snapshots/{snapshot_id}", response_model=ComparisonSnapshotResponse)
def get_comparison_snapshot(snapshot_id: str):
    registry = _load_registry()
    for pid, entry in registry.items():
        store = _get_store_for_project(pid)
        row = store._connect().execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is not None:
            import json
            snap = dict(row)
            readiness = json.loads(snap.get("readiness_json", "{}"))
            return ComparisonSnapshotResponse(
                comparison_snapshot_id=snap["comparison_snapshot_id"],
                comparison_id=snap["comparison_id"],
                comparison_artifact_id=snap["comparison_artifact_id"],
                ready=readiness.get("ready", False),
                created_at=snap["created_at"],
            )
    raise HTTPException(status_code=404, detail={"code": "SNAPSHOT_NOT_FOUND", "message": f"No snapshot with ID {snapshot_id}"})
