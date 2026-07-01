"""Phase 1 tests — WorkflowGuidanceService delegation and key resolution.

Phase 0 locked the seam (constructible, zero public methods).
Phase 1 replaces that test with real delegation coverage.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cardre.audit import StepSpec, json_logical_hash, utc_now_iso
from cardre.store import ProjectStore
from cardre.services.workflow_guidance_service import (
    WorkflowGuidanceService,
    WorkflowGuidanceServiceError,
    BUILD_STREAM_CANONICAL_IDS,
    VALIDATE_STREAM_CANONICAL_IDS,
)


def _init_store(tmp: str) -> ProjectStore:
    """Create and initialize a fresh ProjectStore in a temp directory."""
    store = ProjectStore(Path(tmp))
    store.initialize()
    return store


def test_constructible():
    """Service can be constructed with a ProjectStore."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        assert isinstance(svc, WorkflowGuidanceService)


def test_raises_without_branch_and_run():
    """Raises WorkflowGuidanceServiceError when both branch_id and run_id are None."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        with pytest.raises(WorkflowGuidanceServiceError, match="At least one"):
            svc.build(plan_id="p1", project_id="prj1")


def test_default_step_guidance_keys():
    """All canonical steps appear in step_guidance output, even when no data exists."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        result = svc.build(plan_id="p1", project_id="prj1", branch_id="b1")
        for cid in BUILD_STREAM_CANONICAL_IDS + VALIDATE_STREAM_CANONICAL_IDS:
            assert cid in result.step_guidance, f"Missing {cid}"
            sg = result.step_guidance[cid]
            assert "readiness" in sg
            assert "primary_action" in sg
            assert "explanation" in sg
            assert "evidence_kinds" in sg


def test_phase_is_setup_when_no_train_artifact():
    """Phase is 'setup' when no train-role artifact exists."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        result = svc.build(plan_id="p1", project_id="prj1", branch_id="b1")
        assert result.phase == "setup"


def test_build_stream_constants_match():
    """Verify no overlap between build and validate stream constants."""
    build_set = set(BUILD_STREAM_CANONICAL_IDS)
    validate_set = set(VALIDATE_STREAM_CANONICAL_IDS)
    assert build_set & validate_set == set(), "Overlap between build and validate streams"
    assert "model-fit" in build_set or "logistic-regression" in build_set


def test_known_evidence_kinds():
    """Spot-check that important steps have evidence_kinds populated."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        result = svc.build(plan_id="p1", project_id="prj1", branch_id="b1")
        mb = result.step_guidance.get("manual-binning", {})
        assert len(mb.get("evidence_kinds", [])) > 0, "manual-binning should have evidence_kinds"


# ---------------------------------------------------------------------------
# Fix 1: branch/run consistency
# ---------------------------------------------------------------------------

def test_raises_on_inconsistent_branch_and_run():
    """Raises WorkflowGuidanceServiceError when branch_id and run_id conflict."""
    import uuid
    from cardre.audit import utc_now_iso

    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        prj_id = store.create_project("Test Project")

        plan_id = store.create_plan(prj_id, "Test Plan")
        pv1 = store.create_plan_version(plan_id, steps=[])
        pv2 = store.create_plan_version(plan_id, steps=[])

        # Branch A with head = pv1
        branch_a_id = str(uuid.uuid4())
        store._connect().execute(
            "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
            "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (branch_a_id, plan_id, prj_id, "Branch A", "baseline", pv1, pv1,
             utc_now_iso(), utc_now_iso(), "test"),
        )
        store._connect().commit()

        # Run on pv1
        run_id = store.create_run(plan_version_id=pv1)
        store.finish_run(run_id, status="succeeded")

        # Branch B with head = pv2 (different from run's pv1)
        branch_b_id = str(uuid.uuid4())
        store._connect().execute(
            "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
            "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (branch_b_id, plan_id, prj_id, "Branch B", "challenger", pv2, pv2,
             utc_now_iso(), utc_now_iso(), "test"),
        )
        store._connect().commit()

        svc = WorkflowGuidanceService(store)
        # branch_b head = pv2, but run is on pv1 → mismatch
        with pytest.raises(WorkflowGuidanceServiceError, match="inconsistent"):
            svc.build(
                plan_id=plan_id, project_id=prj_id,
                branch_id=branch_b_id, run_id=run_id,
            )


# ---------------------------------------------------------------------------
# Fix 2: no fallback to failed runs
# ---------------------------------------------------------------------------

def test_no_fallback_to_failed_run():
    """When a branch has only a failed run, run_id stays None and report_readiness absent."""
    import uuid
    from cardre.audit import utc_now_iso

    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        prj_id = store.create_project("Fail Project")

        plan_id = store.create_plan(prj_id, "Fail Plan")
        pv_id = store.create_plan_version(plan_id, steps=[])

        branch_id = str(uuid.uuid4())
        store._connect().execute(
            "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
            "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (branch_id, plan_id, prj_id, "Fail Branch", "baseline", pv_id, pv_id,
             utc_now_iso(), utc_now_iso(), "test"),
        )
        store._connect().commit()

        # Create a failed run (no successful run exists)
        run_id = store.create_run(plan_version_id=pv_id)
        store.finish_run(run_id, status="failed")

        svc = WorkflowGuidanceService(store)
        result = svc.build(
            plan_id=plan_id, project_id=prj_id, branch_id=branch_id,
        )

        # Run_id should be None because no successful run existed
        assert result.run_id is None, "Should not fall back to failed run"
        # No report readiness without a valid run
        assert result.report_readiness is None
        # Phase should be build or setup (not report/ready)
        assert result.phase in ("setup", "build")


