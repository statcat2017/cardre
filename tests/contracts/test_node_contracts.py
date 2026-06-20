from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from cardre.audit import NodeType, StepSpec, json_logical_hash
from cardre.executor import PlanExecutor
from cardre.nodes import (
    AlternativeDataManifestNode,
    ApplyExclusionsNode,
    ApplyModelNode,
    ApplyWoeMappingNode,
    AutoBinningFitNode,
    BuildSummaryReportNode,
    CalculateWoeIvNode,
    CatBoostClassifierNode,
    CutoffAnalysisNode,
    DecisionTreeNode,
    DefineModellingMetadataNode,
    DevelopmentSampleDefinitionNode,
    DummyApplyNode,
    DummyFitNode,
    ExplicitMissingOutlierTreatmentNode,
    FairnessReportNode,
    FeatureSelectionEmbeddedNode,
    FeatureSelectionFilterNode,
    FineClassingNode,
    FrozenScorecardBundleNode,
    GradientBoostingClassifierNode,
    HyperparameterTuningNode,
    ImportGermanCreditNode,
    ImportTabularDatasetNode,
    LightGBMClassifierNode,
    LogisticRegressionNode,
    ManualBinningNode,
    ModelExplainabilityNode,
    ModelLimitationsNode,
    ProfileDatasetNode,
    ProxyRiskReportNode,
    RandomForestClassifierNode,
    ResampleTrainingDataNode,
    ScoreScalingNode,
    SmoteTrainingDataNode,
    SplitTrainTestOotNode,
    TechnicalManifestExportNode,
    ThresholdOptimizationNode,
    ValidateBinaryTargetNode,
    ValidationMetricsNode,
    VariableClusteringNode,
    VariableSelectionNode,
    VotingEnsembleNode,
    WeightedEnsembleNode,
    WoeTransformTrainNode,
    XGBoostClassifierNode,
)
from cardre.store import ProjectStore


VALID_CATEGORIES = {"fit", "apply", "selection", "refinement", "transform", "report"}


