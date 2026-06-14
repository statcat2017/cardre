"""Import service — business logic for dataset import orchestration."""

from __future__ import annotations

from pathlib import Path

from cardre.audit import replace_step_params
from cardre.store import ProjectStore


def get_or_create_import_plan(store: ProjectStore, project_id: str) -> str:
    """Find or create a dedicated import plan (separate from proof pathway)."""
    plans = store.get_plans_for_project(project_id)
    for p in plans:
        if p["name"] == "__import__":
            return p["plan_id"]
    return store.create_plan(project_id, "__import__")


def update_single_plan_import_params(store: ProjectStore, plan_id: str, source_path: str) -> None:
    latest_pv_id = store.get_latest_plan_version_id(plan_id)
    if latest_pv_id is None:
        return
    steps = store.get_plan_version_steps(latest_pv_id)
    params = {"source_path": str(Path(source_path).resolve())}
    new_steps = replace_step_params(steps, "import", params)
    store.create_plan_version(plan_id, new_steps, description="Import configured")


def update_plan_import_params(store: ProjectStore, project_id: str, source_path: str) -> None:
    """Update the scorecard pathway's import step with the given source_path.

    Creates a new plan version so the import step knows which file to load.
    Updates both Proof Pathway and Scorecard Pathway if they exist.
    """
    plans = store.get_plans_for_project(project_id)
    for plan_name in ("Proof Pathway", "Scorecard Pathway"):
        pathway_plan = next((p for p in plans if p["name"] == plan_name), None)
        if pathway_plan is None:
            continue
        plan_id = pathway_plan["plan_id"]
        update_single_plan_import_params(store, plan_id, source_path)