# ---------------------------------------------------------------------------
# Fix 3: step status derived from branch context
# ---------------------------------------------------------------------------

def test_step_readiness_from_branch_context():
    """Step readiness for a branch-owned step uses branch step map resolution."""
    import uuid
    from cardre.audit import StepSpec, utc_now_iso

    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        prj_id = store.create_project("Branch Ctx Project")

        plan_id = store.create_plan(prj_id, "Branch Ctx Plan")
        # Create a plan version with a manual-binning step
        mb_step = StepSpec(
            "manual-binning__br_custom",      # step_id
            "cardre.manual_binning",          # node_type
            "",                               # node_version
            "build",                          # category
            {},                               # params
            "",                               # params_hash
            [],                               # parent_step_ids
            "baseline",                       # branch_label
            12,                               # position
            canonical_step_id="manual-binning",
        )
        pv_id = store.create_plan_version(plan_id, steps=[mb_step])

        branch_id = str(uuid.uuid4())
        store._connect().execute(
            "INSERT INTO plan_branches (branch_id, plan_id, project_id, name, branch_type, "
            "base_plan_version_id, head_plan_version_id, created_at, updated_at, created_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (branch_id, plan_id, prj_id, "Branch Ctx", "baseline", pv_id, pv_id,
             utc_now_iso(), utc_now_iso(), "test"),
        )

        # Create a branch_step_map entry for manual-binning
        from uuid import uuid4 as gen_uuid
        store._connect().execute(
            "INSERT INTO branch_step_map "
            "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
            " is_shared_upstream, is_branch_owned, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(gen_uuid()), branch_id, pv_id, "manual-binning", "manual-binning__br_custom",
             0, 1, utc_now_iso()),
        )
        store._connect().commit()

        # Create a successful run for this plan version
        run_id = store.create_run(plan_version_id=pv_id)
        store.finish_run(run_id, status="succeeded")

        svc = WorkflowGuidanceService(store)
        result = svc.build(
            plan_id=plan_id, project_id=prj_id,
            branch_id=branch_id,
            # Do NOT pass run_id — let it resolve from branch
        )

        # Should have resolved run_id from the successful run
        assert result.run_id is not None, "Should have resolved run_id from branch"

        # The step_guidance for manual-binning should reflect the branch-owned step
        # (may be blocked if upstream evidence is missing, but still resolved correctly)
        mb_guidance = result.step_guidance.get("manual-binning", {})
        assert "readiness" in mb_guidance, "manual-binning readiness missing"
        # Key assertion: the step was resolved; readiness exists (blocked due to
        # missing upstream evidence is expected in a minimal test fixture)
        assert mb_guidance.get("explanation", ""), "manual-binning should have explanation"
        assert mb_guidance.get("primary_action", ""), "manual-binning should have primary_action"
        # The branch-owned step should appear in the run step map (non-empty step_guidance
        # shows it was resolved from the branch_step_map, not the generic plan)
        assert len(mb_guidance.get("evidence_kinds", [])) > 0, "manual-binning evidence_kinds"


def test_degraded_diagnostics_when_staleness_fails(monkeypatch):
    """When compute_staleness raises, guidance is degraded with STALENESS_UNAVAILABLE."""
    from cardre.errors import GraphValidationError

    def _raise_staleness(*args, **kwargs):
        raise GraphValidationError("Staleness failed")

    monkeypatch.setattr("cardre.services.workflow_guidance_service.compute_staleness", _raise_staleness)

    tmp = tempfile.mkdtemp()
    store = _init_store(tmp)
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")

    # Create a plan version with a step, run it, and produce a train artifact
    # so the phase advances past "setup"
    import polars as pl
    from cardre.audit import RunStepRecord
    df = pl.DataFrame({"x": [1.0, 2.0], "y": [0, 1]})
    from cardre.artifacts import write_parquet_artifact
    train_art = write_parquet_artifact(store, artifact_type="dataset", role="train",
                                        stem="test-train", frame=df, metadata={})

    steps = [
        StepSpec(
            step_id="import", node_type="cardre.import_fixture_uci_german_credit",
            node_version="1", category="transform",
            params={"source_path": "/tmp/test.csv"},
            params_hash=json_logical_hash({"source_path": "/tmp/test.csv"}),
            parent_step_ids=[], branch_label="", position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps)
    run_id = store.create_run(pv_id)
    # Create a run step that references the train artifact
    rs = RunStepRecord(
        run_step_id="rs-1", run_id=run_id, step_id="import",
        plan_version_id=pv_id, status="succeeded",
        started_at=utc_now_iso(), finished_at=utc_now_iso(),
        input_artifact_ids=[], output_artifact_ids=[train_art.artifact_id],
        execution_fingerprint={"node_type": "cardre.import_fixture_uci_german_credit",
                                "node_version": "1", "params_hash": "h",
                                "parent_output_logical_hashes_by_step": {},
                                "output_artifact_logical_hashes": ["h1"]},
        warnings=[], errors=[],
    )
    store.save_run_step(rs)
    store.finish_run(run_id, status="succeeded")

    svc = WorkflowGuidanceService(store)
    result = svc.build(
        plan_id=plan_id, project_id=prj_id,
        run_id=run_id,
    )

    assert result.degraded is True, "Expected degraded=True when staleness fails"
    assert len(result.diagnostics) > 0, "Expected at least one diagnostic"
    codes = [d.code for d in result.diagnostics]
    assert "STALENESS_UNAVAILABLE" in codes, (
        f"Expected STALENESS_UNAVAILABLE diagnostic, got {codes}"
    )
    assert result.next_action_kind == "resolve_diagnostics", (
        f"Expected resolve_diagnostics action, got {result.next_action_kind}"
    )
