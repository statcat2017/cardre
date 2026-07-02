"""Apply / scoring data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class ApplyWoeEvidence:
    policy: JsonDict
    roles: dict[str, JsonDict]
    warnings: list[JsonDict] = field(default_factory=list)
    bin_definition_artifact_id: str = ""
    woe_table_artifact_id: str = ""
    selection_artifact_id: str | None = None
    frozen_bundle_artifact_id: str | None = None
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ApplyWoeEvidence:
        return cls(
            policy=dict(data.get("policy", {})),
            roles={str(k): dict(v) for k, v in dict(data.get("roles", {})).items()},
            warnings=list(data.get("warnings", [])),
            bin_definition_artifact_id=data.get("bin_definition_artifact_id", ""),
            woe_table_artifact_id=data.get("woe_table_artifact_id", ""),
            selection_artifact_id=data.get("selection_artifact_id"),
            frozen_bundle_artifact_id=data.get("frozen_bundle_artifact_id"),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ApplyModelEvidence:
    roles: dict[str, JsonDict]
    model_artifact_id: str
    warnings: list[JsonDict] = field(default_factory=list)
    scorecard_artifact_id: str | None = None
    frozen_bundle_artifact_id: str | None = None
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ApplyModelEvidence:
        return cls(
            roles={str(k): dict(v) for k, v in dict(data.get("roles", {})).items()},
            model_artifact_id=data.get("model_artifact_id", ""),
            warnings=list(data.get("warnings", [])),
            scorecard_artifact_id=data.get("scorecard_artifact_id"),
            frozen_bundle_artifact_id=data.get("frozen_bundle_artifact_id"),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ScoredDataset:
    dataframe: Any
    _raw: JsonDict = field(default_factory=dict, repr=False)
