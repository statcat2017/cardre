from __future__ import annotations

from typing import Any, cast

import polars as pl

from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_CUTOFF_ANALYSIS
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)
from cardre.nodes.parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)


class CutoffAnalysisNode(NodeType):
    node_type = "cardre.cutoff_analysis"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Cutoff Analysis",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Analyse approval rate, bad rate, and capture rate across score bands / cutoffs.",
                    params=[
                        ParameterDefinition(
                            name="band_count",
                            label="Band Count",
                            kind="integer",
                            default=20,
                            help_text="Number of equal-width score bands to divide the score range into (used when cutoffs is empty).",
                            constraint=ParameterConstraint(min_value=2),
                        ),
                        ParameterDefinition(
                            name="cutoffs",
                            label="Cutoffs",
                            kind="list",
                            default=[],
                            help_text="Explicit list of score cutoffs (overrides band_count when non-empty).",
                        ),
                    ],
                ),
            ],
            default_method="default",
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        band_count = params.get("band_count", 20)
        try:
            if int(band_count) < 2:
                errors.append("band_count must be at least 2")
        except (ValueError, TypeError):
            errors.append("band_count must be an integer")
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        band_count = int(params.get("band_count", 20))
        cutoffs = list(params.get("cutoffs", []))

        if band_count < 2:
            raise ValueError(f"band_count must be at least 2, got {band_count}")

        meta = context.inputs.target_metadata()
        target_col = meta.target_column if meta is not None else ""
        good = meta.good_values if meta is not None else frozenset()
        bad = meta.bad_values if meta is not None else frozenset()
        bad_list = list(bad)

        train_arts = context.inputs.by_role("train")
        test_arts = context.inputs.by_role("test")
        oot_arts = context.inputs.by_role("oot")
        data_arts = train_arts + test_arts + oot_arts

        cutoff_tables: dict[str, list[JsonDict]] = {}
        warnings: list[JsonDict] = []

        for data_art in data_arts:
            role = data_art.role
            df = context.inputs.read_dataframe(data_art)
            if "score" not in df.columns or "predicted_bad_probability" not in df.columns:
                continue

            score_series = df["score"]
            if score_series.n_unique() < 2:
                raise ValueError(f"Score column has zero variance in role {role!r}")

            min_s = cast(float, score_series.min())
            max_s = cast(float, score_series.max())

            if cutoffs:
                band_breaks = sorted(float(c) for c in cutoffs if isinstance(c, (int, float)))
            else:
                step = (max_s - min_s) / band_count
                band_breaks = [min_s + i * step for i in range(1, band_count)]

            has_target = target_col and target_col in df.columns
            if has_target and good and bad:
                y_bin_expr = pl.when(pl.col(target_col).cast(pl.String).is_in(bad_list)).then(1).otherwise(0)
            else:
                if not has_target:
                    warnings.append({
                        "role": role, "code": "MISSING_TARGET_COLUMN",
                        "message": f"Target column {target_col!r} not found in role {role!r}; "
                                   "bad rate and capture rate are not meaningful.",
                    })
                elif not good and not bad:
                    warnings.append({
                        "role": role, "code": "MISSING_TARGET_METADATA",
                        "message": "No good_values/bad_values in definition artifact; "
                                   "bad rate and capture rate are not meaningful.",
                    })
                y_bin_expr = pl.lit(0)
                has_target = False

            band_cuts = [float("-inf")] + band_breaks + [float("inf")]
            binned = df.with_columns(
                y_bin_expr.alias("_y_binary"),
                pl.col("score").cut(band_breaks, include_breaks=True).alias("_band"),
            )
            total_bad = binned.select(pl.sum("_y_binary")).item()
            total_n = binned.height

            grouped = binned.with_columns([
                binned["_band"].struct.field("breakpoint").alias("_brk"),
            ]).group_by("_brk", maintain_order=True).agg([
                pl.len().alias("count"),
                pl.sum("_y_binary").alias("bad_count"),
            ]).sort("_brk")

            band_results: list[JsonDict] = []
            for i, row in enumerate(grouped.iter_rows()):
                brk, cnt, bc = row[0], row[1], row[2]
                band_results.append({
                    "band": i + 1,
                    "lower": round(float(band_cuts[i]), 2) if band_cuts[i] != float("-inf") else None,
                    "upper": round(float(brk), 2) if brk != float("inf") else None,
                    "count": cnt,
                    "bad_count": bc,
                    "approval_rate": round(1 - cnt / total_n, 4),
                    "bad_rate": round(bc / cnt, 4) if cnt > 0 else 0,
                    "capture_rate": round(bc / total_bad, 4) if total_bad > 0 else 0,
                })

            cutoff_tables[role] = [
                {
                    "score_cutoff": b["upper"] if b["upper"] is not None else b["lower"],
                    "approval_rate": b["approval_rate"],
                    "bad_rate": b["bad_rate"],
                    "capture_rate": b["capture_rate"],
                }
                for b in band_results
            ]

        payload: JsonDict = {
            "schema_version": SCHEMA_CUTOFF_ANALYSIS,
            "cutoff_tables": cutoff_tables,
        }
        if warnings:
            payload["warnings"] = warnings

        context.outputs.publish_json(
            role="report", kind=EvidenceKind.CUTOFF_ANALYSIS,
            payload=payload,
            metadata={"schema_version": SCHEMA_CUTOFF_ANALYSIS},
        )

        context.outputs.add_metric("role_count", len(data_arts))
        return context.outputs.build_result()


__definition__ = NodeDefinition(
    node_type=CutoffAnalysisNode.node_type,
    version=CutoffAnalysisNode.version,
    category=CutoffAnalysisNode.category,
    description="Analyse approval rate, bad rate, and capture rate across score bands / cutoffs",
    input_contract=ArtifactContract(
        roles=tuple(ArtifactRoleSpec(r, required=True) for r in CutoffAnalysisNode.input_roles),
    ),
    output_contract=ArtifactContract(
        roles=tuple(ArtifactRoleSpec(r, required=True) for r in CutoffAnalysisNode.output_roles),
    ),
    parameter_schema=None,
    optional_dependencies=(),
    tier="launch",
)
