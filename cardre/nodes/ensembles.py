"""Advanced ensemble nodes — voting, weighted, and stacking.

Phase 10 adds research-level ensemble methods. These are advanced
challengers hidden from default governed templates. All ensemble
nodes consume explicitly selected fitted model artifact IDs and
record full lineage for auditability.
"""

from __future__ import annotations

import io
from typing import Any, cast

import joblib
import numpy as np
import polars as pl

from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.store.artifact_repo import ArtifactRepository


def _load_estimator(store: Any, estimator_ref: dict[str, Any]) -> Any:
    """Load a fitted estimator from an estimator reference."""
    artifact_id = estimator_ref.get("artifact_id", "")
    if not artifact_id:
        raise ValueError("estimator_reference.artifact_id is required")

    from cardre.modeling.serialization import read_estimator_artifact
    art = ArtifactRepository(store).get(artifact_id)
    if art is None:
        raise ValueError(f"Estimator artifact {artifact_id!r} not found")

    estimator_bytes = read_estimator_artifact(
        store, art,
        expected_logical_hash=estimator_ref.get("logical_hash"),
    )
    return cast(Any, joblib.load(io.BytesIO(estimator_bytes)))


def _load_model_artifact(reader: ArtifactEvidenceReader, artifact_id: str) -> dict[str, Any]:
    """Load a model JSON artifact by ID."""
    art = ArtifactRepository(reader._store).get(artifact_id)
    if art is None:
        raise ValueError(f"Model artifact {artifact_id!r} not found")
    typed = reader.require_model(art, "ensemble")
    return cast("dict[str, Any]", typed.to_dict())


def _get_predictions(
    store: Any, model: dict[str, Any], df: pl.DataFrame, features: list[str],
) -> np.ndarray[Any, Any]:
    """Get probability predictions from a model artifact on a dataframe."""
    model_family = model.get("model_family", "")
    prob_col_idx = model.get("probability_column_index", 1)

    if model_family == "logistic_regression":
        coefs = model.get("coefficients", {})
        intercept = float(model.get("intercept", 0))
        X = df.select(features).to_numpy()
        log_odds = np.full(X.shape[0], intercept, dtype=np.float64)
        for i, feat in enumerate(features):
            log_odds += float(coefs.get(feat, 0)) * X[:, i]
        return cast(np.ndarray[Any, Any], 1.0 / (1.0 + np.exp(-log_odds)))
    else:
        estimator_ref = model.get("estimator_reference", {})
        estimator = _load_estimator(store, estimator_ref)
        X = df.select(features).to_numpy()
        if hasattr(estimator, "predict_proba"):
            proba = estimator.predict_proba(X)
            if proba.shape[1] > prob_col_idx:
                return cast(np.ndarray[Any, Any], proba[:, prob_col_idx])
            return cast(np.ndarray[Any, Any], proba[:, -1])
        return cast(np.ndarray[Any, Any], estimator.predict(X).astype(np.float64))


# StackingEnsembleNode is deferred until fold-level base-model artifacts and
# leakage-safe lineage semantics are implemented. The class and apply dispatch
# were removed to avoid advertising a known-bad path. See PR #24 review for details.
