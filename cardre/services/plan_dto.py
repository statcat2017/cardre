"""Plain dataclass DTOs for plan-service return values.

These mirror the Pydantic models in ``sidecar.models`` so that
``cardre.services`` has no dependency on the FastAPI sidecar layer.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepStatusItem:
    step_id: str
    node_type: str
    category: str
    status: str = "not_run"
    is_stale: bool = False
    position: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    canonical_step_id: str = ""
    branch_id: str | None = None


@dataclass
class PlanResponse:
    plan_id: str
    project_id: str
    name: str
    latest_version_id: str
    steps: list[StepStatusItem]


@dataclass
class UpdateStepParamsResponse:
    plan_id: str
    new_plan_version_id: str
    changed_step_id: str
    stale_step_ids: list[str]


@dataclass
class ManualBinningSourceInfo:
    binning_step_id: str
    binning_artifact_id: str
    binning_method: str
    variable_selection_step_id: str
    variable_selection_artifact_id: str


@dataclass
class PreviewDiagnostics:
    override_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclasses.dataclass
class ManualBinningVariableSummary:
    variable: str
    iv: float | None = None
    woe_by_bin: dict[str, float] | None = None
    event_rate_by_bin: dict[str, float] | None = None
    missing_count: int | None = None
    special_bin_count: int | None = None
    sparse_bin_warning: bool = False
    non_monotonic_warning: bool = False


@dataclass
class ManualBinningEditorStateResponse:
    plan_id: str
    plan_version_id: str
    step_id: str = "manual-binning"
    ready: bool = False
    blocked_reason: str | None = None
    required_steps: list[str] = field(default_factory=list)
    source: ManualBinningSourceInfo | None = None
    selected_variables: list[str] = field(default_factory=list)
    source_bins_by_variable: dict[str, Any] = field(default_factory=dict)
    current_overrides: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    variable_summaries: list[ManualBinningVariableSummary] = field(default_factory=list)


@dataclass
class ManualBinningPreviewResponse:
    valid: bool = False
    refined_bins_by_variable: dict[str, Any] = field(default_factory=dict)
    diagnostics: PreviewDiagnostics | None = None
