"""BranchService — branch creation orchestration.

Orchestrates validation, graph remapping, and transactional writing.
``create_branch`` delegates to:
  1. ``BranchValidator`` — pure validation
  2. ``BranchGraphRemapper`` — pure graph cloning + ID remapping
  3. ``BranchTransactionWriter`` — atomic transactional writes
"""

from __future__ import annotations

from typing import Any

from cardre.services.branch_graph import BranchGraphRemapper
from cardre.services.branch_validator import BranchValidator
from cardre.services.branch_writer import BranchTransactionWriter
from cardre.store.db import ProjectStore


class BranchService:
    """Business logic for branch creation and management."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
        self._validator = BranchValidator(store)
        self._graph_remapper = BranchGraphRemapper()
        self._writer = BranchTransactionWriter(store)

    def create_branch(
        self,
        project_id: str,
        plan_id: str,
        name: str,
        branch_type: str,
        branch_point_step_id: str,
        base_branch_id: str | None = None,
        base_plan_version_id: str | None = None,
        created_reason: str = "",
        description: str | None = None,
        segment_filter_spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a constrained challenger branch from a permitted branch point.

        Atomic: plan version, branch metadata, and branch step maps
        are committed in a single transaction.

        Returns a dict with branch metadata, created step IDs, and shared
        upstream step IDs.
        """
        validated = self._validator.validate_create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name=name,
            branch_type=branch_type,
            branch_point_step_id=branch_point_step_id,
            base_branch_id=base_branch_id,
            base_plan_version_id=base_plan_version_id,
            created_reason=created_reason,
            description=description,
            segment_filter_spec=segment_filter_spec,
        )

        clone = self._graph_remapper.build_clone(validated)

        return self._writer.create_branch_with_graph(validated, clone)


__all__ = ["BranchService"]
