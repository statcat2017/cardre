from __future__ import annotations

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import Run
from cardre.domain.run import RunStep
from cardre.domain.run import RunStepStatus


def test_run_transition_sets_terminal_finished_at() -> None:
    run = Run(
        run_id="run-1",
        plan_version_id="pv-1",
        status="created",
        started_at=utc_now_iso(),
    )

    queued = run.transition_to("queued")
    running = queued.transition_to("running")
    finished = running.transition_to("succeeded")

    assert queued.status == "queued"
    assert queued.finished_at is None
    assert running.status == "running"
    assert finished.status == "succeeded"
    assert finished.finished_at is not None


def test_run_rejects_invalid_transition() -> None:
    run = Run(
        run_id="run-1",
        plan_version_id="pv-1",
        status="created",
        started_at=utc_now_iso(),
    )

    with pytest.raises(ValueError):
        run.transition_to("running")


def test_run_step_has_no_artifact_arrays() -> None:
    assert "input_artifact_ids" not in RunStep.__dataclass_fields__
    assert "output_artifact_ids" not in RunStep.__dataclass_fields__
    step = RunStep(
        run_step_id="rs-1",
        run_id="run-1",
        step_id="step-1",
        plan_version_id="pv-1",
        status=RunStepStatus.PENDING,
        started_at=utc_now_iso(),
    )
    assert step.status is RunStepStatus.PENDING
