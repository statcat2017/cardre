"""Backward-compat shim — replaced by ``cardre/bootstrap/node_catalogue.py``.

This file will be removed in Batch 05.  New code must use
``NodeCatalogue`` from ``cardre.bootstrap.node_catalogue``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.nodes.contracts import NodeType


@dataclass(frozen=True)
class _NodeAvailability:
    available: bool = False
    tier: str = "unknown"
    disabled_reason: str | None = None
    missing_optional_dependencies: list[str] = field(default_factory=list)


class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, type[NodeType]] = {}
        self._available: dict[str, Any] = {}

    def register(self, cls: type[NodeType]) -> type[NodeType]:
        node_type = getattr(cls, "node_type", None)
        if node_type is None:
            raise ValueError(f"{cls.__name__} must define node_type")
        self._nodes[node_type] = cls
        return cls

    def resolve(self, node_type: str) -> type[NodeType]:
        cls = self._nodes.get(node_type)
        if cls is None:
            raise KeyError(f"Unknown node type {node_type!r}")
        return cls

    def has(self, node_type: str) -> bool:
        return node_type in self._nodes

    def list_types(self) -> list[str]:
        return list(self._nodes.keys())

    def availability(self, node_type: str) -> Any:
        cls = self._nodes.get(node_type)
        if cls is None:
            return _NodeAvailability(available=False, tier="unknown", disabled_reason=f"Unknown node type {node_type!r}.")
        return _NodeAvailability(available=True, tier="launch")

    def is_available(self, node_type: str) -> bool:
        return self.availability(node_type).available

    def instantiate(self, node_type: str) -> NodeType:
        cls = self.resolve(node_type)
        return cls()

    @classmethod
    def with_defaults(cls) -> NodeRegistry:
        reg = cls()
        _register_launch_nodes(reg)
        _register_deferred_nodes(reg)
        return reg

    def list_launch_nodes(self) -> list[str]:
        return [nt for nt, cls in self._nodes.items() if not getattr(cls, "_deferred", False)]

    def list_deferred_nodes(self) -> list[str]:
        return [nt for nt, cls in self._nodes.items() if getattr(cls, "_deferred", False)]

    @property
    def catalogue(self) -> Any:
        raise RuntimeError("NodeRegistry stub — use NodeCatalogue")


def _deferred(cls: type[NodeType]) -> type[NodeType]:
    cls._deferred = True
    return cls


def _register_launch_nodes(reg: NodeRegistry) -> None:
    from cardre.nodes.build import (
        AutomaticBinningNode,
        BuildSummaryReportNode,
        CalculateWoeIvNode,
        CalibrationDiagnosticsNode,
        CoefficientSignCheckNode,
        FrozenScorecardBundleNode,
        LogisticRegressionNode,
        ManualBinningNode,
        NoopNode,
        PythonScoringExportNode,
        ScorecardTableExportNode,
        ScoreScalingNode,
        SeparationDiagnosticsNode,
        SqlScoringExportNode,
        TechnicalManifestExportNode,
        VariableClusteringNode,
        VariableSelectionNode,
        VifDiagnosticsNode,
        WoeTransformTrainNode,
    )
    from cardre.nodes.prep import (
        ApplyExclusionsNode,
        DefineModellingMetadataNode,
        DevelopmentSampleDefinitionNode,
        ExplicitMissingOutlierTreatmentNode,
        ImportTabularDatasetNode,
        ProfileDatasetNode,
        SplitTrainTestOotNode,
        ValidateBinaryTargetNode,
    )
    from cardre.nodes.validate import (
        ApplyModelNode,
        ApplyWoeMappingNode,
        CutoffAnalysisNode,
        ValidationMetricsNode,
    )

    for n in [
        ApplyExclusionsNode,
        DevelopmentSampleDefinitionNode,
        DefineModellingMetadataNode,
        ExplicitMissingOutlierTreatmentNode,
        CoefficientSignCheckNode,
        CalibrationDiagnosticsNode,
        SeparationDiagnosticsNode,
        VifDiagnosticsNode,
        ImportTabularDatasetNode,
        ProfileDatasetNode,
        ValidateBinaryTargetNode,
        SplitTrainTestOotNode,
        AutomaticBinningNode,
        CalculateWoeIvNode,
        VariableClusteringNode,
        VariableSelectionNode,
        ManualBinningNode,
        NoopNode,
        TechnicalManifestExportNode,
        WoeTransformTrainNode,
        LogisticRegressionNode,
        ScoreScalingNode,
        FrozenScorecardBundleNode,
        BuildSummaryReportNode,
        ScorecardTableExportNode,
        PythonScoringExportNode,
        SqlScoringExportNode,
        ApplyWoeMappingNode,
        ApplyModelNode,
        ValidationMetricsNode,
        CutoffAnalysisNode,
    ]:
        reg.register(n)


def _register_deferred_nodes(reg: NodeRegistry) -> None:
    from cardre.nodes import (
        AlternativeDataManifestNode,
        CalibrateProbabilitiesNode,
        CatBoostClassifierNode,
        DecisionTreeNode,
        DefineRejectPopulationNode,
        FairnessReportNode,
        FeatureSelectionEmbeddedNode,
        FeatureSelectionFilterNode,
        GradientBoostingClassifierNode,
        HyperparameterTuningNode,
        LightGBMClassifierNode,
        ModelExplainabilityNode,
        ModelLimitationsNode,
        ProxyRiskReportNode,
        RandomForestClassifierNode,
        RejectInferenceAugmentationNode,
        RejectInferenceNoneNode,
        ResampleTrainingDataNode,
        SmoteTrainingDataNode,
        ThresholdOptimizationNode,
        XGBoostClassifierNode,
    )

    for n in [
        RandomForestClassifierNode,
        GradientBoostingClassifierNode,
        XGBoostClassifierNode,
        LightGBMClassifierNode,
        CatBoostClassifierNode,
        FeatureSelectionFilterNode,
        FeatureSelectionEmbeddedNode,
        HyperparameterTuningNode,
        ResampleTrainingDataNode,
        SmoteTrainingDataNode,
        ModelExplainabilityNode,
        ModelLimitationsNode,
        FairnessReportNode,
        ProxyRiskReportNode,
        AlternativeDataManifestNode,
        RejectInferenceNoneNode,
        RejectInferenceAugmentationNode,
        DecisionTreeNode,
        CalibrateProbabilitiesNode,
        DefineRejectPopulationNode,
        ThresholdOptimizationNode,
    ]:
        reg.register(_deferred(n))
