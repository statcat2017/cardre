"""Plan and PlanVersion domain types.

``Plan`` is a named container.  ``PlanVersion`` is an immutable snapshot
of a plan's step graph at a point in time; it can be draft or committed.
"""

from __future__ import annotations

from dataclasses import dataclass

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class Plan:
    """A named plan belonging to a project."""
    plan_id: str
    project_id: str
    name: str
    created_at: str

    def to_dict(self) -> JsonDict:
        return {
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PlanVersion:
    """An immutable version of a plan's step graph.

    ``is_committed`` distinguishes draft (editable) from committed
    (frozen) versions.  Committed versions must not be mutated.
    """
    plan_version_id: str
    plan_id: str
    version_number: int
    is_committed: bool
    created_at: str
    description: str = ""

    def to_dict(self) -> JsonDict:
        return {
            "plan_version_id": self.plan_version_id,
            "plan_id": self.plan_id,
            "version_number": self.version_number,
            "is_committed": self.is_committed,
            "created_at": self.created_at,
            "description": self.description,
        }


__all__ = ["Plan", "PlanVersion"]
