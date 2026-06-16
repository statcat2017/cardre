"""Explainability and limitation evidence nodes.

Phase 5 adds model_explainability and model_limitations nodes to make
challenger models governable. Every model family must produce an
explainability report before it is champion-eligible.
"""

from __future__ import annotations

import json
from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
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
    input_roles: list[str] = ["model", "train"]
    output_roles: list[str] = ["report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        include_permutation = params.get("include_permutation_importance", False)
        if not isinstance(include_permutation, bool):
            errors.append("include_permutation_importance must be a boolean")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        include_permutation = params.get("include_permutation_importance", False)

        reader = ArtifactEvidenceReader(store)
        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
        if model_art is None:
            raise ValueError("model_explainability requires a model artifact")

        model = json.loads(store.artifact_path(model_art).read_text())
        model_typed = reader.read_optional(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)
        if model_typed is not None:
            model_family = model_typed.model_family
            features = model_typed.features
        else:
            model_family = model.get("model_family", "unknown")
            features = model.get("features", [])
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
        if model_family == "logistic_regression":
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

        elif model_family == "decision_tree":
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

        elif model_family in ("random_forest", "gbdt"):
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

        # Permutation importance (optional, requires train data)
        if include_permutation:
            train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
            if train_art is not None and features:
                perm_result = self._compute_permutation_importance(
                    store, model, train_art, features,
                )
                if perm_result is not None:
                    report["permutation_importance"] = perm_result

        # Limitations from model artifact
        report["limitations"] = interpretability.get("limitations", [])
        report["native_importance_available"] = interpretability.get("native_importance_available", False)
        report["global_importance_fields"] = interpretability.get("global_importance_fields", [])

        # Champion eligibility detail
        report["champion_gate"] = self._champion_gate(explanation_level, report)

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"explainability-{context.step_spec.step_id}",
            payload=report,
            metadata={"model_family": model_family, "explanation_level": explanation_level},
        )
        return NodeOutput(artifacts=[art], metrics={"model_family": model_family})

    def _compute_permutation_importance(
        self, store, model: dict, train_art, features: list[str],
    ) -> dict | None:
        """Compute permutation importance on training data."""
        try:
            from sklearn.inspection import permutation_importance as sklearn_permutation_importance
            import numpy as np
        except ImportError:
            return None

        model_family = model.get("model_family", "")
        estimator_ref = model.get("estimator_reference", {})

        if model_family == "logistic_regression":
            # Use coefficient magnitudes as proxy
            coefs = model.get("coefficients", {})
            return {
                "method": "coefficient_magnitude",
                "importance": {f: round(abs(coefs.get(f, 0.0)), 6) for f in features},
            }

        if not estimator_ref.get("artifact_id"):
            return None

        try:
            from cardre.modeling.serialization import read_estimator_artifact
            estimator_art = store.get_artifact(estimator_ref["artifact_id"])
            if estimator_art is None:
                return None
            estimator_bytes = read_estimator_artifact(
                store, estimator_art,
                expected_logical_hash=estimator_ref.get("logical_hash"),
            )
            import io
            import joblib
            estimator = joblib.load(io.BytesIO(estimator_bytes))

            df = pl.read_parquet(store.artifact_path(train_art))
            target_col = model.get("target_column", "")
            if target_col not in df.columns:
                return None

            meta_art = None
            for a in [train_art]:
                try:
                    meta = json.loads(store.artifact_path(a).read_text())
                    if "target_column" in meta:
                        break
                except Exception:
                    pass

            y_raw = df[target_col].cast(pl.String).to_list()
            bad_values = set(model.get("bad_class_label", "").split()) or {"bad"}
            y_bin = [1 if str(v) in bad_values else 0 for v in y_raw]

            X = df.select(features).to_numpy()
            result = sklearn_permutation_importance(
                estimator, X, y_bin, n_repeats=5, random_state=42, n_jobs=-1,
            )
            return {
                "method": "permutation_importance",
                "n_repeats": 5,
                "importance_mean": {
                    f: round(float(result.importances_mean[i]), 6)
                    for i, f in enumerate(features)
                },
                "importance_std": {
                    f: round(float(result.importances_std[i]), 6)
                    for i, f in enumerate(features)
                },
            }
        except Exception:
            return None

    def _champion_gate(self, explanation_level: str, report: dict) -> dict:
        """Determine champion gate status from explanation level."""
        eligibility = CHAMPION_ELIGIBILITY.get(explanation_level, "not_champion_eligible")

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
    input_roles: list[str] = ["model", "train", "definition"]
    output_roles: list[str] = ["report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        accepted = params.get("accepted_limitations", [])
        if not isinstance(accepted, list):
            errors.append("accepted_limitations must be a list")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        accepted_codes = set(params.get("accepted_limitations", []))

        reader = ArtifactEvidenceReader(store)
        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)
        if model_art is None:
            raise ValueError("model_limitations requires a model artifact")

        model = json.loads(store.artifact_path(model_art).read_text())
        model_typed = reader.read_optional(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)
        if model_typed is not None:
            model_family = model_typed.model_family
            features = model_typed.features
        else:
            model_family = model.get("model_family", "unknown")
            features = model.get("features", [])
        interpretability = model.get("interpretability", {})
        explanation_level = interpretability.get("explanation_level", "none")
        model_limitations = interpretability.get("limitations", [])
        training = model.get("training", {})
        warnings_list = model.get("warnings", [])

        # Data quality checks
        data_issues = self._check_data_quality(store, context.input_artifacts, features)

        # Dimensionality assessment
        dimensionality = self._assess_dimensionality(features, training.get("row_count", 0))

        # Build structured limitations
        limitations: list[dict] = []

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
            "model_family": model_family,
            "explanation_level": explanation_level,
            "overall_status": overall_status,
            "limitations": limitations,
            "accepted_limitations": sorted(accepted_codes),
            "unaccepted_blocks": len(unaccepted_blocks),
            "unaccepted_warnings": len(unaccepted_warns),
            "champion_eligible": len(unaccepted_blocks) == 0,
        }

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"limitations-{context.step_spec.step_id}",
            payload=report,
            metadata={"model_family": model_family, "overall_status": overall_status},
        )
        return NodeOutput(artifacts=[art], metrics={"overall_status": overall_status})

    def _check_data_quality(
        self, store, input_artifacts, features: list[str],
    ) -> list[dict]:
        """Check training data quality for the model's features."""
        issues: list[dict] = []
        train_art = next((a for a in input_artifacts if a.role == "train"), None)
        if train_art is None:
            return issues

        try:
            df = pl.read_parquet(store.artifact_path(train_art))
        except Exception:
            return issues

        n_rows = df.height
        for feat in features:
            if feat not in df.columns:
                issues.append({
                    "code": "MISSING_FEATURE_COLUMN",
                    "severity": "block",
                    "message": f"Feature {feat!r} not found in training data",
                })
                continue

            null_count = df[feat].null_count()
            null_pct = null_count / n_rows if n_rows > 0 else 0
            if null_pct > 0.5:
                issues.append({
                    "code": "HIGH_NULL_FEATURE",
                    "severity": "warn",
                    "message": f"Feature {feat!r} has {null_pct:.1%} null values",
                })

        return issues

    def _assess_dimensionality(self, features: list[str], n_rows: int) -> dict:
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
