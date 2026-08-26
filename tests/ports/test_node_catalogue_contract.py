"""NodeCatalogue port contract tests (Batch 2A).

Covers the real ``NodeCatalogue`` built by ``build_default_catalogue()``:
resolve / has / list_types / instantiate and unknown-type behaviour. Registry
canonical-invariant tests (exact node-type set matching the canonical pathway)
live in ``tests/test_registry_canonical_invariant.py`` and are not duplicated
here.
"""

from __future__ import annotations

import pytest

from cardre.bootstrap.node_catalogue import build_default_catalogue


@pytest.fixture(scope="module")
def catalogue():
    return build_default_catalogue()


class TestNodeCatalogueContract:
    def test_resolve_returns_node_class(self, catalogue):
        for node_type in catalogue.list_types():
            cls = catalogue.resolve(node_type)
            assert isinstance(cls, type)
            assert getattr(cls, "node_type", None) == node_type

    def test_has_accepts_registered_and_rejects_unknown(self, catalogue):
        assert catalogue.has("cardre.apply_exclusions") is True
        assert catalogue.has("cardre.no_such_node") is False

    def test_list_types_is_unique_and_nonempty(self, catalogue):
        types = catalogue.list_types()
        assert types
        assert len(types) == len(set(types))

    def test_instantiate_returns_instance_of_resolved_class(self, catalogue):
        node_type = "cardre.apply_exclusions"
        assert catalogue.has(node_type)
        instance = catalogue.instantiate(node_type)
        assert instance.node_type == node_type
        assert catalogue.resolve(node_type).__name__ == type(instance).__name__

    def test_unknown_resolve_raises_key_error(self, catalogue):
        with pytest.raises(KeyError):
            catalogue.resolve("cardre.not_a_real_node")

    def test_unknown_instantiate_raises_key_error(self, catalogue):
        with pytest.raises(KeyError):
            catalogue.instantiate("cardre.not_a_real_node")
