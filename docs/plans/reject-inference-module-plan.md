# Reject Inference Module — Comprehensive Plan

> Derived from: Anderson Ch. 19, Ehrhardt et al. (2021), Kozodoi et al. (2019),
> toad (augmentation weights), Sakhi_finance (counterfactual patterns).
> Aligned with Cardre's branching DAG architecture, typed evidence system, and
> governance-first design.

---

## 1. Architecture Overview

Reject inference is modeled as a **branchable pipeline stage**, consistent with
Cardre's DAG architecture. Each inference method is a separate branch; the
comparison and sensitivity surfaces expose assumption-vs-performance tradeoffs
consistent with the literature's finding that no method is universally superior.

### Pipeline Position

Positioned between `development-sample-definition` and `split-train-test-oot`.
Reject inference enriches the development sample before binning/WOE/model
fitting, so the downstream pipeline operates on augmented data identically to
normal data.

```
Normal pathway (no rejects):
  input → define-modelling-metadata → development-sample-definition
       → split-train-test-oot → fine-classing → WOE → model → validation

Reject inference pathway:
  input → define-modelling-metadata → development-sample-definition
       → define-reject-population              [NEW]
       → reject-inference-{method}             [NEW — branches here]
       → split-train-test-oot                 [reuses existing node]
       → fine-classing → WOE → model → validation
       → reject-inference-sensitivity          [NEW — report/comparison]
```

### Core Principle

The Ehrhardt et al. (2021) paper proves several methods collapse to "ignore
rejects" under MAR + well-specified model. Cardre's value is not picking the
"right" method — it's making every method's assumptions visible, auditable, and
comparable. Each node produces a documented trail of exactly what was assumed,
how, and with what effect.

---

## 2. Data Flow

The `reject-inference-{method}` node consumes:
- `input` (full through-the-door population, financed and non-financed rows)
- `definition` (modelling metadata: target column, good/bad values)
- `reject-config` (from `define-reject-population`: which rows are non-financed)

It produces:
- `input` (augmented development sample — all rows have outcomes, real or
  inferred; or weighted/resampled; or financed-only)
- `report` (structured evidence of method, assumptions, parameters, weights)

The split node operates on the augmented input, producing `train`, `test`, `oot`
as usual. All downstream nodes (fine classing, WOE, model fitting, validation)
work unchanged.

---

## 3. New Evidence Kinds and Data Structures

### EvidenceKind Entries — add to `EvidenceKind` enum in `evidence.py`

| Enum value | Schema version | Purpose |
|------------|----------------|---------|
| `REJECT_POPULATION_CONFIG` | `cardre.reject_population_config.v1` | Reject population definition |
| `REJECT_INFERENCE_RESULT` | `cardre.reject_inference_result.v1` | Inference method evidence |
| `REJECT_INFERENCE_SENSITIVITY` | `cardre.reject_inference_sensitivity.v1` | Cross-branch sensitivity |

### `RejectPopulationConfig`

```
schema_version: str                    # "cardre.reject_population_config.v1"
source_artifact_id: str
total_rows: int                        # through-the-door population size
financed_rows: int                     # known-outcome rows
non_financed_rows: int                 # unknown-outcome rows
indeterminate_rows: int                # excluded indeterminate rows
rejection_source: str                  # "flag_column" | "target_missing" | "score_cutoff"
rejection_column: str | None           # column name if flag_column
rejection_values: list[str] | None     # indicator values for rejection
exclusion_categories: dict[str, int]   # e.g. {"policy_reject": 120, "ntu": 45}
observation_window_note: str           # free-text documentation
```

### `RejectInferenceResult`

