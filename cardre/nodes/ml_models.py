"""ML model nodes — decision tree, random forest, GBDT challengers.

Phase 2 adds the decision tree as the first non-logistic challenger.
Phase 3 adds random forest and GBDT using the same contract.
"""

from __future__ import annotations

import io
import time
from typing import Any

import joblib
import numpy as np
import polars as pl
from sklearn.tree import DecisionTreeClassifier, export_text

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    json_logical_hash,
)


def _extract_target_metadata(
    store,
    input_artifacts,
) -> tuple[str, set[str], set[str], dict | None]:
    """Extract target column, good/bad values, and raw metadata from definition artifacts."""
    reader = ArtifactEvidenceReader(store)
    meta = reader.find_optional(input_artifacts, EvidenceKind.MODELLING_METADATA)
    if meta is None:
        return "", set(), set(), {}
    return meta.target_column, set(str(v) for v in meta.good_values), set(str(v) for v in meta.bad_values), {}


def _resolve_features(
    df: pl.DataFrame,
    target_column: str,
    params: dict[str, Any],
) -> list[str]:
    """Resolve feature columns from params and dataframe, excluding target."""
    include_columns = list(params.get("include_columns", []))
    exclude_columns = list(params.get("exclude_columns", []))

    if target_column:
        exclude_columns = list(set(exclude_columns + [target_column]))

    if include_columns:
        missing = [c for c in include_columns if c not in df.columns]
        if missing:
            raise ValueError(f"include_columns references missing columns: {missing}")
        features = [c for c in include_columns if c not in exclude_columns]
    else:
        features = [c for c in df.columns if c not in exclude_columns]

    if not features:
        raise ValueError("No feature columns available after exclusions")

    non_numeric = [
        c for c in features
        if not df.schema[c].is_numeric()
    ]
    if non_numeric:
        raise ValueError(
            f"Non-numeric columns not supported without encoding: {non_numeric}. "
            f"Use include_columns to select only numeric features, or add an encoding node."
        )

    return features


def _extract_rules_from_tree(
    classifier: DecisionTreeClassifier,
    feature_names: list[str],
) -> list[dict]:
    """Extract human-readable rules from a fitted decision tree."""
    tree = classifier.tree_
    rules: list[dict] = []

    def _recurse(node_id: int, conditions: list[dict]) -> None:
        left_child = tree.children_left[node_id]
        right_child = tree.children_right[node_id]

        if left_child == right_child:
            samples = int(tree.n_node_samples[node_id])
            value = tree.value[node_id][0]
            total = float(value.sum())
            bad_prob = float(value[1] / total) if total > 0 and len(value) > 1 else 0.0
            prediction = int(classifier.classes_[np.argmax(value)])

            rules.append({
                "rule_id": len(rules) + 1,
                "leaf_id": int(node_id),
                "prediction": prediction,
                "probability": round(bad_prob, 6),
                "conditions": list(conditions),
                "sample_count": samples,
                "bad_count": int(value[1]) if len(value) > 1 else 0,
            })
            return

        feature_idx = int(tree.feature[node_id])
        threshold = float(tree.threshold[node_id])
        feature_name = feature_names[feature_idx] if feature_idx < len(feature_names) else f"feature_{feature_idx}"

        left_conditions = conditions + [{
            "feature": feature_name,
            "operator": "<=",
            "threshold": round(threshold, 6),
        }]
        right_conditions = conditions + [{
            "feature": feature_name,
            "operator": ">",
            "threshold": round(threshold, 6),
        }]

        _recurse(left_child, left_conditions)
        _recurse(right_child, right_conditions)

    _recurse(0, [])
    return rules


