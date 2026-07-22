"""FinalizeRun — write manifest + transition run status in one UoW."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre._version import __version__
from cardre.application.ports.manifest_publisher import ManifestPublisherPort
from cardre.domain.diagnostics import JsonDict, utc_now_iso
from cardre.domain.errors import CardreError

MANIFEST_VERSION = "cardre.run_manifest.v1"


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

        peek = self._uow_factory()
        try:
            run_record = peek.runs.get(run_id)
        finally:
            peek.close()

        payload = self._build_manifest(run_id, status, steps or [], diagnostic, run_record)
        self._manifest_publisher.publish(run_id, payload)

        try:
            uow = self._uow_factory()
            if diagnostic is not None:
                uow.runs.append_diagnostic(run_id, {"code": diagnostic.code, "message": diagnostic.message})
            if status == "succeeded":
                uow.runs.succeed(run_id)
            elif status == "failed":
                uow.runs.fail(run_id)
            elif status == "cancelled":
                uow.runs.cancel(run_id)
            elif status == "interrupted":
                uow.runs.interrupt(run_id)
            else:
                uow.runs.transition(run_id, status, expected_from=("running",))
            uow.commit()
        except Exception:
            uow2 = self._uow_factory()
            actual_record = uow2.runs.get(run_id)
            actual_status = actual_record["status"]
            uow2.close()
            rewritten = self._build_manifest(run_id, actual_status, steps or [], diagnostic, actual_record)
            self._manifest_publisher.publish(run_id, rewritten)
            raise RunAlreadyFinalised(run_id, actual_status) from None

    def _build_manifest(
        self,
        run_id: str,
        status: str,
        steps: list[dict[str, Any]],
        diagnostic: FinalizeDiagnostic | None,
        run_record: JsonDict,
    ) -> JsonDict:
        payload: JsonDict = {
            "manifest_version": MANIFEST_VERSION,
            "run_id": run_id,
            "plan_version_id": run_record.get("plan_version_id", ""),
            "branch_id": run_record.get("branch_id"),
            "started_at": run_record.get("started_at", ""),
            "finished_at": utc_now_iso(),
            "status": status,
            "execution_mode": run_record.get("execution_mode", "unknown"),
            "cardre_version": __version__,
            "steps": steps,
        }
        if diagnostic is not None:
            payload["diagnostic"] = {"code": diagnostic.code, "message": diagnostic.message}
        return payload


class RunAlreadyFinalised(CardreError):
    def __init__(self, run_id: str, actual_status: str) -> None:
        super().__init__(
            f"Run {run_id} was already finalised (status={actual_status})"
        )
