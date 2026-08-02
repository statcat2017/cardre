"""Pre-execution node-version validation — obsolete plans must be rejected
before any step runs, creating no run-step records, artifacts or lineage."""

from __future__ import annotations

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.submit_run import SubmitRunCommand
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec


def _step_spec(step_id: str, node_type: str, version: str, parents: list[str] | None = None) -> StepSpec:
    return StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version=version,
        category="transform",
        params={},
        params_hash=json_logical_hash({}),
        parent_step_ids=list(parents or []),
        canonical_step_id=step_id,
    )


def _provision_project(tmp_path, steps):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        uow.commit()
    registry.register(project_id, root)

    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    return project_id, pv_id, uow_factory, root


def _counts(uow_factory, project_id, run_id) -> tuple[int, int, int]:
    with uow_factory.for_project(project_id) as uow:
        run_steps = uow._conn.execute(
            "SELECT COUNT(*) FROM run_steps WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        artifacts = uow._conn.execute(
            "SELECT COUNT(*) FROM artifacts a JOIN artifact_lineage al ON a.artifact_id = al.artifact_id "
            "WHERE al.run_id = ?", (run_id,)
        ).fetchone()[0]
        lineage = uow._conn.execute(
            "SELECT COUNT(*) FROM artifact_lineage WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    return run_steps, artifacts, lineage


def test_mismatch_in_second_step_creates_no_records(tmp_path):
    """A valid first step followed by an obsolete second step must reject the
    whole plan before executing either step."""
    steps = [
        _step_spec("step-1", "cardre.noop", "1"),
        _step_spec("step-2", "cardre.noop", "99", parents=["step-1"]),
    ]
    project_id, pv_id, uow_factory, root = _provision_project(tmp_path, steps)

    settings = Settings(launch_mode=True, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )

    with uow_factory.for_project(project_id) as uow:
        run = uow.runs.get(result.run_id)
        assert run.status == "failed", f"Run status: {run.status}"

    run_steps, artifacts, lineage = _counts(uow_factory, project_id, result.run_id)
    assert run_steps == 0, f"Expected no run-step records, got {run_steps}"
    assert artifacts == 0, f"Expected no artifacts, got {artifacts}"
    assert lineage == 0, f"Expected no lineage, got {lineage}"

    with uow_factory.for_project(project_id) as uow:
        diagnostics = uow.runs.get_diagnostics(result.run_id)
    assert diagnostics, "failed run must carry a diagnostic"
    codes = {d["code"] for d in diagnostics}
    assert "NODE_VERSION_MISMATCH" in codes, f"Expected NODE_VERSION_MISMATCH diagnostic, got {diagnostics}"
    mismatch = next(d for d in diagnostics if d["code"] == "NODE_VERSION_MISMATCH")
    assert "step-2" in mismatch["message"]
    assert "99" in mismatch["message"]


def test_matching_versions_run_succeeds(tmp_path):
    """A plan whose persisted versions all match executes normally."""
    steps = [
        _step_spec("step-1", "cardre.noop", "1"),
        _step_spec("step-2", "cardre.noop", "1", parents=["step-1"]),
    ]
    project_id, pv_id, uow_factory, _ = _provision_project(tmp_path, steps)

    settings = Settings(launch_mode=True, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )

    with uow_factory.for_project(project_id) as uow:
        run = uow.runs.get(result.run_id)
        assert run.status == "succeeded", f"Run status: {run.status}"


def test_obsolete_threshold_optimization_version_rejected_pre_execution(tmp_path):
    """A persisted v1 threshold_optimization step must be rejected before any
    step executes once the node moved to v2 (output contract changed)."""
    from cardre.bootstrap.node_catalogue import build_default_catalogue

    cat = build_default_catalogue(Settings(launch_mode=False))
    current = cat.resolve("cardre.threshold_optimization").node_definition().version
    assert current == "2", f"expected threshold_optimization at v2, got {current}"

    steps = [
        _step_spec("step-1", "cardre.threshold_optimization", "1"),
    ]
    project_id, pv_id, uow_factory, root = _provision_project(tmp_path, steps)

    settings = Settings(launch_mode=False, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )

    with uow_factory.for_project(project_id) as uow:
        run = uow.runs.get(result.run_id)
        assert run.status == "failed", f"Run status: {run.status}"
        diagnostics = uow.runs.get_diagnostics(result.run_id)
    codes = {d["code"] for d in diagnostics}
    assert "NODE_VERSION_MISMATCH" in codes, f"Expected NODE_VERSION_MISMATCH, got {diagnostics}"

    run_steps, artifacts, lineage = _counts(uow_factory, project_id, result.run_id)
    assert run_steps == 0, f"Expected no run-step records, got {run_steps}"
    assert artifacts == 0, f"Expected no artifacts, got {artifacts}"
    assert lineage == 0, f"Expected no lineage, got {lineage}"
