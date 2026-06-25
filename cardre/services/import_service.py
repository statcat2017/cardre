"""Import service — business logic for dataset import orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardre.audit import replace_step_params
from cardre.store import ProjectStore


def import_params_from_request(body: Any, source_path: str) -> dict[str, object]:
    """Build canonical import params dict from an import request body."""
    params: dict[str, object] = {"source_path": str(Path(source_path).resolve())}
    if body.format and body.format != "auto":
        params["format"] = body.format
    if body.delimiter is not None:
        params["delimiter"] = body.delimiter
    if not body.has_header:
        params["has_header"] = False
    if body.schema_overrides:
        params["schema_overrides"] = dict(body.schema_overrides)
    if body.max_rows is not None:
        params["max_rows"] = body.max_rows
    if body.encoding is not None:
        params["encoding"] = body.encoding
    if body.null_values:
        params["null_values"] = list(body.null_values)
    return params


def get_or_create_import_plan(store: ProjectStore, project_id: str) -> str:
    """Find or create a dedicated import plan (separate from proof pathway)."""
    plans = store.get_plans_for_project(project_id)
    for p in plans:
        if p["name"] == "__import__":
            return p["plan_id"]
    return store.create_plan(project_id, "__import__")


def update_single_plan_import_params(
    store: ProjectStore, plan_id: str, source_path: str, extra_params: dict | None = None,
) -> None:
    latest_pv_id = store.get_latest_plan_version_id(plan_id)
    if latest_pv_id is None:
        return
    steps = store.get_plan_version_steps(latest_pv_id)
    params = {"source_path": str(Path(source_path).resolve())}
    if extra_params:
        params.update(extra_params)
    new_steps = replace_step_params(steps, "import", params)
    store.create_plan_version(plan_id, new_steps, description="Import configured")


def update_plan_import_params(
    store: ProjectStore, project_id: str, source_path: str, extra_params: dict | None = None,
) -> None:
    """Update the scorecard pathway's import step with the given source_path.

    Creates a new plan version so the import step knows which file to load.
    Updates both Proof Pathway and Scorecard Pathway if they exist.
    Any *extra_params* (e.g. schema_overrides) are merged into the import step params.
    """
    plans = store.get_plans_for_project(project_id)
    for plan_name in ("Proof Pathway", "Scorecard Pathway"):
        pathway_plan = next((p for p in plans if p["name"] == plan_name), None)
        if pathway_plan is None:
            continue
        plan_id = pathway_plan["plan_id"]
        update_single_plan_import_params(store, plan_id, source_path, extra_params=extra_params)
