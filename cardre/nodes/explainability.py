"""Explainability and limitation evidence nodes.

Phase 5 adds model_explainability and model_limitations nodes to make
challenger models governable. Every model family must produce an
explainability report before it is champion-eligible.
"""

from __future__ import annotations

from typing import Any

import joblib
from polars.exceptions import ComputeError

from cardre.domain.evidence.kinds import EvidenceKind, RoleKind
from cardre.domain.evidence.schemas import SCHEMA_EXPLAINABILITY_REPORT
from cardre.nodes._model_artifacts import load_estimator
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    InputCollection,
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

EXPLAINABILITY_LEVELS = {
    "native_scorecard",
    "native_interpretable",
    "native_semi_transparent",
    "post_hoc_only",
    "none",
}

CHAMPION_ELIGIBILITY = {
    "native_scorecard": "fully_eligible",
    "native_interpretable": "eligible_with_rule_report",
    "native_semi_transparent": "eligible_with_limitation_evidence",
    "post_hoc_only": "requires_explicit_limitation_acceptance",
    "none": "not_champion_eligible",
}


def _require_model(context: NodeContext, node_type: str) -> Any:
    model_art = context.inputs.require("model", node_type)
    model = context.inputs.read(model_art, EvidenceKind.MODEL_ARTIFACT)
    if not model.model_family:
        raise ValueError(f"{node_type} requires a readable model artifact")
    return model


def _load_estimator(inputs: InputCollection, estimator_ref: dict[str, Any]) -> Any | None:
    """Load the estimator a model references through the shared deep module.

    Verification (hash + ``creating_run_id`` provenance) is mandatory and
    centralized (see ADR-0016).
    """
    return load_estimator(inputs, estimator_ref, node_type="model_explainability")


