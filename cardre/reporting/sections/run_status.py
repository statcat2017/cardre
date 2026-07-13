"""Run status section collector — needs run + manifest_digest from ctx."""

from __future__ import annotations

from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import DiagnosticEntry, Limitation, RunStatusInfo
from cardre.reporting.types import SectionCollector, SectionContext
from cardre.store.run_repo import RunRepository


class RunStatusSection(SectionCollector):
    canonical_step_id = None
    kinds = ()

    def build(self, ctx: SectionContext) -> None:
        run_diags = RunRepository(ctx.store).get_diagnostics(ctx.run["run_id"])
        ctx.bundle.run_status = RunStatusInfo(
            run_id=ctx.run["run_id"],
            status=ctx.run.get("status", ""),
            started_at=ctx.run.get("started_at", ""),
            finished_at=ctx.run.get("finished_at"),
            execution_mode=ctx.manifest_digest.execution_mode or "unknown",
            target_step_id=ctx.manifest_digest.target_step_id,
            in_scope_step_ids=list(ctx.manifest_digest.in_scope_step_ids),
        )
        for d in run_diags:
            ctx.bundle.run_status.diagnostics.append(DiagnosticEntry(
                code=d.get("code", ""),
                message=d.get("message", ""),
                severity=d.get("severity", "warning"),
                category=d.get("category", ""),
                created_at=d.get("created_at", ""),
            ))
        if ctx.run.get("status") and ctx.run["status"] != "succeeded":
            ctx.add_limitation(Limitation(
                severity="blocker",
                code=LimitationCode.RUN_NOT_SUCCEEDED,
                message=f"Run status is '{ctx.run['status']}', expected 'succeeded'.",
            ))
