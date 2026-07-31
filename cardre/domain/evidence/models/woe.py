"""WOE / IV data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class AffectedBin:
    bin_id: str
    detail: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class WoeBin:
    bin_id: str
    label: str = ""
    lower: float | None = None
    upper: float | None = None
    good_count: int = 0
    bad_count: int = 0
    bad_rate: float = 0.0
    woe: float | None = None
    iv_contribution: float | None = None


@dataclass(frozen=True)
class WoeSmoothing:
    enabled: bool = False
    method: str = "additive"
    alpha: float = 0.5
    zero_cell_policy: str = "block"


@dataclass(frozen=True)
class WoeIvVariable:
    variable_name: str
    iv: float = 0.0
    status: str = "included"
    bins: list[WoeBin] = field(default_factory=list)
    affected_bins: list[AffectedBin] = field(default_factory=list)
    smoothing_applied: bool = False
    zero_cell_encountered: bool = False
    warnings: list[JsonDict] = field(default_factory=list)


@dataclass(frozen=True)
class WoeIvEvidence:
    variables: list[WoeIvVariable]
    smoothing: WoeSmoothing = field(default_factory=WoeSmoothing)
    schema_version: str = ""
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> WoeIvEvidence:
        config = data.get("config", {})
        smoothing_config = config.get("smoothing", {})
        smoothing = WoeSmoothing(
            enabled=smoothing_config.get("enabled", False),
            method=smoothing_config.get("method", "additive"),
            alpha=smoothing_config.get("alpha", 0.5),
            zero_cell_policy=smoothing_config.get("zero_cell_policy", "block"),
        )

        variables = []
        for v in data.get("variables", []):
            bins = [
                WoeBin(
                    bin_id=b.get("bin_id", ""),
                    label=b.get("label", ""),
                    lower=b.get("lower"),
                    upper=b.get("upper"),
                    good_count=b.get("good_count", 0),
                    bad_count=b.get("bad_count", 0),
                    bad_rate=b.get("bad_rate", 0.0),
                    woe=b.get("woe"),
                    iv_contribution=b.get("iv_contribution"),
                )
                for b in v.get("bins", [])
            ]
            affected_bins = [
                AffectedBin(bin_id=ab.get("bin_id", ""), detail=ab)
                for ab in v.get("affected_bins", [])
            ]
            variables.append(WoeIvVariable(
                variable_name=v.get("variable_name", v.get("variable", "")),
                iv=float(v.get("iv", 0)),
                status=v.get("status", "included"),
                bins=bins,
                affected_bins=affected_bins,
                smoothing_applied=v.get("smoothing_applied", False),
                zero_cell_encountered=v.get("zero_cell_encountered", False),
                warnings=list(v.get("warnings", [])),
            ))

        return cls(
            variables=variables,
            smoothing=smoothing,
            schema_version=data.get("schema_version", ""),
            _raw=data,
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class WoeTable:
    mapping: dict[str, dict[str, float]]
    columns: list[str]
    dataframe: Any = None
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""


@dataclass(frozen=True)
class IvTable:
    dataframe: Any
    columns: list[str]
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""


@dataclass(frozen=True)
class WoeTransformEvidence:
    target_column: str
    transformed_variables: list[str]
    selected_only: bool = False
    row_count: int = 0
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> WoeTransformEvidence:
        return cls(
            target_column=data.get("target_column", ""),
            transformed_variables=[str(v) for v in data.get("transformed_variables", [])],
            selected_only=bool(data.get("selected_only", False)),
            row_count=int(data.get("row_count", 0)),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )
