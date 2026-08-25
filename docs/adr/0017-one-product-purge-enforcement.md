# ADR 0017 — One-product purge: enforcement of ADR 0015

## Status

Accepted.

## Decision

Cardre is a single, opinionated, production-facing logistic scorecard engine.
This ADR records the completed one-product purge as the enforcement of
[ADR 0015](0015-no-compatibility-policy.md), and it supersedes two earlier ADRs
whose concerns no longer describe the current product:

- **Supersedes [ADR 0016](0016-estimator-load-verification-is-mandatory.md)**
  because estimator-binary load verification is no longer a current product
  concern. The serialized joblib estimator and its load-time hash verification
  were removed with the estimator reference; the model artifact is now a single
  strict JSON logistic payload with no binary twin and no load-time trust path.
- **Supersedes [ADR 0013](0013-evidence-locator-implementation.md)** because
  branch evidence resolution was removed with branch execution. Evidence
  resolution is now a single full-plan pathway; there is no branch fallback
  chain to locate.

The final product shape, and the consequences of the purge, are recorded below.

## Context

Cardre accumulated deferred product surface, compatibility handling for
pre-release formats, governance functionality, alternate methodology
selectors, and duplicate data representations. ADR 0015 established that only
the current persisted shape is supported — no aliases, fallback readers,
compatibility shims, or migrations for previous development formats.

The purge removed that surface so the product reduces to one canonical
opinionated pathway:

```text
Parquet input
  -> fine classing
  -> WOE/IV
  -> correlation-threshold clustering
  -> variable selection
  -> manual binning
  -> WOE transform
  -> standard logistic regression
  -> score scaling
  -> validation and export
```

## The final Parquet boundary

The import boundary accepts **Parquet only**. The import node retains
`source_path` and `max_rows`; all format, encoding, delimiter, null-value, and
dtype configuration was removed. The scorecard table export publishes a single
tabular Parquet SCORE_TABLE artifact; the duplicate JSON publication was
removed.

## The logistic artifact

The persisted model artifact (`cardre.model_artifact.v1`) is a single strict
logistic scorecard payload: a WOE feature contract, an intercept, per-feature
coefficients, and training provenance. There is no model-family dispatch, no
estimator reference, no runtime calibration block, and no generic
interpretability or tuning metadata. The parser is strict: it rejects unknown
top-level fields generically and requires the complete current payload rather
than reconstructing omitted fields.

## No governance

Challenger governance and branch execution were removed from the launch
product. There is no `CARDRE_GOVERNANCE` flag, no branch scope, no champion or
comparison, and no branch evidence resolution. Manual-binning review remains
available as a normal plans-scoped workflow through the ungated plans API.

## Consequences

- **Easier:** the codebase and documentation describe one flat, opinionated
  production engine with no deferred tier, launch-mode flag, alternate
  methodology selector, or compatibility fallback.
- **Easier:** a single strict parser per persisted concept rejects unknown
  fields and missing current fields, so persisted-shape drift fails closed.
- **Easier:** the import boundary and SCORE_TABLE export are Parquet-only,
  removing a whole class of format and representation handling.
- **Easier:** governance and branch execution are absent, simplifying run
  scope, reporting, evidence resolution, and the SQLite schema.
- **Harder:** development projects whose persisted schemas predate the purge
  must be recreated; no migration chain is added (ADR 0015).
- **Harder:** any future reintroduction of estimator binaries, branch
  governance, alternate model families, or non-Parquet import must reopen this
  ADR and record a compatibility or migration strategy.
