# ML Scorecard Methods Implementation Plan

## Purpose

This plan incorporates the findings from Ayari, Guetari, and Kraiem's systematic
review, "Machine learning powered financial credit scoring", into Cardre's
branchable, auditable scorecard builder.

The paper's practical message is not to replace governed scorecards with black
box models. It shows that modern credit scoring compares transparent baseline
models with selected traditional ML, ensemble, feature-selection,
imbalance-handling, explainability, and fairness-aware methods. Cardre should
support that pattern directly: build a transparent baseline scorecard, create a
small number of governable challenger branches, validate all branches under the
same evidence standard, and promote a champion only when the evidence supports
it.

Cardre should not try to become "all ML methods for credit scoring." The target
product is a governed scorecard builder with auditable ML challenger branches.

## Product Principle

Cardre remains an auditable scorecard builder, not a generic AutoML or research
workbench.

Every new method must satisfy these constraints:

1. It is represented as an explicit pathway node with versioned parameters.
2. It produces immutable artifacts with enough metadata to reproduce the run.
3. It can be compared against baseline and challenger branches.
4. It has validation evidence across train, test, and OOT samples where present.
5. It records interpretability limits instead of hiding them.
6. It does not mutate historical runs, artifacts, or branch evidence.
7. It has explicit champion-eligibility gates; metric improvement alone is never enough.

## Findings To Incorporate

| Paper finding | Cardre capability to add |
|---|---|
| Logistic regression remains relevant for transparent, smaller-data scorecards | Keep WOE + logistic scorecard as the governed baseline |
| Decision trees are interpretable and capture nonlinear rules | Add decision tree as the first non-logistic challenger and require rule export |
| Random forests and gradient boosting often outperform single models | Add RF and sklearn GBDT after decision tree proves the generic path |
| Optional boosting libraries can be high-value | Add XGBoost/LightGBM/CatBoost later as optional dependencies |
| Hybrid and ensemble models are widely used but harder to govern | Treat voting/stacking/segmented models as advanced research challengers |
| Feature selection is central to stronger models | Expand governed selection cautiously; keep wrapper/projection methods experimental |
| Imbalanced data is a recurring credit-scoring issue | Add class weights first; treat synthetic sampling such as SMOTE as high-governance friction |
| Deep learning can help on large or sequential data but is less interpretable | Defer DL to experimental backlog; do not include LSTM/CNN until sequence artifacts exist |
| Alternative data can improve inclusion but raises privacy and fairness risk | Add provenance, consent, sensitive-feature, and proxy-risk gates |
| SHAP/LIME can support black-box review but are not native interpretability | Add explainability evidence without treating SHAP/LIME as equivalent to scorecard logic |
| Accuracy alone is insufficient on imbalanced data | Expand validation to precision, recall, specificity, F1, G-Mean, confusion matrix, cost error, AUC, KS, PSI, and calibration |

## Current Cardre Starting Point

Relevant existing implementation:

| Area | Current files | Notes |
|---|---|---|
| Node registration | `cardre/registry.py` | Registers current proof/build/validate nodes |
| Build nodes | `cardre/nodes/build.py` | Fine classing, WOE/IV, variable clustering, variable selection, logistic regression, score scaling |
| Apply/validate nodes | `cardre/nodes/validate.py` | WOE apply, model apply, validation metrics, cutoff analysis |
| Branching/comparison | `cardre/services/branch_service.py`, `cardre/services/comparison_service.py`, `cardre/services/champion_service.py` | Branch-aware pathway and champion selection already exist |
| Report readiness | `cardre/reporting/readiness.py` | Currently expects `logistic-regression` as required model evidence |
| Package dependencies | `pyproject.toml` | Already has `scikit-learn`; boosting, imbalance, explainability, and deep-learning dependencies should be optional |

## Architecture Target

### Governed Baseline And Challenger Pathway

Cardre should support this governed branch shape:

```text
dataset
  -> profile / target validation / split / exclusions / treatment
  -> fine classing / WOE / IV / variable selection
      -> logistic scorecard baseline
      -> decision tree challenger
      -> random forest challenger
      -> sklearn gradient boosting challenger
      -> optional XGBoost or LightGBM challenger
      -> advanced/research ensemble challenger
  -> apply model
  -> validation metrics
  -> cutoff analysis
  -> explainability / fairness / limitation evidence
  -> comparison snapshot
  -> champion assignment with gates
  -> governance report / export
```

Early delivery should prove the architecture with decision tree, random forest,
and sklearn GBDT. SVM, KNN, Naive Bayes, PCA, stacking, dynamic ensembles, MLP,
LSTM, and tabular CNN are not near-term governed scorecard methods. They belong
in an experimental or research backlog unless a concrete product requirement
pulls them forward.

### Generic Model Contract

The current model path assumes logistic coefficients. Introduce a generic model
artifact contract so every approved model family can share apply, validation,
comparison, reporting, and champion infrastructure.

Required JSON fields:

