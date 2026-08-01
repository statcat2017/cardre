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

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre._version import __version__
from cardre.application.ports.manifest_publisher import ManifestPublisherPort
from cardre.domain.diagnostics import JsonDict, utc_now_iso
from cardre.domain.errors import CardreError
from cardre.domain.manifest import (
    MANIFEST_VERSION,
    compute_manifest_hash,
    compute_pathway_hash,
)
from cardre.domain.run import RunStatus


@dataclass
class FinalizeDiagnostic:
    code: str
    message: str


class FinalizeRun:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        manifest_publisher: ManifestPublisherPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._manifest_publisher = manifest_publisher

    def __call__(
        self,
        run_id: str,
        status: str,
        steps: list[dict[str, Any]] | None = None,
        diagnostic: FinalizeDiagnostic | None = None,
    ) -> None:
        with self._uow_factory() as uow:
            run_record = uow.runs.get(run_id)
            if run_record is None:
                raise CardreError(
                    f"Run {run_id!r} not found for finalization",
                    code="RUN_NOT_FOUND",
                    context={"run_id": run_id},
                )

            target = RunStatus(status)
            if target in (RunStatus.FAILED, RunStatus.CANCELLED):
                expected_from: tuple[RunStatus, ...] = (RunStatus.CREATED, RunStatus.QUEUED, RunStatus.RUNNING)
            else:
                expected_from = (RunStatus.RUNNING,)

            if diagnostic is not None:
                uow.runs.append_diagnostic(run_id, {"code": diagnostic.code, "message": diagnostic.message})

            transitioned = uow.runs.transition(run_id, target, expected_from=expected_from)
            if not transitioned:
                actual = uow.runs.get(run_id)
                raise RunAlreadyFinalised(run_id, str(actual.status) if actual else "unknown")

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
        # durable). Only now do we touch the filesystem. On failure the outbox
        # row records the durable failure so reconciliation can retry.
        try:
            self._manifest_publisher.publish(run_id, payload)
        except Exception as exc:
            with self._uow_factory() as mark_uow:
                mark_uow.publications.mark_failed(outbox_id, str(exc))
                mark_uow.commit()
            raise
        else:
            with self._uow_factory() as mark_uow:
                mark_uow.publications.mark_published(outbox_id)
                mark_uow.commit()

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
            try:
                all_edges = uow.steps.get_all_edges(pv_id) if hasattr(uow, "steps") else []
                for edge in all_edges:
                    child = edge.get("child_step_id", "")
                    parent = edge.get("parent_step_id", "")
                    step_edges.setdefault(child, []).append(parent)
            except Exception:
                pass

        result: list[JsonDict] = []
        for rs in run_steps:
            lineage = uow.artifacts.artifacts_for_run_step(rs.run_step_id)
            input_ids = [a.artifact_id for d, a in lineage if d == "input"]
            output_ids = [a.artifact_id for d, a in lineage if d == "output"]
            spec = plan_steps.get(rs.step_id)
            result.append({
                "step_id": rs.step_id,
                "canonical_step_id": spec.canonical_step_id if spec else rs.step_id,
                "branch_id": None,
                "node_type": rs.execution_fingerprint.get("node_type", spec.node_type if spec else ""),
                "node_version": rs.execution_fingerprint.get("node_version", spec.node_version if spec else ""),
                "category": spec.category if spec else "",
                "status": rs.status.value,
                "action": "",
                "is_carried_forward": False,
                "started_at": rs.started_at,
                "finished_at": rs.finished_at,
                "params": rs.execution_fingerprint.get("params", spec.params if spec else {}),
                "params_hash": rs.execution_fingerprint.get("params_hash", spec.params_hash if spec else ""),
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
        branch_id = getattr(run_record, "branch_id", None)
        started_at = getattr(run_record, "started_at", "") or ""

        plan_id = ""
        project_id = ""
        if plan_version_id and uow is not None:
            with contextlib.suppress(Exception):
                plan_id = uow.plans.get_plan_id_for_version(plan_version_id) or ""
            if plan_id:
                try:
                    plan = uow.plans.get_plan(plan_id)
                    if plan is not None:
                        project_id = plan.project_id
                except Exception:
                    pass

        diagnostics: list[JsonDict] = []
        if uow is not None:
            try:
                diagnostics = list(uow.runs.get_diagnostics(run_id))
            except Exception:
                diagnostics = []
        if diagnostic is not None and not any(
            d.get("code") == diagnostic.code and d.get("message") == diagnostic.message
            for d in diagnostics
        ):
            diagnostics.append({"code": diagnostic.code, "message": diagnostic.message})

        step_ids = [s["step_id"] for s in steps]

        payload: JsonDict = {
            "manifest_version": MANIFEST_VERSION,
            "run_id": run_id,
            "plan_version_id": plan_version_id,
            "plan_id": plan_id,
            "project_id": project_id,
            "branch_id": branch_id,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "status": status,
            "execution_mode": "full_plan" if branch_id is None else "branch",
            "cardre_version": __version__,
            "pathway_hash": "",
            "artifact_root": "",
            "in_scope_step_ids": step_ids,
            "steps": steps,
            "diagnostics": diagnostics,
        }
        return payload


class RunAlreadyFinalised(CardreError):
    def __init__(self, run_id: str, actual_status: str) -> None:
        super().__init__(
            f"Run {run_id} was already finalised (status={actual_status})"
        )
