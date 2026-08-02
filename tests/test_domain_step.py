from __future__ import annotations

import dataclasses

import pytest

from cardre.domain.artifacts import params_hash
from cardre.domain.step import StepSpec


def test_step_spec_round_trips() -> None:
    spec = StepSpec(
        step_id="step-a",
        node_type="cardre.example",
        node_version="1",
        category="analysis",
        params={"alpha": 1},
        params_hash=params_hash({"alpha": 1}),
        parent_step_ids=["parent-a"],
        canonical_step_id="step-a",
    )
    assert spec.canonical_step_id == "step-a"
    assert spec.to_dict()["canonical_step_id"] == "step-a"


def test_step_spec_requires_canonical_step_id() -> None:
    with pytest.raises(TypeError, match="canonical_step_id"):
        StepSpec(
            step_id="step-b",
            node_type="cardre.example",
            node_version="1",
            category="analysis",
            params={"beta": 2},
            params_hash=params_hash({"beta": 2}),
            parent_step_ids=[],
        )


def test_step_spec_is_frozen() -> None:
    spec = StepSpec(
        step_id="step-c",
        node_type="cardre.example",
        node_version="1",
        category="analysis",
        params={},
        params_hash="h",
        parent_step_ids=[],
        canonical_step_id="step-c",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.step_id = "other"  # type: ignore[misc]