| Field | Purpose |
|---|---|
| `schema_version` | Example: `cardre.model_artifact.v1` |
| `model_family` | Initially `logistic_regression`, `decision_tree`, `random_forest`, `gbdt`; optional later `xgboost`, `lightgbm`, `catboost`; advanced methods only by explicit experimental flag |
| `input_artifact_id` | Exact training dataset artifact used for fitting |
| `training_role` | Must be `train`; prevents leakage from test/OOT into fit |
| `target_column` | Target used for fitting |
| `target_event_value` | Explicit bad/default event definition |
| `class_mapping` | Explicit good/bad labels and encoded class positions |
| `probability_column_index` | Which estimator probability column represents bad/default |
| `feature_contract` | Feature columns, transformation strategy, order, dtypes, missing policy, unknown-category policy |
| `feature_order_hash` | Prevents silent column-order drift between fit and apply |
| `feature_dtype_contract` | Prevents train/apply dtype drift |
| `preprocessing_artifact_ids` | Encoders, imputers, WOE maps, selection definitions, calibration artifacts |
| `prediction_contract` | Probability semantics, score direction, score type, threshold policy references |
| `score_direction` | Whether higher score means lower risk or higher risk |
| `calibration_artifact_id` | Optional separate calibration model when fitted |
| `estimator_artifact_id` | Binary estimator reference when needed |
| `estimator_format` | `pickle`, `joblib`, `skops`, `onnx`, or JSON-native |
| `trusted_load_required` | Security flag for binary estimator loading |
| `training` | Row count, params, random seed, package versions, elapsed time, convergence/tuning status |
| `model_payload` | Coefficients, scorecard points, tree rules, feature importance, or other lightweight model-specific payload |
| `interpretability` | Native explainability type, explanation level, limitations, global importance fields where available |
| `warnings` | Fit-time and governance warnings |

Use JSON for metadata and lightweight interpretable payloads. Use JSON-native
exports for logistic scorecards and shallow decision trees where practical. Use a
separate binary artifact for sklearn estimators only when necessary, referenced
from the JSON model artifact by artifact id and logical hash. Do not embed large
pickles inside JSON.

### Preprocessing Contract

For non-logistic models, the fitted system is the estimator plus the explicit
feature transformation graph.

The contract must distinguish:

| Item | Requirement |
|---|---|
| Estimator | The fitted model payload or estimator artifact |
| Preprocessing graph | Exclusions, treatment, encoding, imputation, WOE mapping, selection, resampling, calibration |
| Training sample role | Must be train-only for fitting and train-only for synthetic resampling |
| Application-time expectations | Required columns, dtypes, missing handling, unknown category handling, fallback warnings |
| Governance passthrough columns | Target, identifiers, and sensitive columns retained for audit/fairness but excluded from features |

`ApplyModelNode` must use only `feature_contract.features` for prediction. It may
carry passthrough columns forward for reporting and fairness evidence, but those
columns must not silently become model features.

### Feature Strategy Defaults

Do not default every challenger model to WOE features. Every branch template must
declare a feature strategy explicitly.

| Model family | Default feature strategy |
|---|---|
| Logistic scorecard | WOE |
| Decision tree | Raw numeric, with explicit encoding later for categoricals |
| Random forest | Raw numeric or encoded raw |
| Sklearn GBDT | Raw numeric or encoded raw |
| XGBoost/LightGBM | Raw numeric or encoded raw |
| CatBoost | Raw categorical where supported |
| WOE-feature challengers | Allowed only when explicitly labelled as WOE-feature challengers |
| Projection/PCA challengers | Experimental and lower-interpretability by default |

Reports must show whether a branch used WOE, raw, encoded, projected, or mixed
features.

### Universal Scored Dataset Output

`ApplyModelNode` should emit a standard output contract without implying that
every model has native scorecard points.

| Column | Meaning |
|---|---|
| `predicted_bad_probability` | Required for classifiers where probability is available |
| `raw_model_output` | Optional decision function, logit, margin, or estimator-specific output |
| `native_scorecard_points` | Present only for native scorecard models |
| `cardre_scaled_score` | Optional Cardre-created score scale from probability or log odds |
| `decision_label` | Optional; present only when a threshold policy exists |
| `threshold_policy_id` | Links decision label to selected cutoff policy |
| `model_artifact_id` | Exact model artifact used for scoring |
| `model_family` | Model family name |
| `scoring_warnings` | Missing columns, unknown categories, fallback use, dtype coercions |

Governance reports must distinguish native scorecard points, scaled ML scores,
raw probabilities, and threshold decisions.

### Canonical Step Naming

Introduce these canonical ids for branch readiness and reporting:

| Canonical step | Meaning |
|---|---|
| `model-fit` | Any approved model family, including logistic regression |
| `model-apply` | Applies the fitted model to train/test/OOT and emits scored datasets |
| `validation-metrics` | Common model performance evidence |
| `cutoff-analysis` | Score/probability threshold and band evidence |
| `model-explainability` | Coefficients, feature importance, rules, SHAP/LIME/permutation evidence |
| `fairness-report` | Sensitive-group, proxy, and bias evidence |
| `model-limitations` | Structured interpretability and deployment limitations |

Keep `logistic-regression` as a legacy canonical id during migration, but new
plans should use `model-fit`. Legacy resolution must happen lazily at
readiness/report/comparison time. Do not rewrite saved plan versions to force the
new canonical id.

## Dependency Strategy

Keep the default install lightweight and reproducible.

Update `pyproject.toml` optional dependencies:

