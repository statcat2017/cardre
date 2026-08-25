# Node Catalogue

Cardre exposes one flat production catalogue of nodes. There is no launch /
deferred tier and no `CARDRE_LAUNCH_MODE` flag: every registered node is
executable in the canonical scorecard pathway. The catalogue is the single
source of truth for production node registration and must contain exactly the
distinct node types required by `_CANONICAL_SCORECARD_STEPS`.

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
| `cardre.import_dataset` | transform | Import tabular data from a Parquet file; Parquet is the only import boundary |
| `cardre.profile_dataset` | transform | Profile dataset columns and statistics |
| `cardre.validate_binary_target` | transform | Validate binary target column |
| `cardre.split_train_test_oot` | transform | Random-stratified split into train/test/OOT |
| `cardre.automatic_binning` | fit | Automatic binning of variables; fine classing is the only method |
| `cardre.calculate_woe_iv` | selection | Calculate WOE and IV |
| `cardre.variable_clustering` | selection | Correlation-threshold variable clustering |
| `cardre.variable_selection` | selection | Variable selection |
| `cardre.manual_binning` | refinement | Manual bin editing/coarse classing |
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
