"""Tests for honest audit persistence (#213).

A step-recording failure must not fabricate artifacts.  The new execution
path records a failed run step with empty output_artifact_ids and a typed
error entry — no phantom outputs.
"""

from __future__ import annotations

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.submit_run import SubmitRunCommand
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec
from cardre.workflows import build_canonical_scorecard_steps


def _write_input_csv(path):
    import csv

    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def provisioned(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        uow.commit()
    registry.register(project_id, root)

    csv_path = _write_input_csv(tmp_path / "input.csv")
    steps = build_canonical_scorecard_steps(csv_path)
    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    settings = Settings(launch_mode=True, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    return project_id, pv_id, container, uow_factory


def test_failed_step_records_no_phantom_outputs(provisioned):
    """A failing step records a failed run step with empty output artifacts (#213)."""
    project_id, pv_id, container, uow_factory = provisioned

    # Seed a plan with a single step that will deterministically fail:
    # apply-woe-mapping with no bin definition artifact.
    from cardre.nodes.validate.apply import ApplyWoeMappingNode

    node = ApplyWoeMappingNode()
    spec = StepSpec(
        step_id="apply-woe",
        node_type="cardre.apply_woe_mapping",
        node_version=node.version,
        category=node.category,
        params={},
        params_hash=json_logical_hash({}),
        parent_step_ids=[],
    )
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Fail Plan")
        fail_pv = uow.plans.create_version(plan_id, [spec], is_committed=True)
        uow.commit()

    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=fail_pv, sync=True),
    )
    assert result.status == "failed", f"Run should fail: {result}"

    with uow_factory.read_only(project_id) as uow:
        run_steps = uow.run_steps.get_for_run(result.run_id)
        assert len(run_steps) == 1
        rs = run_steps[0]
        assert rs.status.value == "failed"
        # No phantom output artifacts for the failed step.
        outputs = uow.artifacts.output_artifact_ids_for_run_step(rs.run_step_id)
        assert outputs == [], f"Failed step should have no output artifacts, got {outputs}"
        assert rs.errors, "Failed step should carry a typed error entry"
