"""RefreshComparison — re-check branch readiness and create a new comparison snapshot.

Ports ``comparison_service.refresh_comparison`` into a single use case.
Uses ``EvidenceReaderPort`` (passed as a dependency) for typed evidence
lookup instead of ``ProjectStore``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from cardre._evidence.kinds import EvidenceKind
from cardre.application.reporting.contracts import REQUIRED_STEPS_COMPARISON
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError, GovernanceNotEnabled


@runtime_checkable
class ComparisonEvidencePort(Protocol):
    """Port for reading typed evidence needed by the comparison builders.

    Implementations resolve canonical step IDs through the
    branch-step-map, locate the relevant run-step evidence, and read
    the typed payload.
    """

    def find_typed(
        self,
        step_map: list[dict[str, Any]],
        canonical_step_id: str,
        plan_version_id: str,
        evidence_branch_id: str | None,
        kinds: tuple[EvidenceKind, ...],
    ) -> dict[str, Any] | None:
        ...


@dataclass
class RefreshComparisonCommand:
    comparison_id: str


@dataclass
class RefreshComparisonResult:
    comparison_id: str
    comparison_snapshot_id: str | None = None
    ready: bool = False
    comparison_artifact_id: str | None = None
    refreshed_at: str = ""
    blocked_reason: str | None = None
    missing_or_stale: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ComparisonContentResult:
    content: dict[str, Any]
    artifact_id: str


class RefreshComparison:
    """Re-check branch readiness and create a new snapshot if ready."""

    def __init__(
        self,
        uow_factory: Any,
        evidence_port: ComparisonEvidencePort,
        artifact_writer: Any,
        governance_enabled: bool = True,
    ) -> None:
        self._uow_factory = uow_factory
        self._evidence_port = evidence_port
        self._artifact_writer = artifact_writer
        self._governance_enabled = governance_enabled

    def __call__(self, command: RefreshComparisonCommand) -> RefreshComparisonResult:
        if not self._governance_enabled:
            raise GovernanceNotEnabled()

        with self._uow_factory.for_project(None) as uow:  # project_id resolved from comparison
            comparison = uow.comparisons.get_comparison(command.comparison_id)
            if comparison is None:
                raise CardreError(
                    f"COMPARISON_NOT_FOUND: {command.comparison_id}",
                    code="COMPARISON_NOT_FOUND",
                    context={"comparison_id": command.comparison_id},
                    status_code=404,
                )

            project_id: str = comparison["project_id"]
            plan_id: str = comparison["plan_id"]
            baseline_branch_id: str = comparison["baseline_branch_id"]
            spec = json.loads(comparison["comparison_spec_json"])
            challenger_rows = uow.comparisons.get_challenger_branches(command.comparison_id)
            challenger_ids = [r["branch_id"] for r in challenger_rows]

            baseline = uow.branches.get_branch(baseline_branch_id)
            if baseline is None:
                raise CardreError(
                    f"BASELINE_BRANCH_NOT_FOUND: {baseline_branch_id}",
                    code="BASELINE_BRANCH_NOT_FOUND",
                    context={"branch_id": baseline_branch_id},
                    status_code=404,
                )
            pv_id_baseline: str = baseline["head_plan_version_id"]

            # --- Readiness check ---
            all_missing: list[dict[str, str]] = self._check_readiness(
                uow, baseline_branch_id, pv_id_baseline, is_baseline=True,
            )
            for cid in challenger_ids:
                challenger = uow.branches.get_branch(cid)
                if challenger is None:
                    all_missing.append({"branch_id": cid, "canonical_step_id": "", "step_id": "", "status": "not_found"})
                    continue
                missing = self._check_readiness(uow, cid, challenger["head_plan_version_id"])
                all_missing.extend(missing)

            if all_missing:
                return RefreshComparisonResult(
                    comparison_id=command.comparison_id,
                    ready=False,
                    refreshed_at=utc_now_iso(),
                    blocked_reason="One or more branches have missing or stale evidence.",
                    missing_or_stale=all_missing,
                )

            # --- Build comparison content ---
            now = utc_now_iso()
            last_snapshot_id: str | None = None
            artifact_id: str | None = None

            conn = uow._conn
            for cid in challenger_ids:
                challenger = uow.branches.get_branch(cid)
                if challenger is None:
                    continue
                pv_id_challenger: str = challenger["head_plan_version_id"]

                content = self._build_content(
                    uow, project_id,
                    pv_id_baseline, pv_id_challenger,
                    baseline_branch_id, cid, spec,
                )

                artifact = self._artifact_writer.write_json(
                    artifact_type="branch_comparison",
                    role="comparison",
                    stem=f"comparison_{command.comparison_id}_{cid}",
                    payload=content,
                    metadata={"comparison_id": command.comparison_id, "challenger_branch_id": cid},
                )
                artifact_id = artifact.artifact_id

                snapshot_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO branch_comparison_snapshots "
                    "(comparison_snapshot_id, comparison_id, project_id, plan_id, "
                    " comparison_artifact_id, readiness_json, created_at, created_reason) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        snapshot_id, command.comparison_id, project_id, plan_id,
                        artifact_id,
                        json.dumps({"ready": True, "missing": []}),
                        now, "Comparison refresh",
                    ),
                )

                conn.execute(
                    "INSERT INTO comparison_snapshot_plan_versions "
                    "(comparison_snapshot_id, plan_version_id, branch_id) "
                    "VALUES (?, ?, ?)",
                    (snapshot_id, pv_id_baseline, baseline_branch_id),
                )
                conn.execute(
                    "INSERT INTO comparison_snapshot_plan_versions "
                    "(comparison_snapshot_id, plan_version_id, branch_id) "
                    "VALUES (?, ?, ?)",
                    (snapshot_id, pv_id_challenger, cid),
                )

                last_snapshot_id = snapshot_id

            if last_snapshot_id is not None:
                conn.execute(
                    "UPDATE branch_comparisons SET latest_snapshot_id = ?, latest_ready = 1 "
                    "WHERE comparison_id = ?",
                    (last_snapshot_id, command.comparison_id),
                )

            uow.commit()

        return RefreshComparisonResult(
            comparison_id=command.comparison_id,
            comparison_snapshot_id=last_snapshot_id,
            ready=True,
            comparison_artifact_id=artifact_id,
            refreshed_at=now,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_readiness(
        self,
        uow: Any,
        branch_id: str,
        plan_version_id: str,
        *,
        is_baseline: bool = False,
    ) -> list[dict[str, str]]:
        step_map = uow.branches.get_step_map(branch_id, plan_version_id)
        canon_to_actual: dict[str, str] = {}
        for row in step_map:
            canon_to_actual[row["canonical_step_id"]] = row["step_id"]

        missing: list[dict[str, str]] = []
        for cs in REQUIRED_STEPS_COMPARISON:
            actual_id = canon_to_actual.get(cs, cs)
            evidence_branch = branch_id if not is_baseline else None
            edges = uow.evidence.get_edges_for_plan_step_branch(
                plan_version_id, actual_id, evidence_branch,
            )
            if not edges:
                missing.append({
                    "branch_id": branch_id,
                    "canonical_step_id": cs,
                    "step_id": actual_id,
                    "status": "not_run",
                })
        return missing

    def _build_content(
        self,
        uow: Any,
        project_id: str,
        pv_id_baseline: str,
        pv_id_challenger: str,
        branch_id_baseline: str,
        branch_id_challenger: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        step_map_baseline = uow.branches.get_step_map(branch_id_baseline, pv_id_baseline)
        step_map_challenger = uow.branches.get_step_map(branch_id_challenger, pv_id_challenger)

        return {
            "comparison_type": "challenger_vs_baseline",
            "baseline_branch_id": branch_id_baseline,
            "challenger_branch_id": branch_id_challenger,
            "woe_iv": self._build_woe_iv(
                step_map_baseline, step_map_challenger,
                pv_id_baseline, pv_id_challenger,
                branch_id_baseline, branch_id_challenger,
                spec,
            ),
            "model": self._build_model(
                step_map_baseline, step_map_challenger,
                pv_id_baseline, pv_id_challenger,
                branch_id_baseline, branch_id_challenger,
                spec,
            ),
            "validation": self._build_validation(
                step_map_baseline, step_map_challenger,
                pv_id_baseline, pv_id_challenger,
                branch_id_baseline, branch_id_challenger,
                spec,
            ),
            "cutoff": self._build_cutoff(
                step_map_baseline, step_map_challenger,
                pv_id_baseline, pv_id_challenger,
                branch_id_baseline, branch_id_challenger,
                spec,
            ),
            "warnings": [],
        }

    def _find_artifact(
        self,
        step_map: list[dict[str, Any]],
        cs: str,
        pv_id: str,
        evidence_branch_id: str | None,
        kinds: tuple[EvidenceKind, ...],
    ) -> dict[str, Any] | None:
        for kind in kinds:
            result = self._evidence_port.find_typed(step_map, cs, pv_id, evidence_branch_id, (kind,))
            if result is not None:
                return result
        return None

    def _build_woe_iv(
        self,
        step_map_baseline: list[dict[str, Any]],
        step_map_challenger: list[dict[str, Any]],
        pv_id_baseline: str,
        pv_id_challenger: str,
        branch_id_baseline: str,
        branch_id_challenger: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        if not spec.get("include_woe_iv"):
            return {"variables": []}

        woe_b = self._find_artifact(step_map_baseline, "final-woe-iv", pv_id_baseline, None, (EvidenceKind.WOE_IV_EVIDENCE,))
        woe_c = self._find_artifact(step_map_challenger, "final-woe-iv", pv_id_challenger, branch_id_challenger, (EvidenceKind.WOE_IV_EVIDENCE,))

        if not woe_b or not woe_c:
            return {"variables": []}

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
        return {"variables": woe_vars}

    def _build_model(
        self,
        step_map_baseline: list[dict[str, Any]],
        step_map_challenger: list[dict[str, Any]],
        pv_id_baseline: str,
        pv_id_challenger: str,
        branch_id_baseline: str,
        branch_id_challenger: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        if not spec.get("include_model"):
            return {"variables": [], "branch_level": {}}

        lr_b = self._find_artifact(
            step_map_baseline, "model-fit", pv_id_baseline, None,
            (EvidenceKind.MODEL_ARTIFACT, EvidenceKind.ENSEMBLE_MODEL_ARTIFACT),
        )
        lr_c = self._find_artifact(
            step_map_challenger, "model-fit", pv_id_challenger, branch_id_challenger,
            (EvidenceKind.MODEL_ARTIFACT, EvidenceKind.ENSEMBLE_MODEL_ARTIFACT),
        )

        if not lr_b or not lr_c:
            return {"variables": [], "branch_level": {}}

        from cardre.modeling.families import require as require_family

        b_family = lr_b.get("model_family", "logistic_regression")
        c_family = lr_c.get("model_family", "logistic_regression")
        b_spec = require_family(b_family)
        c_spec = require_family(c_family)

        result: dict[str, Any] = {
            "branch_level": {
                "baseline": {
                    "model_family": b_family,
                    "feature_count": len(lr_b.get("features", lr_b.get("feature_contract", {}).get("features", []))),
                    "warnings": lr_b.get("warnings", []),
                },
                branch_id_challenger: {
                    "model_family": c_family,
                    "feature_count": len(lr_c.get("features", lr_c.get("feature_contract", {}).get("features", []))),
                    "warnings": lr_c.get("warnings", []),
                },
            },
        }

        if b_spec.has_coefficients and c_spec.has_coefficients:
            b_coeffs_value = lr_b.get("coefficients", [])
            c_coeffs_value = lr_c.get("coefficients", [])
            b_coeffs = {}
            c_coeffs = {}
            if isinstance(b_coeffs_value, dict):
                b_coeffs = b_coeffs_value
            else:
                for c in b_coeffs_value:
                    if isinstance(c, dict) and "variable" in c:
                        b_coeffs[c["variable"]] = c
            if isinstance(c_coeffs_value, dict):
                c_coeffs = c_coeffs_value
            else:
                for c in c_coeffs_value:
                    if isinstance(c, dict) and "variable" in c:
                        c_coeffs[c["variable"]] = c

            model_vars = []
            for var_name in sorted(set(b_coeffs) | set(c_coeffs)):
                b_val = (
                    b_coeffs.get(var_name, 0) if isinstance(b_coeffs.get(var_name), (int, float))
                    else b_coeffs.get(var_name, {}).get("coefficient", 0)
                )
                c_val = (
                    c_coeffs.get(var_name, 0) if isinstance(c_coeffs.get(var_name), (int, float))
                    else c_coeffs.get(var_name, {}).get("coefficient", 0)
                )
                model_vars.append({
                    "variable": var_name,
                    "baseline": {"included": var_name in b_coeffs, "coefficient": b_val, "points_range": 0},
                    "challengers": {branch_id_challenger: {"included": var_name in c_coeffs, "coefficient": c_val, "points_range": 0}},
                })
            result["variables"] = model_vars
        else:
            b_features = lr_b.get("features", lr_b.get("feature_contract", {}).get("features", []))
            c_features = lr_c.get("features", lr_c.get("feature_contract", {}).get("features", []))
            b_interp = lr_b.get("interpretability", {})
            c_interp = lr_c.get("interpretability", {})
            result["generic_comparison"] = {
                "baseline": {"model_family": b_family, "features": b_features, "interpretability": b_interp},
                "challenger": {"model_family": c_family, "features": c_features, "interpretability": c_interp},
                "feature_overlap": len(set(b_features) & set(c_features)),
                "baseline_only_features": [f for f in b_features if f not in c_features],
                "challenger_only_features": [f for f in c_features if f not in b_features],
            }

        return result

    def _build_validation(
        self,
        step_map_baseline: list[dict[str, Any]],
        step_map_challenger: list[dict[str, Any]],
        pv_id_baseline: str,
        pv_id_challenger: str,
        branch_id_baseline: str,
        branch_id_challenger: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        if not spec.get("include_validation"):
            return {"roles": {"train": {}, "test": {}, "oot": {}}}

        vm_b = self._find_artifact(
            step_map_baseline, "validation-metrics", pv_id_baseline, None,
            (EvidenceKind.VALIDATION_METRICS, EvidenceKind.VALIDATION_EVIDENCE),
        )
        vm_c = self._find_artifact(
            step_map_challenger, "validation-metrics", pv_id_challenger, branch_id_challenger,
            (EvidenceKind.VALIDATION_METRICS, EvidenceKind.VALIDATION_EVIDENCE),
        )

        def _roles(payload: dict[str, Any] | None) -> dict[str, Any]:
            if not isinstance(payload, dict):
                return {}
            r = payload.get("roles")
            if isinstance(r, dict):
                return r
            metrics_by_role = payload.get("metrics_by_role")
            if isinstance(metrics_by_role, dict):
                return metrics_by_role
            metrics = payload.get("metrics")
            if isinstance(metrics, dict):
                return metrics
            return payload

        b_roles = _roles(vm_b)
        c_roles = _roles(vm_c)

        roles: dict[str, Any] = {}
        for role_name in ("train", "test", "oot"):
            b_role = b_roles.get(role_name, {}) if isinstance(b_roles, dict) else {}
            c_role = c_roles.get(role_name, {}) if isinstance(c_roles, dict) else {}
            role_data: dict[str, Any] = {}
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
            roles[role_name] = role_data
        return {"roles": roles}

    def _build_cutoff(
        self,
        step_map_baseline: list[dict[str, Any]],
        step_map_challenger: list[dict[str, Any]],
        pv_id_baseline: str,
        pv_id_challenger: str,
        branch_id_baseline: str,
        branch_id_challenger: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        if not spec.get("include_cutoff"):
            return {"roles": {}}

        co_b = self._find_artifact(
            step_map_baseline, "cutoff-analysis", pv_id_baseline, None,
            (EvidenceKind.CUTOFF_ANALYSIS,),
        )
        co_c = self._find_artifact(
            step_map_challenger, "cutoff-analysis", pv_id_challenger, branch_id_challenger,
            (EvidenceKind.CUTOFF_ANALYSIS,),
        )

        roles: dict[str, Any] = {}
        for role_name in ("train", "test", "oot"):
            b_bands: list[dict[str, Any]] = []
            if isinstance(co_b, dict):
                b_bands = co_b.get(role_name) or co_b.get("bands") or []
            c_bands: list[dict[str, Any]] = []
            if isinstance(co_c, dict):
                c_bands = co_c.get(role_name) or co_c.get("bands") or []

            b_by_cutoff = {b.get("cutoff"): b for b in b_bands if isinstance(b, dict)}
            c_by_cutoff = {c.get("cutoff"): c for c in c_bands if isinstance(c, dict)}
            all_cutoffs = sorted({k for k in set(b_by_cutoff) | set(c_by_cutoff) if k is not None})
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
            roles[role_name] = bands
        return {"roles": roles}
