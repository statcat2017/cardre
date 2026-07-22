"""Heartbeat — updates the run's heartbeat timestamp within a UoW."""
from __future__ import annotations


def heartbeat(uow: object, run_id: str) -> None:
    uow.runs.heartbeat(run_id)  # type: ignore[union-attr]
