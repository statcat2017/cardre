"""Optional boosting classifier nodes — XGBoost, LightGBM, CatBoost.

Phase 8 adds high-value optional methods from the paper without making
default Cardre heavy. Each node requires its optional dependency and
fails with a clear installation message if not available.
"""

from __future__ import annotations

import io
import time
from typing import Any

import joblib
import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    json_logical_hash,
)
from cardre.modeling.builders import build_model_artifact
from cardre.nodes._training_utils import _extract_target_metadata, _prepare_training_data, _resolve_features, _write_estimator


def _check_optional_dependency(package_name: str, install_name: str) -> None:
    """Raise ImportError with clear message if optional package is missing."""
    try:
        __import__(package_name)
    except ImportError:
        raise ImportError(
            f"This node requires the '{install_name}' package. "
            f"Install it with: pip install {install_name}"
        )


class XGBoostClassifierNode(NodeType):
    """XGBoost classifier — optional boosting challenger.

    Requires the `xgboost` package. Produces a cardre.model_artifact.v1
    JSON artifact plus a binary estimator artifact.
    """

    node_type = "cardre.xgboost_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_FEATURE_STRATEGIES = {"raw_numeric", "encoded_raw", "woe_challenger"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        feature_strategy = params.get("feature_strategy", "")
        if feature_strategy not in self.VALID_FEATURE_STRATEGIES:
            errors.append(f"feature_strategy must be one of {sorted(self.VALID_FEATURE_STRATEGIES)}")

        n_estimators = params.get("n_estimators", 100)
        try:
            if int(n_estimators) < 1:
                errors.append("n_estimators must be >= 1")
        except (ValueError, TypeError):
            errors.append("n_estimators must be an integer")

        max_depth = params.get("max_depth", 6)
        try:
            if int(max_depth) < 1:
                errors.append("max_depth must be >= 1")
        except (ValueError, TypeError):
            errors.append("max_depth must be an integer")

        learning_rate = params.get("learning_rate", 0.1)
        try:
            if float(learning_rate) <= 0:
                errors.append("learning_rate must be > 0")
        except (ValueError, TypeError):
            errors.append("learning_rate must be a number")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        _check_optional_dependency("xgboost", "xgboost")
        from xgboost import XGBClassifier

        params = context.validated_params
        df, features, target_column, good_values, bad_values, y_binary, meta = (
            _prepare_training_data(context, params)
        )

        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        n_estimators = int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 6))
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        xgb_params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "random_state": random_seed,
            "use_label_encoder": False,
            "eval_metric": "logloss",
            "n_jobs": -1,
        }

        start_time = time.monotonic()
        clf = XGBClassifier(**xgb_params)
        X = df.select(features).to_numpy()
        clf.fit(X, y_binary)
        elapsed = time.monotonic() - start_time

        prob_col_idx = 1
        for idx, cls_label in enumerate(clf.classes_):
            if cls_label == 1:
                prob_col_idx = idx
                break

        feature_importance = {
            fname: round(float(imp), 6)
            for fname, imp in zip(features, clf.feature_importances_)
            if imp > 0
        }

        limitations = [
            "XGBoost is semi-transparent: feature importance is available "
            "but individual predictions are not fully decomposable",
            "XGBoost does not produce native scorecard points",
        ]

        training_params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "random_state": random_seed,
        }

        estimator_art = _write_estimator(context.store, clf, context.step_spec.step_id, context.run_id, "xgboost")

        model_payload = {
            "feature_importance": feature_importance,
            "feature_count": len(features),
            "estimator_count": n_estimators,
            "learning_rate": learning_rate,
        }
        interpretability = {
            "explanation_type": "feature_importance",
            "explanation_level": "native_semi_transparent",
            "native_importance_available": True,
            "limitations": limitations,
            "global_importance_fields": ["feature_importance"],
        }

        model = build_model_artifact(
            model_family="xgboost",
            target_column=target_column,
            features=features,
            bad_class=bad_class,
            good_class=good_class,
            prob_col_idx=prob_col_idx,
            feature_strategy=params.get("feature_strategy", "raw_numeric"),
            estimator_art=estimator_art,
            training_params=training_params,
            random_seed=random_seed,
            elapsed=elapsed,
            model_payload=model_payload,
            interpretability=interpretability,
            context=context,
            extra_metrics={"estimator_count": n_estimators},
            row_count=df.height,
        )

        artifact = write_json_artifact(
            context.store, artifact_type="model", role="model",
            stem=f"xgboost-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features),
                "target_column": target_column,
                "model_family": "xgboost",
            },
        )

        return NodeOutput(
            artifacts=[artifact, estimator_art],
            metrics={"feature_count": len(features), "estimator_count": n_estimators})


