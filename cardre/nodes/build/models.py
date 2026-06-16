from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl
from sklearn.linear_model import LogisticRegression

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType, json_logical_hash
from cardre.evidence import (
    AmbiguousEvidenceError,
    ArtifactEvidenceReader,
    EvidenceKind,
    EvidenceNotFoundError,
    SCHEMA_BIN_DEFINITION,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_SCORE_SCALING,
    SCHEMA_WOE_TABLE,
)


class LogisticRegressionNode(NodeType):
    node_type = "cardre.logistic_regression"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_PENALTIES = {"l1", "l2", "elasticnet", None}
    VALID_SOLVERS = {"lbfgs", "liblinear", "newton-cg", "newton-cholesky", "sag", "saga"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        penalty = params.get("penalty")
        if penalty is not None and penalty not in self.VALID_PENALTIES:
            errors.append(f"penalty must be one of {self.VALID_PENALTIES}, got '{penalty}'")
        solver = params.get("solver", "lbfgs")
        if solver not in self.VALID_SOLVERS:
            errors.append(f"solver must be one of {self.VALID_SOLVERS}, got '{solver}'")
        C = params.get("C", 1.0)
        try:
            if float(C) <= 0:
                errors.append("C must be positive")
        except (ValueError, TypeError):
            errors.append("C must be a number")
        max_iter = params.get("max_iter", 1000)
        try:
            if int(max_iter) < 1:
                errors.append("max_iter must be >= 1")
        except (ValueError, TypeError):
            errors.append("max_iter must be an integer")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        import numpy as np
        from sklearn.linear_model import LogisticRegression as SkLearnLR

        store = context.store
        params = context.validated_params
        reader = ArtifactEvidenceReader(store)
        train_artifact = next(a for a in context.input_artifacts if a.role == "train")

        meta = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

        target_column = meta.target_column
        good_values = set(str(v) for v in meta.good_values)
        bad_values = set(str(v) for v in meta.bad_values)

        if not target_column:
            raise ValueError("Target column is required for logistic regression")
        if not good_values:
            raise ValueError("Good values must be defined for logistic regression")
        if not bad_values:
            raise ValueError("Bad values must be defined for logistic regression")

        df = pl.read_parquet(store.artifact_path(train_artifact))
        woe_cols = [c for c in df.columns if c.endswith("_woe")]
        if not woe_cols:
            raise ValueError("No WOE-transformed columns found in training data")

        X = df.select(woe_cols).to_numpy()

        if target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found in training data")

        raw_target = df[target_column].cast(pl.String)
        all_known = good_values | bad_values
        unknown = raw_target.filter(~raw_target.is_in(list(all_known))).to_list()
        if unknown:
            unique_unknown = sorted(set(unknown))
            raise ValueError(
                f"Target column '{target_column}' contains {len(unknown)} value(s) "
                f"not declared as good or bad: {unique_unknown[:10]}. "
                f"Every row must be explicitly classified."
            )

        y_binary = df.with_columns(
            pl.when(pl.col(target_column).cast(pl.String).is_in(list(bad_values)))
            .then(pl.lit(1))
            .otherwise(pl.lit(0))
            .alias("_y_binary")
        )["_y_binary"].to_list()
        n_bad = sum(y_binary)
        n_good = len(y_binary) - n_bad
        if n_bad == 0:
            raise ValueError(f"Logistic regression: no bad-class rows found (bad_values={sorted(bad_values)})")
        if n_good == 0:
            raise ValueError(f"Logistic regression: no good-class rows found (good_values={sorted(good_values)})")

        penalty = params.get("penalty")
        C = float(params.get("C", 1.0))
        max_iter = int(params.get("max_iter", 1000))
        solver = str(params.get("solver", "lbfgs"))
        random_seed = int(params.get("random_seed", 42))

        lr_params = {"C": C, "max_iter": max_iter, "solver": solver, "random_state": random_seed}
        if penalty is not None:
            lr_params["penalty"] = penalty

        lr = SkLearnLR(**lr_params)
        lr.fit(X, y_binary)

        bad_class = sorted(bad_values)[0] if bad_values else "1"
        good_class = sorted(good_values)[0] if good_values else "0"
        class_map = {idx: label for idx, label in enumerate(lr.classes_)}
        bad_class_idx = 1 if len(lr.classes_) > 1 else 0
        if bad_class_idx == 0:
            class_mapping = {"good": str(good_class), "bad": str(bad_class)}
        else:
            class_mapping = {"good": str(good_class), "bad": str(bad_class)}

        features_list = woe_cols
        coefficients = {col: round(float(coef), 6) for col, coef in zip(features_list, lr.coef_[0])}

        warnings_list: list[dict] = []
        if not lr.n_iter_[0] < max_iter:
            warnings_list.append({
                "code": "CONVERGENCE_FAILURE",
                "message": f"Logistic regression did not converge after {max_iter} iterations",
            })

        converged = bool(lr.n_iter_[0] < max_iter)
        training_params = {}
        for k, v in lr_params.items():
            if isinstance(v, np.bool_):
                training_params[k] = bool(v)
            elif isinstance(v, np.integer):
                training_params[k] = int(v)
            elif isinstance(v, np.floating):
                training_params[k] = float(v)
            else:
                training_params[k] = v

        prob_col_idx = 1
        for idx, cls_label in enumerate(lr.classes_):
            if str(cls_label) == str(bad_class):
                prob_col_idx = idx
                break

        feature_order_hash = json_logical_hash(
            {"features": features_list}
        )

        model = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "logistic_regression",
            "target_column": target_column,
            "features": features_list,
            "intercept": round(float(lr.intercept_[0]), 6),
            "coefficients": coefficients,
            "class_mapping": class_mapping,
            "bad_class_label": str(bad_class),
            "target_event_value": str(bad_class),
            "probability_column_index": prob_col_idx,
            "feature_contract": {
                "features": features_list,
                "transformation_strategy": "woe",
                "order_hash": feature_order_hash,
                "missing_policy": "error",
                "unknown_category_policy": "error",
            },
            "feature_order_hash": feature_order_hash,
            "training": {
                "row_count": X.shape[0],
                "converged": converged,
                "iterations": int(lr.n_iter_[0]),
                "params": training_params,
            },
            "warnings": warnings_list,
        }

        artifact = write_json_artifact(
            store, artifact_type="model", role="model",
            stem=f"logistic-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features_list),
                "target_column": target_column,
                "schema_version": SCHEMA_MODEL_ARTIFACT,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"feature_count": len(features_list), "converged": lr.n_iter_[0] < max_iter})


