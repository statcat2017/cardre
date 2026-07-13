"""SQLite-backed metadata store for Cardre v2 projects.

Re-exports ``ProjectStore`` and repository classes for focused access.
"""

from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.branch_repo import BranchRepository
from cardre.store.champion_repo import ChampionRepository
from cardre.store.comparison_repo import ComparisonRepository
from cardre.store.db import ProjectStore
from cardre.store.evidence_repo import EvidenceRepository
from cardre.store.manual_binning_repo import ManualBinningRepository
from cardre.store.plan_repo import PlanRepository
from cardre.store.project_repo import ProjectRepository
from cardre.store.run_repo import RunRepository
from cardre.store.run_step_repo import RunStepRepository
from cardre.store.schema import (
    ALL_TABLES_SQL,
    ANNOTATION_TABLES_SQL,
    BRANCH_TABLES_SQL,
    EVIDENCE_TABLES_SQL,
    EXPORTS_TABLE_SQL,
    INDEXES_SQL,
    REVIEW_TABLES_SQL,
    SCHEMA_SQL,
)
from cardre.store.step_repo import StepRepository

__all__ = [
    "ALL_TABLES_SQL",
    "ANNOTATION_TABLES_SQL",
    "BRANCH_TABLES_SQL",
    "EVIDENCE_TABLES_SQL",
    "EXPORTS_TABLE_SQL",
    "INDEXES_SQL",
    "REVIEW_TABLES_SQL",
    "SCHEMA_SQL",
    "ArtifactRepository",
    "BranchRepository",
    "ChampionRepository",
    "ComparisonRepository",
    "EvidenceRepository",
    "ManualBinningRepository",
    "PlanRepository",
    "ProjectRepository",
    "ProjectStore",
    "RunRepository",
    "RunStepRepository",
    "StepRepository",
]
