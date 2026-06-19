from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ArtifactRef, ExecutionContext, JsonDict, NodeOutput, NodeType
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.nodes._bin_mask import build_bin_condition
from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_SCORE_APPLICATION_EVIDENCE,
    SCHEMA_SCORE_SCALING,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_WOE_APPLICATION_EVIDENCE,
)


class ApplyWoeMappingNode(NodeType):
    node_type = "cardre.apply_woe_mapping"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition", "report", "scorecard"]
    output_roles: list[str] = ["train", "test", "oot"]

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
                            default="warn",
                            constraint=ParameterConstraint(enum_values=["fill_zero", "warn", "fail"]),
                            help_text="Policy when rows do not match any WOE bin: fill_zero, warn, or fail",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        policy = params.get("woe_unmatched_policy", "warn")
        if policy not in self.VALID_UNMATCHED_POLICIES:
            errors.append(
                f"woe_unmatched_policy must be one of {self.VALID_UNMATCHED_POLICIES}, got {policy!r}"
            )
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        woe_unmatched_policy = params.get("woe_unmatched_policy", "warn")

        # Detect frozen scorecard bundle for governed-path defaults
        bundle_art = next(
            (a for a in context.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )
        if bundle_art is not None and "woe_unmatched_policy" not in params:
            woe_unmatched_policy = "fail"

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)
        sel_def = reader.find_optional(context.input_artifacts, EvidenceKind.SELECTION_DEFINITION)

        selected_names: set[str] | None = None
        if sel_def is not None:
            selected_names = sel_def.selected_names

        woe_map = woe_table.mapping

        var_defs = bin_def.variables
        if selected_names is not None:
            var_defs = [v for v in var_defs if v.variable in selected_names]

        # Find referenced artifact ids for evidence
        # (source_artifact_id is populated by the evidence reader's typed parsers)
        sel_art = next(
            (a for a in context.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_SELECTION_DEFINITION),
            None,
        )

        # Verify bundle components against actual artifacts being applied
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
                if sel_art is None:
                    raise ValueError(
                        f"Frozen bundle requires selection artifact "
                        f"{expected_selection_id}, but no selection artifact was provided"
                    )
                if expected_selection_id != sel_art.artifact_id:
                    raise ValueError(
                        f"Frozen bundle selection_artifact_id "
                        f"({expected_selection_id}) "
                        f"does not match the selection being applied "
                        f"({sel_art.artifact_id})"
                    )

        # Per-role evidence tracking
        roles_evidence: dict[str, JsonDict] = {}
        outputs: list[ArtifactRef] = []
        unmatched_total = 0

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role
            fallback_counts: dict[str, int] = {}
            woe_columns_created: list[str] = []
            variables_applied: list[str] = []

            for vd in var_defs:
                var = vd.variable
                kind = vd.kind
                bins = vd.bins
                if var not in df.columns:
                    continue
                woe_col = f"{var}_woe"
                woe_expr = None

                for be in bins:
                    bid = be["bin_id"]

                    mask = build_bin_condition(be, pl.col(var), kind, bins, variable=var, bin_id=bid)

                    wv = woe_map.get(var, {}).get(bid)
                    if wv is None:
                        raise ValueError(f"apply_woe_mapping: missing WOE for {var}:{bid}")
                    wc = pl.when(mask).then(pl.lit(wv))
                    woe_expr = wc if woe_expr is None else woe_expr.when(mask).then(pl.lit(wv))

                if woe_expr is not None:
                    woe_expr = woe_expr.otherwise(pl.lit(None, dtype=pl.Float64))
                    df = df.with_columns(woe_expr.alias(woe_col))
                    woe_columns_created.append(woe_col)
                    variables_applied.append(var)
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

            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"woe-apply-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata={"source_artifact_id": data_art.artifact_id},
            )
            outputs.append(art)

            roles_evidence[role] = {
                "source_artifact_id": data_art.artifact_id,
                "output_artifact_id": art.artifact_id,
                "source_physical_hash": data_art.physical_hash,
                "source_logical_hash": data_art.logical_hash,
                "row_count": df.height,
                "variables_applied": variables_applied,
                "woe_columns_created": woe_columns_created,
                "unmatched_by_variable": fallback_counts,
                "unmatched_row_count": sum(fallback_counts.values()),
            }

        evidence: JsonDict = {
            "schema_version": SCHEMA_WOE_APPLICATION_EVIDENCE,
            "policy": {"woe_unmatched_policy": woe_unmatched_policy},
            "roles": roles_evidence,
            "warnings": [],
        }
        if bundle_art is not None:
            evidence["frozen_bundle_artifact_id"] = bundle_art.artifact_id
        evidence["bin_definition_artifact_id"] = bin_def.source_artifact_id
        evidence["woe_table_artifact_id"] = woe_table.source_artifact_id
        if sel_art is not None:
            evidence["selection_artifact_id"] = sel_art.artifact_id

        evidence_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-apply-evidence-{context.step_spec.step_id}",
            payload=evidence,
            metadata={"schema_version": SCHEMA_WOE_APPLICATION_EVIDENCE},
        )

        all_artifacts = outputs + [evidence_art]
        return NodeOutput(
            artifacts=all_artifacts,
            metrics={
                "output_count": len(outputs),
                "unmatched_row_count": unmatched_total,
                "woe_unmatched_policy": woe_unmatched_policy,
            })