class LightGBMClassifierNode(NodeType):
    """LightGBM classifier — optional boosting challenger.

    Requires the `lightgbm` package. Produces a cardre.model_artifact.v1
    JSON artifact plus a binary estimator artifact.
    """

    node_type = "cardre.lightgbm_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_FEATURE_STRATEGIES = {"raw_numeric", "encoded_raw", "woe_challenger"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        feature_strategy = params.get("feature_strategy", "")
        if feature_strategy not in self.VALID_FEATURE_STRATEGIES:
            errors.append(f"feature_strategy must be one of {sorted(self.VALID_FEATURE_STRATEGIES)}")

        n_estimators = params.get("n_estimators", 100)
        try:
            if int(n_estimators) < 1:
                errors.append("n_estimators must be >= 1")
        except (ValueError, TypeError):
            errors.append("n_estimators must be an integer")

        max_depth = params.get("max_depth", -1)
        if max_depth is not None:
            try:
                if int(max_depth) < -1:
                    errors.append("max_depth must be >= -1")
            except (ValueError, TypeError):
                errors.append("max_depth must be an integer")

        learning_rate = params.get("learning_rate", 0.1)
        try:
            if float(learning_rate) <= 0:
                errors.append("learning_rate must be > 0")
        except (ValueError, TypeError):
            errors.append("learning_rate must be a number")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        _check_optional_dependency("lightgbm", "lightgbm")
        from lightgbm import LGBMClassifier

        params = context.validated_params
        df, features, target_column, good_values, bad_values, y_binary, meta = (
            _prepare_training_data(context, params)
        )

        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        n_estimators = int(params.get("n_estimators", 100))
        max_depth = params.get("max_depth", -1)
        if max_depth is not None:
            max_depth = int(max_depth)
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        lgbm_params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "random_state": random_seed,
            "n_jobs": -1,
            "verbose": -1,
        }

        start_time = time.monotonic()
        clf = LGBMClassifier(**lgbm_params)
        X = df.select(features).to_numpy()
        clf.fit(X, y_binary)
        elapsed = time.monotonic() - start_time

        prob_col_idx = 1
        for idx, cls_label in enumerate(clf.classes_):
            if cls_label == 1:
                prob_col_idx = idx
                break

        feature_importance = {
            fname: round(float(imp), 6)
            for fname, imp in zip(features, clf.feature_importances_)
            if imp > 0
        }

        limitations = [
            "LightGBM is semi-transparent: feature importance is available "
            "but individual predictions are not fully decomposable",
            "LightGBM does not produce native scorecard points",
        ]

        training_params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "random_state": random_seed,
        }

        estimator_art = _write_estimator(context.store, clf, context.step_spec.step_id, context.run_id, "lightgbm")

        model_payload = {
            "feature_importance": feature_importance,
            "feature_count": len(features),
            "estimator_count": n_estimators,
            "learning_rate": learning_rate,
        }
        interpretability = {
            "explanation_type": "feature_importance",
            "explanation_level": "native_semi_transparent",
            "native_importance_available": True,
            "limitations": limitations,
            "global_importance_fields": ["feature_importance"],
        }

        model = build_model_artifact(
            model_family="lightgbm",
            target_column=target_column,
            features=features,
            bad_class=bad_class,
            good_class=good_class,
            prob_col_idx=prob_col_idx,
            feature_strategy=params.get("feature_strategy", "raw_numeric"),
            estimator_art=estimator_art,
            training_params=training_params,
            random_seed=random_seed,
            elapsed=elapsed,
            model_payload=model_payload,
            interpretability=interpretability,
            context=context,
            extra_metrics={"estimator_count": n_estimators},
            row_count=df.height,
        )

        artifact = write_json_artifact(
            context.store, artifact_type="model", role="model",
            stem=f"lightgbm-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features),
                "target_column": target_column,
                "model_family": "lightgbm",
            },
        )

        return NodeOutput(
            artifacts=[artifact, estimator_art],
            metrics={"feature_count": len(features), "estimator_count": n_estimators})


