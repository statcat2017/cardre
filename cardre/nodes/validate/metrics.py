from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    roc_auc_score,
)

from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import (
    SCHEMA_APPLY_MODEL_EVIDENCE,
    SCHEMA_CUTOFF_ANALYSIS,
    SCHEMA_VALIDATION_METRICS,
)
from cardre.artifacts import write_json_artifact
from cardre.domain.diagnostics import JsonDict
from cardre.domain.errors import NodeFailedWithArtifacts
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.nodes.contracts import NodeType
from cardre.nodes.validate._metrics_calculation import (
    derive_binary_target,
    calibration_summary,
    score_distribution,
    population_stability_index,
)


def _calibration_curve(
    y_true: np.ndarray[Any, Any], y_prob: np.ndarray[Any, Any],
    *, n_bins: int, strategy: str,
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    from sklearn.calibration import calibration_curve
    result = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy=strategy)
    return (np.asarray(result[0]), np.asarray(result[1]))


class ValidationMetricsNode(NodeType):
    node_type = "cardre.validation_metrics"
    version = "2"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition", "report"]
    output_roles: list[str] = ["report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Validation Metrics",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Compute validation metrics (AUC, KS, Gini, precision, recall, F1, G-Mean) at given cutoffs.",
                    params=[
                        ParameterDefinition(
                            name="cutoffs",
                            label="Cutoffs",
                            kind="list",
                            default=[0.5],
                            help_text="List of probability thresholds at which to compute confusion-matrix derived metrics.",
                            constraint=ParameterConstraint(min_items=1),
                        ),
                        ParameterDefinition(
                            name="include_calibration_display",
                            label="Include Calibration Display",
                            kind="boolean",
                            default=False,
                            help_text="Whether to include calibration curve data (prob_true, prob_pred) alongside bucketed calibration.",
                        ),
                        ParameterDefinition(
                            name="require_test",
                            label="Require Test",
                            kind="boolean",
                            default=True,
                            help_text="Whether a test dataset is required.",
                        ),
                        ParameterDefinition(
                            name="require_oot",
                            label="Require OOT",
                            kind="boolean",
                            default=False,
                            help_text="Whether an OOT dataset is required.",
                        ),
                        ParameterDefinition(
                            name="minimum_auc",
                            label="Minimum AUC",
                            kind="float",
                            default=None,
                            required=False,
                            help_text="Minimum acceptable AUC (null = no threshold).",
                        ),
                        ParameterDefinition(
                            name="maximum_psi",
                            label="Maximum PSI",
                            kind="float",
                            default=None,
                            required=False,
                            help_text="Maximum acceptable PSI (null = no threshold).",
                        ),
                        ParameterDefinition(
                            name="fail_on_missing_score",
                            label="Fail on Missing Score",
                            kind="boolean",
                            default=True,
                            help_text="Whether missing score column is a gate failure.",
                        ),
                        ParameterDefinition(
                            name="fail_on_missing_target",
                            label="Fail on Missing Target",
                            kind="boolean",
                            default=True,
                            help_text="Whether missing target column is a gate failure.",
                        ),
                    ],
                ),
            ],
            default_method="default",
        )

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        meta = context.target_metadata()
        target_col = meta.target_column if meta is not None else ""
        good = meta.good_values if meta is not None else frozenset()
        bad = meta.bad_values if meta is not None else frozenset()
        bad_list = list(bad)

        params = context.validated_params
        cutoffs = list(params.get("cutoffs", [0.5]))
        include_calibration_display = params.get("include_calibration_display", False)
        require_test = params.get("require_test", True)
        require_oot = params.get("require_oot", False)
        minimum_auc = params.get("minimum_auc")
        maximum_psi = params.get("maximum_psi")
        fail_on_missing_score = params.get("fail_on_missing_score", True)
        fail_on_missing_target = params.get("fail_on_missing_target", True)

        bundle_art = context.find_frozen_bundle()
        score_evidence_art = next(
            (a for a in context.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_APPLY_MODEL_EVIDENCE),
            None,
        )

        data_arts = context.data_artifacts()
        roles_metrics, psi_data, gates = self._compute_role_metrics(
            reader, data_arts, target_col, set(good), set(bad), bad_list,
            cutoffs, include_calibration_display,
            require_test, require_oot,
            fail_on_missing_score, fail_on_missing_target,
        )

        stability, all_psi_warnings = self._compute_stability(psi_data)

        gates = self._apply_threshold_gates(gates, roles_metrics, stability, minimum_auc, maximum_psi)

        payload = self._build_payload(
            target_col, set(good), set(bad), roles_metrics, stability, gates, all_psi_warnings,
            bundle_art, score_evidence_art,
        )

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"validation-metrics-{context.step_spec.step_id}",
            payload=payload,
            metadata={"schema_version": SCHEMA_VALIDATION_METRICS},
        )

        failing_gates = [gate for gate in gates if gate.get("status") == "fail"]
        if failing_gates:
            failing_gate_codes = ", ".join(
                str(gate.get("code", "UNKNOWN_GATE"))
                for gate in failing_gates
            )
            raise NodeFailedWithArtifacts(
                f"Validation metrics failed required gate(s): {failing_gate_codes}",
                artifacts=[art],
            )

        return NodeOutput(artifacts=[art], metrics={"role_count": len(data_arts)})

    def _compute_role_metrics(
        self, reader: ArtifactEvidenceReader, data_arts: list[Any],
        target_col: str, good: set[str], bad: set[str], bad_list: list[str],
        cutoffs: list[float], include_calibration_display: bool,
        require_test: bool, require_oot: bool,
        fail_on_missing_score: bool, fail_on_missing_target: bool,
    ) -> tuple[dict[str, JsonDict], dict[str, pl.Series], list[JsonDict]]:
        roles_metrics: dict[str, JsonDict] = {}
        psi_data: dict[str, Any] = {}
        gates: list[JsonDict] = []

        role_names = {a.role for a in data_arts}
        gates.append({"code": "TRAIN_SAMPLE_PRESENT", "status": "pass"})
        if require_test:
            gates.append({
                "code": "TEST_SAMPLE_PRESENT",
                "status": "pass" if "test" in role_names else "fail",
                "message": "Test sample not supplied" if "test" not in role_names else "",
            })
        if require_oot:
            gates.append({
                "code": "OOT_SAMPLE_PRESENT",
                "status": "pass" if "oot" in role_names else "fail",
                "message": "OOT not supplied" if "oot" not in role_names else "",
            })
        elif "oot" not in role_names:
            gates.append({
                "code": "OOT_SAMPLE_PRESENT",
                "status": "warning",
                "message": "OOT not supplied",
            })

        for data_art in data_arts:
            role = data_art.role
            df = reader.read_dataframe(data_art)
            n = df.height

            if "predicted_bad_probability" not in df.columns:
                roles_metrics[role] = {"row_count": n, "error": "Missing predicted_bad_probability"}
                if fail_on_missing_score:
                    gates.append({
                        "code": "PREDICTED_BAD_PROBABILITY_PRESENT",
                        "status": "fail",
                        "message": f"Role {role!r} missing predicted_bad_probability",
                    })
                continue

            y_bin, known_mask, warnings = derive_binary_target(df, target_col, good, bad)
            y_prob_all = df["predicted_bad_probability"].to_numpy()
            has_score = "score" in df.columns
            if fail_on_missing_score and not has_score:
                gates.append({
                    "code": "NO_MISSING_SCORE",
                    "status": "fail",
                    "message": f"Role {role!r} missing score",
                })
            scores_series_all = df["score"] if has_score else df["predicted_bad_probability"]

            if y_bin is None:
                roles_metrics[role] = {"row_count": n, "warnings": warnings}
                if fail_on_missing_target:
                    gates.append({
                        "code": "TARGET_AVAILABLE",
                        "status": "fail",
                        "message": f"Role {role!r}: target column not available",
                    })
                continue

            y_prob = y_prob_all[known_mask]
            scores = scores_series_all.to_numpy()[known_mask]
            scores_series = pl.Series(scores)

            n_bad = int(sum(y_bin))
            n_good = int(len(y_bin) - n_bad)

            all_known_list = list(good | bad)
            df_known = df.filter(pl.col(target_col).cast(pl.String).is_in(all_known_list))

            auc_val = None
            gini_val = None
            ks_val = None
            ks_at = 0.0
            calib = {}
            calib_display = {}
            score_dist = {}

            if n_bad > 0 and n_good > 0:
                auc_val = round(float(roc_auc_score(y_bin, y_prob)), 6)
                gini_val = round(2 * auc_val - 1, 6)

                ks_sort_col = "score" if has_score else "predicted_bad_probability"
                ks_df = df_known.with_columns(
                    pl.when(pl.col(target_col).cast(pl.String).is_in(bad_list))
                    .then(pl.lit(1)).otherwise(pl.lit(0)).alias("_y_binary")
                ).sort(ks_sort_col).with_columns(
                    (pl.lit(1) - pl.col("_y_binary")).cum_sum().alias("_cum_good"),
                    pl.col("_y_binary").cum_sum().alias("_cum_bad"),
                ).select(
                    (pl.col("_cum_good") / n_good - pl.col("_cum_bad") / n_bad).abs().alias("ks_val"),
                    pl.col(ks_sort_col).alias("ks_at"),
                )
                ks_max = ks_df.select(pl.max("ks_val")).item()
                if ks_max is not None:
                    ks_val = round(float(ks_max), 6)
                    ks_at_rows = ks_df.filter(pl.col("ks_val") == ks_max).select("ks_at")
                    ks_at = float(ks_at_rows.row(0)[0])

                calib = calibration_summary(df_known, target_col, bad_list, 10)
                score_dist = score_distribution(scores)
                if include_calibration_display:
                    prob_true, prob_pred = _calibration_curve(
                        y_bin, y_prob, n_bins=10, strategy="quantile",
                    )
                    calib_display = {
                        "prob_true": [float(v) for v in prob_true],
                        "prob_pred": [float(v) for v in prob_pred],
                        "n_bins": 10,
                        "strategy": "quantile",
                    }
            else:
                calib = {"note": "Single class only; metrics skipped"}

            at_cutoffs: dict[str, dict[str, Any]] = {}
            for cutoff in cutoffs:
                y_pred = (y_prob >= cutoff).astype(int)
                tn, fp, fn, tp = confusion_matrix(y_bin, y_pred, labels=[0, 1]).ravel()
                n_known = len(y_bin)
                accuracy = round((tp + tn) / n_known, 6) if n_known > 0 else 0.0
                precision = round(tp / (tp + fp), 6) if (tp + fp) > 0 else 0.0
                recall = round(tp / (tp + fn), 6) if (tp + fn) > 0 else 0.0
                specificity = round(tn / (tn + fp), 6) if (tn + fp) > 0 else 0.0
                f1 = round(f1_score(y_bin, y_pred, zero_division=0), 6)
                g_mean = round((recall * specificity) ** 0.5, 6) if recall > 0 and specificity > 0 else 0.0
                at_cutoffs[str(cutoff)] = {
                    "cutoff": cutoff,
                    "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
                    "accuracy": accuracy,
                    "precision": precision,
                    "recall": recall,
                    "specificity": specificity,
                    "f1": f1,
                    "g_mean": g_mean,
                }

            roles_metrics[role] = {
                "row_count": n,
                "bad_count": int(n_bad),
                "good_count": int(n_good),
                "auc": auc_val,
                "gini": gini_val,
                "ks": ks_val,
                "ks_at": ks_at,
                "calibration": calib,
                "calibration_display": calib_display,
                "score_distribution": score_dist,
                "at_cutoffs": at_cutoffs,
                "warnings": warnings,
            }

            if has_score:
                psi_data[role] = scores

        return roles_metrics, psi_data, gates

    def _compute_stability(
        self, psi_data: dict[str, pl.Series],
    ) -> tuple[JsonDict, list[JsonDict]]:
        all_psi_warnings: list[JsonDict] = []
        stability: JsonDict = {}

        if "train" in psi_data and "test" in psi_data:
            psi_val, psi_warnings = population_stability_index(
                psi_data["train"], psi_data["test"],
            )
            stability["train_vs_test"] = psi_val
            all_psi_warnings.extend(psi_warnings)
        if "train" in psi_data and "oot" in psi_data:
            psi_val, psi_warnings = population_stability_index(
                psi_data["train"], psi_data["oot"],
            )
            stability["train_vs_oot"] = psi_val
            all_psi_warnings.extend(psi_warnings)
        if "test" in psi_data and "oot" in psi_data:
            psi_val, psi_warnings = population_stability_index(
                psi_data["test"], psi_data["oot"],
            )
            stability["test_vs_oot"] = psi_val
            all_psi_warnings.extend(psi_warnings)

        return stability, all_psi_warnings

    def _apply_threshold_gates(
        self, gates: list[JsonDict], roles_metrics: dict[str, JsonDict],
        stability: JsonDict, minimum_auc: Any, maximum_psi: Any,
    ) -> list[JsonDict]:
        if minimum_auc is not None:
            try:
                threshold_auc = float(minimum_auc)
                for role, m in roles_metrics.items():
                    actual_auc = m.get("auc")
                    if actual_auc is not None and actual_auc < threshold_auc:
                        gates.append({
                            "code": "MINIMUM_AUC",
                            "status": "fail",
                            "message": f"Role {role!r}: AUC {actual_auc} < {threshold_auc}",
                        })
            except (ValueError, TypeError):
                pass

        if maximum_psi is not None:
            try:
                threshold_psi = float(maximum_psi)
                for comparison, actual_psi in stability.items():
                    if actual_psi is not None and actual_psi > threshold_psi:
                        gates.append({
                            "code": "MAXIMUM_PSI",
                            "status": "fail",
                            "message": f"Stability {comparison}: PSI {actual_psi} > {threshold_psi}",
                        })
            except (ValueError, TypeError):
                pass

        return gates

    def _build_payload(
        self, target_col: str, good: set[str], bad: set[str],
        roles_metrics: dict[str, JsonDict], stability: JsonDict,
        gates: list[JsonDict], all_psi_warnings: list[JsonDict],
        bundle_art: Any, score_evidence_art: Any,
    ) -> JsonDict:
        from cardre._evidence.schemas import SCHEMA_CUTOFF_ANALYSIS

        payload: JsonDict = {
            "schema_version": SCHEMA_VALIDATION_METRICS,
            "target_column": target_col,
            "good_values": list(good),
            "bad_values": list(bad),
            "gates": gates,
            "stability": stability,
            "roles": roles_metrics,
            "row_counts": {},
        }
        for role, m in roles_metrics.items():
            payload["row_counts"][role] = m.get("row_count", 0)

        if all_psi_warnings:
            payload["psi_warnings"] = all_psi_warnings

        bundle_source = None
        if bundle_art:
            bundle_source = {
                "bundle_artifact_id": str(bundle_art.artifact_id),
                "schema_version": str(bundle_art.metadata.get("schema_version", "")),
            }
        payload["frozen_bundle"] = bundle_source

        score_source = None
        if score_evidence_art:
            score_source = {
                "artifact_id": str(score_evidence_art.artifact_id),
                "schema_version": SCHEMA_APPLY_MODEL_EVIDENCE,
            }
        payload["score_evidence"] = score_source

        return payload
