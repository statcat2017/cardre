from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    roc_auc_score,
)

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, JsonDict, NodeOutput, NodeType
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_CUTOFF_ANALYSIS,
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_SCORE_APPLICATION_EVIDENCE,
    SCHEMA_VALIDATION_EVIDENCE,
)


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
                            help_text="Minimum acceptable AUC (null = no threshold).",
                        ),
                        ParameterDefinition(
                            name="maximum_psi",
                            label="Maximum PSI",
                            kind="float",
                            default=None,
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

    def _derive_y_bin(
        self, df: pl.DataFrame, target_col: str, good: set[str], bad: set[str],
    ) -> tuple[np.ndarray | None, np.ndarray | None, list[dict]]:
        """Derive the binary target array for known good/bad rows only.

        Returns ``(y_bin, known_mask, warnings)`` where *y_bin* contains only
        rows whose target value is declared as good (0) or bad (1), and
        *known_mask* is a boolean numpy array (length ``df.height``) that
        callers can use to filter probability/score arrays to the same rows.
        Returns ``(None, None, warnings)`` when metrics are unavailable.
        """
        warnings: list[dict] = []
        if not target_col or target_col not in df.columns:
            warnings.append({
                "code": "MISSING_TARGET_COLUMN",
                "message": f"Target column {target_col!r} not found; "
                           "all metrics except row count are unavailable.",
            })
            return None, None, warnings
        if not good and not bad:
            warnings.append({
                "code": "MISSING_TARGET_METADATA",
                "message": "No good_values/bad_values in definition artifact; "
                           "all metrics except row count are unavailable.",
            })
            return None, None, warnings

        good_list = list(good)
        bad_list = list(bad)
        all_known = good | bad
        target_str = df[target_col].cast(pl.String)
        known_mask = target_str.is_in(all_known).to_numpy()
        unknown_count = int((~known_mask).sum())
        if unknown_count > 0:
            warnings.append({
                "code": "UNKNOWN_TARGET_VALUES",
                "message": f"Target column {target_col!r} contains {unknown_count} row(s) "
                           f"with values not declared as good or bad. "
                           f"These rows are excluded from metric computation.",
            })

        y_bin_full = df.with_columns(
            pl.when(target_str.is_in(bad_list))
            .then(pl.lit(1))
            .when(target_str.is_in(good_list))
            .then(pl.lit(0))
            .otherwise(pl.lit(None))
            .alias("_y_binary")
        )["_y_binary"].drop_nulls().to_numpy().astype(np.int64)

        n_bad = int(y_bin_full.sum()) if len(y_bin_full) > 0 else 0
        n_good = int(len(y_bin_full) - n_bad) if len(y_bin_full) > 0 else 0
        if n_bad == 0 and n_good == 0:
            warnings.append({
                "code": "NO_KNOWN_TARGET_VALUES",
                "message": f"Target column {target_col!r} has no rows with declared good or bad values; "
                           "all metrics are unavailable.",
            })
            return None, None, warnings
        if n_bad == 0:
            warnings.append({
                "code": "SINGLE_CLASS_ONLY_GOOD",
                "message": f"Target column {target_col!r} has no bad-class rows; "
                           "AUC and discrimination metrics are undefined.",
            })
        elif n_good == 0:
            warnings.append({
                "code": "SINGLE_CLASS_ONLY_BAD",
                "message": f"Target column {target_col!r} has no good-class rows; "
                           "AUC and discrimination metrics are undefined.",
            })
        return y_bin_full, known_mask, warnings

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_col = meta.target_column if meta is not None else ""
        good = set(str(v) for v in (meta.good_values if meta is not None else []))
        bad = set(str(v) for v in (meta.bad_values if meta is not None else []))
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

        # Detect linked artifacts
        bundle_art = next(
            (a for a in context.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )
        score_evidence_art = next(
            (a for a in context.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_SCORE_APPLICATION_EVIDENCE),
            None,
        )

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        roles_metrics: dict[str, JsonDict] = {}
        psi_data: dict[str, pl.Series] = {}
        gates: list[JsonDict] = []

        # Gate: sample presence
        role_names = {a.role for a in data_arts}
        gates.append({
            "code": "TRAIN_SAMPLE_PRESENT",
            "status": "pass",
        })
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
            df = pl.read_parquet(store.artifact_path(data_art))  # cardre-allow-artifact-read: dataset-frame-input
            n = df.height

            if "predicted_bad_probability" not in df.columns:
                roles_metrics[role] = {
                    "row_count": n,
                    "error": "Missing predicted_bad_probability",
                }
                if fail_on_missing_score:
                    gates.append({
                        "code": "NO_MISSING_SCORE",
                        "status": "fail",
                        "message": f"Role {role!r} missing predicted_bad_probability",
                    })
                continue

            y_bin, known_mask, warnings = self._derive_y_bin(df, target_col, good, bad)
            y_prob_all = df["predicted_bad_probability"].to_numpy()
            has_score = "score" in df.columns
            scores_series_all = df["score"] if has_score else df["predicted_bad_probability"]

            if y_bin is None:
                roles_metrics[role] = {
                    "row_count": n,
                    "warnings": warnings,
                }
                if fail_on_missing_target:
                    gates.append({
                        "code": "TARGET_AVAILABLE",
                        "status": "fail",
                        "message": f"Role {role!r}: target column not available",
                    })
                continue

            # Filter probability, scores, and KS dataframe to known rows only
            # so that y_bin, y_prob, and scores are aligned.
            y_prob = y_prob_all[known_mask]
            scores = scores_series_all.to_numpy()[known_mask]
            scores_series = pl.Series(scores)

            n_bad = int(sum(y_bin))
            n_good = int(len(y_bin) - n_bad)

            # Known-rows dataframe for KS and calibration (excludes unknown targets)
            all_known_list = list(good | bad)
            df_known = df.filter(
                pl.col(target_col).cast(pl.String).is_in(all_known_list)
            )

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
                    ks_at = float(ks_df.filter(pl.col("ks_val") == ks_max).select("ks_at").item())

                calib = self._calibration(df_known, target_col, bad_list, 10)
                score_dist = self._score_distribution(scores)
                if include_calibration_display:
                    prob_true, prob_pred = calibration_curve(
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

            at_cutoffs: dict[str, dict] = {}
            for cutoff in cutoffs:
                y_pred = (y_prob >= cutoff).astype(int)
                tn, fp, fn, tp = confusion_matrix(y_bin, y_pred, labels=[0, 1]).ravel()
                accuracy = round((tp + tn) / n, 6) if n > 0 else 0.0
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
                "ks_at_score": round(ks_at, 2) if ks_val else None,
                "calibration": calib,
                "calibration_display": calib_display,
                "score_distribution": score_dist,
                "at_cutoffs": at_cutoffs,
                "warnings": warnings,
            }
            psi_data[role] = scores_series

        # Stability (PSI)
        stability: JsonDict = {
            "psi_train_vs_test": None,
            "psi_train_vs_oot": None,
        }
        if "train" in psi_data and "test" in psi_data:
            stability["psi_train_vs_test"] = self._psi(psi_data["train"], psi_data["test"])
        if "train" in psi_data and "oot" in psi_data:
            stability["psi_train_vs_oot"] = self._psi(psi_data["train"], psi_data["oot"])

        # Gate: AUC threshold
        if minimum_auc is not None:
            for role_name, rm in roles_metrics.items():
                role_auc = rm.get("auc")
                if role_auc is not None and role_auc < minimum_auc:
                    gates.append({
                        "code": f"MINIMUM_AUC_{role_name.upper()}",
                        "status": "fail",
                        "message": f"AUC ({role_auc}) below minimum ({minimum_auc}) for role {role_name!r}",
                    })

        # Gate: PSI threshold
        if maximum_psi is not None:
            for key in ("psi_train_vs_test", "psi_train_vs_oot"):
                val = stability.get(key)
                if val is not None and val > maximum_psi:
                    gates.append({
                        "code": f"MAXIMUM_PSI_{key.upper()}",
                        "status": "fail",
                        "message": f"PSI ({val}) exceeds maximum ({maximum_psi}) for {key}",
                    })

        # Build payload
        target_payload: JsonDict = {
            "target_column": target_col,
            "good_values": [str(v) for v in good],
            "bad_values": [str(v) for v in bad],
        }

        payload: JsonDict = {
            "schema_version": SCHEMA_VALIDATION_EVIDENCE,
            "target": target_payload,
            "roles": roles_metrics,
            "stability": stability,
            "gates": gates,
            "warnings": [],
        }
        if bundle_art is not None:
            payload["frozen_bundle_artifact_id"] = bundle_art.artifact_id
        if score_evidence_art is not None:
            payload["score_application_evidence_artifact_id"] = score_evidence_art.artifact_id

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"validation-metrics-{context.step_spec.step_id}",
            payload=payload,
            metadata={"schema_version": SCHEMA_VALIDATION_EVIDENCE},
        )
        return NodeOutput(artifacts=[art], metrics={"role_count": len(data_arts)})

    def _calibration(
        self, df: pl.DataFrame, target_col: str, bad_list: list[str], n_bins: int = 10,
    ) -> dict:
        calib_df = df.with_columns(
            pl.col("predicted_bad_probability").qcut(n_bins, allow_duplicates=True).alias("_calib_bin"),
            pl.when(pl.col(target_col).cast(pl.String).is_in(bad_list))
            .then(pl.lit(1)).otherwise(pl.lit(0)).alias("_y_binary"),
        ).group_by("_calib_bin", maintain_order=True).agg([
            pl.len().alias("count"),
            pl.col("predicted_bad_probability").mean().alias("avg_predicted_probability"),
            pl.col("_y_binary").mean().alias("actual_bad_rate"),
        ]).with_columns(
            pl.col("avg_predicted_probability").round(6),
            pl.col("actual_bad_rate").round(6),
        )

        bins = []
        for row in calib_df.iter_rows():
            bins.append({
                "bin": len(bins),
                "count": row[1],
                "avg_predicted_probability": row[2],
                "actual_bad_rate": row[3],
            })
        return {"bins": bins}

    def _score_distribution(self, scores: np.ndarray) -> dict:
        return {
            "mean": round(float(np.mean(scores)), 2),
            "median": round(float(np.median(scores)), 2),
            "min": round(float(np.min(scores)), 2),
            "max": round(float(np.max(scores)), 2),
            "std": round(float(np.std(scores)), 2),
            "p5": round(float(np.percentile(scores, 5)), 2),
            "p25": round(float(np.percentile(scores, 25)), 2),
            "p75": round(float(np.percentile(scores, 75)), 2),
            "p95": round(float(np.percentile(scores, 95)), 2),
        }

    def _psi(self, expected: pl.Series, actual: pl.Series, n_bins: int = 10) -> float:
        if expected.is_empty() or actual.is_empty():
            return 0.0

        expected_arr = expected.to_numpy()
        actual_arr = actual.to_numpy()
        bin_edges = np.percentile(expected_arr, [i * 100 / n_bins for i in range(1, n_bins)])
        bin_edges = np.unique(bin_edges)
        if len(bin_edges) <= 1:
            expected_counts = np.array([len(expected_arr)])
            actual_counts = np.array([len(actual_arr)])
        else:
            extended_edges = np.concatenate([[-np.inf], bin_edges, [np.inf]])
            expected_counts = np.histogram(expected_arr, bins=extended_edges)[0]
            actual_counts = np.histogram(actual_arr, bins=extended_edges)[0]

        psi = 0.0
        n_exp = len(expected_arr)
        n_act = len(actual_arr)
        for ec, ac in zip(expected_counts, actual_counts):
            ep = ec / n_exp
            ap = ac / n_act
            if ap == 0 or ep == 0:
                continue
            psi += (ap - ep) * np.log(ap / ep)
        return round(float(psi), 6)


class ThresholdOptimizationNode(NodeType):
    """Optimize classification threshold using multiple objectives.

    Evaluates thresholds across the full probability range and selects
    the best threshold for each objective: Youden index (J), max F1,
    max G-Mean, and custom cost minimization.

    Emits a policy artifact that can be consumed by downstream decision
    nodes. Does not overwrite model probabilities.
    """

    node_type = "cardre.threshold_optimization"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["report"]

    OBJECTIVES = {"youden", "max_f1", "max_g_mean", "cost_minimize"}

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Threshold optimization",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="objective",
                            label="Objective",
                            kind="enum",
                            default="youden",
                            constraint=ParameterConstraint(
                                enum_values=["youden", "max_f1", "max_g_mean", "cost_minimize"],
                            ),
                            help_text="Optimization objective for threshold selection.",
                        ),
                        ParameterDefinition(
                            name="n_thresholds",
                            label="Number of thresholds",
                            kind="integer",
                            default=200,
                            constraint=ParameterConstraint(min_value=10),
                            help_text="Number of evenly-spaced threshold candidates to evaluate.",
                        ),
                        ParameterDefinition(
                            name="cost_fp",
                            label="False positive cost",
                            kind="float",
                            default=1.0,
                            constraint=ParameterConstraint(min_value=0.0),
                            help_text="Cost of a false positive (used with cost_minimize objective).",
                        ),
                        ParameterDefinition(
                            name="cost_fn",
                            label="False negative cost",
                            kind="float",
                            default=10.0,
                            constraint=ParameterConstraint(min_value=0.0),
                            help_text="Cost of a false negative (used with cost_minimize objective).",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        objective = params.get("objective", "youden")
        if objective not in self.OBJECTIVES:
            errors.append(f"objective must be one of {sorted(self.OBJECTIVES)}, got {objective!r}")

        n_thresholds = params.get("n_thresholds", 200)
        try:
            if int(n_thresholds) < 10:
                errors.append("n_thresholds must be >= 10")
        except (ValueError, TypeError):
            errors.append("n_thresholds must be an integer")

        cost_fp = params.get("cost_fp")
        cost_fn = params.get("cost_fn")
        if objective == "cost_minimize":
            if cost_fp is None or cost_fn is None:
                errors.append("cost_fp and cost_fn are required for cost_minimize objective")
            else:
                try:
                    float(cost_fp)
                    float(cost_fn)
                except (ValueError, TypeError):
                    errors.append("cost_fp and cost_fn must be numbers")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        reader = ArtifactEvidenceReader(store)
        objective = params.get("objective", "youden")
        n_thresholds = int(params.get("n_thresholds", 200))
        cost_fp = float(params.get("cost_fp", 1.0))
        cost_fn = float(params.get("cost_fn", 10.0))

        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_col = meta.target_column if meta is not None else ""
        bad = set(str(v) for v in (meta.bad_values if meta is not None else []))
        bad_list = list(bad)

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        report: dict = {"objective": objective, "cost_fp": cost_fp, "cost_fn": cost_fn, "roles": {}}

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))  # cardre-allow-artifact-read: dataset-frame-input

            if "predicted_bad_probability" not in df.columns:
                report["roles"][role] = {"error": "Missing predicted_bad_probability"}
                continue

            y_prob = df["predicted_bad_probability"].to_numpy()
            if target_col and target_col in df.columns and bad:
                y_bin = df[target_col].cast(pl.String).is_in(bad_list).cast(pl.Int64).to_numpy()
            else:
                y_bin = np.zeros(df.height, dtype=np.int64)

            n_bad = int(y_bin.sum())
            n_good = len(y_bin) - n_bad
            if n_bad == 0 or n_good == 0:
                report["roles"][role] = {"error": "Single class; threshold optimization skipped"}
                continue

            thresholds = np.linspace(0.0, 1.0, n_thresholds)
            y_pred_matrix = (y_prob[:, None] >= thresholds[None, :]).astype(int)
            tp = np.sum((y_bin[:, None] == 1) & (y_pred_matrix == 1), axis=0)
            tn = np.sum((y_bin[:, None] == 0) & (y_pred_matrix == 0), axis=0)
            fp = np.sum((y_bin[:, None] == 0) & (y_pred_matrix == 1), axis=0)
            fn = np.sum((y_bin[:, None] == 1) & (y_pred_matrix == 0), axis=0)

            denom_tp_fn = tp + fn
            denom_tn_fp = tn + fp
            recall = np.divide(tp, denom_tp_fn, where=denom_tp_fn > 0, out=np.zeros_like(tp, dtype=float))
            specificity = np.divide(tn, denom_tn_fp, where=denom_tn_fp > 0, out=np.zeros_like(tn, dtype=float))
            precision = np.divide(tp, tp + fp, where=(tp + fp) > 0, out=np.zeros_like(tp, dtype=float))
            denom_f1 = precision + recall
            f1 = np.divide(2 * precision * recall, denom_f1, where=denom_f1 > 0, out=np.zeros_like(precision, dtype=float))
            g_mean = np.sqrt(recall * specificity)
            cost = cost_fp * fp + cost_fn * fn
            j = recall + specificity - 1.0

            if objective == "youden":
                scores = j
            elif objective == "max_f1":
                scores = f1
            elif objective == "max_g_mean":
                scores = g_mean
            elif objective == "cost_minimize":
                scores = -cost.astype(float)
            else:
                scores = np.zeros(n_thresholds)

            best_idx = int(np.argmax(scores))
            best = {
                "threshold": round(float(thresholds[best_idx]), 6),
                "objective_value": round(float(scores[best_idx]), 6),
                "detail": {
                    "recall": round(float(recall[best_idx]), 6),
                    "specificity": round(float(specificity[best_idx]), 6),
                    "precision": round(float(precision[best_idx]), 6),
                    "f1": round(float(f1[best_idx]), 6),
                    "g_mean": round(float(g_mean[best_idx]), 6),
                    "cost": round(float(cost[best_idx]), 6),
                    "youden_j": round(float(j[best_idx]), 6),
                },
            }

            report["roles"][role] = best

        selected_threshold = 0.5
        for role_priority in ["test", "train", "oot"]:
            role_data = report["roles"].get(role_priority, {})
            if "threshold" in role_data:
                selected_threshold = role_data["threshold"]
                break

        report["selected_threshold"] = selected_threshold

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"threshold-optimization-{context.step_spec.step_id}",
            payload=report,
            metadata={"objective": objective, "selected_threshold": selected_threshold},
        )
        return NodeOutput(
            artifacts=[art],
            metrics={"selected_threshold": selected_threshold})

