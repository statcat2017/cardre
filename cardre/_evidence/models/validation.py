"""Validation metrics data models."""

from __future__ import annotations

from dataclasses import dataclass, field

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class RoleMetrics:
    row_count: int = 0
    auc: float | None = None
    gini: float | None = None
    ks: float | None = None
    bad_rate: float | None = None


@dataclass(frozen=True)
class ValidationMetrics:
    metrics_by_role: dict[str, RoleMetrics] = field(default_factory=dict)
    psi: dict[str, float] = field(default_factory=dict)
    target: JsonDict = field(default_factory=dict)
    gates: list[JsonDict] = field(default_factory=list)
    warnings: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ValidationMetrics:
        metrics_by_role: dict[str, RoleMetrics] = {}
        raw_metrics = data.get("roles", {})

        for role, m in raw_metrics.items():
            bad_rate: float | None = m.get("bad_rate")
            if bad_rate is None and "bad_count" in m and "row_count" in m:
                rc = m.get("row_count", 0)
                bad_rate = float(m["bad_count"]) / rc if rc > 0 else None
            metrics_by_role[role] = RoleMetrics(
                row_count=m.get("row_count", 0),
                auc=m.get("auc"),
                gini=m.get("gini"),
                ks=m.get("ks"),
                bad_rate=bad_rate,
            )

        psi: dict[str, float] = {}
        raw_psi = data.get("stability", {})
        if isinstance(raw_psi, dict):
            psi = {k: float(v) for k, v in raw_psi.items() if isinstance(v, (int, float))}

        return cls(
            metrics_by_role=metrics_by_role,
            psi=psi,
            target=dict(data.get("target", {})),
            gates=list(data.get("gates", [])),
            warnings=list(data.get("warnings", [])),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class CutoffRow:
    score_cutoff: float = 0.0
    approval_rate: float = 0.0
    bad_rate: float = 0.0
    capture_rate: float = 0.0


@dataclass(frozen=True)
class CutoffAnalysis:
    cutoff_tables: dict[str, list[CutoffRow]] = field(default_factory=dict)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> CutoffAnalysis:
        raw_tables = data.get("cutoff_tables", {})
        tables: dict[str, list[CutoffRow]] = {}
        for role, rows in raw_tables.items():
            if isinstance(rows, list):
                tables[role] = [
                    CutoffRow(
                        score_cutoff=r.get("score_cutoff", 0),
                        approval_rate=r.get("approval_rate", 0.0),
                        bad_rate=r.get("bad_rate", 0.0),
                        capture_rate=r.get("capture_rate", 0.0),
                    )
                    for r in rows
                ]
        return cls(cutoff_tables=tables, source_artifact_id=artifact_id)
