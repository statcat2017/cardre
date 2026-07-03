"""Step action dataclass for plan execution planning.

A planned action for a single step during execution — whether to
execute, reuse from a prior run, or skip.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from cardre.domain.evidence import ResolvedEvidence
from cardre.domain.step import StepSpec


@dataclass
class _StepAction:
    """A planned action for a single step during execution."""

    spec: StepSpec
    action: Literal["execute", "reuse", "skip"]
    evidence_source: ResolvedEvidence | None = None
    before_execute: Callable[[], None] | None = None
    reason_code: str = "execute"
    reason_context: dict[str, Any] | None = field(default_factory=dict[str, Any])


__all__ = ["_StepAction"]
