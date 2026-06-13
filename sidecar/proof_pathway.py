"""Hardcoded proof pathway and Phase 2A scorecard pathway plan auto-registered on project creation."""

from __future__ import annotations

from cardre.audit import StepSpec, json_logical_hash
from cardre.store import ProjectStore


PROOF_PATHWAY_STEPS_CONFIG = [
    {
        "step_id": "import",
        "node_type": "cardre.import_dataset",
        "node_version": "1",
        "category": "transform",
        "params": {},
        "parent_step_ids": [],
        "branch_label": "",
    },
    {
        "step_id": "profile",
        "node_type": "cardre.profile_dataset",
        "node_version": "1",
        "category": "transform",
        "params": {},
        "parent_step_ids": ["import"],
        "branch_label": "",
    },
    {
        "step_id": "validate-target",
        "node_type": "cardre.validate_binary_target",
        "node_version": "1",
        "category": "transform",
        "params": {"target_column": "credit_risk_class"},
        "parent_step_ids": ["import"],
        "branch_label": "",
    },
    {
        "step_id": "split",
        "node_type": "cardre.split_train_test_oot",
        "node_version": "2",
        "category": "transform",
        "params": {
            "train_fraction": 0.6,
            "test_fraction": 0.2,
            "oot_fraction": 0.2,
            "strategy": "random_stratified",
            "target_column": "credit_risk_class",
            "role_column": None,
            "random_seed": 42,
        },
        "parent_step_ids": ["import"],
        "branch_label": "",
    },
    {
        "step_id": "dummy-fit",
        "node_type": "cardre.dummy_fit",
        "node_version": "1",
        "category": "fit",
        "params": {},
        "parent_step_ids": ["split"],
        "branch_label": "",
    },
    {
        "step_id": "dummy-apply",
        "node_type": "cardre.dummy_apply",
        "node_version": "1",
        "category": "apply",
        "params": {},
        "parent_step_ids": ["split", "dummy-fit"],
        "branch_label": "",
    },
]

