"""Targeted unit tests for BranchService and related helpers (v2)."""

from __future__ import annotations

import uuid

import pytest

from cardre.application.execution.step_graph import descendant_closure as _descendant_closure
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import BranchValidationError
from cardre.domain.step import StepSpec
from cardre.services.branch_service import (
    BranchService,
)
from cardre.services.branch_validator import (
    ALLOWED_BRANCH_POINTS,
    _validate_segment_filter_rules,
)
from cardre.store.branch_repo import BranchRepository
from cardre.store.plan_repo import PlanRepository

pytestmark = [pytest.mark.unit, pytest.mark.governance]


def _make_steps(count: int = 4) -> list[StepSpec]:
    """Return a simple linear pipeline of *count* steps."""
    from cardre.domain.artifacts import json_logical_hash

    steps = []
    for i in range(count):
        step_id = f"step-{i}"
        parent_ids = [f"step-{i-1}"] if i > 0 else []
        steps.append(StepSpec(
            step_id=step_id,
            node_type="cardre.noop",
            node_version="1",
            category="fit",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=parent_ids,
            branch_label="",
            position=i,
            canonical_step_id=step_id,
        ))
    return steps


@pytest.fixture
def project_and_plan(store):
    """Create a project with a simple plan."""
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "test-proj", utc_now_iso(), "0.2.0"),
    )

    plan_repo = PlanRepository(store)
    plan_id = plan_repo.create_plan(project_id, "test-plan")

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
    @pytest.mark.parametrize("rules,expected_code", [
        ({"rules": []}, "SEGMENT_FILTER_RULES_REQUIRED"),
        ({"rules": [{"operator": "==", "value": "x", "reason": "test"}]}, "SEGMENT_FILTER_INVALID"),
        ({"rules": [{"column": "age", "value": "x", "reason": "test"}]}, "SEGMENT_FILTER_INVALID"),
        ({"rules": [{"column": "age", "operator": "~=", "value": "x", "reason": "test"}]}, "SEGMENT_FILTER_UNSUPPORTED_OPERATOR"),
        ({"rules": [{"column": "age", "operator": "==", "value": "x", "reason": ""}]}, "SEGMENT_FILTER_REASON_REQUIRED"),
        ({"rules": [{"column": "age", "operator": ">", "reason": "test"}]}, "SEGMENT_FILTER_VALUE_REQUIRED"),
    ])
    def test_rejects_invalid_rules(self, rules, expected_code):
        with pytest.raises(BranchValidationError) as exc_info:
            _validate_segment_filter_rules(rules)
        assert exc_info.value.code == expected_code

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

    def _setup_plan_with_steps(self, store):
        """Create a project, plan, and plan version with branch-able steps."""
        from cardre.domain.diagnostics import utc_now_iso
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "test-proj", utc_now_iso(), "0.2.0"),
        )
        plan_repo = PlanRepository(store)
        plan_id = plan_repo.create_plan(project_id, "test-plan")

        # Create steps with branch-able canonical step IDs
        from cardre.domain.artifacts import json_logical_hash

        steps = [
            StepSpec(
                step_id="define-sample", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
                canonical_step_id="sample-definition",
            ),
            StepSpec(
                step_id="do-variable-selection", node_type="cardre.variable_selection",
                node_version="1", category="fit",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["define-sample"], branch_label="", position=1,
                canonical_step_id="variable-selection",
            ),
            StepSpec(
                step_id="do-manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["do-variable-selection"], branch_label="", position=2,
                canonical_step_id="manual-binning",
            ),
            StepSpec(
                step_id="fit-lr", node_type="cardre.logistic_regression",
                node_version="1", category="fit",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["do-manual-binning"], branch_label="", position=3,
                canonical_step_id="logistic-regression",
            ),
        ]
        pv_id = plan_repo.create_version(plan_id, steps, description="v1", is_committed=True)
        return project_id, plan_id, pv_id, steps

    def test_create_branch_success(self, store):
        project_id, plan_id, pv_id, steps = self._setup_plan_with_steps(store)
        branch_point_id = self._find_non_segment_branch_point(steps)
        if branch_point_id is None:
            pytest.skip("No non-segment branch point")

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
        branches_repo = BranchRepository(store)
        branch = branches_repo.get_branch(result["branch_id"])
        assert branch is not None
        assert branch["name"] == "Test Challenger"

    def test_create_branch_from_baseline(self, store):
        project_id, plan_id, pv_id, steps = self._setup_plan_with_steps(store)

        # Create a baseline branch first
        branches_repo = BranchRepository(store)
        baseline_branch_id = branches_repo.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Baseline.",
        )

        branch_point_id = self._find_non_segment_branch_point(steps)
        if branch_point_id is None:
            pytest.skip("No non-segment branch point")

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

    def test_create_segment_challenger(self, store):
        project_id, plan_id, pv_id, steps = self._setup_plan_with_steps(store)

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Segment Challenger",
            branch_type="segment_challenger",
            branch_point_step_id="sample-definition",
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
        pv_id = PlanRepository(store).create_version(plan_id, [], description="v1")
        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="Bad Branch",
                branch_type="model_challenger",
                branch_point_step_id="nonexistent",
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )
        assert exc_info.value.code == "BRANCH_POINT_NOT_ALLOWED"

    def test_create_branch_raises_on_type_mismatch(self, store):
        project_id, plan_id, pv_id, steps = self._setup_plan_with_steps(store)
        branch_point_id = self._find_non_segment_branch_point(steps)
        if branch_point_id is None:
            pytest.skip("No non-segment branch point")

        expected_type = ALLOWED_BRANCH_POINTS[branch_point_id]
        wrong_type = "segment_challenger" if expected_type != "segment_challenger" else "model_challenger"

        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="Type Mismatch",
                branch_type=wrong_type,
                branch_point_step_id=branch_point_id,
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )
        assert exc_info.value.code == "BRANCH_TYPE_MISMATCH"

    def test_create_branch_raises_on_empty_name(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = PlanRepository(store).create_version(plan_id, [], description="v1")
        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )
        assert exc_info.value.code == "BRANCH_NAME_REQUIRED"

    def test_create_branch_raises_on_empty_reason(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = PlanRepository(store).create_version(plan_id, [], description="v1")
        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="No Reason",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_plan_version_id=pv_id,
                created_reason="",
            )
        assert exc_info.value.code == "BRANCH_REASON_REQUIRED"

    def test_create_branch_raises_on_segment_filter_missing(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = PlanRepository(store).create_version(plan_id, [], description="v1")
        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
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
        assert exc_info.value.code == "SEGMENT_FILTER_REQUIRED"

    def test_create_branch_raises_on_plan_not_found(self, store, project_and_plan):
        project_id, _ = project_and_plan
        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id="nonexistent-plan-id",
                name="No Plan",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_plan_version_id="pv-nonexistent",
                created_reason="Should fail.",
            )
        assert exc_info.value.code == "PLAN_NOT_FOUND"

    def test_create_branch_raises_on_plan_project_mismatch(self, store):
        plan_repo = PlanRepository(store)
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "proj-a", utc_now_iso(), "0.2.0"),
        )
        other_project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (other_project_id, "proj-b", utc_now_iso(), "0.2.0"),
        )
        other_plan_id = plan_repo.create_plan(other_project_id, "Other Plan")
        pv_id = plan_repo.create_version(other_plan_id, [], description="v1")

        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id=other_plan_id,
                name="Wrong Project",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )
        assert exc_info.value.code == "PLAN_PROJECT_MISMATCH"

    def test_create_branch_step_map_created(self, store):
        """Verify that step map entries are created for the new branch."""
        project_id, plan_id, pv_id, steps = self._setup_plan_with_steps(store)
        branch_point_id = self._find_non_segment_branch_point(steps)
        if branch_point_id is None:
            pytest.skip("No non-segment branch point")

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Step Map Test",
            branch_type=ALLOWED_BRANCH_POINTS[branch_point_id],
            branch_point_step_id=branch_point_id,
            base_branch_id=None,
            base_plan_version_id=pv_id,
            created_reason="Step map test.",
        )

        branches_repo = BranchRepository(store)
        step_map = branches_repo.get_step_map(result["branch_id"], result["new_plan_version_id"])
        assert len(step_map) > 0
        # Shared upstream steps should be present
        assert len(result["shared_upstream_step_ids"]) > 0
        # Created (branch-owned) steps should be present
        assert len(result["created_step_ids"]) > 0

    def test_create_branch_preserves_shared_and_duplicated_edges(self, store):
        project_id, plan_id, pv_id, steps = self._setup_plan_with_steps(store)

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Manual Binning Challenger",
            branch_type="binning_challenger",
            branch_point_step_id="manual-binning",
            base_branch_id=None,
            base_plan_version_id=pv_id,
            created_reason="Edge preservation test.",
        )

        branches_repo = BranchRepository(store)
        step_map = branches_repo.get_step_map(result["branch_id"], result["new_plan_version_id"])
        by_canonical = {row["canonical_step_id"]: row for row in step_map}

        assert by_canonical["sample-definition"]["is_shared_upstream"] == 1
        assert by_canonical["variable-selection"]["is_shared_upstream"] == 1
        assert by_canonical["manual-binning"]["is_branch_owned"] == 1
        assert by_canonical["logistic-regression"]["is_branch_owned"] == 1
        assert by_canonical["manual-binning"]["source_step_id"] == "do-manual-binning"
        assert by_canonical["logistic-regression"]["source_step_id"] == "fit-lr"

        new_steps = {
            step.step_id: step
            for step in PlanRepository(store).get_version_steps(result["new_plan_version_id"])
        }
        manual_binning_new_id = result["created_step_ids"]["manual-binning"]
        lr_new_id = result["created_step_ids"]["logistic-regression"]

        assert new_steps[manual_binning_new_id].parent_step_ids == ["do-variable-selection"]
        assert new_steps[lr_new_id].parent_step_ids == [manual_binning_new_id]
