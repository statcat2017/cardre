"""Optional boosting classifier nodes — XGBoost, LightGBM, CatBoost.

Phase 8 adds high-value optional methods from the paper without making
default Cardre heavy. Each node requires its optional dependency and
fails with a clear installation message if not available.
"""

from __future__ import annotations

from typing import Any

from cardre.nodes._classifier_base import BaseClassifierNode, _ClassifierResult


def _check_optional_dependency(package_name: str, install_name: str) -> None:
    """Raise ImportError with clear message if optional package is missing."""
    try:
        __import__(package_name)
    except ImportError:
        raise ImportError(
            f"This node requires the '{install_name}' package. "
            f"Install it with: pip install {install_name}"
        )


class XGBoostClassifierNode(BaseClassifierNode):
    """XGBoost classifier — optional boosting challenger.

    Requires the `xgboost` package. Produces a cardre.model_artifact.v1
    JSON artifact plus a binary estimator artifact.
    """

    node_type = "cardre.xgboost_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]
    model_family = "xgboost"

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

    def _check_dependencies(self) -> None:
        _check_optional_dependency("xgboost", "xgboost")
        from xgboost import XGBClassifier
        self._Cls = XGBClassifier

    def _get_estimator_class(self):
        return self._Cls

    def _build_estimator_kwargs(self, params: dict[str, Any]) -> dict[str, Any]:
        n_estimators = int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 6))
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        return {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "random_state": random_seed,
            "use_label_encoder": False,
            "eval_metric": "logloss",
            "n_jobs": -1,
        }

    def _post_fit(
        self,
        clf,
        features: list[str],
        df,
        params: dict[str, Any],
        *,
        bad_class: str,
        good_class: str,
        feature_importance: dict[str, float],
        prob_col_idx: int,
    ) -> _ClassifierResult:
        n_estimators = int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 6))
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        limitations = [
            "XGBoost is semi-transparent: feature importance is available "
            "but individual predictions are not fully decomposable",
            "XGBoost does not produce native scorecard points",
        ]

        return _ClassifierResult(
            model_payload={
                "feature_importance": feature_importance,
                "feature_count": len(features),
                "estimator_count": n_estimators,
                "learning_rate": learning_rate,
            },
            interpretability={
                "explanation_type": "feature_importance",
                "explanation_level": "native_semi_transparent",
                "native_importance_available": True,
                "limitations": limitations,
                "global_importance_fields": ["feature_importance"],
            },
            training_params={
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "learning_rate": learning_rate,
                "random_state": random_seed,
            },
            extra_metrics={"estimator_count": n_estimators},
        )


class LightGBMClassifierNode(BaseClassifierNode):
    """LightGBM classifier — optional boosting challenger.

    Requires the `lightgbm` package. Produces a cardre.model_artifact.v1
    JSON artifact plus a binary estimator artifact.
    """

    node_type = "cardre.lightgbm_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]
    model_family = "lightgbm"

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

    def _check_dependencies(self) -> None:
        _check_optional_dependency("lightgbm", "lightgbm")
        from lightgbm import LGBMClassifier
        self._Cls = LGBMClassifier

    def _get_estimator_class(self):
        return self._Cls

    def _build_estimator_kwargs(self, params: dict[str, Any]) -> dict[str, Any]:
        n_estimators = int(params.get("n_estimators", 100))
        max_depth = params.get("max_depth", -1)
        if max_depth is not None:
            max_depth = int(max_depth)
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        return {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "random_state": random_seed,
            "n_jobs": -1,
            "verbose": -1,
        }

    def _post_fit(
        self,
        clf,
        features: list[str],
        df,
        params: dict[str, Any],
        *,
        bad_class: str,
        good_class: str,
        feature_importance: dict[str, float],
        prob_col_idx: int,
    ) -> _ClassifierResult:
        n_estimators = int(params.get("n_estimators", 100))
        max_depth = params.get("max_depth", -1)
        if max_depth is not None:
            max_depth = int(max_depth)
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        limitations = [
            "LightGBM is semi-transparent: feature importance is available "
            "but individual predictions are not fully decomposable",
            "LightGBM does not produce native scorecard points",
        ]

        return _ClassifierResult(
            model_payload={
                "feature_importance": feature_importance,
                "feature_count": len(features),
                "estimator_count": n_estimators,
                "learning_rate": learning_rate,
            },
            interpretability={
                "explanation_type": "feature_importance",
                "explanation_level": "native_semi_transparent",
                "native_importance_available": True,
                "limitations": limitations,
                "global_importance_fields": ["feature_importance"],
            },
            training_params={
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "learning_rate": learning_rate,
                "random_state": random_seed,
            },
            extra_metrics={"estimator_count": n_estimators},
        )


class CatBoostClassifierNode(BaseClassifierNode):
    """CatBoost classifier — optional boosting challenger.

    Requires the `catboost` package. Produces a cardre.model_artifact.v1
    JSON artifact plus a binary estimator artifact.
    """

    node_type = "cardre.catboost_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]
    model_family = "catboost"

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

    def _check_dependencies(self) -> None:
        _check_optional_dependency("catboost", "catboost")
        from catboost import CatBoostClassifier as CatBoostClf
        self._Cls = CatBoostClf

    def _get_estimator_class(self):
        return self._Cls

    def _build_estimator_kwargs(self, params: dict[str, Any]) -> dict[str, Any]:
        iterations = int(params.get("iterations", 100))
        depth = int(params.get("depth", 6))
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        return {
            "iterations": iterations,
            "depth": depth,
            "learning_rate": learning_rate,
            "random_seed": random_seed,
            "verbose": 0,
            "allow_writing_files": False,
        }

    def _post_fit(
        self,
        clf,
        features: list[str],
        df,
        params: dict[str, Any],
        *,
        bad_class: str,
        good_class: str,
        feature_importance: dict[str, float],
        prob_col_idx: int,
    ) -> _ClassifierResult:
        iterations = int(params.get("iterations", 100))
        depth = int(params.get("depth", 6))
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        limitations = [
            "CatBoost is semi-transparent: feature importance is available "
            "but individual predictions are not fully decomposable",
            "CatBoost does not produce native scorecard points",
        ]

        return _ClassifierResult(
            model_payload={
                "feature_importance": feature_importance,
                "feature_count": len(features),
                "estimator_count": iterations,
                "learning_rate": learning_rate,
            },
            interpretability={
                "explanation_type": "feature_importance",
                "explanation_level": "native_semi_transparent",
                "native_importance_available": True,
                "limitations": limitations,
                "global_importance_fields": ["feature_importance"],
            },
            training_params={
                "iterations": iterations,
                "depth": depth,
                "learning_rate": learning_rate,
                "random_seed": random_seed,
            },
            extra_metrics={"estimator_count": iterations},
        )


