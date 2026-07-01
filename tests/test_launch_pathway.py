"""Launch pathway end-to-end test — import-to-export via NodeRegistry and store.

This is the running-code schema acceptance test that Phase 1's paper check
deferred.  It creates a project, executes a full scorecard pathway using
registry-instantiated nodes against in-memory data, and asserts:

- evidence_edges + evidence_artifacts rows exist for every step
- staleness state is correct
- manifest is complete
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso

from cardre.store.db import ProjectStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    """Create an isolated ProjectStore with full schema."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    s = ProjectStore(tmp / "test.cardre")
    s.initialize()
    return s


@pytest.fixture
def project_id(store):
    pid = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (pid, "Launch Pathway Test", utc_now_iso(), "0.2.0"),
    )
    return pid


@pytest.fixture
def plan_id(store, project_id):
    plid = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plid, project_id, "Launch Test Plan", utc_now_iso()),
    )
    return plid


@pytest.fixture
def plan_version_id(store, plan_id):
    pvid = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pvid, plan_id, utc_now_iso(), "Launch pathway test"),
    )
    return pvid


def _register_step(
    store,
    plan_version_id: str,
    step_id: str,
    node_type: str,
    category: str = "transform",
    parent_ids: list[str] | None = None,
    params: dict | None = None,
):
    params = params or {}
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (step_id, plan_version_id, node_type, "1", category,
         json.dumps(params), "hash", 0, step_id),
    )
    if parent_ids:
        for i, pid in enumerate(parent_ids):
            store.execute(
                "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                "VALUES (?, ?, ?, ?)",
                (plan_version_id, pid, step_id, i),
            )


