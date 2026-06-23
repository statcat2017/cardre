"""Readiness DTOs — blocker, warning, and result types with step_id support."""

from __future__ import annotations

from typing import Any

from cardre.readiness.limitation_codes import LimitationCode


class ReadinessBlocker:
    code: str
    message: str
    step_id: str | None

    @staticmethod
    def _normalize(code: str) -> str:
        try:
            return LimitationCode(code)
        except ValueError:
            return code

    def __init__(self, code: str, message: str, step_id: str | None = None) -> None:
        self.code = self._normalize(code)
        self.message = message
        self.step_id = step_id

    def to_dict(self) -> dict[str, str]:
        d: dict[str, str] = {"code": str(self.code), "message": self.message}
        if self.step_id is not None:
            d["step_id"] = self.step_id
        return d


class ReadinessWarning:
    code: str
    message: str
    step_id: str | None

    @staticmethod
    def _normalize(code: str) -> str:
        try:
            return LimitationCode(code)
        except ValueError:
            return code

    def __init__(self, code: str, message: str, step_id: str | None = None) -> None:
        self.code = self._normalize(code)
        self.message = message
        self.step_id = step_id

    def to_dict(self) -> dict[str, str]:
        d: dict[str, str] = {"code": str(self.code), "message": self.message}
        if self.step_id is not None:
            d["step_id"] = self.step_id
        return d


class ReportReadinessResult:
    ready: bool
    status: str
    blockers: list[ReadinessBlocker]
    warnings: list[ReadinessWarning]
    target_branch_id: str | None = None
    run_id: str | None = None
    report_mode: str | None = None
    checked_at: str | None = None

    def __init__(
        self,
        blockers: list[ReadinessBlocker] | None = None,
        warnings: list[ReadinessWarning] | None = None,
        target_branch_id: str | None = None,
        run_id: str | None = None,
        report_mode: str | None = None,
        checked_at: str | None = None,
    ) -> None:
        self.blockers = blockers or []
        self.warnings = warnings or []
        self.ready = len(self.blockers) == 0
        self.target_branch_id = target_branch_id
        self.run_id = run_id
        self.report_mode = report_mode
        self.checked_at = checked_at
        if self.ready:
            self.status = "ready_with_warnings" if self.warnings else "ready"
        else:
            self.status = "blocked"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ready": self.ready,
            "status": self.status,
            "blockers": [b.to_dict() for b in self.blockers],
            "warnings": [w.to_dict() for w in self.warnings],
        }
        if self.target_branch_id is not None:
            d["target_branch_id"] = self.target_branch_id
        if self.run_id is not None:
            d["run_id"] = self.run_id
        if self.report_mode is not None:
            d["report_mode"] = self.report_mode
        if self.checked_at is not None:
            d["checked_at"] = self.checked_at
        return d