class NodeContractTestBase:
    node_cls: type[NodeType]
    bad_params: dict[str, Any] | None = None
    expected_output_roles: set[str] | None = None
    expected_category: str = ""

    def _check_abstract(self) -> bool:
        return self.__class__ is NodeContractTestBase

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {}

    def test_has_required_class_attributes(self) -> None:
        if self._check_abstract():
            pytest.skip("base class")
        cls = self.node_cls
        assert cls.node_type, f"{cls.__name__} must define node_type"
        assert cls.node_type.startswith("cardre."), (
            f"{cls.__name__}.node_type should start with 'cardre.', got {cls.node_type!r}"
        )
        assert cls.version, f"{cls.__name__} must define version"
        assert cls.category in VALID_CATEGORIES, (
            f"{cls.__name__}.category must be one of {sorted(VALID_CATEGORIES)}"
        )
        assert isinstance(cls.input_roles, list), f"{cls.__name__}.input_roles must be a list"
        assert isinstance(cls.output_roles, list), f"{cls.__name__}.output_roles must be a list"

    def test_validates_good_params(self, tmp_path: Path) -> None:
        if self._check_abstract():
            pytest.skip("base class")
        node = self.node_cls()
        errors = node.validate_params(self.get_good_params(tmp_path))
        assert errors == [], f"Good params should pass validation: {errors}"

    def test_rejects_bad_params(self, tmp_path: Path) -> None:
        if self._check_abstract():
            pytest.skip("base class")
        if self.bad_params is None:
            pytest.skip("bad_params not configured")
        node = self.node_cls()
        errors = node.validate_params(dict(self.bad_params))
        assert len(errors) > 0, "Bad params must produce at least one validation error"

    def test_output_roles_are_non_empty(self) -> None:
        if self._check_abstract():
            pytest.skip("base class")
        assert len(self.node_cls.output_roles) > 0, (
            f"{self.node_cls.__name__} must declare at least one output_role"
        )

    def test_category_is_valid(self) -> None:
        if self._check_abstract():
            pytest.skip("base class")
        assert self.node_cls.category in VALID_CATEGORIES, (
            f"{self.node_cls.__name__}.category {self.node_cls.category!r} is not valid"
        )

    def test_category_matches_expected(self) -> None:
        if self._check_abstract():
            pytest.skip("base class")
        if not self.expected_category:
            pytest.skip("expected_category not configured")
        assert self.node_cls.category == self.expected_category, (
            f"{self.node_cls.__name__}.category is {self.node_cls.category!r}, "
            f"expected {self.expected_category!r}"
        )

    def test_output_roles_match_expected(self) -> None:
        if self._check_abstract():
            pytest.skip("base class")
        if self.expected_output_roles is None:
            pytest.skip("expected_output_roles not configured")
        actual = set(self.node_cls.output_roles)
        assert actual == self.expected_output_roles, (
            f"{self.node_cls.__name__}.output_roles is {actual}, "
            f"expected {self.expected_output_roles}"
        )

    def test_error_dict_has_category_field(self, tmp_path: Path) -> None:
        if self._check_abstract():
            pytest.skip("base class")
        store = ProjectStore(tmp_path / "test.cardre")
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        plan_version_id = store.create_plan_version(plan_id, [], "test")
        run_id = store.create_run(plan_version_id)
        registry = type("EmptyRegistry", (), {
            "instantiate": lambda self_, nt: (_ for _ in ()).throw(
                KeyError(f"Unknown node type {nt!r}")
            ),
        })()
        executor = PlanExecutor(registry)
        spec = StepSpec(
            step_id="test_step",
            node_type="cardre.nonexistent_node",
            node_version="1",
            category="transform",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="main",
            position=0,
        )
        rs = executor._execute_step(
            store=store,
            spec=spec,
            plan_version_id=plan_version_id,
            run_id=run_id,
            step_outputs={},
            run_step_records={},
        )
        assert len(rs.errors) >= 1, "Expected at least one error in run-step record"
        for err in rs.errors:
            assert "category" in err, f"Error dict missing 'category' key: {err}"
            assert isinstance(err["category"], str) and err["category"], (
                f"category must be a non-empty string, got {err['category']!r}"
            )


# ======================================================================
# Import / ingest nodes
# ======================================================================

class TestImportGermanCreditContract(NodeContractTestBase):
    node_cls = ImportGermanCreditNode
    bad_params: dict[str, Any] = {}
    expected_output_roles = {"input"}
    expected_category = "transform"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        data = tmp_path / "german.data"
        data.write_text("A11 6 A34 A43 1169 A65 A75 4 A93 A101 4 A121 67 A143 A152 2 A173 1 A192 A201 1")
        return {"source_path": str(data)}


class TestImportTabularDatasetContract(NodeContractTestBase):
    node_cls = ImportTabularDatasetNode
    bad_params: dict[str, Any] = {}
    expected_output_roles = {"input"}
    expected_category = "transform"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        csv = tmp_path / "dummy.csv"
        csv.write_text("a,b\n1,2\n")
        return {"source_path": str(csv), "delimiter": ",", "has_header": True}


class TestProfileDatasetContract(NodeContractTestBase):
    node_cls = ProfileDatasetNode
    bad_params = None
    expected_output_roles = {"report"}
    expected_category = "transform"


class TestValidateBinaryTargetContract(NodeContractTestBase):
    node_cls = ValidateBinaryTargetNode
    bad_params = None
    expected_output_roles = {"report"}
    expected_category = "transform"


class TestSplitTrainTestOotContract(NodeContractTestBase):
    node_cls = SplitTrainTestOotNode
    bad_params = None
    expected_output_roles = {"train", "test", "oot"}
    expected_category = "transform"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2}


class TestDefineModellingMetadataContract(NodeContractTestBase):
    node_cls = DefineModellingMetadataNode
    bad_params = None
    expected_output_roles = {"definition"}
    expected_category = "transform"


class TestApplyExclusionsContract(NodeContractTestBase):
    node_cls = ApplyExclusionsNode
    bad_params = None
    expected_output_roles = {"input", "train"}
    expected_category = "transform"


