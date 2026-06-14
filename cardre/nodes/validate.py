from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl
from sklearn.metrics import roc_auc_score

from cardre.artifacts import make_fingerprint, write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
)



class ApplyWoeMappingNode(NodeType):
    node_type = "cardre.apply_woe_mapping"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition", "report"]
    output_roles: list[str] = ["train", "test", "oot"]

    def _find_artifacts(self, artifacts, store):
        bin_art = woe_art = None
        sel_art = None
        data_arts = []
        for a in artifacts:
            if a.role in ("train", "test", "oot"):
                data_arts.append(a)
            elif a.role == "definition":
                try:
                    p = json.loads(store.artifact_path(a).read_text())
                    if "variables" in p and "selected" not in p:
                        bin_art = a
                    elif "selected" in p:
                        sel_art = a
                except Exception:
                    continue
            elif a.role == "report":
                try:
                    c = store.artifact_path(a).read_bytes()
                    if c[:4] == b"PAR1":
                        d = pl.read_parquet(store.artifact_path(a))
                        if "woe" in d.columns and "bin_id" in d.columns and "variable" in d.columns:
                            woe_art = a
                except Exception:
                    continue
        return data_arts, bin_art, woe_art, sel_art

    def run(self, context: ExecutionContext) -> NodeOutput:
        import math

        store = context.store
        data_arts, bin_art, woe_art, sel_art = self._find_artifacts(context.input_artifacts, store)
        if bin_art is None:
            raise ValueError("apply_woe_mapping requires a bin definition artifact")
        if woe_art is None:
            raise ValueError("apply_woe_mapping requires a WOE table report")

        bin_def = json.loads(store.artifact_path(bin_art).read_text())

        selected_names: set[str] | None = None
        if sel_art:
            try:
                s = json.loads(store.artifact_path(sel_art).read_text())
                selected_names = {x["variable"] for x in s.get("selected", [])}
            except Exception:
                pass

        woe_df = pl.read_parquet(store.artifact_path(woe_art))
        c = woe_df.columns
        woe_map: dict[str, dict[str, float]] = {}
        for r in woe_df.iter_rows():
            var = str(r[c.index("variable")])
            bid = str(r[c.index("bin_id")])
            wv = float(r[c.index("woe")])
            woe_map.setdefault(var, {})[bid] = wv

        var_defs = bin_def.get("variables", [])
        if selected_names is not None:
            var_defs = [v for v in var_defs if v["variable"] in selected_names]

        fallback_report: dict[str, dict] = {}
        outputs = []

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role
            fallback_counts: dict[str, int] = {}

            for vd in var_defs:
                var = vd["variable"]
                kind = vd["kind"]
                bins = vd["bins"]
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
                        df = df.with_columns(pl.col(woe_col).fill_null(0.0))

            fallback_report[role] = fallback_counts
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"woe-apply-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata={"source_id": data_art.artifact_id},
            )
            outputs.append(art)

        write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-apply-fallback-{context.step_spec.step_id}",
            payload=fallback_report,
            metadata={},
        )

        fp = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type, node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=outputs,
        )
        return NodeOutput(artifacts=outputs, metrics={"output_count": len(outputs)}, execution_fingerprint=fp)


class ApplyModelNode(NodeType):
    node_type = "cardre.apply_model"
    version = "1"
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
        if scorecard_art is None:
            raise ValueError("apply_model requires a scorecard artifact")

        model = json.loads(store.artifact_path(model_art).read_text())
        scorecard = json.loads(store.artifact_path(scorecard_art).read_text())

        features = model.get("features", [])
        intercept = float(model.get("intercept", 0))
        coefficients = model.get("coefficients", {})

        target_column = model.get("target_column", "")
        offset = float(scorecard.get("offset", 0))
        factor = float(scorecard.get("factor", 1))
        direction = -1.0 if scorecard.get("higher_score_is_lower_risk", True) else 1.0

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
            score_vals = offset + direction * factor * log_odds

            df = df.with_columns([
                pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
                pl.Series("score", score_vals, dtype=pl.Float64),
            ])
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"scored-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata={"model_artifact_id": model_art.artifact_id},
            )
            outputs.append(art)

        fp = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type, node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=outputs,
        )
        return NodeOutput(artifacts=outputs, metrics={"output_count": len(outputs)}, execution_fingerprint=fp)


