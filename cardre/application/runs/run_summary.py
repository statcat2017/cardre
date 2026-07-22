from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunSummary:
    run_id: str
    plan_version_id: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    step_count: int = 0
    branch_id: str | None = None
    executed_step_ids: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    latest_error: str | None = None
    heartbeat_at: str | None = None
    is_stale: bool = False
