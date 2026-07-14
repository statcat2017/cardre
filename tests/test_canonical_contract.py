"""Canonical contract tests — enforce the canonical architecture.

These tests guard against regression to legacy node identities, aliases,
and compatibility mechanisms that have been removed.
"""

from __future__ import annotations

from cardre.nodes.registry import NodeRegistry


def test_only_one_automatic_binning_node_registered():
    reg = NodeRegistry.with_defaults()
    assert reg.has("cardre.automatic_binning")
    assert not reg.has("cardre.fine_classing")
    assert not reg.has("cardre.auto_binning_fit")
    assert not reg.has("cardre.binning")


def test_manual_binning_distinct_node():
    reg = NodeRegistry.with_defaults()
    manual = reg.resolve("cardre.manual_binning")
    assert manual.category == "refinement"
    assert manual.node_type == "cardre.manual_binning"