```
schema_version: str                    # "cardre.reject_inference_result.v1"
source_artifact_id: str
method: str                            # "none" | "augmentation" | "parceling" | "self_learning"
method_params: dict[str, Any]          # parameter snapshot
missingness_assumption: str            # "MAR" | "MNAR" | "agnostic"
ignorability_note: str                 # free-text assumption documentation
theoretical_limitations: list[str]     # from literature review
n_financed: int
n_non_financed: int
n_inferred_good: int                   # rows with inferred good outcome
n_inferred_bad: int                    # rows with inferred bad outcome
n_never_labeled: int                   # self-learning: rows never confident enough
resampling_factor: float | None        # augmentation: resampling multiplier
weight_summary: dict[str, float] | None  # min/max/mean/std of weights
convergence: dict[str, Any] | None     # iterations, stability, final state
runtime_seconds: float
```

### `RejectInferenceSensitivity`

```
schema_version: str
baseline_method: str                   # "none" | "augmentation" | "parceling" | "self_learning"
candidate_method: str
baseline_branch_id: str | None
candidate_branch_id: str
gini_change: dict[str, float]          # by role: train/test/oot
ks_change: dict[str, float]
psi_score_distribution: float          # PSI between baseline and candidate scores
approval_rate_shift: float             # absolute change in approval rate at cutoff
decile_migration: dict[str, float]     # fraction per decile that changed decile
population_impact: list[dict]          # per-decile approval rate changes
correlation_between_scores: float      # Pearson r between baseline and candidate scores
parameter_sensitivity: dict | None     # method-specific parameter sweeps
limitations: list[str]
verdict: str                           # "candidate_better" | "baseline_better" | "inconclusive"
```

---

## 4. Node Specifications

### 4.0 `DefineRejectPopulationNode`

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.define_reject_population` |
| `version` | `1` |
| `category` | `transform` |
| `input_roles` | `["input", "definition"]` |
| `output_roles` | `["definition"]` |

**Parameters:**
- `rejection_source` (str, default `"target_missing"`): `"target_missing"` |
  `"flag_column"` | `"score_cutoff"`
- `rejection_column` (str | None): column name if `flag_column`
- `rejection_values` (list[str], default `["1", "true", "yes"]`): values
  indicating rejection in the flag column
- `exclusion_categories` (dict[str, list], default `{}`): named categories of
  rows to exclude entirely, each with column+values, e.g.
  `{"policy_reject": {"column": "reject_reason", "values": ["fraud", "KYC"]}}`

**Behavior:**
1. Read the full input dataset (through-the-door population)
2. Read `MODELLING_METADATA` for target column and good/bad values
3. Classify every row:
   - **Financed**: known target value ∈ good ∪ bad, not excluded
   - **Non-financed**: missing/unknown target, not excluded, not indeterminate
   - **Indeterminate**: declared indeterminate in metadata
   - **Excluded**: matching an exclusion category (policy reject, NTU, ...)
4. Validate: no overlapping classifications, both sets non-empty or warn
5. Write `RejectPopulationConfig` artifact (role: `definition`)
6. Return `NodeOutput` with counts in metrics

**Rationale for being its own node:** Separating population definition from
method application lets users define rejects once and branch on method — they
don't re-configure the population for every branch.

---

### 4.1 `RejectInferenceNoneNode` (Baseline — Explicit "No RI")

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.reject_inference_none` |
| `version` | `1` |
| `category` | `transform` |
| `input_roles` | `["input", "definition"]` |
| `output_roles` | `["input", "report"]` |

**Parameters:** None

**Behavior:**
1. Read the reject population config
2. Filter input dataset to financed rows only (known outcomes)
3. Pass through unchanged as the "augmented" input
4. Write `RejectInferenceResult` with `method="none"`,
   `missingness_assumption="MAR"`, `ignorability_note` explaining that ignoring
   rejects assumes p(y|x,f) = p(y|x)
5. Return both artifacts

**Why an explicit node:** Makes the "ignore rejects" baseline auditable. The
sensitivity node can then reference this branch's documented assumptions when
comparing against inference methods.

---

