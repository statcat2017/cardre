"""Node catalogue for Cardre pipeline nodes.

Built from a list of node classes, replacing the old ``NodeRegistry.with_defaults()``
pattern.
"""

from __future__ import annotations

from cardre.nodes.contracts import NodeType


class NodeCatalogue:
    def __init__(
        self,
        node_classes: list[type[NodeType]],
    ) -> None:
        self._nodes: dict[str, type[NodeType]] = {}
        for cls in node_classes:
            node_type = getattr(cls, "node_type", None)
            if node_type is not None:
                self._nodes[node_type] = cls

    def resolve(self, node_type: str) -> type[NodeType]:
        cls = self._nodes.get(node_type)
        if cls is None:
            raise KeyError(f"Unknown node type {node_type!r}")
        return cls

    def has(self, node_type: str) -> bool:
        return node_type in self._nodes

    def list_types(self) -> list[str]:
        return list(self._nodes.keys())

    def instantiate(self, node_type: str) -> NodeType:
        cls = self.resolve(node_type)
        return cls()


def build_default_catalogue() -> NodeCatalogue:
    from cardre.nodes.build import (
        AutomaticBinningNode,
        BuildSummaryReportNode,
        CalculateWoeIvNode,
        CalibrationDiagnosticsNode,
        CoefficientSignCheckNode,
        FrozenScorecardBundleNode,
        LogisticRegressionNode,
        ManualBinningNode,
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

    node_classes: list[type[NodeType]] = [
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
    ]

    return NodeCatalogue(node_classes)