```toml
[project.optional-dependencies]
sidecar = ["fastapi", "uvicorn"]
test = ["pytest", "httpx", "starlette"]
boosting = ["xgboost", "lightgbm", "catboost"]
imbalance = ["imbalanced-learn"]
explain = ["shap", "lime"]
deep = ["torch"]
all-methods = ["xgboost", "lightgbm", "catboost", "imbalanced-learn", "shap", "lime", "torch"]
```

Rules:

1. Nodes requiring optional packages must fail with a clear dependency message.
2. Default test suite must not require optional packages.
3. Optional-package tests must be marked and runnable separately.
4. Artifacts must record dependency versions used during fitting and explanation.
5. Optional methods must not appear as default branch templates unless the dependency is installed and the method is governance-eligible.

## Implementation Phases

## Phase 0: Correctness Hotfix

Goal: fix known scorecard correctness defects before adding new model families.

### Workstreams

1. Fix cutoff analysis labels
   - `CutoffAnalysisNode` must derive observed bad/good labels from the actual target column and modelling metadata.
   - It must never derive `y_bin` from `predicted_bad_probability`.
   - It must warn when target metadata is absent instead of emitting misleading bad-rate/capture-rate evidence.

2. Add focused regression tests
   - Known cutoff fixture proving target labels drive bad rate and capture rate.
   - Fixture where predicted probability order would produce a different result from actual labels.
   - Single-class and missing-target warnings.

### Acceptance Criteria

- Cutoff bad rate and capture rate are computed from observed target labels.
- Existing cutoff output shape remains compatible where possible.
- The fix can be shipped before or alongside Phase 1.

## Phase 1: Model Contract Foundation

Goal: allow non-logistic model families without breaking current scorecards.

### Workstreams

1. Define model artifact schema
   - Add `cardre/modeling/schema.py` or `cardre/reporting/schema.py` extension.
   - Define `ModelArtifactV1`, `FeatureContract`, `PredictionContract`, `TrainingMetadata`, `EstimatorReference`, and `InterpretabilityMetadata` as serialisable dataclasses or pydantic models.
   - Add schema helpers to validate required fields before writing artifacts.
   - Preserve compatibility with current logistic model JSON.
   - Make probability orientation explicit using `class_mapping`, `target_event_value`, and `probability_column_index`.

2. Generalize model application
   - Replace or extend `ApplyModelNode` so it dispatches by `model_family`.
   - Support linear coefficient application for existing logistic artifacts.
   - Support sklearn-estimator application through a secured binary artifact reference.
   - Emit standard scored columns: `predicted_bad_probability`, `raw_model_output`, `native_scorecard_points`, `cardre_scaled_score`, `decision_label`, `threshold_policy_id`, `model_artifact_id`, `model_family`, and `scoring_warnings` where applicable.
   - Ensure every scored artifact records source model artifact id and model logical hash.

3. Generalize readiness and comparison
   - Update `cardre/reporting/readiness.py` required steps from `logistic-regression` to `model-fit` for new plans.
   - Resolve legacy `logistic-regression` lazily as `model-fit` during readiness, reporting, and comparison.
   - Update `cardre/services/comparison_service.py` to read generic model artifacts.
   - Compare common model-level fields: family, feature strategy, feature count, selected features, native interpretability, warnings, package versions.
   - Keep coefficient comparison only for coefficient-bearing models.

4. Register compatibility aliases
   - Keep `cardre.logistic_regression` registered.
   - Allow it to produce `schema_version = cardre.model_artifact.v1` while preserving existing output fields until migration is complete.

5. Define secure estimator loading policy
   - Only load binary estimators from the project artifact store.
   - Verify artifact hash before loading.
   - Store creating run id, run step id, logical hash, physical hash, and estimator format.
   - Refuse arbitrary external pickle/joblib paths by default.
   - Warn when importing externally produced binary models.
   - Prefer JSON-native exports where feasible; later evaluate `skops` or ONNX for safer persistence.

### Files

| File | Action |
|---|---|
| `cardre/modeling/__init__.py` | Create |
| `cardre/modeling/schema.py` | Create generic model artifact contract |
| `cardre/modeling/serialization.py` | Create secure estimator read/write helpers if binary artifacts are used |
| `cardre/nodes/validate.py` | Extend `ApplyModelNode` dispatch and fix cutoff label source if not already done in Phase 0 |
| `cardre/nodes/build.py` | Update `LogisticRegressionNode` artifact output |
| `cardre/reporting/readiness.py` | Accept generic `model-fit` evidence and legacy lazy resolution |
| `cardre/services/comparison_service.py` | Generic model comparison |
| `tests/` | Add schema, apply, readiness, security, and comparison tests |

### Acceptance Criteria

- Existing logistic scorecard tests still pass.
- New logistic artifacts contain generic schema fields.
- `ApplyModelNode` applies both legacy logistic and generic v1 logistic artifacts.
- Probability orientation is correct when sklearn class order is not `[good, bad]`.
- Readiness accepts new `model-fit` canonical evidence and lazily accepts legacy `logistic-regression` evidence.
- Comparison snapshots do not crash for models without coefficients.
- Binary estimator loads require artifact-store provenance and hash verification.

### Verification

```bash
python3 -m pytest tests/ -q
```

