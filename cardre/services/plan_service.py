"""PlanService — query and commit operations for plans.

Step mutations (edits that create new draft versions) go through
``PlanMutationService``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cardre.domain.plan import Plan, PlanVersion
from cardre.store.plan_repo import PlanRepository
from cardre.domain.errors import CardreError

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class PlanServiceError(CardreError):
    """Raised when a plan operation fails."""
    code = "PLAN_SERVICE_ERROR"
    status_code = 400


class PlanService:
    """Service for querying and committing plans."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
        self._plan_repo = PlanRepository(store)

    def get_plan(self, plan_id: str) -> Plan | None:
        """Get a plan by ID."""
        row = self._plan_repo.get_plan(plan_id)
        if row is None:
            return None
        return Plan(
            plan_id=row["plan_id"],
            project_id=row["project_id"],
            name=row["name"],
            created_at=row["created_at"],
        )

    def get_plan_version(self, plan_version_id: str) -> PlanVersion | None:
        """Get a plan version by ID."""
        row = self._plan_repo.get_version(plan_version_id)
        if row is None:
            return None
        return PlanVersion(
            plan_version_id=row["plan_version_id"],
            plan_id=row["plan_id"],
            version_number=row["version_number"],
            is_committed=bool(row.get("is_committed", False)),
            created_at=row["created_at"],
            description=row.get("description", ""),
        )

    def list_plans(self, project_id: str) -> list[Plan]:
        """List all plans for a project."""
        rows = self._plan_repo.list_for_project(project_id)
        return [
            Plan(
                plan_id=r["plan_id"],
                project_id=r["project_id"],
                name=r["name"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def commit_plan_version(self, plan_version_id: str) -> PlanVersion:
        """Commit a draft plan version, making it read-only.

        Raises ``PlanServiceError`` if the version is already committed
        or does not exist.
        """
        existing = self._plan_repo.get_version(plan_version_id)
        if existing is None:
            raise PlanServiceError(
                f"Plan version {plan_version_id!r} not found."
            )

        if existing.get("is_committed"):
            raise PlanServiceError(
                f"Plan version {plan_version_id!r} is already committed."
            )

        self._plan_repo.commit_version(plan_version_id)

        return PlanVersion(
            plan_version_id=existing["plan_version_id"],
            plan_id=existing["plan_id"],
            version_number=existing["version_number"],
            is_committed=True,
            created_at=existing["created_at"],
            description=existing.get("description", ""),
        )


__all__ = [
    "PlanService",
    "PlanServiceError",
]
