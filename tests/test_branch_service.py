"""Targeted unit tests for BranchService and related helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cardre.audit import StepSpec
from cardre.services.branch_service import (
    BranchService,
    _descendant_closure,
    _validate_segment_filter_rules,
    ALLOWED_BRANCH_POINTS,
)
from cardre.store import ProjectStore


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
