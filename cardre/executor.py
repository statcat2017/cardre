"""Plan executor: topological step execution, role enforcement, staleness, and replay.

The executor walks plan_steps in topological order, resolves input
artifacts from parent run-step outputs, validates role access, runs each
node, records outputs, and creates run_step evidence.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    NodeOutput,
    NodeType,
    RunStepRecord,
    StepSpec,
    json_logical_hash,
    utc_now_iso,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore


FIT_ROLES = {"train"}
APPLY_ROLES = {"train", "test", "oot"}
APPLY_PLUS_DEFINITION = {"train", "test", "oot", "definition"}
VALID_CATEGORIES = {"fit", "apply", "selection", "refinement", "transform"}
STATUS_NOT_RUN = "not_run"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


class PlanExecutor:
    """Executes plan versions using a node registry."""

    def __init__(self, registry: NodeRegistry) -> None:
        self.registry = registry

    # ------------------------------------------------------------------
    # Run a plan version
    # ------------------------------------------------------------------

    def run_plan_version(
        self,
        store: ProjectStore,
        plan_version_id: str,
    ) -> str:
        """Execute all steps in a plan version. Returns the run_id."""
        steps = store.get_plan_version_steps(plan_version_id)
        self._validate_topology(steps)

        run_id = store.create_run(plan_version_id)

        step_outputs: dict[str, list[ArtifactRef]] = {}
        run_step_records: dict[str, RunStepRecord] = {}

        try:
            for spec in steps:
                rs = self._execute_step(store, spec, plan_version_id, run_id, step_outputs, run_step_records)
                run_step_records[spec.step_id] = rs
                step_outputs[spec.step_id] = self._resolve_output_artifacts(store, rs)

            store.finish_run(run_id, STATUS_SUCCEEDED)
        except BaseException:
            store.finish_run(run_id, STATUS_FAILED)
            raise

        return run_id

    def _execute_step(
        self,
        store: ProjectStore,
        spec: StepSpec,
        plan_version_id: str,
        run_id: str,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStepRecord],
    ) -> RunStepRecord:
        node = self.registry.instantiate(spec.node_type)
        raw_inputs = self._resolve_inputs(spec, step_outputs)
        input_artifacts = self._filter_inputs_by_role(node, raw_inputs)

        self._validate_role_access(node, input_artifacts)

        parent_run_steps = [
            rs for pid in spec.parent_step_ids
            if (rs := run_step_records.get(pid)) is not None
        ]

        # Capture the full output logical hashes from parents (for staleness)
        parent_output_logical_hashes: list[str] = []
        for rs in parent_run_steps:
            parent_output_logical_hashes.extend(
                rs.execution_fingerprint.get("output_artifact_logical_hashes", [])
            )
        if not parent_output_logical_hashes:
            for pid in spec.parent_step_ids:
                parent_artifacts = step_outputs.get(pid, [])
                parent_output_logical_hashes.extend(a.logical_hash for a in parent_artifacts)

        ctx = ExecutionContext(
            store=store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=spec,
            parent_run_steps=parent_run_steps,
            input_artifacts=input_artifacts,
            validated_params=spec.params,
            runtime_metadata={},
        )

        output: NodeOutput = node.run(ctx)
        output = self._ensure_execution_fingerprint(
            output, plan_version_id, spec, parent_run_steps,
            input_artifacts, parent_output_logical_hashes,
        )

        rs = self._record_run_step(
            store=store,
            run_id=run_id,
            spec=spec,
            plan_version_id=plan_version_id,
            output=output,
            parent_run_steps=parent_run_steps,
        )
        return rs

    def _resolve_inputs(
        self,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
    ) -> list[ArtifactRef]:
        if not spec.parent_step_ids:
            return []
        artifacts = []
        for pid in spec.parent_step_ids:
            parent_outputs = step_outputs.get(pid)
            if parent_outputs is None:
                raise ValueError(
                    f"Step {spec.step_id!r}: parent {pid!r} has no outputs "
                    "(not executed or missing)"
                )
            artifacts.extend(parent_outputs)
        return artifacts

    def _validate_topology(self, steps: list[StepSpec]) -> None:
        seen: set[str] = set()
        for step in steps:
            if step.step_id in seen:
                raise ValueError(f"Duplicate step_id {step.step_id!r}")
            for pid in step.parent_step_ids:
                if pid not in seen:
                    raise ValueError(
                        f"Step {step.step_id!r} references missing parent {pid!r}"
                    )
            seen.add(step.step_id)

    # ------------------------------------------------------------------
    # Role enforcement
    # ------------------------------------------------------------------

    FIT_PERMITTED_ROLES = {"train"}
    APPLY_PERMITTED_ROLES = {"train", "test", "oot", "definition"}
    SELECTION_PERMITTED_ROLES = {"report", "definition"}
    REFINEMENT_PERMITTED_ROLES = {"definition"}
    TRANSFORM_PERMITTED_ROLES: set[str] = set()

    CATEGORY_ROLE_MAP = {
        "fit": FIT_PERMITTED_ROLES,
        "apply": APPLY_PERMITTED_ROLES,
        "selection": SELECTION_PERMITTED_ROLES,
        "refinement": REFINEMENT_PERMITTED_ROLES,
        "transform": TRANSFORM_PERMITTED_ROLES,
    }

    def _filter_inputs_by_role(
        self,
        node: NodeType,
        artifacts: list[ArtifactRef],
    ) -> list[ArtifactRef]:
        permitted_roles = self.CATEGORY_ROLE_MAP.get(node.category)
        if permitted_roles is None or not permitted_roles:
            return artifacts
        return [a for a in artifacts if a.role in permitted_roles]

    def _validate_role_access(self, node: NodeType, artifacts: list[ArtifactRef]) -> None:
        permitted_roles = self.CATEGORY_ROLE_MAP.get(node.category)
        if permitted_roles is None or not permitted_roles:
            return
        if not artifacts:
            raise RoleAccessError(
                f"Node {node.node_type!r} (category={node.category!r}) "
                f"receives no artifacts with permitted roles {sorted(permitted_roles)}"
            )
        for artifact in artifacts:
            if artifact.role not in permitted_roles:
                raise RoleAccessError(
                    f"Node {node.node_type!r} (category={node.category!r}) "
                    f"cannot consume artifact role {artifact.role!r}. "
                    f"Permitted roles: {sorted(permitted_roles)}"
                )

    # ------------------------------------------------------------------
    # Execution fingerprint
    # ------------------------------------------------------------------

    def _ensure_execution_fingerprint(
        self,
        output: NodeOutput,
        plan_version_id: str,
        spec: StepSpec,
        parent_run_steps: list[RunStepRecord],
        input_artifacts: list[ArtifactRef],
        parent_output_logical_hashes: list[str] | None = None,
    ) -> NodeOutput:
        fp = output.execution_fingerprint
        fp["plan_version_id"] = plan_version_id
        fp["step_id"] = spec.step_id
        fp["node_type"] = spec.node_type
        fp["node_version"] = spec.node_version
        fp["params_hash"] = spec.params_hash
        fp["parent_run_step_ids"] = [rs.run_step_id for rs in parent_run_steps]
        fp["input_artifact_logical_hashes"] = parent_output_logical_hashes or [a.logical_hash for a in input_artifacts]
        fp["output_artifact_logical_hashes"] = [a.logical_hash for a in output.artifacts]
        fp["python_version"] = sys.version.split()[0]
        fp["cardre_version"] = "0.1.0"
        return output

    def _resolve_output_artifacts(
        self,
        store: ProjectStore,
        rs: RunStepRecord,
    ) -> list[ArtifactRef]:
        artifacts = []
        for aid in rs.output_artifact_ids:
            a = store.get_artifact(aid)
            if a is not None:
                artifacts.append(a)
        return artifacts

    # ------------------------------------------------------------------
    # Run-step record
    # ------------------------------------------------------------------

    def _record_run_step(
        self,
        store: ProjectStore,
        run_id: str,
        spec: StepSpec,
        plan_version_id: str,
        output: NodeOutput,
        parent_run_steps: list[RunStepRecord],
    ) -> RunStepRecord:
        rs = RunStepRecord(
            run_step_id=str(uuid.uuid4()),
            run_id=run_id,
            step_id=spec.step_id,
            plan_version_id=plan_version_id,
            status=STATUS_SUCCEEDED,
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=[a.artifact_id for a in (
                a for rs in parent_run_steps for a in self._resolve_output_artifacts(store, rs)
            )] if parent_run_steps else [],
            output_artifact_ids=[a.artifact_id for a in output.artifacts],
            execution_fingerprint=output.execution_fingerprint,
            warnings=[],
            errors=[],
        )
        store.save_run_step(rs)
        return rs

    # ------------------------------------------------------------------
    # Staleness
    # ------------------------------------------------------------------

    def compute_staleness(
        self,
        store: ProjectStore,
        plan_version_id: str,
    ) -> dict[str, bool]:
        """Return {step_id: is_stale} for each step in the plan version."""
        steps = store.get_plan_version_steps(plan_version_id)
        run_id = store.get_latest_successful_run_id(plan_version_id)
        if run_id is None:
            return {s.step_id: True for s in steps}

        run_steps = store.get_run_steps(run_id)
        rs_by_step = {rs.step_id: rs for rs in run_steps}

        stale: dict[str, bool] = {}
        for spec in steps:
            is_stale = self._step_is_stale(store, spec, steps, rs_by_step, stale)
            stale[spec.step_id] = is_stale
        return stale

    def _step_is_stale(
        self,
        store: ProjectStore,
        spec: StepSpec,
        all_steps: list[StepSpec],
        rs_by_step: dict[str, RunStepRecord],
        stale_cache: dict[str, bool],
    ) -> bool:
        if spec.step_id in stale_cache:
            return stale_cache[spec.step_id]

        rs = rs_by_step.get(spec.step_id)
        if rs is None:
            stale_cache[spec.step_id] = True
            return True

        fp = rs.execution_fingerprint
        fp_params_hash = fp.get("params_hash", "")
        if fp_params_hash != spec.params_hash:
            stale_cache[spec.step_id] = True
            return True

        fp_node_type = fp.get("node_type", "")
        fp_node_version = fp.get("node_version", "")
        if fp_node_type != spec.node_type or fp_node_version != spec.node_version:
            stale_cache[spec.step_id] = True
            return True

        for pid in spec.parent_step_ids:
            if self._step_is_stale(store, self._find_spec(pid, all_steps), all_steps, rs_by_step, stale_cache):
                stale_cache[spec.step_id] = True
                return True

            parent_rs = rs_by_step.get(pid)
            if parent_rs is None:
                stale_cache[spec.step_id] = True
                return True

        stale_cache[spec.step_id] = False
        return False

    def _find_spec(self, step_id: str, steps: list[StepSpec]) -> StepSpec:
        for s in steps:
            if s.step_id == step_id:
                return s
        raise KeyError(step_id)

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    def replay_from_step(
        self,
        store: ProjectStore,
        plan_id: str,
        previous_plan_version_id: str,
        changed_step_id: str,
        new_params: dict[str, Any],
        description: str = "Replay from changed step",
    ) -> str:
        previous_steps = store.get_plan_version_steps(previous_plan_version_id)
        previous_plan = store.get_plan_version(previous_plan_version_id)
        if previous_plan is None:
            raise ValueError(f"Plan version {previous_plan_version_id!r} not found")

        new_steps = [
            StepSpec(
                step_id=s.step_id,
                node_type=s.node_type,
                node_version=s.node_version,
                category=s.category,
                params=new_params if s.step_id == changed_step_id else s.params,
                params_hash=json_logical_hash(new_params) if s.step_id == changed_step_id else s.params_hash,
                parent_step_ids=s.parent_step_ids,
                branch_label=s.branch_label,
                position=s.position,
            )
            if s.step_id == changed_step_id else s
            for s in previous_steps
        ]

        new_plan_version_id = store.create_plan_version(
            plan_id=plan_id,
            steps=new_steps,
            description=description,
        )

        return self.run_plan_version(store, new_plan_version_id)


class RoleAccessError(ValueError):
    """Raised when a node attempts to consume an artifact with an
    unacceptable role for its category."""


def _output_logical_hashes(rs: RunStepRecord) -> list[str]:
    return rs.execution_fingerprint.get("output_artifact_logical_hashes", [])