## Phase 2: Decision Tree Challenger

Goal: add the first non-logistic challenger and prove the generic model path with
an interpretable, auditable model.

### Node Inventory

| Node | Model family | Priority | Notes |
|---|---|---|---|
| `cardre.decision_tree_classifier` | `decision_tree` | High | First non-logistic challenger; must export rules |

### Implementation Details

1. Add `cardre/nodes/ml_models.py`.
2. Add a shared helper for extracting target labels and declared feature columns.
3. Require branch templates to declare `feature_strategy`; do not default to WOE.
4. Start with raw numeric features and explicit include/exclude columns.
5. Reject unsupported categorical columns with a clear error until encoding nodes exist.
6. Store shallow tree rules in JSON where feasible and a binary estimator artifact only when necessary.
7. Store interpretable summaries in JSON: tree depth, leaf count, rule list, feature usage, class mapping, probability orientation, and limitations.
8. Register the node in `cardre/registry.py` and re-export in `cardre/nodes/__init__.py`.

### Parameters

| Parameter | Meaning |
|---|---|
| `feature_strategy` | Required: `raw_numeric`, `encoded_raw`, or explicit `woe_challenger` |
| `include_columns` | Optional explicit feature list |
| `exclude_columns` | Columns to remove |
| `max_depth` | Required governance control for interpretability |
| `min_samples_leaf` | Stability control |
| `class_weight` | `balanced`, explicit dict, or null |
| `random_seed` | Deterministic fit seed |

### Acceptance Criteria

- Decision tree validates parameters before fitting.
- Decision tree produces `cardre.model_artifact.v1` JSON plus binary estimator artifact only if required.
- Decision tree can feed generic `ApplyModelNode`.
- Decision tree can feed `ValidationMetricsNode` without special cases.
- Decision tree artifact includes native rule export.
- Branch comparison can compare one logistic baseline against one decision-tree challenger.
- Champion promotion can treat shallow decision trees as eligible with rule evidence.

### Verification

```bash
python3 -m pytest tests/ -q
```

## Phase 3: Core ML Benchmark Challengers

Goal: add the minimum useful benchmark set after the decision tree proves the
generic model contract.

### Node Inventory

| Node | Model family | Priority | Notes |
|---|---|---|---|
| `cardre.random_forest_classifier` | `random_forest` | High | Strong ensemble benchmark, feature importance, interpretability warning |
| `cardre.gradient_boosting_classifier` | `gbdt` | High | Dependency-free boosting challenger |

### Advanced Backlog

| Method | Reason deferred |
|---|---|
| SVM | Calibration and explainability concerns; not a core governed scorecard challenger |
| KNN | Distance methods suffer under high dimensionality and are harder to explain |
| Naive Bayes | Useful benchmark but not enough product value for early delivery |
| Histogram GBDT | Add only if large-tabular performance need appears |

### Implementation Details

1. Reuse the decision-tree model contract and apply path.
2. Require explicit `feature_strategy` for every branch template.
3. Store feature importance and model complexity summaries.
4. Mark RF/GBDT as semi-transparent, not fully interpretable.
5. Add champion warnings when a challenger improves metrics but has weaker interpretability than baseline.

### Acceptance Criteria

- RF and GBDT nodes produce generic model artifacts and scored datasets.
- Branch comparison can compare logistic, decision tree, RF, and GBDT.
- Reports show model family, feature strategy, feature importance, and interpretability level.
- Champion promotion requires validation, limitation, and explainability evidence before RF/GBDT can be selected.

## Phase 4: Expanded Validation Metrics And Threshold Policy

Goal: align Cardre validation with the metrics the paper identifies as common and
important for imbalanced credit scoring, now that non-logistic challengers exist.

### Metrics To Add

| Metric | Scope |
|---|---|
| Confusion matrix | Per selected cutoff and per role |
| Accuracy | Per cutoff and per role |
| Precision | Per cutoff and per role |
| Recall / sensitivity | Per cutoff and per role |
| Specificity | Per cutoff and per role |
| F1 | Per cutoff and per role |
| G-Mean | Per cutoff and per role |
| Cost-weighted error | Per cutoff and per role when cost policy exists |
| AUC | Already present |
| Gini | Already present |
| KS | Already present |
| Calibration | Already present, improve formatting |
| PSI | Already present, keep role comparisons |

### Implementation Details

1. Update `ValidationMetricsNode` to accept optional threshold policy artifacts.
2. Emit metrics at default 0.5, KS-optimal, configured cutoffs, and threshold policy cutoffs.
3. Keep the Phase 0 cutoff-label fix in place; no metric may derive observed labels from predictions.
4. Add validation summaries for branch comparison snapshots.
5. Report metric limitations when a role has single-class outcomes or missing target labels.
6. Add a `cardre.threshold_optimization` node for Youden index, max F1, max G-Mean, and custom cost minimization.
7. Threshold optimization must emit a policy artifact; it must not overwrite model probabilities.

### Acceptance Criteria

- All metrics are computed from actual target labels.
- Single-class samples produce warnings, not misleading zeros.
- Branch comparison can rank models by AUC, KS, F1, G-Mean, and cost objective.
- Threshold policy records objective, selected threshold, and tradeoffs.
- Tests cover imbalanced data, single-class edge cases, and class-order inversion.

