# PR 3 — Canonical score column, score-direction, and `points_to_double_odds`

**Sprint:** `docs/plans/legacy-compat-collapse.md`
**Depends on:** PR 2
**Risk:** Medium
**Authority:** ADR 0003; user decisions (`points_to_double_odds`; unify on `score_direction` string).

## Goal

One canonical score column (`score`); one canonical score-direction representation (`score_direction` string enum) across scorecard AND model artifacts; one canonical score-scaling param/artifact name (`points_to_double_odds`).

## Files to read first (do not edit)

- `cardre/modeling/adapters.py` — `cardre_scaled_score` writes (:196-197, 301-302); `higher_score_is_lower_risk` bool reads (:139, 296).
- `cardre/nodes/build/models.py` — `ScoreScalingNode`: param `points_to_double_odds` (:357); `validate_params` (:384-389); `run` reads `points_to_double_odds` (:427); writes `"points_to_double_odds": pdo` (:466) and `"higher_score_is_lower_risk": higher_is_lower_risk` (:469); `BuildSummaryReportNode` writes `"points_to_double_odds": scorecard.pdo` (:558) and `"higher_score_is_lower_risk"` (:560).
- `cardre/nodes/build/freeze.py` — :124 writes `"higher_score_is_lower_risk"`.
- `cardre/nodes/build/scoring_export.py` — many references to `higher_score_is_lower_risk` (writes at :72, :163, :318, :339, :514, :535; reads at :140, :372) and `points_to_double_odds` (writes at :70, :144, :162, :321, :338, :517, :534).
- `cardre/_evidence/models/model.py` — `ScoreScaling` dataclass (:133-176): field `pdo` (:137), `from_json` dual-accept `pdo`/`points_to_double_odds` (:152), `_raw` (:144), `higher_score_is_lower_risk` property dual-accept (:178-184).
- `cardre/reporting/schema.py` — `ScoreScalingInfo.pdo` (:201), `score_direction` (:204).
- `cardre/reporting/sections/score_scaling.py` — `pdo=scaling.pdo` (:33).
- `tests/fixtures/golden_report_bundle.json` — `pdo` (:1813), `higher_score_is_lower_risk` occurrences.
- `tests/test_scoring_export_parity.py:122` — drops `["score", "cardre_scaled_score", ...]`.

## Code instructions

### Step 1 — Remove the duplicate `cardre_scaled_score` column

In `cardre/modeling/adapters.py`:

`apply_logistic` (around line 196):
```python
# DELETE line 196:
#     add_exprs.append(score_expr.alias("cardre_scaled_score"))
# CHANGE line 197:
#     output_cols.extend(["score", "cardre_scaled_score"])
# TO:
output_cols.append("score")
```

`apply_sklearn_estimator` (around line 301):
```python
# DELETE line 301:
#     add_exprs.append(score_series.alias("cardre_scaled_score"))
# CHANGE line 302:
#     output_cols.extend(["score", "cardre_scaled_score"])
# TO:
output_cols.append("score")
```

### Step 2 — Unify score direction to `score_direction` (string) in scorecard writers

The scorecard artifact (`cardre.score_scaling.v1`) currently emits `higher_score_is_lower_risk` (bool). Change every scorecard writer to emit `score_direction` (string: `"higher_is_lower_risk"` or `"higher_is_better"`).

`cardre/nodes/build/models.py` (`ScoreScalingNode.run`):
- Line 428: keep `higher_is_lower_risk = bool(params.get("higher_score_is_lower_risk", True))` — this is the node's UI param (bool); it stays.
- Line 469: replace
  ```python
  "higher_score_is_lower_risk": higher_is_lower_risk,
  ```
  with
  ```python
  "score_direction": "higher_is_lower_risk" if higher_is_lower_risk else "higher_is_better",
  ```
- Line 558 (`BuildSummaryReportNode`): replace `"points_to_double_odds": scorecard.pdo,` — note: `scorecard` is a `ScoreScaling` evidence reader instance; after PR3 step 4 it exposes `.points_to_double_odds`. Change to `"points_to_double_odds": scorecard.points_to_double_odds,`.
- Line 560: replace `"higher_score_is_lower_risk": scorecard.higher_score_is_lower_risk,` with `"score_direction": scorecard.score_direction,`.

`cardre/nodes/build/freeze.py`:
- Line 124: replace `"higher_score_is_lower_risk": higher_is_lower_risk,` with `"score_direction": "higher_is_lower_risk" if higher_is_lower_risk else "higher_is_better",`. (Read the surrounding context to confirm `higher_is_lower_risk` is a local bool.)

`cardre/nodes/build/scoring_export.py` — replace every `"higher_score_is_lower_risk": <bool expr>,` write with `"score_direction": "higher_is_lower_risk" if <bool expr> else "higher_is_better",`:
- Line 72
- Line 163
- Line 318
- Line 339
- Line 514
- Line 535

Replace every read `scorecard_dict.get("higher_score_is_lower_risk", True)` (lines 140, 372) with:
```python
scorecard_dict.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk"
```

`cardre/modeling/adapters.py` — replace reads at lines 139 and 296:
```python
# was: direction = -1.0 if scorecard_parsed.get("higher_score_is_lower_risk", True) else 1.0
direction = -1.0 if scorecard_parsed.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk" else 1.0
```

### Step 3 — Canonicalize `ScoreScaling` reader

In `cardre/_evidence/models/model.py`, the `ScoreScaling` dataclass (lines 133-176):