class TestDevelopmentSampleDefinitionContract(NodeContractTestBase):
    node_cls = DevelopmentSampleDefinitionNode
    bad_params = None
    expected_output_roles = {"definition"}
    expected_category = "transform"


class TestTechnicalManifestExportContract(NodeContractTestBase):
    node_cls = TechnicalManifestExportNode
    bad_params = None
    expected_output_roles = {"manifest"}
    expected_category = "transform"


# ======================================================================
# Dummy / proof nodes
# ======================================================================

class TestDummyFitContract(NodeContractTestBase):
    node_cls = DummyFitNode
    bad_params = None
    expected_output_roles = {"definition"}
    expected_category = "fit"


class TestDummyApplyContract(NodeContractTestBase):
    node_cls = DummyApplyNode
    bad_params = None
    expected_output_roles = {"prediction"}
    expected_category = "apply"


# ======================================================================
# Treatment / imputation nodes
# ======================================================================

class TestExplicitMissingOutlierTreatmentContract(NodeContractTestBase):
    node_cls = ExplicitMissingOutlierTreatmentNode
    bad_params = None
    expected_output_roles = {"train", "test", "oot"}
    expected_category = "apply"


# ======================================================================
# Binning / WOE nodes
# ======================================================================

class TestAutoBinningFitContract(NodeContractTestBase):
    node_cls = AutoBinningFitNode
    bad_params: dict[str, Any] = {"engine": "invalid"}
    expected_output_roles = {"definition", "report"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        pytest.importorskip("optbinning")
        return {"engine": "optbinning", "prebinning_method": "cart", "solver": "cp"}


class TestFineClassingContract(NodeContractTestBase):
    node_cls = FineClassingNode
    bad_params: dict[str, Any] = {"max_bins": 1}
    expected_output_roles = {"definition"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"max_bins": 10, "min_bin_fraction": 0.05, "missing_policy": "separate_bin"}


class TestCalculateWoeIvContract(NodeContractTestBase):
    node_cls = CalculateWoeIvNode
    bad_params = None
    expected_output_roles = {"report"}
    expected_category = "selection"


class TestWoeTransformTrainContract(NodeContractTestBase):
    node_cls = WoeTransformTrainNode
    bad_params = None
    expected_output_roles = {"train"}
    expected_category = "fit"


# ======================================================================
# Variable selection / clustering nodes
# ======================================================================

class TestVariableClusteringContract(NodeContractTestBase):
    node_cls = VariableClusteringNode
    bad_params: dict[str, Any] = {"method": "correlation_threshold", "threshold": 2.0}
    expected_output_roles = {"report"}
    expected_category = "selection"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {
            "method": "correlation_threshold",
            "threshold": 0.7,
            "candidate_limit": 50,
        }


class TestVariableSelectionContract(NodeContractTestBase):
    node_cls = VariableSelectionNode
    bad_params: dict[str, Any] = {"manual_includes": [{"variable": "x"}]}
    expected_output_roles = {"definition"}
    expected_category = "selection"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {
            "min_iv": 0.02, "max_variables": 15,
            "cluster_representative_rule": "none",
            "cluster_representative_overrides": [],
        }


class TestManualBinningContract(NodeContractTestBase):
    node_cls = ManualBinningNode
    bad_params: dict[str, Any] = {"overrides": [{"variable": "x", "action": "unknown_action", "source_bin_ids": [], "reason": "bad"}]}
    expected_output_roles = {"definition"}
    expected_category = "refinement"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {}


# ======================================================================
# Frozen scorecard bundle
# ======================================================================

class TestFrozenScorecardBundleContract(NodeContractTestBase):
    node_cls = FrozenScorecardBundleNode
    bad_params = None
    expected_output_roles = {"scorecard"}
    expected_category = "fit"


# ======================================================================
# Model fit nodes (LR)
# ======================================================================

class TestLogisticRegressionContract(NodeContractTestBase):
    node_cls = LogisticRegressionNode
    bad_params: dict[str, Any] = {"penalty": "invalid_penalty", "C": 0.0, "max_iter": 100}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"penalty": "l2", "C": 1.0, "max_iter": 100}


