"""Tests for report readiness checks — early-return and basic blocker paths.

Covers the port-native check_report_readiness function through the production
persistence stack.
"""

from __future__ import annotations

from cardre.application.reporting.readiness import check_report_readiness


class _FakeEvidenceReader:
    def read_step_output_optional(self, run_step_id, evidence_kind):
        return None


class TestCheckReportReadiness:
    def test_missing_run_blocks(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            result = check_report_readiness(
                uow, _FakeEvidenceReader(), project_id, "nonexistent-run",
            )
        assert not result.ready
        assert any(f.code == "MISSING_RUN_MANIFEST" for f in result.blockers)

    def test_unsuccessful_run_blocks(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            run_id = uow.runs.create(pv_id)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = check_report_readiness(
                uow, _FakeEvidenceReader(), project_id, run_id,
            )
        assert not result.ready
        assert any(f.code == "RUN_NOT_SUCCEEDED" for f in result.blockers)
