"""Pathway definitions auto-registered on project creation.

Uses the canonical PathwaySpec builder from cardre.pathway.
"""

from __future__ import annotations

from cardre.pathway import PathwaySpec, PathwayStepSpec, build_pathway_steps
from cardre.store import ProjectStore


PROOF_PATHWAY = PathwaySpec(
    name="Proof Pathway",
    description="Minimal proof-of-concept pathway",
    phases=[[
        PathwayStepSpec("import", "cardre.import_dataset"),
        PathwayStepSpec("profile", "cardre.profile_dataset", parent_step_ids=["import"]),
        PathwayStepSpec("validate-target", "cardre.validate_binary_target",
                        params={"target_column": ""},
                        parent_step_ids=["import"]),
        PathwayStepSpec("split", "cardre.split_train_test_oot", node_version="2",
                        params={
                            "train_fraction": 0.6, "test_fraction": 0.2,
                            "oot_fraction": 0.2, "strategy": "random_stratified",
                            "target_column": "", "role_column": None,
                            "random_seed": 42,
                        },
                        parent_step_ids=["import"]),
        PathwayStepSpec("dummy-fit", "cardre.dummy_fit", category="fit",
                        parent_step_ids=["split"]),
        PathwayStepSpec("dummy-apply", "cardre.dummy_apply", category="apply",
                        parent_step_ids=["split", "dummy-fit"]),
    ]],
)


