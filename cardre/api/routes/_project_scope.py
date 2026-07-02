"""Helpers for enforcing project-scoped resource ownership."""

from __future__ import annotations

from cardre.store.db import ProjectStore


def run_belongs_to_project(store: ProjectStore, project_id: str, run_id: str) -> bool:
    row = store.execute(
        "SELECT 1 FROM runs r "
        "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
        "JOIN plans p ON pv.plan_id = p.plan_id "
        "WHERE p.project_id = ? AND r.run_id = ?",
        (project_id, run_id),
    ).fetchone()
    return row is not None


def plan_belongs_to_project(store: ProjectStore, project_id: str, plan_id: str) -> bool:
    row = store.execute(
        "SELECT 1 FROM plans WHERE project_id = ? AND plan_id = ?",
        (project_id, plan_id),
    ).fetchone()
    return row is not None


def plan_version_belongs_to_project(store: ProjectStore, project_id: str, plan_version_id: str) -> bool:
    row = store.execute(
        "SELECT 1 FROM plan_versions pv "
        "JOIN plans p ON pv.plan_id = p.plan_id "
        "WHERE p.project_id = ? AND pv.plan_version_id = ?",
        (project_id, plan_version_id),
    ).fetchone()
    return row is not None


def branch_belongs_to_project(store: ProjectStore, project_id: str, branch_id: str) -> bool:
    row = store.execute(
        "SELECT 1 FROM plan_branches WHERE project_id = ? AND branch_id = ?",
        (project_id, branch_id),
    ).fetchone()
    return row is not None


def step_belongs_to_project(store: ProjectStore, project_id: str, plan_version_id: str, step_id: str) -> bool:
    row = store.execute(
        "SELECT 1 FROM plan_steps ps "
        "JOIN plan_versions pv ON ps.plan_version_id = pv.plan_version_id "
        "JOIN plans p ON pv.plan_id = p.plan_id "
        "WHERE p.project_id = ? AND ps.plan_version_id = ? AND ps.step_id = ?",
        (project_id, plan_version_id, step_id),
    ).fetchone()
    return row is not None
