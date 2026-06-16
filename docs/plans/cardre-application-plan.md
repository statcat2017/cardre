# Cardre Application Plan

## Vision

Cardre will be an open-source desktop scorecard builder for credit-risk model
development. It will let a modeller load local data, build a scorecard through a
visible pathway of auditable transformation/model nodes, manually refine bins,
compare modelling choices, and export a model-development audit pack.

The product idea is: **PowerBI-style transform flow for scorecard modelling, but
local-first, reproducible, branchable, and governance-aware.**

Cardre is not intended to be a hosted web app. Credit datasets are often large,
sensitive, and governed by strict data-handling rules. The app should run on the
user's machine from day one and should not require uploading portfolio data to a
remote service.

## Product Positioning

Cardre's differentiator is not simply calculating WOE, IV, logistic regression,
or score scaling. Existing Python packages can already do parts of that.

Cardre's differentiator is:

> Making the scorecard modelling journey visible, editable, branchable,
> reproducible, and exportable for audit.

The first strong claim should be **reproducible auditable scorecard runs**. The
larger visual branching/modelling workspace should grow from that foundation.

## Core Decisions

- Cardre's product form is a **desktop app from day one**, but implementation
  begins with the local engine, storage model, and reproducibility contract
  before the GUI is built.
- The desktop shell will use **Tauri**.
- The GUI will use **React + TypeScript**.
- The backend will be a **bundled local FastAPI sidecar**.
- The scorecard engine will be a pure Python package used by the sidecar.
- Project metadata, plan versions, and run records will live in **SQLite** (metadata only, no tabular data).
- Large tabular artifacts will be stored as **Parquet**. Small non-tabular definitions (bin maps, model params) as **JSON**.
- Raw CSV is an import/export format, not the internal canonical data format.
- The backend plan model will be **DAG-capable** internally, but the first GUI presents a fixed two-stream scorecard pathway.
- The first GUI will present a constrained **two-stream scorecard pathway** (build stream on train, scoring/evaluation stream on train/test/OOT), not a freeform DAG canvas.
- **Manual binning is essential** and must be part of the first credible scorecard release.
- The formal plugin API is deferred until the internal node registry API stabilises.
- **Node type** and **step** are distinct: a node type is a reusable implementation, a step is one occurrence of a node type within a plan.

## Core Principles

- Original input data is stored as an immutable content-addressed artifact.
- Every step in a plan is represented by a step with an explicit node type, properties, inputs, outputs, validation rules, and executable implementation.
- Every step execution creates a durable audit record. Existing run history is never overwritten.
- Changing a step's properties creates a new plan version. The changed step and all descendants become stale. The executor replays only the affected branch.
- The pathway splits into two streams after the train/test/OOT split. The build stream fits all parameters on train only. The scoring/evaluation stream applies the fitted definitions to train/test/OOT for metrics. The executor enforces role-based artifact access per step type.
- GUI state is not modelling truth. The Python engine and SQLite records are the source of truth.
- Every artifact has a physical hash (raw bytes) and a logical hash (canonical content) for reproducibility comparison.
- Step outputs must be explainable from input artifacts, node type, parameter values, hashes, metrics, warnings, code versions, and run records.

## Target Users

- Credit-risk analysts who need a transparent scorecard-building tool.
- Data scientists building reproducible WOE/logistic-regression scorecards.
- Model-risk/governance teams reviewing model development evidence.
- Learners who want to understand scorecard development step by step.

The first version should serve technical and semi-technical users. A later
wizard-style mode can hide pathway complexity for traditional analysts while
still producing the same audit trail.

## Desktop Architecture

```text
Cardre Desktop App
  Tauri shell
    React + TypeScript frontend
      pathway view
      node property editor
      manual binning editor
      run/status views
      metrics and result viewers
      audit export UI

  bundled local FastAPI sidecar
    project API
    dataset API
    pathway/plan API
    node execution API
    artifact/result API
    export API

  Python Cardre engine
    pipeline executor
    node registry
    scorecard domain functions
    audit and replay logic

  local project storage
    SQLite metadata database
    Parquet datasets and artifacts
    exported audit packs
```

