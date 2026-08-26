"""Parameter schema coverage for the build/refinement nodes.

These tests pin the structured-list schema contracts (item_kind, defaults,
required flags) and verify normalization accepts the canonical defaults and
rejects null for required array parameters.
"""

from __future__ import annotations

import pytest

from cardre.nodes.build.features import CalculateWoeIvNode
from cardre.nodes.build.manual import ManualBinningNode
from cardre.nodes.build.selection import VariableSelectionNode
from cardre.nodes.parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterDefinition,
    normalize_node_params,
)


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


class TestStructuralTypeEnforcement:
    """Structural typing: kind=object requires a JSON-object dict, kind=list
    requires a list, and item_kind validates each list item."""

    def _object_schema(self, item_kind: str | None = None) -> NodeParameterSchema:
        kind = "list" if item_kind else "object"
        return NodeParameterSchema(
            node_type="test.obj",
            node_version="1",
            methods=[
                MethodOption(
                    id="default",
                    params=[
                        ParameterDefinition(name="payload", kind=kind, item_kind=item_kind),
                    ],
                ),
            ],
        )

    def _plain_list_schema(self) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type="test.plain_list",
            node_version="1",
            methods=[
                MethodOption(
                    id="default",
                    params=[ParameterDefinition(name="tags", kind="list")],
                ),
            ],
        )

    def test_object_accepts_dict_preserves_value(self):
        schema = CalculateWoeIvNode.parameter_schema()
        smoothing = {"method": "additive", "alpha": 0.5, "rationale": "stable"}
        normalized = normalize_node_params(
            schema,
            {"zero_cell_policy": "block", "purpose": "initial", "smoothing": smoothing},
        )
        assert normalized["smoothing"] == smoothing

    @pytest.mark.parametrize("bad", [[], "hello", 123, 4.5, True, False])
    def test_object_rejects_non_dict(self, bad):
        schema = CalculateWoeIvNode.parameter_schema()
        with pytest.raises(ValueError, match="smoothing"):
            normalize_node_params(
                schema,
                {"zero_cell_policy": "block", "purpose": "initial", "smoothing": bad},
            )

    def test_list_accepts_list_and_preserves_items(self):
        schema = ManualBinningNode.parameter_schema()
        overrides = [
            {"variable": "age", "action": "merge_bins", "reason": "sparse",
             "source_bin_ids": ["a", "b"]},
        ]
        normalized = normalize_node_params(
            schema,
            {"overrides": overrides, "reviewed": False, "accept_automated": False},
        )
        assert normalized["overrides"] == overrides

    @pytest.mark.parametrize("bad", ["scalar", 123, {"a": 1}, True, ("tuple",)])
    def test_list_rejects_non_list(self, bad):
        schema = ManualBinningNode.parameter_schema()
        with pytest.raises(ValueError, match="overrides"):
            normalize_node_params(schema, {"overrides": bad, "accept_automated": True})

    @pytest.mark.parametrize("bad_item", ["string", 123, True])
    def test_object_item_list_rejects_non_dict_items(self, bad_item):
        schema = ManualBinningNode.parameter_schema()
        with pytest.raises(ValueError, match="'overrides'\\[0\\]"):
            normalize_node_params(
                schema, {"overrides": [bad_item], "accept_automated": True}
            )

    def test_plain_list_without_item_kind_preserves_current_behavior(self):
        schema = self._plain_list_schema()
        raw = ["a", "b", 1, {"nested": True}]
        assert normalize_node_params(schema, {"tags": raw})["tags"] == raw

    def test_scalar_item_kind_validates_items(self):
        schema = self._object_schema(item_kind="integer")
        assert normalize_node_params(schema, {"payload": [1, 2, 3]})["payload"] == [1, 2, 3]
        with pytest.raises(ValueError, match="'payload'\\[0\\]"):
            normalize_node_params(schema, {"payload": ["x"]})
        # bool must not be accepted as an integer item.
        with pytest.raises(ValueError, match="'payload'\\[0\\]"):
            normalize_node_params(schema, {"payload": [True]})

    def test_object_item_kind_enforced_per_item(self):
        schema = self._object_schema(item_kind="object")
        item = {"variable": "age", "reason": "forced"}
        assert normalize_node_params(schema, {"payload": [item]})["payload"] == [item]
        with pytest.raises(ValueError, match="'payload'\\[1\\]"):
            normalize_node_params(schema, {"payload": [{"ok": True}, "bad"]})

    def test_bool_item_kind_coerces_without_integer_promotion(self):
        schema = self._object_schema(item_kind="boolean")
        assert normalize_node_params(schema, {"payload": [True, False]})["payload"] == [True, False]

    def _scalar_schema(self, kind: str) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type="test.scalar",
            node_version="1",
            methods=[
                MethodOption(
                    id="default",
                    params=[ParameterDefinition(name="payload", kind=kind)],
                ),
            ],
        )

    @pytest.mark.parametrize("kind", ["integer", "int"])
    def test_integer_scalar_rejects_bool(self, kind):
        schema = self._scalar_schema(kind)
        with pytest.raises(ValueError, match="integer"):
            normalize_node_params(schema, {"payload": True})

    @pytest.mark.parametrize("kind", ["float", "number", "numeric"])
    def test_float_scalar_rejects_bool(self, kind):
        schema = self._scalar_schema(kind)
        with pytest.raises(ValueError, match="number"):
            normalize_node_params(schema, {"payload": True})

    @pytest.mark.parametrize("kind", ["integer", "int"])
    def test_integer_scalar_coerces_valid_inputs(self, kind):
        schema = self._scalar_schema(kind)
        assert normalize_node_params(schema, {"payload": "42"})["payload"] == 42
        assert normalize_node_params(schema, {"payload": 42})["payload"] == 42

    @pytest.mark.parametrize("kind", ["float", "number", "numeric"])
    def test_float_scalar_coerces_valid_inputs(self, kind):
        schema = self._scalar_schema(kind)
        assert normalize_node_params(schema, {"payload": "1.5"})["payload"] == 1.5
        assert normalize_node_params(schema, {"payload": 1.5})["payload"] == 1.5

    def test_integer_scalar_rejects_non_numeric_string(self):
        schema = self._scalar_schema("integer")
        with pytest.raises(ValueError, match="integer"):
            normalize_node_params(schema, {"payload": "abc"})

    def test_float_scalar_rejects_non_numeric_string(self):
        schema = self._scalar_schema("float")
        with pytest.raises(ValueError, match="number"):
            normalize_node_params(schema, {"payload": "abc"})

    def test_string_item_kind_requires_strings(self):
        schema = self._object_schema(item_kind="string")
        assert normalize_node_params(schema, {"payload": ["a", "b"]})["payload"] == ["a", "b"]
        # Arbitrary values must not be silently stringified.
        with pytest.raises(ValueError, match="'payload'\\[0\\]"):
            normalize_node_params(schema, {"payload": [123]})

    @pytest.mark.parametrize("item_kind", ["float", "number", "numeric"])
    def test_float_item_kind_validates_and_coerces(self, item_kind):
        schema = self._object_schema(item_kind=item_kind)
        assert normalize_node_params(schema, {"payload": [1, "2.5"]})["payload"] == [1.0, 2.5]
        with pytest.raises(ValueError, match="'payload'\\[0\\]"):
            normalize_node_params(schema, {"payload": ["x"]})

    def test_unknown_item_kind_rejected(self):
        schema = self._object_schema(item_kind="bogus")
        with pytest.raises(ValueError, match="item_kind"):
            normalize_node_params(schema, {"payload": [{"a": 1}]})
