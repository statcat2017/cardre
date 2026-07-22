"""Backward-compat shim — RunCoordinator was replaced by application/runs use cases."""
from __future__ import annotations

from cardre.application.runs.run_summary import RunSummary  # noqa: F401


class RunCoordinator:
    """Legacy stub — replaced by SubmitRun + ExecuteRun in cardre.application.runs."""
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass
