from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl
from sklearn.metrics import roc_auc_score

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ExecutionContext,
    JsonDict,
    NodeOutput,
    NodeType,
)
from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_CUTOFF_ANALYSIS,
    SCHEMA_VALIDATION_METRICS,
    SCHEMA_WOE_TABLE,
)



class ApplyWoeMappingNode(NodeType):
    node_type = "cardre.apply_woe_mapping"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition", "report"]
    output_roles: list[str] = ["train", "test", "oot"]

    VALID_UNMATCHED_POLICIES = {"fill_zero", "warn", "fail"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        policy = params.get("woe_unmatched_policy", "warn")
        if policy not in self.VALID_UNMATCHED_POLICIES:
            errors.append(
                f"woe_unmatched_policy must be one of {self.VALID_UNMATCHED_POLICIES}, got {policy!r}"
            )
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        import math

        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        woe_unmatched_policy = params.get("woe_unmatched_policy", "warn")

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)
        sel_def = reader.find_optional(context.input_artifacts, EvidenceKind.SELECTION_DEFINITION)

        selected_names: set[str] | None = None
        if sel_def is not None:
            selected_names = sel_def.selected_names

        woe_map = woe_table.mapping

        var_defs = bin_def.variables
        if selected_names is not None:
            var_defs = [v for v in var_defs if v.variable in selected_names]

        fallback_report: dict[str, dict] = {}
        outputs: list[ArtifactRef] = []
        unmatched_total = 0

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role
            fallback_counts: dict[str, int] = {}

            for vd in var_defs:
                var = vd.variable
                kind = vd.kind
                bins = vd.bins
                if var not in df.columns:
                    continue
                woe_col = f"{var}_woe"
                woe_expr = None

                for be in bins:
                    bid = be["bin_id"]
                    is_miss = be.get("is_missing_bin", False)
                    if kind == "numeric":
                        lo = be.get("lower"); hi = be.get("upper")
                        li = be.get("lower_inclusive", False); ui = be.get("upper_inclusive", True)
                        if is_miss:
                            mask = pl.col(var).is_null()
                        else:
                            parts = []
                            c2 = pl.col(var)
                            if lo is not None:
                                parts.append((c2 >= lo) if li else (c2 > lo))
                            if hi is not None:
                                parts.append((c2 <= hi) if ui else (c2 < hi))
                            mask = parts[0]
                            for p in parts[1:]:
                                mask = mask & p
                    else:
                        cats = be.get("categories", [])
                        if is_miss:
                            mask = pl.col(var).is_null()
                        elif be.get("is_other_bin", False):
                            explicit_cats = []
                            for bd in bins:
                                if bd.get("is_missing_bin", False) or bd.get("is_other_bin", False):
                                    continue
                                explicit_cats.extend(bd.get("categories") or [])
                            mask = pl.col(var).is_not_null() & ~pl.col(var).is_in(explicit_cats)
                        elif cats:
                            mask = pl.col(var).is_in(cats)
                        else:
                            mask = pl.lit(False)

                    wv = woe_map.get(var, {}).get(bid)
                    if wv is None:
                        raise ValueError(f"apply_woe_mapping: missing WOE for {var}:{bid}")
                    wc = pl.when(mask).then(pl.lit(wv))
                    woe_expr = wc if woe_expr is None else woe_expr.when(mask).then(pl.lit(wv))

                if woe_expr is not None:
                    woe_expr = woe_expr.otherwise(pl.lit(None, dtype=pl.Float64))
                    df = df.with_columns(woe_expr.alias(woe_col))
                    n_unmatched = df.filter(pl.col(woe_col).is_null()).height
                    if n_unmatched > 0:
                        fallback_counts[var] = n_unmatched
                        unmatched_total += n_unmatched
                        if woe_unmatched_policy == "fail":
                            raise ValueError(
                                f"apply_woe_mapping: {n_unmatched} rows in role={role!r} "
                                f"variable={var!r} did not match any bin"
                            )
                        df = df.with_columns(pl.col(woe_col).fill_null(0.0))

            fallback_report[role] = fallback_counts
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"woe-apply-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata={"source_id": data_art.artifact_id},
            )
            outputs.append(art)

        fallback_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-apply-fallback-{context.step_spec.step_id}",
            payload=fallback_report,
            metadata={},
        )

        all_artifacts = outputs + [fallback_art]
        return NodeOutput(
            artifacts=all_artifacts,
            metrics={
                "output_count": len(outputs),
                "unmatched_row_count": unmatched_total,
                "woe_unmatched_policy": woe_unmatched_policy,
            })


