"""Compiler/IR validation tests for scoring-export.

These unit tests exercise ``scoring_export_ir.compile_scorecard`` directly:
compilation must fail loudly (rather than silently dropping) when a model
coefficient has no matching bin variable, when a coefficient's variable has no
WOE map, or when a bin definition has no corresponding WOE entry.
"""

from __future__ import annotations

import pytest

from cardre.domain.evidence.models.binning import BinDefinition, BinVariable
from cardre.domain.evidence.models.woe import WoeTable
from cardre.nodes.build.scoring_export_ir import compile_scorecard
from tests.nodes._scoring_helpers import make_simple_numeric_agecard


def test_compile_scorecard_raises_on_unconsumed_coefficient():
    """When a model has a coefficient for a variable that has no bin
    definition, compilation fails rather than silently dropping it."""
    bin_def, woe_table, scorecard_raw, model_raw = make_simple_numeric_agecard(
        coefficients={"age_woe": 1.0, "income_woe": 0.5}
    )
    with pytest.raises(ValueError, match="no corresponding bin variable"):
        compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw)


def test_compile_scorecard_raises_on_missing_woe_map_for_coefficient():
    """When a model coefficient exists but the variable has no WOE map,
    compilation fails with a useful error rather than silently skipping."""
    bin_def, woe_table, scorecard_raw, model_raw = make_simple_numeric_agecard()
    woe_table = WoeTable(  # no WOE for age!
        mapping={},
        columns=["variable", "bin_id", "woe"],
    )
    with pytest.raises(ValueError, match="no WOE mapping"):
        compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw)


def test_compile_scorecard_raises_on_bin_without_woe():
    """When a bin definition exists but the WOE table has no entry for that
    bin, compilation fails with a useful error."""
    bin_def = BinDefinition(
        source_artifact_id="test",
        variables=[
            BinVariable(
                variable="age", dtype="int64", kind="numeric",
                bins=[
                    {"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30,
                     "lower_inclusive": True, "upper_inclusive": True},
                    {"bin_id": "b2", "label": "31+", "lower": 31,
                     "upper_inclusive": True, "lower_inclusive": True},
                ],
            ),
        ],
    )
    woe_table = WoeTable(
        mapping={"age": {"b1": 0.3}},  # b2 missing!
        columns=["variable", "bin_id", "woe"],
    )
    scorecard_raw = {"factor": 1, "offset": 0, "score_direction": "higher_is_lower_risk"}
    model_raw = {"intercept": 0.0, "coefficients": {"age_woe": 1.0}}

    with pytest.raises(ValueError, match="no WOE entry"):
        compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw)
