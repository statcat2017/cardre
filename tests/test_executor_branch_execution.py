"""Characterization tests for PlanExecutor.run_branch — shared evidence reuse."""

from __future__ import annotations

from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    StepSpec,
    json_logical_hash,
)
from cardre.artifacts import write_json_artifact
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

import pytest

from tests.helpers import make_store


pytestmark = pytest.mark.integration


class SimpleSourceNode(NodeType):
    node_type = "cardre.test.branch_source"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["artifact"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        art = write_json_artifact(
            context.store, artifact_type="report", role="artifact",
            stem=f"source-{context.step_spec.step_id}",
            payload={"step_id": context.step_spec.step_id},
            metadata={},
        )
        return NodeOutput(artifacts=[art], metrics={})


class SimpleTransformNode(NodeType):
    node_type = "cardre.test.branch_transform"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["artifact"]
    output_roles: list[str] = ["artifact"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        art = write_json_artifact(
            context.store, artifact_type="report", role="artifact",
            stem=f"transform-{context.step_spec.step_id}",
            payload={
                "step_id": context.step_spec.step_id,
                "parent_count": len(context.input_artifacts),
            },
            metadata={},
        )
        return NodeOutput(artifacts=[art], metrics={})


class TestBranchExecution:
    """PlanExecutor.run_branch shares upstream evidence correctly."""

    def test_shared_upstream_evidence_is_reused(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        shared_step = StepSpec(
            step_id="shared_source", node_type="cardre.test.branch_source",
            node_version="1", category="transform",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        )
        branch_step = StepSpec(
            step_id="branch_transform", node_type="cardre.test.branch_transform",
            node_version="1", category="transform",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=["shared_source"], branch_label="", position=1,
        )
        steps = [shared_step, branch_step]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        reg.register(SimpleTransformNode)
        executor = PlanExecutor(reg)

        # Full plan run to establish shared upstream evidence
        full_run_id = executor.run_plan_version(store, pv_id)
        assert store.get_run(full_run_id)["status"] == "succeeded"
        full_steps = store.get_run_steps(full_run_id)
        full_shared = next(rs for rs in full_steps if rs.step_id == "shared_source")

        # Create branch with shared upstream + branch-owned steps
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id, name="test-branch",
            branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="shared_source", step_id="shared_source",
            is_shared_upstream=True, is_branch_owned=False,
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="branch_transform", step_id="branch_transform",
            is_shared_upstream=False, is_branch_owned=True,
        )

        # Branch run (force to bypass staleness short-circuit)
        branch_run_id = executor.run_branch(store, pv_id, branch_id, force=True)
        assert store.get_run(branch_run_id)["status"] == "succeeded"
        branch_steps = store.get_run_steps(branch_run_id)

        # 1. Shared upstream step must NOT be re-executed
        branch_step_ids = {rs.step_id for rs in branch_steps}
        assert "shared_source" not in branch_step_ids, \
            "shared upstream should not be re-executed during branch run"

        # 2. Branch-owned step must be executed and consume shared evidence
        branch_transform = next(
            rs for rs in branch_steps if rs.step_id == "branch_transform"
        )
        assert branch_transform.status == "succeeded"
        assert set(branch_transform.input_artifact_ids) == set(full_shared.output_artifact_ids), \
            "branch-owned step must consume shared upstream output artifacts"
