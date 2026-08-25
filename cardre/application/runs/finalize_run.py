"""FinalizeRun — transition run status and publish a canonical manifest.

The terminal status transition and a manifest publication outbox record are
persisted in one transaction. The manifest is published to the filesystem
only after that transaction commits, so a DB commit failure can never leave a
terminal manifest paired with a non-terminal run row. After publishing, the
outbox record is marked published; a publish failure is recorded on the
outbox row (``failed``) and re-raised, and startup reconciliation retries
incomplete publications.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre._version import __version__
from cardre.application.ports.clock import ClockPort
from cardre.application.ports.manifest_publisher import ManifestPublisherPort
from cardre.application.publications.publisher import PublicationPublisher
from cardre.domain.diagnostics import JsonDict
from cardre.domain.errors import CardreError, ErrorCode
from cardre.domain.manifest import (
    MANIFEST_VERSION,
    RunManifest,
    RunManifestStep,
    compute_manifest_hash,
    compute_pathway_hash,
)
from cardre.domain.run import RunStatus


@dataclass
class FinalizeDiagnostic:
    code: str
    message: str


class FinalizeRun:
    # Sentinel distinguishing "stale mode not requested" from "the observed
    # heartbeat was NULL". NULL is a legitimate stale value, so it must not be
    # conflated with "no stale mode".
    _STALE_UNSET = object()

    def __init__(
        self,
        uow_factory: Callable[[], Any],
        manifest_publisher: ManifestPublisherPort,
        publication_publisher: PublicationPublisher,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._manifest_publisher = manifest_publisher
        self._publication_publisher = publication_publisher
        self._clock = clock

    def __call__(
        self,
        run_id: str,
        status: str,
        steps: list[dict[str, Any]] | None = None,
        diagnostic: FinalizeDiagnostic | None = None,
        worker_generation: int | None = None,
        stale_heartbeat_at: Any = _STALE_UNSET,
    ) -> None:
        with self._uow_factory() as uow:
            run_record = uow.runs.get(run_id)
            if run_record is None:
                raise CardreError(
                    f"Run {run_id!r} not found for finalization",
                    code=ErrorCode.RUN_NOT_FOUND,
                    context={"run_id": run_id},
                )

            target = RunStatus(status)
            if target == RunStatus.SUCCEEDED and worker_generation is None:
                raise TypeError(
                    "FinalizeRun('succeeded') requires worker_generation: success "
                    "finalization must prove lease ownership"
                )
            if target in (RunStatus.FAILED, RunStatus.CANCELLED):
                expected_from: tuple[RunStatus, ...] = (RunStatus.SUBMITTED, RunStatus.RUNNING)
            else:
                expected_from = (RunStatus.RUNNING,)

            if target == RunStatus.SUCCEEDED:
                # Success must not beat a concurrent cancellation: transition only
                # while still running, cancellation not requested, and (when the
                # worker provided its generation) lease ownership is intact.
                transitioned = uow.runs.transition_success(run_id, worker_generation)
                if not transitioned:
                    actual = uow.runs.get(run_id)
                    if actual is not None and actual.cancel_requested:
                        # Cancellation won the race — finalize as cancelled in the
                        # same transaction.
                        status = "cancelled"
                        target = RunStatus.CANCELLED
                        transitioned = uow.runs.transition(
                            run_id, target,
                            expected_from=(RunStatus.SUBMITTED, RunStatus.RUNNING),
                        )
                        if not transitioned:
                            actual2 = uow.runs.get(run_id)
                            raise RunAlreadyFinalised(run_id, str(actual2.status) if actual2 else "unknown")
                    else:
                        raise RunAlreadyFinalised(run_id, str(actual.status) if actual else "unknown")
            elif target == RunStatus.INTERRUPTED and stale_heartbeat_at is not FinalizeRun._STALE_UNSET:
                # Stale-interruption mode: conditionally transition the stale run
                # only if its heartbeat is still exactly the observed value
                # (compare-and-set; a NULL heartbeat is a legitimate observed
                # value). If the worker renewed it or the run already
                # terminalized, the transition loses and we return silently with
                # no mutations — no diagnostic, manifest, or outbox record.
                transitioned = uow.runs.transition_interrupted(run_id, stale_heartbeat_at)
                if not transitioned:
                    return
            else:
                transitioned = uow.runs.transition(run_id, target, expected_from=expected_from)
                if not transitioned:
                    actual = uow.runs.get(run_id)
                    raise RunAlreadyFinalised(run_id, str(actual.status) if actual else "unknown")

            # Only after a successful conditional transition do we append the
            # diagnostic, so a lost stale race never commits a false RUN_STALE.
            if diagnostic is not None:
                uow.runs.append_diagnostic(run_id, {"code": diagnostic.code, "message": diagnostic.message})

            # Invalidate any surviving worker of the old generation: a terminal
            # transition (whether this worker finishing or a stale recovery
            # interrupting) means no earlier-generation worker may write output.
            uow.runs.begin_worker_generation(run_id)

            # A run terminalized before any worker claimed it (dispatch failure,
            # pre-execution validation failure, pre-claim cancellation) still
            # has a durable pending-dispatch row. Clear it in the same
            # transaction so startup reconciliation does not redispatch a
            # terminal run on every boot. This is a no-op for runs that already
            # claimed (their row was removed on claim).
            uow.dispatches.remove(run_id)

            manifest_steps = self._build_manifest_steps(uow, run_id)
            payload = self._build_manifest(
                run_id, status, manifest_steps, diagnostic, run_record, uow,
            )
            self._complete_payload_hashes(payload)
            outbox_id = uow.publications.enqueue_manifest(
                run_id=run_id,
                plan_version_id=str(run_record.plan_version_id),
                payload=payload,
                manifest_hash=payload["manifest_hash"],
            )

        # The transaction above committed (terminal run row + outbox record are
        # durable). Only now do we touch the filesystem via the publication
        # protocol, which runs the manifest write then marks the row (and marks
        # it failed + re-raises on error so the caller's failure path runs).
        self._publication_publisher.publish(
            outbox_id,
            lambda: self._manifest_publisher.publish(run_id, payload),
        )

    @staticmethod
    def _complete_payload_hashes(payload: JsonDict) -> None:
        """Fill pathway_hash and manifest_hash so the outbox stores the same
        canonical payload the publisher writes."""
        steps = payload.get("steps", [])
        if not payload.get("pathway_hash"):
            payload["pathway_hash"] = compute_pathway_hash(steps)
        payload["manifest_version"] = MANIFEST_VERSION
        payload["manifest_hash"] = compute_manifest_hash(payload)

    def _build_manifest_steps(self, uow: Any, run_id: str) -> list[JsonDict]:
        run_steps = uow.run_steps.get_for_run(run_id)
        pv_id = run_steps[0].plan_version_id if run_steps else ""
        plan_steps = {}
        step_edges: dict[str, list[str]] = {}
        if pv_id:
            for spec in uow.plans.get_version_steps(pv_id):
                plan_steps[spec.step_id] = spec
            # Plan-step edges are canonical manifest integrity data: a failure
            # to load them must surface, never silently produce an empty graph.
            all_edges = uow.steps.get_all_edges(pv_id) if hasattr(uow, "steps") else []
            for edge in all_edges:
                child = edge.get("child_step_id", "")
                parent = edge.get("parent_step_id", "")
                step_edges.setdefault(child, []).append(parent)

        result: list[JsonDict] = []
        for rs in run_steps:
            lineage = uow.artifacts.artifacts_for_run_step(rs.run_step_id)
            input_ids = [a.artifact_id for d, a in lineage if d == "input"]
            output_ids = [a.artifact_id for d, a in lineage if d == "output"]
            spec = plan_steps.get(rs.step_id)
            if spec is None:
                # A run step that has no plan specification is a manifest
                # integrity failure: the canonical manifest must not fall back
                # to empty node/category fields.
                raise CardreError(
                    f"Run step {rs.step_id!r} of run {run_id!r} has no plan "
                    "specification; cannot build a canonical manifest",
                    code=ErrorCode.MANIFEST_STEP_MISSING,
                    context={"run_id": run_id, "step_id": rs.step_id, "plan_version_id": pv_id},
                )
            result.append({
                "step_id": rs.step_id,
                "canonical_step_id": spec.canonical_step_id,
                "node_type": rs.execution_fingerprint.get("node_type", spec.node_type),
                "node_version": rs.execution_fingerprint.get("node_version", spec.node_version),
                "category": spec.category,
                "status": rs.status.value,
                "action": "",
                "is_carried_forward": False,
                "started_at": rs.started_at,
                "finished_at": rs.finished_at,
                "params": rs.execution_fingerprint.get("params", spec.params),
                "params_hash": rs.execution_fingerprint.get("params_hash", spec.params_hash),
                "parent_step_ids": step_edges.get(rs.step_id, []),
                "input_artifact_ids": input_ids,
                "output_artifact_ids": output_ids,
                "warnings": rs.warnings,
                "errors": rs.errors,
                "execution_fingerprint": rs.execution_fingerprint,
            })
        return result

    def _build_manifest(
        self,
        run_id: str,
        status: str,
        steps: list[JsonDict],
        diagnostic: FinalizeDiagnostic | None,
        run_record: Any,
        uow: Any,
    ) -> JsonDict:
        plan_version_id = getattr(run_record, "plan_version_id", "") or ""
        started_at = getattr(run_record, "started_at", "") or ""

        plan_id = ""
        project_id = ""
        if plan_version_id and uow is not None:
            # Plan/project identity is canonical manifest integrity data. A
            # resolution failure must surface rather than publish an empty
            # identity.
            plan_id = uow.plans.get_plan_id_for_version(plan_version_id) or ""
            if not plan_id:
                raise CardreError(
                    f"Plan version {plan_version_id!r} has no plan record; "
                    "cannot build a canonical manifest",
                    code=ErrorCode.MANIFEST_PLAN_MISSING,
                    context={"run_id": run_id, "plan_version_id": plan_version_id},
                )
            plan = uow.plans.get_plan(plan_id)
            if plan is None:
                raise CardreError(
                    f"Plan {plan_id!r} not found; cannot build a canonical manifest",
                    code=ErrorCode.MANIFEST_PLAN_MISSING,
                    context={"run_id": run_id, "plan_id": plan_id},
                )
            project_id = plan.project_id or ""
            if not project_id:
                raise CardreError(
                    f"Plan {plan_id!r} has no project; cannot build a canonical manifest",
                    code=ErrorCode.MANIFEST_PLAN_MISSING,
                    context={"run_id": run_id, "plan_id": plan_id},
                )

        # Diagnostics are auxiliary (non-integrity) — read them without
        # silently substituting an empty list on a transient read error.
        diagnostics: list[JsonDict] = []
        if uow is not None:
            diagnostics = list(uow.runs.get_diagnostics(run_id))
        if diagnostic is not None and not any(
            d.get("code") == diagnostic.code and d.get("message") == diagnostic.message
            for d in diagnostics
        ):
            diagnostics.append({"code": diagnostic.code, "message": diagnostic.message})

        manifest = RunManifest(
            manifest_version=MANIFEST_VERSION,
            run_id=run_id,
            plan_version_id=plan_version_id,
            plan_id=plan_id,
            project_id=project_id,
            started_at=started_at,
            finished_at=self._clock.now_iso(),
            status=status,
            cardre_version=__version__,
            steps=[RunManifestStep(**s) for s in steps],
            diagnostics=diagnostics,
        )
        return manifest.to_dict()


class RunAlreadyFinalised(CardreError):
    def __init__(self, run_id: str, actual_status: str) -> None:
        super().__init__(
            f"Run {run_id} was already finalised (status={actual_status})"
        )
