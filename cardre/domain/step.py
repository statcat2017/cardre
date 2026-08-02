"""StepSpec — the pure specification of a plan step.

No NodeType here (that is an executable plugin interface in
``cardre/nodes/contracts.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    canonical_step_id: str = field(kw_only=True)
    branch_id: str | None = field(default=None, kw_only=True)

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


__all__ = ["StepSpec"]
