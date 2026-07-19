from __future__ import annotations

from typing import Any

import polars as pl

from cardre._evidence.kinds import EvidenceKind, EvidenceNotFoundError
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import (
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_SCORE_TABLE,
    SCHEMA_SCORING_EXPORT_PYTHON,
    SCHEMA_SCORING_EXPORT_SQL,
)
from cardre.artifacts import write_csv_artifact, write_json_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.build.scoring_export_ir import (
    ScoringVariable,
    compile_scorecard,
    compute_log_odds_and_direction,
)
from cardre.nodes.contracts import NodeType


class ScorecardTableExportNode(NodeType):
    node_type = "cardre.scorecard_table_export"
    version = "1"
    category = "export"
    input_roles: list[str] = ["scorecard", "report"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)

        scorecard_art = next(
            (a for a in context.input_artifacts if a.role == "scorecard"
             and a.metadata.get("schema_version") != SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )
        if scorecard_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.SCORE_SCALING,
                candidate_artifact_ids=[a.artifact_id for a in context.input_artifacts],
            )
        scorecard = reader.read(scorecard_art.artifact_id, EvidenceKind.SCORE_SCALING)
        attributes = scorecard.attributes
        if not attributes:
            raise ValueError("Scorecard table export: no attributes found in score scaling artifact")

        table_rows: list[dict[str, Any]] = []
        for attr in attributes:
            table_rows.append({
                "variable": attr["variable"],
                "bin_id": attr["bin_id"],
                "label": attr.get("label", ""),
                "woe": attr["woe"],
                "coefficient": attr.get("coefficient", 0),
                "points": attr["points"],
            })

        df = pl.DataFrame(table_rows)

        csv_artifact = write_csv_artifact(
            store, artifact_type="report", role="report",
            stem=f"scorecard-table-csv-{context.step_spec.step_id}",
            frame=df,
            metadata={"schema_version": SCHEMA_SCORE_TABLE, "row_count": len(table_rows)},
        )

        table_payload: dict[str, Any] = {
            "schema_version": SCHEMA_SCORE_TABLE,
            "base_score": scorecard.base_score,
            "base_odds": scorecard.base_odds,
            "points_to_double_odds": scorecard.points_to_double_odds,
            "base_points": scorecard.base_points or 0,
            "score_direction": scorecard.score_direction,
            "target_column": scorecard.target_column,
            "rows": table_rows,
        }

        json_artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"scorecard-table-{context.step_spec.step_id}",
            payload=table_payload,
            metadata={
                "schema_version": SCHEMA_SCORE_TABLE,
                "row_count": len(table_rows),
                "csv_artifact_id": csv_artifact.artifact_id,
            },
        )

        return NodeOutput(
            artifacts=[json_artifact, csv_artifact],
            metrics={"row_count": len(table_rows)},
        )


def _validate_bundle_components(
    bundle_art: Any,
    model_art: Any,
    scorecard_evidence: Any,
    bin_def_evidence: Any,
    woe_table_evidence: Any,
) -> None:
    bundle_meta = bundle_art.metadata
    expected_model = bundle_meta.get("model_artifact_id")
    expected_scorecard = bundle_meta.get("scorecard_artifact_id")
    expected_bin_def = bundle_meta.get("bin_definition_artifact_id")
    expected_woe_table = bundle_meta.get("woe_table_artifact_id")

    if expected_model and model_art and expected_model != model_art.artifact_id:
        raise ValueError(
            f"Frozen bundle model_artifact_id ({expected_model}) "
            f"does not match input model artifact ({model_art.artifact_id})"
        )
    if expected_scorecard and scorecard_evidence and expected_scorecard != scorecard_evidence.source_artifact_id:
        raise ValueError(
            f"Frozen bundle scorecard_artifact_id ({expected_scorecard}) "
            f"does not match input scorecard artifact ({scorecard_evidence.source_artifact_id})"
        )
    if expected_bin_def and bin_def_evidence and expected_bin_def != bin_def_evidence.source_artifact_id:
        raise ValueError(
            f"Frozen bundle bin_definition_artifact_id ({expected_bin_def}) "
            f"does not match input bin definition artifact ({bin_def_evidence.source_artifact_id})"
        )
    if expected_woe_table and woe_table_evidence and expected_woe_table != woe_table_evidence.source_artifact_id:
        raise ValueError(
            f"Frozen bundle woe_table_artifact_id ({expected_woe_table}) "
            f"does not match input WOE table artifact ({woe_table_evidence.source_artifact_id})"
        )


