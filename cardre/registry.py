"""Node registry for Cardre pipeline nodes.

Each node type defines a node_type identifier, version, category,
input/output roles, params schema, and an executable run method.
"""

from __future__ import annotations

from cardre.audit import ExecutionContext, NodeOutput, NodeType


class NodeRegistry:
    """Registry of available node types.

    Nodes are registered by their ``node_type`` string identifier
    (e.g. ``"cardre.import_dataset"``) and resolved at plan-execution
    time.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, type[NodeType]] = {}

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

    def instantiate(self, node_type: str) -> NodeType:
        cls = self.resolve(node_type)
        return cls()

    @classmethod
    def with_defaults(cls) -> NodeRegistry:
        """Create a registry pre-loaded with proof nodes."""
        reg = cls()
        _register_proof_nodes(reg)
        return reg


def _register_proof_nodes(reg: NodeRegistry) -> None:
    from cardre.nodes import (
        ApplyExclusionsNode,
        ApplyModelNode,
        ApplyWoeMappingNode,
        BuildSummaryReportNode,
        CalculateWoeIvNode,
        CutoffAnalysisNode,
        DefineModellingMetadataNode,
        DevelopmentSampleDefinitionNode,
        DummyApplyNode,
        DummyFitNode,
        ExplicitMissingOutlierTreatmentNode,
        FineClassingNode,
        ImportGermanCreditNode,
        LogisticRegressionNode,
        ManualBinningNode,
        ProfileDatasetNode,
        ScoreScalingNode,
        SplitTrainTestOotNode,
        TechnicalManifestExportNode,
        ValidateBinaryTargetNode,
        ValidationMetricsNode,
        VariableClusteringNode,
        VariableSelectionNode,
        WoeTransformTrainNode,
    )

    for n in [
        ImportGermanCreditNode,
        ProfileDatasetNode,
        ValidateBinaryTargetNode,
        SplitTrainTestOotNode,
        DummyFitNode,
        DummyApplyNode,
        DefineModellingMetadataNode,
        ApplyExclusionsNode,
        DevelopmentSampleDefinitionNode,
        ExplicitMissingOutlierTreatmentNode,
        FineClassingNode,
        CalculateWoeIvNode,
        VariableClusteringNode,
        VariableSelectionNode,
        ManualBinningNode,
        TechnicalManifestExportNode,
        WoeTransformTrainNode,
        LogisticRegressionNode,
        ScoreScalingNode,
        BuildSummaryReportNode,
        ApplyWoeMappingNode,
        ApplyModelNode,
        ValidationMetricsNode,
        CutoffAnalysisNode,
    ]:
        reg.register(n)
