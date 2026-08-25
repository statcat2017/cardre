"""Node catalogue for Cardre pipeline nodes.

Built from ``Settings`` + a list of node classes, replacing the old
``NodeRegistry.with_defaults()`` pattern.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field

from cardre.bootstrap.settings import Settings
from cardre.nodes.contracts import NodeType


@dataclass(frozen=True)
class NodeAvailability:
    available: bool
    disabled_reason: str | None = None
    missing_optional_dependencies: list[str] = field(default_factory=list)


_OPTIONAL_DEP_MODULES: dict[str, tuple[str, ...]] = {
    "optimal-binning": ("optbinning",),
}


def _probe_optional_dep(group: str) -> bool:
    for mod in _OPTIONAL_DEP_MODULES.get(group, ()):
        if importlib.util.find_spec(mod) is None:
            return False
    return True


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
                disabled_reason=f"Unknown node type {node_type!r}.",
            )

        dep_groups = getattr(cls, "optional_dependencies", None) or ()
        missing = [g for g in dep_groups if not _probe_optional_dep(g)]

        if missing:
            return NodeAvailability(
                available=False,
                disabled_reason=(
                    f"Optional dependency group(s) not installed: "
                    f"{', '.join(missing)}. "
                    f"Install with: pip install -e '.[{','.join(missing)}]'"
                ),
                missing_optional_dependencies=missing,
            )

        return NodeAvailability(available=True)

    def is_available(self, node_type: str) -> bool:
        return self.availability(node_type).available

    def instantiate(self, node_type: str) -> NodeType:
        cls = self.resolve(node_type)
        av = self.availability(node_type)
        if not av.available:
            if av.missing_optional_dependencies:
                from cardre.domain.errors import OptionalDependencyNotInstalled
                raise OptionalDependencyNotInstalled(
                    node_type=node_type,
                    missing_groups=av.missing_optional_dependencies,
                )
        return cls()


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

    return NodeCatalogue(settings, node_classes)
