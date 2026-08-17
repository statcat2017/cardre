from __future__ import annotations

from types import SimpleNamespace

import polars as pl
from node_harness import FakeArtifact, FakeInputCollection, FakeOutputPublisher, make_context

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import NodeResult
from cardre.nodes.fairness import (
    AlternativeDataManifestNode,
    FairnessReportNode,
    ProxyRiskReportNode,
)
from cardre.nodes.reject_inference import (
    DefineRejectPopulationNode,
    RejectInferenceAugmentationNode,
    RejectInferenceNoneNode,
)


def _run(node, inputs, outputs, params):
    return node.run(make_context(inputs, outputs, params))


def test_reject_population_and_none_publish_typed_outputs() -> None:
    source = FakeArtifact(role="input", artifact_id="source")
    metadata = SimpleNamespace(
        target_column="target",
        good_values=frozenset({"good"}),
        bad_values=frozenset({"bad"}),
        indeterminate_values=frozenset(),
    )
    sample_definition = SimpleNamespace(
        sample_domain="ttd",
        rejection_source="flag_column",
        rejection_column="rejected",
        rejection_values=["1"],
    )
    source_frame = pl.DataFrame(
        {"target": ["good", "bad", None], "rejected": [0, 0, 1]}
    )
    source = FakeArtifact(role="input", artifact_id="source", frame=source_frame)
    outputs = FakeOutputPublisher()
    result = _run(
        DefineRejectPopulationNode(),
        FakeInputCollection(
            roles={"input": [source]},
            evidence={EvidenceKind.SAMPLE_DEFINITION: sample_definition},
            target_metadata=metadata,
        ),
        outputs,
        {},
    )

    assert isinstance(result, NodeResult)
    meta_table = outputs.by_kind(EvidenceKind.MODELLING_METADATA)[0]
    assert meta_table.kind is EvidenceKind.MODELLING_METADATA
    assert meta_table.artifact_type == "dataset"
    assert outputs.by_kind(EvidenceKind.REJECT_POPULATION_CONFIG)[0].kind is EvidenceKind.REJECT_POPULATION_CONFIG
    assert outputs.metrics == {
        "total_rows": 3,
        "financed_rows": 2,
        "non_financed_rows": 1,
        "excluded_rows": 0,
    }

    classified = FakeArtifact(
        role="input", artifact_id="classified", frame=meta_table.payload,
    )
    config = SimpleNamespace(financed_rows=2, non_financed_rows=1)
    none_outputs = FakeOutputPublisher()
    none_result = _run(
        RejectInferenceNoneNode(),
        FakeInputCollection(
            roles={"input": [classified]},
            evidence={EvidenceKind.REJECT_POPULATION_CONFIG: config},
        ),
        none_outputs,
        {},
    )

    assert isinstance(none_result, NodeResult)
    assert none_outputs.by_kind(EvidenceKind.MODELLING_METADATA)[0].payload.height == 2
    ri_result = none_outputs.by_kind(EvidenceKind.REJECT_INFERENCE_RESULT)[0]
    assert ri_result.kind is EvidenceKind.REJECT_INFERENCE_RESULT
    assert ri_result.payload["method"] == "none"


def test_reject_augmentation_no_rejects_publishes_typed_outputs() -> None:
    frame = pl.DataFrame({"target": ["good", "bad"], "_ri_financed": [True, True]})
    source = FakeArtifact(role="input", artifact_id="source", frame=frame)
    outputs = FakeOutputPublisher()

    result = _run(
        RejectInferenceAugmentationNode(),
        FakeInputCollection(
            roles={"input": [source]},
            evidence={
                EvidenceKind.REJECT_POPULATION_CONFIG: SimpleNamespace(
                    financed_rows=2, non_financed_rows=0,
                ),
            },
        ),
        outputs,
        {},
    )

    assert isinstance(result, NodeResult)
    meta_table = outputs.by_kind(EvidenceKind.MODELLING_METADATA)[0]
    assert meta_table.kind is EvidenceKind.MODELLING_METADATA
    assert meta_table.artifact_type == "dataset"
    assert "_ri_financed" not in meta_table.payload.columns
    assert outputs.by_kind(EvidenceKind.REJECT_INFERENCE_RESULT)[0].kind is EvidenceKind.REJECT_INFERENCE_RESULT


def test_fairness_and_governance_reports_use_output_publisher() -> None:
    frame = pl.DataFrame(
        {
            "segment": ["a"] * 5 + ["b"] * 5,
            "predicted_bad_probability": [0.1] * 5 + [0.9] * 5,
            "score": [700] * 5 + [500] * 5,
            "target": ["good"] * 5 + ["bad"] * 5,
        }
    )
    metadata = SimpleNamespace(target_column="target", bad_values=frozenset({"bad"}))
    train = FakeArtifact(role="train", artifact_id="train", frame=frame)

    fairness_outputs = FakeOutputPublisher()
    fairness_result = _run(
        FairnessReportNode(),
        FakeInputCollection(roles={"train": [train]}, target_metadata=metadata),
        fairness_outputs,
        {"sensitive_columns": ["segment"], "min_group_size": 5},
    )

    assert isinstance(fairness_result, NodeResult)
    fairness_report = fairness_outputs.by_kind(EvidenceKind.FAIRNESS_REPORT)[0]
    assert fairness_report.kind is EvidenceKind.FAIRNESS_REPORT
    assert fairness_report.payload["schema_version"] == "cardre.fairness_report.v1"

    proxy_outputs = FakeOutputPublisher()
    proxy_result = _run(
        ProxyRiskReportNode(),
        FakeInputCollection(roles={"train": [train]}),
        proxy_outputs,
        {"sensitive_columns": ["segment"]},
    )

    assert isinstance(proxy_result, NodeResult)
    assert proxy_outputs.by_kind(EvidenceKind.PROXY_RISK_REPORT)[0].kind is EvidenceKind.PROXY_RISK_REPORT

    manifest_outputs = FakeOutputPublisher()
    manifest_result = _run(
        AlternativeDataManifestNode(),
        FakeInputCollection(roles={"train": [train]}),
        manifest_outputs,
        {
            "data_sources": [
                {
                    "source_name": "provider",
                    "consent_basis": "consent",
                    "permitted_use": "credit assessment",
                    "columns": ["segment"],
                }
            ]
        },
    )

    assert isinstance(manifest_result, NodeResult)
    assert manifest_outputs.by_kind(EvidenceKind.REPORT_BUNDLE)[0].kind is EvidenceKind.REPORT_BUNDLE
    assert manifest_outputs.metrics["total_sources"] == 1
