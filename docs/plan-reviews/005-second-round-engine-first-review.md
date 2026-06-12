# Plan Review 005: Second Round Engine-First Review

This is much stronger. You fixed the biggest issue from the first version: it now has a clear product wedge — local reproducible audit-ready scorecard runs first, visual modelling workspace second.

The plan now feels like something that could become a credible open-source project rather than just a concept note. The best changes are:

- desktop-first is now explicit
- Streamlit is gone, which is right for this product
- manual binning is now treated as core, not a future nice-to-have
- leakage prevention is explicit
- DAG backend / fixed-pathway GUI is the right compromise
- governance export is split into technical manifest and human-readable report
- non-goals are clear
- packaging and sidecar lifecycle are finally acknowledged

My critique now is less “this is too vague” and more: this is credible, but still at risk of trying to build the polished app before proving the hard modelling engine.

## Biggest remaining risk: Phase 1 is still too broad

Phase 1 currently includes:

```text
Tauri shell
React scaffold
FastAPI sidecar
SQLite store
artifact store
executor
node registry
dummy nodes
immutable run records
replay
installer smoke test
```

That is a lot. I’d split it.

### Phase 1A: engine/storage proof

No Tauri yet. No React yet. Just prove:

```text
create project
import tiny dataset
run dummy DAG
write SQLite run records
write artifacts
change params
mark descendants stale
replay from changed node
export technical manifest
```

### Phase 1B: desktop shell proof

Then add:

```text
Tauri shell
bundled FastAPI sidecar
health check
logs
project open/create
installer smoke test
```

The risk is that Tauri/React/sidecar packaging issues consume all early energy before you have proven the actual Cardre engine.

Tauri sidecars are a legitimate fit here: Tauri supports bundling external binaries via `externalBin`, which maps well to a packaged local FastAPI/Python executable. But that also means you need early cross-platform packaging tests, not just Python unit tests.

## Strong recommendation: define the core SQLite schema next

The plan talks about the right concepts, but the next useful artefact should be a concrete schema. Something like:

```text
projects
datasets
dataset_snapshots
artifacts
plans
plan_versions
plan_steps
runs
run_steps
run_step_inputs
run_step_outputs
warnings
errors
annotations
branch_labels
champion_marks
```

The important distinction is:

```text
plan_steps = intended modelling graph
run_steps = actual execution evidence
artifacts = immutable outputs referenced by run steps
```

That separation is central to the whole product. Do not let “current node state” and “historical execution record” blur together.

## Manual binning needs a stricter minimum UX definition

You rightly say manual binning is essential. I’d now define the minimum acceptable v0 manual binning UX very concretely.

For v0, I’d require:

For each variable:

- show auto bins
- show count, bad count, good count, bad rate, WOE, IV contribution
- show train/test/OOT distribution where available
- allow merge adjacent numeric bins
- allow group categorical levels
- allow isolate missing
- allow isolate special values
- require reason for each override
- show monotonicity warning
- show sparse-bin warning
- show zero-cell warning
- preview before accepting

I would not allow arbitrary freehand numeric boundary editing in the first version unless you can validate it extremely safely. Merging bins is safer, easier to audit, and closer to how a lot of coarse classing actually works.

## Data engine choice: I’d make DuckDB the first backbone

Your open question asks DuckDB, Polars, or pandas. My practical answer:

DuckDB first for import, profiling, split summaries, aggregation, Parquet querying.
pandas/sklearn/statsmodels for model-fitting once a modelling matrix is materialised.
Polars later if needed.

DuckDB is a strong fit because Cardre’s early workload is full of SQL-like profiling, grouped summaries, bin counts, Parquet scans, train/test/OOT comparisons, and artifact inspection. DuckDB’s Python client can directly query Pandas, Polars, and Arrow objects, and it has native Parquet-oriented workflows, so it gives you flexibility without committing everything to pandas memory semantics.

I’d avoid trying to be “engine agnostic” too early. Pick one execution backbone for v0 or you’ll spend too much time abstracting.

## Packaging: start PyInstaller, keep Nuitka as a later alternative

For the Python sidecar, I’d start with PyInstaller unless you hit a specific blocker. It is mature for bundling Python apps, but note the important limitation: it is not a cross-compiler, so you need to build Windows on Windows, macOS on macOS, and Linux on Linux in CI/release packaging.

Nuitka is worth keeping on the list, especially if startup time, binary size, or source-code exposure become issues. Nuitka supports standalone/onefile deployment modes, but it is likely to add more packaging complexity earlier than you need.

So I’d phrase the decision like this:

```text
Default packaging path: PyInstaller.
Evaluation trigger for Nuitka: PyInstaller startup time, package size,
dependency compatibility, or source-distribution concerns become unacceptable.
```

## Add a “model correctness test suite” section

The plan has engineering smoke tests, but it needs scorecard-specific correctness tests. This is absolutely essential.

Add tests like:

Given a known toy dataset:

- bin counts match expected values
- WOE values match hand-calculated values
- IV values match hand-calculated values
- smoothing behaves as specified
- train-only fitting does not inspect test/OOT target distribution
- WOE mapping applies correctly to unseen test/OOT values
- score scaling produces expected points
- Python and SQL scoring outputs match row-by-row

This is more important than the GUI early on. The product’s credibility depends on boring numerical correctness.

## Define WOE smoothing policy early

