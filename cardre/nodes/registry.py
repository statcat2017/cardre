"""Node registry for Cardre pipeline nodes.

Each node type defines a node_type identifier, version, category,
input/output roles, params schema, and an executable run method.

Node tiers:
- launch: nodes that are executable at launch (canonical scorecard journey).
  Instantiating a deferred node raises NodeNotAvailableForLaunch.
- deferred: nodes that exist as registered schemas for UI display but are
  not executable at launch (boosting, ensembles, fairness, etc.).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Literal

from cardre.config import CardreConfig
from cardre.nodes.contracts import NodeType

NodeTier = Literal["launch", "deferred"]


@dataclass(frozen=True)
class NodeAvailability:
    """Whether a node type can be instantiated right now, and why not."""
    available: bool
    tier: str
    disabled_reason: str | None = None
    missing_optional_dependencies: list[str] = field(default_factory=list)


_OPTIONAL_DEP_MODULES: dict[str, tuple[str, ...]] = {
    "xgboost": ("xgboost",),
    "lightgbm": ("lightgbm",),
    "catboost": ("catboost",),
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
        cls = self._nodes.get(node_type)
        if cls is None:
            return NodeAvailability(
                available=False,
                tier="unknown",
                disabled_reason=f"Unknown node type {node_type!r}.",
            )
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
            )

        return NodeAvailability(available=True, tier=tier)

    def is_available(self, node_type: str) -> bool:
        return self.availability(node_type).available

    def instantiate(self, node_type: str) -> NodeType:
        cls = self.resolve(node_type)
        av = self.availability(node_type)
        if not av.available:
            if av.tier == "deferred" and CardreConfig.from_env().launch_mode:
                from cardre.domain.errors import NodeNotAvailableForLaunch
                raise NodeNotAvailableForLaunch(
                    f"Node {node_type!r} is not available in launch mode. "
                    f"It will be available in a future release."
                )
            if av.missing_optional_dependencies:
                from cardre.domain.errors import OptionalDependencyNotInstalled
                raise OptionalDependencyNotInstalled(
                    node_type=node_type,
                    missing_groups=av.missing_optional_dependencies,
                )
        return cls()

    @classmethod
    def with_defaults(cls) -> NodeRegistry:
        """Create a registry pre-loaded with the built-in node catalog."""
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
    from cardre.nodes.prep import (
        DefineModellingMetadataNode,
        ImportGermanCreditNode,
        ImportTabularDatasetNode,
        ProfileDatasetNode,
        SplitTrainTestOotNode,
        ValidateBinaryTargetNode,
    )
    from cardre.nodes.build import (
        BinningNode,
        BuildSummaryReportNode,
        CalculateWoeIvNode,
        FineClassingNode,
        FrozenScorecardBundleNode,
        LogisticRegressionNode,
        ManualBinningNode,
        NoopNode,
        ScoreScalingNode,
        TechnicalManifestExportNode,
        VariableClusteringNode,
        VariableSelectionNode,
        WoeTransformTrainNode,
    )
    from cardre.nodes.validate import (
        ApplyModelNode,
        ApplyWoeMappingNode,
        CutoffAnalysisNode,
        DummyApplyNode,
        ValidationMetricsNode,
    )

    for n in [
        BinningNode,
        DefineModellingMetadataNode,
        ImportGermanCreditNode,
        ImportTabularDatasetNode,
        ProfileDatasetNode,
        ValidateBinaryTargetNode,
        SplitTrainTestOotNode,
        FineClassingNode,
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
        ApplyWoeMappingNode,
        ApplyModelNode,
        ValidationMetricsNode,
        CutoffAnalysisNode,
        DummyApplyNode,
    ]:
        reg.register(n)


# ---------------------------------------------------------------------------
# Deferred-tier nodes (registered for schema display, not executable at launch)
# ---------------------------------------------------------------------------

def _register_deferred_nodes(reg: NodeRegistry) -> None:
    from cardre.nodes import (
        AlternativeDataManifestNode,
        CatBoostClassifierNode,
        DecisionTreeNode,
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
        DecisionTreeNode,
    ]:
        reg.register(_deferred(n))
