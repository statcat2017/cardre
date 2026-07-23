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
    ) -> None:
        self._uow_factory = uow_factory
        self._node_catalogue = node_catalogue
        self._step_runner = step_runner
        self._finalize_run = finalize_run
        self._artifact_store_factory = artifact_store_factory

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
                uow3.runs.transition(command.run_id, RunStatus.RUNNING,
                                    expected_from=(RunStatus.CREATED, RunStatus.QUEUED))
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

                persist_uow = self._uow_factory()
                try:
                    artifact_store = self._artifact_store_factory()
                    output_refs: list[ArtifactRef] = []
                    for staged in result.staged_artifacts:
                        published_path = str(artifact_store.publish(staged))
                        provisional_ref = ArtifactRef(
                            artifact_id=staged.provisional_artifact_id,
                            artifact_type=staged.artifact_type,
                            role=staged.role,
                            path=published_path,
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

                    persist_uow.commit()
                except Exception:
                    persist_uow.rollback()
                    raise
                finally:
                    persist_uow.close()

                if result.status == RunStepStatus.FAILED:
                    self._finalize_run(command.run_id, "failed")
                    return

            self._finalize_run(command.run_id, "succeeded")

        except Exception as exc:
            self._finalize_run(command.run_id, "failed", diagnostic=FinalizeDiagnostic(
                code="RUN_EXECUTION_FAILED",
                message=str(exc),
            ))
