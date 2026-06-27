"""Characterization tests for executor error classification.

Covers every category in _CATEGORY_MAP / _CODE_MAP that flows through
the _execute_step exception handler (lines 497-560 of executor.py).

NOTE: ParameterValidationError and ArtifactReadError are already
characterized by existing tests in test_executor.py:
  - test_structured_error_categories (RoleAccessError)
  - test_missing_artifact_file_fails_validation (ArtifactReadError)
  - test_artifact_hash_mismatch_fails_validation (ArtifactReadError)

GraphValidationError is raised before _execute_step (in _validate_topology)
and is NOT covered here.
"""

from __future__ import annotations

import pytest

from cardre.audit import ExecutionContext, NodeOutput, StepSpec, json_logical_hash
from cardre.executor import PlanExecutor
from cardre.errors import (
    CardreError,
    ArtifactWriteError,
    ContractViolationError,
    NodeExecutionError,
)
from cardre.nodes import DummyFitNode
from cardre.nodes.prep import ImportGermanCreditNode
from cardre.registry import NodeRegistry

from tests.test_executor import make_store, make_sample_german_credit_file


# ── Helper nodes that raise specific errors during run() ─────────────


class NoInputRolesNode(DummyFitNode):
    """DummyFitNode subclass with no input_roles, so it doesn't trigger
    RoleAccessError before the intended error."""
    node_type = "cardre.test.no_input_roles"
    input_roles = []


class RaiseNodeExecutionErrorNode(NoInputRolesNode):
    node_type = "cardre.test.node_execution_error"

    def run(self, context: ExecutionContext) -> NodeOutput:
        raise NodeExecutionError("Node execution failed intentionally")


class RaiseCardreErrorNode(NoInputRolesNode):
    node_type = "cardre.test.cardre_error"

    def run(self, context: ExecutionContext) -> NodeOutput:
        raise CardreError("Generic Cardre error")


class RaiseRuntimeErrorNode(NoInputRolesNode):
    node_type = "cardre.test.runtime_error"

    def run(self, context: ExecutionContext) -> NodeOutput:
        raise RuntimeError("Unhandled runtime error")


class RaiseContractViolationNode(NoInputRolesNode):
    node_type = "cardre.test.contract_violation"

    def run(self, context: ExecutionContext) -> NodeOutput:
        raise ContractViolationError("Contract violation")


class RaiseArtifactWriteErrorNode(NoInputRolesNode):
    node_type = "cardre.test.artifact_write_error"

    def run(self, context: ExecutionContext) -> NodeOutput:
        raise ArtifactWriteError("Artifact write failed")


# ── Error category test matrix ───────────────────────────────────────

ErrorScenario = tuple[str, str, str]


ERROR_SCENARIOS: list[ErrorScenario] = [
    (
        "ArtifactWriteError",
        "ARTIFACT_WRITE_ERROR",
        "node raises ArtifactWriteError during run",
    ),
    (
        "NodeExecutionError",
        "NODE_EXECUTION_ERROR",
        "node raises NodeExecutionError during run",
    ),
    (
        "ContractViolationError",
        "CONTRACT_VIOLATION_ERROR",
        "node raises ContractViolationError during run",
    ),
    (
        "CardreError",
        "CARDRE_ERROR",
        "node raises generic CardreError during run",
    ),
    (
        "InternalExecutionError",
        "STEP_FAILED",
        "node raises non-CardreError (RuntimeError)",
    ),
]


