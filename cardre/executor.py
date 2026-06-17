"""Plan executor: topological step execution, role enforcement, staleness, and replay.

The executor walks plan_steps in topological order, resolves input
artifacts from parent run-step outputs, validates role access, runs each
node, records outputs, and creates run_step evidence. Every failed step
is recorded as auditable run-step evidence with structured errors and
whatever input evidence was resolved before the failure.
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
    physical_hash,
    replace_step_params,
    utc_now_iso,
)
from cardre.registry import NodeRegistry
from cardre.staleness import compute_staleness
from cardre.store import ProjectStore
from cardre.topology import validate_topology


LEAKAGE_SENSITIVE_CATEGORIES = {"fit", "selection", "refinement"}

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
        run_id: str | None = None,
    ) -> str:
        """Execute all steps in a plan version. Returns the run_id.

        Every step is wrapped in its own per-step try/except to ensure
        that even if node instantiation or step execution fails, a
        RunStepRecord with structured errors is saved and the run is
        finished as FAILED. The run is never left in 'running' state.

        When *run_id* is provided, use that existing run (must be in
        'running' status) instead of creating a new one.
        """
        steps = store.get_plan_version_steps(plan_version_id)
        self._validate_topology(steps)

        if run_id is None:
            run_id = store.create_run(plan_version_id)

        step_outputs: dict[str, list[ArtifactRef]] = {}
        run_step_records: dict[str, RunStepRecord] = {}
        has_failure = False

        try:
            for spec in steps:
                rs = self._execute_step(
                    store, spec, plan_version_id, run_id,
                    step_outputs, run_step_records,
                )
                run_step_records[spec.step_id] = rs
                step_outputs[spec.step_id] = self._resolve_output_artifacts(store, rs)

                if rs.status == STATUS_FAILED:
                    has_failure = True
        finally:
            if has_failure:
                store.finish_run(run_id, STATUS_FAILED)
            else:
                # Only finish as succeeded if all steps were actually
                # processed and none failed
                all_processed = len(run_step_records) == len(steps)
                if all_processed and not has_failure:
                    store.finish_run(run_id, STATUS_SUCCEEDED)
                else:
                    store.finish_run(run_id, STATUS_FAILED)

        return run_id

    def run_branch(
        self,
        store: ProjectStore,
        plan_version_id: str,
        branch_id: str,
        run_id: str | None = None,
    ) -> str:
        """Execute stale/not-run branch-owned steps for a single branch.

        Shared upstream steps are left untouched. Short-circuits if all
        branch-owned steps are already current.

        Blocks if shared upstream evidence is stale (checked against
        full-plan evidence, not the branch run's partial record).

        When *run_id* is provided, use that existing run (must be in
        'running' status) instead of creating a new one.

        Returns the run_id.
        """
        from cardre.services.branch_evidence import BranchEvidenceResolver
        resolver = BranchEvidenceResolver(self)
        ctx = resolver.prepare_branch_run(store, branch_id, plan_version_id)
        if ctx.short_circuit_run_id is not None:
            return ctx.short_circuit_run_id

        if run_id is None:
            run_id = store.create_run(plan_version_id, branch_id=branch_id)

        has_failure = False
        executed_ids: list[str] = []

        try:
            for spec in ctx.steps:
                if has_failure:
                    break
                if spec.step_id not in ctx.branch_owned_step_ids:
                    continue
                if spec.step_id not in ctx.stale_branch_step_ids:
                    continue

                resolver.resolve_parent_evidence(store, ctx, spec)

                executed_ids.append(spec.step_id)
                rs = self._execute_step(
                    store, spec, plan_version_id, run_id,
                    ctx.step_outputs, ctx.run_step_records,
                )
                ctx.run_step_records[spec.step_id] = rs
                ctx.step_outputs[spec.step_id] = self._resolve_output_artifacts(store, rs)

                if rs.status == STATUS_FAILED:
                    has_failure = True
        finally:
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
        # Initialise before try so failure can still record partial
        # evidence.
        raw_inputs: list[ArtifactRef] = []
        input_artifacts: list[ArtifactRef] = []
        parent_run_steps: list[RunStepRecord] = []

        try:
            node = self.registry.instantiate(spec.node_type)

            param_errors = node.validate_params(spec.params)
            if param_errors:
                raise ValueError(
                    f"Invalid parameters for step {spec.step_id!r} ({spec.node_type}): "
                    + "; ".join(param_errors)
                )

            raw_inputs = self._resolve_inputs(spec, step_outputs)
            input_artifacts = self._filter_inputs_by_role(node, raw_inputs)
            self._validate_role_access(node, spec, input_artifacts, raw_inputs)
            self._validate_node_input_roles(node, input_artifacts)
            self.validate_leakage_rules(node, input_artifacts)
            self._validate_input_artifact_files(store, input_artifacts)

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

            output.execution_fingerprint = self._build_execution_fingerprint(
                plan_version_id, spec, parent_run_steps,
                input_artifacts, output.artifacts,
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
            exc_type = sys.exc_info()[0]
            exc_value = sys.exc_info()[1]
            error_entry = {
                "code": "STEP_FAILED",
                "message": f"{exc_type.__name__ if exc_type else 'Unknown'}: {exc_value}",
                "traceback": tb,
            }

            # If node was never instantiated, do it now for metadata
            try:
                node = self.registry.instantiate(spec.node_type)
            except BaseException:
                node = None

            # Include whatever input evidence was resolved before
            # failure (may be partial if node instantiation itself
            # failed).
            recorded_input_ids = [a.artifact_id for a in input_artifacts]

            output = NodeOutput(
                artifacts=[],
                metrics={},
                execution_fingerprint=self._build_execution_fingerprint(
                    plan_version_id, spec, parent_run_steps,
                    input_artifacts, [],
                ),
            )

            rs = self._record_run_step(
                store=store,
                run_id=run_id,
                spec=spec,
                plan_version_id=plan_version_id,
                output=output,
                input_artifact_ids=recorded_input_ids,
                parent_run_steps=parent_run_steps,
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
        validate_topology(steps)

    # ------------------------------------------------------------------
    # Role enforcement
    # ------------------------------------------------------------------

    def _filter_inputs_by_role(
        self,
        node: NodeType,
        artifacts: list[ArtifactRef],
    ) -> list[ArtifactRef]:
        if not node.input_roles:
            return artifacts
        permitted = set(node.input_roles)
        return [a for a in artifacts if a.role in permitted]

    def _validate_role_access(
        self,
        node: NodeType,
        spec: StepSpec,
        filtered_artifacts: list[ArtifactRef],
        raw_inputs: list[ArtifactRef],
    ) -> None:
        if not node.input_roles:
            return

        if spec.parent_step_ids and not filtered_artifacts:
            raw_roles = sorted({a.role for a in raw_inputs})
            raise RoleAccessError(
                f"Node {node.node_type!r} declares input roles "
                f"{node.input_roles} but receives no matching artifacts. "
                f"Raw parent roles: {raw_roles}. "
                f"Check plan wiring: step {spec.step_id!r} parents "
                f"{spec.parent_step_ids!r}."
            )

        permitted = set(node.input_roles)
        for artifact in filtered_artifacts:
            if artifact.role not in permitted:
                raise RoleAccessError(
                    f"Node {node.node_type!r} declares input roles "
                    f"{sorted(permitted)} but cannot consume artifact "
                    f"role {artifact.role!r}."
                )

    def _validate_node_input_roles(
        self,
        node: NodeType,
        artifacts: list[ArtifactRef],
    ) -> None:
        if not node.input_roles:
            return
        if not artifacts:
            raise RoleAccessError(
                f"Node {node.node_type!r} declares input roles "
                f"{node.input_roles} but received no artifacts."
            )
        actual_roles = {a.role for a in artifacts}
        matching = set(node.input_roles) & actual_roles
        if not matching:
            raise RoleAccessError(
                f"Node {node.node_type!r} permits input roles "
                f"{node.input_roles} but receives only "
                f"{sorted(actual_roles)}. No permitted role matched."
            )

    def validate_leakage_rules(
        self,
        node: NodeType,
        artifacts: list[ArtifactRef],
    ) -> None:
        if node.category not in LEAKAGE_SENSITIVE_CATEGORIES:
            return
        for a in artifacts:
            if a.role in ("test", "oot") and a.artifact_type == "dataset":
                raise RoleAccessError(
                    f"Node {node.node_type!r} (category={node.category!r}) "
                    f"cannot consume {a.role!r} dataset artifact. "
                    f"Leakage-sensitive nodes must not consume test or OOT "
                    f"tabular data. Artifact ID: {a.artifact_id}"
                )

    # ------------------------------------------------------------------
    # Execution fingerprint
    # ------------------------------------------------------------------

    def _build_execution_fingerprint(
        self,
        plan_version_id: str,
        spec: StepSpec,
        parent_run_steps: list[RunStepRecord],
        input_artifacts: list[ArtifactRef],
        output_artifacts: list[ArtifactRef],
    ) -> dict[str, Any]:
        return {
            "plan_version_id": plan_version_id,
            "step_id": spec.step_id,
            "node_type": spec.node_type,
            "node_version": spec.node_version,
            "params_hash": spec.params_hash,
            "parent_run_step_ids": [rs.run_step_id for rs in parent_run_steps],
            "input_artifact_logical_hashes": [a.logical_hash for a in input_artifacts],
            "output_artifact_logical_hashes": [a.logical_hash for a in output_artifacts],
            "parent_output_logical_hashes_by_step": _build_parent_output_hashes(parent_run_steps),
            "python_version": sys.version.split()[0],
            "cardre_version": "0.1.0",
        }

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

    def _validate_input_artifact_files(
        self,
        store: ProjectStore,
        artifacts: list[ArtifactRef],
    ) -> None:
        for artifact in artifacts:
            path = store.artifact_path(artifact)
            if not path.exists():
                raise FileNotFoundError(
                    f"Artifact {artifact.artifact_id!r} metadata points to missing file {artifact.path!r}"
                )
            current_hash = physical_hash(path)
            if current_hash != artifact.physical_hash:
                raise ValueError(
                    f"Artifact {artifact.artifact_id!r} physical hash mismatch for {artifact.path!r}: "
                    f"metadata has {artifact.physical_hash}, file has {current_hash}. "
                    "The artifact file was modified after registration."
                )

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
        branch_id: str | None = None,
    ) -> dict[str, bool]:
        return compute_staleness(store, plan_version_id, branch_id=branch_id)

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
        ancestor run-step evidence into the new run, and execute only
        the affected subgraph (changed step + descendants).

        Copied fingerprints are rewritten with the new plan_version_id
        to maintain internal consistency.
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

        new_steps = replace_step_params(previous_steps, changed_step_id, new_params)

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
                # Copy previous run-step evidence into the new run,
                # rewriting the fingerprint to reference the new context
                prev_rs = prev_rs_by_step.get(spec.step_id)
                if prev_rs is None:
                    raise ValueError(
                        f"Cannot retain missing prior record for {spec.step_id!r}"
                    )
                # Rewrite the copied fingerprint to match the new
                # plan_version_id
                copied_fp = dict(prev_rs.execution_fingerprint)
                copied_fp["plan_version_id"] = new_plan_version_id
                copied_fp["cardre_step_carried_forward"] = True
                copied_fp["carried_forward_from_run_step_id"] = prev_rs.run_step_id

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
                    execution_fingerprint=copied_fp,
                    warnings=prev_rs.warnings,
                    errors=prev_rs.errors,
                )
                store.save_run_step(copied_rs)
                run_step_records[spec.step_id] = copied_rs
                step_outputs[spec.step_id] = self._resolve_output_artifacts(store, copied_rs)
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


def _build_parent_output_hashes(
    parent_run_steps: list[RunStepRecord],
) -> dict[str, list[str]]:
    return {
        rs.step_id: rs.execution_fingerprint.get("output_artifact_logical_hashes", [])
        for rs in parent_run_steps
    }
