"""Phase 1 — domain step: StepSpec construction, params_hash stability."""

from cardre.domain.step import StepSpec
from cardre.domain.artifacts import json_logical_hash


def test_step_spec_minimal():
    """StepSpec can be constructed with minimal required args."""
    step = StepSpec(
        step_id="s1",
        node_type="cardre.import_dataset",
        node_version="1",
        category="import",
        params={},
        params_hash="dummy",
        parent_step_ids=[],
    )
    assert step.step_id == "s1"
    assert step.node_type == "cardre.import_dataset"
    assert step.branch_label == ""
    assert step.position == 0
    assert step.canonical_step_id == "s1"
    assert step.branch_id is None


def test_step_spec_canonical_step_id_default():
    """canonical_step_id defaults to step_id when not provided."""
    step = StepSpec(
        step_id="custom_id",
        node_type="test",
        node_version="1",
        category="test",
        params={},
        params_hash="h",
        parent_step_ids=[],
    )
    assert step.canonical_step_id == "custom_id"


def test_step_spec_canonical_step_id_explicit():
    """canonical_step_id can be overridden."""
    step = StepSpec(
        step_id="step_v2",
        node_type="test",
        node_version="1",
        category="test",
        params={},
        params_hash="h",
        parent_step_ids=[],
        canonical_step_id="import_dataset",
    )
    assert step.canonical_step_id == "import_dataset"


def test_step_spec_params_hash_stability():
    """Same params always produce the same hash via the explicit field."""
    params1 = {"method": "fine_classing", "min_bins": 5}
    params2 = {"min_bins": 5, "method": "fine_classing"}  # different key order
    h1 = json_logical_hash(params1)
    h2 = json_logical_hash(params2)
    assert h1 == h2
    step1 = StepSpec(
        step_id="s1", node_type="t", node_version="1", category="c",
        params=params1, params_hash=h1, parent_step_ids=[],
    )
    step2 = StepSpec(
        step_id="s2", node_type="t", node_version="1", category="c",
        params=params2, params_hash=h2, parent_step_ids=[],
    )
    assert step1.params_hash == step2.params_hash


def test_step_spec_to_dict_roundtrip():
    """StepSpec.to_dict() -> from_dict() preserves all fields."""
    step = StepSpec(
        step_id="s1",
        node_type="cardre.binning",
        node_version="1",
        category="binning",
        params={"method": "fine_classing"},
        params_hash=json_logical_hash({"method": "fine_classing"}),
        parent_step_ids=["import"],
        branch_label="main",
        position=2,
        canonical_step_id="binning_v1",
        branch_id="b1",
    )
    d = step.to_dict()
    restored = StepSpec.from_dict(d)
    assert restored == step


def test_step_spec_from_dict_defaults():
    """from_dict fills defaults for optional fields."""
    data = {
        "step_id": "s1",
        "node_type": "cardre.import",
        "node_version": "1",
        "category": "import",
        "params": {},
        "parent_step_ids": [],
        "params_hash": "h1",
    }
    step = StepSpec.from_dict(data)
    assert step.branch_label == ""
    assert step.position == 0
    assert step.canonical_step_id == "s1"
    assert step.branch_id is None
