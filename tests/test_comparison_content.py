from __future__ import annotations

import cardre.services.comparison_service as comparison_service


class TestValidationRoles:
    def test_none_returns_empty(self):
        assert comparison_service._validation_roles(None) == {}

    def test_non_dict_returns_empty(self):
        assert comparison_service._validation_roles("string") == {}

    def test_roles_key(self):
        result = comparison_service._validation_roles({"roles": {"train": {"auc": 0.8}}})
        assert result == {"train": {"auc": 0.8}}

    def test_metrics_by_role_key(self):
        result = comparison_service._validation_roles({"metrics_by_role": {"test": {"auc": 0.7}}})
        assert result == {"test": {"auc": 0.7}}

    def test_metrics_key(self):
        result = comparison_service._validation_roles({"metrics": {"gini": 0.6}})
        assert result == {"gini": 0.6}

    def test_fallback_to_payload(self):
        result = comparison_service._validation_roles({"other": "value"})
        assert result == {"other": "value"}


class TestMaterializeEvidence:
    def test_materialize_dict(self):
        result = comparison_service._materialize_evidence({"a": 1, "b": {"c": 2}})
        assert result == {"a": 1, "b": {"c": 2}}

    def test_materialize_list_of_dicts(self):
        result = comparison_service._materialize_evidence([{"x": 1}, {"y": 2}])
        assert result == [{"x": 1}, {"y": 2}]

    def test_materialize_tuple_to_list(self):
        result = comparison_service._materialize_evidence((1, 2, 3))
        assert result == [1, 2, 3]

    def test_materialize_primitive_returns_primitive(self):
        result = comparison_service._materialize_evidence(42)
        assert result == 42

    def test_materialize_none(self):
        result = comparison_service._materialize_evidence(None)
        assert result is None

    def test_materialize_tuple(self):
        import cardre.services.comparison_service as cs
        result = cs._materialize_evidence((1, 2, 3))
        assert result == [1, 2, 3]

    def test_materialize_nested(self):
        import cardre.services.comparison_service as cs
        result = cs._materialize_evidence({"a": {"b": [1, {"c": 2}]}})
        assert result == {"a": {"b": [1, {"c": 2}]}}
