"""Strict scorecard model artifact schema — cardre.model_artifact.v1.

The canonical, opinionated persisted contract for the logistic scorecard
pathway. It carries exactly the current shape: a WOE feature contract, an
intercept, per-feature coefficients, and training provenance. There is no
model-family dispatch, estimator or calibration metadata, generic
interpretability block, or tuning status.

The parser is strict: unknown top-level keys are rejected generically and
every current field is required — omitted fields are never reconstructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MODEL_ARTIFACT_SCHEMA_VERSION = "cardre.model_artifact.v1"

# ---------------------------------------------------------------------------
# Strict parser helpers
# ---------------------------------------------------------------------------


def _require(owner: str, data: dict[str, Any], keys: frozenset[str]) -> None:
    missing = keys - set(data)
    if missing:
        raise ValueError(f"{owner} requires the following key(s): {sorted(missing)}")


def _reject_unknown(owner: str, data: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{owner} rejects unknown key(s): {sorted(unknown)}")


# ---------------------------------------------------------------------------
# Sub-contracts
# ---------------------------------------------------------------------------


@dataclass
class FeatureContract:
    """Describes the WOE feature columns expected by the model at apply time."""

    features: list[str] = field(default_factory=list)
    transformation_strategy: str = "woe"
    order_hash: str = ""
    missing_policy: str = "error"
    unknown_category_policy: str = "error"

    _KEYS = frozenset({
        "features",
        "transformation_strategy",
        "order_hash",
        "missing_policy",
        "unknown_category_policy",
    })

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": list(self.features),
            "transformation_strategy": self.transformation_strategy,
            "order_hash": self.order_hash,
            "missing_policy": self.missing_policy,
            "unknown_category_policy": self.unknown_category_policy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureContract:
        if not isinstance(data, dict):
            raise ValueError("feature_contract must be an object")
        _reject_unknown("feature_contract", data, cls._KEYS)
        _require("feature_contract", data, cls._KEYS)
        features = data["features"]
        if not isinstance(features, list) or not features:
            raise ValueError("FeatureContract requires a non-empty 'features' list")
        for feature in features:
            if not isinstance(feature, str) or not feature:
                raise ValueError("FeatureContract feature names must be non-empty strings")
        return cls(
            features=list(features),
            transformation_strategy=str(data["transformation_strategy"]),
            order_hash=str(data["order_hash"]),
            missing_policy=str(data["missing_policy"]),
            unknown_category_policy=str(data["unknown_category_policy"]),
        )


@dataclass
class TrainingMetadata:
    """Records training conditions for reproducibility."""

    row_count: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    converged: bool = False
    iterations: int = 0

    _KEYS = frozenset({"row_count", "params", "converged", "iterations"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "params": dict(self.params),
            "converged": self.converged,
            "iterations": self.iterations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrainingMetadata:
        if not isinstance(data, dict):
            raise ValueError("training must be an object")
        _reject_unknown("training", data, cls._KEYS)
        _require("training", data, cls._KEYS)
        row_count = data["row_count"]
        if not isinstance(row_count, int) or row_count <= 0:
            raise ValueError("TrainingMetadata requires row_count > 0")
        if not isinstance(data["params"], dict):
            raise ValueError("TrainingMetadata 'params' must be an object")
        if not isinstance(data["converged"], bool):
            raise ValueError("TrainingMetadata 'converged' must be a boolean")
        if not isinstance(data["iterations"], int) or data["iterations"] < 0:
            raise ValueError("TrainingMetadata 'iterations' must be a non-negative integer")
        return cls(
            row_count=row_count,
            params=dict(data["params"]),
            converged=data["converged"],
            iterations=data["iterations"],
        )


@dataclass(frozen=True)
class ModelCoefficient:
    variable_name: str
    coefficient: float = 0.0
    standard_error: float | None = None
    p_value: float | None = None


# ---------------------------------------------------------------------------
# The strict logistic scorecard artifact
# ---------------------------------------------------------------------------


@dataclass
class ModelArtifactV1:
    """Strict logistic scorecard artifact — cardre.model_artifact.v1.

    The persisted payload is exactly the current logistic shape. Unknown
    top-level keys are rejected generically and every current field is
    required; nothing is reconstructed from omission.
    """

    target_column: str
    target_event_value: str
    class_mapping: dict[str, Any]
    probability_column_index: int
    feature_contract: FeatureContract
    model_payload: dict[str, Any]
    training: TrainingMetadata
    source_variables: list[str] = field(default_factory=list)
    bad_class_label: str = ""
    warnings: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = MODEL_ARTIFACT_SCHEMA_VERSION

    _TOP_LEVEL_KEYS = frozenset({
        "schema_version",
        "target_column",
        "target_event_value",
        "class_mapping",
        "probability_column_index",
        "feature_contract",
        "model_payload",
        "training",
        "source_variables",
        "bad_class_label",
        "warnings",
    })

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
    def coefficients(self) -> list[ModelCoefficient]:
        return [
            ModelCoefficient(variable_name=name, coefficient=value)
            for name, value in self.coefficients_dict.items()
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the canonical strict JSON-compatible dict."""
        return {
            "schema_version": self.schema_version,
            "target_column": self.target_column,
            "target_event_value": self.target_event_value,
            "class_mapping": dict(self.class_mapping),
            "probability_column_index": self.probability_column_index,
            "feature_contract": self.feature_contract.to_dict(),
            "model_payload": dict(self.model_payload),
            "training": self.training.to_dict(),
            "source_variables": list(self.source_variables),
            "bad_class_label": self.bad_class_label,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], artifact_id: str = "") -> ModelArtifactV1:
        """Deserialize from a strict JSON dict."""
        if not isinstance(data, dict):
            raise ValueError("ModelArtifactV1 requires an object payload")

        if data.get("schema_version") != MODEL_ARTIFACT_SCHEMA_VERSION:
            raise ValueError(
                f"ModelArtifactV1 requires schema_version "
                f"{MODEL_ARTIFACT_SCHEMA_VERSION!r}, got {data.get('schema_version')!r}."
            )

        # Reject unknown top-level keys generically (no historical blacklist).
        _reject_unknown("ModelArtifactV1", data, cls._TOP_LEVEL_KEYS)
        # Require the complete current set; never reconstruct omitted fields.
        _require("ModelArtifactV1", data, cls._TOP_LEVEL_KEYS)

        feature_contract = FeatureContract.from_dict(data["feature_contract"])

        model_payload = data["model_payload"]
        if not isinstance(model_payload, dict) or not model_payload:
            raise ValueError("ModelArtifactV1 requires a non-empty 'model_payload' dict.")
        if "intercept" not in model_payload or not isinstance(model_payload["intercept"], (int, float)):
            raise ValueError("ModelArtifactV1 requires a numeric 'intercept' in model_payload.")
        coeffs = model_payload.get("coefficients", {})
        if not isinstance(coeffs, dict):
            raise ValueError(
                "ModelArtifactV1 requires 'coefficients' to be a dict "
                "{variable: coefficient} in model_payload."
            )
        coeff_features = set(coeffs.keys())
        declared_features = set(feature_contract.features)
        missing = declared_features - coeff_features
        if missing:
            raise ValueError(
                f"ModelArtifactV1 missing coefficients for features: {sorted(missing)}"
            )
        extra = coeff_features - declared_features
        if extra:
            raise ValueError(
                f"ModelArtifactV1 has coefficients for unknown features: {sorted(extra)}"
            )
        for value in coeffs.values():
            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"ModelArtifactV1 coefficient {value!r} must be numeric."
                )

        class_mapping = data["class_mapping"]
        if not isinstance(class_mapping, dict) or not class_mapping:
            raise ValueError("ModelArtifactV1 requires non-empty 'class_mapping' dict.")

        probability_column_index = data["probability_column_index"]
        if not isinstance(probability_column_index, int):
            raise ValueError("ModelArtifactV1 'probability_column_index' must be an integer.")

        source_variables = data["source_variables"]
        if not isinstance(source_variables, list) or not source_variables:
            raise ValueError("ModelArtifactV1 requires non-empty 'source_variables' list.")
        if not all(isinstance(value, str) and value for value in source_variables):
            raise ValueError("ModelArtifactV1 'source_variables' must contain non-empty strings.")

        warnings = data["warnings"]
        if not isinstance(warnings, list) or not all(isinstance(warning, dict) for warning in warnings):
            raise ValueError("ModelArtifactV1 'warnings' must be a list.")

        target_column = data["target_column"]
        target_event_value = data["target_event_value"]
        bad_class_label = data["bad_class_label"]
        if not all(
            isinstance(value, str) and value
            for value in (target_column, target_event_value, bad_class_label)
        ):
            raise ValueError(
                "ModelArtifactV1 requires non-empty target_column, "
                "target_event_value, and bad_class_label strings."
            )
        if probability_column_index < 0:
            raise ValueError("ModelArtifactV1 'probability_column_index' must be non-negative.")

        return cls(
            target_column=target_column,
            target_event_value=target_event_value,
            class_mapping=dict(class_mapping),
            probability_column_index=probability_column_index,
            feature_contract=feature_contract,
            model_payload=dict(model_payload),
            training=TrainingMetadata.from_dict(data["training"]),
            source_variables=list(source_variables),
            bad_class_label=bad_class_label,
            warnings=[dict(w) for w in warnings],
            schema_version=data["schema_version"],
        )
