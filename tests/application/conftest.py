"""Shared fixtures for governance/plans/evidence use-case characterization tests.

These tests exercise the new application-layer use cases through the
production SQLite persistence stack (SqliteProjectProvisioner,
SqliteUnitOfWorkFactory, JsonProjectRegistry) instead of the legacy
ProjectStore + service path.
"""

from __future__ import annotations

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec


def make_branchable_steps() -> list[StepSpec]:
    """sample-definition -> variable-selection -> manual-binning -> logistic-regression."""
    return [
        StepSpec(
            step_id="step-sample-def", node_type="cardre.noop",
            node_version="1", category="transform",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
            canonical_step_id="sample-definition",
        ),
        StepSpec(
            step_id="step-var-sel", node_type="cardre.variable_selection",
            node_version="1", category="fit",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=["step-sample-def"], branch_label="", position=1,
            canonical_step_id="variable-selection",
        ),
        StepSpec(
            step_id="step-manual-bin", node_type="cardre.manual_binning",
            node_version="1", category="refinement",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=["step-var-sel"], branch_label="", position=2,
            canonical_step_id="manual-binning",
        ),
        StepSpec(
            step_id="step-logistic-reg", node_type="cardre.logistic_regression",
            node_version="1", category="fit",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=["step-manual-bin"], branch_label="", position=3,
            canonical_step_id="logistic-regression",
        ),
    ]


@pytest.fixture
def provisioned_project(tmp_path):
    """Provision a real project database and return (project_id, uow_factory, registry, root)."""
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "projects" / "project-1"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test Project")
        uow.commit()

    registry.register(project_id, root)
    return project_id, uow_factory, registry, root


@pytest.fixture
def plan_with_branchable_version(provisioned_project):
    """Create a plan + committed version with branchable steps.

    Returns (project_id, plan_id, pv_id, uow_factory, registry, root).
    """
    project_id, uow_factory, registry, root = provisioned_project
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        pv_id = uow.plans.create_version(
            plan_id, make_branchable_steps(),
            description="char-branch-base", is_committed=True,
        )
        uow.commit()
    return project_id, plan_id, pv_id, uow_factory, registry, root
