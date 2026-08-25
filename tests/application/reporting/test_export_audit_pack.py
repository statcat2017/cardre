from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardre.application.reporting.export_audit_pack import ExportAuditPack, ExportAuditPackCommand
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.errors import CardreError
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
from cardre.domain.plan import Plan
from cardre.domain.project import Project
from cardre.domain.run import Run, RunStep, RunStepStatus


class _Context:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *args):
        return None


class _Factory:
    def __init__(self, uow):
        self.uow = uow

    def read_only(self, project_id):
        return _Context(self.uow)

    def for_project(self, project_id):
        return _Context(self.uow)


class _Reader:
    def read_bytes(self, artifact):
        return f"artifact:{artifact.artifact_id}".encode()


class _Projects:
    def get(self, project_id):
        return Project(project_id, "Audit project", "2026-01-01", "1")


class _Plans:
    def get_plan(self, plan_id):
        return Plan(plan_id, "project", "Audit plan", "2026-01-01")

    def get_version_steps(self, plan_version_id):
        return []


class _Runs:
    def __init__(self, runs):
        self.runs = runs

    def get(self, run_id):
        return self.runs.get(run_id)


class _RunSteps:
    def __init__(self, local):
        self.local = local

    def get_for_run(self, run_id):
        return [self.local] if run_id == "branch-run" else []

    def get(self, run_step_id):
        return {self.local.run_step_id: self.local}.get(run_step_id)


class _Artifacts:
    def __init__(self, artifacts, lineage):
        self.artifacts = artifacts
        self.lineage = lineage

    def get(self, artifact_id):
        return self.artifacts.get(artifact_id)

    def artifacts_for_run_step(self, run_step_id):
        return self.lineage.get(run_step_id, [])


class _Evidence:
    def get_edges_for_run_step(self, run_step_id):
        return []

    def get_artifacts_for_edge(self, edge_id):
        return []


class _Exports:
    def register(self, **kwargs):
        self.registered = kwargs


class _Uow:
    def __init__(self):
        local = RunStep("local", "branch-run", "local-step", "pv", RunStepStatus.SUCCEEDED, "2026-01-01")
        local_artifact = ArtifactRef("local-artifact", "report", "report", "local", "local-hash", "local-logical")
        self.projects = _Projects()
        self.plans = _Plans()
        self.runs = _Runs({
            "branch-run": Run("branch-run", "pv", "succeeded", "2026-01-01"),
        })
        self.run_steps = _RunSteps(local)
        self.artifacts = _Artifacts(
            {local_artifact.artifact_id: local_artifact},
            {local.run_step_id: [("output", local_artifact)]},
        )
        self.evidence = _Evidence()
        self.exports = _Exports()

    def commit(self):
        pass


def _use_case(tmp_path: Path) -> ExportAuditPack:
    return ExportAuditPack(_Factory(_Uow()), lambda project_id: _Reader(), lambda project_id: tmp_path, lambda command: None)


def test_export_includes_run_evidence_and_artifacts(tmp_path):
    export_dir = tmp_path / "audit-pack"
    result = _use_case(tmp_path)(ExportAuditPackCommand("project", "plan", "branch-run", export_path=export_dir))

    assert result.partial is False
    run_steps = json.loads((export_dir / "run_steps.json").read_text())
    assert {row["run_step_id"] for row in run_steps} == {"local"}
    artifacts = json.loads((export_dir / "artifacts.json").read_text())
    assert {artifact["artifact_id"] for artifact in artifacts} == {"local-artifact"}
    assert (export_dir / "artifacts" / "local-artifact_local-hash").read_bytes() == b"artifact:local-artifact"
    assert (export_dir / "checksums.sha256").is_file()


def test_export_rejects_missing_run(tmp_path):
    with pytest.raises(CardreError) as exc_info:
        _use_case(tmp_path)(ExportAuditPackCommand("project", "plan", "missing", export_path=tmp_path / "audit-pack"))
    assert exc_info.value.code == "RUN_NOT_FOUND"


def test_export_excludes_stale_evidence_edges(tmp_path):
    """Stale evidence edges must not appear in the audit pack."""
    export_dir = tmp_path / "audit-pack"

    stale_edge = EvidenceEdge(
        evidence_edge_id="stale-ee", run_id="branch-run", run_step_id="local",
        plan_version_id="pv", step_id="local-step", parent_step_id="parent",
        source_run_id="branch-run", source_run_step_id="other",
        policy="exact", source_label="test", is_reused=False, is_stale=True,
    )
    current_edge = EvidenceEdge(
        evidence_edge_id="current-ee", run_id="branch-run", run_step_id="local",
        plan_version_id="pv", step_id="local-step", parent_step_id="parent",
        source_run_id="branch-run", source_run_step_id="other",
        policy="exact", source_label="test", is_reused=False, is_stale=False,
    )
    current_artifact = EvidenceArtifact("ea-1", "current-ee", "art-1", "output", "2026-01-01")

    class _StaleEvidence:
        def get_edges_for_run_step(self, run_step_id):
            if run_step_id == "local":
                return [stale_edge, current_edge]
            return []

        def get_artifacts_for_edge(self, edge_id):
            if edge_id == "current-ee":
                return [current_artifact]
            return []

    local_artifact = ArtifactRef("art-1", "report", "report", "local", "h1", "lh1")
    local_step = RunStep("local", "branch-run", "local-step", "pv", RunStepStatus.SUCCEEDED, "2026-01-01")

    class _UowWithStale(_Uow):
        def __init__(self):
            super().__init__()
            self.evidence = _StaleEvidence()
            self.artifacts = _Artifacts(
                {local_artifact.artifact_id: local_artifact},
                {local_step.run_step_id: [("output", local_artifact)]},
            )
            self.run_steps = _RunSteps(local_step)

    use_case = ExportAuditPack(
        _Factory(_UowWithStale()),
        lambda project_id: _Reader(),
        lambda project_id: tmp_path,
        lambda command: None,
    )
    use_case(ExportAuditPackCommand("project", "plan", "branch-run", export_path=export_dir))

    evidence = json.loads((export_dir / "evidence.json").read_text())
    edge_ids = {e["edge"]["evidence_edge_id"] for e in evidence}
    assert "stale-ee" not in edge_ids
    assert "current-ee" in edge_ids