def _prepare_training_data(
    context: ExecutionContext,
    params: dict[str, Any],
) -> tuple[pl.DataFrame, list[str], str, set[str], set[str], np.ndarray, dict]:
    """Shared training data preparation for all sklearn model nodes.

    Returns (df, features, target_column, good_values, bad_values, y_binary, meta).
    """
    store = context.store
    train_artifact = next(a for a in context.input_artifacts if a.role == "train")

    target_column, good_values, bad_values, meta = _extract_target_metadata(
        store, context.input_artifacts,
    )

    if not target_column:
        raise ValueError("Target column is required")
    if not good_values:
        raise ValueError("Good values must be defined")
    if not bad_values:
        raise ValueError("Bad values must be defined")

    df = pl.read_parquet(store.artifact_path(train_artifact))

    if target_column not in df.columns:
        raise ValueError(f"Target column '{target_column}' not found in training data")

    features = _resolve_features(df, target_column, params)

    raw_target = df[target_column].cast(pl.String)
    y_raw = raw_target.to_list()
    all_known = good_values | bad_values
    unknown = [str(v) for v in y_raw if str(v) not in all_known]
    if unknown:
        unique_unknown = sorted(set(unknown))
        raise ValueError(
            f"Target column '{target_column}' contains {len(unknown)} value(s) "
            f"not declared as good or bad: {unique_unknown[:10]}. "
            f"Every row must be explicitly classified."
        )

    y_binary = [1 if str(v) in bad_values else 0 for v in y_raw]
    n_bad = sum(y_binary)
    n_good = len(y_binary) - n_bad
    if n_bad == 0:
        raise ValueError(f"No bad-class rows found (bad_values={sorted(bad_values)})")
    if n_good == 0:
        raise ValueError(f"No good-class rows found (good_values={sorted(good_values)})")

    return df, features, target_column, good_values, bad_values, np.array(y_binary), meta


def _write_estimator(store, clf, step_id: str, run_id: str, model_family: str):
    """Serialize a fitted sklearn estimator to a binary artifact."""
    buf = io.BytesIO()
    joblib.dump(clf, buf)
    estimator_bytes = buf.getvalue()
    from cardre.modeling.serialization import write_estimator_artifact
    return write_estimator_artifact(
        store,
        estimator_bytes=estimator_bytes,
        estimator_format="joblib",
        stem=f"{model_family}-estimator-{step_id}",
        creating_run_id=run_id,
        creating_run_step_id=step_id,
        metadata={"model_family": model_family},
    )


def _build_model_artifact(
    *,
    model_family: str,
    target_column: str,
    features: list[str],
    bad_class,
    good_class,
    prob_col_idx: int,
    feature_strategy: str,
    estimator_art,
    training_params: dict,
    random_seed: int,
    elapsed: float,
    model_payload: dict,
    interpretability: dict,
    context: ExecutionContext,
    extra_metrics: dict | None = None,
    warnings_list: list[dict] | None = None,
    row_count: int | None = None,
) -> dict:
    """Build a cardre.model_artifact.v1 JSON dict."""
    feature_order_hash = json_logical_hash({"features": features})

    class_mapping = {str(idx): str(label) for idx, label in enumerate([good_class, bad_class])}

    model: dict[str, Any] = {
        "schema_version": "cardre.model_artifact.v1",
        "model_family": model_family,
        "target_column": target_column,
        "features": features,
        "class_mapping": class_mapping,
        "bad_class_label": str(bad_class),
        "target_event_value": str(bad_class),
        "probability_column_index": prob_col_idx,
        "feature_order_hash": feature_order_hash,
        "feature_strategy": feature_strategy,
        "feature_contract": {
            "features": features,
            "transformation_strategy": feature_strategy,
        },
        "estimator_reference": {
            "artifact_id": estimator_art.artifact_id,
            "logical_hash": estimator_art.logical_hash,
            "physical_hash": estimator_art.physical_hash,
            "estimator_format": "joblib",
            "trusted_load_required": True,
            "creating_run_id": context.run_id,
            "creating_run_step_id": context.step_spec.step_id,
        },
        "training": {
            "row_count": row_count if row_count is not None else len(features),
            "params": training_params,
            "random_seed": random_seed,
            "elapsed_seconds": round(elapsed, 3),
        },
        "model_payload": model_payload,
        "interpretability": interpretability,
        "warnings": warnings_list or [],
    }
    if extra_metrics:
        model["training"].update(extra_metrics)
    return model


