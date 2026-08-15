"""Tests for sampling provenance — ``_is_synthetic_row`` materialisation.

Exercises random resampling and SMOTE through their Node ``run()`` methods
via the node harness.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import polars as pl
import pytest

from cardre.modeling.target import TargetSpec
from cardre.nodes.selection import ResampleTrainingDataNode, SmoteTrainingDataNode


def _make_imbalanced_frame() -> pl.DataFrame:
    """Return a train frame with 80 good / 20 bad rows and deterministic IDs."""
    rng = np.random.RandomState(42)
    n_good = 80
    n_bad = 20
    target_data = ["good"] * n_good + ["bad"] * n_bad
    rng.shuffle(target_data)
    return pl.DataFrame({
        "row_id": list(range(100)),
        "feature_a": rng.randn(100).tolist(),
        "feature_b": rng.randn(100).tolist(),
        "target": target_data,
    })


def _target_metadata() -> TargetSpec:
    return TargetSpec(
        target_column="target",
        good_values=frozenset({"good"}),
        bad_values=frozenset({"bad"}),
    )


class TestRandomResamplingProvenance:
    """Random resampling writes _is_synthetic_row correctly."""

    def _run(self, node_harness, params):
        return node_harness(
            ResampleTrainingDataNode,
            frames={"train": _make_imbalanced_frame()},
            target_metadata=_target_metadata(),
            params=params,
        )

    def test_oversample_writes_flag_column(self, node_harness):
        out = self._run(node_harness, {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        train_art = next(a for a in out.staged if a.role == "train")
        df = train_art.payload
        assert "_is_synthetic_row" in df.columns
        n_synthetic = int(df["_is_synthetic_row"].sum())
        assert n_synthetic > 0
        # oversample_minority from 20 bad -> 80 bad = 60 extra
        assert n_synthetic == 60

    def test_oversample_synthetic_matches_report(self, node_harness):
        out = self._run(node_harness, {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        train_art = next(a for a in out.staged if a.role == "train")
        df = train_art.payload
        n_synthetic = int(df["_is_synthetic_row"].sum())
        assert n_synthetic == out.metrics.get("synthetic_count", -1)

    def test_undersample_all_false(self, node_harness):
        out = self._run(node_harness, {"strategy": "undersample_majority", "sampling_ratio": 0.5})
        train_art = next(a for a in out.staged if a.role == "train")
        df = train_art.payload
        assert "_is_synthetic_row" in df.columns
        assert df["_is_synthetic_row"].sum() == 0

    def test_original_rows_are_false(self, node_harness):
        """Every original selected row is False; only extra duplicates are True."""
        out = self._run(node_harness, {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        train_art = next(a for a in out.staged if a.role == "train")
        df = train_art.payload

        n_false = int((df["_is_synthetic_row"] == False).sum())  # noqa: E712
        n_true = int(df["_is_synthetic_row"].sum())
        assert n_false + n_true == len(df)
        # Exactly 60 extra minority rows (from 20 to 80 bad)
        assert n_true == 60
        assert n_false == 100

        # Every True row has a row_id from an original bad row
        distinct_true_ids = set(df.filter(pl.col("_is_synthetic_row"))["row_id"].to_list())
        for rid in distinct_true_ids:
            df_has_false = df.filter((pl.col("row_id") == rid) & (~pl.col("_is_synthetic_row")))
            assert len(df_has_false) > 0, f"row_id {rid} has no False copy"

    def test_chained_resampling_preserves_incoming(self, node_harness):
        """Running oversampling on an already-resampled artifact preserves
        the incoming _is_synthetic_row=True for previously added rows."""
        first = self._run(node_harness, {"strategy": "oversample_minority", "sampling_ratio": 1.0})
        first_art = next(a for a in first.staged if a.role == "train")
        first_df = first_art.payload
        first_synthetic = int(first_df["_is_synthetic_row"].sum())
        assert first_synthetic == 60

        # Second pass: feed the resampled artifact back as train input.
        second = node_harness(
            ResampleTrainingDataNode,
            frames={"train": first_df},
            target_metadata=_target_metadata(),
            params={"strategy": "undersample_majority", "sampling_ratio": 0.5},
        )
        second_art = next(a for a in second.staged if a.role == "train")
        second_df = second_art.payload
        second_synthetic = int(second_df["_is_synthetic_row"].sum())
        # The second pass should NOT add new synthetic rows (undersample),
        # and should preserve the incoming 60 True values.
        assert second_synthetic >= 60, (
            f"Expected at least {first_synthetic} synthetic rows preserved, "
            f"got {second_synthetic}"
        )


class TestSmoteProvenance:
    """SMOTE writes _is_synthetic_row correctly when imblearn is available."""

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_writes_flag_column(self, node_harness):
        out = node_harness(
            SmoteTrainingDataNode,
            frames={"train": _make_imbalanced_frame()},
            target_metadata=_target_metadata(),
            params={"sampling_ratio": 1.0},
        )
        train_art = next(a for a in out.staged if a.role == "train")
        df = train_art.payload
        assert "_is_synthetic_row" in df.columns
        assert df["_is_synthetic_row"].sum() > 0

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_synthetic_matches_report(self, node_harness):
        out = node_harness(
            SmoteTrainingDataNode,
            frames={"train": _make_imbalanced_frame()},
            target_metadata=_target_metadata(),
            params={"sampling_ratio": 1.0},
        )
        train_art = next(a for a in out.staged if a.role == "train")
        df = train_art.payload
        assert df["_is_synthetic_row"].sum() == out.metrics.get("synthetic_count", -1)

    @pytest.mark.skipif(
        not importlib.util.find_spec("imblearn"),
        reason="SMOTE requires imbalanced-learn",
    )
    def test_smote_original_rows_are_false(self, node_harness):
        out = node_harness(
            SmoteTrainingDataNode,
            frames={"train": _make_imbalanced_frame()},
            target_metadata=_target_metadata(),
            params={"sampling_ratio": 1.0},
        )
        train_art = next(a for a in out.staged if a.role == "train")
        df = train_art.payload
        n_original = 100  # original rows in fixture
        first_rows = df.head(n_original)
        assert first_rows["_is_synthetic_row"].sum() == 0