class CatBoostClassifierNode(NodeType):
    """CatBoost classifier — optional boosting challenger.

    Requires the `catboost` package. Produces a cardre.model_artifact.v1
    JSON artifact plus a binary estimator artifact.
    """

    node_type = "cardre.catboost_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_FEATURE_STRATEGIES = {"raw_numeric", "encoded_raw", "woe_challenger"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        feature_strategy = params.get("feature_strategy", "")
        if feature_strategy not in self.VALID_FEATURE_STRATEGIES:
            errors.append(f"feature_strategy must be one of {sorted(self.VALID_FEATURE_STRATEGIES)}")

        iterations = params.get("iterations", 100)
        try:
            if int(iterations) < 1:
                errors.append("iterations must be >= 1")
        except (ValueError, TypeError):
            errors.append("iterations must be an integer")

        depth = params.get("depth", 6)
        try:
            if int(depth) < 1:
                errors.append("depth must be >= 1")
        except (ValueError, TypeError):
            errors.append("depth must be an integer")

        learning_rate = params.get("learning_rate", 0.1)
        try:
            if float(learning_rate) <= 0:
                errors.append("learning_rate must be > 0")
        except (ValueError, TypeError):
            errors.append("learning_rate must be a number")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        _check_optional_dependency("catboost", "catboost")
        from catboost import CatBoostClassifier as CatBoostClf

        params = context.validated_params
        df, features, target_column, good_values, bad_values, y_binary, meta = (
            _prepare_training_data(context, params)
        )

        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        iterations = int(params.get("iterations", 100))
        depth = int(params.get("depth", 6))
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        cat_params = {
            "iterations": iterations,
            "depth": depth,
            "learning_rate": learning_rate,
            "random_seed": random_seed,
            "verbose": 0,
            "allow_writing_files": False,
        }

        start_time = time.monotonic()
        clf = CatBoostClf(**cat_params)
        X = df.select(features).to_numpy()
        clf.fit(X, y_binary)
        elapsed = time.monotonic() - start_time

        prob_col_idx = 1
        for idx, cls_label in enumerate(clf.classes_):
            if cls_label == 1:
                prob_col_idx = idx
                break

        feature_importance = {
            fname: round(float(imp), 6)
            for fname, imp in zip(features, clf.feature_importances_)
            if imp > 0
        }

        limitations = [
            "CatBoost is semi-transparent: feature importance is available "
            "but individual predictions are not fully decomposable",
            "CatBoost does not produce native scorecard points",
        ]

        training_params = {
            "iterations": iterations,
            "depth": depth,
            "learning_rate": learning_rate,
            "random_seed": random_seed,
        }

        estimator_art = _write_estimator(context.store, clf, context.step_spec.step_id, context.run_id, "catboost")

        model_payload = {
            "feature_importance": feature_importance,
            "feature_count": len(features),
            "estimator_count": iterations,
            "learning_rate": learning_rate,
        }
        interpretability = {
            "explanation_type": "feature_importance",
            "explanation_level": "native_semi_transparent",
            "native_importance_available": True,
            "limitations": limitations,
            "global_importance_fields": ["feature_importance"],
        }

        model = build_model_artifact(
            model_family="catboost",
            target_column=target_column,
            features=features,
            bad_class=bad_class,
            good_class=good_class,
            prob_col_idx=prob_col_idx,
            feature_strategy=params.get("feature_strategy", "raw_numeric"),
            estimator_art=estimator_art,
            training_params=training_params,
            random_seed=random_seed,
            elapsed=elapsed,
            model_payload=model_payload,
            interpretability=interpretability,
            context=context,
            extra_metrics={"estimator_count": iterations},
            row_count=df.height,
        )

        artifact = write_json_artifact(
            context.store, artifact_type="model", role="model",
            stem=f"catboost-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features),
                "target_column": target_column,
                "model_family": "catboost",
            },
        )

        return NodeOutput(
            artifacts=[artifact, estimator_art],
            metrics={"feature_count": len(features), "estimator_count": iterations})


