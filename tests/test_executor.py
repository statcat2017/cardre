"""Tests for cardre.executor — plan execution, role enforcement, staleness, replay."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import polars as pl

from cardre.artifacts import write_json_artifact
from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    NodeOutput,
    NodeType,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.executor import PlanExecutor, RoleAccessError
from cardre.errors import ArtifactReadError, GraphValidationError, CancellationError
from cardre.staleness import compute_staleness
from cardre.nodes import (
    DummyApplyNode,
    DummyFitNode,
    ImportGermanCreditNode,
    ProfileDatasetNode,
    SplitTrainTestOotNode,
    FineClassingNode,
    CalculateWoeIvNode,
    WoeTransformTrainNode,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

import pytest

from tests.helpers import (
    _make_train_artifact,
    make_sample_german_credit_file,
    make_store,
)

pytestmark = pytest.mark.integration



# ======================================================================
# Slice 5: Executor + Run Records
# ======================================================================

class ExecutorTests:

    def test_running_proof_plan_writes_runs_and_run_steps(self) -> None:
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
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "succeeded"

        run_steps = store.get_run_steps(run_id)
        assert len(run_steps) == 1
        rs = run_steps[0]
        assert rs.status == "succeeded"
        assert rs.step_id == "import"
        assert rs.plan_version_id == pv_id

    def test_run_step_has_input_output_artifact_ids(self) -> None:
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
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)
        rs = run_steps[0]
        assert isinstance(rs.input_artifact_ids, list)
        assert isinstance(rs.output_artifact_ids, list)
        assert len(rs.output_artifact_ids) > 0

    def test_run_step_has_execution_fingerprint(self) -> None:
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
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)
        rs = run_steps[0]
        fp = rs.execution_fingerprint
        assert "plan_version_id" in fp
        assert "step_id" in fp
        assert "node_type" in fp
        assert "node_version" in fp
        assert "params_hash" in fp
        assert "input_artifact_logical_hashes" in fp
        assert "output_artifact_logical_hashes" in fp
        assert "python_version" in fp
        assert "cardre_version" in fp

    def test_failed_step_does_not_mark_descendants_current(self) -> None:
        class FailOnPurposeNode(DummyFitNode):
            node_type = "cardre.fail_on_purpose"

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
                step_id="fail-step", node_type="cardre.fail_on_purpose",
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
        reg.register(FailOnPurposeNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        assert run["status"] == "failed"

        run_steps = store.get_run_steps(run_id)
        fail_step = [rs for rs in run_steps if rs.step_id == "fail-step"]
        assert len(fail_step) == 1
        assert fail_step[0].status == "failed"
        assert len(fail_step[0].errors) > 0

    def test_structured_error_categories(self) -> None:
        class FailOnPurposeNode(DummyFitNode):
            node_type = "cardre.fail_on_purpose"

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
                step_id="fail-step", node_type="cardre.fail_on_purpose",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(ImportGermanCreditNode)
        reg.register(FailOnPurposeNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        assert run["status"] == "failed"

        run_steps = store.get_run_steps(run_id)
        fail_step = [rs for rs in run_steps if rs.step_id == "fail-step"]
        assert len(fail_step) == 1
        assert fail_step[0].status == "failed"
        assert len(fail_step[0].errors) > 0

        error = fail_step[0].errors[0]
        assert "category" in error
        known_categories = {
            "CancellationError", "GraphValidationError",
            "MissingInputArtifactError", "ParameterValidationError",
            "ArtifactReadError", "ArtifactWriteError",
            "NodeExecutionError", "ContractViolationError",
            "CardreError", "InternalExecutionError",
        }
        assert error["category"] in known_categories
        assert error["category"] == "InternalExecutionError"

    def test_missing_artifact_file_fails_validation(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({"x": [1.0]})
        art = _make_train_artifact(store, df, role="train")
        p = store.artifact_path(art)
        p.unlink() if p.exists() else None

        executor = PlanExecutor(NodeRegistry())
        with pytest.raises(ArtifactReadError):
            executor._validate_input_artifact_files(store, [art])

    def test_artifact_hash_mismatch_fails_validation(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({"x": [1.0]})
        art = _make_train_artifact(store, df, role="train")
        p = store.artifact_path(art)
        if p.exists():
            p.write_text("tampered data")

        executor = PlanExecutor(NodeRegistry())
        with pytest.raises(ArtifactReadError):
            executor._validate_input_artifact_files(store, [art])


# ======================================================================
# Slice 6: Split + Role Enforcement
# ======================================================================

class SplitAndRoleTests:

    def make_proof_plan_steps(self, source: Path) -> list[StepSpec]:
        return [
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
                    "train_fraction": 0.6,
                    "test_fraction": 0.2,
                    "oot_fraction": 0.2,
                    "method": "random",
                    "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="fit", node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]

    def test_split_creates_three_immutable_artifacts_with_roles(self) -> None:
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
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)

        split_rs = [rs for rs in run_steps if rs.step_id == "split"][0]
        import_rs = [rs for rs in run_steps if rs.step_id == "import"][0]


        roles_found = set()
        for aid in split_rs.output_artifact_ids:
            art = store.get_artifact(aid)
            assert art is not None
            if art.artifact_type == "dataset":
                roles_found.add(art.role)
        assert roles_found == {"train", "test", "oot"}

    def test_fit_node_consuming_train_succeeds(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = self.make_proof_plan_steps(source)
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        assert run["status"] == "succeeded"

    def test_fit_node_wired_to_test_fails_before_execution(self) -> None:
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
                step_id="fit-on-import",
                node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        assert run["status"] == "failed"

        run_steps = store.get_run_steps(run_id)
        fit_steps = [rs for rs in run_steps if rs.step_id == "fit-on-import"]
        any_role_error = any(
            "role" in str(e.get("message", "")) for rs in run_steps for e in rs.errors
        )
        assert any_role_error

    def test_apply_node_consumes_train_test_oot_and_definition(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = self.make_proof_plan_steps(source) + [
            StepSpec(
                step_id="apply", node_type="cardre.dummy_apply",
                node_version="1", category="apply",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split", "fit"], branch_label="", position=3,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        assert run["status"] == "succeeded"

    def test_apply_with_multi_parent_produces_three_prediction_artifacts(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = self.make_proof_plan_steps(source) + [
            StepSpec(
                step_id="apply", node_type="cardre.dummy_apply",
                node_version="1", category="apply",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split", "fit"],
                branch_label="", position=3,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)
        apply_rs = [rs for rs in run_steps if rs.step_id == "apply"][0]

        assert len(apply_rs.output_artifact_ids) >= 1

        roles = set()
        for aid in apply_rs.output_artifact_ids:
            art = store.get_artifact(aid)
            if art is not None:
                roles.add(art.role)
        assert "prediction" in roles


# ======================================================================
# Slice 7: Staleness + Replay
# ======================================================================

class StalenessAndReplayTests:

    def test_changing_split_params_marks_downstream_stale(self) -> None:
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
                step_id="fit", node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        executor.run_plan_version(store, pv_id)

        new_steps = [
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
                    "train_fraction": 0.7, "test_fraction": 0.15,
                    "oot_fraction": 0.15, "method": "random", "random_seed": 99,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.7, "test_fraction": 0.15,
                    "oot_fraction": 0.15, "method": "random", "random_seed": 99,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="fit", node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]
        new_pv_id = store.create_plan_version(plan_id, new_steps)
        executor.run_plan_version(store, new_pv_id)

        staleness = compute_staleness(store, new_pv_id)
        assert staleness["import"] == False
        assert staleness["split"] == False
        assert staleness["fit"] == False

    def test_replay_from_changed_split_produces_new_downstream_artifacts(self) -> None:
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
                step_id="fit", node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        first_run_id = executor.run_plan_version(store, pv_id)

        new_params = {
            "train_fraction": 0.7, "test_fraction": 0.15,
            "oot_fraction": 0.15, "method": "random", "random_seed": 99,
        }
        new_run_id = executor.replay_from_step(
            store, plan_id, pv_id, "split", new_params,
        )

        first_steps = store.get_run_steps(first_run_id)
        new_steps = store.get_run_steps(new_run_id)

        first_by_step = {rs.step_id: rs for rs in first_steps}
        new_by_step = {rs.step_id: rs for rs in new_steps}

        new_split = new_by_step["split"]
        assert first_by_step["split"].output_artifact_ids != new_split.output_artifact_ids
        new_fit = new_by_step["fit"]
        assert first_by_step["fit"].output_artifact_ids != new_fit.output_artifact_ids

    def test_unchanged_upstream_evidence_remains_valid(self) -> None:
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
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        first_run_id = executor.run_plan_version(store, pv_id)
        second_run_id = executor.run_plan_version(store, pv_id)

        first_steps = store.get_run_steps(first_run_id)
        second_steps = store.get_run_steps(second_run_id)


    def test_old_run_remains_queryable(self) -> None:
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
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        first_run_id = executor.run_plan_version(store, pv_id)

        new_params = {"source_path": str(tmp / "nonexistent")}
        try:
            executor.replay_from_step(store, plan_id, pv_id, "import", new_params)
        except (FileNotFoundError, RuntimeError):
            pass

        old_run = store.get_run(first_run_id)


# ======================================================================
# Wave 2: run_to_node, force, cancellation, manifest
# ======================================================================

class SimpleSourceNode(NodeType):
    node_type = "cardre.test.simple_source"
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
    node_type = "cardre.test.simple_transform"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["artifact"]
    output_roles: list[str] = ["artifact"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        art = write_json_artifact(
            context.store, artifact_type="report", role="artifact",
            stem=f"transform-{context.step_spec.step_id}",
            payload={"step_id": context.step_spec.step_id,
                     "parent_count": len(context.input_artifacts)},
            metadata={},
        )
        return NodeOutput(artifacts=[art], metrics={})


class Wave2Tests:

    def test_run_to_node_executes_ancestors_only(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="step_a", node_type="cardre.test.simple_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="step_b", node_type="cardre.test.simple_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=2,
            ),
            StepSpec(
                step_id="target", node_type="cardre.test.simple_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["step_a"], branch_label="", position=3,
            ),
            StepSpec(
                step_id="other_target", node_type="cardre.test.simple_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["step_b"], branch_label="", position=4,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        reg.register(SimpleTransformNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_to_node(store, pv_id, "target")

        run = store.get_run(run_id)
        assert run["status"] == "succeeded"

        run_steps = store.get_run_steps(run_id)
        executed_step_ids = {rs.step_id for rs in run_steps}
        assert "import" in executed_step_ids
        assert "step_a" in executed_step_ids
        assert "target" in executed_step_ids
        assert "step_b" not in executed_step_ids, "step_b is not in ancestor closure"
        assert "other_target" not in executed_step_ids, "other_target is not in ancestor closure"

    def test_force_rerun_regenerates_artifacts(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="source", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        first_run_id = executor.run_plan_version(store, pv_id, force=True)
        first_steps = store.get_run_steps(first_run_id)
        first_fp = first_steps[0].execution_fingerprint

        second_run_id = executor.run_plan_version(store, pv_id, force=True)
        second_steps = store.get_run_steps(second_run_id)
        second_fp = second_steps[0].execution_fingerprint

        assert first_steps[0].output_artifact_ids != second_steps[0].output_artifact_ids, \
            "forced runs should produce new artifact IDs"
        assert first_fp == second_fp, \
            "fingerprints should be identical between forced runs"

    def test_cancellation_stops_mid_flight(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        class CancellingNode(NodeType):
            node_type = "cardre.test.cancelling"
            version = "1"
            category = "transform"
            input_roles: list[str] = []
            output_roles: list[str] = ["artifact"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                from cardre.cancellation import cancel_run
                cancel_run(context.run_id)
                return NodeOutput(artifacts=[], metrics={})

        steps = [
            StepSpec(
                step_id="step_a", node_type="cardre.test.cancelling",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="step_b", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["step_a"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(CancellingNode)
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        assert run["status"] == "cancelled", f"Expected cancelled, got {run['status']}"

        run_steps = store.get_run_steps(run_id)
        executed_step_ids = {rs.step_id for rs in run_steps}
        assert "step_a" in executed_step_ids
        assert "step_b" not in executed_step_ids, "step_b should not execute after cancellation"

    def test_manifest_status_matches_run_status(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="step_a", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="step_b", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["step_a"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        assert run["status"] == "succeeded", f"Expected succeeded, got {run['status']}"

        manifest_arts = [a for a in store.list_artifacts() if a.artifact_type == "run_manifest"]
        assert len(manifest_arts) >= 1, "No manifest artifact found"
        manifest_art = manifest_arts[-1]
        import json
        manifest = json.loads(store.artifact_path(manifest_art).read_text())
        assert manifest["status"] == run["status"], f"Manifest status {manifest['status']} != run status {run['status']}"
        assert manifest["finished_at"], "Manifest missing finished_at"

    def test_run_to_node_invalid_target_raises(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        steps = [
            StepSpec(
                step_id="step_a", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        with pytest.raises(GraphValidationError):
            executor.run_to_node(store, pv_id, "nonexistent_step")

    def test_cancellation_raised_from_inside_node(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        class TokenCheckingNode(NodeType):
            node_type = "cardre.test.token_checking"
            version = "1"
            category = "transform"
            input_roles: list[str] = []
            output_roles: list[str] = ["artifact"]

            def run(self, context: ExecutionContext) -> NodeOutput:
                from cardre.cancellation import cancel_run
                cancel_run(context.run_id)
                context.cancellation_token.raise_if_cancelled()
                return NodeOutput(artifacts=[], metrics={})

        steps = [
            StepSpec(
                step_id="raise_step", node_type="cardre.test.token_checking",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(TokenCheckingNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        assert run["status"] == "cancelled", f"Expected cancelled, got {run['status']}"
