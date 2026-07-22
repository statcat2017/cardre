"""GetRunEvidence — read-only query for run evidence."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class GetRunEvidenceCommand:
    run_id: str


class GetRunEvidence:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: GetRunEvidenceCommand) -> list[Any]:
        uow = self._uow_factory()
        return uow.evidence.get_for_run(command.run_id)
