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
    """Collector blocker-level limitations must be a subset of readiness blockers."""

    def test_collector_woe_iv_blocker_is_readiness_blocker(self):
        """MISSING_WOE_IV_EVIDENCE_V1 emitted by collector must also be a readiness blocker."""
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

            # Create a run step for final-woe-iv with NO v1 evidence artifact
            for step_id in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
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
                         "[]", "[]", '{"params_hash":"x","output_artifact_logical_hashes":[]}',
                         utc_now_iso(), utc_now_iso(),
                         "[]", "[]", 0),
                    )
            store.finish_run(run_id, status="succeeded")

            # Collector should emit MISSING_WOE_IV_EVIDENCE_V1
            bundle = generate_report_bundle(
                store=store, project_id=prj_id, run_id=run_id,
                target_branch_id=branch_id, report_mode="branch",
            )
            collector_blocker_codes = {
                str(LimitationCode.MISSING_WOE_IV_EVIDENCE_V1)
                for lim in bundle.limitations
                if lim.severity == "blocker"
            }

            # Readiness should also block with MISSING_WOE_IV_EVIDENCE_V1
            result = check_report_readiness(
                store=store, project_id=prj_id, run_id=run_id,
                target_branch_id=branch_id, report_mode="branch",
            )
            readiness_blocker_codes = {str(b.code) for b in result.blockers}

            # Every collector blocker-level code must appear in readiness blockers
            missing_in_readiness = collector_blocker_codes - readiness_blocker_codes
            assert not missing_in_readiness, (
                f"Collector emitted blocker-level codes absent from readiness: "
                f"{missing_in_readiness}"
            )
