"""Shared fixtures/helpers for the scoring-export node unit tests.

Only genuinely shared building blocks live here so the compiler/IR, generated
Python scorer, and SQL scorer test modules do not duplicate helper copies.
"""

from __future__ import annotations

from typing import Any

from cardre.domain.evidence.models.binning import BinDefinition, BinVariable
from cardre.domain.evidence.models.woe import WoeTable


def _exec_scorer(source: str):
    """Exec the generated scorer source and return the ``score_cardre`` callable."""
    local_ns: dict[str, Any] = {}
    exec(source, local_ns)
    return local_ns["score_cardre"]


def make_simple_numeric_agecard(coefficients: dict[str, float] | None = None):
    """Build the canonical single-bin numeric 'age' scorecard.

    Returns the ``(bin_def, woe_table, scorecard_raw, model_raw)`` tuple used
    verbatim by many unit tests: one 18-30 bin with WOE 0.3, a linear
    factor/offset scorecard, and a single (optionally overridden) logit
    coefficient for ``age_woe``.
    """
    bin_def = BinDefinition(
        source_artifact_id="test",
        variables=[
            BinVariable(
                variable="age", dtype="int64", kind="numeric",
                bins=[
                    {"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30,
                     "lower_inclusive": True, "upper_inclusive": True},
                ],
            ),
        ],
    )
    woe_table = WoeTable(
        mapping={"age": {"b1": 0.3}},
        columns=["age", "bin_id", "woe"],
    )
    scorecard_raw = {"factor": 1, "offset": 0, "score_direction": "higher_is_lower_risk"}
    model_raw = {
        "intercept": 0.0,
        "coefficients": coefficients if coefficients is not None else {"age_woe": 1.0},
    }
    return bin_def, woe_table, scorecard_raw, model_raw
