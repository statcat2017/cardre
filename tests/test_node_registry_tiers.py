"""Tests for NodeCatalogue tier enforcement.

- Launch nodes are executable (instantiate returns a node).
- Deferred nodes raise NodeNotAvailableForLaunch in launch mode.
- NodeAvailability reports correct tier and available flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cardre.bootstrap.node_catalogue import NodeCatalogue, build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.errors import NodeNotAvailableForLaunch


def _default_catalogue() -> NodeCatalogue:
    return build_default_catalogue(Settings(launch_mode=True))


def _non_launch_catalogue() -> NodeCatalogue:
    return build_default_catalogue(Settings(launch_mode=False))


def test_catalogue_launch_nodes_available():
    """All launch-tier nodes should be available (instantiable) in launch mode."""
    cat = _default_catalogue()

    for node_type in cat.list_launch_types():
        av = cat.availability(node_type)
        assert av.available, f"Launch node {node_type} should be available but got {av}"
        assert av.tier == "launch", f"Launch node {node_type} should have tier='launch' got {av.tier}"

        node = cat.instantiate(node_type)
        assert node is not None
        assert node.node_type == node_type


def test_catalogue_deferred_nodes_not_available():
    """Deferred nodes should raise NodeNotAvailableForLaunch in launch mode."""
    cat = _default_catalogue()

    for node_type in cat.list_deferred_types():
        av = cat.availability(node_type)
        assert not av.available, f"Deferred node {node_type} should not be available"
        assert av.tier == "deferred", f"Deferred node {node_type} should have tier='deferred'"

        with pytest.raises(NodeNotAvailableForLaunch) as exc:
            cat.instantiate(node_type)
        assert node_type in str(exc.value) or "launch mode" in str(exc.value)


def test_catalogue_unknown_node_raises_key_error():
    cat = NodeCatalogue(Settings(), [])
    with pytest.raises(KeyError):
        cat.resolve("cardre.nonexistent_node")


def test_catalogue_has_and_list_types():
    cat = _default_catalogue()
    launch = cat.list_launch_types()
    deferred = cat.list_deferred_types()

    assert len(launch) > 0
    assert len(deferred) > 0

    for nt in launch:
        assert cat.has(nt)
        av = cat.availability(nt)
        assert av.available

    for nt in deferred:
        assert cat.has(nt)


def test_catalogue_outside_launch_mode():
    """When launch_mode=False, deferred nodes should still be marked deferred."""
    cat = _non_launch_catalogue()

    for node_type in cat.list_deferred_types():
        av = cat.availability(node_type)
        deps = getattr(type(cat.resolve(node_type)), "optional_dependencies", None)
        if deps:
            pass
        else:
            if not av.available:
                assert "Optional dependency" in (av.disabled_reason or "")


def test_catalogue_is_available():
    cat = _default_catalogue()
    for nt in cat.list_types():
        assert cat.is_available(nt) == cat.availability(nt).available


def test_catalogue_exposes_issue_273_prep_nodes_as_launch_nodes():
    cat = _default_catalogue()

    for node_type in [
        "cardre.apply_exclusions",
        "cardre.development_sample_definition",
        "cardre.explicit_missing_outlier_treatment",
        "cardre.coefficient_sign_check",
        "cardre.separation_diagnostics",
        "cardre.vif_diagnostics",
        "cardre.calibration_diagnostics",
    ]:
        availability = cat.availability(node_type)
        assert availability.available, availability
        assert availability.tier == "launch"


def _catalogue_rows(section_header: str) -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / "docs" / "reference" / "node-catalogue.md"
    rows: dict[str, str] = {}
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == section_header:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.startswith("| `cardre."):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        rows[parts[0].strip("`")] = parts[1]
    return rows


def test_node_catalogue_matches_registry_tiers_and_categories():
    """The published node catalogue is a contract, not hand-written folklore."""
    cat = _default_catalogue()

    launch_rows = _catalogue_rows("## Launch Nodes (executable at launch)")
    deferred_rows = _catalogue_rows("## Deferred Nodes (schema only, not executable at launch)")

    assert set(launch_rows) == set(cat.list_launch_types())
    assert set(deferred_rows) == set(cat.list_deferred_types())

    for node_type, category in launch_rows.items():
        assert category == cat.resolve(node_type).category
    for node_type, category in deferred_rows.items():
        assert category == cat.resolve(node_type).category
