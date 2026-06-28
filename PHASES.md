# Phase Plan

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Tests | Write TDD tests for dataset-quality profiling |
| 2 | Core | Implement quality warnings in ProfileDatasetNode |
| 3 | Evidence | Update evidence models and summaries to surface quality warnings |

## Phase 1 — Tests

Write TDD red tests in `tests/test_dataset_quality.py` for dataset-quality profiling.

Test targets:
1. Clean dataset produces no quality warnings
2. ID/date/leakage-like column names produce suspect warnings
3. Constant/dominant/high-cardinality/null-heavy columns produce statistical warnings
4. String-coded numeric and date-like strings produce type warnings
5. Duplicate rows and duplicate column names produce warnings
6. Profile summary exposes warning count and warning messages

Use `tests/helpers/__init__.py` for store/artifact helpers. Do NOT implement the production code yet — just write failing tests that assert the expected warning codes and fields.

## Phase 2 — Core Implementation

Implement `_quality_warnings` in `ProfileDatasetNode` (`cardre/nodes/prep.py`) that:
- Scans column names for ID/date/leakage patterns
- Scans column values for constants, near-unique, dominant values, high cardinality, null-heavy, string-coded numeric, date-like strings
- Scans dataset for duplicate rows and blank/duplicate column names
- Returns `(quality_warnings: list[JsonDict], recommended_exclude_columns: list[str])`
- Adds `quality_warnings`, `warnings`, and `recommended_exclude_columns` to the profile report payload

## Phase 3 — Evidence & Summaries

Update `cardre/_evidence/models.py` `ProfileSummary` to parse `quality_warnings`.
Update `cardre/_evidence/summaries.py` `_summarise_profile` to include `warning_count` and return warning messages in the warning list.