PHASE2A_PATHWAY_STEPS_CONFIG = [
    {
        "step_id": "import",
        "node_type": "cardre.import_dataset",
        "node_version": "1",
        "category": "transform",
        "params": {},
        "parent_step_ids": [],
        "branch_label": "",
    },
    {
        "step_id": "define-metadata",
        "node_type": "cardre.define_modelling_metadata",
        "node_version": "1",
        "category": "transform",
        "params": {
            "target_column": "credit_risk_class",
            "good_values": ["1"],
            "bad_values": ["2"],
            "indeterminate_values": [],
            "population": "",
            "product": "",
            "segment": "",
            "observation_window": None,
            "performance_window": None,
        },
        "parent_step_ids": ["import"],
        "branch_label": "",
    },
    {
        "step_id": "apply-exclusions",
        "node_type": "cardre.apply_exclusions",
        "node_version": "1",
        "category": "transform",
        "params": {"rules": []},
        "parent_step_ids": ["import", "define-metadata"],
        "branch_label": "",
    },
    {
        "step_id": "profile",
        "node_type": "cardre.profile_dataset",
        "node_version": "1",
        "category": "transform",
        "params": {},
        "parent_step_ids": ["apply-exclusions"],
        "branch_label": "",
    },
    {
        "step_id": "validate-target",
        "node_type": "cardre.validate_binary_target",
        "node_version": "1",
        "category": "transform",
        "params": {"target_column": "credit_risk_class"},
        "parent_step_ids": ["apply-exclusions", "define-metadata"],
        "branch_label": "",
    },
    {
        "step_id": "sample-definition",
        "node_type": "cardre.development_sample_definition",
        "node_version": "1",
        "category": "transform",
        "params": {
            "sample_method": "full_population",
            "weight_column": None,
            "population_bad_rate": None,
            "prior_probability_adjustment": None,
        },
        "parent_step_ids": ["apply-exclusions", "define-metadata"],
        "branch_label": "",
    },
    {
        "step_id": "split",
        "node_type": "cardre.split_train_test_oot",
        "node_version": "2",
        "category": "transform",
        "params": {
            "strategy": "random_stratified",
            "train_fraction": 0.6,
            "test_fraction": 0.2,
            "oot_fraction": 0.2,
            "target_column": "credit_risk_class",
            "role_column": None,
            "random_seed": 42,
        },
        "parent_step_ids": ["apply-exclusions", "sample-definition"],
        "branch_label": "",
    },
    {
        "step_id": "explicit-missing-outlier-treatment",
        "node_type": "cardre.explicit_missing_outlier_treatment",
        "node_version": "1",
        "category": "apply",
        "params": {
            "imputations": {},
            "caps": {},
            "floors": {},
        },
        "parent_step_ids": ["split"],
        "branch_label": "",
    },
    {
        "step_id": "fine-classing",
        "node_type": "cardre.fine_classing",
        "node_version": "1",
        "category": "fit",
        "params": {
            "max_bins": 20,
            "min_bin_fraction": 0.05,
            "missing_policy": "separate_bin",
            "max_categorical_levels": 50,
            "exclude_columns": [],
        },
        "parent_step_ids": ["explicit-missing-outlier-treatment", "define-metadata"],
        "branch_label": "",
    },
    {
        "step_id": "initial-woe-iv",
        "node_type": "cardre.calculate_woe_iv",
        "node_version": "1",
        "category": "selection",
        "params": {
            "zero_cell_policy": "block",
            "smoothing": None,
            "purpose": "initial",
        },
        "parent_step_ids": ["explicit-missing-outlier-treatment", "fine-classing", "define-metadata"],
        "branch_label": "",
    },
    {
        "step_id": "variable-clustering",
        "node_type": "cardre.variable_clustering",
        "node_version": "1",
        "category": "selection",
        "params": {
            "correlation_threshold": 0.7,
            "candidate_limit": 50,
        },
        "parent_step_ids": ["explicit-missing-outlier-treatment", "initial-woe-iv"],
        "branch_label": "",
    },
    {
        "step_id": "variable-selection",
        "node_type": "cardre.variable_selection",
        "node_version": "1",
        "category": "selection",
        "params": {
            "min_iv": 0.02,
            "max_variables": 15,
            "manual_includes": [],
            "manual_excludes": [],
        },
        "parent_step_ids": ["initial-woe-iv", "variable-clustering"],
        "branch_label": "",
    },
    {
        "step_id": "manual-binning",
        "node_type": "cardre.manual_binning",
        "node_version": "1",
        "category": "refinement",
        "params": {"overrides": []},
        "parent_step_ids": ["fine-classing", "variable-selection"],
        "branch_label": "",
    },
    {
        "step_id": "final-woe-iv",
        "node_type": "cardre.calculate_woe_iv",
        "node_version": "1",
        "category": "selection",
        "params": {
            "zero_cell_policy": "block",
            "smoothing": None,
            "purpose": "final",
        },
        "parent_step_ids": ["explicit-missing-outlier-treatment", "manual-binning", "define-metadata"],
        "branch_label": "",
    },
    {
        "step_id": "technical-manifest-stub",
        "node_type": "cardre.technical_manifest_export",
        "node_version": "1",
        "category": "transform",
        "params": {},
        "parent_step_ids": [
            "define-metadata",
            "sample-definition",
            "split",
            "explicit-missing-outlier-treatment",
            "fine-classing",
            "variable-selection",
            "manual-binning",
            "final-woe-iv",
        ],
        "branch_label": "",
    },
]


def _build_steps(config: list[dict]) -> list[StepSpec]:
    steps = []
    for i, c in enumerate(config):
        params = dict(c["params"])
        steps.append(
            StepSpec(
                step_id=c["step_id"],
                node_type=c["node_type"],
                node_version=c["node_version"],
                category=c["category"],
                params=params,
                params_hash=json_logical_hash(params),
                parent_step_ids=list(c["parent_step_ids"]),
                branch_label=c.get("branch_label", ""),
                position=i,
            )
        )
    return steps


def register_proof_pathway(store: ProjectStore, project_id: str) -> str:
    """Register the proof pathway plan in the given project."""
    plan_id = store.create_plan(project_id, "Proof Pathway")
    steps = _build_steps(PROOF_PATHWAY_STEPS_CONFIG)
    store.create_plan_version(plan_id, steps, description="Auto-registered proof pathway")
    return plan_id


def register_scorecard_pathway(store: ProjectStore, project_id: str) -> str:
    """Register the Phase 2A scorecard pathway in the given project."""
    plan_id = store.create_plan(project_id, "Scorecard Pathway")
    steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG)
    store.create_plan_version(plan_id, steps, description="Auto-registered Phase 2A scorecard pathway")
    return plan_id
