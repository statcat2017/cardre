"""Dataset roles section collector — no ref, uses run from ctx."""

from __future__ import annotations

from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import DatasetRole, Limitation
from cardre.reporting.types import SectionCollector, SectionContext


class DatasetRolesSection(SectionCollector):
    canonical_step_id = None
    kinds = ()

    def build(self, ctx: SectionContext) -> None:
        roles: list[DatasetRole] = []
        for row in ctx.store.execute(
            "SELECT al.artifact_id FROM artifact_lineage al "
            "WHERE al.run_id = ? AND al.direction = 'output'",
            (ctx.run["run_id"],),
        ).fetchall():
            art = ctx.store.get_artifact(row["artifact_id"])
            if art and art.role in ("train", "test", "oot"):
                roles.append(DatasetRole(
                    role=art.role,
                    dataset_id=art.artifact_id,
                    row_count=art.metadata.get("row_count", 0),
                    column_count=art.metadata.get("column_count", 0),
                ))

        has_oot = any(r.role == "oot" for r in roles)
        if not has_oot:
            ctx.add_limitation(Limitation(
                severity="warning", code=LimitationCode.NO_OOT_SAMPLE,
                message="No OOT dataset role was present for this run.",
            ))

        ctx.bundle.dataset_roles = roles
