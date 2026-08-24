from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from cardre.domain.binning.woe import MissingWoePolicy, apply_woe_columns
from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import (
    SCHEMA_APPLY_MODEL_EVIDENCE,
    SCHEMA_APPLY_WOE_EVIDENCE,
)
from cardre.nodes._model_artifacts import load_estimator
from cardre.nodes._samples import sample_bundle
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


class ApplyWoeMappingNode(NodeType):
    node_type = "cardre.apply_woe_mapping"
    version = "1"
    category = "apply"

    __definition__ = NodeDefinition(
        node_type="cardre.apply_woe_mapping",
        version="1",
        category="apply",
        description="Apply WOE mapping to transform raw features into WOE values",
        input_contract=ArtifactContract(
            roles=(
                # Bin definition and WOE table are hard-required (looked up by
                # kind); data roles and the scorecard role are optional — the node
                # transforms whichever datasets are supplied.
                ArtifactRoleSpec("definition", required=True),
                ArtifactRoleSpec("report", required=True),
                ArtifactRoleSpec("train", required=False),
                ArtifactRoleSpec("test", required=False),
                ArtifactRoleSpec("oot", required=False),
                ArtifactRoleSpec("scorecard", required=False),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                # A partial apply (e.g. only test) emits only that data role plus
                # the evidence report; the data output roles must be optional.
                ArtifactRoleSpec("train", required=False),
                ArtifactRoleSpec("test", required=False),
                ArtifactRoleSpec("oot", required=False),
                ArtifactRoleSpec("report", required=True, kinds=(EvidenceKind.APPLY_WOE_EVIDENCE,), media_types=("application/json",), schema_versions=(SCHEMA_APPLY_WOE_EVIDENCE,)),
            ),
        ),
    )

    VALID_UNMATCHED_POLICIES = {"fill_zero", "warn", "fail"}

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Apply WOE Mapping",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="woe_unmatched_policy",
                            label="Unmatched Policy",
                            kind="enum",
                            default="fail",
                            constraint=ParameterConstraint(enum_values=["fill_zero", "warn", "fail"]),
                            help_text="Policy when rows do not match any WOE bin (default fail). Choose 'warn' or 'fill_zero' for permissive handling.",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        policy = params.get("woe_unmatched_policy", "fail")
        if policy not in self.VALID_UNMATCHED_POLICIES:
            errors.append(
                f"woe_unmatched_policy must be one of {self.VALID_UNMATCHED_POLICIES}, got {policy!r}"
            )
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        woe_unmatched_policy = params.get("woe_unmatched_policy", "fail")

        bundle_art = context.inputs.find_frozen_bundle()
        if bundle_art is not None and "woe_unmatched_policy" not in params:
            woe_unmatched_policy = "fail"

        data_arts = sample_bundle(context.inputs)

        bin_def_arts = context.inputs.by_kind(EvidenceKind.BIN_DEFINITION)
        if not bin_def_arts:
            raise ValueError("No bin definition artifact found")
        bin_def = bin_def_arts[0]

        woe_table_arts = context.inputs.by_kind(EvidenceKind.WOE_TABLE)
        if not woe_table_arts:
            raise ValueError("No WOE table artifact found")
        woe_table = woe_table_arts[0]

        sel_def_arts = context.inputs.by_kind(EvidenceKind.SELECTION_DEFINITION)
        sel_def = sel_def_arts[0] if sel_def_arts else None

        selected_names: set[str] | None = None
        if sel_def is not None:
            selected_names = sel_def.selected_names

        woe_map = woe_table.mapping

        var_defs = bin_def.variables
        if selected_names is not None:
            var_defs = [v for v in var_defs if v.variable in selected_names]

        sel_art_id = sel_def.source_artifact_id if sel_def is not None else None

        if bundle_art is not None:
            bundle_meta = bundle_art.metadata
            if bundle_meta.get("bin_definition_artifact_id") != bin_def.source_artifact_id:
                raise ValueError(
                    f"Frozen bundle bin_definition_artifact_id "
                    f"({bundle_meta.get('bin_definition_artifact_id')}) "
                    f"does not match the bin definition being applied "
                    f"({bin_def.source_artifact_id})"
                )
            if bundle_meta.get("woe_table_artifact_id") != woe_table.source_artifact_id:
                raise ValueError(
                    f"Frozen bundle woe_table_artifact_id "
                    f"({bundle_meta.get('woe_table_artifact_id')}) "
                    f"does not match the WOE table being applied "
                    f"({woe_table.source_artifact_id})"
                )
            expected_selection_id = bundle_meta.get("selection_artifact_id")
            if expected_selection_id:
                if sel_art_id is None:
                    raise ValueError(
                        f"Frozen bundle requires selection artifact "
                        f"{expected_selection_id}, but no selection artifact was provided"
                    )
                if expected_selection_id != sel_art_id:
                    raise ValueError(
                        f"Frozen bundle selection_artifact_id "
                        f"({expected_selection_id}) "
                        f"does not match the selection being applied "
                        f"({sel_art_id})"
                    )

        roles_evidence: dict[str, JsonDict] = {}
        output_count = 0
        unmatched_total = 0

        for data_art in data_arts:
            df = context.inputs.read_dataframe(data_art)
            role = data_art.role
            fallback_counts: dict[str, int] = {}
            woe_columns_created: list[str] = []
            variables_applied: list[str] = []

            df, woe_columns_created = apply_woe_columns(
                df,
                var_defs,
                lambda var, bid: woe_map.get(var, {}).get(bid),
                policy=MissingWoePolicy.RAISE,
            )
            variables_applied = [c[: -len("_woe")] for c in woe_columns_created]
            for woe_col in woe_columns_created:
                var = woe_col[: -len("_woe")]
                n_unmatched = df.filter(pl.col(woe_col).is_null()).height
                if n_unmatched > 0:
                    fallback_counts[var] = n_unmatched
                    unmatched_total += n_unmatched
                    if woe_unmatched_policy == "fail":
                        raise ValueError(
                            f"apply_woe_mapping: {n_unmatched} rows in role={role!r} "
                            f"variable={var!r} did not match any bin"
                        )
                    df = df.with_columns(pl.col(woe_col).fill_null(0.0))

            out_art = context.outputs.publish_table(
                role=role, kind=EvidenceKind.SCORED_DATASET,
                frame=df,
                metadata={"source_artifact_id": data_art.artifact_id},
            )
            output_count += 1

            roles_evidence[role] = {
                "source_artifact_id": data_art.artifact_id,
                "output_artifact_id": getattr(out_art, "artifact_id", getattr(out_art, "provisional_artifact_id", "")),
                "source_physical_hash": data_art.physical_hash,
                "source_logical_hash": data_art.logical_hash,
                "row_count": df.height,
                "variables_applied": variables_applied,
                "woe_columns_created": woe_columns_created,
                "unmatched_by_variable": fallback_counts,
                "unmatched_row_count": sum(fallback_counts.values()),
            }

        evidence: JsonDict = {
            "schema_version": SCHEMA_APPLY_WOE_EVIDENCE,
            "policy": {"woe_unmatched_policy": woe_unmatched_policy},
            "roles": roles_evidence,
            "warnings": [],
        }
        if bundle_art is not None:
            evidence["frozen_bundle_artifact_id"] = bundle_art.artifact_id
        evidence["bin_definition_artifact_id"] = bin_def.source_artifact_id
        evidence["woe_table_artifact_id"] = woe_table.source_artifact_id
        if sel_art_id is not None:
            evidence["selection_artifact_id"] = sel_art_id

        context.outputs.publish_json(
            role="report", kind=EvidenceKind.APPLY_WOE_EVIDENCE,
            payload=evidence,
            metadata={"schema_version": SCHEMA_APPLY_WOE_EVIDENCE},
        )

        context.outputs.add_metric("output_count", output_count)
        context.outputs.add_metric("unmatched_row_count", unmatched_total)
        context.outputs.add_metric("woe_unmatched_policy", woe_unmatched_policy)

        return context.outputs.build_result()


