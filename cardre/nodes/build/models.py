from __future__ import annotations

import json  # noqa: F401 — imported for monkeypatch compatibility in tests
import math
import warnings
from typing import Any

from cardre._evidence.kinds import (
    EvidenceKind,
    EvidenceNotFoundError,
)
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import SCHEMA_MODEL_ARTIFACT, SCHEMA_SCORE_SCALING
from cardre.artifacts import write_json_artifact
from cardre.domain.artifacts import json_logical_hash
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.build._logit_helpers import (
    COEF_ROUND,
    POINTS_ROUND,
    WOE_ROUND,
    build_class_mapping,
    build_lr_params,
    build_scorecard_attribute,
    parse_base_odds,
    resolve_features,
)
from cardre.nodes.contracts import NodeContext, NodeResult, NodeType
from cardre.nodes.parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)


class LogisticRegressionNode(NodeType):
    node_type = "cardre.logistic_regression"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_PENALTIES = {"l1", "l2", "elasticnet", None}
    VALID_SOLVERS = {"lbfgs", "liblinear", "newton-cg", "newton-cholesky", "sag", "saga"}

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Logistic Regression",
            default_method="standard_logit",
            methods=[
                MethodOption(
                    id="standard_logit",
                    label="Standard Logit",
                    status="available",
                    description="Standard logistic regression with L2 penalty (default).",
                    params=[
                        ParameterDefinition(
                            name="solver",
                            label="Solver",
                            kind="enum",
                            default="lbfgs",
                            help_text="Algorithm to use in the optimization problem.",
                            constraint=ParameterConstraint(enum_values=sorted(cls.VALID_SOLVERS)),
                        ),
                        ParameterDefinition(
                            name="C",
                            label="Inverse Regularization Strength",
                            kind="float",
                            default=1.0,
                            help_text="Inverse of regularization strength; must be positive.",
                            constraint=ParameterConstraint(min_value=0.0, exclusive_min=0.0),
                        ),
                        ParameterDefinition(
                            name="max_iter",
                            label="Max Iterations",
                            kind="integer",
                            default=1000,
                            help_text="Maximum number of iterations for convergence.",
                            constraint=ParameterConstraint(min_value=1),
                        ),
                        ParameterDefinition(
                            name="random_seed",
                            label="Random Seed",
                            kind="integer",
                            default=42,
                            help_text="Random state for reproducibility.",
                            constraint=ParameterConstraint(min_value=0),
                        ),
                        ParameterDefinition(
                            name="fail_on_non_convergence",
                            label="Fail on Non-convergence",
                            kind="boolean",
                            default=True,
                            help_text="Raise when logistic regression does not converge. Set to false to warn only.",
                        ),
                    ],
                ),
                MethodOption(
                    id="penalised_logit",
                    label="Penalised Logit",
                    status="available",
                    description="Logistic regression with configurable penalty.",
                    params=[
                        ParameterDefinition(
                            name="penalty",
                            label="Penalty",
                            kind="enum",
                            default="l2",
                            help_text="Norm used in the penalization.",
                            constraint=ParameterConstraint(enum_values=["l1", "l2", "elasticnet"]),
                        ),
                        ParameterDefinition(
                            name="solver",
                            label="Solver",
                            kind="enum",
                            default="lbfgs",
                            help_text="Algorithm to use in the optimization problem.",
                            constraint=ParameterConstraint(enum_values=sorted(cls.VALID_SOLVERS)),
                        ),
                        ParameterDefinition(
                            name="C",
                            label="Inverse Regularization Strength",
                            kind="float",
                            default=1.0,
                            help_text="Inverse of regularization strength; must be positive.",
                            constraint=ParameterConstraint(min_value=0.0, exclusive_min=0.0),
                        ),
                        ParameterDefinition(
                            name="max_iter",
                            label="Max Iterations",
                            kind="integer",
                            default=1000,
                            help_text="Maximum number of iterations for convergence.",
                            constraint=ParameterConstraint(min_value=1),
                        ),
                        ParameterDefinition(
                            name="random_seed",
                            label="Random Seed",
                            kind="integer",
                            default=42,
                            help_text="Random state for reproducibility.",
                            constraint=ParameterConstraint(min_value=0),
                        ),
                        ParameterDefinition(
                            name="fail_on_non_convergence",
                            label="Fail on Non-convergence",
                            kind="boolean",
                            default=True,
                            help_text="Raise when logistic regression does not converge. Set to false to warn only.",
                        ),
                    ],
                ),
                MethodOption(
                    id="lasso_logit",
                    label="Lasso Logit",
                    status="coming_soon",
                    description="L1-regularized logistic regression (LASSO).",
                    params=[],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        penalty = params.get("penalty")
        if penalty is not None and penalty not in self.VALID_PENALTIES:
            errors.append(f"penalty must be one of {self.VALID_PENALTIES}, got '{penalty}'")
        solver = params.get("solver", "lbfgs")
        if solver not in self.VALID_SOLVERS:
            errors.append(f"solver must be one of {self.VALID_SOLVERS}, got '{solver}'")
        C = params.get("C", 1.0)
        try:
            if float(C) <= 0:
                errors.append("C must be positive")
        except (ValueError, TypeError):
            errors.append("C must be a number")
        max_iter = params.get("max_iter", 1000)
        try:
            if int(max_iter) < 1:
                errors.append("max_iter must be >= 1")
        except (ValueError, TypeError):
            errors.append("max_iter must be an integer")
        return errors

    def run(self, context: Any) -> Any:
        """Dispatch to NodeContext or ExecutionContext implementation.

        Backward compat: step runner still passes ``ExecutionContext``.
        New callers should pass ``NodeContext``.
        """
        if hasattr(context, 'inputs'):
            return self._run_node_context(context)
        return self._run_execution_context(context)

    def _run_node_context(self, context: NodeContext) -> NodeResult:
        import numpy as np
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import LogisticRegression as SkLearnLR

        params = context.params
        train_artifact = context.inputs.require("train", "LogisticRegressionNode")

        meta = context.inputs.target_metadata()
        from cardre.modeling.target import TargetSpec
        target_spec = TargetSpec.from_metadata(meta)
        if target_spec is None:
            raise ValueError("Target metadata is required for logistic regression")

        sel_def_list = context.inputs.by_kind(EvidenceKind.SELECTION_DEFINITION)  # type: ignore[arg-type]
        sel_def = sel_def_list[0] if sel_def_list else None

        target_column = target_spec.target_column
        good_values = target_spec.good_values
        bad_values = target_spec.bad_values

        df = context.inputs.read_dataframe(train_artifact)
        woe_cols = [c for c in df.columns if c.endswith("_woe")]
        if not woe_cols:
            raise ValueError("No WOE-transformed columns found in training data")

        X = df.select(woe_cols).to_numpy()

        if target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found in training data")

        target_spec.validate_good_bad_only(df)
        y_binary = target_spec.encode_binary_strict(df).to_list()
        n_bad = sum(y_binary)
        n_good = len(y_binary) - n_bad
        if n_bad == 0:
            raise ValueError(f"Logistic regression: no bad-class rows found (bad_values={sorted(bad_values)})")
        if n_good == 0:
            raise ValueError(f"Logistic regression: no good-class rows found (good_values={sorted(good_values)})")

        lr_params = build_lr_params(params)

        lr = SkLearnLR(**lr_params)
        with warnings.catch_warnings(record=True) as fit_warnings:
            warnings.simplefilter("always")
            lr.fit(X, y_binary)

        bad_class = sorted(bad_values)[0] if bad_values else "1"
        good_class = sorted(good_values)[0] if good_values else "0"
        class_mapping = build_class_mapping(good_class, bad_class)

        features_list, source_variables = resolve_features(woe_cols, sel_def)
        coefficients: dict[str, float] = {
            col: round(float(coef), COEF_ROUND) for col, coef in zip(features_list, lr.coef_[0], strict=False)
        }

        max_iter = int(params.get("max_iter", 1000))
        fail_on_non_convergence = bool(params.get("fail_on_non_convergence", True))
        has_sklearn_warning = any(issubclass(w.category, ConvergenceWarning) for w in fit_warnings)
        converged = not has_sklearn_warning and bool(lr.n_iter_[0] <= max_iter)
        warnings_list: list[dict[str, Any]] = []
        if not converged:
            msg = f"Logistic regression did not converge after {max_iter} iterations"
            if fail_on_non_convergence:
                raise ValueError(f"{msg} (set fail_on_non_convergence=False to warn only)")
            warnings_list.append({
                "code": "CONVERGENCE_FAILURE",
                "message": msg,
            })
        training_params: dict[str, Any] = {}
        for k, v in lr_params.items():
            if isinstance(v, np.bool_):
                training_params[k] = bool(v)
            elif isinstance(v, np.integer):
                training_params[k] = int(v)
            elif isinstance(v, np.floating):
                training_params[k] = float(v)
            else:
                training_params[k] = v

        prob_col_idx = 1
        for idx, cls_label in enumerate(lr.classes_):
            if str(cls_label) == str(bad_class):
                prob_col_idx = idx
                break

        feature_order_hash = json_logical_hash(
            {"features": features_list}
        )

        model = {
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "model_family": "logistic_regression",
            "target_column": target_column,
            "source_variables": source_variables,
            "class_mapping": class_mapping,
            "bad_class_label": str(bad_class),
            "target_event_value": str(bad_class),
            "probability_column_index": prob_col_idx,
            "feature_contract": {
                "features": features_list,
                "transformation_strategy": "woe",
                "order_hash": feature_order_hash,
                "missing_policy": "error",
                "unknown_category_policy": "error",
            },
            "feature_order_hash": feature_order_hash,
            "model_payload": {
                "intercept": round(float(lr.intercept_[0]), COEF_ROUND),
                "coefficients": coefficients,
            },
            "training": {
                "row_count": X.shape[0],
                "converged": converged,
                "iterations": int(lr.n_iter_[0]),
                "params": training_params,
            },
            "warnings": warnings_list,
        }

        context.outputs.publish_json(
            role="model",
            kind=EvidenceKind.MODEL_ARTIFACT,  # type: ignore[arg-type]
            payload=model,
            metadata={
                "feature_count": len(features_list),
                "target_column": target_column,
                "schema_version": SCHEMA_MODEL_ARTIFACT,
            },
        )
        context.outputs.add_metric("feature_count", len(features_list))
        context.outputs.add_metric("converged", converged)
        return context.outputs.build_result()  # type: ignore[no-any-return]

    def _run_execution_context(self, context: ExecutionContext) -> NodeOutput:
        import numpy as np
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import LogisticRegression as SkLearnLR

        store = context.store
        params = context.validated_params
        reader = ArtifactEvidenceReader(store)
        train_artifact = context.require_train_artifact("LogisticRegressionNode")

        meta = context.target_metadata()
        from cardre.modeling.target import TargetSpec
        target_spec = TargetSpec.from_metadata(meta)
        if target_spec is None:
            raise ValueError("Target metadata is required for logistic regression")

        sel_def = reader.find_optional(context.input_artifacts, EvidenceKind.SELECTION_DEFINITION)

        target_column = target_spec.target_column
        good_values = target_spec.good_values
        bad_values = target_spec.bad_values

        df = reader.read_dataframe(train_artifact)
        woe_cols = [c for c in df.columns if c.endswith("_woe")]
        if not woe_cols:
            raise ValueError("No WOE-transformed columns found in training data")

        X = df.select(woe_cols).to_numpy()

        if target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found in training data")

        target_spec.validate_good_bad_only(df)
        y_binary = target_spec.encode_binary_strict(df).to_list()
        n_bad = sum(y_binary)
        n_good = len(y_binary) - n_bad
        if n_bad == 0:
            raise ValueError(f"Logistic regression: no bad-class rows found (bad_values={sorted(bad_values)})")
        if n_good == 0:
            raise ValueError(f"Logistic regression: no good-class rows found (good_values={sorted(good_values)})")

        lr_params = build_lr_params(params)

        lr = SkLearnLR(**lr_params)
        with warnings.catch_warnings(record=True) as fit_warnings:
            warnings.simplefilter("always")
            lr.fit(X, y_binary)

        bad_class = sorted(bad_values)[0] if bad_values else "1"
        good_class = sorted(good_values)[0] if good_values else "0"
        class_mapping = build_class_mapping(good_class, bad_class)

        features_list, source_variables = resolve_features(woe_cols, sel_def)
        coefficients: dict[str, float] = {
            col: round(float(coef), COEF_ROUND) for col, coef in zip(features_list, lr.coef_[0], strict=False)
        }

        max_iter = int(params.get("max_iter", 1000))
        fail_on_non_convergence = bool(params.get("fail_on_non_convergence", True))
        has_sklearn_warning = any(issubclass(w.category, ConvergenceWarning) for w in fit_warnings)
        converged = not has_sklearn_warning and bool(lr.n_iter_[0] <= max_iter)
        warnings_list: list[dict[str, Any]] = []
        if not converged:
            msg = f"Logistic regression did not converge after {max_iter} iterations"
            if fail_on_non_convergence:
                raise ValueError(f"{msg} (set fail_on_non_convergence=False to warn only)")
            warnings_list.append({
                "code": "CONVERGENCE_FAILURE",
                "message": msg,
            })
        training_params: dict[str, Any] = {}
        for k, v in lr_params.items():
            if isinstance(v, np.bool_):
                training_params[k] = bool(v)
            elif isinstance(v, np.integer):
                training_params[k] = int(v)
            elif isinstance(v, np.floating):
                training_params[k] = float(v)
            else:
                training_params[k] = v

        prob_col_idx = 1
        for idx, cls_label in enumerate(lr.classes_):
            if str(cls_label) == str(bad_class):
                prob_col_idx = idx
                break

        feature_order_hash = json_logical_hash(
            {"features": features_list}
        )

        model = {
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "model_family": "logistic_regression",
            "target_column": target_column,
            "source_variables": source_variables,
            "class_mapping": class_mapping,
            "bad_class_label": str(bad_class),
            "target_event_value": str(bad_class),
            "probability_column_index": prob_col_idx,
            "feature_contract": {
                "features": features_list,
                "transformation_strategy": "woe",
                "order_hash": feature_order_hash,
                "missing_policy": "error",
                "unknown_category_policy": "error",
            },
            "feature_order_hash": feature_order_hash,
            "model_payload": {
                "intercept": round(float(lr.intercept_[0]), COEF_ROUND),
                "coefficients": coefficients,
            },
            "training": {
                "row_count": X.shape[0],
                "converged": converged,
                "iterations": int(lr.n_iter_[0]),
                "params": training_params,
            },
            "warnings": warnings_list,
        }

        artifact = write_json_artifact(
            store, artifact_type="model", role="model",
            stem=f"logistic-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features_list),
                "target_column": target_column,
                "schema_version": SCHEMA_MODEL_ARTIFACT,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"feature_count": len(features_list), "converged": lr.n_iter_[0] < max_iter})


class ScoreScalingNode(NodeType):
    node_type = "cardre.score_scaling"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["model", "definition", "report"]
    output_roles: list[str] = ["scorecard"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Score Scaling",
            methods=[
                MethodOption(
                    id="score_scaling",
                    label="Score Scaling",
                    status="available",
                    description="Scale model log-odds into a credit scorecard.",
                    params=[
                        ParameterDefinition(
                            name="base_score",
                            label="Base Score",
                            kind="integer",
                            default=600,
                            help_text="Score assigned to the base odds.",
                            constraint=ParameterConstraint(min_value=0),
                        ),
                        ParameterDefinition(
                            name="base_odds",
                            label="Base Odds",
                            kind="string",
                            default="50:1",
                            help_text="Odds at the base score (e.g. '50:1' or a number).",
                        ),
                        ParameterDefinition(
                            name="points_to_double_odds",
                            label="Points to Double Odds",
                            kind="float",
                            default=20.0,
                            help_text="Number of points required to double the odds.",
                            constraint=ParameterConstraint(exclusive_min=0.0),
                        ),
                        ParameterDefinition(
                            name="higher_score_is_lower_risk",
                            label="Higher Score = Lower Risk",
                            kind="boolean",
                            default=True,
                            help_text="If True, higher scores indicate lower risk.",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        try:
            base_odds_val = parse_base_odds(params.get("base_odds", 50.0))
            if base_odds_val <= 0:
                errors.append("base_odds must be positive")
        except ValueError:
            errors.append("base_odds must be a number or 'N:M' odds ratio string")
        pdo = params.get("points_to_double_odds", 20)
        try:
            if float(pdo) <= 0:
                errors.append("points_to_double_odds must be positive")
        except (ValueError, TypeError):
            errors.append("points_to_double_odds must be a number")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params
        reader = ArtifactEvidenceReader(store)

        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
        if model_art is None:
            raise EvidenceNotFoundError(
                EvidenceKind.MODEL_ARTIFACT,
                candidate_artifact_ids=[a.artifact_id for a in context.input_artifacts],
            )
        model = reader.require_model(model_art, "ScoreScalingNode")

        # Detect calibration compatibility before building additive scorecard points.
        calibration = model.calibration
        if calibration:
            application_mode = calibration.get("application_mode", "")
            score_scaling_compatible = bool(calibration.get("score_scaling_compatible", False))
            if application_mode != "folded_linear_log_odds" or not score_scaling_compatible:
                raise ValueError(
                    "Score scaling requires calibration.application_mode="
                    "'folded_linear_log_odds'. Runtime probability calibration "
                    "(including isotonic and CV Platt ensembles) is not compatible "
                    "with additive scorecard points."
                )

        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)

        if not bin_def.variables:
            raise ValueError("Score scaling received an empty bin definition")

        base_score = float(params.get("base_score", 600))
        base_odds = parse_base_odds(params.get("base_odds", 50.0))
        pdo = float(params.get("points_to_double_odds", 20))
        higher_is_lower_risk = bool(params.get("higher_score_is_lower_risk", True))

        if base_odds <= 0:
            raise ValueError(f"base_odds must be positive, got {base_odds}")
        if pdo <= 0:
            raise ValueError(f"points_to_double_odds must be positive, got {pdo}")

        factor = pdo / math.log(2)
        offset = base_score - factor * math.log(base_odds)
        intercept = float(model.intercept)
        coefficients = model.coefficients_dict

        direction = -1.0 if higher_is_lower_risk else 1.0
        base_points = round(offset + direction * factor * intercept, POINTS_ROUND)

        attributes: list[dict[str, Any]] = []
        all_woe_map = woe_table.mapping

        for var_def_obj in bin_def.variables:
            variable = var_def_obj.variable
            woe_key = f"{variable}_woe"
            if woe_key not in coefficients:
                continue
            coef = float(coefficients[woe_key])

            for bin_entry in var_def_obj.bins:
                woe_val = all_woe_map.get(variable, {}).get(bin_entry["bin_id"])
                if woe_val is None:
                    raise ValueError(
                        f"Score scaling: missing WOE value for variable {variable!r} bin {bin_entry['bin_id']!r}"
                    )
                attributes.append(
                    build_scorecard_attribute(variable, bin_entry, woe_val, coef, factor, direction)
                )

        scorecard = {
            "base_score": base_score,
            "base_odds": base_odds,
            "points_to_double_odds": pdo,
            "factor": round(factor, WOE_ROUND),
            "offset": round(offset, WOE_ROUND),
            "score_direction": "higher_is_lower_risk" if higher_is_lower_risk else "higher_is_better",
            "intercept": intercept,
            "base_points": base_points,
            "attributes": attributes,
            "target_column": model.target_column,
        }

        scorecard["schema_version"] = SCHEMA_SCORE_SCALING
        artifact = write_json_artifact(
            store, artifact_type="scorecard", role="scorecard",
            stem=f"scorecard-{context.step_spec.step_id}",
            payload=scorecard,
            metadata={
                "base_score": base_score,
                "attribute_count": len(attributes),
                "schema_version": SCHEMA_SCORE_SCALING,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"attribute_count": len(attributes)})


class BuildSummaryReportNode(NodeType):
    node_type = "cardre.build_summary_report"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["scorecard", "model", "report"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        reader = ArtifactEvidenceReader(store)

        scorecard_art = next((a for a in context.input_artifacts if a.role == "scorecard"), None)
        if scorecard_art is None:
            raise ValueError("Build summary requires a scorecard artifact")
        scorecard = reader.read_optional(scorecard_art.artifact_id, EvidenceKind.SCORE_SCALING)
        if scorecard is None:
            raise ValueError(f"Build summary requires scorecard artifact {scorecard_art.artifact_id!r} to be readable as SCORE_SCALING evidence")

        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
        if model_art is None:
            raise ValueError("Build summary requires a model artifact")
        model = reader.require_model(model_art, "BuildSummaryNode")

        model_features = model.features
        model_intercept = model.intercept
        model_coeff_count = len(model.coefficients_dict)
        model_converged = model.training.converged or False
        model_row_count = model.training.row_count or 0
        model_warnings = list(model.warnings)
        model_target = model.target_column

        woe_summaries: list[dict[str, Any]] = []
        iv_lf = reader.find_optional(context.input_artifacts, EvidenceKind.IV_TABLE)
        if iv_lf is not None:
            iv_df = iv_lf.dataframe.collect()
            woe_summaries.append({
                "artifact_id": iv_lf.source_artifact_id,
                "type": "iv_ranking",
                "row_count": iv_df.height,
                "columns": list(iv_df.columns),
            })
        woe_table = reader.find_optional(context.input_artifacts, EvidenceKind.WOE_TABLE)
        if woe_table is not None and woe_table.dataframe is not None:
            woe_summaries.append({
                "artifact_id": woe_table.source_artifact_id,
                "type": "woe_table",
                "row_count": woe_table.dataframe.collect().height,
                "columns": list(woe_table.columns),
            })

        scorecard_base_odds = scorecard.base_odds

        report = {
            "model_summary": {
                "target_column": model_target,
                "features": model_features,
                "intercept": model_intercept,
                "coefficient_count": model_coeff_count,
                "converged": model_converged,
                "row_count": model_row_count,
            },
            "scorecard_summary": {
                "base_score": scorecard.base_score,
                "base_odds": scorecard_base_odds,
                "points_to_double_odds": scorecard.points_to_double_odds,
                "attribute_count": len(scorecard.attributes),
                "score_direction": scorecard.score_direction,
            },
            "woe_iv_references": woe_summaries,
            "warnings": model_warnings,
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"build-summary-{context.step_spec.step_id}",
            payload=report,
            metadata={},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"feature_count": len(model_features)})


class DummyFitNode(NodeType):
    node_type = "cardre.dummy_fit"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        input_artifact = context.input_artifacts[0]
        params = context.validated_params

        df = reader.read_dataframe(input_artifact)
        dummy_def = {
            "model_type": "dummy",
            "version": self.version,
            "params": params,
            "input_columns": list(df.columns),
            "row_count": df.height,
        }

        artifact = write_json_artifact(
            store,
            artifact_type="definition",
            role="definition",
            stem=f"dummy-fit-{context.step_spec.step_id}",
            payload=dummy_def,
            metadata={"source_artifact_id": input_artifact.artifact_id},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height})


class NoopNode(NodeType):
    node_type = "cardre.noop"
    version = "1"
    category = "transform"
    input_roles: list[str] = [
        "input",
        "train",
        "test",
        "oot",
        "definition",
        "report",
        "model",
        "scorecard",
        "manifest",
    ]
    output_roles: list[str] = []

    def run(self, context: ExecutionContext) -> NodeOutput:
        return NodeOutput(artifacts=[], metrics={})
