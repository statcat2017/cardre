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
    BuildSummaryReportNode,
    CalculateWoeIvNode,
    DummyFitNode,
    FineClassingNode,
    FrozenScorecardBundleNode,
    LogisticRegressionNode,
    ManualBinningNode,
    NoopNode,
    PythonScoringExportNode,
    ScorecardTableExportNode,
    ScoreScalingNode,
    SqlScoringExportNode,
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
    ApplyExclusionsNode,
    DefineModellingMetadataNode,
    DevelopmentSampleDefinitionNode,
    ExplicitMissingOutlierTreatmentNode,
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
    ThresholdOptimizationNode,
    ValidationMetricsNode,
)

__all__ = [
    "AlternativeDataManifestNode",
    "ApplyExclusionsNode",
    "ApplyModelNode",
    "ApplyWoeMappingNode",
    "BuildSummaryReportNode",
    "CalculateWoeIvNode",
    "CalibrateProbabilitiesNode",
    "CatBoostClassifierNode",
    "CutoffAnalysisNode",
    "DecisionTreeNode",
    "DefineModellingMetadataNode",
    "DefineRejectPopulationNode",
    "DevelopmentSampleDefinitionNode",
    "DummyFitNode",
    "ExplicitMissingOutlierTreatmentNode",
    "FairnessReportNode",
    "FeatureSelectionEmbeddedNode",
    "FeatureSelectionFilterNode",
    "FineClassingNode",
    "FrozenScorecardBundleNode",
    "GradientBoostingClassifierNode",
    "HyperparameterTuningNode",
    "ImportTabularDatasetNode",
    "LightGBMClassifierNode",
    "LogisticRegressionNode",
    "ManualBinningNode",
    "ModelExplainabilityNode",
    "ModelLimitationsNode",
    "NoopNode",
    "ProfileDatasetNode",
    "ProxyRiskReportNode",
    "PythonScoringExportNode",
    "RandomForestClassifierNode",
    "RejectInferenceAugmentationNode",
    "RejectInferenceNoneNode",
    "ResampleTrainingDataNode",
    "ScoreScalingNode",
    "ScorecardTableExportNode",
    "SmoteTrainingDataNode",
    "SplitTrainTestOotNode",
    "SqlScoringExportNode",
    "TechnicalManifestExportNode",
    "ThresholdOptimizationNode",
    "ValidateBinaryTargetNode",
    "ValidationMetricsNode",
    "VariableClusteringNode",
    "VariableSelectionNode",
    "WoeTransformTrainNode",
    "XGBoostClassifierNode",
    "apply_manual_binning_overrides",
    "validate_manual_binning_overrides",
]
