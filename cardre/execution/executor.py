"""Plan executor: topological step execution, role enforcement, and evidence persistence.

The executor walks plan_steps in topological order, resolves input
artifacts from parent run-step outputs, validates role access, runs each
node, records outputs, and creates evidence_edges + evidence_artifacts
per-step inside the run transaction.

Every failed step is recorded with structured errors and whatever input
evidence was resolved before the failure.
"""

from __future__ import annotations

import enum
import sys
import threading
import traceback
import uuid
from typing import TYPE_CHECKING, Any

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import (
    CardreError,
    GraphValidationError,
    MissingInputArtifactError,
    ParameterValidationError,
    PlanContainsUnavailableNodesError,
)
from cardre.domain.evidence import ResolvedEvidence
from cardre.domain.run import RunStep, RunStepStatus
from cardre.execution.action_planner import _StepAction
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.execution.failure_classification import classify_step_failure
from cardre.execution.fingerprints import build_execution_fingerprint
from cardre.execution.run_step_writer import write_reused_run_step, write_run_step
from cardre.execution.topology import validate_topology
from cardre.nodes.registry import NodeRegistry

if TYPE_CHECKING:
    from cardre.domain.diagnostics import JsonDict
    from cardre.domain.step import StepSpec
    from cardre.store.db import ProjectStore

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


def _json_ready(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, set):
        return [_json_ready(v) for v in value]
    import numpy as np
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.ndarray,)):
        return [_json_ready(v) for v in value.tolist()]
    return value


class _HeartbeatWatchdog:
    """Daemon thread that keeps ``heartbeat_at`` fresh while a step executes.

    Started before ``node.run(ctx)`` and stopped after it returns.  The
    watchdog ticks at ``interval_seconds`` so a healthy long-running step
    never goes stale.  A truly dead worker (process crash) takes the
    daemon thread with it, so stale recovery still works.
    """

    def __init__(
        self,
        store: ProjectStore,
        run_id: str,
        step_id: str,
        interval_seconds: int,
    ) -> None:
        self._root = store.root
        self._run_id = run_id
        self._step_id = step_id
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._tick,
            name=f"hb-watchdog-{run_id[:8]}",
            daemon=True,
        )

    def __enter__(self) -> _HeartbeatWatchdog:
        from cardre.store.run_repo import RunRepository
        with self._store_for_root(self._root) as main_store:
            main_repo = RunRepository(main_store)
            main_repo.set_active_step(self._run_id, self._step_id)
            main_repo.heartbeat(self._run_id)
        self._stop.clear()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval * 2 + 2)
        from cardre.store.run_repo import RunRepository
        with self._store_for_root(self._root) as main_store:
            main_repo = RunRepository(main_store)
            main_repo.set_active_step(self._run_id, None)

    def _tick(self) -> None:
        from cardre.store.run_repo import RunRepository
        while not self._stop.wait(self._interval):
            with self._store_for_root(self._root) as hb_store:
                hb_repo = RunRepository(hb_store)
                hb_repo.heartbeat(self._run_id)

    @staticmethod
    def _store_for_root(root: Any) -> ProjectStore:
        from cardre.store.db import ProjectStore
        return ProjectStore(root)


def _open_store_for_root(root: Any) -> ProjectStore:
    """Open a ProjectStore from root for use in a separate thread."""
    from cardre.store.db import ProjectStore
    s = ProjectStore(root)
    s.open()
    return s


