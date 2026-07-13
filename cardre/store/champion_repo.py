"""Champion repository — read-only access to champion_assignments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cardre.domain.diagnostics import JsonDict

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class ChampionRepository:
    """Repository for champion assignment reads."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def get_champion_assignment_for_project(self, project_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM champion_assignments "
            "WHERE project_id = ? AND superseded_at IS NULL "
            "ORDER BY assigned_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_champion_assignment(self, plan_id: str, champion_branch_id: str | None = None) -> JsonDict | None:
        if champion_branch_id:
            row = self._store.execute(
                "SELECT * FROM champion_assignments WHERE plan_id = ? AND champion_branch_id = ? AND superseded_at IS NULL",
                (plan_id, champion_branch_id),
            ).fetchone()
        else:
            row = self._store.execute(
                "SELECT * FROM champion_assignments WHERE plan_id = ? AND superseded_at IS NULL",
                (plan_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def get_champion_assignment_by_branch(self, branch_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM champion_assignments WHERE champion_branch_id = ? AND superseded_at IS NULL",
            (branch_id,),
        ).fetchone()
        return None if row is None else dict(row)
