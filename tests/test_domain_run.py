from __future__ import annotations

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import Run, RunStep, RunStepStatus


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
        run.transition_to("succeeded")


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


def _run(status: str = "running", heartbeat_at: str | None = None) -> Run:
    return Run(
        run_id="run-1",
        plan_version_id="pv-1",
        status=status,
        started_at=utc_now_iso(),
        heartbeat_at=heartbeat_at,
    )


def test_non_running_is_never_stale() -> None:
    assert _run(status="succeeded").is_stale(stale_heartbeat_seconds=300) is False


def test_running_no_heartbeat_is_stale() -> None:
    assert _run(heartbeat_at=None).is_stale(stale_heartbeat_seconds=300) is True


def test_running_recent_heartbeat_is_fresh() -> None:
    from datetime import UTC, datetime, timedelta

    hb = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    assert _run(heartbeat_at=hb).is_stale(stale_heartbeat_seconds=300) is False


def test_running_old_heartbeat_is_stale() -> None:
    from datetime import UTC, datetime, timedelta

    hb = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
    assert _run(heartbeat_at=hb).is_stale(stale_heartbeat_seconds=300) is True


def test_malformed_heartbeat_is_stale() -> None:
    assert _run(heartbeat_at="not-a-date").is_stale(stale_heartbeat_seconds=300) is True


def test_now_ts_is_injectable_and_deterministic() -> None:
    from datetime import UTC, datetime, timedelta

    hb = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
    run = _run(heartbeat_at=hb)
    assert run.is_stale(stale_heartbeat_seconds=300, now_ts=1e12) is True
    assert run.is_stale(stale_heartbeat_seconds=300, now_ts=0.0) is False


def test_is_stale_uses_threshold_boundary() -> None:
    from datetime import UTC, datetime, timedelta

    hb = (datetime.now(UTC) - timedelta(seconds=299)).isoformat()
    assert _run(heartbeat_at=hb).is_stale(stale_heartbeat_seconds=300) is False
    hb = (datetime.now(UTC) - timedelta(seconds=301)).isoformat()
    assert _run(heartbeat_at=hb).is_stale(stale_heartbeat_seconds=300) is True
