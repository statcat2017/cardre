"""Node catalogue for Cardre pipeline nodes.

Replaces ``cardre/nodes/registry.py`` (Batch 04). The catalogue is built
from ``Settings`` + a list of node classes, replacing the old
``NodeRegistry.with_defaults()`` pattern.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Literal

from cardre.bootstrap.settings import Settings
from cardre.nodes.contracts import NodeType

NodeTier = Literal["launch", "deferred"]


@dataclass(frozen=True)
class NodeAvailability:
    available: bool
    tier: str
    disabled_reason: str | None = None
    missing_optional_dependencies: list[str] = field(default_factory=list)


_OPTIONAL_DEP_MODULES: dict[str, tuple[str, ...]] = {
    "xgboost": ("xgboost",),
    "lightgbm": ("lightgbm",),
    "catboost": ("catboost",),
    "imbalance": ("imblearn",),
    "explain": ("shap",),
    "deep": ("torch",),
    "optimal-binning": ("optbinning",),
}


def _probe_optional_dep(group: str) -> bool:
    for mod in _OPTIONAL_DEP_MODULES.get(group, ()):
        if importlib.util.find_spec(mod) is None:
            return False
    return True


def _resolve_tier(cls: type[NodeType]) -> NodeTier:
    if getattr(cls, "_deferred", False):
        return "deferred"
    definition = getattr(cls, "_NodeType__definition_cached", None)
    if definition is not None and hasattr(definition, "tier"):
        return definition.tier
    return getattr(cls, "tier", "launch")


class NodeCatalogue:
    def __init__(
        self,
        settings: Settings,
        node_classes: list[type[NodeType]],
    ) -> None:
        self._settings = settings
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

    def availability(self, node_type: str) -> NodeAvailability:
        cls = self._nodes.get(node_type)
        if cls is None:
            return NodeAvailability(
                available=False,
                tier="unknown",
                disabled_reason=f"Unknown node type {node_type!r}.",
            )
        tier = _resolve_tier(cls)

        dep_groups = getattr(cls, "optional_dependencies", None) or ()
        missing = [g for g in dep_groups if not _probe_optional_dep(g)]

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

        if tier == "deferred" and self._settings.launch_mode:
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
            if av.tier == "deferred" and self._settings.launch_mode:
                from cardre.domain.errors import NodeNotAvailableForLaunch
                raise NodeNotAvailableForLaunch(
                    f"Node {node_type!r} is not available in launch mode. "
                    f"It will be available in a future release.",
                )
            if av.missing_optional_dependencies:
                from cardre.domain.errors import OptionalDependencyNotInstalled
                raise OptionalDependencyNotInstalled(
                    node_type=node_type,
                    missing_groups=av.missing_optional_dependencies,
                )
        return cls()

    def list_types_by_tier(self, tier: NodeTier) -> list[str]:
        return [
            nt for nt, cls in self._nodes.items()
            if _resolve_tier(cls) == tier
        ]

    def list_launch_types(self) -> list[str]:
        return self.list_types_by_tier("launch")

    def list_deferred_types(self) -> list[str]:
        return self.list_types_by_tier("deferred")


def _deferred(cls: type[NodeType]) -> type[NodeType]:
    cls._deferred = True
    return cls


def build_default_catalogue(settings: Settings) -> NodeCatalogue:
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

    launch_nodes: list[type[NodeType]] = [
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
    ]

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

    deferred_nodes: list[type[NodeType]] = [
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
    ]

    for n in deferred_nodes:
        _deferred(n)

    return NodeCatalogue(settings, launch_nodes + deferred_nodes)