def _build_python_scorer_source(
    variables: list[ScoringVariable],
    scorecard_dict: dict[str, Any],
    model_dict: dict[str, Any],
) -> str:
    _, offset, factor_val, direction = compute_log_odds_and_direction(scorecard_dict, model_dict)
    base_score = scorecard_dict.get("base_score", 600)
    base_odds = scorecard_dict.get("base_odds", 50.0)
    pdo = scorecard_dict.get("points_to_double_odds", 20)

    lines: list[str] = []
    lines.append('"""Standalone scorecard scorer generated by Cardre."""')
    lines.append("")
    lines.append("import math")
    lines.append("")
    lines.append("")
    lines.append("SCORECARD_META = {")
    lines.append(f'    "base_score": {base_score!r},')
    lines.append(f'    "base_odds": {base_odds!r},')
    lines.append(f'    "points_to_double_odds": {pdo!r},')
    dir_str = (
        '"higher_is_lower_risk"'
        if scorecard_dict.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk"
        else '"higher_is_better"'
    )
    lines.append(f'    "score_direction": {dir_str},')
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def score_cardre(record):")
    lines.append('    """Score a single record dict. Returns the scaled score."""')

    woe_var_lines: list[str] = []
    for sv in variables:
        var = sv.name
        woe_var_lines.append(f"    # {var}")
        woe_var_lines.append(f"    _val = record.get({var!r})")

        has_missing = any(b.is_missing for b in sv.bins)
        if has_missing:
            missing_woe = next((b.woe for b in sv.bins if b.is_missing), None)
            if missing_woe is not None:
                woe_var_lines.append("    if _val is None:")
                woe_var_lines.append(f"        _woe_{var} = {missing_woe!r}")
                woe_var_lines.append("    else:")
            else:
                woe_var_lines.append("    if _val is None:")
                woe_var_lines.append(f"        _woe_{var} = 0.0")
                woe_var_lines.append("    else:")
        elif sv.missing_policy == "error":
            woe_var_lines.append("    if _val is None:")
            woe_var_lines.append(f'        raise ValueError("score_cardre: missing value for {var}")')
            woe_var_lines.append("    else:")
        else:
            woe_var_lines.append("    if _val is None:")
            woe_var_lines.append(f"        _woe_{var} = 0.0")
            woe_var_lines.append("    else:")

        has_other = any(b.is_other for b in sv.bins)
        conditions: list[str] = []
        for b in sv.bins:
            if b.is_missing:
                continue
            if b.kind == "numeric":
                parts: list[str] = []
                if b.lower is not None:
                    op = ">=" if b.lower_inclusive else ">"
                    parts.append(f"_val {op} {b.lower!r}")
                if b.upper is not None:
                    op = "<=" if b.upper_inclusive else "<"
                    parts.append(f"_val {op} {b.upper!r}")
                cond = " and ".join(parts)
                conditions.append(f"        if {cond}:\n            _woe_{var} = {b.woe!r}")
            else:
                if b.is_other:
                    conditions.append(f"        else:\n            _woe_{var} = {b.woe!r}")
                elif b.categories:
                    conditions.append(f"        if _val in {b.categories!r}:\n            _woe_{var} = {b.woe!r}")

        if conditions:
            woe_var_lines.append(conditions[0])
            for c in conditions[1:]:
                woe_var_lines.append(c)
        elif not has_other and not has_missing:
            woe_var_lines.append(f"        _woe_{var} = 0.0")
        woe_var_lines.append("")

    lines.extend(woe_var_lines)
    log_odds_parts: list[str] = [f"{model_dict.get('intercept', 0)!r}"]
    for sv in variables:
        log_odds_parts.append(f"{sv.coefficient!r} * _woe_{sv.name}")

    log_odds_expr = " + ".join(log_odds_parts)
    lines.append(f"    _log_odds = {log_odds_expr}")
    lines.append(f"    _score = {offset!r} + ({direction!r} * {factor_val!r} * _log_odds)")
    lines.append("    return _score")
    lines.append("")

    return "\n".join(lines)