class CutoffAnalysisNode(NodeType):
    node_type = "cardre.cutoff_analysis"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Cutoff Analysis",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Analyse approval rate, bad rate, and capture rate across score bands / cutoffs.",
                    params=[
                        ParameterDefinition(
                            name="band_count",
                            label="Band Count",
                            kind="integer",
                            default=20,
                            help_text="Number of equal-width score bands to divide the score range into (used when cutoffs is empty).",
                            constraint=ParameterConstraint(min_value=2),
                        ),
                        ParameterDefinition(
                            name="cutoffs",
                            label="Cutoffs",
                            kind="list",
                            default=[],
                            help_text="Explicit list of score cutoffs (overrides band_count when non-empty).",
                        ),
                    ],
                ),
            ],
            default_method="default",
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        band_count = params.get("band_count", 20)
        try:
            if int(band_count) < 2:
                errors.append("band_count must be at least 2")
        except (ValueError, TypeError):
            errors.append("band_count must be an integer")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        reader = ArtifactEvidenceReader(store)
        band_count = int(params.get("band_count", 20))
        cutoffs = list(params.get("cutoffs", []))

        if band_count < 2:
            raise ValueError(f"band_count must be at least 2, got {band_count}")

        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_col = meta.target_column if meta is not None else ""
        good = set(str(v) for v in (meta.good_values if meta is not None else []))
        bad = set(str(v) for v in (meta.bad_values if meta is not None else []))
        bad_list = list(bad)

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        cutoff_tables: dict[str, list[JsonDict]] = {}
        warnings: list[JsonDict] = []

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))  # cardre-allow-artifact-read: dataset-frame-input
            if "score" not in df.columns or "predicted_bad_probability" not in df.columns:
                continue

            score_series = df["score"]
            if score_series.n_unique() < 2:
                raise ValueError(f"Score column has zero variance in role {role!r}")

            min_s = score_series.min()
            max_s = score_series.max()

            if cutoffs:
                band_breaks = sorted(float(c) for c in cutoffs if isinstance(c, (int, float)))
            else:
                step = (max_s - min_s) / band_count
                band_breaks = [min_s + i * step for i in range(1, band_count)]

            has_target = target_col and target_col in df.columns
            if has_target and good and bad:
                y_bin_expr = pl.when(pl.col(target_col).cast(pl.String).is_in(bad_list)).then(1).otherwise(0)
            else:
                if not has_target:
                    warnings.append({
                        "role": role, "code": "MISSING_TARGET_COLUMN",
                        "message": f"Target column {target_col!r} not found in role {role!r}; "
                                   "bad rate and capture rate are not meaningful.",
                    })
                elif not good and not bad:
                    warnings.append({
                        "role": role, "code": "MISSING_TARGET_METADATA",
                        "message": "No good_values/bad_values in definition artifact; "
                                   "bad rate and capture rate are not meaningful.",
                    })
                y_bin_expr = pl.lit(0)
                has_target = False

            band_cuts = [float("-inf")] + band_breaks + [float("inf")]
            binned = df.with_columns(
                y_bin_expr.alias("_y_binary"),
                pl.col("score").cut(band_breaks, include_breaks=True).alias("_band"),
            )
            total_bad = binned.select(pl.sum("_y_binary")).item()
            total_n = binned.height

            grouped = binned.with_columns([
                binned["_band"].struct.field("breakpoint").alias("_brk"),
            ]).group_by("_brk", maintain_order=True).agg([
                pl.len().alias("count"),
                pl.sum("_y_binary").alias("bad_count"),
            ]).sort("_brk")

            band_results: list[JsonDict] = []
            for i, row in enumerate(grouped.iter_rows()):
                brk, cnt, bc = row[0], row[1], row[2]
                band_results.append({
                    "band": i + 1,
                    "lower": round(float(band_cuts[i]), 2) if band_cuts[i] != float("-inf") else None,
                    "upper": round(float(brk), 2) if brk != float("inf") else None,
                    "count": cnt,
                    "bad_count": bc,
                    "approval_rate": round(1 - cnt / total_n, 4),
                    "bad_rate": round(bc / cnt, 4) if cnt > 0 else 0,
                    "capture_rate": round(bc / total_bad, 4) if total_bad > 0 else 0,
                })

            cutoff_tables[role] = [
                {
                    "score_cutoff": b["upper"] if b["upper"] is not None else b["lower"],
                    "approval_rate": b["approval_rate"],
                    "bad_rate": b["bad_rate"],
                    "capture_rate": b["capture_rate"],
                }
                for b in band_results
            ]

        payload: JsonDict = {
            "schema_version": SCHEMA_CUTOFF_ANALYSIS,
            "cutoff_tables": cutoff_tables,
        }
        if warnings:
            payload["warnings"] = warnings
        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"cutoff-analysis-{context.step_spec.step_id}",
            payload=payload,
            metadata={"schema_version": SCHEMA_CUTOFF_ANALYSIS},
        )
        return NodeOutput(artifacts=[art], metrics={"role_count": len(data_arts)})
