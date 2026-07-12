"""Plan executor: topological step execution, role enforcement, and evidence persistence.

The executor walks plan_steps in topological order, resolves input
artifacts from parent run-step outputs, validates role access, runs each
node, records outputs, and creates evidence_edges + evidence_artifacts
per-step inside the run transaction.

Every failed step is recorded with structured errors and whatever input
evidence was resolved before the failure.
"""

from __future__ import annotations

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
    PlanContainsUnavailableNodesError,
)
from cardre.domain.evidence import ResolvedEvidence
from cardre.domain.run import RunStep, RunStepStatus
from cardre.execution.action_planner import ExecutionActionPlanner, _StepAction
from cardre.execution.failure_classification import classify_step_failure
from cardre.execution.run_step_writer import write_reused_run_step, write_run_step
from cardre.execution.step_runner import StepExecutionResult, StepRunner
from cardre.execution.topology import validate_topology
from cardre.nodes.registry import NodeRegistry

if TYPE_CHECKING:
    from cardre.domain.step import StepSpec
    from cardre.store.db import ProjectStore

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


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
        self._action_planner = ExecutionActionPlanner()
        self._step_runner = StepRunner(store, self._node_registry)

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
        actions = self._action_planner.plan_full_plan(steps)
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

        step_by_id = {s.step_id: s for s in steps}
        if target_step_id not in step_by_id:
            raise GraphValidationError(
                f"Target step {target_step_id!r} not found in plan version {plan_version_id}"
            )

        actions = self._action_planner.plan_to_node(steps, target_step_id)
        has_failure, _, _ = self._execute_actions(
            plan_version_id, run_id, actions, branch_id=branch_id,
        )
        return run_id

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
                        rs = self._execute_and_persist(
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
                    rs = self._execute_and_persist(
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
    # Execute-and-persist: step runner caller + recording error handling
    # ------------------------------------------------------------------

    def _execute_and_persist(
        self,
        plan_version_id: str,
        run_id: str,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStep],
    ) -> RunStep:
        """Run a step via StepRunner, persist the result, and return the RunStep.

        Handles recording failures: if a *succeeded* execution cannot be
        persisted, the step is recorded as FAILED with the recording error.
        If a *failed* execution also cannot be persisted, raises CardreError
        (double failure — the original step error is logged in context).
        """
        result = self._step_runner.run_step(
            plan_version_id, run_id, spec, step_outputs, run_step_records,
        )
        try:
            return self._record_run_step_from_result(
                run_id, spec, plan_version_id, result,
            )
        except Exception:
            if result.status == RunStepStatus.FAILED:
                exc_info = sys.exc_info()[1]
                raise CardreError(
                    f"Step recording failed for step {spec.step_id!r} "
                    f"in run {run_id}: {exc_info}",
                    code="STEP_RECORDING_FAILED",
                    context={
                        "original_error": result.errors[0] if result.errors else None,
                    },
                ) from exc_info
            # Execution succeeded but recording failed — convert to FAILED step.
            # Rebuild the fingerprint with empty outputs (matching the original
            # _execute_step fallback path) so the failed record does not carry
            # output-artifact-derived hashes or metrics from the successful run.
            tb = traceback.format_exc()
            exc_value = sys.exc_info()[1]
            error_entry = classify_step_failure(exc_value, tb)
            failure_fp = dict(result.fingerprint)
            failure_fp["output_artifact_logical_hashes"] = []
            failure_fp.pop("node_metrics", None)
            failed_result = StepExecutionResult(
                step_id=result.step_id,
                node_type=result.node_type,
                status=RunStepStatus.FAILED,
                fingerprint=failure_fp,
                input_artifact_ids=result.input_artifact_ids,
                input_artifact_ids_by_parent=result.input_artifact_ids_by_parent,
                output_artifact_ids=[],
                parent_run_steps=result.parent_run_steps,
                warnings=[],
                errors=[error_entry],
            )
            try:
                return self._record_run_step_from_result(
                    run_id, spec, plan_version_id, failed_result,
                )
            except Exception as rec_exc2:
                raise CardreError(
                    f"Step recording failed for step {spec.step_id!r} "
                    f"in run {run_id}: {rec_exc2}",
                    code="STEP_RECORDING_FAILED",
                    context={
                        "original_error": error_entry,
                        "recording_error": str(rec_exc2),
                    },
                ) from rec_exc2

    # ------------------------------------------------------------------
    # Run-step persistence from StepExecutionResult
    # ------------------------------------------------------------------

    def _record_run_step_from_result(
        self,
        run_id: str,
        spec: StepSpec,
        plan_version_id: str,
        result: StepExecutionResult,
    ) -> RunStep:
        """Persist a StepExecutionResult as a run step with evidence.

        Writes run_steps, evidence_edges, evidence_artifacts, and
        artifact_lineage inside a single IMMEDIATE transaction.
        """
        rs_id = str(uuid.uuid4())
        now = utc_now_iso()

        run_step = RunStep(
            run_step_id=rs_id,
            run_id=run_id,
            step_id=spec.step_id,
            plan_version_id=plan_version_id,
            status=result.status,
            started_at=now,
            finished_at=now,
            execution_fingerprint=result.fingerprint,
            warnings=result.warnings,
            errors=result.errors,
        )

        # Resolve branch ID for lineage rows
        branch_id = self._get_branch_for_run(run_id)
        run_record = self._store.execute(
            "SELECT branch_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        run_branch_id = run_record["branch_id"] if run_record and run_record["branch_id"] else branch_id

        from cardre.store.evidence_repo import EvidenceRepository
        evidence_repo = EvidenceRepository(self._store)

        with self._store.transaction("IMMEDIATE") as conn:
            write_run_step(
                conn=conn,
                run_step=run_step,
                spec=spec,
                parent_run_steps=result.parent_run_steps,
                input_artifact_ids=result.input_artifact_ids,
                output_artifact_ids=result.output_artifact_ids,
                input_artifact_ids_by_parent=result.input_artifact_ids_by_parent,
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
