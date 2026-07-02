from __future__ import annotations

from cardre.domain.artifacts import params_hash
from cardre.domain.step import StepSpec


def test_step_spec_round_trips_and_defaults_canonical_id() -> None:
    spec = StepSpec(
        step_id="step-a",
        node_type="cardre.example",
        node_version="1",
        category="analysis",
        params={"alpha": 1},
        params_hash=params_hash({"alpha": 1}),
        parent_step_ids=["parent-a"],
    )

    assert spec.canonical_step_id == "step-a"
    assert StepSpec.from_dict(spec.to_dict()) == spec


def test_step_spec_from_dict_derives_missing_hash() -> None:
    spec = StepSpec.from_dict(
        {
            "step_id": "step-b",
            "node_type": "cardre.example",
            "node_version": "1",
            "category": "analysis",
            "params": {"beta": 2},
            "parent_step_ids": [],
        }
    )

    assert spec.params_hash == params_hash({"beta": 2})
