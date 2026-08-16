"""Shared classifier payload helpers.

The six classifier nodes each build the same ``interpretability`` block and
repeat the same ``feature_strategy`` enum.  These helpers keep those shapes
in one place.
"""

from __future__ import annotations

from typing import Any

FEATURE_STRATEGIES = ("raw_numeric", "encoded_raw", "woe_challenger")


def interpretability_block(
    *,
    explanation_type: str,
    explanation_level: str,
    limitations: list[str],
    native_importance_available: bool = True,
) -> dict[str, Any]:
    """The standard interpretability dict for a classifier model artifact."""
    return {
        "explanation_type": explanation_type,
        "explanation_level": explanation_level,
        "native_importance_available": native_importance_available,
        "limitations": limitations,
        "global_importance_fields": ["feature_importance"],
    }
