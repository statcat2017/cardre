"""Tests for NodeRegistry tier enforcement.

- Launch nodes are executable (instantiate returns a node).
- Deferred nodes raise NodeNotAvailableForLaunch in launch mode.
- NodeAvailability reports correct tier and available flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cardre.config import CardreConfig
from cardre.domain.errors import NodeNotAvailableForLaunch
from cardre.nodes.registry import NodeRegistry


def test_registry_launch_nodes_available():
    """All launch-tier nodes should be available (instantiable) in launch mode."""
    reg = NodeRegistry.with_defaults()

    for node_type in reg.list_launch_nodes():
        av = reg.availability(node_type)
        assert av.available, f"Launch node {node_type} should be available but got {av}"
        assert av.tier == "launch", f"Launch node {node_type} should have tier='launch' got {av.tier}"

        node = reg.instantiate(node_type)
        assert node is not None
        assert node.node_type == node_type


def test_registry_deferred_nodes_not_available():
    """Deferred nodes should raise NodeNotAvailableForLaunch in launch mode."""
    reg = NodeRegistry.with_defaults()

    for node_type in reg.list_deferred_nodes():
        av = reg.availability(node_type)
        assert not av.available, f"Deferred node {node_type} should not be available"
        assert av.tier == "deferred", f"Deferred node {node_type} should have tier='deferred'"

        with pytest.raises(NodeNotAvailableForLaunch) as exc:
            reg.instantiate(node_type)
        assert node_type in str(exc.value) or "launch mode" in str(exc.value)


def test_registry_unknown_node_raises_key_error():
    """Unknown node types should raise KeyError."""
    reg = NodeRegistry()
    with pytest.raises(KeyError):
        reg.resolve("cardre.nonexistent_node")


def test_registry_has_and_list_types():
    """has() and list_types() should work correctly."""
    reg = NodeRegistry.with_defaults()
    launch = reg.list_launch_nodes()
    deferred = reg.list_deferred_nodes()

    assert len(launch) > 0
    assert len(deferred) > 0

    for nt in launch:
        assert reg.has(nt)
        av = reg.availability(nt)
        assert av.available

    for nt in deferred:
        assert reg.has(nt)


def test_registry_outside_launch_mode(monkeypatch):
    """When launch_mode=False, deferred nodes should still be marked deferred."""
    monkeypatch.setattr(CardreConfig, "from_env", lambda: CardreConfig(launch_mode=False))
    reg = NodeRegistry.with_defaults()

    for node_type in reg.list_deferred_nodes():
        av = reg.availability(node_type)
        # Outside launch mode, deferred nodes should be available
        # (assuming no missing optional deps)
        deps = getattr(type(reg.resolve(node_type)), "optional_dependencies", None)
        if deps:
            # Skip nodes that need optional deps not installed
            pass
        else:
            if not av.available:
                assert "Optional dependency" in (av.disabled_reason or "")


def test_registry_duplicate_register():
    """Registering the same node_type twice should overwrite (last-wins)."""
    reg = NodeRegistry()
    from cardre.nodes.prep import ProfileDatasetNode

    reg.register(ProfileDatasetNode)
    assert reg.has("cardre.profile_dataset")

    # Re-register should not raise
    reg.register(ProfileDatasetNode)
    assert reg.has("cardre.profile_dataset")


def test_registry_node_type_required():
    """A class without node_type should raise ValueError on register."""
    reg = NodeRegistry()

    class FakeNode:
        pass

    with pytest.raises(ValueError, match="must define node_type"):
        reg.register(FakeNode)  # type: ignore[arg-type]


def test_registry_is_available():
    """is_available should be consistent with availability()."""
    reg = NodeRegistry.with_defaults()
    for nt in reg.list_types():
        assert reg.is_available(nt) == reg.availability(nt).available


def test_registry_exposes_issue_273_prep_nodes_as_launch_nodes():
    reg = NodeRegistry.with_defaults()

    for node_type in [
        "cardre.apply_exclusions",
        "cardre.development_sample_definition",
        "cardre.explicit_missing_outlier_treatment",
        "cardre.coefficient_sign_check",
        "cardre.separation_diagnostics",
        "cardre.vif_diagnostics",
        "cardre.calibration_diagnostics",
    ]:
        availability = reg.availability(node_type)
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
    reg = NodeRegistry.with_defaults()

    launch_rows = _catalogue_rows("## Launch Nodes (executable at launch)")
    deferred_rows = _catalogue_rows("## Deferred Nodes (schema only, not executable at launch)")

    assert set(launch_rows) == set(reg.list_launch_nodes())
    assert set(deferred_rows) == set(reg.list_deferred_nodes())

    for node_type, category in launch_rows.items():
        assert category == reg.resolve(node_type).category
    for node_type, category in deferred_rows.items():
        assert category == reg.resolve(node_type).category
