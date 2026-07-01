from __future__ import annotations

from pathlib import Path

import pytest

from cardre.registry import NodeRegistry
from cardre.store import ProjectStore


@pytest.fixture
def contract_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "test.cardre")
    store.initialize()
    return store


@pytest.fixture
def contract_registry() -> NodeRegistry:
    return NodeRegistry.with_defaults()
