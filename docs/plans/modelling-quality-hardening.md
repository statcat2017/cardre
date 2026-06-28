# Modelling-Quality Hardening Plan (Tiers A + B)

A concrete, aut orchestrator-ready, TDD plan derived from the
scorecard modelling-quality audit. **Read this whole file before
starting any phase.**

## Scope

- 15 phases across Tier A (9, pure TDD) and Tier B (6, TDD with
  encoded decisions).
- Closes **6 of the 8** audit launch-blockers (#6, #3, #2, #12, #15,
  #19) and several non-blocking gaps. The remaining two launch-blockers
  (#13 characteristic report + gains table, #16 leakage scan) are
  design-first and **explicitly out of scope** — they need ADRs before
  any test can be written and are handled in a separate human-gated
  flow.
- Single auto-phase-orchestrator invocation: phases run sequentially,
  `ce-code-review` after each, auto-fix issues, **one PR at the end**.

## Locked-in decisions (do not second-guess)

| Decision | Value | Rationale |
|---|---|---|
| `enforce_monotonic_woe` default | `False` | Additive; no behaviour change for existing runs. Champion readiness gate (B2-adjunct) closes the launch-blocker by *gating*, not by flipping the default. |
| OOT-required-for-champion | `True` in champion mode only; warn-only in branch mode | Aligns with the audit. Branch exploration stays permissive; champion promotion requires OOT evidence. |
| Zero-cell smoothing on initial pass | Apply when `smoothing` is configured; warn-only (`ZERO_CELL_INITIAL_IV_DEFLATED`) when not | Keeps selection IV ranking stable when smoothing is set; surfaces instability when it isn't. |

## How to run this plan (orchestrator instructions)

1. **One invocation, phases in the exact order below.** Do not reorder
   outside the documented dependencies.
2. Each phase follows RED → GREEN → VERIFY → GATE. Do not start RED
   for phase N+1 until GATE for phase N is green.
3. After every phase, internally run `python3 -m pytest tests/ -q`.
   A phase is not done until the **whole suite** is green — not just
   the phase's own selector.
4. Before pushing, run lint and the gate script (see "Pre-push gate"
   below).
5. The orchestrator raises a **single PR** at the end covering all 15
   phases.

## Pre-push gate (per AGENTS.md)

```bash
# Lint — bootstrap the dev venv once; ruff lives in the dev extra.
# One-time bootstrap per clone:
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[sidecar,dev,test]"

# Before pushing:
. .venv/bin/activate
ruff check --fix

# Full suite, including golden-R oracle + determinism tests.
python3 -m pytest tests/ -q

# Push + open/locate PR + poll CI to green. Only then is the PR
# "ready for human review".
scripts/pr-gate.sh
```

**Why ruff isn't reinstalled each time:** `AGENTS.md` installs the full dev
environment once, and `ruff` is part of that dev extra. Re-running a separate
`pip install ruff` step on every push just duplicates work.

## Test conventions (do not reinvent)

- pytest + polars.
- Builders: `tests/helpers/__init__.py` → `_make_train_artifact`,
  `_make_json_artifact`, `_make_parquet_report`, `make_store`.
- Evidence assertions: `tests/helpers/evidence_assertions.py`
  (`assert_woe_iv_evidence`, `assert_model_artifact`,
  `assert_score_scaling`, `assert_bin_definition`).
- Oracle fixtures: `tests/fixtures/reference_scorecard_r_german_credit/`.
- Golden helpers: `tests/golden_scorecard/helpers.py`.

## Sacred invariants (breaking these = stop and surface)

- **Golden-R oracle tests are sacred.** Any phase touching Cardre's
  WOE/IV/LR output must re-run `tests/golden_scorecard/` and pass
  within the existing tolerances. **Never relax tolerances to make a
  test pass.** If a phase would break them, stop and surface.
- **WOE formula sign is off-limits.** A1–A9, B1–B6 must leave WOE
  magnitudes bit-identical except where the phase explicitly changes
  them (B1 smoothing-consistency, B2 rejection). Pinning the WOE
  convention is explicitly out of scope.
- **No scope creep.** Each phase is scoped to its gap. Resist
  refactors. ce-code-review after each phase flags scope creep —
  treat as a hard stop.
- **No new optional dependencies.** All 15 phases use only what's
  already in `pyproject.toml`.
- **Do not flip defaults beyond what the phase says.** B2 keeps
  `enforce_monotonic_woe=False`. B5 only flips champion mode.

## Phase dependency graph

```
Block 1 (Tier A — pure TDD):
  A4 → A3 → A1 → A2 → A5 → A6 → A7 → A8 → A9
  (A4 before A3 — A3's OOT red test needs open-extreme bins.
   A6 before A7 — A7 builds on A6's convergence scaffold.)

Block 2 (Tier B — TDD with encoded decisions):
  B1 → B2 → B3 → B4 → B5 → B6
  (B3 ideally before B2 but independent; listed order is fine.)
```

# Block 1 — Tier A (pure TDD)

## Phase A4 — Fine-classing bins have open extremes

**Gap**: #4 (OOT values below train min fall through to unmatched).
**Files**: `cardre/nodes/build/bins.py:256-289`; `cardre/nodes/_bin_mask.py` (already handles `None` bounds — verify, don't change); `tests/test_binning.py`.

**RED**: `test_oot_below_train_min_maps_to_first_bin_after_fine_classing`.
- Fine-class a train frame `x in [2..6]` (no missing), `max_bins=5`,
  `min_bin_fraction=0.01`, `missing_policy="ignore"`.
- Take the emitted bin definition, run `ApplyWoeMappingNode` (or
  `build_bin_condition`) on an OOT row `x=1.0`.
- Assert the row matches the **first regular bin** (not the unmatched
  path). Today this fails because the first bin's `lower=2.0,
  lower_inclusive=True` excludes `1.0`.

**GREEN**: in `_bin_numeric`, first regular numeric bin sets
`lower=None, lower_inclusive=False` instead of
`lower=col_min, lower_inclusive=True`; last bin keeps `upper=None`.
The "all values" fallback (`bins.py:297-305`) remains unchanged.

**VERIFY**: `pytest tests/test_binning.py -k "numeric_boundaries or oot_below"`.

**GATE**: `test_numeric_bin_boundaries_non_overlapping` still passes —
update its first-bin assertion (`lower_inclusive` is now `False`,
`lower` is now `None`). No regression for non-open bins.

---

## Phase A3 — OOT-unmatched default policy becomes `fail` (launch-blocker #15)

**Files**: `cardre/nodes/validate/apply.py:54,75`; `tests/test_woe.py`.

**RED**: `test_default_woe_unmatched_policy_is_fail`.
- Build a train bin set for a categorical `["a","b","c"]` with WOE
  values; an OOT row with `cat="z"` (unseen).
- Call `ApplyWoeMappingNode().run(ctx)` with **no explicit**
  `woe_unmatched_policy`.
- Assert it raises `ValueError` containing `"did not match any bin"`.

**GREEN**:
- `apply.py:75` default `"warn"` → `"fail"`.
- Update the schema default in `apply.py:54` (`ParameterDefinition`
  default) to `"fail"`.
- Leave `warn` and `fill_zero` as explicit opt-ins.
- Update help text to reflect the new default.

**VERIFY**: `pytest tests/test_woe.py -k "unmatched or unseen or below_min"`.

**GATE**: existing tests that assumed `warn` default —
`test_below_min_numeric_value_fills_zero_by_default`,
`test_applies_woe_to_all_roles` — must now pass an **explicit**
`woe_unmatched_policy="warn"`. Update them, don't delete assertions.
Frozen-bundle-driven `fail` path unchanged
(`test_bundle_driven_fail_policy`).

---

## Phase A1 — Categorical "Other" sorts by frequency (launch-blocker #6)

**Files**: `cardre/nodes/build/bins.py:338`; `tests/test_binning.py`.

**RED**: `test_top_frequency_category_in_explicit_bin_not_other`.
- Frame:
  `[("z","good"),("z","good"),("z","good"),("a","bad"),("b","good"),("c","bad")]`
  with target column where `"good"`/`"bad"` are the good/bad values.
- `FineClassingNode` with `max_categorical_levels=2`,
  `missing_policy="separate_bin"`.
- Assert `"z"` (most frequent, alphabetically last) appears in an
  explicit bin's `categories`, and the 2 explicit bins are the top-2
  by frequency — **not** `["z","c"]` (label-descending) as today.

**GREEN**: `bins.py:338`
`vc = non_null[col].value_counts().sort(col, descending=True)` →
`vc = non_null[col].value_counts().sort("count", descending=True)`.
Polars `value_counts()` returns a 2-column frame
`(value, count)`; sort on the count column.

**VERIFY**: `pytest tests/test_binning.py -k "high_cardinality or top_frequency"`.

**GATE**: existing `test_high_cardinality_creates_other_bin` still
passes; golden WOE/IV tests unaffected (golden uses R's bins, not
Cardre fine-classing).

---

## Phase A2 — PSI floors empty bins instead of skipping (launch-blocker #12)

**Files**: `cardre/nodes/validate/analyse.py:479-504`; new or extended
test in `tests/test_comparison_service.py` or
`tests/test_reporting_acceptance.py`.

**RED**: `test_psi_empty_oot_bin_is_large_not_zero`.
- Train scores `[1,1,1,1,1,2,2,2,2,2]`; OOT scores
  `[1,1,1,1,1,1,1,1,1,1]` so one train bin is empty in OOT.
- Assert `_psi(train, oot)` ≥ ~0.69 (≈ `0.5·ln(0.5/1)·2`), and **not**
  `0.0`.
- Also assert a `PSI_EMPTY_BIN` warning is present in the validation
  evidence `warnings` (you may need to surface it from `_psi` up to the
  payload).

**GREEN**: in `_psi` (`analyse.py:479-504`):
- Replace `if ap == 0 or ep == 0: continue` with a Laplace floor
  `ep = max(ep, 0.5/n_exp); ap = max(ap, 0.5/n_act)`.
- Emit one `PSI_EMPTY_BIN` warning per floored bin (collect and return
  from `_psi`, or thread through the caller).
- Record `config.psi_floor` in the validation payload.

**VERIFY**: `pytest tests/test_reporting.py tests/test_comparison_service.py -k psi`.

**GATE**: PSI on identical distributions still ~0; PSI on a mild
(non-empty-bin) shift unaffected.

---

## Phase A5 — Validation accuracy uses known-rows denominator

**Gap**: #11 (accuracy divides by `n = df.height` including unknown-target rows).
**Files**: `cardre/nodes/validate/analyse.py:344-362`; `tests/test_reporting_acceptance.py`.

**RED**: `test_accuracy_denominator_excludes_unknown_target_rows`.
- Validation frame of 100 rows: 90 known good/bad + 10 with target
  `"unknown"` (not in good/bad sets).
- Assert `at_cutoffs["0.5"]["accuracy"] == (tp+tn)/90`, not `/100`.
- Also assert `UNKNOWN_TARGET_VALUES` warning present and the unknown
  rows excluded from `y_bin`.

**GREEN**:
- `analyse.py:347` `accuracy = (tp+tn)/n` →
  `accuracy = (tp+tn)/len(y_bin)`.
- Define `n_known = len(y_bin)` once at `:291` and use it for accuracy.
- Precision/recall/specificity divisors are already correct
  (`tp+fp`, `tp+fn`, `tn+fp`) — do not touch them.

**VERIFY**: `pytest tests/test_reporting_acceptance.py -k accuracy`.

**GATE**: existing per-role metrics tests still match within rounding.

---

## Phase A6 — Logistic regression: explicit L2 + convergence hard-fail

**Gap**: #8 (default penalty invisible; non-convergence warns only).
**Files**: `cardre/nodes/build/models.py:222-247`; `tests/test_scorecard_model.py`.

**RED**:
1. `test_standard_logit_params_explicit_l2` — run the standard-logit
   method; assert persisted model artifact
   `training.params["penalty"] == "l2"` (today it's absent — sklearn
   fills the default silently).
2. `test_lr_non_convergence_fails_step` — run `LogisticRegressionNode`
   with `max_iter=1` on a non-separable frame; assert it raises (not
   just warns). Use a new `fail_on_non_convergence=True` param to
   control.

**GREEN**:
- `models.py:222` add `"penalty": "l2"` to `lr_params` for the
  `standard_logit` method explicitly.
- Add `ParameterDefinition("fail_on_non_convergence", kind="boolean",
  default=True)` to the `standard_logit` and `penalised_logit`
  schemas.
- In `run`, when `not converged and fail_on_non_convergence`,
  `raise ValueError("Logistic regression did not converge after
  {max_iter} iterations (set fail_on_non_convergence=False to
  warn-only)")` instead of appending a warning.
- Keep the warn path for `fail_on_non_convergence=False`.

**VERIFY**: `pytest tests/test_scorecard_model.py -k "logistic_regression or convergence"`.

**GATE**: existing `test_logistic_regression_fits_and_records_coefficients`
still asserts `converged=True` with the default fixture.

---

## Phase A7 — Capture sklearn ConvergenceWarning as the convergence signal

**Gap**: #22 (convergence inferred from `n_iter_ < max_iter`, misses boundary).
**Files**: `cardre/nodes/build/models.py:241-247`; `tests/test_scorecard_model.py`.

**RED**: `test_convergence_signal_uses_sklearn_warning`.
- Patch `warnings` to capture.
- Run with a `max_iter` where `n_iter_ == max_iter` but sklearn emits
  **no** `ConvergenceWarning` → assert `converged=True`.
- Force real non-convergence (pathological features, tiny `max_iter`)
  → assert `ConvergenceWarning` captured and `converged=False`.

**GREEN**:
- Wrap `lr.fit(...)` in
  `with warnings.catch_warnings(record=True) as w: warnings.simplefilter("always"); lr.fit(...)`.
- Import `from sklearn.exceptions import ConvergenceWarning` and
  `import warnings` at module top.
- Set
  `converged = (not any(issubclass(x.category, ConvergenceWarning) for x in w)) and lr.n_iter_[0] < max_iter`.
- Preserve the existing `CONVERGENCE_FAILURE` warning emission when
  `not converged` (used by the `fail_on_non_convergence=False` path).

**VERIFY**: `pytest tests/test_scorecard_model.py -k convergence`.

**GATE**: A6 still passes; default-fixture `converged=True` unchanged.

---

## Phase A8 — `source_variables` tracked explicitly in model artifact

**Gap**: #24 (suffix-strip breaks for raw vars named `*_woe`).
**Files**: `cardre/nodes/build/models.py` (LR emits); `cardre/nodes/build/freeze.py:95-101` (consume); `tests/test_scorecard_model.py`, `tests/test_frozen_scorecard_bundle.py`.

**RED**: `test_source_variables_explicit_not_suffix_stripped`.
- Train frame with a raw variable literally named `my_woe`. Run LR.
- Assert `model_artifact["source_variables"] == ["my_woe"]`
  (not `["my"]`).
- Run `FrozenScorecardBundleNode`; assert
  `feature_contract.source_variables == ["my_woe"]`.

**GREEN**:
- In `LogisticRegressionNode.run`, when a selection-definition is
  available, read its `selected` variable names as `source_variables`;
  otherwise fall back to stripping `_woe` from feature names. Persist
  `source_variables` in the model artifact next to `features`.
- In `freeze.py:95-101`, prefer `model.get("source_variables")` when
  present; fall back to the `_woe`-strip only when absent
  (backward-compat for old artifacts).

**VERIFY**: `pytest tests/test_scorecard_model.py tests/test_frozen_scorecard_bundle.py -k "source_variables or frozen"`.

**GATE**: legacy-artifact backward-compat test (old model artifact
without `source_variables`) still passes.

---

## Phase A9 — Duplicate-value concentration warning in fine classing

**Gap**: #5 (concentrated numeric variables produce unstable bins silently).
**Files**: `cardre/nodes/build/bins.py:242-253`; `tests/test_binning.py`.

**RED**: `test_concentrated_numeric_emits_warning`.
- Frame `x = [1,1,1,1,1,1,1,1,2,3,4,5,6]` (8/13 duplicates of 1).
- Fine-class with `max_bins=5`, `missing_policy="ignore"`.
- Assert a warning with code `DUPLICATE_VALUES_CONCENTRATED` is present
  in the bin-definition `warnings`, carrying `concentration_ratio` and
  the dominant value.

**GREEN**:
- After `qcut` produces the breakpoint list, compute
  `dup_ratio = max(value_counts) / n`; if `dup_ratio > 0.5`
  (configurable threshold, default `0.5`), append the warning.
- Do **not** collapse bins — the warning is enough for MVP.

**VERIFY**: `pytest tests/test_binning.py -k concentr`.

**GATE**: existing fine-classing tests unaffected; no warning for
non-concentrated variables.

---

# Block 2 — Tier B (TDD with encoded decisions)

## Phase B1 — Zero-cell handling consistent between initial and final WOE (launch-blocker #2)

**Decision baked in**: when `smoothing` is configured on the initial
pass, apply it (same as final); when smoothing is absent on initial,
keep the current `iv_comp=0` behaviour but emit a
`ZERO_CELL_INITIAL_IV_DEFLATED` warning naming the affected variable
so selection instability is visible.

**Files**: `cardre/nodes/build/features.py:154-194`; `tests/test_woe.py`.

**RED**:
1. `test_initial_iv_zero_cell_matches_final_iv_when_smoothed` — a
   variable with one zero-cell bin; run `CalculateWoeIvNode` twice
   (`purpose="initial"`, `purpose="final"`) both with the **same**
   `smoothing={"method":"additive","alpha":0.5,"rationale":"..."}`;
   assert `initial_iv == pytest.approx(final_iv, rel=1e-6)`.
2. `test_initial_iv_zero_cell_warns_when_unsmoothed` — same setup, no
   smoothing on initial → assert a `ZERO_CELL_INITIAL_IV_DEFLATED`
   warning present in the WOE evidence `warnings`.

**GREEN**:
- In `features.py:154-182`, factor the zero-cell smoothing block so
  both `purpose=="final"` and `purpose=="initial"` share the
  smoothing-apply logic.
- In the `initial` + no-smoothing branch, change the silent
  `woe=0, iv_comp=0` to also append the
  `ZERO_CELL_INITIAL_IV_DEFLATED` warning (with `variable` and
  `bin_id`).

**VERIFY**: `pytest tests/test_woe.py -k "zero_cell or initial_iv"`.

**GATE**: `test_final_woe_zero_cell_block_fails_without_smoothing`
still passes — final still blocks without smoothing.

---

## Phase B2 — Non-monotonic WOE enforcement gate + champion readiness gate (launch-blocker #3)

**Decision baked in**:
- New `enforce_monotonic_woe` param on `calculate_woe_iv`, **default
  `False`** (additive; no behaviour change for existing run evidence).
- When `True` and `purpose="final"`, non-monotonic variables move to
  the bin definition's `rejected` list with
  `failure_reason="non_monotonic_woe"`.
- **Champion readiness gate** (B2-adjunct, same phase): champion
  readiness blocks when any **selected** final-WOE variable is
  non-monotonic AND not re-binned to monotonic by a covering manual
  override. This closes the launch-blocker by gating even though the
  node default stays `False`. Mirrors B5's pattern and
  `_variable_needs_review`'s per-bin coverage logic (B4).

**Files**:
- `cardre/nodes/build/features.py` (param + rejection).
- `cardre/engine/binning/definition.py` (accept rejected vars from
  WOE node, mirroring `auto_binning_fit.py:310-372`).
- `cardre/readiness/check.py` (champion gate).
- `cardre/readiness/limitation_codes.py` (new code
  `NON_MONOTONIC_WOE_CHAMPION`).
- `tests/test_woe.py`, `tests/test_readiness_consistency.py`,
  `tests/test_readiness_package.py`.

**RED**:
1. `test_non_monotonic_variable_rejected_when_enforced` — bin def
   with one variable whose WOE across bins is `[+0.5, -0.3, +0.4]`
   (non-monotonic); run `CalculateWoeIvNode` with
   `enforce_monotonic_woe=True, purpose="final"`; assert the output
   WOE evidence marks the variable `status="REJECTED"`,
   `failure_reason` contains `non_monotonic_woe`, and the variable is
   in the bin definition's `rejected` list (not `variables`).
2. `test_non_monotonic_passthrough_when_not_enforced` — same input,
   `enforce_monotonic_woe=False` (default) → variable stays in
   `variables`, only the existing `non_monotonic` warning is set.
3. `test_champion_readiness_blocked_on_non_monotonic_woe` — build a
   readiness scenario in `report_mode="champion"` where a selected
   final-WOE variable is non-monotonic and no covering override
   re-bins it; assert a `NON_MONOTONIC_WOE_CHAMPION` blocker present.
4. `test_champion_readiness_passes_when_non_monotonic_re_binned` —
   same, but with a manual override that merges bins so the resulting
   WOE is monotonic; assert no `NON_MONOTONIC_WOE_CHAMPION` blocker.

**GREEN**:
- (a) Add `ParameterDefinition("enforce_monotonic_woe", kind="boolean",
  default=False)` to the `calculate_woe_iv` schema.
- (b) In `CalculateWoeIvNode.run`, after computing WOE per variable:
  if the param is `True`, `purpose=="final"`, and
  `monotonicity_status(woe_by_bin) == MonotonicStatus.non_monotonic`,
  move the variable to a `rejected` list in the emitted evidence with
  `status="REJECTED"`, `failure_reason="non_monotonic_woe"`. Mirror
  the `auto_binning_fit.py:310-372` rejection-block pattern so
  downstream nodes (manual binning, WOE transform) skip rejected vars.
- (c) Champion readiness gate: in `check.py`, after the existing
  `final-woe-iv` evidence check (`:152-165`), when
  `report_mode == "champion"`:
  - Read the `cardre.woe_iv_evidence.v1` artifact.
  - Resolve the selection-definition for selected variable names.
  - Resolve the manual-binning overrides.
  - For each selected variable whose WOE across bins is
    non-monotonic, check whether a covering override re-bins it to
    monotonic (reuse `manual_binning_service._variable_needs_review`
    / `monotonicity_status` semantics; after B4 lands, the per-bin
    coverage check applies).
  - If any selected variable stays non-monotonic and uncovered,
    append a `NON_MONOTONIC_WOE_CHAMPION` blocker.
- (d) Add `NON_MONOTONIC_WOE_CHAMPION` to
  `readiness/limitation_codes.py` as a blocker code.

**VERIFY**: `pytest tests/test_woe.py tests/test_readiness_consistency.py tests/test_readiness_package.py -k "monotonic or non_monotonic or champion"`.

**GATE**: default-`False` means all existing tests pass unchanged. The
champion gate is **champion-mode only** — branch-mode readiness is
unchanged. Coordinate with B5 (OOT gate) so both use the same
champion-mode branch pattern in `check.py`.

---

## Phase B3 — Pure-bin diagnostic

**Gap**: #20 (pure-good/pure-bad bins silently inflate IV).
**Decision baked in**: diagnostic only, no enforcement.
**Files**: `cardre/engine/binning/diagnostics.py`; `cardre/nodes/build/features.py`; `tests/test_woe.py`.

**RED**: `test_pure_bin_diagnostic_emitted`.
- A variable where one bin holds `good_count == total_good` (all
  goods). Run `CalculateWoeIvNode`.
- Assert a `PURE_BIN` diagnostic present with `variable`, `bin_id`,
  and `direction="all_good"` (or `"all_bad"`).

**GREEN**:
- Add `check_pure_bins(bins, variable)` to `diagnostics.py` returning
  `BinningDiagnostic(code="PURE_BIN", severity="warning",
  requires_acknowledgement=True, details={"direction": ...})`.
- Call it from `CalculateWoeIvNode.run` per variable after counts are
  computed.
- Do **not** reject — `requires_acknowledgement=True` flows into the
  manual-binning gate.

**VERIFY**: `pytest tests/test_woe.py -k pure_bin`.

**GATE**: pure-bin variables no longer silently inflate IV without a
visible warning.

---

## Phase B4 — Per-bin review coverage in `_variable_needs_review`

**Gap**: #14 (reason-code coverage is binary per variable, not per bin).
**Decision baked in**: a `sparse_bin`/`zero_cell` override must cover
the specific flagged bin (by `source_bin_ids`) to count as
acknowledgement, not just the variable.
**Files**: `cardre/services/manual_binning_service.py:649-691`; `cardre/readiness/manual_binning.py:42-60`; `tests/test_manual_binning_phase3.py` (or `tests/test_manual_binning_gate.py`).

**RED**: `test_multiple_sparse_bins_require_per_bin_coverage`.
- Variable with 3 sparse bins; override list has 1 `sparse_bin`-coded
  override naming only bin #1 (in `source_bin_ids`).
- Assert `review_required == True` (bins #2, #3 uncovered).
- Add a second override covering bins #2 and #3 → assert
  `review_required == False`.

**GREEN**:
- Change `_variable_needs_review` to build the set of *uncovered
  flagged bin ids*: for each flagged bin, look for an override whose
  `source_bin_ids` contains that bin_id and whose `reason_code`
  matches the flag.
- `review_required = bool(uncovered)`.
- Mirror the same per-bin check in `compute_manual_binning_blockers`
  (`manual_binning.py`) so the editor gate and the readiness gate are
  consistent.

**VERIFY**: `pytest tests/test_manual_binning_gate.py tests/test_manual_binning_phase3.py -k "review or blocker"`.

**GATE**: existing single-sparse-bin tests still pass (one override
covers one bin). B2's champion gate uses this per-bin coverage once B4
lands — ensure B2's gate test for "re-binned to monotonic" still
passes after B4.

---

## Phase B5 — Champion readiness requires OOT (launch-blocker #19)

**Decision baked in**: `require_oot=True` in champion mode (default);
warn-only in branch mode (default). Configurable via a param on
`check_report_readiness`.
**Files**: `cardre/reporting/evidence_contract.py`; `cardre/readiness/check.py`; `cardre/readiness/limitation_codes.py`; `tests/test_readiness_consistency.py`, `tests/test_readiness_package.py`.

**RED**:
1. `test_champion_readiness_blocked_without_oot` — readiness scenario
   in `report_mode="champion"` with no OOT artifact role present;
   assert a blocker with code `NO_OOT_SAMPLE_CHAMPION` (new) in
   `blockers`.
2. `test_branch_readiness_warns_without_oot` — same,
   `report_mode="branch"` → `NO_OOT_SAMPLE` is a *warning*, not a
   blocker (current behaviour preserved).

**GREEN**:
- In `check.py:230-235`, branch on `report_mode == "champion"`: emit
  `LimitationCode.NO_OOT_SAMPLE_CHAMPION` as a blocker; else keep the
  current `NO_OOT_SAMPLE` warning.
- Add `NO_OOT_SAMPLE_CHAMPION` to `readiness/limitation_codes.py` as
  a blocker code.
- Optionally add `require_oot_branch: bool=False` param for users who
  want it in branch mode too.

**VERIFY**: `pytest tests/test_readiness_consistency.py tests/test_readiness_package.py -k "oot or champion"`.

**GATE**: branch-mode readiness with OOT still passes; champion-mode
without OOT now blocks. Coordinate the champion-mode branch pattern
with B2 (both branch on `report_mode == "champion"` in `check.py`).

---

## Phase B6 — Spearman without scipy hard-fails at param validation

**Gap**: #17 (silent pass-through when scipy missing).
**Decision baked in**: hard-fail at `validate_params`, not silent
pass-through at runtime.
**Files**: `cardre/nodes/build/clustering.py:153-216`; `tests/test_scorecard_selection.py`.

**RED**: `test_spearman_unavailable_scipy_hard_fails_validation`.
- Monkeypatch `similarity_metric="spearman"`; simulate
  scipy-unavailable by stubbing `import scipy` to raise inside
  `_tie_aware_rank`'s lazy import.
- Call
  `VariableClusteringNode().validate_params({"method":"correlation_threshold","similarity_metric":"spearman"})`
  → assert an error string mentions scipy. Currently returns no
  errors (silent pass-through at runtime).

**GREEN**:
- In `validate_params`, if `similarity_metric == "spearman"`, try
  `import scipy.stats` eagerly; on `ImportError` append
  `"spearman requires scipy; install cardre[stats] or similar"`.
- Do **not** change runtime `_tie_aware_rank` (still lazy import).

**VERIFY**: `pytest tests/test_scorecard_selection.py -k "spearman or scipy"`.

**GATE**: pearson clustering unaffected when scipy is missing.

---

# Global gate before raising the PR

After all 15 phases are green:

1. **Lint** (use the bootstrapped dev venv):
   ```bash
   # One-time bootstrap per clone:
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -e ".[sidecar,dev,test]"

   # Before pushing:
   . .venv/bin/activate
   ruff check --fix
   ```
2. **Full suite**:
   ```bash
   python3 -m pytest tests/ -q
   ```
   Must include golden-R (`tests/golden_scorecard/`) and the
   determinism tests (`test_reporting.py::TestDeterminism`,
   `test_woe.py::test_deterministic_output`).
3. **Integration check**: the scorecard-pathway integration test
   (`test_scorecard_model.py::Phase2AEndToEndTests`) must still pass
   end-to-end. A3 (OOT default → `fail`) and A4 (open extremes) must
   not break it. If the integration test relied on the default
   `warn`, update it to an explicit `warn` (or to the new `fail`
   default) and confirm OOT rows still bin (they will, post-A4).
4. **Push + CI gate**:
   ```bash
   scripts/pr-gate.sh
   ```
   Polls CI to green. Only then is the PR ready for human review.

# Launch-blocker coverage

| # | Launch-blocker | Phase | In this plan? |
|---|---|---|---|
| #6 | Categorical "Other" frequency sort | A1 | Yes |
| #3 | Non-monotonic WOE enforcement | B2 | Yes (capability + champion gate; node default stays off) |
| #2 | Zero-cell initial↔final consistency | B1 | Yes |
| #12 | PSI empty-bin silent-zero | A2 | Yes |
| #15 | OOT-unmatched default `fail` | A3 | Yes |
| #19 | OOT-required-for-champion | B5 | Yes |
| #16 | Leakage scan | — | **Out** (Tier C, design-first) |
| #13 | Characteristic report + gains | — | **Out** (Tier C, design-first) |

This plan closes **6 of the 8** launch-blockers. The remaining two
are explicitly out of scope and need ADRs before TDD.
