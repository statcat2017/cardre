"""Pure helper functions for logistic regression and score scaling nodes.

These consolidate duplicated parsing/logic from ``LogisticRegressionNode``,
``ScoreScalingNode``, and ``BuildSummaryReportNode`` into testable pure
functions.
"""

from __future__ import annotations

from typing import Any

# ------------------------------------------------------------------
# Named rounding constants
# ------------------------------------------------------------------
WOE_ROUND = 6
POINTS_ROUND = 2
COEF_ROUND = 6


# ------------------------------------------------------------------
# Base-odds parsing
# ------------------------------------------------------------------

def parse_base_odds(raw: Any) -> float:
    """Parse *raw* base-odds into a ``float``.

    Accepts:

    * ``"N:M"`` string format (e.g. ``"50:1"`` → ``50.0``)
    * Plain number string (e.g. ``"50"`` → ``50.0``)
    * Numeric input (e.g. ``50.0`` → ``50.0``)

    Raises ``ValueError`` for unparseable inputs (``"abc"``, ``None``,
    empty string, zero-division).  Callers are responsible for checking
    positivity — this function returns ``0.0`` for ``"0:1"``.
    """
    if isinstance(raw, str) and ":" in raw:
        try:
            num, den = raw.split(":", 1)
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            raise ValueError(
                f"base_odds must be a number or 'N:M' odds ratio string, got {raw!r}"
            ) from None
    try:
        return float(raw)
    except (ValueError, TypeError):
        raise ValueError(
            f"base_odds must be a number or 'N:M' odds ratio string, got {raw!r}"
        ) from None


# ------------------------------------------------------------------
# sklearn LogisticRegression parameter preparation
# ------------------------------------------------------------------

def build_lr_params(params: dict[str, Any]) -> dict[str, Any]:
    """Prepare sklearn ``LogisticRegression`` kwargs from *params*.

    Defaults: ``penalty="l2"``, ``C=1.0``, ``max_iter=1000``,
    ``solver="lbfgs"``, ``random_state=42``.
    """
    penalty = params.get("penalty")
    if penalty is None:
        penalty = "l2"
    return {
        "penalty": penalty,
        "C": float(params.get("C", 1.0)),
        "max_iter": int(params.get("max_iter", 1000)),
        "solver": str(params.get("solver", "lbfgs")),
        "random_state": int(params.get("random_seed", 42)),
    }


# ------------------------------------------------------------------
# Feature / source-variable resolution
# ------------------------------------------------------------------

def resolve_features(
    woe_cols: list[str],
    sel_def: Any | None,
) -> tuple[list[str], list[str]]:
    """Resolve ``(features_list, source_variables)``.

    *features_list* is the list of WOE column names (unchanged).

    *source_variables* comes from ``sel_def.selected_names`` when
    *sel_def* is not ``None``, otherwise derived by stripping the
    ``_woe`` suffix from each column name.
    """
    features_list = woe_cols
    if sel_def is not None:
        source_variables = list(sel_def.selected_names)
    else:
        source_variables = (
            [f[:-4] for f in features_list if f.endswith("_woe")]
            if features_list
            else []
        )
    return features_list, source_variables


# ------------------------------------------------------------------
# Class mapping
# ------------------------------------------------------------------

def build_class_mapping(good_class: str, bad_class: str) -> dict[str, str]:
    """Build the ``{"good": …, "bad": …}`` class-mapping dict.

    .. note::
       ``_behavior_preserved`` — both branches of the original
       ``if bad_class_idx == 0`` produced the same dict.  This is
       preserved intentionally and is **not** a bug fix.
    """
    return {"good": str(good_class), "bad": str(bad_class)}


# ------------------------------------------------------------------
# Scorecard attribute building
# ------------------------------------------------------------------

def build_scorecard_attribute(
    variable: str,
    bin_entry: dict[str, Any],
    woe_val: float,
    coef: float,
    factor: float,
    direction: float,
) -> dict[str, Any]:
    """Build a single scorecard attribute dict.

    Rounds ``woe`` to ``WOE_ROUND`` (6) and ``points`` to
    ``POINTS_ROUND`` (2).
    """
    raw_points = direction * factor * coef * woe_val
    return {
        "variable": variable,
        "bin_id": bin_entry["bin_id"],
        "label": bin_entry["label"],
        "woe": round(woe_val, WOE_ROUND),
        "coefficient": coef,
        "points": round(raw_points, POINTS_ROUND),
    }