### 4.2 `RejectInferenceAugmentationNode` (Propensity Re-weighting — MAR)

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.reject_inference_augmentation` |
| `version` | `1` |
| `category` | `transform` |
| `input_roles` | `["input", "definition"]` |
| `output_roles` | `["input", "report"]` |

**Parameters:**
- `method` (str, default `"resample"`): `"resample"` (bootstrap) |
  `"weight_fit"` (use sample weights — requires downstream support)
- `n_score_bands` (int, default `10`): equal-frequency bands for propensity
- `min_samples_per_band` (int, default `30`): merge below this
- `band_min_p_financed` (float, default `0.01`): floor for estimated
  p(financed\|band) to avoid extreme weights
- `random_seed` (int, default `42`)

**Behavior:**
1. Read reject population config
2. Fit a logistic regression on financed rows using all numeric features
3. Score ALL applicants through this model
4. Create K equal-frequency score bands on the full population
5. For each band k: estimate `p_k = n_financed_in_band / n_total_in_band`
6. Compute weight for each financed row: `w_i = 1 / max(p_k, band_min_p_financed)`
7. **If `method=resample`**: draw a bootstrap sample of size = n_financed from
   the financed rows, with replacement, probabilities proportional to w_i
8. Write the resampled/weighted dataset as a plain Parquet artifact (no special
   column needed for resample; add `_ri_weight` column for `weight_fit`)
9. Write `RejectInferenceResult` with `missingness_assumption="MAR"`,
   documenting the band-level propensity statistics and resampling factor
10. Return both artifacts

**Limitations (documented in artifact):**
- Assumes p(financed|x,y) = p(financed|x) (MAR)
- Requires p(financed|x) > 0 for all x in the population
- Band-based estimation may pool dissimilar applicants
- Resampling introduces Monte Carlo variance

---

### 4.3 `RejectInferenceParcelingNode` (Prudence Factors — MNAR)

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.reject_inference_parceling` |
| `version` | `1` |
| `category` | `transform` |
| `input_roles` | `["input", "definition"]` |
| `output_roles` | `["input", "report"]` |

**Parameters:**
- `n_score_bands` (int, default `10`)
- `prudence_factors` (list[float], default `[]`): per-band epsilon_k (ε_k ≥ 1).
  If empty, defaults to `[1.0 + k*0.05 for k in range(K)]`. Each ε_k must be
  ≥ 1.0.
- `enforce_monotonic` (bool, default `True`): require ε_1 ≤ ε_2 ≤ ... ≤ ε_K
- `max_iterations` (int, default `50`): EM iteration limit
- `convergence_tol` (float, default `1e-4`)
- `max_depth_initial_model` (int, default `3`): complexity of the initial
  financed-only model

**Behavior:**
1. Read reject population config
2. Fit baseline model on financed rows only
3. Score all applicants through baseline model
4. Assign each row to a score band (equal-frequency)
5. Initialize non-financed outcome probabilities:
   `p_bad(x_i, nf) = ε_k * p_bad(x_i, f)` where k is the band of x_i
   (capped at 1.0)
6. Impute outcomes for non-financed rows via MAP from adjusted probabilities
7. Re-fit model on financed + imputed non-financed
8. Re-score → re-band → re-impute → re-fit until convergence or max iterations
9. Write augmented input dataset
10. Write `RejectInferenceResult` with `missingness_assumption="MNAR"`,
    convergence diagnostics, and a strong note that prudence factors are
    unverifiable expert beliefs (per Ehrhardt 2021 §3.7)

**Unique requirement:** The `ignorability_note` must explain WHY the chosen
prudence factors are appropriate for this portfolio. This is the key
regulatory-documentation value of this node.

---