class DecisionTreeNode(NodeType):
    """Decision tree classifier — first non-logistic challenger.

    Produces a cardre.model_artifact.v1 JSON artifact plus a binary
    estimator artifact. Exports interpretable tree rules in JSON.
    """

    node_type = "cardre.decision_tree_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_FEATURE_STRATEGIES = {"raw_numeric", "encoded_raw", "woe_challenger"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        feature_strategy = params.get("feature_strategy", "")
        if feature_strategy not in self.VALID_FEATURE_STRATEGIES:
            errors.append(
                f"feature_strategy must be one of {sorted(self.VALID_FEATURE_STRATEGIES)}, "
                f"got {feature_strategy!r}"
            )

        max_depth = params.get("max_depth")
        if max_depth is not None:
            try:
                if int(max_depth) < 1:
                    errors.append("max_depth must be >= 1")
            except (ValueError, TypeError):
                errors.append("max_depth must be an integer")

        min_samples_leaf = params.get("min_samples_leaf", 1)
        try:
            if int(min_samples_leaf) < 1:
                errors.append("min_samples_leaf must be >= 1")
        except (ValueError, TypeError):
            errors.append("min_samples_leaf must be an integer")

        class_weight = params.get("class_weight")
        if class_weight is not None and class_weight != "balanced":
            if not isinstance(class_weight, dict):
                errors.append("class_weight must be 'balanced', a dict, or null")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        params = context.validated_params

        df, features, target_column, good_values, bad_values, y_binary, meta = (
            _prepare_training_data(context, params)
        )

        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        max_depth = params.get("max_depth")
        if max_depth is not None:
            max_depth = int(max_depth)
        min_samples_leaf = int(params.get("min_samples_leaf", 1))
        class_weight = params.get("class_weight")
        random_seed = int(params.get("random_seed", 42))

        dt_params: dict[str, Any] = {
            "max_depth": max_depth,
            "min_samples_leaf": min_samples_leaf,
            "random_state": random_seed,
        }
        if class_weight is not None:
            dt_params["class_weight"] = class_weight

        start_time = time.monotonic()
        clf = DecisionTreeClassifier(**dt_params)
        X = df.select(features).to_numpy()
        clf.fit(X, y_binary)
        elapsed = time.monotonic() - start_time

        prob_col_idx = 1
        for idx, cls_label in enumerate(clf.classes_):
            if cls_label == 1:
                prob_col_idx = idx
                break

        rules = _extract_rules_from_tree(clf, features)
        tree_depth = int(clf.get_depth())
        leaf_count = int(clf.get_n_leaves())
        feature_importance = {
            fname: round(float(imp), 6)
            for fname, imp in zip(features, clf.feature_importances_)
            if imp > 0
        }

        warnings_list: list[dict] = []
        if max_depth is not None and tree_depth >= max_depth:
            warnings_list.append({
                "code": "TREE_FULL_DEPTH",
                "message": f"Tree reached max_depth={max_depth}. Consider limiting depth for interpretability.",
            })

        limitations: list[str] = []
        if tree_depth > 5:
            limitations.append(f"Tree depth {tree_depth} may be hard to explain in governance contexts")
        if leaf_count > 20:
            limitations.append(f"Leaf count {leaf_count} reduces interpretability")
        limitations.append("Decision tree does not produce native scorecard points")

        training_params = {
            "max_depth": max_depth,
            "min_samples_leaf": min_samples_leaf,
            "class_weight": class_weight,
            "random_state": random_seed,
        }

        estimator_art = _write_estimator(context.store, clf, context.step_spec.step_id, context.run_id, "decision_tree")

        model_payload = {
            "tree_rules": rules,
            "tree_depth": tree_depth,
            "leaf_count": leaf_count,
            "feature_importance": feature_importance,
            "feature_count": len(features),
        }
        interpretability = {
            "explanation_type": "tree_rules",
            "explanation_level": "native_interpretable",
            "native_importance_available": True,
            "limitations": limitations,
            "global_importance_fields": ["feature_importance"],
        }

        model = _build_model_artifact(
            model_family="decision_tree",
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
            extra_metrics={"tree_depth": tree_depth, "leaf_count": leaf_count},
            warnings_list=warnings_list,
            row_count=df.height,
        )

        artifact = write_json_artifact(
            context.store, artifact_type="model", role="model",
            stem=f"decision-tree-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features),
                "target_column": target_column,
                "model_family": "decision_tree",
                "tree_depth": tree_depth,
                "leaf_count": leaf_count,
            },
        )

        return NodeOutput(
            artifacts=[artifact, estimator_art],
            metrics={
                "feature_count": len(features),
                "tree_depth": tree_depth,
                "leaf_count": leaf_count,
            })