### Sidecar Lifecycle

The Tauri shell owns the sidecar lifecycle in production:

1. Choose or reserve a localhost port.
2. Start the bundled `cardre-api` sidecar process.
3. Wait for a `/health` endpoint.
4. Pass the API URL to React.
5. Capture sidecar logs to a local diagnostic file.
6. Shut down the sidecar when the app exits.
7. Surface startup failures with actionable messages.

Development mode may run the frontend and backend separately, but production
installers must not require the user to install Python or start a server.

## Project Storage

Each Cardre project is a local directory containing a SQLite database and local
artifacts:

```text
my-scorecard.cardre/
  cardre.sqlite
  datasets/
  artifacts/
  exports/
  logs/
```

SQLite stores **metadata only** (no tabular data or binary blobs):

- project metadata
- plan versions and step configurations
- run records
- step execution records
- artifact references (paths + hashes)
- warnings and structured errors
- champion/challenger labels
- user-entered override reasons and annotations

The filesystem stores all data artifacts:

- imported raw file copies where appropriate
- canonical Parquet datasets
- transformed Parquet datasets
- JSON definition artifacts (bin maps, model coefficients, scorecard specs)
- model artifacts
- validation metrics and reports
- exported audit packs

SQLite gives transactional updates for plan edits and run records while keeping
large binary/tabular files out of the database. Tabular data lives in Parquet,
small non-tabular definitions live as JSON artifact files.

## Artifact Strategy

### Internal Format

- Use Parquet for internal tabular artifacts.
- Convert CSV imports to canonical Parquet as early as possible.
- Keep CSV as an import/export convenience, not as the internal truth.

### Artifact Hashing

Every artifact has two hashes:

- **`physical_hash`**: raw file bytes (SHA-256). Used for storage deduplication and bit-level integrity.
- **`logical_hash`**: canonical representation hash (SHA-256 of a normalized form). Used for reproducibility comparison and staleness detection.

For tabular artifacts, the logical hash is computed over a canonical form:

- use deterministic column ordering. For unordered datasets this may be sorted
  by name; for model matrices or artifacts where order is semantically
  meaningful, the artifact schema declares the canonical order.
- serialize to canonical binary format (fixed schema, no compression,
  deterministic float representation)
- hash the serialized bytes

For definition artifacts (bin maps, model coefficients, scorecard params):

- JSON-sorted-keys canonical serialization, then hash

The artifact store deduplicates by `physical_hash`. Audit and reproducibility
comparisons use `logical_hash`. This avoids false-negative comparisons caused by
Parquet metadata differences, compression variation, or float formatting across
platforms.

### Snapshot Strategy

Large datasets make full physical copies after every node expensive. Early
versions should snapshot physical Parquet artifacts when rows change or new
columns are created. For purely metadata-like steps, store reports or recipes
rather than full dataset copies.

Later, Cardre can use DuckDB or Polars lazy execution for larger-than-memory
data, but the audit record must still make the executed transformation and its
inputs explicit.

## Plan Model

A plan is a versioned DAG of steps. The first GUI presents this as a fixed
two-stream scorecard pathway (build stream on train, scoring/evaluation stream on train/test/OOT),
but the backend supports multiple parents through `parent_step_ids` to avoid
painting the architecture into a corner.

`plan_steps` records current design intent:

- `step_id`: unique step instance ID within the plan
- `node_type`: registered implementation type, e.g. `cardre.woe_transform`
- `version`: implementation/schema version of the node type
- `params`: JSON-serialisable properties
- `params_hash`: stable hash of properties (for change detection)
- `parent_step_ids`: upstream steps
- `branch_label`: optional GUI label
- `warnings`: structured modelling or data-quality warnings

Execution status belongs to `run_steps`, not `plan_steps`. The API computes a
display status from the latest relevant run step and computes `is_stale` from the
execution fingerprint described below.

`run_steps` records execution evidence:

- `run_step_id`
- `run_id`
- `step_id`
- `plan_version_id`
- `status`: `not_run`, `queued`, `running`, `succeeded`, `failed`, `cancelled`
- `started_at`, `finished_at`
- `input_artifact_ids`
- `output_artifact_ids`
- `execution_fingerprint`
- `warnings`
- `errors`

