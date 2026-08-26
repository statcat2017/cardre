from __future__ import annotations

from cardre.api.mappers import (
    evidence_edge_to_response,
    node_parameter_schema_to_response,
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


def test_project_and_node_type_mappers() -> None:
    project = {
        "project_id": "proj-1",
        "name": "Project",
        "created_at": "now",
        "cardre_version": "0.2.0",
    }

    assert project_to_response(project).model_dump() == project
    assert node_type_to_response("cardre.demo", category="fit").model_dump() == {
        "node_type": "cardre.demo",
        "display_name": "demo",
        "description": "",
        "category": "fit",
        "has_params": True,
        "parameter_schema": None,
    }


def test_node_parameter_schema_mapper_serializes_item_kind() -> None:
    from cardre.nodes.build.manual import ManualBinningNode
    from cardre.nodes.parameters import MethodOption, NodeParameterSchema, ParameterDefinition

    # A structured list must round-trip item_kind into the API DTO.
    schema = ManualBinningNode.parameter_schema()
    response = node_parameter_schema_to_response(schema).model_dump()
    params = {p["name"]: p for p in response["methods"][0]["params"]}
    assert params["overrides"]["kind"] == "list"
    assert params["overrides"]["item_kind"] == "object"

    # Plain params without item_kind default to None.
    schema = NodeParameterSchema(
        node_type="x",
        node_version="1",
        title="",
        default_method="",
        methods=[
            MethodOption(
                id="default",
                label="",
                status="available",
                description="",
                params=[ParameterDefinition(name="tags", kind="list", default=[])],
            )
        ],
    )
    mapped = node_parameter_schema_to_response(schema).model_dump()["methods"][0]["params"][0]
    assert mapped["kind"] == "list"
    assert mapped["item_kind"] is None


def test_selection_schemas_serialize_item_kind_object() -> None:
    from cardre.nodes.build.selection import VariableSelectionNode

    response = node_parameter_schema_to_response(VariableSelectionNode.parameter_schema()).model_dump()
    params = {p["name"]: p for p in response["methods"][0]["params"]}

    for name in ("manual_includes", "manual_excludes", "cluster_representative_overrides"):
        assert params[name]["kind"] == "list"
        assert params[name]["item_kind"] == "object"
        assert params[name]["required"] is False
        assert params[name]["default"] == []


def test_manual_overrides_required_and_object_item_kind() -> None:
    from cardre.nodes.build.manual import ManualBinningNode

    schema = ManualBinningNode.parameter_schema()
    params = {p.name: p for m in schema.methods for p in m.params}
    assert params["overrides"].kind == "list"
    assert params["overrides"].item_kind == "object"
    assert params["overrides"].required is True
    assert params["overrides"].default == []


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
