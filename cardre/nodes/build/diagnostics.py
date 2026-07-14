from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import roc_auc_score

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import (
    SCHEMA_CALIBRATION_DIAGNOSTICS,
    SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS,
    SCHEMA_SEPARATION_DIAGNOSTICS,
    SCHEMA_VIF_DIAGNOSTICS,
    SCHEMA_WOE_IV_EVIDENCE,
)
from cardre.artifacts import write_json_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.contracts import NodeType


def _json_float(value: float | None) -> float | None:
    """Return a JSON-safe float, or None if non-finite."""
    if value is None:
        return None
    if math.isinf(value) or math.isnan(value):
        return None
    return value


def _find_model_artifact(
    reader: ArtifactEvidenceReader, context: ExecutionContext
) -> Any:
    """Find the model artifact, excluding frozen scorecard bundle artifacts."""

    bundle = context.find_frozen_bundle()
    non_bundle_artifacts = [
        a for a in context.input_artifacts
        if a.artifact_id != (bundle.artifact_id if bundle else "")
    ]
    return reader.find(non_bundle_artifacts, EvidenceKind.MODEL_ARTIFACT)


class CoefficientSignCheckNode(NodeType):
    node_type = "cardre.coefficient_sign_check"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["model", "report"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        model = _find_model_artifact(reader, context)

        woe_evidence_candidates = [
            artifact
            for artifact in context.input_artifacts
            if artifact.metadata.get("schema_version") == SCHEMA_WOE_IV_EVIDENCE
        ]
        final_woe_artifact = next(
            (
                artifact
                for artifact in woe_evidence_candidates
                if artifact.metadata.get("purpose") == "final"
            ),
            None,
        )
        if final_woe_artifact is None:
            raise ValueError(
                "Coefficient sign check requires a final WOE/IV evidence artifact"
            )

        woe_evidence = json.loads(
            store.artifact_path(final_woe_artifact).read_text(encoding="utf-8")  # cardre-allow-artifact-read: low-level-evidence-parser
        )
        variables_by_name = {
            str(variable.get("variable_name", "")): variable
            for variable in list(woe_evidence.get("variables", []))
            if variable.get("variable_name")
        }

        variable_results: list[dict[str, Any]] = []
        warning_count = 0
        checked_variable_count = 0

        for feature_name in model.features:
            if not feature_name.endswith("_woe"):
                continue
            checked_variable_count += 1
            variable_name = feature_name[:-4]
            coefficient = float(model.coefficients_dict.get(feature_name, 0.0))
            variable_evidence = variables_by_name.get(variable_name, {})

            status = "pass"
            reason = (
                "Higher WOE means a higher good-to-bad ratio under ln(good_dist / bad_dist); "
                "a negative logistic coefficient therefore lowers predicted bad odds as WOE rises."
            )
            if coefficient > 0:
                status = "warning"
                warning_count += 1
                reason = (
                    "Coefficient is positive even though higher WOE indicates better risk under "
                    "ln(good_dist / bad_dist); this increases predicted bad odds as WOE rises."
                )
            elif coefficient == 0:
                status = "neutral"
                reason = "Coefficient is zero, so the WOE-transformed variable has no directional effect."

            variable_results.append(
                {
                    "variable_name": variable_name,
                    "feature_name": feature_name,
                    "coefficient": _json_float(coefficient),
                    "coefficient_is_infinite": math.isinf(coefficient) or math.isnan(coefficient),
                    "coefficient_sign": "positive" if coefficient > 0 else "negative" if coefficient < 0 else "zero",
                    "expected_sign": "negative",
                    "status": status,
                    "reason": reason,
                    "woe_variable_status": variable_evidence.get("status", "unknown"),
                }
            )

        payload = {
            "schema_version": SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS,
            "target_column": model.target_column,
            "conventions": {
                "event": "bad",
                "non_event": "good",
                "woe_formula": "ln(non_event_distribution / event_distribution)",
                "expected_logistic_sign_for_woe": "negative",
            },
            "variables": variable_results,
            "summary": {
                "checked_variable_count": checked_variable_count,
                "warning_count": warning_count,
            },
        }
        artifact = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"coefficient-sign-check-{context.step_spec.step_id}",
            payload=payload,
            metadata={"schema_version": SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS},
        )
        return NodeOutput(
            artifacts=[artifact],
            metrics={
                "checked_variable_count": checked_variable_count,
                "warning_count": warning_count,
            },
        )