class ApplyModelNode(NodeType):
    node_type = "cardre.apply_model"
    version = "2"
    category = "apply"

    __definition__ = NodeDefinition(
        node_type="cardre.apply_model",
        version="2",
        category="apply",
        description="Apply a fitted model to score datasets across train/test/oot roles",
        input_contract=ArtifactContract(
            roles=(
                # Only the model is hard-required. Scorecard is optional (the node
                # scores without it) and each of the three data roles is processed
                # for whichever datasets the plan supplies. The estimator role is
                # the binary twin of the JSON model (resolved by estimator_reference
                # artifact_id); it must remain in the input set.
                ArtifactRoleSpec("model", required=True),
                ArtifactRoleSpec("estimator", required=False),
                ArtifactRoleSpec("train", required=False),
                ArtifactRoleSpec("test", required=False),
                ArtifactRoleSpec("oot", required=False),
                ArtifactRoleSpec("scorecard", required=False),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("train", required=False),
                ArtifactRoleSpec("test", required=False),
                ArtifactRoleSpec("oot", required=False),
                ArtifactRoleSpec("report", required=True, kinds=(EvidenceKind.APPLY_MODEL_EVIDENCE,), media_types=("application/json",), schema_versions=(SCHEMA_APPLY_MODEL_EVIDENCE,)),
            ),
        ),
    )

    _DATA_ROLES = ("train", "test", "oot")

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Apply Model",
            methods=[
                MethodOption(
                    id="apply_model",
                    label="Apply Model",
                    status="available",
                    description="Apply a fitted model to score datasets.",
                    params=[],
                ),
            ],
        )

    def run(self, context: NodeContext) -> NodeResult:
        model_art = context.inputs.require("model", self.node_type)
        typed_model = context.inputs.read(model_art, EvidenceKind.MODEL_ARTIFACT)
        model = typed_model.to_dict()

        scorecard_arts = context.inputs.by_role("scorecard")
        scorecard_evidence = None
        scorecard_artifact_id = None
        if scorecard_arts:
            # A supplied scorecard must be a readable scorecard. Optionality
            # means the role may be absent; a supplied artifact that fails to
            # parse must fail the step rather than silently scoring unscaled.
            scorecard_evidence = context.inputs.read(scorecard_arts[0], EvidenceKind.SCORE_SCALING)
            scorecard_artifact_id = scorecard_arts[0].artifact_id

        bundle_art = context.inputs.find_frozen_bundle()
        if bundle_art is not None:
            bundle_meta = bundle_art.metadata
            if bundle_meta.get("model_artifact_id") != model_art.artifact_id:
                raise ValueError(
                    f"Frozen bundle model_artifact_id ({bundle_meta.get('model_artifact_id')}) "
                    f"does not match input model artifact ({model_art.artifact_id})"
                )
            expected_scorecard_id = bundle_meta.get("scorecard_artifact_id")
            if expected_scorecard_id:
                if not scorecard_arts:
                    raise ValueError(
                        f"Frozen bundle requires scorecard artifact "
                        f"{expected_scorecard_id}, but no scorecard scaling artifact was provided"
                    )
                if expected_scorecard_id != scorecard_artifact_id:
                    raise ValueError(
                        f"Frozen bundle scorecard_artifact_id ({expected_scorecard_id}) "
                        f"does not match input scorecard artifact ({scorecard_artifact_id})"
                    )
        bundle_artifact_id = bundle_art.artifact_id if bundle_art else None

        model_family = model.get("model_family", "logistic_regression")
        data_arts = []
        for role in self._DATA_ROLES:
            data_arts.extend(context.inputs.by_role(role))

        staged: list[Any] = []
        roles_evidence: dict[str, JsonDict] = {}

        for data_art in data_arts:
            df = context.inputs.read_dataframe(data_art)
            role = data_art.role

            if model_family == "logistic_regression":
                fc = model.get("feature_contract", {})
                features = fc.get("features", [])
                mp = model.get("model_payload", {})
                intercept = float(mp.get("intercept", 0))
                coefficients = mp.get("coefficients", {})

                has_scorecard = scorecard_evidence is not None
                if has_scorecard:
                    scorecard_parsed = scorecard_evidence.to_dict() if hasattr(scorecard_evidence, 'to_dict') else scorecard_evidence
                    offset = float(scorecard_parsed.get("offset", 0))
                    factor_val = float(scorecard_parsed.get("factor", 1))
                    direction = -1.0 if scorecard_parsed.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk" else 1.0
                else:
                    offset, factor_val, direction = 0.0, 1.0, -1.0

                missing = [f for f in features if f not in df.columns]
                if missing:
                    raise ValueError(f"apply_model: role {role!r} missing features {missing}")

                log_odds_expr = pl.lit(intercept)
                for feat in features:
                    log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(float(coefficients.get(feat, 0)))

                prob_expr = (1.0 / (1.0 + (-log_odds_expr).exp())).alias("predicted_bad_probability")
                raw_expr = log_odds_expr.alias("raw_model_output")

                df = df.with_columns([prob_expr, raw_expr])

                # Runtime calibration: a non-folded calibrator (isotonic,
                # CV-Platt, non-linear Platt) must transform the raw sigmoid
                # probabilities before scoring. Folded-linear calibration is
                # already baked into the coefficients and needs no runtime step.
                calibration = model.get("calibration") or {}
                if calibration.get("application_mode") == "runtime_probability_transform":
                    calibrator_id = calibration.get("calibrator_artifact_id", "")
                    if not calibrator_id:
                        raise ValueError(
                            "Model has calibration block but no calibrator_artifact_id"
                        )
                    calibrator = load_estimator(
                        context.inputs,
                        {
                            "artifact_id": calibrator_id,
                            "physical_hash": calibration.get("calibrator_physical_hash", ""),
                            "logical_hash": calibration.get("calibrator_logical_hash", ""),
                        },
                        node_type="apply_model",
                    )
                    if calibrator is None:
                        raise ValueError(
                            f"Calibrator artifact {calibrator_id!r} not among step inputs"
                        )
                    raw_probs = df["predicted_bad_probability"].to_numpy()
                    x_cal = np.column_stack([1.0 - raw_probs, raw_probs])
                    if hasattr(calibrator, "predict_proba"):
                        cal_probs = calibrator.predict_proba(x_cal)
                        cal_p = cal_probs[:, 1] if cal_probs.shape[1] > 1 else cal_probs[:, 0]
                    else:
                        cal_p = calibrator.predict(raw_probs)
                    cal_p = np.asarray(cal_p, dtype=np.float64)
                    cal_log_odds = np.log(
                        np.clip(cal_p / np.maximum(1 - cal_p, 1e-15), 1e-15, None),
                    )
                    df = df.with_columns([
                        pl.Series("predicted_bad_probability", cal_p, dtype=pl.Float64),
                        pl.Series("raw_model_output", cal_log_odds, dtype=pl.Float64),
                    ])

                base_metadata: JsonDict = {
                    "model_artifact_id": model_art.artifact_id,
                    "model_family": "logistic_regression",
                }
                if scorecard_artifact_id:
                    base_metadata["scorecard_artifact_id"] = scorecard_artifact_id
                if bundle_artifact_id:
                    base_metadata["frozen_bundle_artifact_id"] = bundle_artifact_id

                output_cols = ["predicted_bad_probability", "raw_model_output", "model_artifact_id", "model_family"]
                add_exprs = [
                    pl.lit(model_art.artifact_id).alias("model_artifact_id"),
                    pl.lit("logistic_regression").alias("model_family"),
                ]
                if has_scorecard:
                    score_expr = pl.lit(offset) + pl.lit(direction * factor_val) * pl.col("raw_model_output")
                    add_exprs.append(score_expr.alias("score"))
                    output_cols.append("score")

                df = df.with_columns(add_exprs)
                art = context.outputs.publish_table(
                    role=role, kind=EvidenceKind.SCORED_DATASET,
                    frame=df, metadata=base_metadata,
                )
                staged.append(art)

                roles_evidence[role] = _role_entry_from_df(
                    df, data_art, art, features, missing, output_cols, has_scorecard,
                )

            elif model_family in _SKLEARN_FAMILIES:
                estimator = _load_estimator(context, model)
                prob_col_idx = int(model.get("probability_column_index", 1))
                features = model.get("feature_contract", {}).get("features", [])
                missing = [f for f in features if f not in df.columns]
                if missing:
                    raise ValueError(f"apply_model: role {role!r} missing features {missing}")
                X = df.select(features).to_numpy()
                if hasattr(estimator, "predict_proba"):
                    proba = estimator.predict_proba(X)
                    if prob_col_idx < 0 or prob_col_idx >= proba.shape[1]:
                        raise ValueError(
                            f"probability_column_index {prob_col_idx} is out of range "
                            f"for predict_proba output with {proba.shape[1]} columns"
                        )
                    pred_bad = proba[:, prob_col_idx]
                else:
                    pred_bad = estimator.predict(X).astype(np.float64)

                calibration = model.get("calibration") or {}
                if calibration.get("application_mode") == "runtime_probability_transform":
                    pred_bad = _apply_runtime_calibration(
                        context, calibration, pred_bad,
                    )
                pred_bad = np.asarray(pred_bad, dtype=np.float64)

                has_scorecard = scorecard_evidence is not None
                base_metadata: JsonDict = {
                    "model_artifact_id": model_art.artifact_id,
                    "model_family": model_family,
                }
                if scorecard_artifact_id:
                    base_metadata["scorecard_artifact_id"] = scorecard_artifact_id
                if bundle_artifact_id:
                    base_metadata["frozen_bundle_artifact_id"] = bundle_artifact_id

                output_cols = ["predicted_bad_probability", "model_artifact_id", "model_family"]
                add_exprs = [
                    pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
                    pl.lit(model_art.artifact_id).alias("model_artifact_id"),
                    pl.lit(model_family).alias("model_family"),
                ]
                if has_scorecard:
                    sc_parsed = scorecard_evidence.to_dict() if hasattr(scorecard_evidence, "to_dict") else scorecard_evidence
                    offset = float(sc_parsed.get("offset", 0))
                    factor_val = float(sc_parsed.get("factor", 1))
                    direction = -1.0 if sc_parsed.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk" else 1.0
                    log_odds = np.log(np.clip(pred_bad / np.maximum(1 - pred_bad, 1e-15), 1e-15, None))
                    score_vals = offset + direction * factor_val * log_odds
                    add_exprs.append(pl.Series("score", score_vals, dtype=pl.Float64))
                    output_cols.append("score")

                df = df.with_columns(add_exprs)
                art = context.outputs.publish_table(
                    role=role, kind=EvidenceKind.SCORED_DATASET,
                    frame=df, metadata=base_metadata,
                )
                staged.append(art)
                roles_evidence[role] = _role_entry_from_df(
                    df, data_art, art, features, missing, output_cols, has_scorecard,
                )

            elif model_family in _ENSEMBLE_FAMILIES:
                raise NotImplementedError(
                    f"apply_model: model_family {model_family!r} (ensemble) is not yet "
                    f"supported through NodeContext."
                )
            else:
                raise ValueError(
                    f"apply_model: unsupported model_family {model_family!r}. "
                    f"Supported families: logistic_regression, "
                    f"{', '.join(sorted(_SKLEARN_FAMILIES))}"
                )

        evidence: JsonDict = {
            "schema_version": SCHEMA_APPLY_MODEL_EVIDENCE,
            "model_artifact_id": model_art.artifact_id,
            "roles": roles_evidence,
            "warnings": [],
        }
        if bundle_artifact_id is not None:
            evidence["frozen_bundle_artifact_id"] = bundle_artifact_id
        if scorecard_artifact_id is not None:
            evidence["scorecard_artifact_id"] = scorecard_artifact_id

        context.outputs.publish_json(
            role="report", kind=EvidenceKind.APPLY_MODEL_EVIDENCE,
            payload=evidence,
            metadata={"schema_version": SCHEMA_APPLY_MODEL_EVIDENCE},
        )

        context.outputs.add_metric("output_count", len(staged))
        return context.outputs.build_result()


