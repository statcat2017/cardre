"""Comparison service — intent, readiness, and immutable comparison snapshots.

Port from v1.  Uses relational ``comparison_challenger_branches`` and
``comparison_snapshot_plan_versions`` tables (not JSON arrays).
"""

from __future__ import annotations

import json
from typing import Any

from cardre.artifacts import write_json_artifact
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError
from cardre.reporting.evidence_contract import (
    REQUIRED_STEPS_COMPARISON,
)
from cardre.services.comparison.resolver import (
    _materialize_evidence,  # noqa: F401 — re-exported for tests
)
from cardre.services.comparison.validation import (
    _validation_roles,  # noqa: F401 — re-exported for tests
)
from cardre.services.staleness_service import StalenessService
from cardre.store.branch_repo import BranchRepository
from cardre.store.comparison_repo import ComparisonRepository
from cardre.store.db import ProjectStore


def _check_branch_readiness(
    store: ProjectStore,
    branch_id: str,
    plan_version_id: str,
    required_steps: list[str],
    is_baseline: bool = False,
) -> list[dict[str, str]]:
    """Check if a branch has current successful evidence for required canonical steps.

    Uses ``EvidenceLocator`` (ADR-0005 §3) for branch-scoped evidence lookup
    with the canonical branch→full→plan fallback. For baseline branches,
    ``branch_id=None`` is used directly since baseline runs pre-date the
    branch model.

    Handles legacy canonical step aliases (e.g., logistic-regression -> model-fit).

    Returns a list of missing-or-stale entries; empty list = ready.
    """
    from cardre.evidence_locator import EvidenceLocator

    branches_repo = BranchRepository(store)
    step_map = branches_repo.get_step_map(branch_id, plan_version_id)
    canon_to_actual: dict[str, str] = {}
    for row in step_map:
        canon_to_actual[row["canonical_step_id"]] = row["step_id"]

    staleness_svc = StalenessService(store)
    locator = EvidenceLocator(store)

    missing: list[dict[str, str]] = []
    for cs in required_steps:
        actual_id = canon_to_actual.get(cs, cs)
        evidence_branch = branch_id if not is_baseline else None
        # Single Locator call — the Locator owns the branch→full→plan
        # fallback (ADR-0005 §3).  No caller-side retry.
        resolved = locator.resolve(
            plan_version_id, actual_id, branch_id=evidence_branch,
        )
        if resolved is None:
            # Use staleness service to determine if stale or not_run
            explanation = staleness_svc.explain_step(
                plan_version_id, actual_id, branch_id=evidence_branch,
            )
            status = "stale" if explanation.status == "stale" else "not_run"
            missing.append({
                "branch_id": branch_id,
                "canonical_step_id": cs,
                "step_id": actual_id,
                "status": status,
            })
    return missing


