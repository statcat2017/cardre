"""Tests for run_step_writer — run_step/evidence/lineage persistence.

Exercises the writer through ``PlanExecutor.run_plan_version`` for the
main write path, and through direct ``write_reused_run_step`` calls for
the carried-forward (reuse) path.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
from cardre.domain.run import RunStep, RunStepStatus
from cardre.execution.executor import PlanExecutor
from cardre.execution.run_step_writer import write_reused_run_step

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore

    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_plan_version(store, input_path):
    """Seed a store with a plan, steps, and edges. Returns (plan_version_id, step_ids)."""
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )

    step_import = "step-import"
    step_profile = "step-profile"
    step_export = "step-export"

    for sid, node_type, params_json, pos in [
        (
            step_import,
            "cardre.import_dataset",
            json.dumps({"source_path": str(input_path)}),
            0,
        ),
        (step_profile, "cardre.profile_dataset", json.dumps({}), 1),
        (step_export, "cardre.technical_manifest_export", json.dumps({}), 2),
    ]:
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, pv_id, node_type, "1", "transform", params_json, f"hash-{sid}", "",
             pos, sid),
        )

    for parent, child, order in [
        (step_import, step_profile, 0),
        (step_profile, step_export, 0),
    ]:
        store.execute(
            "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
            "VALUES (?, ?, ?, ?)",
            (pv_id, parent, child, order),
        )

    return pv_id, [step_import, step_profile, step_export]


def _write_input_csv(project_root: Path) -> Path:
    input_path = project_root / "input.csv"
    input_path.write_text(
        "credit_amount,age_years,credit_risk_class\n"
        "1000,35,good\n"
        "2500,42,bad\n",
        encoding="utf-8",
    )
    return input_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunStepWriter:
    """run_step_writer exercised through PlanExecutor."""

    def test_run_step_row_persisted(self, tmp_path):
        """run_step row exists with correct status, step_id, run_id."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        from cardre.store.run_repo import RunRepository

        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        for step_id in step_ids:
            row = store.execute(
                "SELECT run_id, step_id, status FROM run_steps WHERE run_id = ? AND step_id = ?",
                (run_id, step_id),
            ).fetchone()
            assert row is not None, f"No run_step row for {step_id}"
            assert row["run_id"] == run_id
            assert row["step_id"] == step_id
            assert row["status"] == "succeeded"

    def test_evidence_edges_count(self, tmp_path):
        """evidence_edges count equals number of parent_run_steps."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        from cardre.store.run_repo import RunRepository

        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        rows = store.execute(
            "SELECT step_id, COUNT(*) as cnt FROM evidence_edges WHERE run_id = ? GROUP BY step_id",
            (run_id,),
        ).fetchall()
        counts = {r["step_id"]: r["cnt"] for r in rows}
        # step-import (root): no parents → 0 edges
        assert counts.get("step-import", 0) == 0
        # step-profile: 1 parent (step-import)
        assert counts.get("step-profile", 0) == 1
        # step-export: 1 parent (step-profile)
        assert counts.get("step-export", 0) == 1

    def test_evidence_artifacts_match_lineage(self, tmp_path):
        """evidence_artifacts per edge correspond to parent output lineage."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        from cardre.store.run_repo import RunRepository

        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        edge_rows = store.execute(
            "SELECT evidence_edge_id, parent_step_id FROM evidence_edges WHERE run_id = ?",
            (run_id,),
        ).fetchall()

        for edge in edge_rows:
            edge_aids = [
                r["artifact_id"]
                for r in store.execute(
                    "SELECT artifact_id FROM evidence_artifacts WHERE evidence_edge_id = ? ORDER BY artifact_id",
                    (edge["evidence_edge_id"],),
                ).fetchall()
            ]
            parent_outputs = store.execute(
                "SELECT artifact_id FROM artifact_lineage "
                "WHERE run_id = ? AND step_id = ? AND direction = 'output' ORDER BY artifact_id",
                (run_id, edge["parent_step_id"]),
            ).fetchall()
            parent_aids = [r["artifact_id"] for r in parent_outputs]

            assert edge_aids == parent_aids, (
                f"Evidence artifacts for parent {edge['parent_step_id']!r} "
                f"do not match its output lineage: got {edge_aids}, expected {parent_aids}"
            )

    def test_artifact_lineage_directions(self, tmp_path):
        """artifact_lineage has input and output rows for non-root steps."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        from cardre.store.run_repo import RunRepository

        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        dir_rows = store.execute(
            "SELECT step_id, direction, COUNT(*) as cnt FROM artifact_lineage "
            "WHERE run_id = ? GROUP BY step_id, direction",
            (run_id,),
        ).fetchall()
        dirs = {(r["step_id"], r["direction"]): r["cnt"] for r in dir_rows}

        # step-import (root): 0 inputs, ≥1 outputs
        assert dirs.get(("step-import", "output"), 0) >= 1

        # step-profile: ≥1 inputs (from import), ≥1 outputs
        assert dirs.get(("step-profile", "input"), 0) >= 1
        assert dirs.get(("step-profile", "output"), 0) >= 1

        # step-export: ≥1 inputs (from profile), may produce outputs
        assert dirs.get(("step-export", "input"), 0) >= 1

    def test_failed_step_errors_json(self, tmp_path):
        """On a failed step, structured error payload is persisted in errors_json."""
        store = _make_store(tmp_path)
        # Use a nonexistent path to cause the import node to fail at runtime
        nonexistent = tmp_path / "nonexistent.csv"
        input_path_ok = _write_input_csv(tmp_path)
        pv_id, _ = _seed_plan_version(store, input_path_ok)

        # Swap the import step's params to point to a non-existent file
        pv_id_fail = str(uuid.uuid4())
        now = utc_now_iso()

        # We need a separate plan version where the import step will fail.
        # Create a minimal plan with a single step that cannot succeed.
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Fail Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Fail Plan", now),
        )
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
            "VALUES (?, ?, 1, 1, ?, ?)",
            (pv_id_fail, plan_id, now, "Failure test"),
        )

        fail_step_id = "step-fail"
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fail_step_id, pv_id_fail, "cardre.import_dataset", "1", "transform",
             json.dumps({"source_path": str(nonexistent)}), "hash-fail", "", 0,
             fail_step_id),
        )

        from cardre.store.run_repo import RunRepository

        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id_fail)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id_fail, run_id)

        row = store.execute(
            "SELECT status, errors_json FROM run_steps WHERE run_id = ? AND step_id = ?",
            (run_id, fail_step_id),
        ).fetchone()
        assert row is not None, "No run_step row for failed step"
        assert row["status"] == "failed", f"Expected failed status, got {row['status']}"

        errors = json.loads(row["errors_json"])
        assert isinstance(errors, list), f"errors_json should be a list, got {type(errors)}"
        assert len(errors) >= 1, "Expected at least one error entry"

        error = errors[0]
        assert "code" in error, f"Error entry missing 'code': {error}"
        assert "message" in error, f"Error entry missing 'message': {error}"
        # The error should reference file-not-found or similar
        assert "traceback" in error, f"Error entry missing 'traceback': {error}"

    def test_reused_step_fingerprint_keys(self, tmp_path):
        """Reused step has cardre_step_carried_forward and carried_forward_from_run_step_id."""
        store = _make_store(tmp_path)

        # Seed a prior run step that we'll "carry forward"
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Reuse Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Reuse Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
            "VALUES (?, ?, 1, 1, ?, ?)",
            (pv_id, plan_id, now, "Reuse version"),
        )

        step_id = "step-reused"
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (step_id, pv_id, "cardre.noop", "1", "transform",
             json.dumps({}), "hash-reuse", "", 0, step_id),
        )

        # Insert a prior run and run_step
        from cardre.store.run_repo import RunRepository

        prior_run_id = run_repo = RunRepository(store)
        # Actually create the prior run
        run_repo = RunRepository(store)
        prior_run_id = run_repo.create(pv_id)

        prior_rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps "
            "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
            " execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            (prior_rs_id, prior_run_id, step_id, pv_id, now, now),
        )

        # Build the data for write_reused_run_step — as the executor would
        new_run_id = run_repo.create(pv_id)
        new_rs_id = str(uuid.uuid4())

        copied_fp = {
            "cardre_step_carried_forward": True,
            "carried_forward_from_run_step_id": prior_rs_id,
            "carried_forward_from_plan_version_id": pv_id,
            "carried_forward_from_run_id": prior_run_id,
            "carried_forward_original_started_at": now,
            "carried_forward_original_finished_at": now,
        }

        copied_rs = RunStep(
            run_step_id=new_rs_id,
            run_id=new_run_id,
            step_id=step_id,
            plan_version_id=pv_id,
            status=RunStepStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
            execution_fingerprint=copied_fp,
            warnings=[],
            errors=[],
        )

        edges: list[EvidenceEdge] = []
        all_artifacts: list[EvidenceArtifact] = []
        lineage_rows: list[dict] = []

        with store.transaction("IMMEDIATE") as conn:
            write_reused_run_step(
                conn=conn,
                copied_rs=copied_rs,
                edges=edges,
                all_artifacts=all_artifacts,
                lineage_rows=lineage_rows,
                run_branch_id=None,
            )

        # Verify the persisted row
        row = store.execute(
            "SELECT run_step_id, run_id, step_id, status, execution_fingerprint_json "
            "FROM run_steps WHERE run_step_id = ?",
            (new_rs_id,),
        ).fetchone()
        assert row is not None, "No run_step row for reused step"
        assert row["run_id"] == new_run_id
        assert row["step_id"] == step_id
        assert row["status"] == "succeeded"

        fp = json.loads(row["execution_fingerprint_json"])
        assert fp.get("cardre_step_carried_forward") is True, (
            f"Missing cardre_step_carried_forward in fingerprint: {fp}"
        )
        assert fp.get("carried_forward_from_run_step_id") == prior_rs_id, (
            f"Missing or wrong carried_forward_from_run_step_id in fingerprint: {fp}"
        )
