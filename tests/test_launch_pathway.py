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

from cardre.domain.artifacts import ArtifactRef
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


def _seed_launch_plan(store: ProjectStore) -> tuple[str, str, list[dict]]:
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
            _step("import-data", "cardre.import_fixture_uci_german_credit", 0, []),
            _step("profile", "cardre.profile_dataset", 1, ["import-data"]),
            _step("export", "cardre.technical_manifest_export", 2, ["profile"]),
        ],
        is_committed=True,
    )
    return project_id, plan_version_id, [
        {"step_id": "import-data", "artifact_id": "art-import"},
        {"step_id": "profile", "artifact_id": "art-profile"},
        {"step_id": "export", "artifact_id": "art-export"},
    ]


def _step(step_id: str, node_type: str, position: int, parents: list[str]):
    from cardre.domain.step import StepSpec

    return StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version="1",
        category="transform",
        params={},
        params_hash="hash",
        parent_step_ids=parents,
        position=position,
    )


def test_full_launch_pathway(store, monkeypatch):
    _project_id, plan_version_id, output_specs = _seed_launch_plan(store)

    now = utc_now_iso()
    output_map = {}
    for spec in output_specs:
        artifact = ArtifactRef(
            artifact_id=spec["artifact_id"],
            artifact_type="json",
            role="output",
            path=f"artifacts/{spec['step_id']}.json",
            physical_hash=f"phys-{spec['step_id']}",
            logical_hash=f"log-{spec['step_id']}",
            media_type="application/json",
            created_at=now,
        )
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact.artifact_id,
                artifact.artifact_type,
                artifact.role,
                artifact.path,
                artifact.physical_hash,
                artifact.logical_hash,
                artifact.media_type,
                artifact.created_at,
            ),
        )
        output_map[spec["step_id"]] = [artifact]

    def resolve_output_artifacts(plan_version_id: str, run_id: str, run_step):
        return output_map.get(run_step.step_id, [])

    monkeypatch.setattr(
        PlanExecutor,
        "_resolve_output_artifacts",
        staticmethod(resolve_output_artifacts),
    )

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
