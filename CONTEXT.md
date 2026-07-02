# Cardre Domain Glossary

## v2 Domain Model — Five First-Class Concepts

Cardre v2 is organised around five first-class domain concepts:

1. **Project**: A scorecard project root directory (e.g. `example.cardre/`) containing a SQLite metadata store, datasets, artifacts, exports, and logs.
2. **Plan**: The versioned document describing *what* to build — the intended graph of node instances. Users save, load, and version plans.
3. **PlanVersion**: An immutable snapshot of a plan at a point in time. May be **draft** (editable, not yet executed) or **committed** (finalised, eligible for execution). Created on save; every run references exactly one plan version.
4. **Run**: One execution of a committed plan version. Has a status lifecycle (pending → running → succeeded/failed/cancelled). May be sync (blocking) or async (background). Contains per-step execution records.
5. **Artifact**: An immutable output file produced by a run step. Stored on filesystem by physical hash (SHA-256); carries a logical hash for reproducibility comparison. Referenced by metadata store.

### Plan Version State

- **Draft**: Editable plan version. No runs can reference it. Steps may be added, removed, or reconfigured. Drafts become committed via the mutation service.
- **Committed**: Frozen plan version. Eligible for execution. Runs reference exactly one committed plan version.

## Two-Level Evidence Model

v2 replaces the v1 `run_steps.input_artifact_ids_json` / `output_artifact_ids_json` columns with a proper two-level evidence model:

- **`evidence_edges`**: One row per parent→child edge at run time. Records the resolution policy (exact, param-only, tolerance), whether the edge is reused or stale, and links to source run steps. The grain is (run_step_id, parent_step_id, source_run_step_id).
- **`evidence_artifacts`**: One row per artifact attached to an evidence edge. Multiple artifacts (e.g. bin definitions + profile summary) can be attached to the same edge.

This is the **only** lineage source. No JSON arrays on `run_steps`. Staleness is computed from these tables, not written onto historical rows.

### EvidenceAdapter

- **EvidenceAdapter**: the concrete thing at the evidence seam — one per `EvidenceKind`, owns matching (which artifact in a list is this kind) and parsing (artifact bytes → typed dataclass). Registered in `cardre/_evidence/adapters/` via the `EVIDENCE_ADAPTERS` registry. `ArtifactEvidenceReader` is the thin dispatcher + `artifact_lineage` resolver that delegates to adapters.

## Relational Relationship Tables

JSON relationship arrays from v1 have been replaced by relational join tables:

| v1 (JSON array) | v2 (relational table) |
|---|---|
| `plan_steps.parent_step_ids_json` | `plan_step_edges` |
| `branch_comparisons.challenger_branch_ids_json` | `comparison_challenger_branches` |
| `branch_comparison_snapshots.source_plan_version_ids_json` | `comparison_snapshot_plan_versions` |

## Node Type vs Step

- **Node type**: a reusable implementation registered in the node registry (e.g. `cardre.woe_transform`, `cardre.logistic_regression`). Has a `node_type` identifier, input/output contract, and executable code.
- **Step**: one occurrence of a node type within a plan. Has a `step_id`, params, parent step IDs (via `plan_step_edges`), status, and run records. A plan is a graph of steps.
- Plan endpoints model `plan_steps` (intended configuration). Run endpoints model `run_steps` (execution evidence).

## Node Tiers

- **Launch**: Nodes executable in the default scorecard journey. Instantiation of a deferred node raises `NodeNotAvailableForLaunch`.
- **Deferred**: Nodes registered as schemas for UI display but not executable in launch mode (boosting, ensembles, fairness, reject inference, etc.).

## Plan Version vs Run

- A **plan version** is created when the user explicitly saves/modifies the plan (adds/removes/reconfigures steps). It is a user-triggered snapshot of *intent*.
- A **run** is one execution of a given plan version. The same plan version may be run multiple times (e.g. different seeds, comparison runs).
- A plan version exists independently of any run. Every run references exactly one plan version.

## Build Stream vs Validate Stream

The pathway has a clear boundary after the scorecard is finalized:

- **Build stream** (train only): everything from import through score scaling. Fits all parameters — bin boundaries, WOE maps, model coefficients, scorecard parameters. Operates exclusively on the `train` artifact.
- **Validate stream** (test/oot): everything after scorecard finalization. Applies the fitted definitions from the build stream to `test` and `oot` data. Produces performance metrics.