class ModelExplainabilityNode(NodeType):
    """Produce an explainability report for a fitted model.

    Reads the model artifact and emits a structured explainability
    report with coefficients, feature importance, tree rules, or
    permutation importance depending on model family.

    This node does not require the model to be applied first.
    It reads the model artifact directly.
    """

    node_type = "cardre.model_explainability"
    version = "1"
    category = "report"
    optional_dependencies: list[str] = ["explain"]

    __definition__ = NodeDefinition(
        node_type="cardre.model_explainability",
        version="1",
        category="report",
        description="Produce explainability evidence for a fitted model",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,)),
                ArtifactRoleSpec("estimator", required=False, media_types=("application/octet-stream",)),
                ArtifactRoleSpec("train", required=False, kinds=(RoleKind.DATASET,)),
                ArtifactRoleSpec("test", required=False, kinds=(RoleKind.DATASET,)),
                ArtifactRoleSpec("oot", required=False, kinds=(RoleKind.DATASET,)),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(ArtifactRoleSpec("report", kinds=(EvidenceKind.EXPLAINABILITY_REPORT,), media_types=("application/json",), schema_versions=(SCHEMA_EXPLAINABILITY_REPORT,)),),
        ),
    )

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Model Explainability",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Produce explainability report for a fitted model.",
                    params=[
                        ParameterDefinition(
                            name="include_permutation_importance",
                            label="Include Permutation Importance",
                            kind="boolean",
                            default=False,
                            help_text="Whether to compute permutation feature importance.",
                        ),
                        ParameterDefinition(
                            name="permutation_data_role",
                            label="Permutation Data Role",
                            kind="string",
                            default="train",
                            constraint=ParameterConstraint(
                                enum_values=["train", "test", "oot"],
                            ),
                            help_text="Which data role to use for permutation importance computation.",
                        ),
                        ParameterDefinition(
                            name="random_seeds",
                            label="Random Seeds",
                            kind="list",
                            default=None,
                            help_text="List of random seeds for stability analysis (null to skip).",
                        ),
                        ParameterDefinition(
                            name="include_pdp",
                            label="Include Partial Dependence",
                            kind="boolean",
                            default=False,
                            help_text="Whether to compute partial dependence plots.",
                        ),
                        ParameterDefinition(
                            name="include_shap",
                            label="Include SHAP",
                            kind="boolean",
                            default=False,
                            help_text="Whether to compute SHAP explanations.",
                        ),
                    ],
                ),
            ],
            default_method="default",
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        include_permutation = params.get("include_permutation_importance", False)
        if not isinstance(include_permutation, bool):
            errors.append("include_permutation_importance must be a boolean")
        data_role = params.get("permutation_data_role", "train")
        if data_role not in ("train", "test", "oot"):
            errors.append("permutation_data_role must be one of 'train', 'test', 'oot'")
        random_seeds = params.get("random_seeds")
        if random_seeds is not None:
            if not isinstance(random_seeds, list) or not all(isinstance(s, int) for s in random_seeds):
                errors.append("random_seeds must be a list of integers or null")
        include_pdp = params.get("include_pdp", False)
        if not isinstance(include_pdp, bool):
            errors.append("include_pdp must be a boolean")
        include_shap = params.get("include_shap", False)
        if not isinstance(include_shap, bool):
            errors.append("include_shap must be a boolean")
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        include_permutation = params.get("include_permutation_importance", False)
        permutation_data_role = params.get("permutation_data_role", "train")
        random_seeds = params.get("random_seeds", None)
        include_pdp = params.get("include_pdp", False)
        include_shap = params.get("include_shap", False)

        model_typed = _require_model(context, self.node_type)
        model_family = model_typed.model_family
        features = model_typed.features
        model = model_typed.to_dict()
        interpretability = model.get("interpretability", {})
        explanation_level = interpretability.get("explanation_level", "none")

        report: dict[str, Any] = {
            "model_family": model_family,
            "explanation_level": explanation_level,
            "champion_eligibility": CHAMPION_ELIGIBILITY.get(explanation_level, "not_champion_eligible"),
            "features": features,
            "feature_count": len(features),
        }

        # Native explanations by model family
        from cardre.modeling.families import get as get_family_spec
        family_spec = get_family_spec(model_family)

        if family_spec is not None and family_spec.native_explanation_type == "coefficients":
            if model_typed is not None:
                report["coefficients"] = model_typed.coefficients_dict
                report["intercept"] = model_typed.intercept
            else:
                report["coefficients"] = model.get("coefficients", {})
                report["intercept"] = model.get("intercept", 0.0)
            report["explanation_type"] = "coefficients"
            report["explanation_summary"] = (
                f"Logistic regression with {len(features)} WOE features. "
                f"Coefficients are directly interpretable as log-odds contributions."
            )

        elif family_spec is not None and family_spec.native_explanation_type == "tree_rules":
            payload = model.get("model_payload", {})
            report["tree_rules"] = payload.get("tree_rules", [])
            report["tree_depth"] = payload.get("tree_depth", 0)
            report["leaf_count"] = payload.get("leaf_count", 0)
            report["feature_importance"] = payload.get("feature_importance", {})
            report["explanation_type"] = "tree_rules"
            report["explanation_summary"] = (
                f"Decision tree with depth {report['tree_depth']} and "
                f"{report['leaf_count']} leaves. Rules are human-readable."
            )

        elif family_spec is not None and family_spec.native_explanation_type == "feature_importance":
            payload = model.get("model_payload", {})
            report["feature_importance"] = payload.get("feature_importance", {})
            report["estimator_count"] = payload.get("estimator_count", 0)
            report["explanation_type"] = "feature_importance"
            report["explanation_summary"] = (
                f"{model_family.replace('_', ' ').title()} with "
                f"{report['estimator_count']} estimators. "
                f"Feature importance is available but individual predictions "
                f"are not fully decomposable."
            )

        else:
            report["explanation_type"] = "none"
            report["explanation_summary"] = (
                f"No native explanation available for model family {model_family!r}."
            )

        # Permutation importance (optional, configurable data role)
        if include_permutation:
            data_art = context.inputs.first(permutation_data_role)
            if data_art is not None and features:
                perm_result = self._compute_permutation_importance(
                    context.inputs, model, data_art, features,
                    data_role=permutation_data_role,
                )
                if perm_result is not None:
                    report["permutation_importance"] = perm_result
                if random_seeds and perm_result is not None and perm_result.get("method") == "permutation_importance":
                    stability = self._compute_stability_analysis(
                        context.inputs, model, data_art, features, random_seeds,
                        data_role=permutation_data_role,
                    )
                    if stability:
                        report["stability_analysis"] = stability

        # Partial dependence (optional)
        if include_pdp:
            pdp_data_art = context.inputs.first("train")
            if pdp_data_art is not None and features:
                pdp_result = self._compute_pdp(context.inputs, model, pdp_data_art, features)
                if pdp_result:
                    report["partial_dependence"] = pdp_result

        # SHAP explanations (optional)
        if include_shap:
            shap_data_art = context.inputs.first("train")
            if shap_data_art is not None and features:
                shap_result = self._compute_shap(context.inputs, model, shap_data_art, features)
                if shap_result:
                    report["shap"] = shap_result

        # Limitations from model artifact
        report["limitations"] = interpretability.get("limitations", [])
        report["native_importance_available"] = interpretability.get("native_importance_available", False)
        report["global_importance_fields"] = interpretability.get("global_importance_fields", [])

        # Champion eligibility detail
        report["champion_gate"] = self._champion_gate(explanation_level, report)

        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.EXPLAINABILITY_REPORT,
            payload=report,
            metadata={
                "model_family": model_family,
                "explanation_level": explanation_level,
                "schema_version": SCHEMA_EXPLAINABILITY_REPORT,
            },
        )
        context.outputs.add_metric("model_family", model_family)
        return context.outputs.build_result()

    def _compute_permutation_importance(
        self, inputs: InputCollection, model: dict[str, Any], data_art: Any, features: list[str],
        data_role: str = "train", random_state: int = 42,
    ) -> dict[str, Any] | None:
        """Compute permutation importance on specified data."""
        try:
            from sklearn.inspection import permutation_importance as sklearn_permutation_importance
        except ImportError:
            return None

        model_family = model.get("model_family", "")
        estimator_ref = model.get("estimator_reference", {})

        if model_family == "logistic_regression":
            coefs = model.get("coefficients", {})
            return {
                "method": "coefficient_magnitude",
                "importance": {f: round(abs(coefs.get(f, 0.0)), 6) for f in features},
                "data_role": data_role,
            }

        if not estimator_ref.get("artifact_id"):
            return None

        try:
            estimator = _load_estimator(inputs, estimator_ref)
            if estimator is None:
                return None
            df = inputs.read_dataframe(data_art)
            target_col = model.get("target_column", "")
            if target_col not in df.columns:
                return None

            from cardre.modeling.target import TargetSpec
            bad_values_set = set(model.get("bad_class_label", "").split()) or {"bad"}
            target_spec = TargetSpec(
                target_column=target_col,
                good_values=frozenset(),
                bad_values=frozenset(bad_values_set),
            )
            y_bin = target_spec.encode_binary(df).to_numpy()

            X = df.select(features).to_numpy()
            result = sklearn_permutation_importance(
                estimator, X, y_bin, n_repeats=5, random_state=random_state, n_jobs=-1,
            )
            return {
                "method": "permutation_importance",
                "n_repeats": 5,
                "data_role": data_role,
                "importance_mean": {
                    f: round(float(result.importances_mean[i]), 6)
                    for i, f in enumerate(features)
                },
                "importance_std": {
                    f: round(float(result.importances_std[i]), 6)
                    for i, f in enumerate(features)
                },
            }
        except (ImportError, FileNotFoundError, joblib.InvalidJoblibException):
            return None

    def _compute_stability_analysis(
        self, inputs: InputCollection, model: dict[str, Any], data_art: Any, features: list[str],
        random_seeds: list[int], data_role: str = "train",
    ) -> dict[str, Any] | None:
        try:
            import numpy as np
            from scipy.stats import spearmanr
        except ImportError:
            return None

        seed_importances: dict[str, list[str]] = {}
        for seed in random_seeds:
            result = self._compute_permutation_importance(
                inputs, model, data_art, features,
                data_role=data_role, random_state=seed,
            )
            if result is None or result.get("method") != "permutation_importance":
                return None
            imp = result.get("importance_mean", {})
            sorted_feats = sorted(imp, key=lambda f: imp[f], reverse=True)
            seed_importances[str(seed)] = sorted_feats

        seeds_list = list(seed_importances.keys())
        correlations: list[float] = []
        for i in range(len(seeds_list)):
            for j in range(i + 1, len(seeds_list)):
                rank_i = {f: idx for idx, f in enumerate(seed_importances[seeds_list[i]])}
                rank_j = {f: idx for idx, f in enumerate(seed_importances[seeds_list[j]])}
                common = [f for f in features if f in rank_i and f in rank_j]
                if len(common) < 2:
                    continue
                r_i = [rank_i[f] for f in common]
                r_j = [rank_j[f] for f in common]
                corr, _ = spearmanr(r_i, r_j)
                correlations.append(float(corr))

        if not correlations:
            return None

        mean_corr = float(np.mean(correlations))
        return {
            "random_seeds": random_seeds,
            "mean_spearman_rank_correlation": round(mean_corr, 4),
            "top_features_changed": mean_corr < 0.85,
            "per_seed_importance": seed_importances,
        }

    def _compute_pdp(
        self, inputs: InputCollection, model: dict[str, Any], data_art: Any, features: list[str],
    ) -> list[dict[str, Any]] | None:
        try:
            from sklearn.inspection import partial_dependence
        except ImportError:
            return None

        estimator_ref = model.get("estimator_reference", {})
        if not estimator_ref.get("artifact_id"):
            return None

        try:
            estimator = _load_estimator(inputs, estimator_ref)
            if estimator is None:
                return None
            df = inputs.read_dataframe(data_art)
            X = df.select(features).to_numpy()

            feature_importance = model.get("model_payload", {}).get("feature_importance", {})
            if feature_importance:
                sorted_feats = sorted(feature_importance, key=feature_importance.get, reverse=True)
                top_features = sorted_feats[:3]
            else:
                top_features = features[:3]

            pdp_results: list[dict[str, Any]] = []
            for feat in top_features:
                if feat not in features:
                    continue
                feat_idx = features.index(feat)
                result = partial_dependence(
                    estimator, X, [feat_idx], kind="average",
                )
                pdp_results.append({
                    "feature": feat,
                    "feature_idx": feat_idx,
                    "grid_values": result["grid_values"][0].tolist(),
                    "average_predictions": result["average"][0].tolist(),
                })
            return pdp_results if pdp_results else None
        except (ImportError, FileNotFoundError, joblib.InvalidJoblibException):
            return None

    def _compute_shap(
        self, inputs: InputCollection, model: dict[str, Any], data_art: Any, features: list[str],
    ) -> dict[str, Any] | None:
        try:
            import shap
        except ImportError:
            return None

        estimator_ref = model.get("estimator_reference", {})
        if not estimator_ref.get("artifact_id"):
            return None

        try:
            estimator = _load_estimator(inputs, estimator_ref)
            if estimator is None:
                return None
            import numpy as np

            model_family = model.get("model_family", "")

            from cardre.modeling.families import get as get_family_spec
            family_spec = get_family_spec(model_family)

            df = inputs.read_dataframe(data_art)
            X = df.select(features).to_numpy()

            if family_spec is not None and family_spec.shap_explainer_kind == "TreeExplainer":
                explainer = shap.TreeExplainer(estimator)
                explainer_type = "TreeExplainer"
            elif family_spec is not None and family_spec.shap_explainer_kind == "LinearExplainer":
                explainer = shap.LinearExplainer(estimator, X)
                explainer_type = "LinearExplainer"
            else:
                return None

            shap_values = explainer.shap_values(X)
            shap_values_np = np.array(shap_values) if isinstance(shap_values, list) else shap_values
            if shap_values_np.ndim == 3:
                shap_values_np = shap_values_np[:, 1, :]
            mean_abs_shap = np.abs(shap_values_np).mean(axis=0)

            return {
                "feature_importance": {
                    f: round(float(mean_abs_shap[i]), 6)
                    for i, f in enumerate(features)
                },
                "explainer_type": explainer_type,
            }
        except (ImportError, FileNotFoundError, joblib.InvalidJoblibException):
            return None

    def _champion_gate(self, explanation_level: str, report: dict[str, Any]) -> dict[str, str]:
        """Determine champion gate status from explanation level."""
        if explanation_level == "native_scorecard":
            return {
                "status": "pass",
                "message": "Fully interpretable scorecard. Champion-eligible.",
            }
        elif explanation_level == "native_interpretable":
            return {
                "status": "pass",
                "message": "Native interpretable model with rule export. Champion-eligible.",
            }
        elif explanation_level == "native_semi_transparent":
            return {
                "status": "warn",
                "message": (
                    "Semi-transparent model. Feature importance is available but "
                    "individual predictions are not fully decomposable. "
                    "Requires accepted limitation evidence for champion promotion."
                ),
            }
        elif explanation_level == "post_hoc_only":
            return {
                "status": "block",
                "message": (
                    "No native explanation. Requires explicit limitation acceptance "
                    "and post-hoc explanation evidence."
                ),
            }
        else:
            return {
                "status": "block",
                "message": "No explanation artifact. Not champion-eligible.",
            }


