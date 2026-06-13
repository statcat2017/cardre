"""Comparison service — intent, readiness, and immutable comparison snapshots."""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.artifacts import write_json_artifact
from cardre.audit import utc_now_iso
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

REQUIRED_EVIDENCE_CANONICAL_STEPS = [
    "final-woe-iv",
    "logistic-regression",
    "score-scaling",
    "validation-metrics",
    "cutoff-analysis",
    "technical-manifest-stub",
]


def _check_branch_readiness(
    store: ProjectStore,
    branch_id: str,
    plan_version_id: str,
    required_steps: list[str],
) -> list[dict[str, str]]:
    """Check if a branch has current successful evidence for required canonical steps.

    Returns a list of missing-or-stale entries; empty list = ready.
    """
    step_map = store.get_branch_step_map(branch_id, plan_version_id)
    canon_to_actual: dict[str, str] = {}
    for row in step_map:
        if row["is_branch_owned"]:
            canon_to_actual[row["canonical_step_id"]] = row["step_id"]

    executor = PlanExecutor(NodeRegistry.with_defaults())
    staleness = executor.compute_staleness(store, plan_version_id)

    missing: list[dict[str, str]] = []
    for cs in required_steps:
        actual_id = canon_to_actual.get(cs, cs)
        run_id = store.get_latest_successful_run_id(plan_version_id)
        if run_id is None:
            missing.append({"branch_id": branch_id, "canonical_step_id": cs, "step_id": actual_id, "status": "not_run"})
            continue
        run_steps = store.get_run_steps(run_id)
        found = any(rs.step_id == actual_id and rs.status == "succeeded" for rs in run_steps)
        if not found or staleness.get(actual_id, True):
            missing.append({"branch_id": branch_id, "canonical_step_id": cs, "step_id": actual_id, "status": "stale" if staleness.get(actual_id, True) else "not_run"})
    return missing