## Phase 5: Thin Explainability And Limitation Evidence

Goal: make early challenger models governable before adding broader methods.

### Node Inventory

| Node | Purpose |
|---|---|
| `cardre.model_explainability` | Coefficients, scorecard points, decision tree rules, RF/GBDT feature importance, permutation importance |
| `cardre.model_limitations` | Structured limitations for interpretability, imbalance, dimensionality, data quality, optional dependency status |

### Explainability Levels And Champion Treatment

| Explanation level | Eligible model families | Champion treatment |
|---|---|---|
| Native scorecard | Logistic scorecard | Fully eligible when validation evidence passes |
| Native interpretable | Shallow decision tree | Eligible with rule report |
| Native semi-transparent | RF, GBDT, XGBoost, LightGBM, CatBoost | Eligible only with interpretability warning and accepted limitation evidence |
| Post-hoc only | SVM, KNN, stacking, neural nets | Requires explicit limitation acceptance; not part of early governed delivery |
| No explanation artifact | Any model | Not champion-eligible |

### Acceptance Criteria

- Reports can show why a branch is less interpretable than baseline.
- Champion promotion blocks models with no explanation artifact.
- RF/GBDT promotion requires limitation evidence even if metrics improve.
- SHAP/LIME, when later added, are labelled post-hoc and not equivalent to native scorecard interpretability.

## Phase 6: Thin UI/API Integration

Goal: expose the governed method framework early enough to avoid backend method
sprawl and make challenger branches understandable.

### Sidecar API

