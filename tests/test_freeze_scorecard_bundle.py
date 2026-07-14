from __future__ import annotations

import json
import uuid
from pathlib import Path

import polars as pl

from cardre._evidence.schemas import (
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_MODELLING_METADATA,
    SCHEMA_SCORE_SCALING,
    SCHEMA_WOE_TABLE,
)
from cardre.domain.artifacts import ArtifactRef, json_logical_hash
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec
from cardre.execution.context import ExecutionContext
from cardre.nodes.build.freeze import FrozenScorecardBundleNode

SCHEMA_BIN_DEFINITION = "cardre.bin_definition.v1"


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore

    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _register_artifact(
    store,
    artifact_id: str,
    artifact_type: str,
    role: str,
    path: Path,
    *,
    schema_version: str | None = None,
    media_type: str = "application/json",
):
    metadata = {}
    if schema_version:
        metadata["schema_version"] = schema_version
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            artifact_id,
            artifact_type,
            role,
            str(path),
            f"ph-{artifact_id}",
            f"lh-{artifact_id}",
            media_type,
            utc_now_iso(),
            json.dumps(metadata),
        ),
    )


def test_freeze_bundle_allows_missing_scorecard_intercept(tmp_path):
    store = _make_store(tmp_path)
    order_hash = json_logical_hash({"features": ["age_woe"]})

    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps({
        "schema_version": SCHEMA_MODELLING_METADATA,
        "target_column": "default_flag",
        "good_values": ["0"],
        "bad_values": ["1"],
    }))
    _register_artifact(store, "meta-art", "definition", "definition", meta_path, schema_version=SCHEMA_MODELLING_METADATA)

    bin_def_path = tmp_path / "bin_def.json"
    bin_def_path.write_text(json.dumps({
        "schema_version": SCHEMA_BIN_DEFINITION,
        "variables": [{
            "variable": "age",
            "dtype": "numeric",
            "kind": "fine",
            "bins": [{"bin_id": "b1", "label": "all", "lower": 0, "upper": 100}],
        }],
    }))
    _register_artifact(store, "bin-art", "definition", "definition", bin_def_path, schema_version=SCHEMA_BIN_DEFINITION)

    woe_path = tmp_path / "woe.parquet"
    pl.DataFrame({"variable": ["age"], "bin_id": ["b1"], "woe": [0.5]}).write_parquet(woe_path)
    _register_artifact(store, "woe-art", "report", "report", woe_path, schema_version=SCHEMA_WOE_TABLE, media_type="application/vnd.apache.parquet")

    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps({
        "schema_version": SCHEMA_MODEL_ARTIFACT,
        "model_family": "logistic_regression",
        "target_column": "default_flag",
        "target_event_value": "1",
        "class_mapping": {"good": "0", "bad": "1"},
        "probability_column_index": 1,
        "source_variables": ["age"],
        "feature_contract": {
            "features": ["age_woe"],
            "transformation_strategy": "woe",
            "order_hash": order_hash,
            "missing_policy": "error",
            "unknown_category_policy": "error",
        },
        "feature_order_hash": order_hash,
        "model_payload": {
            "intercept": -0.5,
            "coefficients": {"age_woe": 1.2},
        },
        "training": {"row_count": 100, "converged": True, "iterations": 12, "params": {}},
        "warnings": [],
    }))
    _register_artifact(store, "model-art", "model", "model", model_path, schema_version=SCHEMA_MODEL_ARTIFACT)

    scorecard_path = tmp_path / "scorecard.json"
    scorecard_path.write_text(json.dumps({
        "schema_version": SCHEMA_SCORE_SCALING,
        "base_score": 600,
        "base_odds": "50:1",
        "points_to_double_odds": 20,
        "factor": 28.8539,
        "offset": 487.1229,
        "score_direction": "higher_is_lower_risk",
        "base_points": 500.0,
        "target_column": "default_flag",
        "attributes": [{
            "variable": "age",
            "bin_id": "b1",
            "label": "all",
            "woe": 0.5,
            "coefficient": 1.2,
            "points": 15,
        }],
    }))
    _register_artifact(store, "scorecard-art", "scorecard", "scorecard", scorecard_path, schema_version=SCHEMA_SCORE_SCALING)

    ctx = ExecutionContext(
        store=store,
        run_id=str(uuid.uuid4()),
        plan_version_id="pv-1",
        step_spec=StepSpec(
            step_id="freeze-1",
            node_type="cardre.freeze_scorecard_bundle",
            node_version="1",
            category="fit",
            params={},
            params_hash="hash-freeze",
            parent_step_ids=[],
            branch_label="",
            position=0,
        ),
        parent_run_steps=[],
        input_artifacts=[
            ArtifactRef("meta-art", "definition", "definition", str(meta_path), "ph", "lh", metadata={"schema_version": SCHEMA_MODELLING_METADATA}),
            ArtifactRef("bin-art", "definition", "definition", str(bin_def_path), "ph", "lh", metadata={"schema_version": SCHEMA_BIN_DEFINITION}),
            ArtifactRef("woe-art", "report", "report", str(woe_path), "ph", "lh", media_type="application/vnd.apache.parquet", metadata={"schema_version": SCHEMA_WOE_TABLE}),
            ArtifactRef("model-art", "model", "model", str(model_path), "ph", "lh", metadata={"schema_version": SCHEMA_MODEL_ARTIFACT}),
            ArtifactRef("scorecard-art", "scorecard", "scorecard", str(scorecard_path), "ph", "lh", metadata={"schema_version": SCHEMA_SCORE_SCALING}),
        ],
        validated_params={},
        runtime_metadata={},
    )

    output = FrozenScorecardBundleNode().run(ctx)

    assert len(output.artifacts) == 1
    bundle_path = store.artifact_path(output.artifacts[0])
    bundle = json.loads(bundle_path.read_text())
    assert bundle["schema_version"] == SCHEMA_FROZEN_SCORECARD_BUNDLE
    assert bundle["score_scaling"]["intercept"] == 0.0
    assert bundle["feature_contract"]["source_variables"] == ["age"]