### 4.4 `RejectInferenceSelfLearningNode` (Kozodoi-style Iterative Labeling)

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.reject_inference_self_learning` |
| `version` | `1` |
| `category` | `transform` |
| `input_roles` | `["input", "definition"]` |
| `output_roles` | `["input", "report"]` |

**Parameters:**
- `initial_labeling` (str, default `"financed_model"`): `"financed_model"` |
  `"random"` | `"majority_class"`
- `label_type` (str, default `"soft"`): `"soft"` (float probability — EM-like) |
  `"hard"` (0/1 MAP — Classification-EM). Soft is recommended to avoid the
  sharpening bias identified by Ehrhardt.
- `labeling_threshold` (float, default `0.8`): probability above/below which a
  pseudo-label is accepted
- `training_regime` (str, default `"incremental"`): `"incremental"` (add
  confident labels each round) | `"batch"` (re-label all rejects each round)
- `max_iterations` (int, default `10`)
- `min_new_labels_ratio` (float, default `0.05`): stop if fewer than this
  fraction of non-financed rows are newly labeled
- `stability_window` (int, default `3`): consecutive rounds without label
  changes → early stop
- `min_labeled_ratio` (float, default `0.2`): warn if final labeled ratio below
  this

**Behavior:**
1. Read reject population config
2. Train initial model on financed rows
3. Predict outcomes for non-financed rows
4. Select confident predictions: `p > labeling_threshold` or `p < 1 - labeling_threshold`
5. Assign pseudo-labels (soft probabilities or hard 0/1)
6. **Incremental regime**: add newly labeled rows to training set, retain
   previously labeled rows
7. **Batch regime**: re-label all rejects from current model each round
8. Re-train on financed + pseudo-labeled
9. Repeat until max_iterations, stability, or insufficient new labels
10. Rows never confidently labeled remain excluded
11. Write augmented input dataset (financed + confidently labeled non-financed)
12. Write `RejectInferenceResult` with convergence history, iteration-level
    label counts, and `missingness_assumption="agnostic"`

**Literature note:** This method is based on Kozodoi et al. (2019) "Shallow
Self-Learning for Reject Inference in Credit Scoring." The soft-label
incremental variant avoids the Classification-EM bias identified by Ehrhardt
et al. (2021) §3.4.

---

### 4.5 `RejectInferenceSensitivityNode` (Cross-Branch Comparison)

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.reject_inference_sensitivity` |
| `version` | `1` |
| `category` | `report` |
| `input_roles` | `["train", "test", "oot", "definition", "report"]` |
| `output_roles` | `["report"]` |

**Parameters:**
- `baseline_branch_id` (str | None, default `None`): branch ID for comparison
  baseline. `None` = compare against the "no reject inference" branch.
- `candidate_branch_id` (str): branch ID for the candidate method
- `cutoff` (float, default `0.5`): the decision threshold for approval rate
  calculations

**Behavior:**
1. Scored datasets from both branches with predicted probabilities
2. Per-branch per-role: Gini, KS, bad rate, approval rate at cutoff
3. Cross-branch distribution shifts:
   - **PSI** of score distributions
   - **KS test** of score distributions
   - **Decile migration matrix**: what proportion of applicants change score
     decile between branches?
4. Cross-branch population impact:
   - Approval rate change by baseline-score decile
   - Which applicants are most affected? (describe by feature profile)
5. Read both branches' `RejectInferenceResult` artifacts
6. Compare stated assumptions side by side
7. Compute parameter sensitivity (where applicable):
   - For parcelling: iterate over plausible prudence factor ranges
   - For augmentation: vary n_score_bands
8. Produce verdict: which method improves Gini? shifts population? introduces
   more instability?
9. Write `RejectInferenceSensitivity` artifact
10. Return both artifact and computed metric dict

**This is the most important node for Cardre's audit/governance story.** It does
not tell the user reject inference is "better" — it tells them exactly what
changes when they include it. The verdict field is directional, not prescriptive.

---

## 5. Branch Point Integration

### New branch point type

In `branch_service.py`, `ALLOWED_BRANCH_POINTS`:

```python
"define-reject-population": "reject_inference_challenger",
```

The canonical step ID at this branch point is `"define-reject-population"`.
Branching here duplicates the downstream subgraph: all steps from `split` onward
(split → fine classing → WOE → model → validation).

