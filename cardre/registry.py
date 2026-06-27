"""Node registry for Cardre pipeline nodes.

Each node type defines a node_type identifier, version, category,
input/output roles, params schema, and an executable run method.

Node tiers:
- launch: nodes that are executable at launch (canonical scorecard journey
  plus decision-tree challenger). Instantiating a deferred node raises
  NodeNotAvailableForLaunch.
- deferred: nodes that exist as registered schemas for UI display but are
  not executable at launch (boosting, ensembles, fairness, etc.).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field

from cardre.audit import NodeType
from cardre.config import CardreConfig


@dataclass(frozen=True)
class NodeAvailability:
    """Whether a node type can be instantiated right now, and why not."""
    available: bool
    tier: str
    disabled_reason: str | None = None
    missing_optional_dependencies: list[str] = field(default_factory=list)


_OPTIONAL_DEP_MODULES: dict[str, tuple[str, ...]] = {
    "boosting": ("xgboost", "lightgbm", "catboost"),
    "imbalance": ("imblearn",),
    "explain": ("shap", "lime"),
    "deep": ("torch",),
    "optimal-binning": ("optbinning",),
}


def _probe_optional_dep(group: str) -> bool:
    for mod in _OPTIONAL_DEP_MODULES.get(group, ()):
        if importlib.util.find_spec(mod) is None:
            return False
    return True


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

    def availability(self, node_type: str) -> NodeAvailability:
        cls = self.resolve(node_type)
        is_deferred = getattr(cls, "_deferred", False)
        tier = "deferred" if is_deferred else "launch"

        missing = [
            g for g in (getattr(cls, "optional_dependencies", None) or [])
            if not _probe_optional_dep(g)
        ]

        if missing:
            return NodeAvailability(
                available=False,
                tier=tier,
                disabled_reason=(
                    f"Optional dependency group(s) not installed: "
                    f"{', '.join(missing)}. "
                    f"Install with: pip install -e '.[{','.join(missing)}]'"
                ),
                missing_optional_dependencies=missing,
            )

        if is_deferred and CardreConfig.from_env().launch_mode:
            return NodeAvailability(
                available=False,
                tier=tier,
                disabled_reason=(
                    "Not available in launch mode. "
                    "This method will be enabled in a future release."
                ),
                missing_optional_dependencies=missing,
            )

        return NodeAvailability(available=True, tier=tier)

    def is_available(self, node_type: str) -> bool:
        return self.availability(node_type).available

    def instantiate(self, node_type: str) -> NodeType:
        cls = self.resolve(node_type)
        av = self.availability(node_type)
        if not av.available:
            if av.tier == "deferred" and CardreConfig.from_env().launch_mode:
                from cardre.errors import NodeNotAvailableForLaunch
                raise NodeNotAvailableForLaunch(
                    f"Node {node_type!r} is not available in launch mode. "
                    f"It will be available in a future release."
                )
            if av.missing_optional_dependencies:
                from cardre.errors import OptionalDependencyNotInstalled
                raise OptionalDependencyNotInstalled(
                    node_type=node_type,
                    missing_groups=av.missing_optional_dependencies,
                )
        return cls()

    @classmethod
    def with_defaults(cls) -> NodeRegistry:
        """Create a registry pre-loaded with launch-tier nodes.

        Deferred nodes are registered but guarded behind the
        CARDRE_LAUNCH_MODE flag — they render in the UI via
        their parameter schemas but raise NodeNotAvailableForLaunch
        on instantiation when launch mode is active.
        """
        reg = cls()
        _register_launch_nodes(reg)
        _register_deferred_nodes(reg)
        return reg

    def list_launch_nodes(self) -> list[str]:
        """Node types in the launch tier."""
        return [nt for nt, cls in self._nodes.items()
                if not getattr(cls, "_deferred", False)]

    def list_deferred_nodes(self) -> list[str]:
        """Node types in the deferred tier."""
        return [nt for nt, cls in self._nodes.items()
                if getattr(cls, "_deferred", False)]


def _deferred(cls: type[NodeType]) -> type[NodeType]:
    """Mark a node class as deferred (not executable at launch)."""
    cls._deferred = True
    return cls


# ---------------------------------------------------------------------------
# Launch-tier nodes
# ---------------------------------------------------------------------------

def _register_launch_nodes(reg: NodeRegistry) -> None:
    from cardre.nodes import (
        AutoBinningFitNode,
        BinningNode,
        ApplyExclusionsNode,
        ApplyModelNode,
        ApplyWoeMappingNode,
        BuildSummaryReportNode,
        CalculateWoeIvNode,
        CutoffAnalysisNode,
        DecisionTreeNode,
        DefineModellingMetadataNode,
        DefineRejectPopulationNode,
        DevelopmentSampleDefinitionNode,
        DummyApplyNode,
        DummyFitNode,
        ExplicitMissingOutlierTreatmentNode,
        FineClassingNode,
        FrozenScorecardBundleNode,
        ImportGermanCreditNode,
        ImportTabularDatasetNode,
        LogisticRegressionNode,
        ManualBinningNode,
        NoopNode,
        ProfileDatasetNode,
        ScoreScalingNode,
        SplitTrainTestOotNode,
        TechnicalManifestExportNode,
        ThresholdOptimizationNode,
        ValidateBinaryTargetNode,
        ValidationMetricsNode,
        VariableClusteringNode,
        VariableSelectionNode,
        WoeTransformTrainNode,
    )

    for n in [
        BinningNode,
        ImportGermanCreditNode,
        ImportTabularDatasetNode,
        ProfileDatasetNode,
        ValidateBinaryTargetNode,
        SplitTrainTestOotNode,
        DummyFitNode,
        DummyApplyNode,
        DefineModellingMetadataNode,
        DefineRejectPopulationNode,
        ApplyExclusionsNode,
        DevelopmentSampleDefinitionNode,
        ExplicitMissingOutlierTreatmentNode,
        AutoBinningFitNode,
        FineClassingNode,
        CalculateWoeIvNode,
        VariableClusteringNode,
        VariableSelectionNode,
        ManualBinningNode,
        NoopNode,
        TechnicalManifestExportNode,
        WoeTransformTrainNode,
        LogisticRegressionNode,
        DecisionTreeNode,
        ScoreScalingNode,
        FrozenScorecardBundleNode,
        BuildSummaryReportNode,
        ApplyWoeMappingNode,
        ApplyModelNode,
        ValidationMetricsNode,
        ThresholdOptimizationNode,
        CutoffAnalysisNode,
    ]:
        reg.register(n)


# ---------------------------------------------------------------------------
# Deferred-tier nodes (registered for schema display, not executable at launch)
# ---------------------------------------------------------------------------

def _register_deferred_nodes(reg: NodeRegistry) -> None:
    from cardre.nodes import (
        AlternativeDataManifestNode,
        CatBoostClassifierNode,
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
        VotingEnsembleNode,
        WeightedEnsembleNode,
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
        VotingEnsembleNode,
        WeightedEnsembleNode,
    ]:
        reg.register(_deferred(n))
