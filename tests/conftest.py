"""Shared pytest fixtures for Cardre v2 tests.

Provides modern SQLite-adapter fixtures (SqliteProjectProvisioner +
SqliteUnitOfWorkFactory + JsonProjectRegistry) replacing the legacy
ProjectStore-based `store` fixture.
"""

from __future__ import annotations

import uuid

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.domain.diagnostics import utc_now_iso


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
def store_with_evidence(provisioned_project):
    """Create a project with a plan, plan version, run, run step, and evidence rows.

    Returns (project_id, uow_factory, plan_id, pv_id, mb_step_id).
    """
    project_id, uow_factory, registry, root = provisioned_project
    now = utc_now_iso()

    binning_step_id = "automatic-binning"
    mb_step_id = "manual-binning"
    downstream_step_id = "apply-woe"

    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            steps=[
                _step_spec(binning_step_id, "cardre.automatic_binning", "fit",
                           {"max_bins": 20}, "abc123", 0, []),
                _step_spec(mb_step_id, "cardre.manual_binning", "refinement",
                           {"overrides": []}, "def456", 1, [binning_step_id]),
                _step_spec(downstream_step_id, "cardre.apply_woe_mapping", "transform",
                           {}, "ghi789", 2, [mb_step_id]),
            ],
            is_committed=True,
        )
        uow.commit()

    with uow_factory.for_project(project_id) as uow:
        run_id = uow.runs.create(pv_id)
        rs_binning = f"{run_id}-automatic-binning"
        rs_mb = f"{run_id}-manual-binning"
        rs_downstream = f"{run_id}-apply-woe"
        for rs_id, step_id in ((rs_binning, binning_step_id), (rs_mb, mb_step_id),
                               (rs_downstream, downstream_step_id)):
            uow._conn.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json) "
                "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
                (rs_id, run_id, step_id, pv_id, now, now),
            )
        uow._conn.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, storage_key, "
            " physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("art-bin-001", "bin_definition", "definition", "/tmp/artifacts/bin.json",
             "abc123", "def456", "application/json", now),
        )
        uow._conn.execute(
            "INSERT INTO evidence_edges "
            "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
            " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
            " stale_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
            (str(uuid.uuid4()), run_id, rs_mb, pv_id, mb_step_id, binning_step_id,
             run_id, rs_binning, "exact", "binning", now),
        )
        uow._conn.execute(
            "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), _edge_id(uow, run_id, rs_mb), "art-bin-001", "definition", now),
        )
        uow.commit()

    return project_id, uow_factory, plan_id, pv_id, mb_step_id


def _step_spec(step_id: str, node_type: str, category: str, params: dict,
               params_hash: str, position: int, parent_step_ids: list[str]):
    from cardre.domain.step import StepSpec

    return StepSpec(
        step_id=step_id, node_type=node_type, node_version="1", category=category,
        params=params, params_hash=params_hash, parent_step_ids=parent_step_ids,
        position=position, canonical_step_id=step_id,
    )


def _edge_id(uow, run_id: str, run_step_id: str) -> str:
    row = uow._conn.execute(
        "SELECT evidence_edge_id FROM evidence_edges WHERE run_id = ? AND run_step_id = ? LIMIT 1",
        (run_id, run_step_id),
    ).fetchone()
    return row["evidence_edge_id"]


@pytest.fixture
def api_client():
    """FastAPI TestClient bound to the v2 minimal API."""
    from fastapi.testclient import TestClient

    from cardre.api._app_instance import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _project_resolution_test_env(monkeypatch, tmp_path_factory):
    """Set up the project registry path for tests."""
    registry_dir = tmp_path_factory.mktemp("cardre-registry")
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(registry_dir / "projects.json"))
