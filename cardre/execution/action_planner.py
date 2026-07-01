"""Step action dataclass for plan execution planning.

A planned action for a single step during execution — whether to
execute, reuse from a prior run, or skip.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from cardre.domain.step import StepSpec
from cardre.domain.run import RunStep


@dataclass
class _StepAction:
    """A planned action for a single step during execution."""

    spec: StepSpec
    action: Literal["execute", "reuse", "skip"]
    evidence_source: RunStep | None = None
    before_execute: Callable[[], None] | None = None


__all__ = ["_StepAction"]
