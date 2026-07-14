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

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "base_score": self.base_score,
            "base_odds": self.base_odds_text,
            "points_to_double_odds": self.points_to_double_odds,
            "factor": self.factor,
            "offset": self.offset,
            "score_direction": self.score_direction,
            "rounding": self.rounding,
            "min_score": self.min_score,
            "max_score": self.max_score,
            "target_column": self.target_column,
            "attributes": self.attributes,
        }
        if self.has_explicit_intercept:
            payload["intercept"] = self.intercept
        if self.base_points is not None:
            payload["base_points"] = self.base_points
        return payload
