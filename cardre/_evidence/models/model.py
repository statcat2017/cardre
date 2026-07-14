"""Model artifact data models."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import JsonDict


def _parse_base_odds(raw: Any) -> float:
    if isinstance(raw, str) and ":" in raw:
        num, den = raw.split(":", 1)
        return float(num) / float(den)
    return float(raw)


@dataclass(frozen=True)
class Coefficient:
    variable_name: str
    coefficient: float = 0.0
    standard_error: float | None = None
    p_value: float | None = None


@dataclass(frozen=True)
class ModelArtifact:
    model_family: str
    features: list[str]
    target_column: str
    intercept: float = 0.0
    coefficients: list[Coefficient] = field(default_factory=list)
    coefficients_dict: dict[str, float] = field(default_factory=dict)
    training: JsonDict = field(default_factory=dict)
    warnings: list[JsonDict] = field(default_factory=list)
    calibration: JsonDict = field(default_factory=dict)
    feature_contract: JsonDict = field(default_factory=dict)
    source_variables: list[str] | None = None
    has_explicit_intercept: bool = False
    interpretability: JsonDict = field(default_factory=dict)
    source_artifact_id: str = ""
    _data: JsonDict = field(default_factory=dict, repr=False)
    ensemble_type: str = ""
    base_models: list[JsonDict] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    voting: str = ""
    threshold: float | None = None
    estimator_reference: JsonDict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ModelArtifact:
        raw_coeffs = data.get("coefficients", [])
        model_payload = data.get("model_payload", {}) if isinstance(data.get("model_payload", {}), dict) else {}
        model_family = str(data.get("model_family", "")).strip()
        features = data.get("features", [])

        if not model_family:
            raise ValueError("ModelArtifact requires a non-empty 'model_family'.")
        if not features:
            raise ValueError("ModelArtifact requires a non-empty 'features' list.")

        coefficients: list[Coefficient] = []
        coefficients_dict: dict[str, float] = {}

        if isinstance(raw_coeffs, dict):
            coefficients_dict = {
                k: v for k, v in raw_coeffs.items()
                if isinstance(v, (int, float))
            }
            coefficients = [
                Coefficient(variable_name=k, coefficient=v)
                for k, v in coefficients_dict.items()
            ]
        elif isinstance(raw_coeffs, list):
            raise ValueError(
                "ModelArtifact coefficients must be a dict {variable: coefficient}; "
                "list-of-dicts form is not supported."
            )

        return cls(
            model_family=model_family,
            features=features,
            target_column=data.get("target_column", ""),
            intercept=float(data.get("intercept", 0)),
            coefficients=coefficients,
            coefficients_dict=coefficients_dict,
            training=data.get("training", {}),
            warnings=list(data.get("warnings", [])),
            calibration=dict(data.get("calibration", {})),
            feature_contract=dict(data.get("feature_contract", {})),
            source_variables=[str(v) for v in data["source_variables"]] if "source_variables" in data else None,
            has_explicit_intercept="intercept" in data,
            interpretability=dict(data.get("interpretability", {})),
            source_artifact_id=artifact_id,
            _data=data,
            ensemble_type=str(model_payload.get("ensemble_type", "")),
            base_models=list(model_payload.get("base_models", [])),
            weights=[float(v) for v in model_payload.get("weights", []) if isinstance(v, (int, float))],
            voting=str(model_payload.get("voting", "")),
            threshold=model_payload.get("threshold"),
            estimator_reference=dict(data.get("estimator_reference", {})),
        )

    def to_model_dict(self) -> JsonDict:
        return {
            "model_family": self.model_family,
            "coefficients": self.coefficients_dict,
            "intercept": self.intercept,
            "features": self.features,
            "target_column": self.target_column,
        }

    def to_dict(self) -> JsonDict:
        return dict(self._data)


@dataclass(frozen=True)
class ScoreScaling:
    base_score: int = 600
    base_odds: float = 50.0
    points_to_double_odds: int = 20
    factor: float = 0.0
    offset: float = 0.0
    score_direction: str = "higher_is_lower_risk"
    rounding: str = "nearest_integer"
    min_score: int = 0
    max_score: int = 0
    source_artifact_id: str = ""
    base_odds_text: str = "50:1"
    intercept: float = 0.0
    has_explicit_intercept: bool = False
    base_points: float | int | None = None
    target_column: str = ""
    attributes: list[JsonDict] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ScoreScaling:
        raw_odds = data.get("base_odds", "50:1")
        base_odds = _parse_base_odds(raw_odds)
        points_to_double_odds = data.get("points_to_double_odds", 20)
        base_score = data.get("base_score", 600)
        if "factor" in data and "offset" in data:
            factor = float(data.get("factor", 0))
            offset = float(data.get("offset", 0))
        else:
            factor = float(points_to_double_odds) / math.log(2)
            offset = float(base_score) - factor * math.log(base_odds)
        return cls(
            base_score=base_score,
            base_odds=base_odds,
            points_to_double_odds=points_to_double_odds,
            factor=factor,
            offset=offset,
            score_direction=data.get("score_direction", "higher_is_lower_risk"),
            rounding=data.get("rounding", "nearest_integer"),
            min_score=data.get("min_score", 0),
            max_score=data.get("max_score", 0),
            source_artifact_id=artifact_id,
            base_odds_text=str(raw_odds),
            intercept=float(data.get("intercept", 0.0)),
            has_explicit_intercept="intercept" in data,
            base_points=data.get("base_points"),
            target_column=str(data.get("target_column", "")),
            attributes=[dict(v) for v in data.get("attributes", []) if isinstance(v, dict)],
        )

    @property
    def higher_score_is_lower_risk(self) -> bool:
        return self.score_direction == "higher_is_lower_risk"
