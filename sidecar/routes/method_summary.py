"""Method summary and model ranking API endpoints.

Phase 6 adds:
- GET /branches/{branch_id}/method-summary — model family, metrics, limitations
- GET /branch-comparison-snapshots/{snapshot_id}/model-ranking — rank by metric
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from cardre.audit import json_logical_hash
from cardre.store import ProjectStore
from sidecar.models import MethodSummaryResponse, ModelRankingItem, ModelRankingResponse

router = APIRouter(tags=["method-summary"])

_PROJECT_STORE_CACHE: dict[str, ProjectStore] = {}


def _get_store(project_id: str) -> ProjectStore:
    if project_id not in _PROJECT_STORE_CACHE:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id!r}")
    return _PROJECT_STORE_CACHE[project_id]


def register_project_store(project_id: str, store: ProjectStore) -> None:
    """Register a project store for API access."""
    _PROJECT_STORE_CACHE[project_id] = store


@router.get("/branches/{branch_id}/method-summary", response_model=MethodSummaryResponse)
def get_branch_method_summary(branch_id: str) -> MethodSummaryResponse:
    """Get method summary for a branch: model family, metrics, limitations, evidence readiness."""
    from cardre.reporting.evidence_resolver import resolve_branch

    # Find the store from any registered project
    store = None
    for s in _PROJECT_STORE_CACHE.values():
        store = s
        break
    if store is None:
        raise HTTPException(status_code=404, detail="No project loaded")

    branch = resolve_branch(store, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail=f"Branch not found: {branch_id!r}")

    plan_version_id = branch.get("plan_version_id", "")
    branch_label = branch.get("label", "")

    # Find model artifact from latest run
    model_family = None
    feature_strategy = None
    feature_count = 0
    interpretability_level = None
    champion_eligibility = None
    limitations: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    # Query run-steps for this branch
    try:
        import sqlite3
        conn = sqlite3.connect(str(store.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT rs.artifact_ids, rs.node_type, rs.status "
            "FROM run_steps rs "
            "JOIN runs r ON rs.run_id = r.run_id "
            "WHERE r.branch_id = ? AND rs.status = 'success' "
            "ORDER BY rs.position DESC",
            (branch_id,),
        )
        for row in cursor.fetchall():
            artifact_ids = json.loads(row["artifact_ids"]) if row["artifact_ids"] else []
            for aid in artifact_ids:
                try:
                    art = store.get_artifact(aid)
                    if art is None:
                        continue
                    art_path = store.artifact_path(art)
                    if art.artifact_type == "model" and art.role == "model":
                        model_data = json.loads(art_path.read_text())
                        model_family = model_data.get("model_family")
                        feature_strategy = model_data.get("feature_strategy")
                        feature_count = len(model_data.get("features", []))
                        interpretability_level = model_data.get("interpretability", {}).get("explanation_level")
                        limitations = model_data.get("interpretability", {}).get("limitations", [])
                        warnings = [w.get("message", "") for w in model_data.get("warnings", [])]
                except Exception:
                    continue
        conn.close()
    except Exception:
        pass

    # Determine champion eligibility
    if interpretability_level:
        from cardre.nodes.explainability import CHAMPION_ELIGIBILITY
        champion_eligibility = CHAMPION_ELIGIBILITY.get(interpretability_level)

    return MethodSummaryResponse(
        branch_id=branch_id,
        model_family=model_family,
        feature_strategy=feature_strategy,
        feature_count=feature_count,
        interpretability_level=interpretability_level,
        champion_eligibility=champion_eligibility,
        limitations=limitations,
        warnings=warnings,
        metrics=metrics,
        evidence_readiness={},
    )


@router.get(
    "/branch-comparison-snapshots/{snapshot_id}/model-ranking",
    response_model=ModelRankingResponse,
)
def get_model_ranking(
    snapshot_id: str,
    metric: str = "auc",
) -> ModelRankingResponse:
    """Rank branches by a selected metric from a comparison snapshot."""
    store = None
    for s in _PROJECT_STORE_CACHE.values():
        store = s
        break
    if store is None:
        raise HTTPException(status_code=404, detail="No project loaded")

    # Read snapshot
    try:
        import sqlite3
        conn = sqlite3.connect(str(store.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM branch_comparison_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        conn.close()

        if row is None:
            raise HTTPException(status_code=404, detail=f"Snapshot not found: {snapshot_id!r}")

        artifact_id = row["artifact_id"]
        art = store.get_artifact(artifact_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Snapshot artifact not found")

        snapshot_data = json.loads(store.artifact_path(art).read_text())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    comparison_id = snapshot_data.get("comparison_id", snapshot_id)

    # Extract branch info from model.branch_level and validation.roles
    model_branches = snapshot_data.get("model", {}).get("branch_level", {})
    validation_by_role = snapshot_data.get("validation", {}).get("roles", {})

    rankings: list[ModelRankingItem] = []
    for branch_id, branch_model in model_branches.items():
        model_family = branch_model.get("model_family")
        feature_count = branch_model.get("feature_count", 0)
        branch_warnings = branch_model.get("warnings", [])

        # Get metric value from validation data across roles
        metric_value = None
        for role in ("test", "train", "oot"):
            role_validation = validation_by_role.get(role, {})
            branch_metrics = role_validation.get(branch_id, {})
            if isinstance(branch_metrics, dict) and metric in branch_metrics:
                val = branch_metrics[metric]
                if val is not None:
                    metric_value = val
                    break

        interpretability = None

        from cardre.nodes.explainability import CHAMPION_ELIGIBILITY
        champion_eligible = CHAMPION_ELIGIBILITY.get(interpretability or "", "not_champion_eligible") in (
            "fully_eligible", "eligible_with_rule_report", "eligible_with_limitation_evidence",
        )

        rankings.append(ModelRankingItem(
            branch_id=branch_id,
            branch_label=branch_id,
            model_family=model_family,
            metric_name=metric,
            metric_value=metric_value,
            interpretability_level=interpretability,
            champion_eligible=champion_eligible,
            limitations_summary=[],
        ))

    # Sort by metric value descending (higher is better for AUC/KS/F1/G-Mean)
    rankings.sort(key=lambda r: r.metric_value if r.metric_value is not None else -1.0, reverse=True)
    for i, r in enumerate(rankings):
        r.rank = i + 1

    return ModelRankingResponse(
        comparison_id=comparison_id,
        metric_name=metric,
        rankings=rankings,
        total_branches=len(rankings),
    )