_SKLEARN_FAMILIES = {"random_forest", "xgboost", "lightgbm", "catboost", "gbdt", "svm", "mlp", "decision_tree"}
_ENSEMBLE_FAMILIES = {"voting_ensemble", "stacking_ensemble", "blending_ensemble"}


def _load_estimator(context: NodeContext, model: dict[str, Any]) -> Any:
    """Load a serialized estimator binary through the shared deep module.

    The classifier node publishes the JSON model first and the joblib
    estimator binary second (same descriptor family). The JSON model carries
    ``estimator_reference.artifact_id`` pointing at the binary; resolution,
    hash verification and ``creating_run_id`` enforcement are centralized in
    ``load_estimator`` (see ADR-0016).
    """
    estimator_ref = model.get("estimator_reference") or {}
    estimator_artifact_id = estimator_ref.get("artifact_id", "")
    if not estimator_artifact_id:
        raise ValueError(
            f"apply_model: non-logistic model_family "
            f"{model.get('model_family')!r} requires estimator_reference.artifact_id"
        )
    estimator = load_estimator(context.inputs, estimator_ref, node_type="apply_model")
    if estimator is None:
        raise ValueError(
            f"apply_model: estimator artifact {estimator_artifact_id!r} not among step inputs"
        )
    return estimator


