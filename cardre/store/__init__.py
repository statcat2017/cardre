"""SQLite-backed metadata store for Cardre projects.

Re-exports ``ProjectStore`` and schema for backward compatibility.
Specialized repository classes are available for focused access.
"""

from cardre.store.project_store import ProjectStore
from cardre.store.schema import BRANCH_TABLES_SQL, SCHEMA_SQL
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.plan_repo import PlanRepository
from cardre.store.run_repo import RunRepository
from cardre.store.branch_repo import BranchRepository
from cardre.store.project_repo import ProjectRepository

__all__ = [
    "ProjectStore", "SCHEMA_SQL", "BRANCH_TABLES_SQL",
    "ArtifactRepository", "PlanRepository", "RunRepository",
    "BranchRepository", "ProjectRepository",
]
