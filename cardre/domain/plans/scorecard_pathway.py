from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec

_CANONICAL_SCORECARD_STEPS: list[tuple[str, str, list[str], dict[str, Any]]] = [
    (
        "import",
        "cardre.import_dataset",
        [],
        {"source_path": "PLACEHOLDER"},
    ),
    (
        "define-metadata",
        "cardre.define_modelling_metadata",
        ["import"],
        {
            "target_column": "credit_risk_class",
            "good_values": ["good"],
            "bad_values": ["bad"],
            "purpose": "application_credit_scorecard",
            # Business metadata is deliberately empty in the production
            # template: a real project must supply product, segment, windows
            # and reject-inference position before the version can commit.
            "product": "",
            "segment": "",
            "observation_window": "",
            "performance_window": "",
            "reject_inference_position": "",
        },
    ),
    (
        "apply-exclusions",
        "cardre.apply_exclusions",
        ["import", "define-metadata"],
        {"rules": []},
    ),
    (
        "profile",
        "cardre.profile_dataset",
        ["apply-exclusions"],
        {},
    ),
    (
        "validate-target",
        "cardre.validate_binary_target",
        ["apply-exclusions", "define-metadata"],
        {"target_column": "credit_risk_class"},
    ),
    (
        "sample-definition",
        "cardre.development_sample_definition",
        ["apply-exclusions", "define-metadata"],
        {
            "sample_method": "full_population",
            "sample_domain": "ttd",
            "sample_description": "Full booked population without additional row filtering",
        },
    ),
    (
        "split",
        "cardre.split_train_test_oot",
        ["apply-exclusions", "sample-definition"],
        {"target_column": "credit_risk_class"},
    ),
    (
        "explicit-missing-outlier-treatment",
        "cardre.explicit_missing_outlier_treatment",
        ["split"],
        {"imputations": {}, "caps": {}, "floors": {}},
    ),
    (
        "automatic-binning",
        "cardre.automatic_binning",
        ["explicit-missing-outlier-treatment", "define-metadata"],
        {},
    ),
    (
        "initial-woe-iv",
        "cardre.calculate_woe_iv",
        ["explicit-missing-outlier-treatment", "automatic-binning", "define-metadata"],
        {"purpose": "initial"},
    ),
    (
        "variable-clustering",
        "cardre.variable_clustering",
        ["explicit-missing-outlier-treatment", "initial-woe-iv"],
        {},
    ),
    (
        "variable-selection",
        "cardre.variable_selection",
        ["initial-woe-iv", "variable-clustering"],
        {"min_iv": 0.0},
    ),
    (
        "manual-binning",
        "cardre.manual_binning",
        ["automatic-binning", "variable-selection"],
        {"accept_automated": False},
    ),
    (
        "final-woe-iv",
        "cardre.calculate_woe_iv",
        ["explicit-missing-outlier-treatment", "manual-binning", "define-metadata"],
        {
            "purpose": "final",
        },
    ),
    (
        "woe-transform-train",
        "cardre.woe_transform_train",
        [
            "explicit-missing-outlier-treatment",
            "manual-binning",
            "final-woe-iv",
            "define-metadata",
            "variable-selection",
        ],
        {},
    ),
    (
        "model-fit",
        "cardre.logistic_regression",
        ["woe-transform-train", "define-metadata", "variable-selection"],
        {},
    ),
    (
        "coefficient-sign-check",
        "cardre.coefficient_sign_check",
        ["model-fit", "final-woe-iv"],
        {},
    ),
    (
        "separation-diagnostics",
        "cardre.separation_diagnostics",
        ["model-fit"],
        {},
    ),
    (
        "vif-diagnostics",
        "cardre.vif_diagnostics",
        ["woe-transform-train", "model-fit"],
        {},
    ),
    (
        "score-scaling",
        "cardre.score_scaling",
        [
            "model-fit",
            "manual-binning",
            "final-woe-iv",
            "coefficient-sign-check",
            "separation-diagnostics",
            "vif-diagnostics",
        ],
        {},
    ),
    (
        "build-summary-report",
        "cardre.build_summary_report",
        ["score-scaling", "model-fit", "final-woe-iv"],
        {},
    ),
    (
        "freeze-scorecard-bundle",
        "cardre.freeze_scorecard_bundle",
        [
            "score-scaling",
            "model-fit",
            "manual-binning",
            "final-woe-iv",
            "define-metadata",
            "variable-selection",
        ],
        {},
    ),
    (
        "apply-woe",
        "cardre.apply_woe_mapping",
        [
            "explicit-missing-outlier-treatment",
            "manual-binning",
            "final-woe-iv",
            "variable-selection",
            "freeze-scorecard-bundle",
        ],
        {},
    ),
    (
        "apply-model",
        "cardre.apply_model",
        ["apply-woe", "model-fit", "score-scaling", "freeze-scorecard-bundle"],
        {},
    ),
    (
        "calibration-diagnostics",
        "cardre.calibration_diagnostics",
        ["apply-model", "model-fit", "define-metadata"],
        {},
    ),
    (
        "validation-metrics",
        "cardre.validation_metrics",
        ["apply-model", "define-metadata"],
        {"fail_on_missing_score": True, "require_test": True, "require_oot": False},
    ),
    (
        "cutoff-analysis",
        "cardre.cutoff_analysis",
        ["apply-model", "define-metadata"],
        {},
    ),
    (
        "scorecard-table-export",
        "cardre.scorecard_table_export",
        ["score-scaling", "freeze-scorecard-bundle", "apply-model", "manual-binning", "final-woe-iv"],
        {},
    ),
    (
        "scoring-export-python",
        "cardre.scoring_export_python",
        ["freeze-scorecard-bundle", "model-fit", "score-scaling", "apply-model", "manual-binning", "final-woe-iv"],
        {},
    ),
    (
        "scoring-export-sql",
        "cardre.scoring_export_sql",
        ["freeze-scorecard-bundle", "model-fit", "score-scaling", "apply-model", "manual-binning", "final-woe-iv"],
        {},
    ),
    (
        "technical-manifest",
        "cardre.technical_manifest_export",
        [
            "define-metadata",
            "sample-definition",
            "final-woe-iv",
            "build-summary-report",
            "validation-metrics",
            "cutoff-analysis",
        ],
        {},
    ),
]


