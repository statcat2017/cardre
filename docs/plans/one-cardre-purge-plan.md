# One Cardre Purge Plan

## Status

Prepared for implementation.

## Objective

Reduce Cardre to one opinionated, production-facing scorecard engine:

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

The cleanup removes deferred product surface, compatibility handling for
pre-release formats, governance functionality, alternate methodology
selectors, and duplicate data representations.

This plan implements [ADR 0015](../adr/0015-no-compatibility-policy.md):
Cardre supports one current persisted shape only. It does not preserve
development-era formats, aliases, fallback readers, compatibility shims,
migrations, or historical identifier handling.

## Locked Decisions

- Logistic regression is standard logit only.
- The import boundary accepts Parquet only.
- Import retains `source_path` and `max_rows`; all format, encoding, delimiter,
  null-value, and dtype configuration is removed.
- Manual-binning preview, edit, and review endpoints move from the governance
  router to an ungated plans-scoped router.
- The manual-binning review workflow and its persistence remain current
  functionality.
- The canonical pathway remains the source of truth for production node
  registration.
- Development projects with incompatible schemas are recreated; no migration
  chain is added.

## Verified Baseline

The audit findings were checked against the repository before this plan was
written.

- `cardre/bootstrap/node_catalogue.py` registers exactly 21 deferred nodes.
- The launch registry contains 31 nodes.
- `_CANONICAL_SCORECARD_STEPS` contains 30 distinct production node types.
- `NoopNode` is the only launch-registered node absent from the canonical
  pathway.
- `DummyFitNode` is implemented and re-exported but not registered.
- `CARDRE_LAUNCH_MODE` and `CARDRE_GOVERNANCE` are active configuration flags.
- Estimator serialization and physical-hash fallback are used by deferred
  classifier and calibration infrastructure.
- `ModelArtifactV1` is a generic multi-family model schema.
- Governance tables are included unconditionally in `ALL_TABLES_SQL`.
- `ScorecardTableExportNode` publishes both table and JSON SCORE_TABLE output.
- `scripts/v2-phase-check.sh` references 16 test files that no longer exist.
- `make test-launch-core` references three test files that no longer exist.
- Ruff contains an ignore for the nonexistent `cardre/_evidence/` package.

## Execution Rules

Each batch is implemented on its own branch and must remain independently
reviewable.

After each batch:

```bash
. .venv/bin/activate
ruff check --fix
make preflight
scripts/pr-gate.sh
```

`scripts/pr-gate.sh` is the only permitted PR and CI interface. Do not request
review until it reports `CI GREEN`. If CI fails, read the downloaded logs under
`.opencode/pr-gate-logs/`, fix the failure, push again, and rerun the gate.

Merge each green batch before starting the next batch. This avoids prolonged
conflicts in shared registry, schema, API, documentation, and fixture files.

## Batch 1: Remove Deferred Product Surface

### Purpose

Delete the future-product layer and flatten the node catalogue.

### Production changes

- Map each deferred class to its defining module, then delete modules whose
  contents are exclusively deferred functionality:
  - boosting classifiers
  - deferred model families
  - calibration
  - fairness and proxy-risk reporting
  - explainability
  - reject inference
  - threshold optimization
  - deferred feature selection and resampling
  - hyperparameter tuning
- Delete `_classifier_base.py`, `_classifier_result.py`,
  `_training_utils.py`, and `_model_artifacts.py`.
- Delete `NoopNode` and `DummyFitNode`, including production re-exports.
- Remove all deferred-node imports from `cardre/nodes/__init__.py` and related
  package initializers.
- Remove `NodeTier`, deferred node lists, tier resolution, deferred listing,
  launch-mode availability branches, and deferred disabled reasons from
  `bootstrap/node_catalogue.py`.
- Remove `launch_mode` from `Settings` and remove `_deferred` from node
  contracts.
- Remove `NodeNotAvailableForLaunch` and
  `PLAN_CONTAINS_UNAVAILABLE_NODES` error codes.
- Remove launch/deferred counts and tier fields from health and API schemas.
- Remove `model-limitations` from `REQUIRED_STEPS_COLLECTOR`.
- Keep optional-dependency probing temporarily only for OptBinning; Batch 4
  removes the remaining optional-dependency machinery.

### Compatibility cleanup

- Remove the `physical_hash` argument from the `InputCollection.artifact_ref`
  protocol and implementation.
- Remove the physical-hash fallback from test harnesses and test doubles.
- Delete the legacy UUID estimator-resolution test and estimator fallback tests.

### Evidence cleanup

Remove deferred-only evidence kinds, profiles, parsers, schemas, and models for:

- reject population and reject inference
- threshold optimization
- calibration reports
- feature selection
- resampling
- hyperparameter tuning
- explainability
- fairness
- proxy risk

Keep `CALIBRATION_DIAGNOSTICS`, because it is emitted by the canonical,
launch-tier diagnostics node. Remove `COMPARISON_ARTIFACT` in Batch 3 with
governance.

### Tests