- Line 137: rename field `pdo: int = 20` → `points_to_double_odds: int = 20`.
- Line 140: `score_direction: str = "higher_is_better"` — change default to `"higher_is_lower_risk"` (canonical default; the scorecard writer defaults `higher_is_lower_risk=True`).
- Line 152: replace
  ```python
  pdo = data.get("pdo", data.get("points_to_double_odds", 20))
  ```
  with
  ```python
  points_to_double_odds = data.get("points_to_double_odds", 20)
  ```
  (Read only `points_to_double_odds`. Do NOT fall back to `pdo`.)
- Line 158: `factor = float(pdo) / math.log(2)` → `factor = float(points_to_double_odds) / math.log(2)`.
- Line 163: `pdo=pdo,` → `points_to_double_odds=points_to_double_odds,`.
- Line 166-170: set `score_direction = data.get("score_direction", "higher_is_lower_risk")`. Remove the `higher_score_is_lower_risk` bool read.
- Lines 178-184: replace the `higher_score_is_lower_risk` property:
  ```python
  @property
  def higher_score_is_lower_risk(self) -> bool:
      return self.score_direction == "higher_is_lower_risk"
  ```
  (This keeps a convenience bool accessor for callers that want it, but it's derived from the canonical `score_direction`, not from `_raw`.)

Note: the `_raw` field and `_raw`-backed properties (`base_odds_text`, `intercept`, `has_explicit_intercept`, `base_points`, `target_column`, `attributes`) are removed in **PR 4**, not here. Leave them for PR 4 to keep this PR focused.

### Step 4 — Canonicalize `points_to_double_odds` in report bundle

`cardre/reporting/schema.py`:
- Line 201: rename `pdo: int = 20` → `points_to_double_odds: int = 20`.

`cardre/reporting/sections/score_scaling.py`:
- Line 33: `pdo=scaling.pdo` → `points_to_double_odds=scaling.points_to_double_odds`.

### Step 5 — Update golden fixture

`tests/fixtures/golden_report_bundle.json`:
- Line 1813: `"pdo": 20` → `"points_to_double_odds": 20`.
- Find every `"higher_score_is_lower_risk": true` (or `false`) in the scorecard payload → replace with `"score_direction": "higher_is_lower_risk"` (or `"higher_is_better"`). Search:
  ```bash
  rg -n "higher_score_is_lower_risk" tests/fixtures/golden_report_bundle.json
  ```

### Step 6 — Update score-scaling tests

Search and update:
```bash
rg -n "pdo|higher_score_is_lower_risk|cardre_scaled_score" tests/
```

Update each assertion to the canonical name:
- `tests/test_score_scaling_known_input.py`
- `tests/test_score_scaling_errors.py`
- `tests/test_freeze_scorecard_bundle.py`
- `tests/test_build_summary_node.py` / `tests/test_build_summary_report.py`
- `tests/test_reporting.py`
- `tests/test_scoring_export_parity.py:122`: change the drop list from `["score", "cardre_scaled_score", "predicted_bad_probability", ...]` to `["score", "predicted_bad_probability", ...]`.

For tests that assert `scorecard.pdo == 20` → `scorecard.points_to_double_odds == 20`.
For tests that assert `scorecard.higher_score_is_lower_risk is True` → keep (the convenience property still works) OR assert `scorecard.score_direction == "higher_is_lower_risk"`. Prefer the canonical `score_direction` assertion.

### Step 7 — Add guard tests

Add to `tests/test_canonical_contract.py`:
```python
def test_score_scaling_rejects_pdo_key():
    from cardre._evidence.models.model import ScoreScaling
    s = ScoreScaling.from_json({"pdo": 20, "base_score": 600})
    # pdo is not read; points_to_double_odds stays at default
    assert s.points_to_double_odds == 20  # default — pdo was ignored

def test_scored_dataset_single_score_column():
    # Build a tiny scored dataset via apply_logistic (or apply_sklearn_estimator)
    # and assert "score" in columns, "cardre_scaled_score" not in columns.
    # Use an existing fixture/test helper that produces a scored dataframe.
    ...
```

## Verification

```bash
. .venv/bin/activate
rg -n "cardre_scaled_score" cardre/ tests/
# Zero matches in cardre/ and tests/ (except maybe historical docs — PR6 handles those).
rg -n "\"pdo\"" cardre/ tests/
# Zero matches in non-doc files.
rg -n "higher_score_is_lower_risk" cardre/
# Only the node param definition (UI form, models.py:365/428) and the ScoreScaling convenience
# property may remain. All artifact writers/readers use score_direction.
ruff check --fix
pytest tests/test_score_scaling_known_input.py tests/test_score_scaling_errors.py \
       tests/test_freeze_scorecard_bundle.py tests/test_scoring_export_parity.py \
       tests/test_build_summary_node.py tests/test_reporting.py \
       tests/test_canonical_contract.py -q
make preflight
scripts/pr-gate.sh
```

## Definition of done

- [ ] `cardre_scaled_score` column not written anywhere; `score` is the sole score column.
- [ ] Scorecard artifact emits `score_direction` (string), not `higher_score_is_lower_risk` (bool).
- [ ] `ScoreScaling` reader reads only `points_to_double_odds` (not `pdo`).
- [ ] `ScoreScalingInfo` field is `points_to_double_odds` (not `pdo`).
- [ ] Golden fixture updated.
- [ ] Guard tests added.
- [ ] `ruff check` clean; `make preflight` green; PR gate green.

## Failure mode

- **Test asserts `scorecard.pdo`:** the reader field is now `points_to_double_odds`. Update the test.
- **Score-direction mismatch in apply:** the apply adapter read `score_direction` but the scorecard fixture still has `higher_score_is_lower_risk`. Regenerate the fixture or update the test setup to emit `score_direction`.
- **`freeze.py` test fails:** the frozen bundle now carries `score_direction`; the test asserts the old bool. Update the assertion.