class SeparationDiagnosticsNode(NodeType):
    node_type = "cardre.separation_diagnostics"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["model"]
    output_roles: list[str] = ["report"]

    SEPARATION_COEFFICIENT_THRESHOLD = 10.0

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        model = _find_model_artifact(reader, context)

        variable_results: list[dict[str, Any]] = []
        warning_count = 0

        for feature_name in model.features:
            coefficient = float(model.coefficients_dict.get(feature_name, 0.0))

            status = "pass"
            reasons: list[str] = []

            if math.isinf(coefficient):
                status = "fail"
                reasons.append(
                    f"Coefficient is infinite for {feature_name!r}, indicating "
                    f"complete separation."
                )
            elif abs(coefficient) > self.SEPARATION_COEFFICIENT_THRESHOLD:
                if status != "fail":
                    status = "warning"
                reasons.append(
                    f"Coefficient magnitude ({abs(coefficient):.2f}) exceeds "
                    f"threshold ({self.SEPARATION_COEFFICIENT_THRESHOLD}), indicating "
                    f"possible quasi-complete separation."
                )

            if status in ("fail", "warning"):
                warning_count += 1

            reason = " ".join(reasons) if reasons else "Coefficient magnitude is within normal range."

            variable_results.append(
                {
                    "feature_name": feature_name,
                    "coefficient": _json_float(coefficient),
                    "coefficient_is_infinite": math.isinf(coefficient),
                    "abs_coefficient": _json_float(abs(coefficient)),
                    "status": status,
                    "reason": reason,
                }
            )

        converged = bool(model.training.converged or False)
        iterations = int(model.training.iterations or 0)

        payload = {
            "schema_version": SCHEMA_SEPARATION_DIAGNOSTICS,
            "target_column": model.target_column,
            "threshold": self.SEPARATION_COEFFICIENT_THRESHOLD,
            "model_converged": converged,
            "model_iterations": iterations,
            "variables": variable_results,
            "summary": {
                "checked_variable_count": len(variable_results),
                "warning_count": warning_count,
            },
        }
        artifact = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"separation-diagnostics-{context.step_spec.step_id}",
            payload=payload,
            metadata={"schema_version": SCHEMA_SEPARATION_DIAGNOSTICS},
        )
        return NodeOutput(
            artifacts=[artifact],
            metrics={
                "checked_variable_count": len(variable_results),
                "warning_count": warning_count,
            },
        )


