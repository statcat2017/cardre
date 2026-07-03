"""Manual-binning API route tests."""

from __future__ import annotations

import json
import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_and_store(store):
    """Create a project in the store and return (project_id, store, root)."""
    from cardre.domain.diagnostics import utc_now_iso

    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", now, "0.2.0"),
    )
    return project_id, store, store.root


@pytest.fixture
def plan_with_mb_step(project_and_store):
    """Create a plan with a manual-binning step and return IDs."""
    project_id, store, root = project_and_store
    now = "2025-01-01T00:00:00"

    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )

    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )

    mb_step_id = "manual-binning"
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mb_step_id, pv_id, "cardre.manual_binning", "1", "refinement",
         json.dumps({"overrides": []}), "abc", "", 0, mb_step_id),
    )

    return project_id, store, root, plan_id, pv_id, mb_step_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestManualBinningReviews:
    def test_list_reviews_empty(self, api_client, plan_with_mb_step):
        project_id, store, root, plan_id, pv_id, mb_step_id = plan_with_mb_step
        resp = api_client.get(
            f"/projects/{project_id}/manual-binning/reviews",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_review_not_found(self, api_client, plan_with_mb_step):
        project_id, store, root, plan_id, pv_id, mb_step_id = plan_with_mb_step
        resp = api_client.get(
            f"/projects/{project_id}/manual-binning/reviews/nonexistent",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404

    def test_edit_review_round_trip(self, api_client, plan_with_mb_step):
        """POST /edit creates a draft, GET /reviews/{id} reads it back."""
        project_id, store, root, plan_id, pv_id, mb_step_id = plan_with_mb_step

        edit_resp = api_client.post(
            f"/projects/{project_id}/manual-binning/edit",
            headers={"X-Project-Path": str(root)},
            json={
                "plan_version_id": pv_id,
                "step_id": mb_step_id,
                "overrides": [{"variable": "income", "action": "merge_bins"}],
                "reviewer_notes": "Test edit",
                "status": "pending",
                "affected_downstream_step_ids": [],
            },
        )
        assert edit_resp.status_code == 200, f"Edit failed: {edit_resp.text}"
        edit_data = edit_resp.json()
        assert "new_plan_version_id" in edit_data
        assert "review_id" in edit_data

        review_resp = api_client.get(
            f"/projects/{project_id}/manual-binning/reviews/{edit_data['review_id']}",
            headers={"X-Project-Path": str(root)},
        )
        assert review_resp.status_code == 200
        review_data = review_resp.json()
        assert review_data["review_id"] == edit_data["review_id"]
        assert review_data["plan_version_id"] == edit_data["new_plan_version_id"]
        assert review_data["status"] == "pending"
        assert review_data["reviewer_notes"] == "Test edit"

    def test_patch_review(self, api_client, plan_with_mb_step):
        """PATCH updates review status."""
        project_id, store, root, plan_id, pv_id, mb_step_id = plan_with_mb_step

        edit_resp = api_client.post(
            f"/projects/{project_id}/manual-binning/edit",
            headers={"X-Project-Path": str(root)},
            json={
                "plan_version_id": pv_id,
                "step_id": mb_step_id,
                "overrides": [],
                "status": "pending",
            },
        )
        review_id = edit_resp.json()["review_id"]

        patch_resp = api_client.patch(
            f"/projects/{project_id}/manual-binning/reviews/{review_id}",
            headers={"X-Project-Path": str(root)},
            json={"status": "approved", "reviewer_notes": "Looks good."},
        )
        assert patch_resp.status_code == 200
        patch_data = patch_resp.json()
        assert patch_data["status"] == "approved"
        assert patch_data["reviewer_notes"] == "Looks good."

    def test_preview_endpoint(self, api_client, plan_with_mb_step):
        """POST /preview computes WOE/IV from variable data."""
        project_id, store, root, plan_id, pv_id, mb_step_id = plan_with_mb_step

        resp = api_client.post(
            f"/projects/{project_id}/manual-binning/preview",
            headers={"X-Project-Path": str(root)},
            json={
                "variable_data": {
                    "variable": "income",
                    "bins": [
                        {"bin_id": "b1", "label": "Low", "good_count": 200, "bad_count": 50, "row_count": 250},
                        {"bin_id": "b2", "label": "High", "good_count": 50, "bad_count": 200, "row_count": 250},
                    ],
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "woe_by_bin" in data
        assert "iv" in data
        assert "event_rate_by_bin" in data
        assert len(data["woe_by_bin"]) == 2
        assert data["iv"] > 0


# ---------------------------------------------------------------------------
# Full review lifecycle test (Batch C)
# ---------------------------------------------------------------------------


def _seed_store_with_evidence(store, project_id):
    """Seed a store with a committed plan (fine-classing → manual-binning → apply-woe)
    and a succeeded run with evidence.

    Mirrors conftest.store_with_evidence but operates on an existing store.
    Returns (plan_id, base_pv_id, mb_step_id, downstream_step_id).
    """
    now = utc_now_iso()

    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )

    # Committed base plan version
    base_pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (base_pv_id, plan_id, now, "Base version"),
    )

    # Steps: fine-classing -> manual-binning -> apply-woe
    binning_step_id = "fine-classing"
    mb_step_id = "manual-binning"
    downstream_step_id = "apply-woe"

    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (binning_step_id, base_pv_id, "cardre.fine_classing", "1", "fit",
         json.dumps({"max_bins": 20}), "abc123", "", 0, binning_step_id),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mb_step_id, base_pv_id, "cardre.manual_binning", "1", "refinement",
         json.dumps({"overrides": []}), "def456", "", 1, mb_step_id),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (downstream_step_id, base_pv_id, "cardre.apply_woe_mapping", "1", "transform",
         json.dumps({}), "ghi789", "", 2, downstream_step_id),
    )

    # Edges
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (base_pv_id, binning_step_id, mb_step_id, 0),
    )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (base_pv_id, mb_step_id, downstream_step_id, 0),
    )

    # Run
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, base_pv_id, now, now, now),
    )

    # Run steps
    rs_binning = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (rs_binning, run_id, binning_step_id, base_pv_id, now, now),
    )
    rs_mb = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (rs_mb, run_id, mb_step_id, base_pv_id, now, now),
    )
    rs_downstream = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
        (rs_downstream, run_id, downstream_step_id, base_pv_id, now, now),
    )

    # Evidence edges
    ee_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
        " stale_reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
        (ee_id, run_id, rs_mb, base_pv_id, mb_step_id, binning_step_id,
         run_id, rs_binning, "exact", "binning", now),
    )

    # Artifact (for FK constraint)
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("art-bin-001", "bin_definition", "bin_definition", "/tmp/artifacts/bin.json",
         "abc123", "def456", "application/json", now),
    )

    # Evidence artifacts
    ea_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ea_id, ee_id, "art-bin-001", "bin_definition", now),
    )

    return plan_id, base_pv_id, mb_step_id, downstream_step_id


