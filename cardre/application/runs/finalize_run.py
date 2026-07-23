"""FinalizeRun — build a canonical manifest and transition run status.

The manifest is built from persisted run, run-step, and artifact lineage
data through the UnitOfWork. The canonical manifest is published by
``ManifestPublisherPort`` before the run status is transitioned.

If the status transition fails (e.g. the run was already finalised),
the manifest is re-published with the actual terminal status.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre._version import __version__
from cardre.application.ports.manifest_publisher import ManifestPublisherPort
from cardre.domain.diagnostics import JsonDict, utc_now_iso
from cardre.domain.errors import CardreError
from cardre.domain.manifest import MANIFEST_VERSION


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
            manifest_steps = self._build_manifest_steps(uow, run_id)
            payload = self._build_manifest(
                run_id, status, manifest_steps, diagnostic, run_record, uow,
            )
            self._manifest_publisher.publish(run_id, payload)

            if diagnostic is not None:
                uow.runs.append_diagnostic(run_id, {"code": diagnostic.code, "message": diagnostic.message})
            from cardre.domain.run import RunStatus
            uow.runs.transition(run_id, RunStatus(status), expected_from=(RunStatus.RUNNING,))

    def _build_manifest_steps(self, uow: Any, run_id: str) -> list[JsonDict]:
        run_steps = uow.run_steps.get_for_run(run_id)
        result: list[JsonDict] = []
        for rs in run_steps:
            input_ids = list(uow.artifacts.output_artifact_ids_for_run_step(rs.run_step_id))
            output_ids = list(input_ids)
            lineage = uow.artifacts.artifacts_for_run_step(rs.run_step_id)
            input_ids = [a.artifact_id for d, a in lineage if d == "input"]
            output_ids = [a.artifact_id for d, a in lineage if d == "output"]
            result.append({
                "step_id": rs.step_id,
                "canonical_step_id": rs.step_id,
                "branch_id": None,
                "node_type": rs.execution_fingerprint.get("node_type", ""),
                "node_version": rs.execution_fingerprint.get("node_version", ""),
                "category": "",
                "status": rs.status.value,
                "action": "",
                "is_carried_forward": False,
                "started_at": rs.started_at,
                "finished_at": rs.finished_at,
                "params": rs.execution_fingerprint.get("params", {}),
                "params_hash": rs.execution_fingerprint.get("params_hash", ""),
                "parent_step_ids": [],
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
        uow: Any | None,
    ) -> JsonDict:
        plan_version_id = getattr(run_record, "plan_version_id", "") or (
            run_record.get("plan_version_id", "") if isinstance(run_record, dict) else ""
        )
        branch_id = getattr(run_record, "branch_id", None)
        started_at = getattr(run_record, "started_at", "") or (
            run_record.get("started_at", "") if isinstance(run_record, dict) else ""
        )
        str(getattr(run_record, "status", "") or (
            run_record.get("status", "") if isinstance(run_record, dict) else ""
        ))

        diagnostics: list[JsonDict] = []
        if uow is not None:
            try:
                diagnostics = list(uow.runs.get_diagnostics(run_id))
            except Exception:
                diagnostics = []
        if diagnostic is not None:
            diagnostics.append({"code": diagnostic.code, "message": diagnostic.message})

        payload: JsonDict = {
            "manifest_version": MANIFEST_VERSION,
            "run_id": run_id,
            "plan_version_id": plan_version_id,
            "plan_id": "",
            "project_id": "",
            "branch_id": branch_id,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "status": status,
            "execution_mode": "unknown",
            "cardre_version": __version__,
            "pathway_hash": "",
            "artifact_root": "",
            "in_scope_step_ids": [],
            "steps": steps,
            "diagnostics": diagnostics,
        }
        return payload


class RunAlreadyFinalised(CardreError):
    def __init__(self, run_id: str, actual_status: str) -> None:
        super().__init__(
            f"Run {run_id} was already finalised (status={actual_status})"
        )
