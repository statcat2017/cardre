from __future__ import annotations

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec
from cardre.nodes.registry import NodeRegistry

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
            "product": "term_loan",
            "segment": "retail",
            "observation_window": "2024-01_to_2024-06",
            "performance_window": "2024-07_to_2024-12",
            "reject_inference_position": "not_applied",
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
        "fine-classing",
        "cardre.fine_classing",
        ["explicit-missing-outlier-treatment", "define-metadata"],
        {},
    ),
    (
        "initial-woe-iv",
        "cardre.calculate_woe_iv",
        ["explicit-missing-outlier-treatment", "fine-classing", "define-metadata"],
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
        ["fine-classing", "variable-selection"],
        {"accept_automated": True},
    ),
    (
        "final-woe-iv",
        "cardre.calculate_woe_iv",
        ["explicit-missing-outlier-treatment", "manual-binning", "define-metadata"],
        {
            "purpose": "final",
            "smoothing": {
                "method": "additive",
                "alpha": 0.5,
                "rationale": "Acceptance fixture uses a tiny synthetic sample with sparse terminal bins",
            },
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
        "logistic-regression",
        "cardre.logistic_regression",
        ["woe-transform-train", "define-metadata", "variable-selection"],
        {},
    ),
    (
        "coefficient-sign-check",
        "cardre.coefficient_sign_check",
        ["logistic-regression", "final-woe-iv"],
        {},
    ),
    (
        "separation-diagnostics",
        "cardre.separation_diagnostics",
        ["logistic-regression"],
        {},
    ),
    (
        "vif-diagnostics",
        "cardre.vif_diagnostics",
        ["woe-transform-train", "logistic-regression"],
        {},
    ),
    (
        "score-scaling",
        "cardre.score_scaling",
        [
            "logistic-regression",
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
        ["score-scaling", "logistic-regression", "final-woe-iv"],
        {},
    ),
    (
        "freeze-scorecard-bundle",
        "cardre.freeze_scorecard_bundle",
        [
            "score-scaling",
            "logistic-regression",
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
        ["apply-woe", "logistic-regression", "score-scaling", "freeze-scorecard-bundle"],
        {},
    ),
    (
        "calibration-diagnostics",
        "cardre.calibration_diagnostics",
        ["apply-model", "logistic-regression", "define-metadata"],
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
        ["freeze-scorecard-bundle", "logistic-regression", "score-scaling", "apply-model", "manual-binning", "final-woe-iv"],
        {},
    ),
    (
        "scoring-export-sql",
        "cardre.scoring_export_sql",
        ["freeze-scorecard-bundle", "logistic-regression", "score-scaling", "apply-model", "manual-binning", "final-woe-iv"],
        {},
    ),
    (
        "technical-manifest-stub",
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


def build_canonical_scorecard_steps(source_path: str | Path) -> list[StepSpec]:
    registry = NodeRegistry.with_defaults()
    resolved_source_path = str(source_path)
    result: list[StepSpec] = []

    for position, (step_id, node_type, parent_step_ids, raw_params) in enumerate(_CANONICAL_SCORECARD_STEPS):
        params = dict(raw_params)
        if step_id == "import":
            params["source_path"] = resolved_source_path
        node_cls = registry.resolve(node_type)
        result.append(
            StepSpec(
                step_id=step_id,
                node_type=node_type,
                node_version=node_cls.version,
                category=node_cls.category,
                params=params,
                params_hash=json_logical_hash(params),
                parent_step_ids=list(parent_step_ids),
                position=position,
                canonical_step_id=step_id,
            )
        )

    return result


__all__ = ["build_canonical_scorecard_steps", "canonical_scorecard_step_ids"]