def _apply_runtime_calibration(
    context: NodeContext,
    calibration: dict[str, Any],
    raw_probs: np.ndarray,
) -> np.ndarray:
    """Apply a runtime probability-transform calibrator to raw probabilities.

    Mirrors the logistic-regression branch: a non-folded calibrator (isotonic,
    CV-Platt, non-linear Platt) transforms probabilities before scoring.
    Folded-linear calibration is baked into coefficients and needs no runtime
    step. The calibrator binary is loaded through the shared verified loader
    (ADR-0016), which raises on hash mismatch or missing provenance.
    """
    calibrator_id = calibration.get("calibrator_artifact_id", "")
    if not calibrator_id:
        raise ValueError("Model has calibration block but no calibrator_artifact_id")
    calibrator_ref = {
        "artifact_id": calibrator_id,
        "physical_hash": calibration.get("calibrator_physical_hash", ""),
        "logical_hash": calibration.get("calibrator_logical_hash", ""),
    }
    calibrator = load_estimator(context.inputs, calibrator_ref, node_type="apply_model")
    if calibrator is None:
        raise ValueError(f"Calibrator artifact {calibrator_id!r} not among step inputs")
    x_cal = np.column_stack([1.0 - raw_probs, raw_probs])
    if hasattr(calibrator, "predict_proba"):
        cal_probs = calibrator.predict_proba(x_cal)
        cal_p = cal_probs[:, 1] if cal_probs.shape[1] > 1 else cal_probs[:, 0]
    else:
        cal_p = calibrator.predict(raw_probs)
    return np.asarray(cal_p, dtype=np.float64)


def _role_entry_from_df(
    df: pl.DataFrame,
    data_art: Any,
    art: Any,
    features: list[str],
    missing: list[str],
    output_cols: list[str],
    has_scorecard: bool,
) -> JsonDict:
    pd_series = df["predicted_bad_probability"]
    art_id = getattr(art, "artifact_id", getattr(art, "provisional_artifact_id", ""))
    entry: JsonDict = {
        "source_artifact_id": data_art.artifact_id,
        "output_artifact_id": art_id,
        "row_count": df.height,
        "required_features": features,
        "missing_features": missing,
        "output_columns": output_cols,
        "pd_min": round(float(pd_series.min()), 6),
        "pd_max": round(float(pd_series.max()), 6),
        "pd_mean": round(float(pd_series.mean()), 6),
    }
    if has_scorecard and "score" in df.columns:
        score_series = df["score"]
        entry["score_min"] = round(float(score_series.min()), 2)
        entry["score_max"] = round(float(score_series.max()), 2)
        entry["score_mean"] = round(float(score_series.mean()), 2)
    return entry

