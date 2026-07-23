"""Tests for report readiness checks — early-return and basic blocker paths.

Covers the port-native check_report_readiness function through the production
persistence stack.
"""

from __future__ import annotations

from cardre.application.reporting.readiness import check_report_readiness


class _FakeEvidenceReader:
    def read_step_output_optional(self, run_step_id, evidence_kind):
        return None


def _factory(uow_factory, project_id):
    def factory():
        return uow_factory.for_project(project_id)
    return factory


class TestCheckReportReadiness:
    def test_missing_branch_blocks(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            result = check_report_readiness(
                uow, _FakeEvidenceReader(), project_id, "nonexistent-run",
                "nonexistent-branch", "branch",
            )
        assert not result.ready
        assert any(f.code == "TARGET_BRANCH_NOT_FOUND" for f in result.blockers)

    def test_missing_run_blocks(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            branch_id = uow.branches.create_branch(
                project_id=project_id, plan_id=plan_id, name="B",
                branch_type="baseline", base_plan_version_id=pv_id,
                head_plan_version_id=pv_id, created_reason="test",
            )
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = check_report_readiness(
                uow, _FakeEvidenceReader(), project_id, "nonexistent-run",
                branch_id, "branch",
            )
        assert not result.ready
        assert any(f.code == "MISSING_RUN_MANIFEST" for f in result.blockers)

    def test_inactive_branch_blocks(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            branch_id = uow.branches.create_branch(
                project_id=project_id, plan_id=plan_id, name="B",
                branch_type="baseline", base_plan_version_id=pv_id,
                head_plan_version_id=pv_id, created_reason="test",
            )
            uow._conn.execute(
                "UPDATE plan_branches SET status = 'inactive' WHERE branch_id = ?",
                (branch_id,),
            )
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = check_report_readiness(
                uow, _FakeEvidenceReader(), project_id, "nonexistent-run",
                branch_id, "branch",
            )
        assert not result.ready
        assert any(f.code == "TARGET_BRANCH_NOT_FOUND" or f.code == "MISSING_RUN_MANIFEST"
                   for f in result.blockers)
