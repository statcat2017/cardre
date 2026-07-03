"""Base classifier node — template method pattern.

Extracts the duplicated 14-step run() flow shared by 6 classifier nodes
into a single template.  Subclasses provide 4 hooks:

  - _get_estimator_class() -> type
  - _build_estimator_kwargs(params) -> dict
  - _post_fit(clf, features, df, params, *, bad_class, good_class,
               feature_importance, prob_col_idx) -> _ClassifierResult
  - _check_dependencies() -> None  (optional, default noop)

The base handles: training-data prep, estimator construction + fit + timing,
prob_col_idx scan, feature_importance extraction, binary estimator persistence,
model artifact construction (via build_model_artifact), JSON artifact writing,
and NodeOutput assembly.

Callers and tests see the same public interface (run(context) -> NodeOutput).
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any

import polars as pl
from sklearn.model_selection import StratifiedKFold, cross_validate

from cardre.artifacts import write_json_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.modeling.builders import build_model_artifact
from cardre.nodes._training_utils import _prepare_training_data, _write_estimator
from cardre.nodes.contracts import NodeType


@dataclass
class _ClassifierResult:
    """Varying parts of a classifier run, returned by _post_fit()."""

    model_payload: dict[str, Any]
    interpretability: dict[str, Any]
    training_params: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    extra_metrics: dict[str, Any] = field(default_factory=dict)


class BaseClassifierNode(NodeType):
    """Classifier node with a template-method run().

    Subclasses must set *model_family* as a class attribute and implement the
    three abstract hooks below.
    """

    model_family: str = ""

    def _check_dependencies(self) -> None:
        """Optional pre-flight check (import, optional deps, etc.)."""

    def _get_estimator_class(self):
        """Return the estimator class to instantiate (e.g. ``DecisionTreeClassifier``)."""
        raise NotImplementedError

    def _build_estimator_kwargs(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return keyword arguments for the estimator constructor from *params*."""
        raise NotImplementedError

    def _post_fit(
        self,
        clf,
        features: list[str],
        df: pl.DataFrame,
        params: dict[str, Any],
        *,
        bad_class: str,
        good_class: str,
        feature_importance: dict[str, float],
        prob_col_idx: int,
    ) -> _ClassifierResult:
        """Return the varying parts of the model artifact after fitting.

        Called after the estimator has been fitted and feature_importance /
        prob_col_idx have been computed.  Subclasses inspect *clf* and *df*
        to build model_payload, interpretability, training_params, warnings,
        and extra_metrics.
        """
        raise NotImplementedError

    def run(self, context: ExecutionContext) -> NodeOutput:
        self._check_dependencies()
        estimator_class = self._get_estimator_class()
        params = context.validated_params
        step_id = context.step_spec.step_id

        # 1. Prepare training data
        df, features, target_column, good_values, bad_values, y_binary, _ = (
            _prepare_training_data(context, params)
        )
        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        random_seed = int(params.get("random_seed", 42))

        # 2. Build estimator kwargs
        kwargs = self._build_estimator_kwargs(params)

        # 2b. Validate kwargs against constructor signature.
        # Raise on unknown params instead of silently dropping them.
        sig = inspect.signature(estimator_class.__init__)
        valid_init_params = {p for p in sig.parameters if p != "self"}
        has_var_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        )
        if not has_var_kwargs:
            unknown = {k for k in kwargs if k not in valid_init_params}
            if unknown:
                raise ValueError(
                    f"Unknown parameters for {estimator_class.__name__}: "
                    f"{sorted(unknown)}. Valid params: {sorted(valid_init_params)}"
                )
            kwargs = {k: v for k, v in kwargs.items() if k in valid_init_params}

        # 3. Fit
        start_time = time.monotonic()
        clf = estimator_class(**kwargs)
        X = df.select(features).to_numpy()
        clf.fit(X, y_binary)
        elapsed = time.monotonic() - start_time

        # 3b. Optional cross-validation
        cv_folds = int(params.get("cv_folds", 0))
        cv_results = None
        if cv_folds > 0:
            cv_results = cross_validate(
                estimator_class(**kwargs), X, y_binary,  # kwargs already filtered above
                cv=StratifiedKFold(n_splits=cv_folds),
                scoring=["roc_auc", "f1_macro"],
                return_train_score=True, n_jobs=-1,
            )

        # 4. Find prob_col_idx
        prob_col_idx = 1
        for idx, cls_label in enumerate(clf.classes_):
            if cls_label == 1:
                prob_col_idx = idx
                break

        # 5. Feature importance
        feature_importance = {
            fname: round(float(imp), 6)
            for fname, imp in zip(features, clf.feature_importances_, strict=False)
            if imp > 0
        }

        # 6. Varying parts
        result = self._post_fit(
            clf, features, df, params,
            bad_class=bad_class, good_class=good_class,
            feature_importance=feature_importance,
            prob_col_idx=prob_col_idx,
        )

        # 6b. CV overfitting warning
        if cv_folds > 0 and cv_results is not None:
            train_roc = cv_results["train_roc_auc"].mean()
            test_roc = cv_results["test_roc_auc"].mean()
            if test_roc < train_roc - 0.1:
                result.warnings.append({
                    "message": (
                        f"Overfitting detected: test ROC-AUC ({test_roc:.4f}) "
                        f"is more than 0.1 below train ROC-AUC ({train_roc:.4f})"
                    ),
                })

        # 7. Persist binary estimator
        estimator_art = _write_estimator(
            context.store, clf, step_id, context.run_id, self.model_family,
        )

        # 8. Build model artifact
        model = build_model_artifact(
            model_family=self.model_family,
            target_column=target_column,
            features=features,
            bad_class=bad_class,
            good_class=good_class,
            prob_col_idx=prob_col_idx,
            feature_strategy=params.get("feature_strategy", "raw_numeric"),
            estimator_art=estimator_art,
            training_params=result.training_params,
            random_seed=random_seed,
            elapsed=elapsed,
            model_payload=result.model_payload,
            interpretability=result.interpretability,
            context=context,
            extra_metrics=result.extra_metrics,
            warnings_list=result.warnings,
            row_count=df.height,
        )

        # 8b. Cross-validation results
        if cv_folds > 0 and cv_results is not None:
            model["training"]["cross_validation"] = {
                "folds": cv_folds,
                "train_roc_auc": round(float(cv_results["train_roc_auc"].mean()), 4),
                "test_roc_auc": round(float(cv_results["test_roc_auc"].mean()), 4),
                "train_f1_macro": round(float(cv_results["train_f1_macro"].mean()), 4),
                "test_f1_macro": round(float(cv_results["test_f1_macro"].mean()), 4),
            }

        # 8c. Native importance data source annotation
        if hasattr(clf, "feature_importances_") and clf.feature_importances_ is not None:
            model["interpretability"]["native_importance_source"] = "training_data"

        # 9. Write JSON artifact
        artifact_metadata = {
            "feature_count": len(features),
            "target_column": target_column,
            "model_family": self.model_family,
            **{k: v for k, v in result.extra_metrics.items() if isinstance(v, (str, int, float))},
        }
        artifact = write_json_artifact(
            context.store, artifact_type="model", role="model",
            stem=f"{self.model_family}-model-{step_id}",
            payload=model,
            metadata=artifact_metadata,
        )

        # 10. Build metrics
        metrics: dict[str, Any] = {
            "feature_count": len(features),
        }
        metrics.update(
            {k: v for k, v in result.extra_metrics.items() if isinstance(v, (int, float))}
        )

        return NodeOutput(
            artifacts=[artifact, estimator_art],
            metrics=metrics,
        )
