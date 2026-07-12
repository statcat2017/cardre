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
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""
    ensemble_type: str = ""
    base_models: list[JsonDict] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    voting: str = ""
    threshold: float | None = None
    estimator_reference: JsonDict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ModelArtifact:
        coefficients: list[Coefficient] = []
        coefficients_dict: dict[str, float] = {}
        raw_coeffs = data.get("coefficients", [])
        model_payload = data.get("model_payload", {}) if isinstance(data.get("model_payload", {}), dict) else {}
        model_family = str(data.get("model_family", "")).strip()

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
            for c in raw_coeffs:
                if isinstance(c, dict):
                    coefficients.append(Coefficient(
                        variable_name=c.get("variable_name", c.get("variable", "")),  # type: ignore[arg-type]  # .get() on dict[str, Any] returns Any
                        coefficient=c.get("coefficient", 0.0),
                        standard_error=c.get("standard_error"),
                        p_value=c.get("p_value"),
                    ))
                    var_name = c.get("variable_name") or c.get("variable", "")
                    if var_name and isinstance(c.get("coefficient"), (int, float)):
                        coefficients_dict[var_name] = c["coefficient"]

        features = data.get("features", [])
        if not features and coefficients_dict:
            features = list(coefficients_dict.keys())
        if not model_family and (coefficients_dict or raw_coeffs):
            model_family = "logistic_regression"

        return cls(
            model_family=model_family,
            features=features,
            target_column=data.get("target_column", ""),
            intercept=float(data.get("intercept", 0)),
            coefficients=coefficients,
            coefficients_dict=coefficients_dict,
            training=data.get("training", {}),
            warnings=list(data.get("warnings", [])),
            _raw=data,
            source_artifact_id=artifact_id,
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

    @property
    def feature_contract(self) -> JsonDict:
        return dict(self._raw.get("feature_contract", {}))

    @property
    def source_variables(self) -> list[str] | None:
        variables = self._raw.get("source_variables")
        if variables is None:
            return None
        return [str(value) for value in variables]

    @property
    def calibration(self) -> JsonDict:
        return dict(self._raw.get("calibration", {}))

    @property
    def has_explicit_intercept(self) -> bool:
        return "intercept" in self._raw

    def to_dict(self) -> JsonDict:
        return dict(self._raw)


@dataclass(frozen=True)
class ScoreScaling:
    base_score: int = 600
    base_odds: float = 50.0
    pdo: int = 20
    factor: float = 0.0
    offset: float = 0.0
    score_direction: str = "higher_is_better"
    rounding: str = "nearest_integer"
    min_score: int = 0
    max_score: int = 0
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ScoreScaling:
        raw_odds = data.get("base_odds", "50:1")
        base_odds = _parse_base_odds(raw_odds)
        higher_score_is_lower_risk = data.get("higher_score_is_lower_risk")
        pdo = data.get("pdo", data.get("points_to_double_odds", 20))
        base_score = data.get("base_score", 600)
        if "factor" in data and "offset" in data:
            factor = float(data.get("factor", 0))
            offset = float(data.get("offset", 0))
        else:
            factor = float(pdo) / math.log(2)  # type: ignore[arg-type]  # pdo is Any from .get()
            offset = float(base_score) - factor * math.log(base_odds)
        return cls(
            base_score=base_score,
            base_odds=base_odds,
            pdo=pdo,  # type: ignore[arg-type]  # pdo is Any from .get()
            factor=factor,
            offset=offset,
            score_direction=(
                "higher_is_lower_risk"
                if higher_score_is_lower_risk is True
                else data.get("score_direction", "higher_is_better")
            ),
            rounding=data.get("rounding", "nearest_integer"),
            min_score=data.get("min_score", 0),
            max_score=data.get("max_score", 0),
            _raw=data,
            source_artifact_id=artifact_id,
        )

    @property
    def higher_score_is_lower_risk(self) -> bool:
        return self.score_direction == "higher_is_lower_risk"

    @property
    def base_odds_text(self) -> str:
        raw_value = self._raw.get("base_odds", self.base_odds)
        return str(raw_value)

    @property
    def intercept(self) -> float:
        return float(self._raw.get("intercept", 0.0))

    @property
    def base_points(self) -> float | int | None:
        return self._raw.get("base_points")

    @property
    def target_column(self) -> str:
        return str(self._raw.get("target_column", ""))

    @property
    def attributes(self) -> list[JsonDict]:
        return [dict(value) for value in self._raw.get("attributes", []) if isinstance(value, dict)]

    def to_dict(self) -> JsonDict:
        return dict(self._raw)
