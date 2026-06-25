# Domain Model

## Plan vs Pathway vs DAG

- **Plan**: the versioned document that describes *what* to build — the intended graph of node instances. This is the user-facing concept they save, load, and version.
- **Pathway**: a fixed template or constrained view of a plan (e.g. "this plan follows the standard scorecard pathway"). A pathway *is a kind of plan*, not a synonym for all plans.
- **DAG**: internal implementation detail of the plan graph. Not exposed to the user.

## Node Type vs Step

- **Node type**: a reusable implementation registered in the node registry (e.g. `cardre.woe_transform`, `cardre.logistic_regression`). Has a `node_type` identifier, input/output contract, and executable code.
- **Step**: one occurrence of a node type within a plan. Has a `step_id`, params, parent step IDs, status, and run records. A plan is a graph of steps.
- Plan endpoints model `plan_steps` (intended configuration). Run endpoints model `run_steps` (execution evidence).

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
- **Refinement nodes** (build stream only): consume a definition artifact and produce a refined definition. Manual bin editing is the canonical example.
- **Selection nodes** (build stream only): consume metrics/rankings and filter which variables proceed downstream. Variable clustering and variable selection are canonical examples.
- **Apply nodes** (validate stream only): consume definitions from build stream + test/oot data, produce predictions and metrics. Examples: apply WOE mapping, apply model, calculate validation metrics.

## Step Status: Stored vs Computed

- **Stored statuses** (set by the executor): `not_run`, `queued`, `running`, `succeeded`, `failed`, `cancelled`.
- **`is_stale`**: a computed boolean property, not a stored status. Answers: "does this step's latest run reference the latest upstream run steps?" If an upstream step was re-run with different params/hash, all downstream steps become stale regardless of their stored status.

## Dataset vs Artifact vs Snapshot

- **Artifact**: any immutable output of a step execution. Includes datasets, models, metrics JSONs, reports, charts. Every artifact is content-addressed (by canonical hash) and stored immutably.
- **Dataset**: a tabular artifact (Parquet). Has schema, row count, column metadata, split roles. A *kind of* artifact, not a separate concept.
- **Snapshot**: not a separate entity. "Snapshot" describes an immutability property of artifacts (content-addressed, never mutated), not a distinct storage concept. Every artifact is a snapshot.

## Storage Model

- **SQLite**: metadata only — step records, plan versions, run records, artifact references (paths + hashes), user annotations, override reasons. No tabular data or binary blobs.
- **Parquet artifacts**: all tabular data — imported datasets, transformed datasets, metric tables, IV rankings, prediction tables.
- **JSON artifacts**: small non-tabular reports, configuration blobs, definition artifacts (bin maps, model parameters, scorecard specs).

## Artifact Hashing

- Every artifact has two hashes:
  - `physical_hash`: raw file bytes (SHA-256). Used for storage deduplication and bit-level integrity.
  - `logical_hash`: canonical representation hash (SHA-256 of a normalized form). Used for reproducibility comparison and staleness detection.
- For tabular artifacts: sort columns by name, serialize to canonical binary format (fixed schema, no compression, deterministic float representation), hash the result.
- For definition artifacts (bin maps, model coefficients): JSON-sorted-keys canonical serialization, then hash.
- The artifact store deduplicates by `physical_hash`. Audit/reproducibility compares by `logical_hash`.

## WOE/IV Evaluation vs WOE Transform

- **`calculate_woe_iv`**: a diagnostic/selection node. Consumes bin definitions + train data. Computes WOE and IV per variable. Output is a metrics/report artifact (IV ranking table), not a dataset transformation.
- **`woe_transform`**: a transformative node. Consumes bin definitions + data (train or test/oot). Applies bin definitions to produce a WOE-transformed dataset.

## Train/Test/OOT Split

- The split is a **step** in the pathway, not dataset metadata.
- The split step takes one input dataset and produces **three output artifacts**, one per role: `train`, `test`, `oot`.
- Each output artifact carries its role as metadata. Downstream nodes declare which artifact roles they consume.
- Fitting nodes consume `train`. Apply/transform nodes consume `test` and `oot`.
- The executor enforces role-based access: a fitting node cannot read test/OOT targets during fitting.
- Artifact roles are immutable once set by the split step.

## Licensing

Apache 2.0. Chosen over MIT for its patent grant clause, which is important for adoption in regulated financial institutions.
