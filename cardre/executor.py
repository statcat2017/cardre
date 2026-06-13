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
    replace_step_params,
    utc_now_iso,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore


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
    ) -> str:
        """Execute all steps in a plan version. Returns the run_id.

        Every step is wrapped in its own per-step try/except to ensure
        that even if node instantiation or step execution fails, a
        RunStepRecord with structured errors is saved and the run is
        finished as FAILED. The run is never left in 'running' state.
        """
        steps = store.get_plan_version_steps(plan_version_id)
        self._validate_topology(steps)

        run_id = store.create_run(plan_version_id)

        step_outputs: dict[str, list[ArtifactRef]] = {}
        run_step_records: dict[str, RunStepRecord] = {}
        has_failure = False

        try:
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
    ) -> str:
        """Execute stale/not-run branch-owned steps for a single branch.

        Shared upstream steps are left untouched. Short-circuits if all
        branch-owned steps are already current.

        Blocks if shared upstream evidence is stale (checked against
        full-plan evidence, not the branch run's partial record).

        Returns the run_id.
        """
        branch = store.get_branch(branch_id)
        if branch is None:
            raise ValueError(f"Branch {branch_id} not found")
        if branch.get("status") != "active":
            raise ValueError(f"Branch {branch_id} is not active")

        if branch["head_plan_version_id"] != plan_version_id:
            raise ValueError(
                f"BRANCH_VERSION_MISMATCH: Branch head is {branch['head_plan_version_id']}, "
                f"requested {plan_version_id}"
            )

        step_map = store.get_branch_step_map(branch_id, plan_version_id)
        branch_owned_step_ids = {
            r["step_id"] for r in step_map if r["is_branch_owned"]
        }
        shared_upstream_step_ids = {
            r["step_id"] for r in step_map if r["is_shared_upstream"]
        }

        steps = store.get_plan_version_steps(plan_version_id)
        self._validate_topology(steps)

        # Compute branch-scoped staleness for branch-owned steps, but use
        # full-plan (branch_id=NULL) staleness for shared upstream checks.
        branch_staleness = self.compute_staleness(store, plan_version_id, branch_id=branch_id)
        plan_staleness = self.compute_staleness(store, plan_version_id, branch_id=None)

        # Merge: shared upstream steps use full-plan staleness, branch-owned use branch-scoped
        merged_staleness = dict(plan_staleness)
        for sid, is_stale in branch_staleness.items():
            if sid not in shared_upstream_step_ids:
                merged_staleness[sid] = is_stale

        # Check shared upstream staleness using full-plan evidence
        stale_shared = [
            sid for sid in shared_upstream_step_ids
            if plan_staleness.get(sid, True)
        ]
        if stale_shared:
            raise ValueError(
                f"SHARED_UPSTREAM_STALE: Cannot run branch {branch_id} because "
                f"shared upstream steps {stale_shared} are stale. "
                "Run the shared pathway first."
            )

        # Seed step_outputs and run_step_records from latest successful
        # run evidence for shared upstream steps. This ensures
        # _resolve_inputs() can find parent outputs.
        def _find_shared_evidence(step_id: str) -> RunStepRecord | None:
            rs = store.get_latest_successful_run_step_for_step(
                plan_version_id, step_id, branch_id=None,
            )
            if rs is not None:
                return rs
            plan_run_id = store.get_latest_successful_run_id_for_plan(branch["plan_id"])
            if plan_run_id is not None:
                for prs in store.get_run_steps(plan_run_id):
                    if prs.step_id == step_id and prs.status == STATUS_SUCCEEDED:
                        return prs
            return None

        # Identify stale branch-owned steps that need execution
        stale_branch_step_ids = [
            sid for sid in branch_owned_step_ids
            if branch_staleness.get(sid, True)
        ]

        # Short-circuit if no branch-owned steps are stale — don't create
        # an empty successful run that poisons future staleness.
        if not stale_branch_step_ids:
            existing_run_id = store.get_latest_successful_run_id(
                plan_version_id, branch_id=branch_id,
            )
            if existing_run_id is not None:
                return existing_run_id
            raise ValueError(
                f"BRANCH_NO_OP_FAILED: All branch-owned steps are current "
                f"but no prior successful branch run exists for branch {branch_id}."
            )

        step_outputs: dict[str, list[ArtifactRef]] = {}
        run_step_records: dict[str, RunStepRecord] = {}
        for sid in shared_upstream_step_ids:
            rs = _find_shared_evidence(sid)
            if rs is not None:
                run_step_records[sid] = rs
                step_outputs[sid] = self._resolve_output_artifacts(store, rs)

        # Seed current (non-stale) branch-owned step evidence too, so
        # downstream branch-owned steps can consume their outputs.
        for spec in steps:
            if spec.step_id in branch_owned_step_ids and not branch_staleness.get(spec.step_id, True):
                rs = store.get_latest_successful_run_step_for_step(
                    plan_version_id, spec.step_id, branch_id=branch_id,
                )
                if rs is not None:
                    run_step_records[spec.step_id] = rs
                    step_outputs[spec.step_id] = self._resolve_output_artifacts(store, rs)

        # Create run with branch association
        run_id = store.create_run(plan_version_id, branch_id=branch_id)

        has_failure = False
        executed_ids: list[str] = []

        try:
            for spec in steps:
                if has_failure:
                    break
                if spec.step_id not in branch_owned_step_ids:
                    continue
                # Skip if already current
                if not branch_staleness.get(spec.step_id, True):
                    continue

                # Seed shared upstream parent outputs that were missed
                for pid in spec.parent_step_ids:
                    if pid in shared_upstream_step_ids and pid not in step_outputs:
                        rs = _find_shared_evidence(pid)
                        if rs is not None:
                            run_step_records[pid] = rs
                            step_outputs[pid] = self._resolve_output_artifacts(store, rs)

                    # Also seed current branch-owned parent outputs
                    if pid in branch_owned_step_ids and pid not in step_outputs:
                        rs = store.get_latest_successful_run_step_for_step(
                            plan_version_id, pid, branch_id=branch_id,
                        )
                        if rs is not None:
                            run_step_records[pid] = rs
                            step_outputs[pid] = self._resolve_output_artifacts(store, rs)

                executed_ids.append(spec.step_id)
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

            raw_inputs = self._resolve_inputs(spec, step_outputs)
            input_artifacts = self._filter_inputs_by_role(node, raw_inputs)
            self._validate_role_access(node, spec, input_artifacts, raw_inputs)
            self._validate_node_input_roles(node, input_artifacts)
            self._validate_leakage_rules(node, input_artifacts)

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
            recorded_input_logical_hashes = [a.logical_hash for a in input_artifacts]
            recorded_parent_run_step_ids = [rs.run_step_id for rs in parent_run_steps]

            parent_outputs = _build_parent_output_hashes(parent_run_steps)

            output = NodeOutput(
                artifacts=[],
                metrics={},
                execution_fingerprint={
                    "plan_version_id": plan_version_id,
                    "step_id": spec.step_id,
                    "node_type": spec.node_type,
                    "node_version": spec.node_version,
                    "params_hash": spec.params_hash,
                    "parent_run_step_ids": recorded_parent_run_step_ids,
                    "input_artifact_logical_hashes": recorded_input_logical_hashes,
                    "output_artifact_logical_hashes": [],
                    "parent_output_logical_hashes_by_step": parent_outputs,
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
            return
        actual_roles = {a.role for a in artifacts}
        matching = set(node.input_roles) & actual_roles
        if not matching:
            raise RoleAccessError(
                f"Node {node.node_type!r} permits input roles "
                f"{node.input_roles} but receives only "
                f"{sorted(actual_roles)}. No permitted role matched."
            )

    def _validate_leakage_rules(
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

        fp["parent_output_logical_hashes_by_step"] = _build_parent_output_hashes(parent_run_steps)
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
        branch_id: str | None = None,
    ) -> dict[str, bool]:
        """Return {step_id: is_stale} for each step in the plan version.

        When branch_id is provided, looks for run evidence specific to
        that branch.  When branch_id is None, looks for full-plan
        (non-branch) runs only.

        Compares:
        - current params_hash, node_type, node_version
        - parent output logical hashes (has a parent been re-run?)
        - all ancestors recursively

        When the current plan version has no successful run, falls back
        to the most recent successful run from any version of the same
        plan.  This prevents every step from appearing stale immediately
        after a param-update creates a brand-new plan version.
        """
        steps = store.get_plan_version_steps(plan_version_id)
        run_id = store.get_latest_successful_run_id(plan_version_id, branch_id=branch_id)

        if run_id is None and branch_id:
            # Branch-scoped fallback: try any successful run for this plan
            # (including branch runs on other plan versions).
            pv = store.get_plan_version(plan_version_id)
            if pv is not None:
                row = store._connect().execute(
                    "SELECT r.run_id FROM runs r "
                    "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
                    "WHERE pv.plan_id = ? AND r.status = 'succeeded' "
                    "ORDER BY r.started_at DESC LIMIT 1",
                    (pv["plan_id"],),
                ).fetchone()
                if row is not None:
                    run_id = row["run_id"]

        if run_id is None:
            pv = store.get_plan_version(plan_version_id)
            if pv is not None:
                run_id = store.get_latest_successful_run_id_for_plan(pv["plan_id"])

            if run_id is None:
                return {s.step_id: True for s in steps}

        run_steps = store.get_run_steps(run_id)
        rs_by_step = {rs.step_id: rs for rs in run_steps}

        # For branch-scoped staleness, seed shared upstream evidence into
        # rs_by_step so parent recursion can find shared upstream records
        # (which are stored in full-plan runs, not branch-scoped ones).
        if branch_id:
            pv = store.get_plan_version(plan_version_id)
            if pv is not None:
                full_run_id = store.get_latest_successful_run_id(plan_version_id, branch_id=None)
                if full_run_id is None:
                    full_run_id = store.get_latest_successful_run_id_for_plan(pv["plan_id"])
                if full_run_id is not None and full_run_id != run_id:
                    for prs in store.get_run_steps(full_run_id):
                        if prs.step_id not in rs_by_step:
                            rs_by_step[prs.step_id] = prs

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


def _build_parent_output_hashes(
    parent_run_steps: list[RunStepRecord],
) -> dict[str, list[str]]:
    return {
        rs.step_id: rs.execution_fingerprint.get("output_artifact_logical_hashes", [])
        for rs in parent_run_steps
    }