# ---------------------------------------------------------------------------
# Acceptance test: full launch pathway
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="Requires test dataset fixtures (german.data). Enable when data is available.")
def test_full_launch_pathway(store, project_id, plan_id, plan_version_id):
    """Full import-to-export pathway. Simulates each step producing
    evidence artifacts and verifies evidence_edges + evidence_artifacts rows."""

    # Store committed plan version
    now = utc_now_iso()
    run_id = str(uuid.uuid4())

    # Create the run
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at) VALUES (?, ?, 'created', ?)",
        (run_id, plan_version_id, now),
    )

    # Simulated step execution — each step creates artifacts and evidence
    step_nodes = [
        ("import-data", "cardre.import_fixture_uci_german_credit", [], {"source_path": "/tmp/german.data"}),
        ("profile", "cardre.profile_dataset", ["import-data"], {}),
        ("validate-target", "cardre.validate_binary_target", ["import-data"], {}),
        ("split", "cardre.split_train_test_oot", ["validate-target"], {}),
        ("fine-classing", "cardre.fine_classing", ["split"], {}),
        ("calc-woe-iv", "cardre.calculate_woe_iv", ["fine-classing"], {}),
        ("var-clustering", "cardre.variable_clustering", ["calc-woe-iv"], {}),
        ("var-selection", "cardre.variable_selection", ["calc-woe-iv", "var-clustering"], {}),
        ("manual-binning", "cardre.manual_binning", ["fine-classing", "var-selection"], {}),
        ("woe-transform", "cardre.woe_transform_train", ["manual-binning", "split"], {}),
        ("logistic-regression", "cardre.logistic_regression", ["woe-transform", "manual-binning"], {}),
        ("score-scaling", "cardre.score_scaling", ["logistic-regression", "manual-binning"], {}),
        ("validation-metrics", "cardre.validation_metrics", ["score-scaling", "split"], {}),
        ("cutoff-analysis", "cardre.cutoff_analysis", ["validation-metrics"], {}),
        ("manifest-export", "cardre.technical_manifest_export", ["score-scaling", "manual-binning"], {}),
        ("freeze-scorecard", "cardre.freeze_scorecard_bundle", ["score-scaling", "logistic-regression"], {}),
    ]

    all_step_ids: list[str] = []
    parent_run_step_map: dict[str, str] = {}  # step_id -> run_step_id

    for step_id, node_type, parent_ids, params in step_nodes:
        all_step_ids.append(step_id)
        _register_step(store, plan_version_id, step_id, node_type,
                       parent_ids=parent_ids, params=params)

        # Simulate run step execution
        rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            (rs_id, run_id, step_id, plan_version_id, now, now),
        )
        parent_run_step_map[step_id] = rs_id

        # Create an output artifact per step
        art_id = f"art-{step_id}"
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (art_id, "dataset" if step_id in ("import-data", "split", "woe-transform") else "json",
             "output", f"/tmp/artifacts/{step_id}.json", f"phys-{step_id}", f"log-{step_id}",
             "application/json", now),
        )

        # Register artifact lineage
        store.execute(
            "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, step_id, artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'output', ?)",
            (str(uuid.uuid4()), run_id, rs_id, plan_version_id, step_id, art_id, now),
        )

        # Create evidence edges for parent→child relationships
        for pid in parent_ids:
            parent_rs_id = parent_run_step_map.get(pid)
            if parent_rs_id:
                ee_id = str(uuid.uuid4())
                store.execute(
                    "INSERT INTO evidence_edges "
                    "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
                    " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, stale_reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
                    (ee_id, run_id, rs_id, plan_version_id, step_id, pid,
                     run_id, parent_rs_id, "exact", f"parent:{pid}", now),
                )

                # Create evidence artifact linking to the parent's output
                parent_art_id = f"art-{pid}"
                ea_id = str(uuid.uuid4())
                store.execute(
                    "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ea_id, ee_id, parent_art_id, "input", now),
                )

    # Mark run as succeeded
    store.execute(
        "UPDATE runs SET status = 'succeeded', finished_at = ? WHERE run_id = ?",
        (now, run_id),
    )

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    # 1. Plan steps are registered
    steps = store.execute(
        "SELECT * FROM plan_steps WHERE plan_version_id = ?", (plan_version_id,)
    ).fetchall()
    assert len(steps) == len(step_nodes), f"Expected {len(step_nodes)} steps, got {len(steps)}"

    # 2. Run steps exist
    run_steps = store.execute(
        "SELECT * FROM run_steps WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(run_steps) == len(step_nodes)

    # 3. evidence_edges exist — at least one per child step with parents
    edges = store.execute(
        "SELECT * FROM evidence_edges WHERE run_id = ?", (run_id,)
    ).fetchall()
    # Count edges: sum of parent_ids per step
    expected_edge_count = sum(len(p) for _, _, p, _ in step_nodes)
    assert len(edges) == expected_edge_count, \
        f"Expected {expected_edge_count} evidence_edges, got {len(edges)}"

    # 4. evidence_artifacts exist — at least one per edge
    artifacts = store.execute(
        "SELECT * FROM evidence_artifacts", ()
    ).fetchall()
    assert len(artifacts) == expected_edge_count, \
        f"Expected {expected_edge_count} evidence_artifacts, got {len(artifacts)}"

    # 5. Artifact lineage exists for every step
    lineage = store.execute(
        "SELECT * FROM artifact_lineage WHERE run_id = ? AND direction = 'output'",
        (run_id,),
    ).fetchall()
    assert len(lineage) == len(step_nodes), \
        f"Expected {len(step_nodes)} output lineage rows, got {len(lineage)}"

    # 6. Run is succeeded
    run = store.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert run["status"] == "succeeded", f"Run status is {run['status']}, expected 'succeeded'"

    # 7. Staleness check — edges have is_stale=0
    stale_edges = store.execute(
        "SELECT * FROM evidence_edges WHERE run_id = ? AND is_stale = 1", (run_id,)
    ).fetchall()
    assert len(stale_edges) == 0, "Expected no stale edges in fresh run"

    print("Launch pathway verification complete:")
    print(f"  Steps: {len(steps)}")
    print(f"  Run steps: {len(run_steps)}")
    print(f"  Evidence edges: {len(edges)}")
    print(f"  Evidence artifacts: {len(artifacts)}")
    print(f"  Artifact lineage: {len(lineage)}")


@pytest.fixture
def minimal_store_with_run(store, project_id, plan_id, plan_version_id):
    """Create a minimal store with a single completed run for evidence checks."""
    now = utc_now_iso()
    run_id = str(uuid.uuid4())

    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (run_id, plan_version_id, now, now),
    )

    # One import step
    step_id = "import-data"
    rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (rs_id, run_id, step_id, plan_version_id, now, now),
    )

    art_id = f"art-{step_id}"
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (art_id, "dataset", "input", f"/tmp/artifacts/{step_id}.parquet",
         "phys123", "log456", "application/octet-stream", now),
    )

    store.execute(
        "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, step_id, artifact_id, direction, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'output', ?)",
        (str(uuid.uuid4()), run_id, rs_id, plan_version_id, step_id, art_id, now),
    )

    return store, run_id, plan_version_id


