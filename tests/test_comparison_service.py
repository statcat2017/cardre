"""Tests for ComparisonService (v2)."""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec
import cardre.services.comparison_service as comparison_service
from cardre.store.branch_repo import BranchRepository
from cardre.store.comparison_repo import ComparisonRepository
from cardre.store.plan_repo import PlanRepository

pytestmark = pytest.mark.unit


# =========================================================================
# _check_branch_readiness tests
# =========================================================================

class TestCheckBranchReadiness:
    def test_readiness_no_evidence_returns_missing(self, store):
        """A branch with no evidence should report missing steps."""
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "test", utc_now_iso(), "0.2.0"),
        )
        plan_repo = PlanRepository(store)
        plan_id = plan_repo.create_plan(project_id, "test-plan")
        from cardre.domain.artifacts import json_logical_hash
        steps = [
            StepSpec(step_id="import", node_type="cardre.import_dataset", node_version="1",
                     category="transform", params={}, params_hash=json_logical_hash({}),
                     parent_step_ids=[], branch_label="", position=0,
                     canonical_step_id="sample-definition"),
        ]
        pv_id = plan_repo.create_version(plan_id, steps, description="v1")

        branches_repo = BranchRepository(store)
        branch_id = branches_repo.create_branch(
            project_id, plan_id, "test-branch", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        # Create step map so the branch knows its steps
        branches_repo.create_step_map(
            branch_id, pv_id, "sample-definition", "import",
            is_shared_upstream=True, is_branch_owned=False,
        )

        missing = comparison_service._check_branch_readiness(
            store, branch_id, pv_id, ["sample-definition"],
        )
        assert len(missing) > 0
        assert missing[0]["branch_id"] == branch_id
        assert missing[0]["canonical_step_id"] == "sample-definition"


# =========================================================================
# create_comparison tests
# =========================================================================

class TestCreateComparison:
    def test_create_comparison_success(self, store):
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "test", utc_now_iso(), "0.2.0"),
        )
        plan_repo = PlanRepository(store)
        plan_id = plan_repo.create_plan(project_id, "test-plan")
        pv_id = plan_repo.create_version(plan_id, [], description="v1")

        branches_repo = BranchRepository(store)
        baseline_id = branches_repo.create_branch(
            project_id, plan_id, "baseline", "baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Baseline.",
        )
        challenger_id = branches_repo.create_branch(
            project_id, plan_id, "challenger", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Challenger.",
        )

        result = comparison_service.create_comparison(
            store,
            project_id=project_id,
            plan_id=plan_id,
            baseline_branch_id=baseline_id,
            challenger_branch_ids=[challenger_id],
            created_reason="Test comparison.",
        )

        assert result["comparison_id"] is not None
        assert result["baseline_branch_id"] == baseline_id
        assert result["challenger_branch_ids"] == [challenger_id]

        # Verify the comparison was persisted
        comparison_repo = ComparisonRepository(store)
        saved = comparison_repo.get_comparison(result["comparison_id"])
        assert saved is not None
        assert saved["plan_id"] == plan_id

    def test_create_comparison_missing_baseline(self, store):
        with pytest.raises(ValueError, match="BASELINE_BRANCH_NOT_FOUND"):
            comparison_service.create_comparison(
                store,
                project_id="p1",
                plan_id="pl1",
                baseline_branch_id="nonexistent",
                challenger_branch_ids=[],
            )

    def test_create_comparison_missing_challenger(self, store):
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "test", utc_now_iso(), "0.2.0"),
        )
        plan_repo = PlanRepository(store)
        plan_id = plan_repo.create_plan(project_id, "test-plan")
        pv_id = plan_repo.create_version(plan_id, [], description="v1")
        branches_repo = BranchRepository(store)
        baseline_id = branches_repo.create_branch(
            project_id, plan_id, "baseline", "baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Baseline.",
        )
        with pytest.raises(ValueError, match="CHALLENGER_BRANCH_NOT_FOUND"):
            comparison_service.create_comparison(
                store,
                project_id=project_id,
                plan_id=plan_id,
                baseline_branch_id=baseline_id,
                challenger_branch_ids=["nonexistent"],
            )


# =========================================================================
# refresh_comparison tests
# =========================================================================

class TestRefreshComparison:
    def test_refresh_missing_comparison(self, store):
        with pytest.raises(ValueError, match="COMPARISON_NOT_FOUND"):
            comparison_service.refresh_comparison(store, "nonexistent")

    def test_refresh_not_ready(self, store):
        """A comparison without evidence should report not ready."""
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "test", utc_now_iso(), "0.2.0"),
        )
        plan_repo = PlanRepository(store)
        plan_id = plan_repo.create_plan(project_id, "test-plan")
        pv_id = plan_repo.create_version(plan_id, [], description="v1")
        branches_repo = BranchRepository(store)
        baseline_id = branches_repo.create_branch(
            project_id, plan_id, "baseline", "baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Baseline.",
        )
        comparison_repo = ComparisonRepository(store)
        comparison_id = comparison_repo.create_comparison(
            project_id=project_id,
            plan_id=plan_id,
            baseline_branch_id=baseline_id,
        )

        result = comparison_service.refresh_comparison(store, comparison_id)
        assert result["ready"] is False
        assert result["blocked_reason"] is not None
        assert len(result["missing_or_stale"]) > 0


# =========================================================================
# _build_comparison_content tests
# =========================================================================

class TestBuildComparisonContent:
    def test_build_comparison_content_validation_materialization(self, monkeypatch):
        """Test that _materialize_evidence correctly converts dataclasses."""
        from cardre._evidence.models import ValidationMetrics as VM, RoleMetrics as RM

        vm = VM(
            metrics_by_role={
                "train": RM(row_count=100, auc=0.81, gini=0.62, ks=0.41),
                "test": RM(row_count=40, auc=0.79, gini=0.58, ks=0.37),
            },
            psi={"score": 0.1},
            target={},
            gates=[],
            warnings=[],
            source_artifact_id="test-artifact",
        )
        materialized = comparison_service._materialize_evidence(vm)
        assert isinstance(materialized, dict)
        assert materialized["metrics_by_role"]["train"]["auc"] == 0.81
        assert materialized["metrics_by_role"]["train"]["gini"] == 0.62

        roles = comparison_service._validation_roles(materialized)
        assert roles["train"]["auc"] == 0.81
        assert roles["test"]["ks"] == 0.37
