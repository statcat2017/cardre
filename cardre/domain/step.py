"""StepSpec — the pure specification of a plan step.

No NodeType here (that is an executable plugin interface in
``cardre/nodes/contracts.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class StepSpec:
    """Immutable specification of a single step in a plan version.

    Does **not** carry input/output artifact IDs — those are derived from
    ``evidence_edges`` + ``evidence_artifacts`` + ``artifact_lineage`` at
    query time.
    """
    step_id: str
    node_type: str
    node_version: str
    category: str
    params: JsonDict
    params_hash: str
    parent_step_ids: list[str]
    branch_label: str = ""
    position: int = 0
    canonical_step_id: str = field(default="", kw_only=True)
    branch_id: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.canonical_step_id:
            object.__setattr__(self, "canonical_step_id", self.step_id)

    def to_dict(self) -> JsonDict:
        return {
            "step_id": self.step_id,
            "node_type": self.node_type,
            "node_version": self.node_version,
            "category": self.category,
            "params": self.params,
            "params_hash": self.params_hash,
            "parent_step_ids": list(self.parent_step_ids),
            "branch_label": self.branch_label,
            "position": self.position,
            "canonical_step_id": self.canonical_step_id,
            "branch_id": self.branch_id,
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> StepSpec:
        return cls(
            step_id=data["step_id"],
            node_type=data["node_type"],
            node_version=data["node_version"],
            category=data["category"],
            params=dict(data.get("params", {})),
            params_hash=data.get("params_hash", json_logical_hash(dict(data.get("params", {})))),
            parent_step_ids=list(data.get("parent_step_ids", [])),
            branch_label=data.get("branch_label", ""),
            position=data.get("position", 0),
            canonical_step_id=cast(str, data.get("canonical_step_id", data["step_id"])),
            branch_id=data.get("branch_id"),
        )


__all__ = ["StepSpec"]
