from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, JsonDict, NodeOutput, NodeType
from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_CUTOFF_ANALYSIS,
    SCHEMA_VALIDATION_METRICS,
)


class ValidationMetricsNode(NodeType):
    node_type = "cardre.validation_metrics"
    version = "2"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["report"]

    def _derive_y_bin(
        self, df: pl.DataFrame, target_col: str, good: set[str], bad: set[str],
    ) -> tuple[np.ndarray | None, list[dict]]:
        warnings: list[dict] = []
        if not target_col or target_col not in df.columns:
            warnings.append({
                "code": "MISSING_TARGET_COLUMN",
                "message": f"Target column {target_col!r} not found; "
                           "all metrics except row count are unavailable.",
            })
            return None, warnings
        if not good and not bad:
            warnings.append({
                "code": "MISSING_TARGET_METADATA",
                "message": "No good_values/bad_values in definition artifact; "
                           "all metrics except row count are unavailable.",
            })
            return None, warnings

        bad_list = list(bad)
        y_bin = (df.with_columns(
            pl.when(pl.col(target_col).cast(pl.String).is_in(bad_list))
            .then(pl.lit(1)).otherwise(pl.lit(0)).alias("_y_binary")
        )["_y_binary"].to_numpy())
        n_bad = sum(y_bin)
        n_good = len(y_bin) - n_bad
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
        return y_bin, warnings

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_col = meta.target_column if meta is not None else ""
        good = set(str(v) for v in (meta.good_values if meta is not None else []))
        bad = set(str(v) for v in (meta.bad_values if meta is not None else []))
        bad_list = list(bad)

        cutoffs = list(context.validated_params.get("cutoffs", [0.5]))
        include_calibration_display = context.validated_params.get("include_calibration_display", False)

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        metrics_report: dict = {}
        psi_data: dict[str, pl.Series] = {}

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))
            n = df.height

            if "predicted_bad_probability" not in df.columns:
                metrics_report[role] = {"row_count": n, "error": "Missing predicted_bad_probability"}
                continue

            y_bin, warnings = self._derive_y_bin(df, target_col, good, bad)
            y_prob = df["predicted_bad_probability"].to_numpy()
            has_score = "score" in df.columns
            scores_series = df["score"] if has_score else df["predicted_bad_probability"]
            scores = scores_series.to_numpy()

            if y_bin is None:
                metrics_report[role] = {
                    "row_count": n,
                    "warnings": warnings,
                }
                continue

            n_bad = sum(y_bin)
            n_good = n - n_bad

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

                ks_df = df.with_columns(
                    pl.when(pl.col(target_col).cast(pl.String).is_in(bad_list))
                    .then(pl.lit(1)).otherwise(pl.lit(0)).alias("_y_binary")
                ).sort("score").with_columns(
                    (pl.lit(1) - pl.col("_y_binary")).cum_sum().alias("_cum_good"),
                    pl.col("_y_binary").cum_sum().alias("_cum_bad"),
                ).select(
                    (pl.col("_cum_good") / n_good - pl.col("_cum_bad") / n_bad).abs().alias("ks_val"),
                    pl.col("score").alias("ks_at"),
                )
                ks_max = ks_df.select(pl.max("ks_val")).item()
                if ks_max is not None:
                    ks_val = round(float(ks_max), 6)
                    ks_at = float(ks_df.filter(pl.col("ks_val") == ks_max).select("ks_at").item())

                calib = self._calibration(df, target_col, bad_list, 10)
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

            metrics_report[role] = {
                "row_count": n,
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

        if "train" in psi_data and "test" in psi_data:
            metrics_report.setdefault("psi", {})["train_vs_test"] = self._psi(psi_data["train"], psi_data["test"])
        if "train" in psi_data and "oot" in psi_data:
            metrics_report.setdefault("psi", {})["train_vs_oot"] = self._psi(psi_data["train"], psi_data["oot"])

        metrics_report["schema_version"] = SCHEMA_VALIDATION_METRICS
        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"validation-metrics-{context.step_spec.step_id}",
            payload=metrics_report,
            metadata={"schema_version": SCHEMA_VALIDATION_METRICS},
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
            expected_counts = np.histogram(expected_arr, bins=bin_edges)[0]
            actual_counts = np.histogram(actual_arr, bins=bin_edges)[0]

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
            df = pl.read_parquet(store.artifact_path(data_art))

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
            df = pl.read_parquet(store.artifact_path(data_art))
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