class ApplyModelNode(NodeType):
    node_type = "cardre.apply_model"
    version = "2"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "model", "scorecard"]
    output_roles: list[str] = ["train", "test", "oot"]

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

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)

        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
        scorecard_art = next(
            (a for a in context.input_artifacts
             if a.role == "scorecard"
             and a.metadata.get("schema_version") == SCHEMA_SCORE_SCALING),
            None,
        )
        if model_art is None:
            raise ValueError("apply_model requires a model artifact")

        # Detect frozen bundle
        bundle_art = next(
            (a for a in context.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )
        if bundle_art is not None:
            bundle_meta = bundle_art.metadata
            if bundle_meta.get("model_artifact_id") != model_art.artifact_id:
                raise ValueError(
                    f"Frozen bundle model_artifact_id ({bundle_meta.get('model_artifact_id')}) "
                    f"does not match input model artifact ({model_art.artifact_id})"
                )
            expected_scorecard_id = bundle_meta.get("scorecard_artifact_id")
            if expected_scorecard_id:
                if scorecard_art is None:
                    raise ValueError(
                        f"Frozen bundle requires scorecard artifact "
                        f"{expected_scorecard_id}, but no scorecard scaling artifact was provided"
                    )
                if expected_scorecard_id != scorecard_art.artifact_id:
                    raise ValueError(
                        f"Frozen bundle scorecard_artifact_id ({expected_scorecard_id}) "
                        f"does not match input scorecard artifact ({scorecard_art.artifact_id})"
                    )

        model = json.loads(store.artifact_path(model_art).read_text())
        if "model_family" not in model:
            typed_model = reader.find_optional(context.input_artifacts, EvidenceKind.MODEL_ARTIFACT)
            if typed_model is not None:
                model.update(typed_model.as_legacy_dict())

        model_family = model.get("model_family", "logistic_regression")
        if model_family == "logistic_regression":
            return self._apply_logistic(context, model, model_art, scorecard_art, bundle_art)
        elif model_family in (
            "decision_tree", "random_forest", "gbdt",
            "xgboost", "lightgbm", "catboost",
        ):
            return self._apply_sklearn_estimator(context, model, model_art, scorecard_art, bundle_art)
        elif model_family in ("voting_ensemble", "weighted_ensemble"):
            return self._apply_voting_weighted_ensemble(context, model, model_art, bundle_art)
        else:
            raise ValueError(
                f"apply_model: unsupported model_family {model_family!r}. "
                f"Supported families: logistic_regression, decision_tree, random_forest, "
                f"gbdt, xgboost, lightgbm, catboost, voting_ensemble, weighted_ensemble"
            )

    def _apply_logistic(
        self, context: ExecutionContext, model: dict, model_art, scorecard_art, bundle_art=None,
    ) -> NodeOutput:
        store = context.store

        features = model.get("features", [])
        intercept = float(model.get("intercept", 0))
        coefficients = model.get("coefficients", {})

        if scorecard_art is not None:
            scorecard = json.loads(store.artifact_path(scorecard_art).read_text())
            offset = float(scorecard.get("offset", 0))
            factor_val = float(scorecard.get("factor", 1))
            direction = -1.0 if scorecard.get("higher_score_is_lower_risk", True) else 1.0
            has_scorecard = True
        else:
            offset = 0.0
            factor_val = 1.0
            direction = -1.0
            has_scorecard = False

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        outputs: list[ArtifactRef] = []
        roles_evidence: dict[str, JsonDict] = {}

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role
            missing = [f for f in features if f not in df.columns]
            if missing:
                raise ValueError(
                    f"apply_model: role {role!r} missing features {missing}"
                )

            log_odds_expr = pl.lit(intercept)
            for feat in features:
                coef = float(coefficients.get(feat, 0))
                log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(coef)

            prob_expr = (1.0 / (1.0 + (-log_odds_expr).exp())).alias("predicted_bad_probability")
            raw_expr = log_odds_expr.alias("raw_model_output")

            base_metadata: JsonDict = {"model_artifact_id": model_art.artifact_id, "model_family": "logistic_regression"}
            if scorecard_art is not None:
                base_metadata["scorecard_artifact_id"] = scorecard_art.artifact_id
            if bundle_art is not None:
                base_metadata["frozen_bundle_artifact_id"] = bundle_art.artifact_id

            output_cols = ["predicted_bad_probability", "raw_model_output", "model_artifact_id", "model_family"]
            add_exprs = [prob_expr, raw_expr,
                         pl.lit(model_art.artifact_id).alias("model_artifact_id"),
                         pl.lit("logistic_regression").alias("model_family")]

            if has_scorecard:
                score_expr = pl.lit(offset) + pl.lit(direction * factor_val) * log_odds_expr
                add_exprs.append(score_expr.alias("score"))
                add_exprs.append(score_expr.alias("cardre_scaled_score"))
                output_cols.extend(["score", "cardre_scaled_score"])

            df = df.with_columns(add_exprs)
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"scored-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata=base_metadata,
            )
            outputs.append(art)

            pd_series = df["predicted_bad_probability"]
            role_entry: JsonDict = {
                "source_artifact_id": data_art.artifact_id,
                "output_artifact_id": art.artifact_id,
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
                role_entry["score_min"] = round(float(score_series.min()), 2)
                role_entry["score_max"] = round(float(score_series.max()), 2)
                role_entry["score_mean"] = round(float(score_series.mean()), 2)
            roles_evidence[role] = role_entry

        evidence: JsonDict = {
            "schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE,
            "model_artifact_id": model_art.artifact_id,
            "roles": roles_evidence,
            "warnings": [],
        }
        if bundle_art is not None:
            evidence["frozen_bundle_artifact_id"] = bundle_art.artifact_id
        if scorecard_art is not None:
            evidence["scorecard_artifact_id"] = scorecard_art.artifact_id

        evidence_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"score-apply-evidence-{context.step_spec.step_id}",
            payload=evidence,
            metadata={"schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE},
        )

        return NodeOutput(
            artifacts=outputs + [evidence_art],
            metrics={"output_count": len(outputs)},
        )

    def _apply_sklearn_estimator(
        self, context: ExecutionContext, model: dict, model_art, scorecard_art, bundle_art=None,
    ) -> NodeOutput:
        store = context.store

        estimator_ref = model.get("estimator_reference", {})
        estimator_artifact_id = estimator_ref.get("artifact_id", "")

        feature_contract = model.get("feature_contract", {})
        features = feature_contract.get("features", [])
        if not features:
            features = model.get("features", [])

        prob_col_idx = model.get("probability_column_index", 1)

        scorecard = None
        if scorecard_art is not None:
            scorecard = json.loads(store.artifact_path(scorecard_art).read_text())

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        outputs: list[ArtifactRef] = []
        roles_evidence: dict[str, JsonDict] = {}

        if not estimator_artifact_id:
            raise ValueError(
                "apply_model: non-logistic model requires estimator_reference.artifact_id"
            )

        estimator_art = store.get_artifact(estimator_artifact_id)
        if estimator_art is None:
            raise ValueError(
                f"apply_model: estimator artifact {estimator_artifact_id!r} not found"
            )

        from cardre.modeling.serialization import read_estimator_artifact
        estimator_bytes = read_estimator_artifact(
            store, estimator_art,
            expected_logical_hash=estimator_ref.get("logical_hash"),
        )

        import io
        import joblib
        estimator = joblib.load(io.BytesIO(estimator_bytes))

        model_family = model.get("model_family", "unknown")
        has_scorecard = scorecard is not None

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role
            missing = [f for f in features if f not in df.columns]
            if missing:
                raise ValueError(
                    f"apply_model: role {role!r} missing features {missing}"
                )

            X = df.select(features).to_numpy()

            if hasattr(estimator, "predict_proba"):
                proba = estimator.predict_proba(X)
                if proba.shape[1] > prob_col_idx:
                    pred_bad = proba[:, prob_col_idx]
                else:
                    pred_bad = proba[:, -1]
            else:
                raw_output = estimator.predict(X)
                pred_bad = raw_output.astype(np.float64)

            base_metadata: JsonDict = {"model_artifact_id": model_art.artifact_id, "model_family": model_family}
            if scorecard_art is not None:
                base_metadata["scorecard_artifact_id"] = scorecard_art.artifact_id
            if bundle_art is not None:
                base_metadata["frozen_bundle_artifact_id"] = bundle_art.artifact_id

            output_cols = ["predicted_bad_probability", "model_artifact_id", "model_family"]
            add_exprs = [
                pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
                pl.lit(model_art.artifact_id).alias("model_artifact_id"),
                pl.lit(model_family).alias("model_family"),
            ]

            if has_scorecard:
                offset = float(scorecard.get("offset", 0))
                factor = float(scorecard.get("factor", 1))
                higher_is_lower = scorecard.get("higher_score_is_lower_risk", True)
                direction = -1.0 if higher_is_lower else 1.0
                log_odds = np.log(np.clip(pred_bad / np.maximum(1 - pred_bad, 1e-15), 1e-15, None))
                score_vals = offset + direction * factor * log_odds
                score_series = pl.Series("score", score_vals, dtype=pl.Float64)
                add_exprs.append(score_series)
                add_exprs.append(score_series.alias("cardre_scaled_score"))
                output_cols.extend(["score", "cardre_scaled_score"])

            df = df.with_columns(add_exprs)
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"scored-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata=base_metadata,
            )
            outputs.append(art)

            pd_series = df["predicted_bad_probability"]
            role_entry: JsonDict = {
                "source_artifact_id": data_art.artifact_id,
                "output_artifact_id": art.artifact_id,
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
                role_entry["score_min"] = round(float(score_series.min()), 2)
                role_entry["score_max"] = round(float(score_series.max()), 2)
                role_entry["score_mean"] = round(float(score_series.mean()), 2)
            roles_evidence[role] = role_entry

        evidence: JsonDict = {
            "schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE,
            "model_artifact_id": model_art.artifact_id,
            "roles": roles_evidence,
            "warnings": [],
        }
        if bundle_art is not None:
            evidence["frozen_bundle_artifact_id"] = bundle_art.artifact_id
        if scorecard_art is not None:
            evidence["scorecard_artifact_id"] = scorecard_art.artifact_id

        evidence_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"score-apply-evidence-{context.step_spec.step_id}",
            payload=evidence,
            metadata={"schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE},
        )

        return NodeOutput(
            artifacts=outputs + [evidence_art],
            metrics={"output_count": len(outputs)},
        )

    def _apply_voting_weighted_ensemble(
        self, context: ExecutionContext, model: dict, model_art, bundle_art=None,
    ) -> NodeOutput:
        store = context.store
        model_payload = model.get("model_payload", {})
        base_models = model_payload.get("base_models", [])
        ensemble_type = model_payload.get("ensemble_type", "voting")
        weights_list = model_payload.get("weights", None)
        voting = model_payload.get("voting", "soft")
        threshold = model_payload.get("threshold", 0.5)

        features = model.get("features", [])
        prob_col_idx = model.get("probability_column_index", 1)

        base_artifacts = []
        for bm in base_models:
            aid = bm.get("artifact_id", "")
            if not aid:
                continue
            art = store.get_artifact(aid)
            if art is None:
                continue
            try:
                base_artifacts.append(json.loads(store.artifact_path(art).read_text()))
            except Exception:
                continue

        if not base_artifacts:
            raise ValueError("No base model artifacts could be loaded for ensemble apply")

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        outputs: list[ArtifactRef] = []
        roles_evidence: dict[str, JsonDict] = {}

        model_family = model.get("model_family", "unknown")

        for data_art in data_arts:
            df = pl.read_parquet(store.artifact_path(data_art))
            role = data_art.role

            all_probs = []
            for bm_art in base_artifacts:
                bm_art_features = bm_art.get("features", [])
                bm_features = bm_art.get("feature_contract", {}).get("features", []) or bm_art_features
                missing = [f for f in bm_features if f not in df.columns]
                if missing:
                    raise ValueError(
                        f"apply_model: ensemble base model role {role!r} missing features {missing}"
                    )

                bm_family = bm_art.get("model_family", "")
                bm_prob_col = bm_art.get("probability_column_index", 1)

                if bm_family == "logistic_regression":
                    coefs = bm_art.get("coefficients", {})
                    intercept = float(bm_art.get("intercept", 0))
                    log_odds_expr = pl.lit(intercept)
                    for feat in bm_features:
                        log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(float(coefs.get(feat, 0)))
                    probs = df.select((1.0 / (1.0 + (-log_odds_expr).exp())).alias("_probs"))["_probs"].to_numpy()
                else:
                    estimator_ref = bm_art.get("estimator_reference", {})
                    estimator_art_id = estimator_ref.get("artifact_id", "")
                    if not estimator_art_id:
                        raise ValueError("Ensemble base model missing estimator_reference")
                    est_art = store.get_artifact(estimator_art_id)
                    if est_art is None:
                        raise ValueError(f"Base model estimator artifact {estimator_art_id!r} not found")
                    from cardre.modeling.serialization import read_estimator_artifact
                    import joblib
                    import io
                    est_bytes = read_estimator_artifact(
                        store, est_art,
                        expected_logical_hash=estimator_ref.get("logical_hash"),
                    )
                    estimator = joblib.load(io.BytesIO(est_bytes))
                    X = df.select(bm_features).to_numpy()
                    if hasattr(estimator, "predict_proba"):
                        proba = estimator.predict_proba(X)
                        if proba.shape[1] > bm_prob_col:
                            probs = proba[:, bm_prob_col]
                        else:
                            probs = proba[:, -1]
                    else:
                        probs = estimator.predict(X).astype(np.float64)
                all_probs.append(probs)

            prob_matrix = np.column_stack(all_probs)

            if ensemble_type == "weighted" and weights_list:
                weights = np.array(weights_list, dtype=np.float64)
                pred_bad = prob_matrix @ weights
            elif voting == "soft":
                pred_bad = np.mean(prob_matrix, axis=1)
            else:
                predictions = (prob_matrix >= threshold).astype(int)
                pred_bad = (np.sum(predictions, axis=1) > (len(base_artifacts) / 2)).astype(float)

            base_metadata: JsonDict = {"model_artifact_id": model_art.artifact_id, "model_family": model_family}
            if bundle_art is not None:
                base_metadata["frozen_bundle_artifact_id"] = bundle_art.artifact_id

            output_cols = ["predicted_bad_probability", "model_artifact_id", "model_family"]
            add_exprs = [
                pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
                pl.lit(model_art.artifact_id).alias("model_artifact_id"),
                pl.lit(model_family).alias("model_family"),
            ]

            df = df.with_columns(add_exprs)
            art = write_parquet_artifact(
                store, artifact_type="dataset", role=role,
                stem=f"scored-{role}-{context.step_spec.step_id}",
                frame=df,
                metadata=base_metadata,
            )
            outputs.append(art)

            pd_series = df["predicted_bad_probability"]
            roles_evidence[role] = {
                "source_artifact_id": data_art.artifact_id,
                "output_artifact_id": art.artifact_id,
                "row_count": df.height,
                "required_features": features,
                "missing_features": [],
                "output_columns": output_cols,
                "pd_min": round(float(pd_series.min()), 6),
                "pd_max": round(float(pd_series.max()), 6),
                "pd_mean": round(float(pd_series.mean()), 6),
            }

        evidence: JsonDict = {
            "schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE,
            "model_artifact_id": model_art.artifact_id,
            "roles": roles_evidence,
            "warnings": [],
        }
        if bundle_art is not None:
            evidence["frozen_bundle_artifact_id"] = bundle_art.artifact_id

        evidence_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"score-apply-evidence-{context.step_spec.step_id}",
            payload=evidence,
            metadata={"schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE},
        )

        return NodeOutput(
            artifacts=outputs + [evidence_art],
            metrics={"output_count": len(outputs)},
        )


class DummyApplyNode(NodeType):
    node_type = "cardre.dummy_apply"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["prediction"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        data_artifacts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        def_artifact = next((a for a in context.input_artifacts if a.role == "definition"), None)

        if def_artifact is None:
            raise ValueError("Dummy apply requires a definition artifact")

        input_roles = {a.role for a in data_artifacts}
        required_roles = {"train", "test", "oot"}
        missing = required_roles - input_roles
        if missing:
            raise ValueError(
                f"Dummy apply requires train, test, and oot artifacts. "
                f"Missing: {sorted(missing)}. "
                f"Received roles: {sorted(input_roles)}"
            )

        outputs = []
        for data_art in data_artifacts:
            df = pl.read_parquet(store.artifact_path(data_art))
            pred = pl.DataFrame({
                "dummy_prediction": [0.5] * df.height,
                "row_id": list(range(df.height)),
            })

            artifact = write_parquet_artifact(
                store,
                artifact_type="dataset",
                role="prediction",
                stem=f"apply-{data_art.role}-{context.step_spec.step_id}",
                frame=pred,
                metadata={
                    "source_artifact_id": data_art.artifact_id,
                    "definition_artifact_id": def_artifact.artifact_id,
                },
                directory="artifacts",
            )
            outputs.append(artifact)

        return NodeOutput(
            artifacts=outputs,
            metrics={"output_count": len(outputs)})
