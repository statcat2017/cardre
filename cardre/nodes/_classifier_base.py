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

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType
from cardre.modeling.builders import build_model_artifact
from cardre.nodes._training_utils import _prepare_training_data, _write_estimator


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

        # 3. Fit
        start_time = time.monotonic()
        clf = estimator_class(**kwargs)
        X = df.select(features).to_numpy()
        clf.fit(X, y_binary)
        elapsed = time.monotonic() - start_time

        # 4. Find prob_col_idx
        prob_col_idx = 1
        for idx, cls_label in enumerate(clf.classes_):
            if cls_label == 1:
                prob_col_idx = idx
                break

        # 5. Feature importance
        feature_importance = {
            fname: round(float(imp), 6)
            for fname, imp in zip(features, clf.feature_importances_)
            if imp > 0
        }

        # 6. Varying parts
        result = self._post_fit(
            clf, features, df, params,
            bad_class=bad_class, good_class=good_class,
            feature_importance=feature_importance,
            prob_col_idx=prob_col_idx,
        )

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