class TestManualBinningReviewLifecycle:
    """Full manual-binning review lifecycle driven through the API."""

    def test_manual_binning_review_lifecycle(self, api_client, project_and_store):
        project_id, store, root = project_and_store
        plan_id, base_pv_id, mb_step_id, ds_step_id = _seed_store_with_evidence(
            store, project_id,
        )

        # 1. POST /edit — apply a bin override edit
        edit_resp = api_client.post(
            f"/projects/{project_id}/manual-binning/edit",
            headers={"X-Project-Path": str(root)},
            json={
                "plan_version_id": base_pv_id,
                "step_id": mb_step_id,
                "overrides": [{"variable": "income", "action": "merge_bins", "reason": "test"}],
                "reviewer_notes": "Merged low-frequency bins.",
                "status": "pending",
                "affected_downstream_step_ids": [ds_step_id],
            },
        )
        assert edit_resp.status_code == 200, f"Edit failed: {edit_resp.text}"
        edit_data = edit_resp.json()
        draft_pv_id = edit_data["new_plan_version_id"]
        review_id = edit_data["review_id"]

        # 2. Assert a draft plan_version exists and is NOT committed
        pv_rows = store.execute(
            "SELECT * FROM plan_versions WHERE plan_version_id = ?",
            (draft_pv_id,),
        ).fetchall()
        assert len(pv_rows) == 1
        draft = dict(pv_rows[0])
        assert draft["is_committed"] == 0, "Draft should not be committed"
        assert draft["plan_id"] == plan_id

        # 3. Assert a manual_binning_reviews row exists pointing at the draft
        review_rows = store.execute(
            "SELECT * FROM manual_binning_reviews WHERE review_id = ?",
            (review_id,),
        ).fetchall()
        assert len(review_rows) == 1
        review = dict(review_rows[0])
        assert review["plan_version_id"] == draft_pv_id

        # 4. Assert affected_downstream_step_ids_json includes "apply-woe"
        downstream = json.loads(review["affected_downstream_step_ids_json"])
        assert ds_step_id in downstream, f"Expected {ds_step_id!r} in {downstream}"

        # 5. GET staleness on the draft plan version — status is "stale" or "missing"
        stale_resp = api_client.get(
            f"/projects/{project_id}/steps/{ds_step_id}/evidence",
            headers={"X-Project-Path": str(root)},
            params={"plan_version_id": draft_pv_id},
        )
        assert stale_resp.status_code == 200, f"Staleness failed: {stale_resp.text}"
        stale_data = stale_resp.json()
        assert stale_data["step_id"] == ds_step_id
        assert stale_data["status"] in ("missing", "stale"), (
            f"Expected 'missing' or 'stale', got {stale_data['status']!r}"
        )

        # 6. PATCH the review to "approved"
        patch_resp = api_client.patch(
            f"/projects/{project_id}/manual-binning/reviews/{review_id}",
            headers={"X-Project-Path": str(root)},
            json={"status": "approved"},
        )
        assert patch_resp.status_code == 200, f"Patch failed: {patch_resp.text}"
        patch_data = patch_resp.json()
        assert patch_data["status"] == "approved"
        assert patch_data["review_id"] == review_id

        # 7. POST /commit — commit the draft plan version
        commit_resp = api_client.post(
            f"/projects/{project_id}/plan-versions/{draft_pv_id}/commit",
            headers={"X-Project-Path": str(root)},
        )
        assert commit_resp.status_code == 200, f"Commit failed: {commit_resp.text}"
        commit_data = commit_resp.json()
        assert commit_data["plan_version_id"] == draft_pv_id
        assert commit_data["is_committed"] is True

        # 8. Re-run staleness on the now-committed version — still "stale" or "missing"
        stale2_resp = api_client.get(
            f"/projects/{project_id}/steps/{ds_step_id}/evidence",
            headers={"X-Project-Path": str(root)},
            params={"plan_version_id": draft_pv_id},
        )
        assert stale2_resp.status_code == 200
        stale2_data = stale2_resp.json()
        assert stale2_data["status"] in ("missing", "stale"), (
            f"Expected 'missing' or 'stale', got {stale2_data['status']!r}"
        )