class PythonScoringExportNode(NodeType):
    node_type = "cardre.scoring_export_python"
    version = "1"
    category = "export"
    input_roles: list[str] = ["scorecard", "model", "report", "definition"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)

        bundle_art = context.find_frozen_bundle()
        if bundle_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.FROZEN_SCORECARD_BUNDLE,
                candidate_artifact_ids=[a.artifact_id for a in context.input_artifacts],
            )

        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)

        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
        if model_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.MODEL_ARTIFACT,
                candidate_artifact_ids=[a.artifact_id for a in context.input_artifacts],
            )
        model = reader.read(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)

        scorecard_candidates = [
            a for a in context.input_artifacts
            if a.role == "scorecard"
            and a.metadata.get("schema_version") != SCHEMA_FROZEN_SCORECARD_BUNDLE
        ]
        if not scorecard_candidates:
            raise EvidenceNotFoundError(
                EvidenceKind.SCORE_SCALING,
                candidate_artifact_ids=[a.artifact_id for a in context.input_artifacts],
            )
        scorecard = reader.find(scorecard_candidates, EvidenceKind.SCORE_SCALING)

        _validate_bundle_components(
            bundle_art, model_art, scorecard, bin_def, woe_table,
        )

        bundle_payload = reader.read(bundle_art.artifact_id, EvidenceKind.FROZEN_SCORECARD_BUNDLE)
        feature_contract = bundle_payload.get("feature_contract", {})

        scorecard_for_source = {
            "offset": scorecard.offset,
            "factor": scorecard.factor,
            "score_direction": scorecard.score_direction,
            "base_score": scorecard.base_score,
            "base_odds": scorecard.base_odds,
            "points_to_double_odds": scorecard.points_to_double_odds,
        }
        model_for_source = {
            "intercept": model.intercept,
            "coefficients": model.coefficients_dict,
        }
        variables = compile_scorecard(
            bin_def, woe_table, scorecard_for_source, model_for_source, feature_contract,
        )
        source = _build_python_scorer_source(
            variables, scorecard_for_source, model_for_source,
        )

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_SCORING_EXPORT_PYTHON,
            "source": source,
            "function_name": "score_cardre",
            "metadata": {
                "base_score": scorecard.base_score,
                "base_odds": scorecard.base_odds,
                "points_to_double_odds": scorecard.points_to_double_odds,
                "score_direction": scorecard.score_direction,
                "target_column": scorecard.target_column or model.target_column,
                "model_family": model.model_family,
            },
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"scoring-export-python-{context.step_spec.step_id}",
            payload=payload,
            metadata={
                "schema_version": SCHEMA_SCORING_EXPORT_PYTHON,
                "function_name": "score_cardre",
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"function_name": "score_cardre"},
        )


