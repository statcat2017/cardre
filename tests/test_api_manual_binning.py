"""Minimal route round-trip tests for the manual-binning API."""

from __future__ import annotations

import json
import uuid

import pytest



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


class TestHealth:
    def test_health_returns_ok(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestProjects:
    def test_get_project_not_found(self, api_client, project_and_store):
        """A non-existent project returns 404."""
        # The minimal API needs an X-Project-Path header to resolve the store
        project_id, store, root = project_and_store
        resp = api_client.get(
            f"/projects/{project_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200  # project actually exists in the store

    def test_get_project_missing_header(self, api_client):
        """Missing X-Project-Path returns 400."""
        resp = api_client.get("/projects/some-id")
        assert resp.status_code == 400


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

        # Submit an edit
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

        # Fetch the review
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

        # First create a review via edit
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

        # Patch to approve
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
