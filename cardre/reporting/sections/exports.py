"""Implementation artifacts section collector — takes 3 refs."""

from __future__ import annotations

from typing import Any

from cardre._evidence.schemas import (
    SCHEMA_SCORE_TABLE,
    SCHEMA_SCORING_EXPORT_PYTHON,
    SCHEMA_SCORING_EXPORT_SQL,
)
from cardre.reporting.schema import ImplementationArtifactInfo, ImplementationArtifactsInfo
from cardre.reporting.types import SectionCollector, SectionContext


class ImplementationArtifactsSection(SectionCollector):
    canonical_step_id = None
    kinds = ()

    def _find_artifact_by_step(self, ctx: SectionContext, rs: Any, schema_version: str) -> Any | None:
        for row in ctx.store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
            (rs.run_step_id,),
        ).fetchall():
            art = ctx.store.get_artifact(row["artifact_id"])
            if art and art.metadata.get("schema_version") == schema_version:
                return art
        return None

    def build(self, ctx: SectionContext) -> None:
        from cardre.reporting.collector import _resolve_run_step

        table_ref = ctx.resolved.get("scorecard-table-export")
        py_ref = ctx.resolved.get("scoring-export-python")
        sql_ref = ctx.resolved.get("scoring-export-sql")

        if not table_ref and not py_ref and not sql_ref:
            return

        table_art = None
        py_art = None
        sql_art = None

        if table_ref is not None:
            rs = _resolve_run_step(ctx.store, table_ref, ctx.plan_version_id)
            if rs is not None:
                table_art = self._find_artifact_by_step(ctx, rs, SCHEMA_SCORE_TABLE)
        if py_ref is not None:
            rs = _resolve_run_step(ctx.store, py_ref, ctx.plan_version_id)
            if rs is not None:
                py_art = self._find_artifact_by_step(ctx, rs, SCHEMA_SCORING_EXPORT_PYTHON)
        if sql_ref is not None:
            rs = _resolve_run_step(ctx.store, sql_ref, ctx.plan_version_id)
            if rs is not None:
                sql_art = self._find_artifact_by_step(ctx, rs, SCHEMA_SCORING_EXPORT_SQL)

        ctx.bundle.implementation_artifacts = ImplementationArtifactsInfo(
            scorecard_table=ImplementationArtifactInfo(
                artifact_type="scorecard_table",
                schema_version=SCHEMA_SCORE_TABLE,
                artifact_id=table_art.artifact_id if table_art else "",
                description="Flat-file attribute points table",
            ) if table_art else None,
            scoring_export_python=ImplementationArtifactInfo(
                artifact_type="scoring_export_python",
                schema_version=SCHEMA_SCORING_EXPORT_PYTHON,
                artifact_id=py_art.artifact_id if py_art else "",
                description="Standalone Python scoring function",
            ) if py_art else None,
            scoring_export_sql=ImplementationArtifactInfo(
                artifact_type="scoring_export_sql",
                schema_version=SCHEMA_SCORING_EXPORT_SQL,
                artifact_id=sql_art.artifact_id if sql_art else "",
                description="Standalone SQL scoring query",
            ) if sql_art else None,
            source_step_refs=[r.to_schema_ref() for r in [table_ref, py_ref, sql_ref] if r is not None],
        )