### Execution Fingerprint

Each successful step execution records an execution fingerprint containing:

- plan version ID
- step ID
- node type and implementation version
- step params hash
- parent run step IDs
- input artifact logical hashes
- relevant runtime/dependency metadata
- output artifact logical hashes

A step is current only if its latest successful execution fingerprint matches the
current plan, current parent outputs, and current implementation version.
Otherwise it is stale.

### Replay Semantics

When a user changes a step property:

1. Cardre creates a new plan version.
2. The changed step and all descendants are marked stale (computed `is_stale`).
3. Unaffected sibling branches remain valid.
4. The executor reruns the changed step and descendants in topological order.
5. Existing run records are retained; new records are added for the replayed
   branch.
6. The user can compare previous and new results.

## Minimum Viable Scorecard Pathway

The first useful product release should not be a freeform visual modelling
platform. It should be a fixed, credible scorecard template with two streams:

```text
BUILD STREAM (train only):
  Import Dataset
  -> Define Population / Product / Segment
  -> Define Target, Good/Bad/Indeterminate, Observation + Performance Windows
  -> Apply Exclusions
  -> Profile Dataset
  -> Validate Binary Target
  -> Development Sample Definition  (sample method, weights, base bad rate)
  -> Define Train/Test/OOT Split  -- produces train, test, oot artifacts
  -> Missing/Outlier Treatment
  -> Candidate Variable Derivation
  -> Automatic Fine Classing       (bins all variables on train)
  -> Initial WOE/IV Diagnostics    (rank variables using automatic bins)
  -> Variable Clustering           (correlation/redundancy groups)
  -> Candidate Variable Selection  (filter to strongest variables)
  -> Manual Bin Editing            (refine bins for selected variables only)
  -> Final WOE/IV Calculation      (using refined bins)
  -> WOE Transform Train           (apply refined bins to train)
  -> Logistic Regression           (fit model on WOE-transformed train)
  -> Score Scaling                 (convert log-odds to scorecard points)
  -> Gains + Characteristic Reports
  ------------------------------- SCORECARD FINALIZED -----------------

SCORING/EVALUATION STREAM (train, test, and oot):
  -> Apply WOE Mapping             (using build-stream bin definitions)
  -> Apply Model                   (using build-stream model coefficients)
  -> Score -> Metrics by role
  -> Cutoff / Strategy Analysis
  -> Audit Export
```

The fixed two-stream pathway keeps the early product focused while proving the
hard parts: storage, step execution, leakage prevention (test/oot never pass
through fitting steps), the build/evaluation boundary, Siddiqi-style project
parameter discipline, manual binning, reproducibility, and audit export.

The early project-parameter steps are part of the scorecard pathway, not just
report text. They capture the assumptions Siddiqi treats as load-bearing:

- the target population and intended product/channel/segment
- good, bad, and indeterminate outcome definitions
- observation/sample window and performance/outcome window
- maturity/representativeness checks for the selected sample window
- exclusion rules and the reasons they are applied
- development sample construction, including oversampling, sample weights, and
  population bad-rate metadata used for prior-probability adjustment

The first release may implement some of these as configuration and report nodes
rather than complex automated analytics, but their definitions must be explicit,
versioned, and exported in the audit pack.

Segmentation is also a first-class modelling consideration. The first fixed
pathway can build one scorecard at a time, but it should still include a
segmentation analysis/report step so the modeller can record whether separate
scorecards, separate cutoffs, or no segmentation are justified. Later branching
support should make segment-specific challenger scorecards natural.

## Train/Test/OOT Discipline

Leakage prevention is a core correctness requirement enforced structurally, not
by convention.

The split is a **step** in the pathway, not dataset metadata. The split step
takes one input dataset and produces **three output artifacts**, one per role:

- `train`
- `test`
- `oot`

Each output artifact carries its role as immutable metadata. Downstream steps
declare which artifact roles they consume:

