"""Route tests for the relocated (ungated) manual-binning review endpoints.

These endpoints moved from the governance router to the plans-scoped router and
are no longer gated by CARDRE_GOVERNANCE.
"""

from __future__ import annotations

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec


def _seed_mb_plan_and_review(container, project_id, status="pending", notes="initial"):
    steps = [
        StepSpec(step_id="automatic-binning", node_type="cardre.automatic_binning",
                 node_version="1", category="fit", params={"max_bins": 20},
                 params_hash=json_logical_hash({"max_bins": 20}),
                 parent_step_ids=[], position=0,
                 canonical_step_id="automatic-binning"),
        StepSpec(step_id="manual-binning", node_type="cardre.manual_binning",
                 node_version="1", category="refinement", params={"overrides": []},
                 params_hash=json_logical_hash({"overrides": []}),
                 parent_step_ids=["automatic-binning"], position=1,
                 canonical_step_id="manual-binning"),
    ]
    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        review = uow.manual_binning.create_review(
            plan_version_id=pv_id, step_id="manual-binning", status=status,
            reviewer_notes=notes, affected_downstream_step_ids=["apply-woe"],
        )
        uow.commit()
        return plan_id, pv_id, review.review_id


def _seed_committed_mb_plan(container, project_id):
    steps = [
        StepSpec(step_id="automatic-binning", node_type="cardre.automatic_binning",
                 node_version="1", category="fit", params={"max_bins": 20},
                 params_hash=json_logical_hash({"max_bins": 20}),
                 parent_step_ids=[], position=0,
                 canonical_step_id="automatic-binning"),
        StepSpec(step_id="manual-binning", node_type="cardre.manual_binning",
                 node_version="1", category="refinement", params={"overrides": []},
                 params_hash=json_logical_hash({"overrides": []}),
                 parent_step_ids=["automatic-binning"], position=1,
                 canonical_step_id="manual-binning"),
    ]
    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()
        return plan_id, pv_id


class TestManualBinningReviewRoutes:
    def test_list_and_get_review(self, app_env, tmp_path):
        client, container = app_env
        pid, _ = _provision(container, tmp_path)
        _, _, rid = _seed_mb_plan_and_review(container, pid)

        resp = client.get(f"/projects/{pid}/manual-binning-reviews")
        assert resp.status_code == 200, resp.text
        assert any(r["review_id"] == rid for r in resp.json())

        resp2 = client.get(f"/projects/{pid}/manual-binning-reviews/{rid}")
        assert resp2.status_code == 200
        assert resp2.json()["review_id"] == rid

    def test_patch_notes_only_preserves_status(self, app_env, tmp_path):
        client, container = app_env
        pid, _ = _provision(container, tmp_path)
        _, _, rid = _seed_mb_plan_and_review(container, pid, status="pending", notes="orig")
        resp = client.patch(
            f"/projects/{pid}/manual-binning-reviews/{rid}",
            json={"reviewer_notes": "updated notes"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["reviewer_notes"] == "updated notes"
        assert data["status"] == "pending"

    def test_patch_status_only_preserves_notes(self, app_env, tmp_path):
        client, container = app_env
        pid, _ = _provision(container, tmp_path)
        _, _, rid = _seed_mb_plan_and_review(container, pid, status="pending", notes="keep me")
        resp = client.patch(
            f"/projects/{pid}/manual-binning-reviews/{rid}",
            json={"status": "approved"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "approved"
        assert data["reviewer_notes"] == "keep me"

    def test_patch_invalid_status_returns_400(self, app_env, tmp_path):
        client, container = app_env
        pid, _ = _provision(container, tmp_path)
        _, _, rid = _seed_mb_plan_and_review(container, pid)
        resp = client.patch(
            f"/projects/{pid}/manual-binning-reviews/{rid}",
            json={"status": "bogus"},
        )
        assert resp.status_code == 400

    def test_patch_nonexistent_review_returns_404(self, app_env, tmp_path):
        client, container = app_env
        pid, _ = _provision(container, tmp_path)
        resp = client.patch(
            f"/projects/{pid}/manual-binning-reviews/nonexistent",
            json={"status": "approved"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "REVIEW_NOT_FOUND"


class TestManualBinningPreviewRoute:
    def test_preview(self, app_env, tmp_path):
        client, container = app_env
        pid, _ = _provision(container, tmp_path)
        resp = client.post(
            f"/projects/{pid}/manual-binning-preview",
            json={"variable_data": {"variable": "age", "bins": []}},
        )
        assert resp.status_code == 200, resp.text
        assert "woe_by_bin" in resp.json()
        assert "iv" in resp.json()
        assert "event_rate_by_bin" in resp.json()


class TestApplyManualBinningEditRoute:
    def test_apply_edit_creates_draft_and_review(self, app_env, tmp_path):
        client, container = app_env
        pid, _ = _provision(container, tmp_path)
        _, pv_id = _seed_committed_mb_plan(container, pid)
        resp = client.post(
            f"/projects/{pid}/apply-manual-binning-edit",
            json={
                "plan_version_id": pv_id,
                "step_id": "manual-binning",
                "overrides": [{"bin_id": "b1", "reason": "business rationale"}],
                "reviewer_notes": "edits applied",
                "status": "pending",
                "affected_downstream_step_ids": ["apply-woe"],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["new_plan_version_id"]
        assert data["review_id"]
        assert data["affected_step_ids"] == ["apply-woe"]


def _provision(container, tmp_path, name="Proj"):
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / f"{name}.cardre"
    provisioner.initialize(root)
    with container.uow_factory.for_root(root) as uow:
        project_id = uow.projects.create(name)
        uow.commit()
    container.project_registry.register(project_id, root)
    return project_id, root
