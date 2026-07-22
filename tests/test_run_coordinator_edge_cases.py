from __future__ import annotations

import pytest


class TestRunCoordinatorEdgeCases:
    def test_get_summary_nonexistent_raises(self, tmp_path):
        from cardre.store.db import ProjectStore
        store = ProjectStore(tmp_path / "test.cardre")
        store.initialize()
        from cardre.domain.errors import CardreError
        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        with pytest.raises(CardreError, match="not found"):
            coordinator.get_summary("nonexistent-run")

    def test_dispatcher_init(self):
        from cardre.services.run_coordinator import _get_global_dispatcher
        dispatcher = _get_global_dispatcher()
        assert dispatcher is not None
