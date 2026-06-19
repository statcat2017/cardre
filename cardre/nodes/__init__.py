"""Proof node implementations for Phase 1.

These are minimal implementations to exercise the executor, role enforcement,
and artifact lifecycle. Phase 2+ will replace these with real scorecard nodes.

Re-exports all node classes from subpackages for backward compatibility.
"""

from cardre.nodes.prep import (
    GERMAN_CREDIT_COLUMNS,
    ApplyExclusionsNode,
    DefineModellingMetadataNode,
    DevelopmentSampleDefinitionNode,
    ExplicitMissingOutlierTreatmentNode,
    ImportGermanCreditNode,
    ImportTabularDatasetNode,
    ProfileDatasetNode,
    SplitTrainTestOotNode,
    ValidateBinaryTargetNode,
)
from cardre.nodes.build import (
    AutoBinningFitNode,
    BinningNode,
    BuildSummaryReportNode,
    CalculateWoeIvNode,
    DummyFitNode,
    FineClassingNode,
    FrozenScorecardBundleNode,
    LogisticRegressionNode,
    ManualBinningNode,
    ScoreScalingNode,
    TechnicalManifestExportNode,
    VariableClusteringNode,
    VariableSelectionNode,
    WoeTransformTrainNode,
    apply_manual_binning_overrides,
    validate_manual_binning_overrides,
)
from cardre.nodes.ml_models import (
    DecisionTreeNode,
    GradientBoostingClassifierNode,
    RandomForestClassifierNode,
)
from cardre.nodes.boosting import (
    CatBoostClassifierNode,
    LightGBMClassifierNode,
    XGBoostClassifierNode,
)
from cardre.nodes.explainability import (
    ModelExplainabilityNode,
    ModelLimitationsNode,
)
from cardre.nodes.ensembles import (
    VotingEnsembleNode,
    WeightedEnsembleNode,
)
from cardre.nodes.tuning import (
    HyperparameterTuningNode,
)
from cardre.nodes.fairness import (
    AlternativeDataManifestNode,
    FairnessReportNode,
    ProxyRiskReportNode,
)
from cardre.nodes.feature_selection import (
    FeatureSelectionEmbeddedNode,
    FeatureSelectionFilterNode,
    ResampleTrainingDataNode,
    SmoteTrainingDataNode,
)
from cardre.nodes.validate import (
    ApplyModelNode,
    ApplyWoeMappingNode,
    CutoffAnalysisNode,
    DummyApplyNode,
    ThresholdOptimizationNode,
    ValidationMetricsNode,
)

__all__ = [
    "AlternativeDataManifestNode",
    "BinningNode",
    "ApplyExclusionsNode",
    "ApplyModelNode",
    "ApplyWoeMappingNode",
    "BuildSummaryReportNode",
    "CalculateWoeIvNode",
    "CatBoostClassifierNode",
    "CutoffAnalysisNode",
    "DecisionTreeNode",
    "DefineModellingMetadataNode",
    "DevelopmentSampleDefinitionNode",
    "DummyApplyNode",
    "DummyFitNode",
    "ExplicitMissingOutlierTreatmentNode",
    "FairnessReportNode",
    "FeatureSelectionEmbeddedNode",
    "FeatureSelectionFilterNode",
    "FineClassingNode",
    "FrozenScorecardBundleNode",
    "GERMAN_CREDIT_COLUMNS",
    "GradientBoostingClassifierNode",
    "HyperparameterTuningNode",
    "ImportGermanCreditNode",
    "ImportTabularDatasetNode",
    "LightGBMClassifierNode",
    "LogisticRegressionNode",
    "ManualBinningNode",
    "ModelExplainabilityNode",
    "ModelLimitationsNode",
    "ProfileDatasetNode",
    "ProxyRiskReportNode",
    "RandomForestClassifierNode",
    "ResampleTrainingDataNode",
    "ScoreScalingNode",
    "SmoteTrainingDataNode",
    "SplitTrainTestOotNode",
    "TechnicalManifestExportNode",
    "ThresholdOptimizationNode",
    "ValidateBinaryTargetNode",
    "ValidationMetricsNode",
    "VariableClusteringNode",
    "VariableSelectionNode",
    "VotingEnsembleNode",
    "WeightedEnsembleNode",
    "WoeTransformTrainNode",
    "XGBoostClassifierNode",
    "apply_manual_binning_overrides",
    "validate_manual_binning_overrides",
]