class ScoreScalingNode(NodeType):
    node_type = "cardre.score_scaling"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["model", "definition", "report"]
    output_roles: list[str] = ["scorecard"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        base_odds = params.get("base_odds", 50.0)
        try:
            if isinstance(base_odds, str) and ":" in base_odds:
                num, den = base_odds.split(":", 1)
                base_odds_val = float(num) / float(den)
            else:
                base_odds_val = float(base_odds)
            if base_odds_val <= 0:
                errors.append("base_odds must be positive")
        except (ValueError, TypeError, ZeroDivisionError):
            errors.append("base_odds must be a number or 'N:M' odds ratio string")
        pdo = params.get("points_to_double_odds", 20)
        try:
            if float(pdo) <= 0:
                errors.append("points_to_double_odds must be positive")
        except (ValueError, TypeError):
            errors.append("points_to_double_odds must be a number")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        import math

        store = context.store
        params = context.validated_params
        reader = ArtifactEvidenceReader(store)

        try:
            model = reader.find(context.input_artifacts, EvidenceKind.MODEL_ARTIFACT)
            model_dict = model.as_legacy_dict()
        except (EvidenceNotFoundError, AmbiguousEvidenceError):
            model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
            if model_art is None:
                raise ValueError("Score scaling requires a model artifact")
            model_dict = json.loads(store.artifact_path(model_art).read_text())

        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find_optional(context.input_artifacts, EvidenceKind.WOE_TABLE)
        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

        if not bin_def.variables:
            raise ValueError("Score scaling received an empty bin definition")
        if woe_table is None:
            raise ValueError(
                "Score scaling requires exactly one WOE report artifact; found 0"
            )

        base_score = float(params.get("base_score", 600))
        base_odds = float(params.get("base_odds", 50.0))
        pdo = float(params.get("points_to_double_odds", 20))
        higher_is_lower_risk = bool(params.get("higher_score_is_lower_risk", True))

        if base_odds <= 0:
            raise ValueError(f"base_odds must be positive, got {base_odds}")
        if pdo <= 0:
            raise ValueError(f"points_to_double_odds must be positive, got {pdo}")

        factor = pdo / math.log(2)
        offset = base_score - factor * math.log(base_odds)
        intercept = float(model_dict.get("intercept", 0))
        coefficients = model_dict.get("coefficients", {})

        direction = -1.0 if higher_is_lower_risk else 1.0
        base_points = round(offset + direction * factor * intercept, 2)

        attributes: list[dict] = []
        all_woe_map = woe_table.mapping

        for var_def_obj in bin_def.variables:
            variable = var_def_obj.variable
            woe_key = f"{variable}_woe"
            if woe_key not in coefficients:
                continue
            coef = float(coefficients[woe_key])

            for bin_entry in var_def_obj.bins:
                bin_id = bin_entry["bin_id"]
                label = bin_entry["label"]
                woe_val = all_woe_map.get(variable, {}).get(bin_id)
                if woe_val is None:
                    raise ValueError(
                        f"Score scaling: missing WOE value for variable {variable!r} bin {bin_id!r}"
                    )
                raw_points = direction * factor * coef * woe_val
                point_value = round(raw_points, 2)
                attributes.append({
                    "variable": variable,
                    "bin_id": bin_id,
                    "label": label,
                    "woe": round(woe_val, 6),
                    "coefficient": coef,
                    "points": point_value,
                })

        scorecard = {
            "base_score": base_score,
            "base_odds": base_odds,
            "points_to_double_odds": pdo,
            "factor": round(factor, 6),
            "offset": round(offset, 6),
            "higher_score_is_lower_risk": higher_is_lower_risk,
            "intercept": intercept,
            "base_points": base_points,
            "attributes": attributes,
            "target_column": model_dict.get("target_column", ""),
        }

        scorecard["schema_version"] = SCHEMA_SCORE_SCALING
        artifact = write_json_artifact(
            store, artifact_type="scorecard", role="scorecard",
            stem=f"scorecard-{context.step_spec.step_id}",
            payload=scorecard,
            metadata={
                "base_score": base_score,
                "attribute_count": len(attributes),
                "schema_version": SCHEMA_SCORE_SCALING,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"attribute_count": len(attributes)})


class BuildSummaryReportNode(NodeType):
    node_type = "cardre.build_summary_report"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["scorecard", "model", "report"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        reader = ArtifactEvidenceReader(store)

        scorecard_artifact = next(a for a in context.input_artifacts if a.role == "scorecard")
        scorecard = json.loads(store.artifact_path(scorecard_artifact).read_text())

        try:
            model = reader.find(context.input_artifacts, EvidenceKind.MODEL_ARTIFACT)
        except EvidenceNotFoundError:
            model_artifact = next(a for a in context.input_artifacts if a.role == "model")
            model = json.loads(store.artifact_path(model_artifact).read_text())
            model_is_typed = False
        else:
            model_is_typed = True

        woe_summaries: list[dict[str, Any]] = []
        iv_lf = reader.find_optional(context.input_artifacts, EvidenceKind.IV_TABLE)
        if iv_lf is not None:
            iv_df = iv_lf.dataframe.collect()
            woe_summaries.append({
                "artifact_id": iv_lf.source_artifact_id,
                "type": "iv_ranking",
                "row_count": iv_df.height,
                "columns": list(iv_df.columns),
            })
        try:
            woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)
            woe_df = woe_table.dataframe
            if woe_df is not None:
                woe_summaries.append({
                    "artifact_id": woe_table.source_artifact_id,
                    "type": "woe_table",
                    "row_count": woe_df.collect().height,
                    "columns": list(woe_table.columns),
                })
        except EvidenceNotFoundError:
            pass

        model_features = model.features if model_is_typed else model.get("features", [])
        model_intercept = model.intercept if model_is_typed else model.get("intercept", 0)
        model_coeff_count = len(model.coefficients_dict) if model_is_typed else len(model.get("coefficients", {}))
        model_converged = model.training.get("converged", False) if model_is_typed else model.get("training", {}).get("converged", False)
        model_row_count = model.training.get("row_count", 0) if model_is_typed else model.get("training", {}).get("row_count", 0)
        model_warnings = list(model.warnings) if model_is_typed else model.get("warnings", [])
        model_target = model.target_column if model_is_typed else model.get("target_column", "")

        report = {
            "model_summary": {
                "target_column": model_target,
                "features": model_features,
                "intercept": model_intercept,
                "coefficient_count": model_coeff_count,
                "converged": model_converged,
                "row_count": model_row_count,
            },
            "scorecard_summary": {
                "base_score": scorecard.get("base_score", 0),
                "base_odds": scorecard.get("base_odds", 0),
                "points_to_double_odds": scorecard.get("points_to_double_odds", 0),
                "attribute_count": len(scorecard.get("attributes", [])),
                "higher_score_is_lower_risk": scorecard.get("higher_score_is_lower_risk", True),
            },
            "woe_iv_references": woe_summaries,
            "warnings": model_warnings,
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"build-summary-{context.step_spec.step_id}",
            payload=report,
            metadata={},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"feature_count": len(model_features)})


class DummyFitNode(NodeType):
    node_type = "cardre.dummy_fit"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        input_artifact = context.input_artifacts[0]
        params = context.validated_params

        df = pl.read_parquet(store.artifact_path(input_artifact))
        dummy_def = {
            "model_type": "dummy",
            "version": self.version,
            "params": params,
            "input_columns": list(df.columns),
            "row_count": df.height,
        }

        artifact = write_json_artifact(
            store,
            artifact_type="definition",
            role="definition",
            stem=f"dummy-fit-{context.step_spec.step_id}",
            payload=dummy_def,
            metadata={"source_artifact_id": input_artifact.artifact_id},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height})