Add or extend endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /node-types` | Include method family, dependency status, feature strategies, interpretability level, champion eligibility |
| `GET /node-types/{node_type}/schema` | Parameter schema and defaults |
| `POST /plans/{plan_id}/branches/from-template` | Create governed challenger branch from method template |
| `GET /branches/{branch_id}/method-summary` | Model family, metrics, limitations, evidence readiness, warnings/blocks |
| `GET /comparisons/{comparison_id}/model-ranking` | Rank branches by selected metric and governance constraints |

### Frontend UX

Recommended thin UI concepts:

1. Method summary showing model family, feature strategy, dependency status, and interpretability level.
2. Template action to create a decision-tree challenger branch.
3. Branch readiness checklist showing pass, warn, block, not applicable, and insufficient evidence states.
4. Metrics leaderboard with AUC/KS/F1/G-Mean available and accuracy not used as the default sole ranking.
5. Interpretability and limitation warning badges.
6. Champion promotion gate requiring validation, explainability, and limitation evidence.

### Acceptance Criteria

- Users can create a decision-tree challenger branch without editing raw JSON.
- Missing optional dependencies are visible before run execution.
- UI does not rank by accuracy alone by default.
- Champion promotion displays metric gain and governance tradeoffs.

## Phase 7: Governed Feature Selection And Class-Imbalance Controls

Goal: add methodological depth without hiding important choices inside model
nodes.

### Feature Selection Decision Rule

Freeze current `VariableSelectionNode` for IV/manual-governance semantics. Do not
turn it into a general-purpose selector. Create new nodes for non-IV methods
unless the change is strictly additive, backward-compatible, and preserves the
existing artifact shape.

### Governed Feature Selection

| Node | Methods | Output |
|---|---|---|
| `cardre.feature_selection_filter` | IV threshold, missingness threshold, correlation threshold, simple chi-square where explainable | Selection definition |
| `cardre.feature_selection_embedded` | Tree importance as challenger evidence | Selection definition and importance report |

### Experimental Feature Selection Backlog

| Method | Reason deferred |
|---|---|
| RFE | Computationally heavier and harder to audit |
| Forward/backward search | Wrapper search can become opaque and slow |
| PCA/projection | Lower interpretability; components are harder to justify in credit governance |
| Mutual information | Needs careful explanation and stability evidence before governed use |

### Imbalance Controls

| Node | Methods | Governance level |
|---|---|---|
| `cardre.cost_sensitive_policy` | Class weights, false-negative/false-positive cost matrix | Governed first choice |
| `cardre.resample_training_data` | Random under-sampling and over-sampling | Governed with explicit lineage |
| `cardre.smote_training_data` | SMOTE and variants | High-friction advanced method; optional dependency |
| `cardre.outlier_screening` | Report-only LOF/isolation forest initially | Advanced; exclusion mode requires branch evidence |

### Synthetic Data Rules

1. Synthetic data must be train-only.
2. Synthetic rows must never appear in validation, test, or OOT artifacts.
3. Reports must show original and synthetic class distributions.
4. Champion promotion requires explicit rationale if synthetic data was used.
5. Calibration must be checked after resampling.
6. Cutoff and approval-rate evidence must be based on real validation data, not resampled training data.

### Acceptance Criteria

- Feature selection artifacts include selected, rejected, reason, score, method, and source artifact ids.
- Business overrides remain explicit and always require reasons.
- Class-weighted and resampled branches can be compared against plain branches.
- Synthetic-data use is visible in governance output and champion promotion.

## Phase 8: Optional Boosting Libraries

Goal: add high-value optional methods from the paper without making default
Cardre heavy.

### Node Inventory

| Node | Optional dependency | Notes |
|---|---|---|
| `cardre.xgboost_classifier` | `xgboost` | High-priority optional method after core GBDT |
| `cardre.lightgbm_classifier` | `lightgbm` | Efficient large-tabular method |
| `cardre.catboost_classifier` | `catboost` | Strong categorical handling, useful when raw categorical support exists |

### Implementation Details

1. Add import guards with clear installation instructions.
2. Reuse generic model contract and apply path.
3. Record native feature importance and package versions.
4. Add optional CI job or local marker for optional dependency tests.
5. Require explicit feature strategy and explainability/limitation evidence before champion eligibility.

### Acceptance Criteria

- Default install and default tests do not require boosting packages.
- Installed optional packages enable nodes only when imports succeed or explicit registry configuration allows them.
- Missing optional dependency errors are user-actionable.
- Boosting branches are marked semi-transparent and require limitation evidence for champion promotion.

## Phase 9: Fairness, Proxy, And Alternative-Data Governance

Goal: add concrete governance gates for fairness and alternative-data usage.

### Node Inventory

| Node | Purpose |
|---|---|
| `cardre.fairness_report` | Group metrics, approval rates, error rates, score distribution by sensitive group |
| `cardre.proxy_risk_report` | Correlation and importance checks for sensitive/prohibited variables and proxies |
| `cardre.alternative_data_manifest` | Consent, source, recency, retention, coverage, missingness, privacy, and allowed-use evidence |

### Sensitive Column Flow

Sensitive columns may be retained as governance-only passthrough columns in
scored datasets or attached through a protected fairness join artifact. They must
be excluded from `feature_contract.features` unless a project policy explicitly
allows their use. If they are used in training, Cardre must emit a governance
warning and require a policy-backed reason.

### Gate States

Governance evidence should use explicit states:

| State | Meaning |
|---|---|
| `pass` | Evidence exists and passes configured policy |
| `warn` | Evidence exists with concerns requiring acknowledgement |
| `block` | Missing or failed evidence blocks champion promotion |
| `not_applicable` | Evidence is not applicable to this branch or milestone |
| `insufficient_evidence` | Data exists but group sizes or coverage are too small for a reliable conclusion |

### Promotion Gates

1. If alternative-data features are used and `alternative_data_manifest` is missing, promotion is blocked.
2. If sensitive columns are available and fairness report is missing, promotion warns or blocks according to project policy.
3. If proxy-risk report flags high proxy risk, promotion requires override reason.
4. If group counts are below threshold, report says `insufficient_evidence`, not `pass`.
5. If a model improves AUC but worsens approval or error parity materially, comparison summary must show the tradeoff.

### Acceptance Criteria

- Fairness evidence never requires sensitive columns to be model features.
- Small groups are suppressed or reported as insufficient evidence.
- Alternative-data branches require provenance and consent evidence before champion promotion.
- Comparison snapshots include fairness tradeoffs when evidence exists.

## Phase 10: Advanced Research Challengers

Goal: preserve room for paper-covered methods without pulling Cardre away from
its governed scorecard product identity.

### Advanced Ensemble Inventory

| Node | Methods | Status |
|---|---|---|
| `cardre.voting_ensemble` | Hard/soft voting across selected fitted model artifacts | Advanced |
| `cardre.stacking_ensemble` | Base learners plus meta learner | Deferred — needs fold-level base-model artifacts and leakage-safe semantics |
| `cardre.weighted_ensemble` | User-defined or validation-optimized weights | Advanced |
| `cardre.dynamic_ensemble` | Segment- or cluster-specific model choice | Research backlog |
| `cardre.segmented_model_fit` | Fit separate model per cluster/segment | Research backlog |

### Ensemble Artifact Selection

Ensemble nodes must consume explicitly selected fitted model artifact ids. They
must not consume branch names ambiguously, discover hidden models, or refit base
models unless the refit is represented as explicit child run steps.

The sidecar API and frontend must expose a model-artifact selection mechanism
before voting or stacking is user-facing.

### Stacking Leakage Lineage

Stacking must record:

1. Fold specification and random seed.
2. Fold assignment artifact.
3. Base model artifact ids per fold.
4. Out-of-fold prediction artifacts per base learner.
5. Meta-training artifact built only from OOF predictions.
6. Final base model artifact ids used for application.
7. Tests proving no test/OOT rows enter meta-training.

### Experimental Deep Learning

Only `cardre.mlp_classifier` remains in scope as a future experimental tabular
challenger, and only after model contract, explainability, limitation evidence,
and UI/API gates are mature.

`sequence_lstm_classifier` and `tabular_cnn_classifier` are out of scope for this
plan. They require a separate sequence/event artifact model or tabular-to-image
research plan before implementation.

### Acceptance Criteria

- Advanced challengers are hidden from default governed templates.
- Ensemble lineage is fully visible in artifacts and reports.
- Stacking leakage controls are tested before release.
- Deep-learning branches are experimental and not champion-eligible without explicit limitation acceptance and explanation evidence.

## Testing Strategy

### Unit Tests

| Area | Tests |
|---|---|
| Model schema | Required fields, legacy compatibility, invalid payload rejection |
| Model nodes | Parameter validation, deterministic seeds, artifact contents |
| Apply node | Family dispatch, probability output, score direction |
| Validation | Metrics correctness, single-class warnings, cutoff correctness |
| Feature selection | Selection reasons, manual override reasons, projection warnings |
| Resampling | Class counts, synthetic-row flags, artifact lineage |
| Explainability | Native summaries, optional dependency guards, limitation warnings |
| Fairness | Group metrics, minimum group suppression, no target leakage |
| Security | Hash mismatch, untrusted binary load, arbitrary path rejection |

### Golden Numerical Fixtures

Add deterministic fixtures for:

1. Known WOE/IV values.
2. Known logistic coefficients.
3. Known decision-tree rules and predictions.
4. Known cutoff output proving target labels are used correctly.
5. Known confusion matrix at selected thresholds.
6. Class mapping where bad/default is not encoded as `1`.
7. Sklearn probability orientation where `estimator.classes_` would otherwise invert bad probability.
8. Feature order mismatch at apply time.
9. Missing column at apply time.
10. Unknown category at apply time.
11. Binary artifact tampering or untrusted-load refusal.

### Integration Tests

1. Baseline logistic scorecard branch still passes end-to-end.
2. Decision-tree challenger branch can run and compare against baseline.
3. Random-forest challenger branch can run and compare against baseline.
4. GBDT challenger branch can run and compare against baseline.
5. Feature-selection branch changes only downstream evidence.
6. Resampling branch records lineage and validation differences.
7. Explainability/fairness evidence blocks or warns champion promotion as expected.

### Optional Dependency Tests

Use pytest markers:

```python
@pytest.mark.optional_boosting
@pytest.mark.optional_imbalance
@pytest.mark.optional_explain
@pytest.mark.optional_deep
```

Run default tests:

```bash
python3 -m pytest tests/ -q
```

Run optional tests when dependencies are installed:

```bash
python3 -m pytest tests/ -q -m optional_boosting
python3 -m pytest tests/ -q -m optional_imbalance
python3 -m pytest tests/ -q -m optional_explain
python3 -m pytest tests/ -q -m optional_deep
```

## Migration Strategy

1. Do not rewrite existing run records or artifacts.
2. Keep `cardre.logistic_regression` and `logistic-regression` canonical evidence readable.
3. New plans use `model-fit`; old plans resolve `logistic-regression` as a legacy model-fit step lazily during readiness/report/comparison.
4. Report readiness should accept legacy evidence with a compatibility warning only when needed.
5. Comparison service should tolerate old coefficient-list and coefficient-map shapes.

## Reporting Changes

Add governance report sections or subsections:

| Section | Content |
|---|---|
| Method family | Baseline/challenger model type, dependency versions, training params |
| Feature strategy | Raw/WOE/projected features, selected/rejected variables, manual overrides |
| Preprocessing lineage | Encoders, imputers, WOE maps, selection artifacts, resampling artifacts, calibration artifacts |
| Imbalance treatment | Class distribution, resampling, class weights, synthetic-data use |
| Validation leaderboard | AUC, KS, Gini, precision, recall, specificity, F1, G-Mean, PSI, calibration |
| Cutoff policy | Threshold objective, approval rate, bad rate, capture rate, cost tradeoff |
| Explainability | Coefficients, points, rules, feature importance, SHAP/LIME/permutation summaries |
| Fairness and proxy risk | Group metrics, approval parity, error parity, proxy warnings |
| Limitations | Interpretability, data quality, OOT absence, high dimensionality, optional dependency status |
| Champion rationale | Selected branch, metric gains, governance tradeoffs, approval reason |

### Report Section Gating

| Milestone state | Report behavior |
|---|---|
| Evidence not implemented yet | Section may show `not_applicable` or `not implemented in this milestone` |
| Evidence optional for current milestone | Section appears as warning only when absent |
| Evidence required by active milestone | Missing evidence becomes warning or blocker according to report/champion mode |
| Champion promotion | Required evidence gates must be pass or explicitly accepted according to policy |

## Security, Privacy, And Governance Requirements

1. Alternative-data artifacts must record source, consent basis, permitted use, retention, refresh date, missingness, and coverage.
2. Sensitive columns should be allowed for fairness analysis without being model features.
3. Binary model artifacts must be treated as untrusted serialized objects.
4. Only load binary estimators from the project artifact store after hash verification.
5. Refuse arbitrary external pickle/joblib paths by default.
6. Store hash, estimator format, creating run id, and creating run step id for every binary estimator artifact.
7. Warn when importing external binary models.
8. Prefer JSON-native exports where feasible; later evaluate safer persistence formats such as `skops` or ONNX.
9. Reports must flag black-box or post-hoc-only explanations.
10. Champion promotion should warn or block when a challenger has materially better metrics but weaker interpretability or fairness evidence.

## Parallelisation Plan

The core principle is that Phase 0/1 is the foundation gate, then work fans out
in controlled batches. The decision-tree milestone is a serial checkpoint before
broad parallelism.

### Batch 0: Correctness + Contract (M1)

Phase 0 and Phase 1 form the foundation. Within this batch, two tracks run in
parallel:

| Track | Scope |
|---|---|
| A: Cutoff hotfix | Phase 0 cutoff label fix + regression tests |
| B: Model contract | Phase 1 schema, apply dispatch, readiness/comparison, secure loading |

Merge together for M1. No non-logistic model can proceed until both tracks land.

### Batch 1: First Challenger (M2)

Decision tree only. Mostly serial because it proves the generic model path:

- Model node implementation
- Rule export and JSON-native artifacts
- Comparison/report adjustments
- Golden fixtures

Some parallelism is possible on tests vs. node implementation, but the batch is
intentionally narrow to validate architecture before broad fan-out.

### Batch 2: Core Benchmark Set (M3–M4)

Good parallelism after decision tree proves the contract:

| Track | Scope |
|---|---|
| A: Random forest | Phase 3 RF node |
| B: Sklearn GBDT | Phase 3 GBDT node |
| C: Expanded metrics | Phase 4 validation metrics + threshold policy |

These three tracks are independent and can run concurrently.

### Batch 3: Governance + Thin UI (M5–M6)

Strong parallelism:

| Track | Scope |
|---|---|
| A: Explainability + limitations | Phase 5 model explainability, limitation evidence, champion gates |
| B: Sidecar + frontend | Phase 6 branch templates, readiness checklist, leaderboard, champion gate UI |

### Batch 4: Feature Selection + Imbalance (M7)

Medium parallelism:

| Track | Scope |
|---|---|
| A: Feature selection | Phase 7 filter and embedded selection nodes |
| B: Class weights + resampling | Phase 7 cost-sensitive policy, resampling, SMOTE, synthetic-data controls |

### Batch 5: Optional Boosting + Fairness (M8–M9)

Parallel after governance gates exist:

| Track | Scope |
|---|---|
| A: Optional boosting | Phase 8 XGBoost/LightGBM/CatBoost nodes |
| B: Fairness + alternative data | Phase 9 fairness report, proxy risk, alternative data manifest |

### Batch 6: Advanced Research (M10)

Defer until core governed challenger workflow is stable. No parallelism
assumed — this is research backlog work.

### Why Not Full Parallelism From The Start

The old approach allowed sklearn nodes + feature selection + imbalance + metrics
all in parallel. This is too broad because:

1. The generic model contract is unproven until decision tree passes the full
   apply → validate → compare → report path.
2. RF/GBDT without proven contract mechanics risks building on unstable ground.
3. Feature selection and imbalance controls depend on the metrics and threshold
   infrastructure from Phase 4.
4. Explainability and UI depend on knowing which model families exist and how
   their artifacts look.

The revised plan enforces a serial checkpoint at M2 (decision tree) before
broad fan-out, reducing rework risk.

### Delivery Order

| Milestone | Batch | Scope | User-visible result |
|---|---|---|---|
| M1 | 0 | Phase 0 + Phase 1 | Correct cutoff evidence, generic model artifact, logistic compatibility |
| M2 | 1 | Phase 2 | Decision tree challenger only; first proof of non-logistic generic path |
| M3 | 2 | Phase 3 (RF + GBDT) | RF and sklearn GBDT challengers as the core ML benchmark set |
| M4 | 2 | Phase 4 | Expanded validation metrics and threshold policy |
| M5 | 3 | Phase 5 | Thin explainability and limitation evidence; champion gates |
| M6 | 3 | Phase 6 | Thin UI/API branch templates, readiness, leaderboard, champion gates |
| M7 | 4 | Phase 7 | Governed feature selection, class weights, resampling, synthetic-data controls |
| M8 | 5 | Phase 8 | Optional XGBoost/LightGBM/CatBoost challengers |
| M9 | 5 | Phase 9 | Fairness, proxy-risk, and alternative-data governance |
| M10 | 6 | Phase 10 | Advanced ensemble and experimental research methods |

## Non-Goals

1. Do not make deep learning part of the default governed scorecard path.
2. Do not auto-promote the highest metric model to champion.
3. Do not hide preprocessing, resampling, feature selection, or threshold optimization inside model nodes.
4. Do not require optional ML libraries for normal Cardre installation.
5. Do not claim SHAP/LIME explanations are equivalent to native scorecard interpretability.
6. Do not default all challenger models to WOE features.
7. Do not expose advanced/research methods as normal branch templates.
8. Do not make SVM, KNN, Naive Bayes, PCA, stacking, LSTM, or tabular CNN part of the near-term governed roadmap.
9. Do not allow champion promotion without required evidence gates passing or being explicitly accepted according to policy.

## Immediate Next PR Recommendation

Start with Phase 0 and Phase 1.

The smallest safe first PR should include:

1. `CutoffAnalysisNode` target-label fix.
2. Cutoff regression tests proving actual target labels drive bad rate and capture rate.
3. `cardre.model_artifact.v1` schema helpers.
4. Updated logistic model artifact output preserving legacy fields.
5. Explicit probability orientation fields: `target_event_value`, `class_mapping`, and `probability_column_index`.
6. Generic `ApplyModelNode` dispatch for legacy and v1 logistic artifacts.
7. Readiness/comparison compatibility for `model-fit` and lazy legacy `logistic-regression` resolution.
8. Secure binary-estimator loading policy scaffolding, even if no non-logistic binary estimator is used yet.
9. Tests proving existing scorecard runs still work.

This unlocks decision tree as the first non-logistic challenger without forcing a
large dependency, broad model inventory, or full UI change in the first
implementation step.
