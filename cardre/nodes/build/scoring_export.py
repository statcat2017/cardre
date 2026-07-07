from __future__ import annotations

from typing import Any

from cardre._evidence.kinds import EvidenceKind, EvidenceNotFoundError
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import (
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_SCORE_TABLE,
    SCHEMA_SCORING_EXPORT_PYTHON,
    SCHEMA_SCORING_EXPORT_SQL,
)
from cardre.artifacts import write_json_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
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
        scorecard_raw = getattr(scorecard, "_raw", {})

        attributes = scorecard_raw.get("attributes", [])
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

        table_payload: dict[str, Any] = {
            "schema_version": SCHEMA_SCORE_TABLE,
            "base_score": scorecard_raw.get("base_score", 600),
            "base_odds": scorecard_raw.get("base_odds", 50.0),
            "points_to_double_odds": scorecard_raw.get("points_to_double_odds", 20),
            "base_points": scorecard_raw.get("base_points", 0),
            "higher_score_is_lower_risk": scorecard_raw.get("higher_score_is_lower_risk", True),
            "target_column": scorecard_raw.get("target_column", ""),
            "rows": table_rows,
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"scorecard-table-{context.step_spec.step_id}",
            payload=table_payload,
            metadata={
                "schema_version": SCHEMA_SCORE_TABLE,
                "row_count": len(table_rows),
            },
        )

        return NodeOutput(
            artifacts=[artifact],
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
    bin_def: Any,
    woe_table: Any,
    scorecard_raw: dict[str, Any],
    model_raw: dict[str, Any],
    feature_contract: dict[str, Any] | None = None,
) -> str:
    intercept = float(model_raw.get("intercept", 0))
    coefficients = model_raw.get("coefficients", {})
    offset = float(scorecard_raw.get("offset", 0))
    factor_val = float(scorecard_raw.get("factor", 1))
    higher_is_lower = bool(scorecard_raw.get("higher_score_is_lower_risk", True))
    direction = -1.0 if higher_is_lower else 1.0
    base_score = scorecard_raw.get("base_score", 600)
    base_odds = scorecard_raw.get("base_odds", 50.0)
    pdo = scorecard_raw.get("points_to_double_odds", 20)

    missing_policy = "error"
    if feature_contract:
        missing_policy = feature_contract.get("missing_policy", "error")

    woe_map = woe_table.mapping
    var_defs = bin_def.variables

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
    lines.append(f'    "higher_score_is_lower_risk": {higher_is_lower!r},')
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def score_cardre(record):")
    lines.append('    """Score a single record dict. Returns the scaled score."""')

    woe_var_lines: list[str] = []
    for vd in var_defs:
        var = vd.variable
        kind = vd.kind
        bins = vd.bins
        woe_key = f"{var}_woe"
        if woe_key not in coefficients:
            continue
        var_woe_map = woe_map.get(var, {})
        if not var_woe_map:
            continue

        has_missing_bin = any(be.get("is_missing_bin", False) for be in bins)

        woe_var_lines.append(f"    # {var} ({kind})")
        woe_var_lines.append(f"    _val = record.get({var!r})")

        if has_missing_bin:
            missing_bin_woe = None
            for be in bins:
                if be.get("is_missing_bin", False):
                    missing_bin_woe = var_woe_map.get(be["bin_id"])
                    break
            if missing_bin_woe is not None:
                woe_var_lines.append("    if _val is None:")
                woe_var_lines.append(f"        _woe_{var} = {missing_bin_woe!r}")
                woe_var_lines.append("    else:")
            else:
                woe_var_lines.append("    if _val is None:")
                woe_var_lines.append(f"        _woe_{var} = 0.0")
                woe_var_lines.append("    else:")
        elif missing_policy == "error":
            woe_var_lines.append("    if _val is None:")
            woe_var_lines.append(f'        raise ValueError("score_cardre: missing value for {var}")')
            woe_var_lines.append("    else:")
        else:
            woe_var_lines.append("    if _val is None:")
            woe_var_lines.append(f"        _woe_{var} = 0.0")
            woe_var_lines.append("    else:")

        conditions: list[str] = []
        for be in bins:
            bid = be["bin_id"]
            wv = var_woe_map.get(bid)
            if wv is None:
                continue
            if be.get("is_missing_bin", False):
                continue
            if kind == "numeric":
                lower = be.get("lower")
                upper = be.get("upper")
                lower_inc = be.get("lower_inclusive", False)
                upper_inc = be.get("upper_inclusive", True)
                parts: list[str] = []
                if lower is not None:
                    op = ">=" if lower_inc else ">"
                    parts.append(f"_val {op} {lower!r}")
                if upper is not None:
                    op = "<=" if upper_inc else "<"
                    parts.append(f"_val {op} {upper!r}")
                cond = " and ".join(parts)
                conditions.append(f"        if {cond}:\n            _woe_{var} = {wv!r}")
            else:
                cats = be.get("categories", [])
                if be.get("is_other_bin", False):
                    conditions.append(f"        else:\n            _woe_{var} = {wv!r}")
                elif cats:
                    conditions.append(f"        if _val in {repr(tuple(cats))}:\n            _woe_{var} = {wv!r}")

        if conditions:
            woe_var_lines.append(conditions[0])
            for c in conditions[1:]:
                woe_var_lines.append(c)
        else:
            woe_var_lines.append(f"        _woe_{var} = 0.0")
        woe_var_lines.append("")

    lines.extend(woe_var_lines)

    log_odds_parts: list[str] = [f"{intercept!r}"]
    for vd in var_defs:
        var = vd.variable
        woe_key = f"{var}_woe"
        if woe_key not in coefficients:
            continue
        coef = float(coefficients[woe_key])
        log_odds_parts.append(f"{coef!r} * _woe_{var}")

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

        bundle_art = next(
            (a for a in context.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )
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
        model_raw = getattr(model, "_raw", {})

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
        scorecard_raw = getattr(scorecard, "_raw", {})

        _validate_bundle_components(
            bundle_art, model_art, scorecard, bin_def, woe_table,
        )

        bundle_raw = reader.read(bundle_art.artifact_id, EvidenceKind.FROZEN_SCORECARD_BUNDLE)
        bundle_payload = getattr(bundle_raw, "_raw", {})
        feature_contract = bundle_payload.get("feature_contract", {})

        source = _build_python_scorer_source(
            bin_def, woe_table, scorecard_raw, model_raw, feature_contract,
        )

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_SCORING_EXPORT_PYTHON,
            "source": source,
            "function_name": "score_cardre",
            "metadata": {
                "base_score": scorecard_raw.get("base_score", 600),
                "base_odds": scorecard_raw.get("base_odds", 50.0),
                "points_to_double_odds": scorecard_raw.get("points_to_double_odds", 20),
                "higher_score_is_lower_risk": scorecard_raw.get("higher_score_is_lower_risk", True),
                "target_column": scorecard_raw.get("target_column", ""),
                "model_family": model_raw.get("model_family", "logistic_regression"),
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
    bin_def: Any,
    woe_table: Any,
    scorecard_raw: dict[str, Any],
    model_raw: dict[str, Any],
    feature_contract: dict[str, Any] | None = None,
) -> str:
    intercept = float(model_raw.get("intercept", 0))
    coefficients = model_raw.get("coefficients", {})
    offset = float(scorecard_raw.get("offset", 0))
    factor_val = float(scorecard_raw.get("factor", 1))
    higher_is_lower = bool(scorecard_raw.get("higher_score_is_lower_risk", True))
    direction = -1.0 if higher_is_lower else 1.0

    missing_policy = "error"
    if feature_contract:
        missing_policy = feature_contract.get("missing_policy", "error")

    woe_map = woe_table.mapping
    var_defs = bin_def.variables

    lines: list[str] = []
    lines.append("-- Standalone scorecard SQL generated by Cardre.")
    lines.append("")

    woe_case_parts: list[str] = []
    log_odds_parts: list[str] = [f"{intercept!r}"]

    for vd in var_defs:
        var = vd.variable
        kind = vd.kind
        bins = vd.bins
        woe_key = f"{var}_woe"
        if woe_key not in coefficients:
            continue
        var_woe_map = woe_map.get(var, {})
        if not var_woe_map:
            continue

        coef = float(coefficients[woe_key])
        log_odds_parts.append(f"{coef!r} * woe_{var}")

        has_missing_bin = any(be.get("is_missing_bin", False) for be in bins)
        has_other_bin = any(be.get("is_other_bin", False) for be in bins)

        case_lines: list[str] = []
        case_lines.append("    CASE")
        for be in bins:
            bid = be["bin_id"]
            wv = var_woe_map.get(bid)
            if wv is None:
                continue
            if be.get("is_missing_bin", False):
                case_lines.append(f"        WHEN {var} IS NULL THEN {wv!r}")
            elif kind == "numeric":
                lower = be.get("lower")
                upper = be.get("upper")
                lower_inc = be.get("lower_inclusive", False)
                upper_inc = be.get("upper_inclusive", True)
                cond_parts: list[str] = []
                if lower is not None:
                    op = ">=" if lower_inc else ">"
                    cond_parts.append(f"{var} {op} {lower!r}")
                if upper is not None:
                    op = "<=" if upper_inc else "<"
                    cond_parts.append(f"{var} {op} {upper!r}")
                cond = " AND ".join(cond_parts)
                case_lines.append(f"        WHEN {cond} THEN {wv!r}")
            else:
                cats = be.get("categories", [])
                if be.get("is_other_bin", False):
                    case_lines.append(f"        ELSE {wv!r}")
                elif cats:
                    cats_sql = ", ".join(repr(c) for c in cats)
                    case_lines.append(f"        WHEN {var} IN ({cats_sql}) THEN {wv!r}")
        if not has_other_bin:
            if has_missing_bin:
                case_lines.append("        ELSE 0.0")
            elif missing_policy == "error":
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

        bundle_art = next(
            (a for a in context.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )
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
        model_raw = getattr(model, "_raw", {})

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
        scorecard_raw = getattr(scorecard, "_raw", {})

        _validate_bundle_components(
            bundle_art, model_art, scorecard, bin_def, woe_table,
        )

        bundle_raw = reader.read(bundle_art.artifact_id, EvidenceKind.FROZEN_SCORECARD_BUNDLE)
        bundle_payload = getattr(bundle_raw, "_raw", {})
        feature_contract = bundle_payload.get("feature_contract", {})

        source = _build_sql_scorer_source(
            bin_def, woe_table, scorecard_raw, model_raw, feature_contract,
        )

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_SCORING_EXPORT_SQL,
            "source": source,
            "dialect": "generic",
            "metadata": {
                "base_score": scorecard_raw.get("base_score", 600),
                "base_odds": scorecard_raw.get("base_odds", 50.0),
                "points_to_double_odds": scorecard_raw.get("points_to_double_odds", 20),
                "higher_score_is_lower_risk": scorecard_raw.get("higher_score_is_lower_risk", True),
                "target_column": scorecard_raw.get("target_column", ""),
                "model_family": model_raw.get("model_family", "logistic_regression"),
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
