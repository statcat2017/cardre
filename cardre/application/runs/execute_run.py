"""ExecuteRun — execute a run's steps in topological order."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from cardre.application.execution.heartbeat import heartbeat
from cardre.application.runs.finalize_run import FinalizeDiagnostic, FinalizeRun
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import LeaseLost
from cardre.domain.run import RunStatus, RunStep, RunStepStatus


@contextmanager
def _read_uow(factory: Callable[[], Any]):
    """Open + close a UoW for reads; rolls back any uncommitted work on error."""
    uow = factory()
    try:
        yield uow
    finally:
        uow.close()


@contextmanager
def _fenced_persist(factory: Callable[[], Any], run_id: str, worker_generation: int):
    """Open a mutation UoW, assert the lease, and commit on success.

    Raises ``LeaseLost`` (after rollback) if the run was cancelled or its
    lease was lost between the node finishing and this transaction.
    """
    uow = factory()
    try:
        uow.runs.assert_running_lease(run_id, worker_generation)
        yield uow
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()


@dataclass
class ExecuteRunCommand:
    run_id: str


class _RunSummaryHook:
    """Publishes the RunSummary before the technical-manifest step runs and
    remembers the ref so its lineage can be registered with that step.

    Owned per-``ExecuteRun.__call__`` so ``ExecuteRun`` stays reentrant — no
    instance-state side-channel between the loop and the persist block.
    """

    def __init__(self, execute_run: ExecuteRun) -> None:
        self._execute_run = execute_run
        self._summary_ref: ArtifactRef | None = None

    def before_step(
        self,
        step: Any,
        command: ExecuteRunCommand,
        pv_id: str,
        run: Any,
        step_outputs: dict[str, list[Any]],
        run_step_records: dict[str, RunStep],
        worker_generation: int,
    ) -> None:
        if step.node_type != "cardre.technical_manifest_export" or not step_outputs:
            return
        self._summary_ref = self._execute_run._publish_run_summary(
            command, pv_id, run, step_outputs, run_step_records, worker_generation,
        )
        # Inject the RunSummary into the step's own output bucket.
        # StepRunner._resolve_inputs later picks up own-step entries.
        if self._summary_ref is not None:
            step_outputs.setdefault(step.step_id, []).append(self._summary_ref)

    def register_own_lineage(
        self,
        uow: Any,
        command: ExecuteRunCommand,
        pv_id: str,
        run: Any,
        run_step: RunStep,
        input_id_set: set[str],
    ) -> None:
        # The step's normal input-lineage loop over parent_step_ids does not
        # cover own-step entries, so the synthetic RunSummary lineage is
        # registered here explicitly.
        sr = self._summary_ref
        if sr is not None and sr.artifact_id in input_id_set:
            uow.artifacts.register_lineage(
                run_id=command.run_id,
                run_step_id=run_step.run_step_id,
                plan_version_id=pv_id,
                step_id=run_step.step_id,
                artifact_id=sr.artifact_id,
                direction="input",
                branch_id=run.branch_id if hasattr(run, "branch_id") else None,
            )


class ExecuteRun:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        node_catalogue: Any,
        step_runner: Any,
        finalize_run: FinalizeRun,
        artifact_store_factory: Callable[[], Any],
        heartbeat_interval_seconds: float = 75,
        read_only_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._node_catalogue = node_catalogue
        self._step_runner = step_runner
        self._finalize_run = finalize_run
        self._artifact_store_factory = artifact_store_factory
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._read_only_factory = read_only_factory or uow_factory

    def __call__(self, command: ExecuteRunCommand) -> None:
        # FsArtifactStore is stateless and project-bound — construct once per
        # run and reuse across all steps (P3-2).
        self._artifact_store = self._artifact_store_factory()

        with _read_uow(self._uow_factory) as uow:
            run = uow.runs.get(command.run_id)
        if run is None or run.status not in ("created", "queued"):
            return

        pv_id = run.plan_version_id
        with _read_uow(self._uow_factory) as uow:
            pv = uow.plans.get_version(pv_id)
            steps = uow.plans.get_version_steps(pv_id) if pv is not None else None
        if pv is None or steps is None:
            return

        from cardre.application.execution.topology import validate_topology

        try:
            validate_topology(steps)
            self._assert_nodes_available(steps)
            worker_generation = self._claim_run(command)
        except Exception:
            self._finalize_after_pre_exec_failure(command)
            return
        if worker_generation is None:
            return

        from cardre.application.execution.heartbeat import HeartbeatWatchdog

        # Lease: renew the heartbeat periodically DURING node execution so a
        # legitimate long-running node is not terminalized as stale.
        watchdog = HeartbeatWatchdog(
            self._uow_factory, command.run_id, self._heartbeat_interval_seconds,
        )
        watchdog.start()
        try:
            self._execute_steps(command, pv_id, run, steps, worker_generation)
        except Exception as exc:
            self._finalize_run(command.run_id, "failed", diagnostic=FinalizeDiagnostic(
                code="RUN_EXECUTION_FAILED",
                message=str(exc),
            ))
        finally:
            watchdog.stop()

    # -- orchestration helpers ------------------------------------------------

    def _assert_nodes_available(self, steps: list[Any]) -> None:
        unavailable = []
        for step in steps:
            av = self._node_catalogue.availability(step.node_type)
            if not av.available:
                unavailable.append(step.step_id)
        if unavailable:
            from cardre.domain.errors import PlanContainsUnavailableNodesError

            raise PlanContainsUnavailableNodesError(
                [{"step_id": sid, "node_type": "", "node_version": "", "reason": "Node is unavailable."}
                 for sid in unavailable]
            )

    def _claim_run(self, command: ExecuteRunCommand) -> int | None:
        """Transition created/queued -> running and begin a worker lease.

        Returns the worker generation, or ``None`` if the run was already
        claimed/terminalized concurrently.
        """
        with self._uow_factory() as uow:
            claimed = uow.runs.transition(
                command.run_id, RunStatus.RUNNING,
                expected_from=(RunStatus.CREATED, RunStatus.QUEUED),
            )
            if not claimed:
                return None
            return uow.runs.begin_worker_generation(command.run_id)

    def _finalize_after_pre_exec_failure(self, command: ExecuteRunCommand) -> None:
        # If a cancellation landed while we validated, the run must end
        # cancelled, not failed (a created/queued run is terminalized by
        # CancelRun before we reach here; a running run is cooperative).
        with _read_uow(self._uow_factory) as uow:
            cancel_check = uow.runs.get(command.run_id)
        if cancel_check is not None and getattr(cancel_check, "cancel_requested", False):
            self._finalize_run(command.run_id, "cancelled")
            return
        self._finalize_run(command.run_id, "failed", diagnostic=FinalizeDiagnostic(
            code="RUN_VALIDATION_FAILED",
            message="Pre-execution validation failed",
        ))

    def _is_cancelled(self, command: ExecuteRunCommand) -> bool:
        with _read_uow(self._uow_factory) as uow:
            run = uow.runs.get(command.run_id)
        return run is not None and getattr(run, "cancel_requested", False)

    def _heartbeat(self, command: ExecuteRunCommand) -> None:
        uow = self._uow_factory()
        try:
            heartbeat(uow, command.run_id)
            uow.commit()
        except Exception:
            uow.rollback()
        finally:
            uow.close()

    def _execute_steps(
        self,
        command: ExecuteRunCommand,
        pv_id: str,
        run: Any,
        steps: list[Any],
        worker_generation: int,
    ) -> None:
        step_outputs: dict[str, list[Any]] = {}
        run_step_records: dict[str, RunStep] = {}
        summary_hook = _RunSummaryHook(self)
        for step in steps:
            if self._is_cancelled(command):
                self._finalize_run(command.run_id, "cancelled")
                return

            summary_hook.before_step(
                step, command, pv_id, run, step_outputs, run_step_records, worker_generation,
            )
            self._heartbeat(command)

            result = self._step_runner.run_step(
                pv_id, command.run_id, step, step_outputs, run_step_records,
            )

            try:
                output_refs, staged_by_artifact, outbox_ids = self._persist_step_outputs(
                    command, step, pv_id, run, result, step_outputs, run_step_records,
                    worker_generation, summary_hook,
                )
            except LeaseLost as exc:
                if "cancellation" in str(exc):
                    self._finalize_run(command.run_id, "cancelled")
                return

            self._finalize_artifacts(output_refs, staged_by_artifact, outbox_ids)

            if result.status == RunStepStatus.FAILED:
                self._finalize_run(command.run_id, "failed")
                return

        # Cancellation can arrive during the final node: re-read the run
        # immediately before success finalization. If cancelled, the run must
        # end cancelled, never succeeded.
        if self._is_cancelled(command):
            self._finalize_run(command.run_id, "cancelled")
            return

        # Pass the worker generation so success finalization cannot beat a
        # concurrent cancellation: the terminal transition is conditional on
        # running + cancel_requested=0 + lease ownership inside its own txn.
        self._finalize_run(command.run_id, "succeeded", worker_generation=worker_generation)

    def _persist_step_outputs(
        self,
        command: ExecuteRunCommand,
        step: Any,
        pv_id: str,
        run: Any,
        result: Any,
        step_outputs: dict[str, list[Any]],
        run_step_records: dict[str, RunStep],
        worker_generation: int,
        summary_hook: _RunSummaryHook,
    ) -> tuple[list[ArtifactRef], dict[str, Any], list[str]]:
        """Register artifacts, run-step, lineage, evidence edges, and outbox
        rows inside one fenced transaction.

        Returns ``(output_refs, staged_by_artifact, outbox_ids)`` for the
        post-commit filesystem finalization. The lease fence is asserted
        atomically inside the ``BEGIN IMMEDIATE`` transaction: a cancellation
        or terminalization that raced the node finishing causes a
        ``LeaseLost`` and nothing is written.
        """
        artifact_store = self._artifact_store
        with _fenced_persist(self._uow_factory, command.run_id, worker_generation) as uow:
            output_refs: list[ArtifactRef] = []
            staged_by_artifact: dict[str, Any] = {}
            for staged in result.staged_artifacts:
                dest = artifact_store.dest_path(staged)
                provisional_ref = ArtifactRef(
                    artifact_id=staged.provisional_artifact_id,
                    artifact_type=staged.artifact_type,
                    role=staged.role,
                    path=str(dest),
                    physical_hash=staged.physical_hash,
                    logical_hash=staged.logical_hash,
                    media_type=staged.media_type,
                    metadata=staged.metadata,
                )
                canonical_id = uow.artifacts.register(provisional_ref)
                if canonical_id != provisional_ref.artifact_id:
                    canonical_ref = uow.artifacts.get(canonical_id)
                    if canonical_ref is not None:
                        output_refs.append(canonical_ref)
                    else:
                        output_refs.append(provisional_ref)
                else:
                    output_refs.append(provisional_ref)
                staged_by_artifact[canonical_id] = staged

            step_outputs[step.step_id] = output_refs

            run_step = RunStep(
                run_step_id=f"{command.run_id}-{step.step_id}",
                run_id=command.run_id,
                step_id=step.step_id,
                plan_version_id=pv_id,
                status=RunStepStatus.SUCCEEDED if result.status == RunStepStatus.SUCCEEDED else RunStepStatus.FAILED,
                started_at=utc_now_iso(),
                finished_at=utc_now_iso(),
                execution_fingerprint=result.fingerprint,
                warnings=result.warnings,
                errors=result.errors,
            )
            uow.run_steps.insert(run_step)
            run_step_records[step.step_id] = run_step

            outbox_ids: list[str] = []
            for art_ref in output_refs:
                uow.artifacts.register_lineage(
                    run_id=command.run_id,
                    run_step_id=run_step.run_step_id,
                    plan_version_id=pv_id,
                    step_id=step.step_id,
                    artifact_id=art_ref.artifact_id,
                    direction="output",
                    branch_id=run.branch_id if hasattr(run, "branch_id") else None,
                )
                staged = staged_by_artifact.get(art_ref.artifact_id)
                if staged is not None:
                    outbox_id = uow.publications.enqueue_artifact(
                        run_id=command.run_id,
                        plan_version_id=pv_id,
                        run_step_id=run_step.run_step_id,
                        artifact_id=art_ref.artifact_id,
                        physical_hash=staged.physical_hash,
                        storage_key=str(artifact_store.object_path(staged.physical_hash)),
                        staging_source=str(staged.staging_path),
                    )
                    outbox_ids.append(outbox_id)

            input_id_set = set(result.input_artifact_ids)
            for parent_step_id in step.parent_step_ids:
                for parent_art in step_outputs.get(parent_step_id, []):
                    if parent_art.artifact_id in input_id_set:
                        uow.artifacts.register_lineage(
                            run_id=command.run_id,
                            run_step_id=run_step.run_step_id,
                            plan_version_id=pv_id,
                            step_id=step.step_id,
                            artifact_id=parent_art.artifact_id,
                            direction="input",
                            branch_id=run.branch_id if hasattr(run, "branch_id") else None,
                        )

            self._write_evidence_edges(
                uow, run_step, step, result, run_step_records, run,
            )

            summary_hook.register_own_lineage(uow, command, pv_id, run, run_step, input_id_set)

        return output_refs, staged_by_artifact, outbox_ids

    def _finalize_artifacts(
        self,
        output_refs: list[ArtifactRef],
        staged_by_artifact: dict[str, Any],
        outbox_ids: list[str],
    ) -> None:
        # The filesystem side of the publication happens only after the DB
        # mutation committed. On failure here the DB already has the
        # descriptor + outbox row, so reconciliation can retry; the staging
        # file is not orphaned into objects/.
        artifact_store = self._artifact_store
        for art_ref in output_refs:
            staged = staged_by_artifact.get(art_ref.artifact_id)
            if staged is not None:
                artifact_store.finalize(staged)
        if outbox_ids:
            pub_uow = self._uow_factory()
            try:
                for outbox_id in outbox_ids:
                    pub_uow.publications.mark_published(outbox_id)
                pub_uow.commit()
            except Exception:
                pub_uow.rollback()
                raise
            finally:
                pub_uow.close()

    def _publish_run_summary(
        self,
        command: ExecuteRunCommand,
        pv_id: str,
        run: Any,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStep],
        worker_generation: int,
    ) -> ArtifactRef | None:
        """Build and publish a RunSummary artifact from persisted execution state.

        Reads run steps and artifact lineage from the database so that
        input/output IDs, warnings and errors reflect what was actually
        persisted rather than what was staged in step_outputs.

        Returns the registered ArtifactRef (or ``None`` if the run lost its
        lease before publication) so callers can inject it into step inputs for
        the technical-manifest step to consume.
        """
        from cardre.domain.evidence.kinds import EvidenceKind
        from cardre.domain.evidence.schemas import SCHEMA_RUN_SUMMARY

        plan_steps: dict[str, Any] = {}
        run_steps = None
        # All reads happen through one read-only UoW — never a write UoW with
        # an eager BEGIN IMMEDIATE (R1 invariant, P2-3).
        summary_uow = self._read_only_factory()
        try:
            for spec in summary_uow.plans.get_version_steps(pv_id):
                plan_steps[spec.step_id] = spec
            run_steps = summary_uow.run_steps.get_for_run(command.run_id)

            steps_data: list[dict[str, Any]] = []
            artifacts_data: list[dict[str, Any]] = []
            seen_artifact_ids: set[str] = set()

            for rs in run_steps:
                spec = plan_steps.get(rs.step_id)
                lineage = summary_uow.artifacts.artifacts_for_run_step(rs.run_step_id)
                input_ids = [a.artifact_id for d, a in lineage if d == "input"]
                output_ids = [a.artifact_id for d, a in lineage if d == "output"]
                input_logical_hashes = [a.logical_hash for d, a in lineage if d == "input"]
                output_logical_hashes = [a.logical_hash for d, a in lineage if d == "output"]
                steps_data.append({
                    "step_id": rs.step_id,
                    "node_type": spec.node_type if spec else "",
                    "node_version": spec.node_version if spec else "",
                    "status": rs.status.value,
                    "params_hash": spec.params_hash if spec else "",
                    "input_artifact_logical_hashes": input_logical_hashes,
                    "output_artifact_logical_hashes": output_logical_hashes,
                    "input_artifact_ids": input_ids,
                    "output_artifact_ids": output_ids,
                    "warnings": rs.warnings,
                    "errors": rs.errors,
                })
                for aid in output_ids + input_ids:
                    if aid not in seen_artifact_ids:
                        seen_artifact_ids.add(aid)
                        art = summary_uow.artifacts.get(aid)
                        if art is not None:
                            artifacts_data.append({
                                "artifact_id": art.artifact_id,
                                "artifact_type": art.artifact_type,
                                "role": art.role,
                                "physical_hash": art.physical_hash,
                                "logical_hash": art.logical_hash,
                                "media_type": art.media_type,
                            })
        finally:
            summary_uow.close()

        summary = {
            "run_id": command.run_id,
            "plan_version_id": pv_id,
            "steps": steps_data,
            "artifacts": artifacts_data,
        }

        artifact_store = self._artifact_store
        staged = artifact_store.stage_json(
            role="manifest",
            kind=EvidenceKind.RUN_SUMMARY.value,
            payload=summary,
            metadata={"schema_version": SCHEMA_RUN_SUMMARY},
        )
        dest = artifact_store.dest_path(staged)
        summary_ref = ArtifactRef(
            artifact_id=staged.provisional_artifact_id,
            artifact_type=staged.artifact_type,
            role=staged.role,
            path=str(dest),
            physical_hash=staged.physical_hash,
            logical_hash=staged.logical_hash,
            media_type=staged.media_type,
            metadata=staged.metadata,
        )
        uow = self._uow_factory()
        try:
            # Lease fence inside the summary's own transaction: a run that was
            # cancelled or terminalized while we were reading state must not
            # accept a RunSummary publication. Mirrors the normal step-output
            # fence so no artifact/outbox row is left for a terminal run.
            try:
                uow.runs.assert_running_lease(command.run_id, worker_generation)
            except LeaseLost:
                uow.rollback()
                return None
            uow.artifacts.register(summary_ref)
            outbox_id = uow.publications.enqueue_artifact(
                run_id=command.run_id,
                plan_version_id=pv_id,
                run_step_id="",
                artifact_id=summary_ref.artifact_id,
                physical_hash=staged.physical_hash,
                storage_key=str(dest),
                staging_source=str(staged.staging_path),
            )
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
        artifact_store.finalize(staged)
        mark_uow = self._uow_factory()
        try:
            mark_uow.publications.mark_published(outbox_id)
            mark_uow.commit()
        except Exception:
            mark_uow.rollback()
            raise
        return summary_ref

    @staticmethod
    def _write_evidence_edges(
        uow: Any,
        run_step: RunStep,
        step: Any,
        result: Any,
        run_step_records: dict[str, RunStep],
        run: Any,
    ) -> None:
        """Create evidence edges from parent-child step relationships.

        For each parent step that contributed consumed artifacts, an evidence
        edge is created linking this step to its parent.  One ``EvidenceArtifact``
        row is inserted for every consumed artifact on that edge.

        Parent steps whose outputs were entirely filtered out (no artifacts
        consumed) produce no edge, keeping the evidence graph accurate.
        """
        import uuid

        from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge

        input_map = getattr(result, "input_artifact_ids_by_parent", {}) or {}
        for parent_rs in result.parent_run_steps:
            consumed_ids = input_map.get(parent_rs.step_id, [])
            if not consumed_ids:
                continue
            edge = EvidenceEdge(
                evidence_edge_id=str(uuid.uuid4()),
                run_id=run_step.run_id,
                run_step_id=run_step.run_step_id,
                plan_version_id=run_step.plan_version_id,
                step_id=run_step.step_id,
                parent_step_id=parent_rs.step_id,
                source_run_id=run_step.run_id,
                source_run_step_id=parent_rs.run_step_id,
                policy="exact",
                source_label="parent",
                is_reused=False,
                is_stale=False,
            )
            uow.evidence.insert_edge(edge)
            for aid in consumed_ids:
                ea = EvidenceArtifact(
                    evidence_artifact_id=str(uuid.uuid4()),
                    evidence_edge_id=edge.evidence_edge_id,
                    artifact_id=aid,
                    role="input",
                    created_at=run_step.started_at or "",
                )
                uow.evidence.insert_artifact(ea)
