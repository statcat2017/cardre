"""Manual-binning review repository.

.. note::

    ``affected_downstream_step_ids_json`` is a non-authoritative UI hint.
    The authoritative answer for "which downstream steps are affected" is
    ``StalenessService.explain_step`` against the draft plan version. Do not
    add SQL filters or joins on this column; treat it as opaque display
    payload. If it ever needs to be queried, promote it to a
    ``manual_binning_affected_steps`` table first.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.manual_binning import ManualBinningReview

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class ManualBinningRepository:
    """Repository for manual_binning_reviews."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def create_review(
        self,
        plan_version_id: str,
        step_id: str,
        status: str = "pending",
        reviewer_notes: str = "",
        affected_downstream_step_ids: list[str] | None = None,
    ) -> str:
        review_id = str(uuid.uuid4())
        now = utc_now_iso()
        downstream_json = json.dumps(affected_downstream_step_ids or [])
        self._store.execute(
            "INSERT INTO manual_binning_reviews "
            "(review_id, plan_version_id, step_id, status, reviewer_notes, "
            " affected_downstream_step_ids_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (review_id, plan_version_id, step_id, status, reviewer_notes, downstream_json, now, now),
        )
        return review_id

    def get_review(self, review_id: str) -> ManualBinningReview | None:
        row = self._store.execute(
            "SELECT * FROM manual_binning_reviews WHERE review_id = ?", (review_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_review(row)

    def get_reviews_for_step(self, plan_version_id: str, step_id: str) -> list[ManualBinningReview]:
        rows = self._store.execute(
            "SELECT * FROM manual_binning_reviews WHERE plan_version_id = ? AND step_id = ? ORDER BY created_at",
            (plan_version_id, step_id),
        ).fetchall()
        return [self._row_to_review(r) for r in rows]

    def update_review(
        self,
        review_id: str,
        status: str | None = None,
        reviewer_notes: str | None = None,
    ) -> None:
        now = utc_now_iso()
        updates = []
        params = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if reviewer_notes is not None:
            updates.append("reviewer_notes = ?")
            params.append(reviewer_notes)
        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(review_id)
            self._store.execute(
                f"UPDATE manual_binning_reviews SET {', '.join(updates)} WHERE review_id = ?",
                params,
            )

    @staticmethod
    def _row_to_review(row) -> ManualBinningReview:
        d = dict(row)
        return ManualBinningReview(
            review_id=d["review_id"],
            plan_version_id=d["plan_version_id"],
            step_id=d["step_id"],
            status=d["status"],
            reviewer_notes=d.get("reviewer_notes", ""),
            affected_downstream_step_ids=json.loads(d.get("affected_downstream_step_ids_json", "[]")),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )
