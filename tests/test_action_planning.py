"""Tests for honest action planning (#214).

Every step action must carry a reason code. There are no pretend reuse/skip
branches.

"""

def test_step_action_has_reason_code():
    """_StepAction carries a reason_code field (#214)."""
    from cardre.application.execution.action_planner import _StepAction
    from cardre.domain.step import StepSpec

    spec = StepSpec(
        step_id="s1", node_type="cardre.noop", node_version="1",
        category="transform", params={}, params_hash="h", position=0,
        parent_step_ids=[], canonical_step_id="s1",
    )
    action = _StepAction(spec=spec, action="execute", reason_code="full_plan")
    assert action.reason_code == "full_plan"
    assert action.reason_context == {}