### Expected branch structure

```
Main trunk (or "no-ri" branch):
  define-reject-population → reject-inference-none → split → ... → validation-metrics

Branch "augmentation":
  define-reject-population → reject-inference-augmentation → split → ... → validation-metrics

Branch "parceling":
  define-reject-population → reject-inference-parceling → split → ... → validation-metrics

Branch "self-learning":
  define-reject-population → reject-inference-self-learning → split → ... → validation-metrics
```

### Comparison registration

In `comparison_service.py`, `REQUIRED_EVIDENCE_CANONICAL_STEPS` gains:

```python
"define-reject-population",
```

The comparison service compares `validation-metrics` and
`reject-inference-sensitivity` across branches.

### Champion/challenger

Champion assignment operates on validated model branches. A branch with reject
inference can be champion — the sensitivity report becomes part of the champion
evidence bundle.

---

## 6. Reporting Integration

### Report schema additions (`reporting/schema.py`)

```python
class RejectInferenceSensitivityInfo(BaseModel):
    psi_score_distribution: float | None
    gini_change: dict[str, float]
    approval_rate_shift: float | None
    correlation_between_scores: float | None
    verdict: str | None

class RejectInferenceInfo(BaseModel):
    method: str
    missingness_assumption: str
    ignorability_note: str
    n_financed: int
    n_non_financed: int
    n_inferred_good: int | None
    n_inferred_bad: int | None
    weight_summary: dict[str, float] | None
    sensitivity: RejectInferenceSensitivityInfo | None

# In ReportBundle:
reject_inference: RejectInferenceInfo | None = None
```

### Collector extension (`reporting/collector.py`)

New method `_collect_reject_inference()` that:
1. Tries to read `REJECT_POPULATION_CONFIG` from run artifacts
2. If found, reads the `REJECT_INFERENCE_RESULT` artifact
3. If both found and a comparison exists, reads `REJECT_INFERENCE_SENSITIVITY`
4. Populates `RejectInferenceInfo` on the bundle

This is an optional section — most reports won't have it. The collector should
fail softly (set `reject_inference = None`) rather than blocking report
generation.

### HTML report template

The report.html.j2 template gains an optional section:

```
Reject Inference
├── Method: "augmentation" (MAR)
├── Population: 15,432 financed, 4,212 non-financed
├── Inferred: 2,101 good, 2,111 bad
├── Missingness assumption: MAR — financing depends only on x
├── Weight summary: mean 1.24, max 4.87
└── Sensitivity vs baseline:
    ├── Gini change: train +0.012, test +0.009, oot +0.007
    ├── PSI score distributions: 0.023
    ├── Approval rate shift at cutoff 0.5: +3.2%
    └── Verdict: candidate_better
```

### Readiness checks (`reporting/readiness.py`)

- If a branch has no `define-reject-population` step: report is valid (normal,
  no reject inference)
- If it has `define-reject-population` but no completed `reject-inference-*`
  step: warning ("reject population defined but no inference method applied")
- If it has both: no additional blockers (the reject inference section is
  optional in the report)

---

## 7. Files to Create or Modify

| File | Action | Notes |
|------|--------|-------|
| `cardre/nodes/reject_inference.py` | **CREATE** | All 6 node classes (~600 lines) |
| `cardre/evidence.py` | **MODIFY** | +3 EvidenceKind entries, +3 frozen dataclasses, +3 schema constants |
| `cardre/nodes/__init__.py` | **MODIFY** | Import and re-export all 6 node classes |
| `cardre/registry.py` | **MODIFY** | Register all 6 node types |
| `cardre/services/branch_service.py` | **MODIFY** | +1 entry in ALLOWED_BRANCH_POINTS |
| `cardre/services/comparison_service.py` | **MODIFY** | +1 entry in REQUIRED_EVIDENCE_CANONICAL_STEPS |
| `cardre/reporting/collector.py` | **MODIFY** | +1 collector method |
| `cardre/reporting/schema.py` | **MODIFY** | +2 Pydantic models |
| `cardre/reporting/readiness.py` | **MODIFY** | +reject inference warning |
| `cardre/reporting/templates/report.html.j2` | **MODIFY** | +optional reject inference section |
| `tests/test_reject_inference.py` | **CREATE** | 15+ unit tests |
| `tests/test_reporting_reject_inference.py` | **CREATE** | 3+ reporting integration tests |

