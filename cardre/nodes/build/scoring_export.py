from __future__ import annotations

from typing import Any

import polars as pl

from cardre.domain.evidence.kinds import EvidenceKind, EvidenceNotFoundError
from cardre.domain.evidence.schemas import (
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_SCORE_TABLE,
    SCHEMA_SCORING_EXPORT_PYTHON,
    SCHEMA_SCORING_EXPORT_SQL,
)
from cardre.nodes.build.scoring_export_ir import (
    ScoringVariable,
    compile_scorecard,
    compute_log_odds_and_direction,
)
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)


class ScorecardTableExportNode(NodeType):
    node_type = "cardre.scorecard_table_export"
    version = "1"
    category = "export"
    description = "Export scorecard as a table (CSV equivalent + JSON)"
    input_roles: list[str] = ["scorecard", "report"]
    output_roles: list[str] = ["report"]

    __definition__ = NodeDefinition(
        node_type="cardre.scorecard_table_export",
        version="1",
        category="export",
        description="Export scorecard as a table (CSV equivalent + JSON)",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("scorecard", required=True),
                ArtifactRoleSpec("report", required=True),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(ArtifactRoleSpec("report", required=True),),
        ),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    def run(self, context: NodeContext) -> NodeResult:
        scorecard_list = context.inputs.by_role("scorecard")
        scorecard_art = next(
            (a for a in scorecard_list if a.metadata.get("schema_version") != SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )
        if scorecard_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.SCORE_SCALING,
                candidate_artifact_ids=[a.artifact_id for a in scorecard_list],
            )
        scorecard = context.inputs.read(scorecard_art, EvidenceKind.SCORE_SCALING)
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

        context.outputs.publish_table(
            role="report",
            kind=EvidenceKind.SCORE_TABLE,
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

        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.SCORE_TABLE,
            payload=table_payload,
            metadata={
                "schema_version": SCHEMA_SCORE_TABLE,
                "row_count": len(table_rows),
            },
        )
        context.outputs.add_metric("row_count", len(table_rows))
        return context.outputs.build_result()