- **Fit steps** (build stream): consume `train` only. Examples: fine classing,
  WOE transform, logistic regression, score scaling.
- **Apply steps** (scoring/evaluation stream): consume `train`, `test`, and
  `oot` as scoring inputs (plus definition artifacts from the build stream).
  Examples: apply WOE mapping, apply model, calculate metrics. Train is scored
  for comparison, not used for additional fitting.
- **Refinement steps** (build stream): consume existing definition artifacts and
  produce refined definitions. Example: manual bin editing.
- **Selection steps** (build stream): consume metric/report artifacts and produce
  a filtered set. Examples: variable clustering and variable selection.

The executor validates artifact role access before each execution. A fitting
step is structurally prevented from reading test/OOT artifacts, even if a bug
miswired the plan graph.

Rules:

- Split definitions must be recorded in the audit trail.
- Validation metrics are reported separately for train, test, and OOT.
- A future governance mode can block full-dataset fitting for learned
  transformations, requiring an explicit split step.

## Node Type Model

Each **node type** is a reusable registered implementation. A **step** is one
occurrence of a node type within a plan. A node type defines:

- stable `node_type` identifier
- implementation version
- display name and description
- category: `fit`, `apply`, `refinement`, `selection`, or `transform`
- input artifact roles (e.g. `fit_inputs=["train"]`, `apply_inputs=["test","oot"]`)
- output artifact roles and artifact types (dataset, definition, report)
- property schema with validation rules
- deterministic execution function
- optional GUI renderer metadata

Example node type concept:

```python
class FineClassingNode:
    node_type = "cardre.fine_classing"
    version = "1"
    display_name = "Automatic fine classing"
    category = "fit"

    property_schema = {
        "max_bins": {"type": "integer", "minimum": 2, "default": 20},
        "min_bin_fraction": {"type": "number", "minimum": 0, "default": 0.05},
        "missing_policy": {
            "type": "string",
            "enum": ["separate_bin", "impute", "exclude"],
            "default": "separate_bin",
        },
        "random_seed": {"type": "integer", "nullable": True},
    }
```

Step properties (set by the user in the GUI) must be:

- JSON-serialisable
- validated against the node type's property schema before execution
- included in the `params_hash` for change detection
- stored in the audit record
- displayed in the GUI

## Manual Binning (Coarse Classing)

Manual binning (coarse classing) is essential for professional scorecard
development. Automated binning should be treated as a starting point, not the
final modelling decision. Manual binning operates on the build stream only,
refining bin definitions for variables selected after WOE/IV evaluation and
variable clustering - not for all variables (coarse classing is manual, so it is
limited to the strongest scorecard candidates).

The manual binning node should support:

- merging adjacent numeric bins
- editing numeric boundaries where safe
- grouping categorical levels
- isolating missing values
- isolating special codes such as `999`, `-1`, `No hit`, or bureau error codes
- requiring override reasons for manual changes
- warning on non-monotonic WOE
- warning on zero-cell bins
- warning on sparse bins below a configured population threshold
- showing before/after WOE and event-rate charts
- preserving every manual decision in the plan and audit record
- identifying source bins by immutable bin IDs, not by array index position

Manual bin adjustments should be represented as explicit JSON properties, not as
opaque edited output files. Example concept:

```json
{
  "variable": "utilisation_rate",
  "source_bins_artifact": "auto-bin-output",
  "overrides": [
    {
      "action": "merge_bins",
      "source_bin_ids": ["bin_03", "bin_04"],
      "new_label": "40%-70%",
      "reason": "Merged sparse adjacent bins to meet minimum population rule"
    },
    {
      "action": "isolate_special_value",
      "values": [999],
      "new_label": "Bureau no-hit",
      "reason": "Operationally distinct bureau no-hit code"
    }
  ]
}
```

This allows the exact binning choices to be replayed and reviewed without relying
on an analyst's spreadsheet edits.

The v0 binning UI should be table-based. Users merge/group bins, click
recalculate, then see updated before/after WOE and event-rate charts. Live chart
updates on every edit and drag-and-drop boundary editing can come later.

## Variable Selection Auditability

