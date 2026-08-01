"""ExecuteRun — execute a run's steps in topological order."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.application.execution.heartbeat import heartbeat
from cardre.application.runs.finalize_run import FinalizeDiagnostic, FinalizeRun
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import RunStatus, RunStep, RunStepStatus


@dataclass
class ExecuteRunCommand:
    run_id: str


class ExecuteRun:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        node_catalogue: Any,
        step_runner: Any,
        finalize_run: FinalizeRun,
        artifact_store_factory: Callable[[], Any],
        heartbeat_interval_seconds: float = 75,
    ) -> None:
        self._uow_factory = uow_factory
        self._node_catalogue = node_catalogue
        self._step_runner = step_runner
        self._finalize_run = finalize_run
        self._artifact_store_factory = artifact_store_factory
        self._heartbeat_interval_seconds = heartbeat_interval_seconds

    def __call__(self, command: ExecuteRunCommand) -> None:
        uow = self._uow_factory()
        try:
            run = uow.runs.get(command.run_id)
        finally:
            uow.close()

        if run is None:
            return
        if run.status not in ("created", "queued"):
            return

        pv_id = run.plan_version_id

        uow2 = self._uow_factory()
        try:
            pv = uow2.plans.get_version(pv_id)
            if pv is None:
                return
            steps = uow2.plans.get_version_steps(pv_id)
        finally:
            uow2.close()

        from cardre.application.execution.topology import validate_topology

        try:
            validate_topology(steps)

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

            uow3 = self._uow_factory()
            try:
                claimed = uow3.runs.transition(command.run_id, RunStatus.RUNNING,
                                              expected_from=(RunStatus.CREATED, RunStatus.QUEUED))
                if not claimed:
                    uow3.rollback()
                    return
                uow3.commit()
            except Exception:
                uow3.rollback()
                raise
            finally:
                uow3.close()
        except Exception:
            self._finalize_run(command.run_id, "failed", diagnostic=FinalizeDiagnostic(
                code="RUN_VALIDATION_FAILED",
                message="Pre-execution validation failed",
            ))
            return

        from cardre.application.execution.heartbeat import HeartbeatWatchdog

        # Lease: renew the heartbeat periodically DURING node execution so a
        # legitimate long-running node is not terminalized as stale.
        watchdog = HeartbeatWatchdog(
            self._uow_factory, command.run_id, self._heartbeat_interval_seconds,
        )
        watchdog.start()

        step_outputs: dict[str, list[Any]] = {}
        run_step_records: dict[str, RunStep] = {}

        try:
            for step in steps:
                uow_check = self._uow_factory()
                try:
                    run_check = uow_check.runs.get(command.run_id)
                finally:
                    uow_check.close()

                if run_check is not None and getattr(run_check, "cancel_requested", False):
                    self._finalize_run(command.run_id, "cancelled")
                    return

                # Publish a RunSummary artifact from persisted execution state before
                # the technical-manifest step executes.  Inject into the outputs of
                # the build-summary-report parent step so the TechnicalManifestExportNode
                # finds it as an input with role=manifest.
                if step.node_type == "cardre.technical_manifest_export" and step_outputs:
                    summary_ref = self._publish_run_summary(command, pv_id, run, step_outputs, run_step_records)
                    # Inject the RunSummary into the step's own output bucket.
                    # StepRunner._resolve_inputs later picks up own-step entries.
                    step_outputs.setdefault(step.step_id, []).append(summary_ref)
                    self._run_summary_ref = summary_ref

                hb_uow = self._uow_factory()
                try:
                    heartbeat(hb_uow, command.run_id)
                    hb_uow.commit()
                except Exception:
                    hb_uow.rollback()
                finally:
                    hb_uow.close()

                result = self._step_runner.run_step(
                    pv_id, command.run_id, step, step_outputs, run_step_records,
                )

                # Lease fence: if a stale recovery terminalized this run (or a
                # cancellation arrived) while the node was running, the worker
                # must not persist its output.
                uow_fence = self._uow_factory()
                try:
                    fence_check = uow_fence.runs.get(command.run_id)
                finally:
                    uow_fence.close()
                if fence_check is not None:
                    if getattr(fence_check, "cancel_requested", False):
                        self._finalize_run(command.run_id, "cancelled")
                        return
                    if str(fence_check.status) != RunStatus.RUNNING.value:
                        return

                persist_uow = self._uow_factory()
                artifact_outbox_ids: list[str] = []
                try:
                    artifact_store = self._artifact_store_factory()
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
                        canonical_id = persist_uow.artifacts.register(provisional_ref)
                        if canonical_id != provisional_ref.artifact_id:
                            canonical_ref = persist_uow.artifacts.get(canonical_id)
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
                    persist_uow.run_steps.insert(run_step)
                    run_step_records[step.step_id] = run_step

                    for art_ref in output_refs:
                        persist_uow.artifacts.register_lineage(
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
                            outbox_id = persist_uow.publications.enqueue_artifact(
                                run_id=command.run_id,
                                plan_version_id=pv_id,
                                run_step_id=run_step.run_step_id,
                                artifact_id=art_ref.artifact_id,
                                physical_hash=staged.physical_hash,
                                storage_key=str(artifact_store.object_path(staged.physical_hash)),
                                staging_source=str(staged.staging_path),
                            )
                            artifact_outbox_ids.append(outbox_id)
                    input_id_set = set(result.input_artifact_ids)
                    for parent_step_id in step.parent_step_ids:
                        for parent_art in step_outputs.get(parent_step_id, []):
                            if parent_art.artifact_id in input_id_set:
                                persist_uow.artifacts.register_lineage(
                                    run_id=command.run_id,
                                    run_step_id=run_step.run_step_id,
                                    plan_version_id=pv_id,
                                    step_id=step.step_id,
                                    artifact_id=parent_art.artifact_id,
                                    direction="input",
                                    branch_id=run.branch_id if hasattr(run, "branch_id") else None,
                                )

                    self._write_evidence_edges(
                        persist_uow, run_step, step, result,
                        run_step_records, run,
                    )

                    # Register lineage for the synthetic RunSummary artifact that
                    # was injected into this step's own output bucket.  The step's
                    # normal input-lineage loop over parent_step_ids does not cover
                    # own-step entries, so we register it here explicitly.
                    sr = getattr(self, "_run_summary_ref", None)
                    if sr is not None and sr.artifact_id in input_id_set:
                        persist_uow.artifacts.register_lineage(
                            run_id=command.run_id,
                            run_step_id=run_step.run_step_id,
                            plan_version_id=pv_id,
                            step_id=step.step_id,
                            artifact_id=sr.artifact_id,
                            direction="input",
                            branch_id=run.branch_id if hasattr(run, "branch_id") else None,
                        )

                    persist_uow.commit()
                except Exception:
                    persist_uow.rollback()
                    raise
                finally:
                    persist_uow.close()

                # The filesystem side of the publication happens only after the
                # DB mutation committed. On failure here the DB already has the
                # descriptor + outbox row, so reconciliation can retry; the
                # staging file is not orphaned into objects/.
                artifact_store = self._artifact_store_factory()
                for art_ref in output_refs:
                    staged = staged_by_artifact.get(art_ref.artifact_id)
                    if staged is not None:
                        artifact_store.finalize(staged)
                if artifact_outbox_ids:
                    pub_uow = self._uow_factory()
                    try:
                        for outbox_id in artifact_outbox_ids:
                            pub_uow.publications.mark_published(outbox_id)
                        pub_uow.commit()
                    except Exception:
                        pub_uow.rollback()
                        raise
                    finally:
                        pub_uow.close()

                if result.status == RunStepStatus.FAILED:
                    self._finalize_run(command.run_id, "failed")
                    return

            # Cancellation can arrive during the final node: re-read the run
            # immediately before success finalization. If cancelled, the run
            # must end cancelled, never succeeded.
            uow_final = self._uow_factory()
            try:
                final_check = uow_final.runs.get(command.run_id)
            finally:
                uow_final.close()
            if final_check is not None and getattr(final_check, "cancel_requested", False):
                self._finalize_run(command.run_id, "cancelled")
                return

            self._finalize_run(command.run_id, "succeeded")

        except Exception as exc:
            self._finalize_run(command.run_id, "failed", diagnostic=FinalizeDiagnostic(
                code="RUN_EXECUTION_FAILED",
                message=str(exc),
            ))
        finally:
            watchdog.stop()

    def _publish_run_summary(
        self,
        command: ExecuteRunCommand,
        pv_id: str,
        run: Any,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStep],
    ) -> ArtifactRef:
        """Build and publish a RunSummary artifact from persisted execution state.

        Reads run steps and artifact lineage from the database so that
        input/output IDs, warnings and errors reflect what was actually
        persisted rather than what was staged in step_outputs.

        Returns the registered ArtifactRef so callers can inject it into
        step inputs for the technical-manifest step to consume.
        """
        from cardre.domain.evidence.kinds import EvidenceKind
        from cardre.domain.evidence.schemas import SCHEMA_RUN_SUMMARY

        plan_steps: dict[str, Any] = {}
        pv_uow = self._uow_factory()
        try:
            for spec in pv_uow.plans.get_version_steps(pv_id):
                plan_steps[spec.step_id] = spec
        finally:
            pv_uow.close()

        ruow = self._uow_factory()
        try:
            run_steps = ruow.run_steps.get_for_run(command.run_id)
        finally:
            ruow.close()

        steps_data: list[dict[str, Any]] = []
        artifacts_data: list[dict[str, Any]] = []
        seen_artifact_ids: set[str] = set()

        for rs in run_steps:
            spec = plan_steps.get(rs.step_id)
            lineage_ruow = self._uow_factory()
            try:
                lineage = lineage_ruow.artifacts.artifacts_for_run_step(rs.run_step_id)
            finally:
                lineage_ruow.close()
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
                    line_ruow = self._uow_factory()
                    try:
                        art = line_ruow.artifacts.get(aid)
                    finally:
                        line_ruow.close()
                    if art is not None:
                        artifacts_data.append({
                            "artifact_id": art.artifact_id,
                            "artifact_type": art.artifact_type,
                            "role": art.role,
                            "physical_hash": art.physical_hash,
                            "logical_hash": art.logical_hash,
                            "media_type": art.media_type,
                        })

        summary = {
            "run_id": command.run_id,
            "plan_version_id": pv_id,
            "steps": steps_data,
            "artifacts": artifacts_data,
        }

        artifact_store = self._artifact_store_factory()
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
        finally:
            mark_uow.close()
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