Delete tests whose only purpose is deferred functionality or estimator-binary
support, including the deferred-node, registry-tier, classifier-context,
calibration, explainability, feature-selection, resampling, estimator-reference,
classifier-ordering, sklearn-apply, and apply-calibration suites.

Add the registry invariant test described in the final guard section. It must
pass at the end of this batch: the flat production registry must contain the
30 distinct node types required by `_CANONICAL_SCORECARD_STEPS`.

### Documentation

Rewrite the node catalogue and feature-status documentation to describe one
flat production catalogue. Remove deferred and launch-tier terminology from
active documentation after the corresponding code is gone.

## Batch 2: Logistic Model Artifact and Apply Path

### Purpose

Replace the generic model-family contract with one strict logistic scorecard
artifact and one direct application path.

### Model schema

Replace the generic `ModelArtifactV1` contract with a logistic-specific model
artifact. The persisted payload must contain only the current model shape.

Remove:

- model-family dispatch
- estimator references and binary estimator metadata
- calibration artifacts and runtime calibration blocks
- generic interpretability metadata
- tuning status and other deferred-model fields
- the explicit blacklist of historical top-level keys

The parser must reject unknown top-level fields generically. It must require
the complete current payload rather than reconstructing omitted fields.

Update all consumers, including evidence parsers, score scaling, freezing,
scoring exports, apply-model, golden fixtures, and report fixtures.

### Apply model

Reduce `ApplyModelNode` to the canonical logistic scorecard path:

- remove `_SKLEARN_FAMILIES`
- remove `_ENSEMBLE_FAMILIES`
- remove binary estimator loading
- remove numpy classifier inference
- remove runtime calibrator loading and transformation
- remove the estimator input role
- require the logistic model payload and WOE feature contract
- retain score scaling and scored-dataset evidence

### Strict metadata

- Remove the legacy-null fallback in modelling metadata handling.
- Require the current metadata type and fields in `TargetSpec.from_metadata`.
- Remove `getattr` defaults and `all_known` reconstruction.
- Remove `hasattr` fallbacks from `StepInputCollection.target_metadata`.

### Verification

- Update model artifact unit tests for strict parsing.
- Regenerate deterministic model and report fixtures.
- Run the canonical pathway and apply-model tests.
- Confirm no production code references estimator binaries, model-family
  dispatch, or runtime calibration.

## Batch 3: Remove Governance and Branch Execution

### Purpose

Remove challenger governance from the launch product while preserving manual
binning review functionality as a normal plans workflow.

### Remove

- `cardre/application/governance/`
- the governance API router and governance-only schemas
- branch, comparison, and champion repositories
- `CARDRE_GOVERNANCE` and `GovernanceNotEnabled`
- `run_scope="branch"` and branch-specific run validation
- branch columns and branch checks from runs, steps, and lineage tables
- `BRANCH_TABLES_SQL` and branch-only indexes
- branch-centric report modes and branch evidence resolution
- `COMPARISON_ARTIFACT` evidence vocabulary and parser support
- governance tests, marker, Makefile target, preflight invocation, and CI job
- governance-specific mypy configuration

Remove the governance job from the required-job verification logic in CI.

### Report collector

Simplify `ReportCollector` to operate from a run and plan version directly:

- remove `target_branch_id`
- remove inherited branch evidence resolution
- remove branch lists from report output
- remove champion lookup and champion status
- remove branch limitations and branch resolution metadata

### Manual-binning API relocation

Move these endpoints from `api/routes/governance.py` to an ungated plans-scoped
router:

- manual-binning preview
- apply manual-binning edit
- list/get/update manual-binning reviews

Keep their application use cases and review persistence. Update API schemas,
route tests, generated OpenAPI files, and frontend API types.

### Store naming

Rename:

- `V3_STORE_SCHEMA_FAMILY` → `STORE_SCHEMA_FAMILY`
- `V3_STORE_SCHEMA_VERSION` → `STORE_SCHEMA_VERSION`

Remove comments referring to v101 replacement or historical migration. The
store retains one schema identifier and rejects incompatible project stores.

## Batch 4: Collapse Methodology and Data Representations

### Automatic binning

Keep fine classing only:

- delete `_optbinning.py`
- delete `domain/binning/optbinning_adapter.py`
- remove OptBinning dependency checks and parameters
- remove `chi_merge` and `tree_binning` entries
- remove the `method` selector
- update canonical parameters to omit `method: fine_classing`

### Variable clustering

Keep correlation-threshold clustering only:

- remove hierarchical clustering implementation and parameters
- remove VARCLUS/PCA, mixed-type, and target-aware entries
- retain the current default threshold configuration

### Logistic regression

Keep standard logit only:

- remove penalised-logit and lasso-logit methods
- remove penalty, `C`, solver, and method-selector parameters
- retain only the standard logistic fit and its current validation rules

### Sample and split methodology

- Keep random-stratified splitting only.
- Remove preassigned-role splitting.
- Keep development sample domain `ttd` and method `full_population` only.
- Remove OTB, rejection-source, rejection-column, rejection-values,
  approval-column, and approval-values fields.
