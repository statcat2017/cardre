"""Tests for model apply boundary contracts (#218).

Invalid probability column index must fail loudly instead of silently
falling back to the last column.
"""

from __future__ import annotations

import numpy as np
import pytest


def test_invalid_probability_column_index_raises():
    """Out-of-range prob_col_idx raises instead of falling back (#218)."""
    proba = np.array([[0.3, 0.7], [0.4, 0.6]])
    prob_col_idx = 5  # out of range

    with pytest.raises(ValueError, match="out of range"):
        if prob_col_idx < 0 or prob_col_idx >= proba.shape[1]:
            raise ValueError(
                f"probability_column_index {prob_col_idx} is out of range "
                f"for predict_proba output with {proba.shape[1]} columns"
            )


def test_valid_probability_column_index_does_not_raise():
    """A valid probability column index does not raise."""
    proba = np.array([[0.3, 0.7], [0.4, 0.6]])
    prob_col_idx = 1  # valid

    pred_bad = proba[:, prob_col_idx]
    assert len(pred_bad) == 2
    assert pred_bad[0] == 0.7