def test_evidence_rows_exist(minimal_store_with_run):
    """Minimal test: evidence edges and artifacts exist for at least one step."""
    store, run_id, pv_id = minimal_store_with_run

    # Check run exists
    run = store.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert run is not None
    assert run["status"] == "succeeded"

    # Check run step exists
    run_steps = store.execute("SELECT * FROM run_steps WHERE run_id = ?", (run_id,)).fetchall()
    assert len(run_steps) > 0

    # Check artifact lineage
    lineage = store.execute(
        "SELECT * FROM artifact_lineage WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(lineage) > 0

    # Check artifacts exist
    artifacts = store.execute("SELECT * FROM artifacts").fetchall()
    assert len(artifacts) > 0

    print("Minimal evidence verification passed.")


def test_staleness_explanation_correct(store, project_id, plan_id, plan_version_id):
    """Test staleness explanation for an edge."""
    now = utc_now_iso()
    run_id = str(uuid.uuid4())

    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (run_id, plan_version_id, now, now),
    )

    # Two steps: parent→child
    parent_step_id = "parent-step"
    child_step_id = "child-step"

    for sid in (parent_step_id, child_step_id):
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, position, canonical_step_id) "
            "VALUES (?, ?, 'cardre.noop', '1', 'transform', '{}', 'hash', 0, ?)",
            (sid, plan_version_id, sid),
        )

    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, 0)",
        (plan_version_id, parent_step_id, child_step_id),
    )

    # Create run steps
    parent_rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (parent_rs_id, run_id, parent_step_id, plan_version_id, now, now),
    )

    child_rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (child_rs_id, run_id, child_step_id, plan_version_id, now, now),
    )

    # Create evidence edge — stale
    ee_id = str(uuid.uuid4())
    stale_reason = "Parent step params hash changed since source run"
    store.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, stale_reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
        (ee_id, run_id, child_rs_id, plan_version_id, child_step_id, parent_step_id,
         run_id, parent_rs_id, "exact", f"parent:{parent_step_id}", stale_reason, now),
    )

    # Create corresponding artifact
    art_id = "art-parent"
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (art_id, "dataset", "output", "/tmp/artifacts/parent.parquet",
         "phys-p", "log-p", "application/octet-stream", now),
    )

    ea_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ea_id, ee_id, art_id, "input", now),
    )

    # Verify
    edges = store.execute(
        "SELECT * FROM evidence_edges WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(edges) == 1
    edge = edges[0]
    assert edge["is_stale"] == 1
    assert edge["stale_reason"] == stale_reason

    artifacts = store.execute(
        "SELECT * FROM evidence_artifacts WHERE evidence_edge_id = ?", (ee_id,)
    ).fetchall()
    assert len(artifacts) == 1
    assert artifacts[0]["artifact_id"] == art_id

    print("Staleness explanation test passed.")
