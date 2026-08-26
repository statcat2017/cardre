"""Schema coverage for the modelling-metadata and sample-definition nodes.

These nodes previously inherited the base ``parameter_schema() -> None``, so
the schema-driven editor exposed no fields. These tests pin the declared
schemas (fields, kinds, defaults, required flags, enum constraints) and verify
that normalization accepts the canonical defaults and existing valid fixture
parameters.
"""

from __future__ import annotations

from cardre.nodes.parameters import normalize_node_params
from cardre.nodes.prep.metadata import (
    DefineModellingMetadataNode,
    DevelopmentSampleDefinitionNode,
)


def _params_by_name(schema):
    return {p.name: p for m in schema.methods for p in m.params}


class TestDefineModellingMetadataSchema:
    def test_schema_identity(self):
        schema = DefineModellingMetadataNode.parameter_schema()
        assert schema.node_type == "cardre.define_modelling_metadata"
        assert schema.node_version == "1"
        assert len(schema.methods) == 1
        assert schema.methods[0].id == "default"

    def test_covers_previously_editable_fields(self):
        schema = DefineModellingMetadataNode.parameter_schema()
        params = _params_by_name(schema)
        expected = {
            "target_column",
            "good_values",
            "bad_values",
            "indeterminate_values",
            "purpose",
            "population",
            "product",
            "segment",
            "observation_window",
            "performance_window",
            "reject_inference_position",
        }
        assert expected <= set(params)

    def test_target_fields_kinds_and_required(self):
        schema = DefineModellingMetadataNode.parameter_schema()
        params = _params_by_name(schema)
        assert params["target_column"].kind == "string"
        assert params["target_column"].required is True
        assert params["good_values"].kind == "list"
        assert params["good_values"].required is True
        assert params["bad_values"].kind == "list"
        assert params["bad_values"].required is True
        assert params["indeterminate_values"].kind == "list"
        assert params["indeterminate_values"].required is False
        assert params["indeterminate_values"].default == []

    def test_reject_inference_enum_constraint(self):
        schema = DefineModellingMetadataNode.parameter_schema()
        params = _params_by_name(schema)
        rip = params["reject_inference_position"]
        assert rip.kind == "string"
        assert rip.constraint is not None
        assert set(rip.constraint.enum_values) == {
            "",
            "not_applied",
            "excluded",
            "ignored",
            "documented_method",
        }

    def test_normalization_accepts_canonical_defaults(self):
        schema = DefineModellingMetadataNode.parameter_schema()
        normalized = normalize_node_params(schema, {
            "target_column": "credit_risk_class",
            "good_values": ["good"],
            "bad_values": ["bad"],
            "purpose": "application_credit_scorecard",
            "product": "",
            "segment": "",
            "observation_window": "",
            "performance_window": "",
            "reject_inference_position": "not_applied",
        })
        assert normalized["target_column"] == "credit_risk_class"
        assert normalized["good_values"] == ["good"]
        assert normalized["bad_values"] == ["bad"]
        assert normalized["indeterminate_values"] == []
        assert normalized["reject_inference_position"] == "not_applied"

    def test_normalization_rejects_invalid_reject_inference(self):
        schema = DefineModellingMetadataNode.parameter_schema()
        try:
            normalize_node_params(schema, {
                "target_column": "outcome",
                "good_values": ["good"],
                "bad_values": ["bad"],
                "reject_inference_position": "bogus",
            })
        except ValueError as exc:
            assert "reject_inference_position" in str(exc)
        else:
            raise AssertionError("expected ValueError for invalid reject_inference_position")


class TestDevelopmentSampleDefinitionSchema:
    def test_schema_identity(self):
        schema = DevelopmentSampleDefinitionNode.parameter_schema()
        assert schema.node_type == "cardre.development_sample_definition"
        assert schema.node_version == "1"
        assert len(schema.methods) == 1
        assert schema.methods[0].id == "default"

    def test_covers_consumed_parameters(self):
        schema = DevelopmentSampleDefinitionNode.parameter_schema()
        params = _params_by_name(schema)
        expected = {
            "sample_method",
            "sample_domain",
            "sample_description",
            "weight_column",
            "population_bad_rate",
            "prior_probability_adjustment",
        }
        assert expected <= set(params)

    def test_allowed_values_and_defaults(self):
        schema = DevelopmentSampleDefinitionNode.parameter_schema()
        params = _params_by_name(schema)
        assert params["sample_method"].default == "full_population"
        assert params["sample_method"].constraint.enum_values == ["full_population"]
        assert params["sample_domain"].default == "ttd"
        assert params["sample_domain"].constraint.enum_values == ["ttd"]
        assert params["sample_description"].default == ""
        assert params["sample_description"].required is False
        assert params["weight_column"].default is None
        assert params["weight_column"].required is False
        assert params["population_bad_rate"].default is None
        assert params["population_bad_rate"].required is False
        assert params["prior_probability_adjustment"].kind == "object"
        assert params["prior_probability_adjustment"].default is None
        assert params["prior_probability_adjustment"].required is False

    def test_normalization_accepts_canonical_defaults(self):
        schema = DevelopmentSampleDefinitionNode.parameter_schema()
        normalized = normalize_node_params(schema, {
            "sample_method": "full_population",
            "sample_domain": "ttd",
            "sample_description": "Full booked population without additional row filtering",
        })
        assert normalized["sample_method"] == "full_population"
        assert normalized["sample_domain"] == "ttd"
        assert normalized["sample_description"] == (
            "Full booked population without additional row filtering"
        )
        assert normalized["weight_column"] is None
        assert normalized["population_bad_rate"] is None
        assert normalized["prior_probability_adjustment"] is None

    def test_normalization_rejects_unknown_sample_method(self):
        schema = DevelopmentSampleDefinitionNode.parameter_schema()
        try:
            normalize_node_params(schema, {"sample_method": "random_sample"})
        except ValueError as exc:
            assert "sample_method" in str(exc)
        else:
            raise AssertionError("expected ValueError for invalid sample_method")