def _build_sql_scorer_source(
    variables: list[ScoringVariable],
    scorecard_dict: dict[str, Any],
    model_dict: dict[str, Any],
) -> str:
    intercept, offset, factor_val, direction = compute_log_odds_and_direction(scorecard_dict, model_dict)

    lines: list[str] = []
    lines.append("-- Standalone scorecard SQL generated by Cardre.")
    lines.append("")

    woe_case_parts: list[str] = []
    log_odds_parts: list[str] = [f"{intercept!r}"]

    for sv in variables:
        var = sv.name
        log_odds_parts.append(f"{sv.coefficient!r} * woe_{var}")

        has_other = any(b.is_other for b in sv.bins)
        case_lines: list[str] = []
        case_lines.append("    CASE")
        for b in sv.bins:
            if b.is_missing:
                case_lines.append(f"        WHEN {var} IS NULL THEN {b.woe!r}")
            elif b.kind == "numeric":
                cond_parts: list[str] = []
                if b.lower is not None:
                    op = ">=" if b.lower_inclusive else ">"
                    cond_parts.append(f"{var} {op} {b.lower!r}")
                if b.upper is not None:
                    op = "<=" if b.upper_inclusive else "<"
                    cond_parts.append(f"{var} {op} {b.upper!r}")
                cond = " AND ".join(cond_parts)
                case_lines.append(f"        WHEN {cond} THEN {b.woe!r}")
            else:
                if b.is_other:
                    case_lines.append(f"        ELSE {b.woe!r}")
                elif b.categories:
                    cats_sql = ", ".join(repr(c) for c in b.categories)
                    case_lines.append(f"        WHEN {var} IN ({cats_sql}) THEN {b.woe!r}")
        if not has_other:
            if sv.missing_policy == "error":
                case_lines.append("        ELSE NULL")
            else:
                case_lines.append("        ELSE 0.0")
        case_lines.append(f"    END AS woe_{var}")
        woe_case_parts.append("\n".join(case_lines))

    woe_cte = ",\n".join(woe_case_parts)
    log_odds_expr = " + ".join(log_odds_parts)
    score_expr = f"{offset!r} + ({direction!r} * {factor_val!r} * ({log_odds_expr}))"

    lines.append("WITH woe_cte AS (")
    lines.append("    SELECT")
    lines.append("        *,")
    lines.append(woe_cte)
    lines.append("    FROM input_data")
    lines.append(")")
    lines.append("SELECT")
    lines.append("    *,")
    lines.append(f"    {score_expr} AS score")
    lines.append("FROM woe_cte")
    lines.append("")

    return "\n".join(lines)


class SqlScoringExportNode(NodeType):
    node_type = "cardre.scoring_export_sql"
    version = "1"
    category = "export"
    input_roles: list[str] = ["scorecard", "model", "report", "definition"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)

        bundle_art = context.find_frozen_bundle()
        if bundle_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.FROZEN_SCORECARD_BUNDLE,
                candidate_artifact_ids=[a.artifact_id for a in context.input_artifacts],
            )

        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)

        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
        if model_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.MODEL_ARTIFACT,
                candidate_artifact_ids=[a.artifact_id for a in context.input_artifacts],
            )
        model = reader.read(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)

        scorecard_candidates = [
            a for a in context.input_artifacts
            if a.role == "scorecard"
            and a.metadata.get("schema_version") != SCHEMA_FROZEN_SCORECARD_BUNDLE
        ]
        if not scorecard_candidates:
            raise EvidenceNotFoundError(
                EvidenceKind.SCORE_SCALING,
                candidate_artifact_ids=[a.artifact_id for a in context.input_artifacts],
            )
        scorecard = reader.find(scorecard_candidates, EvidenceKind.SCORE_SCALING)

        _validate_bundle_components(
            bundle_art, model_art, scorecard, bin_def, woe_table,
        )

        bundle_payload = reader.read(bundle_art.artifact_id, EvidenceKind.FROZEN_SCORECARD_BUNDLE)
        feature_contract = bundle_payload.get("feature_contract", {})

        scorecard_for_source = {
            "offset": scorecard.offset,
            "factor": scorecard.factor,
            "score_direction": scorecard.score_direction,
            "base_score": scorecard.base_score,
            "base_odds": scorecard.base_odds,
            "points_to_double_odds": scorecard.points_to_double_odds,
        }
        model_for_source = {
            "intercept": model.intercept,
            "coefficients": model.coefficients_dict,
        }
        variables = compile_scorecard(
            bin_def, woe_table, scorecard_for_source, model_for_source, feature_contract,
        )
        source = _build_sql_scorer_source(
            variables, scorecard_for_source, model_for_source,
        )

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_SCORING_EXPORT_SQL,
            "source": source,
            "dialect": "generic",
            "metadata": {
                "base_score": scorecard.base_score,
                "base_odds": scorecard.base_odds,
                "points_to_double_odds": scorecard.points_to_double_odds,
                "score_direction": scorecard.score_direction,
                "target_column": scorecard.target_column or model.target_column,
                "model_family": model.model_family,
            },
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"scoring-export-sql-{context.step_spec.step_id}",
            payload=payload,
            metadata={
                "schema_version": SCHEMA_SCORING_EXPORT_SQL,
                "dialect": "generic",
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"dialect": "generic"},
        )


__all__ = [
    "ScorecardTableExportNode",
    "PythonScoringExportNode",
    "SqlScoringExportNode",
]