class ModelLimitationsNode(NodeType):
    """Produce a structured limitations report for a fitted model.

    Records interpretability limits, data quality issues, dimensionality
    concerns, optional dependency status, and deployment constraints.
    """

    node_type = "cardre.model_limitations"
    version = "1"
    category = "report"

    __definition__ = NodeDefinition(
        node_type="cardre.model_limitations",
        version="1",
        category="report",
        description="Produce limitations evidence for a fitted model",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,)),
                ArtifactRoleSpec("estimator", required=False, media_types=("application/octet-stream",)),
                ArtifactRoleSpec("train", required=False, kinds=(RoleKind.DATASET,)),
                ArtifactRoleSpec("definition", required=False, kinds=(RoleKind.DEFINITION,)),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(ArtifactRoleSpec("report", kinds=(EvidenceKind.EXPLAINABILITY_REPORT,), media_types=("application/json",), schema_versions=(SCHEMA_EXPLAINABILITY_REPORT,)),),
        ),
    )

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Model Limitations",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Produce structured limitations report for a fitted model.",
                    params=[
                        ParameterDefinition(
                            name="accepted_limitations",
                            label="Accepted Limitations",
                            kind="list",
                            default=[],
                            help_text="List of limitation codes the user has explicitly accepted.",
                        ),
                    ],
                ),
            ],
            default_method="default",
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        accepted = params.get("accepted_limitations", [])
        if not isinstance(accepted, list):
            errors.append("accepted_limitations must be a list")
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        accepted_codes = set(params.get("accepted_limitations", []))

        model_typed = _require_model(context, self.node_type)
        model_family = model_typed.model_family
        features = model_typed.features
        model = model_typed.to_dict()
        interpretability = model.get("interpretability", {})
        explanation_level = interpretability.get("explanation_level", "none")
        model_limitations = interpretability.get("limitations", [])
        training = model.get("training", {})
        warnings_list = model.get("warnings", [])

        # Data quality checks
        data_issues = self._check_data_quality(context.inputs, features)

        # Dimensionality assessment
        dimensionality = self._assess_dimensionality(features, training.get("row_count", 0))

        # Build structured limitations
        limitations: list[dict[str, Any]] = []

        # Interpretability limitation
        if explanation_level in ("native_semi_transparent", "post_hoc_only", "none"):
            limitations.append({
                "code": "INTERPRETABILITY_LIMITED",
                "severity": "warn" if explanation_level == "native_semi_transparent" else "block",
                "category": "interpretability",
                "message": (
                    f"Model family {model_family!r} has {explanation_level.replace('_', ' ')} "
                    f"interpretability. Individual predictions are not fully decomposable."
                ),
                "accepted": "INTERPRETABILITY_LIMITED" in accepted_codes,
            })

        # Model-specific limitations from the model artifact
        for lim_text in model_limitations:
            code = self._text_to_code(lim_text)
            limitations.append({
                "code": code,
                "severity": "warn",
                "category": "model_inherent",
                "message": lim_text,
                "accepted": code in accepted_codes,
            })

        # Data quality limitations
        for issue in data_issues:
            limitations.append({
                "code": issue["code"],
                "severity": issue.get("severity", "warn"),
                "category": "data_quality",
                "message": issue["message"],
                "accepted": issue["code"] in accepted_codes,
            })

        # Dimensionality limitation
        if dimensionality["severity"] != "pass":
            limitations.append({
                "code": dimensionality["code"],
                "severity": dimensionality["severity"],
                "category": "dimensionality",
                "message": dimensionality["message"],
                "accepted": dimensionality["code"] in accepted_codes,
            })

        # Training warnings
        for w in warnings_list:
            code = w.get("code", "UNKNOWN_WARNING")
            limitations.append({
                "code": code,
                "severity": "warn",
                "category": "training_warning",
                "message": w.get("message", ""),
                "accepted": code in accepted_codes,
            })

        # Compute overall gate status
        statuses = [lim["severity"] for lim in limitations]
        if "block" in statuses:
            overall_status = "block"
        elif "warn" in statuses:
            overall_status = "warn"
        else:
            overall_status = "pass"

        unaccepted_blocks = [
            lim for lim in limitations
            if lim["severity"] == "block" and not lim["accepted"]
        ]
        unaccepted_warns = [
            lim for lim in limitations
            if lim["severity"] == "warn" and not lim["accepted"]
        ]

        report: dict[str, Any] = {
            "schema_version": SCHEMA_EXPLAINABILITY_REPORT,
            "model_family": model_family,
            "explanation_level": explanation_level,
            "overall_status": overall_status,
            "limitations": limitations,
            "accepted_limitations": sorted(accepted_codes),
            "unaccepted_blocks": len(unaccepted_blocks),
            "unaccepted_warnings": len(unaccepted_warns),
            "champion_eligible": len(unaccepted_blocks) == 0,
        }

        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.EXPLAINABILITY_REPORT,
            payload=report,
            metadata={
                "model_family": model_family,
                "overall_status": overall_status,
                "schema_version": SCHEMA_EXPLAINABILITY_REPORT,
            },
        )
        context.outputs.add_metric("overall_status", overall_status)
        return context.outputs.build_result()

    def _check_data_quality(
        self, inputs: InputCollection, features: list[str],
    ) -> list[dict[str, Any]]:
        """Check training data quality for the model's features."""
        issues: list[dict[str, Any]] = []
        train_art = inputs.first("train")
        if train_art is None:
            return issues

        try:
            df = inputs.read_dataframe(train_art)
        except (OSError, ComputeError):
            return issues

        n_rows = df.height
        null_counts = {c: int(df[c].null_count()) for c in features if c in df.columns}
        for feat in features:
            if feat not in df.columns:
                issues.append({
                    "code": "MISSING_FEATURE_COLUMN",
                    "severity": "block",
                    "message": f"Feature {feat!r} not found in training data",
                })
                continue

            null_count = null_counts.get(feat, 0)
            null_pct = null_count / n_rows if n_rows > 0 else 0
            if null_pct > 0.5:
                issues.append({
                    "code": "HIGH_NULL_FEATURE",
                    "severity": "warn",
                    "message": f"Feature {feat!r} has {null_pct:.1%} null values",
                })

        return issues

    def _assess_dimensionality(self, features: list[str], n_rows: int) -> dict[str, Any]:
        """Assess feature-to-sample ratio."""
        n_features = len(features)
        if n_rows == 0:
            return {"code": "NO_TRAINING_DATA", "severity": "block", "message": "No training data"}

        ratio = n_features / n_rows
        if ratio > 0.5:
            return {
                "code": "HIGH_DIMENSIONALITY",
                "severity": "warn",
                "message": (
                    f"Feature-to-sample ratio is {ratio:.2f} "
                    f"({n_features} features / {n_rows} rows). "
                    f"May indicate overfitting risk."
                ),
            }
        return {"code": "DIMENSIONALITY_OK", "severity": "pass", "message": "Dimensionality within bounds"}

    def _text_to_code(self, text: str) -> str:
        """Convert a limitation text to a machine-readable code."""
        text_lower = text.lower()
        if "scorecard" in text_lower:
            return "NO_NATIVE_SCORECARD"
        if "depth" in text_lower or "leaf" in text_lower:
            return "TREE_COMPLEXITY"
        if "semi-transparent" in text_lower or "ensemble" in text_lower:
            return "SEMI_TRANSPARENT_MODEL"
        if "boosting" in text_lower:
            return "BOOSTING_INTERPRETABILITY"
        if "not human-readable" in text_lower:
            return "NON_HUMAN_READABLE"
        return "GENERIC_LIMITATION"
