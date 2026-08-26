"""Parameter schema coverage for the build/refinement nodes.

These tests pin the structured-list schema contracts (item_kind, defaults,
required flags) and verify normalization accepts the canonical defaults and
rejects null for required array parameters.
"""

from __future__ import annotations

import pytest

from cardre.nodes.build.manual import ManualBinningNode
from cardre.nodes.build.selection import VariableSelectionNode
from cardre.nodes.parameters import normalize_node_params


def _params_by_name(schema):
    return {p.name: p for m in schema.methods for p in m.params}


class TestManualBinningSchema:
    def test_overrides_structured_list_contract(self):
        schema = ManualBinningNode.parameter_schema()
        params = _params_by_name(schema)
        assert params["overrides"].kind == "list"
        assert params["overrides"].item_kind == "object"
        assert params["overrides"].default == []
        assert params["overrides"].required is True

    def test_normalization_accepts_canonical_defaults(self):
        schema = ManualBinningNode.parameter_schema()
        normalized = normalize_node_params(
            schema,
            {
                "overrides": [
                    {"variable": "age", "action": "merge_bins", "reason": "sparse",
                     "source_bin_ids": ["a", "b"]},
                ],
                "reviewed": False,
                "accept_automated": False,
            },
        )
        assert normalized["overrides"] == [
            {"variable": "age", "action": "merge_bins", "reason": "sparse",
             "source_bin_ids": ["a", "b"]},
        ]
        assert normalized["reviewed"] is False
        assert normalized["accept_automated"] is False

    def test_normalization_accepts_missing_overrides_as_empty_list(self):
        schema = ManualBinningNode.parameter_schema()
        normalized = normalize_node_params(schema, {"accept_automated": True})
        assert normalized["overrides"] == []

    def test_normalization_rejects_null_overrides(self):
        schema = ManualBinningNode.parameter_schema()
        with pytest.raises(ValueError, match="overrides"):
            normalize_node_params(schema, {"overrides": None, "accept_automated": True})


class TestVariableSelectionSchema:
    def test_structured_lists_use_object_item_kind(self):
        schema = VariableSelectionNode.parameter_schema()
        params = _params_by_name(schema)
        for name in ("manual_includes", "manual_excludes", "cluster_representative_overrides"):
            param = params[name]
            assert param.kind == "list"
            assert param.item_kind == "object"
            assert param.default == []
            assert param.required is False

    def test_normalization_accepts_canonical_defaults(self):
        schema = VariableSelectionNode.parameter_schema()
        normalized = normalize_node_params(
            schema,
            {
                "min_iv": 0.02,
                "max_variables": 15,
                "manual_includes": [{"variable": "age", "reason": "forced"}],
                "manual_excludes": [],
                "cluster_representative_rule": "none",
                "cluster_representative_overrides": [],
            },
        )
        assert normalized["manual_includes"] == [{"variable": "age", "reason": "forced"}]
        assert normalized["manual_excludes"] == []
        assert normalized["cluster_representative_overrides"] == []
        assert normalized["cluster_representative_rule"] == "none"

    def test_normalization_missing_lists_default_to_empty(self):
        schema = VariableSelectionNode.parameter_schema()
        normalized = normalize_node_params(
            schema,
            {"min_iv": 0.02, "max_variables": 15, "cluster_representative_rule": "none"},
        )
        assert normalized["manual_includes"] == []
        assert normalized["manual_excludes"] == []
        assert normalized["cluster_representative_overrides"] == []
