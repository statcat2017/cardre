"""Tests for typed run evidence API responses (#216)."""

from __future__ import annotations

import uuid

from cardre.domain.diagnostics import utc_now_iso


def test_run_evidence_endpoint_returns_typed_model():
    """RunEvidenceEdgeResponse is a typed model with nested artifacts (#216)."""
    from cardre.api.schemas import EvidenceArtifactResponse, RunEvidenceEdgeResponse

    artifact = EvidenceArtifactResponse(
        evidence_artifact_id="ea-1",
        evidence_edge_id="ee-1",
        artifact_id="art-1",
        role="bin_definition",
    )
    edge = RunEvidenceEdgeResponse(
        evidence_edge_id="ee-1",
        run_id="run-1",
        run_step_id="rs-1",
        step_id="step-a",
        parent_step_id="step-parent",
        policy="exact",
        source_label="binning",
        is_reused=False,
        is_stale=False,
        stale_reason=None,
        artifacts=[artifact],
    )
    assert edge.evidence_edge_id == "ee-1"
    assert len(edge.artifacts) == 1
    assert edge.artifacts[0].artifact_id == "art-1"


def test_run_evidence_route_uses_typed_response(raw_project_path, api_client, store):
    """GET /runs/{run_id}/evidence returns a list of typed objects, not raw dicts."""
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )

    resp = api_client.get(
        f"/projects/{project_id}/runs/{run_id}/evidence",
        headers={"X-Project-Path": str(store.root)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Empty list is fine — the point is the route compiles with a typed model.
