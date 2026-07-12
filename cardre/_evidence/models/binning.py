"""Bin / selection data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class BinVariable:
    variable: str
    dtype: str = ""
    kind: str = ""
    bins: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {"variable": self.variable, "dtype": self.dtype, "kind": self.kind, "bins": self.bins}


@dataclass(frozen=True)
class BinDefinition:
    variables: list[BinVariable]
    source_artifact_id: str
    _lifecycle: Any = field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> BinDefinition:
        from cardre.engine.binning.definition import LifecycleBinDefinition
        lifecycle = LifecycleBinDefinition.from_payload(data)
        variables = [
            BinVariable(
                variable=v.get("variable", ""),
                dtype=v.get("dtype", ""),
                kind=v.get("kind", ""),
                bins=list(v.get("bins", [])),
            )
            for v in data.get("variables", [])
        ]
        return cls(variables=variables, source_artifact_id=artifact_id, _lifecycle=lifecycle)

    def to_dict(self) -> JsonDict:
        if self._lifecycle is not None:
            return dict(self._lifecycle.to_payload())
        return {"variables": [v.to_dict() for v in self.variables]}

    @property
    def lifecycle(self) -> Any | None:
        return self._lifecycle

    @property
    def rejected(self) -> list[Any]:
        if self._lifecycle is not None:
            return list(self._lifecycle.rejected)
        return []

    @property
    def warnings(self) -> list[JsonDict]:
        if self._lifecycle is not None:
            return list(self._lifecycle.warnings)
        return []

    @property
    def source(self) -> JsonDict | None:
        if self._lifecycle is not None:
            val = self._lifecycle.source
            return dict(val) if val is not None else None
        return None


@dataclass(frozen=True)
class ManualBinningOverride:
    variable: str
    action: str
    bins: list[Any] = field(default_factory=list)
    reason: str = ""
    comment: str = ""
    group_label: str = ""
    new_label: str = ""

    @classmethod
    def from_dict(cls, data: JsonDict) -> ManualBinningOverride:
        return cls(
            variable=data.get("variable", ""),
            action=data.get("action", ""),
            bins=list(data.get("bins", [])),
            reason=data.get("reason", ""),
            comment=data.get("comment", ""),
            group_label=data.get("group_label", ""),
            new_label=data.get("new_label", ""),
        )

    def to_dict(self) -> JsonDict:
        d: JsonDict = {
            "variable": self.variable,
            "action": self.action,
            "bins": list(self.bins),
            "reason": self.reason,
        }
        if self.comment:
            d["comment"] = self.comment
        if self.group_label:
            d["group_label"] = self.group_label
        if self.new_label:
            d["new_label"] = self.new_label
        return d


@dataclass(frozen=True)
class ManualBinningOverrides:
    overrides: list[ManualBinningOverride] = field(default_factory=list)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ManualBinningOverrides:
        overrides = [ManualBinningOverride.from_dict(o) for o in data.get("overrides", [])]
        return cls(
            overrides=overrides,
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )

    def to_dict(self) -> JsonDict:
        return {
            "schema_version": self.schema_version,
            "overrides": [o.to_dict() for o in self.overrides],
            "source_artifact_id": self.source_artifact_id,
        }


@dataclass(frozen=True)
class SelectedVariable:
    variable: str
    reason: str = ""
    extra: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class SelectionDefinition:
    selected: list[SelectedVariable]
    method: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> SelectionDefinition:
        selected = [
            SelectedVariable(
                variable=s.get("variable", ""),
                reason=s.get("reason", ""),
                extra={k: v for k, v in s.items() if k not in ("variable", "reason")},
            )
            for s in data.get("selected", [])
        ]
        return cls(selected=selected, method=data.get("method", ""), source_artifact_id=artifact_id)

    @property
    def selected_names(self) -> set[str]:
        return {s.variable for s in self.selected}

    def to_dict(self) -> JsonDict:
        return {
            "selected": [
                {"variable": s.variable, "reason": s.reason, **s.extra}
                for s in self.selected
            ],
            "method": self.method,
        }
