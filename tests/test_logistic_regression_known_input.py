"""Integration test: LogisticRegressionNode.run() with known fixtures.

Exercises the actual node code path (reader, artifact resolution, sklearn fit,
helper functions) against tiny synthetic inputs so we can assert on exact model
artifact output shape: features, source_variables, coefficients, intercept,
class_mapping, probability_column_index, training params, and convergence
metadata.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import polars as pl
import pytest

from cardre._evidence.schemas import SCHEMA_MODELLING_METADATA
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec
from cardre.execution.context import ExecutionContext
from cardre.nodes.build.models import LogisticRegressionNode


def _seed_project_and_plan(store) -> tuple[str, str]:
    """Create a minimal project with one plan version. Returns (project_id, pv_id)."""
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "LR Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )
    return project_id, pv_id


def _register_artifact(
    store,
    artifact_id: str,
    artifact_type: str,
    role: str,
    path: str,
    media_type: str = "application/json",
    schema_version: str | None = None,
) -> None:
    metadata = {}
    if schema_version:
        metadata["schema_version"] = schema_version
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, "
        "media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, artifact_type, role, path, "phys_hash", "log_hash",
         media_type, utc_now_iso(), json.dumps(metadata)),
    )


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def train_parquet(fixture_dir: Path) -> Path:
    """Write a tiny training parquet with WOE columns and a binary target."""
    df = pl.DataFrame({
        "age_woe": [0.5, -0.3, 0.1, -0.2, 0.4],
        "income_woe": [-0.1, 0.2, -0.4, 0.3, -0.2],
        "default_flag": ["good", "bad", "good", "bad", "good"],
    })
    path = fixture_dir / "train.parquet"
    df.write_parquet(path)
    return path


@pytest.fixture
def modelling_metadata_payload() -> dict:
    """A minimal modelling-metadata JSON payload."""
    return {
        "target_column": "default_flag",
        "good_values": ["good"],
        "bad_values": ["bad"],
        "indeterminate_values": [],
    }


def test_logistic_regression_model_artifact_shape(
    store,
    fixture_dir: Path,
    train_parquet: Path,
    modelling_metadata_payload: dict,
) -> None:
    """Run LogisticRegressionNode.run() with known fixtures and assert model artifact shape."""
    _seed_project_and_plan(store)

    # --- Write modelling metadata artifact ---
    meta_path = fixture_dir / "modelling_metadata.json"
    meta_path.write_text(json.dumps(modelling_metadata_payload))
    meta_art_id = "meta-art-1"
    _register_artifact(
        store, meta_art_id, "definition", "definition",
        str(meta_path), schema_version=SCHEMA_MODELLING_METADATA,
    )

    # --- Write train artifact (parquet) ---
    train_art_id = "train-art-1"
    _register_artifact(
        store, train_art_id, "dataset", "train",
        str(train_parquet), media_type="application/vnd.apache.parquet",
    )

    # --- Retrieve ArtifactRefs from the store ---
    meta_art = store.get_artifact(meta_art_id)
    assert meta_art is not None
    train_art = store.get_artifact(train_art_id)
    assert train_art is not None

    # --- Build ExecutionContext ---
    step_spec = StepSpec(
        step_id="lr-1",
        node_type="cardre.logistic_regression",
        node_version="1",
        category="fit",
        params={
            "solver": "lbfgs",
            "C": 1.0,
            "max_iter": 1000,
            "random_seed": 42,
            "fail_on_non_convergence": True,
        },
        params_hash="dummy",
        parent_step_ids=[],
    )

    context = ExecutionContext(
        store=store,
        run_id="run-1",
        plan_version_id="pv-1",
        step_spec=step_spec,
        parent_run_steps=[],
        input_artifacts=[train_art, meta_art],
        validated_params={
            "solver": "lbfgs",
            "C": 1.0,
            "max_iter": 1000,
            "random_seed": 42,
            "fail_on_non_convergence": True,
        },
        runtime_metadata={},
    )

    # --- Run the node ---
    node = LogisticRegressionNode()
    output = node.run(context)

    # --- Assert on NodeOutput ---
    assert len(output.artifacts) == 1
    model_art = output.artifacts[0]
    assert model_art.artifact_type == "model"
    assert model_art.role == "model"

    # Read back the written model artifact payload
    model_path = store.artifact_path(model_art)
    raw = json.loads(model_path.read_bytes())

    # --- Verify model artifact shape ---
    assert raw["schema_version"] == "cardre.model_artifact.v1"
    assert raw["model_family"] == "logistic_regression"
    assert raw["target_column"] == "default_flag"

    # Features: the two WOE columns
    assert raw["features"] == ["age_woe", "income_woe"]

    # Source variables: derived from WOE column names (no selection definition)
    assert raw["source_variables"] == ["age", "income"]

    # Intercept and coefficients: rounded to 6 decimal places
    assert isinstance(raw["intercept"], float)
    assert len(str(raw["intercept"]).split(".")[1]) <= 6
    assert set(raw["coefficients"].keys()) == {"age_woe", "income_woe"}
    for coef in raw["coefficients"].values():
        assert isinstance(coef, float)
        assert len(str(coef).split(".")[1]) <= 6

    # Class mapping: good/bad labels
    assert raw["class_mapping"] == {"good": "good", "bad": "bad"}
    assert raw["bad_class_label"] == "bad"
    assert raw["target_event_value"] == "bad"

    # Probability column index: should be 1 (bad class is second in sklearn classes_)
    assert raw["probability_column_index"] == 1

    # Feature contract
    assert raw["feature_contract"]["features"] == ["age_woe", "income_woe"]
    assert raw["feature_contract"]["transformation_strategy"] == "woe"
    assert raw["feature_contract"]["missing_policy"] == "error"
    assert raw["feature_contract"]["unknown_category_policy"] == "error"
    assert "order_hash" in raw["feature_contract"]
    assert raw["feature_order_hash"] == raw["feature_contract"]["order_hash"]

    # Training block
    assert raw["training"]["row_count"] == 5
    assert raw["training"]["converged"] is True
    assert raw["training"]["iterations"] >= 1
    assert raw["training"]["params"]["C"] == 1.0
    assert raw["training"]["params"]["solver"] == "lbfgs"
    assert raw["training"]["params"]["max_iter"] == 1000
    assert raw["training"]["params"]["random_state"] == 42
    assert raw["training"]["params"]["penalty"] == "l2"

    # Warnings: should be empty for a converged model
    assert raw["warnings"] == []

    # Metrics
    assert output.metrics["feature_count"] == 2
    assert bool(output.metrics["converged"]) is True
