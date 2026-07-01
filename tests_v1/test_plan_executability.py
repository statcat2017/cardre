"""A plan containing a deferred node must be rejected BEFORE any run row
is created or step executed."""
from __future__ import annotations

import pytest

from cardre.audit import StepSpec
from cardre.errors import PlanContainsUnavailableNodesError
from cardre.registry import NodeRegistry
from cardre.services.run_service import RunService


def _plan_with_deferred_node(store) -> str:
    project_id = store.create_project("test-project")
    plan_id = store.create_plan(project_id, "deferred-plan")
    steps = [
        StepSpec(
            step_id="gbdt",
            node_type="cardre.gradient_boosting_classifier",
            node_version="1",
            category="fit",
            parent_step_ids=[],
            params={},
            params_hash="",
            branch_label="",
            position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps, description="has deferred")
    return pv_id


class TestPreExecutionGate:
    def test_run_plan_rejects_deferred_node_before_run_row(self, store) -> None:
        pv_id = _plan_with_deferred_node(store)

        service = RunService(store)
        with pytest.raises(PlanContainsUnavailableNodesError) as exc:
            service.run_plan(plan_version_id=pv_id, run_scope="full_plan", sync=True)

        runs = store.list_runs(plan_version_id=pv_id)
        assert runs == [], "a run row was created despite the unavailable-node gate"

        assert exc.value.context["issues"][0]["node_type"] == "cardre.gradient_boosting_classifier"
        assert exc.value.context["issues"][0]["step_id"] == "gbdt"

    def test_executor_validate_plan_executability_lists_issues(self, store) -> None:
        from cardre.executor import PlanExecutor
        pv_id = _plan_with_deferred_node(store)

        executor = PlanExecutor(NodeRegistry.with_defaults())
        issues = executor.validate_plan_executability(store, pv_id)
        assert len(issues) == 1
        assert issues[0]["node_type"] == "cardre.gradient_boosting_classifier"
        assert issues[0]["available"] is False

    def test_clean_plan_has_no_issues(self, store) -> None:
        from cardre.executor import PlanExecutor
        project_id = store.create_project("test-project")
        plan_id = store.create_plan(project_id, "clean-plan")
        steps = [
            StepSpec(step_id="imp", node_type="cardre.import_dataset",
                     node_version="1", category="import", parent_step_ids=[], params={},
                     params_hash="", branch_label="", position=0),
        ]
        pv_id = store.create_plan_version(plan_id, steps, description="clean")
        executor = PlanExecutor(NodeRegistry.with_defaults())
        assert executor.validate_plan_executability(store, pv_id) == []
