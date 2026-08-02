"""CalibrateProbabilitiesNode - Platt and isotonic calibration for probability outputs.

Fits a calibrator (Platt logistic regression or isotonic regression) on scored
holdout data and wraps the original ModelArtifact with a calibration block.

Score-scaling-compatible modes:
  - Platt (single, no CV): folded_linear_log_odds, score_scaling_compatible=True.
    Updates top-level intercept and coefficients so ScoreScalingNode consumes
    calibrated log-odds transparently.
  - Platt CV ensemble: runtime_probability_transform, not scorecard-compatible.
  - Isotonic (any): runtime_probability_transform, not scorecard-compatible.
"""

from __future__ import annotations

import hashlib
import io
from typing import Any, cast

import joblib
import numpy as np
import polars as pl
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind, RoleKind
from cardre.domain.evidence.schemas import SCHEMA_CALIBRATION_REPORT, SCHEMA_MODEL_ARTIFACT
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


def _safe_logit(probability: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Convert probabilities to log-odds with clipping for numerical safety."""
    p = np.clip(np.asarray(probability, dtype=float), eps, 1.0 - eps)
    return cast(np.ndarray[Any, Any], np.log(p / (1.0 - p)))


def _compute_calibration_bins(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    y_prob_cal: np.ndarray,
    n_bins: int = 10,
) -> list[JsonDict]:
    """Compute 10-bin calibration diagnostics (pre and post)."""
    bins: list[JsonDict] = []
    quantiles = np.linspace(0, 100, n_bins + 1)
    percentiles = np.percentile(y_prob_cal, quantiles)

    for i in range(n_bins):
        lo = percentiles[i]
        hi = percentiles[i + 1]
        if i == n_bins - 1:
            mask = (y_prob_cal >= lo) & (y_prob_cal <= hi)
        else:
            mask = (y_prob_cal >= lo) & (y_prob_cal < hi)

        count = int(np.sum(mask))
        if count == 0:
            continue
        avg_pred_cal = float(np.mean(y_prob_cal[mask]))
        avg_pred_pre = float(np.mean(y_prob[mask]))
        actual_rate = float(np.mean(y_true[mask]))
        bins.append({
            "bin": i,
            "count": count,
            "avg_predicted": round(avg_pred_cal, 6),
            "actual_bad_rate": round(actual_rate, 6),
            "avg_predicted_" "raw": round(avg_pred_pre, 6),
            "abs_deviation": round(abs(avg_pred_cal - actual_rate), 6),
        })
    return bins


class _CalibratorEnsemble:
    """Ensemble of calibrators fitted on CV folds.

    Averages predict_proba (Platt) or predict (isotonic) across folds.
    """

    def __init__(self, calibrators: list[Any], method: str) -> None:
        self._calibrators = calibrators
        self._method = method
        if method == "platt":
            self._has_predict_proba = True
        else:
            self._has_predict_proba = False

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Average calibrated probabilities across all fold calibrators."""
        all_probs: list[np.ndarray[Any, Any]] = []
        for cal in self._calibrators:
            if self._method == "platt":
                raw = X[:, 1] if X.ndim == 2 and X.shape[1] == 2 else X.ravel()
                p = cal.predict_proba(_safe_logit(raw).reshape(-1, 1))
                all_probs.append(p)
            else:
                raw = X[:, 1] if X.ndim == 2 and X.shape[1] == 2 else X.ravel()
                p = cal.predict(raw)
                all_probs.append(np.column_stack([1.0 - p, p]))
        return cast(np.ndarray[Any, Any], np.asarray(np.mean(all_probs, axis=0), dtype=float))

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return average prediction across fold calibrators."""
        all_preds: list[np.ndarray[Any, Any]] = []
        for cal in self._calibrators:
            if self._method == "platt":
                raw = X[:, 1] if X.ndim == 2 and X.shape[1] == 2 else X.ravel()
                p = cal.predict_proba(_safe_logit(raw).reshape(-1, 1))
                all_preds.append(p[:, 1] if p.shape[1] > 1 else p[:, 0])
            else:
                raw = X[:, 1] if X.ndim == 2 and X.shape[1] == 2 else X.ravel()
                all_preds.append(cal.predict(raw))
        return cast(np.ndarray[Any, Any], np.asarray(np.mean(all_preds, axis=0), dtype=float))


def _fit_platt_cv(
    y_prob: np.ndarray,
    y_true: np.ndarray,
    n_folds: int = 5,
) -> _CalibratorEnsemble:
    """Fit Platt calibrator via CV, averaging calibrator probabilities."""
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    all_calibrators: list[Any] = []
    for train_idx, _ in skf.split(np.zeros(len(y_true)), y_true):
        cal = LogisticRegression(solver="lbfgs")
        X_fold = _safe_logit(y_prob[train_idx]).reshape(-1, 1)
        cal.fit(X_fold, y_true[train_idx])
        all_calibrators.append(cal)
    return _CalibratorEnsemble(all_calibrators, method="platt")


def _fit_isotonic_cv(
    y_prob: np.ndarray,
    y_true: np.ndarray,
    n_folds: int = 5,
) -> _CalibratorEnsemble:
    """Fit isotonic calibrator via CV, averaging predictions."""
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    all_calibrators = []
    for train_idx, _ in skf.split(np.zeros(len(y_true)), y_true):
        cal = IsotonicRegression(out_of_bounds="clip")
        cal.fit(y_prob[train_idx], y_true[train_idx])
        all_calibrators.append(cal)
    return _CalibratorEnsemble(all_calibrators, method="isotonic")


def _supports_folded_linear_calibration(typed_model: Any) -> bool:
    from cardre.modeling.families import get as get_family_spec
    spec = get_family_spec(typed_model.model_family)
    return (
        spec is not None
        and spec.has_coefficients
        and spec.supports_scorecard_scaling
        and typed_model.has_explicit_intercept
        and bool(typed_model.coefficients_dict)
    )


class CalibrateProbabilitiesNode(NodeType):
    node_type = "cardre.calibrate_probabilities"
    version = "1"
    category = "fit"
    description = "Calibrate model probabilities using Platt scaling or isotonic regression"

    __definition__ = NodeDefinition(
        node_type="cardre.calibrate_probabilities",
        version="1",
        category="fit",
        description=description,
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("train", required=False, kinds=(RoleKind.DATASET,)),
                ArtifactRoleSpec("test", required=False, kinds=(RoleKind.DATASET,)),
                ArtifactRoleSpec("oot", required=False, kinds=(RoleKind.DATASET,)),
                ArtifactRoleSpec("definition", required=False, kinds=(RoleKind.DEFINITION,)),
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,)),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,), media_types=("application/json",), schema_versions=(SCHEMA_MODEL_ARTIFACT,)),
                ArtifactRoleSpec("estimator", required=False, media_types=("application/octet-stream",)),
                ArtifactRoleSpec("report", kinds=(EvidenceKind.CALIBRATION_REPORT,), media_types=("application/json",), schema_versions=(SCHEMA_CALIBRATION_REPORT,)),
            ),
        ),
    )

    def allows_leakage_artifact(self, artifact: ArtifactRef) -> bool:
        """Allow test/OOT scored datasets only when they carry a model_artifact_id
        metadata proving they are apply-model outputs, not raw training splits."""
        return (
            artifact.role in {"test", "oot"}
            and artifact.artifact_type == "dataset"
            and bool(artifact.metadata.get("model_artifact_id"))
        )

    MIN_CALIBRATION_ROWS = 30
    ISOTONIC_MIN_ROWS = 1000

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Calibrate Probabilities",
            default_method="platt",
            methods=[
                MethodOption(
                    id="platt",
                    label="Platt Scaling",
                    status="available",
                    description=(
                        "Logistic sigmoid calibration. "
                        "Without CV, folds calibrator into linear log-odds "
                        "for scorecard compatibility. With CV, uses ensemble average."
                    ),
                    params=[
                        ParameterDefinition(
                            name="calibration_sample",
                            label="Calibration Sample",
                            kind="enum",
                            default="train",
                            constraint=ParameterConstraint(
                                enum_values=["test", "oot", "train"],
                            ),
                            help_text=(
                                "Which data role to use for fitting the calibrator. "
                                "When 'train' is used with cross_validation=True, "
                                "the calibrator is fitted via out-of-fold predictions "
                                "and test/OOT remain clean holdouts for final validation."
                            ),
                        ),
                        ParameterDefinition(
                            name="cross_validation",
                            label="Cross-Validation",
                            kind="boolean",
                            default=True,
                            help_text=(
                                "Use CV ensemble when True (recommended). "
                                "When calibration_sample='train' and CV is on, "
                                "the calibrator is fitted on out-of-fold predictions "
                                "to avoid overfitting. Note: CV Platt produces a "
                                "runtime probability transform that is not "
                                "scorecard-point compatible; score scaling will fail."
                            ),
                        ),
                        ParameterDefinition(
                            name="cv_folds",
                            label="CV Folds",
                            kind="integer",
                            default=5,
                            constraint=ParameterConstraint(min_value=2, max_value=20),
                        ),
                        ParameterDefinition(
                            name="min_probability",
                            label="Min Probability",
                            kind="float",
                            default=0.001,
                            constraint=ParameterConstraint(min_value=0.0, exclusive_min=0.0),
                        ),
                        ParameterDefinition(
                            name="max_probability",
                            label="Max Probability",
                            kind="float",
                            default=0.999,
                            constraint=ParameterConstraint(max_value=1.0, exclusive_max=1.0),
                        ),
                    ],
                ),
                MethodOption(
                    id="isotonic",
                    label="Isotonic Regression",
                    status="available",
                    description=(
                        "Non-parametric step-function calibration. "
                        "Not compatible with additive scorecard points."
                    ),
                    params=[
                        ParameterDefinition(
                            name="calibration_sample",
                            label="Calibration Sample",
                            kind="enum",
                            default="train",
                            constraint=ParameterConstraint(
                                enum_values=["test", "oot", "train"],
                            ),
                            help_text="Which data role to use for fitting the calibrator.",
                        ),
                        ParameterDefinition(
                            name="cross_validation",
                            label="Cross-Validation",
                            kind="boolean",
                            default=True,
                        ),
                        ParameterDefinition(
                            name="cv_folds",
                            label="CV Folds",
                            kind="integer",
                            default=5,
                            constraint=ParameterConstraint(min_value=2, max_value=20),
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        sample = params.get("calibration_sample", "train")
        if sample not in ("test", "oot", "train"):
            errors.append(f"calibration_sample must be 'test', 'oot', or 'train', got {sample!r}")
        method = params.get("method", "platt")
        if method not in ("platt", "isotonic"):
            errors.append(f"method must be 'platt' or 'isotonic', got {method!r}")
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        method = params.get("method", "platt")
        calibration_sample = params.get("calibration_sample", "train")
        min_prob = float(params.get("min_probability", 0.001))
        max_prob = float(params.get("max_probability", 0.999))
        cross_validated = bool(params.get("cross_validation", True))
        cv_folds = int(params.get("cv_folds", 5))

        if cv_folds < 2:
            cross_validated = False

        # 1. Read modelling metadata for target definition
        meta = context.inputs.target_metadata()
        target_column = meta.target_column if meta else ""
        good_values = meta.good_values if meta else frozenset()
        bad_values = meta.bad_values if meta else frozenset()
        if not good_values or not bad_values:
            raise ValueError(
                "Calibration requires modelling metadata with good_values and bad_values"
            )

        # 2. Read the scored calibration sample
        calib_art = next(
            (a for a in context.inputs.by_role(calibration_sample)),
            None,
        )
        if calib_art is None:
            raise ValueError(
                f"Calibration requires a dataset with role={calibration_sample!r}, "
                f"none found in input artifacts"
            )

        df = context.inputs.read_dataframe(calib_art)

        if "predicted_bad_probability" not in df.columns:
            raise ValueError(
                f"Calibration sample role={calibration_sample!r} is missing "
                f"column 'predicted_bad_probability'. Run apply-model first."
            )
        if target_column not in df.columns:
            raise ValueError(
                f"Calibration sample role={calibration_sample!r} is missing "
                f"target column {target_column!r}"
            )

        # 3. Extract raw probabilities and binary target with proper value mapping
        y_prob = df["predicted_bad_probability"].to_numpy()
        target_str = df[target_column].cast(pl.String)
        unknown = df.filter(~target_str.is_in(good_values | bad_values))
        if unknown.height > 0:
            raise ValueError(
                f"Calibration target column {target_column!r} contains "
                f"{unknown.height} value(s) not declared as good or bad"
            )
        y_binary = target_str.is_in(bad_values).cast(pl.Int64).to_numpy()

        # Clip extreme values
        y_prob = np.clip(y_prob, min_prob, max_prob)

        # 4. Build warnings list
        warnings_list: list[JsonDict] = []
        too_few_rows = df.height < self.MIN_CALIBRATION_ROWS
        if too_few_rows:
            warnings_list.append({
                "code": "TOO_FEW_CALIBRATION_ROWS",
                "message": (
                    f"Calibration sample ({calibration_sample}) has {df.height} rows, "
                    f"minimum is {self.MIN_CALIBRATION_ROWS}. "
                    f"Skipping calibration and passing through the original model unchanged."
                ),
            })

        # Warn if calibration sample is train without CV (risk of overfitting)
        if calibration_sample == "train" and not cross_validated:
            warnings_list.append({
                "code": "CALIBRATION_ON_TRAIN_SAMPLE",
                "message": (
                    "Calibration fitted on the training sample without "
                    "cross-validation. This risks overfitting the calibrator. "
                    "Enable cross_validation or use a held-out sample (test/oot)."
                ),
            })

        # Warn if calibration uses test sample - OOT is needed for clean validation
        if calibration_sample == "test":
            warnings_list.append({
                "code": "CALIBRATION_ON_TEST_SAMPLE",
                "message": (
                    "Calibration fitted on the test sample. "
                    "Because test is used for calibration, it is not an independent "
                    "holdout for post-calibration validation. "
                    "Ensure an OOT sample is used for final model validation."
                ),
            })

        # Read model artifact once for model_family checks and later update
        typed_model = context.inputs.read(
            context.inputs.require("model", self.node_type),
            EvidenceKind.MODEL_ARTIFACT,
        )
        has_linear_coefficients = _supports_folded_linear_calibration(typed_model)

        # 5. Fit calibrator (skip if too few rows)
        if too_few_rows:
            # Pass through: original model unchanged, no calibrator artifact
            application_mode = "folded_linear_log_odds" if has_linear_coefficients else "runtime_probability_transform"
            score_scaling_compatible = has_linear_coefficients
            calibrator = None
        elif method == "platt":
            log_odds = _safe_logit(y_prob).reshape(-1, 1)
            if cross_validated and cv_folds > 1:
                calibrator = _fit_platt_cv(y_prob, y_binary, cv_folds)
                application_mode = "runtime_probability_transform"
                score_scaling_compatible = False
            else:
                calibrator = LogisticRegression(solver="lbfgs")
                calibrator.fit(log_odds, y_binary)
                slope = float(calibrator.coef_[0][0])
                intercept_shift = float(calibrator.intercept_[0])
                if slope <= 0:
                    raise ValueError(
                        "Platt calibration produced non-positive slope; "
                        "score ordering would invert"
                    )
                if has_linear_coefficients:
                    application_mode = "folded_linear_log_odds"
                    score_scaling_compatible = True
                else:
                    application_mode = "runtime_probability_transform"
                    score_scaling_compatible = False
        elif method == "isotonic":
            if cross_validated and cv_folds > 1:
                calibrator = _fit_isotonic_cv(y_prob, y_binary, cv_folds)
            else:
                calibrator = IsotonicRegression(out_of_bounds="clip")
                calibrator.fit(y_prob, y_binary)
            application_mode = "runtime_probability_transform"
            score_scaling_compatible = False
            # Warn if small sample for isotonic
            if len(y_prob) < self.ISOTONIC_MIN_ROWS:
                warnings_list.append({
                    "code": "SMALL_ISOTONIC_SAMPLE",
                    "message": (
                        f"Isotonic regression on {len(y_prob)} rows "
                        f"(<{self.ISOTONIC_MIN_ROWS}): non-parametric calibration "
                        f"may overfit"
                    ),
                })
        else:
            raise ValueError(f"Unknown calibration method {method!r}")

        # 6. Compute calibrated probabilities for diagnostics
        if calibrator is not None:
            if method == "platt" and not cross_validated:
                y_prob_cal = calibrator.predict_proba(log_odds)[:, 1]
            elif hasattr(calibrator, "predict_proba"):
                probs = calibrator.predict_proba(
                    np.column_stack([1.0 - y_prob, y_prob])
                )
                y_prob_cal = probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
            else:
                y_prob_cal = calibrator.predict(y_prob)
        else:
            y_prob_cal = y_prob  # pass-through

        # 7. Compute calibration metrics (10-bin)
        bins = _compute_calibration_bins(y_binary, y_prob, y_prob_cal)

        calibration_error = float(np.mean([b["abs_deviation"] for b in bins]))
        max_bin_deviation = float(np.max([b["abs_deviation"] for b in bins]))

        if calibration_error > 0.05 and not too_few_rows:
            warnings_list.append({
                "code": "HIGH_CALIBRATION_ERROR",
                "message": (
                    f"Post-calibration calibration error {calibration_error:.4f} "
                    f"exceeds 0.05"
                ),
            })

        # 8. Build updated model artifact from the original
        model: dict[str, Any] = typed_model.to_dict()

        # 9. Serialize the calibrator and precompute its descriptor id so the
        # JSON model can reference it before the binary is staged. Publish
        # order matters: downstream `require("model")`/`first("model")`
        # consumers select the first model artifact by role, and it must be the
        # parseable JSON model, not the joblib calibrator blob.
        calibrator_ref: dict[str, Any] | None = None
        if calibrator is not None:
            calibrator_buf = io.BytesIO()
            joblib.dump(calibrator, calibrator_buf)
            serialized_calibrator = calibrator_buf.getvalue()
            calibrator_logical_hash = hashlib.sha256(serialized_calibrator).hexdigest()
            calibrator_metadata = {
                "schema_version": SCHEMA_MODEL_ARTIFACT,
                "artifact_subtype": "probability_calibrator",
                "method": method,
                "estimator_format": "joblib",
                "byte_count": len(serialized_calibrator),
                "creating_run_id": context.run_id,
                "creating_run_step_id": context.runtime.step_id,
            }
            from cardre.nodes._training_utils import _model_binary_descriptor_id

            calibrator_ref = {
                "provisional_artifact_id": _model_binary_descriptor_id(
                    serialized_calibrator, calibrator_logical_hash, calibrator_metadata,
                ),
                "physical_hash": calibrator_logical_hash,
                "logical_hash": calibrator_logical_hash,
            }

            if application_mode == "folded_linear_log_odds":
                model_payload = dict(model.get("model_payload", {}))
                original_intercept = typed_model.intercept
                original_coefficients = typed_model.coefficients_dict
                model_payload["intercept"] = round(original_intercept * slope + intercept_shift, 6)
                model_payload["coefficients"] = {
                    name: round(float(value) * slope, 6)
                    for name, value in original_coefficients.items()
                }
                model["model_payload"] = model_payload
        # 10. Write calibration report artifact
        cal_report: JsonDict = {
            "schema_version": SCHEMA_CALIBRATION_REPORT,
            "method": method,
            "calibrated_on": calibration_sample,
            "cross_validated": cross_validated,
            "calibration_error": round(calibration_error, 6),
            "max_bin_deviation": round(max_bin_deviation, 6),
            "bins": bins,
            "warnings": warnings_list,
            "calibration_sample_role": calibration_sample,
            "calibration_sample_is_training_independent": calibration_sample in ("test", "oot"),
            "calibration_sample_is_post_calibration_validation_holdout": False,
            "post_calibration_validation_requires_different_role": True,
            "recommended_independent_validation_roles": [
                role for role in ("test", "oot") if role != calibration_sample
            ],
            "source_scoring_policy": {
                "woe_unmatched_policy": "fail",
            },
        }
        report_art = context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.CALIBRATION_REPORT,
            payload=cal_report,
            metadata={"schema_version": SCHEMA_CALIBRATION_REPORT},
        )

        # 11. Update model artifact with calibration block
        if calibrator_ref is not None:
            model["calibration"] = {
                "method": method,
                "application_mode": application_mode,
                "score_scaling_compatible": score_scaling_compatible,
                "cross_validated": cross_validated,
                "calibrator_artifact_id": calibrator_ref["provisional_artifact_id"],
                "calibrator_physical_hash": calibrator_ref["physical_hash"],
                "calibrator_logical_hash": calibrator_ref["logical_hash"],
                "calibration_report_artifact_id": report_art.provisional_artifact_id,
                "calibration_report_physical_hash": report_art.physical_hash,
                "calibration_error": round(calibration_error, 6),
                "max_bin_deviation": round(max_bin_deviation, 6),
                "calibrator_format": "joblib",
            }
        else:
            model["calibration"] = {
                "method": method,
                "application_mode": application_mode,
                "score_scaling_compatible": score_scaling_compatible,
                "cross_validated": cross_validated,
                "calibrator_artifact_id": "",
                "calibrator_physical_hash": "",
                "calibrator_logical_hash": "",
                "calibration_report_artifact_id": report_art.provisional_artifact_id,
                "calibration_report_physical_hash": report_art.physical_hash,
                "calibration_error": round(calibration_error, 6),
                "max_bin_deviation": round(max_bin_deviation, 6),
                "calibrator_format": "none",
                "note": "Calibration skipped: too few rows in calibration sample",
            }
        model["schema_version"] = SCHEMA_MODEL_ARTIFACT

        # Publish the JSON model BEFORE the calibrator blob so role consumers
        # select the parseable model. The blob is staged last with the same
        # precomputed descriptor id the model's calibration block references.
        context.outputs.publish_json(
            role="model",
            kind=EvidenceKind.MODEL_ARTIFACT,
            payload=model,
            metadata={
                "schema_version": SCHEMA_MODEL_ARTIFACT,
                "calibrated": calibrator is not None,
                "calibration_method": method,
            },
        )

        if calibrator_ref is not None:
            context.outputs.publish_bytes(
                role="estimator",
                kind=EvidenceKind.MODEL_ARTIFACT,
                data=serialized_calibrator,
                media_type="application/octet-stream",
                logical_hash=calibrator_logical_hash,
                metadata=calibrator_metadata,
            )

        context.outputs.add_metric("method", method)
        context.outputs.add_metric("calibration_sample", calibration_sample)
        context.outputs.add_metric("calibration_error", round(calibration_error, 6))
        context.outputs.add_metric("cross_validated", cross_validated)
        context.outputs.add_metric("calibration_skipped", calibrator is None)
        return context.outputs.build_result()
