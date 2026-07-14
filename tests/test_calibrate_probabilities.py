from __future__ import annotations

from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.calibrate import _supports_folded_linear_calibration


def test_folded_linear_calibration_requires_explicit_intercept():
    without_intercept = ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "bad_flag",
        "feature_contract": {"features": ["age_woe"]},
        "model_payload": {"coefficients": {"age_woe": 0.8}},
    })
    with_intercept = ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "bad_flag",
        "feature_contract": {"features": ["age_woe"]},
        "model_payload": {"intercept": -0.4, "coefficients": {"age_woe": 0.8}},
    })

    assert not _supports_folded_linear_calibration(without_intercept)
    assert _supports_folded_linear_calibration(with_intercept)
