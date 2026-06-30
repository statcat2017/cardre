"""Step action dataclass for plan execution planning.

A planned action for a single step during execution — whether to
execute, reuse from a prior run, or skip.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from cardre.audit import RunStepRecord, StepSpec


@dataclass
class _StepAction:
    """A planned action for a single step during execution."""

    spec: StepSpec
    action: Literal["execute", "reuse", "skip"]
    evidence_source: RunStepRecord | None = None
    before_execute: Callable[[], None] | None = None
