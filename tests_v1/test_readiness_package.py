"""Tests for the cardre/readiness/ package — single-producer invariant and DTO shape."""

from __future__ import annotations

import tempfile
from pathlib import Path


from cardre.readiness import check_report_readiness, ReportReadinessResult, ReadinessBlocker, ReadinessWarning
from cardre.services.workflow_guidance_service import WorkflowGuidanceService
from cardre.store import ProjectStore


def _init_store(tmp: str) -> ProjectStore:
    store = ProjectStore(Path(tmp))
    store.initialize()
    return store


def _store_with_branch_and_run(tmp: str) -> tuple[ProjectStore, str, str, str, str]:
    """Create a minimal store with project, plan, plan_version, branch, and run.

    Returns (store, project_id, plan_id, branch_id, run_id).
    """
    store = _init_store(tmp)
    prj_id = store.create_project("Test Project")
    plan_id = store.create_plan(prj_id, "Test Plan")
    pv_id = store.create_plan_version(plan_id, steps=[])

    import uuid
    from cardre.audit import utc_now_iso

    branch_id = str(uuid.uuid4())
    store._connect().execute(
        "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
        "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (branch_id, plan_id, prj_id, "Test Branch", "baseline", pv_id, pv_id,
         utc_now_iso(), utc_now_iso(), "test"),
    )
    store._connect().commit()

    run_id = store.create_run(plan_version_id=pv_id)
    store.finish_run(run_id, status="succeeded")

    # Create a branch_step_map entry so the required_canonical_steps check passes
    for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
        from uuid import uuid4 as gen_uuid
        store._connect().execute(
            "INSERT INTO branch_step_map "
            "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
            " is_shared_upstream, is_branch_owned, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(gen_uuid()), branch_id, pv_id, cid, cid,
             1, 0, utc_now_iso()),
        )
    store._connect().commit()

    return store, prj_id, plan_id, branch_id, run_id


class TestSingleProducer:
    """The report-readiness route and the workflow-guidance route must produce the same
    blocker and warning dicts for the same inputs."""

    def test_single_producer_shape_blocked(self):
        """Both paths produce equal blockers/warnings in a minimal scenario."""
        with tempfile.TemporaryDirectory() as tmp:
            store, prj_id, plan_id, branch_id, run_id = _store_with_branch_and_run(tmp)

            # Path 1: direct check_report_readiness (used by /report-readiness)
            direct_result = check_report_readiness(
                store=store,
                project_id=prj_id,
                run_id=run_id,
                target_branch_id=branch_id,
                report_mode="branch",
            )
            direct_dict = direct_result.to_dict()

            # Path 2: WorkflowGuidanceService.build (used by /workflow-guidance)
            svc = WorkflowGuidanceService(store)
            guidance_result = svc.build(
                plan_id=plan_id,
                project_id=prj_id,
                branch_id=branch_id,
                run_id=run_id,
            )
            guidance_dict = guidance_result.report_readiness

            # Both paths produce a dict
            assert isinstance(direct_dict, dict)
            assert isinstance(guidance_dict, dict)

            # Deep-equal for blockers and warnings
            assert direct_dict["blockers"] == guidance_dict["blockers"], (
                f"Blockers differ. Direct: {direct_dict['blockers']!r}, "
                f"Guidance: {guidance_dict['blockers']!r}"
            )
            assert direct_dict["warnings"] == guidance_dict["warnings"], (
                f"Warnings differ. Direct: {direct_dict['warnings']!r}, "
                f"Guidance: {guidance_dict['warnings']!r}"
            )

            # ready/status must agree
            assert direct_dict["ready"] == guidance_dict["ready"]
            assert direct_dict["status"] == guidance_dict["status"]

    def test_to_dict_contains_step_id(self):
        """ReadinessBlocker.to_dict() includes step_id only when not None."""
        blocker = ReadinessBlocker("TEST_CODE", "test message")
        d = blocker.to_dict()
        assert "step_id" not in d, "step_id omitted when None"

        blocker_with_step = ReadinessBlocker("TEST_CODE_2", "test message", step_id="step-123")
        d2 = blocker_with_step.to_dict()
        assert d2["step_id"] == "step-123"

    def test_readiness_warning_to_dict_contains_step_id(self):
        warning = ReadinessWarning("TEST_WARN", "warning message")
        d = warning.to_dict()
        assert "step_id" not in d, "step_id omitted when None"

        warning_with_step = ReadinessWarning("TEST_WARN_2", "warning message", step_id="step-456")
        d2 = warning_with_step.to_dict()
        assert d2["step_id"] == "step-456"

    def test_report_readiness_result_serializes_step_ids(self):
        blockers = [
            ReadinessBlocker("MISSING_WOE_IV_EVIDENCE_V1", "No WOE/IV", step_id="woe-iv-step"),
            ReadinessBlocker("MANUAL_BINNING_NOT_REVIEWED", "Review needed", step_id="mb-step"),
        ]
        result = ReportReadinessResult(blockers=blockers)
        d = result.to_dict()
        assert len(d["blockers"]) == 2
        assert d["blockers"][0]["step_id"] == "woe-iv-step"
        assert d["blockers"][1]["step_id"] == "mb-step"

    # Known limitation — manual-binning readiness is not yet branch-scoped
    # (Phase 1 will fix this by routing through resolve_required_steps).
    # This test documents the current behaviour: the linear scan may find
    # a step owned by a different branch.
    def test_manual_binning_linear_scan_not_branch_scoped(self):
        """Manual-binning check scans plan_version_steps linearly, not via
        resolve_required_steps. Branch-scoped resolution is Phase 1."""
        import uuid

        with tempfile.TemporaryDirectory() as tmp:
            store = _init_store(tmp)
            prj_id = store.create_project("Test Project")
            plan_id = store.create_plan(prj_id, "Test Plan")

            from cardre.audit import StepSpec, utc_now_iso
            mb_step = StepSpec(
                "manual-binning__br_b",
                "cardre.manual_binning",
                "",
                "build",
                {"reviewed": False},
                "",
                [],
                "baseline",
                1,
                canonical_step_id="manual-binning",
            )
            pv_id = store.create_plan_version(plan_id, steps=[mb_step])

            branch_id = str(uuid.uuid4())
            store._connect().execute(
                "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
                "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (branch_id, plan_id, prj_id, "Test Branch", "baseline", pv_id, pv_id,
                 utc_now_iso(), utc_now_iso(), "test"),
            )
            store._connect().commit()

            run_id = store.create_run(plan_version_id=pv_id)
            store.finish_run(run_id, status="succeeded")

            result = check_report_readiness(
                store=store,
                project_id=prj_id,
                run_id=run_id,
                target_branch_id=branch_id,
                report_mode="branch",
            )

            codes = {b.code for b in result.blockers}
            # The linear scan found the manual-binning step from the plan
            # version, not scoped through branch_step_map. Phase 1 will
            # change this to use resolve_required_steps.
            known_limitations = {
                "MISSING_REQUIRED_CANONICAL_STEP",  # no step map entry
                "MANUAL_BINNING_NOT_REVIEWED",      # found via linear scan
            }
            assert codes & known_limitations, (
                f"Expected at least one known-limitation blocker, got {codes}"
            )

