"""Comparison service — intent, readiness, and immutable comparison snapshots."""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.artifacts import write_json_artifact
from cardre.audit import utc_now_iso
from cardre.staleness import compute_staleness
from cardre.store import ProjectStore

REQUIRED_EVIDENCE_CANONICAL_STEPS = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "validation-metrics",
    "cutoff-analysis",
    "technical-manifest-stub",
]

LEGACY_CANONICAL_ALIASES: dict[str, str] = {
    "logistic-regression": "model-fit",
}


def _check_branch_readiness(
    store: ProjectStore,
    branch_id: str,
    plan_version_id: str,
    required_steps: list[str],
    is_baseline: bool = False,
) -> list[dict[str, str]]:
    """Check if a branch has current successful evidence for required canonical steps.

    Uses branch-scoped evidence lookup. For baseline branches, falls back
    to full-plan (branch_id=NULL) evidence since baseline runs pre-date
    the branch model.

    Handles legacy canonical step aliases (e.g., logistic-regression -> model-fit).

    Returns a list of missing-or-stale entries; empty list = ready.
    """
    step_map = store.get_branch_step_map(branch_id, plan_version_id)
    canon_to_actual: dict[str, str] = {}
    for row in step_map:
        canon_to_actual[row["canonical_step_id"]] = row["step_id"]

    # Build reverse alias map for legacy resolution
    legacy_reverse = {v: k for k, v in LEGACY_CANONICAL_ALIASES.items()}

    staleness = compute_staleness(
        store, plan_version_id, branch_id=branch_id if not is_baseline else None,
    )

    missing: list[dict[str, str]] = []
    for cs in required_steps:
        actual_id = canon_to_actual.get(cs)
        if actual_id is None and cs in legacy_reverse:
            actual_id = canon_to_actual.get(legacy_reverse[cs])
        if actual_id is None:
            actual_id = cs
        evidence_branch = branch_id if not is_baseline else None
        rs = store.get_latest_successful_run_step_for_step(
            plan_version_id, actual_id, branch_id=evidence_branch,
        )
        if rs is None and not is_baseline:
            # Also try plan-level evidence (run before branch existed)
            plan_run_id = store.get_latest_successful_run_id_for_plan(
                store.get_plan_version(plan_version_id)["plan_id"],
            )
            if plan_run_id:
                for prs in store.get_run_steps(plan_run_id):
                    if prs.step_id == actual_id and prs.status == "succeeded":
                        rs = prs
                        break
        if rs is None:
            status = "stale" if staleness.get(actual_id, True) else "not_run"
            missing.append({
                "branch_id": branch_id,
                "canonical_step_id": cs,
                "step_id": actual_id,
                "status": status,
            })
    return missing