def _validate_bundle_components(
    bundle_meta: dict[str, Any],
    model_evidence: Any,
    scorecard_evidence: Any,
    bin_def_evidence: Any,
    woe_table_evidence: Any,
) -> None:
    expected_model = bundle_meta.get("model_artifact_id")
    expected_scorecard = bundle_meta.get("scorecard_artifact_id")
    expected_bin_def = bundle_meta.get("bin_definition_artifact_id")
    expected_woe_table = bundle_meta.get("woe_table_artifact_id")

    if expected_model and model_evidence and expected_model != getattr(model_evidence, "source_artifact_id", None):
        raise ValueError(
            f"Frozen bundle model_artifact_id ({expected_model}) "
            f"does not match input model artifact ({getattr(model_evidence, 'source_artifact_id', None)})"
        )
    if expected_scorecard and scorecard_evidence and expected_scorecard != getattr(scorecard_evidence, "source_artifact_id", None):
        raise ValueError(
            f"Frozen bundle scorecard_artifact_id ({expected_scorecard}) "
            f"does not match input scorecard artifact ({getattr(scorecard_evidence, 'source_artifact_id', None)})"
        )
    if expected_bin_def and bin_def_evidence and expected_bin_def != getattr(bin_def_evidence, "source_artifact_id", None):
        raise ValueError(
            f"Frozen bundle bin_definition_artifact_id ({expected_bin_def}) "
            f"does not match input bin definition artifact ({getattr(bin_def_evidence, 'source_artifact_id', None)})"
        )
    if expected_woe_table and woe_table_evidence and expected_woe_table != getattr(woe_table_evidence, "source_artifact_id", None):
        raise ValueError(
            f"Frozen bundle woe_table_artifact_id ({expected_woe_table}) "
            f"does not match input WOE table artifact ({getattr(woe_table_evidence, 'source_artifact_id', None)})"
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

        # Build an if/elif/else chain for non-missing bins.
        non_missing = [b for b in sv.bins if not b.is_missing]
        has_other = any(b.is_other for b in non_missing)
        first_cond = True
        for b in non_missing:
            if b.is_other:
                woe_var_lines.append("        else:")
                woe_var_lines.append(f"            _woe_{var} = {b.woe!r}")
                break
            kw = "if" if first_cond else "elif"
            if b.kind == "numeric":
                parts: list[str] = []
                if b.lower is not None:
                    op = ">=" if b.lower_inclusive else ">"
                    lower_str = "float('-inf')" if b.lower == float("-inf") else repr(b.lower)
                    parts.append(f"_val {op} {lower_str}")
                if b.upper is not None:
                    op = "<=" if b.upper_inclusive else "<"
                    upper_str = "float('inf')" if b.upper == float("inf") else repr(b.upper)
                    parts.append(f"_val {op} {upper_str}")
                cond = " and ".join(parts)
                woe_var_lines.append(f"        {kw} {cond}:")
                woe_var_lines.append(f"            _woe_{var} = {b.woe!r}")
                first_cond = False
            elif b.categories:
                woe_var_lines.append(f"        {kw} _val in {b.categories!r}:")
                woe_var_lines.append(f"            _woe_{var} = {b.woe!r}")
                first_cond = False

        if non_missing and not has_other:
            # Unmatched fallback when no "other" bin catches the value.
            if sv.unmatched_policy == "error":
                woe_var_lines.append("        else:")
                woe_var_lines.append(
                    '            raise ValueError(f"score_cardre: unmatched value for '
                    + var
                    + ': {_val!r}"' + ')'
                )
            else:
                woe_var_lines.append("        else:")
                woe_var_lines.append(f"            _woe_{var} = 0.0")
        elif not non_missing and not has_missing:
            # No bins at all — value never contributes.
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
    description = "Export a standalone Python scorer from a frozen scorecard bundle"
    input_roles: list[str] = ["scorecard", "model", "report", "definition"]
    output_roles: list[str] = ["report"]

    __definition__ = NodeDefinition(
        node_type="cardre.scoring_export_python",
        version="1",
        category="export",
        description="Export a standalone Python scorer from a frozen scorecard bundle",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("scorecard", required=True),
                ArtifactRoleSpec("model", required=True),
                ArtifactRoleSpec("report", required=True),
                ArtifactRoleSpec("definition", required=True),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(ArtifactRoleSpec("report", required=True),),
        ),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    def run(self, context: NodeContext) -> NodeResult:
        bundle_art = context.inputs.find_frozen_bundle()
        if bundle_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.FROZEN_SCORECARD_BUNDLE,
                candidate_artifact_ids=[],
            )

        bin_def_list = context.inputs.by_kind(EvidenceKind.BIN_DEFINITION)
        if not bin_def_list:
            raise EvidenceNotFoundError(
                EvidenceKind.BIN_DEFINITION,
                candidate_artifact_ids=[],
            )
        bin_def = bin_def_list[0]

        woe_table_list = context.inputs.by_kind(EvidenceKind.WOE_TABLE)
        if not woe_table_list:
            raise EvidenceNotFoundError(
                EvidenceKind.WOE_TABLE,
                candidate_artifact_ids=[],
            )
        woe_table = woe_table_list[0]

        model_arts = context.inputs.by_role("model")
        if not model_arts:
            raise EvidenceNotFoundError(
                EvidenceKind.MODEL_ARTIFACT,
                candidate_artifact_ids=[],
            )
        model_art = model_arts[0]
        model = context.inputs.read(model_art, EvidenceKind.MODEL_ARTIFACT)

        scorecard_candidates = context.inputs.by_role("scorecard")
        non_bundle_scorecards = [
            a for a in scorecard_candidates
            if a.metadata.get("schema_version") != SCHEMA_FROZEN_SCORECARD_BUNDLE
        ]
        if not non_bundle_scorecards:
            raise EvidenceNotFoundError(
                EvidenceKind.SCORE_SCALING,
                candidate_artifact_ids=[a.artifact_id for a in scorecard_candidates],
            )
        scorecard_art = non_bundle_scorecards[0]
        scorecard = context.inputs.read(scorecard_art, EvidenceKind.SCORE_SCALING)

        _validate_bundle_components(
            bundle_art.metadata, model, scorecard, bin_def, woe_table,
        )

        bundle_payload = context.inputs.read(bundle_art, EvidenceKind.FROZEN_SCORECARD_BUNDLE)
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

        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.SCORING_EXPORT_PYTHON,
            payload=payload,
            metadata={
                "schema_version": SCHEMA_SCORING_EXPORT_PYTHON,
                "function_name": "score_cardre",
            },
        )
        context.outputs.add_metric("function_name", "score_cardre")
        return context.outputs.build_result()


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

        has_missing = any(b.is_missing for b in sv.bins)
        has_other = any(b.is_other for b in sv.bins)
        case_lines: list[str] = []
        case_lines.append("    CASE")
        if has_missing:
            missing_woe = next((b.woe for b in sv.bins if b.is_missing), None)
            case_lines.append(f"        WHEN {var} IS NULL THEN {missing_woe!r}")
        elif sv.missing_policy == "error":
            case_lines.append(f"        WHEN {var} IS NULL THEN NULL")
        else:
            case_lines.append(f"        WHEN {var} IS NULL THEN 0.0")
        for b in sv.bins:
            if b.is_missing:
                continue
            if b.kind == "numeric":
                cond_parts: list[str] = []
                if b.lower is not None:
                    op = ">=" if b.lower_inclusive else ">"
                    lower_str = "-1e100" if b.lower == float("-inf") else repr(b.lower)
                    cond_parts.append(f"{var} {op} {lower_str}")
                if b.upper is not None:
                    op = "<=" if b.upper_inclusive else "<"
                    upper_str = "1e100" if b.upper == float("inf") else repr(b.upper)
                    cond_parts.append(f"{var} {op} {upper_str}")
                cond = " AND ".join(cond_parts)
                case_lines.append(f"        WHEN {cond} THEN {b.woe!r}")
            else:
                if b.is_other:
                    case_lines.append(f"        ELSE {b.woe!r}")
                elif b.categories:
                    cats_sql = ", ".join(repr(c) for c in b.categories)
                    case_lines.append(f"        WHEN {var} IN ({cats_sql}) THEN {b.woe!r}")
        if not has_other:
            if sv.unmatched_policy == "error":
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
    description = "Export a generic SQL scorer from a frozen scorecard bundle"
    input_roles: list[str] = ["scorecard", "model", "report", "definition"]
    output_roles: list[str] = ["report"]

    __definition__ = NodeDefinition(
        node_type="cardre.scoring_export_sql",
        version="1",
        category="export",
        description="Export a generic SQL scorer from a frozen scorecard bundle",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("scorecard", required=True),
                ArtifactRoleSpec("model", required=True),
                ArtifactRoleSpec("report", required=True),
                ArtifactRoleSpec("definition", required=True),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(ArtifactRoleSpec("report", required=True),),
        ),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    def run(self, context: NodeContext) -> NodeResult:
        bundle_art = context.inputs.find_frozen_bundle()
        if bundle_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.FROZEN_SCORECARD_BUNDLE,
                candidate_artifact_ids=[],
            )

        bin_def_list = context.inputs.by_kind(EvidenceKind.BIN_DEFINITION)
        if not bin_def_list:
            raise EvidenceNotFoundError(
                EvidenceKind.BIN_DEFINITION,
                candidate_artifact_ids=[],
            )
        bin_def = bin_def_list[0]

        woe_table_list = context.inputs.by_kind(EvidenceKind.WOE_TABLE)
        if not woe_table_list:
            raise EvidenceNotFoundError(
                EvidenceKind.WOE_TABLE,
                candidate_artifact_ids=[],
            )
        woe_table = woe_table_list[0]

        model_arts = context.inputs.by_role("model")
        if not model_arts:
            raise EvidenceNotFoundError(
                EvidenceKind.MODEL_ARTIFACT,
                candidate_artifact_ids=[],
            )
        model_art = model_arts[0]
        model = context.inputs.read(model_art, EvidenceKind.MODEL_ARTIFACT)

        scorecard_candidates = context.inputs.by_role("scorecard")
        non_bundle_scorecards = [
            a for a in scorecard_candidates
            if a.metadata.get("schema_version") != SCHEMA_FROZEN_SCORECARD_BUNDLE
        ]
        if not non_bundle_scorecards:
            raise EvidenceNotFoundError(
                EvidenceKind.SCORE_SCALING,
                candidate_artifact_ids=[a.artifact_id for a in scorecard_candidates],
            )
        scorecard_art = non_bundle_scorecards[0]
        scorecard = context.inputs.read(scorecard_art, EvidenceKind.SCORE_SCALING)

        _validate_bundle_components(
            bundle_art.metadata, model, scorecard, bin_def, woe_table,
        )

        bundle_payload = context.inputs.read(bundle_art, EvidenceKind.FROZEN_SCORECARD_BUNDLE)
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

        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.SCORING_EXPORT_SQL,
            payload=payload,
            metadata={
                "schema_version": SCHEMA_SCORING_EXPORT_SQL,
                "dialect": "generic",
            },
        )
        context.outputs.add_metric("dialect", "generic")
        return context.outputs.build_result()


__all__ = [
    "ScorecardTableExportNode",
    "PythonScoringExportNode",
    "SqlScoringExportNode",
]
