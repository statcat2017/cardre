from __future__ import annotations

from cardre._evidence.models.binning import BinDefinition, BinVariable
from cardre._evidence.models.model import ScoreScaling
from cardre._evidence.models.woe import WoeTable
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.build.freeze import FrozenScorecardBundleNode

SCHEMA_BIN_DEFINITION = "cardre.bin_definition.v1"


def test_freeze_bundle_allows_missing_scorecard_intercept(node_harness):
    from node_harness import FakeArtifact as _FakeArtifact

    order_hash = json_logical_hash({"features": ["age_woe"]})

    meta = _FakeArtifact("definition", metadata={"schema_version": "cardre.modelling_metadata.v1"}, artifact_id="meta-art")
    bin_art = _FakeArtifact("definition", metadata={"schema_version": SCHEMA_BIN_DEFINITION}, artifact_id="bin-art")
    woe_art = _FakeArtifact("report", metadata={"schema_version": "cardre.woe_table.v1"}, artifact_id="woe-art")
    model_art = _FakeArtifact("model", metadata={"schema_version": "cardre.model_artifact.v1"}, artifact_id="model-art")
    scorecard_art = _FakeArtifact("scorecard", metadata={"schema_version": "cardre.score_scaling.v1"}, artifact_id="scorecard-art")

    out = node_harness(
        FrozenScorecardBundleNode,
        roles={
            "definition": [meta, bin_art],
            "report": [woe_art],
            "model": [model_art],
            "scorecard": [scorecard_art],
        },
        evidence={
            EvidenceKind.MODELLING_METADATA: type("M", (), {
                "target_column": "default_flag",
                "good_values": ["0"],
                "bad_values": ["1"],
            })(),
            EvidenceKind.BIN_DEFINITION: BinDefinition(
                source_artifact_id="bin-art",
                variables=[
                    BinVariable(
                        variable="age", dtype="numeric", kind="fine",
                        bins=[{"bin_id": "b1", "label": "all", "lower": 0, "upper": 100}],
                    ),
                ],
            ),
            EvidenceKind.WOE_TABLE: WoeTable(
                mapping={"age": {"b1": 0.5}},
                columns=["variable", "bin_id", "woe"],
                source_artifact_id="woe-art",
            ),
            EvidenceKind.MODEL_ARTIFACT: ModelArtifactV1.from_dict({
                "schema_version": "cardre.model_artifact.v1",
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
            }, artifact_id="model-art"),
            EvidenceKind.SCORE_SCALING: ScoreScaling.from_json({
                "schema_version": "cardre.score_scaling.v1",
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
            }, artifact_id="scorecard-art"),
        },
    )

    assert len(out.staged) == 1
    bundle = out.staged[0].payload
    assert bundle["schema_version"] == "cardre.frozen_scorecard_bundle.v1"
    assert bundle["score_scaling"]["intercept"] == 0.0
    assert bundle["feature_contract"]["source_variables"] == ["age"]
