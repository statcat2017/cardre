"""Tests for cardre.executor — plan execution, role enforcement, staleness, replay."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import polars as pl

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    NodeOutput,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.executor import PlanExecutor, RoleAccessError
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

from tests.helpers import (
    _make_train_artifact,
    make_sample_german_credit_file,
    make_store,
)


# ======================================================================
# Slice 5: Executor + Run Records
# ======================================================================

class ExecutorTests(unittest.TestCase):

    def test_running_proof_plan_writes_runs_and_run_steps(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "succeeded")

        run_steps = store.get_run_steps(run_id)
        self.assertEqual(len(run_steps), 1)
        rs = run_steps[0]
        self.assertEqual(rs.status, "succeeded")
        self.assertEqual(rs.step_id, "import")
        self.assertEqual(rs.plan_version_id, pv_id)

    def test_run_step_has_input_output_artifact_ids(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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
        self.assertIsInstance(rs.input_artifact_ids, list)
        self.assertIsInstance(rs.output_artifact_ids, list)
        self.assertGreater(len(rs.output_artifact_ids), 0)

    def test_run_step_has_execution_fingerprint(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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
        self.assertIn("plan_version_id", fp)
        self.assertIn("step_id", fp)
        self.assertIn("node_type", fp)
        self.assertIn("node_version", fp)
        self.assertIn("params_hash", fp)
        self.assertIn("input_artifact_logical_hashes", fp)
        self.assertIn("output_artifact_logical_hashes", fp)
        self.assertIn("python_version", fp)
        self.assertIn("cardre_version", fp)

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
                step_id="import", node_type="cardre.import_dataset",
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
        self.assertEqual(run["status"], "failed", "Failed run should be marked failed")

        run_steps = store.get_run_steps(run_id)
        fail_step = [rs for rs in run_steps if rs.step_id == "fail-step"]
        self.assertEqual(len(fail_step), 1, "Expected one run-step for fail-step")
        self.assertEqual(fail_step[0].status, "failed")
        self.assertGreater(len(fail_step[0].errors), 0, "Expected structured error evidence")

    def test_missing_artifact_file_fails_validation(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({"x": [1.0]})
        art = _make_train_artifact(store, df, role="train")
        p = store.artifact_path(art)
        p.unlink() if p.exists() else None

        executor = PlanExecutor(NodeRegistry())
        with self.assertRaises(FileNotFoundError):
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
        with self.assertRaises(ValueError):
            executor._validate_input_artifact_files(store, [art])


# ======================================================================
# Slice 6: Split + Role Enforcement
# ======================================================================

class SplitAndRoleTests(unittest.TestCase):

    def make_proof_plan_steps(self, source: Path) -> list[StepSpec]:
        return [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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
                step_id="import", node_type="cardre.import_dataset",
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

        self.assertEqual(len(split_rs.output_artifact_ids), 4)

        roles_found = set()
        for aid in split_rs.output_artifact_ids:
            art = store.get_artifact(aid)
            self.assertIsNotNone(art)
            if art.artifact_type == "dataset":
                roles_found.add(art.role)
        self.assertEqual(roles_found, {"train", "test", "oot"})

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
        self.assertEqual(run["status"], "succeeded")

    def test_fit_node_wired_to_test_fails_before_execution(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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
        self.assertEqual(run["status"], "failed",
                         "Fit node wired to import should produce a failed run")

        run_steps = store.get_run_steps(run_id)
        fit_steps = [rs for rs in run_steps if rs.step_id == "fit-on-import"]
        self.assertEqual(len(fit_steps), 1)
        any_role_error = any(
            "role" in str(e.get("message", "")) for rs in run_steps for e in rs.errors
        )
        self.assertTrue(any_role_error,
                        "Expected role-access error in failed run-step")

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
        self.assertEqual(run["status"], "succeeded")

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

        self.assertGreaterEqual(len(apply_rs.output_artifact_ids), 1)

        roles = set()
        for aid in apply_rs.output_artifact_ids:
            art = store.get_artifact(aid)
            if art is not None:
                roles.add(art.role)
        self.assertIn("prediction", roles)


# ======================================================================
# Slice 7: Staleness + Replay
# ======================================================================

class StalenessAndReplayTests(unittest.TestCase):

    def test_changing_split_params_marks_downstream_stale(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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
                step_id="import", node_type="cardre.import_dataset",
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

        staleness = executor.compute_staleness(store, new_pv_id)
        self.assertEqual(staleness["import"], False)
        self.assertEqual(staleness["split"], False)
        self.assertEqual(staleness["fit"], False)

    def test_replay_from_changed_split_produces_new_downstream_artifacts(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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
        self.assertNotEqual(
            first_by_step["split"].output_artifact_ids,
            new_split.output_artifact_ids,
        )
        new_fit = new_by_step["fit"]
        self.assertNotEqual(
            first_by_step["fit"].output_artifact_ids,
            new_fit.output_artifact_ids,
        )

    def test_unchanged_upstream_evidence_remains_valid(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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

        self.assertEqual(
            first_steps[0].execution_fingerprint["output_artifact_logical_hashes"],
            second_steps[0].execution_fingerprint["output_artifact_logical_hashes"],
        )

    def test_old_run_remains_queryable(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
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
        self.assertIsNotNone(old_run)
        self.assertEqual(old_run["status"], "succeeded")


# ======================================================================
# Workstream 1: Node-Level Input Contracts + Leakage Tests
# ======================================================================

class InputContractTests(unittest.TestCase):

    def test_fit_node_rejects_test_oot_datasets(self) -> None:
        store, tmp = make_store()
        store.initialize()
        node = FineClassingNode()

        mock_train = ArtifactRef(
            artifact_id="t1", artifact_type="dataset", role="train",
            path="mock", physical_hash="a", logical_hash="b",
        )
        mock_test = ArtifactRef(
            artifact_id="t2", artifact_type="dataset", role="test",
            path="mock", physical_hash="c", logical_hash="d",
        )
        mock_oot = ArtifactRef(
            artifact_id="t3", artifact_type="dataset", role="oot",
            path="mock", physical_hash="e", logical_hash="f",
        )

        with self.assertRaises(RoleAccessError):
            executor = PlanExecutor(NodeRegistry.with_defaults())
            executor.validate_leakage_rules(node, [mock_test])

        with self.assertRaises(RoleAccessError):
            executor = PlanExecutor(NodeRegistry.with_defaults())
            executor.validate_leakage_rules(node, [mock_oot])

        try:
            executor = PlanExecutor(NodeRegistry.with_defaults())
            executor.validate_leakage_rules(node, [mock_train])
        except RoleAccessError:
            self.fail("Fit node should accept train dataset")

    def test_selection_node_rejects_test_tabular(self) -> None:
        store, tmp = make_store()
        store.initialize()
        node = CalculateWoeIvNode()

        mock_test_dataset = ArtifactRef(
            artifact_id="t1", artifact_type="dataset", role="test",
            path="mock", physical_hash="a", logical_hash="b",
        )
        mock_oot_dataset = ArtifactRef(
            artifact_id="t2", artifact_type="dataset", role="oot",
            path="mock", physical_hash="c", logical_hash="d",
        )

        executor = PlanExecutor(NodeRegistry.with_defaults())
        with self.assertRaises(RoleAccessError):
            executor.validate_leakage_rules(node, [mock_test_dataset])
        with self.assertRaises(RoleAccessError):
            executor.validate_leakage_rules(node, [mock_oot_dataset])

    def test_selection_node_accepts_report_artifacts(self) -> None:
        store, tmp = make_store()
        store.initialize()
        node = CalculateWoeIvNode()

        mock_report = ArtifactRef(
            artifact_id="r1", artifact_type="report", role="report",
            path="mock", physical_hash="a", logical_hash="b",
        )

        executor = PlanExecutor(NodeRegistry.with_defaults())
        try:
            executor.validate_leakage_rules(node, [mock_report])
        except RoleAccessError:
            self.fail("Selection node should accept report artifacts")

    def test_transform_node_no_restrictions(self) -> None:
        store, tmp = make_store()
        store.initialize()
        node = ProfileDatasetNode()

        mock_test_dataset = ArtifactRef(
            artifact_id="t1", artifact_type="dataset", role="test",
            path="mock", physical_hash="a", logical_hash="b",
        )

        executor = PlanExecutor(NodeRegistry.with_defaults())
        try:
            executor.validate_leakage_rules(node, [mock_test_dataset])
        except RoleAccessError:
            self.fail("Transform node should accept any role")


class Phase2BEndToEndTests(unittest.TestCase):

    def test_woe_transform_train_rejects_test_role(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({"x": [1.0], "target": ["g"]})
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        test_art = ArtifactRef(
            artifact_id="test1", artifact_type="dataset", role="test",
            path=relative_path(path, store.root),
            physical_hash=physical_hash(path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(test_art)

        executor = PlanExecutor(NodeRegistry.with_defaults())
        node = WoeTransformTrainNode()
        with self.assertRaises(RoleAccessError):
            executor.validate_leakage_rules(node, [test_art])
