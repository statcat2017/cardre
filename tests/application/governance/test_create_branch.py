"""Characterization tests for CreateBranch use case — pin branch-creation behavior.

Ported from tests/test_branch_service_characterization.py to exercise the new
application-layer CreateBranch use case through the production persistence
stack instead of the legacy BranchService + ProjectStore.
"""

from __future__ import annotations

import pytest

from cardre.adapters.sqlite.plan_repo import PlanRepo
from cardre.application.governance.create_branch import CreateBranch, CreateBranchCommand
from cardre.domain.errors import BranchValidationError

# =========================================================================
# Descendant closure direction
# =========================================================================


class TestDescendantClosureDirection:
    def test_branch_duplicates_only_downstream_steps(self, plan_with_branchable_version):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version
        use_case = CreateBranch(uow_factory)

        result = use_case(CreateBranchCommand(
            project_id=project_id, plan_id=plan_id, name="Desc-Test",
            branch_type="binning_challenger", branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id, created_reason="Descendant closure test.",
        ))

        created_canonical = set(result.created_step_ids.keys())
        assert "manual-binning" in created_canonical
        assert "logistic-regression" in created_canonical

        shared = result.shared_upstream_step_ids
        assert len(shared) == 2
        assert "step-sample-def" in shared
        assert "step-var-sel" in shared
        assert "step-manual-bin" not in shared
        assert "step-logistic-reg" not in shared


# =========================================================================
# ID remapping rules
# =========================================================================


class TestIDRemapping:
    def test_duplicated_step_ids_contain_branch_id(self, plan_with_branchable_version):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version
        use_case = CreateBranch(uow_factory)

        result = use_case(CreateBranchCommand(
            project_id=project_id, plan_id=plan_id, name="ID-Test",
            branch_type="binning_challenger", branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id, created_reason="ID remapping test.",
        ))

        for _canonical, new_step_id in result.created_step_ids.items():
            assert new_step_id.endswith(f"__{result.branch_id}"), (
                f"Created step ID {new_step_id!r} does not end with __{result.branch_id}"
            )

    def test_remapped_parent_step_ids_are_consistent(self, plan_with_branchable_version):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version
        use_case = CreateBranch(uow_factory)

        result = use_case(CreateBranchCommand(
            project_id=project_id, plan_id=plan_id, name="Parent-Test",
            branch_type="binning_challenger", branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id, created_reason="Parent remap test.",
        ))

        with uow_factory.for_project(project_id) as uow:
            new_steps = uow.plans.get_version_steps(result.new_plan_version_id)
        new_by_step_id = {s.step_id: s for s in new_steps}

        mb_new_id = result.created_step_ids["manual-binning"]
        mb_new_spec = new_by_step_id[mb_new_id]
        assert mb_new_spec.parent_step_ids == ["step-var-sel"]

        lr_new_id = result.created_step_ids["logistic-regression"]
        lr_new_spec = new_by_step_id[lr_new_id]
        assert lr_new_spec.parent_step_ids == [mb_new_id]

        vs_spec = new_by_step_id["step-var-sel"]
        assert vs_spec.parent_step_ids == ["step-sample-def"]


# =========================================================================
# Non-destructive — original plan version unchanged
# =========================================================================


class TestNonDestructive:
    def test_original_plan_version_remains_unchanged(self, plan_with_branchable_version):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version

        with uow_factory.for_project(project_id) as uow:
            original_steps = uow.plans.get_version_steps(pv_id)
        original_ids = {s.step_id: s.parent_step_ids for s in original_steps}

        use_case = CreateBranch(uow_factory)
        use_case(CreateBranchCommand(
            project_id=project_id, plan_id=plan_id, name="NonDestruct",
            branch_type="binning_challenger", branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id, created_reason="Non-destructive test.",
        ))

        with uow_factory.for_project(project_id) as uow:
            after_steps = uow.plans.get_version_steps(pv_id)
        after_ids = {s.step_id: s.parent_step_ids for s in after_steps}
        assert after_ids == original_ids

        with uow_factory.for_project(project_id) as uow:
            edges = uow._conn.execute(
                "SELECT parent_step_id, child_step_id FROM plan_step_edges WHERE plan_version_id = ?",
                (pv_id,),
            ).fetchall()
        assert len(edges) == 3
        parent_child = {(e["parent_step_id"], e["child_step_id"]) for e in edges}
        assert ("step-sample-def", "step-var-sel") in parent_child
        assert ("step-var-sel", "step-manual-bin") in parent_child
        assert ("step-manual-bin", "step-logistic-reg") in parent_child


# =========================================================================
# Return contract shape
# =========================================================================


class TestReturnContract:
    def test_create_branch_returns_all_expected_fields(self, plan_with_branchable_version):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version
        use_case = CreateBranch(uow_factory)

        result = use_case(CreateBranchCommand(
            project_id=project_id, plan_id=plan_id, name="Contract-Test",
            branch_type="binning_challenger", branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id, created_reason="Contract check.",
        ))

        assert result.branch_id
        assert result.new_plan_version_id
        assert result.name == "Contract-Test"
        assert result.branch_type == "binning_challenger"
        assert result.branch_point_step_id == "manual-binning"
        assert result.branch_point_canonical_step_id == "manual-binning"
        assert isinstance(result.created_step_ids, dict)
        assert isinstance(result.shared_upstream_step_ids, list)
        assert result.status == "not_run"
        assert isinstance(result.warnings, list)


# =========================================================================
# Validation edge cases
# =========================================================================


