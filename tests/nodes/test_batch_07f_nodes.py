from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import polars as pl

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.step import StepSpec
from cardre.nodes.contracts import NodeContext, NodeResult, RuntimeMeta
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


class FakeInputs:
    def __init__(
        self,
        artifacts: list[Any],
        frames: dict[str, pl.DataFrame],
        evidence: dict[EvidenceKind, list[Any]],
        metadata: Any | None = None,
    ) -> None:
        self.artifacts = artifacts
        self.frames = frames
        self.evidence = evidence
        self.metadata = metadata

    def by_role(self, role: str) -> list[Any]:
        return [artifact for artifact in self.artifacts if artifact.role == role]

    def by_kind(self, kind: EvidenceKind) -> list[Any]:
        return self.evidence.get(kind, [])

    def first(self, role: str) -> Any | None:
        artifacts = self.by_role(role)
        return artifacts[0] if artifacts else None

    def require(self, role: str, node_type: str) -> Any:
        artifact = self.first(role)
        if artifact is None:
            raise ValueError(f"{node_type} requires {role}")
        return artifact

    def read(self, artifact: Any, kind: EvidenceKind) -> Any:
        return self.evidence[kind][0]

    def read_dataframe(self, artifact: Any) -> pl.DataFrame:
        return self.frames[artifact.artifact_id]

    def target_metadata(self) -> Any | None:
        return self.metadata


class FakeOutputs:
    def __init__(self) -> None:
        self.tables: list[tuple[str, EvidenceKind, pl.DataFrame, dict[str, Any] | None, str | None]] = []
        self.json: list[tuple[str, EvidenceKind, dict[str, Any], dict[str, Any] | None]] = []
        self.metrics: dict[str, Any] = {}
        self.warnings: list[dict[str, Any]] = []

    def publish_table(
        self,
        *,
        role: str,
        kind: EvidenceKind,
        frame: pl.DataFrame,
        metadata: dict[str, Any] | None = None,
        artifact_type: str | None = None,
    ) -> None:
        self.tables.append((role, kind, frame, metadata, artifact_type))

    def publish_json(
        self,
        *,
        role: str,
        kind: EvidenceKind,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.json.append((role, kind, payload, metadata))

    def add_metric(self, name: str, value: Any) -> None:
        self.metrics[name] = value

    def add_warning(self, warning: dict[str, Any]) -> None:
        self.warnings.append(warning)

    def build_result(self) -> NodeResult:
        return NodeResult(metrics=self.metrics, warnings=self.warnings)


def make_context(inputs: FakeInputs, outputs: FakeOutputs, params: dict[str, Any]) -> NodeContext:
    spec = StepSpec(
        step_id="step",
        node_type="test.node",
        node_version="1",
        category="test",
        params=params,
        params_hash="hash",
        parent_step_ids=[],
    )
    return NodeContext(
        run_id="run",
        plan_version_id="plan",
        step_spec=spec,
        inputs=inputs,
        outputs=outputs,
        params=params,
        runtime=RuntimeMeta("run", "plan", "step", "test.node"),
    )


def test_reject_population_and_none_publish_typed_outputs() -> None:
    source = SimpleNamespace(artifact_id="source", role="input")
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
    outputs = FakeOutputs()
    result = DefineRejectPopulationNode().run(
        make_context(
            FakeInputs(
                [source],
                {"source": source_frame},
                {EvidenceKind.SAMPLE_DEFINITION: [sample_definition]},
                metadata,
            ),
            outputs,
            {},
        )
    )

    assert isinstance(result, NodeResult)
    assert outputs.tables[0][1] is EvidenceKind.MODELLING_METADATA
    assert outputs.tables[0][4] == "dataset"
    assert outputs.json[0][1] is EvidenceKind.REJECT_POPULATION_CONFIG
    assert outputs.metrics == {
        "total_rows": 3,
        "financed_rows": 2,
        "non_financed_rows": 1,
        "excluded_rows": 0,
    }

    classified = SimpleNamespace(artifact_id="classified", role="input")
    config = SimpleNamespace(financed_rows=2, non_financed_rows=1)
    none_outputs = FakeOutputs()
    none_result = RejectInferenceNoneNode().run(
        make_context(
            FakeInputs(
                [classified],
                {"classified": outputs.tables[0][2]},
                {EvidenceKind.REJECT_POPULATION_CONFIG: [config]},
            ),
            none_outputs,
            {},
        )
    )

    assert isinstance(none_result, NodeResult)
    assert none_outputs.tables[0][2].height == 2
    assert none_outputs.json[0][1] is EvidenceKind.REJECT_INFERENCE_RESULT
    assert none_outputs.json[0][2]["method"] == "none"


def test_reject_augmentation_no_rejects_publishes_typed_outputs() -> None:
    source = SimpleNamespace(artifact_id="source", role="input")
    frame = pl.DataFrame({"target": ["good", "bad"], "_ri_financed": [True, True]})
    outputs = FakeOutputs()

    result = RejectInferenceAugmentationNode().run(
        make_context(
            FakeInputs(
                [source],
                {"source": frame},
                {EvidenceKind.REJECT_POPULATION_CONFIG: [SimpleNamespace(financed_rows=2, non_financed_rows=0)]},
            ),
            outputs,
            {},
        )
    )

    assert isinstance(result, NodeResult)
    assert outputs.tables[0][1] is EvidenceKind.MODELLING_METADATA
    assert outputs.tables[0][4] == "dataset"
    assert "_ri_financed" not in outputs.tables[0][2].columns
    assert outputs.json[0][1] is EvidenceKind.REJECT_INFERENCE_RESULT


def test_fairness_and_governance_reports_use_output_publisher() -> None:
    train = SimpleNamespace(artifact_id="train", role="train")
    frame = pl.DataFrame(
        {
            "segment": ["a"] * 5 + ["b"] * 5,
            "predicted_bad_probability": [0.1] * 5 + [0.9] * 5,
            "score": [700] * 5 + [500] * 5,
            "target": ["good"] * 5 + ["bad"] * 5,
        }
    )
    metadata = SimpleNamespace(target_column="target", bad_values=frozenset({"bad"}))

    fairness_outputs = FakeOutputs()
    fairness_result = FairnessReportNode().run(
        make_context(
            FakeInputs([train], {"train": frame}, {}, metadata),
            fairness_outputs,
            {"sensitive_columns": ["segment"], "min_group_size": 5},
        )
    )

    assert isinstance(fairness_result, NodeResult)
    assert fairness_outputs.json[0][1] is EvidenceKind.FAIRNESS_REPORT
    assert fairness_outputs.json[0][2]["schema_version"] == "cardre.fairness_report.v1"

    proxy_outputs = FakeOutputs()
    proxy_result = ProxyRiskReportNode().run(
        make_context(
            FakeInputs([train], {"train": frame}, {}),
            proxy_outputs,
            {"sensitive_columns": ["segment"]},
        )
    )

    assert isinstance(proxy_result, NodeResult)
    assert proxy_outputs.json[0][1] is EvidenceKind.PROXY_RISK_REPORT

    manifest_outputs = FakeOutputs()
    manifest_result = AlternativeDataManifestNode().run(
        make_context(
            FakeInputs([train], {"train": frame}, {}),
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
    )

    assert isinstance(manifest_result, NodeResult)
    assert manifest_outputs.json[0][1] is EvidenceKind.REPORT_BUNDLE
    assert manifest_outputs.metrics["total_sources"] == 1