class ApplyModelNode(NodeType):
    node_type = "cardre.apply_model"
    version = "2"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "model", "scorecard"]
    output_roles: list[str] = ["train", "test", "oot"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        import numpy as np

        store = context.store
        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
        scorecard_art = next((a for a in context.input_artifacts if a.role == "scorecard"), None)
        if model_art is None:
            raise ValueError("apply_model requires a model artifact")

        model = json.loads(store.artifact_path(model_art).read_text())

        model_family = model.get("model_family", "logistic_regression")
        if model_family == "logistic_regression":
            return self._apply_logistic(context, model, model_art, scorecard_art)
        elif model_family in (
            "decision_tree", "random_forest", "gbdt",
            "xgboost", "lightgbm", "catboost",
        ):
            return self._apply_sklearn_estimator(context, model, model_art, scorecard_art)
        elif model_family in ("voting_ensemble", "weighted_ensemble"):
            return self._apply_voting_weighted_ensemble(context, model, model_art)
        else:
            raise ValueError(
                f"apply_model: unsupported model_family {model_family!r}. "
                f"Supported families: logistic_regression, decision_tree, random_forest, "
                f"gbdt, xgboost, lightgbm, catboost, voting_ensemble, weighted_ensemble"
            )

    def _apply_logistic(
        self, context: ExecutionContext, model: dict, model_art, scorecard_art,
    ) -> NodeOutput:
        import numpy as np

        store = context.store

        features = model.get("features", [])
        intercept = float(model.get("intercept", 0))
        coefficients = model.get("coefficients", {})

        prob_col_idx = model.get("probability_column_index", 1)

        if scorecard_art is not None:
            scorecard = json.loads(store.artifact_path(scorecard_art).read_text())
            offset = float(scorecard.get("offset", 0))
            factor = float(scorecard.get("factor", 1))
            direction = -1.0 if scorecard.get("higher_score_is_lower_risk", True) else 1.0
            has_scorecard = True
        else:
            offset = 0.0
            factor = 1.0
            direction = -1.0
            has_scorecard = False

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        outputs = []

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role
            missing = [f for f in features if f not in df.columns]
            if missing:
                raise ValueError(
                    f"apply_model: role {role!r} missing features {missing}"
                )

            feature_arr = df.select(features).to_numpy()
            log_odds = np.full(feature_arr.shape[0], intercept, dtype=np.float64)
            for i, feat in enumerate(features):
                log_odds += float(coefficients.get(feat, 0)) * feature_arr[:, i]

            pred_bad = 1.0 / (1.0 + np.exp(-log_odds))

            columns_to_add = [
                pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
                pl.Series("raw_model_output", log_odds, dtype=pl.Float64),
                pl.lit(model_art.artifact_id).alias("model_artifact_id"),
                pl.lit("logistic_regression").alias("model_family"),
            ]

            if has_scorecard:
                score_vals = offset + direction * factor * log_odds
                columns_to_add.append(pl.Series("score", score_vals, dtype=pl.Float64))
                columns_to_add.append(pl.Series("cardre_scaled_score", score_vals, dtype=pl.Float64))

            df = df.with_columns(columns_to_add)
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"scored-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata={"model_artifact_id": model_art.artifact_id},
            )
            outputs.append(art)

        return NodeOutput(artifacts=outputs, metrics={"output_count": len(outputs)})

    def _apply_sklearn_estimator(
        self, context: ExecutionContext, model: dict, model_art, scorecard_art,
    ) -> NodeOutput:
        import numpy as np

        store = context.store

        estimator_ref = model.get("estimator_reference", {})
        estimator_artifact_id = estimator_ref.get("artifact_id", "")

        feature_contract = model.get("feature_contract", {})
        features = feature_contract.get("features", [])
        if not features:
            features = model.get("features", [])

        prob_col_idx = model.get("probability_column_index", 1)

        scorecard = None
        if scorecard_art is not None:
            scorecard = json.loads(store.artifact_path(scorecard_art).read_text())

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        outputs = []

        if not estimator_artifact_id:
            raise ValueError(
                "apply_model: non-logistic model requires estimator_reference.artifact_id"
            )

        estimator_art = store.get_artifact(estimator_artifact_id)
        if estimator_art is None:
            raise ValueError(
                f"apply_model: estimator artifact {estimator_artifact_id!r} not found"
            )

        from cardre.modeling.serialization import read_estimator_artifact
        estimator_bytes = read_estimator_artifact(
            store, estimator_art,
            expected_logical_hash=estimator_ref.get("logical_hash"),
        )

        import io
        import joblib
        estimator = joblib.load(io.BytesIO(estimator_bytes))

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role
            missing = [f for f in features if f not in df.columns]
            if missing:
                raise ValueError(
                    f"apply_model: role {role!r} missing features {missing}"
                )

            X = df.select(features).to_numpy()

            if hasattr(estimator, "predict_proba"):
                proba = estimator.predict_proba(X)
                if proba.shape[1] > prob_col_idx:
                    pred_bad = proba[:, prob_col_idx]
                else:
                    pred_bad = proba[:, -1]
            else:
                raw_output = estimator.predict(X)
                pred_bad = raw_output.astype(np.float64)

            columns_to_add = [
                pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
                pl.lit(model_art.artifact_id).alias("model_artifact_id"),
                pl.lit(model.get("model_family", "unknown")).alias("model_family"),
            ]

            if scorecard is not None:
                offset = float(scorecard.get("offset", 0))
                factor = float(scorecard.get("factor", 1))
                higher_is_lower = scorecard.get("higher_score_is_lower_risk", True)
                direction = -1.0 if higher_is_lower else 1.0
                log_odds = np.log(np.clip(pred_bad / np.maximum(1 - pred_bad, 1e-15), 1e-15, None))
                score_vals = offset + direction * factor * log_odds
                columns_to_add.append(pl.Series("score", score_vals, dtype=pl.Float64))
                columns_to_add.append(pl.Series("cardre_scaled_score", score_vals, dtype=pl.Float64))

            df = df.with_columns(columns_to_add)
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"scored-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata={"model_artifact_id": model_art.artifact_id},
            )
            outputs.append(art)

        return NodeOutput(artifacts=outputs, metrics={"output_count": len(outputs)})

    def _apply_voting_weighted_ensemble(
        self, context: ExecutionContext, model: dict, model_art,
    ) -> NodeOutput:
        import json
        import numpy as np

        store = context.store
        model_payload = model.get("model_payload", {})
        base_models = model_payload.get("base_models", [])
        ensemble_type = model_payload.get("ensemble_type", "voting")
        weights_list = model_payload.get("weights", None)
        voting = model_payload.get("voting", "soft")
        threshold = model_payload.get("threshold", 0.5)

        features = model.get("features", [])
        prob_col_idx = model.get("probability_column_index", 1)

        # Load base model artifacts and their features
        base_artifacts = []
        for bm in base_models:
            aid = bm.get("artifact_id", "")
            if not aid:
                continue
            art = store.get_artifact(aid)
            if art is None:
                continue
            try:
                base_artifacts.append(json.loads(store.artifact_path(art).read_text()))
            except Exception:
                continue

        if not base_artifacts:
            raise ValueError("No base model artifacts could be loaded for ensemble apply")

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        outputs = []

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role

            all_probs = []
            for bm_art in base_artifacts:
                bm_art_features = bm_art.get("features", [])
                bm_features = bm_art.get("feature_contract", {}).get("features", []) or bm_art_features
                missing = [f for f in bm_features if f not in df.columns]
                if missing:
                    raise ValueError(
                        f"apply_model: ensemble base model role {role!r} missing features {missing}"
                    )

                bm_family = bm_art.get("model_family", "")
                bm_prob_col = bm_art.get("probability_column_index", 1)

                if bm_family == "logistic_regression":
                    coefs = bm_art.get("coefficients", {})
                    intercept = float(bm_art.get("intercept", 0))
                    X = df.select(bm_features).to_numpy()
                    log_odds = np.full(X.shape[0], intercept, dtype=np.float64)
                    for i, feat in enumerate(bm_features):
                        log_odds += float(coefs.get(feat, 0)) * X[:, i]
                    probs = 1.0 / (1.0 + np.exp(-log_odds))
                else:
                    estimator_ref = bm_art.get("estimator_reference", {})
                    estimator_art_id = estimator_ref.get("artifact_id", "")
                    if not estimator_art_id:
                        raise ValueError("Ensemble base model missing estimator_reference")
                    est_art = store.get_artifact(estimator_art_id)
                    if est_art is None:
                        raise ValueError(f"Base model estimator artifact {estimator_art_id!r} not found")
                    from cardre.modeling.serialization import read_estimator_artifact
                    import joblib
                    import io
                    est_bytes = read_estimator_artifact(
                        store, est_art,
                        expected_logical_hash=estimator_ref.get("logical_hash"),
                    )
                    estimator = joblib.load(io.BytesIO(est_bytes))
                    X = df.select(bm_features).to_numpy()
                    if hasattr(estimator, "predict_proba"):
                        proba = estimator.predict_proba(X)
                        if proba.shape[1] > bm_prob_col:
                            probs = proba[:, bm_prob_col]
                        else:
                            probs = proba[:, -1]
                    else:
                        probs = estimator.predict(X).astype(np.float64)
                all_probs.append(probs)

            prob_matrix = np.column_stack(all_probs)

            if ensemble_type == "weighted" and weights_list:
                weights = np.array(weights_list, dtype=np.float64)
                pred_bad = prob_matrix @ weights
            elif voting == "soft":
                pred_bad = np.mean(prob_matrix, axis=1)
            else:
                predictions = (prob_matrix >= threshold).astype(int)
                pred_bad = (np.sum(predictions, axis=1) > (len(base_artifacts) / 2)).astype(float)

            columns_to_add = [
                pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
                pl.lit(model_art.artifact_id).alias("model_artifact_id"),
                pl.lit(model.get("model_family", "unknown")).alias("model_family"),
            ]
            df = df.with_columns(columns_to_add)
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"scored-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata={"model_artifact_id": model_art.artifact_id},
            )
            outputs.append(art)

        return NodeOutput(artifacts=outputs, metrics={"output_count": len(outputs)})


