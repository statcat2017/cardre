# Node Catalogue

Generated from `NodeRegistry.with_defaults()`. Nodes are divided into launch and deferred tiers.

## Launch Nodes (executable at launch)

| Node Type | Category | Description |
|-----------|----------|-------------|
| `cardre.import_dataset` | transform | Import tabular data from CSV/TSV/Parquet |
| `cardre.import_fixture_uci_german_credit` | transform | Import the UCI German Credit fixture |
| `cardre.profile_dataset` | transform | Profile dataset columns and statistics |
| `cardre.validate_binary_target` | transform | Validate binary target column |
| `cardre.split_train_test_oot` | transform | Split data into train/test/OOT |
| `cardre.define_modelling_metadata` | transform | Define modelling metadata |
| `cardre.define_reject_population` | transform | Define reject population |
| `cardre.apply_exclusions` | transform | Apply exclusion criteria |
| `cardre.development_sample_definition` | transform | Define development sample |
| `cardre.explicit_missing_outlier_treatment` | transform | Explicit missing/outlier treatment |
| `cardre.auto_binning_fit` | fit | Automatic binning fit |
| `cardre.fine_classing` | fit | Fine classing of variables |
| `cardre.calculate_woe_iv` | fit | Calculate WOE and IV |
| `cardre.variable_clustering` | selection | Variable clustering/correlation grouping |
| `cardre.variable_selection` | selection | Variable selection |
| `cardre.manual_binning` | refinement | Manual bin editing/coarse classing |
| `cardre.technical_manifest_export` | transform | Technical manifest export |
| `cardre.woe_transform_train` | transform | WOE transform on train data |
| `cardre.logistic_regression` | fit | Logistic regression model |
| `cardre.decision_tree_classifier` | fit | Decision tree classifier |
| `cardre.score_scaling` | fit | Score scaling to points |
| `cardre.calibrate_probabilities` | fit | Platt or isotonic probability calibration on holdout |
| `cardre.freeze_scorecard_bundle` | transform | Freeze scorecard bundle |
| `cardre.build_summary_report` | transform | Build summary report |
| `cardre.apply_woe_mapping` | apply | Apply WOE mapping to test/oot |
| `cardre.apply_model` | apply | Apply model to test/oot |
| `cardre.validation_metrics` | apply | Calculate validation metrics |
| `cardre.threshold_optimization` | apply | Threshold optimization |
| `cardre.cutoff_analysis` | apply | Cutoff analysis |
| `cardre.binning` | transform | Generic binning |
| `cardre.dummy_fit` | fit | Dummy fit (testing) |
| `cardre.dummy_apply` | apply | Dummy apply (testing) |

## Deferred Nodes (schema only, not executable at launch)

| Node Type | Category | Description |
|-----------|----------|-------------|
| `cardre.random_forest_classifier` | fit | Random forest classifier |
| `cardre.gradient_boosting_classifier` | fit | Gradient boosting classifier |
| `cardre.xgboost_classifier` | fit | XGBoost classifier |
| `cardre.lightgbm_classifier` | fit | LightGBM classifier |
| `cardre.catboost_classifier` | fit | CatBoost classifier |
| `cardre.feature_selection_filter` | selection | Filter-based feature selection |
| `cardre.feature_selection_embedded` | selection | Embedded feature selection |
| `cardre.hyperparameter_tuning` | fit | Hyperparameter tuning |
| `cardre.resample_training_data` | transform | Resample training data |
| `cardre.smote_training_data` | transform | SMOTE training data |
| `cardre.model_explainability` | transform | Model explainability |
| `cardre.model_limitations` | transform | Model limitations |
| `cardre.fairness_report` | transform | Fairness report |
| `cardre.proxy_risk_report` | transform | Proxy risk report |
| `cardre.alternative_data_manifest` | transform | Alternative data manifest |
| `cardre.reject_inference_none` | fit | Reject inference (none) |
| `cardre.reject_inference_augmentation` | fit | Reject inference (augmentation) |
| `cardre.voting_ensemble` | fit | Voting ensemble |
| `cardre.weighted_ensemble` | fit | Weighted ensemble |
