"""Integration test: ScoreScalingNode.run() with known fixtures.

Exercises the actual node code path (reader, artifact resolution, helper
functions) against tiny synthetic inputs so we can assert on exact numeric
outputs for factor, offset, base_points, and attributes.
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import polars as pl
import pytest

from cardre._evidence.schemas import SCHEMA_MODEL_ARTIFACT
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec
from cardre.execution.context import ExecutionContext
from cardre.nodes.build._logit_helpers import WOE_ROUND
from cardre.nodes.build.models import ScoreScalingNode
from cardre.store.artifact_repo import ArtifactRepository

# ------------------------------------------------------------------
# Helper: seed a minimal project + plan + plan_version
# ------------------------------------------------------------------

def _seed_project_and_plan(store) -> tuple[str, str]:
    """Create a minimal project with one plan version. Returns (project_id, pv_id)."""
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Score Scaling Test", now, "0.2.0"),
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


# ------------------------------------------------------------------
# Helper: register an artifact in the store
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def model_artifact_payload() -> dict:
    """A minimal model-artifact JSON payload matching SCHEMA_MODEL_ARTIFACT."""
    return {
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "default_flag",
        "intercept": -0.5,
        "coefficients": {
            "age_woe": 1.2,
            "income_woe": -0.8,
        },
        "features": ["age_woe", "income_woe"],
        "source_variables": ["age", "income"],
        "class_mapping": {"good": "0", "bad": "1"},
        "bad_class_label": "1",
        "target_event_value": "1",
        "probability_column_index": 1,
        "feature_contract": {
            "features": ["age_woe", "income_woe"],
            "transformation_strategy": "woe",
            "order_hash": "abc",
            "missing_policy": "error",
            "unknown_category_policy": "error",
        },
        "feature_order_hash": "abc",
        "training": {
            "row_count": 100,
            "converged": True,
            "iterations": 15,
            "params": {"C": 1.0},
        },
        "warnings": [],
    }


@pytest.fixture
def bin_def_payload() -> dict:
    """A minimal bin-definition payload matching SCHEMA_BIN_DEFINITION."""
    return {
        "schema_version": "cardre.bin_definition.v1",
        "variables": [
            {
                "variable": "age",
                "dtype": "numeric",
                "kind": "fine",
                "bins": [
                    {"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30},
                    {"bin_id": "b2", "label": "31-50", "lower": 31, "upper": 50},
                ],
            },
            {
                "variable": "income",
                "dtype": "numeric",
                "kind": "fine",
                "bins": [
                    {"bin_id": "b3", "label": "Low", "lower": 0, "upper": 30000},
                ],
            },
        ],
    }


@pytest.fixture
def woe_table_parquet(fixture_dir: Path) -> Path:
    """Write a tiny WOE table parquet to disk and return its path."""
    df = pl.DataFrame({
        "variable": ["age", "age", "income"],
        "bin_id": ["b1", "b2", "b3"],
        "woe": [0.5, -0.3, 0.2],
    })
    path = fixture_dir / "woe_table.parquet"
    df.write_parquet(path)
    return path


# ------------------------------------------------------------------
# Test
# ------------------------------------------------------------------

def test_score_scaling_with_known_input(
    store,
    fixture_dir: Path,
    model_artifact_payload: dict,
    bin_def_payload: dict,
    woe_table_parquet: Path,
) -> None:
    """Run ScoreScalingNode.run() with known fixtures and assert exact outputs."""
    # Seed project & plan
    _seed_project_and_plan(store)

    # --- Write model artifact ---
    model_path = fixture_dir / "model.json"
    model_path.write_text(json.dumps(model_artifact_payload))
    model_art_id = "model-art-1"
    _register_artifact(
        store, model_art_id, "model", "model",
        str(model_path), schema_version=SCHEMA_MODEL_ARTIFACT,
    )

    # --- Write bin definition ---
    bin_def_path = fixture_dir / "bin_def.json"
    bin_def_path.write_text(json.dumps(bin_def_payload))
    bin_def_art_id = "bin-def-art-1"
    _register_artifact(
        store, bin_def_art_id, "definition", "definition",
        str(bin_def_path), schema_version="cardre.bin_definition.v1",
    )

    # --- Write WOE table (parquet) ---
    woe_art_id = "woe-table-art-1"
    _register_artifact(
        store, woe_art_id, "report", "report",
        str(woe_table_parquet), media_type="application/vnd.apache.parquet",
    )

    # --- Retrieve ArtifactRefs from the store ---
    model_art = ArtifactRepository(store).get(model_art_id)
    assert model_art is not None
    bin_def_art = ArtifactRepository(store).get(bin_def_art_id)
    assert bin_def_art is not None
    woe_art = ArtifactRepository(store).get(woe_art_id)
    assert woe_art is not None

    # --- Build ExecutionContext ---
    step_spec = StepSpec(
        step_id="score-scaling-1",
        node_type="cardre.score_scaling",
        node_version="1",
        category="fit",
        params={"base_score": 600, "base_odds": "50:1", "points_to_double_odds": 20.0,
                "higher_score_is_lower_risk": True},
        params_hash="dummy",
        parent_step_ids=[],
    )

    context = ExecutionContext(
        store=store,
        run_id="run-1",
        plan_version_id="pv-1",
        step_spec=step_spec,
        parent_run_steps=[],
        input_artifacts=[model_art, bin_def_art, woe_art],
        validated_params={
            "base_score": 600,
            "base_odds": "50:1",
            "points_to_double_odds": 20.0,
            "higher_score_is_lower_risk": True,
        },
        runtime_metadata={},
    )

    # --- Run the node ---
    node = ScoreScalingNode()
    output = node.run(context)

    # --- Assert on NodeOutput ---
    assert len(output.artifacts) == 1
    scorecard_art = output.artifacts[0]
    assert scorecard_art.artifact_type == "scorecard"
    assert scorecard_art.role == "scorecard"

    # Read back the written scorecard payload
    scorecard_path = store.artifact_path(scorecard_art)
    raw = json.loads(scorecard_path.read_bytes())

    # --- Verify known math ---
    base_score = 600.0
    base_odds = 50.0
    pdo = 20.0
    factor = pdo / math.log(2)  # ~28.8539
    offset = base_score - factor * math.log(base_odds)  # ~487.155
    direction = -1.0  # higher_is_lower_risk = True
    intercept = -0.5

    expected_factor = round(factor, WOE_ROUND)
    expected_offset = round(offset, WOE_ROUND)
    expected_base_points = round(offset + direction * factor * intercept, 2)

    assert raw["factor"] == pytest.approx(expected_factor)
    assert raw["offset"] == pytest.approx(expected_offset)
    assert raw["base_points"] == pytest.approx(expected_base_points)
    assert raw["base_score"] == base_score
    assert raw["base_odds"] == base_odds
    assert raw["points_to_double_odds"] == pdo
    assert raw["higher_score_is_lower_risk"] is True
    assert raw["intercept"] == intercept
    assert raw["target_column"] == "default_flag"

    # --- Verify attributes ---
    attributes = raw["attributes"]
    # We have 3 bins: age b1, age b2, income b3
    assert len(attributes) == 3

    # Attribute 1: age / b1 — woe=0.5, coef=1.2
    attr1 = attributes[0]
    assert attr1["variable"] == "age"
    assert attr1["bin_id"] == "b1"
    assert attr1["label"] == "18-30"
    assert attr1["woe"] == round(0.5, WOE_ROUND)
    assert attr1["coefficient"] == 1.2
    expected_pts1 = round(direction * factor * 1.2 * 0.5, 2)
    assert attr1["points"] == expected_pts1

    # Attribute 2: age / b2 — woe=-0.3, coef=1.2
    attr2 = attributes[1]
    assert attr2["variable"] == "age"
    assert attr2["bin_id"] == "b2"
    assert attr2["woe"] == round(-0.3, WOE_ROUND)
    expected_pts2 = round(direction * factor * 1.2 * (-0.3), 2)
    assert attr2["points"] == expected_pts2

    # Attribute 3: income / b3 — woe=0.2, coef=-0.8
    attr3 = attributes[2]
    assert attr3["variable"] == "income"
    assert attr3["bin_id"] == "b3"
    assert attr3["woe"] == round(0.2, WOE_ROUND)
    assert attr3["coefficient"] == -0.8
    expected_pts3 = round(direction * factor * (-0.8) * 0.2, 2)
    assert attr3["points"] == expected_pts3

    # --- Verify metrics ---
    assert output.metrics["attribute_count"] == 3
