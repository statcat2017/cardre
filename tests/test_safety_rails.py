"""Phase 0 safety-rail smoke tests.

These tests verify API contract consistency between the sidecar backend
routes and the frontend client. They detect broken route references,
missing URL path segments, and SQL schema/status drift.

Every assertion reflects CURRENT behaviour — even when that behaviour
is buggy. When the underlying issue is fixed these tests will start
failing (canary), at which point they should be updated.
"""

from __future__ import annotations

import pytest

from cardre.store import ProjectStore

pytest_plugins = []
pytestmark = [pytest.mark.regression, pytest.mark.usefixtures("_isolated_registry")]


# ---------------------------------------------------------------------------
# Test 1 — Manual Binning Preview Route Contract
# ---------------------------------------------------------------------------

class TestManualBinningPreviewRouteContract:
    """The frontend client calls /plans/{planId}/steps/manual-binning/preview
    (missing the {step_id} segment).  The backend route is
    /plans/{plan_id}/steps/{step_id}/manual-binning/preview.

    This test verifies the broken frontend route actually 404s and the
    correct route resolves to a business-logic response.
    """

    def test_missing_step_id_returns_404(self, client, tmp_path):
        proj_path = tmp_path / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Route Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        pv_id = store.get_latest_plan_version_id(plan_id)

        # Frontend route — missing {step_id}
        frontend_url = f"/plans/{plan_id}/steps/manual-binning/preview"
        resp = client.post(frontend_url, json={
            "project_id": pid,
            "plan_version_id": pv_id,
            "overrides": [],
        })
        assert resp.status_code == 404, (
            f"Expected 404 for frontend route {frontend_url!r}, got {resp.status_code}"
        )

    def test_correct_route_reaches_handler(self, client, tmp_path):
        proj_path = tmp_path / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Route Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        pv_id = store.get_latest_plan_version_id(plan_id)

        # Correct route — step_id="manual-binning" appears twice (step_id + path literal)
        correct_url = f"/plans/{plan_id}/steps/manual-binning/manual-binning/preview"
        resp = client.post(correct_url, json={
            "project_id": pid,
            "plan_version_id": pv_id,
            "overrides": [],
        })
        assert resp.status_code in (200, 400), (
            f"Expected 200 or 400 (business-logic response) for correct route "
            f"{correct_url!r}, got {resp.status_code}: {resp.json()}"
        )


# ---------------------------------------------------------------------------
# Test 2 — Report Serve URL Contract
# ---------------------------------------------------------------------------

class TestReportServeURLContract:
    """The frontend builds {baseUrl}/reports/serve?path=... but the backend
    route is /projects/{project_id}/reports/serve.  The frontend is
    missing the projects/{project_id} prefix.
    """

    def test_missing_project_id_returns_404(self, client, tmp_path):
        proj_path = tmp_path / "test.cardre"
        client.post("/projects", json={"path": str(proj_path), "name": "Report Test"})

        # Frontend route — missing projects/{project_id} prefix
        resp = client.get("/reports/serve?path=test.html")
        assert resp.status_code == 404, (
            f"Expected 404 for frontend route /reports/serve, got {resp.status_code}"
        )

    def test_correct_route_resolves_to_handler(self, client, tmp_path):
        proj_path = tmp_path / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Report Test"}).json()
        pid = proj["project_id"]

        # Correct route with project_id prefix
        resp = client.get(f"/projects/{pid}/reports/serve?path=test.html")
        # The route resolves to the handler (project found in registry).
        # The handler returns 404 because the file doesn't exist, but
        # the response body differs from a raw routing 404.
        data = resp.json()
        assert resp.status_code == 404, (
            f"Correct route should reach the handler (which returns 404 for missing file). "
            f"Status: {resp.status_code}, body: {data}"
        )
        # Routing 404 has {"detail": "Not Found"}.
        # Handler 404 has {"detail": {"code": "FILE_NOT_FOUND", ...}}.
        assert data["detail"]["code"] == "FILE_NOT_FOUND", (
            f"Expected FILE_NOT_FOUND from handler, not routing 404. Body: {data}"
        )


