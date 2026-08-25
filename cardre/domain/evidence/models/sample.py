"""Sample / profile data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.schemas import SCHEMA_MODELLING_METADATA


@dataclass(frozen=True)
class ModellingMetadata:
    target_column: str
    good_values: list[Any]
    bad_values: list[Any]
    indeterminate_values: list[Any] = field(default_factory=list)
    extra: JsonDict = field(default_factory=dict)
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ModellingMetadata:
        if not isinstance(data, dict):
            raise ValueError("MODELLING_METADATA requires an object payload")
        if data.get("schema_version") != SCHEMA_MODELLING_METADATA:
            raise ValueError(
                f"ModellingMetadata requires schema_version {SCHEMA_MODELLING_METADATA!r}"
            )
        # Require the current target fields; no legacy-null fallback.
        target_column = data.get("target_column", "")
        if not isinstance(target_column, str) or not target_column:
            raise ValueError("ModellingMetadata requires a non-empty target_column")
        good_values = data.get("good_values")
        bad_values = data.get("bad_values")
        if not isinstance(good_values, list) or not isinstance(bad_values, list):
            raise ValueError("ModellingMetadata requires good_values and bad_values lists")
        if not good_values or not bad_values:
            raise ValueError("ModellingMetadata requires non-empty good_values and bad_values")
        indeterminate = data.get("indeterminate_values")
        if not isinstance(indeterminate, list):
            raise ValueError("ModellingMetadata requires indeterminate_values list")
        return cls(
            target_column=target_column,
            good_values=list(good_values),
            bad_values=list(bad_values),
            indeterminate_values=list(indeterminate),
            extra={k: v for k, v in data.items()
                   if k not in ("target_column", "good_values", "bad_values", "indeterminate_values")},
            _raw=data,
            source_artifact_id=artifact_id,
            schema_version=str(data.get("schema_version", "")),
        )

    def to_dict(self) -> JsonDict:
        """Serialize to the canonical modelling-metadata JSON shape.

        Emits only the typed current fields (plus any explicit ``extra``
        values), never the raw input passthrough. The ``_raw`` snapshot is
        retained for debugging but is not emitted.
        """
        payload: JsonDict = {
            "schema_version": self.schema_version,
            "target_column": self.target_column,
            "good_values": list(self.good_values),
            "bad_values": list(self.bad_values),
            "indeterminate_values": list(self.indeterminate_values),
        }
        payload.update(self.extra)
        return payload


@dataclass(frozen=True)
class SampleDefinition:
    sample_method: str = "full_population"
    sample_domain: str = "ttd"
    total_rows: int = 0
    weight_column: str | None = None
    sample_description: str = ""
    extra: JsonDict = field(default_factory=dict)
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> SampleDefinition:
        return cls(
            sample_method=data.get("sample_method", "full_population"),
            sample_domain=data.get("sample_domain", "ttd"),
            total_rows=data.get("total_rows", 0),
            weight_column=data.get("weight_column"),
            sample_description=data.get("sample_description", ""),
            extra={k: v for k, v in data.items()
                   if k not in ("sample_method", "sample_domain", "total_rows",
                                "weight_column", "sample_description")},
            _raw=data,
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class SplitSummary:
    strategy: str
    row_counts: dict[str, int]
    target_rates: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> SplitSummary:
        return cls(
            strategy=data.get("strategy", ""),
            row_counts={k: int(v) for k, v in dict(data.get("row_counts", {})).items()},
            target_rates={
                str(role): {str(k): int(v) for k, v in dict(counts).items()}
                for role, counts in dict(data.get("target_rates", {})).items()
            },
            warnings=list(data.get("warnings", [])),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ProfileSummary:
    row_count: int = 0
    column_count: int = 0
    columns: list[str] = field(default_factory=list)
    dtypes: dict[str, str] = field(default_factory=dict)
    null_counts: dict[str, int] = field(default_factory=dict)
    numeric_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    profile_steps: list[JsonDict] = field(default_factory=list)
    profiles: list[JsonDict] = field(default_factory=list)
    warnings: list[JsonDict] = field(default_factory=list)
    quality_warnings: list[JsonDict] = field(default_factory=list)
    recommended_exclude_columns: list[str] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ProfileSummary:
        profiles = data.get("profiles", [])
        if isinstance(profiles, dict):
            profiles = list(profiles.values())
        columns = data.get("columns", [])
        if isinstance(columns, dict):
            columns = list(columns.keys())
        return cls(
            row_count=int(data.get("row_count", 0)),
            column_count=int(data.get("column_count", 0)),
            columns=[str(c) for c in columns],
            dtypes={str(k): str(v) for k, v in dict(data.get("dtypes", {})).items()},
            null_counts={str(k): int(v) for k, v in dict(data.get("null_counts", {})).items()},
            numeric_stats={str(k): dict(v) for k, v in dict(data.get("numeric_stats", {})).items()},
            profile_steps=list(data.get("profile_steps", [])),
            profiles=list(profiles),
            warnings=list(data.get("warnings", [])),
            quality_warnings=list(data.get("quality_warnings", [])),
            recommended_exclude_columns=[str(c) for c in data.get("recommended_exclude_columns", [])],
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ExclusionSummary:
    rows_before: int
    rows_after: int
    rows_excluded: int
    rules: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ExclusionSummary:
        return cls(
            rows_before=int(data.get("rows_before", 0)),
            rows_after=int(data.get("rows_after", 0)),
            rows_excluded=int(data.get("rows_excluded", 0)),
            rules=list(data.get("rules", [])),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )
