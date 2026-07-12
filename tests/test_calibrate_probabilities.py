from __future__ import annotations

from cardre._evidence.models.model import ModelArtifact
from cardre.nodes.calibrate import _supports_folded_linear_calibration


def test_folded_linear_calibration_requires_explicit_intercept():
    without_intercept = ModelArtifact.from_json({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "bad_flag",
        "coefficients": {"age_woe": 0.8},
        "features": ["age_woe"],
    })
    with_intercept = ModelArtifact.from_json({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "bad_flag",
        "intercept": -0.4,
        "coefficients": {"age_woe": 0.8},
        "features": ["age_woe"],
    })

    assert not _supports_folded_linear_calibration(without_intercept)
    assert _supports_folded_linear_calibration(with_intercept)
