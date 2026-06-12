# Plan Review 009: Final Round Structural Rigor Review

This third version is a mature, tightly-scoped product blueprint. It takes the strong ideas from earlier drafts, adds structural rigor (especially around leakage prevention, artifact hashing, and two-stream execution), and makes concrete engineering decisions that a small team can execute. The plan is now ready to guide implementation.

---

## What makes v3 exceptional

### Leakage prevention is now structural, not advisory.

The two-stream pathway (build on train, validate on test/OOT) with enforced artifact roles per node type (fit, apply, refinement, selection) is the best design choice in the document. The executor can reject a plan graph that accidentally feeds test data into a binning step. This turns a common subtle bug into a hard failure, which governance teams will love.

### Artifact hashing is done correctly.

Dual physical_hash (raw bytes) and logical_hash (canonical content) solves the reproducibility-comparison problem that plagues Parquet-based pipelines. The logical hash definition is specific enough to implement and test, and it avoids false staleness from compression metadata changes.

### Staleness is a computed property, not a stored status.

Deriving is_stale from upstream run version comparison means the database never contains contradictory state. A step that was run, then had an upstream parameter change, is immediately stale on the next read. This keeps the UI and audit trail consistent by design.

### Node type vs. step distinction is now explicit.

This clears up a source of confusion from earlier drafts and makes the registry, plan model, and execution model much cleaner. It also sets the stage for plugin nodes later.

### Phases are split into 1A (engine proof) and 1B (desktop shell proof).

This de-risks the biggest unknowns in parallel: the reproducibility model on one side, and the Tauri+sidecar lifecycle on the other. If one fails, the other can still proceed or be adjusted without throwing away the whole project.

### The license decision is made (Apache 2.0) and the reasoning is documented.

For a tool aimed at regulated industries, the patent grant matters. Closing this early removes a barrier for enterprise adoption.

---

## Remaining subtle points to watch during implementation

These are not flaws in the plan; they are areas where the design will meet reality and require careful engineering.

### 1. Cross-stream artifact wiring

The two-stream diagram shows the validate stream “using build-stream bin definitions” and “using build-stream model coefficients”, but the plan’s DAG model uses parent_step_ids to link steps. The apply-woe step will need parent_step_ids that point to both the split step (for test/oot data) and the manual binning step (for the bin definition artifact). The executor must understand that a step can consume multiple artifacts from different upstream steps and validate each artifact’s role separately. This is straightforward but worth an explicit test case in Phase 1A: an apply step that reads a data artifact from one parent and a definition artifact from another.

### 2. Staleness computation granularity

The definition says a step is stale when “its latest successful execution references upstream step versions that are no longer current.” The current version of an upstream step is defined by the latest plan version’s params_hash, but staleness should also consider whether that upstream step has produced a new output (even with the same params) due to a change further up. If step A is re-run and produces a different output (because its own upstream changed), step B—which depends on A’s output—must become stale even though A’s params didn’t change. The staleness check must compare input artifact logical hashes from the last run against current upstream outputs, not just parameter versions. The team will likely catch this when writing the is_stale logic, but the plan text could be slightly more precise.

### 3. Manual binning UX state management

Table-based merge/group editing (as decided) still requires handling undo, reordering, and validation feedback in real time. The bin editor will need to load a variable’s auto-bins, apply user overrides locally, and show WOE/event-rate charts that update on each edit. This is a non-trivial React state problem, especially when multiple variables are edited in a session. A small prototype of this component before Phase 3 would be valuable.

### 4. Desktop sidecar robustness

The Tauri sidecar lifecycle is well-described, but the real pain points (antivirus interference, port conflicts on corporate machines, Python DLL loading on Windows) will surface in the first few user installs. The installer smoke test is essential, but consider also a silent diagnostic report the app can generate to aid support. The plan’s log capture is a good start.

### 5. Large categorical variables in WOE/IV

The plan mentions 1M rows and 50 variables, but doesn’t discuss high-cardinality categoricals (e.g., a variable with 10,000 unique levels). Automatic fine classing on such a variable can be slow or produce memory pressure. The engine should have a pre-grouping step or a configurable max-categories guard. This can be addressed during implementation but is worth flagging now.

---

## Verdict

The Cardre plan is now a tight, defensible product specification. It has made all the hard calls: desktop-only, Tauri+FastAPI, two-stream enforcement, logical hashing, computed staleness, fixed pathway first, manual binning as core, and Apache 2.0. There are no fundamental gaps remaining.

The most significant risk is still the desktop packaging and sidecar lifecycle across platforms, but the plan acknowledges this and splits it into its own proof phase. If Phase 1B succeeds, the rest is domain logic and careful UI work.

This document is ready to move from planning to the first code commits.
