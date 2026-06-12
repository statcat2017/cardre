# Plan Review 002: MVP Sequencing And Product Scope Review

I downloaded/read it. Overall: the idea is strong and genuinely useful, especially the “PowerBI transform flow, but for scorecard modelling” concept. The best part is the separation between GUI, application services, node engine, scorecard domain functions, and storage; that gives you a real chance of building something auditable rather than just a nice notebook wrapper. The plan’s core principles — immutable input snapshot, node-based DAG/tree, non-mutating audit history, GUI-independent engine — are exactly the right foundations.

## My main critique

The plan is architecturally mature but MVP-overloaded. It tries to solve six hard problems at once:

1. a reproducible pipeline engine
2. a credit scorecard modelling library
3. a GUI workflow builder
4. branch/champion/challenger comparison
5. governance/audit pack generation
6. plugin architecture

That is too much for a first working version. The most important change I’d make is: build the boring reproducible engine and one narrow scorecard path first, then add the pretty branching UI later.

The killer MVP should be:

```text
import dataset
-> profile
-> validate binary target
-> train/test split
-> automatic binning
-> WOE transform
-> logistic regression
-> score scaling
-> validation metrics
-> audit export
```

Then add branch comparison once the linear pathway is solid.

## What’s good

The product positioning is good. Existing Python tools already cover pieces of this problem — for example OptBinning focuses on optimal binning, scorecardpy provides common scorecard development functions, and skorecard is a scikit-learn-compatible scorecard package. Cardre’s differentiator should therefore not be “we can calculate WOE”. It should be:

> “We make the modelling journey visible, branchable, reproducible, and exportable for audit.”

That is a much sharper pitch.

The audit model is also directionally right. Recording node IDs, implementation versions, params, parent IDs, input/output hashes, warnings, timestamps, and status is exactly the sort of evidence you need for model-risk review.

The package split is sensible too: nodes/ adapting GUI-configured steps into pure scorecard/ functions is the right boundary. The plan explicitly says the scorecard package should remain UI-free and storage-free, which is very important.

## Biggest risks

### 1. “Governance-ready” is under-specified

The plan talks about audit packs, manifests, warnings, and approvals, but governance-ready scorecard documentation needs more than replay metadata. The export pack should eventually include:

- target definition and performance window
- observation window / outcome window
- population exclusions
- train/test/OOT split logic
- data dictionary
- missing-value policy by variable
- variable exclusion reasons
- binning override reasons
- monotonicity exceptions
- zero-cell / sparse-bin handling
- correlation and variable clustering evidence
- coefficient signs and business-sense checks
- calibration and discrimination metrics
- stability / PSI by segment
- limitations and assumptions
- implementation parity test between Python/SQL score output

The plan has some of these pieces scattered around, but I would make them explicit product requirements.

### 2. Manual binning is the real UX problem

The plan correctly lists manual bin editing, coarse classing, and bin overrides. But this is probably the hardest part of the application, not a small feature. Scorecard modellers often need to merge bins, force missing values into separate bins, override automatic groupings, preserve business logic, and explain why.

So the MVP should decide:

Either automatic-only binning for v0, with no claim of governance readiness,
or make manual bin editing a first-class workflow from the beginning.

A GUI scorecard builder without good manual bin/coarse-class editing will feel incomplete to actual credit-risk users.

### 3. Streamlit is fine, but only as a prototype

Using Streamlit first is pragmatic, and the plan says it is mainly for speed. That is fine. But the product’s core UX — pathway canvas, stale nodes, branch comparison, manual bin editing — will eventually fight Streamlit.

I’d treat Streamlit as:

```text
Phase 0/1: internal dogfood GUI
Phase 2+: replace with React + FastAPI once engine stabilises
```

Do not let Streamlit design constraints leak into the engine.

### 4. DAG/tree ambiguity should be resolved early

The open question about strict trees vs general DAGs is important. My recommendation:

- Internal model: DAG.
- Initial GUI: tree-like presentation.
- Rule: every node declares typed artifact inputs and outputs.
- Execution: topological order based on artifact dependencies.

That prevents painting yourself into a corner. Scorecard workflows naturally become DAG-like once you have shared datasets, multiple validation nodes, champion/challenger comparisons, export nodes, and monitoring nodes.

