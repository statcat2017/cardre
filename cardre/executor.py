"""Plan executor: topological step execution, role enforcement, staleness, and replay.

The executor walks plan_steps in topological order, resolves input
artifacts from parent run-step outputs, validates role access, runs each
node, records outputs, and creates run_step evidence. Every failed step
is recorded as auditable run-step evidence with structured errors.
"""

from __future__ import annotations

import sys
import traceback
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
APPLY_ROLES = {"train", "test", "oot", "definition"}
SELECTION_ROLES = {"report", "definition"}
REFINEMENT_ROLES = {"definition"}
TRANSFORM_ROLES: set[str] = set()

CATEGORY_ROLE_MAP: dict[str, set[str]] = {
    "fit": FIT_ROLES,
    "apply": APPLY_ROLES,
    "selection": SELECTION_ROLES,
    "refinement": REFINEMENT_ROLES,
    "transform": TRANSFORM_ROLES,
}

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
        """Execute all steps in a plan version. Returns the run_id.

        Each step is wrapped in its own try/except. If a step fails, a
        failed RunStepRecord with structured errors is saved, the run is
        marked failed, and descendants are skipped.
        """
        steps = store.get_plan_version_steps(plan_version_id)
        self._validate_topology(steps)

        run_id = store.create_run(plan_version_id)

        step_outputs: dict[str, list[ArtifactRef]] = {}
        run_step_records: dict[str, RunStepRecord] = {}
        has_failure = False

        for spec in steps:
            if has_failure:
                break

            rs = self._execute_step(
                store, spec, plan_version_id, run_id,
                step_outputs, run_step_records,
            )
            run_step_records[spec.step_id] = rs
            step_outputs[spec.step_id] = self._resolve_output_artifacts(store, rs)

            if rs.status == STATUS_FAILED:
                has_failure = True

        if has_failure:
            store.finish_run(run_id, STATUS_FAILED)
        else:
            store.finish_run(run_id, STATUS_SUCCEEDED)

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

        try:
            raw_inputs = self._resolve_inputs(spec, step_outputs)
            input_artifacts = self._filter_inputs_by_role(node, raw_inputs)
            self._validate_role_access(node, spec, input_artifacts, raw_inputs)

            parent_run_steps = [
                rs for pid in spec.parent_step_ids
                if (rs := run_step_records.get(pid)) is not None
            ]

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
                input_artifacts,
            )

            rs = self._record_run_step(
                store=store,
                run_id=run_id,
                spec=spec,
                plan_version_id=plan_version_id,
                output=output,
                input_artifact_ids=[a.artifact_id for a in input_artifacts],
                parent_run_steps=parent_run_steps,
                status=STATUS_SUCCEEDED,
                errors=[],
            )
            return rs

        except BaseException:
            tb = traceback.format_exc()
            error_entry = {
                "code": "STEP_FAILED",
                "message": f"{sys.exc_info()[0].__name__}: {sys.exc_info()[1]}",
                "traceback": tb,
            }

            output = NodeOutput(
                artifacts=[],
                metrics={},
                execution_fingerprint={
                    "plan_version_id": plan_version_id,
                    "step_id": spec.step_id,
                    "node_type": spec.node_type,
                    "node_version": spec.node_version,
                    "params_hash": spec.params_hash,
                    "parent_run_step_ids": [
                        rs.run_step_id
                        for pid in spec.parent_step_ids
                        if (rs := run_step_records.get(pid)) is not None
                    ],
                    "input_artifact_logical_hashes": [],
                    "output_artifact_logical_hashes": [],
                    "python_version": sys.version.split()[0],
                    "cardre_version": "0.1.0",
                },
            )

            rs = self._record_run_step(
                store=store,
                run_id=run_id,
                spec=spec,
                plan_version_id=plan_version_id,
                output=output,
                input_artifact_ids=[],
                parent_run_steps=[
                    rs for pid in spec.parent_step_ids
                    if (rs := run_step_records.get(pid)) is not None
                ],
                status=STATUS_FAILED,
                errors=[error_entry],
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

    def _filter_inputs_by_role(
        self,
        node: NodeType,
        artifacts: list[ArtifactRef],
    ) -> list[ArtifactRef]:
        permitted_roles = CATEGORY_ROLE_MAP.get(node.category)
        if permitted_roles is None or not permitted_roles:
            return artifacts
        return [a for a in artifacts if a.role in permitted_roles]

    def _validate_role_access(
        self,
        node: NodeType,
        spec: StepSpec,
        filtered_artifacts: list[ArtifactRef],
        raw_inputs: list[ArtifactRef],
    ) -> None:
        permitted_roles = CATEGORY_ROLE_MAP.get(node.category)
        if permitted_roles is None or not permitted_roles:
            return

        # If the node has parents but after filtering there are no
        # matching artifacts, the graph is wired incorrectly.
        if spec.parent_step_ids and not filtered_artifacts:
            raw_roles = sorted({a.role for a in raw_inputs})
            raise RoleAccessError(
                f"Node {node.node_type!r} (category={node.category!r}) "
                f"receives no artifacts with permitted roles {sorted(permitted_roles)}. "
                f"Raw parent roles: {raw_roles}. "
                f"Check plan wiring: step {spec.step_id!r} parents "
                f"{spec.parent_step_ids!r} must produce {sorted(permitted_roles)}."
            )

        for artifact in filtered_artifacts:
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
    ) -> NodeOutput:
        fp = output.execution_fingerprint
        fp["plan_version_id"] = plan_version_id
        fp["step_id"] = spec.step_id
        fp["node_type"] = spec.node_type
        fp["node_version"] = spec.node_version
        fp["params_hash"] = spec.params_hash
        fp["parent_run_step_ids"] = [rs.run_step_id for rs in parent_run_steps]

        # Store the actual input artifact logical hashes (filtered)
        fp["input_artifact_logical_hashes"] = [a.logical_hash for a in input_artifacts]
        fp["output_artifact_logical_hashes"] = [a.logical_hash for a in output.artifacts]

        # Store parent output logical hashes keyed by parent step_id
        # for staleness comparison
        parent_outputs: dict[str, list[str]] = {}
        for rs in parent_run_steps:
            parent_outputs[rs.step_id] = rs.execution_fingerprint.get(
                "output_artifact_logical_hashes", []
            )
        fp["parent_output_logical_hashes_by_step"] = parent_outputs

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
        input_artifact_ids: list[str],
        parent_run_steps: list[RunStepRecord],
        status: str,
        errors: list[dict],
    ) -> RunStepRecord:
        rs = RunStepRecord(
            run_step_id=str(uuid.uuid4()),
            run_id=run_id,
            step_id=spec.step_id,
            plan_version_id=plan_version_id,
            status=status,
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=input_artifact_ids,
            output_artifact_ids=[a.artifact_id for a in output.artifacts],
            execution_fingerprint=output.execution_fingerprint,
            warnings=[],
            errors=errors,
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
        """Return {step_id: is_stale} for each step in the plan version.

        Compares:
        - current params_hash, node_type, node_version
        - parent output logical hashes (has a parent been re-run?)
        - all ancestors recursively
        """
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

        # Compare params_hash
        if fp.get("params_hash", "") != spec.params_hash:
            stale_cache[spec.step_id] = True
            return True

        # Compare node type/version
        if fp.get("node_type", "") != spec.node_type or fp.get("node_version", "") != spec.node_version:
            stale_cache[spec.step_id] = True
            return True

        # Check parents recursively AND compare parent output logical hashes
        parent_output_by_step: dict[str, list[str]] = fp.get(
            "parent_output_logical_hashes_by_step", {}
        )

        for pid in spec.parent_step_ids:
            # Recursive check: is the parent itself stale?
            if self._step_is_stale(store, self._find_spec(pid, all_steps), all_steps, rs_by_step, stale_cache):
                stale_cache[spec.step_id] = True
                return True

            # Compare parent output logical hashes: has the parent been
            # re-run since this child was last executed?
            parent_rs = rs_by_step.get(pid)
            if parent_rs is None:
                stale_cache[spec.step_id] = True
                return True

            stored_parent_outputs = parent_output_by_step.get(pid, [])
            current_parent_outputs = parent_rs.execution_fingerprint.get(
                "output_artifact_logical_hashes", []
            )
            if stored_parent_outputs != current_parent_outputs:
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
    # Incremental replay
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
        """Incremental replay: create a new plan version, copy unchanged
        ancestor run-step references into the new run, and execute only
        the affected subgraph (changed step + descendants).
        """
        previous_steps = store.get_plan_version_steps(previous_plan_version_id)
        previous_plan = store.get_plan_version(previous_plan_version_id)
        if previous_plan is None:
            raise ValueError(f"Plan version {previous_plan_version_id!r} not found")

        previous_run_id = store.get_latest_successful_run_id(previous_plan_version_id)
        if previous_run_id is None:
            raise ValueError(
                f"No successful previous run to replay from for "
                f"version {previous_plan_version_id!r}"
            )

        previous_run_steps = store.get_run_steps(previous_run_id)
        prev_rs_by_step = {rs.step_id: rs for rs in previous_run_steps}

        # Determine which step_ids are in the affected subgraph
        all_step_ids = {s.step_id for s in previous_steps}
        affected = self._descendants(changed_step_id, previous_steps)

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

        # Build new run, copying ancestor run-steps and executing
        # the affected subgraph
        run_id = store.create_run(new_plan_version_id)
        step_outputs: dict[str, list[ArtifactRef]] = {}
        run_step_records: dict[str, RunStepRecord] = {}

        for spec in new_steps:
            if spec.step_id not in affected:
                # Copy previous run-step evidence into the new run
                prev_rs = prev_rs_by_step.get(spec.step_id)
                if prev_rs is None:
                    raise ValueError(
                        f"Cannot retain missing prior record for {spec.step_id!r}"
                    )
                # Re-save the previous run-step under the new run_id
                copied_rs = RunStepRecord(
                    run_step_id=str(uuid.uuid4()),
                    run_id=run_id,
                    step_id=prev_rs.step_id,
                    plan_version_id=new_plan_version_id,
                    status=prev_rs.status,
                    started_at=prev_rs.started_at,
                    finished_at=prev_rs.finished_at,
                    input_artifact_ids=prev_rs.input_artifact_ids,
                    output_artifact_ids=prev_rs.output_artifact_ids,
                    execution_fingerprint=prev_rs.execution_fingerprint,
                    warnings=prev_rs.warnings,
                    errors=prev_rs.errors,
                )
                store.save_run_step(copied_rs)
                run_step_records[spec.step_id] = copied_rs
                step_outputs[spec.step_id] = self._resolve_output_artifacts(store, prev_rs)
                continue

            rs = self._execute_step(
                store, spec, new_plan_version_id, run_id,
                step_outputs, run_step_records,
            )
            run_step_records[spec.step_id] = rs
            step_outputs[spec.step_id] = self._resolve_output_artifacts(store, rs)

            if rs.status == STATUS_FAILED:
                break

        has_failure = any(
            rs.status == STATUS_FAILED
            for rs in run_step_records.values()
            if isinstance(rs, RunStepRecord)
        )
        if has_failure:
            store.finish_run(run_id, STATUS_FAILED)
        else:
            store.finish_run(run_id, STATUS_SUCCEEDED)

        return run_id

    def _descendants(self, step_id: str, steps: list[StepSpec]) -> set[str]:
        step_ids = {s.step_id for s in steps}
        if step_id not in step_ids:
            raise KeyError(step_id)
        descendants = set()
        changed = True
        while changed:
            changed = False
            for s in steps:
                if s.step_id in descendants:
                    continue
                if s.step_id == step_id or descendants.intersection(s.parent_step_ids):
                    descendants.add(s.step_id)
                    changed = True
        return descendants | {step_id}

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def find_ancestors(self, step_id: str, steps: list[StepSpec]) -> set[str]:
        """Return all ancestor step_ids of the given step (reverse
        topological walk)."""
        step_map = {s.step_id: s for s in steps}
        ancestors: set[str] = set()
        queue = list(step_map[step_id].parent_step_ids) if step_id in step_map else []
        while queue:
            pid = queue.pop()
            if pid in ancestors:
                continue
            ancestors.add(pid)
            if pid in step_map:
                queue.extend(step_map[pid].parent_step_ids)
        return ancestors


class RoleAccessError(ValueError):
    """Raised when a node attempts to consume an artifact with an
    unacceptable role for its category."""


def _output_logical_hashes(rs: RunStepRecord) -> list[str]:
    return rs.execution_fingerprint.get("output_artifact_logical_hashes", [])