The boundary: once score scaling produces the finalized scorecard, the validate stream applies it to holdout samples.

### Build Stream Workflow

1. Define population/product/segment, target, good/bad/indeterminate categories, observation/sample window, performance/outcome window, and exclusions.
2. Define development sample construction, including sampling method, weights, base bad rate, and any prior-probability adjustment metadata.
3. Split train/test/OOT → produces role-tagged artifacts.
4. Missing/outlier treatment and candidate variable derivation.
5. Auto fine classing → bins ALL variables on train.
6. WOE/IV calculation → computes WOE and IV for all variables (enables variable ranking/selection).
7. Variable clustering / correlation grouping → identifies redundant variables before selection.
8. Variable selection → filters to the strongest variables for coarse classing and modelling.
9. Manual bin editing / coarse classing → refines bins for *only the selected variables* (manual, so limiting to strong candidates is essential).
10. WOE transform → applies refined (or auto) bin definitions to produce the WOE-transformed train dataset.
11. Logistic regression → fits model on WOE-transformed train data.
12. Score scaling → converts log-odds to scorecard points.
13. Gains/characteristic reports and cutoff/strategy analysis.

### Node Categories

- **Fit nodes** (build stream only): consume `train`, produce definition artifacts (bin maps, WOE maps, model, scorecard). Examples: auto fine classing, WOE transform, logistic regression, score scaling.
- **Refinement nodes** (build stream only): consume a definition artifact and produce a refined definition. Manual bin editing is the canonical example — it takes auto bin definitions and produces overridden bin definitions for selected variables only.
- **Selection nodes** (build stream only): consume metrics/rankings and filter which variables proceed downstream. Variable clustering/correlation grouping and variable selection are canonical examples.
- **Apply nodes** (validate stream only): consume definitions from build stream + test/oot data, produce predictions and metrics. Examples: apply WOE mapping, apply model, calculate validation metrics.

## Branch / Comparison / Champion

- **Branch**: A diverged copy of a plan starting from a permitted branch point. Each challenger branch creates a new plan version with duplicated downstream steps and shared upstream steps.
- **Comparison**: An intent to compare a baseline branch against one or more challenger branches. Produces immutable comparison snapshots containing WOE/IV, model coefficients, validation metrics, and cutoff analysis.
- **Champion**: The designated best-performing branch for a given scope. Supersedes previous champions. Assignments require a ready comparison snapshot.

## Governance

Governance features (branching, comparison, champion assignment) are gated behind `CARDRE_GOVERNANCE=1`. The API uses `Depends(require_governance)` to return 403 when governance is not enabled.

## Licensing

Apache 2.0. Chosen over MIT for its patent grant clause, which is important for adoption in regulated financial institutions. Downstream users get explicit protection from patent claims related to the code.

## Missing Value Handling

Two distinct concepts:

- **Imputation**: pre-binning data transform. Replaces missing values with a statistical value (mean, median, mode) so the variable can participate in binning normally. Lives in the data preparation phase.
- **Separate bin**: binning-time strategy. Missing values (or specific codes) are isolated into their own bin with their own WOE calculation. Treated as a distinct risk category at scoring time.

These are two different node types: `impute_missing` (data transform) and the `missing_policy` property on `fine_classing` (binning strategy). A variable may use neither, one, or both.

## Storage Model

- **SQLite**: metadata only — step records, plan versions, run records, artifact references (paths + hashes), evidence edges + artifacts, user annotations, override reasons. No tabular data or binary blobs.
- **Parquet artifacts**: all tabular data — imported datasets, transformed datasets, metric tables, IV rankings, prediction tables.
- **JSON artifacts**: small non-tabular reports, configuration blobs, definition artifacts (bin maps, model parameters, scorecard specs).
- This keeps SQLite lean, queryable, and easy to backup while Parquet handles columnar data efficiently.

## Artifact Hashing

- Every artifact has two hashes:
  - `physical_hash`: raw file bytes (SHA-256). Used for storage deduplication and bit-level integrity.
  - `logical_hash`: canonical representation hash (SHA-256 of a normalized form). Used for reproducibility comparison and staleness detection.
- For tabular artifacts: sort columns by name, serialize to canonical binary format (fixed schema, no compression, deterministic float representation), hash the result.
- For definition artifacts (bin maps, model coefficients): JSON-sorted-keys canonical serialization, then hash.
- The artifact store deduplicates by `physical_hash`. Audit/reproducibility compares by `logical_hash`.
