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
and NodeResult assembly.

Callers and tests see the same public interface (run(context) -> NodeResult).
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import polars as pl
from sklearn.model_selection import StratifiedKFold, cross_validate

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_MODEL_ARTIFACT
from cardre.modeling.builders import build_model_artifact
from cardre.nodes._model_artifacts import publish_estimator, stage_estimator_bytes
from cardre.nodes._training_utils import prepare_supervised_training_data
from cardre.nodes.contracts import NodeContext, NodeResult, NodeType


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

    def _get_estimator_class(self) -> type[Any]:
        """Return the estimator class to instantiate (e.g. ``DecisionTreeClassifier``)."""
        raise NotImplementedError

    def _build_estimator_kwargs(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return keyword arguments for the estimator constructor from *params*."""
        raise NotImplementedError

    def _post_fit(
        self,
        clf: Any,
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

    def run(self, context: NodeContext) -> NodeResult:
        self._check_dependencies()
        estimator_class: type[Any] = self._get_estimator_class()
        params = context.params
        step_id = context.step_spec.step_id

        # 1. Prepare training data
        prepared = prepare_supervised_training_data(
            context.inputs,
            operation=self.node_type,
        )
        df = prepared.frame
        features = prepared.feature_columns(params)
        target_column = prepared.target_column
        y_binary = prepared.y_binary
        bad_class = sorted(prepared.bad_values)[0]
        good_class = sorted(prepared.good_values)[0]

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
        feature_importance: dict[str, float] = {
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

        # 7. Serialize the binary estimator and precompute its descriptor id so
        # the JSON model can reference it BEFORE the binary is staged. Publish
        # order matters: downstream `require("model")`/`first("model")` consumers
        # select the first model artifact by role, and it must be the parseable
        # JSON model, not the joblib blob (which the MODEL_ARTIFACT profile
        # rejects on media type).
        estimator_ref = publish_estimator(
            clf,
            step_id=step_id,
            run_id=context.run_id,
            model_family=self.model_family,
        )
        estimator_art = SimpleNamespace(
            artifact_id=None,
            provisional_artifact_id=estimator_ref.provisional_artifact_id,
            logical_hash=estimator_ref.logical_hash,
            physical_hash=estimator_ref.physical_hash,
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
            run_id=context.run_id,
            step_id=step_id,
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

        # 9. Write JSON artifact FIRST so role consumers pick it up
        artifact_metadata = {
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "feature_count": len(features),
            "target_column": target_column,
            "model_family": self.model_family,
            **{k: v for k, v in result.extra_metrics.items() if isinstance(v, (str, int, float))},
        }
        context.outputs.publish_json(
            role="model",
            kind=EvidenceKind.MODEL_ARTIFACT,
            payload=model,
            metadata=artifact_metadata,
        )

        # 10. Stage the binary estimator SECOND (same descriptor id as the
        # model's estimator_reference) under the distinct estimator role.
        stage_estimator_bytes(context.outputs, estimator_ref)

        # 10. Build metrics
        metrics: dict[str, Any] = {
            "feature_count": len(features),
        }
        metrics.update(
            {k: v for k, v in result.extra_metrics.items() if isinstance(v, (int, float))}
        )

        for name, value in metrics.items():
            context.outputs.add_metric(name, value)
        return context.outputs.build_result()