### 5. Artifact hashing sounds easy but can become messy

“Artifacts should be content-addressed” is right. But dataframe artifacts are not always byte-stable. CSV ordering, parquet metadata, float formatting, categorical ordering, timezone handling, and index preservation can all create false hash differences.

I’d define early:

Canonical artifact hash = hash of:

- artifact type
- schema
- ordered column names
- ordered row identity or stable row order
- canonical serialized values
- null representation
- relevant metadata

Do not rely blindly on raw file bytes if you want reproducibility.

### 6. Plugins are too early

The plugin idea is good, but I would defer it. The node API will change a lot once you actually build profiling, binning, WOE, model fitting, validation, and export. If you formalise plugins too early, you’ll freeze the wrong abstraction.

Better approach:

```text
v0: internal node registry only
v1: custom Python node inside project
v2: pyproject entry-point plugins
```

## Suggested revised implementation order

### Phase 1: Reproducible local engine, no GUI

Build:

```text
ProjectStore
ArtifactRef
PipelinePlan
PipelineRun
StepSpec
NodeResult
PipelineExecutor
NodeRegistry
```

Add only dummy/example nodes first. Prove that:

- runs are immutable
- changed params create new run records
- downstream cache invalidation works
- artifacts are hashed
- audit JSON can reconstruct what happened

### Phase 2: Minimal scorecard CLI/API

Add real nodes:

```text
import_dataset
profile_dataset
validate_binary_target
train_test_split
automatic_binning
woe_transform
fit_logistic_regression
scale_scorecard
validate_scorecard
export_audit_pack
```

Do this through Python API or CLI first, not GUI.

### Phase 3: Basic Streamlit GUI

Only after the engine works:

```text
select project
import dataset
view fixed pathway
edit node parameters
run pathway
view node outputs
export pack
```

Avoid a freeform pathway canvas at first. Use a fixed template scorecard pathway.

### Phase 4: Branching

Then add:

```text
duplicate branch from binning step
compare IV/WOE tables
compare selected variables
compare AUC/Gini/KS
mark champion
```

This is where the product starts feeling differentiated.

### Phase 5: Manual bin editing

This is the point where real credit-risk users will care.

Add:

```text
bin table editor
merge/split bins
special/missing bin handling
override reason required
monotonicity warning
zero-cell warning
before/after WOE chart
```

### Phase 6: Governance pack

Turn the export from “technical replay manifest” into a proper model document.

## Specific changes I’d make to the plan text

I’d add a section called “Non-goals for MVP”:

MVP will not support:

- multi-user collaboration
- plugin nodes
- reject inference
- PMML/ONNX
- generic DAG editing
- background execution
- approval workflow
- external object storage

I’d also change the MVP definition of success. Current success includes two branches, fitting/scaling, exporting audit pack, and rerunning earlier nodes. That is good, but probably too ambitious for first useful version.

I’d make v0 success:

> A user can load a binary-target dataset, run a fixed scorecard template,
> inspect binning/WOE/model/validation outputs, and export a reproducible
> audit bundle proving the exact input, parameters, code version, artifacts,
> and metrics used.

Then v1 success:

> A user can duplicate the binning/model branch, compare challenger outputs,
> mark a champion, and export the chosen branch.

## Domain features I would add explicitly

The plan should mention these now, even if later:

- train/test/OOT split support
- sample weights
- special codes, missing values, and “unknown” handling
- zero-cell smoothing
- perfect separation detection
- minimum bin size rules
- monotonic WOE constraints
- coefficient sign checks
- high-correlation variable clustering
- variable exclusion reason log
- scorecard implementation parity tests
- SQL scoring dialect strategy
- model monitoring pack: PSI, drift, calibration over time
- reject inference as a late-stage optional module

## Verdict

This is a very good product plan, but it needs sharper sequencing. The architecture is strong; the danger is trying to build a full Alteryx/PowerBI-style visual modelling platform before proving the scorecard engine and audit trail.

My recommendation: make Cardre’s first claim “reproducible auditable scorecard runs”, not “full GUI scorecard builder”. Once that core is solid, the GUI and branching workflow become much easier — and much more credible.
