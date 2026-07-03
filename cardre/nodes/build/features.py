from __future__ import annotations

import math

import polars as pl

from cardre._evidence.kinds import AmbiguousEvidenceError, EvidenceKind, EvidenceNotFoundError
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import (
    SCHEMA_IV_TABLE,
    SCHEMA_WOE_TABLE,
    SCHEMA_WOE_TRANSFORM_EVIDENCE,
)
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.engine.binning.diagnostics import MonotonicStatus, check_pure_bins, monotonicity_status
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.nodes._bin_mask import build_bin_condition
from cardre.nodes.contracts import NodeType


class CalculateWoeIvNode(NodeType):
    node_type = "cardre.calculate_woe_iv"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Calculate WOE & IV",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="zero_cell_policy",
                            label="Zero Cell Policy",
                            kind="string",
                            default="block",
                            constraint=ParameterConstraint(enum_values=["block"]),
                            help_text="Policy for handling zero-cell bins in final WOE calculation",
                        ),
                        ParameterDefinition(
                            name="purpose",
                            label="Purpose",
                            kind="enum",
                            default="initial",
                            constraint=ParameterConstraint(enum_values=["initial", "final"]),
                            help_text="Calculation purpose: initial exploratory or final production",
                        ),
                        ParameterDefinition(
                            name="smoothing",
                            label="Smoothing",
                            kind="object",
                            default=None,
                            required=False,
                            help_text="Optional additive smoothing configuration with method, alpha, and rationale",
                        ),
                        ParameterDefinition(
                            name="enforce_monotonic_woe",
                            label="Enforce Monotonic WOE",
                            kind="boolean",
                            default=False,
                            help_text="When true and purpose=final, reject variables with non-monotonic WOE",
                        ),
                    ],
                ),
            ],
        )

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        zero_cell_policy = params.get("zero_cell_policy", "block")
        smoothing = params.get("smoothing")
        purpose = params.get("purpose", "initial")
        enforce_monotonic_woe = bool(params.get("enforce_monotonic_woe", False))

        train_artifact = next(a for a in context.input_artifacts if a.role == "train")
        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        meta_def = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

        df = pl.read_parquet(store.artifact_path(train_artifact))  # cardre-allow-artifact-read: dataset-frame-input

        target_column = meta_def.target_column
        good_values = set(str(v) for v in meta_def.good_values)
        bad_values = set(str(v) for v in meta_def.bad_values)
        good_values_list = list(good_values)
        bad_values_list = list(bad_values)

        if not target_column or target_column not in df.columns:
            raise ValueError(f"WOE/IV target column {target_column!r} not found in training data")
        if not good_values or not bad_values:
            raise ValueError("WOE/IV requires non-empty good_values and bad_values")
        target_series = df[target_column].cast(pl.String)
        total_good_all = int(target_series.is_in(good_values_list).sum())
        total_bad_all = int(target_series.is_in(bad_values_list).sum())
        if total_good_all == 0 or total_bad_all == 0:
            raise ValueError(
                f"WOE/IV requires at least one good and one bad row; found goods={total_good_all}, bads={total_bad_all}"
            )
        woe_rows: list[dict] = []
        iv_rows: dict[str, dict] = {}
        warnings_list: list[dict] = []

        # Track per-variable smoothing for controlled evidence artifact
        evidence_variables: list[dict] = []

        for var_def in bin_def.variables:
            variable = var_def.variable
            kind = var_def.kind
            bins = var_def.bins

            if variable not in df.columns:
                continue

            col_values = df[variable]

            total_good = total_good_all
            total_bad = total_bad_all

            var_woe_rows = []
            var_iv = 0.0
            zero_cell_count = 0
            smoothing_applied = False
            zero_cell_encountered = False
            affected_bins: list[dict] = []

            for bin_def in bins:
                bin_id = bin_def["bin_id"]
                label = bin_def["label"]

                bin_mask = build_bin_condition(bin_def, col_values, kind, bins, variable=variable, bin_id=bin_id)

                row_count = int(bin_mask.sum())

                if target_series is not None and good_values and bad_values:
                    bin_good = int(target_series.filter(bin_mask).is_in(good_values_list).sum())
                    bin_bad = int(target_series.filter(bin_mask).is_in(bad_values_list).sum())
                else:
                    bin_good = bin_def.get("good_count", 0)
                    bin_bad = bin_def.get("bad_count", 0)

                raw_good_dist = bin_good / total_good if total_good > 0 else 0.0
                raw_bad_dist = bin_bad / total_bad if total_bad > 0 else 0.0
                good_dist = raw_good_dist
                bad_dist = raw_bad_dist
                was_smoothed = False
                raw_woe_val: float | None = None

                if good_dist == 0.0 or bad_dist == 0.0:
                    zero_cell_count += 1
                    zero_cell_encountered = True
                    if smoothing and smoothing.get("method") == "additive":
                        alpha = float(smoothing.get("alpha", 0.5))
                        if alpha <= 0:
                            raise ValueError("Smoothing alpha must be positive")
                        if purpose == "final" and not smoothing.get("rationale"):
                            raise ValueError(
                                f"Zero cell in variable {variable!r} bin {bin_id!r}: "
                                f"smoothing configured without a rationale"
                            )
                        good_dist = (bin_good + alpha) / (total_good + alpha * len(bins)) if total_good > 0 else alpha / (alpha * len(bins))
                        bad_dist = (bin_bad + alpha) / (total_bad + alpha * len(bins)) if total_bad > 0 else alpha / (alpha * len(bins))
                        was_smoothed = True
                        smoothing_applied = True
                        warnings_list.append({
                            "variable": variable,
                            "bin_id": bin_id,
                            "message": f"Zero cell smoothed with additive alpha={alpha}",
                        })
                    elif zero_cell_policy == "block" and purpose == "final":
                        raise ValueError(
                            f"Zero cell in variable {variable!r} bin {bin_id!r}: "
                            f"good_dist={good_dist:.4f}, bad_dist={bad_dist:.4f}. "
                            f"Final WOE blocked by zero_cell_policy={zero_cell_policy!r}. "
                            f"Configure smoothing with a rationale to proceed."
                        )
                    else:
                        warnings_list.append({
                            "code": "ZERO_CELL_INITIAL_IV_DEFLATED",
                            "variable": variable,
                            "bin_id": bin_id,
                            "message": f"Zero cell in variable {variable!r} bin {bin_id!r} "
                                      f"during initial pass; IV component set to 0",
                        })

                if good_dist == 0.0 or bad_dist == 0.0:
                    woe_val = 0.0
                    iv_comp = 0.0
                else:
                    woe_val = float(math.log(good_dist / bad_dist))
                    iv_comp = (good_dist - bad_dist) * woe_val
                    if was_smoothed:
                        raw_woe_val = float(math.log(raw_good_dist / raw_bad_dist)) if raw_good_dist > 0 and raw_bad_dist > 0 else None

                var_iv += iv_comp

                var_woe_rows.append({
                    "variable": variable,
                    "bin_id": bin_id,
                    "label": label,
                    "row_count": row_count,
                    "good_count": bin_good,
                    "bad_count": bin_bad,
                    "good_distribution": round(good_dist, 6),
                    "bad_distribution": round(bad_dist, 6),
                    "woe": round(woe_val, 6),
                    "iv_component": round(iv_comp, 6),
                })

                if was_smoothed:
                    alpha = float(smoothing.get("alpha", 0.5))
                    affected_bins.append({
                        "bin_id": bin_id,
                        "reason": "zero_good" if raw_good_dist == 0.0 else "zero_bad",
                        "raw_good_count": bin_good,
                        "raw_bad_count": bin_bad,
                        "smoothed_good_count": bin_good + alpha,
                        "smoothed_bad_count": bin_bad + alpha,
                        "raw_woe": raw_woe_val,
                        "final_woe": round(woe_val, 6),
                    })

            woe_rows.extend(var_woe_rows)
            iv_rows[variable] = {
                "variable": variable,
                "iv": round(var_iv, 6),
                "bin_count": len(bins),
                "zero_cell_count": zero_cell_count,
                "warning_count": sum(1 for w in warnings_list if w["variable"] == variable),
            }

            var_bins_out = []
            for i, woe_row in enumerate(var_woe_rows):
                bd = bins[i] if i < len(bins) else {}
                var_bins_out.append({
                    "bin_id": woe_row["bin_id"],
                    "label": woe_row["label"],
                    "lower": bd.get("lower"),
                    "upper": bd.get("upper"),
                    "good_count": woe_row["good_count"],
                    "bad_count": woe_row["bad_count"],
                    "bad_rate": round(woe_row["bad_count"] / max(woe_row["good_count"] + woe_row["bad_count"], 1), 4),
                    "woe": woe_row["woe"],
                    "iv_contribution": woe_row["iv_component"],
                })

            pure_diags = check_pure_bins(variable, bins, total_good, total_bad)
            for d in pure_diags:
                warnings_list.append({
                    "code": d.code,
                    "variable": d.variable,
                    "bin_id": d.bin_id,
                    "message": d.message,
                    "requires_acknowledgement": d.requires_acknowledgement,
                    **d.details,
                })

            var_status = "included"
            var_warnings: list[dict] = []
            if enforce_monotonic_woe and purpose == "final" and len(var_woe_rows) >= 2:
                woe_by_bin = {r["bin_id"]: r["woe"] for r in var_woe_rows}
                m_status = monotonicity_status(woe_by_bin)
                if m_status == MonotonicStatus.non_monotonic:
                    var_status = "REJECTED"
                    w = {
                        "code": "NON_MONOTONIC_WOE",
                        "variable": variable,
                        "message": f"Variable {variable!r} has non-monotonic WOE and was rejected",
                    }
                    warnings_list.append(w)
                    var_warnings.append(w)
                    iv_rows[variable]["iv"] = 0.0
                    iv_rows[variable]["warning_count"] += 1

            evidence_variables.append({
                "variable_name": variable,
                "status": var_status,
                "iv": round(var_iv, 6) if var_status == "included" else 0.0,
                "smoothing_applied": smoothing_applied,
                "zero_cell_encountered": zero_cell_encountered,
                "affected_bins": affected_bins,
                "warnings": var_warnings,
                "bins": var_bins_out,
            })

        woe_table = pl.DataFrame(woe_rows) if woe_rows else pl.DataFrame({
            "variable": [], "bin_id": [], "label": [], "row_count": [],
            "good_count": [], "bad_count": [], "good_distribution": [],
            "bad_distribution": [], "woe": [], "iv_component": [],
        })
        iv_table = pl.DataFrame(list(iv_rows.values())) if iv_rows else pl.DataFrame({
            "variable": [], "iv": [], "bin_count": [],
            "zero_cell_count": [], "warning_count": [],
        })

        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-table-{purpose}-{context.step_spec.step_id}",
            frame=woe_table,
            metadata={"purpose": purpose, "zero_cell_policy": zero_cell_policy, "schema_version": SCHEMA_WOE_TABLE},
        )
        iv_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem=f"iv-ranking-{purpose}-{context.step_spec.step_id}",
            frame=iv_table,
            metadata={"purpose": purpose, "zero_cell_policy": zero_cell_policy, "schema_version": SCHEMA_IV_TABLE},
        )

        summary = {
            "purpose": purpose,
            "zero_cell_policy": zero_cell_policy,
            "smoothing": smoothing,
            "event_convention": "bad",
            "non_event_convention": "good",
            "woe_formula": "ln(non_event_distribution / event_distribution)",
            "variable_count": len(iv_rows),
            "warnings": warnings_list,
        }
        summary_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-summary-{purpose}-{context.step_spec.step_id}",
            payload=summary,
            metadata={"purpose": purpose},
        )

        # Controlled WOE/IV evidence artifact (Phase 5, cardre.woe_iv_evidence.v1)
        project_id = ""
        plan_id = store.get_plan_id_for_version(context.plan_version_id)
        if plan_id:
            plan = store.get_plan(plan_id)
            if plan:
                project_id = plan["project_id"]

        woe_evidence = {
            "schema_version": "cardre.woe_iv_evidence.v1",
            "project_id": project_id,
            "run_id": context.run_id,
            "branch_id": context.step_spec.branch_id or "",
            "step_id": context.step_spec.step_id,
            "canonical_step_id": context.step_spec.canonical_step_id,
            "dataset_role": "train",
            "target_column": target_column,
            "config": {
                "smoothing": {
                    "enabled": smoothing is not None,
                    "method": (smoothing or {}).get("method", "additive"),
                    "alpha": float((smoothing or {}).get("alpha", 0.5)),
                    "zero_cell_policy": zero_cell_policy,
                },
            },
            "variables": evidence_variables,
        }
        evidence_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-iv-evidence-{purpose}-{context.step_spec.step_id}",
            payload=woe_evidence,
            metadata={"purpose": purpose, "schema_version": "cardre.woe_iv_evidence.v1"},
        )

        all_artifacts = [woe_art, iv_art, summary_art, evidence_art]

        return NodeOutput(
            artifacts=all_artifacts,
            metrics={
                "variable_count": len(iv_rows),
                "zero_cell_warning_count": len(warnings_list),
            })


