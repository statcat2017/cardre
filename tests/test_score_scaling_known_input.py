"""Integration test: ScoreScalingNode.run() with known fixtures.

Exercises the actual node code path against tiny synthetic inputs so we can
assert on exact numeric outputs for factor, offset, base_points, and
attributes.  Runs through the ``node_harness`` (no store required).
"""

from __future__ import annotations

import math

import pytest

from cardre._evidence.models.binning import BinDefinition, BinVariable
from cardre._evidence.models.woe import WoeTable
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.build._logit_helpers import WOE_ROUND
from cardre.nodes.build.models import ScoreScalingNode


def _model_artifact() -> ModelArtifactV1:
    return ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "default_flag",
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
        "model_payload": {
            "intercept": -0.5,
            "coefficients": {
                "age_woe": 1.2,
                "income_woe": -0.8,
            },
        },
        "training": {
            "row_count": 100,
            "converged": True,
            "iterations": 15,
            "params": {"C": 1.0},
        },
        "warnings": [],
    })


def _bin_definition() -> BinDefinition:
    return BinDefinition(
        source_artifact_id="bin-def-art-1",
        variables=[
            BinVariable(
                variable="age", dtype="numeric", kind="fine",
                bins=[
                    {"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30},
                    {"bin_id": "b2", "label": "31-50", "lower": 31, "upper": 50},
                ],
            ),
            BinVariable(
                variable="income", dtype="numeric", kind="fine",
                bins=[
                    {"bin_id": "b3", "label": "Low", "lower": 0, "upper": 30000},
                ],
            ),
        ],
    )


def _woe_table() -> WoeTable:
    return WoeTable(
        mapping={"age": {"b1": 0.5, "b2": -0.3}, "income": {"b3": 0.2}},
        columns=["variable", "bin_id", "woe"],
    )


def test_score_scaling_with_known_input(node_harness) -> None:
    """Run ScoreScalingNode.run() with known fixtures and assert exact outputs."""
    out = node_harness(
        ScoreScalingNode,
        roles={"model": ["model-art-1"]},
        evidence={
            EvidenceKind.MODEL_ARTIFACT: _model_artifact(),
            EvidenceKind.BIN_DEFINITION: _bin_definition(),
            EvidenceKind.WOE_TABLE: _woe_table(),
        },
        params={
            "base_score": 600,
            "base_odds": "50:1",
            "points_to_double_odds": 20.0,
            "higher_score_is_lower_risk": True,
        },
    )

    assert len(out.staged) == 1
    scorecard_art = out.staged[0]
    assert scorecard_art.role == "scorecard"
    raw = scorecard_art.payload

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
    assert attr1["points"] == round(direction * factor * 1.2 * 0.5, 2)

    attr2 = attributes[1]
    assert attr2["variable"] == "age"
    assert attr2["bin_id"] == "b2"
    assert attr2["woe"] == round(-0.3, WOE_ROUND)
    assert attr2["points"] == round(direction * factor * 1.2 * (-0.3), 2)

    attr3 = attributes[2]
    assert attr3["variable"] == "income"
    assert attr3["bin_id"] == "b3"
    assert attr3["woe"] == round(0.2, WOE_ROUND)
    assert attr3["coefficient"] == -0.8
    assert attr3["points"] == round(direction * factor * (-0.8) * 0.2, 2)

    # --- Verify metrics ---
    assert out.metrics["attribute_count"] == 3
