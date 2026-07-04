"""Branch transaction writer — atomic branch creation writes.

Owns the single ``IMMEDIATE`` transaction that creates the plan version,
branch metadata, and step map rows.

No validation or graph remapping — the caller supplies validated data
and a pre-built graph clone.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from cardre.domain.diagnostics import utc_now_iso
from cardre.store.plan_repo import PlanRepository

if TYPE_CHECKING:
    from cardre.services.branch_graph import BranchGraphClone
    from cardre.services.branch_validator import ValidatedBranchData
    from cardre.store.db import ProjectStore


class BranchTransactionWriter:
    """Atomic branch creation writer.

    Writes in a single transaction:
      - Plan version + steps + edges (via ``PlanRepository.create_version``)
      - ``plan_branches`` row
      - ``branch_step_map`` rows
    """

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
        self._plans = PlanRepository(store)

    def create_branch_with_graph(
        self,
        validated: ValidatedBranchData,
        clone: BranchGraphClone,
    ) -> dict[str, Any]:
        """Create a branch atomically and return the branch metadata dict.

        The transaction includes plan version creation, branch metadata
        insert, and step map inserts.
        """
        now = utc_now_iso()

        with self._store.transaction("IMMEDIATE") as conn:
            # 1. Insert plan version + steps via the shared plan repository.
            new_pv_id = self._plans.create_version(
                validated.plan_id,
                clone.new_steps,
                description=f"Branch '{validated.name}' created from {validated.branch_point_step_id}",
                is_committed=False,
                conn=conn,
            )

            # 2. Insert branch metadata
            conn.execute(
                "INSERT INTO plan_branches "
                "(branch_id, project_id, plan_id, name, description, branch_type, status, "
                " base_branch_id, base_plan_version_id, head_plan_version_id, "
                " branch_point_step_id, branch_point_canonical_step_id, "
                " segment_filter_spec_json, created_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    clone.branch_id,
                    validated.project_id,
                    validated.plan_id,
                    validated.name,
                    validated.description,
                    validated.branch_type,
                    validated.base_branch_id,
                    validated.head_pv_id,
                    new_pv_id,
                    validated.branch_point_step_id,
                    clone.branch_point_canonical_step_id,
                    validated.segment_filter_json,
                    validated.created_reason,
                    now,
                    now,
                ),
            )

            # 3. Insert step maps
            for s in clone.new_steps:
                was_duplicated = s.step_id in list(clone.created_step_ids.values())
                is_shared = not was_duplicated
                original_step_id = (
                    clone.source_of_new_step.get(s.step_id) if was_duplicated
                    else s.step_id
                )

                conn.execute(
                    "INSERT INTO branch_step_map "
                    "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
                    " source_branch_id, source_step_id, is_shared_upstream, is_branch_owned, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        clone.branch_id,
                        new_pv_id,
                        s.canonical_step_id,
                        s.step_id,
                        validated.base_branch_id if (was_duplicated or is_shared) else None,
                        original_step_id if was_duplicated else s.step_id if is_shared else None,
                        1 if is_shared else 0,
                        0 if is_shared else 1,
                        now,
                    ),
                )

        return {
            "branch_id": clone.branch_id,
            "new_plan_version_id": new_pv_id,
            "name": validated.name,
            "branch_type": validated.branch_type,
            "branch_point_step_id": validated.branch_point_step_id,
            "branch_point_canonical_step_id": clone.branch_point_canonical_step_id,
            "created_step_ids": clone.created_step_ids,
            "shared_upstream_step_ids": clone.shared_upstream_step_ids,
            "status": "not_run",
            "warnings": [],
        }


__all__ = ["BranchTransactionWriter"]