class TestExecutorErrorClassification:
    """Characterize every error category in _CATEGORY_MAP / _CODE_MAP."""

    @pytest.mark.parametrize(
        "expected_category,expected_code,scenario",
        ERROR_SCENARIOS,
        ids=[s[2].replace(" ", "_") for s in ERROR_SCENARIOS],
    )
    def test_error_category_and_code(
        self,
        expected_category: str,
        expected_code: str,
        scenario: str,
    ) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        reg = NodeRegistry()
        reg.register(ImportGermanCreditNode)

        if scenario == "node raises ArtifactWriteError during run":
            reg.register(RaiseArtifactWriteErrorNode)
            source = make_sample_german_credit_file(tmp)
            steps = [
                StepSpec(step_id="import", node_type="cardre.import_fixture_uci_german_credit",
                         node_version="1", category="transform",
                         params={"source_path": str(source)},
                         params_hash=json_logical_hash({"source_path": str(source)}),
                         parent_step_ids=[], branch_label="", position=0),
                StepSpec(step_id="fail-step", node_type="cardre.test.artifact_write_error",
                         node_version="1", category="fit",
                         params={}, params_hash=json_logical_hash({}),
                         parent_step_ids=["import"], branch_label="", position=1),
            ]
            pv_id = store.create_plan_version(plan_id, steps)
            executor = PlanExecutor(reg)
            run_id = executor.run_plan_version(store, pv_id)
            run = store.get_run(run_id)
            assert run["status"] == "failed"
            run_steps = store.get_run_steps(run_id)
            fail_step = [rs for rs in run_steps if rs.step_id == "fail-step"]
            assert len(fail_step) == 1
            error = fail_step[0].errors[0]

        elif scenario == "node raises NodeExecutionError during run":
            reg.register(RaiseNodeExecutionErrorNode)
            source = make_sample_german_credit_file(tmp)
            steps = [
                StepSpec(step_id="import", node_type="cardre.import_fixture_uci_german_credit",
                         node_version="1", category="transform",
                         params={"source_path": str(source)},
                         params_hash=json_logical_hash({"source_path": str(source)}),
                         parent_step_ids=[], branch_label="", position=0),
                StepSpec(step_id="fail-step", node_type="cardre.test.node_execution_error",
                         node_version="1", category="fit",
                         params={}, params_hash=json_logical_hash({}),
                         parent_step_ids=["import"], branch_label="", position=1),
            ]
            pv_id = store.create_plan_version(plan_id, steps)
            executor = PlanExecutor(reg)
            run_id = executor.run_plan_version(store, pv_id)
            run = store.get_run(run_id)
            assert run["status"] == "failed"
            run_steps = store.get_run_steps(run_id)
            fail_step = [rs for rs in run_steps if rs.step_id == "fail-step"]
            assert len(fail_step) == 1
            error = fail_step[0].errors[0]

        elif scenario == "node raises ContractViolationError during run":
            reg.register(RaiseContractViolationNode)
            source = make_sample_german_credit_file(tmp)
            steps = [
                StepSpec(step_id="import", node_type="cardre.import_fixture_uci_german_credit",
                         node_version="1", category="transform",
                         params={"source_path": str(source)},
                         params_hash=json_logical_hash({"source_path": str(source)}),
                         parent_step_ids=[], branch_label="", position=0),
                StepSpec(step_id="fail-step", node_type="cardre.test.contract_violation",
                         node_version="1", category="fit",
                         params={}, params_hash=json_logical_hash({}),
                         parent_step_ids=["import"], branch_label="", position=1),
            ]
            pv_id = store.create_plan_version(plan_id, steps)
            executor = PlanExecutor(reg)
            run_id = executor.run_plan_version(store, pv_id)
            run = store.get_run(run_id)
            assert run["status"] == "failed"
            run_steps = store.get_run_steps(run_id)
            fail_step = [rs for rs in run_steps if rs.step_id == "fail-step"]
            assert len(fail_step) == 1
            error = fail_step[0].errors[0]

        elif scenario == "node raises generic CardreError during run":
            reg.register(RaiseCardreErrorNode)
            source = make_sample_german_credit_file(tmp)
            steps = [
                StepSpec(step_id="import", node_type="cardre.import_fixture_uci_german_credit",
                         node_version="1", category="transform",
                         params={"source_path": str(source)},
                         params_hash=json_logical_hash({"source_path": str(source)}),
                         parent_step_ids=[], branch_label="", position=0),
                StepSpec(step_id="fail-step", node_type="cardre.test.cardre_error",
                         node_version="1", category="fit",
                         params={}, params_hash=json_logical_hash({}),
                         parent_step_ids=["import"], branch_label="", position=1),
            ]
            pv_id = store.create_plan_version(plan_id, steps)
            executor = PlanExecutor(reg)
            run_id = executor.run_plan_version(store, pv_id)
            run = store.get_run(run_id)
            assert run["status"] == "failed"
            run_steps = store.get_run_steps(run_id)
            fail_step = [rs for rs in run_steps if rs.step_id == "fail-step"]
            assert len(fail_step) == 1
            error = fail_step[0].errors[0]

        elif scenario == "node raises non-CardreError (RuntimeError)":
            reg.register(RaiseRuntimeErrorNode)
            source = make_sample_german_credit_file(tmp)
            steps = [
                StepSpec(step_id="import", node_type="cardre.import_fixture_uci_german_credit",
                         node_version="1", category="transform",
                         params={"source_path": str(source)},
                         params_hash=json_logical_hash({"source_path": str(source)}),
                         parent_step_ids=[], branch_label="", position=0),
                StepSpec(step_id="fail-step", node_type="cardre.test.runtime_error",
                         node_version="1", category="fit",
                         params={}, params_hash=json_logical_hash({}),
                         parent_step_ids=["import"], branch_label="", position=1),
            ]
            pv_id = store.create_plan_version(plan_id, steps)
            executor = PlanExecutor(reg)
            run_id = executor.run_plan_version(store, pv_id)
            run = store.get_run(run_id)
            assert run["status"] == "failed"
            run_steps = store.get_run_steps(run_id)
            fail_step = [rs for rs in run_steps if rs.step_id == "fail-step"]
            assert len(fail_step) == 1
            error = fail_step[0].errors[0]

        else:
            pytest.fail(f"Unknown scenario: {scenario}")

        assert error["category"] == expected_category, (
            f"Scenario {scenario!r}: expected category={expected_category!r}, "
            f"got {error['category']!r}"
        )
        assert error["code"] == expected_code, (
            f"Scenario {scenario!r}: expected code={expected_code!r}, "
            f"got {error['code']!r}"
        )