The plan mentions zero-cell bins and smoothing, but this needs a product decision. WOE can explode with zero goods or zero bads. You need explicit handling:

Options:

- block execution until bins are merged
- apply additive smoothing
- cap WOE at configured limits
- allow override only with governance warning

My suggestion for governance mode:

Default: block zero-cell WOE unless smoothing is explicitly enabled.
If smoothing is enabled, record method, parameter, affected bins, and rationale.

Otherwise users will get plausible-looking scorecards with hidden instability.

## Add “unknown category / out-of-range scoring” handling

This is a common implementation gap. The plan says fit on train and apply to test/OOT, but what happens when production data has:

```text
a categorical level unseen in train
```

Cardre should define this in the binning artifact.

For every variable, the binning map should include:

```text
normal bins
missing bin policy
special-code policy
unknown category policy
out-of-range numeric policy
fallback behaviour
warning/error severity
```

This matters later for SQL export and implementation parity.

## The audit pack should include the environment, but not depend on it too much

The manifest includes Python/runtime version, dependency lockfile hash, and node versions. Good. But for user trust, also include:

```text
Cardre project schema version
model artifact schema version
scorecard export schema version
operating system/platform
numerical tolerance policy
```

The reproducibility contract correctly distinguishes logical reproducibility from byte-level reproducibility. That is a very mature bit of the plan.

## Security section needs one more practical item

Add:

Project-level “sensitive mode”:

- redact sample values in logs
- suppress raw row previews unless user enables them
- prevent exporting raw transformed datasets inside audit pack by default
- audit pack includes metadata/reports/model artifacts, not full portfolio data unless explicitly selected

This is important because “audit export” can accidentally become “zip up all sensitive customer data”.

## API surface needs job/cancellation endpoints

Since execution does not block the GUI, add endpoints for run lifecycle:

```text
POST /runs
GET /runs/{run_id}
POST /runs/{run_id}/cancel
GET /runs/{run_id}/events
GET /runs/{run_id}/logs
```

Polling is fine for v0, but the API should treat runs as jobs from the beginning.

Also consider separating plan mutation from execution:

```text
POST /plans/{plan_id}/versions
PATCH /plans/{plan_id}/versions/{version_id}/nodes/{node_id}
POST /runs?plan_version_id=...
```

This makes it harder to accidentally run a moving target.

## Add explicit “governance mode” vs “exploration mode”

This could be a useful product concept.

Exploration mode:

```text
warnings allowed
unseeded stochastic steps allowed with warning
looser audit requirements
faster iteration
```

Governance mode:

```text
explicit seeds required
zero-cell WOE blocked or justified
manual overrides require reasons
missing target definitions blocked
```

That gives users freedom while preserving the serious model-risk story.

## Open questions: my answers

### PyInstaller or Nuitka?

Start with PyInstaller. Evaluate Nuitka later if packaging/startup/source-exposure becomes painful.

### DuckDB, Polars, or pandas?

Use DuckDB + Parquet as the data/profiling backbone. Use pandas/sklearn/statsmodels for modelling matrices where needed. Avoid bringing in Polars until there is a clear pain point.

### Canonical hash rules?

Start with a pragmatic v0:

```text
hash(
  artifact_kind,
  schema,
  ordered column names,
  row count,
  role metadata,
  sorted stable row-id hash if row id exists,
  deterministic Arrow/Parquet logical value stream where feasible
)
```

For v0, also store a raw file hash separately. Call them:

```text
physical_hash
logical_hash
```

### Minimum manual binning UX?

Merge bins, group categorical levels, isolate missing/specials, require reasons, show WOE/event-rate/counts, warn on monotonicity/sparse/zero-cell issues. Defer arbitrary boundary editing if necessary.

### Should SQLite store small tabular reports?

Yes, but only small summaries. Store big tables as Parquet. A good rule:

```text
SQLite: metadata, JSON summaries, warnings, metrics, small report tables.
Parquet/filesystem: datasets, transformed matrices, large bin-level outputs, model artifacts.
```

### Mandatory validation metrics?

For the first governance-quality version:

```text
sample counts and bad rates by split
AUC/Gini by split
KS by split
score distribution by split
calibration table by score band
bin-level WOE/IV
variable IV
coefficient table
correlation/high-collinearity evidence
PSI/CSI where OOT or time period exists
Python-vs-SQL parity test
```

### License?

For this type of modelling tool, I’d lean Apache 2.0 over MIT because it gives a more explicit patent grant, which can matter for corporate adoption. MIT is simpler, but Apache 2.0 may feel more comfortable to banks and larger firms.

## My revised verdict

This is now a serious plan. The architecture is coherent, the sequencing is much better, and the product positioning is sharp.

The main thing I’d change now is:

Do not build “the desktop app” first. Build the executable modelling truth first, then wrap it.

In practical terms:

1. Python engine + SQLite + artifact store + dummy DAG
2. Scorecard correctness tests
3. Minimal fixed scorecard pathway via CLI/API
4. Then Tauri/React GUI
5. Then branching
6. Then governance-quality report

The plan is very close. The next document should probably be one of these:

- Cardre v0 technical architecture spec
- SQLite schema and artifact model
- Node contract/interface spec
- Manual binning UX spec
- Scorecard correctness test plan

Of those, I’d do Node contract/interface spec + SQLite schema first, because everything else depends on that.