class VifDiagnosticsNode(NodeType):
    node_type = "cardre.vif_diagnostics"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "model"]
    output_roles: list[str] = ["report"]

    VIF_WARNING_THRESHOLD = 10.0

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        model = _find_model_artifact(reader, context)

        train_artifact = context.train_artifact()
        if train_artifact is None:
            raise ValueError("VIF diagnostics requires a WOE-transformed train dataset")

        df = reader.read_dataframe(train_artifact)
        woe_features = [f for f in model.features if f.endswith("_woe") and f in df.columns]

        if len(woe_features) < 2:
            payload = {
                "schema_version": SCHEMA_VIF_DIAGNOSTICS,
                "target_column": model.target_column,
                "threshold": self.VIF_WARNING_THRESHOLD,
                "variables": [],
                "summary": {
                    "checked_variable_count": len(woe_features),
                    "warning_count": 0,
                    "note": "Fewer than 2 WOE features available; VIF not computed.",
                },
            }
            artifact = write_json_artifact(
                store,
                artifact_type="report",
                role="report",
                stem=f"vif-diagnostics-{context.step_spec.step_id}",
                payload=payload,
                metadata={"schema_version": SCHEMA_VIF_DIAGNOSTICS},
            )
            return NodeOutput(
                artifacts=[artifact],
                metrics={"checked_variable_count": len(woe_features), "warning_count": 0},
            )

        X = df.select(woe_features).to_numpy()
        variable_results: list[dict[str, Any]] = []
        warning_count = 0

        # Correlation-matrix VIF: VIF_j = diagonal of inv(cor(X))
        try:
            corr = np.corrcoef(X, rowvar=False)
            if corr.ndim == 0 or corr.shape[0] < 2:
                raise ValueError("Insufficient features for correlation matrix")
            corr = corr.reshape(len(woe_features), len(woe_features))

            # Handle exact collinearity: if any column has zero variance,
            # corr will have NaN; if columns are perfectly correlated,
            # inv will fail.
            has_nan = np.isnan(corr).any()
            if has_nan:
                for _i, feature in enumerate(woe_features):
                    variable_results.append(
                        {
                            "feature_name": feature,
                            "vif": None,
                            "vif_is_infinite": True,
                            "r_squared": None,
                            "status": "warning",
                            "reason": "Variance is zero or correlation matrix is singular; VIF is infinite.",
                        }
                    )
                warning_count = len(woe_features)
            else:
                try:
                    from numpy.linalg import inv

                    vif_diagonal = np.diag(inv(corr))
                    for i, feature in enumerate(woe_features):
                        vif_raw = float(vif_diagonal[i])
                        is_infinite = math.isinf(vif_raw) or math.isnan(vif_raw)
                        vif: float | None = None if is_infinite else vif_raw
                        r_squared = 1.0 - 1.0 / vif if vif is not None and vif != 0 else None

                        status = "pass"
                        reason = f"VIF ({vif:.4f}) is below threshold ({self.VIF_WARNING_THRESHOLD})." if vif is not None else "VIF is infinite, indicating exact collinearity."
                        if is_infinite or (vif is not None and vif >= self.VIF_WARNING_THRESHOLD):
                            status = "warning"
                            warning_count += 1
                            if vif is not None:
                                reason = (
                                    f"VIF ({vif:.4f}) exceeds threshold ({self.VIF_WARNING_THRESHOLD}), "
                                    f"indicating multicollinearity."
                                )

                        variable_results.append(
                            {
                                "feature_name": feature,
                                "vif": round(vif, 6) if vif is not None else None,
                                "vif_is_infinite": is_infinite,
                                "r_squared": round(r_squared, 6) if r_squared is not None else None,
                                "status": status,
                                "reason": reason,
                            }
                        )
                except np.linalg.LinAlgError:
                    for _i, feature in enumerate(woe_features):
                        variable_results.append(
                            {
                                "feature_name": feature,
                                "vif": None,
                                "vif_is_infinite": True,
                                "r_squared": None,
                                "status": "warning",
                                "reason": "Correlation matrix is singular (exact collinearity); VIF is infinite.",
                            }
                        )
                    warning_count = len(woe_features)
        except np.linalg.LinAlgError:
            for _i, feature in enumerate(woe_features):
                variable_results.append(
                    {
                        "feature_name": feature,
                        "vif": None,
                        "r_squared": None,
                        "status": "error",
                        "reason": "VIF could not be computed.",
                    }
                )
            warning_count = len(woe_features)

        payload = {
            "schema_version": SCHEMA_VIF_DIAGNOSTICS,
            "target_column": model.target_column,
            "threshold": self.VIF_WARNING_THRESHOLD,
            "variables": variable_results,
            "summary": {
                "checked_variable_count": len(variable_results),
                "warning_count": warning_count,
            },
        }
        artifact = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"vif-diagnostics-{context.step_spec.step_id}",
            payload=payload,
            metadata={"schema_version": SCHEMA_VIF_DIAGNOSTICS},
        )
        return NodeOutput(
            artifacts=[artifact],
            metrics={
                "checked_variable_count": len(variable_results),
                "warning_count": warning_count,
            },
        )


