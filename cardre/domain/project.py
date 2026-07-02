"""Project domain type."""

from __future__ import annotations

from dataclasses import dataclass

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class Project:
    """A Cardre project on disk."""
    project_id: str
    name: str
    created_at: str
    cardre_version: str

    def to_dict(self) -> JsonDict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at,
            "cardre_version": self.cardre_version,
        }


__all__ = ["Project"]
