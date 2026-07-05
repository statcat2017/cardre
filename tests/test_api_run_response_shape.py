"""Characterization tests that pin the exact JSON shape of run/step/evidence responses.

These tests assert the full field set and values returned by each endpoint,
serving as a safety net for the mapper extraction refactor in Slice 1.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from cardre.domain.diagnostics import utc_now_iso

# ---------------------------------------------------------------------------
# Local fixture — mirrors the one in test_api_runs.py but self-contained so
# this test file can be run independently.
# ---------------------------------------------------------------------------


@pytest.fixture
def project_with_run(store):
    """Create a project, plan, plan version, and run (no steps / evidence)."""
    from cardre.config import CardreConfig
    from cardre.services.project_resolver import ProjectResolver

    project_id = str(uuid.uuid4())
    now = utc_now_iso()
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
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )
    resolver = ProjectResolver(CardreConfig.from_env().registry_path)
    resolver.register_project(project_id, store.root)
    return project_id, plan_id, pv_id, run_id, store, store.root


# ---------------------------------------------------------------------------
# RunResponse shape
# ---------------------------------------------------------------------------


class TestRunResponseShape:
    """Pin the exact field set and values of RunResponse."""

    def test_run_response_from_get_run(self, api_client, project_with_run):
        project_id, _, _, run_id, _, _ = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()

        expected_fields = {
            "run_id",
            "plan_version_id",
            "status",
            "started_at",
            "finished_at",
            "step_count",
            "branch_id",
            "executed_step_ids",
            "diagnostics",
            "latest_error",
            "heartbeat_at",
            "is_stale",
        }
        assert set(data.keys()) == expected_fields, f"Unexpected fields: {set(data.keys()) ^ expected_fields}"

        assert data["run_id"] == run_id
        assert data["status"] == "succeeded"
        assert data["step_count"] == 0
        assert data["branch_id"] is None
        assert data["executed_step_ids"] == []
        assert data["diagnostics"] == []
        assert data["latest_error"] is None
        assert data["heartbeat_at"] is None
        assert data["is_stale"] is False

    def test_run_response_from_create_run(self, api_client, project_with_run):
        project_id, _, pv_id, _, _, _ = project_with_run
        resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": False},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        expected_fields = {
            "run_id",
            "plan_version_id",
            "status",
            "started_at",
            "finished_at",
            "step_count",
            "branch_id",
            "executed_step_ids",
            "diagnostics",
            "latest_error",
            "heartbeat_at",
            "is_stale",
        }
        assert set(data.keys()) == expected_fields, f"Unexpected fields: {set(data.keys()) ^ expected_fields}"

        assert data["plan_version_id"] == pv_id
        assert data["status"] == "succeeded"
        assert data["step_count"] == 0
        assert data["executed_step_ids"] == []
        assert data["diagnostics"] == []


# ---------------------------------------------------------------------------
# RunStepResponse shape
# ---------------------------------------------------------------------------


class TestRunStepResponseShape:
    """Pin the exact field set and values of RunStepResponse."""

    def test_run_step_response_shape(self, api_client, project_with_run):
        project_id, _, pv_id, run_id, store, _ = project_with_run

        # Insert a plan step (required FK for run_steps.step_id)
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'test', '1', 'fit', '{}', 'abc', '', 0, ?)",
            ("test-step", pv_id, "test-step"),
        )

        now = utc_now_iso()
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            ("rs-1", run_id, "test-step", pv_id, now, now),
        )

        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/steps",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

        step = data[0]
        expected_fields = {
            "run_step_id",
            "run_id",
            "step_id",
            "plan_version_id",
            "status",
            "started_at",
            "finished_at",
            "execution_fingerprint",
            "warnings",
            "errors",
        }
        assert set(step.keys()) == expected_fields, f"Unexpected fields: {set(step.keys()) ^ expected_fields}"

        assert step["run_step_id"] == "rs-1"
        assert step["run_id"] == run_id
        assert step["step_id"] == "test-step"
        assert step["plan_version_id"] == pv_id
        assert step["status"] == "succeeded"
        assert step["finished_at"] == now
        assert step["execution_fingerprint"] == {}
        assert step["warnings"] == []
        assert step["errors"] == []


# ---------------------------------------------------------------------------
# RunEvidenceEdgeResponse shape (including nested artifacts)
# ---------------------------------------------------------------------------


class TestRunEvidenceResponseShape:
    """Pin the exact field set and values of RunEvidenceEdgeResponse."""

    EVIDENCE_EDGE_FIELDS = {
        "evidence_edge_id",
        "run_id",
        "run_step_id",
        "plan_version_id",
        "step_id",
        "parent_step_id",
        "source_run_id",
        "source_run_step_id",
        "policy",
        "source_label",
        "is_reused",
        "is_stale",
        "stale_reason",
        "created_at",
        "artifacts",
    }

    ARTIFACT_FIELDS = {
        "evidence_artifact_id",
        "evidence_edge_id",
        "artifact_id",
        "role",
        "created_at",
    }

    def test_run_evidence_response_shape(self, api_client, project_with_run):
        project_id, _, pv_id, run_id, store, _ = project_with_run

        now = utc_now_iso()

        # Insert a plan step
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'test', '1', 'fit', '{}', 'abc', '', 0, ?)",
            ("step-a", pv_id, "step-a"),
        )

        # Insert a run step
        rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            (rs_id, run_id, "step-a", pv_id, now, now),
        )

        # Insert an artifact (required FK for evidence_artifacts)
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("art-001", "dataset", "input", "/tmp/art.csv", "abc", "def", "text/csv", now),
        )

        # Insert an evidence edge
        ee_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO evidence_edges "
            "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
            " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
            " stale_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
            (ee_id, run_id, rs_id, pv_id, "step-a", "",
             run_id, rs_id, "exact", "parent", now),
        )

        # Insert an evidence artifact
        ea_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ea_id, ee_id, "art-001", "input", now),
        )

        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/evidence",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

        edge = data[0]
        expected_edge_fields = {
            "evidence_edge_id",
            "run_id",
            "run_step_id",
            "plan_version_id",
            "step_id",
            "parent_step_id",
            "source_run_id",
            "source_run_step_id",
            "policy",
            "source_label",
            "is_reused",
            "is_stale",
            "stale_reason",
            "created_at",
            "artifacts",
        }
        assert set(edge.keys()) == expected_edge_fields, (
            f"Unexpected edge fields: {set(edge.keys()) ^ expected_edge_fields}"
        )

        assert edge["evidence_edge_id"] == ee_id
        assert edge["run_id"] == run_id
        assert edge["run_step_id"] == rs_id
        assert edge["plan_version_id"] == pv_id
        assert edge["step_id"] == "step-a"
        assert edge["is_reused"] is False
        assert edge["is_stale"] is False
        assert edge["stale_reason"] is None
        assert edge["created_at"] == now

        # Nested artifacts
        artifacts = edge["artifacts"]
        assert isinstance(artifacts, list)
        assert len(artifacts) == 1
        art = artifacts[0]

        expected_artifact_fields = {
            "evidence_artifact_id",
            "evidence_edge_id",
            "artifact_id",
            "role",
            "created_at",
        }
        assert set(art.keys()) == expected_artifact_fields, (
            f"Unexpected artifact fields: {set(art.keys()) ^ expected_artifact_fields}"
        )

        assert art["evidence_artifact_id"] == ea_id
        assert art["evidence_edge_id"] == ee_id
        assert art["artifact_id"] == "art-001"
        assert art["role"] == "input"
        assert art["created_at"] == now, f"Expected created_at={now!r}, got {art['created_at']!r}"

    def test_run_evidence_order_and_bulk_queries(self, api_client, project_with_run, monkeypatch):
        project_id, _, pv_id, run_id, store, root = project_with_run

        from cardre.store.db import ProjectStore

        base = datetime(2026, 7, 5, tzinfo=UTC)
        step_ids: list[str] = []
        run_step_ids: list[str] = []

        for idx in range(10):
            step_id = f"ordered-step-{idx}"
            run_step_id = f"ordered-run-step-{idx}"
            step_ids.append(step_id)
            run_step_ids.append(run_step_id)
            started_at = (base + timedelta(seconds=idx)).isoformat().replace("+00:00", "Z")
            store.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'test', '1', 'fit', '{}', ?, '', ?, ?)",
                (step_id, pv_id, f"hash-{idx}", idx, step_id),
            )
            store.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
                (run_step_id, run_id, step_id, pv_id, started_at, started_at),
            )
            if idx == 0:
                continue
            edge_id = f"ordered-edge-{idx}"
            store.execute(
                "INSERT INTO evidence_edges "
                "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
                " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
                " stale_reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
                (
                    edge_id,
                    run_id,
                    run_step_id,
                    pv_id,
                    step_id,
                    step_ids[idx - 1],
                    run_id,
                    run_step_ids[idx - 1],
                    "exact",
                    f"edge-{idx}",
                    started_at,
                ),
            )
            store.execute(
                "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"art-{idx}-z", "dataset", "zeta", f"/tmp/{idx}-z.csv", "ph-z", "lh-z", "text/csv", started_at),
            )
            store.execute(
                "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"art-{idx}-a", "dataset", "alpha", f"/tmp/{idx}-a.csv", "ph-a", "lh-a", "text/csv", started_at),
            )
            store.execute(
                "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"ea-{idx}-z", edge_id, f"art-{idx}-z", "zeta", started_at),
            )
            store.execute(
                "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"ea-{idx}-a", edge_id, f"art-{idx}-a", "alpha", started_at),
            )

        original_execute = ProjectStore.execute
        counts = {"evidence_edges": 0, "evidence_artifacts": 0}

        def counted_execute(self, sql, params=()):
            if sql.lstrip().upper().startswith("SELECT") and "FROM evidence_edges" in sql:
                counts["evidence_edges"] += 1
            if sql.lstrip().upper().startswith("SELECT") and "FROM evidence_artifacts" in sql:
                counts["evidence_artifacts"] += 1
            return original_execute(self, sql, params)

        monkeypatch.setattr(ProjectStore, "execute", counted_execute)

        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/evidence",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 9
        assert [edge["step_id"] for edge in data] == step_ids[1:]
        assert [artifact["role"] for artifact in data[0]["artifacts"]] == ["alpha", "zeta"]
        assert counts == {"evidence_edges": 1, "evidence_artifacts": 1}

    def test_evidence_order_with_same_timestamp_steps(self, api_client, project_with_run):
        """Regression: evidence order must match run-step iteration order even when
        multiple steps share the same started_at timestamp and run_step_ids are
        in non-execution (reverse) order."""
        project_id, _, pv_id, run_id, store, _ = project_with_run

        now = utc_now_iso()

        for idx in range(3):
            store.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'test', '1', 'fit', '{}', ?, '', ?, ?)",
                (f"step-{idx}", pv_id, f"hash-{idx}", idx, f"step-{idx}"),
            )

        step_info: list[tuple[str, int]] = []
        for idx in range(3):
            run_step_id = f"rs-rev-{2 - idx}"
            store.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
                (run_step_id, run_id, f"step-{idx}", pv_id, now, now),
            )
            step_info.append((run_step_id, idx))

        for run_step_id, idx in step_info:
            edge_id = f"ee-same-ts-{idx}"
            store.execute(
                "INSERT INTO evidence_edges "
                "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
                " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
                " stale_reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, '', ?, ?, 'exact', ?, 0, 0, NULL, ?)",
                (edge_id, run_id, run_step_id, pv_id, f"step-{idx}",
                 run_id, run_step_id, f"label-{idx}", now),
            )

        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/evidence",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert [e["step_id"] for e in data] == ["step-0", "step-1", "step-2"]
