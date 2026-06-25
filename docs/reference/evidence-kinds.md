# Evidence Kinds

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

## Evidence Kinds

The `ArtifactEvidenceReader` (`cardre/evidence/`) supports the following evidence kinds:

- `SCHEMA_VARIABLE_CLUSTERING_EVIDENCE`
- Additional kinds defined in `cardre/evidence/` module

## Resolution Rules

- Evidence is resolved by canonical step ID, not by step instance ID.
- Legacy aliases are resolved via `LEGACY_CANONICAL_ALIASES`.
- The collector uses `resolve_canonical_step_id()` to map legacy IDs to current canonical forms.
- `canonical_alias_candidates()` returns both current and legacy IDs for flexible matching.
