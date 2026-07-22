"""Port for dispatching run execution (sync or async)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RunDispatcherPort(Protocol):
    def dispatch(self, request: RunRequest) -> None: ...
    def get_status(self, run_id: str) -> str: ...
    def shutdown(self) -> None: ...


class RunRequest:
    """Request to execute a run."""
    def __init__(self, run_id: str, plan_version_id: str) -> None:
        self.run_id = run_id
        self.plan_version_id = plan_version_id