**Files that must NOT change:**
- `cardre/nodes/prep.py` — population definition stays upstream
- `cardre/nodes/build.py` — WOE/model nodes stay downstream
- `cardre/nodes/validate/*.py` — validation nodes stay downstream
- `cardre/audit.py` — core structures irrelevant to this module
- `cardre/store.py` / `cardre/store_schema.py` — no schema migration needed

---

## 8. Testing Strategy

### Unit tests (`tests/test_reject_inference.py`)

**Population definition (4 tests):**
1. `test_define_reject_population_target_missing`: Dataset with nulls in target
   column → verify classification into financed/non-financed/indeterminate
2. `test_define_reject_population_flag_column`: Explicit `was_rejected` boolean
   column → verify correct detection
3. `test_define_reject_population_exclusion_categories`: Policy reject rows
   should be excluded from both sets
4. `test_define_reject_population_all_financed`: If no rows are rejected, the
   config should have 0 non-financed rows (warns but doesn't error)

**None method (1 test):**
5. `test_none_method_passthrough`: Output = financed-only rows, artifact
   documents MAR assumption

**Augmentation (3 tests):**
6. `test_augmentation_resample_produces_expected_count`: Bootstrap sample =
   n_financed, distributions track
7. `test_augmentation_band_estimation`: Verify band-level p_k computed
   correctly; edge case: band with all financed rows
8. `test_augmentation_min_p_financed_floor`: Band with zero financed rows uses
   `band_min_p_financed` as floor

**Parceling (3 tests):**
9. `test_parceling_prudence_one`: ε_k = 1.0 for all bands → result ≈ baseline
   (no material change)
10. `test_parceling_monotonic_enforcement`: Non-monotonic ε array raises
    validation error
11. `test_parceling_convergence`: Verify EM converges within max_iterations

**Self-learning (4 tests):**
12. `test_self_learning_incremental_label_accumulation`: Labels should increase
    each round under incremental regime
13. `test_self_learning_stability_early_stop`: When labels stop changing for
    stability_window rounds, the loop terminates early
14. `test_self_learning_threshold`: Rows with max(p,1-p) < labeling_threshold
    should never receive pseudo-labels
15. `test_self_learning_hard_vs_soft_labeling`: Hard labels should produce
    sharper decision boundary (prove the Ehrhardt bias)

**Sensitivity (3 tests):**
16. `test_sensitivity_metrics_comparison`: Two dummy scored datasets → verify
    Gini, PSI, approval rate shift computed correctly
17. `test_sensitivity_decile_migration`: Matrix of decile transitions sums to
    1.0 per row
18. `test_sensitivity_verdict_candidate_better`: Higher Gini + acceptable PSI →
    verdict "candidate_better"

**Integration (2 tests):**
19. `test_full_pipeline_with_augmentation`: Import → define target → define
    reject population → augmentation → split → fine classing → WOE → logistic
    regression → score → validate. Should produce a valid run with evidence
    artifacts at each stage.
20. `test_branch_at_reject_inference_point`: Create two branches (none,
    augmentation), run both, compare via comparison service.

### Reporting tests (`tests/test_reporting_reject_inference.py`)

1. `test_collector_reject_inference_present`: Run with augmentation branch →
    collector finds and populates RejectInferenceInfo
2. `test_collector_reject_inference_absent`: Run without reject inference →
    RejectInferenceInfo is None (no crash)
3. `test_report_renders_reject_inference_section`: Generated HTML contains
    "Reject Inference" heading when evidence exists

---

## 9. Implementation Sequence

| Phase | What | Effort | Depends on |
|-------|------|--------|------------|
| 1 | Evidence types + frozen dataclasses + schema constants | Small | — |
| 2 | `DefineRejectPopulationNode` | Small | Phase 1 |
| 3 | `RejectInferenceNoneNode` | Tiny | Phase 1+2 |
| 4 | `RejectInferenceAugmentationNode` | Medium | Phase 1+2 |
| 5 | `RejectInferenceParcelingNode` | Medium | Phase 1+2 |
| 6 | `RejectInferenceSelfLearningNode` | Medium | Phase 1+2 |
| 7 | `RejectInferenceSensitivityNode` | Medium | Phase 4-6 (needs scored data) |
| 8 | Branch point registration + comparison updates | Tiny | Phase 2 |
| 9 | Report collector + schema + readiness | Medium | Phase 4-6 |
| 10 | Tests (unit + integration + reporting) | Medium | Phase 1-9 |

**MVP (Phase 1-4, 8, 10):** Augmentation method + "no RI" baseline + branch
point. Ships with one inference method and comparison support.

**Full module (all phases):** 3 inference methods + sensitivity analysis +
reporting integration.

---

## 10. Open Questions for Implementation

1. **Sample weight support**: Does Cardre's model pipeline support
   `sample_weight`? The current model nodes (boosting.py, ml_models.py) use
   sklearn-compatible classifiers which accept `sample_weight` in `.fit()`. If
   the weight column convention isn't set up yet, the augmentation node should
   use **resampling** (bootstrap with replacement) instead — no downstream
   changes needed.

2. **Resampling seed**: Should each branch get a deterministic resampling draw
   based on its branch_id? Yes — this ensures reproducibility across runs.

3. **What if no non-financed rows exist?** The `DefineRejectPopulationNode`
   should produce a valid config with `non_financed_rows=0`. The method nodes
   should detect this case and write a warning in the result artifact. The
   `reject-inference-none` node is automatically the only valid choice.

4. **Should the parcelling node support ε_k < 1.0 (rejects are BETTER)?** The
   literature assumes ε_k ≥ 1.0 (rejects are riskier). If a user believes
   otherwise, they should use a different method. The validation should enforce
   ε_k ≥ 1.0.

5. **Should the sensitivity node auto-detect the baseline branch?** It should
   default to finding the "none" or "no reject inference" branch in the same
   project. If none exists, it should error with a clear message.

6. **Does the self-learning node need GPU support?** No — the inner model is
   logistic regression (or shallow tree), not neural networks. The computational
   cost is trivial even at 50k+ rows.

7. **How does this interact with Cardre's existing fairness module?** Reject
   inference has fairness implications: different demographic groups may have
   different rejection rates, and the inference method can amplify or mitigate
   bias. The sensitivity node should flag if the rejection rate varies
   significantly across protected groups, linking to the fairness report.

---

## 11. Relationship to Existing Cardre Features

| Feature | Relationship |
|---------|-------------|
| **Branching DAG** | Reject inference is a branch point. Each method is a branch. |
| **Champion/challenger** | Different RI methods compete as challengers. Sensitivity report is evidence for champion selection. |
| **Audit pack export** | `RejectInferenceResult` and `RejectInferenceSensitivity` are included in the audit pack. |
| **Fairness/proxy risk** | Reject inference has direct fairness implications — flagged in sensitivity report. |
| **Validation metrics** | Downstream, unchanged. The sensitivity node compares validation metrics across branches. |
| **Technical manifest** | Gets a new section for reject inference parameters and assumption documents. |
| **Report bundle** | Gets a new optional `RejectInferenceInfo` section. |
| **Plan steps/params** | Reject inference parameters are stored as node params in the plan version. |
| **Manual binning** | Unaffected — operates on the augmented dataset identically. |
| **ML model nodes** | Unaffected — operate on augmented train/test/oot identically. |