class WoeTransformTrainNode(NodeType):
    node_type = "cardre.woe_transform_train"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition", "report"]
    output_roles: list[str] = ["train"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        reader = ArtifactEvidenceReader(store)
        train_artifact = next(a for a in context.input_artifacts if a.role == "train")

        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)

        try:
            meta = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        except (EvidenceNotFoundError, AmbiguousEvidenceError):
            meta = None
        sel = reader.find_optional(context.input_artifacts, EvidenceKind.SELECTION_DEFINITION)

        if not bin_def.variables:
            raise ValueError("WOE transform received an empty bin definition")
        target_column = meta.target_column if meta is not None else ""

        df = pl.read_parquet(store.artifact_path(train_artifact))  # cardre-allow-artifact-read: dataset-frame-input
        woe_map = woe_table.mapping

        missing_woe_bins: list[str] = []
        for var_def in bin_def.variables:
            for bin_entry in var_def.bins:
                bin_id = bin_entry["bin_id"]
                if woe_map.get(var_def.variable, {}).get(bin_id) is None:
                    missing_woe_bins.append(f"{var_def.variable}:{bin_id}")

        if missing_woe_bins:
            raise ValueError(
                f"WOE transform: {len(missing_woe_bins)} bin(s) have no WOE mapping: "
                f"{', '.join(missing_woe_bins[:10])}"
            )

        selected_names: set[str] | None = None
        if sel is not None:
            selected_names = sel.selected_names

        all_var_defs = bin_def.variables
        if selected_names is not None:
            selected_vars = [v for v in all_var_defs if v.variable in selected_names]
            if not selected_vars:
                raise ValueError(
                    f"WOE transform: variable-selection defined {len(selected_names)} selected "
                    f"variable(s) but none found in bin definitions"
                )
        else:
            selected_vars = list(all_var_defs)

        woe_columns = []
        woe_exprs = []
        column_variable_map: list[tuple[str, str]] = []
        result_df = df

        for var_def in selected_vars:
            variable = var_def.variable if hasattr(var_def, 'variable') else var_def.get('variable', '')
            kind = var_def.kind if hasattr(var_def, 'kind') else var_def.get('kind', '')
            bins = var_def.bins if hasattr(var_def, 'bins') else var_def.get('bins', [])
            woe_col = f"{variable}_woe"

            if variable not in df.columns:
                continue

            woe_expr = None
            for bin_def_entry in bins:
                bin_id = bin_def_entry["bin_id"]

                mask_expr = build_bin_condition(bin_def_entry, pl.col(variable), kind, bins, variable=variable, bin_id=bin_id)

                woe_val = woe_map.get(variable, {}).get(bin_id, 0.0)
                when_clause = pl.when(mask_expr).then(pl.lit(woe_val))
                woe_expr = when_clause if woe_expr is None else woe_expr.when(mask_expr).then(pl.lit(woe_val))

            if woe_expr is None:
                raise ValueError(f"WOE transform: variable '{variable}' has no bins defined")

            woe_expr = woe_expr.otherwise(pl.lit(None, dtype=pl.Float64))
            woe_exprs.append(woe_expr.alias(woe_col))
            column_variable_map.append((woe_col, variable))
            woe_columns.append(woe_col)

        if woe_exprs:
            result_df = result_df.with_columns(woe_exprs)

        for woe_col, variable in column_variable_map:
            unmatched = result_df.filter(pl.col(woe_col).is_null()).height
            if unmatched > 0:
                raise ValueError(
                    f"WOE transform: {unmatched} row(s) in variable '{variable}' "
                    f"did not match any bin. All training rows must belong to a defined bin."
                )

        transform_report = {
            "target_column": target_column,
            "transformed_variables": woe_columns,
            "selected_only": selected_names is not None,
            "row_count": df.height,
        }
        report_artifact_ref = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-transform-report-{context.step_spec.step_id}",
            payload=transform_report,
            metadata={"schema_version": SCHEMA_WOE_TRANSFORM_EVIDENCE},
        )

        dataset_artifact = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem=f"woe-transformed-train-{context.step_spec.step_id}",
            frame=result_df,
            metadata={
                "source_artifact_id": train_artifact.artifact_id,
                "woe_columns": woe_columns,
                "target_column": target_column,
            },
        )

        all_outputs = [dataset_artifact, report_artifact_ref]
        return NodeOutput(
            artifacts=all_outputs,
            metrics={"variable_count": len(woe_columns)})
