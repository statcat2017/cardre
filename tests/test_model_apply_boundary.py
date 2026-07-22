"""Tests for model apply boundary contracts (#218).

Tests the production adapter code path, not copied logic.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import joblib
import numpy as np
import pytest

from cardre.domain.diagnostics import utc_now_iso

pytestmark = pytest.mark.xfail(reason="Uses old ExecutionContext; needs NodeContext update")


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_project_and_plan(store):
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) "
        "VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) "
        "VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions"
        " (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    return project_id, pv_id


def _write_estimator_artifact(store, estimator):
    from cardre.domain.artifacts import ArtifactRef

    artifact_id = str(uuid.uuid4())
    now = utc_now_iso()
    buf = io.BytesIO()
    joblib.dump(estimator, buf)
    raw_bytes = buf.getvalue()

    est_path = store.root / "artifacts" / f"{artifact_id}.joblib"
    est_path.parent.mkdir(parents=True, exist_ok=True)
    est_path.write_bytes(raw_bytes)

    store.execute(
        "INSERT INTO artifacts"
        " (artifact_id, artifact_type, role, path, physical_hash, logical_hash,"
        "  media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            artifact_id,
            "estimator",
            "estimator",
            f"artifacts/{artifact_id}.joblib",
            "",
            "",
            "application/octet-stream",
            now,
            json.dumps({"creating_run_id": "run-1"}),
        ),
    )
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type="estimator",
        role="estimator",
        path=f"artifacts/{artifact_id}.joblib",
        physical_hash="",
        logical_hash="",
        media_type="application/octet-stream",
        created_at=now,
        metadata={"creating_run_id": "run-1"},
    )


def test_write_estimator_artifact_registers_with_repository(tmp_path):
    from cardre.modeling.serialization import write_estimator_artifact
    from cardre.store.artifact_repo import ArtifactRepository

    store = _make_store(tmp_path)
    try:
        buf = io.BytesIO()
        joblib.dump(FakeEstimator(), buf)
        artifact = write_estimator_artifact(
            store,
            estimator_bytes=buf.getvalue(),
            estimator_format="joblib",
            stem="test-estimator",
            creating_run_id="run-1",
            creating_run_step_id="step-1",
            metadata={"model_family": "sklearn"},
        )

        stored = ArtifactRepository(store).get(artifact.artifact_id)
        assert stored is not None
        assert stored.artifact_id == artifact.artifact_id
        assert stored.metadata["creating_run_id"] == "run-1"
        assert stored.metadata["creating_run_step_id"] == "step-1"
        assert stored.metadata["model_family"] == "sklearn"
        assert store.artifact_path(stored).exists()
    finally:
        store.close()


class FakeEstimator:
    """Minimal estimator with predict_proba returning 2 columns."""

    n_classes_ = 2

    def predict_proba(self, X):
        return np.array([[0.3, 0.7]] * len(X))


def test_apply_sklearn_estimator_raises_on_invalid_prob_col_idx(tmp_path):
    """apply_sklearn_estimator raises on out-of-range prob_col_idx via production code (#218)."""
    from cardre.domain.artifacts import ArtifactRef
    from cardre.execution.context import ExecutionContext

    store = _make_store(tmp_path)
    _seed_project_and_plan(store)

    est_art = _write_estimator_artifact(store, FakeEstimator())

    data_art = ArtifactRef(
        artifact_id="data-1",
        artifact_type="dataset",
        role="train",
        path="datasets/train.parquet",
        physical_hash="",
        logical_hash="",
        media_type="application/octet-stream",
        created_at=utc_now_iso(),
        metadata={},
    )

    import polars as pl

    df = pl.DataFrame({"f1": [1.0, 2.0]})
    df.write_parquet(store.root / "datasets" / "train.parquet")

    model = {
        "model_family": "sklearn",
        "estimator_reference": {"artifact_id": est_art.artifact_id},
        "feature_contract": {"features": ["f1"]},
        "probability_column_index": 99,
    }

    model_art = ArtifactRef(
        artifact_id="model-1",
        artifact_type="model",
        role="model",
        path="models/model.json",
        physical_hash="",
        logical_hash="",
        media_type="application/json",
        created_at=utc_now_iso(),
        metadata={},
    )

    context = ExecutionContext(
        store=store,
        run_id="run-1",
        plan_version_id="pv-1",
        step_spec=None,
        parent_run_steps=[],
        input_artifacts=[data_art],
        validated_params={},
        runtime_metadata={},
    )

    with pytest.raises(ValueError, match="out of range"):
        # Import lazily to avoid circular import — the adapter is accessible
        # via the node that wraps it.
        from cardre.modeling.adapters import apply_sklearn_estimator

        apply_sklearn_estimator(
            context=context,
            model=model,
            model_art=model_art,
        )
