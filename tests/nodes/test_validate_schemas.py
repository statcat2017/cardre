"""Parameter schema coverage for the validate nodes.

These tests pin the ``cutoffs`` list contract (item_kind=float) on the real
validation schemas: numeric strings normalize to floats, and non-numeric
entries are rejected.
"""

from __future__ import annotations

import pytest

from cardre.nodes.parameters import normalize_node_params
from cardre.nodes.validate.cutoff import CutoffAnalysisNode
from cardre.nodes.validate.metrics import ValidationMetricsNode


class TestValidationCutoffsNormalization:
    def _cutoffs_param(self, node_cls):
        schema = node_cls.parameter_schema()
        method = schema.methods[0]
        return next(p for p in method.params if p.name == "cutoffs")

    def test_metrics_cutoffs_numeric_strings_normalize(self):
        param = self._cutoffs_param(ValidationMetricsNode)
        assert param.kind == "list"
        assert param.item_kind == "float"
        assert param.default == [0.5]
        schema = ValidationMetricsNode.parameter_schema()
        normalized = normalize_node_params(schema, {"cutoffs": ["0.4", "0.5"]})
        assert normalized["cutoffs"] == [0.4, 0.5]

    def test_metrics_cutoffs_reject_non_numeric(self):
        schema = ValidationMetricsNode.parameter_schema()
        with pytest.raises(ValueError):
            normalize_node_params(schema, {"cutoffs": ["0.4", "high"]})

    def test_cutoff_analysis_numeric_strings_normalize(self):
        param = self._cutoffs_param(CutoffAnalysisNode)
        assert param.item_kind == "float"
        assert param.default == []
        schema = CutoffAnalysisNode.parameter_schema()
        normalized = normalize_node_params(schema, {"cutoffs": ["0.4", "0.5"]})
        assert normalized["cutoffs"] == [0.4, 0.5]

    def test_cutoff_analysis_reject_non_numeric(self):
        schema = CutoffAnalysisNode.parameter_schema()
        with pytest.raises(ValueError):
            normalize_node_params(schema, {"cutoffs": ["0.4", "bad"]})
