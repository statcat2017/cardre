"""Phase 1 — domain run: state machine transitions, illegal transitions raise,
    RunStep does not own artifact arrays."""

import pytest

from cardre.domain.run import (
    Run,
    RunScope,
    RunStep,
    RunStepEvidenceView,
    RunStepStatus,
    _check_transition,
)


class TestRunStateMachine:
    """Run status transitions."""

    def test_created_to_queued(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="created", started_at="now")
        r2 = r.transition_to("queued")
        assert r2.status == "queued"
        assert r2.finished_at is None

    def test_queued_to_running(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="queued", started_at="now")
        r2 = r.transition_to("running")
        assert r2.status == "running"

    def test_running_to_succeeded(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="running", started_at="now")
        r2 = r.transition_to("succeeded")
        assert r2.status == "succeeded"
        assert r2.finished_at is not None

    def test_running_to_failed(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="running", started_at="now")
        r2 = r.transition_to("failed")
        assert r2.status == "failed"
        assert r2.finished_at is not None

    def test_running_to_cancelled(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="running", started_at="now")
        r2 = r.transition_to("cancelled")
        assert r2.status == "cancelled"
        assert r2.finished_at is not None

    def test_running_to_interrupted(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="running", started_at="now")
        r2 = r.transition_to("interrupted")
        assert r2.status == "interrupted"
        assert r2.finished_at is not None

    def test_created_to_running_raises(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="created", started_at="now")
        with pytest.raises(ValueError, match="Invalid run state transition"):
            r.transition_to("running")

    def test_succeeded_is_terminal(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="succeeded", started_at="now")
        with pytest.raises(ValueError):
            r.transition_to("running")

    def test_failed_is_terminal(self):
        r = Run(run_id="r1", plan_version_id="pv1", status="failed", started_at="now")
        with pytest.raises(ValueError):
            r.transition_to("running")

    def test_original_run_is_unchanged(self):
        """transition_to returns a new Run — original is not mutated."""
        r = Run(run_id="r1", plan_version_id="pv1", status="created", started_at="now",
                finished_at=None, branch_id="b1")
        r.transition_to("queued")
        assert r.status == "created"  # original unchanged


class TestRunStepDomain:
    """RunStep does not own artifact arrays."""

    def test_run_step_no_artifact_arrays(self):
        """RunStep does not have input/output artifact ID fields."""
        step = RunStep(
            run_step_id="rs1",
            run_id="r1",
            step_id="s1",
            plan_version_id="pv1",
            status=RunStepStatus.PENDING,
            started_at="now",
        )
        assert step.run_step_id == "rs1"
        assert not hasattr(step, "input_artifact_ids")
        assert not hasattr(step, "output_artifact_ids")

    def test_run_step_execution_fingerprint_empty(self):
        step = RunStep(
            run_step_id="rs1",
            run_id="r1",
            step_id="s1",
            plan_version_id="pv1",
            status=RunStepStatus.PENDING,
            started_at="now",
        )
        assert step.execution_fingerprint == {}

    def test_run_step_evidence_view_derives_artifacts(self):
        """RunStepEvidenceView composes RunStep with derived artifact lists."""
        step = RunStep(
            run_step_id="rs1",
            run_id="r1",
            step_id="s1",
            plan_version_id="pv1",
            status=RunStepStatus.PENDING,
            started_at="now",
        )
        view = RunStepEvidenceView(
            run_step=step,
            input_artifacts=[],
            output_artifacts=[],
        )
        assert view.run_step.run_step_id == "rs1"
        assert view.input_artifacts == []
        assert view.output_artifacts == []


class TestRunScope:
    def test_minimal_scope(self):
        scope = RunScope(plan_version_id="pv1")
        assert scope.plan_version_id == "pv1"
        assert scope.branch_id is None
        assert scope.target_step_id is None
        assert scope.force is False

    def test_full_scope(self):
        scope = RunScope(
            plan_version_id="pv1",
            branch_id="b1",
            target_step_id="s1",
            force=True,
        )
        assert scope.branch_id == "b1"
        assert scope.target_step_id == "s1"
        assert scope.force is True


class TestCheckTransition:
    def test_valid_transition(self):
        _check_transition("created", "queued")  # should not raise

    def test_invalid_transition(self):
        with pytest.raises(ValueError):
            _check_transition("succeeded", "running")

    def test_unknown_state(self):
        with pytest.raises(ValueError):
            _check_transition("unknown", "running")
