from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import roc_auc_score

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import (
    SCHEMA_CALIBRATION_DIAGNOSTICS,
    SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS,
    SCHEMA_SEPARATION_DIAGNOSTICS,
    SCHEMA_VIF_DIAGNOSTICS,
    SCHEMA_WOE_IV_EVIDENCE,
)
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    InputCollection,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)


def _json_float(value: float | None) -> float | None:
    if value is None:
        return None
    if math.isinf(value) or math.isnan(value):
        return None
    return value


def _find_model_artifact(inputs: InputCollection) -> Any:
    model_list = inputs.by_kind(EvidenceKind.MODEL_ARTIFACT)
    if not model_list:
        raise ValueError("No model artifact found")
    return model_list[0]


class CoefficientSignCheckNode(NodeType):
    node_type = "cardre.coefficient_sign_check"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["model", "report"]
    output_roles: list[str] = ["report"]

    __definition__ = NodeDefinition(
        node_type="cardre.coefficient_sign_check",
        version="1",
        category="fit",
        description="Check coefficient signs against WOE expectations",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,)),
                ArtifactRoleSpec("report"),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("report"),
            ),
        ),
        parameter_schema=None,
    )

    def run(self, context: NodeContext) -> NodeResult:
        model = _find_model_artifact(context.inputs)

        report_arts = context.inputs.by_role("report")
        final_woe_candidates = [
            a for a in report_arts
            if a.metadata.get("schema_version") == SCHEMA_WOE_IV_EVIDENCE
            and a.metadata.get("purpose") == "final"
        ]
        if not final_woe_candidates:
            raise ValueError(
                "Coefficient sign check requires a final WOE/IV evidence artifact"
            )

        woe_evidence = context.inputs.read(final_woe_candidates[0], EvidenceKind.WOE_IV_EVIDENCE)
        variables_by_name = {
            v.variable_name: v
            for v in woe_evidence.variables
            if v.variable_name
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
                    "woe_variable_status": getattr(variable_evidence, "status", "unknown"),
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
        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS,
            payload=payload,
            metadata={"schema_version": SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS},
        )
        context.outputs.add_metric("checked_variable_count", checked_variable_count)
        context.outputs.add_metric("warning_count", warning_count)
        return context.outputs.build_result()


class SeparationDiagnosticsNode(NodeType):
    node_type = "cardre.separation_diagnostics"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["model"]
    output_roles: list[str] = ["report"]

    __definition__ = NodeDefinition(
        node_type="cardre.separation_diagnostics",
        version="1",
        category="fit",
        description="Check model coefficients for separation",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,)),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("report"),
            ),
        ),
        parameter_schema=None,
    )

    SEPARATION_COEFFICIENT_THRESHOLD = 10.0

    def run(self, context: NodeContext) -> NodeResult:
        model = _find_model_artifact(context.inputs)

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
        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.SEPARATION_DIAGNOSTICS,
            payload=payload,
            metadata={"schema_version": SCHEMA_SEPARATION_DIAGNOSTICS},
        )
        context.outputs.add_metric("checked_variable_count", len(variable_results))
        context.outputs.add_metric("warning_count", warning_count)
        return context.outputs.build_result()


class VifDiagnosticsNode(NodeType):
    node_type = "cardre.vif_diagnostics"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "model"]
    output_roles: list[str] = ["report"]

    __definition__ = NodeDefinition(
        node_type="cardre.vif_diagnostics",
        version="1",
        category="fit",
        description="VIF multicollinearity diagnostics",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("train"),
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,)),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("report"),
            ),
        ),
        parameter_schema=None,
    )

    VIF_WARNING_THRESHOLD = 10.0

    def run(self, context: NodeContext) -> NodeResult:
        model = _find_model_artifact(context.inputs)

        train_artifact = context.inputs.first("train")
        if train_artifact is None:
            raise ValueError("VIF diagnostics requires a WOE-transformed train dataset")

        df = context.inputs.read_dataframe(train_artifact)
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
            context.outputs.publish_json(
                role="report",
                kind=EvidenceKind.VIF_DIAGNOSTICS,
                payload=payload,
                metadata={"schema_version": SCHEMA_VIF_DIAGNOSTICS},
            )
            context.outputs.add_metric("checked_variable_count", len(woe_features))
            context.outputs.add_metric("warning_count", 0)
            return context.outputs.build_result()

        X = df.select(woe_features).to_numpy()
        variable_results: list[dict[str, Any]] = []
        warning_count = 0

        try:
            corr = np.corrcoef(X, rowvar=False)
            if corr.ndim == 0 or corr.shape[0] < 2:
                raise ValueError("Insufficient features for correlation matrix")
            corr = corr.reshape(len(woe_features), len(woe_features))

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
        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.VIF_DIAGNOSTICS,
            payload=payload,
            metadata={"schema_version": SCHEMA_VIF_DIAGNOSTICS},
        )
        context.outputs.add_metric("checked_variable_count", len(variable_results))
        context.outputs.add_metric("warning_count", warning_count)
        return context.outputs.build_result()


class CalibrationDiagnosticsNode(NodeType):
    node_type = "cardre.calibration_diagnostics"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "test", "oot", "model", "definition"]
    output_roles: list[str] = ["report"]

    __definition__ = NodeDefinition(
        node_type="cardre.calibration_diagnostics",
        version="1",
        category="fit",
        description="Calibration diagnostics using Hosmer-Lemeshow",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("train"),
                ArtifactRoleSpec("test"),
                ArtifactRoleSpec("oot"),
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,)),
                ArtifactRoleSpec("definition", kinds=(EvidenceKind.BIN_DEFINITION,)),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("report"),
            ),
        ),
        parameter_schema=None,
    )

    def run(self, context: NodeContext) -> NodeResult:
        model = _find_model_artifact(context.inputs)
        meta = context.inputs.target_metadata()

        target_col = meta.target_column if meta is not None else model.target_column
        good = meta.good_values if meta is not None else frozenset()
        bad = meta.bad_values if meta is not None else frozenset()
        bad_list = list(bad)

        data_arts = []
        for role in ("train", "test", "oot"):
            data_arts.extend(context.inputs.by_role(role))
        roles_results: dict[str, dict[str, Any]] = {}

        for data_art in data_arts:
            role = data_art.role
            df = context.inputs.read_dataframe(data_art)

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

            hl_stat = 0.0
            decile_bins: list[dict[str, Any]] = []

            for g_idx, group in enumerate(groups):
                n_g = len(group)
                observed_events = int(y_bin[group].sum())
                expected_events = float(y_prob[group].sum())
                observed_non_events = n_g - observed_events
                expected_non_events = n_g - expected_events

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
        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.CALIBRATION_DIAGNOSTICS,
            payload=payload,
            metadata={"schema_version": SCHEMA_CALIBRATION_DIAGNOSTICS},
        )
        context.outputs.add_metric("role_count", len(roles_results))
        return context.outputs.build_result()
