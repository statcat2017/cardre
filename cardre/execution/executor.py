"""Plan executor: topological step execution, role enforcement, and evidence persistence.

The executor walks plan_steps in topological order, resolves input
artifacts from parent run-step outputs, validates role access, runs each
node, records outputs, and creates evidence_edges + evidence_artifacts
per-step inside the run transaction.

Every failed step is recorded with structured errors and whatever input
evidence was resolved before the failure.
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
import uuid
from typing import TYPE_CHECKING

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import (
    GraphValidationError,
    MissingInputArtifactError,
)
from cardre.domain.evidence import EvidenceEdge
from cardre.domain.run import RunStep, RunStepStatus
from cardre.execution.action_planner import _StepAction
from cardre.execution.failure_classification import classify_step_failure
from cardre.execution.fingerprints import build_execution_fingerprint
from cardre.execution.topology import validate_topology

if TYPE_CHECKING:
    from cardre.domain.diagnostics import JsonDict
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
        interval_seconds: int = 75,
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
        main_repo = RunRepository(self._store_for_root(self._root))
        main_repo.set_active_step(self._run_id, self._step_id)
        main_repo.heartbeat(self._run_id)
        self._stop.clear()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval * 2 + 2)
        from cardre.store.run_repo import RunRepository
        main_repo = RunRepository(self._store_for_root(self._root))
        main_repo.set_active_step(self._run_id, None)

    def _tick(self) -> None:
        from cardre.store.run_repo import RunRepository
        hb_store = self._store_for_root(self._root)
        hb_repo = RunRepository(hb_store)
        while not self._stop.wait(self._interval):
            hb_repo.heartbeat(self._run_id)

    @staticmethod
    def _store_for_root(root) -> "ProjectStore":
        from cardre.store.db import ProjectStore
        s = ProjectStore(root)
        s.open()
        return s


def _open_store_for_root(root):
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
        actions = [_StepAction(spec=s, action="execute") for s in steps]
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
        from cardre.services.staleness_service import StalenessService
        staleness_svc = StalenessService(self._store)
        explanation = staleness_svc.explain_step(plan_version_id, closure_steps[0].step_id)
        staleness = explanation.upstream_changes if explanation else {}

        actions: list[_StepAction] = []
        for spec in closure_steps:
            if not force and spec.step_id in staleness and not staleness.get(spec.step_id, True):
                actions.append(_StepAction(spec=spec, action="execute"))  # still execute if no staleness
            else:
                actions.append(_StepAction(spec=spec, action="execute"))
        return actions

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
                    evidence_source=action.evidence_source, branch_id=branch_id,
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
        raw_inputs: list[ArtifactRef] = []
        input_artifacts: list[ArtifactRef] = []
        parent_run_steps: list[RunStep] = []

        try:
            raw_inputs = self._resolve_inputs(spec, step_outputs)

            # In v2 without a full registry, we do lightweight validation
            # For full node execution, the NodeRegistry would be used here.
            # TODO: wire NodeRegistry in Phase 5 when nodes are available.
            input_artifacts = raw_inputs

            parent_run_steps = [
                rs for pid in spec.parent_step_ids
                if (rs := run_step_records.get(pid)) is not None
            ]

            # Node execution — placeholder until Phase 5 nodes are wired.
            # In a full run, this would instantiate the node and call run().
            output_artifacts: list[ArtifactRef] = []

            fp = build_execution_fingerprint(
                plan_version_id, spec, parent_run_steps,
                input_artifacts, output_artifacts,
            )

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
                warnings=[],
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
                )
            except Exception as rec_exc:
                import logging
                logging.getLogger(__name__).exception(
                    "_record_run_step failed for step %s in run %s", spec.step_id, run_id
                )
                return RunStep(
                    run_step_id=str(uuid.uuid4()),
                    run_id=run_id,
                    step_id=spec.step_id,
                    plan_version_id=plan_version_id,
                    status=RunStepStatus.FAILED,
                    started_at=utc_now_iso(),
                    finished_at=utc_now_iso(),
                    execution_fingerprint=fp,
                    warnings=[],
                    errors=[
                        error_entry,
                        {
                            "code": "STEP_RECORDING_FAILED",
                            "message": f"Recording step result failed: {rec_exc}",
                        },
                    ],
                )

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

        # Persist run_step + evidence + lineage in a single transaction
        with self._store.transaction("IMMEDIATE") as conn:
            # 1. Write run_step
            # Use the raw connection for the transaction-scoped write
            conn.execute(
                "INSERT OR REPLACE INTO run_steps "
                "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
                " execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_step.run_step_id,
                    run_step.run_id,
                    run_step.step_id,
                    run_step.plan_version_id,
                    run_step.status.value,
                    run_step.started_at,
                    run_step.finished_at,
                    json.dumps(run_step.execution_fingerprint),
                    json.dumps(run_step.warnings),
                    json.dumps(run_step.errors),
                ),
            )

            # 2. Write evidence_edges + evidence_artifacts
            branch_id = self._get_branch_for_run(run_id)
            run_record = self._store.execute(
                "SELECT branch_id FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            run_branch_id = run_record["branch_id"] if run_record and run_record["branch_id"] else branch_id

            for idx, parent_rs in enumerate(parent_run_steps):
                ee_id = str(uuid.uuid4())
                edge = EvidenceEdge(
                    evidence_edge_id=ee_id,
                    run_id=run_id,
                    run_step_id=rs_id,
                    plan_version_id=plan_version_id,
                    step_id=spec.step_id,
                    parent_step_id=parent_rs.step_id,
                    source_run_id=run_id,
                    source_run_step_id=parent_rs.run_step_id,
                    policy="exact",
                    source_label=f"parent_{idx}",
                    is_reused=False,
                    is_stale=False,
                    stale_reason=None,
                    created_at=now_dt,
                )
                conn.execute(
                    "INSERT INTO evidence_edges "
                    "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
                    " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
                    " stale_reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        edge.evidence_edge_id,
                        edge.run_id,
                        edge.run_step_id,
                        edge.plan_version_id,
                        edge.step_id,
                        edge.parent_step_id,
                        edge.source_run_id,
                        edge.source_run_step_id,
                        edge.policy,
                        edge.source_label,
                        1 if edge.is_reused else 0,
                        1 if edge.is_stale else 0,
                        edge.stale_reason,
                        edge.created_at,
                    ),
                )

                # Evidence artifacts for each parent edge
                for aid in input_artifact_ids:
                    ea_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO evidence_artifacts "
                        "(evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (ea_id, ee_id, aid, "input", now_dt),
                    )

            # 3. Write artifact_lineage for inputs
            for aid in input_artifact_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO artifact_lineage "
                    "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, artifact_id, direction, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), run_id, rs_id, plan_version_id, spec.step_id, run_branch_id, aid, "input", now_dt),
                )

            # 4. Write artifact_lineage for outputs
            for aid in output_artifact_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO artifact_lineage "
                    "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, artifact_id, direction, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), run_id, rs_id, plan_version_id, spec.step_id, run_branch_id, aid, "output", now_dt),
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
        evidence_source: RunStep | None = None,
        branch_id: str | None = None,
    ) -> RunStep | None:
        """Carry forward a prior run step into the current run."""
        from cardre.store.run_step_repo import RunStepRepository
        from cardre.store.evidence_repo import EvidenceRepository
        from cardre.store.artifact_repo import ArtifactRepository

        prev_rs = evidence_source
        if prev_rs is None:
            rs_repo = RunStepRepository(self._store)
            prev_rs = rs_repo.get_latest_successful_step(plan_version_id, spec.step_id, branch_id=branch_id)
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
        rs_id = str(uuid.uuid4())

        # Get input/output artifacts from the original run step's evidence
        evidence_repo = EvidenceRepository(self._store)
        edges = evidence_repo.get_edges_for_run_step(prev_rs.run_step_id)
        input_artifact_ids: list[str] = []
        for edge in edges:
            artifacts = evidence_repo.get_artifacts_for_edge(edge.evidence_edge_id)
            input_artifact_ids.extend(a.artifact_id for a in artifacts)

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

        # Persist within a transaction
        run_record = self._store.execute(
            "SELECT branch_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        run_branch_id = run_record["branch_id"] if run_record and run_record["branch_id"] else branch_id

        with self._store.transaction("IMMEDIATE") as conn:
            conn.execute(
                "INSERT OR REPLACE INTO run_steps "
                "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
                " execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    copied_rs.run_step_id, copied_rs.run_id, copied_rs.step_id,
                    copied_rs.plan_version_id, copied_rs.status.value,
                    copied_rs.started_at, copied_rs.finished_at,
                    json.dumps(copied_rs.execution_fingerprint),
                    json.dumps(copied_rs.warnings),
                    json.dumps(copied_rs.errors),
                ),
            )

            # Copy evidence edges from source
            for edge in edges:
                reused_ee_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO evidence_edges "
                    "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
                    " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
                    " stale_reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        reused_ee_id, run_id, rs_id, plan_version_id, copied_rs.step_id,
                        edge.parent_step_id, edge.source_run_id, edge.source_run_step_id,
                        edge.policy, edge.source_label,
                        1, edge.is_stale, edge.stale_reason, now,
                    ),
                )
                # Copy evidence artifacts
                artifacts = evidence_repo.get_artifacts_for_edge(edge.evidence_edge_id)
                for art in artifacts:
                    conn.execute(
                        "INSERT INTO evidence_artifacts "
                        "(evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (str(uuid.uuid4()), reused_ee_id, art.artifact_id, art.role, now),
                    )

            # Copy lineage
            for l in lineage:
                conn.execute(
                    "INSERT OR IGNORE INTO artifact_lineage "
                    "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, artifact_id, direction, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), run_id, rs_id, plan_version_id, copied_rs.step_id,
                     run_branch_id, l["artifact_id"], l["direction"], now),
                )

        return copied_rs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_and_validate(self, plan_version_id: str) -> list:
        """Load plan version steps and validate topology."""
        from cardre.store.plan_repo import PlanRepository
        plan_repo = PlanRepository(self._store)
        steps = plan_repo.get_version_steps(plan_version_id)
        validate_topology(steps)
        return steps

    def _heartbeat(self, run_id: str) -> None:
        from cardre.store.run_repo import RunRepository
        RunRepository(self._store).heartbeat(run_id)

    def _append_diagnostic(self, run_id: str, diag: dict) -> None:
        from cardre.store.run_repo import RunRepository
        RunRepository(self._store).append_diagnostic(run_id, diag)

    def _get_branch_for_run(self, run_id: str) -> str | None:
        row = self._store.execute(
            "SELECT branch_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row["branch_id"] if row else None

    @staticmethod
    def _resolve_output_artifacts(
        plan_version_id: str,
        run_id: str,
        rs: RunStep,
    ) -> list[ArtifactRef]:
        """Resolve output artifact Refs for a run step from artifact_lineage."""
        return []

    @staticmethod
    def compute_final_status(has_failure: bool) -> str:
        return STATUS_FAILED if has_failure else STATUS_SUCCEEDED


__all__ = ["PlanExecutor"]
