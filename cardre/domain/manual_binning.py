"""Manual-binning review domain type."""

from __future__ import annotations

from dataclasses import dataclass, field

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class ManualBinningReview:
    """A manual-binning review for a specific step + plan version.

    Persisted via ``manual_binning_reviews`` table.
    """
    review_id: str
    plan_version_id: str
    step_id: str
    status: str  # e.g. pending | approved | rejected
    reviewer_notes: str = ""
    affected_downstream_step_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> JsonDict:
        return {
            "review_id": self.review_id,
            "plan_version_id": self.plan_version_id,
            "step_id": self.step_id,
            "status": self.status,
            "reviewer_notes": self.reviewer_notes,
            "affected_downstream_step_ids": list(self.affected_downstream_step_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


__all__ = ["ManualBinningReview"]
