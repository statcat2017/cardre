"""Tests for cardre.step_graph — ancestor/descendant closure."""

from __future__ import annotations

import pytest

from cardre.audit import StepSpec, json_logical_hash
from cardre.step_graph import ancestor_closure, descendant_closure


def _s(step_id: str, parents: list[str] | None = None) -> StepSpec:
    return StepSpec(
        step_id=step_id, node_type="t", node_version="1", category="t",
        params={}, params_hash=json_logical_hash({}),
        parent_step_ids=parents or [],
        branch_label="", position=0,
    )


class TestDescendantClosure:

    def test_singleton(self):
        steps = [_s("a")]
        assert descendant_closure("a", steps) == {"a"}

    def test_linear_chain(self):
        steps = [_s("a"), _s("b", ["a"]), _s("c", ["b"])]
        assert descendant_closure("a", steps) == {"a", "b", "c"}
        assert descendant_closure("b", steps) == {"b", "c"}
        assert descendant_closure("c", steps) == {"c"}

    def test_diamond_dag(self):
        steps = [
            _s("a"),
            _s("b", ["a"]),
            _s("c", ["a"]),
            _s("d", ["b", "c"]),
        ]
        assert descendant_closure("a", steps) == {"a", "b", "c", "d"}
        assert descendant_closure("b", steps) == {"b", "d"}
        assert descendant_closure("d", steps) == {"d"}

    def test_disconnected(self):
        steps = [_s("a"), _s("b")]
        assert descendant_closure("a", steps) == {"a"}
        assert descendant_closure("b", steps) == {"b"}

    def test_missing_step_raises(self):
        with pytest.raises(KeyError):
            descendant_closure("z", [_s("a")])


class TestAncestorClosure:

    def test_root_has_no_ancestors(self):
        steps = [_s("a")]
        assert ancestor_closure("a", steps) == set()

    def test_direct_parent(self):
        steps = [_s("a"), _s("b", ["a"])]
        assert ancestor_closure("b", steps) == {"a"}

    def test_chain(self):
        steps = [_s("a"), _s("b", ["a"]), _s("c", ["b"])]
        assert ancestor_closure("c", steps) == {"a", "b"}

    def test_diamond(self):
        steps = [
            _s("a"),
            _s("b", ["a"]),
            _s("c", ["a"]),
            _s("d", ["b", "c"]),
        ]
        assert ancestor_closure("d", steps) == {"a", "b", "c"}

    def test_missing_step_raises(self):
        with pytest.raises(KeyError):
            ancestor_closure("z", [_s("a")])