class CalibrationDiagnosticsNode(NodeType):
    node_type = "cardre.calibration_diagnostics"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "test", "oot", "model", "definition"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        model = _find_model_artifact(reader, context)
        meta = context.target_metadata()

        target_col = meta.target_column if meta is not None else model.target_column
        good = meta.good_values if meta is not None else frozenset()
        bad = meta.bad_values if meta is not None else frozenset()
        bad_list = list(bad)

        data_arts = context.data_artifacts()
        roles_results: dict[str, dict[str, Any]] = {}

        for data_art in data_arts:
            role = data_art.role
            df = reader.read_dataframe(data_art)

            if "predicted_bad_probability" not in df.columns or not target_col or target_col not in df.columns:
                roles_results[role] = {
                    "row_count": df.height,
                    "status": "skipped",
                    "reason": "Missing predicted_bad_probability or target column.",
                }
                continue

            target_str = df[target_col].cast(pl.String)
            known_mask = target_str.is_in(good | bad).to_numpy()
            y_prob_all = df["predicted_bad_probability"].to_numpy()

            if known_mask.sum() < 2:
                roles_results[role] = {
                    "row_count": df.height,
                    "known_count": int(known_mask.sum()),
                    "status": "skipped",
                    "reason": "Fewer than 2 rows with known target values.",
                }
                continue

            y_bin = np.where(target_str.filter(known_mask).is_in(bad_list).to_numpy(), 1, 0)
            y_prob = y_prob_all[known_mask]

            if len(np.unique(y_bin)) < 2:
                roles_results[role] = {
                    "row_count": df.height,
                    "known_count": int(known_mask.sum()),
                    "status": "skipped",
                    "reason": "Single class only; Hosmer-Lemeshow not meaningful.",
                }
                continue

            n = len(y_bin)
            target_n_bins = max(2, min(10, n // 5))

            # Sort by predicted probability and form tie-aware quantile groups.
            # Rows with identical predicted probabilities are never split across
            # groups, ensuring the grouping is invariant to row order within ties.
            sort_idx = np.argsort(y_prob, kind="stable")
            group_size = max(1, math.ceil(n / target_n_bins))
            groups: list[np.ndarray] = []
            i = 0
            while i < n:
                end = min(i + group_size, n)
                if end < n:
                    while end < n and y_prob[sort_idx[end]] == y_prob[sort_idx[end - 1]]:
                        end += 1
                groups.append(sort_idx[i:end])
                i = end

            actual_min_bins = len(groups)

            # Hosmer-Lemeshow statistic:
            # H = sum_g [ (O_g - E_g)^2 / E_g + (N_g - O_g - N_g + E_g)^2 / (N_g - E_g) ]
            #   = sum_g [ (O_g - E_g)^2 / E_g + (O_non_g - E_non_g)^2 / E_non_g ]
            hl_stat = 0.0
            decile_bins: list[dict[str, Any]] = []

            for g_idx, group in enumerate(groups):
                n_g = len(group)
                observed_events = int(y_bin[group].sum())
                expected_events = float(y_prob[group].sum())
                observed_non_events = n_g - observed_events
                expected_non_events = n_g - expected_events

                # HL component: (O-E)^2/E for both event and non-event
                hl_events = 0.0
                hl_non_events = 0.0
                if expected_events > 1e-12:
                    hl_events = (observed_events - expected_events) ** 2 / expected_events
                else:
                    hl_events = 0.0 if observed_events == 0 else float("inf")
                if expected_non_events > 1e-12:
                    hl_non_events = (observed_non_events - expected_non_events) ** 2 / expected_non_events
                else:
                    hl_non_events = 0.0 if observed_non_events == 0 else float("inf")

                hl_stat += hl_events + hl_non_events

                obs_rate = observed_events / n_g if n_g > 0 else 0.0
                pred_rate = expected_events / n_g if n_g > 0 else 0.0
                decile_bins.append({
                    "bin": g_idx + 1,
                    "count": n_g,
                    "observed_events": observed_events,
                    "expected_events": round(expected_events, 6),
                    "observed_non_events": observed_non_events,
                    "expected_non_events": round(expected_non_events, 6),
                    "observed_event_rate": round(obs_rate, 6),
                    "predicted_event_rate": round(pred_rate, 6),
                    "abs_deviation": round(abs(obs_rate - pred_rate), 6),
                })

            # Degrees of freedom: groups - 2 (for intercept and slope)
            dof = max(1, actual_min_bins - 2)
            try:
                from scipy.stats import chi2

                hl_p_value = round(float(chi2.sf(hl_stat, dof)), 6)
            except (ValueError, TypeError):
                hl_p_value = None

            hl_stat_json = _json_float(hl_stat)
            hl_stat_is_infinite = math.isinf(hl_stat) or math.isnan(hl_stat)
            calibration_error = float(np.mean([b["abs_deviation"] for b in decile_bins])) if decile_bins else 0.0

            try:
                auc = round(float(roc_auc_score(y_bin, y_prob)), 6)
            except (ValueError, TypeError):
                auc = None

            roles_results[role] = {
                "row_count": df.height,
                "known_count": int(known_mask.sum()),
                "n_bins": actual_min_bins,
                "hosmer_lemeshow_statistic": round(hl_stat_json, 6) if hl_stat_json is not None else None,
                "hosmer_lemeshow_statistic_is_infinite": hl_stat_is_infinite,
                "hosmer_lemeshow_degrees_of_freedom": dof,
                "hosmer_lemeshow_p_value": hl_p_value,
                "calibration_error": round(calibration_error, 6),
                "auc": auc,
                "decile_bins": decile_bins,
                "status": "pass",
            }

        payload = {
            "schema_version": SCHEMA_CALIBRATION_DIAGNOSTICS,
            "target_column": target_col,
            "model_family": model.model_family,
            "conventions": {
                "event": "bad",
                "non_event": "good",
            },
            "roles": roles_results,
            "summary": {
                "role_count": len(roles_results),
                "roles_with_metrics": sum(
                    1 for r in roles_results.values() if r.get("status") == "pass"
                ),
            },
        }
        artifact = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"calibration-diagnostics-{context.step_spec.step_id}",
            payload=payload,
            metadata={"schema_version": SCHEMA_CALIBRATION_DIAGNOSTICS},
        )
        return NodeOutput(
            artifacts=[artifact],
            metrics={"role_count": len(roles_results)},
        )