# ---------------------------------------------------------------------------
# Test 3 — Method Summary Schema / Status Drift
# ---------------------------------------------------------------------------

class TestMethodSummarySchemaDrift:
    """The method_summary endpoint had three bugs:

    1. It referenced ``store.db_path`` but ``ProjectStore`` does not
       expose a ``db_path`` attribute (the path is a local variable in
       ``_connect()``).  This caused an **AttributeError** → 500 before
       the SQL even runs.  Fixed by using ``store.get_sqlite_path()``.

    2. The raw SQL referenced ``rs.artifact_ids`` (does not exist —
       schema uses ``output_artifact_ids_json``) and filtered by
       ``rs.status = 'success'`` (actual status is ``'succeeded'``).

    3. The model-ranking endpoint also referenced ``store.db_path`` and
       used the wrong column name ``snapshot_id`` instead of
       ``comparison_snapshot_id``.

    All three bugs are now fixed.  The endpoint should return 200.
    """

    @pytest.fixture
    def sample_german_credit(self, tmp_path):
        p = tmp_path / "german.data"
        lines = [
            "A11 6 A34 A43 1169 A65 A75 4 A93 A101 4 A121 67 A143 A152 2 A173 1 A192 A201 1",
            "A12 24 A32 A43 5951 A61 A73 2 A92 A101 4 A121 22 A142 A152 2 A173 1 A191 A201 2",
        ]
        p.write_text("\n".join(lines))
        return p

    def test_method_summary_endpoint_200s_with_expected_fields(self, client, tmp_path, sample_german_credit):
        proj_path = tmp_path / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Schema Drift Test"}).json()
        pid = proj["project_id"]

        # Import dataset so the Proof Pathway can run
        client.post("/datasets/import", json={
            "project_id": pid,
            "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)

        # Find the Proof Pathway (small — ~4 steps, runs quickly)
        plans = store.get_plans_for_project(pid)
        proof_plans = [p for p in plans if p["name"] == "Proof Pathway"]
        assert len(proof_plans) == 1, "Proof Pathway must be discoverable"
        proof_plan_id = proof_plans[0]["plan_id"]
        proof_pv_id = store.get_latest_plan_version_id(proof_plan_id)

        # Run the Proof Pathway
        run_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": proof_pv_id,
        })
        assert run_resp.status_code == 201
        assert run_resp.json()["status"] == "succeeded", (
            f"Proof Pathway run failed: {run_resp.json()}"
        )

        # Migrate to create a baseline branch
        mig_resp = client.post("/migrations/baseline", json={"project_id": pid})
        assert mig_resp.status_code == 200, (
            f"Baseline migration failed: {mig_resp.json()}"
        )

        # Grab the first branch ID for the Proof Pathway
        branches_resp = client.get(f"/projects/{pid}/branches?plan_id={proof_plan_id}")
        assert branches_resp.status_code == 200
        branches = branches_resp.json()["branches"]
        assert len(branches) >= 1, f"No branches found for Proof Pathway: {branches_resp.json()}"
        branch_id = branches[0]["branch_id"]

        # Call the method-summary endpoint.
        # After bug fixes (correct attribute, column name, status value),
        # the endpoint should return 200 with expected fields.
        summary_resp = client.get(
            f"/branches/{branch_id}/method-summary?project_id={pid}"
        )
        assert summary_resp.status_code == 200, (
            f"method-summary should return 200 after bug fixes. "
            f"Got {summary_resp.status_code}: {summary_resp.text}"
        )

        data = summary_resp.json()
        assert data["branch_id"] == branch_id
        assert "model_family" in data
        assert "feature_strategy" in data
        assert "feature_count" in data
        assert "interpretability_level" in data
        assert "champion_eligibility" in data
        assert "limitations" in data
        assert "warnings" in data
        assert "evidence_readiness" in data