class ValidationMetricsNode(NodeType):
    node_type = "cardre.validation_metrics"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from sklearn.metrics import roc_auc_score

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

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        metrics_report: dict = {}
        psi_bins: dict[str, list[float]] = {}

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))
            n = df.height

            if target_col not in df.columns:
                metrics_report[role] = {"row_count": n, "error": f"Missing target column {target_col!r}"}
                continue
            if "predicted_bad_probability" not in df.columns:
                metrics_report[role] = {"row_count": n, "error": "Missing predicted_bad_probability"}
                continue
            if "score" not in df.columns:
                metrics_report[role] = {"row_count": n, "error": "Missing score column"}
                continue

            y_true = df[target_col].cast(pl.String).to_list()
            y_bin = [1 if str(v) in bad else 0 for v in y_true]
            y_prob = df["predicted_bad_probability"].to_list()
            scores = df["score"].to_list()

            n_bad = sum(y_bin)
            n_good = n - n_bad
            auc_val = None
            gini_val = None
            ks_val = None
            calib = {}
            score_dist = {}

            if n_bad > 0 and n_good > 0:
                auc_val = float(roc_auc_score(y_bin, y_prob))
                gini_val = round(2 * auc_val - 1, 6)
                auc_val = round(auc_val, 6)

                sorted_by_score = sorted(zip(scores, y_bin), key=lambda x: x[0])
                cum_good = 0
                cum_bad = 0
                ks = 0.0
                ks_at = 0.0
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

            metrics_report[role] = {
                "row_count": n,
                "auc": auc_val,
                "gini": gini_val,
                "ks": ks_val,
                "ks_at_score": round(ks_at, 2) if ks_val else None,
                "calibration": calib,
                "score_distribution": score_dist,
            }
            psi_bins[role] = scores

        if "train" in psi_bins and "test" in psi_bins:
            metrics_report.setdefault("psi", {})["train_vs_test"] = self._psi(psi_bins["train"], psi_bins["test"])
        if "train" in psi_bins and "oot" in psi_bins:
            metrics_report.setdefault("psi", {})["train_vs_oot"] = self._psi(psi_bins["train"], psi_bins["oot"])

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"validation-metrics-{context.step_spec.step_id}",
            payload=metrics_report,
            metadata={},
        )
        fp = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type, node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[art],
        )
        return NodeOutput(artifacts=[art], metrics={"role_count": len(data_arts)}, execution_fingerprint=fp)

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


class CutoffAnalysisNode(NodeType):
    node_type = "cardre.cutoff_analysis"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot"]
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

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        report: dict = {}

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))
            if "score" not in df.columns or "predicted_bad_probability" not in df.columns:
                report[role] = {"error": "Missing score or predicted_bad_probability column"}
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

            y_bin = [1 if str(v) in ("bad", "2") else 0 for v in df["predicted_bad_probability"].to_list()]

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

            report[role] = {
                "row_count": len(scores),
                "bands": band_results,
                "overall_bad_rate": round(sum(y_bin) / len(y_bin), 4),
            }

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"cutoff-analysis-{context.step_spec.step_id}",
            payload=report,
            metadata={},
        )
        fp = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type, node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[art],
        )
        return NodeOutput(artifacts=[art], metrics={"role_count": len(data_arts)}, execution_fingerprint=fp)


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

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=outputs,
        )

        return NodeOutput(
            artifacts=outputs,
            metrics={"output_count": len(outputs)},
            execution_fingerprint=fingerprint,
        )