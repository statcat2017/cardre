from __future__ import annotations

import polars as pl
import pytest

from cardre.modeling.target import TargetSpec
from cardre.nodes.validate.metrics import ValidationMetricsNode


def _target_metadata() -> TargetSpec:
    return TargetSpec(
        target_column="credit_risk_class",
        good_values=frozenset({"good"}),
        bad_values=frozenset({"bad"}),
    )


def _dataset(*, include_score: bool, include_probability: bool) -> pl.DataFrame:
    payload: dict[str, list[object]] = {
        "credit_risk_class": ["good", "bad", "good", "bad"],
    }
    if include_probability:
        payload["predicted_bad_probability"] = [0.1, 0.8, 0.2, 0.9]
    if include_score:
        payload["score"] = [700.0, 550.0, 680.0, 530.0]
    return pl.DataFrame(payload)


def test_validation_metrics_step_fails_when_test_sample_required_but_missing(node_harness):
    with pytest.raises(Exception, match="TEST_SAMPLE_PRESENT"):
        node_harness(
            ValidationMetricsNode,
            frames={"train": _dataset(include_score=True, include_probability=True)},
            target_metadata=_target_metadata(),
            params={
                "require_test": True,
                "require_oot": False,
                "fail_on_missing_score": True,
                "fail_on_missing_target": True,
            },
        )


def test_validation_metrics_step_fails_when_score_column_missing(node_harness):
    with pytest.raises(Exception, match="NO_MISSING_SCORE"):
        node_harness(
            ValidationMetricsNode,
            frames={
                "train": _dataset(include_score=False, include_probability=True),
                "test": _dataset(include_score=False, include_probability=True),
            },
            target_metadata=_target_metadata(),
            params={
                "require_test": True,
                "require_oot": False,
                "fail_on_missing_score": True,
                "fail_on_missing_target": True,
            },
        )