def canonical_scorecard_step_ids() -> list[str]:
    return [step_id for step_id, _, _, _ in _CANONICAL_SCORECARD_STEPS]


# Target-dependent canonical steps: a custom target must reach all three for
# the pathway to be internally consistent.
TARGET_DEPENDENT_STEP_IDS = ("define-metadata", "validate-target", "split")


def _rebuild_step(step: StepSpec, params: dict[str, Any]) -> StepSpec:
    """Rebuild a canonical step with new params, recomputing params_hash."""
    return StepSpec(
        step_id=step.step_id, node_type=step.node_type,
        node_version=step.node_version, category=step.category,
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=step.parent_step_ids,
        position=step.position,
        canonical_step_id=step.canonical_step_id,
    )


def configure_canonical_scorecard(
    steps: list[StepSpec],
    *,
    target_column: str | None = None,
    good_values: list[str] | None = None,
    bad_values: list[str] | None = None,
    product: str | None = None,
    segment: str | None = None,
    observation_window: str | None = None,
    performance_window: str | None = None,
    reject_inference_position: str | None = None,
    accept_automated: bool | None = None,
    smoothing: dict[str, Any] | None = None,
) -> list[StepSpec]:
    """Apply optional user configuration to a canonical pathway's steps.

    ``target_column`` is propagated to *every* target-dependent step
    (``define-metadata``, ``validate-target``, ``split``), so a custom
    target stays internally consistent across the pathway. All other
    options target the specific step that owns them. Unaffected steps are
    returned unchanged. A new list is returned; the input is not mutated.
    """
    result: list[StepSpec] = []
    for step in steps:
        params = dict(step.params)
        if step.canonical_step_id == "define-metadata":
            if target_column is not None:
                params["target_column"] = target_column
            if good_values is not None:
                params["good_values"] = list(good_values)
            if bad_values is not None:
                params["bad_values"] = list(bad_values)
            for key, value in (
                ("product", product),
                ("segment", segment),
                ("observation_window", observation_window),
                ("performance_window", performance_window),
                ("reject_inference_position", reject_inference_position),
            ):
                if value is not None:
                    params[key] = value
        elif step.canonical_step_id in ("validate-target", "split"):
            if target_column is not None:
                params["target_column"] = target_column
        elif step.canonical_step_id == "manual-binning":
            if accept_automated is not None:
                params["accept_automated"] = bool(accept_automated)
        elif step.canonical_step_id == "final-woe-iv":
            if smoothing is not None:
                params["smoothing"] = dict(smoothing)
        if params != step.params:
            result.append(_rebuild_step(step, params))
        else:
            result.append(step)
    return result


def build_canonical_scorecard_steps(
    source_path: str | Path,
    resolve_node: Callable[[str], Any],
) -> list[StepSpec]:
    resolved_source_path = str(source_path)
    result: list[StepSpec] = []

    for position, (step_id, node_type, parent_step_ids, raw_params) in enumerate(_CANONICAL_SCORECARD_STEPS):
        params = dict(raw_params)
        if step_id == "import":
            params["source_path"] = resolved_source_path
        node_cls = resolve_node(node_type)
        result.append(
            StepSpec(
                step_id=step_id,
                node_type=node_type,
                node_version=node_cls.node_definition().version,
                category=node_cls.node_definition().category,
                params=params,
                params_hash=json_logical_hash(params),
                parent_step_ids=list(parent_step_ids),
                position=position,
                canonical_step_id=step_id,
            )
        )

    return result


__all__ = ["build_canonical_scorecard_steps", "canonical_scorecard_step_ids", "configure_canonical_scorecard", "TARGET_DEPENDENT_STEP_IDS"]