def _read_artifact_json(store: ProjectStore, artifact_id: str) -> dict[str, Any] | None:
    art = store.get_artifact(artifact_id)
    if art is None:
        return None
    if art.media_type != "application/json":
        return None
    try:
        path = store.artifact_path(art)
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return None


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

    def _find_artifact(step_map: list[dict], cs: str, pv_id: str, evidence_branch_id: str | None) -> dict[str, Any] | None:
        """Find the JSON artifact for a canonical step, using evidence_branch_id
        for branch-scoped lookup or None for full-plan (baseline) evidence."""
        for row in step_map:
            if row["canonical_step_id"] == cs:
                rs = store.get_latest_successful_run_step_for_step(pv_id, row["step_id"], branch_id=evidence_branch_id)
                if rs is None and evidence_branch_id is not None:
                    # Fall back to full-plan evidence for challenger shared upstreams
                    rs = store.get_latest_successful_run_step_for_step(pv_id, row["step_id"], branch_id=None)
                if rs and rs.output_artifact_ids:
                    for aid in rs.output_artifact_ids:
                        art = store.get_artifact(aid)
                        if art and art.media_type == "application/json":
                            result = _read_artifact_json(store, aid)
                            if result is not None:
                                return result
        return None

    woe_b = _find_artifact(step_map_b, "final-woe-iv", plan_version_id_baseline, None) if spec.get("include_woe_iv") else None
    woe_c = _find_artifact(step_map_c, "final-woe-iv", plan_version_id_challenger, branch_id_challenger) if spec.get("include_woe_iv") else None
    if woe_b and woe_c:
        b_vars = {}
        c_vars = {}
        for v in woe_b.get("variables", []):
            if isinstance(v, dict) and "variable" in v:
                b_vars[v["variable"]] = v
        for v in woe_c.get("variables", []):
            if isinstance(v, dict) and "variable" in v:
                c_vars[v["variable"]] = v
        all_vars = sorted(set(b_vars) | set(c_vars))
        woe_vars = []
        for var_name in all_vars:
            bv = b_vars.get(var_name, {})
            cv = c_vars.get(var_name, {})
            woe_vars.append({
                "variable": var_name,
                "baseline": {
                    "iv": bv.get("iv", 0),
                    "bin_count": len(bv.get("bins", [])),
                    "zero_cell_warning_count": len([w for w in bv.get("warnings", []) if "zero" in str(w).lower()]),
                    "sparse_bin_warning_count": len([w for w in bv.get("warnings", []) if "sparse" in str(w).lower()]),
                    "monotonicity_warning": any("monotonic" in str(w).lower() for w in bv.get("warnings", [])),
                },
                "challengers": {
                    branch_id_challenger: {
                        "iv": cv.get("iv", 0),
                        "bin_count": len(cv.get("bins", [])),
                        "zero_cell_warning_count": len([w for w in cv.get("warnings", []) if "zero" in str(w).lower()]),
                        "sparse_bin_warning_count": len([w for w in cv.get("warnings", []) if "sparse" in str(w).lower()]),
                        "monotonicity_warning": any("monotonic" in str(w).lower() for w in cv.get("warnings", [])),
                    },
                },
                "difference": {
                    "iv_delta_vs_baseline": cv.get("iv", 0) - bv.get("iv", 0),
                    "bin_count_delta_vs_baseline": len(cv.get("bins", [])) - len(bv.get("bins", [])),
                },
            })
        content["woe_iv"]["variables"] = woe_vars

    lr_b = _find_artifact(step_map_b, "model-fit", plan_version_id_baseline, None) if spec.get("include_model") else None
    lr_c = _find_artifact(step_map_c, "model-fit", plan_version_id_challenger, branch_id_challenger) if spec.get("include_model") else None

    # Fallback to legacy logistic-regression canonical step
    if lr_b is None and spec.get("include_model"):
        lr_b = _find_artifact(step_map_b, "logistic-regression", plan_version_id_baseline, None)
    if lr_c is None and spec.get("include_model"):
        lr_c = _find_artifact(step_map_c, "logistic-regression", plan_version_id_challenger, branch_id_challenger)

    if lr_b and lr_c:
        b_family = lr_b.get("model_family", "logistic_regression")
        c_family = lr_c.get("model_family", "logistic_regression")

        content["model"]["branch_level"]["baseline"] = {
            "model_family": b_family,
            "feature_count": len(lr_b.get("features", lr_b.get("feature_contract", {}).get("features", []))),
            "warnings": lr_b.get("warnings", []),
        }
        content["model"]["branch_level"][branch_id_challenger] = {
            "model_family": c_family,
            "feature_count": len(lr_c.get("features", lr_c.get("feature_contract", {}).get("features", []))),
            "warnings": lr_c.get("warnings", []),
        }

        # Coefficient comparison only for coefficient-bearing models
        if b_family == "logistic_regression" and c_family == "logistic_regression":
            b_coeffs_raw = lr_b.get("coefficients", [])
            c_coeffs_raw = lr_c.get("coefficients", [])
            b_coeffs = {}
            c_coeffs = {}
            if isinstance(b_coeffs_raw, dict):
                b_coeffs = b_coeffs_raw
            else:
                for c in b_coeffs_raw:
                    if isinstance(c, dict) and "variable" in c:
                        b_coeffs[c["variable"]] = c
            if isinstance(c_coeffs_raw, dict):
                c_coeffs = c_coeffs_raw
            else:
                for c in c_coeffs_raw:
                    if isinstance(c, dict) and "variable" in c:
                        c_coeffs[c["variable"]] = c

            model_vars = []
            for var_name in sorted(set(b_coeffs) | set(c_coeffs)):
                b_val = b_coeffs.get(var_name, 0) if isinstance(b_coeffs.get(var_name), (int, float)) else b_coeffs.get(var_name, {}).get("coefficient", 0)
                c_val = c_coeffs.get(var_name, 0) if isinstance(c_coeffs.get(var_name), (int, float)) else c_coeffs.get(var_name, {}).get("coefficient", 0)
                model_vars.append({
                    "variable": var_name,
                    "baseline": {"included": var_name in b_coeffs, "coefficient": b_val, "points_range": 0},
                    "challengers": {branch_id_challenger: {"included": var_name in c_coeffs, "coefficient": c_val, "points_range": 0}},
                })
            content["model"]["variables"] = model_vars
        else:
            # Generic model comparison: feature importance, interpretability
            b_features = lr_b.get("features", lr_b.get("feature_contract", {}).get("features", []))
            c_features = lr_c.get("features", lr_c.get("feature_contract", {}).get("features", []))
            b_interp = lr_b.get("interpretability", {})
            c_interp = lr_c.get("interpretability", {})
            content["model"]["generic_comparison"] = {
                "baseline": {
                    "model_family": b_family,
                    "features": b_features,
                    "interpretability": b_interp,
                },
                "challenger": {
                    "model_family": c_family,
                    "features": c_features,
                    "interpretability": c_interp,
                },
                "feature_overlap": len(set(b_features) & set(c_features)),
                "baseline_only_features": [f for f in b_features if f not in c_features],
                "challenger_only_features": [f for f in c_features if f not in b_features],
            }

    # Validation metrics by role
    if spec.get("include_validation"):
        vm_b = _find_artifact(step_map_b, "validation-metrics", plan_version_id_baseline, None)
        vm_c = _find_artifact(step_map_c, "validation-metrics", plan_version_id_challenger, branch_id_challenger)
        for role_name in ("train", "test", "oot"):
            b_role = vm_b.get(role_name, {}) if isinstance(vm_b, dict) else {}
            c_role = vm_c.get(role_name, {}) if isinstance(vm_c, dict) else {}
            role_data = {}
            if b_role and isinstance(b_role, dict):
                role_data["baseline"] = {
                    "auc": b_role.get("auc"),
                    "gini": b_role.get("gini"),
                    "ks": b_role.get("ks"),
                    "calibration": b_role.get("calibration", {}),
                }
            if c_role and isinstance(c_role, dict):
                role_data[branch_id_challenger] = {
                    "auc": c_role.get("auc"),
                    "gini": c_role.get("gini"),
                    "ks": c_role.get("ks"),
                    "calibration": c_role.get("calibration", {}),
                }
            content["validation"]["roles"][role_name] = role_data

    # Cutoff comparison
    if spec.get("include_cutoff"):
        co_b = _find_artifact(step_map_b, "cutoff-analysis", plan_version_id_baseline, None)
        co_c = _find_artifact(step_map_c, "cutoff-analysis", plan_version_id_challenger, branch_id_challenger)
        for role_name in ("train", "test", "oot"):
            b_bands = []
            if isinstance(co_b, dict):
                b_bands = co_b.get(role_name) or co_b.get("bands") or []
            c_bands = []
            if isinstance(co_c, dict):
                c_bands = co_c.get(role_name) or co_c.get("bands") or []

            # Pair up bands by cutoff value
            b_by_cutoff = {b.get("cutoff"): b for b in b_bands if isinstance(b, dict)}
            c_by_cutoff = {c.get("cutoff"): c for c in c_bands if isinstance(c, dict)}
            all_cutoffs = sorted(set(b_by_cutoff) | set(c_by_cutoff))
            bands = []
            for cutoff in all_cutoffs[:20]:
                b_entry = b_by_cutoff.get(cutoff, {})
                c_entry = c_by_cutoff.get(cutoff, {})
                bands.append({
                    "cutoff": cutoff,
                    "baseline": {
                        "approval_rate": b_entry.get("approval_rate"),
                        "bad_rate": b_entry.get("bad_rate"),
                        "capture_rate": b_entry.get("capture_rate"),
                        "population_count": b_entry.get("population_count"),
                    },
                    branch_id_challenger: {
                        "approval_rate": c_entry.get("approval_rate"),
                        "bad_rate": c_entry.get("bad_rate"),
                        "capture_rate": c_entry.get("capture_rate"),
                        "population_count": c_entry.get("population_count"),
                    },
                })
            content["cutoff"]["roles"][role_name] = bands

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

    Checks both baseline and all challenger branches.
    Does NOT execute modelling nodes. Does NOT create run records.
    """
    comparison = store.get_branch_comparison(comparison_id)
    if comparison is None:
        raise ValueError(f"COMPARISON_NOT_FOUND: {comparison_id}")

    baseline_branch_id = comparison["baseline_branch_id"]
    challenger_ids = json.loads(comparison["challenger_branch_ids_json"])
    spec = json.loads(comparison["comparison_spec_json"])

    baseline = store.get_branch(baseline_branch_id)
    if baseline is None:
        raise ValueError(f"BASELINE_BRANCH_NOT_FOUND: {baseline_branch_id}")

    required = REQUIRED_EVIDENCE_CANONICAL_STEPS

    # Check baseline readiness (uses full-plan evidence, not branch-scoped)
    all_missing: list[dict[str, str]] = _check_branch_readiness(
        store, baseline_branch_id, baseline["head_plan_version_id"], required,
        is_baseline=True,
    )

    # Check each challenger
    for cid in challenger_ids:
        challenger = store.get_branch(cid)
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
    for cid in challenger_ids:
        challenger = store.get_branch(cid)
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

        snapshot_id = str(uuid.uuid4())
        source_pv_ids = json.dumps([baseline["head_plan_version_id"], challenger["head_plan_version_id"]])
        readiness_data = json.dumps({"ready": True, "missing": []})

        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO branch_comparison_snapshots "
                "(comparison_snapshot_id, comparison_id, project_id, plan_id, "
                " comparison_artifact_id, readiness_json, source_plan_version_ids_json, "
                " created_at, created_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id, comparison_id, comparison["project_id"], comparison["plan_id"],
                    artifact.artifact_id, readiness_data, source_pv_ids,
                    now, "Comparison refresh",
                ),
            )
            conn.execute(
                "UPDATE branch_comparisons SET latest_snapshot_id = ?, latest_ready = 1 "
                "WHERE comparison_id = ?",
                (snapshot_id, comparison_id),
            )
        last_snapshot_id = snapshot_id

    return {
        "comparison_id": comparison_id,
        "comparison_snapshot_id": last_snapshot_id,
        "ready": True,
        "comparison_artifact_id": artifact.artifact_id if challenger_ids else None,
        "refreshed_at": now,
        "blocked_reason": None,
        "missing_or_stale": [],
        "warnings": [],
    }