def _build_comparison_content(
    store: ProjectStore,
    plan_version_id_baseline: str,
    plan_version_id_challenger: str,
    branch_id_baseline: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Build comparison JSON content from branch evidence.

    Reads WOE/IV, model, validation, and cutoff artifacts.
    No modelling execution. No run records created.
    """
    from cardre.services.comparison.cutoff import build_cutoff_comparison
    from cardre.services.comparison.model import build_model_comparison
    from cardre.services.comparison.validation import build_validation_comparison
    from cardre.services.comparison.woe_iv import build_woe_iv_comparison

    return {
        "comparison_type": "challenger_vs_baseline",
        "baseline_branch_id": branch_id_baseline,
        "challenger_branch_id": branch_id_challenger,
        "woe_iv": build_woe_iv_comparison(
            store, plan_version_id_baseline, plan_version_id_challenger,
            branch_id_baseline, branch_id_challenger, spec,
        ),
        "model": build_model_comparison(
            store, plan_version_id_baseline, plan_version_id_challenger,
            branch_id_baseline, branch_id_challenger, spec,
        ),
        "validation": build_validation_comparison(
            store, plan_version_id_baseline, plan_version_id_challenger,
            branch_id_baseline, branch_id_challenger, spec,
        ),
        "cutoff": build_cutoff_comparison(
            store, plan_version_id_baseline, plan_version_id_challenger,
            branch_id_baseline, branch_id_challenger, spec,
        ),
        "warnings": [],
    }


def create_comparison(
    store: ProjectStore,
    project_id: str,
    plan_id: str,
    baseline_branch_id: str,
    challenger_branch_ids: list[str],
    comparison_spec: dict[str, Any] | None = None,
    created_reason: str | None = None,
) -> dict[str, Any]:
    """Create comparison intent. Does NOT execute any modelling nodes.

    Uses relational ``comparison_challenger_branches`` table (not JSON array).
    """
    branches_repo = BranchRepository(store)
    comparison_repo = ComparisonRepository(store)

    baseline = branches_repo.get_branch(baseline_branch_id)
    if baseline is None:
        raise CardreError(
            f"BASELINE_BRANCH_NOT_FOUND: {baseline_branch_id}",
            code="BASELINE_BRANCH_NOT_FOUND",
            context={"branch_id": baseline_branch_id},
            status_code=404,
        )

    for cid in challenger_branch_ids:
        if branches_repo.get_branch(cid) is None:
            raise CardreError(
                f"CHALLENGER_BRANCH_NOT_FOUND: {cid}",
                code="CHALLENGER_BRANCH_NOT_FOUND",
                context={"branch_id": cid},
                status_code=404,
            )

    spec = comparison_spec or {
        "roles": ["train", "test", "oot"],
        "include_woe_iv": True,
        "include_model": True,
        "include_validation": True,
        "include_cutoff": True,
        "include_warnings": True,
    }

    comparison_id = comparison_repo.create_comparison(
        project_id=project_id,
        plan_id=plan_id,
        baseline_branch_id=baseline_branch_id,
        comparison_spec=spec,
        created_reason=created_reason,
    )

    # Insert challenger branches relationally
    for idx, cid in enumerate(challenger_branch_ids):
        comparison_repo.add_challenger_branch(comparison_id, cid, position=idx)

    now = utc_now_iso()
    return {
        "comparison_id": comparison_id,
        "project_id": project_id,
        "plan_id": plan_id,
        "baseline_branch_id": baseline_branch_id,
        "challenger_branch_ids": challenger_branch_ids,
        "latest_snapshot_id": None,
        "latest_ready": None,
        "blocked_reason": None,
        "missing_or_stale": [],
        "warnings": [],
        "created_at": now,
    }


def refresh_comparison(
    store: ProjectStore,
    comparison_id: str,
) -> dict[str, Any]:
    """Refresh a comparison intent — check readiness and create snapshot if ready.

    Checks both baseline and all challenger branches.
    Does NOT execute modelling nodes. Does NOT create run records.
    """
    branches_repo = BranchRepository(store)
    comparison_repo = ComparisonRepository(store)

    comparison = comparison_repo.get_comparison(comparison_id)
    if comparison is None:
        raise CardreError(
            f"COMPARISON_NOT_FOUND: {comparison_id}",
            code="COMPARISON_NOT_FOUND",
            context={"comparison_id": comparison_id},
            status_code=404,
        )

    baseline_branch_id = comparison["baseline_branch_id"]

    # Read challenger branches from relational table, not JSON array
    challenger_rows = comparison_repo.get_challenger_branches(comparison_id)
    challenger_ids = [r["branch_id"] for r in challenger_rows]

    spec = json.loads(comparison["comparison_spec_json"])

    baseline = branches_repo.get_branch(baseline_branch_id)
    if baseline is None:
        raise CardreError(
            f"BASELINE_BRANCH_NOT_FOUND: {baseline_branch_id}",
            code="BASELINE_BRANCH_NOT_FOUND",
            context={"branch_id": baseline_branch_id},
            status_code=404,
        )

    required = REQUIRED_STEPS_COMPARISON

    # Check baseline readiness (uses full-plan evidence, not branch-scoped)
    all_missing: list[dict[str, str]] = _check_branch_readiness(
        store, baseline_branch_id, baseline["head_plan_version_id"], required,
        is_baseline=True,
    )

    # Check each challenger
    for cid in challenger_ids:
        challenger = branches_repo.get_branch(cid)
        if challenger is None:
            all_missing.append({"branch_id": cid, "canonical_step_id": "", "step_id": "", "status": "not_found"})
            continue
        missing = _check_branch_readiness(
            store, cid, challenger["head_plan_version_id"], required,
        )
        all_missing.extend(missing)

    if all_missing:
        return {
            "comparison_id": comparison_id,
            "comparison_snapshot_id": None,
            "ready": False,
            "comparison_artifact_id": None,
            "refreshed_at": utc_now_iso(),
            "blocked_reason": "One or more branches have missing or stale evidence.",
            "missing_or_stale": all_missing,
            "warnings": [],
        }

    # Build comparison snapshots — one per challenger
    now = utc_now_iso()
    last_snapshot_id = None
    artifact = None

    with store.transaction("IMMEDIATE") as conn:
        for cid in challenger_ids:
            challenger = branches_repo.get_branch(cid)
            if challenger is None:
                continue

            content = _build_comparison_content(
                store,
                baseline["head_plan_version_id"],
                challenger["head_plan_version_id"],
                baseline_branch_id,
                cid,
                spec,
            )
            artifact = write_json_artifact(
                store,
                artifact_type="branch_comparison",
                role="comparison",
                stem=f"comparison_{comparison_id}_{cid}",
                payload=content,
                metadata={"comparison_id": comparison_id, "challenger_branch_id": cid},
            )

            # Create snapshot using repository (relational plan versions)
            snapshot_id = comparison_repo.create_snapshot(
                comparison_id=comparison_id,
                project_id=comparison["project_id"],
                plan_id=comparison["plan_id"],
                comparison_artifact_id=artifact.artifact_id,
                readiness={"ready": True, "missing": []},
                created_reason="Comparison refresh",
                conn=conn,
            )

            # Add source plan versions relationally
            comparison_repo.add_snapshot_plan_version(
                snapshot_id,
                baseline["head_plan_version_id"],
                branch_id=baseline_branch_id,
                conn=conn,
            )
            comparison_repo.add_snapshot_plan_version(
                snapshot_id,
                challenger["head_plan_version_id"],
                branch_id=cid,
                conn=conn,
            )

            last_snapshot_id = snapshot_id

        # Single UPDATE at the end — inside the same transaction
        if last_snapshot_id is not None:
            conn.execute(
                "UPDATE branch_comparisons SET latest_snapshot_id = ?, latest_ready = 1 WHERE comparison_id = ?",
                (last_snapshot_id, comparison_id),
            )

    return {
        "comparison_id": comparison_id,
        "comparison_snapshot_id": last_snapshot_id,
        "ready": True,
        "comparison_artifact_id": artifact.artifact_id if artifact else None,
        "refreshed_at": now,
        "blocked_reason": None,
        "missing_or_stale": [],
        "warnings": [],
    }
