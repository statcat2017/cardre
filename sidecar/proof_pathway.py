"""Hardcoded proof pathway plan auto-registered on project creation."""

from __future__ import annotations

from cardre.audit import StepSpec, json_logical_hash, params_hash
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
        "node_version": "1",
        "category": "transform",
        "params": {
            "train_fraction": 0.6,
            "test_fraction": 0.2,
            "oot_fraction": 0.2,
            "method": "random",
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


def register_proof_pathway(store: ProjectStore, project_id: str) -> str:
    """Register the proof pathway plan in the given project.

    Returns the plan_id.
    """
    plan_id = store.create_plan(project_id, "Proof Pathway")

    steps = []
    for i, config in enumerate(PROOF_PATHWAY_STEPS_CONFIG):
        params = dict(config["params"])
        steps.append(
            StepSpec(
                step_id=config["step_id"],
                node_type=config["node_type"],
                node_version=config["node_version"],
                category=config["category"],
                params=params,
                params_hash=json_logical_hash(params),
                parent_step_ids=list(config["parent_step_ids"]),
                branch_label=config.get("branch_label", ""),
                position=i,
            )
        )

    store.create_plan_version(plan_id, steps, description="Auto-registered proof pathway")
    return plan_id
