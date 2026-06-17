"""Targeted unit tests for BranchService and related helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cardre.audit import StepSpec, json_logical_hash
from cardre.services import migrate_project_to_branch_model
from cardre.services.branch_service import (
    BranchService,
    _descendant_closure,
    _validate_segment_filter_rules,
    ALLOWED_BRANCH_POINTS,
)
from cardre.store import ProjectStore
from sidecar.proof_pathway import (
    PROOF_PATHWAY_STEPS_CONFIG,
    PHASE2A_PATHWAY_STEPS_CONFIG,
    _build_steps,
)

from tests.helpers import make_store


@pytest.fixture
def store():
    tmp = Path(tempfile.mkdtemp())
    s = ProjectStore(tmp / "test.cardre")
    s.initialize()
    return s


@pytest.fixture
def project_and_plan(store):
    """Create a project with a full scorecard pathway plan."""
    from sidecar.proof_pathway import register_scorecard_pathway
    project_id = store.create_project("test-proj")
    plan_id = register_scorecard_pathway(store, project_id)
    return project_id, plan_id


# =========================================================================
# _descendant_closure tests
# =========================================================================

class TestDescendantClosure:
    def test_single_step(self):
        steps = [
            StepSpec(step_id="a", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=[], branch_label="", position=0),
        ]
        assert _descendant_closure("a", steps) == {"a"}

    def test_linear_chain(self):
        steps = [
            StepSpec(step_id="a", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=[], branch_label="", position=0),
            StepSpec(step_id="b", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=["a"], branch_label="", position=1),
            StepSpec(step_id="c", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=["b"], branch_label="", position=2),
        ]
        assert _descendant_closure("a", steps) == {"a", "b", "c"}
        assert _descendant_closure("b", steps) == {"b", "c"}
        assert _descendant_closure("c", steps) == {"c"}

    def test_diamond_dag(self):
        steps = [
            StepSpec(step_id="a", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=[], branch_label="", position=0),
            StepSpec(step_id="b", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=["a"], branch_label="", position=1),
            StepSpec(step_id="c", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=["a"], branch_label="", position=2),
            StepSpec(step_id="d", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=["b", "c"], branch_label="", position=3),
        ]
        assert _descendant_closure("a", steps) == {"a", "b", "c", "d"}
        assert _descendant_closure("b", steps) == {"b", "d"}
        assert _descendant_closure("d", steps) == {"d"}

    def test_missing_step_raises(self):
        steps = [
            StepSpec(step_id="a", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=[], branch_label="", position=0),
        ]
        with pytest.raises(KeyError):
            _descendant_closure("z", steps)

    def test_disconnected_steps(self):
        steps = [
            StepSpec(step_id="a", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=[], branch_label="", position=0),
            StepSpec(step_id="b", node_type="t", node_version="1", category="t",
                     params={}, params_hash="h", parent_step_ids=[], branch_label="", position=1),
        ]
        assert _descendant_closure("a", steps) == {"a"}
        assert _descendant_closure("b", steps) == {"b"}


# =========================================================================
# Segment filter validation tests
# =========================================================================

class TestValidateSegmentFilterRules:
    @pytest.mark.parametrize("rules,expected_error", [
        ({"rules": []}, "SEGMENT_FILTER_RULES_REQUIRED"),
        ({"rules": [{"operator": "==", "value": "x", "reason": "test"}]}, "SEGMENT_FILTER_INVALID"),
        ({"rules": [{"column": "age", "value": "x", "reason": "test"}]}, "SEGMENT_FILTER_INVALID"),
        ({"rules": [{"column": "age", "operator": "~=", "value": "x", "reason": "test"}]}, "SEGMENT_FILTER_UNSUPPORTED_OPERATOR"),
        ({"rules": [{"column": "age", "operator": "==", "value": "x", "reason": ""}]}, "SEGMENT_FILTER_REASON_REQUIRED"),
        ({"rules": [{"column": "age", "operator": ">", "reason": "test"}]}, "SEGMENT_FILTER_VALUE_REQUIRED"),
    ])
    def test_rejects_invalid_rules(self, rules, expected_error):
        with pytest.raises(ValueError, match=expected_error):
            _validate_segment_filter_rules(rules)

    @pytest.mark.parametrize("rules", [
        {"rules": [{"column": "age", "operator": ">", "value": 18, "reason": "Adult population"}]},
        {"rules": [{"column": "age", "operator": "is_null", "reason": "Missing data"}]},
        {"rules": [{"column": "age", "operator": "is_not_null", "reason": "Present data"}]},
    ])
    def test_accepts_valid_rules(self, rules):
        _validate_segment_filter_rules(rules)


# =========================================================================
# BranchService integration tests
# =========================================================================

class TestBranchServiceCreateBranch:
    def _find_non_segment_branch_point(self, steps):
        """Find a branch point that is not segment_challenger (avoids needing segment_filter_spec)."""
        for s in steps:
            cid = s.canonical_step_id
            if cid in ALLOWED_BRANCH_POINTS and ALLOWED_BRANCH_POINTS[cid] != "segment_challenger":
                return cid
        return None

    def test_create_branch_success(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        steps = store.get_plan_version_steps(pv_id)
        branch_point_id = self._find_non_segment_branch_point(steps)
        if branch_point_id is None:
            pytest.skip("No non-segment branch point in default pathway")

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Test Challenger",
            branch_type=ALLOWED_BRANCH_POINTS[branch_point_id],
            branch_point_step_id=branch_point_id,
            base_branch_id=None,
            base_plan_version_id=pv_id,
            created_reason="Integration test.",
        )
        assert "branch_id" in result
        assert result["name"] == "Test Challenger"
        assert result["branch_type"] == ALLOWED_BRANCH_POINTS[branch_point_id]
        assert "new_plan_version_id" in result
        assert result["status"] == "not_run"

        # Verify the branch was persisted
        branch = store.get_branch(result["branch_id"])
        assert branch is not None
        assert branch["name"] == "Test Challenger"

    def test_create_branch_from_baseline(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)

        # Create a baseline branch first
        baseline_branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Baseline.",
        )

        steps = store.get_plan_version_steps(pv_id)
        branch_point_id = self._find_non_segment_branch_point(steps)
        if branch_point_id is None:
            pytest.skip("No non-segment branch point in default pathway")

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Challenger from Baseline",
            branch_type=ALLOWED_BRANCH_POINTS[branch_point_id],
            branch_point_step_id=branch_point_id,
            base_branch_id=baseline_branch_id,
            base_plan_version_id=pv_id,
            created_reason="Branching from baseline.",
        )
        assert "branch_id" in result
        assert result["name"] == "Challenger from Baseline"
        assert result["branch_id"] != baseline_branch_id

    def test_create_segment_challenger(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        steps = store.get_plan_version_steps(pv_id)

        branch_point_id = None
        for s in steps:
            if s.canonical_step_id == "sample-definition":
                branch_point_id = s.canonical_step_id
                break
        if branch_point_id is None:
            pytest.skip("sample-definition not in default pathway")

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Segment Challenger",
            branch_type="segment_challenger",
            branch_point_step_id=branch_point_id,
            base_plan_version_id=pv_id,
            created_reason="Segment filter test.",
            segment_filter_spec={
                "rules": [
                    {"column": "age", "operator": ">=", "value": 18, "reason": "Adult only"},
                ]
            },
        )
        assert result["name"] == "Segment Challenger"

    def test_create_branch_raises_on_invalid_point(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        svc = BranchService(store)
        with pytest.raises(ValueError, match="BRANCH_POINT_NOT_ALLOWED"):
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="Bad Branch",
                branch_type="model_challenger",
                branch_point_step_id="nonexistent",
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )

    def test_create_branch_raises_on_type_mismatch(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        steps = store.get_plan_version_steps(pv_id)
        branch_point_id = None
        for s in steps:
            if s.canonical_step_id in ALLOWED_BRANCH_POINTS:
                branch_point_id = s.canonical_step_id
                break
        if branch_point_id is None:
            pytest.skip("No allowed branch point in default pathway")

        expected_type = ALLOWED_BRANCH_POINTS[branch_point_id]
        wrong_type = "segment_challenger" if expected_type != "segment_challenger" else "model_challenger"

        svc = BranchService(store)
        with pytest.raises(ValueError, match="BRANCH_TYPE_MISMATCH"):
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="Type Mismatch",
                branch_type=wrong_type,
                branch_point_step_id=branch_point_id,
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )

    def test_create_branch_raises_on_empty_name(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        svc = BranchService(store)
        with pytest.raises(ValueError, match="BRANCH_NAME_REQUIRED"):
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )

    def test_create_branch_raises_on_empty_reason(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        svc = BranchService(store)
        with pytest.raises(ValueError, match="BRANCH_REASON_REQUIRED"):
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="No Reason",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_plan_version_id=pv_id,
                created_reason="",
            )

    def test_create_branch_raises_on_segment_filter_missing(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        svc = BranchService(store)
        with pytest.raises(ValueError, match="SEGMENT_FILTER_REQUIRED"):
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="Segment Challenger",
                branch_type="segment_challenger",
                branch_point_step_id="sample-definition",
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
                segment_filter_spec=None,
            )

    def test_create_branch_raises_on_plan_not_found(self, store, project_and_plan):
        project_id, _ = project_and_plan
        svc = BranchService(store)
        with pytest.raises(ValueError, match="PLAN_NOT_FOUND"):
            svc.create_branch(
                project_id=project_id,
                plan_id="nonexistent-plan-id",
                name="No Plan",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_plan_version_id="pv-nonexistent",
                created_reason="Should fail.",
            )

    def test_create_branch_raises_on_plan_project_mismatch(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        other_project_id = store.create_project("other-proj")
        # Create a plan under the other project
        other_plan_id = store.create_plan(other_project_id, "Other Plan")
        pv_id = store.create_plan_version(other_plan_id, [])

        svc = BranchService(store)
        with pytest.raises(ValueError, match="PLAN_PROJECT_MISMATCH"):
            svc.create_branch(
                project_id=project_id,
                plan_id=other_plan_id,
                name="Wrong Project",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )


# ======================================================================
# Baseline migration service (from Phase 4)
# ======================================================================


class BaselineMigrationTests:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.store, self.tmp = make_store()

    def test_migrate_creates_baseline_branch(self):
        project_id = self.store.create_project("test")
        plan_id = self.store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG)
        pv_id = self.store.create_plan_version(plan_id, steps, description="v1")

        result = migrate_project_to_branch_model(self.store, project_id)

        assert result["branches_created"] == 1
        assert result["plan_versions_mapped"] == 1
        assert result["steps_mapped"] == len(steps)

        branches = self.store.list_branches(project_id)
        assert len(branches) == 1
        assert branches[0]["branch_type"] == "baseline"
        assert branches[0]["name"] == "Baseline"

    def test_migrate_creates_step_map_for_all_versions(self):
        project_id = self.store.create_project("test")
        plan_id = self.store.create_plan(project_id, "Scorecard Pathway")

        v1_steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        pv1_id = self.store.create_plan_version(plan_id, v1_steps, description="v1")

        v2_steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:4])
        pv2_id = self.store.create_plan_version(plan_id, v2_steps, description="v2")

        result = migrate_project_to_branch_model(self.store, project_id)

        assert result["plan_versions_mapped"] == 2
        assert result["steps_mapped"] == len(v1_steps) + len(v2_steps)

        branches = self.store.list_branches(project_id)
        branch_id = branches[0]["branch_id"]

        v1_map = self.store.get_branch_step_map(branch_id, pv1_id)
        assert len(v1_map) == len(v1_steps)

        v2_map = self.store.get_branch_step_map(branch_id, pv2_id)
        assert len(v2_map) == len(v2_steps)

    def test_migrate_idempotent(self):
        project_id = self.store.create_project("test")
        plan_id = self.store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        self.store.create_plan_version(plan_id, steps, description="v1")

        result1 = migrate_project_to_branch_model(self.store, project_id)
        assert result1["branches_created"] == 1

        result2 = migrate_project_to_branch_model(self.store, project_id)
        assert result2["branches_created"] == 0

        branches = self.store.list_branches(project_id)
        assert len(branches) == 1

    def test_migrate_excludes_hidden_import_plan(self):
        project_id = self.store.create_project("test")
        self.store.create_plan_version(
            self.store.create_plan(project_id, "__import__"),
            _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:1]),
            description="import",
        )
        plan_id = self.store.create_plan(project_id, "Scorecard Pathway")
        self.store.create_plan_version(plan_id, _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2]), description="v1")

        result = migrate_project_to_branch_model(self.store, project_id)
        assert result["branches_created"] == 1
        assert result["plan_versions_mapped"] == 1

    def test_migrate_does_not_rewrite_run_history(self):
        from cardre.executor import PlanExecutor
        from cardre.registry import NodeRegistry

        project_id = self.store.create_project("test")
        plan_id = self.store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        pv_id = self.store.create_plan_version(plan_id, steps, description="v1")

        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        run_id = executor.run_plan_version(self.store, pv_id)
        original_run = self.store.get_run(run_id)
        original_run_steps = self.store.get_run_steps(run_id)

        migrate_project_to_branch_model(self.store, project_id)

        after_run = self.store.get_run(run_id)
        assert after_run is not None
        assert after_run["status"] == original_run["status"]
        assert after_run["started_at"] == original_run["started_at"]
        assert after_run["finished_at"] == original_run["finished_at"]

        after_run_steps = self.store.get_run_steps(run_id)
        assert len(after_run_steps) == len(original_run_steps)
        for original, after in zip(original_run_steps, after_run_steps):
            assert original.run_step_id == after.run_step_id
            assert original.status == after.status
            assert original.execution_fingerprint == after.execution_fingerprint

    def test_migrate_does_not_rewrite_artifacts(self):
        from cardre.executor import PlanExecutor
        from cardre.registry import NodeRegistry

        project_id = self.store.create_project("test")
        plan_id = self.store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        pv_id = self.store.create_plan_version(plan_id, steps, description="v1")

        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        executor.run_plan_version(self.store, pv_id)

        original_artifacts = self.store.list_artifacts()

        migrate_project_to_branch_model(self.store, project_id)

        after_artifacts = self.store.list_artifacts()
        assert len(after_artifacts) == len(original_artifacts)
        for oa, aa in zip(original_artifacts, after_artifacts):
            assert oa.artifact_id == aa.artifact_id
            assert oa.physical_hash == aa.physical_hash
            assert oa.logical_hash == aa.logical_hash

    def test_migrate_branch_list_endpoint_works(self):
        project_id = self.store.create_project("test")
        plan_id = self.store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        self.store.create_plan_version(plan_id, steps, description="v1")

        migrate_project_to_branch_model(self.store, project_id)

        branches = self.store.list_branches(project_id)
        assert len(branches) == 1
        branch = branches[0]
        assert branch["name"] == "Baseline"
        assert branch["branch_type"] == "baseline"

    def test_migrate_creates_branch_with_correct_head_version(self):
        project_id = self.store.create_project("test")
        plan_id = self.store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        pv1 = self.store.create_plan_version(plan_id, steps[:1], description="v1")
        pv2 = self.store.create_plan_version(plan_id, steps, description="v2")

        migrate_project_to_branch_model(self.store, project_id)

        branches = self.store.list_branches(project_id)
        branch = branches[0]
        assert branch["base_plan_version_id"] == pv1
        assert branch["head_plan_version_id"] == pv2