Variable selection must be as auditable as manual binning. The variable selection
step records one decision object per candidate variable:

```json
{
  "variable": "utilisation_rate",
  "decision": "include",
  "source": "automatic_threshold",
  "iv": 0.18,
  "iv_threshold": 0.02,
  "correlation_cluster_id": "cluster_04",
  "manual_override": false,
  "reason": "Included because IV exceeds threshold and no stronger correlated variable was selected"
}
```

For exclusions, the decision record must capture the exclusion reason, such as
low IV, high missingness, high correlation with a selected variable, unstable
WOE, business inadmissibility, or manual analyst override. Manual overrides
require non-empty reason text and appear in the model development report.

### Scoring Fallback Rules

Every binning artifact must define explicit handling for:

- unseen categorical levels
- numeric values outside training ranges
- missing values
- undeclared special codes
- malformed scoring-time values

Fallback usage must be counted during validation and included in the audit
report. Governance exports should flag high fallback usage as a model
implementation risk.

### Zero-Cell WOE Policy

Bins with zero goods or zero bads must not silently produce infinite WOE values.
The default behaviour is to block final WOE mapping until the bins are merged or
a smoothing policy is explicitly enabled. If smoothing is enabled, the smoothing
method, parameter, affected bins, and user rationale are recorded in the audit
trail.

## Built-In Node Roadmap

### Data Nodes

- import dataset
- define population / product / segment
- define target and good/bad/indeterminate outcome categories
- define observation/sample window and performance/outcome window
- apply exclusion rules with reason capture
- profile dataset
- validate binary target
- maturity and representativeness report for the selected sample window
- development sample definition, including sampling method, sample weights, and
  population bad-rate metadata
- define train/test/OOT split
- filter rows
- select/exclude variables
- impute missing values
- cap/floor outliers
- create derived variables
- segmentation analysis report

### Binning Nodes

- automatic fine classing (bins all variables on train)
- manual bin editing (coarse classing on selected variables only)
- categorical grouping
- missing/special value isolation
- bin override import/export
- monotonicity and sparse-bin checks

### WOE/IV Nodes

- initial WOE/IV diagnostics (ranks variables by IV using automatic bins)
- final WOE/IV calculation (uses manually refined bins)
- apply WOE mapping to test/OOT
- flag zero-cell bins and apply smoothing policy
- generate WOE-transformed dataset (applies refined bin definitions)

### Modelling Nodes

- high-correlation variable clustering
- variable selection with auditable inclusion/exclusion decisions
- logistic regression
- perfect separation detection
- coefficient sign checks (business-sense validation)
- sample-weight handling
- prior-probability/base-rate adjustment for oversampled development samples
- reject inference (see Phase 7 and `docs/plans/reject-inference-module-plan.md`)

### Scorecard Nodes

- score scaling
- points allocation
- reason-code generation
- gains table and cutoff analysis
- characteristic report / attribute-points report
- score distribution analysis
- Python scoring export
- SQL scoring export
- implementation parity test between Python and SQL scoring

### Validation And Monitoring Nodes

- ROC AUC / Gini
- KS statistic
- lift/gains charts
- calibration plot
- PSI by segment and time period
- SSI / characteristic stability
- train/test/OOT metric comparison
- subpopulation impact report
- policy rule and override policy documentation
- champion/challenger comparison

### Export Nodes

- technical JSON manifest
- human-readable model development report
- scorecard CSV
- Python scoring code
- SQL scoring code
- PMML later if useful for banking integrations

## GUI Plan

### Initial GUI

The initial Tauri/React GUI should be constrained and product-focused:

- create/open local project
- select local dataset
- convert/store internal Parquet artifact
- configure ID, target, and split fields
- display fixed two-stream pathway (build and validate) as connected step cards
- show step statuses: not run, running, succeeded, failed, cancelled; stale state shown as a computed visual marker
- edit step properties per node type schema
- run from selected step (and its downstream branch)
- view step outputs and warnings
- manually edit bins in a dedicated table/chart view
- export an audit pack

### Later GUI

After the fixed pathway works:

- duplicate a branch from a binning/model node
- compare branch outputs side by side
- mark champion/challenger branches
- add constrained tree editing
- eventually add richer DAG/canvas editing if justified

The GUI should make stale state obvious. A user should immediately see which
steps are current, stale due to upstream changes, failed, or not yet run.

## API Surface

The local FastAPI sidecar should expose stable endpoints such as:

- `GET /health`
- `POST /projects`
- `GET /projects/{project_id}`
- `POST /datasets/import`
- `GET /plans/{plan_id}`
- `POST /plans/{plan_id}/steps/{step_id}/params`
- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/steps/{step_id}`
- `GET /artifacts/{artifact_id}`
- `POST /exports/audit-pack`

The API owns validation and state transitions. React should not calculate stale
steps, mutate audit records, or infer model state locally.

## Execution Model

Step execution should not block the GUI.

Early implementation can use a local background worker thread/process behind the
FastAPI sidecar. The UI should poll or subscribe to run status.

Step statuses (stored):

- `not_run`
- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

Staleness is a **computed property** (`is_stale: bool`), not a stored status. A
step is stale when its latest successful execution references upstream step
versions that are no longer current. The API computes `is_stale` on read; the
GUI renders stale markers based on this computed field.

Failure semantics:

- failed steps preserve structured errors
- successful upstream records remain valid
- downstream descendants remain stale/not-run
- partial outputs are either marked incomplete or discarded from normal artifact
  selection
- user-facing errors should include suggested fixes where possible

## Audit And Governance

### Technical Manifest

Every run should produce machine-readable evidence:

- project metadata
- input snapshot metadata
- pathway graph
- plan version
- step parameter values
- step parameter hashes
- input artifact references
- output artifact references
- metrics
- warnings
- errors
- timestamps
- Cardre version
- node type implementation versions
- dependency lockfile hash
- Python/runtime version

### Model Development Report

The governance export should also produce a human-readable model development
report, not only JSON. It should eventually include:

- target definition
- good/bad/indeterminate outcome definitions
- observation window and outcome window
- maturity and representativeness evidence for the chosen window
- population exclusions
- segmentation analysis and segmentation decision rationale
- development sample construction, sampling method, sample weights, and any
  prior-probability/base-rate adjustment
- train/test/OOT split logic
- data dictionary
- missing-value policy by variable
- special-code handling
- variable exclusion reasons
- binning override reasons
- monotonicity exceptions
- zero-cell/sparse-bin handling
- correlation and variable clustering evidence
- coefficient signs and business-sense checks
- gains tables, score distributions, and characteristic reports
- cutoff analysis, approval-rate/bad-rate trade-offs, and policy/override
  strategy assumptions where applicable
- subpopulation impact analysis
- calibration and discrimination metrics
- stability / PSI by segment
- fair-lending/adverse-impact hooks or explicit statement that such review is
  outside the exported pack
- reviewer/sign-off metadata placeholders, even if formal approval workflow is
  outside MVP
- limitations and assumptions
- implementation parity test results

This report is a major product differentiator.

## Reproducibility Contract

Cardre should aim for this contract:

> Two executions with the same input artifacts, step parameters, code version,
> dependency lockfile, and runtime configuration should produce equivalent
> logical artifacts and identical audit records except for run IDs and timestamps.

This is verified by comparing `logical_hash` values of output artifacts across
runs. `physical_hash` (raw byte hash) may differ due to Parquet metadata or
compression variation; `logical_hash` (canonical content hash) is the source of
truth for reproducibility. Both hashes are recorded in the audit trail.

For stochastic steps:

- random seeds must be explicit step properties
- default seeds should be recorded
- unseeded stochastic steps should warn or be disallowed for governance runs

## Performance And Data Volume

MVP performance targets should be explicit. Initial target:

- 1M rows
- 50 variables
- local laptop execution
- profiling under roughly one minute where feasible
- UI remains responsive during execution

Implementation guidance:

- use Parquet internally
- consider DuckDB or Polars early for profiling/aggregation
- avoid pandas-only assumptions for large data
- avoid full artifact copies after metadata-only nodes
- stream/chunk CSV import where possible
- background long-running execution
- apply configurable guards for high-cardinality categoricals before WOE/IV, such
  as max unique categories, rare-level grouping, or explicit exclusion warnings

## Security Model

Cardre is local-first, but credit data is sensitive. The plan should include a
simple security model:

- no cloud upload by default
- no plaintext sensitive values in logs
- local project warning: users are responsible for storing projects on encrypted
  drives or approved secure locations
- audit packs do not include raw row-level customer data by default
- optional PII masking/profiling node later
- audit log integrity checks later
- clear documentation of where raw and transformed data are stored

### Audit Export Data Minimisation

Audit packs should not include raw row-level customer data by default. The
default export contains manifests, summaries, metrics, bin definitions, model
parameters, scorecard specifications, validation evidence, and reports. Row-level
datasets may be exported only by explicit user action.

## Installation And Packaging

Production users should install a single desktop app. They should not need to
install Python, run FastAPI manually, or manage frontend/backend processes.

Packaging workstream:

- Tauri installer
- React production bundle
- bundled Python sidecar executable via PyInstaller or Nuitka
- bundled default node implementations
- installer smoke test
- sidecar health check
- local log collection

Installer smoke test must prove:

1. app launches
2. sidecar starts
3. `/health` passes
4. project can be created/opened
5. dummy node can execute
6. SQLite records and artifact files are written locally

## Open Source Project Direction

Cardre is intended as an open-source scorecard builder.

Needed before broader release:

- license: Apache 2.0 (chosen over MIT for patent grant, important for regulated-industry adoption)
- contribution guide
- code of conduct
- security/data-handling documentation
- reproducible development setup
- clear issue templates for node bugs vs modelling questions

Formal enterprise/hosted/team features are not part of the current product
direction.

## Non-Goals For MVP

The MVP will not support:

- multi-user collaboration
- hosted/cloud execution
- formal plugin packages
- arbitrary freeform DAG editing
- full approval workflow
- PMML/ONNX export
- external object storage
- regulator-ready certification claims

## Revised Phased Plan

### Phase 1A: Engine And Storage Proof (foundation)

- Phase 1 dataset manifest: `docs/data-sources/phase-1-datasets.json`
- Phase 1 public fixtures: UCI German Credit for deterministic smoke tests and
  UCI Default of Credit Card Clients for medium-size import/split/profiling tests
- SQLite schema: plans, plan_versions, steps, runs, run_steps, artifacts
- filesystem artifact store (Parquet + JSON)
- `ProjectStore`, `ArtifactRef`, `PipelinePlan`, `PipelineRun`, `StepSpec`
- DAG-capable `PipelineExecutor`
- internal node registry with dummy/example nodes
- immutable run records, replay from changed step
- artifact physical/logical dual hash
- execution fingerprint and staleness algorithm (step params, parent output
  logical hashes, node implementation version, runtime/dependency metadata)
- model correctness and reproducibility test harness
- cross-stream artifact wiring test (apply step consuming data from split step
  and definitions from a build-stream step)
- build/validate two-stream pathway template as the default plan type

### Phase 1B: Desktop Shell Proof

- Tauri shell scaffold
- React app scaffold with two-stream pathway display
- bundled FastAPI sidecar prototype
- sidecar health check (`/health`)
- create/open local project from GUI
- dummy step execution round-trip
- installer smoke test
- sidecar lifecycle: start, port allocation, log capture, graceful shutdown

### Phase 2: Minimum Viable Scorecard Engine

- import dataset, convert CSV to canonical Parquet
- define population/product/segment metadata
- define good/bad/indeterminate categories, observation/sample window, and
  performance/outcome window
- apply exclusion rules with reason capture
- profile dataset, validate binary target
- maturity/representativeness report for the selected sample window
- development sample definition, including sampling method, sample weights, and
  population bad-rate metadata for prior-probability adjustment
- train/test/OOT split step (produces three role-tagged artifacts)
- missing/outlier treatment and candidate variable derivation
- automatic fine classing (bins all variables on train)
- initial WOE/IV diagnostics (rank variables using automatic bins)
- variable clustering / correlation grouping
- variable selection (filter to strongest candidates)
- manual bin editing / coarse classing (refine bins for selected variables)
- final WOE/IV calculation (using refined bins)
- WOE transform train (apply refined bin definitions)
- logistic regression (fit on WOE-transformed train)
- score scaling
- gains table and characteristic report generation
- apply WOE mapping + apply model to train/test/OOT (scoring/evaluation stream)
- validation metrics by role (AUC, Gini, KS, calibration, PSI)
- cutoff/strategy analysis with approval-rate and bad-rate trade-offs
- basic implementation parity test for Cardre's generated/internal scorer
- basic technical-manifest audit export

### Phase 3: Fixed Pathway Desktop GUI

- local project create/open
- dataset import UI
- fixed pathway node view
- node property editor
- node status/stale markers
- run/replay selected node and descendants
- node output viewers
- manual bin table editor
- WOE/event-rate charts
- audit export UI

### Phase 4: Branching And Champion/Challenger

- duplicate branch from binning/model node
- duplicate branch for segment-specific scorecard experiments
- compare IV/WOE tables
- compare model variables
- compare AUC/Gini/KS/calibration
- compare cutoff/approval-rate/bad-rate trade-offs
- mark champion branch
- export selected branch

### Phase 5: Governance-Quality Report

- model development report template
- target/window/exclusion documentation
- good/bad/indeterminate documentation
- maturity, sample construction, segmentation, and prior-probability adjustment
  documentation
- variable selection rationale
- variable clustering/correlation evidence
- manual override rationale
- gains tables, characteristic reports, cutoff/strategy analysis, and
  subpopulation impact evidence
- policy-rule and override-policy documentation where applicable
- reviewer/sign-off metadata placeholders
- limitations and assumptions
- stability/PSI report
- implementation parity test
- richer HTML/Markdown/PDF export if feasible

### Phase 6: Extensibility

- project-local custom Python nodes
- formalise node compatibility contracts
- entry-point plugin discovery later
- custom output renderers later

### Phase 7: Reject Inference

See full plan: `docs/plans/reject-inference-module-plan.md`

- **Phase 7a — Core infrastructure**: Evidence types (`RejectPopulationConfig`,
  `RejectInferenceResult`), `DefineRejectPopulationNode`, `RejectInferenceNoneNode`
  (explicit documented baseline)
- **Phase 7b — Augmentation method**: `RejectInferenceAugmentationNode`
  (propensity re-weighting/resampling, MAR assumption). Branch point registration
  at `define-reject-population`. MVP ships with one inference method.
- **Phase 7c — Alternative methods**: `RejectInferenceParcelingNode` (prudence
  factors, MNAR), `RejectInferenceSelfLearningNode` (Kozodoi-style iterative
  labeling)
- **Phase 7d — Sensitivity and governance**: `RejectInferenceSensitivityNode`
  (cross-branch comparison, parameter sensitivity, verdict). Report collector
  integration, HTML report section, audit pack inclusion.

## Definition Of Success

### v0 Success

A user can install Cardre as a desktop app, create a local project, load a
binary-target dataset, run a fixed scorecard pathway, inspect profiling,
binning, WOE, model, validation outputs, manually adjust bins, and export a
reproducible audit bundle proving the exact input, parameters, code version,
artifacts, and metrics used.

### v1 Success

A user can duplicate the binning/model branch, compare challenger outputs, mark a
champion branch, and export the chosen branch with its complete audit trail.

### Governance-Ready Success

A user can export a human-readable model development report with enough evidence
for an internal model-risk/governance team to review the scorecard development
journey, modelling choices, validation results, limitations, and implementation
parity.

## Open Engineering Decisions

These decisions affect implementation but do not change the architectural model
and can be made during development:

- PyInstaller vs Nuitka for sidecar bundling (start with PyInstaller)
- Polars vs DuckDB vs pandas for tabular operations (Polars recommended for core
  transforms, DuckDB for profiling/aggregation queries)
- Minimum manual binning UX details for v0 (table-based merge/group with
  before/after charts, no drag-and-drop)
- Which validation metrics are mandatory in the first governance-quality report
