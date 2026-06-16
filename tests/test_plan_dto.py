"""Tests for plan DTO models."""

from cardre.services.plan_dto import (
    PlanResponse,
    StepStatusItem,
    UpdateStepParamsResponse,
)


def test_step_status_item_defaults():
    item = StepStatusItem(step_id="s1", node_type="test", category="transform", status="not_run")
    assert item.step_id == "s1"
    assert item.is_stale is False


def test_update_step_params_response():
    resp = UpdateStepParamsResponse(
        plan_id="p1",
        new_plan_version_id="pv2",
        changed_step_id="s1",
        stale_step_ids=["s2", "s3"],
    )
    assert resp.plan_id == "p1"
    assert len(resp.stale_step_ids) == 2