class ValidationMetricsNode(NodeType):
    node_type = "cardre.validation_metrics"
    version = "2"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["report"]

    def _derive_y_bin(
        self, df: pl.DataFrame, target_col: str, good: set[str], bad: set[str],
    ) -> tuple[list[int] | None, list[dict]]:
        """Derive binary target from definition metadata; never from predictions.

        Returns (y_bin or None if target is unavailable, warnings).
        """
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

        y_raw = df[target_col].cast(pl.String).to_list()
        y_bin = [1 if str(v) in bad else 0 for v in y_raw]
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
        from sklearn.metrics import (
            confusion_matrix,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )
        import numpy as np

        store = context.store
        meta_art = None
        for a in context.input_artifacts:
            if a.role == "definition":
                try:
                    p = json.loads(store.artifact_path(a).read_text())
                    if "target_column" in p and "good_values" in p:
                        meta_art = a
                        break
                except Exception:
                    continue

        meta = {}
        if meta_art:
            meta = json.loads(store.artifact_path(meta_art).read_text())
        target_col = meta.get("target_column", "")
        good = set(str(v) for v in meta.get("good_values", []))
        bad = set(str(v) for v in meta.get("bad_values", []))

        cutoffs = list(context.validated_params.get("cutoffs", [0.5]))

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        metrics_report: dict = {}
        psi_bins: dict[str, list[float]] = {}

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))
            n = df.height

            if "predicted_bad_probability" not in df.columns:
                metrics_report[role] = {"row_count": n, "error": "Missing predicted_bad_probability"}
                continue

            y_bin, warnings = self._derive_y_bin(df, target_col, good, bad)
            y_prob = df["predicted_bad_probability"].to_list()
            scores = df["score"].to_list() if "score" in df.columns else y_prob

            if y_bin is None:
                metrics_report[role] = {
                    "row_count": n,
                    "warnings": warnings,
                }
                continue

            n_bad = sum(y_bin)
            n_good = n - n_bad

            # Threshold-invariant metrics
            auc_val = None
            gini_val = None
            ks_val = None
            ks_at = 0.0
            calib = {}
            score_dist = {}

            if n_bad > 0 and n_good > 0:
                auc_val = round(float(roc_auc_score(y_bin, y_prob)), 6)
                gini_val = round(2 * auc_val - 1, 6)

                sorted_by_score = sorted(zip(scores, y_bin), key=lambda x: x[0])
                cum_good = 0
                cum_bad = 0
                ks = 0.0
                total_good = n_good
                total_bad = n_bad
                for sc, is_bad in sorted_by_score:
                    cum_good += (1 - is_bad)
                    cum_bad += is_bad
                    diff = abs(cum_good / total_good - cum_bad / total_bad) if total_good > 0 and total_bad > 0 else 0
                    if diff > ks:
                        ks = diff
                        ks_at = sc
                ks_val = round(ks, 6)

                calib = self._calibration(y_bin, y_prob, 10)
                score_dist = self._score_distribution(scores)
            else:
                calib = {"note": "Single class only; metrics skipped"}

            # Threshold-dependent metrics at each cutoff
            at_cutoffs: dict[str, dict] = {}
            for cutoff in cutoffs:
                y_pred = [1 if p >= cutoff else 0 for p in y_prob]
                tn, fp, fn, tp = confusion_matrix(y_bin, y_pred, labels=[0, 1]).ravel()
                accuracy = round((tp + tn) / n, 6) if n > 0 else 0.0
                precision = round(tp / (tp + fp), 6) if (tp + fp) > 0 else 0.0
                recall = round(tp / (tp + fn), 6) if (tp + fn) > 0 else 0.0  # sensitivity
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
                "score_distribution": score_dist,
                "at_cutoffs": at_cutoffs,
                "warnings": warnings,
            }
            psi_bins[role] = scores

        if "train" in psi_bins and "test" in psi_bins:
            metrics_report.setdefault("psi", {})["train_vs_test"] = self._psi(psi_bins["train"], psi_bins["test"])
        if "train" in psi_bins and "oot" in psi_bins:
            metrics_report.setdefault("psi", {})["train_vs_oot"] = self._psi(psi_bins["train"], psi_bins["oot"])

        metrics_report["schema_version"] = SCHEMA_VALIDATION_METRICS
        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"validation-metrics-{context.step_spec.step_id}",
            payload=metrics_report,
            metadata={"schema_version": SCHEMA_VALIDATION_METRICS},
        )
        return NodeOutput(artifacts=[art], metrics={"role_count": len(data_arts)})

    def _calibration(self, y_true: list[int], y_prob: list[float], n_bins: int = 10) -> dict:
        import numpy as np
        pairs = list(zip(y_prob, y_true))
        pairs.sort(key=lambda x: x[0])
        n = len(pairs)
        bins = []
        for i in range(n_bins):
            lo = i * n // n_bins
            hi = (i + 1) * n // n_bins if i < n_bins - 1 else n
            if lo >= hi:
                continue
            bin_probs = [p[0] for p in pairs[lo:hi]]
            bin_actual = [p[1] for p in pairs[lo:hi]]
            avg_pred = float(np.mean(bin_probs)) if bin_probs else 0.0
            avg_actual = float(np.mean(bin_actual)) if bin_actual else 0.0
            bins.append({
                "bin": i,
                "count": hi - lo,
                "avg_predicted_probability": round(avg_pred, 6),
                "actual_bad_rate": round(avg_actual, 6),
            })
        return {"bins": bins}

    def _score_distribution(self, scores: list[float]) -> dict:
        import numpy as np
        arr = np.array(scores)
        return {
            "mean": round(float(np.mean(arr)), 2),
            "median": round(float(np.median(arr)), 2),
            "min": round(float(np.min(arr)), 2),
            "max": round(float(np.max(arr)), 2),
            "std": round(float(np.std(arr)), 2),
            "p5": round(float(np.percentile(arr, 5)), 2),
            "p25": round(float(np.percentile(arr, 25)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
            "p95": round(float(np.percentile(arr, 95)), 2),
        }

    def _psi(self, expected: list[float], actual: list[float], n_bins: int = 10) -> float:
        import numpy as np
        if not expected or not actual:
            return 0.0
        all_vals = np.concatenate([expected, actual])
        bins = np.percentile(expected, [i * 100 / n_bins for i in range(1, n_bins)])
        bins = np.unique(bins)
        expected_counts = np.histogram(expected, bins=bins if len(bins) > 1 else 2)[0]
        actual_counts = np.histogram(actual, bins=bins if len(bins) > 1 else 2)[0]
        psi = 0.0
        for ec, ac in zip(expected_counts, actual_counts):
            ep = ec / len(expected)
            ap = ac / len(actual)
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
        import numpy as np

        store = context.store
        params = context.validated_params
        objective = params.get("objective", "youden")
        n_thresholds = int(params.get("n_thresholds", 200))
        cost_fp = float(params.get("cost_fp", 1.0))
        cost_fn = float(params.get("cost_fn", 10.0))

        meta_art = None
        for a in context.input_artifacts:
            if a.role == "definition":
                try:
                    p = json.loads(store.artifact_path(a).read_text())
                    if "target_column" in p and "good_values" in p:
                        meta_art = a
                        break
                except Exception:
                    continue

        meta = {}
        if meta_art:
            meta = json.loads(store.artifact_path(meta_art).read_text())
        target_col = meta.get("target_column", "")
        good = set(str(v) for v in meta.get("good_values", []))
        bad = set(str(v) for v in meta.get("bad_values", []))

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        report: dict = {"objective": objective, "cost_fp": cost_fp, "cost_fn": cost_fn, "roles": {}}

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))

            if "predicted_bad_probability" not in df.columns:
                report["roles"][role] = {"error": "Missing predicted_bad_probability"}
                continue

            y_prob = df["predicted_bad_probability"].to_list()
            y_bin = [0] * df.height
            if target_col and target_col in df.columns and bad:
                y_raw = df[target_col].cast(pl.String).to_list()
                y_bin = [1 if str(v) in bad else 0 for v in y_raw]

            n_bad = sum(y_bin)
            n_good = len(y_bin) - n_bad
            if n_bad == 0 or n_good == 0:
                report["roles"][role] = {"error": "Single class; threshold optimization skipped"}
                continue

            thresholds = np.linspace(0.0, 1.0, n_thresholds)
            best = {"threshold": 0.5, "objective_value": -np.inf, "detail": {}}

            for t in thresholds:
                y_pred = [1 if p >= t else 0 for p in y_prob]
                tn, fp, fn, tp = self._confusion(y_bin, y_pred)

                recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
                g_mean = (recall * specificity) ** 0.5 if recall > 0 and specificity > 0 else 0.0
                cost = cost_fp * fp + cost_fn * fn
                j = recall + specificity - 1.0

                detail = {
                    "recall": round(recall, 6),
                    "specificity": round(specificity, 6),
                    "precision": round(precision, 6),
                    "f1": round(f1, 6),
                    "g_mean": round(g_mean, 6),
                    "cost": round(cost, 6),
                    "youden_j": round(j, 6),
                }

                if objective == "youden":
                    score = j
                elif objective == "max_f1":
                    score = f1
                elif objective == "max_g_mean":
                    score = g_mean
                elif objective == "cost_minimize":
                    score = -cost  # minimize cost = maximize negative cost
                else:
                    score = 0.0

                if score > best["objective_value"]:
                    best = {"threshold": round(float(t), 6), "objective_value": round(score, 6), "detail": detail}

            report["roles"][role] = best

        # Select best threshold from test set, fallback to train, fallback to 0.5
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

    def _confusion(self, y_bin: list[int], y_pred: list[int]) -> tuple[int, int, int, int]:
        """Compute (tn, fp, fn, tp)."""
        tn = fp = fn = tp = 0
        for actual, predicted in zip(y_bin, y_pred):
            if actual == 0 and predicted == 0:
                tn += 1
            elif actual == 0 and predicted == 1:
                fp += 1
            elif actual == 1 and predicted == 0:
                fn += 1
            else:
                tp += 1
        return tn, fp, fn, tp


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
        band_count = int(params.get("band_count", 20))
        cutoffs = list(params.get("cutoffs", []))

        if band_count < 2:
            raise ValueError(f"band_count must be at least 2, got {band_count}")

        meta_art = None
        for a in context.input_artifacts:
            if a.role == "definition":
                try:
                    p = json.loads(store.artifact_path(a).read_text())
                    if "target_column" in p and "good_values" in p:
                        meta_art = a
                        break
                except Exception:
                    continue

        meta = {}
        if meta_art:
            meta = json.loads(store.artifact_path(meta_art).read_text())
        target_col = meta.get("target_column", "")
        good = set(str(v) for v in meta.get("good_values", []))
        bad = set(str(v) for v in meta.get("bad_values", []))

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        cutoff_tables: dict[str, list[JsonDict]] = {}
        warnings: list[JsonDict] = []

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))
            if "score" not in df.columns or "predicted_bad_probability" not in df.columns:
                continue

            scores = df["score"].to_list()
            if len(set(scores)) < 2:
                raise ValueError(f"Score column has zero variance in role {role!r}")

            min_s, max_s = min(scores), max(scores)
            if cutoffs:
                bands = sorted(float(c) for c in cutoffs if isinstance(c, (int, float)))
            else:
                step = (max_s - min_s) / band_count
                bands = [min_s + i * step for i in range(1, band_count)]

            if not target_col or target_col not in df.columns:
                warnings.append({
                    "role": role,
                    "code": "MISSING_TARGET_COLUMN",
                    "message": f"Target column {target_col!r} not found in role {role!r}; "
                               "bad rate and capture rate are not meaningful.",
                })
                y_bin = [0] * df.height
            elif not good and not bad:
                warnings.append({
                    "role": role,
                    "code": "MISSING_TARGET_METADATA",
                    "message": "No good_values/bad_values in definition artifact; "
                               "bad rate and capture rate are not meaningful.",
                })
                y_bin = [0] * df.height
            else:
                y_raw = df[target_col].cast(pl.String).to_list()
                y_bin = [1 if str(v) in bad else 0 for v in y_raw]

            bands_with_sentinel = [float("-inf")] + bands + [float("inf")]
            band_results = []
            for i in range(len(bands_with_sentinel) - 1):
                lo = bands_with_sentinel[i]
                hi = bands_with_sentinel[i + 1]
                idx = [j for j, s in enumerate(scores) if lo <= s < hi] if i < len(bands_with_sentinel) - 2 else [j for j, s in enumerate(scores) if lo <= s <= hi]
                if not idx:
                    continue
                n_band = len(idx)
                n_bad_band = sum(y_bin[j] for j in idx)
                band_results.append({
                    "band": i + 1,
                    "lower": round(lo, 2) if lo != float("-inf") else None,
                    "upper": round(hi, 2) if hi != float("inf") else None,
                    "count": n_band,
                    "bad_count": n_bad_band,
                    "approval_rate": round(1 - n_band / len(scores), 4),
                    "bad_rate": round(n_bad_band / n_band if n_band > 0 else 0, 4),
                    "capture_rate": round(n_bad_band / sum(y_bin) if sum(y_bin) > 0 else 0, 4),
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


class DummyApplyNode(NodeType):
    node_type = "cardre.dummy_apply"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["prediction"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        data_artifacts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        def_artifact = next((a for a in context.input_artifacts if a.role == "definition"), None)

        if def_artifact is None:
            raise ValueError("Dummy apply requires a definition artifact")

        input_roles = {a.role for a in data_artifacts}
        required_roles = {"train", "test", "oot"}
        missing = required_roles - input_roles
        if missing:
            raise ValueError(
                f"Dummy apply requires train, test, and oot artifacts. "
                f"Missing: {sorted(missing)}. "
                f"Received roles: {sorted(input_roles)}"
            )

        outputs = []
        for data_art in data_artifacts:
            df = pl.read_parquet(store.artifact_path(data_art))
            pred = pl.DataFrame({
                "dummy_prediction": [0.5] * df.height,
                "row_id": list(range(df.height)),
            })

            artifact = write_parquet_artifact(
                store,
                artifact_type="dataset",
                role="prediction",
                stem=f"apply-{data_art.role}-{context.step_spec.step_id}",
                frame=pred,
                metadata={
                    "source_artifact_id": data_art.artifact_id,
                    "definition_artifact_id": def_artifact.artifact_id,
                },
                directory="artifacts",
            )
            outputs.append(artifact)

        return NodeOutput(
            artifacts=outputs,
            metrics={"output_count": len(outputs)})