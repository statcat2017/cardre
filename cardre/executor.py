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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

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
from cardre.errors import (
    ArtifactReadError,
    ArtifactWriteError,
    CardreError,
    ContractViolationError,
    GraphValidationError,
    MissingInputArtifactError,
    NodeExecutionError,
    ParameterValidationError,
)
from cardre.evidence_locator import resolve_output_artifacts
from cardre.registry import NodeRegistry
from cardre.step_graph import ancestor_closure, descendant_closure
from cardre.store import ProjectStore
from cardre.topology import validate_topology


LEAKAGE_SENSITIVE_CATEGORIES = {"fit", "selection", "refinement"}

STATUS_NOT_RUN = "not_run"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


@dataclass
class _StepAction:
    """A planned action for a single step during execution."""

    spec: StepSpec
    action: Literal["execute", "reuse", "skip"]
    evidence_source: RunStepRecord | None = None
    before_execute: Callable[[], None] | None = None


class PlanExecutor:

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
        force: bool = False,
    ) -> str:
        steps = store.get_plan_version_steps(plan_version_id)
        self._validate_topology(steps)

        from cardre.run_lifecycle import RunLifecycle
        execution_mode = "force" if force else "full"
        with RunLifecycle.start(store, plan_version_id, run_id=run_id, execution_mode=execution_mode, force=force) as lifecycle:
            run_id = lifecycle.run_id

            actions = [
                _StepAction(spec=s, action="execute")
                for s in steps
            ]

            has_failure, outputs, records = self._execute_actions(
                store, actions, plan_version_id, run_id,
            )
            status = self._compute_final_status(has_failure, actions)

            lifecycle.finalise(
                status=status, execution_mode=execution_mode,
            )
        return run_id

    def run_branch(
        self,
        store: ProjectStore,
        plan_version_id: str,
        branch_id: str,
        run_id: str | None = None,
        force: bool = False,
    ) -> str:
        from cardre.run_lifecycle import RunLifecycle
        from cardre.services.branch_evidence import BranchEvidenceResolver
        resolver = BranchEvidenceResolver(self)
        ctx = resolver.prepare_branch_run(store, branch_id, plan_version_id, force=force)
        if not force and ctx.short_circuit_run_id is not None:
            return ctx.short_circuit_run_id

        execution_mode = "force" if force else "branch"
        with RunLifecycle.start(
            store, plan_version_id, run_id=run_id,
            branch_id=branch_id, execution_mode=execution_mode,
            force=force,
        ) as lifecycle:
            run_id = lifecycle.run_id

            # Build action list but defer parent evidence resolution to
            # just-before-execute so branch-owned parent steps produce
            # fresh evidence before their children resolve inputs.
            actions: list[_StepAction] = []
            for spec in ctx.steps:
                if spec.step_id not in ctx.branch_owned_step_ids:
                    actions.append(_StepAction(spec=spec, action="skip"))
                elif not force and spec.step_id not in ctx.stale_branch_step_ids:
                    actions.append(_StepAction(spec=spec, action="skip"))
                else:
                    actions.append(_StepAction(
                        spec=spec, action="execute",
                        before_execute=lambda s=spec: resolver.resolve_parent_evidence(
                            store, ctx, s,
                        ),
                    ))

            has_failure, outputs, records = self._execute_actions(
                store, actions, plan_version_id, run_id,
                step_outputs=ctx.step_outputs,
                run_step_records=ctx.run_step_records,
            )
            status = self._compute_final_status(has_failure, actions)

            lifecycle.finalise(
                status=status, execution_mode=execution_mode,
                branch_id=branch_id,
            )
        return run_id

    def run_to_node(
        self,
        store: ProjectStore,
        plan_version_id: str,
        target_step_id: str,
        run_id: str | None = None,
        force: bool = False,
        branch_id: str | None = None,
    ) -> str:
        steps = store.get_plan_version_steps(plan_version_id)
        self._validate_topology(steps)

        step_by_id = {s.step_id: s for s in steps}
        if target_step_id not in step_by_id:
            raise GraphValidationError(
                f"Target step {target_step_id!r} not found in plan version {plan_version_id}"
            )

        ancestors = ancestor_closure(target_step_id, steps)
        closure = ancestors | {target_step_id}
        closure_steps = [s for s in steps if s.step_id in closure]

        # Short-circuit when nothing to run
        if not force:
            from cardre.staleness import compute_staleness
            staleness = compute_staleness(store, plan_version_id)
            if all(not staleness.get(s.step_id, True) for s in closure_steps):
                existing_run_id = store.get_latest_successful_run_id(plan_version_id)
                if existing_run_id is not None:
                    return existing_run_id

        from cardre.run_lifecycle import RunLifecycle
        execution_mode = "force" if force else "to_node"
        with RunLifecycle.start(
            store, plan_version_id, run_id=run_id,
            execution_mode=execution_mode,
            target_step_id=target_step_id,
            in_scope_step_ids=sorted(closure),
            force=force,
        ) as lifecycle:
            run_id = lifecycle.run_id

            from cardre.staleness import compute_staleness
            staleness = compute_staleness(store, plan_version_id, branch_id=branch_id)

            # Planning is pure: reuse is recorded as action metadata, not written to store.
            actions: list[_StepAction] = []
            for spec in closure_steps:
                if not force and spec.step_id in staleness and not staleness[spec.step_id]:
                    actions.append(_StepAction(spec=spec, action="reuse"))
                else:
                    actions.append(_StepAction(spec=spec, action="execute"))

            has_failure, outputs, records = self._execute_actions(
                store, actions, plan_version_id, run_id,
            )
            status = self._compute_final_status(has_failure, actions)

            lifecycle.finalise(
                status=status, execution_mode=execution_mode,
                target_step_id=target_step_id,
                in_scope_step_ids=sorted(closure),
            )
        return run_id

    # ------------------------------------------------------------------
    # Shared action execution loop
    # ------------------------------------------------------------------

    def _execute_actions(
        self,
        store: ProjectStore,
        actions: list[_StepAction],
        plan_version_id: str,
        run_id: str,
        step_outputs: dict[str, list[ArtifactRef]] | None = None,
        run_step_records: dict[str, RunStepRecord] | None = None,
    ) -> tuple[bool, dict[str, list[ArtifactRef]], dict[str, RunStepRecord]]:
        """Execute a sequence of step actions.

        Returns ``(has_failure, step_outputs, rs_records)``.
        """
        outputs: dict[str, list[ArtifactRef]] = step_outputs or {}
        records: dict[str, RunStepRecord] = run_step_records or {}
        has_failure = False

        for action in actions:
            if has_failure:
                break

            if action.action == "skip":
                continue

            if action.action == "reuse":
                rs = self._reuse_run_step(store, action.spec, plan_version_id, run_id, outputs, records, evidence_source=action.evidence_source)
                if rs is not None:
                    records[action.spec.step_id] = rs
                    outputs[action.spec.step_id] = resolve_output_artifacts(store, rs)
                else:
                    if action.before_execute is not None:
                        action.before_execute()
                    store.run_heartbeat(run_id)
                    rs = self._execute_step(
                        store, action.spec, plan_version_id, run_id,
                        outputs, records,
                    )
                    records[action.spec.step_id] = rs
                    outputs[action.spec.step_id] = resolve_output_artifacts(store, rs)
                    if rs.status == STATUS_FAILED:
                        has_failure = True
                continue

            if action.action == "execute":
                if action.before_execute is not None:
                    action.before_execute()

                store.run_heartbeat(run_id)
                rs = self._execute_step(
                    store, action.spec, plan_version_id, run_id,
                    outputs, records,
                )
                store.run_heartbeat(run_id)
                records[action.spec.step_id] = rs
                outputs[action.spec.step_id] = resolve_output_artifacts(store, rs)
                if rs.status == STATUS_FAILED:
                    has_failure = True

        return has_failure, outputs, records

    @staticmethod
    def _compute_final_status(
        has_failure: bool,
        actions: list[_StepAction],
    ) -> str:
        if has_failure:
            return STATUS_FAILED
        executed = sum(1 for a in actions if a.action == "execute")
        if executed == 0:
            return STATUS_SUCCEEDED
        return STATUS_SUCCEEDED

    # ------------------------------------------------------------------
    # Step execution internals
    # ------------------------------------------------------------------

    def _execute_step(
        self,
        store: ProjectStore,
        spec: StepSpec,
        plan_version_id: str,
        run_id: str,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStepRecord],
    ) -> RunStepRecord:
        # Initialise before try so failure can still record partial evidence.
        raw_inputs: list[ArtifactRef] = []
        input_artifacts: list[ArtifactRef] = []
        parent_run_steps: list[RunStepRecord] = []

        try:
            node = self.registry.instantiate(spec.node_type)

            param_errors = node.validate_params(spec.params)
            if param_errors:
                raise ParameterValidationError(
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

        except Exception:
            tb = traceback.format_exc()
            exc_type = sys.exc_info()[0]
            exc_value = sys.exc_info()[1]

            _CATEGORY_MAP: tuple = (
                (GraphValidationError, "GraphValidationError"),
                (MissingInputArtifactError, "MissingInputArtifactError"),
                (ParameterValidationError, "ParameterValidationError"),
                (ArtifactReadError, "ArtifactReadError"),
                (ArtifactWriteError, "ArtifactWriteError"),
                (NodeExecutionError, "NodeExecutionError"),
                (ContractViolationError, "ContractViolationError"),
                (CardreError, "CardreError"),
            )
            category = "InternalExecutionError"
            if exc_value is not None:
                for exc_cls, cat in _CATEGORY_MAP:
                    if isinstance(exc_value, exc_cls):
                        category = cat
                        break

            error_entry = {
                "code": "STEP_FAILED",
                "message": f"{exc_type.__name__ if exc_type else 'Unknown'}: {exc_value}",
                "traceback": tb,
                "category": category,
            }

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
                raise MissingInputArtifactError(
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

    def _validate_input_artifact_files(
        self,
        store: ProjectStore,
        artifacts: list[ArtifactRef],
    ) -> None:
        for artifact in artifacts:
            path = store.artifact_path(artifact)  # cardre-allow-artifact-read: low-level-evidence-parser
            if not path.exists():
                raise ArtifactReadError(
                    f"Artifact {artifact.artifact_id!r} metadata points to missing file {artifact.path!r}"
                )
            current_hash = physical_hash(path)
            if current_hash != artifact.physical_hash:
                raise ArtifactReadError(
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
            warnings=output.warnings or [],
            errors=errors,
        )
        store.save_run_step(rs)
        return rs

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
        branch_id: str | None = None,
    ) -> str:
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

        affected = descendant_closure(changed_step_id, previous_steps)

        new_steps = replace_step_params(previous_steps, changed_step_id, new_params)

        if branch_id:
            new_plan_version_id = store.create_branch_plan_version(
                branch_id=branch_id,
                plan_id=plan_id,
                steps=new_steps,
                description=description,
                latest_pv_id=previous_plan_version_id,
            )
        else:
            new_plan_version_id = store.create_plan_version(
                plan_id=plan_id,
                steps=new_steps,
                description=description,
            )

        from cardre.run_lifecycle import RunLifecycle
        with RunLifecycle.start(store, new_plan_version_id, execution_mode="replay") as lifecycle:
            run_id = lifecycle.run_id

            # Build actions: reuse for unaffected steps, execute for affected
            actions: list[_StepAction] = []
            for spec in new_steps:
                if spec.step_id not in affected:
                    prev_rs = prev_rs_by_step.get(spec.step_id)
                    if prev_rs is None:
                        raise ValueError(
                            f"Cannot retain missing prior record for {spec.step_id!r}"
                        )
                    actions.append(_StepAction(
                        spec=spec, action="reuse",
                        evidence_source=prev_rs,
                    ))
                else:
                    actions.append(_StepAction(spec=spec, action="execute"))

            has_failure, outputs, records = self._execute_actions(
                store, actions, new_plan_version_id, run_id,
            )

            status = self._compute_final_status(has_failure, actions)
            lifecycle.finalise(
                status=status, execution_mode="replay",
            )
        return run_id

    # ------------------------------------------------------------------
    # Reuse run step (carry-forward)
    # ------------------------------------------------------------------

    def _reuse_run_step(
        self,
        store: ProjectStore,
        spec: StepSpec,
        plan_version_id: str,
        run_id: str,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStepRecord],
        evidence_source: RunStepRecord | None = None,
        branch_id: str | None = None,
    ) -> RunStepRecord | None:
        """Carry forward a prior run step into the current run.

        If *evidence_source* is provided, use it directly (replay path).
        Otherwise look up the latest successful run step for the spec.
        The write happens here, inside execution, not during planning.
        """
        prev_rs = evidence_source
        if prev_rs is None:
            latest_run_id = store.get_latest_successful_run_id(plan_version_id, branch_id=branch_id)
            if latest_run_id is None:
                return None
            prev_steps = store.get_run_steps(latest_run_id)
            prev_rs_by_step = {rs.step_id: rs for rs in prev_steps}
            prev_rs = prev_rs_by_step.get(spec.step_id)
            if prev_rs is None:
                return None
        copied_fp = dict(prev_rs.execution_fingerprint)
        copied_fp["cardre_step_carried_forward"] = True
        copied_fp["carried_forward_from_run_step_id"] = prev_rs.run_step_id
        copied_fp["carried_forward_from_plan_version_id"] = prev_rs.plan_version_id
        copied_fp["carried_forward_from_run_id"] = prev_rs.run_id
        copied_fp["carried_forward_original_started_at"] = prev_rs.started_at
        copied_fp["carried_forward_original_finished_at"] = prev_rs.finished_at
        now = utc_now_iso()
        copied_rs = RunStepRecord(
            run_step_id=str(uuid.uuid4()),
            run_id=run_id,
            step_id=prev_rs.step_id,
            plan_version_id=plan_version_id,
            status=prev_rs.status,
            started_at=now,
            finished_at=now,
            input_artifact_ids=prev_rs.input_artifact_ids,
            output_artifact_ids=prev_rs.output_artifact_ids,
            execution_fingerprint=copied_fp,
            warnings=prev_rs.warnings,
            errors=prev_rs.errors,
            is_carried_forward=True,
        )
        store.save_run_step(copied_rs)
        return copied_rs


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
