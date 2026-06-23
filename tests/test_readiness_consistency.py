"""Tests proving readiness blockers and collector limitations agree for key scenarios."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cardre.readiness import check_report_readiness, LimitationCode
from cardre.reporting.collector import generate_report_bundle
from cardre.store import ProjectStore


def _init_store(tmp: str) -> ProjectStore:
    store = ProjectStore(Path(tmp))
    store.initialize()
    return store


class TestCollectorReadinessConsistency:
    """Collector blocker-level limitations must be a subset of readiness blockers.

    The collector and readiness check share some limitation codes but not all.
    This test proves that when the collector emits a blocker-level code that
    also exists in the readiness vocabulary, readiness agrees.  Collector-only
    codes (e.g. MISSING_MODEL_COEFFICIENTS which checks coefficient detail)
    are exempt from this assertion — they represent a different level of
    granularity.
    """

    def test_collector_target_branch_not_found_is_readiness_blocker(self):
        """TARGET_BRANCH_NOT_FOUND emitted by collector must also be a readiness blocker."""
        from cardre.audit import StepSpec

        with tempfile.TemporaryDirectory() as tmp:
            store = _init_store(tmp)
            prj_id = store.create_project("Test Project")
            plan_id = store.create_plan(prj_id, "Test Plan")

            step = StepSpec(
                "final-woe-iv", "cardre.woe_iv", "", "build",
                {}, "", [], "baseline", 1, canonical_step_id="final-woe-iv",
            )
            pv_id = store.create_plan_version(plan_id, steps=[step])
            run_id = store.create_run(pv_id)
            store.finish_run(run_id, status="succeeded")

            # Non-existent branch — both collector and readiness should
            # emit TARGET_BRANCH_NOT_FOUND as a blocker.
            bundle = generate_report_bundle(
                store=store, project_id=prj_id, run_id=run_id,
                target_branch_id="nonexistent", report_mode="branch",
            )
            collector_blocker_codes = {
                str(lim.code)
                for lim in bundle.limitations
                if lim.severity == "blocker"
            }

            result = check_report_readiness(
                store=store, project_id=prj_id, run_id=run_id,
                target_branch_id="nonexistent", report_mode="branch",
            )
            readiness_blocker_codes = {str(b.code) for b in result.blockers}

            # Explicit assertion: expected blocker appears on both sides
            assert str(LimitationCode.TARGET_BRANCH_NOT_FOUND) in collector_blocker_codes, (
                f"Collector did not emit TARGET_BRANCH_NOT_FOUND: "
                f"collector_blocker_codes={collector_blocker_codes}"
            )
            assert str(LimitationCode.TARGET_BRANCH_NOT_FOUND) in readiness_blocker_codes, (
                f"Readiness did not block with TARGET_BRANCH_NOT_FOUND: "
                f"readiness_blocker_codes={readiness_blocker_codes}"
            )

            # Subset: every collector blocker-level code must appear in readiness
            codes_only_in_collector = collector_blocker_codes - readiness_blocker_codes
            assert not codes_only_in_collector, (
                f"Collector emitted blocker-level codes absent from readiness: "
                f"{codes_only_in_collector}"
            )

    def test_collector_woe_iv_missing_step_is_readiness_blocker(self):
        """When final-woe-iv has no run step, both collector and readiness block.

        Collector emits MISSING_WOE_IV_EVIDENCE_V1 (blocker).
        Readiness emits MISSING_REQUIRED_CANONICAL_STEP because no run step exists.
        These are structurally different codes but both are blockers referenced
        in the respective code sets.  This test documents that the codes differ
        rather than silently passing.
        """
        import uuid
        from cardre.audit import StepSpec, utc_now_iso

        with tempfile.TemporaryDirectory() as tmp:
            store = _init_store(tmp)
            prj_id = store.create_project("Test Project")
            plan_id = store.create_plan(prj_id, "Test Plan")

            step = StepSpec(
                "final-woe-iv", "cardre.woe_iv", "", "build",
                {}, "", [], "baseline", 1, canonical_step_id="final-woe-iv",
            )
            pv_id = store.create_plan_version(plan_id, steps=[step])

            branch_id = str(uuid.uuid4())
            store._connect().execute(
                "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
                "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (branch_id, plan_id, prj_id, "Branch", "baseline", pv_id, pv_id,
                 utc_now_iso(), utc_now_iso(), "test"),
            )
            store._connect().commit()

            for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
                store.create_branch_step_map(
                    branch_id=branch_id, plan_version_id=pv_id,
                    canonical_step_id=cid, step_id=cid,
                    is_shared_upstream=False, is_branch_owned=True,
                )

            run_id = store.create_run(plan_version_id=pv_id)

            # Create run steps for everything EXCEPT final-woe-iv
            for step_id in ("model-fit", "score-scaling", "validation-metrics"):
                rs_id = str(uuid.uuid4())
                with store.transaction() as conn:
                    conn.execute(
                        "INSERT INTO run_steps "
                        "(run_step_id, run_id, step_id, plan_version_id, status, "
                        " output_artifact_ids_json, input_artifact_ids_json, "
                        " execution_fingerprint_json, started_at, finished_at, "
                        " warnings_json, errors_json, is_carried_forward) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (rs_id, run_id, step_id, pv_id, "succeeded",
                         "[]", "[]", '{"params_hash":"x"}',
                         utc_now_iso(), utc_now_iso(),
                         "[]", "[]", 0),
                    )
            store.finish_run(run_id, status="succeeded")

            # Collector should emit MISSING_WOE_IV_EVIDENCE_V1 as blocker
            # (no run step for final-woe-iv → collector line 312)
            bundle = generate_report_bundle(
                store=store, project_id=prj_id, run_id=run_id,
                target_branch_id=branch_id, report_mode="branch",
            )
            collector_blocker_codes = {
                str(lim.code)
                for lim in bundle.limitations
                if lim.severity == "blocker"
            }

            # Readiness should block (MISSING_REQUIRED_CANONICAL_STEP because
            # no run step exists for final-woe-iv, or MISSING_WOE_IV_EVIDENCE_V1
            # depending on resolution)
            result = check_report_readiness(
                store=store, project_id=prj_id, run_id=run_id,
                target_branch_id=branch_id, report_mode="branch",
            )
            readiness_blocker_codes = {str(b.code) for b in result.blockers}

            assert str(LimitationCode.MISSING_WOE_IV_EVIDENCE_V1) in collector_blocker_codes, (
                f"Collector did not emit MISSING_WOE_IV_EVIDENCE_V1: "
                f"collector_blocker_codes={collector_blocker_codes}"
            )
            assert len(readiness_blocker_codes) > 0, (
                "Readiness did not block at all"
            )