class TestScoreScalingContract(NodeContractTestBase):
    node_cls = ScoreScalingNode
    bad_params: dict[str, Any] = {"base_odds": 0}
    expected_output_roles = {"scorecard"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"base_odds": 50.0, "points_to_double_odds": 20}


class TestBuildSummaryReportContract(NodeContractTestBase):
    node_cls = BuildSummaryReportNode
    bad_params = None
    expected_output_roles = {"report"}
    expected_category = "fit"


# ======================================================================
# ML model nodes
# ======================================================================

class TestDecisionTreeContract(NodeContractTestBase):
    node_cls = DecisionTreeNode
    bad_params: dict[str, Any] = {"feature_strategy": "invalid"}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"feature_strategy": "raw_numeric", "max_depth": 5, "min_samples_leaf": 1}


class TestRandomForestClassifierContract(NodeContractTestBase):
    node_cls = RandomForestClassifierNode
    bad_params: dict[str, Any] = {"feature_strategy": "invalid"}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"feature_strategy": "raw_numeric", "n_estimators": 100, "max_depth": 5}


class TestGradientBoostingClassifierContract(NodeContractTestBase):
    node_cls = GradientBoostingClassifierNode
    bad_params: dict[str, Any] = {"feature_strategy": "invalid"}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"feature_strategy": "raw_numeric", "n_estimators": 100, "max_depth": 3, "learning_rate": 0.1}


# ======================================================================
# Boosting nodes (optional deps — validate_params still runs without them)
# ======================================================================

class TestXGBoostClassifierContract(NodeContractTestBase):
    node_cls = XGBoostClassifierNode
    bad_params: dict[str, Any] = {"feature_strategy": "invalid"}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"feature_strategy": "raw_numeric", "n_estimators": 100, "max_depth": 6, "learning_rate": 0.1}


class TestLightGBMClassifierContract(NodeContractTestBase):
    node_cls = LightGBMClassifierNode
    bad_params: dict[str, Any] = {"feature_strategy": "invalid"}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"feature_strategy": "raw_numeric", "n_estimators": 100, "max_depth": -1, "learning_rate": 0.1}


class TestCatBoostClassifierContract(NodeContractTestBase):
    node_cls = CatBoostClassifierNode
    bad_params: dict[str, Any] = {"feature_strategy": "invalid"}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"feature_strategy": "raw_numeric", "iterations": 100, "depth": 6, "learning_rate": 0.1}


# ======================================================================
# Ensemble nodes
# ======================================================================

class TestVotingEnsembleContract(NodeContractTestBase):
    node_cls = VotingEnsembleNode
    bad_params: dict[str, Any] = {"model_artifact_ids": []}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"model_artifact_ids": ["id1", "id2"], "voting": "soft", "threshold": 0.5}


class TestWeightedEnsembleContract(NodeContractTestBase):
    node_cls = WeightedEnsembleNode
    bad_params: dict[str, Any] = {"model_artifact_ids": []}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"model_artifact_ids": ["id1", "id2"], "weights": [0.5, 0.5], "optimize_weights": False}


# ======================================================================
# Hyperparameter tuning
# ======================================================================

class TestHyperparameterTuningContract(NodeContractTestBase):
    node_cls = HyperparameterTuningNode
    bad_params: dict[str, Any] = {"estimator_type": "invalid", "param_grid": {}}
    expected_output_roles = {"model"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {
            "estimator_type": "logistic_regression",
            "search_method": "grid",
            "param_grid": {"C": [0.1, 1.0]},
            "cv_folds": 3,
        }


# ======================================================================
# Feature selection nodes
# ======================================================================

class TestFeatureSelectionFilterContract(NodeContractTestBase):
    node_cls = FeatureSelectionFilterNode
    bad_params: dict[str, Any] = {"min_iv": -1.0}
    expected_output_roles = {"definition"}
    expected_category = "selection"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"min_iv": 0.02, "max_missingness": 0.5, "max_correlation": 0.85, "min_variance": 0.0}


