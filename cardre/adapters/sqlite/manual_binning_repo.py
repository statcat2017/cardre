"""SQLite manual binning repository — query object for manual_binning_reviews."""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.manual_binning import ManualBinningReview


class ManualBinningRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def create_review(self, plan_version_id: str, step_id: str, status: str,
                      reviewer_notes: str = "", affected_downstream_step_ids: list[str] | None = None) -> ManualBinningReview:
        review_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._conn.execute(
            "INSERT INTO manual_binning_reviews (review_id, plan_version_id, step_id, status, "
            "reviewer_notes, affected_downstream_step_ids_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (review_id, plan_version_id, step_id, status, reviewer_notes,
             json.dumps(affected_downstream_step_ids or []), now, now),
        )
        return ManualBinningReview(
            review_id=review_id, plan_version_id=plan_version_id, step_id=step_id,
            status=status, reviewer_notes=reviewer_notes,
            affected_downstream_step_ids=affected_downstream_step_ids or [],
            created_at=now, updated_at=now,
        )

    def get_review(self, review_id: str) -> ManualBinningReview | None:
        row = self._conn.execute(
            "SELECT * FROM manual_binning_reviews WHERE review_id = ?", (review_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_review(row)

    def list_for_project(self, project_id: str) -> list[ManualBinningReview]:
        rows = self._conn.execute(
            "SELECT mbr.* FROM manual_binning_reviews mbr "
            "JOIN plan_versions pv ON mbr.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? ORDER BY mbr.created_at", (project_id,)
        ).fetchall()
        return [self._row_to_review(r) for r in rows]

    def get_reviews_for_step(self, plan_version_id: str, step_id: str) -> list[ManualBinningReview]:
        rows = self._conn.execute(
            "SELECT * FROM manual_binning_reviews WHERE plan_version_id = ? AND step_id = ? ORDER BY created_at",
            (plan_version_id, step_id),
        ).fetchall()
        return [self._row_to_review(r) for r in rows]

    def update_review(
        self, review_id: str, status: str | None = None, reviewer_notes: str | None = None,
    ) -> bool:
        """Patch the review. Only provided fields are updated. Returns False
        if no review row matched (so the caller can raise REVIEW_NOT_FOUND)."""
        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if reviewer_notes is not None:
            sets.append("reviewer_notes = ?")
            params.append(reviewer_notes)
        if not sets:
            cursor = self._conn.execute(
                "SELECT 1 FROM manual_binning_reviews WHERE review_id = ?", (review_id,)
            )
            return cursor.fetchone() is not None
        sets.append("updated_at = ?")
        params.append(utc_now_iso())
        params.append(review_id)
        cursor = self._conn.execute(
            f"UPDATE manual_binning_reviews SET {', '.join(sets)} WHERE review_id = ?",
            tuple(params),
        )
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_review(row: Any) -> ManualBinningReview:
        raw = row["affected_downstream_step_ids_json"]
        affected = json.loads(raw) if raw else []
        return ManualBinningReview(
            review_id=row["review_id"], plan_version_id=row["plan_version_id"],
            step_id=row["step_id"], status=row["status"],
            reviewer_notes=row["reviewer_notes"],
            affected_downstream_step_ids=affected,
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
