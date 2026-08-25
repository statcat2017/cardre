"""Registry invariant — the flat production registry is the canonical pathway.

The single source of truth for production node registration is
``_CANONICAL_SCORECARD_STEPS``. The node catalogue must register exactly the
distinct node types required by that pathway, no more and no less, and every
node type in the pathway must resolve through the catalogue.
"""

from __future__ import annotations

from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.plans.scorecard_pathway import _CANONICAL_SCORECARD_STEPS


def _canonical_node_types() -> set[str]:
    return {node_type for _, node_type, _, _ in _CANONICAL_SCORECARD_STEPS}


def test_flat_registry_matches_canonical_pathway_node_types():
    cat = build_default_catalogue(Settings())
    registered = set(cat.list_types())
    canonical = _canonical_node_types()

    assert registered == canonical, (
        "The production registry must contain exactly the distinct node types "
        "required by the canonical scorecard pathway. "
        f"Registered-but-not-canonical={sorted(registered - canonical)} "
        f"Canonical-but-not-registered={sorted(canonical - registered)}"
    )


def test_canonical_pathway_node_types_distinct_and_registered():
    cat = build_default_catalogue(Settings())
    canonical = _canonical_node_types()
    assert len(canonical) == len(set(canonical)), "canonical node types must be distinct"
    for node_type in canonical:
        assert cat.has(node_type), f"canonical node type {node_type!r} is not registered"
        assert cat.resolve(node_type).node_definition().version, (
            f"canonical node type {node_type!r} lacks a version"
        )
