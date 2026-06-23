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

    def to_dict(self) -> dict[str, str | None]:
        return {"code": str(self.code), "message": self.message, "step_id": self.step_id}


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

    def to_dict(self) -> dict[str, str | None]:
        return {"code": str(self.code), "message": self.message, "step_id": self.step_id}


class ReportReadinessResult:
    ready: bool
    status: str
    blockers: list[ReadinessBlocker]
    warnings: list[ReadinessWarning]

    def __init__(
        self,
        blockers: list[ReadinessBlocker] | None = None,
        warnings: list[ReadinessWarning] | None = None,
    ) -> None:
        self.blockers = blockers or []
        self.warnings = warnings or []
        self.ready = len(self.blockers) == 0
        if self.ready:
            self.status = "ready_with_warnings" if self.warnings else "ready"
        else:
            self.status = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status,
            "blockers": [b.to_dict() for b in self.blockers],
            "warnings": [w.to_dict() for w in self.warnings],
        }
