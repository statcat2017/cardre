"""Launch pathway acceptance test.

This drives ``PlanExecutor`` through a small plan, uses a tiny output seam to
simulate node-produced artifacts, and verifies evidence rows plus the final
run manifest.
"""

from __future__ import annotations

import json
import uuid
import tempfile
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.execution.executor import PlanExecutor
from cardre.execution.run_lifecycle import RunLifecycle
from cardre.store.db import ProjectStore
from cardre.store.plan_repo import PlanRepository
from cardre.store.run_repo import RunRepository
from cardre.store.run_step_repo import RunStepRepository


@pytest.fixture
def store():
    tmp = Path(tempfile.mkdtemp())
    s = ProjectStore(tmp / "test.cardre")
    s.initialize()
    return s


def _write_input_csv(root: Path) -> Path:
    input_path = root / "launch-input.csv"
    input_path.write_text(
        "credit_amount,age_years,credit_risk_class\n"
        "1000,35,good\n"
        "2500,42,bad\n",
        encoding="utf-8",
    )
    return input_path


def _seed_launch_plan(store: ProjectStore, source_path: Path) -> tuple[str, str]:
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Launch Pathway Test", now, "0.2.0"),
    )

    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Launch Plan", now),
    )

    plan_version_id = PlanRepository(store).create_version(
        plan_id,
        steps=[
            _step("import-data", "cardre.import_dataset", 0, [], params={"source_path": str(source_path)}),
            _step("profile", "cardre.profile_dataset", 1, ["import-data"]),
            _step("export", "cardre.technical_manifest_export", 2, ["profile"]),
        ],
        is_committed=True,
    )
    return project_id, plan_version_id


def _step(step_id: str, node_type: str, position: int, parents: list[str], params: dict | None = None):
    from cardre.domain.step import StepSpec

    return StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version="1",
        category="transform",
        params=params or {},
        params_hash="hash",
        parent_step_ids=parents,
        position=position,
    )


def test_full_launch_pathway(store):
    input_path = _write_input_csv(store.root.parent)
    _project_id, plan_version_id = _seed_launch_plan(store, input_path)

    run_id = RunRepository(store).create(plan_version_id)
    executor = PlanExecutor(store)
    executor.run_plan_version(plan_version_id, run_id)

    lifecycle = RunLifecycle(store, run_id, plan_version_id, execution_mode="full_plan")
    lifecycle.finalise(status="succeeded", execution_mode="full_plan")

    run_steps = RunStepRepository(store).get_for_run(run_id)
    assert [rs.step_id for rs in run_steps] == ["import-data", "profile", "export"]

    edges = store.execute(
        "SELECT * FROM evidence_edges WHERE run_id = ? ORDER BY created_at",
        (run_id,),
    ).fetchall()
    assert len(edges) == 2
    assert all(edge["is_stale"] == 0 for edge in edges)

    evidence_artifacts = store.execute(
        "SELECT * FROM evidence_artifacts ea JOIN evidence_edges ee ON ee.evidence_edge_id = ea.evidence_edge_id WHERE ee.run_id = ?",
        (run_id,),
    ).fetchall()
    assert len(evidence_artifacts) == 2

    manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["run_id"] == run_id
    assert manifest["status"] == "succeeded"
    assert [step["step_id"] for step in manifest["steps"]] == [
        "import-data",
        "profile",
        "export",
    ]