class RandomForestClassifierNode(NodeType):
    """Random forest classifier — semi-transparent ensemble challenger.

    Produces a cardre.model_artifact.v1 JSON artifact plus a binary
    estimator artifact. Reports feature importance but is not fully
    interpretable like a single decision tree.
    """

    node_type = "cardre.random_forest_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_FEATURE_STRATEGIES = {"raw_numeric", "encoded_raw", "woe_challenger"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        feature_strategy = params.get("feature_strategy", "")
        if feature_strategy not in self.VALID_FEATURE_STRATEGIES:
            errors.append(
                f"feature_strategy must be one of {sorted(self.VALID_FEATURE_STRATEGIES)}, "
                f"got {feature_strategy!r}"
            )

        max_depth = params.get("max_depth")
        if max_depth is not None:
            try:
                if int(max_depth) < 1:
                    errors.append("max_depth must be >= 1")
            except (ValueError, TypeError):
                errors.append("max_depth must be an integer")

        n_estimators = params.get("n_estimators", 100)
        try:
            if int(n_estimators) < 1:
                errors.append("n_estimators must be >= 1")
        except (ValueError, TypeError):
            errors.append("n_estimators must be an integer")

        min_samples_leaf = params.get("min_samples_leaf", 1)
        try:
            if int(min_samples_leaf) < 1:
                errors.append("min_samples_leaf must be >= 1")
        except (ValueError, TypeError):
            errors.append("min_samples_leaf must be an integer")

        class_weight = params.get("class_weight")
        if class_weight is not None and class_weight != "balanced":
            if not isinstance(class_weight, dict):
                errors.append("class_weight must be 'balanced', a dict, or null")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        from sklearn.ensemble import RandomForestClassifier

        params = context.validated_params

        df, features, target_column, good_values, bad_values, y_binary, meta = (
            _prepare_training_data(context, params)
        )

        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        max_depth = params.get("max_depth")
        if max_depth is not None:
            max_depth = int(max_depth)
        n_estimators = int(params.get("n_estimators", 100))
        min_samples_leaf = int(params.get("min_samples_leaf", 1))
        class_weight = params.get("class_weight")
        random_seed = int(params.get("random_seed", 42))

        rf_params: dict[str, Any] = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "min_samples_leaf": min_samples_leaf,
            "random_state": random_seed,
            "n_jobs": -1,
        }
        if class_weight is not None:
            rf_params["class_weight"] = class_weight

        start_time = time.monotonic()
        clf = RandomForestClassifier(**rf_params)
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

        avg_tree_depth = int(np.mean([t.get_depth() for t in clf.estimators_]))
        avg_leaves = int(np.mean([t.get_n_leaves() for t in clf.estimators_]))

        warnings_list: list[dict] = []
        limitations: list[str] = [
            "Random forest is semi-transparent: feature importance is available "
            "but individual tree rules are not human-readable at ensemble scale",
            "Random forest does not produce native scorecard points",
        ]

        training_params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "min_samples_leaf": min_samples_leaf,
            "class_weight": class_weight,
            "random_state": random_seed,
        }

        estimator_art = _write_estimator(context.store, clf, context.step_spec.step_id, context.run_id, "random_forest")

        model_payload = {
            "feature_importance": feature_importance,
            "feature_count": len(features),
            "estimator_count": n_estimators,
            "avg_tree_depth": avg_tree_depth,
            "avg_leaves": avg_leaves,
        }
        interpretability = {
            "explanation_type": "feature_importance",
            "explanation_level": "native_semi_transparent",
            "native_importance_available": True,
            "limitations": limitations,
            "global_importance_fields": ["feature_importance"],
        }

        model = _build_model_artifact(
            model_family="random_forest",
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
            extra_metrics={"estimator_count": n_estimators, "avg_tree_depth": avg_tree_depth},
            warnings_list=warnings_list,
            row_count=df.height,
        )

        artifact = write_json_artifact(
            context.store, artifact_type="model", role="model",
            stem=f"random-forest-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features),
                "target_column": target_column,
                "model_family": "random_forest",
                "estimator_count": n_estimators,
                "avg_tree_depth": avg_tree_depth,
            },
        )

        return NodeOutput(
            artifacts=[artifact, estimator_art],
            metrics={
                "feature_count": len(features),
                "estimator_count": n_estimators,
                "avg_tree_depth": avg_tree_depth,
            })


