"""Baseline branch migration service.

Migrates existing Phase 3 projects into the Phase 4 branch model
without rewriting historical run evidence or artefact records.
"""

from __future__ import annotations

import uuid
from typing import Any

from cardre.audit import utc_now_iso
from cardre.store import ProjectStore


def migrate_project_to_branch_model(
    store: ProjectStore,
    project_id: str,
) -> dict[str, Any]:
    """Create baseline branches for all user-facing Scorecard Pathway plans.

    This is a metadata-only migration. It does not rewrite:
      - run records
      - run_step records
      - artefact records
      - artefact files
      - execution fingerprints

    Returns a dict with migration results.
    """
    store.run_migrations()

    plans = store.get_plans_for_project(project_id)
    branches_created = 0
    plan_versions_mapped = 0
    steps_mapped = 0

    for plan in plans:
        plan_id = plan["plan_id"]
        plan_name = plan["name"]

        if plan_name == "__import__":
            continue

        all_versions = store.list_plan_versions(plan_id)
        if not all_versions:
            continue

        earliest_pv_id = all_versions[0]["plan_version_id"]
        latest_pv_id = all_versions[-1]["plan_version_id"]

        existing = store.list_branches(project_id, plan_id)
        baseline_branches = [b for b in existing if b.get("branch_type") == "baseline"]

        if baseline_branches:
            existing_branch_id = baseline_branches[0]["branch_id"]
            maps = store._connect().execute(
                "SELECT DISTINCT plan_version_id FROM branch_step_map WHERE branch_id = ?",
                (existing_branch_id,),
            ).fetchall()
            mapped_versions = {r["plan_version_id"] for r in maps}
            all_version_ids = {r["plan_version_id"] for r in all_versions}
            missing = all_version_ids - mapped_versions
            if missing:
                raise ValueError(
                    f"INCOMPLETE_BRANCH_MAP: Baseline branch {existing_branch_id} "
                    f"is missing step map entries for plan versions: {sorted(missing)}. "
                    "Run full migration or manually repair branch_step_map."
                )
            continue

        now = utc_now_iso()
        branch_id = str(uuid.uuid4())
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO plan_branches "
                "(branch_id, project_id, plan_id, name, description, branch_type, status, "
                " base_branch_id, base_plan_version_id, head_plan_version_id, "
                " branch_point_step_id, branch_point_canonical_step_id, "
                " segment_filter_spec_json, created_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    branch_id, project_id, plan_id, "Baseline", None, "baseline",
                    None, earliest_pv_id, latest_pv_id,
                    None, None,
                    None,
                    "Created automatically during Phase 4 baseline branch migration.",
                    now, now,
                ),
            )

            branches_created += 1

            for pv in all_versions:
                pv_id = pv["plan_version_id"]
                steps = store.get_plan_version_steps(pv_id)
                for step in steps:
                    conn.execute(
                        "INSERT INTO branch_step_map "
                        "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
                        " source_branch_id, source_step_id, is_shared_upstream, is_branch_owned, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(uuid.uuid4()),
                            branch_id, pv_id, step.canonical_step_id, step.step_id,
                            None, None, 0, 1,
                            now,
                        ),
                    )
                    steps_mapped += 1
                plan_versions_mapped += 1

    return {
        "project_id": project_id,
        "branches_created": branches_created,
        "plan_versions_mapped": plan_versions_mapped,
        "steps_mapped": steps_mapped,
    }
