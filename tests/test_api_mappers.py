from __future__ import annotations

from cardre.api.routes._run_mappings import (
    branch_to_response,
    comparison_to_response,
    evidence_edge_to_response,
    node_type_to_response,
    plan_to_response,
    plan_version_to_response,
    project_to_response,
)
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
from cardre.domain.plan import Plan, PlanVersion


def test_plan_mappers_return_expected_shapes() -> None:
    plan = Plan(plan_id="plan-1", project_id="proj-1", name="Plan", created_at="now")
    version = PlanVersion(
        plan_version_id="pv-1",
        plan_id="plan-1",
        version_number=2,
        is_committed=True,
        created_at="now",
        description="Base",
    )

    assert plan_to_response(plan).model_dump() == {
        "plan_id": "plan-1",
        "project_id": "proj-1",
        "name": "Plan",
        "created_at": "now",
    }
    assert plan_version_to_response(version).model_dump() == {
        "plan_version_id": "pv-1",
        "plan_id": "plan-1",
        "version_number": 2,
        "is_committed": True,
        "created_at": "now",
        "description": "Base",
    }


def test_branch_comparison_project_and_node_type_mappers() -> None:
    branch = {
        "branch_id": "branch-1",
        "project_id": "proj-1",
        "plan_id": "plan-1",
        "name": "branch",
        "description": None,
        "branch_type": "challenger",
        "status": "active",
        "base_branch_id": None,
        "base_plan_version_id": "pv-base",
        "head_plan_version_id": "pv-head",
        "branch_point_step_id": None,
        "branch_point_canonical_step_id": None,
        "created_reason": "",
        "created_at": "now",
        "updated_at": "later",
    }
    comparison = {
        "comparison_id": "cmp-1",
        "project_id": "proj-1",
        "plan_id": "plan-1",
        "baseline_branch_id": "branch-1",
        "created_at": "now",
        "latest_ready": None,
    }
    project = {
        "project_id": "proj-1",
        "name": "Project",
        "created_at": "now",
        "cardre_version": "0.2.0",
    }

    assert branch_to_response(branch).model_dump() == branch
    assert comparison_to_response(comparison).model_dump() == comparison
    assert project_to_response(project).model_dump() == project
    assert node_type_to_response("cardre.demo", category="fit").model_dump() == {
        "node_type": "cardre.demo",
        "display_name": "demo",
        "description": "",
        "category": "fit",
        "tier": "launch",
        "has_params": True,
    }


def test_evidence_edge_mapper_returns_nested_artifacts() -> None:
    edge = EvidenceEdge(
        evidence_edge_id="ee-1",
        run_id="run-1",
        run_step_id="rs-1",
        plan_version_id="pv-1",
        step_id="step-1",
        parent_step_id="step-0",
        source_run_id="run-0",
        source_run_step_id="rs-0",
        policy="exact",
        source_label="parent",
        is_reused=False,
        is_stale=False,
        stale_reason=None,
        created_at="now",
    )
    artifacts = [
        EvidenceArtifact(
            evidence_artifact_id="ea-1",
            evidence_edge_id="ee-1",
            artifact_id="art-1",
            role="alpha",
            created_at="now",
        ),
        EvidenceArtifact(
            evidence_artifact_id="ea-2",
            evidence_edge_id="ee-1",
            artifact_id="art-2",
            role="zeta",
            created_at="later",
        ),
    ]

    payload = evidence_edge_to_response(edge, artifacts).model_dump()
    assert payload["evidence_edge_id"] == "ee-1"
    assert [artifact["role"] for artifact in payload["artifacts"]] == ["alpha", "zeta"]