class TestFeatureSelectionEmbeddedContract(NodeContractTestBase):
    node_cls = FeatureSelectionEmbeddedNode
    bad_params: dict[str, Any] = {"importance_threshold": -1.0}
    expected_output_roles = {"definition", "report"}
    expected_category = "selection"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"importance_threshold": 0.01, "estimator": "decision_tree"}


# ======================================================================
# Resampling / imbalance nodes
# ======================================================================

class TestResampleTrainingDataContract(NodeContractTestBase):
    node_cls = ResampleTrainingDataNode
    bad_params: dict[str, Any] = {"strategy": "invalid"}
    expected_output_roles = {"train"}
    expected_category = "transform"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"strategy": "combined", "sampling_ratio": 1.0}


class TestSmoteTrainingDataContract(NodeContractTestBase):
    node_cls = SmoteTrainingDataNode
    bad_params: dict[str, Any] = {"k_neighbors": 0}
    expected_output_roles = {"train"}
    expected_category = "transform"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"k_neighbors": 5, "sampling_ratio": 1.0}


# ======================================================================
# Apply / scoring nodes
# ======================================================================

class TestApplyWoeMappingContract(NodeContractTestBase):
    node_cls = ApplyWoeMappingNode
    bad_params: dict[str, Any] = {"woe_unmatched_policy": "invalid"}
    expected_output_roles = {"train", "test", "oot"}
    expected_category = "apply"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"woe_unmatched_policy": "warn"}


class TestApplyModelContract(NodeContractTestBase):
    node_cls = ApplyModelNode
    bad_params = None
    expected_output_roles = {"train", "test", "oot"}
    expected_category = "apply"


class TestValidationMetricsContract(NodeContractTestBase):
    node_cls = ValidationMetricsNode
    bad_params = None
    expected_output_roles = {"report"}
    expected_category = "apply"


class TestThresholdOptimizationContract(NodeContractTestBase):
    node_cls = ThresholdOptimizationNode
    bad_params: dict[str, Any] = {"objective": "invalid"}
    expected_output_roles = {"report"}
    expected_category = "apply"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"objective": "youden", "n_thresholds": 100}


class TestCutoffAnalysisContract(NodeContractTestBase):
    node_cls = CutoffAnalysisNode
    bad_params: dict[str, Any] = {"band_count": 1}
    expected_output_roles = {"report"}
    expected_category = "apply"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"band_count": 10}


# ======================================================================
# Explainability / limitations nodes
# ======================================================================

class TestModelExplainabilityContract(NodeContractTestBase):
    node_cls = ModelExplainabilityNode
    bad_params: dict[str, Any] = {"include_permutation_importance": "not_a_bool"}
    expected_output_roles = {"report"}
    expected_category = "report"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"include_permutation_importance": False, "permutation_data_role": "train"}


class TestModelLimitationsContract(NodeContractTestBase):
    node_cls = ModelLimitationsNode
    bad_params: dict[str, Any] = {"accepted_limitations": "not_a_list"}
    expected_output_roles = {"report"}
    expected_category = "report"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"accepted_limitations": []}


# ======================================================================
# Fairness / governance nodes
# ======================================================================

class TestFairnessReportContract(NodeContractTestBase):
    node_cls = FairnessReportNode
    bad_params: dict[str, Any] = {}
    expected_output_roles = {"report"}
    expected_category = "report"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"sensitive_columns": ["gender"], "min_group_size": 30, "cutoff": 0.5}


class TestProxyRiskReportContract(NodeContractTestBase):
    node_cls = ProxyRiskReportNode
    bad_params: dict[str, Any] = {"sensitive_columns": "not_a_list"}
    expected_output_roles = {"report"}
    expected_category = "report"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"sensitive_columns": ["gender"], "correlation_threshold": 0.3, "importance_threshold": 0.05}


class TestAlternativeDataManifestContract(NodeContractTestBase):
    node_cls = AlternativeDataManifestNode
    bad_params: dict[str, Any] = {"data_sources": "not_a_list"}
    expected_output_roles = {"report"}
    expected_category = "report"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"data_sources": [{"source_name": "test", "consent_basis": "consent", "permitted_use": "scoring"}]}
