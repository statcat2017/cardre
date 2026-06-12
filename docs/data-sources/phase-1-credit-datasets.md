# Phase 1 Credit Scoring Datasets

Phase 1 needs public, licensed datasets that exercise the engine/storage layer
without introducing licensing friction or authentication requirements.

Raw datasets should not be committed by default. Store local downloads under
`input/credit/`, which is ignored by git. Dataset metadata and expected usage are
tracked here so tests and examples can be reproducible.

## Recommended Datasets

### 1. UCI Statlog German Credit Data

- Purpose: primary small smoke dataset for deterministic engine/storage tests.
- Source: https://archive.ics.uci.edu/dataset/144/statlog+german+credit+data
- DOI: https://doi.org/10.24432/C5NC77
- License: Creative Commons Attribution 4.0 International (CC BY 4.0).
- Rows: 1,000.
- Features: 20.
- Target: credit risk class, encoded as `1 = Good`, `2 = Bad` in the original UCI files.
- Files: `german.data`, `german.data-numeric`, `german.doc`.
- Strengths: tiny, classic credit-risk dataset, mixed categorical/integer variables, clear binary target, fast enough for repeat tests.
- Limitations: no missing values, small sample size, no natural observation/performance window fields.

Phase 1 use:

- CSV/text import smoke test.
- Canonical Parquet conversion.
- Physical/logical artifact hashing.
- Train/test/OOT split role tagging.
- Deterministic replay and staleness tests.
- Basic target validation using `1/2` to `good/bad` mapping.

### 2. UCI Default of Credit Card Clients

- Purpose: medium-size dataset for richer performance and correlation behaviour.
- Source: https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients
- DOI: https://doi.org/10.24432/C55S3H
- License: Creative Commons Attribution 4.0 International (CC BY 4.0).
- Rows: 30,000.
- Features: 23 plus ID and target in the source file.
- Target: `default payment next month`, encoded as `1 = default`, `0 = non-default`.
- Source file: `default of credit card clients.xls`.
- Strengths: larger than German Credit, real credit-card default target, repeated monthly payment/balance fields useful for correlation and clustering tests.
- Limitations: Excel source requires either an `.xls` import path or a one-time conversion fixture; no missing values; demographic variables require care in governance examples.

Phase 1 use:

- Medium-size import/conversion test.
- Profiling and schema metadata test.
- Logical hash stability on larger tabular artifacts.
- Split role tagging with enough rows for train/test/OOT.
- Later variable clustering and performance-envelope checks.

## Later Candidate

### HMEQ / Home Equity Credit Data

- Purpose: later scorecard-realistic fixture with missing values and common credit variables.
- Status: do not bake into Phase 1 until source and license are confirmed.
- Strengths: missing values, debt/income/delinquency-style predictors, home-equity lending context.
- Risk: copies online vary and licensing is less immediately clear than UCI.

## Synthetic Fixture Needed

The two UCI datasets do not cover all scorecard edge cases. Add a tiny synthetic
fixture later for deterministic correctness tests with:

- missing values
- special codes such as `999`, `-1`, and `unknown`
- unseen categorical values for scoring fallback tests
- high-cardinality categorical field
- deterministic row IDs
- explicit train/test/OOT split column
- known expected target distribution

This synthetic fixture should be small enough to commit under `tests/fixtures/`
and should complement, not replace, the public datasets.

## Local Storage Convention

```text
input/credit/
  uci-german-credit/
    raw/
    prepared/
  uci-default-credit-card-clients/
    raw/
    prepared/
```

`raw/` contains downloaded source files. `prepared/` contains local conversion
outputs such as CSV or Parquet created by scripts. Both are ignored by git.

## Phase 1 Dataset Acceptance Criteria

- Dataset source URL, DOI, license, target mapping, and row/feature counts are documented.
- Raw download can be stored outside git under `input/credit/`.
- Import creates a canonical Parquet artifact.
- Re-import of the same source produces the same logical hash.
- Split step produces immutable `train`, `test`, and `oot` artifacts.
- Split parameters are recorded and changing them makes downstream artifacts stale.
- Dataset-specific target mappings are explicit and auditable.
