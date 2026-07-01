"""Tests for cardre.evidence_locator — consolidated evidence lookup policies."""

from __future__ import annotations

from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    StepSpec,
    json_logical_hash,
)
from cardre.artifacts import write_json_artifact
from cardre.evidence_locator import (
    latest_successful_run_id,
    latest_successful_run_step,
    collect_run_steps_for_plan_version,
)
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry


from tests.helpers import make_store


class SimpleSource(NodeType):
    node_type = "cardre.test.evidence_source"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["artifact"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        art = write_json_artifact(
            context.store, artifact_type="report", role="artifact",
            stem=f"src-{context.step_spec.step_id}",
            payload={"step_id": context.step_spec.step_id},
            metadata={},
        )
        return NodeOutput(artifacts=[art], metrics={})


class TestEvidenceLocator:
    """Characterize evidence lookup policies against real run records."""

    def test_latest_run_id_returns_run(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="source", node_type="cardre.test.evidence_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSource)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        assert store.get_run(run_id)["status"] == "succeeded"

        found = latest_successful_run_id(store, pv_id)
        assert found == run_id

    def test_latest_run_step_none_when_no_run(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], "empty")

        rs = latest_successful_run_step(store, pv_id, "nonexistent")
        assert rs is None

    def test_collect_run_steps_empty_when_no_run(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], "empty")

        steps = collect_run_steps_for_plan_version(store, pv_id)
        assert steps == {}

    def test_branch_lookup_falls_back_to_full_plan(self) -> None:
        """Branch-scoped ``latest_successful_run_step`` falls back to
        full-plan evidence when no branch-specific run exists."""
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="source", node_type="cardre.test.evidence_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSource)
        executor = PlanExecutor(reg)

        # Full-plan run (no branch)
        executor.run_plan_version(store, pv_id)

        # Look up with a branch_id that has no branch-specific run —
        # should fall back to the full-plan evidence
        rs = latest_successful_run_step(store, pv_id, "source", branch_id="nonexistent")
        assert rs is not None
        assert rs.step_id == "source"
        assert rs.status == "succeeded"

    def test_collect_run_steps_merges_full_plan_when_branch_missing(self) -> None:
        """``collect_run_steps_for_plan_version`` with a branch_id that
        has no branch-specific run returns the full-plan run steps."""
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="source", node_type="cardre.test.evidence_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSource)
        executor = PlanExecutor(reg)

        executor.run_plan_version(store, pv_id)

        rs_by_step = collect_run_steps_for_plan_version(
            store, pv_id, branch_id="nonexistent",
        )
        assert "source" in rs_by_step
        assert rs_by_step["source"].status == "succeeded"

    def test_latest_successful_run_id_falls_back_across_plans(self) -> None:
        """When no run exists for the exact plan_version_id, fall back
        to a run in an earlier plan version."""
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="source", node_type="cardre.test.evidence_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv1_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSource)
        executor = PlanExecutor(reg)

        executor.run_plan_version(store, pv1_id)

        # Create a second plan version with no run
        pv2_id = store.create_plan_version(plan_id, steps)

        # Looking up the new plan version should find the old version's run
        found = latest_successful_run_id(store, pv2_id)
        assert found is not None  # fell back to plan-level run