class PlanExecutor:
    """Executes plan versions step by step, persisting evidence per-step.

    Execution flow:
      ActionPlanner resolves intended evidence (planned actions).
      PlanExecutor executes action.
      RunStepRepository writes run_step.
      EvidenceRepository writes evidence_edge + evidence_artifacts for that run_step.
      RunLifecycle finalises run and manifest.
    """

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
        self._node_registry = NodeRegistry.with_defaults()
        from cardre.config import CardreConfig
        self._heartbeat_interval = CardreConfig.from_env().heartbeat_watchdog_interval_seconds

    # ------------------------------------------------------------------
    # Top-level run entrypoints
    # ------------------------------------------------------------------

    def run_plan_version(
        self,
        plan_version_id: str,
        run_id: str,
        *,
        force: bool = False,
        branch_id: str | None = None,
        precomputed_outputs: dict[str, list[ArtifactRef]] | None = None,
        precomputed_records: dict[str, RunStep] | None = None,
    ) -> str:
        """Execute all steps in a plan version. Returns the run_id."""
        steps = self._load_and_validate(plan_version_id)
        actions = [_StepAction(spec=s, action="execute", reason_code="full_plan") for s in steps]
        has_failure, _, _ = self._execute_actions(
            plan_version_id, run_id, actions, branch_id=branch_id,
            precomputed_outputs=precomputed_outputs,
            precomputed_records=precomputed_records,
        )
        return run_id

    def run_to_node(
        self,
        plan_version_id: str,
        target_step_id: str,
        run_id: str,
        *,
        force: bool = False,
        branch_id: str | None = None,
    ) -> str:
        """Execute only the ancestor closure of *target_step_id*."""
        steps = self._load_and_validate(plan_version_id)
        from cardre.execution.step_graph import ancestor_closure

        step_by_id = {s.step_id: s for s in steps}
        if target_step_id not in step_by_id:
            raise GraphValidationError(
                f"Target step {target_step_id!r} not found in plan version {plan_version_id}"
            )

        ancestors = ancestor_closure(target_step_id, steps)
        closure = ancestors | {target_step_id}
        closure_steps = [s for s in steps if s.step_id in closure]

        # Build to_node actions with staleness checks
        actions = self._build_to_node_actions(plan_version_id, closure_steps, force, branch_id)
        has_failure, _, _ = self._execute_actions(
            plan_version_id, run_id, actions, branch_id=branch_id,
        )
        return run_id

    # ------------------------------------------------------------------
    # Action planning helpers
    # ------------------------------------------------------------------

    def _build_to_node_actions(
        self,
        plan_version_id: str,
        closure_steps: list[StepSpec],
        force: bool,
        branch_id: str | None,
    ) -> list[_StepAction]:
        """Build actions for a to-node run.

        All steps in the ancestor closure are marked ``execute`` with
        reason ``to_node_closure``. Staleness-aware reuse/skip is not
        implemented yet — pretending it is would be dishonest (#214).
        """
        return [
            _StepAction(spec=s, action="execute", reason_code="to_node_closure")
            for s in closure_steps
        ]

    # ------------------------------------------------------------------
    # Shared action execution loop
    # ------------------------------------------------------------------

    def _execute_actions(
        self,
        plan_version_id: str,
        run_id: str,
        actions: list[_StepAction],
        *,
        branch_id: str | None = None,
        precomputed_outputs: dict[str, list[ArtifactRef]] | None = None,
        precomputed_records: dict[str, RunStep] | None = None,
    ) -> tuple[bool, dict[str, list[ArtifactRef]], dict[str, RunStep]]:
        """Execute a sequence of step actions.

        Returns ``(has_failure, step_outputs, run_step_records)``.
        """
        outputs: dict[str, list[ArtifactRef]] = precomputed_outputs or {}
        records: dict[str, RunStep] = precomputed_records or {}
        has_failure = False

        for action in actions:
            if has_failure:
                break
            if action.action == "skip":
                continue
            if action.action == "reuse":
                rs = self._reuse_run_step(
                    plan_version_id, run_id, action.spec, outputs, records,
                    evidence=action.evidence_source, branch_id=branch_id,
                )
                if rs is not None:
                    records[action.spec.step_id] = rs
                    outputs[action.spec.step_id] = self._resolve_output_artifacts(
                        plan_version_id, run_id, rs,
                    )
                else:
                    self._append_diagnostic(run_id, {
                        "code": "REUSE_EVIDENCE_NOT_FOUND",
                        "message": f"No prior evidence to reuse for step {action.spec.step_id}, falling back to execute.",
                        "severity": "warning",
                        "run_id": run_id,
                        "plan_version_id": plan_version_id,
                        "step_id": action.spec.step_id,
                        "branch_id": branch_id,
                    })
                    if action.before_execute is not None:
                        action.before_execute()
                    self._heartbeat(run_id)
                    with _HeartbeatWatchdog(
                        self._store, run_id, action.spec.step_id,
                        interval_seconds=self._heartbeat_interval,
                    ):
                        rs = self._execute_step(
                            plan_version_id, run_id, action.spec, outputs, records,
                        )
                    records[action.spec.step_id] = rs
                    outputs[action.spec.step_id] = self._resolve_output_artifacts(
                        plan_version_id, run_id, rs,
                    )
                    if rs.status == RunStepStatus.FAILED:
                        has_failure = True
                continue

            if action.action == "execute":
                if action.before_execute is not None:
                    action.before_execute()
                self._heartbeat(run_id)
                with _HeartbeatWatchdog(
                    self._store, run_id, action.spec.step_id,
                    interval_seconds=self._heartbeat_interval,
                ):
                    rs = self._execute_step(
                        plan_version_id, run_id, action.spec, outputs, records,
                    )
                self._heartbeat(run_id)
                records[action.spec.step_id] = rs
                outputs[action.spec.step_id] = self._resolve_output_artifacts(
                    plan_version_id, run_id, rs,
                )
                if rs.status == RunStepStatus.FAILED:
                    has_failure = True

        return has_failure, outputs, records

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def _execute_step(
        self,
        plan_version_id: str,
        run_id: str,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStep],
    ) -> RunStep:
        """Execute a single step and persist run_step + evidence."""
        parent_run_steps: list[RunStep] = [
            rs for pid in spec.parent_step_ids
            if (rs := run_step_records.get(pid)) is not None
        ]
        raw_inputs: list[ArtifactRef] = []
        input_artifacts: list[ArtifactRef] = []
        input_artifact_ids_by_parent: dict[str, list[str]] = {}

        try:
            raw_inputs = self._resolve_inputs(spec, step_outputs)
            input_artifacts = raw_inputs

            # Build per-parent input artifact mapping for evidence attribution
            for pid in spec.parent_step_ids:
                parent_artifacts = step_outputs.get(pid, [])
                input_artifact_ids_by_parent[pid] = [a.artifact_id for a in parent_artifacts]

            node = self._node_registry.instantiate(spec.node_type)
            validation_errors = node.validate_params(dict(spec.params))
            if validation_errors:
                raise ParameterValidationError(
                    f"Step {spec.step_id!r} parameter validation failed: {'; '.join(validation_errors)}",
                    context={
                        "plan_version_id": plan_version_id,
                        "step_id": spec.step_id,
                        "node_type": spec.node_type,
                        "errors": validation_errors,
                    },
                )

            context = ExecutionContext(
                store=self._store,
                run_id=run_id,
                plan_version_id=plan_version_id,
                step_spec=spec,
                parent_run_steps=parent_run_steps,
                input_artifacts=input_artifacts,
                validated_params=dict(spec.params),
                runtime_metadata={
                    "run_id": run_id,
                    "plan_version_id": plan_version_id,
                    "step_id": spec.step_id,
                    "node_type": spec.node_type,
                },
            )

            node_output = node.run(context)
            if not isinstance(node_output, NodeOutput):
                raise TypeError(
                    f"Node {spec.node_type!r} returned {type(node_output)!r} instead of NodeOutput"
                )

            output_artifacts = list(node_output.artifacts)

            fp = build_execution_fingerprint(
                plan_version_id, spec, parent_run_steps,
                input_artifacts, output_artifacts,
            )
            if node_output.execution_fingerprint:
                fp.update(node_output.execution_fingerprint)
            if node_output.metrics:
                fp["node_metrics"] = dict(node_output.metrics)
            fp = _json_ready(fp)

            return self._record_run_step(
                run_id=run_id,
                spec=spec,
                plan_version_id=plan_version_id,
                fp=fp,
                input_artifact_ids=[a.artifact_id for a in input_artifacts],
                output_artifact_ids=[a.artifact_id for a in output_artifacts],
                parent_run_steps=parent_run_steps,
                status=RunStepStatus.SUCCEEDED,
                errors=[],
                warnings=list(node_output.warnings or []),
                input_artifact_ids_by_parent=input_artifact_ids_by_parent,
            )

        except Exception:
            tb = traceback.format_exc()
            exc_value = sys.exc_info()[1]
            error_entry = classify_step_failure(exc_value, tb)

            recorded_input_ids = [a.artifact_id for a in input_artifacts]

            fp = build_execution_fingerprint(
                plan_version_id, spec, parent_run_steps,
                input_artifacts, [],
            )
            fp = _json_ready(fp)

            try:
                return self._record_run_step(
                    run_id=run_id,
                    spec=spec,
                    plan_version_id=plan_version_id,
                    fp=fp,
                    input_artifact_ids=recorded_input_ids,
                    output_artifact_ids=[],
                    parent_run_steps=parent_run_steps,
                    status=RunStepStatus.FAILED,
                    errors=[error_entry],
                    warnings=[],
                    input_artifact_ids_by_parent=input_artifact_ids_by_parent,
                )
            except Exception as rec_exc:
                raise CardreError(
                    f"Step recording failed for step {spec.step_id!r} in run {run_id}: {rec_exc}",
                    code="STEP_RECORDING_FAILED",
                    context={
                        "run_id": run_id,
                        "plan_version_id": plan_version_id,
                        "step_id": spec.step_id,
                        "original_error": error_entry,
                        "recording_error": str(rec_exc),
                    },
                ) from rec_exc

    def _resolve_inputs(
        self,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
    ) -> list[ArtifactRef]:
        """Resolve input artifacts from parent step outputs."""
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

    # ------------------------------------------------------------------
    # Run-step record + evidence persistence
    # ------------------------------------------------------------------

    def _record_run_step(
        self,
        run_id: str,
        spec: StepSpec,
        plan_version_id: str,
        fp: JsonDict,
        input_artifact_ids: list[str],
        output_artifact_ids: list[str],
        parent_run_steps: list[RunStep],
        status: RunStepStatus,
        errors: list[JsonDict],
        warnings: list[JsonDict],
        input_artifact_ids_by_parent: dict[str, list[str]] | None = None,
    ) -> RunStep:
        """Persist the run_step and evidence inside a transaction.

        Writes:
          - run_steps row via RunStepRepository
          - evidence_edges + evidence_artifacts rows
          - artifact_lineage rows
        """
        rs_id = str(uuid.uuid4())
        now = utc_now_iso()
        now_dt = now

        run_step = RunStep(
            run_step_id=rs_id,
            run_id=run_id,
            step_id=spec.step_id,
            plan_version_id=plan_version_id,
            status=status,
            started_at=now_dt,
            finished_at=now_dt,
            execution_fingerprint=fp,
            warnings=warnings,
            errors=errors,
        )

        # Resolve branch ID for lineage rows
        branch_id = self._get_branch_for_run(run_id)
        run_record = self._store.execute(
            "SELECT branch_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        run_branch_id = run_record["branch_id"] if run_record and run_record["branch_id"] else branch_id

        from cardre.store.evidence_repo import EvidenceRepository
        evidence_repo = EvidenceRepository(self._store)

        # Delegate persistence to the writer module
        with self._store.transaction("IMMEDIATE") as conn:
            write_run_step(
                conn=conn,
                run_step=run_step,
                spec=spec,
                parent_run_steps=parent_run_steps,
                input_artifact_ids=input_artifact_ids,
                output_artifact_ids=output_artifact_ids,
                input_artifact_ids_by_parent=input_artifact_ids_by_parent,
                run_branch_id=run_branch_id,
                evidence_repo=evidence_repo,
            )

        return run_step

    # ------------------------------------------------------------------
    # Reuse (carry-forward)
    # ------------------------------------------------------------------

    def _reuse_run_step(
        self,
        plan_version_id: str,
        run_id: str,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStep],
        evidence: ResolvedEvidence | None = None,
        branch_id: str | None = None,
    ) -> RunStep | None:
        """Carry forward a prior run step into the current run."""
        from cardre.store.artifact_repo import ArtifactRepository
        from cardre.store.evidence_repo import EvidenceRepository
        from cardre.store.run_step_repo import RunStepRepository

        evidence_repo = EvidenceRepository(self._store)

        prev_rs = evidence.run_step if evidence is not None else None
        if prev_rs is None:
            rs_repo = RunStepRepository(self._store)
            prev_rs = rs_repo.get_latest_successful_step(plan_version_id, spec.step_id, branch_id=branch_id)
            if prev_rs is None:
                return None
            # Fetch edges/artifacts for fallback
            edges = evidence_repo.get_edges_for_run_step(prev_rs.run_step_id)
            all_artifacts = evidence_repo.get_artifacts_for_run_step(prev_rs.run_step_id)
        else:
            edges = evidence.edges  # type: ignore[union-attr]  # evidence is guaranteed not None by prev_rs guard above
            all_artifacts = evidence.artifacts  # type: ignore[union-attr]  # evidence is guaranteed not None by prev_rs guard above

        copied_fp = dict(prev_rs.execution_fingerprint)
        copied_fp["cardre_step_carried_forward"] = True
        copied_fp["carried_forward_from_run_step_id"] = prev_rs.run_step_id
        copied_fp["carried_forward_from_plan_version_id"] = prev_rs.plan_version_id
        copied_fp["carried_forward_from_run_id"] = prev_rs.run_id
        copied_fp["carried_forward_original_started_at"] = prev_rs.started_at
        copied_fp["carried_forward_original_finished_at"] = prev_rs.finished_at

        now = utc_now_iso()
        rs_id = str(uuid.uuid4())

        # Get output artifacts from artifact_lineage
        art_repo = ArtifactRepository(self._store)
        lineage = art_repo.get_lineage_for_run_step(prev_rs.run_step_id)

        copied_rs = RunStep(
            run_step_id=rs_id,
            run_id=run_id,
            step_id=prev_rs.step_id,
            plan_version_id=plan_version_id,
            status=prev_rs.status,
            started_at=now,
            finished_at=now,
            execution_fingerprint=copied_fp,
            warnings=prev_rs.warnings,
            errors=prev_rs.errors,
        )

        # Resolve branch ID for lineage rows
        run_record = self._store.execute(
            "SELECT branch_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        run_branch_id = run_record["branch_id"] if run_record and run_record["branch_id"] else branch_id

        # Delegate persistence to the writer module
        with self._store.transaction("IMMEDIATE") as conn:
            write_reused_run_step(
                conn=conn,
                copied_rs=copied_rs,
                edges=edges,
                all_artifacts=all_artifacts,
                lineage_rows=lineage,
                run_branch_id=run_branch_id,
                evidence_repo=evidence_repo,
            )

        return copied_rs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_and_validate(self, plan_version_id: str) -> list[StepSpec]:
        """Load plan version steps and validate topology."""
        from cardre.store.plan_repo import PlanRepository
        plan_repo = PlanRepository(self._store)
        steps = plan_repo.get_version_steps(plan_version_id)
        validate_topology(steps)
        unavailable_issues: list[dict[str, object]] = []
        for step in steps:
            availability = self._node_registry.availability(step.node_type)
            if not availability.available:
                unavailable_issues.append(
                    {
                        "step_id": step.step_id,
                        "node_type": step.node_type,
                        "node_version": step.node_version,
                        "reason": availability.disabled_reason or "Node is unavailable.",
                        "missing_optional_dependencies": availability.missing_optional_dependencies,
                    }
                )
        if unavailable_issues:
            raise PlanContainsUnavailableNodesError(unavailable_issues)
        return steps

    def _heartbeat(self, run_id: str) -> None:
        from cardre.store.run_repo import RunRepository
        RunRepository(self._store).heartbeat(run_id)

    def _append_diagnostic(self, run_id: str, diag: dict[str, Any]) -> None:
        from cardre.store.run_repo import RunRepository
        RunRepository(self._store).append_diagnostic(run_id, diag)

    def _get_branch_for_run(self, run_id: str) -> str | None:
        row = self._store.execute(
            "SELECT branch_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row["branch_id"] if row else None

    def _resolve_output_artifacts(
        self,
        plan_version_id: str,
        run_id: str,
        rs: RunStep,
    ) -> list[ArtifactRef]:
        """Resolve output artifact Refs for a run step from artifact_lineage."""
        rows = self._store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output' ORDER BY created_at",
            (rs.run_step_id,),
        ).fetchall()
        artifacts: list[ArtifactRef] = []
        for row in rows:
            artifact = self._store.get_artifact(row["artifact_id"])
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    @staticmethod
    def compute_final_status(has_failure: bool) -> str:
        return STATUS_FAILED if has_failure else STATUS_SUCCEEDED


__all__ = ["PlanExecutor"]
