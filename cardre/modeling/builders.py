"""Centralized model artifact builders.

Consolidates model-artifact construction logic from cardre.nodes.ml_models,
cardre.nodes.build, and cardre.nodes.ensembles into a single builder
backed by the cardre.model_artifact.v1 schema.
"""

from __future__ import annotations

from typing import Any

from cardre.execution.context import ExecutionContext
from cardre.domain.artifacts import json_logical_hash


def build_model_artifact(
    *,
    model_family: str,
    target_column: str,
    features: list[str],
    bad_class,
    good_class,
    prob_col_idx: int,
    feature_strategy: str,
    estimator_art,
    training_params: dict[str, Any],
    random_seed: int,
    elapsed: float,
    model_payload: dict[str, Any],
    interpretability: dict[str, Any],
    context: ExecutionContext,
    extra_metrics: dict[str, Any] | None = None,
    warnings_list: list[dict[str, Any]] | None = None,
    row_count: int | None = None,
) -> dict[str, Any]:
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

