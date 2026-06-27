"""Characterisation tests for the run lifecycle behaviour of PlanExecutor.

These tests capture the current contract of run creation, status
finalisation, manifest generation, reuse labelling, and scope
metadata before any lifecycle refactoring.
"""

from __future__ import annotations

import json


from cardre.audit import RunStepRecord, StepSpec, json_logical_hash, utc_now_iso
from cardre.executor import PlanExecutor
from cardre.nodes import DummyFitNode
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

from tests.helpers import make_store
from tests.test_executor import SimpleSourceNode, SimpleTransformNode


# ======================================================================
# Phase 0 — Full-plan run lifecycle
# ======================================================================


class TestFullPlanRunLifecycle:
    """Lock down the full-plan run lifecycle contract."""

    def _one_step_plan(self, store: ProjectStore, plan_id: str) -> tuple[str, list[StepSpec]]:
        steps = [
            StepSpec(
                step_id="source", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        return pv_id, steps

    def test_run_record_created(self) -> None:
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id, _ = self._one_step_plan(store, plan_id)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "succeeded"
        assert run["started_at"] is not None
        assert run["finished_at"] is not None

    def test_run_status_succeeded_for_successful_run(self) -> None:
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id, _ = self._one_step_plan(store, plan_id)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        assert run["status"] == "succeeded"

    def test_run_steps_recorded_for_all_steps(self) -> None:
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id, steps = self._one_step_plan(store, plan_id)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)
        executed_ids = {rs.step_id for rs in run_steps}
        assert executed_ids == {"source"}

    def test_manifest_artifact_written(self) -> None:
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id, _ = self._one_step_plan(store, plan_id)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        manifest_arts = [a for a in store.list_artifacts() if a.artifact_type == "run_manifest"]
        assert len(manifest_arts) >= 1
        manifest_path = store.artifact_path(manifest_arts[-1])
        manifest = json.loads(manifest_path.read_text())
        assert manifest["run_id"] == run_id
        assert manifest["status"] == "succeeded"
        assert manifest["execution_mode"] == "full"
        assert len(manifest["steps"]) == 1

    def test_manifest_action_labels(self) -> None:
        """Steps successfully executed are labelled 'executed'."""
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id, _ = self._one_step_plan(store, plan_id)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        executor = PlanExecutor(reg)

        executor.run_plan_version(store, pv_id)
        manifest_arts = [a for a in store.list_artifacts() if a.artifact_type == "run_manifest"]
        manifest = json.loads(store.artifact_path(manifest_arts[-1]).read_text())
        assert manifest["steps"][0]["action"] == "executed"

    def test_failed_run_records_failed_status(self) -> None:
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        class FailOnPurposeNode(DummyFitNode):
            node_type = "cardre.fail_on_purpose"

            def run(self, context):
                raise RuntimeError("Intentional failure")

        steps = [
            StepSpec(
                step_id="failing", node_type="cardre.fail_on_purpose",
                node_version="1", category="fit",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(FailOnPurposeNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        assert run["status"] == "failed"

    def test_failed_run_has_error_evidence(self) -> None:
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        class FailOnPurposeNode(SimpleSourceNode):
            node_type = "cardre.fail_on_purpose"

            def run(self, context):
                raise RuntimeError("Intentional failure")

        steps = [
            StepSpec(
                step_id="failing", node_type="cardre.fail_on_purpose",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(FailOnPurposeNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)
        failing = [rs for rs in run_steps if rs.step_id == "failing"][0]
        assert failing.status == "failed"
        assert len(failing.errors) > 0
        assert "Intentional failure" in failing.errors[0]["message"]


# ======================================================================
# Phase 0 — Force mode
# ======================================================================


class TestForceMode:
    """force=True must execute steps unconditionally."""

    def test_force_rerun_produces_new_artifacts(self) -> None:
        store, tmp = make_store()
        store.initialize()
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

        second_run_id = executor.run_plan_version(store, pv_id, force=True)
        second_steps = store.get_run_steps(second_run_id)

        assert first_steps[0].output_artifact_ids != second_steps[0].output_artifact_ids, \
            "forced runs should produce new artifact IDs"

    def test_force_manifest_labelled_force(self) -> None:
        store, tmp = make_store()
        store.initialize()
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

        executor.run_plan_version(store, pv_id, force=True)
        manifest_arts = [a for a in store.list_artifacts() if a.artifact_type == "run_manifest"]
        manifest = json.loads(store.artifact_path(manifest_arts[-1]).read_text())
        assert manifest["execution_mode"] == "force"


# ======================================================================
# Phase 0 — To-node run lifecycle
# ======================================================================


class TestToNodeRunLifecycle:

    def test_to_node_executes_only_ancestors_and_target(self) -> None:
        store, tmp = make_store()
        store.initialize()
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
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        reg.register(SimpleTransformNode)
        executor = PlanExecutor(reg)

        run_id = executor.run_to_node(store, pv_id, "target")
        run_steps = store.get_run_steps(run_id)
        executed_ids = {rs.step_id for rs in run_steps}
        assert "import" in executed_ids
        assert "step_a" in executed_ids
        assert "target" in executed_ids
        assert "step_b" not in executed_ids

    def test_to_node_manifest_has_target_and_scope(self) -> None:
        store, tmp = make_store()
        store.initialize()
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
                step_id="target", node_type="cardre.test.simple_transform",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(SimpleSourceNode)
        reg.register(SimpleTransformNode)
        executor = PlanExecutor(reg)

        executor.run_to_node(store, pv_id, "target")
        manifest_arts = [a for a in store.list_artifacts() if a.artifact_type == "run_manifest"]
        manifest = json.loads(store.artifact_path(manifest_arts[-1]).read_text())
        assert manifest["target_step_id"] == "target"
        assert "in_scope_step_ids" in manifest


# ======================================================================
# Phase 0 — Manifest determinism
# ======================================================================


class TestManifestDeterminism:

    def test_identical_run_produces_identical_manifest(self) -> None:
        store, tmp = make_store()
        store.initialize()
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

        # Both runs use the same plan_version_id with force to get deterministic fingerprints
        # (same inputs → same output artifact logical hashes)
        executor.run_plan_version(store, pv_id, force=True)
        manifest_arts = [a for a in store.list_artifacts() if a.artifact_type == "run_manifest"]
        manifest1 = json.loads(store.artifact_path(manifest_arts[-1]).read_text())

        executor.run_plan_version(store, pv_id, force=True)
        manifest_arts = [a for a in store.list_artifacts() if a.artifact_type == "run_manifest"]
        manifest2 = json.loads(store.artifact_path(manifest_arts[-1]).read_text())

        # Action labels must be identical (both should be "executed")
        for s1, s2 in zip(manifest1["steps"], manifest2["steps"]):
            assert s1["action"] == s2["action"] == "executed"
            assert s1["node_type"] == s2["node_type"]
            assert s1["step_id"] == s2["step_id"]


# ======================================================================
# Phase 0 — Short-circuit placeholder manifest (ADR 0004 atomic finalisation)
# ======================================================================


class TestShortCircuitManifest:
    """RED: Short-circuit placeholder runs must have a manifest artifact,
    per ADR 0004's atomic-finalisation guarantee. Currently short-circuit
    placeholders are finished via direct ``store.finish_run(run_id,
    "cancelled")`` calls that bypass ``RunLifecycle`` / ``finalise_run``,
    so no manifest is written.
    """

    def test_to_node_short_circuit_placeholder_has_manifest(self) -> None:
        """A to-node short-circuit placeholder must have a manifest with
        status='cancelled'. No governance gate needed for to-node scope."""
        from cardre.services.run_service import RunService
        from cardre.services.run_worker import SyncRunDispatcher
        from cardre.artifacts import write_json_artifact
        import uuid

        store, tmp = make_store()
        store.initialize()
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

        # Seed a prior successful run so the to-node run short-circuits.
        prev_run_id = store.create_run(pv_id)
        art = write_json_artifact(
            store, artifact_type="report", role="artifact",
            stem="seed-source", payload={"step_id": "source"}, metadata={},
        )
        store.save_run_step(RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=prev_run_id, step_id="source",
            plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[art.artifact_id],
            execution_fingerprint={
                "params_hash": steps[0].params_hash,
                "node_type": "cardre.test.simple_source",
                "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [art.logical_hash],
            },
            warnings=[], errors=[],
        ))
        store.finish_run(prev_run_id, "succeeded")

        svc = RunService(store, dispatcher=SyncRunDispatcher())
        resp = svc.run_plan(pv_id, run_scope="to_node", target_step_id="source", sync=True)

        assert resp.run_id == prev_run_id, "must return existing run_id"

        placeholders = [r for r in store.list_runs(plan_version_id=pv_id)
                        if r.get("status") == "cancelled"]
        assert placeholders, "expected a cancelled placeholder"
        ph_id = placeholders[-1]["run_id"]

        manifests = [a for a in store.list_artifacts()
                     if a.artifact_type == "run_manifest"
                     and a.metadata.get("run_id") == ph_id]
        assert len(manifests) == 1, (
            f"short-circuit placeholder must have exactly one manifest "
            f"(ADR 0004 atomic finalisation); got {len(manifests)}"
        )
        manifest = json.loads(store.artifact_path(manifests[0]).read_text())
        assert manifest["status"] == "cancelled"
        assert manifest["execution_mode"] == "to_node"


