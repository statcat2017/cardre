"""ScoreScalingNode with known fixtures produces known scores.

Restores the pre-refactor ``test_score_scaling_known_input`` parity oracle
against the post-rewrite node contract (``NodeContext`` + ``InputCollection``
+ ``StagingOutputPublisher``). The old test drove ``ExecutionContext``/legacy
store surfaces that Batch 07 deleted; the node math it pinned is unchanged.

Exercises the actual node code path (typed evidence resolution through the
reader, attribute building, factor/offset/base_points arithmetic) and asserts
on exact numeric outputs.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.input_collection import StepInputCollection
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_MODEL_ARTIFACT
from cardre.domain.step import StepSpec
from cardre.nodes.build._logit_helpers import POINTS_ROUND, WOE_ROUND
from cardre.nodes.build.models import ScoreScalingNode
from cardre.nodes.contracts import NodeContext, RuntimeMeta


class _NullRepo:
    def get(self, artifact_id):
        return None


class _StubArtifactRepo:
    def __init__(self, refs: list[ArtifactRef]):
        self._refs = {r.artifact_id: r for r in refs}

    def get(self, artifact_id):
        return self._refs.get(artifact_id)


def _staged_to_ref(staged: Any) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=staged.provisional_artifact_id,
        artifact_type=staged.artifact_type,
        role=staged.role,
        path=str(staged.staging_path),
        physical_hash=staged.physical_hash,
        logical_hash=staged.logical_hash,
        media_type=staged.media_type,
        metadata=staged.metadata,
    )


def _context(inputs: Any, outputs: Any, params: dict) -> NodeContext:
    spec = StepSpec(
        step_id="score-scaling-1",
        node_type="cardre.score_scaling",
        node_version="1",
        category="fit",
        params=params,
        params_hash="params-hash",
        parent_step_ids=[],
    )
    return NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=spec,
        inputs=inputs,
        outputs=outputs,
        params=params,
        runtime=RuntimeMeta("run-1", "plan-1", "score-scaling-1", "cardre.score_scaling"),
    )


def test_score_scaling_with_known_input(tmp_path: Path) -> None:
    """Run ScoreScalingNode.run() with known fixtures and assert exact outputs."""
    store = FsArtifactStore(tmp_path)
    pub = StagingOutputPublisher(store)

    # --- model artifact (intercept=-0.5, age_woe=1.2, income_woe=-0.8) ---
    model_staged = pub.publish_json(
        role="model",
        kind=EvidenceKind.MODEL_ARTIFACT,
        payload={
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "model_family": "logistic_regression",
            "target_column": "default_flag",
            "target_event_value": "1",
            "class_mapping": {"good": "0", "bad": "1"},
            "probability_column_index": 1,
            "feature_contract": {
                "features": ["age_woe", "income_woe"],
                "transformation_strategy": "woe",
                "order_hash": "abc",
                "missing_policy": "error",
                "unknown_category_policy": "error",
            },
            "model_payload": {
                "intercept": -0.5,
                "coefficients": {"age_woe": 1.2, "income_woe": -0.8},
            },
            "training": {"row_count": 100, "converged": True, "iterations": 15, "params": {"C": 1.0}},
            "warnings": [],
        },
        metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
    )

    # --- bin definition (age b1/b2, income b3) ---
    bin_def_staged = pub.publish_json(
        role="definition",
        kind=EvidenceKind.BIN_DEFINITION,
        payload={
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
        },
        metadata={"schema_version": "cardre.bin_definition.v1"},
    )

    # --- WOE table (parquet): age/b1=0.5, age/b2=-0.3, income/b3=0.2 ---
    woe_df = pl.DataFrame({
        "variable": ["age", "age", "income"],
        "bin_id": ["b1", "b2", "b3"],
        "woe": [0.5, -0.3, 0.2],
    })
    woe_staged = pub.publish_table(
        role="report",
        kind=EvidenceKind.WOE_TABLE,
        frame=woe_df,
    )

    for staged in (model_staged, bin_def_staged, woe_staged):
        store.finalize(staged)

    refs = [_staged_to_ref(model_staged), _staged_to_ref(bin_def_staged), _staged_to_ref(woe_staged)]
    reader = EvidenceReader(store, _StubArtifactRepo(refs), _NullRepo())
    inputs = StepInputCollection(reader, refs)
    outputs = StagingOutputPublisher(store)

    params = {
        "base_score": 600,
        "base_odds": "50:1",
        "points_to_double_odds": 20.0,
        "higher_score_is_lower_risk": True,
    }
    ScoreScalingNode().run(_context(inputs, outputs, params))

    assert outputs._staged_artifacts, "score_scaling published no outputs"
    scorecard = next((a for a in outputs._staged_artifacts if a.role == "scorecard"), None)
    assert scorecard is not None
    store.finalize(scorecard)
    raw = json.loads(store.read_bytes(_staged_to_ref(scorecard)))

    # --- Verify known math (unchanged from the pre-refactor oracle) ---
    base_score = 600.0
    base_odds = 50.0
    pdo = 20.0
    factor = pdo / math.log(2)
    offset = base_score - factor * math.log(base_odds)
    direction = -1.0  # higher_is_lower_risk = True
    intercept = -0.5

    expected_factor = round(factor, WOE_ROUND)
    expected_offset = round(offset, WOE_ROUND)
    expected_base_points = round(offset + direction * factor * intercept, POINTS_ROUND)

    assert raw["factor"] == pytest.approx(expected_factor)
    assert raw["offset"] == pytest.approx(expected_offset)
    assert raw["base_points"] == pytest.approx(expected_base_points)
    assert raw["base_score"] == base_score
    assert raw["base_odds"] == base_odds
    assert raw["points_to_double_odds"] == pdo
    assert raw["score_direction"] == "higher_is_lower_risk"
    assert raw["intercept"] == intercept
    assert raw["target_column"] == "default_flag"

    # --- Verify attributes ---
    attributes = raw["attributes"]
    assert len(attributes) == 3

    attr1 = attributes[0]
    assert attr1["variable"] == "age"
    assert attr1["bin_id"] == "b1"
    assert attr1["label"] == "18-30"
    assert attr1["woe"] == round(0.5, WOE_ROUND)
    assert attr1["coefficient"] == 1.2
    assert attr1["points"] == round(direction * factor * 1.2 * 0.5, POINTS_ROUND)

    attr2 = attributes[1]
    assert attr2["variable"] == "age"
    assert attr2["bin_id"] == "b2"
    assert attr2["woe"] == round(-0.3, WOE_ROUND)
    assert attr2["points"] == round(direction * factor * 1.2 * (-0.3), POINTS_ROUND)

    attr3 = attributes[2]
    assert attr3["variable"] == "income"
    assert attr3["bin_id"] == "b3"
    assert attr3["woe"] == round(0.2, WOE_ROUND)
    assert attr3["coefficient"] == -0.8
    assert attr3["points"] == round(direction * factor * (-0.8) * 0.2, POINTS_ROUND)
