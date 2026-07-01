"""Characterization tests for PlanExecutor — lock behaviour before refactor.

These tests must pass against the unrefactored executor AND after all
extractions. They serve as the behaviour contract.
"""
from __future__ import annotations

from cardre.artifacts import write_json_artifact
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    StepSpec,
    json_logical_hash,
)
from cardre.executor import PlanExecutor
from cardre.nodes import DummyFitNode
from cardre.nodes.prep import ImportGermanCreditNode, SplitTrainTestOotNode
from cardre.registry import NodeRegistry

from tests.helpers import make_store, make_sample_german_credit_file


class TestFailedStepEvidence:
    """C1: Failed step records resolved input artifact IDs and structured errors."""

    def test_failed_step_records_resolved_input_evidence(self):
        class FailWithInputsNode(DummyFitNode):
            node_type = "cardre.test.fail_with_inputs"

            def run(self, context: ExecutionContext) -> NodeOutput:
                raise RuntimeError("Intentional failure")

        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_fixture_uci_german_credit",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="1", category="transform",
                params={
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="failing", node_type="cardre.test.fail_with_inputs",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(ImportGermanCreditNode)
        reg.register(SplitTrainTestOotNode)
        reg.register(FailWithInputsNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        assert run["status"] == "failed"

        run_steps = store.get_run_steps(run_id)
        failing = next(s for s in run_steps if s.step_id == "failing")
        assert failing.status == "failed"
        assert failing.input_artifact_ids, "Failed step should record resolved input artifacts"
        assert failing.errors, "Failed step should have error entries"
        assert failing.errors[0]["code"]
        assert failing.errors[0]["message"]
        assert failing.errors[0]["traceback"]
        assert failing.errors[0]["category"]


class TestRoleAccess:
    """C2: Role access error when parent outputs have no matching role."""

    def test_role_access_error_when_parent_outputs_have_no_matching_role(self):
        class TestRoleSource(NodeType):
            node_type = "cardre.test.role_source"
            version = "1"
            category = "transform"
            input_roles: list[str] = []
            output_roles: list[str] = ["test"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                art = write_json_artifact(
                    context.store, artifact_type="dataset", role="test",
                    stem="test-art", payload={"x": 1}, metadata={},
                )
                return NodeOutput(artifacts=[art], metrics={})

        class TestRoleChild(NodeType):
            node_type = "cardre.test.role_child"
            version = "1"
            category = "apply"
            input_roles: list[str] = ["train"]
            output_roles: list[str] = ["prediction"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                return NodeOutput(artifacts=[], metrics={})

        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="parent", node_type="cardre.test.role_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="child", node_type="cardre.test.role_child",
                node_version="1", category="apply",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["parent"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(TestRoleSource)
        reg.register(TestRoleChild)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        assert run["status"] == "failed"

        run_steps = store.get_run_steps(run_id)
        child = next(s for s in run_steps if s.step_id == "child")
        assert child.errors[0]["code"] == "ROLE_ACCESS_ERROR"
        assert child.errors[0]["category"] == "RoleAccessError"


class TestLeakageProtection:
    """C3: Leakage protection blocks test/OOT datasets for fit/selection/refinement nodes."""

    def test_leakage_protection_blocks_test_dataset_for_fit_node(self):
        class TestLeakageSource(NodeType):
            node_type = "cardre.test.leakage_source"
            version = "1"
            category = "transform"
            input_roles: list[str] = []
            output_roles: list[str] = ["test"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                art = write_json_artifact(
                    context.store, artifact_type="dataset", role="test",
                    stem="leakage-test", payload={"x": 1}, metadata={},
                )
                return NodeOutput(artifacts=[art], metrics={})

        class TestLeakageFit(NodeType):
            node_type = "cardre.test.leakage_fit"
            version = "1"
            category = "fit"
            input_roles: list[str] = ["train", "test"]
            output_roles: list[str] = ["prediction"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                return NodeOutput(artifacts=[], metrics={})

        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="source", node_type="cardre.test.leakage_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="fit", node_type="cardre.test.leakage_fit",
                node_version="1", category="fit",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["source"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(TestLeakageSource)
        reg.register(TestLeakageFit)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        assert run["status"] == "failed"

        run_steps = store.get_run_steps(run_id)
        fit = next(s for s in run_steps if s.step_id == "fit")
        assert fit.errors[0]["code"] == "LEAKAGE_PROTECTION_ERROR"
        assert fit.errors[0]["category"] == "LeakageProtectionError"


class TestFingerprintContract:
    """C4: Execution fingerprint contract remains stable."""

    def test_execution_fingerprint_contract_for_successful_step(self):
        class FpSourceNode(NodeType):
            node_type = "cardre.test.fp_source"
            version = "1"
            category = "transform"
            input_roles: list[str] = []
            output_roles: list[str] = ["artifact"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                art = write_json_artifact(
                    context.store, artifact_type="report", role="artifact",
                    stem="fp-src", payload={}, metadata={},
                )
                return NodeOutput(artifacts=[art], metrics={})

        class FpChildNode(NodeType):
            node_type = "cardre.test.fp_child"
            version = "1"
            category = "transform"
            input_roles: list[str] = ["artifact"]
            output_roles: list[str] = ["artifact"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                art = write_json_artifact(
                    context.store, artifact_type="report", role="artifact",
                    stem="fp-child", payload={}, metadata={},
                )
                return NodeOutput(artifacts=[art], metrics={})

        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="source", node_type="cardre.test.fp_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="child", node_type="cardre.test.fp_child",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["source"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(FpSourceNode)
        reg.register(FpChildNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run_steps = store.get_run_steps(run_id)
        child = next(s for s in run_steps if s.step_id == "child")
        fp = child.execution_fingerprint

        assert fp["plan_version_id"] == pv_id
        assert fp["step_id"] == "child"
        assert fp["node_type"] == "cardre.test.fp_child"
        assert fp["node_version"] == "1"
        assert fp["params_hash"] == json_logical_hash({})
        assert isinstance(fp["parent_run_step_ids"], list)
        assert len(fp["parent_run_step_ids"]) == 1
        assert isinstance(fp["input_artifact_logical_hashes"], list)
        assert isinstance(fp["output_artifact_logical_hashes"], list)
        assert len(fp["output_artifact_logical_hashes"]) == 1
        assert "source" in fp["parent_output_logical_hashes_by_step"]
        assert isinstance(fp["parent_output_logical_hashes_by_step"]["source"], list)
        assert fp["python_version"].startswith("3.")
        assert fp["cardre_version"] == "0.1.0"


class TestToNodeAncestorClosure:
    """C5: To-node run executes only target ancestor closure."""

    def test_run_to_node_executes_only_target_ancestor_closure(self):
        class TnSourceNode(NodeType):
            node_type = "cardre.test.tn_source"
            version = "1"
            category = "transform"
            input_roles: list[str] = []
            output_roles: list[str] = ["artifact"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                art = write_json_artifact(
                    context.store, artifact_type="report", role="artifact",
                    stem=f"tn-{context.step_spec.step_id}",
                    payload={"step_id": context.step_spec.step_id},
                    metadata={},
                )
                return NodeOutput(artifacts=[art], metrics={})

        class TnTransformNode(NodeType):
            node_type = "cardre.test.tn_transform"
            version = "1"
            category = "transform"
            input_roles: list[str] = ["artifact"]
            output_roles: list[str] = ["artifact"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                art = write_json_artifact(
                    context.store, artifact_type="report", role="artifact",
                    stem=f"tn-{context.step_spec.step_id}",
                    payload={"step_id": context.step_spec.step_id,
                             "parent_count": len(context.input_artifacts)},
                    metadata={},
                )
                return NodeOutput(artifacts=[art], metrics={})

        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.test.tn_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="step_a", node_type="cardre.test.tn_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="step_b", node_type="cardre.test.tn_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=2,
            ),
            StepSpec(
                step_id="target", node_type="cardre.test.tn_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["step_a"], branch_label="", position=3,
            ),
            StepSpec(
                step_id="other_target", node_type="cardre.test.tn_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["step_b"], branch_label="", position=4,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(TnSourceNode)
        reg.register(TnTransformNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_to_node(store, pv_id, "target")

        run = store.get_run(run_id)
        assert run["status"] == "succeeded"

        executed = {s.step_id for s in store.get_run_steps(run_id)}
        assert "import" in executed
        assert "step_a" in executed
        assert "target" in executed
        assert "step_b" not in executed
        assert "other_target" not in executed


class TestReplay:
    """C6: Replay reuses unaffected steps and executes affected descendants."""

    def test_replay_from_step_reuses_unaffected_and_executes_affected(self):
        class RpSourceNode(NodeType):
            node_type = "cardre.test.rp_source"
            version = "1"
            category = "transform"
            input_roles: list[str] = []
            output_roles: list[str] = ["artifact"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                art = write_json_artifact(
                    context.store, artifact_type="report", role="artifact",
                    stem=f"rp-{context.step_spec.step_id}",
                    payload={"step_id": context.step_spec.step_id},
                    metadata={},
                )
                return NodeOutput(artifacts=[art], metrics={})

        class RpTransformNode(NodeType):
            node_type = "cardre.test.rp_transform"
            version = "1"
            category = "transform"
            input_roles: list[str] = ["artifact"]
            output_roles: list[str] = ["artifact"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                art = write_json_artifact(
                    context.store, artifact_type="report", role="artifact",
                    stem=f"rp-{context.step_spec.step_id}",
                    payload={"step_id": context.step_spec.step_id,
                             "parent_count": len(context.input_artifacts)},
                    metadata={},
                )
                return NodeOutput(artifacts=[art], metrics={})

        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="unaffected-upstream", node_type="cardre.test.rp_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="changed", node_type="cardre.test.rp_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["unaffected-upstream"],
                branch_label="", position=1,
            ),
            StepSpec(
                step_id="changed-descendant", node_type="cardre.test.rp_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["changed"], branch_label="", position=2,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(RpSourceNode)
        reg.register(RpTransformNode)
        executor = PlanExecutor(reg)

        original_run_id = executor.run_plan_version(store, pv_id)

        new_params = {"k": "v"}
        new_run_id = executor.replay_from_step(
            store, plan_id, pv_id, "changed", new_params,
        )

        replay_steps = store.get_run_steps(new_run_id)
        reused = [s for s in replay_steps
                   if s.execution_fingerprint.get("cardre_step_carried_forward")]
        executed = [s for s in replay_steps
                    if not s.execution_fingerprint.get("cardre_step_carried_forward")]

        assert any(s.step_id == "unaffected-upstream" for s in reused)
        assert any(s.step_id == "changed" for s in executed)
        assert any(s.step_id == "changed-descendant" for s in executed)

        for rs in reused:
            assert rs.execution_fingerprint.get("carried_forward_from_run_step_id")
            assert rs.execution_fingerprint.get("carried_forward_from_run_id") == original_run_id
