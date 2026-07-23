from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardre.application.reporting.export_audit_pack import ExportAuditPack, ExportAuditPackCommand
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.errors import CardreError
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


class _Branches:
    def get_branch(self, branch_id):
        if branch_id == "branch":
            return {"branch_id": "branch", "project_id": "project", "plan_id": "plan", "head_plan_version_id": "pv"}
        if branch_id == "source":
            return {"branch_id": "source", "project_id": "project", "plan_id": "plan", "head_plan_version_id": "source-pv"}
        return None

    def get_step_map(self, branch_id, plan_version_id):
        if branch_id == "branch":
            return [{
                "canonical_step_id": "import-data", "step_id": "local-step",
                "is_shared_upstream": True, "source_branch_id": "source", "source_step_id": "shared-step",
            }]
        return []


class _Runs:
    def __init__(self, runs):
        self.runs = runs

    def get(self, run_id):
        return self.runs.get(run_id)

    def get_latest_successful_id(self, plan_version_id, branch_id=None):
        return "branch-run" if plan_version_id == "pv" else None

    def get_latest_successful_step_across_plan(self, plan_id, step_id):
        return None


class _RunSteps:
    def __init__(self, local, shared):
        self.local = local
        self.shared = shared

    def get_for_run(self, run_id):
        return [self.local] if run_id == "branch-run" else [self.shared] if run_id == "source-run" else []

    def get(self, run_step_id):
        return {self.local.run_step_id: self.local, self.shared.run_step_id: self.shared}.get(run_step_id)

    def get_latest_successful_step(self, plan_version_id, step_id, branch_id=None):
        if (plan_version_id, step_id, branch_id) == ("source-pv", "shared-step", "source"):
            return self.shared
        return None


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


class _OptionalRepo:
    def get_comparison_snapshot(self, snapshot_id):
        return None

    def get_champion_assignment(self, plan_id, branch_id=None):
        return None


class _Uow:
    def __init__(self):
        local = RunStep("local", "branch-run", "local-step", "pv", RunStepStatus.SUCCEEDED, "2026-01-01")
        shared = RunStep("shared", "source-run", "shared-step", "source-pv", RunStepStatus.SUCCEEDED, "2026-01-01")
        local_artifact = ArtifactRef("local-artifact", "report", "report", "local", "local-hash", "local-logical")
        shared_artifact = ArtifactRef("shared-artifact", "report", "report", "shared", "shared-hash", "shared-logical")
        self.projects = _Projects()
        self.plans = _Plans()
        self.branches = _Branches()
        self.runs = _Runs({
            "branch-run": Run("branch-run", "pv", "succeeded", "2026-01-01", branch_id="branch"),
            "source-run": Run("source-run", "source-pv", "succeeded", "2026-01-01", branch_id="source"),
        })
        self.run_steps = _RunSteps(local, shared)
        self.artifacts = _Artifacts(
            {local_artifact.artifact_id: local_artifact, shared_artifact.artifact_id: shared_artifact},
            {local.run_step_id: [("output", local_artifact)], shared.run_step_id: [("output", shared_artifact)]},
        )
        self.evidence = _Evidence()
        self.comparisons = _OptionalRepo()
        self.champion = _OptionalRepo()


def _use_case(tmp_path: Path) -> ExportAuditPack:
    return ExportAuditPack(_Factory(_Uow()), lambda project_id: _Reader(), lambda project_id: tmp_path, lambda command: None)


def test_export_includes_shared_upstream_evidence_and_artifacts(tmp_path):
    export_dir = tmp_path / "audit-pack"
    result = _use_case(tmp_path)(ExportAuditPackCommand("project", "plan", "branch", export_path=export_dir))

    assert result.partial is False
    run_steps = json.loads((export_dir / "run_steps.json").read_text())
    assert {row["run_step_id"] for row in run_steps} == {"local", "shared"}
    assert next(row for row in run_steps if row["run_step_id"] == "shared")["source"] == "shared_upstream"
    artifacts = json.loads((export_dir / "artifacts.json").read_text())
    assert {artifact["artifact_id"] for artifact in artifacts} == {"local-artifact", "shared-artifact"}
    assert (export_dir / "artifacts" / "shared-artifact_shared-hash").read_bytes() == b"artifact:shared-artifact"
    assert (export_dir / "checksums.sha256").is_file()


def test_export_rejects_missing_branch(tmp_path):
    with pytest.raises(CardreError) as exc_info:
        _use_case(tmp_path)(ExportAuditPackCommand("project", "plan", "missing", export_path=tmp_path / "audit-pack"))
    assert exc_info.value.code == "BRANCH_NOT_FOUND"
