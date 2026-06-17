"""Hyperparameter tuning node using sklearn GridSearchCV / RandomizedSearchCV."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import polars as pl
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
from sklearn.tree import DecisionTreeClassifier

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType
from cardre.modeling.builders import build_model_artifact
from cardre.nodes._training_utils import _prepare_training_data, _write_estimator

ESTIMATOR_MAP = {
    "decision_tree": DecisionTreeClassifier,
    "random_forest": RandomForestClassifier,
    "gbdt": GradientBoostingClassifier,
    "logistic_regression": LogisticRegression,
}

ESTIMATOR_DEFAULT_KWARGS = {
    "decision_tree": {},
    "random_forest": {"n_jobs": -1},
    "gbdt": {},
    "logistic_regression": {"solver": "lbfgs", "max_iter": 1000},
}

ESTIMATOR_TO_FAMILY = {
    "decision_tree": "decision_tree",
    "random_forest": "random_forest",
    "gbdt": "gbdt",
    "logistic_regression": "logistic_regression",
}


class HyperparameterTuningNode(NodeType):
    node_type = "cardre.hyperparameter_tuning"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        estimator_type = params.get("estimator_type", "")
        if estimator_type not in ESTIMATOR_MAP:
            errors.append(
                f"estimator_type must be one of {sorted(ESTIMATOR_MAP.keys())}, "
                f"got {estimator_type!r}"
            )

        search_method = params.get("search_method", "grid")
        if search_method not in ("grid", "randomized"):
            errors.append("search_method must be 'grid' or 'randomized'")

        param_grid = params.get("param_grid")
        if not param_grid or not isinstance(param_grid, dict):
            errors.append("param_grid must be a non-empty dict")

        cv_folds = params.get("cv_folds", 5)
        try:
            if int(cv_folds) < 2:
                errors.append("cv_folds must be >= 2")
        except (ValueError, TypeError):
            errors.append("cv_folds must be an integer")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        feature_strategy = params.get("feature_strategy", "raw_numeric")
        valid_strategies = {"raw_numeric", "encoded_raw", "woe_challenger"}
        if feature_strategy not in valid_strategies:
            errors.append(
                f"feature_strategy must be one of {sorted(valid_strategies)}, "
                f"got {feature_strategy!r}"
            )

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        params = context.validated_params
        step_id = context.step_spec.step_id

        df, features, target_column, good_values, bad_values, y_binary, _ = (
            _prepare_training_data(context, params)
        )
        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]
        random_seed = int(params.get("random_seed", 42))

        estimator_type = params["estimator_type"]
        search_method = params.get("search_method", "grid")
        param_grid = params["param_grid"]
        cv_folds = int(params.get("cv_folds", 5))
        scoring = str(params.get("scoring", "roc_auc"))
        n_jobs = int(params.get("n_jobs", -1))
        n_iter = int(params.get("n_iter", 10))
        refit = bool(params.get("refit", True))

        estimator_cls = ESTIMATOR_MAP[estimator_type]
        base_kwargs = dict(ESTIMATOR_DEFAULT_KWARGS.get(estimator_type, {}))
        base_kwargs["random_state"] = random_seed

        start_time = time.monotonic()

        if search_method == "randomized":
            search = RandomizedSearchCV(
                estimator=estimator_cls(**base_kwargs),
                param_distributions=param_grid,
                n_iter=n_iter,
                cv=cv_folds,
                scoring=scoring,
                n_jobs=n_jobs,
                random_state=random_seed,
                refit=refit,
            )
        else:
            search = GridSearchCV(
                estimator=estimator_cls(**base_kwargs),
                param_grid=param_grid,
                cv=cv_folds,
                scoring=scoring,
                n_jobs=n_jobs,
                refit=refit,
            )

        X = df.select(features).to_numpy()
        search.fit(X, y_binary)
        elapsed = time.monotonic() - start_time

        best_params = search.best_params_
        best_score = float(search.best_score_)
        cv_results = search.cv_results_

        if refit:
            best_estimator = search.best_estimator_
        else:
            merged = dict(base_kwargs)
            merged.update(best_params)
            best_estimator = estimator_cls(**merged)
            best_estimator.fit(X, y_binary)

        prob_col_idx = 1
        for idx, cls_label in enumerate(best_estimator.classes_):
            if cls_label == 1:
                prob_col_idx = idx
                break

        feature_importance = {}
        if hasattr(best_estimator, "feature_importances_"):
            feature_importance = {
                fname: round(float(imp), 6)
                for fname, imp in zip(features, best_estimator.feature_importances_)
                if imp > 0
            }
        elif hasattr(best_estimator, "coef_"):
            coef = best_estimator.coef_.ravel()
            feature_importance = {
                fname: round(float(c), 6)
                for fname, c in zip(features, coef)
                if abs(c) > 0
            }

        cv_results_df = pl.DataFrame({
            k: v for k, v in cv_results.items()
            if isinstance(v, (list, np.ndarray))
        })

        model_family = ESTIMATOR_TO_FAMILY[estimator_type]
        estimator_art = _write_estimator(
            context.store, best_estimator, step_id, context.run_id, model_family,
        )

        model = build_model_artifact(
            model_family=model_family,
            target_column=target_column,
            features=features,
            bad_class=bad_class,
            good_class=good_class,
            prob_col_idx=prob_col_idx,
            feature_strategy=params.get("feature_strategy", "raw_numeric"),
            estimator_art=estimator_art,
            training_params={
                "estimator_type": estimator_type,
                "search_method": search_method,
                "cv_folds": cv_folds,
                "scoring": scoring,
                "n_iter": n_iter,
                "random_state": random_seed,
            },
            random_seed=random_seed,
            elapsed=elapsed,
            model_payload={
                "feature_importance": feature_importance,
                "feature_count": len(features),
            },
            interpretability={
                "explanation_type": "feature_importance",
                "explanation_level": "post_hoc_only",
                "native_importance_available": bool(feature_importance),
                "limitations": [
                    "Hyperparameter-tuned model does not produce native scorecard points",
                ],
                "global_importance_fields": ["feature_importance"],
            },
            context=context,
            extra_metrics=None,
            warnings_list=[],
            row_count=df.height,
        )

        if estimator_type == "logistic_regression":
            model["intercept"] = round(float(best_estimator.intercept_[0]), 6)
            model["coefficients"] = {
                f: round(float(best_estimator.coef_[0][i]), 6)
                for i, f in enumerate(features)
            }

        model["training"]["hyperparameter_tuning"] = {
            "search_method": search_method,
            "best_params": {
                k: str(v) if isinstance(v, (np.integer, np.floating, np.bool_)) else v
                for k, v in best_params.items()
            },
            "best_score": round(float(best_score), 6),
            "cv_results_df_shape": list(cv_results_df.shape),
        }

        artifact_metadata = {
            "feature_count": len(features),
            "target_column": target_column,
            "model_family": model_family,
            "best_score": round(float(best_score), 6),
            "search_method": search_method,
            "estimator_type": estimator_type,
        }
        artifact = write_json_artifact(
            context.store, artifact_type="model", role="model",
            stem=f"{model_family}-model-{step_id}",
            payload=model,
            metadata=artifact_metadata,
        )

        metrics: dict[str, Any] = {
            "feature_count": len(features),
            "best_score": round(float(best_score), 6),
        }

        return NodeOutput(
            artifacts=[artifact, estimator_art],
            metrics=metrics,
        )
