# Node Catalogue

Generated from `NodeRegistry.with_defaults()`. Nodes are divided into launch and deferred tiers.

## Launch Nodes (executable at launch)

| Node Type | Category | Description |
|-----------|----------|-------------|
| `cardre.apply_exclusions` | transform | Apply exclusion criteria |
| `cardre.development_sample_definition` | transform | Define development sample |
| `cardre.define_modelling_metadata` | transform | Define modelling metadata |
| `cardre.explicit_missing_outlier_treatment` | apply | Explicit missing/outlier treatment |
| `cardre.coefficient_sign_check` | fit | Check fitted coefficient signs against WOE direction |
| `cardre.calibration_diagnostics` | fit | Compute calibration diagnostics for scored roles |
| `cardre.separation_diagnostics` | fit | Detect high-coefficient separation risk |
| `cardre.vif_diagnostics` | fit | Compute VIF multicollinearity diagnostics |
| `cardre.import_dataset` | transform | Import tabular data from CSV/TSV/Parquet |
| `cardre.profile_dataset` | transform | Profile dataset columns and statistics |
| `cardre.validate_binary_target` | transform | Validate binary target column |
| `cardre.split_train_test_oot` | transform | Split data into train/test/OOT |
| `cardre.fine_classing` | fit | Fine classing of variables (supports fine_classing and optbinning methods) |
| `cardre.calculate_woe_iv` | selection | Calculate WOE and IV |
| `cardre.variable_clustering` | selection | Variable clustering/correlation grouping |
| `cardre.variable_selection` | selection | Variable selection |
| `cardre.manual_binning` | refinement | Manual bin editing/coarse classing |
| `cardre.noop` | transform | No-op utility node |
| `cardre.technical_manifest_export` | transform | Technical manifest export |
| `cardre.woe_transform_train` | fit | WOE transform on train data |
| `cardre.logistic_regression` | fit | Logistic regression model |
| `cardre.score_scaling` | fit | Score scaling to points |
| `cardre.freeze_scorecard_bundle` | fit | Freeze scorecard bundle |
| `cardre.build_summary_report` | fit | Build summary report |
| `cardre.scorecard_table_export` | export | Export a human-readable scorecard points table |
| `cardre.scoring_export_python` | export | Export standalone Python scoring code |
| `cardre.scoring_export_sql` | export | Export standalone SQL scoring code |
| `cardre.apply_woe_mapping` | apply | Apply WOE mapping to test/oot |
| `cardre.apply_model` | apply | Apply model to test/oot |
| `cardre.validation_metrics` | apply | Calculate validation metrics |
| `cardre.cutoff_analysis` | apply | Cutoff analysis |

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
| `cardre.model_explainability` | report | Model explainability |
| `cardre.model_limitations` | report | Model limitations |
| `cardre.fairness_report` | report | Fairness report |
| `cardre.proxy_risk_report` | report | Proxy risk report |
| `cardre.alternative_data_manifest` | report | Alternative data manifest |
| `cardre.reject_inference_none` | transform | Reject inference (none) |
| `cardre.reject_inference_augmentation` | transform | Reject inference (augmentation) |
| `cardre.decision_tree_classifier` | fit | Decision tree classifier |
| `cardre.calibrate_probabilities` | fit | Platt and isotonic probability calibration |
| `cardre.define_reject_population` | transform | Define reject population for inference |
| `cardre.threshold_optimization` | apply | Optimize classification threshold |
