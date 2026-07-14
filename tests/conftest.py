"""Shared pytest fixtures for Cardre v2 tests."""

from __future__ import annotations

import json
import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.store.db import ProjectStore


@pytest.fixture
def store(tmp_path):
    """Create an isolated ProjectStore in a temp directory with full schema.

    Uses pytest's ``tmp_path`` (auto-cleaned) rather than ``tempfile.mkdtemp``
    to avoid leaking temp dirs on disk.
    """
    s = ProjectStore(tmp_path / "test.cardre")
    s.initialize()
    return s


@pytest.fixture
def store_with_evidence(store):
    """Create a store with a plan, plan version, run, run step, and evidence rows."""

    project_id = str(uuid.uuid4())
    now = utc_now_iso()

    # Insert project
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", now, "0.2.0"),
    )

    # Insert plan
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )

    # Insert plan version (committed base)
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )

    # Insert steps
    binning_step_id = "automatic-binning"
    mb_step_id = "manual-binning"
    downstream_step_id = "apply-woe"

    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (binning_step_id, pv_id, "cardre.automatic_binning", "1", "fit",
         json.dumps({"max_bins": 20}), "abc123", "", 0, binning_step_id),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mb_step_id, pv_id, "cardre.manual_binning", "1", "refinement",
         json.dumps({"overrides": []}), "def456", "", 1, mb_step_id),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (downstream_step_id, pv_id, "cardre.apply_woe_mapping", "1", "transform",
         json.dumps({}), "ghi789", "", 2, downstream_step_id),
    )

    # Insert edges
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, binning_step_id, mb_step_id, 0),
    )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, mb_step_id, downstream_step_id, 0),
    )

    # Insert a run with completed steps (simulating an execution)
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )

    # Insert run steps
    rs_binning = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (rs_binning, run_id, binning_step_id, pv_id, now, now),
    )

    rs_mb = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (rs_mb, run_id, mb_step_id, pv_id, now, now),
    )

    rs_downstream = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (rs_downstream, run_id, downstream_step_id, pv_id, now, now),
    )

    # Insert evidence edges (for the manual-binning step from fine-classing)
    ee_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
        " stale_reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
        (ee_id, run_id, rs_mb, pv_id, mb_step_id, binning_step_id,
         run_id, rs_binning, "exact", "binning", now),
    )

    # Insert the artifact first (required by FK constraint)
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("art-bin-001", "bin_definition", "bin_definition", "/tmp/artifacts/bin.json",
         "abc123", "def456", "application/json", now),
    )

    # Insert evidence artifacts
    ea_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ea_id, ee_id, "art-bin-001", "bin_definition", now),
    )

    return store, project_id, plan_id, pv_id, mb_step_id


@pytest.fixture
def api_client():
    """FastAPI TestClient bound to the v2 minimal API."""
    from fastapi.testclient import TestClient

    from cardre.api.app import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _project_resolution_test_env(monkeypatch, tmp_path_factory):
    """Set up registry path for tests. Raw project path is disabled by default.

    Tests that need the legacy raw-path mode should use the
    ``raw_project_path`` fixture to opt in.
    """
    registry_dir = tmp_path_factory.mktemp("cardre-registry")
    monkeypatch.setenv("CARDRE_ALLOW_RAW_PROJECT_PATH", "0")
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(registry_dir / "projects.json"))


@pytest.fixture
def raw_project_path(monkeypatch):
    """Opt-in fixture for tests that need CARDRE_ALLOW_RAW_PROJECT_PATH=1."""
    monkeypatch.setenv("CARDRE_ALLOW_RAW_PROJECT_PATH", "1")


@pytest.fixture
def registered_store(store):
    """Register a store's project in the registry and return (store, project_id).

    Tests that need X-Project-Id can use this fixture instead of manually
    registering the project.
    """
    from cardre.config import CardreConfig
    from cardre.services.project_resolver import ProjectResolver

    rows = store.execute("SELECT project_id FROM projects").fetchall()
    if not rows:
        return store, None
    project_id = rows[0]["project_id"]
    resolver = ProjectResolver(CardreConfig.from_env().registry_path)
    resolver.register_project(project_id, store.root)
    return store, project_id