SCORECARD_PATHWAY = PathwaySpec(
    name="Scorecard Pathway",
    description="Full credit scorecard development pathway (Phase 2A + 2B + 2C + Manifest)",
    phases=[

        # Phase 2A: Import through Variable Clustering/Selection
        [
            PathwayStepSpec("import", "cardre.import_dataset"),
            PathwayStepSpec("define-metadata", "cardre.define_modelling_metadata",
                            params={
                                "target_column": "",
                                "good_values": [], "bad_values": [],
                                "indeterminate_values": [],
                                "population": "", "product": "", "segment": "",
                                "observation_window": None, "performance_window": None,
                            },
                            parent_step_ids=["import"]),
            PathwayStepSpec("apply-exclusions", "cardre.apply_exclusions",
                            params={"rules": []},
                            parent_step_ids=["import", "define-metadata"]),
            PathwayStepSpec("profile", "cardre.profile_dataset",
                            parent_step_ids=["apply-exclusions"]),
            PathwayStepSpec("validate-target", "cardre.validate_binary_target",
                            params={"target_column": ""},
                            parent_step_ids=["apply-exclusions", "define-metadata"]),
            PathwayStepSpec("sample-definition", "cardre.development_sample_definition",
                            params={
                                "sample_method": "full_population",
                                "weight_column": None,
                                "population_bad_rate": None,
                                "prior_probability_adjustment": None,
                            },
                            parent_step_ids=["apply-exclusions", "define-metadata"]),
            PathwayStepSpec("split", "cardre.split_train_test_oot", node_version="2",
                            params={
                                "strategy": "random_stratified",
                                "train_fraction": 0.6, "test_fraction": 0.2,
                                "oot_fraction": 0.2,
                                "target_column": "",
                                "role_column": None, "random_seed": 42,
                            },
                            parent_step_ids=["apply-exclusions", "sample-definition"]),
            PathwayStepSpec("explicit-missing-outlier-treatment",
                            "cardre.explicit_missing_outlier_treatment", category="apply",
                            params={"imputations": {}, "caps": {}, "floors": {}},
                            parent_step_ids=["split"]),
            PathwayStepSpec("binning", "cardre.binning", category="fit",
                            params={
                                "method": "fine_classing",
                                "max_bins": 20, "min_bin_fraction": 0.05,
                                "missing_policy": "separate_bin",
                                "max_categorical_levels": 50, "exclude_columns": [],
                            },
                            parent_step_ids=["explicit-missing-outlier-treatment", "define-metadata"]),
            PathwayStepSpec("initial-woe-iv", "cardre.calculate_woe_iv", category="selection",
                            params={"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"},
                            parent_step_ids=["explicit-missing-outlier-treatment", "binning", "define-metadata"]),
            PathwayStepSpec("variable-clustering", "cardre.variable_clustering", category="selection",
                            params={"correlation_threshold": 0.7, "candidate_limit": 50},
                            parent_step_ids=["explicit-missing-outlier-treatment", "initial-woe-iv"]),
            PathwayStepSpec("variable-selection", "cardre.variable_selection", category="selection",
                            params={
                                "min_iv": 0.02, "max_variables": 15,
                                "manual_includes": [], "manual_excludes": [],
                            },
                            parent_step_ids=["initial-woe-iv", "variable-clustering"]),
            PathwayStepSpec("manual-binning", "cardre.manual_binning", category="refinement",
                            params={"overrides": []},
                            parent_step_ids=["binning", "variable-selection"]),
            PathwayStepSpec("final-woe-iv", "cardre.calculate_woe_iv", category="selection",
                            params={
                                "zero_cell_policy": "block",
                                "smoothing": {
                                    "method": "additive", "alpha": 0.5,
                                    "rationale": "Default smoothing to ensure the auto-registered pathway is runnable on realistic data without manual binning edits.",
                                },
                                "purpose": "final",
                            },
                            parent_step_ids=["explicit-missing-outlier-treatment", "manual-binning", "define-metadata"]),
        ],

        # Phase 2B: WOE transform, logistic regression, score scaling, summary report
        [
            PathwayStepSpec("woe-transform-train", "cardre.woe_transform_train", category="fit",
                            parent_step_ids=["explicit-missing-outlier-treatment", "manual-binning", "final-woe-iv", "variable-selection"]),
            PathwayStepSpec("logistic-regression", "cardre.logistic_regression", category="fit",
                            params={"C": 1.0, "max_iter": 1000, "solver": "lbfgs", "random_seed": 42},
                            parent_step_ids=["woe-transform-train", "define-metadata"]),
            PathwayStepSpec("score-scaling", "cardre.score_scaling", category="fit",
                            params={
                                "base_score": 600, "base_odds": 50.0,
                                "points_to_double_odds": 20, "higher_score_is_lower_risk": True,
                            },
                            parent_step_ids=["logistic-regression", "manual-binning", "final-woe-iv"]),
            PathwayStepSpec("build-summary-report", "cardre.build_summary_report", category="fit",
                            parent_step_ids=["score-scaling", "logistic-regression", "final-woe-iv"]),
            PathwayStepSpec("freeze-scorecard-bundle", "cardre.freeze_scorecard_bundle", category="fit",
                            parent_step_ids=["logistic-regression", "score-scaling", "manual-binning", "final-woe-iv", "define-metadata", "variable-selection"]),
        ],

        # Phase 2C: Apply WOE, apply model, validation, cutoff analysis
        [
            PathwayStepSpec("apply-woe", "cardre.apply_woe_mapping", category="apply",
                            parent_step_ids=["explicit-missing-outlier-treatment", "manual-binning", "final-woe-iv", "freeze-scorecard-bundle", "variable-selection"]),
            PathwayStepSpec("apply-model", "cardre.apply_model", category="apply",
                            parent_step_ids=["apply-woe", "logistic-regression", "score-scaling", "freeze-scorecard-bundle"]),
            PathwayStepSpec("validation-metrics", "cardre.validation_metrics", category="apply",
                            parent_step_ids=["apply-model", "define-metadata", "freeze-scorecard-bundle"]),
            PathwayStepSpec("cutoff-analysis", "cardre.cutoff_analysis", category="apply",
                            params={"band_count": 20},
                            parent_step_ids=["apply-model", "validation-metrics"]),
        ],

        # Technical Manifest (placed last, depends on all prior steps)
        [
            PathwayStepSpec("technical-manifest-stub", "cardre.technical_manifest_export",
                            parent_step_ids=[
                                "define-metadata", "sample-definition", "split",
                                "explicit-missing-outlier-treatment", "binning",
                                "variable-selection", "manual-binning", "final-woe-iv",
                                "woe-transform-train", "logistic-regression", "score-scaling",
                                "build-summary-report", "freeze-scorecard-bundle", "apply-woe", "apply-model",
                                "validation-metrics", "cutoff-analysis",
                            ]),
        ],
    ],
)


def register_proof_pathway(store: ProjectStore, project_id: str) -> str:
    """Register the proof pathway plan in the given project."""
    plan_id = store.create_plan(project_id, PROOF_PATHWAY.name)
    steps = build_pathway_steps(PROOF_PATHWAY)
    store.create_plan_version(plan_id, steps, description=f"Auto-registered {PROOF_PATHWAY.name}")
    return plan_id


def register_scorecard_pathway(store: ProjectStore, project_id: str) -> str:
    """Register the full scorecard pathway in the given project."""
    plan_id = store.create_plan(project_id, SCORECARD_PATHWAY.name)
    steps = build_pathway_steps(SCORECARD_PATHWAY)
    store.create_plan_version(plan_id, steps, description=f"Auto-registered {SCORECARD_PATHWAY.name}")
    return plan_id