- Review ADR 0007 and add a supersession note if its sample vocabulary no
  longer matches the current product.

### WOE application

Make unmatched WOE values a strict failure invariant:

- remove `warn` and `fill_zero`
- remove `woe_unmatched_policy`
- collapse `MissingWoePolicy` to the failure behavior
- simplify evidence and metrics accordingly

### Parquet boundary

Import accepts only Parquet:

- retain `source_path` and `max_rows`
- remove CSV, TSV, and auto format detection
- remove delimiters, headers, encodings, null-value configuration,
  schema overrides, and dtype aliases
- update input validation, help text, tests, and documentation

Scorecard table export becomes Parquet-only:

- publish one tabular SCORE_TABLE artifact
- remove the duplicate JSON publication
- update the SCORE_TABLE evidence profile and parser to read the tabular form
- update downstream report/export consumers

### Dependencies and configuration

After the methodology purge, remove:

- optional dependency groups for boosting, imbalance, explainability, deep
  learning, OptBinning, and all-methods
- optional-dependency probing and related error codes
- pytest markers for removed optional features
- mypy ignores for removed third-party libraries

## Batch 5: Documentation, Tooling, and Drift Guards

### Remove obsolete tooling

- Delete `docs/architecture-rewrite/`.
- Delete `scripts/v2-phase-check.sh`.
- Delete `make v2-phase-check`.
- Delete `make test-launch-core`, which references missing tests.
- Remove the stale Ruff ignore for `cardre/_evidence/`.
- Remove stale mypy sections for deleted packages.

### ADRs and active documentation

Do not delete historical ADRs. Add a new ADR that:

- records the one-product purge as enforcement of ADR 0015
- supersedes ADR 0016 because estimator-binary verification is no longer a
  current product concern
- supersedes or replaces ADR 0013 if branch evidence resolution is removed
- documents the final Parquet boundary, logistic artifact, and governance
  decision

Update active documentation:

- `docs/README.md`
- `CONTEXT.md`
- node catalogue and feature-status references
- evidence-kind reference
- API contract
- report-bundle documentation
- storage architecture documentation
- any manual-binning API documentation

Remove launch-mode, deferred, estimator-reference, branch-governance, and
historical-migration language that no longer describes the product.

### Drift guards

Add repository-level tests or static checks for:

1. Registered production node types equal the distinct node types in
   `_CANONICAL_SCORECARD_STEPS`.
2. Production code contains no `launch_mode`, deferred-tier, `coming_soon`,
   or alternate model-family dispatch surface.
3. Strict persisted parsers reject unknown fields and missing current fields.
4. Production packages contain no test-fake node implementations.
5. The import boundary accepts only Parquet.
6. SCORE_TABLE has exactly one tabular publication path.
7. No governance branch scope or compatibility fallback remains.

The source-token guard must avoid false positives in historical ADRs and test
fixtures where the terms are intentionally documenting rejected behavior. It
should scan production implementation paths, not all repository text.

## Cross-Cutting Verification

Run these checks after every batch:

```bash
ruff check --fix
make preflight
scripts/pr-gate.sh
```

Also verify the following as relevant changes land:

- generated OpenAPI files are regenerated and clean
- generated error-code files are regenerated and clean
- frontend lint, format, build, and type checks pass
- import-linter passes
- artifact-read audit passes
- line-count and documentation-reference checks pass
- coverage remains above the configured 60% threshold
- fresh SQLite projects initialize successfully
- incompatible project schemas are rejected without migration attempts
- the canonical scorecard pathway executes end-to-end
- manual-binning preview/edit/review routes work without governance flags
- model, scorecard, validation, and export artifacts round-trip correctly

## Main Risks

- The model schema change affects parser adapters, score scaling, freezing,
  exports, apply-model, and golden fixtures simultaneously.
- Removing branch columns requires coordinated changes to SQLite DDL,
  repositories, run creation, reporting, and API models.
- Manual-binning review routes must be relocated before governance routes are
  deleted, or current canonical functionality loses its HTTP entry point.
- Removing estimator references makes ADR 0016 and estimator-focused tests
  obsolete; both code and documentation must change together.
- The evidence vocabulary must be pruned only after distinguishing canonical
  diagnostics from deferred reports, especially calibration.
- Generated frontend contracts may retain deleted fields until OpenAPI and
  error-code generators are rerun.

## Completion Criteria

The purge is complete when:

- production node registration exactly matches the canonical pathway
- no launch/deferred tier or launch-mode flag exists
- no deferred model family or alternate methodology selector exists
- logistic regression is the only model implementation
- model application has one direct logistic scorecard path
- persisted parsers accept exactly one current schema
- Parquet is the only input and score-table representation
- governance and branch execution are absent, while manual-binning review is
  available through the ungated plans API
- no compatibility fallback, historical-key blacklist, or migration chain
  remains
- obsolete tooling and architecture-rewrite documentation are removed
- all active documentation describes the resulting architecture
- every batch has passed the repository preflight and CI gate
