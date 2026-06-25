# Evidence Kinds

## EvidenceKind Enum

The `EvidenceKind` enum (`cardre/evidence/`) defines all evidence types produced by node executions:

| EvidenceKind | Description |
|-------------|-------------|
| `MODELLING_METADATA` | Modelling metadata definition |
| `BIN_DEFINITION` | Bin boundary definitions |
| `SAMPLE_DEFINITION` | Development sample definition |
| `SPLIT_SUMMARY` | Train/test/OOT split summary |
| `PROFILE_SUMMARY` | Dataset profile summary |
| `EXCLUSION_SUMMARY` | Exclusion criteria summary |
| `REJECT_POPULATION_CONFIG` | Reject population configuration |
| `REJECT_INFERENCE_RESULT` | Reject inference result |
| `SELECTION_DEFINITION` | Variable selection definition |
| `WOE_TRANSFORM_EVIDENCE` | WOE transform evidence |
| `WOE_TABLE` | WOE table |
| `WOE_IV_EVIDENCE` | WOE/IV evidence |
| `VARIABLE_CLUSTERING` | Variable clustering result |
| `MODEL_ARTIFACT` | Model artifact |
| `SCORE_SCALING` | Score scaling definition |
| `VALIDATION_METRICS` | Validation metrics |
| `CUTOFF_ANALYSIS` | Cutoff analysis result |
| `SCORED_DATASET` | Scored dataset |
| `MANUAL_BINNING_OVERRIDES` | Manual binning overrides |
| `IV_TABLE` | IV ranking table |
| `FROZEN_SCORECARD_BUNDLE` | Frozen scorecard bundle |
| `APPLY_WOE_EVIDENCE` | WOE application evidence |
| `WOE_APPLICATION_EVIDENCE` | WOE application evidence (alias) |
| `APPLY_MODEL_EVIDENCE` | Model application evidence |
| `SCORE_APPLICATION_EVIDENCE` | Score application evidence |
| `VALIDATION_EVIDENCE` | Validation evidence |
| `REPORT_BUNDLE` | Report bundle |
| `RUN_MANIFEST` | Run manifest |
| `TECHNICAL_MANIFEST_INDEX` | Technical manifest index |
| `COMPARISON_ARTIFACT` | Comparison artifact |
| `FEATURE_SELECTION_EVIDENCE` | Feature selection evidence |
| `RESAMPLING_EVIDENCE` | Resampling evidence |
| `HYPERPARAMETER_TUNING_EVIDENCE` | Hyperparameter tuning evidence |
| `ENSEMBLE_MODEL_ARTIFACT` | Ensemble model artifact |
| `EXPLAINABILITY_REPORT` | Explainability report |
| `FAIRNESS_REPORT` | Fairness report |
| `PROXY_RISK_REPORT` | Proxy risk report |

## Canonical Step IDs

Evidence is resolved by canonical step IDs defined in `cardre/reporting/evidence_contract.py`:

| Canonical ID | Description |
|-------------|-------------|
| `final-woe-iv` | Final WOE/IV evidence |
| `model-fit` | Model fit evidence |
| `score-scaling` | Score scaling evidence |
| `validation-metrics` | Validation metrics evidence |
| `cutoff-analysis` | Cutoff analysis evidence |
| `manual-binning` | Manual binning evidence |
| `variable-clustering` | Variable clustering evidence |
| `technical-manifest-stub` | Technical manifest stub (comparison mode) |

## Legacy Aliases

| Legacy ID | Current ID |
|-----------|------------|
| `logistic-regression` | `model-fit` |

## Required Steps by Report Mode

| Mode | Required Steps |
|------|---------------|
| Branch report | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics` |
| Champion report | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics` |
| Full collector | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics`, `cutoff-analysis`, `manual-binning`, `variable-clustering` |
| Comparison | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics`, `cutoff-analysis`, `technical-manifest-stub` |
