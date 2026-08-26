"""ProjectRegistry port contract tests (Batch 2A).

Runs the same register / resolve_root / list_all contract against the real
``JsonProjectRegistry`` (JSON-file-backed) and a minimal in-memory fake
(``MemoryProjectRegistry`` in ``tests/ports/_fakes``).
"""

from __future__ import annotations

import pytest

from cardre.adapters.system.project_registry import JsonProjectRegistry
from tests.ports._fakes import MemoryProjectRegistry


@pytest.fixture(params=["json", "memory"])
def registry(request, tmp_path):
    """Parametrized fixture returning either the real or fake registry."""
    if request.param == "json":
        return JsonProjectRegistry(tmp_path / "registry.json")
    return MemoryProjectRegistry()


class TestProjectRegistryContract:
    def test_register_then_resolve_root(self, registry, tmp_path):
        root = tmp_path / "projects" / "p1"
        registry.register("proj-1", root)
        resolved = registry.resolve_root("proj-1")
        assert resolved is not None
        assert resolved == root.resolve()

    def test_resolve_unknown_project_returns_none(self, registry):
        assert registry.resolve_root("missing") is None

    def test_list_all_reflects_registered(self, registry, tmp_path):
        root1 = tmp_path / "a"
        root2 = tmp_path / "b"
        registry.register("p1", root1)
        registry.register("p2", root2)
        listing = registry.list_all()
        assert set(listing.keys()) == {"p1", "p2"}
        assert listing["p1"] == str(root1.resolve())
        assert listing["p2"] == str(root2.resolve())

    def test_register_overwrites_existing_mapping(self, registry, tmp_path):
        root1 = tmp_path / "a"
        root2 = tmp_path / "b"
        registry.register("p1", root1)
        registry.register("p1", root2)
        assert registry.resolve_root("p1") == root2.resolve()
        assert registry.list_all()["p1"] == str(root2.resolve())

    def test_register_accepts_str_and_path(self, registry, tmp_path):
        registry.register("s", str(tmp_path / "s"))
        registry.register("p", tmp_path / "p")
        assert registry.resolve_root("s") == (tmp_path / "s").resolve()
        assert registry.resolve_root("p") == (tmp_path / "p").resolve()

    def test_registry_round_trip_persists(self, tmp_path):
        path = tmp_path / "registry.json"
        registry = JsonProjectRegistry(path)
        registry.register("proj-1", tmp_path / "p1")
        # A fresh instance over the same path must observe the persisted state.
        reloaded = JsonProjectRegistry(path)
        assert reloaded.resolve_root("proj-1") == (tmp_path / "p1").resolve()
