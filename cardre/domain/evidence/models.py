"""Evidence domain types — the two-level model.

``EvidenceEdge``  represents one parent-step's evidence contribution to a
run step, with its own staleness state.  ``EvidenceArtifact`` hangs off an
edge to describe which artifacts came through that edge and in which role.
"""

from __future__ import annotations

from dataclasses import dataclass

from cardre.domain.diagnostics import JsonDict
from cardre.domain.run import RunStep


@dataclass(frozen=True)
class EvidenceEdge:
    """One parent-step evidence contribution to a consuming run step."""
    evidence_edge_id: str
    run_id: str
    run_step_id: str
    plan_version_id: str
    step_id: str
    parent_step_id: str
    source_run_id: str
    source_run_step_id: str
    policy: str
    source_label: str
    is_reused: bool
    is_stale: bool
    stale_reason: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class EvidenceArtifact:
    """An artifact that came through a specific evidence edge."""
    evidence_artifact_id: str
    evidence_edge_id: str
    artifact_id: str
    role: str
    created_at: str = ""


@dataclass(frozen=True)
class ResolvedEvidence:
    """Aggregate view of all evidence for one run step."""
    run_step_id: str
    run_step: RunStep
    edges: list[EvidenceEdge]
    artifacts: list[EvidenceArtifact]
    source_label: str = ""  # "branch", "full_plan", "latest_plan_run", "across_plan", "run"

    def input_artifact_ids(self) -> list[str]:
        return [ea.artifact_id for ea in self.artifacts]

    def edge_for_artifact(self, artifact_id: str) -> EvidenceEdge | None:
        for ea in self.artifacts:
            if ea.artifact_id == artifact_id:
                for e in self.edges:
                    if e.evidence_edge_id == ea.evidence_edge_id:
                        return e
        return None

    def to_dict(self) -> JsonDict:
        return {
            "run_step_id": self.run_step_id,
            "run_step": {
                "run_step_id": self.run_step.run_step_id,
                "run_id": self.run_step.run_id,
                "step_id": self.run_step.step_id,
                "plan_version_id": self.run_step.plan_version_id,
                "status": self.run_step.status.value,
                "started_at": self.run_step.started_at,
                "finished_at": self.run_step.finished_at,
                "execution_fingerprint": self.run_step.execution_fingerprint,
                "warnings": self.run_step.warnings,
                "errors": self.run_step.errors,
            },
            "edges": [
                {
                    "evidence_edge_id": e.evidence_edge_id,
                    "run_id": e.run_id,
                    "run_step_id": e.run_step_id,
                    "plan_version_id": e.plan_version_id,
                    "step_id": e.step_id,
                    "parent_step_id": e.parent_step_id,
                    "source_run_id": e.source_run_id,
                    "source_run_step_id": e.source_run_step_id,
                    "policy": e.policy,
                    "source_label": e.source_label,
                    "is_reused": e.is_reused,
                    "is_stale": e.is_stale,
                    "stale_reason": e.stale_reason,
                    "created_at": e.created_at,
                }
                for e in self.edges
            ],
            "artifacts": [
                {
                    "evidence_artifact_id": ea.evidence_artifact_id,
                    "evidence_edge_id": ea.evidence_edge_id,
                    "artifact_id": ea.artifact_id,
                    "role": ea.role,
                    "created_at": ea.created_at,
                }
                for ea in self.artifacts
            ],
        }


__all__ = ["EvidenceArtifact", "EvidenceEdge", "ResolvedEvidence"]
