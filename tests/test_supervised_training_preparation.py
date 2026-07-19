"""Tests for the deepened supervised training preparation module.

Exercises ``SupervisedTrainingData`` and ``resolve_supervised_feature_columns``
with real DataFrames and constructed instances. Full ``ExecutionContext``
integration is exercised through existing executor and classifier tests.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from cardre.nodes._training_utils import (
    SupervisedTrainingData,
    resolve_supervised_feature_columns,
)

# ---------------------------------------------------------------------------
# Example frames
# ---------------------------------------------------------------------------


def _example_frame() -> pl.DataFrame:
    return pl.DataFrame({
        "numeric_feature": [1.0, 2.0, 3.0, 4.0, 5.0],
        "second_feature": [10, 20, 30, 40, 50],
        "target": ["good", "bad", "good", "bad", "good"],
        "_is_synthetic_row": [False, False, True, False, False],
        "_governance_marker": [0, 1, 0, 1, 0],
    })


# ---------------------------------------------------------------------------
# resolve_supervised_feature_columns
# ---------------------------------------------------------------------------


class TestResolveSupervisedFeatureColumns:
    """Feature resolution enforces target, internal, and numeric rules."""

    def test_excludes_target_column(self):
        df = _example_frame()
        features = resolve_supervised_feature_columns(
            df, target_column="target", params={},
        )
        assert "target" not in features

    def test_excludes_internal_columns(self):
        df = _example_frame()
        features = resolve_supervised_feature_columns(
            df, target_column="target", params={},
        )
        assert "_is_synthetic_row" not in features
        assert "_governance_marker" not in features

    def test_rejects_internal_explicit_include(self):
        df = _example_frame()
        with pytest.raises(ValueError, match="internal columns"):
            resolve_supervised_feature_columns(
                df, target_column="target",
                params={"include_columns": ["numeric_feature", "_is_synthetic_row"]},
            )

    def test_explicit_exclude_removes_feature(self):
        df = _example_frame()
        features = resolve_supervised_feature_columns(
            df, target_column="target",
            params={"exclude_columns": ["second_feature"]},
        )
        assert "second_feature" not in features
        assert "numeric_feature" in features

    def test_missing_include_columns_raises(self):
        df = _example_frame()
        with pytest.raises(ValueError, match="missing columns"):
            resolve_supervised_feature_columns(
                df, target_column="target",
                params={"include_columns": ["nonexistent"]},
            )

    def test_non_numeric_included_raises(self):
        df = _example_frame().with_columns(
            pl.Series("category_col", ["a", "b", "c", "d", "e"]),
        )
        with pytest.raises(ValueError, match="Non-numeric"):
            resolve_supervised_feature_columns(
                df, target_column="target",
                params={"include_columns": ["category_col"]},
            )

    def test_numeric_only_after_exclusions(self):
        """Non-numeric columns are not selected by default."""
        df = _example_frame().with_columns(
            pl.Series("category_col", ["a", "b", "c", "d", "e"]),
        )
        features = resolve_supervised_feature_columns(
            df, target_column="target", params={},
        )
        assert "category_col" not in features

    def test_no_features_remaining_raises(self):
        df = pl.DataFrame({"target": ["good", "bad"], "_internal": [1, 2]})
        with pytest.raises(ValueError, match="No numeric"):
            resolve_supervised_feature_columns(
                df, target_column="target", params={},
            )


# ---------------------------------------------------------------------------
# SupervisedTrainingData
# ---------------------------------------------------------------------------


class TestSupervisedTrainingData:
    """SupervisedTrainingData.feature_columns delegates correctly."""

    def test_feature_columns_excludes_target_and_internals(self):
        df = _example_frame()
        data = SupervisedTrainingData(
            frame=df,
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
            y_binary=np.array([0, 1, 0, 1, 0]),
            metadata=None,
        )
        features = data.feature_columns({})
        assert "target" not in features
        assert "_is_synthetic_row" not in features
        assert "_governance_marker" not in features
        assert "numeric_feature" in features
        assert "second_feature" in features

    def test_feature_columns_applies_exclusions(self):
        df = _example_frame()
        data = SupervisedTrainingData(
            frame=df,
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
            y_binary=np.array([0, 1, 0, 1, 0]),
            metadata=None,
        )
        features = data.feature_columns({"exclude_columns": ["second_feature"]})
        assert "second_feature" not in features