class TestValidationEdgeCases:
    def test_branch_point_not_in_plan_raises(self, plan_with_branchable_version):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version
        use_case = CreateBranch(uow_factory)

        with pytest.raises(BranchValidationError) as exc_info:
            use_case(CreateBranchCommand(
                project_id=project_id, plan_id=plan_id, name="No-BP",
                branch_type="cutoff_strategy_challenger",
                branch_point_step_id="cutoff-analysis",
                base_plan_version_id=pv_id, created_reason="Should fail.",
            ))
        assert exc_info.value.code == "BRANCH_POINT_NOT_IN_PLAN"

    def test_base_branch_inactive_raises(self, plan_with_branchable_version):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version

        with uow_factory.for_project(project_id) as uow:
            base_branch_id = uow.branches.create_branch(
                project_id=project_id, plan_id=plan_id, name="Inactive-Base",
                branch_type="baseline", base_plan_version_id=pv_id,
                head_plan_version_id=pv_id, created_reason="Base for inactive test.",
            )
            uow._conn.execute(
                "UPDATE plan_branches SET status = 'inactive' WHERE branch_id = ?",
                (base_branch_id,),
            )
            uow.commit()

        use_case = CreateBranch(uow_factory)
        with pytest.raises(BranchValidationError) as exc_info:
            use_case(CreateBranchCommand(
                project_id=project_id, plan_id=plan_id, name="From-Inactive",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_branch_id=base_branch_id, base_plan_version_id=pv_id,
                created_reason="Should fail.",
            ))
        assert exc_info.value.code == "BASE_BRANCH_INACTIVE"

    def test_reject_inference_requires_ttd_sample_domain(self, provisioned_project):
        from cardre.domain.artifacts import json_logical_hash
        from cardre.domain.step import StepSpec

        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "reject-inf")
            reject_pv_id = uow.plans.create_version(
                plan_id,
                steps=[
                    StepSpec(
                        step_id="step-sample-def", node_type="cardre.noop",
                        node_version="1", category="transform",
                        params={"sample_domain": "otb"},
                        params_hash=json_logical_hash({}),
                        parent_step_ids=[], branch_label="", position=0,
                        canonical_step_id="sample-definition",
                    ),
                    StepSpec(
                        step_id="step-reject", node_type="cardre.noop",
                        node_version="1", category="transform",
                        params={}, params_hash=json_logical_hash({}),
                        parent_step_ids=["step-sample-def"], branch_label="", position=1,
                        canonical_step_id="define-reject-population",
                    ),
                ],
                description="reject-test", is_committed=True,
            )
            uow.commit()

        use_case = CreateBranch(uow_factory)
        with pytest.raises(BranchValidationError) as exc_info:
            use_case(CreateBranchCommand(
                project_id=project_id, plan_id=plan_id, name="Reject-Inf",
                branch_type="reject_inference_challenger",
                branch_point_step_id="define-reject-population",
                base_plan_version_id=reject_pv_id,
                created_reason="Should fail (sample_domain must be ttd).",
            ))
        assert exc_info.value.code == "REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD"


# =========================================================================
# Segment filter validation at use-case level
# =========================================================================


class TestSegmentFilterUseCaseLevel:
    def test_invalid_segment_filter_operator_rejected(self, plan_with_branchable_version):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version
        use_case = CreateBranch(uow_factory)

        with pytest.raises(BranchValidationError) as exc_info:
            use_case(CreateBranchCommand(
                project_id=project_id, plan_id=plan_id, name="Bad-Filter",
                branch_type="segment_challenger",
                branch_point_step_id="sample-definition",
                base_plan_version_id=pv_id, created_reason="Segment filter test.",
                segment_filter_spec={
                    "rules": [
                        {"column": "age", "operator": "~=",
                         "value": 18, "reason": "Bad operator"},
                    ]
                },
            ))
        assert exc_info.value.code == "SEGMENT_FILTER_UNSUPPORTED_OPERATOR"


# =========================================================================
# Transactional rollback
# =========================================================================


class TestTransactionalRollback:
    def test_failure_after_plan_version_does_not_leave_partial_branch(
        self, plan_with_branchable_version, monkeypatch,
    ):
        project_id, plan_id, pv_id, uow_factory, _, _ = plan_with_branchable_version

        with uow_factory.for_project(project_id) as uow:
            branch_count_before = uow._conn.execute(
                "SELECT COUNT(*) FROM plan_branches WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            step_map_count_before = uow._conn.execute(
                "SELECT COUNT(*) FROM branch_step_map "
                "WHERE branch_id IN (SELECT branch_id FROM plan_branches WHERE project_id = ?)",
                (project_id,),
            ).fetchone()[0]

        use_case = CreateBranch(uow_factory)

        original_create_version = PlanRepo.create_version

        def _failing_create_version(self, plan_id_, steps_, **kwargs):
            original_create_version(self, plan_id_, steps_, **kwargs)
            raise RuntimeError("Simulated transaction failure")

        monkeypatch.setattr(PlanRepo, "create_version", _failing_create_version)

        with pytest.raises(RuntimeError, match="Simulated transaction failure"):
            use_case(CreateBranchCommand(
                project_id=project_id, plan_id=plan_id, name="TX-Fail",
                branch_type="binning_challenger", branch_point_step_id="manual-binning",
                base_plan_version_id=pv_id, created_reason="TX rollback test.",
            ))

        with uow_factory.for_project(project_id) as uow:
            branch_count_after = uow._conn.execute(
                "SELECT COUNT(*) FROM plan_branches WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            step_map_count_after = uow._conn.execute(
                "SELECT COUNT(*) FROM branch_step_map "
                "WHERE branch_id IN (SELECT branch_id FROM plan_branches WHERE project_id = ?)",
                (project_id,),
            ).fetchone()[0]

        assert branch_count_after == branch_count_before
        assert step_map_count_after == step_map_count_before
