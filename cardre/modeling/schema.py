"""Generic model artifact schema — cardre.model_artifact.v1.

Defines the JSON contract that every approved model family must emit.
Logistic regression, decision tree, random forest, and GBDT all produce
artifacts conforming to this schema. Lightweight interpretable payloads
(coefficients, tree rules, feature importance) live inside the JSON;
binary estimator artifacts are referenced by artifact id and hash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MODEL_ARTIFACT_SCHEMA_VERSION = "cardre.model_artifact.v1"


@dataclass
class FeatureContract:
    """Describes the feature columns expected by the model at apply time."""

    features: list[str] = field(default_factory=list)
    transformation_strategy: str = "raw_numeric"
    order_hash: str = ""
    dtype_contract: dict[str, str] = field(default_factory=dict)
    missing_policy: str = "error"
    unknown_category_policy: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": list(self.features),
            "transformation_strategy": self.transformation_strategy,
            "order_hash": self.order_hash,
            "dtype_contract": dict(self.dtype_contract),
            "missing_policy": self.missing_policy,
            "unknown_category_policy": self.unknown_category_policy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureContract:
        return cls(
            features=list(data.get("features", [])),
            transformation_strategy=data.get("transformation_strategy", "raw_numeric"),
            order_hash=data.get("order_hash", ""),
            dtype_contract=dict(data.get("dtype_contract", {})),
            missing_policy=data.get("missing_policy", "error"),
            unknown_category_policy=data.get("unknown_category_policy", "error"),
        )


@dataclass
class PredictionContract:
    """Describes probability semantics and score direction."""

    probability_semantics: str = "p(bad)"
    score_direction: str = "higher_is_lower_risk"
    score_type: str = "log_odds_scaled"
    threshold_policy_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability_semantics": self.probability_semantics,
            "score_direction": self.score_direction,
            "score_type": self.score_type,
            "threshold_policy_refs": list(self.threshold_policy_refs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PredictionContract:
        return cls(
            probability_semantics=data.get("probability_semantics", "p(bad)"),
            score_direction=data.get("score_direction", "higher_is_lower_risk"),
            score_type=data.get("score_type", "log_odds_scaled"),
            threshold_policy_refs=list(data.get("threshold_policy_refs", [])),
        )


@dataclass
class TrainingMetadata:
    """Records training conditions for reproducibility."""

    row_count: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    random_seed: int | None = None
    package_versions: dict[str, str] = field(default_factory=dict)
    elapsed_seconds: float | None = None
    converged: bool | None = None
    iterations: int | None = None
    tuning_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"row_count": self.row_count}
        if self.params:
            result["params"] = dict(self.params)
        if self.random_seed is not None:
            result["random_seed"] = self.random_seed
        if self.package_versions:
            result["package_versions"] = dict(self.package_versions)
        if self.elapsed_seconds is not None:
            result["elapsed_seconds"] = self.elapsed_seconds
        if self.converged is not None:
            result["converged"] = self.converged
        if self.iterations is not None:
            result["iterations"] = self.iterations
        if self.tuning_status is not None:
            result["tuning_status"] = self.tuning_status
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrainingMetadata:
        return cls(
            row_count=data.get("row_count", 0),
            params=dict(data.get("params", {})),
            random_seed=data.get("random_seed"),
            package_versions=dict(data.get("package_versions", {})),
            elapsed_seconds=data.get("elapsed_seconds"),
            converged=data.get("converged"),
            iterations=data.get("iterations"),
            tuning_status=data.get("tuning_status"),
        )


@dataclass
class InterpretabilityMetadata:
    """Records native explainability type and limitations."""

    explanation_type: str = "none"
    explanation_level: str = "none"
    native_importance_available: bool = False
    limitations: list[str] = field(default_factory=list)
    global_importance_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "explanation_type": self.explanation_type,
            "explanation_level": self.explanation_level,
            "native_importance_available": self.native_importance_available,
            "limitations": list(self.limitations),
            "global_importance_fields": list(self.global_importance_fields),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterpretabilityMetadata:
        return cls(
            explanation_type=data.get("explanation_type", "none"),
            explanation_level=data.get("explanation_level", "none"),
            native_importance_available=data.get("native_importance_available", False),
            limitations=list(data.get("limitations", [])),
            global_importance_fields=list(data.get("global_importance_fields", [])),
        )


@dataclass
class EstimatorReference:
    """Reference to a binary estimator artifact in the project store."""

    artifact_id: str = ""
    logical_hash: str = ""
    physical_hash: str = ""
    estimator_format: str = "json_native"
    trusted_load_required: bool = False
    creating_run_id: str = ""
    creating_run_step_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "logical_hash": self.logical_hash,
            "physical_hash": self.physical_hash,
            "estimator_format": self.estimator_format,
            "trusted_load_required": self.trusted_load_required,
            "creating_run_id": self.creating_run_id,
            "creating_run_step_id": self.creating_run_step_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EstimatorReference:
        return cls(
            artifact_id=data.get("artifact_id", ""),
            logical_hash=data.get("logical_hash", ""),
            physical_hash=data.get("physical_hash", ""),
            estimator_format=data.get("estimator_format", "json_native"),
            trusted_load_required=data.get("trusted_load_required", False),
            creating_run_id=data.get("creating_run_id", ""),
            creating_run_step_id=data.get("creating_run_step_id", ""),
        )


@dataclass(frozen=True)
class ModelCoefficient:
    variable_name: str
    coefficient: float = 0.0
    standard_error: float | None = None
    p_value: float | None = None


@dataclass
class ModelArtifactV1:
    """Generic model artifact — cardre.model_artifact.v1.

    Every approved model family produces this structure. The model_payload
    field carries family-specific interpretable data (coefficients, tree
    rules, feature importance). Binary estimator references are kept
    separate via estimator_reference.
    """

    schema_version: str = MODEL_ARTIFACT_SCHEMA_VERSION
    model_family: str = "logistic_regression"
    input_artifact_id: str = ""
    training_role: str = "train"
    target_column: str = ""
    target_event_value: str = ""
    class_mapping: dict[str, Any] = field(default_factory=dict)
    probability_column_index: int = 1
    feature_contract: FeatureContract = field(default_factory=FeatureContract)
    feature_order_hash: str = ""
    feature_dtype_contract: dict[str, str] = field(default_factory=dict)
    preprocessing_artifact_ids: list[str] = field(default_factory=list)
    prediction_contract: PredictionContract = field(default_factory=PredictionContract)
    score_direction: str = "higher_is_lower_risk"
    calibration_artifact_id: str = ""
    calibration: dict[str, Any] = field(default_factory=dict)
    estimator_reference: EstimatorReference = field(default_factory=EstimatorReference)
    training: TrainingMetadata = field(default_factory=TrainingMetadata)
    model_payload: dict[str, Any] = field(default_factory=dict)
    interpretability: InterpretabilityMetadata = field(default_factory=InterpretabilityMetadata)
    source_variables: list[str] | None = None
    base_odds_text: str = "50:1"
    bad_class_label: str = ""
    feature_strategy: str = ""
    warnings: list[dict[str, Any]] = field(default_factory=list)
    source_artifact_id: str = ""

    @property
    def coefficients_dict(self) -> dict[str, float]:
        """Convenience: model_payload coefficients as a dict."""
        coeffs = self.model_payload.get("coefficients", {})
        if isinstance(coeffs, dict):
            return {k: float(v) for k, v in coeffs.items() if isinstance(v, (int, float))}
        return {}

    @property
    def intercept(self) -> float:
        """Model intercept from model_payload."""
        return float(self.model_payload.get("intercept", 0.0))

    @property
    def features(self) -> list[str]:
        """Feature names from feature_contract."""
        return list(self.feature_contract.features)

    @property
    def base_odds(self) -> float:
        """Base odds parsed from 'N:M' string to float."""
        raw = self.base_odds_text
        if isinstance(raw, str) and ":" in raw:
            parts = raw.split(":", 1)
            try:
                return float(parts[0]) / float(parts[1])
            except (ValueError, ZeroDivisionError):
                return 50.0
        return float(raw)

    @property
    def coefficients(self) -> list[ModelCoefficient]:
        return [
            ModelCoefficient(variable_name=name, coefficient=value)
            for name, value in self.coefficients_dict.items()
        ]

    @property
    def has_explicit_intercept(self) -> bool:
        return "intercept" in self.model_payload

    def to_model_dict(self) -> dict[str, Any]:
        return {
            "model_family": self.model_family,
            "coefficients": self.coefficients_dict,
            "intercept": self.intercept,
            "features": self.features,
            "target_column": self.target_column,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        result = {
            "schema_version": self.schema_version,
            "model_family": self.model_family,
            "input_artifact_id": self.input_artifact_id,
            "training_role": self.training_role,
            "target_column": self.target_column,
            "target_event_value": self.target_event_value,
            "class_mapping": dict(self.class_mapping),
            "probability_column_index": self.probability_column_index,
            "feature_contract": self.feature_contract.to_dict(),
            "feature_order_hash": self.feature_order_hash,
            "feature_dtype_contract": dict(self.feature_dtype_contract),
            "preprocessing_artifact_ids": list(self.preprocessing_artifact_ids),
            "prediction_contract": self.prediction_contract.to_dict(),
            "score_direction": self.score_direction,
            "calibration_artifact_id": self.calibration_artifact_id,
            "calibration": dict(self.calibration),
            "estimator_reference": self.estimator_reference.to_dict(),
            "training": self.training.to_dict(),
            "model_payload": dict(self.model_payload),
            "interpretability": self.interpretability.to_dict(),
            "base_odds": self.base_odds_text,
            "bad_class_label": self.bad_class_label,
            "warnings": list(self.warnings),
        }

        if self.source_variables is not None:
            result["source_variables"] = list(self.source_variables)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any], artifact_id: str = "") -> ModelArtifactV1:
        """Deserialize from a JSON dict."""
        model_family = data.get("model_family", "")
        if not model_family:
            raise ValueError("ModelArtifactV1 requires a non-empty 'model_family'.")

        # Reject legacy top-level keys that duplicate canonical locations
        for legacy_key in ("features", "coefficients", "intercept", "feature_strategy"):
            if legacy_key in data:
                raise ValueError(
                    f"ModelArtifactV1 rejects top-level key {legacy_key!r}; "
                    f"use feature_contract.features / model_payload.{legacy_key} instead."
                )

        if "feature_contract" not in data:
            raise ValueError("ModelArtifactV1 requires 'feature_contract'.")
        feature_contract = FeatureContract.from_dict(data.get("feature_contract", {}))
        if not feature_contract.features:
            raise ValueError("ModelArtifactV1 requires feature_contract.features to be a non-empty list.")

        model_payload = data.get("model_payload")
        if not isinstance(model_payload, dict) or not model_payload:
            raise ValueError("ModelArtifactV1 requires a non-empty 'model_payload' dict.")

        coeffs = model_payload.get("coefficients", {})
        if isinstance(coeffs, list):
            raise ValueError(
                "ModelArtifact coefficients must be a dict {variable: coefficient}; "
                "list-of-dicts form is not supported."
            )

        # For logistic regression, validate coefficient coverage
        if model_family == "logistic_regression":
            if "intercept" not in model_payload:
                raise ValueError(
                    "Logistic regression ModelArtifactV1 requires "
                    "'intercept' in model_payload."
                )
            if not isinstance(model_payload["intercept"], (int, float)):
                raise ValueError(
                    "Logistic regression ModelArtifactV1 requires "
                    "a numeric 'intercept' in model_payload."
                )
            if not isinstance(coeffs, dict):
                raise ValueError(
                    "Logistic regression ModelArtifactV1 requires "
                    "'coefficients' to be a dict in model_payload."
                )
            coeff_features = set(coeffs.keys())
            declared_features = set(feature_contract.features)
            missing = declared_features - coeff_features
            if missing:
                raise ValueError(
                    f"Logistic regression ModelArtifactV1 missing coefficients "
                    f"for features: {sorted(missing)}"
                )
            extra = coeff_features - declared_features
            if extra:
                raise ValueError(
                    f"Logistic regression ModelArtifactV1 has coefficients "
                    f"for unknown features: {sorted(extra)}"
                )
            for val in coeffs.values():
                if not isinstance(val, (int, float)):
                    raise ValueError(
                        f"Logistic regression coefficient {val!r} must be numeric."
                    )

        target_column = data.get("target_column", "")
        if not target_column:
            raise ValueError("ModelArtifactV1 requires non-empty 'target_column'.")

        target_event_value = data.get("target_event_value", "")
        if not target_event_value:
            raise ValueError("ModelArtifactV1 requires non-empty 'target_event_value'.")

        class_mapping = data.get("class_mapping", {})
        if not isinstance(class_mapping, dict) or not class_mapping:
            raise ValueError("ModelArtifactV1 requires non-empty 'class_mapping' dict.")

        if "probability_column_index" not in data:
            raise ValueError("ModelArtifactV1 requires 'probability_column_index'.")

        training = data.get("training", {})
        if not training.get("row_count"):
            raise ValueError("ModelArtifactV1 requires training.row_count > 0.")

        return cls(
            schema_version=data.get("schema_version", MODEL_ARTIFACT_SCHEMA_VERSION),
            model_family=model_family,
            input_artifact_id=data.get("input_artifact_id", ""),
            training_role=data.get("training_role", "train"),
            target_column=target_column,
            target_event_value=target_event_value,
            class_mapping=dict(class_mapping),
            probability_column_index=data.get("probability_column_index", 1),
            feature_contract=feature_contract,
            feature_order_hash=data.get("feature_order_hash", ""),
            feature_dtype_contract=dict(data.get("feature_dtype_contract", {})),
            preprocessing_artifact_ids=list(data.get("preprocessing_artifact_ids", [])),
            prediction_contract=PredictionContract.from_dict(data.get("prediction_contract", {})),
            score_direction=data.get("score_direction", "higher_is_lower_risk"),
            calibration_artifact_id=data.get("calibration_artifact_id", ""),
            calibration=dict(data.get("calibration", {})),
            estimator_reference=EstimatorReference.from_dict(data.get("estimator_reference", {})),
            training=TrainingMetadata.from_dict(training),
            model_payload=model_payload,
            interpretability=InterpretabilityMetadata.from_dict(data.get("interpretability", {})),
            source_variables=list(data.get("source_variables", [])) or None,
            base_odds_text=str(data.get("base_odds", "50:1")),
            bad_class_label=str(data.get("bad_class_label", "")),
            feature_strategy="",  # legacy; no longer written
            warnings=list(data.get("warnings", [])),
            source_artifact_id=artifact_id,
        )


def estimate_probability_column_index(class_mapping: dict[str, Any], target_event_value: str) -> int:
    """Infer which probability column represents the target event.

    sklearn's ``predict_proba`` columns follow ``estimator.classes_``.
    This helper maps the target event value to its position in the
    class mapping.
    """
    if not class_mapping or not target_event_value:
        return 1

    for idx_str, label in class_mapping.items():
        if str(label) == str(target_event_value):
            return int(idx_str)
    return 1


def validate_model_artifact(data: dict[str, Any]) -> list[str]:
    """Validate a model artifact dict against the v1 contract.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []

    if data.get("schema_version") != MODEL_ARTIFACT_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {MODEL_ARTIFACT_SCHEMA_VERSION!r}, "
            f"got {data.get('schema_version')!r}"
        )

    required_fields = [
        "model_family", "target_column", "target_event_value",
        "class_mapping", "feature_contract",
    ]
    for field_name in required_fields:
        if not data.get(field_name):
            errors.append(f"Required field {field_name!r} is missing or empty")

    fc = data.get("feature_contract", {})
    if not fc.get("features"):
        errors.append("feature_contract.features must be a non-empty list")

    if "probability_column_index" not in data:
        errors.append("probability_column_index is required")

    training = data.get("training", {})
    if not training.get("row_count"):
        errors.append("training.row_count is required")

    return errors