def _build_comparison_content(
    store: ProjectStore,
    plan_version_id_baseline: str,
    plan_version_id_challenger: str,
    branch_id_baseline: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Build comparison JSON content from branch evidence."""
    content: dict[str, Any] = {
        "comparison_type": "challenger_vs_baseline",
        "baseline_branch_id": branch_id_baseline,
        "challenger_branch_id": branch_id_challenger,
        "woe_iv": {"variables": []},
        "model": {"variables": [], "branch_level": {}},
        "validation": {"roles": {"train": {}, "test": {}, "oot": {}}},
        "cutoff": {"roles": {}},
        "warnings": [],
    }

    step_map_b = store.get_branch_step_map(branch_id_baseline, plan_version_id_baseline)
    step_map_c = store.get_branch_step_map(branch_id_challenger, plan_version_id_challenger)

    def _find_artifact_for_step(
        step_map: list[dict], canonical_step_id: str, pv_id: str
    ) -> dict[str, Any] | None:
        for row in step_map:
            if row["canonical_step_id"] == canonical_step_id:
                run_id = store.get_latest_successful_run_id(pv_id)
                if run_id is None:
                    return None
                for rs in store.get_run_steps(run_id):
                    if rs.step_id == row["step_id"] and rs.output_artifact_ids:
                        art = store.get_artifact(rs.output_artifact_ids[0])
                        if art:
                            try:
                                path = store.artifact_path(art)
                                data = json.loads(path.read_text())
                                return data
                            except (FileNotFoundError, json.JSONDecodeError):
                                return None
        return None

    # WOE/IV comparison
    fw_b = _find_artifact_for_step(step_map_b, "final-woe-iv", plan_version_id_baseline)
    fw_c = _find_artifact_for_step(step_map_c, "final-woe-iv", plan_version_id_challenger)
    if fw_b and fw_c:
        all_vars = set()
        for v in fw_b.get("variables", []):
            all_vars.add(v.get("variable", ""))
        for v in fw_c.get("variables", []):
            all_vars.add(v.get("variable", ""))
        b_vars = {v.get("variable"): v for v in fw_b.get("variables", [])}
        c_vars = {v.get("variable"): v for v in fw_c.get("variables", [])}

        woe_vars = []
        for var_name in sorted(all_vars):
            bv = b_vars.get(var_name, {})
            cv = c_vars.get(var_name, {})
            woe_vars.append({
                "variable": var_name,
                "baseline": {
                    "iv": bv.get("iv", 0),
                    "bin_count": len(bv.get("bins", [])),
                    "zero_cell_warning_count": 0,
                    "sparse_bin_warning_count": 0,
                    "monotonicity_warning": False,
                },
                "challengers": {
                    branch_id_challenger: {
                        "iv": cv.get("iv", 0),
                        "bin_count": len(cv.get("bins", [])),
                        "zero_cell_warning_count": 0,
                        "sparse_bin_warning_count": 0,
                        "monotonicity_warning": False,
                    }
                },
                "difference": {
                    "iv_delta_vs_baseline": cv.get("iv", 0) - bv.get("iv", 0),
                    "bin_count_delta_vs_baseline": len(cv.get("bins", [])) - len(bv.get("bins", [])),
                },
            })
        content["woe_iv"]["variables"] = woe_vars

    # Model comparison
    lr_b = _find_artifact_for_step(step_map_b, "logistic-regression", plan_version_id_baseline)
    lr_c = _find_artifact_for_step(step_map_c, "logistic-regression", plan_version_id_challenger)
    if lr_b and lr_c:
        model_vars = []
        b_coeffs = {c.get("variable"): c for c in lr_b.get("coefficients", [])}
        c_coeffs = {c.get("variable"): c for c in lr_c.get("coefficients", [])}
        for var_name in sorted(set(b_coeffs) | set(c_coeffs)):
            model_vars.append({
                "variable": var_name,
                "baseline": {"included": var_name in b_coeffs, "coefficient": b_coeffs.get(var_name, {}).get("coefficient", 0), "points_range": 0},
                "challengers": {branch_id_challenger: {"included": var_name in c_coeffs, "coefficient": c_coeffs.get(var_name, {}).get("coefficient", 0), "points_range": 0}},
            })
        content["model"]["variables"] = model_vars
        content["model"]["branch_level"]["baseline"] = {"feature_count": len(b_coeffs), "converged": lr_b.get("converged", True), "warnings": lr_b.get("warnings", [])}
        content["model"]["branch_level"][branch_id_challenger] = {"feature_count": len(c_coeffs), "converged": lr_c.get("converged", True), "warnings": lr_c.get("warnings", [])}

    return content


def create_comparison(
    store: ProjectStore,
    project_id: str,
    plan_id: str,
    baseline_branch_id: str,
    challenger_branch_ids: list[str],
    comparison_spec: dict[str, Any] | None = None,
    created_reason: str | None = None,
) -> dict[str, Any]:
    """Create comparison intent. Does NOT execute any modelling nodes."""
    baseline = store.get_branch(baseline_branch_id)
    if baseline is None:
        raise ValueError(f"BASELINE_BRANCH_NOT_FOUND: {baseline_branch_id}")

    for cid in challenger_branch_ids:
        if store.get_branch(cid) is None:
            raise ValueError(f"CHALLENGER_BRANCH_NOT_FOUND: {cid}")

    spec = comparison_spec or {
        "roles": ["train", "test", "oot"],
        "include_woe_iv": True,
        "include_model": True,
        "include_validation": True,
        "include_cutoff": True,
        "include_warnings": True,
    }

    comparison_id = str(uuid.uuid4())
    now = utc_now_iso()
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO branch_comparisons "
            "(comparison_id, project_id, plan_id, baseline_branch_id, "
            " challenger_branch_ids_json, comparison_spec_json, created_at, created_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                comparison_id, project_id, plan_id, baseline_branch_id,
                json.dumps(challenger_branch_ids), json.dumps(spec),
                now, created_reason,
            ),
        )

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

    Does NOT execute modelling nodes. Does NOT create run records.
    """
    row = store._connect().execute(
        "SELECT * FROM branch_comparisons WHERE comparison_id = ?",
        (comparison_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"COMPARISON_NOT_FOUND: {comparison_id}")

    comparison = dict(row)
    baseline_branch_id = comparison["baseline_branch_id"]
    challenger_ids = json.loads(comparison["challenger_branch_ids_json"])
    spec = json.loads(comparison["comparison_spec_json"])

    baseline = store.get_branch(baseline_branch_id)

    all_missing: list[dict[str, str]] = []
    for cid in challenger_ids:
        challenger = store.get_branch(cid)
        required = spec.get("include_woe_iv", True) and REQUIRED_EVIDENCE_CANONICAL_STEPS or ["cutoff-analysis"]
        missing = _check_branch_readiness(store, cid, challenger["head_plan_version_id"], required)
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

    # Build comparison content
    now = utc_now_iso()
    snapshot_id = str(uuid.uuid4())

    # Build content for each challenger vs baseline
    for cid in challenger_ids:
        challenger = store.get_branch(cid)
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
            metadata={"comparison_id": comparison_id, "snapshot_id": snapshot_id},
        )

        source_pv_ids = json.dumps([baseline["head_plan_version_id"], challenger["head_plan_version_id"]])
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO branch_comparison_snapshots "
                "(comparison_snapshot_id, comparison_id, project_id, plan_id, "
                " comparison_artifact_id, readiness_json, source_plan_version_ids_json, "
                " created_at, created_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id, comparison_id, comparison["project_id"], comparison["plan_id"],
                    artifact.artifact_id,
                    json.dumps({"ready": True, "missing": []}),
                    source_pv_ids, now, "Comparison refresh",
                ),
            )
            conn.execute(
                "UPDATE branch_comparisons SET latest_snapshot_id = ?, latest_ready = 1, latest_readiness_json = ? WHERE comparison_id = ?",
                (snapshot_id, json.dumps({"ready": True}), comparison_id),
            )

        return {
            "comparison_id": comparison_id,
            "comparison_snapshot_id": snapshot_id,
            "ready": True,
            "comparison_artifact_id": artifact.artifact_id,
            "refreshed_at": now,
            "blocked_reason": None,
            "missing_or_stale": [],
            "warnings": [],
        }

    return {
        "comparison_id": comparison_id,
        "comparison_snapshot_id": None,
        "ready": False,
        "comparison_artifact_id": None,
        "refreshed_at": now,
        "blocked_reason": "No challengers to compare.",
        "missing_or_stale": [],
        "warnings": [],
    }
