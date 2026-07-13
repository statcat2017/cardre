"""Manual interventions section collector — reads step params + annotations."""

from __future__ import annotations

from json import loads
from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre.branch_step_resolver import resolve_step_for_branch
from cardre.domain.errors import Diagnostic
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import (
    Limitation,
    ManualBinningReviewState,
    ManualIntervention,
)
from cardre.reporting.types import SectionCollector, SectionContext


class ManualInterventionsSection(SectionCollector):
    canonical_step_id = "manual-binning"
    kinds = (EvidenceKind.BIN_DEFINITION, EvidenceKind.MANUAL_BINNING_OVERRIDES)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return

        step_map = ctx.store.get_branch_step_map(ctx.bundle.target_branch_id, ctx.plan_version_id)
        if step_map:
            mb_ref = resolve_step_for_branch(
                branch_id=ctx.bundle.target_branch_id,
                canonical_step_id="manual-binning",
                branch_step_map=step_map,
            )
            if mb_ref:
                for s in ctx.store.get_plan_version_steps(ctx.plan_version_id):
                    if s.step_id == mb_ref.step_id:
                        params = s.params
                        is_reviewed = params.get("reviewed", False)
                        is_accepted = params.get("accept_automated", False)
                        overrides = params.get("overrides", [])
                        edited_vars = list({ov.get("variable", "") for ov in overrides if ov.get("variable")})
                        reasons = list({ov.get("reason_code", "") for ov in overrides if ov.get("reason_code")})
                        annotation, annotation_diags = self._get_latest_review_annotation(ctx, mb_ref.step_id)
                        if annotation_diags:
                            ctx.add_limitation(Limitation(
                                severity="warning", code=LimitationCode.MISSING_MANUAL_INTERVENTION_REASON,
                                message="Review annotation could not be read.",
                            ))
                        ctx.bundle.manual_binning_review = ManualBinningReviewState(
                            review_status="reviewed" if is_reviewed else ("accepted_automated" if is_accepted else "not_started"),
                            accepted_automated=is_accepted,
                            edited_variable_count=len(edited_vars),
                            variables_edited=edited_vars,
                            reasons=reasons,
                            reviewed_at=annotation.get("created_at", "") if annotation else "",
                            reviewed_by=annotation.get("reviewed_by", "") if annotation else "",
                            review_reason=annotation.get("review_reason", "") if annotation else "",
                        )
                        break

        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            return

        for row in ctx.store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
            (rs.run_step_id,),
        ).fetchall():
            aid = row["artifact_id"]
            art = ctx.store.get_artifact(aid)
            if art and art.role in ("definition", "report") and "manual" in art.path.lower():
                data = ctx.reader.read_optional(aid, EvidenceKind.BIN_DEFINITION)
                legacy = ctx.reader.read_optional(aid, EvidenceKind.MANUAL_BINNING_OVERRIDES)
                if data is None and legacy is None:
                    continue
                interventions: list[dict[str, Any]] = []
                if data is not None:
                    payload = data.to_dict()
                    if isinstance(payload, dict):
                        for var in list(payload.get("variables", [])) + list(payload.get("rejected", [])):
                            if isinstance(var, dict):
                                interventions.extend(var.get("override_history", []) or [])
                if not interventions and legacy is not None:
                    legacy_payload = legacy.to_dict()
                    if isinstance(legacy_payload, dict):
                        interventions.extend(legacy_payload.get("overrides", []) or [])
                for i, ov in enumerate(interventions):
                    ctx.bundle.manual_interventions.append(ManualIntervention(
                        intervention_id=f"mi_{i:03d}",
                        branch_id=ref.resolved_branch_id,
                        canonical_step_id=ref.canonical_step_id,
                        step_id=ref.step_id,
                        type=ov.get("user_action", ov.get("type", "unknown")),
                        variable_name=ov.get("variable_name", ov.get("variable", "")),
                        before_artifact=str(ov.get("before", "")),
                        after_artifact=str(ov.get("after", "")),
                        reason=ov.get("reason", ""),
                        created_at=ov.get("created_at", ""),
                    ))

    def _get_latest_review_annotation(self, ctx: SectionContext, step_id: str) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
        try:
            with ctx.store.transaction() as conn:
                rows = conn.execute(
                    "SELECT payload_json, created_at FROM step_annotations "
                    "WHERE step_id = ? AND plan_version_id = ? AND kind = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (step_id, ctx.plan_version_id, "manual_binning_review"),
                ).fetchall()
            if not rows:
                return (None, [])
            payload = loads(rows[0]["payload_json"])
            payload["created_at"] = rows[0]["created_at"]
            return (payload, [])
        except Exception as exc:
            return (None, [Diagnostic(
                code="REVIEW_ANNOTATION_UNREADABLE",
                message="Could not read review annotation.",
                exception_type=type(exc).__name__,
                context={"step_id": step_id, "plan_version_id": ctx.plan_version_id},
            )])