class GradientBoostingClassifierNode(NodeType):
    """Sklearn gradient boosting classifier — semi-transparent ensemble challenger.

    Produces a cardre.model_artifact.v1 JSON artifact plus a binary
    estimator artifact. Feature importance is available; individual
    boosting iterations are not human-readable.
    """

    node_type = "cardre.gradient_boosting_classifier"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_FEATURE_STRATEGIES = {"raw_numeric", "encoded_raw", "woe_challenger"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        feature_strategy = params.get("feature_strategy", "")
        if feature_strategy not in self.VALID_FEATURE_STRATEGIES:
            errors.append(
                f"feature_strategy must be one of {sorted(self.VALID_FEATURE_STRATEGIES)}, "
                f"got {feature_strategy!r}"
            )

        n_estimators = params.get("n_estimators", 100)
        try:
            if int(n_estimators) < 1:
                errors.append("n_estimators must be >= 1")
        except (ValueError, TypeError):
            errors.append("n_estimators must be an integer")

        max_depth = params.get("max_depth", 3)
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

        min_samples_leaf = params.get("min_samples_leaf", 1)
        try:
            if int(min_samples_leaf) < 1:
                errors.append("min_samples_leaf must be >= 1")
        except (ValueError, TypeError):
            errors.append("min_samples_leaf must be an integer")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        from sklearn.ensemble import GradientBoostingClassifier

        params = context.validated_params

        df, features, target_column, good_values, bad_values, y_binary, meta = (
            _prepare_training_data(context, params)
        )

        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        n_estimators = int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 3))
        learning_rate = float(params.get("learning_rate", 0.1))
        min_samples_leaf = int(params.get("min_samples_leaf", 1))
        random_seed = int(params.get("random_seed", 42))

        gbdt_params: dict[str, Any] = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "min_samples_leaf": min_samples_leaf,
            "random_state": random_seed,
        }

        start_time = time.monotonic()
        clf = GradientBoostingClassifier(**gbdt_params)
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

        warnings_list: list[dict] = []
        limitations: list[str] = [
            "Gradient boosting is semi-transparent: feature importance is available "
            "but individual boosting iterations are not human-readable",
            "Gradient boosting does not produce native scorecard points",
        ]

        training_params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "min_samples_leaf": min_samples_leaf,
            "random_state": random_seed,
        }

        estimator_art = _write_estimator(context.store, clf, context.step_spec.step_id, context.run_id, "gbdt")

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

        model = _build_model_artifact(
            model_family="gbdt",
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
            warnings_list=warnings_list,
            row_count=df.height,
        )

        artifact = write_json_artifact(
            context.store, artifact_type="model", role="model",
            stem=f"gbdt-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features),
                "target_column": target_column,
                "model_family": "gbdt",
                "estimator_count": n_estimators,
            },
        )

        return NodeOutput(
            artifacts=[artifact, estimator_art],
            metrics={
                "feature_count": len(features),
                "estimator_count": n_estimators,
            })
