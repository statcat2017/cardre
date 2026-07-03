"""Built-in node implementations for the Cardre scorecard engine.

This module re-exports all node classes from subpackages for backward
compatibility.  Nodes are registered in ``cardre.registry.NodeRegistry``
and divided into two tiers:

- **Launch tier**: executable at launch (logistic regression, binning,
  WOE/IV, score scaling, validation, cutoff, decision tree challenger).
- **Deferred tier**: registered as schemas for UI display but not
  executable unless ``CARDRE_LAUNCH_MODE=0`` (boosting, ensembles,
  fairness, explainability, reject inference, feature selection, tuning).

See ``docs/launch-mode.md`` and ``docs/reference/node-catalogue.md``.
"""

from cardre.nodes.boosting import (
    CatBoostClassifierNode,
    LightGBMClassifierNode,
    XGBoostClassifierNode,
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
    NoopNode,
    ScoreScalingNode,
    TechnicalManifestExportNode,
    VariableClusteringNode,
    VariableSelectionNode,
    WoeTransformTrainNode,
    apply_manual_binning_overrides,
    validate_manual_binning_overrides,
)
from cardre.nodes.calibrate import (
    CalibrateProbabilitiesNode,
)
from cardre.nodes.ensembles import (
    VotingEnsembleNode,
    WeightedEnsembleNode,
)
from cardre.nodes.explainability import (
    ModelExplainabilityNode,
    ModelLimitationsNode,
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
from cardre.nodes.ml_models import (
    DecisionTreeNode,
    GradientBoostingClassifierNode,
    RandomForestClassifierNode,
)
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
from cardre.nodes.reject_inference import (
    DefineRejectPopulationNode,
    RejectInferenceAugmentationNode,
    RejectInferenceNoneNode,
)
from cardre.nodes.tuning import (
    HyperparameterTuningNode,
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
    "GERMAN_CREDIT_COLUMNS",
    "AlternativeDataManifestNode",
    "ApplyExclusionsNode",
    "ApplyModelNode",
    "ApplyWoeMappingNode",
    "AutoBinningFitNode",
    "BinningNode",
    "BuildSummaryReportNode",
    "CalculateWoeIvNode",
    "CalibrateProbabilitiesNode",
    "CatBoostClassifierNode",
    "CutoffAnalysisNode",
    "DecisionTreeNode",
    "DefineModellingMetadataNode",
    "DefineRejectPopulationNode",
    "DevelopmentSampleDefinitionNode",
    "DummyApplyNode",
    "DummyFitNode",
    "ExplicitMissingOutlierTreatmentNode",
    "FairnessReportNode",
    "FeatureSelectionEmbeddedNode",
    "FeatureSelectionFilterNode",
    "FineClassingNode",
    "FrozenScorecardBundleNode",
    "GradientBoostingClassifierNode",
    "HyperparameterTuningNode",
    "ImportGermanCreditNode",
    "ImportTabularDatasetNode",
    "LightGBMClassifierNode",
    "LogisticRegressionNode",
    "ManualBinningNode",
    "ModelExplainabilityNode",
    "ModelLimitationsNode",
    "NoopNode",
    "ProfileDatasetNode",
    "ProxyRiskReportNode",
    "RandomForestClassifierNode",
    "RejectInferenceAugmentationNode",
    "RejectInferenceNoneNode",
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
