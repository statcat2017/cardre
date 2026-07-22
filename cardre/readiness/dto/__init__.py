"""Readiness DTOs — Pydantic models for readiness check results."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class ReportMode(StrEnum):
    FULL = "full"
    SUMMARY = "summary"


class ReadinessFinding(BaseModel):
    severity: str
    code: str
    message: str
    step_id: str | None = None


class ReportReadinessResult(BaseModel):
    blockers: list[ReadinessFinding] = Field(default_factory=list)
    warnings: list[ReadinessFinding] = Field(default_factory=list)
    target_branch_id: str | None = None
    run_id: str | None = None
    report_mode: ReportMode | None = None
    checked_at: str | None = None

    @computed_field
    def ready(self) -> bool:
        return len(self.blockers) == 0

    @computed_field
    def status(self) -> str:
        if len(self.blockers) > 0:
            return "blocked"
        if self.warnings:
            return "ready_with_warnings"
        return "ready"
